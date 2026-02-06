# xgb_predict.py
import os
import joblib
import numpy as np
import xgboost as xgb
import config


class XGBSimulator:
    def __init__(self, model_dir=None):
        if model_dir is None:
            model_dir = os.path.join(config.BASE_STORAGE_DIR, "default", "bundles")

        self.model_path = os.path.join(model_dir, "xgb_simulator.json")
        # 兼容性檢查：也檢查 model.json (新的引擎命名)
        if not os.path.exists(self.model_path):
            alt_path = os.path.join(model_dir, "model.json")
            if os.path.exists(alt_path):
                self.model_path = alt_path

        self.feature_names_path = os.path.join(model_dir, "xgb_features.pkl")
        # 兼容性檢查：也檢查 feature_names.pkl
        if not os.path.exists(self.feature_names_path):
            alt_feat_path = os.path.join(model_dir, "feature_names.pkl")
            if os.path.exists(alt_feat_path):
                self.feature_names_path = alt_feat_path

        self.model = None
        self.feature_names = None
        self.load_model()

    def load_model(self):
        """載入 XGBoost 模型與特徵列表"""
        if not os.path.exists(self.model_path):
            print(f"⚠️ 找不到模型檔案: {self.model_path}。請先執行訓練腳本產生模型。")
            return

        self.model = xgb.XGBRegressor()
        self.model.load_model(self.model_path)

        if os.path.exists(self.feature_names_path):
            self.feature_names = joblib.load(self.feature_names_path)
            print(f"✅ XGBoost 模擬器載入成功。特徵維度: {len(self.feature_names)}")

    def predict_next_y(self, row_data, current_actions=None, delta_actions=None):
        """
        輸入完整的 row 數據,預測下一步的 y (量測值)

        Args:
            row_data: 完整的數據行 (dict 或 Series),包含所有 predFeatures
            current_actions: (已棄用,保留以兼容舊代碼)
            delta_actions: (已棄用,保留以兼容舊代碼)

        Returns:
            float: 預測的 y 值
        """
        if self.model is None:
            return None

        # 使用 feature_names 從 row_data 中提取特徵
        if self.feature_names is None:
            print("[ERROR] ❌ Feature names not loaded!")
            return None

        try:
            # 從 row_data 中提取所有需要的特徵
            features = np.array([row_data[f] for f in self.feature_names]).reshape(
                1, -1
            )

            print(f"[DEBUG] XGBoost input shape: {features.shape}")
            print(f"[DEBUG] XGBoost expected features: {len(self.feature_names)}")

            # 執行預測
            y_pred = self.model.predict(features)[0]
            return float(y_pred)
        except KeyError as e:
            print(f"[ERROR] ❌ Missing feature in row_data: {e}")
            print(f"[ERROR]    Available keys: {list(row_data.keys())[:10]}...")
            return None
        except Exception as e:
            print(f"[ERROR] ❌ XGBoost prediction failed: {e}")
            import traceback

            traceback.print_exc()
            return None


# --- 測試預測功能 ---
if __name__ == "__main__":
    # 這裡放一個簡單的範例展示如何呼叫
    simulator = XGBSimulator()

    if simulator.model:
        # 模擬一組測試資料 (需符合您 config 中的 bg_features 數量)
        # 假設 bg 為 337 維 (這裡用隨機數代替)
        dummy_bg = [0.0] * 337
        dummy_current = [540.0, 57.0, 3.55]  # 範例控制值
        dummy_delta = [2.0, -1.0, 0.05]  # 範例調整量

        predicted_y = simulator.predict_next_y(dummy_bg, dummy_current, dummy_delta)
        print("-" * 30)
        print("🔮 預測結果:")
        print(f"   輸入動作增量: {dummy_delta}")
        print(f"   預測未來的 {config.MEASURE_COL}: {predicted_y:.4f}")
        print("-" * 30)
