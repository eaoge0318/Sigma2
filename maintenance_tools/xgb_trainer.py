# xgb_trainer.py
import pandas as pd
import numpy as np
import xgboost as xgb
import DataPreprocess
import config
import os
import joblib
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, r2_score


def train_xgb_simulator():
    # 1. 載入並整理資料
    print("正在從資料集中學習因果規律...")
    df, all_cols = DataPreprocess.get_processed_data_and_cols(config.RAW_DATA_PATH)

    bg_features = [
        c for c in all_cols if c not in config.ACTION_FEATURES + [config.MEASURE_COL]
    ]

    # 2. 構建「因果」特徵矩陣
    # X: [State_t, Action_delta_t]
    # y: [Measure_t+1]
    X_list, y_list = [], []

    for i in range(len(df) - 1):
        row, row2 = df.iloc[i], df.iloc[i + 1]

        # 取得動作位移量
        delta_a = (
            row2[config.ACTION_FEATURES].values - row[config.ACTION_FEATURES].values
        ).astype(np.float32)

        # 特徵組合: 背景 + 當前參數 + 調整量
        features = np.concatenate(
            [
                row[bg_features].values.astype(np.float32),
                row[config.ACTION_FEATURES].values.astype(np.float32),
                delta_a,
            ]
        )

        X_list.append(features)
        y_list.append(row2[config.MEASURE_COL])

    X = np.array(X_list)
    y = np.array(y_list)

    # 特徵名稱 (用於後續 LLM 分析重要性)
    feature_names = (
        bg_features
        + config.ACTION_FEATURES
        + [f"delta_{a}" for a in config.ACTION_FEATURES]
    )

    # 3. 訓練模型
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.15, random_state=42
    )

    print(f"正在訓練 XGBoost 模擬器... (樣本數: {len(X)})")
    model = xgb.XGBRegressor(
        n_estimators=1000,
        max_depth=7,
        learning_rate=0.03,
        objective="reg:squarederror",
        tree_method="hist",
        n_jobs=-1,
    )

    model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=200)

    # 4. 評估與存檔
    y_pred = model.predict(X_test)
    print(f"\n📊 模擬器性能報告:")
    print(f"   準確度 (R2 Score): {r2_score(y_test, y_pred):.4f}")
    print(f"   平均誤差 (MAE): {mean_absolute_error(y_test, y_pred):.6e}")

    save_path = os.path.join(config.MODEL_SAVE_DIR, "xgb_simulator.json")
    model.save_model(save_path)
    joblib.dump(feature_names, os.path.join(config.MODEL_SAVE_DIR, "xgb_features.pkl"))
    print(f"💾 模擬器已存檔: {save_path}")


if __name__ == "__main__":
    train_xgb_simulator()
