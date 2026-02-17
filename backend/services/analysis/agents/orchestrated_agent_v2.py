from typing import Any, Dict, AsyncGenerator, List
import logging
from backend.services.analysis.analysis_types import (
    StartEvent,
    AnalysisState,
    AnalysisContext,
    RoleInput,
    RoleOutput,
    StepResult,
    ProgressEvent,
    MonologueEvent,
    TextChunkEvent,
    ExperimentContext,
    Evidence,
    AnalysisReport,
)
from collections import Counter

# Import V2 Roles
from .roles_v2.strategist import Strategist
from .roles_v2.planner import ExperimentPlanner
from .roles_v2.executor import BatchExecutor
from .roles_v2.synthesizer import Synthesizer


class OrchestratedAnalysisAgentV2:
    """
    [V2 Architecture] Orchestrated Agent with Batch Analysis Loop
    Flow: Strategist -> Planner -> Executor -> Synthesizer
    """

    MAX_STEPS = 10  # Default max (overridden by mode)
    QUICK_MAX_STEPS = 5  # Quick mode: focused scan
    DEEP_MAX_STEPS = 60  # Deep mode: thorough investigation

    def __init__(self, llm: Any, tool_executor: Any, analysis_service: Any = None):
        self.llm = llm
        self.executor = tool_executor
        self.analysis_service = analysis_service
        self.logger = logging.getLogger("OrchestratedAgentV2")

        # [RESUME] In-memory cache of last analysis state per session
        self._last_states: Dict[
            str, Any
        ] = {}  # session_id -> (state, summary_data, mode)

        # Initialize V2 Roles
        self.roles = {
            "strategist": Strategist(llm),
            "planner": ExperimentPlanner(llm),
            "executor": BatchExecutor(llm, tool_executor),  # Uses updated adapter
            "synthesizer": Synthesizer(llm),
        }

    def has_saved_state(self, session_id: str) -> bool:
        """Check if there is a saved analysis state for this session."""
        return session_id in self._last_states

    async def run_analysis(
        self, start_event: StartEvent, summary_data: Dict, resume: bool = False
    ) -> AsyncGenerator[Any, None]:
        """
        V2 Main Loop (Async Batch Execution)
        """
        session_id = start_event.session_id

        # [RESUME PATH] If resuming from a previous analysis, load cached state
        if resume and session_id in self._last_states:
            cached = self._last_states[session_id]
            state = cached["state"]
            is_deep = cached["is_deep"]
            max_turns = cached["max_turns"]
            summary_data = cached["summary_data"]

            # Extend budget: add 3 more turns from current position
            extra_turns = 3
            new_max = state.step_count + extra_turns
            state = state.update(
                role_name="Resume",
                max_steps=new_max,
                current_knowledge=state.current_knowledge
                + f"\n[繼續分析] 用戶要求繼續。額外 {extra_turns} Turn 預算。新查詢: {start_event.query}",
            )

            mode_label = "深度分析" if is_deep else "快速回應"
            has_specific_targets = True  # Skip Turn 1 auto-scan on resume
            is_optimization = False  # Resume always uses Strategist

            yield ProgressEvent(
                msg=f"🔄 繼續上次分析 (從 Turn {state.step_count} 開始, 額外 {extra_turns} Turn)..."
            )
            self.logger.info(
                f"[RESUME] Continuing from step {state.step_count}, "
                f"history_len={len(state.history)}, max_steps={new_max}"
            )
        else:
            # [NORMAL PATH] Fresh analysis initialization
            # 1. Initialize State (Dashboard)
            # [Fix] Parse summary_data correctly (AnalysisService format)
            n_rows = summary_data.get(
                "total_rows", summary_data.get("n_rows", "Unknown")
            )
            columns = summary_data.get("parameters", summary_data.get("columns", []))

            # Construct schema from numerical_columns if dtypes unavailable
            numerical_cols = set(summary_data.get("numerical_columns", []))
            data_schema = {}
            for col in columns:
                data_schema[col] = "float" if col in numerical_cols else "object"

            data_summary_str = f"Rows: {n_rows}, Columns: {len(columns)}"
            if "quality_stats" in summary_data:
                q = summary_data["quality_stats"]
                data_summary_str += f", Null Cols: {q.get('null_column_count')}, Sparse: {q.get('sparse_column_count')}"

            # [NEW] Mode-based configuration
            analysis_mode = getattr(start_event, "mode", "quick") or "quick"
            is_deep = analysis_mode in ("deep", "full")
            if is_deep:
                max_turns = self.DEEP_MAX_STEPS
                mode_label = "深度分析"
            else:
                max_turns = self.QUICK_MAX_STEPS
                mode_label = "快速回應"

            # Detect if user specified targets (suspect_pool)
            suspect_pool = getattr(start_event, "suspect_pool", []) or []

            # --- [NEW] Query Pre-Processing ---
            import re
            import json as _json

            query = start_event.query or ""

            # 1. Resolve positional references (最後一個欄位, etc.) -- deterministic fallback
            if not suspect_pool and columns:
                positional_patterns = [
                    (r"最後\s*(?:一個|1個)?(?:欄位|參數|column|變數|變量)", -1),
                    (r"倒數第?\s*(?:一個|1個)?(?:欄位|參數|column|變數|變量)", -1),
                    (r"第\s*(?:一個|1個)?(?:欄位|參數|column|變數|變量)", 0),
                    (
                        r"倒數第\s*(\d+)\s*(?:個)?(?:欄位|參數|column|變數|變量)",
                        "neg_idx",
                    ),
                    (r"第\s*(\d+)\s*(?:個)?(?:欄位|參數|column|變數|變量)", "pos_idx"),
                ]
                for pattern, idx_type in positional_patterns:
                    m = re.search(pattern, query)
                    if m:
                        if idx_type == "neg_idx":
                            idx = -int(m.group(1))
                        elif idx_type == "pos_idx":
                            idx = int(m.group(1)) - 1  # 0-indexed
                        else:
                            idx = idx_type
                        try:
                            resolved_col = columns[idx]
                            suspect_pool = [resolved_col]
                            self.logger.info(
                                f"[QueryPreProcess] Resolved '{m.group()}' -> '{resolved_col}'"
                            )
                        except IndexError:
                            pass
                        break

            # 2. LLM-based intent classification (scalable, handles any phrasing)
            analysis_type = "anomaly_detection"  # default
            llm_target = None
            try:
                # Build a short column hint (first 5 + last 5 to keep prompt small)
                col_hint = (
                    columns[:5] + (["..."] if len(columns) > 10 else []) + columns[-5:]
                )
                col_hint_str = ", ".join(col_hint)

                classify_prompt = (
                    "你是工業數據分析系統的意圖分類器。根據用戶的問題,回傳一個 JSON:\n"
                    '{"type": "...", "target": "...", "goal": "..."}\n\n'
                    "type 必須是以下之一:\n"
                    "- optimization: 用戶想調整/降低/提高某個指標 (例: 如何降低不良率? 怎麼讓水分更均勻?)\n"
                    "- anomaly_detection: 用戶想找異常/診斷問題 (例: 哪些參數異常? 為什麼良率下降?)\n"
                    "- comparison: 用戶想比較不同區段/條件 (例: 前100筆和後100筆有什麼差異?)\n"
                    "- visualization: 用戶只想看圖/趨勢 (例: 畫出溫度的趨勢圖)\n\n"
                    "target: 用戶關注的目標欄位名稱 (從可用欄位中選擇最接近的)。\n"
                    '  - 若有多個目標 (如同時優化兩個欄位), 用逗號分隔: "col_a,col_b"\n'
                    "  - 若用戶說「最後兩個欄位」或類似語句,請從欄位清單中取最後兩個\n"
                    "  - 若無法確定則為 null。\n"
                    "goal: 用戶想達成的目標 (例: '降低', '提高', '穩定', '找出原因', '同時優化')。\n\n"
                    f"可用欄位 (部分): [{col_hint_str}]\n"
                    f"用戶問題: {query}\n\n"
                    "回傳 JSON (不要回傳其他內容):"
                )
                resp = await self.llm.acomplete(classify_prompt)
                resp_text = str(resp.text).strip()

                # Parse JSON from response (handle markdown code blocks)
                if "```" in resp_text:
                    resp_text = resp_text.split("```")[1]
                    if resp_text.startswith("json"):
                        resp_text = resp_text[4:]
                    resp_text = resp_text.strip()

                intent_result = _json.loads(resp_text)
                analysis_type = intent_result.get("type", "anomaly_detection")
                llm_target = intent_result.get("target")
                llm_goal = intent_result.get("goal", "")

                # Validate analysis_type
                if analysis_type not in (
                    "optimization",
                    "anomaly_detection",
                    "comparison",
                    "visualization",
                ):
                    analysis_type = "anomaly_detection"

                # If LLM found a target and we don't have one yet, try to match it
                if llm_target and not suspect_pool and columns:
                    # Handle multi-target: LLM may return "col_a,col_b"
                    raw_targets = [
                        t.strip() for t in llm_target.split(",") if t.strip()
                    ]
                    resolved = []
                    for rt in raw_targets:
                        if rt in columns:
                            resolved.append(rt)
                        else:
                            matches = [c for c in columns if rt.lower() in c.lower()]
                            if matches:
                                resolved.append(matches[0])
                    if resolved:
                        suspect_pool = resolved

                self.logger.info(
                    f"[IntentClassifier] type={analysis_type}, target={llm_target}, "
                    f"goal={llm_goal}, resolved_pool={suspect_pool}"
                )
            except Exception as e:
                self.logger.warning(
                    f"[IntentClassifier] LLM classification failed: {e}, using default"
                )
                analysis_type = "anomaly_detection"

            is_optimization = analysis_type == "optimization"
            has_specific_targets = len(suspect_pool) > 0

            state = AnalysisState(
                session_id=session_id,
                file_id=start_event.file_id,
                original_query=start_event.query,
                current_context=AnalysisContext(
                    targets=suspect_pool, feature_pool=summary_data.get("columns", [])
                ),
                data_summary=data_summary_str,
                data_schema=data_schema,
                max_steps=max_turns,
                current_knowledge="Analysis started.",
            )

            # Inject mode context into state so Strategist knows the depth expectation
            state.current_knowledge += (
                f"\n[模式: {mode_label}, 最多 {max_turns} Turn] "
                + (
                    "有足夠的 Turn 進行完整調查。請充分探索每個發現,進行相關性驗證、因果推理和殘差分析。"
                    if is_deep
                    else f"請在 {max_turns} 個 Turn 內完成分析。優先做全域掃描,快速定位問題。"
                )
            )

            # --- Inject Analysis Type Context (from LLM classification) ---
            is_multi_target = analysis_type == "optimization" and len(suspect_pool) > 1

            if analysis_type == "optimization" and suspect_pool:
                if is_multi_target:
                    # Multi-objective optimization path
                    target_names = ", ".join(suspect_pool)
                    targets_csv = ",".join(suspect_pool)
                    state.current_knowledge += (
                        f"\n\n[分析類型: 多目標優化] 用戶想同時優化: {target_names}"
                        f"\n[CRITICAL] 這是多目標問題! 需要先分析目標間的 Synergy/Trade-off 關係!"
                        f"\n[策略] Turn 1: 多目標分析+側寫"
                        f"\n  1. multi_objective_analysis(targets='{targets_csv}') - Synergy/Trade-off 分類"
                        f"\n  2. get_top_correlations 對每個目標 - 相關參數"
                        f"\n  3. performance_segmentation 對主要目標 - 好壞批次"
                        f"\n[策略] Turn 2: 邊際效應+因果"
                        f"\n  4. partial_dependence - 各參數對各目標的影響曲線"
                        f"\n  5. interaction_scatter - 兩關鍵參數的交互效應"
                        f"\n[策略] Turn 3: 多劇本建議"
                        f"\n  6. generate_operating_window - SOP"
                        f"\n[禁止] 不要做無目標的全域異常掃描!"
                    )
                else:
                    # Single-target optimization path
                    target_name = suspect_pool[0]
                    state.current_knowledge += (
                        f"\n\n[分析類型: 優化推薦] 用戶目標: 調整 '{target_name}' 的數值。"
                        f"\n[CRITICAL] 這不是異常檢測! 用戶想知道: 哪些參數影響 '{target_name}'? 怎麼調整能達到目標?"
                        f"\n[策略] Turn 1: 側寫+分割"
                        f"\n  1. get_top_correlations(target='{target_name}') - 找出相關參數"
                        f"\n  2. analyze_feature_importance(target='{target_name}') - 驅動因子"
                        f"\n  3. performance_segmentation(target='{target_name}') - 好壞批次分割"
                        f"\n[策略] Turn 2: 因果+邊際效應"
                        f"\n  4. partial_dependence(target='{target_name}') - 非線性影響曲線"
                        f"\n  5. cross_correlation_lag / causal_relationship_analysis - 因果驗證"
                        f"\n[策略] Turn 3: 操作建議"
                        f"\n  6. interaction_scatter - Sweet Spot 識別"
                        f"\n  7. generate_operating_window(target='{target_name}') - SOP 建議表"
                        f"\n[禁止] 不要做無目標的全域異常掃描!"
                    )
            elif analysis_type == "optimization" and not suspect_pool:
                state.current_knowledge += (
                    "\n\n[分析類型: 優化推薦] 用戶想調整某個變數,但未能自動解析目標欄位。"
                    "\n請從用戶的問題中推斷目標變數,並使用 get_top_correlations + analyze_feature_importance 分析。"
                )
            elif analysis_type == "comparison":
                state.current_knowledge += (
                    "\n\n[分析類型: 區段比較] 用戶想比較不同數據區段。"
                    "\n使用 compare_data_segments 和 distribution_shift_analysis 進行比較分析。"
                )
            elif analysis_type == "visualization":
                state.current_knowledge += (
                    "\n\n[分析類型: 視覺化] 用戶只想看圖表。"
                    "\n優先使用 draw_trend / get_time_series_data,快速產出圖表後結案。"
                )

            yield ProgressEvent(
                msg=f"🚀 啟動 V2 批量分析引擎 (模式: {mode_label}, 最多 {max_turns} 個 Turn)..."
            )

        while True:
            # [STOP CHECK]
            if self.analysis_service and self.analysis_service.is_generation_stopped(
                session_id
            ):
                yield ProgressEvent(msg="🛑 收到停止信號。")
                break

            if state.step_count >= max_turns:
                yield MonologueEvent(
                    monologue="【達到最大步數】強制結案。",
                    tool_name="force_finish",
                    tool_params={},
                    query=state.original_query,
                    file_id=state.file_id,
                    session_id=session_id,
                    history="",
                )
                break

            self.logger.info(f"--- Turn {state.step_count} ---")

            # --- [Turn 1 Conditional Scan] ---
            # Route to different initial scans based on intent
            if state.step_count == 1 and not has_specific_targets:
                yield ProgressEvent(msg="[Turn 1] 執行標準初始掃描...")

                experiments = [
                    ExperimentContext(
                        id="scan_01",
                        objective="全域 Z-Score 掃描",
                        technique="detect_outliers",
                        target_columns=["all"],
                        focus_range="Global",
                    ),
                    ExperimentContext(
                        id="scan_02",
                        objective="多變量異常偵測 (Hotelling T2)",
                        technique="hotelling_t2_analysis",
                        target_columns=["all"],
                        focus_range="Global",
                    ),
                    ExperimentContext(
                        id="scan_03",
                        objective="全域關聯性掃描",
                        technique="get_top_correlations",
                        target_columns=["all"],
                        focus_range="Global",
                    ),
                ]

                exp_list_str = "\n".join(
                    [
                        f"- {exp.technique} on {exp.target_columns}"
                        for exp in experiments
                    ]
                )
                yield MonologueEvent(
                    monologue=f"【初始掃描】無特定目標,執行標準三合一掃描:\n{exp_list_str}",
                    tool_name="InitialScan",
                    tool_params={"count": len(experiments)},
                    query=state.original_query,
                    file_id=state.file_id,
                    session_id=session_id,
                    history="",
                )
            elif state.step_count == 1 and has_specific_targets and is_optimization:
                # --- [OPTIMIZATION Turn 1] Target-focused profiling ---
                target_name = suspect_pool[0]
                yield ProgressEvent(
                    msg=f"[Turn 1] 目標導向分析: 分析 '{target_name}' 的影響因子..."
                )

                experiments = []

                # Multi-target: add multi_objective_analysis first
                if is_multi_target:
                    targets_csv = ",".join(suspect_pool)
                    experiments.append(
                        ExperimentContext(
                            id="opt_00",
                            objective=f"分析多目標之間的 Synergy/Trade-off 關係",
                            technique="multi_objective_analysis",
                            target_columns=suspect_pool,
                            focus_range="Global",
                        )
                    )

                experiments.extend(
                    [
                        ExperimentContext(
                            id="opt_01",
                            objective=f"找出與 {target_name} 最相關的參數",
                            technique="get_top_correlations",
                            target_columns=[target_name],
                            focus_range="Global",
                        ),
                        ExperimentContext(
                            id="opt_02",
                            objective=f"找出驅動 {target_name} 的關鍵因子",
                            technique="analyze_feature_importance",
                            target_columns=[target_name],
                            focus_range="Global",
                        ),
                        ExperimentContext(
                            id="opt_03",
                            objective=f"分割好壞批次,比較 {target_name} 高低族群的參數差異",
                            technique="performance_segmentation",
                            target_columns=[target_name],
                            focus_range="Global",
                        ),
                        ExperimentContext(
                            id="opt_04",
                            objective=f"分析 {target_name} 的分佈特性",
                            technique="analyze_distribution",
                            target_columns=[target_name],
                            focus_range="Global",
                        ),
                    ]
                )

                exp_list_str = "\n".join(
                    [
                        f"- {exp.technique} on {exp.target_columns}"
                        for exp in experiments
                    ]
                )
                yield MonologueEvent(
                    monologue=f"【優化分析】目標: {target_name},執行影響因子掃描:\n{exp_list_str}",
                    tool_name="OptimizationScan",
                    tool_params={"target": target_name, "count": len(experiments)},
                    query=state.original_query,
                    file_id=state.file_id,
                    session_id=session_id,
                    history="",
                )
            else:
                # --- Phase 1: Strategist (The Commander) ---
                # [SPEED] Quick mode Turn 2+: skip Strategist, use Synthesizer's suggestion
                last_suggestion = ""
                if state.history:
                    last_step = state.history[-1]
                    if hasattr(last_step, "evidence") and isinstance(
                        last_step.evidence, dict
                    ):
                        report = last_step.evidence.get("analysis_report")
                        if report and hasattr(report, "next_step_suggestion"):
                            last_suggestion = report.next_step_suggestion

                if not is_deep and state.step_count >= 2 and last_suggestion:
                    # Quick mode fast path: skip Strategist
                    yield ProgressEvent(
                        msg=f"⚡ [Turn {state.step_count}] 快速模式: 直接規劃實驗..."
                    )
                    directive = last_suggestion
                    strat_decision = "CONTINUE"
                else:
                    # Deep mode or Turn 1: full Strategist
                    yield ProgressEvent(
                        msg=f"🧠 [Turn {state.step_count}] 策略思考中..."
                    )

                    strat_in = RoleInput(state_machine=state)
                    strat_out = await self.roles["strategist"].execute(strat_in)
                    directive = strat_out.directive
                    strat_decision = strat_out.decision

                    yield MonologueEvent(
                        monologue=f"【策略指揮】\n{strat_out.reasoning}\n\n決定: {strat_out.decision}\n指令: {strat_out.directive}",
                        tool_name="Strategist",
                        tool_params={
                            "decision": strat_out.decision,
                            "directive": strat_out.directive,
                        },
                        query=state.original_query,
                        file_id=state.file_id,
                        session_id=session_id,
                        history="",
                    )

                if strat_decision == "FINISH":
                    break

                # --- Phase 2: Planner (The Architect) ---
                yield ProgressEvent(msg="📐 正在規劃實驗清單...")

                plan_in = RoleInput(state_machine=state, directive=directive)
                plan_out = await self.roles["planner"].execute(plan_in)

                experiments = plan_out.experiments

                # [Fix 5] Planner returned FINISH (late-stage fallback convergence)
                if plan_out.decision == "FINISH" and not experiments:
                    yield ProgressEvent(msg="Planner 判断已无需继续分析，准备结案。")
                    break

                if not experiments:
                    # [Fix 6] Track consecutive empty plans
                    empty_plan_count = getattr(self, "_empty_plan_count", 0) + 1
                    self._empty_plan_count = empty_plan_count
                    if empty_plan_count >= 2:
                        yield ProgressEvent(msg="连续 2 次无法规划实验，结束分析。")
                        break
                    yield MonologueEvent(
                        monologue="【規劃受阻】沒有可行的實驗方案，將回報給策略師。",
                        tool_name="Planner",
                        tool_params={},
                        query=state.original_query,
                        file_id=state.file_id,
                        session_id=session_id,
                        history="",
                    )
                    state.history.append(
                        StepResult(
                            role="Planner",
                            conclusion="Failed to generate experiments. Data might be insufficient.",
                            timestamp=0.0,
                        )
                    )
                    state.step_count += 1
                    continue
                else:
                    # Reset empty plan counter on successful planning
                    self._empty_plan_count = 0

                exp_list_str = "\n".join(
                    [
                        f"- {exp.technique} on {exp.target_columns}"
                        for exp in experiments
                    ]
                )
                yield MonologueEvent(
                    monologue=f"【實驗規劃】\n{plan_out.reasoning}\n\n計畫執行:\n{exp_list_str}",
                    tool_name="Planner",
                    tool_params={"count": len(experiments)},
                    query=state.original_query,
                    file_id=state.file_id,
                    session_id=session_id,
                    history="",
                )

                # [NEW] Surface missing_capabilities to frontend
                missing_caps_raw = (plan_out.structured_log or {}).get(
                    "missing_capabilities", ""
                )
                if missing_caps_raw:
                    caps_lines = [
                        c.strip() for c in missing_caps_raw.split("\n") if c.strip()
                    ]
                    caps_str = "\n".join([f"  - {cap}" for cap in caps_lines])
                    yield ProgressEvent(
                        msg=f"[系統建議] Planner 認為需要但尚未擁有的能力:\n{caps_str}"
                    )

            # --- Phase 3: Executor (The Builder) ---
            # Parallel Execution
            yield ProgressEvent(
                msg=f"⚙️ 批量執行 {len(experiments)} 個實驗中 (Async)..."
            )

            exec_in = RoleInput(state_machine=state, experiments=experiments)
            exec_out = await self.roles["executor"].execute(exec_in)
            evidences = exec_out.evidences

            # Show progress for each evidence (with brief key metrics)
            for ev in evidences:
                status_icon = "✅" if ev.status == "SUCCESS" else "❌"
                # Extract brief summary from result
                brief = ev.observation[:80]
                if ev.status == "SUCCESS" and isinstance(ev.result, dict):
                    # Try to extract key Z-Score or anomaly info
                    top_params = ev.result.get("top_abnormal_parameters", {})
                    if top_params and isinstance(top_params, dict):
                        first_key = list(top_params.keys())[0]
                        first_z = (
                            top_params[first_key].get("stats", {}).get("max_z", 0)
                            if isinstance(top_params[first_key], dict)
                            else 0
                        )
                        brief = f"Top: {first_key} (Z={first_z:.1f})"
                    elif "anomaly_indices" in ev.result:
                        indices = ev.result["anomaly_indices"][:3]
                        brief = f"異常樣本: Row {indices}"
                    elif "top_correlations" in ev.result:
                        corrs = ev.result["top_correlations"]
                        if corrs and isinstance(corrs, list) and len(corrs) > 0:
                            top_c = corrs[0]
                            brief = f"最強關聯: {top_c.get('parameter', '?')} (r={top_c.get('correlation', 0):.2f})"
                yield ProgressEvent(msg=f"{status_icon} [{ev.tool_name}] {brief}")

            # --- Phase 4: Synthesizer (The Reviewer) ---
            # Review & Update Dashboard
            yield ProgressEvent(msg=f"⚖️ 綜合分析師正在驗收 {len(evidences)} 項證據...")

            syn_in = RoleInput(
                state_machine=state, experiments=experiments, evidences=evidences
            )
            syn_out = await self.roles["synthesizer"].execute(syn_in)
            report = syn_out.analysis_report

            # Broadcast Synthesis
            findings_str = "\n".join([f"- {f}" for f in report.key_findings])
            yield MonologueEvent(
                monologue=f"【綜合驗收】\n邏輯: {report.synthesis_logic}\n\n關鍵發現:\n{findings_str}\n\n建議: {report.next_step_suggestion}",
                tool_name="Synthesizer",
                tool_params={},
                query=state.original_query,
                file_id=state.file_id,
                session_id=session_id,
                history="",
            )

            # Summary progress line for user visibility
            n_findings = len(report.key_findings)
            top_finding = report.key_findings[0][:60] if report.key_findings else "無"
            decision_label = (
                "繼續深入" if syn_out.decision == "CONTINUE" else "準備結案"
            )
            yield ProgressEvent(
                msg=f"📊 Turn {state.step_count} 小結: {n_findings} 項發現 | 最關鍵: {top_finding} | {decision_label}"
            )

            # [NEW] Surface Synthesizer's analysis gaps (post-execution perspective)
            analysis_gaps = (syn_out.structured_log or {}).get("analysis_gaps", [])
            if analysis_gaps and isinstance(analysis_gaps, list):
                gaps_str = "\n".join([f"  - {gap}" for gap in analysis_gaps])
                yield ProgressEvent(
                    msg=f"[分析缺口] Synthesizer 識別的工具缺口:\n{gaps_str}"
                )

            # --- Update State (Dashboard) ---
            new_history = state.history + [
                StepResult(
                    role="Synthesizer",
                    conclusion=f"Turn {state.step_count} Findings: {findings_str}",
                    timestamp=0.0,
                    evidence={
                        "raw_evidences": evidences,
                        "analysis_report": report,
                        "structured_log": syn_out.structured_log,
                    },
                )
            ]

            # Track used tools + parameters for diversity (tool::param pairs)
            turn_tools = []
            turn_failed = []
            for ev in evidences:
                if ev.tool_name:
                    # Extract the target parameter from experiment context
                    exp = next(
                        (e for e in experiments if e.id == ev.experiment_id), None
                    )
                    target = (
                        exp.target_columns[0] if exp and exp.target_columns else "all"
                    )
                    key = f"{ev.tool_name}::{target}"
                    turn_tools.append(key)
                    # [Fix 3] Track failures with error detail for LLM feedback
                    if ev.status == "FAIL" or (
                        isinstance(ev.result, dict) and "error" in ev.result
                    ):
                        # Store error reason for Planner context
                        error_msg = ""
                        if isinstance(ev.result, str):
                            error_msg = ev.result[:100]
                        elif isinstance(ev.result, dict):
                            error_msg = str(ev.result.get("error", ""))[:100]
                        failed_key = f"{key}|{error_msg}" if error_msg else key
                        turn_failed.append(failed_key)
            new_tools_history = state.used_tools_history + turn_tools
            new_failed = list(set(state.failed_experiments + turn_failed))

            # Combine direct updates from synthesizer + internal updates
            final_updates = syn_out.updates.copy() if syn_out.updates else {}
            final_updates.update(
                {
                    "current_knowledge": self._update_dashboard(
                        state.current_knowledge, report
                    ),
                    "history": new_history,
                    "step_count": state.step_count + 1,
                    "used_tools_history": new_tools_history,
                    "failed_experiments": new_failed,
                }
            )

            # Trigger Immutable Update with Snapshot
            state = state.update(role_name="Orchestrator_V2", **final_updates)

            self.logger.info(
                f"State Version: {state.version}, Tools used: {Counter(new_tools_history).most_common(3)}"
            )

            # [Fix 1] Respect Synthesizer convergence decision
            if syn_out.decision == "FINISH":
                self.logger.info(
                    "Convergence triggered FINISH from Synthesizer — stopping loop"
                )
                break

        # End of Loop -> Final Result
        # [FIX] Build structured step history for humanizer
        all_steps = []
        for i, step in enumerate(state.history):
            step_data = {
                "step": i + 1,
                "tool": getattr(step, "role", "Unknown"),
                "monologue": getattr(step, "conclusion", ""),
                "result": {},
            }
            # Extract evidence data from step results
            if hasattr(step, "evidence") and step.evidence:
                ev_data = step.evidence
                # Handle new dict format: {raw_evidences: [...], analysis_report: ...}
                if isinstance(ev_data, dict):
                    raw_evidences = ev_data.get("raw_evidences", [])
                    analysis_rpt = ev_data.get("analysis_report", None)

                    # Extract raw evidence details
                    if raw_evidences:
                        for ev in raw_evidences:
                            tool_result = {}
                            if hasattr(ev, "result") and isinstance(ev.result, dict):
                                tool_result = ev.result
                            step_data["result"][ev.tool_name] = {
                                "status": ev.status,
                                "observation": ev.observation,
                                "data": tool_result,
                            }

                    # Extract analysis report findings
                    if analysis_rpt:
                        step_data["key_findings"] = getattr(
                            analysis_rpt, "key_findings", []
                        )
                        step_data["rejected_hypotheses"] = getattr(
                            analysis_rpt, "rejected_hypotheses", []
                        )
                        step_data["next_step_suggestion"] = getattr(
                            analysis_rpt, "next_step_suggestion", ""
                        )

                    # Extract causal_chain and isolated_observations from structured_log
                    s_log = ev_data.get("structured_log", {})
                    if isinstance(s_log, dict):
                        step_data["causal_chain"] = s_log.get("causal_chain", [])
                        step_data["isolated_observations"] = s_log.get(
                            "isolated_observations", []
                        )
                else:
                    # Legacy: evidence is a list of Evidence objects
                    try:
                        for ev in ev_data:
                            tool_result = {}
                            if hasattr(ev, "result") and isinstance(ev.result, dict):
                                tool_result = ev.result
                            step_data["result"][getattr(ev, "tool_name", "unknown")] = {
                                "status": getattr(ev, "status", "UNKNOWN"),
                                "observation": getattr(ev, "observation", ""),
                                "data": tool_result,
                            }
                    except (TypeError, AttributeError):
                        step_data["result"]["raw"] = str(ev_data)[:500]
            all_steps.append(step_data)

        # [FIX] Extract chart objects from all evidence results
        all_charts = []
        for step in state.history:
            if not hasattr(step, "evidence") or not step.evidence:
                continue
            ev_data = step.evidence
            raw_evidences = []
            if isinstance(ev_data, dict):
                raw_evidences = ev_data.get("raw_evidences", [])
            elif isinstance(ev_data, list):
                raw_evidences = ev_data
            for ev in raw_evidences:
                if hasattr(ev, "result") and isinstance(ev.result, dict):
                    chart_obj = ev.result.get("chart")
                    if isinstance(chart_obj, dict) and chart_obj.get("type") == "chart":
                        all_charts.append(chart_obj)

        yield {
            "response": f"V2 Analysis Completed (Steps: {state.step_count - 1}).",
            "final_decision": state.current_knowledge,
            "all_steps_results": all_steps,
            "chart": all_charts,
            "state_version": state.version,
        }

        # [RESUME] Cache final state for potential continuation
        self._last_states[session_id] = {
            "state": state,
            "summary_data": summary_data,
            "is_deep": is_deep,
            "max_turns": max_turns,
        }

    # --- Follow-up Mode ---

    def _is_followup(self, query: str) -> bool:
        """判断是否为追问 (而非全新查询)"""
        followup_patterns = [
            "那",
            "然後",
            "接下來",
            "續",
            "剛才",
            "上面提到",
            "這個參數",
            "為什麼",
            "为什么",
            "具體",
            "更詳細",
            "展開",
            "可以再",
            "幫我看",
            "進一步",
            "深入分析",
            "什麼時候",
            "多久",
            "頻率",
            # --- 新增追問詞 ---
            "可以用",
            "簡單",
            "說明",
            "解釋",
            "列出",
            "總結",
            "怎麼做",
            "補充",
            "舉例",
        ]
        return any(p in query for p in followup_patterns)

    def _is_chat_only(self, query: str) -> bool:
        """
        [Safety Net] 當 LLM 意圖分類誤判時的備用檢查。
        只保留意圖**絕對明確**的對話詞組，避免誤攔分析請求。
        注意: 主要的意圖分類由 agent.py 的 LLM classify_prompt 負責。
        """
        chat_only_patterns = [
            "簡單說明",
            "簡單解釋",
            "白話文",
            "用比較簡單",
            "總結一下",
            "總結重點",
            "列出重點",
            "幫我整理",
            "換個方式",
            "換句話說",
            "能不能簡化",
            "精簡一點",
            "一句話",
            "懶人包",
        ]
        # 提取消息最後 200 字做判斷
        tail = query[-200:] if len(query) > 200 else query
        return any(p in tail for p in chat_only_patterns)

    async def run_chat_only(self, start_event: StartEvent) -> AsyncGenerator[Any, None]:
        """
        Pure Chat Mode: 不跑任何工具，直接用 LLM 回答對話性質的請求。
        例如「簡單說明」「總結重點」「用白話文解釋」
        """
        self.logger.info(f"[CHAT_ONLY] Handling as pure chat (no tools)")
        yield ProgressEvent(msg="正在整理回覆...")

        # 組合 prompt: 歷史對話 + 用戶當前請求
        history_section = ""
        if start_event.history:
            history_section = f"\n\n以下是最近的對話歷史:\n{start_event.history}"

        chat_prompt = f"""你是一個友善的工業數據分析助手。
用戶正在對之前的分析結果提出對話性的請求（例如簡化說明、總結重點等）。
請根據對話歷史直接回答用戶，不需要執行任何工具或分析。
用繁體中文回答，語氣要自然且易懂。{history_section}

用戶的訊息:
{start_event.query}

請直接回答:"""

        try:
            response = await self.llm.ainvoke(chat_prompt)
            resp_text = (
                response.content if hasattr(response, "content") else str(response)
            )

            yield TextChunkEvent(content=resp_text)
            yield {
                "response": resp_text,
                "is_chat_only": True,
            }
        except Exception as e:
            self.logger.error(f"[CHAT_ONLY] LLM error: {e}")
            yield {
                "response": f"抱歉，回答時發生錯誤: {str(e)}",
                "is_chat_only": True,
            }

    async def run_followup(
        self, start_event: StartEvent, summary_data: Dict
    ) -> AsyncGenerator[Any, None]:
        """
        Follow-up Mode: 继承上次分析状态，只跑 1 Turn 针对性分析。
        比 resume 更轻量 -- 不扩展 budget，只回答一个追问。
        """
        session_id = start_event.session_id
        cached = self._last_states.get(session_id)

        if not cached:
            yield ProgressEvent(msg="没有找到上一次分析的状态，将执行完整分析。")
            async for event in self.run_analysis(start_event, summary_data):
                yield event
            return

        state = cached["state"]
        query = start_event.query or ""

        yield ProgressEvent(
            msg=f"Follow-up: 继承上次分析状态 (Turn {state.step_count - 1})，针对性回答追问..."
        )

        # Inject follow-up context: rolling_summary + new query
        followup_context = (
            f"## 上次分析摘要\n{state.rolling_summary or state.current_knowledge}\n\n"
            f"## 用户追问\n{query}\n\n"
            f"请针对用户的追问，规划 1-3 个实验来回答。"
        )

        # Update state for 1-Turn followup
        state = state.update(
            role_name="Followup",
            max_steps=state.step_count + 1,
            original_query=query,
            current_knowledge=state.current_knowledge
            + f"\n[Follow-up] 用户追问: {query}",
        )

        # --- Single Turn: Planner -> Executor -> Synthesizer ---
        yield ProgressEvent(msg="正在规划针对性实验...")

        plan_in = RoleInput(
            state_machine=state,
            directive=followup_context,
        )
        plan_out = await self.roles["planner"].execute(plan_in)
        experiments = plan_out.experiments or []

        if not experiments:
            yield {
                "response": "无法针对您的追问规划实验。请尝试更具体地描述您想了解的内容。",
                "structured_report": None,
                "chart": [],
            }
            return

        yield ProgressEvent(msg=f"执行 {len(experiments)} 个针对性实验...")

        exec_in = RoleInput(state_machine=state, experiments=experiments)
        exec_out = await self.roles["executor"].execute(exec_in)
        evidences = exec_out.evidences or []

        for ev in evidences:
            status_icon = "OK" if ev.status == "SUCCESS" else "FAIL"
            yield ProgressEvent(
                msg=f"[{status_icon}] [{ev.tool_name}] {ev.observation[:80]}"
            )

        # Synthesize
        yield ProgressEvent(msg="正在综合回答...")
        syn_in = RoleInput(
            state_machine=state,
            experiments=experiments,
            evidences=evidences,
        )
        syn_out = await self.roles["synthesizer"].execute(syn_in)
        report = syn_out.analysis_report

        # Build concise follow-up response
        findings_str = (
            "; ".join(report.key_findings) if report.key_findings else "未发现新信息"
        )

        yield {
            "response": findings_str,
            "final_decision": report.synthesis_logic,
            "structured_report": {
                "executive_summary": findings_str,
                "findings": [
                    {"title": f, "severity": "MEDIUM", "detail": f}
                    for f in (report.key_findings or [])
                ],
                "action_items": [],
                "is_followup": True,
            },
            "chart": [],
        }

        # Update cached state for chaining follow-ups
        new_history = state.history + [
            StepResult(
                role="Followup",
                conclusion=f"Follow-up: {findings_str}",
                timestamp=0.0,
                evidence={
                    "raw_evidences": evidences,
                    "analysis_report": report,
                },
            )
        ]
        state = state.update(
            role_name="Followup",
            history=new_history,
            step_count=state.step_count + 1,
        )
        self._last_states[session_id] = {
            "state": state,
            "summary_data": cached["summary_data"],
            "is_deep": cached["is_deep"],
            "max_turns": cached["max_turns"],
        }

    def _update_dashboard(self, current: str, report: AnalysisReport) -> str:
        """
        Rolling update of the dashboard text.
        """
        new_entry = f"\n[Update]: {report.synthesis_logic}\nFindings: {report.key_findings}\nNext: {report.next_step_suggestion}"
        return current + new_entry
