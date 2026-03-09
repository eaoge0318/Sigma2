"""
Evidence Chart Generator (通用版)

為每個工具的結果自動生成最適合的 matplotlib 圖表，
以 base64 PNG 格式回傳，供多模態 LLM 分析。

設計原則：
- 不修改任何工具本身的代碼
- 根據結果中常見的 key pattern 自動選擇圖表類型
- 生成精簡的小圖 (300 DPI, 適合 LLM 輸入)
- 如果工具結果無法繪圖，返回 None
"""

import base64
import io
import logging

logger = logging.getLogger(__name__)

# 抑制 matplotlib 的字體警告
import warnings

warnings.filterwarnings("ignore", category=UserWarning, module="matplotlib")


def generate_evidence_chart(tool_name: str, result: dict) -> str | None:
    """
    根據工具名和結果，生成對應的 matplotlib 圖表。

    Returns:
        base64-encoded PNG string, or None if chart cannot be generated.
    """
    if not isinstance(result, dict):
        return None

    try:
        import matplotlib

        matplotlib.use("Agg")  # 非互動模式
        import matplotlib.pyplot as plt
        import numpy as np

        # 嘗試設定中文字體 (可選)
        try:
            plt.rcParams["font.sans-serif"] = [
                "Microsoft JhengHei",
                "SimHei",
                "DejaVu Sans",
            ]
            plt.rcParams["axes.unicode_minus"] = False
        except Exception:
            pass

        fig = None

        # ==========================================
        # 根據工具名稱 dispatch 到對應的繪圖函數
        # ==========================================
        if tool_name in ("draw_trend", "get_time_series_data"):
            fig = _chart_time_series(result, plt, np)

        elif tool_name == "hotelling_t2_analysis":
            fig = _chart_t2(result, plt, np)

        elif tool_name == "analyze_distribution":
            fig = _chart_distribution(result, plt, np)

        elif tool_name in ("compare_data_segments",):
            fig = _chart_segment_comparison(result, plt, np)

        elif tool_name == "analyze_residuals":
            fig = _chart_residuals(result, plt, np)

        elif tool_name in ("get_top_correlations",):
            fig = _chart_correlations(result, plt, np)

        elif tool_name == "analyze_feature_importance":
            fig = _chart_feature_importance(result, plt, np)

        elif tool_name in ("detect_outliers",):
            fig = _chart_outliers(result, plt, np)

        elif tool_name in ("scan_anomaly_segments",):
            fig = _chart_anomaly_segments(result, plt, np)

        elif tool_name in ("classify_anomaly_type",):
            fig = _chart_anomaly_type(result, plt, np)

        elif tool_name in ("cross_correlation_lag",):
            fig = _chart_cross_correlation(result, plt, np)

        elif tool_name in ("frequency_analysis",):
            fig = _chart_frequency(result, plt, np)

        elif tool_name in ("find_temporal_patterns",):
            fig = _chart_temporal_patterns(result, plt, np)

        elif tool_name in ("control_loop_assessment",):
            fig = _chart_control_loop(result, plt, np)

        elif tool_name in ("cv_ranking",):
            fig = _chart_cv_ranking(result, plt, np)

        elif tool_name in ("distribution_shift_analysis",):
            fig = _chart_distribution_shift(result, plt, np)

        elif tool_name in ("performance_segmentation",):
            fig = _chart_performance_seg(result, plt, np)

        # ==========================================
        # Fallback: 嘗試通用繪圖
        # ==========================================
        if fig is None:
            fig = _chart_generic(tool_name, result, plt, np)

        if fig is None:
            result_keys = list(result.keys())[:10]
            logger.warning(
                f"[EvidenceChart] No chart generated for tool={tool_name}, result_keys={result_keys}"
            )
            return None

        # 轉為 base64 PNG
        buf = io.BytesIO()
        fig.savefig(
            buf,
            format="png",
            dpi=150,
            bbox_inches="tight",
            facecolor="white",
            edgecolor="none",
        )
        plt.close(fig)
        buf.seek(0)
        return base64.b64encode(buf.read()).decode("utf-8")

    except Exception as e:
        logger.warning(f"[EvidenceChart] Failed to generate chart for {tool_name}: {e}")
        return None


# ==========================================
# 各工具的繪圖函數
# ==========================================


