from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import StreamingResponse, PlainTextResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import httpx
import json
import logging
import asyncio
import shutil

# 使用新的 AnalysisService 與 Workflow
from backend.services.analysis.analysis_service import AnalysisService
from backend.services.analysis.agent import SigmaAnalysisWorkflow
from backend.services.analysis.analysis_types import (
    MonologueEvent,
    ProgressEvent,
    TextChunkEvent,
    ToolResultEvent,
    ErrorEvent,
    CodeBlockEvent,
    CodeOutputEvent,
    ChartImageEvent,
)
from backend.services.analysis.tools.executor import ToolExecutor
from backend.dependencies import (
    get_intelligent_analysis_service,
    get_analysis_service as get_old_analysis_service,
)
from backend.models.request_models import (
    TrainRequest,
    QuickAnalysisRequest,
    SaveFileRequest,
    AdvancedAnalysisRequest,
)
from backend.services.chat_history_service import ChatHistoryService

router = APIRouter(tags=["Intelligent Analysis"])
logger = logging.getLogger(__name__)

_chat_history = ChatHistoryService()

# ========== 依賴注入 ==========

# [SHARED STATE] 只共享 _last_states 字典, 不共享整個 Orchestrator
# 這樣每個請求有獨立的 Strategist/Planner (避免跨 Session 污染),
# 但分析狀態 (用於 Resume) 可以跨請求保留。
_shared_last_states: dict = {}


def get_tool_executor(
    analysis_service: AnalysisService = Depends(get_intelligent_analysis_service),
):
    return ToolExecutor(analysis_service)


def get_analysis_workflow(
    analysis_service: AnalysisService = Depends(get_intelligent_analysis_service),
    tool_executor: ToolExecutor = Depends(get_tool_executor),
):
    workflow = SigmaAnalysisWorkflow(tool_executor, analysis_service)
    # 每次請求建立新的 Orchestrator (獨立 Roles),
    # 但注入共享的 _last_states dict 讓 Resume 功能跨請求保留
    from backend.services.analysis.agents.orchestrated_agent_v2 import (
        OrchestratedAnalysisAgentV2,
    )

    workflow.orchestrator = OrchestratedAnalysisAgentV2(
        workflow.llm,
        tool_executor,
        analysis_service=analysis_service,
        shared_states=_shared_last_states,
        chat_history_service=_chat_history,
    )
    return workflow


# --- V3 Workflow Factory ---
_shared_v3_states: dict = {}


def get_analysis_workflow_v3(
    analysis_service: AnalysisService = Depends(get_intelligent_analysis_service),
    tool_executor: ToolExecutor = Depends(get_tool_executor),
):
    """建立 V3 劇本驅動 Workflow (與 V2 並存)"""
    from backend.services.analysis.agents.orchestrated_agent_v3 import (
        OrchestratedAnalysisAgentV3,
    )
    from backend.services.analysis.agent import CustomOllamaLLM
    import config

    llm = CustomOllamaLLM(
        model_name=config.LLM_MODEL,
        api_url=config.LLM_API_URL,
    )
    workflow = OrchestratedAnalysisAgentV3(
        llm=llm,
        tool_executor=tool_executor,
        analysis_service=analysis_service,
        shared_states=_shared_v3_states,
        chat_history_service=_chat_history,
    )
    return workflow


# ========== 請求/響應模型 ==========


class PrepareFileRequest(BaseModel):
    filename: str
    session_id: str = "default"
    conversation_id: str = "default"


class PrepareFileResponse(BaseModel):
    status: str
    file_id: str
    summary: Dict[str, Any]
    message: str


class AttachmentItem(BaseModel):
    name: str
    type: str  # MIME, e.g. "image/png"
    data: str  # base64 data-URL


class ChatRequest(BaseModel):
    session_id: str = "default"
    file_id: Optional[str] = ""
    message: str
    conversation_id: Optional[str] = "default"
    mode: str = "fast"  # 'fast' or 'full'
    suspect_params: Optional[List[str]] = None
    target_range: Optional[str] = None
    baseline_range: Optional[str] = None
    optimization_targets: Optional[List[dict]] = None
    attachments: Optional[List[AttachmentItem]] = None


class ChatResponse(BaseModel):
    response: str
    data: Optional[Any] = None
    chart: Optional[Any] = None


class FileListResponse(BaseModel):
    files: List[Dict[str, Any]]


class MappingStatusResponse(BaseModel):
    active_mapping: Optional[str] = None
    status: str


# ========== API 端點 ==========


