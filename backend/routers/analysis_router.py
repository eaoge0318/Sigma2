from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse, PlainTextResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import json
import logging
import asyncio  # Added

# 使用新的 AnalysisService 與 Workflow
from backend.services.analysis.analysis_service import AnalysisService
from backend.services.analysis.agent import SigmaAnalysisWorkflow
from backend.services.analysis.types import (
    MonologueEvent,
    ProgressEvent,
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

router = APIRouter(tags=["Intelligent Analysis"])
logger = logging.getLogger(__name__)

# ========== 依賴注入 ==========


def get_tool_executor(
    analysis_service: AnalysisService = Depends(get_intelligent_analysis_service),
) -> ToolExecutor:
    return ToolExecutor(analysis_service)


def get_analysis_workflow(
    analysis_service: AnalysisService = Depends(get_intelligent_analysis_service),
    tool_executor: ToolExecutor = Depends(get_tool_executor),
) -> SigmaAnalysisWorkflow:
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
    file_id: str
    message: str
    conversation_id: str = "default"


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
    try:
        csv_path = (
            analysis_service.base_dir
            / request.session_id
            / "uploads"
            / request.filename
        )

        if not csv_path.exists():
            raise HTTPException(404, detail=f"File not found: {request.filename}")

        summary = await analysis_service.build_analysis_index(
            csv_path=str(csv_path),
            session_id=request.session_id,
            filename=request.filename,
        )

        return PrepareFileResponse(
            status="success",
            file_id=summary["file_id"],
            summary=summary,
            message=f"Analysis index built for {request.filename}",
        )
    except Exception as e:
        raise HTTPException(500, detail=f"Failed to build index: {str(e)}")


@router.post("/chat", response_model=ChatResponse)
async def chat_with_ai(
    request: ChatRequest,
    workflow: SigmaAnalysisWorkflow = Depends(get_analysis_workflow),
):
    """
    智能對話分析 (同步模式)
    """
    try:
        result = await workflow.run(
            query=request.message,
            file_id=request.file_id,
            session_id=request.session_id,
            history="",  # TODO: 從資料庫加載歷史
        )

        # 解析 workflow 結果
        try:
            res_dict = json.loads(result)
            return ChatResponse(
                response=res_dict.get("summary", ""),
                data=res_dict.get("data"),
                chart=res_dict.get("chart"),
            )
        except:
            return ChatResponse(response=str(result))

    except Exception as e:
        logger.error(f"Chat failed: {e}")
        raise HTTPException(500, detail=str(e))


@router.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    workflow: SigmaAnalysisWorkflow = Depends(get_analysis_workflow),
):
    """
    智能對話分析 (SSE串流模式)
    """

    # 設置 Streaming Handler (LlamaIndex Workflow 原生支援 stream_events)
    # 設置 Streaming Handler
    async def event_generator():
        event_queue = asyncio.Queue()

        # 1. 定義事件處理器，將 MonologueEvent 放入隊列
        async def event_handler(ev):
            await event_queue.put(ev)

        # 2. 綁定 Handler 到 Workflow
        workflow.event_handler = event_handler

        # 3. 在背景任務中執行 Workflow
        async def run_workflow():
            try:
                result = await workflow.run(
                    query=request.message,
                    file_id=request.file_id,
                    session_id=request.session_id,
                    history="",  # TODO: 從資料庫加載歷史
                )
                await event_queue.put({"type": "done", "result": result})
            except Exception as e:
                await event_queue.put({"type": "error", "error": e})

        task = asyncio.create_task(run_workflow())

        # 4. 消費隊列並產生 SSE
        get_task = None
        try:
            while True:
                # 只有當前沒有等待中的 get_task 時才創建新的
                if get_task is None:
                    get_task = asyncio.create_task(event_queue.get())

                # 等待隊列中的新事件 或 Workflow 任務結束
                done, pending = await asyncio.wait(
                    [get_task, task], return_when=asyncio.FIRST_COMPLETED
                )

                if get_task in done:
                    event = get_task.result()
                    get_task = None  # 重置以便下一輪讀取

                    if isinstance(event, dict):
                        if event["type"] == "done":
                            # 最終結果
                            result = event["result"]

                            # 確保 result 是 JSON 格式
                            json_result = ""
                            try:
                                if isinstance(result, str):
                                    json.loads(result)
                                    json_result = result
                                else:
                                    json_result = json.dumps(result, ensure_ascii=False)
                            except json.JSONDecodeError:
                                json_result = json.dumps(
                                    {"summary": str(result)}, ensure_ascii=False
                                )
                            except Exception as e:
                                json_result = json.dumps(
                                    {
                                        "summary": f"Result serialization failed: {str(e)}"
                                    },
                                    ensure_ascii=False,
                                )

                            yield f"data: {json_result}\n\n"
                            yield "event: done\ndata: [DONE]\n\n"
                            break

                        elif event["type"] == "error":
                            error = event["error"]
                            logger.error(f"Stream error in background task: {error}")
                            error_json = json.dumps(
                                {"detail": str(error)}, ensure_ascii=False
                            )
                            yield f"event: error\ndata: {error_json}\n\n"
                            break

                    elif isinstance(event, MonologueEvent):
                        # 串流 Monologue
                        logger.info(
                            f"Streaming monologue event: {event.monologue[:50]}..."
                        )
                        thought_payload = json.dumps(
                            {"content": event.monologue}, ensure_ascii=False
                        )
                        yield f"event: thought\ndata: {thought_payload}\n\n"

                        tool_call_data = json.dumps(
                            {"tool": event.tool_name, "params": event.tool_params},
                            ensure_ascii=False,
                        )
                        yield f"event: tool_call\ndata: {tool_call_data}\n\n"

                    elif isinstance(event, ProgressEvent):
                        logger.info(f"Stream Status: {event.msg}")
                        # 使用 json.dumps 確保特殊字符 (如引號) 被轉義
                        status_json = json.dumps(
                            {"content": event.msg}, ensure_ascii=False
                        )
                        yield f"event: status\ndata: {status_json}\n\n"

                if task in done:
                    # 如果 workflow task 結束但沒有放入 "done" 事件 (異常情況?)
                    if task.exception():
                        ex = task.exception()
                        logger.error(f"Workflow task failed with exception: {ex}")
                        error_json = json.dumps({"detail": str(ex)}, ensure_ascii=False)
                        yield f"event: error\ndata: {error_json}\n\n"
                        break
                    # 如果正常結束，迴圈會繼續直到處理到 "done" 事件 (由 get_task 處理)

        except asyncio.CancelledError:
            logger.info("Stream cancelled by client")
            task.cancel()
            raise

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ========== 檔案與其他輔助端點 ==========


