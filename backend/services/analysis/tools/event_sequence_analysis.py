"""
事件序列關聯分析工具 (Event Sequence Association)
- 偵測上游參數的離散操作事件 (突變/狀態切換)
- 檢驗這些事件是否在目標參數異常前頻繁出現
- 輸出事件→異常的關聯強度和時序關係
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List
from .base import AnalysisTool
import logging

logger = logging.getLogger(__name__)


class EventSequenceAnalysisTool(AnalysisTool):
    """事件序列關聯: 偵測操作事件與目標異常的時序因果關係"""

    @property
    def name(self) -> str:
        return "event_sequence_analysis"

    @property
    def description(self) -> str:
        return (
            "事件序列關聯分析: 自動偵測所有參數中的離散操作事件 "
            "(突變/狀態切換/閥門開關), 檢驗這些事件是否在目標參數異常前 "
            "頻繁出現, 找出最可能的前導事件。"
        )

    @property
    def required_params(self) -> List[str]:
        return ["file_id", "target"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        try:
            file_id = params.get("file_id")
            target = params.get("target")
            lookback = int(params.get("lookback_window", 10))
            event_threshold = float(params.get("event_threshold", 3.0))
            top_k = int(params.get("top_k", 10))

            # Load data
            summary = self.analysis_service.load_summary(session_id, file_id)
            if not summary:
                return {"status": "ERROR", "message": "No summary data available"}
            filename = summary["filename"]
            csv_path = (
                self.analysis_service.base_dir / session_id / "uploads" / filename
            )
            df = pd.read_csv(csv_path)

            if target not in df.columns:
                return {"status": "ERROR", "message": f"Target '{target}' not found"}

            numeric_df = df.select_dtypes(include=[np.number]).copy()
            if target not in numeric_df.columns:
                return {
                    "status": "ERROR",
                    "message": f"Target '{target}' is not numeric",
                }

            target_series = numeric_df[target].fillna(method="ffill")

            # Step 1: Detect target anomaly positions
            target_diff = target_series.diff().abs()
            target_std = target_diff.std()
            if target_std == 0:
                return {
                    "status": "WARNING",
                    "message": f"Target '{target}' has no variation",
                }

            # Anomaly = points where target changes dramatically (> 2 std of diff)
            target_anomaly_mask = target_diff > (target_diff.mean() + 2 * target_std)
            anomaly_indices = target_anomaly_mask[target_anomaly_mask].index.tolist()

            if len(anomaly_indices) < 3:
                return {
                    "status": "WARNING",
                    "message": f"Only {len(anomaly_indices)} anomaly events detected in target. Need at least 3.",
                    "anomaly_count": len(anomaly_indices),
                }

            # Step 2: Detect events in all other parameters
            other_cols = [c for c in numeric_df.columns if c != target]
            event_associations = []

            for col in other_cols:
                col_series = numeric_df[col].fillna(method="ffill")
                col_diff = col_series.diff().abs()
                col_std = col_diff.std()

                if col_std == 0 or col_diff.mean() == 0:
                    continue

                # Event = abrupt change > event_threshold * std
                event_mask = col_diff > (col_diff.mean() + event_threshold * col_std)
                event_indices = set(event_mask[event_mask].index.tolist())

                if len(event_indices) < 2:
                    continue

                # Step 3: Count how many target anomalies have a preceding event
                # (within lookback_window rows before the anomaly)
                hits = 0
                hit_lags = []
                for anomaly_idx in anomaly_indices:
                    window_start = max(0, anomaly_idx - lookback)
                    preceding_events = [
                        e for e in event_indices if window_start <= e < anomaly_idx
                    ]
                    if preceding_events:
                        hits += 1
                        # Record the lag (distance from event to anomaly)
                        closest_event = max(preceding_events)
                        hit_lags.append(anomaly_idx - closest_event)

                # Association strength: hit_rate (proportion of anomalies preceded by event)
                hit_rate = hits / len(anomaly_indices) if anomaly_indices else 0

                # Baseline: how often would random points have a preceding event?
                total_events = len(event_indices)
                expected_rate = min(1.0, (total_events * lookback) / len(numeric_df))

                # Lift: hit_rate / expected_rate (> 1 means association)
                lift = hit_rate / expected_rate if expected_rate > 0 else 0

                if hit_rate >= 0.3:  # At least 30% of anomalies preceded
                    avg_lag = np.mean(hit_lags) if hit_lags else 0
                    event_associations.append(
                        {
                            "upstream_parameter": col,
                            "event_count": total_events,
                            "anomaly_preceded_count": hits,
                            "total_anomalies": len(anomaly_indices),
                            "hit_rate": round(float(hit_rate), 4),
                            "lift": round(float(lift), 2),
                            "avg_lag_rows": round(float(avg_lag), 1),
                            "interpretation": self._interpret_single(
                                col, hit_rate, lift, avg_lag
                            ),
                        }
                    )

            # Sort by lift (strongest association first)
            event_associations.sort(key=lambda x: x["lift"], reverse=True)
            top_associations = event_associations[:top_k]

            return {
                "status": "OK",
                "target": target,
                "total_anomalies_detected": len(anomaly_indices),
                "lookback_window": lookback,
                "parameters_scanned": len(other_cols),
                "associations_found": len(event_associations),
                "top_associations": top_associations,
                "interpretation": self._interpret_all(target, top_associations),
            }

        except Exception as e:
            logger.error(f"EventSequenceAnalysis error: {e}")
            return {"status": "ERROR", "message": str(e)}

    def _interpret_single(self, col, hit_rate, lift, avg_lag) -> str:
        strength = "強" if lift > 3 else "中等" if lift > 1.5 else "弱"
        return (
            f"{col} 的突變事件在 {hit_rate:.0%} 的目標異常前出現 "
            f"(Lift={lift:.1f}, {strength}關聯), "
            f"平均前導 {avg_lag:.0f} 筆"
        )

    def _interpret_all(self, target, associations) -> str:
        if not associations:
            return f"未發現任何上游參數事件與 {target} 異常有顯著時序關聯。"

        lines = [f"與 {target} 異常有時序關聯的上游事件:"]
        for i, a in enumerate(associations[:5]):
            lines.append(
                f"  {i + 1}. {a['upstream_parameter']}: "
                f"Hit Rate={a['hit_rate']:.0%}, Lift={a['lift']:.1f}, "
                f"平均前導 {a['avg_lag_rows']:.0f} 筆"
            )
        if associations:
            top = associations[0]
            lines.append(
                f"\n最強關聯: {top['upstream_parameter']} 的操作事件 "
                f"在 {top['hit_rate']:.0%} 的 {target} 異常前約 "
                f"{top['avg_lag_rows']:.0f} 筆出現"
            )
        return "\n".join(lines)
