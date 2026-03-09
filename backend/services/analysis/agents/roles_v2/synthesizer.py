from typing import List, Any
from backend.services.analysis.agents.roles.base_role import BaseRole
from backend.services.analysis.analysis_types import (
    RoleInput,
    RoleOutput,
    Evidence,
    ExperimentContext,
    AnalysisReport,
)
import json as _json


# === Module-level utilities (可被 orchestrator / strategist import) ===


def format_rolling_summary(raw_summary: str) -> str:
    """將 JSON 事件 Dict 格式化成人類/LLM 可讀文字塊"""
    if not raw_summary or not raw_summary.strip():
        return ""
    if not raw_summary.strip().startswith("{"):
        return raw_summary
    try:
        event_dict = _json.loads(raw_summary)
    except _json.JSONDecodeError:
        return raw_summary
    lines = []
    for event_key, entries in event_dict.items():
        lines.append(f"[Event: {event_key}]")
        for e in entries:
            turn = e.get("turn", "?")
            module = e.get("module", "")
            text = e.get("text", "")
            lines.append(f"  T{turn} [{module}] {text}")
    return "\n".join(lines)


def inject_to_rolling_summary(
    raw_summary: str, event_key: str, text: str, module: str = "系統"
) -> str:
    """安全向 JSON 事件 Dict 追加一筆記錄, 回傳更新後 JSON 字串"""
    if not raw_summary or not raw_summary.strip():
        event_dict = {}
    elif raw_summary.strip().startswith("{"):
        try:
            event_dict = _json.loads(raw_summary)
        except _json.JSONDecodeError:
            event_dict = {}
    else:
        event_dict = {}
        if raw_summary.strip():
            event_dict["歷史過渡"] = [
                {"turn": 0, "module": "摘要", "text": raw_summary.strip()}
            ]
    entry = {"turn": 0, "module": module, "text": text}
    if event_key not in event_dict:
        event_dict[event_key] = []
    event_dict[event_key].append(entry)
    return _json.dumps(event_dict, ensure_ascii=False)


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
    - **[CRITICAL] 禁止使用泛稱**: 在所有 key_findings 和建議中,
      永遠使用參數的**完整名稱** (如 METROLOGY-P21-MO1-SP-2SIGMA),
      **絕對禁止**只寫「目標變數」、「目標」或「target」等模糊代稱。
      正確例: "降低 MEDIC-DCS_A1005 可降低 METROLOGY-P21-MO1-SP-2SIGMA"
      錯誤例: "降低 MEDIC-DCS_A1005 可降低目標變數值" ← 讀者不知道目標是什麼
    - **衝突解決 (Conflict Resolution)**:
      - Z-Score > 6 -> **極端異常**
      - Correlation > 0.7 -> 信心: **High**

    ### 2.1 發現標記規則 (Finding Tagging) [CRITICAL]
    
    根據 current_knowledge 中的模式選擇標記方式:
    
    #### A. 有目標模式 (current_knowledge 包含 `[目標變量]`)
    每個 `key_findings` 條目必須標記與目標變量的關聯狀態:
    
    - **[已驗證]**: 有**統計關聯證據**顯示該發現與目標變量有關。
      必須具備以下至少一項: |r| > 0.3, feature_importance > 0, 因果關係 p < 0.05, 或控制迴路評估結果。
      **Z-Score 高不等於 [已驗證]**。Z-Score 只說明該參數自身異常,不代表它與目標有關。
      只有 Z-Score 的發現應標記為 [待驗證]。
      正確例: "[已驗證] FORMULA-DCS_A4 與目標變量呈強負相關 (r=-0.85), 是關鍵驅動因子"
      錯誤例: "[已驗證] SHAP-DCS_A65 Z=15.56 極端異常" ← 沒有關聯證據,應為 [待驗證]
    - **[待驗證]**: 異常但尚未確認與目標變量的關係
      例: "[待驗證] SHAP-DCS_A65 Z=15.56 極端異常, 但與目標變量的相關性未知"
    - **[無關]**: 已證明與目標變量無顯著關聯 (|r| < 0.3)
      例: "[無關] MEDIC-DCS_A1006 雖 CV 高但與目標變量相關性僅 r=0.05"
    - **[已排除]**: 經嫌疑犯篩查後排除 — 雖然統計指標異常 (高 CV / 高 Z-Score),
      但經控制迴路品質評估、頻譜分析等深入檢查後確認為正常行為,不再追蹤。
      例: "[已排除] MEDIC-DCS_A1006 (CV=1.24, 但 Harris=1.00, 頻譜正常, 非異常)"
    
    **intent_coverage**: 只有 [已驗證] 的發現才計入。
    
    #### B. 無指定線索模式 (current_knowledge 包含 `[線索目標] 尚未確定`)
    改用嚴重程度標記:
    
    - **[重要]**: Z > 6, 或異常類型為 DRIFT/LEVEL_SHIFT, 或為 Hub 中樞參數
      例: "[重要] FORMULA-DCS_A15 呈持續漂移 (DRIFT), Z=15.56, 控制迴路品質不佳"
    - **[次要]**: Z 3~6, 或 SPIKE/OSCILLATION 類型
      例: "[次要] BCDRY-ABB_B19 Z=7.56 異常, 為局部 SPIKE"
    - **[噪音]**: Z < 3, 或 FREEZE (傳感器問題非製程問題)
      例: "[噪音] SHAP-DCS_A65 為傳感器凍結 (FREEZE), 非製程異常"
    
    **intent_coverage**: 以異常分類完成率計算 (已分類數 / Top 5 異常數)。


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
    
    ### 3.6 可執行建議 (Actionable Recommendations)
    
    若已有足夠證據,在 key_findings 中附上工程解讀 (參見 3.5 工程語義翻譯表)。

    ### 3.7 共線性自動判定 (Collinearity Detection) [CRITICAL]
    
    - 當 evidence 中出現 **|r| > 0.99** 的參數組合時,標記為 "[共線性] A 與 B (r=0.999), 判定為同源信號"。
    - 將共線性參數放入 `isolated_observations`,不放入 `causal_chain`。
    - (系統代碼護欄會自動阻止後續對共線性組合的因果實驗)

    ### 3.8 只報告新發現 (Anti-Repeat) [CRITICAL]
    
    - key_findings 只包含本次 Turn 的**新發現**,不重複過去的發現。
    - 若本次確認了之前的發現,記錄新資訊而非重複舊結論。
    - 連續 2 輪無新 key_findings → `decision` 填 "FINISH"。

    ### 3.9 圖表觀察備註規則 (Visual Evidence Annotation) [CRITICAL]
    
    你可能會收到附帶圖表的證據 (Images)。對於從圖表中觀察到的新線索:
    
    - **記錄為 `key_findings` 的 [待驗證] 項**，例如:
      "[待驗證] 趨勢圖顯示 FORMULA-DCS_A15 在 Row 100-150 出現階梯式上升，可能為 Level Shift"
    - **禁止**將圖表觀察放入 `analysis_gaps`。圖表觀察是「已觀察到的現象」，不是「分析缺口」。
    - **禁止**因為圖表中看到新線索就建議額外的深入分析 — 你的職責是備註，不是追加實驗。
    - 圖表觀察應與數據證據交叉印證，例如:
      "趨勢圖確認 CUSUM 檢測到的 Row 120 變化點，視覺可見斜率驟變"

    ### 3.10 證據交叉比對規則 (Evidence Cross-Validation) [CRITICAL]
    
    當多個工具對同一參數給出矛盾結論時，你**必須**在 key_findings 中明確標記：
    
    - **T2 標記異常 但 classify_anomaly_type 回報 No anomaly / draw_trend 趨勢正常**:
      → 記錄為 `[已排除] PRESSDRY-SIEMENS_D43: T2 貢獻度排名第2，但單變量趨勢正常、無偵測到異常類型。異常可能為多變量結構偏移，非該參數自身問題`
    - **T2 標記異常 但本 Turn 中沒有任何後續工具(classify_anomaly_type/draw_trend/distribution_shift)對該參數進行驗證**:
      → 記錄為 `[未驗證] PRESSDRY-SIEMENS_D43: T2 貢獻度排名第2，但尚未進行單變量驗證，不可作為主因`
      → **禁止**將 [未驗證] 參數的 T2 結論寫入最終報告的結論段落
    - **禁止**照搬 T2 的 top_contributors 作為「主因參數」而忽視後續工具的否定證據或缺少驗證
    - 在 thought 中必須逐一檢查: T2 標記的每個參數是否已被本 Turn 的後續工具驗證，未驗證的列為 [未驗證]
    
    **原則**: 後續精細分析 (classify_anomaly_type, draw_trend, distribution_shift_analysis) 的結論
    優先於初步掃描 (T2, detect_outliers) 的結論。如果後續工具否定了初步掃描的判斷，
    必須降級或排除該參數，不可繼續宣稱其為主因。
    **未驗證的參數不得出現在結論段落中**，只能出現在 [未驗證] 標記的 key_findings 中。

    ### 3.11 新線索追蹤記錄規則 (New Clue Tracking) [IMPORTANT]
    
    當工具結果或圖表中出現**場景目標以外的新參數**時，記錄為 key_findings 的 [待追蹤] 項：
    
    - 例如 compare_data_segments 結果中出現新的高偏離參數:
      "[待追蹤] compare_data_segments 顯示 SHAP-DCS_A51 在 Row 240-243 偏離 Z=3.4σ，尚未進一步分析"
    - 例如圖表中觀察到場景目標外的參數行為:
      "[待追蹤] 趨勢圖中 PRESSDRY-ABB_B88 在 Row 200 後出現明顯下降，需確認"
    - **不要**為追蹤項建議具體工具 — 這是 Strategist 的職責


    ### 4. Output Format
    回傳一個 JSON 物件:
    {
        "thought": "用繁體中文描述你如何權衡證據。包含: (1) 參數線索 (2) 樣本線索 (3) 交叉判斷 (4) 圖表觀察 — 如果有附帶圖表,描述你從圖中看到了什麼 (例如趨勢形狀、異常點分佈、區段差異的視覺特徵)",
        "key_findings": [
            "[參數線索][已驗證] FORMULA-DCS_A15 為主要漂移源 (Z=7.90)",
            "[樣本線索][待驗證] Row 48-96 區間多變量異常, 與 A15 漂移時間重疊"
        ],
        "causal_chain": [
            {
                "from": "上游參數 (例: FORMULA-DCS_A15)",
                "to": "下游參數 (例: BCDRY-DCS_A107)",
                "evidence": "Cross-correlation lag=14, r=0.59",
                "confidence": "HIGH/MEDIUM/LOW"
            }
        ],
        "isolated_observations": ["與因果鏈無關的獨立發現"],
        "rejected_hypotheses": ["被排除的假設"],
        "next_step_suggestion": "簡要描述尚未釐清的分析面向 (不指定工具)",
        "synthesis_logic": "綜合邏輯說明",
        "intent_coverage": 60,
        "completed_milestones": ["anomaly_identification", "anomaly_classification"],
        "decision": "CONTINUE" | "FINISH"
    }

    ### 4.1 causal_chain 規則 [CRITICAL]
    - **只放有直接證據支撐的因果關係**。lag > 0 且 r > 0.4 才算因果證據。
    - 僅有 lag=0 或弱相關 (r < 0.4) 的放到 `isolated_observations`。
    - 本次 Turn 沒有新因果 → `causal_chain` 留空 `[]`。

    ### 4.2 intent_coverage 規則 [CRITICAL]
    - 對照用戶的原始問題,評估發現覆蓋程度 (0-100)。
    - **intent_coverage < 70 時禁止 FINISH**。

    ### 4.3 completed_milestones
    從下列標記已完成的:
    anomaly_identification / anomaly_classification / causal_analysis /
    root_cause / actionable_recommendation / optimization_direction / segment_comparison
    """

    async def execute(self, input_data: RoleInput) -> RoleOutput:
        experiments = input_data.experiments  # The Plan
        evidences = input_data.evidences  # The Result
        state = input_data.state_machine  # For convergence check

        # 1. Pre-processing (Subject-Oriented Grouping)
        context_str = self._build_synthesis_context(experiments, evidences, state)

        # 2. Collect evidence charts for multimodal LLM
        evidence_charts = []
        for ev in evidences:
            chart = getattr(ev, "chart_base64", None)
            if chart:
                evidence_charts.append(chart)
        # 限制最多 5 張圖以控制 token 用量
        evidence_charts = evidence_charts[:5]

        # 3. Call LLM (with optional images)
        # Build user prompt with chart awareness
        user_prompt = f"Please synthesize the following evidence:\n\n{context_str}"
        if evidence_charts:
            # 收集每張圖對應的工具名稱
            chart_tool_names = []
            for ev in evidences:
                chart = getattr(ev, "chart_base64", None)
                if chart:
                    chart_tool_names.append(ev.tool_name)
            chart_tool_names = chart_tool_names[:5]  # 與圖片數量對齊
            chart_list_str = ", ".join(chart_tool_names)
            user_prompt += (
                f"\n\n=== VISUAL EVIDENCE ({len(evidence_charts)} charts attached) ===\n"
                f"圖表來源: {chart_list_str}\n"
                f"[CRITICAL] 你收到了 {len(evidence_charts)} 張分析圖表。\n"
                f"請仔細觀察每張圖中的視覺特徵 (趨勢形狀、突變點、異常區段、數值範圍)，\n"
                f"並在 thought 中明確描述你從每張圖中看到了什麼。\n"
                f"特別注意: 圖表中可能包含數值證據未反映的視覺線索 (如漸變趨勢、局部異常)。\n"
            )
        response = await self._call_llm(
            sys_prompt=self.SYSTEM_PROMPT,
            user_prompt=user_prompt,
            images=evidence_charts if evidence_charts else None,
        )

        # 3. Parse Output
        parsed = self._parse_json(response)

        # [LOG] 確認 LLM 是否觀察了圖表
        if evidence_charts:
            thought = parsed.get("thought", "")
            thought_preview = thought[:200] if thought else "(empty)"
            print(
                f"[Synthesizer] 傳入 {len(evidence_charts)} 張圖表, "
                f"LLM thought: {thought_preview}"
            )

        # 4. Construct Report
        key_findings = parsed.get("key_findings", [])

        # [FIX] Fallback: 當 LLM 返回空 key_findings 但有成功的實驗時,
        # 自動從 evidence 中提取關鍵指標作為 findings
        if not key_findings and evidences:
            successful = [ev for ev in evidences if ev.status == "SUCCESS"]
            if successful:
                print(
                    f"[Synthesizer-Fallback] LLM returned 0 findings but {len(successful)} experiments succeeded. Auto-extracting..."
                )
                for ev in successful[:5]:
                    metrics_dict = self._extract_key_metrics(ev.result)
                    metrics_flat = self._flatten_metrics(metrics_dict)
                    if metrics_flat and len(metrics_flat) > 10:
                        exp = {e.id: e for e in experiments}.get(ev.experiment_id)
                        target_name = (
                            exp.target_columns[0]
                            if exp and exp.target_columns
                            else "Unknown"
                        )
                        finding = f"[待驗證] {ev.tool_name}({target_name}): {metrics_flat[:200]}"
                        key_findings.append(finding)
                if key_findings:
                    print(
                        f"[Synthesizer-Fallback] Auto-generated {len(key_findings)} findings from evidence"
                    )

        # 4.5 [CRITICAL] 程式化過濾: 把被否定的 T2 參數從 key_findings 中移除
        # 這確保所有下游 (DASHBOARD, scene_summary, final_decision) 都不會包含虛假結論
        try:
            _denied_params = set()
            _t2_params = set()
            for ev in evidences:
                if ev.status != "SUCCESS" or not isinstance(ev.result, dict):
                    continue
                tool = ev.tool_name or ""
                result = ev.result
                # 收集 T2 的 top_contributors
                if "hotelling" in tool or "t2" in tool.lower():
                    for zone in result.get("anomaly_zones", []):
                        for c in zone.get("top_contributors", []):
                            p = c.get("parameter", "")
                            if p:
                                _t2_params.add(p)
                    for c in result.get("top_contributors", []):
                        p = c.get("parameter", "")
                        if p:
                            _t2_params.add(p)
            # 也從歷史 discovered_sites 提取 T2 參數 (支援跨 Turn)
            if hasattr(state, "discovered_sites") and state.discovered_sites:
                for site in state.discovered_sites:
                    desc = getattr(site, "description", "") or ""
                    if "T2" in desc or "t2" in desc or "Hotelling" in desc:
                        param_name = getattr(site, "parameter", "")
                        if param_name:
                            _t2_params.add(param_name)
            if _t2_params:
                for ev in evidences:
                    if ev.status != "SUCCESS" or not isinstance(ev.result, dict):
                        continue
                    tool = ev.tool_name or ""
                    result = ev.result
                    if "classify_anomaly" in tool:
                        param = result.get("parameter", "")
                        zones = result.get("anomaly_zones", [])
                        has_anomaly = (
                            any(
                                z.get("type", "") not in ("", "NORMAL", "Normal")
                                for z in zones
                            )
                            if zones
                            else False
                        )
                        if param in _t2_params and not has_anomaly:
                            _denied_params.add(param)
                    elif "distribution_shift" in tool:
                        param = result.get("parameter", "")
                        if param in _t2_params and not result.get(
                            "is_significant", False
                        ):
                            _denied_params.add(param)
            if _denied_params:
                original_count = len(key_findings)
                filtered_findings = []
                for f in key_findings:
                    # 檢查此 finding 是否「專門」提及被否定的參數 (且不含已確認的參數)
                    mentioned_denied = [p for p in _denied_params if p in str(f)]
                    confirmed_params = [
                        p for p in _t2_params - _denied_params if p in str(f)
                    ]
                    if mentioned_denied and not confirmed_params:
                        # 整條 finding 都是關於被否定參數的, 移除
                        print(
                            f"[T2-Filter] 移除 finding (含已否定參數 {mentioned_denied}): {str(f)[:80]}"
                        )
                        continue
                    elif mentioned_denied:
                        # mixed finding: 保留但附加警告
                        denied_list = ", ".join(mentioned_denied)
                        f_str = (
                            str(f)
                            + f" [注意: {denied_list} 經後續驗證為非異常, 不應作為主因]"
                        )
                        filtered_findings.append(f_str)
                    else:
                        filtered_findings.append(f)
                # 加入明確的否定結論
                for p in _denied_params:
                    filtered_findings.append(
                        f"[T2交叉驗證-已排除] {p} 在 T2 貢獻排名中出現, "
                        f"但經 classify_anomaly_type/distribution_shift 驗證: 該參數無異常, "
                        f"不應列為異常主因。"
                    )
                key_findings = filtered_findings
                print(
                    f"[T2-Filter] findings {original_count} → {len(key_findings)}, "
                    f"已否定: {_denied_params}"
                )
        except Exception as e:
            print(f"[T2-Filter] 過濾出錯 (非致命): {e}")

        report = AnalysisReport(
            key_findings=key_findings,
            rejected_hypotheses=parsed.get("rejected_hypotheses", []),
            next_step_suggestion=parsed.get("next_step_suggestion", ""),
            synthesis_logic=parsed.get("synthesis_logic", ""),
        )

        # 5. Update Rolling Summary (每 Turn 更新 — 事件式)
        # 收集本 Turn 每個實驗的 event_key + 模組化 metrics
        exp_map = {exp.id: exp for exp in experiments}
        turn_event_entries = []  # [(event_key, module_key, metric_str), ...]
        for ev in evidences:
            if ev.status != "SUCCESS":
                continue
            exp = exp_map.get(ev.experiment_id)
            event_key = self._derive_event_key(exp, ev)
            ev_modules = self._extract_key_metrics(ev.result)
            for mod_key, items in ev_modules.items():
                for item in items:
                    turn_event_entries.append((event_key, mod_key, item))
        new_summary, new_counter = await self._update_rolling_summary(
            state, report, turn_event_entries, exp_map
        )

        # 5.5 [CRITICAL] T2 交叉比對結果回寫 rolling summary
        # 掃描本 Turn evidences, 如果有 T2 參數被其他工具否定, 直接注入到 summary
        try:
            t2_params_in_turn = set()
            deny_tools = {}  # {param: [denial_msgs]}
            for ev in evidences:
                if ev.status != "SUCCESS" or not isinstance(ev.result, dict):
                    continue
                tool = ev.tool_name or ""
                result = ev.result
                # 收集 T2 的 top_contributors
                if "hotelling" in tool or "t2" in tool.lower():
                    for zone in result.get("anomaly_zones", []):
                        for contrib in zone.get("top_contributors", []):
                            p = contrib.get("parameter", "")
                            if p:
                                t2_params_in_turn.add(p)
                    for contrib in result.get("top_contributors", []):
                        p = contrib.get("parameter", "")
                        if p:
                            t2_params_in_turn.add(p)
            # 也從歷史 discovered_sites 提取 T2 參數
            if hasattr(state, "discovered_sites") and state.discovered_sites:
                for site in state.discovered_sites:
                    desc = getattr(site, "description", "") or ""
                    if "T2" in desc or "t2" in desc or "Hotelling" in desc:
                        param_name = getattr(site, "parameter", "")
                        if param_name:
                            t2_params_in_turn.add(param_name)

            if t2_params_in_turn:
                # 掃描驗證工具結果
                for ev in evidences:
                    if ev.status != "SUCCESS" or not isinstance(ev.result, dict):
                        continue
                    tool = ev.tool_name or ""
                    result = ev.result
                    if "classify_anomaly" in tool:
                        zones = result.get("anomaly_zones", [])
                        param = result.get("parameter", "")
                        has_anomaly = (
                            any(
                                z.get("type", "") not in ("", "NORMAL", "Normal")
                                for z in zones
                            )
                            if zones
                            else False
                        )
                        if param in t2_params_in_turn and not has_anomaly:
                            deny_tools.setdefault(param, []).append(
                                f"classify_anomaly_type: 未檢測到異常"
                            )
                    elif "distribution_shift" in tool:
                        param = result.get("parameter", "")
                        sig = result.get("is_significant", False)
                        if param in t2_params_in_turn and not sig:
                            deny_tools.setdefault(param, []).append(
                                f"distribution_shift: 無顯著偏移"
                            )

                # 把否定結果注入 rolling summary
                if deny_tools:
                    for param, msgs in deny_tools.items():
                        denial_text = (
                            f"[T2交叉比對-已否定] 參數 {param} 雖在 T2 貢獻度排名中，"
                            f"但經後續工具驗證: {'; '.join(msgs)}。"
                            f"結論: {param} 不應被視為異常主因。"
                        )
                        new_summary = inject_to_rolling_summary(
                            new_summary, "T2交叉比對", denial_text, "交叉驗證"
                        )
                    print(
                        f"[T2-CrossVal] 已否定 {len(deny_tools)} 個 T2 參數, "
                        f"回寫 rolling summary: {list(deny_tools.keys())}"
                    )
        except Exception as e:
            print(f"[T2-CrossVal] 回寫 rolling summary 時出錯 (非致命): {e}")

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

        # [FIX] All-Fail Guard: 如果本 Turn 所有實驗都失敗, 強制 CONTINUE
        successful_count = sum(1 for ev in evidences if ev.status == "SUCCESS")
        all_failed = successful_count == 0 and len(evidences) > 0

        # 如果收斂，強制 FINISH；否則尊重 LLM 的決定（但 intent_coverage < 70 時阻止 FINISH）
        llm_decision = parsed.get("decision", "CONTINUE")

        if all_failed:
            decision = "CONTINUE"
            print(
                f"[FailGuard] All {len(evidences)} experiments failed this turn, "
                f"forcing CONTINUE regardless of convergence"
            )
        elif state.step_count <= 1:
            # Turn 1 是初始掃描, 場景尚未生成, 絕對不能 FINISH
            decision = "CONTINUE"
            print("[Turn1Guard] Turn 1 初始掃描完成, 必須繼續生成場景並深入調查")
        elif not key_findings and state.step_count < 5:
            # 如果 0 發現且 Turn 數少, 強制 CONTINUE
            decision = "CONTINUE"
            print(
                f"[EmptyFindingsGuard] 0 findings at Turn {state.step_count}, "
                f"forcing CONTINUE"
            )
        elif is_converged:
            # 檢查是否還有未完成的場景
            _pending = [
                s
                for s in getattr(state, "scene_queue", [])
                if s.status in ("PENDING", "ACTIVE")
            ]
            if _pending:
                decision = "CONTINUE"
                print(
                    f"[SceneGuard] Converged but {len(_pending)} scenes pending, "
                    f"forcing CONTINUE"
                )
            else:
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

        # 8. Synthesizer 直接組裝完整 current_knowledge
        #    包含 [SUMMARY] + [DASHBOARD] + [AutoTarget]
        #    Orchestrator 只做任務派送，不再組裝知識面板
        from backend.services.analysis.knowledge_utils import (
            set_summary as _set_summary,
            append_dashboard as _append_dashboard,
            append_routing as _append_routing,
        )

        _ck = state.current_knowledge
        # 8a. 寫入 [SUMMARY] 段落 (JSON 事件字典)
        if new_summary:
            _ck = _set_summary(_ck, new_summary)
        # 8b. 寫入 [DASHBOARD] 段落 (本 Turn 的分析摘要)
        _dashboard_entry = (
            f"[Update]: {report.synthesis_logic}\n"
            f"Findings: {report.key_findings}\n"
            f"Next: {report.next_step_suggestion}"
        )
        _ck = _append_dashboard(_ck, _dashboard_entry)

        # 8c. 直接從 evidences 提取 AutoTarget (首次掃描時)
        #     不再依賴 state.auto_target_raw，Synthesizer 在 Turn 1 就能處理
        _at_data = self._extract_auto_targets_from_evidence(evidences)
        if _at_data and (
            _at_data.get("auto_targets") or _at_data.get("auto_row_ranges")
        ):
            _at_lines = []
            _at_targets = _at_data.get("auto_targets", [])
            _atg = _at_data.get("anomaly_type_groups", [])
            _t2s = _at_data.get("t2_summary", {})
            _ar = _at_data.get("auto_row_ranges", [])

            if _at_targets:
                _at_lines.append(
                    f"自動識別 {len(_at_targets)} 個異常參數: "
                    + ", ".join(_at_targets[:10])
                    + (f" ...等{len(_at_targets)}個" if len(_at_targets) > 10 else "")
                )
            if _atg:
                for tg in _atg[:6]:
                    tcn = tg.get("type_cn", tg.get("type", ""))
                    pc = tg.get("param_count", 0)
                    params = tg.get("parameters", [])
                    ps = ", ".join(params[:5])
                    if len(params) > 5:
                        ps += f" ...等{pc}個"
                    _at_lines.append(f"  {tcn}({pc}個參數): {ps}")
            if _t2s:
                nc = _t2s.get("n_components", 0)
                ve = _t2s.get("variance_explained", "")
                th = _t2s.get("t2_threshold", 0)
                _at_lines.append(f"PCA-T2: {nc} 主成分, 解釋力 {ve}, 閾值 T2={th}")
                for az in (_t2s.get("anomaly_zones", []) or [])[:7]:
                    sr = az.get("zone_range", az.get("range", ""))
                    st2 = az.get("t2_max", 0)
                    sp = ", ".join(
                        [
                            c.get("parameter", "")
                            for c in az.get("top_contributors", [])[:3]
                        ]
                    )
                    _at_lines.append(f"  T2 異常區段 {sr} (T2_max={st2}): {sp}")
            if _ar:
                for rr in _ar[:5]:
                    rr_range = rr.get("range", "")
                    rr_sev = rr.get("severity", "")
                    rr_zone = rr.get("zone_label", "")
                    rr_params = rr.get("params", [])
                    rr_types = rr.get("types", [])
                    _at_lines.append(
                        f"  異常區段 {rr_range} (severity={rr_sev}) "
                        + (f"[{rr_zone}] " if rr_zone else "")
                        + ", ".join(rr_params[:3])
                        + (" / " + "/".join(rr_types[:2]) if rr_types else "")
                    )
            if _at_lines:
                _at_block = "\n\n## [AutoTarget 全局掃描結果] ##\n" + "\n".join(
                    _at_lines
                )
                _ck = _append_routing(_ck, _at_block)
                print(
                    f"[Synthesizer] AutoTarget 寫入 current_knowledge: "
                    f"{len(_at_lines)} 行"
                )

        updates = {"current_knowledge": _ck}
        # 將 AutoTarget 結構化數據傳回 Orchestrator (用於 ProgressEvents + state 更新)
        if _at_data and (
            _at_data.get("auto_targets") or _at_data.get("auto_row_ranges")
        ):
            updates["_auto_target_data"] = _at_data

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

    @staticmethod
    def _extract_auto_targets_from_evidence(evidences: list) -> dict:
        """
        直接從 evidences 列表中提取 AutoTarget 資料。
        在 Turn 1 Synthesizer 階段就能執行，無需等到 Turn 2 Strategist。

        從以下工具提取:
        - hotelling_t2_analysis → auto_targets + auto_row_ranges + t2_summary
        - scan_anomaly_segments → anomaly_type_groups
        - detect_outliers → fallback auto_targets

        回傳 dict: {
            "auto_targets": [...],
            "auto_row_ranges": [...],
            "anomaly_type_groups": [...],
            "t2_summary": {...},
        }
        """
        auto_targets = []
        auto_row_ranges = []
        _anomaly_type_groups = []
        _t2_summary = {}

        for ev in evidences:
            # --- hotelling_t2_analysis: 主力來源 ---
            if ev.tool_name == "hotelling_t2_analysis" and ev.status == "SUCCESS":
                result = ev.result if isinstance(ev.result, dict) else {}
                top_contribs = result.get("top_contributions", [])

                # 參數目標: 從全域 T2 Top 6 貢獻
                _t2_all_params = [
                    c.get("parameter", "")
                    for c in top_contribs
                    if c.get("parameter", "")
                ]
                for param_name in _t2_all_params[:6]:
                    if param_name not in auto_targets:
                        auto_targets.append(param_name)

                # 記錄 T2 概要 (含趨勢數據供 MINI_CHART 繪圖)
                _t2_summary = {
                    "n_components": result.get("n_components_used", 0),
                    "variance_explained": result.get("variance_explained", ""),
                    "t2_threshold": result.get("t2_threshold", 0),
                    "t2_trend": result.get("t2_trend", []),
                    "anomaly_zones": result.get("anomaly_zones", []),
                }

                # 從 anomaly_zones 提取結構化區段
                t2_zones = result.get("anomaly_zones", [])
                t2_zones = sorted(
                    t2_zones, key=lambda z: z.get("t2_max", 0), reverse=True
                )
                for zone in t2_zones[:8]:
                    zone_range = zone.get("zone_range", "")
                    t2_mean = zone.get("t2_mean", 0)
                    t2_max = zone.get("t2_max", 0)
                    zone_len = zone.get("length", 0)
                    severity = min(10, 5 + t2_mean * 0.1)
                    zone_top = zone.get("top_contributors", [])
                    zone_params = [c["parameter"] for c in zone_top]
                    is_fallback = zone.get("is_fallback", False)

                    if zone_range and zone_len >= 1:
                        auto_row_ranges.append(
                            {
                                "range": zone_range,
                                "severity": round(severity, 2),
                                "params": zone_params,
                                "types": ["T2_ZONE"],
                                "affected_params_count": len(zone_params),
                                "t2_mean": t2_mean,
                                "t2_max": t2_max,
                                "is_fallback": is_fallback,
                                "source": "T2",
                            }
                        )

                # Fallback: anomaly_zones 為空時從 primary_anomaly_range 補
                if not t2_zones:
                    primary_range = result.get("primary_anomaly_range")
                    if (
                        primary_range
                        and isinstance(primary_range, (list, tuple))
                        and len(primary_range) == 2
                    ):
                        r_start, r_end = int(primary_range[0]), int(primary_range[1])
                        if r_end - r_start + 1 >= 3:
                            max_t2 = result.get("max_t2_value", 0)
                            auto_row_ranges.append(
                                {
                                    "range": f"Row {r_start}-{r_end}",
                                    "severity": round(min(10, 5 + max_t2 * 0.1), 2),
                                    "params": _t2_all_params[:6],
                                    "types": ["T2_ANOMALY"],
                                    "affected_params_count": min(
                                        len(_t2_all_params), 6
                                    ),
                                    "source": "T2",
                                }
                            )

            # --- scan_anomaly_segments: 只提取分類資訊 ---
            if ev.tool_name == "scan_anomaly_segments" and ev.status == "SUCCESS":
                result = ev.result if isinstance(ev.result, dict) else {}
                _anomaly_type_groups = result.get("anomaly_type_groups", [])

        # Fallback: detect_outliers Z-Score 排名
        if not auto_targets:
            for ev in evidences:
                if ev.tool_name == "detect_outliers" and ev.status == "SUCCESS":
                    result = ev.result if isinstance(ev.result, dict) else {}
                    top_params = result.get("top_abnormal_parameters", {})
                    if isinstance(top_params, dict):
                        for param_name in list(top_params.keys())[:3]:
                            if param_name not in auto_targets:
                                auto_targets.append(param_name)

        # Fallback: detect_outliers 推斷區段
        if not auto_row_ranges:
            for ev in evidences:
                if ev.tool_name == "detect_outliers" and ev.status == "SUCCESS":
                    result = ev.result if isinstance(ev.result, dict) else {}
                    total_rows = result.get("total_rows", 0)
                    if total_rows > 0:
                        mid = total_rows // 2
                        auto_row_ranges.append(
                            {
                                "range": f"Row {mid}-{total_rows - 1}",
                                "severity": 3,
                                "params": auto_targets[:2] if auto_targets else [],
                                "types": ["unknown"],
                            }
                        )

        if not auto_targets and not auto_row_ranges:
            return {}

        return {
            "auto_targets": auto_targets,
            "auto_row_ranges": auto_row_ranges,
            "anomaly_type_groups": _anomaly_type_groups,
            "t2_summary": _t2_summary,
        }

    @staticmethod
    def _flatten_metrics(metrics_dict: dict) -> str:
        """將模組化 Dict 平鋪成 pipe-separated string (用於 fallback/debug)"""
        if isinstance(metrics_dict, str):
            return metrics_dict
        if not isinstance(metrics_dict, dict):
            return str(metrics_dict)[:500]
        all_items = []
        for items in metrics_dict.values():
            all_items.extend(items)
        return " | ".join(all_items) if all_items else ""

    @staticmethod
    def _derive_event_key(exp, ev) -> str:
        """
        從實驗計畫 + 工具結果推導事件 key
        格式: "參數名" 或 "參數名 (Row X-Y)" 或 "全域掃描"
        """
        target = "Unknown"
        segment = ""

        # 1. 從實驗計畫取得 target
        if exp:
            if exp.target_columns:
                targets = exp.target_columns
                if len(targets) == 1 and targets[0].lower() == "all":
                    target = "全域掃描"
                elif len(targets) <= 2:
                    target = "+".join(targets)
                else:
                    target = f"{targets[0]}+{len(targets) - 1}個"
            # 2. 從 focus_range 取得區段
            if exp.focus_range:
                segment = f" ({exp.focus_range})"

        # 3. 特殊工具的覆寫
        if ev and hasattr(ev, "tool_name"):
            tool = ev.tool_name or ""
            if tool in (
                "scan_anomaly_segments",
                "zone_diagnosis",
                "multivariate_anomaly_detection",
                "cv_ranking",
                "correlation_network",
                "regime_detection",
            ):
                target = "全域掃描"
                segment = ""

        return f"{target}{segment}"

    async def _update_rolling_summary(
        self,
        state,
        current_report,
        turn_event_entries: list = None,
        exp_map: dict = None,
    ) -> tuple[str, int]:
        """
        每 Turn 更新滾動摘要 (Rolling Summary) — 事件式版本
        內部以 JSON Dict 儲存: { event_key: [ {turn, module, text}, ... ] }
        回傳 (formatted_summary_str, new_counter)
        """
        import json
        from backend.services.analysis.knowledge_utils import get_summary

        new_counter = state.summary_update_counter + 1
        raw = get_summary(state.current_knowledge)

        # 解析現有的 JSON dict (相容舊版純文字格式)
        if raw.strip().startswith("{"):
            try:
                event_dict = json.loads(raw)
            except json.JSONDecodeError:
                event_dict = {}
        else:
            # 舊格式: 將整段放進 "歷史過渡" key
            event_dict = {}
            if raw.strip():
                event_dict["歷史過渡"] = [
                    {"turn": 0, "module": "摘要", "text": raw.strip()}
                ]

        # Part A: 工具指標 — 按事件分組入師
        if turn_event_entries:
            for event_key, mod_key, text in turn_event_entries:
                label = self._MODULE_LABELS.get(mod_key, mod_key)
                entry = {"turn": new_counter, "module": label, "text": text}
                if event_key not in event_dict:
                    event_dict[event_key] = []
                event_dict[event_key].append(entry)

        # Part B: LLM key_findings — 按內容推測 event_key
        if current_report.key_findings:
            for finding in current_report.key_findings:
                # 嘗試從 finding 文字中提取參數名作為 event_key
                event_key = self._guess_event_key_from_finding(finding)
                entry = {"turn": new_counter, "module": "摘要", "text": finding}
                if event_key not in event_dict:
                    event_dict[event_key] = []
                event_dict[event_key].append(entry)

        # 序列化存儲 (內部用 JSON, 對外輸出用格式化文字)
        serialized = json.dumps(event_dict, ensure_ascii=False)
        return serialized, new_counter

    @staticmethod
    def _guess_event_key_from_finding(finding: str) -> str:
        """
        從 LLM 產生的 finding 文字中推測 event_key
        優先匹配參數名 (e.g. SHAP-DCS_A65)
        """
        import re

        # 匹配工業參數名: 大寫開頭 + 含底線/橫線 + 英數組合
        params = re.findall(r"[A-Z][A-Z0-9_-]+(?:_[A-Z0-9]+)+", finding)
        if params:
            # 取第一個匹配到的參數名
            return params[0]
        # 匹配區段範圍 (Row 45-82)
        row_match = re.search(r"Row\s*(\d+)\s*[-~–]\s*(\d+)", finding, re.IGNORECASE)
        if row_match:
            return f"區段 Row {row_match.group(1)}-{row_match.group(2)}"
        return "綜合分析"

    @classmethod
    def _format_rolling_summary(cls, raw_summary: str) -> str:
        """
        將 JSON 事件 Dict 格式化成人類/LLM 可讀的文字塊
        """
        import json

        if not raw_summary or not raw_summary.strip():
            return ""
        if not raw_summary.strip().startswith("{"):
            return raw_summary  # 舊格式 fallback
        try:
            event_dict = json.loads(raw_summary)
        except json.JSONDecodeError:
            return raw_summary

        lines = []
        for event_key, entries in event_dict.items():
            lines.append(f"[Event: {event_key}]")
            for e in entries:
                turn = e.get("turn", "?")
                module = e.get("module", "")
                text = e.get("text", "")
                lines.append(f"  T{turn} [{module}] {text}")
        return "\n".join(lines)

    def _check_convergence(
        self,
        current_findings: List[str],
        state,
        intent_coverage: int = 50,
        completed_milestones: List[str] = None,
    ) -> bool:
        """
        四重收斂檢查 (Quadruple Convergence Check)

        觸發 FINISH 的條件 (任一即可):
        A. 三重門檻: novelty < 15% AND intent >= 70% AND checklist >= 60%
        B. 高信心提前結束: intent >= 90% AND checklist >= 60%
        C. [NEW] 硬收斂: Turn >= 10 且存在 [已驗證] 驅動因子 (有 r > 0.3 等證據)
        D. [NEW] 操作建議守門: 若為優化分析但未執行過 actionable 工具, 抑制硬收斂
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

        # --- Signal 4: Hard Convergence (Code-Level Enforcement) ---
        # If Turn >= 5 and we have verified drivers with statistical evidence,
        # force FINISH regardless of LLM's intent_coverage assessment.
        hard_converged = False
        turn_count = state.step_count  # current turn number
        if turn_count >= 10:
            # [FIX] 檢查是否已執行過 actionable 工具 (操作建議類)
            actionable_tools = {
                "performance_segmentation",
                "generate_operating_window",
                "multi_objective_analysis",
                "operating_window",
            }
            used_tools_set = set(t.split("::")[0] for t in state.used_tools_history)
            has_actionable = bool(used_tools_set & actionable_tools)

            # Collect ALL findings across all turns
            all_findings = list(current_findings)
            for step in state.history:
                if hasattr(step, "evidence") and isinstance(step.evidence, dict):
                    rpt = step.evidence.get("analysis_report")
                    if rpt and hasattr(rpt, "key_findings"):
                        all_findings.extend(rpt.key_findings)
                if hasattr(step, "conclusion"):
                    all_findings.append(step.conclusion)

            # Count verified findings with statistical evidence
            verified_with_evidence = 0
            for f in all_findings:
                if "[已驗證]" in f:
                    # Check for actual statistical evidence (not just Z-Score)
                    has_correlation = bool(re.search(r"r[=＝]\s*-?0\.\d+", f))
                    has_importance = bool(re.search(r"importance[=＝]\s*0\.\d+", f))
                    has_causation = (
                        "因果" in f or "causal" in f.lower() or "驅動因子" in f
                    )
                    has_control_loop = "Harris" in f or "控制迴路" in f
                    if (
                        has_correlation
                        or has_importance
                        or has_causation
                        or has_control_loop
                    ):
                        verified_with_evidence += 1

            if verified_with_evidence >= 3:
                # [FIX] 如果是優化分析但還沒跑過 actionable 工具, 不觸發硬收斂
                if not has_actionable and turn_count < 15:
                    print(
                        f"[Convergence] HARD CONVERGENCE SUPPRESSED: Turn={turn_count}, "
                        f"verified={verified_with_evidence} but no actionable tools used yet. "
                        f"Allowing more turns for operating recommendations."
                    )
                else:
                    hard_converged = True
                    print(
                        f"[Convergence] HARD CONVERGENCE: Turn={turn_count}, "
                        f"verified_with_evidence={verified_with_evidence} -> FORCE FINISH"
                    )

        print(
            f"[Convergence] novelty={novelty_ratio:.0%}(sat={novelty_saturated}) | "
            f"intent={intent_coverage}%(sat={intent_satisfied}) | "
            f"checklist={checklist_ratio:.0%}(sat={checklist_satisfied}) | "
            f"hard={hard_converged}(turn={turn_count})"
        )

        # Signal 4: Hard convergence override
        if hard_converged:
            return True

        # --- Signal 5: Consecutive Zero Findings Early Stop ---
        # 連續 2 個 Turn 零發現 + Turn >= 4 → 強制 FINISH
        if turn_count >= 4 and len(current_findings) == 0:
            consecutive_zero = 1  # current turn has 0
            for step in reversed(state.history[-3:]):
                if hasattr(step, "analysis_report") and step.analysis_report:
                    if len(step.analysis_report.key_findings) == 0:
                        consecutive_zero += 1
                    else:
                        break
                else:
                    break
            if consecutive_zero >= 2:
                print(
                    f"[Convergence] CONSECUTIVE ZERO FINDINGS: "
                    f"{consecutive_zero} turns with 0 findings (turn={turn_count}) -> FORCE FINISH"
                )
                return True

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

        # [SCENE TARGET] 注入當前場景目標, 約束 Synthesizer 只報告相關發現
        scene_queue = getattr(state, "scene_queue", [])
        scene_idx = getattr(state, "current_scene_index", -1)
        if scene_queue and 0 <= scene_idx < len(scene_queue):
            _active_scene = scene_queue[scene_idx]
            if _active_scene.status == "ACTIVE" and _active_scene.targets:
                _scene_targets_str = ", ".join(_active_scene.targets[:5])
                ctx += (
                    f"\n=== 當前調查場景 [CRITICAL] ===\n"
                    f"場景: {_active_scene.scene_id} - {_active_scene.label}\n"
                    f"目標參數: {_scene_targets_str}\n"
                    f"[ABSOLUTE RULE] 你的 key_findings 必須只報告與上述目標參數直接相關的發現。\n"
                    f"如果工具回傳了其他參數 (如 FORMULA-DCS_A760) 的異常, \n"
                    f"但它不在本場景的目標參數中, 則禁止列入 key_findings。\n"
                    f"相關性分析的結果可以報告 (因為它顯示了目標參數與其他參數的關聯), \n"
                    f"但必須以目標參數為主語 (如「{_active_scene.targets[0]} 與 X 的相關性為 r=0.5」)。\n"
                )

        # [GUARDRAIL] 注入已執行工具清單, 防止 Synthesizer 誤報已有工具為 missing
        if hasattr(state, "used_tools_history") and state.used_tools_history:
            executed_tools = set()
            for pair in state.used_tools_history:
                tool_name = pair.split("::")[0] if "::" in pair else pair
                executed_tools.add(tool_name)
            ctx += f"\n=== 已執行過的工具 (不可報告為 missing) ===\n"
            ctx += f"{', '.join(sorted(executed_tools))}\n"
            ctx += "[RULE] 以上工具系統已支援且已成功使用, 禁止在 analysis_gaps 中報告為缺失!\n"

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

        # [NEW] Add Historical Findings (事件式格式)
        from backend.services.analysis.knowledge_utils import get_summary as _get_sum

        _raw_summary = _get_sum(state.current_knowledge)
        if _raw_summary:
            formatted = self._format_rolling_summary(_raw_summary)
            if formatted:
                ctx += "\n=== HISTORICAL FINDINGS (事件索引, 禁止重複) ===\n"
                ctx += f"{formatted}\n"
                ctx += "[IMPORTANT] 以上按事件分組。你的 key_findings 應只包含本次 Turn 的新發現!\n"

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

        # ============================================================
        # [T2 交叉比對] 程式化掃描本 Turn 工具結果, 標記 T2 參數的驗證狀態
        # ============================================================
        t2_params = set()  # T2 top_contributors 中的參數名
        validated_params = {}  # {param: "status_msg"}
        validated_tools = set()  # 本 Turn 中有驗證能力的工具

        # 從歷史 discovered_sites 中提取 T2 標記的參數 (支援跨 Turn)
        if hasattr(state, "discovered_sites") and state.discovered_sites:
            for site in state.discovered_sites:
                desc = getattr(site, "description", "") or ""
                if "T2" in desc or "t2" in desc or "Hotelling" in desc:
                    param_name = getattr(site, "parameter", "")
                    if param_name:
                        t2_params.add(param_name)

        for ev in evidences:
            if ev.status != "SUCCESS" or not isinstance(ev.result, dict):
                continue

            # 收集 T2 標記的參數
            if ev.tool_name in ("hotelling_t2_analysis",):
                for zone in ev.result.get("anomaly_zones", []):
                    for c in zone.get("top_contributors", []):
                        if isinstance(c, dict) and c.get("parameter"):
                            t2_params.add(c["parameter"])
                for c in ev.result.get("top_3_contributors", []):
                    if isinstance(c, dict) and c.get("parameter"):
                        t2_params.add(c["parameter"])

            # 收集驗證工具的結果
            if ev.tool_name in ("classify_anomaly_type",):
                param = ev.result.get("parameter", "")
                total_regions = ev.result.get("total_anomaly_regions", -1)
                validated_tools.add("classify_anomaly_type")
                if param:
                    if total_regions == 0:
                        validated_params[param] = (
                            f"[已否定] classify_anomaly_type: No anomaly detected"
                        )
                    else:
                        types = ev.result.get("type_summary", {})
                        validated_params[param] = (
                            f"[已確認] classify_anomaly_type: {types}"
                        )

            if ev.tool_name in ("distribution_shift_analysis",):
                param = ev.result.get("parameter", "")
                validated_tools.add("distribution_shift_analysis")
                if param:
                    is_significant = ev.result.get("is_significant_shift", False)
                    wd = ev.result.get("wasserstein_distance", 0)
                    if not is_significant:
                        old = validated_params.get(param, "")
                        validated_params[param] = (
                            old
                            + f" [已否定] distribution_shift: No Significant Shift (WD={wd})"
                        ).strip()
                    else:
                        old = validated_params.get(param, "")
                        validated_params[param] = (
                            old + f" [已確認] distribution_shift: Significant (WD={wd})"
                        ).strip()

            if ev.tool_name in ("draw_trend",):
                param = ev.result.get("parameter", "")
                validated_tools.add("draw_trend")
                if param and param not in validated_params:
                    validated_params[param] = "[已驗證-視覺] draw_trend 已繪製趨勢圖"

        # 如果有 T2 參數, 注入交叉比對表
        if t2_params:
            ctx += "\n=== T2 交叉比對結果 [MANDATORY - 必須遵守] ===\n"
            ctx += "以下為程式化比對結果，Synthesizer 必須嚴格遵守:\n"
            for param in sorted(t2_params):
                if param in validated_params:
                    status = validated_params[param]
                    ctx += f"  - {param}: {status}\n"
                    if "[已否定]" in status:
                        ctx += f"    → 禁止在結論中宣稱 {param} 為異常主因\n"
                else:
                    ctx += f"  - {param}: [未驗證] 本 Turn 無後續工具對此參數進行個別驗證\n"
                    ctx += f"    → 禁止在結論中宣稱 {param} 為異常主因\n"
            ctx += "[ABSOLUTE RULE] 只有標記為 [已確認] 的參數才能出現在結論的主因列表中!\n"
            ctx += "[ABSOLUTE RULE] [已否定] 和 [未驗證] 的參數禁止作為主因寫入結論!\n"

        ctx += "\n=== CURRENT TURN RESULTS ===\n"
        for target, items in by_target.items():
            ctx += f"\n[Target: {target}]\n"
            for exp, ev in items:
                objective = exp.objective if exp else "Unknown Intent"
                ctx += f"  - Intent: {objective}\n"
                ctx += f"  - Tool: {ev.tool_name}\n"

                # [NEW] Smart Evidence Extraction (模組化)
                key_metrics = self._extract_key_metrics(ev.result)
                if isinstance(key_metrics, dict) and key_metrics:
                    for mod_key, items in key_metrics.items():
                        label = self._MODULE_LABELS.get(mod_key, mod_key)
                        for item in items:
                            ctx += f"  - [{label}] {item}\n"
                else:
                    ctx += f"  - Key Metrics: {key_metrics}\n"
                ctx += f"  - Observation: {ev.observation}\n"

        # [FIX] Context size guard: 避免超大數據集 (343+ columns) 產生過長 context 導致 LLM 無法提取 findings
        MAX_CTX_LEN = 12000
        if len(ctx) > MAX_CTX_LEN:
            # 保留頭部 (系統資訊 + checklist) 和尾部 (當前 Turn 結果)
            current_turn_marker = "=== CURRENT TURN RESULTS ==="
            marker_pos = ctx.find(current_turn_marker)
            if marker_pos > 0:
                header = ctx[: min(2000, marker_pos)]
                turn_results = ctx[marker_pos:]
                # 截斷 turn_results 如果仍然太長
                if len(turn_results) > MAX_CTX_LEN - 2100:
                    turn_results = (
                        turn_results[: MAX_CTX_LEN - 2100]
                        + "\n... (已截斷，僅顯示最關鍵結果)\n"
                    )
                ctx = header + "\n... (歷史部分已省略) ...\n\n" + turn_results
            else:
                ctx = ctx[:MAX_CTX_LEN] + "\n... (已截斷)\n"

        return ctx

    # === 模組分類常量 ===
    _MODULE_LABELS = {
        "anomaly_scan": "異常掃描",
        "parameter_stats": "參數統計",
        "contribution": "貢獻分析",
        "correlation": "相關與因果",
        "pattern": "時序模式",
        "comparison": "比較分析",
        "recommendation": "優化建議",
        "classification": "分類標注",
    }

    def _extract_key_metrics(self, result: any) -> dict:
        """
        從工具結果中提取關鍵指標 (模組化版本)
        回傳 Dict[str, List[str]], key 為模組名稱, value 為該模組的 metric 列表
        """
        if not isinstance(result, dict):
            return {"parameter_stats": [str(result)[:500]]}

        modules = {k: [] for k in self._MODULE_LABELS}

        # ============================================================
        # [參數統計] Z-Score, 分佈, 離群值
        # ============================================================
        if "stats" in result and isinstance(result["stats"], dict):
            max_z = result["stats"].get("max_z")
            if max_z and max_z > 3:
                severity = "極端異常" if max_z > 6 else "顯著異常"
                modules["parameter_stats"].append(f"Max Z={max_z:.2f} ({severity})")
            max_sigma = result["stats"].get("max_sigma")
            min_sigma = result["stats"].get("min_sigma")
            if max_sigma and abs(max_sigma) > 3:
                modules["parameter_stats"].append(f"Max Sigma={max_sigma:.2f}")
            if min_sigma and abs(min_sigma) > 3:
                modules["parameter_stats"].append(f"Min Sigma={min_sigma:.2f}")

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
                    modules["parameter_stats"].append(
                        f"Top異常: {', '.join(param_details)}"
                    )

        if "distribution_type" in result:
            dtype = result.get("distribution_type", "?")
            skew = result.get("skewness", 0)
            kurt = result.get("kurtosis", 0)
            std = result.get("std", 0)
            mean = result.get("mean", 0)
            modules["parameter_stats"].append(
                f"分佈: {dtype} (mean={mean:.4f}, std={std:.4f}, skew={skew:.2f}, kurt={kurt:.2f})"
            )

        # [NEW] most_drifting from cv_ranking — 漂移排名
        if "most_drifting" in result and isinstance(result["most_drifting"], list):
            drift_items = [
                d
                for d in result["most_drifting"][:5]
                if isinstance(d, dict) and d.get("drift_total_sigma", 0) > 1.5
            ]
            if drift_items:
                drift_strs = [
                    f"{d['parameter']}(drift={d['drift_total_sigma']}σ, {d['drift_grade']})"
                    for d in drift_items
                ]
                modules["parameter_stats"].append(f"Top漂移: {', '.join(drift_strs)}")

        # ============================================================
        # [貢獻分析] T2, Feature Importance, PCA
        # ============================================================
        # --- Hotelling T2 核心結果 ---
        if "n_components_used" in result and "t2_threshold" in result:
            n_comp = result.get("n_components_used", 0)
            var_exp = result.get("variance_explained", "?")
            threshold = result.get("t2_threshold", 0)
            modules["contribution"].append(
                f"PCA-T2: {n_comp} 主成分, 解釋力 {var_exp}, 閾值={threshold}"
            )

        if "anomaly_zones" in result:
            zones = result["anomaly_zones"]
            if isinstance(zones, list) and zones:
                # 按 t2_max 排序，取前 5 個最嚴重的區段
                sorted_zones = sorted(
                    zones, key=lambda z: z.get("t2_max", 0), reverse=True
                )
                zone_strs = []
                for z in sorted_zones[:5]:
                    zr = z.get("zone_range", "?")
                    t2_max = z.get("t2_max", 0)
                    t2_mean = z.get("t2_mean", 0)
                    length = z.get("length", 0)
                    # 提取 top contributors 的參數名
                    top_contribs = z.get("top_contributors", [])
                    contrib_names = [
                        c.get("parameter", "?")
                        for c in top_contribs[:3]
                        if isinstance(c, dict)
                    ]
                    contrib_str = ", ".join(contrib_names) if contrib_names else "?"
                    zone_strs.append(
                        f"{zr}(T2_max={t2_max:.1f}, mean={t2_mean:.1f}, "
                        f"{length}筆, T2貢獻排名(待驗證): {contrib_str})"
                    )
                modules["contribution"].append(
                    f"T2 異常區段 ({len(zones)}個): {'; '.join(zone_strs)}"
                )

        if "anomaly_indices" in result:
            indices = result["anomaly_indices"][:3]
            modules["contribution"].append(f"Anomaly Rows: {indices}")

        if "top_3_contributors" in result:
            contributors = result["top_3_contributors"]
            if isinstance(contributors, list):
                contrib_str = ", ".join(
                    f"{c.get('parameter', '?')}({c.get('contribution', 0):.1f}%)"
                    for c in contributors[:3]
                    if isinstance(c, dict)
                )
                if contrib_str:
                    modules["contribution"].append(f"T2 Contributors: {contrib_str}")

        if "top_features" in result:
            top_f = result["top_features"]
            if isinstance(top_f, list) and top_f:
                fi_strs = []
                for f in top_f[:5]:
                    if isinstance(f, dict):
                        pname = f.get("parameter", "?")
                        imp = f.get("importance_score", 0)
                        corr = f.get("correlation", 0)
                        role = f.get("role", "")
                        fi_strs.append(f"{pname}(imp={imp:.4f}, r={corr:.2f}, {role})")
                modules["contribution"].append(f"特徵重要性: {', '.join(fi_strs)}")
            model_used = result.get("model_used", "")
            if model_used:
                modules["contribution"].append(f"模型: {model_used}")

        # ============================================================
        # [相關與因果] 相關性, 交叉相關, 因果分析
        # ============================================================
        if "correlation" in result:
            corr = result["correlation"]
            if abs(corr) > 0.5:
                strength = "強" if abs(corr) > 0.7 else "中等"
                modules["correlation"].append(f"Corr={corr:.2f} ({strength})")

        if "best_lag" in result and "peak_correlation" in result:
            lag = result["best_lag"]
            corr = result["peak_correlation"]
            interp = result.get("interpretation", {})
            direction = interp.get("causality_direction", "?")
            explanation = interp.get("explanation", "")[:200]
            modules["correlation"].append(
                f"交叉相關: Lag={lag}, Corr={corr:.3f}, 方向={direction}"
            )
            if explanation:
                modules["correlation"].append(f"因果解讀: {explanation}")

        if "top_correlations" in result:
            corrs = result["top_correlations"]
            if isinstance(corrs, list) and corrs:
                top_strs = []
                for c in corrs[:5]:
                    if isinstance(c, dict):
                        pname = c.get("parameter", "?")
                        r_val = c.get("correlation", 0)
                        strength = (
                            "極強"
                            if abs(r_val) > 0.9
                            else ("強" if abs(r_val) > 0.7 else "中等")
                        )
                        top_strs.append(f"{pname}(r={r_val:.3f}, {strength})")
                modules["correlation"].append(f"Top相關性: {', '.join(top_strs)}")

        # ============================================================
        # [時序模式] 頻域, 時頻, 趨勢, 控制迴路
        # ============================================================
        if "full_spectrum" in result:
            spec = result["full_spectrum"]
            entropy = spec.get("spectral_entropy", 0)
            dom_period = spec.get("dominant_period", 0)
            modules["pattern"].append(f"頻域: 熵={entropy:.2f}, 主頻週期={dom_period}")
            comparison = result.get("comparison")
            if comparison and isinstance(comparison, dict):
                for interp in comparison.get("interpretation", [])[:2]:
                    modules["pattern"].append(f"頻域比較: {interp[:150]}")
            for anomaly in result.get("spectral_anomalies", [])[:2]:
                modules["pattern"].append(f"頻譜異常: {anomaly[:150]}")

        if "harris_index" in result:
            harris = result["harris_index"]
            grade = harris.get("grade", "?")
            idx = harris.get("index", 0)
            modules["pattern"].append(f"Harris Index: {idx:.2f} ({grade})")
        if "oscillation_assessment" in result:
            osc = result["oscillation_assessment"]
            status = osc.get("status", "?")
            desc = osc.get("description", "")[:150]
            modules["pattern"].append(f"震盪評估: {status} - {desc}")
        if "engineering_assessment" in result:
            modules["pattern"].append(
                f"控制迴路總評: {result['engineering_assessment'][:200]}"
            )

        if "trend" in result and isinstance(result["trend"], dict):
            trend = result["trend"]
            slope = trend.get("slope", 0)
            drift = trend.get("drift_per_10_points", 0)
            direction = trend.get("direction", "?")
            modules["pattern"].append(
                f"趨勢: slope={slope:.6f}, drift/10pts={drift:.4f}, direction={direction}"
            )

        # ============================================================
        # [異常掃描] scan_anomaly_segments, zone_diagnosis
        # ============================================================
        if "total_anomaly_segments" in result and "worst_parameters" in result:
            total_segs = result.get("total_anomaly_segments", 0)
            total_cols = result.get("total_columns_scanned", 0)
            modules["anomaly_scan"].append(
                f"全域掃描: {total_cols}個欄位, {total_segs}個異常區段"
            )
            worst = result.get("worst_parameters", [])
            if worst:
                worst_strs = [
                    f"{w.get('parameter', '?')}({w.get('anomaly_count', 0)}次)"
                    for w in worst[:5]
                ]
                modules["anomaly_scan"].append(f"最嚴重參數: {', '.join(worst_strs)}")
            type_dist = result.get("anomaly_type_distribution", {})
            if type_dist:
                dist_strs = [f"{k}={v}" for k, v in list(type_dist.items())[:5]]
                modules["anomaly_scan"].append(f"異常類型分佈: {', '.join(dist_strs)}")
            consensus = result.get("consensus_zones", [])
            if consensus:
                modules["anomaly_scan"].append(
                    f"共識異常區: {len(consensus)}個 (多演算法一致認定)"
                )
            method_cov = result.get("detection_method_coverage", {})
            if method_cov:
                cov_strs = [f"{k}={v}" for k, v in method_cov.items()]
                modules["anomaly_scan"].append(f"偵測方法覆蓋: {', '.join(cov_strs)}")
            eng_summary = result.get("engineering_summary", "")
            if eng_summary:
                modules["anomaly_scan"].append(f"工程摘要: {str(eng_summary)[:300]}")

        if "event_zones" in result and "zones_analyzed" in result:
            zones = result.get("event_zones", [])
            overall = result.get("overall_interpretation", "")
            if overall:
                modules["anomaly_scan"].append(f"Zone診斷: {overall}")
            for ez in zones[:3]:
                zone_range = ez.get("zone_range", "?")
                n_params = ez.get("affected_params_count", 0)
                severity = ez.get("max_severity", 0)
                interp = ez.get("interpretation", "")
                if interp:
                    modules["anomaly_scan"].append(
                        f"[EventZone] {zone_range} "
                        f"({n_params}參數, 嚴重度{severity}): {interp}"
                    )
                contributors = ez.get("top_contributors", [])
                if contributors:
                    contrib_strs = [
                        f"{c['parameter']}(貢獻={c['contribution']:.2f})"
                        for c in contributors[:3]
                    ]
                    modules["anomaly_scan"].append(
                        f"  T2貢獻排名: {', '.join(contrib_strs)}"
                    )

        # ============================================================
        # [比較分析] 區段比較, 好壞批次, 交互效應
        # ============================================================
        if "top_discriminating_parameters" in result:
            _perf_target = result.get("target", "?")
            _interp = result.get("interpretation", "")
            if _interp:
                modules["comparison"].append(_interp)
            top_disc = result["top_discriminating_parameters"]
            if isinstance(top_disc, list) and top_disc:
                disc_strs = []
                for d in top_disc[:5]:
                    if isinstance(d, dict):
                        pname = d.get("parameter", "?")
                        es = d.get("effect_size", 0)
                        gm = d.get("good_batch_mean", 0)
                        bm = d.get("bad_batch_mean", 0)
                        direction = d.get("suggested_direction", "?")
                        disc_strs.append(
                            f"{pname}(effect={es:.2f}, good={gm:.4f}, bad={bm:.4f}, {direction})"
                        )
                modules["comparison"].append(
                    f"好壞批次差異Top(分組依據={_perf_target}): {', '.join(disc_strs)}"
                )
            ts = result.get("target_stats", {})
            if ts:
                modules["comparison"].append(
                    f"{_perf_target} 目標好批={ts.get('good_mean', 0):.4f}, 壞批={ts.get('bad_mean', 0):.4f}"
                )

        if "segment_comparison" in result or "top_diff_features" in result:
            top_diff = result.get(
                "top_diff_features", result.get("segment_comparison", [])
            )
            if isinstance(top_diff, list) and top_diff:
                diff_strs = []
                for d in top_diff[:5]:
                    if isinstance(d, dict):
                        pname = d.get("parameter", d.get("feature", "?"))
                        z_diff = d.get("z_score_diff", d.get("difference", 0))
                        diff_strs.append(f"{pname}(z_diff={z_diff:.2f})")
                if diff_strs:
                    modules["comparison"].append(f"區段差異Top: {', '.join(diff_strs)}")

        if "interaction_p_value" in result or "interaction_significant" in result:
            p_val = result.get("interaction_p_value", 0)
            sig = result.get("interaction_significant", False)
            effect = result.get("interaction_effect_size", 0)
            modules["comparison"].append(
                f"交互效應: p={p_val:.4f}, significant={sig}, effect_size={effect:.4f}"
            )

        if "pdp_results" in result:
            pdp = result["pdp_results"]
            if isinstance(pdp, list):
                for p in pdp[:3]:
                    if isinstance(p, dict):
                        feat = p.get("feature", "?")
                        effect = p.get("effect_range", p.get("range", 0))
                        modules["comparison"].append(
                            f"PDP {feat}: effect_range={effect}"
                        )

        # ============================================================
        # [優化建議] SOP, 多目標
        # ============================================================
        if "sop_recommendations" in result:
            sop = result["sop_recommendations"]
            if isinstance(sop, list) and sop:
                sop_strs = []
                for s in sop[:3]:
                    if isinstance(s, dict):
                        pname = s.get("parameter", "?")
                        tgt = s.get("suggested_target", 0)
                        adj = s.get("adjustment_direction", "?")
                        sop_strs.append(f"{pname}(target={tgt:.4f}, {adj})")
                modules["recommendation"].append(f"SOP建議: {', '.join(sop_strs)}")

        if "pareto_front" in result or "trade_off_analysis" in result:
            pareto = result.get("pareto_front", [])
            if isinstance(pareto, list) and pareto:
                modules["recommendation"].append(
                    f"Pareto Front: {len(pareto)} solutions"
                )
            trade = result.get("trade_off_analysis", {})
            if isinstance(trade, dict):
                conflict = trade.get("conflict_score", 0)
                modules["recommendation"].append(f"目標衝突度: {conflict}")

        # ============================================================
        # [分類標注] anomaly classification, regime detection
        # ============================================================
        if "classifications" in result and isinstance(result["classifications"], list):
            for c in result["classifications"][:3]:
                if isinstance(c, dict):
                    atype = c.get("type", "UNKNOWN")
                    conf = c.get("confidence", 0)
                    rng = c.get("range", "?")
                    desc = c.get("description", "")[:100]
                    modules["classification"].append(
                        f"異常分類[{rng}]: {atype} (信心{conf:.0%}) - {desc}"
                    )
            hints = result.get("engineering_hints", [])
            for h in hints[:2]:
                modules["classification"].append(f"工程建議: {h[:150]}")

        # 移除空模組
        return {k: v for k, v in modules.items() if v}
