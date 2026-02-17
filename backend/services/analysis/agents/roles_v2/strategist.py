from backend.services.analysis.agents.roles.base_role import BaseRole
from backend.services.analysis.analysis_types import (
    RoleInput,
    RoleOutput,
    AnalysisState,
)
from collections import Counter


class Strategist(BaseRole):
    """
    [V2 Role] 策略指揮官 (Strategist)

    Responsibilities:
    1.  **User Intent Analysis**: Decode what the user REALLY wants (Actionable Insight).
    2.  **Turn-by-Turn Strategy**:
        - Turn 1 (Cold Start): Global Scan / Health Check.
        - Turn 2 (Focus): Deep Dive on specific anomalies.
        - Turn 3 (Verify): Causality check.
    3.  **Stop Criteria**: Converged evidence, Exhausted search, or Resource limit.
    """

    SYSTEM_PROMPT = """
    你現在是 **策略指揮官 (Strategist / Lead Investigator)**。
    你的目標是引導工業數據分析系統，精確回答使用者的問題 (User Query)。

    ### 1. 最高指導原則 (Prime Directive)
    - **對齊目標 (Alignment)**: 你的分析必須最終回答使用者的具體問題。
    - **拒絕發散 (Focus)**: 如果使用者問 "良率 (Yield)"，不要浪費時間分析無關的 "溫度"，除非你證明它們有關聯。
    - **可執行洞察 (Actionable Insight)**: 你的最終輸出應該幫助使用者「解決問題」或「找到原因」。
    - **語言規範**: 你的 thought 和 reasoning 必須使用 **繁體中文**。
    - **長訊息處理**: 當用戶的訊息很長時（例如包含之前的分析結果引用），用戶的真正意圖通常在訊息的**最後一段或最後幾行**。請優先根據訊息末尾來判斷用戶意圖，前面的內容視為參考上下文。

    ### 2. 分析類型自動識別 [CRITICAL]
    
    檢查 current_knowledge 中的 "[分析類型: ...]" 標籤。
    根據分析類型選擇不同策略:
    
    #### A. 優化推薦模式 (current_knowledge 包含 "優化推薦")
    
    用戶想知道如何調整某個目標變數。**禁止做全域異常掃描!**
    
    - **Turn 1 (Target Profiling + Segmentation)**:
      指令: "針對目標變數做完整側寫:
        (1) get_top_correlations(target=目標) - 找出相關性最高的前 10 個參數
        (2) analyze_feature_importance(target=目標) - 找出驅動因子排名
        (3) performance_segmentation(target=目標) - 分割好批/壞批,找出哪些參數最影響效能
        (4) analyze_distribution(parameter=目標) - 了解目標的分佈範圍"
    
    - **Turn 2 (Causality + Marginal Effects)**:
      指令: "針對 Turn 1 找到的 Top 5 相關參數:
        (1) partial_dependence(target=目標, features=Top5參數) - 看每個參數的邊際效應曲線
        (2) cross_correlation_lag(target=目標, reference=各相關參數) - 確認因果方向
        (3) causal_relationship_analysis - 驗證 Granger 因果性"
    
    - **Turn 3+ (Interaction + SOP)**:
      指令: "產出操作建議:
        (1) interaction_scatter(x=最重要參數, y=第二重要, color=目標) - 找 Sweet Spot
        (2) generate_operating_window(target=目標) - 生成 SOP 建議表 (設定值+範圍+方向)
        (3) 建議: 將參數X 調整到 range 範圍可讓目標下降 Y%"

    #### B. 區段比較模式 (current_knowledge 包含 "區段比較")
    
    用戶想比較不同數據區段的差異。**優先使用比較類工具!**
    
    - **Turn 1**: compare_data_segments + distribution_shift_analysis 比較兩區段
    - **Turn 2**: 對差異最大的參數使用 analyze_distribution + draw_trend 視覺化
    - **Turn 3**: 總結差異,提出可能原因

    #### C. 視覺化模式 (current_knowledge 包含 "視覺化")
    
    用戶只想看圖。**快速產出圖表後結案,不要做複雜分析!**
    
    - **Turn 1**: 直接使用 draw_trend / get_time_series_data 產出圖表
    - 收到結果後立即 FINISH

    #### D. 異常檢測模式 (預設模式)
    
    注意: Turn 1 的初始掃描 (detect_outliers + hotelling_t2 + get_top_correlations) 已由系統自動執行。
    你從 Turn 2 開始接手。

    - **Turn 2-3 (聚焦 Focus)**:
        - 根據 Turn 1 的初始掃描結果,鎖定最異常的參數或樣本
        - **第一步必須做異常類型分類** [MANDATORY]:
          指令 Planner 對 Top 3 異常參數使用 `classify_anomaly_type`,
          確認是 FREEZE / OSCILLATION / SPIKE / DRIFT / LEVEL_SHIFT。
          這決定了後續所有策略。
        - **區分異常類型 (Distinguish Anomaly Types)** [CRITICAL]:
          - **Feature Anomaly (參數異常)**: 指令: "針對 A257 進行分佈分析、趨勢圖、區段比較"
          - **Row Anomaly (樣本異常)**: 指令: "針對 Row 243 進行切片比較,找出異常前後差異"
          - **雙軌並行 (Dual Track)**: 若同時發現參數與樣本異常,**務必同時下達兩組指令**
        - 指令給 Planner 時要**具體且全面**,不要只叫他做一件事
        - 範例好指令: "對 SHAP-DCS_A65 使用 classify_anomaly_type 分類異常, 
          使用 cross_correlation_lag 分析其與 FORMULA-DCS_A15 的因果方向,
          並使用 frequency_analysis 確認是否有傳感器凍結特徵"
        - 範例差指令: "計算 SHAP-DCS_A65 的相關性" (太窄)

    - **Turn 4-10 (驗證與因果 Verify & Causal)**:
        - 驗證已發現的異常之間的因果關係
        - 使用進階工具: 殘差分析、PCA、特徵重要性
        - 建立因果鏈: A → B → C
        - **系統級視角**: 可使用 `correlation_network` 找出 Hub 中樞參數,
          `cv_ranking` 按波動性排名鎖定最不穩定的參數,
          `regime_detection` 識別操作模式切換時間點
        
    - **Turn 10+ (擴展 Expand, 僅深度模式)**:
        - 探索次要異常
        - 交叉驗證不同方法的結論
        - 分佈漂移、時間模式分析

    ### 2.5 反直覺檢查 (Counter-Intuition Check) [CRITICAL]
    
    當發現以下**反常現象**時,**不要直接接受**, 必須在 directive 中指令 Planner 進一步驗證:
    
    - **Lag = 0 (零延遲)**: "這在物理上合理嗎? 可能是因果倒置 (控制器輸出追逐製程變量)。
      指令 Planner 使用 cross_correlation_lag 確認, 並檢查該變數是否為控制器 OP 值。"
    - **標準差 = 0 (或趨近 0)**: "是真的穩定還是傳感器凍結?
      指令 Planner 使用 frequency_analysis 確認高頻噪聲是否消失, 並使用 classify_anomaly_type 區分 FREEZE vs 正常穩定。"
    - **相關性突然消失或反轉**: "是關係改變了還是數據品質問題? 
      指令 Planner 使用 distribution_shift_analysis 比較前後分佈。"
    - **高 Z-Score 但無時間趨勢**: "是持續異常還是單點突波?
      指令 Planner 使用 classify_anomaly_type 區分 SPIKE vs DRIFT vs LEVEL_SHIFT。"

    ### 2.6 異常類型導向策略 (Anomaly-Type-Driven Strategy) [NEW]
    
    當 classify_anomaly_type 回傳結果後,根據異常類型選擇對應策略:
    
    | 異常類型 | 後續工具 | 目的 |
    |---------|---------|------|
    | **FREEZE** | frequency_analysis + find_temporal_patterns | 確認傳感器凍結 vs 真實穩定 |
    | **OSCILLATION** | cross_correlation_lag + control_loop_assessment | 找出震盪源頭, 評估 PID 調校品質 |
    | **SPIKE** | find_event_patterns + compare_data_segments | 偵測事件序列, 比較前後差異 |
    | **DRIFT** | find_temporal_patterns + distribution_shift_analysis | 確認漂移趨勢, 量化漂移程度 |
    | **LEVEL_SHIFT** | compare_data_segments + get_top_correlations | 比較偏移前後, 找同時偏移的參數 |

    ### 3. 指令品質要求 [CRITICAL]
    
    你給 Planner 的 directive 決定了分析的深度。**不要給出只涉及 1-2 個工具的窄指令**。
    
    好的指令範例:
    - "Turn 1 發現 SHAP-DCS_A65 (Z=15.56) 和 FORMULA-DCS_A15 (Contribution=10.4) 異常。
      請對這兩個參數進行: (1) 分佈分析 (2) 時間趨勢 (3) 兩者間的相關性 (4) 與全域的區段比較"
    - "Row 243 被標記為多變量異常。請: (1) 比較 Row 238-242 vs Row 243-248 的差異 
      (2) 找出差異最大的前5個參數 (3) 對差異最大的參數做分佈偏移分析"
    
    差的指令範例:
    - "計算 SHAP-DCS_A65 與良率的相關性" → 太窄,只會產出 1 個實驗
    - "繼續分析" → 太模糊,Planner 不知道該做什麼

    ### 4. 回答對齊檢查 (Answer Alignment Check) [CRITICAL]
    
    在決定 FINISH 之前，必須先通過 **「回答對齊檢查」**:
    
    #### 完整性評分 (Completeness Score, 1-5 分):
    - **5 分**: 完整回答，含因果鏈與可執行建議
    - **4 分**: 找到關鍵變數，但缺乏因果驗證
    - **3 分**: 找到異常，但與目標變數的關聯未知
    - **2 分**: 只有初步掃描結果
    - **1 分**: 無有效發現
    
    #### FINISH 條件 (動態):
    - **完整性評分 >= 4 分** → 可以 FINISH
    - **完整性評分 = 3 分 且 已用超過一半步數** → FINISH (部分結論)
    - **連續 2 個 Turn 工具全失敗** → FINISH (提前結束)
    - **否則** → CONTINUE,繼續探索
    
    #### 範例:
    **使用者問題**: "為什麼良率下降?"
    
    **Turn 1 發現**: SHAP-DCS_A65 的 Z=859.99 極端異常  
    **完整性評分**: 3 分 (找到異常，但未驗證與良率關係)  
    **決定**: CONTINUE  
    **下一步指令**: "對 SHAP-DCS_A65 進行完整調查: 分佈分析、趨勢圖、與良率的相關性、區段比較"
    
    **Turn 2 發現**: SHAP-DCS_A65 與良率相關性 = -0.85 (強負相關)  
    **完整性評分**: 4 分 (找到關鍵變數且驗證關聯)  
    **決定**: FINISH  
    **結論**: "良率下降的主因是 SHAP-DCS_A65 異常升高 (Z=859.99)，兩者呈強負相關 (-0.85)"

    ### 5. 停止條件 (Stop Criteria)
    - **收斂 (Converged)**: 你已經有強力的多角度證據 (趨勢+統計+分佈) 支持某個假設。 -> `FINISH`
    - **耗盡 (Exhausted)**: 你已經掃描了所有可能性，但找不到顯著異常。誠實回報。 -> `FINISH`
    - **不要過早結束**: 如果還有未探索的重要異常,就 CONTINUE。

    ### 5.5 防止鬼打牆 (Anti-Repeat Rule) [CRITICAL]
    - **查看 '已使用工具' 清單**: 你的 directive 中不要再建議已經執行過的相同工具+參數組合。
    - **查看 '已失敗的實驗' 清單**: Context 中標記為「嚴禁重試」的實驗,絕對不要出現在 directive 中。
    - **每個 Turn 必須有新信息**: 如果你的 directive 與上一個 Turn 的內容高度重疊,代表你在鬼打牆。
      此時應該: (a) 嘗試不同的工具, (b) 嘗試不同的目標參數, (c) 降低 completeness 要求直接 FINISH。
    - **連續失敗處理**: 如果連續 2 個 Turn 的工具大量失敗，直接 FINISH 並在 reasoning 中說明原因。

    ### 6. Output Format
    回傳一個 JSON 物件:
    {
        "thought": "用繁體中文描述你對目前局勢的判斷",
        "hypothesis": "你的核心假設",
        "directive": "給實驗規劃師 (Planner) 的具體且全面的指令",
        "completeness_score": 3,
        "decision": "CONTINUE" | "FINISH",
        "reasoning": "簡短總結你的決策理由 (繁體中文)"
    }
    """

    async def execute(self, input_data: RoleInput) -> RoleOutput:
        state = input_data.state_machine

        # 1. Construct Context from State
        context_str = self._build_context_str(state)

        # 2. Call LLM
        response = await self._call_llm(
            sys_prompt=self.SYSTEM_PROMPT,
            user_prompt=f"User Query: {state.original_query}\n\nCurrent Context:\n{context_str}",
        )

        # 3. Parse Output
        parsed = self._parse_json(response)

        # 4. Construct RoleOutput
        return RoleOutput(
            decision=parsed.get("decision", "CONTINUE"),
            reasoning=parsed.get("reasoning", ""),
            hypothesis=parsed.get("hypothesis"),
            directive=parsed.get("directive"),
            structured_log={"thought": parsed.get("thought", "")},
        )

    def _build_context_str(self, state: AnalysisState) -> str:
        """
        Build a concise context string from the state machine.
        使用滾動摘要 + 最近 3 步，避免 Strategist 遺忘早期發現。
        """
        # Current Step & Resource
        ctx = f"Current Step: {state.step_count} / {state.max_steps}\n"

        # [NEW] Failure Counter
        ctx += self._calculate_failure_rate(state)

        ctx += f"Original Question: {state.original_query}\n\n"

        # [NEW] Used vs Unused Tools (for diversification)
        from backend.services.analysis.tools.registry import TOOL_REGISTRY

        if state.used_tools_history:
            # Extract just tool names from "tool::param" pairs
            used_tool_names = set()
            for pair in state.used_tools_history:
                tool_name = pair.split("::")[0] if "::" in pair else pair
                used_tool_names.add(tool_name)

            ctx += "=== 已使用工具 ===\n"
            tool_counts = Counter(
                [p.split("::")[0] if "::" in p else p for p in state.used_tools_history]
            )
            for tool, count in tool_counts.most_common():
                ctx += f"- {tool}: {count} 次\n"

            # Show UNUSED tools from registry (excluding blacklisted)
            blacklisted = {
                "basic_stats",
                "correlation_analysis",
                "search_parameters_by_concept",
                "get_time_series_data",
                "get_correlation_matrix",
                "get_data_overview",
                "compare_distributions",
            }
            all_tools = set(TOOL_REGISTRY.keys()) - blacklisted
            unused_tools = all_tools - used_tool_names
            if unused_tools:
                ctx += "\n=== 尚未使用的工具 (建議在 directive 中指定使用) ===\n"
                for tool in sorted(unused_tools):
                    spec = TOOL_REGISTRY.get(tool, {})
                    ctx += f"- {tool}: {spec.get('description', '')}\n"
                ctx += "[建議] 在你的 directive 中明確指定使用這些尚未探索的工具!\n"
            ctx += "\n"

        # [ANTI-REPEAT] Failed experiments blacklist
        if state.failed_experiments:
            ctx += "=== 已失敗的實驗 (嚴禁重試) ===\n"
            for failed in state.failed_experiments:
                ctx += f"- {failed}\n"
            ctx += "[嚴禁] 上述工具+參數組合已經失敗，不要在 directive 中再次建議！\n"
            ctx += "[替代] 如果目標欄位不存在，請使用 get_parameter_list 或 search_parameters 確認正確欄位名稱後再重試。\n\n"

        # Known Discoveries (Convergence Check)
        if state.discovered_sites:
            ctx += "=== Discovered Anomalies ===\n"
            for site in state.discovered_sites:
                ctx += f"- {site.range} (Score: {site.score:.2f}): {site.description}\n"

        # Historical Summary (Rolling Context)
        if state.rolling_summary:
            ctx += f"\n=== Previous Findings ===\n{state.rolling_summary}\n"

        # Recent History (最近 3 步的詳細進展)
        ctx += "最近進展 (Recent Steps):\n"
        if state.history:
            for i, step in enumerate(state.history[-3:]):  # Last 3 steps
                step_num = len(state.history) - 3 + i + 1
                ctx += f"- Step {step_num}: {step.conclusion}\n"
        else:
            ctx += "（無歷史記錄，這是分析的起點）\n"

        ctx += "\n"

        # Current Data Context
        if state.current_context:
            ctx += f"Current Focus: {state.current_context.targets}\n"
            ctx += f"Focus Range: {state.current_context.focus_range}\n"

        # [NEW] Surface Synthesizer's analysis_gaps so Strategist can relay to Planner
        if state.history:
            latest = state.history[-1]
            if hasattr(latest, "evidence") and isinstance(latest.evidence, dict):
                s_log = latest.evidence.get("structured_log", {})
                if isinstance(s_log, dict):
                    gaps = s_log.get("analysis_gaps", [])
                    if gaps and isinstance(gaps, list):
                        ctx += "\n=== Synthesizer 識別的分析缺口 ===\n"
                        for gap in gaps:
                            ctx += f"- {gap}\n"
                        ctx += "[建議] 在 directive 中指示 Planner 優先補齊上述缺口 (如果對應工具存在)。\n"

        # [NEW] Duplicate Analysis Detection (tool+params combinations)
        ctx += self._check_analysis_repetition(state)

        # [NEW] Query Alignment Signal — 幫助 Strategist 判斷是否已回答用戶問題
        ctx += self._check_query_alignment(state)

        return ctx

    def _calculate_failure_rate(self, state: AnalysisState) -> str:
        """計算工具失敗率，並提供逐 Turn 成功/失敗明細，觸發停滯警報"""
        if not hasattr(state, "evidences_history") or not state.evidences_history:
            return ""

        # 取最近 2 個 Turn 的 evidences
        recent_evidences = (
            state.evidences_history[-2:]
            if len(state.evidences_history) >= 2
            else state.evidences_history
        )

        total_tools = sum(len(turn_evidences) for turn_evidences in recent_evidences)
        failed_tools = sum(
            1
            for turn_evidences in recent_evidences
            for ev in turn_evidences
            if ev.status != "SUCCESS"
        )

        failure_rate = (failed_tools / total_tools * 100) if total_tools > 0 else 0

        ctx = "\n=== Tool Success Rate ===\n"
        ctx += f"Recent Tools: {total_tools - failed_tools}/{total_tools} successful ({100 - failure_rate:.1f}%)\n"

        # --- Per-Turn Breakdown ---
        consecutive_all_fail = 0
        for i, turn_evs in enumerate(reversed(state.evidences_history)):
            turn_total = len(turn_evs)
            turn_success = sum(1 for ev in turn_evs if ev.status == "SUCCESS")
            if turn_total > 0 and turn_success == 0:
                consecutive_all_fail += 1
            else:
                break

        if consecutive_all_fail >= 2:
            ctx += (
                f"\n[STAGNATION WARNING] 連續 {consecutive_all_fail} 個 Turn 的實驗全部失敗!\n"
                "[RECOMMENDATION] 根據停止條件 (Section 4, 完整性評分): 連續 2 Turn 工具全失敗 → 應 FINISH\n"
            )
        elif consecutive_all_fail == 1:
            ctx += "\n[CAUTION] 上一個 Turn 的實驗全部失敗。如果下個 Turn 仍然失敗，應考慮 FINISH。\n"

        # [NEW] Plan B Trigger
        if failure_rate > 50:
            ctx += "WARNING: Tool failure rate > 50%. Consider switching to reasoning-based analysis.\n"

        return ctx

    def _check_analysis_repetition(self, state: AnalysisState) -> str:
        """
        重複分析檢測: 比較最近 2 Turn 使用的 (tool+params) 和更早的 Turn,
        如果重複率 > 50%, 建議 FINISH。
        """
        if not hasattr(state, "used_tools_history") or not state.used_tools_history:
            return ""
        if not hasattr(state, "history") or len(state.history) < 4:
            return ""

        # Split history into recent (last 2 turns) and earlier
        all_pairs = list(state.used_tools_history)
        history_len = len(state.history)

        # Approximate: each turn has N experiments, split by step count
        # Use the step data to determine recent vs old
        recent_pairs = set()
        older_pairs = set()

        # Calculate proportional split: last 2 turns ~ last 2/total of all pairs
        if history_len >= 2:
            split_ratio = max(2, history_len - 2) / history_len
            split_idx = int(len(all_pairs) * split_ratio)
            older_pairs = set(all_pairs[:split_idx])
            recent_pairs = set(all_pairs[split_idx:])

        if not recent_pairs or not older_pairs:
            return ""

        # Calculate overlap
        overlap = recent_pairs & older_pairs
        overlap_ratio = len(overlap) / len(recent_pairs) if recent_pairs else 0

        ctx = ""
        if overlap_ratio > 0.5:
            ctx += (
                f"\n=== 重複分析警告 ===\n"
                f"最近 Turn 的實驗中有 {overlap_ratio:.0%} 與之前重複:\n"
            )
            for pair in sorted(overlap)[:5]:
                ctx += f"  - {pair}\n"
            ctx += (
                "[STRONG RECOMMENDATION] 分析已在「鬼打牆」! "
                "最近的 Turn 與歷史高度重複,無法產出新發現。\n"
                "建議: 直接 FINISH 並總結目前發現,或者嘗試完全不同的分析工具/參數。\n"
            )
        elif overlap_ratio > 0.3:
            ctx += (
                f"\n[CAUTION] 最近 Turn 有 {overlap_ratio:.0%} 的實驗與歷史重複。"
                f"請確認 directive 帶來新分析角度。\n"
            )

        return ctx

    def _check_query_alignment(self, state: AnalysisState) -> str:
        """
        使用者提問對齊: 提取原始問題的關鍵詞,
        與目前發現做比對, 告訴 Strategist 回答覆蓋率。
        """
        import re

        query = getattr(state, "original_query", "") or ""
        summary = getattr(state, "rolling_summary", "") or ""

        if not query or not summary:
            return ""

        def _extract_kw(text: str) -> set:
            latin = set(re.findall(r"[A-Z][A-Z0-9_-]+(?:_[A-Z0-9]+)*", text))
            cjk = set(re.findall(r"[\u4e00-\u9fff]{2,}", text))
            return latin | cjk

        query_kw = _extract_kw(query)
        summary_kw = _extract_kw(summary)

        if not query_kw:
            return ""

        covered = query_kw & summary_kw
        coverage = len(covered) / len(query_kw) if query_kw else 0

        ctx = "\n=== 使用者問題回答對齊 ===\n"
        ctx += f"原始問題關鍵詞: {', '.join(sorted(query_kw)[:8])}\n"
        ctx += f"已回答覆蓋率: {coverage:.0%}"

        if coverage >= 0.7:
            ctx += " (高 — 主要問題已有回答,可考慮 FINISH)\n"
        elif coverage >= 0.4:
            ctx += " (中 — 部分已回答,可繼續補強或 FINISH)\n"
        else:
            ctx += " (低 — 核心問題尚未回答,應 CONTINUE)\n"

        # Also show which query keywords are NOT yet in summary
        uncovered = query_kw - summary_kw
        if uncovered:
            ctx += f"尚未涵蓋: {', '.join(sorted(uncovered)[:5])}\n"

        return ctx
