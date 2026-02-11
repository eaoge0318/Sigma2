from typing import Dict, Any, List
import logging
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
)
from .helpers import SuggestNextAnalysisTool, ExplainResultTool

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
        "cross_correlation": "analyze_category_correlation",
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

    async def execute_tool(
        self, tool_name: str, params: Dict, session_id: str
    ) -> Dict[str, Any]:
        """統一執行入口 (含工具名稱自動修正)"""
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

            result = tool.execute(params, session_id)
            return result

        except Exception as e:
            logger.error(f"Tool execution failed: {resolved_name}, Error: {e}")
            return {"error": f"Internal execution error: {str(e)}"}
