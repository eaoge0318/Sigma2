"""
Combo Tools — 複合分析工具模組

每個 Combo Tool 內部呼叫多個原子工具, 一次完成多維度分析,
減少 Planner 決策負擔且保證基礎覆蓋。

命名規則: combo_* 前綴
描述標籤: [組合·多參數] 或 [組合·單參數]
"""

import traceback
from typing import Dict, Any, List
from .base import AnalysisTool


# ============================================================
# 1. combo_parameter_profiling — 多參數四合一掃描
# ============================================================
class ComboParameterProfilingTool(AnalysisTool):
    """
    [組合·多參數] 四合一參數掃描
    內含: draw_trend + analyze_distribution + get_top_correlations + detect_outliers
    一次呼叫完成所有 targets 的基礎面貌掃描。
    """

    @property
    def name(self) -> str:
        return "combo_parameter_profiling"

    @property
    def description(self) -> str:
        return (
            "[組合·多參數] 四合一參數掃描 "
            "(趨勢 + 分佈 + 相關性排名 + 異常偵測)，一次涵蓋所有指定參數的基礎分析"
        )

    @property
    def required_params(self) -> List[str]:
        return ["file_id"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        parameters_raw = (
            params.get("parameters")
            or params.get("target_columns")
            or params.get("parameter")
        )

        # --- 解析參數列表 ---
        if isinstance(parameters_raw, list):
            parameters = [p.strip() for p in parameters_raw if p and p.strip()]
        elif isinstance(parameters_raw, str):
            parameters = [p.strip() for p in parameters_raw.split(",") if p.strip()]
        else:
            # Fallback: 掃描所有數值欄位
            summary = self.analysis_service.load_summary(session_id, file_id)
            parameters = summary.get("numerical_columns", [])[:10]

        if not parameters:
            return {"error": "未指定分析參數 (parameters)"}

        results = {
            "tool": "combo_parameter_profiling",
            "parameters_analyzed": parameters,
            "sub_analyses": {},
        }

        # --- 子工具: draw_trend (趨勢觀察) ---
        try:
            from .data_query import GetTimeSeriesDataTool

            trend_tool = GetTimeSeriesDataTool(self.analysis_service)
            for param in parameters:
                trend_result = trend_tool.execute(
                    {"file_id": file_id, "parameter": param},
                    session_id,
                )
                results["sub_analyses"].setdefault(param, {})["trend"] = (
                    _summarize_trend(trend_result)
                )
        except Exception as e:
            results["sub_analyses"]["_trend_error"] = str(e)
            print(f"[ComboProfiler] Trend error: {e}")

        # --- 子工具: analyze_distribution (分佈形態) ---
        try:
            from .statistics import AnalyzeDistributionTool

            dist_tool = AnalyzeDistributionTool(self.analysis_service)
            for param in parameters:
                dist_result = dist_tool.execute(
                    {"file_id": file_id, "parameter": param},
                    session_id,
                )
                results["sub_analyses"].setdefault(param, {})["distribution"] = (
                    _summarize_distribution(dist_result)
                )
        except Exception as e:
            results["sub_analyses"]["_distribution_error"] = str(e)
            print(f"[ComboProfiler] Distribution error: {e}")

        # --- 子工具: get_top_correlations (相關性排名) ---
        try:
            from .statistics import GetTopCorrelationsTool

            corr_tool = GetTopCorrelationsTool(self.analysis_service)
            for param in parameters:
                corr_result = corr_tool.execute(
                    {"file_id": file_id, "target": param, "top_k": 5},
                    session_id,
                )
                results["sub_analyses"].setdefault(param, {})["correlations"] = (
                    _summarize_correlations(corr_result)
                )
        except Exception as e:
            results["sub_analyses"]["_correlation_error"] = str(e)
            print(f"[ComboProfiler] Correlation error: {e}")

        # --- 子工具: detect_outliers (異常偵測) ---
        try:
            from .statistics import DetectOutliersTool

            outlier_tool = DetectOutliersTool(self.analysis_service)
            for param in parameters:
                outlier_result = outlier_tool.execute(
                    {"file_id": file_id, "parameter": param, "method": "zscore"},
                    session_id,
                )
                results["sub_analyses"].setdefault(param, {})["outliers"] = (
                    _summarize_outliers(outlier_result)
                )
        except Exception as e:
            results["sub_analyses"]["_outlier_error"] = str(e)
            print(f"[ComboProfiler] Outlier error: {e}")

        # --- 交叉分析摘要 (多參數才做) ---
        if len(parameters) >= 2:
            results["cross_analysis"] = _build_cross_summary(
                results["sub_analyses"], parameters
            )

        return results


# ============================================================
# 2. combo_anomaly_diagnosis — 異常深度診斷
# ============================================================
class ComboAnomalyDiagnosisTool(AnalysisTool):
    """
    [組合·單參數] 異常深度診斷
    內含: classify_anomaly_type + find_temporal_patterns + frequency_analysis
    針對單一參數進行完整的異常機制識別。
    """

    @property
    def name(self) -> str:
        return "combo_anomaly_diagnosis"

    @property
    def description(self) -> str:
        return (
            "[組合·單參數] 異常深度診斷 "
            "(異常類型分類 + 時序穩定性分析 + 頻域分析)，深入識別異常的具體機制"
        )

    @property
    def required_params(self) -> List[str]:
        return ["file_id"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        parameter = params.get("parameter") or (
            params.get("target_columns", [None])[0]
            if isinstance(params.get("target_columns"), list)
            else params.get("target_columns")
        )
        focus_range = params.get("focus_range")

        if not parameter or parameter == "all":
            return {"error": "combo_anomaly_diagnosis 需要指定單一參數 (parameter)"}

        results = {
            "tool": "combo_anomaly_diagnosis",
            "parameter": parameter,
            "focus_range": focus_range,
            "sub_analyses": {},
        }

        # --- 子工具: classify_anomaly_type ---
        try:
            from .anomaly_classifier import AnomalyClassifierTool

            cls_tool = AnomalyClassifierTool(self.analysis_service)
            cls_params = {"file_id": file_id, "parameter": parameter}
            if focus_range:
                cls_params["focus_range"] = focus_range
            cls_result = cls_tool.execute(cls_params, session_id)
            results["sub_analyses"]["anomaly_classification"] = cls_result
        except Exception as e:
            results["sub_analyses"]["anomaly_classification"] = {"error": str(e)}
            print(f"[ComboDiagnosis] Anomaly classification error: {e}")

        # --- 子工具: find_temporal_patterns ---
        try:
            from .patterns import FindTemporalPatternsTool

            pat_tool = FindTemporalPatternsTool(self.analysis_service)
            pat_result = pat_tool.execute(
                {"file_id": file_id, "parameter": parameter}, session_id
            )
            results["sub_analyses"]["temporal_patterns"] = pat_result
        except Exception as e:
            results["sub_analyses"]["temporal_patterns"] = {"error": str(e)}
            print(f"[ComboDiagnosis] Temporal patterns error: {e}")

        # --- 子工具: frequency_analysis ---
        try:
            from .frequency_analysis import FrequencyAnalysisTool

            freq_tool = FrequencyAnalysisTool(self.analysis_service)
            freq_params = {"file_id": file_id, "parameter": parameter}
            if focus_range:
                freq_params["focus_range"] = focus_range
            freq_result = freq_tool.execute(freq_params, session_id)
            results["sub_analyses"]["frequency_analysis"] = freq_result
        except Exception as e:
            results["sub_analyses"]["frequency_analysis"] = {"error": str(e)}
            print(f"[ComboDiagnosis] Frequency analysis error: {e}")

        # --- 綜合診斷摘要 ---
        results["diagnosis_summary"] = _build_diagnosis_summary(results["sub_analyses"])

        return results


# ============================================================
# 3. combo_optimization — 最佳化全流程
# ============================================================
class ComboOptimizationTool(AnalysisTool):
    """
    [組合·單參數] 最佳化全流程
    內含: performance_segmentation + analyze_feature_importance + generate_operating_window
    一次完成好壞批分割、因子排名、SOP 建議。
    """

    @property
    def name(self) -> str:
        return "combo_optimization"

    @property
    def description(self) -> str:
        return (
            "[組合·單參數] 最佳化全流程 "
            "(好壞批分割 + 因子排名 + SOP 建議表)，一站式產出優化方案"
        )

    @property
    def required_params(self) -> List[str]:
        return ["file_id"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        target = (
            params.get("target")
            or params.get("parameter")
            or (
                params.get("target_columns", [None])[0]
                if isinstance(params.get("target_columns"), list)
                else params.get("target_columns")
            )
        )

        if not target or target == "all":
            return {"error": "combo_optimization 需要指定目標參數 (target)"}

        results = {
            "tool": "combo_optimization",
            "target": target,
            "sub_analyses": {},
        }

        # --- 子工具: performance_segmentation ---
        try:
            from .performance_segmentation import PerformanceSegmentationTool

            seg_tool = PerformanceSegmentationTool(self.analysis_service)
            seg_result = seg_tool.execute(
                {"file_id": file_id, "target": target}, session_id
            )
            results["sub_analyses"]["performance_segmentation"] = seg_result
        except Exception as e:
            results["sub_analyses"]["performance_segmentation"] = {"error": str(e)}
            print(f"[ComboOptimization] Segmentation error: {e}")

        # --- 子工具: analyze_feature_importance ---
        try:
            from .advanced_ai import FeatureImportanceWorkflowTool

            fi_tool = FeatureImportanceWorkflowTool(self.analysis_service)
            fi_result = fi_tool.execute(
                {"file_id": file_id, "target": target}, session_id
            )
            results["sub_analyses"]["feature_importance"] = fi_result
        except Exception as e:
            results["sub_analyses"]["feature_importance"] = {"error": str(e)}
            print(f"[ComboOptimization] Feature importance error: {e}")

        # --- 子工具: generate_operating_window ---
        try:
            from .performance_segmentation import OperatingWindowTool

            ow_tool = OperatingWindowTool(self.analysis_service)
            ow_result = ow_tool.execute(
                {"file_id": file_id, "target": target}, session_id
            )
            results["sub_analyses"]["operating_window"] = ow_result
        except Exception as e:
            results["sub_analyses"]["operating_window"] = {"error": str(e)}
            print(f"[ComboOptimization] Operating window error: {e}")

        # --- 綜合優化摘要 ---
        results["optimization_summary"] = _build_optimization_summary(
            results["sub_analyses"]
        )

        return results


# ============================================================
# 4. combo_causal_tracing — 因果鏈追蹤
# ============================================================
class ComboCausalTracingTool(AnalysisTool):
    """
    [組合·單參數] 因果鏈追蹤
    內含: cross_correlation_lag + causal_relationship_analysis + event_sequence_analysis
    從統計相關到因果驗證的完整鏈路。
    """

    @property
    def name(self) -> str:
        return "combo_causal_tracing"

    @property
    def description(self) -> str:
        return (
            "[組合·單參數] 因果鏈追蹤 "
            "(Lead-Lag 交叉相關 + Granger 因果檢定 + 事件序列分析)，完整追蹤因果關係"
        )

    @property
    def required_params(self) -> List[str]:
        return ["file_id"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        target = (
            params.get("target")
            or params.get("parameter")
            or (
                params.get("target_columns", [None])[0]
                if isinstance(params.get("target_columns"), list)
                else params.get("target_columns")
            )
        )
        reference = params.get("reference") or params.get("reference_parameters")

        if not target or target == "all":
            return {"error": "combo_causal_tracing 需要指定目標參數 (target)"}

        results = {
            "tool": "combo_causal_tracing",
            "target": target,
            "reference": reference,
            "sub_analyses": {},
        }

        # --- 子工具: cross_correlation_lag ---
        try:
            from .cross_correlation import CrossCorrelationLagTool

            cc_tool = CrossCorrelationLagTool(self.analysis_service)
            cc_params = {"file_id": file_id, "target": target}
            if reference:
                cc_params["reference"] = (
                    reference if isinstance(reference, str) else reference[0]
                )
            cc_result = cc_tool.execute(cc_params, session_id)
            results["sub_analyses"]["cross_correlation_lag"] = cc_result
        except Exception as e:
            results["sub_analyses"]["cross_correlation_lag"] = {"error": str(e)}
            print(f"[ComboCausal] Cross correlation error: {e}")

        # --- 子工具: causal_relationship_analysis ---
        try:
            from .deep_diagnostics import CausalRelationshipTool

            cr_tool = CausalRelationshipTool(self.analysis_service)
            cr_params = {"file_id": file_id, "target_parameter": target}
            if reference:
                cr_params["reference_parameters"] = (
                    reference if isinstance(reference, list) else [reference]
                )
            cr_result = cr_tool.execute(cr_params, session_id)
            results["sub_analyses"]["causal_relationship"] = cr_result
        except Exception as e:
            results["sub_analyses"]["causal_relationship"] = {"error": str(e)}
            print(f"[ComboCausal] Causal relationship error: {e}")

        # --- 子工具: event_sequence_analysis ---
        try:
            from .event_sequence_analysis import EventSequenceAnalysisTool

            es_tool = EventSequenceAnalysisTool(self.analysis_service)
            es_result = es_tool.execute(
                {"file_id": file_id, "target": target}, session_id
            )
            results["sub_analyses"]["event_sequence"] = es_result
        except Exception as e:
            results["sub_analyses"]["event_sequence"] = {"error": str(e)}
            print(f"[ComboCausal] Event sequence error: {e}")

        # --- 綜合因果摘要 ---
        results["causal_summary"] = _build_causal_summary(results["sub_analyses"])

        return results


# ============================================================
# Helper Functions — 結果摘要提取
# ============================================================


def _summarize_trend(result: Dict) -> Dict:
    """從 draw_trend 結果提取摘要"""
    if not isinstance(result, dict) or "error" in result:
        return result
    return {
        "data_points": result.get("total_points", 0),
        "has_chart": "chart_data" in result or "time_series" in result,
    }


def _summarize_distribution(result: Dict) -> Dict:
    """從 analyze_distribution 結果提取摘要"""
    if not isinstance(result, dict) or "error" in result:
        return result
    # 嘗試從 results_map 或直接結果提取
    if "results" in result and isinstance(result["results"], dict):
        # 多參數結果格式
        summary = {}
        for param, data in result["results"].items():
            if isinstance(data, dict):
                summary[param] = {
                    "normality": data.get("normality_test", {}).get("is_normal"),
                    "skewness": data.get("skewness"),
                    "kurtosis": data.get("kurtosis"),
                    "mean": data.get("stats", {}).get("mean"),
                    "std": data.get("stats", {}).get("std"),
                }
        return summary
    return {
        "normality": result.get("normality_test", {}).get("is_normal"),
        "skewness": result.get("skewness"),
        "kurtosis": result.get("kurtosis"),
    }


def _summarize_correlations(result: Dict) -> Dict:
    """從 get_top_correlations 結果提取摘要"""
    if not isinstance(result, dict) or "error" in result:
        return result
    top_corrs = result.get("top_correlations", [])
    if isinstance(top_corrs, list):
        return {
            "top_3": [
                {
                    "parameter": c.get("parameter", ""),
                    "correlation": round(c.get("correlation", 0), 3),
                }
                for c in top_corrs[:3]
                if isinstance(c, dict)
            ]
        }
    return result


def _summarize_outliers(result: Dict) -> Dict:
    """從 detect_outliers 結果提取摘要"""
    if not isinstance(result, dict) or "error" in result:
        return result
    # 處理多參數結果 (results_map 格式)
    if "results" in result and isinstance(result["results"], dict):
        summary = {}
        for param, data in result["results"].items():
            if isinstance(data, dict):
                summary[param] = {
                    "outlier_count": data.get("outlier_count", 0),
                    "max_z_score": data.get("max_z_score", 0),
                    "has_extreme": data.get("has_extreme_outlier", False),
                }
        return summary
    return {
        "outlier_count": result.get("outlier_count", 0),
        "max_z_score": result.get("max_z_score", 0),
        "has_extreme": result.get("has_extreme_outlier", False),
    }


def _build_cross_summary(sub_analyses: Dict, parameters: List[str]) -> Dict:
    """構建多參數交叉分析摘要"""
    cross = {
        "parameter_count": len(parameters),
        "shared_correlations": [],
        "anomaly_comparison": {},
    }
    # 比較各參數的 Top 相關因子是否有重疊
    all_top_factors = {}
    for param in parameters:
        param_data = sub_analyses.get(param, {})
        corr_data = param_data.get("correlations", {})
        if isinstance(corr_data, dict) and "top_3" in corr_data:
            factors = [c["parameter"] for c in corr_data["top_3"]]
            all_top_factors[param] = set(factors)

    # 找出被多個 targets 共同關聯的因子
    if len(all_top_factors) >= 2:
        factor_counts = {}
        for param, factors in all_top_factors.items():
            for f in factors:
                if f not in parameters:  # 排除 targets 本身
                    factor_counts.setdefault(f, []).append(param)
        cross["shared_correlations"] = [
            {"factor": f, "related_targets": targets}
            for f, targets in factor_counts.items()
            if len(targets) >= 2
        ]

    # 各參數異常狀態比較
    for param in parameters:
        param_data = sub_analyses.get(param, {})
        outlier_data = param_data.get("outliers", {})
        if isinstance(outlier_data, dict):
            cross["anomaly_comparison"][param] = {
                "outlier_count": outlier_data.get("outlier_count", 0),
                "has_extreme": outlier_data.get("has_extreme", False),
            }

    return cross


def _build_diagnosis_summary(sub_analyses: Dict) -> Dict:
    """構建異常診斷綜合摘要"""
    summary = {
        "anomaly_types": [],
        "has_periodicity": False,
        "dominant_frequency": None,
    }

    # 異常分類結果
    cls_result = sub_analyses.get("anomaly_classification", {})
    if isinstance(cls_result, dict) and "segments" in cls_result:
        for seg in cls_result.get("segments", []):
            if isinstance(seg, dict):
                summary["anomaly_types"].append(seg.get("type", "UNKNOWN"))
    elif isinstance(cls_result, dict) and "anomaly_type" in cls_result:
        summary["anomaly_types"].append(cls_result["anomaly_type"])

    # 頻域分析結果
    freq_result = sub_analyses.get("frequency_analysis", {})
    if isinstance(freq_result, dict):
        summary["has_periodicity"] = freq_result.get("has_significant_frequency", False)
        dominant = freq_result.get("dominant_frequency")
        if dominant:
            summary["dominant_frequency"] = dominant

    return summary


def _build_optimization_summary(sub_analyses: Dict) -> Dict:
    """構建優化流程摘要"""
    summary = {
        "segmentation_success": False,
        "top_factors_count": 0,
        "has_operating_window": False,
    }

    seg_result = sub_analyses.get("performance_segmentation", {})
    if isinstance(seg_result, dict) and "error" not in seg_result:
        summary["segmentation_success"] = True

    fi_result = sub_analyses.get("feature_importance", {})
    if isinstance(fi_result, dict):
        rankings = fi_result.get("importance_ranking", [])
        if isinstance(rankings, list):
            summary["top_factors_count"] = len(rankings)

    ow_result = sub_analyses.get("operating_window", {})
    if isinstance(ow_result, dict) and "error" not in ow_result:
        summary["has_operating_window"] = True

    return summary


def _build_causal_summary(sub_analyses: Dict) -> Dict:
    """構建因果鏈追蹤摘要"""
    summary = {
        "lead_lag_detected": False,
        "granger_significant": False,
        "event_triggers_found": 0,
    }

    cc_result = sub_analyses.get("cross_correlation_lag", {})
    if isinstance(cc_result, dict) and "best_lag" in cc_result:
        if cc_result.get("best_lag", 0) != 0:
            summary["lead_lag_detected"] = True
            summary["best_lag"] = cc_result["best_lag"]

    cr_result = sub_analyses.get("causal_relationship", {})
    if isinstance(cr_result, dict):
        # 檢查是否有顯著的 Granger 因果
        for key, val in cr_result.items():
            if isinstance(val, dict) and val.get("p_value", 1.0) < 0.05:
                summary["granger_significant"] = True
                break

    es_result = sub_analyses.get("event_sequence", {})
    if isinstance(es_result, dict):
        triggers = es_result.get("significant_triggers", [])
        if isinstance(triggers, list):
            summary["event_triggers_found"] = len(triggers)

    return summary
