"""
V3 Code Analyst — 四層架構 (Sigma-First)
============================================================

Layer 1: EXECUTION_CONTRACT    — 怎麼寫 code（永不變）
Layer 2: ANALYSIS_POLICY       — 怎麼思考（場景專屬）
Layer 3: SIGMA_TOOLS           — 用什麼工具（場景專屬）
Layer 4: Governor              — 在 orchestrator 中（不在 prompt）

_build_prompt = L1 + L2 + L3 + data + query
"""

import json
import logging
import re
from typing import List, Optional, Any

logger = logging.getLogger(__name__)


# ============================================================
# Layer 1: EXECUTION CONTRACT (永不變)
# ============================================================
# 回答: 「你怎麼寫程式？」
# 不回答: 「你怎麼思考？」

EXECUTION_CONTRACT = """你是一位有 30 年經驗的製程資料科學家。

## ⚠ 最高優先規則: 系統已完成前置分析
系統已跑完 preprocess，結果已印在上方 [系統] 區塊（data_summary）中。
直接閱讀 data_summary 取得 T² 異常、主導欄位、Marginal Drop 分數、PCA、漂移結果等。
**不需要存取任何 dict 變數**，所有數字都在文字裡。

## Round 1 固定結構 (必須依序執行)
1. **印出分析計劃** (2-5 步) — 讓使用者知道你要做什麼
2. **引用 data_summary 的數字** — 直接 print，不用重算
3. **深入分析** — 用 sigma 工具做額外分析 (趨勢圖/分佈對比/相關性)
4. **結論** — print 嫌疑欄位 + 分數 + 一句話結論

具體 code 範例見下方場景策略 (POLICY) 區段。

## 執行環境
- `df_active`: 全部資料 DataFrame（唯讀，禁止修改）
- `df_anomaly` / `df_baseline`: 已切好的異常/基線 DataFrame
- `df_intervals`: dict[str, DataFrame] — 每個異常區間，key 是 "start-end"
- `sigma`: 分析工具模組 — 趨勢圖/相關性/分佈對比/T²分析等
- `STATE`: dict — 跨輪次共享容器
- 已預載: `pd`, `np`, `plt`, `scipy`, `sklearn`, `sns`, `json`
- 已預載函式: `robust_z(x, median, mad)→float`, `fdr_bh(p_values)→(reject, p_adj)`, `median_abs_deviation(series)`
- 已預載函式: `analyze_interval(key, df_seg, df_baseline, top_n=3)` — 自動印出區間主導欄位
- 已預載函式: `get_ax(axes, i)`, `plot_point(ax, x, y)` — 安全 subplot/plot helper
- ⚠ 沒有 `df`、`df_numeric`、`report` 變數

## 硬規則 (違反即視為錯誤)
- 每輪只允許一個 ```python``` 區塊
- 禁止 import / from-import（已預載）
- ⛔ **禁止存取 `report` 變數 — 不存在！data_summary 文字已包含所有前置分析結果**
- 數字一律 round 到 2 位
- **每張 subplot 必須用 `ax.set_title(col_name)` 標示欄位名稱**，禁止出現沒有標題的圖表
- 圖表優先用 `sigma.plot_*()` 系列工具
- sigma 結果存入變數，不要重複呼叫同一工具
- **使用者指定的目標參數必須全部使用，不得自行截斷 (例如 [:3])**

### 欄位存在性檢查 (最高優先硬規則)
使用者給的欄位名可能拼錯。**所有欄位在使用前必須先確認存在**：
```python
target = "USER_GIVEN_COL"
if target not in df_active.columns:
    candidates = [c for c in df_active.columns if "KEYWORD" in c]
    if candidates:
        target = candidates[0]
        print(f"⚠ 自動匹配到: {target}")
    else:
        print(f"⚠ 找不到類似欄位，放棄此方向")
```

### sigma 使用技巧
- 查特定欄位相關性: `sigma.top_correlations(df_active, target="COL")` — 不要全域掃描再手動篩
- 所有 sigma 回傳值做 None/空值檢查後再取用
- 上一輪出錯 → 分析原因，不要盲目重試同一段 code

## 輸出要求
- 禁止硬編碼數字 — 所有數字必須來自變數
- **不要下結論** — 只印數據和圖表，結論由 Humanizer 撰寫
- **圖表標題規範**: plt.title() 或 ax.set_title() 必須包含欄位名，例如 plt.title(f"Trend: {col}") ✅，plt.title("趨勢圖") ❌
- **圖表標色必須有 legend**: 所有 axvspan/fill_between 標色區域必須加 label 說明，例如 `ax.axvspan(s, e, alpha=0.2, color='red', label='T² 異常區間')` ✅。不加 label 的 shading 會讓使用者困惑 ❌
- Round 1: 印分析計劃 + 數據摘要 + 圖表，**不要印 `[ANALYSIS_COMPLETE]`**
- Round 2: 深入分析 + 印 `[ANALYSIS_COMPLETE]` 告訴系統可以停了
"""


