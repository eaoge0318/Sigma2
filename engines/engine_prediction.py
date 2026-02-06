import sys
import os

# 修正導入路徑，確保能找到 root 的 config 與 core_logic
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import xgboost as xgb
from core_logic import DataPreprocess
import joblib
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, r2_score
from datetime import datetime
import json
import numpy as np
import config  # 匯入全域配置


def run_parameterized_xgb(
    data_path, target_col, features, hyperparams, common_config, save_dir="model"
):
    """
    執行參數化的引擎訓練 (以 XGBoost 為主，支援 UI > config.py > Hardcoded 優先級)
    """
    # 取得全域預設配置 (優先找對應演算法，若無則回退)
    algo_defaults = config.PRED_ALGO_CONFIGS.get("XGBoost", {})

    # 整合 hyperparams 與 common_config
    n_estimators = int(
        common_config.get("n_estimators") or algo_defaults.get("n_estimators", 100)
    )
    early_stop = int(
        common_config.get("early_stop") or algo_defaults.get("early_stop", 10)
    )
    val_split = float(common_config.get("val_split") or 0.2)

    print("DEBUG: Starting prediction engine training task...")
    print(
        f"DEBUG: target={target_col}, features_count={len(features)}, val_split={val_split}"
    )

    # 1. 載入並整理資料
    df, _ = DataPreprocess.get_processed_data_and_cols(data_path)

    # 2. 構建訓練矩陣
    X = df[features].values.astype(np.float32)
    y = df[target_col].values.astype(np.float32)

    # 3. 訓練/測試集拆分 (參考介面設定的驗證比例)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=val_split, random_state=42
    )

    # 4. 初始化模型 (參數優先級連動)
    model = xgb.XGBRegressor(
        n_estimators=n_estimators,
        max_depth=int(
            hyperparams.get("max_depth") or algo_defaults.get("max_depth", 6)
        ),
        learning_rate=float(
            hyperparams.get("learning_rate") or algo_defaults.get("learning_rate", 0.1)
        ),
        subsample=float(
            hyperparams.get("subsample") or algo_defaults.get("subsample", 0.8)
        ),
        colsample_bytree=float(
            hyperparams.get("colsample_bytree")
            or algo_defaults.get("colsample_bytree", 0.8)
        ),
        objective="reg:squarederror",
        tree_method="hist",
        n_jobs=-1,
        early_stopping_rounds=early_stop,
    )

    # 5. 執行訓練
    model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)

    # 6. 評估結果
    y_pred = model.predict(X_test)
    r2 = r2_score(y_test, y_pred)
    mae = mean_absolute_error(y_test, y_pred)

    print(f"[SUCCESS] Training completed | R2: {r2:.4f} | MAE: {mae:.6f}")

    # 7. 存檔
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_name = f"pred_run_{timestamp}"
    run_path = os.path.join(save_dir, run_name)
    os.makedirs(run_path, exist_ok=True)

    model_path = os.path.join(run_path, "model.json")
    model.save_model(model_path)
    joblib.dump(features, os.path.join(run_path, "feature_names.pkl"))

    return {
        "status": "success",
        "r2": r2,
        "mae": mae,
        "model_path": model_path,
        "run_path": run_path,
    }


def run_from_json(json_path):
    """從 JSON 配置文件啟動訓練"""
    if not os.path.exists(json_path):
        print(f"Error: Config file not found {json_path}")
        return

    with open(json_path, "r", encoding="utf-8") as f:
        job_config = json.load(f)

    # 核心參數：必須由 UI 提供，否則直接報錯 (不再回退到 config.py)
    data_path = job_config.get("data_full_path") or job_config.get("filename")
    target_col = job_config.get("goal")
    features = job_config.get("features")

    if not data_path or not target_col or not features:
        raise ValueError(
            "Missing modeling info (file/target/features). Please select in UI before training."
        )

    # 執行訓練
    save_dir = job_config.get("bundles_dir", "model")
    result = run_parameterized_xgb(
        data_path=data_path,
        target_col=target_col,
        features=features,
        hyperparams=job_config.get("hyperparams", {}),
        common_config=job_config.get("common", {}),
        save_dir=save_dir,
    )

    # 回寫狀態到 JSON (供 UI 顯示)
    if result and result.get("status") == "success":
        job_config["status"] = "completed"
        job_config["r2"] = result.get("r2")
        job_config["mae"] = result.get("mae")
        job_config["run_path"] = result.get("run_path")

        # 關鍵：在模型資料夾內也存一份「暫存緩存」，確保資料連動
        run_config_path = os.path.join(result.get("run_path"), "config.json")
        with open(run_config_path, "w", encoding="utf-8") as f:
            json.dump(job_config, f, ensure_ascii=False, indent=4)

        # 同步回寫到全域 configs 目錄 (供列表顯示)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(job_config, f, ensure_ascii=False, indent=4)

    return result


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        # 支援從命令行傳入 json 路徑： python engine_prediction.py config.json
        run_from_json(sys.argv[1])
    else:
        print(
            "Prediction Engine Ready. Usage: python engine_prediction.py <config_json_path>"
        )
