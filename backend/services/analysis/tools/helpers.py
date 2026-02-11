from .base import AnalysisTool
from typing import Dict, Any


class SuggestNextAnalysisTool(AnalysisTool):
    """根據歷史步驟動態推薦下一步分析"""

    @property
    def name(self) -> str:
        return "suggest_next_analysis"

    @property
    def description(self) -> str:
        return "基於已執行的分析步驟，動態推薦下一步可探索的方向。"

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        current_focus = params.get("current_focus", "")
        history = params.get("history", [])

        # 收集已使用的工具
        used_tools = set()
        if isinstance(history, list):
            for h in history:
                if isinstance(h, dict):
                    used_tools.add(h.get("tool", ""))

        suggestions = []

        # 根據已執行的工具，推薦尚未執行的互補工具
        tool_recommendations = {
            "compare_data_segments": {
                "condition": "compare_data_segments" not in used_tools,
                "text": "執行區間對比分析，量化異常區間與基準的差異",
            },
            "hotelling_t2_analysis": {
                "condition": "hotelling_t2_analysis" not in used_tools,
                "text": "執行 Hotelling T2 多維度異常偵測，找出系統性組合偏移",
            },
            "distribution_shift_test": {
                "condition": "distribution_shift_test" not in used_tools
                and (
                    "compare_data_segments" in used_tools
                    or "hotelling_t2_analysis" in used_tools
                ),
                "text": "對已識別的可疑參數執行 K-S 分佈檢定，驗證分佈形狀是否改變",
            },
            "causal_relationship_analysis": {
                "condition": "causal_relationship_analysis" not in used_tools
                and len(used_tools) >= 2,
                "text": "執行 Granger 因果檢定，識別哪個參數最先變化（領頭羊分析）",
            },
            "analyze_feature_importance": {
                "condition": "analyze_feature_importance" not in used_tools
                and ("hotelling_t2_analysis" in used_tools),
                "text": "執行因素貢獻度分析，量化各參數對異常的影響程度排序",
            },
            "find_temporal_patterns": {
                "condition": "find_temporal_patterns" not in used_tools
                and current_focus,
                "text": f"對 {current_focus} 進行 CUSUM 趨勢分析，偵測製程漂移變化點",
            },
        }

        for tool_name, rec in tool_recommendations.items():
            if rec["condition"]:
                suggestions.append(rec["text"])

        # 如果有聚焦參數但功能建議不多，補充通用建議
        if current_focus and len(suggestions) < 2:
            if "detect_outliers" not in used_tools:
                suggestions.append(f"對 {current_focus} 執行 IQR 異常值偵測")
            if "analyze_distribution" not in used_tools:
                suggestions.append(f"分析 {current_focus} 的數據分佈形態")

        # 兜底
        if not suggestions:
            suggestions.append("當前分析已較為充分，建議進行最終結案摘要。")

        return {
            "suggestions": suggestions[:5],
            "used_tools_count": len(used_tools),
            "used_tools": list(used_tools),
        }


