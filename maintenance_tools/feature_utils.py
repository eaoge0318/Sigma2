# feature_utils.py
import pandas as pd
import os


def load_feature_mapping(filepath="參數對應表_utf8_sig_1.csv"):
    """
    載入參數對應表，建立 {原始ID: 中文名稱} 的字典。
    """
    if not os.path.exists(filepath):
        print(f"⚠️ Warning: Mapping file {filepath} not found.")
        return {}

    try:
        # 使用 utf-8-sig 處理 BOM
        df = pd.read_csv(filepath, encoding="utf-8-sig")
        # CSV 欄位是: 編號, 中文, 編號 (第三個編號是真正的 Key)
        # 我們需要第三欄 (列索引 2) -> 第二欄 (列索引 1)
        mapping = dict(zip(df.iloc[:, 2], df.iloc[:, 1]))
        return mapping
    except Exception as e:
        print(f"❌ Error loading mapping: {e}")
        return {}


def translate_features(features, mapping):
    """
    將特徵列表轉換為中文名稱列表。
    """
    return [mapping.get(f, f) for f in features]