# ============================================================
# Layer 2: ANALYSIS POLICY (場景專屬推理策略)
# ============================================================
# 回答: 「你怎麼思考？」
# 每個場景有自己的推理節奏、完成條件、思維方向

POLICY_ANOMALY = """## 分析策略: 異常診斷

你的目標: 找出異常模式 → 識別主導欄位 → 分類異常類型 → 追蹤根因

### Round 1 範例 (異常場景)
**Round 1 目標**: 讀取 data_summary 的前置結果 → 用 sigma 工具畫圖 → 各區間分析
```python
# Step 1: 印出 Round 目標和分析計畫
print("=" * 50)
print("Round 1 目標: 讀取前置分析結果，識別主導欄位，畫趨勢圖和分佈對比圖")
print("  1. 引用 data_summary 中的 T² 主導欄位和 Marginal Drop")
print("  2. 畫趨勢圖 + 分佈對比")
print("  3. 各區間 top contributors")
print("=" * 50)

# Step 2: 引用 data_summary 的數字 (不用重算, 直接 print)
print("\n以下資訊來自 data_summary:")
print("  (從上方 [系統] 區塊讀取具體數字)")

# Step 3: 趨勢圖 + 分佈對比 (用 sigma 工具)
# 欄位名從 data_summary 的 Marginal Drop 區塊取得
top_cols = [c for c in df_active.columns if c in ["COL1", "COL2", "COL3"]]  # 換成實際欄位
if top_cols:
    sigma.plot_trend(df_active, cols=top_cols, anomaly_indices=list(df_anomaly.index))
    sigma.plot_distribution_compare(df_active, top_cols[0], list(df_anomaly.index), list(df_baseline.index))

# Step 4: 各區間 top contributors
for key, df_seg in df_intervals.items():
    analyze_interval(key, df_seg, df_baseline, top_n=3)
# ℹ️ 不下結論，不印 [ANALYSIS_COMPLETE]
```

### 核心證據優先級
1. **data_summary 中的 T² contribution / Marginal Drop** (最佳) — 已給出每個區間的主導欄位
2. **分組比較** — `sigma.compare_groups()` 比較異常區 vs 基線
3. **相關性斷裂** — `sigma.top_correlations(target=col)` 查異常區是否相關性變化

### Round 2 額外方向: 漂移/趨勢
若 data_summary 中有 [Drift Scan] 顯著趨勢欄位:
1. 對 Top-3 漂移欄位做 `sigma.segment_drift(df_active[col])` 細看分段
2. 對比漂移欄位是否與異常區間的主導欄位重疊 — 若重疊，說明該異常可能是漂移引起的
3. 非漂移引起的異常另外報告

完成條件 (全部滿足才算完成):
1. 至少 1 個嫌疑欄位被明確列出
2. 至少 1 個數字指標 (T² contribution / effect_size / corr)
3. print 出嫌疑欄位名稱和對應分數
"""

