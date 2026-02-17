import json
import logging
import asyncio
import httpx
import requests
import re
from typing import Any, Optional, Union
from llama_index.core.llms import (
    CustomLLM,
    CompletionResponse,
    CompletionResponseGen,
    ChatResponse,
    ChatResponseGen,
    LLMMetadata,
    ChatMessage,
)
from llama_index.core.memory import ChatMemoryBuffer
from llama_index.core.llms.callbacks import llm_completion_callback, llm_chat_callback
from llama_index.core.workflow import (
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
    ErrorEvent,
)
from .tools.executor import ToolExecutor
from .analysis_service import AnalysisService

# from .agents.orchestrated_agent import OrchestratedAnalysisAgent
# [V2 Architecture] Import the new orchestrator
from .agents.orchestrated_agent_v2 import OrchestratedAnalysisAgentV2

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
            is_chat_model=True,
        )

    @llm_completion_callback()
    async def acomplete(
        self, prompt: str, json_mode: bool = False, **kwargs: Any
    ) -> CompletionResponse:
        """核心非串流回傳，支持 JSON 模式"""
        is_openai = "/v1/chat/completions" in self.api_url

        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }

        if not is_openai and json_mode:
            payload["format"] = "json"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(self.api_url, json=payload)
                response.raise_for_status()
                result = response.json()

                if is_openai:
                    # OpenAI / VLLM Format
                    content = result["choices"][0]["message"]["content"]
                else:
                    # Ollama Format
                    content = result.get("message", {}).get("content", "")

                return CompletionResponse(text=content)
        except Exception as e:
            provider = "OpenAI/VLLM" if is_openai else "Ollama"
            logger.error(f"{provider} Async 連線錯誤: {str(e)}")
            raise ConnectionError(f"無法非同步連線至 {provider}: {str(e)}")

    async def astream_complete(
        self, prompt: str, **kwargs: Any
    ) -> CompletionResponseGen:
        """核心串流回傳，用於即時打字機效果"""
        is_openai = "/v1/chat/completions" in self.api_url

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

                        if is_openai:
                            # OpenAI Format: data: {...}
                            if line.startswith("data: "):
                                data_str = line[6:].strip()
                                if data_str == "[DONE]":
                                    break
                                try:
                                    chunk = json.loads(data_str)
                                    if len(chunk["choices"]) > 0:
                                        delta = chunk["choices"][0]["delta"]
                                        content = delta.get("content", "")
                                        if content:
                                            yield CompletionResponse(
                                                text=content, delta=content
                                            )
                                except json.JSONDecodeError:
                                    pass
                        else:
                            # Ollama Format: {...}
                            try:
                                chunk = json.loads(line)
                                if "message" in chunk:
                                    content = chunk["message"].get("content", "")
                                    yield CompletionResponse(
                                        text=content, delta=content
                                    )
                                if chunk.get("done"):
                                    break
                            except json.JSONDecodeError:
                                pass
        except Exception as e:
            provider = "OpenAI/VLLM" if is_openai else "Ollama"
            logger.error(f"{provider} Stream 連線錯誤: {str(e)}")
            raise ConnectionError(f"無法串流連線至 {provider}: {str(e)}")

    @llm_completion_callback()
    def complete(self, prompt: str, **kwargs: Any) -> CompletionResponse:
        is_openai = "/v1/chat/completions" in self.api_url
        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        try:
            response = requests.post(self.api_url, json=payload, timeout=self.timeout)
            response.raise_for_status()
            result = response.json()

            if is_openai:
                content = result["choices"][0]["message"]["content"]
            else:
                content = result.get("message", {}).get("content", "")

            return CompletionResponse(text=content)
        except Exception as e:
            provider = "OpenAI/VLLM" if is_openai else "Ollama"
            logger.error(f"{provider} Sync 連線錯誤: {str(e)}")
            raise ConnectionError(f"無法同步連線至 {provider}: {str(e)}")

    @llm_completion_callback()
    def stream_complete(self, prompt: str, **kwargs: Any) -> CompletionResponseGen:
        yield self.complete(prompt, **kwargs)

    async def achat(self, messages, **kwargs: Any) -> ChatResponse:
        """
        非阻塞異步聊天 (async chat)。
        直接使用 httpx.AsyncClient，避免阻塞 event loop。
        這是防止分析期間其他 API 無法回應的關鍵方法。
        """
        is_openai = "/v1/chat/completions" in self.api_url

        # 將 ChatMessage 轉換為 dict 格式
        formatted_messages = []
        for msg in messages:
            role = str(msg.role.value) if hasattr(msg.role, "value") else str(msg.role)
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            formatted_messages.append({"role": role, "content": content})

        payload = {
            "model": self.model_name,
            "messages": formatted_messages,
            "stream": False,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(self.api_url, json=payload)
                response.raise_for_status()
                result = response.json()

                if is_openai:
                    content = result["choices"][0]["message"]["content"]
                else:
                    content = result.get("message", {}).get("content", "")

                from llama_index.core.llms import ChatMessage as CM, MessageRole

                return ChatResponse(
                    message=CM(role=MessageRole.ASSISTANT, content=content),
                    raw=result,
                )
        except Exception as e:
            provider = "OpenAI/VLLM" if is_openai else "Ollama"
            logger.error(f"{provider} Async Chat 連線錯誤: {str(e)}")
            raise ConnectionError(f"無法非同步聊天至 {provider}: {str(e)}")


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
        timeout: int = 600,
    ):
        super().__init__(timeout=timeout, verbose=True)
        self.tool_executor = tool_executor
        self.analysis_service = analysis_service
        # 使用自定義極速引擎 (兼容 Ollama 與 VLLM/OpenAI)
        self.llm = CustomOllamaLLM(
            model_name=model_name, api_url=ollama_api_url, timeout=float(timeout)
        )
        self.llm_json = self.llm

        if "/v1" in ollama_api_url:
            logger.info(f"Initialized VLLM Mode: {ollama_api_url}")
        else:
            logger.info(f"Initialized Ollama Mode: {ollama_api_url}")

        # [V2 Architecture] Use OrchestratedAnalysisAgentV2
        self.orchestrator = OrchestratedAnalysisAgentV2(
            self.llm, self.tool_executor, analysis_service=self.analysis_service
        )
        # [NEW] Feature Flag (Enabled for Phase 3/4)
        self.USE_NEW_ARCHITECTURE = True

    @staticmethod
    def _convert_cn_to_an(text: str) -> str:
        """
        將中文數字轉換為阿拉伯數字 (支持 0-999)
        例如: "第一筆" -> "第1筆", "一百二十" -> "120"
        """
        cn_map = {
            "零": 0,
            "一": 1,
            "二": 2,
            "三": 3,
            "四": 4,
            "五": 5,
            "六": 6,
            "七": 7,
            "八": 8,
            "九": 9,
            "十": 10,
            "百": 100,
        }

        def cn_str_to_int(cn_str):
            num = 0
            # 處理百位
            if "百" in cn_str:
                parts = cn_str.split("百")
                hundreds = parts[0]
                num += cn_map.get(hundreds, 1) * 100 if hundreds else 100
                rest = parts[1] if len(parts) > 1 else ""
            else:
                rest = cn_str

            # 處理十位
            if "十" in rest:
                parts = rest.split("十")
                tens = parts[0]
                if not tens:
                    num += 10
                else:
                    num += cn_map.get(tens, 1) * 10
                ones = parts[1] if len(parts) > 1 else ""
                if ones:
                    num += cn_map.get(ones, 0)
            else:
                num += cn_map.get(rest, 0)
            return str(num)

        # 匹配連續的中文數字
        try:
            matches = list(re.finditer(r"[零一二三四五六七八九十百]+", text))
            # 倒序替換以免索引跑掉
            new_text = list(text)
            for m in reversed(matches):
                s, e = m.span()
                new_text[s:e] = cn_str_to_int(m.group())
            return "".join(new_text)
        except Exception:
            return text

    @step
    async def route_intent(
        self, ctx: Context, ev: StartEvent
    ) -> IntentEvent | ErrorEvent:
        # 向前端發送初步反饋
        ctx.write_event_to_stream(ProgressEvent(msg="─ 正在快速匹配指令路徑..."))

        # [PRE-PROCESS] 中文數字轉阿拉伯數字
        raw_query = getattr(ev, "query", "").strip()
        query = self._convert_cn_to_an(raw_query)

        file_id = getattr(ev, "file_id", None)
        session_id = getattr(ev, "session_id", None)

        # [AUTO-RESET] 新對話開始時，強制清除殘留的停止/立即回答信號
        if session_id:
            try:
                self.tool_executor.analysis_service.clear_stop_signal(session_id)
            except Exception:
                pass
        history = getattr(ev, "history", "")

        if not query:
            return ErrorEvent(error="未提供問題", session_id=session_id)

        # --- 智能意圖分類 (LLM-First Intent Classification) ---
        query_lower = query.lower().strip()

        # Step 1: 極簡短路 — 只攔截最明確的寒暄 (完全不需要 LLM)
        trivial_chat_exact = [
            "謝謝",
            "好的",
            "了解",
            "收到",
            "明白",
            "ok",
            "好",
            "你好",
            "嗨",
            "hello",
            "hi",
            "hey",
            "感謝",
            "辛苦了",
            "不用了",
            "沒事",
        ]
        if query_lower in trivial_chat_exact:
            intent = "chat"
            return IntentEvent(
                query=query,
                intent=intent,
                file_id=file_id,
                session_id=session_id,
                history=history,
                mode=ev.mode,
                suspect_pool=getattr(ev, "suspect_pool", []),
            )

        # Step 2: 所有其他情況 — 交給 LLM 判斷 (含上下文)
        has_file = bool(file_id)
        has_history = bool(history and len(history) > 50)

        try:
            # 對超長訊息做預處理: 額外提取末尾給 LLM 參考
            tail_hint = ""
            if len(query) > 300:
                tail_text = query[-200:]
                tail_hint = (
                    f"\n\nCRITICAL: The message above is very long ({len(query)} chars). "
                    f"The user likely pasted previous analysis results and added their REAL request at the end.\n"
                    f"Focus on the LAST part of the message to determine intent:\n"
                    f'"""{tail_text}"""\n'
                )

            classify_prompt = (
                "You are an intent classifier for an industrial data analysis system.\n"
                "Classify the user message as 'analysis' or 'chat'. Reply with ONLY one word.\n\n"
                "Rules:\n"
                "- analysis: User wants to START or RE-RUN data analysis, draw charts, "
                "detect anomalies, check correlations, run diagnostics, or perform optimization.\n"
                "- chat: User is asking questions, requesting explanations, "
                "following up on previous results, greeting, or having a general conversation.\n"
                "- chat: User wants to SIMPLIFY, SUMMARIZE, REPHRASE, or REORGANIZE previous results.\n\n"
                "KEY DISTINCTION:\n"
                "- 'REFERENCES past analysis' (剛才分析說..., 上次的異常..., 那個結果是什麼意思) → chat\n"
                "- 'REQUESTS new action' (幫我分析, 診斷一下, 畫趨勢圖, 偵測異常) → analysis\n"
                "- 'ASKS for simpler explanation' (簡單說明, 總結一下, 用白話文, 看不懂) → chat\n\n"
                "Examples:\n"
                "- '幫我分析這份數據的異常' → analysis\n"
                "- '剛才分析說 BCDRY 有異常趨勢，這是什麼意思？' → chat\n"
                "- '畫出 A15 的趨勢圖' → analysis\n"
                "- '為什麼上次說要檢查 A15？' → chat\n"
                "- '診斷異常原因' → analysis\n"
                "- '幫我總結一下結果' → chat\n"
                "- '可以用比較簡單的說明嗎?' → chat\n"
                "- '列出重點就好' → chat\n"
                "- '太複雜了, 簡單講' → chat\n"
                "- 'BCDRY 是什麼參數？' → chat\n"
                "- '這份資料有哪些欄位？' → analysis\n"
                "- '重新跑一次 Hotelling T2' → analysis\n"
                "- '剛才的 T2 分數代表什麼？' → chat\n\n"
                f"Context: User {'HAS' if has_file else 'has NO'} uploaded data file. "
                f"{'Previous conversation exists.' if has_history else 'This is a new conversation.'}\n\n"
                f"User message: {query}\n"
                f"{tail_hint}"
                "Answer:"
            )
            response = await self.llm.acomplete(classify_prompt)
            raw_intent = str(response.text).strip().lower()

            if "analysis" in raw_intent:
                intent = "analysis"
            else:
                intent = "chat"

            logger.info(
                f"[LLM Intent] query='{query[:50]}' → {intent} (raw: {raw_intent})"
            )
        except Exception as e:
            # LLM 失敗時的 Fallback: 如果有檔案就預設 analysis，否則 chat
            logger.warning(f"[LLM Intent] Classification failed: {e}, using fallback")
            intent = "analysis" if has_file else "chat"

        return IntentEvent(
            query=query,
            intent=intent,
            file_id=file_id,
            session_id=session_id,
            history=history,
            mode=ev.mode,
            suspect_pool=getattr(ev, "suspect_pool", []),
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
    ) -> Union[AnalysisEvent, TranslationEvent, SummarizeEvent, VisualizingEvent]:
        intent = (ev.intent or "").strip().lower()
        query_lower = ev.query.lower()

        # --- 視覺化快車道 (Visualization Fast-Track) ---
        # 如果用戶只是想畫圖，直接調用 get_time_series_data 後出圖，完全跳過 LLM 分析循環
        viz_keywords = ["畫", "繪製", "顯示", "show", "plot", "draw"]
        chart_keywords = ["圖", "趨勢", "chart", "trend", "graph", "折線", "曲線"]
        # 排除含有深度分析意圖的語句
        deep_analysis_keywords = [
            "分析",
            "診斷",
            "異常",
            "原因",
            "為什麼",
            "影響",
            "關聯",
            "偵測",
            "比較",
            "對比",
        ]

        has_viz_intent = any(kw in query_lower for kw in viz_keywords)
        has_chart_intent = any(kw in query_lower for kw in chart_keywords)
        has_deep_intent = any(kw in query_lower for kw in deep_analysis_keywords)

        if (
            "analysis" in intent
            and (has_viz_intent or has_chart_intent)
            and not has_deep_intent
            and ev.file_id
        ):
            summary = self.tool_executor.analysis_service.load_summary(
                ev.session_id, ev.file_id
            )
            if summary:
                params_list = summary.get("parameters", [])
                mappings = summary.get("mappings", {}) if summary else {}
                total_rows = summary.get("total_rows", 0)

                # 從 query 中提取參數名稱 (精確匹配已知欄位名)
                extracted_params = []
                query_upper = ev.query.upper()
                for p in params_list:
                    if p.upper() in query_upper:
                        extracted_params.append(p)

                # 如果沒有精確匹配到，嘗試用 regex 提取工業感測器代碼模式
                if not extracted_params:
                    sensor_matches = re.findall(
                        r"[A-Z][A-Z0-9]*[-_][A-Z0-9]+[-_][A-Z0-9]+", ev.query
                    )
                    for sm in sensor_matches:
                        # 大小寫不敏感匹配
                        for p in params_list:
                            if p.upper() == sm.upper():
                                extracted_params.append(p)
                                break

                if extracted_params:
                    ctx.write_event_to_stream(
                        ProgressEvent(
                            msg=f"-- [快車道] 偵測到繪圖指令，直接擷取 {', '.join(extracted_params)} 的時間序列數據..."
                        )
                    )

                    # 直接呼叫 get_time_series_data 工具
                    tool_params = {
                        "file_id": ev.file_id,
                        "parameters": extracted_params,
                    }

                    # 如果 query 中有指定範圍，也加上
                    range_patterns = [
                        (
                            r"第?\s*(\d+)\s*(?:筆)?\s*(?:到|至|~|～|to|-|與)\s*第?\s*(\d+)\s*(?:筆)?",
                            "range",
                        ),
                        (r"(\d+)\s*[~-]\s*(\d+)", "range"),
                    ]
                    for rp, rtype in range_patterns:
                        rm = re.search(rp, ev.query)
                        if rm and rtype == "range":
                            tool_params["target_segments"] = (
                                f"{rm.group(1)}-{rm.group(2)}"
                            )
                            break

                    try:
                        chart_data = await self.tool_executor.execute_tool(
                            "get_time_series_data", tool_params, ev.session_id
                        )

                        if (
                            isinstance(chart_data, dict)
                            and "data" in chart_data
                            and chart_data["data"]
                        ):
                            ctx.write_event_to_stream(
                                ProgressEvent(
                                    msg=f"-- [快車道] 數據擷取完成 ({chart_data.get('total_points', 0)} 筆)，正在繪製圖表..."
                                )
                            )
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
                                suspect_pool=ev.suspect_pool,
                            )
                        else:
                            # 數據獲取失敗，回退到正常分析流程
                            ctx.write_event_to_stream(
                                ProgressEvent(
                                    msg="-- [快車道] 數據擷取失敗，改走標準分析流程..."
                                )
                            )
                    except Exception as e:
                        logger.warning(
                            f"Visualization Fast-Track failed: {e}, falling back to analysis"
                        )
                        ctx.write_event_to_stream(
                            ProgressEvent(
                                msg="-- [快車道] 快速繪圖失敗，改走標準分析流程..."
                            )
                        )
                else:
                    # [CLARIFICATION] 用戶想畫圖但沒說畫什麼
                    # 停止猜測，直接反問用戶
                    ctx.write_event_to_stream(
                        ProgressEvent(msg="-- [快車道] 偵測到繪圖意圖，但未指定參數...")
                    )
                    return SummarizeEvent(
                        data={
                            "direct_reply": (
                                "請問您想要繪製哪一個參數的趨勢圖？\n\n"
                                "請明確指定參數名稱（例如：「畫 **(參數名)** 的趨勢圖」）。\n"
                                "目前系統無法得知您的繪圖目標，請補充説明。"
                            )
                        },
                        query=ev.query,
                        file_id=ev.file_id,
                        session_id=ev.session_id,
                        history=ev.history,
                        mode=ev.mode,
                    )

        # --- 零延遲快車道 (Metadata Fast-Track) ---
        # 如果只是想知道欄位清單、行數或檔案摘要，沒必要動用 AI 大腦
        # 注意：必須非常謹慎，只攔截純粹的「檔案基本資訊查詢」
        summary_keywords = [
            "有哪些欄位",
            "欄位清單",
            "所有參數",
            "幾筆資料",
            "總行數",
            "幾行",
            "這份檔案",
            "簡介",
            "檔案概況",
            "資料概況",
            "資料品質",
            "品質概況",
            "檢視資料品質概況",
            "資料概況",
            "資料品質",
            "品質概況",
        ]
        # 排除深度分析意圖 (避免「分析摘要」「數據概況分析」被誤攔截)
        metadata_exclude_keywords = [
            "分析",
            "診斷",
            "異常",
            "原因",
            "為什麼",
            "影響",
            "關聯",
            "偵測",
            "比較",
            "對比",
            "偏離",
            "Z-Score",
            "趨勢",
            "變化",
            "問題",
            "故障",
            "根因",
            "追查",
        ]
        has_metadata_intent = any(kw in query_lower for kw in summary_keywords)
        has_analysis_intent = any(kw in query_lower for kw in metadata_exclude_keywords)
        if "analysis" in intent and has_metadata_intent and not has_analysis_intent:
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
                        "**數據品質警訊**: \n- " + "\n- ".join(quality_msg) + "\n\n"
                    )
                else:
                    content += "**數據品質**: 數據完整，無明顯缺失或稀疏欄位。\n\n"

                content += "您可以問我關於這些參數的趨勢、異常偵測或相關性分析。"

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
                    data={"direct_reply": content, "all_steps_results": []},
                    query=ev.query,
                    file_id=ev.file_id,
                    session_id=ev.session_id,
                    history=ev.history,
                    mode=ev.mode,
                    row_count=total_rows,
                    col_count=len(params_list),
                    mappings=summary.get("mappings", {}),
                    suspect_pool=ev.suspect_pool,
                )

        if "analysis" in intent:
            return AnalysisEvent(
                query=ev.query,
                file_id=ev.file_id,
                session_id=ev.session_id,
                history=ev.history,
                mode=ev.mode,
                suspect_pool=ev.suspect_pool,
            )
        return TranslationEvent(
            query=ev.query,
            file_id=ev.file_id,
            session_id=ev.session_id,
            history=ev.history,
            mode=ev.mode,
            suspect_pool=ev.suspect_pool,
        )

    @step
    async def execute_analysis(
        self, ctx: Context, ev: AnalysisEvent
    ) -> Union[AnalysisEvent, VisualizingEvent, SummarizeEvent]:
        """
        [Local Step] 執行智慧分析決策 (支持最多 3 步的循環診斷)
        """
        import re  # Import at method level to avoid UnboundLocalError

        # [INTERRUPT CHECK] 檢查是否收到立即回答指令
        if self.tool_executor.analysis_service.is_generation_stopped(ev.session_id):
            ctx.write_event_to_stream(
                ProgressEvent(msg="⚡ 收到立即回答指令，中止分析並生成結論...")
            )
            # 清除信號以免影響下次
            self.tool_executor.analysis_service.clear_stop_signal(ev.session_id)

            # 使用目前累積的結果直接總結
            return SummarizeEvent(
                data={
                    "all_steps_results": ev.prev_results,
                    "reason": "user_interruption",
                },
                query=ev.query,
                file_id=ev.file_id,
                session_id=ev.session_id,
                history=ev.history,  # 傳遞目前為止的對話歷史
                mode=ev.mode,
                suspect_pool=ev.suspect_pool,
            )

        summary = self.tool_executor.analysis_service.load_summary(
            ev.session_id, ev.file_id
        )
        params_list = summary.get("parameters", []) if summary else []
        total_cols = len(params_list)
        total_rows = summary.get("total_rows", 0) if summary else 0

        # --- [NEW] 參數提取與標準化 (Parameter Extraction) ---
        # 如果 suspect_pool 為空，嘗試從 query 中提取參數名稱
        if not ev.suspect_pool or len(ev.suspect_pool) == 0:
            # 提取參數名稱（匹配常見的參數命名模式）
            # 例如：METROLOGY-P21-MO1-SP, FORMULA-DCS_A15, PRESSDRY-DCS_A107
            param_pattern = r"\b([A-Z][A-Z0-9_-]*(?:-[A-Z0-9_-]+)+)\b"
            detected_params = re.findall(param_pattern, ev.query)

            # 過濾：只保留在實際參數列表中的參數
            if detected_params and params_list:
                valid_params = [p for p in detected_params if p in params_list]
                if valid_params:
                    ev.suspect_pool = list(
                        dict.fromkeys(valid_params)
                    )  # 去重並保持順序
                    logger.info(
                        f"[Parameter Extraction] 從 query 中提取到目標參數: {ev.suspect_pool}"
                    )

        # 只有在第一步顯示詳細檢索訊息，後續步數顯示簡潔進度
        if ev.step_count == 1:
            ctx.write_event_to_stream(
                ProgressEvent(
                    msg=f"─ 正在初始化分析環境，鎖定 {total_cols} 個原始欄位..."
                )
            )

        mappings = summary.get("mappings", {}) if summary else {}

        # --- [NEW] 語意範圍預處理器 (Range Pre-processor) ---
        # 捕捉各種寫法並標準化
        range_patterns = [
            (
                r"第?\s*(\d+)\s*(?:筆)?\s*(?:到|至|~|～|to|-|與)\s*第?\s*(\d+)\s*(?:筆)?",
                "range",
            ),
            (r"第?\s*(\d+)\s*(?:筆)?\s*(?:之後|以後|起|onwards|\+)", "after"),
            (r"第?\s*(\d+)\s*(?:筆)?\s*(?:以前|之前|止|before|up to)", "before"),
            (r"(?:第)\s*(\d+)\s*(?:筆)", "single"),
            (r"(\d+)\s*(?:-|~|～|to)\s*(\d+)", "range"),  # 簡版如 30-50
        ]

        detected_range = None
        standard_format = None
        for pattern_str, p_type in range_patterns:
            match = re.search(pattern_str, ev.query)
            if match:
                groups = match.groups()
                if p_type == "range":
                    s, e = groups
                    standard_format = f"{s}-{e}"
                    detected_range = (
                        f"【偵測到目標範圍】: {s} 到 {e} (標準格式: {standard_format})"
                    )
                elif p_type == "after":
                    s = groups[0]
                    if total_rows > 0:
                        standard_format = f"{s}-{total_rows - 1}"
                        detected_range = f"【偵測到開放範圍】: 第 {s} 筆之後 (0-indexed 範圍: {standard_format})"
                    else:
                        standard_format = f"{s}+"
                        detected_range = f"【偵測到開放範圍】: 第 {s} 筆之後"
                elif p_type == "before":
                    e = groups[0]
                    standard_format = f"0-{e}"
                    detected_range = f"【偵測到開放範圍】: 第 {e} 筆以前 (0-indexed 範圍: {standard_format})"
                elif p_type == "single":
                    idx = groups[0]
                    standard_format = str(idx)
                    detected_range = f"【偵測到目標單點】: 第 {idx} 筆"
                break

        # 填充 suspect_range（如果尚未設定）
        if standard_format and not ev.suspect_range:
            ev.suspect_range = standard_format
            logger.info(
                f"[Range Extraction] 從 query 中提取到目標範圍: {ev.suspect_range}"
            )

        range_mandate = ""
        if detected_range:
            range_mandate = (
                f"\n!!! 重要：系統已自動識別分析區間 !!!\n"
                f"{detected_range}\n"
                f'請務必在工具參數 (如 target_segments) 中填入: "{standard_format}"。\n'
                f"絕對禁止隨意更改或縮減此範圍。\n"
            )
            # 在串流中給用戶反饋，增加透明度
            if ev.step_count == 1:
                ctx.write_event_to_stream(
                    ProgressEvent(
                        msg=f"─ [護欄同步] 偵測到關鍵索引 {standard_format}，已自動補全分析範圍參數..."
                    )
                )

        # [NEW] Orchestrate the analysis process if enabled
        if self.USE_NEW_ARCHITECTURE and ev.step_count == 1:
            logger.info("Starting Orchestrated Analysis Agent...")

            # [RESUME] Detect "continue" intent from user query
            continue_keywords = [
                "繼續",
                "繼續分析",
                "更深入",
                "深入分析",
                "接著分析",
                "再分析",
                "進一步",
                "continue",
                "keep going",
                "go deeper",
            ]
            is_resume = (
                any(kw in ev.query.lower() for kw in continue_keywords)
                and hasattr(self, "orchestrator")
                and self.orchestrator.has_saved_state(ev.session_id)
            )

            if is_resume:
                logger.info(
                    f"[RESUME] Detected continue intent, resuming from saved state"
                )

            # Re-wrap start info with enriched query
            state_query = ev.query
            if range_mandate:
                state_query += "\n" + range_mandate

            start_data = StartEvent(
                query=state_query,
                file_id=ev.file_id,
                session_id=ev.session_id,
                history=ev.history or "",
                suspect_pool=ev.suspect_pool,
                mode=ev.mode,
            )

            # Summary enrichment
            sum_data = summary if summary else {}
            sum_data["parameters"] = params_list

            final_resp = {"response": "Analysis failed or was interrupted."}

            try:
                # [NEW] Pure chat detection: conversational requests that don't need tools
                is_chat_only = (
                    not is_resume
                    and hasattr(self.orchestrator, "_is_chat_only")
                    and self.orchestrator._is_chat_only(state_query)
                )

                # Follow-up detection: if not explicit resume but has cached state and looks like followup
                is_followup = (
                    not is_resume
                    and not is_chat_only
                    and hasattr(self.orchestrator, "_is_followup")
                    and self.orchestrator.has_saved_state(ev.session_id)
                    and self.orchestrator._is_followup(state_query)
                )

                if is_chat_only:
                    logger.info(
                        "[CHAT_ONLY] Detected pure chat request, bypassing analysis pipeline"
                    )
                    async for event in self.orchestrator.run_chat_only(start_data):
                        if isinstance(event, dict):
                            final_resp = event
                        else:
                            ctx.write_event_to_stream(event)
                        await asyncio.sleep(0)
                elif is_followup:
                    async for event in self.orchestrator.run_followup(
                        start_data, sum_data
                    ):
                        if isinstance(event, dict):
                            final_resp = event
                        else:
                            ctx.write_event_to_stream(event)
                        await asyncio.sleep(0)
                else:
                    async for event in self.orchestrator.run_analysis(
                        start_data, sum_data, resume=is_resume
                    ):
                        if isinstance(event, dict):
                            final_resp = event
                        else:
                            ctx.write_event_to_stream(event)
                        await asyncio.sleep(0)
            except Exception as e:
                logger.error(f"Orchestrator error: {e}")
                final_resp["response"] = f"分析過程發生錯誤: {str(e)}"

            # Ensure final_resp is a dict before accessing
            if not isinstance(final_resp, dict):
                try:
                    # Attempt to parse if it's a JSON string
                    if isinstance(final_resp, str) and final_resp.strip().startswith(
                        "{"
                    ):
                        import json

                        final_resp = json.loads(final_resp)
                    else:
                        final_resp = {"response": str(final_resp)}
                except Exception:
                    final_resp = {"response": str(final_resp)}

            # Return as SummarizeEvent (which workflow handles by summarizing or finishing)
            final_decision_text = ""
            if isinstance(final_resp, dict):
                final_decision_text = final_resp.get("response", "")
            else:
                final_decision_text = str(final_resp)

            # [FIX] Pass through V2's structured step history instead of hardcoding empty
            v2_steps = []
            v2_final_decision = final_decision_text
            if isinstance(final_resp, dict):
                v2_steps = final_resp.get("all_steps_results", [])
                v2_final_decision = final_resp.get(
                    "final_decision", final_decision_text
                )

            return SummarizeEvent(
                data={
                    "final_decision": v2_final_decision,
                    "all_steps_results": v2_steps,
                },
                query=ev.query,
                file_id=ev.file_id,
                session_id=ev.session_id,
                history=ev.history,
                mode=ev.mode,
                row_count=total_rows,
                col_count=total_cols,
                mappings=mappings,
                suspect_pool=ev.suspect_pool,
            )

        # --- 安全閥：解鎖深度診斷分析 ---
        MAX_STEPS = 30
        is_last_step = ev.step_count >= MAX_STEPS

        tool_specs = self.tool_executor.list_tools()

        # --- 硬核限制：Step 1 工具選擇策略 ---
        if ev.mode == "deep" and ev.step_count == 1:
            # 檢查是否有使用者指定的目標參數
            has_user_targets = ev.suspect_pool and len(ev.suspect_pool) > 0

            if has_user_targets:
                # 【Targeted Analysis】：有目標參數時，允許使用分析工具
                # 但要在 Prompt 中強制要求使用目標參數，不能用 'all'
                ctx.write_event_to_stream(
                    ProgressEvent(
                        msg=f"─ 目標導向分析啟動：將優先分析使用者指定的 {len(ev.suspect_pool)} 個目標參數..."
                    )
                )
            else:
                # 【Global Sweep】：無目標參數時，Step 1 只能觀察，不能跳演算法
                forbidden_step1 = [
                    "hotelling_t2_analysis",
                    "systemic_pca_analysis",
                    "causal_relationship_analysis",
                    "multivariate_anomaly_detection",
                    "analyze_feature_importance",
                ]
                tool_specs = [t for t in tool_specs if t["name"] not in forbidden_step1]
                ctx.write_event_to_stream(
                    ProgressEvent(
                        msg="─ 5-Why 診斷啟動：第一步已強制鎖定為「數據觀察與驗證」階段。"
                    )
                )

        # --- 欄位清單智慧分類與物理名稱轉譯 (Categorized Column Display) ---
        # 排除包含 ID, TIME, CONTEXT 等關鍵字的欄位作為 Target
        id_keywords = ["ID", "TIME", "CONTEXT", "LOT", "WAFER", "DATE"]
        metadata_cols = [
            p for p in params_list if any(k in p.upper() for k in id_keywords)
        ]
        core_features = [p for p in params_list if p not in metadata_cols]

        mapping_info = [f"{p} ({mappings.get(p, p)})" for p in core_features[:20]]

        all_columns_display = (
            f"【核心數值特徵 (可用於 Target ({len(core_features)}個)】: {', '.join(mapping_info)}...\n"
            f"【中繼/ID 欄位 (不可作為 Target ({len(metadata_cols)}個)】: {', '.join(metadata_cols[:10])}...\n"
            "AI 提示：嚴禁選擇「ID 欄位」作為分析 target。請優先選擇數值型核心特徵。"
        )

        # 構建過去步驟的背景資訊
        history_context = ""
        simplified_history = []
        if ev.prev_results:
            # 僅保留關鍵結果，縮減 Token
            for r in ev.prev_results:
                # [TOKEN OPTIMIZATION] 針對大數據工具進行結果摘要
                # 如果是 get_time_series_data，絕對不要將 raw data 塞回 context
                if r.get("tool") == "get_time_series_data":
                    res_data = r.get("result", {})
                    if isinstance(res_data, dict) and "data" in res_data:
                        # 只保留 metadata，移除實際數據點
                        truncated_result = str(
                            {
                                "status": "success",
                                "message": "Time series data retrieved successfully",
                                "parameters": res_data.get("parameters"),
                                "total_points": res_data.get("total_points"),
                                "target_range": res_data.get("target_range"),
                                "note": "Data omitted for token optimization (available in chart)",
                            }
                        )
                    else:
                        truncated_result = str(res_data)[:200]
                else:
                    # 一般工具結果：截斷過長的輸出以節省 Context
                    raw_result = str(r.get("result", ""))
                    truncated_result = (
                        raw_result[:800] + "...(略)"
                        if len(raw_result) > 800
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

        # --- 動態追蹤 Why 層級、證據回溯與修正護欄 ---
        current_why = 1
        hallucination_correction = ""
        last_monologue = ""
        key_evidence = ""

        if ev.prev_results:
            last_r = ev.prev_results[-1]
            last_monologue = last_r.get("monologue", "")

            # A. 提取 Why 層級 (掃描全部歷史，取最高值，防止倒退)
            max_why_seen = 1
            for r in ev.prev_results:
                mono = r.get("monologue", "")
                why_matches = re.findall(r"\[Why\s*#(\d+)\]", mono)
                if why_matches:
                    max_why_seen = max(max_why_seen, max(int(w) for w in why_matches))
            current_why = max_why_seen

            # 如果最後一步已含 [Conclusion]，代表該層 Why 已結案，應進入下一層
            if "[Conclusion]" in last_monologue:
                current_why = max_why_seen + 1
                logger.info(
                    f"[Why Tracker] Last step concluded Why #{max_why_seen}, advancing to Why #{current_why}"
                )

            # B. 找尋關鍵數據證據 (例如 Hotelling T2 的 Top 3)
            all_summaries = []
            for r in ev.prev_results:
                res = r.get("result", {})
                if isinstance(res, dict) and "top_3_summary" in res:
                    all_summaries.append(
                        f"第 {r.get('step')} 步發現: {res['top_3_summary']}"
                    )
            if all_summaries:
                key_evidence = "\n【關鍵歷史證據 (絕對優先參考)】:\n" + "\n".join(
                    all_summaries
                )

            # C. 修正強行關聯幻覺
            if "242" in last_monologue and "20" in last_monologue:
                hallucination_correction = "【核心修正令】偵測到前序步驟錯誤地將「第 242 筆」與「第 20 筆」進行了關聯。這是一個邏輯錯誤。第 242 筆是全域異常點，而第 20 筆是您的目標。請絕對禁止再說 242 代表 20，專注於分析第 20 筆跟正常數據的差異。"

        history_context = (
            "\n### 前序分析結果摘要 (含數據記憶) ###\n"
            + json.dumps(simplified_history, ensure_ascii=False)
            + (key_evidence if key_evidence else "")
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

        mode_instruction = ""
        if ev.mode == "deep":
            # 檢查是否有使用者指定的目標參數（從 suspect_pool 或 query 中提取）
            has_user_targets = ev.suspect_pool and len(ev.suspect_pool) > 0

            if has_user_targets:
                # 構建目標資訊
                target_params_info = f"目標參數：{', '.join(ev.suspect_pool[:5])}{'...' if len(ev.suspect_pool) > 5 else ''}"
                target_range_info = (
                    f"目標範圍：{ev.suspect_range}"
                    if ev.suspect_range
                    else "目標範圍：全域數據"
                )

                # 使用者有指定目標參數的情況
                mode_instruction = (
                    "## 當前模式：深度診斷 (5-Why Methodology - Targeted Analysis) ##\n"
                    "你必須嚴格遵循「由淺入深、追根究底」的科學診斷邏輯：\n"
                    f"1. **【分析標的】**: \n"
                    f"   - {target_params_info}\n"
                    f"   - {target_range_info}\n"
                    f"   - **你的任務**：分析這些參數在指定範圍內的異常狀態，並找出根本原因。\n"
                    "2. **【目標參數優先令】**: \n"
                    "   - 執行 `hotelling_t2_analysis`, `compare_data_segments` 或 `analyze_feature_importance` 時，**必須**在 `parameters` 參數中傳入這些目標參數的完整名稱（逗號分隔字串）。\n"
                    "   - **禁止**使用 `'all'`，因為使用者已經明確指定了分析範圍。\n"
                    f"   - 例如：`parameters='{','.join(ev.suspect_pool[:2])}'`\n"
                    f"   - 如果有指定範圍，必須在 `target_segments` 參數中傳入：`target_segments='{ev.suspect_range}'`\n"
                    if ev.suspect_range
                    else ""
                    "3. **【診斷節奏】先目標檢、再擴展關聯**: \n"
                    "   - 第一步：使用 `hotelling_t2_analysis(parameters='使用者指定的目標參數')` 或 `compare_data_segments(parameters='使用者指定的目標參數')` 偵測目標參數的異常。\n"
                    f"     * 如果使用者指定了範圍（{ev.suspect_range}），必須在該範圍內分析。\n"
                    if ev.suspect_range
                    else "     * 如果使用者未指定範圍，分析全域數據並找出異常的筆數範圍（例如：第 242 筆）。\n"
                    "   - 第二步：使用 `get_top_correlations(target='目標參數之一')` 找出與目標參數最相關的其他參數。\n"
                    "   - 第三步：使用 `analyze_feature_importance(target='目標參數')` 或繼續深入分析第二步發現的相關參數。\n"
                    "   - 每一步都必須回扣使用者的原始問題，確保邏輯連貫性。\n"
                    f"   - **範圍鎖定原則**：{'使用者已指定範圍為 ' + ev.suspect_range + '，所有步驟必須在此範圍內分析，禁止切換到其他筆數。' if ev.suspect_range else '如果第一步發現某個筆數範圍異常（例如第 242 筆），後續所有步驟必須繼續分析該範圍，禁止突然跳到其他筆數（如 30-50 筆）。'}\n"
                    "   - **禁止隨意切換分析範圍**：如果第一步發現第 242 筆異常，後續步驟必須繼續分析第 242 筆，不能突然跳到「30-50 筆」或其他範圍。\n"
                    "3. **【領域知識交流 (Domain Exchange)】**: \n"
                    "   - 如果使用者的問題偏向「製程原理」、「物理意義交流」或「維修經驗探討」而非數據讀取，你應優先切換為專業顧問角色。\n"
                    "   - 在此情況下，使用 `action: 'finish'` 並在回覆中結合物理譯名與你的內建知識庫進行深度說明。\n"
                    "\n"
                    "**【5-Why 診斷結構規範 (核心強制執行)】**\n"
                    "1. 在每一輪的 `monologue` 中，你必須嚴格採用以下結構：\n"
                    "   - **[Why #N]**: 當前追取的異常層級 (例如：[Why #1] 解析目標參數的整體狀態)\n"
                    "   - **[Hypothesis]**: 根據數據或物理意義提出的『核心假設』(例如：懷疑是爐溫波動導致品質下降)\n"
                    "   - **[Action]**: 解釋選擇特定工具的邏輯。\n"
                    "   - **[Conclusion]**: 本步結果解讀及其與假設的對比。**必須包含邏輯連貫性檢查**：\n"
                    "     * 本步發現與使用者的原始問題（分析目標參數）有什麼關聯？\n"
                    "     * 這個發現是否支持或反駁了當前的假設？\n"
                    "     * 下一步應該繼續深入（同一個異常點/範圍），還是換一個方向？\n"
                    "     * **嚴禁**在沒有合理解釋的情況下，突然切換到不同的筆數範圍。\n"
                    "     * **異常排名報告**：如果工具返回了 `top_10_anomalies`，你必須在 Conclusion 中列出異常程度最高的前 5-10 筆資料（格式：第 X 筆, T² = Y.YY），幫助使用者快速定位問題樣本。\n"
                    "     * **背景對照**：即使在分析特定目標，也請參考全域狀態（如 `state_analysis` 中的過渡區），確認該異常是否屬於某個更大事件的一部分（例如：餘震、系統性漂移）。\n"
                    "     * **角色敘事**：如果相關性分析提供了角色標籤（如 🔥 Main Driver, ❄️ Main Suppressor），請直接在報告中使用這些分類，並發展出物理故事（例如『參數 A 作為主要驅動者，推高了數值；參數 B 作為抑制者失效...』）。\n"
                    "2. **邏輯連貫性強制令**：\n"
                    "   - 如果某個 Why 的結果與使用者問題（目標參數）無關，你必須在 Conclusion 中說明，並選擇 `action='finish'` 或調整方向。\n"
                    "   - 禁止為了湊滿 5 個 Why 而分析與目標參數無關的內容。\n"
                    "   - 每個 Why 的發現必須能串成一條清晰的因果鏈，最終指向目標參數的異常原因。\n"
                    "   - **範圍一致性原則**：如果 Why #1 發現第 X 筆異常，Why #2, #3 應該繼續深入分析第 X 筆的原因，而不是跳到其他筆數。\n"
                    "3. **追根究底令**：如果當前步發現某個內部參數是異常起因，你**必須**在 monologue 結束前提出下一層次的 Why。禁止在未推導至底層物理原因前結束分析。\n"
                    "\n"
                    "**【物理意義優先規範】**\n"
                    "- 你現在看到的欄位清單已含「物理名稱」(如：Oven Pressure)。請在思考時以此對應領域知識。\n"
                    "- 在每一輪的 `monologue` 欄位中，你必須具體回答：根據上一步的數據與物理量（如：壓力、流量），『為什麼』你現在要選擇這個工具？你想驗證什麼假設？"
                )
            else:
                # 沒有指定目標參數，使用全域掃描
                mode_instruction = (
                    "## 當前模式：深度診斷 (5-Why Methodology - Global Sweep) ##\n"
                    "你必須嚴格遵循「由淺入深、追根究底」的科學診斷邏輯：\n"
                    "1. **【全場掃描強制令】**: 為了確保診斷的最高穩定度與避免偏見，執行 `hotelling_t2_analysis`, `compare_data_segments` 或 `systemic_pca_analysis` 時，**必須**將 `parameters` 設為 `'all'`。禁止自行挑選 3-5 個參數。\n"
                    "2. **【診斷節奏】先全體檢、再鎖定病灶**: \n"
                    "   - 第一步：使用 `compare_data_segments(parameters='all')` 觀察全場單點位移。\n"
                    "   - 第二步：使用 `hotelling_t2_analysis(parameters='all')` 偵測系統性組合異常。\n"
                    "   - 兩者證據齊全後，才能鎖定具體的異常筆數範圍（例如：第 242 筆），並在後續步驟中針對該範圍進行深層維度掃描。\n"
                    "3. **【領域知識交流 (Domain Exchange)】**: \n"
                    "   - 如果使用者的問題偏向「製程原理」、「物理意義交流」或「維修經驗探討」而非數據讀取，你應優先切換為專業顧問角色。\n"
                    "   - 在此情況下，使用 `action: 'finish'` 並在回覆中結合物理譯名與你的內建知識庫進行深度說明。\n"
                    "\n"
                    "**【5-Why 診斷結構規範 (核心強制執行)】**\n"
                    "1. 在每一輪的 `monologue` 中，你必須嚴格採用以下結構：\n"
                    "   - **[Why #N]**: 當前追取的異常層級 (例如：[Why #1] 解析數據整體偏離)\n"
                    "   - **[Hypothesis]**: 根據數據或物理意義提出的『核心假設』(例如：懷疑是爐溫波動導致品質下降)\n"
                    "   - **[Action]**: 解釋選擇特定工具的邏輯。\n"
                    "   - **[Conclusion]**: 本步結果解讀及其與假設的對比。**必須包含邏輯連貫性檢查**：\n"
                    "     * 是否已成功鎖定異常範圍（例如哪幾筆資料最異常）？\n"
                    "     * 下一步是否應該針對鎖定的範圍深入挖掘？\n"
                    "     * **範圍一致性原則**：一旦鎖定異常範圍（例如第 242 筆），後續步驟必須針對該範圍挖掘原因，禁止隨意切換到其他筆數範圍。\n"
                    "     * **異常排名報告**：如果工具返回了 `top_10_anomalies`，你必須在 Conclusion 中列出異常程度最高的前 5-10 筆資料（格式：第 X 筆, T² = Y.YY），幫助使用者快速定位問題樣本。\n"
                    "     * **全域狀態掃描**：如果工具返回了 `state_analysis`（包含群集、過渡區），你必須在報告中指明系統的運作狀態（例如：正常 -> 異常 -> 過渡震盪 -> 恢復）。不要只看單點，要看過程。\n"
                    "     * **角色敘事**：如果相關性分析提供了角色標籤（如 🔥 Main Driver, ❄️ Main Suppressor），請直接在報告中使用這些分類，並發展出物理故事（例如『參數 A 作為主要驅動者，推高了數值；參數 B 作為抑制者失效...』）。\n"
                    "     * **隱沒檢查**：在報告完主要異常區間後，請主動檢查是否有「次要/隱性異常」或「過渡震盪區」，並將其作為補充發現告知使用者，不要遺漏細節。\n"
                    "2. **追根究底令**：如果當前步發現某個內部參數是異常起因，你**必須**在 monologue 結束前提出下一層次的 Why。禁止在未推導至底層物理原因前結束分析。\n"
                    "\n"
                    "**【物理意義優先規範】**\n"
                    "- 你現在看到的欄位清單已含「物理名稱」(如：Oven Pressure)。請在思考時以此對應領域知識。\n"
                    "- 在每一輪的 `monologue` 欄位中，你必須具體回答：根據上一步的數據與物理量（如：壓力、流量），『為什麼』你現在要選擇這個工具？你想驗證什麼假設？"
                )
        else:
            mode_instruction = (
                "## 當前模式：快速回應 (Quick Response) ##\n"
                "你的目標是在 **2 步內** 給出精確結論：\n"
                "1. 優先選擇最強力的單一診斷工具 (如 `hotelling_t2_analysis` 或 `compare_data_segments`)。\n"
                "2. 獲得 Top 3 貢獻度後立即結案，解釋核心原因即可。\n"
            )

        tools_json = json.dumps(tool_specs, ensure_ascii=False)
        tool_names_list = ", ".join([t["name"] for t in tool_specs])
        prompt_parts = [
            f"你是一個機靈且嚴謹的工業數據分析專家。目前是診斷的第 {ev.step_count} 步。",
            f"基礎數據資訊: 當前檔案共有 {total_rows} 行數據，{total_cols} 個欄位。",
            f"{range_mandate}",  # [核心修復] 直接注入標準化後的範圍指示
            f"數據品質警訊 (絕對事實): {quality_info}",
            f"所有可用欄位 (部分展示): {all_columns_display}",
            f"【嚴格工具名稱清單 (只能使用以下名稱，禁止臆造)】: {tool_names_list}",
            f"工具詳細規格: {tools_json}",
            f"分析目標 (Query): {ev.query}",
            f"【當前嫌疑參數池 (Suspect Pool)】: {ev.suspect_pool}",
            f"{history_context}",
            "",
            f"## 當前模式：{'深度診斷 (5-Why)' if ev.mode == 'deep' else '快速回應'} ##",
            mode_instruction,
            hallucination_correction,
            f"目前診斷層級: [Why #{current_why}]",
            "## 核心原則 (嚴格執行) ##",
            "1. **參數名稱絕對精確性 (Vital)**: \n"
            "   - 嚴格禁止對參數名稱進行任何縮寫、截斷或修改。必須與 `all_columns_display` 中的名稱完全一致 (Case-Sensitive)。\n"
            "   - **負面範例**: 若原名為 `METROLOGY-P21-MO1-SP-2SIGMA`，禁止輸出 `METROLOGY-P21` 或 `METROLOGY-P21-MO1`。這會導致分析失敗。\n"
            "   - 必須使用完整全名 (Full String Match)。\n",
            "2. **【5-Why 強制結構】**: 你的 `monologue` **必須** 嚴格遵循以下 Markdown 格式：",
            "   ```",
            f"   [Why #{current_why}]: (描述本層追查的目標)",
            "   [Hypothesis]: (根據物理意義提出的假設)",
            "   [Action]: (解釋為何選擇此工具)",
            "   [Conclusion]: (本步分析的具體結論，並宣告是否進入下一個 Why)",
            "   ```",
            "3. **對比分析 (Abnormal vs Normal)**: 任何分析都必須基於對比。解釋目標區間與基準數據的 Delta (差異)。",
            "4. **嚴禁硬拗**: 禁止編造無邏輯的因果關聯（如 242 代表 20）。",
            "5. **記憶運用**: 參考歷史結果中的 `result` 資料，不要重複執行。",
            "6. **透明獨白**: 在 `monologue` 中用繁體中文解釋你的思考路徑。",
            "7. **數據說話 (Delta-Driven)**: 任何結論都必須建立在「差異」之上 (例如：目標區間的 Z-Score 偏離基準 3 倍)。",
            f"8. **狀態提醒**: 目前是第 {ev.step_count} 步。",
            "9. **【嚴格範圍令】**: 如果使用者指定了數據範圍 (例如：30-50, 第 100 點等)，你**必須**在工具參數中使用 `target_segments` 精確對應。絕對禁止私自縮減範圍（如只看 30 點）。",
            "10. **繁體中文指令**: 你必須全通使用「繁體中文」進行思考與工具規劃。禁止使用英文。",
            "11. **【工具名稱精確令】**: `tool_name` **必須**從上方「嚴格工具名稱清單」中精確複製。禁止自行臆造或縮寫工具名稱（例如：禁止使用 `analyze_correlation`，正確名稱為 `get_correlation_matrix` 或 `get_top_correlations`）。",
            "12. **工具多樣性 (Tool Diversity)**: 嚴禁連續兩步使用相同的工具。若上一步已用 `compare_data_segments`，下一步必須切換至 `get_top_correlations` (找連動)、`analyze_feature_importance` (找權重) 或 `causal_relationship_analysis` (找因果)。單純的數值比對不應重複執行。",
            "13. **擴大搜索半徑 (Broad Scan)**: 在中間分析步驟 (Step 1~Step N-1)，請將觀察範圍擴大至 **Top 5 ~ Top 10** 個參數。寧可多查，不可漏看。但在最終報告階段，請僅摘要那些真正具有異常特徵的關鍵參數 (Key Findings Only)，不限數量。",
            "14. **【維度區分 (Crucial)】**: 使用者查詢中有兩種不同維度，你必須精確區分並使用對應的參數名：",
            '   - **`target_index` (筆/片/行)**: 指定「第幾筆資料」。例如「第30筆」→ `"target_index": "30"`；「第30~50筆」→ `"target_index": "30-50"`。',
            "   - **`target_column` (欄位/參數/感測器)**: 指定「哪個欄位」。支持**多欄位** (逗號分隔)。例如：",
            '     - 單欄位: `"target_column": "PRESSDRY-SIEMENS_D42"`',
            '     - 多欄位: `"target_column": "PRESSDRY-SIEMENS_D42,PRESSDRY-SIEMENS_D67,BCDRY-ABB_B90"`',
            '   - **組合查詢**: 「第30~50筆的 PRESSDRY-SIEMENS_D42 和 D67 有問題」→ 同時填 `"target_index": "30-50"` 和 `"target_column": "PRESSDRY-SIEMENS_D42,PRESSDRY-SIEMENS_D67"`。',
            "   - **嚴禁混用**: `target_index` 只能填數字/範圍，`target_column` 只能填欄位名稱。",
            "15. **工具參數完整性**: `target_column` 必須填寫**欄位名稱**，嚴禁填入 Index 數字。當有多個欄位需分析時，用逗號分隔即可，系統會自動分派給各工具處理。",
            "16. **防止鬼打牆**: 同一個工具禁止連續使用超過 2 次。若已重複使用，請強制切換至 Dead-End Pivot Protocol。",
            "## 輸出規範 ##",
            '1. 輸出為一個完整的 JSON 物件，包含 "action", "tool_name", "params", "monologue", "suspect_pool" 欄位。',
            '2. "tool_name" 必須是上方工具清單中的精確名稱，不可臆造。',
            '3. "monologue" 必須嚴格遵守上述 [Why] 模板。',
            '4. "suspect_pool" 應包含您目前認為與問題相關的所有感測器代碼 (List of strings)。請繼承並擴充它。',
            '4. "suspect_pool" 應包含您目前認為與問題相關的所有感測器代碼 (List of strings)。請繼承並擴充它。',
            "",
            "## 死巷突圍原則 (Dead-End Pivot Protocol) - 自動化視角切換 ##",
            "當你在某一層 Why 分析中發現「無顯著異常」、「相關性低」或「找不出原因」時，**嚴禁直接結案**。",
            "你必須主動切換分析維度，嘗試以下進階演算法來突破僵局：",
            "1. **如果 Z-Score 均正常** → 改用 `local_outlier_factor` (LOF) 偵測密度異常 (尋找躲在群體中的異類)。",
            "2. **如果 相關係數 低** → 改用 `causal_relationship_analysis` (Granger) 偵測時間序列上的因果滯後關係。",
            "3. **如果 單點數值 均正常** → 改用 `distribution_shift_analysis` (Wasserstein) 偵測整體分佈是否發生了微小的系統性偏移。",
            "4. **如果 找不到關鍵參數** → 改用 `analyze_feature_importance` (Random Forest) 進行非線性特徵篩選。",
            "規則：一旦標準工具撞牆，monologue 必須宣稱『標準視角未發現異常，切換至 [工具名] 進行深層維度掃描』。",
            "",
            "## 演算法推薦協議 (Algorithm Recommendation Protocol) ##",
            "如果上述所有內部工具都無法有效解釋現象，你必須切換為『技術顧問』角色，",
            "根據數據特徵 (Data Pattern) 在 `tool_gap` 欄位中，推薦用戶應該引入的外部演算法：",
            "- **週期性/震盪**: 建議 `Fast Fourier Transform (FFT)` 或 `Wavelet Transform`。",
            "- **微小趨勢/老化**: 建議 `Mann-Kendall Test` 或 `CUSUM (累積和控制圖)`。",
            "- **非線性複雜關係**: 建議 `XGBoost Feature Importance` 或 `Deep Autoencoder`。",
            "- **多變量因果網**: 建議 `Bayesian Network Structure Learning`。",
            "格式: 在 JSON 的 `tool_gap` 欄位中具體填寫建議的演算法名稱與理由。",
        ]
        prompt = "\n".join(prompt_parts)

        # 1. 只有第一步顯示底層對齊資訊，減少重複
        if ev.step_count == 1:
            ctx.write_event_to_stream(
                ProgressEvent(msg="─ 正在對應物理感測器譯名與特徵...")
            )
            ctx.write_event_to_stream(
                ProgressEvent(msg="─ 正在對齊歷史診斷邏輯與 5-Why 假設...")
            )

        ctx.write_event_to_stream(
            ProgressEvent(
                msg=f"**[Step {ev.step_count}]** 正在分析上下文並規劃下一步行動..."
            )
        )

        # 強制開啟 JSON 模式
        response = await self.llm.acomplete(prompt, json_mode=True)
        ctx.write_event_to_stream(
            ProgressEvent(msg="─ 決策已生成，準備執行診斷工具...")
        )

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

            # [Fix] Ensure params is a dict (handle double-serialized JSON case)
            if "params" in decision and isinstance(decision["params"], str):
                try:
                    import json

                    # Attempt to parse if it looks like a JSON object
                    cleaned_params = decision["params"].strip()
                    if cleaned_params.startswith("{"):
                        decision["params"] = json.loads(cleaned_params)
                    else:
                        decision["params"] = {}
                except Exception:
                    decision["params"] = {}

            # Final safety net: if params is still not a dict, force it
            if not isinstance(decision.get("params"), dict):
                decision["params"] = {}

            # --- [DEBUG LOGS] ---
            logger.info(f"Decision type: {type(decision)}, content: {decision}")
            logger.info(
                f"Params type: {type(decision.get('params'))}, content: {decision.get('params')}"
            )

            # --- 硬核防死循環邏輯 ---
            tool_history = []
            for r in ev.prev_results:
                p = r.get("params", {})
                if isinstance(p, str):
                    try:
                        import json

                        p = json.loads(p)
                    except Exception:
                        p = {}
                # Ensure p is a dict
                if not isinstance(p, dict):
                    p = {}

                tool_history.append(
                    (r.get("tool"), str(p.get("target") or p.get("parameter")))
                )

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

            # --- 嫌疑參數池累積邏輯 (Suspect Pool Accumulation) ---
            new_suspects = decision.get("suspect_pool", [])
            if not isinstance(new_suspects, list):
                new_suspects = []

            # 合併並去重
            current_pool = list(set(ev.suspect_pool + new_suspects))
            # 輔助：如果 tool_name 的 params 中有明確的 target/parameter，也加入 pool
            p_target = decision.get("params", {}).get("target") or decision.get(
                "params", {}
            ).get("parameter")
            if p_target and isinstance(p_target, str) and p_target != "all":
                if p_target not in current_pool:
                    current_pool.append(p_target)
            elif p_target and isinstance(p_target, list):
                for pt in p_target:
                    if pt not in current_pool:
                        current_pool.append(pt)

            # --- 工具缺口建議收集 (Tool Gap Collection) ---
            tool_gap = decision.get("tool_gap")
            if tool_gap and isinstance(tool_gap, dict):
                tool_gaps = await ctx.get("tool_gaps", default=[])
                # 避免重複建議
                existing_names = {g.get("name", "").lower() for g in tool_gaps}
                gap_name = tool_gap.get("name", "")
                if gap_name.lower() not in existing_names:
                    tool_gaps.append(tool_gap)
                    await ctx.set("tool_gaps", tool_gaps)
                    ctx.write_event_to_stream(
                        ProgressEvent(
                            msg=f"-- [工具建議] AI 建議引入: {gap_name} — {tool_gap.get('reason', '')}"
                        )
                    )

            # --- UI 優化：清理獨白中的 JSON 或代碼塊，防止黑色底框污染聊天室 ---
            if isinstance(monologue, str):
                # 移除 ```json ... ``` 或 ``` ... ``` 代碼塊
                monologue = re.sub(r"```(?:json)?.*?\n", "", monologue)
                monologue = monologue.replace("```", "")
                # 如果 AI 輸出了純 JSON 字串在 monologue，給予預設文字
                if monologue.strip().startswith("{") and monologue.strip().endswith(
                    "}"
                ):
                    monologue = "正在根據數據特徵執行進階關聯性診斷..."

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
            # [Why Conclusion Registration - Finish Path]
            if ev.mode == "deep":
                last_tool_name = ""
                last_tool_result = {}
                if ev.prev_results:
                    last_tool_name = ev.prev_results[-1].get("tool", "")
                    lr = ev.prev_results[-1].get("result", {})
                    last_tool_result = lr if isinstance(lr, dict) else {}
                await self._register_why_conclusion(
                    ctx,
                    monologue,
                    current_why,
                    last_tool_name,
                    last_tool_result,
                    ev.step_count,
                )

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
                    suspect_pool=current_pool,
                )

            # 建立顯示名稱映射
            full_display_mappings = {p: mappings.get(p, p) for p in params_list}

            # 優化：提取具體的分析結果摘要，避免 AI 混淆
            aggregated_data = {
                "monologue_history": monologue,
                "latest_analysis_results": ev.prev_results[-1].get("result")
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
                suspect_pool=current_pool,
            )

        # 否則，執行工具並進入下一步循環
        tool_name = decision.get("tool_name")
        params = decision.get("params", {})
        if not isinstance(params, dict):
            params = {}
        params["file_id"] = ev.file_id

        # [PRE-GUARD] 參數正規化：target_column → target/parameter/target_parameter, target_index → target_segments/row_index
        # 確保護欄邏輯能正確辨識 AI 已填寫的參數
        if "target_column" in params:
            tc_val = params.pop("target_column")
            if tool_name == "causal_relationship_analysis":
                # 因果分析：第一個欄位 → target_parameter，其餘 → reference_parameters
                if isinstance(tc_val, str) and "," in tc_val:
                    parts = [p.strip() for p in tc_val.split(",") if p.strip()]
                    if "target_parameter" not in params:
                        params["target_parameter"] = parts[0]
                    if "reference_parameters" not in params and len(parts) > 1:
                        params["reference_parameters"] = parts[1:]
                else:
                    if "target_parameter" not in params:
                        params["target_parameter"] = tc_val
            else:
                if "target" not in params:
                    params["target"] = tc_val
                if "parameter" not in params:
                    params["parameter"] = tc_val
        if "target_index" in params:
            ti_val = params.pop("target_index")
            if "target_segments" not in params:
                params["target_segments"] = ti_val
            if "row_index" not in params:
                params["row_index"] = ti_val

        # --- [Smart Override] 5-Why 參數選取平衡邏輯與區間護欄 ---
        # A. 區間自動繼承：如果 query 中有 30-50 且工具支援但參數漏掉，自動補齊
        if "target_segments" not in params or not params["target_segments"]:
            # 使用與 Pre-processor 一致的高階檢測模式
            range_check_patterns = [
                r"第?\s*(\d+)\s*(?:筆)?\s*(?:到|至|~|～|to|-|與)\s*第?\s*(\d+)\s*(?:筆)?",
                r"第?\s*(\d+)\s*(?:筆)?\s*(?:之後|以後|起|onwards|\+)",
                r"第?\s*(\d+)\s*(?:筆)?\s*(?:以前|之前|止|before|up to)",
                r"(\d+)\s*[~-]\s*(\d+)",
                r"第\s*(\d+)\s*(?:筆|片|個|條|列|組|號|樣本|資料)",  # 單點模式
            ]
            for rp in range_check_patterns:
                rm = re.search(rp, ev.query)
                if rm:
                    groups = rm.groups()
                    if len(groups) == 2:
                        params["target_segments"] = f"{groups[0]}-{groups[1]}"
                    elif len(groups) == 1:
                        # 簡單處理 Suffix / Prefix
                        if (
                            "之後" in rm.group(0)
                            or "以後" in rm.group(0)
                            or "+" in rm.group(0)
                        ):
                            params["target_segments"] = (
                                f"{groups[0]}-{total_rows - 1}"
                                if total_rows > 0
                                else f"{groups[0]}+"
                            )
                        elif "以前" in rm.group(0) or "之前" in rm.group(0):
                            params["target_segments"] = f"0-{groups[0]}"
                        else:
                            # 單點模式：如「第30筆」
                            params["target_segments"] = str(groups[0])

                    if params.get("target_segments"):
                        ctx.write_event_to_stream(
                            ProgressEvent(
                                msg=f"─ [護欄同步] 偵測到關鍵索引 {params['target_segments']}，已自動補齊參數..."
                            )
                        )
                    break

            # [Fallback] 當 query 中完全沒有數字範圍時 (如「整個時間段」、「比較全部數據」)
            # 且工具確實需要 target_segments，使用智慧預設
            if (
                "target_segments" not in params or not params["target_segments"]
            ) and tool_name == "compare_data_segments":
                if total_rows > 0:
                    # 預設策略：以後半段 (50%~100%) 作為 target，前半段作為 baseline
                    midpoint = total_rows // 2
                    params["target_segments"] = f"{midpoint}-{total_rows - 1}"
                    ctx.write_event_to_stream(
                        ProgressEvent(
                            msg=f"─ [護欄補齊] 未偵測到目標區間，自動採用後半段數據 ({midpoint}-{total_rows - 1}) 作為比較目標..."
                        )
                    )
                else:
                    # 極端防禦：無法取得 total_rows，使用 0-全域
                    params["target_segments"] = "0-999"
                    ctx.write_event_to_stream(
                        ProgressEvent(
                            msg="─ [護欄補齊] 無法確定數據範圍，使用預設範圍..."
                        )
                    )

        # A2. 通用必填參數自動補齊護欄：
        # 當工具需要 parameters/target/parameter 但 AI 漏傳時，
        # 嘗試從嫌疑參數池 (suspect_pool) 或 monologue 中自動提取
        tool_instance = self.tool_executor.get_tool(tool_name)
        if tool_instance:
            # 策略 A2-1: 預先檢查並 invalid 錯誤的參數 (例如 target='30')
            if tool_name == "analyze_feature_importance" and params.get("target"):
                t_val = str(params["target"]).strip()
                # 如果是純數字且長度短，視為無效行號引用，改為自動補齊
                if t_val.isdigit() and len(t_val) < 10:
                    ctx.write_event_to_stream(
                        ProgressEvent(
                            msg=f"─ [護欄修正] 偵測到無效目標 '{t_val}' (可能是行號)，嘗試自動修正為上下文中的參數..."
                        )
                    )
                    del params["target"]  # 刪除它，讓後面的邏輯補齊

            missing_keys = [
                p
                for p in tool_instance.required_params
                if p != "file_id" and not params.get(p)
            ]

            if missing_keys:
                # 嘗試從 monologue 中提取工業感測器名稱
                extracted_from_monologue = []
                if monologue:
                    import re as _re

                    extracted_from_monologue = _re.findall(
                        r"[A-Z][A-Z0-9]*[-_][A-Z0-9]+[-_][A-Z0-9]+", monologue
                    )
                    extracted_from_monologue = list(
                        dict.fromkeys(extracted_from_monologue)
                    )  # 去重保序

                for missing_key in missing_keys:
                    # 特殊處理：target_segments 從 query 中提取行號
                    if missing_key == "target_segments":
                        import re as _re2

                        # 嘗試從 query 中提取單點或區間索引
                        single_point = _re2.search(
                            r"第\s*(\d+)\s*(?:筆|片|個|條|列|組|號|樣本|資料)", ev.query
                        )
                        if single_point:
                            params["target_segments"] = single_point.group(1)
                            ctx.write_event_to_stream(
                                ProgressEvent(
                                    msg=f"─ [護欄補齊] 從用戶問題中提取到目標索引: {single_point.group(1)}，已填入 'target_segments'"
                                )
                            )
                        elif total_rows > 0:
                            # 全域 fallback：query 中無索引數字時，自動使用後半段
                            midpoint = total_rows // 2
                            params["target_segments"] = f"{midpoint}-{total_rows - 1}"
                            ctx.write_event_to_stream(
                                ProgressEvent(
                                    msg=f"─ [護欄補齊] 未偵測到具體目標區間，自動以後半段 ({midpoint}-{total_rows - 1}) 作為比較對象..."
                                )
                            )
                        continue

                    # 定義哪些 key 接受「參數名稱列表」類型的值
                    is_param_type = missing_key in (
                        "parameters",
                        "target",
                        "parameter",
                        "features",
                        "target_parameter",
                        "reference_parameters",
                    )

                    if not is_param_type:
                        continue  # concept 等其他類型的 key 無法自動補齊

                    # 策略 1：從 suspect_pool 補齊
                    if current_pool and len(current_pool) > 0:
                        # target/parameter/target_parameter 類型期望字串
                        if missing_key in ("target", "parameter", "target_parameter"):
                            # target_parameter 只取第一個
                            if missing_key == "target_parameter":
                                params[missing_key] = current_pool[0]
                            else:
                                params[missing_key] = ", ".join(current_pool)
                        elif missing_key == "reference_parameters":
                            # reference_parameters 排除已設定的 target_parameter
                            tp = params.get("target_parameter", "")
                            params[missing_key] = [p for p in current_pool if p != tp]
                        else:
                            params[missing_key] = current_pool
                        ctx.write_event_to_stream(
                            ProgressEvent(
                                msg=f"─ [護欄補齊] {tool_name} 須要 '{missing_key}' 但 AI 未提供，已從嫌疑參數池補齊: {', '.join(current_pool[:5])}"
                            )
                        )
                    # 策略 2：從 monologue 中提取
                    elif extracted_from_monologue:
                        if missing_key in ("target", "parameter"):
                            params[missing_key] = ", ".join(extracted_from_monologue)
                        else:
                            params[missing_key] = extracted_from_monologue
                        ctx.write_event_to_stream(
                            ProgressEvent(
                                msg=f"─ [護欄補齊] 從分析策略中提取到參數: {', '.join(extracted_from_monologue[:5])}，已填入 '{missing_key}'"
                            )
                        )
                    # 策略 3：最後防線
                    else:
                        if missing_key == "parameters":
                            params[missing_key] = "all"
                            ctx.write_event_to_stream(
                                ProgressEvent(
                                    msg="─ [護欄補齊] 無法確定具體參數，改為全場分析..."
                                )
                            )

        # B. 初期強制全場掃描
        force_global_tools = [
            "hotelling_t2_analysis",
            "systemic_pca_analysis",
            "compare_data_segments",
        ]
        if ev.mode == "deep" and tool_name in force_global_tools:
            param_val = params.get("parameters")
            is_few_params = False
            if isinstance(param_val, list) and 0 < len(param_val) < 5:
                is_few_params = True
            elif (
                isinstance(param_val, str)
                and 0 < len(param_val.split(",")) < 5
                and param_val.lower() != "all"
            ):
                is_few_params = True

            # 僅在初期強制，後期若 AI 挑選則視為有目的的操作
            if is_few_params and ev.step_count <= 2:
                params["parameters"] = "all"
                ctx.write_event_to_stream(
                    ProgressEvent(
                        msg="─ [系統優化] 診斷初期強制執行全場掃描，以建立全局基準數據..."
                    )
                )
            elif is_few_params and ev.step_count > 2:
                ctx.write_event_to_stream(
                    ProgressEvent(
                        msg="─ [針對性分析] 偵測到特定參數選取，正在根據前序證據進行深度下鑽..."
                    )
                )

        # --- [C. 重複工具偵測護欄] 防止 AI 以完全相同參數重複調用同一工具 ---
        # 注意：「parameters」字段的變化 (如 'all' → 特定參數列表) 屬於有目的的下鑽分析，
        # 不應被視為重複。只比對除 file_id 和 parameters 以外的參數。
        if ev.prev_results:
            for prev in ev.prev_results:
                prev_tool = prev.get("tool", "")
                if prev_tool == tool_name:
                    # 排除 file_id 和 parameters/target (這些的變化代表有目的的深入分析)
                    drill_down_keys = {
                        "file_id",
                        "parameters",
                        "target",
                        "parameter",
                        "features",
                    }

                    # [Fix] Safely handle prev params which might be stringified
                    prev_raw_params = prev.get("params", {})
                    if isinstance(prev_raw_params, str):
                        try:
                            import json

                            prev_raw_params = json.loads(prev_raw_params)
                        except Exception:
                            prev_raw_params = {}

                    if not isinstance(prev_raw_params, dict):
                        prev_raw_params = {}

                    prev_params = {
                        k: v
                        for k, v in prev_raw_params.items()
                        if k not in drill_down_keys
                    }
                    curr_params = {
                        k: v for k, v in params.items() if k not in drill_down_keys
                    }

                    # 額外檢查：如果 parameters 字段明顯不同，絕對不是重複
                    prev_param_val = str(prev_raw_params.get("parameters", ""))
                    curr_param_val = str(params.get("parameters", ""))
                    params_changed = prev_param_val != curr_param_val

                    if params_changed:
                        logger.info(
                            f"[Duplicate Guard] Tool '{tool_name}' reused with different parameters "
                            f"('{prev_param_val[:50]}' → '{curr_param_val[:50]}'), allowing drill-down."
                        )
                        continue  # 允許通過，不算重複

                    # 將值統一為字串比較，避免型別差異造成誤判
                    if str(sorted(prev_params.items())) == str(
                        sorted(curr_params.items())
                    ):
                        logger.warning(
                            f"[Duplicate Guard] Tool '{tool_name}' already executed in Step {prev.get('step')} "
                            f"with identical params. Forcing finish."
                        )
                        ctx.write_event_to_stream(
                            ProgressEvent(
                                msg=f"─ [護欄] 偵測到工具 {tool_name} 已在 Step {prev.get('step')} 以完全相同參數執行過，強制進入結案階段。"
                            )
                        )
                        # 建立顯示名稱映射
                        full_display_mappings = {
                            p: mappings.get(p, p) for p in params_list
                        }
                        aggregated_data = {
                            "monologue_history": monologue,
                            "latest_analysis_results": ev.prev_results[-1].get("result")
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
                            suspect_pool=current_pool,
                        )

        try:
            # 根據工具名提供動態的進度提示
            tool_display_names = {
                "get_time_series_data": "正在讀取數據趨勢...",
                "detect_outliers": "正在偵測異常點...",
                "get_top_correlations": "正在分析因素相關性...",
                "analyze_distribution": "正在分析數據分佈...",
                "hotelling_t2_analysis": "正在執行 Hotelling's T2 系統性診斷...",
                "causal_relationship_analysis": "正在推導因果關聯鏈路...",
            }
            msg = tool_display_names.get(tool_name, f"正在執行 {tool_name}...")

            # --- 額外提示：如果參數是 'all' 或很多，提示正在處理大量數據 ---
            if params.get("parameters") == "all" or (
                isinstance(params.get("parameters"), list)
                and len(params.get("parameters")) > 30
            ):
                ctx.write_event_to_stream(
                    ProgressEvent(
                        msg="─ 偵測到大規模參數掃描，正在載入並對齊各感測器數據時間戳..."
                    )
                )

            ctx.write_event_to_stream(ProgressEvent(msg=f"🛠️ {msg}"))

            tool_result = await self.tool_executor.execute_tool(
                tool_name, params, ev.session_id
            )

            # 檢查結果是否包含錯誤，若 Hotelling 失敗但在深層分析模式，可以在此處注入提示
            if ev.mode == "deep" and tool_name == "hotelling_t2_analysis":
                # Check for error key or NaN T2_value
                if (isinstance(tool_result, dict) and "error" in tool_result) or (
                    isinstance(tool_result, dict)
                    and "T2_value" in tool_result
                    and str(tool_result["T2_value"]).lower() == "nan"
                ):
                    # If T2 fails, we add a "hint" to the result sent to the next step, guiding the AI to fallback
                    tool_result["fallback_hint"] = (
                        "Hotelling 分析失敗。原因可能是參數間共線性太高或樣本不足。請改用單變量分析 (analyze_distribution) 或重新挑選不相關的參數。"
                    )

            # 強制功能：將分析結果摘要即時推送到聊天室思考視窗
            if isinstance(tool_result, dict):
                if "top_3_summary" in tool_result:
                    ctx.write_event_to_stream(
                        ProgressEvent(msg=f"✅ {tool_result['top_3_summary']}")
                    )
                elif "interpretation" in tool_result:
                    ctx.write_event_to_stream(
                        ProgressEvent(msg=f"✅ {tool_result['interpretation']}")
                    )
                elif "conclusion" in tool_result:
                    # 避免太長的結論，只取前 100 字
                    conclusion = tool_result["conclusion"]
                    if len(conclusion) > 100:
                        conclusion = conclusion[:100] + "..."
                    ctx.write_event_to_stream(
                        ProgressEvent(msg=f"✅ 分析摘要: {conclusion}")
                    )
                elif "error" in tool_result:
                    ctx.write_event_to_stream(
                        ProgressEvent(msg=f"❌ 工具執行中斷: {tool_result['error']}")
                    )
                else:
                    ctx.write_event_to_stream(
                        ProgressEvent(msg=f"─ {tool_name} 分析完成，準備下一階段。")
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

            # [Why Conclusion Registration - Call Tool Path]
            if ev.mode == "deep":
                await self._register_why_conclusion(
                    ctx,
                    monologue,
                    current_why,
                    tool_name,
                    tool_result if isinstance(tool_result, dict) else {},
                    ev.step_count,
                )

            return AnalysisEvent(
                query=ev.query,
                file_id=ev.file_id,
                session_id=ev.session_id,
                history=ev.history,
                mode=ev.mode,
                step_count=ev.step_count + 1,
                prev_results=next_history,
                suspect_pool=current_pool,
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

        # [NEW] 注入上一次分析的結論，讓 humanizer 能回答追問
        if hasattr(self, "orchestrator") and ev.session_id:
            cached = self.orchestrator._last_states.get(ev.session_id)
            if cached:
                state = cached.get("state")
                if (
                    state
                    and hasattr(state, "current_knowledge")
                    and state.current_knowledge
                ):
                    context_data["previous_analysis"] = state.current_knowledge
                    logger.info(
                        f"[Chat Context] Injected {len(state.current_knowledge)} chars of previous analysis"
                    )

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
            suspect_pool=ev.suspect_pool,
        )

    # --- [Why Conclusion Registry] 結構化 5-Why 結論提取與註冊 ---

    def _extract_why_section(self, monologue: str, section_name: str) -> str:
        """
        從 monologue 中提取指定的 5-Why 結構化段落。
        例如提取 [Hypothesis]: ... 或 [Conclusion]: ... 的內容。
        """
        all_tags = ["Why", "Hypothesis", "Action", "Conclusion"]
        lookahead_parts = [rf"\[{re.escape(t)}" for t in all_tags if t != section_name]
        lookahead = "|".join(lookahead_parts) if lookahead_parts else "$"
        pattern = (
            rf"\[{re.escape(section_name)}(?:\s*#\d+)?\]\s*:?\s*(.*?)"
            rf"(?={lookahead}|$)"
        )
        match = re.search(pattern, monologue, re.DOTALL)
        if match:
            return match.group(1).strip()
        return ""

    async def _register_why_conclusion(
        self,
        ctx: Context,
        monologue: str,
        current_why: int,
        tool_name: str,
        tool_result: dict,
        step_num: int,
    ):
        """
        [Why 結論註冊器]
        當 monologue 中包含 [Conclusion] 時，提取結構化結論並鎖定存入 Context。
        確保最終 humanizer 可以直接引用，而非從原始數據重新推導。
        """
        if "[Conclusion]" not in monologue:
            return

        why_matches = re.findall(r"\[Why\s*#(\d+)\]", monologue)
        concluded_why = max(int(w) for w in why_matches) if why_matches else current_why

        # 防止重複註冊同一層級
        why_chain = await ctx.get("why_chain", default=[])
        existing_levels = {w.get("why_level") for w in why_chain}
        if concluded_why in existing_levels:
            return

        evidence_summary = ""
        key_metrics = {}
        if isinstance(tool_result, dict):
            evidence_summary = (
                tool_result.get("top_3_summary")
                or tool_result.get("interpretation")
                or tool_result.get("conclusion", "")
            )
            key_metrics = {
                k: v
                for k, v in tool_result.items()
                if k
                in [
                    "t2_value",
                    "T2_value",
                    "p_value",
                    "threshold",
                    "top_3_contributors",
                    "top_deviations",
                    "z_scores",
                    "anomaly_count",
                    "variance_explained",
                    "correlations",
                    "significant_shifts",
                ]
            }

        why_conclusion = {
            "why_level": concluded_why,
            "hypothesis": self._extract_why_section(monologue, "Hypothesis"),
            "action_reasoning": self._extract_why_section(monologue, "Action"),
            "conclusion": self._extract_why_section(monologue, "Conclusion"),
            "evidence_tool": tool_name or "N/A",
            "evidence_summary": evidence_summary,
            "key_metrics": key_metrics,
            "step_num": step_num,
        }

        why_chain.append(why_conclusion)
        await ctx.set("why_chain", why_chain)

        ctx.write_event_to_stream(
            ProgressEvent(
                msg=f"-- [Why #{concluded_why} 結案] 結論已鎖定並存檔，準備推進至下一層級..."
            )
        )

    async def _render_layered_report(
        self,
        ctx: Context,
        ev: SummarizeEvent,
        why_chain: list,
        has_mapping: bool,
        row_count: int,
        col_count: int,
    ) -> StopEvent:
        """
        [5-Why 分層渲染器]
        逐層獨立生成摘要，確保報告天然具有層次結構。
        每層使用獨立的小型 LLM 調用，避免大 Prompt 壓平層次。
        """
        full_text = ""
        suffix = f"\n\n```json\n{ev.chart_json}\n```\n" if ev.chart_json else ""

        # 讀取真實欄位清單 (防止 LLM 幻覺)
        actual_params_list = []
        try:
            summary = self.tool_executor.analysis_service.load_summary(
                ev.session_id, ev.file_id
            )
            if summary:
                actual_params_list = summary.get("parameters", [])
        except Exception:
            pass
        params_anchor_short = ""
        if not has_mapping and actual_params_list:
            preview = ", ".join(actual_params_list[:30])
            params_anchor_short = f"\n\u6a94\u6848\u5be6\u969b\u6b04\u4f4d (\u524d30\u500b): {preview}\n\u5831\u544a\u4e2d\u63d0\u53ca\u7684\u6b04\u4f4d\u540d\u7a31\u5fc5\u9808\u51fa\u81ea\u6b04\u6e05\u55ae\u3002\n"

        # --- 1. 報告標題 (硬編碼結構，不依賴 LLM) ---
        header = (
            f"## 5-Why 深度診斷報告\n\n"
            f"**分析目標**: {ev.query}\n"
            f"**數據規模**: {row_count} 筆資料, {col_count} 個參數\n"
            f"**診斷深度**: 共 {len(why_chain)} 層 Why 分析\n\n"
        )
        ctx.write_event_to_stream(TextChunkEvent(content=header))
        full_text += header

        # --- 2. 逐層渲染 ---
        for i, why in enumerate(why_chain):
            level = why.get("why_level", i + 1)
            section_header = f"### Why #{level}\n\n"
            ctx.write_event_to_stream(TextChunkEvent(content=section_header))
            full_text += section_header

            # 構建該層的 Mapping 上下文
            mapping_context = ""
            if has_mapping and ev.mappings:
                evidence_str = str(why.get("evidence_summary", "")) + str(
                    why.get("key_metrics", {})
                )
                relevant = {k: v for k, v in ev.mappings.items() if k in evidence_str}
                if relevant:
                    mapping_context = (
                        f"參數對照: {json.dumps(relevant, ensure_ascii=False)}\n"
                    )

            no_mapping_warn = ""
            if not has_mapping:
                no_mapping_warn = f"【嚴重警示】無參數對照表，嚴禁臆測參數的物理意義，僅使用診斷記錄中出現的真實欄位代碼。{params_anchor_short}\n"

            layer_prompt = (
                f"你是一位嚴謹的工業數據分析專家。請用繁體中文撰寫這一層 Why 分析的精簡摘要。\n"
                f"{no_mapping_warn}"
                f"## Why #{level} 的分析內容 ##\n"
                f"假設: {why.get('hypothesis', '未提供')}\n"
                f"使用工具: {why.get('evidence_tool', '未知')}\n"
                f"行動理由: {why.get('action_reasoning', '未提供')}\n"
                f"原始結論: {why.get('conclusion', '未提供')}\n"
                f"關鍵數據: {json.dumps(why.get('key_metrics', {}), ensure_ascii=False, default=str)}\n"
                f"證據摘要: {why.get('evidence_summary', '無')}\n"
                f"{mapping_context}\n"
                f"## 撰寫要求 ##\n"
                f"1. 用因果推理的敘事方式描述：先提出假設 → 說明如何驗證 → 數據結果 → 結論，形成一條清晰的推理鏈\n"
                f"2. 判定標準 (嚴格)：\n"
                f"   - |Z-Score| > 6 或與平均差異極大：才可稱為「異常」，需要報告\n"
                f"   - 3 < |Z-Score| <= 6：僅稱為「偏離」或「值得關注」，可在次要觀察中提及\n"
                f"   - |Z-Score| <= 3：視為「正常波動」，不需報告\n"
                f"3. 必須引用具體數值，但只突出真正極端的參數\n"
                f"4. 如果這不是最後一層，必須明確說明『因為上一層發現了 XX，所以我懷疑 YY，接下來要驗證 ZZ』\n"
                f"5. 使用繁體中文，禁止分隔線 (===, ---, ***)\n"
                f"6. 直接輸出內容，不要加標題或前綴\n"
            )

            async for chunk in self.llm.astream_complete(layer_prompt):
                if chunk.delta:
                    cleaned = re.sub(r"[=\-*~]{3,}", "", chunk.delta)
                    full_text += cleaned
                    ctx.write_event_to_stream(TextChunkEvent(content=cleaned))

            spacing = "\n\n"
            ctx.write_event_to_stream(TextChunkEvent(content=spacing))
            full_text += spacing

        # --- 3. 最終結論與建議 ---
        final_header = "### 最終結論與建議\n\n"
        ctx.write_event_to_stream(TextChunkEvent(content=final_header))
        full_text += final_header

        chain_summary = "\n".join(
            [
                f"- Why #{w.get('why_level', '?')}: {w.get('conclusion', '未提供')}"
                for w in why_chain
            ]
        )
        suspect_list = ", ".join(ev.suspect_pool) if ev.suspect_pool else "無"

        final_prompt = (
            f"你是一位嚴謹的工業數據分析專家。\n"
            f"以下是 5-Why 診斷鏈的所有層級結論：\n{chain_summary}\n"
            f"鎖定的嫌疑參數: {suspect_list}\n\n"
            f"## 任務 ##\n"
            f"1. 用因果推理鏈的方式總結根因：『因為 A → 所以 B → 導致 C』。每一層 Why 的結論必須邏輯銜接。\n"
            f"2. 只報告 |Z-Score| > 6 或與平均差異極大的參數。若全場 |Z-Score| < 6，應明確告知『本次分析未發現極端異常』。\n"
            f"3. 行動建議僅限 1-2 條：若 Z<6 僅能建議「持續監控」；若 Z>6 才能建議具體設備檢查。\n"
            f"4. 使用繁體中文，禁止分隔線\n"
            f"5. 直接輸出內容，不要重複以上的診斷鏈\n"
        )
        if not has_mapping:
            final_prompt += (
                f"5. 嚴禁臆測參數物理意義，僅使用真實欄位代碼。{params_anchor_short}\n"
            )

        async for chunk in self.llm.astream_complete(final_prompt):
            if chunk.delta:
                cleaned = re.sub(r"[=\-*~]{3,}", "", chunk.delta)
                full_text += cleaned
                ctx.write_event_to_stream(TextChunkEvent(content=cleaned))

        if suffix:
            ctx.write_event_to_stream(TextChunkEvent(content=suffix))
            full_text += suffix

        return StopEvent(result={"response": full_text, "data": ev.data})

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
            _is_scatter = any(kw in query_lower for kw in ["散佈", "scatter", "相關性"])

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
                # 偵測 X 軸欄位 (時間軸 / 索引軸)
                axis_candidates = ["TIME", "Timestamp", "Date", "INDEX_AXIS"]
                label_col = next((c for c in axis_candidates if c in actual_data), None)
                labels = (
                    actual_data[label_col]
                    if label_col
                    else list(range(len(next(iter(actual_data.values())))))
                )
                datasets = []
                for col, vals in actual_data.items():
                    # 跳過 X 軸欄位，不將其畫為數據線
                    if col == label_col or col in axis_candidates:
                        continue
                    datasets.append({"label": ev.mappings.get(col, col), "data": vals})
                chart_obj = {
                    "type": "chart",
                    "chart_type": "line",
                    "labels": labels,
                    "datasets": datasets,
                }

            return json.dumps(chart_obj, ensure_ascii=False)
        except Exception:
            return None

    @step
    async def visualize_data(
        self, ctx: Context, ev: VisualizingEvent
    ) -> SummarizeEvent:
        ctx.write_event_to_stream(
            ProgressEvent(msg="(Visualizing...) 正在繪製分析圖表...")
        )
        chart_json = self._build_programmatic_chart(ev)

        # [TOKEN OPTIMIZATION] 數據清洗
        # 為了防止 LLM 看到大量原始數據而崩潰或復讀，這裡將 raw data 移除，只傳遞 metadata 給 humanizer
        sanitized_data = ev.data
        if isinstance(ev.data, dict) and "data" in ev.data:
            sanitized_data = ev.data.copy()
            sanitized_data["data"] = (
                "Raw time-series data omitted for token optimization. Please refer to the generated chart."
            )

        return SummarizeEvent(
            data=sanitized_data,
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

        # [DIRECT REPLY CHECK]
        # 如果事件包含 direct_reply，直接輸出該內容，跳過 LLM
        # 這用於系統級的快速反問或錯誤提示
        if isinstance(ev.data, dict) and ev.data.get("direct_reply"):
            return StopEvent(
                result={"response": ev.data["direct_reply"], "data": ev.data}
            )

        # 1. 檢查是否有 Mapping
        has_mapping = bool(ev.mappings and len(ev.mappings) > 0)

        # 最終防線：抓取物理全量統計與欄位清單作為背景
        row_count = ev.row_count
        col_count = ev.col_count
        actual_params_list = []
        try:
            summary = self.tool_executor.analysis_service.load_summary(
                ev.session_id, ev.file_id
            )
            if summary:
                if row_count <= 0:
                    row_count = summary.get("total_rows", 0)
                if col_count <= 0:
                    col_count = summary.get("total_columns", 0)
                actual_params_list = summary.get("parameters", [])
        except Exception:
            pass

        # --- [5-Why 分層渲染快車道] ---
        # 如果 Context 中有結構化的 why_chain，直接走分層渲染，跳過一次性重寫
        if ev.mode in ("deep", "full"):
            try:
                why_chain = await ctx.get("why_chain", default=[])
            except (AttributeError, Exception):
                why_chain = []
            if isinstance(why_chain, list) and len(why_chain) > 0:
                logger.info(
                    f"[Humanizer] 偵測到 {len(why_chain)} 層結構化 Why 結論，啟用分層渲染模式"
                )
                return await self._render_layered_report(
                    ctx, ev, why_chain, has_mapping, row_count, col_count
                )

        # --- [降級路徑] 構建 5-Why 診斷鏈摘要 (從 ev.data 中提取) ---
        diagnostic_chain = ""
        tool_history = []
        # [FIX] Extract V2 final_decision dashboard context
        v2_dashboard = ""
        if isinstance(ev.data, dict):
            tool_history = ev.data.get("full_tool_history", []) or ev.data.get(
                "all_steps_results", []
            )
            v2_dashboard = ev.data.get("final_decision", "")

        if tool_history:
            chain_parts = []
            # [FIX] Prepend V2 dashboard context if available
            if v2_dashboard:
                chain_parts.append(f"### 分析儀表板總覽\n{v2_dashboard}\n")
            for step_data in tool_history:
                step_num = step_data.get("step", "?")
                tool_used = step_data.get("tool", "unknown")
                mono = step_data.get("monologue", "")
                result = step_data.get("result", {})

                # 提取結果文本 (核心字段禁止截斷)
                result_text = ""
                if isinstance(result, dict):
                    key_fields = {}
                    for rk, rv in result.items():
                        # 核心診斷欄位如 contribution/top_3 等，絕對禁止截斷
                        if rk in [
                            "top_3_contributors",
                            "top_3_summary",
                            "top_deviations",
                            "correlations",
                            "p_value",
                            "t2_value",
                        ]:
                            key_fields[rk] = rv
                        else:
                            rv_str = str(rv)
                            key_fields[rk] = (
                                rv_str[:800] + "..." if len(rv_str) > 800 else rv_str
                            )

                    result_text = json.dumps(
                        key_fields, ensure_ascii=False, default=str
                    )
                else:
                    result_text = str(result)[:1000]

                chain_parts.append(
                    f"### Step {step_num} (工具: {tool_used})\n"
                    f"**AI 思考**: {mono}\n"
                    f"**完整數據結果**: {result_text}\n"
                )
                # [FIX] Also append V2 key_findings if present
                kf = step_data.get("key_findings", [])
                if kf:
                    findings_text = "\n".join(f"  - {f}" for f in kf)
                    chain_parts.append(f"**關鍵發現**:\n{findings_text}\n")
                rh = step_data.get("rejected_hypotheses", [])
                if rh:
                    rejected_text = "\n".join(f"  - {r}" for r in rh)
                    chain_parts.append(f"**排除假說**:\n{rejected_text}\n")
                ns = step_data.get("next_step_suggestion", "")
                if ns:
                    chain_parts.append(f"**下步建議**: {ns}\n")
                # Append structured causal data if available
                cc = step_data.get("causal_chain", [])
                if cc:
                    cc_text = []
                    for link in cc:
                        if isinstance(link, dict):
                            cc_text.append(
                                f"  - {link.get('from', '?')} → {link.get('to', '?')} "
                                f"[證據: {link.get('evidence', '無')}] "
                                f"(信心: {link.get('confidence', '?')})"
                            )
                    if cc_text:
                        chain_parts.append(
                            f"**因果鏈 (Causal Chain)**:\n" + "\n".join(cc_text) + "\n"
                        )
                iso = step_data.get("isolated_observations", [])
                if iso:
                    iso_text = "\n".join(f"  - {o}" for o in iso if o)
                    if iso_text:
                        chain_parts.append(f"**獨立觀察 (Independent)**:\n{iso_text}\n")
            diagnostic_chain = "\n".join(chain_parts)
        elif isinstance(ev.data, dict) and ev.data.get("previous_analysis"):
            # [Chat Path] 用戶在聊天中追問上次分析結果
            prev = ev.data["previous_analysis"]
            diagnostic_chain = (
                "### 上次分析的結論摘要 (Previous Analysis Context)\n"
                f"{prev}\n\n"
                "注意：以上是上次分析的完整結論。用戶正在追問相關內容，請基於這些結論回答，"
                "不要重新分析或生成新的數據。"
            )
        else:
            # 如果沒有工具歷史，直接使用 data_json
            diagnostic_chain = json.dumps(ev.data, ensure_ascii=False)[:5000]

        # 嫌疑參數池
        suspect_info = ""
        if ev.suspect_pool:
            suspect_display = []
            for s in ev.suspect_pool:
                if has_mapping and s in ev.mappings:
                    display_name = ev.mappings[s]
                    suspect_display.append(f"- **{s}** ({display_name})")
                else:
                    # 無對照時，嚴禁給予括號空間，避免 AI 填空
                    suspect_display.append(f"- **{s}**")
            suspect_info = "\n## 最終鎖定的參數代碼 (Suspect Pool) ##\n" + "\n".join(
                suspect_display
            )

        # [VISUALIZATION FAST-TRACK CHECK]
        # 如果是純繪圖請求 (tool_history 僅含 get_time_series_data 或為空) 且有圖表
        # 強制切換為極簡模式，只輸出一句話，不寫分析報告
        is_pure_viz = False
        if ev.chart_json and (
            not tool_history
            or all(t.get("tool") == "get_time_series_data" for t in tool_history)
        ):
            is_pure_viz = True

        # [CHAT PATH DETECTION]
        # 如果沒有工具歷史且不是分析結果，說明這是聊天/追問路徑
        is_chat_path = not tool_history and not v2_dashboard

        if is_pure_viz:
            prompt = (
                "你是一個數據視覺化助理。\n"
                f"用戶提問: {ev.query}\n"
                "任務: 用戶要求繪製圖表。圖表數據已準備好。\n"
                "請僅用一句簡短的話回應（例如：「這是您要求的 XX 參數趨勢圖。」）。\n"
                "嚴格禁止：\n"
                "1. 禁止撰寫分析報告、摘要或建議。\n"
                "2. 禁止解釋數據含義。\n"
                "3. 禁止廢話。\n"
                "4. 直接輸出那一句話即可。\n"
                "請使用繁體中文。"
            )
        elif is_chat_path:
            # [聊天路徑專用 Prompt] 不使用分析報告格式，而是對話式回答
            chat_context_parts = []

            # 注入對話歷史 (最關鍵的修復：之前完全沒有注入 history)
            if ev.history:
                # 限制歷史長度，避免 Token 爆炸
                history_text = (
                    ev.history[:6000] if len(ev.history) > 6000 else ev.history
                )
                chat_context_parts.append(
                    f"## 對話歷史 (Conversation History) ##\n{history_text}"
                )

            # 注入上次分析結論
            if isinstance(ev.data, dict) and ev.data.get("previous_analysis"):
                prev = ev.data["previous_analysis"]
                prev_text = prev[:4000] if len(prev) > 4000 else prev
                chat_context_parts.append(
                    f"## 上次分析結論 (Previous Analysis) ##\n{prev_text}"
                )

            # 注入可用參數清單
            if actual_params_list:
                params_display = ", ".join(actual_params_list[:30])
                chat_context_parts.append(
                    f"## 可用參數 ##\n{params_display} (共 {len(actual_params_list)} 個)"
                )

            chat_context = (
                "\n\n".join(chat_context_parts)
                if chat_context_parts
                else "（無可用背景資訊）"
            )

            prompt = (
                "你是一位工業數據分析系統的對話助理。\n"
                "## 核心規則 ##\n"
                "1. 你只能基於【對話歷史】和【上次分析結論】中的真實內容來回答。\n"
                "2. **嚴禁編造**任何數據、Z-Score、異常報告或分析結果。\n"
                "3. 如果對話歷史或分析結論中沒有相關資訊，請明確告知用戶：\n"
                "   「目前沒有相關的分析記錄，建議您先執行分析後再查詢。」\n"
                "4. 若用戶要求整合或總結多次對話，只能總結對話歷史中實際出現的內容。\n"
                "5. **嚴禁**自行生成工業數據診斷報告或異常分析報告。\n"
                "6. 使用繁體中文回答。\n\n"
                f"{chat_context}\n\n"
                f"用戶提問: {ev.query}\n"
                f"數據概況: 包含 {row_count} 行與 {col_count} 個欄位。\n\n"
                "請基於以上背景資訊回答用戶的問題。"
            )
        else:
            # 根據模式調整摘要指令 (正常分析模式)
            # [NEW] Detect analysis type from diagnostic chain (shared by all modes)
            is_optimization = (
                "優化推薦" in diagnostic_chain or "多目標優化" in diagnostic_chain
            )
            is_segment = "區段比較" in diagnostic_chain

            if ev.mode in ("deep", "full"):
                if is_optimization:
                    structure_instruction = (
                        "## 報告結構要求 (優化分析報告) ##\n"
                        "你必須嚴格按照以下結構撰寫最終報告：\n\n"
                        "1. **分析概要**: 一段話總結目標參數、使用方法和核心結論。\n\n"
                        "2. **關鍵驅動因子排名**: 按影響力列出所有影響目標的參數：\n"
                        "   | 排名 | 參數名稱 | 影響力 | 相關係數 | 調整方向 |\n"
                        "   - 影響力 = feature importance 或 correlation 的絕對值\n"
                        "   - 調整方向 = 提高/降低該參數可改善目標\n"
                        "   所有數值必須從診斷記錄中直接引用,嚴禁編造。\n\n"
                        "3. **最佳操作範圍**: 如果有 performance_segmentation 或 compare_data_segments 結果,\n"
                        "   列出好壞批次的參數差異和建議範圍：\n"
                        "   | 參數 | 好批次範圍 | 壞批次範圍 | 建議操作範圍 |\n\n"
                        "4. **因果結構**: 如有 cross_correlation_lag 或 causal_relationship_analysis 結果,\n"
                        "   說明各驅動因子之間的因果方向 (誰影響誰)。\n"
                        "   - 僅在有直接因果證據時才寫因果關係。\n"
                        "   - 無因果證據時標註為『統計關聯』。\n\n"
                        "5. **行動建議**: 按優先順序列出 1-3 條具體參數調整建議。\n"
                        "   每條建議必須包含: 參數名稱 + 調整方向 + 預期效果。\n"
                    )
                elif is_segment:
                    structure_instruction = (
                        "## 報告結構要求 (區段比較報告) ##\n"
                        "你必須嚴格按照以下結構撰寫最終報告：\n\n"
                        "1. **分析概要**: 比較了哪些區段、使用了什麼方法。\n\n"
                        "2. **區段差異排名**: 按差異程度列出參數：\n"
                        "   | 排名 | 參數名稱 | 區段A均值 | 區段B均值 | 差異 | 顯著性 |\n\n"
                        "3. **差異原因**: 如有因果證據,說明差異的可能原因。\n\n"
                        "4. **行動建議**: 1-3 條具體建議。\n"
                    )
                else:
                    # 預設: 異常檢測模式
                    structure_instruction = (
                        "## 報告結構要求 (深度分析報告) ##\n"
                        "你必須嚴格按照以下結構撰寫最終報告：\n\n"
                        "1. **分析概要**: 一段話總結本次分析的範圍、使用方法和核心發現。\n\n"
                        "2. **異常發現排名**: 按嚴重程度列出所有 |Z-Score| > 3 的異常：\n"
                        "   | 排名 | 參數名稱 | Z-Score | 異常類型 | 嚴重程度 |\n"
                        "   所有數值必須從診斷記錄中直接引用,嚴禁編造。\n\n"
                        "3. **因果推理鏈 (Causal Chain)** [嚴格規則]:\n"
                        "   - **只有**當診斷記錄中存在明確的『因果鏈 (Causal Chain)』標注時,才寫 Why 鏈。\n"
                        "   - Why 鏈格式: Why #N 必須以前一個 Why 的結論作為起點。\n"
                        "     - Why #1: 描述初始異常現象 (Discovery) → 第一層原因 (Cause)\n"
                        "     - Why #2: 以 Why #1 的原因作為新起點 → 推導下一層原因\n"
                        "   - **每個 Why 之間必須有因果銜接**: '因為 A (上一層結論),所以我們調查 B,發現...'\n"
                        "   - **如果沒有因果證據** (如 cross-correlation lag 或 Hotelling T2 貢獻度),\n"
                        "     則不要寫 Why 鏈,改用下方的『獨立異常觀察』呈現。\n"
                        "   - **絕對禁止**把獨立的發現強行編號為 Why #1, #2, #3。\n\n"
                        "4. **獨立異常觀察**: 與因果鏈無關的其他異常發現。\n"
                        "   - 每一項獨立列出,用加粗標題 + 簡述格式。\n"
                        "   - 例如: **BCDRY-ABB_B19 系統凍結**: Row 33-129 標準差極低 (≈0.0001),研判為傳感器未更新。\n\n"
                        "5. **行動建議**: 按優先順序列出 1-3 條具體建議。\n"
                    )
            else:
                if is_optimization:
                    structure_instruction = (
                        "## 報告結構要求 (快速優化摘要) ##\n"
                        "簡明地提供：\n"
                        "1. **關鍵驅動因子**: 列出 Top 3 影響目標的參數 (含影響力和調整方向)。\n"
                        "2. **建議操作**: 1-2 條具體的參數調整建議。\n"
                    )
                else:
                    structure_instruction = (
                        "## 報告結構要求 (快速摘要) ##\n"
                        "簡明地提供：\n"
                        "1. **核心發現**: 報告所有重要發現,包括但不限於:\n"
                        "   - |Z-Score| > 3 的顯著異常 (含參數名和實際 Z-Score 數值)\n"
                        "   - 殘差分析異常 (如特定 Row 的異常殘差)\n"
                        "   - 特徵重要性排名 (Top 3 驅動因子)\n"
                        "   - 好壞批次分割結果 (閾值、關鍵差異參數)\n"
                        "   - CV 波動性排名中最不穩定的參數\n"
                        "   若無任何異常,告知『未發現顯著異常』。\n"
                        "   **重要**: 診斷記錄中每一個 Turn 的「關鍵發現」都必須在報告中呈現,禁止遺漏。\n"
                        "2. **關聯性**: 若有因果證據 (cross_correlation_lag, causal_chain),簡述因果方向。\n"
                        "3. **行動建議**: 1-3 條,按嚴重程度排序。若無異常僅建議持續監控。\n"
                    )

            data_limit = 25000 if ev.mode in ("deep", "full") else 8000

            # 強化禁令
            if has_mapping:
                mapping_status = f"參數顯示名稱對應 (Mapping): {json.dumps(ev.mappings, ensure_ascii=False)}"
                mapping_rule = "3. **翻譯物理意義**: 參數代碼旁必須附上物理名稱 (使用提供的 Mapping)。\n"
            else:
                mapping_status = "參數顯示名稱對應 (Mapping): (完全無對照表，請注意)"
                mapping_rule = (
                    "3. **【嚴重警示：禁止臆測】**: 目前完全沒有參數對照表。你必須僅使用「診斷記錄中出現的真實欄位代碼」，"
                    "「絕對禁止」自行編造任何欄位名稱、添加括號說明、或嘗試解釋其物理意義（如冷卻水、壓力等）。"
                    "欄位名稱必須與下方「檔案實際欄位清單」中的名稱完全一致。"
                    "任何形式的推測或捏造欄位名稱都屬於數據安全違規，會導致診斷錯誤。\n"
                )

            # 構建真實欄位名稱清單 (防止 LLM 編造不存在的欄位)
            if actual_params_list:
                # 最多顯示 50 個欄位，避免 Token 爆炸
                params_display = ", ".join(actual_params_list[:50])
                if len(actual_params_list) > 50:
                    params_display += f" ... (共 {len(actual_params_list)} 個)"
                params_anchor = f"\n## 檔案實際欄位清單 (Ground Truth) ##\n{params_display}\n報告中提及的所有欄位名稱【必須】出自此清單，禁止編造。\n"
            else:
                params_anchor = ""

            prompt = (
                "你是一位極度嚴謹的工業數據專家。\n"
                "## 核心安全準則 - 違反將導致系統崩潰 ##\n"
                f"{mapping_rule}\n"
                "**客觀判斷原則**：根據數據說話，不預設異常。正常就說是正常。\n"
                "4. **【數據真實性絕對命令 (Anti-Hallucination)】**: \n"
                "   - 報告中引用的每一個數值 (如 Z-Score, 相關係數) **必須** 直接來自上方提供的【完整診斷過程記錄】。\n"
                "   - **嚴禁編造**記錄中不存在的數據。如果記錄顯示 Z-Score 為 3.53，你**絕對禁止**將其寫成 6.19 或其他數值。\n"
                "   - 若發現數據與你的預期不符，請如實報告數據，不要修改數據。\n"
                "**【統計判定標準 (修正版)】**：\n"
                "- **顯著異常 (Anomaly)**: 當 |Z-Score| > 3 時，即可判定為『異常』並在報告中重點報告。\n"
                "- **極端異常 (Critical)**: 當 |Z-Score| > 6 時，稱為『極端異常』，需強烈建議檢查。\n"
                "- **正常 (Normal)**: 若 |Z-Score| <= 3，視為「正常範圍」，可視情況略過。\n\n"
                f"用戶提問: {ev.query}\n"
                f"數據概況: 包含 {row_count} 行與 {col_count} 個欄位。\n"
                f"{mapping_status}\n"
                f"{params_anchor}"
                f"\n"
                f"## 完整診斷過程記錄 (包含所有原始數據) ##\n"
                f"{diagnostic_chain[:data_limit]}\n"
                f"{suspect_info}\n"
                f"\n"
                f"{structure_instruction}\n"
                "## 生成準則 ##\n"
                "1. **禁止佔位符**: 絕對禁止出現 [需要插入] 等模板文字。數值必須從記錄中直接引用。\n"
                "2. **因果推理鏈**: 報告的核心價值是呈現『A 導致 B，B 引發 C』的推理過程。每一層 Why 之間必須有明確的因果銜接，禁止平鋪式列點。\n"
                "3. **精簡報告**: 重點報告 |Z-Score| > 3 的參數。若無，則報告觀察到的最大偏差值與參數。\n"
                "4. **邏輯連貫**: Why #1 的結論必須自然引出 Why #2 的假設，形成一條無斷裂的推理鏈。\n"
                "5. **STRICT CHINESE (強制繁體中文)**: 你必須使用台灣繁體中文撰寫報告。絕對禁止使用英文或簡體中文。\n"
                "6. **判定嚴謹**: 若全場 |Z-Score| 均 < 3，應直接告知『本次分析未發現顯著異常，各參數均在正常波動範圍內』。\n"
                "7. **禁止重複**: 每層 Why 必須有新的發現。\n"
                "8. **禁止臆測**: 再次強調，若無 Mapping，報告中嚴禁出現任何代碼以外的描述性術語。\n"
                "9. **行動建議分級**: \n"
                "   - 若 |Z-Score| < 3：建議「持續監控」。\n"
                "   - 若 |Z-Score| > 3：建議「檢查相關參數變異」。\n"
                "   - 若 |Z-Score| > 6：強烈建議「立即停機檢查」或「校準設備」。\n"
                "10. **輸出純文字**: 最終報告必須是乾淨的 Markdown 格式。絕對禁止輸出原始的 JSON 物件或字典代碼。\n"
                "11. **禁止分隔線**: 絕對禁止使用 ===、---、*** 等連續符號作為分隔線。段落之間只用空行或 Markdown 標題分隔。"
            )

        full_text = ""
        suffix = f"\n\n```json\n{ev.chart_json}\n```\n" if ev.chart_json else ""

        # --- 真串流開始 ---
        async for chunk in self.llm.astream_complete(prompt):
            if chunk.delta:
                # 清理 LLM 輸出中的各種垃圾字元
                cleaned = chunk.delta
                # 1. 移除分隔線符號 (===, ---, *** 等連續 3 個以上)
                cleaned = re.sub(r"[=\-*~]{3,}", "", cleaned)
                # 2. 移除 JSON 殘留字元 (LLM 從 JSON 模式切換時的殘留)
                if not full_text.strip():
                    # 報告開頭：移除常見的 JSON 殘留前綴
                    cleaned = re.sub(r'^[\s@",{}\[\]\\:;`]+', "", cleaned)

                if cleaned.strip() or not chunk.delta.strip():  # 保留空行但去除純垃圾行
                    full_text += cleaned
                    ctx.write_event_to_stream(TextChunkEvent(content=cleaned))

        # 最終整體清理：移除報告開頭可能殘留的 JSON 碎片
        full_text = re.sub(r'^[\s@",{}\[\]\\:;`]*\n*', "", full_text)

        # [Safety Fix] 移除報告結尾的 JSON 幻覺 (LLM 錯誤續寫了外層 JSON 結構)
        # 當 Context 含有大量 JSON 時，LLM 容易產生幻覺，以為自己還在寫 JSON，導致輸出類似 ", "data": {...} 的內容
        # 這裡強制切斷這種錯誤的續寫
        full_text = re.sub(
            r'",\s*"(?:data|monologue_history|latest_analysis_results|full_tool_history)":\s*[\{\[].*$',
            "",
            full_text,
            flags=re.DOTALL,
        )

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

        # --- Extract structured report from Humanizer's Markdown ---
        structured_report = None
        try:
            from backend.services.analysis.report_builder import ReportBuilder

            rb = ReportBuilder()
            structured_report = rb.extract_from_markdown(
                final_result.get("response", "")
            )
        except Exception as e:
            logger.warning(f"[ReportBuilder] Extraction failed: {e}")

        # Build final SSE payload
        tool_result_data = final_result.get("data") or {}
        if isinstance(tool_result_data, dict):
            tool_result_data["structured_report"] = structured_report
        else:
            tool_result_data = {"structured_report": structured_report}

        yield json.dumps(
            {
                "type": "response",
                "content": final_result.get("response"),
                "tool_result": tool_result_data,
            },
            ensure_ascii=False,
        )

    async def clear_session(self, session_id: str = "default"):
        """Clear the session memory."""
        # Simple stub to preventing syntax error
        pass
