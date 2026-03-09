"""
V3 Deep Chain — 規則驅動的多層遞進分析
============================================================
根據 (task_type, has_params, has_range) 三維度選擇 Chain Template，
每層工具結果自動萃取 → 注入下一層參數。
不增加 LLM 調用次數（純計算）。

場景矩陣 (以 anomaly_detection 為例):
  ┌──────────────────┬──────────────────┬──────────────────┐
  │                  │ 有目標參數        │ 無目標參數        │
  ├──────────────────┼──────────────────┼──────────────────┤
  │ 有目標區間        │ 精準區段診斷      │ 區段掃描          │
  │ 無目標區間        │ 參數全域剖析      │ 全域掃描          │
  └──────────────────┴──────────────────┴──────────────────┘

Phase 2 預留: MicroPlanner 接口 (suggest_next_analysis)
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ============================================================
# 1. Chain Template 定義
# ============================================================

# Key 格式: "task_type:param_mode:range_mode"
#   param_mode: "y" = 有目標參數, "n" = 無目標參數
#   range_mode: "y" = 有目標區間, "n" = 無目標區間
#
# 每個 Layer 的結構:
#   tools        — 要執行的工具列表
#   extract_key  — 萃取類型 (對應 extract_from_layer 的分支)
#   inject_mode  — "per_param"  = 對每個萃取出的參數分別執行
#                  "once"       = 只執行一次 (用萃取的彙整資訊)
#                  "use_input"  = 使用輸入的 target_params (不依賴上層萃取)
#   max_params   — per_param 模式下最多處理幾個參數
#   label        — 顯示在前端的中文標籤

DEEP_CHAIN_TEMPLATES: Dict[str, List[Dict[str, Any]]] = {
    # ================================================================
    # anomaly_detection: 異常檢測
    # ================================================================
    # ── 無參數 + 無區間 (全域掃描) ──
    "anomaly_detection:n:n": [
        {
            "tools": ["scan_anomaly_segments"],
            "extract_key": "anomaly_scan",
            "inject_mode": "once",
            "label": "全域異常掃描",
        },
        {
            "tools": ["classify_anomaly_type"],
            "extract_key": "anomaly_classify",
            "inject_mode": "per_param",
            "max_params": 5,
            "label": "異常類型分類",
        },
        {
            "tools": ["get_top_correlations", "detect_correlation_breakdown"],
            "extract_key": "correlation_root_cause",
            "inject_mode": "per_param",
            "max_params": 3,
            "label": "根因溯源",
        },
    ],
    # ── 有參數 + 無區間 (參數全域剖析) ──
    "anomaly_detection:y:n": [
        {
            "tools": ["classify_anomaly_type"],
            "extract_key": "anomaly_classify",
            "inject_mode": "use_input",
            "label": "異常類型分類",
        },
        {
            "tools": ["get_top_correlations", "detect_correlation_breakdown"],
            "extract_key": "correlation_root_cause",
            "inject_mode": "per_param",
            "max_params": 5,
            "label": "關聯因子 + 相關崩潰",
        },
        {
            "tools": ["combo_causal_tracing"],
            "extract_key": "causal_result",
            "inject_mode": "per_param",
            "max_params": 3,
            "label": "因果鏈追蹤",
        },
    ],
    # ── 無參數 + 有區間 (區段掃描) ──
    "anomaly_detection:n:y": [
        {
            "tools": ["scan_anomaly_segments"],
            "extract_key": "anomaly_scan",
            "inject_mode": "once",
            "inject_range": True,  # 注入 focus_range
            "label": "區段異常掃描",
        },
        {
            "tools": ["classify_anomaly_type"],
            "extract_key": "anomaly_classify",
            "inject_mode": "per_param",
            "max_params": 5,
            "inject_range": True,
            "label": "異常類型分類",
        },
        {
            "tools": ["compare_data_segments", "get_top_correlations"],
            "extract_key": "correlation_root_cause",
            "inject_mode": "per_param",
            "max_params": 3,
            "inject_range": True,
            "label": "區段比較 + 根因",
        },
    ],
    # ── 有參數 + 有區間 (精準區段診斷) ──
    "anomaly_detection:y:y": [
        {
            "tools": ["classify_anomaly_type"],
            "extract_key": "anomaly_classify",
            "inject_mode": "use_input",
            "inject_range": True,
            "label": "精準異常分類",
        },
        {
            "tools": ["compare_data_segments", "distribution_shift_analysis"],
            "extract_key": "segment_compare",
            "inject_mode": "per_param",
            "max_params": 5,
            "inject_range": True,
            "label": "區段偏移比較",
        },
        {
            "tools": ["detect_correlation_breakdown", "get_top_correlations"],
            "extract_key": "correlation_root_cause",
            "inject_mode": "per_param",
            "max_params": 3,
            "inject_range": True,
            "label": "區間內根因溯源",
        },
    ],
    # ================================================================
    # drift_analysis: 漂移分析
    # ================================================================
    "drift_analysis:n:n": [
        {
            "tools": ["scan_anomaly_segments"],
            "extract_key": "drift_scan",
            "inject_mode": "once",
            "label": "漂移掃描",
        },
        {
            "tools": ["classify_anomaly_type", "find_temporal_patterns"],
            "extract_key": "drift_classify",
            "inject_mode": "per_param",
            "max_params": 5,
            "label": "漂移機制分析",
        },
        {
            "tools": ["detect_correlation_breakdown"],
            "extract_key": "correlation_root_cause",
            "inject_mode": "per_param",
            "max_params": 3,
            "label": "相關性變化追蹤",
        },
    ],
    "drift_analysis:y:n": [
        {
            "tools": ["classify_anomaly_type", "find_temporal_patterns"],
            "extract_key": "drift_classify",
            "inject_mode": "use_input",
            "label": "參數漂移分析",
        },
        {
            "tools": ["detect_correlation_breakdown", "get_top_correlations"],
            "extract_key": "correlation_root_cause",
            "inject_mode": "per_param",
            "max_params": 3,
            "label": "漂移根因",
        },
    ],
    "drift_analysis:n:y": [
        {
            "tools": ["scan_anomaly_segments"],
            "extract_key": "drift_scan",
            "inject_mode": "once",
            "inject_range": True,
            "label": "區段漂移掃描",
        },
        {
            "tools": ["classify_anomaly_type"],
            "extract_key": "drift_classify",
            "inject_mode": "per_param",
            "max_params": 5,
            "inject_range": True,
            "label": "漂移分類",
        },
        {
            "tools": ["distribution_shift_analysis"],
            "extract_key": "segment_compare",
            "inject_mode": "per_param",
            "max_params": 3,
            "inject_range": True,
            "label": "分佈偏移量化",
        },
    ],
    "drift_analysis:y:y": [
        {
            "tools": ["classify_anomaly_type", "distribution_shift_analysis"],
            "extract_key": "drift_classify",
            "inject_mode": "use_input",
            "inject_range": True,
            "label": "精準漂移診斷",
        },
        {
            "tools": ["detect_correlation_breakdown"],
            "extract_key": "correlation_root_cause",
            "inject_mode": "per_param",
            "max_params": 3,
            "inject_range": True,
            "label": "因果鏈變化",
        },
    ],
    # ================================================================
    # global_analysis: 全域分析
    # ================================================================
    "global_analysis:n:n": [
        {
            "tools": ["combo_parameter_profiling"],
            "extract_key": "profiling_scan",
            "inject_mode": "once",
            "label": "四合一參數掃描",
        },
        {
            "tools": ["cv_ranking", "scan_anomaly_segments"],
            "extract_key": "global_ranking",
            "inject_mode": "once",
            "label": "穩定性排名 + 異常掃描",
        },
        {
            "tools": ["classify_anomaly_type", "get_top_correlations"],
            "extract_key": "correlation_root_cause",
            "inject_mode": "per_param",
            "max_params": 3,
            "label": "重點參數深度診斷",
        },
    ],
}

# ============================================================
# 內部: 快速查詢入口工具表
# ============================================================

# 從所有 chain 的第一層工具建立反查表
_CHAIN_ENTRY_MAP: Dict[str, List[str]] = {}
for _chain_key, _layers in DEEP_CHAIN_TEMPLATES.items():
    if _layers:
        _task_type = _chain_key.split(":")[0]
        for _tool in _layers[0]["tools"]:
            if _tool not in _CHAIN_ENTRY_MAP:
                _CHAIN_ENTRY_MAP[_tool] = []
            if _task_type not in _CHAIN_ENTRY_MAP[_tool]:
                _CHAIN_ENTRY_MAP[_tool].append(_task_type)


# ============================================================
# 2. 觸發判斷
# ============================================================


def _build_chain_key(
    task_type: str,
    has_params: bool,
    has_range: bool,
) -> str:
    """建構 chain template 查詢 key"""
    p = "y" if has_params else "n"
    r = "y" if has_range else "n"
    return f"{task_type}:{p}:{r}"


def should_use_deep_chain(
    task_type: str,
    suggested_tools: List[str],
    target_params: Optional[List[str]] = None,
    target_range: Optional[str] = None,
) -> Optional[str]:
    """
    判斷是否應該啟用 Deep Chain。

    Args:
        task_type: 任務類型
        suggested_tools: LLM 建議的工具列表
        target_params: 目標參數列表
        target_range: 目標區間

    Returns:
        匹配的 chain_key (如 "anomaly_detection:n:n") 或 None
    """
    has_params = bool(target_params)
    has_range = bool(target_range and target_range != "all")

    # 嘗試精確匹配
    chain_key = _build_chain_key(task_type, has_params, has_range)
    if chain_key in DEEP_CHAIN_TEMPLATES:
        # LLM 只指定了 <= 1 個工具時才啟用 (多工具代表 LLM 有明確意圖)
        if len(suggested_tools) <= 1:
            return chain_key
        # 即使多工具，如果首個工具是入口工具也啟用
        if suggested_tools and suggested_tools[0] in _CHAIN_ENTRY_MAP:
            first_tool_entry = DEEP_CHAIN_TEMPLATES[chain_key][0]["tools"]
            if suggested_tools[0] in first_tool_entry:
                return chain_key

    # 嘗試同 task_type 的無參數無區間版本作為 fallback
    fallback_key = _build_chain_key(task_type, False, False)
    if fallback_key in DEEP_CHAIN_TEMPLATES and len(suggested_tools) <= 1:
        logger.info(
            f"[DeepChain] No exact match for '{chain_key}', "
            f"falling back to '{fallback_key}'"
        )
        return fallback_key

    # 根據入口工具推斷 task_type
    if len(suggested_tools) == 1:
        first_tool = suggested_tools[0]
        if first_tool in _CHAIN_ENTRY_MAP:
            inferred_type = _CHAIN_ENTRY_MAP[first_tool][0]
            inferred_key = _build_chain_key(inferred_type, has_params, has_range)
            if inferred_key in DEEP_CHAIN_TEMPLATES:
                logger.info(
                    f"[DeepChain] Inferred chain '{inferred_key}' "
                    f"from tool '{first_tool}'"
                )
                return inferred_key

    return None


# ============================================================
# 3. 結果萃取器
# ============================================================


def extract_from_layer(
    results: List[Dict[str, Any]],
    extract_key: str,
) -> Dict[str, Any]:
    """
    從一層工具的執行結果中萃取下一層需要的資訊。

    Returns:
        {
            "params": ["PARAM_A", "PARAM_B", ...],
            "ranges": {"PARAM_A": "100-200", ...},
            "context": {...},
            "findings": ["發現1", ...],
        }
    """
    extracted = {
        "params": [],
        "ranges": {},
        "context": {},
        "findings": [],
    }

    for result in results:
        if not isinstance(result, dict):
            continue
        if result.get("status") == "ERROR" or result.get("error"):
            continue

        if extract_key in ("anomaly_scan", "drift_scan"):
            _extract_anomaly_scan(result, extracted, extract_key)
        elif extract_key in ("anomaly_classify", "drift_classify"):
            _extract_anomaly_classify(result, extracted)
        elif extract_key == "profiling_scan":
            _extract_profiling(result, extracted)
        elif extract_key == "global_ranking":
            _extract_global_ranking(result, extracted)
        elif extract_key in ("correlation_root_cause", "causal_result"):
            _extract_correlation(result, extracted)
        elif extract_key == "segment_compare":
            _extract_segment_compare(result, extracted)

    # 去重
    extracted["params"] = list(dict.fromkeys(extracted["params"]))
    return extracted


# --- 各萃取器實作 ---


def _extract_anomaly_scan(result: Dict, extracted: Dict, extract_key: str) -> None:
    """從 scan_anomaly_segments 結果萃取"""
    worst = result.get("worst_parameters", [])
    for wp in worst:
        param = wp.get("parameter", "")
        if param and param not in extracted["params"]:
            extracted["params"].append(param)

    top_segs = result.get("top_segments", [])
    for seg in top_segs:
        param = seg.get("parameter", "")
        if param:
            row_range = f"{seg.get('row_start', 0)}-{seg.get('row_end', 0)}"
            if param not in extracted["ranges"]:
                extracted["ranges"][param] = row_range
            seg_type = seg.get("type", "")
            severity = seg.get("severity", "")
            extracted["findings"].append(
                f"{param}: {seg_type} (Row {row_range}, {severity})"
            )

    type_groups = result.get("anomaly_type_groups", [])
    if type_groups:
        extracted["context"]["type_groups"] = type_groups

    # drift_scan: 只保留 DRIFT/LEVEL_SHIFT
    if extract_key == "drift_scan":
        drift_params = set()
        for seg in top_segs:
            if seg.get("type") in ("DRIFT", "LEVEL_SHIFT"):
                p = seg.get("parameter", "")
                if p:
                    drift_params.add(p)
        if drift_params:
            extracted["params"] = [p for p in extracted["params"] if p in drift_params]

    total = result.get("total_anomaly_segments", 0)
    scanned = result.get("total_columns_scanned", 0)
    if total > 0:
        extracted["findings"].insert(
            0, f"全域掃描: {scanned} 欄位中發現 {total} 個異常區段"
        )


def _extract_anomaly_classify(result: Dict, extracted: Dict) -> None:
    """從 classify_anomaly_type 結果萃取"""
    param = result.get("parameter", "")
    classifications = result.get("classifications", [])

    for cls in classifications:
        cls_type = cls.get("type", "")
        cls_range = cls.get("range", "")
        confidence = cls.get("confidence", 0)

        if param and cls_range and confidence > 0.5:
            if param not in extracted["ranges"] or confidence > 0.7:
                extracted["ranges"][param] = cls_range
            extracted["findings"].append(
                f"{param}: {cls_type} (Row {cls_range}, 信心度 {confidence:.0%})"
            )

    if param and classifications:
        if param not in extracted["params"]:
            extracted["params"].append(param)


def _extract_profiling(result: Dict, extracted: Dict) -> None:
    """從 combo_parameter_profiling 結果萃取"""
    for key in ("auto_targets", "anomaly_parameters"):
        items = result.get(key, [])
        for item in items:
            param = item.get("parameter", item) if isinstance(item, dict) else str(item)
            if param and param not in extracted["params"]:
                extracted["params"].append(param)
    auto_targets = result.get("auto_targets", [])
    if auto_targets:
        extracted["findings"].append(f"四合一掃描識別 {len(auto_targets)} 個異常參數")


def _extract_global_ranking(result: Dict, extracted: Dict) -> None:
    """從 cv_ranking / scan_anomaly_segments 結果萃取"""
    rankings = result.get("rankings", result.get("cv_rankings", []))
    for rank in rankings[:5]:
        param = rank.get("parameter", rank.get("column", ""))
        if param and param not in extracted["params"]:
            extracted["params"].append(param)
            cv = rank.get("cv", rank.get("coefficient_of_variation", 0))
            extracted["findings"].append(f"{param}: CV={cv:.4f}")
    _extract_anomaly_scan(result, extracted, "anomaly_scan")


def _extract_correlation(result: Dict, extracted: Dict) -> None:
    """從相關分析結果萃取"""
    top_corr = result.get("top_correlations", [])
    for corr in top_corr[:5]:
        param = corr.get("parameter", corr.get("column", ""))
        r_val = corr.get("correlation", corr.get("r", 0))
        if param and abs(r_val) > 0.5:
            extracted["findings"].append(f"相關: {param} (r={r_val:.3f})")

    breakdowns = result.get("breakdowns", result.get("changed_pairs", []))
    for bd in breakdowns[:3]:
        param = bd.get("parameter", bd.get("pair", ""))
        change = bd.get("change", bd.get("delta", 0))
        if param:
            extracted["findings"].append(f"相關崩潰: {param} (變化={change:.3f})")


def _extract_segment_compare(result: Dict, extracted: Dict) -> None:
    """從 compare_data_segments / distribution_shift_analysis 萃取"""
    # distribution_shift
    shift = result.get("wasserstein_distance", result.get("shift_score", 0))
    param = result.get("parameter", "")
    if param and shift:
        extracted["findings"].append(f"{param}: 分佈偏移 = {shift:.4f}")
        if param not in extracted["params"]:
            extracted["params"].append(param)

    # compare_data_segments
    diffs = result.get("significant_differences", result.get("diffs", []))
    for d in diffs[:5]:
        col = d.get("column", d.get("parameter", ""))
        if col:
            extracted["findings"].append(f"區段差異: {col}")
            if col not in extracted["params"]:
                extracted["params"].append(col)


# ============================================================
# 4. 下一層參數建構器
# ============================================================


def build_next_layer_tasks(
    layer_template: Dict[str, Any],
    prev_extracted: Dict[str, Any],
    file_id: str,
    input_target_params: Optional[List[str]] = None,
    input_target_range: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    根據模板和萃取結果建構下一層工具執行任務。

    Args:
        layer_template: 本層模板定義
        prev_extracted: 上一層的萃取結果
        file_id: 檔案 ID
        input_target_params: 用戶指定的目標參數 (use_input 模式)
        input_target_range: 用戶指定的目標區間

    Returns:
        [{tool_name, params, source_param}, ...]
    """
    tools = layer_template["tools"]
    inject_mode = layer_template.get("inject_mode", "once")
    max_params = layer_template.get("max_params", 5)
    inject_range = layer_template.get("inject_range", False)

    # 決定參數來源
    if inject_mode == "use_input":
        params_list = (input_target_params or [])[:max_params]
        ranges = prev_extracted.get("ranges", {}) if prev_extracted else {}
    else:
        params_list = (prev_extracted.get("params", []) if prev_extracted else [])[
            :max_params
        ]
        ranges = prev_extracted.get("ranges", {}) if prev_extracted else {}

    tasks = []

    if inject_mode in ("per_param", "use_input"):
        if not params_list:
            logger.info("[DeepChain] 無可用參數，跳過此層")
            return []

        for param in params_list:
            param_range = ranges.get(param)
            for tool_name in tools:
                task_params = {
                    "file_id": file_id,
                    "parameter": param,
                    "target": param,
                }
                # 注入區間: 優先用萃取的精確區間，其次用輸入區間
                effective_range = param_range
                if inject_range and input_target_range:
                    effective_range = effective_range or input_target_range
                if effective_range:
                    task_params["focus_range"] = effective_range
                    # distribution_shift 需要 baseline_range
                    if tool_name in (
                        "distribution_shift_analysis",
                        "compare_data_segments",
                    ):
                        task_params["baseline_range"] = "all"
                        if tool_name == "compare_data_segments":
                            task_params["target_segments"] = effective_range

                tasks.append(
                    {
                        "tool_name": tool_name,
                        "params": task_params,
                        "source_param": param,
                    }
                )
    else:
        # once 模式
        for tool_name in tools:
            task_params = {"file_id": file_id}
            if params_list:
                task_params["target_columns"] = params_list
                task_params["parameters"] = params_list
            if inject_range and input_target_range:
                task_params["focus_range"] = input_target_range
            tasks.append(
                {
                    "tool_name": tool_name,
                    "params": task_params,
                    "source_param": None,
                }
            )

    return tasks


