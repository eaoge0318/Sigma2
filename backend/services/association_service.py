"""
Association Analysis Service - Apriori 關聯規則挖掘
完全獨立模組，不依賴其他 Sigma2 服務
"""

import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────
# Binning helpers
# ────────────────────────────────────────────────

def _apply_binning(series: pd.Series, rules: List[Dict]) -> pd.Series:
    """
    將數值 Series 依規則轉成類別 Series。

    rules 格式（依序判斷，第一個符合者獲勝）：
      {"op": ">",  "val": 4,            "label": "G1"}
      {"op": ">=", "val": 3,            "label": "G1"}
      {"op": "<",  "val": 3,            "label": "G3"}
      {"op": "<=", "val": 3,            "label": "G3"}
      {"op": "~",  "lo": 3, "hi": 4,   "label": "G2"}   # lo < x <= hi
      {"op": "==", "val": 3,            "label": "G_eq"}
    """
    result = pd.Series(["_other"] * len(series), index=series.index, dtype=str)

    for rule in rules:
        op = rule.get("op", "")
        label = str(rule.get("label", "?"))
        try:
            if op == ">":
                mask = series > float(rule["val"])
            elif op == ">=":
                mask = series >= float(rule["val"])
            elif op == "<":
                mask = series < float(rule["val"])
            elif op == "<=":
                mask = series <= float(rule["val"])
            elif op == "==":
                mask = series == float(rule["val"])
            elif op == "~":
                mask = (series > float(rule["lo"])) & (series <= float(rule["hi"]))
            elif op == "idx~":
                # 依 DataFrame row index（序號）分組
                mask = (series.index >= int(rule["lo"])) & (series.index <= int(rule["hi"]))
            elif op == "idx>":
                mask = series.index > int(rule["val"])
            else:
                continue
            # 只填入尚未被賦值的行
            result[(mask) & (result == "_other")] = label
        except (KeyError, TypeError, ValueError):
            continue

    return result


def _preview_binning(series: pd.Series, rules: List[Dict]) -> Dict[str, int]:
    """回傳各 label 的行數，供前端預覽分布。"""
    grouped = _apply_binning(series, rules)
    return grouped.value_counts().to_dict()


# ────────────────────────────────────────────────
# Core Apriori logic
# ────────────────────────────────────────────────

