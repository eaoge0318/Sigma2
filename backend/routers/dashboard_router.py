"""
Dashboard Router - 即時看板相關 API
"""

import time
import os
import pandas as pd
from fastapi import APIRouter, HTTPException, Depends, Body

import config
from core_logic import DataPreprocess
from backend.models.request_models import InferenceRequest
from backend.services.session_service import SessionService
from backend.services.prediction_service import PredictionService
from backend.services.file_service import FileService
from backend.dependencies import (
    get_session_service,
    get_prediction_service,
    get_file_service,
)
from backend.utils import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.post("/predict")
async def predict(
    request: InferenceRequest,
    session_service: SessionService = Depends(get_session_service),
    prediction_service: PredictionService = Depends(get_prediction_service),
):
    """執行 IQL 預測並返回建議"""
    if not prediction_service.is_ready(request.session_id):
        raise HTTPException(500, "Agent not initialized. Ensure models are trained.")

    try:
        print(f"[DEBUG] predict() called")
        print(f"[DEBUG] Session ID: {request.session_id}")
        print(f"[DEBUG] Measure value: {request.measure_value}")

        session = session_service.get_dashboard_session(request.session_id)
        row = request.data

        # 自動刪除 NaN 值
        row = {k: v for k, v in row.items() if v is not None and v == v}

        # 取得或推測目標值
        y_val = request.measure_value
        try:
            y = float(y_val) if y_val is not None else 0.0
            print(f"[DEBUG] Target Y value: {y}")
        except (ValueError, TypeError):
            logger.warning(f"無法將目標值轉為浮點數: {y_val}，使用預設值 0.0")
            y = 0.0

        # 執行預測
        print(f"[DEBUG] Calling prediction_service.predict()...")
        result = await prediction_service.predict(row, y, request.session_id)
        print(f"[DEBUG] prediction_service.predict() returned")
        print(f"[DEBUG] Result keys: {list(result.keys())}")

        # 加入時間戳
        result["timestamp"] = time.time()

        # 寫入 Session 專屬歷史
        session.prediction_history.append(result)
        if len(session.prediction_history) > 5000:
            session.prediction_history.pop(0)

        print(f"[DEBUG] predict() completed successfully")
        return result

    except Exception as e:
        print(f"[ERROR] Exception in predict():")
        print(f"[ERROR] Type: {type(e).__name__}")
        print(f"[ERROR] Message: {str(e)}")
        import traceback

        traceback.print_exc()
        logger.error("預測執行失敗", exc_info=True)
        raise HTTPException(500, detail=str(e))


@router.get("/history")
async def get_history(
    session_id: str = "default",
    session_service: SessionService = Depends(get_session_service),
):
    """取得預測歷史紀錄"""
    session = session_service.get_dashboard_session(session_id)
    return session.prediction_history


@router.post("/clear")
async def clear_history(
    session_id: str = Body(default="default", embed=True),
    session_service: SessionService = Depends(get_session_service),
):
    """清空預測歷史"""
    session_service.clear_dashboard_session(session_id)
    return {"status": "success", "session_id": session_id}


