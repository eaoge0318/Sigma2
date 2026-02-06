"""
安全性工具
提供路徑驗證、Session ID 清理等安全功能
"""

import re
import os
from pathlib import Path
from typing import Optional
from backend.utils.exceptions import SecurityError, InvalidSessionError
from backend.utils.logger import get_logger

logger = get_logger(__name__)


def sanitize_session_id(session_id: str) -> str:
    """
    清理並驗證 session ID

    Args:
        session_id: 原始 session ID

    Returns:
        清理後的 session ID

    Raises:
        InvalidSessionError: 如果 session ID 無效
    """
    if not session_id or not isinstance(session_id, str):
        raise InvalidSessionError("Session ID 不可為空")

    # 移除所有非字母數字、底線、中線的字元
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", session_id)

    if not safe_id:
        logger.warning(f"無效的 session ID 被過濾: {session_id}")
        raise InvalidSessionError(session_id)

    # 防止路徑穿越攻擊
    if ".." in safe_id or "/" in safe_id or "\\" in safe_id:
        logger.warning(f"偵測到路徑穿越嘗試: {session_id}")
        raise SecurityError(f"Session ID 包含非法字元: {session_id}")

    # 長度限制 (防止過長的 ID)
    if len(safe_id) > 100:
        logger.warning(f"Session ID 過長 ({len(safe_id)} 字元): {safe_id[:50]}...")
        raise InvalidSessionError("Session ID 過長 (最多 100 字元)")

    # 如果清理後與原始不同，記錄警告
    if safe_id != session_id:
        logger.warning(f"Session ID 已清理: '{session_id}' -> '{safe_id}'")

    return safe_id


def sanitize_filename(filename: str) -> str:
    """
    清理並驗證檔案名稱

    Args:
        filename: 原始檔案名稱

    Returns:
        清理後的檔案名稱

    Raises:
        SecurityError: 如果檔案名稱無效
    """
    if not filename or not isinstance(filename, str):
        raise SecurityError("檔案名稱不可為空")

    # 移除路徑部分，只保留檔案名稱
    filename = os.path.basename(filename)

    # 防止路徑穿越
    if ".." in filename or "/" in filename or "\\" in filename:
        logger.warning(f"偵測到檔案名稱路徑穿越嘗試: {filename}")
        raise SecurityError(f"檔案名稱包含非法字元: {filename}")

    # 檢查空檔名
    if not filename.strip():
        raise SecurityError("檔案名稱不可為空")

    return filename


def validate_file_path(file_path: str, base_dir: str, must_exist: bool = False) -> Path:
    """
    驗證檔案路徑的安全性，確保路徑在允許的基礎目錄內

    Args:
        file_path: 要驗證的檔案路徑
        base_dir: 基礎目錄
        must_exist: 是否必須存在

    Returns:
        驗證後的 Path 物件

    Raises:
        SecurityError: 如果路徑不安全
        FileNotFoundError: 如果 must_exist=True 且檔案不存在
    """
    try:
        # 解析為絕對路徑
        base = Path(base_dir).resolve()
        target = Path(file_path).resolve()

        # 確保基礎目錄存在
        if not base.exists():
            logger.warning(f"基礎目錄不存在，將建立: {base}")
            base.mkdir(parents=True, exist_ok=True)

        # 檢查目標路徑是否在基礎目錄內
        try:
            target.relative_to(base)
        except ValueError:
            logger.warning(f"路徑穿越嘗試: {file_path} 不在 {base_dir} 內")
            raise SecurityError(
                f"拒絕存取: 路徑在允許的目錄之外",
                details={"path": str(file_path), "base_dir": str(base_dir)},
            )

        # 檢查是否存在 (如果需要)
        if must_exist and not target.exists():
            raise FileNotFoundError(str(target))

        return target

    except Exception as e:
        if isinstance(e, (SecurityError, FileNotFoundError)):
            raise
        logger.error(f"路徑驗證失敗: {file_path}, 錯誤: {e}")
        raise SecurityError(f"路徑驗證失敗: {str(e)}")


def sanitize_draft_id(draft_id: str) -> str:
    """
    清理並驗證 draft ID

    Args:
        draft_id: 原始 draft ID

    Returns:
        清理後的 draft ID

    Raises:
        SecurityError: 如果 draft ID 無效
    """
    if not draft_id or not isinstance(draft_id, str):
        raise SecurityError("Draft ID 不可為空")

    # 只允許字母數字、底線、中線
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", draft_id)

    if not safe_id:
        logger.warning(f"無效的 draft ID: {draft_id}")
        raise SecurityError(f"Draft ID 包含非法字元: {draft_id}")

    # 防止路徑穿越
    if ".." in safe_id or "/" in safe_id or "\\" in safe_id:
        logger.warning(f"Draft ID 路徑穿越嘗試: {draft_id}")
        raise SecurityError(f"Draft ID 包含非法字元")

    # 長度限制
    if len(safe_id) > 200:
        raise SecurityError("Draft ID 過長 (最多 200 字元)")

    return safe_id


def validate_column_name(
    column_name: str, allowed_columns: Optional[list] = None
) -> str:
    """
    驗證欄位名稱

    Args:
        column_name: 欄位名稱
        allowed_columns: 允許的欄位清單 (可選)

    Returns:
        驗證後的欄位名稱

    Raises:
        SecurityError: 如果欄位名稱無效
    """
    if not column_name or not isinstance(column_name, str):
        raise SecurityError("欄位名稱不可為空")

    # 檢查 SQL 注入風險字元
    dangerous_chars = [
        ";",
        "--",
        "/*",
        "*/",
        "xp_",
        "sp_",
        "DROP",
        "DELETE",
        "INSERT",
        "UPDATE",
    ]
    column_upper = column_name.upper()

    for char in dangerous_chars:
        if char in column_upper:
            logger.warning(f"欄位名稱包含危險字元: {column_name}")
            raise SecurityError(f"欄位名稱包含非法字元: {column_name}")

    # 如果有允許清單，檢查是否在清單中
    if allowed_columns is not None and column_name not in allowed_columns:
        raise SecurityError(f"欄位名稱不在允許清單中: {column_name}")

    return column_name
