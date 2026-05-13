from typing import Dict, Any, List
import pandas as pd
import numpy as np
from scipy import stats
from .base import AnalysisTool
import warnings


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
        return ["file_id"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        param_input = params.get("parameter")
        target_segments_str = params.get("target_segments")

        # 支援全域掃描：如果 parameter 為空，則自動掃描所有數值欄位
        if not param_input:
            summary = self.analysis_service.load_summary(session_id, file_id)
            columns = summary.get("numerical_columns", [])
            # 限制掃描數量以免超時，或全掃描如果是必要的
            if not columns:
                return {"error": "未指定參數且無可用數值欄位。"}
            is_global_scan = True
        elif isinstance(param_input, list):
            columns = param_input
            is_global_scan = False
        elif isinstance(param_input, str):
            columns = [p.strip() for p in param_input.split(",")]
            is_global_scan = False
        else:
            return {"error": "無效的參數類型"}

        stats_data = self.analysis_service.load_statistics(session_id, file_id)
        summary = self.analysis_service.load_summary(session_id, file_id)
        filename = summary["filename"]
        csv_path = self.analysis_service.get_csv_path(session_id, filename)

        results_map = {}
        for col in columns:
            if not col:
                continue

            try:
                # 讀取單一欄位數據
                df_full = pd.read_csv(csv_path, usecols=[col])

                # 區間過濾處理
                if target_segments_str:
                    target_indices = self.parse_indices(
                        target_segments_str, max_len=len(df_full)
                    )
                    if target_indices:
                        data_series = df_full.iloc[target_indices][col].dropna()
                    else:
                        data_series = df_full[col].dropna()
                else:
                    data_series = df_full[col].dropna()

                data = data_series.values
                if len(data) == 0:
                    results_map[col] = {"error": "無有效數值數據"}
                    continue

                hist, bin_edges = np.histogram(data, bins=20)

                # 獲取基礎統計量 (如果是全量則用緩存，否則動態計算)
                if not target_segments_str:
                    # 全域分析: 使用快取的統計資料
                    col_stats = stats_data.get(str(col), {})
                else:
                    # 區間分析: 動態重新計算所有統計資料,包括 Z-Score
                    mean_val = float(np.mean(data))
                    std_val = float(
                        np.std(data, ddof=1)
                    )  # [FIX] 統一使用 ddof=1,與 pandas/detect_outliers 一致
                    min_val = float(np.min(data))
                    max_val = float(np.max(data))

                    # 重新計算 Z-Score (使用區間的 mean 和 std)
                    max_sigma = 0.0
                    min_sigma = 0.0
                    has_extreme_outlier = False

                    if std_val > 0:
                        max_sigma = (max_val - mean_val) / std_val
                        min_sigma = (min_val - mean_val) / std_val

                        if abs(max_sigma) > 6 or abs(min_sigma) > 6:
                            has_extreme_outlier = True

                    col_stats = {
                        "count": len(data),
                        "mean": mean_val,
                        "min": min_val,
                        "max": max_val,
                        "std": std_val,
                        "max_sigma": round(max_sigma, 1),
                        "min_sigma": round(min_sigma, 1),
                        "has_extreme_outlier": has_extreme_outlier,
                    }

                # Suppress Precision Loss warnings for nearly-constant data
                with warnings.catch_warnings():
                    warnings.filterwarnings(
                        "ignore",
                        category=RuntimeWarning,
                        message=".*Precision loss occurred.*",
                    )
                    skewness = float(stats.skew(data)) if len(data) > 0 else 0.0
                    kurtosis = float(stats.kurtosis(data)) if len(data) > 0 else 0.0

                results_map[col] = {
                    "basic_stats": col_stats,
                    "histogram": {"counts": hist.tolist(), "bins": bin_edges.tolist()},
                    "skewness": skewness,
                    "kurtosis": kurtosis,
                    "target_range": target_segments_str or "full",
                }
            except Exception as e:
                results_map[col] = {"error": str(e)}

        # 向下相容單一參數模式
        if len(columns) == 1:
            col = columns[0]
            res = results_map.get(col)
            if res and "error" in res:
                return res
            return {"parameter": col, **(res or {})}

        # 如果是全域掃描，只回傳最有意義的 Top 5 (例如根據變異數或偏度)
        if hasattr(self, "name") and is_global_scan:
            # [NEW] Priority 1: Extreme Outliers (Sigma > 6)
            extreme_outliers = []
            for col, res in results_map.items():
                # Fix: Retrieve stats correctly from the result dictionary
                col_stats = res.get("basic_stats", {})
                if col_stats.get("has_extreme_outlier"):
                    extreme_outliers.append(
                        {
                            "parameter": col,
                            "max_sigma": col_stats.get("max_sigma"),
                            "min_sigma": col_stats.get("min_sigma"),
                        }
                    )

            # Sort outliers by severity (max abs sigma)
            extreme_outliers.sort(
                key=lambda x: max(abs(x["max_sigma"] or 0), abs(x["min_sigma"] or 0)),
                reverse=True,
            )

            # [NEW] Priority 2: High Skewness/Kurtosis (Interesting distributions)
            # 排序邏輯：這裡使用 偏度絕對值 + 峰度絕對值 作為 "是否有趣" 的指標
            sorted_cols = sorted(
                results_map.items(),
                key=lambda x: abs(x[1].get("skewness", 0)) if "skewness" in x[1] else 0,
                reverse=True,
            )
            top_5 = dict(sorted_cols[:5])

            summary_note = "系統自動掃描並選取了分佈特徵最顯著的前 5 個欄位。"
            if extreme_outliers:
                outlier_names = ", ".join(
                    [
                        f"{o['parameter']} ({max(o['max_sigma'], abs(o['min_sigma']))}σ)"
                        for o in extreme_outliers[:3]
                    ]
                )
                summary_note = f"⚠️ [CRITICAL] 發現 {len(extreme_outliers)} 個參數出現極端異常 (>6σ)：{outlier_names}..."

            return {
                "scan_mode": "global_auto_detection",
                "scanned_columns_count": len(columns),
                "extreme_outliers_count": len(extreme_outliers),
                "extreme_outliers_list": extreme_outliers,  # Explicit list for LLM
                "top_interesting_distributions": top_5,
                "note": summary_note,
            }

        return {"parameters": columns, "multi_results": results_map}


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

        # 參數兼容性修正：支援 target_segments 或 target
        target_input = params.get("target_segments") or params.get("target")
        # 參數兼容性修正：支援 baseline_segments 或 baseline
        baseline_input = params.get("baseline_segments") or params.get("baseline")

        summary = self.analysis_service.load_summary(session_id, file_id)
        csv_path = self.analysis_service.get_csv_path(session_id, summary["filename"])
        df = pd.read_csv(csv_path)
        numeric_cols = df.select_dtypes(include=[np.number]).columns

        target_indices = self.parse_indices(target_input, max_len=len(df))
        if not target_indices:
            return {"error": f"無法解析目標區間: {target_input}"}

        if baseline_input:
            baseline_indices = self.parse_indices(baseline_input, max_len=len(df))
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
            f"{d['parameter']} ({'偏高' if d['z_score_diff'] > 0 else '偏低'} {abs(d['z_score_diff']):.1f}σ)"
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
        return ["file_id"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        param_input = params.get("parameter")

        summary = self.analysis_service.load_summary(session_id, file_id)

        # 支援全域掃描
        if not param_input or param_input == "all" or param_input == ["all"]:
            summary = self.analysis_service.load_summary(session_id, file_id)
            columns = summary.get("numerical_columns", [])
            if not columns:
                return {"error": "未指定參數且無可用數值欄位。"}
            is_global_scan = True
        elif isinstance(param_input, list):
            columns = param_input
            is_global_scan = False
        elif isinstance(param_input, str):
            columns = [p.strip() for p in param_input.split(",")]
            is_global_scan = False
        else:
            return {"error": "無效的參數類型"}

        summary = self.analysis_service.load_summary(session_id, file_id)
        filename = summary["filename"]
        csv_path = self.analysis_service.get_csv_path(session_id, filename)

        results_map = {}
        for col in columns:
            if not col:
                continue
            try:
                method = params.get("method", "zscore")  # Default to zscore

                # 讀取數據
                df = pd.read_csv(csv_path, usecols=[col])
                series = df[col].dropna()

                if series.empty:
                    results_map[col] = {"error": "Skipped (Empty)"}
                    continue

                # [Robustness] Skip non-numeric columns
                if not pd.api.types.is_numeric_dtype(series):
                    results_map[col] = {"error": "Skipped (Non-Numeric)"}
                    continue

                if method == "iqr":
                    q1 = series.quantile(0.25)
                    q3 = series.quantile(0.75)
                    iqr = q3 - q1
                    lower_bound = q1 - 1.5 * iqr
                    upper_bound = q3 + 1.5 * iqr
                    outliers = series[(series < lower_bound) | (series > upper_bound)]
                    interpretation = f"使用 IQR 方法，在 {len(series)} 筆樣本中發現 {len(outliers)} 個異常點。"
                    stats_data = {
                        "q1": float(q1),
                        "q3": float(q3),
                        "iqr": float(iqr),
                        "mean": float(series.mean()),
                        "std": float(series.std()),
                    }
                else:
                    # Default: Z-Score (支援用戶要求的 |Z|>3 與 |Z|>6)
                    mean = series.mean()
                    std = series.std()  # ddof=1 (pandas default)

                    # [FIX] Low-variance filter: 如果 CV < 0.001 (std/|mean| < 0.1%),
                    # 該參數幾乎是常數, Z-Score 因分母趨近零而虛高,不是真正的異常。
                    # 但仍保留原始 Z 值，僅標記 low_variance 供下游判斷。
                    cv = (
                        abs(std / mean)
                        if mean != 0
                        else (0.0 if std == 0 else float("inf"))
                    )
                    is_low_variance = cv < 0.001 and std > 0

                    if std == 0:
                        z_scores = series * 0
                    else:
                        z_scores = (series - mean) / std

                    abs_z = z_scores.abs()
                    outliers = series[abs_z > 3]
                    extreme_outliers = series[abs_z > 6]
                    max_z = round(float(abs_z.max()), 1) if not abs_z.empty else 0

                    # [FIX] 計算 max_sigma / min_sigma,與 analyze_distribution 格式一致
                    min_val = float(series.min())
                    max_val = float(series.max())
                    max_sigma = (
                        round((max_val - float(mean)) / float(std), 1)
                        if std > 0
                        else 0.0
                    )
                    min_sigma = (
                        round((min_val - float(mean)) / float(std), 1)
                        if std > 0
                        else 0.0
                    )

                    # [FIX] Low-variance parameters: 標記但保留原始 Z 值
                    has_extreme_outlier = abs(max_sigma) > 6 or abs(min_sigma) > 6
                    if is_low_variance:
                        interpretation = (
                            f"[低變異提示] {col} 的 CV={cv:.6f} (<0.001),"
                            f" 標準差={std:.6f}, 均值={mean:.4f}。"
                            f" 此參數變異極低, Z-Score={max_z:.1f} 可能虛高,"
                            f" 請結合工程經驗判斷。"
                        )
                    else:
                        interpretation = f"使用 Z-Score 方法，偵測到 {len(outliers)} 筆顯著異常 (|Z|>3) 與 {len(extreme_outliers)} 筆極端異常 (|Z|>6)。最大 Z 值為 {max_z:.1f}。"

                    stats_data = {
                        "mean": float(mean),
                        "std": float(std),
                        "cv": round(cv, 6),
                        "max_z": max_z,
                        "max_sigma": max_sigma,
                        "min_sigma": min_sigma,
                        "has_extreme_outlier": has_extreme_outlier,
                        "significant_count": len(outliers),
                        "extreme_count": len(extreme_outliers),
                        "low_variance_false_positive": is_low_variance,
                    }

                outlier_count = len(outliers)
                total_count = len(series)
                percentage = (
                    (outlier_count / total_count) * 100 if total_count > 0 else 0
                )

                results_map[col] = {
                    "method": method,
                    "stats": stats_data,
                    "outlier_info": {
                        "count": outlier_count,
                        "percentage": f"{percentage:.2f}%",
                        "is_abnormal": outlier_count > 0,
                        "recent_outliers_preview": outliers.tail(5).tolist()
                        if not outliers.empty
                        else [],
                    },
                    "interpretation": interpretation,
                }
            except Exception as e:
                results_map[col] = {"error": str(e)}

        # 向下相容
        if len(columns) == 1:
            col = columns[0]
            res = results_map.get(col)
            if res and "error" in res:
                return res
            return {"parameter": col, **(res or {})}

        # 如果是全域掃描，回傳異常程度最嚴重的 Top 5 (Severity > Count)
        if hasattr(self, "name") and is_global_scan:
            # [FIX] 低方差假陽性過濾: CV < 0.001 的參數 Z-Score 因分母趨近零而虛高,
            # 不應佔據 Top 5 位置。排序時將其權重歸零。
            def sort_key(item):
                stats = item[1].get("stats", {})
                if not isinstance(stats, dict):
                    return 0
                # 低方差假陽性:權重歸零
                if stats.get("low_variance_false_positive", False):
                    return 0
                return stats.get("max_z", 0)

            sorted_cols = sorted(
                results_map.items(),
                key=sort_key,
                reverse=True,
            )
            top_5 = dict(sorted_cols[:5])

            # 統計被降權的低方差參數數量
            low_var_count = sum(
                1
                for _, v in results_map.items()
                if isinstance(v.get("stats"), dict)
                and v["stats"].get("low_variance_false_positive", False)
            )

            # [Debug Info] Print top 1 to log to confirm Z > 6 exists
            if top_5:
                first_key = list(top_5.keys())[0]
                first_max_z = top_5[first_key].get("stats", {}).get("max_z", 0)
                print(
                    f"[DetectOutliers] Top 1 Anomaly: {first_key} with Max Z={first_max_z}"
                )

            note = "系統自動掃描並選取了 Z-Score (異常程度) 最高的前 5 個欄位。"
            if low_var_count > 0:
                note += f" (已排除 {low_var_count} 個低變異假陽性參數)"

            return {
                "scan_mode": "global_outlier_detection",
                "scanned_columns_count": len(columns),
                "top_abnormal_parameters": top_5,
                "low_variance_excluded_count": low_var_count,
                "note": note,
            }

        return {"parameters": columns, "multi_results": results_map}


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
        elif target_input.lower().strip() == "all":
            # [Fix] target="all" → 自動選取最高方差的前 3 個欄位
            correlations = self.analysis_service.load_correlations(session_id, file_id)
            if correlations:
                # 用平均絕對相關性排序,選出最「有趣」的欄位
                col_scores = {}
                for col, corr_dict in correlations.items():
                    if isinstance(corr_dict, dict):
                        vals = [
                            abs(v)
                            for v in corr_dict.values()
                            if v is not None and isinstance(v, (int, float))
                        ]
                        if vals:
                            col_scores[col] = sum(vals) / len(vals)
                sorted_cols = sorted(
                    col_scores.items(), key=lambda x: x[1], reverse=True
                )
                targets = [col for col, _ in sorted_cols[:3]]
                if not targets:
                    return {
                        "error": "No valid columns found in correlation matrix for global analysis"
                    }
            else:
                return {
                    "error": "Correlation data not available. Please build index first."
                }
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
                        "correlation": round(v, 3),
                    }
                )
            results = results[:top_n]

            multi_results[target] = results

        # --- Collinearity Detection ---
        # Scan top correlated parameters for high inter-correlation (|r| > 0.9)
        collinearity_warnings = []
        try:
            # Collect all unique parameters across all targets
            all_top_params = set()
            for res_list in multi_results.values():
                if isinstance(res_list, list):
                    for item in res_list:
                        all_top_params.add(item["parameter"])

            # Check pairwise correlations among top params
            param_list = list(all_top_params)
            for i in range(len(param_list)):
                for j in range(i + 1, len(param_list)):
                    p_a, p_b = param_list[i], param_list[j]
                    # Look up correlation between p_a and p_b
                    corr_val = None
                    if p_a in correlations and p_b in correlations.get(p_a, {}):
                        corr_val = correlations[p_a].get(p_b)
                    elif p_b in correlations and p_a in correlations.get(p_b, {}):
                        corr_val = correlations[p_b].get(p_a)

                    if corr_val is not None and abs(corr_val) > 0.9:
                        collinearity_warnings.append(
                            {
                                "param_a": p_a,
                                "param_b": p_b,
                                "correlation": round(corr_val, 3),
                                "warning": "高度共線 (|r|>0.9)，可能是同一物理量，調整其一即可",
                            }
                        )
        except Exception:
            pass  # Collinearity detection is best-effort

        # 向下兼容單一目標的輸出格式
        if len(targets) == 1:
            target = targets[0]
            res = multi_results[target]
            if isinstance(res, dict) and "error" in res:
                return res  # Return error dict directly
            result = {"target": target, "top_correlations": res}
            if collinearity_warnings:
                result["collinearity_warnings"] = collinearity_warnings
            return result

        result = {"targets": targets, "multi_target_correlations": multi_results}
        if collinearity_warnings:
            result["collinearity_warnings"] = collinearity_warnings
        return result


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
                        {
                            "param_a": a,
                            "param_b": b,
                            "correlation": round(a_corrs[b], 3),
                        }
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
