"""
Dataset Router - 子資料集管理 API（掛在 /api/data-prep/subset 下）

儲存結構（與 notebook notes 整合）：
  workspace/{session_id}/notes/{file_stem}/               ← 主資料集
    ├── note_*.json, _proc_desc.txt                        ← 主資料集筆記（現有）
    ├── cleaning_rules.json                                ← 主資料集清洗規則（新增）
    └── {subset_id}/                                       ← 子資料集
        ├── note_*.json, _proc_desc.txt                    ← 子資料集筆記
        ├── cleaning_rules.json                            ← 子資料集清洗規則
        ├── data.csv                                       ← 過濾後實體 CSV
        └── meta.json                                      ← 子資料集描述
"""

from fastapi import APIRouter, Query, Body, HTTPException
from pathlib import Path
from typing import Optional
import json
import asyncio
import hashlib
import config

router = APIRouter()

BASE_DIR = Path(config.BASE_STORAGE_DIR)


def _get_file_id(filename: str) -> str:
    """與 analysis_service.get_file_id 一致的 MD5 hash"""
    return hashlib.md5(filename.encode()).hexdigest()[:12]


def _notes_root(session_id: str) -> Path:
    """workspace/{session_id}/notes/"""
    return BASE_DIR / session_id / "notes"


def _dataset_dir(session_id: str, file_stem: str, subset_id: str) -> Path:
    """
    主資料集 (main)：workspace/{session_id}/notes/{file_stem}/
    子資料集       ：workspace/{session_id}/notes/{file_stem}/{subset_id}/
    """
    base = _notes_root(session_id) / file_stem
    if subset_id == "main":
        return base
    return base / subset_id


def _note_count(session_id: str, file_stem: str, subset_id: str) -> int:
    nd = _dataset_dir(session_id, file_stem, subset_id)
    if not nd.exists():
        return 0
    return len(list(nd.glob("note_*.json")))


def _find_csv(uploads_dir: Path, file_id: str) -> Optional[Path]:
    """依 file_id (MD5) 找到對應的 CSV"""
    if not uploads_dir.exists():
        return None
    for f in uploads_dir.glob("*.csv"):
        if _get_file_id(f.name) == file_id:
            return f
    return None


