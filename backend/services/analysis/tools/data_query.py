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

        quality_stats = summary.get("quality_stats", {})

        # Double Injection (雙重植入): 強制在工具輸出夾帶「品質警訊」
        quality_alerts = {}
        if quality_stats.get("null_column_count", 0) > 0:
            quality_alerts["high_missing_rate_columns"] = quality_stats.get(
                "null_columns_preview", []
            )
        if quality_stats.get("sparse_column_count", 0) > 0:
            quality_alerts["sparse_columns"] = quality_stats.get(
                "sparse_columns_preview", []
            )
        if quality_stats.get("constant_column_count", 0) > 0:
            quality_alerts["constant_columns_sample"] = quality_stats.get(
                "constant_columns_preview", []
            )

        return {
            "parameters": summary.get("parameters", []),
            "total_count": summary.get("total_columns", 0),
            "mappings": summary.get("mappings", {}),
            "quality_alerts (ATTENTION!)": quality_alerts,  # 強制 AI 注意這裡
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
            # 獲取 CSV 實際的所有欄位名
            full_df_sample = pd.read_csv(csv_path, nrows=0)
            all_csv_columns = full_df_sample.columns.tolist()

            # 進行大小寫不敏感的欄位匹配
            matched_columns = []
            for target in target_params:
                target_upper = target.upper()
                for csv_col in all_csv_columns:
                    if csv_col.upper() == target_upper:
                        matched_columns.append(csv_col)
                        break

            # 強制包含時間欄位 (僅限標準時間格式)
            time_axis_keywords = ["TIME", "TIMESTAMP", "DATE"]
            time_cols = [
                c
                for c in all_csv_columns
                if any(kw in c.upper() for kw in time_axis_keywords)
            ]

            cols_to_read = list(set(matched_columns + time_cols))

            if not matched_columns:
                return {
                    "error": f"找不到指定的參數: {', '.join(target_params)}。請確認參數名稱是否正確。",
                    "available_columns_preview": all_csv_columns[:10],
                }

            # 只讀取匹配到的欄位
            df = pd.read_csv(csv_path, usecols=cols_to_read)

            # 簡單降採樣邏輯
            if len(df) > limit:
                step = len(df) // limit
                df = df.iloc[::step]

            # 確保返回的是對齊後的數據
            if not time_cols:
                # 注入行號作為 fallback 時間軸，確保 AI 敢畫圖
                df["INDEX_AXIS"] = range(len(df))
                time_cols = ["INDEX_AXIS"]

            result = df.to_dict(orient="list")
            return {
                "data": result,
                "parameters": matched_columns,
                "time_column": time_cols[0],
                "total_points": len(df),
                "note": "使用 INDEX_AXIS 或 CONTEXTID 作為序列參考"
                if "TIME" not in str(time_cols).upper()
                else "",
            }
        except Exception as e:
            return {"error": f"Failed to load data: {str(e)}"}
