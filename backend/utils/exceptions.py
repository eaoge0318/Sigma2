"""
自定義異常類別
提供結構化的錯誤處理機制
"""

from typing import Optional, Dict, Any


class Sigma2Exception(Exception):
    """基礎異常類別"""

    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_ERROR",
        status_code: int = 500,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        """轉換為字典格式"""
        return {"error": self.message, "code": self.code, "details": self.details}


class ValidationError(Sigma2Exception):
    """數據驗證錯誤"""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message, code="VALIDATION_ERROR", status_code=400, details=details
        )


class FileNotFoundError(Sigma2Exception):
    """檔案不存在錯誤"""

    def __init__(self, filepath: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=f"檔案不存在: {filepath}",
            code="FILE_NOT_FOUND",
            status_code=404,
            details=details or {"filepath": filepath},
        )


class InvalidSessionError(Sigma2Exception):
    """無效的 Session ID 錯誤"""

    def __init__(self, session_id: str):
        super().__init__(
            message=f"無效的 Session ID: {session_id}",
            code="INVALID_SESSION",
            status_code=400,
            details={"session_id": session_id},
        )


class ModelTrainingError(Sigma2Exception):
    """模型訓練錯誤"""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message, code="TRAINING_ERROR", status_code=500, details=details
        )


class DataProcessingError(Sigma2Exception):
    """數據處理錯誤"""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="DATA_PROCESSING_ERROR",
            status_code=500,
            details=details,
        )


class ConfigurationError(Sigma2Exception):
    """配置錯誤"""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="CONFIGURATION_ERROR",
            status_code=500,
            details=details,
        )


class SecurityError(Sigma2Exception):
    """安全錯誤"""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message, code="SECURITY_ERROR", status_code=403, details=details
        )