def _chart_time_series(result, plt, np):
    """趨勢圖 — 從 data dict 繪製時序線圖 + 異常區段黃色標記"""
    data = result.get("data", {})
    params = result.get("parameters", [])
    time_col = result.get("time_column", "")

    if not data or not params:
        return None

    x = data.get(time_col, list(range(len(next(iter(data.values()))))))
    fig, ax = plt.subplots(figsize=(8, 3))
    for p in params[:5]:  # 最多畫 5 條
        if p in data:
            ax.plot(data[p], label=p, linewidth=0.8)

    # [標註] focus_range 綠色框
    focus = result.get("focus_range", result.get("range", {}))
    if isinstance(focus, dict):
        fr_start = focus.get("start", focus.get("from", None))
        fr_end = focus.get("end", focus.get("to", None))
        if fr_start is not None and fr_end is not None:
            ax.axvspan(
                fr_start,
                fr_end,
                alpha=0.15,
                color="limegreen",
                label=f"Focus: {fr_start}-{fr_end}",
            )

    # [標註] anomaly_zones 黃色底色
    zones = result.get("anomaly_zones", result.get("anomaly_indices", []))
    if isinstance(zones, list):
        for z in zones:
            if isinstance(z, dict):
                zs = z.get("start", z.get("from", 0))
                ze = z.get("end", z.get("to", zs + 1))
                ax.axvspan(zs, ze, alpha=0.2, color="gold", zorder=0)

    ax.set_title(f"Time Series ({', '.join(params[:3])})", fontsize=9)
    ax.legend(fontsize=7, loc="upper right")
    ax.tick_params(labelsize=7)
    return fig


def _chart_t2(result, plt, np):
    """T2 趨勢圖 + 閾值線 + 異常區段黃色標記"""
    t2_trend = result.get("t2_trend", [])
    threshold = result.get("t2_threshold", 0)
    if not t2_trend:
        return None

    vals = np.array(t2_trend)
    fig, ax = plt.subplots(figsize=(8, 3))
    colors = ["red" if v > threshold else "steelblue" for v in vals]
    ax.scatter(range(len(vals)), vals, c=colors, s=4, zorder=3)
    ax.plot(vals, color="steelblue", linewidth=0.6, alpha=0.5)
    ax.axhline(
        y=threshold,
        color="red",
        linestyle="--",
        linewidth=0.8,
        label=f"Threshold={threshold:.2f}",
    )

    # [標註] 超閾值的連續區段用黃色底色標記
    above = vals > threshold
    in_zone = False
    zone_start = 0
    for i, a in enumerate(above):
        if a and not in_zone:
            zone_start = i
            in_zone = True
        elif not a and in_zone:
            ax.axvspan(zone_start, i, alpha=0.2, color="gold", zorder=0)
            in_zone = False
    if in_zone:
        ax.axvspan(zone_start, len(vals), alpha=0.2, color="gold", zorder=0)

    ax.set_title(f"Hotelling T² (threshold={threshold:.2f})", fontsize=9)
    ax.set_ylabel("T²", fontsize=8)
    ax.set_xlabel("Row Index", fontsize=8)
    ax.legend(fontsize=7)
    ax.tick_params(labelsize=7)
    return fig


