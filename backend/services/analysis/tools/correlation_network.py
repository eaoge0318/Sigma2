"""
相關性網路分析工具 (Correlation Network Analysis)
- CorrelationNetworkTool: 把相關性矩陣轉成圖,用 centrality 找出最具影響力的"中樞"參數
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List
from .base import AnalysisTool
import logging

logger = logging.getLogger(__name__)


class CorrelationNetworkTool(AnalysisTool):
    """相關性網路分析: 找出最具影響力的 Hub 參數"""

    @property
    def name(self) -> str:
        return "correlation_network"

    @property
    def description(self) -> str:
        return (
            "將參數間的相關性矩陣轉成網路圖,計算 Degree Centrality 和 Betweenness Centrality,"
            "識別出最具影響力的中樞 (Hub) 參數 — 即與最多其他參數有強關聯的控制節點。"
        )

    @property
    def required_params(self) -> List[str]:
        return ["file_id"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        try:
            file_id = params.get("file_id")
            threshold = float(params.get("threshold", 0.5))  # |r| > threshold = edge
            top_k = int(params.get("top_k", 10))

            # Load data
            summary = self.analysis_service.load_summary(session_id, file_id)
            if not summary:
                return {"status": "ERROR", "message": "No summary data available"}
            filename = summary["filename"]
            csv_path = (
                self.analysis_service.get_csv_path(session_id, filename)
            )
            df = pd.read_csv(csv_path)

            # Select numeric columns only
            numeric_df = df.select_dtypes(include=[np.number])

            # Remove constant columns
            stds = numeric_df.std()
            numeric_df = numeric_df[stds[stds > 0].index]

            if len(numeric_df.columns) < 3:
                return {
                    "status": "ERROR",
                    "message": "Not enough numeric columns for network analysis",
                }

            # Compute correlation matrix
            corr_matrix = numeric_df.corr()
            n_params = len(corr_matrix.columns)
            param_names = corr_matrix.columns.tolist()

            # Build adjacency: edge exists if |r| > threshold
            # Degree Centrality: number of strong connections / (n-1)
            # Betweenness approximation: how many shortest paths pass through a node
            degree = {}
            total_strength = {}
            edges = []

            for i, p_a in enumerate(param_names):
                count = 0
                strength = 0.0
                for j, p_b in enumerate(param_names):
                    if i == j:
                        continue
                    r = corr_matrix.iloc[i, j]
                    if abs(r) > threshold:
                        count += 1
                        strength += abs(r)
                        if i < j:
                            edges.append(
                                {
                                    "source": p_a,
                                    "target": p_b,
                                    "weight": round(float(r), 4),
                                }
                            )
                degree[p_a] = count / (n_params - 1) if n_params > 1 else 0
                total_strength[p_a] = strength

            # Betweenness Centrality (simplified: based on bridge detection)
            # A parameter is a "bridge" if removing it would disconnect clusters
            # Approximation: parameters that connect to multiple distinct groups
            betweenness = {}
            for p in param_names:
                # Count how many of p's neighbors are NOT connected to each other
                neighbors = []
                for j, p_b in enumerate(param_names):
                    if p_b == p:
                        continue
                    r = corr_matrix.loc[p, p_b]
                    if abs(r) > threshold:
                        neighbors.append(p_b)

                if len(neighbors) < 2:
                    betweenness[p] = 0.0
                    continue

                # Count non-connected neighbor pairs
                non_connected_pairs = 0
                total_pairs = 0
                for ni in range(len(neighbors)):
                    for nj in range(ni + 1, len(neighbors)):
                        total_pairs += 1
                        r_nn = corr_matrix.loc[neighbors[ni], neighbors[nj]]
                        if abs(r_nn) <= threshold:
                            non_connected_pairs += 1

                betweenness[p] = (
                    non_connected_pairs / total_pairs if total_pairs > 0 else 0
                )

            # Rank by composite score
            hub_scores = []
            for p in param_names:
                composite = (
                    degree[p] * 0.4
                    + betweenness.get(p, 0) * 0.3
                    + (total_strength[p] / n_params) * 0.3
                )
                hub_scores.append(
                    {
                        "parameter": p,
                        "degree_centrality": round(degree[p], 4),
                        "betweenness_centrality": round(betweenness.get(p, 0), 4),
                        "total_strength": round(total_strength[p], 4),
                        "hub_score": round(composite, 4),
                    }
                )

            hub_scores.sort(key=lambda x: x["hub_score"], reverse=True)

            return {
                "status": "OK",
                "correlation_threshold": threshold,
                "total_parameters": n_params,
                "total_edges": len(edges),
                "network_density": round(
                    len(edges) / (n_params * (n_params - 1) / 2), 4
                )
                if n_params > 1
                else 0,
                "top_hub_parameters": hub_scores[:top_k],
                "top_edges": sorted(
                    edges, key=lambda x: abs(x["weight"]), reverse=True
                )[:20],
            }

        except Exception as e:
            logger.error(f"CorrelationNetwork error: {e}")
            return {"status": "ERROR", "message": str(e)}
