"""
小波/時頻分析工具 (Wavelet / Time-Frequency Analysis)
- WaveletAnalysisTool: CWT 連續小波變換,產出時頻圖譜與動態頻率特徵

相比 frequency_analysis.py (PSD):
  PSD 只告訴你「整段信號有哪些頻率」
  Wavelet 告訴你「哪些頻率在什麼時間出現/消失」
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List
from .base import AnalysisTool
import logging

logger = logging.getLogger(__name__)


class WaveletAnalysisTool(AnalysisTool):
    """
    連續小波變換 (CWT) 時頻分析:
    - 偵測瞬態頻率變化 (如機台共振啟動/停止)
    - 識別非穩態行為 (表示機台狀態切換)
    - 量化低頻/高頻能量隨時間的變化
    """

    @property
    def name(self) -> str:
        return "wavelet_analysis"

    @property
    def description(self) -> str:
        return (
            "連續小波變換 (CWT) 時頻分析: 產出時頻圖譜資料,"
            "偵測頻率隨時間的變化 (瞬態干擾/狀態切換)。"
        )

    @property
    def required_params(self) -> List[str]:
        return ["file_id", "parameter"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        try:
            file_id = params.get("file_id")
            parameter = params.get("parameter")
            n_scales = int(params.get("n_scales", 32))
            # Sampling rate (samples per second), default 1 Hz
            fs = float(params.get("sampling_rate", 1.0))

            # Load data
            summary = self.analysis_service.load_summary(session_id, file_id)
            if not summary:
                return {"status": "ERROR", "message": "No summary data available"}
            filename = summary["filename"]
            csv_path = (
                self.analysis_service.get_csv_path(session_id, filename)
            )
            df = pd.read_csv(csv_path)

            if parameter not in df.columns:
                return {
                    "status": "ERROR",
                    "message": f"Parameter '{parameter}' not found",
                }

            series = df[parameter].dropna().values.astype(float)
            if len(series) < 30:
                return {
                    "status": "ERROR",
                    "message": f"Insufficient data ({len(series)} points). Need at least 30.",
                }

            # Limit to 2000 points for performance
            max_len = 2000
            if len(series) > max_len:
                step = len(series) // max_len
                series = series[::step][:max_len]

            # Normalize signal (zero mean, unit variance)
            mean_val = float(np.mean(series))
            std_val = float(np.std(series))
            if std_val < 1e-10:
                return {
                    "status": "OK",
                    "parameter": parameter,
                    "message": "Signal has near-zero variance (likely frozen/constant)",
                    "is_frozen": True,
                    "interpretation": f"{parameter} 信號幾乎不變 (標準差 ≈ 0),可能為感測器凍結或常數",
                }

            normalized = (series - mean_val) / std_val

            # Continuous Wavelet Transform using Morlet wavelet
            # Scales correspond to different frequency bands
            min_scale = 2
            max_scale = min(len(normalized) // 2, 128)
            scales = np.geomspace(min_scale, max_scale, num=n_scales)

            # Manual Morlet CWT (replaces deprecated scipy.signal.cwt)
            n = len(normalized)
            cwt_matrix = np.zeros((len(scales), n), dtype=complex)
            sig_fft = np.fft.fft(normalized, n=2 * n)  # zero-padded FFT
            angular_freqs = 2 * np.pi * np.fft.fftfreq(2 * n)
            w0 = 5.0  # Morlet central frequency
            for i, scale in enumerate(scales):
                # Morlet wavelet in frequency domain
                norm = (np.pi**-0.25) * np.sqrt(2 * np.pi * scale)
                wavelet_fft = norm * np.exp(-0.5 * (scale * angular_freqs - w0) ** 2)
                conv = np.fft.ifft(sig_fft * wavelet_fft)
                cwt_matrix[i] = conv[:n]
            power = np.abs(cwt_matrix) ** 2

            # Convert scales to approximate frequencies
            freqs = (5.0 * fs) / (2 * np.pi * scales)  # Morlet wavelet center frequency

            # Time axis
            time_axis = np.arange(len(normalized)) / fs

            # Energy distribution over time
            # Split into temporal segments for summary
            n_segments = min(10, len(normalized) // 10)
            segment_len = len(normalized) // n_segments

            temporal_energy = []
            for seg_idx in range(n_segments):
                start = seg_idx * segment_len
                end = min((seg_idx + 1) * segment_len, power.shape[1])
                seg_power = power[:, start:end]

                # Split into low-freq and high-freq bands
                mid_idx = len(scales) // 2
                low_freq_energy = float(np.mean(seg_power[:mid_idx, :]))
                high_freq_energy = float(np.mean(seg_power[mid_idx:, :]))
                total_energy = low_freq_energy + high_freq_energy + 1e-10

                temporal_energy.append(
                    {
                        "segment": seg_idx + 1,
                        "time_start": round(float(time_axis[start]), 2),
                        "time_end": round(
                            float(time_axis[min(end - 1, len(time_axis) - 1)]), 2
                        ),
                        "low_freq_energy": round(low_freq_energy, 4),
                        "high_freq_energy": round(high_freq_energy, 4),
                        "lf_hf_ratio": round(
                            low_freq_energy / (high_freq_energy + 1e-10), 4
                        ),
                        "total_power": round(float(total_energy), 4),
                    }
                )

            # Detect non-stationarity: variance of energy across segments
            total_powers = [s["total_power"] for s in temporal_energy]
            energy_cv = float(np.std(total_powers) / (np.mean(total_powers) + 1e-10))
            is_non_stationary = energy_cv > 0.3

            # Find dominant frequency bands
            mean_power_by_scale = np.mean(power, axis=1)
            top_freq_indices = np.argsort(mean_power_by_scale)[-3:][::-1]
            dominant_frequencies = [
                {
                    "frequency": round(float(freqs[idx]), 4),
                    "period": round(float(1.0 / (freqs[idx] + 1e-10)), 2),
                    "relative_power": round(
                        float(
                            mean_power_by_scale[idx]
                            / (np.sum(mean_power_by_scale) + 1e-10)
                            * 100
                        ),
                        2,
                    ),
                }
                for idx in top_freq_indices
            ]

            # Detect transient events: find time points where energy spikes
            total_power_over_time = np.sum(power, axis=0)
            power_threshold = np.mean(total_power_over_time) + 2 * np.std(
                total_power_over_time
            )
            transient_indices = np.where(total_power_over_time > power_threshold)[0]

            transient_events = []
            if len(transient_indices) > 0:
                # Group consecutive indices into events
                events = np.split(
                    transient_indices, np.where(np.diff(transient_indices) > 3)[0] + 1
                )
                for event in events[:10]:  # Max 10 events
                    if len(event) > 0:
                        transient_events.append(
                            {
                                "time_start": round(float(time_axis[event[0]]), 2),
                                "time_end": round(float(time_axis[event[-1]]), 2),
                                "duration": round(
                                    float((event[-1] - event[0]) / fs), 2
                                ),
                                "peak_power": round(
                                    float(np.max(total_power_over_time[event])), 4
                                ),
                            }
                        )

            # Scalogram data (downsampled for frontend)
            # Downsample both time and frequency axes
            max_time_points = 100
            max_freq_points = min(n_scales, 20)
            time_step = max(1, power.shape[1] // max_time_points)
            freq_step = max(1, power.shape[0] // max_freq_points)
            scalogram = power[::freq_step, ::time_step].tolist()
            scalogram_freqs = freqs[::freq_step].tolist()
            scalogram_times = time_axis[::time_step].tolist()

            interpretation = self._interpret(
                parameter,
                is_non_stationary,
                energy_cv,
                dominant_frequencies,
                transient_events,
                temporal_energy,
            )

            return {
                "status": "OK",
                "parameter": parameter,
                "n_samples": len(series),
                "sampling_rate": fs,
                "is_frozen": False,
                "is_non_stationary": is_non_stationary,
                "energy_cv": round(energy_cv, 4),
                "dominant_frequencies": dominant_frequencies,
                "transient_events": transient_events,
                "temporal_energy": temporal_energy,
                "scalogram": {
                    "power": [[round(v, 4) for v in row] for row in scalogram],
                    "frequencies": [round(f, 4) for f in scalogram_freqs],
                    "times": [round(t, 2) for t in scalogram_times],
                },
                "interpretation": interpretation,
            }

        except ImportError as ie:
            logger.error(f"WaveletAnalysis import error: {ie}")
            return {"status": "ERROR", "message": f"Missing dependency: {ie}"}
        except Exception as e:
            logger.error(f"WaveletAnalysis error: {e}")
            return {"status": "ERROR", "message": str(e)}

    def _interpret(
        self,
        param,
        is_non_stat,
        energy_cv,
        dom_freqs,
        transients,
        temporal_energy,
    ) -> str:
        lines = []

        # Stationarity assessment
        if is_non_stat:
            lines.append(
                f"{param} 呈現非穩態行為 (能量變異係數={energy_cv:.3f} > 0.3), "
                f"表示頻率特徵隨時間顯著變化,可能存在狀態切換"
            )
        else:
            lines.append(
                f"{param} 頻率特徵穩定 (能量變異係數={energy_cv:.3f}), "
                f"信號行為在分析區間內一致"
            )

        # Dominant frequencies
        if dom_freqs:
            top = dom_freqs[0]
            lines.append(
                f"主導頻率: {top['frequency']:.4f} Hz (週期≈{top['period']:.1f}s), "
                f"佔總功率 {top['relative_power']:.1f}%"
            )

        # Transient events
        if transients:
            lines.append(f"偵測到 {len(transients)} 個瞬態能量異常事件")
            first = transients[0]
            lines.append(
                f"首個事件: 時間={first['time_start']}-{first['time_end']}s, "
                f"持續{first['duration']}s"
            )

        # Energy trend
        if len(temporal_energy) >= 3:
            first_power = temporal_energy[0]["total_power"]
            last_power = temporal_energy[-1]["total_power"]
            change = (last_power - first_power) / (first_power + 1e-10) * 100
            if abs(change) > 30:
                direction = "增加" if change > 0 else "降低"
                lines.append(
                    f"整體頻率能量呈{direction}趨勢 ({change:+.1f}%), "
                    f"可能反映機台狀態逐步改變"
                )

        return "; ".join(lines)