@router.post("/prepare", response_model=PrepareFileResponse)
async def prepare_file_for_analysis(
    request: PrepareFileRequest,
    analysis_service: AnalysisService = Depends(get_intelligent_analysis_service),
):
    """
    預處理檔案：建立索引、生成摘要
    """
    try:
        success, message, summary = await analysis_service.prepare_file(
            request.session_id,
            request.filename,
            conversation_id=request.conversation_id,
        )
        if not success:
            raise HTTPException(status_code=400, detail=message)

        return PrepareFileResponse(
            status="success",
            file_id=analysis_service.get_file_id(
                request.filename, conversation_id=request.conversation_id
            ),
            summary=summary,
            message=message,
        )
    except Exception as e:
        logger.error(f"Error preparing file: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat", response_model=ChatResponse)
async def chat_with_ai(
    request: ChatRequest,
    workflow: SigmaAnalysisWorkflow = Depends(get_analysis_workflow),
):
    """
    智能對話分析 (同步模式)
    """
    try:
        # 加载对话历史
        history_text = _chat_history.load_history_as_text(
            request.session_id, file_id=request.file_id
        )
        # 保存用户消息
        _chat_history.save_message(
            request.session_id, "user", request.message, file_id=request.file_id
        )

        result = await workflow.run(
            query=request.message,
            file_id=request.file_id,
            session_id=request.session_id,
            history=history_text,
        )
        # result 是 StopEvent.result，應該是個 dict
        response_text = result.get("response", "")

        # 保存 AI 回复
        _chat_history.save_message(
            request.session_id, "assistant", response_text, file_id=request.file_id
        )

        return ChatResponse(
            response=response_text,
            data=result.get("data"),
            chart=result.get("chart"),
        )
    except Exception as e:
        logger.error(f"Error in chat: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class StopRequest(BaseModel):
    session_id: str = "default"


@router.post("/chat/stop")
async def stop_chat_generation(
    request: StopRequest,
    analysis_service: AnalysisService = Depends(get_intelligent_analysis_service),
):
    """
    強制停止當前的 AI 分析生成，並觸發立即總結
    """
    analysis_service.stop_generation(request.session_id)
    return {"status": "stopping", "message": "Stop signal sent"}


@router.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    workflow: SigmaAnalysisWorkflow = Depends(get_analysis_workflow),
):
    """
    智能對話分析 (SSE串流模式)
    """

    # 加载对话历史 + 保存用户消息 (在 generator 外做，避免并发问题)
    history_text = _chat_history.load_history_as_text(
        request.session_id,
        file_id=request.file_id,
        conversation_id=request.conversation_id,
    )
    _chat_history.save_message(
        request.session_id,
        "user",
        request.message,
        file_id=request.file_id,
        conversation_id=request.conversation_id,
    )

    # 載入先前分析上下文 (供追問使用)
    _prev_ctx = _chat_history.load_analysis_context(
        request.session_id, file_id=request.file_id
    )
    if _prev_ctx:
        _ctx_parts = []
        _at = _prev_ctx.get("auto_targets", [])
        if _at:
            _ctx_parts.append(
                f"先前識別的異常參數({len(_at)}個): {', '.join(_at[:15])}"
            )
        _atg = _prev_ctx.get("anomaly_type_groups", [])
        if _atg:
            for g in _atg[:5]:
                tcn = g.get("type_cn", g.get("type", ""))
                params = g.get("parameters", [])
                _ctx_parts.append(f"{tcn}: {', '.join(params[:5])}")
        _kf = _prev_ctx.get("key_findings", [])
        if _kf:
            _ctx_parts.append("重要發現: " + "; ".join(_kf[:5]))
        _fi = _prev_ctx.get("follow_up_items", [])
        if _fi:
            labels = []
            for item in _fi[:5]:
                if isinstance(item, dict):
                    labels.append(item.get("label", str(item)))
                else:
                    labels.append(str(item))
            _ctx_parts.append(f"後續追蹤項目: {', '.join(labels)}")
        if _ctx_parts:
            history_text = (
                "[先前分析上下文]\n" + "\n".join(_ctx_parts) + "\n\n" + history_text
            )

    async def event_generator():
        try:
            # [DIAGNOSTIC] 記錄前端傳入的 file_id, 方便排查快車道失效
            logger.info(
                f"[chat_stream] file_id={request.file_id!r}, "
                f"session_id={request.session_id!r}, "
                f"mode={request.mode!r}, msg={request.message[:50]!r}"
            )
            # 1. 啟動 Workflow 並獲取 handler
            handler = workflow.run(
                query=request.message,
                file_id=request.file_id,
                session_id=request.session_id,
                history=history_text,
                mode=request.mode,
            )

            # 2. 迭代 Workflow 產生的所有事件 (包含 ctx.write_event_to_stream 的事件)
            accumulated_response = []  # 累積 TextChunkEvent 的完整文字
            async for event in handler.stream_events():
                await asyncio.sleep(0)  # Yield control to ensure real-time streaming
                if isinstance(event, MonologueEvent):
                    # 串流思考獨白與工具提示
                    thought_json = json.dumps(
                        {"content": event.monologue}, ensure_ascii=False
                    )
                    yield f"event: thought\ndata: {thought_json}\n\n"

                    tool_json = json.dumps(
                        {"tool": event.tool_name, "params": event.tool_params},
                        ensure_ascii=False,
                    )
                    yield f"event: tool_call\ndata: {tool_json}\n\n"

                elif isinstance(event, ProgressEvent):
                    # 串流進度狀態 (含 Turn 編號)
                    status_json = json.dumps(
                        {"content": event.msg, "turn": event.turn},
                        ensure_ascii=False,
                    )
                    yield f"event: status\ndata: {status_json}\n\n"

                elif isinstance(event, TextChunkEvent):
                    # 串流即時文字片段 (打字機效果)
                    chunk_json = json.dumps(
                        {"content": event.content}, ensure_ascii=False
                    )
                    yield f"event: text_chunk\ndata: {chunk_json}\n\n"
                    accumulated_response.append(event.content)  # 累積完整回應

                elif isinstance(event, ToolResultEvent):
                    # 串流工具執行結果 (可選)
                    result_json = json.dumps(
                        {"tool": event.tool, "result": event.result}, ensure_ascii=False
                    )
                    yield f"event: tool_result\ndata: {result_json}\n\n"

            # 3. 等待最終結果
            result = await handler

            # 兼容性處理：確保傳回給前端的是正確的 JSON 格式
            # 使用遞歸淨化器打破循環引用 (json.dumps 的 default=str 無法處理循環引用)
            def _safe_serialize(obj, seen=None):
                """遞歸淨化: 打破循環引用,將不可序列化物件轉為字串"""
                if seen is None:
                    seen = set()
                obj_id = id(obj)
                if isinstance(obj, dict):
                    if obj_id in seen:
                        return "[circular ref]"
                    seen.add(obj_id)
                    return {k: _safe_serialize(v, seen) for k, v in obj.items()}
                elif isinstance(obj, (list, tuple)):
                    if obj_id in seen:
                        return "[circular ref]"
                    seen.add(obj_id)
                    return [_safe_serialize(v, seen) for v in obj]
                elif isinstance(obj, (str, int, float, bool, type(None))):
                    return obj
                else:
                    # Pydantic models, custom objects, etc.
                    return str(obj)

            if isinstance(result, dict):
                safe_result = _safe_serialize(result)
                final_json = json.dumps(safe_result, ensure_ascii=False, default=str)
            else:
                final_json = json.dumps({"summary": str(result)}, ensure_ascii=False)

            yield f"event: response\ndata: {final_json}\n\n"

            # 保存 AI 回复到历史
            if isinstance(result, dict):
                # 優先使用累積的串流文字（V2 架構的 result["response"] 是佔位符）
                resp_text = (
                    "".join(accumulated_response)
                    if accumulated_response
                    else result.get("response", "")
                )
                knowledge = result.get("final_decision", "")
                _chat_history.save_message(
                    request.session_id,
                    "assistant",
                    resp_text,
                    analysis_knowledge=knowledge if knowledge else None,
                    file_id=request.file_id,
                    conversation_id=request.conversation_id,
                )

                # 持久化結構化分析上下文 (供追問時載入)
                _ctx = result.get("analysis_context")
                if _ctx and isinstance(_ctx, dict):
                    try:
                        _chat_history.save_analysis_context(
                            request.session_id, _ctx, file_id=request.file_id
                        )
                    except Exception as ctx_err:
                        logger.warning(f"Failed to save analysis context: {ctx_err}")

            yield "event: done\ndata: [DONE]\n\n"

        except Exception as e:
            logger.error(f"Stream error in Workflow: {str(e)}", exc_info=True)
            error_json = json.dumps({"detail": str(e)}, ensure_ascii=False)
            yield f"event: error\ndata: {error_json}\n\n"
            # 即使發生錯誤，也嘗試保存已累積的部分回應
            if accumulated_response:
                partial_text = "".join(accumulated_response)
                if partial_text.strip():
                    try:
                        _chat_history.save_message(
                            request.session_id,
                            "assistant",
                            partial_text + "\n\n[分析未完成，發生錯誤]",
                            file_id=request.file_id,
                            conversation_id=request.conversation_id,
                        )
                    except Exception:
                        pass

        except asyncio.CancelledError:
            logger.info("Stream cancelled by client")
            raise

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ========== Vision QA (圖片附件直接走 LLM vision) ==========