def _chart_distribution(result, plt, np):
    """分佈直方圖 — 從 histogram / histogram_data / stats 繪製"""
    # Priority 1: 已計算好的 histogram (counts + bins) — analyze_distribution 實際輸出格式
    hist_obj = result.get("histogram", {})
    if isinstance(hist_obj, dict) and "counts" in hist_obj and "bins" in hist_obj:
        counts = hist_obj["counts"]
        bins = hist_obj["bins"]
        if counts and bins and len(counts) > 0:
            fig, ax = plt.subplots(figsize=(6, 3))
            # bins 比 counts 多一個元素，用 bar 繪製
            bin_centers = [(bins[i] + bins[i + 1]) / 2 for i in range(len(counts))]
            bin_widths = [bins[i + 1] - bins[i] for i in range(len(counts))]
            ax.bar(
                bin_centers,
                counts,
                width=bin_widths,
                color="steelblue",
                edgecolor="white",
                linewidth=0.5,
                alpha=0.8,
            )
            param_name = result.get("parameter", "")
            skew = result.get("skewness", 0)
            kurtosis = result.get("kurtosis", 0)
            basic = result.get("basic_stats", {})
            mean_val = basic.get("mean", 0) if isinstance(basic, dict) else 0
            ax.set_title(
                f"Distribution: {param_name} (skew={skew:.2f}, kurtosis={kurtosis:.2f})",
                fontsize=9,
            )
            # 標記均值線
            if mean_val:
                ax.axvline(
                    x=mean_val,
                    color="red",
                    linestyle="--",
                    linewidth=0.8,
                    label=f"Mean={mean_val:.4f}",
                )
                ax.legend(fontsize=7)
            ax.tick_params(labelsize=7)
            return fig

    # Priority 2: 原始數據列表
    hist_data = result.get("histogram_data", result.get("data_values", []))
    if isinstance(hist_data, list) and len(hist_data) > 5:
        fig, ax = plt.subplots(figsize=(6, 3))
        ax.hist(
            hist_data,
            bins=min(50, len(hist_data) // 5),
            color="steelblue",
            edgecolor="white",
            linewidth=0.5,
            alpha=0.8,
        )
        dtype = result.get("distribution_type", "")
        skew = result.get("skewness", 0)
        mean = result.get("mean", 0)
        ax.set_title(
            f"Distribution ({dtype}, skew={skew:.2f}, mean={mean:.4f})", fontsize=9
        )
        ax.tick_params(labelsize=7)
        return fig

    # Fallback: 用 stats 畫 box plot 風格
    stats = result.get("stats", {})
    if stats:
        return _chart_stats_summary(stats, result, plt)
    return None


def _chart_segment_comparison(result, plt, np):
    """區段對比 — 柱狀圖顯示兩個區段的參數差異"""
    comparison = result.get("comparison", result.get("segment_comparison", {}))
    if isinstance(comparison, dict) and comparison:
        params = list(comparison.keys())[:15]
        if not params:
            return None
        fig, ax = plt.subplots(figsize=(8, 4))
        x = range(len(params))
        target_vals = []
        baseline_vals = []
        for p in params:
            p_data = comparison[p]
            if isinstance(p_data, dict):
                target_vals.append(p_data.get("target_mean", p_data.get("mean_a", 0)))
                baseline_vals.append(
                    p_data.get("baseline_mean", p_data.get("mean_b", 0))
                )
            else:
                target_vals.append(0)
                baseline_vals.append(0)
        width = 0.35
        ax.bar(
            [i - width / 2 for i in x],
            target_vals,
            width,
            label="Target",
            color="coral",
        )
        ax.bar(
            [i + width / 2 for i in x],
            baseline_vals,
            width,
            label="Baseline",
            color="steelblue",
        )
        ax.set_xticks(list(x))
        ax.set_xticklabels(
            [p[-15:] for p in params], rotation=45, ha="right", fontsize=6
        )
        ax.set_title("Segment Comparison (Target vs Baseline)", fontsize=9)
        ax.legend(fontsize=7)
        ax.tick_params(labelsize=7)
        fig.tight_layout()
        return fig

    # Fallback: top_deviations (compare_data_segments 的實際輸出格式)
    top_dev = result.get("top_deviations", result.get("top_differences", []))
    if isinstance(top_dev, list) and top_dev:
        items = [d for d in top_dev[:10] if isinstance(d, dict)]
        if items:
            params = [d.get("parameter", "?") for d in items]
            diffs = [
                d.get("z_score_diff", d.get("diff", d.get("z_diff", 0))) for d in items
            ]
            fig, ax = plt.subplots(figsize=(7, 3))
            colors = ["coral" if v > 0 else "steelblue" for v in diffs]
            ax.barh(params[::-1], diffs[::-1], color=colors[::-1])
            target_range = result.get("target_range", "?")
            ax.set_title(f"Segment Deviation (Target={target_range})", fontsize=9)
            ax.set_xlabel("Z-Score Deviation", fontsize=8)
            ax.tick_params(labelsize=7)
            fig.tight_layout()
            return fig
    return None


def _chart_residuals(result, plt, np):
    """殘差散佈圖"""
    residuals = result.get("residuals", result.get("residual_values", []))
    if isinstance(residuals, list) and len(residuals) > 5:
        fig, ax = plt.subplots(figsize=(7, 3))
        ax.scatter(range(len(residuals)), residuals, s=3, alpha=0.6, color="steelblue")
        ax.axhline(y=0, color="red", linestyle="--", linewidth=0.8)
        ax.set_title("Residual Analysis", fontsize=9)
        ax.set_ylabel("Residual", fontsize=8)
        ax.set_xlabel("Row Index", fontsize=8)
        ax.tick_params(labelsize=7)
        return fig

    # top external factors 柱狀圖
    ext_factors = result.get(
        "top_external_factors", result.get("external_correlations", [])
    )
    if isinstance(ext_factors, list) and ext_factors:
        names = [
            f.get("parameter", "?") for f in ext_factors[:10] if isinstance(f, dict)
        ]
        corrs = [
            abs(f.get("correlation", 0))
            for f in ext_factors[:10]
            if isinstance(f, dict)
        ]
        if names:
            fig, ax = plt.subplots(figsize=(7, 3))
            ax.barh(names, corrs, color="teal")
            ax.set_title(
                "Top External Factors (|correlation| with residuals)", fontsize=9
            )
            ax.tick_params(labelsize=7)
            fig.tight_layout()
            return fig
    return None


def _chart_correlations(result, plt, np):
    """相關性柱狀圖"""
    corrs = result.get("top_correlations", result.get("correlations", []))
    if isinstance(corrs, list) and corrs:
        names = [c.get("parameter", "?") for c in corrs[:10] if isinstance(c, dict)]
        vals = [c.get("correlation", 0) for c in corrs[:10] if isinstance(c, dict)]
        if names:
            fig, ax = plt.subplots(figsize=(7, 3))
            colors = ["coral" if v < 0 else "steelblue" for v in vals]
            ax.barh(names, vals, color=colors)
            target_name = result.get("target", "")
            title = (
                f"Top Correlations ({target_name})"
                if target_name
                else "Top Correlations"
            )
            ax.set_title(title, fontsize=9)
            ax.set_xlabel("r", fontsize=8)
            ax.axvline(x=0, color="gray", linewidth=0.5)
            ax.tick_params(labelsize=7)
            fig.tight_layout()
            return fig
    return None


def _chart_feature_importance(result, plt, np):
    """特徵重要性柱狀圖"""
    features = result.get("top_features", result.get("feature_importances", []))
    if isinstance(features, list) and features:
        names = [f.get("parameter", "?") for f in features[:10] if isinstance(f, dict)]
        imps = [
            f.get("importance_score", f.get("importance", 0))
            for f in features[:10]
            if isinstance(f, dict)
        ]
        if names:
            fig, ax = plt.subplots(figsize=(7, 3))
            ax.barh(names, imps, color="teal")
            ax.set_title("Feature Importance", fontsize=9)
            ax.tick_params(labelsize=7)
            fig.tight_layout()
            return fig
    return None


def _chart_outliers(result, plt, np):
    """異常值分佈 — Top 異常參數的 Z-Score"""
    top_params = result.get("top_abnormal_parameters", {})
    if isinstance(top_params, dict) and top_params:
        names = []
        z_vals = []
        for pname, pdata in list(top_params.items())[:10]:
            if isinstance(pdata, dict):
                stats = pdata.get("stats", {})
                max_z = max(
                    abs(stats.get("max_sigma", 0)),
                    abs(stats.get("min_sigma", 0)),
                    stats.get("max_z", 0),
                )
                names.append(pname[-20:])
                z_vals.append(max_z)
        if names:
            fig, ax = plt.subplots(figsize=(7, 3))
            colors = [
                "red" if z > 6 else ("orange" if z > 3 else "steelblue") for z in z_vals
            ]
            ax.barh(names, z_vals, color=colors)
            ax.axvline(x=3, color="orange", linestyle="--", linewidth=0.5, label="Z=3")
            ax.axvline(x=6, color="red", linestyle="--", linewidth=0.5, label="Z=6")
            ax.set_title("Top Anomalous Parameters (Z-Score)", fontsize=9)
            ax.legend(fontsize=7)
            ax.tick_params(labelsize=7)
            fig.tight_layout()
            return fig
    return None


def _chart_anomaly_segments(result, plt, np):
    """異常區段分佈 — 橫軸為 Row Index，縱軸為嚴重程度"""
    worst = result.get("worst_parameters", [])
    if isinstance(worst, list) and worst:
        names = [
            w.get("parameter", "?")[-20:] for w in worst[:10] if isinstance(w, dict)
        ]
        counts = [w.get("anomaly_count", 0) for w in worst[:10] if isinstance(w, dict)]
        if names:
            fig, ax = plt.subplots(figsize=(7, 3))
            ax.barh(names, counts, color="coral")
            ax.set_title("Anomaly Segment Count by Parameter", fontsize=9)
            ax.tick_params(labelsize=7)
            fig.tight_layout()
            return fig
    return None


def _chart_anomaly_type(result, plt, np):
    """異常類型分類結果 — 上圖: 類型分佈, 下圖: 趨勢圖+異常區段顏色標記"""
    colors_map = {
        "OSCILLATION": "#FFB74D",
        "SPIKE": "#E57373",
        "DRIFT": "#81C784",
        "LEVEL_SHIFT": "#BA68C8",
        "DIP_RECOVERY": "#4DD0E1",
        "MIXED": "#90A4AE",
        "SHIFTED_STABLE": "#06B6D4",
        "REGIME_CHANGE": "#90A4AE",
        "UNKNOWN": "#90A4AE",
    }

    # 取得分類結果
    type_summary = result.get("type_summary", {})
    classifications = result.get("classifications", result.get("segments", []))
    raw_values = result.get("raw_values", [])
    param = result.get("parameter", "")
    has_raw = isinstance(raw_values, list) and len(raw_values) > 5

    # 無異常偵測 — 文字卡片
    if (
        result.get("status") == "SUCCESS"
        and result.get("total_anomaly_regions", -1) == 0
    ):
        if has_raw:
            # 有原始數據：畫趨勢圖 + No anomaly 標記
            fig, ax = plt.subplots(figsize=(7, 3))
            x = list(range(len(raw_values)))
            ax.plot(x, raw_values, color="steelblue", linewidth=0.6, alpha=0.8)
            ax.set_title(f"No anomaly detected ({param})", fontsize=9, color="#4CAF50")
            ax.set_xlabel("Row Index", fontsize=8)
            ax.set_ylabel("Value", fontsize=8)
            ax.tick_params(labelsize=7)
            fig.tight_layout()
            return fig
        else:
            fig, ax = plt.subplots(figsize=(4, 2))
            ax.text(
                0.5,
                0.5,
                f"No anomaly\ndetected\n({param})",
                ha="center",
                va="center",
                fontsize=12,
                color="#4CAF50",
            )
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
            ax.axis("off")
            return fig

    # 判斷有幾張子圖
    has_type_summary = isinstance(type_summary, dict) and type_summary
    has_classifications = isinstance(classifications, list) and len(classifications) > 0

    if not has_type_summary and not has_classifications and not has_raw:
        # 單一分類結果 — 用文字卡片
        classification = result.get("classification", result.get("anomaly_type", ""))
        if classification:
            fig, ax = plt.subplots(figsize=(4, 2))
            ax.text(
                0.5,
                0.5,
                f"Type: {classification}",
                ha="center",
                va="center",
                fontsize=14,
                fontweight="bold",
            )
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
            ax.axis("off")
            return fig
        return None

    # 建立 type_counts（統一來源）
    type_counts = {}
    if has_type_summary:
        type_counts = type_summary
    elif has_classifications:
        for seg in classifications:
            atype = (
                seg.get("type", seg.get("anomaly_type", "UNKNOWN"))
                if isinstance(seg, dict)
                else "UNKNOWN"
            )
            type_counts[atype] = type_counts.get(atype, 0) + 1

    has_bar = bool(type_counts)
    n_plots = (1 if has_bar else 0) + (1 if has_raw else 0)

    if n_plots == 0:
        return None

    fig, axes = plt.subplots(n_plots, 1, figsize=(7, 3 * n_plots))
    if n_plots == 1:
        axes = [axes]

    ax_idx = 0

    # --- 上圖: 異常類型分佈柱狀圖 ---
    if has_bar:
        ax = axes[ax_idx]
        labels = list(type_counts.keys())
        values = list(type_counts.values())
        bar_colors = [colors_map.get(lab, "teal") for lab in labels]
        ax.bar(labels, values, color=bar_colors)
        ax.set_title(f"Anomaly Types ({param})", fontsize=9)
        ax.set_ylabel("Count", fontsize=8)
        ax.tick_params(labelsize=7)
        ax_idx += 1

    # --- 下圖: 趨勢圖 + 異常區段顏色標記 ---
    if has_raw:
        ax = axes[ax_idx]
        x = list(range(len(raw_values)))
        ax.plot(x, raw_values, color="steelblue", linewidth=0.6, alpha=0.8, label=param)

        # 解析 classifications 中的異常區段並用顏色標記
        if has_classifications:
            import re as _re

            labeled_types = set()  # 避免 legend 重複
            for seg in classifications:
                if not isinstance(seg, dict):
                    continue
                atype = seg.get("type", "UNKNOWN")
                range_str = seg.get("range", "")
                # 解析 "50-67" 格式
                match = _re.search(r"(\d+)-(\d+)", str(range_str))
                if match:
                    start = int(match.group(1))
                    end = int(match.group(2))
                    color = colors_map.get(atype, "#90A4AE")
                    label = atype if atype not in labeled_types else None
                    ax.axvspan(start, end, alpha=0.25, color=color, label=label)
                    labeled_types.add(atype)

            ax.legend(fontsize=6, loc="upper right", ncol=2)

        ax.set_title(f"Trend + Anomaly Regions ({param})", fontsize=9)
        ax.set_xlabel("Row Index", fontsize=8)
        ax.set_ylabel("Value", fontsize=8)
        ax.tick_params(labelsize=7)

    fig.tight_layout()
    return fig


def _chart_cross_correlation(result, plt, np):
    """交叉相關圖"""
    lag = result.get("best_lag", 0)
    peak_corr = result.get("peak_correlation", 0)
    lags_data = result.get("correlation_values", result.get("lags", []))

    if isinstance(lags_data, list) and len(lags_data) > 3:
        fig, ax = plt.subplots(figsize=(7, 3))
        ax.plot(lags_data, color="steelblue", linewidth=0.8)
        ax.axvline(
            x=lag,
            color="red",
            linestyle="--",
            linewidth=0.8,
            label=f"Best lag={lag}, r={peak_corr:.3f}",
        )
        ax.set_title("Cross Correlation", fontsize=9)
        ax.legend(fontsize=7)
        ax.tick_params(labelsize=7)
        return fig

    # Fallback: 純文字摘要
    if lag is not None and peak_corr:
        fig, ax = plt.subplots(figsize=(5, 2))
        direction = result.get("interpretation", {}).get("causality_direction", "?")
        ax.text(
            0.5,
            0.6,
            f"Lag = {lag}, r = {peak_corr:.3f}",
            ha="center",
            va="center",
            fontsize=12,
            fontweight="bold",
        )
        ax.text(
            0.5,
            0.3,
            f"Direction: {direction}",
            ha="center",
            va="center",
            fontsize=10,
            color="gray",
        )
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")
        return fig
    return None


def _chart_frequency(result, plt, np):
    """PSD 頻域分析圖 — 上圖: PSD 頻譜, 下圖: 趨勢圖+週期標記"""
    spectrum = result.get("full_spectrum", {})
    psd = spectrum.get("psd_values", result.get("psd", []))
    freqs = spectrum.get("frequencies", result.get("frequencies", []))
    raw_values = result.get("raw_values", [])
    period_rows = result.get("dominant_period_rows", [])
    param = result.get("parameter", "")
    dom_period = spectrum.get("dominant_period", None)
    dom_freq = spectrum.get("dominant_frequency", None)
    entropy = spectrum.get("spectral_entropy", None)

    has_psd = isinstance(psd, list) and isinstance(freqs, list) and len(psd) > 3
    has_raw = isinstance(raw_values, list) and len(raw_values) > 5

    if not has_psd and not has_raw:
        return None

    n_plots = (1 if has_psd else 0) + (1 if has_raw else 0)
    fig, axes = plt.subplots(n_plots, 1, figsize=(7, 3 * n_plots))
    if n_plots == 1:
        axes = [axes]

    ax_idx = 0

    # --- 上圖: PSD 頻譜 ---
    if has_psd:
        ax = axes[ax_idx]
        ax.semilogy(freqs[: len(psd)], psd, color="steelblue", linewidth=0.8)

        # 標記主頻位置
        if dom_freq and dom_freq > 0:
            # 找到頻譜中主頻對應的 PSD 值
            freqs_arr = np.array(freqs[: len(psd)])
            psd_arr = np.array(psd)
            closest_idx = np.argmin(np.abs(freqs_arr - dom_freq))
            ax.plot(
                freqs_arr[closest_idx],
                psd_arr[closest_idx],
                "rv",
                markersize=8,
                label=f"主頻 f={dom_freq:.4f}",
            )
            ax.axvline(
                x=dom_freq, color="red", linestyle="--", linewidth=0.6, alpha=0.5
            )

        # 左上角標注摘要
        info_lines = []
        if dom_period and dom_period != float("inf"):
            info_lines.append(f"主週期: 每 {dom_period:.1f} 筆")
        if entropy is not None:
            info_lines.append(f"頻譜熵: {entropy:.3f}")
        if info_lines:
            ax.text(
                0.02,
                0.95,
                "\n".join(info_lines),
                transform=ax.transAxes,
                fontsize=7,
                verticalalignment="top",
                bbox=dict(
                    boxstyle="round,pad=0.3",
                    facecolor="lightyellow",
                    edgecolor="gray",
                    alpha=0.8,
                ),
            )

        ax.set_title(f"Power Spectral Density ({param})", fontsize=9)
        ax.set_xlabel("Frequency", fontsize=8)
        ax.set_ylabel("PSD (log)", fontsize=8)
        ax.tick_params(labelsize=7)
        if dom_freq and dom_freq > 0:
            ax.legend(fontsize=7, loc="upper right")
        ax_idx += 1

    # --- 下圖: 趨勢圖 + 週期位置標記 ---
    if has_raw:
        ax = axes[ax_idx]
        x = list(range(len(raw_values)))
        ax.plot(x, raw_values, color="steelblue", linewidth=0.6, alpha=0.8)

        # 用紅色虛線標記每個週期的位置
        if period_rows and dom_period and dom_period != float("inf"):
            for i, row in enumerate(period_rows):
                if row < len(raw_values):
                    ax.axvline(
                        x=row, color="red", linestyle="--", linewidth=0.5, alpha=0.4
                    )
            # 在第一條線旁邊標注週期
            if len(period_rows) > 1 and period_rows[0] < len(raw_values):
                y_pos = max(raw_values) * 0.95
                ax.annotate(
                    f"T={dom_period:.1f}",
                    xy=(period_rows[0], y_pos),
                    fontsize=7,
                    color="red",
                )

        ax.set_title(f"Trend + Dominant Period Markers ({param})", fontsize=9)
        ax.set_xlabel("Row Index", fontsize=8)
        ax.set_ylabel("Value", fontsize=8)
        ax.tick_params(labelsize=7)

    fig.tight_layout()
    return fig


def _chart_temporal_patterns(result, plt, np):
    """時序模式 — 雙圖: 上圖 CUSUM 變化偵測, 下圖趨勢 + 滾動標準差"""
    raw = result.get("raw_values", [])
    cusum_pos = result.get("cusum_pos", [])
    cusum_neg = result.get("cusum_neg", [])
    rolling_std_vals = result.get("rolling_std", [])
    param = result.get("parameter", "")

    # 需要至少有 raw_values 和 cusum 資料
    if not (
        isinstance(raw, list)
        and len(raw) > 5
        and isinstance(cusum_pos, list)
        and len(cusum_pos) > 5
    ):
        # Fallback: 穩定性文字卡片
        roc = result.get("rate_of_change", {})
        stability = roc.get("stability_class", "") if isinstance(roc, dict) else ""
        if not stability:
            stability = result.get("stability_class", result.get("trend", ""))
        if stability:
            fig, ax = plt.subplots(figsize=(4, 2))
            color = (
                "red"
                if "DRIFT" in str(stability)
                else ("orange" if "UNSTABLE" in str(stability) else "green")
            )
            ax.text(
                0.5,
                0.5,
                f"Stability: {stability}",
                ha="center",
                va="center",
                fontsize=12,
                fontweight="bold",
                color=color,
            )
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
            ax.axis("off")
            return fig
        return None

    raw_arr = np.array(raw)
    n = len(raw_arr)
    x = np.arange(n)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 5), height_ratios=[1, 1.2])

    # ===== 上圖: CUSUM 正向/負向 + 變化點 =====
    cusum_p = np.array(cusum_pos[:n])
    cusum_n = np.array(cusum_neg[:n])
    ax1.plot(
        x[: len(cusum_p)],
        cusum_p,
        color="#E57373",
        linewidth=0.9,
        label="CUSUM+ (upward shift)",
    )
    ax1.plot(
        x[: len(cusum_n)],
        cusum_n,
        color="#64B5F6",
        linewidth=0.9,
        label="CUSUM- (downward shift)",
    )

    # 變化點標記
    change_points = result.get("cusum_change_points", [])
    if isinstance(change_points, list):
        for cp in change_points:
            cp_idx = cp.get("index", cp) if isinstance(cp, dict) else cp
            direction = cp.get("direction", "") if isinstance(cp, dict) else ""
            if isinstance(cp_idx, (int, float)) and 0 <= cp_idx < n:
                cp_color = "#D32F2F" if "UP" in str(direction) else "#1565C0"
                ax1.axvline(
                    x=cp_idx, color=cp_color, linestyle="--", linewidth=1.2, alpha=0.8
                )
                label_text = f"{'UP' if 'UP' in str(direction) else 'DN'}@{int(cp_idx)}"
                y_pos = max(cusum_p.max(), cusum_n.max()) * 0.85
                ax1.annotate(
                    label_text,
                    xy=(cp_idx, y_pos),
                    fontsize=6.5,
                    color=cp_color,
                    ha="center",
                    fontweight="bold",
                )

    # 穩定性標籤
    roc = result.get("rate_of_change", {})
    stability = roc.get("stability_class", "") if isinstance(roc, dict) else ""
    total_shifts = result.get("cusum_total_shifts", 0)
    title_suffix = ""
    if stability:
        title_suffix = f"  [{stability}]"
    if total_shifts > 0:
        title_suffix += f"  ({total_shifts} change points)"

    ax1.set_title(f"CUSUM Change Detection ({param}){title_suffix}", fontsize=9)
    ax1.set_ylabel("CUSUM Value", fontsize=8)
    ax1.tick_params(labelsize=7)
    ax1.legend(fontsize=6.5, loc="upper left")
    ax1.grid(True, alpha=0.3)

    # ===== 下圖: 趨勢線 + 線性回歸 + 滾動標準差帶 =====
    ax2.plot(x, raw_arr, color="steelblue", linewidth=0.8, alpha=0.9, label=param)

    # 線性回歸線
    slope = result.get("slope_per_unit", 0)
    intercept = result.get("slope_intercept", None)
    if intercept is not None and slope != 0:
        trend_line = slope * x + intercept
        ax2.plot(
            x,
            trend_line,
            color="#FF7043",
            linewidth=1.2,
            linestyle="--",
            alpha=0.7,
            label=f"Trend (slope={slope:.4f})",
        )

    # 滾動標準差 (灰色帶)
    if isinstance(rolling_std_vals, list) and len(rolling_std_vals) > 3:
        rs_arr = np.array(rolling_std_vals)
        rs_start = result.get("rolling_std_start_idx", n - len(rs_arr))
        rs_x = np.arange(rs_start, rs_start + len(rs_arr))
        # 用第二 Y 軸畫滾動標準差
        ax2b = ax2.twinx()
        ax2b.fill_between(
            rs_x, 0, rs_arr, color="gray", alpha=0.15, label="Rolling Std"
        )
        ax2b.plot(rs_x, rs_arr, color="gray", linewidth=0.6, alpha=0.5)
        ax2b.set_ylabel("Rolling Std", fontsize=7, color="gray")
        ax2b.tick_params(labelsize=6, colors="gray")

    # 變化點紅線也在趨勢圖上標
    if isinstance(change_points, list):
        for cp in change_points:
            cp_idx = cp.get("index", cp) if isinstance(cp, dict) else cp
            if isinstance(cp_idx, (int, float)) and 0 <= cp_idx < n:
                ax2.axvline(
                    x=cp_idx, color="red", linestyle=":", linewidth=0.8, alpha=0.5
                )

    trend_text = result.get("trend", "")
    change_pct = result.get("total_change_pct", "")
    ax2.set_title(
        f"Trend + Volatility ({param})  [{trend_text} {change_pct}]", fontsize=9
    )
    ax2.set_xlabel("Row Index", fontsize=8)
    ax2.set_ylabel("Value", fontsize=8)
    ax2.tick_params(labelsize=7)
    ax2.legend(fontsize=6.5, loc="upper left")
    ax2.grid(True, alpha=0.3)

    fig.tight_layout()
    return fig


