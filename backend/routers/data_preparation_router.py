"""
資料整理工具 Router — 獨立於 analysis_router
提供樞紐分析表、欄位讀取、相關性圖表等資料前處理功能
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from typing import List, Dict
import asyncio
import logging
import io

from backend.services.analysis.analysis_service import AnalysisService
from backend.dependencies import get_intelligent_analysis_service

logger = logging.getLogger(__name__)

router = APIRouter()


# ========== 欄位讀取 ==========


@router.get("/columns/{file_id}")
async def get_file_columns(
    file_id: str,
    session_id: str = Query("default"),
    analysis_service: AnalysisService = Depends(get_intelligent_analysis_service),
):
    """輕量端點：直接讀取 CSV 取得欄位名稱與型別"""
    import pandas as pd

    def _read_columns():
        uploads_dir = analysis_service.base_dir / session_id / "uploads"
        csv_path = _find_csv(uploads_dir, file_id, analysis_service)

        df = pd.read_csv(csv_path, encoding="utf-8-sig", nrows=5)
        df.columns = [str(c).strip() for c in df.columns]
        numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()

        return {
            "file_id": file_id,
            "columns": list(df.columns),
            "numeric_columns": numeric_cols,
            "total_columns": len(df.columns),
        }

    try:
        return await asyncio.to_thread(_read_columns)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get columns error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ========== 樞紐分析表 ==========


class PivotValueSpec(BaseModel):
    column: str
    aggfunc: str = "mean"


class PivotRequest(BaseModel):
    file_id: str
    rows: List[str] = []
    columns: List[str] = []
    values: List[PivotValueSpec] = []
    filters: List[str] = []
    targets: List[str] = []  # 多目標參數


@router.post("/pivot")
async def run_pivot_table(
    request: PivotRequest,
    session_id: str = Query("default"),
    analysis_service: AnalysisService = Depends(get_intelligent_analysis_service),
):
    """樞紐分析表 + 可選的多目標組內相關係數計算"""
    import pandas as pd
    import numpy as np

    def _do_pivot():
        uploads_dir = analysis_service.base_dir / session_id / "uploads"
        csv_path = _find_csv(uploads_dir, request.file_id, analysis_service)

        df = pd.read_csv(csv_path, encoding="utf-8-sig")
        df.columns = [str(c).strip() for c in df.columns]

        # Validate
        all_cols = set(df.columns)
        for _, col_list in [
            ("rows", request.rows),
            ("columns", request.columns),
            ("values", [v.column for v in request.values]),
        ]:
            for c in col_list:
                if c not in all_cols:
                    raise HTTPException(400, detail=f"欄位 '{c}' 不存在")

        # Build aggfunc
        agg_map = {
            "mean": "mean",
            "sum": "sum",
            "count": "count",
            "min": "min",
            "max": "max",
            "std": "std",
            "median": "median",
        }

        if not request.values:
            first_col = df.columns[0]
            value_cols = [first_col]
            aggfuncs = {first_col: "count"}
        else:
            value_cols = list(set(v.column for v in request.values))
            aggfuncs = {}
            for v in request.values:
                fn = agg_map.get(v.aggfunc, "mean")
                if v.column not in aggfuncs:
                    aggfuncs[v.column] = [fn]
                elif fn not in aggfuncs[v.column]:
                    aggfuncs[v.column].append(fn)
            for k, v in aggfuncs.items():
                if len(v) == 1:
                    aggfuncs[k] = v[0]

        index_cols = request.rows if request.rows else None
        col_cols = request.columns if request.columns else None

        try:
            pivot = pd.pivot_table(
                df,
                values=value_cols,
                index=index_cols,
                columns=col_cols,
                aggfunc=aggfuncs,
                fill_value=0,
            )
        except Exception as e:
            raise HTTPException(400, detail=f"樞紐分析失敗: {str(e)}")

        if isinstance(pivot.columns, pd.MultiIndex):
            pivot.columns = [
                " | ".join(str(c) for c in col).strip(" | ")
                for col in pivot.columns.values
            ]

        pivot = pivot.reset_index()
        pivot = pivot.replace([np.inf, -np.inf], np.nan)

        # ===== 多目標 Top3 相關係數 =====
        valid_targets = [t for t in request.targets if t and t in df.columns]

        if valid_targets and index_cols:
            exclude_base = set(index_cols) | set(request.columns or [])
            num_cols_all = [
                c
                for c in df.select_dtypes(include=["number"]).columns
                if c not in exclude_base
            ]

            if num_cols_all:
                grouped = df.groupby(index_cols, dropna=False)

                # Add Source Table (group size) if not already present
                if "Source Table" not in pivot.columns:
                    gs = grouped.size().reset_index(name="Source Table")
                    for ic in index_cols:
                        pivot[ic] = pivot[ic].astype(str)
                        gs[ic] = gs[ic].astype(str)
                    pivot = pivot.merge(gs, on=index_cols, how="left")

                for target_col in valid_targets:
                    num_cols = [c for c in num_cols_all if c != target_col]
                    if not num_cols:
                        continue

                    corr_rows = []
                    for group_key, group_df in grouped:
                        if not isinstance(group_key, tuple):
                            group_key = (group_key,)
                        row_data = dict(zip(index_cols, group_key))

                        if len(group_df) < 3:
                            row_data["_top1_label"] = "n<3"
                            row_data["_corr_sort"] = None
                            row_data["_top3"] = None
                            corr_rows.append(row_data)
                            continue

                        target_s = group_df[target_col]
                        if target_s.std() == 0:
                            row_data["_top1_label"] = "無變異"
                            row_data["_corr_sort"] = None
                            row_data["_top3"] = None
                            corr_rows.append(row_data)
                            continue

                        correlations = {}
                        for col in num_cols:
                            try:
                                s = group_df[col]
                                if s.std() == 0:
                                    continue
                                r = target_s.corr(s)
                                if not np.isnan(r):
                                    correlations[col] = round(float(r), 4)
                            except Exception:
                                continue

                        if not correlations:
                            row_data["_top1_label"] = "-"
                            row_data["_corr_sort"] = None
                            row_data["_top3"] = None
                            corr_rows.append(row_data)
                            continue

                        top3 = sorted(
                            correlations.items(),
                            key=lambda x: abs(x[1]),
                            reverse=True,
                        )[:3]

                        row_data["_top1_label"] = f"{top3[0][0]}({top3[0][1]:+.3f})"
                        row_data["_corr_sort"] = abs(top3[0][1])
                        row_data["_top3"] = [{"name": n, "r": r} for n, r in top3]
                        corr_rows.append(row_data)

                    if corr_rows:
                        corr_df = pd.DataFrame(corr_rows)
                        col_name = f"Top1 vs {target_col}"
                        sort_col = f"_sort_{target_col}"
                        top3_col = f"_top3_{target_col}"

                        for ic in index_cols:
                            pivot[ic] = pivot[ic].astype(str)
                            corr_df[ic] = corr_df[ic].astype(str)

                        corr_df = corr_df.rename(
                            columns={
                                "_top1_label": col_name,
                                "_corr_sort": sort_col,
                                "_top3": top3_col,
                            }
                        )

                        pivot = pivot.merge(
                            corr_df[index_cols + [col_name, sort_col, top3_col]],
                            on=index_cols,
                            how="left",
                        )

                # ===== XGBoost 重要參數 =====
                for target_col in valid_targets:
                    num_cols = [c for c in num_cols_all if c != target_col]
                    if not num_cols:
                        continue

                    xgb_rows = []
                    for group_key, group_df in grouped:
                        if not isinstance(group_key, tuple):
                            group_key = (group_key,)
                        row_data = dict(zip(index_cols, group_key))

                        if len(group_df) < 10:
                            row_data["_xgb_label"] = "n<10"
                            row_data["_xgb_sort"] = None
                            row_data["_xgb_top3"] = None
                            xgb_rows.append(row_data)
                            continue

                        try:
                            from xgboost import XGBRegressor

                            y = group_df[target_col].values
                            X = group_df[num_cols].fillna(0).values
                            # Drop NaN/Inf in target
                            valid_mask = np.isfinite(y)
                            if valid_mask.sum() < 10:
                                row_data["_xgb_label"] = "-"
                                row_data["_xgb_sort"] = None
                                row_data["_xgb_top3"] = None
                                xgb_rows.append(row_data)
                                continue
                            y = y[valid_mask]
                            X = X[valid_mask]

                            model = XGBRegressor(
                                n_estimators=50,
                                max_depth=3,
                                learning_rate=0.1,
                                random_state=42,
                                verbosity=0,
                                n_jobs=1,
                            )
                            model.fit(X, y)
                            importances = model.feature_importances_

                            feat_imp = {
                                num_cols[j]: round(float(importances[j]), 4)
                                for j in range(len(num_cols))
                                if importances[j] > 0
                            }

                            if not feat_imp:
                                row_data["_xgb_label"] = "-"
                                row_data["_xgb_sort"] = None
                                row_data["_xgb_top3"] = None
                            else:
                                top3 = sorted(
                                    feat_imp.items(),
                                    key=lambda x: x[1],
                                    reverse=True,
                                )[:3]
                                row_data["_xgb_label"] = (
                                    f"{top3[0][0]}({top3[0][1]:.3f})"
                                )
                                row_data["_xgb_sort"] = top3[0][1]
                                row_data["_xgb_top3"] = [
                                    {"name": n, "imp": v} for n, v in top3
                                ]
                        except Exception as exc:
                            logger.warning(f"XGB failed for {target_col}: {exc}")
                            row_data["_xgb_label"] = "err"
                            row_data["_xgb_sort"] = None
                            row_data["_xgb_top3"] = None

                        xgb_rows.append(row_data)

                    if xgb_rows:
                        xgb_df = pd.DataFrame(xgb_rows)
                        col_name = f"XGB Top1 vs {target_col}"
                        sort_col = f"_xgb_sort_{target_col}"
                        top3_col = f"_xgb_top3_{target_col}"

                        for ic in index_cols:
                            xgb_df[ic] = xgb_df[ic].astype(str)

                        xgb_df = xgb_df.rename(
                            columns={
                                "_xgb_label": col_name,
                                "_xgb_sort": sort_col,
                                "_xgb_top3": top3_col,
                            }
                        )

                        pivot = pivot.merge(
                            xgb_df[index_cols + [col_name, sort_col, top3_col]],
                            on=index_cols,
                            how="left",
                        )

                # ===== 共同相關 (方案 B: 加權總分) =====
                if len(valid_targets) > 1:
                    _compute_common_corr(pivot, valid_targets)

                # ===== T² Hotelling =====
                from scipy import stats as sp_stats
                from sklearn.decomposition import PCA
                from sklearn.preprocessing import StandardScaler

                t2_rows = []
                for group_key, group_df in grouped:
                    if not isinstance(group_key, tuple):
                        group_key = (group_key,)
                    row_data = dict(zip(index_cols, group_key))

                    if len(group_df) < 10 or len(num_cols_all) < 2:
                        row_data["_t2_label"] = "n<10"
                        row_data["_t2_data"] = None
                        t2_rows.append(row_data)
                        continue

                    try:
                        sub = group_df[num_cols_all].copy()
                        # Drop cols with >50% NaN, fill rest with median
                        thresh = int(len(sub) * 0.5)
                        sub = sub.dropna(axis=1, thresh=thresh)
                        sub = sub.fillna(sub.median())
                        # Drop zero-variance cols
                        sub = sub.loc[:, sub.std() > 0]
                        n_obs, p_dim = sub.shape
                        if p_dim < 2:
                            row_data["_t2_label"] = "-"
                            row_data["_t2_data"] = None
                            t2_rows.append(row_data)
                            continue

                        scaler = StandardScaler()
                        scaled = scaler.fit_transform(sub.values)

                        pca_used = False
                        n_comp = p_dim
                        if p_dim / n_obs > 0.5:
                            pca = PCA()
                            pca.fit(scaled)
                            cum = np.cumsum(pca.explained_variance_ratio_)
                            n_comp = int(np.searchsorted(cum, 0.95) + 1)
                            n_comp = max(2, min(n_comp, n_obs - 2))
                            pca2 = PCA(n_components=n_comp)
                            scaled = pca2.fit_transform(scaled)
                            pca_used = True

                        mean = scaled.mean(axis=0)
                        cov_inv = np.linalg.pinv(np.cov(scaled, rowvar=False))
                        diff = scaled - mean
                        t2_vals = [float(d @ cov_inv @ d.T) for d in diff]

                        ucl99 = float(sp_stats.chi2.ppf(0.99, n_comp))
                        ucl95 = float(sp_stats.chi2.ppf(0.95, n_comp))
                        n_anom = sum(1 for v in t2_vals if v > ucl99)

                        row_data["_t2_label"] = f"{n_anom}/{n_obs}"
                        row_data["_t2_data"] = {
                            "t2_values": t2_vals,
                            "ucl_99": ucl99,
                            "ucl_95": ucl95,
                            "n_components": n_comp,
                            "pca_used": pca_used,
                            "n_anomalies": n_anom,
                            "n_obs": n_obs,
                        }
                    except Exception as exc:
                        logger.warning(f"T2 failed: {exc}")
                        row_data["_t2_label"] = "err"
                        row_data["_t2_data"] = None

                    t2_rows.append(row_data)

                if t2_rows:
                    t2_df = pd.DataFrame(t2_rows)
                    for ic in index_cols:
                        t2_df[ic] = t2_df[ic].astype(str)
                    t2_df = t2_df.rename(
                        columns={
                            "_t2_label": "T² 異常",
                            "_t2_data": "_t2_data",
                        }
                    )
                    pivot = pivot.merge(
                        t2_df[index_cols + ["T² 異常", "_t2_data"]],
                        on=index_cols,
                        how="left",
                    )

        # Build output
        hide_cols = set()
        for t in request.targets or []:
            hide_cols.add(f"_sort_{t}")
            hide_cols.add(f"_top3_{t}")
            hide_cols.add(f"_xgb_sort_{t}")
            hide_cols.add(f"_xgb_top3_{t}")
        hide_cols.add("_sort_common")
        hide_cols.add("_top3_common")
        hide_cols.add("_t2_data")

        records = pivot.head(500).to_dict(orient="records")
        all_cols = [c for c in pivot.columns if c not in hide_cols]

        # Reorder: base columns first, then grouped per target, then common
        analysis_prefixes = ["Top1 vs ", "XGB Top1 vs "]
        base_cols = []
        analysis_cols_set = set()
        for c in all_cols:
            is_analysis = False
            for pfx in analysis_prefixes:
                if c.startswith(pfx):
                    is_analysis = True
                    break
            if c == "共同相關 Top1" or c == "T² 異常":
                is_analysis = True
            if is_analysis:
                analysis_cols_set.add(c)
            else:
                base_cols.append(c)

        grouped_analysis = []
        for t in request.targets or []:
            for pfx in analysis_prefixes:
                col_name = pfx + t
                if col_name in analysis_cols_set:
                    grouped_analysis.append(col_name)

        if "共同相關 Top1" in analysis_cols_set:
            grouped_analysis.append("共同相關 Top1")
        if "T² 異常" in analysis_cols_set:
            grouped_analysis.append("T² 異常")

        columns = base_cols + grouped_analysis

        for rec in records:
            for k, v in list(rec.items()):
                if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
                    rec[k] = None

        return {
            "columns": columns,
            "data": records,
            "total_rows": len(pivot),
            "truncated": len(pivot) > 500,
        }

    try:
        return await asyncio.to_thread(_do_pivot)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Pivot table error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def _compute_common_corr(pivot, targets):
    """方案 B: 對每行，把各目標的 top3 參數的 |r| 加總，取 Top3"""

    common_labels = []
    common_sorts = []
    common_top3s = []

    for _, row in pivot.iterrows():
        # Collect all (param, |r|) from every target's top3
        score_map = {}  # param -> sum of |r|
        all_top3 = {}  # param -> list of {target, r}
        has_data = False

        for t in targets:
            top3_col = f"_top3_{t}"
            top3_data = row.get(top3_col)
            if not isinstance(top3_data, list):
                continue
            has_data = True
            for item in top3_data:
                name = item["name"]
                r = item["r"]
                score_map[name] = score_map.get(name, 0) + abs(r)
                if name not in all_top3:
                    all_top3[name] = []
                all_top3[name].append({"target": t, "r": r})

        if not has_data or not score_map:
            common_labels.append("-")
            common_sorts.append(None)
            common_top3s.append(None)
            continue

        # Top 3 by total |r|
        ranked = sorted(score_map.items(), key=lambda x: x[1], reverse=True)[:3]
        label = f"{ranked[0][0]}(Σ{ranked[0][1]:.3f})" if ranked else "-"
        common_labels.append(label)
        common_sorts.append(ranked[0][1] if ranked else None)
        common_top3s.append(
            [{"name": n, "score": s, "details": all_top3.get(n, [])} for n, s in ranked]
        )

    pivot["共同相關 Top1"] = common_labels
    pivot["_sort_common"] = common_sorts
    pivot["_top3_common"] = common_top3s


# ========== 相關性圖表 ==========


class CorrChartRequest(BaseModel):
    file_id: str
    group_filters: Dict[str, str]
    target: str
    params: List[str]


@router.post("/corr-chart")
async def generate_corr_chart(
    request: CorrChartRequest,
    session_id: str = Query("default"),
    analysis_service: AnalysisService = Depends(get_intelligent_analysis_service),
):
    """生成 3×1 雙軸相關性圖表"""
    import pandas as pd
    import numpy as np
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import rcParams

    def _gen_chart():
        uploads_dir = analysis_service.base_dir / session_id / "uploads"
        csv_path = _find_csv(uploads_dir, request.file_id, analysis_service)

        df = pd.read_csv(csv_path, encoding="utf-8-sig")
        df.columns = [str(c).strip() for c in df.columns]

        mask = pd.Series(True, index=df.index)
        for col, val in request.group_filters.items():
            if col in df.columns:
                mask &= df[col].astype(str) == str(val)
        group_df = df[mask].reset_index(drop=True)

        if len(group_df) < 2:
            raise HTTPException(400, detail="組內資料不足")

        rcParams["font.sans-serif"] = ["Microsoft JhengHei", "SimHei", "DejaVu Sans"]
        rcParams["axes.unicode_minus"] = False

        n_charts = min(len(request.params), 3)
        fig, all_axes = plt.subplots(
            n_charts,
            2,
            figsize=(10, 2.0 * n_charts),
            dpi=100,
            gridspec_kw={"width_ratios": [3, 2]},
        )
        if n_charts == 1:
            all_axes = [all_axes]

        colors_left = "#ef4444"
        colors_right = ["#3b82f6", "#10b981", "#f59e0b"]

        target_s = group_df[request.target]
        x = range(len(group_df))

        for i, param in enumerate(request.params[:3]):
            if param not in df.columns:
                continue

            ax_line = all_axes[i][0]
            ax_scat = all_axes[i][1]
            param_s = group_df[param]
            r = target_s.corr(param_s)
            r_str = f"{r:+.3f}" if not np.isnan(r) else "N/A"

            # --- Left: dual-axis line chart ---
            ax_line.plot(
                x,
                target_s,
                color=colors_left,
                linewidth=1.2,
                label=request.target,
                alpha=0.8,
            )
            ax_line.set_ylabel(request.target, color=colors_left, fontsize=8)
            ax_line.tick_params(axis="y", labelcolor=colors_left, labelsize=7)

            ax2 = ax_line.twinx()
            ax2.plot(
                x, param_s, color=colors_right[i], linewidth=1.2, label=param, alpha=0.8
            )
            ax2.set_ylabel(param, color=colors_right[i], fontsize=8)
            ax2.tick_params(axis="y", labelcolor=colors_right[i], labelsize=7)

            ax_line.set_title(f"{param}  (r = {r_str})", fontsize=9, fontweight="bold")
            ax_line.tick_params(axis="x", labelsize=6)
            ax_line.grid(True, alpha=0.15)

            # --- Right: scatter plot ---
            clean = group_df[[param, request.target]].dropna()
            if len(clean) > 1:
                ax_scat.scatter(
                    clean[param],
                    clean[request.target],
                    s=8,
                    alpha=0.5,
                    color=colors_right[i],
                    edgecolors="none",
                )
                # Trend line
                z = np.polyfit(clean[param], clean[request.target], 1)
                p = np.poly1d(z)
                x_line = np.linspace(clean[param].min(), clean[param].max(), 50)
                ax_scat.plot(
                    x_line,
                    p(x_line),
                    color=colors_left,
                    linewidth=1.5,
                    linestyle="--",
                    alpha=0.8,
                )
                ax_scat.set_title(f"r² = {r**2:.3f}", fontsize=9, fontweight="bold")
            else:
                ax_scat.set_title("資料不足", fontsize=9)

            ax_scat.set_xlabel(param, fontsize=7)
            ax_scat.set_ylabel(request.target, fontsize=7)
            ax_scat.tick_params(labelsize=6)
            ax_scat.grid(True, alpha=0.15)

        plt.tight_layout(h_pad=2.0, w_pad=1.5)

        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
        plt.close(fig)
        buf.seek(0)
        return buf.getvalue()

    try:
        img_bytes = await asyncio.to_thread(_gen_chart)
        return Response(content=img_bytes, media_type="image/png")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Corr chart error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ========== XGBoost 重要參數圖表 ==========


@router.post("/xgb-chart")
async def generate_xgb_chart(
    request: CorrChartRequest,
    session_id: str = Query("default"),
    analysis_service: AnalysisService = Depends(get_intelligent_analysis_service),
):
    """XGBoost feature importance bar chart + scatter plots for top3"""
    import pandas as pd
    import numpy as np
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import rcParams

    def _gen_chart():
        uploads_dir = analysis_service.base_dir / session_id / "uploads"
        csv_path = _find_csv(uploads_dir, request.file_id, analysis_service)

        df = pd.read_csv(csv_path, encoding="utf-8-sig")
        df.columns = [str(c).strip() for c in df.columns]

        mask = pd.Series(True, index=df.index)
        for col, val in request.group_filters.items():
            if col in df.columns:
                mask &= df[col].astype(str) == str(val)
        group_df = df[mask].reset_index(drop=True)

        if len(group_df) < 10:
            raise HTTPException(400, detail="組內資料不足 (n<10)")

        rcParams["font.sans-serif"] = ["Microsoft JhengHei", "SimHei", "DejaVu Sans"]
        rcParams["axes.unicode_minus"] = False

        exclude = set(request.group_filters.keys()) | {request.target}
        num_cols = [
            c for c in df.select_dtypes(include=["number"]).columns if c not in exclude
        ]
        if not num_cols:
            raise HTTPException(400, detail="無可用數值欄位")

        from xgboost import XGBRegressor

        y = group_df[request.target].values
        X = group_df[num_cols].fillna(0).values

        model = XGBRegressor(
            n_estimators=50,
            max_depth=3,
            learning_rate=0.1,
            random_state=42,
            verbosity=0,
            n_jobs=1,
        )
        model.fit(X, y)
        importances = model.feature_importances_

        feat_imp = sorted(
            [
                (num_cols[j], float(importances[j]))
                for j in range(len(num_cols))
                if importances[j] > 0
            ],
            key=lambda x: x[1],
            reverse=True,
        )

        n_top = min(len(feat_imp), 10)
        n_scatter = min(len(request.params), 3)

        fig, axes = plt.subplots(
            max(n_scatter, 1),
            2,
            figsize=(10, 2.0 * max(n_scatter, 1)),
            dpi=100,
            gridspec_kw={"width_ratios": [3, 2]},
        )
        if max(n_scatter, 1) == 1:
            axes = [axes]

        # --- Left column: bar chart (span all rows) ---
        for i in range(len(axes)):
            if i > 0:
                axes[i][0].set_visible(False)

        ax_bar = axes[0][0]
        top_n = feat_imp[:n_top]
        names = [x[0] for x in reversed(top_n)]
        values = [x[1] for x in reversed(top_n)]
        colors = [
            "#059669" if n in [p for p in request.params] else "#94a3b8" for n in names
        ]

        ax_bar.barh(range(len(names)), values, color=colors, height=0.6)
        ax_bar.set_yticks(range(len(names)))
        ax_bar.set_yticklabels(names, fontsize=8)
        ax_bar.set_xlabel("Importance", fontsize=8)
        ax_bar.set_title(f"XGBoost Top{n_top} 重要參數", fontsize=10, fontweight="bold")
        ax_bar.grid(True, axis="x", alpha=0.15)
        ax_bar.tick_params(labelsize=7)

        # --- Right column: scatter plots for top3 ---
        greens = ["#059669", "#10b981", "#34d399"]
        for i in range(n_scatter):
            param = request.params[i]
            if param not in df.columns:
                continue
            ax_scat = axes[i][1]
            clean = group_df[[param, request.target]].dropna()
            if len(clean) > 1:
                r = clean[param].corr(clean[request.target])
                ax_scat.scatter(
                    clean[param],
                    clean[request.target],
                    s=8,
                    alpha=0.5,
                    color=greens[i],
                    edgecolors="none",
                )
                z = np.polyfit(clean[param], clean[request.target], 1)
                p = np.poly1d(z)
                x_line = np.linspace(clean[param].min(), clean[param].max(), 50)
                ax_scat.plot(
                    x_line,
                    p(x_line),
                    color="#b91c1c",
                    linewidth=1.5,
                    linestyle="--",
                    alpha=0.8,
                )
                r_str = f"{r:+.3f}" if not np.isnan(r) else "N/A"
                ax_scat.set_title(f"{param} (r={r_str})", fontsize=9, fontweight="bold")
            else:
                ax_scat.set_title(f"{param} (資料不足)", fontsize=9)
            ax_scat.set_xlabel(param, fontsize=7)
            ax_scat.set_ylabel(request.target, fontsize=7)
            ax_scat.tick_params(labelsize=6)
            ax_scat.grid(True, alpha=0.15)

        plt.tight_layout(h_pad=2.0, w_pad=1.5)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
        plt.close(fig)
        buf.seek(0)
        return buf.getvalue()

    try:
        img_bytes = await asyncio.to_thread(_gen_chart)
        return Response(content=img_bytes, media_type="image/png")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"XGB chart error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ========== 相關係數矩陣 ==========


class CorrMatrixRequest(BaseModel):
    file_id: str
    group_filters: Dict[str, str]
    targets: List[str]
    params: List[str]


@router.post("/corr-matrix")
async def generate_corr_matrix(
    request: CorrMatrixRequest,
    session_id: str = Query("default"),
    analysis_service: AnalysisService = Depends(get_intelligent_analysis_service),
):
    """生成相關係數矩陣熱力圖: params × targets"""
    import pandas as pd
    import numpy as np
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import rcParams
    from matplotlib.colors import TwoSlopeNorm

    def _gen_matrix():
        uploads_dir = analysis_service.base_dir / session_id / "uploads"
        csv_path = _find_csv(uploads_dir, request.file_id, analysis_service)

        df = pd.read_csv(csv_path, encoding="utf-8-sig")
        df.columns = [str(c).strip() for c in df.columns]

        # Filter to group
        mask = pd.Series(True, index=df.index)
        for col, val in request.group_filters.items():
            if col in df.columns:
                mask &= df[col].astype(str) == str(val)
        group_df = df[mask].reset_index(drop=True)

        if len(group_df) < 3:
            raise HTTPException(400, detail="組內資料不足")

        # Compute correlation matrix
        valid_params = [p for p in request.params if p in df.columns]
        valid_targets = [t for t in request.targets if t in df.columns]

        if not valid_params or not valid_targets:
            raise HTTPException(400, detail="無有效欄位")

        matrix = []
        for p in valid_params:
            row = []
            for t in valid_targets:
                try:
                    r = group_df[p].corr(group_df[t])
                    row.append(round(float(r), 3) if not np.isnan(r) else 0)
                except Exception:
                    row.append(0)
            matrix.append(row)

        matrix_np = np.array(matrix)

        rcParams["font.sans-serif"] = ["Microsoft JhengHei", "SimHei", "DejaVu Sans"]
        rcParams["axes.unicode_minus"] = False

        n_rows = len(valid_params)
        n_cols = len(valid_targets)
        cell_h = max(0.6, min(0.9, 5.0 / n_rows))
        cell_w = max(1.2, min(2.0, 8.0 / n_cols))
        fig_w = n_cols * cell_w + 2.5
        fig_h = n_rows * cell_h + 1.5

        fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=100)

        # Diverging colormap
        vmax = max(abs(matrix_np.max()), abs(matrix_np.min()), 0.01)
        norm = TwoSlopeNorm(vmin=-vmax, vcenter=0, vmax=vmax)
        cmap = plt.cm.RdBu_r

        im = ax.imshow(matrix_np, cmap=cmap, norm=norm, aspect="auto")

        # Annotate
        for i in range(n_rows):
            for j in range(n_cols):
                v = matrix_np[i, j]
                color = "white" if abs(v) > vmax * 0.6 else "black"
                ax.text(
                    j,
                    i,
                    f"{v:+.3f}",
                    ha="center",
                    va="center",
                    fontsize=9,
                    fontweight="bold",
                    color=color,
                )

        ax.set_xticks(range(n_cols))
        ax.set_xticklabels(valid_targets, fontsize=9, rotation=30, ha="right")
        ax.set_yticks(range(n_rows))
        ax.set_yticklabels(valid_params, fontsize=9)

        ax.set_title("相關係數矩陣", fontsize=12, fontweight="bold", pad=10)
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label="r")

        plt.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
        plt.close(fig)
        buf.seek(0)
        return buf.getvalue()

    try:
        img_bytes = await asyncio.to_thread(_gen_matrix)
        return Response(content=img_bytes, media_type="image/png")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Corr matrix error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ========== 工具函數 ==========


# ========== T² 直接計算 (MVA 面板用) ==========


class T2Filter(BaseModel):
    column: str
    keyword: str = ""
    exclude_empty: bool = False


class T2ComputeRequest(BaseModel):
    file_id: str
    filters: List[T2Filter] = []
    exclude_indices: List[int] = []  # row indices to exclude (from previous runs)
    exclude_columns: List[str] = []  # columns to exclude from T² calculation


@router.post("/t2-compute")
async def compute_t2(
    req: T2ComputeRequest,
    session_id: str = Query("default"),
    analysis_service: AnalysisService = Depends(get_intelligent_analysis_service),
):
    """Compute T² on raw file data with optional filters (no pivot needed)"""
    import numpy as np
    import pandas as pd
    from scipy import stats as sp_stats
    from sklearn.decomposition import PCA
    from sklearn.preprocessing import StandardScaler

    uploads_dir = analysis_service.base_dir / session_id / "uploads"
    csv_path = _find_csv(uploads_dir, req.file_id, analysis_service)
    df = pd.read_csv(csv_path, encoding="utf-8-sig")

    # Apply filters
    for f in req.filters:
        if f.column not in df.columns:
            continue
        if f.exclude_empty:
            df = df.dropna(subset=[f.column])
            df = df[df[f.column].astype(str).str.strip() != ""]
        if f.keyword:
            kw = f.keyword.strip()
            # Numeric operators
            import re

            num_match = re.match(r"^([><=!]+)\s*([\d.]+)$", kw)
            if num_match:
                op, val = num_match.group(1), float(num_match.group(2))
                col_num = pd.to_numeric(df[f.column], errors="coerce")
                if op in (">=", "≥"):
                    df = df[col_num >= val]
                elif op == "<=":
                    df = df[col_num <= val]
                elif op == ">":
                    df = df[col_num > val]
                elif op == "<":
                    df = df[col_num < val]
                elif op in ("=", "=="):
                    df = df[col_num == val]
                elif op == "!=":
                    df = df[col_num != val]
            else:
                df = df[df[f.column].astype(str).str.contains(kw, case=False, na=False)]

    # After filters, assign stable row positions (these are "original indices" for exclusion tracking)
    df = df.reset_index(drop=True)
    df["__orig_idx__"] = df.index.tolist()  # stable position after filters

    # Exclude specific row indices (from previous brush-select removals)
    if req.exclude_indices:
        valid_indices = [i for i in req.exclude_indices if 0 <= i < len(df)]
        if valid_indices:
            df = df.drop(index=valid_indices).reset_index(drop=True)

    # Capture the original indices of remaining rows
    remaining_orig_indices = df["__orig_idx__"].tolist()

    n_obs = len(df)
    if n_obs < 10:
        raise HTTPException(
            status_code=400, detail=f"過濾後剩餘 {n_obs} 筆，不足 10 筆"
        )

    # Select numeric columns (exclude our tracking col)
    num_cols = [
        c for c in df.select_dtypes(include="number").columns if c != "__orig_idx__"
    ]
    sub = df[num_cols].copy()

    # Drop cols with >50% NaN, fill rest with median, drop zero-variance
    thresh = int(len(sub) * 0.5)
    sub = sub.dropna(axis=1, thresh=thresh)
    sub = sub.fillna(sub.median())
    sub = sub.loc[:, sub.std() > 0]
    # Exclude user-dismissed columns
    if req.exclude_columns:
        sub = sub.drop(
            columns=[c for c in req.exclude_columns if c in sub.columns],
            errors="ignore",
        )

    p_dim = sub.shape[1]
    if p_dim < 2:
        raise HTTPException(status_code=400, detail="有效數值欄位不足 2 個")

    scaler = StandardScaler()
    scaled = scaler.fit_transform(sub.values)

    pca_used = False
    n_comp = p_dim
    if True:  # always use PCA
        pca = PCA()
        pca.fit(scaled)
        cum = np.cumsum(pca.explained_variance_ratio_)
        n_comp = int(np.searchsorted(cum, 0.95) + 1)
        n_comp = max(2, min(n_comp, n_obs - 2))
        pca2 = PCA(n_components=n_comp)
        scaled = pca2.fit_transform(scaled)
        pca_used = True

    mean = scaled.mean(axis=0)
    cov_inv = np.linalg.pinv(np.cov(scaled, rowvar=False))
    diff = scaled - mean
    t2_vals = [float(d @ cov_inv @ d.T) for d in diff]

    ucl99 = float(sp_stats.chi2.ppf(0.99, n_comp))
    ucl95 = float(sp_stats.chi2.ppf(0.95, n_comp))
    n_anom = sum(1 for v in t2_vals if v > ucl99)

    return {
        "t2_values": t2_vals,
        "ucl_99": ucl99,
        "ucl_95": ucl95,
        "n_components": n_comp,
        "pca_used": pca_used,
        "n_anomalies": n_anom,
        "n_obs": n_obs,
        "columns_used": sub.columns.tolist(),
        "original_indices": remaining_orig_indices,
    }


def _find_csv(uploads_dir, file_id, analysis_service):
    csv_path = None
    if uploads_dir.exists():
        for f in uploads_dir.glob("*.csv"):
            fid = analysis_service.get_file_id(f.name)
            if fid == file_id:
                csv_path = f
                break

    if not csv_path or not csv_path.exists():
        raise HTTPException(status_code=404, detail=f"找不到檔案: {file_id}")

    return csv_path


class T2ContributionRequest(BaseModel):
    file_id: str
    filters: List[T2Filter] = []
    exclude_indices: List[int] = []
    selected_indices: List[int] = []  # chart indices of selected points
    top_n: int = 10
    exclude_columns: List[str] = []


@router.post("/t2-contribution")
async def compute_t2_contribution(
    req: T2ContributionRequest,
    session_id: str = Query("default"),
    analysis_service: AnalysisService = Depends(get_intelligent_analysis_service),
):
    """Compute per-variable T² contribution for selected samples."""
    import numpy as np
    import pandas as pd
    from sklearn.preprocessing import StandardScaler

    uploads_dir = analysis_service.base_dir / session_id / "uploads"
    csv_path = _find_csv(uploads_dir, req.file_id, analysis_service)
    df = pd.read_csv(csv_path, encoding="utf-8-sig")

    # Apply same filters
    for f in req.filters:
        if f.exclude_empty and f.column in df.columns:
            df = df[df[f.column].notna() & (df[f.column].astype(str).str.strip() != "")]
        kw = (f.keyword or "").strip()
        if kw and f.column in df.columns:
            import re as _re

            m = _re.match(r"^([><=!]+)\s*([\d.]+)$", kw)
            if m:
                op, val = m.group(1), float(m.group(2))
                col_num = pd.to_numeric(df[f.column], errors="coerce")
                if op == ">":
                    df = df[col_num > val]
                elif op == ">=":
                    df = df[col_num >= val]
                elif op == "<":
                    df = df[col_num < val]
                elif op == "<=":
                    df = df[col_num <= val]
                elif op in ("=", "=="):
                    df = df[col_num == val]
                elif op == "!=":
                    df = df[col_num != val]
            else:
                df = df[df[f.column].astype(str).str.contains(kw, case=False, na=False)]

    df = df.reset_index(drop=True)

    # Exclude indices — build mapping from original → new position
    if req.exclude_indices:
        valid = [i for i in req.exclude_indices if 0 <= i < len(df)]
        if valid:
            keep_mask = ~df.index.isin(valid)
            # orig_to_new: maps pre-exclusion index → post-exclusion index
            orig_to_new = {}
            new_idx = 0
            for old_idx in range(len(df)):
                if keep_mask[old_idx]:
                    orig_to_new[old_idx] = new_idx
                    new_idx += 1
            df = df.loc[keep_mask].reset_index(drop=True)
        else:
            orig_to_new = {i: i for i in range(len(df))}
    else:
        orig_to_new = {i: i for i in range(len(df))}

    if len(df) < 10:
        raise HTTPException(status_code=400, detail="樣本不足 10 筆")

    # Numeric columns
    num_cols = df.select_dtypes(include="number").columns.tolist()
    sub = df[num_cols].copy()
    thresh = int(len(sub) * 0.5)
    sub = sub.dropna(axis=1, thresh=thresh)
    sub = sub.fillna(sub.median())
    sub = sub.loc[:, sub.std() > 0]
    # Exclude user-dismissed columns
    if req.exclude_columns:
        sub = sub.drop(
            columns=[c for c in req.exclude_columns if c in sub.columns],
            errors="ignore",
        )
    col_names = sub.columns.tolist()

    if len(col_names) < 2:
        raise HTTPException(status_code=400, detail="有效欄位不足")

    p_dim = len(col_names)

    scaler = StandardScaler()
    z_scores = scaler.fit_transform(sub.values)  # (n_obs, p_dim) z-scores

    # Map selected original indices → new indices in filtered df
    valid_sel = []
    for orig_idx in req.selected_indices:
        new_idx = orig_to_new.get(orig_idx)
        if new_idx is not None and 0 <= new_idx < len(z_scores):
            valid_sel.append(new_idx)
    if not valid_sel:
        raise HTTPException(status_code=400, detail="無有效選取樣本")

    # Rank by average |z-score| of selected samples per variable
    sel_z = z_scores[valid_sel, :]  # (n_sel, p_dim)
    avg_abs_z = np.mean(np.abs(sel_z), axis=0)  # (p_dim,)

    # Top N
    top_n = min(req.top_n, p_dim)
    ranked = np.argsort(-avg_abs_z)[:top_n]

    result = []
    total = avg_abs_z.sum()
    for r in ranked:
        result.append(
            {
                "parameter": col_names[r],
                "contribution": round(float(avg_abs_z[r]), 4),
                "pct": round(float(avg_abs_z[r] / total * 100), 1) if total > 0 else 0,
                "values": [
                    round(float(v), 4) if not np.isnan(v) else None
                    for v in z_scores[:, r]
                ],
            }
        )

    return {
        "top_contributions": result,
        "n_selected": len(valid_sel),
        "n_variables": p_dim,
        "selected_indices": valid_sel,
    }


# ================================================================
# G/B Test
# ================================================================


class PCAScatterRequest(BaseModel):
    file_id: str
    filters: List[T2Filter] = []
    exclude_indices: List[int] = []
    exclude_cols: List[str] = []


@router.post("/pca-scatter")
async def pca_scatter(
    req: PCAScatterRequest,
    session_id: str = Query("default"),
    analysis_service=Depends(get_intelligent_analysis_service),
):
    """Return first 2 PC scores for scatter plot."""
    import pandas as pd
    from sklearn.preprocessing import StandardScaler
    from sklearn.decomposition import PCA

    uploads_dir = analysis_service.base_dir / session_id / "uploads"
    csv_path = _find_csv(uploads_dir, req.file_id, analysis_service)
    df = pd.read_csv(csv_path, encoding="utf-8-sig")

    # Apply filters
    for f in req.filters:
        if f.exclude_empty and f.column in df.columns:
            df = df[df[f.column].notna() & (df[f.column].astype(str).str.strip() != "")]
        kw = (f.keyword or "").strip()
        if kw and f.column in df.columns:
            col_series = df[f.column]
            import re as _re

            m = _re.match(r"^([><=!]+)\s*([\d.]+)$", kw)
            if m and pd.api.types.is_numeric_dtype(col_series):
                op, val = m.group(1), float(m.group(2))
                col_num = pd.to_numeric(col_series, errors="coerce")
                if op == ">":
                    df = df[col_num > val]
                elif op == ">=":
                    df = df[col_num >= val]
                elif op == "<":
                    df = df[col_num < val]
                elif op == "<=":
                    df = df[col_num <= val]
                elif op in ("=", "=="):
                    df = df[col_num == val]
                elif op == "!=":
                    df = df[col_num != val]
            else:
                df = df[df[f.column].astype(str).str.contains(kw, case=False, na=False)]

    df = df.reset_index(drop=True)

    if req.exclude_indices:
        valid = [i for i in req.exclude_indices if 0 <= i < len(df)]
        if valid:
            df = df.drop(index=valid).reset_index(drop=True)

    num_cols = df.select_dtypes(include="number").columns.tolist()
    sub = df[num_cols].copy()
    thresh = int(len(sub) * 0.5)
    sub = sub.dropna(axis=1, thresh=thresh)
    sub = sub.fillna(sub.median())
    sub = sub.loc[:, sub.std() > 0]
    # Exclude user-specified columns
    if req.exclude_cols:
        sub = sub.drop(
            columns=[c for c in req.exclude_cols if c in sub.columns], errors="ignore"
        )
    col_names = sub.columns.tolist()

    if len(col_names) < 2:
        raise HTTPException(status_code=400, detail="有效欄位不足")

    scaler = StandardScaler()
    scaled = scaler.fit_transform(sub.values)
    pca = PCA(n_components=2)
    scores = pca.fit_transform(scaled)

    return {
        "scores": [[round(float(s[0]), 4), round(float(s[1]), 4)] for s in scores],
        "explained_var": [round(float(v), 4) for v in pca.explained_variance_ratio_],
        "n_obs": len(scores),
        "col_names": col_names,
    }


class GBTestRequest(BaseModel):
    file_id: str
    filters: List[T2Filter] = []
    exclude_indices: List[int] = []
    groups: dict = {}  # {"G1": [0,1,2], "G2": [5,6,7], ...}
    test_method: str = "ttest"  # ttest | ks | mannwhitney | fisherz
    top_n: int = 10
    target_param: str = ""  # fisherz: vs Target mode
    exclude_cols: List[str] = []  # columns to exclude
    r_threshold: float = 0.0  # fisherz: only keep pairs where max |r| >= threshold


@router.post("/gb-test")
async def gb_test(
    req: GBTestRequest,
    session_id: str = Query("default"),
    analysis_service=Depends(get_intelligent_analysis_service),
):
    """Run G/B statistical test across groups per variable."""
    import numpy as np
    import pandas as pd
    from scipy import stats as sp_stats

    uploads_dir = analysis_service.base_dir / session_id / "uploads"
    csv_path = _find_csv(uploads_dir, req.file_id, analysis_service)
    df = pd.read_csv(csv_path, encoding="utf-8-sig")

    # Apply same filters
    for f in req.filters:
        if f.exclude_empty and f.column in df.columns:
            df = df[df[f.column].notna() & (df[f.column].astype(str).str.strip() != "")]
        kw = (f.keyword or "").strip()
        if kw and f.column in df.columns:
            col_series = df[f.column]
            import re as _re

            m = _re.match(r"^([><=!]+)\s*([\d.]+)$", kw)
            if m and pd.api.types.is_numeric_dtype(col_series):
                op, val = m.group(1), float(m.group(2))
                col_num = pd.to_numeric(col_series, errors="coerce")
                if op == ">":
                    df = df[col_num > val]
                elif op == ">=":
                    df = df[col_num >= val]
                elif op == "<":
                    df = df[col_num < val]
                elif op == "<=":
                    df = df[col_num <= val]
                elif op in ("=", "=="):
                    df = df[col_num == val]
                elif op == "!=":
                    df = df[col_num != val]
            else:
                df = df[df[f.column].astype(str).str.contains(kw, case=False, na=False)]

    df = df.reset_index(drop=True)
    if req.exclude_indices:
        valid = [i for i in req.exclude_indices if 0 <= i < len(df)]
        if valid:
            df = df.drop(index=valid).reset_index(drop=True)

    num_cols = df.select_dtypes(include="number").columns.tolist()
    sub = df[num_cols].copy()
    thresh = int(len(sub) * 0.5)
    sub = sub.dropna(axis=1, thresh=thresh)
    sub = sub.fillna(sub.median())
    sub = sub.loc[:, sub.std() > 0]
    # Exclude user-specified columns
    if req.exclude_cols:
        sub = sub.drop(
            columns=[c for c in req.exclude_cols if c in sub.columns], errors="ignore"
        )
    col_names = sub.columns.tolist()

    if not req.groups or len(req.groups) < 2:
        raise HTTPException(status_code=400, detail="至少需要 2 組")

    # Build group data
    group_names = list(req.groups.keys())
    group_indices = {}
    for gname, idxs in req.groups.items():
        valid = [i for i in idxs if 0 <= i < len(sub)]
        if len(valid) < 2:
            raise HTTPException(status_code=400, detail=f"組 {gname} 樣本不足 2 筆")
        group_indices[gname] = valid

    n_groups = len(group_names)
    results = []

    def _box_stats(arr):
        """Compute box plot statistics."""
        q1, med, q3 = np.percentile(arr, [25, 50, 75])
        iqr = q3 - q1
        wlo = (
            float(arr[arr >= q1 - 1.5 * iqr].min())
            if len(arr[arr >= q1 - 1.5 * iqr])
            else float(q1)
        )
        whi = (
            float(arr[arr <= q3 + 1.5 * iqr].max())
            if len(arr[arr <= q3 + 1.5 * iqr])
            else float(q3)
        )
        outliers = arr[(arr < wlo) | (arr > whi)].tolist()
        return {
            "q1": round(float(q1), 4),
            "median": round(float(med), 4),
            "q3": round(float(q3), 4),
            "whisker_lo": round(float(wlo), 4),
            "whisker_hi": round(float(whi), 4),
            "outliers": [round(float(o), 4) for o in outliers],
            "n": len(arr),
        }

    def _fisher_z_test(r1, n1, r2, n2):
        """Fisher Z-Transformation test for comparing two correlations."""
        if n1 < 4 or n2 < 4:
            return 0.0, 1.0
        z1 = np.arctanh(np.clip(r1, -0.999, 0.999))
        z2 = np.arctanh(np.clip(r2, -0.999, 0.999))
        se = np.sqrt(1.0 / (n1 - 3) + 1.0 / (n2 - 3))
        if se == 0:
            return 0.0, 1.0
        z_stat = (z1 - z2) / se
        p_val = 2.0 * (1.0 - sp_stats.norm.cdf(abs(z_stat)))
        return float(z_stat), float(p_val)

    def _pearson_r(x, y):
        """Safe Pearson correlation."""
        mask = ~(np.isnan(x) | np.isnan(y))
        x2, y2 = x[mask], y[mask]
        if len(x2) < 4 or np.std(x2) == 0 or np.std(y2) == 0:
            return 0.0, len(x2)
        r, _ = sp_stats.pearsonr(x2, y2)
        return float(r), len(x2)

    # ---- Fisher Z: All Pairs mode (vectorized) ----
    if req.test_method == "fisherz" and not req.target_param:
        from itertools import combinations

        n_cols = len(col_names)
        # Per-group correlation matrices (vectorized)
        corr_mats = {}
        group_ns = {}
        for g in group_names:
            g_data = (
                sub.iloc[group_indices[g]].values.astype(float).T
            )  # (n_cols, n_samples)
            group_ns[g] = len(group_indices[g])
            if group_ns[g] >= 4:
                corr_mats[g] = np.corrcoef(g_data)
                # Replace NaN with 0
                corr_mats[g] = np.nan_to_num(corr_mats[g], nan=0.0)
            else:
                corr_mats[g] = np.zeros((n_cols, n_cols))

        # Fisher Z test for all pairs using matrices
        candidates = []
        for ci, cj in combinations(range(n_cols), 2):
            r_vals = {}
            for g in group_names:
                r_vals[g] = round(float(corr_mats[g][ci, cj]), 4)

            # r_threshold filter: at least one group has |r| >= threshold
            if req.r_threshold > 0:
                max_abs_r = max(abs(r_vals[g]) for g in group_names)
                if max_abs_r < req.r_threshold:
                    continue

            try:
                if n_groups == 2:
                    stat, pval = _fisher_z_test(
                        r_vals[group_names[0]],
                        group_ns[group_names[0]],
                        r_vals[group_names[1]],
                        group_ns[group_names[1]],
                    )
                else:
                    min_p, min_s = 1.0, 0.0
                    for gi in range(n_groups):
                        for gj in range(gi + 1, n_groups):
                            s, p = _fisher_z_test(
                                r_vals[group_names[gi]],
                                group_ns[group_names[gi]],
                                r_vals[group_names[gj]],
                                group_ns[group_names[gj]],
                            )
                            if p < min_p:
                                min_p, min_s = p, s
                    stat, pval = min_s, min_p
                if np.isnan(pval):
                    pval = 1.0
            except Exception:
                stat, pval = 0.0, 1.0

            candidates.append(
                {
                    "ci": ci,
                    "cj": cj,
                    "parameter": f"{col_names[ci]} vs {col_names[cj]}",
                    "param_x": col_names[ci],
                    "param_y": col_names[cj],
                    "statistic": round(float(stat), 6),
                    "p_value": round(float(pval), 6),
                    "r_values": r_vals,
                }
            )

        candidates.sort(key=lambda x: x["p_value"])
        top_results = candidates[: min(req.top_n, len(candidates))]

        # Build scatter_data only for top results
        for item in top_results:
            ci, cj = item.pop("ci"), item.pop("cj")
            x_all = sub.iloc[:, ci].values.astype(float)
            y_all = sub.iloc[:, cj].values.astype(float)
            scatter_data = {}
            for g in group_names:
                gx = x_all[group_indices[g]]
                gy = y_all[group_indices[g]]
                scatter_data[g] = {
                    "x": [round(float(v), 4) for v in gx],
                    "y": [round(float(v), 4) for v in gy],
                }
            item["scatter_data"] = scatter_data

        return {
            "results": top_results,
            "n_variables": len(col_names),
            "n_pairs": len(candidates),
            "group_names": group_names,
            "group_sizes": {g: len(group_indices[g]) for g in group_names},
            "test_method": "fisherz",
            "mode": "all_pairs",
        }

    # ---- Fisher Z: vs Target mode ----
    if req.test_method == "fisherz" and req.target_param:
        if req.target_param not in col_names:
            raise HTTPException(
                status_code=400, detail=f"Target {req.target_param} 不在數值欄位中"
            )
        target_ci = col_names.index(req.target_param)
        target_data = sub.iloc[:, target_ci].values.astype(float)

        for ci, col in enumerate(col_names):
            if col == req.target_param:
                continue
            col_data = sub.iloc[:, ci].values.astype(float)

            r_vals = {}
            scatter_data = {}
            ns = {}
            for g in group_names:
                gx = col_data[group_indices[g]]
                gy = target_data[group_indices[g]]
                r, n = _pearson_r(gx, gy)
                r_vals[g] = round(r, 4)
                ns[g] = n
                scatter_data[g] = {
                    "x": [round(float(v), 4) for v in gx],
                    "y": [round(float(v), 4) for v in gy],
                }

            # r_threshold filter
            if req.r_threshold > 0:
                max_abs_r = max(abs(r_vals[g]) for g in group_names)
                if max_abs_r < req.r_threshold:
                    continue

            try:
                if n_groups == 2:
                    stat, pval = _fisher_z_test(
                        r_vals[group_names[0]],
                        ns[group_names[0]],
                        r_vals[group_names[1]],
                        ns[group_names[1]],
                    )
                else:
                    min_p, min_s = 1.0, 0.0
                    for gi in range(n_groups):
                        for gj in range(gi + 1, n_groups):
                            s, p = _fisher_z_test(
                                r_vals[group_names[gi]],
                                ns[group_names[gi]],
                                r_vals[group_names[gj]],
                                ns[group_names[gj]],
                            )
                            if p < min_p:
                                min_p, min_s = p, s
                    stat, pval = min_s, min_p
                if np.isnan(pval):
                    pval = 1.0
            except Exception:
                stat, pval = 0.0, 1.0

            results.append(
                {
                    "parameter": f"{col} vs {req.target_param}",
                    "param_x": col,
                    "param_y": req.target_param,
                    "statistic": round(float(stat), 6),
                    "p_value": round(float(pval), 6),
                    "r_values": r_vals,
                    "scatter_data": scatter_data,
                }
            )

        results.sort(key=lambda x: x["p_value"])
        top_results = results[: min(req.top_n, len(results))]
        return {
            "results": top_results,
            "n_variables": len(col_names),
            "group_names": group_names,
            "group_sizes": {g: len(group_indices[g]) for g in group_names},
            "test_method": "fisherz",
            "mode": "vs_target",
            "target_param": req.target_param,
        }

    # ---- Standard tests (ttest, ks, mannwhitney) ----
    for ci, col in enumerate(col_names):
        col_data = sub.iloc[:, ci].values
        group_arrs = [col_data[group_indices[g]].astype(float) for g in group_names]

        try:
            method = req.test_method
            if method == "ttest":
                if n_groups == 2:
                    stat, pval = sp_stats.ttest_ind(
                        group_arrs[0], group_arrs[1], equal_var=False
                    )
                else:
                    stat, pval = sp_stats.f_oneway(*group_arrs)
            elif method == "ks":
                if n_groups == 2:
                    stat, pval = sp_stats.ks_2samp(group_arrs[0], group_arrs[1])
                else:
                    min_p, min_s = 1.0, 0.0
                    for i in range(n_groups):
                        for j in range(i + 1, n_groups):
                            s, p = sp_stats.ks_2samp(group_arrs[i], group_arrs[j])
                            if p < min_p:
                                min_p, min_s = p, s
                    stat, pval = min_s, min_p
            elif method == "mannwhitney":
                if n_groups == 2:
                    stat, pval = sp_stats.mannwhitneyu(
                        group_arrs[0], group_arrs[1], alternative="two-sided"
                    )
                else:
                    min_p, min_s = 1.0, 0.0
                    for i in range(n_groups):
                        for j in range(i + 1, n_groups):
                            s, p = sp_stats.mannwhitneyu(
                                group_arrs[i], group_arrs[j], alternative="two-sided"
                            )
                            if p < min_p:
                                min_p, min_s = p, s
                    stat, pval = min_s, min_p
            else:
                stat, pval = 0, 1.0

            if np.isnan(pval) or np.isinf(pval):
                pval = 1.0
            if np.isnan(stat) or np.isinf(stat):
                stat = 0.0
        except Exception:
            stat, pval = 0.0, 1.0

        box_data = {}
        values_data = {}
        for gi, g in enumerate(group_names):
            box_data[g] = _box_stats(group_arrs[gi])
            values_data[g] = [round(float(v), 4) for v in group_arrs[gi]]

        results.append(
            {
                "parameter": col,
                "statistic": round(float(stat), 6),
                "p_value": round(float(pval), 6),
                "box_data": box_data,
                "values": values_data,
            }
        )

    # Sort by p_value ascending, take top_n
    results.sort(key=lambda x: x["p_value"])
    top_results = results[: min(req.top_n, len(results))]

    return {
        "results": top_results,
        "n_variables": len(col_names),
        "group_names": group_names,
        "group_sizes": {g: len(group_indices[g]) for g in group_names},
        "test_method": req.test_method,
    }


@router.get("/gb-target-groups")
async def gb_target_groups(
    file_id: str = Query(...),
    column: str = Query(...),
    session_id: str = Query("default"),
    analysis_service: AnalysisService = Depends(get_intelligent_analysis_service),
):
    """Group row indices by unique values in target column."""
    import pandas as pd

    uploads_dir = analysis_service.base_dir / session_id / "uploads"
    csv_path = _find_csv(uploads_dir, file_id, analysis_service)
    df = pd.read_csv(csv_path, encoding="utf-8-sig")

    if column not in df.columns:
        raise HTTPException(status_code=400, detail=f"欄位 {column} 不存在")

    groups = {}
    for val in df[column].dropna().unique():
        label = str(val).strip()
        if not label:
            continue
        idxs = df.index[df[column].astype(str).str.strip() == label].tolist()
        if len(idxs) >= 2:
            groups[label] = idxs

    if len(groups) < 2:
        raise HTTPException(status_code=400, detail="分組不足 2 組")

    return groups


@router.get("/gb-column-values")
async def gb_column_values(
    file_id: str = Query(...),
    column: str = Query(...),
    session_id: str = Query("default"),
    analysis_service: AnalysisService = Depends(get_intelligent_analysis_service),
):
    """Return raw values of a column for trend chart."""
    import pandas as pd
    import numpy as np

    uploads_dir = analysis_service.base_dir / session_id / "uploads"
    csv_path = _find_csv(uploads_dir, file_id, analysis_service)
    df = pd.read_csv(csv_path, encoding="utf-8-sig")

    if column not in df.columns:
        raise HTTPException(status_code=400, detail=f"欄位 {column} 不存在")

    series = pd.to_numeric(df[column], errors="coerce")
    values = [round(float(v), 4) if not np.isnan(v) else None for v in series]
    return {"column": column, "values": values, "n": len(values)}
