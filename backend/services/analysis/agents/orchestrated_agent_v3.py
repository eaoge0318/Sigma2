"""
V3 分析系統 — 簡化 Workflow (3 步驟)
============================================================
LLM 全程只呼叫 2 次 (RouteIntent + Humanizer)，中間全部純計算。

架構:
  V3StartEvent → route_intent (LLM#1)
    ├── has suggested_tools → execute_tools → AnalysisDoneEvent → humanize (LLM#2)
    └── has clarification_question → StopEvent (直接回覆)
"""

import asyncio
import logging
import re
from typing import Any, Optional

from llama_index.core.workflow import (
    Workflow,
    StopEvent,
    Context,
    step,
)

from backend.services.analysis.analysis_types import (
    MonologueEvent,
    ProgressEvent,
    TextChunkEvent,
)
from backend.services.analysis.analysis_types_v3 import (
    V3StartEvent,
    RouteCompleteEvent,
    RouteIntentOutput,
    ToolExecuteEvent,
    AnalysisDoneEvent,
    PlaybookResult,
    ToolChainResult,
)
from backend.services.analysis.tools.executor import ToolExecutor

logger = logging.getLogger(__name__)


class OrchestratedAnalysisAgentV3(Workflow):
    """
    V3 簡化 Workflow (3 步驟)

    設計原則:
    - LLM 只呼叫 2 次: RouteIntent + Humanizer
    - 中間的工具執行全部是純計算
    - task_type 是主角，決定分析方向
    """

    def __init__(
        self,
        llm: Any,
        tool_executor: ToolExecutor,
        analysis_service: Any = None,
        shared_states: Optional[dict] = None,
        chat_history_service: Any = None,
        **kwargs,
    ):
        super().__init__(timeout=600, **kwargs)
        self.llm = llm
        self.tool_executor = tool_executor
        self.analysis_service = analysis_service
        self._shared_states = shared_states or {}
        self._chat_history = chat_history_service
        # 即時 stdout 串流: 繞過 llama-index event stream
        # 由 router 在 run() 前設定，stream_consumer 推送 (line, round_num)
        self.stdout_queue: Optional[asyncio.Queue] = None

    # ============================================================
    # Session Context 管理
    # ============================================================

    def _get_session_key(self, session_id: str, file_id: str) -> str:
        return f"v3:{session_id}:{file_id}"

    def _load_session_context(self, session_id: str, file_id: str):
        """載入 SessionContext (追問時使用)"""
        from backend.services.analysis.analysis_types_v3 import V3SessionContext

        key = self._get_session_key(session_id, file_id)
        ctx_data = self._shared_states.get(key)
        if ctx_data and isinstance(ctx_data, dict):
            return V3SessionContext(**ctx_data)
        return V3SessionContext()

    def _save_session_context(
        self,
        session_id: str,
        file_id: str,
        restatement: str,
        key_findings: list,
        target_params: list,
        task_type: str = "general",
    ):
        """
        儲存 SessionContext (每輪分析後呼叫)
        current_knowledge 是累積式的，不會被覆蓋
        """
        key = self._get_session_key(session_id, file_id)

        # 載入現有的 context (保留 current_knowledge)
        existing = self._shared_states.get(key, {})
        old_knowledge = existing.get("current_knowledge", [])
        old_round = existing.get("round_counter", 0)
        new_round = old_round + 1

        # 從 key_findings 提取新的 DiscoveryEntry
        new_entries = []
        for finding in key_findings[:10]:
            params = []
            if isinstance(finding, str):
                import re

                params = re.findall(r"[A-Z][A-Z0-9_-]+(?:_[A-Z0-9]+)+", finding)

            new_entries.append(
                {
                    "round": new_round,
                    "source": task_type,
                    "finding": finding[:200],
                    "params": params[:5],
                    "confidence": "suspected",
                }
            )

        # 累積 current_knowledge (最多 20 條)
        all_knowledge = old_knowledge + new_entries
        if len(all_knowledge) > 20:
            all_knowledge = all_knowledge[-20:]

        self._shared_states[key] = {
            "last_restatement": restatement,
            "last_key_findings": key_findings[:10],
            "last_target_params": target_params[:10],
            "current_knowledge": all_knowledge,
            "round_counter": new_round,
        }

    # ============================================================
    # Step 1: RouteIntent (LLM #1)
    # ============================================================

    @step
    async def route_intent(
        self, ctx: Context, ev: V3StartEvent
    ) -> RouteCompleteEvent | StopEvent:
        """
        [LLM #1] 意圖路由: 填寫統一合約

        快速通道: [QUICK_SCAN] / [DRAW:xxx] / [TOOL:xxx] 前綴直接短路
        元資料前綴: [TASK:] / [PARAMS:] / [RANGE:] 覆蓋 LLM 推斷
        一般問句: 1 次 LLM 完成所有判斷
        """
        from backend.services.analysis.agents.roles_v3.route_intent import (
            RouteIntentAgent,
        )

        query = ev.query.strip()
        logger.info(f"[V3:RouteIntent] query={query[:80]!r}")

        ctx.write_event_to_stream(ProgressEvent(msg="正在解析意圖...", turn=0))

        # --- 複合前綴提取器 ---
        import re

        # 預設走 Code Interpreter 模式
        # 只有 [QUICK_SCAN], [DRAW:], [TOOL:] 等特殊前綴才走 Tool 模式
        use_code_interpreter = True

        # [CODE] 前綴: 相容舊格式，剝離前綴
        if query.startswith("[CODE]"):
            query = query[len("[CODE]") :].strip()
            logger.info("[V3:RouteIntent] [CODE] 前綴偵測 (已為預設 CI 模式)")

        # use_code_interpreter 會透過 RouteCompleteEvent 傳遞到 dispatch

        prefix_task_type = None
        prefix_params = []
        prefix_range = None

        m = re.search(r"\[TASK:(\w+)\]", query)
        if m:
            prefix_task_type = m.group(1)
            query = query.replace(m.group(0), "").strip()

        m = re.search(r"\[PARAMS:([^\]]+)\]", query)
        if m:
            prefix_params = [p.strip() for p in m.group(1).split(",") if p.strip()]
            query = query.replace(m.group(0), "").strip()

        m = re.search(r"\[RANGE:([^\]]+)\]", query)
        if m:
            prefix_range = m.group(1).strip()
            query = query.replace(m.group(0), "").strip()

        if prefix_task_type or prefix_params or prefix_range:
            logger.info(
                f"[V3:RouteIntent] 前綴提取: task={prefix_task_type}, "
                f"params={prefix_params}, range={prefix_range}"
            )

        # --- 快速通道: [QUICK_SCAN] ---
        if query.startswith("[QUICK_SCAN]"):
            clean_query = query.replace("[QUICK_SCAN]", "").strip()
            route_result = RouteIntentOutput(
                restatement=f"快速掃描: {clean_query or '全域四合一掃描'}",
                task_type="global_analysis",
                has_y=False,
                suggested_tools=["combo_parameter_profiling"],
            )
            logger.info("[V3:RouteIntent] 快速通道 → QUICK_SCAN")
            return RouteCompleteEvent(
                route_result=route_result,
                query=clean_query or query,
                file_id=ev.file_id,
                session_id=ev.session_id,
                history=ev.history,
                use_code_interpreter=False,  # QUICK_SCAN 走 Tool 模式
            )

        # --- 快速通道: [DRAW:xxx] ---
        if query.startswith("[DRAW:"):
            param_name = query.split("]")[0].replace("[DRAW:", "").strip()
            route_result = RouteIntentOutput(
                restatement=f"繪製 {param_name} 的趨勢圖",
                task_type="general",
                has_y=True,
                target_params=[param_name],
                suggested_tools=["draw_trend"],
            )
            logger.info(f"[V3:RouteIntent] 快速通道 → DRAW:{param_name}")
            return RouteCompleteEvent(
                route_result=route_result,
                query=query,
                file_id=ev.file_id,
                session_id=ev.session_id,
                history=ev.history,
                use_code_interpreter=False,  # DRAW 走 Tool 模式
            )

        # --- 快速通道: [TOOL:xxx] ---
        if query.startswith("[TOOL:"):
            tool_name = query.split("]")[0].replace("[TOOL:", "").strip()
            rest_query = query.split("]", 1)[1].strip() if "]" in query else ""
            route_result = RouteIntentOutput(
                restatement=f"使用 {tool_name} 進行分析",
                task_type="general",
                has_y=False,
                suggested_tools=[tool_name],
            )
            logger.info(f"[V3:RouteIntent] 快速通道 → TOOL:{tool_name}")
            return RouteCompleteEvent(
                route_result=route_result,
                query=rest_query or query,
                file_id=ev.file_id,
                session_id=ev.session_id,
                history=ev.history,
                use_code_interpreter=False,  # TOOL 走 Tool 模式
            )

        # --- 快速通道: [DIRECT_TOOL] sigma_utils 直接執行 (不跑 LLM) ---
        if query.startswith("[DIRECT_TOOL]"):
            result = await self._run_direct_tool(ctx, ev, query)
            return result

        # --- 正式 LLM 路由 ---
        columns = []
        column_mappings = {}
        data_summary = {}

        if self.analysis_service and ev.file_id:
            try:
                import asyncio

                summary_data = await asyncio.to_thread(
                    self.analysis_service.load_summary, ev.session_id, ev.file_id
                )
                if summary_data:
                    columns = summary_data.get("parameters", [])
                    column_mappings = summary_data.get("mappings", {})
                    data_summary = {
                        "row_count": summary_data.get("row_count", 0),
                        "col_count": summary_data.get("col_count", 0),
                    }
            except Exception as e:
                logger.warning(f"[V3:RouteIntent] 載入摘要失敗: {e}")

        # 呼叫 RouteIntent Agent (1 次 LLM)
        agent = RouteIntentAgent(self.llm)
        route_result = await agent.run(
            query=query,
            columns=columns,
            column_mappings=column_mappings,
            data_summary=data_summary,
            history=getattr(ev, "history", ""),
        )

        # --- 前綴覆蓋 ---
        if prefix_task_type:
            route_result.task_type = prefix_task_type
            route_result.clarification_question = None  # 已確認，不再追問
        if prefix_params:
            route_result.target_params = prefix_params
            route_result.has_y = True
        if prefix_range:
            route_result.target_range = prefix_range

        # --- UI metadata 覆蓋 (來自 mining modal 或 confirmation panel) ---
        _has_ui_metadata = False
        if getattr(ev, "suspect_params", None):
            route_result.target_params = ev.suspect_params
            route_result.has_y = True
            _has_ui_metadata = True
        if getattr(ev, "target_range", None):
            route_result.target_range = [ev.target_range]
            _has_ui_metadata = True
        if getattr(ev, "baseline_range", None):
            route_result.baseline_range = ev.baseline_range
            _has_ui_metadata = True

        # --- Intent Confirmation (兩次請求模式) ---
        # 需要確認的 task_type + 沒有 UI metadata → 回傳確認事件，不跑分析
        _NEEDS_CONFIRMATION = {"anomaly_detection", "drift_analysis", "global_analysis"}
        if (
            route_result.task_type in _NEEDS_CONFIRMATION
            and not _has_ui_metadata
            and not prefix_task_type  # 前綴已明確指定，不需確認
        ):
            from backend.services.analysis.analysis_types_v3 import (
                IntentConfirmationEvent,
            )

            logger.info(
                f"[V3:RouteIntent] Confirmation needed for {route_result.task_type}, "
                f"returning IntentConfirmationEvent"
            )
            ctx.write_event_to_stream(
                IntentConfirmationEvent(
                    task_type=route_result.task_type,
                    restatement=route_result.restatement,
                    target_params=route_result.target_params,
                    target_range=route_result.target_range,
                    baseline_range=route_result.baseline_range,
                )
            )
            return StopEvent(
                result={
                    "response": "",
                    "intent_confirmation": True,
                    "task_type": route_result.task_type,
                    "restatement": route_result.restatement,
                    "target_params": route_result.target_params,
                    "target_range": route_result.target_range,
                    "baseline_range": route_result.baseline_range,
                }
            )

        ctx.write_event_to_stream(
            ProgressEvent(msg=f"意圖: {route_result.restatement[:120]}...", turn=0)
        )

        return RouteCompleteEvent(
            route_result=route_result,
            query=query,
            file_id=ev.file_id,
            session_id=ev.session_id,
            history=ev.history,
            use_code_interpreter=use_code_interpreter,
        )

    # ============================================================
    # Step 2: 分發 (純邏輯)
    # ============================================================

    @step
    async def dispatch(
        self, ctx: Context, ev: RouteCompleteEvent
    ) -> ToolExecuteEvent | StopEvent:
        """
        分發: 有工具就執行，有追問就回覆
        """
        route = ev.route_result
        logger.info(
            f"[V3:Dispatch] task_type={route.task_type}, "
            f"tools={len(route.suggested_tools)}, "
            f"clarify={bool(route.clarification_question)}"
        )

        # 追問: 如果是分析類意圖，改為跳 wizard modal 讓用戶選參數
        _NEEDS_CONFIRMATION = {"anomaly_detection", "drift_analysis", "global_analysis"}
        if route.clarification_question:
            # 分析類意圖 → 改為跳 wizard modal
            if route.task_type in _NEEDS_CONFIRMATION or route.task_type == "general":
                from backend.services.analysis.analysis_types_v3 import (
                    IntentConfirmationEvent,
                )

                logger.info(
                    f"[V3:Dispatch] 追問轉為確認 modal: {route.clarification_question[:80]}"
                )
                ctx.write_event_to_stream(
                    IntentConfirmationEvent(
                        task_type=route.task_type
                        if route.task_type != "general"
                        else "anomaly_detection",
                        restatement=route.restatement,
                        target_params=route.target_params,
                        target_range=route.target_range,
                        baseline_range=route.baseline_range,
                    )
                )
                return StopEvent(
                    result={
                        "response": "",
                        "intent_confirmation": True,
                        "task_type": route.task_type,
                        "restatement": route.restatement,
                        "target_params": route.target_params,
                        "target_range": route.target_range,
                        "baseline_range": route.baseline_range,
                    }
                )
            else:
                # 非分析類 (optimization / spec_recommendation 等) → 照舊文字追問
                logger.info(f"[V3:Dispatch] 追問: {route.clarification_question[:80]}")
                ctx.write_event_to_stream(
                    TextChunkEvent(
                        content=f"**{route.restatement}**\n\n{route.clarification_question}"
                    )
                )
                return StopEvent(
                    result={
                        "response": route.clarification_question,
                        "restatement": route.restatement,
                    }
                )

        # 有工具: 進入執行
        return ToolExecuteEvent(
            route_result=route,
            query=ev.query,
            file_id=ev.file_id,
            session_id=ev.session_id,
            mode="code" if ev.use_code_interpreter else "tool",
        )

    # ============================================================
    # Step 3: 工具執行 (純計算)
    # ============================================================

    @step
    async def execute_tools(
        self, ctx: Context, ev: ToolExecuteEvent
    ) -> AnalysisDoneEvent:
        """
        遍歷 suggested_tools 執行工具鏈

        自動推斷參數:
        - 從 registry 查詢 required_params
        - 根據 target_params / target_range 注入
        """
        route = ev.route_result
        task_type = route.task_type
        target_params = route.target_params or []
        target_range = route.target_range or []
        tools = route.suggested_tools

        logger.info(
            f"[V3:Execute] task_type={task_type}, "
            f"tools={tools}, targets={target_params}"
        )

        # === 分析計劃說明 (寫到思考視窗) ===
        _TASK_TYPE_CN = {
            "anomaly_detection": "異常檢測",
            "drift_analysis": "製程飄移分析",
            "optimization": "最佳化與參數調整",
            "spec_recommendation": "製程參數建議規格",
            "global_analysis": "全域分析",
            "general": "一般分析",
        }
        plan_lines = [f"分析需求: {route.restatement}"]
        plan_lines.append(f"任務類型: {_TASK_TYPE_CN.get(task_type, task_type)}")

        if ev.mode == "code":
            # Code Interpreter 模式: 不顯示工具鏈
            plan_lines.append("模式: Code Interpreter (自主規劃)")
        else:
            plan_lines.append(f"工具鏈: {', '.join(tools)}")

        # 統一合約四參數
        reference_params = getattr(route, "reference_params", []) or []
        baseline_range = getattr(route, "baseline_range", "") or ""

        if target_params:
            plan_lines.append(f"目標參數: {', '.join(target_params)}")
        else:
            plan_lines.append("目標參數: (無, 全域模式)")
        if reference_params:
            plan_lines.append(f"對照參數: {', '.join(reference_params)}")
        else:
            plan_lines.append("對照參數: (無)")
        if target_range:
            plan_lines.append(f"目標區間: {', '.join(target_range)}")
        else:
            plan_lines.append("目標區間: 全部資料")
        if baseline_range:
            plan_lines.append(f"對照區間: 第 {baseline_range} 筆")
        else:
            plan_lines.append("對照區間: (無)")
        plan_lines.append(f"有目標變數 (has_y): {route.has_y}")

        ctx.write_event_to_stream(
            MonologueEvent(
                monologue="\n".join(plan_lines),
                tool_name=tools[0] if tools else None,
                tool_params={
                    "task_type": task_type,
                    "target_params": target_params,
                    "reference_params": reference_params,
                    "target_range": target_range,
                    "baseline_range": baseline_range,
                },
                query=route.restatement,
                file_id=ev.file_id,
                session_id=ev.session_id,
                history="",
            )
        )

        # === Code Interpreter 路徑 ===
        if ev.mode == "code":
            logger.info("[V3:Execute] Code Interpreter 模式")
            ctx.write_event_to_stream(
                ProgressEvent(msg="啟動 Code Interpreter...", turn=0)
            )
            return await self._run_code_interpreter(ctx, ev, route)

        # === Deep Chain 判斷 ===
        from backend.services.analysis.agents.deep_chain import (
            should_use_deep_chain,
        )

        chain_key = should_use_deep_chain(task_type, tools, target_params, target_range)
        if chain_key:
            # 走 Deep Chain 路徑 (多層遞進分析)
            logger.info(f"[V3:DeepChain] Activating chain: {chain_key}")
            ctx.write_event_to_stream(
                ProgressEvent(
                    msg=f"啟動深度分析鏈: {chain_key}",
                    turn=0,
                )
            )
            return await self._run_deep_chain(ctx, ev, route, chain_key)

        # === 扁平路徑 (原有邏輯) ===
        return await self._run_flat_tools(
            ctx, ev, route, tools, target_params, target_range
        )

    # ============================================================
    # _run_direct_tool: 直接執行 sigma_utils (不跑 LLM)
    # ============================================================

    async def _run_direct_tool(
        self, ctx: Context, ev: V3StartEvent, raw_query: str
    ) -> StopEvent:
        """
        [DIRECT_TOOL] 快速通道:
        直接執行 sigma_utils 函式，不經過 LLM。
        前端送來格式: [DIRECT_TOOL] func_name(key="val", key2=0.05)
        """
        import re
        import asyncio
        from backend.services.analysis.code_executor import CodeExecutor
        from backend.services.analysis.analysis_types import (
            CodeBlockEvent,
            CodeOutputEvent,
            ChartImageEvent,
        )

        # 1. parse tool_name and params
        body = raw_query.replace("[DIRECT_TOOL]", "").strip()
        m = re.match(r"(\w+)\((.*)\)", body, re.DOTALL)
        if not m:
            ctx.write_event_to_stream(TextChunkEvent(content="❌ 無法解析工具指令格式"))
            return StopEvent(result={"response": "parse error"})

        tool_name = m.group(1)
        params_str = m.group(2).strip()

        logger.info(f"[V3:DirectTool] tool={tool_name}, params={params_str!r}")
        ctx.write_event_to_stream(
            ProgressEvent(msg=f"直接執行: {tool_name}...", turn=0)
        )

        # 2. Load dataframe
        df = None
        if self.analysis_service and ev.file_id:
            try:
                df = await asyncio.to_thread(
                    self.analysis_service.get_dataframe,
                    ev.session_id,
                    ev.file_id,
                )
            except Exception as e:
                logger.error(f"[V3:DirectTool] 載入資料失敗: {e}")

        if df is None:
            ctx.write_event_to_stream(
                TextChunkEvent(content="❌ 資料載入失敗，無法執行")
            )
            return StopEvent(result={"response": "data load error"})

        # 3. Build python code
        # Functions that take series (single col) instead of df
        SERIES_FUNCS = {
            "segment_drift",
            "distribution_shift",
            "classify_anomaly_type",
            "frequency_analysis",
            "wavelet_analysis",
            "trend_prediction",
            "control_loop_assessment",
            "plot_drift",
            "plot_trend",
        }
        # Functions that take two series
        TWO_SERIES_FUNCS = {"cross_correlation_lag"}
        # Functions that need target as string kwarg
        TARGET_KWARG_FUNCS = {
            "top_correlations",
            "residual_analysis",
            "operating_window",
            "feature_importance",
        }
        # Plot scatter needs x, y
        SCATTER_FUNCS = {"plot_scatter"}
        # Compare groups needs index ranges
        GROUP_FUNCS = {"compare_groups", "plot_distribution_compare"}

        # Parse user params into a dict for code generation
        code_lines = [
            "import backend.services.analysis.sigma_utils as sigma",
            "import pandas as pd",
            "import numpy as np",
            "import json",
            "",
            "df_numeric = df.select_dtypes(include='number').fillna(0)",
            "df_active, dead_cols = sigma.filter_dead_columns(df_numeric)",
            "",
        ]

        if tool_name == "filter_dead_columns":
            code_lines += [
                "print(f'活性欄位: {len(df_active.columns)} / {len(df_numeric.columns)}')",
                "if dead_cols:",
                "    print(f'被移除的死水欄位 ({len(dead_cols)}): {dead_cols[:20]}')",
                "else:",
                "    print('沒有死水欄位')",
            ]
        elif tool_name in SERIES_FUNCS:
            code_lines += [
                "# series-based function",
                f"_params = dict({params_str})" if params_str else "_params = {}",
                "target_col = _params.pop('target_col', None)",
                "if not target_col:",
                "    print('❌ 必須指定 target_col')",
                "else:",
                "    series = df_active[target_col] if target_col in df_active.columns else df_numeric[target_col]",
                f"    result = sigma.{tool_name}(series, **_params)"
                if tool_name != "plot_trend"
                else f"    result = sigma.{tool_name}(df_active, [target_col])",
                "    if isinstance(result, dict):",
                "        for k, v in result.items():",
                "            if isinstance(v, (np.ndarray, pd.Series)):",
                "                continue",
                "            print(f'{k}: {v}')",
            ]
        elif tool_name in TWO_SERIES_FUNCS:
            code_lines += [
                f"_params = dict({params_str})" if params_str else "_params = {}",
                "col_a = _params.pop('col_a', None)",
                "col_b = _params.pop('col_b', None)",
                "if not col_a or not col_b:",
                "    print('❌ 必須指定 col_a 和 col_b')",
                "else:",
                "    sa = df_active[col_a] if col_a in df_active.columns else df_numeric[col_a]",
                "    sb = df_active[col_b] if col_b in df_active.columns else df_numeric[col_b]",
                f"    result = sigma.{tool_name}(sa, sb, **_params)",
                "    if isinstance(result, dict):",
                "        for k, v in result.items():",
                "            if isinstance(v, (np.ndarray, pd.Series)):",
                "                continue",
                "            print(f'{k}: {v}')",
            ]
        elif tool_name in SCATTER_FUNCS:
            code_lines += [
                f"_params = dict({params_str})" if params_str else "_params = {}",
                "x_col = _params.pop('x_col', None)",
                "y_col = _params.pop('y_col', None)",
                "if not x_col or not y_col:",
                "    print('❌ 必須指定 x_col 和 y_col')",
                "else:",
                f"    sigma.{tool_name}(df_active, x_col, y_col, **_params)",
            ]
        elif tool_name in TARGET_KWARG_FUNCS:
            code_lines += [
                f"_params = dict({params_str})" if params_str else "_params = {}",
                "target_col = _params.pop('target_col', None)",
                "if target_col:",
                f"    result = sigma.{tool_name}(df_active, target=target_col, **_params)"
                if tool_name == "top_correlations"
                else f"    result = sigma.{tool_name}(df_active, target_col, **_params)",
                "else:",
                f"    result = sigma.{tool_name}(df_active, **_params)",
                "if isinstance(result, dict):",
                "    for k, v in result.items():",
                "        if isinstance(v, (np.ndarray, pd.Series, pd.DataFrame)):",
                "            continue",
                "        print(f'{k}: {v}')",
            ]
        elif tool_name in GROUP_FUNCS:
            code_lines += [
                f"_params = dict({params_str})" if params_str else "_params = {}",
                "ga_range = _params.pop('group_a_range', '')",
                "gb_range = _params.pop('group_b_range', '')",
                "target_col = _params.pop('target_col', None)",
                "def _parse_range(r):",
                "    parts = r.split('-')",
                "    return list(range(int(parts[0])-1, int(parts[1]))) if len(parts)==2 else []",
                "ga_idx = _parse_range(ga_range) if ga_range else list(range(len(df_active)//2))",
                "gb_idx = _parse_range(gb_range) if gb_range else list(range(len(df_active)//2, len(df_active)))",
            ]
            if tool_name == "compare_groups":
                code_lines += [
                    "result = sigma.compare_groups(df_active, ga_idx, gb_idx, **_params)",
                    "if isinstance(result, dict):",
                    "    for k, v in result.items():",
                    "        if isinstance(v, (np.ndarray, pd.Series, pd.DataFrame)):",
                    "            continue",
                    "        print(f'{k}: {v}')",
                ]
            else:
                code_lines += [
                    "if target_col:",
                    f"    sigma.{tool_name}(df_active, target_col, ga_idx, gb_idx, **_params)",
                ]
        else:
            # Generic: pass df_active + user params
            code_lines += [
                f"_params = dict({params_str})" if params_str else "_params = {}",
                f"result = sigma.{tool_name}(df_active, **_params)",
                "if isinstance(result, dict):",
                "    for k, v in result.items():",
                "        if isinstance(v, (np.ndarray, pd.Series, pd.DataFrame)):",
                "            continue",
                "        print(f'{k}: {v}')",
                "elif isinstance(result, tuple) and len(result) == 2:",
                "    print(f'Result: {result}')",
            ]

        code = "\n".join(code_lines)
        logger.info(f"[V3:DirectTool] Generated code:\n{code[:500]}")

        # 4. Execute
        executor = CodeExecutor()
        namespace = {"df": df, "pd": __import__("pandas"), "np": __import__("numpy")}

        ctx.write_event_to_stream(CodeBlockEvent(code=code, round_num=1))

        try:
            exec_result = await asyncio.to_thread(
                executor.execute_streaming, code, namespace
            )

            stdout_text = exec_result.stdout or ""
            charts = exec_result.charts or []

            # Stream stdout
            if stdout_text.strip():
                for line in stdout_text.strip().split("\n"):
                    ctx.write_event_to_stream(CodeOutputEvent(output=line, round_num=1))

            # Stream charts
            for i, chart in enumerate(charts):
                ctx.write_event_to_stream(
                    ChartImageEvent(
                        image_base64=chart.get("image_base64", ""),
                        chart_title=chart.get("title", f"Chart {i + 1}"),
                        width=chart.get("width", 800),
                        height=chart.get("height", 400),
                    )
                )

            if exec_result.error:
                ctx.write_event_to_stream(
                    CodeOutputEvent(output=f"⚠️ Error: {exec_result.error}", round_num=1)
                )

        except Exception as e:
            logger.error(f"[V3:DirectTool] 執行失敗: {e}")
            ctx.write_event_to_stream(TextChunkEvent(content=f"❌ 執行失敗: {e}"))

        return StopEvent(result={"response": f"[DIRECT_TOOL] {tool_name} 執行完成"})

    # ============================================================
    # _run_code_interpreter: Code Interpreter 路徑
    # ============================================================

    async def _run_code_interpreter(
        self,
        ctx: Context,
        ev: ToolExecuteEvent,
        route: RouteIntentOutput,
    ) -> AnalysisDoneEvent:
        """
        Code Interpreter 路徑:
        LLM 生成 Python code → 沙箱執行 → 串流 code/output/chart
        最多 MAX_CODE_ROUNDS 輪迭代
        """
        from backend.services.analysis.code_executor import CodeExecutor
        from backend.services.analysis.agents.roles_v3.code_analyst import CodeAnalyst
        from backend.services.analysis.analysis_types import (
            CodeBlockEvent,
            ChartImageEvent,
        )
        from backend.services.analysis.agents.ci_helpers import (
            load_analysis_data,
            build_report_prep,
            build_progress_hints,
            run_exec_streaming,
        )

        MAX_CODE_ROUNDS = 2

        executor = CodeExecutor()
        analyst = CodeAnalyst(self.llm)

        # --- 載入資料 ---
        df, data_summary = await load_analysis_data(
            self.analysis_service, ev.session_id, ev.file_id
        )

        if df is None:
            logger.error("[V3:CodeInterpreter] DataFrame 為 None，無法執行")
            return AnalysisDoneEvent(
                result=PlaybookResult(
                    restatement=route.restatement,
                    task_type=route.task_type,
                    tool_results=[],
                    key_findings=["資料載入失敗，無法執行 Code Interpreter"],
                ),
                restatement=route.restatement,
                file_id=ev.file_id,
                session_id=ev.session_id,
            )

        # --- 統一合約 context ---
        unified_context = {
            "target_params": route.target_params or [],
            "reference_params": getattr(route, "reference_params", []) or [],
            "target_range": route.target_range or [],
            "baseline_range": getattr(route, "baseline_range", "") or "",
            "has_y": route.has_y,
        }

        # --- Preprocess + Report + Baseline ---
        df_numeric = df.select_dtypes(include="number").fillna(0)
        df_active, prep = build_report_prep(df_numeric, route, unified_context)
        code_context = {
            "df_active": df_active,
            "_prep": prep,
        }  # _prep 僅供系統使用，不注入 LLM namespace
        if prep and isinstance(prep, dict) and "_preprocess_summary" in prep:
            data_summary["preprocess_summary"] = prep.pop("_preprocess_summary")

        # --- 多輪 code 迭代 (系統控制輪數) ---
        previous_outputs = []
        all_findings = []
        total_charts = 0
        focus_targets = []  # Round 2+ 聚焦目標
        accumulated_evidence = []  # 結構化 findings JSON

        # === 前處理圖表 (在 LLM 生成 code 之前推送前端) ===
        if prep is not None:
            try:
                from backend.services.analysis import sigma_utils

                preprocess_charts = sigma_utils.generate_preprocess_charts(
                    prep,
                    route.task_type,
                    target_params=route.target_params,
                )
                for chart in preprocess_charts:
                    # is_overview=False → 不放概述區，round_num=-1
                    _round = 0 if chart.get("is_overview", True) else -1
                    ctx.write_event_to_stream(
                        ChartImageEvent(
                            image_base64=chart["image_base64"],
                            title=chart["title"],
                            width=chart.get("width", 0),
                            height=chart.get("height", 0),
                            round_num=_round,
                        )
                    )
                    total_charts += 1
                logger.info(
                    f"[V3:CodeInterpreter] 前處理圖表: {len(preprocess_charts)} 張"
                )
            except Exception as e:
                import traceback

                logger.warning(
                    f"[V3:CodeInterpreter] preprocess charts failed: {e}\n{traceback.format_exc()}"
                )
        max_rounds = self._get_max_rounds(route.task_type)

        round_num = 0
        all_chart_titles: list = []  # 收集各輪圖表標題，供 chart-to-finding mapping
        error_retries = 0
        MAX_ERROR_RETRIES = 2
        _is_retry = False  # 重試 flag: 避免重發 CodeBlockEvent

        # === Run-level 持久 STATE（跨輪次共享計算結果）===
        ci_state: dict = {}
        code_context["__ci_state__"] = ci_state  # pass by reference，同一個 dict

        # === Round 0: 自動生成資料摘要（不需 LLM，讓 LLM 在 Round 1 看到資料長相）===
        try:
            _summary_lines = ["[系統] 資料摘要 (Round 0 自動生成):"]
            _summary_lines.append(
                f"  資料維度: {df_active.shape[0]} 筆 x {df_active.shape[1]} 欄"
            )
            # Top-8 高變異欄位 (std 最大，最可能包含異常訊號)
            _top_std = df_active.std().nlargest(8)
            _summary_lines.append("  Top-8 高變異欄位 (std):")
            for _col, _std in _top_std.items():
                _mn = df_active[_col].mean()
                _mi = df_active[_col].min()
                _mx = df_active[_col].max()
                _summary_lines.append(
                    f"    {_col}: mean={_mn:.2f}, std={_std:.2f}, range=[{_mi:.2f}, {_mx:.2f}]"
                )

            if isinstance(prep, dict):
                _scenario = prep.get("scenario", "A")

                # --- Hotelling T² ---
                _hot = prep.get("hotelling", {})
                if _hot:
                    _t2_vals = _hot.get("t2_values", [])
                    _ucl99 = _hot.get("ucl_99", 0)
                    _ucl95 = _hot.get("ucl_95", 0)
                    import numpy as _np

                    _t2_arr = (
                        _np.array(_t2_vals) if len(_t2_vals) > 0 else _np.array([])
                    )
                    _real_anom = (
                        _np.where(_t2_arr > _ucl99)[0].tolist()
                        if len(_t2_arr) > 0
                        else []
                    )
                    _real_warn_count = (
                        int((_t2_arr > _ucl95).sum()) - len(_real_anom)
                        if len(_t2_arr) > 0
                        else 0
                    )
                    _summary_lines.append(
                        f"  Hotelling T²: {len(_real_anom)} 個異常 (>99%), "
                        f"{_real_warn_count} 個警告 (>95%) / {df_active.shape[0]} 筆 "
                        f"(UCL_99={_ucl99:.2f}, UCL_95={_ucl95:.2f}, 維度={df_active.shape[1]})"
                    )
                    # Scene A/C: 列出每筆異常; Scene B/D: 只印總數
                    if _scenario not in ("B", "D"):
                        for _ai in _real_anom[:10]:
                            _summary_lines.append(
                                f"    異常: 第 {_ai} 筆 (T²={_t2_arr[_ai]:.2f})"
                            )

                # --- PCA ---
                _pca = prep.get("pca", {})
                if _pca and _pca.get("explained_variance_ratio"):
                    _evr = _pca["explained_variance_ratio"]
                    _loadings = _pca.get("top_loadings", {})
                    _n_pc = len(_evr)
                    _summary_lines.append(f"  PCA 分析 ({_n_pc} 主成分):")
                    _cum = 0
                    for _i, _var in enumerate(_evr):
                        _cum += _var * 100
                        _summary_lines.append(
                            f"    PC{_i + 1}: {_var * 100:.1f}% (累積 {_cum:.1f}%)"
                        )
                        # Scene B/D: 不列 PCA loadings (不需要)
                        if _scenario not in ("B", "D"):
                            _pc_loads = _loadings.get(f"PC{_i + 1}", [])
                            for _lc, _lv in _pc_loads[:3]:
                                _summary_lines.append(f"      {_lc}: {_lv:.4f}")

                # --- 場景 ---
                if _scenario:
                    _summary_lines.append(f"  場景: {_scenario}")

                # --- 異常區間 (Scene A/C 列出，Scene B/D 跳過) ---
                _iv_scores = prep.get("interval_scores", {})
                _core_by_iv = prep.get("core_indices_by_interval", {})
                if _scenario not in ("B", "D"):
                    _intervals = prep.get("anomaly_intervals", [])
                    _low_pri = prep.get("low_priority_intervals", [])
                    if _intervals:
                        _parts = []
                        for _iv in _intervals:
                            _sc = _iv_scores.get(_iv, 0)
                            _nc = len(_core_by_iv.get(_iv, []))
                            _parts.append(f"#{_iv} (score={_sc:.0f}, core={_nc}筆)")
                        _summary_lines.append(
                            f"  異常區間 (Top-{len(_intervals)}): {', '.join(_parts)}"
                        )
                        if _low_pri:
                            _summary_lines.append(
                                f"  略過低優先區間 ({len(_low_pri)} 個): {_low_pri}"
                            )

                # --- T² contribution (Scene A/C only) ---
                _t2c = prep.get("t2_contrib", {})
                if _t2c and _scenario not in ("B", "D"):
                    _by_interval = _t2c.get("top_contributors_by_interval", {})
                    _marginal_by_int = _t2c.get("marginal_scores_by_interval", {})
                    if _by_interval or _marginal_by_int:
                        _summary_lines.append("  各異常區間分析:")
                        _all_keys = list(_by_interval.keys()) or list(
                            _marginal_by_int.keys()
                        )
                        for _key in _all_keys:
                            _sc = _iv_scores.get(_key, 0)
                            _nc = len(_core_by_iv.get(_key, []))
                            _summary_lines.append(
                                f"    --- 區間 #{_key} (score={_sc:.0f}, core={_nc}筆) ---"
                            )
                            _m_scores = _marginal_by_int.get(_key, [])
                            if _m_scores:
                                _summary_lines.append("      Marginal Drop (主導):")
                                for _mc, _ms in _m_scores[:3]:
                                    _summary_lines.append(
                                        f"        {_mc}: T²_drop={_ms:.4f}"
                                    )
                            _cols = _by_interval.get(_key, [])
                            if _cols:
                                _summary_lines.append(
                                    f"      T² 貢獻 (輔助): {', '.join(_cols[:3])}"
                                )

                    # Global: Marginal Drop 先，其他後
                    _global_top = _t2c.get("top_contributors_global", [])
                    _marginal_g = _t2c.get("marginal_scores_global", [])
                    _baseline_g = _t2c.get("baseline_scores_global", [])
                    if _marginal_g or _global_top:
                        _summary_lines.append("  全域分析:")
                    if _marginal_g:
                        _summary_lines.append("    Marginal Drop (主導):")
                        for _mc, _ms in _marginal_g[:5]:
                            _summary_lines.append(f"      {_mc}: T²_drop={_ms:.4f}")
                    if _global_top:
                        _summary_lines.append(
                            f"    T² 貢獻 (輔助 Top 5): {', '.join(_global_top[:5])}"
                        )
                    if _baseline_g:
                        _summary_lines.append("    Baseline 差分:")
                        for _bc, _bs in _baseline_g[:5]:
                            _summary_lines.append(f"      {_bc}: delta={_bs:.4f}")

                # --- Scene B: 輸出 preprocess_summary (zscore/drift/RF/corr) ---
                if _scenario in ("B", "D"):
                    _ps = data_summary.get("preprocess_summary", "")
                    if _ps:
                        _summary_lines.append(f"\n{_ps}")
            # --- 用戶查詢中的行號引用解析 ---
            import re as _re_row

            _query_lower = ev.query.lower() if hasattr(ev, "query") else ""
            _n_rows = df_active.shape[0]
            _focus_rows = []  # (label, row_indices)

            # 解析相對位置描述
            _patterns = [
                (r"最後[一1]筆", "最後一筆", [-1]),
                (r"最後(\d+)筆", "最後N筆", None),  # group(1) = N
                (r"倒數第?(\d+)筆", "倒數第N筆", None),
                (r"第[一1]筆|第一[筆條]", "第一筆", [0]),
                (r"前(\d+)筆", "前N筆", None),
                (r"第(\d+)筆", "第N筆", None),
                (r"第(\d+)[到至~-]第?(\d+)筆", "range", None),
            ]
            for _pat, _label, _fixed in _patterns:
                _m = _re_row.search(_pat, _query_lower)
                if _m:
                    if _fixed is not None:
                        _focus_rows.append((_label, _fixed))
                    elif _label == "最後N筆":
                        _n = int(_m.group(1))
                        _focus_rows.append((f"最後{_n}筆", list(range(-_n, 0))))
                    elif _label == "倒數第N筆":
                        _n = int(_m.group(1))
                        _focus_rows.append((f"倒數第{_n}筆", [-_n]))
                    elif _label == "前N筆":
                        _n = int(_m.group(1))
                        _focus_rows.append((f"前{_n}筆", list(range(_n))))
                    elif _label == "第N筆":
                        _n = int(_m.group(1))
                        _idx = _n - 1 if _n >= 1 else _n  # 1-indexed → 0-indexed
                        _focus_rows.append((f"第{_n}筆", [_idx]))
                    elif _label == "range":
                        _s, _e = int(_m.group(1)), int(_m.group(2))
                        _focus_rows.append((f"第{_s}-{_e}筆", list(range(_s - 1, _e))))
                    break  # 只取第一個匹配

            if _focus_rows:
                _summary_lines.append("")
                _summary_lines.append("  ⚠ 用戶指定的目標行:")
                for _fl_label, _fl_indices in _focus_rows:
                    _actual = [(i if i >= 0 else _n_rows + i) for i in _fl_indices]
                    _actual = [i for i in _actual if 0 <= i < _n_rows]
                    if not _actual:
                        _summary_lines.append(f"    {_fl_label}: 超出範圍")
                        continue
                    _summary_lines.append(
                        f"    {_fl_label} → 實際行號: {_actual} (df_active.iloc[{_fl_indices}])"
                    )
                    # 印出這些行的基本統計
                    _focus_df = df_active.iloc[_actual]
                    if len(_actual) <= 3:
                        for _fi in _actual:
                            _row = df_active.iloc[_fi]
                            _top5_std_cols = df_active.std().nlargest(5).index.tolist()
                            _vals = [
                                f"{c}={_row[c]:.2f}"
                                for c in _top5_std_cols
                                if c in _row.index
                            ]
                            _summary_lines.append(
                                f"      第{_fi}筆: {', '.join(_vals)}"
                            )
                    # T² 值
                    if isinstance(prep, dict):
                        _t2_vals = prep.get("hotelling", {}).get("t2_values", [])
                        _ucl99 = prep.get("hotelling", {}).get("ucl_99", 0)
                        if _t2_vals:
                            for _fi in _actual:
                                if _fi < len(_t2_vals):
                                    _t2v = _t2_vals[_fi]
                                    _flag = "🔴 異常" if _t2v > _ucl99 else "🟢 正常"
                                    _summary_lines.append(
                                        f"      第{_fi}筆 T²={_t2v:.2f} (UCL_99={_ucl99:.2f}) → {_flag}"
                                    )

            # === 注入上一輪 session context（讓 LLM 知道已分析過什麼）===
            _session_ctx = self._load_session_context(ev.session_id, ev.file_id)
            if _session_ctx.round_counter > 0 and _session_ctx.current_knowledge:
                _summary_lines.append("")
                _summary_lines.append(
                    "  ⚠ 上一輪分析已覆蓋（不要重複，請往更深方向分析）:"
                )
                _summary_lines.append(f"    已完成 {_session_ctx.round_counter} 輪分析")
                if _session_ctx.last_key_findings:
                    _summary_lines.append("    已報告的發現:")
                    for _kf in _session_ctx.last_key_findings[:5]:
                        _kf_text = _kf[:120] if isinstance(_kf, str) else str(_kf)[:120]
                        _summary_lines.append(f"      - {_kf_text}")
                # 提取已分析的參數名
                _prev_params = set()
                for _entry in _session_ctx.current_knowledge:
                    if isinstance(_entry, dict):
                        _prev_params.update(_entry.get("params", []))
                if _prev_params:
                    _summary_lines.append(
                        f"    已分析的參數: {', '.join(sorted(_prev_params)[:10])}"
                    )
                _summary_lines.append(
                    "    → 本輪應: 分析低優先區間、跨區間關聯、或對已知因子做更深入分析"
                )

            code_context["__data_summary__"] = "\n".join(_summary_lines)
        except Exception as _e:
            logger.warning(f"[V3:CI] Round 0 data summary failed: {_e}")
            code_context["__data_summary__"] = ""

        while round_num < max_rounds:
            round_num += 1

            # G2: Per-round plot budget
            _plot_budget = 25  # 每輪最多 25 張圖
            code_context["__max_charts__"] = _plot_budget
            code_context["__round__"] = round_num
            logger.info(
                f"[V3:CodeInterpreter] Round {round_num}/{max_rounds} (task={route.task_type})"
            )

            _retry_label = f" (重試 {error_retries})" if _is_retry else ""
            ctx.write_event_to_stream(
                ProgressEvent(
                    msg=f"Code Interpreter [{round_num}/{max_rounds}]: 生成分析程式碼...{_retry_label}",
                    turn=0,
                )
            )

            # === Progress state gate: 防止 Round 2+ 重做 Round 1 ===
            if round_num >= 2 and previous_outputs:
                hint = build_progress_hints(previous_outputs)
                if hint:
                    focus_targets.append(hint)

            # code_block header 在 generate_code 完成後才發，見下方 Line ~635

            # LLM 生成 code (streaming: 透過 on_chunk 打字機推送)
            async def _push_code_chunk(chunk_text):
                if self.stdout_queue is not None:
                    await self.stdout_queue.put(
                        ("__code_chunk__", chunk_text, round_num)
                    )

            # 因為 on_chunk 需要是 sync callable 但要推 async queue
            # 用 loop.call_soon_threadsafe 不適用（已在 main loop）
            # 改用: 收集 chunks 後在 generate_code 內部 await
            code = await analyst.generate_code(
                query=ev.query,
                data_summary=data_summary,
                unified_context=unified_context,
                previous_outputs=previous_outputs,
                round_num=round_num,
                focus_targets=focus_targets,
                task_type=route.task_type,
                on_chunk=None,  # 關閉打字機，整塊送
            )

            if not code or code.strip() == "":
                logger.warning(
                    f"[V3:CodeInterpreter] Round {round_num}: empty code, stopping"
                )
                break

            # ============================================================
            # Two-Stage Sigma Spec Injection
            # 掃描 LLM 生成的 code，偵測 sigma.xxx() 呼叫，
            # 注入 API spec 後讓 LLM 重新生成
            # ============================================================
            import re as _re_spec
            from backend.services.analysis.sigma_utils import _SIGMA_SPECS

            _sigma_calls = set(_re_spec.findall(r"sigma\.(\w+)\s*\(", code))
            # 排除 help 本身和 filter_dead_columns (不需要 spec)
            _sigma_calls -= {"help", "filter_dead_columns"}
            # 只保留有 spec 的函式
            _sigma_calls = {fn for fn in _sigma_calls if fn in _SIGMA_SPECS}

            if _sigma_calls:
                logger.info(
                    f"[V3:SpecInjection] Round {round_num}: 偵測到 sigma 呼叫: {_sigma_calls}"
                )
                # 組合 spec 文字
                _spec_parts = []
                for fn in sorted(_sigma_calls):
                    _spec_parts.append(_SIGMA_SPECS[fn])
                _spec_text = "\n\n".join(_spec_parts)

                # 注入 spec 到 previous_outputs
                previous_outputs.append(
                    {
                        "round": f"{round_num}_spec",
                        "code": f"# [系統自動查詢] sigma API 規格: {', '.join(sorted(_sigma_calls))}",
                        "stdout": f"[Sigma API 規格 — 請嚴格按照以下格式使用]\n{_spec_text}",
                        "error": "",
                        "charts_count": 0,
                    }
                )

                ctx.write_event_to_stream(
                    ProgressEvent(
                        msg=f"Code Interpreter [{round_num}/{max_rounds}]: API 規格確認，重新生成...",
                        turn=0,
                    )
                )

                # === 第二次 LLM 呼叫 ===
                code = await analyst.generate_code(
                    query=ev.query,
                    data_summary=data_summary,
                    unified_context=unified_context,
                    previous_outputs=previous_outputs,
                    round_num=round_num,
                    focus_targets=focus_targets
                    + ["⚠ 請參考上方 [Sigma API 規格] 的回傳格式撰寫程式碼，不要猜"],
                    task_type=route.task_type,
                    on_chunk=None,  # 關閉打字機，整塊送
                )

                # 移除 spec entry（避免佔 context）
                previous_outputs.pop()

                if not code or code.strip() == "":
                    logger.warning(
                        f"[V3:CodeInterpreter] Round {round_num}: empty code after spec injection, stopping"
                    )
                    break

            # 發送 code block（整塊顯示，打字機已關閉）
            ctx.write_event_to_stream(
                CodeBlockEvent(code=code, language="python", round_num=round_num)
            )

            # --- 自動 prepend bootstrap 代碼 ---
            bootstrap = (
                "# === 系統前置分析已完成 ===\n"
                "# df_active: 已過濾死水欄位的 DataFrame (唯一允許分析的數據)\n"
                "# report: 預計算結果 dict (hotelling, pca, t2_contrib, stability 等)\n"
                "# sigma: 分析工具庫\n"
                f"print(f'[系統] 資料維度: {{df_active.shape[0]}} 筆 x {{df_active.shape[1]}} 欄')\n"
                "# === 以下為 LLM 生成的分析程式碼 ===\n\n"
            )
            code = bootstrap + code

            ctx.write_event_to_stream(
                ProgressEvent(
                    msg=f"Code Interpreter [{round_num}/{MAX_CODE_ROUNDS}]: 執行中...",
                    turn=0,
                )
            )

            # --- 即時串流 stdout + 執行 ---
            result, new_charts = await run_exec_streaming(
                executor,
                code,
                code_context,
                self.stdout_queue,
                ctx,
                round_num,
            )
            total_charts += new_charts
            # 收集本輪圖表標題
            for _ch in result.charts:
                all_chart_titles.append(_ch.get("title", ""))

            # 記錄本輪結果
            round_output = {
                "round": round_num,
                "code": code,
                "stdout": result.stdout,
                "error": result.error or "",
                "charts_count": len(result.charts),
            }
            previous_outputs.append(round_output)

            # 收集 findings
            if result.stdout:
                # 取前 2000 字元作為 finding 摘要
                finding_summary = result.stdout[:2000]
                # 去掉 data_summary 前綴（避免重複）
                # data_summary 格式: "[系統] 資料摘要 ... 很長一串 ..."
                # 它通常佔 stdout 開頭大部分，找最後一個 sigma 標記後的內容
                _ds_marker = "[系統] 資料摘要"
                if _ds_marker in finding_summary:
                    # 找 [sigma] 開頭的行（代表分析工具輸出開始）
                    _lines = finding_summary.split("\n")
                    _cut_idx = 0
                    for _li, _line in enumerate(_lines):
                        if (
                            _line.strip().startswith("[sigma]")
                            or _line.strip().startswith("---")
                            or _line.strip().startswith("=")
                        ):
                            _cut_idx = _li
                            break
                    if _cut_idx > 0:
                        finding_summary = "\n".join(_lines[_cut_idx:]).strip()
                    else:
                        # 整段都是 data_summary，跳過（Round 0 已有）
                        finding_summary = ""
                # 重試成功時替換之前的 error finding，不要重複加
                if _is_retry:
                    # 移除上一次同 round 的 ERROR finding
                    all_findings = [
                        f
                        for f in all_findings
                        if not f.startswith(f"[Round {round_num} ERROR]")
                    ]
                if finding_summary:
                    all_findings.append(f"[Round {round_num}] {finding_summary}")

                # 從 stdout 提取結論 (不再依賴 __FINDINGS__ JSON)
                evidence = {"round": round_num}
                for line in result.stdout.split("\n"):
                    if "嫌疑欄位" in line or "primary" in line.lower():
                        evidence["conclusion"] = line.strip()
                        break
                if "[ANALYSIS_COMPLETE]" in result.stdout:
                    evidence["complete"] = True
                accumulated_evidence.append(evidence)

            if result.error:
                # 只保留第一行錯誤訊息，不塞完整 traceback
                _err_short = result.error.split("\n")[-1][:150] if result.error else ""
                all_findings.append(f"[Round {round_num} ERROR] {_err_short}")

            # === 系統判斷是否繼續下一輪 ===
            if result.error:
                # 執行錯誤: 回退 round_num 重試同一輪
                error_retries += 1

                # 注入針對性修正提示到 previous_outputs
                fix_hint = self._get_error_fix_hint(result.error)
                if fix_hint:
                    previous_outputs[-1]["error"] += f"\n\n[自動修正提示] {fix_hint}"

                if error_retries <= MAX_ERROR_RETRIES:
                    logger.warning(
                        f"[V3:CodeInterpreter] Round {round_num}: 執行錯誤 (重試 {error_retries}/{MAX_ERROR_RETRIES})"
                    )
                    round_num -= 1  # 回退，while loop 會重新 +1
                    _is_retry = True
                    continue
                else:
                    logger.warning(
                        f"[V3:CodeInterpreter] Round {round_num}: 重試次數耗盡，跳到下輪"
                    )
                    error_retries = 0  # reset for next round
                    continue
            else:
                error_retries = 0  # 成功執行，重置重試計數
                _is_retry = False

            # === Mid-Round Evidence Evaluation ===
            # 每輪結束後跑 evaluator，把判定注入下一輪 context
            if round_num < max_rounds and result.stdout and not result.error:
                try:
                    from backend.services.analysis.agents.roles_v3.evidence_evaluator import (
                        EvidenceEvaluator,
                    )

                    _mid_evaluator = EvidenceEvaluator()
                    _round_findings = [
                        f for f in all_findings if f.startswith(f"[Round {round_num}]")
                    ]
                    _mid_evaluated = _mid_evaluator.evaluate(
                        all_findings=_round_findings or [result.stdout[:2000]],
                        stdout_rounds=[result.stdout],
                        data_summary="",
                        prep=None,  # mid-round 不用 prep (final 才用)
                        task_type=route.task_type,
                    )
                    if _mid_evaluated:
                        _mid_text = _mid_evaluator.format_for_humanizer(_mid_evaluated)
                        # 注入到 previous_outputs，讓 Round N+1 的 LLM 看到
                        previous_outputs[-1]["evaluation_hint"] = _mid_text
                        logger.info(
                            f"[V3:CI] Mid-round eval: {len(_mid_evaluated)} findings "
                            f"(H={sum(1 for e in _mid_evaluated if e.severity == 'high')}, "
                            f"M={sum(1 for e in _mid_evaluated if e.severity == 'medium')})"
                        )
                except Exception as _eval_err:
                    logger.warning(f"[V3:CI] Mid-round eval failed: {_eval_err}")

            # 取最新一輪 findings 給 Governor
            _latest_findings = accumulated_evidence[-1] if accumulated_evidence else {}
            decision = self._evaluate_should_continue(
                round_num=round_num,
                task_type=route.task_type,
                stdout=result.stdout,
                max_rounds=max_rounds,
                findings=_latest_findings,
                accumulated_evidence=accumulated_evidence,
            )
            logger.info(
                f"[V3:CodeInterpreter] Round {round_num} 判斷: "
                f"{decision['action']} — {decision['reason']}"
            )
            if decision["action"] == "STOP":
                break
            focus_targets = decision.get("focus_targets", [])

        logger.info(
            f"[V3:CodeInterpreter] 完成: "
            f"{len(previous_outputs)} 輪, {total_charts} 張圖表"
        )

        # --- 儲存 session context ---
        self._save_session_context(
            session_id=ev.session_id,
            file_id=ev.file_id,
            restatement=route.restatement,
            key_findings=all_findings[:10],
            target_params=route.target_params or [],
            task_type=route.task_type,
        )

        # --- 組裝結果 ---
        # 提取 prep 的結構化數據（只傳 t2_contrib + anomaly_intervals，避免傳巨大 numpy arrays）
        _prep_for_eval = None
        if prep and isinstance(prep, dict):
            _prep_for_eval = {
                "anomaly_intervals": prep.get("anomaly_intervals", []),
                "t2_contrib": prep.get("t2_contrib", {}),
                "drift_scan": prep.get("drift_scan", {}),
                "deep_analysis": prep.get("deep_analysis", {}),
            }

        return AnalysisDoneEvent(
            result=PlaybookResult(
                restatement=route.restatement,
                task_type=route.task_type,
                tool_results=[
                    ToolChainResult(
                        tool_name="code_interpreter",
                        params={
                            "rounds": len(previous_outputs),
                            "charts": total_charts,
                        },
                        success=True,
                        result={
                            "rounds": len(previous_outputs),
                            "total_charts": total_charts,
                            "evidence": accumulated_evidence,
                            "outputs": [
                                {
                                    "round": o["round"],
                                    "stdout": self._filter_stdout_for_humanizer(
                                        o["stdout"]
                                    ),
                                    "charts_count": o["charts_count"],
                                    "has_error": bool(o["error"]),
                                }
                                for o in previous_outputs
                            ],
                        },
                    )
                ],
                key_findings=all_findings[:10],
            ),
            restatement=route.restatement,
            file_id=ev.file_id,
            session_id=ev.session_id,
            data_summary=code_context.get("__data_summary__", ""),
            prep=_prep_for_eval,
            chart_titles=all_chart_titles,
        )

    # ============================================================
    # 多輪分析: 系統判斷函式
    # ============================================================

    @staticmethod
    def _filter_stdout_for_humanizer(stdout: str, max_chars: int = 3000) -> str:
        """過濾 stdout 噪音，只保留有意義的分析結果給 humanizer。"""
        if not stdout:
            return ""
        filtered = []
        for line in stdout.split("\n"):
            stripped = line.strip()
            # 跳過: 裝飾線
            if (
                stripped.startswith("=")
                and len(stripped) > 5
                and stripped == stripped[0] * len(stripped)
            ):
                continue
            # 跳過: 圖表標題 (圖已另存)
            if stripped.startswith("[圖表]"):
                continue
            # 跳過: 系統資訊 (data_summary 已有)
            if stripped.startswith("[系統]"):
                continue
            # 跳過: LLM 計畫文字 (Round N 目標:)
            if stripped.startswith("Round") and "目標" in stripped:
                continue
            # 跳過: LLM 計畫步驟 (1. xxx / 2. xxx)
            if re.match(r"^\d+\.\s", stripped):
                continue
            # 跳過: 空行
            if not stripped:
                continue
            # 跳過: 完成標記
            if "[ANALYSIS_COMPLETE]" in stripped:
                continue
            # 跳過: sigma 工具 verbose (PCA 詳細輸出已在 data_summary)
            if stripped.startswith("[sigma] PCA"):
                continue
            # 跳過: 重複引用 data_summary
            if "以下資訊來自" in stripped or "引用 data_summary" in stripped:
                continue
            filtered.append(line)
        result = "\n".join(filtered)
        if len(result) > max_chars:
            result = result[: max_chars - 50] + "\n...(截斷)..."
        return result

    @staticmethod
    def _get_error_fix_hint(error_msg: str) -> str:
        """
        根據 error traceback 回傳針對性修正提示，注入 retry prompt。
        讓 LLM 能精準修正而非盲目重試。
        """
        hints = []
        e = error_msg.lower()

        # report 已從 namespace 移除 — LLM 必須改用 data_summary + sigma tools
        if "name 'report' is not defined" in e:
            hints.append(
                "⛔ `report` 變數已不存在！前置分析結果已印在 data_summary（[系統] 區塊）中。\n"
                "直接閱讀 data_summary 文字取得數字。需要更多數據用 sigma 工具：\n"
                "  - sigma.t2_contribution_marginal(df_active, anomaly_indices)\n"
                "  - sigma.compare_groups(df_active, group_a_indices, group_b_indices)\n"
                "  - 已切好的 DataFrame: df_anomaly, df_baseline, df_intervals\n"
                "  - 遍歷異常區間: for key, df_seg in df_intervals.items():"
            )
        # report[...] KeyError — report 已不存在
        if "'report'" in e and "keyerror" in e.lower():
            hints.append(
                "⛔ `report` 變數已不存在！改用 data_summary 文字 + sigma tools。"
            )
        # report["pca"]["top_loading_cols"] 是 list，不是 dict
        if "'list' object has no attribute 'keys'" in e:
            hints.append(
                "top_loading_cols 是 list[str]，不是 dict。"
                "不能呼叫 .keys()。直接 for col in list_var: 即可。"
            )
        # report["t2_contrib"]["top_contributors_by_interval"] 是 dict[str, list]，不能 [:5]
        if "keyerror: slice(" in e:
            hints.append(
                "report['t2_contrib']['top_contributors_by_interval'] 是 dict[str, list[str]]，"
                "不能用 [:5] 切片。遍歷用: for key, cols in report['t2_contrib']['top_contributors_by_interval'].items():"
            )
        # df_active.index not in [59, 243] → 需要用 ~df_active.index.isin([59, 243])
        if "the truth value of an array" in e:
            hints.append(
                "不能用 `index not in [59, 243]`，這在 pandas 中會產生 array 而非 bool。"
                "改用: df_active[~df_active.index.isin([59, 243])]"
            )
        # mannwhitneyu alternative='equal' → 'two-sided'
        if "alternative" in e and "mannwhitney" in e:
            hints.append(
                "mannwhitneyu 的 alternative 參數應為 'two-sided'，不是 'equal'。"
            )
        # df_active.loc[idx, col] 回傳 scalar，不能直接傳給 sns.histplot/boxplot
        if "numpy.float64" in e and "has no len" in e:
            hints.append(
                "df_active.loc[單一index, col] 回傳 scalar (numpy.float64)，不能直接傳給 seaborn。"
                "取子集用 df_active.loc[[idx], col] (雙括號) 或 df_active.loc[idx_list, col]。"
            )
        # axes ndarray 不能直接呼叫 matplotlib 方法
        if "numpy.ndarray" in e and "has no attribute" in e:
            import re as _rhint

            _m = _rhint.search(r"has no attribute '(\w+)'", error_msg)
            _method = _m.group(1) if _m else "hist/plot/set_title"
            hints.append(
                f"plt.subplots() 回傳的 axes 是 numpy.ndarray，不能直接呼叫 .{_method}()！\n"
                "正確做法: ax = get_ax(axes, i)  然後 ax." + _method + "(data)\n"
                "或改用 plt.subplots(1, 1) 只建一個 axes，直接回傳單一 axes 物件而非 ndarray。\n"
                "get_ax(axes, i) 已預載入 namespace，直接呼叫即可。"
            )
        # list.items() — anomaly_intervals 是 list，不是 dict
        if "'list' object has no attribute 'items'" in e or (
            "has no attribute" in e and "'items'" in e
        ):
            hints.append(
                "report['anomaly_intervals'] 是 list（如 ['50-69','100-120']），不是 dict！\n"
                "不能用 .items()。正確的做法:\n"
                "  - 要取切好的 DataFrame: for key, df_seg in df_intervals.items()  ← df_intervals 才是 dict\n"
                "  - 要遍歷區間字串: for key in report['anomaly_intervals']:\n"
                "  - report['anomaly_intervals'] 和 df_intervals 是兩個不同的東西！"
            )
        # plt.subplots(nrows=0) — 空列表長度當 subplot 數
        if "number of rows must be a positive integer" in e:
            hints.append(
                "plt.subplots 的 nrows/ncols 不能是 0。"
                "在呼叫前先檢查 list 是否為空: if len(cols) == 0: print('無資料'); 否則再 subplots。"
            )
        # SANITIZER-R15: 不能覆蓋系統保護變數
        if "SANITIZER-R15" in e:
            hints.append(
                "df_intervals、df_active、df_baseline、report 是系統預載入的保護變數，禁止重新賦值！\n"
                "常見錯誤: df_intervals = report['anomaly_intervals']  ← 這會把 dict 蓋成 list！\n"
                "正確做法:\n"
                "  - 要遍歷異常區間: for key, df_seg in df_intervals.items():  ← df_intervals 已是 dict\n"
                "  - 不需要重新建立 df_intervals，直接用就好\n"
                "  - 若要建子集: df_seg = df_intervals['50-69']  ← 用新變數名"
            )
        # df_intervals key 是字串 "start-end"，不能 unpack 成 (s, e)
        if "too many values to unpack" in e:
            hints.append(
                'anomaly_intervals 的元素和 df_intervals 的 key 都是字串 "50-69"，不是 tuple！'
                '\n不能 for s, e in report["anomaly_intervals"] 或 for (s,e), df in df_intervals.items()'
                "\n正確寫法： for key, df_seg in df_intervals.items():"
                '\n若需要 start/end 整數： parts = key.split("-"); start=int(parts[0]); end=int(parts[1])'
                "\n\n=== Sigma API 回傳格式（直接回傳 list，不用取 key！）==="
                "\ncompare_groups → [(col, mean_a, mean_b, diff, t_stat, p_val)] → 6 個值"
                "\n  正確: for col, ma, mb, d, t, p in sigma.compare_groups(...):"
                "\ndetect_outliers_iqr → [(col, count, ratio)] → 3 個值"
                "\n  正確: for col, n, r in sigma.detect_outliers_iqr(...):"
                "\ntop_correlations → [(colA, colB, corr)] → 3 個值"
                "\n  正確: for a, b, r in sigma.top_correlations(...):"
                "\nt2_contribution → ([(col, score)], [col, ...]) → tuple! 要解包"
                "\n  正確: scores, names = sigma.t2_contribution(df, idx)"
                "\nfind_anomalies → dict! result['top_suspects']: [(col, diff)] → 2 個值"
            )
        # int("50-69") 失敗——字串含有 -
        if "invalid literal for int" in e:
            hints.append(
                'anomaly_intervals 的元素是 "50-69" 格式的字串，不能直接 int()!'
                '\n取起止點: parts = key.split("-"); start = int(parts[0]); end = int(parts[1])'
                "\n最簡單: 就用 for key, df_seg in df_intervals.items() 直接取切好的 DataFrame，不需要手動切"
            )
        # .str accessor 只能用在字串欄位
        if ".str accessor" in e or "can only use .str accessor" in e:
            hints.append(
                "df_active / df_anomaly / df_baseline 的 index 是整數（非字串），不能用 .str！\n"
                "常見錯誤: df_active.index.str.contains('50') — index 是 int，沒有 .str\n"
                "正確替代方案:\n"
                "  - 篩選區段: df_active.iloc[start:end+1] （位置切片）\n"
                "  - 用 df_intervals[key] 直接取該區間 DataFrame（最推薦）\n"
                "  - 篩選欄位名稱才能用 .str: [c for c in df_active.columns if 'ABC' in c]\n"
                "  - 整數 index 過濾: df_active[df_active.index.isin([50, 51, 52])]"
            )
        # spearmanr 維度不匹配 — 不能拿 1 筆跟 N 筆做相關
        if "concatenation axis" in e and "spearmanr" in e:
            hints.append(
                "spearmanr 需要兩組等長的陣列。不能拿單一異常點 (size=1) 跟 baseline (size=N) 做相關。"
                "改用 baseline window 的完整資料: spearmanr(df_baseline[col_a], df_baseline[col_b])。"
            )
        # plt.plot() 不支援 facecolor，要用 color
        if "unexpected keyword argument 'facecolor'" in e:
            hints.append(
                "plt.plot() / Line2D 不支援 facecolor。改用 color='...' 參數。"
                "facecolor 只能用在 fill / patch / bar 等有面積的物件。"
            )
        # SyntaxError: 中文欄位名含括號放進 f-string {} 裡
        if "SyntaxError" in e:
            hints.append(
                "SyntaxError 常見原因: f-string 的 {} 裡不能直接放欄位名（如 (AD)塗佈量）！\n"
                '錯誤: f"{(AD)塗佈量} 的值"\n'
                "正確: col = '(AD)塗佈量'; f\"{col} 的值: {df_active[col].mean():.2f}\"\n"
                '或直接不用 {}: f"(AD)塗佈量 的值: {mean_val:.2f}"'
            )
        # ttest_ind 小樣本被 guardrail 攔截
        if "t-test" in e and "至少 5 筆" in error_msg:
            hints.append(
                "不能對單一異常點做 t-test（只有 1 筆）。"
                "改用 robust_z(value, median, mad) 計算 z-score。"
                "median = df_baseline[col].median(); mad = median_abs_deviation(df_baseline[col]); "
                "z = robust_z(df_anomaly[col].values, median, mad)"
            )
        # median_abs_deviation 是函式，不是 Series 方法
        if "has no attribute 'median_abs_deviation'" in e:
            hints.append(
                "median_abs_deviation 是函式呼叫，不是 pandas 方法。"
                "正確: median_abs_deviation(series)　錯誤: series.median_abs_deviation()"
            )
        # t2_contribution / t2_contribution_marginal 缺少 anomaly_indices
        if "missing" in e and "anomaly_indices" in e:
            hints.append(
                "t2_contribution(df, anomaly_indices) 和 t2_contribution_marginal(df, anomaly_indices) "
                "都需要 anomaly_indices 參數！\n"
                "正確: sigma.t2_contribution(df_active, list(df_anomaly.index))\n"
                "或: sigma.t2_contribution_marginal(df_active, list(df_anomaly.index))"
            )
        # dict[:5] → KeyError: slice — sigma 回傳是 dict，不能直接切片
        if "KeyError: slice" in e:
            hints.append(
                "sigma 工具回傳的是 dict，不能直接切片 result[:5]！\n"
                "正確做法: result['top_diffs'][:5] 或 result['pairs'][:5] — 先取 key 再切。"
            )
        # series[N] → KeyError: N (label 不在 index 裡)
        import re as _hint_re

        if _hint_re.search(r"KeyError: \d+", e):
            hints.append(
                "df_active 的 index 可能不包含這個數字。"
                "不能用 series[N]，要用 series.iloc[N] (位置索引) 或 series.values[N]。"
                "存取 dict 時先確認 key 存在: dict.get(N, default)。"
            )
        # report key 不存在
        if "KeyError" in e and any(
            k in e
            for k in ["hotelling", "pca", "t2_contrib", "drift_scan", "target_analysis"]
        ):
            hints.append(
                "report 的 key 取決於 task_type: "
                "anomaly→hotelling/pca/t2_contrib; "
                "optimization→target_analysis; "
                "drift→drift_scan。"
                "存取前先用 report.get('key') 檢查是否存在。"
            )

        # KeyError: 'start' / 'end' — split("-") 結果被當成 column name
        if any(f"keyerror: '{k}'" in e for k in ["start", "end", "50", "69", "begin"]):
            hints.append(
                "KeyError: 'start' 或數字字串表示 key.split('-') 的結果被當成 DataFrame 欄位名！\n"
                "split('-') 回傳的是字串 ('50', '69')，不能當作 df['start'] 或 df[start] 存取欄位。\n"
                "正確做法:\n"
                "  - 直接用: df_intervals[key] 取已切好的區間 DataFrame（推薦）\n"
                "  - 若要手動切: start_i = int(key.split('-')[0]); end_i = int(key.split('-')[1])\n"
                "    然後: df_seg = df_active.iloc[start_i:end_i+1] （iloc 才是位置切片）"
            )
        # NameError — LLM 用了未定義的變數
        if "NameError" in e and "is not defined" in e:
            hints.append(
                "NameError: 變數未定義。namespace 中已預載入的變數: "
                "df_active, df_anomaly, df_baseline, df_intervals, report, sigma, "
                "anomaly_indices, data_summary。"
                "\n若需要目標欄位清單，用 focus_targets (list[str])。"
                "\n不可自行定義已不存在的 report 子 key，先用 report.get('key') 確認。"
            )
        # === 通用 KeyError — LLM 猜錯 dict key ===
        if "keyerror" in e and not hints:
            import re as _rke

            _bad_key = _rke.search(r"KeyError:\s*['\"]?(\w+)['\"]?", error_msg)
            _key_name = _bad_key.group(1) if _bad_key else "?"
            hints.append(
                f"KeyError: '{_key_name}' — 這個 key 不存在於該 dict 中。\n"
                "不要猜測 dict 的 key 名稱！正確做法:\n"
                "  1. 先用 print(my_dict.keys()) 看 dict 實際有哪些 key\n"
                "  2. 用 my_dict.get('key', default) 安全存取\n"
                "  3. sigma 工具回傳的 dict key 名稱以 data_summary 中印出的為準"
            )

        return " | ".join(hints) if hints else ""

    def _get_max_rounds(self, task_type: str) -> int:
        """從 SCENARIO_CONFIG 取場景專屬 max_rounds"""
        from backend.services.analysis.agents.roles_v3.code_analyst import (
            SCENARIO_CONFIG,
        )

        config = SCENARIO_CONFIG.get(task_type, {})
        return config.get("max_rounds", 3)

    def _evaluate_should_continue(
        self,
        round_num: int,
        task_type: str,
        stdout: str,
        max_rounds: int,
        findings: dict = None,
        accumulated_evidence: list = None,
    ) -> dict:
        """
        L4 Governor: 結構化驗證 + stagnation 偵測。

        三層判斷:
        1. SCENARIO_CONFIG.completion_check (結構化 findings 驗證)
        2. LLM 的 [ANALYSIS_COMPLETE] 信號
        3. Stagnation 偵測 (連續無新 evidence)

        Returns:
            {"action": "STOP" | "CONTINUE", "reason": str, "focus_targets": list}
        """
        from backend.services.analysis.agents.roles_v3.code_analyst import (
            SCENARIO_CONFIG,
        )

        config = SCENARIO_CONFIG.get(task_type, SCENARIO_CONFIG.get("general", {}))
        min_rounds = config.get("min_rounds", 1)
        completion_check = config.get("completion_check")
        findings = findings or {}
        accumulated_evidence = accumulated_evidence or []

        # 安全閥: 達到上限強制停止
        if round_num >= max_rounds:
            return {"action": "STOP", "reason": f"已達最大輪數 ({max_rounds})"}

        # --- Governor Layer 1: 結構化 completion_check ---
        if completion_check and round_num >= min_rounds:
            if completion_check(stdout, findings):
                logger.info(
                    f"[V3:Governor] Round {round_num}: completion_check PASSED for {task_type}"
                )
                # 如果 LLM 也說完了，直接停
                if "[ANALYSIS_COMPLETE]" in stdout:
                    return {"action": "STOP", "reason": "Governor + LLM 皆判斷完成"}
                # Governor 通過但 LLM 沒說完 → 也停（Governor 優先）
                return {"action": "STOP", "reason": f"Governor 判斷完成 ({task_type})"}

        # --- Governor Layer 2: LLM 自行判斷 ---
        if "[ANALYSIS_COMPLETE]" in stdout:
            if round_num < min_rounds:
                logger.info(
                    f"[V3:Governor] Round {round_num} ANALYSIS_COMPLETE ignored, "
                    f"forcing continue (min_rounds={min_rounds} for {task_type})"
                )
                suspects = self._extract_suspects_from_stdout(stdout)
                return {
                    "action": "CONTINUE",
                    "reason": f"系統強制至少 {min_rounds} 輪",
                    "focus_targets": suspects[:5],
                }
            return {"action": "STOP", "reason": "LLM 判斷分析已完成"}

        # --- Governor Layer 3: Stagnation 偵測 ---
        if len(accumulated_evidence) >= 2:
            last_two = accumulated_evidence[-2:]
            # 如果連續兩輪的 primary_column 相同 → 卡住了
            cols = [e.get("primary_column", "") for e in last_two]
            if cols[0] and cols[0] == cols[1]:
                logger.warning(
                    f"[V3:Governor] Stagnation detected: {cols[0]} repeated 2 rounds"
                )
                return {
                    "action": "CONTINUE",
                    "reason": f"偵測到停滯 ({cols[0]} 重複)，強制換方向",
                    "focus_targets": [f"⚠ 不要再分析 {cols[0]}，換其他欄位深入"],
                }

        # 未完成 → 繼續
        suspects = self._extract_suspects_from_stdout(stdout)
        return {
            "action": "CONTINUE",
            "reason": f"第 {round_num} 輪完成，繼續深入",
            "focus_targets": suspects[:5],
        }

    def _extract_suspects_from_stdout(self, stdout: str) -> list:
        """
        從 stdout 中提取嫌疑欄位名稱。
        匹配 sigma 函式的標準輸出格式。
        """
        suspects = []
        # 匹配 sigma 輸出的嫌疑犯格式: "  COLUMN_NAME: 均值差 xxx" 或 "  COLUMN_NAME: xxx"
        # 也匹配 "COLUMN_NAME: N 個偏移區段"
        for line in stdout.split("\n"):
            line = line.strip()
            # sigma 嫌疑犯格式: "FORMULA-DCS_A19: 均值差 73.8016"
            match = re.match(r"^([A-Z][A-Z0-9_\-]+): .+", line)
            if match:
                col_name = match.group(1)
                # 過濾掉太短的名字（避免誤匹配）
                if len(col_name) > 4 and "-" in col_name:
                    suspects.append(col_name)

        # 去重保持順序
        seen = set()
        unique = []
        for s in suspects:
            if s not in seen:
                seen.add(s)
                unique.append(s)
        return unique[:10]  # 最多 10 個

    # ============================================================
    # _run_flat_tools: 扁平工具遍歷 (原有邏輯)
    # ============================================================

    async def _run_flat_tools(
        self,
        ctx: Context,
        ev: ToolExecuteEvent,
        route: RouteIntentOutput,
        tools: list,
        target_params: list,
        target_range: str,
    ) -> AnalysisDoneEvent:
        """扁平遍歷 suggested_tools 執行工具鏈 (使用統一注入器)"""
        from backend.services.analysis.agents.deep_chain import inject_tool_params
        from backend.services.analysis.agents.ci_helpers import extract_finding_text

        first_param = target_params[0] if target_params else None
        reference_params = getattr(route, "reference_params", []) or []
        baseline_range = getattr(route, "baseline_range", "") or ""

        key_findings = []
        tool_results = []

        for tool_name in tools:
            params = inject_tool_params(
                tool_name=tool_name,
                file_id=ev.file_id,
                target_params=target_params or None,
                reference_params=reference_params or None,
                target_range=target_range if target_range != "all" else None,
                baseline_range=baseline_range or None,
            )

            ctx.write_event_to_stream(
                ProgressEvent(msg=f"執行: {tool_name}...", turn=0)
            )

            try:
                res = await self.tool_executor.execute_tool(
                    tool_name,
                    params,
                    ev.session_id,
                )
                is_error = isinstance(res, dict) and bool(res.get("error"))
                tool_results.append(
                    ToolChainResult(
                        tool_name=tool_name,
                        params=params,
                        success=not is_error,
                        result=res,
                        error=res.get("error") if isinstance(res, dict) else None,
                    )
                )

                if isinstance(res, dict) and not res.get("error"):
                    # --- 摘取 key finding ---
                    finding_text = extract_finding_text(res, first_param)
                    if finding_text:
                        key_findings.append(finding_text)

                    # --- 串流工具結果摘要到思考流程 ---
                    thought_lines = [f"[{tool_name}] 完成"]
                    thought_lines.append(f"  參數: {params}")
                    if finding_text:
                        thought_lines.append(f"  發現: {finding_text}")
                    ctx.write_event_to_stream(
                        MonologueEvent(
                            monologue="\n".join(thought_lines),
                            tool_name=tool_name,
                            tool_params=params,
                            query=route.restatement,
                            file_id=ev.file_id,
                            session_id=ev.session_id,
                            history="",
                        )
                    )

                    # --- 如果有圖表資料，串流 MINI_CHART ---
                    # 優先: 工具自帶 chart (trend_prediction, radar_chart 等)
                    # Fallback: _extract_chart_data 從統計結果自動生成
                    _builtin_chart = res.get("chart") if isinstance(res, dict) else None
                    _extracted_chart = self._extract_chart_data(
                        res, tool_name, first_param
                    )
                    chart_json = _builtin_chart or _extracted_chart
                    logger.info(
                        f"[V3:Chart] {tool_name}: "
                        f"keys={list(res.keys()) if isinstance(res, dict) else 'N/A'}, "
                        f"builtin={'YES' if _builtin_chart else 'NO'}, "
                        f"extracted={'YES' if _extracted_chart else 'NO'}"
                    )
                    if chart_json:
                        import json as _json

                        ctx.write_event_to_stream(
                            MonologueEvent(
                                monologue=f"[MINI_CHART]{_json.dumps(chart_json, ensure_ascii=False)}",
                                tool_name=tool_name,
                                tool_params=params,
                                query=route.restatement,
                                file_id=ev.file_id,
                                session_id=ev.session_id,
                                history="",
                            )
                        )

                else:
                    err = (
                        res.get("error", "未知錯誤")
                        if isinstance(res, dict)
                        else str(res)
                    )
                    key_findings.append(f"{tool_name} 失敗: {err}")

            except Exception as e:
                logger.warning(f"[V3:Execute] {tool_name} failed: {e}")
                tool_results.append(
                    ToolChainResult(
                        tool_name=tool_name,
                        params=params,
                        success=False,
                        error=str(e),
                    )
                )

        if not key_findings:
            key_findings.append("分析完成，未發現顯著異常")

        status = "ok" if key_findings else "no_anomaly_found"
        result = PlaybookResult(
            task_type=route.task_type,
            status=status,
            key_findings=key_findings,
            tool_results=tool_results,
        )

        # 視覺化專用工具: 跳過 Humanizer
        VISUAL_ONLY_TOOLS = {"draw_trend", "get_time_series_data"}
        is_visual_only = all(t in VISUAL_ONLY_TOOLS for t in tools)

        return AnalysisDoneEvent(
            result=result,
            restatement=route.restatement,
            file_id=ev.file_id,
            session_id=ev.session_id,
            skip_humanizer=is_visual_only,
        )

    # ============================================================
    # _extract_chart_data: 工具結果圖表提取
    # ============================================================

    def _extract_chart_data(
        self,
        result: dict,
        tool_name: str,
        param_name: str = None,
    ) -> dict | None:
        """從工具結果中提取 Chart.js JSON (delegate to chart_extractors registry)。"""
        from backend.services.analysis.agents.chart_extractors import (
            extract_chart_data,
        )

        return extract_chart_data(result, tool_name, param_name)

    async def _run_deep_chain(
        self,
        ctx: Context,
        ev: ToolExecuteEvent,
        route: RouteIntentOutput,
        chain_type: str,
    ) -> AnalysisDoneEvent:
        """
        Deep Chain: 逐層執行工具鏈，每層萃取結果注入下一層。
        不增加 LLM 調用（純計算 + 規則萃取）。
        """
        from backend.services.analysis.agents.deep_chain import (
            DEEP_CHAIN_TEMPLATES,
            extract_from_layer,
            build_next_layer_tasks,
        )
        from backend.services.analysis.agents.ci_helpers import extract_finding_text

        layers = DEEP_CHAIN_TEMPLATES.get(chain_type, [])
        if not layers:
            logger.warning(
                f"[V3:DeepChain] No template for '{chain_type}', falling back to flat"
            )
            return await self._run_flat_tools(
                ctx,
                ev,
                route,
                route.suggested_tools or [],
                route.target_params or [],
                route.target_range or "all",
            )

        all_key_findings = []
        all_tool_results = []
        prev_extracted = None

        # 從 route 取得輸入參數
        input_target_params = route.target_params or []
        input_target_range = route.target_range or []
        input_baseline_range = getattr(route, "baseline_range", "") or ""

        for layer_idx, layer_template in enumerate(layers):
            layer_label = layer_template.get("label", f"Layer {layer_idx + 1}")
            layer_tools = layer_template["tools"]
            extract_key = layer_template.get("extract_key", "")

            logger.info(
                f"[V3:DeepChain:L{layer_idx + 1}] {layer_label} → tools={layer_tools}"
            )
            ctx.write_event_to_stream(
                ProgressEvent(
                    msg=f"深度分析 [{layer_idx + 1}/{len(layers)}]: {layer_label}...",
                    turn=0,
                )
            )

            # --- 建構本層任務 ---
            if layer_idx == 0:
                # 第一層: 直接執行
                inject_mode = layer_template.get("inject_mode", "once")
                if inject_mode == "use_input" and input_target_params:
                    # 有目標參數的場景: 直接把目標參數注入第一層
                    tasks = build_next_layer_tasks(
                        layer_template,
                        None,
                        ev.file_id,
                        input_target_params=input_target_params,
                        input_target_range=input_target_range,
                    )
                else:
                    # 無目標參數: 全域掃描
                    tasks = []
                    for t in layer_tools:
                        p = {"file_id": ev.file_id}
                        for tr in input_target_range:
                            p["focus_range"] = tr  # 相容舊版 tool param
                        if input_baseline_range:
                            p["baseline_range"] = input_baseline_range
                        tasks.append(
                            {"tool_name": t, "params": p, "source_param": None}
                        )
            else:
                # 後續層: 用上一層萃取結果注入
                if prev_extracted is None or not prev_extracted.get("params"):
                    logger.info(f"[V3:DeepChain:L{layer_idx + 1}] 上層無發現，提前終止")
                    all_key_findings.append(f"[{layer_label}] 跳過: 上層未發現異常")
                    break

                tasks = build_next_layer_tasks(
                    layer_template,
                    prev_extracted,
                    ev.file_id,
                    input_target_params=input_target_params,
                    input_target_range=input_target_range,
                )
                if not tasks:
                    logger.info(f"[V3:DeepChain:L{layer_idx + 1}] 無可用任務，跳過")
                    break

            # --- 執行本層所有任務 ---
            layer_results = []
            for task in tasks:
                tool_name = task["tool_name"]
                params = task["params"]
                source_param = task.get("source_param", "")

                param_hint = f"({source_param})" if source_param else ""
                ctx.write_event_to_stream(
                    ProgressEvent(
                        msg=f"  執行: {tool_name}{param_hint}...",
                        turn=0,
                    )
                )

                try:
                    res = await self.tool_executor.execute_tool(
                        tool_name, params, ev.session_id
                    )
                    is_error = isinstance(res, dict) and bool(res.get("error"))
                    tool_result = ToolChainResult(
                        tool_name=tool_name,
                        params=params,
                        success=not is_error,
                        result=res,
                        error=res.get("error") if isinstance(res, dict) else None,
                    )
                    all_tool_results.append(tool_result)
                    if not is_error:
                        layer_results.append(res)

                        # --- 串流工具結果到思考流程 ---
                        finding_text = extract_finding_text(res, source_param or None)

                        thought_lines = [f"[{tool_name}]{param_hint} 完成"]
                        thought_lines.append(f"  參數: {params}")
                        if finding_text:
                            thought_lines.append(f"  發現: {finding_text}")
                        ctx.write_event_to_stream(
                            MonologueEvent(
                                monologue="\n".join(thought_lines),
                                tool_name=tool_name,
                                tool_params=params,
                                query=route.restatement,
                                file_id=ev.file_id,
                                session_id=ev.session_id,
                                history="",
                            )
                        )

                        # --- MINI_CHART ---
                        # 優先: 工具自帶 chart, Fallback: 自動生成
                        chart_json = (
                            res.get("chart") if isinstance(res, dict) else None
                        ) or self._extract_chart_data(
                            res, tool_name, source_param or None
                        )
                        if chart_json:
                            import json as _json

                            ctx.write_event_to_stream(
                                MonologueEvent(
                                    monologue=f"[MINI_CHART]{_json.dumps(chart_json, ensure_ascii=False)}",
                                    tool_name=tool_name,
                                    tool_params=params,
                                    query=route.restatement,
                                    file_id=ev.file_id,
                                    session_id=ev.session_id,
                                    history="",
                                )
                            )

                    logger.info(
                        f"[V3:DeepChain:L{layer_idx + 1}] "
                        f"{tool_name}{param_hint} → "
                        f"{'OK' if not is_error else 'ERROR'}"
                    )

                except Exception as e:
                    logger.warning(
                        f"[V3:DeepChain:L{layer_idx + 1}] "
                        f"{tool_name}{param_hint} failed: {e}"
                    )
                    all_tool_results.append(
                        ToolChainResult(
                            tool_name=tool_name,
                            params=params,
                            success=False,
                            error=str(e),
                        )
                    )

            # --- 萃取本層結果 ---
            if layer_results and extract_key:
                prev_extracted = extract_from_layer(layer_results, extract_key)
                # 將本層發現加入 key_findings
                for finding in prev_extracted.get("findings", []):
                    all_key_findings.append(f"[L{layer_idx + 1}] {finding}")
                logger.info(
                    f"[V3:DeepChain:L{layer_idx + 1}] "
                    f"萃取: {len(prev_extracted['params'])} 參數, "
                    f"{len(prev_extracted.get('findings', []))} 發現"
                )
            else:
                prev_extracted = None

        # --- 彙整結果 ---
        if not all_key_findings:
            all_key_findings.append("深度分析完成，未發現顯著異常")

        # 串流思考過程
        chain_summary = (
            f"Deep Chain ({chain_type}) 完成: "
            f"{len(layers)} 層, "
            f"{len(all_tool_results)} 個工具呼叫, "
            f"{len(all_key_findings)} 個發現"
        )
        ctx.write_event_to_stream(
            MonologueEvent(
                monologue=chain_summary + "\n" + "\n".join(all_key_findings[:10]),
                tool_name="deep_chain",
                tool_params={"chain_type": chain_type},
                query=route.restatement,
                file_id=ev.file_id,
                session_id=ev.session_id,
                history="",
            )
        )

        result = PlaybookResult(
            task_type=route.task_type,
            status="ok",
            key_findings=all_key_findings,
            tool_results=all_tool_results,
        )

        return AnalysisDoneEvent(
            result=result,
            restatement=route.restatement,
            file_id=ev.file_id,
            session_id=ev.session_id,
        )

    @step
    async def humanize(self, ctx: Context, ev: AnalysisDoneEvent) -> StopEvent:
        """
        [LLM #2] 結構化結果 → 人話報告

        報告長度根據工具數量自動調整
        """
        from backend.services.analysis.agents.roles_v3.humanizer_v3 import HumanizerV3
        from backend.services.analysis.agents.roles_v3.evidence_evaluator import (
            EvidenceEvaluator,
        )

        result = ev.result
        logger.info(
            f"[V3:Humanizer] task_type={result.task_type}, "
            f"findings={len(result.key_findings)}"
        )

        # 視覺化工具跳過 Humanizer，直接顯示圖表
        evaluated = []  # 預設空，skip_humanizer 時不會有 findings
        if ev.skip_humanizer:
            logger.info("[V3:Humanizer] skip_humanizer=True, 跳過報告生成")
            report = f"✅ {ev.restatement}"
            ctx.write_event_to_stream(TextChunkEvent(content=report))
        else:
            ctx.write_event_to_stream(ProgressEvent(msg="正在評估分析結果...", turn=0))

            # ── Evidence Evaluator (純 Python, <100ms) ──
            evaluator = EvidenceEvaluator()
            # 從 tool_results 提取各輪 stdout
            stdout_rounds = []
            for tr in result.tool_results:
                _r = tr.result if hasattr(tr, "result") else tr.get("result", {})
                if isinstance(_r, dict) and "outputs" in _r:
                    for _o in _r["outputs"]:
                        _s = _o.get("stdout", "")
                        if _s:
                            stdout_rounds.append(_s)

            evaluated = evaluator.evaluate(
                all_findings=result.key_findings,
                stdout_rounds=stdout_rounds,
                data_summary=ev.data_summary or "",
                prep=ev.prep,
                task_type=result.task_type,
            )
            evaluated_text = evaluator.format_for_humanizer(evaluated)

            # ── Chart-to-Finding Mapping ──
            chart_mapping = {}
            if ev.chart_titles and evaluated:
                chart_mapping = evaluator.match_charts_to_findings(
                    evaluated, ev.chart_titles
                )
                # 給前端發 mapping event
                ctx.write_event_to_stream(
                    ProgressEvent(
                        msg=f"__CHART_MAPPING__{__import__('json').dumps(chart_mapping)}",
                        turn=0,
                    )
                )

            # 用評估後的 findings 替換原始 findings
            if evaluated:
                evaluated_findings = [
                    f"[{ef.severity.upper()}|{ef.evidence_grade}] {ef.verdict}: {ef.raw_text[:200]}"
                    for ef in evaluated
                ]
            else:
                # 區分「真的沒異常」vs「code 執行錯誤導致沒結果」
                _has_errors = any("ERROR" in f for f in result.key_findings)
                if _has_errors:
                    evaluated_findings = [
                        "分析過程中程式碼執行發生錯誤，以下根據前處理階段數據提供初步結論。",
                        f"前處理摘要: {ev.data_summary[:500]}"
                        if ev.data_summary
                        else "",
                    ]
                else:
                    evaluated_findings = [
                        "分析完成，未發現顯著異常（所有指標均在正常管制範圍內）"
                    ]

            ctx.write_event_to_stream(ProgressEvent(msg="正在生成報告...", turn=0))

            # 呼叫 HumanizerV3 (LLM #2) — 串流模式
            humanizer = HumanizerV3(self.llm)

            # === Token 計算 (debug) ===
            _ef_text = "\n".join(str(f) for f in evaluated_findings)
            _tr_text = str(result.tool_results)
            _ds_text = ev.data_summary or ""
            _ev_text = evaluated_text or ""
            _total = len(_ef_text) + len(_tr_text) + len(_ds_text) + len(_ev_text)
            _tr_lines = []
            for _tr in result.tool_results:
                _tn = (
                    _tr.get("tool_name", "?")
                    if isinstance(_tr, dict)
                    else getattr(_tr, "tool_name", "?")
                )
                _r = (
                    _tr.get("result", {})
                    if isinstance(_tr, dict)
                    else getattr(_tr, "result", {})
                )
                if isinstance(_r, dict):
                    for _k, _v in _r.items():
                        _tr_lines.append(f"    [{_tn}].{_k}: {len(str(_v)):>6} chars")
                else:
                    _tr_lines.append(f"    [{_tn}]: {len(str(_r)):>6} chars")
            _bd = "\n".join(_tr_lines) if _tr_lines else "    (empty)"
            logger.warning(
                f"\n{'=' * 60}\n"
                f"[Humanizer Input Token Count]\n"
                f"  key_findings:        {len(_ef_text):>8} chars ({len(_ef_text) // 4:>6} tokens est.)\n"
                f"  tool_results:        {len(_tr_text):>8} chars ({len(_tr_text) // 4:>6} tokens est.)\n"
                f"{_bd}\n"
                f"  data_summary:        {len(_ds_text):>8} chars ({len(_ds_text) // 4:>6} tokens est.)\n"
                f"  evaluation_summary:  {len(_ev_text):>8} chars ({len(_ev_text) // 4:>6} tokens est.)\n"
                f"  ---\n"
                f"  TOTAL:               {_total:>8} chars ({_total // 4:>6} tokens est.)\n"
                f"{'=' * 60}"
            )

            full_report_parts = []
            async for chunk in humanizer.generate_report_stream(
                restatement=ev.restatement,
                key_findings=evaluated_findings,
                tool_results=result.tool_results,
                data_summary=ev.data_summary,
                evaluation_summary=evaluated_text,
            ):
                ctx.write_event_to_stream(TextChunkEvent(content=chunk))
                full_report_parts.append(chunk)

            # post-processing: evidence gate
            report = "".join(full_report_parts).strip()
            report = humanizer._post_process(report, result.tool_results)

            # post-processing: 程式化注入 📊 目標參數段落（取代 LLM 生成的）
            if ev.prep and isinstance(ev.prep, dict):
                _param_md = EvidenceEvaluator.generate_param_markdown(ev.prep)
                if _param_md:
                    import re as _re

                    # 移除 LLM 生成的 📊 段落 + 整體總結表
                    # 找到「目標參數」相關 heading 和「發現」heading 之間的內容
                    _pattern = _re.compile(
                        r"(###?\s*目標參數.*?)(?=###?\s*發現|###?\s*行動|$)",
                        _re.DOTALL,
                    )
                    if _pattern.search(report):
                        report = _pattern.sub(_param_md + "\n", report, count=1)
                    else:
                        # LLM 沒寫 📊 heading — 在概述後面插入
                        _overview_end = _re.search(r"\n(###?\s*發現|\n---)", report)
                        if _overview_end:
                            insert_pos = _overview_end.start()
                            report = (
                                report[:insert_pos]
                                + "\n\n"
                                + _param_md
                                + report[insert_pos:]
                            )
                        else:
                            # fallback: 直接加在報告最前面
                            report = _param_md + "\n\n" + report
                    logger.info(
                        f"[V3:Humanizer] Injected programmatic 📊 sections "
                        f"({len(_param_md)} chars)"
                    )

        # 保存 SessionContext
        self._save_session_context(
            session_id=ev.session_id,
            file_id=ev.file_id,
            restatement=ev.restatement,
            key_findings=result.key_findings,
            target_params=[],
            task_type=result.task_type,
        )

        # 組裝最終結果
        # 將 evaluated findings 轉為前端可渲染的 structured_report
        _structured_report = None
        if evaluated:
            _sr_findings = []
            for ef in evaluated:
                _detail_parts = [ef.verdict]
                for m in ef.metrics[:3]:
                    _detail_parts.append(f"{m.note}: T²_drop={m.value:.2f}")
                _sr_findings.append(
                    {
                        "title": ef.title,
                        "severity": ef.severity.upper(),
                        "detail": " | ".join(_detail_parts),
                    }
                )
            _structured_report = {
                "findings": _sr_findings,
                "executive_summary": (
                    f"共 {len(_sr_findings)} 個發現 "
                    f"(高={sum(1 for f in _sr_findings if f['severity'] == 'HIGH')}, "
                    f"中={sum(1 for f in _sr_findings if f['severity'] == 'MEDIUM')}, "
                    f"低={sum(1 for f in _sr_findings if f['severity'] == 'LOW')})"
                ),
            }

        final_result = {
            "response": report,
            "task_type": result.task_type,
            "key_findings": result.key_findings,
            "status": result.status,
            "tool_result": {"structured_report": _structured_report}
            if _structured_report
            else {},
        }

        return StopEvent(result=final_result)
