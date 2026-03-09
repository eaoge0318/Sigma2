"""
Code Interpreter 子方法
============================================================
從 OrchestratedAnalysisAgentV3._run_code_interpreter 提取出來的共用邏輯。
"""

import logging
import re

logger = logging.getLogger(__name__)


async def load_analysis_data(analysis_service, session_id, file_id):
    """載入 DataFrame + summary。回傳 (df, data_summary) 或 (None, {})。"""
    import asyncio

    df = None
    data_summary = {}
    if analysis_service and file_id:
        try:
            df = await asyncio.to_thread(
                analysis_service.get_dataframe, session_id, file_id
            )
            summary_data = await asyncio.to_thread(
                analysis_service.load_summary, session_id, file_id
            )
            if summary_data:
                data_summary = {
                    "row_count": summary_data.get("row_count", 0),
                    "column_count": summary_data.get("col_count", 0),
                    "numerical_columns": [
                        c for c in summary_data.get("columns", []) if c != "CONTEXTID"
                    ],
                    "categorical_columns": (
                        ["CONTEXTID"]
                        if "CONTEXTID" in summary_data.get("columns", [])
                        else []
                    ),
                }
        except Exception as e:
            logger.error(f"[V3:CodeInterpreter] 載入資料失敗: {e}")
    return df, data_summary


