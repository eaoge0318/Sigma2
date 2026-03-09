"""
Chart Extractors Registry
============================================================
從 OrchestratedAnalysisAgentV3._extract_chart_data 提取出來。
每個工具有一個獨立的 extractor 函式，統一由 extract_chart_data() dispatch。
"""


def _bar(title, labels, values, label="值", color="rgba(59,130,246,0.6)"):
    """Bar chart 快捷建構器"""
    return {
        "type": "chart",
        "chart_type": "bar",
        "title": title,
        "data": {
            "labels": labels,
            "datasets": [{"label": label, "data": values, "backgroundColor": color}],
        },
    }


# ── 各工具 extractor ──────────────────────────────────────


def _trend(result, param_name):
    data = result.get("data", {})
    key = param_name
    if not key or key not in data:
        for k, v in data.items():
            if isinstance(v, list) and len(v) > 0:
                key = k
                break
    if key and key in data:
        vals = data[key]
        if isinstance(vals, list) and vals:
            step = max(1, len(vals) // 200)
            return {
                "type": "chart",
                "chart_type": "line",
                "title": f"{key} 趨勢",
                "data": {
                    "labels": list(range(0, len(vals), step)),
                    "datasets": [
                        {
                            "label": key,
                            "data": vals[::step],
                            "borderWidth": 1,
                            "pointRadius": 0,
                        }
                    ],
                },
            }
    return None


def _top_correlations(result, param_name):
    corrs = result.get("top_correlations", [])[:10]
    if not corrs:
        return None
    labels = [c.get("parameter", "?")[:15] for c in corrs if isinstance(c, dict)]
    values = [
        round(abs(c.get("correlation", 0)), 3) for c in corrs if isinstance(c, dict)
    ]
    return (
        _bar(f"{param_name or 'Target'} 相關因子", labels, values, "|r|")
        if labels
        else None
    )


def _scan_anomaly_segments(result, param_name):
    worst = result.get("worst_parameters", [])[:10]
    if not worst:
        return None
    labels = [w.get("parameter", "?")[:15] for w in worst if isinstance(w, dict)]
    values = [w.get("segment_count", 0) for w in worst if isinstance(w, dict)]
    return (
        _bar("異常區段 Top 參數", labels, values, "異常區段數", "rgba(239,68,68,0.6)")
        if labels
        else None
    )


def _cv_ranking(result, param_name):
    rankings = result.get("rankings", result.get("cv_rankings", []))[:10]
    if not rankings:
        return None
    labels = [
        r.get("parameter", r.get("column", "?"))[:15]
        for r in rankings
        if isinstance(r, dict)
    ]
    values = [
        round(r.get("cv", r.get("coefficient_of_variation", 0)), 4)
        for r in rankings
        if isinstance(r, dict)
    ]
    return (
        _bar("CV 變異排名", labels, values, "CV", "rgba(245,158,11,0.6)")
        if labels
        else None
    )


def _detect_outliers(result, param_name):
    # 多參數格式
    results_map = result.get("results", {})
    if isinstance(results_map, dict) and results_map:
        labels, values = [], []
        for p, d in list(results_map.items())[:10]:
            if isinstance(d, dict):
                labels.append(p[:15])
                values.append(d.get("outlier_count", 0))
        if labels and any(v > 0 for v in values):
            return _bar("離群值數量", labels, values, "離群值", "rgba(220,38,38,0.6)")
    # 單參數格式
    if result.get("outlier_count", 0) > 0:
        oc = result["outlier_count"]
        total = result.get("total_points", 100)
        return {
            "type": "chart",
            "chart_type": "doughnut",
            "title": f"{param_name or 'Target'} 離群值",
            "data": {
                "labels": ["離群值", "正常值"],
                "datasets": [
                    {
                        "data": [oc, total - oc],
                        "backgroundColor": [
                            "rgba(239,68,68,0.7)",
                            "rgba(34,197,94,0.5)",
                        ],
                    }
                ],
            },
        }
    return None


def _basic_stats(result, param_name):
    stats = result.get("statistics", result.get("results", {}))
    if not isinstance(stats, dict) or not stats:
        return None
    labels, means, stds = [], [], []
    for p, d in list(stats.items())[:10]:
        if isinstance(d, dict) and d.get("mean") is not None:
            labels.append(p[:15])
            means.append(round(d["mean"], 3))
            stds.append(round(d.get("std", 0), 3))
    if not labels:
        return None
    return {
        "type": "chart",
        "chart_type": "bar",
        "title": "基礎統計摘要 (Mean +/- Std)",
        "data": {
            "labels": labels,
            "datasets": [
                {
                    "label": "Mean",
                    "data": means,
                    "backgroundColor": "rgba(59,130,246,0.6)",
                },
                {
                    "label": "Std",
                    "data": stds,
                    "backgroundColor": "rgba(245,158,11,0.4)",
                },
            ],
        },
    }


def _analyze_distribution(result, param_name):
    hist = result.get("histogram")
    if isinstance(hist, dict) and "counts" in hist:
        return _bar(
            f"{param_name or 'Distribution'} 直方圖",
            hist.get("bin_edges", []),
            hist["counts"],
            "頻次",
            "rgba(99,102,241,0.6)",
        )
    return None


def _correlation_network(result, param_name):
    edges = result.get("edges", result.get("links", []))[:10]
    if not edges:
        return None
    labels, values = [], []
    for e in edges:
        if isinstance(e, dict):
            src = e.get("source", e.get("from", "?"))[:8]
            tgt = e.get("target", e.get("to", "?"))[:8]
            labels.append(f"{src}-{tgt}")
            values.append(round(abs(e.get("weight", e.get("correlation", 0))), 3))
    return (
        _bar("Top 相關性連結", labels, values, "|r|", "rgba(16,185,129,0.6)")
        if labels
        else None
    )


def _feature_importance(result, param_name):
    rankings = result.get("importance_ranking", result.get("feature_importance", []))[
        :10
    ]
    if not rankings:
        return None
    labels = [
        r.get("feature", r.get("parameter", "?"))[:15]
        for r in rankings
        if isinstance(r, dict)
    ]
    values = [
        round(r.get("importance", r.get("score", 0)), 4)
        for r in rankings
        if isinstance(r, dict)
    ]
    return (
        _bar("特徵重要性排名", labels, values, "重要性", "rgba(139,92,246,0.6)")
        if labels
        else None
    )


def _combo_profiling(result, param_name):
    auto_targets = result.get("auto_targets", [])
    if auto_targets and isinstance(auto_targets, list):
        details = result.get("profiling_details", {})
        labels = auto_targets[:10]
        values = [
            details.get(t, {}).get("severity", 1.0)
            if isinstance(details.get(t), dict)
            else 1.0
            for t in labels
        ]
        return _bar(
            f"AutoTarget ({len(auto_targets)} 個異常參數)",
            [lbl[:15] for lbl in labels],
            values,
            "嚴重度",
            "rgba(168,85,247,0.6)",
        )
    # Fallback: sub_analyses outlier count
    sub = result.get("sub_analyses", {})
    if sub:
        labels, counts = [], []
        for p, d in list(sub.items())[:10]:
            if isinstance(d, dict) and "outliers" in d:
                od = d["outliers"]
                if isinstance(od, dict) and od.get("outlier_count", 0) > 0:
                    labels.append(p[:15])
                    counts.append(od["outlier_count"])
        if labels:
            return _bar(
                "參數掃描 - 離群值分佈",
                labels,
                counts,
                "離群值數",
                "rgba(239,68,68,0.6)",
            )
    return None


# ── Fallback extractors ──────────────────────────────────


def _fallback_anomaly_params(result, param_name):
    anom = result.get("anomaly_parameters", [])
    if not isinstance(anom, list) or len(anom) < 2:
        return None
    labels, scores = [], []
    for a in anom[:10]:
        if isinstance(a, dict):
            labels.append(a.get("parameter", "?")[:15])
            scores.append(a.get("score", a.get("z_score", 1.0)))
        elif isinstance(a, str):
            labels.append(a[:15])
            scores.append(1.0)
    return (
        _bar("異常參數排名", labels, scores, "異常分數", "rgba(239,68,68,0.5)")
        if labels
        else None
    )


def _fallback_worst_params(result, param_name):
    worst = result.get("worst_parameters", [])
    if not isinstance(worst, list) or len(worst) < 2:
        return None
    labels = [w.get("parameter", "?")[:15] for w in worst[:10] if isinstance(w, dict)]
    values = [
        w.get("score", w.get("segment_count", 1.0))
        for w in worst[:10]
        if isinstance(w, dict)
    ]
    return (
        _bar("最差參數排名", labels, values, "分數", "rgba(251,146,60,0.6)")
        if labels
        else None
    )


# ── Registry ─────────────────────────────────────────────

TOOL_EXTRACTORS: dict[str, callable] = {
    "draw_trend": _trend,
    "get_time_series_data": _trend,
    "get_top_correlations": _top_correlations,
    "scan_anomaly_segments": _scan_anomaly_segments,
    "cv_ranking": _cv_ranking,
    "detect_outliers": _detect_outliers,
    "basic_stats": _basic_stats,
    "analyze_distribution": _analyze_distribution,
    "correlation_network": _correlation_network,
    "analyze_feature_importance": _feature_importance,
    "combo_parameter_profiling": _combo_profiling,
}

FALLBACK_EXTRACTORS = [_fallback_anomaly_params, _fallback_worst_params]


def extract_chart_data(
    result: dict, tool_name: str, param_name: str = None
) -> dict | None:
    """
    從工具結果中提取 Chart.js JSON。
    先查 registry，再跑 fallback chain。
    """
    if not isinstance(result, dict) or result.get("error"):
        return None
    extractor = TOOL_EXTRACTORS.get(tool_name)
    if extractor:
        chart = extractor(result, param_name)
        if chart:
            return chart
    for fb in FALLBACK_EXTRACTORS:
        chart = fb(result, param_name)
        if chart:
            return chart
    return None