async def _vision_qa_generator(request, cfg, chat_history_svc):
    """
    有圖片附件時跳過 V3 pipeline，直接打 vLLM vision API。
    使用和 V3 相同的 SSE event 格式 (text_chunk / response / done)。
    """
    try:
        # 組 multimodal content parts
        content_parts = []
        text_parts = []
        if request.message:
            text_parts.append(request.message)

        for att in request.attachments or []:
            if att.type.startswith("image/"):
                content_parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": att.data},
                    }
                )
            else:
                # 非圖片附件 (csv/txt) — 嘗試解碼文字
                try:
                    import base64

                    header, b64data = att.data.split(",", 1)
                    raw = base64.b64decode(b64data)
                    decoded = raw.decode("utf-8", errors="replace")[:5000]
                    text_parts.append(
                        f"\n--- 附件: {att.name} ---\n{decoded}\n--- 附件結束 ---"
                    )
                except Exception:
                    text_parts.append(f"\n[附件: {att.name} (無法解碼)]")

        # 合併文字 part 放第一個
        combined_text = "\n".join(text_parts) if text_parts else "請描述這張圖片"
        content_parts.insert(0, {"type": "text", "text": combined_text})

        payload = {
            "model": cfg.LLM_MODEL,
            "messages": [{"role": "user", "content": content_parts}],
            "stream": True,
        }

        accumulated = []
        yield f"event: status\ndata: {json.dumps({'content': '🔍 Vision QA 分析中...', 'turn': 0}, ensure_ascii=False)}\n\n"

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", cfg.LLM_API_URL, json=payload) as resp:
                if resp.status_code != 200:
                    body = ""
                    async for chunk in resp.aiter_text():
                        body += chunk
                        if len(body) > 1000:
                            break
                    err = json.dumps(
                        {
                            "detail": f"Vision QA 失敗 ({resp.status_code}): {body[:500]}"
                        },
                        ensure_ascii=False,
                    )
                    yield f"event: error\ndata: {err}\n\n"
                    return

                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        delta = chunk["choices"][0].get("delta", {})
                        text = delta.get("content", "")
                        if text:
                            accumulated.append(text)
                            yield f"event: text_chunk\ndata: {json.dumps({'content': text}, ensure_ascii=False)}\n\n"
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

        # 儲存回覆到歷史
        full_response = "".join(accumulated)
        chat_history_svc.save_message(
            request.session_id,
            "assistant",
            full_response,
            file_id=request.file_id,
            conversation_id=request.conversation_id,
        )

        yield f"event: response\ndata: {json.dumps({'summary': full_response}, ensure_ascii=False)}\n\n"
        yield "event: done\ndata: [DONE]\n\n"

    except Exception as e:
        logger.error(f"[VisionQA] Error: {e}", exc_info=True)
        yield f"event: error\ndata: {json.dumps({'detail': str(e)}, ensure_ascii=False)}\n\n"


