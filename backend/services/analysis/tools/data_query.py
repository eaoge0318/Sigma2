from typing import Dict, Any, List, Optional
import pandas as pd
from .base import AnalysisTool


class GetParameterListTool(AnalysisTool):
    """獲取數據文件中的所有參數列表"""

    @property
    def name(self) -> str:
        return "get_parameter_list"

    @property
    def description(self) -> str:
        return "獲取所有可用參數的列表，包含其中文描述（如果有）。當用戶詢問「有哪些欄位」或「有哪些數據」時使用。"

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        summary = self.analysis_service.load_summary(session_id, file_id)

        if not summary:
            return {"error": "File not found or not indexed"}

        return {
            "parameters": summary.get("parameters", []),
            "total_count": summary.get("total_columns", 0),
            "mappings": summary.get("mappings", {}),
        }


class GetDataOverviewTool(AnalysisTool):
    """獲取數據總覽（行數、列數、分類統計）"""

    @property
    def name(self) -> str:
        return "get_data_overview"

    @property
    def description(self) -> str:
        return "獲取數據的整體概況，包含數據量、參數分類統計等。"

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        summary = self.analysis_service.load_summary(session_id, file_id)

        if not summary:
            return {"error": "File analysis not found"}

        # 構建更友好的分類統計
        categories = summary.get("categories", {})
        cat_stats = {k: len(v) for k, v in categories.items()}

        return {
            "total_rows": summary.get("total_rows", 0),
            "total_columns": summary.get("total_columns", 0),
            "category_stats": cat_stats,
            "time_range": "N/A",  # TODO: 若有時間欄位可在此擴充
        }


class SearchParametersTool(AnalysisTool):
    """根據關鍵字或概念搜索參數"""

    @property
    def name(self) -> str:
        return "search_parameters_by_concept"

    @property
    def description(self) -> str:
        return (
            "根據關鍵字（如「溫度」、「壓力」）搜索相關的參數欄位。支持中英文模糊匹配。"
        )

    @property
    def required_params(self) -> List[str]:
        return ["file_id", "concept"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        concept = params.get("concept", "").strip()

        if not concept:
            return {"error": "Concept keyword is required"}

        # 1. 嘗試從語義索引查找
        semantic_index = self.analysis_service.load_semantic_index(session_id, file_id)
        if concept in semantic_index:
            return {
                "matches": semantic_index[concept],
                "source": "semantic_index",
                "concept": concept,
            }

        # 2. 若索引無匹配，進行模糊搜索
        summary = self.analysis_service.load_summary(session_id, file_id)
        all_params = summary.get("parameters", [])
        mappings = summary.get("mappings", {})

        matches = []
        concept_upper = concept.upper()

        for param in all_params:
            # 檢查參數代碼
            if concept_upper in param.upper():
                matches.append(param)
                continue

            # 檢查中文名稱
            if param in mappings:
                if concept_upper in mappings[param].upper():
                    matches.append(param)

        return {
            "matches": matches,
            "source": "fuzzy_search",
            "concept": concept,
            "total_matches": len(matches),
        }


class GetTimeSeriesDataTool(AnalysisTool):
    """獲取特定參數的時間序列數據（支持降採樣）"""

    @property
    def name(self) -> str:
        return "get_time_series_data"

    @property
    def description(self) -> str:
        return "獲取指定參數的詳細數據。當需要繪製折線圖或查看趨勢時使用。"

    @property
    def required_params(self) -> List[str]:
        return ["file_id", "parameters"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        target_params = params.get("parameters", [])
        limit = params.get("limit", 2000)  # 預設限制 2000 點以防前端卡死

        if isinstance(target_params, str):
            target_params = [target_params]

        summary = self.analysis_service.load_summary(session_id, file_id)
        if not summary:
            return {"error": "File not found"}

        filename = summary["filename"]
        csv_path = self.analysis_service.base_dir / session_id / "uploads" / filename

        try:
            # 優化讀取：只讀取需要的欄位
            df = pd.read_csv(
                csv_path, usecols=lambda c: c in target_params or "TIME" in c.upper()
            )

            # 簡單降採樣邏輯
            if len(df) > limit:
                step = len(df) // limit
                df = df.iloc[::step]

            # 轉換為前端友好的格式
            result = df.to_dict(orient="records")
            return {
                "data": result,
                "parameters": target_params,
                "total_points": len(df),
            }
        except Exception as e:
            return {"error": f"Failed to load data: {str(e)}"}
