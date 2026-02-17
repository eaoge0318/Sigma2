from typing import Any, Dict, List, Optional
from llama_index.core.workflow import Event
from pydantic import BaseModel, Field


class StartEvent(Event):
    """
    Workflow 啟動事件
    """

    query: str
    file_id: str
    session_id: str
    history: str = ""
    mode: str = "fast"
    suspect_pool: List[str] = []  # 參數嫌疑犯
    suspect_range: Optional[str] = None  # 樣本嫌疑犯（筆數範圍）


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
    suspect_pool: List[str] = []
    suspect_range: Optional[str] = None


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
    suspect_pool: List[str] = []  # 參數嫌疑犯
    suspect_range: Optional[str] = None  # 樣本嫌疑犯（筆數範圍）


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
    suspect_pool: List[str] = []


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
    suspect_pool: List[str] = []


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


class AnomalousSite(BaseModel):
    """
    異常站點 (Anomalous Site)
    記錄各個發現的異常樣本區間及其顯著度。
    """

    range: str = Field(..., description="異常區間 (e.g., '100-150')")
    score: float = Field(0.0, description="異常分數/明顯度 (Hotelling T2 or LOF score)")
    primary_params: List[str] = Field(
        default_factory=list, description="該區間主導異常的參數"
    )
    status: str = "PENDING"  # PENDING, ANALYZING, COMPLETED
    finding_summary: str = ""


# --- [NEW] 4-Variable Context & Role Types ---


class AnalysisContext(BaseModel):
    """
    四維分析語境 (4-Variable Context)
    這是全系統的核心資料結構，用於描述每一層 Why 的分析環境。
    """

    targets: List[str] = Field(
        default_factory=list, description="當前分析的目標變數 (Symptom/Effect)"
    )
    feature_pool: List[str] = Field(
        default_factory=list, description="潛在的原因變數池 (Cause Candidates)"
    )
    focus_range: Optional[str] = Field(
        None, description="關注的異常數據範圍 (Focus/Experimental Group)"
    )
    baseline_range: Optional[str] = Field(
        None, description="用於對照的正常數據範圍 (Baseline/Control Group)"
    )


class StepResult(BaseModel):
    """
    單步分析結果記錄
    """

    role: str  # 執行角色 (Specialist, Evaluator...)
    tool_name: Optional[str] = None
    tool_params: Optional[Dict] = None
    evidence: Any = None  # 工具執行結果 (P-values, Scores...)
    conclusion: str = ""  # 該步的簡短結論
    timestamp: float = 0.0


class StateSnapshot(BaseModel):
    """
    狀態快照 (State Snapshot)
    用於版本控制與回溯
    """

    version: int
    timestamp: str
    modified_by: str
    changes: Dict[str, Any]


class AnalysisState(BaseModel):
    """
    分析任務的整體狀態機 (State Persistence)
    """

    # [NEW] Version Control
    version: int = Field(1, description="狀態版本號")
    snapshots: List[StateSnapshot] = Field(default_factory=list, description="歷史快照")

    session_id: str
    file_id: str
    original_query: str
    strategy_plan: str = ""  # Evaluator 擬定的初始策略
    current_context: AnalysisContext
    history: List[StepResult] = []
    status: str = "IDLE"  # IDLE, PLANNING, EXECUTING, REVIEWING, FINISHED

    # [NEW] Decision Logic Enhancements
    evaluator_feedback: str = ""  # The latest command/feedback from Evaluator (Role 0)
    thought_history: List[
        str
    ] = []  # Accumulated insights/thoughts from each step (Role 0 memory)
    causal_chain: List[str] = Field(
        default_factory=list, description="記錄已發現的因果鏈路 (e.g., A -> B -> C)"
    )
    analysis_roadmap: List[str] = Field(
        default_factory=list, description="待完成的分析任務清單"
    )
    current_knowledge: str = Field(
        "", description="目前的定論摘要 (Rolling Summary / Dashboard)"
    )
    discovered_sites: List[AnomalousSite] = Field(
        default_factory=list, description="記錄所有發現的異常樣本區間與其顯著度"
    )
    data_summary: str = Field(
        "", description="數據集摘要 (e.g., '500 rows, 30 columns')"
    )
    data_schema: Dict[str, Any] = Field(
        default_factory=dict, description="數據欄位型態與定義"
    )

    # [NEW] Rolling Summary System
    rolling_summary: str = Field(
        "", description="滾動摘要：每 3 步由 Synthesizer 更新，濃縮歷史發現"
    )
    summary_update_counter: int = Field(
        0, description="距離上次更新 rolling_summary 的步數"
    )

    step_count: int = 1
    max_steps: int = 5
    used_tools_history: List[str] = Field(
        default_factory=list, description="已使用工具名稱歷史 (含重複)"
    )
    failed_experiments: List[str] = Field(
        default_factory=list, description="失敗的工具+參數組合 (不可重試)"
    )

    def update(self, role_name: str, **kwargs) -> "AnalysisState":
        """
        不可變更新模式 (Immutable Update)
        建立快照並回傳新的 State 實例
        """
        from datetime import datetime

        # 1. 建立快照
        snapshot = StateSnapshot(
            version=self.version,
            timestamp=datetime.now().isoformat(),
            modified_by=role_name,
            changes=kwargs,
        )

        # 2. 準備更新資料
        update_data = kwargs.copy()
        update_data["version"] = self.version + 1
        update_data["snapshots"] = self.snapshots + [snapshot]

        # 3. 建立新實例 (使用 model_copy 或 copy)
        # Pydantic v1 uses copy(update=...), v2 uses model_copy(update=...)
        # 假設是 v1 或 v2 兼容寫法，或是直接用 copy
        new_state = self.copy(update=update_data)

        return new_state