def build_report_prep(df_numeric, route, unified_context):
    """
    preprocess + report aliases + deterministic baseline + range-focus。
    回傳 (df_active, prep)。prep 為 None 表示 preprocess 失敗。
    """
    try:
        from backend.services.analysis import sigma_utils

        prep = sigma_utils.preprocess(
            df_numeric,
            task_type=route.task_type,
            target_params=route.target_params,
            target_range=route.target_range,
            baseline_range=getattr(route, "baseline_range", None),
        )
        df_active = prep["df_active"]
    except Exception as e:
        logger.error(f"[V3:CodeInterpreter] preprocess 失敗: {e}", exc_info=True)
        return df_numeric, None

    # preprocess_summary_text 獨立 try-except，不影響 prep 本體
    try:
        from backend.services.analysis import sigma_utils

        prep["_preprocess_summary"] = sigma_utils.preprocess_summary_text(prep)
    except Exception as e:
        logger.error(
            f"[V3:CodeInterpreter] preprocess_summary_text 失敗: {e}", exc_info=True
        )
        prep["_preprocess_summary"] = f"[前處理摘要產生失敗: {e}]"

    if not isinstance(prep, dict):
        return df_active, prep

    # Schema alias
    if "meta" in prep:
        prep["top_std_cols"] = prep["meta"].get("top_std_cols", [])

    # Report ↔ df_active 一致性
    _valid = set(df_active.columns)

    def _fc(cl):
        return [c for c in cl if c in _valid]

    t2c = prep.get("t2_contrib", {})
    if "top_contributors_global" in t2c:
        t2c["top_contributors_global"] = _fc(t2c["top_contributors_global"])
    for idx in t2c.get("top_contributors_by_interval", {}):
        t2c["top_contributors_by_interval"][idx] = _fc(
            t2c["top_contributors_by_interval"][idx]
        )
    pca = prep.get("pca", {})
    if "top_loading_cols" in pca:
        pca["top_loading_cols"] = _fc(pca["top_loading_cols"])
    meta = prep.get("meta", {})
    if "top_std_cols" in meta:
        meta["top_std_cols"] = _fc(meta["top_std_cols"])
        prep["top_std_cols"] = meta["top_std_cols"]

    # Report compatibility: 扁平化快捷鍵
    # hotelling.anomaly_indices 已在 sigma_utils.py 擴展 ±3，這裡直接用
    _expanded_indices = prep.get("hotelling", {}).get("anomaly_indices", [])
    _sorted_expanded = sorted(set(_expanded_indices))
    prep["anomaly_indices"] = _sorted_expanded
    # anomaly_intervals 由 sigma_utils 計算並回傳，直接用（保證與 top_contributors_by_interval keys 一致）
    if "anomaly_intervals" not in prep:
        # fallback: 自己算（例如 optimization/drift 場景沒有 anomaly_intervals）
        _intervals = []
        if _sorted_expanded:
            _s = _sorted_expanded[0]
            _e = _s
            for _v in _sorted_expanded[1:]:
                if _v == _e + 1:
                    _e = _v
                else:
                    _intervals.append(f"{_s}-{_e}")
                    _s = _v
                    _e = _v
            _intervals.append(f"{_s}-{_e}")
        prep["anomaly_intervals"] = _intervals
    prep["pca_top_cols"] = prep.get("pca", {}).get("top_loading_cols", [])
    prep["t2_top_global"] = prep.get("t2_contrib", {}).get(
        "top_contributors_global", []
    )
    # t2_by_interval 已在 sigma_utils.py 完成，直接用
    prep["t2_by_interval"] = prep.get("t2_contrib", {}).get(
        "top_contributors_by_interval", {}
    )
    prep["allow_corr"] = prep.get("stability", {}).get("allow_corr", False)
    prep["allow_ttest"] = prep.get("stability", {}).get("allow_ttest", False)

    # === Deterministic Baseline ===
    _anom_idxs = prep.get("anomaly_indices", [])
    _all_idx = list(df_active.index)
    _n = len(_all_idx)
    _anom_set = set(_anom_idxs)
    prep["baseline_indices"] = [i for i in _all_idx if i not in _anom_set]

    def _make_bw(center_pos, half_w=20):
        far_s = max(0, center_pos - 3 * half_w)
        far_e = max(0, center_pos - 2 * half_w)
        if far_e - far_s < half_w:
            far_s = min(_n - half_w, center_pos + 2 * half_w)
            far_e = min(_n, far_s + half_w)
        return {"start": int(far_s), "end": int(far_e)}

    prep["baseline_windows"] = {}
    for _aidx in _anom_idxs:
        try:
            _pos = _all_idx.index(_aidx)
        except ValueError:
            _pos = _aidx
        prep["baseline_windows"][_aidx] = _make_bw(_pos)

    # === target_range: 使用者指定區間 (List[str]) ===
    _tr_list = unified_context.get("target_range", [])
    if isinstance(_tr_list, str):
        # 相容舊版: "50-69" → ["50-69"], "all"/""→ []
        _tr_list = [] if _tr_list in ("all", "") else [_tr_list]

    if _tr_list:
        # 解析多個使用者指定區間
        _target_idxs = []
        _parsed_intervals = []
        for _tr in _tr_list:
            _range_match = re.match(r"(\d+)\s*[-~—]\s*(\d+)", str(_tr))
            if _range_match:
                _rs_user = int(_range_match.group(1))
                _re_user = int(_range_match.group(2))
                _rs = max(0, _rs_user - 1)  # user 1-based → 0-based
                _re_val = min(_n, _re_user)
                _target_idxs.extend(range(_rs, _re_val))
                _parsed_intervals.append(f"{_rs}-{_re_val - 1}")

        prep["target_intervals"] = _parsed_intervals
        prep["anomaly_indices"] = sorted(set(_target_idxs))
        logger.info(
            f"[ci_helpers] target_range 解析: input={_tr_list}, "
            f"parsed_intervals={_parsed_intervals}, "
            f"anomaly_indices[:5]={sorted(set(_target_idxs))[:5]}, "
            f"count={len(set(_target_idxs))}"
        )

        # 用指定範圍重算 T² contribution
        from backend.services.analysis.sigma_utils import t2_contribution

        _anom_set = set(_target_idxs)
        prep["baseline_indices"] = [i for i in _all_idx if i not in _anom_set]
        try:
            c_scores, c_names = t2_contribution(df_active, list(_anom_set))
            _t2_by_interval = {}
            for _iv in _parsed_intervals:
                _t2_by_interval[_iv] = c_names[:10]
            prep["t2_contrib"] = {
                "top_contributors_global": c_names[:15],
                "top_contributors_by_interval": _t2_by_interval,
                "overlap": [],
            }
            prep["t2_top_global"] = c_names[:15]
            prep["t2_by_interval"] = _t2_by_interval
        except Exception as _e:
            logger.warning(f"[ci_helpers] target_range T² contribution failed: {_e}")

        # 重建 baseline_windows
        prep["baseline_windows"] = {}
        for _aidx in _target_idxs:
            try:
                _pos = _all_idx.index(_aidx)
            except ValueError:
                _pos = _aidx
            prep["baseline_windows"][_aidx] = _make_bw(_pos)
    else:
        prep["target_intervals"] = []

    # === 預建 DataFrame，供 LLM 直接使用（不需要手動 indexing）===
    _scenario = prep.get("scenario", "A") if isinstance(prep, dict) else "A"
    _ai = prep.get("anomaly_indices", [])
    _bi = prep.get("baseline_indices", [])

    if _scenario in ("B", "D") and isinstance(prep, dict):
        # Scene B/D: 有目標參數
        # 優先使用 target_range（使用者指定區間），其次才用 Z-score outlier
        _user_range_idxs = prep.get(
            "anomaly_indices", []
        )  # L169 已被 target_range 覆寫
        _has_user_range = bool(prep.get("target_intervals"))

        if _has_user_range and _user_range_idxs:
            # 使用者明確指定區間 → 直接用
            _valid = [i for i in _user_range_idxs if i in df_active.index]
            prep["_df_anomaly"] = (
                df_active.loc[_valid] if _valid else df_active.iloc[0:0]
            )
            prep["_df_baseline"] = df_active.loc[
                [i for i in df_active.index if i not in set(_user_range_idxs)]
            ]
            logger.info(
                f"[ci_helpers:D] df_anomaly 索引範圍: "
                f"min={min(_valid) if _valid else 'N/A'}, "
                f"max={max(_valid) if _valid else 'N/A'}, "
                f"count={len(_valid)}, "
                f"first_5={_valid[:5]}, "
                f"df_anomaly.index[:5]={list(prep['_df_anomaly'].index[:5])}"
            )
            # df_intervals 也從 target_intervals 建構
            _target_intervals = {}
            for _iv in prep.get("target_intervals", []):
                _parts = _iv.split("-")
                try:
                    _s, _e = int(_parts[0]), int(_parts[1])
                    _target_intervals[_iv] = df_active.iloc[_s : _e + 1]
                except (ValueError, IndexError):
                    pass
            prep["_df_intervals"] = _target_intervals
        else:
            # 沒有使用者指定區間 → 用 Z-score outlier_indices
            _ta = prep.get("target_analysis", {})
            _target_outlier_idx = []
            _target_intervals = {}
            for _y_col, _zinfo in _ta.get("zscore", {}).items():
                _oi = _zinfo.get("outlier_indices", [])
                _target_outlier_idx.extend(_oi)
            for _y_col, _ivs in _ta.get("anomaly_intervals", {}).items():
                for _iv in _ivs:
                    _parts = _iv.split("-")
                    try:
                        _s, _e = int(_parts[0]), int(_parts[1])
                        _target_intervals[_iv] = df_active.iloc[_s : _e + 1]
                    except (ValueError, IndexError):
                        pass

            # Fallback: Z-score 沒抓到時，用 anomaly_scan 的 segments 補充
            if not _target_outlier_idx:
                for _y_col, _sinfo in _ta.get("anomaly_scan", {}).items():
                    for _seg in _sinfo.get("segments", []):
                        _s = _seg.get("start", 0)
                        _e = _seg.get("end", 0)
                        _target_outlier_idx.extend(range(_s, _e + 1))
                        _iv_key = f"{_s}-{_e}"
                        if _iv_key not in _target_intervals:
                            _target_intervals[_iv_key] = df_active.iloc[_s : _e + 1]

            _target_outlier_idx = sorted(set(_target_outlier_idx))
            _valid = [i for i in _target_outlier_idx if i in df_active.index]
            prep["_df_anomaly"] = (
                df_active.loc[_valid] if _valid else df_active.iloc[0:0]
            )
            prep["_df_baseline"] = df_active.loc[
                [i for i in df_active.index if i not in set(_target_outlier_idx)]
            ]
            prep["_df_intervals"] = _target_intervals
    else:
        # Scene A/C: 用全域 T² anomaly_indices
        # ⚠️ 必須用 .loc 不能用 .iloc：
        # _ai / _bi 的值來自 list(df_active.index)，是 index label
        prep["_df_anomaly"] = df_active.loc[_ai] if _ai else df_active.iloc[0:0]
        prep["_df_baseline"] = df_active.loc[_bi] if _bi else df_active.iloc[0:0]
        # anomaly_intervals 現在是字串 "s-e" 格式
        prep["_df_intervals"] = {}
        for _key in prep.get("anomaly_intervals", []):
            _parts = _key.split("-")
            _s_int, _e_int = int(_parts[0]), int(_parts[1])
            prep["_df_intervals"][_key] = df_active.iloc[_s_int : _e_int + 1]

    return df_active, prep