# ========== V3 串流端點 ==========


@router.post("/chat/stream/v3")
async def chat_stream_v3(
    request: ChatRequest,
    workflow=Depends(get_analysis_workflow_v3),
):
    """
    [V3] 劇本驅動分析 (SSE 串流模式)
    LLM 只呼叫 2 次: RouteIntent + Humanizer
    如果有圖片附件 → 跳過 V3 pipeline，直接走 Vision QA
    """
    import config as _cfg
    from backend.services.analysis.analysis_types_v3 import V3StartEvent

    history_text = _chat_history.load_history_as_text(
        request.session_id,
        file_id=request.file_id,
        conversation_id=request.conversation_id,
    )
    _chat_history.save_message(
        request.session_id,
        "user",
        request.message,
        file_id=request.file_id,
        conversation_id=request.conversation_id,
    )

    # === Vision QA 分流 ===
    _has_images = request.attachments and any(
        a.type.startswith("image/") for a in request.attachments
    )
    if _has_images:
        return StreamingResponse(
            _vision_qa_generator(request, _cfg, _chat_history),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    async def v3_event_generator():
        try:
            logger.info(
                f"[V3:stream] file_id={request.file_id!r}, "
                f"session_id={request.session_id!r}, "
                f"msg={request.message[:50]!r}"
            )

            # 設定即時 stdout queue (繞過 llama-index event stream)
            stdout_queue = asyncio.Queue()
            workflow.stdout_queue = stdout_queue

            handler = workflow.run(
                query=request.message,
                file_id=request.file_id or "",
                session_id=request.session_id,
                history=history_text,
                mode=request.mode,
                conversation_id=request.conversation_id or "default",
                suspect_params=request.suspect_params,
                target_range=request.target_range,
                baseline_range=request.baseline_range,
                optimization_targets=request.optimization_targets,
            )

            accumulated_response = []

            # === 統一 event queue ===
            # 兩個 producer 都推到同一個 queue，主循環統一消費
            _DONE = object()
            unified_queue = asyncio.Queue()

            async def _produce_workflow_events():
                """讀 llama-index stream_events 推到 unified_queue"""
                try:
                    async for ev in handler.stream_events():
                        await unified_queue.put(("wf", ev))
                finally:
                    await unified_queue.put(("wf_done", _DONE))

            async def _produce_stdout_lines():
                try:
                    while True:
                        item = await stdout_queue.get()
                        if (
                            isinstance(item, tuple)
                            and len(item) == 3
                            and item[0] == "__code_chunk__"
                        ):
                            _, chunk_text, rnd = item
                            await unified_queue.put(("code_chunk", (chunk_text, rnd)))
                        else:
                            await unified_queue.put(("line", item))
                except asyncio.CancelledError:
                    pass

            wf_task = asyncio.create_task(_produce_workflow_events())
            line_task = asyncio.create_task(_produce_stdout_lines())

            wf_finished = False
            while not wf_finished:
                try:
                    tag, payload = await asyncio.wait_for(
                        unified_queue.get(), timeout=0.1
                    )
                except asyncio.TimeoutError:
                    continue

                # --- code chunk (typewriter) ---
                if tag == "code_chunk":
                    chunk_text, rnd = payload
                    out = json.dumps(
                        {"chunk": chunk_text, "round": rnd}, ensure_ascii=False
                    )
                    yield f"event: code_chunk\ndata: {out}\n\n"
                    continue

                # --- stdout line ---
                if tag == "line":
                    line, rnd = payload
                    out = json.dumps(
                        {
                            "stdout": line,
                            "stderr": "",
                            "error": "",
                            "round": rnd,
                            "is_line": True,
                        },
                        ensure_ascii=False,
                    )
                    yield f"event: code_output\ndata: {out}\n\n"
                    continue

                if tag == "wf_done":
                    wf_finished = True
                    continue

                # --- workflow 事件 ---
                event = payload
                if isinstance(event, MonologueEvent):
                    mono_text = event.monologue or ""
                    # Extract MINI_CHART if present
                    if "[MINI_CHART]" in mono_text:
                        chart_marker = "[MINI_CHART]"
                        idx = mono_text.index(chart_marker)
                        chart_json_str = mono_text[idx + len(chart_marker) :]
                        thought_text = mono_text[:idx].strip()
                        # Wrap chart data to prevent type collision
                        try:
                            chart_obj = json.loads(chart_json_str)
                            wrapped = json.dumps(
                                {"type": "mini_chart", "chart": chart_obj},
                                ensure_ascii=False,
                            )
                        except json.JSONDecodeError:
                            wrapped = json.dumps(
                                {"type": "mini_chart", "chart": {}}, ensure_ascii=False
                            )
                        yield f"event: mini_chart\ndata: {wrapped}\n\n"
                        if thought_text:
                            yield f"event: thought\ndata: {json.dumps({'content': thought_text}, ensure_ascii=False)}\n\n"
                    else:
                        yield f"event: thought\ndata: {json.dumps({'content': mono_text}, ensure_ascii=False)}\n\n"
                    yield f"event: tool_call\ndata: {json.dumps({'tool': event.tool_name, 'params': event.tool_params}, ensure_ascii=False, default=str)}\n\n"

                elif isinstance(event, ProgressEvent):
                    if event.msg.startswith("__CHART_MAPPING__"):
                        mapping_json = event.msg[len("__CHART_MAPPING__") :]
                        yield f"event: chart_mapping\ndata: {mapping_json}\n\n"
                    else:
                        yield f"event: status\ndata: {json.dumps({'content': event.msg, 'turn': event.turn}, ensure_ascii=False)}\n\n"

                elif isinstance(event, TextChunkEvent):
                    yield f"event: text_chunk\ndata: {json.dumps({'content': event.content}, ensure_ascii=False)}\n\n"
                    accumulated_response.append(event.content)

                elif isinstance(event, CodeBlockEvent):
                    yield f"event: code_block\ndata: {json.dumps({'code': event.code, 'language': event.language, 'round': event.round_num}, ensure_ascii=False)}\n\n"

                elif isinstance(event, CodeOutputEvent):
                    out = json.dumps(
                        {
                            "stdout": event.stdout,
                            "stderr": event.stderr,
                            "error": event.error,
                            "round": event.round_num,
                            "is_line": event.is_line,
                        },
                        ensure_ascii=False,
                    )
                    yield f"event: code_output\ndata: {out}\n\n"

                elif isinstance(event, ChartImageEvent):
                    yield f"event: chart_image\ndata: {json.dumps({'image_base64': event.image_base64, 'title': event.title, 'width': event.width, 'height': event.height, 'round': event.round_num}, ensure_ascii=False)}\n\n"

                elif (
                    hasattr(event, "task_type")
                    and hasattr(event, "restatement")
                    and type(event).__name__ == "IntentConfirmationEvent"
                ):
                    yield f"event: intent_confirmation\ndata: {json.dumps({'task_type': event.task_type, 'restatement': event.restatement, 'target_params': event.target_params, 'target_range': event.target_range, 'baseline_range': event.baseline_range}, ensure_ascii=False)}\n\n"

            # 清理
            line_task.cancel()
            try:
                await line_task
            except asyncio.CancelledError:
                pass

            # flush 殘餘行
            while not stdout_queue.empty():
                line, rnd = stdout_queue.get_nowait()
                out = json.dumps(
                    {
                        "stdout": line,
                        "stderr": "",
                        "error": "",
                        "round": rnd,
                        "is_line": True,
                    },
                    ensure_ascii=False,
                )
                yield f"event: code_output\ndata: {out}\n\n"

            result = await handler
            if isinstance(result, dict):
                safe_result = _safe_serialize_v3(result)
                final_json = json.dumps(safe_result, ensure_ascii=False, default=str)
            else:
                final_json = json.dumps({"summary": str(result)}, ensure_ascii=False)
            yield f"event: response\ndata: {final_json}\n\n"

            if isinstance(result, dict):
                resp_text = (
                    "".join(accumulated_response)
                    if accumulated_response
                    else result.get("response", "")
                )
                _chat_history.save_message(
                    request.session_id,
                    "assistant",
                    resp_text,
                    file_id=request.file_id,
                    conversation_id=request.conversation_id,
                )

            yield "event: done\ndata: [DONE]\n\n"

        except Exception as e:
            logger.error(f"[V3] Stream error: {str(e)}", exc_info=True)
            error_json = json.dumps({"detail": str(e)}, ensure_ascii=False)
            yield f"event: error\ndata: {error_json}\n\n"

        except asyncio.CancelledError:
            logger.info("[V3] Stream cancelled by client")
            raise

    return StreamingResponse(
        v3_event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _safe_serialize_v3(obj, seen=None):
    """遞歸淨化: 打破循環引用"""
    if seen is None:
        seen = set()
    obj_id = id(obj)
    if isinstance(obj, dict):
        if obj_id in seen:
            return "[circular ref]"
        seen.add(obj_id)
        return {k: _safe_serialize_v3(v, seen) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        if obj_id in seen:
            return "[circular ref]"
        seen.add(obj_id)
        return [_safe_serialize_v3(v, seen) for v in obj]
    elif isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    else:
        return str(obj)


# ========== 檔案與其他輔助端點 ==========


@router.get("/files", response_model=FileListResponse)
async def list_analysis_files(
    session_id: str = Query("default"),
    analysis_service: AnalysisService = Depends(get_intelligent_analysis_service),
):
    def _list_files_sync():
        # 只列出當前 session 的檔案 (每個聊天室完全獨立)
        files = []

        uploads_dir = analysis_service.base_dir / session_id / "uploads"
        if not uploads_dir.exists():
            return FileListResponse(files=[])

        for file_path in uploads_dir.glob("*.csv"):
            filename = file_path.name
            # 跳過對應表檔案
            if "(參數對應表)_" in filename:
                continue
            file_id = analysis_service.get_file_id(filename)
            analysis_path = analysis_service.get_analysis_path(session_id, file_id)
            is_indexed = (analysis_path / "summary.json").exists()

            stats = file_path.stat()
            files.append(
                {
                    "filename": filename,
                    "file_id": file_id,
                    "size": stats.st_size,
                    "uploaded_at": str(stats.st_mtime),
                    "status": "indexed" if is_indexed else "uploaded",
                    "is_indexed": is_indexed,
                }
            )

        return FileListResponse(files=files)

    try:
        return await asyncio.to_thread(_list_files_sync)
    except Exception as e:
        logger.error(f"Error listing files: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary/{file_id}")
async def get_file_summary(
    file_id: str,
    session_id: str = Query("default"),
    analysis_service: AnalysisService = Depends(get_intelligent_analysis_service),
):
    summary = await asyncio.to_thread(
        analysis_service.load_summary, session_id, file_id
    )
    if not summary:
        raise HTTPException(status_code=404, detail="Summary not found")
    return summary


@router.get("/mapping-status", response_model=MappingStatusResponse)
async def get_mapping_status(
    session_id: str = Query("default"),
    file_id: str = Query(""),
    analysis_service: AnalysisService = Depends(get_intelligent_analysis_service),
):
    try:
        mapping_name, status = await asyncio.to_thread(
            analysis_service.get_active_mapping, session_id, file_id or None
        )
        return MappingStatusResponse(active_mapping=mapping_name, status=status)
    except Exception as e:
        logger.error(f"Error getting mapping status: {e}", exc_info=True)
        return MappingStatusResponse(active_mapping=None, status="error: " + str(e))


@router.delete("/mapping")
async def delete_mapping(
    session_id: str = Query("default"),
    file_id: str = Query(""),
    analysis_service: AnalysisService = Depends(get_intelligent_analysis_service),
):
    """刪除當前的術語對應表"""
    try:
        deleted = await asyncio.to_thread(
            analysis_service.delete_mapping, session_id, file_id or None
        )
        return {"status": "ok", "deleted_count": deleted}
    except Exception as e:
        logger.error(f"Error deleting mapping: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    session_id: str = Form("default"),
    is_mapping: str = Form("false"),
    file_id: str = Form(""),
    analysis_service: AnalysisService = Depends(get_intelligent_analysis_service),
):
    """
    上傳檔案 (支援資料檔與術語對應表)
    """
    try:
        if not file.filename or not file.filename.endswith(".csv"):
            raise HTTPException(status_code=400, detail="僅支援 CSV 格式檔案")

        uploads_dir = analysis_service.base_dir / session_id / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)

        # Save uploaded file (mapping files get prefix for hiding from file list)
        if is_mapping.lower() == "true":
            save_filename = f"(參數對應表)_{file.filename}"
            # 清理舊的全域對應表
            for old_f in uploads_dir.iterdir():
                if "(參數對應表)_" in old_f.name:
                    try:
                        old_f.unlink()
                    except Exception:
                        pass
        else:
            save_filename = file.filename

        save_path = uploads_dir / save_filename

        with open(save_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        result = {
            "status": "success",
            "filename": file.filename,
            "path": str(save_path),
        }

        # If this is a mapping file and bound to a specific data file
        if is_mapping.lower() == "true" and file_id:
            analysis_dir = analysis_service.get_analysis_path(session_id, file_id)
            analysis_dir.mkdir(parents=True, exist_ok=True)
            bound_path = analysis_dir / "mapping.csv"
            shutil.copy2(save_path, bound_path)
            result["bound_to"] = file_id
            logger.info(f"Mapping file bound to file_id={file_id}: {bound_path}")

        logger.info(
            f"File uploaded: {file.filename} (session={session_id}, mapping={is_mapping})"
        )
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading file: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ========== 模型管理端點 (Restore) ==========


@router.get("/models")
async def list_models_endpoint(
    session_id: str = Query("default"),
    analysis_service=Depends(get_old_analysis_service),
):
    """
    獲取模型列表 (用於 Model Registry)
    """
    try:
        models = await analysis_service.list_models(session_id)
        return models
    except Exception as e:
        logger.error(f"Error listing models: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/models/{job_id}")
async def delete_model_endpoint(
    job_id: str,
    session_id: str = Query("default"),
    analysis_service=Depends(get_old_analysis_service),
):
    """
    刪除模型
    """
    try:
        result = await analysis_service.delete_model(job_id, session_id)
        return result
    except Exception as e:
        logger.error(f"Error deleting model: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/models/{job_id}/stop")
async def stop_model_endpoint(
    job_id: str,
    session_id: str = Query("default"),
    analysis_service=Depends(get_old_analysis_service),
):
    """
    強制停止模型訓練
    """
    try:
        result = await analysis_service.stop_model(job_id, session_id)
        return result
    except Exception as e:
        logger.error(f"Error stopping model: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models/{job_id}/log")
async def get_model_log(
    job_id: str,
    session_id: str = Query("default"),
    analysis_service=Depends(get_old_analysis_service),
):
    """
    獲取模型訓練日誌
    """
    try:
        log_content = await analysis_service.get_training_log(job_id, session_id)
        return PlainTextResponse(log_content)
    except Exception as e:
        logger.error(f"Error getting log: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== 舊版兼容端點 ==========
# (保留原有的舊版端點以確保相容性)


@router.post("/train")
async def train_model(
    request: TrainRequest,
    session_id: str = Query("default"),
    analysis_service=Depends(get_old_analysis_service),
):
    return await analysis_service.train_model(request, session_id)


@router.post("/quick_analysis")
async def quick_analysis(
    request: QuickAnalysisRequest,
    session_id: str = Query("default"),
    analysis_service=Depends(get_old_analysis_service),
):
    return await analysis_service.quick_analysis(request, session_id)


@router.get("/column_data")
async def get_column_data(
    filename: str,
    column: str,
    session_id: str = Query("default"),
    analysis_service=Depends(get_old_analysis_service),
):
    return await analysis_service.get_column_data(filename, column, session_id)


@router.post("/save_file")
async def save_file_endpoint(
    request: SaveFileRequest,
    session_id: str = Query("default"),
    analysis_service=Depends(get_old_analysis_service),
):
    return await analysis_service.save_filtered_file(request, session_id)


@router.post("/advanced_analysis")
async def advanced_analysis_endpoint(
    request: AdvancedAnalysisRequest,
    session_id: str = Query("default"),
    analysis_service=Depends(get_old_analysis_service),
):
    return await analysis_service.advanced_analysis(request, session_id)


# ========== 資料描述 API ==========


class DataDescriptionRequest(BaseModel):
    file_id: str
    description: str


@router.put("/data_description")
async def set_data_description(request: DataDescriptionRequest):
    """設定資料集場景描述"""
    import json
    from pathlib import Path

    desc_dir = Path("data") / "descriptions"
    desc_dir.mkdir(parents=True, exist_ok=True)
    desc_file = desc_dir / f"{request.file_id}.json"
    desc_file.write_text(
        json.dumps({"description": request.description}, ensure_ascii=False),
        encoding="utf-8",
    )
    return {"status": "success", "file_id": request.file_id}


@router.get("/data_description/{file_id}")
async def get_data_description(file_id: str):
    """讀取資料集場景描述"""
    import json
    from pathlib import Path

    desc_file = Path("data") / "descriptions" / f"{file_id}.json"
    if desc_file.exists():
        data = json.loads(desc_file.read_text(encoding="utf-8"))
        return {"file_id": file_id, "description": data.get("description", "")}
    return {"file_id": file_id, "description": ""}


# ========== 聊天室管理 API ==========


@router.get("/sessions")
async def list_sessions(user_id: str = Query("default")):
    """列出指定用戶的聊天室 (過濾其他用戶的 session)"""
    sessions = _chat_history.list_sessions(user_id=user_id)
    return {"sessions": sessions}


class CreateSessionRequest(BaseModel):
    title: str = "新對話"
    session_id: Optional[str] = None


@router.post("/sessions")
async def create_session(request: CreateSessionRequest):
    """建立新聊天室 (初始化空歷史)"""
    import uuid

    session_id = request.session_id or str(uuid.uuid4())[:12]
    _chat_history.save_message(session_id, "system", f"聊天室已建立: {request.title}")
    return {"status": "success", "session_id": session_id}


@router.get("/sessions/{session_id}/history")
async def get_session_history(
    session_id: str,
    last_n: int = Query(50),
    file_id: str = Query(""),
    conversation_id: str = Query(""),
):
    """取得指定聊天室的對話歷史"""
    messages = _chat_history.load_history(
        session_id,
        max_entries=last_n,
        file_id=file_id,
        conversation_id=conversation_id,
    )
    return {"session_id": session_id, "file_id": file_id, "messages": messages}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, file_id: str = Query("")):
    """刪除聊天室的對話歷史"""
    deleted = _chat_history.delete_history(session_id, file_id=file_id)
    if deleted:
        return {"status": "success", "message": f"聊天室 {session_id} 歷史已刪除"}
    return {"status": "not_found", "message": "未找到該聊天室歷史"}
