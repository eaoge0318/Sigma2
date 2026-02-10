import json
import logging
import requests
import httpx
from typing import Any, Dict, Optional
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
from .tools.executor import ToolExecutor

logger = logging.getLogger(__name__)


class CustomOllamaLLM(CustomLLM):
    """
    自定義 Ollama LLM 封裝
    使用 requests 直接發送請求，支援完整 URL (如 http://ip:port/api/chat)
    解決 LlamaIndex 原生 Ollama 套件對 URL 格式與連線的限制
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
    async def acomplete(self, prompt: str, **kwargs: Any) -> CompletionResponse:
        """非串流完整回傳 (用於意圖與工具選擇，速度較快)"""
        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(self.api_url, json=payload)
                response.raise_for_status()
                result = response.json()
                content = result.get("message", {}).get("content", "")
                return CompletionResponse(text=content)
        except Exception as e:
            logger.error(f"Ollama Async 連線錯誤: {str(e)}")
            raise ConnectionError(
                f"無法非同步連線至 Ollama: {str(e)} (URL: {self.api_url})"
            )

    async def astream_complete(
        self, prompt: str, **kwargs: Any
    ) -> CompletionResponseGen:
        """核心串流回傳 (用於最後的摘要報告)"""
        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
        }
        try:
            full_content = ""
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
                            full_content += content
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
        try:
            response = requests.post(self.api_url, json=payload, timeout=self.timeout)
            response.raise_for_status()
            result = response.json()
            content = result.get("message", {}).get("content", "")
            return CompletionResponse(text=content)
        except Exception as e:
            logger.error(f"Ollama 連線錯誤: {str(e)}")
            raise ConnectionError(f"無法連線至 Ollama: {str(e)} (URL: {self.api_url})")

    @llm_completion_callback()
    def stream_complete(self, prompt: str, **kwargs: Any) -> CompletionResponseGen:
        # 暫不支援串流，直接返回一次性結果
        response = self.complete(prompt, **kwargs)
        yield response


# ========== 事件定義 (Events) ==========


class IntentEvent(Event):
    """意圖識別後的事件"""

    query: str
    intent: str  # "analysis", "translation", "chat"
    file_id: str
    session_id: str
    history: str


class AnalysisEvent(Event):
    """執行地端分析的事件"""

    query: str
    file_id: str
    session_id: str
    history: str


class TranslationEvent(Event):
    """執行簡單翻譯或聊天的事件"""

    query: str
    session_id: str
    history: str


class VisualizingEvent(Event):
    """數據可視化/繪圖站的事件"""

    data: Any
    query: str
    session_id: str
    history: str
    row_count: int = 0
    col_count: int = 0
    mappings: Dict[str, str] = {}


class SummarizeEvent(Event):
    """執行結果總結的事件 (包含可選的圖表 JSON)"""

    data: Any
    query: str
    session_id: str
    history: str
    chart_json: Optional[str] = None
    row_count: int = 0
    col_count: int = 0


class ToolCallEvent(Event):
    """工具調用開始事件"""

    tool: str
    params: Dict


class TextChunkEvent(Event):
    """流式文本碎片的事件"""

    content: str


class ToolResultEvent(Event):
    """工具調用結果完成事件"""

    tool: str
    result: Any


class ProgressEvent(Event):
    """通用進度更新事件"""

    msg: str


class ConceptExpansionEvent(Event):
    """當搜索失敗時，請求 LLM 擴展概念的事件"""

    query: str
    original_concept: str
    file_id: str
    session_id: str
    history: str


class ErrorEvent(Event):
    """錯誤事件"""

    error: str
    session_id: str


# ========== Workflow 實作 ==========


class SigmaAnalysisWorkflow(Workflow):
    """
    Sigma2 智能分析工作流
    將 LLM 作為調度員與總結員，而將複雜運算交給地端 Python 執行。
    """

    def __init__(
        self,
        tool_executor: ToolExecutor,
        model_name: str = "llama3:latest",
        ollama_api_url: str = "http://localhost:11434/api/chat",
        timeout: int = 180,
    ):
        super().__init__(timeout=timeout, verbose=True)
        self.tool_executor = tool_executor
        self.llm = CustomOllamaLLM(
            model_name=model_name,
            api_url=ollama_api_url,
            timeout=180.0,
        )

    @step
    async def route_intent(
        self, ctx: Context, ev: StartEvent
    ) -> IntentEvent | ErrorEvent:
        """
        [LLM Step] 意圖識別工作站
        """
        ctx.write_event_to_stream(
            ProgressEvent(msg="(Thinking...) 正在理解您的問題並準備分析重點...")
        )
        query = getattr(ev, "query", None)
        file_id = getattr(ev, "file_id", None)
        session_id = getattr(ev, "session_id", None)
        history = getattr(ev, "history", "")

        if not query:
            return ErrorEvent(error="未提供問題", session_id=session_id)

        prompt = (
            "你是一個意圖識別專員。請根據對話歷史與當前問題判斷類型。\n"
            f"對話歷史:\n{history}\n"
            f"用戶問題: {query}\n"
            "類型必須是以下之一:\n"
            "- 'analysis': 用戶想分析數據、查欄位、繪圖或任何涉及 CSV 資料的操作。\n"
            "- 'translation': 用戶想翻譯內容或進行簡單對話。\n"
            "- 'chat': 其他的一般聊天。\n"
            "請僅回傳類型名稱。請用繁體中文思考，但只輸出類型單字。"
        )

        response = await self.llm.acomplete(prompt)
        intent = str(response.text).strip().lower()

        logger.info(f"🎯 [Intent Station] Intent: {intent}")

        return IntentEvent(
            query=query,
            intent=intent,
            file_id=file_id,
            session_id=session_id,
            history=history,
        )

    @step
    async def dispatch_work(
        self, ctx: Context, ev: IntentEvent
    ) -> AnalysisEvent | TranslationEvent:
        # Normalize and log intent for debugging
        intent = (ev.intent or "").strip().lower()
        logger.info(f"🔄 [Dispatch Station] Routing intent: {repr(intent)}")

        if "analysis" in intent or "chart" in intent or "data" in intent:
            return AnalysisEvent(
                query=ev.query,
                file_id=ev.file_id,
                session_id=ev.session_id,
                history=ev.history,
            )
        else:
            return TranslationEvent(
                query=ev.query, session_id=ev.session_id, history=ev.history
            )

    @step
    async def execute_analysis(
        self, ctx: Context, ev: AnalysisEvent
    ) -> VisualizingEvent | ConceptExpansionEvent:
        """
        [Local Step] 數據分析工作站
        """
        ctx.write_event_to_stream(
            ProgressEvent(
                msg="(Executing...) 正在掃描地端資料庫，尋找最相關的欄位與參數..."
            )
        )
        # 獲取工具清單

        tool_specs = ""
        for name, tool in self.tool_executor.tools.items():
            tool_specs += (
                f"- {name}: {tool.description} (需要參數: {tool.required_params})\n"
            )

        # 獲取文件摘要以提供可用欄位資訊給 LLM
        logger.info(f"🔍 [Analysis Station] Loading summary for file: {ev.file_id}")
        summary = self.tool_executor.analysis_service.load_summary(
            ev.session_id, ev.file_id
        )
        available_params = ""
        if summary:
            params_list = summary.get("parameters", [])
            mappings = summary.get("mappings", {})
            # 如果欄位太多，只取一部分或關鍵資訊 (減少 LLM 負擔，從 100 降為 40)
            sampled_params = params_list[:40]
            param_desc = []
            for p in sampled_params:
                m = mappings.get(p, "")
                param_desc.append(f"{p} ({m})" if m else p)
            available_params = ", ".join(param_desc)
            if len(params_list) > 40:
                available_params += "... (等更多欄位)"

        prompt = (
            "你是一個工具調用專家。請根據歷史與問題選擇合適的工具並提取參數。\n"
            f"對話歷史:\n{ev.history}\n"
            f"可用數據欄位 (格式: 代碼 (中文名稱)): {available_params}\n"
            f"工具清單:\n{tool_specs}\n"
            f"用戶問題: {ev.query}\n"
            f"文件 ID: {ev.file_id}\n"
            "**重要規則**:\n"
            "1. 如果用戶問「有哪些欄位」或「列出參數」，**必須** 調用 get_parameter_list。\n"
            "2. 如果是用戶要求「畫圖」、「趨勢」、「分佈」，請調用數據獲取工具（如 get_time_series_data）。\n"
            "3. get_time_series_data 的參數 'parameters' 必須是列表格式，例如 ['MEDIC-ABB_B41']。\n"
            "4. 如果用戶問的概念不在清單中，請調用 search_parameters_by_concept。\n"
            "5. 請回傳 JSON 格式: {'tool_name': '...', 'params': {...}}\n"
        )

        response = await self.llm.acomplete(prompt)
        try:
            clean_text = str(response.text).strip()
            # 1. 移除 Markdown 標記
            if "```" in clean_text:
                import re

                match = re.search(r"```(?:json)?(.*?)```", clean_text, re.DOTALL)
                if match:
                    clean_text = match.group(1).strip()

            # 2. 嘗試解析 JSON
            import ast

            try:
                decision = json.loads(clean_text)
            except json.JSONDecodeError:
                # Fallback: 嘗試使用 ast.literal_eval 處理 Python 風格的字典 (單引號)
                try:
                    decision = ast.literal_eval(clean_text)
                except Exception:
                    logger.warning(f"JSON Parsing failed completely. Raw: {clean_text}")
                    raise

            if not isinstance(decision, dict):
                raise ValueError("Parsed result is not a dictionary")

            tool_name = decision.get("tool_name")
            params = decision.get("params", {})
            params["file_id"] = ev.file_id

            # --- 參數補強 ( hallu-correction ) ---
            # 如果 LLM 把 parameters 寫成 column_name 或 parameter
            if "parameter" in params and "parameters" not in params:
                val = params["parameter"]
                params["parameters"] = val if isinstance(val, list) else [val]
            if "column_name" in params and "parameters" not in params:
                val = params["column_name"]
                params["parameters"] = val if isinstance(val, list) else [val]
            if "keyword" in params and "concept" not in params:
                params["concept"] = params["keyword"]

            # 確保 parameters 永遠是扁平列表 (避免 [[...]] 發生)
            if "parameters" in params and isinstance(params["parameters"], list):
                if len(params["parameters"]) > 0 and isinstance(
                    params["parameters"][0], list
                ):
                    params["parameters"] = params["parameters"][0]

            logger.info(
                f"🛠️ [Analysis Station] Calling tool: {tool_name} with params: {params}"
            )
            # 發送工具開始事件到串流
            ctx.write_event_to_stream(
                ProgressEvent(
                    msg=f"(Planning...) 分析策略已擬定，正在啟動 '{tool_name}' 以檢索對應數據..."
                )
            )
            ctx.write_event_to_stream(ToolCallEvent(tool=tool_name, params=params))

            result = self.tool_executor.execute_tool(tool_name, params, ev.session_id)

            # 計算取得筆數 (針對不同工具結果型態)
            data_count = "部分"
            if isinstance(result, list):
                data_count = len(result)
            elif isinstance(result, dict) and "data" in result:
                # 取得 data 字典中第一個列表的長度作為筆數
                first_val = (
                    next(iter(result["data"].values())) if result["data"] else []
                )
                if isinstance(first_val, list):
                    data_count = len(first_val)

            total_cols = summary.get("total_columns", 0) if summary else 0

            # 發送工具結果事件到串流
            ctx.write_event_to_stream(ToolResultEvent(tool=tool_name, result=result))
            ctx.write_event_to_stream(
                ProgressEvent(
                    msg=f"(Executing...) 數據檢索完成，共取得 {data_count} 筆記錄，準備進行可視化加工處理..."
                )
            )

            logger.info(
                f"📦 [Analysis Station] Tool Result Keys: {list(result.keys()) if isinstance(result, dict) else 'non-dict'}, count={data_count}"
            )

            # --- 語義擴展邏輯 (Self-Correction) ---
            # 如果是搜索工具但沒結果，且還沒重試過，則進入擴展流程
            is_search_tool = tool_name in [
                "get_parameter_list",
                "search_parameters_by_concept",
            ]
            has_no_results = not result.get("parameters") and not result.get(
                "matched_parameters"
            )

            # 使用 ctx.store 做為狀態儲存 (LlamaIndex Workflow 標準方式)
            retry_count = await ctx.store.get("retry_count", default=0)

            if is_search_tool and has_no_results and retry_count < 1:
                logger.info(
                    "🔍 [Analysis Station] No results found. Attempting semantic expansion..."
                )
                await ctx.store.set("retry_count", retry_count + 1)
                concept = params.get("keyword") or params.get("concept") or ev.query
                return ConceptExpansionEvent(
                    query=ev.query,
                    original_concept=concept,
                    file_id=ev.file_id,
                    session_id=ev.session_id,
                    history=ev.history,
                )
            # ------------------------------------
            # --- 智慧路徑分流 (Smart Skip) ---
            # 如果結果不包含數據（例如只是獲取欄位列表），則跳過繪圖站，直接進入總結站
            has_data = isinstance(result, dict) and "data" in result
            if has_data:
                logger.info(
                    "🎨 [Analysis Station] Data found. Routing to Visualizing Station."
                )
                return VisualizingEvent(
                    data=result,
                    query=ev.query,
                    session_id=ev.session_id,
                    history=ev.history,
                    row_count=data_count if isinstance(data_count, int) else 0,
                    col_count=total_cols,
                    mappings=mappings if isinstance(mappings, dict) else {},
                )
            else:
                logger.info(
                    "⏭️ [Analysis Station] No data for chart. Skipping to Summary Station."
                )
                return SummarizeEvent(
                    data=result,
                    query=ev.query,
                    session_id=ev.session_id,
                    history=ev.history,
                    row_count=data_count if isinstance(data_count, int) else 0,
                    col_count=total_cols,
                )

        except Exception as e:
            logger.error(f"❌ [Analysis Station] Error: {e}")
            return SummarizeEvent(
                data=f"分析工具執行失敗: {str(e)}",
                query=ev.query,
                session_id=ev.session_id,
                history=ev.history,
                row_count=0,
                col_count=0,
            )

    @step
    async def expand_concept(
        self, ctx: Context, ev: ConceptExpansionEvent
    ) -> AnalysisEvent:
        """
        [LLM Step] Semantic Expansion Station
        """
        logger.info(f"🧠 [Expansion Station] Expanding concept: {ev.original_concept}")

        prompt = (
            "你是一個工業與自動化專家。用戶在地端資料庫搜尋關鍵字失敗了。\n"
            f"原始關鍵字: {ev.original_concept}\n"
            "請思考在實際的生產數據集（CSV）中，這個概念可能對應的專業英文術語、縮寫或常見欄位名稱。\n"
            "例如：「壓力」可能對應 'Pressure', 'PRESS', 'Bar', 'PSI' 等。\n"
            "請提供 3-5 個最可能的替代關鍵字，並以 JSON 列表格式回傳：\n"
            '["term1", "term2", ...]\n'
            "不要回傳其他文字。"
        )

        response = await self.llm.acomplete(prompt)
        try:
            expanded_terms = json.loads(str(response.text).strip())
            new_query = f"請幫我搜尋以下相關欄位: {', '.join(expanded_terms)}"
            logger.info(f"💡 [Expansion Station] Expanded to: {expanded_terms}")

            return AnalysisEvent(
                query=new_query,
                file_id=ev.file_id,
                session_id=ev.session_id,
                history=ev.history
                + f"\n系統提示: 自動重試語義擴展搜尋: {expanded_terms}",
            )
        except Exception as e:
            logger.warning(f"⚠️ [Expansion Station] Expansion process failed: {str(e)}")
            # 如果解析失敗，就用原始問題再試一次，但會因為 retry_count 停止
            return AnalysisEvent(
                query=ev.query,
                file_id=ev.file_id,
                session_id=ev.session_id,
                history=ev.history,
            )

    @step
    async def execute_translation(
        self, ctx: Context, ev: TranslationEvent
    ) -> VisualizingEvent:
        # Debug Log
        logger.info(
            f"🔄 [Translation Station] Processing translation intent for query: {ev.query}"
        )
        return VisualizingEvent(
            data=None,
            query=ev.query,
            session_id=ev.session_id,
            history=ev.history,
        )

    def _build_programmatic_chart(self, ev: VisualizingEvent) -> Optional[str]:
        """
        純程式邏輯生成的圖表 JSON，完全不依賴 LLM，確保 100% 穩定。
        """
        try:
            if (
                not isinstance(ev.data, dict)
                or "data" not in ev.data
                or not ev.data["data"]
            ):
                return None

            actual_data = ev.data["data"]
            query_lower = ev.query.lower()
            is_histogram = (
                any(kw in query_lower for kw in ["直方圖", "histogram", "分佈", "分布"])
                and "趨勢" not in query_lower
            )
            is_scatter = any(kw in query_lower for kw in ["散佈", "scatter", "相關性"])
            is_dual_axis = any(kw in query_lower for kw in ["雙軸", "dual", "不同刻度"])

            if is_histogram:
                # ... [Histogram logic preserved] ...
                logger.info("📊 [Visualizer] Building Histogram.")
                target_col = None
                for col, vals in actual_data.items():
                    if col not in [
                        "CONTEXTID",
                        "TIME",
                        "Timestamp",
                        "Date",
                        "時間",
                    ] and any(isinstance(v, (int, float)) for v in vals[:20]):
                        target_col = col
                        break

                if not target_col:
                    return None
                values = [
                    v for v in actual_data[target_col] if isinstance(v, (int, float))
                ]
                if not values:
                    return None

                v_min, v_max = min(values), max(values)
                if v_min == v_max:
                    v_max += 1.0
                num_bins = 15
                bin_size = (v_max - v_min) / num_bins
                bins = [0] * num_bins
                for v in values:
                    idx = int((v - v_min) / bin_size)
                    idx = min(idx, num_bins - 1)
                    bins[idx] += 1

                labels = [
                    f"{v_min + i * bin_size:.2f}-{v_min + (i + 1) * bin_size:.2f}"
                    for i in range(num_bins)
                ]
                chart_obj = {
                    "type": "chart",
                    "chart_type": "bar",
                    "title": f"{ev.mappings.get(target_col, target_col)} 數據分佈直方圖",
                    "labels": labels,
                    "datasets": [
                        {
                            "label": "頻次",
                            "data": bins,
                            "backgroundColor": "rgba(54, 162, 235, 0.6)",
                            "borderColor": "rgb(54, 162, 235)",
                        }
                    ],
                }
                final_labels, datasets = labels, chart_obj["datasets"]

            elif is_scatter:
                logger.info("📊 [Visualizer] Building Scatter Plot.")
                numeric_cols = []
                for col, vals in actual_data.items():
                    if col not in [
                        "CONTEXTID",
                        "TIME",
                        "Timestamp",
                        "Date",
                        "時間",
                    ] and any(isinstance(v, (int, float)) for v in vals[:10]):
                        numeric_cols.append(col)

                if len(numeric_cols) < 2:
                    return None  # 散佈圖至少要兩個維度

                col_x, col_y = numeric_cols[0], numeric_cols[1]
                scatter_data = []
                for i in range(min(len(actual_data[col_x]), 100)):  # 限制 100 點
                    vx, vy = actual_data[col_x][i], actual_data[col_y][i]
                    if isinstance(vx, (int, float)) and isinstance(vy, (int, float)):
                        scatter_data.append({"x": vx, "y": vy})

                chart_obj = {
                    "type": "chart",
                    "chart_type": "scatter",
                    "title": f"相關性分析: {ev.mappings.get(col_x, col_x)} vs {ev.mappings.get(col_y, col_y)}",
                    "datasets": [
                        {
                            "label": f"{ev.mappings.get(col_x, col_x)} / {ev.mappings.get(col_y, col_y)}",
                            "data": scatter_data,
                        }
                    ],
                    "options": {
                        "scales": {
                            "x": {
                                "title": {
                                    "display": True,
                                    "text": ev.mappings.get(col_x, col_x),
                                },
                                "grid": {"display": True},
                            },
                            "y": {
                                "title": {
                                    "display": True,
                                    "text": ev.mappings.get(col_y, col_y),
                                }
                            },
                        }
                    },
                }
                final_labels, datasets = [], chart_obj["datasets"]

            else:
                # 趨勢圖 (Line Chart) 邏輯，增加雙軸偵測
                labels = []
                label_col = next(
                    (
                        c
                        for c in ["CONTEXTID", "TIME", "Timestamp", "Date", "時間"]
                        if c in actual_data
                    ),
                    None,
                )
                first_col_data = next(iter(actual_data.values()))
                labels = (
                    actual_data[label_col]
                    if label_col
                    else list(range(1, len(first_col_data) + 1))
                )

                datasets = []
                max_points = 50
                for col_name, values in actual_data.items():
                    if col_name == label_col:
                        continue
                    sampled = values[:: max(1, len(values) // max_points)][:max_points]
                    if not any(isinstance(x, (int, float)) for x in sampled[:5]):
                        continue

                    friendly_name = ev.mappings.get(col_name, col_name)
                    datasets.append(
                        {
                            "label": friendly_name,
                            "raw_max": max(
                                [v for v in sampled if isinstance(v, (int, float))]
                                or [0]
                            ),
                            "data": sampled,
                        }
                    )
                    if len(datasets) >= 30:
                        break

                if not datasets:
                    return None

                # 雙軸自動偵測：如果最大值相差 10 倍以上，且用戶沒反對 OR 用戶明確要求
                if (len(datasets) >= 2 and is_dual_axis) or (
                    len(datasets) >= 2
                    and max(d["raw_max"] for d in datasets)
                    / (min(d["raw_max"] for d in datasets) or 1)
                    > 10
                ):
                    logger.info(
                        "📊 [Visualizer] Auto-detected scale mismatch, enabling Dual Y-Axis."
                    )
                    # 將最大值較大的 dataset 放到了右軸 (y1)
                    idx_max = 0
                    curr_max = -1
                    for i, d in enumerate(datasets):
                        if d["raw_max"] > curr_max:
                            curr_max = d["raw_max"]
                            idx_max = i

                    datasets[idx_max]["yAxisID"] = "y1"
                    chart_options = {
                        "scales": {
                            "y1": {
                                "type": "linear",
                                "display": True,
                                "position": "right",
                                "title": {
                                    "display": True,
                                    "text": datasets[idx_max]["label"],
                                },
                                "grid": {"drawOnChartArea": False},
                            }
                        }
                    }
                else:
                    chart_options = {}

                final_labels = labels[:: max(1, len(labels) // max_points)][:max_points]
                chart_obj = {
                    "type": "chart",
                    "chart_type": "line",
                    "title": f"數據趨勢分析: {ev.query[:20]}",
                    "labels": final_labels,
                    "datasets": datasets,
                    "options": chart_options,
                }

            logger.info(
                f"📊 [Visualizer] Generated chart_obj with {len(datasets)} datasets and {len(final_labels)} labels."
            )
            return json.dumps(chart_obj, ensure_ascii=False)
        except Exception as e:
            logger.error(f"❌ [Visualizer] Programmatic chart build failed: {e}")
            return None

    @step
    async def visualize_data(
        self, ctx: Context, ev: VisualizingEvent
    ) -> SummarizeEvent:
        """
        [Hybrid Step] 繪圖工作站 - 先嘗試程式生成，失敗才用 LLM (目前強制程式生成以求穩定)
        """
        ctx.write_event_to_stream(
            ProgressEvent(
                msg="(Visualizing...) 技術分析完成，正在精準繪製數據趨勢圖..."
            )
        )

        # 改為程式化生成，確保穩定
        chart_json = self._build_programmatic_chart(ev)

        if chart_json:
            logger.info(
                f"🎨 [Visualizer] Programmatic chart generated. Len: {len(chart_json)}"
            )
            # 完整印出 JSON 以便除錯 (僅限目前開發偵錯階段)
            logger.debug(f"🎨 [Visualizer] Full Chart JSON: {chart_json}")
        else:
            logger.info("🎨 [Visualizer] No chart generated (data invalid or empty).")

        return SummarizeEvent(
            data=ev.data,
            query=ev.query,
            session_id=ev.session_id,
            history=ev.history,
            chart_json=chart_json,
            row_count=ev.row_count,
            col_count=ev.col_count,
        )

    @step
    async def humanizer(self, ctx: Context, ev: SummarizeEvent) -> StopEvent:
        """
        [LLM Step] 結果總結工作站 - 專注於自然語言分析報告
        """
        ctx.write_event_to_stream(
            ProgressEvent(
                msg="(Humanizing...) 圖表已生成，正在撰寫分析報告並提供專家建議..."
            )
        )
        logger.info("✍️ [Humanizer Station] Generating summary...")

        # 數據抽樣 (避免數據量過大導致 Prompt 超長或 LLM 混亂)
        display_data = ev.data
        if isinstance(ev.data, dict) and "data" in ev.data:
            # 複製一份來抽樣
            display_data = ev.data.copy()
            actual_data = ev.data.get("data", {})
            sampled_data = {}
            for k, v in actual_data.items():
                if isinstance(v, list) and len(v) > 50:
                    # 每 20 點取 1 點，確保 LLM 能看到趨勢但又不會淹沒在數字中
                    step = len(v) // 50
                    sampled_data[k] = v[::step][:50]
                else:
                    sampled_data[k] = v
            display_data["data"] = sampled_data
            display_data["_is_sampled"] = True
            display_data["_original_count"] = (
                len(next(iter(actual_data.values()))) if actual_data else 0
            )

        # 安全序列化函式
        def safe_json_dumps(obj):
            try:
                return json.dumps(obj, ensure_ascii=False, default=str)
            except Exception as e:
                logger.error(f"❌ [Humanizer] JSON serialization failed: {e}")
                return "{}"

        data_json_str = safe_json_dumps(ev.data)
        logger.info(
            f"📊 [Humanizer] Injecting data into prompt. Size: {len(data_json_str)} chars"
        )

        prompt = (
            "你是一個專業的工業數據分析專家。你 **必須全程使用 繁體中文 (Traditional Chinese)** 回答用戶。\n"
            "如果你有圖表數據，請結合圖表內容進行深入的專家級分析。\n"
            "\n"
            "**輸出準則**:\n"
            "1. **嚴禁英文回覆**: 所有的描述、總結都必須是繁體中文。\n"
            "2. **專家建議**: 請針對分析結果給出 3-5 點具體的專業建議。\n"
            "3. **格式說明**: 圖表已經在下方由系統自動加載，你不需要再次輸出 JSON 格式，只需專注於文字分析。\n"
            "\n"
            f"用戶問題: {ev.query}\n"
            f"本次分析涵蓋數據筆數: {ev.row_count}\n"
            f"本次分析涵蓋總欄位數: {ev.col_count}\n"
            f"重要提示: 僅針對這 {ev.row_count} 筆數據進行精確描述，嚴禁虛構數據量。總欄位數應以 {ev.col_count} 為準。\n"
            f"分析數據範例: {json.dumps(ev.data, ensure_ascii=False, default=str)[:2000]} (已省略過長部分)\n"
            f"對話歷史: {ev.history}\n"
        )

        # 強力防護：偵測 Prompt 自身是否含損毀物件標記
        if "[object Object]" in prompt:
            logger.warning(
                "⚠️ [Humanizer] [object Object] detected in incoming prompt history/data."
            )

        # 確保 chart_json 絕對是字串或 None
        final_chart_json = ev.chart_json
        if final_chart_json and not isinstance(final_chart_json, str):
            logger.warning(
                f"⚠️ [Humanizer] chart_json is not a string (type={type(final_chart_json)}), forcing conversion."
            )
            final_chart_json = json.dumps(final_chart_json, ensure_ascii=False)

        if final_chart_json and "[object Object]" in str(final_chart_json):
            logger.error(
                "⚠️ [Humanizer] Caught [object Object] in chart_json. (Reporting but NOT clearing as requested for debug)"
            )

        # 將圖表設為後置 (Suffix)，避免打字機渲染時圖表一直重新跳動
        suffix = ""
        if final_chart_json:
            suffix = f"\n\n```json\n{final_chart_json}\n```\n"
            logger.info(
                f"🎨 [Humanizer] Chart JSON prepared as suffix. Len: {len(suffix)}"
            )
        else:
            logger.info("🎨 [Humanizer] No chart JSON to inject.")

        logger.info("✍️ [Humanizer] Starting stream...")

        # 建立一個內部變數來精確追蹤串流內容，不依賴 chunk.text
        streamed_text = ""

        async for chunk in self.llm.astream_complete(prompt):
            # Ensure content is string to prevent [object Object]
            delta = chunk.delta
            if delta is not None:
                content_str = str(delta)
                # 某些 LLM 可能會回傳物件或奇怪的字串
                if content_str == "[object Object]":
                    logger.warning(
                        "⚠️ [Humanizer] [object Object] detected in LLM stream chunk!"
                    )
                    content_str = ""  # Clear it if it's just the literal object string

                if content_str:
                    # 偵測過濾: 若 Chunk 包含 [object Object]
                    if "[object Object]" in content_str:
                        logger.warning(
                            "⚠️ [Humanizer] [object Object] detected in LLM stream chunk!"
                        )
                        content_str = content_str.replace(
                            "[object Object]", "(數據異常)"
                        )

                    ctx.write_event_to_stream(TextChunkEvent(content=content_str))
                    streamed_text += content_str

        # 在串流結束後，再注入圖表 Suffix
        if suffix:
            logger.info(
                f"🎨 [Humanizer] Appending chart suffix to finished stream... len={len(suffix)}"
            )
            # 提供更多前綴細節以便確認是否有 [object Object]
            logger.info(f"🎨 [Humanizer] Suffix sample (200 chars): {suffix[:200]}")
            ctx.write_event_to_stream(TextChunkEvent(content=suffix))

        # 最終完整回應內容
        full_response = streamed_text + suffix

        result = {
            "response": full_response,
            "tool_result": ev.data,
            "tool_used": "AnalysisTool",
            "thoughts": ["數據分析完成", "正在等待結果渲染"],
        }
        return StopEvent(result=result)

    @step
    async def handle_error(self, ctx: Context, ev: ErrorEvent) -> StopEvent:
        """
        [Local Step] 錯誤處理站
        當任何步驟拋出 ErrorEvent 時，在此攔截並回傳錯誤訊息。
        """
        logger.error(f"❌ [Error Station] Workflow Error: {ev.error}")
        result = {
            "response": f"抱歉，系統運作出現錯誤：{ev.error}",
            "tool_result": None,
            "thoughts": ["流程中斷", "錯誤處理完成"],
        }
        return StopEvent(result=result)


# 為了保持向上相容性，我們保留 LLMAnalysisAgent 類別名，但內部切換為 Workflow
class LLMAnalysisAgent:
    def __init__(self, tool_executor: ToolExecutor, **kwargs):
        self.workflow = SigmaAnalysisWorkflow(tool_executor=tool_executor, **kwargs)
        # 依照 session_id 儲存記憶
        self.memories: Dict[str, ChatMemoryBuffer] = {}

    def _get_memory(self, session_id: str) -> ChatMemoryBuffer:
        if session_id not in self.memories:
            self.memories[session_id] = ChatMemoryBuffer.from_defaults(token_limit=8000)
        return self.memories[session_id]

    async def analyze(
        self, session_id: str, file_id: str, user_question: str
    ) -> Dict[str, Any]:
        memory = self._get_memory(session_id)
        history_msgs = memory.get_all()
        history_str = "\n".join([f"{m.role}: {m.content}" for m in history_msgs])

        result = await self.workflow.run(
            query=user_question,
            file_id=file_id,
            session_id=session_id,
            history=history_str,
        )

        # 紀錄記憶
        memory.put(ChatMessage(role="user", content=user_question))
        memory.put(ChatMessage(role="assistant", content=result.get("response", "")))

        return result

    async def stream_analyze(
        self, session_id: str, file_id: str, user_question: str, analysis_service=None
    ):
        """
        [Generator] 串流分析用戶問題 (Workflow 模式)
        """
        memory = self._get_memory(session_id)
        history_msgs = memory.get_all()
        history_str = "\n".join([f"{m.role}: {m.content}" for m in history_msgs])

        try:
            handler = self.workflow.run(
                query=user_question,
                file_id=file_id,
                session_id=session_id,
                history=history_str,
                timeout=180,
            )

            # 用於追蹤本次對話產生的新內容 (用於過濾校驗)
            newly_accumulated_text = ""

            async for event in handler.stream_events():
                # 檢查停止信號
                if analysis_service and analysis_service.is_generation_stopped(
                    session_id
                ):
                    yield json.dumps(
                        {"type": "error", "content": "[系統提示] 生成已手動停止"},
                        ensure_ascii=False,
                    )
                    return  # 直接退出

                # Workflow 事件處理
                event_type = type(event).__name__
                if event_type == "IntentEvent":
                    yield json.dumps(
                        {
                            "type": "thought",
                            "content": f"(Thinking...) 正在分析意圖: {event.intent}",
                        },
                        ensure_ascii=False,
                    )
                elif event_type == "AnalysisEvent":
                    yield json.dumps(
                        {
                            "type": "thought",
                            "content": "(Scanning/Retrieving...) 正在從地端資料庫檢索數據...",
                        },
                        ensure_ascii=False,
                    )
                elif event_type == "SummarizeEvent":
                    yield json.dumps(
                        {
                            "type": "thought",
                            "content": "(Humanizing...) 數據彙整完成，正在將技術參數轉化為易懂的中文分析報告...",
                        },
                        ensure_ascii=False,
                    )
                elif event_type == "ProgressEvent":
                    yield json.dumps(
                        {"type": "thought", "content": event.msg},
                        ensure_ascii=False,
                    )
                elif event_type == "TranslationEvent":
                    yield json.dumps(
                        {"type": "thought", "content": "正在準備對話回應..."},
                        ensure_ascii=False,
                    )
                elif event_type == "VisualizingEvent":
                    yield json.dumps(
                        {
                            "type": "thought",
                            "content": "(Visualizing...) 數據檢索成功，正在繪製分析圖表...",
                        },
                        ensure_ascii=False,
                    )
                elif event_type == "ConceptExpansionEvent":
                    yield json.dumps(
                        {
                            "type": "thought",
                            "content": f"🔍 發現無直接匹配欄位，正在進行語義擴展分析: {event.original_concept}",
                        },
                        ensure_ascii=False,
                    )
                elif event_type == "TextChunkEvent":
                    # TextChunkEvent 由 Humanizer 觸發
                    content = event.content
                    if not isinstance(content, str):
                        try:
                            content = json.dumps(content, ensure_ascii=False)
                        except Exception:
                            content = str(content)

                    # 累計校驗 (防止 [object Object] 被切分在多個 chunk)
                    newly_accumulated_text += content
                    if "[object Object]" in newly_accumulated_text:
                        # 如果是本區塊包含完整物件，則清理
                        if "[object Object]" in content:
                            content = content.replace("[object Object]", "(數據異常)")
                        else:
                            # 可能是跨 Chunk 的 [object Object]，交由最後的 final_text 取代處理
                            pass

                    if content:
                        yield json.dumps(
                            {"type": "text_chunk", "content": content},
                            ensure_ascii=False,
                        )
                elif event_type == "ToolCallEvent":
                    yield json.dumps(
                        {
                            "type": "tool_call",
                            "tool": event.tool,
                            "params": event.params,
                        },
                        ensure_ascii=False,
                    )
                elif event_type == "ToolResultEvent":
                    # 某些工具回傳的是 ToolOutput 物件，需提取 content
                    res = event.result
                    if hasattr(res, "content"):
                        res = res.content
                    elif not isinstance(
                        res, (dict, list, str, int, float, bool, type(None))
                    ):
                        res = str(res)

                    # 再次對字串結果做安全檢查
                    if str(res) == "[object Object]":
                        res = {
                            "status": "success",
                            "message": "工具執行完成，但回傳格式異常 (Caught [object Object] in Python)",
                        }

                    # 防止 res 為 None 或非串行化對象
                    try:
                        # 測試序列化
                        json.dumps(res)
                    except Exception:
                        res = str(res)

                    yield json.dumps(
                        {
                            "type": "tool_result",
                            "tool": event.tool,
                            "result": res,
                        },
                        ensure_ascii=False,
                    )

            # 等待最終結果
            final_result = await handler
            # 如果 workflow 回傳的是對象而非 dict，嘗試轉化
            if not isinstance(final_result, dict):
                final_result = {"response": str(final_result)}

            # 紀錄記憶 (移除圖表數據塊以節省 Token 並防止損毀數據污染記憶)
            import re

            final_text = str(final_result.get("response", "")) or ""

            # 偵測過濾: 若最終文本包含 [object Object]
            if "[object Object]" in final_text:
                logger.warning(
                    "⚠️ [SSE] [object Object] detected in final response content."
                )

            # 移除所有 ```json ... ``` 區塊
            memory_safe_text = re.sub(
                r"```json.*?```",
                "\n(互動式圖表數據已從對話記憶中移除以節省 Token)\n",
                final_text,
                flags=re.DOTALL,
            )

            # 存入記憶前偵測
            if "[object Object]" in memory_safe_text:
                logger.warning(
                    "⚠️ [Memory] [object Object] found in text being saved to memory."
                )

            memory.put(ChatMessage(role="user", content=user_question))
            memory.put(ChatMessage(role="assistant", content=memory_safe_text))

            yield json.dumps(
                {
                    "type": "response",
                    "content": final_text,
                    "tool_result": final_result.get("tool_result"),
                },
                ensure_ascii=False,
            )
        except Exception as e:
            logger.error(f"❌ [Stream Analyze] Critical error: {str(e)}", exc_info=True)
            yield json.dumps(
                {
                    "type": "error",
                    "content": f"分析過程發生錯誤: {str(e)}。請嘗試縮短問題或重新選擇檔案。",
                },
                ensure_ascii=False,
            )

    async def clear_session(self, session_id: str = "default"):
        if session_id in self.memories:
            self.memories[session_id].reset()
