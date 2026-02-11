"""
Sigma2 Agentic Reasoning API - 主入口
重構後的版本：使用模組化架構，各功能完全隔離
"""

import os
import uvicorn
import sys
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

import config

# 配置日志输出
import logging

logging.basicConfig(
    level=logging.INFO,  # 改為 INFO 級別，減少日誌輸出
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)  # 输出到控制台
    ],
)

# 获取 logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# 设置其他关键模块的日志级别（只顯示重要訊息）
logging.getLogger("agent_logic").setLevel(logging.WARNING)
logging.getLogger("backend.services.prediction_service").setLevel(logging.WARNING)
logging.getLogger("backend.routers.dashboard_router").setLevel(logging.WARNING)

# 關閉第三方庫的冗長日誌
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

logger.info("=" * 60)
logger.info("Starting Sigma2 API Server")
logger.info("=" * 60)

# 匯入各個 Router
from backend.routers import (
    dashboard_router,
    file_router,
    analysis_router,
    ai_router,
    chart_ai_router,
    draft_router,
)


from contextlib import asynccontextmanager

# --- Log Filter (過濾輪詢請求日誌) ---
from backend.utils.log_filters import add_log_filter


@asynccontextmanager
async def lifespan(app: FastAPI):
    """應用生命週期管理 (Startup & Shutdown)"""
    # --- Startup ---
    # 過濾 uvicorn.access 中的特定路徑
    add_log_filter("uvicorn.access", "/api/history")
    add_log_filter("uvicorn.access", "/api/dashboard/history")
    add_log_filter("uvicorn.access", "/health")

    # 顯示啟動訊息
    print("=" * 60)
    print("Sigma2 Agentic Reasoning API v2.0 啟動成功")
    print("=" * 60)
    print("已載入模組：")
    print("  Dashboard Router (即時看板)")
    print("  File Router (檔案管理)")
    print("  Analysis Router (數據分析)")
    print("  AI Router (智能助手)")
    print("=" * 60)
    print(f"API 文件：http://localhost:{config.API_PORT}/docs")
    print(f"Dashboard：http://localhost:{config.API_PORT}/dashboard")
    print("=" * 60)

    yield

    # --- Shutdown ---
    print("正在關閉 Sigma2 API Server...")
    # 在此處可以添加釋放資源的邏輯 (例如關閉 DB 連線、停止背景任務)
    print("Sigma2 API Server 已關閉。")


# --- 初始化 FastAPI App ---
app = FastAPI(
    title="Sigma2 Agentic Reasoning API",
    description="模組化架構的 AI 輔助系統",
    version="2.0.0",
    lifespan=lifespan,
)


# --- 靜態檔案服務（No Cache）---
class NoCacheStaticFiles(StaticFiles):
    """強制不快取的靜態檔案服務"""

    def is_not_modified(self, response_headers, request_headers) -> bool:
        return False  # Always reload

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp


app.mount("/static", NoCacheStaticFiles(directory="static"), name="static")


# --- 註冊各功能模組的 Router ---
# 每個模組完全獨立，修改一個不會影響其他模組
app.include_router(
    dashboard_router.router,
    prefix="/api/dashboard",
    tags=["Dashboard - 即時看板"],
)

app.include_router(
    file_router.router,
    prefix="/api/files",
    tags=["Files - 檔案管理"],
)

app.include_router(
    analysis_router.router,
    prefix="/api/analysis",
    tags=["Analysis - 數據分析"],
)

app.include_router(
    ai_router.router,
    prefix="/api/ai",
    tags=["AI - 智能助手"],
)

app.include_router(
    chart_ai_router.router,
    prefix="/api/chart_ai",
    tags=["Chart AI - 圖表AI助手"],
)

app.include_router(
    draft_router.router,
    prefix="/api/draft",
    tags=["Draft - 建模暫存"],
)


