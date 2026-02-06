"""
靜默路由中間件
過濾掉輪詢等高頻請求的日誌輸出，保持控制台清爽
"""

import logging
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


class QuietRoutesMiddleware(BaseHTTPMiddleware):
    """
    過濾特定路由的訪問日誌，避免輪詢請求淹沒控制台
    """

    def __init__(self, app: ASGIApp, quiet_routes: list = None):
        super().__init__(app)
        # 預設靜默的路由（通常是輪詢請求）
        self.quiet_routes = quiet_routes or [
            "/api/history",
            "/api/dashboard/history",
        ]

    async def dispatch(self, request: Request, call_next):
        # 檢查是否為靜默路由
        should_be_quiet = any(
            request.url.path.startswith(route) for route in self.quiet_routes
        )

        # 如果是靜默路由，暫時提高 uvicorn 的日誌級別
        if should_be_quiet:
            uvicorn_logger = logging.getLogger("uvicorn.access")
            original_level = uvicorn_logger.level
            uvicorn_logger.setLevel(logging.WARNING)  # 只記錄警告和錯誤

        # 執行請求
        response = await call_next(request)

        # 恢復原始日誌級別
        if should_be_quiet:
            uvicorn_logger.setLevel(original_level)

        return response


def add_quiet_routes_middleware(app, quiet_routes: list = None):
    """
    便捷函數：將靜默路由中間件添加到 FastAPI app

    Args:
        app: FastAPI 應用實例
        quiet_routes: 需要靜默的路由清單

    Example:
        add_quiet_routes_middleware(app, ["/api/history", "/health"])
    """
    app.add_middleware(QuietRoutesMiddleware, quiet_routes=quiet_routes)
