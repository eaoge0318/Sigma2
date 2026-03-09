"""
進階異常區段偵測方法 (Advanced Anomaly Segment Detection)

提供 CUSUM, EWMA, Ruptures (Change Point Detection) 三種演算法,
作為滑動窗口方法的補充/替代方案。

所有方法都輸出統一格式:
  List[Dict] 其中每個 Dict 包含 {"start": int, "end": int}
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)

# Ruptures 可選依賴
try:
    import ruptures as rpt

    HAS_RUPTURES = True
except ImportError:
    HAS_RUPTURES = False
    logger.info(
        "ruptures not installed, Change Point Detection will use fallback method"
    )


def cusum_detect(
    series: pd.Series,
    threshold: float = 5.0,
    drift: float = 0.5,
    min_segment_length: int = 5,
) -> List[Dict]:
    """
    CUSUM (Cumulative Sum) 異常區段偵測

    原理:
    - 追蹤數據相對均值的累積偏差
    - 當累積偏差超過 threshold 時,標記為異常區段開始
    - 對微小持續偏移 (Drift) 特別敏感 -- 這是 Z-Score 難以偵測的

    參數:
    - series: 輸入時間序列
    - threshold: CUSUM 報警閾值 (越小越敏感)
    - drift: 允許的漂移量 (k),通常設為 0.5 * delta (預期偏移量)
    - min_segment_length: 最短異常區段長度

    回傳:
    - List[Dict] with {"start", "end", "method": "CUSUM", "direction": "up"/"down"}
    """
    values = series.values.astype(float)
    n = len(values)
    if n < 10:
        return []

    mean = np.mean(values)
    std = np.std(values, ddof=1)

    if std == 0:
        return []

    # 正規化
    normalized = (values - mean) / std

    # CUSUM 累積和 (上方 + 下方)
    s_pos = np.zeros(n)  # 偵測向上偏移
    s_neg = np.zeros(n)  # 偵測向下偏移

    for i in range(1, n):
        s_pos[i] = max(0, s_pos[i - 1] + normalized[i] - drift)
        s_neg[i] = max(0, s_neg[i - 1] - normalized[i] - drift)

    # 找出超過 threshold 的區段
    regions = []

    # 偵測向上偏移的區段
    _extract_cusum_regions(s_pos, threshold, min_segment_length, "up", regions)

    # 偵測向下偏移的區段
    _extract_cusum_regions(s_neg, threshold, min_segment_length, "down", regions)

    return regions


def _extract_cusum_regions(
    cusum_values: np.ndarray,
    threshold: float,
    min_length: int,
    direction: str,
    regions: List[Dict],
):
    """從 CUSUM 累積和中提取超閾值區段"""
    n = len(cusum_values)
    in_alarm = False
    start_idx = 0

    for i in range(n):
        if cusum_values[i] > threshold and not in_alarm:
            start_idx = i
            in_alarm = True
        elif cusum_values[i] <= threshold * 0.5 and in_alarm:
            # 回到正常 (使用 hysteresis: 0.5 * threshold)
            if i - start_idx >= min_length:
                regions.append(
                    {
                        "start": start_idx,
                        "end": i - 1,
                        "method": "CUSUM",
                        "direction": direction,
                        "max_cusum": float(np.max(cusum_values[start_idx:i])),
                    }
                )
            in_alarm = False

    if in_alarm and n - start_idx >= min_length:
        regions.append(
            {
                "start": start_idx,
                "end": n - 1,
                "method": "CUSUM",
                "direction": direction,
                "max_cusum": float(np.max(cusum_values[start_idx:])),
            }
        )


def ewma_detect(
    series: pd.Series,
    lambda_param: float = 0.2,
    sigma_limit: float = 3.0,
    min_segment_length: int = 5,
) -> List[Dict]:
    """
    EWMA (Exponentially Weighted Moving Average) 異常區段偵測

    原理:
    - 使用指數加權移動平均追蹤數據的期望值
    - 當實際值偏離 EWMA 超過控制限時,標記為異常
    - 對平滑的 Level Shift 特別敏感

    參數:
    - series: 輸入時間序列
    - lambda_param: 平滑係數 (0-1), 越小對歷史越敏感, 越大對近期越敏感
    - sigma_limit: 控制限倍數 (類似 Z-Score 的 sigma 倍)
    - min_segment_length: 最短異常區段長度

    回傳:
    - List[Dict] with {"start", "end", "method": "EWMA", "deviation": float}
    """
    values = series.values.astype(float)
    n = len(values)
    if n < 10:
        return []

    mean = np.mean(values)
    std = np.std(values, ddof=1)

    if std == 0:
        return []

    # 計算 EWMA
    ewma = np.zeros(n)
    ewma[0] = mean  # 初始值設為全域均值

    for i in range(1, n):
        ewma[i] = lambda_param * values[i] + (1 - lambda_param) * ewma[i - 1]

    # 計算 EWMA 控制限 (隨時間增加到穩態)
    # UCL/LCL = mean +/- L * sigma * sqrt(lambda/(2-lambda) * (1-(1-lambda)^(2i)))
    control_widths = np.zeros(n)
    ratio = lambda_param / (2 - lambda_param)
    for i in range(n):
        factor = 1 - (1 - lambda_param) ** (2 * (i + 1))
        control_widths[i] = sigma_limit * std * np.sqrt(ratio * factor)

    # 計算偏差
    deviations = np.abs(ewma - mean)
    is_anomalous = deviations > control_widths

    # 提取異常區段
    regions = []
    in_anomaly = False
    start_idx = 0

    for i in range(n):
        if is_anomalous[i] and not in_anomaly:
            start_idx = i
            in_anomaly = True
        elif not is_anomalous[i] and in_anomaly:
            if i - start_idx >= min_segment_length:
                regions.append(
                    {
                        "start": start_idx,
                        "end": i - 1,
                        "method": "EWMA",
                        "deviation": float(np.max(deviations[start_idx:i])),
                        "ewma_at_peak": float(
                            ewma[start_idx + np.argmax(deviations[start_idx:i])]
                        ),
                    }
                )
            in_anomaly = False

    if in_anomaly and n - start_idx >= min_segment_length:
        regions.append(
            {
                "start": start_idx,
                "end": n - 1,
                "method": "EWMA",
                "deviation": float(np.max(deviations[start_idx:])),
                "ewma_at_peak": float(
                    ewma[start_idx + np.argmax(deviations[start_idx:])]
                ),
            }
        )

    return regions


def changepoint_detect(
    series: pd.Series,
    method: str = "pelt",
    model: str = "rbf",
    min_segment_size: int = 10,
    penalty_value: Optional[float] = None,
) -> List[Dict]:
    """
    Change Point Detection (變點偵測)

    如果有 ruptures 套件,使用 PELT/Binseg 算法。
    如果沒有,使用純 numpy 實現的簡化版 CUSUM-based 變點偵測。

    參數:
    - series: 輸入時間序列
    - method: "pelt" (最快) 或 "binseg" (較準)
    - model: "rbf" (均值+方差), "l2" (均值), "l1" (中位數)
    - min_segment_size: 最短區段長度
    - penalty_value: 懲罰值 (越大越少變點), None = 自動計算

    回傳:
    - List[Dict] with {"start", "end", "method": "CHANGEPOINT",
                        "mean_before": float, "mean_after": float, "shift": float}
    """
    values = series.values.astype(float)
    n = len(values)
    if n < 2 * min_segment_size:
        return []

    if HAS_RUPTURES:
        return _changepoint_ruptures(
            values, method, model, min_segment_size, penalty_value
        )
    else:
        return _changepoint_fallback(values, min_segment_size)


def _changepoint_ruptures(
    values: np.ndarray,
    method: str,
    model: str,
    min_size: int,
    penalty: Optional[float],
) -> List[Dict]:
    """使用 ruptures 套件做變點偵測"""
    n = len(values)

    # 自動懲罰值: 基於 BIC (Bayesian Information Criterion)
    if penalty is None:
        penalty = np.log(n) * np.var(values) * 2

    try:
        if method == "pelt":
            algo = rpt.Pelt(model=model, min_size=min_size).fit(values)
            breakpoints = algo.predict(pen=penalty)
        elif method == "binseg":
            # Binseg 需要指定最大變點數
            max_bkps = min(10, n // (min_size * 2))
            algo = rpt.Binseg(model=model, min_size=min_size).fit(values)
            breakpoints = algo.predict(n_bkps=max_bkps)
        else:
            algo = rpt.Window(model=model, min_size=min_size, width=min_size * 2).fit(
                values
            )
            breakpoints = algo.predict(pen=penalty)
    except Exception as e:
        logger.warning(f"Ruptures {method} failed: {e}, falling back to CUSUM-based")
        return _changepoint_fallback(values, min_size)

    # 轉換 breakpoints 為區段
    # breakpoints 格式: [100, 250, 500] 表示在 row 100, 250, 500 處有變點
    # 最後一個元素始終是 n (序列長度)
    return _breakpoints_to_segments(values, breakpoints, n)


def _changepoint_fallback(values: np.ndarray, min_size: int) -> List[Dict]:
    """
    純 numpy 實現的變點偵測 (不需要 ruptures)

    使用 Binary Segmentation 算法 + CUSUM 統計量:
    1. 在每個可能的分割點計算 CUSUM 統計量
    2. 找到最大 CUSUM 的點作為變點
    3. 遞迴地對子序列重複
    """
    n = len(values)
    if n < 2 * min_size:
        return []

    breakpoints = []
    _binary_segmentation(values, 0, n, min_size, breakpoints, max_depth=5)
    breakpoints.sort()
    breakpoints.append(n)

    return _breakpoints_to_segments(values, breakpoints, n)


def _binary_segmentation(
    values: np.ndarray,
    start: int,
    end: int,
    min_size: int,
    breakpoints: List[int],
    max_depth: int,
):
    """遞迴 Binary Segmentation"""
    if max_depth <= 0 or (end - start) < 2 * min_size:
        return

    # 在 [start+min_size, end-min_size] 範圍內找最佳分割點
    best_stat = 0
    best_pos = -1

    segment = values[start:end]
    seg_len = len(segment)
    total_var = np.var(segment)

    if total_var == 0:
        return

    for t in range(min_size, seg_len - min_size):
        left = segment[:t]
        right = segment[t:]

        # CUSUM test statistic: t * (n-t) / n * (mean_left - mean_right)^2
        left_mean = np.mean(left)
        right_mean = np.mean(right)
        stat = (t * (seg_len - t) / seg_len) * (left_mean - right_mean) ** 2

        if stat > best_stat:
            best_stat = stat
            best_pos = t

    # 判斷是否顯著 (使用 BIC 準則)
    threshold = 2 * np.log(seg_len) * total_var
    if best_stat > threshold and best_pos > 0:
        abs_pos = start + best_pos
        breakpoints.append(abs_pos)

        # 遞迴左右子序列
        _binary_segmentation(
            values, start, abs_pos, min_size, breakpoints, max_depth - 1
        )
        _binary_segmentation(values, abs_pos, end, min_size, breakpoints, max_depth - 1)


def _breakpoints_to_segments(
    values: np.ndarray, breakpoints: List[int], n: int
) -> List[Dict]:
    """將變點列表轉換為異常區段"""
    if len(breakpoints) <= 1:
        return []

    # 計算全域統計
    global_mean = np.mean(values)
    global_std = np.std(values, ddof=1)

    if global_std == 0:
        return []

    segments = []
    prev = 0

    for bp in breakpoints:
        if bp >= n:
            bp = n

        seg_values = values[prev:bp]
        if len(seg_values) < 3:
            prev = bp
            continue

        seg_mean = np.mean(seg_values)
        seg_std = np.std(seg_values, ddof=1)

        # 判斷此區段是否異常 (偏離全域均值 > 1.5 sigma, 或方差比異常)
        mean_shift = abs(seg_mean - global_mean) / (global_std + 1e-10)
        variance_ratio = seg_std / (global_std + 1e-10)

        is_anomalous = mean_shift > 1.5 or variance_ratio > 2.5 or variance_ratio < 0.1

        if is_anomalous:
            segments.append(
                {
                    "start": prev,
                    "end": bp - 1,
                    "method": "CHANGEPOINT",
                    "mean_shift": round(float(mean_shift), 3),
                    "variance_ratio": round(float(variance_ratio), 3),
                    "segment_mean": round(float(seg_mean), 4),
                    "global_mean": round(float(global_mean), 4),
                }
            )

        prev = bp

    return segments


def ensemble_detect(
    series: pd.Series,
    cusum_threshold: float = 5.0,
    ewma_lambda: float = 0.2,
    min_segment_length: int = 5,
) -> Dict:
    """
    集成偵測: 同時執行 CUSUM + EWMA + Change Point Detection,
    合併結果並標記共識區段 (多方法同時報警 = 更可信)。

    回傳:
    {
        "cusum_segments": [...],
        "ewma_segments": [...],
        "changepoint_segments": [...],
        "consensus_zones": [...],   # 多方法交集
        "all_segments": [...],      # 全部合併
    }
    """
    results = {
        "cusum_segments": [],
        "ewma_segments": [],
        "changepoint_segments": [],
        "consensus_zones": [],
        "all_segments": [],
        "methods_used": [],
    }

    # 執行 CUSUM
    try:
        cusum_segs = cusum_detect(
            series, threshold=cusum_threshold, min_segment_length=min_segment_length
        )
        results["cusum_segments"] = cusum_segs
        results["methods_used"].append("CUSUM")
    except Exception as e:
        logger.warning(f"CUSUM failed: {e}")

    # 執行 EWMA
    try:
        ewma_segs = ewma_detect(
            series, lambda_param=ewma_lambda, min_segment_length=min_segment_length
        )
        results["ewma_segments"] = ewma_segs
        results["methods_used"].append("EWMA")
    except Exception as e:
        logger.warning(f"EWMA failed: {e}")

    # 執行 Change Point Detection
    try:
        cp_segs = changepoint_detect(
            series, min_segment_size=max(10, min_segment_length)
        )
        results["changepoint_segments"] = cp_segs
        results["methods_used"].append("CHANGEPOINT")
    except Exception as e:
        logger.warning(f"ChangePoint failed: {e}")

    # 合併所有區段
    all_segs = (
        results["cusum_segments"]
        + results["ewma_segments"]
        + results["changepoint_segments"]
    )
    results["all_segments"] = all_segs

    # 計算共識區段 (至少 2 種方法同時報警的 row 範圍)
    if len(all_segs) > 0:
        results["consensus_zones"] = _find_consensus_zones(all_segs, n=len(series))

    return results


def _find_consensus_zones(
    segments: List[Dict], n: int, min_methods: int = 2
) -> List[Dict]:
    """找出多方法交集的共識區段"""
    if not segments:
        return []

    # 建立每個 row 的方法票數
    method_votes = {}  # row_idx -> set of methods
    for seg in segments:
        method = seg.get("method", "UNKNOWN")
        for r in range(seg["start"], seg["end"] + 1):
            if r not in method_votes:
                method_votes[r] = set()
            method_votes[r].add(method)

    # 找出 >= min_methods 的連續區段
    consensus_rows = sorted(
        [r for r, methods in method_votes.items() if len(methods) >= min_methods]
    )

    if not consensus_rows:
        return []

    # 合併連續 row 為區段
    zones = []
    start = consensus_rows[0]
    prev = consensus_rows[0]
    methods_in_zone = method_votes[start].copy()

    for r in consensus_rows[1:]:
        if r <= prev + 2:  # 允許 2 row 間隔
            prev = r
            methods_in_zone |= method_votes[r]
        else:
            zones.append(
                {
                    "start": start,
                    "end": prev,
                    "zone_range": f"Row {start}-{prev}",
                    "length": prev - start + 1,
                    "methods_agreed": sorted(list(methods_in_zone)),
                    "consensus_count": len(methods_in_zone),
                }
            )
            start = r
            prev = r
            methods_in_zone = method_votes[r].copy()

    zones.append(
        {
            "start": start,
            "end": prev,
            "zone_range": f"Row {start}-{prev}",
            "length": prev - start + 1,
            "methods_agreed": sorted(list(methods_in_zone)),
            "consensus_count": len(methods_in_zone),
        }
    )

    # 按長度排序 (越長越嚴重)
    zones.sort(key=lambda x: x["length"], reverse=True)
    return zones
