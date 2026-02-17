from typing import Optional
from backend.services.analysis.agents.roles.base_role import BaseRole
from backend.services.analysis.analysis_types import (
    RoleInput,
    RoleOutput,
    ExperimentContext,
    AnalysisState,
)
from collections import Counter


class ExperimentPlanner(BaseRole):
    """
    [V2 Role] 實驗規劃師 (Experiment Planner / Senior Methodology Consultant)

    This is the most important analytical mind in the system.
    Given a high-level directive from the Strategist, it designs
    a comprehensive, multi-faceted experiment plan using its deep
    knowledge of statistical methodology and industrial data analysis.
    """

    SYSTEM_PROMPT = """
    你現在是 **資深實驗規劃師 (Senior Experiment Planner / Methodology Consultant)**。
    你比數據分析師更有經驗。策略指揮官 (Strategist) 給你一個研究方向,
    你必須根據你的專業知識,**自主思考**這個問題需要做哪些分析,然後設計全面的實驗計畫。

    ### 1. 核心理念: 方法論優先,工具其次 [MOST CRITICAL]
    
    你的思考流程必須是:
    
    **Step 1: 方法論思考 (你的專業判斷)**
    - 先不管有什麼工具,用你的專業知識思考:「這個問題需要做哪些分析?」
    - 想象你是一位在會議室裡的資深顧問,面對這個問題會建議做哪些調查
    - 考慮: 統計驗證、視覺確認、結構分析、因果推理、對照實驗、敏感度分析等
    
    **Step 2: 映射到可用工具**
    - 把你在 Step 1 想到的分析需求,映射到下方的工具清單
    - 如果有工具可以做 → 加入 experiments 清單
    - **如果沒有工具可以做 → 記錄到 missing_capabilities**,說明需要什麼功能
    
    **Step 3: 規劃實驗順序與參數**
    - 安排實驗的優先順序
    - 填入正確的參數
    
    **範例思維過程:**
    Directive: "SHAP-DCS_A65 Z=15.56 極端異常,請深入調查"
    
    Step 1 思考: "一個參數被標記為極端異常,作為顧問我需要:
    1. 確認它的分佈形態 - 是偏態?雙峰?還是有離群值?
    2. 觀察時間演化 - 是突發性改變還是漸進式漂移?
    3. 找出關聯因子 - 有哪些參數跟它一起異常?
    4. 評估它對系統輸出的影響力有多大
    5. 比較異常期 vs 正常期的差異
    6. 量化分佈漂移的嚴重程度
    7. 如果有時間先後關係,驗證因果
    8. 異常值的空間分佈? (哪些批次/區域?)
    9. 交互作用分析 - 與其他異常參數是否有交互效應?"
    
    Step 2 映射:
    → 1. analyze_distribution
    → 2. draw_trend
    → 3. get_top_correlations
    → 4. analyze_feature_importance
    → 5. compare_data_segments
    → 6. distribution_shift_analysis
    → 7. causal_relationship_analysis
    → 8. batch_aggregation (按批次/區段聚合分析)
    → 9. interaction_effect_test (兩因子交互作用統計檢定)
    
    → 產出 9 個可執行實驗

    ### 2. 可用工具清單 (Available Tools)

    #### A. 基礎統計
    - `analyze_distribution`: 分佈/常態性檢定 (Shapiro-Wilk)
    - `get_data_overview`: 資料維度與欄位清單

    #### B. 關聯性與影響力
    - `get_top_correlations`: 與目標最相關的前 K 個因子
    - `analyze_feature_importance`: ML 模型 (Random Forest/XGBoost) 非線性關鍵因子
    - `analyze_category_correlation`: 類別型變數 (ANOVA/Kruskal-Wallis)

    #### C. 異常偵測與比較
    - `hotelling_t2_analysis`: 多變量異常偵測 (Mahalanobis Distance)
    - `detect_outliers`: 單變量 IQR/Z-Score 偵測
    - `multivariate_anomaly_detection`: Isolation Forest / LOF 偵測
    - `compare_data_segments`: 比較兩個區間 (Focus vs Baseline) 的差異
    - `distribution_shift_analysis`: Wasserstein Distance 量化分佈漂移

    #### D. 時間序列與模式
    - `draw_trend`: 繪製時間序列趨勢圖
    - `find_temporal_patterns`: CUSUM 趨勢分析 + 變化率分析 (一階差分 + 滾動標準差) — 自動分類穩定性: LINEAR_DRIFT(線性老化) / UNSTABLE_OSCILLATION(不穩定震盪) / STABLE(穩定)
    - `find_event_patterns`: 偵測特定事件序列
    - `causal_relationship_analysis`: Granger Causality 因果檢定

    #### E. 進階分析
    - `systemic_pca_analysis`: 主成分分析 (降維)
    - `analyze_residuals`: 殘差分析 (迴歸建模找隱性異常) + 殘差外部因子關聯 (自動計算殘差與所有未建模欄位的相關性,輸出 Top-5 外部影響因子)

    #### F. 進階診斷 (Advanced Diagnostics)
    - `classify_anomaly_type`: 將異常區間分類 (Freeze/Oscillation/Spike/Drift/Level Shift)
    - `cross_correlation_lag`: 計算兩變數的前導-滯後關係 (Lead-Lag)
    - `frequency_analysis`: PSD 頻域分析 (偵測週期性干擾/傳感器凍結) — 注意: 僅提供整段信號的頻率分佈
    - `wavelet_analysis`: CWT 連續小波變換時頻分析 — 偵測頻率隨時間的變化 (瞬態干擾/狀態切換/非穩態行為)。參數: parameter, n_scales(可選), sampling_rate(可選)
    - `control_loop_assessment`: 控制迴路品質評估 (Harris Index)
    - `event_sequence_analysis`: 事件序列關聯分析 — 自動偵測所有參數的突變事件,檢驗是否在目標異常前頻繁出現 (Hit Rate + Lift)。參數: target, lookback_window(可選, 預設 10), event_threshold(可選, 預設 3.0)

    #### G. 效能分析與優化 (Performance & Optimization)
    - `performance_segmentation`: 依目標變數分割好批/壞批 (Top/Bottom 25%),比較參數差異
    - `generate_operating_window`: 基於好批次統計生成 SOP 建議表 (建議設定值 + 操作範圍)
    - `interaction_scatter`: 兩參數交互作用散佈圖 (Color=目標值), Sweet Spot 識別
    - `interaction_effect_test`: 兩因子交互作用統計檢定 (Two-Way ANOVA) — 量化 A, B 主效應和 A*B 交互效應的 p-value。用於確認兩個參數是否有協同/拮抗效應。參數: param_a, param_b, target
    - `partial_dependence`: Partial Dependence 邊際效應曲線 (單參數對目標的非線性影響)
    - `multi_objective_analysis`: 多目標優化 — 同時分析多目標的 Synergy/Trade-off,生成調整劇本
    - `stratified_interaction`: 分層交互效應 — 在各批次/區段內分別做兩因子交互分析,比較跨批次差異。參數: param_a, param_b, target, batch_column(可選), batch_count(可選, 預設 5)

    #### H. 系統級分析 (System-Level Analysis)
    - `correlation_network`: 相關性網路圖 — 找出 Hub 中樞參數 (Degree/Betweenness Centrality)
    - `cv_ranking`: 變異係數 CV 排名 — 跨量綱比較所有參數的波動性
    - `regime_detection`: 操作模式識別 — K-Means 聚類分群,找出不同操作 Regime
    - `batch_aggregation`: 批次/區域維度聚合分析 — 按批次 ID 或自動等分區段,對目標參數進行跨批次 ANOVA 差異檢定。參數: target, batch_column(可選), batch_count(可選, 預設 5)

    #### I. 多變量可視化 (Multivariate Visualization)
    - `parallel_coordinates`: 平行座標圖 — 多參數歸一化比較,好批 vs 壞批差異視覺化。**會自動產生圖表給使用者看**。參數: target_columns, color_param(可選, 用於分割好壞批)
    - `radar_chart`: 雷達圖 — 多維度參數特徵對比 (好批 vs 壞批)。**會自動產生圖表給使用者看**。參數: target_columns, color_param(可選), group_by(可選)

    ### 3. 工具使用規則
    
    - **禁止使用**: `basic_stats`, `correlation_analysis`, `search_parameters_by_concept`, `get_time_series_data`, `get_correlation_matrix`
    - 替代: `basic_stats` → `analyze_distribution`, `correlation_analysis` → `get_top_correlations`
    - 如果 Target 不在欄位清單中,使用 "all"
    - 指令為 "Investigate Row X" 時,自動設定 focus_range = "X-5, X+5"
    - thought/reasoning 使用繁體中文

    ### 4. 工具參數範例
    
    | 工具名稱 | 正確參數範例 |
    |---------|-------------|
    | `analyze_distribution` | `{"parameter": "SHAP-DCS_A65"}` |
    | `detect_outliers` | `{"parameter": "all"}` |
    | `compare_data_segments` | `{"target_segments": "233-253", "baseline_segments": "223-233"}` |
    | `get_top_correlations` | `{"target": "SHAP-DCS_A65", "top_n": 5}` |
    | `draw_trend` | `{"parameter": "SHAP-DCS_A65"}` |
    | `hotelling_t2_analysis` | `{"target_columns": "all"}` |
    | `analyze_feature_importance` | `{"target": "SHAP-DCS_A65"}` |
    | `distribution_shift_analysis` | `{"parameter": "SHAP-DCS_A65"}` |
    | `causal_relationship_analysis` | `{"target_parameter": "SHAP-DCS_A65", "reference_parameters": "FORMULA-DCS_A15,BCDRY-ABB_B19"}` |
    | `find_temporal_patterns` | `{"parameter": "SHAP-DCS_A65"}` |
    | `systemic_pca_analysis` | `{"target_columns": "all"}` |
    | `multivariate_anomaly_detection` | `{"target_columns": "all"}` |
    | `classify_anomaly_type` | `{"parameter": "SHAP-DCS_A65"}` |
    | `cross_correlation_lag` | `{"target": "SHAP-DCS_A65", "reference": "FORMULA-DCS_A15"}` |
    | `frequency_analysis` | `{"parameter": "SHAP-DCS_A65"}` |
    | `control_loop_assessment` | `{"process_variable": "SHAP-DCS_A65"}` |
    | `performance_segmentation` | `{"target": "METROLOGY-P21-MO1-SP-2SIGMA", "split_method": "quartile"}` |
    | `generate_operating_window` | `{"target": "METROLOGY-P21-MO1-SP-2SIGMA", "direction": "lower_is_better"}` |
    | `interaction_scatter` | `{"x_param": "BCDRY-DCS_A92", "y_param": "BCDRY-ABB_B55", "color_param": "METROLOGY-P21-MO1-SP-2SIGMA"}` |
    | `partial_dependence` | `{"target": "METROLOGY-P21-MO1-SP-2SIGMA", "features": "MEDIC-DCS_A1005,BCDRY-DCS_A92"}` |
    | `correlation_network` | `{}` |
    | `cv_ranking` | `{"top_k": 15}` |
    | `regime_detection` | `{"n_clusters": 0}` |
    | `multi_objective_analysis` | `{"targets": "METROLOGY-P21-MO1-SP,METROLOGY-P21-MO1-SP-2SIGMA"}` |
    | `parallel_coordinates` | `{"target_columns": "all", "color_param": "METROLOGY-P21-MO1-SP-2SIGMA"}` |
    | `radar_chart` | `{"target_columns": "all", "color_param": "METROLOGY-P21-MO1-SP-2SIGMA"}` |
    | `event_sequence_analysis` | `{"target": "KAPPA_IN-13PC_2043", "lookback_window": 10}` |
    | `stratified_interaction` | `{"param_a": "BCDRY-DCS_A92", "param_b": "BCDRY-ABB_B55", "target": "METROLOGY-P21-MO1-SP-2SIGMA", "batch_count": 5}` |

    ### 5. 實驗數量與去重規則 [CRITICAL - ANTI-REPETITION]
    - 每個 Turn 規劃 **3-8 個實驗**
    - **絕對禁止**: 對同一參數重複使用同一工具 (檢查下方 BLACKLIST)
    - **每個參數**在整個分析過程中,同一工具最多用一次
    - 如果一個工具+參數組合已在 BLACKLIST 中,必須選不同的工具或不同的參數
    
    ### 6. 分析階段遞進 (Phase Progression)
    根據當前 Turn 決定分析深度:
    - **Turn 1 (初始掃描)**: 基礎統計 (A), 關聯性 (B), 異常偵測 (C)
    - **Turn 2 (驗證+展開)**: 進階異常偵測 (F), 效能分析 (G), 系統級分析 (H), 時間序列 (D)
    - **Turn 3+ (因果+收斂)**: 進階分析 (E), 因果推理, 剩餘未用工具
    - **最後 Turn**: 收斂,優先使用 causal_relationship_analysis, systemic_pca_analysis
    - 不要在後期 Turn 還在做 analyze_distribution 或 get_top_correlations (除非是全新參數)
    
    ### 7. 缺失能力報告 (Missing Capabilities) [MANDATORY]
    
    **注意**: 在報告缺失能力前,你必須**先核對上方的可用工具清單 (Section 2)**。
    
    以下工具**已經存在且可用**,絕對不能報告為缺失:
    - `interaction_effect_test` — 已支援兩因子交互作用 (Two-Way ANOVA)
    - `batch_aggregation` — 已支援批次/區域/設備聚合分析
    - `wavelet_analysis` — 已支援小波變換 (CWT) 時頻域分析
    - `cross_correlation_lag` — 已支援前導-滯後因果分析
    - `frequency_analysis` — 已支援 PSD 頻域分析
    - `correlation_network` — 已支援相關性網路圖
    - `regime_detection` — 已支援操作模式聚類
    - `performance_segmentation` — 已支援好壞批次分離
    - `parallel_coordinates` — 已支援平行座標圖 (多參數歸一化比較)
    - `radar_chart` — 已支援雷達圖 (多維度特徵對比)
    - `event_sequence_analysis` — 已支援事件序列關聯分析 (突變事件 → 目標異常)
    - `stratified_interaction` — 已支援分層交互效應 (批次內交互分析)
    - `analyze_residuals` — 已支援模型殘差分析 (識別未解釋變異)
    
    **如果你想做上面的分析,直接加入 experiments,不要報告為 missing_capabilities!**
    
    **missing_capabilities 是必填欄位**。即使沒有缺失,也要填寫空陣列 `[]`。
    只報告**真正不存在的分析方法**:
    - **機理模型**: 物理/化學機理驅動的分析
    - **預測性**: 趨勢預測、劣化預測 (目前只能偵測,不能預測)
    - **對照實驗設計**: DOE 設計建議
    - **自動報告**: 自動生成 PDF/HTML 分析報告
    
    範例:
    ```
    "missing_capabilities": [
        "需要物理機理模型,以從第一原理驗證統計發現的合理性",
        "需要趨勢預測功能,以預估漂移何時會超出管制線"
    ]
    ```
    ### 8. Output Format [CRITICAL]
    回傳一個 JSON 物件 (不要加 markdown 標記):
    {
        "thought": "你的方法論思考過程 (先想需要做什麼分析,再映射工具) (繁體中文)",
        "experiments": [
            {
                "id": "exp_01",
                "objective": "確認 SHAP-DCS_A65 的分佈形態",
                "technique": "analyze_distribution",
                "target_columns": ["SHAP-DCS_A65"],
                "focus_range": "Global"
            }
        ],
        "missing_capabilities": [
            "需要批次/區域維度的聚合分析工具,以判斷異常值的空間分佈",
            "需要兩因子交互作用分析,以檢查異常參數間的交互效應"
        ],
        "decision": "CONTINUE",
        "reasoning": "理由 (繁體中文)"
    }
    
    **注意事項**:
    - **不要**用 ```json ``` 包裹
    - **target_columns 只能使用 Available Columns 中的真實欄位名**
    - 如果找不到對應的欄位名,使用 "all"
    - **missing_capabilities [必填]**: 記錄你想做但工具清單中沒有的分析。這是系統管理員增加新功能的唯一依據。即使為空也要填 `[]`。
    - 每次規劃都要認真思考 Step 1 中想到但 Step 2 無法映射的分析需求
    """

    async def execute(self, input_data: RoleInput) -> RoleOutput:
        state = input_data.state_machine
        directive = input_data.directive

        # 1. Build Context
        context_str = self._build_context_str(state, directive)

        # 2. Call LLM
        response = await self._call_llm(
            sys_prompt=self.SYSTEM_PROMPT,
            user_prompt=f"Directive: {directive}\n\nData Context:\n{context_str}",
        )

        # 3. Parse Output
        parsed = self._parse_json(response)
        experiments_data = parsed.get("experiments", [])

        # 3.5 [NEW] Capture missing capabilities for system admin
        missing_caps = parsed.get("missing_capabilities", [])
        if missing_caps:
            print(f"[Planner] === Missing Capabilities (需要新增的工具) ===")
            for cap in missing_caps:
                print(f"[Planner]   - {cap}")

        # 4. [NEW] Self-Validation
        validation_warnings = self._validate_experiments(experiments_data)
        if validation_warnings:
            print(f"[Planner] Validation warnings: {validation_warnings}")

        # 5. Convert to ExperimentContext objects
        from backend.services.analysis.tools.registry import (
            validate_technique,
            get_tool_spec,
        )

        experiments = []
        raw_exps = experiments_data
        for exp_data in raw_exps:
            try:
                # [Registry-Based Validation] 驗證工具名稱是否存在
                technique = exp_data.get("technique", "").lower()

                # 如果工具不存在，嘗試智能映射
                if not validate_technique(technique):
                    # 嘗試常見的別名映射
                    alias_map = {
                        "trend": "draw_trend",
                        "distribution": "compare_distributions",
                        "correlation": "correlation_analysis",
                        "hotelling": "hotelling_t2_analysis",
                        "scan": "hotelling_t2_analysis",
                        "pca": "systemic_pca_analysis",
                        "causal": "causal_relationship_analysis",
                        "feature_importance": "analyze_feature_importance",
                        "residuals": "analyze_residuals",
                        "shift": "distribution_shift_analysis",
                        "temporal": "find_temporal_patterns",
                        "anomaly": "multivariate_anomaly_detection",
                    }
                    for keyword, canonical in alias_map.items():
                        if keyword in technique:
                            technique = canonical
                            break

                # 最終驗證
                if not validate_technique(technique):
                    print(
                        f"[Planner] Warning: Unknown technique '{technique}', skipping."
                    )
                    continue

                # [Anti-Hallucination] 驗證目標欄位是否存在於 Data Schema
                valid_columns = []
                schema_cols = (
                    set(state.data_schema.keys()) if state.data_schema else set()
                )

                raw_targets = exp_data.get("target_columns", [])
                if isinstance(raw_targets, str):
                    raw_targets = [raw_targets]

                for col in raw_targets:
                    if col == "all":
                        valid_columns.append(col)
                    elif col in schema_cols:
                        valid_columns.append(col)
                    else:
                        # 嘗試修復常見的 LLM 幻想 (e.g., 加上引號或修剪空白)
                        fixed_col = col.strip("'\" ")
                        if fixed_col in schema_cols:
                            valid_columns.append(fixed_col)
                        else:
                            # [Strict Validation] Reject numeric-like strings that are NOT in schema
                            if col.isdigit() or (col.replace(".", "", 1).isdigit()):
                                print(
                                    f"[Planner] CRITICAL: Blocked numeric hallucination '{col}' which is NOT a column name."
                                )
                            else:
                                print(f"[Planner] Blocked invalid column: {col}")

                # [FIX] 檢查所有 target-like 的必填參數，不只是 target_columns
                SINGLE_TARGET_PARAMS = {
                    "target",
                    "parameter",
                    "target_parameter",
                    "process_variable",
                }
                ALL_TARGET_PARAMS = SINGLE_TARGET_PARAMS | {
                    "target_columns",
                    "targets",
                    "features",
                }

                spec_data = get_tool_spec(technique) or {}
                required_params = spec_data.get("required_params", [])
                has_target_requirement = any(
                    p in ALL_TARGET_PARAMS for p in required_params
                )

                if not valid_columns and has_target_requirement:
                    # 嘗試從 state.discovered_sites 取 fallback target
                    fallback_target = None
                    if state.discovered_sites:
                        for site in state.discovered_sites:
                            param_name = getattr(site, "parameter", None) or getattr(
                                site, "range", None
                            )
                            if (
                                param_name
                                and not str(param_name).replace(" ", "").isdigit()
                            ):
                                fallback_target = param_name
                                break
                    if fallback_target:
                        valid_columns = [fallback_target]
                        print(
                            f"[Planner] Auto-filled target from discovered_sites: {fallback_target} for {technique}"
                        )
                    else:
                        print(
                            f"[Planner] Skipping {technique}: no valid target columns and no fallback available."
                        )
                        continue

                exp = ExperimentContext(
                    id=exp_data.get("id", "unknown"),
                    objective=exp_data.get("objective", ""),
                    technique=technique,
                    target_columns=valid_columns
                    if valid_columns
                    else exp_data.get("target_columns", []),
                    focus_range=exp_data.get("focus_range"),
                    baseline_range=exp_data.get("baseline_range"),
                )
                experiments.append(exp)
            except Exception as e:
                print(f"Skipping invalid experiment: {e}")

        # [HARD DEDUP] Code-level safety net: reject experiments that duplicate used_tools_history
        if state.used_tools_history:
            used_pairs = set()
            for pair in state.used_tools_history:
                if "::" in pair:
                    used_pairs.add(pair)  # "tool::param"
                else:
                    used_pairs.add(pair)

            # Also include failed experiments as absolute blacklist
            # Failed entries may contain error detail: "tool::param|error_msg"
            failed_pairs = set()
            if state.failed_experiments:
                for fp in state.failed_experiments:
                    # Strip error detail for matching: "tool::param|error" -> "tool::param"
                    clean_key = fp.split("|")[0] if "|" in fp else fp
                    failed_pairs.add(clean_key)

            original_count = len(experiments)
            deduplicated = []
            for exp in experiments:
                target = exp.target_columns[0] if exp.target_columns else "all"
                key = f"{exp.technique}::{target}"
                if key in failed_pairs:
                    print(
                        f"[Planner DEDUP] BLOCKED failed experiment: {key} (already failed, will not retry)"
                    )
                elif key in used_pairs:
                    print(f"[Planner DEDUP] Blocked duplicate: {key} (already done)")
                else:
                    deduplicated.append(exp)
            experiments = deduplicated

            if len(experiments) < original_count:
                print(
                    f"[Planner DEDUP] Filtered {original_count - len(experiments)} duplicates, {len(experiments)} remaining"
                )

        # [Fallback Mechanism] If no experiments were planned (JSON parse failure, etc.)
        if not experiments:
            # [Fix 5] Late-stage fallback: force convergence instead of guessing
            if state.step_count >= 5:
                print(
                    f"[Planner] Turn {state.step_count} >= 5 with no valid experiments. Forcing FINISH."
                )
                return RoleOutput(
                    decision="FINISH",
                    reasoning="无法规划新实验，且已执行超过 5 轮分析。建议结案。",
                    experiments=[],
                )

            print(
                "[Planner] Fallback: Attempting directive-based experiment generation."
            )
            # Try to extract target parameters from the directive
            import re

            directive = input_data.directive or ""
            # Extract parameter names that look like column names (uppercase, with dashes/underscores)
            potential_targets = re.findall(
                r"[A-Z][A-Z0-9_-]+(?:_[A-Z0-9]+)+", directive
            )
            # Also try to extract from discovered_sites
            if not potential_targets and state.discovered_sites:
                potential_targets = [
                    site.range
                    for site in state.discovered_sites[:3]
                    if not site.range.replace(" ", "").isdigit()  # Skip row numbers
                ]

            if potential_targets:
                # Directive-aware fallback: analyze the targets mentioned
                for i, target in enumerate(potential_targets[:3]):
                    experiments.append(
                        ExperimentContext(
                            id=f"fallback_{i + 1}a",
                            objective=f"分析 {target} 的分佈 (Fallback)",
                            technique="analyze_distribution",
                            target_columns=[target],
                            focus_range="Global",
                        )
                    )
                    experiments.append(
                        ExperimentContext(
                            id=f"fallback_{i + 1}b",
                            objective=f"觀察 {target} 的時間趨勢 (Fallback)",
                            technique="draw_trend",
                            target_columns=[target],
                            focus_range="Global",
                        )
                    )
            else:
                # Last resort: generic but non-repetitive fallback
                experiments.append(
                    ExperimentContext(
                        id="fallback_01",
                        objective="主成分分析 (Fallback)",
                        technique="systemic_pca_analysis",
                        target_columns=["all"],
                        focus_range="Global",
                    )
                )
                experiments.append(
                    ExperimentContext(
                        id="fallback_02",
                        objective="多變量異常偵測 (Fallback)",
                        technique="multivariate_anomaly_detection",
                        target_columns=["all"],
                        focus_range="Global",
                    )
                )

            # [Fix 4] Apply dedup to fallback experiments too
            if state.used_tools_history or state.failed_experiments:
                used_set = (
                    set(state.used_tools_history) if state.used_tools_history else set()
                )
                failed_set = set()
                if state.failed_experiments:
                    for fp in state.failed_experiments:
                        failed_set.add(fp.split("|")[0] if "|" in fp else fp)
                deduped_fallback = []
                for exp in experiments:
                    target = exp.target_columns[0] if exp.target_columns else "all"
                    key = f"{exp.technique}::{target}"
                    if key not in used_set and key not in failed_set:
                        deduped_fallback.append(exp)
                    else:
                        print(f"[Planner DEDUP] Blocked fallback duplicate: {key}")
                experiments = deduped_fallback

        return RoleOutput(
            decision=parsed.get("decision", "CONTINUE"),
            reasoning=parsed.get("reasoning", ""),
            experiments=experiments,
            structured_log={
                "thought": parsed.get("thought", ""),
                "missing_capabilities": "\n".join(missing_caps) if missing_caps else "",
            },
        )

    def _build_context_str(self, state: AnalysisState, directive: Optional[str]) -> str:
        ctx = f"Directive: {directive or 'No specific directive'}\n"
        ctx += f"Data Summary: {state.data_summary}\n"
        ctx += f"Current Step: {state.step_count} / {state.max_steps}\n"

        # [CRITICAL] 已完成分析的工具-參數組合 BLACKLIST
        if state.used_tools_history:
            ctx += "\n=== BLACKLIST (已完成, 禁止重複) ===\n"
            for pair in state.used_tools_history:
                if "::" in pair:
                    tool, param = pair.split("::", 1)
                    ctx += f"- {tool} on [{param}] -- ALREADY DONE\n"
                else:
                    ctx += f"- {pair} -- ALREADY DONE\n"
            ctx += "[RULE] 上面的工具+參數組合已經分析過了。你必須選擇不同的工具或不同的參數!\n"

            # Also show summary counts
            tool_counts = Counter(
                [p.split("::")[0] if "::" in p else p for p in state.used_tools_history]
            )
            ctx += "\n工具使用次數統計:\n"
            for tool, count in tool_counts.most_common():
                ctx += f"  {tool}: {count} 次\n"

        # [Fix 3] Show failed experiments with error details so LLM can learn
        if state.failed_experiments:
            ctx += "\n=== FAILED EXPERIMENTS (失败原因, 禁止重试) ===\n"
            for entry in state.failed_experiments:
                if "|" in entry:
                    pair, error_msg = entry.split("|", 1)
                    ctx += f"- {pair} -- FAILED: {error_msg}\n"
                else:
                    ctx += f"- {entry} -- FAILED\n"
            ctx += "[CRITICAL] 上列工具+參數組合已經失敗過, 絕對不能再用相同參數重試! 如果需要類似分析, 請使用不同的參數或工具。\n"

        # Phase progression hint
        if state.step_count >= 2:
            ctx += "\n[PHASE] 你現在在深入分析階段 (Turn 2+)。"
            ctx += "優先使用尚未使用的進階工具: batch_aggregation, interaction_effect_test, "
            ctx += "wavelet_analysis, cross_correlation_lag, find_temporal_patterns, "
            ctx += (
                "causal_relationship_analysis, analyze_residuals, correlation_network, "
            )
            ctx += "performance_segmentation, regime_detection, parallel_coordinates, radar_chart。"
            ctx += "避免重複基礎工具如 analyze_distribution, get_top_correlations (除非是全新未分析過的參數)。\n"

        # [NEW] Show unused tools from registry
        from backend.services.analysis.tools.registry import TOOL_REGISTRY

        blacklisted = {
            "basic_stats",
            "correlation_analysis",
            "search_parameters_by_concept",
            "get_time_series_data",
            "get_correlation_matrix",
            "get_data_overview",
            "compare_distributions",
        }
        used_tool_names = set()
        if state.used_tools_history:
            for pair in state.used_tools_history:
                tool_name = pair.split("::")[0] if "::" in pair else pair
                used_tool_names.add(tool_name)
        all_tools = set(TOOL_REGISTRY.keys()) - blacklisted
        unused_tools = all_tools - used_tool_names
        if unused_tools and state.step_count >= 2:
            ctx += "\n=== 尚未使用的工具 (優先選用!) ===\n"
            for tool in sorted(unused_tools):
                spec = TOOL_REGISTRY.get(tool, {})
                ctx += f"- {tool}: {spec.get('description', '')}\n"
            ctx += "[PRIORITY] 優先從上面的清單中選擇工具! 已用過的工具+參數組合禁止重複。\n"

        # Add Knowledge of Anomalies (Game Context)
        if state.discovered_sites:
            ctx += "\nKnown Anomalies:\n"
            for site in state.discovered_sites:
                ctx += f"- {site.range} (Score: {site.score:.2f})\n"

        # Rolling Summary (previous findings)
        if state.rolling_summary:
            ctx += f"\n=== 歷史發現摘要 ===\n{state.rolling_summary}\n"

        # Add Schema (Column Names) ensuring ground truth
        if state.data_schema:
            columns = list(state.data_schema.keys())
            # Truncate if too many
            if len(columns) > 50:
                columns = columns[:50] + ["..."]
            ctx += "\n=== Available Columns (只能使用以下欄位名) ===\n"
            ctx += f"{', '.join(columns)}\n"
            ctx += f"=== 共 {len(columns)} 個欄位 ===\n"
            ctx += "[WARNING] 如果你想分析的目標不在上面的清單中,請使用 'all' 代替。禁止猜測或自創欄位名!\n"

        return ctx

    def _validate_experiments(self, experiments_data: list) -> list:
        """
        自我驗證實驗計畫的合理性
        Returns: List of warning messages
        """
        warnings = []

        # 黑名單工具檢查
        BLACKLISTED_TOOLS = [
            "basic_stats",
            "correlation_analysis",
            "search_parameters_by_concept",
            "get_time_series_data",
            "get_correlation_matrix",
        ]

        for i, exp in enumerate(experiments_data):
            technique = exp.get("technique", "")

            # 檢查是否使用黑名單工具
            if technique in BLACKLISTED_TOOLS:
                warnings.append(
                    f"Exp {i + 1}: '{technique}' is blacklisted. "
                    f"Consider using alternative tools."
                )

            # 檢查 compare_data_segments 的參數完整性
            if technique == "compare_data_segments":
                params = exp.get("parameter", {})
                if not params or "target_segments" not in params:
                    warnings.append(
                        f"Exp {i + 1}: compare_data_segments missing 'target_segments' parameter"
                    )

        return warnings
