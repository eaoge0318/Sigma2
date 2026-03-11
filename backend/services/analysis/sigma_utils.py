"""
Sigma Utils — Code Interpreter 預建分析函式庫
============================================================
將 38 個 Tool 中最成熟的邏輯封裝為純函式，
預注入到 Code Interpreter 的 namespace 中。

用法（LLM 生成的 code 中）:
    df_active = sigma.filter_dead_columns(df_numeric)
    result = sigma.find_anomalies(df_active)
    sigma.plot_suspects(df_active, result['top_suspects'])
"""

import matplotlib

matplotlib.use("Agg")  # 必須在 pyplot import 前設定，防止 server 端彈出 GUI 視窗
import numpy as np
import pandas as pd
from typing import List, Dict, Optional, Tuple
import warnings

warnings.filterwarnings("ignore")

# ============================================================
# 0. API Help — 回傳 sigma 函式的 I/O 規格
# ============================================================

_SIGMA_SPECS = {
    "scan_anomaly_segments": (
        "sigma.scan_anomaly_segments(series)\n"
        "→ dict: {'segments': [{'start', 'end', 'type', 'severity', 'severity_score', 'description'}], "
        "'total_segments': int, 'has_anomaly': bool}\n"
        "type: DRIFT/OSCILLATION/SPIKE/DIP_RECOVERY/LEVEL_SHIFT/SHIFTED_STABLE/REGIME_CHANGE\n"
        "用法: result = sigma.scan_anomaly_segments(df['COL'])"
    ),
    "top_correlations": (
        "sigma.top_correlations(df, target=None, top_n=15)\n"
        "→ [(colA, colB, corr), ...]  ← 直接回傳 list of 3-tuple\n"
        "用法: for colA, colB, r in sigma.top_correlations(df, target='COL'):"
    ),
    "compare_groups": (
        "sigma.compare_groups(df, group_a_indices, group_b_indices, top_n=15)\n"
        "→ [(col, mean_a, mean_b, diff, t_stat, p_val), ...]  ← 直接回傳 list of 6-tuple\n"
        "用法: for col, ma, mb, d, t, p in sigma.compare_groups(df, a_idx, b_idx):"
    ),
    "detect_outliers_iqr": (
        "sigma.detect_outliers_iqr(df, top_n=15)\n"
        "→ [(col, count, ratio), ...]  ← 直接回傳 list of 3-tuple\n"
        "用法: for col, n, r in sigma.detect_outliers_iqr(df):"
    ),
    "t2_contribution": (
        "sigma.t2_contribution(df, anomaly_indices, top_n=15)\n"
        "→ ([(col, score), ...], [col, ...])  ← tuple: (contributions, top_contributors)\n"
        "用法: scores, names = sigma.t2_contribution(df, idx)\n"
        "      for col, s in scores:"
    ),
    "t2_contribution_baseline": (
        "sigma.t2_contribution_baseline(df, anomaly_indices, top_n=15)\n"
        "→ ([(col, delta_score), ...], [col, ...])  ← tuple\n"
        "用法: scores, names = sigma.t2_contribution_baseline(df, idx)"
    ),
    "t2_contribution_marginal": (
        "sigma.t2_contribution_marginal(df, anomaly_indices, top_n=15)\n"
        "→ ([(col, drop_score), ...], [col, ...])  ← tuple\n"
        "用法: scores, names = sigma.t2_contribution_marginal(df, idx)"
    ),
    "find_anomalies": (
        "sigma.find_anomalies(df, method='isolation_forest', top_n=15)\n"
        "→ dict: {'anomaly_indices': list[int], 'top_suspects': [(col, diff), ...], 'labels': ndarray}\n"
        "用法: result = sigma.find_anomalies(df)\n"
        "      for col, diff in result['top_suspects']:"
    ),
    "hotelling_t2": (
        "sigma.hotelling_t2(df, alpha=0.01)\n"
        "→ dict: {'t2_values': ndarray, 'ucl': float, 'ucl_warn': float, 'anomaly_indices': list[int]}\n"
        "用法: result = sigma.hotelling_t2(df)\n"
        "      anomaly_idx = result['anomaly_indices']"
    ),
    "robust_zscore": (
        "sigma.robust_zscore(df, threshold=3.0, top_n=15)\n"
        "→ dict: {'shifted_columns': [col, ...], 'column_stats': DataFrame, 'outlier_indices': list[int]}\n"
        "用法: result = sigma.robust_zscore(df)\n"
        "      shifted = result['shifted_columns']"
    ),
    "segment_drift": (
        "sigma.segment_drift(series, method='cusum')\n"
        "→ dict: {'segments': [{'start': int, 'end': int, 'direction': 'up'|'down'}, ...], 'method': str}\n"
        "用法: result = sigma.segment_drift(df['COL'])\n"
        "      for seg in result['segments']:"
    ),
    "scan_all_drift": (
        "sigma.scan_all_drift(df, top_n=10)\n"
        "→ dict: {'drift_columns': [col, ...], 'total_drifted': int, 'details': {col: [segs]}}\n"
        "用法: result = sigma.scan_all_drift(df)"
    ),
    "feature_importance": (
        "sigma.feature_importance(df, target, method='random_forest', top_n=15)\n"
        "→ dict: {'importances': [(col, score), ...], 'model_score': float}\n"
        "用法: result = sigma.feature_importance(df, 'TARGET')\n"
        "      for col, score in result['importances']:"
    ),
    "classify_anomaly_type": (
        "sigma.classify_anomaly_type(series)\n"
        "→ dict: {'anomaly_type': str, 'evidence': str}\n"
        "用法: result = sigma.classify_anomaly_type(df['COL'])"
    ),
    "plot_trend": (
        "sigma.plot_trend(df, cols=['COL'], anomaly_indices=list, title='Trend: COL')\n"
        "→ None (直接畫圖)\n"
        "⚠ title 必須包含欄位名！"
    ),
    "plot_distribution_compare": (
        "sigma.plot_distribution_compare(df, col, group_a_idx, group_b_idx, title='Distribution: COL')\n"
        "→ None (直接畫圖)\n"
        "⚠ title 必須包含欄位名！"
    ),
    "plot_scatter": (
        "sigma.plot_scatter(df, col_x, col_y, anomaly_indices=list, title='Scatter: X vs Y')\n"
        "→ None (直接畫圖)\n"
        "⚠ title 必須包含欄位名！"
    ),
}


def help(func_name: str = "") -> str:
    """回傳 sigma API 的 I/O 規格。不帶參數時列出所有可用函式。"""
    if not func_name:
        names = sorted(_SIGMA_SPECS.keys())
        return "可用的 sigma 函式:\n" + "\n".join(f"  - sigma.{n}()" for n in names)
    spec = _SIGMA_SPECS.get(func_name)
    if spec:
        return f"=== sigma.{func_name} ===\n{spec}"
    return f"未知函式: {func_name}。呼叫 sigma.help() 查看所有可用函式。"


# ============================================================
# 0.5 共用 Auto-Chart Helpers
# ============================================================


def _label_from_indices(indices, default_name=""):
    """從 index list 自動生成描述性名稱 (如 '#50-69')。"""
    if default_name and default_name not in ("A 組", "B 組", "Group A", "Group B"):
        return default_name
    if len(indices) == 0:
        return default_name or "?"
    s = sorted(indices)
    if len(s) > 1 and s[-1] - s[0] == len(s) - 1:
        return f"#{s[0]}-{s[-1]}"
    if len(s) <= 5:
        return f"#{','.join(str(x) for x in s)}"
    return f"#{s[0]}-{s[-1]}({len(s)}筆)"


def _auto_bar_chart(items, title, xlabel="分數", top_n=10, figsize=(8, 3.5)):
    """共用水平 Bar chart — 用於 T² contribution, importance, z-score 等排名圖。"""
    try:
        import matplotlib.pyplot as plt

        items = items[:top_n]
        if not items:
            return
        # 描述放文字框
        print(f"[圖表] {title}")
        labels = [str(x[0]) for x in items]
        values = [float(x[1]) for x in items]
        labels.reverse()
        values.reverse()

        fig, ax = plt.subplots(figsize=figsize)
        colors = [
            "#EF4444" if i >= len(values) - 3 else "#3B82F6" for i in range(len(values))
        ]
        ax.barh(labels, values, color=colors)
        ax.set_xlabel(xlabel)
        # 圖 title 只留簡短標籤
        ax.set_title(title, fontsize=10, fontweight="bold")
        ax.grid(True, axis="x", alpha=0.3)
        plt.tight_layout()
        plt.show()
        plt.close(fig)
    except Exception:
        pass


def _auto_comparison_bar(
    top_diffs,
    group_a_name,
    group_b_name,
    title,
    top_n=8,
    figsize=(8, 4),
    df=None,
    group_a_indices=None,
    group_b_indices=None,
):
    """共用分組對比 Box Plot — 每個欄位一個 subplot。"""
    try:
        import matplotlib.pyplot as plt

        items = top_diffs[:top_n]
        if not items:
            return
        # 需要原始 df 才能畫 boxplot
        if df is None or group_a_indices is None or group_b_indices is None:
            return

        n_cols = min(len(items), top_n)
        print(f"[圖表] {title}")

        _valid_a = df.index.intersection(group_a_indices)
        _valid_b = df.index.intersection(group_b_indices)

        fig, axes = plt.subplots(1, n_cols, figsize=(3.2 * n_cols, 4))
        if n_cols == 1:
            axes = [axes]

        for i, item in enumerate(items[:n_cols]):
            col_name = str(item[0])
            ax = axes[i]
            a_vals = df.loc[_valid_a, col_name].dropna().values
            b_vals = df.loc[_valid_b, col_name].dropna().values

            bp = ax.boxplot(
                [a_vals, b_vals],
                labels=[group_a_name, group_b_name],
                patch_artist=True,
                widths=0.6,
                medianprops=dict(color="#1F2937", linewidth=1.5),
            )
            bp["boxes"][0].set_facecolor("#93C5FD")
            bp["boxes"][0].set_edgecolor("#3B82F6")
            bp["boxes"][1].set_facecolor("#FCA5A5")
            bp["boxes"][1].set_edgecolor("#EF4444")

            ax.set_title(col_name, fontsize=9, fontweight="bold")
            ax.tick_params(axis="x", labelsize=8, rotation=20)
            ax.grid(True, axis="y", alpha=0.3)

        fig.suptitle(title, fontsize=10, fontweight="bold")
        plt.tight_layout()
        plt.show()
        plt.close(fig)
    except Exception:
        pass


# ============================================================
# 1. 資料清理
# ============================================================


def filter_dead_columns(
    df: pd.DataFrame,
    min_std: float = 1e-6,
    min_cv: float = 0.001,
    keep_cols: Optional[List[str]] = None,
) -> Tuple[pd.DataFrame, List[str]]:
    """
    過濾死水欄位 (std ≈ 0 的常數欄位) 和近似常數欄位 (MAD/median 極小)。

    Args:
        df: 純數值 DataFrame
        min_std: 最小標準差閾值
        min_cv: 最小變異係數閾值 (MAD / |median|)，低於此值視為近似常數
        keep_cols: 白名單欄位 — 即使符合死水條件也強制保留（如使用者指定的 target_params）

    Returns:
        (過濾後的 DataFrame, 被移除的欄位名稱列表)
    """
    # 自動過濾非數值欄位（防止 LLM 誤傳含字串的 df）
    df = df.select_dtypes(include="number")
    if df.empty:
        print("[sigma] 過濾死水欄位: 沒有數值欄位")
        return df, []

    _keep_set = set(keep_cols or [])

    dead = []
    kept_dead = []  # 符合死水條件但被白名單保留的欄位
    for col in df.columns:
        s = df[col]
        std_val = s.std()
        median_val = s.median()
        mad_val = (s - median_val).abs().median()  # MAD

        is_dead = False
        # 條件 1: std 接近 0 (完全常數)
        if std_val <= min_std:
            is_dead = True
        # 條件 2: MAD / |median| < min_cv (近似常數，變異極小)
        elif abs(median_val) > 1e-10 and (mad_val / abs(median_val)) < min_cv:
            is_dead = True

        if is_dead:
            if col in _keep_set:
                kept_dead.append(col)  # 白名單保留，不移除
            else:
                dead.append(col)

    active = [col for col in df.columns if col not in dead]
    df_active = df[active]
    print(
        f"[sigma] 過濾死水欄位: {len(df.columns)} -> {len(active)} 有效 (移除 {len(dead)} 個)"
    )
    if kept_dead:
        print(
            f"[sigma] ⚠️ 以下目標欄位為低變異/近似常數，已強制保留: {', '.join(kept_dead)}"
        )
    return df_active, dead


# ============================================================
# 2. 異常偵測
# ============================================================


def find_anomalies(
    df: pd.DataFrame,
    method: str = "isolation_forest",
    contamination: float = 0.05,
    top_n: int = 15,
    auto_chart: bool = True,
) -> Dict:
    """
    整體異常偵測 + 嫌疑犯欄位解釋。

    Args:
        df: 純數值 DataFrame (建議先用 filter_dead_columns 過濾)
        method: 'isolation_forest' 或 'zscore'
        contamination: IsolationForest 的汙染比例
        top_n: 回傳最重要的 N 個嫌疑犯欄位

    Returns:
        dict with keys:
        - anomaly_indices: 異常點的 row index
        - anomaly_count: 異常數量
        - normal_count: 正常數量
        - top_suspects: [(欄位名, 均值差異)] 差異最大的 Top-N
        - labels: 全部資料的標籤 (1=正常, -1=異常)
    """
    if method == "isolation_forest":
        from sklearn.ensemble import IsolationForest

        model = IsolationForest(
            contamination=contamination, random_state=42, n_estimators=100
        )
        labels = model.fit_predict(df)
    elif method == "zscore":
        from scipy import stats

        z = np.abs(stats.zscore(df, nan_policy="omit"))
        # 任何一欄 Z > 3 就視為異常
        labels = np.where(np.any(z > 3, axis=1), -1, 1)
    else:
        raise ValueError(f"不支援的方法: {method}")

    anomaly_mask = labels == -1
    normal_mask = labels == 1
    anomaly_indices = np.where(anomaly_mask)[0]

    # 計算嫌疑犯欄位 (異常 vs 正常的均值差異)
    top_suspects = []
    if len(anomaly_indices) > 0 and np.sum(normal_mask) > 0:
        anomaly_means = df[anomaly_mask].mean()
        normal_means = df[normal_mask].mean()
        diffs = (anomaly_means - normal_means).abs()
        sorted_diffs = diffs.sort_values(ascending=False)
        top_suspects = [
            (col, round(float(sorted_diffs[col]), 4))
            for col in sorted_diffs.index[:top_n]
        ]

    print(
        f"[sigma] 異常偵測 ({method}): {len(anomaly_indices)} 異常 / {np.sum(normal_mask)} 正常"
    )
    if top_suspects:
        print(f"[sigma] Top {min(top_n, len(top_suspects))} 嫌疑犯欄位:")
        for col, diff in top_suspects[:10]:
            print(f"  {col}: 均值差 {diff:.4f}")

    _result = {
        "anomaly_indices": anomaly_indices.tolist(),
        "anomaly_count": int(len(anomaly_indices)),
        "normal_count": int(np.sum(normal_mask)),
        "top_suspects": top_suspects,
        "labels": labels,
    }
    if auto_chart and top_suspects:
        _top = top_suspects[:10]
        _title = (
            f"異常偵測 ({method}): "
            f"{len(anomaly_indices)} 異常 / {int(np.sum(normal_mask))} 正常 — "
            f"{_top[0][0]} 差異最大"
        )
        _auto_bar_chart(_top, _title, xlabel="均值差異")
    return _result


def detect_outliers_iqr(
    df: pd.DataFrame, top_n: int = 15, auto_chart: bool = True
) -> Dict:
    """
    IQR 方法偵測每個欄位的離群值。

    Returns:
        dict with keys:
        - outlier_summary: [(欄位名, 離群值數量, 離群值比例)]
        - total_outlier_cells: 所有欄位的離群值總數
    """
    results = []
    total = 0
    for col in df.columns:
        q1 = df[col].quantile(0.25)
        q3 = df[col].quantile(0.75)
        iqr = q3 - q1
        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr
        outliers = ((df[col] < lower) | (df[col] > upper)).sum()
        total += outliers
        if outliers > 0:
            results.append((col, int(outliers), round(outliers / len(df), 4)))

    results.sort(key=lambda x: x[1], reverse=True)
    print(f"[sigma] IQR 離群值: {len(results)} 個欄位有離群值, 共 {total} 個離群值")
    for col, count, ratio in results[:top_n]:
        print(f"  {col}: {count} 個 ({ratio:.1%})")

    _result = results[:top_n]
    if auto_chart and results:
        _items = [(r[0], r[1]) for r in results[:top_n]]
        _title = f"IQR 離群值: {results[0][0]} 最多 ({results[0][1]} 筆), 共 {total} 個"
        _auto_bar_chart(_items, _title, xlabel="離群值數量")
    return _result


# ============================================================
# 2.5 Hotelling T² 分析
# ============================================================


def hotelling_t2(
    df: pd.DataFrame,
    alpha: float = 0.01,
    pca_threshold: float = 0.95,
    auto_chart: bool = True,
) -> Dict:
    """
    Hotelling T² 多變量異常偵測。
    當維度過高 (p/n > 0.5) 時，自動用 PCA 降維到累積解釋量 >= pca_threshold。

    Args:
        df: 純數值 DataFrame (建議先用 filter_dead_columns 過濾)
        alpha: 顯著水準 (預設 0.01，更嚴格以減少假陽性)
        pca_threshold: PCA 累積解釋量閾值 (預設 0.95 = 95%)

    Returns:
        dict with keys:
        - t2_values: np.ndarray — 每筆的 T² 值
        - ucl: float — 管控上限 (99% 界線)
        - ucl_warn: float — 警告上限 (95% 界線)
        - anomaly_indices: list[int] — T² > UCL 的行號
        - anomaly_ratio: float — 異常比例
        - pca_used: bool — 是否使用了 PCA 降維
        - n_components: int — 使用的主成分數
    """
    from scipy import stats
    from sklearn.decomposition import PCA
    from sklearn.preprocessing import StandardScaler

    # 安全處理 NaN: 移除含 NaN 的欄位（不要 fillna(0)，會扭曲 PCA 結果）
    df = df.select_dtypes(include=[np.number])
    nan_cols = df.columns[df.isna().any()].tolist()
    if nan_cols:
        print(f"[sigma] T² 移除 {len(nan_cols)} 個含 NaN 欄位")
        df = df.dropna(axis=1)

    n, p = df.shape
    if p < 2:
        print("[sigma] T² 分析需要至少 2 個欄位")
        return {
            "t2_values": np.array([]),
            "ucl": 0,
            "anomaly_indices": [],
            "anomaly_ratio": 0,
            "pca_used": False,
            "n_components": 0,
        }

    # 標準化
    scaler = StandardScaler()
    data_scaled = scaler.fit_transform(df.values)

    # 當 p/n > 0.5 時自動 PCA 降維
    pca_used = False
    n_components = p
    if p / n > 0.5:
        pca = PCA()
        pca.fit(data_scaled)
        cumulative = np.cumsum(pca.explained_variance_ratio_)
        # 取累積解釋量 >= threshold 的最小主成分數
        n_components = int(np.searchsorted(cumulative, pca_threshold) + 1)
        n_components = max(2, min(n_components, n - 2))  # 至少 2, 最多 n-2
        pca = PCA(n_components=n_components)
        data_scaled = pca.fit_transform(data_scaled)  # 用標準化後的數據
        pca_used = True
        print(
            f"[sigma] T²: 維度過高 ({p} 欄 vs {n} 筆), PCA 降至 {n_components} 主成分 (累積解釋量 {cumulative[n_components - 1]:.1%})"
        )

    p_eff = n_components  # 有效維度

    mean = data_scaled.mean(axis=0)
    cov = np.cov(data_scaled, rowvar=False)

    # 使用 pseudo-inverse 處理共線性
    cov_inv = np.linalg.pinv(cov)

    # 計算每筆的 T² 值
    diff = data_scaled - mean
    t2_values = np.array([float(d @ cov_inv @ d.T) for d in diff])

    # UCL 基於卡方分佈 (與業界 MSPC 標準一致)
    ucl = float(stats.chi2.ppf(0.99, p_eff))  # 99% 異常界線
    ucl_warn = float(stats.chi2.ppf(0.95, p_eff))  # 95% 警告界線

    anomaly_mask = t2_values > ucl
    anomaly_indices = np.where(anomaly_mask)[0].tolist()

    warn_count = int(np.sum(t2_values > ucl_warn)) - len(anomaly_indices)
    print(
        f"[sigma] Hotelling T²: {len(anomaly_indices)} 個異常 (>99%), "
        f"{warn_count} 個警告 (>95%) / {n} 筆 "
        f"(UCL_99={ucl:.2f}, UCL_95={ucl_warn:.2f}, 維度={p_eff})"
    )
    if anomaly_indices:
        for idx in anomaly_indices[:10]:
            print(f"  異常: 第 {idx} 筆 (T²={t2_values[idx]:.2f})")

    _result = {
        "t2_values": t2_values,
        "ucl": ucl,
        "ucl_warn": ucl_warn,
        "anomaly_indices": anomaly_indices,
        "pass1_extreme_indices": [],
        "pass2_anomaly_indices": [],
        "anomaly_ratio": round(len(anomaly_indices) / n, 4),
        "pca_used": pca_used,
        "n_components": n_components,
    }
    if auto_chart and len(t2_values) > 0:
        _title = (
            f"T² 控制圖: {len(anomaly_indices)} 異常 (>99%), "
            f"{warn_count} 警告 (>95%) / {n} 筆 — UCL_99={ucl:.1f}"
        )
        plot_t2(t2_values, ucl, ucl_warn, title=_title)
    return _result


def t2_contribution(
    df: pd.DataFrame,
    anomaly_indices: List[int],
    top_n: int = 15,
    pca_threshold: float = 0.9,
    auto_chart: bool = True,
) -> Dict:
    """
    T² 貢獻分解 — 找出哪些原始參數導致 T² 值超標。

    當維度過高 (p/n > 0.5) 時:
    1. PCA 降維（與 hotelling_t2 一致）
    2. 在 PCA 空間計算各主成分的 T² 貢獻
    3. 透過 PCA loadings 映射回原始欄位

    Args:
        df: 純數值 DataFrame
        anomaly_indices: hotelling_t2 回傳的 anomaly_indices
        top_n: 回傳前幾個
        pca_threshold: PCA 累積解釋量閾值 (需與 hotelling_t2 一致)

    Returns:
        dict with keys:
        - contributions: list[(col, avg_contribution)] — 按貢獻度排序
        - top_contributors: list[str] — 前 top_n 個關鍵參數名稱
    """
    from sklearn.decomposition import PCA
    from sklearn.preprocessing import StandardScaler

    if not anomaly_indices:
        print("[sigma] T² 貢獻分解: 沒有異常樣本")
        return [], []

    # 安全處理 NaN: 移除含 NaN 的欄位（與 hotelling_t2 一致）
    df = df.select_dtypes(include=[np.number]).dropna(axis=1)

    n, p = df.shape
    columns = df.columns.tolist()

    # 高維度時用 PCA（與 hotelling_t2 保持一致的降維策略）
    if p / n > 0.5:
        scaler = StandardScaler()
        data_scaled = scaler.fit_transform(df.values)

        pca_full = PCA()
        pca_full.fit(data_scaled)
        cumulative = np.cumsum(pca_full.explained_variance_ratio_)
        n_components = int(np.searchsorted(cumulative, pca_threshold) + 1)
        n_components = max(2, min(n_components, n - 2))

        pca = PCA(n_components=n_components)
        pca.fit(data_scaled)

        # 用 PCA 構建正則化偽逆: Σ⁻¹ ≈ V' diag(1/λ) V
        # V = pca.components_ (k, p), λ = pca.explained_variance_ (k,)
        loadings = pca.components_  # (k, p)
        eigenvalues = pca.explained_variance_  # (k,)
        cov_inv_approx = loadings.T @ np.diag(1.0 / eigenvalues) @ loadings  # (p, p)

        # 在標準化的原始空間直接計算貢獻: c_i = z_i * (Σ⁻¹z)_i
        mean_scaled = data_scaled.mean(axis=0)
        feature_contributions = np.zeros(p)
        for idx in anomaly_indices:
            z = data_scaled[idx] - mean_scaled
            contrib = z * (cov_inv_approx @ z)  # 每個原始欄位的貢獻
            feature_contributions += np.abs(contrib)

        avg_contributions = feature_contributions / len(anomaly_indices)

        print(
            f"[sigma] T² 貢獻分解 (標準化空間, {n_components} PCs): Top {min(top_n, len(columns))} 關鍵參數"
        )
    else:
        # 低維度直接在原始空間計算
        mean = df.mean().values
        cov = df.cov().values
        cov_inv = np.linalg.pinv(cov)

        all_contributions = np.zeros(p)
        for idx in anomaly_indices:
            x = df.iloc[idx].values
            diff = x - mean
            contrib = diff * (cov_inv @ diff)
            all_contributions += np.abs(contrib)

        avg_contributions = all_contributions / len(anomaly_indices)

        print(f"[sigma] T² 貢獻分解: Top {min(top_n, len(columns))} 關鍵參數")

    # 排序
    ranked = sorted(
        zip(columns, avg_contributions),
        key=lambda x: x[1],
        reverse=True,
    )

    for col, contrib in ranked[:top_n]:
        print(f"  {col}: {contrib:.4f}")

    _contributions = ranked[:top_n]
    _top_contributors = [col for col, _ in ranked[:top_n]]
    if auto_chart and ranked:
        _top = ranked[:top_n]
        _title = (
            f"T² 貢獨分解 ({len(anomaly_indices)} 異常點): "
            f"{_top[0][0]} 貢獨最大 ({_top[0][1]:.2f})"
        )
        _auto_bar_chart(_top, _title, xlabel="T² 貢獨分數")
    return _contributions, _top_contributors


def t2_contribution_baseline(
    df: pd.DataFrame,
    anomaly_indices: List[int],
    baseline_window: int = 20,
    top_n: int = 15,
    auto_chart: bool = True,
) -> Dict:
    """
    方向 1: Baseline 差分 T² contribution。
    不跟全域均值比，而是跟異常區間前後的 local baseline 比。
    這樣 level-shift 欄位不會因為跟全域均值差異大而被高估。

    Args:
        df: 純數值 DataFrame
        anomaly_indices: 超過 UCL 的行號
        baseline_window: baseline 取異常區間前後各 N 筆
        top_n: 回傳前幾個

    Returns:
        dict with keys:
        - contributions: list[(col, delta_score)]
        - top_contributors: list[str]
    """
    if not anomaly_indices:
        return [], []

    df = df.select_dtypes(include=[np.number]).dropna(axis=1)
    columns = df.columns.tolist()
    n = len(df)

    # 建立 baseline: 異常區間前後各 baseline_window 筆的「正常」資料
    anomaly_set = set(anomaly_indices)
    min_idx = max(0, min(anomaly_indices) - baseline_window)
    max_idx = min(n, max(anomaly_indices) + baseline_window + 1)
    baseline_indices = [i for i in range(min_idx, max_idx) if i not in anomaly_set]

    # 如果 baseline 太少，擴大到全域非異常資料
    if len(baseline_indices) < 10:
        baseline_indices = [i for i in range(n) if i not in anomaly_set]

    if not baseline_indices:
        return [], []

    # 計算 baseline 和 anomaly 的均值
    baseline_mean = df.iloc[baseline_indices].mean().values
    anomaly_mean = df.iloc[anomaly_indices].mean().values
    baseline_std = df.iloc[baseline_indices].std().values

    # 避免除以零
    baseline_std = np.where(baseline_std < 1e-10, 1.0, baseline_std)

    # Delta contribution: |anomaly_mean - baseline_mean| / baseline_std
    delta = np.abs(anomaly_mean - baseline_mean) / baseline_std

    ranked = sorted(
        zip(columns, delta),
        key=lambda x: x[1],
        reverse=True,
    )

    print(
        f"[sigma] Baseline 差分 T² contribution (baseline={len(baseline_indices)} 筆):"
    )
    for col, d in ranked[:top_n]:
        print(f"  {col}: delta={d:.4f}")

    _contributions = [(col, round(float(d), 4)) for col, d in ranked[:top_n]]
    _top_contributors = [col for col, _ in ranked[:top_n]]
    if auto_chart and ranked:
        _top = [(col, round(float(d), 4)) for col, d in ranked[:top_n]]
        _title = (
            f"Baseline 差分 T² ({len(anomaly_indices)} 異常, "
            f"baseline={len(baseline_indices)} 筆): {_top[0][0]} delta={_top[0][1]:.2f}"
        )
        _auto_bar_chart(_top, _title, xlabel="Delta 分數")
    return _contributions, _top_contributors


def t2_contribution_marginal(
    df: pd.DataFrame,
    anomaly_indices: List[int],
    top_n: int = 15,
    pca_threshold: float = 0.9,
    auto_chart: bool = True,
) -> Dict:
    """
    方向 3: Marginal Drop T² contribution。
    對每個異常點，逐欄遮蔽（替換成均值），看 T² 下降多少。
    T² 下降最多的欄位 = 真正驅動 T² 超標的 driver。

    抗 level-shift: 如果某欄位在該區間其實是正常值，
    遮蔽它 T² 不會下降 → 自然排名低。

    Args:
        df: 純數值 DataFrame
        anomaly_indices: 超過 UCL 的行號
        top_n: 回傳前幾個
        pca_threshold: PCA 累積解釋量閾值

    Returns:
        dict with keys:
        - contributions: list[(col, avg_t2_drop)]
        - top_contributors: list[str]
    """
    from sklearn.decomposition import PCA
    from sklearn.preprocessing import StandardScaler

    if not anomaly_indices:
        return [], []

    df = df.select_dtypes(include=[np.number]).dropna(axis=1)
    columns = df.columns.tolist()
    n, p = df.shape

    # 標準化
    scaler = StandardScaler()
    data_scaled = scaler.fit_transform(df.values)

    # PCA (與 hotelling_t2 一致)
    pca_used = False
    if p / n > 0.5:
        pca_full = PCA()
        pca_full.fit(data_scaled)
        cumulative = np.cumsum(pca_full.explained_variance_ratio_)
        n_comp = int(np.searchsorted(cumulative, pca_threshold) + 1)
        n_comp = max(2, min(n_comp, n - 2))
        pca = PCA(n_components=n_comp)
        pca.fit(data_scaled)
        pca_used = True
    else:
        pca = None
        n_comp = p

    def _compute_t2(data_matrix):
        """計算一組資料的 T² 值"""
        if pca_used and pca is not None:
            transformed = pca.transform(data_matrix)
        else:
            transformed = data_matrix
        mean = transformed.mean(axis=0)
        cov = np.cov(transformed, rowvar=False)
        if cov.ndim == 0:
            cov = np.array([[cov]])
        cov_inv = np.linalg.pinv(cov)
        diff = transformed - mean
        return np.array([float(d @ cov_inv @ d.T) for d in diff])

    # 全域均值 (標準化空間)
    global_mean_scaled = data_scaled.mean(axis=0)

    # 用全域 cov 計算 T² (跟 hotelling_t2 一致)
    if pca_used and pca is not None:
        transformed_all = pca.transform(data_scaled)
    else:
        transformed_all = data_scaled
    mean_all = transformed_all.mean(axis=0)
    cov_all = np.cov(transformed_all, rowvar=False)
    if cov_all.ndim == 0:
        cov_all = np.array([[cov_all]])
    cov_inv_all = np.linalg.pinv(cov_all)

    def _single_t2(row_scaled):
        """單筆 T² (用全域 cov)"""
        if pca_used and pca is not None:
            t = pca.transform(row_scaled.reshape(1, -1))[0]
        else:
            t = row_scaled
        d = t - mean_all
        return float(d @ cov_inv_all @ d.T)

    # Marginal drop: 逐欄遮蔽
    marginal_drops = np.zeros(p)
    for idx in anomaly_indices:
        row = data_scaled[idx].copy()
        base_t2 = _single_t2(row)

        for j in range(p):
            masked_row = row.copy()
            masked_row[j] = global_mean_scaled[j]  # 遮蔽此欄
            masked_t2 = _single_t2(masked_row)
            drop = base_t2 - masked_t2  # T² 下降量
            marginal_drops[j] += max(0, drop)  # 只計正向 drop

    # 平均
    avg_drops = marginal_drops / len(anomaly_indices)

    ranked = sorted(
        zip(columns, avg_drops),
        key=lambda x: x[1],
        reverse=True,
    )

    print(f"[sigma] Marginal Drop T² contribution ({len(anomaly_indices)} 異常點):")
    for col, drop in ranked[:top_n]:
        if drop > 0.01:
            print(f"  {col}: T²_drop={drop:.4f}")

    _contributions = [(col, round(float(d), 4)) for col, d in ranked[:top_n]]
    _top_contributors = [col for col, _ in ranked[:top_n]]
    if auto_chart and ranked:
        _top = [(col, round(float(d), 4)) for col, d in ranked[:top_n]]
        _title = (
            f"Marginal Drop T² ({len(anomaly_indices)} 異常點): "
            f"{_top[0][0]} T²_drop={_top[0][1]:.2f}"
        )
        _auto_bar_chart(_top, _title, xlabel="T² Drop")
    return _contributions, _top_contributors


