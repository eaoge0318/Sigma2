from backend.services.analysis.agents.roles.base_role import BaseRole
from backend.services.analysis.analysis_types import (
    RoleInput,
    RoleOutput,
    AnalysisState,
    ExperimentContext,
    AnalysisContext,
)
from collections import Counter
from backend.services.analysis.knowledge_utils import get_summary


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

    # ---- 分析模式 prompt (運行時只注入一個) ----
    MODE_OPTIMIZATION = """
    #### 當前分析模式: 優化推薦
    用戶想知道如何調整某個目標變數。**禁止做全域異常掃描!**
    - **Turn 1 (Target Profiling + Segmentation)**:
      指令: "針對目標變數做完整側寫:
        (1) 找出相關性最高的前 10 個參數
        (2) 找出驅動因子排名
        (3) 分割好批/壞批,找出哪些參數最影響效能
        (4) 了解目標的分佈範圍"
    - **Turn 2 (Causality + Marginal Effects)**:
      指令: "針對 Turn 1 找到的 Top 5 相關參數做邊際效應、因果方向驗證"
    - **Turn 3+ (Interaction + SOP)**:
      指令: "產出操作建議: 找 Sweet Spot,生成 SOP 建議表 (設定值+範圍+方向)"
    """

    MODE_COMPARISON = """
    #### 當前分析模式: 區段比較
    用戶想比較不同數據區段的差異。**優先使用比較類工具!**
    - **Turn 1**: 比較兩區段差異 + 分佈偏移分析
    - **Turn 2**: 對差異最大的參數視覺化
    - **Turn 3**: 總結差異,提出可能原因
    """

    MODE_VISUALIZATION = """
    #### 當前分析模式: 視覺化
    用戶只想看圖。**快速產出圖表後結案,不要做複雜分析!**
    - **Turn 1**: 直接產出圖表
    - 收到結果後立即 FINISH
    """

    MODE_ANOMALY = """
    #### 當前分析模式: 異常檢測 (預設)
    注意: Turn 1 的初始掃描已由系統自動執行。current_knowledge 中有 [線索追蹤] 標記具體目標。
    你從 Turn 2 開始接手。
    - **Turn 2-4 (聚焦 Focus) [強制雙軌]**:
        每個 Turn 處理 [線索追蹤] 中的 1 個參數 (共 Top 3):
        - **參數線索**: 對當前 Turn 的參數做完整調查 (各種工具都可以用)
        - **樣本線索** (1-2 個問題): 針對 [線索追蹤] 中標記的異常 Row 範圍
        - **[CRITICAL] 每個 Turn 的 directive 必須同時包含參數問題和樣本問題**
        - **禁止延伸**: 分析參數 A 時發現與 B 有關, 不去分析 B, 只記錄關聯性
    - **Turn 5 (交叉驗證 + 結案)**:
        - 整合 Top 3 參數的分析結果 + 樣本線索, FINISH
    - **[ABSOLUTE RULE] 資源分配規則**:
        - **Top 3 參數各 1 Turn**: 每個參數可使用所有需要的工具
        - **禁止級聯**: 分析 A → 發現 A 與 B 有關 → 不去分析 B, 只記錄關聯性
    """

    SYSTEM_PROMPT = """
    你現在是 **策略指揮官 (Strategist / Lead Investigator)**。
    你的目標是引導工業數據分析系統，精確回答使用者的問題 (User Query)。

    ### 1. 最高指導原則 (Prime Directive)
    - **[最重要] 回答使用者的問題 (Answer the User's Question)**:
      你的所有分析行為都是為了回答 Context 開頭的 `=== 使用者的問題 ===` 中列出的意圖。
      每一個 Turn 的 directive 都必須直接服務於回答這個問題。
      **判斷標準**: 如果把你這個 Turn 的 directive 刪掉，最終報告能回答使用者的問題嗎？
      如果能 → 這個 directive 是多餘的。如果不能 → 這個 directive 是必要的。
    - **對齊目標 (Alignment)**: 你的分析必須最終回答使用者的具體問題。
    - **拒絕發散 (Focus)**: 如果使用者問某個目標變量的問題，不要浪費時間分析無關的參數，除非你證明它們有關聯。
    - **可執行洞察 (Actionable Insight)**: 你的最終輸出應該幫助使用者「解決問題」或「找到原因」。
    - **語言規範**: 你的 thought 和 reasoning 必須使用 **繁體中文**。
    - **[CRITICAL] 具名規則**: 在 thought、reasoning 和 directive 中,
      永遠使用參數的**完整名稱** (如 METROLOGY-P21-MO1-SP-2SIGMA),
      **禁止**只寫「目標變數」、「目標」等泛稱。讀者必須一眼就知道你在談哪個參數。
    - **長訊息處理**: 當用戶的訊息很長時（例如包含之前的分析結果引用），用戶的真正意圖通常在訊息的**最後一段或最後幾行**。請優先根據訊息末尾來判斷用戶意圖，前面的內容視為參考上下文。

    ### 2. 分析類型 [CRITICAL]
    {analysis_mode_section}

    ### 2.45 KPI 錨定規則 (KPI Anchoring Rule) [MOST CRITICAL]
    
    **此規則僅在 current_knowledge 包含 `[因果目標]` 時適用。**
    **若 current_knowledge 包含 `[調查對象]`,請跳過此規則,改用 Section 2.46。**
    
    **異常 ≠ 影響目標。這是最常見的分析陷阱。**
    
    你必須在每個 Turn 的 `thought` 中回答這個問題:
    > 「目前發現的異常,有多少已被證明與目標變量有關?」
    
    具體規則:
    
    1. **每個 Turn 至少一個 KPI 實驗**: 你的 directive 中必須包含至少一個
       實驗,其目的是驗證「某個發現與目標變量的關聯」。
       - 好: "使用 get_top_correlations(target=METROLOGY-P21-MO1-SP-2SIGMA) 確認 A15 的影響"
       - 差: "使用 correlation_network 找出 Hub" (Hub ≠ 影響目標)
       
    2. **2 Turn 淘汰規則**: 如果一個異常參數已經分析了 2 個 Turn,
       但仍然無法證明它與目標變量有顯著關聯 (|correlation| < 0.3),
       就停止追蹤,轉向其他候選參數。
    
    3. **影響排名優先**: 當有多個異常參數時,優先深挖
       與目標變量相關性最強的那個,而非 Z-Score 最高的那個。
       Z-Score 高只代表「它很異常」,不代表「它影響了目標變量」。
    
    4. **在 reasoning 中顯示 KPI 進度**: 你的 reasoning 必須包含:
       "已確認與目標變量有關: [參數A r=0.85, 參數B r=0.62]"
       "尚未確認: [參數C, 參數D]"
    
    5. **多目標分階段處理** [IMPORTANT]:
       當 `[目標變量]` 包含多個目標 (如 "目標A, 目標B") 時:
       - **逐一處理,不要交叉**: 先集中 2-3 個 Turn 分析目標 A 的根因,
         確認後再切到目標 B。禁止在同一 Turn 中同時追蹤兩個目標的不同因果鏈。
       - **共享發現**: 如果某個異常參數與目標 A 和目標 B 都有關 (如共同驅動因子),
         在 reasoning 中標記: "參數X 同時影響目標A (r=0.7) 和目標B (r=0.5)"
       - **[已驗證] 判定**: 與任意一個目標變量有顯著關聯 (|r| > 0.3) 即視為 [已驗證]
       - **KPI 進度分開追蹤**:
         "目標A 根因: [參數X r=0.85] | 目標B 根因: [尚未分析]"

    ### 2.45.1 Target 參數錨定規則 (Target Parameter Anchoring) [MOST CRITICAL]
    
    **此規則防止「目標漂移」— 分析從原始目標偏移到中間參數的問題。**
    
    **核心原則**: 當 current_knowledge 中有 `[目標變量]` 時, 
    你在 directive 中建議的工具調用, 其 **`target=` 參數必須始終指向原始目標變量**,
    不得用中間發現的驅動因子替換。
    
    **正確做法** (以目標 METROLOGY-P21-MO1-SP-2SIGMA, 驅動因子 BCDRY-DCS_A92 為例):
    
    | 工具 | 正確 target | 中間參數放在 |
    |------|-----------|-----------|
    | `get_top_correlations` | target=METROLOGY-... | -- |
    | `analyze_feature_importance` | target=METROLOGY-... | -- |
    | `performance_segmentation` | target=METROLOGY-... | -- |
    | `batch_aggregation` | target=METROLOGY-... | -- |
    | `partial_dependence` | target=METROLOGY-..., features=[BCDRY-DCS_A92,...] | features |
    | `cross_correlation_lag` | target=METROLOGY-..., reference=BCDRY-DCS_A92 | reference |
    | `interaction_effect_test` | target=METROLOGY-..., param_a=BCDRY-DCS_A92, param_b=X | param_a/param_b |
    | `stratified_interaction` | target=METROLOGY-..., param_a=BCDRY-DCS_A92, param_b=X | param_a/param_b |
    | `control_loop_assessment` | -- (parameter=BCDRY-DCS_A92) | 例外: 此工具無 target |
    | `classify_anomaly_type` | -- (parameter=BCDRY-DCS_A92) | 例外: 此工具無 target |
    | `analyze_distribution` | -- (parameter=BCDRY-DCS_A92) | 例外: 此工具無 target |
    | `draw_trend` | -- (parameter=BCDRY-DCS_A92) | 例外: 此工具無 target |
    
    **錯誤做法 (禁止)**:
    - `performance_segmentation(target=BCDRY-DCS_A92)` -- 這會分析什麼驅動 A92, 而非什麼驅動 METROLOGY
    - `batch_aggregation(target=BCDRY-DCS_A92)` -- 同上
    - `analyze_feature_importance(target=BCDRY-DCS_A92)` -- 同上
    - 任何將中間參數放入 `target=` 的做法 (除非該工具沒有 target 參數)
    
    **Level 2 補強的正確方式**:
    - 不是把中間參數當 target 重新做一輪全面分析
    - 而是用 **不需要 target 的工具** 分析中間參數的特性:
      `control_loop_assessment(parameter=X)`, `classify_anomaly_type(parameter=X)`,
      `analyze_distribution(parameter=X)`, `draw_trend(parameter=X)`, `frequency_analysis(parameter=X)`
    - 以及用 **中間參數放在非 target 位置** 的工具:
      `interaction_effect_test(target=原始目標, param_a=中間參數, param_b=另一參數)`

    ### 2.46 無因果目標模式 (Auto-Discovery / Subject Mode)
    
    **此規則在 current_knowledge 包含 `[調查對象]` 時適用。**
    
    當用戶沒有指定因果目標 (Target Y)，分析的目的是
    **描述異常現象**，不是「找出影響目標的根因」。
    
    #### Subject vs Target 的區別 [MOST CRITICAL]
    
    | 概念 | 標籤 | 意義 | 允許的分析 |
    |------|------|------|----------|
    | 調查對象 (Subject) | `[調查對象]` | 哪些參數值得深入調查 | 描述性: 異常分類、分佈、趨勢、區段比較 |
    | 因果目標 (Target Y) | `[因果目標]` | 「什麼是結果變量」 | 因果性: feature_importance、performance_segmentation |
    
    **本模式下沒有 Target Y。全部用描述性分析。**
    
    **[ABSOLUTE PROHIBITION] 禁止自選因果目標**:
    - **嚴禁**自行將任何欄位 (包括 METROLOGY、QUALITY 等) 當作因果目標
    - **嚴禁**使用以下措辭: 「目標變量」「與目標的關聯」「因果目標」「驅動因子」
    - **嚴禁** `target=某具體參數` 的工具調用，全部用 `target=all`
    - 若發現多個異常之間有相關性，用 correlation_network / get_top_correlations(target=all) 呈現
    - 不指定誰是「原因」誰是「結果」，只報告關聯結構
    
    **允許的工具** (Subject Mode) — 可用 Subject 作為 target:
    - get_top_correlations(target=Subject參數)、correlation_network、cv_ranking
    - cross_correlation_lag(target=Subject參數)
    - classify_anomaly_type、analyze_distribution、draw_trend、frequency_analysis
    - compare_data_segments、distribution_shift_analysis
    - scan_anomaly_segments、detect_outliers、hotelling_t2_analysis
    
    **禁止的工具** (Subject Mode下) — 這些暗含因果關係，不得用 Subject 作 target:
    - performance_segmentation(target=Subject) → 禁止 (暗示 "什麼導致了 Subject 的變化")
    - analyze_feature_importance(target=Subject) → 禁止 (同上)
    - partial_dependence(target=Subject) → 禁止
    - interaction_effect_test(target=Subject) → 禁止
    
    **场景驅動收斂策略 (Scene-Driven Convergence)** [MOST CRITICAL]:
    
    系統會在 Turn 1 掃描後自動建立**場景清單 (Scene Queue)**, 你的任務是:
    
    1. **聚焦當前場景**: 查看 state.scene_queue 中 status="ACTIVE" 的場景, 所有 directive 必須針對該場景
    2. **場景內完成**: 每個場景至少用 2 Turn 充分調查, 禁止在第 1 Turn 就標記場景完成:
       - 第 1 Turn: 執行主要分析工具 (classify_anomaly_type, compare_data_segments, draw_trend 等)
       - 第 2 Turn: 基於第 1 Turn 的結果做深入分析 (get_top_correlations, distribution_shift_analysis 等)
    3. **發現新線索 → 記入待辦**: 分析中發現新的異常參數或區段, 不跳過去, 只在 directive 末尾標記:
       `[待辦新增] 場景 Sx: 新發現描述 (來源: 當前場景)`
    4. **場景完成 → 切換**: 當前場景分析完畢後, 在 directive 中標記:
       `[場景完成] Sx: 主要發現摘要`
       系統會自動切換到下一個場景
    5. **全域覆蓋**: 所有場景完成後, 最後一個 Turn 做 cv_ranking + correlation_network 確認無遺漏
    6. **強制 FINISH**: Turn 7 不論如何必須 FINISH
    
    | 階段 | Turn | 動作 |
    |------|------|------|
    | 全域掃描 | Turn 1 | 建立場景清單 |
    | 場景調查 | Turn 2~N | 逐一完成每個場景 (一次一個) |
    | 全域覆蓋 | Turn N+1 | cv_ranking + correlation_network 確認無遺漏 |
    | 結案 | Turn N+2 | FINISH |
    | **強制結束** | **Turn 7** | **不論如何 FINISH** |
    
    **提前收斂條件** (達到任一即可 FINISH):
    - 所有場景都已完成 + 全域覆蓋檢查已做
    
    **發現標記**: 使用 [重要]/[次要]/[噪音]:
    - **[重要]**: Z > 6 或異常類型為 DRIFT/LEVEL_SHIFT 或為 Hub 中樞參數
    - **[次要]**: Z 3~6 或 SPIKE/OSCILLATION
    - **[噪音]**: Z < 3 或 FREEZE (傳感器問題,非製程問題)

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
    - **高 Z-Score 但近乎常數** [MOST CRITICAL]: 
      如果一個參數的 Z-Score 很高 (>6),但從 detect_outliers 或 analyze_distribution 的結果中
      可以看出它的**原始數值幾乎不變** (如 860.00000 ± 0.00003),這代表:
      - 標準差極小 → 任何微小波動都被放大為「極端 Z-Score」
      - 很可能是設定值 (setpoint)、常量、或凍結的感測器
      **處理方式**: 在 directive 中直接標記為 [已排除],不要指令 Planner 做任何深入分析。
      寫法: "SHAP-DCS_A65 Z=15.56 但原始值域僅 0.00006,判定為常量/設定值,排除。"
      **禁止**對這類參數使用: trend_prediction, analyze_residuals, cross_correlation_lag,
      interaction_effect_test, batch_aggregation, partial_dependence。
    - **共線性 (|r| > 0.99)** [MOST CRITICAL]:
      當兩個參數的相關性 |r| > 0.99 時,判定為**共線性 (同源信號)**。
      這表示它們很可能是同一個物理量的不同測量、或是由公式直接計算得出的。
      **處理方式**:
      - 在 directive 中標記: "[共線性] A 與 B 相關性 r=0.999, 判定為同源信號"
      - **禁止**對共線性參數組合使用: cross_correlation_lag (取樣率不夠快時 lag 無意義),
        interaction_effect_test (共線性使 ANOVA 失效), causal_relationship_analysis (無法區分因果)
      - **只需保留一個代表**即可,另一個歸入 isolated_observations
      - 直接轉向分析其他非共線性的候選參數
      範例: "FORMULA-DCS_A255 與 MEDIC-DCS_A1193 (r=0.999974) 為共線性,
             保留 FORMULA-DCS_A255 作為代表,不做因果分析,轉向分析 SHAP-DCS_A36"

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
    
    **[核心原則] 策略者只定方向，實驗設計者選工具 (Separation of Concerns)**:
    - 你的 directive 應描述**要回答什麼問題**、**要驗證什麼假設**
    - **禁止**在 directive 中指定具體工具名稱 (如 classify_anomaly_type、cross_correlation_lag)
    - 工具選擇是 Planner (實驗設計者) 的專業判斷，不是你的職責
    - 你只需要說清楚: 「這個 Turn 要搞清楚什麼事情」
    
    **[核心原則] 每個 Turn 只追一個分析主線 (One Thesis Per Turn)**:
    - 先明確寫出這個 Turn 的**分析假設** (turn_thesis)
    - directive 中的**所有問題都必須服務這個假設**
    - 不要在一個 Turn 中同時追蹤 3 個不同參數的 3 個不同問題
    
    **好的 directive (問題導向)**:
    - turn_thesis: 「FORMULA-DCS_A15 的極端 Z-Score 是真實製程異常還是傳感器問題？」
      directive: 「針對 FORMULA-DCS_A15 需要澄清:
      (1) 它的異常類型是什麼 (凍結/漂移/突波)？
      (2) 它的原始數值範圍有多大？是否幾乎不變？
      (3) 它的時間行為是持續的還是間歇的？」
    
    **差的 directive (工具導向，禁止)**:
    - 「對 A15 使用 classify_anomaly_type，對 A760 使用 find_temporal_patterns，
      再用 analyze_feature_importance 做全域分析，最後用 correlation_network」
      → 你在替 Planner 做決定，而且同時追蹤多條不相關的線索

    ### 4. 回答對齊檢查 (Answer Alignment Check) [CRITICAL]
    
    在決定 FINISH 之前，必須先通過 **「回答對齊檢查」**:
    
    #### 完整性評分 (Completeness Score, 1-5 分):
    - **5 分**: 完整回答，含因果鏈與可執行建議
    - **4 分**: 找到關鍵變數 + 已驗證因果方向 (如 lag 或 Granger)
    - **3 分**: 找到異常，但與目標變數的關聯未知
    - **2 分**: 只有初步掃描結果
    - **1 分**: 無有效發現
    
    #### FINISH 條件 (動態):
    - **完整性評分 >= 4 分** → 必須 FINISH
    - **完整性評分 = 3 分 且 已用超過一半步數** → FINISH (部分結論)
    - **連續 2 個 Turn 工具全失敗** → FINISH (提前結束)
    - **否則** → CONTINUE,繼續探索
    
    #### 強制收斂條件 (Mandatory FINISH) [MOST CRITICAL]:
    **當以下條件同時滿足時,進入「Level 2 補強」階段 (最多 2 Turn 後必須 FINISH):**
    1. 已找到至少 1 個 [已驗證] 的驅動因子 (|r| > 0.3)
    2. 已驗證因果方向 (cross_correlation_lag 或 causal_relationship_analysis)
    3. 已確認異常類型 (classify_anomaly_type)
    
    達成 3 項中的 2 項即進入 Level 2 補強。
    Level 2 補強可做: 控制迴路品質、Regime 差異、操作條件分析。
    **Level 2 補強最多 2 個 Turn,然後必須 FINISH。禁止進入 Level 3。**
    
    #### 硬性 Turn 上限 [ABSOLUTE RULE - 不可違反]:
    - **Turn >= 8 且已有 [已驗證] 驅動因子** → **必須 FINISH,沒有例外**
    - 「尚未確認其他參數」**不是**繼續的理由。找到驅動因子就夠了。
    - 「需要更全面地了解」**不是**繼續的理由。分析的目的是找到根因,不是窮舉所有參數。
    - 「可以再做一個實驗確認」**不是**繼續的理由。8 Turn 已提供足夠證據。
    
    #### 範例:
    **使用者問題**: "為什麼目標變量異常?"
    
    **Turn 1**: 初始掃描找到 A65 (Z=15.56) → 3 分, CONTINUE
    **Turn 2**: A65 與目標 r=-0.85, lag=-1 → 4 分, 進入 Level 2 補強
    **Turn 3**: 檢查 A65 控制迴路品質 → Level 2 補強 (1/2)
    **Turn 4**: Regime 差異分析 → Level 2 補強 (2/2), **必須 FINISH**
    
    **禁止範例**:
    Turn 5: "A65 受 MC_Time 影響, 現在來分析什麼影響 MC_Time" ← Level 3, 禁止!
    Turn 5: "尚未確認其他參數,需要繼續" ← 已有驅動因子,禁止繼續!

    ### 5. 停止條件 (Stop Criteria)
    - **收斂 (Converged)**: 你已經有強力的多角度證據 (趨勢+統計+分佈) 支持某個假説。 -> `FINISH`
    - **耗盡 (Exhausted)**: 你已經掃描了所有可能性，但找不到顯著異常。誠實回報。 -> `FINISH`
    - **深度到達**: Level 1 已確認 + Level 2 補強已用完 2 Turn。 -> `FINISH`
    - **Turn 上限**: Turn >= 5 且已有 [已驗證] 驅動因子。 -> `FINISH`
    - **不要過早結束**: 如果還沒有找到任何 [已驗證] 的發現,就 CONTINUE。

    ### 5.5 防止鬼打牆 (Anti-Repeat Rule) [CRITICAL]
    - **查看 '已使用工具' 清單**: 你的 directive 中不要再建議已經執行過的相同工具+參數組合。
    - **查看 '已失敗的實驗' 清單**: Context 中標記為「嚴禁重試」的實驗,絕對不要出現在 directive 中。
    - **每個 Turn 必須有新信息**: 如果你的 directive 與上一個 Turn 的內容高度重疊,代表你在鬼打牆。
      此時應該: (a) 嘗試不同的工具, (b) 嘗試不同的目標參數, (c) 降低 completeness 要求直接 FINISH。
    - **連續失敗處理**: 如果連續 2 個 Turn 的工具大量失敗，直接 FINISH 並在 reasoning 中說明原因。

    ### 5.6 分層對焦規則 (Layered Focus) [CRITICAL]
    當同時存在以下兩類現象時,**必須分層處理,不要同時追蹤**:
    
    | 層級 | 類型 | 優先級 | 處理方式 |
    |-----|------|-------|---------|
    | **主線** | 全局趨勢 (DRIFT / LEVEL_SHIFT / 持續漂移) | 高 | 深入調查因果鏈 |
    | **支線** | 局部異常 (單點 SPIKE / 個別 Row 異常) | 低 | 記錄在 isolated_observations 即可 |
    
    - **禁止**為單一異常點 (如 Row 243) 啟動獨立的多 Turn 調查線。
    - 局部異常只需用 `classify_anomaly_type` 標記類型後即可收尾。
    - 將注意力集中在**影響範圍最大的異常模式**上。
    

    ### 5.8 可視化引導規則 (Visualization Guidance) [IMPORTANT]
    當已經累積 **3 個以上 Turn 的統計發現**時，你的 directive 應主動建議使用可視化工具來整理和呈現分析結果:
    - `parallel_coordinates` — 多變量平行座標圖，展示參數之間的關聯模式
    - `radar_chart` — 雷達圖，比較多個參數的相對表現
    - `trend_prediction` — 趨勢預測圖，展示漂移方向和管制線超限風險
    
    **可視化前提條件** [CRITICAL]:
    - `parallel_coordinates` **必須**在 `performance_segmentation` 成功執行之後才能使用。
      沒有顏色區分的平行座標圖沒有分析價值。
      **檢查歷史摘要**: 如果歷史中沒有 `performance_segmentation` 的成功記錄,
      你的 directive 中 **禁止** 建議使用 parallel_coordinates。
    - `radar_chart` 適合在有 3+ 個已驗證參數時使用
    - `trend_prediction` 適合在確認漂移趨勢後使用
    
    **時機**: 可視化應在 Turn 4 之後使用,不要過早畫圖。
    先收集足夠的統計證據,再用圖表整合呈現。
    
    **注意**: 可視化不是必須的,但能讓思考過程更清晰。

    ### 5.9 嫌疑參數調查規則 (Suspect Investigation Protocol) [CRITICAL]
    
    **對 [線索追蹤] 中的 Top 3 參數各執行 1 Turn 完整分析。**
    每個參數可使用所有需要的工具, 但禁止延伸到新參數。
    
    **調查流程 (每個參數 1 Turn)**:
    ```
    Top 3 嫌疑參數 (A15, A255, A760)
         ↓
    Turn 2: A15 完整分析 (classify + distribution + 其他需要的工具) + 樣本線索
    Turn 3: A255 完整分析 + 樣本線索
    Turn 4: A760 完整分析 + 樣本線索
    Turn 5: 整合結果 + 結案
         ↓
    結果寫入報告:
    - FREEZE / 原始值域 < 0.01 → [已排除] 常量或凍結
    - DRIFT / LEVEL_SHIFT → [確認異常] 報告中記錄詳細結果
    - SPIKE → [孤立事件] 記錄在 isolated_observations
    ```
    
    **核心原則**:
    - 每個參數可做完整分析, 工具數量不限
    - **唯一限制**: 分析參數 A 時發現與參數 B 相關, 不去分析 B
      只記錄: "A 與 B 相關 (r=0.586), B 可作為追問方向"
    - Top 3 以外的嫌疑參數在報告中標記名稱 + Z-Score, 供用戶追問

    ### 6. Output Format
    回傳一個 JSON 物件:
    {
        "turn_thesis": "這個 Turn 要驗證的核心假設 (一句話)。",
        "answer_alignment": "使用者問的是: [重述使用者的問題]。目前分析進度: [已回答/部分回答/尚未回答]。缺少的部分: [列出]",
        "thought": {
            "user_intent": "使用者想知道什麼",
            "param_clue_progress": "參數線索進度: 已確認哪些參數異常？類型是什麼？還需驗證什麼？",
            "sample_clue_progress": "樣本線索進度: 異常樣本集中在哪？與參數線索是否對應？",
            "cross_clue": "兩條線索交叉後的核心問題是什麼？"
        },
        "hypothesis": "你的核心假設",
        "directive": {
            "param_questions": [
                "針對當前 Turn 的目標參數的分析問題 (至少 1 個)"
            ],
            "sample_questions": [
                "針對異常 Row 範圍的分析問題 (至少 1 個)"
            ]
        },
        "completeness_score": 3,
        "decision": "CONTINUE" | "FINISH",
        "reasoning": "簡短總結你的決策理由 (繁體中文)"
    }
    
    **answer_alignment 欄位強制規則** [ABSOLUTE RULE]:
    - 此欄位是**最先填寫**的欄位
    - 你必須用一句話重述使用者問的是什麼
    - 然後評估目前的分析結果是否在回答這個問題
    - 如果不是,你的 directive 必須修正方向,回到回答使用者問題的軌道上
    """

    def _build_dynamic_prompt(self, state: AnalysisState) -> str:
        """根据 current_knowledge 中的分析类型, 只注入对应的模式 prompt"""
        knowledge = getattr(state, "current_knowledge", "") or ""

        if "優化推薦" in knowledge or "优化推荐" in knowledge:
            mode_text = self.MODE_OPTIMIZATION
            mode_name = "優化推薦"
        elif "區段比較" in knowledge or "区段比较" in knowledge:
            mode_text = self.MODE_COMPARISON
            mode_name = "區段比較"
        elif "視覺化" in knowledge or "视觉化" in knowledge:
            mode_text = self.MODE_VISUALIZATION
            mode_name = "視覺化"
        else:
            mode_text = self.MODE_ANOMALY
            mode_name = "異常檢測"

        prompt = self.SYSTEM_PROMPT.replace("{analysis_mode_section}", mode_text)
        print(f"[Strategist] 動態注入分析模式: {mode_name}")
        return prompt

    async def execute(self, input_data: RoleInput) -> RoleOutput:
        state = input_data.state_machine
        targets = (
            getattr(state.current_context, "targets", [])
            if state.current_context
            else []
        )
        knowledge = getattr(state, "current_knowledge", "") or ""
        has_specific_targets = len(targets) > 0

        # =====================================================================
        # [DISPATCH] Turn 1 三路分派 (D / S / C)
        # =====================================================================
        if state.step_count == 1:
            has_domain_intent = getattr(state, "has_domain_intent", False)
            specified_tool = getattr(state, "specified_tool", None)

            if has_specific_targets and specified_tool:
                # 路徑 D: 有明確目標 + 有指定工具 → 精確執行, 跳過場景
                print(
                    f"[Strategist] [路徑 D] 精確指令: "
                    f"工具={specified_tool}, 目標={targets[:3]}"
                )
                return await self._generate_precise_experiments(
                    state, targets, specified_tool
                )

            elif has_specific_targets or has_domain_intent:
                # 路徑 S (統一場景): 有目標 和/或 有意圖
                # 意圖和目標不互斥, 同時送進場景生成
                _info_parts = []
                if has_specific_targets:
                    _info_parts.append(f"目標={targets[:3]}")
                if has_domain_intent:
                    _info_parts.append("有領域意圖")
                print(f"[Strategist] [路徑 S] 統一場景生成: {', '.join(_info_parts)}")
                return await self._generate_unified_scenes(state, targets)

            else:
                # 路徑 C: 無目標、無意圖 → 保留盲掃
                print("[Strategist] [路徑 C] 無目標無意圖, 執行盲掃")
                return self._generate_turn1_experiments(state)

        # =====================================================================
        # [DISPATCH] Turn 2 AutoTarget: 從 Turn 1 結果提取目標 (僅路徑 C 會到這)
        # =====================================================================
        auto_target_data = None
        if state.step_count == 2 and not has_specific_targets:
            # 優先從 state.auto_target_raw 讀取 (Synthesizer 已在 Turn 1 提取)
            _at_raw = getattr(state, "auto_target_raw", None)
            if _at_raw and _at_raw.get("auto_targets"):
                auto_target_data = _at_raw
            else:
                # Fallback: 若 Synthesizer 未提取, 由 Strategist 補充提取
                auto_target_data = self._extract_auto_targets(state)
            if auto_target_data and auto_target_data.get("auto_targets"):
                # 提取成功, 更新 targets 供後續 turn assignment 使用
                targets = auto_target_data["auto_targets"]
                has_specific_targets = True

        # 1. Construct Context from State
        context_str = self._build_context_str(state)

        # 1.5 [TURN-PARAMETER ASSIGNMENT] 強制指定本 Turn 必須分析的參數
        turn_assignment = ""
        if targets and len(targets) >= 2 and "[線索追蹤]" in knowledge:
            step = state.step_count
            n_targets = min(3, len(targets))
            if 2 <= step <= (n_targets + 1):
                assigned_param = targets[step - 2]
                other_params = [
                    t for i, t in enumerate(targets[:n_targets]) if i != step - 2
                ]
                other_str = ", ".join(other_params) if other_params else "無"
                turn_assignment = (
                    f"\n[MANDATORY - 本 Turn 指定參數] [ABSOLUTE RULE]\n"
                    f"本 Turn (Turn {step}) 你必須分析: {assigned_param}\n"
                    f"嚴禁在本 Turn 分析以下參數: {other_str}\n"
                    f"這些參數會在後續 Turn 分析, 本 Turn 不得提前處理。\n"
                    f"你的 directive 中的 param_questions 必須全部針對 {assigned_param}。\n"
                )
                print(f"[Strategist] Turn {step} 指定分析: {assigned_param}")
            elif step == (n_targets + 2):
                # 覆蓋檢查 Turn: 先做全域排除再結案
                turn_assignment = (
                    f"\n[MANDATORY - 全域覆蓋檢查 Turn] [ABSOLUTE RULE]\n"
                    f"所有 Top {n_targets} 參數已各完成 1 Turn 分析。\n"
                    f"本 Turn 必須執行全域覆蓋檢查, 確認有無遺漏的顯著因子:\n"
                    f"  1. 用 cv_ranking 全域掃描, 看有無其他 CV 極高但未分析的參數\n"
                    f"  2. 用 correlation_network 或 get_top_correlations(target=all) 確認無遺漏的 Hub 中樞\n"
                    f"  3. 若發現新的顯著參數, 標記為 [次要/補充] 發現\n"
                    f"  4. 完成覆蓋檢查後, 如果無新發現則可 FINISH\n"
                )
                print(f"[Strategist] Turn {step} 指定: 全域覆蓋檢查")
            elif step >= (n_targets + 3):
                turn_assignment = (
                    f"\n[MANDATORY - 結案 Turn] [ABSOLUTE RULE]\n"
                    f"所有 Top {n_targets} 參數已各完成 1 Turn 分析。\n"
                    f"全域覆蓋檢查已完成。本 Turn 必須整合結果並 FINISH。\n"
                )

        # 2. Build dynamic system prompt (only inject relevant mode)
        sys_prompt = self._build_dynamic_prompt(state)

        # 2b. [SCENE-AWARE] 如果已有場景, 在 user_prompt 中注入場景聚焦指令
        #     讓 LLM 在生成 directive 時就知道要分析哪些參數
        scene_focus = ""
        _existing_queue = getattr(state, "scene_queue", [])
        _existing_idx = getattr(state, "current_scene_index", -1)
        if _existing_queue and 0 <= _existing_idx < len(_existing_queue):
            _active = _existing_queue[_existing_idx]
            if _active.status == "ACTIVE":
                _targets_str = ", ".join(_active.targets[:10]) or "全域"
                scene_focus = (
                    f"\n\n███ [當前場景聚焦 - 最高優先] ███\n"
                    f"場景: {_active.scene_id} — {_active.label}\n"
                    f"目標參數: {_targets_str}\n"
                    f"[CRITICAL] 你的 directive 中所有分析問題必須針對上述目標參數。\n"
                    f"禁止分析不在此場景 targets 中的參數！\n"
                    f"如果你想分析 FORMULA-DCS_A15 但它不在 targets 中, 就不能分析它。\n"
                )

        # 3. Call LLM
        response = await self._call_llm(
            sys_prompt=sys_prompt,
            user_prompt=f"{turn_assignment}{scene_focus}\nUser Query: {state.original_query}\n\nCurrent Context:\n{context_str}",
        )

        # 3. Parse Output
        parsed = self._parse_json(response)

        # [FIX] JSON 解析失敗恢復: 如果有活躍場景, 用 _build_hard_directive 生成高品質 directive
        if parsed.get("decision") == "WAIT" and parsed.get("error"):
            scene_queue = getattr(state, "scene_queue", [])
            scene_idx = getattr(state, "current_scene_index", -1)
            if scene_queue and 0 <= scene_idx < len(scene_queue):
                active_scene = scene_queue[scene_idx]
                scene_targets = active_scene.targets[:5]
                targets_str = ", ".join(scene_targets) if scene_targets else "全域"

                # 累計此場景的 recovery 次數
                if not hasattr(active_scene, "_recovery_count"):
                    active_scene._recovery_count = 0
                active_scene._recovery_count += 1

                # 如果同一場景 recovery >= 2 次, 強制完成該場景
                if active_scene._recovery_count >= 2:
                    parsed = {
                        "decision": "CONTINUE",
                        "thought": (
                            f"[恢復] 場景 {active_scene.scene_id} 多次格式錯誤, "
                            f"強制完成並切換下一場景。"
                        ),
                        "reasoning": f"Recovery 次數過多, 強制完成 {active_scene.scene_id}",
                        "directive": (
                            f"[場景完成] {active_scene.scene_id}: "
                            f"多次 LLM 格式錯誤, 以現有發現結案。"
                        ),
                    }
                    print(
                        f"[Strategist RECOVERY] 場景 {active_scene.scene_id} "
                        f"recovery {active_scene._recovery_count} 次 → 強制完成"
                    )
                else:
                    # 使用 _build_hard_directive 生成有方向的 directive (不是通用訊息)
                    hard_dir = self._build_hard_directive(
                        active_scene, scene_targets, targets_str
                    )
                    parsed = {
                        "decision": "CONTINUE",
                        "thought": (
                            f"[恢復] LLM 回傳格式錯誤, 自動恢復。"
                            f" 繼續場景 {active_scene.scene_id}: {active_scene.label}"
                        ),
                        "reasoning": f"LLM 格式錯誤已恢復, 繼續 {active_scene.scene_id}",
                        "directive": hard_dir,
                    }
                    print(
                        f"[Strategist RECOVERY] JSON 解析失敗 → "
                        f"強制 CONTINUE + hard_directive, "
                        f"場景 {active_scene.scene_id} targets={targets_str}"
                    )
            else:
                # 沒有場景, 用原始查詢生成通用 directive
                parsed = {
                    "decision": "CONTINUE",
                    "thought": "[恢復] LLM 回傳格式錯誤, 使用通用分析方向。",
                    "reasoning": "LLM 格式錯誤已恢復, 繼續通用分析",
                    "directive": (
                        f"繼續分析用戶問題: {state.original_query}\n"
                        f"請根據已有發現, 進一步深入分析。"
                    ),
                }
                print("[Strategist RECOVERY] JSON 解析失敗 → 強制 CONTINUE (無場景)")

        # 3.5 [FLATTEN] 結構化 thought/directive → 扁平字串 (下游相容)
        thought_raw = parsed.get("thought", "")
        if isinstance(thought_raw, dict):
            flat_parts = []
            if thought_raw.get("user_intent"):
                flat_parts.append(f"[使用者意圖] {thought_raw['user_intent']}")
            if thought_raw.get("param_clue_progress"):
                flat_parts.append(
                    f"[參數線索進度] {thought_raw['param_clue_progress']}"
                )
            if thought_raw.get("sample_clue_progress"):
                flat_parts.append(
                    f"[樣本線索進度] {thought_raw['sample_clue_progress']}"
                )
            if thought_raw.get("cross_clue"):
                flat_parts.append(f"[交叉線索] {thought_raw['cross_clue']}")
            parsed["thought"] = "\n".join(flat_parts)

        directive_raw = parsed.get("directive", "")
        if isinstance(directive_raw, dict):
            flat_parts = []
            param_qs = directive_raw.get("param_questions", [])
            sample_qs = directive_raw.get("sample_questions", [])
            if param_qs:
                flat_parts.append(
                    "[參數問題]\n" + "\n".join(f"- {q}" for q in param_qs)
                )
            if sample_qs:
                flat_parts.append(
                    "[樣本問題]\n" + "\n".join(f"- {q}" for q in sample_qs)
                )
            parsed["directive"] = "\n\n".join(flat_parts)

        # 4. [GUARD] 無因果目標模式下，防止 LLM 自選目標變量 + 強制 rewrite target
        knowledge = getattr(state, "current_knowledge", "") or ""
        directive = parsed.get("directive", "")
        is_subject_mode = "調查對象]" in knowledge and "因果目標]" not in knowledge
        if is_subject_mode and directive:
            import re

            # [ENHANCED GUARD] 只攔截因果類工具的 target=某參數
            # 允許描述性/相關性工具 (get_top_correlations, cross_correlation_lag 等) 使用 Subject 作 target
            causal_tools = [
                "performance_segmentation",
                "analyze_feature_importance",
                "partial_dependence",
                "interaction_effect_test",
                "stratified_interaction",
                "batch_aggregation",
            ]
            original_directive = directive
            for tool_name in causal_tools:
                # 匹配 tool_name(...target=XXX...) 模式
                pattern = (
                    rf"({re.escape(tool_name)}\s*\([^)]*)"
                    rf"target\s*=\s*['\"]?([A-Z][A-Z0-9_-]+)['\"]?"
                )
                directive = re.sub(pattern, rf"\1target='all'", directive)
            if directive != original_directive:
                print(
                    f"[Strategist GUARD] Subject Mode: "
                    f"已將因果類工具的 target=XXX 替換為 target='all' (描述性工具保留)"
                )

            # 檢測 LLM 自選目標的措辭
            self_selected = re.search(
                r"(?:我選擇|選定|選取|作為初始目標|作為目標|因果目標|目標變量|驅動因子)",
                directive + " " + parsed.get("thought", ""),
            )
            if self_selected:
                print(
                    f"[Strategist GUARD] Subject Mode: "
                    f"LLM 使用了因果性語言 '{self_selected.group(0)}'，已在 directive 前插入提醒"
                )
                directive = (
                    "[系統提醒] 本次為調查對象模式 (Subject Mode)，沒有因果目標。"
                    "請只做描述性分析 (異常分類、分佈、趨勢、區段比較)，"
                    "不要尋找因果鏈或驅動因子。\n" + directive
                )
            parsed["directive"] = directive

        # 4b. [SCENE GENERATION] Turn 1 完成後, 建場景作為追蹤項目 (不執行)
        scene_queue = getattr(state, "scene_queue", [])
        step_count = getattr(state, "step_count", 1)
        _scenes_just_created = False
        if not scene_queue and step_count >= 2:
            # [Path A/B] Turn 1 已建好追蹤項目 → 直接 FINISH
            _t1_path = getattr(state, "turn1_path_type", "")
            _pending_items = getattr(state, "pending_follow_up_items", [])
            if (
                _t1_path in ("intent_scan", "direct_scan", "precise_tool")
                and _pending_items
            ):
                print(
                    f"[Strategist] Turn 2 路徑 {_t1_path}: "
                    f"Turn 1 已建 {len(_pending_items)} 個追蹤項目, FINISH"
                )
                return RoleOutput(
                    decision="FINISH",
                    reasoning=(
                        f"[Turn 2] Turn 1 ({_t1_path}) 掃描完成, "
                        f"已建立 {len(_pending_items)} 個後續追蹤場景。"
                    ),
                    directive="掃描結果已產出，列出後續追蹤項目",
                    experiments=[],
                    structured_log={
                        "turn1_type": _t1_path,
                        "auto_target_data": auto_target_data,
                        "follow_up_items": _pending_items,
                    },
                )

            # [Path C] 從 AutoTarget 結果或 LLM 建場景 → 作為追蹤項目 FINISH
            if auto_target_data and (
                auto_target_data.get("auto_targets")
                or auto_target_data.get("auto_row_ranges")
            ):
                generated_scenes = self._build_scenes_from_autotarget(
                    auto_target_data, state
                )
                print(
                    f"[Strategist] 路徑 C: 從四合一結果直接建立 "
                    f"{len(generated_scenes)} 個場景 (作為追蹤項目)"
                )
            else:
                generated_scenes = await self._generate_scenes(state)
            if generated_scenes:
                # --- [NEW] 場景作為追蹤項目，直接 FINISH ---
                follow_up_items = []
                for s in generated_scenes:
                    follow_up_items.append(
                        {
                            "scene_id": s.scene_id,
                            "label": s.label,
                            "scene_type": s.scene_type,
                            "targets": s.targets,
                        }
                    )
                scene_labels = [f"{s.scene_id}: {s.label}" for s in generated_scenes]
                print(
                    f"[Strategist] 路徑 C: {len(generated_scenes)} 個追蹤項目, FINISH"
                )

                return RoleOutput(
                    decision="FINISH",
                    reasoning=(
                        f"[Turn 2 路徑C: 四合一結果] "
                        f"建立 {len(generated_scenes)} 個後續追蹤場景。"
                    ),
                    directive="四合一掃描結果已產出，列出後續追蹤項目",
                    experiments=[],
                    structured_log={
                        "turn1_type": "autotarget_scan",
                        "auto_target_data": auto_target_data,
                        "follow_up_items": follow_up_items,
                        "knowledge_addon": (
                            f"\n[場景選單] 共 {len(generated_scenes)} 個追蹤項目: "
                            + " | ".join(scene_labels)
                        ),
                    },
                )

        # 5. [SCENE ENFORCEMENT] 在 directive 前面加入當前場景聚焦指令
        # 注意: 如果 _generate_scenes 剛產生了 scene_queue, 用本地變數;
        #       否則從 state 獲取 (已存在場景時)
        if not scene_queue:
            scene_queue = getattr(state, "scene_queue", [])
        scene_idx = getattr(state, "current_scene_index", -1)
        if scene_queue and scene_idx < 0:
            scene_idx = 0  # 新生成的場景, index 從 0 開始
        _scene_changed = False
        if scene_queue and 0 <= scene_idx < len(scene_queue):
            active_scene = scene_queue[scene_idx]
            if active_scene.status == "ACTIVE":
                # 累計此場景花費的 Turn 數
                active_scene.turns_spent += 1

                # [STALE FINDINGS] 連續無新發現 → 強制完成
                _MAX_TURNS_PER_SCENE = 3
                _force_complete = False
                if active_scene.turns_spent >= 2 and not _scenes_just_created:
                    _cur_fc = len(active_scene.findings)
                    _prev_fc = getattr(active_scene, "_prev_findings_count", 0)
                    if _cur_fc > 0 and _cur_fc <= _prev_fc:
                        parsed["directive"] = (
                            f"[場景完成] {active_scene.scene_id}: "
                            f"連續無新發現, 以現有 {_cur_fc} 項結論結案。"
                        )
                        _force_complete = True
                        print(
                            f"[Strategist] 場景 {active_scene.scene_id} "
                            f"連續無新發現 ({_cur_fc} 項) → 強制完成"
                        )
                    active_scene._prev_findings_count = _cur_fc

                # [MAX TURNS 強制截斷] 單場景最多 3 Turn
                if (
                    not _force_complete
                    and active_scene.turns_spent >= _MAX_TURNS_PER_SCENE
                ):
                    parsed["directive"] = (
                        f"[場景完成] {active_scene.scene_id}: "
                        f"已達 {active_scene.turns_spent} Turn 上限, "
                        f"以現有發現結案。"
                    )
                    _force_complete = True
                    print(
                        f"[Strategist] 場景 {active_scene.scene_id} "
                        f"達到 {_MAX_TURNS_PER_SCENE} Turn → 強制完成"
                    )

                _type_map = {
                    "parameter": "參數",
                    "interaction": "交互",
                    "segment": "區段",
                    "optimization": "最佳化",
                }
                type_label = _type_map.get(active_scene.scene_type, "參數")
                # 計算場景 Turn 預算
                pending = sum(1 for s in scene_queue if s.status == "PENDING")

                _scene_turns_left = _MAX_TURNS_PER_SCENE - active_scene.turns_spent
                scene_prefix = (
                    f"[當前場景] {active_scene.scene_id}: {type_label} — "
                    f"{active_scene.label} "
                    f"(已花 {active_scene.turns_spent}/{_MAX_TURNS_PER_SCENE} Turn)\n"
                    f"  targets: {', '.join(active_scene.targets[:5])}\n"
                    f"  場景剩餘 Turn: {_scene_turns_left}, 待辦場景: {pending} 個\n"
                    f"  所有分析必須針對此場景, 禁止跳到其他場景的參數。\n"
                    f"  新發現 → 記入 [潛在線索], 不中斷當前場景。\n"
                    f"  分析到位後, 在 directive 末尾加: "
                    f"[場景完成] {active_scene.scene_id}: 主要發現\n"
                )
                # [覆蓋缺口優先] 場景即將超時, 提醒優先處理覆蓋缺口
                if active_scene.turns_spent >= 2:
                    scene_prefix += (
                        "\n███ [注意] 此場景僅剩最後 1 Turn, 下一輪將強制切換。\n"
                        "如有覆蓋缺口或未分析的 targets, 本 Turn 務必優先處理！\n"
                    )

                # === [HARD OVERRIDE] 直接用場景 targets 重寫 directive ===
                # 但如果已被 _force_complete 強制完成, 則跳過 (保留 [場景完成] 標記)
                scene_targets = active_scene.targets[:5]
                if _force_complete:
                    pass  # 保留 max-turns 強制完成的 directive
                elif scene_targets:
                    targets_str = ", ".join(scene_targets)
                    hard_directive = self._build_hard_directive(
                        active_scene, scene_targets, targets_str
                    )
                    print(
                        f"[Strategist] 場景 {active_scene.scene_id} "
                        f"硬替換 directive + thought → targets: {targets_str}"
                    )
                    parsed["directive"] = scene_prefix + hard_directive
                    # 同步覆寫 thought, 防止顯示與場景無關的參數名
                    parsed["thought"] = (
                        f"[場景聚焦] 當前分析場景: {active_scene.scene_id} — "
                        f"{active_scene.label}\n"
                        f"目標參數: {targets_str}\n"
                        f"本 Turn 所有分析僅針對上述參數展開。"
                    )
                else:
                    # 無 targets 的場景, 保留 LLM 原始 directive + 場景前綴
                    current_dir = parsed.get("directive", "") or ""
                    parsed["directive"] = scene_prefix + current_dir

        # 5b. [SCENE TRANSITION] 檢測場景完成標記, 更新 scene_queue
        directive_text = parsed.get("directive", "") or ""
        if (
            "場景完成" in directive_text
            and scene_queue
            and not _scene_changed
            and not _scenes_just_created
        ):
            import re as _re

            # 匹配所有場景 ID 格式: P1, SEG1, S1, T1, TSEG1, A2.1, S3.2 等
            completed_match = _re.search(
                r"\[場景完成\]\s*((?:TSEG|T|P|SEG|S|A)\d+(?:\.\d+)?)", directive_text
            )
            if completed_match:
                completed_id = completed_match.group(1)
                for s in scene_queue:
                    if s.scene_id == completed_id and s.status == "ACTIVE":
                        # [GUARD] 最低 Turn 數保護: 場景至少要跑 2 Turn 才允許完成
                        if s.turns_spent < 2:
                            print(
                                f"[Strategist SCENE] {completed_id} "
                                f"僅跑了 {s.turns_spent} Turn, "
                                f"忽略 [場景完成] 標記, 強制繼續分析"
                            )
                            # 移除 [場景完成] 標記, 改為繼續指令
                            parsed["directive"] = (
                                f"[場景繼續] {completed_id}: "
                                f"分析尚未充分 (僅 {s.turns_spent} Turn), "
                                f"請繼續深入分析此場景的目標參數。"
                            )
                            break
                        s.status = "COMPLETED"
                        # 提取發現摘要
                        finding_match = _re.search(
                            r"\[場景完成\]\s*((?:TSEG|T|P|SEG|S|A)\d+(?:\.\d+)?)[:\s]*(.*?)(?:\n|$)",
                            directive_text,
                        )
                        if finding_match:
                            s.findings.append(finding_match.group(2).strip())
                        print(f"[Strategist SCENE] {completed_id} 完成, 切換下一場景")
                        break
                # 找到下一個 PENDING 場景
                next_idx = -1
                for i, s in enumerate(scene_queue):
                    if s.status == "PENDING":
                        s.status = "ACTIVE"
                        next_idx = i
                        print(f"[Strategist SCENE] 切換到 {s.scene_id}: {s.label}")
                        break
                if next_idx >= 0:
                    scene_idx = next_idx
                _scene_changed = True

        # 5b-2. 場景有變更 → 透過 structured_log 傳回給 orchestrator
        if _scene_changed:
            parsed.setdefault("_scene_updates", {})
            parsed["_scene_updates"]["scene_queue"] = scene_queue
            parsed["_scene_updates"]["current_scene_index"] = scene_idx
            parsed["_scene_updates"]["_prev_scene_index"] = state.current_scene_index
            parsed["_scene_updates"]["coverage_pct"] = getattr(
                self, "_last_coverage_pct", 0.0
            )

            # [FIX] 場景切換後, 必須用新場景的 targets 重寫 directive + experiments
            if 0 <= scene_idx < len(scene_queue):
                # 自動把前一個 ACTIVE 場景標記為 COMPLETED
                prev_idx = parsed.get("_scene_updates", {}).get(
                    "_prev_scene_index", state.current_scene_index
                )
                if prev_idx is not None and 0 <= prev_idx < len(scene_queue):
                    prev_scene = scene_queue[prev_idx]
                    if prev_scene.status == "ACTIVE" and prev_idx != scene_idx:
                        prev_scene.status = "COMPLETED"
                        print(
                            f"[Strategist SCENE] 場景切換: 自動完成 "
                            f"{prev_scene.scene_id} (ACTIVE → COMPLETED)"
                        )
                new_scene = scene_queue[scene_idx]
                new_targets = new_scene.targets[:5]
                if new_targets:
                    new_targets_str = ", ".join(new_targets)
                    _type_map = {
                        "parameter": "參數",
                        "interaction": "交互",
                        "segment": "區段",
                    }
                    new_type_label = _type_map.get(new_scene.scene_type, "參數")
                    hard_directive = self._build_hard_directive(
                        new_scene, new_targets, new_targets_str
                    )

                    parsed["directive"] = (
                        f"[場景切換] 進入 {new_scene.scene_id}: {new_type_label} — "
                        f"{new_scene.label}\n"
                        f"  targets: {new_targets_str}\n\n" + hard_directive
                    )
                    parsed["thought"] = (
                        f"[場景切換] 當前分析場景: {new_scene.scene_id} — "
                        f"{new_scene.label}\n"
                        f"目標參數: {new_targets_str}\n"
                        f"本 Turn 所有分析僅針對上述參數展開。"
                    )
                    # 不再產生 _new_experiments, 讓 Planner 根據 directive 自行選工具

                    print(
                        f"[Strategist] 場景切換後重寫 directive: "
                        f"{new_scene.scene_id} targets={new_targets_str}"
                    )

        # 5c. [COVERAGE ENFORCEMENT] Strategist 只負責提出 "哪些問題還沒回答"
        #    Planner 負責選擇具體工具去回答 (角色分離)
        step_count = getattr(state, "step_count", 1)
        uncovered_gaps = getattr(self, "_last_uncovered_gaps", []) or []

        if step_count >= 3 and uncovered_gaps:
            gap_list = "\n".join(
                f"  {i + 1}. {gap}" for i, gap in enumerate(uncovered_gaps[:3])
            )
            coverage_supplement = (
                "\n\n[覆蓋缺口 - 以下問題尚未回答] [CRITICAL]\n"
                f"{gap_list}\n"
                "Planner 必須選擇合適的工具來回答上述問題。\n"
                "完成後覆蓋率才能提升。\n"
            )
            current_directive = parsed.get("directive", "") or ""
            parsed["directive"] = current_directive + coverage_supplement
            print(
                f"[Strategist COVERAGE] Turn {step_count}: "
                f"尚未回答 {uncovered_gaps[:3]}"
            )

        # 5d. [COVERAGE ENFORCEMENT] 覆蓋率達標時, Strategist 代碼層級強制 FINISH
        #    這是 Strategist 的核心職責: 判斷答案是否已充分回答用戶問題
        #    注意: 場景剛建立時 state.scene_queue 尚未更新, 必須用本地 scene_queue
        _coverage_pct = getattr(self, "_last_coverage_pct", 0.0)
        _uncovered = getattr(self, "_last_uncovered_gaps", []) or []
        _decision = parsed.get("decision", "CONTINUE")

        # [GUARD] 場景剛建立 → 禁止立即結案, 必須先跑完場景
        if _scenes_just_created:
            if _decision == "FINISH":
                _decision = "CONTINUE"
                parsed["decision"] = "CONTINUE"
                print("[Strategist] 場景剛建立, 禁止立即 FINISH → 強制 CONTINUE")
        elif _decision != "FINISH" and _coverage_pct >= 0.7 and not _uncovered:
            # 用本地 scene_queue (包含剛建立的場景), 而非 state.scene_queue
            _effective_queue = (
                scene_queue
                if scene_queue
                else (getattr(state, "scene_queue", []) or [])
            )
            _all_scenes_done = (
                all(s.status == "COMPLETED" for s in _effective_queue)
                if _effective_queue
                else True
            )

            if _all_scenes_done:
                _decision = "FINISH"
                parsed["directive"] = (
                    f"[覆蓋率達標] 回答覆蓋率 {_coverage_pct:.0%}, "
                    f"所有場景已完成, Strategist 判定結束分析。"
                )
                print(
                    f"[Strategist COVERAGE FINISH] "
                    f"coverage={_coverage_pct:.0%}, "
                    f"uncovered=0, scenes_done={_all_scenes_done} "
                    f"→ 強制 FINISH"
                )

        # 6. Construct RoleOutput
        _structured_log = {
            "thought": parsed.get("thought", ""),
            "turn_thesis": parsed.get("turn_thesis", ""),
            "answer_alignment": parsed.get("answer_alignment", ""),
        }
        # 場景更新透過 structured_log 傳遞給 orchestrator
        if parsed.get("_scene_updates"):
            _structured_log["_scene_updates"] = parsed["_scene_updates"]

        # AutoTarget 更新透過 structured_log 傳遞給 orchestrator
        if auto_target_data and auto_target_data.get("auto_targets"):
            _structured_log["auto_target_data"] = auto_target_data

        return RoleOutput(
            decision=_decision,
            reasoning=parsed.get("reasoning", ""),
            hypothesis=parsed.get("hypothesis"),
            directive=parsed.get("directive"),
            structured_log=_structured_log,
        )

    def _build_context_str(self, state: AnalysisState) -> str:
        """
        Build a concise context string from the state machine.
        使用滾動摘要 + 最近 3 步，避免 Strategist 遺忘早期發現。
        """
        # [FIX] 最先呈現使用者問題對齊狀態 (放在 context 開頭,確保 LLM 首先看到)
        ctx = self._check_query_alignment(state)
        ctx += "\n"

        # Current Step & Resource
        ctx += f"Current Step: {state.step_count} / {state.max_steps}\n"

        # [NEW] Scene Status Injection
        scene_queue = getattr(state, "scene_queue", [])
        if scene_queue:
            ctx += "\n=== 場景進度 ===\n"
            for i, scene in enumerate(scene_queue):
                if scene.status == "ACTIVE":
                    marker = "→ 當前"
                elif scene.status == "COMPLETED":
                    marker = "  完成"
                else:
                    marker = "  待辦"
                type_label = "參數" if scene.scene_type == "parameter" else "區段"
                ctx += f"  [{marker}] {scene.scene_id}: {type_label} — {scene.label}\n"
                if scene.findings:
                    for f in scene.findings[:2]:
                        ctx += f"    發現: {f}\n"
            backlog = getattr(state, "scene_backlog", [])
            if backlog:
                ctx += f"  待辦新增: {len(backlog)} 個場景\n"
            ctx += "================\n"

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
        _raw_summary = get_summary(state.current_knowledge)
        if _raw_summary:
            from backend.services.analysis.agents.roles_v2.synthesizer import (
                format_rolling_summary,
            )

            _formatted = format_rolling_summary(_raw_summary)
            ctx += f"\n=== Previous Findings ===\n{_formatted}\n"

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

        # [REFACTORED] 從 Synthesizer 結構化輸出讀取里程碑和覆蓋率
        # Strategist 自行判斷下一步方向, 不依賴 Synthesizer 的工具建議
        if state.history:
            latest = state.history[-1]
            if hasattr(latest, "evidence") and isinstance(latest.evidence, dict):
                s_log = latest.evidence.get("structured_log", {})
                if isinstance(s_log, dict):
                    milestones = s_log.get("completed_milestones", [])
                    coverage = s_log.get("intent_coverage", 0)
                    if milestones:
                        ctx += f"\n=== 已完成的里程碑 ===\n"
                        ctx += f"{', '.join(milestones)}\n"
                    ctx += f"\n[COVERAGE] intent_coverage = {coverage}%\n"
                    if coverage < 70:
                        ctx += "[指示] 覆蓋率不足 70%, 必須 CONTINUE, 不得 FINISH。\n"
                        ctx += "請根據分析摘要和已完成的里程碑, 自行判斷下一步應往哪個方向深入。\n"

        # [NEW] Duplicate Analysis Detection (tool+params combinations)
        ctx += self._check_analysis_repetition(state)

        # Query alignment 已移到 context 開頭 (line ~471), 不在末尾重複

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

    async def _generate_scenes(self, state: AnalysisState) -> list:
        """
        [LLM-Driven Scene Generation]
        根據 Turn 1 掃描結果 + 用戶問題, 用 LLM 生成語意化調查場景。
        動態構建 prompt, 確保 LLM 使用實際參數名稱而非範例。
        """
        import json as _json

        query = getattr(state, "original_query", "") or ""

        # --- 收集 Turn 1 結果摘要 + 提取實際參數名 ---
        turn1_findings = []
        actual_params = []  # 實際異常參數名
        actual_segments = []  # 實際異常區段
        correlation_info = []  # 相關性資訊

        for step in (state.history or [])[-5:]:
            evidences = getattr(step, "evidences", []) or []
            for ev in evidences:
                if getattr(ev, "status", "") != "SUCCESS":
                    continue
                tool = getattr(ev, "tool_name", "")
                result = ev.result if isinstance(ev.result, dict) else {}

                if tool == "detect_outliers":
                    top_params = result.get("top_abnormal_parameters", {})
                    if top_params:
                        for k, v in list(top_params.items())[:5]:
                            actual_params.append({"name": k, "z_score": v})
                        params_str = ", ".join(
                            f"{p['name']} (Z={p['z_score']})" for p in actual_params
                        )
                        turn1_findings.append(f"異常參數: {params_str}")

                elif tool == "scan_anomaly_segments":
                    segments = result.get("anomaly_segments", [])
                    # 提取多個區段 (多餘的存入 knowledge, 供續查使用)
                    for s in segments[:8]:
                        seg_info = {
                            "range": f"Row {s.get('start', '?')}-{s.get('end', '?')}",
                            "severity": s.get("severity", "?"),
                            "params": s.get("involved_params", [])[:3],
                        }
                        actual_segments.append(seg_info)
                    if actual_segments:
                        # 全部記入 findings (供續查時讀取)
                        seg_str = ", ".join(
                            f"{s['range']} (severity={s['severity']})"
                            for s in actual_segments
                        )
                        turn1_findings.append(f"異常區段: {seg_str}")

                elif tool == "get_top_correlations":
                    corr_data = result.get("correlations", [])
                    if isinstance(corr_data, list):
                        for c in corr_data[:5]:
                            if isinstance(c, dict) and abs(c.get("r", 0)) > 0.3:
                                correlation_info.append(
                                    f"{c.get('param_a', '?')} ↔ {c.get('param_b', '?')} (r={c.get('r', 0):.2f})"
                                )

                elif tool == "classify_anomaly_type":
                    anomalies = result.get("anomalies", {})
                    if anomalies:
                        types_str = ", ".join(
                            f"{k}: {v.get('type', 'unknown')}"
                            for k, v in list(anomalies.items())[:5]
                        )
                        turn1_findings.append(f"異常類型: {types_str}")

                elif tool == "hotelling_t2_analysis":
                    outlier_rows = result.get("outlier_rows", [])
                    if outlier_rows:
                        turn1_findings.append(f"多變量異常: {len(outlier_rows)} 個樣本")

        findings_text = (
            "\n".join(turn1_findings) if turn1_findings else "初步掃描尚無明確結果"
        )

        if correlation_info:
            findings_text += "\n相關性: " + "; ".join(correlation_info[:5])

        # --- [NEW] Fallback: 從 state.discovered_sites 補充區段資訊 ---
        if not actual_segments:
            sites = getattr(state, "discovered_sites", [])
            for site in sites:
                seg_range = getattr(site, "range", "")
                seg_score = getattr(site, "score", 0)
                if seg_range and seg_score > 0:
                    actual_segments.append(
                        {
                            "range": seg_range,
                            "severity": seg_score,
                            "params": [],
                        }
                    )
            if actual_segments:
                seg_str = ", ".join(
                    f"{s['range']} (severity={s['severity']})"
                    for s in actual_segments[:3]
                )
                turn1_findings.append(f"異常區段: {seg_str}")
                findings_text += f"\n異常區段: {seg_str}"
                print(
                    f"[Strategist] 從 discovered_sites 補充 {len(actual_segments)} 個區段"
                )

        # --- [NEW] Fallback 2: 從 knowledge 中解析 AutoTarget 區段 ---
        if not actual_segments:
            import re as _re_seg

            knowledge = getattr(state, "current_knowledge", "") or ""
            # 匹配 "Row XX-YY" 模式
            row_matches = _re_seg.findall(r"Row\s+(\d+)\s*[-~]\s*(\d+)", knowledge)
            for start_str, end_str in row_matches[:3]:
                actual_segments.append(
                    {
                        "range": f"Row {start_str}-{end_str}",
                        "severity": 3,
                        "params": [],
                    }
                )
            if actual_segments:
                seg_str = ", ".join(s["range"] for s in actual_segments)
                findings_text += f"\n異常區段 (從知識庫提取): {seg_str}"
                print(f"[Strategist] 從 knowledge 解析 {len(actual_segments)} 個區段")

        # --- [NEW] Step 1: 用 LLM 篩選與用戶問題語意相關的參數 ---
        domain_relevant_params = []
        all_columns = list(getattr(state, "data_schema", {}).keys())
        if all_columns and query and len(query) > 2:
            # 截取前 200 個欄位名 (避免 prompt 過長)
            col_sample = all_columns[:200]
            col_list_str = ", ".join(col_sample)
            if len(all_columns) > 200:
                col_list_str += f"\n... (共 {len(all_columns)} 個欄位, 僅列出前 200 個)"

            # --- [NEW] 註入術語對應表讓 LLM 理解欄位的中文含義 ---
            mapping_hint = ""
            term_mappings = getattr(state, "term_mappings", {})
            if term_mappings:
                # 只取與當前欄位相關的 mapping (交集), 最多 100 組
                relevant_mappings = {
                    k: v for k, v in term_mappings.items() if k in set(all_columns)
                }
                if relevant_mappings:
                    mapping_lines = [
                        f"  {code} = {name}"
                        for code, name in list(relevant_mappings.items())[:100]
                    ]
                    mapping_hint = (
                        "\n\n[術語對應表] 以下是欄位編號對應的中文名稱:\n"
                        + "\n".join(mapping_lines)
                        + "\n請利用此對應表理解各欄位的實際含義, "
                        "從而更準確地判斷哪些欄位與用戶問題相關。\n"
                    )
                    print(
                        f"[Strategist] 注入術語對應表: "
                        f"{len(relevant_mappings)} 個映射 (共 {len(term_mappings)} 個)"
                    )

            relevance_prompt = (
                "你是工業數據專家。以下是數據集中的所有欄位名稱:\n"
                f"{col_list_str}\n"
                f"{mapping_hint}\n"
                f"用戶問題: {query}\n\n"
                "請從上方欄位中, 挑出最可能與用戶問題語意相關的參數。\n"
                "判斷依據: 欄位名稱中的關鍵字是否與用戶問題的主題有關。\n"
                "如果有術語對應表, 請優先利用中文名稱來判斷欄位與問題的關聯性。\n"
                "例如: 如果用戶問「水份不均」, 則含有 MOISTURE, HUMID, DRYER, WATER 等詞的欄位都相關。\n"
                "例如: 如果用戶問「斷紙原因」, 則含有 TENSION, PRESS, SPEED, BREAK 等詞的欄位都相關。\n\n"
                "規則:\n"
                "- 回傳 JSON 陣列, 只包含相關的欄位名稱 (必須完全匹配上方列表)\n"
                "- 最多挑 30 個\n"
                "- 如果無法判斷 (問題太模糊), 回傳空陣列 []\n"
                "- 只回傳 JSON 陣列, 不要其他文字\n"
            )
            try:
                rel_resp = await self.llm.acomplete(relevance_prompt)
                rel_text = str(rel_resp.text).strip()
                if "```" in rel_text:
                    import re as _re2

                    json_match = _re2.search(r"\[.*\]", rel_text, _re2.DOTALL)
                    if json_match:
                        rel_text = json_match.group(0)
                domain_relevant_params = _json.loads(rel_text)
                if not isinstance(domain_relevant_params, list):
                    domain_relevant_params = []
                # 驗證: 只保留實際存在的欄位名
                all_columns_set = set(all_columns)
                domain_relevant_params = [
                    p for p in domain_relevant_params if p in all_columns_set
                ]
                if domain_relevant_params:
                    print(
                        f"[Strategist] 語意篩選: 從 {len(all_columns)} 個欄位中找到 "
                        f"{len(domain_relevant_params)} 個與「{query[:20]}」相關的參數"
                    )
            except Exception as e:
                print(f"[Strategist] Domain relevance filter failed: {e}")
                domain_relevant_params = []

        # --- 將語意相關參數加入 findings ---
        if domain_relevant_params:
            findings_text += (
                f"\n\n[語意相關參數] 以下 {len(domain_relevant_params)} 個參數"
                f"與用戶問題「{query[:30]}」語意相關:\n"
                + ", ".join(domain_relevant_params[:30])
            )

        # --- 構建動態範例 (優先語意相關 > 掃描異常 > 區段) ---
        examples = []
        # S1: 語意相關參數優先
        if domain_relevant_params:
            dp1 = domain_relevant_params[0]
            examples.append(
                f'{{"scene_id": "A1", "type": "parameter", '
                f'"label": "{dp1} 與用戶問題的關聯調查", '
                f'"targets": ["{dp1}"]}}'
            )
            if len(domain_relevant_params) >= 3:
                dp2 = domain_relevant_params[1]
                dp3 = domain_relevant_params[2]
                examples.append(
                    f'{{"scene_id": "A2", "type": "interaction", '
                    f'"label": "{dp2} 與 {dp3} 的交互作用分析", '
                    f'"targets": ["{dp2}", "{dp3}"]}}'
                )
        # 掃描異常參數作為補充場景
        if actual_params:
            p1 = actual_params[0]["name"]
            sid = f"A{len(examples) + 1}"
            examples.append(
                f'{{"scene_id": "{sid}", "type": "parameter", '
                f'"label": "{p1} 統計異常調查 (Z-Score)", '
                f'"targets": ["{p1}"]}}'
            )
        # 區段場景
        if actual_segments:
            seg = actual_segments[0]
            sid = f"A{len(examples) + 1}"
            examples.append(
                f'{{"scene_id": "{sid}", "type": "segment", '
                f'"label": "{seg["range"]} 異常區段前後差異分析", '
                f'"targets": []}}'
            )

        # --- [NEW] 注入用戶意圖分解結果 ---
        intent_text = ""
        query_intents = getattr(state, "query_intents", []) or []
        if query_intents:
            intent_lines = [
                f"  {i + 1}. {intent}" for i, intent in enumerate(query_intents[:6])
            ]
            intent_text = (
                "\n\n[用戶意圖分解] LLM 已將用戶問題分解為以下意圖:\n"
                + "\n".join(intent_lines)
                + "\n"
            )
            print(f"[Strategist] 注入 {len(query_intents)} 個用戶意圖到場景生成 prompt")

        examples_text = "\n".join(f"  {e}" for e in examples)

        # ── 快速 vs 深度模式: 場景數量 ──
        _is_quick = getattr(state, "max_steps", 10) <= 5
        _scene_count_hint = (
            "只規劃 2 個調查場景 (1 個參數分析 + 1 個區段分析)"
            if _is_quick
            else "規劃 3-6 個調查場景"
        )

        prompt = (
            f"你是數據分析策略師。根據以下掃描結果和用戶問題，{_scene_count_hint}。\n"
            "每個場景是一個調查方向，需要 1-3 Turn 完成。\n\n"
            f"用戶問題: {query}\n"
            f"{intent_text}\n"
            f"掃描發現:\n{findings_text}\n\n"
        )

        # 根據是否有意圖分解，使用不同的場景設計指導
        if query_intents:
            prompt += (
                "██ [核心原則: 意圖驅動場景設計] ██\n"
                "你必須根據上方「用戶意圖分解」來設計場景。\n"
                "每個場景應對應 1-2 個意圖，確保所有意圖都被覆蓋。\n\n"
                "[場景類型映射]\n"
                "  - 描述性統計/分佈 → type: parameter, 使用 Top 異常參數\n"
                "  - 異常值識別 → type: parameter, 使用掃描發現的異常參數\n"
                "  - 關聯性/共線性 → type: interaction, 使用高相關的參數對\n"
                "  - 關鍵因素/影響力 → type: parameter, 使用 Top 貢獻參數\n"
                "  - 分組/區段對比 → type: segment, 使用異常區段\n"
                "  - 異常區段深入分析 → type: segment, 使用異常區段\n\n"
                "[targets 選擇規則]\n"
                "  - 每個場景的 targets 必須來自「掃描發現」中的實際參數名或區段\n"
                "  - 不同場景應使用不同的參數，避免重複\n"
                "  - interaction 類型的場景: targets 放 2-3 個需要比較的參數\n"
                "  - segment 類型的場景: targets 可以為空 (會自動補充區段參數)\n"
                "  - 禁止編造不存在的參數名稱\n\n"
            )
        else:
            prompt += (
                "[場景 label 設計]\n"
                "  - label 描述調查方向, 應貼合用戶問題\n"
                "  - label 可以用較大的主題 (如「壓力類參數群組異常分析」「異常區段根因調查」)\n"
                "  - label 可以引用用戶問題中的概念 (如用戶問「斷紙原因」→ label 可含「斷紙」)\n"
                "  - label 不需要列出所有參數, 但需讓人理解調查目的\n\n"
                "███ [targets 規則 - 最重要] ███\n"
                "  場景 targets 的優先順序:\n"
                "  1. 【最優先】語意相關參數 — 與用戶問題直接相關的參數\n"
                "     (例如用戶問斷紙 → SPEED, TENSION, PRESS, BREAK 類參數)\n"
                "  2. 【次要】掃描發現的異常參數 — Z-Score 最高的參數作為補充場景\n"
                "  3. 【禁止】不在上述兩類中的參數名稱\n\n"
                "  前 2-3 個場景: 使用與用戶問題語意相關的參數\n"
                "  後續場景: 使用掃描發現的 Top Z-Score 異常參數\n"
                "  最後 1 個場景: 可用異常區段 (如果有)\n\n"
            )

        prompt += (
            "[場景設計原則]\n"
            "  - 場景應圍繞用戶問題展開, 用語意相關參數為主要調查對象\n"
            "  - 掃描發現的統計異常參數作為補充調查方向\n"
            "  - 如果掃描發現中有異常區段 (Row 範圍), 至少包含 1 個 segment 類型場景\n"
            "  - 場景不能是通用教科書步驟 (如「初步探索分佈」「缺失值分析」)\n"
            "  - 不同場景必須使用不同的 targets, 禁止多個場景共用相同參數\n\n"
            "███ [label 描述規則 - 必須遵守] ███\n"
            "  場景 label 必須描述【分析動作】而非【識別/找出/繪圖動作】。\n"
            "  概念展開階段已自動找出相關參數, 場景的目的是對這些參數做深入分析。\n\n"
            "  [禁止的 label 寫法] 以下詞彙會導致系統誤判為繪圖請求, 嚴禁使用:\n"
            "    找出、識別、列出、篩選、確認哪些、盤點、搜尋、\n"
            "    趨勢、趨勢圖、數值趨勢、畫圖、繪製、繪圖\n"
            "  [正確的 label 寫法] 必須使用分析類動詞:\n"
            "    分析...的異常模式與波動、探討...的關聯性、調查...的異常原因、\n"
            "    比較...的變異特徵、評估...的影響因素、檢驗...的因果關係\n\n"
            "  [範例對照]\n"
            "    BAD:  找出與水分相關的參數數值趨勢\n"
            "    GOOD: 分析水分相關參數 (如乾燥溫度、蒸氣流量) 的異常模式與波動特徵\n\n"
            "    BAD:  找出影響斷紙的參數趨勢\n"
            "    GOOD: 分析張力與壓力類參數的交互作用，評估其對斷紙事件的影響\n\n"
            "[GOOD EXAMPLES] 正確的場景示例:\n"
            f"{examples_text}\n\n"
            "規則:\n"
            "- scene_id: S1, S2, S3... 依序編號\n"
            "- type: parameter / interaction / segment / comparison\n"
            "- label: 調查方向描述 (中文, 必須是分析類動詞開頭, 貼合用戶問題)\n"
            "- targets: 優先使用語意相關參數, 其次掃描異常參數\n"
            "- 按與用戶問題的相關度排序\n\n"
            "只回傳 JSON 陣列, 不要其他文字:\n"
        )

        try:
            resp = await self.llm.acomplete(prompt)
            resp_text = str(resp.text).strip()

            # 清理 LLM 回應: 移除可能的 markdown 包裹
            if "```" in resp_text:
                import re as _re

                json_match = _re.search(r"\[.*\]", resp_text, _re.DOTALL)
                if json_match:
                    resp_text = json_match.group(0)

            scenes_data = _json.loads(resp_text)
            if not isinstance(scenes_data, list):
                scenes_data = [scenes_data]

            # 構建白名單: 掃描發現的參數 + 語意相關參數 + 所有欄位
            from backend.services.analysis.analysis_types import SceneItem

            scan_param_names = {p["name"] for p in actual_params}
            domain_param_set = set(domain_relevant_params)
            all_columns_set = set(all_columns) if all_columns else set()
            whitelist = scan_param_names | domain_param_set | all_columns_set

            scenes = []
            for i, sd in enumerate(scenes_data):
                scene_type = sd.get("type", "parameter")
                if scene_type in ("interaction", "comparison"):
                    effective_type = "parameter"
                else:
                    effective_type = scene_type

                # 驗證 targets: 必須存在於白名單中
                raw_targets = sd.get("targets", [])
                valid_targets = [t for t in raw_targets if t in whitelist]

                # 如果 targets 全部無效, 優先從語意相關參數補充, 其次掃描發現
                if not valid_targets:
                    if domain_relevant_params:
                        start_idx = i % len(domain_relevant_params)
                        valid_targets = [domain_relevant_params[start_idx]]
                    elif actual_params:
                        start_idx = i % len(actual_params)
                        valid_targets = [actual_params[start_idx]["name"]]
                    if valid_targets:
                        print(
                            f"[Strategist] 場景 S{i + 1} targets 無效 "
                            f"({raw_targets}), 替換為: {valid_targets}"
                        )

                scenes.append(
                    SceneItem(
                        scene_id=sd.get("scene_id", f"A{i + 1}"),
                        scene_type=effective_type,
                        label=sd.get("label", f"場景 {i + 1}"),
                        targets=valid_targets,
                        severity=float(6 - i),
                        status="ACTIVE" if i == 0 else "PENDING",
                        source="Strategist LLM 生成",
                    )
                )
            # === [POST-VALIDATION] 強制補充缺失的場景類型 ===
            # 1. 如果有異常區段但沒有 segment 場景, 強制補充 (所有模式)
            has_segment_scene = any(s.scene_type == "segment" for s in scenes)
            if actual_segments and not has_segment_scene:
                seg_targets = []
                for seg in actual_segments[:2]:
                    seg_params = seg.get("params", [])
                    seg_targets.extend(seg_params[:2])
                seg_ranges = ", ".join(s["range"] for s in actual_segments[:2])
                seg_scene = SceneItem(
                    scene_id=f"A{len(scenes) + 1}",
                    scene_type="segment",
                    label=f"異常區段 ({seg_ranges}) 根因調查",
                    targets=seg_targets,
                    severity=2.0,
                    status="PENDING",
                    source="自動補充 (缺少 segment 場景)",
                )
                scenes.append(seg_scene)
                print(f"[Strategist] 自動補充 segment 場景: {seg_ranges}")

            # 2. (僅深度模式) 如果 AutoTarget 的異常參數完全未被任何場景覆蓋, 補充一個
            if not _is_quick:
                all_scene_targets = set()
                for s in scenes:
                    all_scene_targets.update(s.targets)
                scan_names = [p["name"] for p in actual_params[:3]]
                uncovered = [n for n in scan_names if n not in all_scene_targets]
                if uncovered:
                    auto_scene = SceneItem(
                        scene_id=f"A{len(scenes) + 1}",
                        scene_type="parameter",
                        label=f"統計異常參數補充調查 ({', '.join(uncovered[:2])})",
                        targets=uncovered[:3],
                        severity=1.5,
                        status="PENDING",
                        source="自動補充 (AutoTarget 未覆蓋)",
                    )
                    scenes.append(auto_scene)
                    print(f"[Strategist] 自動補充 AutoTarget 場景: {uncovered[:3]}")

            print(
                f"[Strategist] 最終 {len(scenes)} 個調查場景: "
                f"{[s.label for s in scenes]}"
            )
            return scenes

        except Exception as e:
            print(f"[Strategist] Scene generation failed: {e}, using fallback")
            # Fallback: 用 actual_params 直接建立基本場景
            from backend.services.analysis.analysis_types import SceneItem

            fallback_scenes = []
            for i, p in enumerate(actual_params[:3]):
                fallback_scenes.append(
                    SceneItem(
                        scene_id=f"A{i + 1}",
                        scene_type="parameter",
                        label=f"{p['name']} 異常調查 (Z={p['z_score']})",
                        targets=[p["name"]],
                        severity=float(6 - i),
                        status="ACTIVE" if i == 0 else "PENDING",
                        source="Fallback (LLM 失敗)",
                    )
                )
            for i, seg in enumerate(actual_segments[:3]):
                fallback_scenes.append(
                    SceneItem(
                        scene_id=f"A{len(fallback_scenes) + 1}",
                        scene_type="segment",
                        label=f"{seg['range']} 區段調查",
                        targets=seg.get("params", []),
                        severity=float(3 - i),
                        status="PENDING",
                        source="Fallback (LLM 失敗)",
                    )
                )
            if fallback_scenes:
                print(
                    f"[Strategist] Fallback: {len(fallback_scenes)} 場景 from actual params"
                )
            return fallback_scenes

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
        使用者提問對齊: 提取原始問題的意圖和關鍵詞,
        與目前發現做比對, 告訴 Strategist 回答覆蓋率。
        同時把未涵蓋的 gap 存到 self._last_uncovered_gaps 供 execute() 使用。
        """
        import re

        query = getattr(state, "original_query", "") or ""
        summary = get_summary(state.current_knowledge)
        knowledge = getattr(state, "current_knowledge", "") or ""

        if not query:
            self._last_uncovered_gaps = []
            self._last_coverage_pct = 0.0
            return ""

        ctx = "=== 使用者的問題 (你必須回答這個) ===\n"
        ctx += f"原始提問: {query}\n"

        # Extract user intent phrases (more meaningful than single keywords)
        intent_phrases = []

        # Pattern 1: 「...的原因」「為什麼...」
        why_patterns = re.findall(r"為什麼[^，。、？!]+|[^，。、？!]+的原因", query)
        for p in why_patterns:
            intent_phrases.append(f"找出原因: {p.strip()}")

        # Pattern 2: 「如何優化/改善/降低/提升...」
        how_patterns = re.findall(
            r"(?:如何|怎麼|怎樣)[^，。、？!]+|(?:優化|改善|降低|提升|調整)[^，。、？!]+",
            query,
        )
        for p in how_patterns:
            intent_phrases.append(f"操作建議: {p.strip()}")

        # Pattern 3: 「分析...與...的關係」「...影響...」
        rel_patterns = re.findall(
            r"[^，。、？!]*(?:與|和|跟)[^，。、？!]*(?:關係|關聯|影響|相關)", query
        )
        for p in rel_patterns:
            intent_phrases.append(f"關聯分析: {p.strip()}")

        # Pattern 4: 「找出影響...的因子」
        factor_patterns = re.findall(
            r"找出[^，。、？!]+|影響[^，。、？!]+的[^，。、？!]*因[子素]", query
        )
        for p in factor_patterns:
            intent_phrases.append(f"因子識別: {p.strip()}")

        # Pattern 5: explicit target variable mentions
        target_match = re.search(r"\[目標變量\]\s*(\S+)", knowledge)
        if target_match:
            ctx += f"目標變量: {target_match.group(1)}\n"

        if intent_phrases:
            ctx += "使用者意圖分解:\n"
            for i, intent in enumerate(intent_phrases[:5], 1):
                ctx += f"  {i}. {intent}\n"
            ctx += "你的 directive 必須服務於上述意圖。如果不相關,就停下來重新對焦。\n"
        else:
            # Fallback: extract key parameter names and action verbs
            def _extract_kw(text: str) -> set:
                latin = set(re.findall(r"[A-Z][A-Z0-9_-]+(?:_[A-Z0-9]+)*", text))
                return latin

            query_kw = _extract_kw(query)
            if query_kw:
                ctx += f"問題關鍵詞: {', '.join(sorted(query_kw)[:8])}\n"

        # Coverage check against summary section (hybrid: semantic + scene)
        if summary or state.scene_queue:
            # --- 混合覆蓋率: 語義 + 場景完成率 ---
            _hybrid_result = None
            # 優先使用 query_intents (LLM 分解), 降級為標點切分
            intents = getattr(state, "query_intents", []) or []
            if not intents:
                # Fallback: 標點切分
                intents = re.split(r"[，。、；！？\n]+", query)
                intents = [c.strip() for c in intents if len(c.strip()) >= 4]
                if not intents:
                    intents = [query.strip()]

            try:
                from backend.services.analysis.embedding_service import (
                    compute_hybrid_coverage,
                )

                _hybrid_result = compute_hybrid_coverage(
                    intents=intents,
                    summary=summary,
                    scene_queue=state.scene_queue or [],
                )
            except Exception:
                pass

            if _hybrid_result is not None:
                coverage = _hybrid_result["coverage_pct"]
                uncov = _hybrid_result.get("uncovered_intents", [])
                uncov_scenes = _hybrid_result.get("uncovered_scenes", [])
                semantic_pct = _hybrid_result.get("semantic_pct", 0)
                scene_pct = _hybrid_result.get("scene_pct", 0)

                # 工具歷史過濾: 如果相關工具已使用, 視為已覆蓋
                if uncov:
                    _intent_tools = {
                        "全域": {
                            "cv_ranking",
                            "correlation_network",
                            "scan_anomaly_segments",
                        },
                        "因子": {
                            "get_top_correlations",
                            "correlation_network",
                            "analyze_feature_importance",
                        },
                        "影響": {
                            "get_top_correlations",
                            "correlation_network",
                            "analyze_feature_importance",
                        },
                        "異常": {
                            "scan_anomaly_segments",
                            "classify_anomaly_type",
                            "detect_outliers",
                        },
                        "關聯": {
                            "get_top_correlations",
                            "correlation_network",
                            "cross_correlation_lag",
                        },
                        "區段": {"scan_anomaly_segments", "compare_data_segments"},
                        "差異": {
                            "compare_data_segments",
                            "distribution_shift_analysis",
                        },
                        "探勘": {
                            "cv_ranking",
                            "correlation_network",
                            "hotelling_t2_analysis",
                        },
                        "排名": {"cv_ranking", "analyze_feature_importance"},
                        "診斷": {
                            "classify_anomaly_type",
                            "detect_outliers",
                            "scan_anomaly_segments",
                        },
                    }
                    used_tools = set(
                        t.split("::")[0]
                        for t in getattr(state, "used_tools_history", [])
                    )
                    filtered_uncov = []
                    for intent in uncov:
                        satisfied = False
                        for keyword, tools in _intent_tools.items():
                            if keyword in intent and (tools & used_tools):
                                satisfied = True
                                break
                        if not satisfied:
                            filtered_uncov.append(intent)
                    uncov = filtered_uncov

                    # 重算語義覆蓋率
                    if len(intents) > 0:
                        new_semantic = (len(intents) - len(uncov)) / len(intents)
                        if state.scene_queue:
                            coverage = 0.4 * new_semantic + 0.6 * scene_pct
                        else:
                            coverage = new_semantic

                # 覆蓋率文字
                cov_parts = [f"回答覆蓋率: {coverage:.0%}"]
                if state.scene_queue:
                    cov_parts.append(f"(語義:{semantic_pct:.0%} 場景:{scene_pct:.0%})")
                if coverage >= 0.7:
                    cov_parts.append("(高)")
                elif coverage >= 0.4:
                    cov_parts.append("(中 — 需要繼續)")
                else:
                    cov_parts.append("(低 — 核心問題尚未回答!)")
                ctx += " ".join(cov_parts) + "\n"

                if uncov:
                    ctx += f"尚未涵蓋意圖: {'; '.join(c[:40] for c in uncov[:3])}\n"
                if uncov_scenes:
                    ctx += (
                        f"未完成場景: {'; '.join(s[:30] for s in uncov_scenes[:3])}\n"
                    )
                self._last_uncovered_gaps = (
                    (uncov + uncov_scenes) if (uncov or uncov_scenes) else []
                )
                self._last_coverage_pct = coverage
            else:
                # --- Fallback: substring + topic-map ---
                _q_latin = set(re.findall(r"[A-Z][A-Z0-9_-]+(?:_[A-Z0-9]+)*", query))
                _q_cjk = set(re.findall(r"(?=([\u4e00-\u9fff]{2}))", query))
                _q_kw = _q_latin | _q_cjk
                if _q_kw:
                    covered = {kw for kw in _q_kw if kw in summary}
                    coverage = len(covered) / len(_q_kw)
                    if coverage >= 0.7:
                        ctx += f"回答覆蓋率: {coverage:.0%} (高)\n"
                    elif coverage >= 0.4:
                        ctx += f"回答覆蓋率: {coverage:.0%} (中 — 需要繼續)\n"
                    else:
                        ctx += f"回答覆蓋率: {coverage:.0%} (低 — 核心問題尚未回答!)\n"
                    _topic_map = {
                        "異常": "異常偵測",
                        "區段": "區段分析",
                        "區間": "區間比較",
                        "探勘": "資料探勘",
                        "因子": "影響因子",
                        "差異": "差異比較",
                        "全域": "全域分析",
                    }
                    _topic_tools = {
                        "異常": {
                            "scan_anomaly_segments",
                            "classify_anomaly_type",
                            "detect_outliers",
                        },
                        "區段": {"scan_anomaly_segments", "compare_data_segments"},
                        "區間": {
                            "compare_data_segments",
                            "distribution_shift_analysis",
                        },
                        "探勘": {
                            "cv_ranking",
                            "correlation_network",
                            "hotelling_t2_analysis",
                        },
                        "因子": {
                            "get_top_correlations",
                            "correlation_network",
                            "analyze_feature_importance",
                        },
                        "差異": {
                            "compare_data_segments",
                            "distribution_shift_analysis",
                        },
                        "全域": {
                            "cv_ranking",
                            "correlation_network",
                            "scan_anomaly_segments",
                        },
                    }
                    used_tools = set(
                        t.split("::")[0]
                        for t in getattr(state, "used_tools_history", [])
                    )
                    uncov = []
                    for key, lbl in _topic_map.items():
                        if key in query:
                            satisfied_by_summary = key in summary
                            satisfied_by_tools = bool(
                                _topic_tools.get(key, set()) & used_tools
                            )
                            if not satisfied_by_summary and not satisfied_by_tools:
                                uncov.append(lbl)
                    if uncov:
                        ctx += f"尚未涵蓋: {', '.join(uncov[:5])}\n"
                        self._last_uncovered_gaps = uncov
                        self._last_coverage_pct = coverage
                    else:
                        self._last_uncovered_gaps = []
                        self._last_coverage_pct = coverage
                else:
                    self._last_uncovered_gaps = []
                    self._last_coverage_pct = 0.0

        ctx += "===================================\n"
        return ctx

    # ------------------------------------------------------------------
    # [NEW] Turn 1 初始掃描 (from Orchestrator)
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # [NEW] Turn 1 路徑 A/B: 跳過盲掃, 直接生成場景
    # ------------------------------------------------------------------
    async def _generate_intent_scenes(self, state: AnalysisState) -> "RoleOutput":
        """
        路徑 A: 有領域意圖 (如「斷紙原因」) → 用 LLM 生場景 + 快速掃描。
        Turn 1 掃描完後 FINISH，場景作為後續追蹤項目列出。
        """
        scenes = await self._generate_scenes(state)
        if not scenes:
            # fallback: 如果場景生成失敗, 退回盲掃
            print("[Strategist] [路徑 A] 場景生成失敗, 退回盲掃")
            return self._generate_turn1_experiments(state)

        # --- [NEW] 建立快速掃描實驗 (四合一全域掃描) ---
        experiments = [
            ExperimentContext(
                id="scan_a_01",
                objective="全域 Z-Score 掃描",
                technique="detect_outliers",
                target_columns=["all"],
                focus_range="Global",
            ),
            ExperimentContext(
                id="scan_a_02",
                objective="多變量異常偵測 (Hotelling T2)",
                technique="hotelling_t2_analysis",
                target_columns=["all"],
                focus_range="Global",
            ),
            ExperimentContext(
                id="scan_a_03",
                objective="全域關聯性掃描",
                technique="get_top_correlations",
                target_columns=["all"],
                focus_range="Global",
            ),
            ExperimentContext(
                id="scan_a_04",
                objective="全域異常區段掃描",
                technique="scan_anomaly_segments",
                target_columns=["all"],
                focus_range="Global",
            ),
        ]

        # --- 格式化場景為後續追蹤項目 ---
        follow_up_items = []
        for s in scenes:
            follow_up_items.append(
                {
                    "scene_id": s.scene_id,
                    "label": s.label,
                    "scene_type": s.scene_type,
                    "targets": s.targets,
                }
            )

        scene_labels = [f"{s.scene_id}: {s.label}" for s in scenes]

        print(f"[Strategist] [路徑 A] 快速掃描 + 場景選單: {len(scenes)} 個追蹤項目")

        return RoleOutput(
            decision="CONTINUE",
            reasoning=(
                f"[Turn 1 路徑A: 意圖掃描] 執行全域四合一掃描, "
                f"建立 {len(scenes)} 個後續追蹤場景。"
            ),
            directive="全域掃描 + 領域意圖場景生成",
            experiments=experiments,
            structured_log={
                "turn1_type": "intent_scan",
                "follow_up_items": follow_up_items,
                "knowledge_addon": (
                    f"\n[場景選單] 共 {len(scenes)} 個追蹤項目: "
                    + " | ".join(scene_labels)
                ),
            },
        )

    async def _generate_precise_experiments(
        self, state: AnalysisState, targets: list, tool_name: str
    ) -> "RoleOutput":
        """
        [路徑 D] 精確指令模式:
        用戶已明確指定工具名稱和目標參數, 直接構建精確的 experiment,
        跳過四合一掃描, 最大化效率。

        [NEW] 語意場景生成:
        - 視覺化工具 (draw_trend 等): 執行後 FINISH, 不需追蹤場景
        - 分析工具: 執行後用 LLM 生成 1-2 個收斂的追蹤場景

        參數映射策略:
        - 從 TOOL_REGISTRY 查詢工具的 required_params / optional_params
        - 根據 targets 智慧填充:
          - 雙參數工具 (如 cross_correlation_lag): targets[0] → target, targets[1] → reference
          - 單參數工具 (如 draw_trend): targets[0] → parameter/target
          - 多參數工具 (如 parallel_coordinates): targets → target_columns
        """
        from backend.services.analysis.tools.registry import (
            TOOL_REGISTRY,
            get_tool_spec,
        )
        from backend.services.analysis.analysis_types import (
            SceneItem,
            ExperimentContext,
        )

        spec = get_tool_spec(tool_name)
        if not spec:
            # 工具不存在 → 退回路徑 B
            print(f"[Strategist] [路徑 D] 工具 {tool_name} 不在 Registry, 退回路徑 B")
            return RoleOutput(
                decision="CONTINUE",
                reasoning=f"指定工具 {tool_name} 不存在, 退回四合一掃描",
                directive=f"快速掃描目標參數: {', '.join(targets[:3])}",
                experiments=[],
            )

        required = spec.get("required_params", [])
        optional = spec.get("optional_params", [])
        all_params = required + optional

        # --- 智慧參數映射 ---
        tool_params = {}

        # 常見參數名到 targets 位置的映射表
        _target_aliases = {
            "target",
            "parameter",
            "process_variable",
            "target_parameter",
            "param_a",
            "x_param",
        }
        _reference_aliases = {"reference", "param_b", "y_param", "setpoint"}
        _multi_aliases = {"target_columns", "targets", "features"}

        for p in all_params:
            if p in _multi_aliases:
                # 多欄位參數: 放入所有 targets
                tool_params[p] = targets[:5]
            elif p in _target_aliases and targets:
                tool_params[p] = targets[0]
            elif p in _reference_aliases and len(targets) >= 2:
                tool_params[p] = targets[1]
            elif p == "color_param" and len(targets) >= 3:
                tool_params[p] = targets[2]
            elif p == "controller_output" and len(targets) >= 3:
                tool_params[p] = targets[2]

        # --- 構建精確實驗 ---
        target_desc = ", ".join(targets[:3])
        experiments = [
            ExperimentContext(
                id="precise_d_01",
                objective=f"使用 {tool_name} 分析 {target_desc}",
                technique=tool_name,
                target_columns=targets[:3],
                focus_range="Global",
            )
        ]

        # --- [NEW] 判斷是否為視覺化工具 (執行後直接 FINISH) ---
        _visualization_tools = {
            "draw_trend",
            "get_time_series_data",
            "parallel_coordinates",
            "heatmap",
            "scatter_plot",
            "box_plot",
        }
        is_visualization = tool_name in _visualization_tools

        if is_visualization:
            # 視覺化工具: 執行後 FINISH, 不需追蹤場景
            scene = SceneItem(
                scene_id="A1",
                scene_type="parameter",
                label=f"{tool_name}: {target_desc}",
                targets=targets[:3],
                severity=8.0,
                status="ACTIVE",
                source="用戶精確指令 (路徑 D, 視覺化)",
            )

            print(
                f"[Strategist] [路徑 D] 視覺化工具 {tool_name}, "
                f"執行後 FINISH。目標: {target_desc}"
            )

            return RoleOutput(
                decision="FINISH",
                reasoning=(
                    f"[Turn 1 路徑D: 視覺化] 用戶指定 {tool_name}, "
                    f"執行後直接呈現結果。目標: {target_desc}"
                ),
                directive=f"精確執行 {tool_name}: {target_desc}",
                experiments=experiments,
                structured_log={
                    "turn1_type": "precise_visualization",
                    "specified_tool": tool_name,
                    "tool_params": tool_params,
                    "knowledge_addon": (
                        f"\n[視覺化指令] 用戶指定 {tool_name}, "
                        f"目標: {target_desc}, 執行後 FINISH"
                    ),
                },
            )

        # --- 非視覺化工具: 用 LLM 生成收斂的追蹤場景 ---
        scenes = []
        try:
            scenes = await self._generate_semantic_scenes(state, targets, max_scenes=2)
        except Exception as e:
            print(f"[Strategist] [路徑 D] 語意場景生成失敗: {e}")

        # Fallback: 如果 LLM 失敗,建一個基本場景
        if not scenes:
            scenes = [
                SceneItem(
                    scene_id="A1",
                    scene_type="parameter",
                    label=f"{tool_name} 精確分析: {target_desc}",
                    targets=targets[:3],
                    severity=8.0,
                    status="ACTIVE",
                    source="用戶精確指令 (路徑 D)",
                )
            ]

        follow_up_items = [
            {
                "scene_id": s.scene_id,
                "label": s.label,
                "scene_type": s.scene_type,
                "targets": s.targets,
            }
            for s in scenes
        ]

        scene_labels = [f"{s.scene_id}: [{s.scene_type}] {s.label}" for s in scenes]

        print(
            f"[Strategist] [路徑 D] 精確實驗: {tool_name}({tool_params}), "
            f"{len(scenes)} 個追蹤場景:\n"
            + "\n".join(f"  - {lbl}" for lbl in scene_labels)
        )

        return RoleOutput(
            decision="CONTINUE",
            reasoning=(
                f"[Turn 1 路徑D: 精確指令] 用戶指定工具 {tool_name}, "
                f"直接執行, 跳過四合一掃描。目標: {target_desc}"
            ),
            directive=f"精確執行 {tool_name}: {target_desc}",
            experiments=experiments,
            structured_log={
                "turn1_type": "precise_tool",
                "specified_tool": tool_name,
                "tool_params": tool_params,
                "follow_up_items": follow_up_items,
                "_scene_updates": {
                    "scene_queue": scenes,
                    "current_scene_index": 0,
                    "_prev_scene_index": -1,
                    "coverage_pct": 0.0,
                },
                "knowledge_addon": (
                    f"\n[精確指令] 用戶指定 {tool_name}, "
                    f"目標: {target_desc}\n"
                    + "\n".join(f"[追蹤場景] {lbl}" for lbl in scene_labels)
                ),
            },
        )

    async def _generate_semantic_scenes(
        self, state: AnalysisState, targets: list, max_scenes: int = 4
    ) -> list:
        """
        [LLM-Driven Semantic Scene Generation for Path B/D]
        根據使用者問題語意 + 已知 targets, 用 LLM 生成調查場景。
        不需要 Turn 1 掃描結果 (與 _generate_scenes 的區別)。

        Args:
            state: 分析狀態
            targets: 已知目標參數列表
            max_scenes: 最大場景數 (路徑 B=5, 路徑 D=2)

        Returns:
            list[SceneItem]: 語意場景列表
        """
        import json as _json
        from backend.services.analysis.analysis_types import SceneItem

        query = getattr(state, "original_query", "") or ""
        if not query or not targets:
            return []

        # --- 術語對應表, 讓 LLM 理解參數含義 ---
        mapping_hint = ""
        term_mappings = getattr(state, "term_mappings", {})
        if term_mappings:
            relevant_mappings = {
                k: v for k, v in term_mappings.items() if k in set(targets)
            }
            if relevant_mappings:
                mapping_lines = [
                    f"  {code} = {name}" for code, name in relevant_mappings.items()
                ]
                mapping_hint = "\n[術語對應表]\n" + "\n".join(mapping_lines) + "\n"

        targets_str = ", ".join(targets[:5])

        prompt = (
            f"你是工業數據分析策略師。\n\n"
            f"用戶問題: {query}\n"
            f"目標參數: {targets_str}\n"
            f"{mapping_hint}\n"
            f"請根據用戶問題的語意, 規劃 {max_scenes} 個以內的調查場景。\n\n"
            "██ [場景類型] ██\n"
            "根據用戶問題的意圖, 選擇合適的場景類型:\n"
            "  - parameter: 參數深度分析 (異常偵測、趨勢分析、分佈分析)\n"
            "  - optimization: 最佳化分析 (找最佳操作範圍、SOP 建議)\n"
            "  - interaction: 交互分析 (參數間相關性、因果關係)\n"
            "  - segment: 區段分析 (特定 Row 範圍的深入分析)\n\n"
            "██ [意圖判斷規則] ██\n"
            "  - 用戶提到「優化/改善/調整/設定值/SOP/怎麼調」→ optimization 類型\n"
            "  - 用戶提到「異常/問題/為什麼/原因/分析」→ parameter 類型\n"
            "  - 用戶提到「相關/影響/互動/比較」→ interaction 類型\n"
            "  - 用戶提到某個 Row 範圍 → segment 類型\n"
            "  - 可以組合多種類型\n\n"
            "██ [label 設計] ██\n"
            "  - label 必須貼合用戶問題的語意, 不要使用通用描述\n"
            "  - 例如用戶問「如何降低斷紙率」→ label: 「張力參數最佳化與斷紙風險降低」\n"
            "  - 例如用戶問「A65 異常原因」→ label: 「A65 異常根因調查與影響範圍評估」\n\n"
            "回傳格式: JSON 陣列, 每個元素:\n"
            '  {"scene_id": "A1", "type": "parameter|optimization|interaction|segment", '
            '"label": "場景描述", "targets": ["param1"]}\n\n'
            "規則:\n"
            f"  - 最多 {max_scenes} 個場景\n"
            "  - targets 必須從上方目標參數中選取\n"
            "  - 只回傳 JSON 陣列, 不要其他文字\n"
        )

        try:
            resp = await self.llm.acomplete(prompt)
            text = str(resp.text).strip()

            # 提取 JSON
            if "```" in text:
                import re as _re_json

                json_match = _re_json.search(r"\[.*\]", text, _re_json.DOTALL)
                if json_match:
                    text = json_match.group(0)
            elif not text.startswith("["):
                import re as _re_json2

                json_match = _re_json2.search(r"\[.*\]", text, _re_json2.DOTALL)
                if json_match:
                    text = json_match.group(0)

            raw_scenes = _json.loads(text)
            if not isinstance(raw_scenes, list):
                raw_scenes = []

            scenes = []
            for i, rs in enumerate(raw_scenes[:max_scenes]):
                scene_type = rs.get("type", "parameter")
                if scene_type not in (
                    "parameter",
                    "optimization",
                    "interaction",
                    "segment",
                ):
                    scene_type = "parameter"

                scene_targets = rs.get("targets", targets[:1])
                # 驗證 targets 存在
                valid_targets = [t for t in scene_targets if t in set(targets)]
                if not valid_targets:
                    valid_targets = targets[:1]

                scenes.append(
                    SceneItem(
                        scene_id=rs.get("scene_id", f"A{i + 1}"),
                        scene_type=scene_type,
                        label=rs.get("label", f"{valid_targets[0]} 分析"),
                        targets=valid_targets,
                        severity=float(7 - i),
                        status="PENDING",
                        source="LLM 語意場景生成",
                    )
                )

            if scenes:
                scene_labels = [
                    f"{s.scene_id}: [{s.scene_type}] {s.label}" for s in scenes
                ]
                print(
                    f"[Strategist] 語意場景生成: {len(scenes)} 個場景\n"
                    + "\n".join(f"  - {lbl}" for lbl in scene_labels)
                )

            return scenes

        except Exception as e:
            print(f"[Strategist] 語意場景生成失敗: {e}, 回退硬編碼場景")
            return []

    async def _expand_concepts(
        self,
        query: str,
        all_columns: list,
        term_mappings: dict,
        existing_targets: list,
        intents: list = None,
        progress_callback=None,
    ) -> tuple:
        """
        概念展開: 按意圖分組, 讓 LLM 為每個意圖找出對應參數。
        [分批處理] 將欄位拆成每批 120 個, 避免超過 context window。

        回傳:
          (expanded_targets: list, intent_groups: dict)
          - expanded_targets: 所有展開的參數名列表 (flat)
          - intent_groups: {"意圖1描述": [params], "意圖2描述": [params]}
        """
        import json as _json

        if not all_columns or not query:
            return ([], {})

        # 建立意圖清單 (如果沒有意圖, 用 query 本身作為唯一意圖)
        if intents and len(intents) > 0:
            # 清理意圖文字 (去掉 "意圖N: " 前綴)
            import re as _re_intent

            clean_intents = []
            for it in intents:
                cleaned = _re_intent.sub(r"^意圖\d+[:：]\s*", "", it.strip())
                if cleaned:
                    clean_intents.append(cleaned)
            if not clean_intents:
                clean_intents = [query]
        else:
            clean_intents = [query]

        intent_list_text = "\n".join(
            f"  意圖{i + 1}: {it}" for i, it in enumerate(clean_intents)
        )
        print(f"[Strategist] [概念展開] 按意圖分組, {len(clean_intents)} 個意圖")

        BATCH_SIZE = 50  # 每批 50 個, 讓 prompt 短一些, 給輸出留足空間
        valid_set = set(all_columns)
        merged_groups = {}  # intent_label -> [params]

        # 分批處理
        batches = [
            all_columns[i : i + BATCH_SIZE]
            for i in range(0, len(all_columns), BATCH_SIZE)
        ]
        print(
            f"[Strategist] [概念展開] 欄位數={len(all_columns)}, "
            f"分成 {len(batches)} 批 (每批 {BATCH_SIZE})"
        )

        for batch_idx, batch_cols in enumerate(batches):
            # 建立本批參數表
            mapping_lines = []
            for col in batch_cols:
                cn_name = term_mappings.get(col, "")
                if cn_name and cn_name != col:
                    mapping_lines.append(f"  {col} = {cn_name}")
                else:
                    mapping_lines.append(f"  {col}")
            param_text = "\n".join(mapping_lines)

            prompt = (
                "你是工業數據領域專家。使用者有多個分析意圖, "
                "你需要為每個意圖從參數清單中找出所有相關的參數。\n\n"
                f"原始問題: {query}\n\n"
                f"[分析意圖清單]\n{intent_list_text}\n\n"
                f"[參數清單 - 批次 {batch_idx + 1}/{len(batches)}] "
                f"({len(batch_cols)} 個):\n{param_text}\n\n"
                "\u2588\u2588 [任務] \u2588\u2588\n"
                "為每個意圖, 從 **此批次** 參數清單中找出所有相關參數。\n"
                "判斷依據: 參數的代碼或中文名是否與該意圖的主題相關。\n"
                "寧可多列也不要少列。\n\n"
                "回傳格式 (只回傳 JSON):\n"
                "```json\n"
                "{\n"
                '  "groups": {\n'
                '    "意圖1": ["PARAM_001", "PARAM_002"],\n'
                '    "意圖2": ["PARAM_003", "PARAM_004"]\n'
                "  }\n"
                "}\n"
                "```\n\n"
                "規則:\n"
                "  - groups 的 key 必須是「意圖1」「意圖2」等 "
                "(對應上方意圖編號)\n"
                "  - 如果某意圖在此批次中沒有對應參數, "
                "該意圖的陣列設為 []\n"
                "  - 參數名必須完全匹配清單中的代碼 (區分大小寫)\n"
                "  - 同一個參數可以出現在多個意圖中\n"
                "  - 相關判斷要寬鬆: 例如意圖提到「流量」, "
                "應包含所有含「流量」或 flow 的參數\n"
            )

            try:
                print(
                    f"[Strategist] [概念展開] 批次 {batch_idx + 1}/{len(batches)}: "
                    f"prompt={len(prompt)} chars, 欄位={len(batch_cols)}"
                )
                resp = await self.llm.acomplete(prompt)
                text = str(resp.text).strip()
                print(
                    f"[Strategist] [概念展開] 批次 {batch_idx + 1} LLM 回傳 "
                    f"({len(text)} chars):\n{text[:800]}"
                )

                import re as _re_ce
                import json as _json

                json_match = _re_ce.search(r"\{.*\}", text, _re_ce.DOTALL)
                if json_match:
                    text = json_match.group(0)

                # 嘗試解析, 若截斷則修復
                parsed = None
                try:
                    parsed = _json.loads(text)
                except _json.JSONDecodeError:
                    # 截斷修復: 去掉最後不完整的值, 補齊括號
                    repair = text.rstrip()
                    # 移除尾部不完整的字串 (如 "PARAM 截斷)
                    repair = _re_ce.sub(r',?\s*"[^"]*$', "", repair)
                    # 補齊缺少的括號
                    open_sq = repair.count("[") - repair.count("]")
                    open_cu = repair.count("{") - repair.count("}")
                    repair += "]" * max(0, open_sq)
                    repair += "}" * max(0, open_cu)
                    try:
                        parsed = _json.loads(repair)
                        print(
                            f"[Strategist] [概念展開] 批次 {batch_idx + 1} "
                            f"JSON 截斷已修復"
                        )
                    except _json.JSONDecodeError:
                        print(
                            f"[Strategist] [概念展開] 批次 {batch_idx + 1} "
                            f"JSON 修復失敗, 跳過"
                        )
                        continue

                groups = parsed.get("groups", {})

                # 驗證並合併: key 轉換為意圖描述
                for key, params in groups.items():
                    valid_params = [p for p in params if p in valid_set]
                    if not valid_params:
                        continue
                    # key 可能是 "意圖1" or "意圖2", 轉換為實際描述
                    import re as _re_idx

                    idx_match = _re_idx.search(r"(\d+)", key)
                    if idx_match:
                        idx = int(idx_match.group(1)) - 1  # 0-based
                        if 0 <= idx < len(clean_intents):
                            label = clean_intents[idx]
                        else:
                            label = key
                    else:
                        label = key

                    if label not in merged_groups:
                        merged_groups[label] = []
                    existing = set(merged_groups[label])
                    for p in valid_params:
                        if p not in existing:
                            merged_groups[label].append(p)
                            existing.add(p)

                batch_found = sum(len(v) for v in groups.values())
                print(
                    f"[Strategist] [概念展開] 批次 {batch_idx + 1} "
                    f"找到 {batch_found} 個參數"
                )

                # 回報批次進度到前端
                if progress_callback:
                    _running_total = sum(len(v) for v in merged_groups.values())
                    progress_callback(
                        f"參數掃描 {batch_idx + 1}/{len(batches)} "
                        f"(本批 +{batch_found}, 累計 {_running_total} 個)"
                    )

            except Exception as e:
                print(f"[Strategist] [概念展開] 批次 {batch_idx + 1} 失敗: {e}, 跳過")
                continue

        # 最終彙總
        if not merged_groups:
            print("[Strategist] [概念展開] 所有批次均無結果")
            return ([], {})

        all_expanded = []
        for params in merged_groups.values():
            all_expanded.extend(params)
        # 去重
        all_expanded = list(dict.fromkeys(all_expanded))

        total = len(all_expanded)
        group_summary = ", ".join(
            f"{k[:20]}: {len(v)}個" for k, v in merged_groups.items()
        )
        print(
            f"[Strategist] [概念展開] 彙總: "
            f"{len(merged_groups)} 個意圖, "
            f"共 {total} 個參數 ({group_summary})"
        )

        return (all_expanded, merged_groups)

    async def _generate_unified_scenes(
        self, state: AnalysisState, targets: list
    ) -> "RoleOutput":
        """
        [路徑 S] 統一場景生成 — 合併原 Path A + Path B。
        LLM 同時接收意圖 + 目標 + 完整參數表, 一次完成:
        1. 概念→參數對應 (如「水分」→ MOISTURE_001)
        2. 場景生成 (根據語意切分調查方向)
        3. execution_mode 判斷 (auto 直接跑 / interactive 場景選單)

        場景直接設入 scene_queue, 不再硬編碼實驗。
        """
        from backend.services.analysis.analysis_types import SceneItem

        query = getattr(state, "original_query", "") or ""
        if not query:
            print("[Strategist] [路徑 S] 無 query, 退回盲掃")
            return self._generate_turn1_experiments(state)

        # --- 建立完整參數表 (不只已知 targets) ---
        term_mappings = getattr(state, "term_mappings", {})
        all_columns = []
        if state.current_context:
            all_columns = getattr(state.current_context, "all_columns", []) or []
        if not all_columns and term_mappings:
            all_columns = list(term_mappings.keys())

        # --- 取得意圖清單, 先決定 auto / interactive ---
        _intents = getattr(state, "query_intents", []) or []
        # 清理意圖 (去掉 "意圖N: " 前綴)
        import re as _re_mode

        clean_intents = []
        for it in _intents:
            cleaned = _re_mode.sub(r"^意圖\d+\s*[:：]\s*", "", str(it)).strip()
            if cleaned:
                clean_intents.append(cleaned)
        if not clean_intents:
            clean_intents = [query]

        # execution_mode: 意圖 <=3 → auto (需要展開參數), >3 → interactive (直接列場景)
        execution_mode = "auto" if len(clean_intents) <= 3 else "interactive"
        print(
            f"[Strategist] [路徑 S] 意圖數={len(clean_intents)}, mode={execution_mode}"
        )

        # =========================================================
        # Interactive 模式: 跳過概念展開, 直接用意圖建場景選單
        # =========================================================
        if execution_mode == "interactive":
            from backend.services.analysis.analysis_types import SceneItem

            def _infer_scene_type_quick(intent_text: str) -> str:
                text = intent_text.lower()
                if any(kw in text for kw in ["原因", "為什麼", "why", "因果"]):
                    return "correlation_breakdown"
                if any(kw in text for kw in ["相關", "關係", "影響", "交互", "因子"]):
                    return "interaction"
                if any(kw in text for kw in ["最佳", "優化", "改善", "提升"]):
                    return "optimization"
                if any(kw in text for kw in ["區段", "區間", "範圍", "第"]):
                    return "segment"
                return "parameter"

            scenes = []
            for i, intent_label in enumerate(clean_intents):
                scene_type = _infer_scene_type_quick(intent_label)
                scenes.append(
                    SceneItem(
                        scene_id=f"S{i + 1}",
                        scene_type=scene_type,
                        label=intent_label,
                        targets=targets[:3],  # 先放原始 targets, 選場景後再展開
                        severity=float(7 - i),
                        status="PENDING",
                        source="路徑 S 意圖→場景 (interactive)",
                        analysis_focus=intent_label,
                    )
                )

            scene_menu_lines = []
            for s in scenes:
                scene_menu_lines.append(
                    f"  {s.scene_id}: {s.label}\n    類型: {s.scene_type}"
                )
            menu_text = "\n".join(scene_menu_lines)

            scene_labels = [f"{s.scene_id}: [{s.scene_type}] {s.label}" for s in scenes]
            print(
                f"[Strategist] [路徑 S: interactive] "
                f"直接列場景 (跳過概念展開), {len(scenes)} 個場景\n"
                + "\n".join(f"  - {lbl}" for lbl in scene_labels)
            )

            return RoleOutput(
                decision="FINISH",
                reasoning=(
                    f"[路徑 S: interactive] 問題開放性較高, "
                    f"生成 {len(scenes)} 個場景供使用者選擇。"
                ),
                directive="場景選單已生成, 等待使用者選擇",
                experiments=[],
                structured_log={
                    "turn1_type": "scene_menu",
                    "execution_mode": "interactive",
                    # orchestrator 用 _scene_updates 將場景寫入 state
                    "_scene_updates": {
                        "scene_queue": scenes,
                        "current_scene_index": 0,
                    },
                    "scene_queue": [
                        {
                            "scene_id": s.scene_id,
                            "scene_type": s.scene_type,
                            "label": s.label,
                            "targets": s.targets,
                            "status": s.status,
                        }
                        for s in scenes
                    ],
                    "knowledge_addon": (
                        f"\n[分析規劃]\n"
                        f"我為你規劃了以下分析方向:\n\n{menu_text}\n\n"
                        f"請選擇要執行的分析 (可直接回覆場景編號如 S1, "
                        f"或回覆「全部執行」)。"
                    ),
                },
            )

        # =========================================================
        # Auto 模式: 做概念展開 → Top-N → 建場景 → 直接執行
        # =========================================================
        expanded_targets, intent_groups = await self._expand_concepts(
            query, all_columns, term_mappings, targets, intents=_intents
        )
        # 把展開結果合併到 targets (去重)
        if expanded_targets:
            merged = list(dict.fromkeys(targets + expanded_targets))
            targets = merged
            print(f"[Strategist] [概念展開] 擴展後 targets: {len(targets)} 個")

        # --- [方法 D] 智能 Top-N 篩選: 每個意圖保留 CV 最高的前 N 個 ---
        MAX_PER_INTENT = 5  # 每個意圖最多保留 5 個參數
        if intent_groups:
            try:
                stats = getattr(state, "_statistics_cache", None)
                if not stats:
                    svc = getattr(self, "_analysis_service", None)
                    if svc and hasattr(state, "file_id"):
                        stats = svc.load_statistics(state.session_id, state.file_id)

                trimmed_intent_groups = {}
                for intent_label, params in intent_groups.items():
                    if len(params) <= MAX_PER_INTENT:
                        trimmed_intent_groups[intent_label] = params
                    elif stats:
                        # 按 CV 排序, 保留 top-N
                        cv_scores = {}
                        for p in params:
                            s = stats.get(p, {})
                            mean_val = abs(s.get("mean", 0))
                            std_val = s.get("std", 0)
                            if mean_val > 1e-9:
                                cv_scores[p] = std_val / mean_val
                            else:
                                cv_scores[p] = std_val
                        ranked = sorted(
                            params, key=lambda t: cv_scores.get(t, 0), reverse=True
                        )
                        trimmed_intent_groups[intent_label] = ranked[:MAX_PER_INTENT]
                        print(
                            f"[Strategist] [Top-N] {intent_label[:25]}: "
                            f"{len(params)} -> {MAX_PER_INTENT} "
                            f"(保留: {ranked[:MAX_PER_INTENT]})"
                        )
                    else:
                        trimmed_intent_groups[intent_label] = params[:MAX_PER_INTENT]

                intent_groups = trimmed_intent_groups
                # 重新計算 flat targets
                targets = list(
                    dict.fromkeys(
                        p for params in intent_groups.values() for p in params
                    )
                )
                print(
                    f"[Strategist] [Top-N] 裁剪完成: "
                    f"每意圖最多 {MAX_PER_INTENT} 個, "
                    f"共 {len(targets)} 個 targets"
                )
            except Exception as e:
                print(f"[Strategist] [Top-N] 裁剪失敗: {e}, 保留原始")

        # --- 直接從意圖 → 場景 (auto 模式) ---
        if not intent_groups:
            print("[Strategist] [路徑 S] 無意圖分組, 退回盲掃")
            return self._generate_turn1_experiments(state)

        try:
            from backend.services.analysis.analysis_types import SceneItem

            def _infer_scene_type(intent_text: str) -> str:
                """根據意圖關鍵字判定場景類型"""
                text = intent_text.lower()
                if any(kw in text for kw in ["原因", "為什麼", "why", "因果"]):
                    return "correlation_breakdown"
                if any(kw in text for kw in ["相關", "關係", "影響", "交互", "因子"]):
                    return "interaction"
                if any(kw in text for kw in ["最佳", "優化", "改善", "提升"]):
                    return "optimization"
                if any(kw in text for kw in ["區段", "區間", "範圍", "第"]):
                    return "segment"
                return "parameter"

            scenes = []
            for i, (intent_label, params) in enumerate(intent_groups.items()):
                if not params:
                    continue
                scene_type = _infer_scene_type(intent_label)
                scenes.append(
                    SceneItem(
                        scene_id=f"S{i + 1}",
                        scene_type=scene_type,
                        label=intent_label,
                        targets=params,
                        severity=float(7 - i),
                        status="PENDING",
                        source="路徑 S 意圖→場景",
                        analysis_focus=intent_label,
                    )
                )

            if not scenes:
                print("[Strategist] [路徑 S] 意圖分組無有效參數, 退回盲掃")
                return self._generate_turn1_experiments(state)

            # auto 模式: 直接執行, 啟動 S1
            scenes[0].status = "ACTIVE"

            scene_labels = [
                f"{s.scene_id}: [{s.scene_type}] {s.label} ({len(s.targets)}個參數)"
                for s in scenes
            ]
            scene_list_text = "\n".join(f"  - {lbl}" for lbl in scene_labels)
            print(
                f"[Strategist] [路徑 S: auto] 意圖→場景完成: "
                f"{len(scenes)} 個場景\n" + scene_list_text
            )

            return RoleOutput(
                decision="CONTINUE",
                reasoning=(
                    f"[路徑 S: auto] 意圖明確, "
                    f"直接執行 {scenes[0].scene_id}: {scenes[0].label}\n"
                    f"共 {len(scenes)} 個場景:\n{scene_list_text}"
                ),
                directive=(
                    f"[場景啟動] {scenes[0].scene_id}: {scenes[0].label}\n"
                    f"目標參數: {', '.join(scenes[0].targets[:5])}\n"
                    f"分析焦點: {scenes[0].analysis_focus}"
                ),
                experiments=[],
                structured_log={
                    "turn1_type": "unified_scene_auto",
                    "scene_queue": [
                        {
                            "scene_id": s.scene_id,
                            "scene_type": s.scene_type,
                            "label": s.label,
                            "targets": s.targets,
                            "status": s.status,
                        }
                        for s in scenes
                    ],
                    "execution_mode": "auto",
                    "knowledge_addon": (
                        f"\n[場景規劃] 共 {len(scenes)} 個場景: "
                        + " | ".join(scene_labels)
                    ),
                },
            )

        except Exception as e:
            print(f"[Strategist] [路徑 S] 場景生成失敗: {e}, 退回盲掃")
            import traceback

            traceback.print_exc()
            return self._generate_turn1_experiments(state)

    async def _generate_direct_scenes(
        self, state: AnalysisState, targets: list
    ) -> "RoleOutput":
        """
        [已棄用] 原路徑 B — 由 _generate_unified_scenes 取代。
        保留代碼供 fallback 參考, 但不再被 execute() 調用。
        """
        from backend.services.analysis.analysis_types import SceneItem

        if not targets:
            print("[Strategist] [路徑 B] 無目標, 退回盲掃")
            return self._generate_turn1_experiments(state)

        scenes = []
        term_mappings = getattr(state, "term_mappings", {})

        # --- [NEW] LLM 語意場景生成: 根據用戶問題語意動態建立場景 ---
        try:
            scenes = await self._generate_semantic_scenes(state, targets, max_scenes=5)
        except Exception as e:
            print(f"[Strategist] [路徑 B] 語意場景生成失敗: {e}")

        # --- Fallback: 如果 LLM 場景生成失敗, 用基本場景 ---
        if not scenes:
            from backend.services.analysis.analysis_types import SceneItem

            print("[Strategist] [路徑 B] LLM 場景失敗, 使用 fallback 場景")
            for i, param in enumerate(targets[:3]):
                display_name = term_mappings.get(param, param)
                scenes.append(
                    SceneItem(
                        scene_id=f"A{i + 1}",
                        scene_type="parameter",
                        label=f"{display_name} 深度分析",
                        targets=[param],
                        severity=float(7 - i),
                        status="PENDING",
                        source="用戶指定目標 (fallback)",
                    )
                )

        # 場景數量不限 (使用者自選追蹤項目)

        if not scenes:
            print("[Strategist] [路徑 B] 場景建立失敗, 退回盲掃")
            return self._generate_turn1_experiments(state)

        # --- [OPTIMIZED] 根據場景類型 + analysis_type 動態選擇掃描工具 ---
        _analysis_type = getattr(state, "analysis_type", "anomaly_detection")
        scene_types = {s.scene_type for s in scenes}

        TOOL_MAP = {
            "anomaly_detection": [
                ("draw_trend", "分析 {p} 的時間趨勢"),
                ("classify_anomaly_type", "分類 {p} 的異常類型"),
                ("detect_outliers", "偵測 {p} 的離群值"),
            ],
            "optimization": [
                ("get_top_correlations", "找出與 {p} 最相關的參數"),
                ("analyze_feature_importance", "分析 {p} 的驅動因子"),
                ("performance_segmentation", "分割 {p} 的好壞批次"),
            ],
            "visualization": [
                ("draw_trend", "繪製 {p} 的時間趨勢圖"),
            ],
            "comparison": [
                ("draw_trend", "分析 {p} 的時間趨勢"),
                ("analyze_distribution", "分析 {p} 的分佈特性"),
            ],
        }

        # 場景類型覆蓋 analysis_type (語意判斷優先)
        if "optimization" in scene_types:
            selected_tools = TOOL_MAP["optimization"]
        else:
            selected_tools = TOOL_MAP.get(_analysis_type, TOOL_MAP["anomaly_detection"])

        # 多目標時補充交互分析 (避免重複)
        if len(targets) >= 2 and _analysis_type != "visualization":
            existing_techniques = {t[0] for t in selected_tools}
            if "get_top_correlations" not in existing_techniques:
                selected_tools.append(
                    ("get_top_correlations", "找出與 {p} 最相關的參數")
                )

        print(
            f"[Strategist] [路徑 B] scene_types={scene_types}, "
            f"選擇 {len(selected_tools)} 個工具: "
            f"{[t[0] for t in selected_tools]}"
        )

        experiments = []
        for i, param in enumerate(targets[:3]):
            for j, (technique, obj_template) in enumerate(selected_tools):
                experiments.append(
                    ExperimentContext(
                        id=f"scan_b_{i}_{j + 1:02d}",
                        objective=obj_template.format(p=param),
                        technique=technique,
                        target_columns=[param],
                        focus_range="Global",
                    )
                )

        # --- 格式化場景為後續追蹤項目 ---
        follow_up_items = []
        for s in scenes:
            follow_up_items.append(
                {
                    "scene_id": s.scene_id,
                    "label": s.label,
                    "scene_type": s.scene_type,
                    "targets": s.targets,
                }
            )

        scene_labels = [f"{s.scene_id}: {s.label}" for s in scenes]

        print(
            f"[Strategist] [路徑 B] 快速掃描 + 場景選單: {len(experiments)} 個掃描實驗, "
            f"{len(scenes)} 個追蹤項目"
        )
        for lbl in scene_labels:
            print(f"  - {lbl}")

        scene_list_text = "\n".join(f"  - {lbl}" for lbl in scene_labels)

        return RoleOutput(
            decision="CONTINUE",
            reasoning=(
                f"[Turn 1 路徑B: 快速掃描] 對 {len(targets[:3])} 個目標參數做四合一掃描, "
                f"建立 {len(scenes)} 個後續追蹤場景:\n{scene_list_text}"
            ),
            directive=f"快速掃描目標參數: {', '.join(targets[:3])}",
            experiments=experiments,
            structured_log={
                "turn1_type": "direct_scan",
                "follow_up_items": follow_up_items,
                "knowledge_addon": (
                    f"\n[場景選單] 共 {len(scenes)} 個追蹤項目: "
                    + " | ".join(scene_labels)
                ),
            },
        )

    def _build_scenes_from_autotarget(
        self, auto_target_data: dict, state: AnalysisState
    ) -> list:
        """
        [路徑 C 專用] 從四合一掃描的 AutoTarget 結果直接建場景。
        不使用 LLM, 確保場景目標與實際掃描發現一致。

        場景來源:
        - auto_targets (異常參數): 每個參數一個 parameter 場景
        - auto_row_ranges (異常區段): 每個區段一個 segment 場景
        - 如果參數 >= 2, 額外加一個 interaction 場景
        """
        from backend.services.analysis.analysis_types import SceneItem

        scenes = []
        scene_idx = 1

        auto_targets = auto_target_data.get("auto_targets", [])
        auto_row_ranges = auto_target_data.get("auto_row_ranges", [])
        query = getattr(state, "original_query", "") or ""

        # ── 快速模式: 只保留 1 個參數 + 1 個區段 ──
        _is_quick = getattr(state, "max_steps", 10) <= 5
        if _is_quick:
            auto_targets = auto_targets[:1]
            auto_row_ranges = auto_row_ranges[:1]

        # --- 1. 參數場景: 每個 AutoTarget 參數一個場景 ---
        for param in auto_targets[:3]:
            # 嘗試用 term_mappings 翻譯參數名
            term_mappings = getattr(state, "term_mappings", {})
            display_name = term_mappings.get(param, param)

            scenes.append(
                SceneItem(
                    scene_id=f"A{scene_idx}",
                    scene_type="parameter",
                    label=f"{display_name} 參數異常分析及影響因素調查",
                    targets=[param],
                    severity=float(7 - scene_idx),
                    status="PENDING",
                    source="四合一掃描 AutoTarget",
                )
            )
            scene_idx += 1

        # --- 2. 交互場景: 前兩個參數的相關性 ---
        if len(auto_targets) >= 2:
            p1, p2 = auto_targets[0], auto_targets[1]
            scenes.append(
                SceneItem(
                    scene_id=f"A{scene_idx}",
                    scene_type="interaction",
                    label=f"{p1} 與 {p2} 的交互作用與相關性分析",
                    targets=[p1, p2],
                    severity=float(7 - scene_idx),
                    status="PENDING",
                    source="四合一掃描 AutoTarget",
                )
            )
            scene_idx += 1

        # --- 3. 區段場景: 每個異常區段一個場景 ---
        for seg in auto_row_ranges[:2]:
            seg_range = seg.get("range", "")
            seg_params = seg.get("params", [])
            seg_severity = seg.get("severity", 3)
            # 提取純數字 row range (e.g., "Row 10-17" -> "10-17")
            import re as _re_seg

            _rr_match = _re_seg.search(r"(\d+-\d+)", seg_range)
            _row_range_str = _rr_match.group(1) if _rr_match else None

            scenes.append(
                SceneItem(
                    scene_id=f"A{scene_idx}",
                    scene_type="segment",
                    label=f"{seg_range} 異常區段根因調查",
                    targets=seg_params[:3],
                    row_range=_row_range_str,
                    severity=float(seg_severity),
                    status="PENDING",
                    source="四合一掃描 AutoTarget",
                )
            )
            scene_idx += 1

        # --- 4. 最佳化場景: 偵測用戶意圖 ---
        _opt_keywords = [
            "優化",
            "优化",
            "提升",
            "最佳",
            "良率",
            "SOP",
            "改善",
            "操作範圍",
            "操作范围",
            "怎麼調",
            "怎么调",
            "怎麼做",
            "怎么做",
            "最好",
            "建議",
            "建议",
            "設定值",
            "设定值",
            "控制",
            "目標",
            "目标",
            "範圍",
            "范围",
            "降低",
            "穩定",
            "維持",
            "维持",
            "調整",
            "调整",
        ]
        query_text = state.original_query.lower() if state.original_query else ""
        has_opt_intent = any(kw in query_text for kw in _opt_keywords)

        if has_opt_intent and auto_targets:
            opt_targets = auto_targets[:3]
            scenes.append(
                SceneItem(
                    scene_id=f"A{scene_idx}",
                    scene_type="optimization",
                    label=f"{', '.join(opt_targets)} 最佳化分析與 SOP 建議",
                    targets=opt_targets,
                    severity=4.0,
                    status="PENDING",
                    source="四合一掃描 + 最佳化意圖",
                )
            )
            scene_idx += 1
            print(f"[Strategist] [路徑 C] 偵測到最佳化意圖, 加入 optimization 場景")

        # 場景數量不限 (使用者自選追蹤項目)

        # 設定第一個為 ACTIVE
        if scenes:
            scenes[0].status = "ACTIVE"

        labels = [f"{s.scene_id}: {s.label}" for s in scenes]
        print(
            f"[Strategist] 四合一場景: {len(scenes)} 個 "
            f"({len(auto_targets)} 參數 + {len(auto_row_ranges)} 區段)"
        )
        for label in labels:
            print(f"  - {label}")

        return scenes

    async def _cluster_params_by_domain(
        self,
        expanded_params: list,
        term_mappings: dict,
        intent_label: str,
    ) -> dict:
        """
        [路徑 S 專用] 將概念展開後的參數按製程領域分群。
        例如: 溫度類、壓力類、真空類、速度類...

        輸入:
          - expanded_params: 概念展開後的參數名列表
          - term_mappings: {col_name: chinese_name}
          - intent_label: 意圖場景的 label

        回傳:
          dict: {"溫度類": [col1, col2, ...], "壓力類": [col3, ...], ...}
        """
        import json as _json

        if not expanded_params or len(expanded_params) < 4:
            return {}

        # 構建參數列表 (含中文名)
        param_lines = []
        for col in expanded_params[:100]:
            cn = term_mappings.get(col, "")
            if cn and cn != col:
                param_lines.append(f"  {col} = {cn}")
            else:
                param_lines.append(f"  {col}")
        param_text = "\n".join(param_lines)

        prompt = (
            f"你是製程數據領域專家。\n"
            f"分析意圖: 「{intent_label}」\n\n"
            f"以下是與此意圖相關的 {len(expanded_params)} 個參數:\n"
            f"{param_text}\n\n"
            "請將這些參數按製程領域分群。\n"
            "分群依據: 參數的物理意義或功能區域 (如溫度、壓力、速度、"
            "真空、流量、張力、電流、品質指標 等)。\n\n"
            "[規則]\n"
            "1. 每個分群至少 2 個參數\n"
            "2. 分群名稱要簡短 (如「烘缸溫度」「蒸氣壓力」「抽吸真空」)\n"
            "3. 分群數量: 3-6 個\n"
            "4. 參數名必須完全匹配 (區分大小寫)\n"
            "5. 無法歸類的參數放到「其他」群\n\n"
            "回傳 JSON:\n"
            "```json\n"
            "{\n"
            '  "clusters": {\n'
            '    "烘缸溫度": ["PARAM_A", "PARAM_B"],\n'
            '    "蒸氣壓力": ["PARAM_C", "PARAM_D"],\n'
            '    "抽吸真空": ["PARAM_E", "PARAM_F"]\n'
            "  }\n"
            "}\n"
            "```\n\n"
            "只回傳 JSON:\n"
        )

        try:
            resp = await self.llm.acomplete(prompt)
            text = str(resp.text).strip()

            import re as _re_cl

            json_match = _re_cl.search(r"\{.*\}", text, _re_cl.DOTALL)
            if json_match:
                text = json_match.group(0)

            parsed = _json.loads(text)
            clusters = parsed.get("clusters", parsed)

            # 驗證: 只保留實際存在的參數
            valid_set = set(expanded_params)
            result = {}
            for cluster_name, params in clusters.items():
                valid = [p for p in params if p in valid_set]
                if len(valid) >= 2:
                    result[cluster_name] = valid

            if result:
                total = sum(len(v) for v in result.values())
                print(
                    f"[Strategist] [Path S] 參數分群: {len(result)} 個領域, "
                    f"共 {total} 個參數 — "
                    + ", ".join(f"{k}({len(v)})" for k, v in result.items())
                )
            else:
                print("[Strategist] [Path S] 參數分群結果為空")

            return result

        except Exception as e:
            print(f"[Strategist] [Path S] 參數分群 LLM 失敗: {e}")
            # Fallback: 用參數名前綴分群
            return self._fallback_cluster_by_prefix(expanded_params)

    def _fallback_cluster_by_prefix(self, params: list) -> dict:
        """
        Fallback: 用參數名中的'-'前綴自動分群。
        例如: ACDRY-DCS_A103 → 前綴 ACDRY
        """
        from collections import defaultdict

        groups = defaultdict(list)
        for p in params:
            if "-" in p:
                prefix = p.split("-")[0]
            elif "_" in p:
                prefix = p.split("_")[0]
            else:
                prefix = "其他"
            groups[prefix].append(p)

        # 只保留 >= 2 個參數的群
        result = {k: v for k, v in groups.items() if len(v) >= 2}
        if result:
            print(
                f"[Strategist] [Path S] Prefix 分群: {len(result)} 個 — "
                + ", ".join(f"{k}({len(v)})" for k, v in result.items())
            )
        return result

    async def _build_scenes_from_intent(
        self,
        intent_label: str,
        intent_groups: dict,
        all_columns: list,
        state: "AnalysisState",
        parent_scene_id: str = "",
    ) -> list:
        """
        [路徑 S 專用] 從意圖場景 label + 概念展開分組, 用 LLM 規劃分析場景。
        每個分析場景描述兩組參數之間的分析 (Group vs Group)。

        輸入:
          - intent_label: 意圖場景的 label (如 "分析烘乾參數與水分含量參數之間的相關性")
          - intent_groups: 概念展開分組 {"溫度類": [col1, col2, ...], "壓力類": [col3, ...]}
          - all_columns: 全部欄位
          - state: 分析狀態

        回傳:
          List[SceneItem] — 2-4 個分析場景
        """
        import json as _json
        from backend.services.analysis.analysis_types import SceneItem

        if not intent_groups:
            print("[Strategist] [Path S] intent_groups 為空, 無法產生分析場景")
            return []

        # --- 構建分組摘要 ---
        group_summary_lines = []
        for group_name, params in intent_groups.items():
            sample_params = ", ".join(params[:5])
            suffix = f" ...共 {len(params)} 個" if len(params) > 5 else ""
            group_summary_lines.append(f"  {group_name}: {sample_params}{suffix}")
        groups_text = "\n".join(group_summary_lines)

        # --- 快速 vs 深度模式 ---
        _is_quick = getattr(state, "max_steps", 10) <= 5
        scene_count_hint = "2" if _is_quick else "2-4"

        # --- 構建 LLM Prompt ---
        prompt = (
            f"你是製程數據分析場景規劃師。\n"
            f"用戶選擇了意圖場景: 「{intent_label}」\n\n"
            f"概念展開已從 {len(all_columns)} 個欄位中, 識別出以下參數分組:\n"
            f"{groups_text}\n\n"
            f"請基於這些分組, 規劃 {scene_count_hint} 個分析場景。\n"
            "場景分為兩種類型:\n"
            "  A. 組間分析 — 兩個不同分組之間的關聯性/交互作用\n"
            "  B. 組內分析 — 同一分組內部參數的相關性變化 "
            "(重要: 出問題前後相關性可能改變)\n\n"
            "███ [場景設計原則] ███\n"
            "1. 至少包含 1 個組間分析 + 1 個組內分析\n"
            "2. 場景類型:\n"
            "   - parameter: 參數相關性/影響因素分析 (組間或組內)\n"
            "   - segment: 異常區段的差異比較 (組內前後段)\n"
            "   - interaction: 參數交互作用分析 (組間)\n"
            "3. 組內分析場景: group_a 和 group_b 填同一個分組名\n"
            "   targets 取該群的全部參數\n"
            "4. targets 取對應分組的全部參數名 (不要只取代表)\n"
            "5. 不同場景應覆蓋不同的分析角度, 避免重複\n"
            "6. label 必須使用分析類動詞 (分析、探討、比較、評估), 禁止使用\n"
            "   找出、識別、趨勢、趨勢圖、畫圖 等詞彙\n\n"
            "回傳 JSON 陣列, 格式:\n"
            "[\n"
            '  {"scene_id": "A1", "type": "parameter",\n'
            '   "label": "分析烘缸溫度與蒸氣壓力的相關性",\n'
            '   "group_a": "烘缸溫度", "group_b": "蒸氣壓力",\n'
            '   "targets": ["PARAM_1", "PARAM_2", "PARAM_3"],\n'
            '   "analysis_focus": "cross_group_correlation"},\n'
            '  {"scene_id": "A2", "type": "segment",\n'
            '   "label": "比較烘缸溫度群組內參數在不同區段的相關性變化",\n'
            '   "group_a": "烘缸溫度", "group_b": "烘缸溫度",\n'
            '   "targets": ["PARAM_A", "PARAM_B", "PARAM_C"],\n'
            '   "analysis_focus": "intra_group_stability"},\n'
            "注意: scene_id 由系統自動分配, 你只需填寫其他欄位即可。\n"
            "  ...\n"
            "]\n\n"
            "只回傳 JSON 陣列, 不要其他文字:\n"
        )

        try:
            resp = await self.llm.acomplete(prompt)
            resp_text = str(resp.text).strip()

            # 清理 markdown 包裹
            if "```" in resp_text:
                import re as _re_json

                json_match = _re_json.search(r"\[.*\]", resp_text, _re_json.DOTALL)
                if json_match:
                    resp_text = json_match.group(0)

            scenes_data = _json.loads(resp_text)
            if not isinstance(scenes_data, list):
                scenes_data = [scenes_data]

        except Exception as e:
            print(f"[Strategist] [Path S] LLM 場景規劃失敗: {e}, 使用 fallback")
            # Fallback: 從分組自動組合
            scenes_data = self._fallback_scenes_from_groups(
                intent_groups, intent_label, parent_scene_id=parent_scene_id
            )

        # --- 構建 SceneItem 列表 ---
        all_columns_set = set(all_columns) if all_columns else set()
        # 建立 group_name → params 的快速查找
        group_params_map = {k: v for k, v in intent_groups.items()}

        scenes = []
        for i, sd in enumerate(scenes_data[:4]):  # 最多 4 個場景
            scene_type = sd.get("type", "parameter")
            if scene_type not in ("parameter", "segment", "interaction"):
                scene_type = "parameter"

            # 驗證 targets: 只保留實際存在的欄位
            raw_targets = sd.get("targets", [])
            valid_targets = [t for t in raw_targets if t in all_columns_set]

            # 用分群的全部參數補充 targets (不截斷)
            group_a = sd.get("group_a", "")
            group_b = sd.get("group_b", "")
            for gname in [group_a, group_b]:
                if gname in group_params_map:
                    for p in group_params_map[gname]:
                        if p not in valid_targets:
                            valid_targets.append(p)
            # 去重 (不限制數量)
            valid_targets = list(dict.fromkeys(valid_targets))

            # 將 group_a, group_b 資訊存入 scene 以便後續 directive 使用
            _group_a = sd.get("group_a", "")
            _group_b = sd.get("group_b", "")
            _analysis_focus = sd.get("analysis_focus", "correlation")

            # 層級命名: 若有父場景 (如 A2), 子場景命名為 A2.1, A2.2
            if parent_scene_id:
                _sub_id = f"{parent_scene_id}.{i + 1}"
            else:
                _sub_id = f"A{i + 1}"
            scenes.append(
                SceneItem(
                    scene_id=_sub_id,
                    scene_type=scene_type,
                    label=sd.get("label", f"分析場景 {i + 1}"),
                    targets=valid_targets,
                    severity=float(6 - i),
                    status="ACTIVE" if i == 0 else "PENDING",
                    source=f"Path_S_intent|{_group_a}|{_group_b}|{_analysis_focus}",
                )
            )

        if scenes:
            labels = [f"{s.scene_id}: {s.label}" for s in scenes]
            print(
                f"[Strategist] [Path S] 從意圖「{intent_label[:30]}」"
                f"產生 {len(scenes)} 個分析場景:"
            )
            for lbl in labels:
                print(f"  - {lbl}")
        else:
            print("[Strategist] [Path S] 無法產生分析場景")

        return scenes

    def _fallback_scenes_from_groups(
        self,
        intent_groups: dict,
        intent_label: str,
        parent_scene_id: str = "",
    ) -> list:
        """
        Fallback: 當 LLM 失敗時, 從概念展開分組自動組合分析場景。
        策略: 最大的組 vs 其他各組 (組間) + 最大組的組內分析。
        """
        if not intent_groups or len(intent_groups) < 2:
            return []

        # 按參數數量排序, 最大的組作為 anchor
        sorted_groups = sorted(
            intent_groups.items(), key=lambda x: len(x[1]), reverse=True
        )
        anchor_name, anchor_params = sorted_groups[0]

        scenes_data = []

        # 組間分析場景: anchor vs 其他組
        for i, (group_name, params) in enumerate(sorted_groups[1:3]):
            combined_targets = anchor_params[:3] + params[:3]
            scenes_data.append(
                {
                    "scene_id": f"{parent_scene_id}.{i + 1}"
                    if parent_scene_id
                    else f"A{i + 1}",
                    "type": "parameter",
                    "label": f"分析{anchor_name}與{group_name}參數的關聯性",
                    "group_a": anchor_name,
                    "group_b": group_name,
                    "targets": combined_targets,
                    "analysis_focus": "cross_group_correlation",
                }
            )

        # 組內分析場景: anchor 組內部穩定性
        _intra_idx = len(scenes_data) + 1
        scenes_data.append(
            {
                "scene_id": f"{parent_scene_id}.{_intra_idx}"
                if parent_scene_id
                else f"A{_intra_idx}",
                "type": "segment",
                "label": f"比較{anchor_name}群組內參數在不同區段的相關性變化",
                "group_a": anchor_name,
                "group_b": anchor_name,
                "targets": anchor_params[:5],
                "analysis_focus": "intra_group_stability",
            }
        )

        print(
            f"[Strategist] [Path S] Fallback: 從 {len(sorted_groups)} 個分組"
            f"產生 {len(scenes_data)} 個場景 (含組內分析)"
        )
        return scenes_data

    async def _generate_extension_scenes(
        self,
        key_findings: list,
        original_query: str,
        state: "AnalysisState",
    ) -> list:
        """
        [路徑 S 專用] 從分析結論的 key_findings 生成延伸分析場景。
        回傳 follow_up_items 格式的 dict list (供前端紫色按鈕使用)。

        回傳格式:
          [{"scene_id": "E1", "label": "...", "targets": [...], "type": "parameter"}]
        """
        import json as _json

        if not key_findings:
            return []

        findings_text = "\n".join(f"  - {kf}" for kf in key_findings[:8])

        prompt = (
            f"你是製程數據分析延伸場景規劃師。\n"
            f"用戶原始問題: 「{original_query}」\n\n"
            f"分析結論發現:\n{findings_text}\n\n"
            "請基於以上結論, 規劃 2-3 個延伸分析場景。\n"
            "每個場景應是結論中值得深入調查的方向。\n\n"
            "[延伸場景設計原則]\n"
            "1. 基於結論中的「異常參數」「顯著相關性」「可疑模式」等發現\n"
            "2. 場景應具體可執行, 不能太籠統\n"
            "3. label 使用分析類動詞 (分析、探討、比較、評估)\n"
            "4. 禁止使用: 找出、識別、趨勢圖、畫圖\n\n"
            "回傳 JSON 陣列:\n"
            "[\n"
            '  {"scene_id": "E1", "type": "parameter",\n'
            '   "label": "深入分析 PARAM_X 的因果關係",\n'
            '   "targets": ["PARAM_X", "PARAM_Y"]},\n'
            "  ...\n"
            "]\n\n"
            "只回傳 JSON 陣列:\n"
        )

        try:
            resp = await self.llm.acomplete(prompt)
            resp_text = str(resp.text).strip()

            if "```" in resp_text:
                import re as _re_ext

                json_match = _re_ext.search(r"\[.*\]", resp_text, _re_ext.DOTALL)
                if json_match:
                    resp_text = json_match.group(0)

            ext_data = _json.loads(resp_text)
            if not isinstance(ext_data, list):
                ext_data = [ext_data]

            # 標準化: 確保每個 item 有必要欄位
            result = []
            for i, ed in enumerate(ext_data[:3]):
                item = {
                    "scene_id": ed.get("scene_id", f"E{i + 1}"),
                    "label": ed.get("label", f"延伸分析 {i + 1}"),
                    "type": ed.get("type", "parameter"),
                    "targets": ed.get("targets", []),
                    "source": "Path_S_extension",
                }
                result.append(item)

            if result:
                print(
                    f"[Strategist] [Path S] 延伸場景: {len(result)} 個 — "
                    + ", ".join(r["scene_id"] + ": " + r["label"] for r in result)
                )
            return result

        except Exception as e:
            print(f"[Strategist] [Path S] 延伸場景 LLM 失敗: {e}")
            return []

    def _build_hard_directive(
        self, scene, scene_targets: list, targets_str: str
    ) -> str:
        """
        根據場景類型生成 HARD OVERRIDE directive。
        [重要] 只描述「分析什麼」, 不指定工具名稱。
        工具選擇是 Planner 的職責。
        輸出前面會加 [scene_type: XXX] 標記, 讓 Planner 識別場景類型。
        """
        _type_tag = f"[scene_type: {scene.scene_type}]\n"
        if scene.scene_type == "segment":
            import re

            # 優先使用結構化 row_range，fallback 到 label 解析
            if scene.row_range:
                focus = f"Row {scene.row_range}"
                row_range_str = scene.row_range
            else:
                row_match = re.search(r"Row\s*\d+-\d+", scene.label)
                focus = row_match.group(0) if row_match else scene.label
                rr_match = re.search(r"(\d+-\d+)", focus)
                row_range_str = rr_match.group(1) if rr_match else ""

            questions = [
                f"- 比較 {focus} 異常區段與正常區段的數據差異",
                f"- 針對 {targets_str}, 在 {focus} 範圍內分析異常類型 (FREEZE/DRIFT/SPIKE/LEVEL_SHIFT)",
                f"- 對所有目標參數 ({targets_str}) 繪製趨勢圖，視覺確認各參數在 {focus} 的實際行為",
                f"- 量化目標參數在 {focus} 區段的分佈漂移程度 (與正常區段相比)",
                f"- 偵測 {focus} 區段內是否存在週期性干擾或頻率異常",
                f"- 分析目標參數之間在 {focus} 內的時間先後關係 (誰先變化)",
            ]
            constraint = (
                f"\n\n[場景約束 - 最高優先級]\n"
                f"本 Turn 分析範圍嚴格限定在: {focus}\n"
                f"目標參數: {targets_str}\n"
            )
            if row_range_str:
                constraint += (
                    f"\n[分析約束]\n"
                    f"- 焦點區段: {row_range_str}，所有區段比較必須以此為 target_segments\n"
                    f"- 目標參數: {targets_str}，每個目標參數都需要視覺確認 (趨勢圖)\n"
                    f"- 所有分析結果必須聚焦描述 {focus} 區間的變化\n"
                    f"- 禁止報告或引用 {focus} 以外的 Row 範圍\n"
                )
            return _type_tag + f"[區段分析問題]\n" + "\n".join(questions) + constraint

        elif scene.scene_type == "interaction":
            _focus = getattr(scene, "analysis_focus", "") or ""
            if _focus:
                return _type_tag + (
                    f"[分析焦點]\n{_focus}\n\n[場景約束] 目標參數: {targets_str}\n"
                )
            if len(scene_targets) >= 2:
                p1, p2 = scene_targets[0], scene_targets[1]
                questions = [
                    f"- 分析 {p1} 與 {p2} 的時間滯後關係 (誰先變化、誰後變化)",
                    f"- 檢測 {p1} 與 {p2} 的交互作用效果",
                    f"- 分析 {p1}, {p2} 與其他參數的相關性",
                ]
            else:
                questions = [
                    f"- 分析 {targets_str} 與其他參數的相關性",
                ]
            return _type_tag + (
                f"[交互分析問題]\n"
                + "\n".join(questions)
                + f"\n\n[場景約束] 本 Turn 只允許分析: {targets_str}\n"
            )

        elif scene.scene_type == "optimization":
            questions = [
                f"- 分割好批/壞批, 找出影響 {targets_str} 的關鍵差異因子",
                f"- 分析 {targets_str} 的邊際效應, 確定最佳操作範圍",
                f"- 生成 {targets_str} 相關參數的 SOP 建議表",
            ]
            return _type_tag + (
                f"[最佳化分析問題]\n"
                + "\n".join(questions)
                + f"\n\n[場景約束] 目標參數: {targets_str}\n"
            )

        elif scene.scene_type == "correlation_breakdown":
            questions = [
                f"- 比較 {targets_str} 在正常區段與異常區段的相關矩陣差異",
                f"- 找出原本高度相關但在異常時解耦的參數對 (共線性瓦解 = 因果鏈斷裂)",
                f"- 分析 {targets_str} 與其最相關參數的時間先後關係",
                f"- 確認瓦解的參數對是否有物理/製程上的因果邏輯",
            ]
            return _type_tag + (
                f"[共線性瓦解分析問題]\n"
                + "\n".join(questions)
                + f"\n\n[場景約束] 目標參數: {targets_str}\n"
            )

        else:
            # 取得分析焦點 (如果有)
            _focus = getattr(scene, "analysis_focus", "") or ""

            if _focus:
                # ★ 有明確焦點: 傳遞給 Planner, 由 Planner 決定用什麼方法
                return _type_tag + (
                    f"[分析焦點]\n{_focus}\n\n[場景約束] 目標參數: {targets_str}\n"
                )
            else:
                # 無焦點: 多目標均等分析 + 交叉分析
                target_questions = []

                # === A. 每個 target 都獲得完整分析問題 ===
                for t in scene_targets:
                    target_questions.extend(
                        [
                            f"- [{t}] 異常類型分析 (FREEZE/DRIFT/SPIKE/LEVEL_SHIFT)",
                            f"- [{t}] 時間趨勢與穩定性 (漂移、震盪、突變)",
                            f"- [{t}] 與其他參數的相關性排名",
                        ]
                    )

                # === B. 多目標交叉分析 (場景有 >=2 個 targets 時) ===
                if len(scene_targets) >= 2:
                    target_questions.append(
                        "\n[多目標交叉分析] (以下分析需涵蓋場景內所有 targets)"
                    )
                    target_questions.extend(
                        [
                            f"- 分析 {targets_str} 之間的共變關係 (是否同步異常?)",
                            f"- 檢查 {targets_str} 之間的共線性 (是否本質上是同一物理量?)",
                            f"- 如有異常區段, 比較所有 targets 在異常 vs 正常區段的差異",
                        ]
                    )
                    # 如果有 3 個以上 targets, 暗示可能是同一製程群組
                    if len(scene_targets) >= 3:
                        target_questions.append(
                            f"- 這些參數可能屬於同一製程群組, "
                            f"分析群組內的主成分 (PCA) 或相關網路結構"
                        )

                return _type_tag + (
                    f"[多目標參數分析]\n"
                    + "\n".join(target_questions)
                    + f"\n\n[場景約束]\n"
                    f"  本 Turn 必須分析的所有目標: {targets_str}\n"
                    f"  每個目標至少安排 1 個實驗, 禁止只分析其中一個而忽略其他。\n"
                    f"  優先使用支持多目標的工具 (如一次呼叫涵蓋多參數)。\n"
                )

    def _generate_turn1_experiments(self, state: AnalysisState) -> "RoleOutput":
        """
        Turn 1 硬編碼掃描, 不經 LLM, 保證 100% 確定性。
        依分析類型建立不同的 experiments, 透過 RoleOutput 回傳。
        """
        targets = (
            getattr(state.current_context, "targets", [])
            if state.current_context
            else []
        )
        knowledge = getattr(state, "current_knowledge", "") or ""
        is_optimization = "優化推薦" in knowledge or "多目標優化" in knowledge
        has_specific_targets = len(targets) > 0
        is_multi_target = is_optimization and len(targets) > 1

        if has_specific_targets and is_optimization:
            # --- 優化模式: 目標導向掃描 ---
            target_name = targets[0]
            experiments = []

            if is_multi_target:
                experiments.append(
                    ExperimentContext(
                        id="opt_00",
                        objective=f"分析多目標之間的 Synergy/Trade-off 關係",
                        technique="multi_objective_analysis",
                        target_columns=targets,
                        focus_range="Global",
                    )
                )

            experiments.extend(
                [
                    ExperimentContext(
                        id="opt_01",
                        objective=f"找出與 {target_name} 最相關的參數",
                        technique="get_top_correlations",
                        target_columns=[target_name],
                        focus_range="Global",
                    ),
                    ExperimentContext(
                        id="opt_02",
                        objective=f"找出驅動 {target_name} 的關鍵因子",
                        technique="analyze_feature_importance",
                        target_columns=[target_name],
                        focus_range="Global",
                    ),
                    ExperimentContext(
                        id="opt_03",
                        objective=f"分割好壞批次,比較 {target_name} 高低族群的參數差異",
                        technique="performance_segmentation",
                        target_columns=[target_name],
                        focus_range="Global",
                    ),
                    ExperimentContext(
                        id="opt_04",
                        objective=f"分析 {target_name} 的分佈特性",
                        technique="analyze_distribution",
                        target_columns=[target_name],
                        focus_range="Global",
                    ),
                ]
            )

            return RoleOutput(
                decision="CONTINUE",
                reasoning=f"[Turn 1 優化掃描] 目標: {target_name}, 執行 {len(experiments)} 個影響因子分析",
                directive=f"目標導向分析: {target_name}",
                experiments=experiments,
                structured_log={"turn1_type": "optimization", "target": target_name},
            )
        else:
            # --- 異常偵測 / 無目標: 四合一掃描 ---
            experiments = [
                ExperimentContext(
                    id="scan_01",
                    objective="全域 Z-Score 掃描",
                    technique="detect_outliers",
                    target_columns=["all"],
                    focus_range="Global",
                ),
                ExperimentContext(
                    id="scan_02",
                    objective="多變量異常偵測 (Hotelling T2)",
                    technique="hotelling_t2_analysis",
                    target_columns=["all"],
                    focus_range="Global",
                ),
                ExperimentContext(
                    id="scan_03",
                    objective="全域關聯性掃描",
                    technique="get_top_correlations",
                    target_columns=["all"],
                    focus_range="Global",
                ),
                ExperimentContext(
                    id="scan_04",
                    objective="全域異常區段掃描 (Row 範圍偵測)",
                    technique="scan_anomaly_segments",
                    target_columns=["all"],
                    focus_range="Global",
                ),
            ]

            return RoleOutput(
                decision="CONTINUE",
                reasoning="[Turn 1 初始掃描] 無特定目標, 執行標準四合一掃描",
                directive="全域初始掃描: detect_outliers + hotelling_t2 + correlations + anomaly_segments",
                experiments=experiments,
                structured_log={"turn1_type": "anomaly_scan"},
            )

    # ------------------------------------------------------------------
    # [NEW] AutoTarget 提取 (from Orchestrator)
    # ------------------------------------------------------------------
    def _extract_auto_targets(self, state: AnalysisState) -> dict:
        """
        從 Turn 1 的 evidences 中自動提取:
        - auto_targets: 異常參數 (from T2 top_contributions / detect_outliers)
        - auto_row_ranges: 異常區段 (from scan_anomaly_segments)
        回傳 dict: {
            "auto_targets": [...],
            "auto_row_ranges": [...],
            "knowledge_addon": str,
            "context_update": AnalysisContext | None,
            "summary_injection": str,
        }
        """
        auto_targets = []
        auto_row_ranges = []
        _anomaly_type_groups = []
        _t2_summary = {}  # T2 概要 (主成分數、解釋力)

        # 取得 Turn 1 的 evidences
        evidences = []
        if state.history:
            last_step = state.history[-1]
            ev_data = getattr(last_step, "evidence", None)
            if isinstance(ev_data, dict):
                evidences = ev_data.get("raw_evidences", [])
            elif isinstance(ev_data, list):
                evidences = ev_data

        # --- [主力] 從 T2 anomaly_zones 提取結構化異常區段 (由上往下) ---
        for ev in evidences:
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

                # === [NEW] 從 anomaly_zones 提取結構化區段 (主力來源) ===
                t2_zones = result.get("anomaly_zones", [])
                # 按 T2 最大值降序排列 (尖峰越高越優先)
                t2_zones = sorted(
                    t2_zones, key=lambda z: z.get("t2_max", 0), reverse=True
                )
                for zone in t2_zones[:8]:
                    zone_range = zone.get("zone_range", "")
                    t2_mean = zone.get("t2_mean", 0)
                    t2_max = zone.get("t2_max", 0)
                    zone_len = zone.get("length", 0)
                    # severity 基於 T2 強度
                    severity = min(10, 5 + t2_mean * 0.1)
                    # 取出此 zone 的 top contributors
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

                # Fallback: 如果 anomaly_zones 為空，從 primary_anomaly_range 補
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

            # --- scan_anomaly_segments: 只提取分類資訊, 不加入區段 ---
            # (時間段定位由 T2 zones 獨力負責)
            if ev.tool_name == "scan_anomaly_segments" and ev.status == "SUCCESS":
                result = ev.result if isinstance(ev.result, dict) else {}
                _anomaly_type_groups = result.get("anomaly_type_groups", [])

        # Fallback 2: detect_outliers 推斷區段
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

        if not auto_targets and not auto_row_ranges:
            return {
                "auto_targets": [],
                "auto_row_ranges": [],
                "knowledge_addon": "",
                "context_update": None,
                "summary_injection": "",
            }

        # --- 構建雙軌線索框架 ---
        param_clue = ""
        if auto_targets:
            target_list = "\n".join(
                f"    {i + 1}. {t}" for i, t in enumerate(auto_targets[:3])
            )
            param_clue = (
                f"\n  線索 1 — 參數線索 (Top {min(3, len(auto_targets))} 各做 1 Turn 完整分析):"
                f"\n{target_list}"
                f"\n    每個參數可用所有需要的工具, 但禁止延伸到新參數"
            )
        else:
            param_clue = "\n  線索 1 — 參數線索: 尚未發現顯著異常參數。"

        sample_clue = ""
        if auto_row_ranges:
            sample_lines = []
            for rr in auto_row_ranges:
                # [NEW] 優先使用 zone_label 顯示每個參數的異常類型
                zone_lbl = rr.get("zone_label", "")
                if zone_lbl:
                    sample_lines.append(
                        f"    {rr['range']} (severity={rr['severity']}) [{zone_lbl}]"
                    )
                else:
                    involved = ", ".join(rr["params"]) if rr["params"] else "未知"
                    sample_lines.append(
                        f"    {rr['range']} (severity={rr['severity']}, "
                        f"涉及: {involved}, 類型: {'/'.join(rr['types'])})"
                    )
            sample_clue = (
                f"\n  線索 2 — 樣本線索 (必須調查的異常區段):"
                f"\n"
                + "\n".join(sample_lines)
                + f"\n    → 每個 Turn 必須包含至少 1 個樣本問題:"
                f'\n      例: "{auto_row_ranges[0]["range"]} 與正常區間相比, 哪些參數差異最大?"'
                f'\n      例: "{auto_targets[0] if auto_targets else "某參數"} 的異常是否在 {auto_row_ranges[0]["range"]} 附近開始?"'
            )
        else:
            sample_clue = (
                f"\n  線索 2 — 樣本線索: 尚未發現顯著異常區段。"
                f'\n    但仍需每個 Turn 問: "{auto_targets[0] if auto_targets else "主要異常"} 的異常集中在哪些 Row 範圍?"'
            )

        knowledge_addon = (
            f"\n\n[掃描發現] Turn 1 發現 {len(auto_targets)} 個異常參數"
            + (f", {len(auto_row_ranges)} 個異常區段" if auto_row_ranges else "")
            + f"\n  異常參數: {', '.join(auto_targets[:5])}"
        )

        # --- 加入異常類型分組摘要 ---
        if _anomaly_type_groups:
            knowledge_addon += "\n\n[異常類型分析]"
            for tg in _anomaly_type_groups[:6]:
                type_cn = tg.get("type_cn", tg.get("type", ""))
                params = tg.get("parameters", [])
                param_count = tg.get("param_count", len(params))
                ranges = tg.get("ranges", [])
                range_str = ", ".join(ranges[:3]) if ranges else "未指定"
                param_str = ", ".join(params[:5])
                if len(params) > 5:
                    param_str += f" ...等{param_count}個"
                knowledge_addon += (
                    f"\n  {type_cn} ({param_count}個參數): {param_str}"
                    f"\n    主要區段: {range_str}"
                )

        knowledge_addon += (
            f"\n\n[線索追蹤]{param_clue}{sample_clue}"
            f"\n\n[潛在線索]"
            f"\n  分析過程中發現的新線索記錄在此, 不做深入分析:"
            f"\n  (尚無, 會在分析中逐步累積)"
            f"\n\n[場景機制] 場景清單將由 Strategist 根據掃描結果自動生成。"
        )

        # 區段注入 summary section
        segment_summary = ""
        if auto_row_ranges:
            seg_parts = []
            for rr in auto_row_ranges:
                zone_lbl = rr.get("zone_label", "")
                if zone_lbl:
                    seg_parts.append(
                        f"{rr['range']}(severity={rr['severity']}) [{zone_lbl}]"
                    )
                else:
                    involved = ", ".join(rr["params"]) if rr.get("params") else "未知"
                    seg_parts.append(
                        f"{rr['range']}(severity={rr['severity']}, {involved}, {'/'.join(rr.get('types', []))})"
                    )
            segment_summary = (
                f"已鎖定: {'; '.join(seg_parts)}。需比較異常區間與正常區間差異。"
            )

        context_update = AnalysisContext(
            targets=auto_targets,
            feature_pool=state.current_context.feature_pool
            if state.current_context
            else [],
        )

        return {
            "auto_targets": auto_targets,
            "auto_row_ranges": auto_row_ranges,
            "anomaly_type_groups": _anomaly_type_groups,
            "t2_summary": _t2_summary,
            "knowledge_addon": knowledge_addon,
            "context_update": context_update,
            "summary_injection": segment_summary,
        }
