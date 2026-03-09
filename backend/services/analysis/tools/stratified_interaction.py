"""
分層交互效應分析工具 (Stratified Interaction Analysis)
- 在每個批次/區段內部分別做兩因子交互效應檢定
- 比較不同批次間交互效應的差異
- 找出交互效應在哪些批次特別強/弱
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List
from .base import AnalysisTool
import logging

logger = logging.getLogger(__name__)


class StratifiedInteractionTool(AnalysisTool):
    """分層交互分析: 在各批次/區段內分別做交互效應檢定,比較跨批次差異"""

    @property
    def name(self) -> str:
        return "stratified_interaction"

    @property
    def description(self) -> str:
        return (
            "分層交互效應分析: 將資料按批次或等分區段切分, "
            "在每個區段內分別做兩因子交互效應分析, "
            "找出交互效應在哪些批次特別強/弱。"
        )

    @property
    def required_params(self) -> List[str]:
        return ["file_id", "param_a", "param_b", "target"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        try:
            file_id = params.get("file_id")
            param_a = params.get("param_a")
            param_b = params.get("param_b")
            target = params.get("target")
            batch_column = params.get("batch_column")
            batch_count = int(params.get("batch_count", 5))

            # Load data
            summary = self.analysis_service.load_summary(session_id, file_id)
            if not summary:
                return {"status": "ERROR", "message": "No summary data available"}
            filename = summary["filename"]
            csv_path = (
                self.analysis_service.base_dir / session_id / "uploads" / filename
            )
            df = pd.read_csv(csv_path)

            # Validate columns
            for col_name, label in [
                (param_a, "param_a"),
                (param_b, "param_b"),
                (target, "target"),
            ]:
                if col_name not in df.columns:
                    return {
                        "status": "ERROR",
                        "message": f"{label} '{col_name}' not found",
                    }

            numeric_df = df.select_dtypes(include=[np.number])
            required_cols = [param_a, param_b, target]
            for col in required_cols:
                if col not in numeric_df.columns:
                    return {
                        "status": "ERROR",
                        "message": f"'{col}' is not numeric",
                    }

            # Split into batches
            if batch_column and batch_column in df.columns:
                # Use provided batch column
                df["_batch"] = df[batch_column].astype(str)
            else:
                # Auto-split into equal segments
                n_rows = len(df)
                segment_size = max(n_rows // batch_count, 20)
                df["_batch"] = [
                    f"Segment-{i // segment_size + 1}" for i in range(n_rows)
                ]

            batch_labels = df["_batch"].unique()
            if len(batch_labels) < 2:
                return {
                    "status": "WARNING",
                    "message": "Need at least 2 batches for stratified analysis",
                }

            # Run interaction analysis within each batch
            from scipy import stats

            batch_results = []
            for batch_label in batch_labels:
                batch_df = df[df["_batch"] == batch_label][
                    [param_a, param_b, target]
                ].dropna()

                if len(batch_df) < 10:
                    batch_results.append(
                        {
                            "batch": str(batch_label),
                            "sample_size": len(batch_df),
                            "status": "SKIP",
                            "reason": "Insufficient data (<10 rows)",
                        }
                    )
                    continue

                # Binarize param_a and param_b by median
                a_median = batch_df[param_a].median()
                b_median = batch_df[param_b].median()

                batch_df = batch_df.copy()
                batch_df["A_group"] = (batch_df[param_a] > a_median).astype(int)
                batch_df["B_group"] = (batch_df[param_b] > b_median).astype(int)

                # Get 4 cells of 2x2 factorial
                groups = {}
                for a_val in [0, 1]:
                    for b_val in [0, 1]:
                        mask = (batch_df["A_group"] == a_val) & (
                            batch_df["B_group"] == b_val
                        )
                        cell_data = batch_df.loc[mask, target]
                        groups[(a_val, b_val)] = cell_data

                # Check minimum cell size
                min_cell = min(len(g) for g in groups.values())
                if min_cell < 3:
                    batch_results.append(
                        {
                            "batch": str(batch_label),
                            "sample_size": len(batch_df),
                            "status": "SKIP",
                            "reason": f"Cell size too small (min={min_cell})",
                        }
                    )
                    continue

                # Compute interaction effect
                # Interaction = (mean_11 - mean_10) - (mean_01 - mean_00)
                mean_00 = groups[(0, 0)].mean()
                mean_01 = groups[(0, 1)].mean()
                mean_10 = groups[(1, 0)].mean()
                mean_11 = groups[(1, 1)].mean()

                interaction_effect = (mean_11 - mean_10) - (mean_01 - mean_00)

                # Main effects
                main_a = ((mean_10 + mean_11) / 2) - ((mean_00 + mean_01) / 2)
                main_b = ((mean_01 + mean_11) / 2) - ((mean_00 + mean_10) / 2)

                # One-way ANOVA as proxy for significance
                all_groups = [
                    groups[(0, 0)].values,
                    groups[(0, 1)].values,
                    groups[(1, 0)].values,
                    groups[(1, 1)].values,
                ]
                try:
                    f_stat, p_value = stats.f_oneway(*all_groups)
                except Exception:
                    f_stat, p_value = 0, 1.0

                # Effect size (eta-squared approximation)
                overall_mean = batch_df[target].mean()
                ss_between = sum(
                    len(g) * (g.mean() - overall_mean) ** 2 for g in groups.values()
                )
                ss_total = ((batch_df[target] - overall_mean) ** 2).sum()
                eta_squared = ss_between / ss_total if ss_total > 0 else 0

                batch_results.append(
                    {
                        "batch": str(batch_label),
                        "sample_size": len(batch_df),
                        "status": "OK",
                        "interaction_effect": round(float(interaction_effect), 4),
                        "main_effect_A": round(float(main_a), 4),
                        "main_effect_B": round(float(main_b), 4),
                        "f_statistic": round(float(f_stat), 4),
                        "p_value": round(float(p_value), 6),
                        "eta_squared": round(float(eta_squared), 4),
                        "cell_means": {
                            "A_low_B_low": round(float(mean_00), 4),
                            "A_low_B_high": round(float(mean_01), 4),
                            "A_high_B_low": round(float(mean_10), 4),
                            "A_high_B_high": round(float(mean_11), 4),
                        },
                    }
                )

            # Find batches with strongest interaction
            valid_results = [r for r in batch_results if r.get("status") == "OK"]
            if valid_results:
                valid_results.sort(
                    key=lambda x: abs(x.get("interaction_effect", 0)), reverse=True
                )

            return {
                "status": "OK",
                "param_a": param_a,
                "param_b": param_b,
                "target": target,
                "total_batches": len(batch_labels),
                "analyzed_batches": len(valid_results),
                "batch_results": batch_results,
                "strongest_interaction_batch": valid_results[0]["batch"]
                if valid_results
                else None,
                "interpretation": self._interpret(
                    param_a, param_b, target, valid_results
                ),
            }

        except Exception as e:
            logger.error(f"StratifiedInteraction error: {e}")
            return {"status": "ERROR", "message": str(e)}

    def _interpret(self, param_a, param_b, target, valid_results) -> str:
        if not valid_results:
            return "無法在任何批次中完成交互效應分析 (樣本數不足)。"

        lines = [f"{param_a} x {param_b} 對 {target} 的分層交互效應分析:"]

        # Classify batches by interaction strength
        strong = [r for r in valid_results if abs(r["interaction_effect"]) > 0.5]
        sig = [r for r in valid_results if r.get("p_value", 1) < 0.05]

        lines.append(
            f"  共分析 {len(valid_results)} 個批次, "
            f"{len(strong)} 個有明顯交互效應, "
            f"{len(sig)} 個達統計顯著 (p<0.05)"
        )

        if valid_results:
            top = valid_results[0]
            lines.append(
                f"\n  最強交互效應: {top['batch']}"
                f" (交互={top['interaction_effect']:.4f}, "
                f"p={top.get('p_value', 'N/A')}, "
                f"eta2={top.get('eta_squared', 'N/A')})"
            )

            # Check if interaction is consistent across batches
            effects = [r["interaction_effect"] for r in valid_results]
            signs = [np.sign(e) for e in effects]
            if len(set(signs)) == 1:
                lines.append("  交互效應方向在所有批次一致 (穩定的協同/拮抗關係)")
            else:
                lines.append("  交互效應方向在不同批次不一致 (可能存在調節因子)")

        return "\n".join(lines)
