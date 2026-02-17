from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse, PlainTextResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import json
import logging
import asyncio

# 使用新的 AnalysisService 與 Workflow
from backend.services.analysis.analysis_service import AnalysisService
from backend.services.analysis.agent import SigmaAnalysisWorkflow
from backend.services.analysis.analysis_types import (
    MonologueEvent,
    ProgressEvent,
    TextChunkEvent,
    ToolResultEvent,
    ErrorEvent,
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


def get_tool_executor(
    analysis_service: AnalysisService = Depends(get_intelligent_analysis_service),
):
    return ToolExecutor(analysis_service)


def get_analysis_workflow(
    analysis_service: AnalysisService = Depends(get_intelligent_analysis_service),
    tool_executor: ToolExecutor = Depends(get_tool_executor),
):
    return SigmaAnalysisWorkflow(tool_executor, analysis_service)


# ========== 請求/響應模型 ==========


class PrepareFileRequest(BaseModel):
    filename: str
    session_id: str = "default"


class PrepareFileResponse(BaseModel):
    status: str
    file_id: str
    summary: Dict[str, Any]
    message: str


class ChatRequest(BaseModel):
    session_id: str = "default"
    file_id: Optional[str] = ""
    message: str
    conversation_id: Optional[str] = "default"
    mode: str = "fast"  # 'fast' or 'full'
    suspect_params: Optional[List[str]] = None
    target_range: Optional[str] = None


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
            request.session_id, request.filename
        )
        if not success:
            raise HTTPException(status_code=400, detail=message)

        return PrepareFileResponse(
            status="success",
            file_id=analysis_service.get_file_id(request.filename),
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
        history_text = _chat_history.load_history_as_text(request.session_id)
        # 保存用户消息
        _chat_history.save_message(request.session_id, "user", request.message)

        result = await workflow.run(
            query=request.message,
            file_id=request.file_id,
            session_id=request.session_id,
            history=history_text,
        )
        # result 是 StopEvent.result，應該是個 dict
        response_text = result.get("response", "")

        # 保存 AI 回复
        _chat_history.save_message(request.session_id, "assistant", response_text)

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
    history_text = _chat_history.load_history_as_text(request.session_id)
    _chat_history.save_message(request.session_id, "user", request.message)

    async def event_generator():
        try:
            # 1. 啟動 Workflow 並獲取 handler
            handler = workflow.run(
                query=request.message,
                file_id=request.file_id,
                session_id=request.session_id,
                history=history_text,
                mode=request.mode,
            )

            # 2. 迭代 Workflow 產生的所有事件 (包含 ctx.write_event_to_stream 的事件)
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
                    # 串流進度狀態
                    status_json = json.dumps({"content": event.msg}, ensure_ascii=False)
                    yield f"event: status\ndata: {status_json}\n\n"

                elif isinstance(event, TextChunkEvent):
                    # 串流即時文字片段 (打字機效果)
                    chunk_json = json.dumps(
                        {"content": event.content}, ensure_ascii=False
                    )
                    yield f"event: text_chunk\ndata: {chunk_json}\n\n"

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
                resp_text = result.get("response", "")
                knowledge = result.get("final_decision", "")
                _chat_history.save_message(
                    request.session_id,
                    "assistant",
                    resp_text,
                    analysis_knowledge=knowledge if knowledge else None,
                )

            yield "event: done\ndata: [DONE]\n\n"

        except Exception as e:
            logger.error(f"Stream error in Workflow: {str(e)}", exc_info=True)
            error_json = json.dumps({"detail": str(e)}, ensure_ascii=False)
            yield f"event: error\ndata: {error_json}\n\n"

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


# ========== 檔案與其他輔助端點 ==========


@router.get("/files", response_model=FileListResponse)
async def list_analysis_files(
    session_id: str = Query("default"),
    analysis_service: AnalysisService = Depends(get_intelligent_analysis_service),
):
    def _list_files_sync():
        uploads_dir = analysis_service.base_dir / session_id / "uploads"
        files_with_status = []
        if uploads_dir.exists():
            for file_path in uploads_dir.glob("*.csv"):
                filename = file_path.name
                file_id = analysis_service.get_file_id(filename)
                analysis_path = analysis_service.get_analysis_path(session_id, file_id)
                is_indexed = (analysis_path / "summary.json").exists()
                stats = file_path.stat()
                files_with_status.append(
                    {
                        "filename": filename,
                        "file_id": file_id,
                        "size": stats.st_size,
                        "uploaded_at": str(stats.st_mtime),
                        "status": "indexed" if is_indexed else "uploaded",
                    }
                )
        return FileListResponse(files=files_with_status)

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
    analysis_service: AnalysisService = Depends(get_intelligent_analysis_service),
):
    try:
        mapping_name, status = await asyncio.to_thread(
            analysis_service.get_active_mapping, session_id
        )
        return MappingStatusResponse(active_mapping=mapping_name, status=status)
    except Exception as e:
        logger.error(f"Error getting mapping status: {e}", exc_info=True)
        return MappingStatusResponse(active_mapping=None, status="error: " + str(e))


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


# ========== 聊天室管理 API ==========


@router.get("/sessions")
async def list_sessions(user_id: str = Query("default")):
    """列出指定用戶的聊天室 (過濾其他用戶的 session)"""
    all_sessions = _chat_history.list_sessions()
    # 只回傳屬於該用戶的 session (session_id == user_id 或以 user_id 開頭)
    filtered = [
        s
        for s in all_sessions
        if s["session_id"] == user_id or s["session_id"].startswith(f"{user_id}_")
    ]
    return {"sessions": filtered}


class CreateSessionRequest(BaseModel):
    title: str = "新對話"
    session_id: Optional[str] = None


@router.post("/sessions")
async def create_session(request: CreateSessionRequest):
    """建立新聊天室 (初始化空歷史)"""
    import uuid

    session_id = request.session_id or str(uuid.uuid4())
    _chat_history.save_message(session_id, "system", f"聊天室已建立: {request.title}")
    return {"status": "success", "session_id": session_id}


@router.get("/sessions/{session_id}/history")
async def get_session_history(session_id: str, last_n: int = Query(50)):
    """取得指定聊天室的對話歷史"""
    messages = _chat_history.load_history(session_id, last_n=last_n)
    return {"session_id": session_id, "messages": messages}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """刪除聊天室的對話歷史"""
    deleted = _chat_history.delete_history(session_id)
    if deleted:
        return {"status": "success", "message": f"聊天室 {session_id} 歷史已刪除"}
    return {"status": "not_found", "message": "未找到該聊天室歷史"}
