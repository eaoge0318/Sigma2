"""
Association Analysis Router - /api/association
完全獨立模組
"""

import asyncio
import hashlib
import logging
from pathlib import Path
from typing import List, Dict, Optional, Any
import datetime

import pandas as pd
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from backend.services.analysis.analysis_service import AnalysisService
from backend.dependencies import get_intelligent_analysis_service
from backend.services.association_service import (
    run_apriori,
    get_col_distinct_values,
    _preview_binning,
)

router = APIRouter(tags=["Association - 關聯分析"])
logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────
# Helper
# ────────────────────────────────────────────────

def _find_csv(uploads_dir: Path, file_id: str) -> Path:
    if not uploads_dir.exists():
        raise HTTPException(status_code=404, detail="uploads 目錄不存在")
    # Search uploads/ and uploads/subsets/ (subsets are hidden from file management)
    candidates = list(uploads_dir.glob("*.csv"))
    subsets_dir = uploads_dir / "subsets"
    if subsets_dir.exists():
        candidates += list(subsets_dir.glob("*.csv"))
    for f in candidates:
        fid = hashlib.md5(f.name.encode()).hexdigest()[:12]
        if fid == file_id or fid.startswith(file_id) or file_id.startswith(fid):
            return f
    raise HTTPException(status_code=404, detail=f"找不到檔案: {file_id}")


def _load_df(
    file_id: str,
    session_id: str,
    analysis_service: AnalysisService,
    exclude_indices: List[int],
    exclude_cols: List[str],
) -> pd.DataFrame:
    uploads_dir = analysis_service.base_dir / session_id / "uploads"
    csv_path = _find_csv(uploads_dir, file_id)
    df = pd.read_csv(csv_path, encoding="utf-8-sig", low_memory=False)

    if exclude_indices:
        valid = [i for i in exclude_indices if 0 <= i < len(df)]
        df = df.drop(index=valid).reset_index(drop=True)

    if exclude_cols:
        drop = [c for c in exclude_cols if c in df.columns]
        df = df.drop(columns=drop)

    return df


# ────────────────────────────────────────────────
# Request models
# ────────────────────────────────────────────────

class BinningRule(BaseModel):
    op: str
    val: Optional[float] = None
    lo: Optional[float] = None
    hi: Optional[float] = None
    label: str


class RulesToDatasetRequest(BaseModel):
    file_id: str
    session_id: str = "default"
    consequent_col: str
    consequent_val: str
    antecedents: List[str] = []                          # ["col=val", ...]
    column_binning: Dict[str, List[Dict[str, Any]]] = {} # {col: [binning rules]}
    selected_cols: List[str] = []                        # all analysis columns for pre-filtering
    min_count: int = 1                                   # same min_count used in run_apriori
    exclude_indices: List[int] = []
    exclude_cols: List[str] = []
    dataset_filters: List[Dict[str, Any]] = []


class AssocRunRequest(BaseModel):
    file_id: str
    session_id: str = "default"
    selected_cols: List[str]
    binning_rules: Dict[str, List[BinningRule]] = {}
    consequent_col: str
    consequent_val: str
    min_support: float = 0.005
    min_confidence: float = 0.005
    min_lift: float = 0.005
    min_count: int = 30
    exclude_indices: List[int] = []
    exclude_cols: List[str] = []
    exclude_values: Dict[str, List[str]] = {}  # {"*": ["KD8"]} 或 {"AD條件表編碼": ["KD8"]}


class ColValuesRequest(BaseModel):
    file_id: str
    session_id: str = "default"
    col: str
    binning_rules: List[BinningRule] = []
    exclude_indices: List[int] = []
    exclude_cols: List[str] = []


class BinningPreviewRequest(BaseModel):
    file_id: str
    session_id: str = "default"
    col: str
    rules: List[BinningRule]
    exclude_indices: List[int] = []


class ColDistributionRequest(BaseModel):
    file_id: str
    session_id: str = "default"
    cols: List[str]
    binning_rules: Dict[str, List[BinningRule]] = {}
    min_count: int = 1
    exclude_indices: List[int] = []
    exclude_cols: List[str] = []


# ────────────────────────────────────────────────
# Endpoints
# ────────────────────────────────────────────────