def _chart_control_loop(result, plt, np):
    """控制迴路評估 — Harris Index 儀表板"""
    harris = result.get("harris_index", {})
    if isinstance(harris, dict) and harris:
        idx = harris.get("index", 0)
        grade = harris.get("grade", "?")
        fig, ax = plt.subplots(figsize=(4, 2.5))
        color = "green" if idx > 0.7 else ("orange" if idx > 0.3 else "red")
        ax.barh(["Harris Index"], [idx], color=color)
        ax.set_xlim(0, 1)
        ax.axvline(x=0.3, color="red", linestyle="--", linewidth=0.5)
        ax.axvline(x=0.7, color="green", linestyle="--", linewidth=0.5)
        ax.set_title(f"Control Loop: {grade} ({idx:.2f})", fontsize=9)
        ax.tick_params(labelsize=7)
        return fig
    return None


def _chart_cv_ranking(result, plt, np):
    """CV 排名柱狀圖"""
    ranking = result.get("cv_ranking", result.get("ranking", []))
    if isinstance(ranking, list) and ranking:
        names = [
            r.get("parameter", "?")[-20:] for r in ranking[:15] if isinstance(r, dict)
        ]
        cvs = [r.get("cv", 0) for r in ranking[:15] if isinstance(r, dict)]
        if names:
            fig, ax = plt.subplots(figsize=(7, 4))
            ax.barh(names, cvs, color="teal")
            ax.set_title("CV Ranking (Coefficient of Variation)", fontsize=9)
            ax.tick_params(labelsize=7)
            fig.tight_layout()
            return fig
    return None


