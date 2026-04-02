# config.py — 所有設定統一由 settings.json 管理，此檔僅負責載入並輸出 Python 常數
import os
import json
from pathlib import Path

def _load() -> dict:
    p = Path(__file__).parent / "settings.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}

_s = _load()

def _bool_env(key: str, default: bool) -> bool:
    val = os.environ.get(key)
    if val is None:
        return default
    return val.strip().lower() not in ("false", "0", "no", "off")

# --- 功能開關 ---
_feat = _s.get("features", {})
FEATURES = {k: _bool_env(f"SIGMA_FEATURE_{k.upper()}", v) for k, v in _feat.items()}

# --- LLM ---
_llm = _s.get("llm", {})
LLM_API_URL = os.environ.get("SIGMA_LLM_URL",   _llm.get("api_url", "http://localhost:8000/v1/chat/completions"))
LLM_MODEL   = os.environ.get("SIGMA_LLM_MODEL", _llm.get("model",   ""))

# --- 儲存與服務 ---
_sto = _s.get("storage", {})
BASE_STORAGE_DIR = os.environ.get("SIGMA_STORAGE_DIR",    _sto.get("base_dir",      "workspace"))
DASHBOARD_DIR    = os.environ.get("SIGMA_DASHBOARD_DIR",  _sto.get("dashboard_dir", "monitor_dashboard"))
API_PORT         = int(os.environ.get("SIGMA_API_PORT",   str(_sto.get("api_port",  8001))))

# --- 訓練通用設定 ---
_tr = _s.get("train", {})
TRAIN_COMMON = {
    "STABLE_THRESHOLD":    _tr.get("stable_threshold",    1e-3),
    "REQUIRED_STABLE_COUNT": _tr.get("required_stable_count", 5),
    "MAX_EPOCHS":          _tr.get("max_epochs",          50),
    "N_STEPS":             _tr.get("n_steps",             500),
    "N_STEPS_PER_EPOCH":   _tr.get("n_steps_per_epoch",   500),
}

# --- 強化學習演算法 ---
_algo = _s.get("algo", {})
DEFAULT_ALGO = _algo.get("default", "IQL")
ALGO_CONFIGS = {k: v for k, v in _algo.items() if not k.startswith("_") and k != "default"}

# --- 預測演算法 ---
_pred = _s.get("pred_algo", {})
DEFAULT_PRED_ALGO = _pred.get("default", "XGBoost")
PRED_ALGO_CONFIGS = {k: v for k, v in _pred.items() if not k.startswith("_") and k != "default"}

# --- 其他 ---
SHAP_SMOOTHING_WINDOW = _s.get("shap_smoothing_window", 10)

# --- RAG ---
_rag = _s.get("rag", {})
RAG_EMBEDDING_URL        = os.environ.get("SIGMA_RAG_EMBED_URL",  _rag.get("embedding_url",     ""))
RAG_CHROMA_PATH          = os.environ.get("SIGMA_RAG_PATH",       _rag.get("chroma_path",       "workspace/rag_index"))
RAG_TOP_K                = int(os.environ.get("SIGMA_RAG_TOP_K",  str(_rag.get("top_k",         3))))
RAG_SIMILARITY_THRESHOLD = float(os.environ.get("SIGMA_RAG_THRESHOLD", str(_rag.get("similarity_threshold", 0.65))))
RAG_EMBEDDING_MODEL      = os.environ.get("SIGMA_RAG_EMBED_MODEL", _rag.get("embedding_model",  "intfloat/multilingual-e5-base"))
RAG_COLLECTION_PREFIX    = os.environ.get("SIGMA_RAG_COL_PREFIX",  _rag.get("collection_prefix","kbv3"))
RAG_USE_GPU              = _rag.get("use_gpu", False)

# --- Web Search ---
_ws = _s.get("web_search", {})
WEB_SEARCH_ENDPOINT = os.environ.get(
    "SIGMA_WEB_SEARCH_ENDPOINT",
    _ws.get("endpoint", "https://tw.search.yahoo.com/search"),
)
WEB_SEARCH_DEFAULT_MAX_RESULTS = int(os.environ.get(
    "SIGMA_WEB_SEARCH_DEFAULT_MAX_RESULTS",
    str(_ws.get("default_max_results", 5)),
))
WEB_SEARCH_MAX_RESULTS_LIMIT = int(os.environ.get(
    "SIGMA_WEB_SEARCH_MAX_RESULTS_LIMIT",
    str(_ws.get("max_results_limit", 10)),
))
WEB_SEARCH_ALLOWED_DOMAINS = _ws.get("allowed_domains", [])

# --- 進階 ---
_adv = _s.get("advanced", {})
LLM_IMAGE_LIMIT = int(_adv.get("llm_image_limit", 0))

# --- 初始化基本目錄 ---
os.makedirs(DASHBOARD_DIR, exist_ok=True)
os.makedirs(BASE_STORAGE_DIR, exist_ok=True)
