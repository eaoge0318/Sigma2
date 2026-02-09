from typing import Dict, Any, List, Optional
from .base import AnalysisTool

# 導入所有工具
from .data_query import (
    GetParameterListTool,
    GetParameterStatisticsTool,
    SearchParametersByConceptTool,
    GetDataOverviewTool,
    GetTimeSeriesDataTool,
)
from .statistics import (
    CalculateCorrelationTool,
    GetTopCorrelationsTool,
    CompareGroupsTool,
    DetectOutliersTool,
    AnalyzeDistributionTool,
    PerformRegressionTool,
)
from .patterns import (
    FindTemporalPatternsTool,
    FindEventPatternsTool,
    ClusterAnalysisTool,
    FindAssociationRulesTool,
)
from .helpers import ExplainResultTool, SuggestNextAnalysisTool, AskClarificationTool


class ToolExecutor:
    """
    工具執行器
    負責管理和執行所有分析工具
    """

    def __init__(self, analysis_service):
        self.analysis_service = analysis_service
        self.tools = self._register_tools()

    def _register_tools(self) -> Dict[str, AnalysisTool]:
        """註冊所有分析工具"""
        return {
            # 查詢工具 (5個)
            "get_parameter_list": GetParameterListTool(self.analysis_service),
            "get_parameter_statistics": GetParameterStatisticsTool(
                self.analysis_service
            ),
            "search_parameters_by_concept": SearchParametersByConceptTool(
                self.analysis_service
            ),
            "get_data_overview": GetDataOverviewTool(self.analysis_service),
            "get_time_series_data": GetTimeSeriesDataTool(self.analysis_service),
            # 統計工具 (6個)
            "calculate_correlation": CalculateCorrelationTool(self.analysis_service),
            "get_top_correlations": GetTopCorrelationsTool(self.analysis_service),
            "compare_groups": CompareGroupsTool(self.analysis_service),
            "detect_outliers": DetectOutliersTool(self.analysis_service),
            "analyze_distribution": AnalyzeDistributionTool(self.analysis_service),
            "perform_regression": PerformRegressionTool(self.analysis_service),
            # 模式工具 (4個)
            "find_temporal_patterns": FindTemporalPatternsTool(self.analysis_service),
            "find_event_patterns": FindEventPatternsTool(self.analysis_service),
            "cluster_analysis": ClusterAnalysisTool(self.analysis_service),
            "find_association_rules": FindAssociationRulesTool(self.analysis_service),
            # 輔助工具 (3個)
            "explain_result": ExplainResultTool(self.analysis_service),
            "suggest_next_analysis": SuggestNextAnalysisTool(self.analysis_service),
            "ask_clarification": AskClarificationTool(self.analysis_service),
        }

    def execute_tool(
        self, tool_name: str, params: Dict[str, Any], session_id: str
    ) -> Dict[str, Any]:
        """執行指定工具"""
        tool = self.tools.get(tool_name)
        if not tool:
            return {"error": f"Tool not found: {tool_name}"}

        # 驗證參數
        missing = tool.validate_params(params)
        if missing:
            return {"error": f"Missing required parameters: {', '.join(missing)}"}

        try:
            return tool.execute(params, session_id)
        except Exception as e:
            return {"error": f"Tool execution failed: {str(e)}"}

    def list_tools(self) -> List[Dict[str, Any]]:
        """返回所有工具信息"""
        return [
            {
                "name": name,
                "description": tool.description,
                "required_params": tool.required_params,
            }
            for name, tool in self.tools.items()
        ]

    def get_tool(self, tool_name: str) -> Optional[AnalysisTool]:
        """獲取工具實例"""
        return self.tools.get(tool_name)
