"""
多變量異常區段診斷工具 (Zone Diagnosis)

串聯既有工具:
  1. GlobalAnomalySegmentScanner  → 找出合併後的 Event Zone (merged_problem_zones)
  2. HotellingT2AnalysisTool      → 對每個 Zone 做多變量貢獻度分析

輸出: 以 Event Zone 為單位的根因報告,
      包含涉及參數、T2 貢獻度排名、解讀文字
"""

import logging
from typing import Dict, Any, List

from .base import AnalysisTool
from .anomaly_classifier import GlobalAnomalySegmentScanner
from .advanced_ai import HotellingT2AnalysisTool

logger = logging.getLogger(__name__)


class ZoneDiagnosisTool(AnalysisTool):
    """多變量異常區段診斷 — 自動串聯區段掃描 + T2 貢獻度分析"""

    @property
    def name(self) -> str:
        return "zone_diagnosis"

    @property
    def description(self) -> str:
        return (
            "【高階整合工具】自動掃描全域異常區段,合併多參數共變的 Event Zone,"
            "再對每個 Zone 執行 Hotelling T2 貢獻度分析,"
            "產出『哪個區段出問題、哪些參數主導異常』的根因報告。"
            "適合處理多參數同時偏移的場景。"
        )

    @property
    def required_params(self) -> List[str]:
        return ["file_id"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        try:
            file_id = params.get("file_id")
            # 使用者可選: 最多分析幾個 zone (預設 5)
            max_zones = int(params.get("max_zones", 5))
            # 使用者可選: 至少幾個參數才做 T2 分析 (預設 2)
            min_params = int(params.get("min_affected_params", 2))

            # ============================================================
            # Phase 1: 調用 GlobalAnomalySegmentScanner 取得異常區段
            # ============================================================
            scanner = GlobalAnomalySegmentScanner(self.analysis_service)
            scan_result = scanner.execute({"file_id": file_id}, session_id)

            if scan_result.get("status") == "ERROR":
                return scan_result

            merged_zones = scan_result.get("merged_problem_zones", [])
            if not merged_zones:
                return {
                    "status": "OK",
                    "event_zones": [],
                    "total_zones_found": 0,
                    "interpretation": (
                        "全域掃描完成,未發現多參數共變的異常區段。"
                        "所有參數在正常範圍內,或異常僅為單一參數獨立事件。"
                    ),
                    "scan_summary": scan_result.get("engineering_summary", ""),
                }

            # 過濾: 只保留多參數共變的 zone (affected_params_count >= min_params)
            multi_param_zones = [
                z
                for z in merged_zones
                if z.get("affected_params_count", 1) >= min_params
            ]

            # 排序: 按 (涉及參數數 * 嚴重度) 降序, 多參數共變的嚴重問題排最前
            multi_param_zones.sort(
                key=lambda z: (
                    z.get("affected_params_count", 1) * z.get("max_severity", 1)
                ),
                reverse=True,
            )

            # 限制分析數量
            zones_to_analyze = multi_param_zones[:max_zones]

            if not zones_to_analyze:
                return {
                    "status": "OK",
                    "event_zones": [],
                    "total_zones_found": len(merged_zones),
                    "multi_param_zones_found": 0,
                    "interpretation": (
                        f"全域掃描發現 {len(merged_zones)} 個異常區段,"
                        f"但均為單一參數獨立事件 (少於 {min_params} 個參數共變)。"
                        "建議使用 scan_anomaly_segments 或 hotelling_t2_analysis 單獨分析。"
                    ),
                    "scan_summary": scan_result.get("engineering_summary", ""),
                }

            # ============================================================
            # Phase 2: 對每個 Event Zone 做 Hotelling T2 貢獻度分析
            # ============================================================
            t2_tool = HotellingT2AnalysisTool(self.analysis_service)
            event_zones = []

            for zone_idx, zone in enumerate(zones_to_analyze):
                zone_start = zone.get("zone_start", 0)
                zone_end = zone.get("zone_end", 0)
                zone_range_str = zone.get("zone_range", f"Row {zone_start}-{zone_end}")
                zone_params = zone.get("parameters", [])
                zone_types = zone.get("types", [])
                zone_severity = zone.get("max_severity", 0)

                # 呼叫 Hotelling T2, 鎖定此 zone 的 row 範圍
                t2_params = {
                    "file_id": file_id,
                    "parameters": "all",  # 分析所有參數的貢獻
                    "target_segments": f"{zone_start}-{zone_end}",
                }

                t2_result = t2_tool.execute(t2_params, session_id)

                # 提取貢獻度排名
                top_contributors = []
                t2_max = 0
                t2_conclusion = ""

                if "error" not in t2_result:
                    raw_contributions = t2_result.get("top_contributions", [])
                    t2_max = t2_result.get("max_t2_value", 0)
                    t2_conclusion = t2_result.get("conclusion", "")

                    # 取前 5 名貢獻者
                    for c in raw_contributions[:5]:
                        top_contributors.append(
                            {
                                "parameter": c.get("parameter", "?"),
                                "contribution": round(c.get("contribution", 0), 4),
                                "rank": c.get("rank", 0),
                                # 標記此參數是否也在 scanner 的 zone_params 中
                                "also_flagged_by_scanner": c.get("parameter", "")
                                in zone_params,
                            }
                        )
                else:
                    t2_conclusion = f"T2 分析失敗: {t2_result.get('error', '未知錯誤')}"

                # 組裝 Event Zone 報告
                # 生成人類可讀的解讀
                if top_contributors:
                    top1 = top_contributors[0]
                    interpretation = (
                        f"{zone_range_str} 的異常由 {top1['parameter']}"
                        f" (貢獻度 {top1['contribution']:.2f}) 主導,"
                        f" 共涉及 {len(zone_params)} 個參數同時偏移。"
                    )
                    if len(top_contributors) >= 2:
                        top2 = top_contributors[1]
                        interpretation += (
                            f" 其次為 {top2['parameter']}"
                            f" (貢獻度 {top2['contribution']:.2f})。"
                        )
                    # 標注異常類型
                    if zone_types:
                        interpretation += f" 異常模式: {', '.join(zone_types)}。"
                else:
                    interpretation = (
                        f"{zone_range_str} 涉及 {len(zone_params)} 個參數,"
                        " T2 分析未能取得貢獻度。"
                    )

                event_zone = {
                    "zone_id": zone_idx + 1,
                    "zone_range": zone_range_str,
                    "zone_start": zone_start,
                    "zone_end": zone_end,
                    "affected_params_count": len(zone_params),
                    "affected_parameters": zone_params[:10],  # 最多列 10 個
                    "anomaly_types": zone_types,
                    "max_severity": round(zone_severity, 2),
                    "t2_max_value": round(t2_max, 2),
                    "top_contributors": top_contributors,
                    "t2_conclusion": t2_conclusion,
                    "interpretation": interpretation,
                }
                event_zones.append(event_zone)

            # ============================================================
            # Phase 3: 組裝最終報告
            # ============================================================
            # 全域摘要
            total_affected_params = set()
            for ez in event_zones:
                total_affected_params.update(ez.get("affected_parameters", []))

            overall_interpretation = (
                f"共發現 {len(event_zones)} 個多參數共變的 Event Zone"
                f" (涉及 {len(total_affected_params)} 個不重複參數)。"
            )
            if event_zones:
                top_zone = event_zones[0]
                overall_interpretation += (
                    f" 最嚴重的區段為 {top_zone['zone_range']}"
                    f" ({top_zone['affected_params_count']} 個參數,"
                    f" 嚴重度 {top_zone['max_severity']})。"
                )

            return {
                "status": "OK",
                "total_zones_found": len(merged_zones),
                "multi_param_zones_found": len(multi_param_zones),
                "zones_analyzed": len(event_zones),
                "event_zones": event_zones,
                "overall_interpretation": overall_interpretation,
                "scan_summary": scan_result.get("engineering_summary", ""),
            }

        except Exception as e:
            logger.error(f"ZoneDiagnosis error: {e}", exc_info=True)
            return {"status": "ERROR", "message": str(e)}
