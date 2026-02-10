from typing import Dict, Any, List
import pandas as pd
import numpy as np
from scipy import stats
from .base import AnalysisTool


class AnalyzeDistributionTool(AnalysisTool):
    """分析數值參數的分佈情況（直方圖數據）"""

    @property
    def name(self) -> str:
        return "analyze_distribution"

    @property
    def description(self) -> str:
        return (
            "分析數據的分佈，計算直方圖 bin 數據、偏度與峰度。用於了解數據的集中趨勢。"
        )

    @property
    def required_params(self) -> List[str]:
        return ["file_id", "parameter"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        col = params.get("parameter")

        stats_data = self.analysis_service.load_statistics(session_id, file_id)
        col_stats = stats_data.get(col, {})

        if not col_stats or col_stats.get("count", 0) == 0:
            return {"error": "No data available for this parameter"}

        # 讀取原始數據以計算 bins
        summary = self.analysis_service.load_summary(session_id, file_id)
        filename = summary["filename"]
        csv_path = self.analysis_service.base_dir / session_id / "uploads" / filename
        df = pd.read_csv(csv_path, usecols=[col])

        # 計算 Histogram
        data = df[col].dropna().values
        hist, bin_edges = np.histogram(data, bins=20)

        return {
            "parameter": col,
            "basic_stats": col_stats,
            "histogram": {"counts": hist.tolist(), "bins": bin_edges.tolist()},
            "skewness": float(stats.skew(data)),
            "kurtosis": float(stats.kurtosis(data)),
        }


class DetectOutliersTool(AnalysisTool):
    """使用 IQR 方法偵測異常值"""

    @property
    def name(self) -> str:
        return "detect_outliers"

    @property
    def description(self) -> str:
        return "偵測數據中的異常值（Outliers），基於 IQR 四分位距規則。"

    @property
    def required_params(self) -> List[str]:
        return ["file_id", "parameter"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        col = params.get("parameter")

        stats_data = self.analysis_service.load_statistics(session_id, file_id)
        s = stats_data.get(col)

        if not s or not s.get("q1") or not s.get("q3"):
            return {"error": "Insufficient stats for outlier detection"}

        q1 = s["q1"]
        q3 = s["q3"]
        iqr = q3 - q1
        lower_bound = q1 - 1.5 * iqr
        upper_bound = q3 + 1.5 * iqr

        return {
            "parameter": col,
            "method": "IQR",
            "bounds": {"lower": lower_bound, "upper": upper_bound},
            "iqr": iqr,
            "normal_range_desc": f"{lower_bound:.2f} ~ {upper_bound:.2f}",
        }


class GetTopCorrelationsTool(AnalysisTool):
    """獲取與指定參數相關性最高的其他參數"""

    @property
    def name(self) -> str:
        return "get_top_correlations"

    @property
    def description(self) -> str:
        return "找出與目標參數相關性最強的前 N 個參數。用於尋找影響因素。"

    @property
    def required_params(self) -> List[str]:
        return ["file_id", "target"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        target = params.get("target")
        top_n = params.get("top_n", 5)

        correlations = self.analysis_service.load_correlations(session_id, file_id)
        if target not in correlations:
            return {"error": f"No correlation data for {target}"}

        target_corrs = correlations[target]
        # 排序絕對值
        sorted_params = sorted(
            target_corrs.items(),
            key=lambda x: abs(x[1]) if x[1] is not None else 0,
            reverse=True,
        )

        # 過濾掉自己和 None
        results = [
            {"parameter": k, "correlation": v}
            for k, v in sorted_params
            if k != target and v is not None
        ][:top_n]

        return {"target": target, "top_correlations": results}