def run_apriori(
    df: pd.DataFrame,
    selected_cols: List[str],
    binning_rules: Dict[str, List[Dict]],
    consequent_col: str,
    consequent_val: str,
    min_support: float = 0.05,
    min_confidence: float = 0.5,
    min_lift: float = 1.0,
    min_count: int = 30,
    exclude_values: Dict[str, List[str]] = {},
) -> Dict[str, Any]:
    """
    執行 Apriori 關聯規則分析，只回傳含指定 consequent 的規則。

    Returns:
        {
            rules: [{antecedents, support, confidence, lift}],
            total_transactions: int,
            frequent_itemsets_count: int,
        }
    """
    try:
        from mlxtend.frequent_patterns import apriori, association_rules
    except ImportError:
        raise RuntimeError(
            "mlxtend 套件未安裝，請執行: pip install mlxtend>=0.23.0"
        )

    # 1. 準備欄位：對數值欄位套用 binning
    available_cols = [c for c in selected_cols if c in df.columns]
    if not available_cols:
        raise ValueError(f"選擇的欄位均不在資料中，請重新選擇 (requested: {selected_cols})")
    selected_cols = available_cols
    df_work = df[selected_cols].copy()

    for col in selected_cols:
        if col in binning_rules and binning_rules[col]:
            df_work[col] = _apply_binning(df[col], binning_rules[col])
        else:
            df_work[col] = df_work[col].astype(str)

    # 1b. 排除指定欄位值（exclude_values）
    # "*" key 表示排除任意欄位中含有該值的列
    if exclude_values:
        global_excludes = set(str(v) for v in exclude_values.get("*", []))
        for col in df_work.columns:
            col_excludes = set(str(v) for v in exclude_values.get(col, []))
            all_excludes = col_excludes | global_excludes
            if all_excludes:
                df_work = df_work[~df_work[col].astype(str).isin(all_excludes)]

    # 2. 移除含 NaN 或 "_other" 的列
    df_work = df_work.replace("nan", np.nan).dropna()
    for col in df_work.columns:
        df_work = df_work[df_work[col] != "_other"]

    total_transactions = len(df_work)
    if total_transactions < 10:
        return {
            "rules": [],
            "total_transactions": total_transactions,
            "frequent_itemsets_count": 0,
            "warning": "有效資料筆數不足（< 10 筆），請放寬清洗條件或調整分組規則。",
        }

    # 3. Min Count 過濾：移除出現次數 < min_count 的欄位值所在的列
    #    這樣稀有條件（樣本不足，不可信）就不會進入分析
    if min_count > 1:
        for col in df_work.columns:
            freq = df_work[col].value_counts()
            valid_vals = freq[freq >= min_count].index
            before = len(df_work)
            df_work = df_work[df_work[col].isin(valid_vals)]
            removed = before - len(df_work)
            if removed > 0:
                logger.info(f"[Assoc] col={col}: removed {removed} rows with rare values (count < {min_count})")

        total_transactions = len(df_work)
        if total_transactions < 10:
            return {
                "rules": [],
                "total_transactions": total_transactions,
                "frequent_itemsets_count": 0,
                "warning": f"套用最小樣本數（{min_count} 筆）過濾後，有效資料不足。請降低最小樣本數或放寬清洗條件。",
            }

    # 4. 檢查每欄剩餘唯一值數量，防止 OHE 矩陣仍然過大
    MAX_UNIQUE_PER_COL = 200
    problem_cols = []
    for col in df_work.columns:
        n_uniq = df_work[col].nunique()
        if n_uniq > MAX_UNIQUE_PER_COL:
            problem_cols.append(f"{col}（{n_uniq} 個值，建議分組或提高最小樣本數）")
    if problem_cols:
        return {
            "rules": [],
            "total_transactions": total_transactions,
            "frequent_itemsets_count": 0,
            "warning": (
                f"以下欄位過濾後仍有太多唯一值（上限 {MAX_UNIQUE_PER_COL}），"
                f"請提高最小樣本數、對數值欄位設定分組，或移除此欄位：{', '.join(problem_cols)}"
            ),
        }

    # 4b. 預估運算量，超過閾值提早攔截
    total_items = sum(df_work[col].nunique() for col in df_work.columns)
    est_cells = total_transactions * total_items          # OHE 矩陣格子數
    est_mb = est_cells / (1024 * 1024)                   # 每格 1 byte (bool)
    MAX_CELLS_MB = 200                                   # 超過 200 MB 的稀疏矩陣就警告
    if est_mb > MAX_CELLS_MB:
        return {
            "rules": [],
            "total_transactions": total_transactions,
            "frequent_itemsets_count": 0,
            "warning": (
                f"⚠️ 運算量過大（預估矩陣 {est_mb:.0f} MB，上限 {MAX_CELLS_MB} MB）。"
                f" 目前共 {total_transactions} 筆交易 × {total_items} 個項目。"
                f" 請提高 Min Support、Min Count，或減少欄位數量，以降低運算量。"
            ),
        }

    # 5. One-hot 編碼（稀疏矩陣，避免記憶體爆炸）
    # 先建立 item → column index 對照表
    all_items = []
    for col in selected_cols:
        for v in df_work[col].unique():
            all_items.append(f"{col}={v}")
    item_index = {item: i for i, item in enumerate(all_items)}
    n_items = len(all_items)

    from scipy.sparse import lil_matrix
    sparse_mat = lil_matrix((total_transactions, n_items), dtype=bool)
    for row_i, (_, row) in enumerate(df_work.iterrows()):
        for col in selected_cols:
            key = f"{col}={row[col]}"
            if key in item_index:
                sparse_mat[row_i, item_index[key]] = True

    ohe = pd.DataFrame.sparse.from_spmatrix(
        sparse_mat.tocsr(),
        columns=all_items,
    )

    # 4. Apriori 挖掘頻繁項目集
    frequent_itemsets = apriori(
        ohe,
        min_support=min_support,
        use_colnames=True,
        max_len=None,
    )

    if frequent_itemsets.empty:
        return {
            "rules": [],
            "total_transactions": total_transactions,
            "frequent_itemsets_count": 0,
            "warning": f"找不到 support >= {min_support} 的頻繁項目集，請降低 Min Support。",
        }

    # 5. 生成關聯規則
    rules_df = association_rules(
        frequent_itemsets,
        metric="confidence",
        min_threshold=min_confidence,
    )

    if rules_df.empty:
        return {
            "rules": [],
            "total_transactions": total_transactions,
            "frequent_itemsets_count": len(frequent_itemsets),
            "warning": f"找不到 confidence >= {min_confidence} 的規則，請降低 Min Confidence。",
        }

    # 6. 篩選 consequent — 必須剛好等於 {target_item}，避免 {NG, X} 這類混入造成 antecedent 重複
    target_item = f"{consequent_col}={consequent_val}"
    rules_df = rules_df[
        rules_df["consequents"] == frozenset([target_item])
    ]

    # 7. 篩選 lift
    rules_df = rules_df[rules_df["lift"] >= min_lift]

    if rules_df.empty:
        return {
            "rules": [],
            "total_transactions": total_transactions,
            "frequent_itemsets_count": len(frequent_itemsets),
            "warning": f"目標結果「{target_item}」無符合條件的關聯規則。請嘗試降低門檻或選擇其他目標值。",
        }

    # 8. 依 lift 降序排列

    output_rules = []
    for _, r in rules_df.iterrows():
        output_rules.append({
            "antecedents": sorted(list(r["antecedents"])),
            "support": round(float(r["support"]), 4),
            "confidence": round(float(r["confidence"]), 4),
            "lift": round(float(r["lift"]), 4),
        })

    return {
        "rules": output_rules,
        "total_transactions": total_transactions,
        "frequent_itemsets_count": len(frequent_itemsets),
    }


# ────────────────────────────────────────────────
# Distinct values helper (for consequent picker)
# ────────────────────────────────────────────────

def get_col_distinct_values(
    df: pd.DataFrame,
    col: str,
    binning_rules: Optional[List[Dict]] = None,
    max_values: int = 100,
) -> List[str]:
    """回傳欄位的唯一值清單（套用 binning 後）。"""
    if binning_rules:
        series = _apply_binning(df[col], binning_rules)
    else:
        series = df[col].astype(str)

    vals = series.dropna().unique().tolist()
    vals = [v for v in vals if v not in ("_other", "nan")]
    return sorted(vals)[:max_values]
