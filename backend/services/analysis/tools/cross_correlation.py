"""
交叉相關 Lag 分析 (Cross-Correlation Lag Analysis)

計算兩個時間序列之間的交叉相關，找出最佳延遲 (Lag)。
- Lag > 0: target 領先 reference (target 先變化)
- Lag < 0: reference 領先 target (reference 先變化)
- Lag = 0: 同步或因果倒置 (需進一步判斷)
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List
from .base import AnalysisTool
import logging

logger = logging.getLogger(__name__)


class CrossCorrelationLagTool(AnalysisTool):
    """交叉相關 Lag 分析 -- 找出兩個時間序列的領先/落後關係"""

    @property
    def name(self) -> str:
        return "cross_correlation_lag"

    @property
    def description(self) -> str:
        return "計算交叉相關找出兩變數的前導-滯後關係 (Lead-Lag)"

    @property
    def required_params(self) -> List[str]:
        return ["target"]

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

            target = params.get("target", "")
            reference = params.get("reference", "")
            max_lag = int(params.get("max_lag", 20))

            if target not in df.columns:
                return {"status": "ERROR", "message": f"Column '{target}' not found"}

            # Auto-detect reference if not provided
            if not reference:
                numeric_df = df.select_dtypes(include=[np.number])
                if target in numeric_df.columns:
                    corr = numeric_df.corr()[target].drop(target, errors="ignore").abs()
                    reference = corr.idxmax() if not corr.empty else ""
                if not reference:
                    return {
                        "status": "ERROR",
                        "message": "Cannot auto-detect reference parameter",
                    }

            if reference not in df.columns:
                return {"status": "ERROR", "message": f"Column '{reference}' not found"}

            # Prepare data
            ts_target = pd.to_numeric(df[target], errors="coerce").dropna()
            ts_ref = pd.to_numeric(df[reference], errors="coerce").dropna()

            # Align indices
            common_idx = ts_target.index.intersection(ts_ref.index)
            if len(common_idx) < max_lag * 2:
                return {
                    "status": "ERROR",
                    "message": f"Insufficient overlapping data ({len(common_idx)} points)",
                }

            ts_target = ts_target.loc[common_idx].values
            ts_ref = ts_ref.loc[common_idx].values

            # Standardize
            ts_target = (ts_target - ts_target.mean()) / (ts_target.std() + 1e-10)
            ts_ref = (ts_ref - ts_ref.mean()) / (ts_ref.std() + 1e-10)

            # --- Cross-correlation using shift ---
            n = len(ts_target)
            lags = range(-max_lag, max_lag + 1)
            correlations = {}

            for lag in lags:
                if lag > 0:
                    corr = np.corrcoef(ts_target[lag:], ts_ref[: n - lag])[0, 1]
                elif lag < 0:
                    corr = np.corrcoef(ts_target[: n + lag], ts_ref[-lag:])[0, 1]
                else:
                    corr = np.corrcoef(ts_target, ts_ref)[0, 1]

                if not np.isnan(corr):
                    correlations[lag] = round(float(corr), 4)

            if not correlations:
                return {"status": "ERROR", "message": "Could not compute correlations"}

            # Find peak
            best_lag = max(correlations, key=lambda k: abs(correlations[k]))
            peak_corr = correlations[best_lag]

            # Find secondary peaks (different sign or different direction)
            sorted_lags = sorted(
                correlations.items(), key=lambda x: abs(x[1]), reverse=True
            )
            secondary_peaks = []
            for lag_val, corr_val in sorted_lags[1:4]:
                if abs(corr_val) > 0.3:
                    secondary_peaks.append({"lag": lag_val, "correlation": corr_val})

            # --- Engineering interpretation ---
            interpretation = self._interpret_lag(best_lag, peak_corr, target, reference)

            # --- Lag profile (for visualization) ---
            lag_profile = [
                {"lag": lag, "correlation": correlations.get(lag, 0)}
                for lag in range(-max_lag, max_lag + 1)
                if lag in correlations
            ]

            return {
                "status": "SUCCESS",
                "target": target,
                "reference": reference,
                "best_lag": best_lag,
                "peak_correlation": peak_corr,
                "secondary_peaks": secondary_peaks,
                "interpretation": interpretation,
                "lag_profile": lag_profile,
                "data_points": n,
                "max_lag_searched": max_lag,
            }

        except Exception as e:
            logger.error(f"CrossCorrelationLag error: {e}")
            return {"status": "ERROR", "message": str(e)}

    def _interpret_lag(
        self, lag: int, corr: float, target: str, reference: str
    ) -> Dict[str, str]:
        """工程語義解讀"""
        strength = "強" if abs(corr) > 0.7 else "中等" if abs(corr) > 0.4 else "弱"
        direction = "正" if corr > 0 else "負"

        if lag == 0:
            causality = "SIMULTANEOUS"
            explanation = (
                f"{target} 與 {reference} 的{direction}相關性 ({corr:.3f}) 發生在零延遲。"
                "這在物理上有兩種可能: "
                "(1) 極快速的控制迴路,感測器與執行器在同一取樣週期內完成動作; "
                "(2) 因果倒置 (Reverse Causality) -- 例如 {reference} 其實是追逐 {target} 的控制器輸出。"
                "建議: 確認 {reference} 是否為控制器 OP (Output) 值。"
            )
            action = "檢查控制迴路架構，確認因果方向"
        elif lag > 0:
            causality = "TARGET_LEADS"
            explanation = (
                f"{target} 領先 {reference} {lag} 個取樣週期 "
                f"({direction}相關 {corr:.3f}, {strength})。"
                f"即: {target} 的變化 → {lag} 步後 → {reference} 跟著變化。"
            )
            action = f"調查 {target} 上游的製程變數"
        else:
            causality = "REFERENCE_LEADS"
            explanation = (
                f"{reference} 領先 {target} {abs(lag)} 個取樣週期 "
                f"({direction}相關 {corr:.3f}, {strength})。"
                f"即: {reference} 的變化 → {abs(lag)} 步後 → {target} 跟著變化。"
            )
            action = f"調查 {reference} 上游的製程變數"

        return {
            "causality_direction": causality,
            "correlation_strength": strength,
            "explanation": explanation,
            "suggested_action": action,
        }
