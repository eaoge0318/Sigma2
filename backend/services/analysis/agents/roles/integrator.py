from typing import Any, Dict, List
import json
from .base_role import BaseRole
from backend.services.analysis.analysis_types import (
    AnalysisState,
    RoleInput,
    RoleOutput,
    StepResult,
)
from backend.services.analysis.agents.prompts.system_prompts import (
    INTEGRATOR_SYSTEM_PROMPT,
)


class IntegratorRole(BaseRole):
    """
    Role 3: 整合專家 (Integration Expert)
    負責：在所有步驟結束後，總結分析結果，生成具有物理意義的報告。
    """

    async def execute(self, input_data: RoleInput) -> RoleOutput:
        # Integrator 比較特殊，它主要是 synthesize，而不是 execute step
        # 但我們可以利用這個介面來做統一化調用
        return RoleOutput(
            decision="SYNTHESIZE", reasoning="Integrator does not execute steps."
        )

    async def synthesize_report(self, state: AnalysisState) -> Dict[str, Any]:
        """
        整合所有分析步驟，生成最終報告與圖表建議
        """
        history_text = self._format_history(state.history)

        user_prompt = f"""
        [用戶的原始問題]
        "{state.original_query}"
        
        [分析策略]
        {state.strategy_plan}
        
        [累積發現摘要] (所有 Turn 的關鍵發現,不可遺漏任何一項)
        {state.rolling_summary if state.rolling_summary else "（無累積摘要）"}
        
        [詳細分析歷程] (每一步的工具執行結果)
        {history_text}
        
        [因果關係追蹤]
        {state.causal_chain if state.causal_chain else "（尚未建立因果鏈）"}
        
        [已發現的異常區間]
        {[s.range + " (Score: " + str(s.score) + ")" for s in state.discovered_sites] if state.discovered_sites else "（無異常區間）"}
        
        [撰寫指示]
        請根據以上所有資訊,撰寫一份像資深工程師的調查報告。
        
        要求:
        1. 用「問答式標題」組織內容 (如「誰是關鍵驅動因子？」「系統經歷了哪些狀態？」)
        2. 把相關的發現織成因果故事,不要只是列表
        3. 每個數字都要有物理解讀 (如「負相關代表抑制效應」)
        4. 不可遺漏任何 Turn 中發現的異常、相關係數、因果關係
        5. 結尾給出具體可操作的建議
        6. 用繁體中文撰寫
        
        回傳 JSON (不要用 ```json 包裹):
        {{
            "report": {{
                "summary_markdown": "<完整 Markdown 報告>",
                "key_charts": [
                    {{"title": "圖表標題", "type": "trend", "params": ["參數名"]}}
                ]
            }}
        }}
        """

        resp = await self._call_llm(INTEGRATOR_SYSTEM_PROMPT, user_prompt)
        parsed = self._parse_json(resp)
        report = parsed.get("report", {})

        # Fallback if parsing fails
        if not report:
            return {
                "summary": resp,  # Use raw text
                "charts": [],
            }

        return {
            "summary": report.get("summary_markdown", resp),
            "charts": report.get("key_charts", []),
        }

    def _format_history(self, history: List[StepResult]) -> str:
        text = ""
        for i, res in enumerate(history):
            text += f"Step {i + 1}: Used {res.tool_name}\n"
            text += f"Evidence: {str(res.evidence)}\n"  # Keep full evidence
            text += f"Conclusion: {res.conclusion}\n\n"
        return text
