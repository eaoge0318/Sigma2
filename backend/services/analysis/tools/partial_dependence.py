"""
Partial Dependence 邊際效應分析工具
- PartialDependenceTool: 訓練 RF 模型,計算指定特徵的 PDP 曲線
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List
from .base import AnalysisTool
import logging

logger = logging.getLogger(__name__)


class PartialDependenceTool(AnalysisTool):
    """Partial Dependence Plot: 看單一參數變化對目標的非線性影響"""

    @property
    def name(self) -> str:
        return "partial_dependence"

    @property
    def description(self) -> str:
        return (
            "使用 Random Forest 模型計算 Partial Dependence,"
            "呈現指定參數從低到高變化時,目標變數的預測趨勢 (邊際效應曲線)。"
            "可識別非線性關係和臨界點。"
        )

    @property
    def required_params(self) -> List[str]:
        return ["file_id", "target", "features"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        try:
            from sklearn.ensemble import RandomForestRegressor

            file_id = params.get("file_id")
            target = params.get("target")
            features_input = params.get("features")
            n_grid = params.get("n_grid_points", 20)

            # Parse features (comma-separated or list)
            if isinstance(features_input, str):
                features = [f.strip() for f in features_input.split(",")]
            elif isinstance(features_input, list):
                features = features_input
            else:
                features = [str(features_input)]

            # Limit to 5 features max
            features = features[:5]

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
                return {"status": "ERROR", "message": f"Target '{target}' not found"}

            # Prepare numeric data
            numeric_df = df.select_dtypes(include=[np.number]).dropna(subset=[target])

            # Validate features
            valid_features = [
                f for f in features if f in numeric_df.columns and f != target
            ]
            if not valid_features:
                return {
                    "status": "ERROR",
                    "message": f"No valid features found. Requested: {features}",
                }

            # Select all numeric features for model training (excluding target)
            all_features = [c for c in numeric_df.columns if c != target]

            # Filter constant columns
            stds = numeric_df[all_features].std()
            all_features = stds[stds > 0].index.tolist()

            # Handle missing values
            model_df = numeric_df[all_features + [target]].dropna()
            if len(model_df) < 30:
                return {
                    "status": "ERROR",
                    "message": f"Insufficient data: {len(model_df)} rows",
                }

            X = model_df[all_features]
            y = model_df[target]

            # Train Random Forest
            rf = RandomForestRegressor(
                n_estimators=100,
                max_depth=8,
                min_samples_leaf=5,
                random_state=42,
                n_jobs=-1,
            )
            rf.fit(X, y)
            model_r2 = round(rf.score(X, y), 4)

            # Compute PDP for each requested feature
            pdp_results = []
            for feat in valid_features:
                feat_values = model_df[feat].values
                grid = np.linspace(
                    np.percentile(feat_values, 5),
                    np.percentile(feat_values, 95),
                    n_grid,
                )

                # Manual PDP computation (average prediction over grid)
                pdp_values = []
                X_temp = X.copy()
                for val in grid:
                    X_temp[feat] = val
                    pred_mean = rf.predict(X_temp).mean()
                    pdp_values.append(round(float(pred_mean), 4))

                # Detect monotonicity
                diffs = np.diff(pdp_values)
                if all(d >= 0 for d in diffs):
                    monotonicity = "increasing"
                elif all(d <= 0 for d in diffs):
                    monotonicity = "decreasing"
                else:
                    monotonicity = "non_linear"

                # Find threshold (biggest change point)
                abs_diffs = np.abs(diffs)
                if len(abs_diffs) > 0:
                    max_change_idx = int(np.argmax(abs_diffs))
                    threshold_value = round(float(grid[max_change_idx]), 4)
                else:
                    threshold_value = None

                # Effect range (how much target changes across feature range)
                effect_range = round(float(max(pdp_values) - min(pdp_values)), 4)

                pdp_results.append(
                    {
                        "feature": feat,
                        "grid_values": [round(float(v), 4) for v in grid],
                        "pdp_values": pdp_values,
                        "monotonicity": monotonicity,
                        "effect_range": effect_range,
                        "threshold_point": threshold_value,
                        "interpretation": self._interpret(
                            feat, monotonicity, effect_range, threshold_value
                        ),
                    }
                )

            return {
                "status": "OK",
                "target": target,
                "model_r2": model_r2,
                "features_analyzed": valid_features,
                "pdp_curves": pdp_results,
            }

        except Exception as e:
            logger.error(f"PartialDependence error: {e}")
            return {"status": "ERROR", "message": str(e)}

    def _interpret(self, feat, monotonicity, effect_range, threshold) -> str:
        """Auto-generate interpretation"""
        if monotonicity == "increasing":
            return f"{feat} 越高,目標越大 (效果量: {effect_range})"
        elif monotonicity == "decreasing":
            return f"{feat} 越高,目標越小 (效果量: {effect_range})"
        else:
            if threshold:
                return f"{feat} 在 {threshold} 附近有轉折點 (非線性, 效果量: {effect_range})"
            return f"{feat} 與目標呈非線性關係 (效果量: {effect_range})"