# ============================================================
# 5. 統一參數注入器 (Unified Context Injection)
# ============================================================

# 工具參數名 → Context 欄位的映射表
# 單目標 key → 從 target_params[0] 取值
_SINGLE_TARGET_KEYS = {"target", "parameter", "process_variable", "target_parameter"}
# 列表目標 key → 從 target_params 取值
_LIST_TARGET_KEYS = {"target_columns", "targets", "parameters", "features"}
# 對照參數 key → 從 reference_params 取值
_REFERENCE_KEYS = {"reference", "reference_parameters", "predictors", "category"}
# 區間 key
_FOCUS_RANGE_KEYS = {"focus_range", "anomaly_range"}
_BASELINE_RANGE_KEYS = {"baseline_range", "baseline_segments"}
_TARGET_SEGMENTS_KEYS = {"target_segments"}


def inject_tool_params(
    tool_name: str,
    file_id: str,
    target_params: Optional[List[str]] = None,
    reference_params: Optional[List[str]] = None,
    target_range: Optional[str] = None,
    baseline_range: Optional[str] = None,
    extra_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    統一參數注入器: 根據 TOOL_REGISTRY spec + AnalysisContext 四參數
    自動為工具建構完整的執行參數。

    Args:
        tool_name: 工具名稱
        file_id: 檔案 ID
        target_params: 目標參數列表
        reference_params: 對照參數列表
        target_range: 目標區間 (如 "100-200")
        baseline_range: 對照區間 (如 "1-99")
        extra_params: 額外覆寫參數 (優先於自動注入)

    Returns:
        完整的工具參數字典
    """
    from backend.services.analysis.tools.registry import get_tool_spec

    params: Dict[str, Any] = {"file_id": file_id}
    spec = get_tool_spec(tool_name)

    target_params = target_params or []
    reference_params = reference_params or []
    first_target = target_params[0] if target_params else None
    first_ref = reference_params[0] if reference_params else None
    has_range = bool(target_range and target_range != "all")
    has_baseline = bool(baseline_range and baseline_range != "all")

    if spec:
        all_params = set(
            spec.get("required_params", []) + spec.get("optional_params", [])
        )

        # --- 目標參數注入 ---
        for key in all_params:
            if key in _SINGLE_TARGET_KEYS and first_target:
                params[key] = first_target
            elif key in _LIST_TARGET_KEYS and target_params:
                params[key] = target_params
            elif key in _LIST_TARGET_KEYS and not target_params:
                # 無目標 → 全域模式
                if spec.get("supports_global"):
                    params[key] = spec.get("global_target", "all")

        # --- 對照參數注入 ---
        for key in all_params:
            if key in _REFERENCE_KEYS:
                if key == "reference" and first_ref:
                    params[key] = first_ref
                elif key == "reference_parameters" and reference_params:
                    params[key] = reference_params
                elif key == "predictors" and reference_params:
                    params[key] = reference_params
                elif key == "category" and first_ref:
                    params[key] = first_ref

        # --- supports_global 兜底 ---
        if spec.get("supports_global") and not target_params:
            req = spec.get("required_params", [])
            if req and req[0] not in params:
                params[req[0]] = spec.get("global_target", "all")

        # --- 區間注入 ---
        if has_range:
            for key in all_params:
                if key in _FOCUS_RANGE_KEYS:
                    params[key] = target_range
                elif key in _TARGET_SEGMENTS_KEYS:
                    params[key] = target_range
        if has_baseline:
            for key in all_params:
                if key in _BASELINE_RANGE_KEYS:
                    params[key] = baseline_range

        # --- 比較工具特殊處理 ---
        # 如果工具需要 baseline_range 但用戶沒指定，用 "all" 作為基線
        req_params = spec.get("required_params", [])
        if "baseline_range" in req_params and "baseline_range" not in params:
            if has_range:
                params["baseline_range"] = "all"
        if "baseline_segments" not in params and "baseline_segments" in spec.get(
            "optional_params", []
        ):
            if has_range and not has_baseline:
                params["baseline_segments"] = "all"

    else:
        # 無 spec: 最小化注入
        if first_target:
            params["parameter"] = first_target
        if has_range:
            params["focus_range"] = target_range

    # --- 額外參數覆寫 ---
    if extra_params:
        params.update(extra_params)

    return params


# ============================================================
# 5. Phase 2 預留: MicroPlanner 接口
# ============================================================


def suggest_next_analysis(
    chain_findings: List[str],
    task_type: str,
    analyzed_params: List[str],
) -> Optional[str]:
    """
    [Phase 2] 根據 Deep Chain 發現，產生後續分析建議。
    目前回傳 None，待 Phase 2 接入 LLM。
    """
    return None