def robust_zscore(
    df: pd.DataFrame,
    threshold: float = 3.0,
    min_outlier_ratio: float = 0.02,
    top_n: int = 15,
    auto_chart: bool = True,
) -> Dict:
    """
    Robust Z-score 分析 — 用 MAD (Median Absolute Deviation) 找系統性偏移欄位。

    內建 MAD 下限保護（MAD ≈ 0 時不會爆炸）。
    用 outlier_ratio（超過門檻的比例）判定系統性偏移，而非 max > threshold。

    Args:
        df: 純數值 DataFrame
        threshold: Z-score 門檻 (預設 3.0)
        min_outlier_ratio: 最小異常比例（超過此比例才判定為偏移欄位）
        top_n: 回傳前幾個偏移欄位

    Returns:
        dict with keys:
        - shifted_columns: list[str] — 偏移欄位名稱
        - column_stats: pd.DataFrame — 各欄位的 outlier_ratio, median, mad
        - zscore_df: pd.DataFrame — 完整 Z-score 矩陣
    """
    results = {}
    zscore_data = {}

    for col in df.columns:
        s = df[col]
        median = s.median()
        mad = (s - median).abs().median()

        # MAD 下限保護：MAD 太小時回傳 0（避免除零爆炸）
        if mad < 1e-9:
            zscore_data[col] = pd.Series(0.0, index=s.index)
            results[col] = {"outlier_ratio": 0.0, "median": float(median), "mad": 0.0}
            continue

        z = 0.6745 * (s - median) / mad
        zscore_data[col] = z
        outlier_ratio = float((z.abs() > threshold).mean())
        results[col] = {
            "outlier_ratio": outlier_ratio,
            "median": float(median),
            "mad": float(mad),
        }

    # 篩選偏移欄位
    stats_df = pd.DataFrame(results).T
    stats_df = stats_df.sort_values("outlier_ratio", ascending=False)
    shifted = stats_df[stats_df["outlier_ratio"] > min_outlier_ratio]

    print(
        f"[sigma] Robust Z-score: {len(shifted)} 個偏移欄位 "
        f"(outlier_ratio > {min_outlier_ratio:.0%}, 門檻 |z| > {threshold})"
    )
    for col in shifted.index[:top_n]:
        ratio = shifted.loc[col, "outlier_ratio"]
        print(f"  {col}: {ratio:.1%} 的樣本超過門檻")

    zscore_df = pd.DataFrame(zscore_data)

    # 計算所有超過門檻的 row indices（所有欄位聯集）
    _outlier_mask = zscore_df.abs() > threshold
    _outlier_indices = sorted(set(np.where(_outlier_mask.any(axis=1))[0].tolist()))

    _result = {
        "shifted_columns": shifted.index[:top_n].tolist(),
        "column_stats": stats_df,
        "zscore_df": zscore_df,
        "outlier_indices": _outlier_indices,
        "outlier_count": len(_outlier_indices),
    }
    if auto_chart and len(shifted) > 0:
        _items = [
            (col, float(shifted.loc[col, "outlier_ratio"]))
            for col in shifted.index[:top_n]
        ]
        _title = (
            f"Robust Z-score: {len(shifted)} 個偏移欄位 — "
            f"{shifted.index[0]} 偏移最大 ({shifted.iloc[0]['outlier_ratio']:.1%})"
        )
        _auto_bar_chart(_items, _title, xlabel="Outlier Ratio")
    return _result


def plot_t2(
    t2_values: np.ndarray,
    ucl: float,
    ucl_warn: float = None,
    title: str = None,
    pass1_indices: list = None,
    pass2_indices: list = None,
):
    """
    繪製 T² 控制圖 — 時序圖 + UCL 線 + 異常區段標色。

    Two-Pass 模式 (pass1_indices + pass2_indices 提供時):
      - Pass1 extreme: 紅色點 + 紅色填充
      - Pass2 異常: 橘色點 + 橘色填充

    Args:
        t2_values: hotelling_t2 回傳的 t2_values
        ucl: hotelling_t2 回傳的 ucl (99% 界線)
        ucl_warn: hotelling_t2 回傳的 ucl_warn (95% 界線)
        title: 圖表標題
        pass1_indices: Pass 1 extreme 樣本索引
        pass2_indices: Pass 2 新異常樣本索引
    """
    import matplotlib.pyplot as plt

    t2_values = np.asarray(t2_values).ravel()  # 確保 1D
    fig, ax = plt.subplots(figsize=(14, 5))

    # T² 曲線
    x = np.arange(len(t2_values))
    ax.plot(x, t2_values, color="#3B82F6", linewidth=1.2, label="T² 值")

    # 95% 警告線
    if ucl_warn is not None:
        ax.axhline(
            y=ucl_warn,
            color="#F59E0B",
            linestyle="--",
            linewidth=1.0,
            label=f"95% 警告 = {ucl_warn:.2f}",
        )

    # 99% UCL 線
    ax.axhline(
        y=ucl,
        color="#EF4444",
        linestyle="--",
        linewidth=1.5,
        label=f"99% 異常 = {ucl:.2f}",
    )

    # Two-Pass 模式
    if pass1_indices is not None and pass2_indices is not None:
        # Pass 1 extreme: 紅色
        if pass1_indices:
            p1_idx = np.array(pass1_indices)
            p1_mask = np.zeros(len(t2_values), dtype=bool)
            p1_mask[p1_idx] = True
            ax.fill_between(
                x,
                0,
                t2_values,
                where=p1_mask,
                color="#EF4444",
                alpha=0.25,
            )
            ax.scatter(
                p1_idx,
                t2_values[p1_idx],
                color="#EF4444",
                s=25,
                zorder=5,
                label=f"Pass1 extreme ({len(pass1_indices)})",
            )

        # Pass 2 異常: 橘色
        if pass2_indices:
            p2_idx = np.array(pass2_indices)
            p2_mask = np.zeros(len(t2_values), dtype=bool)
            p2_mask[p2_idx] = True
            ax.fill_between(
                x,
                0,
                t2_values,
                where=p2_mask,
                color="#F97316",
                alpha=0.25,
            )
            ax.scatter(
                p2_idx,
                t2_values[p2_idx],
                color="#F97316",
                s=25,
                zorder=5,
                marker="D",
                label=f"Pass2 異常 ({len(pass2_indices)})",
            )
    else:
        # 舊模式：只用 UCL 判定
        anomaly_mask = t2_values > ucl
        if np.any(anomaly_mask):
            ax.fill_between(
                x,
                0,
                t2_values,
                where=anomaly_mask,
                color="#EF4444",
                alpha=0.3,
                label="異常區段",
            )
            anomaly_x = x[anomaly_mask]
            anomaly_y = t2_values[anomaly_mask]
            ax.scatter(anomaly_x, anomaly_y, color="#EF4444", s=20, zorder=5)

    ax.set_xlabel("樣本序號")
    ax.set_ylabel("T² 值")
    ax.set_title(title or "Hotelling T² 控制圖")
    ax.legend(loc="upper right")
    ax.grid(True, alpha=0.3)
    plt.tight_layout()


# ============================================================
# 3. 相關性分析
# ============================================================


def top_correlations(
    df: pd.DataFrame,
    target: Optional[str] = None,
    top_n: int = 15,
    min_abs_corr: float = 0.3,
    auto_chart: bool = True,
    **kwargs,
) -> Dict:
    """
    相關性分析。

    如果指定 target: 回傳與 target 相關性最高的 Top-N 欄位
    如果不指定: 回傳全域最強的 Top-N 欄位對 (pair)

    Returns:
        dict with keys:
        - pairs: [(欄位A, 欄位B, 相關係數)]
    """
    corr = df.corr()

    if target and target in corr.columns:
        # 單目標模式
        target_corr = corr[target].drop(target).abs().sort_values(ascending=False)
        pairs = [
            (target, col, round(float(corr[target][col]), 4))
            for col in target_corr.index[:top_n]
            if abs(corr[target][col]) >= min_abs_corr
        ]
        print(f"[sigma] 與 {target} 相關性最高的 {len(pairs)} 個欄位:")
    else:
        # 全域模式
        pairs_raw = []
        cols = corr.columns
        for i in range(len(cols)):
            for j in range(i + 1, len(cols)):
                r = corr.iloc[i, j]
                if abs(r) >= min_abs_corr:
                    pairs_raw.append((cols[i], cols[j], round(float(r), 4)))
        pairs_raw.sort(key=lambda x: abs(x[2]), reverse=True)
        pairs = pairs_raw[:top_n]
        print(
            f"[sigma] 全域高相關性: 共 {len(pairs_raw)} 對 (|r| >= {min_abs_corr}), 顯示 Top {len(pairs)}"
        )

    for a, b, r in pairs[:10]:
        print(f"  {a} <-> {b}: r={r:.4f}")

    _result = pairs
    if auto_chart and pairs:
        _cols = list(set([p[0] for p in pairs[:8]] + [p[1] for p in pairs[:8]]))
        _title = f"Top 相關: {pairs[0][0]} ↔ {pairs[0][1]} (r={pairs[0][2]:.2f})"
        plot_correlation_heatmap(df, columns=_cols[:15], top_n=15)
    return _result


def correlation_network(
    df: pd.DataFrame, threshold: float = 0.5, top_k: int = 10
) -> Dict:
    """
    相關性網路分析 — 找出 Hub 參數。

    用 Degree Centrality 和 Betweenness Centrality 識別
    與最多其他參數有強關聯的「中樞節點」。

    Returns:
        dict with keys:
        - hub_ranking: [(欄位名, degree_centrality, hub_score)]
        - network_density: 網路密度
        - total_edges: 邊數
    """
    corr = df.corr()
    n = len(corr.columns)
    params = corr.columns.tolist()

    degree = {}
    strength = {}
    edges = 0

    for i, p_a in enumerate(params):
        count = 0
        s = 0.0
        for j, p_b in enumerate(params):
            if i >= j:
                continue
            r = corr.iloc[i, j]
            if abs(r) > threshold:
                count += 1
                s += abs(r)
                edges += 1
        degree[p_a] = count
        strength[p_a] = s

    # 計算 betweenness 近似 (鄰居間不連通的比例)
    betweenness = {}
    for p in params:
        neighbors = [q for q in params if q != p and abs(corr.loc[p, q]) > threshold]
        if len(neighbors) < 2:
            betweenness[p] = 0.0
            continue
        non_connected = 0
        total_pairs = 0
        for ni in range(len(neighbors)):
            for nj in range(ni + 1, len(neighbors)):
                total_pairs += 1
                if abs(corr.loc[neighbors[ni], neighbors[nj]]) <= threshold:
                    non_connected += 1
        betweenness[p] = non_connected / total_pairs if total_pairs > 0 else 0

    # 綜合評分
    hub_scores = []
    for p in params:
        d = degree[p] / (n - 1) if n > 1 else 0
        b = betweenness.get(p, 0)
        s = strength[p] / n if n > 0 else 0
        composite = d * 0.4 + b * 0.3 + s * 0.3
        hub_scores.append((p, round(d, 4), round(composite, 4)))

    hub_scores.sort(key=lambda x: x[2], reverse=True)
    density = edges / (n * (n - 1) / 2) if n > 1 else 0

    print(f"[sigma] 相關性網路: {n} 個節點, {edges} 條邊, 密度={density:.4f}")
    print(f"[sigma] Top {min(top_k, len(hub_scores))} Hub 參數:")
    for p, d, s in hub_scores[:top_k]:
        print(f"  {p}: degree={d:.4f}, hub_score={s:.4f}")

    _result = {
        "hub_ranking": hub_scores[:top_k],
        "network_density": round(density, 4),
        "total_edges": edges,
    }
    _items = [(p, s) for p, d, s in hub_scores[:top_k]]
    if _items:
        _title = f"Hub 分析: {_items[0][0]} hub_score={_items[0][1]:.4f} (網路密度={density:.4f})"
        _auto_bar_chart(_items, _title, xlabel="Hub Score")
    return _result


# ============================================================
# 4. 區間偏移偵測
# ============================================================


def segment_drift(
    series: pd.Series,
    method: str = "cusum",
    threshold: float = 5.0,
    min_segment_length: int = 5,
    quiet: bool = False,
    auto_chart: bool = True,
) -> Dict:
    """
    區間偏移偵測 (CUSUM / EWMA)。

    Args:
        series: 單一欄位的數值序列
        method: 'cusum' 或 'ewma'
        threshold: 偵測閾值 (CUSUM 的累積偏差閾值 / EWMA 的 sigma 倍數)
        min_segment_length: 最小區段長度

    Returns:
        dict with keys:
        - segments: [{'start': int, 'end': int, 'direction': str}]
        - method: str
    """
    values = series.values.astype(float)
    mean = np.mean(values)
    std = np.std(values)

    if std < 1e-10:
        return {"segments": [], "method": method, "message": "標準差為 0, 無法偵測"}

    segments = []

    if method == "cusum":
        drift = 0.5
        cusum_pos = np.zeros(len(values))
        cusum_neg = np.zeros(len(values))

        for i in range(1, len(values)):
            cusum_pos[i] = max(0, cusum_pos[i - 1] + (values[i] - mean) / std - drift)
            cusum_neg[i] = max(0, cusum_neg[i - 1] - (values[i] - mean) / std - drift)

        # 提取超閾值區段
        for direction, cusum in [("up", cusum_pos), ("down", cusum_neg)]:
            in_alarm = False
            start = 0
            for i in range(len(cusum)):
                if cusum[i] > threshold and not in_alarm:
                    in_alarm = True
                    start = i
                elif cusum[i] <= threshold and in_alarm:
                    in_alarm = False
                    if i - start >= min_segment_length:
                        segments.append(
                            {"start": int(start), "end": int(i), "direction": direction}
                        )
            if in_alarm and len(values) - start >= min_segment_length:
                segments.append(
                    {
                        "start": int(start),
                        "end": int(len(values)),
                        "direction": direction,
                    }
                )

    elif method == "ewma":
        lam = 0.2
        ewma = np.zeros(len(values))
        ewma[0] = values[0]
        for i in range(1, len(values)):
            ewma[i] = lam * values[i] + (1 - lam) * ewma[i - 1]

        # 控制限
        sigma_limit = threshold
        ucl = mean + sigma_limit * std * np.sqrt(lam / (2 - lam))
        lcl = mean - sigma_limit * std * np.sqrt(lam / (2 - lam))

        in_alarm = False
        start = 0
        for i in range(len(ewma)):
            oob = ewma[i] > ucl or ewma[i] < lcl
            direction = "up" if ewma[i] > ucl else "down"
            if oob and not in_alarm:
                in_alarm = True
                start = i
            elif not oob and in_alarm:
                in_alarm = False
                if i - start >= min_segment_length:
                    segments.append(
                        {"start": int(start), "end": int(i), "direction": direction}
                    )
        if in_alarm and len(values) - start >= min_segment_length:
            segments.append(
                {"start": int(start), "end": int(len(values)), "direction": direction}
            )

    if not quiet:
        print(
            f"[sigma] {method.upper()} 偵測 '{series.name}': 發現 {len(segments)} 個偏移區段"
        )
        for seg in segments:
            print(f"  [{seg['start']}-{seg['end']}] {seg['direction']}")

    _result = {"segments": segments, "method": method}
    if auto_chart and segments and not quiet:
        plot_drift(series, _result)
    return _result


def scan_all_drift(
    df: pd.DataFrame, method: str = "cusum", top_n: int = 10, auto_chart: bool = True
) -> Dict:
    """
    對所有欄位做區間偏移掃描，回傳偏移最嚴重的 Top-N 欄位。
    """
    # 防護: Series → DataFrame
    if isinstance(df, pd.Series):
        df = df.to_frame()
    results = []
    for col in df.columns:
        r = segment_drift(df[col], method=method, quiet=True, auto_chart=False)
        if r["segments"]:
            results.append((col, len(r["segments"]), r["segments"]))

    results.sort(key=lambda x: x[1], reverse=True)
    print(
        f"\n[sigma] 偏移掃描總結: {len(results)} 個欄位有偏移 (共 {len(df.columns)} 個)"
    )
    for col, count, segs in results[:top_n]:
        print(f"  {col}: {count} 個偏移區段")

    _result = {
        "drift_columns": [col for col, count, _ in results[:top_n]],
        "drift_columns_detail": [(col, count) for col, count, _ in results[:top_n]],
        "total_drifted": len(results),
        "details": {col: segs for col, _, segs in results[:top_n]},
    }
    if auto_chart and results:
        _items = [(col, count) for col, count, _ in results[:top_n]]
        _title = f"全域漂移掃描: {results[0][0]} 最嚴重 ({results[0][1]} 個偏移段), 共 {len(results)} 欄位有偏移"
        _auto_bar_chart(_items, _title, xlabel="偏移區段數")
    return _result


# ============================================================
# 5. 分組比較
# ============================================================


def compare_groups(
    df: pd.DataFrame,
    group_a_indices: List[int],
    group_b_indices: List[int],
    top_n: int = 15,
    group_a_name: str = "A 組",
    group_b_name: str = "B 組",
    auto_chart: bool = True,
) -> Dict:
    """
    比較兩組資料的差異，找出差異最大的欄位。

    Returns:
        dict with keys:
        - top_diffs: [(欄位名, A均值, B均值, 差異, t統計量, p值)]
    """
    from scipy import stats as sp_stats

    group_a_name = _label_from_indices(group_a_indices, group_a_name)
    group_b_name = _label_from_indices(group_b_indices, group_b_name)

    # 安全取子集: 用 loc (label-based)，intersection 防護越界
    _valid_a = df.index.intersection(group_a_indices)
    _valid_b = df.index.intersection(group_b_indices)
    a = df.loc[_valid_a]
    b = df.loc[_valid_b]

    diffs = []
    for col in df.columns:
        mean_a = a[col].mean()
        mean_b = b[col].mean()
        diff = abs(mean_a - mean_b)
        # t-test
        try:
            t_stat, p_val = sp_stats.ttest_ind(a[col], b[col], equal_var=False)
        except Exception:
            t_stat, p_val = 0, 1
        diffs.append(
            (
                col,
                round(float(mean_a), 4),
                round(float(mean_b), 4),
                round(float(diff), 4),
                round(float(t_stat), 4),
                round(float(p_val), 6),
            )
        )

    diffs.sort(key=lambda x: x[3], reverse=True)
    top = diffs[:top_n]

    print(
        f"[sigma] 分組比較: {group_a_name}({len(group_a_indices)}筆) vs {group_b_name}({len(group_b_indices)}筆)"
    )
    print(f"[sigma] Top {len(top)} 差異最大的欄位:")
    for col, ma, mb, d, t, p in top:
        sig = "*" if p < 0.05 else ""
        print(
            f"  {col}: {group_a_name}={ma:.2f}, {group_b_name}={mb:.2f}, 差={d:.2f}, p={p:.4f}{sig}"
        )

    _result = top
    if auto_chart and top:
        _title = (
            f"分組對比 ({group_a_name} {len(group_a_indices)}筆 vs "
            f"{group_b_name} {len(group_b_indices)}筆): {top[0][0]} 差異最大"
        )
        _auto_comparison_bar(
            top,
            group_a_name,
            group_b_name,
            _title,
            df=df,
            group_a_indices=group_a_indices,
            group_b_indices=group_b_indices,
        )
    return _result


# ============================================================
# 6. 繪圖輔助
# ============================================================


def plot_suspects(
    df: pd.DataFrame,
    suspects: List[tuple],
    labels: np.ndarray = None,
    max_plots: int = 10,
    **kwargs,
):
    """
    繪製嫌疑犯欄位的分佈對比圖 (正常 vs 異常)。

    Args:
        df: 純數值 DataFrame
        suspects: find_anomalies 回傳的 top_suspects [(欄位名, 均值差)]
        labels: find_anomalies 回傳的 labels (1=正常, -1=異常)
        max_plots: 最多畫幾個
    """
    import matplotlib.pyplot as plt

    n = min(len(suspects), max_plots)
    if n == 0:
        print("[sigma] 沒有嫌疑犯欄位可繪圖")
        return

    # 支援三種格式: [(col, diff)] 或 [col] 或 [int_index]
    if suspects and isinstance(suspects[0], str):
        suspects = [(col, 0) for col in suspects]
    elif suspects and isinstance(suspects[0], (int, float, np.integer)):
        # 傳入的是 index，不是欄位名
        print("[sigma] plot_suspects: 收到 int indices, 非欄位名, 跳過")
        return

    ncols = min(n, 5)
    nrows = (n + ncols - 1) // ncols

    fig, axes = plt.subplots(nrows=nrows, ncols=ncols, figsize=(4 * ncols, 3 * nrows))
    fig.suptitle("嫌疑犯欄位分佈對比 (正常 vs 異常)", fontsize=14)

    if n == 1:
        axes = np.array([axes])
    axes = axes.flatten()

    for i, (col, diff) in enumerate(suspects[:n]):
        ax = axes[i]
        if col not in df.columns:
            ax.text(
                0.5,
                0.5,
                f"{col}\n(欄位不存在)",
                ha="center",
                va="center",
                fontsize=9,
                color="gray",
            )
            ax.set_title(col, fontsize=9)
            continue
        # labels 驗證：必須跟 df 同長且含 1/-1
        _valid_labels = False
        if labels is not None:
            _labels = np.asarray(labels).ravel()
            if len(_labels) == len(df) and set(np.unique(_labels)).issubset({-1, 1}):
                _valid_labels = True
        if _valid_labels:
            _mask_normal = _labels == 1
            _mask_anomaly = _labels == -1
            normal_data = df[col].values[_mask_normal]
            anomaly_data = df[col].values[_mask_anomaly]
            if len(normal_data) > 0:
                ax.hist(normal_data, bins=20, alpha=0.6, label="正常", color="#4A90D9")
            if len(anomaly_data) > 0:
                ax.hist(anomaly_data, bins=20, alpha=0.6, label="異常", color="#E74C3C")
            ax.legend(fontsize=8)
        else:
            data = df[col].dropna()
            if len(data) > 0:
                ax.hist(data, bins=20, alpha=0.7, color="#4A90D9")
        ax.set_title(f"{col}\n(差={diff:.1f})", fontsize=9)
        ax.tick_params(labelsize=7)

    # 隱藏空白子圖
    for i in range(n, len(axes)):
        axes[i].set_visible(False)

    plt.tight_layout(rect=[0, 0, 1, 0.94])
    plt.show()


def plot_drift(
    series: pd.Series,
    drift_result,
):
    """
    繪製單一欄位的趨勢圖 + 標記偏移區段。
    drift_result 可以是 segment_drift() 回傳的 dict，
    或 scan_all_drift()['details'][col] 回傳的 list。
    """
    import matplotlib.pyplot as plt

    # 防護: 支援多種輸入格式
    if isinstance(drift_result, list):
        # 來自 scan_all_drift()['details'][col]
        segments = drift_result
        method = "cusum"
    elif isinstance(drift_result, dict):
        segments = drift_result.get("segments", [])
        method = drift_result.get("method", "cusum")
    else:
        segments = []
        method = "unknown"

    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(series.values, linewidth=0.8, color="#4A90D9", label=series.name)

    for seg in segments:
        if isinstance(seg, dict):
            color = "#E74C3C" if seg.get("direction") == "up" else "#F39C12"
            ax.axvspan(
                seg.get("start", 0),
                seg.get("end", 0),
                alpha=0.3,
                color=color,
                label=f"{seg.get('direction', '?')} drift",
            )

    ax.set_title(f"{series.name} — {method.upper()} 偏移偵測", fontsize=12)
    ax.set_xlabel("行號")
    ax.set_ylabel("數值")
    # 去重圖例
    handles, lbls = ax.get_legend_handles_labels()
    by_label = dict(zip(lbls, handles))
    ax.legend(by_label.values(), by_label.keys(), fontsize=8)
    plt.tight_layout()
    plt.show()


def plot_correlation_heatmap(
    df: pd.DataFrame,
    columns: List[str] = None,
    top_n: int = 15,
    title: str = "",
):
    """
    繪製相關性熱圖 (Top-N 子集)。
    """
    import matplotlib.pyplot as plt

    if columns is not None:
        cols = [c for c in list(columns) if c in df.columns][:top_n]
    else:
        # 自動選取 std 最大的 Top-N
        stds = df.std().sort_values(ascending=False)
        cols = stds.index[:top_n].tolist()

    corr = df[cols].corr()
    fig, ax = plt.subplots(figsize=(10, 8))
    im = ax.imshow(corr.values, cmap="RdBu_r", vmin=-1, vmax=1, interpolation="nearest")

    ax.set_xticks(range(len(cols)))
    ax.set_yticks(range(len(cols)))
    ax.set_xticklabels(cols, rotation=45, ha="right", fontsize=8)
    ax.set_yticklabels(cols, fontsize=8)
    _top3 = ", ".join(cols[:3])
    _hm_title = title or f"相關性矩陣: {_top3} 等 {len(cols)} 欄"
    ax.set_title(_hm_title, fontsize=12)
    print(f"[圖表] {_hm_title}")

    fig.colorbar(im, label="相關係數")
    plt.tight_layout()
    plt.show()


# ============================================================
# 7. 共線性分析
# ============================================================


def collinearity_analysis(
    df: pd.DataFrame,
    vif_threshold: float = 10.0,
    top_n: int = 15,
    auto_chart: bool = True,
) -> Dict:
    """
    共線性崩潰偵測 — VIF + Condition Number + 高共線性群組。

    VIF (Variance Inflation Factor) > 10 表示嚴重共線性。
    Condition Number > 30 表示矩陣病態（共線性崩潰風險）。

    Returns:
        dict with keys:
        - vif_ranking: [(欄位名, VIF值)] VIF 最高的 Top-N
        - condition_number: 條件數
        - high_collinearity_groups: [[欄位群組]] 高度共線的欄位群
        - risk_level: 'low' / 'medium' / 'high' / 'critical'
    """
    from sklearn.preprocessing import StandardScaler

    # 標準化
    scaler = StandardScaler()
    X = scaler.fit_transform(df)

    # Condition Number
    try:
        cond_number = float(np.linalg.cond(X))
    except Exception:
        cond_number = float("inf")

    # VIF 計算
    vif_results = []
    cols = df.columns.tolist()

    for i in range(len(cols)):
        try:
            # VIF = 1 / (1 - R^2)
            # R^2 = 用其他所有變數預測第 i 個變數的 R-squared
            y = X[:, i]
            X_others = np.delete(X, i, axis=1)

            # 快速 OLS: R^2 = 1 - SS_res / SS_tot
            # 用 np.linalg.lstsq 替代 sklearn 加速
            beta, residuals, _, _ = np.linalg.lstsq(X_others, y, rcond=None)
            y_pred = X_others @ beta
            ss_res = np.sum((y - y_pred) ** 2)
            ss_tot = np.sum((y - np.mean(y)) ** 2)

            r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0
            vif = 1 / (1 - r_squared) if r_squared < 1 else float("inf")
            vif_results.append((cols[i], round(float(vif), 2)))
        except Exception:
            vif_results.append((cols[i], float("inf")))

    vif_results.sort(key=lambda x: x[1], reverse=True)

    # 高共線性群組 (|r| > 0.95 的欄位群)
    corr = df.corr().abs()
    visited = set()
    groups = []
    for i, col_a in enumerate(cols):
        if col_a in visited:
            continue
        group = [col_a]
        for j, col_b in enumerate(cols):
            if i >= j or col_b in visited:
                continue
            if corr.iloc[i, j] > 0.95:
                group.append(col_b)
                visited.add(col_b)
        if len(group) > 1:
            groups.append(group)
            visited.add(col_a)

    # 風險等級
    high_vif_count = sum(1 for _, v in vif_results if v > vif_threshold)
    if cond_number > 1000 or high_vif_count > len(cols) * 0.3:
        risk = "critical"
    elif cond_number > 100 or high_vif_count > len(cols) * 0.15:
        risk = "high"
    elif cond_number > 30 or high_vif_count > 5:
        risk = "medium"
    else:
        risk = "low"

    print(f"[sigma] 共線性分析:")
    print(f"  Condition Number: {cond_number:.1f}")
    print(f"  VIF > {vif_threshold}: {high_vif_count} 個欄位")
    print(f"  高共線性群組 (|r|>0.95): {len(groups)} 組")
    print(f"  風險等級: {risk}")
    print(f"\n  VIF Top {min(top_n, len(vif_results))}:")
    for col, vif in vif_results[:top_n]:
        flag = " *** 危險" if vif > vif_threshold else ""
        print(f"    {col}: VIF={vif:.1f}{flag}")
    if groups:
        print(f"\n  高共線性群組:")
        for g in groups[:5]:
            print(
                f"    {' / '.join(g[:5])}"
                + (f" ...+{len(g) - 5}" if len(g) > 5 else "")
            )

    _result = {
        "vif_ranking": vif_results[:top_n],
        "condition_number": round(cond_number, 2),
        "high_collinearity_groups": groups,
        "high_vif_count": high_vif_count,
        "risk_level": risk,
    }
    if auto_chart and vif_results:
        _title = f"共線性: {risk}風險, {vif_results[0][0]} VIF={vif_results[0][1]:.1f}"
        _auto_bar_chart(vif_results[:top_n], _title, xlabel="VIF")
    return _result


# ============================================================
# 8. 分佈偏移偵測
# ============================================================


def distribution_shift(
    series: pd.Series,
    split_point: Optional[int] = None,
    auto_chart: bool = True,
) -> Dict:
    """
    分佈偏移偵測 (KS-test + Wasserstein distance)。
    如果沒指定 split_point，自動對半分。

    Returns:
        dict with keys:
        - ks_statistic, ks_p_value
        - wasserstein_distance
        - shift_detected: bool (p < 0.05)
        - mean_shift: 前後均值差
    """
    from scipy import stats as sp_stats
    from scipy.stats import wasserstein_distance as wd

    if split_point is None:
        split_point = len(series) // 2

    a = series.iloc[:split_point].dropna().values
    b = series.iloc[split_point:].dropna().values

    if len(a) < 5 or len(b) < 5:
        return {"error": "資料太少無法偵測"}

    ks_stat, ks_p = sp_stats.ks_2samp(a, b)
    w_dist = float(wd(a, b))
    mean_shift = float(np.mean(b) - np.mean(a))
    detected = ks_p < 0.05

    print(f"[sigma] 分佈偏移 '{series.name}':")
    print(f"  KS 統計量={ks_stat:.4f}, p={ks_p:.4f}")
    print(f"  Wasserstein 距離={w_dist:.4f}")
    print(f"  均值偏移={mean_shift:.4f}")
    print(f"  偵測結果: {'有偏移' if detected else '無顯著偏移'}")

    _result = {
        "ks_statistic": round(ks_stat, 4),
        "ks_p_value": round(ks_p, 6),
        "wasserstein_distance": round(w_dist, 4),
        "shift_detected": detected,
        "mean_shift": round(mean_shift, 4),
    }
    if auto_chart:
        try:
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(10, 5))
            ax.hist(a, bins=30, alpha=0.5, label=f"前半 ({len(a)}筆)", color="#3B82F6")
            ax.hist(b, bins=30, alpha=0.5, label=f"後半 ({len(b)}筆)", color="#EF4444")
            _det = "✅有偏移" if detected else "✖無偏移"
            ax.set_title(
                f"分佈偏移 '{series.name}': KS={ks_stat:.3f}, p={ks_p:.4f} {_det}",
                fontsize=11,
                fontweight="bold",
            )
            ax.legend()
            ax.grid(True, alpha=0.3)
            plt.tight_layout()
            plt.show()
            plt.close(fig)
        except Exception:
            pass
    return _result


# ============================================================
# 9. 異常類型分類
# ============================================================


def classify_anomaly_type(series: pd.Series, auto_chart: bool = True) -> Dict:
    """
    將異常區間分類為具體模式:
    - Freeze: 變異數極低 (數值卡住)
    - Spike: 突波 (瞬間高偏差)
    - Drift: 緩慢漂移
    - Oscillation: 振盪
    - Level Shift: 水平跳變
    """
    values = series.dropna().values
    n = len(values)
    if n < 10:
        return {"type": "unknown", "message": "資料太少"}

    std = np.std(values)
    mean = np.mean(values)
    diff = np.diff(values)

    # Freeze: std 極低
    cv = std / abs(mean) if abs(mean) > 1e-10 else 0
    if cv < 0.001:
        atype = "freeze"
        confidence = min(1.0, (0.001 - cv) / 0.001)
    # Spike: 有大突波
    elif np.max(np.abs(diff)) > 5 * np.std(diff):
        atype = "spike"
        spike_count = int(np.sum(np.abs(diff) > 3 * np.std(diff)))
        confidence = min(1.0, spike_count / 5)
    # Oscillation: 高頻正負交替
    elif np.sum(np.diff(np.sign(diff)) != 0) > n * 0.6:
        atype = "oscillation"
        sign_changes = np.sum(np.diff(np.sign(diff)) != 0)
        confidence = min(1.0, sign_changes / n)
    # Level Shift: 均值突變
    else:
        half = n // 2
        mean_a = np.mean(values[:half])
        mean_b = np.mean(values[half:])
        if abs(mean_b - mean_a) > 2 * std:
            atype = "level_shift"
            confidence = min(1.0, abs(mean_b - mean_a) / (3 * std))
        else:
            # Drift: 線性趨勢
            x = np.arange(n)
            slope = np.polyfit(x, values, 1)[0]
            if abs(slope * n) > 2 * std:
                atype = "drift"
                confidence = min(1.0, abs(slope * n) / (3 * std))
            else:
                atype = "normal"
                confidence = 0.8

    print(f"[sigma] 異常類型 '{series.name}': {atype} (信心度={confidence:.2f})")
    _result = {"type": atype, "confidence": round(confidence, 3)}
    if auto_chart:
        try:
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(10, 4))
            ax.plot(values, color="#3B82F6", linewidth=1)
            ax.set_title(
                f"異常類型 '{series.name}': {atype} (信心度={confidence:.2f})",
                fontsize=11,
                fontweight="bold",
            )
            ax.set_xlabel("筆數")
            ax.grid(True, alpha=0.3)
            plt.tight_layout()
            plt.show()
            plt.close(fig)
        except Exception:
            pass
    return _result


# ============================================================
# 9.5 滑動窗口異常區段掃描
# ============================================================


