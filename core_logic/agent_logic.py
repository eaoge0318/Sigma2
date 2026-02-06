# agent_logic.py
import numpy as np
import config
from . import model_manager
from .xgb_predict import XGBSimulator
from collections import deque
import logging

# 获取 logger
logger = logging.getLogger(__name__)


class AgenticReasoning:
    def __init__(self, session_id: str = "default"):
        self.session_id = session_id
        self.iql_algo = None
        self.meta = None
        self.simulator = None
        self.explainer = None
        self.shap_history = None
        self.action_history = deque(maxlen=config.SHAP_SMOOTHING_WINDOW)

        # 初始化預設特徵，避免未載入模型時崩潰
        self.bg_features = getattr(config, "STATE_FEATURES", [])
        self.action_features = getattr(config, "ACTION_FEATURES", [])
        self.action_stds = None
        self.y_low = getattr(config, "Y_LOW", 0)
        self.y_high = getattr(config, "Y_HIGH", 1)
        self.target_center = getattr(
            config, "TARGET_CENTER", (self.y_low + self.y_high) / 2
        )

        # 執行首次模型載入
        self.reload_model()

    def reload_model(self, target_bundle_name: str = None):
        """從隔離空間重新載入模型與模擬器"""
        try:
            from backend.dependencies import get_file_service
            import os

            file_service = get_file_service()
            user_bundles_dir = file_service.get_user_path(self.session_id, "bundles")

            actual_model_path = None
            pred_model_dir = user_bundles_dir  # XGBoost 模型目錄，預設為 bundles

            if target_bundle_name:
                # 嘗試解析使用者指定的模型

                # 情境 0: 是 job_xxx.json (Config File)
                if target_bundle_name.endswith(
                    ".json"
                ) and target_bundle_name.startswith("job_"):
                    import json

                    configs_dir = file_service.get_user_path(self.session_id, "configs")
                    config_path = os.path.join(configs_dir, target_bundle_name)
                    if os.path.exists(config_path):
                        try:
                            with open(config_path, "r", encoding="utf-8") as f:
                                job_conf = json.load(f)

                                # 從設定檔中獲取 RL 模型路徑 (run_dir)
                                run_dir = job_conf.get("run_dir")
                                if run_dir and os.path.exists(run_dir):
                                    if os.path.exists(
                                        os.path.join(run_dir, "policy_bundle")
                                    ):
                                        actual_model_path = os.path.join(
                                            run_dir, "policy_bundle"
                                        )
                                    else:
                                        actual_model_path = run_dir
                                    print(
                                        f"✅ RL Model: Loaded config {target_bundle_name} pointing to {actual_model_path}"
                                    )
                                else:
                                    print(
                                        f"⚠️ Config {target_bundle_name} has invalid run_dir: {run_dir}"
                                    )

                                # 從設定檔中獲取預測模型路徑 (run_path)
                                run_path = job_conf.get("run_path")
                                if run_path and os.path.exists(run_path):
                                    pred_model_dir = run_path
                                    print(
                                        f"✅ Prediction Model: Using run_path from config: {pred_model_dir}"
                                    )
                                else:
                                    print(
                                        f"⚠️ Config {target_bundle_name} has invalid or missing run_path: {run_path}, using default"
                                    )
                        except Exception as e:
                            print(f"Failed to parse config {target_bundle_name}: {e}")

                # 若還未找到，嘗試直接匹配路徑
                if not actual_model_path:
                    possible_path = os.path.join(user_bundles_dir, target_bundle_name)

                    # 情境 1: 此為 rl_run 目錄，下面還有 policy_bundle
                    if os.path.isdir(possible_path) and os.path.exists(
                        os.path.join(possible_path, "policy_bundle")
                    ):
                        actual_model_path = os.path.join(possible_path, "policy_bundle")
                        print(f"Loading specific run bundle: {target_bundle_name}")
                    # 情境 2: 此為直接的模型目錄或檔案
                    elif os.path.exists(possible_path):
                        actual_model_path = possible_path
                        print(f"Loading specific model path: {target_bundle_name}")
                    else:
                        print(
                            f"Warning: Specified model {target_bundle_name} not found or validity check failed. Falling back to latest."
                        )

            # 若無指定或找不到，載入最新的 IQL 策略模型
            if not actual_model_path:
                print(
                    f"ℹ️ No specific model specified, searching for latest model in {user_bundles_dir}"
                )
                actual_model_path = model_manager.find_latest_best_model(
                    user_bundles_dir
                )
                if actual_model_path:
                    print(f"✅ Found latest model: {actual_model_path}")
                else:
                    print(f"⚠️ No model found in {user_bundles_dir}")

            if actual_model_path:
                print(f"🔄 Loading policy bundle from: {actual_model_path}")
                try:
                    self.iql_algo, self.meta = model_manager.load_policy_bundle(
                        actual_model_path
                    )
                    print(f"✅ Policy bundle loaded successfully")
                    print(
                        f"   - bg_features: {len(self.meta.get('bg_features', []))} features"
                    )
                    print(f"   - action_stds: {self.meta.get('action_stds', 'None')}")

                    self.bg_features = self.meta["bg_features"]
                    self.action_stds = self.meta["action_stds"]

                    # 從 JSON 配置讀取 actions (如果有的話)
                    if target_bundle_name and target_bundle_name.endswith(".json"):
                        try:
                            configs_dir = file_service.get_user_path(
                                self.session_id, "configs"
                            )
                            config_path = os.path.join(configs_dir, target_bundle_name)
                            if os.path.exists(config_path):
                                with open(config_path, "r", encoding="utf-8") as f:
                                    job_conf = json.load(f)

                                    # 讀取 actions
                                    self.action_features = job_conf.get("actions", [])
                                    print(
                                        f"   - action_features from JSON: {len(self.action_features)} features"
                                    )
                                    print(f"     {self.action_features}")

                                    # 讀取 goalSettings (LSL/USL)
                                    goal_settings = job_conf.get(
                                        "goalSettings"
                                    ) or job_conf.get("goal_settings")
                                    if goal_settings:
                                        self.y_low = float(goal_settings.get("lsl", 0))
                                        self.y_high = float(goal_settings.get("usl", 1))
                                        self.target_center = float(
                                            goal_settings.get(
                                                "target", (self.y_low + self.y_high) / 2
                                            )
                                        )
                                        print(
                                            f"   - Y range from JSON: [{self.y_low}, {self.y_high}]"
                                        )
                                        print(
                                            f"   - Target center: {self.target_center}"
                                        )
                                    else:
                                        self.y_low = getattr(config, "Y_LOW", 0)
                                        self.y_high = getattr(config, "Y_HIGH", 1)
                                        self.target_center = getattr(
                                            config,
                                            "TARGET_CENTER",
                                            (self.y_low + self.y_high) / 2,
                                        )
                        except Exception as e:
                            print(f"⚠️ Failed to read actions from JSON: {e}")
                            self.action_features = getattr(
                                config, "ACTION_FEATURES", []
                            )
                            self.y_low = getattr(config, "Y_LOW", 0)
                            self.y_high = getattr(config, "Y_HIGH", 1)
                            self.target_center = getattr(
                                config, "TARGET_CENTER", (self.y_low + self.y_high) / 2
                            )
                    else:
                        self.action_features = getattr(config, "ACTION_FEATURES", [])
                        self.y_low = getattr(config, "Y_LOW", 0)
                        self.y_high = getattr(config, "Y_HIGH", 1)
                        self.target_center = getattr(
                            config, "TARGET_CENTER", (self.y_low + self.y_high) / 2
                        )
                except Exception as e:
                    print(f"❌ Failed to load policy bundle: {e}")
                    self.iql_algo = None
                    self.meta = None
            else:
                print(f"⚠️ No RL model path found. IQL will not be available.")
                self.iql_algo = None

            # 載入 XGBoost 模擬器（使用指定的 pred_model_dir）
            print(f"🔄 Loading XGBoost simulator from: {pred_model_dir}")
            self.simulator = XGBSimulator(model_dir=pred_model_dir)
            if self.simulator.model:
                print(f"✅ XGBoost model loaded successfully")
            else:
                print(f"⚠️ XGBoost model not loaded")

            # 初始化 SHAP 解釋器
            if self.simulator.model:
                import shap

                self.explainer = shap.TreeExplainer(self.simulator.model)
                self.shap_history = deque(maxlen=config.SHAP_SMOOTHING_WINDOW)
                print(f"✅ SHAP explainer initialized")

            # 清空歷史記錄,避免形狀不一致問題
            self.action_history.clear()
            print("✅ Action history cleared")

            print(
                f"AgenticReasoning: Session {self.session_id} models reloaded successfully"
            )
            print(f"  - RL Model: {actual_model_path}")
            print(f"  - Prediction Model Dir: {pred_model_dir}")
            print(f"  - IQL Available: {self.iql_algo is not None}")
            print(f"  - XGBoost Available: {self.simulator.model is not None}")
        except Exception as e:
            print(
                f"AgenticReasoning: Reload failed for session {self.session_id} - {e}"
            )
            import traceback

            traceback.print_exc()

    def get_reasoned_advice(self, row, current_y):
        """
        執行 Agentic 推理: IQL 提議 -> XGBoost 驗證 + SHAP 歸因分析
        """
        # 详细调试日志
        logger.debug("=" * 60)
        logger.debug("🔍 get_reasoned_advice 调试信息")
        logger.debug("=" * 60)
        logger.debug(f"Session ID: {self.session_id}")
        logger.debug(f"IQL Model Available: {self.iql_algo is not None}")
        logger.debug(f"Simulator Available: {self.simulator is not None}")
        logger.debug(
            f"XGBoost Model Available: {self.simulator.model is not None if self.simulator else False}"
        )
        logger.debug(
            f"BG Features Count: {len(self.bg_features) if self.bg_features else 0}"
        )
        logger.debug(f"Action STDs: {self.action_stds}")
        logger.debug(f"Current Y: {current_y}")

        # 防呆檢查：確保模型已載入
        if not self.iql_algo:
            logger.error("❌ IQL model not loaded!")
            logger.error("   Reason: self.iql_algo is None")
            return {
                "current_y": current_y,
                "iql_action_delta": None,
                "iql_action_delta_smoothed": None,
                "predicted_y_next": None,
                "top_influencers": [],
                "current_top_influencers": [],
                "smoothed_top_influencers": [],
                "status": "HOLD",
                "diagnosis": "警告：尚未載入有效的策略模型（iql_algo is None），無法提供建議。請先執行模型訓練。",
            }

        if not self.bg_features:
            logger.error("❌ BG features not loaded!")
            logger.error("   Reason: self.bg_features is None or empty")
            return {
                "current_y": current_y,
                "iql_action_delta": None,
                "iql_action_delta_smoothed": None,
                "predicted_y_next": None,
                "top_influencers": [],
                "current_top_influencers": [],
                "smoothed_top_influencers": [],
                "status": "HOLD",
                "diagnosis": "警告：背景特徵未載入（bg_features is None），無法提供建議。請先執行模型訓練。",
            }

        logger.info("✅ All models loaded successfully, proceeding with inference...")
        print("=" * 60)
        print("[DEBUG] Starting inference workflow...")

        # 1. 取得特徵值
        try:
            print("[DEBUG] ⏳ Extracting features...")
            print(f"[DEBUG]    BG Features count: {len(self.bg_features)}")
            print(f"[DEBUG]    Action Features count: {len(self.action_features)}")
            print(f"[DEBUG]    Row data keys count: {len(row.keys())}")

            # 检查是否有缺失的特征
            missing_bg = [f for f in self.bg_features if f not in row]
            missing_act = [f for f in self.action_features if f not in row]

            if missing_bg:
                print(f"[ERROR] ❌ Missing BG features: {missing_bg[:10]}...")
            if missing_act:
                print(f"[ERROR] ❌ Missing Action features: {missing_act}")

            print("[DEBUG] ⏳ Extracting BG values...")
            bg_vals = [row[f] for f in self.bg_features]
            print(f"[DEBUG] ✅ BG values extracted: {len(bg_vals)} values")

            print("[DEBUG] ⏳ Extracting Action values...")
            act_vals = [row[f] for f in self.action_features]
            print(f"[DEBUG] ✅ Action values extracted: {len(act_vals)} values")

        except KeyError as e:
            print(f"[ERROR] ❌ KeyError when extracting features: {e}")
            print(f"[ERROR]    Missing feature: {str(e)}")
            raise
        except Exception as e:
            print(f"[ERROR] ❌ Unexpected error when extracting features: {e}")
            import traceback

            traceback.print_exc()
            raise

        # 2. 先用 IQL 推理出 action delta
        print("[DEBUG] ⏳ Running IQL inference...")
        state_iql = np.concatenate([bg_vals, act_vals, [current_y]], axis=0)[
            None, :
        ].astype(np.float32)

        try:
            action_norm = self.iql_algo.predict(state_iql)[0]
            print(
                f"[DEBUG] ✅ IQL inference complete, action_norm shape: {action_norm.shape}"
            )
        except AssertionError as e:
            print(f"[ERROR] ❌ IQL model dimension mismatch: {e}")
            print(f"[ERROR]    Expected state shape: {state_iql.shape}")
            print(
                f"[ERROR]    This usually means the loaded IQL model was trained with different features"
            )
            print(f"[WARNING] ⚠️ Skipping IQL inference, using HOLD strategy")

            # 跳過 IQL,返回 HOLD 狀態
            return {
                "current_y": current_y,
                "iql_action_delta": None,
                "iql_action_delta_smoothed": None,
                "predicted_y_next": None,
                "top_influencers": [],
                "current_top_influencers": [],
                "smoothed_top_influencers": [],
                "status": "HOLD",
                "diagnosis": f"警告: IQL 模型特徵維度不匹配 (期望: {state_iql.shape[1]} 個特徵)。請使用匹配的模型配置,或重新訓練模型。當前建議: 維持現狀。",
            }

        # 邏輯判斷: 若在帶內則 HOLD
        is_locked = self.y_low <= current_y <= self.y_high
        delta_suggested = (
            np.zeros_like(action_norm) if is_locked else action_norm * self.action_stds
        )
        print(f"[DEBUG]    Is locked: {is_locked}")
        print(f"[DEBUG]    Delta suggested: {delta_suggested}")

        # 2b. 動作平滑邏輯
        # 確保 delta_suggested 是 numpy array 且形狀一致
        delta_suggested = np.array(delta_suggested).flatten()

        # 檢查形狀是否一致
        if len(self.action_history) > 0:
            expected_shape = self.action_history[0].shape
            if delta_suggested.shape != expected_shape:
                print(
                    f"[WARNING] ⚠️ Action shape mismatch: expected {expected_shape}, got {delta_suggested.shape}"
                )
                print(f"[WARNING] ⚠️ Clearing action history")
                self.action_history.clear()

        self.action_history.append(delta_suggested)

        # 安全計算平均值
        try:
            delta_suggested_smoothed = np.mean(list(self.action_history), axis=0)
        except ValueError as e:
            print(f"[ERROR] ❌ Failed to compute smoothed delta: {e}")
            print(f"[ERROR]    Clearing action history and using current delta")
            self.action_history.clear()
            self.action_history.append(delta_suggested)
            delta_suggested_smoothed = delta_suggested

        # 3. 用 XGBoost 預測結果
        print("[DEBUG] ⏳ Running XGBoost prediction...")
        predicted_y_after_move = self.simulator.predict_next_y(row)
        print(f"[DEBUG] ✅ XGBoost prediction complete: {predicted_y_after_move}")

        # 4. SHAP 及時歸因分析（解釋為什麼預測是這個值）
        current_top_influencers = []
        smoothed_top_influencers = []

        if self.explainer:
            print("[DEBUG] ⏳ Running SHAP analysis...")
            # SHAP 使用與 XGBoost 相同的輸入：所有 predFeatures (338個)
            # 使用 simulator.feature_names 從 row 中提取所有特徵
            if self.simulator.feature_names:
                current_state_xgb = np.array(
                    [row[f] for f in self.simulator.feature_names]
                ).reshape(1, -1)
                print(f"[DEBUG]    State shape: {current_state_xgb.shape}")
                print(
                    f"[DEBUG]    Expected features: {len(self.simulator.feature_names)}"
                )

                print("[DEBUG]    Calling explainer.shap_values()...")
                try:
                    shap_output = self.explainer.shap_values(current_state_xgb)
                    print(f"[DEBUG]    SHAP output received, type: {type(shap_output)}")

                    current_shap_v = (
                        shap_output[0]
                        if isinstance(shap_output, list)
                        else shap_output[0]
                    )
                    print("[DEBUG] ✅ SHAP values computed")

                    # 4b. 計算平滑 SHAP
                    self.shap_history.append(current_shap_v)
                    shap_v_avg = np.mean(list(self.shap_history), axis=0)

                    feat_names = self.simulator.feature_names

                    def get_influencers(vals):
                        out = []
                        idx = np.argsort(np.abs(vals))[-3:][::-1]
                        for i in idx:
                            impact = vals[i]
                            feat_name = feat_names[i]  # 直接使用原始特徵名稱
                            dir_str = "[UP]" if impact > 0 else "[DOWN]"
                            out.append(
                                "{} ({} {:.4f})".format(feat_name, dir_str, abs(impact))
                            )
                        return out

                    current_top_influencers = get_influencers(current_shap_v)
                    smoothed_top_influencers = get_influencers(shap_v_avg)
                    print(f"[DEBUG] ✅ SHAP influencers identified")
                except Exception as e:
                    print(f"[ERROR] ❌ SHAP analysis failed: {e}")
                    import traceback

                    traceback.print_exc()
                    # 继续执行，不让 SHAP 错误阻止推理
            else:
                print("[ERROR] ❌ Feature names not available, skipping SHAP analysis")

        # 4. 基礎診斷 (這一部分之後可以餵給 LLM)
        conflict_detected = False
        if not is_locked and predicted_y_after_move is not None:
            improvement = abs(current_y - self.target_center) - abs(
                predicted_y_after_move - self.target_center
            )
            if improvement < 0:
                conflict_detected = True

        # 計算建議的新 action 值（當前值 + delta）
        suggested_actions = np.array(act_vals) + delta_suggested
        suggested_actions_smoothed = np.array(act_vals) + delta_suggested_smoothed

        print(f"[DEBUG] 📊 Recommendation summary:")
        print(f"[DEBUG]    Current actions: {act_vals}")
        print(f"[DEBUG]    Delta suggested: {delta_suggested}")
        print(f"[DEBUG]    Suggested NEW actions: {suggested_actions}")

        result = {
            "current_y": current_y,
            "current_actions": act_vals,  # 新增：當前 action 值
            "iql_action_delta": delta_suggested.tolist(),
            "iql_action_delta_smoothed": delta_suggested_smoothed.tolist(),
            "suggested_actions": suggested_actions.tolist(),  # 新增：建議的新值
            "suggested_actions_smoothed": suggested_actions_smoothed.tolist(),  # 新增：平滑後的建議新值
            "predicted_y_next": predicted_y_after_move,
            "top_influencers": smoothed_top_influencers,  # 預設給 Dashboard 看平滑的
            "current_top_influencers": current_top_influencers,
            "smoothed_top_influencers": smoothed_top_influencers,
            "status": "HOLD"
            if is_locked
            else ("CONFLICT" if conflict_detected else "MOVE"),
            "diagnosis": self._generate_simple_diagnosis(
                current_y, predicted_y_after_move, is_locked, conflict_detected
            ),
        }
        return result

    def _generate_simple_diagnosis(self, curr_y, pred_y, is_locked, is_conflict):
        if is_locked:
            return f"當前數值 {curr_y:.3f} 在安全區間內，建議維持現狀。"

        # 增加防呆：處理 pred_y 為 None 的情況 (模型未完成訓練)
        if pred_y is None:
            return f"診斷中：策略建議執行調整量，但模擬器尚未就緒，無法預測後續趨勢。"

        if is_conflict:
            return f"警報：策略模型建議調整，但模擬器預測調整後數值 ({pred_y:.3f}) 未見明顯改善，可能存在外部噪聲干擾。"

        return (
            f"診斷通過：執行調整後，預計量測值將由 {curr_y:.3f} 改善至 {pred_y:.3f}。"
        )


# --- 測試代碼 ---
if __name__ == "__main__":
    # 這裡可以放一組測試資料驗證雙模型對話
    pass