@router.post("/simulator/next")
async def simulator_next(
    session_id: str = Body(default="default", embed=True),
    session_service: SessionService = Depends(get_session_service),
    prediction_service: PredictionService = Depends(get_prediction_service),
):
    """從模擬數據集讀取下一筆並執行推理"""
    try:
        print(f"\n{'=' * 60}")
        print(f"[DEBUG] /api/simulator/next called")
        print(f"[DEBUG] Session ID: {session_id}")
        print(f"[DEBUG] SessionService instance ID: {id(session_service)}")  # 添加这行

        session = session_service.get_dashboard_session(session_id)
        print(f"[DEBUG] Session found: {session is not None}")
        print(f"[DEBUG] Session object ID: {id(session)}")  # 添加这行
        print(
            f"[DEBUG] sim_df loaded: {session.sim_df is not None if session else False}"
        )

        # 檢查該 Session 是否已載入模擬數據
        if session.sim_df is None:
            print(f"[ERROR] No simulation file loaded!")
            raise HTTPException(
                400,
                detail="請先選擇模擬檔案。請在即時看板頁面的 SIMULATOR 區域選擇要模擬的檔案。",
            )

        print(f"[DEBUG] Current index: {session.sim_index}/{len(session.sim_df)}")

        if session.sim_index >= len(session.sim_df):
            print(f"[INFO] Reached end of simulation data")
            return {"status": "EOF", "message": "已到達模擬資料末端。"}

        row = session.sim_df.iloc[session.sim_index]
        session.sim_index += 1

        print(f"[DEBUG] Row fetched, index: {session.sim_index - 1}")

        # 轉換資料格式
        data_dict = row.to_dict()
        data_dict = {k: (v if not pd.isna(v) else None) for k, v in data_dict.items()}

        print(f"[DEBUG] Data dict keys: {list(data_dict.keys())[:10]}...")

        # 從當前載入的模型配置中讀取 goal 欄位作為 Y 軸目標標的
        measure_value = None
        goal_column = None

        print(f"[DEBUG] ========== Y 軸配置診斷 ==========")
        print(f"[DEBUG] session 物件: {session is not None}")
        print(
            f"[DEBUG] hasattr current_model_config: {hasattr(session, 'current_model_config')}"
        )
        if hasattr(session, "current_model_config"):
            print(
                f"[DEBUG] current_model_config 是否為 None: {session.current_model_config is None}"
            )
            if session.current_model_config:
                print(
                    f"[DEBUG] current_model_config keys: {list(session.current_model_config.keys())[:10]}"
                )

        # 嘗試從 session 中獲取當前載入的模型配置
        if hasattr(session, "current_model_config") and session.current_model_config:
            goal_column = session.current_model_config.get("goal")
            print(f"[DEBUG] ✅ Goal column from model config: {goal_column}")
        else:
            print(f"[DEBUG] ❌ No model config found in session")

        # 如果有 goal 欄位且該欄位存在於數據中,使用它作為 measure_value
        if goal_column and goal_column in row.index:
            measure_value = float(row[goal_column])
            print(
                f"[DEBUG] ✅ Using goal column '{goal_column}' as measure: {measure_value}"
            )
        else:
            if goal_column:
                print(f"[DEBUG] ⚠️ Goal column '{goal_column}' not found in data")
                print(
                    f"[DEBUG]    Available columns (first 20): {list(row.index)[:20]}"
                )
            # 備用方案：自動檢測包含 "std" 或 "measure" 的欄位
            print(
                f"[WARNING] Goal column not found in session or data, falling back to auto-detection"
            )
            measure_col_candidates = [
                col
                for col in row.index
                if "std" in col.lower() or "measure" in col.lower()
            ]
            if measure_col_candidates:
                measure_value = float(row[measure_col_candidates[0]])
                print(
                    f"[DEBUG] Measure column found: {measure_col_candidates[0]} = {measure_value}"
                )
            elif len(row.index) > 0:
                # 如果沒有明確的測量欄位，使用第一個數值型欄位
                for col in row.index:
                    try:
                        measure_value = float(row[col])
                        print(
                            f"[DEBUG] Using first numeric column: {col} = {measure_value}"
                        )
                        break
                    except (ValueError, TypeError):
                        continue

        print(f"[DEBUG] ========== Y 軸配置診斷結束 ==========")

        if measure_value is None:
            print(f"[ERROR] No measure value found!")
            raise HTTPException(400, detail="無法找到有效的測量值欄位")

        # 構造 Request
        req = InferenceRequest(
            data=data_dict,
            measure_value=measure_value,
            session_id=session_id,
        )

        print(f"[DEBUG] Calling predict()...")
        result = await predict(req, session_service, prediction_service)

        # 加入 goal 欄位名稱和 goalSettings 到返回結果
        if hasattr(session, "current_model_config") and session.current_model_config:
            result["goal_name"] = session.current_model_config.get("goal", "")
            result["goal_settings"] = session.current_model_config.get(
                "goalSettings"
            ) or session.current_model_config.get("goal_settings")
            print(f"[DEBUG] Added goal_name: {result.get('goal_name')}")
            print(f"[DEBUG] Added goal_settings: {result.get('goal_settings')}")

        print(f"[DEBUG] Predict returned successfully")
        print(f"{'=' * 60}\n")
        return result

    except HTTPException:
        raise
    except Exception as e:
        import traceback

        print(f"\n{'=' * 60}")
        print(f"[ERROR] Exception in simulator_next:")
        print(f"[ERROR] Type: {type(e).__name__}")
        print(f"[ERROR] Message: {str(e)}")
        print(f"[ERROR] Traceback:")
        traceback.print_exc()
        print(f"{'=' * 60}\n")
        raise HTTPException(500, detail=f"推理失敗: {str(e)}")


