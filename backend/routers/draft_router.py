from fastapi import APIRouter, Depends, Body
from typing import Dict, Any
from backend.services.draft_service import DraftService
from backend.dependencies import get_draft_service

router = APIRouter()


@router.post("/save")
async def save_draft(
    draft: Dict[str, Any] = Body(...),
    session_id: str = "default",
    draft_service: DraftService = Depends(get_draft_service),
):
    """將建模配置儲存為 JSON 暫存檔"""
    return await draft_service.save_draft(draft, session_id)


@router.get("/list")
async def list_drafts(
    session_id: str = "default",
    draft_service: DraftService = Depends(get_draft_service),
):
    """取得伺服器端的所有暫存檔列表"""
    return await draft_service.list_drafts(session_id)


@router.delete("/delete/{draft_id}")
async def delete_draft(
    draft_id: str,
    session_id: str = "default",
    draft_service: DraftService = Depends(get_draft_service),
):
    """刪除指定的暫存檔"""
    return await draft_service.delete_draft(draft_id, session_id)
