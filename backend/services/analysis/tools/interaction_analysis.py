"""
交互作用分析工具 (Interaction Analysis)
- InteractionScatterTool: 兩參數散佈圖 + 目標變數顏色映射,識別操作窗口
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List
from .base import AnalysisTool
import logging

logger = logging.getLogger(__name__)


class InteractionScatterTool(AnalysisTool):
    """兩參數交互作用散佈圖,Color=目標變數,自動識別 Sweet Spot"""

    @property
    def name(self) -> str:
        return "interaction_scatter"

    @property
    def description(self) -> str:
        return (
            "產出兩參數的交互作用分析。以 X/Y 為兩個控制參數,"
            "Color 為目標變數,自動識別最佳操作窗口 (Sweet Spot)。"
        )

    @property
    def required_params(self) -> List[str]:
        return ["file_id", "x_param", "y_param", "color_param"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        try:
            file_id = params.get("file_id")
            x_param = params.get("x_param")
            y_param = params.get("y_param")
            color_param = params.get("color_param")
            direction = params.get("direction", "lower_is_better")

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
            for col_name, col_label in [
                (x_param, "x_param"),
                (y_param, "y_param"),
                (color_param, "color_param"),
            ]:
                if col_name not in df.columns:
                    return {
                        "status": "ERROR",
                        "message": f"{col_label} '{col_name}' not found",
                    }

            # Get numeric subset
            work_df = df[[x_param, y_param, color_param]].dropna()
            if len(work_df) < 10:
                return {
                    "status": "ERROR",
                    "message": "Insufficient data points after removing NaN",
                }

            # Split into good/bad based on color_param
            target_series = work_df[color_param]
            q25 = target_series.quantile(0.25)
            q75 = target_series.quantile(0.75)

            if direction == "lower_is_better":
                good_mask = work_df[color_param] <= q25
                bad_mask = work_df[color_param] >= q75
            else:
                good_mask = work_df[color_param] >= q75
                bad_mask = work_df[color_param] <= q25

            good_df = work_df[good_mask]
            bad_df = work_df[bad_mask]

            # Sweet Spot boundaries (from good batch)
            sweet_spot = {
                "x_range": {
                    "min": round(float(good_df[x_param].quantile(0.1)), 4),
                    "max": round(float(good_df[x_param].quantile(0.9)), 4),
                    "mean": round(float(good_df[x_param].mean()), 4),
                },
                "y_range": {
                    "min": round(float(good_df[y_param].quantile(0.1)), 4),
                    "max": round(float(good_df[y_param].quantile(0.9)), 4),
                    "mean": round(float(good_df[y_param].mean()), 4),
                },
            }

            # Danger Zone boundaries (from bad batch)
            danger_zone = {
                "x_range": {
                    "min": round(float(bad_df[x_param].quantile(0.1)), 4),
                    "max": round(float(bad_df[x_param].quantile(0.9)), 4),
                    "mean": round(float(bad_df[x_param].mean()), 4),
                },
                "y_range": {
                    "min": round(float(bad_df[y_param].quantile(0.1)), 4),
                    "max": round(float(bad_df[y_param].quantile(0.9)), 4),
                    "mean": round(float(bad_df[y_param].mean()), 4),
                },
            }

            # Compute interaction strength (correlation between x*y and target)
            work_df["interaction"] = work_df[x_param] * work_df[y_param]
            interaction_corr = work_df["interaction"].corr(work_df[color_param])

            # Scatter data points (sampled for frontend rendering)
            max_points = 200
            if len(work_df) > max_points:
                sample_df = work_df.sample(n=max_points, random_state=42)
            else:
                sample_df = work_df

            scatter_data = []
            for _, row in sample_df.iterrows():
                scatter_data.append(
                    {
                        "x": round(float(row[x_param]), 4),
                        "y": round(float(row[y_param]), 4),
                        "color": round(float(row[color_param]), 4),
                    }
                )

            return {
                "status": "OK",
                "x_param": x_param,
                "y_param": y_param,
                "color_param": color_param,
                "direction": direction,
                "total_points": len(work_df),
                "sweet_spot": sweet_spot,
                "danger_zone": danger_zone,
                "interaction_strength": round(float(interaction_corr), 4)
                if not np.isnan(interaction_corr)
                else 0,
                "scatter_data": scatter_data,
                "interpretation": self._interpret(
                    sweet_spot, danger_zone, x_param, y_param, direction
                ),
            }

        except Exception as e:
            logger.error(f"InteractionScatter error: {e}")
            return {"status": "ERROR", "message": str(e)}

    def _interpret(self, sweet, danger, x_name, y_name, direction) -> str:
        """Auto-generate human-readable interpretation"""
        lines = []
        # X direction
        if sweet["x_range"]["mean"] < danger["x_range"]["mean"]:
            lines.append(f"降低 {x_name} (目標: {sweet['x_range']['mean']})")
        else:
            lines.append(f"提高 {x_name} (目標: {sweet['x_range']['mean']})")
        # Y direction
        if sweet["y_range"]["mean"] < danger["y_range"]["mean"]:
            lines.append(f"降低 {y_name} (目標: {sweet['y_range']['mean']})")
        else:
            lines.append(f"提高 {y_name} (目標: {sweet['y_range']['mean']})")

        return "最佳操作窗口建議: " + " + ".join(lines)


class InteractionEffectTestTool(AnalysisTool):
    """
    兩因子交互作用統計檢定:
    使用 OLS 迴歸 (含 A, B, A*B 交互項) 進行類 Two-Way ANOVA 分析,
    量化「主效應」和「交互效應」的統計顯著性。
    """

    @property
    def name(self) -> str:
        return "interaction_effect_test"

    @property
    def description(self) -> str:
        return (
            "兩因子交互作用統計檢定: 輸入兩個控制參數和一個目標變數,"
            "使用 OLS 迴歸量化主效應 (A, B) 和交互效應 (A*B) 的 F-value / p-value。"
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
            for col_name, col_label in [
                (param_a, "param_a"),
                (param_b, "param_b"),
                (target, "target"),
            ]:
                if col_name not in df.columns:
                    return {
                        "status": "ERROR",
                        "message": f"{col_label} '{col_name}' not found in data",
                    }

            # Prepare data (drop NaN)
            work_df = df[[param_a, param_b, target]].dropna()
            if len(work_df) < 20:
                return {
                    "status": "ERROR",
                    "message": f"Insufficient data ({len(work_df)} rows). Need at least 20.",
                }

            # Standardize for numerical stability
            from sklearn.preprocessing import StandardScaler

            scaler = StandardScaler()
            scaled = scaler.fit_transform(work_df[[param_a, param_b]])
            a_std = scaled[:, 0]
            b_std = scaled[:, 1]
            y = work_df[target].values

            # Create interaction term
            ab_interaction = a_std * b_std

            # OLS Regression: y = β0 + β1*A + β2*B + β3*A*B + ε
            import statsmodels.api as sm

            X = np.column_stack([a_std, b_std, ab_interaction])
            X = sm.add_constant(X)
            model = sm.OLS(y, X).fit()

            # Extract results
            # Coefficients: [const, A, B, A*B]
            coeff_names = ["intercept", param_a, param_b, f"{param_a}*{param_b}"]
            results = {}
            for i, name in enumerate(coeff_names):
                results[name] = {
                    "coefficient": round(float(model.params[i]), 6),
                    "t_value": round(float(model.tvalues[i]), 4),
                    "p_value": round(float(model.pvalues[i]), 6),
                    "significant": bool(model.pvalues[i] < 0.05),
                }

            # Interaction-specific metrics
            interaction_key = f"{param_a}*{param_b}"
            interaction_p = float(model.pvalues[3])
            interaction_coeff = float(model.params[3])

            # Effect size comparison
            # Compare R² of model with and without interaction
            X_no_interaction = sm.add_constant(np.column_stack([a_std, b_std]))
            model_no_inter = sm.OLS(y, X_no_interaction).fit()
            r2_with = float(model.rsquared)
            r2_without = float(model_no_inter.rsquared)
            r2_improvement = r2_with - r2_without

            # Simple correlation for context
            corr_a_target = round(float(work_df[param_a].corr(work_df[target])), 4)
            corr_b_target = round(float(work_df[param_b].corr(work_df[target])), 4)
            corr_a_b = round(float(work_df[param_a].corr(work_df[param_b])), 4)

            # Interpretation
            interpretation = self._interpret(
                param_a,
                param_b,
                target,
                interaction_p,
                interaction_coeff,
                r2_improvement,
                results[param_a]["p_value"],
                results[param_b]["p_value"],
            )

            return {
                "status": "OK",
                "param_a": param_a,
                "param_b": param_b,
                "target": target,
                "n_samples": len(work_df),
                "model_r_squared": round(r2_with, 4),
                "model_r_squared_without_interaction": round(r2_without, 4),
                "interaction_r2_improvement": round(r2_improvement, 4),
                "effects": results,
                "interaction_summary": {
                    "effect_name": interaction_key,
                    "p_value": round(interaction_p, 6),
                    "is_significant": interaction_p < 0.05,
                    "effect_type": "synergistic"
                    if interaction_coeff > 0
                    else "antagonistic",
                    "strength": (
                        "strong"
                        if interaction_p < 0.001
                        else "moderate"
                        if interaction_p < 0.05
                        else "weak/none"
                    ),
                },
                "pairwise_correlations": {
                    f"{param_a}_vs_{target}": corr_a_target,
                    f"{param_b}_vs_{target}": corr_b_target,
                    f"{param_a}_vs_{param_b}": corr_a_b,
                },
                "interpretation": interpretation,
            }

        except ImportError as ie:
            logger.error(f"InteractionEffectTest import error: {ie}")
            return {"status": "ERROR", "message": f"Missing dependency: {ie}"}
        except Exception as e:
            logger.error(f"InteractionEffectTest error: {e}")
            return {"status": "ERROR", "message": str(e)}

    def _interpret(
        self,
        a_name,
        b_name,
        target_name,
        inter_p,
        inter_coeff,
        r2_imp,
        a_p,
        b_p,
    ) -> str:
        lines = []

        # Main effects
        if a_p < 0.05:
            lines.append(f"{a_name} 對 {target_name} 有顯著主效應 (p={a_p:.4f})")
        else:
            lines.append(f"{a_name} 對 {target_name} 無顯著主效應 (p={a_p:.4f})")

        if b_p < 0.05:
            lines.append(f"{b_name} 對 {target_name} 有顯著主效應 (p={b_p:.4f})")
        else:
            lines.append(f"{b_name} 對 {target_name} 無顯著主效應 (p={b_p:.4f})")

        # Interaction effect
        if inter_p < 0.05:
            effect_type = (
                "協同 (synergistic)" if inter_coeff > 0 else "拮抗 (antagonistic)"
            )
            lines.append(
                f"交互效應 {a_name}*{b_name} 顯著 (p={inter_p:.4f}), "
                f"效應類型: {effect_type}, R² 提升: {r2_imp:.4f}"
            )
            lines.append(
                f"工程含義: {a_name} 和 {b_name} 同時調整的效果 "
                f"{'大於' if inter_coeff > 0 else '小於'}分別調整的效果之和"
            )
        else:
            lines.append(
                f"交互效應 {a_name}*{b_name} 不顯著 (p={inter_p:.4f}), 兩參數可獨立調整"
            )

        return "; ".join(lines)