@router.get("/files", response_model=FileListResponse)
async def list_analysis_files(
    session_id: str = Query("default"),
    analysis_service: AnalysisService = Depends(get_intelligent_analysis_service),
):
    try:
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
                        "is_indexed": is_indexed,
                        "status": "ready" if is_indexed else "not_prepared",
                    }
                )
        return FileListResponse(files=files_with_status)
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@router.get("/summary/{file_id}")
async def get_file_summary(
    file_id: str,
    session_id: str = Query("default"),
    analysis_service: AnalysisService = Depends(get_intelligent_analysis_service),
):
    summary = analysis_service.load_summary(session_id, file_id)
    if not summary:
        raise HTTPException(404, detail="Summary not found")
    return summary


@router.get("/mapping-status", response_model=MappingStatusResponse)
async def get_mapping_status(
    session_id: str = Query("default"),
    analysis_service: AnalysisService = Depends(get_intelligent_analysis_service),
):
    mapping_file = analysis_service._get_mapping_file_name(session_id)
    return MappingStatusResponse(
        active_mapping=mapping_file,
        status="success" if mapping_file else "no_mapping",
    )


# ========== 模型管理端點 (Restore) ==========


@router.get("/list_models")
async def list_models_endpoint(
    session_id: str = Query("default"),
    analysis_service=Depends(get_old_analysis_service),
):
    """
    獲取模型列表 (用於 Model Registry)
    """
    return await analysis_service.list_models(session_id)


@router.delete("/delete_model/{job_id}")
async def delete_model_endpoint(
    job_id: str,
    session_id: str = Query("default"),
    analysis_service=Depends(get_old_analysis_service),
):
    """
    刪除模型
    """
    return await analysis_service.delete_model(job_id, session_id)


@router.post("/stop_model/{job_id}")
async def stop_model_endpoint(
    job_id: str,
    session_id: str = Query("default"),
    analysis_service=Depends(get_old_analysis_service),
):
    """
    強制停止模型訓練
    """
    return await analysis_service.stop_model(job_id, session_id)


@router.get("/get_log/{job_id}")
async def get_model_log(
    job_id: str,
    session_id: str = Query("default"),
    analysis_service=Depends(get_old_analysis_service),
):
    """
    獲取模型訓練日誌
    """
    log_content = await analysis_service.get_training_log(job_id, session_id)
    return PlainTextResponse(log_content)


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


@router.get("/get_column_data")
async def get_column_data(
    filename: str,
    column: str,
    session_id: str = Query("default"),
    analysis_service=Depends(get_old_analysis_service),
):
    return await analysis_service.get_column_data(filename, column, session_id)


@router.post("/save_filtered_file")
async def save_filtered_file(
    request: SaveFileRequest,
    session_id: str = Query("default"),
    analysis_service=Depends(get_old_analysis_service),
):
    return await analysis_service.save_filtered_file(request, session_id)


@router.post("/advanced_analysis")
async def advanced_analysis(
    request: AdvancedAnalysisRequest,
    session_id: str = Query("default"),
    analysis_service=Depends(get_old_analysis_service),
):
    return await analysis_service.advanced_analysis(request, session_id)
