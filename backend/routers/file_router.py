"""
File Router - 檔案管理相關 API
"""

import os, json
from fastapi import APIRouter, Depends, File, UploadFile, Form, Query, Body
from backend.services.file_service import FileService
from backend.dependencies import get_file_service, get_intelligent_analysis_service

router = APIRouter()


def _col_types_path(file_service: FileService, session_id: str, file_stem: str) -> str:
    configs_dir = file_service.get_user_path(session_id, "configs")
    safe_stem = "".join(c for c in file_stem if c.isalnum() or c in "-_")
    return os.path.join(configs_dir, f"{safe_stem}_col_types.json")


@router.get("/col_types")
async def get_col_types(
    session_id: str = Query("default"),
    file_stem: str = Query(...),
    file_service: FileService = Depends(get_file_service),
):
    """取得欄位型別 metadata（使用者手動設定過的）"""
    path = _col_types_path(file_service, session_id, file_stem)
    if not os.path.exists(path):
        return {"col_types": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return {"col_types": json.load(f)}
    except Exception:
        return {"col_types": {}}


@router.post("/col_types")
async def save_col_types(
    session_id: str = Query("default"),
    file_stem: str = Query(...),
    body: dict = Body(...),
    file_service: FileService = Depends(get_file_service),
):
    """儲存欄位型別 metadata（合併更新）"""
    path = _col_types_path(file_service, session_id, file_stem)
    existing = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass
    existing.update(body.get("col_types", {}))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    return {"ok": True, "saved": len(existing)}


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


@router.post("/view-time-range/{filename}")
async def view_file_time_range(
    filename: str,
    body: dict = Body(...),
    session_id: str = Query("default"),
    file_service: FileService = Depends(get_file_service),
):
    """依時間欄位或 row index 範圍篩選 CSV，回傳符合條件的 row（CSV 格式）"""
    import asyncio

    time_col = body.get("time_col", "")
    time_min = body.get("time_min", "")
    time_max = body.get("time_max", "")
    row_min = body.get("row_min")  # int or None
    row_max = body.get("row_max")  # int or None
    mode = body.get("mode", "keep")  # keep | exclude

    max_rows = body.get("max_rows", 10000)  # 前端可指定上限

    def _filter():
        import pandas as pd
        upload_dir = file_service.resolve_uploads_dir(session_id)
        file_path = os.path.join(upload_dir, os.path.basename(filename))
        if not os.path.exists(file_path):
            # Fallback to real uploads/
            real_dir = file_service.get_user_upload_dir(session_id)
            fallback = os.path.join(real_dir, os.path.basename(filename))
            if os.path.exists(fallback):
                file_path = fallback
            else:
                return None

        df = pd.read_csv(file_path, encoding="utf-8-sig", low_memory=False)
        df.columns = [str(c).strip() for c in df.columns]

        if row_min is not None and row_max is not None:
            # Row index 範圍篩選
            mask = (df.index >= int(row_min)) & (df.index <= int(row_max))
            if mode == 'exclude':
                mask = ~mask
        elif time_col and time_col in df.columns:
            # 時間欄位範圍篩選
            col = df[time_col].astype(str).str.strip()
            mask = (col >= time_min) & (col <= time_max)
            if mode == 'exclude':
                mask = ~mask
        else:
            return None

        filtered = df[mask]
        total_filtered = len(filtered)

        # 若超過 max_rows，等距取樣
        if total_filtered > max_rows:
            step = max(1, total_filtered // max_rows)
            sampled = filtered.iloc[::step].head(max_rows)
        else:
            sampled = filtered

        csv_str = sampled.to_csv(index=False)
        return {
            "content": csv_str,
            "total_lines": len(sampled) + 1,
            "filtered_count": total_filtered,
            "sampled_count": len(sampled),
            "original_count": len(df),
            "is_sampled": total_filtered > max_rows,
        }

    result = await asyncio.to_thread(_filter)
    if result is None:
        from fastapi import HTTPException
        raise HTTPException(404, detail="檔案或時間欄位不存在")
    return result


@router.post("/clear_workspace")
async def clear_workspace(
    session_id: str = Query("default"),
    file_service: FileService = Depends(get_file_service),
):
    """清理 folos 使用者的工作空間 (刪除所有資料夾)"""
    return await file_service.clear_user_workspace(session_id)


def _alias_path(file_service: FileService, session_id: str) -> str:
    configs_dir = file_service.get_user_path(session_id, "configs")
    return os.path.join(configs_dir, "column_aliases.json")


@router.get("/column-aliases")
async def get_column_aliases(
    session_id: str = Query("default"),
    file_service: FileService = Depends(get_file_service),
):
    """取得全域欄位別名表"""
    path = _alias_path(file_service, session_id)
    if not os.path.exists(path):
        return {"aliases": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return {"aliases": json.load(f)}
    except Exception:
        return {"aliases": {}}


@router.post("/column-aliases")
async def save_column_aliases(
    session_id: str = Query("default"),
    body: dict = Body(...),
    file_service: FileService = Depends(get_file_service),
):
    """儲存全域欄位別名表 (replace=true 整份覆蓋, 否則 merge)"""
    path = _alias_path(file_service, session_id)
    new_aliases = body.get("aliases", {})
    if body.get("replace"):
        result = new_aliases
    else:
        existing = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                pass
        existing.update(new_aliases)
        result = existing
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return {"ok": True, "count": len(result)}


@router.post("/column-aliases/upload")
async def upload_alias_mapping(
    file: UploadFile = File(...),
    key_col: str = Form(...),
    alias_col: str = Form(...),
    session_id: str = Form("default"),
    file_service: FileService = Depends(get_file_service),
):
    """上傳對照表 CSV/Excel，自動解析為別名表"""
    import pandas as pd
    import io

    content = await file.read()
    fname = file.filename.lower()
    try:
        if fname.endswith(('.xlsx', '.xls')):
            df = pd.read_excel(io.BytesIO(content))
        else:
            for enc in ('utf-8-sig', 'utf-8', 'big5', 'gbk', 'latin-1'):
                try:
                    df = pd.read_csv(io.BytesIO(content), encoding=enc)
                    break
                except (UnicodeDecodeError, LookupError):
                    continue
            else:
                df = pd.read_csv(io.BytesIO(content), encoding='latin-1')
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(400, f"無法解析檔案: {e}")

    if key_col not in df.columns or alias_col not in df.columns:
        from fastapi import HTTPException
        raise HTTPException(400, f"找不到指定欄位: key={key_col}, alias={alias_col}")

    # Build alias map
    new_aliases = {}
    for _, row in df.iterrows():
        k = str(row[key_col]).strip()
        v = str(row[alias_col]).strip()
        if k and v and k != 'nan' and v != 'nan':
            new_aliases[k] = v

    # Merge with existing
    path = _alias_path(file_service, session_id)
    existing = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass
    existing.update(new_aliases)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

    return {"ok": True, "imported": len(new_aliases), "total": len(existing)}


@router.post("/column-aliases/preview-file")
async def preview_alias_file(
    file: UploadFile = File(...),
    session_id: str = Form("default"),
    file_service: FileService = Depends(get_file_service),
):
    """預覽上傳的對照表，回傳欄位名和前幾列"""
    import pandas as pd
    import io

    content = await file.read()
    fname = file.filename.lower()
    try:
        if fname.endswith(('.xlsx', '.xls')):
            df = pd.read_excel(io.BytesIO(content))
        else:
            for enc in ('utf-8-sig', 'utf-8', 'big5', 'gbk', 'latin-1'):
                try:
                    df = pd.read_csv(io.BytesIO(content), encoding=enc)
                    break
                except (UnicodeDecodeError, LookupError):
                    continue
            else:
                df = pd.read_csv(io.BytesIO(content), encoding='latin-1')
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(400, f"無法解析檔案: {e}")

    return {
        "columns": df.columns.tolist(),
        "preview": df.head(5).astype(str).values.tolist(),
        "row_count": len(df),
    }


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


# ── Shadow-file alias mode ──

def _alias_mode_path(file_service: FileService, session_id: str) -> str:
    configs_dir = file_service.get_user_path(session_id, "configs")
    return os.path.join(configs_dir, "alias_mode.json")


def _get_alias_mode(file_service: FileService, session_id: str) -> bool:
    """Read alias mode state from configs/alias_mode.json"""
    path = _alias_mode_path(file_service, session_id)
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f).get("enabled", False)
    except Exception:
        return False


def _generate_shadow_files(file_service: FileService, session_id: str):
    """Generate shadow copies of all CSVs with aliased headers in alias_cache/"""
    # Load alias map
    alias_p = _alias_path(file_service, session_id)
    if not os.path.exists(alias_p):
        return 0
    try:
        with open(alias_p, "r", encoding="utf-8") as f:
            aliases = json.load(f)
    except Exception:
        return 0
    if not aliases:
        return 0

    uploads_dir = file_service.get_user_upload_dir(session_id)
    cache_dir = file_service.get_user_path(session_id, "alias_cache")
    os.makedirs(cache_dir, exist_ok=True)

    count = 0
    for fname in os.listdir(uploads_dir):
        if not fname.lower().endswith(".csv"):
            continue
        src = os.path.join(uploads_dir, fname)
        dst = os.path.join(cache_dir, fname)
        try:
            with open(src, "r", encoding="utf-8-sig") as f_in:
                header_line = f_in.readline()
                rest = f_in.read()
            # Replace header columns with aliases
            cols = header_line.rstrip("\r\n").split(",")
            new_cols = [aliases.get(c.strip(), c.strip()) for c in cols]
            new_header = ",".join(new_cols) + "\n"
            with open(dst, "w", encoding="utf-8-sig", newline="") as f_out:
                f_out.write(new_header)
                f_out.write(rest)
            count += 1
        except Exception:
            continue
    return count


@router.post("/alias-mode")
async def set_alias_mode(
    body: dict = Body(...),
    session_id: str = Query("default"),
    file_service: FileService = Depends(get_file_service),
):
    """切換別名模式 ON/OFF，ON 時自動產生 shadow 檔案"""
    import asyncio

    enabled = bool(body.get("enabled", False))

    # Save state
    mode_path = _alias_mode_path(file_service, session_id)
    with open(mode_path, "w", encoding="utf-8") as f:
        json.dump({"enabled": enabled}, f)

    generated = 0
    if enabled:
        generated = await asyncio.to_thread(
            _generate_shadow_files, file_service, session_id
        )

    # 清除 analysis_service 的 DataFrame 快取，避免讀到舊欄位名
    try:
        ia_service = get_intelligent_analysis_service()
        ia_service.clear_cache(session_id)
    except Exception:
        pass

    return {"ok": True, "enabled": enabled, "shadow_files": generated}


@router.get("/alias-mode")
async def get_alias_mode(
    session_id: str = Query("default"),
    file_service: FileService = Depends(get_file_service),
):
    """取得目前別名模式狀態"""
    enabled = _get_alias_mode(file_service, session_id)
    return {"enabled": enabled}


