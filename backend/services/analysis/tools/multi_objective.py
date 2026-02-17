"""
多目標優化分析工具 (Multi-Objective Optimization)
- MultiObjectiveTool: 同時分析多個目標之間的 Synergy/Trade-off,
  找出同時改善所有目標的"黃金參數"和需要權衡的"衝突參數"
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List
from .base import AnalysisTool
import logging

logger = logging.getLogger(__name__)


class MultiObjectiveTool(AnalysisTool):
    """多目標優化: 分析多目標間的 Synergy/Trade-off,生成多劇本調整建議"""

    @property
    def name(self) -> str:
        return "multi_objective_analysis"

    @property
    def description(self) -> str:
        return (
            "同時分析多個目標變數 (如水分均值+均勻度) 的相關性結構,"
            "找出: (1) 同時改善所有目標的黃金參數 (Synergy), "
            "(2) 改善一個但惡化另一個的衝突參數 (Trade-off), "
            "(3) 針對不同場景生成調整劇本。"
        )

    @property
    def required_params(self) -> List[str]:
        return ["file_id", "targets"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        try:
            file_id = params.get("file_id")
            targets_input = params.get("targets", "")
            top_k = int(params.get("top_k", 10))

            # Parse multiple targets
            if isinstance(targets_input, str):
                targets = [t.strip() for t in targets_input.split(",") if t.strip()]
            elif isinstance(targets_input, list):
                targets = targets_input
            else:
                return {
                    "status": "ERROR",
                    "message": "targets must be comma-separated string or list",
                }

            if len(targets) < 2:
                return {
                    "status": "ERROR",
                    "message": "Need at least 2 targets for multi-objective analysis",
                }

            # Load data
            summary = self.analysis_service.load_summary(session_id, file_id)
            if not summary:
                return {"status": "ERROR", "message": "No summary data available"}
            filename = summary["filename"]
            csv_path = (
                self.analysis_service.base_dir / session_id / "uploads" / filename
            )
            df = pd.read_csv(csv_path)

            # Select numeric columns
            numeric_df = df.select_dtypes(include=[np.number])

            # Validate targets exist
            missing = [t for t in targets if t not in numeric_df.columns]
            if missing:
                return {"status": "ERROR", "message": f"Targets not found: {missing}"}

            # Remove constant columns
            stds = numeric_df.std()
            valid_cols = stds[stds > 1e-10].index.tolist()
            numeric_df = numeric_df[valid_cols]

            # Compute correlation of every parameter with each target
            feature_cols = [c for c in valid_cols if c not in targets]
            corr_matrix = numeric_df.corr()

            # --- Inter-target correlation ---
            target_correlations = {}
            for i in range(len(targets)):
                for j in range(i + 1, len(targets)):
                    t_a, t_b = targets[i], targets[j]
                    r = (
                        corr_matrix.loc[t_a, t_b]
                        if t_a in corr_matrix.index and t_b in corr_matrix.columns
                        else 0
                    )
                    target_correlations[f"{t_a} vs {t_b}"] = {
                        "correlation": round(float(r), 4),
                        "relationship": (
                            "strong_positive"
                            if r > 0.5
                            else "moderate_positive"
                            if r > 0.2
                            else "near_zero"
                            if abs(r) < 0.2
                            else "moderate_negative"
                            if r > -0.5
                            else "strong_negative"
                        ),
                        "implication": self._interpret_target_correlation(r),
                    }

            # --- Classify each feature as Synergy / Trade-off / Neutral ---
            feature_analysis = []
            for feat in feature_cols:
                corrs_with_targets = {}
                for t in targets:
                    r = (
                        corr_matrix.loc[feat, t]
                        if feat in corr_matrix.index and t in corr_matrix.columns
                        else 0
                    )
                    corrs_with_targets[t] = round(float(r), 4)

                # Classification logic
                r_values = list(corrs_with_targets.values())
                signs = [np.sign(r) for r in r_values]
                abs_values = [abs(r) for r in r_values]
                max_abs = max(abs_values) if abs_values else 0
                min_abs = min(abs_values) if abs_values else 0

                # All same sign and at least one strong -> Synergy
                if all(s == signs[0] for s in signs) and max_abs > 0.2:
                    category = "synergy"
                    effect_direction = "negative" if signs[0] < 0 else "positive"
                # Opposite signs and at least one strong -> Trade-off
                elif len(set(signs)) > 1 and max_abs > 0.2:
                    category = "trade_off"
                    effect_direction = "mixed"
                # All weak -> Neutral
                elif max_abs < 0.15:
                    category = "neutral"
                    effect_direction = "none"
                # One strong, others weak -> Selective
                elif max_abs > 0.3 and min_abs < 0.15:
                    category = "selective"
                    # Find which target it affects
                    strongest_target = targets[abs_values.index(max_abs)]
                    effect_direction = f"only_{strongest_target}"
                else:
                    category = "weak"
                    effect_direction = "weak"

                composite_strength = sum(abs_values) / len(abs_values)

                feature_analysis.append(
                    {
                        "parameter": feat,
                        "correlations": corrs_with_targets,
                        "category": category,
                        "effect_direction": effect_direction,
                        "composite_strength": round(float(composite_strength), 4),
                    }
                )

            # Sort by composite strength
            feature_analysis.sort(key=lambda x: x["composite_strength"], reverse=True)

            # Group by category
            synergy_params = [f for f in feature_analysis if f["category"] == "synergy"]
            tradeoff_params = [
                f for f in feature_analysis if f["category"] == "trade_off"
            ]
            selective_params = [
                f for f in feature_analysis if f["category"] == "selective"
            ]

            # --- Generate Scenarios ---
            scenarios = self._generate_scenarios(
                targets, synergy_params, tradeoff_params, selective_params
            )

            return {
                "status": "OK",
                "targets": targets,
                "target_correlations": target_correlations,
                "synergy_parameters": synergy_params[:top_k],
                "tradeoff_parameters": tradeoff_params[:top_k],
                "selective_parameters": selective_params[:top_k],
                "scenarios": scenarios,
                "summary": {
                    "total_features_analyzed": len(feature_analysis),
                    "synergy_count": len(synergy_params),
                    "tradeoff_count": len(tradeoff_params),
                    "selective_count": len(selective_params),
                },
            }

        except Exception as e:
            logger.error(f"MultiObjective error: {e}")
            return {"status": "ERROR", "message": str(e)}

    def _interpret_target_correlation(self, r: float) -> str:
        if r > 0.5:
            return "兩目標正向連動: 改善一個通常也會改善另一個,但很難獨立調整"
        elif r > 0.2:
            return "兩目標中度相關: 有一定連動但仍有空間獨立調整"
        elif r > -0.2:
            return "兩目標幾乎獨立: 可以分別調整,互不干擾"
        elif r > -0.5:
            return "兩目標中度衝突: 改善一個可能輕微惡化另一個"
        else:
            return "兩目標嚴重衝突: 魚與熊掌難以兼得,需要權衡"

    def _generate_scenarios(self, targets, synergy, tradeoff, selective):
        scenarios = []

        # Scenario 1: Use synergy parameters (improve all targets)
        if synergy:
            top_syn = synergy[:3]
            scenarios.append(
                {
                    "name": "穩健改善 (Safe Improvement)",
                    "description": "使用黃金參數同時改善所有目標 — 沒有 Trade-off 風險",
                    "key_parameters": [
                        {
                            "parameter": s["parameter"],
                            "action": "調高"
                            if s["effect_direction"] == "negative"
                            else "調低",
                            "expected_effect": {
                                t: f"改善 (r={s['correlations'][t]})" for t in targets
                            },
                        }
                        for s in top_syn
                    ],
                }
            )

        # Scenario 2: Use selective parameters (improve one target only)
        if selective:
            for target in targets:
                target_selective = [
                    s for s in selective if target in s.get("effect_direction", "")
                ][:2]
                if target_selective:
                    scenarios.append(
                        {
                            "name": f"專注 {target}",
                            "description": f"只想改善 {target},不影響其他目標",
                            "key_parameters": [
                                {
                                    "parameter": s["parameter"],
                                    "action": "調整",
                                    "expected_effect": s["correlations"],
                                }
                                for s in target_selective
                            ],
                        }
                    )

        # Scenario 3: Trade-off aware
        if tradeoff:
            top_trade = tradeoff[:3]
            scenarios.append(
                {
                    "name": "高風險高回報 (Risk-Reward)",
                    "description": "這些參數能大幅改善某個目標,但可能惡化另一個 — 需謹慎權衡",
                    "key_parameters": [
                        {
                            "parameter": t["parameter"],
                            "action": "需權衡",
                            "expected_effect": t["correlations"],
                        }
                        for t in top_trade
                    ],
                }
            )

        return scenarios
