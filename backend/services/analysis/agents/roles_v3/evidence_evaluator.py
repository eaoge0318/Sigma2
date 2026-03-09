"""
Evidence Evaluator — 純 Python 閾值評估器
============================================================
位於 CodeInterpreter → Humanizer 之間，
用硬編碼的統計閾值判定每個 finding 的嚴重性等級。

LLM 不做統計判斷，Evaluator 做完判斷後，
Humanizer 只負責「翻譯成人話」。
"""

import logging
import re
from dataclasses import dataclass, field
from typing import List, Dict

logger = logging.getLogger(__name__)


# ============================================================
# 閾值常數 (可根據產線經驗調整)
# ============================================================


class Thresholds:
    """統計閾值常數"""

    T2_DROP_HIGH = 5.0  # T²_drop > 5 → 重要欄位
    T2_DROP_LOW = 1.0  # T²_drop < 1 → 不重要
    CORR_HIGH = 0.6  # |r| > 0.6 → 強相關
    CORR_MED = 0.4  # |r| 0.4-0.6 → 中相關
    CORR_WEAK = 0.2  # |r| 0.2-0.4 → 弱相關
    Z_SIGNIFICANT = 3.0  # |z| > 3 → 顯著偏移
    Z_WARNING = 2.0  # |z| 2-3 → 輕微偏移
    Z_NORMAL = 1.5  # |z| < 1.5 → 正常
    P_SIGNIFICANT = 0.01  # p < 0.01 → 顯著
    P_MARGINAL = 0.05  # 0.01 < p < 0.05 → 邊緣
    MIN_ANOMALY_SAMPLES = 5
    MIN_ANOMALY_RATIO = 0.02


# ============================================================
# 資料結構
# ============================================================


@dataclass
class EvaluatedMetric:
    """單一指標的評估結果"""

    name: str  # e.g. "T²_drop", "correlation", "z-score"
    value: float
    grade: str  # "high" / "medium" / "low" / "noise"
    note: str = ""


@dataclass
class EvaluatedFinding:
    """評估後的分析發現"""

    title: str
    severity: str  # "high" / "medium" / "low" / "noise"
    evidence_grade: str  # "A" / "B" / "C" / "D"
    verdict: str  # 一句話結論
    metrics: List[EvaluatedMetric] = field(default_factory=list)
    raw_text: str = ""
    matched_chart_indices: List[int] = field(default_factory=list)  # 對應的圖表索引


# ============================================================
# Evidence Evaluator
# ============================================================