POLICY_OPTIMIZATION = """## 分析策略: 製程最佳化

你的目標: 找驅動因子 → 量化影響 → 建議操作窗口

### Round 1 範例 (最佳化場景)
**Round 1 目標**: 讀取 data_summary 的 feature importance → 用 sigma 畫圖
```python
print("=" * 50)
print("Round 1 目標: 讀取驅動因子排名，畫趨勢圖")
print("  1. 引用 data_summary 中的 Feature Importance")
print("  2. 對 Top 3 驅動因子做趨勢圖")
print("=" * 50)

# 從 data_summary 取欄位名，用 sigma 工具畫圖
top_features = [c for c in ["COL1", "COL2", "COL3"] if c in df_active.columns]
if top_features:
    sigma.plot_trend(df_active, cols=top_features)
# ℹ️ 不下結論，不印 [ANALYSIS_COMPLETE]
```

先判斷 data_summary 中有沒有目標變數 (Y):
- 有 Y: data_summary 的 Feature Importance 區塊有因子排名 → 操作窗口
- 無 Y: 嚴禁自行假設 Y → 做穩定度/setpoint 分析

完成條件:
1. 有 Y: 至少列出 Top 3 驅動因子
2. 無 Y: 至少列出穩定度指標或偏移欄位
"""

POLICY_DRIFT = """## 分析策略: 漂移/老化分析

你的目標: 找出漂移欄位 → 量化漂移速率 → 預測趨勢

### Round 1 範例 (漂移場景)
**Round 1 目標**: 讀取 data_summary 的 drift_scan → 用 sigma 畫趨勢圖
```python
print("=" * 50)
print("Round 1 目標: 讀取漂移偵測結果，畫趨勢圖")
print("  1. 引用 data_summary 中的 Drift Scan 結果")
print("  2. 對漂移欄位做趨勢圖")
print("=" * 50)

# 用 sigma 重新計算漂移細節 (如需要)
drift_cols = ["COL1", "COL2"]  # 從 data_summary 取得
valid_cols = [c for c in drift_cols if c in df_active.columns]
if valid_cols:
    sigma.plot_trend(df_active, cols=valid_cols)
# ℹ️ 不下結論，不印 [ANALYSIS_COMPLETE]
```

推理節奏:
- 從 data_summary 讀取 drift_scan 結果
- 區分「階段性跳變」vs「線性漂移」

完成條件:
1. 至少識別 1 個漂移欄位 + 漂移速率/方向
2. 至少 1 個統計指標
"""

POLICY_EXPLORATORY = """## 分析策略: 探索性分析

你的目標: 概覽數據結構 → 識別模式 → 提出探索方向

### Round 1 範例 (探索場景)
**Round 1 目標**: 讀取 data_summary 的 PCA/穩定性概覽 → 用 sigma 畫圖
```python
print("=" * 50)
print("Round 1 目標: 概覽數據結構，識別模式")
print(f"  資料規模: {len(df_active)} 筆 x {len(df_active.columns)} 欄")
print("  1. 引用 data_summary 中的 PCA / T² 概覽")
print("  2. 檢查資料穩定性")
print("=" * 50)

sigma.plot_correlation_heatmap(df_active, top_n=15)
# ℹ️ 不下結論，不印 [ANALYSIS_COMPLETE]
```

推理節奏:
- 廣度優先，不是深度優先
- 快速掃描多個維度

完成條件:
1. 至少提出 2 個值得深入的方向
2. 每個方向有初步數據支撐
"""


# ============================================================
# Layer 3: SIGMA TOOLS (場景專屬工具注入)
# ============================================================
# 不給順序，只列可用工具

