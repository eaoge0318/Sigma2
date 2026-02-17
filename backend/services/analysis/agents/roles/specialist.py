from .base_role import BaseRole
from backend.services.analysis.analysis_types import RoleInput, RoleOutput
from backend.services.analysis.agents.prompts.system_prompts import (
    SPECIALIST_SYSTEM_PROMPT,
)


class SpecialistRole(BaseRole):
    """
    Role 1: 數據專家 (Data Specialist)
    負責：能夠理解 4-Variable Context，並選擇正確的統計工具進行驗證。
    """

    async def execute(self, input_data: RoleInput) -> RoleOutput:
        state = input_data.state_machine
        context = state.current_context

        # Provide tool usage history for intelligent decision-making
        tool_history = [
            f"Step {i + 1}: {step.tool_name} -> {step.conclusion[:100]}..."
            for i, step in enumerate(state.history[-5:])  # Last 5 steps
        ]
        recent_tools = [step.tool_name for step in state.history[-3:]]

        user_prompt = f"""
        [Analysis Task]
        Current Step: {state.step_count}
        Strategy Guidance: {state.strategy_plan}
        Goal: Analyze the relationship between Target {context.targets} and Features in Focus Range {context.focus_range}.
        
        [Context Variables]
        - Targets (Current Focal Point): {context.targets}
        - Feature Pool (Suspects): {context.feature_pool[:10]}... (Total {len(context.feature_pool)})
        - Focus Range (Experimental Group): {context.focus_range}
        - Baseline Range (Control Group): {context.baseline_range}
        
        [Causal Chain Tracking]
        - Current Chain: {state.causal_chain}
        
        [Tool Usage History]
        {chr(10).join(tool_history) if tool_history else "No previous steps"}
        
        [Recent Tools Used]
        Last 3 tools: {recent_tools}
        **IMPORTANT**: Avoid using the same tool repeatedly unless there's a strong reason.
        
        [Evaluator Feedback & Roadmap]
        - Roadmap: {state.analysis_roadmap}
        - Feedback: "{state.evaluator_feedback if state.evaluator_feedback else "No specific command. Follow roadmap."}"
        
        [Instruction]
        Select the best tool to provide STATISTICAL EVIDENCE based on:
        1. **Evaluator Feedback & Roadmap** (HIGHEST PRIORITY)
        2. What has already been analyzed (see Tool Usage History)
        
        **CRITICAL PARAMETER RULE**: 
        - When generating `parameters` (e.g., `target`, `targets`, `y_col`), you MUST use the parameters found in the latest link of the `Causal Chain` or the current `Targets`.
        - DO NOT revert to analyzing parameters already discarded as non-significant in the `Tool Usage History`.
        
        **Decision Guidelines**:
        - **【Sample Track】(Focus Range exists)**:
            - **MANDATORY**: If `Focus Range` is set and hasn't been compared yet, you MUST use `compare_data_segments` FIRST.
            - **EXCEPTION**: If `compare_data_segments` was already used on this range (check history) and yielded poor results, you MAY switch to `analyze_feature_importance` to find non-linear drivers.
            - **Reasoning**: "Abnormal samples (Where/When) must be compared against normal samples to find the root cause (Who/Why)."
            - **Objective**: Identify which parameters are significantly different in the Focus Range compared to the Global Baseline.
            - **FORBIDDEN**: Do NOT use `analyze_feature_importance` directly on a Focus Range without first running `compare_data_segments`.
        - **【Parameter Track】(Global or Target-driven)**:
            - If no global scan done -> `systemic_pca_analysis`
            - If target is identified -> `analyze_feature_importance` to find drivers.
            - If exploring relationships -> `get_top_correlations`.
        
        **MANDATORY REASONING RULE**:
        - You MUST explicitly mention the `Focus Range` (區間) and what you observed in the history.
        - Example: "【發現】位點 40-50 筆觀察到明顯多維度偏移，【行動】選擇執行 analyze_feature_importance 以找出該區間的驅動因子。"
        
        Return JSON format (MUST include the "tool_selection" wrapper):
        {{
            "tool_selection": {{
                "tool_name": "...",
                "parameters": {{ ... }},
                "reasoning": "...",
                "thought_summary": "..." 
            }}
        }}
        """

        resp = await self._call_llm(SPECIALIST_SYSTEM_PROMPT, user_prompt)
        parsed = self._parse_json(resp)
        selection = parsed.get("tool_selection", {})

        # Debug logging
        import logging

        logger = logging.getLogger(__name__)
        logger.info(f"[Specialist] LLM Response: {resp[:500]}...")
        logger.info(f"[Specialist] Parsed JSON: {parsed}")
        logger.info(f"[Specialist] Tool Selection: {selection}")

        if not selection or "tool_name" not in selection:
            logger.error(f"[Specialist] Failed to select tool. Selection: {selection}")
            return RoleOutput(
                decision="FAIL", reasoning="Failed to select a valid tool.", updates={}
            )

        tool_name = selection["tool_name"]
        tool_params = selection.get("parameters", {})
        reasoning = selection.get(
            "reasoning",
            f"Selected {tool_name} to analyze {context.targets}",
        )

        return RoleOutput(
            decision="EXECUTE_TOOL",
            reasoning=reasoning,
            updates={
                "tool_name": tool_name,
                "tool_params": tool_params,
            },
            # [NEW] Structured Log
            structured_log={
                "Tool": tool_name,
                "Intent": reasoning[:80] + "...",
                "Params": str(tool_params),
            },
        )
