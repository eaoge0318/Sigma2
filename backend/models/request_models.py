"""
API Request/Response 資料模型
"""

from pydantic import BaseModel
from typing import Dict, Any, List, Optional


class InferenceRequest(BaseModel):
    data: Dict[str, Any]
    measure_value: Optional[float] = None
    session_id: str = "default"


class ChatRequest(BaseModel):
    messages: List[Dict[str, Any]]
    session_id: str = "default"


class SaveFileRequest(BaseModel):
    filename: str
    headers: List[str]
    rows: List[List[Any]]


class AdvancedAnalysisRequest(BaseModel):
    filename: str
    target_column: str
    algorithm: str  # 'xgboost' or 'correlation'


class TrainRequest(BaseModel):
    config: Dict[str, Any]
    filename: Optional[str] = None


class ChartAIReportRequest(BaseModel):
    """圖表AI報告請求"""

    session_id: str = "default"
    days: int = 30  # 分析最近幾天的數據


class ChartAIChatRequest(BaseModel):
    """圖表AI對話請求"""

    messages: List[Dict[str, Any]]
    session_id: str = "default"
    days: int = 30  # 使用最近幾天的數據作為上下文


class QuickAnalysisRequest(BaseModel):
    """空值分析請求"""

    filename: str
    headers: List[str]
    rows: List[List[Any]]
    filters: Optional[List[Dict[str, Any]]] = None
    session_id: str = "default"
