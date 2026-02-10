from typing import Dict, Any, List
import pandas as pd
import numpy as np
from .base import AnalysisTool


class FindTemporalPatternsTool(AnalysisTool):
    """分析時間序列趨勢 (趨勢方向、週期性)"""

    @property
    def name(self) -> str:
        return "find_temporal_patterns"

    @property
    def description(self) -> str:
        return "分析數據隨時間變化的趨勢（上升、下降、平穩）。需確保數據有時間維度或按時間排序。"

    @property
    def required_params(self) -> List[str]:
        return ["file_id", "parameter"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        col = params.get("parameter")

        summary = self.analysis_service.load_summary(session_id, file_id)
        filename = summary["filename"]
        csv_path = self.analysis_service.base_dir / session_id / "uploads" / filename

        # 讀取數據 (假設前 1000 點做快速趨勢分析)
        df = pd.read_csv(csv_path, usecols=[col], nrows=1000)
        data = df[col].dropna()

        if len(data) < 10:
            return {"error": "Not enough data"}

        # 簡單趨勢計算：前後半段平均值比較
        half = len(data) // 2
        first_half = data.iloc[:half].mean()
        second_half = data.iloc[half:].mean()

        diff_pct = (
            (second_half - first_half) / abs(first_half) if first_half != 0 else 0
        )

        trend = "STABLE"
        if diff_pct > 0.05:
            trend = "INCREASING"
        elif diff_pct < -0.05:
            trend = "DECREASING"

        return {
            "parameter": col,
            "trend": trend,
            "change_percentage": f"{diff_pct * 100:.2f}%",
            "mean_first_half": first_half,
            "mean_second_half": second_half,
        }


class FindEventPatternsTool(AnalysisTool):
    """偵測特定事件模式（如：突波、斷崖式下跌）"""

    @property
    def name(self) -> str:
        return "find_event_patterns"

    @property
    def description(self) -> str:
        return "偵測數據中的突發事件，如數值急劇升降（Spikes/Drops）。"

    @property
    def required_params(self) -> List[str]:
        return ["file_id", "parameter"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        col = params.get("parameter")
        threshold_std = params.get("threshold_std", 3.0)  # 預設 3 倍標準差

        summary = self.analysis_service.load_summary(session_id, file_id)
        csv_path = (
            self.analysis_service.base_dir
            / session_id
            / "uploads"
            / summary["filename"]
        )

        df = pd.read_csv(csv_path, usecols=[col])
        data = df[col]

        mean = data.mean()
        std = data.std()

        # 找出超過閾值的點
        anomalies = data[abs(data - mean) > threshold_std * std]

        events = []
        if len(anomalies) > 0:
            # 簡單聚類：連續的異常點算一個事件
            indices = anomalies.index.tolist()
            if indices:
                events.append(
                    {
                        "start_idx": indices[0],
                        "end_idx": indices[0],
                        "value": float(anomalies.iloc[0]),
                    }
                )

                for idx in indices[1:]:
                    last_event = events[-1]
                    if idx == last_event["end_idx"] + 1:
                        last_event["end_idx"] = idx
                        # 取絕對值最大的作為代表值
                        if abs(data[idx]) > abs(last_event["value"]):
                            last_event["value"] = float(data[idx])
                    else:
                        events.append(
                            {
                                "start_idx": idx,
                                "end_idx": idx,
                                "value": float(data[idx]),
                            }
                        )

        return {
            "parameter": col,
            "total_events": len(events),
            "events_preview": events[:5],  # 只回傳前 5 個避免過大
            "threshold_used": f"{threshold_std} sigma",
        }
