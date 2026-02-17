"""
平行座標圖工具 (Parallel Coordinates)
- 多參數歸一化比較,用於跨批次/好壞批差異視覺化
- 使用 Z-Score 歸一化,使不同量綱的參數可以在同一尺度上比較
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List
from .base import AnalysisTool
import logging

logger = logging.getLogger(__name__)


class ParallelCoordinatesTool(AnalysisTool):
    """平行座標圖: 多參數跨批次比較,識別好批/壞批的關鍵差異"""

    @property
    def name(self) -> str:
        return "parallel_coordinates"

    @property
    def description(self) -> str:
        return (
            "平行座標圖: 將多個參數歸一化到同一尺度,以線條連接各參數值,"
            "用於比較好批 vs 壞批的參數特徵差異,找出最具區別力的參數。"
        )

    @property
    def required_params(self) -> List[str]:
        return ["file_id", "target_columns"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        try:
            file_id = params.get("file_id")
            target_cols_raw = params.get("target_columns", [])
            color_param = params.get("color_param")
            focus_range = params.get("target_segments") or params.get("focus_range")
            top_k = params.get("top_k", 10)

            # Parse target_columns
            if isinstance(target_cols_raw, str):
                if target_cols_raw.lower() == "all":
                    target_cols_raw = "all"
                else:
                    target_cols_raw = [c.strip() for c in target_cols_raw.split(",")]

            # Load data
            summary = self.analysis_service.load_summary(session_id, file_id)
            if not summary:
                return {"status": "ERROR", "message": "No summary data available"}
            filename = summary["filename"]
            csv_path = (
                self.analysis_service.base_dir / session_id / "uploads" / filename
            )
            df = pd.read_csv(csv_path)

            # Filter numeric columns
            numeric_df = df.select_dtypes(include=[np.number]).copy()

            # Apply focus range if specified
            if focus_range:
                indices = self.parse_indices(focus_range, max_len=len(numeric_df))
                if indices:
                    numeric_df = numeric_df.iloc[indices]

            # Select columns
            if target_cols_raw == "all":
                # Use top_k most variable columns (by CV)
                cv = numeric_df.std() / (numeric_df.mean().abs() + 1e-10)
                selected_cols = cv.nlargest(top_k).index.tolist()
            else:
                selected_cols = [c for c in target_cols_raw if c in numeric_df.columns]

            if len(selected_cols) < 2:
                return {
                    "status": "ERROR",
                    "message": f"需要至少 2 個有效數值欄位,目前只有 {len(selected_cols)} 個",
                }

            # Determine grouping (good/bad) based on color_param
            has_groups = False
            if color_param and color_param in numeric_df.columns:
                has_groups = True
                target_series = numeric_df[color_param].dropna()
                q25 = target_series.quantile(0.25)
                q75 = target_series.quantile(0.75)
                good_mask = numeric_df[color_param] <= q25
                bad_mask = numeric_df[color_param] >= q75
            else:
                # No grouping — just show all data
                good_mask = pd.Series([True] * len(numeric_df), index=numeric_df.index)
                bad_mask = pd.Series([False] * len(numeric_df), index=numeric_df.index)

            # Z-Score normalize for parallel coordinates
            work_df = numeric_df[selected_cols].dropna()
            means = work_df.mean()
            stds = work_df.std().replace(0, 1)
            normalized = (work_df - means) / stds

            # Build chart data (sampled for frontend performance)
            max_lines = 60  # max lines to draw
            chart_datasets = []

            if has_groups:
                good_normalized = normalized[
                    good_mask.reindex(normalized.index, fill_value=False)
                ]
                bad_normalized = normalized[
                    bad_mask.reindex(normalized.index, fill_value=False)
                ]

                # Sample good batch lines
                n_good = min(max_lines // 2, len(good_normalized))
                if n_good > 0:
                    good_sample = good_normalized.sample(n=n_good, random_state=42)
                    for i, (_, row) in enumerate(good_sample.iterrows()):
                        chart_datasets.append(
                            {
                                "label": f"Good-{i + 1}" if i == 0 else "",
                                "data": [round(float(v), 3) for v in row.values],
                                "borderColor": "rgba(46, 204, 113, 0.4)",
                                "backgroundColor": "transparent",
                                "borderWidth": 1.5,
                                "pointRadius": 2,
                            }
                        )

                # Sample bad batch lines
                n_bad = min(max_lines // 2, len(bad_normalized))
                if n_bad > 0:
                    bad_sample = bad_normalized.sample(n=n_bad, random_state=42)
                    for i, (_, row) in enumerate(bad_sample.iterrows()):
                        chart_datasets.append(
                            {
                                "label": f"Bad-{i + 1}" if i == 0 else "",
                                "data": [round(float(v), 3) for v in row.values],
                                "borderColor": "rgba(231, 76, 60, 0.4)",
                                "backgroundColor": "transparent",
                                "borderWidth": 1.5,
                                "pointRadius": 2,
                            }
                        )

                # Add group means as bold lines
                if n_good > 0:
                    good_mean = good_normalized.mean()
                    chart_datasets.append(
                        {
                            "label": f"Good Mean (n={len(good_normalized)})",
                            "data": [round(float(v), 3) for v in good_mean.values],
                            "borderColor": "rgba(46, 204, 113, 1)",
                            "backgroundColor": "transparent",
                            "borderWidth": 3,
                            "pointRadius": 4,
                        }
                    )
                if n_bad > 0:
                    bad_mean = bad_normalized.mean()
                    chart_datasets.append(
                        {
                            "label": f"Bad Mean (n={len(bad_normalized)})",
                            "data": [round(float(v), 3) for v in bad_mean.values],
                            "borderColor": "rgba(231, 76, 60, 1)",
                            "backgroundColor": "transparent",
                            "borderWidth": 3,
                            "pointRadius": 4,
                        }
                    )
            else:
                # No grouping — show overall distribution
                n_sample = min(max_lines, len(normalized))
                if n_sample > 0:
                    sample = normalized.sample(n=n_sample, random_state=42)
                    for i, (_, row) in enumerate(sample.iterrows()):
                        chart_datasets.append(
                            {
                                "label": f"Sample-{i + 1}" if i == 0 else "",
                                "data": [round(float(v), 3) for v in row.values],
                                "borderColor": "rgba(52, 152, 219, 0.3)",
                                "backgroundColor": "transparent",
                                "borderWidth": 1,
                                "pointRadius": 2,
                            }
                        )

            # Analytical output: find most discriminating parameters
            discriminating_params = []
            if has_groups:
                good_data = work_df[good_mask.reindex(work_df.index, fill_value=False)]
                bad_data = work_df[bad_mask.reindex(work_df.index, fill_value=False)]
                for col in selected_cols:
                    g_vals = good_data[col].dropna()
                    b_vals = bad_data[col].dropna()
                    if len(g_vals) < 3 or len(b_vals) < 3:
                        continue
                    pooled_std = np.sqrt((g_vals.std() ** 2 + b_vals.std() ** 2) / 2)
                    effect_size = (
                        abs(g_vals.mean() - b_vals.mean()) / pooled_std
                        if pooled_std > 0
                        else 0
                    )
                    discriminating_params.append(
                        {
                            "parameter": col,
                            "effect_size": round(float(effect_size), 4),
                            "good_mean": round(float(g_vals.mean()), 4),
                            "bad_mean": round(float(b_vals.mean()), 4),
                        }
                    )
                discriminating_params.sort(key=lambda x: x["effect_size"], reverse=True)

            # Build chart JSON
            chart_json = {
                "type": "chart",
                "chart_type": "line",
                "title": f"平行座標圖: {', '.join(selected_cols[:5])}{'...' if len(selected_cols) > 5 else ''}",
                "labels": selected_cols,
                "datasets": chart_datasets,
                "options": {
                    "scales": {
                        "y": {
                            "title": {"display": True, "text": "Z-Score (標準化值)"},
                            "grid": {"color": "rgba(0,0,0,0.05)"},
                        },
                        "x": {
                            "title": {"display": True, "text": "參數"},
                        },
                    },
                    "plugins": {
                        "legend": {
                            "labels": {
                                "filter": "function(item) { return item.text !== ''; }"
                            }
                        }
                    },
                },
            }

            return {
                "status": "OK",
                "parameters_analyzed": selected_cols,
                "total_points": len(work_df),
                "good_batch_count": int(good_mask.sum()) if has_groups else None,
                "bad_batch_count": int(bad_mask.sum()) if has_groups else None,
                "top_discriminating": discriminating_params[:5]
                if discriminating_params
                else [],
                "chart": chart_json,
                "interpretation": self._interpret(
                    discriminating_params, has_groups, color_param
                ),
            }

        except Exception as e:
            logger.error(f"ParallelCoordinates error: {e}")
            return {"status": "ERROR", "message": str(e)}

    def _interpret(self, discriminating, has_groups, color_param) -> str:
        if not has_groups or not discriminating:
            return "平行座標圖顯示了各參數的歸一化分佈。"

        lines = [f"以 {color_param} 分割好壞批次後的平行座標分析:"]
        for i, p in enumerate(discriminating[:3]):
            lines.append(
                f"  {i + 1}. {p['parameter']} (效應量={p['effect_size']:.2f}): "
                f"好批均值={p['good_mean']:.4f}, 壞批均值={p['bad_mean']:.4f}"
            )
        if len(discriminating) > 3:
            lines.append(f"  ... 共 {len(discriminating)} 個參數有差異")
        return "\n".join(lines)