class RoleInput(BaseModel):
    """
    角色間通訊協議 - 輸入
    """

    state_machine: AnalysisState
    directive: Optional[str] = None  # 上級角色的指令 (e.g. "Check for drill down")

    # [NEW] V2 Architecture Fields
    experiments: List["ExperimentContext"] = Field(default_factory=list)
    evidences: List["Evidence"] = Field(default_factory=list)


class RoleOutput(BaseModel):
    """
    角色間通訊協議 - 輸出
    """

    decision: str  # "CONTINUE", "PIVOT", "FINISH", "WAIT"
    new_context: Optional[AnalysisContext] = None
    updates: Dict[str, Any] = {}
    reasoning: str = ""
    structured_log: Dict[str, Any] = Field(
        default_factory=dict,
        description="Key insights for logging (e.g., {'strategy': '...', 'causal_chain': [...]})",
    )

    # --- V2 Extensions (Optional to maintain V1 compatibility) ---
    hypothesis: Optional[str] = None
    directive: Optional[str] = None
    experiments: List["ExperimentContext"] = Field(default_factory=list)
    evidences: List["Evidence"] = Field(default_factory=list)
    analysis_report: Optional["AnalysisReport"] = None


# --- V2 Architecture Types (Batch Analysis) ---


class ExperimentContext(BaseModel):
    """
    [V2] 單一實驗上下文 (由 Planner 產生)
    """

    id: str = Field(..., description="實驗唯一ID")
    objective: str = Field(..., description="實驗目標 (e.g. 'Check Trend')")
    focus_range: Optional[str] = Field(None, description="鎖定區間 (e.g. 'Step 40-50')")
    baseline_range: Optional[str] = Field(None, description="對照區間")
    technique: str = Field(..., description="分析技術 (e.g. 'Trend', 'Correlation')")
    target_columns: List[str] = Field(default_factory=list, description="目標欄位")


class Evidence(BaseModel):
    """
    [V2] 單一實驗證據 (由 Batch Executor 產生)
    """

    experiment_id: str = Field(..., description="對應的實驗ID")
    tool_name: str = Field(..., description="執行的工具名稱")
    tool_params: Dict[str, Any] = Field(..., description="執行的工具參數")
    result: Any = Field(..., description="工具執行結果 (Raw Data or Summary)")
    observation: str = Field(..., description="Executor 的初步觀察")
    status: str = Field("SUCCESS", description="SUCCESS | FAIL")


class AnalysisReport(BaseModel):
    """
    [V2] 綜合分析報告 (由 Synthesizer 產生)
    """

    key_findings: List[str] = Field(..., description="關鍵發現")
    rejected_hypotheses: List[str] = Field(..., description="被排除的假設")
    next_step_suggestion: str = Field(..., description="下一步建議")
    synthesis_logic: str = Field(..., description="綜合判斷邏輯")
