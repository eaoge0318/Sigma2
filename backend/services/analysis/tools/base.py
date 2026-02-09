from abc import ABC, abstractmethod
from typing import Dict, Any, List
import logging

logger = logging.getLogger(__name__)


class AnalysisTool(ABC):
    """
    所有分析工具的基類
    定義了標準的執行接口
    """

    def __init__(self, service):
        """
        初始化工具

        Args:
            service: AnalysisService 實例，用於訪問數據和索引
        """
        self.service = service
        # 僅在子類未定義時才設置預設值
        if not hasattr(self, "name") or self.name == "base_tool":
            self.name = "base_tool"
        if not hasattr(self, "description") or self.description == "Base analysis tool":
            self.description = "Base analysis tool"
        if not hasattr(self, "required_params"):
            self.required_params = []

    @abstractmethod
    def execute(self, params: Dict[str, Any], session_id: str) -> Dict[str, Any]:
        """
        執行工具邏輯

        Args:
            params: 工具參數字典
            session_id: 會話 ID

        Returns:
            Dict: 執行結果
        """
        pass

    def validate_params(self, params: Dict[str, Any]) -> List[str]:
        """
        驗證參數是否存在

        Returns:
            缺少的參數列表
        """
        missing = []
        for param in self.required_params:
            if param not in params:
                missing.append(param)
        return missing
