"""
欄位別名中間件
當請求帶有 use_alias=1 參數時，自動替換 API 回應中的欄位名稱為別名。
這樣前端不需要在每個顯示點手動轉換，所有回應統一由後端處理。
"""

import os
import re
import json
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

# 不需要別名處理的路徑前綴
_SKIP_PATHS = (
    "/api/files/column-aliases",   # 別名管理本身
    "/api/settings",
    "/api/features",
    "/static/",
    "/workspace/",
    "/favicon",
)

# 讀取別名對照表快取 (session_id -> {map, mtime})
_alias_cache = {}


def _load_alias_map(session_id: str) -> dict:
    """讀取別名對照表，帶簡易檔案修改時間快取"""
    from backend.dependencies import get_file_service
    file_service = get_file_service()
    configs_dir = file_service.get_user_path(session_id, "configs")
    path = os.path.join(configs_dir, "column_aliases.json")

    if not os.path.exists(path):
        _alias_cache.pop(session_id, None)
        return {}

    try:
        mtime = os.path.getmtime(path)
        cached = _alias_cache.get(session_id)
        if cached and cached["mtime"] == mtime:
            return cached["map"]

        with open(path, "r", encoding="utf-8") as f:
            alias_map = json.load(f)

        _alias_cache[session_id] = {"map": alias_map, "mtime": mtime}
        return alias_map
    except Exception:
        return {}


def _build_replacer(mapping: dict):
    """
    建立同時替換器：一次 pass 替換所有匹配的 "key" → "value"
    用 regex 同時匹配所有 key，避免鏈式替換問題。
    """
    if not mapping:
        return None, None

    # 按長度降序排列，避免短 key 先匹配到長 key 的子字串
    sorted_keys = sorted(mapping.keys(), key=len, reverse=True)
    # 建立 regex: 匹配 "key" (JSON 字串值中的欄位名)
    escaped = [re.escape(k) for k in sorted_keys]
    pattern = re.compile(r'"(' + '|'.join(escaped) + r')"')

    def replacer(m):
        key = m.group(1)
        replacement = mapping.get(key)
        return f'"{replacement}"' if replacement else m.group(0)

    return pattern, replacer


class AliasMiddleware(BaseHTTPMiddleware):
    """
    欄位別名中間件：
    - 攔截 JSON 回應，將原始欄位名替換為別名
    - 前端的 fetch wrapper 負責反向替換（別名→原始）請求參數
    """

    async def dispatch(self, request: Request, call_next):
        # 檢查是否需要別名處理
        use_alias = request.query_params.get("use_alias", "0")
        if use_alias != "1":
            return await call_next(request)

        # 跳過不需要處理的路徑
        path = request.url.path
        if any(path.startswith(skip) for skip in _SKIP_PATHS):
            return await call_next(request)

        # 讀取別名表
        session_id = request.query_params.get("session_id", "default")
        alias_map = _load_alias_map(session_id)
        if not alias_map:
            return await call_next(request)

        # 建立替換器
        fwd_pattern, fwd_replacer = _build_replacer(alias_map)
        if not fwd_pattern:
            return await call_next(request)

        # 反向替換請求 body（別名 → 原始）
        if request.method in ("POST", "PUT", "PATCH"):
            reverse_map = {v: k for k, v in alias_map.items()}
            rev_pattern, rev_replacer = _build_replacer(reverse_map)
            if rev_pattern:
                try:
                    body = await request.body()
                    body_str = body.decode("utf-8")
                    modified_body = rev_pattern.sub(rev_replacer, body_str)
                    if modified_body != body_str:
                        # 替換 request 的 _receive 以提供修改後的 body
                        modified_bytes = modified_body.encode("utf-8")

                        async def new_receive():
                            return {
                                "type": "http.request",
                                "body": modified_bytes,
                            }

                        request._receive = new_receive
                except Exception as e:
                    logger.debug(f"Alias reverse-map request body failed: {e}")

        # 執行原始請求
        response = await call_next(request)

        # 只處理 JSON 回應
        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type and "text/json" not in content_type:
            return response

        # 讀取回應 body
        try:
            body_chunks = []
            async for chunk in response.body_iterator:
                if isinstance(chunk, bytes):
                    body_chunks.append(chunk)
                else:
                    body_chunks.append(chunk.encode("utf-8"))
            body_str = b"".join(body_chunks).decode("utf-8")

            # 正向替換（原始 → 別名）
            modified = fwd_pattern.sub(fwd_replacer, body_str)

            # 重建 headers，移除舊的 content-length（Response 會自動計算）
            new_headers = {
                k: v for k, v in response.headers.items()
                if k.lower() != "content-length"
            }

            return Response(
                content=modified,
                status_code=response.status_code,
                headers=new_headers,
                media_type="application/json",
            )
        except Exception as e:
            logger.debug(f"Alias forward-map response body failed: {e}")
            return response
