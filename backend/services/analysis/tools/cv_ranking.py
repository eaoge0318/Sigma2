"""
變異係數排名工具 (Coefficient of Variation Ranking)
- CVRankingTool: 對所有參數計算 CV,識別最不穩定/最穩定的參數
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List
from .base import AnalysisTool
import logging

logger = logging.getLogger(__name__)


class CVRankingTool(AnalysisTool):
    """變異係數 (CV) 排名: 跨量綱比較參數波動性"""

    @property
    def name(self) -> str:
        return "cv_ranking"

    @property
    def description(self) -> str:
        return (
            "計算所有參數的變異係數 (Coefficient of Variation = std/|mean|),"
            "按波動性排名。CV 越大代表參數越不穩定,可用於快速定位製程中最不可控的變數。"
            "比 Z-Score 更適合跨量綱比較。"
        )

    @property
    def required_params(self) -> List[str]:
        return ["file_id"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        try:
            file_id = params.get("file_id")
            top_k = int(params.get("top_k", 15))
            focus_range = params.get("focus_range")

            # Load data
            summary = self.analysis_service.load_summary(session_id, file_id)
            if not summary:
                return {"status": "ERROR", "message": "No summary data available"}
            filename = summary["filename"]
            csv_path = (
                self.analysis_service.get_csv_path(session_id, filename)
            )
            df = pd.read_csv(csv_path)

            # Apply focus range if specified
            if focus_range:
                try:
                    parts = str(focus_range).replace(" ", "").split(",")
                    if len(parts) == 2:
                        start, end = int(parts[0]), int(parts[1])
                        df = df.iloc[start : end + 1]
                except (ValueError, IndexError):
                    pass

            # Select numeric columns
            numeric_df = df.select_dtypes(include=[np.number])

            # Remove constant columns (std == 0)
            stds = numeric_df.std()
            means = numeric_df.mean()
            numeric_df = numeric_df[stds[stds > 0].index]

            # Calculate CV + Drift for each parameter
            cv_results = []
            for col in numeric_df.columns:
                col_mean = means[col]
                col_std = stds[col]

                # Skip if mean is near zero (CV is meaningless)
                if abs(col_mean) < 1e-10:
                    continue

                cv = col_std / abs(col_mean)

                # [NEW] 線性回歸斜率 — 偵測整段漂移 (Drift)
                series = numeric_df[col].dropna()
                x = np.arange(len(series))
                slope = float(np.polyfit(x, series.values, 1)[0])
                drift_total = abs(slope * len(series))
                drift_sigma = drift_total / (float(col_std) + 1e-10)

                if drift_sigma > 5:
                    drift_grade = "severe_drift"
                elif drift_sigma > 3:
                    drift_grade = "significant_drift"
                elif drift_sigma > 1.5:
                    drift_grade = "moderate_drift"
                elif drift_sigma > 0.5:
                    drift_grade = "mild_drift"
                else:
                    drift_grade = "stable"

                # Stability classification
                if cv < 0.05:
                    stability = "very_stable"
                elif cv < 0.10:
                    stability = "stable"
                elif cv < 0.20:
                    stability = "moderate"
                elif cv < 0.50:
                    stability = "volatile"
                else:
                    stability = "highly_volatile"

                cv_results.append(
                    {
                        "parameter": col,
                        "cv": round(float(cv), 6),
                        "mean": round(float(col_mean), 4),
                        "std": round(float(col_std), 4),
                        "min": round(float(numeric_df[col].min()), 4),
                        "max": round(float(numeric_df[col].max()), 4),
                        "stability": stability,
                        "slope": round(slope, 6),
                        "drift_total_sigma": round(float(drift_sigma), 2),
                        "drift_grade": drift_grade,
                    }
                )

            # Sort by CV descending (most volatile first)
            cv_sorted = sorted(cv_results, key=lambda x: x["cv"], reverse=True)

            # [NEW] Sort by drift severity
            drift_sorted = sorted(
                cv_results, key=lambda x: x["drift_total_sigma"], reverse=True
            )

            # Summary statistics
            all_cvs = [r["cv"] for r in cv_results]
            stability_counts = {}
            for r in cv_results:
                s = r["stability"]
                stability_counts[s] = stability_counts.get(s, 0) + 1

            drift_counts = {}
            for r in cv_results:
                d = r["drift_grade"]
                drift_counts[d] = drift_counts.get(d, 0) + 1

            return {
                "status": "OK",
                "total_parameters": len(cv_results),
                "most_volatile": cv_sorted[:top_k],
                "most_stable": cv_sorted[-top_k:][::-1]
                if len(cv_sorted) > top_k
                else [],
                "most_drifting": drift_sorted[:top_k],
                "stability_distribution": stability_counts,
                "drift_distribution": drift_counts,
                "cv_statistics": {
                    "median_cv": round(float(np.median(all_cvs)), 6) if all_cvs else 0,
                    "mean_cv": round(float(np.mean(all_cvs)), 6) if all_cvs else 0,
                    "max_cv": round(float(max(all_cvs)), 6) if all_cvs else 0,
                },
            }

        except Exception as e:
            logger.error(f"CVRanking error: {e}")
            return {"status": "ERROR", "message": str(e)}
