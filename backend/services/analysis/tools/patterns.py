from .base import AnalysisTool
from typing import Dict, Any
import pandas as pd
import numpy as np
from scipy import signal


# 嘗試導入 sklearn，如果沒有則在運行時報錯
try:
    from sklearn.cluster import MiniBatchKMeans
    from sklearn.preprocessing import StandardScaler

    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False


class FindTemporalPatternsTool(AnalysisTool):
    """時序模式發現工具"""

    name = "find_temporal_patterns"
    description = "檢測數據中的週期性、趨勢和季節性"
    required_params = ["file_id", "parameter"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        parameter = params.get("parameter")

        csv_path = self._get_csv_path(session_id, file_id)
        if not csv_path:
            return {"error": "CSV file not found"}

        try:
            df = pd.read_csv(csv_path)
            if parameter not in df.columns:
                return {"error": f"Parameter {parameter} not found"}

            # 處理數據
            series = (
                pd.to_numeric(df[parameter], errors="coerce").interpolate().dropna()
            )

            if len(series) < 50:
                return {
                    "error": "Insufficient data for temporal analysis (min 50 points)"
                }

            # 去趨勢
            detrended = signal.detrend(series)

            # 自相關分析 (檢測週期)
            acf = np.correlate(detrended, detrended, mode="full")
            acf = acf[len(acf) // 2 :]

            # 尋找峰值
            peaks, _ = signal.find_peaks(acf, distance=10, prominence=0.1)

            periodicity = []
            if len(peaks) > 0:
                # 只取前3個顯著週期
                for p in peaks[:3]:
                    periodicity.append(int(p))

            # 趨勢分析 (簡單線性回歸)
            x = np.arange(len(series))
            poly = np.polyfit(x, series, 1)
            slope = poly[0]

            trend_desc = "無明顯趨勢"
            if abs(slope) > 0.01:  # 閾值需根據數據量級調整，這裡僅示意
                trend_desc = "上升趨勢" if slope > 0 else "下降趨勢"

            return {
                "parameter": parameter,
                "trend": {"slope": float(slope), "description": trend_desc},
                "periodicity": {
                    "detected_periods_indices": periodicity,
                    "has_periodicity": len(periodicity) > 0,
                },
                "analysis_summary": f"檢測到{trend_desc}，"
                + (
                    f"發現潛在週期: {periodicity}"
                    if periodicity
                    else "未發現明顯週期性"
                ),
            }
        except Exception as e:
            return {"error": f"Temporal analysis failed: {str(e)}"}

    def _get_csv_path(self, session_id: str, file_id: str) -> str:
        summary = self.service.load_summary(session_id, file_id)
        if not summary:
            return None
        filename = summary["filename"]
        return str(self.service.base_dir / session_id / "uploads" / filename)


class FindEventPatternsTool(AnalysisTool):
    """事件模式發現工具"""

    name = "find_event_patterns"
    description = "找出滿足特定條件的事件段（如溫度>100）"
    required_params = ["file_id", "condition"]  # e.g. "temperature > 100"

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        condition = params.get("condition")

        csv_path = self._get_csv_path(session_id, file_id)
        if not csv_path:
            return {"error": "CSV file not found"}

        try:
            df = pd.read_csv(csv_path)

            # 安全檢查：僅允許簡單條件
            # 這裡使用 pandas query，存在一定安全風險，實際應用需嚴格過濾
            # 簡單過濾：確保只包含字母、數字、空格和比較運算符
            import re

            if not re.match(r"^[a-zA-Z0-9_\s><=!.-]+$", condition):
                return {
                    "error": "Invalid condition format (only alphanumeric and specific operators allowed)"
                }

            events = df.query(condition)

            if events.empty:
                return {
                    "condition": condition,
                    "event_count": 0,
                    "message": "No events found matching condition",
                }

            # 找出連續事件段
            # 假設 index 是連續的
            events["group"] = (events.index.to_series().diff() > 1).cumsum()
            event_groups = []

            for _, group in events.groupby("group"):
                start_idx = group.index[0]
                end_idx = group.index[-1]
                duration = len(group)
                event_groups.append(
                    {
                        "start_index": int(start_idx),
                        "end_index": int(end_idx),
                        "duration": int(duration),
                    }
                )

            return {
                "condition": condition,
                "total_event_points": len(events),
                "event_segments_count": len(event_groups),
                "segments": event_groups[:10],  # 只返回前10個片段
            }
        except Exception as e:
            return {"error": f"Event analysis failed: {str(e)}"}

    def _get_csv_path(self, session_id: str, file_id: str) -> str:
        summary = self.service.load_summary(session_id, file_id)
        if not summary:
            return None
        filename = summary["filename"]
        return str(self.service.base_dir / session_id / "uploads" / filename)


class ClusterAnalysisTool(AnalysisTool):
    """聚類分析工具"""

    name = "cluster_analysis"
    description = "對多個參數進行K-Means聚類分析"
    required_params = ["file_id", "parameters"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        if not SKLEARN_AVAILABLE:
            return {"error": "scikit-learn not installed"}

        file_id = params.get("file_id")
        parameters = params.get("parameters", [])
        n_clusters = params.get("n_clusters", 3)

        csv_path = self._get_csv_path(session_id, file_id)
        if not csv_path:
            return {"error": "CSV file not found"}

        try:
            df = pd.read_csv(csv_path)

            # 數據準備
            valid_params = [p for p in parameters if p in df.columns]
            if len(valid_params) < 2:
                return {"error": "Need at least 2 valid parameters for clustering"}

            data = df[valid_params].dropna()
            if len(data) < n_clusters:
                return {"error": "Insufficient data points"}

            # 標準化
            scaler = StandardScaler()
            scaled_data = scaler.fit_transform(data)

            # 聚類
            kmeans = MiniBatchKMeans(
                n_clusters=n_clusters, random_state=42, batch_size=256
            )
            kmeans.fit(scaled_data)

            # 結果整理
            centers = scaler.inverse_transform(kmeans.cluster_centers_)
            labels, counts = np.unique(kmeans.labels_, return_counts=True)

            clusters_info = []
            for i in range(len(labels)):
                clusters_info.append(
                    {
                        "cluster_id": int(labels[i]),
                        "size": int(counts[i]),
                        "percentage": float(counts[i] / len(data) * 100),
                        "center": dict(zip(valid_params, centers[i].tolist())),
                    }
                )

            return {
                "parameters": valid_params,
                "n_clusters": n_clusters,
                "clusters": clusters_info,
            }
        except Exception as e:
            return {"error": f"Clustering failed: {str(e)}"}

    def _get_csv_path(self, session_id: str, file_id: str) -> str:
        summary = self.service.load_summary(session_id, file_id)
        if not summary:
            return None
        filename = summary["filename"]
        return str(self.service.base_dir / session_id / "uploads" / filename)


class FindAssociationRulesTool(AnalysisTool):
    """關聯規則發現工具(簡化版)"""

    name = "find_association_rules"
    description = "發現參數間的共現模式（例如：當A高時B通常也高）"
    required_params = ["file_id", "parameters"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        parameters = params.get("parameters", [])
        threshold = params.get("threshold", 0.8)  # 簡單的相關性閾值

        csv_path = self._get_csv_path(session_id, file_id)
        if not csv_path:
            return {"error": "CSV file not found"}

        try:
            df = pd.read_csv(csv_path)
            valid_params = [p for p in parameters if p in df.columns]

            if len(valid_params) < 2:
                # 如果用戶只給一兩個參數，自動補充高相關參數
                # 但這裡先報錯
                return {"error": "Need at least 2 parameters"}

            # 這裡做一個簡單的 'High-High' 關聯分析
            # 定義 'High' 為 > Mean + Std
            data = df[valid_params].dropna()

            high_masks = {}
            for p in valid_params:
                mean = data[p].mean()
                std = data[p].std()
                high_masks[p] = data[p] > (mean + std)

            rules = []
            # 檢查兩兩組合 A -> B (A高則B高)
            for p1 in valid_params:
                for p2 in valid_params:
                    if p1 == p2:
                        continue

                    mask1 = high_masks[p1]
                    mask2 = high_masks[p2]

                    if mask1.sum() == 0:
                        continue

                    # Confidence: P(B|A) = Count(A and B) / Count(A)
                    concurrence = (mask1 & mask2).sum()
                    confidence = concurrence / mask1.sum()

                    if confidence >= threshold:
                        rules.append(
                            {
                                "antecedent": f"{p1} is High",
                                "consequent": f"{p2} is High",
                                "confidence": float(confidence),
                                "support": float(concurrence / len(data)),
                                "count": int(concurrence),
                            }
                        )

            rules.sort(key=lambda x: x["confidence"], reverse=True)

            return {
                "method": "High-Value Association (Mean+Std)",
                "rules_found": len(rules),
                "top_rules": rules[:10],
            }
        except Exception as e:
            return {"error": f"Rule mining failed: {str(e)}"}

    def _get_csv_path(self, session_id: str, file_id: str) -> str:
        summary = self.service.load_summary(session_id, file_id)
        if not summary:
            return None
        filename = summary["filename"]
        return str(self.service.base_dir / session_id / "uploads" / filename)