@router.post("/run")
async def association_run(
    req: AssocRunRequest,
    analysis_service: AnalysisService = Depends(get_intelligent_analysis_service),
):
    """執行 Apriori 關聯規則分析。"""
    try:
        df = await asyncio.to_thread(
            _load_df,
            req.file_id, req.session_id, analysis_service,
            req.exclude_indices, req.exclude_cols,
        )

        binning_rules_dict = {
            col: [r.model_dump() for r in rules]
            for col, rules in req.binning_rules.items()
        }

        result = await asyncio.to_thread(
            run_apriori,
            df,
            req.selected_cols,
            binning_rules_dict,
            req.consequent_col,
            req.consequent_val,
            req.min_support,
            req.min_confidence,
            req.min_lift,
            req.min_count,
            req.exclude_values,
        )
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[Association] run error")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/col_values")
async def association_col_values(
    req: ColValuesRequest,
    analysis_service: AnalysisService = Depends(get_intelligent_analysis_service),
):
    """取得欄位（套用 binning 後）的唯一值，供 Consequent 選擇器使用。"""
    try:
        df = await asyncio.to_thread(
            _load_df,
            req.file_id, req.session_id, analysis_service,
            req.exclude_indices, req.exclude_cols,
        )

        if req.col not in df.columns:
            raise HTTPException(status_code=400, detail=f"欄位不存在: {req.col}")

        rules_dict = [r.model_dump() for r in req.binning_rules] if req.binning_rules else None

        values = await asyncio.to_thread(
            get_col_distinct_values, df, req.col, rules_dict
        )
        return {"col": req.col, "values": values}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[Association] col_values error")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/binning_preview")
async def association_binning_preview(
    req: BinningPreviewRequest,
    analysis_service: AnalysisService = Depends(get_intelligent_analysis_service),
):
    """預覽數值欄位分組後的分布。"""
    try:
        df = await asyncio.to_thread(
            _load_df,
            req.file_id, req.session_id, analysis_service,
            req.exclude_indices, [],
        )

        if req.col not in df.columns:
            raise HTTPException(status_code=400, detail=f"欄位不存在: {req.col}")

        rules_dict = [r.model_dump() for r in req.rules]
        dist = await asyncio.to_thread(
            _preview_binning, df[req.col], rules_dict
        )
        return {"col": req.col, "distribution": dist}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[Association] binning_preview error")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/col_distribution")
async def association_col_distribution(
    req: ColDistributionRequest,
    analysis_service: AnalysisService = Depends(get_intelligent_analysis_service),
):
    """取得多個欄位（套用 binning + min_count 後）的值分布，供 Step 1 右側視覺化使用。"""
    import pandas as pd
    import numpy as np
    try:
        df = await asyncio.to_thread(
            _load_df,
            req.file_id, req.session_id, analysis_service,
            req.exclude_indices, req.exclude_cols,
        )

        result = {}
        for col in req.cols:
            if col not in df.columns:
                continue
            rules = req.binning_rules.get(col)

            if rules:
                # 已有 binning → 顯示分組後的類別分布
                from backend.services.association_service import _apply_binning
                series = _apply_binning(df[col], [r.model_dump() for r in rules])
                series = series[series != "_other"]
                vc = series.value_counts()
                if req.min_count > 1:
                    vc = vc[vc >= req.min_count]
                total = vc.sum()
                result[col] = {
                    "type": "categorical",
                    "items": [
                        {"value": str(v), "count": int(c), "pct": round(int(c) / total * 100, 1) if total else 0}
                        for v, c in vc.head(15).items()
                    ],
                }
            else:
                # 嘗試判斷是否為數值欄位
                numeric_s = pd.to_numeric(df[col], errors="coerce")
                non_null = df[col].notna().sum()
                is_numeric = non_null > 0 and numeric_s.notna().sum() / non_null > 0.8

                if is_numeric:
                    valid = numeric_s.dropna().reset_index(drop=True)
                    if len(valid) == 0:
                        result[col] = {"type": "histogram", "bins": [], "samples": [], "min": 0, "max": 0, "mean": 0}
                        continue
                    n_bins = min(20, int(valid.nunique()))
                    counts, edges = np.histogram(valid, bins=n_bins)
                    total = int(len(valid))
                    # 採樣資料點供散布圖使用（最多 400 點）
                    n_samples = min(400, len(valid))
                    sample_idx = np.linspace(0, len(valid) - 1, n_samples, dtype=int)
                    samples = [
                        {"x": int(i), "y": round(float(valid.iloc[i]), 4)}
                        for i in sample_idx
                    ]
                    result[col] = {
                        "type": "histogram",
                        "bins": [
                            {
                                "lo": round(float(edges[i]), 4),
                                "hi": round(float(edges[i + 1]), 4),
                                "count": int(counts[i]),
                                "pct": round(int(counts[i]) / total * 100, 1) if total else 0,
                            }
                            for i in range(len(counts))
                        ],
                        "samples": samples,
                        "total": total,
                        "min": round(float(valid.min()), 2),
                        "max": round(float(valid.max()), 2),
                        "mean": round(float(valid.mean()), 2),
                    }
                else:
                    series = df[col].astype(str).replace("nan", pd.NA).dropna()
                    vc = series.value_counts()
                    if req.min_count > 1:
                        vc = vc[vc >= req.min_count]
                    total = vc.sum()
                    result[col] = {
                        "type": "categorical",
                        "items": [
                            {"value": str(v), "count": int(c), "pct": round(int(c) / total * 100, 1) if total else 0}
                            for v, c in vc.head(15).items()
                        ],
                    }

        return {"distributions": result}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[Association] col_distribution error")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rules_to_dataset")
