from abc import ABC, abstractmethod
from typing import Dict, Any, List


class AnalysisTool(ABC):
    """分析工具抽象基類"""

    def __init__(self, analysis_service):
        self.analysis_service = analysis_service

    @property
    @abstractmethod
    def name(self) -> str:
        """工具名稱"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """工具描述"""
        pass

    @property
    def required_params(self) -> List[str]:
        """必需參數列表（子類可覆蓋）"""
        return ["file_id"]

    @abstractmethod
    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        """
        執行工具

        Args:
            params: 工具參數
            session_id: 用戶會話 ID

        Returns:
            工具執行結果
        """
        pass

    def validate_params(self, params: Dict) -> bool:
        """驗證參數完整性"""
        return all(p in params for p in self.required_params)
