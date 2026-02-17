from typing import Dict, Any, List
from concurrent.futures import ThreadPoolExecutor
import logging
import asyncio

# Dedicated thread pool for analysis tools (isolated from FastAPI's default pool)
_ANALYSIS_POOL = ThreadPoolExecutor(max_workers=3, thread_name_prefix="analysis")
from .base import AnalysisTool
from .data_query import (
    GetParameterListTool,
    GetDataOverviewTool,
    SearchParametersTool,
    GetTimeSeriesDataTool,
)
from .statistics import (
    AnalyzeDistributionTool,
    DetectOutliersTool,
    GetTopCorrelationsTool,
    AnalyzeCategoryCorrelationTool,
    GetCorrelationMatrixTool,
    CompareSegmentsTool,
)
from .advanced_ai import (
    MultivariateAnomalyTool,
    FeatureImportanceWorkflowTool,
    PrincipalComponentAnalysisTool,
    HotellingT2AnalysisTool,
)
from .patterns import FindTemporalPatternsTool, FindEventPatternsTool
from .deep_diagnostics import (
    DistributionShiftTool,
    LocalOutlierFactorTool,
    CausalRelationshipTool,
    AnalyzeResidualsTool,
)
from .helpers import SuggestNextAnalysisTool, ExplainResultTool
from .anomaly_classifier import AnomalyClassifierTool
from .cross_correlation import CrossCorrelationLagTool
from .frequency_analysis import FrequencyAnalysisTool
from .control_assessment import ControlLoopAssessmentTool
from .performance_segmentation import PerformanceSegmentationTool, OperatingWindowTool
from .interaction_analysis import InteractionScatterTool, InteractionEffectTestTool
from .partial_dependence import PartialDependenceTool
from .correlation_network import CorrelationNetworkTool
from .cv_ranking import CVRankingTool
from .regime_detection import RegimeDetectionTool
from .multi_objective import MultiObjectiveTool
from .batch_aggregation import BatchAggregationTool
from .wavelet_analysis import WaveletAnalysisTool
from .parallel_coordinates import ParallelCoordinatesTool
from .radar_chart import RadarChartTool
from .event_sequence_analysis import EventSequenceAnalysisTool
from .stratified_interaction import StratifiedInteractionTool

logger = logging.getLogger(__name__)


