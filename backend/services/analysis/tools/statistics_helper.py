import pandas as pd
import numpy as np
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class StatisticsHelper:
    """
    統計計算輔助類別
    負責處理 DataFrame 的統計運算、相關性分析與參數分類
    """

    @staticmethod
    def categorize_parameters(columns: List[str]) -> Dict[str, List[str]]:
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

    @staticmethod
    def calculate_statistics(df: pd.DataFrame) -> Dict:
        """計算所有參數的統計信息與缺失值狀況"""
        statistics = {}

        for col in df.columns:
            # 1. 基礎統計：不論類型，先算缺失值
            missing_count = int(df[col].isna().sum())
            total_count = int(df[col].count())

            # 2. 數值深度統計
            if pd.api.types.is_numeric_dtype(df[col]):
                try:
                    # 處理 NaN 和無限值，確保 JSON 可序列化
                    series = df[col].replace([np.inf, -np.inf], np.nan)

                    if series.count() > 0:
                        statistics[col] = {
                            "count": total_count,
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
                            "missing_count": missing_count,
                            "is_numeric": True,
                        }
                    else:
                        statistics[col] = {
                            "count": 0,
                            "missing_count": missing_count,
                            "is_numeric": True,
                        }
                except Exception as e:
                    logger.warning(f"Failed to calculate stats for {col}: {e}")
            else:
                # 3. 非數值欄位：僅記錄基礎計數
                statistics[col] = {
                    "count": total_count,
                    "missing_count": missing_count,
                    "is_numeric": False,
                }

        return statistics

    @staticmethod
    def calculate_correlations(df: pd.DataFrame) -> Dict:
        """計算數值參數間的相關性矩陣 (過濾掉變異數為 0 的欄位)"""
        numeric_cols = df.select_dtypes(include=[np.number]).columns

        if len(numeric_cols) < 2:
            return {}

        try:
            # 處理無限值
            df_numeric = df[numeric_cols].replace([np.inf, -np.inf], np.nan)

            # --- 關鍵修復：過濾掉常數項 (std == 0) ---
            # 計算標準差，如果為 0 代表該欄位所有數值相同，會導致相關性運算出現除以 0
            variances = df_numeric.std()
            valid_cols = variances[variances > 0].index.tolist()

            if len(valid_cols) < 2:
                logger.info("No varied numerical columns found for correlation matrix.")
                return {}

            df_valid = df_numeric[valid_cols]
            corr_matrix = df_valid.corr()

            # 轉換為可序列化的格式，並處理 NaN
            correlations = {}
            for col1 in valid_cols:
                correlations[col1] = {}
                for col2 in valid_cols:
                    val = corr_matrix.loc[col1, col2]
                    correlations[col1][col2] = float(val) if not pd.isna(val) else None

            return correlations
        except Exception as e:
            logger.warning(f"Failed to calculate correlations: {e}")
            return {}