@router.post("/simulator/load_file")
async def load_simulation_file(
    filename: str = Body(..., embed=True),
    session_id: str = Body(default="default", embed=True),
    session_service: SessionService = Depends(get_session_service),
    file_service: FileService = Depends(get_file_service),
):
    """載入指定的 CSV 檔案作為模擬數據"""
    try:
        print(f"\n{'=' * 60}")
        print(f"[DEBUG] /api/simulator/load_file called")
        print(f"[DEBUG] Filename: {filename}")
        print(f"[DEBUG] Session ID: {session_id}")
        print(f"[DEBUG] SessionService instance ID: {id(session_service)}")  # 添加这行

        # 1. 取得檔案完整路徑
        file_path = file_service.get_file_path(filename, session_id)
        print(f"[DEBUG] File path: {file_path}")
        print(f"[DEBUG] File exists: {os.path.exists(file_path)}")

        # 2. 讀取數據
        print(f"[DEBUG] Loading data...")
        df, _ = DataPreprocess.get_processed_data_and_cols(file_path)
        print(f"[DEBUG] Data loaded: {len(df)} rows, {len(df.columns)} columns")

        # 3. 存入 Session
        session = session_service.get_dashboard_session(session_id)
        print(f"[DEBUG] Session object ID before: {id(session)}")
        print(f"[DEBUG] Session.sim_df before: {session.sim_df is not None}")

        session.sim_df = df
        session.sim_file_name = filename
        session.sim_index = 0  # 重置索引

        print(f"[DEBUG] Session.sim_df after: {session.sim_df is not None}")
        print(f"[DEBUG] Session.sim_df shape: {session.sim_df.shape}")
        print(f"[DEBUG] Session.sim_index: {session.sim_index}")

        logger.info(f"Session {session_id} 載入模擬檔案: {filename} ({len(df)} rows)")

        # 驗證：立即讀取一次確認
        verify_session = session_service.get_dashboard_session(session_id)
        print(f"[DEBUG] Verification - Session object ID: {id(verify_session)}")
        print(
            f"[DEBUG] Verification - sim_df is not None: {verify_session.sim_df is not None}"
        )
        print(f"{'=' * 60}\n")

        return {
            "status": "success",
            "message": f"成功載入 {filename}",
            "rows": len(df),
            "columns": len(df.columns),
        }
    except Exception as e:
        import traceback

        print(f"\n{'=' * 60}")
        print(f"[ERROR] Exception in load_simulation_file:")
        print(f"[ERROR] Type: {type(e).__name__}")
        print(f"[ERROR] Message: {str(e)}")
        print(f"[ERROR] Traceback:")
        traceback.print_exc()
        print(f"{'=' * 60}\n")
        raise HTTPException(500, detail=f"載入檔案失敗: {str(e)}")


