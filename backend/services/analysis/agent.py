import json
import logging
import asyncio
import httpx
import requests
import re
from typing import List, Dict, Any, Optional, Union
from llama_index.core.llms import (
    CustomLLM,
    CompletionResponse,
    CompletionResponseGen,
    LLMMetadata,
    ChatMessage,
)
from llama_index.core.memory import ChatMemoryBuffer
from llama_index.core.llms.callbacks import llm_completion_callback
from llama_index.core.workflow import (
    Event,
    StartEvent,
    StopEvent,
    Workflow,
    step,
    Context,
)
import config
from .analysis_types import (
    IntentEvent,
    AnalysisEvent,
    TranslationEvent,
    VisualizingEvent,
    SummarizeEvent,
    ProgressEvent,
    TextChunkEvent,
    ToolCallEvent,
    ToolResultEvent,
    ErrorEvent,
)
from .tools.executor import ToolExecutor
from .analysis_service import AnalysisService

logger = logging.getLogger(__name__)


class CustomOllamaLLM(CustomLLM):
    """
    自定義高效 Ollama 封裝，支持 httpx 異步請求
    """

    model_name: str
    api_url: str
    timeout: float = 120.0

    @property
    def metadata(self) -> LLMMetadata:
        return LLMMetadata(
            context_window=32768,
            num_output=4096,
            model_name=self.model_name,
        )

    @llm_completion_callback()
    async def acomplete(
        self, prompt: str, json_mode: bool = False, **kwargs: Any
    ) -> CompletionResponse:
        """核心非串流回傳，支持 JSON 模式"""
        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        if json_mode:
            payload["format"] = "json"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(self.api_url, json=payload)
                response.raise_for_status()
                result = response.json()
                content = result.get("message", {}).get("content", "")
                return CompletionResponse(text=content)
        except Exception as e:
            logger.error(f"Ollama Async 連線錯誤: {str(e)}")
            raise ConnectionError(f"無法非同步連線至 Ollama: {str(e)}")

    async def astream_complete(
        self, prompt: str, **kwargs: Any
    ) -> CompletionResponseGen:
        """核心串流回傳，用於即時打字機效果"""
        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST", self.api_url, json=payload
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        chunk = json.loads(line)
                        if "message" in chunk:
                            content = chunk["message"].get("content", "")
                            yield CompletionResponse(text=content, delta=content)
                        if chunk.get("done"):
                            break
        except Exception as e:
            logger.error(f"Ollama Stream 連線錯誤: {str(e)}")
            raise ConnectionError(f"無法串流連線至 Ollama: {str(e)}")

    @llm_completion_callback()
    def complete(self, prompt: str, **kwargs: Any) -> CompletionResponse:
        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        response = requests.post(self.api_url, json=payload, timeout=self.timeout)
        result = response.json()
        return CompletionResponse(text=result.get("message", {}).get("content", ""))

    @llm_completion_callback()
    def stream_complete(self, prompt: str, **kwargs: Any) -> CompletionResponseGen:
        yield self.complete(prompt, **kwargs)


