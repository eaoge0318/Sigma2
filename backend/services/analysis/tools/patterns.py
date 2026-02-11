from typing import Dict, Any, List
import pandas as pd
import numpy as np
from .base import AnalysisTool
import logging

logger = logging.getLogger(__name__)


class FindTemporalPatternsTool(AnalysisTool):
    """分析時間序列趨勢 (CUSUM 變化點偵測 + 滑動窗口趨勢分析)"""

    @property
    def name(self) -> str:
        return "find_temporal_patterns"

    @property
    def description(self) -> str:
        return "分析數據隨時間變化的趨勢，使用 CUSUM 累積和控制圖偵測製程漂移變化點，並使用滑動窗口分析局部趨勢。"

    @property
    def required_params(self) -> List[str]:
        return ["file_id", "parameter"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        col = params.get("parameter")

        try:
            summary = self.analysis_service.load_summary(session_id, file_id)
            filename = summary["filename"]
            csv_path = (
                self.analysis_service.base_dir / session_id / "uploads" / filename
            )

            df = pd.read_csv(csv_path, usecols=[col])
            data = df[col].dropna().reset_index(drop=True)
        except Exception as e:
            return {"error": f"讀取數據失敗: {str(e)}"}

        if len(data) < 20:
            return {
                "error": f"數據點不足 (僅 {len(data)} 點)，需要至少 20 點進行趨勢分析。"
            }

        n = len(data)
        mean_val = float(data.mean())
        std_val = float(data.std())

        if std_val == 0:
            return {
                "parameter": col,
                "trend": "CONSTANT",
                "conclusion": f"參數 {col} 為定值 ({mean_val:.4f})，無趨勢變化。",
            }

        # === 1. CUSUM 變化點偵測 (工業 SPC 標準方法) ===
        # 標準化數據
        z_data = (data - mean_val) / std_val

        # 設定 CUSUM 閾值 (drift allowance k=0.5 sigma, decision h=4 sigma 為常用值)
        k = 0.5  # 允許漂移量
        h = 4.0  # 決策閾值

        cusum_pos = np.zeros(n)  # 正向 CUSUM (偵測上漂)
        cusum_neg = np.zeros(n)  # 負向 CUSUM (偵測下漂)

        change_points = []
        for i in range(1, n):
            cusum_pos[i] = max(0, cusum_pos[i - 1] + z_data.iloc[i] - k)
            cusum_neg[i] = max(0, cusum_neg[i - 1] - z_data.iloc[i] - k)

            if cusum_pos[i] > h:
                change_points.append(
                    {
                        "index": i,
                        "direction": "UP_SHIFT",
                        "cusum_value": float(cusum_pos[i]),
                    }
                )
                cusum_pos[i] = 0  # 重置
            elif cusum_neg[i] > h:
                change_points.append(
                    {
                        "index": i,
                        "direction": "DOWN_SHIFT",
                        "cusum_value": float(cusum_neg[i]),
                    }
                )
                cusum_neg[i] = 0  # 重置

        # === 2. 滑動窗口趨勢分析 ===
        window_size = max(10, n // 10)  # 窗口大小：數據量的 1/10，至少 10
        _rolling_mean = data.rolling(window=window_size, center=True).mean().dropna()

        # 計算線性回歸斜率 (整體趨勢)
        x = np.arange(n)
        slope, intercept = np.polyfit(x, data.values, 1)
        slope_per_unit = float(slope)
        slope_pct = float(slope * n / abs(mean_val) * 100) if mean_val != 0 else 0

        # 趨勢判定
        trend = "STABLE"
        if abs(slope_pct) > 5:
            trend = "INCREASING" if slope_pct > 0 else "DECREASING"

        # === 3. 分段統計 (前/中/後三段比較) ===
        third = n // 3
        seg1_mean = float(data.iloc[:third].mean())
        seg2_mean = float(data.iloc[third : 2 * third].mean())
        seg3_mean = float(data.iloc[2 * third :].mean())

        # 構建結論
        conclusion_parts = []
        conclusion_parts.append(
            f"參數 {col} 共 {n} 點數據，整體均值 {mean_val:.4f}，標準差 {std_val:.4f}。"
        )

        if trend != "STABLE":
            conclusion_parts.append(
                f"整體趨勢為 {trend}，斜率 {slope_per_unit:.6f}/點，累計變化約 {slope_pct:.1f}%。"
            )
        else:
            conclusion_parts.append("整體趨勢平穩，無顯著單調漂移。")

        if change_points:
            cp_summary = [
                f"Index {cp['index']} ({cp['direction']})" for cp in change_points[:5]
            ]
            conclusion_parts.append(
                f"CUSUM 偵測到 {len(change_points)} 個變化點: {', '.join(cp_summary)}。"
            )
        else:
            conclusion_parts.append("CUSUM 未偵測到顯著製程漂移。")

        return {
            "parameter": col,
            "total_points": n,
            "trend": trend,
            "slope_per_unit": slope_per_unit,
            "total_change_pct": f"{slope_pct:.2f}%",
            "mean": mean_val,
            "std": std_val,
            "segment_means": {
                "first_third": seg1_mean,
                "middle_third": seg2_mean,
                "last_third": seg3_mean,
            },
            "cusum_change_points": change_points[:10],
            "cusum_total_shifts": len(change_points),
            "conclusion": " ".join(conclusion_parts),
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
        threshold_std = params.get("threshold_std", 3.0)

        # 基礎攔截：支援多欄位字串或清單
        if isinstance(col, str):
            cols = [c.strip() for c in col.split(",")]
        elif isinstance(col, list):
            cols = col
        else:
            cols = [str(col)]

        try:
            summary = self.analysis_service.load_summary(session_id, file_id)
            csv_path = (
                self.analysis_service.base_dir
                / session_id
                / "uploads"
                / summary["filename"]
            )

            # 帶入 lambda 解析以防 usecols 崩潰
            df = pd.read_csv(csv_path, usecols=lambda x: x in cols)
            if df.empty or cols[0] not in df.columns:
                return {"error": f"找不到指定欄位: {cols}"}

            # 使用第一個欄位進行分析
            data = df[cols[0]].dropna()
            col = cols[0]
        except Exception as e:
            return {"error": f"讀取數據失敗: {str(e)}"}

        if len(data) < 10:
            return {"error": "數據量不足，無法進行事件偵測。"}

        mean = data.mean()
        std = data.std()

        if std == 0:
            return {
                "parameter": col,
                "total_events": 0,
                "events_preview": [],
                "conclusion": f"參數 {col} 為定值，無突發事件。",
            }

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
            "conclusion": f"偵測到 {len(events)} 個突發事件。"
            if events
            else "未偵測到突發事件。",
        }