class ExplainResultTool(AnalysisTool):
    """解釋統計術語 (擴展版)"""

    @property
    def name(self) -> str:
        return "explain_result"

    @property
    def description(self) -> str:
        return "為非技術用戶解釋統計結果（如：什麼是 P-value，什麼是相關係數，什麼是 T2 值）。"

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        term = params.get("term", "")

        # 擴充的術語庫
        definitions = {
            # 基礎統計
            "correlation": "相關係數 (Correlation) 表示兩個變數變化的同步程度。1 表示完全正相關，-1 表示完全負相關，0 表示無關。工業應用中，|r| > 0.7 通常被視為強相關。",
            "std": "標準差 (Standard Deviation) 反映數據的離散程度。數值越大，代表數據波動越劇烈。在製程管控中，通常以 ±3σ 作為管控界限。",
            "mean": "平均值 (Mean)，所有數據點的算術平均。是最基本的集中趨勢指標。但容易受極端值影響，建議配合中位數一起參考。",
            "median": "中位數 (Median)，將數據排序後位於正中間的值。相較平均值更不受極端值影響，適合用於偏態分佈的數據。",
            "variance": "變異數 (Variance) 是標準差的平方，衡量數據離散程度的另一種方式。F 檢定即是比較兩組數據的變異數是否有顯著差異。",
            # 異常偵測
            "outlier": "異常值 (Outlier) 是指顯著偏離其他數據點的數值，可能代表設備故障、配方錯誤或特殊事件。常用 IQR (四分位距) 或 Z-Score 方法判定。",
            "z-score": "Z-Score (標準分數) 表示一個數據點偏離平均值幾個標準差。|Z| > 2 表示偏離較大，|Z| > 3 通常被視為異常值。",
            "iqr": "四分位距 (Interquartile Range)，即 Q3 - Q1。超過 Q3 + 1.5×IQR 或低於 Q1 - 1.5×IQR 的點被視為異常值。比 Z-Score 對偏態數據更穩健。",
            # 假設檢定
            "p-value": "P-value (顯著性水準) 用於判斷結果是否顯著。通常小於 0.05 代表具有統計意義（即觀察到的差異不太可能是隨機造成的）。p 越小，差異越顯著。",
            "ks-test": "Kolmogorov-Smirnov 檢定 (K-S Test) 用於比較兩組數據的分佈是否相同。p < 0.05 表示兩組數據的分佈形狀有顯著差異。",
            "f-test": "F 檢定用於比較兩組數據的變異數是否相同。若 p < 0.05，表示兩組數據的波動程度有顯著差異，常用於判斷製程穩定性是否改變。",
            "granger": "Granger 因果檢定用於判斷一個時間序列是否能預測另一個。如果 A Granger-causes B，表示 A 的歷史值能幫助預測 B 的未來值。注意：這是統計因果，不完全等同於物理因果。",
            # 多維度分析
            "t2": "Hotelling's T2 統計量是多變量版的 t 檢定。它衡量一個觀測點在多個參數上同時偏離基準的程度。T2 值越大，表示組合異常越嚴重。",
            "hotelling": "Hotelling's T2 統計量是多變量版的 t 檢定。它衡量一個觀測點在多個參數上同時偏離基準的程度。T2 值越大，表示組合異常越嚴重。",
            "pca": "主成分分析 (PCA) 是一種降維技術，將多個相關的參數壓縮成少數幾個不相關的「主成分」。在工業診斷中，PCA 能幫助識別哪些參數的組合變化最能解釋整體異常。",
            "contribution": "貢獻度 (Contribution) 表示某個參數對整體異常的影響程度。在 T2 分析中，貢獻度高的參數是導致該筆數據偏離正常的主要原因。",
            "isolation_forest": "孤立森林 (Isolation Forest) 是一種基於樹的異常偵測算法。它的原理是異常點比正常點更容易被「隔離」（需要更少的分割步驟）。適合高維度數據。",
            # 分佈相關
            "distribution": "分佈 (Distribution) 描述數據出現的頻率概況。常見有常態分佈（鐘型曲線）、偏態分佈、雙峰分佈等。分佈形狀的改變通常意味著製程條件發生了變化。",
            "skewness": "偏度 (Skewness) 衡量數據分佈的對稱性。正偏表示右尾較長（大值偏多），負偏表示左尾較長（小值偏多）。|偏度| > 1 通常被視為明顯偏態。",
            "kurtosis": "峰度 (Kurtosis) 衡量數據分佈的尖銳程度。高峰度表示數據集中但極端值也多，低峰度表示數據分散較均勻。",
            # 趨勢分析
            "cusum": "CUSUM (累積和控制圖) 是 SPC 中偵測製程持續性微小漂移的標準工具。它累積每個數據點與基準的偏差，當累積值超過決策閾值時，判定發生了製程漂移。",
            "trend": "趨勢 (Trend) 指數據隨時間的系統性變化方向。上升趨勢 (Increasing) 表示數值逐漸增大，下降趨勢 (Decreasing) 表示逐漸減小，平穩 (Stable) 表示無明顯方向。",
            "spc": "統計製程管制 (Statistical Process Control)，利用統計方法監控製程的穩定性。核心工具包括管制圖 (Control Chart)、CUSUM 圖等。",
            # 相關性
            "feature_importance": "因素重要度排序，通常由 XGBoost 或隨機森林算法計算。分數越高，表示該參數對目標變數的預測能力越強。",
            "lof": "局部離群因子 (LOF) 是基於密度的異常偵測方法。它比較一個點與其鄰居的局部密度。LOF > 1 表示該點的密度低於其鄰居，可能為離群點。",
        }

        term_clean = term.lower().strip()
        desc = definitions.get(term_clean)

        if not desc:
            # 模糊匹配：任何定義的 key 包含在搜索詞中，或搜索詞包含在 key 中
            for k, v in definitions.items():
                if k in term_clean or term_clean in k:
                    desc = v
                    break

        if not desc:
            # 二次模糊：檢查中文別名
            chinese_aliases = {
                "相關係數": "correlation",
                "標準差": "std",
                "平均值": "mean",
                "中位數": "median",
                "異常值": "outlier",
                "顯著性": "p-value",
                "分佈": "distribution",
                "主成分": "pca",
                "貢獻度": "contribution",
                "趨勢": "trend",
                "因果": "granger",
                "偏度": "skewness",
                "峰度": "kurtosis",
                "管制圖": "spc",
                "累積和": "cusum",
                "孤立森林": "isolation_forest",
                "局部離群": "lof",
            }
            for cn, en in chinese_aliases.items():
                if cn in term:
                    desc = definitions.get(en)
                    if desc:
                        break

        return {
            "term": term,
            "explanation": desc
            or f"暫無「{term}」的內建解釋。建議諮詢領域專家或查閱相關統計學教材。",
        }
