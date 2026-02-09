from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import os
import logging
from pathlib import Path

# 使用新的 AnalysisService
from backend.services.analysis.analysis_service import AnalysisService
from backend.services.analysis.agent import LLMAnalysisAgent
from backend.dependencies import (
    get_intelligent_analysis_service,
    get_llm_agent,
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

# ========== 請求/響應模型 ==========


class PrepareFileRequest(BaseModel):
    """準備文件分析的請求"""

    filename: str
    session_id: str = "default"


class PrepareFileResponse(BaseModel):
    """準備文件分析的響應"""

    status: str
    file_id: str
    summary: Dict[str, Any]
    message: str


class ChatRequest(BaseModel):
    """智能對話請求"""

    session_id: str = "default"
    file_id: str
    message: str
    conversation_id: str = "default"


class ChatResponse(BaseModel):
    """智能對話響應"""

    response: str
    tool_used: Optional[str] = None
    tool_params: Optional[Dict] = None
    tool_result: Optional[Any] = None
    all_tool_calls: Optional[List[Dict[str, Any]]] = None
    thoughts: Optional[List[str]] = None


class FileListResponse(BaseModel):
    """文件列表響應"""

    files: List[Dict[str, Any]]


class MappingStatusResponse(BaseModel):
    """對應表狀態響應"""

    active_mapping: Optional[str] = None
    status: str


# ========== API 端點 ==========


@router.post("/prepare", response_model=PrepareFileResponse)
async def prepare_file_for_analysis(
    request: PrepareFileRequest,
    analysis_service: AnalysisService = Depends(get_intelligent_analysis_service),
):
    """
    為CSV文件建立分析索引
    這是一次性操作，後續分析會使用緩存的索引
    時間：根據文件大小，約1-3分鐘
    """
    try:
        # 獲取文件路徑
        # 這裡假設上傳路徑規則與 analysis_service 一致
        csv_path = (
            analysis_service.base_dir
            / request.session_id
            / "uploads"
            / request.filename
        )

        if not csv_path.exists():
            raise HTTPException(404, detail=f"File not found: {request.filename}")

        # 建立索引
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

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, detail=f"Failed to build index: {str(e)}")


@router.post("/stop_generation")
async def stop_generation_endpoint(
    session_id: str = Query("default"),
    analysis_service: AnalysisService = Depends(get_intelligent_analysis_service),
):
    """
    停止當前的 AI 生成過程
    """
    analysis_service.stop_generation(session_id)
    return {"status": "success", "message": "Stop signal sent"}


@router.post("/chat", response_model=ChatResponse)
async def chat_with_ai(
    request: ChatRequest,
    analysis_service: AnalysisService = Depends(get_intelligent_analysis_service),
    llm_agent: LLMAnalysisAgent = Depends(get_llm_agent),
):
    """
    智能對話分析
    用戶用自然語言提問，AI 自動調用工具並回答
    """
    try:
        # 清除之前的停止信號
        analysis_service.clear_stop_signal(request.session_id)

        # 驗證 file_id 有效性
        analysis_path = analysis_service.get_analysis_path(
            request.session_id, request.file_id
        )

        # 檢查 summary.json 是否存在
        if not (analysis_path / "summary.json").exists():
            raise HTTPException(
                400, detail="File analysis not ready. Please call /prepare first."
            )

        # 調用 LLM Agent
        result = await llm_agent.analyze(
            session_id=request.session_id,
            file_id=request.file_id,
            user_question=request.message,
        )

        return ChatResponse(**result)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, detail=f"Analysis failed: {str(e)}")


@router.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    analysis_service: AnalysisService = Depends(get_intelligent_analysis_service),
    llm_agent: LLMAnalysisAgent = Depends(get_llm_agent),
):
    """
    智能對話分析 (SSE串流模式)
    回傳 Server-Sent Events (SSE) 格式的數據流
    """
    try:
        # 清除之前的停止信號
        analysis_service.clear_stop_signal(request.session_id)

        # 驗證 file_id 有效性
        analysis_path = analysis_service.get_analysis_path(
            request.session_id, request.file_id
        )

        if not (analysis_path / "summary.json").exists():
            raise HTTPException(
                400, detail="File analysis not ready. Please call /prepare first."
            )

        async def event_generator():
            async for event_json in llm_agent.stream_analyze(
                session_id=request.session_id,
                file_id=request.file_id,
                user_question=request.message,
                analysis_service=analysis_service,
            ):
                # SSE 格式: data: <content>\n\n
                yield f"data: {event_json}\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, detail=f"Stream analysis failed: {str(e)}")