def extract_finding_text(res: dict, param_name: str = None) -> str:
    """
    從工具結果 dict 中萃取 finding 文字。
    共用於 _run_flat_tools 和 _run_deep_chain。
    """
    if not isinstance(res, dict) or res.get("error"):
        return ""
    if res.get("summary"):
        return str(res["summary"])[:200]
    if res.get("z_score") and abs(res["z_score"]) > 3:
        return f"{param_name or '?'} 異常 (Z={res['z_score']:.1f})"
    if res.get("top_correlations"):
        tc = res["top_correlations"][:3]
        parts = [
            f"{c.get('parameter', '?')}(r={c.get('correlation', 0):.2f})"
            for c in tc
            if isinstance(c, dict)
        ]
        if parts:
            label = f"{param_name} 相關" if param_name else "相關"
            return f"{label}: {', '.join(parts)}"
    if res.get("mean") is not None:
        return f"平均值: {res['mean']:.4f}, 標準差: {res.get('std', 0):.4f}"
    if res.get("anomaly_parameters"):
        ap = res["anomaly_parameters"][:5]
        names = [a.get("parameter", a) if isinstance(a, dict) else str(a) for a in ap]
        return f"異常參數 (Top {len(names)}): {', '.join(names)}"
    if res.get("auto_targets"):
        at = res["auto_targets"]
        return f"AutoTarget ({len(at)} 個): {', '.join(at[:5])}"
    return ""


