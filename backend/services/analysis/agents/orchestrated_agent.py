from typing import Any, Dict, AsyncGenerator
import asyncio
from backend.services.analysis.analysis_types import (
    AnalysisState,
    StartEvent,
    RoleInput,
    RoleOutput,
    StepResult,
    ProgressEvent,
    MonologueEvent,
    ToolCallEvent,
    ToolResultEvent,
    AnalysisEvent,
)

# Import Roles
from .roles.evaluator import EvaluatorRole
from .roles.specialist import SpecialistRole
from .roles.designer import DesignerRole
from .roles.integrator import IntegratorRole


class OrchestratedAnalysisAgent:
    """
    New Architecture Agent (Role-Based Orchestration)
    Replacing the monolithic `AnalysisAgent`
    """

    MAX_STEPS = 60  # Maximum analysis depth

    def __init__(self, llm: Any, tool_executor: Any, analysis_service: Any = None):
        self.llm = llm
        self.executor = tool_executor  # Dependency Injection
        self.analysis_service = analysis_service

        # Initialize Roles
        self.roles = {
            "evaluator": EvaluatorRole(llm),
            "specialist": SpecialistRole(llm),
            "designer": DesignerRole(llm),
            "integrator": IntegratorRole(llm),
        }

    def _print_step_log(self, step: int, role: str, log: Dict[str, str]):
        """
        [Visualize] Print structured role output to console
        """
        icon_map = {
            "Evaluator": "💡",
            "Designer": "📐",
            "Specialist": "🛠️",
            "Integrator": "🔗",
            "QC_Judge": "⚖️",
        }
        icon = icon_map.get(role, "🤖")

        print(f"\n[{icon} {role}] Step {step}")
        for key, value in log.items():
            print(f"  - {key}: {value}")

    async def run_analysis(
        self, start_event: StartEvent, summary_data: Dict
    ) -> AsyncGenerator[Any, None]:
        """
        Main Loop (Streaming Version)
        Yields events to be consumed by the Workflow.
        """
        logger_name = "OrchestratedAgent"

        # Step 1: Initialize Strategy (Evaluator)
        state = await self.roles["evaluator"].initialize_plan(
            start_event.query, summary_data
        )

        yield ProgressEvent(msg="🧠 正在制定全域分析策略...")

        # Main Loop
        while True:
            # [STOP CHECK] Check for immediate stop signal
            if self.analysis_service and self.analysis_service.is_generation_stopped(
                start_event.session_id
            ):
                print(
                    f"[{logger_name}] Stop signal received. Terminating analysis loop."
                )
                yield ProgressEvent(msg="🛑 收到停止信號，正在總結目前發現...")
                eval_out = RoleOutput(  # Define eval_out for the final check
                    decision="FINISH",
                    reasoning="收到停止信號，終止分析",
                    updates={},
                )
                break  # Exit the loop

            state.step_count += 1
            print(f"[{logger_name}] --- Step {state.step_count} ---")

            # Check maximum step limit
            if state.step_count >= self.MAX_STEPS:
                print(
                    f"[{logger_name}] ⚠️ Reached maximum step limit ({self.MAX_STEPS}). Forcing conclusion."
                )
                yield MonologueEvent(
                    monologue=f"【達到最大分析深度】\n已執行 {self.MAX_STEPS} 步分析，現在生成部分結論報告。",
                    tool_name="force_finish",
                    tool_params={},
                    query=start_event.query,
                    file_id=start_event.file_id,
                    session_id=start_event.session_id,
                    history="",
                )
                # Force Evaluator to finish
                eval_out = RoleOutput(
                    decision="FINISH",
                    reasoning=f"已達最大分析深度 ({self.MAX_STEPS} 步)，強制生成結論",
                    updates={},
                )
            else:
                # [MODIFIED] Integrate structured logging
                # Step 1: Evaluator Review (Strategy & QC)
                eval_in = RoleInput(state_machine=state, directive="REVIEW")
                eval_out = await self.roles["evaluator"].execute(eval_in)

                if eval_out.structured_log:
                    self._print_step_log(
                        state.step_count, "Evaluator", eval_out.structured_log
                    )
                else:
                    print(f"💡 評估觀點: {eval_out.reasoning[:100]}...")

                state.current_context = eval_out.new_context or state.current_context

                if eval_out.decision == "FINISH":
                    print(f"[{logger_name}] Evaluator decided to FINISH.")
                    break
                elif eval_out.decision == "CONTINUE" or eval_out.decision == "PIVOT":
                    # Step 2: Designer Context Update
                    des_in = RoleInput(state_machine=state, directive=eval_out.decision)
                    des_out = await self.roles["designer"].execute(des_in)

                    if des_out.structured_log:
                        self._print_step_log(
                            state.step_count, "Designer", des_out.structured_log
                        )

                    if des_out.decision == "CONTEXT_UPDATED" and des_out.new_context:
                        state.current_context = des_out.new_context
                        # Notify context update
                        targets_str = ", ".join(state.current_context.targets)
                        focus_range_str = (
                            f" (Row {state.current_context.focus_range})"
                            if state.current_context.focus_range
                            else " (Global Scan)"
                        )

                        yield ProgressEvent(
                            msg=f"🔄 分析焦點切換至: {targets_str}{focus_range_str}"
                        )
                        print(
                            f"[{logger_name}] TARGET PERSISTED: {state.current_context.targets}"
                        )

                # Step 3: Specialist Tool Selection
                spec_out = await self.roles["specialist"].execute(
                    RoleInput(state_machine=state)
                )

                if spec_out.decision == "EXECUTE_TOOL":
                    tool_name = spec_out.updates["tool_name"]
                    tool_params = spec_out.updates["tool_params"]

                    # [DEFENSIVE] Ensure tool_params is a dict
                    if isinstance(tool_params, str):
                        try:
                            import json

                            # Try to parse as JSON if it looks like JSON
                            if tool_params.strip().startswith("{"):
                                tool_params = json.loads(tool_params)
                            else:
                                # Fallback: assume empty dict if invalid string
                                print(
                                    f"[{logger_name}] Warning: tool_params is a string but not JSON: {tool_params}"
                                )
                                tool_params = {}
                        except json.JSONDecodeError:
                            print(
                                f"[{logger_name}] Error parsing tool_params JSON: {tool_params}"
                            )
                            tool_params = {}

                    if not isinstance(tool_params, dict):
                        print(
                            f"[{logger_name}] Warning: tool_params is not a dict: {type(tool_params)}"
                        )
                        tool_params = {}

                    # [BUG FIX] Automatically inject file_id if missing or placeholder
                    if "file_id" not in tool_params or tool_params.get("file_id") in [
                        "placeholder",
                        "...",
                        None,
                        "",
                    ]:
                        tool_params["file_id"] = start_event.file_id

                    # Notify User of Tool Selection
                    yield MonologueEvent(
                        monologue=f"【工具決策】\n{spec_out.reasoning}",
                        tool_name=tool_name,
                        tool_params=tool_params,
                        query=start_event.query,
                        file_id=start_event.file_id,
                        session_id=start_event.session_id,
                        history="",
                    )

                    # Step 4: Execute Tool
                    print(f"[{logger_name}] Executing: {tool_name} with {tool_params}")

                    # [NEW] Include targets and range in progress message
                    targets_info = ""
                    if state.current_context.targets:
                        targets_info = (
                            f" 目標: {', '.join(state.current_context.targets)}"
                        )

                    range_info = ""
                    if state.current_context.focus_range:
                        range_info = f" 區間: {state.current_context.focus_range}"
                    else:
                        range_info = " 區間: 全域"

                    yield ProgressEvent(
                        msg=f"⚙️ 正在調用 {tool_name}{targets_info}{range_info}..."
                    )

                    evidence = ""
                    conclusion = ""

                    try:
                        tool_result = await self.executor.execute_tool(
                            tool_name, tool_params, start_event.session_id
                        )

                        # Parse evidence
                        if isinstance(tool_result, dict) and "evidence" in tool_result:
                            evidence = tool_result["evidence"]
                        elif isinstance(tool_result, dict) and "result" in tool_result:
                            evidence = tool_result["result"]
                        elif isinstance(tool_result, dict) and "error" in tool_result:
                            evidence = tool_result["error"]
                            conclusion = "Tool Failed"
                        else:
                            evidence = str(tool_result)

                        conclusion = str(evidence)[:200] + "..."

                        # Optional: Yield Tool Result (if verbose mode)
                        yield ToolResultEvent(
                            tool=tool_name, result=str(evidence)[:500]
                        )

                    except Exception as e:
                        evidence = f"Tool execution failed: {str(e)}"
                        conclusion = "Failed"
                        print(f"[{logger_name}] Error: {e}")

                    # Record history
                    step_result = StepResult(
                        role="Specialist",
                        tool_name=tool_name,
                        tool_params=tool_params,
                        evidence=evidence,
                        conclusion=conclusion,
                        timestamp=0.0,
                    )
                    state.history.append(step_result)

                    # Step 5: Evaluator QC (Post-Tool)
                    # Step 5: Post-Tool QC (Explicit)
                    # We run the Evaluator again to "Judge" the result immediately
                    print(f"[{logger_name}] Running Post-Tool QC...")
                    qc_in = RoleInput(state_machine=state, directive="QC_REVIEW")
                    qc_out = await self.roles["evaluator"].execute(qc_in)

                    # [VISUALIZE] Explicit QC Report
                    qc_log = {
                        "Verdict": "✅ PASS"
                        if qc_out.decision == "CONTINUE"
                        else "❌ FAIL / PIVOT",
                        "Decision": qc_out.decision,
                        "Critique": qc_out.reasoning[:100] + "...",
                        "Guidance": qc_out.structured_log.get("QC_Feedback", "None"),
                    }
                    self._print_step_log(state.step_count, "QC_Judge", qc_log)

                    # [UI UPDATE] Send QC Report to Frontend (Thought Stream)
                    yield MonologueEvent(
                        monologue=f"【QC 判決】\n結果: {qc_log['Verdict']}\n原因: {qc_log['Critique']}\n指引: {qc_log['Guidance']}",
                        tool_name="QC_Judge",
                        tool_params={},
                        query=start_event.query,
                        file_id=start_event.file_id,
                        session_id=start_event.session_id,
                        history="",
                    )

                    # Update Thought History with QC verdict
                    state.thought_history.append(
                        f"Step {state.step_count} QC: {qc_log['Verdict']} - {qc_log['Guidance']}"
                    )

                    if qc_out.decision == "FINISH":
                        print(f"[{logger_name}] QC decided to FINISH.")
                        break

                    # If QC says PIVOT, we respect it immediately in the next loop
                    # The state is already updated by the evaluator execution (if any internal state changed)
                    # We just need to ensure the Next Loop starts with this context.

                    # (The loop continues to the next iteration, where Evaluator runs again as "Strategy Planner")

                else:
                    print(f"[{logger_name}] Specialist failed to select tool.")
                    yield ProgressEvent(msg="❌ 無法選擇合適的工具，終止分析。")
                    break

        # Step 6: Final Report (Integrator)
        yield ProgressEvent(msg="📝 正在整合最終分析報告...")
        print(f"[{logger_name}] Synthesizing Final Report...")
        final_report = await self.roles["integrator"].synthesize_report(state)

        # [DEFENSIVE] Ensure final_report is a dict
        if not isinstance(final_report, dict):
            final_report = {"summary": str(final_report), "charts": []}

        # Return final result dict (which will be wrapped in StopEvent by the Workflow)
        yield {
            "response": final_report.get("summary", "Analysis completed."),
            "chart": final_report.get("charts", []),  # Pass charts if any
        }