@router.get("/files", response_model=FileListResponse)
async def list_analysis_files(
    session_id: str = Query("default"),
    analysis_service: AnalysisService = Depends(get_intelligent_analysis_service),
):
    """
    獲取當前用戶可分析的文件列表
    返回已上傳的CSV文件及其分析狀態
    """
    try:
        uploads_dir = analysis_service.base_dir / session_id / "uploads"

        files_with_status = []
        if uploads_dir.exists():
            for file_path in uploads_dir.glob("*.csv"):
                filename = file_path.name
                file_id = analysis_service.get_file_id(filename)
                analysis_path = analysis_service.get_analysis_path(session_id, file_id)

                # 檢查是否已建立索引
                is_indexed = (analysis_path / "summary.json").exists()

                stats = file_path.stat()

                files_with_status.append(
                    {
                        "filename": filename,
                        "file_id": file_id,
                        "size": stats.st_size,
                        "uploaded_at": str(stats.st_mtime),  # 簡單時間戳
                        "is_indexed": is_indexed,
                        "status": "ready" if is_indexed else "not_prepared",
                    }
                )

        return FileListResponse(files=files_with_status)

    except Exception as e:
        raise HTTPException(500, detail=f"Failed to list files: {str(e)}")


@router.get("/summary/{file_id}")
async def get_file_summary(
    file_id: str,
    session_id: str = Query("default"),
    analysis_service: AnalysisService = Depends(get_intelligent_analysis_service),
):
    """獲取文件的分析摘要"""
    try:
        summary = analysis_service.load_summary(session_id, file_id)
        if not summary:
            raise HTTPException(404, detail="Summary not found")
        return summary
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, detail=f"Failed to get summary: {str(e)}")


@router.delete("/clear-session")
async def clear_conversation_session(
    session_id: str = Query("default"),
    conversation_id: str = Query("default"),
    llm_agent: LLMAnalysisAgent = Depends(get_llm_agent),
):
    """
    清除對話歷史
    """
    # 調用 Agent 的清除方法
    if hasattr(llm_agent, "clear_session"):
        await llm_agent.clear_session()

    return {"status": "success", "message": "Session cleared"}


@router.get("/mapping-status", response_model=MappingStatusResponse)
async def get_mapping_status(
    session_id: str = Query("default"),
    analysis_service: AnalysisService = Depends(get_intelligent_analysis_service),
):
    """
    獲取當前會話的對應表狀態
    """
    try:
        mapping_file = analysis_service._get_mapping_file_name(session_id)
        return MappingStatusResponse(
            active_mapping=mapping_file,
            status="success" if mapping_file else "no_mapping",
        )
    except Exception as e:
        logger.error(f"Failed to get mapping status: {str(e)}")
        return MappingStatusResponse(status="error")


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
    from fastapi.responses import PlainTextResponse

    log_content = await analysis_service.get_training_log(job_id, session_id)
    return PlainTextResponse(log_content)


# ========== 恢復舊版關鍵端點 (橋接到 Old AnalysisService) ==========


@router.post("/train")
async def train_model(
    request: TrainRequest,
    session_id: str = Query("default"),
    analysis_service=Depends(get_old_analysis_service),
):
    """啟動模型訓練 (橋接舊服務)"""
    return await analysis_service.train_model(request, session_id)


@router.post("/quick_analysis")
async def quick_analysis(
    request: QuickAnalysisRequest,
    session_id: str = Query("default"),
    analysis_service=Depends(get_old_analysis_service),
):
    """快速數據診斷 (橋接舊服務)"""
    return await analysis_service.quick_analysis(request, session_id)


@router.get("/get_column_data")
async def get_column_data(
    filename: str,
    column: str,
    session_id: str = Query("default"),
    analysis_service=Depends(get_old_analysis_service),
):
    """獲取欄位數據分佈 (橋接舊服務)"""
    return await analysis_service.get_column_data(filename, column, session_id)


@router.post("/save_filtered_file")
async def save_filtered_file(
    request: SaveFileRequest,
    session_id: str = Query("default"),
    analysis_service=Depends(get_old_analysis_service),
):
    """儲存過濾後的檔案 (橋接舊服務)"""
    return await analysis_service.save_filtered_file(request, session_id)


@router.post("/advanced_analysis")
async def advanced_analysis(
    request: AdvancedAnalysisRequest,
    session_id: str = Query("default"),
    analysis_service=Depends(get_old_analysis_service),
):
    """執行進階分析 (橋接舊服務)"""
    return await analysis_service.advanced_analysis(request, session_id)
