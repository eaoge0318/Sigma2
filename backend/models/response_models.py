"""
標準 API 回應模型
提供統一的 API 回應格式
"""

from pydantic import BaseModel, Field
from typing import Optional, Any, Dict, List
from datetime import datetime


class APIResponse(BaseModel):
    """標準 API 成功回應"""

    success: bool = Field(default=True, description="請求是否成功")
    data: Optional[Any] = Field(default=None, description="回應數據")
    message: Optional[str] = Field(default=None, description="附加訊息")
    code: str = Field(default="OK", description="狀態碼")
    timestamp: datetime = Field(default_factory=datetime.now, description="回應時間")

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "data": {"result": "example"},
                "message": "操作成功",
                "code": "OK",
                "timestamp": "2026-02-03T17:00:00",
            }
        }


class ErrorResponse(BaseModel):
    """標準 API 錯誤回應"""

    success: bool = Field(default=False, description="請求是否成功")
    error: str = Field(..., description="錯誤訊息")
    code: str = Field(default="ERROR", description="錯誤碼")
    details: Optional[Dict[str, Any]] = Field(default=None, description="詳細錯誤資訊")
    timestamp: datetime = Field(default_factory=datetime.now, description="回應時間")

    class Config:
        json_schema_extra = {
            "example": {
                "success": False,
                "error": "參數驗證失敗",
                "code": "VALIDATION_ERROR",
                "details": {"field": "session_id", "reason": "不可為空"},
                "timestamp": "2026-02-03T17:00:00",
            }
        }


class PaginatedResponse(BaseModel):
    """分頁回應"""

    success: bool = Field(default=True, description="請求是否成功")
    data: List[Any] = Field(default_factory=list, description="數據列表")
    pagination: Dict[str, Any] = Field(default_factory=dict, description="分頁資訊")
    message: Optional[str] = Field(default=None, description="附加訊息")
    timestamp: datetime = Field(default_factory=datetime.now, description="回應時間")

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "data": [{"id": 1}, {"id": 2}],
                "pagination": {
                    "page": 1,
                    "page_size": 10,
                    "total": 100,
                    "total_pages": 10,
                },
                "timestamp": "2026-02-03T17:00:00",
            }
        }


class TaskResponse(BaseModel):
    """異步任務回應"""

    success: bool = Field(default=True, description="任務是否成功提交")
    task_id: str = Field(..., description="任務 ID")
    status: str = Field(default="queued", description="任務狀態")
    message: Optional[str] = Field(default=None, description="附加訊息")
    estimated_time: Optional[int] = Field(
        default=None, description="預估完成時間（秒）"
    )
    timestamp: datetime = Field(default_factory=datetime.now, description="回應時間")

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "task_id": "task_12345",
                "status": "queued",
                "message": "訓練任務已提交",
                "estimated_time": 300,
                "timestamp": "2026-02-03T17:00:00",
            }
        }


class TaskStatusResponse(BaseModel):
    """任務狀態回應"""

    success: bool = Field(default=True, description="查詢是否成功")
    task_id: str = Field(..., description="任務 ID")
    status: str = Field(..., description="任務狀態 (queued/running/completed/failed)")
    progress: Optional[float] = Field(default=None, description="進度 (0-100)")
    result: Optional[Any] = Field(default=None, description="結果（任務完成時）")
    error: Optional[str] = Field(default=None, description="錯誤訊息（任務失敗時）")
    started_at: Optional[datetime] = Field(default=None, description="開始時間")
    completed_at: Optional[datetime] = Field(default=None, description="完成時間")
    timestamp: datetime = Field(default_factory=datetime.now, description="查詢時間")

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "task_id": "task_12345",
                "status": "running",
                "progress": 45.5,
                "started_at": "2026-02-03T17:00:00",
                "timestamp": "2026-02-03T17:05:00",
            }
        }


def create_success_response(
    data: Any = None, message: str = None, code: str = "OK"
) -> APIResponse:
    """
    建立成功回應的便捷函數

    Args:
        data: 回應數據
        message: 附加訊息
        code: 狀態碼

    Returns:
        APIResponse 物件
    """
    return APIResponse(success=True, data=data, message=message, code=code)


def create_error_response(
    error: str, code: str = "ERROR", details: Dict[str, Any] = None
) -> ErrorResponse:
    """
    建立錯誤回應的便捷函數

    Args:
        error: 錯誤訊息
        code: 錯誤碼
        details: 詳細錯誤資訊

    Returns:
        ErrorResponse 物件
    """
    return ErrorResponse(success=False, error=error, code=code, details=details)


def create_paginated_response(
    data: List[Any], page: int, page_size: int, total: int, message: str = None
) -> PaginatedResponse:
    """
    建立分頁回應的便捷函數

    Args:
        data: 數據列表
        page: 當前頁碼
        page_size: 每頁大小
        total: 總數量
        message: 附加訊息

    Returns:
        PaginatedResponse 物件
    """
    total_pages = (total + page_size - 1) // page_size

    return PaginatedResponse(
        success=True,
        data=data,
        pagination={
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        },
        message=message,
    )


def create_task_response(
    task_id: str,
    status: str = "queued",
    message: str = None,
    estimated_time: int = None,
) -> TaskResponse:
    """
    建立任務回應的便捷函數

    Args:
        task_id: 任務 ID
        status: 任務狀態
        message: 附加訊息
        estimated_time: 預估完成時間

    Returns:
        TaskResponse 物件
    """
    return TaskResponse(
        success=True,
        task_id=task_id,
        status=status,
        message=message,
        estimated_time=estimated_time,
    )
