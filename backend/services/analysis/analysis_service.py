import json
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional
import hashlib
import logging

logger = logging.getLogger(__name__)


class AnalysisService:
    """
    數據分析核心服務
    負責：CSV 索引建立、數據摘要、語義搜索
    """

    def __init__(self, base_dir: str = "workspace"):
        self.base_dir = Path(base_dir)
        self.stop_events = {}  # session_id -> bool

    def stop_generation(self, session_id: str):
        """設定停止標誌"""
        self.stop_events[session_id] = True
        logger.info(f"Stop signal set for session: {session_id}")

    def clear_stop_signal(self, session_id: str):
        """清除停止標誌"""
        if session_id in self.stop_events:
            del self.stop_events[session_id]

    def is_generation_stopped(self, session_id: str) -> bool:
        """檢查是否收到停止信號"""
        return self.stop_events.get(session_id, False)

    def get_file_id(self, filename: str) -> str:
        """生成文件 ID（基於文件名的 hash）"""
        return hashlib.md5(filename.encode()).hexdigest()[:12]

    def get_analysis_path(
        self, session_id: str, file_id: str, create: bool = False
    ) -> Path:
        """獲取分析文件存儲路徑"""
        if not session_id or not file_id:
            logger.warning(
                f"Invalid session_id ({session_id}) or file_id ({file_id}) provided to get_analysis_path"
            )
            # 返回一個不存在的安全路徑，避免後續操作報錯，或者拋出 ValueError
            raise ValueError("session_id and file_id must not be None")

        analysis_dir = self.base_dir / session_id / "analysis" / file_id
        if create:
            analysis_dir.mkdir(parents=True, exist_ok=True)
        return analysis_dir

    async def build_analysis_index(
        self, csv_path: str, session_id: str, filename: str
    ) -> Dict:
        """
        為 CSV 文件建立分析索引
        這是一次性操作，結果會緩存

        生成文件：
        - summary.json: 基本摘要
        - statistics.json: 統計信息
        - correlations.json: 相關性矩陣
        - semantic_index.json: 語義索引
        """
        file_id = self.get_file_id(filename)
        analysis_path = self.get_analysis_path(session_id, file_id, create=True)

        # 檢查是否已有索引
        summary_file = analysis_path / "summary.json"
        if summary_file.exists():
            logger.info(f"Index already exists for {filename}")
            with open(summary_file, "r", encoding="utf-8") as f:
                return json.load(f)

        logger.info(f"Building index for {filename}")

        try:
            # 讀取 CSV (支援 utf-8-sig 以處理 BOM，並清理欄位名稱多餘空白)
            df = pd.read_csv(csv_path, encoding="utf-8-sig")
            df.columns = [str(c).strip() for c in df.columns]

            # 1. 生成基本摘要
            summary = {
                "file_id": file_id,
                "filename": filename,
                "total_rows": len(df),
                "total_columns": len(df.columns),
                "parameters": list(df.columns),
                "created_at": pd.Timestamp.now().isoformat(),
            }

            # 2. 參數分類
            categories = self._categorize_parameters(df.columns)
            summary["categories"] = categories

            # 3. 計算統計信息
            statistics = self._calculate_statistics(df)
            with open(analysis_path / "statistics.json", "w", encoding="utf-8") as f:
                json.dump(statistics, f, ensure_ascii=False, indent=2)

            # 4. 計算相關性矩陣
            correlations = self._calculate_correlations(df)
            with open(analysis_path / "correlations.json", "w", encoding="utf-8") as f:
                json.dump(correlations, f, ensure_ascii=False, indent=2)

            # 5. 構建語義索引
            mapping = self._load_mapping_table(session_id)
            semantic_index = self._build_semantic_index(df.columns, mapping)
            with open(
                analysis_path / "semantic_index.json", "w", encoding="utf-8"
            ) as f:
                json.dump(semantic_index, f, ensure_ascii=False, indent=2)

            # 6. 保存映射快照 (方便總結使用)
            summary["mappings"] = {
                col: mapping[col] for col in df.columns if col in mapping
            }

            # 保存摘要
            with open(summary_file, "w", encoding="utf-8") as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)

            logger.info(f"Index built successfully for {filename}")
            return summary

        except Exception as e:
            logger.error(f"Failed to build index for {filename}: {str(e)}")
            raise e

    def _categorize_parameters(self, columns: List[str]) -> Dict[str, List[str]]:
        """根據參數名前綴進行分類"""
        categories = {}
        for col in columns:
            # 提取前綴（如 TENSION-A101 -> TENSION）
            parts = col.split("-")
            if len(parts) > 1:
                category = parts[0]
            else:
                parts = col.split("_")
                category = parts[0] if len(parts) > 1 else "OTHER"

            if category not in categories:
                categories[category] = []
            categories[category].append(col)

        return categories

    def _calculate_statistics(self, df: pd.DataFrame) -> Dict:
        """計算所有數值參數的統計信息"""
        statistics = {}

        for col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col]):
                try:
                    # 處理 NaN 和無限值，確保 JSON 可序列化
                    series = df[col].replace([np.inf, -np.inf], np.nan)

                    if series.count() > 0:
                        statistics[col] = {
                            "count": int(series.count()),
                            "mean": float(series.mean())
                            if not pd.isna(series.mean())
                            else None,
                            "std": float(series.std())
                            if not pd.isna(series.std())
                            else None,
                            "min": float(series.min())
                            if not pd.isna(series.min())
                            else None,
                            "max": float(series.max())
                            if not pd.isna(series.max())
                            else None,
                            "median": float(series.median())
                            if not pd.isna(series.median())
                            else None,
                            "q1": float(series.quantile(0.25))
                            if not pd.isna(series.quantile(0.25))
                            else None,
                            "q3": float(series.quantile(0.75))
                            if not pd.isna(series.quantile(0.75))
                            else None,
                            "missing_count": int(series.isna().sum()),
                        }
                    else:
                        statistics[col] = {
                            "count": 0,
                            "missing_count": int(series.isna().sum()),
                        }
                except Exception as e:
                    logger.warning(f"Failed to calculate stats for {col}: {e}")

        return statistics

    def _calculate_correlations(self, df: pd.DataFrame) -> Dict:
        """計算數值參數間的相關性矩陣"""
        numeric_cols = df.select_dtypes(include=[np.number]).columns

        if len(numeric_cols) < 2:
            return {}

        try:
            # 處理無限值
            df_numeric = df[numeric_cols].replace([np.inf, -np.inf], np.nan)
            corr_matrix = df_numeric.corr()

            # 轉換為可序列化的格式，並處理 NaN
            correlations = {}
            for col1 in numeric_cols:
                correlations[col1] = {}
                for col2 in numeric_cols:
                    val = corr_matrix.loc[col1, col2]
                    correlations[col1][col2] = float(val) if not pd.isna(val) else None

            return correlations
        except Exception as e:
            logger.warning(f"Failed to calculate correlations: {e}")
            return {}

    def _build_semantic_index(
        self, columns: List[str], mapping: Dict[str, str] = None
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

    def _load_mapping_table(
        self, session_id: str, file_id: Optional[str] = None
    ) -> Dict[str, str]:
        """加載術語對應表 (優先使用綁定的對應表，否則使用全域)"""
        mapping = {}
        try:
            mapping_file_path = None

            # 1. 優先檢查綁定的對應表
            if file_id:
                bound_mapping = (
                    self.base_dir / session_id / "analysis" / file_id / "mapping.csv"
                )
                if bound_mapping.exists():
                    mapping_file_path = bound_mapping
                    logger.info(f"Using bound mapping file for {file_id}")

            # 2. 如果沒有綁定，檢查全域對應表
            if not mapping_file_path:
                uploads_dir = self.base_dir / session_id / "uploads"
                mapping_files = (
                    list(uploads_dir.glob("*(參數對應表)*.csv"))
                    if uploads_dir.exists()
                    else []
                )
                if mapping_files:
                    # 使用最新的全域對應表
                    mapping_file_path = max(
                        mapping_files, key=lambda p: p.stat().st_mtime
                    )
                    logger.info(f"Using global mapping file: {mapping_file_path.name}")

            if not mapping_file_path:
                return {}

            # 讀取對應表內容
            import pandas as pd

            df = pd.read_csv(mapping_file_path)
            # 假設有 '代碼' 和 '名稱' 欄位，或者第一欄是代碼，第二欄是名稱
            # 這裡做一個簡單的推斷
            cols = df.columns
            if len(cols) >= 2:
                # 嘗試尋找包含 "code", "id", "parameter" 的欄位作為 key
                # 尋找包含 "name", "desc", "meaning" 的欄位作為 value
                code_col = next(
                    (
                        c
                        for c in cols
                        if any(k in str(c).lower() for k in ["code", "id", "param"])
                    ),
                    cols[0],
                )
                cn_col = next(
                    (
                        c
                        for c in cols
                        if any(
                            k in str(c).lower()
                            for k in ["name", "desc", "mean", "名稱", "說明"]
                        )
                    ),
                    cols[1],
                )

                if cn_col and code_col:
                    for _, row in df.iterrows():
                        code = str(row[code_col]).strip()
                        name = str(row[cn_col]).strip()
                        if code and name and code != "nan" and name != "nan":
                            mapping[code] = name
                logger.info(
                    f"Loaded {len(mapping)} mappings from {mapping_file_path.name}"
                )
        except Exception as e:
            logger.warning(f"Mapping table load failed: {e}")
        return mapping

    def _get_mapping_file_name(self, session_id: str) -> str:
        """獲取當前會話生效的對應表檔名"""
        try:
            uploads_dir = self.base_dir / session_id / "uploads"
            mapping_files = (
                list(uploads_dir.glob("*(參數對應表)*.csv"))
                if uploads_dir.exists()
                else []
            )

            if not mapping_files:
                return None

            # 返回最新的檔名
            latest_file = max(mapping_files, key=lambda p: p.stat().st_mtime)
            return latest_file.name
        except Exception as e:
            logger.warning(f"Failed to get mapping file name: {e}")
            return None

    async def manual_reindex(self, session_id: str, file_id: str):
        """強制重新建立某個文件的索引 (用於更新映射)"""
        summary = self.load_summary(session_id, file_id)
        if not summary:
            return False

        filename = summary["filename"]
        csv_path = self.base_dir / session_id / "uploads" / filename

        # 刪除舊索引文件
        analysis_path = self.get_analysis_path(session_id, file_id)
        for f in [
            "summary.json",
            "semantic_index.json",
            "statistics.json",
            "correlations.json",
        ]:
            p = analysis_path / f
            if p.exists():
                p.unlink()

        # 重新建立
        await self.build_analysis_index(str(csv_path), session_id, filename)
        return True

    def load_summary(self, session_id: str, file_id: str) -> Optional[Dict]:
        """加載分析摘要"""
        analysis_path = self.get_analysis_path(session_id, file_id)
        summary_file = analysis_path / "summary.json"

        if not summary_file.exists():
            logger.warning(
                f"Summary file not found: {summary_file} (Session: {session_id}, File: {file_id})"
            )
            return None

        try:
            with open(summary_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load summary: {e}")
            return None

    def load_statistics(self, session_id: str, file_id: str) -> Dict:
        """加載統計信息"""
        try:
            analysis_path = self.get_analysis_path(session_id, file_id)
            stats_file = analysis_path / "statistics.json"

            if not stats_file.exists():
                return {}

            with open(stats_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def load_correlations(self, session_id: str, file_id: str) -> Dict:
        """加載相關性矩陣"""
        try:
            analysis_path = self.get_analysis_path(session_id, file_id)
            corr_file = analysis_path / "correlations.json"

            if not corr_file.exists():
                return {}

            with open(corr_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def load_semantic_index(self, session_id: str, file_id: str) -> Dict:
        """加載語義索引"""
        try:
            analysis_path = self.get_analysis_path(session_id, file_id)
            index_file = analysis_path / "semantic_index.json"

            if not index_file.exists():
                return {}

            with open(index_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
