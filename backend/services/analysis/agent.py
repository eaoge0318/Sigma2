from typing import Optional, Dict, Any, List
from llama_index.core.workflow import (
    Workflow,
    step,
    Context,
    StartEvent,
    StopEvent,
)
from llama_index.llms.ollama import Ollama
from llama_index.core.llms import ChatMessage
import json
import logging
from .types import (
    IntentEvent,
    AnalysisEvent,
    MonologueEvent,  # Added
    ConceptExpansionEvent,
    VisualizingEvent,
    SummarizeEvent,
    ProgressEvent,
)
from .tools.executor import ToolExecutor
from .analysis_service import AnalysisService

import config

logger = logging.getLogger(__name__)


class SigmaAnalysisWorkflow(Workflow):
    """
    Sigma2 智慧分析工作流 (v2.0)

    核心特性：
    1. 多輪迭代推理 (Iterative Reasoning)
    2. 自我糾錯循環 (Self-Correction Loop)
    3. 狀態機驅動 (State Machine Driven)
    """

    def __init__(
        self,
        tool_executor: ToolExecutor,
        analysis_service: AnalysisService,
        timeout: int = 600,  # Relaxed timeout
        verbose: bool = True,
        event_handler: Optional[Any] = None,  # Added callback
    ):
        super().__init__(timeout=timeout, verbose=verbose)
        self.tool_executor = tool_executor
        self.analysis_service = analysis_service
        self.event_handler = event_handler

        # Parse base_url from config
        base_url = config.LLM_API_URL.replace("/api/chat", "")
        self.llm = Ollama(
            model=config.LLM_MODEL, base_url=base_url, request_timeout=120.0
        )

    @step
    async def route_intent(
        self, ctx: Context, ev: StartEvent
    ) -> IntentEvent | StopEvent:
        """
        [工作站 1] 意圖識別與初始化
        """
        # (Start)
        if self.event_handler:
            await self.event_handler(
                ProgressEvent(msg="(Analyzing Intent...) 正在識別分析意圖與上下文...")
            )

        # 1. 初始化上下文
        await ctx.store.set("session_id", getattr(ev, "session_id", "default"))
        await ctx.store.set("file_id", getattr(ev, "file_id", None))
        await ctx.store.set("history", getattr(ev, "history", ""))
        await ctx.store.set("steps_count", 0)  # 步數計數器

        # 2. 判斷用戶意圖 (簡單規則 + LLM)
        query = getattr(ev, "query", "")
        if not query:
            return StopEvent(result="未提供查詢內容 (Query is empty)")

        # 簡單規則：如果包含 "畫圖"、"分析"、"統計" 等關鍵字，直接進入分析
        keywords = [
            "分析",
            "統計",
            "圖表",
            "畫圖",
            "趨勢",
            "相關性",
            "異常",
            "最大",
            "最小",
        ]
        if any(k in query for k in keywords):
            return IntentEvent(
                query=query,
                intent="analysis",
                file_id=getattr(ev, "file_id", None),
                session_id=getattr(ev, "session_id", "default"),
                history=getattr(ev, "history", ""),
            )

        # 複雜意圖：交給 LLM 判斷
        history_text = getattr(ev, "history", "")
        prompt = f"""
        User Query: {query}
        History: {history_text[-500:] if history_text else ""}
        
        Classify the intent into one of:
        - ANALYSIS: Need to query data, calculate statistics, or draw charts.
        - CHAT: General conversation, greeting, or questions about the system.
        - TRANSLATION: Request to translate text.
        
        Return ONLY the classification word.
        """
        response = await self.llm.acomplete(prompt)
        intent = response.text.strip().upper()

        if "ANALYSIS" in intent:
            return IntentEvent(
                query=query,
                intent="analysis",
                file_id=getattr(ev, "file_id", None),
                session_id=getattr(ev, "session_id", "default"),
                history=getattr(ev, "history", ""),
            )
        else:
            # 非分析意圖，直接結束 (或是可以擴充 ChatEvent)
            return StopEvent(
                result=f"系統目前專注於數據分析。您的意圖被識別為: {intent}"
            )

    @step
    async def plan_analysis(
        self, ctx: Context, ev: IntentEvent | AnalysisEvent | ConceptExpansionEvent
    ) -> MonologueEvent | ConceptExpansionEvent | StopEvent:
        """
        [工作站 2-A] 分析規劃 (Internal Monologue)
        """
        current_steps = await ctx.store.get("steps_count", 0)
        await ctx.store.set("steps_count", current_steps + 1)

        if current_steps > 30:  # Max Steps Safeguard
            return StopEvent(result="分析步驟過多，系統強制終止以節省資源。")

        # 處理 ConceptExpansionEvent 的重試計數
        retry_count = 0
        if isinstance(ev, (AnalysisEvent, ConceptExpansionEvent)):
            retry_count = getattr(ev, "retry_count", 0)

        # (Thinking...)
        if self.event_handler:
            await self.event_handler(
                ProgressEvent(msg="(Planning...) 已確認任務類型，正在從工具箱挑選合適的分析方法...")
            )

        # 構造系統提示詞 (Internal Monologue)
        tools_desc = self.tool_executor.list_tools()
        system_prompt = f"""
        You are a Data Analysis Agent. You have access to the following tools:
        {json.dumps(tools_desc, indent=2, ensure_ascii=False)}
        
        Current Query: {ev.query}
        File ID: {ev.file_id}
        Session ID: {ev.session_id}
        Retry Count: {retry_count}
        
        **Strategy**:
        1. FIRST, check what parameters are available using `get_parameter_list`.
        2. IF user asks for a specific concept (e.g., "Temperature") but you don't see it, USE `search_parameters_by_concept`.
        3. IF you found the parameters, perform the requested analysis (Statistics, Correlation, Patterns).
        4. ALWAYS output your "Internal Monologue" before selecting a tool.
        
        **Output Format (JSON Only)**:
        {{
            "monologue": "Checking parameter list to find relevant columns...",
            "tool": "tool_name",
            "params": {{ ... }}
        }}
        """

        # 呼叫 LLM 決策
        response = await self.llm.acomplete(system_prompt)
        response_text = response.text.strip()

        # Robust JSON Parsing
        try:
            # 1. 嘗試直接解析
            decision = json.loads(response_text)
        except json.JSONDecodeError:
            # 2. 嘗試去除 Markdown code blocks
            clean_text = response_text.replace("```json", "").replace("```", "").strip()
            try:
                decision = json.loads(clean_text)
            except json.JSONDecodeError:
                # 3. 嘗試尋找第一個 { 和最後一個 }
                start = response_text.find("{")
                end = response_text.rfind("}")
                if start != -1 and end != -1:
                    json_str = response_text[start : end + 1]
                    try:
                        decision = json.loads(json_str)
                    except json.JSONDecodeError:
                        decision = None
                else:
                    decision = None

        if not decision:
            logger.error(f"LLM failed to output valid JSON. Response: {response_text}")
            return StopEvent(result="分析決策解析失敗 (Invalid JSON)，請稍後重試。")

        tool_name = decision.get("tool")
        tool_params = decision.get("params", {})
        monologue = decision.get("monologue", "Thinking...")

        # 注入必要的環境參數
        tool_params["file_id"] = ev.file_id

        # 創建 MonologueEvent
        monologue_evt = MonologueEvent(
            monologue=monologue,
            tool_name=tool_name,
            tool_params=tool_params,
            query=ev.query,
            file_id=ev.file_id,
            session_id=ev.session_id,
            history=ev.history,
            retry_count=retry_count,
        )

        # 觸發外部回調 (Streaming)
        if self.event_handler:
            # (Planning...)
            await self.event_handler(
                ProgressEvent(
                    msg=f"(Planning...) 分析策略已擬定，正在啟動 '{tool_name}' 以檢索對應資料"
                )
            )
            logger.info(f"Emitting MonologueEvent: {monologue[:50]}...")
            await self.event_handler(monologue_evt)
        else:
            logger.warning(
                "No event_handler attached to SigmaAnalysisWorkflow, monologue will not be streamed."
            )

        return monologue_evt

    @step
    async def execute_tool_step(
        self, ctx: Context, ev: MonologueEvent
    ) -> VisualizingEvent | ConceptExpansionEvent | StopEvent:
        """
        [工作站 2-B] 工具執行 (Tool Execution)
        """
        try:
            # (Executing...) 模擬正在掃描資料庫
            if self.event_handler:
                await self.event_handler(
                    ProgressEvent(
                        msg="(Executing...) 正在掃描地端資料庫，尋找最相關的欄位與參數..."
                    )
                )

            # --- 執行工具 ---
            result = self.tool_executor.execute_tool(
                ev.tool_name, ev.tool_params, ev.session_id
            )

            # --- 自我糾錯邏輯 (ExpandConcept) ---
            # 如果搜尋結果為空，且重試次數未達上限
            if (
                ev.tool_name == "search_parameters_by_concept"
                or ev.tool_name == "get_parameter_list"
            ) and ev.retry_count < 5:
                # 檢查結果是否真的為空 (根據工具回傳格式)
                is_empty = False
                if isinstance(result, dict):
                    if "matches" in result and not result["matches"]:
                        is_empty = True
                    if "error" in result:  # 某些錯誤也視為需要重試
                        is_empty = True

                if is_empty:
                    logger.info(
                        f"Empty search result for '{ev.query}'. Triggering ExpandConcept."
                    )
                    return ConceptExpansionEvent(
                        query=ev.query,
                        original_concept=ev.tool_params.get("concept", ev.query),
                        file_id=ev.file_id,
                        session_id=ev.session_id,
                        history=ev.history,
                        retry_count=ev.retry_count + 1,
                    )

            # --- 傳遞到視覺化站 ---
            return VisualizingEvent(
                data=result,
                query=ev.query,
                session_id=ev.session_id,
                history=ev.history,
                row_count=len(result) if isinstance(result, list) else 0,
            )

        except Exception as e:
            logger.error(f"Tool execution failed: {e}")
            return StopEvent(result=f"工具執行發生錯誤: {str(e)}")

    @step
    async def expand_concept(
        self, ctx: Context, ev: ConceptExpansionEvent
    ) -> AnalysisEvent | StopEvent:
        """
        [工作站 3] 語義擴展 (自我偵錯循環)
        """
        if ev.retry_count >= 5:
            return StopEvent(
                result=f"經過 5 次嘗試，依然無法在數據中找到與 '{ev.original_concept}' 相關的欄位。請檢查數據文件或嘗試其他關鍵字。"
            )

        prompt = f"""
        User searched for: "{ev.original_concept}" but found NO MATCHES in the dataset.
        
        As an Industrial Data Expert, suggest 3 alternative technical terms (English or Chinese) that might act as synonyms.
        Example: "斷紙" -> "Paper Break", "Sheet Break", "WEB_BREAK"
        
        Return ONLY the suggested terms separated by commas.
        """

        response = await self.llm.acomplete(prompt)
        suggestions = response.text.strip()

        logger.info(f"ExpandConcept suggestions: {suggestions}")

        # 構造新的查詢，回流到 AnalysisEvent
        new_query = f"Search for concepts: {suggestions}"

        return AnalysisEvent(
            query=new_query,
            file_id=ev.file_id,
            session_id=ev.session_id,
            history=ev.history
            + f"\n[System]: Failed to find '{ev.original_concept}', retrying with '{suggestions}'...",
            retry_count=ev.retry_count,
        )

    @step
    async def visualize_data(
        self, ctx: Context, ev: VisualizingEvent
    ) -> SummarizeEvent:
        """
        [工作站 4] 智慧圖表工廠
        """
        # 簡單的透傳，實際圖表邏輯可在此擴充 (Generic Chart)
        # 目前主要由前端處理，這裡可以負責生成 Chart Config JSON

        chart_config = None
        data = ev.data

        # 簡單判斷：如果是時序數據，建議折線圖
        if isinstance(data, dict) and "data" in data and "parameters" in data:
            chart_config = {
                "type": "line",
                "options": {"scales": {"y": {"beginAtZero": False}}},
            }

        evt = SummarizeEvent(
            data=ev.data,
            query=ev.query,
            session_id=ev.session_id,
            history=ev.history,
            chart_json=json.dumps(chart_config) if chart_config else None,
        )
        # 觸發外部回調 (Streaming) 以更新狀態
        if self.event_handler:
            # (Humanizing...)
            await self.event_handler(
                ProgressEvent(
                    msg="(Humanizing...) 圖表已生成，正在撰寫分析報告並提供專家建議..."
                )
            )
            await self.event_handler(evt)
        return evt

    @step
    async def humanizer(self, ctx: Context, ev: SummarizeEvent) -> StopEvent:
        """
        [工作站 5] 結果總結 (Humanizer)
        """
        # 預處理：如果數據過大，僅提供摘要給 LLM (這是為了避免 Token 浪費，前端仍會收到完整數據)
        context_data = ev.data
        if isinstance(context_data, dict):
            # 針對 get_parameter_list
            if "parameters" in context_data and isinstance(
                context_data["parameters"], list
            ):
                if len(context_data["parameters"]) > 50:
                    context_data = context_data.copy()
                    context_data["parameters"] = (
                        f"[List of {len(context_data['parameters'])} columns hidden for brevity. Total count: {context_data.get('total_count', 'Unknown')}]"
                    )

        prompt = f"""
        Original Query: {ev.query}
        Analysis Result: {json.dumps(context_data, ensure_ascii=False)[:30000]} # Limit size
        
        Please summarize the analysis result in Traditional Chinese (繁體中文).
        - Start with a clear direct answer.
        - Explain what the data shows.
        - Point out any anomalies or interesting trends.
        - If the result contains an error, explain it politely.
        """

        response = await self.llm.acomplete(prompt)

        final_result = {
            "summary": response.text,
            "data": ev.data,
            "chart": json.loads(ev.chart_json) if ev.chart_json else None,
        }

        return StopEvent(result=json.dumps(final_result, ensure_ascii=False))
