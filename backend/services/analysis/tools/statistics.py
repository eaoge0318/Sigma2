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


class CompareSegmentsTool(AnalysisTool):
    """數據區間/樣本作對比分析工具"""

    @property
    def name(self) -> str:
        return "compare_data_segments"

    @property
    def description(self) -> str:
        return "對比特定區間（或單點）與基準區間的差異。支援格式如：'30' (單點), '100-150' (區間), 或 '30, 100-150' (混合)。"

    @property
    def required_params(self) -> List[str]:
        return ["file_id", "target_segments"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        target_input = params.get("target_segments")
        baseline_input = params.get("baseline_segments")

        summary = self.analysis_service.load_summary(session_id, file_id)
        csv_path = (
            self.analysis_service.base_dir
            / session_id
            / "uploads"
            / summary["filename"]
        )
        df = pd.read_csv(csv_path)
        numeric_cols = df.select_dtypes(include=[np.number]).columns

        def parse_segments(input_data):
            indices = set()
            if not input_data:
                return indices

            # 兼容列表輸入
            if isinstance(input_data, list):
                for item in input_data:
                    if isinstance(item, int):
                        if 0 <= item < len(df):
                            indices.add(item)
                    else:
                        indices.update(parse_segments(str(item)))
                return list(indices)

            # 兼容字串輸入，移除括號並依逗號切割
            input_str = str(input_data).replace("[", "").replace("]", "").strip()
            parts = [p.strip() for p in input_str.split(",")]
            for p in parts:
                if not p:
                    continue
                if "-" in p:
                    try:
                        start_str, end_str = p.split("-")
                        start, end = int(start_str), int(end_str)
                        indices.update(range(max(0, start), min(len(df), end + 1)))
                    except Exception:
                        pass
                else:
                    try:
                        idx = int(p)
                        if 0 <= idx < len(df):
                            indices.add(idx)
                    except Exception:
                        pass
            return list(indices)

        target_indices = parse_segments(target_input)
        if not target_indices:
            return {"error": f"無法解析目標區間: {target_input}"}

        if baseline_input:
            baseline_indices = parse_segments(baseline_input)
        else:
            baseline_indices = [i for i in range(len(df)) if i not in target_indices]

        if not baseline_indices:
            return {"error": "基準區間解析為空，無法進行對比。"}

        df_target = df.iloc[target_indices][numeric_cols]
        df_base = df.iloc[baseline_indices][numeric_cols]

        diff_results = []
        for col in numeric_cols:
            t_mean = df_target[col].mean()
            b_mean = df_base[col].mean()
            b_std = df_base[col].std()

            if pd.isna(t_mean) or pd.isna(b_mean):
                continue

            # 使用 Z-score 思路看偏離度
            if b_std and b_std > 0:
                deviation = (t_mean - b_mean) / b_std
            else:
                deviation = (
                    0 if t_mean == b_mean else (1.0 if t_mean > b_mean else -1.0)
                )

            diff_results.append(
                {
                    "parameter": col,
                    "target_mean": float(t_mean),
                    "baseline_mean": float(b_mean),
                    "z_score_diff": float(deviation),
                    "percent_diff": float((t_mean - b_mean) / b_mean * 100)
                    if b_mean != 0
                    else 0,
                }
            )

        # 按偏離絕對值排序
        sorted_diffs = sorted(
            diff_results, key=lambda x: abs(x["z_score_diff"]), reverse=True
        )
        top_3 = [
            f"{d['parameter']} ({'偏高' if d['z_score_diff'] > 0 else '偏低'} {abs(d['z_score_diff']):.2f}σ)"
            for d in sorted_diffs[:3]
        ]

        return {
            "target_range": str(target_input),
            "target_sample_count": len(target_indices),
            "baseline_sample_count": len(baseline_indices),
            "top_deviations": sorted_diffs[:15],
            "top_3_summary": "【區間觀察 Top 3】" + " | ".join(top_3),
            "conclusion": f"相對於基準，該區間在 {sorted_diffs[0]['parameter']} 表現出最顯著的偏離。",
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

        summary = self.analysis_service.load_summary(session_id, file_id)
        filename = summary["filename"]
        csv_path = self.analysis_service.base_dir / session_id / "uploads" / filename

        # 讀取數據
        df = pd.read_csv(csv_path, usecols=[col])
        series = df[col].dropna()

        if series.empty:
            return {"error": "No valid data for outlier detection"}

        q1 = series.quantile(0.25)
        q3 = series.quantile(0.75)
        iqr = q3 - q1
        lower_bound = q1 - 1.5 * iqr
        upper_bound = q3 + 1.5 * iqr

        outliers = series[(series < lower_bound) | (series > upper_bound)]
        outlier_count = len(outliers)
        total_count = len(series)
        percentage = (outlier_count / total_count) * 100 if total_count > 0 else 0

        return {
            "parameter": col,
            "method": "IQR (1.5x)",
            "bounds": {"lower": float(lower_bound), "upper": float(upper_bound)},
            "stats": {
                "q1": float(q1),
                "q3": float(q3),
                "iqr": float(iqr),
                "mean": float(series.mean()),
                "std": float(series.std()),
            },
            "outlier_info": {
                "count": outlier_count,
                "percentage": f"{percentage:.2f}%",
                "is_abnormal": outlier_count > 0,
                "recent_outliers_preview": outliers.tail(5).tolist(),
            },
            "interpretation": f"在 {total_count} 筆樣本中發現 {outlier_count} 個異常點 ({percentage:.2f}%)。",
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
        target_input = params.get("target")
        top_n = params.get("top_n", 5)

        # 支援多個參數輸入 (逗號分隔)
        if "," in target_input:
            targets = [t.strip() for t in target_input.split(",")]
        else:
            targets = [target_input]

        correlations = self.analysis_service.load_correlations(session_id, file_id)

        multi_results = {}

        for target in targets:
            if target not in correlations:
                multi_results[target] = {"error": f"No correlation data for {target}"}
                continue

            target_corrs = correlations[target]
            # 排序絕對值
            sorted_params = sorted(
                target_corrs.items(),
                key=lambda x: abs(x[1]) if x[1] is not None else 0,
                reverse=True,
            )

            results = []
            target_norm = str(target).strip().lower()
            for k, v in sorted_params:
                k_norm = str(k).strip().lower()
                # 排除過濾：忽略自身 (不計大小寫與空白) 以及 None 值
                if k_norm == target_norm or v is None:
                    continue

                results.append(
                    {
                        "parameter": k,
                        "correlation": v,
                    }
                )
            results = results[:top_n]

            multi_results[target] = results

        # 向下兼容單一目標的輸出格式
        if len(targets) == 1:
            target = targets[0]
            res = multi_results[target]
            if isinstance(res, dict) and "error" in res:
                return res  # Return error dict directly
            return {"target": target, "top_correlations": res}

        return {"targets": targets, "multi_target_correlations": multi_results}


class AnalyzeCategoryCorrelationTool(AnalysisTool):
    """跨類別參數相關性分析工具"""

    @property
    def name(self) -> str:
        return "analyze_category_correlation"

    @property
    def description(self) -> str:
        return "分析兩個類別（例如 SHAP 與 PRESSDRY）之間所有參數的交叉相關性。返回相關性最高的配對列表。"

    @property
    def required_params(self) -> List[str]:
        return ["file_id", "category_a", "category_b"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        cat_a = params.get("category_a")
        cat_b = params.get("category_b")
        top_n = params.get("top_n", 10)

        summary = self.analysis_service.load_summary(session_id, file_id)
        categories = summary.get("categories", {})

        cols_a = categories.get(cat_a, [])
        cols_b = categories.get(cat_b, [])

        if not cols_a or not cols_b:
            return {"error": f"Category {cat_a} or {cat_b} not found."}

        correlations = self.analysis_service.load_correlations(session_id, file_id)

        cross_pairs = []
        for a in cols_a:
            if a not in correlations:
                continue
            a_corrs = correlations[a]
            for b in cols_b:
                if b in a_corrs and a_corrs[b] is not None:
                    cross_pairs.append(
                        {"param_a": a, "param_b": b, "correlation": a_corrs[b]}
                    )

        # 排序
        sorted_pairs = sorted(
            cross_pairs, key=lambda x: abs(x["correlation"]), reverse=True
        )

        return {
            "category_a": cat_a,
            "category_b": cat_b,
            "top_cross_correlations": sorted_pairs[:top_n],
            "total_pairs_computed": len(cross_pairs),
        }


class GetCorrelationMatrixTool(AnalysisTool):
    """獲取選定參數清單的相關性矩陣"""

    @property
    def name(self) -> str:
        return "get_correlation_matrix"

    @property
    def description(self) -> str:
        return "計算並返回指定參數列表之間的所有相關性。適用於多點連動分析。"

    @property
    def required_params(self) -> List[str]:
        return ["file_id", "parameters"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        param_input = params.get("parameters")

        if isinstance(param_input, str):
            param_list = [p.strip() for p in param_input.split(",")]
        else:
            param_list = param_input

        correlations = self.analysis_service.load_correlations(session_id, file_id)

        matrix = {}
        valid_params = [p for p in param_list if p in correlations]

        for p1 in valid_params:
            matrix[p1] = {}
            for p2 in valid_params:
                matrix[p1][p2] = correlations[p1].get(p2)

        return {"parameters": valid_params, "matrix": matrix}
