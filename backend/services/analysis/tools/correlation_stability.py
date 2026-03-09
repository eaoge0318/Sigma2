"""
共線性瓦解偵測工具 (Correlation Breakdown Detection)

比較「正常區段」vs「異常區段」的相關矩陣差異,
找出原本高度相關但在異常時解耦的參數對 —— 即因果鏈斷裂點。

核心原理:
  正常時 A ↔ B 因物理耦合 r ≈ 0.9+,
  當製程異常時若 r 降至 0.3 → 因果關係被打斷,
  這比「某參數偏高」更深層的根因線索。

統計防護:
  - 最低樣本量門檻 (min_segment_size)
  - Fisher Z 檢定確認 delta 顯著性
  - 輸出 p_value 讓下游判斷可信度
"""

import logging
from typing import Dict, Any, List

import numpy as np
import pandas as pd

from .base import AnalysisTool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
MIN_SEGMENT_SIZE = 15  # 相關性計算最低樣本量
DEFAULT_TOP_N = 10  # 預設輸出前 N 組瓦解
BREAKDOWN_THRESHOLD = 0.30  # |delta| > 此值視為「瓦解」
HIGH_CORR_THRESHOLD = 0.60  # 正常時 |r| > 此值才納入比較 (避免原本就不相關的雜訊)
Z_SCORE_ANOMALY_THRESHOLD = 2.5  # 自動偵測異常的 Z-Score 門檻


