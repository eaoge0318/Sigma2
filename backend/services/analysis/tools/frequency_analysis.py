"""
PSD 頻域分析 (Power Spectral Density / Frequency Analysis)

分析時間序列的頻域特徵:
- 高頻噪聲消失 = 傳感器凍結
- 特定頻率峰值 = 週期性干擾
- 低頻/高頻能量比 = 信號品質指標
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List
from .base import AnalysisTool
import logging

logger = logging.getLogger(__name__)


class FrequencyAnalysisTool(AnalysisTool):
    """PSD 頻域分析 -- 偵測週期性干擾、傳感器凍結"""

    @property
    def name(self) -> str:
        return "frequency_analysis"

    @property
    def description(self) -> str:
        return "使用 PSD 頻域分析偵測週期性干擾與傳感器凍結"

    @property
    def required_params(self) -> List[str]:
        return ["parameter"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        try:
            from scipy import signal as sig

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
            if len(series) < 20:
                return {
                    "status": "ERROR",
                    "message": "Insufficient data (need >= 20 points)",
                }

            # Parse ranges
            focus_range = params.get("focus_range")
            baseline_range = params.get("baseline_range")

            # --- Compute PSD for full series ---
            full_psd = self._compute_psd(series.values, sig)

            # --- Compare focus vs baseline if ranges provided ---
            comparison = None
            if focus_range:
                focus_idx = self.parse_indices(focus_range, max_len=len(series))
                if focus_idx and len(focus_idx) >= 10:
                    focus_series = series.iloc[focus_idx]
                    focus_psd = self._compute_psd(focus_series.values, sig)

                    if baseline_range:
                        base_idx = self.parse_indices(
                            baseline_range, max_len=len(series)
                        )
                    else:
                        # Use everything NOT in focus as baseline
                        all_idx = set(range(len(series)))
                        base_idx = sorted(all_idx - set(focus_idx))

                    if base_idx and len(base_idx) >= 10:
                        base_series = series.iloc[base_idx]
                        base_psd = self._compute_psd(base_series.values, sig)

                        comparison = self._compare_psd(focus_psd, base_psd)

            # --- Anomaly detection based on spectral features ---
            spectral_anomalies = self._detect_spectral_anomalies(full_psd)

            # --- 計算主頻週期對應的 row 位置 (用於趨勢圖標記) ---
            dominant_period_rows = []
            if full_psd["dominant_period"] not in (float("inf"), 0):
                period = full_psd["dominant_period"]
                # 標記每個週期的起點
                idx = 0.0
                while idx < len(series):
                    dominant_period_rows.append(int(round(idx)))
                    idx += period

            return {
                "status": "SUCCESS",
                "parameter": parameter,
                "full_spectrum": {
                    "dominant_frequency": full_psd["dominant_freq"],
                    "dominant_period": full_psd["dominant_period"],
                    "total_power": round(float(full_psd["total_power"]), 6),
                    "low_freq_ratio": round(float(full_psd["low_freq_ratio"]), 4),
                    "high_freq_ratio": round(float(full_psd["high_freq_ratio"]), 4),
                    "spectral_entropy": round(float(full_psd["spectral_entropy"]), 4),
                    "psd_values": [round(float(v), 8) for v in full_psd["psd"]],
                    "frequencies": [round(float(v), 6) for v in full_psd["freqs"]],
                },
                "raw_values": series.values.tolist(),
                "dominant_period_rows": dominant_period_rows,
                "comparison": comparison,
                "spectral_anomalies": spectral_anomalies,
                "data_points": len(series),
            }

        except ImportError:
            return {
                "status": "ERROR",
                "message": "scipy not available for frequency analysis",
            }
        except Exception as e:
            logger.error(f"FrequencyAnalysis error: {e}")
            return {"status": "ERROR", "message": str(e)}

    def _compute_psd(self, data: np.ndarray, sig) -> Dict[str, Any]:
        """計算 PSD 及衍生指標"""
        n = len(data)
        nperseg = min(n, max(16, n // 4))

        freqs, psd = sig.welch(data, fs=1.0, nperseg=nperseg, noverlap=nperseg // 2)

        # Total power
        total_power = np.trapz(psd, freqs)

        # Frequency band analysis
        nyquist = 0.5
        low_cutoff = nyquist * 0.1  # Bottom 10% of spectrum
        high_cutoff = nyquist * 0.5  # Top 50% of spectrum

        low_mask = freqs <= low_cutoff
        high_mask = freqs >= high_cutoff

        low_power = (
            np.trapz(psd[low_mask], freqs[low_mask]) if low_mask.sum() > 1 else 0
        )
        high_power = (
            np.trapz(psd[high_mask], freqs[high_mask]) if high_mask.sum() > 1 else 0
        )

        low_freq_ratio = low_power / (total_power + 1e-10)
        high_freq_ratio = high_power / (total_power + 1e-10)

        # Dominant frequency (excluding DC component at freq=0)
        non_dc = freqs > 0
        if non_dc.sum() > 0:
            peak_idx = np.argmax(psd[non_dc])
            dominant_freq = float(freqs[non_dc][peak_idx])
            dominant_period = (
                round(1.0 / dominant_freq, 1) if dominant_freq > 0 else float("inf")
            )
        else:
            dominant_freq = 0.0
            dominant_period = float("inf")

        # Spectral entropy (uniformity of power distribution)
        psd_norm = psd / (psd.sum() + 1e-10)
        psd_norm = psd_norm[psd_norm > 0]
        spectral_entropy = -np.sum(psd_norm * np.log2(psd_norm + 1e-10))
        max_entropy = np.log2(len(psd_norm)) if len(psd_norm) > 0 else 1
        normalized_entropy = spectral_entropy / (max_entropy + 1e-10)

        return {
            "freqs": freqs,
            "psd": psd,
            "total_power": total_power,
            "low_freq_ratio": low_freq_ratio,
            "high_freq_ratio": high_freq_ratio,
            "dominant_freq": round(dominant_freq, 4),
            "dominant_period": dominant_period,
            "spectral_entropy": normalized_entropy,
        }

    def _compare_psd(self, focus: Dict, baseline: Dict) -> Dict[str, Any]:
        """比較兩個區間的 PSD 差異"""
        power_change = (focus["total_power"] - baseline["total_power"]) / (
            baseline["total_power"] + 1e-10
        )
        hf_change = focus["high_freq_ratio"] - baseline["high_freq_ratio"]
        entropy_change = focus["spectral_entropy"] - baseline["spectral_entropy"]

        interpretation = []

        if focus["total_power"] < baseline["total_power"] * 0.1:
            interpretation.append(
                "FREEZE 特徵: Focus 區間的總功率僅為 Baseline 的 "
                f"{focus['total_power'] / (baseline['total_power'] + 1e-10):.1%}。"
                "高頻噪聲幾乎消失,強烈暗示傳感器數據未更新。"
            )
        elif abs(hf_change) > 0.2:
            direction = "增加" if hf_change > 0 else "減少"
            interpretation.append(
                f"高頻能量{direction}: 可能暗示{'震盪加劇' if hf_change > 0 else '系統趨於穩定或數據更新頻率降低'}。"
            )

        if abs(entropy_change) > 0.15:
            direction = "上升" if entropy_change > 0 else "下降"
            interpretation.append(
                f"頻譜熵{direction}: 能量分佈{'更均勻 (接近白噪聲)' if entropy_change > 0 else '更集中 (特定頻率主導)'}。"
            )

        return {
            "power_change_ratio": round(float(power_change), 4),
            "high_freq_change": round(float(hf_change), 4),
            "entropy_change": round(float(entropy_change), 4),
            "interpretation": interpretation
            if interpretation
            else ["Focus 與 Baseline 的頻譜特徵相似,無顯著差異。"],
        }

    def _detect_spectral_anomalies(self, psd_result: Dict) -> List[str]:
        """檢測頻譜異常"""
        anomalies = []

        if psd_result["total_power"] < 1e-8:
            anomalies.append(
                "極低總功率: 信號幾乎無變異,可能是傳感器凍結或系統處於完全靜止狀態。"
            )

        if psd_result["spectral_entropy"] < 0.3:
            anomalies.append(
                f"低頻譜熵 ({psd_result['spectral_entropy']:.2f}): "
                "能量高度集中在少數頻率,可能存在週期性干擾源。"
                f"主導週期: 每 {psd_result['dominant_period']} 個取樣點。"
            )

        if psd_result["high_freq_ratio"] > 0.6:
            anomalies.append(
                "高頻主導: 可能存在高頻震盪或量測噪聲過大。建議檢查傳感器品質或濾波器設定。"
            )

        if not anomalies:
            anomalies.append("頻譜分佈正常,無明顯異常。")

        return anomalies
