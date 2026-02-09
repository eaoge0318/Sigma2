from .base import AnalysisTool
from typing import Dict, Any, List
import pandas as pd


class ExplainResultTool(AnalysisTool):
    """解釋分析結果工具"""

    name = "explain_result"
    description = "對之前的分析結果進行自然語言解釋"

    # 但如果需要強制生成解釋，可以調用此工具來標記意圖
    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        context = params.get("context", {})
        # 明確指示 Agent 停止調用並直接回答
        return (
            "請根據上下文分析結果，直接用繁體中文回答用戶的疑問。不需要再次調用此工具。"
        )


class SuggestNextAnalysisTool(AnalysisTool):
    """推薦下一步分析工具"""

    name = "suggest_next_analysis"
    description = "根據當前分析結果，推薦後續的分析方向"
    required_params = ["file_id"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        current_analysis = params.get("current_analysis_type", "unknown")

        summary = self.service.load_summary(session_id, file_id)
        if not summary:
            return {"error": "Summary not found"}

        suggestions = []
        params_list = summary.get("parameters", [])

        # 簡單的規則引擎
        if current_analysis == "correlation":
            suggestions.append("Try regression analysis on highly correlated pairs.")
            suggestions.append("Check for outliers in the correlated parameters.")
        elif current_analysis == "outliers":
            suggestions.append("Analyze distribution of parameters with outliers.")
            suggestions.append(
                "Check temporal patterns to see if outliers are time-related."
            )
        else:
            suggestions.append("Check parameter statistics.")
            suggestions.append("Analyze correlations between key parameters.")
            suggestions.append("Find temporal patterns if time series data exists.")

        return {"current_analysis": current_analysis, "suggestions": suggestions}


class AskClarificationTool(AnalysisTool):
    """詢問澄清工具"""

    name = "ask_clarification"
    description = "當用戶意圖不明時，生成澄清問題"

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        missing_info = params.get("missing_info", [])

        questions = []
        for info in missing_info:
            if info == "target":
                questions.append("請問您想分析哪個目標參數？")
            elif info == "file":
                questions.append("請問您指的是哪個文件？")
            elif info == "time_range":
                questions.append("請問您想分析哪個時間段？")

        if not questions:
            questions.append("你能提供更多細節嗎？")

        return {"action": "ask_clarification", "questions": questions}
