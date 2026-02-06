"""
File Router - 檔案管理相關 API
"""

from fastapi import APIRouter, Depends, File, UploadFile, Form, Query
from backend.services.file_service import FileService
from backend.dependencies import get_file_service

router = APIRouter()


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    session_id: str = Form("default"),
    file_service: FileService = Depends(get_file_service),
):
    """上傳檔案"""
    return await file_service.upload_file(file, session_id)


@router.get("/list")
async def list_files(
    session_id: str = Query("default"),
    file_service: FileService = Depends(get_file_service),
):
    """列出已上傳的檔案"""
    return await file_service.list_files(session_id)


@router.delete("/delete/{filename}")
async def delete_file(
    filename: str,
    session_id: str = Query("default"),
    file_service: FileService = Depends(get_file_service),
):
    """刪除指定檔案"""
    return await file_service.delete_file(filename, session_id)


@router.get("/view/{filename}")
async def view_file(
    filename: str,
    page: int = 1,
    page_size: int = 50,
    session_id: str = Query("default"),
    file_service: FileService = Depends(get_file_service),
):
    """預覽檔案內容（分頁）"""
    return await file_service.view_file(filename, page, page_size, session_id)


@router.post("/clear_workspace")
async def clear_workspace(
    session_id: str = Query("default"),
    file_service: FileService = Depends(get_file_service),
):
    """清理 folos 使用者的工作空間 (刪除所有資料夾)"""
    return await file_service.clear_user_workspace(session_id)