async def rules_to_dataset(
    req: RulesToDatasetRequest,
    analysis_service: AnalysisService = Depends(get_intelligent_analysis_service),
):
    """從原始資料中篩出符合目標條件的真實資料列，存成新 CSV 資料集。"""
    try:
        from backend.services.association_service import _apply_binning

        def _build():
            import numpy as np
            # Load original data
            df = _load_df(req.file_id, req.session_id, analysis_service,
                          req.exclude_indices, req.exclude_cols)

            # Apply dataset-level filters (subset conditions)
            for f in req.dataset_filters:
                kw = str(f.get("keyword", "")).strip()
                col = f.get("column", "")
                if kw and col in df.columns:
                    if kw.startswith("=="):
                        df = df[df[col].astype(str).str.strip() == kw[2:]]
                    else:
                        df = df[df[col].astype(str).str.contains(kw, case=False, na=False)]
            if req.dataset_filters:
                df = df.reset_index(drop=True)

            # Apply same pre-processing as run_apriori to match transaction count
            if req.selected_cols:
                valid_cols = [c for c in req.selected_cols if c in df.columns]
                if valid_cols:
                    # Apply binning to numeric columns
                    df_work = df.copy()
                    for col in valid_cols:
                        rules = req.column_binning.get(col, [])
                        if rules:
                            df_work[col] = _apply_binning(df[col], rules)
                        else:
                            df_work[col] = df_work[col].astype(str)
                    # Remove NaN and _other rows (same as run_apriori step 2)
                    df_work = df_work.replace("nan", np.nan)
                    valid_mask = df_work[valid_cols].notna().all(axis=1)
                    for col in valid_cols:
                        valid_mask &= df_work[col] != "_other"
                    df = df[valid_mask].reset_index(drop=True)
                    df_work = df_work[valid_mask].reset_index(drop=True)
                    # Apply min_count filtering (same as run_apriori step 3)
                    if req.min_count > 1:
                        for col in valid_cols:
                            vc = df_work[col].value_counts()
                            valid_vals = vc[vc >= req.min_count].index
                            keep = df_work[col].isin(valid_vals)
                            df = df[keep].reset_index(drop=True)
                            df_work = df_work[keep].reset_index(drop=True)

            # Filter by antecedent conditions only (dataset = all rows matching the condition)
            for item in req.antecedents:
                if "=" not in item:
                    continue
                col, val = item.split("=", 1)
                if col not in df.columns:
                    continue
                col_rules = req.column_binning.get(col, [])
                if col_rules:
                    binned_ant = _apply_binning(df[col], col_rules)
                    df = df[binned_ant == val].reset_index(drop=True)
                else:
                    df = df[df[col].astype(str) == val].reset_index(drop=True)

            df_filtered = df.reset_index(drop=True)

            if df_filtered.empty:
                raise HTTPException(status_code=400,
                    detail=f"找不到符合條件的資料列")

            # Save to uploads/subsets/ — hidden from file management list
            uploads_dir = analysis_service.base_dir / req.session_id / "uploads" / "subsets"
            uploads_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            # Filename based on antecedent conditions
            ant_label = "_".join(
                item.replace("/", "_").replace("\\", "_")[:15]
                for item in req.antecedents[:2]
            ) or "condition"
            filename = f"{ant_label}_{ts}.csv"
            save_path = uploads_dir / filename
            df_filtered.to_csv(save_path, index=False, encoding="utf-8-sig")

            file_id = hashlib.md5(filename.encode()).hexdigest()[:12]
            return {
                "file_id": file_id,
                "filename": filename,
                "row_count": len(df_filtered),
                "columns": list(df_filtered.columns),
            }

        result = await asyncio.to_thread(_build)
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[Association] rules_to_dataset error")
        raise HTTPException(status_code=500, detail=str(e))