def scan_anomaly_segments(
    series: pd.Series,
    auto_chart: bool = True,
) -> Dict:
    """
    單參數滑動窗口異常區段掃描 (FDC)。

    對一個 Series 做:
    1. 滑動窗口偵測異常區域 (freeze/high-var/shifted) — 肉眼級閾值
    2. 分類每個區段:
       DRIFT(漂移) / LEVEL_SHIFT(水平跳變) / SHIFTED_STABLE(偏移穩態) /
       OSCILLATION(震盪) / SPIKE(突波) / DIP_RECOVERY(急跌恢復)
    3. 大區段標註 REGIME_CHANGE(狀態切換)
    4. 嚴重度評分 (0-10)

    Returns:
        dict:
        - segments: [{start, end, type, type_cn, severity, severity_score, description, ...}]
        - total_segments: int
        - has_anomaly: bool
    """
    # --- 中文名稱對照 ---
    _TYPE_CN = {
        "DRIFT": "漂移",
        "LEVEL_SHIFT": "水平跳變",
        "SHIFTED_STABLE": "偏移穩態",
        "OSCILLATION": "震盪",
        "SPIKE": "突波",
        "DIP_RECOVERY": "急跌恢復",
        "REGIME_CHANGE": "狀態切換",
    }

    values = series.dropna()
    n = len(values)
    if n < 10:
        return {"segments": [], "total_segments": 0, "has_anomaly": False}

    # MAD-based robust statistics
    global_median = float(np.median(values))
    _mad = float(np.median(np.abs(values - global_median)))
    global_std = _mad * 1.4826  # MAD → σ
    if global_std < 1e-10:
        global_std = float(values.std())  # fallback
    if global_std == 0:
        return {"segments": [], "total_segments": 0, "has_anomaly": False}

    global_mean = global_median  # 用 median 當 "mean" 更 robust

    # ================================================================
    # Step 1: 滑動窗口偵測異常區域 (肉眼級閾值)
    # ================================================================
    _ws_small = max(5, min(30, n // 40))
    _ws_large = max(10, n // 15)
    _all_regions = []

    for window_size in [_ws_small, _ws_large]:
        regions = []
        in_anomaly = False
        start_idx = 0

        for i in range(0, n - window_size + 1):
            window = values.iloc[i : i + window_size]
            w_std = window.std()
            w_mean = window.mean()

            is_anomalous = (
                (global_std > 0.1 and w_std < global_std * 0.05)  # Freeze
                or (
                    global_std > 0 and w_std > global_std * 3.0
                )  # High variance (肉眼級)
                or (
                    global_std > 0 and abs(w_mean - global_mean) > global_std * 3.0
                )  # Shifted (肉眼級)
            )

            if is_anomalous and not in_anomaly:
                start_idx = i
                in_anomaly = True
            elif not is_anomalous and in_anomaly:
                regions.append({"start": start_idx, "end": i + window_size - 2})
                in_anomaly = False

        if in_anomaly:
            regions.append({"start": start_idx, "end": n - 1})
        _all_regions.extend(regions)

    # 合併重疊區域
    if _all_regions:
        _all_regions.sort(key=lambda r: r["start"])
        _merged = [_all_regions[0]]
        for r in _all_regions[1:]:
            if r["start"] <= _merged[-1]["end"] + 5:  # 允許 5 點間隔合併
                _merged[-1]["end"] = max(_merged[-1]["end"], r["end"])
            else:
                _merged.append(r)
        _all_regions = _merged

    # ================================================================
    # Step 2: 分類每個區段 (7 種異常類型)
    # ================================================================
    segments = []
    for region in _all_regions:
        start, end = region["start"], region["end"]
        seg_len = end - start + 1
        segment = values.iloc[start : end + 1]
        if len(segment) < 3:
            continue

        seg_std = segment.std()
        seg_mean = segment.mean()
        seg_len = len(segment)
        variance_ratio = seg_std / global_std if global_std > 0 else 0
        mean_shift_z = abs(seg_mean - global_mean) / (global_std + 1e-10)

        # Feature extraction
        diff = segment.diff().dropna()
        sign_changes = (
            (diff.iloc[:-1].values * diff.iloc[1:].values < 0).sum()
            if len(diff) > 2
            else 0
        )
        sign_change_rate = sign_changes / max(1, len(diff) - 1)

        x = np.arange(seg_len)
        slope = 0
        trend_strength = 0
        if seg_len >= 3 and seg_std > 0:
            slope = np.polyfit(x, segment.values, 1)[0]
            trend_strength = abs(slope * seg_len) / (seg_std + 1e-10)

        # --- Classification (priority order, 肉眼級) ---
        cls = {"variance_ratio": round(float(variance_ratio), 3)}

        # 1. DRIFT: 持續漂移 (斜率顯著)
        if trend_strength > 2.5:
            direction = "上升" if slope > 0 else "下降"
            cls.update(
                type="DRIFT",
                confidence=min(0.95, trend_strength / 4),
                description=f"漂移 ({direction}): 趨勢強度 {trend_strength:.1f}",
            )

        # 2. OSCILLATION: 控制震盪 (高方差 + 頻繁反轉)
        elif variance_ratio > 2.0 and sign_change_rate > 0.4:
            cls.update(
                type="OSCILLATION",
                confidence=min(0.95, sign_change_rate * variance_ratio / 4),
                description=f"震盪: 方差比 {variance_ratio:.1f}x, 方向變換率 {sign_change_rate:.0%}",
            )

        # 3. SPIKE: 突波 (短區段 + 極大偏移)
        elif seg_len <= 5 and variance_ratio > 2:
            max_dev = abs(segment - global_mean).max()
            max_dev_z = max_dev / (global_std + 1e-10)
            if max_dev_z > 3.0:
                cls.update(
                    type="SPIKE",
                    confidence=min(0.95, max_dev_z / 5),
                    description=f"突波: {seg_len} 點, 最大偏移 {max_dev_z:.1f}σ",
                )
            else:
                continue  # 不夠明顯，跳過

        # 4. DIP_RECOVERY: 急跌恢復 / 急升回落 (V 型)
        elif seg_len >= 3 and seg_len <= 30 and variance_ratio > 1.5:
            vals = segment.values
            mid = len(vals) // 2
            fh_mean = np.mean(vals[:mid]) if mid > 0 else vals[0]
            mid_val = np.mean(vals[max(0, mid - 1) : min(len(vals), mid + 2)])
            sh_mean = np.mean(vals[mid:]) if mid < len(vals) else vals[-1]
            v_depth = min(fh_mean, sh_mean) - mid_val
            inv_v = mid_val - max(fh_mean, sh_mean)

            if v_depth > global_std * 2.5:
                cls.update(
                    type="DIP_RECOVERY",
                    confidence=min(0.95, v_depth / (global_std * 4)),
                    description=f"急跌恢復 (V型): 深度 {v_depth / global_std:.1f}σ",
                )
            elif inv_v > global_std * 2.5:
                cls.update(
                    type="DIP_RECOVERY",
                    confidence=min(0.95, inv_v / (global_std * 4)),
                    description=f"急升回落 (倒V型): 高度 {inv_v / global_std:.1f}σ",
                )
            elif mean_shift_z > 3.0 and variance_ratio < 2:
                shift = seg_mean - global_mean
                cls.update(
                    type="LEVEL_SHIFT",
                    confidence=min(0.95, mean_shift_z / 5),
                    description=f"水平跳變: 偏移 {shift:+.4f} ({mean_shift_z:.1f}σ)",
                )
            else:
                continue  # 不夠明顯，跳過

        # 5. LEVEL_SHIFT: 水平跳變 (均值大幅偏移)
        elif mean_shift_z > 3.0 and variance_ratio < 2:
            shift = seg_mean - global_mean
            cls.update(
                type="LEVEL_SHIFT",
                confidence=min(0.95, mean_shift_z / 5),
                description=f"水平跳變: 偏移 {shift:+.4f} ({mean_shift_z:.1f}σ)",
            )

        # 6. SHIFTED_STABLE: 低方差 + 高偏移
        elif variance_ratio < 0.05 and global_std > 1e-6:
            if mean_shift_z > 2.0:
                # 偏移穩態: 方差低但均值偏了
                _shift_val = seg_mean - global_mean
                cls.update(
                    type="SHIFTED_STABLE",
                    confidence=min(0.95, mean_shift_z / 4),
                    description=f"偏移穩態: 偏移 {_shift_val:+.4f} ({mean_shift_z:.1f}σ), 方差僅 {variance_ratio:.1%}",
                )
            else:
                # 低方差且無偏移 = 正常穩定，跳過
                continue

        # 不符合任何肉眼級條件 → 不回報
        else:
            continue

        # --- Severity scoring ---
        atype = cls["type"]
        if atype == "SHIFTED_STABLE":
            sev = min(10, 4 + mean_shift_z * 0.8)
        elif atype == "OSCILLATION":
            sev = min(10, 5 + variance_ratio * 1.5)
        elif atype == "SPIKE":
            max_dev_z = abs(segment - global_mean).max() / (global_std + 1e-10)
            sev = min(10, 4 + max_dev_z * 0.8)
        elif atype == "DRIFT":
            sev = min(10, 5 + trend_strength * 1.5)
        elif atype == "DIP_RECOVERY":
            sev = min(10, 4 + variance_ratio * 1.5)
        elif atype == "LEVEL_SHIFT":
            sev = min(10, 5 + mean_shift_z * 0.8)
        else:
            sev = 3.0

        sev_label = (
            "CRITICAL"
            if sev >= 8
            else "HIGH"
            if sev >= 6
            else "MEDIUM"
            if sev >= 4
            else "LOW"
        )

        segments.append(
            {
                "start": start,
                "end": end,
                "length": seg_len,
                "type": atype,
                "type_cn": _TYPE_CN.get(atype, atype),
                "severity": sev_label,
                "severity_score": round(sev, 2),
                "confidence": round(cls.get("confidence", 0.5), 2),
                "description": cls.get("description", ""),
            }
        )

    # 按嚴重度排序
    segments.sort(key=lambda x: x["severity_score"], reverse=True)

    # ================================================================
    # Step 3: 獨立邊緣偵測 (LEVEL_SHIFT) — 補抓窗口掃不到的跳變
    # ================================================================
    try:
        _edge_win = max(10, n // 50)
        _ma = values.rolling(_edge_win, center=True).mean().dropna()
        _ma_diff = _ma.diff().abs()
        _edge_thresh = global_std * 3.0  # 肉眼級
        _edge_points = _ma_diff[_ma_diff > _edge_thresh].index.tolist()

        # 合併相近的邊緣點
        _edges = []
        for ep in _edge_points:
            if _edges and ep - _edges[-1] < _edge_win * 2:
                continue  # 跳過太近的
            _edges.append(ep)

        # 檢查是否已有覆蓋此邊緣的 segment
        _existing_ranges = [(s["start"], s["end"]) for s in segments]
        _half = max(5, _edge_win // 2)
        for ep in _edges:
            s = max(0, ep - _half)
            e = min(n - 1, ep + _half)
            # 已有 segment 覆蓋 → 跳過
            _covered = any(es <= ep <= ee for es, ee in _existing_ranges)
            if _covered:
                continue
            # 計算跳變量
            _before = values.iloc[max(0, ep - _half) : ep].mean()
            _after = values.iloc[ep : min(n, ep + _half)].mean()
            _shift = _after - _before
            _shift_z = abs(_shift) / (global_std + 1e-10)
            if _shift_z < 3.0:  # 肉眼級
                continue
            _sev = min(10, 5 + _shift_z * 0.8)
            _sev_label = "CRITICAL" if _sev >= 8 else "HIGH" if _sev >= 6 else "MEDIUM"
            segments.append(
                {
                    "start": s,
                    "end": e,
                    "length": e - s + 1,
                    "type": "LEVEL_SHIFT",
                    "type_cn": _TYPE_CN["LEVEL_SHIFT"],
                    "severity": _sev_label,
                    "severity_score": round(_sev, 2),
                    "confidence": round(min(0.95, _shift_z / 5), 2),
                    "description": f"水平跳變: 偏移 {_shift:+.2f} ({_shift_z:.1f}σ, 在 #{ep} 附近)",
                }
            )
        segments.sort(key=lambda x: x["severity_score"], reverse=True)
    except Exception as _e:
        print(f"[sigma] scan edge detection failed: {_e}")

    # ================================================================
    # Step 4: 大區段標註為 REGIME_CHANGE (不丟棄，改標註)
    # ================================================================
    _keep_always = {"LEVEL_SHIFT", "SHIFTED_STABLE", "DIP_RECOVERY", "SPIKE"}
    for seg in segments:
        if seg["type"] not in _keep_always and seg["length"] > n * 0.1:
            col_name = series.name or "unnamed"
            print(
                f"[sigma] scan: #{seg['start']}-{seg['end']} "
                f"({seg['length']} 點, {seg['length'] / n:.0%}, {seg['type']}) → REGIME_CHANGE"
            )
            seg["original_type"] = seg["type"]
            seg["type"] = "REGIME_CHANGE"
            seg["type_cn"] = _TYPE_CN["REGIME_CHANGE"]
            seg["description"] = (
                f"狀態切換 (原判定: {seg['original_type']}): {seg['description']}"
            )

    has_anomaly = len(segments) > 0
    col_name = series.name or "unnamed"
    if segments:
        print(f"[sigma] scan_anomaly_segments '{col_name}': {len(segments)} 個區段")
        for seg in segments[:5]:
            print(
                f"  #{seg['start']}-{seg['end']}: {seg['type']}({seg['type_cn']}) "
                f"sev={seg['severity_score']}"
            )
    else:
        print(f"[sigma] scan_anomaly_segments '{col_name}': 無異常區段")

    _result = {
        "segments": segments,
        "total_segments": len(segments),
        "has_anomaly": has_anomaly,
    }

    # Auto chart: 趨勢圖 + 異常區段標記
    if auto_chart and has_anomaly:
        try:
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(12, 4))
            ax.plot(values.values, color="#3B82F6", linewidth=0.8, label=col_name)

            _colors = {
                "DRIFT": "#F59E0B",
                "OSCILLATION": "#8B5CF6",
                "SPIKE": "#EF4444",
                "DIP_RECOVERY": "#EC4899",
                "LEVEL_SHIFT": "#F97316",
                "SHIFTED_STABLE": "#06B6D4",
                "REGIME_CHANGE": "#9CA3AF",
            }
            _plotted_types = set()
            _type_zh = {
                "DRIFT": "漂移",
                "OSCILLATION": "震盪",
                "SPIKE": "突波",
                "DIP_RECOVERY": "急跌恢復",
                "LEVEL_SHIFT": "水平跳變",
                "SHIFTED_STABLE": "偏移穩態",
                "REGIME_CHANGE": "狀態切換",
            }
            for seg in segments[:8]:
                c = _colors.get(seg["type"], "#EF4444")
                label = seg["type"] if seg["type"] not in _plotted_types else None
                ax.axvspan(seg["start"], seg["end"], alpha=0.25, color=c, label=label)
                _plotted_types.add(seg["type"])
                # 文字標籤
                _mid_x = (seg["start"] + seg["end"]) / 2
                _y_pos = ax.get_ylim()[1] - (ax.get_ylim()[1] - ax.get_ylim()[0]) * 0.05
                _zh = _type_zh.get(seg["type"], seg["type"])
                ax.text(
                    _mid_x,
                    _y_pos,
                    f"{_zh}\nsev={seg['severity_score']:.1f}",
                    ha="center",
                    va="top",
                    fontsize=7,
                    fontweight="bold",
                    color=c,
                    alpha=0.9,
                )

            ax.set_title(f"異常掃描: {col_name}", fontsize=11, fontweight="bold")
            ax.set_xlabel("樣本序號")
            ax.legend(loc="upper right", fontsize=8)
            ax.grid(True, alpha=0.3)
            plt.tight_layout()
            plt.show()
            plt.close(fig)
        except Exception as _chart_err:
            print(f"[sigma] scan chart 繪圖失敗: {_chart_err}")

    return _result


# ============================================================
# 10. 頻率分析 (FFT)
# ============================================================


def frequency_analysis(
    series: pd.Series, top_n: int = 5, auto_chart: bool = True
) -> Dict:
    """
    頻率分析 — 用 FFT 找出主要頻率成分。

    Returns:
        - dominant_frequencies: [(頻率, 振幅, 週期)]
    """
    values = series.dropna().values
    n = len(values)
    if n < 20:
        return {"error": "資料太少"}

    # 去均值
    values = values - np.mean(values)
    fft_vals = np.fft.rfft(values)
    freqs = np.fft.rfftfreq(n)
    magnitudes = np.abs(fft_vals)

    # 排除 DC 分量
    magnitudes[0] = 0
    top_idx = np.argsort(magnitudes)[::-1][:top_n]

    results = []
    for idx in top_idx:
        if magnitudes[idx] > 0:
            freq = freqs[idx]
            period = 1.0 / freq if freq > 0 else float("inf")
            results.append(
                (
                    round(float(freq), 6),
                    round(float(magnitudes[idx]), 4),
                    round(float(period), 1),
                )
            )

    print(f"[sigma] 頻率分析 '{series.name}':")
    for freq, mag, period in results:
        print(f"  頻率={freq:.4f}, 振幅={mag:.1f}, 週期={period:.1f} 筆")

    _result = {"dominant_frequencies": results}
    if auto_chart and results:
        try:
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(10, 5))
            ax.plot(freqs[1:], magnitudes[1:], color="#3B82F6")
            for freq, mag, period in results[:3]:
                ax.axvline(x=freq, color="#EF4444", linestyle="--", alpha=0.7)
            ax.set_title(
                f"頻率分析 '{series.name}': 主頻={results[0][0]:.4f}, 週期={results[0][2]:.1f}筆",
                fontsize=11,
                fontweight="bold",
            )
            ax.set_xlabel("頻率")
            ax.set_ylabel("振幅")
            ax.grid(True, alpha=0.3)
            plt.tight_layout()
            plt.show()
            plt.close(fig)
        except Exception:
            pass
    return _result


# ============================================================
# 11. 殘差分析
# ============================================================


def residual_analysis(
    df: pd.DataFrame,
    target: str,
    predictors: Optional[List[str]] = None,
    auto_chart: bool = True,
) -> Dict:
    """
    殘差分析 — 用線性回歸預測 target，分析殘差找隱性異常。

    Returns:
        - residuals: np.ndarray
        - r_squared: float
        - residual_std: float
        - large_residual_indices: 殘差超過 2σ 的 row index
    """
    if target not in df.columns:
        return {"error": f"找不到目標欄位 {target}"}

    if predictors:
        X_cols = [c for c in predictors if c in df.columns and c != target]
    else:
        X_cols = [c for c in df.columns if c != target]

    X = df[X_cols].values
    y = df[target].values

    # OLS
    beta, residuals_ss, _, _ = np.linalg.lstsq(
        np.column_stack([np.ones(len(X)), X]), y, rcond=None
    )
    y_pred = np.column_stack([np.ones(len(X)), X]) @ beta
    resid = y - y_pred

    ss_res = np.sum(resid**2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    resid_std = float(np.std(resid))

    large_idx = np.where(np.abs(resid) > 2 * resid_std)[0]

    print(f"[sigma] 殘差分析 (target={target}):")
    print(f"  R² = {r2:.4f}")
    print(f"  殘差 σ = {resid_std:.4f}")
    print(f"  大殘差點 (>2σ): {len(large_idx)} 個")

    _result = {
        "residuals": resid,
        "r_squared": round(r2, 4),
        "residual_std": round(resid_std, 4),
        "large_residual_indices": large_idx.tolist(),
    }
    if auto_chart:
        try:
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(10, 5))
            ax.scatter(range(len(resid)), resid, s=10, color="#3B82F6", alpha=0.6)
            ax.axhline(
                y=2 * resid_std,
                color="#EF4444",
                linestyle="--",
                label=f"2σ={2 * resid_std:.2f}",
            )
            ax.axhline(y=-2 * resid_std, color="#EF4444", linestyle="--")
            ax.set_title(
                f"殘差分析 (target={target}): R²={r2:.3f}, {len(large_idx)}筆超 2σ",
                fontsize=11,
                fontweight="bold",
            )
            ax.legend()
            ax.grid(True, alpha=0.3)
            plt.tight_layout()
            plt.show()
            plt.close(fig)
        except Exception:
            pass
    return _result


# ============================================================
# 12. PCA 降維
# ============================================================


def pca_analysis(
    df: pd.DataFrame, n_components: int = 5, auto_chart: bool = True
) -> Dict:
    """
    PCA 降維分析 — 找出主成分及其貢獻度。

    Returns:
        - explained_variance_ratio: 各主成分的解釋變異比例
        - cumulative_variance: 累積解釋變異
        - top_loadings: 每個主成分中權重最大的欄位
        - transformed: PCA 後的資料矩陣
    """
    from sklearn.decomposition import PCA
    from sklearn.preprocessing import StandardScaler

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(df)

    n_comp = min(n_components, len(df.columns), len(df))
    pca = PCA(n_components=n_comp, random_state=42)
    transformed = pca.fit_transform(X_scaled)

    loadings = pd.DataFrame(
        pca.components_.T,
        index=df.columns,
        columns=[f"PC{i + 1}" for i in range(n_comp)],
    )

    top_loadings = {}
    for i in range(n_comp):
        pc = f"PC{i + 1}"
        abs_loadings = loadings[pc].abs().sort_values(ascending=False)
        top_loadings[pc] = [
            (col, round(float(loadings[pc][col]), 4)) for col in abs_loadings.index[:5]
        ]

    print(f"[sigma] PCA 分析 ({n_comp} 主成分):")
    for i in range(n_comp):
        pct = pca.explained_variance_ratio_[i] * 100
        cum = sum(pca.explained_variance_ratio_[: i + 1]) * 100
        print(f"  PC{i + 1}: {pct:.1f}% (累積 {cum:.1f}%)")
        for col, w in top_loadings[f"PC{i + 1}"][:3]:
            print(f"    {col}: {w:.4f}")

    _result = {
        "explained_variance_ratio": [
            round(float(r), 4) for r in pca.explained_variance_ratio_
        ],
        "cumulative_variance": [
            round(float(sum(pca.explained_variance_ratio_[: i + 1])), 4)
            for i in range(n_comp)
        ],
        "top_loadings": top_loadings,
        "transformed": transformed,
    }
    if auto_chart:
        try:
            import matplotlib.pyplot as plt

            cum = [sum(pca.explained_variance_ratio_[: i + 1]) for i in range(n_comp)]
            fig, ax = plt.subplots(figsize=(8, 5))
            ax.bar(
                range(1, n_comp + 1),
                pca.explained_variance_ratio_,
                color="#3B82F6",
                alpha=0.7,
                label="個別",
            )
            ax.plot(range(1, n_comp + 1), cum, "ro-", label="累積")
            ax.set_title(
                f"PCA: 前 {n_comp} 成分累積 {cum[-1]:.0%}",
                fontsize=11,
                fontweight="bold",
            )
            ax.set_xlabel("主成分")
            ax.set_ylabel("解釋變異比例")
            ax.legend()
            ax.grid(True, alpha=0.3)
            plt.tight_layout()
            plt.show()
            plt.close(fig)
        except Exception:
            pass
    return _result


# ============================================================
# 13. 控制迴路評估
# ============================================================


def control_loop_assessment(
    pv_series: pd.Series, sp_value: Optional[float] = None, auto_chart: bool = True
) -> Dict:
    """
    控制迴路品質評估 — Harris Index + 追蹤誤差。

    Args:
        pv_series: 製程變數序列 (Process Variable)
        sp_value: 設定值 (Set Point)，不指定則用均值

    Returns:
        - tracking_error_mean, tracking_error_std
        - harris_index: 控制效率 (0~1, 越高越好)
        - saturation_ratio: 卡在極值的比例
        - assessment: 'excellent' / 'good' / 'poor' / 'unstable'
    """
    values = pv_series.dropna().values
    if sp_value is None:
        sp_value = np.mean(values)

    # 追蹤誤差
    errors = values - sp_value
    te_mean = float(np.mean(errors))
    te_std = float(np.std(errors))

    # Harris Index (MVC 比值估計)
    # 簡化版: 用一階差分的變異數比原始變異數
    diff_var = np.var(np.diff(values))
    orig_var = np.var(values)
    harris = 1.0 - (diff_var / (2 * orig_var)) if orig_var > 0 else 0
    harris = max(0, min(1, harris))

    # 飽和偵測 (卡在極值)
    q01 = np.percentile(values, 1)
    q99 = np.percentile(values, 99)
    sat_count = np.sum((values <= q01) | (values >= q99))
    sat_ratio = sat_count / len(values)

    if harris > 0.8 and te_std < np.std(values) * 0.3:
        assessment = "excellent"
    elif harris > 0.5:
        assessment = "good"
    elif harris > 0.2:
        assessment = "poor"
    else:
        assessment = "unstable"

    print(f"[sigma] 控制迴路評估 '{pv_series.name}':")
    print(f"  Harris Index = {harris:.3f}")
    print(f"  追蹤誤差: mean={te_mean:.4f}, std={te_std:.4f}")
    print(f"  飽和比例 = {sat_ratio:.2%}")
    print(f"  評估: {assessment}")

    _result = {
        "tracking_error_mean": round(te_mean, 4),
        "tracking_error_std": round(te_std, 4),
        "harris_index": round(harris, 4),
        "saturation_ratio": round(sat_ratio, 4),
        "assessment": assessment,
    }
    if auto_chart:
        try:
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(10, 4))
            ax.plot(values, color="#3B82F6", linewidth=0.8, label="PV")
            ax.axhline(
                y=sp_value, color="#EF4444", linestyle="--", label=f"SP={sp_value:.2f}"
            )
            ax.set_title(
                f"控制迴路 '{pv_series.name}': {assessment}",
                fontsize=11,
                fontweight="bold",
            )
            ax.legend()
            ax.grid(True, alpha=0.3)
            plt.tight_layout()
            plt.show()
            plt.close(fig)
        except Exception:
            pass
    return _result


# ============================================================
# 14. 操作窗口生成
# ============================================================


def operating_window(
    df: pd.DataFrame,
    target: str,
    direction: str = "maximize",
    top_k: int = 10,
    auto_chart: bool = True,
) -> Dict:
    """
    自動生成操作窗口 (SOP 建議)。
    根據 target 的好壞分組，找出每個欄位的最佳操作範圍。

    Args:
        target: 目標欄位
        direction: 'maximize' 或 'minimize'
    """
    if target not in df.columns:
        return {"error": f"找不到 {target}"}

    y = df[target]
    threshold = y.median()
    if direction == "maximize":
        good_mask = y > threshold
    else:
        good_mask = y < threshold

    good = df[good_mask]
    bad = df[~good_mask]

    windows = []
    # 計算每個欄位跟 target 的相關係數
    _corr_with_target = {}
    _numeric_cols = df.select_dtypes(include="number").columns
    for col in _numeric_cols:
        if col == target:
            continue
        _pair = df[[target, col]].dropna()
        if len(_pair) >= 10:
            _r = float(_pair.corr().iloc[0, 1])
            if not np.isnan(_r):
                _corr_with_target[col] = _r

    for col in df.columns:
        if col == target:
            continue
        g_mean, g_std = good[col].mean(), good[col].std()
        b_mean = bad[col].mean()
        diff = abs(g_mean - b_mean)
        _r = _corr_with_target.get(col, 0.0)
        _abs_r = abs(_r)
        # 只保留有一定相關性的參數 (|r| > 0.1)
        if _abs_r < 0.1:
            continue
        if g_std > 0:
            # 複合分數 = |r| × diff（相關性加權的差異量）
            _weighted_score = _abs_r * diff
            window = {
                "parameter": col,
                "optimal_range": (
                    round(float(g_mean - g_std), 4),
                    round(float(g_mean + g_std), 4),
                ),
                "optimal_mean": round(float(g_mean), 4),
                "diff_vs_bad": round(float(diff), 4),
                "correlation_with_target": round(float(_r), 4),
                "abs_correlation": round(float(_abs_r), 4),
                "weighted_score": round(float(_weighted_score), 4),
                "operating_range_min": round(float(g_mean - g_std), 4),
                "operating_range_max": round(float(g_mean + g_std), 4),
                "suggested_target": round(float(g_mean), 4),
            }
            windows.append(window)

    # 用 weighted_score (|r| × diff) 排序，而非單純 diff
    windows.sort(key=lambda x: x["weighted_score"], reverse=True)

    print(f"[sigma] 操作窗口 (target={target}, {direction}):")
    for w in windows[:top_k]:
        lo, hi = w["optimal_range"]
        print(
            f"  {w['parameter']}: [{lo:.2f} ~ {hi:.2f}] "
            f"(r={w['correlation_with_target']:+.4f}, diff={w['diff_vs_bad']:.2f}, "
            f"score={w['weighted_score']:.2f})"
        )

    # sop_recommendations 格式 (供 LLM code 使用)
    _sop = []
    for w in windows[:top_k]:
        _sop.append(
            {
                "parameter": w["parameter"],
                "suggested_target": w["suggested_target"],
                "operating_range_min": w["operating_range_min"],
                "operating_range_max": w["operating_range_max"],
                "correlation_with_target": w["correlation_with_target"],
                "diff_vs_bad": w["diff_vs_bad"],
                "weighted_score": w["weighted_score"],
            }
        )

    _result = {
        "windows": windows[:top_k],
        "sop_recommendations": _sop,
        "good_batch_count": int(good_mask.sum()),
    }
    if auto_chart and windows:
        _items = [(w["parameter"], w["weighted_score"]) for w in windows[:top_k]]
        _auto_bar_chart(
            _items,
            f"操作窗口 (target={target})",
            xlabel="|r| × 差異 (相關性加權分數)",
        )
    return _result


# ============================================================
# 15. 特徵重要性
# ============================================================


def feature_importance(
    df: pd.DataFrame,
    target: str,
    method: str = "random_forest",
    top_n: int = 15,
    auto_chart: bool = True,
) -> Dict:
    """
    計算各欄位對 target 的影響力排名。

    method: 'random_forest' or 'mutual_info'
    """
    if target not in df.columns:
        return {"error": f"找不到 {target}"}

    X = df.drop(columns=[target])
    y = df[target]

    if method == "random_forest":
        from sklearn.ensemble import RandomForestRegressor

        model = RandomForestRegressor(
            n_estimators=50, random_state=42, max_depth=10, n_jobs=-1
        )
        model.fit(X, y)
        importances = model.feature_importances_
    elif method == "mutual_info":
        from sklearn.feature_selection import mutual_info_regression

        importances = mutual_info_regression(X, y, random_state=42)
    else:
        return {"error": f"不支援 {method}"}

    ranking = sorted(zip(X.columns, importances), key=lambda x: x[1], reverse=True)

    print(f"[sigma] 特徵重要性 (target={target}, {method}):")
    for col, imp in ranking[:top_n]:
        print(f"  {col}: {imp:.4f}")

    _result = {"ranking": [(col, round(float(imp), 4)) for col, imp in ranking[:top_n]]}
    if auto_chart and ranking:
        _items = [(col, round(float(imp), 4)) for col, imp in ranking[:top_n]]
        _auto_bar_chart(_items, f"特徵重要性 (target={target})", xlabel="Importance")
    return _result


# ============================================================
# 16. 交叉相關 (時間延遲)
# ============================================================


def cross_correlation_lag(
    series_a: pd.Series, series_b: pd.Series, max_lag: int = 50, auto_chart: bool = True
) -> Dict:
    """
    交叉相關分析 — 找出兩個序列之間的最佳延遲。

    Returns:
        - best_lag: 最佳延遲 (正=A 領先 B)
        - best_correlation: 最佳延遲處的相關係數
        - lags: 所有延遲的相關係數
    """
    a = series_a.dropna().values
    b = series_b.dropna().values
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]

    # 標準化
    a = (a - np.mean(a)) / (np.std(a) + 1e-10)
    b = (b - np.mean(b)) / (np.std(b) + 1e-10)

    correlations = []
    for lag in range(-max_lag, max_lag + 1):
        if lag > 0:
            r = np.corrcoef(a[lag:], b[: n - lag])[0, 1]
        elif lag < 0:
            r = np.corrcoef(a[: n + lag], b[-lag:])[0, 1]
        else:
            r = np.corrcoef(a, b)[0, 1]
        correlations.append((lag, round(float(r), 4) if not np.isnan(r) else 0))

    best = max(correlations, key=lambda x: abs(x[1]))

    print(f"[sigma] 交叉相關 '{series_a.name}' vs '{series_b.name}':")
    print(f"  最佳延遲 = {best[0]} 筆 (r={best[1]:.4f})")

    _result = {
        "best_lag": best[0],
        "best_correlation": best[1],
        "lags": correlations,
    }
    if auto_chart:
        try:
            import matplotlib.pyplot as plt

            lags_x = [c[0] for c in correlations]
            lags_y = [c[1] for c in correlations]
            fig, ax = plt.subplots(figsize=(10, 4))
            ax.plot(lags_x, lags_y, color="#3B82F6")
            ax.axvline(x=best[0], color="#EF4444", linestyle="--")
            ax.set_title(
                f"交叉相關: lag={best[0]}, r={best[1]:.3f}",
                fontsize=11,
                fontweight="bold",
            )
            ax.set_xlabel("Lag")
            ax.set_ylabel("Correlation")
            ax.grid(True, alpha=0.3)
            plt.tight_layout()
            plt.show()
            plt.close(fig)
        except Exception:
            pass
    return _result


# ============================================================
# 17. 小波分析
# ============================================================


def wavelet_analysis(
    series: pd.Series, n_scales: int = 32, auto_chart: bool = True
) -> Dict:
    """
    小波分析 — 用 Morlet 小波分解時間序列的多尺度結構。

    Returns:
        - dominant_scale: 主要尺度
        - energy_by_scale: 各尺度的能量分佈
    """
    values = series.dropna().values
    n = len(values)
    if n < 20:
        return {"error": "資料太少"}

    # 簡化 Morlet 小波 (不需要 pywt)
    scales = np.arange(1, n_scales + 1)
    energy = np.zeros(len(scales))

    for i, scale in enumerate(scales):
        # Morlet wavelet kernel
        t = np.arange(-4 * scale, 4 * scale + 1)
        kernel = np.exp(-0.5 * (t / scale) ** 2) * np.cos(5 * t / scale)
        kernel = kernel / np.sqrt(scale)

        # Convolution
        if len(kernel) < n:
            conv = np.convolve(values, kernel, mode="same")
            energy[i] = np.sum(conv**2) / n
        else:
            energy[i] = 0

    dominant_idx = np.argmax(energy)
    dominant_scale = int(scales[dominant_idx])

    print(f"[sigma] 小波分析 '{series.name}':")
    print(f"  主要尺度 = {dominant_scale}")
    top_scales = np.argsort(energy)[::-1][:5]
    for idx in top_scales:
        print(f"  尺度 {scales[idx]}: 能量 = {energy[idx]:.2f}")

    _result = {
        "dominant_scale": dominant_scale,
        "energy_by_scale": [
            (int(scales[i]), round(float(energy[i]), 4)) for i in range(len(scales))
        ],
    }
    if auto_chart:
        try:
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(10, 4))
            ax.plot(scales, energy, color="#3B82F6")
            ax.axvline(x=dominant_scale, color="#EF4444", linestyle="--")
            ax.set_title(
                f"小波分析 '{series.name}': 主尺度={dominant_scale}",
                fontsize=11,
                fontweight="bold",
            )
            ax.set_xlabel("尺度")
            ax.set_ylabel("能量")
            ax.grid(True, alpha=0.3)
            plt.tight_layout()
            plt.show()
            plt.close(fig)
        except Exception:
            pass
    return _result