class SigmaAnalysisWorkflow(Workflow):
    """
    Sigma2 智能分析工作流 (高性能修正版)
    """

    def __init__(
        self,
        tool_executor: ToolExecutor,
        analysis_service: AnalysisService,
        model_name: str = config.LLM_MODEL,
        ollama_api_url: str = config.LLM_API_URL,
        timeout: int = 180,
    ):
        super().__init__(timeout=timeout, verbose=True)
        self.tool_executor = tool_executor
        self.analysis_service = analysis_service
        # 使用自定義極速引擎，並共享實例以降低開銷
        self.llm = CustomOllamaLLM(model_name=model_name, api_url=ollama_api_url)
        self.llm_json = self.llm  # 故意不開 JSON 模式以提升串流靈活性

    @step
    async def route_intent(
        self, ctx: Context, ev: StartEvent
    ) -> IntentEvent | ErrorEvent:
        # 向前端發送初步反饋
        ctx.write_event_to_stream(ProgressEvent(msg="─ 正在快速匹配指令路徑..."))
        query = getattr(ev, "query", "").strip()
        file_id = getattr(ev, "file_id", None)
        session_id = getattr(ev, "session_id", None)
        history = getattr(ev, "history", "")

        if not query:
            return ErrorEvent(error="未提供問題", session_id=session_id)

        # --- 極速硬體決策 (Heuristic Logic) ---
        # 1. 如果有 File_ID 且字數不多，絕大多數都是分析需求，直接通關
        if file_id and len(query) < 20:
            intent = "analysis"
        else:
            # 2. 關鍵字擴展過濾
            analysis_keywords = [
                "分析",
                "相關性",
                "異常",
                "趨勢",
                "欄位",
                "數據",
                "找出",
                "離群",
                "分佈",
                "幾筆",
                "多少",
                "行數",
                "畫",
                "圖",
            ]
            query_lower = query.lower()
            if any(kw in query_lower for kw in analysis_keywords):
                intent = "analysis"
            else:
                # 3. 只有長難句且不明確時，才動用 LLM (且使用極簡指令)
                try:
                    prompt = f"Categorize as 'analysis' or 'chat': {query}\nReply only 1 word."
                    response = await self.llm.acomplete(prompt)
                    intent = str(response.text).strip().lower()
                except Exception:
                    intent = "analysis"

        return IntentEvent(
            query=query,
            intent=intent,
            file_id=file_id,
            session_id=session_id,
            history=history,
            mode=ev.mode,
        )

    @step
    async def handle_error(self, ctx: Context, ev: ErrorEvent) -> StopEvent:
        """
        [Local Step] 錯誤處理站
        """
        logger.error(f"[Error Station] Workflow Error: {ev.error}")
        return StopEvent(
            result={
                "response": "抱歉，系統運作出現錯誤：" + str(ev.error),
                "data": None,
            }
        )

    @step
    async def dispatch_work(
        self, ctx: Context, ev: IntentEvent
    ) -> Union[AnalysisEvent, TranslationEvent, SummarizeEvent]:
        intent = (ev.intent or "").strip().lower()
        query_lower = ev.query.lower()

        # --- 零延遲快車道 (Metadata Fast-Track) ---
        # 如果只是想知道欄位清單、行數或檔案摘要，沒必要動用 AI 大腦
        summary_keywords = [
            "有哪些欄位",
            "欄位清單",
            "所有參數",
            "幾筆資料",
            "總行數",
            "幾行",
            "摘要",
            "概況",
            "這份檔案",
            "簡介",
        ]
        if "analysis" in intent and (any(kw in query_lower for kw in summary_keywords)):
            summary = self.tool_executor.analysis_service.load_summary(
                ev.session_id, ev.file_id
            )
            if summary:
                ctx.write_event_to_stream(
                    ProgressEvent(
                        msg="─ 檢測到基礎資訊/摘要查詢，正在從快取直接提取答案..."
                    )
                )
                params_list = summary.get("parameters", [])
                total_rows = summary.get("total_rows", 0)
                categories = summary.get("categories", {})

                # 構建結構化摘要
                cat_info = ", ".join(
                    [f"{k} ({len(v)}個)" for k, v in categories.items()]
                )
                quality_stats = summary.get("quality_stats", {})

                content = (
                    f"### 檔案概況摘要\n\n"
                    f"此檔案共有 **{len(params_list)}** 個欄位，總計 **{total_rows}** 筆數據。\n"
                    f"**數據分類**: {cat_info}\n\n"
                )

                # 新增：品質描述 (更詳細版)
                quality_msg = []
                null_cols = quality_stats.get("null_columns_preview", [])
                const_cols = quality_stats.get("constant_columns_preview", [])
                sparse_cols = quality_stats.get("sparse_columns_preview", [])

                if quality_stats.get("null_column_count", 0) > 0:
                    quality_msg.append(
                        f"有 {len(null_cols)} 個高缺失率欄位 ({', '.join(null_cols[:3])}...)"
                    )

                if quality_stats.get("sparse_column_count", 0) > 0:
                    quality_msg.append(
                        f"有 {quality_stats['sparse_column_count']} 個稀疏欄位 (真值比例 < 80%，如 {', '.join(sparse_cols[:3])})"
                    )

                if quality_stats.get("constant_column_count", 0) > 0:
                    quality_msg.append(
                        f"有 {quality_stats['constant_column_count']} 個定值/全零欄位 (如 {', '.join(const_cols[:3])})"
                    )

                if quality_msg:
                    content += (
                        f"**數據品質警訊**: \n- " + "\n- ".join(quality_msg) + "\n\n"
                    )
                else:
                    content += f"**數據品質**: 數據完整，無明顯缺失或稀疏欄位。\n\n"

                content += f"您可以問我關於這些參數的趨勢、異常偵測或相關性分析。"

                if any(
                    kw in query_lower
                    for kw in [
                        "欄位",
                        "參數",
                        "清單",
                        "哪些",
                        "哪兩個",
                        "哪幾個",
                        "那兩個",
                        "那幾個",
                    ]
                ):
                    content += (
                        f"\n\n全部欄位清單如下 (共 {len(params_list)} 個):\n"
                        f"{', '.join(params_list)}"
                    )
                    # 強制攔截：用戶追問空值欄位
                    if (
                        "空值" in query_lower
                        or "缺失" in query_lower
                        or "哪兩個" in query_lower
                    ):
                        null_cols = quality_stats.get("null_columns_preview", [])
                        if null_cols:
                            content += f"\n\n### 🔴 高缺失率欄位詳細清單:\n**{', '.join(null_cols)}**\n(這些欄位幾乎為空，建議忽略或檢查來源)"
                return SummarizeEvent(
                    data={"final_decision": content, "all_steps_results": []},
                    query=ev.query,
                    file_id=ev.file_id,
                    session_id=ev.session_id,
                    history=ev.history,
                    mode=ev.mode,
                    row_count=total_rows,
                    col_count=len(params_list),
                    mappings=summary.get("mappings", {}),
                )

        if "analysis" in intent:
            return AnalysisEvent(
                query=ev.query,
                file_id=ev.file_id,
                session_id=ev.session_id,
                history=ev.history,
                mode=ev.mode,
            )
        return TranslationEvent(
            query=ev.query,
            file_id=ev.file_id,
            session_id=ev.session_id,
            history=ev.history,
            mode=ev.mode,
        )

    @step
    async def execute_analysis(
        self, ctx: Context, ev: AnalysisEvent
    ) -> Union[AnalysisEvent, VisualizingEvent, SummarizeEvent]:
        """
        [Local Step] 執行智慧分析決策 (支持最多 3 步的循環診斷)
        """
        summary = self.tool_executor.analysis_service.load_summary(
            ev.session_id, ev.file_id
        )
        params_list = summary.get("parameters", []) if summary else []
        total_cols = len(params_list)
        total_rows = summary.get("total_rows", 0) if summary else 0

        # 只有在第一步顯示詳細檢索訊息，後續步數顯示簡潔進度
        if ev.step_count == 1:
            ctx.write_event_to_stream(
                ProgressEvent(
                    msg=f"─ 正在初始化分析環境，鎖定 {total_cols} 個原始欄位..."
                )
            )
        else:
            ctx.write_event_to_stream(ProgressEvent(msg=f"─ 正在準備延伸分析邏輯..."))
        mappings = summary.get("mappings", {}) if summary else {}

        # --- 安全閥：解鎖深度診斷分析 ---
        MAX_STEPS = 30
        is_last_step = ev.step_count >= MAX_STEPS

        tool_specs = self.tool_executor.list_tools()

        # --- 欄位清單智慧壓縮 ---
        categories = summary.get("categories", {})
        if total_cols > 50:
            cat_summary = "; ".join(
                [f"{k} ({len(v)}個)" for k, v in categories.items()]
            )
            all_columns_display = f"由於欄位眾多，僅依類別顯示摘要：{cat_summary}。請在需要時使用 search_parameters_by_concept 搜尋具體欄位。"
        else:
            all_columns_display = ", ".join(params_list)

        # 構建過去步驟的背景資訊
        history_context = ""
        if ev.prev_results:
            # 僅保留關鍵結果，縮減 Token
            simplified_history = []
            for r in ev.prev_results:
                # 截斷過長的結果以節省 Context (但保留關鍵數據)
                raw_result = str(r.get("result", ""))
                truncated_result = (
                    raw_result[:500] + "...(略)"
                    if len(raw_result) > 500
                    else raw_result
                )

                simplified_history.append(
                    {
                        "step": r.get("step"),
                        "tool": r.get("tool"),
                        "params": r.get("params"),
                        "result": truncated_result,  # [NEW] 讓 AI 看見過去的數據
                        "monologue": r.get("monologue"),
                    }
                )
            history_context = "\n### 前序分析結果摘要 (含數據記憶) ###\n" + json.dumps(
                simplified_history, ensure_ascii=False
            )

        quality_stats = summary.get("quality_stats", {})
        null_count = quality_stats.get("null_column_count", 0)
        const_count = quality_stats.get("constant_column_count", 0)
        sparse_count = quality_stats.get("sparse_column_count", 0)

        # 將垃圾數據欄位標記為「黑名單」，不再提供具體名稱以免 AI 分心
        quality_info = f"【黑名單警報】偵測到 {null_count} 個全空欄位與 {const_count} 個定值欄位。這些欄位已被系統自動剔除，**絕對禁止提及或分析它們**。"
        if sparse_count > 0:
            quality_info += (
                f" 另有 {sparse_count} 個欄位數據極度稀疏，請優先選擇數據完整的參數。"
            )

        # 根據模式切換指令集
        mode_instruction = ""
        if ev.mode == "deep":
            mode_instruction = (
                "## 當前模式：深度診斷 (Deep Analysis) ##\n"
                "你的目標是進行全方位的根因分析。除了基礎統計，請主動善用以下高階工具來增強說服力：\n"
                "1. **分佈檢定 (`distribution_shift_test`)**: 這是你的核武器。當發現某參數異常時，用它來證明「分佈形狀變了」，而不只是數值變大。\n"
                "2. **因果分析 (`causal_relationship_analysis`)**: 用它來找「領頭羊」。誰先變的？\n"
                "3. **多維分析 (`hotelling_t2_analysis`)**: 用它來量化「整體偏移」。\n"
                "\n"
                "**【絕對禁止死循環與回頭草】**\n"
                "1. **禁止重複**: 檢查 `history`！如果你已經用過某個工具且參數相同，**絕對禁止再用一次**。\n"
                "2. **禁止倒退**: 在 Step 3 之後，**嚴禁**呼叫 `get_data_overview` 或 `get_column_info`。你手上的證據已經夠了，不要浪費步數。\n"
                "3. **果斷結案**: 若已執行過 `compare_data_segments` 或 `hotelling_t2`，且步數 > 4，請直接進入 `humanizer` 結案。"
            )
        else:
            mode_instruction = (
                "## 當前模式：快速回應 (Quick Response) ##\n"
                "你的目標是在 **2 步內** 給出精確結論：\n"
                "1. 優先選擇最強力的單一診斷工具 (如 `hotelling_t2_analysis` 或 `compare_data_segments`)。\n"
                "2. 獲得 Top 3 貢獻度後立即結案，解釋核心原因即可。\n"
            )

        tools_json = json.dumps(tool_specs, ensure_ascii=False)
        prompt_parts = [
            f"你是一個機靈且嚴謹的工業數據分析專家。目前是診斷的第 {ev.step_count} 步。",
            f"基礎數據資訊: 當前檔案共有 {total_rows} 行數據，{total_cols} 個欄位。",
            f"數據品質警訊 (絕對事實): {quality_info}",
            f"所有可用欄位 (部分展示): {all_columns_display}",
            f"可用工具箱: {tools_json}",
            f"分析目標 (Query): {ev.query}",
            f"{history_context}",
            "",
            f"{mode_instruction}",
            "## 核心原則 (嚴格執行) ##",
            "1. **參數名稱精確性**: 絕對禁止使用類別名稱 (如 'PRESSDRY', 'SHAP') 作為參數。你必須從可用欄位清單中選擇具體的感測器代碼 (如 'PRESSDRY-DCS_A423')。",
            "2. **數據說話**: 任何結論都必須有數據支持 (Z-Score, p-value, T2)。",
            "3. **對比分析**: 異常檢測的核心在於「異常 vs 正常」。請時刻保持對比意識。",
            "4. **透明獨白**: 在 `monologue` 中用繁體中文解釋你的思考路徑。",
            "5. **記憶運用**: 請參考 `前序分析結果摘要` 中的 `result` 數據，不要重複執行已知的分析。",
            f"6. **狀態提醒**: 目前是第 {ev.step_count} 步。",
            '輸出唯一個 JSON 物件，必須包含 "action", "tool_name", "params", "monologue" 欄位。',
        ]
        prompt = "\n".join(prompt_parts)

        # 1. 告訴用戶 AI 正在根據上一步的結果進行推理
        ctx.write_event_to_stream(
            ProgressEvent(msg=f"(Step {ev.step_count}) 正在分析上下文並規劃下一步...")
        )

        # 強制開啟 JSON 模式
        response = await self.llm.acomplete(prompt, json_mode=True)

        try:
            text = response.text.strip()
            # 優先處理 Markdown 代碼塊
            if "```" in text:
                text = text.split("```")[1].replace("json", "").strip()

            # 優先使用 Regex 提取 JSON，防止 Ollama 輸出多餘文字或重複 JSON
            json_match = re.search(r"\{.*\}", response.text, re.DOTALL)
            if json_match:
                decision = json.loads(json_match.group(0))
            else:
                decision = json.loads(response.text)

            # --- 硬核防死循環邏輯 ---
            tool_history = [
                (
                    r.get("tool"),
                    str(
                        r.get("params", {}).get("target")
                        or r.get("params", {}).get("parameter")
                    ),
                )
                for r in ev.prev_results
            ]
            current_tool = decision.get("tool_name")
            current_target = str(
                decision.get("params", {}).get("target")
                or decision.get("params", {}).get("parameter")
            )

            # 如果同一個工具對同一個目標連續執行超過 2 次，強制修正為 finish
            repeat_count = tool_history.count((current_tool, current_target))
            if repeat_count >= 2:
                logger.warning(
                    f"Detected repeated tool call: {current_tool} on {current_target}. Forcing finish."
                )
                decision = {
                    "action": "finish",
                    "monologue": f"檢測到重複分析行為 (已執行 {repeat_count} 次)，系統強制進入最終彙整階段以打破死循環。",
                }

            action = decision.get("action", "call_tool")
            monologue = decision.get("monologue", "診斷中...")

            # 2. 告訴用戶 AI 決定要做什麼 (內心獨白)
            ctx.write_event_to_stream(ProgressEvent(msg=f"💡 策略: {monologue}"))

            if action == "call_tool":
                tool_name = decision.get("tool_name")
                # 3. 告訴用戶正在執行什麼耗時操作
                ctx.write_event_to_stream(
                    ProgressEvent(msg=f"🛠️ 執行工具: {tool_name} (正在運算數據...)")
                )

        except Exception as e:
            # 發生解析錯誤時的強制修復邏輯
            logger.error(f"Error parsing LLM decision: {e}. Raw: {response.text}")
            # 如果是第一步就失敗，強制進行數據概覽分析，不准直接 finish
            if ev.step_count == 1:
                action = "call_tool"
                tool_name = "get_data_overview"
                params = {"file_id": ev.file_id}
                monologue = "原定計畫解析失敗，強制啟動數據概覽以打破僵局。"
                decision = {
                    "action": action,
                    "tool_name": tool_name,
                    "params": params,
                    "monologue": monologue,
                }
            else:
                action = "finish"
                monologue = "連續分析出現解析困難，準備進行最終彙整。"
                decision = {"action": action, "monologue": monologue}

        if action == "finish" or is_last_step:
            # 結束前檢查是否有可繪圖數據 (get_time_series_data)
            chart_data = None
            for step_res in ev.prev_results:
                if step_res.get("tool") == "get_time_series_data":
                    res_data = step_res.get("result", {})
                    if (
                        isinstance(res_data, dict)
                        and "data" in res_data
                        and res_data["data"]
                    ):
                        chart_data = res_data
                        break

            total_rows = summary.get("total_rows", 0) if summary else 0
            total_cols = len(params_list) if params_list else 0

            if chart_data:
                # 優先跳轉到視覺化步驟，這會確保 UI 渲染圖表
                return VisualizingEvent(
                    data=chart_data,
                    query=ev.query,
                    file_id=ev.file_id,
                    session_id=ev.session_id,
                    history=ev.history,
                    mode=ev.mode,
                    row_count=chart_data.get("total_points", total_rows),
                    col_count=len(chart_data.get("data", {}).keys()),
                    mappings=mappings,
                )

            # 建立顯示名稱映射
            full_display_mappings = {p: mappings.get(p, p) for p in params_list}

            # 優化：提取具體的分析結果摘要，避免 AI 混淆
            aggregated_data = {
                "monologue_history": monologue,
                "latest_analysis_results": ev.prev_results[-1].get("results")
                if ev.prev_results
                else None,
                "full_tool_history": ev.prev_results,
            }

            return SummarizeEvent(
                data=aggregated_data,
                query=ev.query,
                file_id=ev.file_id,
                session_id=ev.session_id,
                history=ev.history,
                mode=ev.mode,
                row_count=total_rows,
                col_count=total_cols,
                mappings=full_display_mappings,
            )

        # 否則，執行工具並進入下一步循環
        tool_name = decision.get("tool_name")
        params = decision.get("params", {})
        if not isinstance(params, dict):
            params = {}
        params["file_id"] = ev.file_id

        try:
            # 根據工具名提供動態的進度提示
            tool_display_names = {
                "get_time_series_data": "正在讀取數據趨勢...",
                "detect_outliers": "正在偵測異常點...",
                "get_top_correlations": "正在分析因素相關性...",
                "analyze_distribution": "正在分析數據分佈...",
            }
            display_msg = tool_display_names.get(tool_name, f"執行工具 {tool_name}...")

            ctx.write_event_to_stream(
                ProgressEvent(msg=f"(Step {ev.step_count}) {display_msg}")
            )

            # 4. 執行工具
            tool_result = await self.tool_executor.execute_tool(
                tool_name, params, ev.session_id
            )

            # 強制功能：將貢獻度前三名即時推送到聊天室思考視窗
            if isinstance(tool_result, dict) and "top_3_summary" in tool_result:
                ctx.write_event_to_stream(
                    ProgressEvent(msg=f"{tool_result['top_3_summary']}")
                )
            # 5. 將結果存入歷史，並觸發下一步
            new_step_result = {
                "step": ev.step_count,
                "tool": tool_name,
                "params": params,
                "result": tool_result,
                "monologue": monologue,
            }

            next_history = list(ev.prev_results)
            next_history.append(new_step_result)

            return AnalysisEvent(
                query=ev.query,
                file_id=ev.file_id,
                session_id=ev.session_id,
                history=ev.history,
                mode=ev.mode,
                step_count=ev.step_count + 1,
                prev_results=next_history,
            )

        except Exception as e:
            logger.error(f"Tool execution failed: {e}")
            # 若工具執行失敗，不崩潰，而是將錯誤作為結果傳入下一步
            error_result = {
                "step": ev.step_count,
                "tool": tool_name,
                "params": params,
                "result": {"error": str(e)},
                "monologue": monologue,
            }
            next_history = list(ev.prev_results)
            next_history.append(error_result)

            return AnalysisEvent(
                query=ev.query,
                file_id=ev.file_id,
                session_id=ev.session_id,
                history=ev.history,
                mode=ev.mode,
                step_count=ev.step_count + 1,
                prev_results=next_history,
            )

    @step
    async def execute_translation(
        self, ctx: Context, ev: TranslationEvent
    ) -> SummarizeEvent:
        """
        [Local Step] 執行對話或簡單翻譯，並注入參數背景資訊
        """
        # 即使是簡單對話，也抓取參數清單作為 AI 的背景知識
        summary = self.tool_executor.analysis_service.load_summary(
            ev.session_id, ev.file_id
        )
        params_list = summary.get("parameters", []) if summary else []
        total_rows = summary.get("total_rows", 0) if summary else 0
        total_cols = summary.get("total_columns", 0) if summary else 0
        mappings = summary.get("mappings", {}) if summary else {}

        # 建立顯示名稱映射
        full_display_mappings = {p: mappings.get(p, p) for p in params_list}

        # 將參數清單放入 data，讓 humanizer 裡的 AI 看得到
        context_data = {"available_parameters": params_list}

        return SummarizeEvent(
            data=context_data,
            query=ev.query,
            file_id=ev.file_id,
            session_id=ev.session_id,
            history=ev.history,
            mode=ev.mode,
            row_count=total_rows,
            col_count=total_cols,
            mappings=full_display_mappings,
        )

    def _build_programmatic_chart(self, ev: VisualizingEvent) -> Optional[str]:
        """穩定圖表生成邏輯"""
        try:
            if (
                not isinstance(ev.data, dict)
                or "data" not in ev.data
                or not ev.data["data"]
            ):
                return None
            actual_data = ev.data["data"]
            query_lower = ev.query.lower()

            # --- 判斷圖表類型 ---
            is_histogram = any(
                kw in query_lower for kw in ["直方圖", "histogram", "分佈", "分布"]
            )
            is_scatter = any(kw in query_lower for kw in ["散佈", "scatter", "相關性"])

            if is_histogram:
                target_col = next(
                    (
                        c
                        for c in actual_data
                        if c not in ["TIME", "Timestamp"]
                        and any(
                            isinstance(v, (int, float)) for v in actual_data[c][:20]
                        )
                    ),
                    None,
                )
                if not target_col:
                    return None
                vals = [
                    v for v in actual_data[target_col] if isinstance(v, (int, float))
                ]
                v_min, v_max = min(vals), max(vals)
                bins = [0] * 15
                step = (v_max - v_min) / 15 or 1
                for v in vals:
                    bins[min(int((v - v_min) / step), 14)] += 1
                chart_obj = {
                    "type": "chart",
                    "chart_type": "bar",
                    "title": f"分佈: {target_col}",
                    "labels": [f"{v_min + i * step:.1f}" for i in range(15)],
                    "datasets": [{"label": "頻次", "data": bins}],
                }
            else:
                label_col = next(
                    (c for c in ["TIME", "Timestamp", "Date"] if c in actual_data), None
                )
                labels = (
                    actual_data[label_col]
                    if label_col
                    else list(range(len(next(iter(actual_data.values())))))
                )
                datasets = []
                for col, vals in actual_data.items():
                    if col == label_col:
                        continue
                    datasets.append(
                        {"label": ev.mappings.get(col, col), "data": vals[:100]}
                    )
                chart_obj = {
                    "type": "chart",
                    "chart_type": "line",
                    "labels": labels[:100],
                    "datasets": datasets,
                }

            return json.dumps(chart_obj, ensure_ascii=False)
        except:
            return None

    @step
    async def visualize_data(
        self, ctx: Context, ev: VisualizingEvent
    ) -> SummarizeEvent:
        ctx.write_event_to_stream(
            ProgressEvent(msg="(Visualizing...) 正在繪製分析圖表...")
        )
        chart_json = self._build_programmatic_chart(ev)
        return SummarizeEvent(
            data=ev.data,
            query=ev.query,
            file_id=ev.file_id,
            session_id=ev.session_id,
            history=ev.history,
            chart_json=chart_json,
            row_count=ev.row_count,
            col_count=ev.col_count,
            mode=ev.mode,
            mappings=ev.mappings,
        )

    @step
    async def humanizer(self, ctx: Context, ev: SummarizeEvent) -> StopEvent:
        ctx.write_event_to_stream(
            ProgressEvent(msg="(Humanizing...) 正在生成最終分析報告...")
        )

        # 最終防線：抓取物理全量統計與欄位清單作為背景
        row_count = ev.row_count
        col_count = ev.col_count
        params_list = []
        try:
            summary = self.tool_executor.analysis_service.load_summary(
                ev.session_id, ev.file_id
            )
            if summary:
                params_list = summary.get("parameters", [])
                if row_count <= 0:
                    row_count = summary.get("total_rows", 0)
                if col_count <= 0:
                    col_count = summary.get("total_columns", 0)
        except Exception:
            pass

        if ev.mode == "deep":
            mode_instruction = (
                "## 當前模式：深度診斷 (Deep Analysis) ##\n"
                "你的目標是進行全方位的根因分析。除了基礎統計，請主動善用以下高階工具來增強說服力：\n"
                "1. **分佈檢定 (`distribution_shift_test`)**: 這是你的核武器。當發現某參數異常時，用它來證明「分佈形狀變了」，而不只是數值變大。\n"
                "2. **因果分析 (`causal_relationship_analysis`)**: 用它來找「領頭羊」。誰先變的？\n"
                "3. **多維分析 (`hotelling_t2_analysis`)**: 用它來量化「整體偏移」。\n"
                "\n"
                "**【絕對禁止死循環】**\n"
                "檢查 `history`！如果你已經用過某個工具 (如 `get_top_correlations`) 且參數相同，**絕對禁止再用一次**。\n"
                "若基礎分析已完成，請直接進入 `distribution_shift_test` 或 `causal_relationship_analysis`。\n"
                "若證據已充足，請直接 `humanizer` 結案。"
            )
        else:
            mode_instruction = (
                "## 當前模式：快速回應 (Quick Response) ##\n"
                "你的目標是在 **2 步內** 給出精確結論：\n"
                "1. 優先選擇最強力的單一診斷工具 (如 `hotelling_t2_analysis` 或 `compare_data_segments`)。\n"
                "2. 獲得 Top 3 貢獻度後立即結案，解釋核心原因即可。\n"
            )

        # 增加數據內容曝光量，深度模式下不應過度截斷
        data_json = json.dumps(ev.data, ensure_ascii=False)
        data_limit = 20000 if ev.mode == "deep" else 5000

        prompt = (
            f"系統狀態: {mode_instruction}\n"  # Changed from system_instruction to mode_instruction
            f"用戶提問: {ev.query}\n"
            f"數據概況 (背景): 包含 {row_count} 行與 {col_count} 個欄位。\n"
            f"參數顯示名稱對應 (Mapping): {json.dumps(ev.mappings, ensure_ascii=False)}\n"
            f"分析數據 (全量歷史精華): {data_json[:data_limit]}\n"
            "## 生成準則 (數值先行 + 解釋隨後) ##\n"
            "1. **嚴禁空洞描述**: 必須先引用數據 (p-value, T2, Z-Score) 作為開頭。\n"
            "2. **翻譯物理意義**: 解釋時要具體對應到設備狀態 (如：馬達耗損、配方切換、傳感器漂移)。\n"
            "3. **專業口吻**: 繁體中文，專業工業診斷工程師口吻。"
        )

        full_text = ""
        suffix = f"\n\n```json\n{ev.chart_json}\n```\n" if ev.chart_json else ""

        # --- 真串流開始 ---
        async for chunk in self.llm.astream_complete(prompt):
            if chunk.delta:
                full_text += chunk.delta
                ctx.write_event_to_stream(TextChunkEvent(content=chunk.delta))

        if suffix:
            ctx.write_event_to_stream(TextChunkEvent(content=suffix))
            full_text += suffix

        return StopEvent(result={"response": full_text, "data": ev.data})


