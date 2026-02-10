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
from .types import (
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
    async def acomplete(self, prompt: str, **kwargs: Any) -> CompletionResponse:
        """核心非串流回傳，優化回應速度"""
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
                except:
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
                    for kw in ["欄位", "參數", "清單", "哪些", "哪兩個", "哪幾個"]
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

        # --- 安全閥：限制步數防止無窮迴圈 ---
        MAX_STEPS = 3
        is_last_step = ev.step_count >= MAX_STEPS

        tool_specs = self.tool_executor.list_tools()
        all_columns = ", ".join(params_list)

        # 構建過去步驟的背景資訊
        history_context = ""
        if ev.prev_results:
            history_context = "\n### 前序分析結果摘要 ###\n" + json.dumps(
                ev.prev_results, ensure_ascii=False
            )

        quality_stats = summary.get("quality_stats", {})
        null_count = quality_stats.get("null_column_count", 0)
        const_count = quality_stats.get("constant_column_count", 0)
        sparse_count = quality_stats.get("sparse_column_count", 0)

        null_preview = ", ".join(quality_stats.get("null_columns_preview", []))
        const_preview = ", ".join(quality_stats.get("constant_columns_preview", []))
        sparse_preview = ", ".join(quality_stats.get("sparse_columns_preview", []))

        quality_info = (
            f"偵測到 {null_count} 個空值欄位 (例: {null_preview})"
            if null_count > 0
            else "無明顯空值欄位"
        )
        quality_info += (
            f"；{const_count} 個定值欄位 (例: {const_preview})"
            if const_count > 0
            else "；數據皆具備變化性"
        )
        if sparse_count > 0:
            quality_info += (
                f"；另有 {sparse_count} 個欄位的真值比例低於 80% (例: {sparse_preview})"
            )

        prompt = (
            f"你是一個機靈且嚴謹的工業數據分析專家。目前是診斷的第 {ev.step_count} 步。\n"
            f"基礎數據資訊: 當前檔案共有 {total_rows} 行數據，{total_cols} 個欄位。\n"
            f"數據品質警訊 (絕對事實): {quality_info}\n"
            f"所有可用欄位: {all_columns}\n"
            "可用工具箱: " + json.dumps(tool_specs, ensure_ascii=False) + "\n"
            f"用戶問題: {ev.query}\n"
            f"{history_context}\n\n"
            "## 決策準則 ##\n"
            "1. **效率至上**: 如果目前的分析結果（如有）已經能完全回答用戶問題，請立即選擇 'finish' 動作，嚴禁執行不必要的工具。\n"
            "2. **邏輯連貫**: 只有在需要更多證據（如發現異常後需要找原因）時才使用工具。\n"
            "3. **內心獨白**: 請使用【繁體中文】在 monologue 中簡述你的診斷策略，不要列出所有工具。\n"
            f"4. **步數限制**: 目前剩餘 {MAX_STEPS - ev.step_count} 次工具調用機會。\n"
            f"{'！！！注意：這是最後一步，必須結論導向，選擇 finish 並彙整所有發現！！！' if is_last_step else ''}\n"
            '輸出唯一 JSON: {"action": "call_tool"|"finish", "tool_name": "...", "params": {...}, "monologue": "..."}'
        )

        response = await self.llm.acomplete(prompt)
        try:
            text = response.text.strip()
            if "```" in text:
                text = text.split("```")[1].replace("json", "").strip()
            decision = json.loads(text)

            action = decision.get("action", "call_tool")
            monologue = decision.get("monologue", "診斷中...")

            # 向前端發送 AI 的思考過程
            ctx.write_event_to_stream(
                ProgressEvent(msg=f"(Step {ev.step_count}) {monologue}")
            )

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

                # 否則進入總結報告階段
                aggregated_data = {
                    "final_decision": monologue,
                    "all_steps_results": ev.prev_results,
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
                )

            # 否則，執行工具並進入下一步循環
            tool_name = decision.get("tool_name")
            params = decision.get("params", {})
            params["file_id"] = ev.file_id

            # 根據工具名提供動態的進度提示
            tool_display_names = {
                "get_time_series_data": "正在讀取數據趨勢...",
                "detect_outliers": "正在偵測異常點...",
                "get_top_correlations": "正在分析因素相關性...",
                "analyze_distribution": "正在分析數據分佈...",
            }
            display_msg = tool_display_names.get(tool_name, f"執行工具 {tool_name}...")
            ctx.write_event_to_stream(ProgressEvent(msg=f"(Executing) {display_msg}"))

            ctx.write_event_to_stream(ToolCallEvent(tool=tool_name, params=params))
            result = self.tool_executor.execute_tool(tool_name, params, ev.session_id)
            ctx.write_event_to_stream(ToolResultEvent(tool=tool_name, result=result))

            # 將結果存入歷史，並遞增步數發送下一個 AnalysisEvent (Loop)
            new_results = ev.prev_results + [
                {"step": ev.step_count, "tool": tool_name, "result": result}
            ]

            return AnalysisEvent(
                query=ev.query,
                file_id=ev.file_id,
                session_id=ev.session_id,
                history=ev.history,
                mode=ev.mode,
                step_count=ev.step_count + 1,
                prev_results=new_results,
            )

        except Exception as e:
            logger.error(f"Analysis loop failed at step {ev.step_count}: {e}")
            summary = self.tool_executor.analysis_service.load_summary(
                ev.session_id, ev.file_id
            )
            total_rows = summary.get("total_rows", 0) if summary else 0
            total_cols = summary.get("total_columns", 0) if summary else 0

            return SummarizeEvent(
                data=f"分析過程遇到挑戰: {str(e)}",
                query=ev.query,
                file_id=ev.file_id,
                session_id=ev.session_id,
                history=ev.history,
                mode=ev.mode,
                row_count=total_rows,
                col_count=total_cols,
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

        if ev.mode == "fast":
            system_instruction = (
                "作為數據專家，請精簡回答。若數據中包含具體分析結果（如相關性數值、異常點），"
                "請主動摘要最重要的發現，避免空洞的回覆。不必過度受限於 150 字，重點是『精簡且有料』。"
            )
        else:
            system_instruction = (
                "專注於深度技術分析報告。請結合提供的數據，進行多維度的結果解讀、"
                "嘗試分析參數間可能的物理或邏輯因果關係，並給出具體的操作或改善建議。"
            )

        prompt = (
            f"系統指令: {system_instruction}\n"
            f"用戶提問: {ev.query}\n"
            f"數據概況 (背景): 包含 {row_count} 行與 {col_count} 個欄位。欄位清單預覽: {', '.join(params_list[:100])}...\n"
            f"分析數據 (具體內容): {json.dumps(ev.data, ensure_ascii=False)[:3500]}\n"
            "重要規則:\n"
            "1. 若數據中已有分析出的具體指標（如相關係數、異常點），必須在回覆中具體呈現，不要只給籠統描述。\n"
            "2. 若用戶要求『更多資訊』，請檢查數據預覽中是否還有未提到的細節並釋出，而非反問用戶。\n"
            "3. 請用繁體中文自然地回答。"
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
