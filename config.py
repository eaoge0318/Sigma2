# config.py
import os


# --- 1. 通用訓練設定 (共同停止準則與架構) ---
TRAIN_COMMON = {
    "STABLE_THRESHOLD": 1e-3,
    "REQUIRED_STABLE_COUNT": 5,
    "MAX_EPOCHS": 50,
    "N_STEPS": 500,
    "N_STEPS_PER_EPOCH": 500,
}

# --- 2. 演算法特定設定 (Algorithm-Specific Defaults) ---
ALGO_CONFIGS = {
    "IQL": {
        "batch_size": 1024,
        "actor_learning_rate": 3e-4,
        "critic_learning_rate": 3e-4,
        "expectile": 0.8,
        "weight_temp": 0.5,
        "gamma": 0.99,
        "tau": 0.01,
        "observation_scaler": "Standard",
    },
    "PPO": {
        "batch_size": 64,
        "learning_rate": 3e-4,
        "clip_range": 0.2,
        "ent_coef": 0.01,
        "gamma": 0.99,
    },
}

# --- 3. 預測配置設定 (Prediction Algorithm Defaults) ---
PRED_ALGO_CONFIGS = {
    "XGBoost": {
        "max_depth": 6,
        "learning_rate": 0.1,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "n_estimators": 100,
        "early_stop": 10,
    },
    "RandomForest": {"n_estimators": 100, "max_depth": 10, "min_samples_split": 2},
    "LightGBM": {"num_leaves": 31, "learning_rate": 0.05, "feature_fraction": 0.9},
}

DEFAULT_ALGO = "IQL"
DEFAULT_PRED_ALGO = "XGBoost"

# --- 邏輯優化 ---
SHAP_SMOOTHING_WINDOW = 10

# --- LLM 配置 ---
LLM_API_URL = "http://10.10.20.214:11434/api/chat"
LLM_MODEL = "gemma3:27b-it-qat"

# --- 儲存與監控 ---
BASE_STORAGE_DIR = "workspace"
DASHBOARD_DIR = "monitor_dashboard"
API_PORT = 8001

# --- 初始化基本目錄 ---
os.makedirs(DASHBOARD_DIR, exist_ok=True)
os.makedirs(BASE_STORAGE_DIR, exist_ok=True)
