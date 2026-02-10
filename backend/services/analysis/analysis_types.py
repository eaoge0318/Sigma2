from typing import Any, Dict, List, Optional
from llama_index.core.workflow import Event


class StartEvent(Event):
    """
    Workflow 啟動事件
    """

    query: str
    file_id: str
    session_id: str
    history: str = ""
    mode: str = "fast"


class IntentEvent(Event):
    """
    意圖識別結果事件
    """

    query: str
    intent: str
    file_id: str
    session_id: str
    history: str
    mode: str = "fast"


class AnalysisEvent(Event):
    """
    需要執行數據查詢/工具分析的事件 (支持循環分析)
    """

    query: str
    file_id: str
    session_id: str
    history: str
    mode: str = "fast"
    step_count: int = 1  # 記錄當前是第幾步分析 (防止無窮迴圈)
    prev_results: List[Dict] = []  # 存儲前幾步的工具執行結果，用於整合


class TranslationEvent(Event):
    """
    執行對話或簡單翻譯的事件
    """

    query: str
    file_id: str
    session_id: str
    history: str
    mode: str = "fast"


class MonologueEvent(Event):
    """
    AI 思考過程與工具決策的事件 (用於 UI 呈現過程)
    """

    monologue: str
    tool_name: Optional[str]
    tool_params: Optional[Dict]
    query: str
    file_id: str
    session_id: str
    history: str
    mode: str = "fast"


class ToolCallEvent(Event):
    """
    工具調用事件 (用於追蹤)
    """

    tool: str
    params: Dict


class ToolResultEvent(Event):
    """
    工具結果事件
    """

    tool: str
    result: Any


class VisualizingEvent(Event):
    """
    數據已備好，需要進行圖表繪製的事件
    """

    data: Any
    query: str
    file_id: str
    session_id: str
    history: str
    mode: str = "fast"
    row_count: int = 0
    col_count: int = 0
    mappings: Dict = {}


class SummarizeEvent(Event):
    """
    執行結果總結的事件 (最終回應)
    """

    data: Any
    query: str
    file_id: str
    session_id: str
    history: str
    mode: str = "fast"
    chart_json: Optional[str] = None
    row_count: int = 0
    col_count: int = 0
    mappings: Dict = {}


class ErrorEvent(Event):
    """
    分析失敗事件
    """

    error: str
    query: str
    file_id: str
    session_id: str


class ProgressEvent(Event):
    """
    向前端發送進度狀態的事件
    """

    msg: str


class TextChunkEvent(Event):
    """
    向前端發送打字機效果文字片段的事件
    """

    content: str
