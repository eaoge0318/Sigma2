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

            # --- Global statistics for reference (Robust: Median + MAD) ---
            full_series = pd.to_numeric(df[parameter], errors="coerce").dropna()
            global_mean = float(full_series.median())
            mad = float(np.median(np.abs(full_series - global_mean)))
            global_std = mad * 1.4826  # MAD-based robust std estimator
            if global_std < 1e-10:
                global_std = full_series.std()  # fallback if MAD is zero

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
                "raw_values": series.values.tolist(),
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
            # [FIX] Freeze 判定加入絕對門檻: global_std 本身太小時 (< 0.1),
            # 所有窗口都通過 freeze 條件, 導致穩定參數被大量誤報
            is_anomalous = (
                (
                    global_std > 0.1 and w_std < global_std * 0.05
                )  # Freeze (需 global_std > 0.1)
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
        # [PRIORITY ORDER] DRIFT/OSCILLATION/SPIKE 優先於 FREEZE
        # 工業場景: 穩定數據是「正常」, 漂移和震盪才是「異常」
        result = {
            "variance_ratio": round(float(variance_ratio), 3),
            "autocorrelation_lag1": round(float(autocorr), 3),
            "sign_change_rate": round(float(sign_change_rate), 3),
            "trend_strength": round(float(trend_strength), 3),
            "segment_std": round(float(seg_std), 6),
            "segment_mean": round(float(seg_mean), 4),
        }

        # [1] Drift: strong linear trend (最高優先級 - 系統漂移)
        # [FIX] 門檻從 1.5 提高到 2.5, 避免微小趨勢被標為 DRIFT
        if trend_strength > 2.5:
            direction = "上升" if slope > 0 else "下降"
            result["type"] = "DRIFT"
            result["confidence"] = min(0.95, trend_strength / 4)
            result["description"] = (
                f"持續漂移 ({direction}): 趨勢強度 {trend_strength:.1f}。"
                "可能原因: 製程條件緩慢變化、耗材磨損、或環境溫度漂移。"
            )

        # [2] Oscillation: high variance + high sign change rate (控制震盪)
        elif variance_ratio > 1.5 and sign_change_rate > 0.4:
            result["type"] = "OSCILLATION"
            result["confidence"] = min(0.95, sign_change_rate * variance_ratio / 3)
            result["description"] = (
                f"控制震盪: 方差比 {variance_ratio:.1f}x, 方向變換率 {sign_change_rate:.1%}。"
                "可能原因: PID 增益過高 (Over-tuning)、外部干擾 (Disturbance)、或控制迴路不穩定。"
            )

        # [3] Spike: very short + high max deviation (突波)
        elif seg_len <= 5 and variance_ratio > 2:
            result["type"] = "SPIKE"
            max_dev = abs(segment - global_mean).max()
            result["confidence"] = min(0.9, max_dev / (global_std * 3))
            result["description"] = (
                f"突波: 在 {seg_len} 個點內出現劇烈波動 (最大偏移 {max_dev:.4f})。"
                "可能原因: 瞬間干擾 (基材接頭、Splice)、量測雜訊、或設備瞬斷。"
            )

        # [3.5] DIP_RECOVERY: V 或 倒V 型態 — 急跌後恢復或急升後回落
        elif seg_len >= 3 and seg_len <= 30 and variance_ratio > 1.5:
            vals = segment.values
            mid = len(vals) // 2
            first_half_mean = np.mean(vals[:mid]) if mid > 0 else vals[0]
            middle_val = np.mean(vals[max(0, mid - 1) : min(len(vals), mid + 2)])
            second_half_mean = np.mean(vals[mid:]) if mid < len(vals) else vals[-1]
            # V 型: 先跌後升
            v_depth = min(first_half_mean, second_half_mean) - middle_val
            # 倒V 型: 先升後跌
            inv_v_height = middle_val - max(first_half_mean, second_half_mean)
            if v_depth > global_std * 1.5:
                result["type"] = "DIP_RECOVERY"
                result["confidence"] = min(0.9, v_depth / (global_std * 3))
                result["description"] = (
                    f"急跌恢復 (V型): 中段下跌 {v_depth:.4f} 後回升。"
                    "可能原因: 暫態干擾後自動修復、控制系統校正動作。"
                )
            elif inv_v_height > global_std * 1.5:
                result["type"] = "DIP_RECOVERY"
                result["confidence"] = min(0.9, inv_v_height / (global_std * 3))
                result["description"] = (
                    f"急升回落 (倒V型): 中段上升 {inv_v_height:.4f} 後回落。"
                    "可能原因: 短暫過衝 (Overshoot)、暫態擾動。"
                )
            else:
                # 不符合 DIP_RECOVERY，回退判定 LEVEL_SHIFT 或 SPIKE
                if abs(seg_mean - global_mean) > global_std * 2 and variance_ratio < 2:
                    shift = seg_mean - global_mean
                    result["type"] = "LEVEL_SHIFT"
                    result["confidence"] = min(0.9, abs(shift) / (global_std * 3))
                    result["description"] = (
                        f"水平偏移: 均值偏移 {shift:+.4f} (全域均值 {global_mean:.4f})。"
                        "可能原因: 配方切換、設定值變更 (SP Change)、或原料批次差異。"
                    )
                else:
                    result["type"] = "SPIKE"
                    max_dev = abs(segment - global_mean).max()
                    result["confidence"] = min(0.9, max_dev / (global_std * 3))
                    result["description"] = (
                        f"突波: 在 {seg_len} 個點內出現波動 (最大偏移 {max_dev:.4f})。"
                        "可能原因: 瞬間干擾或量測雜訊。"
                    )

        # [4] Level Shift: mean shift without high variance (水平偏移)
        elif abs(seg_mean - global_mean) > global_std * 2 and variance_ratio < 2:
            shift = seg_mean - global_mean
            result["type"] = "LEVEL_SHIFT"
            result["confidence"] = min(0.9, abs(shift) / (global_std * 3))
            result["description"] = (
                f"水平偏移: 均值偏移 {shift:+.4f} (全域均值 {global_mean:.4f})。"
                "可能原因: 配方切換、設定值變更 (SP Change)、或原料批次差異。"
            )

        # [5] Freeze: extremely low variance (嚴格門檻, 避免正常穩定數據被誤判)
        # [FIX] 加入 global_std > 0.1 前提: 當整體標準差本身就很小時,
        # 穩定參數不應該被判為 freeze
        elif variance_ratio < 0.05 and seg_std < 0.001 and global_std > 0.1:
            result["type"] = "FREEZE"
            result["confidence"] = min(0.99, 1.0 - variance_ratio)
            result["description"] = (
                f"系統凍結: 標準差僅 {seg_std:.6f} (全域的 {variance_ratio:.1%})。"
                "可能原因: 傳感器未更新、控制器切換手動模式、或系統飽和 (Saturation)。"
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


class GlobalAnomalySegmentScanner(AnalysisTool):
    """
    全域異常區段掃描器 (Global Anomaly Segment Scanner)

    自動掃描所有數值欄位,使用滑動窗口偵測異常區段,
    並按 Row 範圍分群輸出問題區段摘要。

    輸出格式:
    | 區段 | 涉及參數 | 異常類型 | 嚴重程度 | 說明 |
    | Row 472-529 | KAPPA_IN-13PC_2043 | FREEZE | HIGH | 標準差僅 0.014 |
    """

    @property
    def name(self) -> str:
        return "scan_anomaly_segments"

    @property
    def description(self) -> str:
        return (
            "全域異常區段掃描: 自動掃描所有數值欄位,"
            "偵測異常 Row 範圍 (FREEZE/DRIFT/SPIKE/OSCILLATION/LEVEL_SHIFT),"
            "按嚴重程度排名輸出問題區段表。適用於無目標分析的初始掃描。"
        )

    @property
    def required_params(self) -> List[str]:
        return ["file_id"]

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

            # 取得所有數值欄位
            numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
            if not numeric_cols:
                return {"status": "ERROR", "message": "No numeric columns found"}

            total_rows = len(df)

            # --- Phase 1: 快速預篩 (CV + Z-Score) ---
            # 只掃描有異常跡象的欄位,避免掃描 343 個全部耗時
            candidate_cols = []
            for col in numeric_cols:
                series = df[col].dropna()
                if len(series) < 10:
                    continue
                std = series.std()
                mean = series.mean()
                if std == 0:
                    continue  # 完全常數,跳過

                cv = abs(std / mean) if mean != 0 else float("inf")

                # [FIX] 跳過 CV 極低的 (近常數,Z-Score 會虛高)
                # 門檻從 0.01 提高到 0.02 (CV < 2% 的參數變異太小, 不具分析價值)
                if cv < 0.02:
                    continue

                # 計算 max Z-Score, 快速判斷是否值得深入
                z_scores = ((series - mean) / std).abs()
                max_z = float(z_scores.max())

                # 也計算局部變異: 把資料分 4 段,看段間方差比
                quarter = len(series) // 4
                if quarter > 5:
                    quarter_stds = [
                        series.iloc[i * quarter : (i + 1) * quarter].std()
                        for i in range(4)
                    ]
                    variance_ratio = max(quarter_stds) / (min(quarter_stds) + 1e-10)
                else:
                    variance_ratio = 1.0

                # [NEW] 計算線性回歸斜率, 偵測整段漂移 (Drift)
                x = np.arange(len(series))
                slope = np.polyfit(x, series.values, 1)[0]
                # normalized_slope = 漂移量(slope*N)相對於std的比例
                drift_total = abs(slope * len(series))
                normalized_slope = drift_total / (std + 1e-10)

                # [FIX] 加入絕對偏差過濾: 即使 Z > 3, 如果最大偏差相對均值 < 0.5%,
                # 也排除 (避免像 860.00 ± 0.1 被當成異常)
                max_abs_dev = float((series - mean).abs().max())
                relative_dev = max_abs_dev / abs(mean) if mean != 0 else float("inf")
                if relative_dev < 0.005:  # 偏差 < 0.5% of mean
                    continue

                # 候選條件: 有異常 Z-Score 或 段間方差比超過 3 或 整段漂移超過 2σ
                if max_z > 3.0 or variance_ratio > 3.0 or normalized_slope > 2.0:
                    candidate_cols.append(
                        {
                            "col": col,
                            "max_z": max_z,
                            "variance_ratio": variance_ratio,
                            "cv": cv,
                            "normalized_slope": normalized_slope,
                        }
                    )

            # 按嚴重程度排序,最多掃描 Top 30
            candidate_cols.sort(
                key=lambda x: (
                    x["max_z"] * 0.4
                    + x["variance_ratio"] * 0.3
                    + x.get("normalized_slope", 0) * 0.3
                ),
                reverse=True,
            )
            scan_cols = [c["col"] for c in candidate_cols[:30]]

            if not scan_cols:
                return {
                    "status": "SUCCESS",
                    "total_columns_scanned": len(numeric_cols),
                    "candidates_found": 0,
                    "segment_table": [],
                    "summary": "全域掃描完成,未發現顯著異常區段。所有參數在正常範圍內。",
                }

            # --- Phase 2: 集成異常區段偵測 (Ensemble Detection) ---
            # 同時執行 4 種方法: 滑動窗口 + CUSUM + EWMA + Change Point Detection
            from .advanced_detectors import ensemble_detect

            all_segments = []
            all_consensus_zones = []
            classifier = AnomalyClassifierTool(self.analysis_service)

            for col in scan_cols:
                series = pd.to_numeric(df[col], errors="coerce").dropna()
                if len(series) < 10:
                    continue

                global_mean = float(series.median())
                _mad = float(np.median(np.abs(series - global_mean)))
                global_std = _mad * 1.4826  # MAD-based robust std
                if global_std < 1e-10:
                    global_std = series.std()  # fallback

                if global_std == 0:
                    continue

                # --- Method 1: 滑動窗口 (原有方法) ---
                window_size = max(5, len(series) // 20)
                sw_regions = classifier._detect_anomaly_regions(
                    series, global_std, global_mean, window_size
                )

                for region in sw_regions:
                    start, end = region["start"], region["end"]
                    segment = series.iloc[start : end + 1]
                    classification = classifier._classify_segment(
                        segment, global_std, global_mean
                    )

                    severity_score = self._calc_severity(
                        classification, global_std, global_mean
                    )

                    all_segments.append(
                        {
                            "parameter": col,
                            "row_start": start,
                            "row_end": end,
                            "row_range": f"Row {start}-{end}",
                            "length": end - start + 1,
                            "type": classification["type"],
                            "severity": self._severity_label(severity_score),
                            "severity_score": round(severity_score, 2),
                            "segment_std": classification.get("segment_std", 0),
                            "segment_mean": classification.get("segment_mean", 0),
                            "variance_ratio": classification.get("variance_ratio", 0),
                            "description": classification.get("description", ""),
                            "detection_methods": ["SlidingWindow"],
                        }
                    )

                # --- Method 2/3/4: CUSUM + EWMA + Change Point (集成) ---
                try:
                    ensemble_result = ensemble_detect(series)

                    # 處理 CUSUM/EWMA/ChangePoint 偵測到但滑動窗口沒抓到的區段
                    for method_key in [
                        "cusum_segments",
                        "ewma_segments",
                        "changepoint_segments",
                    ]:
                        for adv_seg in ensemble_result.get(method_key, []):
                            start, end = adv_seg["start"], adv_seg["end"]

                            # 檢查是否已被滑動窗口覆蓋 (避免重複)
                            already_covered = any(
                                s["parameter"] == col
                                and s["row_start"] <= start
                                and s["row_end"] >= end
                                for s in all_segments
                            )

                            if not already_covered and end > start:
                                segment = series.iloc[start : end + 1]
                                if len(segment) < 3:
                                    continue

                                classification = classifier._classify_segment(
                                    segment, global_std, global_mean
                                )
                                severity_score = self._calc_severity(
                                    classification, global_std, global_mean
                                )

                                method_name = adv_seg.get("method", "ADVANCED")
                                all_segments.append(
                                    {
                                        "parameter": col,
                                        "row_start": start,
                                        "row_end": end,
                                        "row_range": f"Row {start}-{end}",
                                        "length": end - start + 1,
                                        "type": classification["type"],
                                        "severity": self._severity_label(
                                            severity_score
                                        ),
                                        "severity_score": round(severity_score, 2),
                                        "segment_std": classification.get(
                                            "segment_std", 0
                                        ),
                                        "segment_mean": classification.get(
                                            "segment_mean", 0
                                        ),
                                        "variance_ratio": classification.get(
                                            "variance_ratio", 0
                                        ),
                                        "description": classification.get(
                                            "description", ""
                                        ),
                                        "detection_methods": [method_name],
                                    }
                                )

                    # 收集共識區段 (多方法交集)
                    for cz in ensemble_result.get("consensus_zones", []):
                        cz["parameter"] = col
                        all_consensus_zones.append(cz)

                except Exception as e:
                    logger.warning(f"Advanced detection failed for {col}: {e}")

            # --- Phase 3: 按嚴重程度排序 + 分群 ---
            all_segments.sort(key=lambda x: x["severity_score"], reverse=True)

            # 合併重疊區間 (不同參數在同一 Row 範圍的異常歸為一群)
            merged_groups = self._merge_overlapping_segments(all_segments)

            # 輸出最多 15 個最嚴重的區段
            top_segments = all_segments[:15]

            # 統計摘要
            type_counts = {}
            param_counts = {}
            for seg in all_segments:
                t = seg["type"]
                p = seg["parameter"]
                type_counts[t] = type_counts.get(t, 0) + 1
                param_counts[p] = param_counts.get(p, 0) + 1

            # 找出問題最多的參數
            worst_params = sorted(
                param_counts.items(), key=lambda x: x[1], reverse=True
            )[:5]

            # 統計各偵測方法的貢獻
            method_stats = {}
            for seg in all_segments:
                for m in seg.get("detection_methods", ["SlidingWindow"]):
                    method_stats[m] = method_stats.get(m, 0) + 1

            # --- [NEW] 按異常類型分組輸出 ---
            ANOMALY_TYPE_CN = {
                "DRIFT": "持續漂移",
                "LEVEL_SHIFT": "階梯跳變",
                "SPIKE": "突波/急升",
                "OSCILLATION": "震盪不穩",
                "FREEZE": "凍結/卡值",
                "DIP_RECOVERY": "急跌恢復",
                "MIXED": "混合異常",
            }
            type_groups = {}  # type -> {params, ranges, max_severity}
            for seg in all_segments:
                t = seg["type"]
                p = seg["parameter"]
                rr = seg.get("row_range", "")
                sev = seg.get("severity_score", 0)
                if t not in type_groups:
                    type_groups[t] = {
                        "type": t,
                        "type_cn": ANOMALY_TYPE_CN.get(t, t),
                        "parameters": [],
                        "param_count": 0,
                        "ranges": [],
                        "max_severity": 0,
                        "total_segments": 0,
                    }
                grp = type_groups[t]
                if p not in grp["parameters"]:
                    grp["parameters"].append(p)
                if rr and rr not in grp["ranges"]:
                    grp["ranges"].append(rr)
                grp["max_severity"] = max(grp["max_severity"], sev)
                grp["total_segments"] += 1

            for grp in type_groups.values():
                grp["param_count"] = len(grp["parameters"])

            # 按參數數量排序（多參數的類型更重要）
            anomaly_type_groups = sorted(
                type_groups.values(),
                key=lambda x: (x["param_count"], x["max_severity"]),
                reverse=True,
            )

            return {
                "status": "SUCCESS",
                "total_columns_scanned": len(numeric_cols),
                "candidates_checked": len(scan_cols),
                "total_anomaly_segments": len(all_segments),
                "total_data_rows": total_rows,
                "anomaly_type_distribution": type_counts,
                "anomaly_type_groups": anomaly_type_groups,
                "detection_method_coverage": method_stats,
                "worst_parameters": [
                    {"parameter": p, "anomaly_count": c} for p, c in worst_params
                ],
                "consensus_zones": all_consensus_zones[:10],
                "merged_problem_zones": merged_groups[:10],
                "top_segments": top_segments,
                "engineering_summary": self._build_engineering_summary(
                    all_segments, type_counts, total_rows
                ),
            }

        except Exception as e:
            logger.error(f"GlobalAnomalySegmentScanner error: {e}")
            return {"status": "ERROR", "message": str(e)}

    def _calc_severity(
        self, classification: Dict, global_std: float, global_mean: float
    ) -> float:
        """計算嚴重程度分數 (0-10)"""
        atype = classification.get("type", "MIXED")
        vr = classification.get("variance_ratio", 1.0)
        length = classification.get("length", 0) if "length" in classification else 1

        if atype == "FREEZE":
            # Freeze: 降低基礎分 (正常穩定數據不應高分)
            return min(10, 3 + length / 30)
        elif atype == "OSCILLATION":
            # 控制震盪: 提高優先級
            return min(10, 5 + vr * 2)
        elif atype == "SPIKE":
            return min(10, 4 + vr * 2)
        elif atype == "DRIFT":
            # 系統漂移: 最高優先級
            ts = classification.get("trend_strength", 0)
            return min(10, 5 + ts * 1.5)
        elif atype == "LEVEL_SHIFT":
            seg_mean = classification.get("segment_mean", 0)
            shift = abs(seg_mean - global_mean) / (global_std + 1e-10)
            return min(10, 4 + shift * 0.8)
        else:
            return 3.0

    def _severity_label(self, score: float) -> str:
        if score >= 8:
            return "CRITICAL"
        elif score >= 6:
            return "HIGH"
        elif score >= 4:
            return "MEDIUM"
        else:
            return "LOW"

    def _merge_overlapping_segments(self, segments: List[Dict]) -> List[Dict]:
        """將重疊的異常區段合併為問題區域, 保留每個參數的異常類型映射"""
        if not segments:
            return []

        # 按 row_start 排序
        sorted_segs = sorted(segments, key=lambda x: x["row_start"])

        def _new_group(seg):
            return {
                "zone_start": seg["row_start"],
                "zone_end": seg["row_end"],
                "parameters": [seg["parameter"]],
                "types": [seg["type"]],
                "max_severity": seg["severity_score"],
                # [NEW] 保留每個參數的異常類型映射
                "param_details": [
                    {
                        "parameter": seg["parameter"],
                        "type": seg["type"],
                        "severity": seg.get("severity_score", 0),
                        "description": seg.get("description", ""),
                        "row_range": seg.get("row_range", ""),
                    }
                ],
            }

        groups = []
        current_group = _new_group(sorted_segs[0])

        for seg in sorted_segs[1:]:
            # 如果和目前群組有重疊 (允許 10 Row 的間隔)
            if seg["row_start"] <= current_group["zone_end"] + 10:
                current_group["zone_end"] = max(
                    current_group["zone_end"], seg["row_end"]
                )
                if seg["parameter"] not in current_group["parameters"]:
                    current_group["parameters"].append(seg["parameter"])
                if seg["type"] not in current_group["types"]:
                    current_group["types"].append(seg["type"])
                current_group["max_severity"] = max(
                    current_group["max_severity"], seg["severity_score"]
                )
                # [NEW] 加入參數細節 (同參數可能有多種異常)
                current_group["param_details"].append(
                    {
                        "parameter": seg["parameter"],
                        "type": seg["type"],
                        "severity": seg.get("severity_score", 0),
                        "description": seg.get("description", ""),
                        "row_range": seg.get("row_range", ""),
                    }
                )
            else:
                current_group["zone_range"] = (
                    f"Row {current_group['zone_start']}-{current_group['zone_end']}"
                )
                current_group["affected_params_count"] = len(
                    current_group["parameters"]
                )
                # [NEW] 生成 zone_label: 按異常類型分組顯示參數
                current_group["zone_label"] = self._build_zone_label(
                    current_group["param_details"]
                )
                groups.append(current_group)
                current_group = _new_group(seg)

        # 最後一個群組
        current_group["zone_range"] = (
            f"Row {current_group['zone_start']}-{current_group['zone_end']}"
        )
        current_group["affected_params_count"] = len(current_group["parameters"])
        current_group["zone_label"] = self._build_zone_label(
            current_group["param_details"]
        )
        groups.append(current_group)

        # 按嚴重程度排序 — 多參數共變的 zone 優先
        # composite_severity: 參數數量越多 → 加乘越高
        for g in groups:
            n = g.get("affected_params_count", 1)
            g["composite_severity"] = round(g["max_severity"] * (1 + 0.3 * (n - 1)), 2)
        groups.sort(
            key=lambda x: x["composite_severity"],
            reverse=True,
        )
        return groups

    def _build_zone_label(self, param_details: List[Dict]) -> str:
        """按異常類型分組顯示參數, 生成 zone_label 摘要字串
        例如: 'DRIFT: A15, B40 | SPIKE: C12'
        """
        from collections import defaultdict

        type_to_params = defaultdict(set)
        for detail in param_details:
            p = detail.get("parameter", "")
            t = detail.get("type", "MIXED")
            if p:
                type_to_params[t].add(p)

        # 按嚴重度排序: DRIFT > OSCILLATION > SPIKE > LEVEL_SHIFT > FREEZE > MIXED
        type_order = {
            "DRIFT": 0,
            "OSCILLATION": 1,
            "SPIKE": 2,
            "LEVEL_SHIFT": 3,
            "FREEZE": 4,
            "MIXED": 5,
        }
        sorted_types = sorted(
            type_to_params.items(), key=lambda x: type_order.get(x[0], 9)
        )

        parts = []
        for atype, params in sorted_types:
            param_str = ", ".join(sorted(params)[:5])
            if len(params) > 5:
                param_str += f" (+{len(params) - 5})"
            parts.append(f"{atype}: {param_str}")

        return " | ".join(parts) if parts else "UNKNOWN"

    def _build_engineering_summary(
        self, segments: List[Dict], type_counts: Dict, total_rows: int
    ) -> str:
        """生成工程層級的摘要文字"""
        if not segments:
            return "全域掃描結果: 所有參數在正常範圍內,未發現異常區段。"

        total_anomaly_rows = set()
        for seg in segments:
            for r in range(seg["row_start"], seg["row_end"] + 1):
                total_anomaly_rows.add(r)

        anomaly_pct = (
            len(total_anomaly_rows) / total_rows * 100 if total_rows > 0 else 0
        )

        lines = [
            f"全域異常區段掃描結果: {len(segments)} 個異常區段,",
            f"覆蓋 {len(total_anomaly_rows)}/{total_rows} 行數據 ({anomaly_pct:.1f}%)。",
        ]

        for atype, count in sorted(
            type_counts.items(), key=lambda x: x[1], reverse=True
        ):
            lines.append(f"- {atype}: {count} 個區段")

        # 找最嚴重的
        worst = segments[0]
        lines.append(
            f"最嚴重: {worst['parameter']} Row {worst['row_start']}-{worst['row_end']} "
            f"({worst['type']}, severity={worst['severity_score']})"
        )

        return " ".join(lines)