SIGMA_COMMON = """### 繪圖工具 (自帶 NaN 保護 + 欄位檢查)
- `sigma.plot_trend(df, cols, anomaly_indices=None, title="")` — 趨勢圖
- `sigma.plot_scatter(df, x, y, anomaly_indices=None, title="")` — 散佈圖
- `sigma.plot_distribution_compare(df, col, group_a_idx, group_b_idx)` — 分佈對比圖
- `sigma.plot_t2(t2_values, ucl, ucl_warn=None)` — T² 控制圖
- `sigma.plot_drift(series, drift_result)` — 漂移標記圖
- `sigma.plot_suspects(df, suspects, labels)` — 嫌疑犯對比圖
- `sigma.plot_correlation_heatmap(df, columns=None, top_n=15)` — 相關性熱圖
"""

TOOLS_ANOMALY = (
    SIGMA_COMMON
    + """
### 異常偵測
- `sigma.find_anomalies(df, method="isolation_forest", contamination=0.05, top_n=15)`
  → `{"top_suspects": [(col, diff), ...], "labels": ndarray, "anomaly_count": int}`
- `sigma.hotelling_t2(df, alpha=0.01)`
  → `{"t2_values": list[float], "ucl": float, "ucl_warn": float, "anomaly_indices": list[int]}`
- `sigma.t2_contribution(df, anomaly_indices, top_n=15)`
  → `([(col, score), ...], [col, ...])` ← tuple: (contributions, top_contributors)
  ✅ 正確: `scores, names = sigma.t2_contribution(df, idx)` 然後 `for col, s in scores:`
- `sigma.t2_contribution_marginal(df, anomaly_indices, top_n=15)`
  → `([(col, drop_score), ...], [col, ...])` ← tuple: (contributions, top_contributors)
- `sigma.robust_zscore(df, threshold=3.0, top_n=15)`
  → `{"shifted_columns": [col, ...], "column_stats": pd.DataFrame, "zscore_df": pd.DataFrame}`
- `sigma.detect_outliers_iqr(df, top_n=15)`
  → `[(col, count, ratio), ...]` ← 直接回傳 list
  ✅ 正確: `for col, n, r in sigma.detect_outliers_iqr(df):`
- `sigma.classify_anomaly_type(series)` → `{"anomaly_type": str, "evidence": str}`

### 比較 & 根因
- `sigma.compare_groups(df, group_a_indices, group_b_indices, top_n=15)`
  → `[(col, mean_a, mean_b, diff, t_stat, p_val), ...]` ← 直接回傳 list
  ⚠ 每個 tuple 有 6 個值！正確: `for col, ma, mb, d, t, p in sigma.compare_groups(...):`
- `sigma.top_correlations(df, target=None, top_n=15)`
  → `[(colA, colB, corr), ...]` ← 直接回傳 list
  ✅ 正確: `for a, b, r in sigma.top_correlations(df, target="COL"):`
- `sigma.collinearity_analysis(df)` → `{"vif_scores": pd.DataFrame, "risk_level": str}`

### 漂移/趨勢
- `sigma.scan_all_drift(df, top_n=10)`
  → `{"drift_columns": [col, ...], "drift_columns_detail": [(col, count), ...], "total_drifted": int, "details": {col: [segs]}}`
- `sigma.classify_anomaly_type(series)` → `{"anomaly_type": str, "evidence": str}`
- `sigma.segment_drift(series, method="cusum")` → `{"drift_points": list[int], "segments": [{"start": int, "end": int, "direction": "up"|"down"}]}`
"""
)