def _chart_distribution_shift(result, plt, np):
    """分佈漂移分析"""
    wd = result.get("wasserstein_distance", result.get("shift_magnitude", 0))
    p_val = result.get("ks_p_value", result.get("p_value", 1))
    fig, ax = plt.subplots(figsize=(5, 2.5))
    status = "Shift Detected" if p_val < 0.05 else "No Significant Shift"
    color = "red" if p_val < 0.05 else "green"
    ax.text(
        0.5,
        0.65,
        status,
        ha="center",
        va="center",
        fontsize=13,
        fontweight="bold",
        color=color,
    )
    ax.text(
        0.5,
        0.35,
        f"WD={wd:.4f}, KS p={p_val:.4f}",
        ha="center",
        va="center",
        fontsize=10,
        color="gray",
    )
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    return fig


def _chart_performance_seg(result, plt, np):
    """好壞批次柱狀比較"""
    good = result.get("good_batch_stats", result.get("top_quartile", {}))
    bad = result.get("bad_batch_stats", result.get("bottom_quartile", {}))
    diff = result.get("significant_differences", result.get("top_differences", []))

    if isinstance(diff, list) and diff:
        names = [
            d.get("parameter", "?")[-20:] for d in diff[:10] if isinstance(d, dict)
        ]
        effects = [
            d.get("effect_size", d.get("diff", 0))
            for d in diff[:10]
            if isinstance(d, dict)
        ]
        if names:
            fig, ax = plt.subplots(figsize=(7, 3))
            colors = ["coral" if e > 0 else "steelblue" for e in effects]
            ax.barh(names, effects, color=colors)
            ax.set_title("Top/Bottom Quartile Differences", fontsize=9)
            ax.axvline(x=0, color="gray", linewidth=0.5)
            ax.tick_params(labelsize=7)
            fig.tight_layout()
            return fig
    return None


