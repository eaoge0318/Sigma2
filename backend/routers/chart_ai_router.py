"""
Chart AI Router - 圖表 AI 助手相關 API
專為數據圖表視圖設計的 AI 助手
"""

from fastapi import APIRouter, Depends
from backend.models.request_models import ChartAIReportRequest, ChartAIChatRequest
from backend.services.session_service import SessionService
from backend.services.chart_ai_service import ChartAIService
from backend.dependencies import get_session_service, get_chart_ai_service

router = APIRouter()


@router.post("/report")
async def get_chart_ai_report(
    request: ChartAIReportRequest,
    session_service: SessionService = Depends(get_session_service),
    chart_ai_service: ChartAIService = Depends(get_chart_ai_service),
):
    """
    生成基於圖表分析數據的 AI 報告

    Args:
        request: 包含 session_id 和 days 參數
        session_service: Session 管理服務
        chart_ai_service: 圖表 AI 服務

    Returns:
        AI 分析報告
    """
    session = session_service.get_analysis_session(request.session_id)
    return await chart_ai_service.generate_chart_report(
        session.chart_analysis_history, request.days
    )


@router.post("/chat")
async def chart_ai_chat(
    request: ChartAIChatRequest,
    session_service: SessionService = Depends(get_session_service),
    chart_ai_service: ChartAIService = Depends(get_chart_ai_service),
):
    """
    與圖表 AI 專家進行對話

    Args:
        request: 包含 messages, session_id 和 days
        session_service: Session 管理服務
        chart_ai_service: 圖表 AI 服務

    Returns:
        AI 回覆
    """
    session = session_service.get_analysis_session(request.session_id)
    return await chart_ai_service.chat_with_chart_expert(
        request.messages, session.chart_analysis_history, request.days
    )


@router.post("/update_data")
async def update_chart_data(
    request: dict,
    session_service: SessionService = Depends(get_session_service),
):
    """
    更新圖表分析數據（已停用存儲功能）
    """
    session = session_service.get_analysis_session(request.get("session_id", "default"))

    # 清空可能存在的舊記錄並停止新增
    session.chart_analysis_history = []

    return {"status": "success", "message": "Chart history tracking is disabled."}
