from typing import Dict, List, Optional


class IndexHelper:
    """
    索引構建輔助類別
    負責構建語義索引與關鍵字匹配
    """

    @staticmethod
    def build_semantic_index(
        columns: List[str], mapping: Dict[str, str] = None
    ) -> Dict[str, List[str]]:
        """
        構建語義索引：概念 -> 參數列表
        支持中英文關鍵詞搜索，並整合映射表內容
        """
        # 關鍵詞映射表 (基礎內建 - 僅保留通用工業術語)
        keyword_map = {
            "溫度": ["TEMP", "HEAT", "溫", "熱"],
            "張力": ["TENSION", "PULL", "STRESS", "張", "拉"],
            "濕度": ["MOISTURE", "HUMIDITY", "WET", "濕", "水"],
            "速度": ["SPEED", "VELOCITY", "RPM", "速"],
            "壓力": ["PRESSURE", "PRESS", "壓"],
            "品質": ["QUALITY", "GRADE", "METROLOGY", "品", "質"],
            "流量": ["FLOW", "RATE", "流"],
            "濃度": ["CONCENTRATION", "CONSISTENCY", "濃"],
            "電流": ["CURRENT", "AMP", "電"],
            "電壓": ["VOLTAGE", "VOLT", "壓"],
        }

        semantic_index = {}
        for concept, keywords in keyword_map.items():
            matched = []
            for col in columns:
                col_upper = col.upper()
                # 獲取映射名稱 (如存在)
                display_name = mapping.get(col, "").upper() if mapping else ""

                for kw in keywords:
                    kw_up = kw.upper()
                    # 同時檢查原始代碼與映射名稱
                    if kw_up in col_upper or (display_name and kw_up in display_name):
                        matched.append(col)
                        break
            if matched:
                semantic_index[concept] = matched

        # 額外擴展：如果映射表中有明顯的工業關鍵字，也加入索引
        if mapping:
            for col, name in mapping.items():
                if col not in columns:
                    continue
                # 簡單分詞或全字匹配
                for concept in keyword_map.keys():
                    if concept in name and col not in semantic_index.get(concept, []):
                        if concept not in semantic_index:
                            semantic_index[concept] = []
                        semantic_index[concept].append(col)

        return semantic_index
