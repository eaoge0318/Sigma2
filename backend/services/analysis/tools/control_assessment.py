"""
控制回路性能評估 (Control Loop Performance Assessment)

評估控制回路品質:
- Harris Index: 最小方差控制的理想表現 vs 實際表現
- 追蹤誤差分析: SP - PV 的分佈與自相關
- 控制器輸出飽和偵測
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List
from .base import AnalysisTool
import logging

logger = logging.getLogger(__name__)


class ControlLoopAssessmentTool(AnalysisTool):
    """控制回路性能評估 -- Harris Index、追蹤誤差、飽和偵測"""

    @property
    def name(self) -> str:
        return "control_loop_assessment"

    @property
    def description(self) -> str:
        return "評估控制回路品質 (Harris Index, 追蹤誤差, 飽和偵測)"

    @property
    def required_params(self) -> List[str]:
        return ["process_variable"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        try:
            file_id = params.get("file_id")
            summary = self.analysis_service.load_summary(session_id, file_id)
            if not summary:
                return {"status": "ERROR", "message": "No summary data available"}
            filename = summary["filename"]
            csv_path = (
                self.analysis_service.get_csv_path(session_id, filename)
            )
            df = pd.read_csv(csv_path)
            if df is None or df.empty:
                return {"status": "ERROR", "message": "No data available"}

            pv_col = params.get("process_variable", "")
            sp_col = params.get("setpoint", "")
            co_col = params.get("controller_output", "")

            if pv_col not in df.columns:
                return {"status": "ERROR", "message": f"Column '{pv_col}' not found"}

            pv = pd.to_numeric(df[pv_col], errors="coerce").dropna()
            if len(pv) < 20:
                return {
                    "status": "ERROR",
                    "message": "Insufficient data (need >= 20 points)",
                }

            result = {
                "status": "SUCCESS",
                "process_variable": pv_col,
            }

            # --- 1. Harris Index (Minimum Variance Benchmark) ---
            harris = self._compute_harris_index(pv.values)
            result["harris_index"] = harris

            # --- 2. Tracking Error Analysis (if SP available) ---
            if sp_col and sp_col in df.columns:
                sp = pd.to_numeric(df[sp_col], errors="coerce").dropna()
                common_idx = pv.index.intersection(sp.index)
                if len(common_idx) >= 10:
                    tracking = self._analyze_tracking_error(
                        pv.loc[common_idx].values, sp.loc[common_idx].values
                    )
                    result["tracking_error"] = tracking
                    result["setpoint"] = sp_col

            # --- 3. Controller Output Analysis (if CO available) ---
            if co_col and co_col in df.columns:
                co = pd.to_numeric(df[co_col], errors="coerce").dropna()
                if len(co) >= 10:
                    saturation = self._detect_saturation(co.values)
                    result["controller_output"] = saturation
                    result["controller_output_column"] = co_col

            # --- 4. Stiction / Oscillation detection ---
            oscillation = self._detect_oscillation(pv.values)
            result["oscillation_assessment"] = oscillation

            # --- 5. Overall engineering assessment ---
            result["engineering_assessment"] = self._overall_assessment(result)

            return result

        except Exception as e:
            logger.error(f"ControlLoopAssessment error: {e}")
            return {"status": "ERROR", "message": str(e)}

    def _compute_harris_index(self, pv: np.ndarray) -> Dict[str, Any]:
        """
        Harris Index: 基於自相關函數估計最小方差基準
        Harris Index = Var(minimum variance) / Var(actual)
        越接近 1 表示控制越好,越接近 0 表示有很大改善空間
        """
        n = len(pv)
        # Remove mean
        pv_centered = pv - pv.mean()

        # Compute autocorrelation
        autocorr = np.correlate(pv_centered, pv_centered, mode="full")
        autocorr = autocorr[n - 1 :] / autocorr[n - 1]  # Normalize

        # Minimum variance estimate (first autocorrelation coefficient)
        # Simplified: use variance of first-difference as minimum variance baseline
        min_var = np.var(np.diff(pv_centered))
        actual_var = np.var(pv_centered)

        harris_idx = min_var / (actual_var + 1e-10) if actual_var > 0 else 1.0
        harris_idx = min(1.0, harris_idx)  # Cap at 1

        # Interpret
        if harris_idx > 0.8:
            grade = "EXCELLENT"
            description = "控制迴路表現接近最優水準,幾乎無改善空間。"
        elif harris_idx > 0.5:
            grade = "GOOD"
            description = "控制迴路表現良好,但仍有適度改善空間。"
        elif harris_idx > 0.3:
            grade = "FAIR"
            description = "控制迴路表現一般,建議檢查 PID 參數調校。"
        else:
            grade = "POOR"
            description = (
                "控制迴路表現不佳,實際方差遠大於最小方差基準。"
                "建議: (1) 重新調校 PID 參數 (2) 檢查是否有持續性干擾 (3) 檢查傳感器延遲"
            )

        # Autocorrelation at key lags
        acf_lags = {}
        for lag in [1, 2, 3, 5, 10]:
            if lag < len(autocorr):
                acf_lags[f"lag_{lag}"] = round(float(autocorr[lag]), 4)

        return {
            "index": round(float(harris_idx), 4),
            "grade": grade,
            "description": description,
            "actual_variance": round(float(actual_var), 6),
            "minimum_variance": round(float(min_var), 6),
            "autocorrelation": acf_lags,
        }

    def _analyze_tracking_error(self, pv: np.ndarray, sp: np.ndarray) -> Dict[str, Any]:
        """分析追蹤誤差 (SP - PV)"""
        error = sp - pv

        # Basic stats
        mean_err = float(error.mean())
        std_err = float(error.std())
        max_err = float(np.abs(error).max())
        rms_err = float(np.sqrt(np.mean(error**2)))

        # Is there systematic bias?
        bias_significant = abs(mean_err) > 2 * std_err / np.sqrt(len(error))

        # Autocorrelation of error (should be low for well-tuned controller)
        if len(error) > 5:
            err_centered = error - error.mean()
            autocorr = np.correlate(err_centered, err_centered, mode="full")
            autocorr = autocorr[len(error) - 1 :] / (autocorr[len(error) - 1] + 1e-10)
            acf1 = float(autocorr[1]) if len(autocorr) > 1 else 0
        else:
            acf1 = 0

        interpretation = []
        if bias_significant:
            direction = "偏高" if mean_err > 0 else "偏低"
            interpretation.append(
                f"系統性偏差: PV 持續{direction} (平均誤差 {mean_err:+.4f})。"
                "可能原因: 控制器 Integral (I 項) 不足,或存在穩態偏差。"
            )

        if abs(acf1) > 0.5:
            interpretation.append(
                f"誤差自相關高 (ACF(1) = {acf1:.3f}): 控制器反應太慢,誤差持續存在。"
                "建議增加 P 增益或減少 I 時間常數。"
            )

        if not interpretation:
            interpretation.append("追蹤誤差表現正常,控制器能有效跟蹤設定值。")

        return {
            "mean_error": round(mean_err, 6),
            "std_error": round(std_err, 6),
            "max_absolute_error": round(max_err, 6),
            "rms_error": round(rms_err, 6),
            "bias_significant": bias_significant,
            "error_autocorrelation_lag1": round(acf1, 4),
            "interpretation": interpretation,
        }

    def _detect_saturation(self, co: np.ndarray) -> Dict[str, Any]:
        """偵測控制器輸出飽和"""
        co_min = float(co.min())
        co_max = float(co.max())
        co_range = co_max - co_min

        if co_range < 1e-10:
            return {
                "saturated": True,
                "saturation_ratio": 1.0,
                "description": "控制器輸出完全不變 -- 可能處於手動模式或飽和狀態。",
            }

        # Check if output spends significant time at limits
        upper_threshold = co_max - co_range * 0.02
        lower_threshold = co_min + co_range * 0.02

        at_upper = (co >= upper_threshold).sum() / len(co)
        at_lower = (co <= lower_threshold).sum() / len(co)
        saturation_ratio = float(at_upper + at_lower)

        description = []
        if at_upper > 0.1:
            description.append(f"輸出觸頂 (飽和上限): {at_upper:.1%} 的時間。")
        if at_lower > 0.1:
            description.append(f"輸出觸底 (飽和下限): {at_lower:.1%} 的時間。")
        if saturation_ratio > 0.3:
            description.append(
                "控制器大量時間處於飽和,可能存在 Integral Windup。建議加入 Anti-Windup 機制。"
            )

        if not description:
            description.append("控制器輸出在正常範圍內運作,無飽和問題。")

        return {
            "saturated": saturation_ratio > 0.2,
            "saturation_ratio": round(saturation_ratio, 4),
            "at_upper_limit": round(float(at_upper), 4),
            "at_lower_limit": round(float(at_lower), 4),
            "output_range": [round(co_min, 4), round(co_max, 4)],
            "description": description,
        }

    def _detect_oscillation(self, pv: np.ndarray) -> Dict[str, Any]:
        """偵測控制震盪 (使用過零率)"""
        pv_centered = pv - pv.mean()
        diff = np.diff(pv_centered)

        # Zero crossing rate of derivative
        sign_changes = np.sum(diff[:-1] * diff[1:] < 0)
        zcr = sign_changes / max(1, len(diff) - 1)

        # Expected ZCR for random noise ~= 0.5
        if zcr > 0.6:
            status = "HIGH_OSCILLATION"
            description = (
                f"高頻震盪 (方向變換率 {zcr:.1%}): "
                "控制迴路可能存在過度調校 (Over-tuning)。"
                "建議: 降低 PID 的 P (比例) 或 D (微分) 增益。"
            )
        elif zcr > 0.4:
            status = "MODERATE"
            description = "方向變換率正常,控制迴路穩定。"
        else:
            status = "SLUGGISH"
            description = (
                f"低頻震盪或緩慢響應 (方向變換率 {zcr:.1%}): "
                "控制迴路可能反應過慢 (Under-tuning)。"
                "建議: 增加 PID 的 P (比例) 增益。"
            )

        return {
            "zero_crossing_rate": round(float(zcr), 4),
            "status": status,
            "description": description,
        }

    def _overall_assessment(self, result: Dict) -> str:
        """綜合評估"""
        issues = []

        harris = result.get("harris_index", {})
        if harris.get("grade") in ("FAIR", "POOR"):
            issues.append(
                f"Harris Index 評級: {harris['grade']} ({harris.get('index', 0):.2f})"
            )

        tracking = result.get("tracking_error", {})
        if tracking.get("bias_significant"):
            issues.append(f"追蹤偏差: {tracking.get('mean_error', 0):+.4f}")

        co = result.get("controller_output", {})
        if co.get("saturated"):
            issues.append(f"控制器飽和: {co.get('saturation_ratio', 0):.1%} 時間")

        osc = result.get("oscillation_assessment", {})
        if osc.get("status") == "HIGH_OSCILLATION":
            issues.append("高頻震盪")

        if not issues:
            return "控制迴路整體表現良好,無明顯問題。"

        return (
            "控制迴路存在以下問題: "
            + "; ".join(issues)
            + "。建議進行 PID 參數重新調校。"
        )