# --- 向後相容的 API 路由 ---
# 為了不破壞現有前端，保留舊的 API 路徑，轉發到新的 router
@app.post("/predict")
async def predict_legacy(request: dict):
    """向後相容：轉發到新的 dashboard router"""
    from backend.routers.dashboard_router import predict
    from backend.models.request_models import InferenceRequest
    from backend.dependencies import get_session_service, get_prediction_service

    req = InferenceRequest(**request)
    return await predict(req, get_session_service(), get_prediction_service())


@app.get("/api/history")
async def get_history_legacy(session_id: str = "default"):
    """向後相容"""
    from backend.routers.dashboard_router import get_history
    from backend.dependencies import get_session_service

    return await get_history(session_id, get_session_service())


@app.post("/api/clear")
async def clear_history_legacy(body: dict):
    """向後相容"""
    from backend.routers.dashboard_router import clear_history
    from backend.dependencies import get_session_service

    session_id = body.get("session_id", "default")
    return await clear_history(session_id, get_session_service())


@app.post("/api/simulator/next")
async def simulator_next_legacy(body: dict):
    """向後相容"""
    from backend.routers.dashboard_router import simulator_next
    from backend.dependencies import get_session_service, get_prediction_service

    session_id = body.get("session_id", "default")
    return await simulator_next(
        session_id, get_session_service(), get_prediction_service()
    )


@app.post("/api/simulator/load_file")
async def simulator_load_file_legacy(request: dict):
    """向後相容：載入模擬檔案"""
    from backend.routers.dashboard_router import load_simulation_file
    from backend.dependencies import get_file_service, get_session_service

    filename = request.get("filename")
    session_id = request.get("session_id", "default")

    return await load_simulation_file(
        filename=filename,
        session_id=session_id,
        file_service=get_file_service(),
        session_service=get_session_service(),
    )


@app.post("/api/model/load")
async def model_load_legacy(request: dict):
    """向後相容:載入模型"""
    from backend.routers.dashboard_router import load_specific_model
    from backend.dependencies import (
        get_prediction_service,
        get_session_service,
        get_file_service,
    )

    model_path = request.get("model_path")
    session_id = request.get("session_id", "default")

    return await load_specific_model(
        model_path=model_path,
        session_id=session_id,
        prediction_service=get_prediction_service(),
        session_service=get_session_service(),
        file_service=get_file_service(),
    )


@app.get("/api/simulator/models")
async def list_models_legacy(session_id: str = "default"):
    """向後相容：列出模型"""
    from backend.routers.dashboard_router import list_available_models
    from backend.dependencies import get_file_service

    return await list_available_models(session_id, get_file_service())


@app.post("/api/upload_file")
async def upload_file_legacy(
    file: UploadFile = File(...),
    session_id: str = Form("default"),
):
    """向後相容"""
    from backend.dependencies import get_file_service

    file_service = get_file_service()
    return await file_service.upload_file(file, session_id)


# --- AI 助手向後相容路由 ---
@app.get("/api/ai_report")
async def ai_report_legacy(session_id: str = "default"):
    """向後相容：AI 報告生成"""
    from backend.routers.ai_router import get_ai_report
    from backend.dependencies import get_session_service, get_ai_service

    return await get_ai_report(session_id, get_session_service(), get_ai_service())


@app.get("/api/ai_report_status/{job_id}")
async def ai_report_status_legacy(job_id: str):
    """向後相容：AI 報告狀態查詢"""
    from backend.routers.ai_router import get_report_status

    return await get_report_status(job_id)


@app.post("/api/ai_chat")
async def ai_chat_legacy(request: dict):
    """向後相容：AI 聊天"""
    from backend.routers.ai_router import ai_chat
    from backend.models.request_models import ChatRequest
    from backend.dependencies import get_session_service, get_ai_service

    req = ChatRequest(**request)
    return await ai_chat(req, get_session_service(), get_ai_service())


