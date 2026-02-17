from typing import List, Any
from backend.services.analysis.agents.roles.base_role import BaseRole
from backend.services.analysis.analysis_types import (
    RoleInput,
    RoleOutput,
    Evidence,
    ExperimentContext,
    AnalysisReport,
)


class Synthesizer(BaseRole):
    """
    [V2 Role] 綜合分析師 (Synthesizer)

    Responsibilities:
    1.  **De-noise**: Filter out failed experiments.
    2.  **Intent Verification**: Check if the Evidence matches the Planner's Original Intent.
    3.  **Conflict Resolution**: Weighted Confidence (Statistical > Visual).
    4.  **Synthesis**: Generate a User-Friendly Report (Layer 1) and Structured Findings (Layer 2).
    """

    SYSTEM_PROMPT = """
    你現在是 **綜合分析師 (Synthesizer / Editor-in-Chief)**。
    你的目標是將執行端 (Executor) 回傳的「證據 (Evidence)」與原本的「計畫 (Original Plan)」進行比對，並產出最終的 **分析報告 (AnalysisReport)**。

    ### 1. 驗收邏輯 (The "Inspector" Role)
    - **意圖對齊 (Match Intent)**: 執行的工具是否有回答到原本的問題？
      - 如果計畫是 "檢查因果"，但結果只有 "相關性"，請指出這個落差。
    - **濾除雜訊 (Filter Noise)**:
      - 忽略 `status="FAIL"` 的實驗。
      - 降低 `observation="Noisy"` 或 `Inconclusive` 的證據權重。

    ### 2. 綜合策略 (Subject-Oriented Synthesis)
    - 將發現按 **目標變數 (Target)** 分群。
    - **數值證據優先 (Evidence-Based)**: 在 `key_findings` 中必須包含具體數值。
    - **衝突解決 (Conflict Resolution)**:
      - Z-Score > 6 -> **極端異常**
      - Correlation > 0.7 -> 信心: **High**

    - **異常類型區分** [CRITICAL]:
      - **Row Anomaly (樣本異常)**: "Row 243 異常 (非參數)"
      - **Feature Anomaly (參數異常)**: "Sensor_A 異常 (參數)"
      - **絕對禁止**將 Row Index 當作 Feature Name。

    - **已知資訊優先** [CRITICAL]:
      - Turn 1 已發現的關鍵異常，即使後續工具失敗，仍應在報告中強調。

    ### 3. 重要: 只報告「新發現」 [CRITICAL]
    
    你的 `key_findings` 應該只包含 **本次 Turn 的新發現**，而不是重複過去的發現。
    
    - 若本次 Turn 確認了之前的發現 (例如分佈分析確認 Z-Score 的異常)，請記錄為:
      "確認 SHAP-DCS_A65 分佈呈右偏，與 Z=15.56 一致" (← 新資訊: 分佈形態)
    - 不要寫: "SHAP-DCS_A65 Z=15.56 異常" (← 這已經在上一個 Turn 報告過了)
    
    ### 3.4.1 優化推薦模式的 key_findings [CRITICAL]
    
    當 current_knowledge 包含 "[分析類型: 優化推薦]" 時:
    - key_findings 必須回答: **哪些參數影響目標? 調整方向是什麼?**
    - 格式: "參數X 與目標呈強正相關 (r=0.85)，降低參數X 可降低目標值"
    - 格式: "feature_importance 顯示參數Y 為最大驅動因子 (importance=0.15)"
    - **禁止**: 不要報告 "SHAP-DCS_A65 Z=15.56 異常" 這類與用戶問題無關的發現
    
    範例:
    - Turn 1 發現: "SHAP-DCS_A65 Z=15.56 極端異常"
    - Turn 2 新發現 (正確): "分佈分析確認 SHAP-DCS_A65 呈右偏分佈 (skewness=2.3)"
    - Turn 2 新發現 (正確): "SHAP-DCS_A65 趨勢圖顯示 Row 200 後急劇上升"
    - Turn 2 錯誤: "SHAP-DCS_A65 Z=15.56 異常" (← 重複！)

    ### 3.5 工程語義翻譯 (Engineering Semantic Translation) [NEW]
    
    將統計發現翻譯為工程師能理解的語言。在 key_findings 中，**除了統計數據,還必須附上工程解讀**:
    
    | 統計發現 | 工程語義翻譯 |
    |---------|-------------|
    | Std ≈ 0 (某區間) | 系統凍結: 傳感器未更新或控制器切換到手動模式 (Manual Hold) |
    | Lag = 0 (兩變數同步) | 極快控制迴路或因果倒置 (控制器輸出追逐製程變量) |
    | 高頻震盪 (方向變換率 > 60%) | PID 增益過高 (Over-tuning)，建議調降 P 或 D 參數 |
    | 分佈漂移 (K-S p < 0.05) | 製程條件改變: 配方切換、原料批次差異、或環境溫度漂移 |
    | 特徵重要性排名改變 | 不同區間的主導因素不同,可能存在多種失效模式 |
    | Harris Index < 0.3 | 控制回路表現不佳,實際方差遠大於理論最小方差 |
    | 控制器輸出觸頂/觸底 | 控制器飽和 (Saturation),可能存在 Integral Windup |
    | 交叉相關方向: Reference Leads | 上游參數 (Reference) 是因,下游 (Target) 是果 |
    
    範例:
    - 差的寫法: "Row 30-50 的 MEDIC-ABB_B40 標準差為 0.001"
    - 好的寫法: "Row 30-50 系統凍結 (FREEZE): MEDIC-ABB_B40 標準差僅 0.001,高頻噪聲消失,研判為傳感器未更新或控制器切到手動模式"
    
    ### 3.6 可執行建議 (Actionable Recommendations) [NEW]
    
    在 next_step_suggestion 中,除了下一步分析建議,若已有足夠證據,需附上**工程對策**:
    
    - 需要檢查的操作日誌 (如: "檢查 Row 30-50 時段是否有人員手動介入紀錄")
    - 需要確認的設備參數 (如: "檢查 PID 的 P 和 D 參數是否過高")
    - 建議的參數調整方向 (如: "建議適度調降 P 增益以減少震盪")

    ### 3.7 必要後續工具建議 (Mandatory Next-Step Rule) [CRITICAL]
    
    你的 next_step_suggestion 會直接被用作下一個 Turn 的指令。因此你必須**具體指定工具名稱**。
    
    **先判斷 current_knowledge 中的 [分析類型] 標籤，再選擇對應的工具建議**:
    
    #### A) 優化推薦 / 多目標優化 模式:
    - **Turn 1 之後** (影響因子掃描完成): 
      "針對最大驅動因子使用 cross_correlation_lag 確認因果方向,
       使用 performance_segmentation 找出最佳操作範圍 (好壞批次分離),
       使用 compare_data_segments 比較好壞批次的參數差異。"
    - **後續 Turn**: 
      "使用 analyze_residuals 驗證模型可靠性,
       使用 causal_relationship_analysis 確認各驅動因子之間的因果結構。"
    - **禁止**: 優化模式下不要建議 classify_anomaly_type (異常分類與優化問題無關)。
    
    #### B) 異常檢測模式 (預設):
    - **Turn 1 之後** (初始掃描完成): 
      "針對 Top 異常參數使用 classify_anomaly_type 進行異常類型分類,
       確認是 FREEZE/OSCILLATION/SPIKE/DRIFT/LEVEL_SHIFT。
       同時對 Top 3 異常參數使用 cross_correlation_lag 分析因果方向。
       若發現標準差極低的參數,使用 frequency_analysis 確認是否為傳感器凍結。"
    - **發現異常類型後**: 根據類型建議對應工具 (參見工程語義翻譯表)
    
    #### C) 區段比較模式:
    - "使用 compare_data_segments 比較指定區段,
       使用 hotelling_t2_analysis 找出主要差異貢獻因子。"
    
    - **禁止模糊建議**: 不要只寫 "繼續深入分析" 或 "驗證因果關係",要具體到工具名稱和參數。

    ### 3.8 防止鬼打牆 (Anti-Repeat Rule) [CRITICAL]
    
    - **禁止重複**: 如果某個工具+參數組合已經在 evidence_summary 中出現過結果,
      嚴禁在 next_step_suggestion 中再次建議同樣的組合。
    - **禁止重試失敗**: 如果某個實驗已經失敗 (error),不要建議重試相同的工具+參數。
      例如: performance_segmentation(target='良率') 已失敗,就不要再建議。
    - **替代方案**: 如果失敗原因是「欄位不存在」,建議先用 get_parameter_list 或 
      search_parameters 確認正確的欄位名稱,然後用正確的欄位重試。
    - **推進而非重複**: 每個 next_step_suggestion 都必須推進分析,不能原地打轉。

    ### 4. Output Format
    回傳一個 JSON 物件:
    {
        "thought": "用繁體中文描述你如何權衡證據。",
        "key_findings": [
            "本次 Turn 的新發現 1 (含工程語義翻譯)",
            "本次 Turn 的新發現 2"
        ],
        "causal_chain": [
            {
                "from": "上游參數或現象 (例: FORMULA-DCS_A15 漂移)",
                "to": "下游參數或影響 (例: BCDRY-DCS_A107 波動增大)",
                "evidence": "支撐因果的證據 (例: Cross-correlation lag=14, r=0.59, 上游領先)",
                "confidence": "HIGH/MEDIUM/LOW"
            }
        ],
        "isolated_observations": [
            "與因果鏈無關的獨立發現 (例: BCDRY-ABB_B19 在 Row 33-129 凍結, Std≈0.0001)"
        ],
        "rejected_hypotheses": [
            "被排除的假設"
        ],
        "next_step_suggestion": "必須具體到工具名稱。",
        "synthesis_logic": "綜合邏輯說明",
        "intent_coverage": 60,
        "completed_milestones": ["anomaly_identification", "anomaly_classification"],
        "analysis_gaps": [
            "本次分析缺少批次/區域維度的聚合,無法判斷異常是否與特定設備相關",
            "需要時頻域分析以區分短暫脆衝 vs 持續漂移"
        ],
        "decision": "CONTINUE" | "FINISH"
    }

    ### 4.1 causal_chain 規則 [CRITICAL]
    - **只放有直接證據支撐的因果關係**。Cross-correlation lag > 0 且 r > 0.4 才算有因果證據。
    - 僅有同時變動 (lag=0) 或弱相關 (r < 0.4) 的，放到 `isolated_observations`。
    - 如果本次 Turn 沒有新的因果發現，`causal_chain` 留空陣列 `[]`。
    - **禁止**把所有發現都塞進 causal_chain。大多數發現應該是 isolated_observations。

    ### 4.2 intent_coverage 規則 [CRITICAL]
    - 對照 **用戶的原始問題** 和 **分析檢查清單 (Checklist)**，評估目前為止的發現覆蓋程度。
    - 0 = 完全沒回答用戶問題。100 = 完全充分回答。
    - 判斷依據：
      - 用戶問「找原因」→ 是否已建立因果鏈？
      - 用戶問「優化」→ 是否已找到可調參數及方向？
      - 用戶問「比較」→ 是否已完成區段差異分析？
    - **intent_coverage < 70 時禁止 FINISH**，即使信息已不再有新發現。

    ### 4.3 completed_milestones 規則
    - 從下列里程碑中，標記已完成的 (參考 Checklist)：
      - "anomaly_identification": 已識別 Top 異常參數
      - "anomaly_classification": 已分類異常類型 (FREEZE/DRIFT/SPIKE...)
      - "causal_analysis": 已建立因果鏈 (cross-correlation / Hotelling T2)
      - "root_cause": 已找到根本原因
      - "actionable_recommendation": 已提出具體工程建議
      - "optimization_direction": 已找到參數調整方向 (優化模式)
      - "segment_comparison": 已完成區段比較 (比較模式)
    
    ### 4.4 analysis_gaps 規則 [必填]
    - 在綜合所有證據後,評估: **還有哪些分析角度尚未被執行?**
    - 即使為空也要填 `[]`
    - **注意**: 以下工具已存在,如果需要這些分析但尚未執行,應建議在 next_step_suggestion 中使用,而非列為 gap:
      - `interaction_effect_test` (兩因子交互作用), `batch_aggregation` (批次聚合),
      - `wavelet_analysis` (小波時頻分析), `cross_correlation_lag` (因果分析),
      - `frequency_analysis` (頻域分析), `correlation_network` (網路圖),
      - `regime_detection` (模式聚類), `performance_segmentation` (好壞批次分離)
    - **只在 analysis_gaps 中報告真正無法用現有工具完成的分析**:
      - "需要物理機理模型驗證統計發現"
      - "需要趨勢預測功能預估漂移超限時間"
      - "需要 DOE 實驗設計建議"
    """

    async def execute(self, input_data: RoleInput) -> RoleOutput:
        experiments = input_data.experiments  # The Plan
        evidences = input_data.evidences  # The Result
        state = input_data.state_machine  # For convergence check

        # 1. Pre-processing (Subject-Oriented Grouping)
        context_str = self._build_synthesis_context(experiments, evidences, state)

        # 2. Call LLM
        response = await self._call_llm(
            sys_prompt=self.SYSTEM_PROMPT,
            user_prompt=f"Please synthesize the following evidence:\n\n{context_str}",
        )

        # 3. Parse Output
        parsed = self._parse_json(response)

        # 4. Construct Report
        report = AnalysisReport(
            key_findings=parsed.get("key_findings", []),
            rejected_hypotheses=parsed.get("rejected_hypotheses", []),
            next_step_suggestion=parsed.get("next_step_suggestion", ""),
            synthesis_logic=parsed.get("synthesis_logic", ""),
        )

        # 5. Update Rolling Summary (每 3 步更新一次)
        new_summary, new_counter = await self._update_rolling_summary(state, report)

        # 6. Extract intent coverage and milestones from LLM output
        intent_coverage = parsed.get("intent_coverage", 50)
        try:
            intent_coverage = int(intent_coverage)
        except (ValueError, TypeError):
            intent_coverage = 50
        completed_milestones = parsed.get("completed_milestones", [])

        # 7. Check Convergence (combined: novelty + intent + checklist)
        is_converged = self._check_convergence(
            report.key_findings, state, intent_coverage, completed_milestones
        )

        # 如果收斂，強制 FINISH；否則尊重 LLM 的決定（但 intent_coverage < 70 時阻止 FINISH）
        llm_decision = parsed.get("decision", "CONTINUE")
        if is_converged:
            decision = "FINISH"
        elif llm_decision == "FINISH" and intent_coverage < 70:
            decision = "CONTINUE"  # 阻止過早結束
            print(
                f"[IntentGuard] LLM wants FINISH but intent_coverage={intent_coverage}% < 70%, forcing CONTINUE"
            )
        else:
            decision = llm_decision

        reasoning = parsed.get("reasoning", f"綜合了 {len(evidences)} 項證據。")
        if is_converged:
            reasoning = f"[已收斂] {reasoning} 新資訊比例 < 20%，建議結束分析。"

        # 7. Update state's rolling summary and counter (for orchestrator to persist)
        updates = {
            "rolling_summary": new_summary,
            "summary_update_counter": new_counter,
        }

        return RoleOutput(
            decision=decision,
            reasoning=reasoning,
            analysis_report=report,
            structured_log={
                "thought": parsed.get("thought", ""),
                "causal_chain": parsed.get("causal_chain", []),
                "isolated_observations": parsed.get("isolated_observations", []),
                "analysis_gaps": self._dedup_gaps(
                    parsed.get("analysis_gaps", []), state
                ),
            },
            updates=updates,
        )

    async def _update_rolling_summary(self, state, current_report) -> tuple[str, int]:
        """
        每 Turn 都更新滾動摘要 (Rolling Summary)
        直接累加新發現, 確保不會漏掉任何 Turn 的關鍵資訊
        回傳 (new_summary, new_counter)
        """
        new_counter = state.summary_update_counter + 1
        current_summary = state.rolling_summary

        # 直接累加新發現到 rolling_summary
        new_findings = (
            "\n".join(f"- {f}" for f in current_report.key_findings)
            if current_report.key_findings
            else ""
        )
        if new_findings:
            new_summary = (
                f"{current_summary}\n[Turn {new_counter}] {new_findings}"
                if current_summary
                else f"[Turn {new_counter}] {new_findings}"
            )
        else:
            new_summary = current_summary
        return new_summary, new_counter

    def _check_convergence(
        self,
        current_findings: List[str],
        state,
        intent_coverage: int = 50,
        completed_milestones: List[str] = None,
    ) -> bool:
        """
        三重收斂檢查 (Triple Convergence Check)

        必須同時滿足多項條件才觸發 FINISH:
        1. 信息新穎度 < 15% (keyword novelty)
        2. 意圖覆蓋率 >= 70% (intent_coverage from LLM)
        3. 檢查清單完成率 >= 60% (checklist milestones)
        """
        if not state.history or len(state.history) < 2:
            return False

        import re

        def _extract_keys(findings: List[str]) -> set:
            """Extract parameter names and key numbers as fingerprint"""
            keys = set()
            for f in findings:
                params = re.findall(r"[A-Z][A-Z0-9_-]+(?:_[A-Z0-9]+)+", f)
                keys.update(params)
                rows = re.findall(r"Row\s*(\d+)", f, re.IGNORECASE)
                keys.update(f"Row_{r}" for r in rows)
            return keys

        # --- Signal 1: Novelty Check ---
        previous_findings = []
        for step in state.history[-3:]:
            if hasattr(step, "analysis_report") and step.analysis_report:
                previous_findings.extend(step.analysis_report.key_findings)

        if len(current_findings) == 0:
            novelty_ratio = 0.0
        else:
            current_keys = _extract_keys(current_findings)
            previous_keys = _extract_keys(previous_findings)
            if not current_keys:
                novelty_ratio = 0.0
            else:
                new_keys = current_keys - previous_keys
                novelty_ratio = len(new_keys) / len(current_keys)

        novelty_saturated = novelty_ratio < 0.15

        # --- Signal 2: Intent Coverage ---
        intent_satisfied = intent_coverage >= 70

        # --- Signal 3: Checklist Completion ---
        required_milestones = self._build_completion_checklist(state)
        if completed_milestones and required_milestones:
            completed_set = set(completed_milestones)
            required_set = set(required_milestones)
            checklist_ratio = len(completed_set & required_set) / len(required_set)
        else:
            checklist_ratio = 0.5  # Default: assume 50% if no data

        checklist_satisfied = checklist_ratio >= 0.6

        print(
            f"[Convergence] novelty={novelty_ratio:.0%}(sat={novelty_saturated}) | "
            f"intent={intent_coverage}%(sat={intent_satisfied}) | "
            f"checklist={checklist_ratio:.0%}(sat={checklist_satisfied})"
        )

        # 三重門檻：信息飽和 + 意圖滿足 + 清單完成
        if novelty_saturated and intent_satisfied and checklist_satisfied:
            print("[Convergence] All 3 signals satisfied -> FINISH")
            return True

        # 高信心提前結束: 意圖覆蓋率 >= 90% 且清單完成
        if intent_coverage >= 90 and checklist_satisfied:
            print(
                "[Convergence] High intent coverage (>=90%) + checklist done -> FINISH"
            )
            return True

        return False

    def _dedup_gaps(self, new_gaps: List[str], state) -> List[str]:
        """
        代码层 analysis_gaps 去重:
        比较新 gap 与之前所有 Turn 报告的 gap,
        如果关键词重叠 > 50% 则视为重复并丢弃。
        """
        if not new_gaps:
            return []

        import re

        def _extract_keywords(text: str) -> set:
            """提取 CJK 关键词和英文单词"""
            # Latin words (e.g. DOE, ANOVA, PCA)
            latin = set(re.findall(r"[A-Za-z_]{3,}", text))
            # CJK phrases: extract 2-char and 3-char grams as proxy
            cjk_chars = re.findall(r"[\u4e00-\u9fff]+", text)
            cjk_kw = set()
            for seg in cjk_chars:
                if len(seg) >= 2:
                    cjk_kw.add(seg)
                    for i in range(len(seg) - 1):
                        cjk_kw.add(seg[i : i + 2])
            return latin | cjk_kw

        # Collect all previously reported gaps
        previous_gap_keywords = []
        if hasattr(state, "history") and state.history:
            for step in state.history:
                s_log = None
                if hasattr(step, "structured_log") and isinstance(
                    step.structured_log, dict
                ):
                    s_log = step.structured_log
                elif hasattr(step, "evidence") and isinstance(step.evidence, dict):
                    s_log = step.evidence.get("structured_log", None)
                if s_log and isinstance(s_log, dict):
                    for gap in s_log.get("analysis_gaps", []):
                        if isinstance(gap, str):
                            previous_gap_keywords.append(_extract_keywords(gap))

        # Filter: drop any new gap that has > 50% Jaccard overlap with any previous gap
        filtered = []
        for gap in new_gaps:
            if not isinstance(gap, str):
                continue
            gap_kw = _extract_keywords(gap)
            if not gap_kw:
                filtered.append(gap)
                continue

            is_duplicate = False
            for prev_kw in previous_gap_keywords:
                if not prev_kw:
                    continue
                intersection = gap_kw & prev_kw
                union = gap_kw | prev_kw
                jaccard = len(intersection) / len(union) if union else 0
                if jaccard > 0.50:
                    is_duplicate = True
                    break

            if not is_duplicate:
                filtered.append(gap)
                # Also track the new gap for intra-batch dedup
                previous_gap_keywords.append(gap_kw)

        if len(filtered) < len(new_gaps):
            print(
                f"[GapDedup] Dropped {len(new_gaps) - len(filtered)} duplicate gaps "
                f"(kept {len(filtered)}/{len(new_gaps)})"
            )

        return filtered

    def _build_completion_checklist(self, state) -> List[str]:
        """
        根據分析類型建立必要里程碑清單 (Completion Checklist)
        """
        knowledge = getattr(state, "current_knowledge", "")

        if "優化推薦" in knowledge or "多目標優化" in knowledge:
            return [
                "anomaly_identification",
                "optimization_direction",
                "actionable_recommendation",
            ]
        elif "區段比較" in knowledge:
            return [
                "anomaly_identification",
                "segment_comparison",
                "actionable_recommendation",
            ]
        elif "視覺化" in knowledge:
            return ["anomaly_identification"]  # 視覺化需求較簡單
        else:
            # 預設: 異常檢測 (最常見)
            return [
                "anomaly_identification",
                "anomaly_classification",
                "causal_analysis",
                "actionable_recommendation",
            ]

    def _build_synthesis_context(
        self,
        experiments: List[ExperimentContext],
        evidences: List[Evidence],
        state: Any,
    ) -> str:
        """
        Groups evidence by Target to facilitate 'Subject-Oriented Synthesis'.
        """
        # Map Exp ID to Exp Object
        exp_map = {exp.id: exp for exp in experiments}

        # Group by Target
        by_target = {}  # { "A257": [Evidence1, Evidence2], ... }

        for ev in evidences:
            if ev.status != "SUCCESS":
                continue  # Skip failures

            # Find target from original plan
            exp = exp_map.get(ev.experiment_id)
            target = exp.target_columns[0] if exp and exp.target_columns else "Unknown"

            if target not in by_target:
                by_target[target] = []
            by_target[target].append((exp, ev))

        # Build String
        ctx = "=== EVIDENCE BOARD ===\n"

        # [NEW] User's original question for intent alignment
        if hasattr(state, "original_query") and state.original_query:
            ctx += f"\n=== USER'S ORIGINAL QUESTION ===\n{state.original_query}\n"
            ctx += "[IMPORTANT] 你的 intent_coverage 評分必須對照此問題來判斷!\n"

        # [NEW] Completion Checklist
        required_milestones = self._build_completion_checklist(state)
        if required_milestones:
            ctx += "\n=== COMPLETION CHECKLIST ===\n"
            milestone_labels = {
                "anomaly_identification": "識別 Top 異常參數",
                "anomaly_classification": "分類異常類型 (FREEZE/DRIFT/SPIKE...)",
                "causal_analysis": "建立因果鏈 (cross-correlation / T2)",
                "root_cause": "找到根本原因",
                "actionable_recommendation": "提出具體工程建議",
                "optimization_direction": "找到參數調整方向",
                "segment_comparison": "完成區段比較",
            }
            for m in required_milestones:
                label = milestone_labels.get(m, m)
                ctx += f"  [ ] {m}: {label}\n"
            ctx += "[INSTRUCTION] 請在 completed_milestones 中標記已完成的項目\n"

        # [NEW] Add Historical Findings
        if hasattr(state, "rolling_summary") and state.rolling_summary:
            ctx += "\n=== HISTORICAL FINDINGS (已報告,禁止重複) ===\n"
            ctx += f"{state.rolling_summary}\n"
            ctx += "[IMPORTANT] 以上為過去 Turn 已報告的發現。你的 key_findings 應只包含本次 Turn 的新發現!\n"

        # [NEW] Gap Deduplication: 追蹤之前的 analysis_gaps, 避免重複報告
        previous_gaps = []
        if hasattr(state, "history") and state.history:
            for step in state.history[-5:]:
                # structured_log 存在 step.evidence["structured_log"] 中
                s_log = None
                if hasattr(step, "structured_log") and isinstance(
                    step.structured_log, dict
                ):
                    s_log = step.structured_log
                elif hasattr(step, "evidence") and isinstance(step.evidence, dict):
                    s_log = step.evidence.get("structured_log", None)
                if s_log and isinstance(s_log, dict):
                    gaps = s_log.get("analysis_gaps", [])
                    previous_gaps.extend(gaps)
        if previous_gaps:
            # 去重
            seen_gaps = list(set(previous_gaps))
            ctx += "\n=== PREVIOUSLY REPORTED GAPS (已知限制) ===\n"
            for gap in seen_gaps[-6:]:
                ctx += f"- [KNOWN_LIMITATION] {gap}\n"
            ctx += (
                "[RULE] 上述 gaps 已經報告過。不要在 analysis_gaps 中再次重複!\n"
                "如果這些需求仍無法滿足，請在 analysis_gaps 中寫: '系統目前不支持此功能'\n"
            )

        # [NEW] Add Known Anomalies
        if hasattr(state, "discovered_sites") and state.discovered_sites:
            ctx += "\n=== KNOWN ANOMALIES ===\n"
            for site in state.discovered_sites:
                ctx += f"- {site.parameter}: {site.description}\n"

        ctx += "\n=== CURRENT TURN RESULTS ===\n"
        for target, items in by_target.items():
            ctx += f"\n[Target: {target}]\n"
            for exp, ev in items:
                objective = exp.objective if exp else "Unknown Intent"
                ctx += f"  - Intent: {objective}\n"
                ctx += f"  - Tool: {ev.tool_name}\n"

                # [NEW] Smart Evidence Extraction
                key_metrics = self._extract_key_metrics(ev.result)
                ctx += f"  - Key Metrics: {key_metrics}\n"
                ctx += f"  - Observation: {ev.observation}\n"

        return ctx

    def _extract_key_metrics(self, result: any) -> str:
        """從工具結果中提取關鍵指標"""
        if not isinstance(result, dict):
            return str(result)[:500]

        key_metrics = []

        # 提取 Z-Score (單一欄位結果)
        if "stats" in result and isinstance(result["stats"], dict):
            max_z = result["stats"].get("max_z")
            if max_z and max_z > 3:
                severity = "極端異常" if max_z > 6 else "顯著異常"
                key_metrics.append(f"Max Z={max_z:.2f} ({severity})")
            max_sigma = result["stats"].get("max_sigma")
            min_sigma = result["stats"].get("min_sigma")
            if max_sigma and abs(max_sigma) > 3:
                key_metrics.append(f"Max Sigma={max_sigma:.2f}")
            if min_sigma and abs(min_sigma) > 3:
                key_metrics.append(f"Min Sigma={min_sigma:.2f}")

        # [FIX] 提取全域掃描結果中的 Top 異常參數 (含 Z-Score 數值)
        if "top_abnormal_parameters" in result:
            top_params = result["top_abnormal_parameters"]
            if isinstance(top_params, dict):
                param_details = []
                for param_name, param_data in list(top_params.items())[:5]:
                    if isinstance(param_data, dict):
                        stats = param_data.get("stats", {})
                        max_z = stats.get("max_z", 0)
                        max_sig = stats.get("max_sigma", 0)
                        min_sig = stats.get("min_sigma", 0)
                        # 取最大的絕對 sigma 值來判斷嚴重程度
                        worst_z = max(
                            abs(max_sig) if max_sig else 0,
                            abs(min_sig) if min_sig else 0,
                            max_z if max_z else 0,
                        )
                        if worst_z > 6:
                            severity = "極端異常"
                        elif worst_z > 3:
                            severity = "顯著異常"
                        else:
                            severity = "正常"
                        param_details.append(
                            f"{param_name}(Z={worst_z:.2f}, {severity})"
                        )
                    else:
                        param_details.append(str(param_name))
                if param_details:
                    key_metrics.append(f"Top異常: {', '.join(param_details)}")

        # 提取 Hotelling T2 異常樣本
        if "anomaly_indices" in result:
            indices = result["anomaly_indices"][:3]
            key_metrics.append(f"Anomaly Rows: {indices}")

        # 提取 Hotelling T2 貢獻度
        if "top_3_contributors" in result:
            contributors = result["top_3_contributors"]
            if isinstance(contributors, list):
                contrib_str = ", ".join(
                    f"{c.get('parameter', '?')}({c.get('contribution', 0):.1f}%)"
                    for c in contributors[:3]
                    if isinstance(c, dict)
                )
                if contrib_str:
                    key_metrics.append(f"T2 Contributors: {contrib_str}")

        # 提取相關性
        if "correlation" in result:
            corr = result["correlation"]
            if abs(corr) > 0.5:
                strength = "強" if abs(corr) > 0.7 else "中等"
                key_metrics.append(f"Corr={corr:.2f} ({strength})")

        # --- 新工具結果提取 ---

        # classify_anomaly_type 結果
        if "classifications" in result and isinstance(result["classifications"], list):
            for c in result["classifications"][:3]:
                if isinstance(c, dict):
                    atype = c.get("type", "UNKNOWN")
                    conf = c.get("confidence", 0)
                    rng = c.get("range", "?")
                    desc = c.get("description", "")[:100]
                    key_metrics.append(
                        f"異常分類[{rng}]: {atype} (信心{conf:.0%}) - {desc}"
                    )
            hints = result.get("engineering_hints", [])
            for h in hints[:2]:
                key_metrics.append(f"工程建議: {h[:150]}")

        # cross_correlation_lag 結果
        if "best_lag" in result and "peak_correlation" in result:
            lag = result["best_lag"]
            corr = result["peak_correlation"]
            interp = result.get("interpretation", {})
            direction = interp.get("causality_direction", "?")
            explanation = interp.get("explanation", "")[:200]
            key_metrics.append(
                f"交叉相關: Lag={lag}, Corr={corr:.3f}, 方向={direction}"
            )
            if explanation:
                key_metrics.append(f"因果解讀: {explanation}")

        # frequency_analysis 結果
        if "full_spectrum" in result:
            spec = result["full_spectrum"]
            entropy = spec.get("spectral_entropy", 0)
            dom_period = spec.get("dominant_period", 0)
            key_metrics.append(f"頻域: 熵={entropy:.2f}, 主頻週期={dom_period}")
            comparison = result.get("comparison")
            if comparison and isinstance(comparison, dict):
                for interp in comparison.get("interpretation", [])[:2]:
                    key_metrics.append(f"頻域比較: {interp[:150]}")
            for anomaly in result.get("spectral_anomalies", [])[:2]:
                key_metrics.append(f"頻譜異常: {anomaly[:150]}")

        # control_loop_assessment 結果
        if "harris_index" in result:
            harris = result["harris_index"]
            grade = harris.get("grade", "?")
            idx = harris.get("index", 0)
            key_metrics.append(f"Harris Index: {idx:.2f} ({grade})")
        if "oscillation_assessment" in result:
            osc = result["oscillation_assessment"]
            status = osc.get("status", "?")
            desc = osc.get("description", "")[:150]
            key_metrics.append(f"震盪評估: {status} - {desc}")
        if "engineering_assessment" in result:
            key_metrics.append(
                f"控制迴路總評: {result['engineering_assessment'][:200]}"
            )

        return " | ".join(key_metrics) if key_metrics else str(result)[:500]
