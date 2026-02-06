"""
檔案管理服務
負責檔案的上傳、刪除、列表等操作
"""

import os
import shutil
from typing import List, Dict, Any
from datetime import datetime
from fastapi import UploadFile, HTTPException


import config as app_config


class FileService:
    """檔案管理服務，實作多租戶隔離"""

    def __init__(self, base_dir: str = None):
        self.base_dir = base_dir or app_config.BASE_STORAGE_DIR
        os.makedirs(self.base_dir, exist_ok=True)

    def get_user_path(self, session_id: str, category: str = "uploads") -> str:
        """
        取得特定使用者的分類目錄路徑
        category 可以是: uploads, drafts, configs, logs, bundles, cache
        """
        # 安全過濾 session_id
        safe_session_id = "".join(
            [c for c in session_id if c.isalnum() or c in ("-", "_")]
        ).strip()
        if not safe_session_id:
            safe_session_id = "default"

        user_dir = os.path.join(self.base_dir, safe_session_id, category)
        os.makedirs(user_dir, exist_ok=True)
        return user_dir

    def get_user_upload_dir(self, session_id: str) -> str:
        """相容性方法：取得上傳目錄"""
        return self.get_user_path(session_id, "uploads")

    async def upload_file(
        self, file: UploadFile, session_id: str = "default"
    ) -> Dict[str, Any]:
        """上傳檔案"""
        try:
            upload_dir = self.get_user_upload_dir(session_id)
            # 安全檢查檔名
            filename = os.path.basename(file.filename)
            file_path = os.path.join(upload_dir, filename)

            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)

            return {
                "status": "success",
                "filename": filename,
                "message": f"檔案 {filename} 上傳成功",
                "session_id": session_id,
            }
        except Exception as e:
            raise HTTPException(500, detail=f"Upload failed: {str(e)}")

    async def list_files(
        self, session_id: str = "default"
    ) -> Dict[str, List[Dict[str, Any]]]:
        """列出已上傳的檔案"""
        try:
            upload_dir = self.get_user_upload_dir(session_id)
            files = []
            if os.path.exists(upload_dir):
                for filename in os.listdir(upload_dir):
                    file_path = os.path.join(upload_dir, filename)
                    if os.path.isfile(file_path):
                        try:
                            stats = os.stat(file_path)
                            files.append(
                                {
                                    "filename": filename,
                                    "size": stats.st_size,
                                    "uploaded_at": datetime.fromtimestamp(
                                        stats.st_mtime
                                    ).strftime("%Y-%m-%d %H:%M:%S"),
                                }
                            )
                        except OSError:
                            continue
            return {"files": files}
        except Exception as e:
            raise HTTPException(500, detail=f"List files failed: {str(e)}")

    async def delete_file(
        self, filename: str, session_id: str = "default"
    ) -> Dict[str, str]:
        """刪除檔案"""
        try:
            if not filename or ".." in filename:
                raise HTTPException(400, detail="Invalid filename")

            upload_dir = self.get_user_upload_dir(session_id)
            file_path = os.path.join(upload_dir, os.path.basename(filename))
            if os.path.exists(file_path):
                os.remove(file_path)
                return {"status": "success", "message": f"檔案 {filename} 已刪除"}
            else:
                raise HTTPException(404, detail="File not found")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(500, detail=f"Delete failed: {str(e)}")

    async def view_file(
        self,
        filename: str,
        page: int = 1,
        page_size: int = 50,
        session_id: str = "default",
    ) -> Dict[str, Any]:
        """預覽檔案內容"""
        try:
            if not filename or ".." in filename:
                raise HTTPException(400, detail="Invalid filename")

            upload_dir = self.get_user_upload_dir(session_id)
            file_path = os.path.join(upload_dir, os.path.basename(filename))
            if not os.path.exists(file_path):
                raise HTTPException(404, detail="File not found")

            total_lines = 0
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                for _ in f:
                    total_lines += 1

            start_line = (page - 1) * page_size
            content_lines = []
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                for _ in range(start_line):
                    if not f.readline():
                        break

                for _ in range(page_size):
                    line = f.readline()
                    if not line:
                        break
                    content_lines.append(line)

            return {
                "filename": filename,
                "content": "".join(content_lines),
                "page": page,
                "page_size": page_size,
                "total_lines": total_lines,
            }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(500, detail=f"View failed: {str(e)}")

    def get_file_path(self, filename: str, session_id: str = "default") -> str:
        """取得檔案的完整路徑"""
        upload_dir = self.get_user_upload_dir(session_id)
        return os.path.join(upload_dir, os.path.basename(filename))

    async def clear_user_workspace(self, session_id: str) -> Dict[str, str]:
        """清理使用者的工作空間 (刪除所有資料夾)"""
        try:
            safe_session_id = "".join(
                [c for c in session_id if c.isalnum() or c in ("-", "_")]
            ).strip()
            if not safe_session_id or safe_session_id == "default":
                return {
                    "status": "error",
                    "message": "預設或是無效的 Session 不允許全域清理",
                }

            user_base = os.path.join(self.base_dir, safe_session_id)
            if os.path.exists(user_base):
                shutil.rmtree(user_base)
                return {
                    "status": "success",
                    "message": f"Session {session_id} 的所有資料已清理",
                }
            return {"status": "success", "message": "工作空間本來就是空的"}
        except Exception as e:
            raise HTTPException(500, detail=f"Clear workspace failed: {str(e)}")