@app.get("/api/ai_chat_status/{job_id}")
async def ai_chat_status_legacy(job_id: str):
    """向後相容：AI 聊天狀態查詢"""
    from backend.routers.ai_router import get_chat_status

    return await get_chat_status(job_id)


@app.get("/api/list_files")
async def list_files_legacy(session_id: str = "default"):
    """向後相容"""
    from backend.dependencies import get_file_service

    return await get_file_service().list_files(session_id)


@app.delete("/api/delete_file/{filename}")
async def delete_file_legacy(filename: str, session_id: str = "default"):
    """向後相容"""
    from backend.dependencies import get_file_service

    return await get_file_service().delete_file(filename, session_id)


@app.get("/api/view_file/{filename}")
async def view_file_legacy(
    filename: str, page: int = 1, page_size: int = 50, session_id: str = "default"
):
    """向後相容"""
    from backend.dependencies import get_file_service

    return await get_file_service().view_file(filename, page, page_size, session_id)


@app.post("/api/save_filtered_file")
async def save_filtered_file_legacy(request: dict, session_id: str = "default"):
    """向後相容"""
    from backend.routers.analysis_router import save_filtered_file
    from backend.models.request_models import SaveFileRequest
    from backend.dependencies import get_analysis_service

    req = SaveFileRequest(**request)
    # Direct service call
    return await get_analysis_service().save_filtered_file(req, session_id)


@app.post("/api/advanced_analysis")
async def advanced_analysis_legacy(request: dict, session_id: str = "default"):
    """向後相容"""
    from backend.models.request_models import AdvancedAnalysisRequest
    from backend.dependencies import get_analysis_service

    req = AdvancedAnalysisRequest(**request)
    return await get_analysis_service().advanced_analysis(req, session_id)


@app.post("/api/train_model")
async def train_model_legacy(request: dict, session_id: str = "default"):
    """向後相容"""
    from backend.models.request_models import TrainRequest
    from backend.dependencies import get_analysis_service

    req = TrainRequest(**request)
    return await get_analysis_service().train_model(req, session_id)


@app.post("/api/quick_analysis")
async def quick_analysis_legacy(request: dict, session_id: str = "default"):
    """向後相容"""
    from backend.models.request_models import QuickAnalysisRequest
    from backend.dependencies import get_analysis_service

    req = QuickAnalysisRequest(**request)
    return await get_analysis_service().quick_analysis(req, session_id)


@app.get("/api/get_column_data")
async def get_column_data_legacy(
    filename: str, column: str, session_id: str = "default"
):
    """向後相容：獲取欄位數據"""
    from backend.dependencies import get_analysis_service

    return await get_analysis_service().get_column_data(filename, column, session_id)


# --- Dashboard 頁面 ---
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """提供主頁面"""
    # file_path = os.path.abspath("dashboard.html")  # Removed unused variable
    with open("dashboard.html", "r", encoding="utf-8") as f:
        content = f.read()
    response = HTMLResponse(content=content)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/test_simulator.html", response_class=HTMLResponse)
async def test_simulator():
    """提供測試頁面"""
    with open("test_simulator.html", "r", encoding="utf-8") as f:
        content = f.read()
    response = HTMLResponse(content=content)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


if __name__ == "__main__":
    import sys

    print(f"Server starting in: {os.getcwd()}")

    # 檢查是否帶有 --reload 參數
    use_reload = "--reload" in sys.argv
    use_reload = True
    if use_reload:
        print("[Development Mode] Auto-reload enabled. Monitoring file changes...")
        # 必須使用字串 "api_entry:app" 才能在 uvicorn 中啟用 reload
        uvicorn.run(
            "api_entry:app",
            host="0.0.0.0",
            port=config.API_PORT,
            reload=True,
            log_level="debug",
        )
    else:
        # 生產/標準模式：直接運行 app 物件
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=config.API_PORT,
            workers=1,
            log_level="debug",
        )
