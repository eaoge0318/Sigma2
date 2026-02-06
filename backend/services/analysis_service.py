"""
分析服務
負責進階分析、模型訓練等業務邏輯
"""

import os
import json
import uuid
import pandas as pd
import numpy as np
from typing import Dict, Any, List
from fastapi import HTTPException
from backend.models.request_models import (
    AdvancedAnalysisRequest,
    SaveFileRequest,
    TrainRequest,
    QuickAnalysisRequest,
)

import config as app_config


class AnalysisService:
    """分析服務，處理數據分析相關的業務邏輯"""

    def __init__(self, base_upload_dir: str = None):
        self.base_upload_dir = base_upload_dir or app_config.BASE_STORAGE_DIR

    def get_user_upload_dir(self, session_id: str) -> str:
        """取得特定使用者的上傳目錄 (Helper)"""
        safe_session_id = "".join(
            [c for c in session_id if c.isalnum() or c in ("-", "_")]
        ).strip()
        if not safe_session_id:
            safe_session_id = "default"
        return os.path.join(self.base_upload_dir, safe_session_id, "uploads")

    async def advanced_analysis(
        self, req: AdvancedAnalysisRequest, session_id: str = "default"
    ) -> Dict[str, Any]:
        """
        執行進階分析

        Args:
            req: 分析請求
            session_id: 使用者 Session ID

        Returns:
            分析結果
        """
        # print(
        #     f"DEBUG: Advanced Analysis requested for {req.filename}, "
        #     f"target={req.target_column}, algo={req.algorithm}, session={session_id}"
        # )
        try:
            upload_dir = self.get_user_upload_dir(session_id)
            file_path = os.path.join(upload_dir, req.filename)
            if not os.path.exists(file_path):
                # print(f"DEBUG: File not found at {file_path}")
                raise HTTPException(404, detail=f"File not found: {req.filename}")

            df = pd.read_csv(file_path)

            if req.target_column not in df.columns:
                raise HTTPException(400, detail="Target column not in file")

            # 僅對數值欄位進行分析
            numeric_df = df.select_dtypes(include=[np.number])
            if req.target_column not in numeric_df.columns:
                # 嘗試轉換
                try:
                    df[req.target_column] = pd.to_numeric(
                        df[req.target_column], errors="coerce"
                    )
                    numeric_df = df.select_dtypes(include=[np.number])
                except Exception as e:
                    raise HTTPException(
                        400,
                        detail=f"Target '{req.target_column}' is not numeric: {str(e)}",
                    )

            # 準備 X and y
            y = numeric_df[req.target_column].ffill().bfill()
            X = numeric_df.drop(columns=[req.target_column]).fillna(0)

            results = []

            if req.algorithm == "correlation":
                # 計算皮爾森相關係數
                raw_corrs = X.corrwith(y)
                sorted_cols = raw_corrs.abs().sort_values(ascending=False).index

                for col in sorted_cols:
                    val = raw_corrs[col]
                    if not np.isnan(val):
                        results.append({"col": str(col), "score": float(val)})

            elif req.algorithm == "xgboost":
                import xgboost as xgb
                import shap

                # 訓練輕量級模型
                model = xgb.XGBRegressor(n_estimators=100, max_depth=4, random_state=42)
                model.fit(X, y)

                # 計算 SHAP 值
                explainer = shap.TreeExplainer(model)
                shap_values = explainer.shap_values(X)

                if isinstance(shap_values, list):
                    shap_values = shap_values[0]

                # 平均絕對 SHAP 值
                vals = np.abs(shap_values).mean(axis=0)
                feature_importance = pd.Series(vals, index=X.columns).sort_values(
                    ascending=False
                )

                for col, val in feature_importance.items():
                    results.append({"col": str(col), "score": float(val)})

            else:
                raise HTTPException(400, detail="Unknown algorithm")

            return {"status": "success", "results": results}

        except HTTPException:
            raise
        except Exception as e:
            import traceback

            traceback.print_exc()
            raise HTTPException(500, detail=f"Analysis failed: {str(e)}")

    async def save_filtered_file(
        self, req: SaveFileRequest, session_id: str = "default"
    ) -> Dict[str, str]:
        """
        儲存過濾後的檔案

        Args:
            req: 儲存請求
            session_id: 使用者 Session ID

        Returns:
            儲存結果
        """
        try:
            # 確保檔名安全
            safe_filename = "".join(
                [c for c in req.filename if c.isalnum() or c in (" ", ".", "_", "-")]
            ).strip()
            if not safe_filename.endswith(".csv"):
                safe_filename += ".csv"

            upload_dir = self.get_user_upload_dir(session_id)
            file_path = os.path.join(upload_dir, safe_filename)

            # 使用 pandas 寫入 CSV
            df = pd.DataFrame(req.rows, columns=req.headers)
            df.to_csv(file_path, index=False, encoding="utf-8-sig")

            return {
                "status": "success",
                "filename": safe_filename,
                "message": f"檔案 {safe_filename} 已儲存至檔案管理",
            }
        except Exception as e:
            raise HTTPException(500, detail=f"Save failed: {str(e)}")

    async def train_model(
        self, req: TrainRequest, session_id: str = "default"
    ) -> Dict[str, Any]:
        """
        異步觸發模型訓練任務，保存配置並背景啟動引擎 (多租戶隔離版)。
        """
        try:
            import json
            import subprocess
            import sys
            from datetime import datetime
            from backend.dependencies import get_file_service

            file_service = get_file_service()

            # 1. 準備隔離目錄
            config_dir = file_service.get_user_path(session_id, "configs")
            log_dir = file_service.get_user_path(session_id, "logs")
            bundles_dir = file_service.get_user_path(session_id, "bundles")

            # 2. 生成配置與作業標記
            job_id = f"job_{uuid.uuid4().hex[:8]}"
            config_filename = f"{job_id}.json"
            json_path = os.path.join(config_dir, config_filename)

            full_config = dict(req.config)

            # 關鍵修正：將相對檔名轉換為絕對路徑，確保背景引擎能找到檔案
            raw_filename = full_config.get("filename")
            target_abs_path = None
            if raw_filename:
                # 取得使用者上傳目錄
                user_dir = file_service.get_user_upload_dir(session_id)
                full_path = os.path.join(user_dir, raw_filename)

                # 如果該 session 目錄找不到，嘗試 default 目錄
                if not os.path.exists(full_path) and session_id != "default":
                    default_dir = file_service.get_user_upload_dir("default")
                    full_path = os.path.join(default_dir, raw_filename)

                if os.path.exists(full_path):
                    target_abs_path = os.path.abspath(full_path)
                    full_config["data_full_path"] = target_abs_path
                else:
                    print(f"Warning: Training data file not found at {full_path}")

            # 自動校正資料筆數
            if target_abs_path and (
                full_config.get("rows") == "未知" or not full_config.get("rows")
            ):
                try:
                    with open(
                        target_abs_path, "r", encoding="utf-8", errors="ignore"
                    ) as f:
                        row_count = sum(1 for _ in f) - 1
                    full_config["rows"] = str(max(0, row_count))
                except Exception:
                    full_config["rows"] = "未知"

            full_config["job_id"] = job_id
            full_config["session_id"] = session_id  # 記錄所屬 session
            full_config["created_at"] = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
            full_config["status"] = "training"
            full_config["bundles_dir"] = bundles_dir  # 告知引擎模型存放地

            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(full_config, f, ensure_ascii=False, indent=4)

            log_file_path = os.path.join(log_dir, f"{job_id}.log")

            # 3. 根據任務類型與配置自動判定執行引擎
            mission_type = full_config.get("missionType") or full_config.get(
                "type", "supervised"
            )
            has_rl = len(full_config.get("actions", [])) > 0
            has_ml = len(full_config.get("features", [])) > 0

            if has_rl and has_ml:
                script_name = os.path.join("engines", "joint_training_orchestrator.py")
            elif mission_type == "rl" or has_rl:
                script_name = os.path.join("engines", "engine_strategy.py")
            else:
                script_name = os.path.join("engines", "engine_prediction.py")

            script_path = os.path.abspath(script_name)

            # 啟動子進程並將輸出定向到隔離後的 log
            try:
                log_file = open(log_file_path, "ab")
                proc = subprocess.Popen(
                    [sys.executable, script_path, json_path],
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                full_config["pid"] = proc.pid
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(full_config, f, ensure_ascii=False, indent=4)
            except Exception as e:
                full_config["status"] = "failed"
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(full_config, f, ensure_ascii=False, indent=4)
                return {"status": "error", "message": f"啟動訓練失敗: {str(e)}"}

            display_name = full_config.get("modelName") or full_config.get(
                "model_name", "Unnamed"
            )
            return {
                "status": "success",
                "message": f"Successfully started {mission_type} training for {display_name}",
                "job_id": job_id,
            }
        except Exception as e:
            raise HTTPException(500, detail=f"訓練編排失敗: {str(e)}")

    async def list_models(self, session_id: str = "default") -> List[Dict[str, Any]]:
        """
        列表化顯示特定使用者的模型工作。
        """
        try:
            from backend.dependencies import get_file_service

            file_service = get_file_service()
            config_dir = file_service.get_user_path(session_id, "configs")

            if not os.path.exists(config_dir):
                return []

            models = []
            for fname in os.listdir(config_dir):
                if fname.endswith(".json"):
                    fpath = os.path.join(config_dir, fname)
                    try:
                        with open(fpath, "r", encoding="utf-8") as f:
                            m_data = json.load(f)

                            # 關鍵增強：檢查「訓練中」的模型進程是否還活著
                            if m_data.get("status") == "training" and m_data.get("pid"):
                                pid = m_data.get("pid")
                                is_alive = self._check_process_alive(pid)

                                if not is_alive:
                                    m_data["status"] = "failed"
                                    m_data["error"] = "Process unexpectedly terminated."
                                    with open(fpath, "w", encoding="utf-8") as fw:
                                        json.dump(
                                            m_data, fw, ensure_ascii=False, indent=4
                                        )
                            models.append(m_data)
                    except Exception:
                        continue
            return sorted(models, key=lambda x: x.get("created_at", ""), reverse=True)
        except Exception as e:
            print(f"Error listing models: {str(e)}")
            return []

    def _check_process_alive(self, pid: int) -> bool:
        """檢查進程是否還活著 (Helper)"""
        if os.name == "nt":
            try:
                import subprocess as sp

                output = sp.check_output(
                    f'tasklist /FI "PID eq {pid}" /NH', shell=True
                ).decode("gbk", errors="ignore")
                return str(pid) in output
            except Exception:
                return False
        else:
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                return False

    async def get_training_log(self, job_id: str, session_id: str = "default") -> str:
        """獲取特定任務的訓練日誌內容 (隔離版)"""
        from backend.dependencies import get_file_service

        job_id = "".join(c for c in job_id if c.isalnum() or c == "_")
        log_dir = get_file_service().get_user_path(session_id, "logs")
        log_path = os.path.join(log_dir, f"{job_id}.log")

        if not os.path.exists(log_path):
            return "尚未生成日誌或任務不存在。"

        try:
            encodings = ["utf-8", "gbk", "big5", "cp950", "utf-16"]
            content = None
            with open(log_path, "rb") as f:
                raw_data = f.read()
                from collections import deque

                lines = deque(raw_data.splitlines(), maxlen=2000)
                raw_data_tail = b"\n".join(lines)

            for enc in encodings:
                try:
                    content = raw_data_tail.decode(enc, errors="replace")
                    break
                except Exception:
                    continue
            return content or "正在初始化訓練系統並等待日誌輸出..."
        except Exception as e:
            return f"讀取日誌出錯: {str(e)}"

    async def delete_model(
        self, job_id: str, session_id: str = "default"
    ) -> Dict[str, Any]:
        """刪除特定模型任務 (隔離版)"""
        from backend.dependencies import get_file_service
        import signal

        file_service = get_file_service()

        job_id = "".join(c for c in job_id if c.isalnum() or c == "_")
        config_path = os.path.join(
            file_service.get_user_path(session_id, "configs"), f"{job_id}.json"
        )
        log_path = os.path.join(
            file_service.get_user_path(session_id, "logs"), f"{job_id}.log"
        )

        try:
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    m_data = json.load(f)
                    pid = m_data.get("pid")
                    if pid and m_data.get("status") == "training":
                        if os.name == "nt":
                            os.system(f"taskkill /F /T /PID {pid}")
                        else:
                            os.kill(pid, signal.SIGTERM)
        except Exception:
            pass

        deleted = False
        try:
            if os.path.exists(config_path):
                os.remove(config_path)
                deleted = True
            if os.path.exists(log_path):
                os.remove(log_path)
                deleted = True
            if deleted:
                return {"status": "success", "message": f"模型任務 {job_id} 已刪除"}
            return {"status": "error", "message": "找不到檔案"}
        except Exception as e:
            return {"status": "error", "message": f"刪除失敗: {str(e)}"}

    async def stop_model(
        self, job_id: str, session_id: str = "default"
    ) -> Dict[str, Any]:
        """停止訓練進程 (隔離版)"""
        from backend.dependencies import get_file_service
        import signal

        file_service = get_file_service()

        job_id = "".join(c for c in job_id if c.isalnum() or c == "_")
        config_path = os.path.join(
            file_service.get_user_path(session_id, "configs"), f"{job_id}.json"
        )

        if not os.path.exists(config_path):
            return {"status": "error", "message": "找不到該模型配置"}

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                m_data = json.load(f)

            pid = m_data.get("pid")
            if pid and m_data.get("status") == "training":
                if os.name == "nt":
                    os.system(f"taskkill /F /T /PID {pid}")
                else:
                    os.kill(pid, signal.SIGTERM)

                m_data["status"] = "failed"
                m_data["error"] = "Manually stopped by user."
                with open(config_path, "w", encoding="utf-8") as fw:
                    json.dump(m_data, fw, ensure_ascii=False, indent=4)
                return {"status": "success", "message": f"任務 {job_id} 已強制停止"}
            return {"status": "error", "message": "任務已結束或無運行中的進程"}
        except Exception as e:
            return {"status": "error", "message": f"停止失敗: {str(e)}"}

    async def quick_analysis(
        self, req: QuickAnalysisRequest, session_id: str = "default"
    ) -> Dict[str, Any]:
        """
        執行快速分析，生成數據摘要。優先由磁碟讀取全量數據以獲取準確統計。
        """
        try:
            # 確保檔案路徑正確
            filename = os.path.basename(req.filename)
            upload_dir = self.get_user_upload_dir(session_id)
            file_path = os.path.join(upload_dir, filename)

            # Fallback: Check default directory if file not found in current session
            if not os.path.exists(file_path) and session_id != "default":
                default_dir = self.get_user_upload_dir("default")
                default_path = os.path.join(default_dir, filename)
                if os.path.exists(default_path):
                    # print(
                    #     f"DEBUG: [QuickAnalysis] File found in default dir: {default_path}"
                    # )
                    file_path = default_path

            df = None
            data_source = f"前端傳送數據 (約 {len(req.rows)} 筆)"

            if os.path.exists(file_path):
                try:
                    # 讀取全量數據
                    df = pd.read_csv(file_path)
                    data_source = f"伺服器原始檔案 ({len(df)} 筆)"
                    # print(f"DEBUG: [QuickAnalysis] Loading full file: {file_path}")

                    # 套用過濾器
                    if req.filters and len(req.filters) > 0:
                        for f in req.filters:
                            ftype = f.get("type", "text")

                            # 針對 'indices' 特殊處理：使用 index 而非 iloc，確保精準匹配原始行號
                            if ftype in ["indices", "exclude_indices"]:
                                indices = f.get("indices", [])
                                if ftype == "indices":
                                    df = df[df.index.isin(indices)]
                                else:
                                    df = df[~df.index.isin(indices)]
                                continue

                            col_name = f.get("colName")
                            col_idx = f.get("colIdx")
                            actual_col = col_name
                            if (
                                actual_col not in df.columns
                                and isinstance(col_idx, int)
                                and col_idx < len(df.columns)
                            ):
                                actual_col = df.columns[col_idx]

                            if actual_col in df.columns:
                                if ftype == "range":
                                    f_min = pd.to_numeric(f.get("min"), errors="coerce")
                                    f_max = pd.to_numeric(f.get("max"), errors="coerce")
                                    df[actual_col] = pd.to_numeric(
                                        df[actual_col], errors="coerce"
                                    )
                                    df = df[
                                        (df[actual_col] >= f_min)
                                        & (df[actual_col] <= f_max)
                                    ]
                                elif ftype == "exclude_range":
                                    f_min = pd.to_numeric(f.get("min"), errors="coerce")
                                    f_max = pd.to_numeric(f.get("max"), errors="coerce")
                                    df[actual_col] = pd.to_numeric(
                                        df[actual_col], errors="coerce"
                                    )
                                    df = df[
                                        (df[actual_col] < f_min)
                                        | (df[actual_col] > f_max)
                                    ]
                                elif ftype == "not_empty":
                                    # 處理空字串與 NaN
                                    df = df[
                                        df[actual_col].astype(str).str.strip() != ""
                                    ]
                                    df = df[df[actual_col].notna()]
                                else:  # text search (contains)
                                    val = str(f.get("value", "")).lower()
                                    df = df[
                                        df[actual_col]
                                        .astype(str)
                                        .str.lower()
                                        .str.contains(val, na=False)
                                    ]

                    data_source = f"伺服器全量過濾數據 ({len(df)} 筆)"
                except Exception as e:
                    print(f"ERROR: [QuickAnalysis] Full file load failed: {e}")
                    df = None

            # 如果磁碟讀取失敗或檔案不存在，回退到使用請求中傳入的 rows
            if df is None:
                df = pd.DataFrame(req.rows, columns=req.headers)

            row_count = len(df)
            col_count = len(df.columns)

            # 計算完整度 (基於當前 df 的所有行)
            completeness = df.count() / len(df) if len(df) > 0 else df.count() * 0
            low_completeness_cols = completeness[completeness < 0.9]

            summary_text = (
                f"📊 **全量數據空值分析報告 ({filename})**\n"
                f"> [!IMPORTANT]\n"
                f"> 此份報告是針對**後端全量檔案實體**進行的空值與完整度診斷。\n\n"
                f"- **數據來源**: {data_source}\n"
                f"- **總分析筆數**: {row_count} 筆\n"
                f"- **欄位總數**: {col_count} 個\n"
            )

            if not low_completeness_cols.empty:
                summary_text += "- **空值警告 (全量完整度 < 90%)**:\n"
                for col, comp in low_completeness_cols.items():
                    summary_text += f"  - `{col}`: 完整度 {comp * 100:.1f}%\n"
            else:
                summary_text += "- **空值檢查**: 通過。所有欄位在全量數據下完整度均為 100% 或 > 90%\n"

            return {
                "status": "success",
                "summary": summary_text,
                "row_count": row_count,
            }
        except Exception as e:
            import traceback

            traceback.print_exc()
            raise HTTPException(500, detail=f"Quick analysis failed: {str(e)}")

    async def get_column_data(
        self, filename: str, column: str, session_id: str = "default"
    ) -> Dict[str, Any]:
        """
        獲取特定欄位的數據分佈，用於圖表預覽
        """
        try:
            upload_dir = self.get_user_upload_dir(session_id)
            file_path = os.path.join(upload_dir, filename)

            # Fallback to default
            if not os.path.exists(file_path) and session_id != "default":
                default_path = os.path.join(
                    self.get_user_upload_dir("default"), filename
                )
                if os.path.exists(default_path):
                    file_path = default_path

            if not os.path.exists(file_path):
                raise HTTPException(404, detail=f"File not found: {filename}")

            df = pd.read_csv(file_path)
            if column not in df.columns:
                raise HTTPException(400, detail=f"Column '{column}' not in file")

            # 轉為數值，非數值轉為 0
            series = pd.to_numeric(df[column], errors="coerce").fillna(0)
            data = series.tolist()

            # 採樣至最多 500 點以提昇前端繪圖效能
            if len(data) > 500:
                indices = np.linspace(0, len(data) - 1, 500, dtype=int)
                data = [data[i] for i in indices]

            return {"success": True, "data": data}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(500, detail=f"Get column data failed: {str(e)}")
