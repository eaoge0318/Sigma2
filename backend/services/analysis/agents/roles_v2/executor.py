import asyncio
from typing import Dict, List, Any, Callable
from backend.services.analysis.agents.roles.base_role import BaseRole
from backend.services.analysis.analysis_types import (
    RoleInput,
    RoleOutput,
    Evidence,
    ExperimentContext,
)


class BatchExecutor(BaseRole):
    """
    [V2 Role] 批量執行官 (Batch Executor)

    Responsibilities:
    1.  **Map**: Convert `ExperimentContext` (Intent) -> `Tool Call` (Function + Params).
    2.  **Execute**: Run tools in parallel (Async).
    3.  **Fault Tolerance**: Catch errors and return `FAIL` status instead of crashing.
    4.  **Rate Limit**: Control concurrency.
    """

    def __init__(self, llm: Any, tool_executor: Any):
        super().__init__(llm)
        self.tool_executor = tool_executor
        self.semaphore = asyncio.Semaphore(
            2
        )  # Max Concurrency = 2 (avoid starving other API endpoints)

    async def execute(self, input_data: RoleInput) -> RoleOutput:
        experiments = input_data.experiments
        state = input_data.state_machine
        session_id = state.session_id

        if not experiments:
            return RoleOutput(decision="Turn_End", reasoning="No experiments to run.")

        # 0. Combo Shield: 移除被 combo 工具覆蓋的重複原子工具
        from backend.services.analysis.tools.registry import shield_covered_experiments

        experiments = shield_covered_experiments(experiments)

        if not experiments:
            return RoleOutput(
                decision="Turn_End",
                reasoning="All experiments shielded by combo tools.",
            )

        # 1. Map & Execute in Parallel
        tasks = [self._run_experiment(exp, state) for exp in experiments]
        evidences = await asyncio.gather(*tasks)

        # 2. Return Evidences
        return RoleOutput(
            decision="CONTINUE",
            evidences=evidences,
            reasoning=f"Executed {len(evidences)} experiments.",
        )

    async def _run_experiment(self, exp: ExperimentContext, state: Any) -> Evidence:
        async with self.semaphore:
            try:
                # --- Step A: Parameter Inference (AI Augmented) ---
                # Check if we need to infer parameters (e.g., missing ranges)
                inferred_params = await self._infer_parameters(exp, state)

                # --- Step B: Registry Mapping (Intent -> Tool) ---
                tool_name, params = self._map_to_tool_v2(exp, inferred_params, state)

                # Handle case where tool is skipped (e.g., blacklisted)
                if tool_name is None:
                    return Evidence(
                        experiment_id=exp.id,
                        tool_name=exp.technique,
                        tool_params={},
                        result="Tool skipped due to redirection or blacklisting.",
                        observation="Skipped",
                        status="SKIPPED",
                    )

                # [Fix] Inject file_id from state if not present
                if "file_id" not in params:
                    params["file_id"] = state.file_id

                # --- Step C: Execution ---
                # Use the system's tool_executor
                result = await self.tool_executor.execute_tool(
                    tool_name, params, state.session_id
                )

                # --- Step D: Generate chart for multimodal LLM ---
                chart_b64 = None
                if isinstance(result, dict):
                    try:
                        from backend.services.analysis.agents.evidence_chart_generator import (
                            generate_evidence_chart,
                        )

                        chart_b64 = generate_evidence_chart(tool_name, result)
                        if chart_b64:
                            print(
                                f"[Executor] Chart generated for {tool_name}: {len(chart_b64)} bytes"
                            )
                        else:
                            # Debug: 列出 result keys 找出為何圖表不產生
                            result_keys = list(result.keys())[:10]
                            print(
                                f"[Executor] NO chart for {tool_name}, result keys: {result_keys}"
                            )
                    except Exception as e:
                        print(f"[Executor] Chart generation ERROR for {tool_name}: {e}")

                return Evidence(
                    experiment_id=exp.id,
                    tool_name=tool_name,
                    tool_params=params,
                    result=result,
                    observation="Executed successfully.",
                    status="SUCCESS",
                    chart_base64=chart_b64,
                )

            except Exception as e:
                return Evidence(
                    experiment_id=exp.id,
                    tool_name=exp.technique,
                    tool_params={},
                    result=str(e),
                    observation=f"Error: {str(e)}",
                    status="FAIL",
                )

    async def _infer_parameters(
        self, exp: ExperimentContext, state: Any
    ) -> Dict[str, Any]:
        """
        使用 LLM 推理缺失的參數 (例如: focus_range, baseline_range)
        """
        from backend.services.analysis.tools.registry import get_tool_spec

        spec = get_tool_spec(exp.technique)
        if not spec:
            return {}

        # 檢查是否有缺失的必要參數
        # 這裡主要針對 Range 進行推理，其他參數通常由 Planner 提供
        need_inference = False
        if "focus_range" in spec.get("optional_params", []) and not exp.focus_range:
            need_inference = True
        if (
            "baseline_range" in spec.get("optional_params", [])
            and not exp.baseline_range
        ):
            need_inference = True

        if not need_inference:
            return {}

        # 使用 LLM 推理
        prompt = f"""根據以下資訊推理實驗參數：

實驗目標：{exp.objective}
使用工具：{exp.technique}
已知參數：
- Target: {exp.target_columns}
- Focus Range: {exp.focus_range or "未指定 (需推理)"}
- Baseline Range: {exp.baseline_range or "未指定 (需推理)"}

資料摘要：{state.data_summary}
已知異常：{[site.range for site in state.discovered_sites]}

請推理缺失的參數 (focus_range, baseline_range)，回傳 JSON：
{{
    "focus_range": "Step 100-150", 
    "baseline_range": "Step 0-50",
    "reasoning": "推理理由"
}}
如果無法推理，請回傳空字串。"""

        try:
            response = await self._call_llm(
                sys_prompt="You are an expert parameter engineer.", user_prompt=prompt
            )
            inferred = self._parse_json(response)
            print(f"[Executor] Inferred parameters for {exp.id}: {inferred}")
            return inferred
        except Exception as e:
            print(f"[Executor] Parameter inference failed: {e}")
            return {}

    def _map_to_tool_v2(
        self, exp: ExperimentContext, inferred_params: Dict, state: Any = None
    ) -> tuple[str, Dict]:
        """
        Maps abstract 'Technique' to concrete 'Tool Name' and 'Params' using Registry.

        [通用映射邏輯]
        不再硬編碼參數名，而是自動讀取 Registry 的 required_params，
        將 Planner 提供的 target_columns 映射到工具需要的參數名上。
        """
        from backend.services.analysis.tools.registry import get_tool_spec

        technique = exp.technique
        spec = get_tool_spec(technique)

        if not spec:
            # Fallback for unknown tools
            return technique, {"targets": exp.target_columns}

        tool_name = spec["executor_function"]
        params = {}

        # [Robustness] Hard Redirect for Hallucinated Tools
        TOOL_REDIRECTS = {
            "basic_stats": "analyze_distribution",
            "correlation_analysis": "get_top_correlations",
            "search_parameters_by_concept": None,  # Skip this tool
            "get_time_series_data": "draw_trend",
            "get_correlation_matrix": "get_top_correlations",
        }

        if technique in TOOL_REDIRECTS:
            redirect_to = TOOL_REDIRECTS[technique]
            if redirect_to is None:
                # Skip this experiment
                print(f"[Executor] Skipping blacklisted tool: {technique}")
                return None, {}

            print(f"[Executor] Redirecting {technique} -> {redirect_to}")
            technique = redirect_to
            # Re-fetch spec for redirected tool
            spec = get_tool_spec(technique)
            if not spec:
                return technique, {"targets": exp.target_columns}
            tool_name = spec["executor_function"]

        # === 通用參數映射 (Generic Parameter Mapping) ===

        # 定義「目標型」參數名 (接收單一目標: target_columns[0])
        SINGLE_TARGET_PARAMS = {
            "target",
            "parameter",
            "target_parameter",
            "process_variable",
        }

        # 定義「列表型」參數名 (接收完整列表: target_columns)
        LIST_TARGET_PARAMS = {
            "target_columns",
            "targets",
            "features",
            "parameters",
        }

        # [FIX] 定義「命名參數」映射 (需要從 target_columns 拆分到具名參數)
        # 格式: tool_name -> [param_name_for_col_0, param_name_for_col_1, ...]
        NAMED_PARAMS_MAP = {
            "interaction_scatter": ["x_param", "y_param", "color_param"],
            "interaction_effect_test": ["param_a", "param_b"],
            "stratified_interaction": ["param_a", "param_b"],
        }

        # 安全取值
        first_target = exp.target_columns[0] if exp.target_columns else None

        # [FIX] Auto-correct target='all' for tools that don't support global mode
        # When Planner outputs target_columns=['all'] but the tool needs a specific column,
        # auto-extract the original target from state's current_knowledge
        if first_target == "all" and not spec.get("supports_global", False):
            import re as _re

            resolved_target = None

            # Strategy 1: Extract from current_knowledge [目標變量] marker
            if (
                state
                and hasattr(state, "current_knowledge")
                and state.current_knowledge
            ):
                _m = _re.search(r"\[目標變量\]\s*(\S+)", state.current_knowledge)
                if _m:
                    resolved_target = _m.group(1)

            # Strategy 2: Extract from current_knowledge target= mentions
            if (
                not resolved_target
                and state
                and hasattr(state, "current_knowledge")
                and state.current_knowledge
            ):
                _m = _re.search(r"target[=＝]\s*(\S+)", state.current_knowledge)
                if _m and _m.group(1) != "all":
                    resolved_target = _m.group(1)

            # Strategy 3: Check history for the most recent successful target
            if not resolved_target and state and hasattr(state, "history"):
                for step in reversed(state.history or []):
                    ev_data = getattr(step, "evidence", None)
                    if not isinstance(ev_data, dict):
                        continue
                    for ev in ev_data.get("raw_evidences") or []:
                        res = (
                            getattr(ev, "result", None)
                            if hasattr(ev, "result")
                            else None
                        )
                        if isinstance(res, dict) and res.get("target"):
                            candidate = res["target"]
                            if candidate != "all":
                                resolved_target = candidate
                                break
                    if resolved_target:
                        break

            if resolved_target:
                print(
                    f"[Executor] Auto-corrected target='all' → '{resolved_target}' "
                    f"for {technique} (supports_global=False)"
                )
                first_target = resolved_target
                # Also update exp.target_columns[0] so downstream mappings use the corrected value
                if exp.target_columns:
                    exp.target_columns[0] = resolved_target
            else:
                print(
                    f"[Executor] WARNING: target='all' for {technique} but could not "
                    f"auto-resolve original target. Tool may fail."
                )

        # [FIX] 0. 優先處理命名參數映射 (在通用映射之前)
        if technique in NAMED_PARAMS_MAP and exp.target_columns:
            named_params = NAMED_PARAMS_MAP[technique]
            for i, param_name in enumerate(named_params):
                if i < len(exp.target_columns) and exp.target_columns[i] != "all":
                    params[param_name] = exp.target_columns[i]
            if len(exp.target_columns) < len(named_params):
                # 不足的參數會在最後的 missing check 中警告
                missing_named = [
                    p
                    for p in named_params[len(exp.target_columns) :]
                    if p not in params
                ]
                if missing_named:
                    print(
                        f"[Executor] Inferred {len(params)} of {len(named_params)} "
                        f"named params for {technique} from target_columns={exp.target_columns}"
                    )

        # [FIX] 0.5 Auto-fill missing named params from analysis state
        # When Planner only provides target (e.g., ["FORMULA-DCS_A15"]) but tool
        # needs param_a + param_b + target, extract param_a/param_b from history
        if technique in NAMED_PARAMS_MAP:
            needed_named = NAMED_PARAMS_MAP[technique]
            missing_named = [p for p in needed_named if p not in params]
            if missing_named:
                # Collect candidate params from state for auto-fill
                candidate_params = []
                state_ref = state

                # Strategy 1: Extract from discovered_sites
                if state_ref and hasattr(state_ref, "discovered_sites"):
                    for site in state_ref.discovered_sites or []:
                        param_name = getattr(site, "range", None)
                        if (
                            param_name
                            and param_name not in candidate_params
                            and not str(param_name)
                            .replace(" ", "")
                            .replace("-", "")
                            .isdigit()
                            and param_name not in params.values()
                            and param_name != first_target
                        ):
                            candidate_params.append(param_name)

                # Strategy 2: Extract from current_knowledge (key parameter names)
                if (
                    state_ref
                    and hasattr(state_ref, "current_knowledge")
                    and state_ref.current_knowledge
                ):
                    import re as _re

                    # Match parameter-like names (UPPERCASE with - or _)
                    found_params = _re.findall(
                        r"[A-Z][A-Z0-9_-]+(?:_[A-Z0-9]+)+", state_ref.current_knowledge
                    )
                    for fp in found_params:
                        schema_cols = (
                            set(state_ref.data_schema.keys())
                            if state_ref.data_schema
                            else set()
                        )
                        if (
                            fp in schema_cols
                            and fp not in candidate_params
                            and fp not in params.values()
                            and fp != first_target
                        ):
                            candidate_params.append(fp)

                # Strategy 3: Extract from history evidence results
                if state_ref and hasattr(state_ref, "history"):
                    for step in reversed(state_ref.history or []):
                        ev_data = getattr(step, "evidence", None)
                        if not isinstance(ev_data, dict):
                            continue
                        # From feature importance results
                        raw_evs = ev_data.get("raw_evidences", [])
                        if isinstance(raw_evs, list):
                            for ev in raw_evs:
                                res = (
                                    getattr(ev, "result", None)
                                    if hasattr(ev, "result")
                                    else (
                                        ev.get("result")
                                        if isinstance(ev, dict)
                                        else None
                                    )
                                )
                                if not isinstance(res, dict):
                                    continue
                                # From top correlations
                                for corr in res.get("top_correlations", []) or []:
                                    if isinstance(corr, dict):
                                        cp = corr.get("parameter", "")
                                        if (
                                            cp
                                            and cp not in candidate_params
                                            and cp not in params.values()
                                            and cp != first_target
                                        ):
                                            candidate_params.append(cp)
                                # From feature importance
                                for fi in res.get("importance_ranking", []) or []:
                                    if isinstance(fi, dict):
                                        fp = fi.get("feature", "") or fi.get(
                                            "parameter", ""
                                        )
                                        if (
                                            fp
                                            and fp not in candidate_params
                                            and fp not in params.values()
                                            and fp != first_target
                                        ):
                                            candidate_params.append(fp)

                # Fill missing named params from candidates
                for p_name in missing_named:
                    if candidate_params:
                        chosen = candidate_params.pop(0)
                        params[p_name] = chosen
                        print(
                            f"[Executor] Auto-filled {p_name}={chosen} for {technique} from analysis history"
                        )

                # If still missing & tool needs target separate from param_a/param_b,
                # resolve the actual response variable from state rather than using first_target
                # (first_target is already mapped to param_a for NAMED_PARAMS tools)
                if (
                    "target" in spec.get("required_params", [])
                    and "target" not in params
                ):
                    import re as _re

                    resolved_response_var = None

                    # Strategy A: Extract from current_knowledge [目標變量] marker
                    if (
                        state
                        and hasattr(state, "current_knowledge")
                        and state.current_knowledge
                    ):
                        _m = _re.search(
                            r"\[目標變量\][^\n]*?目標:\s*(\S+)",
                            state.current_knowledge,
                        )
                        if _m:
                            resolved_response_var = _m.group(1).rstrip(",。")

                    # Strategy B: Extract from current_knowledge
                    if (
                        not resolved_response_var
                        and state
                        and hasattr(state, "current_knowledge")
                        and state.current_knowledge
                    ):
                        _m = _re.search(r"target[=＝]\s*(\S+)", state.current_knowledge)
                        if _m and _m.group(1) not in (
                            "all",
                            params.get("param_a"),
                            params.get("param_b"),
                        ):
                            resolved_response_var = _m.group(1)

                    # Strategy C: Look in history for most recent target
                    if (
                        not resolved_response_var
                        and state
                        and hasattr(state, "history")
                    ):
                        for step in reversed(state.history or []):
                            ev_data = getattr(step, "evidence", None)
                            if not isinstance(ev_data, dict):
                                continue
                            for ev in ev_data.get("raw_evidences") or []:
                                res = (
                                    getattr(ev, "result", None)
                                    if hasattr(ev, "result")
                                    else None
                                )
                                if isinstance(res, dict) and res.get("target"):
                                    cand = res["target"]
                                    if cand not in (
                                        "all",
                                        params.get("param_a"),
                                        params.get("param_b"),
                                    ):
                                        resolved_response_var = cand
                                        break
                            if resolved_response_var:
                                break

                    if resolved_response_var:
                        params["target"] = resolved_response_var
                        print(
                            f"[Executor] NAMED_PARAMS target resolved: "
                            f"param_a={params.get('param_a')}, param_b={params.get('param_b')}, "
                            f"target={resolved_response_var}"
                        )
                    elif first_target and first_target not in (
                        params.get("param_a"),
                        params.get("param_b"),
                    ):
                        # Fallback: use first_target only if it's different from param_a/param_b
                        params["target"] = first_target
                    else:
                        print(
                            f"[Executor] WARNING: Cannot resolve response variable 'target' "
                            f"for {technique}. param_a={params.get('param_a')}, "
                            f"param_b={params.get('param_b')}"
                        )

        # 1. 遍歷 required_params，自動映射
        required = spec.get("required_params", [])
        optional = spec.get("optional_params", [])
        all_params = required + optional

        for param_name in required:
            if param_name in params:
                continue  # 已被命名參數映射處理
            if param_name in SINGLE_TARGET_PARAMS and first_target:
                params[param_name] = first_target
            elif param_name in LIST_TARGET_PARAMS and exp.target_columns:
                params[param_name] = exp.target_columns
            # 其他 required_params (如 focus_range, baseline_range) 在下方處理

        # 2. 映射 optional 中的 target-like 參數 (如果 Planner 有提供)
        for param_name in optional:
            if param_name in params:
                continue  # 已被命名參數映射處理
            if (
                param_name in SINGLE_TARGET_PARAMS
                and first_target
                and param_name not in params
            ):
                params[param_name] = first_target
            elif (
                param_name in LIST_TARGET_PARAMS
                and exp.target_columns
                and param_name not in params
            ):
                params[param_name] = exp.target_columns

        # 3. Map Ranges (Priority: Explicit > Inferred > Context)
        focus = exp.focus_range or inferred_params.get("focus_range")
        baseline = exp.baseline_range or inferred_params.get("baseline_range")

        if focus:
            if "focus_range" in all_params:
                params["focus_range"] = focus
            elif "target_segments" in all_params:
                params["target_segments"] = focus
            elif "range_a" in all_params:
                params["range_a"] = focus

        if baseline:
            if "baseline_range" in all_params:
                params["baseline_range"] = baseline
            elif "baseline_segments" in all_params:
                params["baseline_segments"] = baseline
            elif "range_b" in all_params:
                params["range_b"] = baseline

        # 4. Handle Global Target
        if spec.get("supports_global") and (
            not exp.target_columns or "all" in exp.target_columns
        ):
            global_val = spec.get("global_target", "all")
            # Assign to the first required parameter if possible
            if required:
                first_param = required[0]
                params[first_param] = global_val

        # 5. [Robustness] Special handling for compare_data_segments missing params
        if tool_name == "compare_data_segments":
            if "target_segments" not in params and "target" not in params:
                if exp.target_columns and any(
                    char.isdigit() for char in str(exp.target_columns[0])
                ):
                    params["target_segments"] = exp.target_columns[0]

        # 6. [Safety] 缺失必要參數的警告
        missing = [p for p in required if p not in params]
        if missing:
            print(
                f"[Executor] WARNING: {technique} missing required params: {missing} "
                f"(target_columns={exp.target_columns})"
            )

        return tool_name, params
