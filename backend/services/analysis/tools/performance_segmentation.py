"""
效能分割與操作窗口工具 (Performance Segmentation & Operating Window)
- PerformanceSegmentationTool: 依目標變數分割好批/壞批,比較參數差異
- OperatingWindowTool: 從好批次統計生成 SOP 建議表
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List
from .base import AnalysisTool
import logging

logger = logging.getLogger(__name__)


class PerformanceSegmentationTool(AnalysisTool):
    """依目標變數效能分割好批/壞批,分析參數差異"""

    @property
    def name(self) -> str:
        return "performance_segmentation"

    @property
    def description(self) -> str:
        return (
            "依目標變數排序,自動分割為好批次 (Top 25%) 與壞批次 (Bottom 25%),"
            "比較每個參數在兩組之間的差異,找出影響效能的關鍵參數。"
        )

    @property
    def required_params(self) -> List[str]:
        return ["file_id", "target"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        try:
            file_id = params.get("file_id")
            target = params.get("target")
            split_method = params.get(
                "split_method", "quartile"
            )  # quartile / median / threshold
            threshold_value = params.get("threshold", None)
            top_k = params.get("top_k", 10)

            # Load data
            summary = self.analysis_service.load_summary(session_id, file_id)
            if not summary:
                return {"status": "ERROR", "message": "No summary data available"}
            filename = summary["filename"]
            csv_path = (
                self.analysis_service.base_dir / session_id / "uploads" / filename
            )
            df = pd.read_csv(csv_path)

            if target not in df.columns:
                return {
                    "status": "ERROR",
                    "message": f"Target column '{target}' not found",
                }

            # Filter numeric columns only
            numeric_df = df.select_dtypes(include=[np.number]).copy()
            if target not in numeric_df.columns:
                return {
                    "status": "ERROR",
                    "message": f"Target '{target}' is not numeric",
                }

            target_series = numeric_df[target].dropna()

            # Split into good/bad segments
            if split_method == "quartile":
                q25 = target_series.quantile(0.25)
                q75 = target_series.quantile(0.75)
                good_mask = numeric_df[target] <= q25  # Lower is better (default)
                bad_mask = numeric_df[target] >= q75
                split_desc = f"Target={target}, Good: <= {q25:.4f} (Q25), Bad: >= {q75:.4f} (Q75)"
            elif split_method == "median":
                median = target_series.median()
                good_mask = numeric_df[target] <= median
                bad_mask = numeric_df[target] > median
                split_desc = f"Target={target}, Good: <= {median:.4f} (Median), Bad: > {median:.4f}"
            elif split_method == "threshold" and threshold_value is not None:
                good_mask = numeric_df[target] <= float(threshold_value)
                bad_mask = numeric_df[target] > float(threshold_value)
                split_desc = f"Target={target}, Good: <= {threshold_value}, Bad: > {threshold_value}"
            else:
                q25 = target_series.quantile(0.25)
                q75 = target_series.quantile(0.75)
                good_mask = numeric_df[target] <= q25
                bad_mask = numeric_df[target] >= q75
                split_desc = f"Target={target}, Good: <= {q25:.4f} (Q25), Bad: >= {q75:.4f} (Q75)"

            good_df = numeric_df[good_mask]
            bad_df = numeric_df[bad_mask]

            if len(good_df) < 5 or len(bad_df) < 5:
                return {
                    "status": "WARNING",
                    "message": f"Insufficient data: good={len(good_df)}, bad={len(bad_df)}",
                }

            # Compare parameters between good and bad
            feature_cols = [c for c in numeric_df.columns if c != target]
            comparisons = []

            for col in feature_cols:
                good_vals = good_df[col].dropna()
                bad_vals = bad_df[col].dropna()

                if len(good_vals) < 3 or len(bad_vals) < 3:
                    continue

                good_mean = good_vals.mean()
                bad_mean = bad_vals.mean()
                diff = bad_mean - good_mean

                # Normalized difference (effect size)
                pooled_std = np.sqrt((good_vals.std() ** 2 + bad_vals.std() ** 2) / 2)
                effect_size = abs(diff / pooled_std) if pooled_std > 0 else 0

                # Direction: should we increase or decrease this parameter?
                direction = "decrease" if diff > 0 else "increase"

                comparisons.append(
                    {
                        "parameter": col,
                        "good_batch_mean": round(good_mean, 4),
                        "bad_batch_mean": round(bad_mean, 4),
                        "difference": round(diff, 4),
                        "effect_size": round(effect_size, 4),
                        "suggested_direction": direction,
                        "good_batch_range": f"{good_vals.min():.4f} ~ {good_vals.max():.4f}",
                    }
                )

            # Sort by effect size (most impactful first)
            comparisons.sort(key=lambda x: x["effect_size"], reverse=True)
            top_comparisons = comparisons[:top_k]

            # 增加明確的文字解讀, 防止 LLM 將 target 與 discriminating parameters 混淆
            interpretation = (
                f"以 {target} 為分組依據 (split_description: {split_desc})。"
                f" 下列 top_discriminating_parameters 是【其他參數】在好壞批次間的差異,"
                f" 不是 {target} 本身的數值。"
            )

            return {
                "status": "OK",
                "target": target,
                "interpretation": interpretation,
                "split_method": split_method,
                "split_description": split_desc,
                "good_batch_count": int(good_mask.sum()),
                "bad_batch_count": int(bad_mask.sum()),
                "target_stats": {
                    "good_mean": round(good_df[target].mean(), 4),
                    "bad_mean": round(bad_df[target].mean(), 4),
                },
                "top_discriminating_parameters": top_comparisons,
                "total_parameters_analyzed": len(comparisons),
            }

        except Exception as e:
            logger.error(f"PerformanceSegmentation error: {e}")
            return {"status": "ERROR", "message": str(e)}


class OperatingWindowTool(AnalysisTool):
    """從好批次統計生成 SOP 建議表 (Operating Window / Golden Batch Profile)"""

    @property
    def name(self) -> str:
        return "generate_operating_window"

    @property
    def description(self) -> str:
        return (
            "基於目標變數的好批次 (Top 25%) 統計,自動生成每個關鍵參數的 "
            "建議設定值 (Target)、操作範圍 (Min-Max)、調整方向,形成 SOP 建議表。"
        )

    @property
    def required_params(self) -> List[str]:
        return ["file_id", "target"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        try:
            file_id = params.get("file_id")
            target = params.get("target")
            direction = params.get("direction", "lower_is_better")
            top_k = params.get("top_k", 10)

            # Load data
            summary = self.analysis_service.load_summary(session_id, file_id)
            if not summary:
                return {"status": "ERROR", "message": "No summary data available"}
            filename = summary["filename"]
            csv_path = (
                self.analysis_service.base_dir / session_id / "uploads" / filename
            )
            df = pd.read_csv(csv_path)

            if target not in df.columns:
                return {
                    "status": "ERROR",
                    "message": f"Target column '{target}' not found",
                }

            numeric_df = df.select_dtypes(include=[np.number]).copy()
            if target not in numeric_df.columns:
                return {
                    "status": "ERROR",
                    "message": f"Target '{target}' is not numeric",
                }

            target_series = numeric_df[target].dropna()
            q25 = target_series.quantile(0.25)
            q75 = target_series.quantile(0.75)

            # Select good batch based on direction
            if direction == "lower_is_better":
                good_mask = numeric_df[target] <= q25
                bad_mask = numeric_df[target] >= q75
            else:
                good_mask = numeric_df[target] >= q75
                bad_mask = numeric_df[target] <= q25

            good_df = numeric_df[good_mask]
            bad_df = numeric_df[bad_mask]

            if len(good_df) < 5:
                return {
                    "status": "WARNING",
                    "message": f"Insufficient good batches: {len(good_df)}",
                }

            # Calculate correlations with target to rank importance
            correlations = numeric_df.corr()[target].drop(target, errors="ignore")
            abs_corr = correlations.abs().sort_values(ascending=False)
            top_features = abs_corr.head(top_k).index.tolist()

            # Generate SOP table
            sop_table = []
            for col in top_features:
                good_vals = good_df[col].dropna()
                bad_vals = bad_df[col].dropna()
                all_vals = numeric_df[col].dropna()

                if len(good_vals) < 3:
                    continue

                corr_val = correlations.get(col, 0)

                # Determine adjustment direction
                if direction == "lower_is_better":
                    adj_direction = "decrease" if corr_val > 0 else "increase"
                else:
                    adj_direction = "increase" if corr_val > 0 else "decrease"

                sop_table.append(
                    {
                        "parameter": col,
                        "correlation_with_target": round(float(corr_val), 4),
                        "suggested_target": round(float(good_vals.mean()), 4),
                        "operating_range_min": round(float(good_vals.quantile(0.1)), 4),
                        "operating_range_max": round(float(good_vals.quantile(0.9)), 4),
                        "current_overall_mean": round(float(all_vals.mean()), 4),
                        "adjustment_direction": adj_direction,
                        "good_batch_std": round(float(good_vals.std()), 4),
                        "bad_batch_mean": round(float(bad_vals.mean()), 4)
                        if len(bad_vals) > 0
                        else None,
                    }
                )

            return {
                "status": "OK",
                "target": target,
                "direction": direction,
                "good_batch_threshold": round(
                    float(q25 if direction == "lower_is_better" else q75), 4
                ),
                "good_batch_count": int(good_mask.sum()),
                "target_good_mean": round(float(good_df[target].mean()), 4),
                "target_bad_mean": round(float(bad_df[target].mean()), 4),
                "sop_recommendations": sop_table,
            }

        except Exception as e:
            logger.error(f"OperatingWindow error: {e}")
            return {"status": "ERROR", "message": str(e)}
