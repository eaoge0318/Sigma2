import json
import pandas as pd
import numpy as np
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
        self._df_cache = {}  # session_id_file_id -> pd.DataFrame

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

    def get_file_id(self, filename: str, conversation_id: str = "default") -> str:
        """生成文件 ID（基於文件名的 hash）, 非 default 對話時加上 conversation 後綴"""
        base_id = hashlib.md5(filename.encode()).hexdigest()[:12]
        if conversation_id and conversation_id != "default":
            return f"{base_id}_{conversation_id}"
        return base_id

    def get_uploads_dir(self, session_id: str) -> Path:
        """Alias-aware uploads dir: returns alias_cache/ when alias mode ON."""
        from backend.services.file_service import resolve_uploads_path
        return resolve_uploads_path(self.base_dir, session_id)

    def get_csv_path(self, session_id: str, filename: str) -> Path:
        """Alias-aware CSV path: returns file in alias_cache/ when alias mode ON."""
        return self.get_uploads_dir(session_id) / filename

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
        self, session_id: str, filename: str, conversation_id: str = "default"
    ) -> tuple[bool, str, dict]:
        """預處理檔案的門面方法"""
        csv_path = self.get_csv_path(session_id, filename)
        if not csv_path.exists():
            return False, f"檔案不存在: {filename}", {}

        try:
            summary = await self.build_analysis_index(
                str(csv_path),
                session_id,
                filename,
                conversation_id=conversation_id,
            )
            return True, "檔案預處理成功", summary
        except Exception as e:
            logger.error(f"Prepare file failed: {e}")
            return False, str(e), {}

    def get_dataframe(self, session_id: str, file_id: str) -> Optional[pd.DataFrame]:
        """
        獲取 DataFrame (優先從快取讀取)
        """
        cache_key = f"{session_id}_{file_id}"
        if cache_key in self._df_cache:
            # logger.info(f"Cache hit for {cache_key}")
            return self._df_cache[cache_key]

        # Cache miss - load from disk
        summary = self.load_summary(session_id, file_id)
        if not summary or "filename" not in summary:
            return None

        filename = summary["filename"]
        csv_path = self.get_csv_path(session_id, filename)

        if not csv_path.exists():
            return None

        try:
            # logger.info(f"Cache miss for {cache_key}, loading from disk...")
            df = pd.read_csv(csv_path, encoding="utf-8-sig")
            # Cleanup column names
            df.columns = [str(c).strip() for c in df.columns]
            self._df_cache[cache_key] = df
            return df
        except Exception as e:
            logger.error(f"Failed to load dataframe for {filename}: {e}")
            return None

    def clear_cache(self, session_id: Optional[str] = None):
        """清除快取 (可指定 session)"""
        if session_id:
            keys_to_remove = [k for k in self._df_cache if k.startswith(session_id)]
            for k in keys_to_remove:
                del self._df_cache[k]
            logger.info(f"Cleared cache for session {session_id}")
        else:
            self._df_cache.clear()
            logger.info("Cleared all dataframe cache")

    async def build_analysis_index(
        self,
        csv_path: str,
        session_id: str,
        filename: str,
        conversation_id: str = "default",
    ) -> Dict:
        """為 CSV 文件建立分析索引 (非阻塞: 在獨立 thread 中執行)"""
        import asyncio

        def _build_index_sync():
            file_id = self.get_file_id(filename, conversation_id=conversation_id)
            analysis_path = self.get_analysis_path(session_id, file_id, create=True)

            import os

            current_size = os.path.getsize(csv_path)
            current_mtime = os.path.getmtime(csv_path)

            # [ALWAYS REBUILD] 每次 prepare 都重新計算, 確保數據最新

            logger.info(f"Building index for {filename}")

            try:
                df = pd.read_csv(csv_path, encoding="utf-8-sig")
                df.columns = [str(c).strip() for c in df.columns]

                summary = {
                    "file_id": file_id,
                    "filename": filename,
                    "file_size": current_size,
                    "last_modified": current_mtime,
                    "total_rows": len(df),
                    "total_columns": len(df.columns),
                    "parameters": list(df.columns),
                    "numerical_columns": df.select_dtypes(
                        include=[np.number]
                    ).columns.tolist(),
                    "categories": StatisticsHelper.categorize_parameters(df.columns),
                    "created_at": pd.Timestamp.now().isoformat(),
                }

                statistics = StatisticsHelper.calculate_statistics(df)
                self._save_json(analysis_path / "statistics.json", statistics)

                null_cols = [
                    c for c, s in statistics.items() if s.get("missing_count", 0) > 0
                ]
                const_cols = [col for col in df.columns if df[col].nunique() <= 1]

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

                correlations = StatisticsHelper.calculate_correlations(df)
                self._save_json(analysis_path / "correlations.json", correlations)

                mapping = self._load_mapping_table(session_id)
                semantic_index = IndexHelper.build_semantic_index(df.columns, mapping)
                self._save_json(analysis_path / "semantic_index.json", semantic_index)

                summary["mappings"] = {
                    col: mapping[col] for col in df.columns if col in mapping
                }
                self._save_json(analysis_path / "summary.json", summary)

                logger.info(f"Index built successfully for {filename}")
                return summary

            except Exception as e:
                logger.error(f"Failed to build index for {filename}: {str(e)}")
                raise e

        return await asyncio.to_thread(_build_index_sync)

    def _save_json(self, path: Path, data: Dict):
        """輔助儲存方法"""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load_mapping_table(
        self, session_id: str, file_id: Optional[str] = None
    ) -> Dict[str, str]:
        """加載術語對應表 (優化版：支援三欄位格式與全局 fallback)"""
        mapping = {}

        def _parse_file(p):
            try:
                df = pd.read_csv(p)
                cols = df.columns
                if len(cols) >= 2:
                    # 邏輯：
                    # 如果有三欄以上，通常是 [短編號, 中文, 長編號]
                    # 我們要把 短編號 -> 中文 AND 長編號 -> 中文 都存起來
                    for _, row in df.iterrows():
                        name = str(row[cols[1]]).strip()
                        if not name or name == "nan":
                            continue

                        # 第一欄
                        code1 = str(row[cols[0]]).strip()
                        if code1 and code1 != "nan":
                            mapping[code1] = name

                        # 第三欄 (如果有)
                        if len(cols) >= 3:
                            code2 = str(row[cols[2]]).strip()
                            if code2 and code2 != "nan":
                                mapping[code2] = name
            except Exception as e:
                logger.warning(f"Failed to parse mapping file {p}: {e}")

        # 1. 查找特定 Session 的映射
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
                mapping_files = list(uploads_dir.glob("*參數對應表*.csv"))
                if mapping_files:
                    mapping_file_path = max(
                        mapping_files, key=lambda p: p.stat().st_mtime
                    )

        if mapping_file_path:
            _parse_file(mapping_file_path)

        return mapping

    def load_summary(self, session_id: str, file_id: str) -> Optional[Dict]:
        summary = self._load_json(session_id, file_id, "summary.json")

        # 關鍵修復：補算缺失的品質統計，或修復重名欄位衝突
        if summary:
            # 檢查參數清單是否有重複 (即 strip() 後產生的碰撞)
            all_params = summary.get("parameters", [])

            stats = self.load_statistics(session_id, file_id)
            is_incomplete = stats and any(p not in stats for p in all_params)

            # 如果 quality_stats 缺失，或者尚未計算過「稀疏欄位」，或者缺 numerical_columns
            q_stats = summary.get("quality_stats", {})
            if (
                not q_stats
                or is_incomplete
                or "sparse_column_count" not in q_stats
                or "numerical_columns" not in summary
                or "recommended_targets" not in summary  # Force refresh if missing
            ):
                logger.info(
                    f"Quality data missing or incomplete for {file_id}. Forcing refresh..."
                )
                try:
                    csv_path = self.get_csv_path(session_id, summary["filename"])
                    if csv_path.exists():
                        df = pd.read_csv(csv_path, encoding="utf-8-sig")
                        df.columns = [str(c).strip() for c in df.columns]

                        # 更新摘要基礎資訊
                        summary["parameters"] = list(df.columns)
                        summary["numerical_columns"] = df.select_dtypes(
                            include=[np.number]
                        ).columns.tolist()
                        summary["total_columns"] = len(df.columns)
                        summary["categories"] = StatisticsHelper.categorize_parameters(
                            df.columns
                        )

                        # 重新計算支援全量欄位的統計資訊與相關性
                        statistics = StatisticsHelper.calculate_statistics(df)
                        self._save_json(
                            self.get_analysis_path(session_id, file_id)
                            / "statistics.json",
                            statistics,
                        )

                        correlations = StatisticsHelper.calculate_correlations(df)
                        self._save_json(
                            self.get_analysis_path(session_id, file_id)
                            / "correlations.json",
                            correlations,
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

                        # [NEW] Calculate Recommended Targets based on Variance (CV) & Keywords
                        recommended_targets = []
                        numerical_cols = summary.get("numerical_columns", [])

                        if numerical_cols:
                            try:
                                # Calculate CV = std / mean (handle divide by zero)
                                stats_df = df[numerical_cols].agg(["mean", "std"]).T
                                stats_df["cv"] = stats_df["std"] / (
                                    stats_df["mean"].abs() + 1e-9
                                )
                                stats_df = stats_df.sort_values("cv", ascending=False)

                                # Filter: CV > 0.01 (min variability)
                                high_variance = stats_df[
                                    stats_df["cv"] > 0.01
                                ].index.tolist()

                                # Keyword prioritization
                                keywords = [
                                    "output",
                                    "result",
                                    "yield",
                                    "target",
                                    "score",
                                    "price",
                                    "quality",
                                    "rate",
                                    "efficiency",
                                ]
                                priority_targets = [
                                    c
                                    for c in high_variance
                                    if any(k in c.lower() for k in keywords)
                                ]

                                # Combine: Priority first, then high variance
                                recommended_targets = priority_targets + [
                                    c
                                    for c in high_variance
                                    if c not in priority_targets
                                ]

                                # Limit to top 5
                                recommended_targets = recommended_targets[:5]
                            except Exception as e:
                                logger.warning(
                                    f"Failed to calculate recommended targets: {e}"
                                )

                        summary["recommended_targets"] = recommended_targets

                        self._save_json(
                            self.get_analysis_path(session_id, file_id)
                            / "summary.json",
                            summary,
                        )
                except Exception as e:
                    logger.error(f"Failed to force refresh quality_stats: {e}")

            # [FIX] 每次載入 summary 時, 動態刷新 mappings (而不是只在建索引時)
            # 這樣即使用戶在建索引後才上傳 mapping CSV, 也能正確載入
            try:
                fresh_mapping = self._load_mapping_table(session_id, file_id)
                if fresh_mapping:
                    all_params = set(summary.get("parameters", []))
                    relevant = {
                        k: v for k, v in fresh_mapping.items() if k in all_params
                    }
                    if relevant != summary.get("mappings", {}):
                        summary["mappings"] = relevant
                        self._save_json(
                            self.get_analysis_path(session_id, file_id)
                            / "summary.json",
                            summary,
                        )
                        logger.info(
                            f"[Mapping] 動態刷新 mappings: {len(relevant)} 個映射已更新到 summary"
                        )
            except Exception as e:
                logger.warning(f"[Mapping] 刷新 mappings 失敗: {e}")

        return summary

    def load_statistics(self, session_id: str, file_id: str) -> Dict:
        return self._load_json(session_id, file_id, "statistics.json") or {}

    def load_correlations(self, session_id: str, file_id: str) -> Dict:
        return self._load_json(session_id, file_id, "correlations.json") or {}

    def load_semantic_index(self, session_id: str, file_id: str) -> Dict:
        return self._load_json(session_id, file_id, "semantic_index.json") or {}

    def _get_mapping_file_name(
        self, session_id: str, file_id: str = None
    ) -> Optional[str]:
        """獲取當前會話生效的對應表檔名"""
        try:
            # 1. 優先檢查 bound mapping (綁定到特定檔案)
            if file_id:
                bound_path = (
                    self.base_dir / session_id / "analysis" / file_id / "mapping.csv"
                )
                if bound_path.exists():
                    return bound_path.name

            # 2. 查找全域對應表 (帶前綴)
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

    def get_active_mapping(
        self, session_id: str, file_id: str = None
    ) -> tuple[Optional[str], str]:
        """Expose mapping status to router."""
        mapping_file = self._get_mapping_file_name(session_id, file_id)
        if mapping_file:
            return mapping_file, "active"
        return None, "inactive"

    def delete_mapping(self, session_id: str, file_id: str = None) -> int:
        """刪除 mapping 檔案。回傳刪除的檔案數量。"""
        deleted = 0
        try:
            # 1. 刪除綁定到特定檔案的 mapping
            if file_id:
                bound_path = (
                    self.base_dir / session_id / "analysis" / file_id / "mapping.csv"
                )
                if bound_path.exists():
                    bound_path.unlink()
                    deleted += 1
                    logger.info(f"Deleted bound mapping: {bound_path}")

            # 2. 刪除全域對應表
            uploads_dir = self.base_dir / session_id / "uploads"
            if uploads_dir.exists():
                for f in uploads_dir.glob("*(參數對應表)*.csv"):
                    f.unlink()
                    deleted += 1
                    logger.info(f"Deleted global mapping: {f}")
        except Exception as e:
            logger.error(f"Failed to delete mapping: {e}", exc_info=True)
        return deleted

    async def manual_reindex(self, session_id: str, file_id: str) -> bool:
        """強制重新建立特定檔案的索引"""
        summary = self.load_summary(session_id, file_id)
        if not summary or "filename" not in summary:
            return False

        filename = summary["filename"]
        csv_path = self.get_csv_path(session_id, filename)
        if not csv_path.exists():
            return False

        # 刪除舊的摘要以強制觸發 build_analysis_index
        summary_file = self.get_analysis_path(session_id, file_id) / "summary.json"
        if summary_file.exists():
            summary_file.unlink()

        await self.build_analysis_index(str(csv_path), session_id, filename)
        return True

    def _load_json(
        self, session_id: str, file_id: str, filename: str
    ) -> Optional[Dict]:
        """通用讀取方法"""
        try:
            path = self.get_analysis_path(session_id, file_id) / filename
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # [BUG FIX] Handle double-serialized JSON (stringified JSON)
                    if isinstance(data, str):
                        try:
                            # Try to parse again if it looks like a JSON object/list
                            if data.strip().startswith("{") or data.strip().startswith(
                                "["
                            ):
                                data = json.loads(data)
                        except json.JSONDecodeError:
                            pass
                    return data if isinstance(data, dict) else None
        except Exception:
            pass
        return None
