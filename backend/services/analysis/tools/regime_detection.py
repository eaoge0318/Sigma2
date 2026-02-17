"""
操作模式識別工具 (Operating Regime Detection)
- RegimeDetectionTool: 用 K-Means/DBSCAN 將數據分群,識別不同操作模式
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List
from .base import AnalysisTool
import logging

logger = logging.getLogger(__name__)


class RegimeDetectionTool(AnalysisTool):
    """操作模式識別: 用聚類分析 (K-Means) 識別不同操作區間"""

    @property
    def name(self) -> str:
        return "regime_detection"

    @property
    def description(self) -> str:
        return (
            "使用 K-Means 聚類分析將數據分成不同操作模式 (Regime),"
            "識別每個 Regime 的特徵參數和時間分佈,找出操作模式切換的時間點。"
            "可用於發現隱藏的操作狀態變化。"
        )

    @property
    def required_params(self) -> List[str]:
        return ["file_id"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        try:
            from sklearn.cluster import KMeans
            from sklearn.preprocessing import StandardScaler
            from sklearn.metrics import silhouette_score

            file_id = params.get("file_id")
            n_clusters = int(params.get("n_clusters", 0))  # 0 = auto-detect
            max_clusters = int(params.get("max_clusters", 5))
            top_features = int(params.get("top_features", 10))

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

            # Remove constant and near-constant columns
            stds = numeric_df.std()
            valid_cols = stds[stds > 1e-10].index.tolist()
            numeric_df = numeric_df[valid_cols]

            # Handle NaN
            numeric_df = numeric_df.fillna(numeric_df.median())

            if len(numeric_df) < 10 or len(numeric_df.columns) < 3:
                return {
                    "status": "ERROR",
                    "message": "Insufficient data for clustering",
                }

            # Standardize
            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(numeric_df)

            # Auto-detect optimal number of clusters using silhouette score
            if n_clusters == 0:
                best_k = 2
                best_score = -1
                for k in range(2, min(max_clusters + 1, len(numeric_df) // 5)):
                    km = KMeans(n_clusters=k, random_state=42, n_init=10, max_iter=300)
                    labels = km.fit_predict(X_scaled)
                    score = silhouette_score(
                        X_scaled, labels, sample_size=min(1000, len(X_scaled))
                    )
                    if score > best_score:
                        best_score = score
                        best_k = k
                n_clusters = best_k

            # Final clustering
            km = KMeans(n_clusters=n_clusters, random_state=42, n_init=10, max_iter=300)
            labels = km.fit_predict(X_scaled)
            sil_score = silhouette_score(
                X_scaled, labels, sample_size=min(1000, len(X_scaled))
            )

            # Analyze each regime
            numeric_df = numeric_df.copy()
            numeric_df["regime"] = labels

            regime_profiles = []
            for regime_id in range(n_clusters):
                mask = numeric_df["regime"] == regime_id
                regime_data = numeric_df[mask]
                regime_indices = regime_data.index.tolist()

                # Find the parameters that most distinguish this regime from others
                other_data = numeric_df[~mask]
                distinguishing = []

                for col in valid_cols:
                    regime_mean = regime_data[col].mean()
                    other_mean = other_data[col].mean()
                    pooled_std = np.sqrt(
                        (regime_data[col].std() ** 2 + other_data[col].std() ** 2) / 2
                    )

                    if pooled_std > 0:
                        effect = abs(regime_mean - other_mean) / pooled_std
                    else:
                        effect = 0

                    distinguishing.append(
                        {
                            "parameter": col,
                            "regime_mean": round(float(regime_mean), 4),
                            "other_mean": round(float(other_mean), 4),
                            "effect_size": round(float(effect), 4),
                        }
                    )

                distinguishing.sort(key=lambda x: x["effect_size"], reverse=True)

                # Detect contiguous time blocks
                blocks = self._find_blocks(regime_indices)

                regime_profiles.append(
                    {
                        "regime_id": regime_id,
                        "sample_count": int(mask.sum()),
                        "percentage": round(
                            float(mask.sum() / len(numeric_df) * 100), 1
                        ),
                        "index_range": f"{min(regime_indices)}-{max(regime_indices)}"
                        if regime_indices
                        else "",
                        "time_blocks": blocks[:5],
                        "distinguishing_parameters": distinguishing[:top_features],
                    }
                )

            # Detect regime transitions
            transitions = []
            for i in range(1, len(labels)):
                if labels[i] != labels[i - 1]:
                    transitions.append(
                        {
                            "index": int(i),
                            "from_regime": int(labels[i - 1]),
                            "to_regime": int(labels[i]),
                        }
                    )

            return {
                "status": "OK",
                "n_clusters": n_clusters,
                "silhouette_score": round(float(sil_score), 4),
                "regime_profiles": regime_profiles,
                "transitions": transitions[:30],
                "total_transitions": len(transitions),
                "regime_sequence": [int(label) for label in labels],
            }

        except Exception as e:
            logger.error(f"RegimeDetection error: {e}")
            return {"status": "ERROR", "message": str(e)}

    def _find_blocks(self, indices):
        """Find contiguous blocks from a list of indices"""
        if not indices:
            return []
        blocks = []
        start = indices[0]
        prev = indices[0]
        for idx in indices[1:]:
            if idx != prev + 1:
                blocks.append(f"{start}-{prev}")
                start = idx
            prev = idx
        blocks.append(f"{start}-{prev}")
        return blocks