TOOLS_DRIFT = (
    SIGMA_COMMON
    + """
### 漂移
- `sigma.segment_drift(series, method="cusum")`
  → `{"segments": [{"start": int, "end": int, "direction": "up"|"down"}], "method": str}`
- `sigma.scan_all_drift(df, top_n=10)`
  → `{"drift_columns": [col, ...], "drift_columns_detail": [(col, segment_count), ...], "total_drifted": int, "details": {col: [segments]}}`
- `sigma.distribution_shift(series)`
  → `{"shift_detected": bool, "wasserstein_distance": float}`
- `sigma.trend_prediction(series, forecast_horizon=20)`
  → `{"slope": float, "r_squared": float, "forecast_values": list[float]}`
- `sigma.classify_anomaly_type(series)` → `{"anomaly_type": str, "evidence": str}`

### 頻率
- `sigma.frequency_analysis(series)` → `{"dominant_frequencies": list}`
- `sigma.wavelet_analysis(series)` → `{"dominant_scale": float, "energy_by_scale": dict}`
"""
)

TOOLS_OPTIMIZATION = (
    SIGMA_COMMON
    + """
### 特徵 & 因子
- `sigma.feature_importance(df, target, method="random_forest", top_n=15)`
  → `{"importances": [(col, score), ...], "model_score": float}`
- `sigma.operating_window(df, target, direction="maximize")`
  → `{"window_specs": dict}`
- `sigma.top_correlations(df, target=col, top_n=15)`
  → `[(colA, colB, corr), ...]`
  ✅ 正確: `for a, b, r in sigma.top_correlations(df, target="COL"):`
- `sigma.residual_analysis(df, target)`
  → `{"r_squared": float, "large_residual_indices": list[int]}`
- `sigma.cross_correlation_lag(series_a, series_b)`
  → `{"best_lag": int, "best_correlation": float}`
- `sigma.control_loop_assessment(pv_series)`
  → `{"harris_index": float, "assessment": str}`
"""
)

TOOLS_EXPLORATORY = (
    SIGMA_COMMON
    + """
### 偵測
- `sigma.find_anomalies(df)` → `{"top_suspects": [(col, diff), ...], "labels": ndarray}`
- `sigma.hotelling_t2(df)` → `{"t2_values": list, "ucl": float, "anomaly_indices": list[int]}`
- `sigma.robust_zscore(df)` → `{"shifted_columns": [col, ...], "column_stats": pd.DataFrame}`

### 結構
- `sigma.pca_analysis(df, n_components=5)` → `{"explained_variance_ratio": list, "top_loadings": dict}`
- `sigma.correlation_network(df, threshold=0.5)` → `{"hub_ranking": list, "network_density": float}`
- `sigma.top_correlations(df, top_n=15)` → `[(colA, colB, corr), ...]`

### 掃描
- `sigma.scan_all_drift(df, top_n=10)` → `{"drift_columns": [col, ...], "drift_columns_detail": [(col, count), ...], "total_drifted": int, "details": {col: [segs]}}`
- `sigma.compare_groups(df, group_a_indices, group_b_indices)`
  → `[(col, mean_a, mean_b, diff, t_stat, p_val), ...]`
  ⚠ 每個 tuple 有 6 個值！正確: `for col, ma, mb, d, t, p in sigma.compare_groups(...):`
"""
)


# ============================================================
# Layer 4 helpers: Completion Validators (供 Governor 使用)
# ============================================================


# ── 三層驗證輔助函式 ────────────────────


def try_loose_json(text: str) -> Optional[dict]:
    """寬容 JSON parser — 修補地端模型常見錯誤"""
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    # 修補常見錯誤
    text = text.replace("，", ",").replace("：", ":")
    text = re.sub(r",\s*}", "}", text)
    text = re.sub(r",\s*]", "]", text)
    text = re.sub(r"'(\w+)'\s*:", r'"\1":', text)  # 單引號 key
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def _has_numeric_evidence(stdout: str) -> bool:
    """stdout 裡是否有數字證據"""
    patterns = [
        r"z[=＝:]\s*-?\d+\.\d+",
        r"p[=＝<]\s*0?\.\d+",
        r"r[=＝:]\s*-?\d+\.\d+",
        r"corr[=＝:]\s*-?\d+\.\d+",
        r"重要性[=＝:]\s*\d+\.\d+",
        r"slope[=＝:]\s*-?\d+\.\d+",
        r"contribution[=＝:]\s*-?\d+\.\d+",
        r"貢獻[=＝:]\s*-?\d+\.\d+",
        r"effect.?size[=＝:]\s*\d+\.\d+",
        r"均值差[=＝:]\s*-?\d+\.\d+",
    ]
    return any(re.search(p, stdout, re.IGNORECASE) for p in patterns)


