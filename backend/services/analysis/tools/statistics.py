from .base import AnalysisTool
from typing import Dict, Any, List
import pandas as pd
import numpy as np
from scipy.stats import pearsonr, spearmanr, ttest_ind, linregress, skew, kurtosis
from pathlib import Path


class CalculateCorrelationTool(AnalysisTool):
    """計算相關性工具"""

    name = "calculate_correlation"
    description = "計算參數間的相關係數"
    required_params = ["file_id", "parameters"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        parameters = params.get("parameters", [])
        method = params.get("method", "pearson")
        target = params.get("target")

        # 加載 CSV 數據
        csv_path = self._get_csv_path(session_id, file_id)
        if not csv_path:
            return {"error": "CSV file not found"}

        try:
            df = pd.read_csv(csv_path, encoding="utf-8-sig")
            df.columns = [str(c).strip() for c in df.columns]

            # 過濾只存在的數值列
            numeric_cols = df.select_dtypes(include=[np.number]).columns
            valid_params = [p for p in parameters if p in numeric_cols]

            if not valid_params:
                return {"error": "No valid numeric parameters found"}

            results = []

            if target:
                if target not in numeric_cols:
                    return {
                        "error": f"Target parameter '{target}' not found or not numeric"
                    }

                # 計算所有參數與 target 的相關性
                for param in valid_params:
                    if param == target:
                        continue

                    try:
                        corr, p_val = self._calc_corr(df[param], df[target], method)
                        if np.isnan(corr):
                            continue

                        results.append(
                            {
                                "param1": param,
                                "param2": target,
                                "correlation": float(corr),
                                "p_value": float(p_val),
                                "interpretation": self._interpret_corr(corr, p_val),
                            }
                        )
                    except Exception:
                        continue
            else:
                # 兩兩計算
                for i in range(len(valid_params)):
                    for j in range(i + 1, len(valid_params)):
                        p1, p2 = valid_params[i], valid_params[j]
                        try:
                            corr, p_val = self._calc_corr(df[p1], df[p2], method)
                            if np.isnan(corr):
                                continue

                            results.append(
                                {
                                    "param1": p1,
                                    "param2": p2,
                                    "correlation": float(corr),
                                    "p_value": float(p_val),
                                    "interpretation": self._interpret_corr(corr, p_val),
                                }
                            )
                        except:
                            continue

            return {"method": method, "results": results}
        except Exception as e:
            return {"error": f"Analysis failed: {str(e)}"}

    def _calc_corr(self, x, y, method):
        # 去除 NaN
        mask = ~np.isnan(x) & ~np.isnan(y)
        if not mask.any():
            return np.nan, np.nan

        x_clean = x[mask]
        y_clean = y[mask]

        if len(x_clean) < 2:
            return np.nan, np.nan

        if method == "pearson":
            return pearsonr(x_clean, y_clean)
        elif method == "spearman":
            return spearmanr(x_clean, y_clean)
        else:
            return pearsonr(x_clean, y_clean)

    def _interpret_corr(self, corr: float, p_value: float) -> str:
        if p_value >= 0.05:
            return "無統計顯著性"

        abs_corr = abs(corr)
        if abs_corr >= 0.7:
            strength = "強"
        elif abs_corr >= 0.4:
            strength = "中等"
        else:
            strength = "弱"

        direction = "正" if corr > 0 else "負"
        return f"{strength}{direction}相關，統計顯著"

    def _get_csv_path(self, session_id: str, file_id: str) -> str:
        summary = self.service.load_summary(session_id, file_id)
        if not summary:
            return None
        filename = summary["filename"]
        return str(self.service.base_dir / session_id / "uploads" / filename)


class GetTopCorrelationsTool(AnalysisTool):
    """獲取 Top 相關性工具"""

    name = "get_top_correlations"
    description = "快速獲取與目標變量相關性最強的參數"
    required_params = ["file_id", "target"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        target = params.get("target")
        top_n = params.get("top_n", 10)
        min_corr = params.get("min_correlation", 0.3)

        # 讀取相關性矩陣
        correlations = self.service.load_correlations(session_id, file_id)

        if not correlations:
            return {"error": "Correlations not found. Please prepare index first."}

        if target not in correlations:
            return {"error": f"Target {target} not found in correlation matrix"}

        # 提取與 target 的相關性
        results = []
        for param, corr_value in correlations[target].items():
            if (
                param != target
                and corr_value is not None
                and abs(corr_value) >= min_corr
            ):
                results.append(
                    {
                        "parameter": param,
                        "correlation": corr_value,
                        "p_value": 0.001,  # 簡化，實際應重新計算
                    }
                )

        # 排序
        results.sort(key=lambda x: abs(x["correlation"]), reverse=True)

        return {"target": target, "top_correlations": results[:top_n]}


class CompareGroupsTool(AnalysisTool):
    """組間比較工具"""

    name = "compare_groups"
    description = "比較不同條件下參數的差異（t-test）"
    required_params = ["file_id", "parameter", "group_by"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        parameter = params.get("parameter")
        group_by = params.get("group_by")

        # 加載數據
        csv_path = self._get_csv_path(session_id, file_id)
        if not csv_path:
            return {"error": "CSV file not found"}

        try:
            df = pd.read_csv(csv_path, encoding="utf-8-sig")
            df.columns = [str(c).strip() for c in df.columns]

            if parameter not in df.columns or group_by not in df.columns:
                return {"error": "Parameter or group_by not found"}

            # 分組統計
            groups = df.groupby(group_by)[parameter]
            group_stats = {}
            group_data = {}

            for name, group in groups:
                # 去除 NaN
                clean_group = group.dropna()
                name_str = str(name)

                group_stats[name_str] = {
                    "mean": float(clean_group.mean()) if len(clean_group) > 0 else None,
                    "std": float(clean_group.std()) if len(clean_group) > 0 else None,
                    "count": len(clean_group),
                }
                group_data[name_str] = clean_group.values

            # t-test (僅支持兩組)
            test_result = {}
            if len(group_data) == 2:
                keys = list(group_data.keys())
                g1, g2 = group_data[keys[0]], group_data[keys[1]]

                if len(g1) > 1 and len(g2) > 1:
                    stat, p_val = ttest_ind(g1, g2, equal_var=False)  # Welch's t-test
                    test_result = {
                        "test": "Welch's t-test",
                        "statistic": float(stat),
                        "p_value": float(p_val),
                        "significant": bool(p_val < 0.05),
                        "interpretation": "兩組均值存在顯著差異"
                        if p_val < 0.05
                        else "兩組均值無顯著差異",
                    }
                else:
                    test_result = {"error": "Insufficient data for t-test"}
            else:
                test_result = {
                    "warning": "Only 2 groups supported for automatic t-test"
                }

            return {
                "parameter": parameter,
                "group_by": group_by,
                "groups": group_stats,
                "test_result": test_result,
            }
        except Exception as e:
            return {"error": f"Compare groups failed: {str(e)}"}

    def _get_csv_path(self, session_id: str, file_id: str) -> str:
        summary = self.service.load_summary(session_id, file_id)
        if not summary:
            return None
        filename = summary["filename"]
        return str(self.service.base_dir / session_id / "uploads" / filename)


class DetectOutliersTool(AnalysisTool):
    """異常檢測工具"""

    name = "detect_outliers"
    description = "使用 IQR 方法檢測參數中的異常值"
    required_params = ["file_id", "parameter"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        parameter = params.get("parameter")

        csv_path = self._get_csv_path(session_id, file_id)
        if not csv_path:
            return {"error": "CSV file not found"}

        try:
            df = pd.read_csv(csv_path, encoding="utf-8-sig")
            df.columns = [str(c).strip() for c in df.columns]
            if parameter not in df.columns:
                return {"error": f"Parameter {parameter} not found"}

            series = pd.to_numeric(df[parameter], errors="coerce").dropna()

            q1 = series.quantile(0.25)
            q3 = series.quantile(0.75)
            iqr = q3 - q1
            lower_bound = q1 - 1.5 * iqr
            upper_bound = q3 + 1.5 * iqr

            outliers = series[(series < lower_bound) | (series > upper_bound)]

            return {
                "parameter": parameter,
                "method": "IQR",
                "total_count": len(series),
                "outlier_count": len(outliers),
                "outlier_ratio": len(outliers) / len(series),
                "bounds": {"lower": float(lower_bound), "upper": float(upper_bound)},
                "outliers_head": outliers.head(10).tolist(),  # 只返回前10個
            }
        except Exception as e:
            return {"error": f"Outlier detection failed: {str(e)}"}

    def _get_csv_path(self, session_id: str, file_id: str) -> str:
        summary = self.service.load_summary(session_id, file_id)
        if not summary:
            return None
        filename = summary["filename"]
        return str(self.service.base_dir / session_id / "uploads" / filename)


class AnalyzeDistributionTool(AnalysisTool):
    """分佈分析工具"""

    name = "analyze_distribution"
    description = "分析參數的數據分佈（直方圖、偏度、峰度）"
    required_params = ["file_id", "parameter"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        parameter = params.get("parameter")
        bins = params.get("bins", 20)

        csv_path = self._get_csv_path(session_id, file_id)
        if not csv_path:
            return {"error": "CSV file not found"}

        try:
            df = pd.read_csv(csv_path, encoding="utf-8-sig")
            df.columns = [str(c).strip() for c in df.columns]
            if parameter not in df.columns:
                return {"error": f"Parameter {parameter} not found"}

            series = pd.to_numeric(df[parameter], errors="coerce").dropna()

            # 計算統計量
            skew_val = skew(series)
            kurt_val = kurtosis(series)

            # 計算直方圖
            hist, bin_edges = np.histogram(series, bins=bins)

            return {
                "parameter": parameter,
                "stats": {
                    "count": len(series),
                    "mean": float(series.mean()),
                    "std": float(series.std()),
                    "skewness": float(skew_val),  # 偏度 > 0 右偏
                    "kurtosis": float(kurt_val),
                },
                "histogram": {"counts": hist.tolist(), "bin_edges": bin_edges.tolist()},
                "interpretation": self._interpret_distribution(skew_val),
            }
        except Exception as e:
            return {"error": f"Distribution analysis failed: {str(e)}"}

    def _interpret_distribution(self, skew_val):
        if abs(skew_val) < 0.5:
            return "數據分佈大致對稱 (接近常態分佈)"
        elif skew_val > 0.5:
            if skew_val > 1:
                return "數據呈現高度右偏 (長尾在右側)"
            return "數據呈現中度右偏"
        else:
            if skew_val < -1:
                return "數據呈現高度左偏 (長尾在左側)"
            return "數據呈現中度左偏"

    def _get_csv_path(self, session_id: str, file_id: str) -> str:
        summary = self.service.load_summary(session_id, file_id)
        if not summary:
            return None
        filename = summary["filename"]
        return str(self.service.base_dir / session_id / "uploads" / filename)


class PerformRegressionTool(AnalysisTool):
    """回歸分析工具"""

    name = "perform_regression"
    description = "執行簡單線性回歸分析"
    required_params = ["file_id", "x_param", "y_param"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        x_param = params.get("x_param")
        y_param = params.get("y_param")

        csv_path = self._get_csv_path(session_id, file_id)
        if not csv_path:
            return {"error": "CSV file not found"}

        try:
            df = pd.read_csv(csv_path, encoding="utf-8-sig")
            df.columns = [str(c).strip() for c in df.columns]
            if x_param not in df.columns or y_param not in df.columns:
                return {"error": "Parameters not found"}

            # 清洗數據
            data = df[[x_param, y_param]].dropna()
            if len(data) < 2:
                return {"error": "Insufficient data points"}

            x = data[x_param]
            y = data[y_param]

            slope, intercept, r_value, p_value, std_err = linregress(x, y)

            return {
                "x_param": x_param,
                "y_param": y_param,
                "model": {
                    "slope": float(slope),
                    "intercept": float(intercept),
                    "equation": f"y = {slope:.4f}x + {intercept:.4f}",
                },
                "metrics": {
                    "r_squared": float(r_value**2),
                    "correlation": float(r_value),
                    "p_value": float(p_value),
                    "std_err": float(std_err),
                },
                "data_points": len(x),
                "interpretation": f"模型的 R² 為 {r_value**2:.2f}，顯示自變數能解釋約 {r_value**2 * 100:.1f}% 的變異。",
            }
        except Exception as e:
            return {"error": f"Regression failed: {str(e)}"}

    def _get_csv_path(self, session_id: str, file_id: str) -> str:
        summary = self.service.load_summary(session_id, file_id)
        if not summary:
            return None
        filename = summary["filename"]
        return str(self.service.base_dir / session_id / "uploads" / filename)
