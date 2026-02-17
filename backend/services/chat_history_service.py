"""
聊天室历史记忆服务
负责每个 Session 的对话历史读写与管理
"""

import os
import json
import logging
import threading
from datetime import datetime
from typing import List, Dict

import config as app_config

logger = logging.getLogger(__name__)


class ChatHistoryService:
    """管理每个 Session 的对话历史 (JSON 文件持久化)"""

    HISTORY_FILENAME = "chat_history.json"
    MAX_HISTORY_FOR_LLM = 10  # 给 LLM 的最大历史条数

    def __init__(self, base_dir: str = None):
        self.base_dir = base_dir or app_config.BASE_STORAGE_DIR
        self._locks: Dict[str, threading.Lock] = {}  # per-session locks
        self._locks_guard = threading.Lock()  # guard for _locks dict

    def _get_lock(self, session_id: str) -> threading.Lock:
        """取得指定 session 的寫入鎖 (lazy init)"""
        with self._locks_guard:
            if session_id not in self._locks:
                self._locks[session_id] = threading.Lock()
            return self._locks[session_id]

    def _get_history_path(self, session_id: str) -> str:
        """取得指定 session 的历史文件路径"""
        safe_id = "".join(
            c for c in session_id if c.isalnum() or c in ("-", "_")
        ).strip()
        if not safe_id:
            safe_id = "default"
        return os.path.join(self.base_dir, safe_id, self.HISTORY_FILENAME)

    def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        analysis_knowledge: str = None,
    ) -> None:
        """追加一条消息到历史文件 (per-session 锁保护，防並發寫入覆蓋)"""
        lock = self._get_lock(session_id)
        with lock:
            history_path = self._get_history_path(session_id)
            os.makedirs(os.path.dirname(history_path), exist_ok=True)

            # 读取现有历史
            records = self._load_raw(history_path)

            # 追加新记录
            record = {
                "timestamp": datetime.now().isoformat(),
                "role": role,
                "content": content[:5000],  # 限制单条长度
            }
            if analysis_knowledge:
                record["analysis_knowledge"] = analysis_knowledge[:10000]

            records.append(record)

            # 写回文件
            try:
                with open(history_path, "w", encoding="utf-8") as f:
                    json.dump(records, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"[ChatHistory] Failed to save: {e}")

    def load_history(self, session_id: str, last_n: int = None) -> List[Dict]:
        """读取最近 N 条历史记录"""
        if last_n is None:
            last_n = self.MAX_HISTORY_FOR_LLM
        history_path = self._get_history_path(session_id)
        records = self._load_raw(history_path)
        return records[-last_n:] if len(records) > last_n else records

    def load_history_as_text(self, session_id: str, last_n: int = None) -> str:
        """读取历史并格式化为 LLM 可用的文本"""
        records = self.load_history(session_id, last_n)
        if not records:
            return ""

        parts = []
        for r in records:
            role = r.get("role", "unknown")
            content = r.get("content", "")
            if role == "user":
                parts.append(f"User: {content}")
            elif role == "assistant":
                parts.append(f"Assistant: {content[:1000]}")
        return "\n".join(parts)

    def list_sessions(self) -> List[Dict]:
        """列出所有有对话历史的 session"""
        sessions = []
        if not os.path.exists(self.base_dir):
            return sessions

        for name in os.listdir(self.base_dir):
            session_dir = os.path.join(self.base_dir, name)
            if not os.path.isdir(session_dir):
                continue
            history_path = os.path.join(session_dir, self.HISTORY_FILENAME)
            if os.path.exists(history_path):
                info = self._get_session_info_from_file(name, history_path)
                sessions.append(info)
            else:
                # session 目录存在但没有 history — 检查是否有上传文件
                uploads_dir = os.path.join(session_dir, "uploads")
                if os.path.exists(uploads_dir) and os.listdir(uploads_dir):
                    sessions.append(
                        {
                            "session_id": name,
                            "message_count": 0,
                            "created_at": None,
                            "last_active": None,
                            "title": "新對話",
                        }
                    )

        # 按最后活跃时间排序
        sessions.sort(key=lambda s: s.get("last_active") or "", reverse=True)
        return sessions

    def delete_history(self, session_id: str) -> bool:
        """删除指定 session 的对话历史"""
        history_path = self._get_history_path(session_id)
        if os.path.exists(history_path):
            os.remove(history_path)
            return True
        return False

    def _load_raw(self, path: str) -> List[Dict]:
        """从文件加载原始记录列表"""
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"[ChatHistory] Failed to load {path}: {e}")
        return []

    def _get_session_info_from_file(self, session_id: str, history_path: str) -> Dict:
        """从历史文件提取 session 元信息"""
        records = self._load_raw(history_path)
        title = "新對話"
        created_at = None
        last_active = None

        if records:
            # 用第一条用户消息作为标题
            for r in records:
                if r.get("role") == "user":
                    title = r.get("content", "")[:30]
                    break
            created_at = records[0].get("timestamp")
            last_active = records[-1].get("timestamp")

        return {
            "session_id": session_id,
            "message_count": len(records),
            "created_at": created_at,
            "last_active": last_active,
            "title": title,
        }