# ============================================================
# 18. 趨勢預測
# ============================================================


def trend_prediction(
    series: pd.Series, forecast_horizon: int = 20, auto_chart: bool = True
) -> Dict:
    """
    簡單趨勢預測 — 線性回歸 + 信賴區間。

    Returns:
        - forecast_values: 預測值
        - forecast_upper/lower: 95% 信賴區間
        - slope: 趨勢斜率
        - r_squared: 擬合度
    """
    values = series.dropna().values
    n = len(values)
    x = np.arange(n)

    # 線性回歸
    coeffs = np.polyfit(x, values, 1)
    slope, intercept = coeffs
    y_pred = np.polyval(coeffs, x)
    resid = values - y_pred
    resid_std = np.std(resid)

    ss_res = np.sum(resid**2)
    ss_tot = np.sum((values - np.mean(values)) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0

    # 預測
    x_future = np.arange(n, n + forecast_horizon)
    forecast = np.polyval(coeffs, x_future)
    upper = forecast + 1.96 * resid_std
    lower = forecast - 1.96 * resid_std

    print(f"[sigma] 趨勢預測 '{series.name}':")
    print(f"  斜率 = {slope:.6f}/筆")
    print(f"  R² = {r2:.4f}")
    print(f"  預測 {forecast_horizon} 筆: {forecast[0]:.2f} -> {forecast[-1]:.2f}")

    _result = {
        "forecast_values": forecast.tolist(),
        "forecast_upper": upper.tolist(),
        "forecast_lower": lower.tolist(),
        "slope": round(float(slope), 6),
        "r_squared": round(r2, 4),
    }
    if auto_chart:
        try:
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(10, 5))
            ax.plot(x, values, color="#3B82F6", label="實際")
            ax.plot(x, y_pred, color="#6B7280", linestyle="--", alpha=0.5, label="擬合")
            ax.plot(x_future, forecast, color="#EF4444", label="預測")
            ax.fill_between(
                x_future, lower, upper, color="#EF4444", alpha=0.1, label="95% CI"
            )
            ax.set_title(f"趨勢預測 '{series.name}'", fontsize=11, fontweight="bold")
            ax.legend()
            ax.grid(True, alpha=0.3)
            plt.tight_layout()
            plt.show()
            plt.close(fig)
        except Exception:
            pass
    return _result


# ============================================================
# 10. Preprocessor — deterministic pre-analysis
# ============================================================


def preprocess(
    df: pd.DataFrame,
    task_type: str = "global_analysis",
    target_params: Optional[List[str]] = None,
    target_range: Optional[List[str]] = None,
    baseline_range: Optional[str] = None,
) -> Dict:
    """
    Deterministic 前置分析 — 在 LLM Code Interpreter 之前跑完。

    回傳固定 schema 的 dict，包含通用摘要 + 劇本專屬分析結果。
    LLM 只需要讀 report 物件做深入分析，不需要自己跑偵察。

    Args:
        df: 純數值 DataFrame (df_numeric)
        task_type: route_intent 的 task_type
        target_params: route_intent 的 target_params (Y)
        target_range: route_intent 的 target_range (使用者指定區間 List[str])

    Returns:
        dict with keys: df_active, meta, stability, + scenario-specific keys
    """
    print("[preprocess] 開始前置分析...")

    # ========== 通用: 過濾死水欄位 ==========
    df_active, dead_cols = filter_dead_columns(df, keep_cols=target_params or [])
    n_rows, n_cols_active = df_active.shape

    # 記錄哪些 target_params 是被白名單保留的死水欄位
    _kept_dead_targets = [p for p in (target_params or []) if p in dead_cols]
    # 注意: dead_cols 是「被移除」的，白名單保留的不在裡面
    # 需要重新計算: 哪些 target 本來會被移除但被保留了
    _all_dead_candidates = set(dead_cols)
    _kept_dead_targets = []
    for p in target_params or []:
        if p in df.columns and p in df_active.columns and p not in _all_dead_candidates:
            # 在 active 裡但不在 dead 裡 → 可能是被白名單保留的
            s = df[p]
            std_val = s.std()
            median_val = s.median()
            mad_val = (s - median_val).abs().median()
            if std_val <= 1e-6 or (
                abs(median_val) > 1e-10 and (mad_val / abs(median_val)) < 0.01
            ):
                _kept_dead_targets.append(p)

    # top-10 CV（Coefficient of Variation）欄位——尺度無關
    _means = df_active.mean().abs().replace(0, np.nan)
    _cv = (df_active.std() / _means).dropna().sort_values(ascending=False)
    top_std_cols = _cv.head(10).index.tolist()

    meta = {
        "n_rows": n_rows,
        "n_cols_raw": len(df.columns),
        "n_cols_active": n_cols_active,
        "dropped_dead_cols": len(dead_cols),
        "top_std_cols": top_std_cols,
        "kept_dead_targets": _kept_dead_targets,
    }

    # ========== 通用: Hotelling T² (所有劇本都跑，用於 stability flags) ==========
    t2_result = hotelling_t2(df_active, auto_chart=False)
    anomaly_n = len(t2_result["anomaly_indices"])
    warn_indices = [
        i
        for i in range(n_rows)
        if t2_result["t2_values"][i] > t2_result.get("ucl_warn", float("inf"))
        and i not in t2_result["anomaly_indices"]
    ]

    stability = {
        "anomaly_n": anomaly_n,
        "allow_corr": anomaly_n >= 5,
        "allow_ttest": anomaly_n >= 5,
        "allow_heatmap": n_cols_active <= 20,
        "recommended": [],
    }

    # 推薦下一步
    if anomaly_n > 0 and anomaly_n < 5:
        stability["recommended"] = [
            "t2_contribution_per_anomaly",
            "window_expand",
            "robust_zscore",
        ]
    elif anomaly_n >= 5:
        stability["recommended"] = [
            "group_comparison",
            "corr_on_top_contributors",
            "violin_plot",
        ]
    else:
        stability["recommended"] = [
            "pca_structure",
            "drift_scan",
            "distribution_check",
        ]

    result = {
        "df_active": df_active,
        "meta": meta,
        "stability": stability,
    }

    # ========== 劇本分支 ==========
    anomaly_types = ("anomaly_detection", "global_analysis", "general")
    optim_types = ("optimization", "spec_recommendation")
    drift_types = ("drift_analysis",)

    _target_params = target_params or []
    _target_range = target_range or []

    if task_type in anomaly_types:
        # 異常檢測四場景分派
        has_params = bool(_target_params)
        has_range = bool(_target_range)
        if has_params and has_range:
            print(
                f"[preprocess] 場景 D: 目標參數+區間 params={_target_params}, range={_target_range}"
            )
            result.update(
                _preprocess_anomaly_D(
                    df_active,
                    t2_result,
                    warn_indices,
                    _target_params,
                    _target_range,
                    baseline_range,
                )
            )
        elif has_params:
            print(f"[preprocess] 場景 B: 目標參數 params={_target_params}")
            result.update(
                _preprocess_anomaly_B(
                    df_active, t2_result, warn_indices, _target_params
                )
            )
            result["requested_targets"] = _target_params
        elif has_range:
            print(f"[preprocess] 場景 C: 目標區間 range={_target_range}")
            result.update(
                _preprocess_anomaly_C(df_active, t2_result, warn_indices, _target_range)
            )
        else:
            print("[preprocess] 場景 A: 全域")
            result.update(_preprocess_anomaly(df_active, t2_result, warn_indices))

        # 全域/異常場景也疊加 drift scan（顯著漂移趨勢圖）
        try:
            _drift_result = _preprocess_drift(df_active)
            result.update(_drift_result)
        except Exception as _drift_e:
            print(f"[preprocess] drift scan 失敗 (不影響主分析): {_drift_e}")

        # 深入分析: 每個 Top-3 區間的 compare_groups + 相關性 + 漂移重疊
        try:
            _deep = _preprocess_deep_analysis(df_active, result)
            result.update(_deep)
        except Exception as _deep_e:
            print(f"[preprocess] deep analysis 失敗 (不影響主分析): {_deep_e}")
    elif task_type in optim_types:
        result.update(_preprocess_optimization(df_active, _target_params))
    elif task_type in drift_types:
        result.update(_preprocess_drift(df_active))
    else:
        # fallback: 做 anomaly 分支
        result.update(_preprocess_anomaly(df_active, t2_result, warn_indices))

    # top_std_cols 用 T² contribution 排名取代（比 CV 更有意義）
    _t2g = result.get("t2_contrib", {}).get("top_contributors_global", [])
    if _t2g:
        result["meta"]["top_std_cols"] = _t2g[:10]

    print("[preprocess] 前置分析完成")
    return result


def _preprocess_anomaly(
    df_active: pd.DataFrame, t2_result: Dict, warn_indices: List[int]
) -> Dict:
    """ANOMALY / EXPLORATORY 專屬前置分析"""
    anomaly_indices = t2_result["anomaly_indices"]

    # PCA
    pca_result = pca_analysis(df_active, auto_chart=False)
    # 攤平 top_loadings dict → deduplicated column list
    top_loading_cols = []
    seen = set()
    for _pc, items in pca_result.get("top_loadings", {}).items():
        for col, _load in items:
            if col not in seen:
                top_loading_cols.append(col)
                seen.add(col)

    # 擴展 anomaly_indices ±3 並分成區間
    _n_total = len(df_active)
    _expanded_set = set()
    for idx in anomaly_indices:
        for offset in range(-3, 4):
            ei = idx + offset
            if 0 <= ei < _n_total:
                _expanded_set.add(ei)
    _expanded_sorted = sorted(_expanded_set)

    # 分成連續區間
    _intervals = []
    if _expanded_sorted:
        _s = _expanded_sorted[0]
        _e = _s
        for v in _expanded_sorted[1:]:
            if v == _e + 1:
                _e = v
            else:
                _intervals.append((_s, _e))
                _s = v
                _e = v
        _intervals.append((_s, _e))

    # T² contribution per interval（只用超規點）
    _anomaly_set = set(anomaly_indices)  # 原始超 UCL 的點
    _t2_values = t2_result["t2_values"]
    top_contributors_by_interval = {}  # key = "start-end" 字串
    contribution_scores_by_interval = {}  # key = "start-end" -> [(col, score)]
    # Marginal drop per interval
    marginal_scores_by_interval = {}
    interval_scores = {}  # key -> float score
    core_indices_by_interval = {}  # key -> [actual anomaly indices]
    all_top = set()
    for s, e in _intervals:
        # 只取區間內實際超規的點
        interval_anomaly_idxs = [i for i in range(s, e + 1) if i in _anomaly_set]
        if not interval_anomaly_idxs:
            interval_anomaly_idxs = [s]  # fallback
        _iv_label = f"{s}-{e}"
        print(f"\n--- 區間 #{_iv_label} ({len(interval_anomaly_idxs)} 筆超規) ---")
        # 原始 T² contribution (保留做對照，top 3)
        c_scores, c_names = t2_contribution(
            df_active, interval_anomaly_idxs, top_n=3, auto_chart=False
        )
        top_3 = c_names[:3]
        top_3_scores = c_scores[:3]
        # Marginal drop (per interval, top 3)
        m_scores, _m_names = t2_contribution_marginal(
            df_active, interval_anomaly_idxs, top_n=3, auto_chart=False
        )
        marginal_top = m_scores[:3]

        top_contributors_by_interval[_iv_label] = top_3
        contribution_scores_by_interval[_iv_label] = top_3_scores
        marginal_scores_by_interval[_iv_label] = marginal_top
        all_top.update(top_3)

        # Interval scoring: max(T²) × sqrt(actual anomaly count)
        import math

        _core_idxs = interval_anomaly_idxs
        _max_t2 = max(
            (_t2_values[i] for i in _core_idxs if i < len(_t2_values)), default=0
        )
        _score = _max_t2 * math.sqrt(len(_core_idxs))
        interval_scores[_iv_label] = round(_score, 2)
        core_indices_by_interval[_iv_label] = _core_idxs
        print(f"  Score: {_score:.1f} (max_T²={_max_t2:.1f}, n_core={len(_core_idxs)})")

    # --- 排序並只保留 Top-3 ---
    _MAX_INTERVALS = 3
    _sorted_keys = sorted(interval_scores, key=interval_scores.get, reverse=True)
    _top_keys = _sorted_keys[:_MAX_INTERVALS]
    _low_keys = _sorted_keys[_MAX_INTERVALS:]
    if _low_keys:
        print(f"\n[Interval Prioritization] Top-{_MAX_INTERVALS}: {_top_keys}")
        print(f"  (略過 {len(_low_keys)} 個低優先區間: {_low_keys})")

    # Global: 原始 + Baseline 差分 + Marginal drop
    top_contributors_global = []
    contribution_scores_global = []
    baseline_scores_global = []
    marginal_scores_global = []
    if anomaly_indices:
        print(f"\n--- 全域 ({len(anomaly_indices)} 筆超規) ---")
        c_all_scores, c_all_names = t2_contribution(
            df_active, anomaly_indices, top_n=5, auto_chart=False
        )
        top_contributors_global = c_all_names[:5]
        contribution_scores_global = c_all_scores[:5]
        # Baseline 差分
        b_all_scores, _b_all_names = t2_contribution_baseline(
            df_active, anomaly_indices, top_n=5, auto_chart=False
        )
        baseline_scores_global = b_all_scores[:5]
        # Marginal drop
        m_all_scores, _m_all_names = t2_contribution_marginal(
            df_active, anomaly_indices, top_n=5, auto_chart=False
        )
        marginal_scores_global = m_all_scores[:5]

    # Overlap (Jaccard intersection between intervals)
    overlap = []
    if len(_intervals) == 2:
        keys = list(top_contributors_by_interval.keys())
        set1 = set(top_contributors_by_interval[keys[0]])
        set2 = set(top_contributors_by_interval[keys[1]])
        overlap = list(set1 & set2)

    result = {
        "hotelling": {
            "t2_values": t2_result["t2_values"],
            "ucl_99": t2_result["ucl"],
            "ucl_95": t2_result.get("ucl_warn", 0),
            "anomaly_indices": _expanded_sorted,  # 擴展後的區間 index
            "warn_indices": warn_indices,
            "pass1_extreme_indices": t2_result.get("pass1_extreme_indices", []),
            "pass2_anomaly_indices": t2_result.get("pass2_anomaly_indices", []),
        },
        "anomaly_intervals": _top_keys,  # Top-N only (sorted by score)
        "low_priority_intervals": _low_keys,  # 略過的低優先
        "interval_scores": interval_scores,  # all intervals -> score
        "core_indices_by_interval": core_indices_by_interval,  # actual anomaly indices
        "pca": {
            "explained_variance_ratio": pca_result["explained_variance_ratio"][:10],
            "top_loading_cols": top_loading_cols[:20],
            "scores": pca_result["transformed"][:, :2]
            if pca_result["transformed"].shape[1] >= 2
            else pca_result["transformed"],
        },
        "t2_contrib": {
            "top_contributors_global": top_contributors_global,
            "contribution_scores_global": contribution_scores_global,
            "top_contributors_by_interval": {
                k: v for k, v in top_contributors_by_interval.items() if k in _top_keys
            },
            "contribution_scores_by_interval": {
                k: v
                for k, v in contribution_scores_by_interval.items()
                if k in _top_keys
            },
            "overlap": overlap,
            # 新增：抗 level-shift 的 contribution methods
            "baseline_scores_global": baseline_scores_global,
            "marginal_scores_global": marginal_scores_global,
            "marginal_scores_by_interval": {
                k: v for k, v in marginal_scores_by_interval.items() if k in _top_keys
            },
        },
    }
    return result


def _pca_common(df_active: pd.DataFrame) -> Dict:
    """PCA 共用邏輯：回傳 pca 結果 dict + 攤平 top_loading_cols"""
    pca_result = pca_analysis(df_active, auto_chart=False)
    top_loading_cols = []
    seen = set()
    for _pc, items in pca_result.get("top_loadings", {}).items():
        for col, _load in items:
            if col not in seen:
                top_loading_cols.append(col)
                seen.add(col)
    return {
        "explained_variance_ratio": pca_result["explained_variance_ratio"][:10],
        "top_loading_cols": top_loading_cols[:20],
        "scores": pca_result["transformed"][:, :2]
        if pca_result["transformed"].shape[1] >= 2
        else pca_result["transformed"],
    }


def _parse_ranges(range_strs: List[str], n_total: int) -> List[tuple]:
    """解析 '50-69' 字串列表 → [(start, end), ...] 0-based index

    使用者輸入視為 1-based（第 50 筆 = index 49）。
    與 ci_helpers 的解析邏輯一致。
    """
    import re

    intervals = []
    for r in range_strs:
        m = re.match(r"(\d+)\s*[-~—]\s*(\d+)", str(r))
        if m:
            s = max(0, int(m.group(1)) - 1)  # user 1-based → 0-based
            e = min(n_total - 1, int(m.group(2)) - 1)
            if s <= e:
                intervals.append((s, e))
    return intervals


