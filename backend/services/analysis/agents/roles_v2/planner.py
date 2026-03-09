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

    ### 1.5. 焦點聚焦規則 [IMPORTANT]
    
    當指令中包含 **[分析焦點]** 標記時,代表 Strategist 已明確定義本場景要回答的問題。
    此時你的實驗規劃必須:
    - 圍繞焦點問題設計實驗,選擇最能回答該問題的工具
    - 不要自行擴展到焦點以外的分析方向
    - 例如焦點是「觀察趨勢和相關性」→ 你應該選 draw_trend + get_top_correlations
      而不是自行加入 analyze_distribution / classify_anomaly_type 等無關實驗
    
    當指令中**沒有** [分析焦點] 標記時 (如通用的 [參數問題]),你才需要全面展開 Step 1 的方法論思考。

    ### 2. 可用工具清單 (Available Tools)

    #### 優先選用: 組合工具 (Combo Tools) — 一次覆蓋多維度分析
    - `combo_parameter_profiling`: [組合·多參數] 四合一參數掃描 (趨勢+分佈+相關性排名+異常偵測)
        ↳ 覆蓋: draw_trend, analyze_distribution, get_top_correlations, detect_outliers
        ↳ 參數: parameters (逗號分隔多參數)
    - `combo_anomaly_diagnosis`: [組合·單參數] 異常深度診斷 (異常類型分類+時序穩定性+頻域分析)
        ↳ 覆蓋: classify_anomaly_type, find_temporal_patterns, frequency_analysis
        ↳ 參數: parameter
    - `combo_optimization`: [組合·單參數] 最佳化全流程 (好壞批分割+因子排名+SOP建議表)
        ↳ 覆蓋: performance_segmentation, analyze_feature_importance, generate_operating_window
        ↳ 參數: target
    - `combo_causal_tracing`: [組合·單參數] 因果鏈追蹤 (Lead-Lag+Granger因果+事件序列)
        ↳ 覆蓋: cross_correlation_lag, causal_relationship_analysis, event_sequence_analysis
        ↳ 參數: target, reference(可選)

    **使用規則**: 若使用了某 combo 工具, 不要再對同參數單獨呼叫被覆蓋的原子工具 (系統會自動遮蔽重複)。

    #### 獨立工具 (不被 combo 覆蓋, 特殊用途)

    ##### 查詢與比較
    - `get_data_overview`: 資料維度與欄位清單
    - `compare_data_segments`: 比較兩個區間 (Focus vs Baseline) 的差異，**一次呼叫自動比較所有數值欄位**
    - `distribution_shift_analysis`: Wasserstein Distance 量化分佈漂移
    - `detect_correlation_breakdown`: 比較正常/異常區段的相關矩陣, 找出共線性瓦解
    - `analyze_category_correlation`: 類別型變數 (ANOVA/Kruskal-Wallis)

    ##### 異常偵測
    - `hotelling_t2_analysis`: 多變量異常偵測 (Mahalanobis Distance)
    - `multivariate_anomaly_detection`: Isolation Forest / LOF 偵測
    - `scan_anomaly_segments`: 全域異常區段掃描 (自動偵測 FREEZE/DRIFT/SPIKE 等)

    ##### 時序與診斷
    - `wavelet_analysis`: CWT 連續小波變換時頻分析
    - `control_loop_assessment`: 控制迴路品質評估 (Harris Index)
    - `trend_prediction`: 趨勢預測 + 管制線超限預估
    - `zone_diagnosis`: 多參數共變異常區段診斷

    ##### 進階分析
    - `systemic_pca_analysis`: 主成分分析 (降維)
    - `analyze_residuals`: 殘差分析 + 殘差外部因子關聯

    ##### 效能優化 (獨立)
    - `interaction_scatter`: 兩參數交互作用散佈圖 + Sweet Spot
    - `interaction_effect_test`: 兩因子交互作用 Two-Way ANOVA
    - `partial_dependence`: Partial Dependence 邊際效應曲線
    - `multi_objective_analysis`: 多目標 Synergy/Trade-off 分析
    - `stratified_interaction`: 分層交互效應

    ##### 系統級
    - `correlation_network`: 相關性網路圖
    - `cv_ranking`: 變異係數 CV 排名
    - `regime_detection`: 操作模式識別 (K-Means)
    - `batch_aggregation`: 批次/區域聚合分析

    ##### 可視化
    - `parallel_coordinates`: 平行座標圖
    - `radar_chart`: 雷達圖

    ##### 降維
    - `cluster_trend`: 分群代表趨勢圖
    - `pca_trend`: PCA 降維趨勢圖

    #### 底層原子工具 (已被 combo 覆蓋, 僅在需要細粒度控制時單獨使用)
    draw_trend, analyze_distribution, get_top_correlations, detect_outliers,
    classify_anomaly_type, find_temporal_patterns, frequency_analysis,
    performance_segmentation, analyze_feature_importance, generate_operating_window,
    cross_correlation_lag, causal_relationship_analysis, event_sequence_analysis

    ### 3. 工具使用規則
    
    - **禁止使用**: `basic_stats`, `correlation_analysis`, `search_parameters_by_concept`, `get_time_series_data`, `get_correlation_matrix`
    - 替代: `basic_stats` → `analyze_distribution`, `correlation_analysis` → `get_top_correlations`
    - 指令為 "Investigate Row X" 時,自動設定 focus_range = "X-5, X+5"
    - thought/reasoning 使用繁體中文
    - **共線性/Target 錨定**: 由 Strategist 和系統代碼自動處理,你只需遵守 directive 指示。

    ### 4. 工具參數範例
    
    | 工具名稱 | 正確參數範例 |
    |---------|-------------|
    | `combo_parameter_profiling` | `{"parameters": "SHAP-DCS_A65,FORMULA-DCS_A15,BCDRY-ABB_B19"}` |
    | `combo_anomaly_diagnosis` | `{"parameter": "SHAP-DCS_A65"}` |
    | `combo_optimization` | `{"target": "METROLOGY-P21-MO1-SP-2SIGMA"}` |
    | `combo_causal_tracing` | `{"target": "SHAP-DCS_A65", "reference": "FORMULA-DCS_A15"}` |
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
    | `detect_correlation_breakdown` | `{"target": "SHAP-DCS_A65", "anomaly_range": "30-50"}` |
    | `correlation_network` | `{}` |
    | `cv_ranking` | `{"top_k": 15}` |
    | `regime_detection` | `{"n_clusters": 0}` |
    | `multi_objective_analysis` | `{"targets": "METROLOGY-P21-MO1-SP,METROLOGY-P21-MO1-SP-2SIGMA"}` |
    | `parallel_coordinates` | `{"target_columns": "all", "color_param": "METROLOGY-P21-MO1-SP-2SIGMA"}` |
    | `radar_chart` | `{"target_columns": "all", "color_param": "METROLOGY-P21-MO1-SP-2SIGMA"}` |
    | `event_sequence_analysis` | `{"target": "KAPPA_IN-13PC_2043", "lookback_window": 10}` |
    | `stratified_interaction` | `{"param_a": "BCDRY-DCS_A92", "param_b": "BCDRY-ABB_B55", "target": "METROLOGY-P21-MO1-SP-2SIGMA", "batch_count": 5}` |
    | `zone_diagnosis` | `{}` |

    ### 4.5 參數映射硬規則 [MOST CRITICAL]
    
    **`target` 參數禁止傳入 "all"**:
    以下工具的 `target` 參數必須是具體欄位名 (如 "METROLOGY-P21-MO1-SP-2SIGMA"),
    絕對禁止傳入 "all", "所有欄位", "全部" 等模糊值:
    - `performance_segmentation` (target)
    - `batch_aggregation` (target)
    - `analyze_feature_importance` (target)
    - `analyze_residuals` (target)
    - `partial_dependence` (target + features)
    - `interaction_effect_test` (target + param_a + param_b)
    - `stratified_interaction` (target + param_a + param_b)
    - `interaction_scatter` (x_param + y_param + color_param)
    
    如果 Strategist directive 中說「全域分析」但沒指定具體 target,
    **按優先級自動解析 target**:
    1. 檢查 current_knowledge 中是否有 `[目標變量]` → 使用該目標
    2. 從歷史摘要 (key_findings) 中找 Z-Score 最高的參數 → 使用它作為 target
    3. 從歷史摘要中找 Hub 中樞參數 (degree_centrality 最高) → 使用它
    4. 以上都沒有 → 改用不需要 target 的工具: `detect_outliers`, `cv_ranking`, `correlation_network`
    
    在 reasoning 中說明: "Strategist 指示全域分析,自動選擇 [XXX] 作為 target (來源: Z-Score 排名第一)"
    
    **多參數工具必須全部填寫**:
    - `interaction_effect_test`: 必須同時提供 `param_a`, `param_b`, `target` 三個參數
    - `interaction_scatter`: 必須同時提供 `x_param`, `y_param`, `color_param` 三個參數
    - `stratified_interaction`: 必須同時提供 `param_a`, `param_b`, `target` 三個參數
    - `partial_dependence`: 必須提供 `target` 和 `features` (逗號分隔的欄位名列表)
    
    如果 Strategist directive 中沒有明確指定這些參數,**從歷史摘要中提取**:
    - `param_a` / `x_param`: 使用 key_findings 中排名最高的 [已驗證] 參數
    - `param_b` / `y_param`: 使用排名第二的 [已驗證] 參數
    - `target` / `color_param`: 使用 [目標變量] 或 Z-Score 最高的參數
    - 如果歷史中不足 2 個 [已驗證] 參數 → 跳過該工具,在 reasoning 中說明原因

    ### 5. 實驗數量與去重規則 [CRITICAL - ANTI-REPETITION]
    - 每個 Turn 規劃 **6-12 個實驗**
    - **絕對禁止**: 對同一參數重複使用同一工具 (檢查下方 BLACKLIST)
    - **每個參數**在整個分析過程中,同一工具最多用一次
    - 如果一個工具+參數組合已在 BLACKLIST 中,必須選不同的工具或不同的參數
    
    ### 5.1 全面性原則 [CRITICAL]
    Strategist 的 directive 列出的是核心分析問題,但那只是**最低要求**。
    你作為資深規劃師,必須主動思考 directive 沒有明確提到但仍然有分析價值的角度。
    
    **規劃流程:**
    1. 先為 directive 中明確要求的每個問題安排實驗
    2. 回頭審視「可用工具清單」,逐一考慮還有哪些工具能為目標參數提供額外洞察
    3. 如果一個工具能回答 directive 未提及但有價值的問題,主動加入
    
    **自檢清單**: 規劃完後,問自己:
    - 有沒有做特徵重要性分析? (該參數對系統的影響力排名)
    - 有沒有做時序穩定性分析? (是漂移、震盪還是穩定?)
    - 有沒有做分佈漂移量化? (異常前後差異多大?)
    - 有沒有做頻域分析? (是否有週期性干擾?)
    - 有沒有做因果或時間先後分析?
    
    如果規劃的實驗少於 6 個,**必須重新審視可用工具清單**,
    確認是否遺漏了有價值的分析角度。
    
    ### 5.2 多目標規劃規則 (Multi-Target Planning) [CRITICAL]
    
    **當 directive 包含 `[多目標參數分析]` 且列出多個 targets 時:**
    
    你必須為**每一個 target** 安排至少 1 個實驗, 不可只分析第一個。
    
    **規劃策略:**
    
    #### A. 個體分析 (每個 target 都需要)
    - 每個 target 至少安排 1 個診斷實驗 (如 classify_anomaly_type, find_temporal_patterns)
    - draw_trend 支持多參數 → 用一個 draw_trend 同時畫所有 targets 的趨勢
    - get_top_correlations → 每個 target 分別找其最相關的因子
    
    #### B. 交叉分析 (2+ targets 時必做)
    - `cross_correlation_lag`: 兩個 targets 之間的 Lead-Lag 關係 (誰先變化?)
    - `get_top_correlations`: 各 target 的 Top 相關因子是否重疊?
    - `detect_correlation_breakdown`: 正常 vs 異常區段, 這些 targets 的共線性是否瓦解?
    - `compare_data_segments`: 一次呼叫即可比較所有 targets, 不需分別呼叫
    
    #### C. 群組分析 (3+ targets 時考慮)
    - 多個 targets 可能屬於同一製程群組,考慮:
      - `systemic_pca_analysis`: 降維看是否為同一主成分
      - `correlation_network`: 參數網路結構
      - `detect_correlation_breakdown`: 群組共線性是否在異常時瓦解
    
    **範例 (3 個 targets: A, B, C):**
    
    | 實驗 | 覆蓋 Targets | 類型 |
    |------|-------------|------|
    | draw_trend(A, B, C) | 全部 | 個體觀察 |
    | classify_anomaly_type(A) | A | 個體診斷 |
    | classify_anomaly_type(B) | B | 個體診斷 |
    | get_top_correlations(C) | C | 個體關聯 |
    | cross_correlation_lag(A→B) | A+B | 交叉分析 |
    | detect_correlation_breakdown(A) | A vs 群組 | 群組分析 |
    | compare_data_segments(異常區段) | 全部 | 交叉比較 |
    
    → 7 個實驗, 每個 target 至少被 2 個實驗覆蓋, 覆蓋 3 個 Tier
    
    ### 5.5 雙軌實驗規劃 (Dual-Track Planning) [CRITICAL]
    
    **當 Strategist directive 包含 `[參數問題]` 和 `[樣本問題]` 兩個區塊時:**
    你必須同時為兩個區塊規劃實驗, 不可只處理參數問題。
    
    - **參數實驗**: 針對 `[參數問題]` 中的問題選擇合適的工具
    - **樣本實驗** (至少 1 個): 針對 `[樣本問題]` 中的問題, 使用以下工具:
      - `compare_data_segments` — 比較異常區間 vs 正常區間
      - `batch_aggregation` — 跨批次/區段聚合分析
      - `performance_segmentation` — 好壞批次分離
      - `regime_detection` — 操作模式聚類
    
    **範例**:
    ```
    [參數問題] FORMULA-DCS_A15 的異常類型是什麼?
    [樣本問題] Row 59-243 區間與正常區間的差異?
    
    → 參數實驗: classify_anomaly_type(FORMULA-DCS_A15)
    → 樣本實驗: compare_data_segments(target_segments="59-243", baseline_segments="0-58")
    ```
    
    **禁止**: 只規劃參數實驗而忽略樣本問題。
    
    ### 5.6 工具多樣性規則 [CRITICAL]
    
    同一 Turn 內**禁止**對同一工具呼叫超過 2 次。如果需要分析多個參數，
    優先使用支持多參數的工具，或搭配不同分析角度的工具。
    
    **工具深度分級:**
    
    | Tier | 工具 | 說明 |
    |------|------|------|
    | Tier 1 (觀察) | draw_trend, analyze_distribution, detect_outliers | 基礎描述性統計 |
    | Tier 2 (關聯) | get_top_correlations, cross_correlation_lag, analyze_feature_importance | 變數間關係 |
    | Tier 3 (診斷) | classify_anomaly_type, compare_data_segments, control_loop_assessment, frequency_analysis, find_temporal_patterns | 深入機制分析 |
    | Tier 4 (根因) | causal_relationship_analysis, event_sequence_analysis, zone_diagnosis, wavelet_analysis | 因果推理 |
    
    **規則:**
    - 每個 Turn 的實驗計畫必須覆蓋**至少 2 個不同 Tier**
    - 不允許全部實驗都是 Tier 1 (如 draw_trend x3 + analyze_distribution)
    - Turn 2+ 應優先選用 Tier 2-4 的深度工具
    - 如果要了解多個參數的趨勢，用 1 個 draw_trend + 搭配 cross_correlation_lag 或 classify_anomaly_type
    
    **範例 (錯誤 vs 正確):**
    
    錯誤: draw_trend(A15) + draw_trend(D43) + draw_trend(D69) + classify_anomaly_type(A15)
    → 4 個中有 3 個是同一工具 (Tier 1), 只覆蓋 1 個 Tier
    
    正確: draw_trend(A15) + cross_correlation_lag(A15→D43) + classify_anomaly_type(A15) + compare_data_segments(異常區段)
    → 4 個不同工具, 覆蓋 Tier 1/2/3, 得到更深入的資訊
    
    錯誤: compare_data_segments(A15) + compare_data_segments(D43) + compare_data_segments(D69)
    → compare_data_segments 一次呼叫就比較所有數值欄位, 不需要對每個參數分開呼叫
    
    正確: compare_data_segments(target_segments="240-243") + classify_anomaly_type(A15) + draw_trend(D43)
    → 1 次 compare_data_segments 即可, 搭配其他多樣化工具
    
    ### 6. 分析階段遞進 (Phase Progression)
    根據當前 Turn 決定分析深度:
    - **Turn 1 (初始掃描)**: 基礎統計 (A), 關聯性 (B), 異常偵測 (C)
    - **Turn 2-4 (參數分析 + 樣本分析)**: 每個 Turn 分析 1 個指定參數 + 樣本區間比較
    - **Turn 5+ (匹配驗證+結案)**: 因果推理, 整合報告
    
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
    - `trend_prediction` — 已支援趨勢預測 (線性/指數擬合 + 管制線超限預估)
    
    **如果你想做上面的分析,直接加入 experiments,不要報告為 missing_capabilities!**
    
    **missing_capabilities 是必填欄位**。即使沒有缺失,也要填寫空陣列 `[]`。
    **大部分情況下應該填 `[]`**,因為上面的工具清單已經非常完整。
    只報告**真正不存在、上面清單中完全沒有的分析方法**:
    - **機理模型**: 物理/化學機理驅動的分析 (非統計方法)
    - **DOE 設計**: 實驗設計優化建議
    
    **以下能力已存在,絕對不要報告為 missing**:
    - 批次/區域聚合分析 → 使用 `batch_aggregation`
    - 因果推理/因果圖 → 使用 `causal_relationship_analysis` + `cross_correlation_lag`
    - 趨勢預測/漂移預估 → 使用 `trend_prediction`
    - 交互作用分析 → 使用 `interaction_effect_test` + `stratified_interaction`
    - 頻域/週期分析 → 使用 `frequency_analysis` + `wavelet_analysis`
    - 自動報告 → Synthesizer/Humanizer 已自動產出
    
    範例 (大部分時候應該是空的):
    ```
    "missing_capabilities": []
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
        "missing_capabilities": [],
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
            print("[Planner] === Missing Capabilities (需要新增的工具) ===")
            for cap in missing_caps:
                print(f"[Planner]   - {cap}")

        # ============================================================
        # GUARDRAILS: 代碼護欄 (LLM 自由選擇, 代碼只做安檢)
        # ============================================================

        # 護欄 1: 禁用工具自動替換
        BANNED_TOOL_ALIAS = {
            "get_time_series_data": "draw_trend",
            "basic_stats": "analyze_distribution",
            "correlation_analysis": "get_top_correlations",
            "get_correlation_matrix": "get_top_correlations",
        }
        for exp in experiments_data:
            tech = exp.get("technique", "").lower()
            if tech in BANNED_TOOL_ALIAS:
                new_tech = BANNED_TOOL_ALIAS[tech]
                print(f"[Planner GUARDRAIL] 禁用工具替換: {tech} → {new_tech}")
                exp["technique"] = new_tech

        # 護欄 2: 重複實驗自動刪除 (BLACKLIST 代碼檢查)
        # 豁免清單: 同一工具在不同場景、不同區間下可重複使用
        # 只有全域掃描工具 (如 hotelling_t2) 才需要 global BLACKLIST
        SCENE_REPEATABLE_TOOLS = {
            # 樣本類工具 (不同區間 = 不同分析)
            "compare_data_segments",
            "batch_aggregation",
            "performance_segmentation",
            "regime_detection",
            # 單參數分析工具 (不同場景/區間可重複)
            "get_top_correlations",
            "analyze_distribution",
            "draw_trend",
            "classify_anomaly_type",
            "find_temporal_patterns",
            "distribution_shift_analysis",
            "analyze_feature_importance",
            "causal_relationship_analysis",
            "cross_correlation_lag",
            "frequency_analysis",
            "wavelet_analysis",
            "control_loop_assessment",
            "event_sequence_analysis",
            "trend_prediction",
            "analyze_residuals",
            "partial_dependence",
            "interaction_effect_test",
            "interaction_scatter",
            "stratified_interaction",
        }
        if state.used_tools_history:
            blacklist_set = set(state.used_tools_history)
            pre_count = len(experiments_data)
            filtered_exps = []
            for exp in experiments_data:
                tech = exp.get("technique", "").lower()
                # 樣本類工具豁免 BLACKLIST (它們的參數不同就不算重複)
                if tech in SCENE_REPEATABLE_TOOLS:
                    filtered_exps.append(exp)
                    continue
                targets = exp.get("target_columns", [])
                # 建立和 BLACKLIST 相同格式的 key
                for t in targets or ["all"]:
                    key = f"{tech}::{t}"
                    if key in blacklist_set:
                        print(f"[Planner GUARDRAIL] 刪除重複實驗: {key}")
                        break
                else:
                    filtered_exps.append(exp)
            if len(filtered_exps) < pre_count:
                print(
                    f"[Planner GUARDRAIL] 移除 {pre_count - len(filtered_exps)} 個重複實驗"
                )
            experiments_data = filtered_exps

        # 3.55 [COLLINEARITY FILTER] 代碼層級自動過濾共線性實驗
        collinear_pairs = self._extract_collinear_pairs(state)
        if collinear_pairs:
            causal_tools = {
                "cross_correlation_lag",
                "interaction_effect_test",
                "causal_relationship_analysis",
                "stratified_interaction",
            }
            filtered = []
            for exp in experiments_data:
                tech = exp.get("technique", "").lower()
                if tech in causal_tools:
                    # 檢查實驗中的參數是否為共線性組合
                    exp_params = set()
                    for key in [
                        "target",
                        "reference",
                        "param_a",
                        "param_b",
                        "target_parameter",
                        "reference_parameters",
                    ]:
                        val = exp.get("parameters", {}).get(key, "")
                        if val:
                            exp_params.update(p.strip() for p in val.split(","))
                    cols = exp.get("target_columns", [])
                    exp_params.update(cols)
                    is_collinear = any(
                        a in exp_params and b in exp_params for a, b in collinear_pairs
                    )
                    if is_collinear:
                        print(
                            f"[Planner COLLINEARITY FILTER] 移除共線性因果實驗: "
                            f"{tech} ({exp.get('id', '?')})"
                        )
                        continue
                filtered.append(exp)
            experiments_data = filtered

        # 3.6 [GUARD] 確保樣本問題有對應的有效實驗
        directive_str = directive or ""
        if "[樣本問題]" in directive_str:
            import re

            sample_tools = {
                "compare_data_segments",
                "batch_aggregation",
                "performance_segmentation",
                "regime_detection",
            }
            valid_sample_exp = False
            empty_compare_idx = []
            for idx, exp in enumerate(experiments_data):
                tech = exp.get("technique", "").lower()
                if tech in sample_tools:
                    if tech == "compare_data_segments":
                        params = exp.get("parameters", {})
                        if params.get("target_segments") and params.get(
                            "baseline_segments"
                        ):
                            valid_sample_exp = True
                        else:
                            empty_compare_idx.append(idx)
                    else:
                        valid_sample_exp = True

            if not valid_sample_exp:
                start_row, end_row = None, None
                # 來源 1: directive 中的 Row 範圍
                m = re.search(r"Row\s*(\d+)[\-~](\d+)", directive_str)
                if m:
                    start_row, end_row = int(m.group(1)), int(m.group(2))
                # 來源 2: current_knowledge
                if start_row is None:
                    kn = getattr(state, "current_knowledge", "") or ""
                    m = re.search(r"Row\s*(\d+)[\-~](\d+)", kn)
                    if m:
                        start_row, end_row = int(m.group(1)), int(m.group(2))
                # 來源 3: 歷史步驟中的 scan_anomaly_segments
                if start_row is None:
                    for step_d in state.history or []:
                        ss = str(step_d)
                        if "zone_start" in ss:
                            zm = re.search(
                                r"zone_start.{0,5}(\d+).*?zone_end.{0,5}(\d+)", ss
                            )
                            if zm:
                                start_row, end_row = int(zm.group(1)), int(zm.group(2))
                                break
                # 來源 4: 前後半分割
                if start_row is None:
                    total = getattr(state, "total_rows", 500) or 500
                    start_row, end_row = total // 2, total - 1
                    print(
                        f"[Planner GUARD] 無 Row 範圍, 用前後半分割: 0-{start_row - 1} vs {start_row}-{end_row}"
                    )

                baseline_end = max(0, start_row - 1)
                if empty_compare_idx:
                    for idx in empty_compare_idx:
                        experiments_data[idx]["parameters"] = {
                            "target_segments": f"{start_row}-{end_row}",
                            "baseline_segments": f"0-{baseline_end}",
                        }
                        experiments_data[idx]["target_columns"] = ["all"]
                        experiments_data[idx]["objective"] = (
                            f"[樣本實驗-參數修復] 比較 Row {start_row}-{end_row} vs 0-{baseline_end}"
                        )
                    print(
                        f"[Planner GUARD] 修復 {len(empty_compare_idx)} 個空參數 compare_data_segments"
                        f" -> Row {start_row}-{end_row} vs 0-{baseline_end}"
                    )
                else:
                    inject_exp = {
                        "id": "exp_sample_inject",
                        "objective": f"[樣本實驗-自動注入] 比較 Row {start_row}-{end_row} vs 0-{baseline_end}",
                        "technique": "compare_data_segments",
                        "target_columns": ["all"],
                        "parameters": {
                            "target_segments": f"{start_row}-{end_row}",
                            "baseline_segments": f"0-{baseline_end}",
                        },
                        "focus_range": "Global",
                    }
                    experiments_data.append(inject_exp)
                    print(
                        f"[Planner GUARD] 自動注入 compare_data_segments"
                        f"(Row {start_row}-{end_row} vs 0-{baseline_end})"
                    )

        # ============================================================
        # BLUEPRINT ENFORCER: 自動補齊缺失的分析維度
        # Planner LLM 自由選擇後, 代碼檢查覆蓋率並補齊
        # ============================================================
        TOOL_TO_CATEGORY = {
            # Relationships
            "get_top_correlations": "Relationships",
            "correlation_analysis": "Relationships",
            "analyze_feature_importance": "Relationships",
            "detect_correlation_breakdown": "Relationships",
            # Anomaly Detection
            "detect_outliers": "Anomaly",
            "hotelling_t2_analysis": "Anomaly",
            "multivariate_anomaly_detection": "Anomaly",
            "scan_anomaly_segments": "Anomaly",
            # Comparison
            "compare_data_segments": "Comparison",
            "distribution_shift_analysis": "Comparison",
            # Advanced Diagnostics
            "classify_anomaly_type": "Diagnostics",
            "cross_correlation_lag": "Diagnostics",
            "frequency_analysis": "Diagnostics",
            "wavelet_analysis": "Diagnostics",
            "control_loop_assessment": "Diagnostics",
            "event_sequence_analysis": "Diagnostics",
            "zone_diagnosis": "Diagnostics",
            # Patterns
            "find_temporal_patterns": "Patterns",
            "find_event_patterns": "Patterns",
            "causal_relationship_analysis": "Patterns",
            # Visualization
            "draw_trend": "Visualization",
            "parallel_coordinates": "Visualization",
            "radar_chart": "Visualization",
            # Optimization
            "performance_segmentation": "Optimization",
            "generate_operating_window": "Optimization",
            "interaction_scatter": "Optimization",
            "partial_dependence": "Optimization",
            # System
            "correlation_network": "System",
            "regime_detection": "System",
            "analyze_residuals": "System",
        }

        # 每個 scene_type 必須覆蓋的 category → 默認工具
        SCENE_BLUEPRINTS = {
            "parameter": {
                "Relationships": "get_top_correlations",
                "Diagnostics": "classify_anomaly_type",
                "Patterns": "find_temporal_patterns",
            },
            "segment": {
                "Comparison": "compare_data_segments",
                "Diagnostics": "classify_anomaly_type",
                "Patterns": "find_temporal_patterns",
            },
            "interaction": {
                "Diagnostics": "cross_correlation_lag",
                "Relationships": "detect_correlation_breakdown",
            },
            "correlation_breakdown": {
                "Relationships": "detect_correlation_breakdown",
                "Diagnostics": "classify_anomaly_type",
            },
            "optimization": {
                "Optimization": "performance_segmentation",
                "Relationships": "analyze_feature_importance",
            },
            "default": {
                "Relationships": "get_top_correlations",
                "Diagnostics": "classify_anomaly_type",
            },
        }

        # 從 directive 解析 scene_type 和 targets
        import re as _re_bp

        _bp_scene_type = "default"
        _bp_targets = []

        _scene_m = _re_bp.search(r"\[scene_type:\s*([\w]+)\]", directive_str)
        if _scene_m:
            _bp_scene_type = _scene_m.group(1)

        # 從 directive 解析 targets (場景約束中的目標參數)
        _targets_m = _re_bp.search(r"targets?:\s*(.+?)(?:\n|\[|$)", directive_str)
        if _targets_m:
            _raw_targets = _targets_m.group(1).strip()
            _bp_targets = [
                t.strip()
                for t in _raw_targets.split(",")
                if t.strip() and t.strip() != "all"
            ]
        # fallback: 從 state 的 scene_queue 找 active scene targets
        if not _bp_targets and hasattr(state, "scene_queue"):
            _active_scene = next(
                (s for s in (state.scene_queue or []) if s.status == "ACTIVE"),
                None,
            )
            if _active_scene and _active_scene.targets:
                _bp_targets = _active_scene.targets[:5]

        blueprint = SCENE_BLUEPRINTS.get(_bp_scene_type, SCENE_BLUEPRINTS["default"])

        # 檢查 Planner 已覆蓋哪些 category
        _covered_categories = set()
        for exp in experiments_data:
            _tech = exp.get("technique", "").lower()
            _cat = TOOL_TO_CATEGORY.get(_tech)
            if _cat:
                _covered_categories.add(_cat)

        # 找出缺失的 category 並注入
        _used_set = set(state.used_tools_history or [])
        _injected_count = 0

        for _cat, _default_tool in blueprint.items():
            if _cat in _covered_categories:
                continue  # 已覆蓋, 跳過

            # 用場景的 primary target 建立注入實驗
            _inject_target = _bp_targets[0] if _bp_targets else "all"
            _inject_key = f"{_default_tool}::{_inject_target}"

            # 去重: 檢查 used_tools_history
            if _inject_key in _used_set:
                # 嘗試使用第二個 target
                if len(_bp_targets) > 1:
                    _inject_target = _bp_targets[1]
                    _inject_key = f"{_default_tool}::{_inject_target}"
                    if _inject_key in _used_set:
                        continue  # 兩個 target 都用過, 跳過
                else:
                    continue  # 已用過, 跳過

            # 也檢查本次 Planner 已有的 experiments (避免重複)
            _already_in_plan = any(
                exp.get("technique", "").lower() == _default_tool
                and _inject_target in (exp.get("target_columns", []) or [])
                for exp in experiments_data
            )
            if _already_in_plan:
                continue

            _inject_exp = {
                "id": f"bp_inject_{_cat.lower()}",
                "objective": f"[Blueprint] {_cat} 維度補充分析: {_inject_target}",
                "technique": _default_tool,
                "target_columns": [_inject_target],
                "focus_range": "Global",
            }

            # segment 場景的 compare_data_segments 需要 row range 參數
            if _default_tool == "compare_data_segments":
                _row_m = _re_bp.search(r"Row\s*(\d+)\s*[-~]\s*(\d+)", directive_str)
                if _row_m:
                    _r_start, _r_end = _row_m.group(1), _row_m.group(2)
                    _baseline_end = max(0, int(_r_start) - 1)
                    _inject_exp["parameters"] = {
                        "target_segments": f"{_r_start}-{_r_end}",
                        "baseline_segments": f"0-{_baseline_end}",
                    }
                    _inject_exp["target_columns"] = ["all"]

            experiments_data.append(_inject_exp)
            _injected_count += 1
            print(f"[Blueprint] 補齊 {_cat}: {_default_tool}({_inject_target})")

        if _injected_count > 0:
            print(
                f"[Blueprint] scene_type={_bp_scene_type}, "
                f"已覆蓋={_covered_categories}, "
                f"補齊 {_injected_count} 個實驗"
            )

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

                    # [FIX] Fallback 2: 從歷史 evidence 中提取已分析過的參數
                    if not fallback_target and state.history:
                        for step in reversed(state.history):
                            ev_data = getattr(step, "evidence", None)
                            if not ev_data:
                                continue
                            raw_evs = []
                            if isinstance(ev_data, dict):
                                raw_evs = ev_data.get("raw_evidences", [])
                            elif isinstance(ev_data, list):
                                raw_evs = ev_data
                            for ev in raw_evs:
                                res = getattr(ev, "result", None)
                                if not isinstance(res, dict):
                                    continue
                                # 從 top_abnormal_parameters 提取
                                top_params = res.get("top_abnormal_parameters", {})
                                if isinstance(top_params, dict) and top_params:
                                    fallback_target = list(top_params.keys())[0]
                                    break
                                # 從 top_correlations 提取
                                top_corrs = res.get("top_correlations", [])
                                if isinstance(top_corrs, list) and top_corrs:
                                    first_corr = top_corrs[0]
                                    if isinstance(first_corr, dict):
                                        fallback_target = first_corr.get(
                                            "parameter", None
                                        )
                                        if fallback_target:
                                            break
                            if fallback_target:
                                break

                    # [FIX] Fallback 3: 使用 "all" 作為最終兜底
                    if fallback_target:
                        valid_columns = [fallback_target]
                        print(
                            f"[Planner] Auto-filled target from context: {fallback_target} for {technique}"
                        )
                    else:
                        # 最終兜底: 用 "all" 讓工具自行處理
                        valid_columns = ["all"]
                        print(
                            f"[Planner] No target found for {technique}, using 'all' as fallback."
                        )

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
            batch_seen = set()  # [INTRA-BATCH DEDUP] 同批次內去重
            for exp in experiments:
                # [ENHANCED DEDUP] 對所有 target_columns 逐一檢查, 而非只檢查第一個
                targets = exp.target_columns if exp.target_columns else ["all"]
                is_dup = False
                dup_reason = ""
                for t in targets:
                    key = f"{exp.technique}::{t}"
                    if key in failed_pairs:
                        is_dup = True
                        dup_reason = f"BLOCKED failed: {key}"
                        break
                    elif key in used_pairs:
                        is_dup = True
                        dup_reason = f"Blocked history dup: {key}"
                        break
                    elif key in batch_seen:
                        is_dup = True
                        dup_reason = f"Blocked batch dup: {key}"
                        break
                if is_dup:
                    print(f"[Planner DEDUP] {dup_reason}")
                else:
                    deduplicated.append(exp)
                    # 記錄到 batch_seen
                    for t in targets:
                        batch_seen.add(f"{exp.technique}::{t}")
            experiments = deduplicated

            if len(experiments) < original_count:
                print(
                    f"[Planner DEDUP] Filtered {original_count - len(experiments)} duplicates, {len(experiments)} remaining"
                )

            # [GUARD] 多目標覆蓋護欄: 確保每個 target 至少被 1 個實驗覆蓋
            if "[多目標參數分析]" in directive and experiments:
                import re as _re_mt

                # 從 directive 解析所有 targets
                _mt_match = _re_mt.search(
                    r"必須分析的所有目標:\s*(.+?)$", directive, _re_mt.MULTILINE
                )
                if _mt_match:
                    _all_targets = [
                        t.strip() for t in _mt_match.group(1).split(",") if t.strip()
                    ]
                    # 計算已覆蓋的 targets
                    _covered = set()
                    _has_all = False
                    for exp in experiments:
                        if exp.target_columns:
                            for tc in exp.target_columns:
                                if tc == "all":
                                    _has_all = True
                                else:
                                    _covered.add(tc)
                    # 找出未覆蓋的 targets (如果有 'all' 工具則視為全覆蓋)
                    _uncovered = (
                        []
                        if _has_all
                        else [t for t in _all_targets if t not in _covered]
                    )
                    if _uncovered:
                        print(
                            f"[Planner MULTI-TARGET] Uncovered targets: {_uncovered}, injecting fallback experiments"
                        )
                        for _ut in _uncovered[:3]:  # 最多注入 3 個
                            experiments.append(
                                ExperimentContext(
                                    id=f"mt_cover_{_ut[:8]}",
                                    objective=f"多目標覆蓋: {_ut} 趨勢與相關性分析",
                                    technique="draw_trend",
                                    target_columns=[_ut],
                                    focus_range="Global",
                                )
                            )
                        print(
                            f"[Planner MULTI-TARGET] Injected {len(_uncovered[:3])} experiments for uncovered targets"
                        )

            # [GUARD] Cap max experiments per turn to keep analysis focused
            MAX_EXPERIMENTS_PER_TURN = 12
            if len(experiments) > MAX_EXPERIMENTS_PER_TURN:
                trimmed_count = len(experiments) - MAX_EXPERIMENTS_PER_TURN
                experiments = experiments[:MAX_EXPERIMENTS_PER_TURN]
                print(
                    f"[Planner CAP] Trimmed {trimmed_count} excess experiments, "
                    f"keeping top {MAX_EXPERIMENTS_PER_TURN}"
                )

            # [GUARD] No-target mode: prevent targeting specific columns in scan phase
            knowledge = getattr(state, "current_knowledge", "") or ""
            if "調查對象]" in knowledge and "因果目標]" not in knowledge:
                from backend.services.analysis.tools.registry import (
                    get_tool_spec as _get_spec,
                )

                for exp in experiments:
                    if not exp.target_columns:
                        continue
                    first_tc = exp.target_columns[0] if exp.target_columns else ""
                    # If a specific column is used as target (not 'all'), check if tool supports global
                    if first_tc and first_tc != "all":
                        tool_spec = _get_spec(exp.technique) or {}
                        req_params = tool_spec.get("required_params", [])
                        # Tools using 'parameter' slot (e.g., classify_anomaly_type) are fine
                        # to target specific columns - they analyze individual params, not a "response variable"
                        PARAMETER_SLOT_PARAMS = {"parameter", "process_variable"}
                        uses_parameter_slot = any(
                            p in PARAMETER_SLOT_PARAMS for p in req_params
                        )
                        # Tools using 'target' slot AND supporting global can switch to 'all'
                        uses_target_slot = any(
                            p in {"target", "target_columns", "targets"}
                            for p in req_params
                        )
                        if uses_target_slot and tool_spec.get("supports_global", False):
                            print(
                                f"[Planner NO-TARGET] {exp.technique}: "
                                f"target='{first_tc}' -> 'all' (Subject Mode: 無因果目標)"
                            )
                            exp.target_columns = ["all"]
                        elif uses_target_slot and not uses_parameter_slot:
                            # Tool needs target but doesn't support global —
                            # allow it to keep the target but log a warning
                            print(
                                f"[Planner NO-TARGET] {exp.technique}: keeping "
                                f"target='{first_tc}' (tool doesn't support global)"
                            )

            # [COVERAGE] 解析 Strategist 的覆蓋缺口, 自動補充對應工具實驗
            directive = input_data.directive or ""
            if "覆蓋缺口" in directive and state.step_count >= 2:
                import re as _re

                GAP_TOOL_MAP = {
                    "全域分析": [
                        ("cv_ranking", "全域變異係數排名, 確認無遺漏"),
                        ("correlation_network", "全域相關性網路, 找出 Hub 中樞"),
                    ],
                    "全域數據": [
                        ("cv_ranking", "全域掃描確認無遺漏"),
                        ("correlation_network", "全域相關性網路"),
                    ],
                    "異常偵測": [
                        ("scan_anomaly_segments", "全域異常區段掃描"),
                        ("classify_anomaly_type", "異常類型分類"),
                    ],
                    "影響因子": [
                        ("get_top_correlations", "全域相關性排名 (target=all)"),
                        ("correlation_network", "相關性網路找出 Hub"),
                    ],
                    "因子識別": [
                        ("get_top_correlations", "全域相關性排名 (target=all)"),
                        ("correlation_network", "相關性網路找出 Hub"),
                    ],
                    "關聯分析": [
                        ("get_top_correlations", "全域相關性排名"),
                        ("cross_correlation_lag", "前導-滯後關係"),
                    ],
                    "區段分析": [
                        ("scan_anomaly_segments", "全域異常區段掃描"),
                        ("compare_data_segments", "區段差異比較"),
                    ],
                    "區間比較": [
                        ("compare_data_segments", "區段差異比較"),
                        ("distribution_shift_analysis", "分佈偏移分析"),
                    ],
                    "差異比較": [
                        ("compare_data_segments", "區段差異比較"),
                        ("distribution_shift_analysis", "分佈偏移分析"),
                    ],
                    "資料探勘": [
                        ("cv_ranking", "全域變異排名"),
                        ("correlation_network", "相關性網路"),
                        ("hotelling_t2_analysis", "多變量異常偵測"),
                    ],
                }

                # 從 directive 中提取覆蓋缺口項目
                gap_section = _re.search(
                    r"\[覆蓋缺口[^\]]*\][^\n]*\n((?:\s+\d+\..+\n?)+)",
                    directive,
                )
                if gap_section:
                    gap_items = _re.findall(r"\d+\.\s*(.+)", gap_section.group(1))
                    # 去重: 同時檢查當前 Turn 實驗 + 歷史已用工具
                    existing_techniques = {exp.technique for exp in experiments}
                    used_history = set(
                        t.split("::")[0]
                        for t in getattr(state, "used_tools_history", [])
                    )
                    existing_techniques |= used_history

                    coverage_experiments = []
                    for gap_text in gap_items[:3]:
                        gap_text = gap_text.strip()
                        matched_tools = None
                        # 精確匹配
                        if gap_text in GAP_TOOL_MAP:
                            matched_tools = GAP_TOOL_MAP[gap_text]
                        else:
                            # 模糊匹配
                            for key, tools in GAP_TOOL_MAP.items():
                                if key in gap_text or gap_text in key:
                                    matched_tools = tools
                                    break

                        if matched_tools:
                            for technique, objective in matched_tools:
                                if technique not in existing_techniques:
                                    coverage_experiments.append(
                                        ExperimentContext(
                                            id=f"coverage_{technique}",
                                            objective=f"[覆蓋補強] {objective}",
                                            technique=technique,
                                            target_columns=["all"],
                                        )
                                    )
                                    existing_techniques.add(technique)
                        else:
                            # [意圖型覆蓋缺口] 當缺口文字不匹配任何 GAP_TOOL_MAP key 時,
                            # 嘗試意圖級匹配 (e.g. "找出所有與水分相關的參數")
                            if any(
                                kw in gap_text
                                for kw in [
                                    "找出",
                                    "相關",
                                    "趨勢",
                                    "參數",
                                    "分析",
                                    "比較",
                                ]
                            ):
                                for technique, objective in [
                                    (
                                        "get_top_correlations",
                                        f"覆蓋缺口: {gap_text[:30]}",
                                    ),
                                    (
                                        "get_time_series_data",
                                        f"覆蓋缺口趨勢: {gap_text[:30]}",
                                    ),
                                ]:
                                    if technique not in existing_techniques:
                                        coverage_experiments.append(
                                            ExperimentContext(
                                                id=f"coverage_intent_{technique}",
                                                objective=f"[意圖覆蓋] {gap_text[:40]}",
                                                technique=technique,
                                                target_columns=["all"],
                                            )
                                        )
                                        existing_techniques.add(technique)
                                        print(
                                            f"[Planner COVERAGE] 意圖型匹配: "
                                            f"{gap_text[:30]} → {technique}"
                                        )

                    if coverage_experiments:
                        experiments.extend(coverage_experiments)
                        print(
                            f"[Planner COVERAGE] 自動注入 "
                            f"{len(coverage_experiments)} 個覆蓋補強實驗: "
                            f"{[e.technique for e in coverage_experiments]}"
                        )

        # [Fallback Mechanism] If no experiments were planned (JSON parse failure, etc.)
        if not experiments:
            # [Fix 5] Late-stage fallback: force convergence instead of guessing
            # 但如果 scene_queue 還有待辦場景, 不允許 FINISH, 走 fallback 生實驗
            _has_pending = any(
                s.status in ("PENDING", "ACTIVE")
                for s in getattr(state, "scene_queue", [])
            )
            if state.step_count >= 5 and not _has_pending:
                print(
                    f"[Planner] Turn {state.step_count} >= 5 with no valid experiments. Forcing FINISH."
                )
                return RoleOutput(
                    decision="FINISH",
                    reasoning="无法规划新实验，且已执行超过 5 轮分析。建议结案。",
                    experiments=[],
                )
            elif state.step_count >= 5 and _has_pending:
                _pending_ids = [
                    s.scene_id
                    for s in state.scene_queue
                    if s.status in ("PENDING", "ACTIVE")
                ]
                print(
                    f"[Planner] Turn {state.step_count} >= 5 但仍有待辦場景 "
                    f"{_pending_ids}, 走 fallback 生實驗"
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

        # --- [PATH S] 場景類型工具推薦 ---
        _directive_str = directive or ""
        if "[scene_type:" in _directive_str:
            import re as _re_scene

            _scene_match = _re_scene.search(
                r"\[scene_type:\s*([\w]+)\]", _directive_str
            )
            if _scene_match:
                _scene_type = _scene_match.group(1)
                _SCENE_TOOL_HINTS = {
                    "optimization": (
                        "performance_segmentation, analyze_feature_importance, "
                        "generate_operating_window, partial_dependence, "
                        "interaction_scatter"
                    ),
                    "interaction": (
                        "cross_correlation_lag, causal_relationship_analysis, "
                        "interaction_effect_test, get_top_correlations"
                    ),
                    "segment": (
                        "compare_data_segments, distribution_shift_analysis, "
                        "batch_aggregation, classify_anomaly_type"
                    ),
                    "parameter": (
                        "classify_anomaly_type, find_temporal_patterns, "
                        "analyze_distribution, draw_trend, detect_outliers"
                    ),
                    "correlation_breakdown": (
                        "detect_correlation_breakdown, get_top_correlations, "
                        "cross_correlation_lag, compare_data_segments"
                    ),
                }
                _hint = _SCENE_TOOL_HINTS.get(_scene_type, "")
                if _hint:
                    ctx += (
                        f"\n[場景類型工具推薦] scene_type={_scene_type}\n"
                        f"  優先使用: {_hint}\n"
                        f"  (不限制選擇, 只建議優先考慮上述工具)\n"
                    )

        # [CRITICAL] 已完成分析的工具-參數組合 BLACKLIST
        if state.used_tools_history:
            ctx += "\n=== 歷史分析記錄 (避免無意義重複) ===\n"
            for pair in state.used_tools_history:
                if "::" in pair:
                    tool, param = pair.split("::", 1)
                    ctx += f"- {tool} on [{param}]\n"
                else:
                    ctx += f"- {pair}\n"
            ctx += (
                "[RULE] 以上為歷史使用記錄。\n"
                "- 同一場景內: 禁止對同一參數重複使用同一工具\n"
                "- 跨場景/不同分析區間: 同一工具可以重複用於相同參數 (分析目的不同)\n"
                "- 如果當前場景需要某個分析維度, 即使歷史記錄中有, 仍應規劃\n"
            )

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

        # [REMOVED] Phase progression hint - Planner 不需要知道分析階段
        # [REMOVED] Unused tools list - Planner 不需要被引导选工具，按 directive 选就好
        # [REMOVED] rolling_summary - Planner 只需 directive + BLACKLIST，全局视野由 Strategist 负责

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

    def _extract_collinear_pairs(self, state: AnalysisState) -> list:
        """从历史步骤中提取 |r| > 0.99 的共线性参数对"""
        import re

        pairs = []
        sources = []
        # 来源: current_knowledge
        kn = getattr(state, "current_knowledge", "") or ""
        if kn:
            sources.append(kn)
        # 来源: steps_history
        for step_d in state.history or []:
            sources.append(str(step_d))

        # 合法欄位名稱模式: 字母開頭, 包含字母/數字/底線/連字號, 至少 2 字元
        # 排除中文字符, 避免把分析文本誤判為參數名
        _COL_PAT = r"[A-Za-z][A-Za-z0-9_-]{1,60}"
        for text in sources:
            # 匹配 "A 與 B ... r=0.999" 或 "[共線性] A 與 B"
            # 限制 A/B 必須符合欄位名模式, 且 "與...r=" 之間最多 50 字元
            for m in re.finditer(
                rf"({_COL_PAT})\s*[與和&]\s*({_COL_PAT}).{{0,50}}?r\s*=\s*([\d.]+)",
                text,
            ):
                r_val = float(m.group(3))
                if r_val > 0.99:
                    pairs.append((m.group(1), m.group(2)))
            for m in re.finditer(
                rf"\[共線性\]\s*({_COL_PAT})\s*[與和&]\s*({_COL_PAT})", text
            ):
                pairs.append((m.group(1), m.group(2)))

        if pairs:
            unique = list(set(pairs))
            print(f"[Planner] 偵測到 {len(unique)} 組共線性參數: {unique}")
            return unique
        return []

    # 工具深度分級 — 用於多樣性檢查和自動替換
    _TOOL_TIERS = {
        # Tier 1: 觀察型
        "draw_trend": 1,
        "get_time_series_data": 1,
        "analyze_distribution": 1,
        "detect_outliers": 1,
        # Tier 2: 關聯型
        "get_top_correlations": 2,
        "cross_correlation_lag": 2,
        "analyze_feature_importance": 2,
        "analyze_category_correlation": 2,
        # Tier 3: 診斷型
        "classify_anomaly_type": 3,
        "compare_data_segments": 3,
        "control_loop_assessment": 3,
        "frequency_analysis": 3,
        "find_temporal_patterns": 3,
        "distribution_shift_analysis": 3,
        "hotelling_t2_analysis": 3,
        "multivariate_anomaly_detection": 3,
        # Tier 4: 根因型
        "causal_relationship_analysis": 4,
        "event_sequence_analysis": 4,
        "zone_diagnosis": 4,
        "wavelet_analysis": 4,
        "analyze_residuals": 4,
        "trend_prediction": 4,
        # Tier 2: 參數降維型
        "cluster_trend": 2,
        "pca_trend": 2,
    }

    # 當某工具重複過多時，可替換為的候選工具
    _TOOL_UPGRADES = {
        "draw_trend": [
            "cluster_trend",
            "pca_trend",
            "find_temporal_patterns",
        ],
        "get_time_series_data": [
            "find_temporal_patterns",
            "classify_anomaly_type",
            "distribution_shift_analysis",
        ],
        "analyze_distribution": [
            "distribution_shift_analysis",
            "classify_anomaly_type",
        ],
        "get_top_correlations": ["cross_correlation_lag", "analyze_feature_importance"],
        "detect_outliers": ["classify_anomaly_type", "compare_data_segments"],
    }

    def _validate_experiments(self, experiments_data: list) -> list:
        """
        自我驗證實驗計畫的合理性 + 工具多樣性護欄
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

        # ====== 工具多樣性護欄 (Diversity Guard) ======
        tool_counts = Counter(exp.get("technique", "") for exp in experiments_data)
        used_tools_set = set(tool_counts.keys())

        # 視覺化/查詢工具白名單: 不同參數畫不同圖表是合理的, 不應被替換
        DIVERSITY_WHITELIST = {
            "draw_trend",
            "interaction_scatter",
            "draw_parallel_coordinates",
            "draw_radar_chart",
            "get_top_correlations",
        }

        for tool_name, count in tool_counts.items():
            if tool_name in DIVERSITY_WHITELIST:
                continue  # 白名單工具不受多樣性限制
            if count >= 3:
                # 找到可替換的候選工具
                candidates = self._TOOL_UPGRADES.get(tool_name, [])
                # 排除已在本次計畫中使用的工具
                available = [c for c in candidates if c not in used_tools_set]
                if not available:
                    warnings.append(
                        f"[DiversityGuard] '{tool_name}' 出現 {count} 次，"
                        f"超過上限 2 次，但無可用替代工具"
                    )
                    continue

                # 自動替換多餘的實驗（保留前 2 個，替換第 3 個起）
                replace_count = 0
                occurrence = 0
                for exp in experiments_data:
                    if exp.get("technique") == tool_name:
                        occurrence += 1
                        if occurrence > 2:
                            old_tool = tool_name
                            new_tool = available[replace_count % len(available)]
                            exp["technique"] = new_tool
                            exp["objective"] = (
                                f"[自動升級] {exp.get('objective', '')} "
                                f"(從 {old_tool} 升級為 {new_tool})"
                            )
                            used_tools_set.add(new_tool)
                            replace_count += 1
                            warnings.append(
                                f"[DiversityGuard] 自動替換: "
                                f"{old_tool} → {new_tool} "
                                f"(第 {occurrence} 次出現)"
                            )

        # Tier 覆蓋檢查（僅報告，不自動修正）
        tiers_covered = set()
        for exp in experiments_data:
            t = exp.get("technique", "")
            tier = self._TOOL_TIERS.get(t, 0)
            if tier > 0:
                tiers_covered.add(tier)
        if len(tiers_covered) < 2 and len(experiments_data) >= 3:
            warnings.append(
                f"[DiversityGuard] 僅覆蓋 Tier {tiers_covered}，"
                f"建議至少覆蓋 2 個不同深度等級"
            )

        return warnings
