from typing import Dict
from .base_role import BaseRole
from backend.services.analysis.analysis_types import (
    AnalysisContext,
    AnalysisState,
    RoleInput,
    RoleOutput,
)
from backend.services.analysis.agents.prompts.system_prompts import (
    EVALUATOR_SYSTEM_PROMPT,
)


class EvaluatorRole(BaseRole):
    """
    Role 0: 策略評估者與指揮官
    負責：
    1. initialize_plan: 根據使用者查詢制定初始策略與 Context。
    2. review_step: 在每一步專家的分析後，進行 QC 與決策 (Continue/Pivot/Finish)。
    """

    async def _semantic_target_search(
        self, query: str, numerical_columns: list, recommended_targets: list
    ) -> list:
        """
        三層智能目標搜索策略
        Layer 1: 直接欄位匹配
        Layer 2: LLM 語意擴展關鍵詞
        Layer 3: Fallback 到 CV 推薦目標
        """
        # Layer 1: 直接欄位匹配（簡單字串搜索）
        query_lower = query.lower()
        direct_matches = [
            col
            for col in numerical_columns
            if any(word in col.lower() for word in query_lower.split() if len(word) > 2)
        ]

        if direct_matches:
            return direct_matches[:3]  # 最多返回3個直接匹配

        # Layer 2: LLM 語意擴展
        semantic_prompt = f"""
        User Query: "{query}"
        
        Task: Extract technical keywords that might appear in sensor/parameter column names.
        
        Examples:
        - "斷紙" -> ["paper", "break", "tear", "tension", "speed", "張力", "速度", "紙"]
        - "溫度異常" -> ["temp", "temperature", "heat", "thermal", "溫", "熱"]
        - "產量下降" -> ["yield", "output", "production", "rate", "產", "量"]
        
        Return JSON: {{"keywords": ["...", "..."]}}
        
        IMPORTANT: Return 5-10 keywords. Include both English and Chinese terms if applicable.
        """

        try:
            resp = await self._call_llm(
                "You are a technical keyword extractor for industrial data analysis.",
                semantic_prompt,
            )
            parsed = self._parse_json(resp)
            keywords = parsed.get("keywords", [])

            # 使用擴展關鍵詞搜索
            semantic_matches = [
                col
                for col in numerical_columns
                if any(kw.lower() in col.lower() for kw in keywords)
            ]

            if semantic_matches:
                return semantic_matches[:3]
        except Exception:
            # LLM 失敗時靜默降級
            pass

        # Layer 3: Fallback 到 CV 推薦目標
        if recommended_targets:
            return recommended_targets[:3]

        # 最後的 Fallback：返回最後幾個數值欄位（通常是輸出）
        return (
            numerical_columns[-3:] if len(numerical_columns) >= 3 else numerical_columns
        )

    def _evaluate_tool_performance(self, last_result) -> str:
        """
        評估上一個工具的效能，並在效果不佳時建議替代方案
        """
        if not last_result:
            return ""

        tool_name = last_result.tool_name
        evidence = last_result.evidence or {}

        feedback_lines = []

        # 1. PCA Analysis Performance Check
        if tool_name == "systemic_pca_analysis":
            # Defensive check
            if not isinstance(evidence, dict):
                return ""

            explained_var = evidence.get("total_explained_variance", "")
            if explained_var:
                # Extract percentage (e.g., "43.44%" -> 43.44)
                try:
                    var_pct = float(explained_var.rstrip("%"))
                    if var_pct < 60:
                        feedback_lines.append(
                            f"⚠️ **[TOOL_FAILURE] PCA 解釋力不足** ({explained_var})"
                        )
                        feedback_lines.append(
                            "   **強制指令**: 請勿繼續依賴 PCA 結果。立刻切換至非線性工具。"
                        )
                        feedback_lines.append(
                            "   - `hotelling_t2_analysis` (更敏感的異常檢測)"
                        )
                        feedback_lines.append(
                            "   - `analyze_feature_importance` (直接找驅動因子)"
                        )
                except (ValueError, AttributeError):
                    pass

        # 2. Correlation Analysis Performance Check
        elif tool_name == "get_top_correlations":
            # Defensive check
            if not isinstance(evidence, dict):
                return ""

            correlations = evidence.get("correlations", [])
            if correlations:
                # Check if max correlation is too low
                max_corr = max(
                    [abs(c.get("correlation", 0)) for c in correlations], default=0
                )
                if max_corr < 0.3:
                    feedback_lines.append(
                        f"⚠️ **[WEAK_SIGNAL] 相關性過低** (最高: {max_corr:.2f})"
                    )
                    feedback_lines.append(
                        "   **強制指令**: 線性相關性失效。立刻切換至非線性工具。"
                    )
                    feedback_lines.append(
                        "   - `analyze_feature_importance` (Random Forest)"
                    )

        # 3. Feature Importance Performance Check
        elif tool_name == "analyze_feature_importance":
            # Defensive check
            if not isinstance(evidence, dict):
                return ""

            top_features = evidence.get("top_features", [])
            # [Fix] Handle case where top_features is valid but empty
            if top_features:
                max_importance = max(
                    [f.get("importance_score", 0) for f in top_features], default=0
                )
                if max_importance < 0.3:
                    feedback_lines.append(
                        f"⚠️ **[WEAK_SIGNAL] 特徵重要性偏低** (最高: {max_importance:.2f})"
                    )
                    feedback_lines.append(
                        "   **建議**: 既然找不出顯著驅動因子，可能是範圍鎖定錯誤，這或許是「系統性多點異常」而非單點異常。"
                    )

        # 4. Residual Analysis Performance Check
        elif tool_name == "analyze_residuals":
            anomalies = evidence.get("anomalies", [])
            if not anomalies or len(anomalies) == 0:
                feedback_lines.append("✅ **殘差分析未發現異常**")
                feedback_lines.append("   這表示線性模型適配良好，可以：")
                feedback_lines.append("   - 結束分析（已找到主要驅動因子）")
                feedback_lines.append("   - 或切換到其他目標變數")

        # 5. Hotelling T² Performance Check
        elif tool_name == "hotelling_t2_analysis":
            # Defensive check
            if not isinstance(evidence, dict):
                return ""

            anomaly_count = evidence.get("anomaly_count", 0)
            if anomaly_count == 0:
                feedback_lines.append("⚠️ **[NO_ANOMALY] Hotelling T² 未發現異常**")
                feedback_lines.append(
                    "   **建議**: 如果原問題是「有異常」，但 T² 沒抓到，請嘗試放寬 Focus Range 或改用 PCA。"
                )

        return "\n".join(feedback_lines) if feedback_lines else ""

    def _extract_anomalous_sites(self, last_result) -> list:
        """
        從工具證據中提取異常站點 (Row Ranges)
        """
        sites = []
        if not last_result or not isinstance(last_result.evidence, dict):
            return sites

        tool_name = last_result.tool_name
        evidence = last_result.evidence

        # 1. Hotelling T2 Analysis
        if tool_name == "hotelling_t2_analysis":
            primary_range = evidence.get("primary_anomaly_range")
            if primary_range:
                start, end = primary_range
                range_str = f"{start}-{end}"
                # 獲取顯著度 (這裡簡單使用其 contribution 最強的參數或總分)
                score = evidence.get("max_t2_score", 0.0)
                primary_params = [
                    c.get("parameter") for c in evidence.get("top_contributors", [])[:3]
                ]
                from backend.services.analysis.analysis_types import AnomalousSite

                sites.append(
                    AnomalousSite(
                        range=range_str,
                        score=float(score),
                        primary_params=[p for p in primary_params if p],
                        status="PENDING",
                    )
                )

        # 2. Local Outlier Factor
        elif tool_name == "local_outlier_factor_analysis":
            anomalous_segments = evidence.get("anomalous_segments", [])
            for seg in anomalous_segments:
                from backend.services.analysis.analysis_types import AnomalousSite

                sites.append(
                    AnomalousSite(
                        range=seg.get("range", ""),
                        score=seg.get("avg_score", 0.0),
                        primary_params=seg.get("parameters", []),
                        status="PENDING",
                    )
                )

        return sites

    async def execute(self, input_data: RoleInput) -> RoleOutput:
        """
        Evaluator 的主要入口，通常用於 QC 階段。
        """
        state = input_data.state_machine
        last_result = state.history[-1] if state.history else None

        # Check for repeated tool usage (infinite loop detection)
        recent_tools = (
            [step.tool_name for step in state.history[-3:]]
            if len(state.history) >= 3
            else []
        )
        is_repeating = len(recent_tools) >= 3 and len(set(recent_tools)) == 1

        # [NEW] Tool Performance Evaluation
        tool_performance_feedback = (
            self._evaluate_tool_performance(last_result) if last_result else ""
        )

        # [NEW] Analysis History Summary (Long-term Memory)
        thought_history_text = (
            chr(10).join(state.thought_history[-5:])
            if state.thought_history
            else "No previous analysis history."
        )

        user_prompt = f"""
        [Current Status]
        - Original Query: {state.original_query}
        - Strategy: {state.strategy_plan}
        - Step Count: {state.step_count}
        
        [Analysis History Summary (The Story So Far)]
        {thought_history_text}

        [Last Step Result]
        - Role: {last_result.role if last_result else "N/A"}
        - Tool: {last_result.tool_name if last_result else "N/A"}
        - Evidence: {last_result.evidence if last_result else "N/A"}
        - Conclusion: {last_result.conclusion if last_result else "N/A"}
        
        [Tool Performance Evaluation]
        {tool_performance_feedback if tool_performance_feedback else "No performance issues detected."}
        
        [Recent Tool History]
        - Last 3 tools: {recent_tools}
        - **WARNING**: {"REPEATED TOOL DETECTED! Same tool used 3+ times in a row." if is_repeating else "No repetition detected."}
        
        [Goal Decision]
        Analyze the evidence. Should we:
        1. CONTINUE (Drill down deeper with a DIFFERENT tool)?
        2. PIVOT (Current path is dead end, change target or approach)?
        3. FINISH (Enough evidence found)?
        
        [NEW: Macro Strategic Review]
        - Current Step: {state.step_count}
        - **MANDATORY**: Since we are at Step {state.step_count}, you MUST provide a "Strategic Progress Review" in your `reasoning`. 
        - Compare findings so far against the Original Query: "{state.original_query}".
        - Answer: "What do we know for sure?", "What is still a mystery?", and "Are we converging or drifting?".
        
        [Causal Chain Tracking]
        - Current Chain: {state.causal_chain}
        - **Task**: If you find a NEW key parameter (e.g., Target A drives Target B), you MUST add it to the `causal_chain`.
        
        [Anomalous Sites (Discovery)]
        - **PENDING Sites**: {[s.range + " (Score: " + str(s.score) + ")" for s in state.discovered_sites if s.status == "PENDING"]}
        - Analysed Sites: {[s.range for s in state.discovered_sites if s.status != "PENDING"]}
        - **Task**: You MUST prioritize addressing PENDING Sites. If a high-score site exists, you are FAILING if you only analyze global parameters.

        [Roadmap Management]
        - Current Roadmap: {state.analysis_roadmap}
        
        **MANDATORY OUTPUT PATTERN**:
        - `thought_summary` MUST follow the pattern: **【軌道標籤】 發現 [具體現象或證據摘要] ，下一步 [分析目標與行動動機] 。**
        - **Label Rules**:
            - **【樣本分析軌道】(Sample Track)**: Used when a specific time range, outlier, or pattern is identified (e.g., from Hotelling T2 or Outlier Factor). 
              - **CRITICAL REQUIREMENT**: You MUST explicitly state the Row Range (e.g., "40-50筆", "102-105筆") in the summary if known.
              - **PRIORITY RULE**: If you find an anomaly range from Hotelling T2, YOU MUST USE THIS LABEL FIRST, even if key parameters are also identified. Do NOT jump to Parameter Track until next step.
            - **【參數分析軌道】(Parameter Track)**: Used when a key driver/parameter is identified (e.g., from Feature Importance). Next action is usually "深入追查" or "尋找關聯".
        - Max length: 60 chars.
        - Example 1: "【樣本分析軌道】 發現 42-48 筆異常聚集，下一步 鎖定該區間進行 A/B 對照診斷。"
        - Example 2: "【參數分析軌道】 確認 A15 為主導因子，下一步 切換目標至 A15 追查其物理成因。"
        
        [Output Requirement]
        - reasoning: Detailed reasoning in Traditional Chinese. 
        - thought_summary: A single sentence (Max 30 chars) following the mandatory pattern.
        - new_causal_chain: The updated list of parameters.
        - new_roadmap: The updated list of high-level tasks.

        Return JSON format:
        {{
            "decision": "CONTINUE|PIVOT|FINISH",
            "reasoning": "...",
            "thought_summary": "...",
            "new_causal_chain": [...],
            "new_roadmap": [...]
        }}
        """

        # [NEW] Extract and Merge Anomalous Sites
        new_sites = self._extract_anomalous_sites(last_result)
        for ns in new_sites:
            # Avoid duplicates
            if not any(s.range == ns.range for s in state.discovered_sites):
                state.discovered_sites.append(ns)
                # Auto-add to roadmap as a task if it's a significant finding
                state.analysis_roadmap.append(
                    f"樣本診斷: 區間 {ns.range} (顯著度: {ns.score:.2f})"
                )

        resp = await self._call_llm(EVALUATOR_SYSTEM_PROMPT, user_prompt)
        parsed = self._parse_json(resp)

        decision = parsed.get("decision", "CONTINUE")
        reasoning = parsed.get("reasoning", "")
        thought_summary = parsed.get("thought_summary", "")

        # Update state tracked items
        if "new_causal_chain" in parsed:
            state.causal_chain = parsed["new_causal_chain"]

        # [ENFORCE] Parameter-Centric Task Splitting
        if "new_roadmap" in parsed:
            processed_roadmap = []
            for task in parsed["new_roadmap"]:
                # If a task is just "分析參數 X" or similar, split it
                if "分析參數" in task and "動因" not in task and "模式" not in task:
                    parts = task.split(":")
                    param_name = (
                        parts[-1].strip()
                        if len(parts) > 1
                        else task.replace("分析參數", "").strip()
                    )
                    processed_roadmap.append(
                        f"行為分析: 識別 {param_name} 之異常模式 (Pattern)"
                    )
                    processed_roadmap.append(
                        f"動因分析: 尋找 {param_name} 之驅動因子 (Drivers)"
                    )
                else:
                    processed_roadmap.append(task)
            state.analysis_roadmap = processed_roadmap

        # Update current site status if we are analyzing one
        current_range = state.current_context.focus_range
        if current_range:
            for s in state.discovered_sites:
                if s.range == current_range and s.status == "PENDING":
                    s.status = "ANALYZING"
                if decision == "PIVOT" or decision == "FINISH":
                    if s.range == current_range:
                        s.status = "COMPLETED"

        return RoleOutput(
            decision=decision,
            reasoning=reasoning,
            updates={
                "status": "REVIEWING",
                "thought_summary": thought_summary,
                "causal_chain": state.causal_chain,
                "analysis_roadmap": state.analysis_roadmap,
            },
            # [NEW] Structured Log for Console
            structured_log={
                "Strategy": decision,
                "Reasoning": thought_summary,
                "QC_Feedback": tool_performance_feedback
                if tool_performance_feedback
                else "Passed",
                "Roadmap_Progress": f"{len(state.history)} steps executed",
            },
        )

    async def initialize_plan(self, query: str, data_summary: Dict) -> AnalysisState:
        """
        規劃初始策略
        """
        # [NEW] 三層智能目標搜索
        numerical_cols = data_summary.get("numerical_columns", [])
        recommended_targets = data_summary.get("recommended_targets", [])

        suggested_targets = await self._semantic_target_search(
            query, numerical_cols, recommended_targets
        )

        user_prompt = f"""
        [New Request]
        User Query: "{query}"
        
        [Data Summary]
        - Total Columns: {len(data_summary.get("columns", []))}
        - Numerical Columns ({len(numerical_cols)}): {numerical_cols[:30]}
        - Rows: {data_summary.get("row_count", "Unknown")}
        - **Recommended Targets** (CV統計): {recommended_targets}
        - **Suggested Targets** (智能搜索): {suggested_targets}
        
        [CRITICAL: Target Selection Rules]
        **PRIORITY 1**: Use `Suggested Targets` (智能搜索結果). These are selected using a 3-layer strategy:
           - Layer 1: Direct column name matching with user query
           - Layer 2: LLM semantic keyword expansion
           - Layer 3: Fallback to CV-based recommended targets
        **PRIORITY 2**: If `Suggested Targets` is empty, use `Recommended Targets` (CV統計)
        **PRIORITY 3**: If both are empty, pick the LAST column from `Numerical Columns` list
        **CRITICAL**: You MUST select from ACTUAL column names. DO NOT invent column names.
        **NEVER**: Select metadata columns (containing 'id', 'index', 'timestamp', 'date', 'time', 'file')
        
        [Task]
        1. Define a high-level strategy.
           - **MANDATORY FIRST STEP**: Unless user specifies a narrow range, your strategy MUST start with "Global Scan using systemic_pca_analysis to identify Stable/Transition/Fault states".
        2. Define the INITIAL 4-Variable Context:
           - Targets: [Use Suggested Targets as first choice]
           - Focus Range: (If user specified, else leave empty for global scan)
           - Feature Pool: [] (Leave empty initially, will be populated by tools)
        
        [Output Requirement]
        - Please explain your strategy in Traditional Chinese (繁體中文).
        - **MANDATORY**: In your reasoning, explicitly state if the targets were selected via "語意匹配 (Semantic Match)" or "CV 統計推薦 (Statistical Recommendation)".
        - Detailed reasoning on why this strategy fits the user query.
        - Steps you plan to take.

        Return JSON format:
        {{
            "initial_plan": {{
                "strategy_name": "...",
                "reasoning": "...",  <-- In Traditional Chinese
                "key_focus": "...",
                "initial_context": {{ ... }},
                "initial_roadmap": ["Step 1: ...", "Step 2: ..."],
                "initial_causal_chain": ["Target1", "Target2"]
            }}
        }}
        """

        resp = await self._call_llm(EVALUATOR_SYSTEM_PROMPT, user_prompt)
        parsed = self._parse_json(resp)

        plan_data = parsed.get("initial_plan", {})
        context_data = plan_data.get("initial_context", {})

        # Build initial context
        targets = context_data.get("targets", [])
        if isinstance(targets, str):
            targets = [targets]

        # Type conversion for range fields (must be str or None, not list)
        focus_range = context_data.get("focus_range")
        if isinstance(focus_range, list):
            focus_range = None if not focus_range else str(focus_range[0])

        baseline_range = context_data.get("baseline_range")
        if isinstance(baseline_range, list):
            baseline_range = None if not baseline_range else str(baseline_range[0])

        initial_context = AnalysisContext(
            targets=targets,
            feature_pool=context_data.get("feature_pool", []),
            focus_range=focus_range,
            baseline_range=baseline_range,
        )

        # Construct detailed strategy string
        strategy_name = plan_data.get("strategy_name", "Standard Analysis")
        reasoning = plan_data.get("reasoning", "")
        key_focus = plan_data.get("key_focus", "")

        rich_plan = (
            f"**策略名稱**: {strategy_name}\n"
            f"**分析熱點**: {key_focus}\n"
            f"**策略邏輯**: {reasoning}"
        )

        return AnalysisState(
            session_id="session_init",  # Placeholder, updated by service
            file_id="file_init",
            original_query=query,
            strategy_plan=rich_plan,
            current_context=initial_context,
            causal_chain=plan_data.get("initial_causal_chain", targets),
            analysis_roadmap=plan_data.get(
                "initial_roadmap", ["初始全域掃描及異常檢測"]
            ),
            status="PLANNING",
        )