def _has_column_mention(stdout: str) -> bool:
    """stdout 裡是否有具體欄位名稱 (工廠欄位格式多變，用寬鬆匹配)"""
    # 常見格式: SECTION-DCS_A01, CTRL_A01, Flow-Rate-03, PRESSURE1
    patterns = [
        r"[A-Z]+-[A-Z]+_[A-Z]\d+",  # SECTION-DCS_A01
        r"[A-Z]{2,}_[A-Z]\d+",  # CTRL_A01
        r"[A-Z][a-z]+-[A-Z][a-z]+-\d+",  # Flow-Rate-03
        r"[A-Z]{3,}\d+",  # PRESSURE1
    ]
    return any(re.search(p, stdout) for p in patterns)


def _strict_check_anomaly(findings: dict) -> bool:
    """Layer 1: 扁平 JSON 結構驗證"""
    return (
        bool(findings.get("primary_column"))
        and findings.get("primary_score") is not None
    )


def _strict_check_optimization(findings: dict) -> bool:
    return bool(findings.get("primary_column") and findings.get("conclusion"))


def _strict_check_drift(findings: dict) -> bool:
    return bool(findings.get("primary_column") and findings.get("conclusion"))


def _strict_check_exploratory(findings: dict) -> bool:
    return bool(findings.get("conclusion") and len(findings.get("conclusion", "")) > 5)


# ── 場景完成驗證函式 (三層: strict → loose repair → semantic) ──


def anomaly_complete(stdout: str, findings: Any) -> bool:
    """異常分析完成: 需要嫌疑欄位 + 數字佐證"""
    # 確保 findings 是 dict
    if isinstance(findings, str):
        findings = try_loose_json(findings) or {}
    if not isinstance(findings, dict):
        findings = {}

    # 1️⃣ Strict: 扁平 JSON 驗證
    if _strict_check_anomaly(findings):
        return True

    # 2️⃣ Loose: 嘗試修復 JSON
    raw = findings.get("_raw", "")
    if raw:
        repaired = try_loose_json(raw)
        if repaired and _strict_check_anomaly(repaired):
            return True

    # 3️⃣ Semantic: stdout 有數字證據 + 欄位名
    return _has_numeric_evidence(stdout) and _has_column_mention(stdout)


def optimization_complete(stdout: str, findings: Any) -> bool:
    """最佳化完成: 需要驅動因子或操作窗口"""
    if isinstance(findings, str):
        findings = try_loose_json(findings) or {}
    if not isinstance(findings, dict):
        findings = {}

    if _strict_check_optimization(findings):
        return True

    conclusion = findings.get("conclusion", "")
    if "操作窗口" in conclusion or "驅動因子" in conclusion:
        return True

    return _has_numeric_evidence(stdout) and (
        "重要性" in stdout or "window" in stdout.lower()
    )


def drift_complete(stdout: str, findings: Any) -> bool:
    """漂移完成: 需要漂移方向 + 數字"""
    if isinstance(findings, str):
        findings = try_loose_json(findings) or {}
    if not isinstance(findings, dict):
        findings = {}

    if _strict_check_drift(findings):
        return True

    conclusion = findings.get("conclusion", "")
    if "漂移" in conclusion and _has_numeric_evidence(stdout):
        return True

    return "drift" in stdout.lower() and _has_numeric_evidence(stdout)


def exploratory_complete(stdout: str, findings: Any) -> bool:
    """探索性完成: 門檻最低，有結論即可"""
    if isinstance(findings, str):
        findings = try_loose_json(findings) or {}
    if not isinstance(findings, dict):
        findings = {}

    return _strict_check_exploratory(findings)


