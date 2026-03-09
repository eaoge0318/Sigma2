"""
聊天室历史记忆服务
负责每个 Session 的对话历史读写与管理
聊天記錄存放於: workspace/{session_id}/analysis/{file_id}/chat_history.json
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
    CONTEXT_FILENAME = "analysis_context.json"

    def __init__(self, base_dir: str = None):
        self.base_dir = base_dir or app_config.BASE_STORAGE_DIR
        os.makedirs(self.base_dir, exist_ok=True)
        self._locks: Dict[str, threading.Lock] = {}  # per-session locks
        self._locks_guard = threading.Lock()  # guard for _locks dict

    def _get_lock(self, key: str) -> threading.Lock:
        """取得寫入鎖 (lazy init)"""
        with self._locks_guard:
            if key not in self._locks:
                self._locks[key] = threading.Lock()
            return self._locks[key]

    def _safe_id(self, raw_id: str) -> str:
        """清理 ID 為安全的目錄名"""
        safe = "".join(c for c in raw_id if c.isalnum() or c in ("-", "_")).strip()
        return safe or "default"

    # ── Path helpers ──────────────────────────────────────────

    def _get_history_path(
        self, session_id: str, file_id: str = "", conversation_id: str = ""
    ) -> str:
        """
        取得聊天記錄路徑。
        統一格式: workspace/{session_id}/analysis/{file_id}/chat_history.json
        多對話格式: workspace/{session_id}/analysis/{file_id}/chat_history_{conversation_id}.json
        無 file_id 時使用 '_default' 作為 file_id
        """
        safe_sid = self._safe_id(session_id)
        safe_fid = self._safe_id(file_id) if file_id else "_default"
        # 非 default 的 conversation_id 使用獨立檔案
        if conversation_id and conversation_id != "default":
            filename = f"chat_history_{self._safe_id(conversation_id)}.json"
        else:
            filename = self.HISTORY_FILENAME
        return os.path.join(self.base_dir, safe_sid, "analysis", safe_fid, filename)

    def _get_context_path(self, session_id: str, file_id: str = "") -> str:
        """
        取得分析上下文路徑。
        統一格式: workspace/{session_id}/analysis/{file_id}/analysis_context.json
        無 file_id 時使用 '_default' 作為 file_id
        """
        safe_sid = self._safe_id(session_id)
        safe_fid = self._safe_id(file_id) if file_id else "_default"
        return os.path.join(
            self.base_dir, safe_sid, "analysis", safe_fid, self.CONTEXT_FILENAME
        )

    # ── Save / Load Messages ────────────────────────────────

    def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        analysis_knowledge: str = None,
        file_id: str = "",
        conversation_id: str = "",
    ) -> None:
        """追加一条消息到历史文件"""
        lock_key = (
            f"{session_id}_{file_id}_{conversation_id}" if file_id else session_id
        )
        lock = self._get_lock(lock_key)
        with lock:
            history_path = self._get_history_path(session_id, file_id, conversation_id)
            os.makedirs(os.path.dirname(history_path), exist_ok=True)

            records = self._load_raw(history_path)

            record = {
                "timestamp": datetime.now().isoformat(),
                "role": role,
                "content": content[:5000],
            }
            if analysis_knowledge:
                record["analysis_knowledge"] = analysis_knowledge[:10000]

            records.append(record)

            try:
                with open(history_path, "w", encoding="utf-8") as f:
                    json.dump(records, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"[ChatHistory] Failed to save: {e}")

    def load_history(
        self,
        session_id: str,
        max_entries: int = None,
        file_id: str = "",
        conversation_id: str = "",
    ) -> List[Dict]:
        """读取最近 N 条历史记录"""
        history_path = self._get_history_path(session_id, file_id, conversation_id)
        records = self._load_raw(history_path)
        if max_entries is None:
            return records
        return records[-max_entries:] if len(records) > max_entries else records

    def load_history_as_text(
        self,
        session_id: str,
        max_entries: int = None,
        file_id: str = "",
        conversation_id: str = "",
    ) -> str:
        """加载对话历史并转为文本 (给 LLM context 用)"""
        history_path = self._get_history_path(session_id, file_id, conversation_id)
        records = self._load_raw(history_path)

        if max_entries is None:
            max_entries = self.MAX_HISTORY_FOR_LLM

        recent = records[-max_entries:] if len(records) > max_entries else records

        parts = []
        for r in recent:
            role = r.get("role", "unknown")
            content = r.get("content", "")
            if role == "user":
                parts.append(f"User: {content}")
            elif role == "assistant":
                parts.append(f"Assistant: {content[:1000]}")
        return "\n".join(parts)

    # ── List / Delete Sessions ──────────────────────────────

    def list_sessions(self, user_id: str = None) -> List[Dict]:
        """
        列出所有有聊天記錄的聊天室。
        掃描 workspace/{session_id}/analysis/{file_id}/chat_history.json
        """
        sessions = []
        if not os.path.exists(self.base_dir):
            logger.warning(f"[ChatHistory] base_dir does not exist: {self.base_dir}")
            return sessions

        for session_name in os.listdir(self.base_dir):
            session_dir = os.path.join(self.base_dir, session_name)
            if not os.path.isdir(session_dir):
                continue

            # 嚴格 Session 隔離: 精確匹配 session_id, 不跨 session 顯示
            if user_id and session_name != user_id:
                continue

            analysis_dir = os.path.join(session_dir, "analysis")
            if not os.path.isdir(analysis_dir):
                continue

            for file_id_name in os.listdir(analysis_dir):
                chatroom_dir = os.path.join(analysis_dir, file_id_name)
                if not os.path.isdir(chatroom_dir):
                    continue
                # 掃描所有 chat_history*.json (支援多對話)
                for entry in os.listdir(chatroom_dir):
                    if not entry.startswith("chat_history") or not entry.endswith(
                        ".json"
                    ):
                        continue
                    history_path = os.path.join(chatroom_dir, entry)
                    # 解析 conversation_id
                    if entry == self.HISTORY_FILENAME:
                        conv_id = "default"
                    else:
                        # chat_history_{conv_id}.json -> conv_id
                        conv_id = entry.replace("chat_history_", "").replace(
                            ".json", ""
                        )
                    info = self._get_session_info_from_file(
                        session_name, history_path, file_id_name
                    )
                    info["conversation_id"] = conv_id
                    # 同時讀取 summary.json 取得關聯檔案名稱
                    summary_path = os.path.join(chatroom_dir, "summary.json")
                    if os.path.exists(summary_path):
                        try:
                            with open(summary_path, "r", encoding="utf-8") as sf:
                                summary_data = json.load(sf)
                            if isinstance(summary_data, dict):
                                info["filename"] = summary_data.get("filename", "")
                        except Exception:
                            pass
                    sessions.append(info)

            # [REMOVED] 舊格式向下相容已移除，統一使用 analysis/{file_id}/ 格式

        logger.info(
            f"[ChatHistory] list_sessions(user_id={user_id}) found {len(sessions)} session(s)"
        )
        sessions.sort(key=lambda s: s.get("last_active") or "", reverse=True)
        return sessions

    def delete_history(self, session_id: str, file_id: str = "") -> bool:
        """删除指定聊天室的历史"""
        history_path = self._get_history_path(session_id, file_id)
        if os.path.exists(history_path):
            os.remove(history_path)
            return True
        return False

    # ── Analysis Context 持久化 ─────────────────────────────

    def save_analysis_context(
        self, session_id: str, context_data: Dict, file_id: str = ""
    ) -> None:
        """
        儲存 V2 分析的結構化結果。
        每次分析完成時覆寫，保留最新一次分析的完整摘要。
        """
        lock_key = f"ctx_{session_id}_{file_id}" if file_id else f"ctx_{session_id}"
        lock = self._get_lock(lock_key)
        with lock:
            ctx_path = self._get_context_path(session_id, file_id)
            os.makedirs(os.path.dirname(ctx_path), exist_ok=True)
            payload = {
                "timestamp": datetime.now().isoformat(),
                **context_data,
            }
            try:
                with open(ctx_path, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
                logger.info(f"[ChatHistory] Saved analysis context for {session_id}")
            except Exception as e:
                logger.error(f"[ChatHistory] Failed to save analysis context: {e}")

    def load_analysis_context(self, session_id: str, file_id: str = "") -> Dict:
        """讀取最新的分析上下文。回傳空 dict 如果不存在。"""
        ctx_path = self._get_context_path(session_id, file_id)
        if not os.path.exists(ctx_path):
            return {}
        try:
            with open(ctx_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.warning(f"[ChatHistory] Failed to load analysis context: {e}")
            return {}

    # ── Analysis State 持久化 (V2 Orchestrator State Machine) ──

    STATE_FILENAME = "analysis_state.json"

    def _get_state_path(self, session_id: str, file_id: str = "") -> str:
        """取得分析狀態持久化路徑。"""
        safe_sid = self._safe_id(session_id)
        if file_id:
            safe_fid = self._safe_id(file_id)
            return os.path.join(
                self.base_dir, safe_sid, "analysis", safe_fid, self.STATE_FILENAME
            )
        return os.path.join(self.base_dir, safe_sid, self.STATE_FILENAME)

    def save_analysis_state(
        self, session_id: str, file_id: str, state_dict: Dict
    ) -> None:
        """
        儲存 V2 Orchestrator 的完整分析狀態。
        在 _finalize 時呼叫，確保關閉視窗後可恢復。
        """
        lock_key = f"state_{session_id}_{file_id}"
        lock = self._get_lock(lock_key)
        with lock:
            state_path = self._get_state_path(session_id, file_id)
            os.makedirs(os.path.dirname(state_path), exist_ok=True)
            payload = {
                "timestamp": datetime.now().isoformat(),
                "session_id": session_id,
                "file_id": file_id,
                **state_dict,
            }
            try:
                with open(state_path, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
                logger.info(
                    f"[ChatHistory] Saved analysis state for "
                    f"{session_id}:{file_id} ({len(json.dumps(payload, default=str)) // 1024}KB)"
                )
            except Exception as e:
                logger.error(f"[ChatHistory] Failed to save analysis state: {e}")

    def load_analysis_state(self, session_id: str, file_id: str = "") -> Dict:
        """
        讀取持久化的分析狀態。回傳空 dict 如果不存在。
        """
        state_path = self._get_state_path(session_id, file_id)
        if not os.path.exists(state_path):
            return {}
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    logger.info(
                        f"[ChatHistory] Loaded analysis state for "
                        f"{session_id}:{file_id}"
                    )
                    return data
                return {}
        except Exception as e:
            logger.warning(f"[ChatHistory] Failed to load analysis state: {e}")
            return {}

    # ── Internal helpers ────────────────────────────────────

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

    def _get_session_info_from_file(
        self, session_id: str, history_path: str, file_id: str = ""
    ) -> Dict:
        """从历史文件提取 session 元信息"""
        records = self._load_raw(history_path)
        title = ""
        created_at = None
        last_active = None

        if records:
            for r in records:
                if r.get("role") == "user":
                    title = r.get("content", "")[:30]
                    break
            created_at = records[0].get("timestamp")
            last_active = records[-1].get("timestamp")

        # 如果沒有 user 訊息，嘗試從 summary.json 取得檔案名稱作為標題
        if not title and file_id:
            chatroom_dir = os.path.dirname(history_path)
            summary_path = os.path.join(chatroom_dir, "summary.json")
            if os.path.exists(summary_path):
                try:
                    with open(summary_path, "r", encoding="utf-8") as sf:
                        summary_data = json.load(sf)
                    if isinstance(summary_data, dict):
                        fname = summary_data.get("filename", "")
                        if fname:
                            title = fname[:40]
                except Exception:
                    pass

        if not title:
            title = "新對話"

        info = {
            "session_id": session_id,
            "message_count": len(records),
            "created_at": created_at,
            "last_active": last_active,
            "title": title,
        }
        if file_id:
            info["file_id"] = file_id
        return info
