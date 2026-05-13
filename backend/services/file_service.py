"""
檔案管理服務
負責檔案的上傳、刪除、列表等操作
"""

import os
import shutil
import hashlib  # Ensure hash lib is available
from typing import List, Dict, Any, Optional
from datetime import datetime
from pathlib import Path
from fastapi import UploadFile, HTTPException


import config as app_config


def _safe_sid(session_id: str) -> str:
    """跟 FileService.get_user_path 一致的 session_id 安全過濾"""
    s = "".join(c for c in session_id if c.isalnum() or c in ("-", "_")).strip()
    return s if s else "default"


def resolve_uploads_path(base_dir, session_id: str):
    """Standalone helper: returns alias_cache/ if alias mode ON, else uploads/.
    Works with both str and Path base_dir. Returns a Path object."""
    import json
    sid = _safe_sid(session_id)
    base = Path(base_dir)
    mode_path = base / sid / "configs" / "alias_mode.json"
    try:
        if mode_path.exists():
            with open(mode_path, "r", encoding="utf-8") as f:
                if json.load(f).get("enabled"):
                    cache_dir = base / sid / "alias_cache"
                    if cache_dir.is_dir():
                        return cache_dir
    except Exception:
        pass
    return base / sid / "uploads"


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

    def _sync_shadow_for_file(self, session_id: str, filename: str):
        """若別名模式 ON，為單一檔案產生 shadow 副本到 alias_cache/"""
        import json as _json
        configs_dir = self.get_user_path(session_id, "configs")
        mode_path = os.path.join(configs_dir, "alias_mode.json")
        alias_path = os.path.join(configs_dir, "column_aliases.json")
        try:
            if not os.path.exists(mode_path):
                return
            with open(mode_path, "r", encoding="utf-8") as f:
                if not _json.load(f).get("enabled"):
                    return
            if not os.path.exists(alias_path):
                return
            with open(alias_path, "r", encoding="utf-8") as f:
                aliases = _json.load(f)
            if not aliases:
                return
            uploads_dir = self.get_user_upload_dir(session_id)
            src = os.path.join(uploads_dir, filename)
            cache_dir = self.get_user_path(session_id, "alias_cache")
            dst = os.path.join(cache_dir, filename)
            with open(src, "r", encoding="utf-8-sig") as f_in:
                header_line = f_in.readline()
                rest = f_in.read()
            cols = header_line.rstrip("\r\n").split(",")
            new_cols = [aliases.get(c.strip(), c.strip()) for c in cols]
            new_header = ",".join(new_cols) + "\n"
            with open(dst, "w", encoding="utf-8-sig", newline="") as f_out:
                f_out.write(new_header)
                f_out.write(rest)
        except Exception:
            pass

    def resolve_uploads_dir(self, session_id: str) -> str:
        """取得實際讀取目錄：別名模式 ON → alias_cache/，OFF → uploads/"""
        import json
        configs_dir = self.get_user_path(session_id, "configs")
        mode_path = os.path.join(configs_dir, "alias_mode.json")
        try:
            if os.path.exists(mode_path):
                with open(mode_path, "r", encoding="utf-8") as f:
                    if json.load(f).get("enabled"):
                        cache_dir = self.get_user_path(session_id, "alias_cache")
                        if os.path.isdir(cache_dir):
                            return cache_dir
        except Exception:
            pass
        return self.get_user_upload_dir(session_id)

    async def upload_file(
        self,
        file: UploadFile,
        session_id: str,
        is_mapping: bool = False,
        file_id: Optional[str] = None,
    ):
        """上傳檔案 (支援綁定特定 file_id 的對應表)"""
        import logging
        logger = logging.getLogger(__name__)
        try:
            filename = file.filename
            logger.info(f"[Upload] Started: {filename} for session {session_id}")
            
            # 1. 如果是綁定特定檔案的對應表
            if is_mapping and file_id:
                analysis_path = self.base_dir / session_id / "analysis" / file_id
                if not analysis_path.exists():
                    # 如果尚未分析過，資料夾可能不存在，嘗試建立 (通常只有 analysis/prepare 後才會有)
                    # 但為了讓用戶能預先上傳，我們可以建立它
                    analysis_path.mkdir(parents=True, exist_ok=True)

                # 固定命名為 mapping.csv，方便讀取
                file_path = analysis_path / "mapping.csv"

                content = await file.read()
                with open(file_path, "wb") as f:
                    f.write(content)

                return {
                    "filename": "mapping.csv",
                    "path": str(file_path),
                    "size": len(content),
                    "is_bound": True,
                    "bound_file_id": file_id,
                }

            # 2. 一般上傳邏輯 (含全域對應表)
            upload_dir = self.get_user_upload_dir(session_id)
            base_filename = file.filename

            # 如果是全域參數對應表，加上特定前綴
            if is_mapping:
                filename = f"(參數對應表)_{base_filename}"
                # 清理該會話下舊的全域對應表
                for f in os.listdir(upload_dir):
                    if "(參數對應表)_" in f:
                        try:
                            os.remove(os.path.join(upload_dir, f))
                        except Exception:
                            pass
            else:
                filename = base_filename

            logger.info(f"[Upload] Starting streaming upload to disk: {filename}")
            
            raw_path = os.path.join(upload_dir, filename)
            
            # Stream directly to disk to avoid massive RAM spikes for 100MB+ files
            with open(raw_path, "wb") as f_out:
                while chunk := await file.read(1024 * 1024 * 5):  # 5MB chunks
                    f_out.write(chunk)
                    
            file_size = os.path.getsize(raw_path)
            logger.info(f"[Upload] File streamed and saved to disk: {file_size} bytes")

            # === Excel 自動轉 CSV ===
            ext = os.path.splitext(filename)[1].lower()
            if ext in (".xlsx", ".xls"):
                import asyncio as _asyncio

                try:
                    import pandas as pd
                except ImportError:
                    raise HTTPException(
                        500, detail="伺服器缺少 pandas 套件, 無法處理 Excel 檔案"
                    )
                try:
                    # Step 2: Get sheet names ultra-fast using zipfile (xlsx is a zip)
                    if ext == ".xlsx":
                        import zipfile
                        from xml.etree import ElementTree as ET
                        sheets_info = []
                        with zipfile.ZipFile(raw_path, "r") as zf:
                            with zf.open("xl/workbook.xml") as wb_xml:
                                tree = ET.parse(wb_xml)
                                ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                                sheet_names = [
                                    el.attrib["name"]
                                    for el in tree.findall(".//s:sheet", ns)
                                ]
                            for i, sn in enumerate(sheet_names, 1):
                                ws_path = f"xl/worksheets/sheet{i}.xml"
                                try:
                                    info = zf.getinfo(ws_path)
                                    est_rows = max(0, info.file_size // 100)
                                    sheets_info.append({"name": sn, "rows": est_rows, "cols": -1})
                                except KeyError:
                                    sheets_info.append({"name": sn, "rows": -1, "cols": -1})
                    else:
                        # .xls fallback — lightweight check
                        def _get_xls_sheets(p):
                            import pandas as _pd
                            xls = _pd.ExcelFile(p)
                            names = xls.sheet_names
                            xls.close()
                            return names
                        sheet_names = await _asyncio.to_thread(_get_xls_sheets, raw_path)
                        sheets_info = [{"name": sn, "rows": -1, "cols": -1} for sn in sheet_names]

                    # Step 3: Multi-sheet → return info for frontend selection (fast path)
                    if len(sheet_names) > 1:
                        return {
                            "needs_sheet_selection": True,
                            "filename": filename,
                            "sheets": sheets_info,
                        }

                    # Step 4: Single sheet → convert to CSV in a thread to avoid blocking event loop
                    csv_filename = os.path.splitext(filename)[0] + ".csv"
                    csv_path = os.path.join(upload_dir, csv_filename)
                    
                    def _convert_excel_to_csv(src, dst):
                        import pandas as _pd
                        df = _pd.read_excel(src, sheet_name=0, engine="calamine")
                        df.to_csv(dst, index=False, encoding="utf-8-sig")
                        os.remove(src)  # Remove raw Excel after conversion

                    logger.info(f"[Upload] Converting single-sheet Excel to CSV in thread...")
                    await _asyncio.to_thread(_convert_excel_to_csv, raw_path, csv_path)
                    logger.info(f"[Upload] Conversion complete: {csv_path}")

                    file_size = os.path.getsize(csv_path)
                    filename = csv_filename
                    file_path = csv_path

                except Exception as e:
                    raise HTTPException(500, detail=f"Excel 轉換失敗: {str(e)}")
            elif ext == ".csv":
                # Auto-detect encoding and re-save as UTF-8-sig so all downstream
                # pd.read_csv(..., encoding="utf-8-sig") calls work correctly.
                file_path = raw_path
                try:
                    raw_bytes = open(raw_path, "rb").read()
                    # Try chardet first, fall back to common CJK encodings
                    detected_enc = None
                    try:
                        import chardet
                        det = chardet.detect(raw_bytes[:65536])
                        if det and det.get("confidence", 0) >= 0.7:
                            detected_enc = det["encoding"]
                    except ImportError:
                        pass
                    # If chardet not available or confidence too low, try candidates
                    if not detected_enc:
                        for candidate in ("utf-8-sig", "utf-8", "big5", "gb2312", "gbk", "cp950"):
                            try:
                                raw_bytes.decode(candidate)
                                detected_enc = candidate
                                break
                            except (UnicodeDecodeError, LookupError):
                                continue
                    if detected_enc and detected_enc.lower().replace("-", "") not in ("utf8sig", "utf8"):
                        text = raw_bytes.decode(detected_enc, errors="replace")
                        with open(raw_path, "w", encoding="utf-8-sig", newline="") as f_out:
                            f_out.write(text)
                        logger.info(f"[Upload] Re-encoded CSV from {detected_enc} → utf-8-sig")
                except Exception as enc_err:
                    logger.warning(f"[Upload] Encoding re-save skipped: {enc_err}")
            else:
                # If not an Excel file or CSV, it's already saved down as raw_path
                file_path = raw_path

            logger.info(f"[Upload] Processing finished: {file_path}")

            # 若別名模式 ON，為新上傳的 CSV 產生 shadow 副本
            if filename.lower().endswith(".csv"):
                self._sync_shadow_for_file(session_id, filename)

            return {
                "filename": filename,
                "path": file_path,
                "size": file_size,
                "is_bound": False,
            }
        except Exception as e:
            raise HTTPException(500, detail=f"Upload failed: {str(e)}")

    def _list_files_sync(self, session_id: str) -> Dict[str, List[Dict[str, Any]]]:
        """同步版本的 list_files，在 thread 中執行以避免阻塞 event loop"""
        import hashlib

        upload_dir = self.get_user_upload_dir(session_id)
        analysis_base_dir = os.path.join(self.base_dir, session_id, "analysis")

        files = []
        if os.path.exists(upload_dir):
            for filename in os.listdir(upload_dir):
                if "(參數對應表)_" in filename:
                    continue
                # Skip raw Excel files (temporary, pending sheet conversion)
                if filename.lower().endswith((".xlsx", ".xls")):
                    continue

                file_path = os.path.join(upload_dir, filename)
                if os.path.isfile(file_path):
                    try:
                        stats = os.stat(file_path)
                        file_id = hashlib.md5(filename.encode()).hexdigest()[:12]
                        summary_path = os.path.join(
                            analysis_base_dir, file_id, "summary.json"
                        )
                        is_indexed = os.path.exists(summary_path)

                        files.append(
                            {
                                "filename": filename,
                                "size": stats.st_size,
                                "uploaded_at": datetime.fromtimestamp(
                                    stats.st_mtime
                                ).strftime("%Y-%m-%d %H:%M:%S"),
                                "is_indexed": is_indexed,
                            }
                        )
                    except OSError:
                        continue
        return {"files": files}

    async def list_files(
        self, session_id: str = "default"
    ) -> Dict[str, List[Dict[str, Any]]]:
        """列出已上傳的檔案 (非阻塞: 在獨立 thread 中執行 I/O)"""
        import asyncio

        try:
            return await asyncio.to_thread(self._list_files_sync, session_id)
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

    def _view_file_sync(
        self, filename: str, page: int, page_size: int, session_id: str, sample_count: int = 0
    ) -> Dict[str, Any]:
        """同步版本的 view_file，在 thread 中執行以避免阻塞 event loop"""
        if not filename or ".." in filename:
            raise HTTPException(400, detail="Invalid filename")

        upload_dir = self.resolve_uploads_dir(session_id)
        file_path = os.path.join(upload_dir, os.path.basename(filename))
        if not os.path.exists(file_path):
            # Fallback: alias_cache 裡沒有，嘗試從真實 uploads/ 找
            real_dir = self.get_user_upload_dir(session_id)
            fallback = os.path.join(real_dir, os.path.basename(filename))
            if os.path.exists(fallback):
                # 順便補做 shadow sync
                try:
                    self._sync_shadow_for_file(session_id, os.path.basename(filename))
                except Exception:
                    pass
                file_path = fallback
            else:
                raise HTTPException(404, detail="File not found")

        total_lines = 0
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            for _ in f:
                total_lines += 1

        # Sampling mode: evenly pick sample_count rows
        if sample_count > 0 and total_lines > 1:
            data_lines = total_lines - 1  # exclude header
            step = max(1, data_lines // sample_count)
            content_lines = []
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                header = f.readline()
                content_lines.append(header)
                line_idx = 0
                picked = 0
                for line in f:
                    if line_idx % step == 0 and picked < sample_count:
                        content_lines.append(line)
                        picked += 1
                    line_idx += 1
            return {
                "filename": filename,
                "content": "".join(content_lines),
                "page": 1,
                "page_size": sample_count,
                "total_lines": total_lines,
                "sampled": True,
                "sample_count": len(content_lines) - 1,
            }

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

    async def view_file(
        self,
        filename: str,
        page: int = 1,
        page_size: int = 50,
        session_id: str = "default",
        sample_count: int = 0,
    ) -> Dict[str, Any]:
        """預覽檔案內容 (非阻塞: 在獨立 thread 中執行 I/O)"""
        import asyncio

        try:
            return await asyncio.to_thread(
                self._view_file_sync, filename, page, page_size, session_id, sample_count
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(500, detail=f"View failed: {str(e)}")

    def get_file_path(self, filename: str, session_id: str = "default") -> str:
        """取得檔案的完整路徑（別名模式 ON 時指向 alias_cache，找不到則 fallback 到 uploads）"""
        upload_dir = self.resolve_uploads_dir(session_id)
        path = os.path.join(upload_dir, os.path.basename(filename))
        if not os.path.exists(path):
            real_dir = self.get_user_upload_dir(session_id)
            fallback = os.path.join(real_dir, os.path.basename(filename))
            if os.path.exists(fallback):
                try:
                    self._sync_shadow_for_file(session_id, os.path.basename(filename))
                except Exception:
                    pass
                return fallback
        return path

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
