"""
數據驗證工具
提供訓練參數、數據集等的驗證功能
"""

import os
import pandas as pd
from typing import List, Dict, Any, Optional
from backend.utils.exceptions import ValidationError, FileNotFoundError
from backend.utils.logger import get_logger

logger = get_logger(__name__)


def validate_training_inputs(
    data_path: str,
    goal_col: str,
    action_features: List[str],
    state_features: List[str],
    goal_settings: Dict[str, float],
) -> None:
    """
    嚴格驗證訓練輸入參數

    Args:
        data_path: 數據檔案路徑
        goal_col: 目標欄位名稱
        action_features: 動作特徵清單
        state_features: 狀態特徵清單
        goal_settings: 品質目標設定 (包含 lsl 和 usl)

    Raises:
        ValidationError: 參數驗證失敗
        FileNotFoundError: 檔案不存在
    """
    errors = []

    # 1. 檔案存在性檢查
    if not data_path:
        errors.append("數據檔案路徑不可為空")
    elif not os.path.exists(data_path):
        raise FileNotFoundError(data_path, details={"message": "訓練數據檔案不存在"})

    # 2. 目標欄位檢查
    if not goal_col:
        errors.append("目標欄位 (goal_col) 必須指定")

    # 3. 動作特徵檢查
    if not action_features or len(action_features) == 0:
        errors.append("至少需要指定一個動作特徵 (action_features)")
    elif not isinstance(action_features, list):
        errors.append("動作特徵必須是列表格式")

    # 4. 狀態特徵檢查 (可以為空，但必須是列表)
    if state_features is not None and not isinstance(state_features, list):
        errors.append("狀態特徵必須是列表格式")

    # 5. 品質區間檢查
    if not goal_settings:
        errors.append("品質目標設定 (goal_settings) 不可為空")
    else:
        if "lsl" not in goal_settings:
            errors.append("品質目標缺少下限 (LSL)")
        if "usl" not in goal_settings:
            errors.append("品質目標缺少上限 (USL)")

        # 檢查 LSL < USL
        if "lsl" in goal_settings and "usl" in goal_settings:
            try:
                lsl = float(goal_settings["lsl"])
                usl = float(goal_settings["usl"])

                if lsl >= usl:
                    errors.append(f"品質下限 (LSL={lsl}) 必須小於上限 (USL={usl})")
            except (ValueError, TypeError) as e:
                errors.append(f"品質目標格式錯誤: {e}")

    # 如果有錯誤，統一拋出
    if errors:
        error_message = "訓練參數驗證失敗:\n" + "\n".join(
            f"  - {err}" for err in errors
        )
        logger.error(error_message)
        raise ValidationError(error_message, details={"errors": errors})

    # 6. 數據欄位檢查 (載入第一行檢查欄位)
    try:
        df_sample = pd.read_csv(data_path, nrows=1)
        missing_cols = []

        if goal_col not in df_sample.columns:
            missing_cols.append(goal_col)

        for col in action_features:
            if col not in df_sample.columns:
                missing_cols.append(col)

        if state_features:
            for col in state_features:
                if col not in df_sample.columns:
                    missing_cols.append(col)

        if missing_cols:
            error_msg = f"數據集缺少以下欄位: {missing_cols}"
            logger.error(error_msg)
            raise ValidationError(
                error_msg,
                details={
                    "missing_columns": missing_cols,
                    "available_columns": list(df_sample.columns),
                },
            )

    except pd.errors.EmptyDataError:
        raise ValidationError("數據檔案為空")
    except Exception as e:
        if isinstance(e, ValidationError):
            raise
        raise ValidationError(f"讀取數據檔案失敗: {e}")

    logger.info(f"訓練參數驗證通過 - 檔案: {data_path}, 目標: {goal_col}")


