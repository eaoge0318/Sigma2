"""
統一異常處理中間件
捕獲並處理應用程式中的所有異常
"""

from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from backend.utils.exceptions import Sigma2Exception
from backend.utils.logger import get_logger
from backend.models.response_models import create_error_response
import traceback
import sys

logger = get_logger(__name__)


async def sigma2_exception_handler(request: Request, exc: Sigma2Exception):
    """
    處理自定義的 Sigma2Exception

    Args:
        request: 請求物件
        exc: 異常實例

    Returns:
        JSON 錯誤回應
    """
    logger.warning(
        f"Sigma2Exception - {exc.code}: {exc.message}",
        extra={
            "path": request.url.path,
            "method": request.method,
            "details": exc.details,
        },
    )

    error_response = create_error_response(
        error=exc.message, code=exc.code, details=exc.details
    )

    return JSONResponse(
        status_code=exc.status_code, content=error_response.model_dump()
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    處理 Pydantic 驗證錯誤

    Args:
        request: 請求物件
        exc: 驗證異常

    Returns:
        JSON 錯誤回應
    """
    errors = []
    for error in exc.errors():
        field = " -> ".join(str(loc) for loc in error["loc"])
        message = error["msg"]
        errors.append(f"{field}: {message}")

    error_message = "請求參數驗證失敗: " + "; ".join(errors)

    logger.warning(
        f"Validation Error: {error_message}",
        extra={
            "path": request.url.path,
            "method": request.method,
            "errors": exc.errors(),
        },
    )

    error_response = create_error_response(
        error=error_message,
        code="VALIDATION_ERROR",
        details={"validation_errors": exc.errors()},
    )

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=error_response.model_dump(),
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """
    處理 HTTP 異常

    Args:
        request: 請求物件
        exc: HTTP 異常

    Returns:
        JSON 錯誤回應
    """
    logger.warning(
        f"HTTP Exception - {exc.status_code}: {exc.detail}",
        extra={"path": request.url.path, "method": request.method},
    )

    error_response = create_error_response(
        error=str(exc.detail), code=f"HTTP_{exc.status_code}"
    )

    return JSONResponse(
        status_code=exc.status_code, content=error_response.model_dump()
    )


async def general_exception_handler(request: Request, exc: Exception):
    """
    處理未預期的一般異常

    Args:
        request: 請求物件
        exc: 異常實例

    Returns:
        JSON 錯誤回應
    """
    # 取得完整的堆疊追蹤
    exc_type, exc_value, exc_traceback = sys.exc_info()
    tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))

    logger.error(
        f"Unhandled Exception: {str(exc)}",
        extra={
            "path": request.url.path,
            "method": request.method,
            "exception_type": type(exc).__name__,
            "traceback": tb_str,
        },
    )

    # 在生產環境中不顯示詳細堆疊追蹤
    import os

    is_debug = os.getenv("DEBUG", "false").lower() == "true"

    details = None
    if is_debug:
        details = {
            "exception_type": type(exc).__name__,
            "traceback": tb_str.split("\n"),
        }

    error_response = create_error_response(
        error="內部伺服器錯誤，請稍後再試",
        code="INTERNAL_SERVER_ERROR",
        details=details,
    )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_response.model_dump(),
    )


def register_exception_handlers(app):
    """
    註冊所有異常處理器到 FastAPI 應用

    Args:
        app: FastAPI 應用實例
    """
    app.add_exception_handler(Sigma2Exception, sigma2_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, general_exception_handler)

    logger.info("已註冊所有異常處理器")
