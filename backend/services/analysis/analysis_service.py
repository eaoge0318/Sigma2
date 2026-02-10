import json
import pandas as pd
import hashlib
import logging
from pathlib import Path
from typing import Dict, List, Optional
from .tools.statistics_helper import StatisticsHelper
from .tools.index_helper import IndexHelper

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
            logger.warning(f"Invalid session_id ({session_id}) or file_id ({file_id})")
            raise ValueError("session_id and file_id must not be None")

        analysis_dir = self.base_dir / session_id / "analysis" / file_id
        if create:
            analysis_dir.mkdir(parents=True, exist_ok=True)
        return analysis_dir

    async def build_analysis_index(
        self, csv_path: str, session_id: str, filename: str
    ) -> Dict:
        """為 CSV 文件建立分析索引 (使用模組化 Helper)"""
        file_id = self.get_file_id(filename)
        analysis_path = self.get_analysis_path(session_id, file_id, create=True)

        summary_file = analysis_path / "summary.json"
        if summary_file.exists():
            logger.info(f"Index already exists for {filename}")
            with open(summary_file, "r", encoding="utf-8") as f:
                return json.load(f)

        logger.info(f"Building index for {filename}")

        try:
            df = pd.read_csv(csv_path, encoding="utf-8-sig")
            df.columns = [str(c).strip() for c in df.columns]

            # 1. 基礎摘要 & 分類
            summary = {
                "file_id": file_id,
                "filename": filename,
                "total_rows": len(df),
                "total_columns": len(df.columns),
                "parameters": list(df.columns),
                "categories": StatisticsHelper.categorize_parameters(df.columns),
                "created_at": pd.Timestamp.now().isoformat(),
            }

            # 2. 統計信息
            statistics = StatisticsHelper.calculate_statistics(df)
            self._save_json(analysis_path / "statistics.json", statistics)

            # 3. 相關性矩陣
            correlations = StatisticsHelper.calculate_correlations(df)
            self._save_json(analysis_path / "correlations.json", correlations)

            # 4. 語義索引
            mapping = self._load_mapping_table(session_id)
            semantic_index = IndexHelper.build_semantic_index(df.columns, mapping)
            self._save_json(analysis_path / "semantic_index.json", semantic_index)

            # 5. 保存映射快照
            summary["mappings"] = {
                col: mapping[col] for col in df.columns if col in mapping
            }
            self._save_json(summary_file, summary)

            logger.info(f"Index built successfully for {filename}")
            return summary

        except Exception as e:
            logger.error(f"Failed to build index for {filename}: {str(e)}")
            raise e

    def _save_json(self, path: Path, data: Dict):
        """輔助儲存方法"""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load_mapping_table(
        self, session_id: str, file_id: Optional[str] = None
    ) -> Dict[str, str]:
        """加載術語對應表"""
        mapping = {}
        try:
            mapping_file_path = None
            if file_id:
                bound_mapping = (
                    self.base_dir / session_id / "analysis" / file_id / "mapping.csv"
                )
                if bound_mapping.exists():
                    mapping_file_path = bound_mapping

            if not mapping_file_path:
                uploads_dir = self.base_dir / session_id / "uploads"
                if uploads_dir.exists():
                    mapping_files = list(uploads_dir.glob("*(參數對應表)*.csv"))
                    if mapping_files:
                        mapping_file_path = max(
                            mapping_files, key=lambda p: p.stat().st_mtime
                        )

            if not mapping_file_path:
                return {}

            df = pd.read_csv(mapping_file_path)
            cols = df.columns
            if len(cols) >= 2:
                # 簡單推斷 key/value columns
                code_col = cols[0]
                cn_col = cols[1]
                for _, row in df.iterrows():
                    code = str(row[code_col]).strip()
                    name = str(row[cn_col]).strip()
                    if code and name and code != "nan" and name != "nan":
                        mapping[code] = name
        except Exception as e:
            logger.warning(f"Mapping table load failed: {e}")
        return mapping

    def load_summary(self, session_id: str, file_id: str) -> Optional[Dict]:
        return self._load_json(session_id, file_id, "summary.json")

    def load_statistics(self, session_id: str, file_id: str) -> Dict:
        return self._load_json(session_id, file_id, "statistics.json") or {}

    def load_correlations(self, session_id: str, file_id: str) -> Dict:
        return self._load_json(session_id, file_id, "correlations.json") or {}

    def load_semantic_index(self, session_id: str, file_id: str) -> Dict:
        return self._load_json(session_id, file_id, "semantic_index.json") or {}

    def _get_mapping_file_name(self, session_id: str) -> Optional[str]:
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

    def _load_json(
        self, session_id: str, file_id: str, filename: str
    ) -> Optional[Dict]:
        """通用讀取方法"""
        try:
            path = self.get_analysis_path(session_id, file_id) / filename
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return None
