"""
異常類型分類器 (Anomaly Type Classifier)

將偵測到的異常區間分類為具體的異常模式:
- Freeze: 標準差趨近 0, 傳感器/控制器鎖死
- Oscillation: 高方差 + 高自相關, PID 震盪
- Spike: 單點突變
- Drift: 持續偏移
- Level Shift: 階梯式變化
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List
from .base import AnalysisTool
import logging

logger = logging.getLogger(__name__)


class AnomalyClassifierTool(AnalysisTool):
    """異常類型分類器 -- 區分 Freeze / Oscillation / Spike / Drift / Level Shift"""

    @property
    def name(self) -> str:
        return "classify_anomaly_type"

    @property
    def description(self) -> str:
        return "將異常區間分類為具體模式 (Freeze/Oscillation/Spike/Drift/Level Shift)"

    @property
    def required_params(self) -> List[str]:
        return ["parameter"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        try:
            file_id = params.get("file_id")
            summary = self.analysis_service.load_summary(session_id, file_id)
            if not summary:
                return {"status": "ERROR", "message": "No summary data available"}
            filename = summary["filename"]
            csv_path = (
                self.analysis_service.base_dir / session_id / "uploads" / filename
            )
            df = pd.read_csv(csv_path)
            if df is None or df.empty:
                return {"status": "ERROR", "message": "No data available"}

            parameter = params.get("parameter", "")
            if parameter not in df.columns:
                return {"status": "ERROR", "message": f"Column '{parameter}' not found"}

            series = pd.to_numeric(df[parameter], errors="coerce").dropna()
            if len(series) < 10:
                return {"status": "ERROR", "message": "Insufficient data points"}

            # Parse focus range if provided
            focus_range = params.get("focus_range")
            if focus_range:
                indices = self.parse_indices(focus_range, max_len=len(series))
                if indices:
                    series = series.iloc[indices]

            # --- Global statistics for reference ---
            full_series = pd.to_numeric(df[parameter], errors="coerce").dropna()
            global_std = full_series.std()
            global_mean = full_series.mean()

            # --- Sliding window analysis ---
            window_size = max(5, len(series) // 20)
            anomaly_regions = self._detect_anomaly_regions(
                series, global_std, global_mean, window_size
            )

            # --- Classify each region ---
            classified = []
            for region in anomaly_regions:
                start, end = region["start"], region["end"]
                segment = series.iloc[start : end + 1]
                classification = self._classify_segment(
                    segment, global_std, global_mean
                )
                classification["range"] = f"{start}-{end}"
                classification["length"] = end - start + 1
                classified.append(classification)

            # --- Overall summary ---
            type_counts = {}
            for c in classified:
                t = c["type"]
                type_counts[t] = type_counts.get(t, 0) + 1

            return {
                "status": "SUCCESS",
                "parameter": parameter,
                "total_anomaly_regions": len(classified),
                "type_summary": type_counts,
                "classifications": classified[:10],  # Limit to 10
                "global_stats": {
                    "mean": round(float(global_mean), 4),
                    "std": round(float(global_std), 4),
                    "data_points": len(series),
                },
                "engineering_hints": self._generate_engineering_hints(classified),
            }

        except Exception as e:
            logger.error(f"AnomalyClassifier error: {e}")
            return {"status": "ERROR", "message": str(e)}

    def _detect_anomaly_regions(
        self, series: pd.Series, global_std: float, global_mean: float, window_size: int
    ) -> List[Dict]:
        """使用滑動窗口偵測異常區域"""
        regions = []
        n = len(series)
        if n < window_size:
            return regions

        in_anomaly = False
        start_idx = 0

        for i in range(0, n - window_size + 1):
            window = series.iloc[i : i + window_size]
            w_std = window.std()
            w_mean = window.mean()

            # Anomaly criteria: very low std (freeze) or very high std (oscillation)
            # or large deviation from global mean (drift/shift)
            is_anomalous = (
                (global_std > 0 and w_std < global_std * 0.05)  # Freeze
                or (global_std > 0 and w_std > global_std * 2.5)  # High variance
                or (
                    global_std > 0 and abs(w_mean - global_mean) > global_std * 2.5
                )  # Shifted
            )

            if is_anomalous and not in_anomaly:
                start_idx = i
                in_anomaly = True
            elif not is_anomalous and in_anomaly:
                regions.append({"start": start_idx, "end": i + window_size - 2})
                in_anomaly = False

        if in_anomaly:
            regions.append({"start": start_idx, "end": n - 1})

        return regions

    def _classify_segment(
        self, segment: pd.Series, global_std: float, global_mean: float
    ) -> Dict[str, Any]:
        """分類單一異常區段"""
        seg_std = segment.std()
        seg_mean = segment.mean()
        seg_len = len(segment)

        # --- Feature extraction ---
        # 1. Variance ratio (vs global)
        variance_ratio = seg_std / global_std if global_std > 0 else 0

        # 2. First-order difference (for spike/oscillation detection)
        diff = segment.diff().dropna()
        sign_changes = (
            (diff.iloc[:-1].values * diff.iloc[1:].values < 0).sum()
            if len(diff) > 2
            else 0
        )
        sign_change_rate = sign_changes / max(1, len(diff) - 1)

        # 3. Autocorrelation at lag 1 (for oscillation)
        if seg_len >= 5:
            try:
                autocorr = segment.autocorr(lag=1)
                if pd.isna(autocorr):
                    autocorr = 0.0
            except Exception:
                autocorr = 0.0
        else:
            autocorr = 0.0

        # 4. Linear trend (for drift)
        x = np.arange(seg_len)
        if seg_len >= 3 and seg_std > 0:
            slope = np.polyfit(x, segment.values, 1)[0]
            trend_strength = abs(slope * seg_len) / (seg_std + 1e-10)
        else:
            slope = 0
            trend_strength = 0

        # --- Classification rules ---
        result = {
            "variance_ratio": round(float(variance_ratio), 3),
            "autocorrelation_lag1": round(float(autocorr), 3),
            "sign_change_rate": round(float(sign_change_rate), 3),
            "trend_strength": round(float(trend_strength), 3),
            "segment_std": round(float(seg_std), 6),
            "segment_mean": round(float(seg_mean), 4),
        }

        # Freeze: extremely low variance
        if variance_ratio < 0.1:
            result["type"] = "FREEZE"
            result["confidence"] = min(0.99, 1.0 - variance_ratio)
            result["description"] = (
                f"系統凍結: 標準差僅 {seg_std:.6f} (全域的 {variance_ratio:.1%})。"
                "可能原因: 傳感器未更新、控制器切換手動模式、或系統飽和 (Saturation)。"
            )

        # Oscillation: high variance + high sign change rate (frequent direction changes)
        elif variance_ratio > 1.5 and sign_change_rate > 0.4:
            result["type"] = "OSCILLATION"
            result["confidence"] = min(0.95, sign_change_rate * variance_ratio / 3)
            result["description"] = (
                f"控制震盪: 方差比 {variance_ratio:.1f}x, 方向變換率 {sign_change_rate:.1%}。"
                "可能原因: PID 增益過高 (Over-tuning)、外部干擾 (Disturbance)、或控制迴路不穩定。"
            )

        # Spike: very short + high max deviation
        elif seg_len <= 5 and variance_ratio > 2:
            result["type"] = "SPIKE"
            max_dev = abs(segment - global_mean).max()
            result["confidence"] = min(0.9, max_dev / (global_std * 3))
            result["description"] = (
                f"突波: 在 {seg_len} 個點內出現劇烈波動 (最大偏移 {max_dev:.4f})。"
                "可能原因: 瞬間干擾 (基材接頭、Splice)、量測雜訊、或設備瞬斷。"
            )

        # Drift: strong linear trend
        elif trend_strength > 2.0:
            direction = "上升" if slope > 0 else "下降"
            result["type"] = "DRIFT"
            result["confidence"] = min(0.9, trend_strength / 5)
            result["description"] = (
                f"持續漂移 ({direction}): 趨勢強度 {trend_strength:.1f}。"
                "可能原因: 製程條件緩慢變化、耗材磨損、或環境溫度漂移。"
            )

        # Level Shift: mean shift without high variance
        elif abs(seg_mean - global_mean) > global_std * 2 and variance_ratio < 2:
            shift = seg_mean - global_mean
            result["type"] = "LEVEL_SHIFT"
            result["confidence"] = min(0.9, abs(shift) / (global_std * 3))
            result["description"] = (
                f"水平偏移: 均值偏移 {shift:+.4f} (全域均值 {global_mean:.4f})。"
                "可能原因: 配方切換、設定值變更 (SP Change)、或原料批次差異。"
            )

        else:
            result["type"] = "MIXED"
            result["confidence"] = 0.5
            result["description"] = (
                f"混合異常: 方差比 {variance_ratio:.1f}x, 無法歸類為單一模式。"
                "建議使用頻域分析 (frequency_analysis) 進一步診斷。"
            )

        return result

    def _generate_engineering_hints(self, classified: List[Dict]) -> List[str]:
        """根據分類結果產生工程建議"""
        hints = []
        types_found = set(c["type"] for c in classified)

        if "FREEZE" in types_found:
            hints.append(
                "發現系統凍結 (FREEZE) 區間 -- 建議: (1) 檢查操作日誌是否有手動介入紀錄 "
                "(2) 確認傳感器通訊狀態 (3) 使用 frequency_analysis 確認高頻噪聲是否消失"
            )

        if "OSCILLATION" in types_found:
            hints.append(
                "發現控制震盪 (OSCILLATION) -- 建議: (1) 檢查 PID 控制參數 (P/D 可能過高) "
                "(2) 使用 cross_correlation_lag 確認控制迴路的 Lag "
                "(3) 使用 control_loop_assessment 評估控制品質"
            )

        if "SPIKE" in types_found:
            hints.append(
                "發現突波 (SPIKE) -- 建議: (1) 檢查上游供料是否有接頭通過 (Splice) "
                "(2) 使用 find_event_patterns 偵測事件序列 "
                "(3) 使用 compare_data_segments 比較異常前後差異"
            )

        if "DRIFT" in types_found:
            hints.append(
                "發現持續漂移 (DRIFT) -- 建議: (1) 檢查耗材壽命與更換紀錄 "
                "(2) 使用 find_temporal_patterns 確認漂移趨勢 "
                "(3) 使用 distribution_shift_analysis 量化漂移程度"
            )

        if "LEVEL_SHIFT" in types_found:
            hints.append(
                "發現水平偏移 (LEVEL_SHIFT) -- 建議: (1) 確認是否有配方或設定值變更 "
                "(2) 使用 compare_data_segments 比較偏移前後數據 "
                "(3) 檢查原料批次切換紀錄"
            )

        return hints