class LLMAnalysisAgent:
    """為了兼容外部調用的封裝類"""

    def __init__(
        self, tool_executor: ToolExecutor, analysis_service: AnalysisService, **kwargs
    ):
        self.workflow = SigmaAnalysisWorkflow(tool_executor, analysis_service)
        self.memories = {}

    def _get_memory(self, session_id: str):
        if session_id not in self.memories:
            self.memories[session_id] = ChatMemoryBuffer.from_defaults(
                token_limit=16000
            )
        return self.memories[session_id]

    async def stream_analyze(
        self, session_id: str, file_id: str, user_question: str, analysis_service=None
    ):
        memory = self._get_memory(session_id)
        history_str = "\n".join([f"{m.role}: {m.content}" for m in memory.get_all()])

        handler = self.workflow.run(
            query=user_question,
            file_id=file_id,
            session_id=session_id,
            history=history_str,
        )

        async for event in handler.stream_events():
            event_type = type(event).__name__
            if event_type == "TextChunkEvent":
                yield json.dumps(
                    {"type": "text_chunk", "content": event.content}, ensure_ascii=False
                )
            elif event_type == "ProgressEvent":
                yield json.dumps(
                    {"type": "thought", "content": event.msg}, ensure_ascii=False
                )
            elif event_type == "MonologueEvent":
                yield json.dumps(
                    {"type": "thought", "content": f"思考: {event.monologue}"},
                    ensure_ascii=False,
                )
            elif event_type == "ToolCallEvent":
                yield json.dumps(
                    {"type": "tool_call", "tool": event.tool, "params": event.params},
                    ensure_ascii=False,
                )
            elif event_type == "ToolResultEvent":
                yield json.dumps(
                    {"type": "tool_result", "tool": event.tool, "result": event.result},
                    ensure_ascii=False,
                )

        final_result = await handler
        memory.put(ChatMessage(role="user", content=user_question))
        memory.put(
            ChatMessage(role="assistant", content=final_result.get("response", ""))
        )

        yield json.dumps(
            {
                "type": "response",
                "content": final_result.get("response"),
                "tool_result": final_result.get("data"),
            },
            ensure_ascii=False,
        )

    async def clear_session(self, session_id: str = "default"):
        if session_id in self.memories:
            self.memories[session_id].reset()
