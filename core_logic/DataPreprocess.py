import numpy as np
import pandas as pd

import matplotlib.pyplot as plt


def get_processed_data_and_cols(file_path):
    """
    簡化後的資料預處理：直接讀取已有的欄位資訊。
    不再進行複雜的 Pivot 運算，因為目前的 CSV 已經包含 G_STD 與完整特徵。
    """
    df = pd.read_csv(file_path)

    # 移除缺失值 (選用，目前先註解保留穩定度)
    # df = df.dropna().reset_index(drop=True)

    # 動態識別特徵欄位：排除已知的元數據欄位，保留其餘所有欄位 (包含量測標的)
    metadata_cols = ["CONTEXTID", "CONTEXTID_ORG", "Group", "index_meta", "Unnamed: 0"]
    X_cols = [c for c in df.columns if c not in metadata_cols]

    # print(f"DEBUG: Data loaded from {file_path}")
    # print(f"DEBUG: Found {len(df)} rows. Feature columns identified: {len(X_cols)}")

    return df, X_cols
