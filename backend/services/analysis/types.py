from typing import Dict, Any, List, Optional, Union
from pydantic import BaseModel, Field
from llama_index.core.workflow import Event

# --- Event Definitions ---


class StartEvent(Event):
    """
    Workflow 啟動事件
    """

    query: str
    file_id: str
    session_id: str
    history: str = ""


class IntentEvent(Event):
    """
    意圖識別後的事件
    """

    query: str
    intent: str  # "analysis", "chat", "translation"
    file_id: str
    session_id: str
    history: str


class AnalysisEvent(Event):
    """
    觸發地端分析的事件 (支援自我糾錯循環)
    """

    query: str
    file_id: str
    session_id: str
    history: str
    retry_count: int = 0  # 用於限制遞迴次數


class MonologueEvent(Event):
    """
    Agent 的內部獨白與工具決策事件
    """

    monologue: str
    tool_name: str
    tool_params: Dict[str, Any]
    query: str
    file_id: str
    session_id: str
    history: str
    retry_count: int = 0


class ConceptExpansionEvent(Event):
    """
    當搜尋失敗時，請求 LLM 擴展概念的事件 (自我糾錯)
    """

    query: str
    original_concept: str
    file_id: str
    session_id: str
    history: str
    retry_count: int


class VisualizingEvent(Event):
    """
    數據可視化/繪圖站的事件
    """

    data: Any  # 前一步驟的分析結果 (通常是 List[Dict])
    query: str
    session_id: str
    history: str
    row_count: int = 0
    col_count: int = 0
    mappings: Dict[str, str] = {}


class SummarizeEvent(Event):
    """
    執行結果總結的事件 (包含可選的圖表 JSON)
    """

    data: Any
    query: str
    session_id: str
    history: str
    chart_json: Optional[str] = None
    row_count: int = 0
    col_count: int = 0


class ProgressEvent(Event):
    """
    通用進度/狀態更新事件，用於傳遞給前端顯示詳細步驟
    """

    msg: str


class StopEvent(Event):
    """
    Workflow 結束事件
    """

    result: str


# --- Data Models (Pydantic) ---


class AnalysisResult(BaseModel):
    """
    標準分析結果模型
    """

    summary: str
    data: Optional[List[Dict[str, Any]]] = None
    chart: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