# ============================================================
# SCENARIO_CONFIG — 統一結構化配置
# ============================================================

SCENARIO_CONFIG = {
    "anomaly_detection": {
        "policy": POLICY_ANOMALY,
        "tools": TOOLS_ANOMALY,
        "completion_check": anomaly_complete,
        "max_rounds": 2,
        "min_rounds": 2,
    },
    "drift_analysis": {
        "policy": POLICY_ANOMALY,
        "tools": TOOLS_ANOMALY,
        "completion_check": anomaly_complete,
        "max_rounds": 2,
        "min_rounds": 2,
    },
    "optimization": {
        "policy": POLICY_OPTIMIZATION,
        "tools": TOOLS_OPTIMIZATION,
        "completion_check": optimization_complete,
        "max_rounds": 2,
        "min_rounds": 2,
    },
    "spec_recommendation": {
        "policy": POLICY_OPTIMIZATION,
        "tools": TOOLS_OPTIMIZATION,
        "completion_check": optimization_complete,
        "max_rounds": 2,
        "min_rounds": 2,
    },
    "global_analysis": {
        "policy": POLICY_ANOMALY,
        "tools": TOOLS_ANOMALY,
        "completion_check": anomaly_complete,
        "max_rounds": 2,
        "min_rounds": 2,
    },
    "general": {
        "policy": POLICY_ANOMALY,
        "tools": TOOLS_ANOMALY,
        "completion_check": anomaly_complete,
        "max_rounds": 2,
        "min_rounds": 2,
    },
}

# 向後相容: 保留 ANALYSIS_PERSONA_MAP (其他模組可能引用)
ANALYSIS_PERSONA_MAP = {
    k: (v["policy"][:30], v["policy"]) for k, v in SCENARIO_CONFIG.items()
}


# ============================================================
# Code Analyst Agent
# ============================================================