def _preprocess_anomaly_B(
    df_active: pd.DataFrame,
    t2_result: Dict,
    warn_indices: List[int],
    target_params: List[str],
) -> Dict:
    """場景 B: 有目標參數 — RF importance + zscore + drift + correlation + PCA"""
    from sklearn.ensemble import RandomForestRegressor

    valid_targets = [p for p in target_params if p in df_active.columns]
    _dropped = [p for p in target_params if p not in df_active.columns]
    if _dropped:
        print(f"[preprocess:B] ⚠️ 目標參數被移除 (死水欄位或不存在): {_dropped}")

    if not valid_targets:
        print(f"[preprocess:B] 目標參數 {target_params} 不在 df_active 中, fallback A")
        return _preprocess_anomaly(df_active, t2_result, warn_indices)

    # PCA
    pca_data = _pca_common(df_active)

    # RF feature importance (per Y)
    feature_importance = {}
    all_important_x = set()
    x_cols = [c for c in df_active.columns if c not in valid_targets]
    if x_cols:
        X = df_active[x_cols].fillna(0).values
        for y_col in valid_targets:
            y = df_active[y_col].fillna(0).values
            try:
                rf = RandomForestRegressor(
                    n_estimators=50, max_depth=5, random_state=42, n_jobs=-1
                )
                rf.fit(X, y)
                imp = sorted(
                    zip(x_cols, rf.feature_importances_),
                    key=lambda x: x[1],
                    reverse=True,
                )[:10]
                feature_importance[y_col] = [
                    (col, round(float(s), 4)) for col, s in imp
                ]
                all_important_x.update([col for col, _ in imp[:5]])
                print(
                    f"[preprocess:B] RF importance for {y_col}: {[c for c, _ in imp[:5]]}"
                )
            except Exception as e:
                print(f"[preprocess:B] RF failed for {y_col}: {e}")

    # robust_zscore per target (MAD-based, cap at 6%)
    target_zscore = {}
    _n_total = len(df_active)
    _max_outliers = max(1, int(_n_total * 0.06))
    for y_col in valid_targets:
        try:
            rz = robust_zscore(df_active[[y_col]], threshold=3.5, auto_chart=False)
            _oc = rz.get("outlier_count", 0)
            _oi = rz.get("outlier_indices", [])
            # Debug: log Z-score stats for diagnosis
            _s = df_active[y_col]
            _med = _s.median()
            _mad_raw = (_s - _med).abs().median()
            _max_val = _s.max()
            _z_max = 0.6745 * abs(_max_val - _med) / _mad_raw if _mad_raw > 1e-9 else 0
            print(
                f"[preprocess:B] {y_col}: median={_med:.2f}, MAD={_mad_raw:.4f}, "
                f"max={_max_val:.2f}, Z(max)={_z_max:.2f}, outliers={_oc}"
            )
            # Cap: 超過 6% 時只取 Z 值最大的 top 6%
            if _oc > _max_outliers and _oi:
                _series = df_active[y_col]
                _median = _series.median()
                _mad = (_series - _median).abs().median() * 1.4826
                if _mad > 0:
                    _z_vals = [
                        (_series.iloc[i] - _median).abs() / _mad
                        if i < len(_series)
                        else 0
                        for i in _oi
                    ]
                    _paired = sorted(
                        zip(_oi, _z_vals), key=lambda x: x[1], reverse=True
                    )
                    _oi = [idx for idx, _ in _paired[:_max_outliers]]
                    _oc = len(_oi)
                print(
                    f"[preprocess:B] {y_col}: {rz.get('outlier_count', 0)} 筆超過 6%, 截取 top {_oc} 筆"
                )
            target_zscore[y_col] = {
                "outlier_count": _oc,
                "outlier_indices": _oi[:30],
            }
            print(f"[preprocess:B] {y_col}: robust_zscore 異常 {_oc} 筆")
        except Exception as _e:
            print(f"[preprocess:B] {y_col} outlier detection failed: {_e}")
            target_zscore[y_col] = {"outlier_count": 0, "outlier_indices": []}

    # 單參數異常區間 + 異常類型分類
    target_anomaly_intervals = {}  # {y_col: ["s-e", ...]}
    target_anomaly_types = {}  # {y_col: [{"interval": "s-e", "type": ..., "confidence": ...}, ...]}
    _n_total = len(df_active)
    for y_col in valid_targets:
        _outlier_idx = target_zscore.get(y_col, {}).get("outlier_indices", [])
        if not _outlier_idx:
            target_anomaly_intervals[y_col] = []
            target_anomaly_types[y_col] = []
            continue
        # 分段成連續區間 (±2 擴展)
        _expanded = set()
        for idx in _outlier_idx:
            for off in range(-2, 3):
                ei = idx + off
                if 0 <= ei < _n_total:
                    _expanded.add(ei)
        _sorted = sorted(_expanded)
        _intervals = []
        if _sorted:
            _s = _sorted[0]
            _e = _s
            for v in _sorted[1:]:
                if v == _e + 1:
                    _e = v
                else:
                    _intervals.append((_s, _e))
                    _s = v
                    _e = v
            _intervals.append((_s, _e))

        _iv_labels = [f"{s}-{e}" for s, e in _intervals]
        target_anomaly_intervals[y_col] = _iv_labels

        # 對每個區間跑 classify_anomaly_type
        _types = []
        for s, e in _intervals:
            _seg = df_active[y_col].iloc[max(0, s - 5) : min(_n_total, e + 6)]
            if len(_seg) < 10:
                _seg = df_active[y_col].iloc[max(0, s - 10) : min(_n_total, e + 11)]
            try:
                ct = classify_anomaly_type(_seg, auto_chart=False)
                _types.append(
                    {
                        "interval": f"{s}-{e}",
                        "type": ct.get("type", "unknown"),
                        "confidence": ct.get("confidence", 0),
                    }
                )
                print(
                    f"[preprocess:B] {y_col} 區間 #{s}-{e}: {ct.get('type')} (信心度={ct.get('confidence', 0):.2f})"
                )
            except Exception:
                _types.append(
                    {"interval": f"{s}-{e}", "type": "unknown", "confidence": 0}
                )
        target_anomaly_types[y_col] = _types

    # segment_drift per target
    target_drift = {}
    for y_col in valid_targets:
        try:
            sd = segment_drift(df_active[y_col], auto_chart=False)
            _segs = sd.get("segments", [])
            target_drift[y_col] = {
                "segments": _segs,
                "drift_detected": len(_segs) > 0,
            }
        except Exception:
            pass

    # 滑動窗口異常掃描 per target
    target_scan = {}
    for y_col in valid_targets:
        try:
            scan = scan_anomaly_segments(df_active[y_col], auto_chart=False)
            target_scan[y_col] = {
                "segments": scan.get("segments", [])[:10],
                "has_anomaly": scan.get("has_anomaly", False),
            }
            if scan.get("has_anomaly"):
                print(
                    f"[preprocess:B] {y_col} 異常掃描: {scan['total_segments']} 個區段"
                )
        except Exception as _e:
            print(f"[preprocess:B] {y_col} scan_anomaly_segments failed: {_e}")

    # ========== V2 Deep Analysis: Drift-Primary + Change-Concurrent ==========
    # 1. drift regime 為主偵測器 (CUSUM change-points)
    # 2. scan 只補 ≤10pt 短期異常 (SPIKE, DIP_RECOVERY, OSCILLATION)
    # 3. change-concurrent 取代 T² contribution
    _n_total = len(df_active)
    _global_mean = df_active.mean()
    _global_std = df_active.std().replace(0, np.nan)

    # 合併後的異常段結果 (替代原本的 target_scan)
    target_anomaly_segments = {}  # {y_col: {"segments": [...], "has_anomaly": bool}}

    for y_col in valid_targets:
        merged_segments = []
        _vals = df_active[y_col].values if y_col in df_active.columns else None
        if _vals is None:
            continue

        _y_mean = np.mean(_vals)
        _y_std = np.std(_vals)
        if _y_std < 1e-10:
            target_anomaly_segments[y_col] = {"segments": [], "has_anomaly": False}
            continue

        # --- Step 1: 從 drift 結果生成異常 regime ---
        _drift_info = target_drift.get(y_col, {})
        _drift_segs = _drift_info.get("segments", [])
        _drift_ranges = set()  # 用於 scan 去重

        for dseg in _drift_segs:
            ds, de = dseg["start"], min(dseg["end"], _n_total - 1)
            _direction = dseg.get("direction", "up")
            seg_vals = _vals[ds : de + 1]
            if len(seg_vals) < 3:
                continue

            seg_mean = np.mean(seg_vals)
            seg_std = np.std(seg_vals)
            mean_shift = abs(seg_mean - _y_mean) / _y_std

            # 分類 drift segment
            # 檢查段內是否有趨勢 (Spearman)
            from scipy.stats import spearmanr

            _x_idx = np.arange(len(seg_vals))
            _rho, _p = spearmanr(_x_idx, seg_vals) if len(seg_vals) >= 5 else (0, 1)
            _has_trend = abs(_rho) > 0.4 and _p < 0.1

            if _has_trend and abs(_rho) > 0.5:
                _seg_type = "DRIFT"
                _type_cn = "漂移"
                _desc = f"{'上升' if _rho > 0 else '下降'}趨勢 (ρ={_rho:.2f})"
                _severity = min(10, mean_shift * 2 + abs(_rho) * 3)
            elif mean_shift > 2.0:
                if seg_std / _y_std < 0.5:
                    _seg_type = "SHIFTED_STABLE"
                    _type_cn = "偏移穩態"
                    _desc = f"均值偏移 {mean_shift:.1f}σ，段內穩定"
                    _severity = min(10, mean_shift * 2)
                else:
                    _seg_type = "LEVEL_SHIFT"
                    _type_cn = "水平跳變"
                    _desc = f"均值偏移 {mean_shift:.1f}σ"
                    _severity = min(10, mean_shift * 2.5)
            elif mean_shift > 1.5:
                _seg_type = "LEVEL_SHIFT"
                _type_cn = "水平跳變"
                _desc = f"均值偏移 {mean_shift:.1f}σ"
                _severity = min(10, mean_shift * 2)
            else:
                # 偏移太小，不計入異常
                continue

            seg_entry = {
                "start": ds,
                "end": de,
                "length": de - ds + 1,
                "type": _seg_type,
                "type_cn": _type_cn,
                "direction": _direction,
                "description": _desc,
                "severity_score": round(_severity, 2),
                "confidence": round(min(1.0, mean_shift / 3), 2),
                "mean_shift_sigma": round(mean_shift, 2),
                "source": "drift",
            }

            # --- Change-concurrent analysis (drift segment) ---
            # 比較 change-point 前/後各 N 點的均值差
            _ctx_n = max(10, (de - ds + 1))  # context 大小 = 至少區段長度
            _before_start = max(0, ds - _ctx_n)
            _after_end = min(_n_total, de + 1 + _ctx_n)
            _before = df_active.iloc[_before_start:ds]
            _after = df_active.iloc[ds : de + 1]

            if len(_before) >= 5 and len(_after) >= 3:
                _before_mean = _before.mean()
                _before_std = _before.std().replace(0, np.nan)
                _after_mean = _after.mean()
                _z_shift = ((_after_mean - _before_mean) / _before_std).dropna().abs()
                # 排除目標欄位本身
                _z_shift = _z_shift.drop(y_col, errors="ignore")
                _top_z = _z_shift.nlargest(5)

                seg_entry["top_factors"] = [
                    {
                        "col": col,
                        "z_diff": round(float(min(z, 20.0)), 2),
                        "before_mean": round(float(_before_mean.get(col, 0)), 4),
                        "after_mean": round(float(_after_mean.get(col, 0)), 4),
                        "method": "change_concurrent",
                    }
                    for col, z in _top_z.items()
                    if z > 0.5  # 只保留有意義的偏移
                ][:5]

                if seg_entry["top_factors"]:
                    _top3 = ", ".join(
                        f"{f['col']}(z={f['z_diff']:.1f})"
                        for f in seg_entry["top_factors"][:3]
                    )
                    print(
                        f"[preprocess:B] {y_col} #{ds}-{de} "
                        f"({_seg_type}) 同步變化: {_top3}"
                    )

            merged_segments.append(seg_entry)
            _drift_ranges.update(range(ds, de + 1))

        # --- Step 2: Scan 只取 ≤10pt 短期異常 ---
        _scan_info = target_scan.get(y_col, {})
        _scan_segs = _scan_info.get("segments", [])
        _SHORT_TYPES = {"SPIKE", "DIP_RECOVERY", "OSCILLATION"}
        for sseg in _scan_segs:
            _ss, _se = sseg["start"], sseg["end"]
            _slen = sseg.get("length", _se - _ss + 1)
            _stype = sseg.get("type", "")

            # 只保留短期 + 正確類型 + 不跟 drift 重疊
            if _slen > 10:
                continue
            if _stype not in _SHORT_TYPES:
                continue
            # 檢查重疊
            _seg_set = set(range(_ss, _se + 1))
            if _seg_set & _drift_ranges:
                continue

            # windowed z-diff: 比較異常段 vs 相鄰正常段
            _neighbor_start = max(0, _ss - 20)
            _neighbor_end = min(_n_total, _se + 21)
            _neighbor_idx = [
                i
                for i in range(_neighbor_start, _neighbor_end)
                if i not in _seg_set and i not in _drift_ranges
            ]
            _anom_idx = list(range(_ss, _se + 1))

            if len(_neighbor_idx) >= 10:
                _anom_data = df_active.iloc[_anom_idx]
                _neigh_data = df_active.iloc[_neighbor_idx]
                _anom_mean = _anom_data.mean()
                _neigh_mean = _neigh_data.mean()
                _neigh_std = _neigh_data.std().replace(0, np.nan)
                _z_diff = ((_anom_mean - _neigh_mean) / _neigh_std).dropna().abs()
                _z_diff = _z_diff.drop(y_col, errors="ignore")
                _top_z = _z_diff.nlargest(5)

                sseg["top_factors"] = [
                    {
                        "col": col,
                        "z_diff": round(float(min(z, 20.0)), 2),
                        "anom_mean": round(float(_anom_mean.get(col, 0)), 4),
                        "neighbor_mean": round(float(_neigh_mean.get(col, 0)), 4),
                        "method": "windowed_z_diff",
                    }
                    for col, z in _top_z.items()
                    if z > 0.5
                ][:5]

            sseg["source"] = "scan"
            merged_segments.append(sseg)

        # 按 start 排序
        merged_segments.sort(key=lambda s: s["start"])

        target_anomaly_segments[y_col] = {
            "segments": merged_segments[:10],
            "has_anomaly": len(merged_segments) > 0,
        }
        if merged_segments:
            print(
                f"[preprocess:B] {y_col}: "
                f"{len([s for s in merged_segments if s.get('source') == 'drift'])} drift + "
                f"{len([s for s in merged_segments if s.get('source') == 'scan'])} scan = "
                f"{len(merged_segments)} 個異常段"
            )

    # 將合併結果存入 target_scan (覆蓋，保持下游相容)
    target_scan = target_anomaly_segments

    # cross_correlation_lag: top important X vs each target Y
    target_lag = {}
    if all_important_x:
        _lag_feats = list(all_important_x)[:5]
        _available_feats = [c for c in _lag_feats if c in df_active.columns]
        for y_col in valid_targets:
            _lag_info = {}
            for _feat in _available_feats:
                try:
                    ccl = cross_correlation_lag(
                        df_active[_feat],
                        df_active[y_col],
                        max_lag=min(30, len(df_active) // 5),
                        auto_chart=False,
                    )
                    if isinstance(ccl, dict):
                        _lag_info[_feat] = {
                            "best_lag": ccl.get("best_lag", 0),
                            "best_correlation": round(
                                float(ccl.get("best_correlation", 0)), 4
                            ),
                        }
                except Exception:
                    pass
            if _lag_info:
                target_lag[y_col] = _lag_info
                _delayed = [f for f, v in _lag_info.items() if abs(v["best_lag"]) > 2]
                if _delayed:
                    print(f"[preprocess:B] {y_col} 有延遲效應的特徵: {_delayed}")

    # correlation 之間
    corr_matrix = {}
    if len(valid_targets) >= 2:
        try:
            corr_matrix["target_corr"] = df_active[valid_targets].corr().to_dict()
        except Exception:
            pass
    # target vs important X
    corr_with_x = {}
    if all_important_x:
        top_x_list = list(all_important_x)[:10]
        available = [c for c in top_x_list if c in df_active.columns]
        if available:
            for y_col in valid_targets:
                try:
                    corrs = df_active[available + [y_col]].corr()[y_col].drop(y_col)
                    corr_with_x[y_col] = [
                        (col, round(float(v), 4))
                        for col, v in corrs.abs().sort_values(ascending=False).items()
                    ][:5]
                except Exception:
                    pass

    # Hotelling (保留基本資訊)
    anomaly_indices = t2_result["anomaly_indices"]

    # 共同高相關欄位（多目標時自動計算）
    common_corr = []
    if len(valid_targets) >= 2:
        try:
            _all_corrs = {}
            for y_col in valid_targets:
                _c = df_active.drop(columns=valid_targets, errors="ignore").corrwith(
                    df_active[y_col]
                )
                _all_corrs[y_col] = _c.abs()
            _corr_df = pd.DataFrame(_all_corrs).dropna()
            _corr_df["min_abs_r"] = _corr_df.min(axis=1)
            _top = _corr_df.nlargest(5, "min_abs_r")
            for col, row in _top.iterrows():
                common_corr.append(
                    {
                        "col": col,
                        "min_abs_r": round(float(row["min_abs_r"]), 4),
                        "per_target": {
                            t: round(float(row[t]), 4) for t in valid_targets
                        },
                    }
                )
            if common_corr:
                print(f"[preprocess:B] 共同高相關欄位 (min|r|):")
                for cc in common_corr:
                    parts = ", ".join(
                        f"{t}={cc['per_target'][t]:.3f}" for t in valid_targets
                    )
                    print(f"  {cc['col']}: min|r|={cc['min_abs_r']:.3f} ({parts})")
        except Exception as _e:
            print(f"[preprocess:B] common_corr failed: {_e}")

    return {
        "scenario": "B",
        "hotelling": {
            "t2_values": t2_result["t2_values"],
            "ucl_99": t2_result["ucl"],
            "ucl_95": t2_result.get("ucl_warn", 0),
            "anomaly_indices": anomaly_indices,
            "warn_indices": warn_indices,
        },
        "pca": pca_data,
        "target_analysis": {
            "target_params": valid_targets,
            "feature_importance": feature_importance,
            "important_x": sorted(all_important_x),
            "zscore": target_zscore,
            "anomaly_intervals": target_anomaly_intervals,
            "anomaly_types": target_anomaly_types,
            "drift": target_drift,
            "anomaly_scan": target_scan,
            "cross_correlation_lag": target_lag,
            "correlation": corr_matrix,
            "correlation_with_x": corr_with_x,
            "common_correlations": common_corr,
        },
    }


def _preprocess_anomaly_C(
    df_active: pd.DataFrame,
    t2_result: Dict,
    warn_indices: List[int],
    target_range: List[str],
) -> Dict:
    """場景 C: 有目標區間 — marginal drop + baseline 差分 + compare_groups + PCA"""
    n_total = len(df_active)
    intervals = _parse_ranges(target_range, n_total)

    if not intervals:
        print(f"[preprocess:C] 無法解析區間 {target_range}, fallback A")
        return _preprocess_anomaly(df_active, t2_result, warn_indices)

    # PCA
    pca_data = _pca_common(df_active)

    # 收集所有區間的 index
    all_target_idxs = []
    for s, e in intervals:
        all_target_idxs.extend(range(s, e + 1))
    all_target_idxs = sorted(set(all_target_idxs))

    # baseline = 非目標區間
    target_set = set(all_target_idxs)
    baseline_idxs = [i for i in range(n_total) if i not in target_set]

    # 全域 T² 資訊 (畫圖用)
    t2_values = t2_result["t2_values"]

    # Per interval: marginal drop + baseline 差分
    marginal_by_interval = {}
    baseline_by_interval = {}
    for s, e in intervals:
        iv_idxs = list(range(s, e + 1))
        iv_label = f"{s}-{e}"
        print(f"\n--- 區間 #{iv_label} ({len(iv_idxs)} 筆) ---")

        # Marginal drop
        m_scores, _m_names = t2_contribution_marginal(
            df_active, iv_idxs, top_n=3, auto_chart=False
        )
        marginal_by_interval[iv_label] = m_scores[:3]

        # Baseline 差分
        b_scores, _b_names = t2_contribution_baseline(
            df_active, iv_idxs, top_n=3, auto_chart=False
        )
        baseline_by_interval[iv_label] = b_scores[:3]

    # Global marginal + baseline (全部目標區間合併)
    print(f"\n--- 全域 ({len(all_target_idxs)} 筆指定區間) ---")
    m_g_scores, m_g_names = t2_contribution_marginal(
        df_active, all_target_idxs, top_n=5, auto_chart=False
    )
    b_g_scores, _b_g_names = t2_contribution_baseline(
        df_active, all_target_idxs, top_n=5, auto_chart=False
    )

    # compare_groups: 區間 vs baseline 均值差異
    compare_result = {}
    try:
        compare_result = compare_groups(
            df_active, all_target_idxs, baseline_idxs, top_n=5, auto_chart=False
        )
    except Exception as e:
        print(f"[preprocess:C] compare_groups failed: {e}")

    return {
        "scenario": "C",
        "hotelling": {
            "t2_values": t2_values,
            "ucl_99": t2_result["ucl"],
            "ucl_95": t2_result.get("ucl_warn", 0),
            "anomaly_indices": all_target_idxs,
            "warn_indices": warn_indices,
            "pass1_extreme_indices": t2_result.get("pass1_extreme_indices", []),
            "pass2_anomaly_indices": t2_result.get("pass2_anomaly_indices", []),
        },
        "anomaly_intervals": [f"{s}-{e}" for s, e in intervals],
        "pca": pca_data,
        "t2_contrib": {
            "marginal_scores_global": m_g_scores[:5],
            "baseline_scores_global": b_g_scores[:5],
            "marginal_scores_by_interval": marginal_by_interval,
            "baseline_scores_by_interval": baseline_by_interval,
            "top_contributors_global": m_g_names[:5],
        },
        "compare_groups": compare_result,
    }


def _preprocess_anomaly_D(
    df_active: pd.DataFrame,
    t2_result: Dict,
    warn_indices: List[int],
    target_params: List[str],
    target_range: List[str],
    baseline_range: Optional[str] = None,
) -> Dict:
    """場景 D: 有目標參數+區間 — 6 步完整分析

    Step 1: 全域 Z-score OOC (per target)
    Step 2: T² Marginal Drop (目標區間 vs 對照區間)
    Step 3: Compare Groups (全欄位, 目標 vs 對照)
    Step 4: 相關性差異 (target×全欄位, 區間 vs 對照)
    Step 5: RF Feature Importance + Top Correlation (全域)
    Step 6: Segment Drift (per target)
    """
    from sklearn.ensemble import RandomForestRegressor

    n_total = len(df_active)
    valid_targets = [p for p in target_params if p in df_active.columns]

    # Parse target range
    intervals = _parse_ranges(target_range, n_total)

    if not intervals or not valid_targets:
        # fallback
        if valid_targets:
            return _preprocess_anomaly_B(
                df_active, t2_result, warn_indices, valid_targets
            )
        elif intervals:
            return _preprocess_anomaly_C(
                df_active, t2_result, warn_indices, target_range
            )
        else:
            return _preprocess_anomaly(df_active, t2_result, warn_indices)

    # === 建構目標/對照索引 ===
    all_target_idxs = []
    for s, e in intervals:
        all_target_idxs.extend(range(s, e + 1))
    all_target_idxs = sorted(set(all_target_idxs))
    target_set = set(all_target_idxs)

    # 對照區間: 人工設定 > 自動計算
    if baseline_range and baseline_range not in ("__AUTO__", ""):
        bl_intervals = _parse_ranges([baseline_range], n_total)
        baseline_idxs = []
        for s, e in bl_intervals:
            baseline_idxs.extend(range(s, e + 1))
        baseline_idxs = sorted(set(baseline_idxs))
        print(
            f"[preprocess:D] 使用人工對照區間: {baseline_range} ({len(baseline_idxs)} 筆)"
        )
    else:
        baseline_idxs = [i for i in range(n_total) if i not in target_set]
        print(f"[preprocess:D] 自動對照: 全域去掉目標 ({len(baseline_idxs)} 筆)")

    print(
        f"[preprocess:D] 目標區間: {[f'{s}-{e}' for s, e in intervals]} ({len(all_target_idxs)} 筆)"
    )
    print(f"[preprocess:D] 目標參數: {valid_targets}")

    # === PCA ===
    pca_data = _pca_common(df_active)

    # === Step 1: 全域 Z-score OOC (per target) ===
    print("\n--- Step 1: Z-score OOC 檢查 ---")
    zscore_results = {}
    for y_col in valid_targets:
        try:
            vals = df_active[y_col].values
            median_val = float(np.median(vals))
            from scipy.stats import median_abs_deviation

            mad_val = float(median_abs_deviation(vals))
            if mad_val > 0:
                z_vals = (vals - median_val) / (1.4826 * mad_val)
            else:
                z_vals = np.zeros_like(vals)
            outlier_mask = np.abs(z_vals) > 3
            outlier_indices = [int(i) for i in np.where(outlier_mask)[0]]
            outliers_in_target = [i for i in outlier_indices if i in target_set]
            pct = len(outliers_in_target) / max(len(outlier_indices), 1) * 100

            zscore_results[y_col] = {
                "outlier_indices": outlier_indices,
                "n_outliers": len(outlier_indices),
                "outliers_in_target": outliers_in_target,
                "outliers_in_target_pct": round(pct, 1),
                "median": round(median_val, 4),
                "mad": round(mad_val, 4),
            }
            print(
                f"  {y_col}: {len(outlier_indices)} 筆 OOC, "
                f"其中 {len(outliers_in_target)} 筆在目標區間 ({pct:.0f}%)"
            )
        except Exception as e:
            print(f"  {y_col}: Z-score 失敗 - {e}")

    # === Step 2: T² Marginal Drop (目標區間 vs 對照區間) ===
    print("\n--- Step 2: T² Marginal Drop ---")
    t2_marginal = {}
    t2_baseline_contrib = {}
    try:
        m_scores, m_names = t2_contribution_marginal(
            df_active, all_target_idxs, top_n=10, auto_chart=False
        )
        t2_marginal = {"scores": m_scores[:10], "names": m_names[:10]}
        print(f"  Top 5 Marginal: {m_names[:5]}")
    except Exception as e:
        print(f"  Marginal Drop 失敗: {e}")

    try:
        b_scores, b_names = t2_contribution_baseline(
            df_active, all_target_idxs, top_n=10, auto_chart=False
        )
        t2_baseline_contrib = {"scores": b_scores[:10], "names": b_names[:10]}
    except Exception as e:
        print(f"  Baseline T² 失敗: {e}")

    # === Step 3: Compare Groups (全欄位, 目標 vs 對照) ===
    print("\n--- Step 3: Compare Groups ---")
    compare_result = {}
    try:
        compare_result = compare_groups(
            df_active, all_target_idxs, baseline_idxs, top_n=15, auto_chart=False
        )
    except Exception as e:
        print(f"  Compare Groups 失敗: {e}")

    # === Step 4: 相關性差異 (target×全欄位, 區間 vs 對照) ===
    print("\n--- Step 4: 相關性差異分析 ---")
    correlation_change = {}
    df_in_target = (
        df_active.iloc[all_target_idxs] if all_target_idxs else df_active.iloc[0:0]
    )
    df_in_baseline = (
        df_active.iloc[baseline_idxs] if baseline_idxs else df_active.iloc[0:0]
    )

    for y_col in valid_targets:
        try:
            if len(df_in_target) < 5 or len(df_in_baseline) < 5:
                print(f"  {y_col}: 樣本不足，跳過相關性分析")
                continue
            other_cols = [c for c in df_active.columns if c != y_col]
            corr_target = df_in_target[other_cols].corrwith(df_in_target[y_col])
            corr_baseline = df_in_baseline[other_cols].corrwith(df_in_baseline[y_col])
            delta = (
                (corr_target - corr_baseline)
                .abs()
                .dropna()
                .sort_values(ascending=False)
            )

            top_changes = []
            for col in delta.head(15).index:
                top_changes.append(
                    {
                        "param": col,
                        "corr_target": round(float(corr_target.get(col, 0)), 4),
                        "corr_baseline": round(float(corr_baseline.get(col, 0)), 4),
                        "delta": round(float(delta.get(col, 0)), 4),
                    }
                )
            correlation_change[y_col] = top_changes
            if top_changes:
                print(
                    f"  {y_col}: 最大差異 {top_changes[0]['param']} "
                    f"(target={top_changes[0]['corr_target']}, "
                    f"baseline={top_changes[0]['corr_baseline']}, "
                    f"Δ={top_changes[0]['delta']})"
                )
        except Exception as e:
            print(f"  {y_col}: 相關性差異分析失敗 - {e}")

    # === Step 5: RF Feature Importance + Top Correlation (全域) ===
    print("\n--- Step 5: RF + Top Correlation ---")
    rf_importance = {}
    top_correlations = {}

    for y_col in valid_targets:
        try:
            other_cols = [c for c in df_active.columns if c != y_col]
            X = df_active[other_cols]
            y = df_active[y_col]
            mask = y.notna() & X.notna().all(axis=1)
            X_clean, y_clean = X[mask], y[mask]

            if len(X_clean) < 10:
                print(f"  {y_col}: 樣本不足 ({len(X_clean)})，跳過 RF")
                continue

            # RF
            rf = RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1)
            rf.fit(X_clean, y_clean)
            importances = rf.feature_importances_
            feat_sorted = sorted(
                zip(other_cols, importances), key=lambda x: x[1], reverse=True
            )
            rf_importance[y_col] = [
                {"param": col, "importance": round(float(imp), 6)}
                for col, imp in feat_sorted[:15]
            ]
            r2 = rf.score(X_clean, y_clean)
            print(f"  {y_col}: RF R²={r2:.3f}, Top3={[f[0] for f in feat_sorted[:3]]}")

            # Top Correlation
            corrs = X_clean.corrwith(y_clean).abs().sort_values(ascending=False)
            top_correlations[y_col] = [
                {"param": col, "corr": round(float(corrs[col]), 4)}
                for col in corrs.head(15).index
            ]
        except Exception as e:
            print(f"  {y_col}: RF/Corr 失敗 - {e}")

    # === Step 6: Segment Drift (per target) ===
    print("\n--- Step 6: Segment Drift ---")
    target_drift = {}
    for y_col in valid_targets:
        try:
            sd = segment_drift(df_active, y_col, auto_chart=False)
            target_drift[y_col] = {
                "segments": sd.get("segments", []),
                "drift_detected": sd.get("drift_detected", False),
            }
            n_seg = len(sd.get("segments", []))
            print(
                f"  {y_col}: {'有漂移' if sd.get('drift_detected') else '無明顯漂移'} ({n_seg} 段)"
            )
        except Exception as e:
            print(f"  {y_col}: drift 失敗 - {e}")

    # === 組裝回傳 ===
    # 合併所有 Z-score outlier 作為 anomaly_indices
    all_outlier_idxs = list(target_set)  # 使用者指定區間為主
    for _zr in zscore_results.values():
        all_outlier_idxs.extend(_zr.get("outlier_indices", []))
    all_outlier_idxs = sorted(set(all_outlier_idxs))

    return {
        "scenario": "D",
        "hotelling": {
            "t2_values": t2_result["t2_values"],
            "ucl_99": t2_result["ucl"],
            "ucl_95": t2_result.get("ucl_warn", 0),
            "anomaly_indices": all_target_idxs,
            "warn_indices": warn_indices,
        },
        "anomaly_intervals": [f"{s}-{e}" for s, e in intervals],
        "pca": pca_data,
        "t2_contrib": {
            "marginal_scores_global": t2_marginal.get("scores", []),
            "baseline_scores_global": t2_baseline_contrib.get("scores", []),
            "top_contributors_global": t2_marginal.get("names", []),
            "top_contributors_by_interval": {
                f"{s}-{e}": t2_marginal.get("names", [])[:10] for s, e in intervals
            },
        },
        "compare_groups": compare_result,
        "target_analysis": {
            "target_params": valid_targets,
            "zscore": zscore_results,
            "rf_importance": rf_importance,
            "top_correlations": top_correlations,
            "correlation_change": correlation_change,
            "drift": target_drift,
            "anomaly_intervals": {
                y: [f"{s}-{e}" for s, e in intervals] for y in valid_targets
            },
        },
        "baseline_info": {
            "source": "user_specified"
            if baseline_range and baseline_range not in ("__AUTO__", "")
            else "auto",
            "baseline_range": baseline_range or "auto",
            "n_target": len(all_target_idxs),
            "n_baseline": len(baseline_idxs),
        },
    }