def build_progress_hints(previous_outputs: list) -> str | None:
    """
    分析 previous_outputs 判斷上輪做了什麼，回傳 progress gate hint。
    如果不需要 gate 回傳 None。
    """
    if not previous_outputs:
        return None
    prev_stdout = "\n".join(
        o.get("stdout", "") for o in previous_outputs if not o.get("error")
    )
    has_anomaly = "anomaly" in prev_stdout.lower() or "異常" in prev_stdout
    has_contrib = "主導欄位" in prev_stdout or "top_contributors" in prev_stdout.lower()
    if not (has_anomaly and has_contrib):
        return None
    has_stats = any(
        kw in prev_stdout.lower()
        for kw in ["effect_size", "cohen", "delta_mean", "p-value", "p_value", "rho="]
    )
    hint = "\n\n## ⚠️ 系統進度判定\n上一輪已完成: 異常樣本識別 + 主導欄位列出。"
    if has_stats:
        hint += " 已有部分統計數字。"
    hint += (
        "\n**本輪禁止**: 重新列出 anomaly_indices、重新印 top_contributors、"
        "重新檢查 allow_corr/allow_ttest。"
        "\n**本輪必須**: 選擇 1 個異常點深化追查，產生新的數字證據（不能重複上輪已有的數字）。"
    )
    return hint


async def run_exec_streaming(
    executor, code, code_context, stdout_queue, ctx, round_num
):
    """
    Streaming bridge: queue + consumer + thread exec + chart/error flush。
    回傳 (result, total_new_charts: int)
    """
    import asyncio
    from backend.services.analysis.analysis_types import (
        CodeOutputEvent,
        ChartImageEvent,
    )

    line_queue = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def on_stdout_line(line: str):
        logger.info(f"[V3:stdout:1-callback] {line[:60]}")
        loop.call_soon_threadsafe(line_queue.put_nowait, line)

    streaming_done = asyncio.Event()

    async def stream_consumer():
        while not streaming_done.is_set() or not line_queue.empty():
            try:
                line = await asyncio.wait_for(line_queue.get(), timeout=0.1)
                if stdout_queue is not None:
                    logger.info(f"[V3:stdout:2-consumer→queue] {line[:60]}")
                    await stdout_queue.put((line, round_num))
                else:
                    ctx.write_event_to_stream(
                        CodeOutputEvent(
                            stdout=line,
                            stderr="",
                            error="",
                            round_num=round_num,
                            is_line=True,
                        )
                    )
            except asyncio.TimeoutError:
                continue

    consumer_task = asyncio.create_task(stream_consumer())
    result = await asyncio.to_thread(
        executor.execute_streaming, code, code_context, on_stdout_line
    )
    streaming_done.set()
    await consumer_task

    # flush error/stderr
    if result.stderr or result.error:
        ctx.write_event_to_stream(
            CodeOutputEvent(
                stdout="",
                stderr=result.stderr,
                error=result.error or "",
                round_num=round_num,
            )
        )

    # flush charts
    new_charts = 0
    for chart in result.charts:
        ctx.write_event_to_stream(
            ChartImageEvent(
                image_base64=chart["image_base64"],
                title=chart.get("title", ""),
                width=chart.get("width", 0),
                height=chart.get("height", 0),
                round_num=round_num,
            )
        )
        new_charts += 1
    logger.info(f"[V3:CI] Round {round_num}: {len(result.charts)} charts captured")
    return result, new_charts