class CodeAnalyst:
    """
    四層架構 Code Analyst。
    L1 (Execution Contract) + L2 (Scenario Policy) + L3 (Tool Injection)
    = 完整 System Prompt
    L4 (Governor) 在 orchestrator 中。
    """

    def __init__(self, llm):
        self.llm = llm

    async def generate_code(
        self,
        query: str,
        data_summary: dict,
        unified_context: dict = None,
        previous_outputs: List[dict] = None,
        round_num: int = 1,
        focus_targets: list = None,
        task_type: str = "general",
        on_chunk=None,
    ) -> str:
        prompt = self._build_prompt(
            query,
            data_summary,
            unified_context,
            previous_outputs,
            round_num,
            focus_targets=focus_targets,
            task_type=task_type,
        )

        try:
            full_text = ""
            async for chunk in self.llm.astream_complete(prompt):
                delta = chunk.delta
                if delta and on_chunk:
                    import asyncio

                    result = on_chunk(delta)
                    if asyncio.iscoroutine(result):
                        await result
                full_text += delta or ""

            code = full_text.strip()

            _code_blocks = re.findall(r"```python\s*\n(.*?)```", code, re.DOTALL)
            if _code_blocks:
                if len(_code_blocks) > 1:
                    logger.warning(
                        f"[CodeAnalyst] Round {round_num}: {len(_code_blocks)} code blocks, merging"
                    )
                code = "\n\n".join(b.strip() for b in _code_blocks)
            else:
                if code.startswith("```python"):
                    code = code[len("```python") :].strip()
                if code.startswith("```"):
                    code = code[3:].strip()
                if code.endswith("```"):
                    code = code[:-3].strip()

            logger.info(f"[CodeAnalyst] Round {round_num}: generated {len(code)} chars")
            return code

        except Exception as e:
            logger.error(f"[CodeAnalyst] Code generation failed: {e}")
            return f"print('Code generation failed: {e}')"

    def should_continue(self, code: str) -> bool:
        return "NEED_MORE_ANALYSIS" in code

    def _build_prompt(
        self,
        query: str,
        data_summary: dict,
        unified_context: dict = None,
        previous_outputs: List[dict] = None,
        round_num: int = 1,
        focus_targets: list = None,
        task_type: str = "general",
    ) -> str:
        """L1 + L2 + L3 + data + query 純拼接"""
        config = SCENARIO_CONFIG.get(task_type, SCENARIO_CONFIG["general"])

        parts = []

        # --- L1: Execution Contract ---
        parts.append(EXECUTION_CONTRACT)

        # --- L2: Scenario Policy ---
        parts.append(config["policy"])

        # --- L3: Tool Injection ---
        parts.append("\n## 本場景可用的 sigma 工具")
        parts.append(config["tools"])

        # --- Data Context ---
        parts.append("\n## 資料描述")
        parts.append(f"- 行數: {data_summary.get('row_count', '?')}")
        parts.append(f"- 欄位數: {data_summary.get('column_count', '?')}")

        num_cols = data_summary.get("numerical_columns", [])
        if num_cols:
            preview = ", ".join(num_cols[:50])
            more = "..." if len(num_cols) > 50 else ""
            parts.append(f"- 數值欄位 ({len(num_cols)}): {preview}{more}")

        cat_cols = data_summary.get("categorical_columns", [])
        if cat_cols:
            parts.append(f"- 分類欄位: {', '.join(cat_cols[:10])}")

        prep_summary = data_summary.get("preprocess_summary", "")
        if prep_summary:
            parts.append("\n## 前置分析結果 (report 物件)")
            parts.append(prep_summary)

        # --- Unified Context ---
        if unified_context:
            parts.append("\n## 分析語境")
            tp = unified_context.get("target_params", [])
            rp = unified_context.get("reference_params", [])
            tr = unified_context.get("target_range", [])
            br = unified_context.get("baseline_range", "")
            hy = unified_context.get("has_y", False)
            if tp:
                parts.append(
                    f"- 目標參數: {', '.join(tp) if isinstance(tp, list) else tp}"
                )
            if rp:
                parts.append(
                    f"- 對照參數: {', '.join(rp) if isinstance(rp, list) else rp}"
                )
            if tr:
                parts.append(
                    f"- 目標區間: {', '.join(tr) if isinstance(tr, list) else tr}"
                )
            if br:
                parts.append(f"- 對照區間: {br}")
            parts.append(
                f"- 有目標變數: {'Yes → ' + (', '.join(tp) if tp else 'report中取得') if hy else 'No'}"
            )

        # --- Previous Outputs ---
        if previous_outputs:
            parts.append(f"\n## 前幾輪結果 ({len(previous_outputs)} 輪)")
            for prev in previous_outputs:
                r = prev.get("round", "?")
                parts.append(f"\n### 第 {r} 輪")
                if prev.get("stdout"):
                    parts.append(f"輸出:\n{prev['stdout'][:2500]}")
                if prev.get("error"):
                    parts.append(f"錯誤: {prev['error'][:500]}")
                if prev.get("evaluation_hint"):
                    parts.append(
                        f"\n📋 系統判定 (第 {r} 輪):\n{prev['evaluation_hint']}"
                    )
            parts.append("\n基於以上結果深入分析，不要重複。")

        # --- Query ---
        parts.append(f"\n## 使用者問題\n{query}")

        # --- Round directive (簡潔) ---
        if round_num == 1:
            parts.append("\n請產生 Round 1 程式碼。優先使用 sigma 工具。")
        else:
            parts.append(
                f"\n## Round {round_num}\n"
                f"基於上一輪發現深入分析。達到完成條件就 print('[ANALYSIS_COMPLETE]')。"
            )
            if focus_targets:
                for ft in focus_targets:
                    parts.append(ft)

        return "\n".join(parts)
