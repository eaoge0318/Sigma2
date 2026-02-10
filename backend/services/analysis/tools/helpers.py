from .base import AnalysisTool
from typing import Dict, Any, List


class SuggestNextAnalysisTool(AnalysisTool):
    """根據當前結果推薦下一步分析"""

    @property
    def name(self) -> str:
        return "suggest_next_analysis"

    @property
    def description(self) -> str:
        return "基於當前的分析發現，推薦用戶可以進一步探索的方向。"

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        # 這是一個輕量級工具，主要用於構造提示詞上下文
        current_focus = params.get("current_focus", "")

        suggestions = []
        if current_focus:
            suggestions.append(f"分析 {current_focus} 的時間趨勢")
            suggestions.append(f"尋找影響 {current_focus} 的相關因子")
            suggestions.append(f"檢查 {current_focus} 的異常分佈")
        else:
            suggestions.append("探索數據中的主要異常值")
            suggestions.append("分析關鍵參數的相關性")

        return {"suggestions": suggestions}


class ExplainResultTool(AnalysisTool):
    """解釋統計術語"""

    @property
    def name(self) -> str:
        return "explain_result"

    @property
    def description(self) -> str:
        return "為非技術用戶解釋統計結果（如：什麼是 P-value，什麼是相關係數）。"

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        term = params.get("term", "")
        # 簡單的查找表
        definitions = {
            "correlation": "相關係數 (Correlation) 表示兩個變數變化的同步程度。1 表示完全正相關，-1 表示完全負相關，0 表示無關。",
            "std": "標準差 (Standard Deviation) 反映數據的離散程度。數值越大，代表數據波動越劇烈。",
            "outlier": "異常值 (Outlier) 是指顯著偏離其他數據點的數值，可能代表故障或特殊事件。",
            "p-value": "P-value 用於判斷結果是否顯著。通常小於 0.05 代表具有統計意義。",
            "distribution": "分佈 (Distribution) 描述數據出現的頻率概況。",
        }

        term_clean = term.lower().strip()
        desc = definitions.get(term_clean)

        if not desc:
            # 模糊匹配
            for k, v in definitions.items():
                if k in term_clean:
                    desc = v
                    break

        return {"term": term, "explanation": desc or "暫無該術語的內建解釋。"}
