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
)
from .patterns import FindTemporalPatternsTool, FindEventPatternsTool
from .helpers import SuggestNextAnalysisTool, ExplainResultTool

logger = logging.getLogger(__name__)


class ToolExecutor:
    """
    工具執行器
    負責管理所有分析工具的實例化與調用
    """

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
            # Patterns
            FindTemporalPatternsTool,
            FindEventPatternsTool,
            # Helpers
            SuggestNextAnalysisTool,
            ExplainResultTool,
        ]

        for tool_cls in tool_classes:
            tool_instance = tool_cls(self.analysis_service)
            self.tools[tool_instance.name] = tool_instance

    def get_tool(self, name: str) -> AnalysisTool:
        """獲取指定工具"""
        return self.tools.get(name)

    def list_tools(self) -> List[Dict[str, str]]:
        """列出所有可用工具描述"""
        return [
            {"name": t.name, "description": t.description, "params": t.required_params}
            for t in self.tools.values()
        ]

    def execute_tool(
        self, tool_name: str, params: Dict, session_id: str
    ) -> Dict[str, Any]:
        """統一執行入口"""
        tool = self.get_tool(tool_name)
        if not tool:
            return {"error": f"Tool '{tool_name}' not found"}

        try:
            # 參數驗證
            if not tool.validate_params(params):
                missing = [p for p in tool.required_params if p not in params]
                return {"error": f"Missing required parameters: {missing}"}

            logger.info(f"Executing tool: {tool_name} for session: {session_id}")
            result = tool.execute(params, session_id)
            return result

        except Exception as e:
            logger.error(f"Tool execution failed: {tool_name}, Error: {e}")
            return {"error": f"Internal execution error: {str(e)}"}
