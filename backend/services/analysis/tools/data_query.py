from .base import AnalysisTool
from typing import Dict, Any
import pandas as pd
import logging

logger = logging.getLogger(__name__)


class GetParameterListTool(AnalysisTool):
    """獲取數據集的所有欄位列表"""

    name = "get_parameter_list"
    description = "獲取 CSV 文件的所有欄位名稱，支援關鍵字過濾"
    required_params = ["file_id"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        keyword = params.get("keyword", "").lower()

        summary = self.service.load_summary(session_id, file_id)
        if not summary:
            return {"error": f"Summary not found for file_id: {file_id}"}

        all_params = summary["parameters"]

        # 關鍵字過濾
        if keyword:
            matched = [p for p in all_params if keyword in p.lower()]
        else:
            matched = all_params

        # 只返回匹配到的欄位的映射資訊，避免傳送整張大表給 LLM 導致延遲
        mappings = summary.get("mappings", {})
        matched_mappings = {p: mappings[p] for p in matched if p in mappings}

        return {
            "parameters": matched,
            "total_count": len(all_params),
            "matched_count": len(matched),
            "categories": summary.get("categories", {}),
            "mappings": matched_mappings,
        }


class GetParameterStatisticsTool(AnalysisTool):
    """獲取欄位的統計資訊"""

    name = "get_parameter_statistics"
    description = "返回欄位的均值、中位數、標準差、最大值、最小值等"
    required_params = ["file_id", "parameter"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        parameter = params.get("parameter")

        statistics = self.service.load_statistics(session_id, file_id)

        if parameter not in statistics:
            return {"error": f"Parameter {parameter} not found or not numeric"}

        result = statistics[parameter].copy()
        result["parameter"] = parameter

        return result


class SearchParametersByConceptTool(AnalysisTool):
    """根據關鍵字搜尋相關欄位"""

    name = "search_parameters_by_concept"
    description = "例如輸入「價格」，能找到「單價」、「總價」、「售價」等相關欄位"
    required_params = ["file_id", "concept"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        concept_raw = params.get("concept", "")

        # 轉換為列表處理，支援單一字串或多個關鍵字陣列
        concepts = [concept_raw] if isinstance(concept_raw, str) else concept_raw

        semantic_index = self.service.load_semantic_index(session_id, file_id)
        summary = self.service.load_summary(session_id, file_id)

        if not summary:
            return {"error": "Summary not found"}

        matched_parameters = []
        all_params = summary.get("parameters", [])

        for concept in concepts:
            if not isinstance(concept, str):
                continue

            # 1. 語義索引匹配
            if concept in semantic_index:
                for param in semantic_index[concept]:
                    if not any(m["name"] == param for m in matched_parameters):
                        matched_parameters.append(
                            {
                                "name": param,
                                "confidence": 0.9,
                                "reason": f"語義映射: {concept}",
                            }
                        )

            # 2. 模糊匹配 (對每個關鍵字進行 substring 搜尋)
            # 2. 模糊匹配 (對每個關鍵字進行 substring 搜尋)
            for param in all_params:
                if concept.lower() in param.lower():
                    # 避免重複添加
                    if not any(m["name"] == param for m in matched_parameters):
                        matched_parameters.append(
                            {
                                "name": param,
                                "confidence": 0.7,
                                "reason": f"關鍵字匹配: {concept}",
                            }
                        )

        # 3. 映射表關鍵字匹配 (從參數對應表尋找中文描述)
        mappings = summary.get("mappings", {})
        for code, chinese_name in mappings.items():
            if code not in all_params:
                continue
            for concept in concepts:
                if not isinstance(concept, str):
                    continue
                if concept in chinese_name:
                    if not any(m["name"] == code for m in matched_parameters):
                        matched_parameters.append(
                            {
                                "name": code,
                                "confidence": 0.95,
                                "reason": f"映射表匹配: {chinese_name}",
                            }
                        )

        return {
            "matched_parameters": matched_parameters,
            "search_concepts": concepts,
            "mappings": {
                m["name"]: mappings.get(m["name"], "")
                for m in matched_parameters
                if m["name"] in mappings
            },
        }


class GetDataOverviewTool(AnalysisTool):
    """獲取數據總覽（前幾行）"""

    name = "get_data_overview"
    description = "查看數據集的前5行，了解數據格式"
    required_params = ["file_id"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        rows = params.get("rows", 5)

        csv_path = self._get_csv_path(session_id, file_id)
        if not csv_path:
            return {"error": "CSV file not found"}

        try:
            # 支援 utf-8-sig 並清理欄位名稱
            df = pd.read_csv(csv_path, encoding="utf-8-sig", nrows=rows)
            # 清理欄位名稱 (strip whitespace)
            df.columns = [str(c).strip() for c in df.columns]
            # 處理 NaN 為 None，確保 JSON 序列化
            df = df.where(pd.notnull(df), None)
            return {
                "columns": list(df.columns),
                "data": df.to_dict(orient="records"),
                "total_preview_rows": len(df),
            }
        except Exception as e:
            return {"error": f"Failed to read CSV: {str(e)}"}

    def _get_csv_path(self, session_id: str, file_id: str) -> str:
        summary = self.service.load_summary(session_id, file_id)
        if not summary:
            return None
        filename = summary["filename"]
        return str(self.service.base_dir / session_id / "uploads" / filename)


class GetTimeSeriesDataTool(AnalysisTool):
    """獲取時序數據（用於繪圖）"""

    name = "get_time_series_data"
    description = "獲取指定欄位的數據序列，可用於繪製折線圖"
    required_params = ["file_id", "parameters"]

    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get("file_id")
        parameters = params.get("parameters", [])
        start_index = params.get("start_index", 0)
        limit = params.get("limit", 1000)  # 限制返回數據量，避免過大

        logger.info(
            f"[DataQuery] request: file_id={file_id}, parameters={parameters[:5]}..., session_id={session_id}"
        )

        csv_path = self._get_csv_path(session_id, file_id)
        if not csv_path:
            return {"error": "CSV file not found"}

        try:
            # 優化：先讀取 header 建立映射
            header_df = pd.read_csv(csv_path, encoding="utf-8-sig", nrows=0)

            # 建立 clean_name -> raw_name 的映射
            raw_columns = header_df.columns.tolist()
            col_map = {str(c).strip(): c for c in raw_columns}
            clean_columns = list(col_map.keys())

            # 找出真正需要讀取的原始欄位名稱
            valid_params_map = {}  # clean -> raw
            for p in parameters:
                if p in clean_columns:
                    valid_params_map[p] = col_map[p]

            if not valid_params_map:
                logger.warning(
                    f"[DataQuery] No valid parameters found. request={parameters}, available={clean_columns[:10]}..."
                )
                return {
                    "error": f"No valid parameters found in CSV. Requested: {parameters}, Available: {clean_columns[:10]}..."
                }

            # 使用原始欄位名稱讀取
            use_raw_cols = list(valid_params_map.values())

            df = pd.read_csv(
                csv_path,
                encoding="utf-8-sig",
                usecols=use_raw_cols,
                skiprows=range(1, start_index + 1),
                nrows=limit,
            )

            # 讀取後將欄位名稱轉回 clean names
            df.rename(columns={v: k for k, v in valid_params_map.items()}, inplace=True)

            # 處理 NaN
            df = df.where(pd.notnull(df), None)

            return {
                "start_index": start_index,
                "limit": limit,
                "data": df.to_dict(
                    orient="list"
                ),  # Column-oriented logic is better for charts usually
                "parameters": list(valid_params_map.keys()),
            }
        except Exception as e:
            logger.error(f"[DataQuery] Exception reading CSV: {e}")
            return {"error": f"Failed to read time series data: {str(e)}"}

    def _get_csv_path(self, session_id: str, file_id: str) -> str:
        summary = self.service.load_summary(session_id, file_id)
        if not summary:
            logger.warning(
                f"[DataQuery] Summary not found for file_id={file_id}, session_id={session_id}"
            )
            return None
        filename = summary["filename"]
        path = self.service.base_dir / session_id / "uploads" / filename
        logger.info(f"[DataQuery] Resolved CSV path: {path}")
        return str(path)