class CorrelationBreakdownTool(AnalysisTool):
    """比較正常/異常區段的相關矩陣, 找出共線性瓦解 (因果鏈斷裂)"""

    @property
    def name(self) -> str:
        return "detect_correlation_breakdown"

    @property
    def description(self) -> str:
        return (
            "比較正常/異常區段的相關矩陣變化, "
            "找出共線性瓦解的參數對 (因果鏈斷裂)。"
            "適合原因分析: 原本高度相關的參數在異常時解耦 = 最重要的根因線索。"
        )

    @property
    def required_params(self) -> List[str]:
        return ["file_id", "target"]

    # ------------------------------------------------------------------
    # 主邏輯
    # ------------------------------------------------------------------
    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        target = params.get("target", "")
        anomaly_range = params.get("anomaly_range")
        top_n = int(params.get("top_n", DEFAULT_TOP_N))

        # --- 1. 讀取原始資料 ---
        try:
            summary = self.analysis_service.load_summary(session_id, file_id)
            csv_path = (
                self.analysis_service.base_dir
                / session_id
                / "uploads"
                / summary["filename"]
            )
            df = pd.read_csv(csv_path)
        except Exception as e:
            return {"error": f"資料讀取失敗: {e}"}

        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        if target not in numeric_cols:
            return {"error": f"目標參數 '{target}' 不在數值欄位中"}

        # --- 2. 確定異常區段索引 ---
        if anomaly_range:
            anomaly_indices = self.parse_indices(anomaly_range, max_len=len(df))
        else:
            anomaly_indices = self._auto_detect_anomaly(df, target)

        if len(anomaly_indices) < MIN_SEGMENT_SIZE:
            return {
                "error": (
                    f"異常區段樣本量不足 ({len(anomaly_indices)} 筆, "
                    f"至少需要 {MIN_SEGMENT_SIZE} 筆)。"
                    f"請提供更大的 anomaly_range 或選擇其他目標參數。"
                ),
                "anomaly_count": len(anomaly_indices),
            }

        normal_indices = [i for i in range(len(df)) if i not in set(anomaly_indices)]
        if len(normal_indices) < MIN_SEGMENT_SIZE:
            return {"error": f"正常區段樣本量不足 ({len(normal_indices)} 筆)"}

        # --- 3. 篩選相關參數 (從全域相關矩陣) ---
        related_params = self._get_related_params(
            session_id, file_id, target, numeric_cols
        )
        if len(related_params) < 2:
            # 退回方案: 取方差最高的前 20 個數值欄位
            variances = df[numeric_cols].var().sort_values(ascending=False)
            related_params = [c for c in variances.index[:20].tolist() if c != target]

        # --- 4. 分段計算相關矩陣 ---
        analysis_cols = [target] + [
            p for p in related_params if p != target and p in numeric_cols
        ]
        # 限制最多 30 個欄位避免計算量爆炸
        analysis_cols = analysis_cols[:30]

        df_normal = df.iloc[normal_indices][analysis_cols]
        df_anomaly = df.iloc[anomaly_indices][analysis_cols]

        corr_normal = df_normal.corr(method="pearson")
        corr_anomaly = df_anomaly.corr(method="pearson")

        # --- 5. 計算 delta 並排序 ---
        breakdowns = []
        stable_pairs = []
        checked_pairs = set()

        for col_a in analysis_cols:
            for col_b in analysis_cols:
                if col_a >= col_b:
                    continue
                pair_key = (col_a, col_b)
                if pair_key in checked_pairs:
                    continue
                checked_pairs.add(pair_key)

                r_norm = corr_normal.loc[col_a, col_b]
                r_anom = corr_anomaly.loc[col_a, col_b]

                if pd.isna(r_norm) or pd.isna(r_anom):
                    continue

                # 只比較正常時有足夠相關性的對
                if abs(r_norm) < HIGH_CORR_THRESHOLD:
                    continue

                delta = abs(r_norm) - abs(r_anom)  # 正值 = 瓦解

                # Fisher Z 檢定
                p_value = self._fisher_z_test(
                    r_norm, r_anom, len(normal_indices), len(anomaly_indices)
                )

                entry = {
                    "param_a": col_a,
                    "param_b": col_b,
                    "r_normal": round(float(r_norm), 3),
                    "r_anomaly": round(float(r_anom), 3),
                    "delta": round(float(delta), 3),
                    "p_value": round(float(p_value), 4)
                    if p_value is not None
                    else None,
                    "significant": p_value is not None and p_value < 0.05,
                }

                if delta >= BREAKDOWN_THRESHOLD:
                    # 生成解讀
                    direction_n = "正相關" if r_norm > 0 else "負相關"
                    if abs(r_anom) < 0.3:
                        status_a = "解耦 (幾乎無關)"
                    elif (r_norm > 0 and r_anom < 0) or (r_norm < 0 and r_anom > 0):
                        status_a = "反轉 (方向翻轉)"
                    else:
                        status_a = "減弱"
                    entry["interpretation"] = (
                        f"正常時{direction_n} (r={r_norm:.2f}), "
                        f"異常時{status_a} (r={r_anom:.2f})"
                    )
                    breakdowns.append(entry)
                else:
                    entry["interpretation"] = "相關性穩定, 非問題根源"
                    stable_pairs.append(entry)

        # 按 delta 降冪排序
        breakdowns.sort(key=lambda x: x["delta"], reverse=True)
        stable_pairs.sort(key=lambda x: abs(x["r_normal"]), reverse=True)

        # 取 top_n
        top_breakdowns = breakdowns[:top_n]
        top_stable = stable_pairs[:5]

        # --- 6. 生成摘要 ---
        sig_breakdowns = [b for b in top_breakdowns if b.get("significant", False)]

        if sig_breakdowns:
            top_pair = sig_breakdowns[0]
            summary_text = (
                f"發現 {len(sig_breakdowns)} 組統計顯著的共線性瓦解 (p<0.05)。"
                f"最大瓦解: {top_pair['param_a']} <-> {top_pair['param_b']} "
                f"(正常 r={top_pair['r_normal']}, 異常 r={top_pair['r_anomaly']}, "
                f"delta={top_pair['delta']})"
            )
        elif top_breakdowns:
            top_pair = top_breakdowns[0]
            summary_text = (
                f"發現 {len(top_breakdowns)} 組共線性變化 (delta>{BREAKDOWN_THRESHOLD}), "
                f"但統計顯著性不足 (可能異常樣本量偏少)。"
                f"最大變化: {top_pair['param_a']} <-> {top_pair['param_b']}"
            )
        else:
            summary_text = (
                "未發現顯著的共線性瓦解。"
                "異常區段中參數間的相關結構保持穩定, "
                "問題可能源於均值偏移而非因果鏈斷裂。"
            )

        return {
            "target": target,
            "anomaly_segment": (
                f"{min(anomaly_indices)}-{max(anomaly_indices)}"
                if anomaly_indices
                else "none"
            ),
            "normal_sample_count": len(normal_indices),
            "anomaly_sample_count": len(anomaly_indices),
            "analyzed_params_count": len(analysis_cols),
            "breakdowns": top_breakdowns,
            "stable_pairs": top_stable,
            "total_breakdown_count": len(breakdowns),
            "significant_breakdown_count": len(sig_breakdowns),
            "summary": summary_text,
        }

    # ------------------------------------------------------------------
    # 自動異常偵測
    # ------------------------------------------------------------------
    def _auto_detect_anomaly(self, df: pd.DataFrame, target: str) -> list:
        """用 Z-Score 自動找 target 的異常區段"""
        series = df[target].dropna()
        if len(series) < 30:
            return []

        mean_val = series.mean()
        std_val = series.std()
        if std_val == 0:
            return []

        z_scores = ((series - mean_val) / std_val).abs()
        anomaly_mask = z_scores > Z_SCORE_ANOMALY_THRESHOLD
        anomaly_indices = series.index[anomaly_mask].tolist()

        # 如果異常太少, 嘗試用滾動窗口偵測局部異常
        if len(anomaly_indices) < MIN_SEGMENT_SIZE:
            window = max(20, len(df) // 10)
            rolling_mean = series.rolling(window=window, center=True).mean()
            rolling_std = series.rolling(window=window, center=True).std()
            local_z = ((series - rolling_mean) / rolling_std.replace(0, np.nan)).abs()
            local_z = local_z.fillna(0)
            anomaly_mask = local_z > Z_SCORE_ANOMALY_THRESHOLD
            anomaly_indices = series.index[anomaly_mask].tolist()

        return anomaly_indices

    # ------------------------------------------------------------------
    # 從全域相關矩陣取相關參數
    # ------------------------------------------------------------------
    def _get_related_params(
        self, session_id: str, file_id: str, target: str, numeric_cols: list
    ) -> list:
        """取與 target 相關性最高的參數 (從預計算的全域相關矩陣)"""
        try:
            correlations = self.analysis_service.load_correlations(session_id, file_id)
            if not correlations or target not in correlations:
                return []

            target_corrs = correlations[target]
            sorted_params = sorted(
                target_corrs.items(),
                key=lambda x: abs(x[1]) if x[1] is not None else 0,
                reverse=True,
            )
            return [
                k
                for k, v in sorted_params
                if k != target and v is not None and k in numeric_cols
            ][:20]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Fisher Z 檢定: 兩個相關係數是否顯著不同
    # ------------------------------------------------------------------
    @staticmethod
    def _fisher_z_test(r1: float, r2: float, n1: int, n2: int) -> float:
        """
        Fisher r-to-Z 轉換, 檢定兩個獨立樣本的相關係數是否顯著不同。
        回傳 p-value (雙尾)。
        """
        try:
            # 避免 arctanh(1) = inf
            r1 = np.clip(r1, -0.9999, 0.9999)
            r2 = np.clip(r2, -0.9999, 0.9999)

            z1 = np.arctanh(r1)
            z2 = np.arctanh(r2)

            se = np.sqrt(1.0 / (n1 - 3) + 1.0 / (n2 - 3))
            if se == 0:
                return None

            z_stat = abs(z1 - z2) / se

            # 雙尾 p-value (用標準常態近似)
            from scipy import stats

            p_value = 2.0 * (1.0 - stats.norm.cdf(z_stat))
            return float(p_value)
        except Exception:
            return None
