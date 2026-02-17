from typing import Dict, Optional
from .base_role import BaseRole
from backend.services.analysis.analysis_types import (
    AnalysisContext,
    RoleInput,
    RoleOutput,
)
from backend.services.analysis.agents.prompts.system_prompts import (
    DESIGNER_SYSTEM_PROMPT,
)


class DesignerRole(BaseRole):
    """
    Role 2: 實驗設計者 (Experimental Designer)
    負責：根據前一步的證據，更新 4-Variable Context (Drill Down / Shift)。
    """

    def _apply_tool_rules(
        self, tool_name: str, evidence: Dict, context: AnalysisContext
    ) -> Optional[Dict]:
        """
        規則引擎：根據工具類型自動提取關鍵參數
        返回建議的 Context 更新，如果無法自動處理則返回 None
        """
        if not evidence:
            return None

        # [DEFENSIVE] Ensure evidence is a dict
        if not isinstance(evidence, dict):
            return None

        # Rule 1: Hotelling T² Analysis
        if tool_name == "hotelling_t2_analysis":
            # Extract top 5 contributors
            # [NEW] Row Focus Logic
            # Check for primary anomaly range (Time Clustering)
            # [FIXED] Combine Range Locking AND Target Switching
            # If we find a specific anomaly range, we MUST focus on it.
            # If we ALSO find a strong contributor, we MUST switch to it.

            # [UNIVERSAL RANGE LOCKING]
            # Regardless of tool, if evidence contains a range, we lock it.
            primary_range = evidence.get("primary_anomaly_range")
            # Also check for 'anomaly_range' key from other tools
            if not primary_range:
                primary_range = evidence.get("anomaly_range")

            new_focus_range = context.focus_range

            # Anti-Rollback: If we already have a focus range, keep it unless new range found
            if (
                not new_focus_range
                and primary_range
                and isinstance(primary_range, (list, tuple))
            ):
                start, end = primary_range
                new_focus_range = f"{start}-{end}"
            elif isinstance(primary_range, (list, tuple)):
                # Update to new range if found
                start, end = primary_range
                new_focus_range = f"{start}-{end}"

            # Check for top contributor to switch target
            new_targets = context.targets
            base_reasoning = f"Hotelling T² 發現異常區間 ({new_focus_range})"
            track_info = ""

            top_contributors = evidence.get("top_contributors", [])
            if isinstance(top_contributors, list) and len(top_contributors) > 0:
                top_param = top_contributors[0]
                param_name = top_param.get("parameter") or top_param.get("name")
                if param_name:
                    # [SMART TARGET LOCKING]
                    # Strategy:
                    # 1. Capture ALL significant contributors (Score > 0.1) to avoid missing co-drivers.
                    # 2. If no single param > 0.1, take Top 3 to cast a wider net.
                    # 3. If the top contributors are ALREADY in the current targets, we classify this as "VALIDATION" (Deep Dive).
                    # 4. If they are NEW, we classify as "DISCOVERY" (Switch).

                    significant_params = [
                        p.get("parameter") or p.get("name")
                        for p in top_contributors
                        if p.get("contribution", 0) > 0.1
                    ]

                    # Fallback: If no strong signals, take Top 3
                    if not significant_params:
                        significant_params = [
                            p.get("parameter") or p.get("name")
                            for p in top_contributors[:3]
                        ]

                    # Filter None
                    significant_params = [p for p in significant_params if p]

                    if significant_params:
                        # Check overlap with current targets
                        current_set = set(context.targets)
                        new_set = set(significant_params)

                        # Logic: Always switch to the significant set to "Focus"
                        # The user wants to see if their target is among them -> The result list ALREADY showed that.
                        # Now we must drill down into the ACTUAL anomalies.
                        new_targets = significant_params

                        if new_set.issubset(current_set):
                            track_info = f"，確認目標參數 {significant_params} 為主要異常 (驗證成功)，進入【參數分析軌道】深入分析其驅動因子"
                        else:
                            track_info = f"，發現新關鍵參數 {significant_params} (貢獻度顯著)，切換至【參數分析軌道】鎖定這些新目標"
                    else:
                        track_info = f"，觀察到 {param_name} 貢獻度較低，暫維持原目標，進入【樣本分析軌道】鎖定該區間進行對照診斷"
                else:
                    track_info = "，進入【樣本分析軌道】(Sample Track) 進行區間診斷"
            else:
                track_info = "，進入【樣本分析軌道】(Sample Track) 鎖定該區間進行診斷"

            # [CRITICAL] When entering Sample Track, ensure we compare against the REST of the data.
            # Setting baseline_range to None allows tools to automatically select "Rest of Data" as baseline.
            return {
                "targets": new_targets,
                "feature_pool": context.feature_pool,
                "focus_range": new_focus_range,
                "baseline_range": None,  # Explicitly reset baseline to imply "Global Comparison"
                "reasoning": base_reasoning + track_info,
            }

        # Rule 2: Compare Data Segments - Switch to identified driver
        elif tool_name == "compare_data_segments":
            # [UNIVERSAL RANGE LOCKING]
            # Ensure we don't lose the focus range during comparison
            primary_range = evidence.get("anomaly_range") or evidence.get(
                "primary_anomaly_range"
            )
            new_focus_range = context.focus_range

            if primary_range and isinstance(primary_range, (list, tuple)):
                start, end = primary_range
                new_focus_range = f"{start}-{end}"

            # After comparison, switch targets to the parameter with the largest difference
            top_diffs = evidence.get("top_differences", [])
            if isinstance(top_diffs, list) and len(top_diffs) > 0:
                # Take the top parameter with the largest z_score_diff
                top_param_data = top_diffs[0]
                top_param = top_param_data.get("parameter") or top_param_data.get(
                    "feature"
                )
                z_score = top_param_data.get("z_score_diff", 0)

                if top_param:
                    # [SMART EXPERIMENT DESIGN]
                    # If we have a focus_range locked, we should ensure baseline_range is set to None (Global)
                    # to force a contrast between "The Anomaly" and "The Normal".
                    return {
                        "targets": [top_param],  # Switch to the identified driver
                        "focus_range": new_focus_range,  # Keep the anomaly range locked
                        "baseline_range": None,  # Force comparison against global baseline
                        "reasoning": f"對照分析確認 {top_param} 為主導差異因子 (Z-Score: {z_score:.2f})，切換至【參數分析軌道】(Parameter Track) 深入追查其成因",
                    }

        # Rule 3: Feature Importance Analysis
        elif tool_name == "analyze_feature_importance":
            # [UNIVERSAL RANGE LOCKING]
            primary_range = evidence.get("anomaly_range") or evidence.get(
                "primary_anomaly_range"
            )
            new_focus_range = context.focus_range

            if primary_range and isinstance(primary_range, (list, tuple)):
                start, end = primary_range
                new_focus_range = f"{start}-{end}"

            top_features = evidence.get("top_features", [])
            if isinstance(top_features, list) and len(top_features) > 0:
                # Take top 5 features
                top_params = [
                    f.get("feature") or f.get("name") for f in top_features[:5]
                ]
                top_params = [p for p in top_params if p]
                if top_params:
                    return {
                        "targets": top_params,
                        "focus_range": new_focus_range,  # Preserve current site locking
                        "baseline_range": None,  # Force comparison against global baseline
                        "reasoning": f"Feature Importance 分析識別出 {len(top_params)} 個關鍵驅動因子，切換至【參數分析軌道】(Parameter Track) 設為新目標",
                    }

        # Rule 3: Correlation Analysis
        elif tool_name == "get_top_correlations":
            # [UNIVERSAL RANGE LOCKING]
            primary_range = evidence.get("anomaly_range") or evidence.get(
                "primary_anomaly_range"
            )
            new_focus_range = context.focus_range

            if primary_range and isinstance(primary_range, (list, tuple)):
                start, end = primary_range
                new_focus_range = f"{start}-{end}"

            correlations = evidence.get("correlations", [])
            if isinstance(correlations, list):
                # Filter correlations with |r| > 0.5
                strong_corrs = [
                    c for c in correlations if abs(c.get("correlation", 0)) > 0.5
                ]
                if strong_corrs:
                    top_params = [
                        c.get("parameter") or c.get("feature") for c in strong_corrs
                    ]
                    top_params = [p for p in top_params if p]
                    if top_params:
                        return {
                            "targets": top_params,
                            "focus_range": new_focus_range,  # Preserve current site locking
                            "baseline_range": None,  # Force comparison against global baseline
                            "reasoning": f"發現 {len(top_params)} 個強相關參數 (|r| > 0.5)，切換至【參數分析軌道】(Parameter Track) 設為新目標",
                        }

        # Rule 4: PCA Analysis - suggest next tool instead of changing targets
        elif tool_name == "systemic_pca_analysis":
            explained_var = evidence.get("total_explained_variance", "")
            if explained_var:
                try:
                    var_pct = float(explained_var.rstrip("%"))
                    if var_pct < 60:
                        return {
                            "suggestion": "PCA 解釋力不足，建議使用 Hotelling T² 或 Feature Importance",
                            "keep_current_targets": True,
                        }
                except (ValueError, AttributeError):
                    pass

        return None  # No rule matched, use LLM

    async def execute(self, input_data: RoleInput) -> RoleOutput:
        state = input_data.state_machine
        context = state.current_context
        # Get the latest result to inform the design
        last_step_result = state.history[-1] if state.history else None

        # Try rule-based approach first
        # [REFINED] Only skip rules if directive is PIVOT and the tool doesn't support target discovery.
        # Tools like 'analyze_feature_importance' and 'get_top_correlations' are TARGET DISCOVERY tools,
        # so their rules should apply even during a PIVOT.
        rule_suggestion = None
        target_discovery_tools = [
            "analyze_feature_importance",
            "get_top_correlations",
            "hotelling_t2_analysis",
        ]

        should_skip_rules = (
            input_data.directive == "PIVOT"
            and last_step_result
            and last_step_result.tool_name not in target_discovery_tools
        )

        if last_step_result and not should_skip_rules:
            rule_suggestion = self._apply_tool_rules(
                last_step_result.tool_name, last_step_result.evidence, context
            )

        # If rule matched and provides targets, use it
        if rule_suggestion and "targets" in rule_suggestion:
            # [ENFORCE] Always explicitly derive all 4 variables.
            # If a rule changes targets, it should decide whether to keep or reset the range.
            new_context = AnalysisContext(
                targets=rule_suggestion["targets"],
                feature_pool=rule_suggestion.get("feature_pool", context.feature_pool),
                focus_range=rule_suggestion.get(
                    "focus_range", None
                ),  # Default to Global Scan if not in rule
                baseline_range=rule_suggestion.get(
                    "baseline_range", context.baseline_range
                ),
            )
            return RoleOutput(
                decision="CONTEXT_UPDATED",
                new_context=new_context,
                reasoning=rule_suggestion["reasoning"],
            )

        # Otherwise, use LLM for complex decisions
        user_prompt = f"""
        [Current Context]
        - Current Targets: {context.targets}
        - Focus Range: {context.focus_range}
        
        [Causal Chain & Roadmap (The Task Manager)]
        - **Causal Chain**: {state.causal_chain} (Tracking Root Cause)
        - **Roadmap**: {state.analysis_roadmap} (Current Plan)
        
        [Anomalous Sites Registry]
        - **PENDING Sites**: {[s.range + " (Score: " + str(s.score) + ")" for s in state.discovered_sites if s.status == "PENDING"]}
        - ANALYZING Site: {[s.range for s in state.discovered_sites if s.status == "ANALYZING"]}

        [Evaluator Directive & Feedback]
        - Directive: **{input_data.directive}**
        - Feedback: "{state.evaluator_feedback if state.evaluator_feedback else "No specific command."}"

        [Last Finding]
        - Tool: {last_step_result.tool_name if last_step_result else "N/A"}
        - Evidence: {last_step_result.evidence if last_step_result else "N/A"}
        - Conclusion: {last_step_result.conclusion if last_step_result else "N/A"}
        
        [Your Task]
        You are the navigator of the Double-Helix Analysis Tracks (雙軌制導航):
        
        1. **【Sample Track (樣本分析軌道)】**:
           - **Goal**: Lock on "Where & When" the anomaly happened.
           - **Action**: Set `focus_range` to the anomaly range. Set `baseline_range` to null (implies "Rest of Data" comparison).
           - **Trigger**: When `Feedback` mentions a site or `Roadmap` says "樣本診斷".
           
        2. **【Parameter Track (參數分析軌道)】**:
           - **Goal**: Find "Who & Why" caused the anomaly (Root Cause).
           - **Action**: Switch `targets` to the high-ranking parameters found in previous steps. Keep `focus_range` if investigating local cause, or clear it if investigating global cause.
           - **Trigger**: When analysis finds a strong key driver (e.g., Contribution > 0.3 or Correlation > 0.5).

        **MANDATORY RULES**:
        - **SITE LOCKING**: If `Feedback` mentions a site or the next Roadmap task is "樣本診斷", you MUST set `focus_range`. 
        - **PRESERVE RANGE**: If `Current Context` already has a `focus_range` (e.g., "42-48"), you MUST KEEP IT unless the Directive explicitly says "Global Scan" or "Reset".
        - **ROADMAP SYNC**: If the current site is COMPLETED (check roadmap), you MUST switch to the next PENDING site.
        - **GLOBAL RESET**: Only use `focus_range = null` for the very first step or if explicitly told to perform a global re-scan.
        
        Return JSON with key `new_context`:
        {{
            "targets": [...],
            "feature_pool": [...],
            "focus_range": "...",
            "baseline_range": "..."  // Use null for "Rest of Data" comparison
        }}
        """

        resp = await self._call_llm(DESIGNER_SYSTEM_PROMPT, user_prompt)
        parsed = self._parse_json(resp)
        new_ctx_data = parsed.get("new_context", {})

        # Validation / Fallback
        if not new_ctx_data:
            return RoleOutput(
                decision="FAIL", reasoning="Failed to design new context.", updates={}
            )

        # Construct new context object
        # Inherit from old context if fields are missing
        new_context = AnalysisContext(
            targets=new_ctx_data.get("targets", context.targets),
            feature_pool=new_ctx_data.get("feature_pool", context.feature_pool),
            focus_range=new_ctx_data.get("focus_range", context.focus_range),
            baseline_range=new_ctx_data.get("baseline_range", context.baseline_range),
        )

        decision = "CONTEXT_UPDATED"
        reasoning = f"Updated context based on {input_data.directive}"

        return RoleOutput(
            decision=decision,
            reasoning=reasoning,
            new_context=new_context,
            # [NEW] Structured Log
            structured_log={
                "Context Action": decision,
                "Targets": str(new_context.targets) if new_context else "No Change",
                "Focus_Range": str(new_context.focus_range) if new_context else "-",
                "Baseline_Range": str(new_context.baseline_range)
                if new_context
                else "-",
                "Reason": reasoning[:50] + "...",
            },
        )