def _chart_stats_summary(stats, result, plt):
    """通用 stats 摘要圖"""
    fig, ax = plt.subplots(figsize=(5, 2))
    text_lines = []
    for k in ["mean", "std", "min", "max", "max_z", "max_sigma"]:
        if k in stats:
            text_lines.append(
                f"{k}: {stats[k]:.4f}"
                if isinstance(stats[k], float)
                else f"{k}: {stats[k]}"
            )
    if text_lines:
        ax.text(
            0.1,
            0.5,
            "\n".join(text_lines),
            ha="left",
            va="center",
            fontsize=9,
            family="monospace",
        )
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")
        ax.set_title("Statistics Summary", fontsize=9)
        return fig
    plt.close(fig)
    return None


def _chart_generic(tool_name, result, plt, np):
    """
    通用 Fallback：嘗試從結果中找到可繪圖的數據。
    優先: list of numbers -> line chart
    其次: dict of numbers -> bar chart
    排除: metadata key (basic_stats, global_stats, status 等)
    """
    # 排除無分析意義的 metadata key
    _SKIP_KEYS = {
        "basic_stats",
        "global_stats",
        "stats",
        "status",
        "parameter",
        "parameters",
        "target",
        "targets",
        "message",
        "error",
        "summary",
        "engineering_hints",
        "interpretation",
        "engineering_summary",
        "metadata",
        "time_column",
        "range",
        "focus_range",
        "data_range",
    }

    # 1. 找 list of numbers
    for key, val in result.items():
        if key in _SKIP_KEYS:
            continue
        if isinstance(val, list) and len(val) > 10:
            if all(isinstance(v, (int, float)) for v in val[:20]):
                fig, ax = plt.subplots(figsize=(7, 3))
                ax.plot(val, color="steelblue", linewidth=0.8)
                ax.set_title(f"{tool_name}: {key}", fontsize=9)
                ax.tick_params(labelsize=7)
                return fig

    # 2. 找 dict of numbers (e.g. parameter -> score)
    for key, val in result.items():
        if key in _SKIP_KEYS:
            continue
        if isinstance(val, dict) and len(val) >= 3:
            numeric_items = {
                k: v for k, v in val.items() if isinstance(v, (int, float))
            }
            if len(numeric_items) >= 3:
                names = list(numeric_items.keys())[:15]
                values = [numeric_items[n] for n in names]
                fig, ax = plt.subplots(figsize=(7, 3))
                ax.barh([n[-20:] for n in names], values, color="teal")
                ax.set_title(f"{tool_name}: {key}", fontsize=9)
                ax.tick_params(labelsize=7)
                fig.tight_layout()
                return fig

    return None
