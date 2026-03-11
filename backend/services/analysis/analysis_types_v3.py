"""
V3 分析系統 — 資料合約 (Pydantic Models + Workflow Events)
============================================================
簡化版: 移除 track/playbook/SceneSpec，讓 task_type 成為主角
"""

from typing import Any, Dict, List, Literal, Optional
from llama_index.core.workflow import Event, StartEvent
from pydantic import BaseModel, Field


# ============================================================
# 1. Workflow Events
# ============================================================


class V3StartEvent(StartEvent):
    """V3 Workflow 啟動事件"""

    query: str
    file_id: str
    session_id: str
    history: str = ""
    mode: str = "fast"
    conversation_id: str = "default"
    # UI metadata override (from mining modal or confirmation panel)
    suspect_params: Optional[List[str]] = None
    target_range: Optional[str] = None
    baseline_range: Optional[str] = None
    optimization_targets: Optional[List[dict]] = None


class IntentConfirmationEvent(Event):
    """route_intent 完成後回傳給前端確認的事件 (不繼續分析)"""

    task_type: str = "general"
    restatement: str = ""
    target_params: List[str] = Field(default_factory=list)
    target_range: List[str] = Field(default_factory=list)
    baseline_range: str = ""


class RouteCompleteEvent(Event):
    """RouteIntent 完成後的路由事件"""

    route_result: "RouteIntentOutput"
    query: str
    file_id: str
    session_id: str
    history: str = ""
    use_code_interpreter: bool = False


class ToolExecuteEvent(Event):
    """工具執行事件 (RouteIntent 完成 -> 執行工具鏈 或 Code Interpreter)"""

    route_result: "RouteIntentOutput"
    query: str = ""  # 原始用戶 query
    file_id: str
    session_id: str
    mode: str = "tool"  # "tool" | "code"


class AnalysisDoneEvent(Event):
    """分析完成事件 → 傳給 Humanizer"""

    result: "PlaybookResult"
    restatement: str
    file_id: str
    session_id: str
    data_summary: str = ""
    skip_humanizer: bool = False
    prep: Optional[dict] = None  # preprocess 結構化數據，供 evidence evaluator 使用
    chart_titles: Optional[list] = (
        None  # 各輪圖表標題，供 chart-to-finding mapping 使用
    )


# ============================================================
# 2. RouteIntent I/O 合約 (簡化版)
# ============================================================


class RouteIntentOutput(BaseModel):
    """
    RouteIntent 的 LLM 輸出規格 (簡化版)
    整個 V3 系統的成敗取決於這個輸出的準確性。

    欄位:
      restatement         — 需求重述
      task_type            — 任務類型 (主角)
      target_params        — 目標參數列表
      target_range         — 分析區間
      has_y               — 是否有明確目標變數 (衍生值)
      suggested_tools      — LLM 選的工具鏈 (最多 12 個)
      clarification_question — 追問問題 (有值時不跑工具)
    """

    restatement: str = Field(..., description="需求重述 (補齊用戶沒說的部分)")

    # 任務屬性 — 主角，決定分析方向
    task_type: str = Field(
        "general",
        description=(
            "任務類型: anomaly_detection(異常檢測) / drift_analysis(製程飄移) / "
            "optimization(最佳化與參數調整) / spec_recommendation(製程參數建議規格) / "
            "global_analysis(全域分析) / general(一般分析)"
        ),
    )

    # 分析目標
    target_params: List[str] = Field(default_factory=list, description="目標參數 (Y)")
    reference_params: List[str] = Field(
        default_factory=list,
        description="對照參數 (用於比較，例如正常參數組)",
    )
    target_range: List[str] = Field(
        default_factory=list,
        description="目標區間 (例如 ['50-69', '198-204'])，空 list = 全域",
    )
    baseline_range: str = Field(
        "",
        description="對照區間 (例如 good lot 的 Row 範圍，空字串表示未指定)",
    )
    has_y: bool = Field(True, description="是否有明確的 Y (目標變數)")

    # 工具鏈 — LLM 根據 task_type + 場景組合選取 (最多 12 個)
    suggested_tools: List[str] = Field(
        default_factory=list,
        description="建議使用的工具名稱列表 (最多 12 個)",
    )

    # 追問 — 有值時不跑工具，直接回覆用戶
    clarification_question: Optional[str] = Field(
        None, description="追問用戶的問題 (有值時不執行分析)"
    )

    # 優化控制參數 (從前端 modal 傳入)
    optimization_targets: Optional[List[dict]] = Field(
        None, description="優化目標 [{param, direction, target_value?, lsl?, usl?}]"
    )


# ============================================================
# 3. 執行結果合約
# ============================================================


class ToolChainResult(BaseModel):
    """單個工具的執行結果"""

    tool_name: str
    params: Dict = Field(default_factory=dict)
    success: bool = True
    result: Any = None
    error: Optional[str] = None


class PlaybookResult(BaseModel):
    """工具鏈的最終結構化輸出 → 傳給 Humanizer"""

    task_type: str = Field("general", description="任務類型")
    status: Literal["ok", "no_anomaly_found", "error", "partial"] = "ok"
    key_findings: List[str] = Field(default_factory=list, description="關鍵發現")
    tool_results: List[ToolChainResult] = Field(
        default_factory=list, description="工具執行結果"
    )
    auto_target_summary: str = Field("", description="AutoTarget 摘要文字")
    charts: List[Dict] = Field(default_factory=list, description="圖表數據")


# ============================================================
# 4. Context 管理
# ============================================================


class DiscoveryEntry(BaseModel):
    """
    結構化發現條目 (取代 V2 的自由文本 current_knowledge)
    每條約 30 tokens，最多保留 20 條 = ~600 tokens (可控)
    """

    round: int = Field(0, description="第幾輪對話")
    source: str = Field("", description="來源工具名稱")
    finding: str = Field(
        ..., description="發現摘要, 如 'Row 20-50 T2 異常 (分數=12.3)'"
    )
    params: List[str] = Field(default_factory=list, description="相關參數")
    confidence: str = Field("suspected", description="confirmed / suspected")


class V3SessionContext(BaseModel):
    """V3 Session 級別的 Context (跨追問保留)"""

    last_restatement: str = ""
    last_key_findings: List[str] = Field(default_factory=list)
    last_target_params: List[str] = Field(default_factory=list)

    # 結構化發現日志
    current_knowledge: List[DiscoveryEntry] = Field(default_factory=list)
    round_counter: int = 0
