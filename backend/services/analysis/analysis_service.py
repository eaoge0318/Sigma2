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

    async def prepare_file(
        self, session_id: str, filename: str
    ) -> tuple[bool, str, dict]:
        """預處理檔案的門面方法"""
        csv_path = self.base_dir / session_id / "uploads" / filename
        if not csv_path.exists():
            return False, f"檔案不存在: {filename}", {}

        try:
            summary = await self.build_analysis_index(
                str(csv_path), session_id, filename
            )
            return True, "檔案預處理成功", summary
        except Exception as e:
            logger.error(f"Prepare file failed: {e}")
            return False, str(e), {}

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

            # --- 新增：數據品質指標摘要 ---
            null_cols = [
                c for c, s in statistics.items() if s.get("missing_count", 0) > 0
            ]
            const_cols = [col for col in df.columns if df[col].nunique() <= 1]

            # 偵測「稀疏」欄位：真值比例低於 80% (排除全空或全定值)
            sparse_cols = []
            for col in df.columns:
                if col in null_cols or col in const_cols:
                    continue
                if pd.api.types.is_numeric_dtype(df[col]):
                    real_c = df[col].count() - (df[col] == 0).sum()
                else:
                    real_c = df[col].count()
                if real_c < len(df) * 0.8:
                    sparse_cols.append(col)

            summary["quality_stats"] = {
                "null_column_count": len(null_cols),
                "constant_column_count": len(const_cols),
                "sparse_column_count": len(sparse_cols),
                "null_columns_preview": null_cols[:10],
                "constant_columns_preview": const_cols[:10],
                "sparse_columns_preview": sparse_cols[:10],
            }

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
        summary = self._load_json(session_id, file_id, "summary.json")

        # 關鍵修復：補算缺失的品質統計，並確保統計文件是全量掃描過的
        if summary:
            stats = self.load_statistics(session_id, file_id)
            all_params = summary.get("parameters", [])
            is_incomplete = stats and any(p not in stats for p in all_params)

            # 如果 quality_stats 缺失，或者尚未計算過「稀疏欄位」
            q_stats = summary.get("quality_stats", {})
            if not q_stats or is_incomplete or "sparse_column_count" not in q_stats:
                logger.info(
                    f"Quality data missing or incomplete for {file_id}. Forcing refresh..."
                )
                try:
                    csv_path = (
                        self.base_dir / session_id / "uploads" / summary["filename"]
                    )
                    if csv_path.exists():
                        df = pd.read_csv(csv_path, encoding="utf-8-sig")
                        df.columns = [str(c).strip() for c in df.columns]

                        # 重新計算支援全量欄位的統計資訊
                        statistics = StatisticsHelper.calculate_statistics(df)
                        self._save_json(
                            self.get_analysis_path(session_id, file_id)
                            / "statistics.json",
                            statistics,
                        )

                        null_cols = [
                            c
                            for c, s in statistics.items()
                            if s.get("missing_count", 0) > 0
                        ]
                        const_cols = [
                            col for col in df.columns if df[col].nunique() <= 1
                        ]

                        # 偵測稀疏欄位
                        sparse_cols = []
                        for col in df.columns:
                            if col in null_cols or col in const_cols:
                                continue
                            if pd.api.types.is_numeric_dtype(df[col]):
                                real_c = df[col].count() - (df[col] == 0).sum()
                            else:
                                real_c = df[col].count()
                            if real_c < len(df) * 0.8:
                                sparse_cols.append(col)

                        summary["quality_stats"] = {
                            "null_column_count": len(null_cols),
                            "constant_column_count": len(const_cols),
                            "sparse_column_count": len(sparse_cols),
                            "null_columns_preview": null_cols[:10],
                            "constant_columns_preview": const_cols[:10],
                            "sparse_columns_preview": sparse_cols[:10],
                        }
                        self._save_json(
                            self.get_analysis_path(session_id, file_id)
                            / "summary.json",
                            summary,
                        )
                except Exception as e:
                    logger.error(f"Failed to force refresh quality_stats: {e}")

        return summary

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
