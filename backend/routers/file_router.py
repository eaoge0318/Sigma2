"""
File Router - 檔案管理相關 API
"""

from fastapi import APIRouter, Depends, File, UploadFile, Form, Query
from backend.services.file_service import FileService
from backend.dependencies import get_file_service

router = APIRouter()


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    session_id: str = Form("default"),
    is_mapping: bool = Form(False),
    file_id: str = Form(None),  # Optional: Bind mapping to specific file
    file_service: FileService = Depends(get_file_service),
):
    """上傳檔案"""
    return await file_service.upload_file(
        file, session_id, is_mapping=is_mapping, file_id=file_id
    )


@router.get("/list")
async def list_files(
    session_id: str = Query("default"),
    file_service: FileService = Depends(get_file_service),
):
    """列出已上傳的檔案"""
    return await file_service.list_files(session_id)


@router.delete("/delete/{filename}")
async def delete_file(
    filename: str,
    session_id: str = Query("default"),
    file_service: FileService = Depends(get_file_service),
):
    """刪除指定檔案"""
    return await file_service.delete_file(filename, session_id)


@router.post("/rename/{filename}")
async def rename_file(
    filename: str,
    new_name: str = Query(...),
    session_id: str = Query("default"),
    file_service: FileService = Depends(get_file_service),
):
    """重新命名檔案，並同步更新 notes / analysis / configs / drafts 中的相關參照"""
    import os
    import json
    import hashlib
    import shutil
    from pathlib import Path
    from fastapi import HTTPException

    upload_dir = file_service.get_user_upload_dir(session_id)
    old_path = os.path.join(upload_dir, os.path.basename(filename))
    if not os.path.exists(old_path):
        raise HTTPException(404, detail="檔案不存在")

    # Sanitize and ensure extension
    safe_name = new_name.strip().replace("/", "_").replace("\\", "_")
    if not safe_name:
        raise HTTPException(400, detail="名稱不能為空")
    ext = os.path.splitext(filename)[1]
    if not safe_name.lower().endswith(ext.lower()):
        safe_name = safe_name + ext

    new_path = os.path.join(upload_dir, safe_name)
    if os.path.exists(new_path) and os.path.normpath(old_path) != os.path.normpath(new_path):
        raise HTTPException(400, detail=f"檔案 {safe_name} 已存在")

    # ── 1. Rename the actual file ──
    os.rename(old_path, new_path)

    old_stem = os.path.splitext(filename)[0]
    new_stem = os.path.splitext(safe_name)[0]
    old_file_id = hashlib.md5(filename.encode()).hexdigest()[:12]
    new_file_id = hashlib.md5(safe_name.encode()).hexdigest()[:12]
    user_base = Path(file_service.base_dir) / _safe_session(session_id)

    # ── 2. Rename notes directory ──
    old_notes_dir = user_base / "notes" / old_stem
    new_notes_dir = user_base / "notes" / new_stem
    if old_notes_dir.exists() and old_stem != new_stem:
        if new_notes_dir.exists():
            shutil.rmtree(str(new_notes_dir))
        shutil.move(str(old_notes_dir), str(new_notes_dir))

    # Update meta.json files inside the notes directory (including sub-dataset metas)
    if new_notes_dir.exists():
        for meta_path in new_notes_dir.rglob("meta.json"):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                changed = False
                if meta.get("name") == filename:
                    meta["name"] = safe_name
                    changed = True
                if meta.get("file_stem") == old_stem:
                    meta["file_stem"] = new_stem
                    changed = True
                if meta.get("file_id") == old_file_id:
                    meta["file_id"] = new_file_id
                    changed = True
                if changed:
                    with open(meta_path, "w", encoding="utf-8") as f:
                        json.dump(meta, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

    # ── 3. Rename analysis directories whose prefix matches old_file_id ──
    analysis_base = user_base / "analysis"
    if analysis_base.exists():
        for ana_dir in list(analysis_base.iterdir()):
            if not ana_dir.is_dir():
                continue
            dir_name = ana_dir.name
            if not dir_name.startswith(old_file_id):
                continue
            new_dir_name = new_file_id + dir_name[len(old_file_id):]
            new_ana_dir = analysis_base / new_dir_name
            shutil.move(str(ana_dir), str(new_ana_dir))
            # Update summary.json inside
            summary_path = new_ana_dir / "summary.json"
            if summary_path.exists():
                try:
                    with open(summary_path, "r", encoding="utf-8") as f:
                        summary = json.load(f)
                    if summary.get("filename") == filename:
                        summary["filename"] = safe_name
                    if summary.get("file_id", "").startswith(old_file_id):
                        summary["file_id"] = new_file_id + summary["file_id"][len(old_file_id):]
                    with open(summary_path, "w", encoding="utf-8") as f:
                        json.dump(summary, f, ensure_ascii=False, indent=2)
                except Exception:
                    pass

    # ── 4. Update configs / drafts that reference the old filename ──
    for sub in ("configs", "drafts"):
        sub_dir = user_base / sub
        if not sub_dir.exists():
            continue
        for json_file in sub_dir.glob("*.json"):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("filename") == filename:
                    data["filename"] = safe_name
                    with open(json_file, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

    return {"old_name": filename, "new_name": safe_name}


def _safe_session(session_id: str) -> str:
    import re
    s = re.sub(r"[^a-zA-Z0-9_\-]", "_", session_id)
    return s if s else "default"


@router.get("/download/{filename}")
async def download_file(
    filename: str,
    session_id: str = Query("default"),
    file_service: FileService = Depends(get_file_service),
):
    """下載指定檔案"""
    import os
    from fastapi import HTTPException
    from fastapi.responses import FileResponse

    upload_dir = file_service.get_user_upload_dir(session_id)
    path = os.path.join(upload_dir, os.path.basename(filename))
    if not os.path.exists(path):
        raise HTTPException(404, detail="檔案不存在")
    return FileResponse(
        path,
        filename=os.path.basename(filename),
        media_type="application/octet-stream",
    )


@router.get("/view/{filename}")
async def view_file(
    filename: str,
    page: int = 1,
    page_size: int = 50,
    sample_count: int = Query(0, description="等距取樣筆數，0=不取樣"),
    session_id: str = Query("default"),
    file_service: FileService = Depends(get_file_service),
):
    """預覽檔案內容（分頁 or 等距取樣）"""
    return await file_service.view_file(filename, page, page_size, session_id, sample_count)


@router.post("/clear_workspace")
async def clear_workspace(
    session_id: str = Query("default"),
    file_service: FileService = Depends(get_file_service),
):
    """清理 folos 使用者的工作空間 (刪除所有資料夾)"""
    return await file_service.clear_user_workspace(session_id)


@router.post("/convert-sheet")
async def convert_sheet(
    filename: str = Form(...),
    sheet_name: str = Form(...),
    session_id: str = Form("default"),
    delete_excel: bool = Form(False),
    file_service: FileService = Depends(get_file_service),
):
    """將已上傳的 Excel 檔案的指定 sheet 轉為 CSV"""
    import os
    import asyncio

    upload_dir = file_service.get_user_upload_dir(session_id)
    excel_path = os.path.join(upload_dir, os.path.basename(filename))
    if not os.path.exists(excel_path):
        from fastapi import HTTPException
        raise HTTPException(404, detail="Excel 檔案不存在")

    base = os.path.splitext(filename)[0]

    def _do_convert(src, dst, sname, del_excel):
        import pandas as pd
        xls = pd.ExcelFile(src, engine="calamine")
        try:
            df = pd.read_excel(xls, sheet_name=sname)
            n_sheets = len(xls.sheet_names)
        finally:
            xls.close()

        # Determine CSV filename
        if n_sheets > 1:
            safe_sheet = sname.replace("/", "_").replace("\\", "_")
            csv_name = f"{os.path.splitext(os.path.basename(src))[0]}_{safe_sheet}.csv"
        else:
            csv_name = f"{os.path.splitext(os.path.basename(src))[0]}.csv"

        csv_path = os.path.join(os.path.dirname(src), csv_name)
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        
        if del_excel:
            try:
                os.remove(src)
            except Exception:
                pass

        return csv_path, csv_name

    csv_path, csv_name = await asyncio.to_thread(
        _do_convert, excel_path, base, sheet_name, delete_excel
    )

    return {
        "filename": csv_name,
        "size": os.path.getsize(csv_path),
        "sheet_used": sheet_name,
    }
