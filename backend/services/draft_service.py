"""
暫存 (Draft) 管理服務
負責暫存檔的儲存、讀取與刪除
"""

import os
import json
from typing import List, Dict, Any
from datetime import datetime
from fastapi import HTTPException


import config as app_config


class DraftService:
    def __init__(self, base_dir: str = None):
        self.base_dir = base_dir or app_config.BASE_STORAGE_DIR

    def get_user_draft_dir(self, session_id: str) -> str:
        """取得特定使用者的暫存目錄"""
        safe_session_id = "".join(
            [c for c in session_id if c.isalnum() or c in ("-", "_")]
        ).strip()
        if not safe_session_id:
            safe_session_id = "default"

        draft_dir = os.path.join(self.base_dir, safe_session_id, "drafts")
        os.makedirs(draft_dir, exist_ok=True)
        return draft_dir

    async def save_draft(
        self, draft: Dict[str, Any], session_id: str = "default"
    ) -> Dict[str, Any]:
        """儲存暫存檔"""
        try:
            draft_dir = self.get_user_draft_dir(session_id)
            # 使用 timestamp 或是 draft id 作為檔名，並確保安全性
            draft_id = draft.get("id", f"draft_{int(datetime.now().timestamp())}")
            safe_draft_id = "".join(
                [c for c in str(draft_id) if c.isalnum() or c in ("-", "_")]
            )
            file_path = os.path.join(draft_dir, f"{safe_draft_id}.json")

            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(draft, f, ensure_ascii=False, indent=2)

            return {
                "status": "success",
                "draft_id": safe_draft_id,
                "message": "暫存已成功儲存至伺服器",
            }
        except Exception as e:
            raise HTTPException(500, detail=f"Save draft failed: {str(e)}")

    async def list_drafts(
        self, session_id: str = "default"
    ) -> Dict[str, List[Dict[str, Any]]]:
        """列出所有暫存檔"""
        try:
            draft_dir = self.get_user_draft_dir(session_id)
            drafts = []
            if os.path.exists(draft_dir):
                for filename in os.listdir(draft_dir):
                    if filename.endswith(".json"):
                        file_path = os.path.join(draft_dir, filename)
                        try:
                            with open(file_path, "r", encoding="utf-8") as f:
                                data = json.load(f)
                                stats = os.stat(file_path)
                                data["server_timestamp"] = stats.st_mtime * 1000
                                drafts.append(data)
                        except Exception:
                            continue

            # 依時間排序 (最新在前)
            drafts.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
            return {"drafts": drafts}
        except Exception as e:
            raise HTTPException(500, detail=f"List drafts failed: {str(e)}")

    async def delete_draft(
        self, draft_id: str, session_id: str = "default"
    ) -> Dict[str, str]:
        """刪除暫存檔"""
        try:
            draft_dir = self.get_user_draft_dir(session_id)
            safe_draft_id = "".join(
                [c for c in str(draft_id) if c.isalnum() or c in ("-", "_")]
            )
            file_path = os.path.join(draft_dir, f"{safe_draft_id}.json")
            if os.path.exists(file_path):
                os.remove(file_path)
                return {"status": "success", "message": "暫存已刪除"}
            else:
                raise HTTPException(404, detail="Draft not found")
        except Exception as e:
            raise HTTPException(500, detail=f"Delete draft failed: {str(e)}")
