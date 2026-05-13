"""
趨勢預測工具 (Trend Prediction / Drift Forecasting)
- 對參數進行線性/指數趨勢擬合
- 預估漂移何時超出管制線 (UCL/LCL)
- 輸出趨勢方向、擬合品質、預估超限時間點
"""

import numpy as np
import pandas as pd
import logging
from typing import Any, Dict, List, Optional
from .base import AnalysisTool

logger = logging.getLogger(__name__)


class TrendPredictionTool(AnalysisTool):
    """趨勢預測: 擬合時序趨勢並預估何時超出管制線"""

    @property
    def name(self) -> str:
        return "trend_prediction"

    @property
    def description(self) -> str:
        return (
            "趨勢預測: 線性/指數趨勢擬合 + 管制線超限預估。"
            "預測參數漂移何時超出 UCL/LCL。"
        )

    @property
    def required_params(self) -> List[str]:
        return ["file_id", "target"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        """
        必要參數:
            target: str — 目標參數名稱
        可選參數:
            ucl: float — 管制上限 (預設: mean + 3*std)
            lcl: float — 管制下限 (預設: mean - 3*std)
            forecast_horizon: int — 預測延伸的筆數 (預設: 資料長度的 30%)
            method: str — "auto" | "linear" | "exponential" (預設: auto)
        """
        try:
            file_id = params.get("file_id")
            target = params.get("target")

            # Load data
            summary = self.analysis_service.load_summary(session_id, file_id)
            if not summary:
                return {"status": "ERROR", "message": "No summary data available"}
            filename = summary["filename"]
            csv_path = (
                self.analysis_service.get_csv_path(session_id, filename)
            )
            df = pd.read_csv(csv_path)

            if target not in df.columns:
                return {"status": "ERROR", "message": f"目標欄位 '{target}' 不存在"}

            series = df[target].dropna().values.astype(float)
            n = len(series)

            if n < 10:
                return {
                    "status": "WARNING",
                    "message": f"資料量不足 ({n} 筆), 需至少 10 筆進行趨勢預測",
                }

            x = np.arange(n, dtype=float)

            # 管制線: 使用者指定或自動計算 mean +/- 3*sigma
            mean_val = float(np.mean(series))
            std_val = float(np.std(series, ddof=1)) if n > 1 else 1.0
            ucl = float(params.get("ucl", mean_val + 3 * std_val))
            lcl = float(params.get("lcl", mean_val - 3 * std_val))
            forecast_horizon = int(
                params.get("forecast_horizon", max(10, int(n * 0.3)))
            )
            method = params.get("method", "auto")

            # ===== 趨勢擬合 =====
            results = {}

            # --- 線性擬合 ---
            lin_fit = self._fit_linear(x, series)
            results["linear"] = lin_fit

            # --- 指數擬合 (僅當資料全正時) ---
            if np.all(series > 0):
                exp_fit = self._fit_exponential(x, series)
                results["exponential"] = exp_fit
            else:
                results["exponential"] = None

            # --- 選擇最佳模型 ---
            if method == "auto":
                best_model = "linear"
                best_r2 = lin_fit["r_squared"]
                if (
                    results["exponential"]
                    and results["exponential"]["r_squared"] > best_r2
                ):
                    best_model = "exponential"
            else:
                best_model = (
                    method if method in results and results[method] else "linear"
                )

            best_fit = results[best_model]

            # ===== 預測超限時間 =====
            breach_info = self._predict_breach(
                best_model, best_fit, n, ucl, lcl, forecast_horizon
            )

            # ===== 趨勢方向判斷 =====
            slope = best_fit.get("slope", 0)
            if abs(slope) < std_val * 0.01:
                trend_direction = "穩定 (無顯著趨勢)"
            elif slope > 0:
                trend_direction = "上升趨勢"
            else:
                trend_direction = "下降趨勢"

            # ===== 趨勢強度 (每 10 筆的變化量佔 std 的比例) =====
            drift_per_10 = abs(slope) * 10
            drift_ratio = drift_per_10 / std_val if std_val > 0 else 0
            if drift_ratio > 1.0:
                drift_severity = "強烈漂移"
            elif drift_ratio > 0.3:
                drift_severity = "中度漂移"
            elif drift_ratio > 0.1:
                drift_severity = "輕微漂移"
            else:
                drift_severity = "無漂移"

            # ===== 最近 vs 最早的分段比較 =====
            segment_size = max(5, n // 5)
            early_mean = float(np.mean(series[:segment_size]))
            late_mean = float(np.mean(series[-segment_size:]))
            shift = late_mean - early_mean

            # ===== Build Chart for mini chart rendering =====
            chart_json = self._build_chart(
                target, series, x, best_model, best_fit, ucl, lcl, forecast_horizon
            )

            return {
                "status": "OK",
                "target": target,
                "data_points": n,
                "trend_direction": trend_direction,
                "drift_severity": drift_severity,
                "best_model": best_model,
                "r_squared": round(best_fit["r_squared"], 4),
                "slope": round(slope, 6),
                "drift_per_10_points": round(drift_per_10, 4),
                "drift_ratio_vs_std": round(drift_ratio, 4),
                "statistics": {
                    "mean": round(mean_val, 4),
                    "std": round(std_val, 4),
                    "ucl": round(ucl, 4),
                    "lcl": round(lcl, 4),
                    "early_segment_mean": round(early_mean, 4),
                    "late_segment_mean": round(late_mean, 4),
                    "shift": round(shift, 4),
                },
                "breach_prediction": breach_info,
                "forecast_horizon_points": forecast_horizon,
                "chart": chart_json,
                "interpretation": self._build_interpretation(
                    target,
                    trend_direction,
                    drift_severity,
                    breach_info,
                    shift,
                    std_val,
                    best_model,
                    best_fit["r_squared"],
                ),
            }

        except Exception as e:
            logger.error(f"TrendPrediction error: {e}")
            return {"status": "ERROR", "message": str(e)}

    def _fit_linear(self, x: np.ndarray, y: np.ndarray) -> Dict[str, Any]:
        """線性回歸: y = a*x + b"""
        try:
            coeffs = np.polyfit(x, y, 1)
            slope, intercept = coeffs[0], coeffs[1]
            y_pred = np.polyval(coeffs, x)
            ss_res = np.sum((y - y_pred) ** 2)
            ss_tot = np.sum((y - np.mean(y)) ** 2)
            r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
            return {
                "slope": float(slope),
                "intercept": float(intercept),
                "r_squared": float(max(0, r2)),
            }
        except Exception as e:
            logger.warning(f"Linear fit failed: {e}")
            return {"slope": 0, "intercept": float(np.mean(y)), "r_squared": 0}

    def _fit_exponential(
        self, x: np.ndarray, y: np.ndarray
    ) -> Optional[Dict[str, Any]]:
        """指數擬合: y = a * exp(b * x)"""
        try:
            log_y = np.log(y)
            coeffs = np.polyfit(x, log_y, 1)
            b, log_a = coeffs[0], coeffs[1]
            a = np.exp(log_a)
            y_pred = a * np.exp(b * x)
            ss_res = np.sum((y - y_pred) ** 2)
            ss_tot = np.sum((y - np.mean(y)) ** 2)
            r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
            return {
                "slope": float(b),
                "a": float(a),
                "b": float(b),
                "r_squared": float(max(0, r2)),
            }
        except Exception:
            return None

    def _predict_breach(
        self, model: str, fit: Dict, n: int, ucl: float, lcl: float, horizon: int
    ) -> Dict[str, Any]:
        """預測何時超出管制線"""
        future_x = np.arange(n, n + horizon, dtype=float)

        if model == "linear":
            slope = fit["slope"]
            intercept = fit["intercept"]
            future_y = slope * future_x + intercept
        elif model == "exponential" and fit.get("a") is not None:
            future_y = fit["a"] * np.exp(fit["b"] * future_x)
        else:
            return {"will_breach": False, "message": "模型不支援預測"}

        ucl_breach_idx = np.where(future_y > ucl)[0]
        lcl_breach_idx = np.where(future_y < lcl)[0]

        breach_info = {
            "will_breach": False,
            "ucl_breach_at": None,
            "lcl_breach_at": None,
            "message": "",
        }

        if len(ucl_breach_idx) > 0:
            bp = int(ucl_breach_idx[0])
            breach_info["will_breach"] = True
            breach_info["ucl_breach_at"] = {
                "points_from_now": bp,
                "at_index": n + bp,
                "predicted_value": round(float(future_y[bp]), 4),
            }

        if len(lcl_breach_idx) > 0:
            bp = int(lcl_breach_idx[0])
            breach_info["will_breach"] = True
            breach_info["lcl_breach_at"] = {
                "points_from_now": bp,
                "at_index": n + bp,
                "predicted_value": round(float(future_y[bp]), 4),
            }

        if breach_info["will_breach"]:
            earliest = None
            limit_type = ""
            if breach_info["ucl_breach_at"]:
                earliest = breach_info["ucl_breach_at"]["points_from_now"]
                limit_type = "UCL (上限)"
            if breach_info["lcl_breach_at"]:
                lcl_pts = breach_info["lcl_breach_at"]["points_from_now"]
                if earliest is None or lcl_pts < earliest:
                    earliest = lcl_pts
                    limit_type = "LCL (下限)"
            breach_info["message"] = (
                f"預測在約 {earliest} 筆後將超出 {limit_type}。建議密切監控並提前介入。"
            )
        else:
            breach_info["message"] = (
                f"在未來 {horizon} 筆的預測範圍內，預計不會超出管制線。"
            )

        return breach_info

    def _build_interpretation(
        self, target, direction, severity, breach, shift, std, model, r2
    ) -> str:
        """生成人類可讀的解讀"""
        lines = [f"參數 {target} 呈現 {direction} ({severity})。"]
        lines.append(f"趨勢模型: {model} (R²={r2:.3f})。")

        if abs(shift) > std * 0.5:
            lines.append(
                f"前段與後段均值偏移 {shift:+.4f} "
                f"(約 {abs(shift) / std:.1f} 個標準差)。"
            )

        if breach.get("will_breach"):
            lines.append(breach["message"])
        else:
            lines.append("在預測範圍內無超限風險。")

        return " ".join(lines)

    def _build_chart(
        self,
        target: str,
        series: np.ndarray,
        x: np.ndarray,
        model: str,
        fit: Dict,
        ucl: float,
        lcl: float,
        forecast_horizon: int,
    ) -> Dict[str, Any]:
        """Build Chart.js-compatible chart config for mini chart rendering"""
        n = len(series)

        # Downsample to max 60 points for mini chart readability
        max_pts = 60
        if n > max_pts:
            step = n // max_pts
            idx = list(range(0, n, step))[:max_pts]
        else:
            idx = list(range(n))

        labels = [str(i) for i in idx]
        data_pts = [round(float(series[i]), 4) for i in idx]

        # Trend line
        if model == "linear":
            trend_pts = [
                round(float(fit["slope"] * i + fit["intercept"]), 4) for i in idx
            ]
        elif model == "exponential" and fit.get("a") is not None:
            trend_pts = [round(float(fit["a"] * np.exp(fit["b"] * i)), 4) for i in idx]
        else:
            trend_pts = data_pts

        # Forecast extension (last 10 points of forecast)
        fc_count = min(10, forecast_horizon)
        fc_x = list(range(n, n + fc_count))
        fc_labels = [str(i) for i in fc_x]
        if model == "linear":
            fc_pts = [
                round(float(fit["slope"] * i + fit["intercept"]), 4) for i in fc_x
            ]
        elif model == "exponential" and fit.get("a") is not None:
            fc_pts = [round(float(fit["a"] * np.exp(fit["b"] * i)), 4) for i in fc_x]
        else:
            fc_pts = []

        # Combine labels
        all_labels = labels + fc_labels
        # Extend data with None for forecast region
        data_extended = data_pts + [None] * len(fc_labels)
        trend_extended = trend_pts + fc_pts
        ucl_line = [round(ucl, 4)] * len(all_labels)
        lcl_line = [round(lcl, 4)] * len(all_labels)

        datasets = [
            {
                "label": f"{target} 實際值",
                "data": data_extended,
                "borderColor": "rgba(59, 130, 246, 1)",
                "backgroundColor": "rgba(59, 130, 246, 0.1)",
                "borderWidth": 1.5,
                "pointRadius": 0,
                "fill": False,
            },
            {
                "label": f"趨勢 ({model})",
                "data": trend_extended,
                "borderColor": "rgba(239, 68, 68, 0.8)",
                "backgroundColor": "transparent",
                "borderWidth": 2,
                "borderDash": [4, 2],
                "pointRadius": 0,
                "fill": False,
            },
            {
                "label": "UCL",
                "data": ucl_line,
                "borderColor": "rgba(234, 179, 8, 0.6)",
                "backgroundColor": "transparent",
                "borderWidth": 1,
                "borderDash": [6, 3],
                "pointRadius": 0,
                "fill": False,
            },
            {
                "label": "LCL",
                "data": lcl_line,
                "borderColor": "rgba(234, 179, 8, 0.6)",
                "backgroundColor": "transparent",
                "borderWidth": 1,
                "borderDash": [6, 3],
                "pointRadius": 0,
                "fill": False,
            },
        ]

        return {
            "type": "chart",
            "chart_type": "line",
            "title": f"{target} 趨勢預測",
            "labels": all_labels,
            "datasets": datasets,
            "options": {
                "scales": {
                    "x": {"display": True, "grid": {"display": False}},
                    "y": {"beginAtZero": False},
                },
            },
        }