class ToolExecutor:
    """
    工具執行器
    負責管理所有分析工具的實例化與調用
    包含別名容錯機制，防止 LLM 臆造工具名導致分析中斷
    """

    # --- 工具名稱別名映射表 (LLM 常見臆造名 -> 正確工具名) ---
    TOOL_ALIASES: Dict[str, str] = {
        # 相關性分析系列 (最常見的臆造)
        "analyze_correlation": "get_correlation_matrix",
        "correlation_analysis": "get_correlation_matrix",
        "calculate_correlation": "get_correlation_matrix",
        "compute_correlation": "get_correlation_matrix",
        "cross_correlation": "cross_correlation_lag",
        "find_correlations": "get_top_correlations",
        "top_correlations": "get_top_correlations",
        # 分佈分析系列
        "distribution_analysis": "analyze_distribution",
        "get_distribution": "analyze_distribution",
        # 異常偵測系列
        "outlier_detection": "detect_outliers",
        "find_outliers": "detect_outliers",
        "anomaly_detection": "multivariate_anomaly_detection",
        "detect_anomalies": "multivariate_anomaly_detection",
        # 特徵重要性系列
        "feature_importance": "analyze_feature_importance",
        "get_feature_importance": "analyze_feature_importance",
        # 時間序列系列
        "get_time_series": "get_time_series_data",
        "time_series_data": "get_time_series_data",
        "plot_trend": "get_time_series_data",
        # PCA 系列
        "pca_analysis": "systemic_pca_analysis",
        "principal_component_analysis": "systemic_pca_analysis",
        # Hotelling 系列
        "hotelling_analysis": "hotelling_t2_analysis",
        "hotelling_t2": "hotelling_t2_analysis",
        "t2_analysis": "hotelling_t2_analysis",
        # 區間比較系列
        "compare_segments": "compare_data_segments",
        "segment_comparison": "compare_data_segments",
        # 因果分析系列
        "causal_analysis": "causal_relationship_analysis",
        # 參數清單系列
        "list_parameters": "get_parameter_list",
        "get_columns": "get_parameter_list",
        # 搜索系列
        "search_parameters": "search_parameters_by_concept",
        "find_parameters": "search_parameters_by_concept",
        # 殘差分析系列
        "residual_analysis": "analyze_residuals",
        "check_residuals": "analyze_residuals",
        "analyze_hidden_anomalies": "analyze_residuals",
        # 進階診斷系列 (新工具)
        "anomaly_classification": "classify_anomaly_type",
        "classify_anomaly": "classify_anomaly_type",
        "anomaly_type": "classify_anomaly_type",
        "cross_correlation_analysis": "cross_correlation_lag",
        "lag_analysis": "cross_correlation_lag",
        "lead_lag": "cross_correlation_lag",
        "psd_analysis": "frequency_analysis",
        "spectral_analysis": "frequency_analysis",
        "power_spectral_density": "frequency_analysis",
        "control_assessment": "control_loop_assessment",
        "harris_index": "control_loop_assessment",
        "pid_assessment": "control_loop_assessment",
        # 效能分析與優化系列
        "segment_by_performance": "performance_segmentation",
        "golden_batch_analysis": "performance_segmentation",
        "batch_comparison": "performance_segmentation",
        "operating_window": "generate_operating_window",
        "sop_recommendation": "generate_operating_window",
        "golden_batch_profile": "generate_operating_window",
        "scatter_plot": "interaction_scatter",
        "interaction_plot": "interaction_scatter",
        "sweet_spot_analysis": "interaction_scatter",
        # 交互效應檢定系列
        "interaction_test": "interaction_effect_test",
        "two_way_anova": "interaction_effect_test",
        "interaction_analysis": "interaction_effect_test",
        "anova_interaction": "interaction_effect_test",
        "pdp_analysis": "partial_dependence",
        "marginal_effect": "partial_dependence",
        "partial_dependence_plot": "partial_dependence",
        # 系統級分析系列
        "network_analysis": "correlation_network",
        "hub_analysis": "correlation_network",
        "centrality_analysis": "correlation_network",
        "parameter_network": "correlation_network",
        "volatility_ranking": "cv_ranking",
        "stability_ranking": "cv_ranking",
        "coefficient_of_variation": "cv_ranking",
        "cluster_analysis": "regime_detection",
        "operating_regime": "regime_detection",
        "kmeans_clustering": "regime_detection",
        "mode_detection": "regime_detection",
        # 多目標優化系列
        "multi_target_optimization": "multi_objective_analysis",
        "pareto_analysis": "multi_objective_analysis",
        "tradeoff_analysis": "multi_objective_analysis",
        "synergy_analysis": "multi_objective_analysis",
        # 批次聚合分析系列
        "batch_analysis": "batch_aggregation",
        "segment_aggregation": "batch_aggregation",
        "group_analysis": "batch_aggregation",
        "region_analysis": "batch_aggregation",
        # 小波/時頻分析系列
        "wavelet_transform": "wavelet_analysis",
        "cwt_analysis": "wavelet_analysis",
        "time_frequency_analysis": "wavelet_analysis",
        "stft_analysis": "wavelet_analysis",
        "spectrogram": "wavelet_analysis",
        # 多變量可視化系列
        "parallel_coordinate_plot": "parallel_coordinates",
        "parallel_coords": "parallel_coordinates",
        "multivariate_plot": "parallel_coordinates",
        "radar_plot": "radar_chart",
        "spider_chart": "radar_chart",
        "radar_comparison": "radar_chart",
        # 事件序列 + 分層交互系列
        "event_association": "event_sequence_analysis",
        "event_anomaly_correlation": "event_sequence_analysis",
        "temporal_event_analysis": "event_sequence_analysis",
        "batch_interaction": "stratified_interaction",
        "stratified_anova": "stratified_interaction",
        "segment_interaction": "stratified_interaction",
    }

    def __init__(self, analysis_service):
        self.analysis_service = analysis_service
        self.tools: Dict[str, AnalysisTool] = {}
        self._register_tools()

    def _register_tools(self):
        """註冊所有可用工具"""
        tool_classes = [
            # Data Query
            GetParameterListTool,
            GetDataOverviewTool,
            SearchParametersTool,
            GetTimeSeriesDataTool,
            # Statistics
            AnalyzeDistributionTool,
            DetectOutliersTool,
            GetTopCorrelationsTool,
            AnalyzeCategoryCorrelationTool,
            GetCorrelationMatrixTool,
            CompareSegmentsTool,
            # Advanced AI Workflows
            MultivariateAnomalyTool,
            FeatureImportanceWorkflowTool,
            PrincipalComponentAnalysisTool,
            HotellingT2AnalysisTool,
            # Patterns
            FindTemporalPatternsTool,
            FindEventPatternsTool,
            # Deep Diagnostics
            DistributionShiftTool,
            LocalOutlierFactorTool,
            CausalRelationshipTool,
            AnalyzeResidualsTool,
            # Advanced Diagnostics
            AnomalyClassifierTool,
            CrossCorrelationLagTool,
            FrequencyAnalysisTool,
            ControlLoopAssessmentTool,
            # Performance & Optimization
            PerformanceSegmentationTool,
            OperatingWindowTool,
            InteractionScatterTool,
            InteractionEffectTestTool,
            PartialDependenceTool,
            # System-Level Analysis
            CorrelationNetworkTool,
            CVRankingTool,
            RegimeDetectionTool,
            # Multi-Objective Optimization
            MultiObjectiveTool,
            # Batch/Region Analysis
            BatchAggregationTool,
            # Time-Frequency Analysis
            WaveletAnalysisTool,
            # Multivariate Visualization
            ParallelCoordinatesTool,
            RadarChartTool,
            # Event Sequence + Stratified Interaction
            EventSequenceAnalysisTool,
            StratifiedInteractionTool,
            # Helpers
            SuggestNextAnalysisTool,
            ExplainResultTool,
        ]

        for tool_cls in tool_classes:
            tool_instance = tool_cls(self.analysis_service)
            self.tools[tool_instance.name] = tool_instance

    def _resolve_tool_name(self, name: str) -> str:
        """
        工具名稱解析器：精確匹配 -> 別名映射 -> 模糊匹配
        確保 LLM 臆造的工具名能被正確導向
        """
        # 1. 精確匹配
        if name in self.tools:
            return name

        # 2. 別名映射 (O(1) 查表)
        if name in self.TOOL_ALIASES:
            resolved = self.TOOL_ALIASES[name]
            logger.warning(
                f"[Tool Alias] LLM 使用了不存在的工具名 '{name}'，已自動修正為 '{resolved}'"
            )
            return resolved

        # 3. 模糊匹配 (基於關鍵字相似度，作為最後防線)
        name_lower = name.lower().replace("_", "").replace("-", "")
        best_match = None
        best_score = 0
        for registered_name in self.tools:
            reg_lower = registered_name.lower().replace("_", "").replace("-", "")
            # 計算共同子串長度作為簡單相似度
            common = sum(1 for c in name_lower if c in reg_lower)
            score = common / max(len(name_lower), len(reg_lower))
            if score > best_score and score > 0.6:  # 門檻 60% 相似度
                best_score = score
                best_match = registered_name

        if best_match:
            logger.warning(
                f"[Tool Fuzzy Match] LLM 使用了不存在的工具名 '{name}'，"
                f"模糊匹配到 '{best_match}' (相似度: {best_score:.0%})"
            )
            return best_match

        # 4. 完全無法匹配
        return name

    def get_tool(self, name: str) -> AnalysisTool:
        """獲取指定工具 (含自動修正)"""
        resolved_name = self._resolve_tool_name(name)
        return self.tools.get(resolved_name)

    def list_tools(self) -> List[Dict[str, str]]:
        """列出所有可用工具描述"""
        return [
            {"name": t.name, "description": t.description, "params": t.required_params}
            for t in self.tools.values()
        ]

    @staticmethod
    def _normalize_params(
        params: Dict[str, Any], tool_name: str = ""
    ) -> Dict[str, Any]:
        """
        參數名稱正規化：將 AI 端的語意化參數名映射為工具端的內部參數名。
        根據 tool_name 做上下文感知的映射。

        AI 使用:
          - target_index  -> 資料列 (第幾筆/片)
          - target_column -> 欄位名  (哪個感測器，支援逗號分隔多欄位)
        工具使用 (各工具不同):
          - target_segments / row_index          -> 資料列
          - target                               -> 欄位名 (get_top_correlations, analyze_feature_importance)
          - parameter                            -> 欄位名 (analyze_distribution, detect_outliers)
          - target_parameter + reference_parameters -> 欄位名 (causal_relationship_analysis)
        """
        normalized = dict(params)

        # target_index → target_segments + row_index (向後相容)
        if "target_index" in normalized:
            val = normalized.pop("target_index")
            if "target_segments" not in normalized:
                normalized["target_segments"] = val
            if "row_index" not in normalized:
                normalized["row_index"] = val

        # target_column → 根據工具做不同映射
        if "target_column" in normalized:
            val = normalized.pop("target_column")

            if tool_name == "causal_relationship_analysis":
                # 因果分析工具：第一個欄位 → target_parameter，其餘 → reference_parameters
                if isinstance(val, str) and "," in val:
                    parts = [p.strip() for p in val.split(",") if p.strip()]
                    if "target_parameter" not in normalized:
                        normalized["target_parameter"] = parts[0]
                    if "reference_parameters" not in normalized and len(parts) > 1:
                        normalized["reference_parameters"] = parts[1:]
                else:
                    if "target_parameter" not in normalized:
                        normalized["target_parameter"] = val
            else:
                # 通用映射：target + parameter
                if "target" not in normalized:
                    normalized["target"] = val
                if "parameter" not in normalized:
                    normalized["parameter"] = val

        # Causal tool fallback: LLM often sends "target" instead of "target_parameter"
        if tool_name == "causal_relationship_analysis":
            if "target_parameter" not in normalized and "target" in normalized:
                normalized["target_parameter"] = normalized.pop("target")

        return normalized

    async def execute_tool(
        self, tool_name: str, params: Dict, session_id: str
    ) -> Dict[str, Any]:
        """統一執行入口 (含工具名稱自動修正 + 參數正規化)"""
        if not tool_name or tool_name == "None":
            return {
                "error": "Invalid tool name provided. If you have finished, use 'summarize' or finish your monologue with a conclusion."
            }

        # 先解析工具名稱 (別名/模糊匹配)
        resolved_name = self._resolve_tool_name(tool_name)
        tool = self.tools.get(resolved_name)

        if not tool:
            available = ", ".join(sorted(self.tools.keys()))
            return {
                "error": f"Tool '{tool_name}' not found. Available tools: {available}"
            }

        try:
            # 參數正規化 (根據工具做上下文感知映射)
            params = self._normalize_params(params, resolved_name)

            # 參數驗證
            if not tool.validate_params(params):
                missing = [p for p in tool.required_params if p not in params]
                return {"error": f"Missing required parameters: {missing}"}

            # 如果工具名被修正過，記錄日誌
            if resolved_name != tool_name:
                logger.info(
                    f"Executing tool: {resolved_name} (original: {tool_name}) for session: {session_id}"
                )
            else:
                logger.info(f"Executing tool: {tool_name} for session: {session_id}")

            # Execute in dedicated thread pool to avoid blocking other API endpoints
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                _ANALYSIS_POOL, tool.execute, params, session_id
            )
            return result

        except Exception as e:
            logger.error(f"Tool execution failed: {resolved_name}, Error: {e}")
            return {"error": f"Internal execution error: {str(e)}"}