@router.post("/create")
async def create_dataset(payload: dict = Body(...)):
    """建立子資料集：過濾原始 CSV 並儲存 meta.json（子集才存 data.csv，主資料集只建目錄）"""
    import pandas as pd

    session_id = payload.get("session_id", "default")
    file_id    = payload.get("file_id", "")
    file_stem  = payload.get("file_stem", "").strip()
    subset_id  = payload.get("subset_id", "").strip()
    name       = payload.get("name", subset_id)
    ds_type    = payload.get("type", "pivot")
    filters    = payload.get("filters", [])  # [{col, value}]

    if not file_stem or not subset_id:
        raise HTTPException(400, detail="缺少 file_stem 或 subset_id")

    ds_dir = _dataset_dir(session_id, file_stem, subset_id)
    ds_dir.mkdir(parents=True, exist_ok=True)

    # 初始化 cleaning_rules.json（不存在才建）
    rules_path = ds_dir / "cleaning_rules.json"
    if not rules_path.exists():
        rules_path.write_text(
            json.dumps({"pipeline": [], "excludedCols": [], "excludedIndices": []}),
            encoding="utf-8",
        )

    # 主資料集不需存 data.csv，只需 meta.json
    if subset_id == "main" or not filters:
        meta = {
            "name": name, "type": ds_type, "subset_id": subset_id,
            "file_stem": file_stem, "file_id": file_id,
            "filters": filters, "row_count": None,
        }
        (ds_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {"ok": True, "dataset_path": f"{file_stem}/{subset_id}", "row_count": None}

    # 子資料集：讀原始 CSV → 套用 filters → 存 data.csv
    uploads_dir = BASE_DIR / session_id / "uploads"
    csv_path = _find_csv(uploads_dir, file_id)
    if not csv_path:
        raise HTTPException(404, detail=f"找不到原始檔案: {file_id}")

    def _do_create():
        df = pd.read_csv(csv_path, encoding="utf-8-sig", low_memory=False)
        df.columns = [str(c).strip() for c in df.columns]
        for f in filters:
            col = f.get("col") or f.get("column", "")
            val = f.get("value")
            if col and col in df.columns and val is not None:
                df = df[df[col].astype(str).str.strip() == str(val).strip()]
        df = df.reset_index(drop=True)

        df.to_csv(ds_dir / "data.csv", index=False, encoding="utf-8-sig")
        meta = {
            "name": name, "type": ds_type, "subset_id": subset_id,
            "file_stem": file_stem, "file_id": file_id,
            "filters": filters, "row_count": len(df),
        }
        (ds_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return len(df)

    row_count = await asyncio.to_thread(_do_create)
    return {"ok": True, "dataset_path": f"{file_stem}/{subset_id}", "row_count": row_count}


@router.get("/list")
async def list_datasets(
    session_id: str = Query("default"),
    file_stem:  str = Query(...),
):
    """列出某主檔下所有子資料集 + 各自筆記數（含主資料集）"""
    stem_dir = _notes_root(session_id) / file_stem
    items = []

    # 主資料集（stem_dir 本身）
    main_note_count = len(list(stem_dir.glob("note_*.json"))) if stem_dir.exists() else 0
    main_meta_path  = stem_dir / "meta.json"
    main_name = file_stem
    if main_meta_path.exists():
        try:
            main_name = json.loads(main_meta_path.read_text(encoding="utf-8")).get("name", file_stem)
        except Exception:
            pass
    items.append({
        "subset_id": "main",
        "name": main_name,
        "type": "file",
        "filters": [],
        "row_count": None,
        "note_count": main_note_count,
    })

    # 子資料集（stem_dir 下的子目錄，含 meta.json）
    if stem_dir.exists():
        for d in sorted(stem_dir.iterdir(), key=lambda x: x.stat().st_mtime):
            if not d.is_dir():
                continue
            meta_path = d / "meta.json"
            if not meta_path.exists():
                continue
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            nc = len(list(d.glob("note_*.json")))
            items.append({
                "subset_id": d.name,
                "name": meta.get("name", d.name),
                "type": meta.get("type", "unknown"),
                "filters": meta.get("filters", []),
                "row_count": meta.get("row_count", 0),
                "note_count": nc,
            })

    return {"datasets": items}


@router.get("/cleaning")
async def get_cleaning(
    session_id:   str = Query("default"),
    dataset_path: str = Query(...),
):
    """取得指定資料集的清洗規則"""
    parts = dataset_path.replace("\\", "/").split("/", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return {"rules": None}
    file_stem, subset_id = parts
    rules_path = _dataset_dir(session_id, file_stem, subset_id) / "cleaning_rules.json"
    if not rules_path.exists():
        return {"rules": None}
    try:
        return {"rules": json.loads(rules_path.read_text(encoding="utf-8"))}
    except Exception:
        return {"rules": None}


@router.post("/cleaning")
async def save_cleaning(payload: dict = Body(...)):
    """儲存指定資料集的清洗規則"""
    session_id   = payload.get("session_id", "default")
    dataset_path = payload.get("dataset_path", "")
    rules        = payload.get("rules", {})

    parts = dataset_path.replace("\\", "/").split("/", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise HTTPException(400, detail="Invalid dataset_path")
    file_stem, subset_id = parts

    ds_dir = _dataset_dir(session_id, file_stem, subset_id)
    ds_dir.mkdir(parents=True, exist_ok=True)
    (ds_dir / "cleaning_rules.json").write_text(
        json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"ok": True}


@router.delete("/delete")
async def delete_dataset(payload: dict = Body(...)):
    """刪除子資料集目錄（不可刪主資料集）"""
    import shutil

    session_id   = payload.get("session_id", "default")
    dataset_path = payload.get("dataset_path", "")

    parts = dataset_path.replace("\\", "/").split("/", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise HTTPException(400, detail="Invalid dataset_path")
    file_stem, subset_id = parts

    if subset_id == "main":
        raise HTTPException(400, detail="不能刪除主資料集")

    ds_dir = _dataset_dir(session_id, file_stem, subset_id)
    if ds_dir.exists():
        await asyncio.to_thread(shutil.rmtree, ds_dir)
    return {"ok": True}
