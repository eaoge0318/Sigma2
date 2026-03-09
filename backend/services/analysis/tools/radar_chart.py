"""
雷達圖工具 (Radar Chart)
- 多維度參數特徵對比 (好批 vs 壞批 / 各組 Regime)
- 使用 Min-Max 歸一化到 [0, 1] 使不同量綱可比較
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List
from .base import AnalysisTool
import logging

logger = logging.getLogger(__name__)


class RadarChartTool(AnalysisTool):
    """雷達圖: 多維度參數特徵對比, 好批 vs 壞批"""

    @property
    def name(self) -> str:
        return "radar_chart"

    @property
    def description(self) -> str:
        return (
            "雷達圖: 將多個參數歸一化後以雷達圖展示,"
            "適合比較好批 vs 壞批或不同操作 Regime 的多維度參數特徵。"
        )

    @property
    def required_params(self) -> List[str]:
        return ["file_id", "target_columns"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        try:
            file_id = params.get("file_id")
            target_cols_raw = params.get("target_columns", [])
            color_param = params.get("color_param")
            group_by = params.get("group_by")  # Optional: column to group by
            top_k = params.get("top_k", 8)  # Max axes on radar (readability)

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

            # Select columns
            if target_cols_raw == "all":
                # For radar chart, use top_k most variable columns
                cv = numeric_df.std() / (numeric_df.mean().abs() + 1e-10)
                selected_cols = cv.nlargest(top_k).index.tolist()
            else:
                selected_cols = [c for c in target_cols_raw if c in numeric_df.columns]

            # Radar chart works best with 3-8 axes
            if len(selected_cols) > top_k:
                # Use most variable among selected
                cv = numeric_df[selected_cols].std() / (
                    numeric_df[selected_cols].mean().abs() + 1e-10
                )
                selected_cols = cv.nlargest(top_k).index.tolist()

            if len(selected_cols) < 3:
                return {
                    "status": "ERROR",
                    "message": f"雷達圖需要至少 3 個軸,目前只有 {len(selected_cols)} 個有效欄位",
                }

            # Work with selected columns
            work_df = numeric_df[selected_cols].dropna()

            # Min-Max normalize to [0, 1] for radar
            mins = work_df.min()
            maxs = work_df.max()
            ranges = (maxs - mins).replace(0, 1)
            normalized = (work_df - mins) / ranges

            # Determine groups
            chart_datasets = []
            group_stats = []

            if color_param and color_param in numeric_df.columns:
                # Split by color_param (good/bad quartile)
                target_series = numeric_df[color_param].dropna()
                q25 = target_series.quantile(0.25)
                q75 = target_series.quantile(0.75)

                good_mask = numeric_df[color_param] <= q25
                bad_mask = numeric_df[color_param] >= q75

                good_normalized = normalized[
                    good_mask.reindex(normalized.index, fill_value=False)
                ]
                bad_normalized = normalized[
                    bad_mask.reindex(normalized.index, fill_value=False)
                ]

                if len(good_normalized) >= 3:
                    good_mean = good_normalized.mean()
                    chart_datasets.append(
                        {
                            "label": f"Good (n={len(good_normalized)}, {color_param} <= {q25:.2f})",
                            "data": [round(float(v), 3) for v in good_mean.values],
                            "borderColor": "rgba(46, 204, 113, 1)",
                            "backgroundColor": "rgba(46, 204, 113, 0.2)",
                            "borderWidth": 2,
                            "pointRadius": 4,
                        }
                    )
                    group_stats.append(
                        {
                            "group": "Good",
                            "count": len(good_normalized),
                            "means": {
                                col: round(float(good_normalized[col].mean()), 4)
                                for col in selected_cols
                            },
                        }
                    )

                if len(bad_normalized) >= 3:
                    bad_mean = bad_normalized.mean()
                    chart_datasets.append(
                        {
                            "label": f"Bad (n={len(bad_normalized)}, {color_param} >= {q75:.2f})",
                            "data": [round(float(v), 3) for v in bad_mean.values],
                            "borderColor": "rgba(231, 76, 60, 1)",
                            "backgroundColor": "rgba(231, 76, 60, 0.2)",
                            "borderWidth": 2,
                            "pointRadius": 4,
                        }
                    )
                    group_stats.append(
                        {
                            "group": "Bad",
                            "count": len(bad_normalized),
                            "means": {
                                col: round(float(bad_normalized[col].mean()), 4)
                                for col in selected_cols
                            },
                        }
                    )

                # Also add overall mean for reference
                overall_mean = normalized.mean()
                chart_datasets.append(
                    {
                        "label": f"Overall (n={len(normalized)})",
                        "data": [round(float(v), 3) for v in overall_mean.values],
                        "borderColor": "rgba(149, 165, 166, 0.8)",
                        "backgroundColor": "transparent",
                        "borderWidth": 1,
                        "borderDash": [5, 5],
                        "pointRadius": 3,
                    }
                )

            elif group_by and group_by in df.columns:
                # Split by categorical group_by column
                colors = [
                    ("rgba(46, 204, 113, 1)", "rgba(46, 204, 113, 0.15)"),
                    ("rgba(231, 76, 60, 1)", "rgba(231, 76, 60, 0.15)"),
                    ("rgba(52, 152, 219, 1)", "rgba(52, 152, 219, 0.15)"),
                    ("rgba(241, 196, 15, 1)", "rgba(241, 196, 15, 0.15)"),
                    ("rgba(155, 89, 182, 1)", "rgba(155, 89, 182, 0.15)"),
                ]
                groups = df[group_by].dropna().unique()[:5]  # Max 5 groups
                for idx, group_val in enumerate(groups):
                    mask = df[group_by] == group_val
                    group_normalized = normalized[
                        mask.reindex(normalized.index, fill_value=False)
                    ]
                    if len(group_normalized) < 3:
                        continue
                    group_mean = group_normalized.mean()
                    border_color, bg_color = colors[idx % len(colors)]
                    chart_datasets.append(
                        {
                            "label": f"{group_by}={group_val} (n={len(group_normalized)})",
                            "data": [round(float(v), 3) for v in group_mean.values],
                            "borderColor": border_color,
                            "backgroundColor": bg_color,
                            "borderWidth": 2,
                            "pointRadius": 4,
                        }
                    )
                    group_stats.append(
                        {
                            "group": str(group_val),
                            "count": len(group_normalized),
                            "means": {
                                col: round(float(group_normalized[col].mean()), 4)
                                for col in selected_cols
                            },
                        }
                    )

            else:
                # No grouping — show overall mean radar
                overall_mean = normalized.mean()
                chart_datasets.append(
                    {
                        "label": f"Overall (n={len(normalized)})",
                        "data": [round(float(v), 3) for v in overall_mean.values],
                        "borderColor": "rgba(52, 152, 219, 1)",
                        "backgroundColor": "rgba(52, 152, 219, 0.2)",
                        "borderWidth": 2,
                        "pointRadius": 4,
                    }
                )

            # Shorten column names for display (remove common prefixes)
            display_labels = self._shorten_labels(selected_cols)

            # Build Chart.js radar config
            chart_json = {
                "type": "chart",
                "chart_type": "radar",
                "title": f"雷達圖: {color_param or group_by or '全局'} 多維度特徵比較",
                "labels": display_labels,
                "datasets": chart_datasets,
                "options": {
                    "scales": {
                        "r": {
                            "beginAtZero": True,
                            "max": 1.0,
                            "ticks": {"stepSize": 0.2},
                        }
                    },
                },
            }

            # Find most different dimensions between groups
            key_differences = []
            if len(group_stats) >= 2:
                g1 = group_stats[0]["means"]
                g2 = group_stats[1]["means"]
                for col in selected_cols:
                    diff = abs(g1.get(col, 0) - g2.get(col, 0))
                    key_differences.append(
                        {"parameter": col, "normalized_diff": round(diff, 4)}
                    )
                key_differences.sort(key=lambda x: x["normalized_diff"], reverse=True)

            return {
                "status": "OK",
                "parameters_analyzed": selected_cols,
                "total_points": len(work_df),
                "groups": group_stats,
                "key_differences": key_differences[:5],
                "chart": chart_json,
                "interpretation": self._interpret(
                    group_stats, key_differences, selected_cols
                ),
            }

        except Exception as e:
            logger.error(f"RadarChart error: {e}")
            return {"status": "ERROR", "message": str(e)}

    def _shorten_labels(self, labels: List[str]) -> List[str]:
        """Shorten long parameter names for radar chart readability"""
        if len(labels) <= 1:
            return labels

        # Find common prefix
        prefix = labels[0]
        for label in labels[1:]:
            while not label.startswith(prefix) and prefix:
                prefix = prefix[:-1]

        # Only remove prefix if it's a significant portion and ends with a separator
        if len(prefix) > 3 and prefix[-1] in "-_":
            return [label[len(prefix) :] for label in labels]
        return labels

    def _interpret(self, group_stats, key_diffs, selected_cols) -> str:
        if not group_stats:
            return "雷達圖顯示了各參數的歸一化特徵分佈。"

        lines = []
        if len(group_stats) >= 2:
            g1, g2 = group_stats[0], group_stats[1]
            lines.append(
                f"比較 {g1['group']} (n={g1['count']}) vs {g2['group']} (n={g2['count']}):"
            )
            for i, d in enumerate(key_diffs[:3]):
                lines.append(
                    f"  {i + 1}. {d['parameter']}: 差異={d['normalized_diff']:.3f}"
                )
            if key_diffs:
                lines.append(
                    f"最大差異參數: {key_diffs[0]['parameter']} "
                    f"(歸一化差異 {key_diffs[0]['normalized_diff']:.3f})"
                )
        else:
            lines.append(f"群組 {group_stats[0]['group']} 的多維度特徵概況。")

        return "\n".join(lines)
