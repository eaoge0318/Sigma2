"""
批次/區域維度聚合分析工具 (Batch Aggregation Analysis)
- BatchAggregationTool: 自動偵測或指定分群欄位,按批次聚合分析異常分佈
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List
from .base import AnalysisTool
import logging

logger = logging.getLogger(__name__)


class BatchAggregationTool(AnalysisTool):
    """
    批次/區域維度聚合分析:
    1. 如果用戶指定了 batch_column — 按該欄位分群
    2. 如果未指定 — 自動將數據等分為 N 個區段 (batch_count, 預設 5)

    產出: 每個批次的統計量、跨批次 ANOVA 差異檢定、最差批次排名
    """

    @property
    def name(self) -> str:
        return "batch_aggregation"

    @property
    def description(self) -> str:
        return (
            "批次/區域維度聚合分析: 按批次 ID 欄位 (或自動等分區段) 對目標參數進行分群分析,"
            "輸出每批次統計量、跨批次 ANOVA 差異、最差批次排名。"
        )

    @property
    def required_params(self) -> List[str]:
        return ["file_id", "target"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        try:
            file_id = params.get("file_id")
            target = params.get("target")
            batch_column = params.get("batch_column", None)
            batch_count = int(params.get("batch_count", 5))

            # Load data
            summary = self.analysis_service.load_summary(session_id, file_id)
            if not summary:
                return {"status": "ERROR", "message": "No summary data available"}
            filename = summary["filename"]
            csv_path = (
                self.analysis_service.get_csv_path(session_id, filename)
            )
            df = pd.read_csv(csv_path)

            if target not in df.columns:
                return {
                    "status": "ERROR",
                    "message": f"Target '{target}' not found in data",
                }

            # Determine grouping strategy
            group_source = ""
            if batch_column and batch_column in df.columns:
                # User specified a batch column
                group_col = batch_column
                group_source = f"user_specified:{batch_column}"
                groups = df.groupby(group_col)
            else:
                # Auto-detect: try to find a low-cardinality column
                detected_col = self._detect_batch_column(df, target)
                if detected_col:
                    group_col = detected_col
                    group_source = f"auto_detected:{detected_col}"
                    groups = df.groupby(group_col)
                else:
                    # Fallback: split data into equal segments
                    group_col = "_segment"
                    group_source = f"equal_segments:{batch_count}"
                    df[group_col] = pd.cut(
                        range(len(df)),
                        bins=batch_count,
                        labels=[
                            f"Segment_{i + 1} (Row {int(len(df) / batch_count * i)}-{int(len(df) / batch_count * (i + 1) - 1)})"
                            for i in range(batch_count)
                        ],
                    )
                    groups = df.groupby(group_col)

            # Per-batch statistics
            batch_stats = []
            group_data_for_anova = []
            for group_name, group_df in groups:
                col_data = group_df[target].dropna()
                if len(col_data) == 0:
                    continue
                group_data_for_anova.append(col_data.values)

                z_scores = np.abs(
                    (col_data - col_data.mean()) / (col_data.std() + 1e-10)
                )
                anomaly_count = int((z_scores > 3).sum())

                stat = {
                    "batch": str(group_name),
                    "count": len(col_data),
                    "mean": round(float(col_data.mean()), 4),
                    "std": round(float(col_data.std()), 4),
                    "min": round(float(col_data.min()), 4),
                    "max": round(float(col_data.max()), 4),
                    "cv": round(
                        float(col_data.std() / (abs(col_data.mean()) + 1e-10)), 4
                    ),
                    "anomaly_count": anomaly_count,
                    "anomaly_rate": round(anomaly_count / len(col_data) * 100, 2),
                }
                batch_stats.append(stat)

            if len(batch_stats) < 2:
                return {
                    "status": "ERROR",
                    "message": f"Need at least 2 batches for comparison, got {len(batch_stats)}",
                }

            # Cross-batch ANOVA
            from scipy import stats as scipy_stats

            if len(group_data_for_anova) >= 2:
                f_stat, p_value = scipy_stats.f_oneway(*group_data_for_anova)
                anova_result = {
                    "f_statistic": round(float(f_stat), 4)
                    if not np.isnan(f_stat)
                    else 0,
                    "p_value": round(float(p_value), 6)
                    if not np.isnan(p_value)
                    else 1.0,
                    "significant": bool(p_value < 0.05)
                    if not np.isnan(p_value)
                    else False,
                }
            else:
                anova_result = {"f_statistic": 0, "p_value": 1.0, "significant": False}

            # Rank batches by anomaly severity
            # Composite score: anomaly_rate * 0.5 + cv * 0.3 + |mean - global_mean| * 0.2
            global_mean = df[target].mean()
            global_std = df[target].std() + 1e-10
            for bs in batch_stats:
                mean_deviation = abs(bs["mean"] - global_mean) / global_std
                bs["severity_score"] = round(
                    bs["anomaly_rate"] * 0.5 + bs["cv"] * 30 + mean_deviation * 20, 2
                )

            worst_batches = sorted(
                batch_stats, key=lambda x: x["severity_score"], reverse=True
            )

            # Interpretation
            interpretation = self._interpret(
                target, group_source, anova_result, worst_batches, global_mean
            )

            return {
                "status": "OK",
                "target": target,
                "group_source": group_source,
                "total_batches": len(batch_stats),
                "anova": anova_result,
                "batch_stats": batch_stats,
                "worst_batches": [
                    {
                        "rank": i + 1,
                        "batch": b["batch"],
                        "severity": b["severity_score"],
                        "anomaly_rate": b["anomaly_rate"],
                        "mean": b["mean"],
                        "std": b["std"],
                    }
                    for i, b in enumerate(worst_batches[:5])
                ],
                "interpretation": interpretation,
            }

        except Exception as e:
            logger.error(f"BatchAggregation error: {e}")
            return {"status": "ERROR", "message": str(e)}

    def _detect_batch_column(self, df: pd.DataFrame, target: str) -> str:
        """
        Auto-detect a potential batch/group column.
        Criteria: low cardinality (2-20 unique values), not the target itself.
        """
        candidates = []
        for col in df.columns:
            if col == target:
                continue
            nunique = df[col].nunique()
            if 2 <= nunique <= 20:
                # Prefer non-numeric or integer-only columns
                if df[col].dtype == "object" or (
                    df[col].dtype in ["int64", "int32"] and df[col].nunique() < 15
                ):
                    candidates.append((col, nunique))

        if not candidates:
            return ""

        # Pick the column with fewest unique values (most likely a batch ID)
        candidates.sort(key=lambda x: x[1])
        return candidates[0][0]

    def _interpret(
        self, target, group_source, anova, worst_batches, global_mean
    ) -> str:
        lines = []

        # Grouping method
        if "auto_detected" in group_source:
            col_name = group_source.split(":")[1]
            lines.append(f"自動偵測到批次欄位: {col_name}")
        elif "user_specified" in group_source:
            col_name = group_source.split(":")[1]
            lines.append(f"使用指定批次欄位: {col_name}")
        else:
            lines.append("未偵測到批次欄位,已自動將數據等分為區段進行分析")

        # ANOVA result
        if anova["significant"]:
            lines.append(
                f"跨批次 ANOVA 差異顯著 (F={anova['f_statistic']}, p={anova['p_value']:.6f}), "
                f"不同批次間 {target} 存在統計顯著差異"
            )
        else:
            lines.append(
                f"跨批次 ANOVA 差異不顯著 (F={anova['f_statistic']}, p={anova['p_value']:.6f}), "
                f"各批次間 {target} 無明顯差異"
            )

        # Worst batch
        if worst_batches:
            worst = worst_batches[0]
            lines.append(
                f"最不穩定批次: {worst['batch']} "
                f"(異常率={worst['anomaly_rate']}%, "
                f"均值={worst['mean']}, 全域均值={round(global_mean, 4)})"
            )

        return "; ".join(lines)