def _preprocess_optimization(
    df_active: pd.DataFrame, target_params: Optional[List[str]]
) -> Dict:
    """OPTIMIZATION 專屬前置分析"""
    from sklearn.ensemble import RandomForestRegressor

    # 確定 target Y
    target_col = None
    subject_params = []  # 用戶指定的分析主體

    if target_params:
        for p in target_params:
            if p in df_active.columns:
                subject_params.append(p)

    if subject_params:
        # 用戶指定了目標 → 第一個就是 Y （不論是不是 METROLOGY）
        # 「控制好 A1」→ A1 就是 Y，找它的 drivers
        # 「最佳化 METROLOGY-CW」→ CW 就是 Y
        target_col = subject_params[0]
        print(f"[preprocess:optimization] 目標 Y={target_col} (用戶指定)")
    else:
        # 沒指定 → fallback: 找 METROLOGY 開頭的欄位
        metro_cols = [c for c in df_active.columns if c.startswith("METROLOGY")]
        if metro_cols:
            target_col = metro_cols[0]
            print(
                f"[preprocess:optimization] 自動選擇 Y={target_col} (METROLOGY fallback)"
            )

    if not target_col:
        print("[preprocess:optimization] 找不到 target Y，跳過 feature importance")
        return {"target_analysis": {"target_col": None, "error": "no_target_found"}}

    # RF feature importance
    X = df_active.drop(columns=[target_col])
    y = df_active[target_col]

    # 移除 NaN
    mask = y.notna() & X.notna().all(axis=1)
    X_clean, y_clean = X[mask], y[mask]

    if len(X_clean) < 10:
        print(f"[preprocess:optimization] 樣本不足 ({len(X_clean)}), 跳過 RF")
        return {
            "target_analysis": {
                "target_col": target_col,
                "error": "insufficient_samples",
            }
        }

    rf = RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1)
    rf.fit(X_clean, y_clean)
    importances = rf.feature_importances_
    feat_imp = sorted(zip(X.columns, importances), key=lambda x: x[1], reverse=True)

    # Top correlations with Y
    corrs = X_clean.corrwith(y_clean).abs().sort_values(ascending=False)
    top_corrs = [(col, round(float(corrs[col]), 4)) for col in corrs.head(15).index]

    # Union of top features
    top_rf = [col for col, _ in feat_imp[:10]]
    top_cr = [col for col, _ in top_corrs[:10]]
    recommended = list(dict.fromkeys(top_rf + top_cr))[:15]  # deduplicate, keep order

    print(
        f"[preprocess:optimization] Target: {target_col}, RF R²={rf.score(X_clean, y_clean):.3f}"
    )
    print(f"  Top 5 RF importance: {[f'{c}: {v:.4f}' for c, v in feat_imp[:5]]}")

    # Operating Window (sweet spot for top features)
    op_window = {}
    try:
        ow = operating_window(
            df_active, target_col, direction="maximize", top_k=5, auto_chart=False
        )
        if isinstance(ow, dict) and "windows" in ow:
            op_window = ow
            print(
                f"[preprocess:optimization] Operating window: {len(ow.get('windows', []))} 個特徵"
            )
    except Exception as _e:
        print(f"[preprocess:optimization] operating_window failed: {_e}")

    # Top correlations with target (完整版，含正負號)
    full_corrs = {}
    try:
        tc = top_correlations(df_active, target=target_col, top_n=10, auto_chart=False)
        if isinstance(tc, dict):
            full_corrs = tc
            print(
                f"[preprocess:optimization] top_correlations: {len(tc.get('pairs', []))} 對"
            )
    except Exception as _e:
        print(f"[preprocess:optimization] top_correlations failed: {_e}")

    # Cross-correlation lag (top 5 重要特徵 vs Y)
    lag_results = {}
    for _feat, _ in feat_imp[:5]:
        if _feat not in df_active.columns:
            continue
        try:
            ccl = cross_correlation_lag(
                df_active[_feat],
                df_active[target_col],
                max_lag=min(30, len(df_active) // 5),
                auto_chart=False,
            )
            if isinstance(ccl, dict):
                lag_results[_feat] = {
                    "best_lag": ccl.get("best_lag", 0),
                    "best_correlation": round(float(ccl.get("best_correlation", 0)), 4),
                }
        except Exception:
            pass
    if lag_results:
        print(
            f"[preprocess:optimization] cross_correlation_lag: {len(lag_results)} 個特徵"
        )

    return {
        "target_analysis": {
            "target_col": target_col,
            "subject_params": subject_params,
            "rf_r2": round(float(rf.score(X_clean, y_clean)), 4),
            "feature_importance": [(c, round(float(v), 4)) for c, v in feat_imp[:15]],
            "top_correlations": top_corrs,
            "recommended_features": recommended,
            "operating_window": op_window,
            "full_correlations": full_corrs,
            "cross_correlation_lag": lag_results,
        },
    }


def _preprocess_drift(df_active: pd.DataFrame) -> Dict:
    """DRIFT_AGING 專屬前置分析"""
    # CUSUM scan
    drift_result = scan_all_drift(df_active, method="cusum", top_n=15, auto_chart=False)

    # Mann-Kendall trend test on top-variance columns
    from scipy import stats as sp_stats

    trend_significant = []
    top_cols = df_active.std().sort_values(ascending=False).head(30).index
    for col in top_cols:
        s = df_active[col].values
        # Spearman rank correlation as MK proxy
        x = np.arange(len(s))
        rho, p = sp_stats.spearmanr(x, s)
        if p < 0.05 and abs(rho) > 0.2:
            trend_significant.append((col, round(float(rho), 4), round(float(p), 6)))

    print(
        f"[preprocess:drift] {len(trend_significant)} 個顯著趨勢欄位 (Spearman p<0.05)"
    )
    for col, rho, p in trend_significant[:10]:
        direction = "↑" if rho > 0 else "↓"
        print(f"  {col}: rho={rho:.3f} {direction} (p={p:.4f})")

    return {
        "drift_scan": {
            "drifted_columns": drift_result.get("drift_columns", []),
            "trend_significant": [
                {"col": c, "rho": r, "p": p} for c, r, p in trend_significant
            ],
            "top_drift_details": drift_result.get("details", {}),
        },
    }


def _preprocess_deep_analysis(df_active: pd.DataFrame, prep: Dict) -> Dict:
    """
    深入分析: 對每個 Top-3 異常區間做 compare_groups + correlation + drift-anomaly overlap。
    結果存在 prep["deep_analysis"], 確定性計算不靠 LLM。
    """
    intervals = prep.get("anomaly_intervals", [])
    t2c = prep.get("t2_contrib", {})
    marginal_by_iv = t2c.get("marginal_scores_by_interval", {})
    contrib_by_iv = t2c.get("contribution_scores_by_interval", {})
    drift_scan = prep.get("drift_scan", {})
    trend_sig = drift_scan.get("trend_significant", [])
    drift_cols_set = {t["col"] for t in trend_sig}

    anomaly_indices = set(prep.get("hotelling", {}).get("anomaly_indices", []))
    n_total = len(df_active)

    deep = {}  # key = interval str e.g. "898-940"

    for iv_str in intervals[:3]:
        try:
            parts = iv_str.split("-")
            s, e = int(parts[0]), int(parts[1])

            # interval indices vs baseline
            iv_indices = list(range(s, min(e + 1, n_total)))
            baseline_indices = [i for i in range(n_total) if i not in anomaly_indices]

            if len(iv_indices) < 3 or len(baseline_indices) < 10:
                continue

            # 1) compare_groups (silent)
            group_diff = compare_groups(
                df_active,
                iv_indices,
                baseline_indices,
                top_n=5,
                group_a_name=f"異常 #{iv_str}",
                group_b_name="Baseline",
                auto_chart=False,
            )

            # 2) dominant column + correlation
            m_scores = marginal_by_iv.get(iv_str, [])
            c_scores = contrib_by_iv.get(iv_str, [])
            scores = m_scores if m_scores else c_scores
            dominant_col = scores[0][0] if scores else None

            correlations = []
            if dominant_col and dominant_col in df_active.columns:
                corr_result = top_correlations(
                    df_active,
                    target=dominant_col,
                    top_n=5,
                    auto_chart=False,
                )
                correlations = corr_result if isinstance(corr_result, list) else []

            # 3) drift-anomaly overlap
            drift_overlap = []
            if scores:
                for col, _ in scores[:5]:
                    if col in drift_cols_set:
                        rho = next(
                            (t["rho"] for t in trend_sig if t["col"] == col), None
                        )
                        drift_overlap.append(
                            f"{col} 也在顯著漂移中 (ρ={rho:.3f})" if rho else col
                        )

            deep[iv_str] = {
                "group_diff": group_diff[:5] if isinstance(group_diff, list) else [],
                "correlations": correlations[:5],
                "dominant_col": dominant_col,
                "drift_overlap": drift_overlap,
            }
            print(
                f"[preprocess:deep] 區間 #{iv_str}: "
                f"diff_top={group_diff[0][0] if group_diff else '?'}, "
                f"corr={len(correlations)}, overlap={len(drift_overlap)}"
            )
        except Exception as _e:
            print(f"[preprocess:deep] 區間 #{iv_str} 失敗: {_e}")
            continue

    return {"deep_analysis": deep}


def preprocess_summary_text(prep: Dict) -> str:
    """
    將 preprocess() 結果格式化為人可讀的文字摘要，
    注入到 LLM 的 system prompt 中。
    """
    lines = []
    meta = prep.get("meta", {})
    _scenario = prep.get("scenario", "A")
    lines.append(f"場景: {_scenario}")
    lines.append(
        f"資料維度: {meta.get('n_rows', '?')} 筆 × {meta.get('n_cols_active', '?')} 欄 "
        f"(原始 {meta.get('n_cols_raw', '?')} 欄, 移除 {meta.get('dropped_dead_cols', '?')} 個死水欄位)"
    )
    lines.append(f"變異度最大的欄位: {', '.join(meta.get('top_std_cols', [])[:5])}")

    stability = prep.get("stability", {})
    lines.append(f"異常樣本數: {stability.get('anomaly_n', '?')}")
    lines.append(
        f"允許 corr: {stability.get('allow_corr')}, 允許 t-test: {stability.get('allow_ttest')}"
    )
    lines.append(f"建議動作: {', '.join(stability.get('recommended', []))}")

    # Anomaly/Exploratory
    _scenario = prep.get("scenario", "A")
    if "hotelling" in prep:
        h = prep["hotelling"]
        _ucl99 = h.get("ucl_99", 0)
        _anom_n = len(h.get("anomaly_indices", []))
        if _scenario == "B":
            # Scene B: 只印總數，不列區間（引導 LLM 用 zscore/drift）
            lines.append(
                f"\n[Hotelling T² 參考] 全域異常: {_anom_n} 筆 (UCL_99={_ucl99:.2f})"
            )
            lines.append(
                "  ⚠️ 以上為全域多變量異常，不代表目標參數異常。請用下方目標參數分析結果。"
            )
        elif _scenario == "C":
            # Scene C: 聚焦使用者指定區間
            intervals = prep.get("anomaly_intervals", [])
            _interval_str = (
                ", ".join(f"#{iv}" for iv in intervals) if intervals else "無"
            )
            # 計算指定區間內有多少筆超 UCL
            _t2v = h.get("t2_values", [])
            _anom_in_range = 0
            for iv_str in intervals:
                _parts = iv_str.split("-")
                if len(_parts) == 2:
                    try:
                        _s, _e = int(_parts[0]), int(_parts[1])
                        _anom_in_range += sum(
                            1
                            for i in range(_s, min(_e + 1, len(_t2v)))
                            if _t2v[i] > _ucl99
                        )
                    except (ValueError, IndexError):
                        pass
            lines.append(f"\n[Hotelling T²] 使用者指定區間: {_interval_str}")
            lines.append(f"  區間內超規筆數: {_anom_in_range} (UCL_99={_ucl99:.2f})")
        elif _scenario == "D":
            # Scene D: 精簡 + 區間資訊
            intervals = prep.get("anomaly_intervals", [])
            _interval_str = (
                ", ".join(f"#{iv}" for iv in intervals) if intervals else "無"
            )
            lines.append(
                f"\n[Hotelling T² 參考] 全域異常: {_anom_n} 筆 (UCL_99={_ucl99:.2f})"
            )
            lines.append(f"  使用者指定區間: {_interval_str}")
            lines.append("  ⚠️ 請聚焦指定區間內的目標參數分析結果。")
        else:
            # Scene A: 列出異常區間
            intervals = prep.get("anomaly_intervals", [])
            if intervals:
                interval_strs = [f"#{iv}" for iv in intervals]
                lines.append(
                    f"\n[Hotelling T²] 異常區間: {', '.join(interval_strs)} "
                    f"(共 {len(prep.get('anomaly_indices', []))} 筆, UCL_99={_ucl99:.2f})"
                )
            else:
                indices = h.get("anomaly_indices", [])
                lines.append(f"\n[Hotelling T²] 異常: {indices} (UCL_99={_ucl99:.2f})")
            if h.get("warn_indices"):
                lines.append(f"  警告: {h['warn_indices']}")

    if "pca" in prep:
        p = prep["pca"]
        evr = p.get("explained_variance_ratio", [])
        if evr:
            lines.append(f"\n[PCA] 前 5 主成分解釋比: {[round(v, 3) for v in evr[:5]]}")
        lines.append(f"  關鍵欄位: {', '.join(p.get('top_loading_cols', [])[:10])}")

    if "t2_contrib" in prep:
        tc = prep["t2_contrib"]
        lines.append("\n[T² Contribution]")

        # 優先顯示 Marginal Drop (更準確，抗 level-shift)
        marginal_by_iv = tc.get("marginal_scores_by_interval", {})
        scores_by_iv = tc.get("contribution_scores_by_interval", {})
        if marginal_by_iv:
            lines.append(
                "  (Marginal Drop — 遮蔽後 T² 下降量，數字越大越是真正 driver)"
            )
            for key, scores in marginal_by_iv.items():
                top_scores = [(col, s) for col, s in scores[:5] if s > 0.01]
                if top_scores:
                    score_strs = [f"{col}({s:.2f})" for col, s in top_scores]
                    lines.append(f"  區間 #{key}: {', '.join(score_strs)}")
        elif scores_by_iv:
            for key, scores in scores_by_iv.items():
                score_strs = [f"{col}({s:.2f})" for col, s in scores[:5]]
                lines.append(f"  區間 #{key}: {', '.join(score_strs)}")

        # Global: Marginal → Baseline → 原始
        marginal_g = tc.get("marginal_scores_global", [])
        baseline_g = tc.get("baseline_scores_global", [])
        if marginal_g:
            top_m = [(col, s) for col, s in marginal_g[:5] if s > 0.01]
            if top_m:
                score_strs = [f"{col}({s:.2f})" for col, s in top_m]
                lines.append(f"  全域 Marginal Drop: {', '.join(score_strs)}")
        if baseline_g:
            top_b = [(col, s) for col, s in baseline_g[:5] if s > 0.01]
            if top_b:
                score_strs = [f"{col}({s:.2f})" for col, s in top_b]
                lines.append(f"  全域 Baseline 差分: {', '.join(score_strs)}")

        overlap = tc.get("overlap", [])
        if overlap:
            lines.append(f"  重疊欄位: {', '.join(overlap)}")
        else:
            lines.append("  重疊欄位: 無 (不同型態異常)")

    # Scenario B: 目標參數模式
    if "target_analysis" in prep and _scenario == "B":
        ta = prep["target_analysis"]
        _tp = ta.get("target_params", [])
        lines.append(f"\n[目標參數分析] 目標: {', '.join(_tp)}")
        # 低變異目標參數提示
        _kept_dead = meta.get("kept_dead_targets", [])
        if _kept_dead:
            lines.append(
                f"  ⚠️ 以下目標參數為低變異/近似常數欄位（值幾乎不變，可能為固定設定值或感測器未啟用）: {', '.join(_kept_dead)}"
            )
        # 被移除的目標參數提示
        _all_requested = prep.get("requested_targets", [])
        if _all_requested:
            _dropped = [p for p in _all_requested if p not in _tp]
            if _dropped:
                lines.append(
                    f"  ⚠️ 以下目標參數因死水欄位過濾而移除: {', '.join(_dropped)}"
                )

        _zscore = ta.get("zscore", {})
        for y_col, zinfo in _zscore.items():
            _outlier_n = zinfo.get("outlier_count", 0)
            _outlier_idx = zinfo.get("outlier_indices", [])
            lines.append(
                f"  [{y_col}] Z-score 異常: {_outlier_n} 筆"
                f"{f' (indices: {_outlier_idx[:10]})' if _outlier_idx else ''}"
            )

        # 異常區間 + 類型（整合 scan 結果）
        _anom_ivs = ta.get("anomaly_intervals", {})
        _anom_types = ta.get("anomaly_types", {})
        _scan_data = ta.get("anomaly_scan", {})

        # 建立 scan type lookup: {y_col: [(start, end, type, severity, desc), ...]}
        _scan_lookup = {}
        for _yc, _si in _scan_data.items():
            _scan_lookup[_yc] = [
                (
                    s.get("start", 0),
                    s.get("end", 0),
                    s.get("type", ""),
                    s.get("severity_score", 0),
                    s.get("description", ""),
                )
                for s in _si.get("segments", [])
            ]

        for y_col in _tp:
            _ivs = _anom_ivs.get(y_col, [])
            _types = _anom_types.get(y_col, [])
            if _ivs:
                lines.append(f"  [{y_col}] 異常區間 ({len(_ivs)} 個): {_ivs}")
                for _t in _types:
                    _iv = _t.get("interval", "?")
                    _tp_name = _t.get("type", "unknown")
                    _conf = _t.get("confidence", 0)

                    # 如果 classify 說 "normal"，用 scan 結果覆蓋
                    if _tp_name == "normal" and y_col in _scan_lookup:
                        try:
                            _parts = _iv.split("-")
                            _iv_s, _iv_e = int(_parts[0]), int(_parts[1])
                            for _ss, _se, _st, _sv, _sd in _scan_lookup[y_col]:
                                # 區間重疊
                                if (
                                    _ss <= _iv_e
                                    and _se >= _iv_s
                                    and _st not in ("REGIME_CHANGE", "")
                                ):
                                    _tp_name = _st.lower()
                                    _conf = max(_conf, 0.6)
                                    break
                        except (ValueError, IndexError):
                            pass
                        if _tp_name == "normal":
                            # Scan 也沒覆蓋 → 根據區間長度簡單歸類
                            _seg_len = _iv_e - _iv_s + 1
                            if _seg_len <= 5:
                                _tp_name = "spike"
                            else:
                                _tp_name = "level_shift"

                    _type_zh = {
                        "spike": "突波",
                        "drift": "漂移",
                        "level_shift": "水平跳變",
                        "freeze": "凍結",
                        "oscillation": "振盪",
                        "dip_recovery": "急跌恢復",
                        "unclassified": "待分類",
                    }.get(_tp_name, _tp_name)
                    lines.append(
                        f"    #{_iv}: {_type_zh} ({_tp_name}, 信心度={_conf:.2f})"
                    )
            else:
                lines.append(f"  [{y_col}] 異常區間: 無 (Z-score 未偵測到異常)")

        _drift = ta.get("drift", {})
        for y_col, dinfo in _drift.items():
            _detected = dinfo.get("drift_detected", False)
            _segs = dinfo.get("segments", [])
            if _detected:
                lines.append(f"  [{y_col}] 漂移偵測: ⚠️ 有漂移 ({len(_segs)} 個分段)")
            else:
                lines.append(f"  [{y_col}] 漂移偵測: ✅ 無顯著漂移")

        # 滑動窗口異常掃描
        _scan = ta.get("anomaly_scan", {})
        for y_col, sinfo in _scan.items():
            _segs = sinfo.get("segments", [])
            if _segs:
                lines.append(f"  [{y_col}] ⚠️ 滑動窗口異常掃描: {len(_segs)} 個區段")
                _TYPE_ZH = {
                    "DRIFT": "漂移",
                    "OSCILLATION": "震盪",
                    "SPIKE": "突波",
                    "DIP_RECOVERY": "急跌恢復",
                    "LEVEL_SHIFT": "水平偏移",
                    "SHIFTED_STABLE": "偏移穩態",
                    "REGIME_CHANGE": "狀態切換",
                }
                for seg in _segs[:5]:
                    _t = seg.get("type", "?")
                    _s = seg.get("start", 0)
                    _e = seg.get("end", 0)
                    _sev = seg.get("severity_score", 0)
                    _desc = seg.get("description", "")
                    lines.append(
                        f"    #{_s}-{_e}: {_TYPE_ZH.get(_t, _t)} ({_t}, severity={_sev}, {_desc})"
                    )
                    # 主導因子 (deep analysis)
                    _factors = seg.get("top_factors", [])
                    if _factors:
                        _method = _factors[0].get("method", "unknown")
                        _fstrs = []
                        for _f in _factors[:3]:
                            _score_key = "score" if "score" in _f else "z_diff"
                            _fstrs.append(
                                f"{_f['col']}({_score_key}={_f.get(_score_key, 0):.2f})"
                            )
                        lines.append(f"      主導因子 ({_method}): {', '.join(_fstrs)}")
                    _group = seg.get("group_validation", [])
                    if _group:
                        _gstrs = [
                            f"{g['col']}(z_diff={g['z_diff']:.1f})" for g in _group[:3]
                        ]
                        lines.append(f"      分組驗證: {', '.join(_gstrs)}")
            else:
                lines.append(f"  [{y_col}] 滑動窗口異常掃描: ✅ 無異常區段")

        _fi = ta.get("feature_importance", {})
        for y_col, imp_list in _fi.items():
            if imp_list:
                _top5 = [f"{col}({s:.3f})" for col, s in imp_list[:5]]
                lines.append(f"  [{y_col}] RF 重要特徵: {', '.join(_top5)}")

        _corr_x = ta.get("correlation_with_x", {})
        for y_col, corr_list in _corr_x.items():
            if corr_list:
                _top3 = [f"{col}(r={s:.3f})" for col, s in corr_list[:3]]
                lines.append(f"  [{y_col}] 相關性: {', '.join(_top3)}")

        # 共同高相關欄位
        _common = ta.get("common_correlations", [])
        if _common:
            lines.append(f"  [共同高相關] 與所有目標參數都高相關的欄位 (min|r|排序):")
            for cc in _common:
                parts = ", ".join(f"{t}={cc['per_target'][t]:.3f}" for t in _tp)
                lines.append(f"    {cc['col']}: min|r|={cc['min_abs_r']:.3f} ({parts})")

        _ccl = ta.get("cross_correlation_lag", {})
        for y_col, lag_info in _ccl.items():
            if lag_info:
                _items = []
                for _feat, _info in lag_info.items():
                    _lag = _info.get("best_lag", 0)
                    _corr = _info.get("best_correlation", 0)
                    _mark = " ⚠️" if abs(_lag) > 2 else ""
                    _items.append(f"{_feat}(lag={_lag}, r={_corr:.3f}{_mark})")
                lines.append(f"  [{y_col}] 交叉延遲: {', '.join(_items)}")

    # Scenario C: 目標區間模式 — 輸出 compare_groups
    elif "compare_groups" in prep and _scenario == "C":
        cg = prep["compare_groups"]
        if isinstance(cg, list) and cg:
            # compare_groups() 回傳 [(col, mean_a, mean_b, diff, t, p), ...]
            _sig = [item for item in cg if len(item) >= 6 and item[5] < 0.05]
            if _sig:
                lines.append(f"\n[區間差異分析] 顯著差異欄位 ({len(_sig)} 個):")
                for item in _sig[:8]:
                    lines.append(f"  {item[0]}: 差值={item[3]:.3f}, p={item[5]:.4f}")
            else:
                lines.append("\n[區間差異分析] 無顯著差異欄位")
        elif isinstance(cg, dict):
            _sig = cg.get("significant_columns", [])
            if _sig:
                lines.append(f"\n[區間差異分析] 顯著差異欄位 ({len(_sig)} 個):")
                for item in _sig[:8]:
                    if isinstance(item, dict):
                        _col = item.get("column", "?")
                        _diff = item.get("mean_diff", 0)
                        _pval = item.get("p_value", 1)
                        lines.append(f"  {_col}: 差值={_diff:.3f}, p={_pval:.4f}")
                    elif isinstance(item, (list, tuple)) and len(item) >= 2:
                        lines.append(f"  {item[0]}: {item[1]}")
            else:
                lines.append("\n[區間差異分析] 無顯著差異欄位")

    # Scenario D: 目標參數+區間模式 (6 步分析)
    elif "target_analysis" in prep and _scenario == "D":
        ta = prep["target_analysis"]
        _tp = ta.get("target_params", [])
        bl_info = prep.get("baseline_info", {})
        lines.append(f"\n[目標參數+區間分析] 目標: {', '.join(_tp)}")
        # 低變異目標參數提示
        _kept_dead = meta.get("kept_dead_targets", [])
        if _kept_dead:
            lines.append(
                f"  ⚠️ 以下目標參數為低變異/近似常數欄位（值幾乎不變，可能為固定設定值或感測器未啟用）: {', '.join(_kept_dead)}"
            )
        lines.append(
            f"  對照: {bl_info.get('source', '?')} "
            f"(目標 {bl_info.get('n_target', '?')} 筆, "
            f"對照 {bl_info.get('n_baseline', '?')} 筆)"
        )

        # Step 1: Z-score OOC
        _zs = ta.get("zscore", {})
        if _zs:
            lines.append("\n  [Step 1: Z-score OOC]")
            for col, info in _zs.items():
                lines.append(
                    f"    {col}: {info.get('n_outliers', 0)} 筆超規, "
                    f"其中 {len(info.get('outliers_in_target', []))} 筆在目標區間 "
                    f"({info.get('outliers_in_target_pct', 0):.0f}%)"
                )

        # Step 2: T² Marginal Drop
        t2c = prep.get("t2_contrib", {})
        _mg = t2c.get("top_contributors_global", [])
        if _mg:
            lines.append(f"\n  [Step 2: T² Marginal Drop] Top: {', '.join(_mg[:5])}")

        # Step 3: Compare Groups
        cg = prep.get("compare_groups", [])
        if isinstance(cg, list) and cg:
            # compare_groups() 回傳 [(col, mean_a, mean_b, diff, t, p), ...]
            _sig = [item for item in cg if len(item) >= 6 and item[5] < 0.05]
            if _sig:
                lines.append(
                    f"\n  [Step 3: Compare Groups] 顯著差異 {len(_sig)} 個欄位:"
                )
                for item in _sig[:5]:
                    lines.append(f"    {item[0]}: 差值={item[3]:.3f}, p={item[5]:.4f}")
            else:
                lines.append("\n  [Step 3: Compare Groups] 無顯著差異")
        elif isinstance(cg, dict):
            _sig = cg.get("significant_columns", [])
            if _sig:
                lines.append(
                    f"\n  [Step 3: Compare Groups] 顯著差異 {len(_sig)} 個欄位:"
                )
                for item in _sig[:5]:
                    if isinstance(item, dict):
                        lines.append(
                            f"    {item.get('column', '?')}: "
                            f"差值={item.get('mean_diff', 0):.3f}, p={item.get('p_value', 1):.4f}"
                        )

        # Step 4: Correlation Change
        _cc = ta.get("correlation_change", {})
        if _cc:
            lines.append("\n  [Step 4: 相關性差異]")
            for col, changes in _cc.items():
                if changes:
                    top = changes[0]
                    lines.append(
                        f"    {col}: 最大差異 {top['param']} "
                        f"(target={top['corr_target']}, baseline={top['corr_baseline']}, Δ={top['delta']})"
                    )

        # Step 5: RF + Top Correlation
        _rf = ta.get("rf_importance", {})
        _tc = ta.get("top_correlations", {})
        if _rf:
            lines.append("\n  [Step 5: RF Feature Importance]")
            for col, feats in _rf.items():
                top3 = [f"{f['param']}({f['importance']:.4f})" for f in feats[:3]]
                lines.append(f"    {col}: {', '.join(top3)}")
        if _tc:
            lines.append("  [Top Correlations]")
            for col, corrs in _tc.items():
                top3 = [f"{c['param']}(r={c['corr']:.3f})" for c in corrs[:3]]
                lines.append(f"    {col}: {', '.join(top3)}")

        # Step 6: Drift
        _drift = ta.get("drift", {})
        for y_col, dinfo in _drift.items():
            _detected = dinfo.get("drift_detected", False)
            _segs = dinfo.get("segments", [])
            if _detected:
                lines.append(f"  [{y_col}] 漂移: ⚠️ 有漂移 ({len(_segs)} 個分段)")
            else:
                lines.append(f"  [{y_col}] 漂移: ✅ 無")

    # Optimization (Scene 非 B/C/D 的 target_analysis)
    elif "target_analysis" in prep:
        ta = prep["target_analysis"]
        if ta.get("target_col"):
            lines.append(
                f"\n[Feature Importance] Target: {ta['target_col']} (RF R²={ta.get('rf_r2', '?')})"
            )
            fi = ta.get("feature_importance", [])
            for col, imp in fi[:5]:
                lines.append(f"  {col}: {imp:.4f}")
            lines.append(
                f"  建議分析欄位: {', '.join(ta.get('recommended_features', [])[:10])}"
            )

            # Top correlations with target
            _tc = ta.get("top_correlations", [])
            if _tc:
                lines.append(f"\n[相關性排名] (與 {ta['target_col']} 的相關係數):")
                for _col, _r in _tc[:5]:
                    lines.append(f"  {_col}: r={_r:.4f}")

            # Operating window
            _ow = ta.get("operating_window", {})
            _wins = _ow.get("windows", [])
            if _wins:
                lines.append(f"\n[操作窗口 Sweet Spot] (Target: {ta['target_col']}):")
                for w in _wins[:5]:
                    _feat = w.get("parameter", "?")
                    _opt = w.get("optimal_range", (0, 0))
                    _lo, _hi = _opt[0], _opt[1]
                    _r = w.get("correlation_with_target", 0)
                    _ws = w.get("weighted_score", 0)
                    lines.append(
                        f"  {_feat}: [{_lo:.3f} ~ {_hi:.3f}] (r={_r:+.4f}, score={_ws:.2f})"
                    )

            # Cross-correlation lag
            _ccl = ta.get("cross_correlation_lag", {})
            if _ccl:
                lines.append(f"\n[交叉相關延遲] (正=X 領先 Y):")
                for _feat, _info in _ccl.items():
                    _lag = _info.get("best_lag", 0)
                    _corr = _info.get("best_correlation", 0)
                    _note = " ⚠️ 有延遲效應" if abs(_lag) > 2 else ""
                    lines.append(f"  {_feat}: lag={_lag}, r={_corr:.4f}{_note}")

    # Drift
    if "drift_scan" in prep:
        ds = prep["drift_scan"]
        lines.append(f"\n[Drift Scan] {len(ds.get('drifted_columns', []))} 個偏移欄位")
        trends = ds.get("trend_significant", [])
        if trends:
            lines.append(f"  顯著趨勢 ({len(trends)} 個):")
            for t in trends[:5]:
                d = "↑" if t["rho"] > 0 else "↓"
                lines.append(f"    {t['col']}: rho={t['rho']:.3f} {d}")

    return "\n".join(lines)


# ============================================================
# 11. Preprocess Charts — 前處理階段視覺化
# ============================================================


def generate_preprocess_charts(
    prep: Dict, task_type: str, target_params: Optional[List[str]] = None
) -> List[Dict]:
    """
    根據 preprocess() 結果與 task_type 生成前處理階段概覽圖表。
    在 LLM 開始生成 code 之前推送給前端，讓使用者先看到資料概況。

    Returns:
        list of {"image_base64": str, "title": str, "width": int, "height": int}
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm
    import base64
    from io import BytesIO

    # 中文字型配置 (與 ChartCollector.install 一致)
    chinese_fonts = [
        "Microsoft JhengHei",  # 微軟正黑體
        "Microsoft YaHei",  # 微軟雅黑
        "SimHei",  # 黑體
        "Arial Unicode MS",
    ]
    system_fonts = {f.name for f in fm.fontManager.ttflist}
    for font in chinese_fonts:
        if font in system_fonts:
            matplotlib.rcParams["font.sans-serif"] = [font, "DejaVu Sans"]
            matplotlib.rcParams["axes.unicode_minus"] = False
            break

    charts = []

    def _fig_to_base64(fig) -> Dict:
        buf = BytesIO()
        # 繞過 ChartCollector 的 savefig interceptor (如果存在)
        from matplotlib.figure import Figure as _Fig

        _real_savefig = getattr(_Fig, "_original_savefig", None) or _Fig.savefig
        try:
            _real_savefig(fig, buf, format="png", dpi=100, bbox_inches="tight")
        except TypeError:
            # fallback: 直接用 buf 作為 fname
            fig.savefig(buf, format="png", dpi=100, bbox_inches="tight")
        buf.seek(0)
        img_b64 = base64.b64encode(buf.read()).decode("utf-8")
        w, h = fig.get_size_inches() * fig.dpi
        plt.close(fig)
        return {"image_base64": img_b64, "width": int(w), "height": int(h)}

    anomaly_types = ("anomaly_detection", "global_analysis", "general")
    optim_types = ("optimization", "spec_recommendation")

    # Scene B/C/D 或單參數分析 → 跳過全域 T²/PCA
    _scenario = prep.get("scenario", "")
    _is_single_param = target_params and len(target_params) == 1
    _skip_global = _scenario in ("B", "C", "D") or _is_single_param

    # Scene C: 不產生任何 preprocess 圖表
    if _scenario == "C":
        print("[preprocess_charts] Scene C: 不產生圖表")
        return charts

    # === ANOMALY / EXPLORATORY: T² 控制圖 (跳過 Scene B/D) ===
    if task_type in anomaly_types and "hotelling" in prep and not _skip_global:
        h = prep["hotelling"]
        t2_vals = np.array(h["t2_values"])
        ucl_99 = h["ucl_99"]
        ucl_95 = h.get("ucl_95", None)
        _p1_idx = h.get("pass1_extreme_indices", [])
        _p2_idx = h.get("pass2_anomaly_indices", [])

        fig, ax = plt.subplots(figsize=(14, 5))
        x = np.arange(len(t2_vals))
        ax.plot(x, t2_vals, color="#3B82F6", linewidth=1.2, label="T² 值")
        if ucl_95 and ucl_95 > 0:
            ax.axhline(
                y=ucl_95,
                color="#F59E0B",
                linestyle="--",
                linewidth=1.0,
                label=f"95% 警告 = {ucl_95:.2f}",
            )
        ax.axhline(
            y=ucl_99,
            color="#EF4444",
            linestyle="--",
            linewidth=1.5,
            label=f"99% 異常 = {ucl_99:.2f}",
        )

        if _p1_idx or _p2_idx:
            # Two-Pass 模式: Pass1 紅色, Pass2 橘色
            if _p1_idx:
                p1_arr = np.array(_p1_idx)
                p1_mask = np.zeros(len(t2_vals), dtype=bool)
                p1_mask[p1_arr] = True
                ax.fill_between(
                    x, 0, t2_vals, where=p1_mask, color="#EF4444", alpha=0.2
                )
                ax.scatter(
                    p1_arr,
                    t2_vals[p1_arr],
                    color="#EF4444",
                    s=25,
                    zorder=5,
                    label=f"Pass1 extreme ({len(_p1_idx)})",
                )
            if _p2_idx:
                p2_arr = np.array(_p2_idx)
                p2_mask = np.zeros(len(t2_vals), dtype=bool)
                p2_mask[p2_arr] = True
                ax.fill_between(
                    x, 0, t2_vals, where=p2_mask, color="#F97316", alpha=0.2
                )
                ax.scatter(
                    p2_arr,
                    t2_vals[p2_arr],
                    color="#F97316",
                    s=25,
                    zorder=5,
                    marker="D",
                    label=f"Pass2 異常 ({len(_p2_idx)})",
                )
        else:
            # 舊版 fallback
            anomaly_mask_raw = t2_vals > ucl_99
            anomaly_mask = anomaly_mask_raw.copy()
            for _i in np.where(anomaly_mask_raw)[0]:
                for _offset in range(-3, 4):
                    _ei = _i + _offset
                    if 0 <= _ei < len(anomaly_mask):
                        anomaly_mask[_ei] = True
            if np.any(anomaly_mask):
                ax.fill_between(
                    x,
                    0,
                    t2_vals,
                    where=anomaly_mask,
                    color="#EF4444",
                    alpha=0.3,
                    label="異常區段",
                )
                ax.scatter(
                    x[anomaly_mask_raw],
                    t2_vals[anomaly_mask_raw],
                    color="#EF4444",
                    s=20,
                    zorder=5,
                )

        ax.set_xlabel("樣本序號")
        ax.set_ylabel("T² 值")
        _chart_title = (
            "[前處理] Hotelling T² 控制圖 (Two-Pass)"
            if _p1_idx
            else "[前處理] Hotelling T² 控制圖"
        )
        ax.set_title(_chart_title)
        ax.legend(loc="upper right")
        ax.grid(True, alpha=0.3)
        plt.tight_layout()

        chart_data = _fig_to_base64(fig)
        chart_data["title"] = _chart_title
        charts.append(chart_data)

    # === ANOMALY / EXPLORATORY: PCA 散佈圖 (PC1 vs PC2, 跳過 Scene B/D) ===
    if task_type in anomaly_types and "pca" in prep and not _skip_global:
        pca_data = prep["pca"]
        scores = pca_data.get("scores")
        evr = pca_data.get("explained_variance_ratio", [])

        if scores is not None and scores.shape[1] >= 2:
            fig, ax = plt.subplots(figsize=(10, 8))
            pc1 = scores[:, 0]
            pc2 = scores[:, 1]

            # 先畫正常點
            # 使用擴展後的 anomaly_indices（±3）
            anomaly_indices_list = sorted(
                prep.get(
                    "anomaly_indices",
                    prep.get("hotelling", {}).get("anomaly_indices", []),
                )
            )
            anomaly_indices = set(anomaly_indices_list)
            # 原始 T² 異常點（中心點）
            raw_anomaly = set(prep.get("hotelling", {}).get("anomaly_indices", []))

            normal_mask = np.array([i not in anomaly_indices for i in range(len(pc1))])

            ax.scatter(
                pc1[normal_mask],
                pc2[normal_mask],
                c="#3B82F6",
                alpha=0.5,
                s=30,
                label="正常",
                edgecolors="none",
            )

            # 將異常 indices 分成連續區間
            if anomaly_indices_list:
                intervals = []
                start = anomaly_indices_list[0]
                end = start
                for idx in anomaly_indices_list[1:]:
                    if idx == end + 1:
                        end = idx
                    else:
                        intervals.append((start, end))
                        start = idx
                        end = idx
                intervals.append((start, end))

                # 不同區間用不同顏色
                _interval_colors = [
                    ("#EF4444", "#B91C1C"),  # 紅
                    ("#F97316", "#C2410C"),  # 橘
                    ("#8B5CF6", "#6D28D9"),  # 紫
                    ("#10B981", "#047857"),  # 綠
                    ("#EC4899", "#BE185D"),  # 粉
                ]
                for gi, (s, e) in enumerate(intervals):
                    fill_c, edge_c = _interval_colors[gi % len(_interval_colors)]
                    idxs = list(range(s, e + 1))
                    mask = np.array([i in set(idxs) for i in range(len(pc1))])
                    ax.scatter(
                        pc1[mask],
                        pc2[mask],
                        c=fill_c,
                        alpha=0.9,
                        s=80,
                        label=f"異常區間 #{s}-#{e}",
                        edgecolors=edge_c,
                        linewidths=1.5,
                        zorder=5,
                    )
                    # 只標註原始中心點
                    for idx in idxs:
                        if idx in raw_anomaly and idx < len(pc1):
                            ax.annotate(
                                f"#{idx}",
                                (pc1[idx], pc2[idx]),
                                textcoords="offset points",
                                xytext=(8, 8),
                                fontsize=9,
                                color=edge_c,
                                fontweight="bold",
                            )

            evr_pc1 = f"{evr[0] * 100:.1f}%" if len(evr) > 0 else "?"
            evr_pc2 = f"{evr[1] * 100:.1f}%" if len(evr) > 1 else "?"
            ax.set_xlabel(f"PC1 ({evr_pc1})")
            ax.set_ylabel(f"PC2 ({evr_pc2})")
            ax.set_title("[前處理] PCA 主成分散佈圖")
            ax.legend(loc="upper right")
            ax.grid(True, alpha=0.3)
            plt.tight_layout()

            chart_data = _fig_to_base64(fig)
            chart_data["title"] = "[前處理] PCA 主成分散佈圖"
            charts.append(chart_data)

    # === SCENE B/D: 目標參數趨勢圖 (帶 Z-score 異常標記) ===
    # B: 只畫目標趨勢圖
    # D: 畫目標趨勢圖 + 標記使用者指定的分析區間
    _scenario = prep.get("scenario", "")
    if _scenario in ("B", "D") and "target_analysis" in prep:
        ta = prep["target_analysis"]
        _tp = ta.get("target_params", target_params or [])
        _zscore = ta.get("zscore", {})
        _drift = ta.get("drift", {})
        _df = prep.get("df_active")
        # Scene D: 取得使用者指定的目標/對照區間
        _bl_info = prep.get("baseline_info", {})
        _target_range = _bl_info.get("target_range", None)  # e.g. (start, end)
        _baseline_range = _bl_info.get("baseline_range", None)
        if _df is not None:
            for y_col in _tp[:4]:  # 最多畫 4 個目標參數（使用者指定的）
                if y_col not in _df.columns:
                    continue
                try:
                    fig, ax = plt.subplots(figsize=(14, 5))
                    values = _df[y_col].values
                    x = np.arange(len(values))
                    ax.plot(
                        x,
                        values,
                        color="#3B82F6",
                        linewidth=1.0,
                        alpha=0.7,
                        label=y_col,
                    )

                    # 標記 Z-score 異常點
                    _zinfo = _zscore.get(y_col, {})
                    _outlier_idx = _zinfo.get("outlier_indices", [])
                    if _outlier_idx:
                        _valid_idx = [i for i in _outlier_idx if i < len(values)]
                        ax.scatter(
                            _valid_idx,
                            values[_valid_idx],
                            color="#EF4444",
                            s=40,
                            zorder=5,
                            label=f"Z-score 異常 ({len(_valid_idx)} 筆)",
                        )

                    # Scene D: 標記使用者指定的分析區間
                    if _scenario == "D" and _target_range:
                        _tr_start, _tr_end = _target_range
                        ax.axvspan(
                            _tr_start,
                            _tr_end,
                            alpha=0.15,
                            color="#FEF3C7",
                            label=f"分析區間 #{_tr_start}-{_tr_end}",
                        )
                        if _baseline_range:
                            _bl_start, _bl_end = _baseline_range
                            ax.axvspan(
                                _bl_start,
                                _bl_end,
                                alpha=0.10,
                                color="#DBEAFE",
                                label=f"對照區間 #{_bl_start}-{_bl_end}",
                            )

                    ax.set_xlabel("樣本序號")
                    ax.set_ylabel(y_col)
                    _n_outlier = len(_outlier_idx) if _outlier_idx else 0
                    _trend_suffix = (
                        f" (Z異常{_n_outlier}筆)" if _n_outlier else " (無Z異常)"
                    )
                    _chart_title = f"[補充] {y_col} 趨勢圖{_trend_suffix}"
                    ax.set_title(_chart_title)
                    ax.legend(loc="upper right")
                    ax.grid(True, alpha=0.3)
                    plt.tight_layout()

                    chart_data = _fig_to_base64(fig)
                    chart_data["title"] = _chart_title
                    charts.append(chart_data)
                except Exception as _e:
                    print(
                        f"[preprocess_charts] Scene B/D chart for {y_col} failed: {_e}"
                    )

        # [已停用] Scene B/D 額外圖表 (RF, correlation, lag, drift, scan)
        # 使用者要求只保留目標趨勢圖，其餘不再生成

    # === (以下 Scene B/D 額外圖表已停用 — 用 _SKIP_EXTRA_BD 守衛) ===
    _SKIP_EXTRA_BD = False
    if _scenario in ("B", "D") and "target_analysis" in prep and not _SKIP_EXTRA_BD:
        ta = prep["target_analysis"]
        _fi = ta.get("feature_importance", {})
        _fi_d = ta.get("rf_importance", {})
        # 統一為 { col: [(param, imp), ...] } 格式
        unified_fi = {}
        for y_col, imp_list in _fi.items():
            if imp_list:
                unified_fi[y_col] = imp_list  # already (param, imp) tuples
        for y_col, imp_list in _fi_d.items():
            if imp_list and isinstance(imp_list[0], dict):
                unified_fi[y_col] = [
                    (item["param"], item["importance"]) for item in imp_list
                ]

        for y_col, imp_list in unified_fi.items():
            if not imp_list or len(imp_list) < 3:
                continue
            try:
                top_n = min(10, len(imp_list))
                cols = [c for c, _ in imp_list[:top_n]][::-1]
                imps = [v for _, v in imp_list[:top_n]][::-1]

                fig, ax = plt.subplots(figsize=(10, max(4, top_n * 0.45)))
                bars = ax.barh(range(len(cols)), imps, color="#6366F1", height=0.6)
                ax.set_yticks(range(len(cols)))
                ax.set_yticklabels(cols, fontsize=9)
                ax.set_xlabel("Feature Importance")
                ax.set_title(f"[補充] {y_col} RF 重要特徵 Top {top_n}")
                # 數值標籤
                for bar, val in zip(bars, imps):
                    ax.text(
                        bar.get_width() + 0.002,
                        bar.get_y() + bar.get_height() / 2,
                        f"{val:.3f}",
                        va="center",
                        fontsize=8,
                        color="#4B5563",
                    )
                ax.grid(axis="x", alpha=0.3)
                plt.tight_layout()

                chart_data = _fig_to_base64(fig)
                _rf_names = ", ".join([c for c, _ in imp_list[:3]])
                chart_data["title"] = f"[補充] {y_col} RF重要特徵 ({_rf_names})"
                charts.append(chart_data)
            except Exception as _e:
                print(f"[preprocess_charts] Scene B RF chart for {y_col} failed: {_e}")

            # TOP3 RF 重要特徵趨勢圖 (3 個子圖堆疊)
            try:
                _df = prep.get("df_active")
                if _df is not None:
                    top3_rf = [c for c, _ in imp_list[:3] if c in _df.columns]
                    if top3_rf:
                        n_plots = len(top3_rf)
                        fig, axes = plt.subplots(
                            n_plots, 1, figsize=(14, 3.5 * n_plots), sharex=True
                        )
                        if n_plots == 1:
                            axes = [axes]
                        _trend_colors = ["#EF4444", "#F59E0B", "#10B981"]
                        _target_vals = (
                            _df[y_col].values if y_col in _df.columns else None
                        )
                        for ci, col in enumerate(top3_rf):
                            ax = axes[ci]
                            # 目標參數淡藍底
                            if _target_vals is not None:
                                ax_twin = ax.twinx()
                                ax_twin.plot(
                                    _target_vals,
                                    color="#3B82F6",
                                    linewidth=0.5,
                                    alpha=0.35,
                                )
                                # 目標 MA
                                _t_win = max(5, len(_target_vals) // 20)
                                _t_ma = (
                                    pd.Series(_target_vals)
                                    .rolling(_t_win, center=True)
                                    .mean()
                                )
                                ax_twin.plot(
                                    _t_ma,
                                    color="#3B82F6",
                                    linewidth=1.8,
                                    alpha=0.7,
                                    label=f"{y_col} MA({_t_win})",
                                )
                                ax_twin.set_ylabel(y_col, fontsize=8, color="#3B82F6")
                                ax_twin.tick_params(
                                    axis="y", labelsize=7, colors="#3B82F6"
                                )
                                ax_twin.legend(loc="upper left", fontsize=6)
                            # RF 特徵
                            vals = _df[col].values
                            c = _trend_colors[ci % 3]
                            rf_val = imp_list[ci][1] if ci < len(imp_list) else 0
                            ax.plot(vals, color=c, linewidth=1.2, alpha=0.8)
                            win = max(5, len(vals) // 20)
                            ma = pd.Series(vals).rolling(win, center=True).mean()
                            ax.plot(ma, color=c, linewidth=2.0, label=f"MA({win})")
                            ax.set_title(f"{col} (RF={rf_val:.3f})", fontsize=10)
                            ax.legend(loc="upper right", fontsize=7)
                            ax.grid(True, alpha=0.3)
                        axes[-1].set_xlabel("樣本序號")
                        fig.suptitle(
                            f"[前處理] {y_col} vs RF Top 3 重要特徵",
                            fontsize=12,
                            fontweight="bold",
                        )
                        plt.tight_layout(rect=[0, 0, 1, 0.96])
                        chart_data = _fig_to_base64(fig)
                        _rf3_names = ", ".join(top3_rf)
                        chart_data["title"] = (
                            f"[前處理] {y_col} vs RF Top3 ({_rf3_names})"
                        )
                        charts.append(chart_data)
            except Exception as _e:
                print(f"[preprocess_charts] Scene B RF trend for {y_col} failed: {_e}")

            # TOP3 相關性參數趨勢圖
            try:
                _corr = ta.get("correlations", {}).get(y_col, [])
                _df = prep.get("df_active")
                if _corr and _df is not None:
                    top3_corr = [c for c, _ in _corr[:3] if c in _df.columns]
                    if top3_corr:
                        fig, ax = plt.subplots(figsize=(14, 5))
                        _corr_colors = ["#8B5CF6", "#EC4899", "#06B6D4"]
                        if y_col in _df.columns:
                            ax.plot(
                                _df[y_col].values,
                                color="#3B82F6",
                                linewidth=1.2,
                                alpha=0.8,
                                label=y_col,
                            )
                        ax2 = ax.twinx()
                        for ci, col in enumerate(top3_corr):
                            r_val = _corr[ci][1] if ci < len(_corr) else 0
                            ax2.plot(
                                _df[col].values,
                                color=_corr_colors[ci % 3],
                                linewidth=0.8,
                                alpha=0.7,
                                linestyle="--",
                                label=f"{col} (r={r_val:.3f})",
                            )
                        ax.set_xlabel("樣本序號")
                        ax.set_ylabel(y_col, color="#3B82F6")
                        ax2.set_ylabel("Corr Top 3", color="#8B5CF6")
                        ax.set_title(f"[前處理] {y_col} vs 相關性 Top 3 (|r|)")
                        lines1, labels1 = ax.get_legend_handles_labels()
                        lines2, labels2 = ax2.get_legend_handles_labels()
                        ax.legend(
                            lines1 + lines2,
                            labels1 + labels2,
                            loc="upper right",
                            fontsize=7,
                        )
                        ax.grid(True, alpha=0.3)
                        plt.tight_layout()
                        chart_data = _fig_to_base64(fig)
                        _corr3_names = ", ".join([c for c, _ in _corr[:3]])
                        chart_data["title"] = (
                            f"[補充] {y_col} vs 相關性Top3 ({_corr3_names})"
                        )
                        charts.append(chart_data)
            except Exception as _e:
                print(
                    f"[preprocess_charts] Scene B corr trend for {y_col} failed: {_e}"
                )

        # Scene B: Cross-Correlation Lag 長條圖
        _ccl = ta.get("cross_correlation_lag", {})
        for y_col, lag_info in _ccl.items():
            if not lag_info:
                continue
            try:
                feats = list(lag_info.keys())
                lags = [lag_info[f]["best_lag"] for f in feats]
                corrs_val = [lag_info[f]["best_correlation"] for f in feats]

                fig, ax = plt.subplots(figsize=(10, max(4, len(feats) * 0.8 + 1.5)))
                colors = ["#EF4444" if abs(lv) > 2 else "#3B82F6" for lv in lags]
                ax.barh(range(len(feats)), lags, color=colors, height=0.5)
                ax.set_yticks(range(len(feats)))
                ax.set_yticklabels(
                    [f"{f}\n(r={c:.3f})" for f, c in zip(feats, corrs_val)],
                    fontsize=9,
                )
                ax.set_xlabel("Best Lag (正=X領先Y)")
                ax.set_title(f"[前處理] {y_col} 交叉相關延遲")
                ax.axvline(x=0, color="#9CA3AF", linewidth=1, linestyle="--")
                ax.grid(axis="x", alpha=0.3)
                plt.tight_layout()
                chart_data = _fig_to_base64(fig)
                _top_lag = feats[0] if feats else "?"
                _top_lag_v = lags[0] if lags else 0
                _lag_dir = (
                    "領先" if _top_lag_v > 0 else "滯後" if _top_lag_v < 0 else "同步"
                )
                chart_data["title"] = (
                    f"[補充] {y_col} 交叉延遲 ({_top_lag} {_lag_dir}{abs(_top_lag_v)}步)"
                )
                charts.append(chart_data)
            except Exception as _e:
                print(f"[preprocess_charts] Scene B lag chart for {y_col} failed: {_e}")

        # Scene B: Drift 漂移偵測圖
        _drift = ta.get("drift", {})
        _df = prep.get("df_active")
        for y_col, dinfo in _drift.items():
            if (
                not dinfo.get("drift_detected")
                or _df is None
                or y_col not in _df.columns
            ):
                continue
            try:
                _segs = dinfo.get("segments", [])
                vals = _df[y_col].values
                fig, ax = plt.subplots(figsize=(14, 5))
                ax.plot(vals, color="#3B82F6", linewidth=1.0, alpha=0.7, label=y_col)
                _seg_colors = ["#F59E0B", "#FBBF24"]  # 兩色交替區分分段
                for si, seg in enumerate(_segs):
                    s = seg.get("start", 0)
                    e = seg.get("end", len(vals))
                    ax.axvspan(s, e, alpha=0.2, color=_seg_colors[si % 2])
                ax.set_xlabel("樣本序號")
                ax.set_ylabel(y_col)
                ax.set_title(f"[補充] {y_col} 漂移偵測 ({len(_segs)} 個分段)")
                ax.legend(loc="upper right")
                ax.grid(True, alpha=0.3)
                plt.tight_layout()
                chart_data = _fig_to_base64(fig)
                chart_data["title"] = f"[補充] {y_col} 漂移偵測 ({len(_segs)}個分段)"
                charts.append(chart_data)
            except Exception as _e:
                print(
                    f"[preprocess_charts] Scene B drift chart for {y_col} failed: {_e}"
                )

        # Scene B: Scan 異常掃描圖
        _scan = ta.get("anomaly_scan", {})
        _df = prep.get("df_active")
        for y_col, sinfo in _scan.items():
            segs = sinfo.get("segments", [])
            if not segs or _df is None or y_col not in _df.columns:
                continue
            try:
                vals = _df[y_col].values
                fig, ax = plt.subplots(figsize=(14, 5))
                ax.plot(vals, color="#3B82F6", linewidth=0.8, label=y_col)
                _colors = {
                    "DRIFT": "#F59E0B",
                    "OSCILLATION": "#8B5CF6",
                    "SPIKE": "#EF4444",
                    "DIP_RECOVERY": "#EC4899",
                    "LEVEL_SHIFT": "#F97316",
                    "SHIFTED_STABLE": "#06B6D4",
                    "REGIME_CHANGE": "#9CA3AF",
                }
                _type_zh = {
                    "DRIFT": "漂移",
                    "OSCILLATION": "震盪",
                    "SPIKE": "突波",
                    "DIP_RECOVERY": "急跌恢復",
                    "LEVEL_SHIFT": "水平跳變",
                    "SHIFTED_STABLE": "偏移穩態",
                    "REGIME_CHANGE": "狀態切換",
                }
                _plotted_types = set()
                for seg in segs[:8]:
                    c = _colors.get(seg["type"], "#EF4444")
                    lbl = seg["type"] if seg["type"] not in _plotted_types else None
                    ax.axvspan(seg["start"], seg["end"], alpha=0.25, color=c, label=lbl)
                    _plotted_types.add(seg["type"])
                    _mid_x = (seg["start"] + seg["end"]) / 2
                    _y_pos = (
                        ax.get_ylim()[1] - (ax.get_ylim()[1] - ax.get_ylim()[0]) * 0.05
                    )
                    _zh = _type_zh.get(seg["type"], seg["type"])
                    ax.text(
                        _mid_x,
                        _y_pos,
                        f"{_zh}\nsev={seg.get('severity_score', 0):.1f}",
                        ha="center",
                        va="top",
                        fontsize=7,
                        fontweight="bold",
                        color=c,
                        alpha=0.9,
                    )
                ax.set_title(
                    f"[前處理] {y_col} 異常掃描 ({len(segs)} 個區段)",
                    fontsize=11,
                    fontweight="bold",
                )
                ax.set_xlabel("樣本序號")
                ax.legend(loc="upper right", fontsize=8)
                ax.grid(True, alpha=0.3)
                plt.tight_layout()
                chart_data = _fig_to_base64(fig)
                _scan_types = ", ".join(sorted(_plotted_types))
                chart_data["title"] = (
                    f"[前處理] {y_col} 異常掃描 ({len(segs)}區段: {_scan_types})"
                )
                charts.append(chart_data)

                # === Per-segment 整合圖: 目標趨勢 + Top Factors ===
                for seg in segs[:5]:
                    _factors = seg.get("top_factors", [])
                    if not _factors:
                        continue
                    _s, _e = seg["start"], seg["end"]
                    _seg_type = seg.get("type", "?")
                    _type_cn = _type_zh.get(_seg_type, _seg_type)
                    _sev = seg.get("severity_score", 0)

                    # 取 top 3 factor 欄位
                    _factor_cols = [
                        f["col"]
                        for f in _factors[:3]
                        if f["col"] in _df.columns and f["col"] != y_col
                    ]
                    if not _factor_cols:
                        continue

                    try:
                        # context 範圍: 異常區段前後各 30 點
                        _ctx_start = max(0, _s - 30)
                        _ctx_end = min(len(vals), _e + 31)

                        fig2, (ax_top, ax_bot) = plt.subplots(
                            2,
                            1,
                            figsize=(14, 8),
                            sharex=True,
                            gridspec_kw={"height_ratios": [1.2, 1]},
                        )

                        # --- 上圖: 目標參數趨勢 + 異常區段標色 ---
                        _ctx_x = np.arange(_ctx_start, _ctx_end)
                        _ctx_vals = vals[_ctx_start:_ctx_end]
                        ax_top.plot(
                            _ctx_x,
                            _ctx_vals,
                            color="#3B82F6",
                            linewidth=1.2,
                            label=y_col,
                        )
                        # 異常區段標色
                        _seg_color = _colors.get(_seg_type, "#EF4444")
                        ax_top.axvspan(
                            _s,
                            _e,
                            alpha=0.25,
                            color=_seg_color,
                            label=f"{_type_cn} #{_s}-{_e}",
                        )
                        # 均值線
                        _seg_vals = vals[_s : _e + 1]
                        if len(_seg_vals) > 0:
                            ax_top.axhline(
                                y=np.mean(_seg_vals),
                                color=_seg_color,
                                linestyle="--",
                                linewidth=0.8,
                                alpha=0.6,
                            )
                        ax_top.set_ylabel(y_col, fontsize=9)
                        ax_top.set_title(
                            f"[前處理] {y_col} #{_s}-{_e} {_type_cn} + 主導因子",
                            fontsize=11,
                            fontweight="bold",
                        )
                        ax_top.legend(loc="upper right", fontsize=8)
                        ax_top.grid(True, alpha=0.3)

                        # --- 下圖: Top factors 標準化趨勢 ---
                        _factor_colors = ["#EF4444", "#F59E0B", "#10B981"]
                        for fi, fcol in enumerate(_factor_cols):
                            _f_vals = _df[fcol].values[_ctx_start:_ctx_end]
                            # 標準化 (z-score) 以便比較不同尺度
                            _f_mean = np.nanmean(_f_vals)
                            _f_std = np.nanstd(_f_vals)
                            if _f_std > 0:
                                _f_z = (_f_vals - _f_mean) / _f_std
                            else:
                                _f_z = _f_vals - _f_mean
                            _fc = _factor_colors[fi % 3]
                            # score/z_diff 標籤
                            _f_info = _factors[fi] if fi < len(_factors) else {}
                            _score_key = "score" if "score" in _f_info else "z_diff"
                            _score_val = _f_info.get(_score_key, 0)
                            ax_bot.plot(
                                _ctx_x,
                                _f_z,
                                color=_fc,
                                linewidth=1.2,
                                alpha=0.8,
                                label=f"{fcol} ({_score_key}={_score_val:.1f})",
                            )
                        # 異常區段標色 (下圖也加)
                        ax_bot.axvspan(_s, _e, alpha=0.15, color=_seg_color)
                        ax_bot.axhline(y=0, color="gray", linewidth=0.5, alpha=0.5)
                        ax_bot.set_ylabel("標準化值 (z)", fontsize=9)
                        ax_bot.set_xlabel("樣本序號", fontsize=9)
                        ax_bot.legend(loc="upper right", fontsize=8)
                        ax_bot.grid(True, alpha=0.3)

                        plt.tight_layout()
                        chart_data2 = _fig_to_base64(fig2)
                        _top_factor = _factor_cols[0] if _factor_cols else "?"
                        chart_data2["title"] = (
                            f"[前處理] {y_col} #{_s}-{_e} {_type_cn} 主導因子({_top_factor})"
                        )
                        chart_data2["is_overview"] = False  # 掛在發現下不掛概述
                        charts.append(chart_data2)

                        # --- 第三張圖: Box plot 分布對比 (異常段 vs 基線) ---
                        try:
                            _compare_cols = [y_col] + _factor_cols[:3]
                            _n_box = len(_compare_cols)
                            fig3, axes3 = plt.subplots(
                                1, _n_box, figsize=(3.5 * _n_box, 4), squeeze=False
                            )
                            axes3 = axes3[0]
                            _seg_data = _df.iloc[_s : _e + 1]
                            _base_data = pd.concat(
                                [_df.iloc[: max(0, _s)], _df.iloc[_e + 1 :]]
                            )
                            for ci, ccol in enumerate(_compare_cols):
                                ax3 = axes3[ci]
                                _box_data = []
                                _box_labels = []
                                if ccol in _base_data.columns:
                                    _bv = _base_data[ccol].dropna()
                                    if len(_bv) > 0:
                                        _box_data.append(_bv.values)
                                        _box_labels.append("基線")
                                if ccol in _seg_data.columns:
                                    _sv = _seg_data[ccol].dropna()
                                    if len(_sv) > 0:
                                        _box_data.append(_sv.values)
                                        _box_labels.append(f"#{_s}-{_e}")
                                if _box_data:
                                    bp = ax3.boxplot(
                                        _box_data,
                                        labels=_box_labels,
                                        patch_artist=True,
                                        widths=0.5,
                                    )
                                    _bp_colors = ["#93C5FD", "#F87171"]
                                    for pi, patch in enumerate(bp["boxes"]):
                                        patch.set_facecolor(_bp_colors[pi % 2])
                                        patch.set_alpha(0.7)
                                _short_name = ccol
                                if len(_short_name) > 15:
                                    _short_name = _short_name[:13] + ".."
                                ax3.set_title(_short_name, fontsize=9)
                                ax3.grid(True, alpha=0.2, axis="y")
                            fig3.suptitle(
                                f"[前處理] {y_col} #{_s}-{_e} 分布對比",
                                fontsize=11,
                                fontweight="bold",
                            )
                            plt.tight_layout()
                            chart_data3 = _fig_to_base64(fig3)
                            chart_data3["title"] = (
                                f"[前處理] {y_col} #{_s}-{_e} 分布對比 (基線 vs 異常段)"
                            )
                            chart_data3["is_overview"] = False
                            charts.append(chart_data3)
                        except Exception as _be:
                            print(
                                f"[preprocess_charts] Box plot "
                                f"{y_col} #{_s}-{_e} failed: {_be}"
                            )
                    except Exception as _fe:
                        print(
                            f"[preprocess_charts] Segment factor chart "
                            f"{y_col} #{_s}-{_e} failed: {_fe}"
                        )
            except Exception as _e:
                print(
                    f"[preprocess_charts] Scene B scan chart for {y_col} failed: {_e}"
                )

    # === OPTIMIZATION: Feature Importance 長條圖 ===
    if task_type in optim_types and "target_analysis" in prep:
        ta = prep["target_analysis"]
        fi = ta.get("feature_importance", [])
        target_col = ta.get("target_col", "?")

        if fi and len(fi) >= 3:
            top_n = min(10, len(fi))
            cols = [c for c, _ in fi[:top_n]][::-1]
            imps = [v for _, v in fi[:top_n]][::-1]

            fig, ax = plt.subplots(figsize=(10, 6))
            ax.barh(cols, imps, color="#3B82F6", edgecolor="#1E40AF")
            ax.set_xlabel("Feature Importance")
            ax.set_title(f"[前處理] Top {top_n} 特徵重要性 (Target: {target_col})")
            ax.grid(True, alpha=0.3, axis="x")
            plt.tight_layout()

            chart_data = _fig_to_base64(fig)
            chart_data["title"] = f"[前處理] 特徵重要性 (Target: {target_col})"
            charts.append(chart_data)

        # --- OPTIMIZATION 2: 目標參數趨勢圖 ---
        _df = prep.get("df_active")
        if _df is not None and target_col in _df.columns:
            try:
                fig, ax = plt.subplots(figsize=(14, 5))
                vals = _df[target_col].values
                x = np.arange(len(vals))
                ax.plot(
                    x, vals, color="#3B82F6", linewidth=1.0, alpha=0.7, label=target_col
                )
                win = max(5, len(vals) // 15)
                ma = pd.Series(vals).rolling(win, center=True).mean()
                ax.plot(x, ma, color="#EF4444", linewidth=2.0, label=f"MA({win})")
                ax.set_xlabel("樣本序號")
                ax.set_ylabel(target_col)
                ax.set_title(f"[前處理] {target_col} 趨勢圖")
                ax.legend(loc="upper right")
                ax.grid(True, alpha=0.3)
                plt.tight_layout()
                chart_data = _fig_to_base64(fig)
                chart_data["title"] = f"[前處理] {target_col} 趨勢圖"
                charts.append(chart_data)
            except Exception as _e:
                print(f"[preprocess_charts] optim trend failed: {_e}")

        # --- OPTIMIZATION 3: Top 3 重要特徵 vs 目標散佈圖 ---
        if _df is not None and fi:
            top3 = [c for c, _ in fi[:3] if c in _df.columns]
            if top3:
                try:
                    n_plots = len(top3)
                    fig, axes = plt.subplots(1, n_plots, figsize=(5 * n_plots, 4.5))
                    if n_plots == 1:
                        axes = [axes]
                    for i, feat in enumerate(top3):
                        axes[i].scatter(
                            _df[feat],
                            _df[target_col],
                            c="#3B82F6",
                            alpha=0.5,
                            s=20,
                            edgecolors="none",
                        )
                        # 趨勢線
                        try:
                            z = np.polyfit(
                                _df[feat].dropna(),
                                _df[target_col].loc[_df[feat].dropna().index],
                                1,
                            )
                            p = np.poly1d(z)
                            x_line = np.linspace(_df[feat].min(), _df[feat].max(), 50)
                            axes[i].plot(
                                x_line,
                                p(x_line),
                                color="#EF4444",
                                linewidth=1.5,
                                linestyle="--",
                            )
                        except Exception:
                            pass
                        axes[i].set_xlabel(feat, fontsize=9)
                        axes[i].set_ylabel(target_col if i == 0 else "", fontsize=9)
                        axes[i].set_title(f"{feat}\nvs {target_col}", fontsize=10)
                        axes[i].grid(True, alpha=0.3)
                    plt.suptitle(
                        "[前處理] Top 重要特徵 vs 目標", fontsize=12, fontweight="bold"
                    )
                    plt.tight_layout()
                    chart_data = _fig_to_base64(fig)
                    chart_data["title"] = "[前處理] Top 重要特徵 vs 目標 散佈圖"
                    charts.append(chart_data)
                except Exception as _e:
                    print(f"[preprocess_charts] optim scatter failed: {_e}")

        # --- OPTIMIZATION 3b: Top-3 相關係數雙軸趨勢圖 ---
        if _df is not None and target_col in _df.columns:
            try:
                # 計算所有數值欄位與目標的 Pearson 相關係數
                _numeric_df = _df.select_dtypes(include="number")
                _corrs = {}
                for _c in _numeric_df.columns:
                    if _c == target_col:
                        continue
                    _pair = _numeric_df[[target_col, _c]].dropna()
                    if len(_pair) > 10:
                        _r = _pair.corr().iloc[0, 1]
                        if not np.isnan(_r):
                            _corrs[_c] = _r

                # 取 |r| 最大的 top 3
                _sorted_corrs = sorted(
                    _corrs.items(), key=lambda x: abs(x[1]), reverse=True
                )[:3]

                if _sorted_corrs:
                    _n = len(_sorted_corrs)
                    fig, axes = plt.subplots(_n, 1, figsize=(14, 4 * _n), sharex=True)
                    if _n == 1:
                        axes = [axes]

                    _y_vals = _df[target_col].values
                    _x_idx = np.arange(len(_y_vals))
                    _win = max(5, len(_y_vals) // 20)

                    _colors_x = ["#F97316", "#8B5CF6", "#10B981"]  # 橘/紫/綠

                    for _i, (_col, _r) in enumerate(_sorted_corrs):
                        ax1 = axes[_i]
                        _x_vals = _df[_col].values

                        # 左軸: 目標 Y (藍)
                        ax1.plot(
                            _x_idx, _y_vals, color="#93C5FD", linewidth=0.6, alpha=0.4
                        )
                        _ma_y = pd.Series(_y_vals).rolling(_win, center=True).mean()
                        ax1.plot(
                            _x_idx,
                            _ma_y.values,
                            color="#3B82F6",
                            linewidth=2.0,
                            label=f"{target_col} (MA)",
                        )
                        ax1.set_ylabel(target_col, color="#3B82F6", fontsize=9)
                        ax1.tick_params(axis="y", labelcolor="#3B82F6")

                        # 右軸: 相關 X (橘/紫/綠)
                        ax2 = ax1.twinx()
                        _xc = _colors_x[_i % len(_colors_x)]
                        ax2.plot(_x_idx, _x_vals, color=_xc, linewidth=0.6, alpha=0.3)
                        _ma_x = pd.Series(_x_vals).rolling(_win, center=True).mean()
                        ax2.plot(
                            _x_idx,
                            _ma_x.values,
                            color=_xc,
                            linewidth=2.0,
                            label=f"{_col} (MA)",
                        )
                        ax2.set_ylabel(_col, color=_xc, fontsize=9)
                        ax2.tick_params(axis="y", labelcolor=_xc)

                        # 標題含 r 值 + 方向
                        _dir = "↑正" if _r > 0 else "↓負"
                        ax1.set_title(
                            f"{_col}  (r={_r:.4f} {_dir}相關)",
                            fontsize=10,
                            fontweight="bold",
                        )

                        # 合併 legend
                        _h1, _l1 = ax1.get_legend_handles_labels()
                        _h2, _l2 = ax2.get_legend_handles_labels()
                        ax1.legend(_h1 + _h2, _l1 + _l2, loc="upper right", fontsize=8)
                        ax1.grid(True, alpha=0.2)

                    axes[-1].set_xlabel("樣本序號")
                    fig.suptitle(
                        f"[前處理] Top-{_n} 相關參數趨勢對比 (Target: {target_col})",
                        fontsize=12,
                        fontweight="bold",
                    )
                    plt.tight_layout(rect=[0, 0, 1, 0.96])
                    chart_data = _fig_to_base64(fig)
                    chart_data["title"] = f"[前處理] Top-{_n} 相關參數趨勢對比"
                    charts.append(chart_data)
            except Exception as _e:
                print(f"[preprocess_charts] optim corr dual-axis failed: {_e}")
        # --- OPTIMIZATION 4: Operating Window (sweet spot) ---
        ow = ta.get("operating_window", {})
        _windows = ow.get("windows", [])
        if _windows:
            try:
                top_w = _windows[:5]
                n_w = len(top_w)
                fig, axes = plt.subplots(n_w, 1, figsize=(10, 2.5 * n_w))
                if n_w == 1:
                    axes = [axes]
                for i, w in enumerate(top_w):
                    col_name = w.get("parameter", f"Feature {i}")
                    opt = w.get("optimal_range", (0, 1))
                    lo, hi = opt[0], opt[1]
                    # 取全範圍
                    _df_ow = prep.get("df_active")
                    overall_lo = (
                        float(_df_ow[col_name].min())
                        if _df_ow is not None and col_name in _df_ow.columns
                        else lo
                    )
                    overall_hi = (
                        float(_df_ow[col_name].max())
                        if _df_ow is not None and col_name in _df_ow.columns
                        else hi
                    )
                    # 全範圍灰色長條
                    axes[i].barh(
                        0,
                        overall_hi - overall_lo,
                        left=overall_lo,
                        height=0.4,
                        color="#E5E7EB",
                        edgecolor="#9CA3AF",
                    )
                    # Sweet spot 綠色長條
                    axes[i].barh(
                        0,
                        hi - lo,
                        left=lo,
                        height=0.4,
                        color="#10B981",
                        edgecolor="#047857",
                        alpha=0.8,
                    )
                    axes[i].set_yticks([])
                    _w_r = w.get("correlation_with_target", 0)
                    _r_tag = f"  r={_w_r:+.3f}" if _w_r else ""
                    axes[i].set_title(
                        f"{col_name}  [{lo:.2f} ~ {hi:.2f}]{_r_tag}",
                        fontsize=10,
                        loc="left",
                    )
                    axes[i].grid(axis="x", alpha=0.3)
                plt.suptitle(
                    f"[前處理] 操作窗口 Sweet Spot (Target: {target_col})",
                    fontsize=12,
                    fontweight="bold",
                )
                plt.tight_layout()
                chart_data = _fig_to_base64(fig)
                chart_data["title"] = f"[前處理] 操作窗口 (Target: {target_col})"
                charts.append(chart_data)
            except Exception as _e:
                print(f"[preprocess_charts] optim window failed: {_e}")

        # --- OPTIMIZATION 5: Cross-Correlation Lag ---
        _lag = ta.get("cross_correlation_lag", {})
        if _lag:
            try:
                feats = list(_lag.keys())
                lags = [_lag[f]["best_lag"] for f in feats]
                corrs_val = [_lag[f]["best_correlation"] for f in feats]

                fig, ax = plt.subplots(figsize=(10, max(3, len(feats) * 0.6)))
                colors = [
                    "#EF4444" if abs(lag_val) > 2 else "#3B82F6" for lag_val in lags
                ]
                bars = ax.barh(range(len(feats)), lags, color=colors, height=0.5)
                ax.set_yticks(range(len(feats)))
                ax.set_yticklabels(
                    [f"{f}\n(r={c:.3f})" for f, c in zip(feats, corrs_val)], fontsize=9
                )
                ax.set_xlabel("Best Lag (正=X領先Y)")
                ax.set_title(f"[前處理] 交叉相關延遲 (Target: {target_col})")
                ax.axvline(x=0, color="#9CA3AF", linewidth=1, linestyle="--")
                ax.grid(axis="x", alpha=0.3)
                plt.tight_layout()
                chart_data = _fig_to_base64(fig)
                chart_data["title"] = f"[前處理] 交叉相關延遲 (Target: {target_col})"
                charts.append(chart_data)
            except Exception as _e:
                print(f"[preprocess_charts] optim lag failed: {_e}")

    # === DEEP ANALYSIS: 每個 Top-3 區間的分組對比 + 主導欄位趨勢 ===
    # (不放 overview，只供 inline matching 用)
    try:
        deep = prep.get("deep_analysis", {})
        _df_deep = prep.get("df_active")
        anomaly_indices_all = sorted(
            prep.get("hotelling", {}).get("anomaly_indices", [])
        )
        for iv_str, analysis in deep.items():
            group_diff = analysis.get("group_diff", [])
            dominant_col = analysis.get("dominant_col")
            # 1) 分組對比長條圖
            if group_diff and len(group_diff) >= 2:
                try:
                    top_items = group_diff[:5]
                    cols = [x[0] for x in top_items][::-1]
                    diffs = [x[3] for x in top_items][::-1]
                    p_vals = [x[5] for x in top_items][::-1]
                    fig, ax = plt.subplots(figsize=(10, max(3, len(cols) * 0.7)))
                    colors = ["#EF4444" if p < 0.05 else "#94A3B8" for p in p_vals]
                    bars = ax.barh(range(len(cols)), diffs, color=colors, height=0.5)
                    ax.set_yticks(range(len(cols)))
                    ax.set_yticklabels(cols, fontsize=9)
                    ax.set_xlabel("均值差異 (|Δ|)")
                    _title = f"[深度分析] 區間 #{iv_str} 分組對比 (Top-5 差異)"
                    ax.set_title(_title)
                    for bar, p in zip(bars, p_vals):
                        ax.text(
                            bar.get_width() + 0.01 * max(diffs),
                            bar.get_y() + bar.get_height() / 2,
                            f"p={p:.3f}" if p >= 0.001 else "p<0.001",
                            va="center",
                            fontsize=8,
                            color="#6B7280",
                        )
                    ax.grid(axis="x", alpha=0.3)
                    plt.tight_layout()
                    chart_data = _fig_to_base64(fig)
                    chart_data["title"] = _title
                    chart_data["is_overview"] = False
                    charts.append(chart_data)
                except Exception as _e:
                    print(f"[preprocess_charts] deep compare #{iv_str} failed: {_e}")

                # 1b) Box plot 分布對比 (異常段 vs 基線)
                if group_diff and len(group_diff) >= 2 and _df_deep is not None:
                    try:
                        parts = iv_str.split("-")
                        _bs, _be = int(parts[0]), int(parts[1])
                        top_cols = [x[0] for x in group_diff[:4]]
                        _n_box = len(top_cols)
                        fig_box, axes_box = plt.subplots(
                            1, _n_box, figsize=(3.5 * _n_box, 4), squeeze=False
                        )
                        axes_box = axes_box[0]
                        _seg_df = _df_deep.iloc[_bs : _be + 1]
                        _base_df = pd.concat(
                            [_df_deep.iloc[: max(0, _bs)], _df_deep.iloc[_be + 1 :]]
                        )
                        for ci, ccol in enumerate(top_cols):
                            ax_b = axes_box[ci]
                            _bd, _bl = [], []
                            if ccol in _base_df.columns:
                                _bv = _base_df[ccol].dropna()
                                if len(_bv) > 0:
                                    _bd.append(_bv.values)
                                    _bl.append("基線")
                            if ccol in _seg_df.columns:
                                _sv = _seg_df[ccol].dropna()
                                if len(_sv) > 0:
                                    _bd.append(_sv.values)
                                    _bl.append(f"#{iv_str}")
                            if _bd:
                                bp = ax_b.boxplot(
                                    _bd, labels=_bl, patch_artist=True, widths=0.5
                                )
                                _bpc = ["#93C5FD", "#F87171"]
                                for pi, patch in enumerate(bp["boxes"]):
                                    patch.set_facecolor(_bpc[pi % 2])
                                    patch.set_alpha(0.7)
                            _sn = ccol if len(ccol) <= 18 else ccol[:16] + ".."
                            ax_b.set_title(_sn, fontsize=9)
                            ax_b.grid(True, alpha=0.2, axis="y")
                        fig_box.suptitle(
                            f"[深度分析] #{iv_str} 分布對比 (基線 vs 異常段)",
                            fontsize=11,
                            fontweight="bold",
                        )
                        plt.tight_layout()
                        chart_box = _fig_to_base64(fig_box)
                        chart_box["title"] = (
                            f"[深度分析] #{iv_str} 分布對比 (基線 vs 異常段)"
                        )
                        chart_box["is_overview"] = False
                        charts.append(chart_box)
                    except Exception as _be:
                        print(f"[preprocess_charts] deep box #{iv_str} failed: {_be}")
            # 2) 主導欄位趨勢圖 (帶異常標記)
            if (
                dominant_col
                and _df_deep is not None
                and dominant_col in _df_deep.columns
            ):
                try:
                    fig, ax = plt.subplots(figsize=(14, 4))
                    vals = _df_deep[dominant_col].values
                    x = np.arange(len(vals))
                    ax.plot(x, vals, color="#3B82F6", linewidth=0.8, alpha=0.7)
                    win = max(5, len(vals) // 20)
                    ma = pd.Series(vals).rolling(win, center=True).mean()
                    ax.plot(x, ma, color="#EF4444", linewidth=2.0, label=f"MA({win})")
                    parts = iv_str.split("-")
                    s, e = int(parts[0]), int(parts[1])
                    ax.axvspan(s, e, alpha=0.2, color="#FEF3C7", label=f"#{iv_str}")
                    for idx in anomaly_indices_all:
                        if s <= idx <= e and idx < len(vals):
                            ax.scatter(idx, vals[idx], color="#EF4444", s=20, zorder=5)
                    _title = f"[深度分析] #{iv_str} 主導欄位 {dominant_col} 趨勢"
                    ax.set_title(_title)
                    ax.set_xlabel("樣本序號")
                    ax.set_ylabel(dominant_col)
                    ax.legend(loc="upper right")
                    ax.grid(True, alpha=0.3)
                    plt.tight_layout()
                    chart_data = _fig_to_base64(fig)
                    chart_data["title"] = _title
                    chart_data["is_overview"] = False
                    charts.append(chart_data)
                except Exception as _e:
                    print(f"[preprocess_charts] deep trend #{iv_str} failed: {_e}")
    except Exception as _deep_chart_err:
        print(f"[preprocess_charts] deep analysis charts failed: {_deep_chart_err}")

    # === DRIFT: Top 漂移欄位時序圖 (全域/異常 都顯示, Scene B 單參數跳過) ===
    _scene = prep.get("scenario", "")
    if "drift_scan" in prep and _scene != "B":
        ds = prep["drift_scan"]
        trends = ds.get("trend_significant", [])
        drifted_cols = ds.get("drifted_columns", [])
        df_active = prep.get("df_active")

        if df_active is not None:
            # 優先用 trend_significant，沒有則 fallback 到 drifted_columns
            plot_cols = []
            if trends:
                plot_cols = [(t["col"], t["rho"]) for t in trends[:3]]
            elif drifted_cols:
                plot_cols = [(c, None) for c in drifted_cols[:3]]

            if plot_cols:
                n_plots = len(plot_cols)
                fig, axes = plt.subplots(
                    n_plots, 1, figsize=(14, 4 * n_plots), sharex=True
                )
                if n_plots == 1:
                    axes = [axes]

                _ma_colors = ["#2563EB", "#059669", "#D97706"]  # 藍/綠/橘
                _line_colors = ["#93C5FD", "#6EE7B7", "#FCD34D"]  # 淡色原始線

                # 取異常區間 (用於標記)
                _anomaly_ivs = prep.get("anomaly_intervals", [])
                _anomaly_idx_set = set(
                    prep.get("hotelling", {}).get("anomaly_indices", [])
                )

                for i, (col, rho) in enumerate(plot_cols):
                    if col in df_active.columns:
                        vals = df_active[col].values
                        lc = _line_colors[i % len(_line_colors)]
                        mc = _ma_colors[i % len(_ma_colors)]
                        axes[i].plot(vals, color=lc, linewidth=0.8, alpha=0.6)
                        win = max(5, len(vals) // 20)
                        ma = pd.Series(vals).rolling(win, center=True).mean()
                        axes[i].plot(ma, color=mc, linewidth=2.0, label=f"MA({win})")
                        # 異常區間用淡黃色 + 紅點
                        for iv_key in _anomaly_ivs:
                            parts = str(iv_key).split("-")
                            if len(parts) == 2:
                                s, e = int(parts[0]), int(parts[1])
                                axes[i].axvspan(s, e, alpha=0.15, color="#FDE68A")
                        if rho is not None:
                            direction = "\u2191" if rho > 0 else "\u2193"
                            axes[i].set_title(f"{col} (\u03c1={rho:.3f} {direction})")
                        else:
                            axes[i].set_title(f"{col} (CUSUM \u5075\u6e2c)")
                        axes[i].legend(loc="upper right")
                        axes[i].grid(True, alpha=0.3)

                axes[-1].set_xlabel("\u6a23\u672c\u5e8f\u865f")
                fig.suptitle("[前處理] 顯著漂移趨勢", fontsize=14, fontweight="bold")
                plt.tight_layout(rect=[0, 0, 1, 0.96])

                chart_data = _fig_to_base64(fig)
                chart_data["title"] = "[前處理] 顯著漂移趨勢"
                charts.append(chart_data)

    return charts


# ============================================================
# 6. 安全繪圖 Helper (sigma.plot_*)
# ============================================================
# LLM 呼叫這些 helper 畫圖，不需要自己寫 matplotlib。
# 所有 helper：
#   - 內建欄位存在性檢查 + NaN 處理
#   - 畫不出來只 print()，永不 raise
#   - anomaly_indices 只用 loc index
# ============================================================


def _flatten_any(cols) -> list:
    """把 dict/tuple/slice/ndarray/Series 都變成 list[str]"""
    if cols is None:
        return []
    if isinstance(cols, slice):
        print("[sigma] cols 是 slice，已忽略，請傳 list[str]")
        return []
    if isinstance(cols, dict):
        # dict → values 攤平
        result = []
        for v in cols.values():
            if isinstance(v, (list, tuple)):
                result.extend([str(x) for x in v])
            else:
                result.append(str(v))
        return result
    if isinstance(cols, str):
        return [cols]
    if hasattr(cols, "tolist"):
        # ndarray / pd.Index / pd.Series
        return [str(x) for x in cols.tolist()]
    if isinstance(cols, (list, tuple)):
        result = []
        for item in cols:
            if isinstance(item, tuple):
                result.append(str(item[0]))  # tuple → 取第一個元素
            else:
                result.append(str(item))
        return result
    return [str(cols)]


def _normalize_cols(
    cols, df: pd.DataFrame, max_cols: int = 5, fallback: str = "std"
) -> list:
    """
    交集 + 截斷 + fallback。
    cols 可以是任何亂七八糟的型別，都能安全處理。
    """
    flat = _flatten_any(cols)
    valid = [c for c in flat if c in df.columns]
    missing = set(flat) - set(valid)
    if missing:
        print(f"[sigma] 忽略不存在的欄位: {list(missing)[:5]}")

    if not valid and fallback == "std":
        # fallback: 取 std 最大的 N 欄
        numeric = df.select_dtypes(include="number")
        if not numeric.empty:
            valid = numeric.std().nlargest(max_cols).index.tolist()
            print(f"[sigma] 無有效欄位，自動取 std Top {max_cols}: {valid[:3]}...")

    if len(valid) > max_cols:
        print(f"[sigma] 欄位數 {len(valid)} 超過上限 {max_cols}，已截斷")
        valid = valid[:max_cols]

    return valid


def _safe_indices(indices, df: pd.DataFrame, max_markers: int = 10) -> list:
    """統一轉換 anomaly indices → list[loc index]，上限 max_markers"""
    if indices is None:
        return []
    flat = _flatten_any(indices)
    # 轉回原始型別 (int)
    result = []
    for idx in flat:
        try:
            idx_val = int(idx)
            if idx_val in df.index:
                result.append(idx_val)
        except (ValueError, TypeError):
            if idx in df.index:
                result.append(idx)
    if len(result) > max_markers:
        result = result[:max_markers]
    return result


def plot_scatter(
    df: pd.DataFrame,
    x,
    y,
    hue=None,
    anomaly_indices=None,
    title: str = "",
):
    """
    安全散佈圖。
    x, y: 欄位名 (str 或 list — 取第一個)
    hue: 可選顏色欄位
    anomaly_indices: 異常點 index (loc)，會用紅色標記
    """
    try:
        import matplotlib.pyplot as plt

        # 正規化 x, y
        x_cols = _flatten_any(x)
        y_cols = _flatten_any(y)
        if not x_cols or not y_cols:
            print("[sigma.plot_scatter] x 或 y 為空，跳過")
            return
        x_col, y_col = x_cols[0], y_cols[0]

        if x_col not in df.columns:
            print(f"[sigma.plot_scatter] '{x_col}' 不存在，跳過")
            return
        if y_col not in df.columns:
            print(f"[sigma.plot_scatter] '{y_col}' 不存在，跳過")
            return

        data = df[[x_col, y_col]].dropna()
        if data.empty:
            print("[sigma.plot_scatter] 無有效資料，跳過")
            return

        n = len(data)
        alpha = min(0.6, 2000 / max(n, 1))
        s = max(5, min(30, 3000 / max(n, 1)))

        fig, ax = plt.subplots(figsize=(10, 6))
        ax.scatter(
            data[x_col], data[y_col], alpha=alpha, s=s, color="#3B82F6", label="正常"
        )

        # 標記異常點
        anom = _safe_indices(anomaly_indices, data, max_markers=20)
        if anom:
            anom_data = data.loc[data.index.isin(anom)]
            ax.scatter(
                anom_data[x_col],
                anom_data[y_col],
                color="#EF4444",
                s=s * 3,
                zorder=5,
                label="異常",
                edgecolors="black",
            )

        ax.set_xlabel(x_col)
        ax.set_ylabel(y_col)
        ax.set_title(title or f"{x_col} vs {y_col}")
        ax.legend()
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.show()
    except Exception as e:
        print(f"[sigma.plot_scatter] 繪圖失敗: {e}")


def plot_trend(
    df: pd.DataFrame,
    cols,
    anomaly_indices=None,
    window: int = None,
    title: str = "",
):
    """
    安全趨勢圖。
    cols: 欄位名 list (上限 5)
    anomaly_indices: 異常點 index，標紅色 axvline (上限 10)
    window: 移動平均窗口 (None = auto)
    """
    try:
        import matplotlib.pyplot as plt

        valid_cols = _normalize_cols(cols, df, max_cols=5)
        if not valid_cols:
            print("[sigma.plot_trend] 無有效欄位，跳過")
            return

        anom = _safe_indices(anomaly_indices, df, max_markers=10)
        _desc = title or f"趨勢圖: {', '.join(valid_cols[:3])}"
        if anom:
            _desc += f" (標記 {len(anom)} 筆異常)"
        print(f"[圖表] {_desc}")

        n_cols = len(valid_cols)
        fig, axes = plt.subplots(n_cols, 1, figsize=(10, 2.5 * n_cols), sharex=True)
        if n_cols == 1:
            axes = [axes]

        win = window or max(5, len(df) // 20)
        colors = ["#3B82F6", "#10B981", "#F59E0B", "#8B5CF6", "#EF4444"]

        for i, col in enumerate(valid_cols):
            series = df[col].dropna()
            axes[i].plot(
                series.index,
                series.values,
                alpha=0.5,
                color=colors[i % len(colors)],
                linewidth=0.8,
            )
            # 移動平均
            if len(series) > win:
                ma = series.rolling(win, center=True).mean()
                axes[i].plot(
                    ma.index,
                    ma.values,
                    color=colors[i % len(colors)],
                    linewidth=2.0,
                    label=f"MA({win})",
                )
            # 異常標記
            for idx in anom:
                if idx in series.index:
                    axes[i].axvline(x=idx, color="#EF4444", alpha=0.3, linewidth=1.5)
            axes[i].set_ylabel(col, fontsize=9)
            axes[i].legend(loc="upper right", fontsize=8)
            axes[i].grid(True, alpha=0.3)

        axes[-1].set_xlabel("樣本序號")
        _short = (
            (title.split(":")[0] if ":" in title else title)
            if title
            else ", ".join(valid_cols[:3])
        )
        fig.suptitle(_short, fontsize=11, fontweight="bold")
        plt.tight_layout()
        plt.show()
    except Exception as e:
        print(f"[sigma.plot_trend] 繪圖失敗: {e}")


def plot_distribution_compare(
    df: pd.DataFrame,
    col,
    group_a_idx=None,
    group_b_idx=None,
    labels: tuple = ("Group A", "Group B"),
    title: str = "",
):
    """
    安全分佈對比圖 (histogram + mean/median line)。
    col: 單一欄位名
    group_a_idx / group_b_idx: 兩組的 loc index (list/array)
    labels: 兩組的標籤
    """
    try:
        import matplotlib.pyplot as plt

        col_name = _flatten_any(col)
        if not col_name:
            print("[sigma.plot_distribution_compare] col 為空，跳過")
            return
        col_name = col_name[0]

        if col_name not in df.columns:
            print(f"[sigma.plot_distribution_compare] '{col_name}' 不存在，跳過")
            return

        # 取兩組資料
        a_idx = _safe_indices(group_a_idx, df, max_markers=9999)
        b_idx = _safe_indices(group_b_idx, df, max_markers=9999)

        # 自動生成描述性 label
        labels = (
            _label_from_indices(a_idx, labels[0]),
            _label_from_indices(b_idx, labels[1]),
        )

        if not a_idx and not b_idx:
            # 沒指定分組 → 全部畫
            data = df[col_name].dropna()
            fig, ax = plt.subplots(figsize=(10, 5))
            ax.hist(
                data, bins=min(50, max(10, len(data) // 5)), alpha=0.7, color="#3B82F6"
            )
            ax.axvline(
                data.mean(),
                color="#EF4444",
                linewidth=2,
                label=f"Mean={data.mean():.3f}",
            )
            ax.axvline(
                data.median(),
                color="#F59E0B",
                linewidth=2,
                linestyle="--",
                label=f"Median={data.median():.3f}",
            )
            ax.set_xlabel(col_name)
            ax.set_title(title or f"{col_name} 分佈")
            ax.legend()
            plt.tight_layout()
            plt.show()
            return

        series_a = df.loc[df.index.isin(a_idx), col_name].dropna()
        series_b = df.loc[df.index.isin(b_idx), col_name].dropna()

        fig, ax = plt.subplots(figsize=(10, 5))
        bins = min(50, max(10, max(len(series_a), len(series_b)) // 3))

        if not series_a.empty:
            ax.hist(
                series_a,
                bins=bins,
                alpha=0.5,
                color="#3B82F6",
                label=f"{labels[0]} (n={len(series_a)})",
            )
            ax.axvline(series_a.mean(), color="#3B82F6", linewidth=2, linestyle="--")
        if not series_b.empty:
            ax.hist(
                series_b,
                bins=bins,
                alpha=0.5,
                color="#EF4444",
                label=f"{labels[1]} (n={len(series_b)})",
            )
            ax.axvline(series_b.mean(), color="#EF4444", linewidth=2, linestyle="--")

        _desc = (
            title
            or f"{col_name}: {labels[0]} ({len(series_a)}筆) vs {labels[1]} ({len(series_b)}筆)"
        )
        print(f"[圖表] {_desc}")
        ax.set_xlabel(col_name)
        ax.set_title(col_name)
        ax.legend()
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.show()
    except Exception as e:
        print(f"[sigma.plot_distribution_compare] 繪圖失敗: {e}")


# ============================================================
# 7. 製程能力分析 (Cpk) + 等高線圖
# ============================================================


def process_capability(
    series,
    usl=None,
    lsl=None,
    target=None,
    title: str = "",
):
    """
    製程能力分析。
    計算 Cp, Cpk, Ppk 並繪製直方圖 + USL/LSL/Target 線。

    Parameters:
        series: pd.Series 或 array-like
        usl: 規格上限 (可選)
        lsl: 規格下限 (可選)
        target: 目標值 (可選)
        title: 圖表標題

    Returns:
        dict: {cp, cpk, ppk, mean, std, within_spec_pct, n, usl, lsl, target}
    """
    try:
        import matplotlib.pyplot as plt

        data = pd.Series(series).dropna()
        if len(data) < 5:
            print("[sigma.process_capability] 資料不足 5 筆，跳過")
            return {"error": "資料不足"}

        mean = float(data.mean())
        std = float(data.std(ddof=1))
        n = len(data)

        result = {"mean": mean, "std": std, "n": n}

        # Cp / Cpk 計算 (需要 USL 和 LSL)
        if usl is not None and lsl is not None:
            usl, lsl = float(usl), float(lsl)
            result["usl"] = usl
            result["lsl"] = lsl

            if std > 1e-10:
                cp = (usl - lsl) / (6 * std)
                cpu = (usl - mean) / (3 * std)
                cpl = (mean - lsl) / (3 * std)
                cpk = min(cpu, cpl)
                result["cp"] = round(cp, 3)
                result["cpk"] = round(cpk, 3)
                result["cpu"] = round(cpu, 3)
                result["cpl"] = round(cpl, 3)
            else:
                result["cp"] = float("inf")
                result["cpk"] = float("inf")

            # 規格內比例
            within = ((data >= lsl) & (data <= usl)).sum()
            result["within_spec_pct"] = round(within / n * 100, 2)
        elif usl is not None:
            usl = float(usl)
            result["usl"] = usl
            if std > 1e-10:
                result["cpu"] = round((usl - mean) / (3 * std), 3)
            within = (data <= usl).sum()
            result["within_spec_pct"] = round(within / n * 100, 2)
        elif lsl is not None:
            lsl = float(lsl)
            result["lsl"] = lsl
            if std > 1e-10:
                result["cpl"] = round((mean - lsl) / (3 * std), 3)
            within = (data >= lsl).sum()
            result["within_spec_pct"] = round(within / n * 100, 2)

        if target is not None:
            target = float(target)
            result["target"] = target
            result["offset_from_target"] = round(mean - target, 4)

        # Ppk (使用整體標準差)
        std_overall = float(data.std(ddof=0))
        if std_overall > 1e-10:
            if usl is not None and lsl is not None:
                ppk = min(
                    (usl - mean) / (3 * std_overall), (mean - lsl) / (3 * std_overall)
                )
                result["ppk"] = round(ppk, 3)

        # --- 繪圖 ---
        col_name = getattr(series, "name", "Parameter")
        _desc = title or f"{col_name} 製程能力分析"
        cpk_str = f"Cpk={result.get('cpk', 'N/A')}"
        if isinstance(result.get("cpk"), float):
            cpk_str = f"Cpk={result['cpk']:.3f}"
        print(f"[圖表] {_desc} ({cpk_str})")

        fig, ax = plt.subplots(figsize=(12, 6))

        # 直方圖
        bins = min(50, max(15, n // 5))
        ax.hist(
            data,
            bins=bins,
            alpha=0.6,
            color="#3B82F6",
            edgecolor="#1E40AF",
            density=True,
            label="分佈",
        )

        # 密度曲線
        try:
            from scipy.stats import norm

            x_range = np.linspace(data.min() - std * 2, data.max() + std * 2, 200)
            pdf = norm.pdf(x_range, mean, std)
            ax.plot(x_range, pdf, color="#3B82F6", linewidth=2, label="常態分佈")
        except ImportError:
            pass

        # 均值線
        ax.axvline(
            mean, color="#1E40AF", linewidth=2, linestyle="-", label=f"Mean={mean:.4f}"
        )

        # 規格線
        if lsl is not None:
            ax.axvline(
                lsl, color="#EF4444", linewidth=2.5, linestyle="--", label=f"LSL={lsl}"
            )
        if usl is not None:
            ax.axvline(
                usl, color="#EF4444", linewidth=2.5, linestyle="--", label=f"USL={usl}"
            )
        if target is not None:
            ax.axvline(
                target,
                color="#10B981",
                linewidth=2.5,
                linestyle="-.",
                label=f"Target={target}",
            )

        # USL/LSL 之間的區域著色
        if usl is not None and lsl is not None:
            ax.axvspan(lsl, usl, alpha=0.08, color="#10B981")

        # 統計資訊文字框
        stats_lines = [f"n = {n}", f"μ = {mean:.4f}", f"σ = {std:.4f}"]
        if "cp" in result:
            stats_lines.append(f"Cp = {result['cp']:.3f}")
        if "cpk" in result:
            stats_lines.append(f"Cpk = {result['cpk']:.3f}")
        if "ppk" in result:
            stats_lines.append(f"Ppk = {result['ppk']:.3f}")
        if "within_spec_pct" in result:
            stats_lines.append(f"規格內 = {result['within_spec_pct']:.1f}%")
        if "offset_from_target" in result:
            stats_lines.append(f"偏移 = {result['offset_from_target']:+.4f}")

        stats_text = "\n".join(stats_lines)
        ax.text(
            0.98,
            0.95,
            stats_text,
            transform=ax.transAxes,
            fontsize=10,
            verticalalignment="top",
            horizontalalignment="right",
            bbox=dict(
                boxstyle="round,pad=0.5",
                facecolor="white",
                edgecolor="#D1D5DB",
                alpha=0.9,
            ),
            fontfamily="monospace",
        )

        # Cpk 等級色標
        cpk_val = result.get("cpk")
        if cpk_val is not None and isinstance(cpk_val, (int, float)):
            if cpk_val >= 1.33:
                grade, grade_color = "優良 (≥1.33)", "#10B981"
            elif cpk_val >= 1.0:
                grade, grade_color = "尚可 (≥1.0)", "#F59E0B"
            elif cpk_val >= 0.67:
                grade, grade_color = "警告 (≥0.67)", "#F97316"
            else:
                grade, grade_color = "不足 (<0.67)", "#EF4444"
            ax.text(
                0.02,
                0.95,
                f"Cpk: {grade}",
                transform=ax.transAxes,
                fontsize=12,
                fontweight="bold",
                color=grade_color,
                verticalalignment="top",
            )

        ax.set_xlabel(col_name)
        ax.set_ylabel("機率密度")
        ax.set_title(_desc)
        ax.legend(loc="upper left", fontsize=9)
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.show()

        return result

    except Exception as e:
        print(f"[sigma.process_capability] 失敗: {e}")
        return {"error": str(e)}


def contour_response_surface(
    df: pd.DataFrame,
    x1,
    x2,
    y,
    usl=None,
    lsl=None,
    target=None,
    resolution: int = 50,
    title: str = "",
):
    """
    等高線圖 (Response Surface)。
    用 Top-2 重要 X 和 Y 繪製二維等高線圖，標示最佳操作區域。

    Parameters:
        df: DataFrame
        x1, x2: 兩個 X 欄位名
        y: Y 欄位名
        usl, lsl, target: Y 的規格
        resolution: 網格解析度
        title: 圖表標題
    """
    try:
        import matplotlib.pyplot as plt
        from scipy.interpolate import griddata

        # 正規化欄位名
        x1_col = _flatten_any(x1)[0] if _flatten_any(x1) else None
        x2_col = _flatten_any(x2)[0] if _flatten_any(x2) else None
        y_col = _flatten_any(y)[0] if _flatten_any(y) else None

        if not x1_col or not x2_col or not y_col:
            print("[sigma.contour_response_surface] x1/x2/y 欄位名無效")
            return

        for col in [x1_col, x2_col, y_col]:
            if col not in df.columns:
                print(f"[sigma.contour_response_surface] '{col}' 不存在，跳過")
                return

        data = df[[x1_col, x2_col, y_col]].dropna()
        if len(data) < 10:
            print("[sigma.contour_response_surface] 資料不足 10 筆，跳過")
            return

        x1_vals = data[x1_col].values
        x2_vals = data[x2_col].values
        y_vals = data[y_col].values

        _desc = title or f"Response Surface: {y_col} = f({x1_col}, {x2_col})"
        print(f"[圖表] {_desc}")

        # 建立網格
        x1_grid = np.linspace(x1_vals.min(), x1_vals.max(), resolution)
        x2_grid = np.linspace(x2_vals.min(), x2_vals.max(), resolution)
        X1, X2 = np.meshgrid(x1_grid, x2_grid)

        # 插值 (cubic, fallback to linear, then nearest)
        try:
            Z = griddata((x1_vals, x2_vals), y_vals, (X1, X2), method="cubic")
        except Exception:
            Z = None
        if Z is None or np.all(np.isnan(Z)):
            try:
                Z = griddata((x1_vals, x2_vals), y_vals, (X1, X2), method="linear")
            except Exception:
                Z = None
        if Z is None or np.all(np.isnan(Z)):
            try:
                Z = griddata((x1_vals, x2_vals), y_vals, (X1, X2), method="nearest")
            except Exception:
                Z = None

        fig, ax = plt.subplots(figsize=(12, 9))

        if Z is not None and not np.all(np.isnan(Z)):
            # 等高線填色
            levels = 20
            cf = ax.contourf(X1, X2, Z, levels=levels, cmap="RdYlGn_r", alpha=0.85)
            plt.colorbar(cf, ax=ax, label=y_col, shrink=0.85)

            # 等高線線條
            ax.contour(
                X1, X2, Z, levels=levels, colors="white", linewidths=0.3, alpha=0.5
            )

            # 規格等高線 (USL/LSL/Target)
            if target is not None:
                target = float(target)
                cs_target = ax.contour(
                    X1,
                    X2,
                    Z,
                    levels=[target],
                    colors=["#10B981"],
                    linewidths=3,
                    linestyles=["-"],
                )
                ax.clabel(cs_target, fmt=f"Target={target:.2f}", fontsize=9)
            if usl is not None:
                usl = float(usl)
                cs_usl = ax.contour(
                    X1,
                    X2,
                    Z,
                    levels=[usl],
                    colors=["#EF4444"],
                    linewidths=2.5,
                    linestyles=["--"],
                )
                ax.clabel(cs_usl, fmt=f"USL={usl:.2f}", fontsize=9)
            if lsl is not None:
                lsl = float(lsl)
                cs_lsl = ax.contour(
                    X1,
                    X2,
                    Z,
                    levels=[lsl],
                    colors=["#EF4444"],
                    linewidths=2.5,
                    linestyles=["--"],
                )
                ax.clabel(cs_lsl, fmt=f"LSL={lsl:.2f}", fontsize=9)
        else:
            print("[sigma.contour_response_surface] 插值全 NaN，改用散佈圖模式")

        # 散佈原始點
        ax.scatter(
            x1_vals,
            x2_vals,
            c=y_vals,
            cmap="RdYlGn_r",
            edgecolors="black",
            s=15,
            alpha=0.6,
            linewidths=0.5,
        )

        # 最佳點標記
        if target is not None:
            best_idx = np.argmin(np.abs(y_vals - target))
        else:
            best_idx = np.argmin(y_vals)  # minimize by default
        ax.scatter(
            x1_vals[best_idx],
            x2_vals[best_idx],
            color="#FBBF24",
            s=200,
            marker="*",
            edgecolors="black",
            linewidths=1.5,
            zorder=10,
            label="最佳觀測點",
        )

        ax.set_xlabel(x1_col, fontsize=12)
        ax.set_ylabel(x2_col, fontsize=12)
        ax.set_title(_desc, fontsize=13, fontweight="bold")
        ax.legend(loc="upper right")
        ax.grid(True, alpha=0.2)
        plt.tight_layout()
        plt.show()

    except ImportError:
        print(
            "[sigma.contour_response_surface] 需要 scipy.interpolate (pip install scipy)"
        )
    except Exception as e:
        print(f"[sigma.contour_response_surface] 繪圖失敗: {e}")


def sensitivity_analysis(
    df: pd.DataFrame,
    target,
    top_n: int = 10,
    title: str = "",
):
    """
    敏感度分析 (Sensitivity Analysis)。
    計算每個 X 變動 1σ 時，Y 變動多少 σ（標準化敏感度）。

    Parameters:
        df: DataFrame
        target: Y 欄位名
        top_n: 顯示前幾名
        title: 圖表標題

    Returns:
        list[dict]: [{col, sensitivity, r, direction}, ...]
    """
    try:
        import matplotlib.pyplot as plt

        target_col = _flatten_any(target)[0] if _flatten_any(target) else None
        if not target_col or target_col not in df.columns:
            print(f"[sigma.sensitivity_analysis] '{target}' 不存在，跳過")
            return []

        y = df[target_col].dropna()
        y_std = float(y.std())
        if y_std < 1e-10:
            print("[sigma.sensitivity_analysis] Y 標準差為 0，跳過")
            return []

        numeric_cols = df.select_dtypes(include="number").columns.tolist()
        numeric_cols = [c for c in numeric_cols if c != target_col]

        results = []
        for col in numeric_cols:
            pair = df[[target_col, col]].dropna()
            if len(pair) < 10:
                continue
            x_std = float(pair[col].std())
            if x_std < 1e-10:
                continue

            r = float(pair.corr().iloc[0, 1])
            if np.isnan(r):
                continue

            # 標準化敏感度 = r * (σ_y / σ_x) * (σ_x / σ_y) = r
            # 但更有用的: β_standardized = r (in simple linear regression)
            # 實際敏感度: Δy_σ = |r| (Y 變動幾個 σ when X 變動 1σ)
            sensitivity = abs(r)
            direction = "↑正" if r > 0 else "↓負"

            results.append(
                {
                    "col": col,
                    "sensitivity": round(sensitivity, 4),
                    "r": round(r, 4),
                    "direction": direction,
                    "x_std": round(x_std, 4),
                    "y_impact_per_x_sigma": round(r * y_std, 4),
                }
            )

        results.sort(key=lambda x: x["sensitivity"], reverse=True)
        results = results[:top_n]

        if not results:
            print("[sigma.sensitivity_analysis] 無有效結果")
            return []

        # --- 繪圖 ---
        _desc = title or f"敏感度分析: {target_col}"
        print(f"[圖表] {_desc}")

        fig, ax = plt.subplots(figsize=(12, max(4, len(results) * 0.5 + 1)))

        cols = [r["col"] for r in reversed(results)]
        sens = [r["sensitivity"] for r in reversed(results)]
        colors = ["#EF4444" if r["r"] < 0 else "#3B82F6" for r in reversed(results)]

        bars = ax.barh(cols, sens, color=colors, alpha=0.8, edgecolor="white")

        # 數值標示
        for bar, r_item in zip(bars, reversed(results)):
            w = bar.get_width()
            label = f"r={r_item['r']:+.3f} {r_item['direction']}"
            ax.text(
                w + 0.005,
                bar.get_y() + bar.get_height() / 2,
                label,
                va="center",
                fontsize=9,
                color="#374151",
            )

        ax.set_xlabel("標準化敏感度 |r| (X 變動 1σ → Y 變動幾 σ)")
        ax.set_title(_desc, fontsize=12, fontweight="bold")

        # 圖例
        from matplotlib.patches import Patch

        legend_elements = [
            Patch(facecolor="#3B82F6", label="正相關 (X↑ → Y↑)"),
            Patch(facecolor="#EF4444", label="負相關 (X↑ → Y↓)"),
        ]
        ax.legend(handles=legend_elements, loc="lower right", fontsize=9)
        ax.grid(True, alpha=0.3, axis="x")
        ax.set_xlim(0, max(sens) * 1.3)
        plt.tight_layout()
        plt.show()

        # 印出表格
        print(f"\n{'參數':<35} {'敏感度':>8} {'r值':>8} {'方向':>5} {'Y變量/Xσ':>10}")
        print("-" * 75)
        for r in results:
            print(
                f"{r['col']:<35} {r['sensitivity']:>8.4f} {r['r']:>+8.4f} "
                f"{r['direction']:>5} {r['y_impact_per_x_sigma']:>+10.4f}"
            )

        return results

    except Exception as e:
        print(f"[sigma.sensitivity_analysis] 失敗: {e}")
        return []


def interaction_plot(
    df: pd.DataFrame,
    x1,
    x2,
    y,
    n_levels: int = 3,
    title: str = "",
):
    """
    交互效應圖 (Interaction Plot)。
    將 X1, X2 各分 n_levels 個水平，看 Y 的均值如何隨 X1 變化（線 = X2 水平）。
    如果線條平行 → 無交互效應；如果交叉 → 有交互效應。

    Parameters:
        df: DataFrame
        x1, x2: 兩個 X 欄位名
        y: Y 欄位名
        n_levels: 分幾個水平 (default=3: Low/Mid/High)
        title: 圖表標題
    """
    try:
        import matplotlib.pyplot as plt

        x1_col = _flatten_any(x1)[0] if _flatten_any(x1) else None
        x2_col = _flatten_any(x2)[0] if _flatten_any(x2) else None
        y_col = _flatten_any(y)[0] if _flatten_any(y) else None

        if not all([x1_col, x2_col, y_col]):
            print("[sigma.interaction_plot] 欄位名無效")
            return

        for col in [x1_col, x2_col, y_col]:
            if col not in df.columns:
                print(f"[sigma.interaction_plot] '{col}' 不存在，跳過")
                return

        data = df[[x1_col, x2_col, y_col]].dropna()
        if len(data) < 20:
            print("[sigma.interaction_plot] 資料不足 20 筆，跳過")
            return

        _desc = title or f"交互效應: {y_col} = f({x1_col} × {x2_col})"
        print(f"[圖表] {_desc}")

        # 分水平 — 不預設 labels，讓 qcut 自動決定 bin 數（duplicates="drop" 可能減少）
        try:
            _x1_q = pd.qcut(data[x1_col], n_levels, duplicates="drop")
            _x2_q = pd.qcut(data[x2_col], n_levels, duplicates="drop")
        except Exception as _qe:
            print(f"[sigma.interaction_plot] qcut 失敗: {_qe}")
            return

        # 重命名 categories 為 Low/Mid/High
        _rename_map = {0: "Low", 1: "Mid", 2: "High"}
        data["_x1_level"] = _x1_q.cat.codes.map(
            lambda c: _rename_map.get(c, f"L{c + 1}")
        ).astype("category")
        data["_x2_level"] = _x2_q.cat.codes.map(
            lambda c: _rename_map.get(c, f"L{c + 1}")
        ).astype("category")

        # 重新取實際 level labels
        x2_levels = sorted(data["_x2_level"].unique())
        x1_levels = sorted(data["_x1_level"].unique())

        # 計算每組均值
        grouped = data.groupby(["_x1_level", "_x2_level"])[y_col].agg(["mean", "count"])
        grouped = grouped.reset_index()

        fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))

        # --- Plot 1: X1 為 X 軸, X2 為線條 ---
        _colors = ["#3B82F6", "#F97316", "#10B981", "#8B5CF6", "#EF4444"]
        for i, x2_lv in enumerate(x2_levels):
            subset = grouped[grouped["_x2_level"] == x2_lv]
            if len(subset) > 0:
                axes[0].plot(
                    subset["_x1_level"].astype(str),
                    subset["mean"],
                    marker="o",
                    linewidth=2,
                    markersize=8,
                    color=_colors[i % len(_colors)],
                    label=f"{x2_col}={x2_lv}",
                )
                # 標數值
                for _, row in subset.iterrows():
                    axes[0].annotate(
                        f"{row['mean']:.3f}",
                        (str(row["_x1_level"]), row["mean"]),
                        textcoords="offset points",
                        xytext=(0, 10),
                        fontsize=8,
                        ha="center",
                    )

        axes[0].set_xlabel(x1_col, fontsize=11)
        axes[0].set_ylabel(f"Mean({y_col})", fontsize=11)
        axes[0].set_title(f"{x1_col} × {x2_col} → {y_col}", fontsize=11)
        axes[0].legend(fontsize=9)
        axes[0].grid(True, alpha=0.3)

        # --- Plot 2: X2 為 X 軸, X1 為線條 ---
        for i, x1_lv in enumerate(x1_levels):
            subset = grouped[grouped["_x1_level"] == x1_lv]
            if len(subset) > 0:
                axes[1].plot(
                    subset["_x2_level"].astype(str),
                    subset["mean"],
                    marker="s",
                    linewidth=2,
                    markersize=8,
                    color=_colors[i % len(_colors)],
                    label=f"{x1_col}={x1_lv}",
                )
                for _, row in subset.iterrows():
                    axes[1].annotate(
                        f"{row['mean']:.3f}",
                        (str(row["_x2_level"]), row["mean"]),
                        textcoords="offset points",
                        xytext=(0, 10),
                        fontsize=8,
                        ha="center",
                    )

        axes[1].set_xlabel(x2_col, fontsize=11)
        axes[1].set_ylabel(f"Mean({y_col})", fontsize=11)
        axes[1].set_title(f"{x2_col} × {x1_col} → {y_col}", fontsize=11)
        axes[1].legend(fontsize=9)
        axes[1].grid(True, alpha=0.3)

        # 判斷交互效應
        # 如果線條交叉（不同 x2 level 的 slope 方向不同）→ 有交互
        _has_interaction = False
        if len(x1_levels) >= 2 and len(x2_levels) >= 2:
            slopes = []
            for x2_lv in x2_levels:
                subset = grouped[grouped["_x2_level"] == x2_lv].sort_values("_x1_level")
                if len(subset) >= 2:
                    slopes.append(subset["mean"].iloc[-1] - subset["mean"].iloc[0])
            if slopes and len(slopes) >= 2:
                # 如果 slopes 方向不同 → 有交互
                _has_interaction = any(
                    s1 * s2 < 0 for s1, s2 in zip(slopes[:-1], slopes[1:])
                )
                # 或 slope 差異大於 50% → 可能有交互
                if not _has_interaction and max(abs(s) for s in slopes) > 0:
                    _ratio = min(abs(s) for s in slopes) / max(abs(s) for s in slopes)
                    _has_interaction = _ratio < 0.3

        _interact_text = "⚠️ 交互效應顯著" if _has_interaction else "✓ 無明顯交互效應"
        fig.suptitle(f"{_desc}\n{_interact_text}", fontsize=12, fontweight="bold")
        plt.tight_layout(rect=[0, 0, 1, 0.92])
        plt.show()

        # 印出交互效應判定
        print(f"\n交互效應判定: {_interact_text}")
        if _has_interaction:
            print(f"  → {x1_col} 和 {x2_col} 需要一起調整，不能獨立優化")
        else:
            print(f"  → {x1_col} 和 {x2_col} 可以獨立調整")

    except Exception as e:
        print(f"[sigma.interaction_plot] 繪圖失敗: {e}")
