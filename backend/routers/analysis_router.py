"""
Analysis Router - 數據分析相關 API
"""

from fastapi import APIRouter, Depends, Query
from backend.models.request_models import (
    AdvancedAnalysisRequest,
    SaveFileRequest,
    TrainRequest,
    QuickAnalysisRequest,
)
from backend.services.analysis_service import AnalysisService
from backend.dependencies import get_analysis_service

router = APIRouter()


@router.post("/advanced")
async def advanced_analysis(
    req: AdvancedAnalysisRequest,
    session_id: str = Query("default"),
    analysis_service: AnalysisService = Depends(get_analysis_service),
):
    """執行進階分析：針對特定目標欄位挑選重要參數"""
    return await analysis_service.advanced_analysis(req, session_id)


@router.post("/save_filtered")
async def save_filtered_file(
    req: SaveFileRequest,
    session_id: str = Query("default"),
    analysis_service: AnalysisService = Depends(get_analysis_service),
):
    """將過濾後的數據儲存為新檔案"""
    return await analysis_service.save_filtered_file(req, session_id)


@router.post("/train")
async def train_model(
    req: TrainRequest,
    session_id: str = Query("default"),
    analysis_service: AnalysisService = Depends(get_analysis_service),
):
    """觸發模型訓練（Mock）"""
    return await analysis_service.train_model(req, session_id)


@router.post("/quick_analysis")
async def quick_analysis(
    req: QuickAnalysisRequest,
    session_id: str = Query("default"),
    analysis_service: AnalysisService = Depends(get_analysis_service),
):
    """執行空值分析：根據全量數據分析數據完整度與缺失情況"""
    return await analysis_service.quick_analysis(req, session_id)


@router.get("/get_column_data")
async def get_column_data(
    filename: str,
    column: str,
    session_id: str = Query("default"),
    analysis_service: AnalysisService = Depends(get_analysis_service),
):
    """獲取特定欄位的數據分佈"""
    return await analysis_service.get_column_data(filename, column, session_id)


@router.get("/list_models")
async def list_models(
    session_id: str = Query("default"),
    analysis_service: AnalysisService = Depends(get_analysis_service),
):
    """獲取目前所有的模型及其訓練狀態列表"""
    return await analysis_service.list_models(session_id)


@router.get("/get_log/{job_id}")
async def get_training_log(
    job_id: str,
    session_id: str = Query("default"),
    analysis_service: AnalysisService = Depends(get_analysis_service),
):
    """獲取特定訓練任務的日誌內容"""
    return await analysis_service.get_training_log(job_id, session_id)


@router.delete("/delete_model/{job_id}")
async def delete_model(
    job_id: str,
    session_id: str = Query("default"),
    analysis_service: AnalysisService = Depends(get_analysis_service),
):
    """刪除特定模型任務"""
    return await analysis_service.delete_model(job_id, session_id)


@router.post("/stop_model/{job_id}")
async def stop_model(
    job_id: str,
    session_id: str = Query("default"),
    analysis_service: AnalysisService = Depends(get_analysis_service),
):
    """停止運行中的訓練任務"""
    return await analysis_service.stop_model(job_id, session_id)
