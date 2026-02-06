"""
AI Router - AI 相關 API
"""

from fastapi import APIRouter, Depends, BackgroundTasks
from backend.models.request_models import ChatRequest
from backend.services.session_service import SessionService
from backend.services.ai_service import AIService
from backend.dependencies import get_session_service, get_ai_service
import uuid
import asyncio
from typing import Dict, Any

router = APIRouter()

# 全局存儲 AI 任務結果（生產環境建議使用 Redis）
ai_jobs: Dict[str, Dict[str, Any]] = {}


def cleanup_old_jobs():
    """清理超過 5 分鐘的舊任務"""
    import time

    current_time = time.time()
    to_delete = [
        job_id
        for job_id, job in ai_jobs.items()
        if current_time - job.get("created_at", 0) > 300
    ]
    for job_id in to_delete:
        del ai_jobs[job_id]


async def process_report_background(
    job_id: str, session_id: str, ai_service: AIService, session_service: SessionService
):
    """後台處理報告生成"""
    import time

    try:
        print(f"[AI Background] processing report job: {job_id}")
        session = session_service.get_dashboard_session(session_id)

        # 顯式檢查數據是否為空
        if not session.prediction_history:
            print("[AI Background] No data found.")
            result = {"report": "目前沒有數據，請先啟動系統以收集數據。"}
        else:
            result = await ai_service.generate_report(session.prediction_history)

        print(f"[AI Background] Report result: {str(result)[:100]}...")
        ai_jobs[job_id] = {
            "status": "completed",
            "result": result,
            "created_at": time.time(),
        }
    except Exception as e:
        print(f"[AI Background] Report Error: {e}")
        ai_jobs[job_id] = {
            "status": "error",
            "error": str(e),
            "created_at": time.time(),
        }


async def process_chat_background(
    job_id: str,
    messages: list,
    session_id: str,
    ai_service: AIService,
    session_service: SessionService,
):
    """後台處理聊天"""
    import time

    try:
        print(f"[AI Background] processing chat job: {job_id}")
        session = session_service.get_dashboard_session(session_id)
        recent_data = (
            session.prediction_history[-50:] if session.prediction_history else []
        )
        result = await ai_service.chat_with_expert(messages, recent_data)
        print(f"[AI Background] Chat result: {str(result)[:100]}...")
        ai_jobs[job_id] = {
            "status": "completed",
            "result": result,
            "created_at": time.time(),
        }
    except Exception as e:
        print(f"[AI Background] Chat Error: {e}")
        ai_jobs[job_id] = {
            "status": "error",
            "error": str(e),
            "created_at": time.time(),
        }


@router.get("/report")
async def get_ai_report(
    session_id: str = "default",
    session_service: SessionService = Depends(get_session_service),
    ai_service: AIService = Depends(get_ai_service),
    background_tasks: BackgroundTasks = None,
):
    """生成 AI 報告（異步，立即返回 job_id）"""
    import time

    cleanup_old_jobs()

    job_id = str(uuid.uuid4())
    ai_jobs[job_id] = {"status": "processing", "created_at": time.time()}

    # 在後台處理
    asyncio.create_task(
        process_report_background(job_id, session_id, ai_service, session_service)
    )

    return {"job_id": job_id, "status": "processing"}


@router.get("/report_status/{job_id}")
async def get_report_status(job_id: str):
    """查詢報告生成狀態"""
    job = ai_jobs.get(job_id)
    if not job:
        return {"status": "not_found"}

    if job["status"] == "completed":
        # 防禦性編碼：確保結果不是 coroutine
        report_res = job["result"].get("report", "")
        if asyncio.iscoroutine(report_res):
            try:
                resolved_res = await report_res
                # 更新緩存，避免重複 await exhausted coroutine
                job["result"]["report"] = resolved_res
                report_res = resolved_res
            except Exception as e:
                error_msg = f"Report generation failed: {str(e)}"
                job["result"]["report"] = error_msg
                report_res = error_msg
        return {"status": "completed", "report": report_res}
    elif job["status"] == "error":
        return {"status": "error", "error": job.get("error", "Unknown error")}
    else:
        return {"status": "processing"}


@router.post("/chat")
async def ai_chat(
    req: ChatRequest,
    session_service: SessionService = Depends(get_session_service),
    ai_service: AIService = Depends(get_ai_service),
):
    """與 AI 專家進行連續對話（異步，立即返回 job_id）"""
    import time

    cleanup_old_jobs()

    job_id = str(uuid.uuid4())
    ai_jobs[job_id] = {"status": "processing", "created_at": time.time()}

    # 在後台處理
    asyncio.create_task(
        process_chat_background(
            job_id, req.messages, req.session_id, ai_service, session_service
        )
    )

    return {"job_id": job_id, "status": "processing"}


@router.get("/chat_status/{job_id}")
async def get_chat_status(job_id: str):
    """查詢聊天狀態"""
    job = ai_jobs.get(job_id)
    if not job:
        return {"status": "not_found"}

    if job["status"] == "completed":
        return {"status": "completed", "reply": job["result"].get("reply", "")}
    elif job["status"] == "error":
        return {"status": "error", "error": job.get("error", "Unknown error")}
    else:
        return {"status": "processing"}