def validate_prediction_inputs(
    data_path: str, target_col: str, features: List[str]
) -> None:
    """
    驗證預測模型訓練參數

    Args:
        data_path: 數據檔案路徑
        target_col: 目標欄位
        features: 特徵欄位清單

    Raises:
        ValidationError: 參數驗證失敗
    """
    errors = []

    # 1. 基本參數檢查
    if not data_path:
        errors.append("數據檔案路徑不可為空")
    elif not os.path.exists(data_path):
        raise FileNotFoundError(data_path)

    if not target_col:
        errors.append("目標欄位不可為空")

    if not features or len(features) == 0:
        errors.append("至少需要指定一個特徵欄位")

    # 如果有基本錯誤，直接拋出
    if errors:
        error_message = "預測參數驗證失敗:\n" + "\n".join(
            f"  - {err}" for err in errors
        )
        logger.error(error_message)
        raise ValidationError(error_message, details={"errors": errors})

    # 2. 檢查數據欄位
    try:
        df_sample = pd.read_csv(data_path, nrows=1)
        missing_cols = []

        if target_col not in df_sample.columns:
            missing_cols.append(target_col)

        for col in features:
            if col not in df_sample.columns:
                missing_cols.append(col)

        if missing_cols:
            raise ValidationError(
                f"數據集缺少欄位: {missing_cols}",
                details={
                    "missing_columns": missing_cols,
                    "available_columns": list(df_sample.columns),
                },
            )

    except pd.errors.EmptyDataError:
        raise ValidationError("數據檔案為空")
    except Exception as e:
        if isinstance(e, ValidationError):
            raise
        raise ValidationError(f"讀取數據檔案失敗: {e}")

    logger.info(f"預測參數驗證通過 - 檔案: {data_path}, 目標: {target_col}")


def validate_dataframe(
    df: pd.DataFrame,
    min_rows: Optional[int] = None,
    required_columns: Optional[List[str]] = None,
) -> None:
    """
    驗證 DataFrame 的基本屬性

    Args:
        df: 要驗證的 DataFrame
        min_rows: 最小行數要求
        required_columns: 必要的欄位清單

    Raises:
        ValidationError: 驗證失敗
    """
    # 檢查是否為空
    if df is None or df.empty:
        raise ValidationError("DataFrame 為空")

    # 檢查最小行數
    if min_rows is not None and len(df) < min_rows:
        raise ValidationError(
            f"數據量不足: 需要至少 {min_rows} 行，實際只有 {len(df)} 行",
            details={"required": min_rows, "actual": len(df)},
        )

    # 檢查必要欄位
    if required_columns:
        missing = [col for col in required_columns if col not in df.columns]
        if missing:
            raise ValidationError(
                f"缺少必要欄位: {missing}",
                details={
                    "missing_columns": missing,
                    "available_columns": list(df.columns),
                },
            )

    logger.debug(f"DataFrame 驗證通過 - 形狀: {df.shape}")


def validate_hyperparameters(
    hyperparams: Dict[str, Any], schema: Dict[str, Dict[str, Any]]
) -> None:
    """
    驗證超參數

    Args:
        hyperparams: 超參數字典
        schema: 驗證規則，格式:
            {
                "param_name": {
                    "type": int/float/str,
                    "min": minimum_value (可選),
                    "max": maximum_value (可選),
                    "choices": [allowed_values] (可選)
                }
            }

    Raises:
        ValidationError: 驗證失敗
    """
    errors = []

    for param_name, rules in schema.items():
        if param_name not in hyperparams:
            continue  # 允許缺少參數（使用預設值）

        value = hyperparams[param_name]
        expected_type = rules.get("type")

        # 類型檢查
        if expected_type and not isinstance(value, expected_type):
            try:
                # 嘗試轉換
                value = expected_type(value)
                hyperparams[param_name] = value
            except (ValueError, TypeError):
                errors.append(
                    f"參數 '{param_name}' 類型錯誤: 預期 {expected_type.__name__}, 實際 {type(value).__name__}"
                )
                continue

        # 範圍檢查
        if "min" in rules and value < rules["min"]:
            errors.append(f"參數 '{param_name}' 值 {value} 小於最小值 {rules['min']}")

        if "max" in rules and value > rules["max"]:
            errors.append(f"參數 '{param_name}' 值 {value} 大於最大值 {rules['max']}")

        # 選項檢查
        if "choices" in rules and value not in rules["choices"]:
            errors.append(
                f"參數 '{param_name}' 值 {value} 不在允許的選項中: {rules['choices']}"
            )

    if errors:
        error_message = "超參數驗證失敗:\n" + "\n".join(f"  - {err}" for err in errors)
        logger.error(error_message)
        raise ValidationError(error_message, details={"errors": errors})

    logger.debug("超參數驗證通過")
