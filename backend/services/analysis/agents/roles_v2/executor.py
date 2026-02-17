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
                tool_name, params = self._map_to_tool_v2(exp, inferred_params)

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

                return Evidence(
                    experiment_id=exp.id,
                    tool_name=tool_name,
                    tool_params=params,
                    result=result,
                    observation="Executed successfully.",
                    status="SUCCESS",
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
        self, exp: ExperimentContext, inferred_params: Dict
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
        }

        # 安全取值
        first_target = exp.target_columns[0] if exp.target_columns else None

        # 1. 遍歷 required_params，自動映射
        required = spec.get("required_params", [])
        optional = spec.get("optional_params", [])
        all_params = required + optional

        for param_name in required:
            if param_name in SINGLE_TARGET_PARAMS and first_target:
                params[param_name] = first_target
            elif param_name in LIST_TARGET_PARAMS and exp.target_columns:
                params[param_name] = exp.target_columns
            # 其他 required_params (如 focus_range, baseline_range) 在下方處理

        # 2. 映射 optional 中的 target-like 參數 (如果 Planner 有提供)
        for param_name in optional:
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
            elif "range_a" in all_params:
                params["range_a"] = focus

        if baseline:
            if "baseline_range" in all_params:
                params["baseline_range"] = baseline
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