class EvidenceEvaluator:
    """
    從 Code Interpreter stdout 提取數字，
    用硬閾值判定每個 finding 的嚴重性。
    """

    def __init__(self, thresholds: Thresholds = None):
        self.th = thresholds or Thresholds()

    # ── Chart-to-Finding Mapping ──────────────────────────────

    _PARAM_RE_EN = re.compile(r"[A-Z][A-Z0-9]*[-_][A-Z0-9_]+", re.I)
    _PARAM_RE_ZH = re.compile(r"[\u4e00-\u9fff]{2,}")  # ≥2 個連續中文字

    @staticmethod
    def _extract_params(text: str) -> set:
        """從文字中提取參數名 (英文: SECTION-DCS_A01 / 中文: 對應中文名)"""
        params = set(EvidenceEvaluator._PARAM_RE_EN.findall(text.upper()))
        params.update(EvidenceEvaluator._PARAM_RE_ZH.findall(text))
        return params

    @staticmethod
    def match_charts_to_findings(
        evaluated: List[EvaluatedFinding],
        chart_titles: List[str],
    ) -> Dict[int, int]:
        """
        建立 chart_index → finding_index 的 mapping。
        找不到對應的 chart 設為 -1 (全域/補充圖表)。

        嚴格匹配: 至少要有 1 個具體參數名（>= 8 字元）完全吻合，
        否則不配對（寧可不配也不要配錯）。

        Returns:
            {chart_idx: finding_idx} (finding_idx=-1 表示全域圖)
        """
        import re as _re

        mapping: Dict[int, int] = {}

        # 預提取每個 finding 的參數集 + 區間號
        _iv_re = _re.compile(r"#(\d+-\d+)")
        finding_params = [
            EvidenceEvaluator._extract_params(ef.raw_text + " " + ef.title)
            for ef in evaluated
        ]
        finding_intervals = [
            set(_iv_re.findall(ef.title + " " + ef.raw_text)) for ef in evaluated
        ]

        # 過濾函數: 只保留 >= 8 字元的參數名（排除太短/太 generic 的 token）
        def _meaningful(params: set) -> set:
            return {p for p in params if len(p) >= 8}

        for ci, title in enumerate(chart_titles):
            chart_params = EvidenceEvaluator._extract_params(title)
            chart_intervals = set(_iv_re.findall(title))
            chart_meaningful = _meaningful(chart_params)

            if not chart_params and not chart_intervals:
                mapping[ci] = -1
                continue

            # 參數太多 (5+) 且沒有區間號 → 全域概覽圖
            if len(chart_params) >= 5 and not chart_intervals:
                mapping[ci] = -1
                continue

            best_fi, best_score = -1, 0
            for fi, fp in enumerate(finding_params):
                fp_meaningful = _meaningful(fp)

                # 區間號匹配: chart 有區間號時必須跟 finding 一致
                if chart_intervals:
                    iv_overlap = len(chart_intervals & finding_intervals[fi])
                    if iv_overlap == 0:
                        continue  # 區間號不一致，跳過
                    # 嚴格: 即使區間號匹配，也要有參數名重疊
                    param_overlap = len(chart_meaningful & fp_meaningful)
                    score = iv_overlap * 100 + param_overlap
                else:
                    # 無區間號: 必須有至少 1 個具體參數名完全吻合
                    param_overlap = len(chart_meaningful & fp_meaningful)
                    if param_overlap == 0:
                        continue  # 沒有具體參數名吻合 → 跳過
                    score = param_overlap

                if score > best_score:
                    best_score = score
                    best_fi = fi

            mapping[ci] = best_fi
            if best_fi >= 0:
                evaluated[best_fi].matched_chart_indices.append(ci)

        logger.info(
            f"[EvidenceEvaluator] Chart mapping: {len(chart_titles)} charts → "
            f"{sum(1 for v in mapping.values() if v >= 0)} matched, "
            f"{sum(1 for v in mapping.values() if v < 0)} global"
        )
        return mapping

    def evaluate(
        self,
        all_findings: List[str],
        stdout_rounds: List[str],
        data_summary: str = "",
        prep: Dict = None,
        task_type: str = "",
    ) -> List[EvaluatedFinding]:
        """
        主入口: 評估所有 findings。

        當 task_type 是 anomaly_detection/global_analysis 且 prep 有結構化數據時,
        優先從 prep 自動生成 findings（不依賴 LLM stdout）。
        其他情況（optimization 等）走舊邏輯。
        """
        # ── 結構化 findings 路徑（anomaly detection）──
        if (
            task_type in ("anomaly_detection", "global_analysis", "exploratory")
            and prep
            and isinstance(prep, dict)
            and (prep.get("t2_contrib") or prep.get("target_analysis"))
        ):
            evaluated = self.build_structured_findings(prep)
            if evaluated:
                logger.info(
                    f"[EvidenceEvaluator] Structured mode: {len(evaluated)} findings "
                    f"from prep data "
                    f"(H={sum(1 for e in evaluated if e.severity == 'high')}, "
                    f"M={sum(1 for e in evaluated if e.severity == 'medium')}, "
                    f"L={sum(1 for e in evaluated if e.severity == 'low')})"
                )
                return evaluated

        # ── 舊邏輯路徑（optimization 等）──
        full_stdout = "\n".join(stdout_rounds)
        global_metrics = self._extract_global_metrics(full_stdout, data_summary)

        evaluated = []
        for finding_text in all_findings:
            if finding_text.startswith("[Round") and "ERROR" in finding_text:
                continue
            ef = self._evaluate_single(finding_text, full_stdout, global_metrics)
            evaluated.append(ef)

        # 排序 high → low
        order = {"high": 0, "medium": 1, "low": 2, "noise": 3}
        evaluated.sort(key=lambda x: order.get(x.severity, 4))

        # 過濾 noise
        evaluated = [e for e in evaluated if e.severity != "noise"]

        logger.info(
            f"[EvidenceEvaluator] {len(all_findings)} findings → "
            f"{len(evaluated)} valid "
            f"(H={sum(1 for e in evaluated if e.severity == 'high')}, "
            f"M={sum(1 for e in evaluated if e.severity == 'medium')}, "
            f"L={sum(1 for e in evaluated if e.severity == 'low')})"
        )
        return evaluated

    # ============================================================
    # 結構化 Findings（從 preprocess 數據自動生成）
    # ============================================================

    def build_structured_findings(self, prep: Dict) -> List[EvaluatedFinding]:
        """
        從 preprocess 結構化數據自動生成 findings（不依賴 LLM stdout）。
        每個 anomaly interval 一個 finding，數據 100% 來自計算結果。
        """
        t2c = prep.get("t2_contrib", {})
        intervals = prep.get("anomaly_intervals", [])
        marginal_by_iv = t2c.get("marginal_scores_by_interval", {})
        contrib_by_iv = t2c.get("contribution_scores_by_interval", {})
        marginal_global = t2c.get("marginal_scores_global", [])

        if not intervals:
            return []

        findings = []

        # ── 按 interval 生成 findings ──
        # 先按主導欄位分組（相同主導欄位的 intervals 合併）
        dominant_groups: Dict[str, list] = {}  # dominant_col → [(iv, scores)]
        for iv in intervals:
            m_scores = marginal_by_iv.get(iv, [])
            c_scores = contrib_by_iv.get(iv, [])
            # 優先用 marginal drop（更精準），fallback 用 T² contribution
            scores = m_scores if m_scores else c_scores
            if not scores:
                continue
            dominant_col = scores[0][0] if scores else "unknown"
            if dominant_col not in dominant_groups:
                dominant_groups[dominant_col] = []
            dominant_groups[dominant_col].append((iv, scores))

        for dominant_col, iv_list in dominant_groups.items():
            # 合併所有相同主導欄位的 intervals
            all_ivs = [iv for iv, _ in iv_list]
            # 取最高 T² drop（所有 intervals 中最大的）
            best_scores = max(iv_list, key=lambda x: x[1][0][1] if x[1] else 0)[1]
            top_drop = best_scores[0][1] if best_scores else 0

            # 判定 severity
            if top_drop >= self.th.T2_DROP_HIGH:
                severity = "high"
                evidence_grade = "A"
            elif top_drop >= self.th.T2_DROP_LOW:
                severity = "medium"
                evidence_grade = "B"
            else:
                severity = "low"
                evidence_grade = "C"

            # 組裝 title 和 detail
            iv_str = ", ".join(f"#{iv}" for iv in all_ivs)
            title = f"區間 {iv_str} 主導異常: {dominant_col}"

            # evidence metrics
            metrics = []
            for col, drop in best_scores[:5]:
                grade = (
                    "high"
                    if drop >= self.th.T2_DROP_HIGH
                    else ("medium" if drop >= self.th.T2_DROP_LOW else "low")
                )
                metrics.append(
                    EvaluatedMetric(
                        name="T²_drop",
                        value=drop,
                        grade=grade,
                        note=col,
                    )
                )

            # verdict
            secondary = [f"{col}(T²_drop={drop:.2f})" for col, drop in best_scores[1:3]]
            secondary_str = f"，次要: {', '.join(secondary)}" if secondary else ""
            verdict = f"主導欄位 {dominant_col} T²_drop={top_drop:.2f}{secondary_str}"

            # raw_text（結構化，不是 LLM 生成的）
            raw_lines = [f"--- 區間 {iv_str} ---"]
            raw_lines.append("Marginal Drop (主導):")
            for col, drop in best_scores[:3]:
                raw_lines.append(f"  {col}: T²_drop={drop:.4f}")
            # 加上 T² contribution 對照
            for iv, _ in iv_list:
                c_scores = contrib_by_iv.get(iv, [])
                if c_scores:
                    raw_lines.append(f"T² 貢獻 (輔助, 區間 #{iv}):")
                    for col, score in c_scores[:3]:
                        raw_lines.append(f"  {col}: T²_contrib={score:.4f}")

            # 加上 deep analysis 數據
            deep = prep.get("deep_analysis", {})
            for iv, _ in iv_list:
                da = deep.get(iv, {})
                if da.get("group_diff"):
                    raw_lines.append(f"\n分組對比 (異常 #{iv} vs Baseline):")
                    for gd_col, ma, mb, d, t, p in da["group_diff"][:3]:
                        sig = "*" if p < 0.05 else ""
                        raw_lines.append(
                            f"  {gd_col}: 異常={ma:.2f}, 基線={mb:.2f}, Δ={d:.2f}, p={p:.4f}{sig}"
                        )
                if da.get("correlations"):
                    raw_lines.append(
                        f"\n主導欄位 {da.get('dominant_col', '?')} 相關性:"
                    )
                    for ca, cb, r in da["correlations"][:3]:
                        raw_lines.append(f"  {ca} vs {cb}: r={r:.3f}")
                if da.get("drift_overlap"):
                    raw_lines.append("\n漂移-異常重疊:")
                    for note in da["drift_overlap"]:
                        raw_lines.append(f"  ⚠ {note}")

            findings.append(
                EvaluatedFinding(
                    title=title,
                    severity=severity,
                    evidence_grade=evidence_grade,
                    verdict=verdict,
                    metrics=metrics,
                    raw_text="\n".join(raw_lines),
                )
            )

        # ── 漂移趨勢 finding（從 drift_scan 自動生成）──
        drift_scan = prep.get("drift_scan", {})
        trend_sig = drift_scan.get("trend_significant", [])
        if trend_sig:
            top_drift = trend_sig[:5]
            drift_lines = []
            drift_metrics = []
            for t in top_drift:
                col, rho, p = t["col"], t["rho"], t["p"]
                direction = "↑" if rho > 0 else "↓"
                drift_lines.append(f"  {col}: ρ={rho:.3f} {direction} (p={p:.4f})")
                drift_metrics.append(
                    EvaluatedMetric(
                        name="drift_rho",
                        value=abs(rho),
                        grade="high" if abs(rho) > 0.6 else "medium",
                        note=f"{col} {direction}",
                    )
                )
            max_rho = max(abs(t["rho"]) for t in top_drift)
            drift_severity = "high" if max_rho > 0.6 else "medium"
            drift_grade = "A" if max_rho > 0.6 else "B"
            findings.append(
                EvaluatedFinding(
                    title=f"顯著漂移趨勢 ({len(trend_sig)} 個欄位)",
                    severity=drift_severity,
                    evidence_grade=drift_grade,
                    verdict=f"Top 漂移: {top_drift[0]['col']} (ρ={top_drift[0]['rho']:.3f})",
                    metrics=drift_metrics,
                    raw_text="顯著漂移欄位 (Spearman ρ):\n" + "\n".join(drift_lines),
                )
            )

        # ── 滑動窗口異常區段 (anomaly_scan) ──
        ta = prep.get("target_analysis", {})
        _scan = ta.get("anomaly_scan", {}) if ta else {}
        if _scan:
            for y_col, sinfo in _scan.items():
                segs = sinfo.get("segments", [])
                if not segs:
                    continue
                _type_zh = {
                    "DRIFT": "漂移",
                    "SPIKE": "突波",
                    "OSCILLATION": "震盪",
                    "LEVEL_SHIFT": "水平跳變",
                    "SHIFTED_STABLE": "偏移穩態",
                    "DIP_RECOVERY": "急跌恢復",
                    "REGIME_CHANGE": "狀態切換",
                    "MIXED": "混合",
                }
                for seg in segs:
                    s_type = seg.get("type", "UNKNOWN")
                    s_sev = seg.get("severity_score", 3.0)
                    s_start = seg.get("start", 0)
                    s_end = seg.get("end", 0)
                    s_desc = seg.get("description", "")
                    s_conf = seg.get("confidence", 0.5)
                    s_factors = seg.get("top_factors", [])
                    s_group = seg.get("group_validation", [])
                    s_t2val = seg.get("t2_validation", [])

                    # 嚴重度: severity_score >= 5 → high, >= 3 → medium
                    if s_sev >= 5:
                        sev = "high"
                        grade = "A"
                    elif s_sev >= 3:
                        sev = "medium"
                        grade = "B"
                    else:
                        sev = "low"
                        grade = "C"

                    type_cn = _type_zh.get(s_type, s_type)

                    # 組裝 verdict（含 top factors）
                    verdict_parts = [
                        f"{type_cn}: {s_desc} (severity={s_sev:.1f}, confidence={s_conf:.2f})"
                    ]
                    if s_factors:
                        _top3 = ", ".join(
                            f"{f['col']}({f.get('score', f.get('z_diff', 0)):.2f})"
                            for f in s_factors[:3]
                        )
                        verdict_parts.append(f"主導因子: {_top3}")

                    # 組裝 raw_text（含完整因子資訊）
                    raw_lines = [
                        f"滑動窗口掃描: {y_col} #{s_start}-{s_end}",
                        f"  類型: {type_cn} ({s_type})",
                        f"  嚴重度: {s_sev:.1f}",
                        f"  描述: {s_desc}",
                    ]
                    if s_factors:
                        _method = s_factors[0].get("method", "unknown")
                        raw_lines.append(f"  主導因子 ({_method}):")
                        for f in s_factors[:5]:
                            _score_key = "score" if "score" in f else "z_diff"
                            raw_lines.append(
                                f"    {f['col']}: {_score_key}={f.get(_score_key, 0):.4f}"
                            )
                    if s_group:
                        raw_lines.append("  分組對比驗證 (異常 vs 基線):")
                        for g in s_group[:3]:
                            raw_lines.append(
                                f"    {g['col']}: z_diff={g['z_diff']:.2f}, "
                                f"異常={g['anom_mean']:.4f}, 基線={g['base_mean']:.4f}"
                            )
                    if s_t2val:
                        raw_lines.append("  T² 貢獻驗證:")
                        for t in s_t2val[:3]:
                            raw_lines.append(f"    {t['col']}: score={t['score']:.4f}")

                    # metrics
                    metrics = [
                        EvaluatedMetric(
                            name="scan_severity",
                            value=s_sev,
                            grade=sev,
                            note=f"{y_col} #{s_start}-{s_end} {s_type}",
                        )
                    ]
                    # 加入 top factor metrics
                    for f in s_factors[:3]:
                        _score = f.get("score", f.get("z_diff", 0))
                        _fg = (
                            "high" if _score > 5 else "medium" if _score > 1 else "low"
                        )
                        metrics.append(
                            EvaluatedMetric(
                                name="top_factor",
                                value=float(_score),
                                grade=_fg,
                                note=f"{f['col']} ({f.get('method', 'unknown')})",
                            )
                        )

                    findings.append(
                        EvaluatedFinding(
                            title=f"[{y_col}] #{s_start}-{s_end} {type_cn} (scan)",
                            severity=sev,
                            evidence_grade=grade,
                            verdict=" | ".join(verdict_parts),
                            metrics=metrics,
                            raw_text="\n".join(raw_lines),
                        )
                    )

        # ── 目標參數綜合摘要 (Scene B/D) ─────────────────
        # 每個目標參數產出 1 個 EvaluatedFinding，包含 RF/相關性/交叉延遲/drift/zscore
        ta = prep.get("target_analysis", {})
        _tp_list = ta.get("target_params", [])
        if _tp_list and isinstance(_tp_list, list):
            # 統一 RF importance 格式: Scene B = {y: [(param, imp), ...]}, D = {y: [{param, importance}, ...]}
            _fi_b = ta.get("feature_importance", {})
            _fi_d = ta.get("rf_importance", {})
            # 統一 correlations: Scene B = correlation_with_x {y: [(param, r), ...]}, D = top_correlations
            _corr_b = ta.get("correlation_with_x", {})
            _corr_d = ta.get("top_correlations", {})
            # 通用
            _zscore = ta.get("zscore", {})
            _drift = ta.get("drift", {})
            _scan = ta.get("anomaly_scan", {})
            _lag = ta.get("cross_correlation_lag", {})

            for y_col in _tp_list:
                raw_lines = [f"=== 目標參數摘要: {y_col} ==="]
                param_metrics = []
                has_anomaly = False

                # --- RF importance Top 3 ---
                rf_list = _fi_b.get(y_col, []) or []
                if not rf_list:
                    # Scene D format
                    rf_raw = _fi_d.get(y_col, [])
                    if rf_raw and isinstance(rf_raw[0], dict):
                        rf_list = [
                            (item["param"], item["importance"]) for item in rf_raw
                        ]
                    elif rf_raw and isinstance(rf_raw[0], (list, tuple)):
                        rf_list = rf_raw
                if rf_list:
                    rf_top3 = rf_list[:3]
                    raw_lines.append("RF 重要性 Top 3:")
                    for param, imp in rf_top3:
                        raw_lines.append(f"  {param}: importance={imp:.4f}")
                else:
                    raw_lines.append("RF 重要性: (無資料)")

                # --- Correlation Top 3 ---
                corr_list = _corr_b.get(y_col, []) or _corr_d.get(y_col, [])
                if corr_list:
                    corr_top3 = corr_list[:3]
                    raw_lines.append("相關性 Top 3:")
                    for item in corr_top3:
                        if isinstance(item, (list, tuple)) and len(item) >= 2:
                            param, r = item[0], item[1]
                            raw_lines.append(f"  {param}: r={r:.4f}")
                        elif isinstance(item, dict):
                            raw_lines.append(
                                f"  {item.get('param', '?')}: r={item.get('r', 0):.4f}"
                            )
                else:
                    raw_lines.append("相關性: (無資料)")

                # --- Cross-correlation lag ---
                lag_info = _lag.get(y_col, {})
                if lag_info:
                    raw_lines.append("交叉相關延遲:")
                    for param, linfo in list(lag_info.items())[:3]:
                        if isinstance(linfo, dict):
                            best_lag = linfo.get("best_lag", 0)
                            best_corr = linfo.get("best_correlation", 0)
                            direction = (
                                "領先"
                                if best_lag > 0
                                else "滯後"
                                if best_lag < 0
                                else "同步"
                            )
                            raw_lines.append(
                                f"  {param}: {direction} {abs(best_lag)} 步 (r={best_corr:.3f})"
                            )
                else:
                    raw_lines.append("交叉延遲: (未檢測或無顯著延遲)")

                # --- Z-score anomalies ---
                zinfo = _zscore.get(y_col, {})
                outlier_idx = zinfo.get("outlier_indices", [])
                if outlier_idx:
                    has_anomaly = True
                    raw_lines.append(
                        f"Z-score 異常: {len(outlier_idx)} 筆 (indices: {outlier_idx[:10]})"
                    )
                    param_metrics.append(
                        EvaluatedMetric(
                            name="zscore_outliers",
                            value=float(len(outlier_idx)),
                            grade="high" if len(outlier_idx) >= 3 else "medium",
                            note=f"{y_col} {len(outlier_idx)} 筆異常",
                        )
                    )
                else:
                    raw_lines.append("Z-score 異常: 無")

                # --- Drift ---
                dinfo = _drift.get(y_col, {})
                if dinfo.get("drift_detected"):
                    has_anomaly = True
                    segs = dinfo.get("segments", [])
                    rho = dinfo.get("rho", 0)
                    raw_lines.append(
                        f"漂移: 檢測到 {len(segs)} 個分段"
                        + (f" (ρ={rho:.3f})" if rho else "")
                    )
                else:
                    raw_lines.append("漂移: 未檢測到")

                # --- Anomaly scan ---
                sinfo = _scan.get(y_col, {})
                scan_segs = sinfo.get("segments", []) if sinfo else []
                if scan_segs:
                    has_anomaly = True
                    seg_descs = []
                    for seg in scan_segs[:3]:
                        s_type = seg.get("type", "?")
                        s_start = seg.get("start", 0)
                        s_end = seg.get("end", 0)
                        s_sev = seg.get("severity_score", 0)
                        seg_descs.append(
                            f"#{s_start}-{s_end} {s_type}(sev={s_sev:.1f})"
                        )
                    raw_lines.append(f"異常掃描: {', '.join(seg_descs)}")
                else:
                    raw_lines.append("異常掃描: 無異常區段")

                # 判定 severity
                if has_anomaly:
                    severity = "medium"
                    evidence_grade = "B"
                else:
                    severity = "low"
                    evidence_grade = "C"

                # 一句話 verdict
                status_parts = []
                if outlier_idx:
                    status_parts.append(f"Z-score 異常 {len(outlier_idx)} 筆")
                if dinfo.get("drift_detected"):
                    status_parts.append("有漂移")
                if scan_segs:
                    status_parts.append(f"scan 偵測到 {len(scan_segs)} 個區段")
                if not status_parts:
                    status_parts.append("正常")
                verdict = f"{y_col}: {', '.join(status_parts)}"

                findings.append(
                    EvaluatedFinding(
                        title=f"📊 {y_col} 參數摘要",
                        severity=severity,
                        evidence_grade=evidence_grade,
                        verdict=verdict,
                        metrics=param_metrics,
                        raw_text="\n".join(raw_lines),
                    )
                )

            logger.info(
                f"[EvidenceEvaluator] Generated {len(_tp_list)} target param summaries"
            )

        # 排序 high → low
        order = {"high": 0, "medium": 1, "low": 2, "noise": 3}
        findings.sort(key=lambda x: order.get(x.severity, 4))

        return findings

    # ============================================================
    # 程式化 📊 段落生成（不靠 LLM）
    # ============================================================

    @staticmethod
    def generate_param_markdown(prep: Dict) -> str:
        """
        從 prep["target_analysis"] 程式化生成 📊 段落 markdown。
        100% 確定性，不經過 LLM。
        回傳空字串表示沒有 target_analysis。
        """
        ta = prep.get("target_analysis", {})
        _tp_list = ta.get("target_params", [])
        if not _tp_list or not isinstance(_tp_list, list):
            return ""

        # 統一資料來源
        _fi_b = ta.get("feature_importance", {})
        _fi_d = ta.get("rf_importance", {})
        _corr_b = ta.get("correlation_with_x", {})
        _corr_d = ta.get("top_correlations", {})
        _zscore = ta.get("zscore", {})
        _drift = ta.get("drift", {})
        _scan = ta.get("anomaly_scan", {})
        _lag = ta.get("cross_correlation_lag", {})

        sections = []
        table_rows = []  # 總結表

        for y_col in _tp_list:
            lines = []
            has_anomaly = False
            status_tags = []
            anomaly_count = 0
            top_factor = "—"

            # --- RF importance ---
            rf_list = _fi_b.get(y_col, []) or []
            if not rf_list:
                rf_raw = _fi_d.get(y_col, [])
                if rf_raw and isinstance(rf_raw[0], dict):
                    rf_list = [
                        (item.get("param", "?"), item.get("importance", 0))
                        for item in rf_raw
                    ]
                elif rf_raw and isinstance(rf_raw[0], (list, tuple)):
                    rf_list = rf_raw
            if rf_list:
                rf_top3 = rf_list[:3]
                rf_str = ", ".join(f"{p} ({v:.3f})" for p, v in rf_top3)
                lines.append(f"- **RF 重要性 Top 3**: {rf_str}")
                top_factor = rf_top3[0][0]
            else:
                lines.append("- **RF 重要性**: (此參數無 RF 分析)")

            # --- Correlations ---
            corr_list = _corr_b.get(y_col, []) or _corr_d.get(y_col, [])
            if corr_list:
                corr_parts = []
                for item in corr_list[:3]:
                    if isinstance(item, (list, tuple)) and len(item) >= 2:
                        corr_parts.append(f"{item[0]} (r={item[1]:.3f})")
                    elif isinstance(item, dict):
                        corr_parts.append(
                            f"{item.get('param', '?')} (r={item.get('r', 0):.3f})"
                        )
                lines.append(f"- **相關性 Top 3**: {', '.join(corr_parts)}")
            else:
                lines.append("- **相關性**: (此參數無相關性分析)")

            # --- Cross-correlation lag ---
            lag_info = _lag.get(y_col, {})
            if lag_info:
                lag_parts = []
                for param, linfo in list(lag_info.items())[:3]:
                    if isinstance(linfo, dict):
                        bl = linfo.get("best_lag", 0)
                        bc = linfo.get("best_correlation", 0)
                        direction = "領先" if bl > 0 else "滯後" if bl < 0 else "同步"
                        lag_parts.append(
                            f"{param} {direction} {abs(bl)} 步 (r={bc:.3f})"
                        )
                if lag_parts:
                    lines.append(f"- **交叉延遲**: {'; '.join(lag_parts)}")
                else:
                    lines.append("- **交叉延遲**: 無顯著領先/滯後關係")
            else:
                lines.append("- **交叉延遲**: (未檢測)")

            # --- Z-score ---
            zinfo = _zscore.get(y_col, {})
            outlier_idx = zinfo.get("outlier_indices", [])
            if outlier_idx:
                has_anomaly = True
                anomaly_count = len(outlier_idx)
                idx_str = ", ".join(str(i) for i in outlier_idx[:8])
                if len(outlier_idx) > 8:
                    idx_str += "..."
                lines.append(
                    f"- **Z-score 異常**: {anomaly_count} 筆 (index: {idx_str})"
                )
                status_tags.append(f"Z-score異常{anomaly_count}筆")
            else:
                lines.append("- **Z-score 異常**: 無")

            # --- Drift ---
            dinfo = _drift.get(y_col, {})
            if dinfo.get("drift_detected"):
                has_anomaly = True
                segs = dinfo.get("segments", [])
                rho = dinfo.get("rho", 0)
                rho_str = f" (ρ={rho:.3f})" if rho else ""
                lines.append(f"- **漂移**: 偵測到 {len(segs)} 個分段{rho_str}")
                status_tags.append(f"漂移{len(segs)}段")
            else:
                lines.append("- **漂移**: 未偵測到")

            # --- Anomaly scan ---
            sinfo = _scan.get(y_col, {})
            scan_segs = sinfo.get("segments", []) if sinfo else []
            if scan_segs:
                has_anomaly = True
                _type_zh = {
                    "DRIFT": "漂移",
                    "SPIKE": "突波",
                    "OSCILLATION": "震盪",
                    "LEVEL_SHIFT": "水平跳變",
                    "SHIFTED_STABLE": "偏移穩態",
                    "DIP_RECOVERY": "急跌恢復",
                    "REGIME_CHANGE": "狀態切換",
                }
                seg_descs = []
                for seg in scan_segs[:5]:
                    st = _type_zh.get(seg.get("type", "?"), seg.get("type", "?"))
                    s_s, s_e = seg.get("start", 0), seg.get("end", 0)
                    sv = seg.get("severity_score", 0)
                    seg_descs.append(f"#{s_s}-{s_e} {st}(severity={sv:.1f})")
                    # 取因子
                    factors = seg.get("top_factors", [])
                    if factors and top_factor == "—":
                        top_factor = factors[0].get("col", "?")
                lines.append(f"- **異常掃描**: {', '.join(seg_descs)}")
                status_tags.append(f"scan{len(scan_segs)}區段")
            else:
                lines.append("- **異常掃描**: 無異常區段")

            # --- 一句話結論 ---
            if not has_anomaly:
                status = "正常"
                conclusion = "⭐ 此參數目前無明顯異常，無需特別關注。"
                attention = "🟢 否"
            elif anomaly_count >= 3 or len(scan_segs) >= 3:
                status = ", ".join(status_tags)
                conclusion = "⭐ 此參數有明顯異常，應優先關注並比對設定值變更紀錄。"
                attention = "🔴 是"
            else:
                status = ", ".join(status_tags)
                conclusion = "⭐ 此參數有輕微異常，建議持續監控。"
                attention = "🟡 是"

            heading = f"#### 📊 {y_col}: {status}"
            body = "\n".join(lines)
            sections.append(f"{heading}\n{body}\n{conclusion}\n")

            table_rows.append(
                f"| {y_col} | {status} | {anomaly_count} | {top_factor} | {attention} |"
            )

        # 整體總結表
        table_header = (
            "\n### 整體總結表\n"
            "| 參數 | 狀態 | 異常筆數 | 主導影響因子 | 需要關注？ |\n"
            "|------|------|---------|------------|----------|\n"
        )
        table_body = "\n".join(table_rows)

        # 組裝
        result = "### 目標參數分析\n\n"
        result += "\n".join(sections)
        result += table_header + table_body + "\n"

        return result

    def format_for_humanizer(self, evaluated: List[EvaluatedFinding]) -> str:
        """格式化為 Humanizer 可用的文字"""
        if not evaluated:
            return "分析完成，未發現顯著異常（所有指標均在正常管制範圍內）。"

        parts = []
        _has_corr_warning = False
        _has_lag_info = False
        _has_rf_info = False

        _finding_num = 0
        for i, ef in enumerate(evaluated, 1):
            sev_cn = {"high": "🔴高", "medium": "🟡中", "low": "🟢低"}.get(
                ef.severity, "⚪"
            )

            # 📊 目標參數摘要 — 用完整 raw_text，不截斷
            if ef.title.startswith("📊"):
                lines = [
                    f"[{ef.title}] 嚴重性={sev_cn}",
                    f"  判定: {ef.verdict}",
                    ef.raw_text,  # 完整內容，不截斷
                ]
            else:
                _finding_num += 1
                lines = [
                    f"[發現 {_finding_num}] 嚴重性={sev_cn} 證據={ef.evidence_grade}",
                    f"  判定: {ef.verdict}",
                    f"  原始: {ef.raw_text[:300]}",
                ]
            for m in ef.metrics:
                g_cn = {
                    "high": "顯著",
                    "medium": "中等",
                    "low": "弱",
                    "noise": "雜訊",
                }.get(m.grade, "?")
                lines.append(f"    {m.name}={m.value:.4f} → {g_cn} {m.note}")
                # 收集語義守衛 flags
                if m.name == "correlation" and m.grade in ("high", "medium"):
                    _has_corr_warning = True
                if m.name == "delay_effect":
                    _has_lag_info = True
                if m.name == "RF_R2":
                    _has_rf_info = True
            parts.append("\n".join(lines))

        result = "\n\n".join(parts)

        # ── 語義守衛提示 (給 Humanizer 的硬指令) ──
        guards = []
        if _has_corr_warning:
            guards.append(
                "⚠ 語義守衛: 發現中等以上相關性 (|r|≥0.4)，結論禁止寫「無異常」「未發現關聯」"
            )
        if _has_lag_info:
            guards.append(
                "⚠ Lag 描述規則: 必須用「X 領先 Y 約 N 步」表述，不可只寫 lag=-N"
            )
        if _has_rf_info:
            guards.append(
                "⚠ Feature Importance 規則: 必須註明「預測貢獻」，不可暗示因果關係"
            )
        if guards:
            result = "\n".join(guards) + "\n\n" + result

        return result

    # ── 內部方法 ────────────────────────────────────

    def _extract_global_metrics(self, stdout: str, data_summary: str) -> Dict:
        """從 stdout 提取全域指標 (UCL, 總行數等)"""
        metrics = {}
        # UCL_99
        m = re.search(r"(?:99%|UCL_99|異常)\s*[=:]\s*([\d.]+)", stdout)
        if m:
            metrics["ucl_99"] = float(m.group(1))
        # UCL_95
        m = re.search(r"(?:95%|UCL_95|警告)\s*[=:]\s*([\d.]+)", stdout)
        if m:
            metrics["ucl_95"] = float(m.group(1))
        # 總行數
        if data_summary:
            m = re.search(r"(\d+)\s*(?:筆|行|rows)", data_summary)
            if m:
                metrics["total_rows"] = int(m.group(1))
        # 場景
        _all_text = stdout + "\n" + (data_summary or "")
        _sm = re.search(r"場景:\s*([A-D])", _all_text)
        if _sm:
            metrics["scenario"] = _sm.group(1)
        # 最佳化任務偵測
        if "[Feature Importance]" in _all_text or "操作窗口" in _all_text:
            metrics["is_optimization"] = True
            # 提取 R²
            _r2m = re.search(r"R²\s*=\s*([\d.]+)", _all_text)
            if _r2m:
                metrics["rf_r2"] = float(_r2m.group(1))
        logger.info(
            f"[EvidenceEvaluator] global_metrics: scenario={metrics.get('scenario', 'N/A')}, "
            f"is_optim={metrics.get('is_optimization', False)}, "
            f"ucl_99={metrics.get('ucl_99', 'N/A')}, "
            f"data_summary_len={len(data_summary or '')}, "
            f"data_summary_head={repr((data_summary or '')[:100])}"
        )
        return metrics

    def _evaluate_single(
        self, finding_text: str, stdout: str, global_metrics: Dict
    ) -> EvaluatedFinding:
        """評估單一 finding"""
        metrics = []
        scores = []
        _has_medium_plus_corr = False  # 語義守衛 flag: correlation ≥ 0.4 時不可判無異常

        # 1. T²_drop
        for val_s in re.findall(r"T²_drop\s*=\s*([\d.]+)", finding_text):
            val = float(val_s)
            if val > self.th.T2_DROP_HIGH:
                g, s = "high", 3
            elif val > self.th.T2_DROP_LOW:
                g, s = "medium", 2
            else:
                g, s = "low", 1
            metrics.append(EvaluatedMetric("T²_drop", val, g))
            scores.append(s)

        # 2. z-score
        for val_s in re.findall(r"[zZ]\s*=\s*(-?[\d.]+)", finding_text):
            val = abs(float(val_s))
            if val > self.th.Z_SIGNIFICANT:
                g, s, n = "high", 3, "顯著偏離基線"
            elif val > self.th.Z_WARNING:
                g, s, n = "medium", 2, "輕微偏離"
            elif val > self.th.Z_NORMAL:
                g, s, n = "low", 1, ""
            else:
                g, s, n = "noise", 0, "正常範圍"
            metrics.append(EvaluatedMetric("z-score", val, g, n))
            scores.append(s)

        # 3. 相關係數
        for val_s in re.findall(
            r"(?:corr|相關[性係]?)\s*[:=]\s*(-?[\d.]+)", finding_text, re.I
        ):
            val = abs(float(val_s))
            if val > 1.0:
                continue
            if val > self.th.CORR_HIGH:
                g, s, n = "high", 3, "強相關 (|r|>0.6)"
                _has_medium_plus_corr = True
            elif val > self.th.CORR_MED:
                g, s, n = "medium", 2, "中相關 (|r|>0.4)，不可說無異常"
                _has_medium_plus_corr = True
            elif val > self.th.CORR_WEAK:
                g, s, n = "low", 1, "弱相關"
            else:
                g, s, n = "noise", 0, "無實質相關 (|r|<0.2)"
            metrics.append(EvaluatedMetric("correlation", val, g, n))
            scores.append(s)

        # 4. p-value
        for val_s in re.findall(r"p\s*[=<]\s*([\d.]+)", finding_text):
            val = float(val_s)
            if val > 1.0:
                continue
            if val < self.th.P_SIGNIFICANT:
                g, s = "high", 3
            elif val < self.th.P_MARGINAL:
                g, s = "medium", 2
            else:
                g, s = "noise", 0
            metrics.append(EvaluatedMetric("p-value", val, g))
            scores.append(s)

        # 5. 場景差異化嚴重度判定
        _scenario = global_metrics.get("scenario", "A")
        # 合併所有可搜索文字：結構化 summary + stdout + LLM finding
        _all_search = stdout + "\n" + finding_text
        if _scenario in ("B", "D"):
            # Scene B/D: 用目標參數的異常比例 + 異常型態判斷
            # 5a. 異常比例 (從 data_summary 的 Z-score 抓)
            _outlier_m = re.search(r"Z-score\s*異常[：:]\s*(\d+)\s*筆", _all_search)
            if not _outlier_m:
                _outlier_m = re.search(r"異常[：:]\s*(\d+)\s*筆", _all_search)
            if not _outlier_m:
                _outlier_m = re.search(r"(\d+)\s*筆.*?異常", _all_search)
            _total_rows = global_metrics.get("total_rows", 0)
            if _outlier_m and _total_rows > 0:
                _n_outlier = int(_outlier_m.group(1))
                _ratio = _n_outlier / _total_rows
                if _ratio > 0.10:
                    g, s = "high", 3
                    _note = f"異常比例 {_ratio:.1%} > 10%"
                elif _ratio > 0.05:
                    g, s = "medium", 2
                    _note = f"異常比例 {_ratio:.1%}"
                elif _n_outlier > 0:
                    g, s = "low", 1
                    _note = f"異常 {_n_outlier} 筆"
                else:
                    g, s = "noise", 0
                    _note = "無異常"
                metrics.append(
                    EvaluatedMetric(
                        "outlier_ratio", _ratio if _total_rows else 0, g, _note
                    )
                )
                scores.append(s)

            # 5b. 異常型態 (spike/level_shift > oscillation/drift > normal)
            _severe_types = len(
                re.findall(r"(?:突波|spike|水平跳變|level_shift)", _all_search, re.I)
            )
            _moderate_types = len(
                re.findall(r"(?:振盪|oscillation|漂移|drift)", _all_search, re.I)
            )
            if _severe_types > 0:
                metrics.append(
                    EvaluatedMetric(
                        "anomaly_type", float(_severe_types), "high", "含突波/跳變"
                    )
                )
                scores.append(3)
            elif _moderate_types > 0:
                metrics.append(
                    EvaluatedMetric(
                        "anomaly_type", float(_moderate_types), "medium", "含振盪/漂移"
                    )
                )
                scores.append(2)

            # 5c. 異常區間數量
            _iv_m = re.search(r"異常區間\s*\(?\s*(\d+)\s*個", _all_search)
            if not _iv_m:
                _iv_m = re.search(r"(\d+)\s*個.*?區間", _all_search)
            if _iv_m:
                _n_iv = int(_iv_m.group(1))
                if _n_iv >= 5:
                    metrics.append(
                        EvaluatedMetric(
                            "interval_count", float(_n_iv), "high", "分散性異常"
                        )
                    )
                    scores.append(3)
                elif _n_iv >= 2:
                    metrics.append(
                        EvaluatedMetric(
                            "interval_count", float(_n_iv), "medium", "多區間"
                        )
                    )
                    scores.append(2)
        elif global_metrics.get("is_optimization"):
            # Optimization: 用 R²、相關性、延遲評分
            # 5a. R² 模型可靠度
            _r2 = global_metrics.get("rf_r2", 0)
            if _r2 > 0.7:
                metrics.append(
                    EvaluatedMetric(
                        "RF_R2",
                        _r2,
                        "high",
                        f"R²={_r2:.3f} 模型可靠 (predictive, not causal)",
                    )
                )
                scores.append(3)
            elif _r2 > 0.4:
                metrics.append(
                    EvaluatedMetric(
                        "RF_R2",
                        _r2,
                        "medium",
                        f"R²={_r2:.3f} 中等解釋力 (predictive, not causal)",
                    )
                )
                scores.append(2)
            elif _r2 > 0:
                metrics.append(
                    EvaluatedMetric(
                        "RF_R2",
                        _r2,
                        "low",
                        f"R²={_r2:.3f} 模型較弱 (predictive, not causal)",
                    )
                )
                scores.append(1)

            # 5b. 相關性強度 (從 finding 文字抓)
            _corr_vals = re.findall(r"r\s*=\s*(-?[\d.]+)", finding_text)
            if _corr_vals:
                _max_corr = max(
                    abs(float(v)) for v in _corr_vals if abs(float(v)) <= 1.0
                )
                if _max_corr > 0.7:
                    metrics.append(
                        EvaluatedMetric("max_correlation", _max_corr, "high", "強相關")
                    )
                    scores.append(3)
                elif _max_corr > 0.4:
                    metrics.append(
                        EvaluatedMetric(
                            "max_correlation", _max_corr, "medium", "中等相關"
                        )
                    )
                    scores.append(2)

            # 5c. 延遲效應 — 翻譯 lag 方向
            _lag_m = re.findall(r"lag\s*=\s*(-?\d+)", finding_text)
            if _lag_m:
                for _lag_s in _lag_m:
                    _lag_val = int(_lag_s)
                    _abs_lag = abs(_lag_val)
                    if _abs_lag > 2:
                        if _lag_val > 0:
                            _dir_note = f"A 領先 B 約 {_abs_lag} 步 (A先變→B後跟)"
                        else:
                            _dir_note = f"B 領先 A 約 {_abs_lag} 步 (B先變→A後跟)"
                        metrics.append(
                            EvaluatedMetric(
                                "delay_effect", float(_abs_lag), "medium", _dir_note
                            )
                        )
                        scores.append(2)
                    elif _abs_lag > 0:
                        metrics.append(
                            EvaluatedMetric(
                                "delay_effect",
                                float(_abs_lag),
                                "low",
                                f"微小延遲 (lag={_lag_val})",
                            )
                        )
                        scores.append(1)
        else:
            # Scene A/C: 全域 T² vs UCL 判定
            ucl_99 = global_metrics.get("ucl_99")
            if ucl_99:
                t2_vals = re.findall(r"T²\s*[=:]\s*([\d.]+)", finding_text)
                if t2_vals:
                    has_exceed = any(
                        float(v) > ucl_99 for v in t2_vals if float(v) < 10000
                    )
                    if not has_exceed:
                        scores = [min(s, 1) for s in scores]
                        metrics.append(
                            EvaluatedMetric(
                                "T²_vs_UCL", ucl_99, "noise", "T²未超UCL，在管制範圍內"
                            )
                        )

        # 6. 小樣本檢查
        sm = re.search(r"(\d+)\s*(?:筆|個|點|樣本)", finding_text)
        if sm:
            n = int(sm.group(1))
            if n < self.th.MIN_ANOMALY_SAMPLES:
                metrics.append(
                    EvaluatedMetric("sample_size", float(n), "low", "小樣本")
                )
                scores = [min(s, 2) for s in scores]

        # ── 綜合判定 ──
        if not scores:
            return EvaluatedFinding(
                title=finding_text[:100],
                severity="low",
                evidence_grade="D",
                verdict="無量化指標，結論不確定",
                metrics=metrics,
                raw_text=finding_text,
            )

        mx = max(scores)
        avg = sum(scores) / len(scores)
        hi = sum(1 for s in scores if s >= 3)

        if mx >= 3 and hi >= 2:
            sev, eg, vd = "high", "A", "多項指標確認，為實質異常"
        elif mx >= 3:
            sev, eg, vd = "high", "B", "單一指標顯著，建議交叉驗證"
        elif mx >= 2 and avg >= 1.5:
            sev, eg, vd = "medium", "B", "中等偏移，值得關注"
        elif mx >= 2:
            sev, eg, vd = "low", "C", "輕微偏差，持續監控即可"
        else:
            sev, eg, vd = "noise", "D", "正常變異範圍，無需行動"

        # ── 語義守衛: correlation ≥ 0.4 時不可判為 noise ──
        if _has_medium_plus_corr and sev == "noise":
            sev, eg = "low", "C"
            vd = "存在中等以上相關性，不宜判定為無異常"
            logger.info(f"[EvidenceEvaluator] 語義守衛: correlation≥0.4 覆蓋 noise→low")

        return EvaluatedFinding(
            title=finding_text[:100],
            severity=sev,
            evidence_grade=eg,
            verdict=vd,
            metrics=metrics,
            raw_text=finding_text,
        )