@router.post("/model/load")
async def load_specific_model(
    model_path: str = Body(..., embed=True),
    session_id: str = Body(default="default", embed=True),
    prediction_service: PredictionService = Depends(get_prediction_service),
    session_service: SessionService = Depends(get_session_service),
    file_service: FileService = Depends(get_file_service),
):
    """指定載入特定版本的模型"""
    try:
        # 載入模型
        agent = prediction_service.get_agent(session_id)
        agent.reload_model(target_bundle_name=model_path)

        # 如果是 job_xxx.json 配置檔,讀取並儲存到 session
        if model_path.endswith(".json") and model_path.startswith("job_"):
            import json

            configs_dir = file_service.get_user_path(session_id, "configs")
            config_path = os.path.join(configs_dir, model_path)

            if os.path.exists(config_path):
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        job_config = json.load(f)

                    # 儲存配置到 session
                    session = session_service.get_dashboard_session(session_id)
                    session.current_model_config = job_config

                    logger.info(
                        f"Session {session_id} 載入模型配置: {model_path}, goal={job_config.get('goal')}"
                    )
                except Exception as e:
                    logger.warning(f"Failed to load model config {model_path}: {e}")

        return {
            "status": "success",
            "message": f"Model {model_path} loaded",
            "config": job_config if 'job_config' in locals() else None
        }
    except Exception as e:
        logger.error(f"模型載入失敗: {e}", exc_info=True)
        raise HTTPException(500, f"Model load failed: {str(e)}")


@router.get("/simulator/models")
async def list_available_models(
    session_id: str = "default",
    file_service: FileService = Depends(get_file_service),
):
    """列出該使用者可用的模型 (Config Jobs) - 返回詳細資訊"""
    try:
        models = []
        import json

        # 1. 取得 configs 路徑
        configs_dir = file_service.get_user_path(session_id, "configs")
        if os.path.exists(configs_dir):
            for f in os.listdir(configs_dir):
                if f.startswith("job_") and f.endswith(".json"):
                    full_path = os.path.join(configs_dir, f)
                    try:
                        with open(full_path, "r", encoding="utf-8") as jf:
                            data = json.load(jf)

                            # 檢查訓練狀態 (Fool-proofing)
                            status = data.get("status", "unknown")
                            if status != "completed":
                                continue

                            # 優先使用 model_name，若無則使用 modelName 或檔名
                            model_name = (
                                data.get("model_name") or data.get("modelName") or f
                            )

                            # 取得 R2 分數（若存在）
                            r2 = data.get("r2")
                            r2_text = f"R2: {r2:.4f}" if r2 is not None else "N/A"

                            # 取得建立時間
                            created = data.get("created_at", "")

                            # 組合顯示名稱：Model_XXX | R2: 0.xxxx | 2026/02/03 23:37:36
                            if created:
                                display_name = f"{model_name} | {r2_text} | {created}"
                            else:
                                display_name = f"{model_name} | {r2_text}"

                            models.append(
                                {
                                    "id": f,
                                    "name": display_name,
                                    "timestamp": os.path.getmtime(full_path),
                                    "data": data,  # 關鍵修正：回傳完整配置數據
                                }
                            )
                    except Exception as e:
                        logger.warning(f"Failed to parse config {f}: {e}")
                        # Skip corrupted or invalid config files
                        continue

        # 2. 備援：Bundles 路徑
        models_dir = file_service.get_user_path(session_id, "bundles")
        if os.path.exists(models_dir):
            with os.scandir(models_dir) as entries:
                for entry in entries:
                    if entry.is_file() and (
                        entry.name.endswith(".zip") or entry.name.endswith(".pt")
                    ):
                        models.append(
                            {
                                "id": entry.name,
                                "name": entry.name,
                                "timestamp": entry.stat().st_mtime,
                            }
                        )

        models.sort(key=lambda x: x["timestamp"], reverse=True)
        return models
    except Exception as e:
        logger.error(f"列出模型失敗: {e}")
        return []
