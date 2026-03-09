"""
統一工具註冊表 (Unified Tool Registry)
確保 Planner 和 Executor 對工具的理解完全一致
"""

from typing import Dict, List, Any, Optional

TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {
    # === A. 基礎統計與查詢 (Data & Stats) ===
    "basic_stats": {
        "category": "Data & Stats",
        "description": "[單參數] 快速摘要 (mean, std, min, max, missing)",
        "required_params": [],
        "optional_params": ["parameter"],
        "executor_function": "basic_stats",
        "supports_global": False,
    },
    "analyze_distribution": {
        "category": "Data & Stats",
        "description": "[單參數] 檢查常態性 (Shapiro-Wilk) 與基本分佈形狀",
        "required_params": ["parameter"],
        "optional_params": [],
        "executor_function": "analyze_distribution",
        "supports_global": False,
    },
    "get_data_overview": {
        "category": "Data & Stats",
        "description": "[全域] 取得資料的整體維度與欄位清單",
        "required_params": [],
        "optional_params": [],
        "executor_function": "get_data_overview",
        "supports_global": True,
    },
    "search_parameters_by_concept": {
        "category": "Data & Stats",
        "description": "[全域] 根據關鍵字找出生產參數",
        "required_params": ["concept"],
        "optional_params": [],
        "executor_function": "search_parameters_by_concept",
        "supports_global": False,
    },
    # === B. 關聯性與影響力 (Relationships & Drivers) ===
    "correlation_analysis": {
        "category": "Relationships",
        "description": "[單參數] 計算兩個變數間的 Pearson/Spearman 相關係數",
        "required_params": ["target"],
        "optional_params": ["reference"],
        "executor_function": "get_correlation_matrix",
        "supports_global": False,
    },
    "get_top_correlations": {
        "category": "Relationships",
        "description": "[單參數] 找出與目標變數最相關的前 K 個因子",
        "required_params": ["target"],
        "optional_params": ["top_k"],
        "executor_function": "get_top_correlations",
        "supports_global": True,
        "global_target": "all",
    },
    "analyze_feature_importance": {
        "category": "Relationships",
        "description": "[單參數] 使用 ML 模型 (Random Forest/XGBoost) 找出非線性關鍵因子",
        "required_params": ["target"],
        "optional_params": ["method"],
        "executor_function": "analyze_feature_importance",
        "supports_global": False,
    },
    "detect_correlation_breakdown": {
        "category": "Relationships",
        "description": "[單參數] 比較正常/異常區段的相關矩陣變化, 找出共線性瓦解 (因果鏈斷裂)",
        "required_params": ["target"],
        "optional_params": ["anomaly_range", "top_n"],
        "executor_function": "detect_correlation_breakdown",
        "supports_global": False,
    },
    "analyze_category_correlation": {
        "category": "Relationships",
        "description": "[雙參數] 分析類別型變數 (ANOVA/Kruskal-Wallis), 需指定 target + category",
        "required_params": ["target", "category"],
        "optional_params": [],
        "executor_function": "analyze_category_correlation",
        "supports_global": False,
    },
    # === C. 異常偵測與比較 (Anomaly & Comparison) ===
    "hotelling_t2_analysis": {
        "category": "Anomaly Detection",
        "description": "[多參數] 多變量異常偵測 (Mahalanobis Distance)，適合 Global Health Check",
        "required_params": ["target_columns"],
        "optional_params": ["focus_range"],
        "executor_function": "hotelling_t2_analysis",
        "supports_global": True,
        "global_target": "all",
    },
    "detect_outliers": {
        "category": "Anomaly Detection",
        "description": "[單參數] 單變量 IQR/Z-Score 檢測",
        "required_params": ["parameter"],
        "optional_params": ["method"],
        "executor_function": "detect_outliers",
        "supports_global": False,
    },
    "multivariate_anomaly_detection": {
        "category": "Anomaly Detection",
        "description": "[全域] 使用 Isolation Forest / LOF 偵測複雜異常",
        "required_params": [],
        "optional_params": ["method"],
        "executor_function": "multivariate_anomaly_detection",
        "supports_global": True,
    },
    "compare_distributions": {
        "category": "Comparison",
        "description": "[單參數] 比較兩個區間 (Focus vs Baseline) 的分佈差異 (KS Test)",
        "required_params": ["parameter", "focus_range", "baseline_range"],
        "optional_params": [],
        "executor_function": "distribution_shift_analysis",
        "supports_global": False,
    },
    "compare_data_segments": {
        "category": "Comparison",
        "description": "[單參數] 比較兩個資料片段的統計特性",
        "required_params": ["target_segments"],
        "optional_params": ["baseline_segments"],
        "executor_function": "compare_data_segments",
        "supports_global": False,
    },
    "distribution_shift_analysis": {
        "category": "Comparison",
        "description": "[單參數] 使用 Wasserstein Distance 量化分佈的漂移程度",
        "required_params": ["parameter", "focus_range", "baseline_range"],
        "optional_params": [],
        "executor_function": "distribution_shift_analysis",
        "supports_global": False,
    },
    # === D. 時間序列與模式 (Time Series & Patterns) ===
    "draw_trend": {
        "category": "Time Series",
        "description": "[單參數] 繪製時間序列圖，觀察趨勢與週期",
        "required_params": ["parameter"],
        "optional_params": ["focus_range"],
        "executor_function": "get_time_series_data",
        "supports_global": False,
    },
    "get_time_series_data": {
        "category": "Time Series",
        "description": "[單參數] 取得時間序列資料",
        "required_params": ["parameter"],
        "optional_params": ["start_index", "end_index"],
        "executor_function": "get_time_series_data",
        "supports_global": False,
    },
    "find_temporal_patterns": {
        "category": "Patterns",
        "description": "[單參數] 偵測週期性 (Seasonality) 與趨勢 (Trend)",
        "required_params": ["parameter"],
        "optional_params": [],
        "executor_function": "find_temporal_patterns",
        "supports_global": False,
    },
    "find_event_patterns": {
        "category": "Patterns",
        "description": "[全域] 偵測特定事件序列",
        "required_params": [],
        "optional_params": ["event_type"],
        "executor_function": "find_event_patterns",
        "supports_global": False,
    },
    "causal_relationship_analysis": {
        "category": "Causal",
        "description": "[雙參數] 使用 Granger Causality 檢定時間序列因果關係 (Lag Effect), 需指定 target + reference",
        "required_params": ["target_parameter"],
        "optional_params": ["reference_parameters", "max_lag"],
        "executor_function": "causal_relationship_analysis",
        "supports_global": False,
    },
    # === E. 進階分析 (Advanced) ===
    "systemic_pca_analysis": {
        "category": "Advanced",
        "description": "[全域] 降維分析，觀察資料在主成分空間的分佈",
        "required_params": [],
        "optional_params": ["n_components"],
        "executor_function": "systemic_pca_analysis",
        "supports_global": True,
    },
    "analyze_residuals": {
        "category": "Advanced",
        "description": "[單參數] 分析模型殘差，尋找未被解釋的變異",
        "required_params": ["target"],
        "optional_params": ["predictors"],
        "executor_function": "analyze_residuals",
        "supports_global": False,
    },
    # === F. 進階診斷工具 (Advanced Diagnostics) ===
    "classify_anomaly_type": {
        "category": "Advanced Diagnostics",
        "description": "[單參數] 將異常區間分類為具體模式 (Freeze/Oscillation/Spike/Drift/Level Shift)",
        "required_params": ["parameter"],
        "optional_params": ["focus_range"],
        "executor_function": "classify_anomaly_type",
        "supports_global": False,
    },
    "cross_correlation_lag": {
        "category": "Advanced Diagnostics",
        "description": "[雙參數] 計算交叉相關找出兩變數的前導-滯後關係 (Lead-Lag), 需指定 target + reference",
        "required_params": ["target"],
        "optional_params": ["reference", "max_lag"],
        "executor_function": "cross_correlation_lag",
        "supports_global": False,
    },
    "frequency_analysis": {
        "category": "Advanced Diagnostics",
        "description": "[單參數] 使用 PSD 頻域分析偵測週期性干擾與傳感器凍結",
        "required_params": ["parameter"],
        "optional_params": ["focus_range", "baseline_range"],
        "executor_function": "frequency_analysis",
        "supports_global": False,
    },
    "control_loop_assessment": {
        "category": "Advanced Diagnostics",
        "description": "[單參數] 評估控制回路品質 (Harris Index, 追蹤誤差, 飽和偵測)",
        "required_params": ["process_variable"],
        "optional_params": ["setpoint", "controller_output"],
        "executor_function": "control_loop_assessment",
        "supports_global": False,
    },
    # === G. 效能分析與優化 (Performance & Optimization) ===
    "performance_segmentation": {
        "category": "Optimization",
        "description": "[單參數] 依目標變數分割好批/壞批 (Top/Bottom 25%),比較參數差異找出關鍵因子",
        "required_params": ["target"],
        "optional_params": ["split_method", "threshold", "top_k"],
        "executor_function": "performance_segmentation",
        "supports_global": False,
    },
    "generate_operating_window": {
        "category": "Optimization",
        "description": "[單參數] 基於好批次統計生成 SOP 建議表 (建議設定值 + 操作範圍 + 調整方向)",
        "required_params": ["target"],
        "optional_params": ["direction", "top_k"],
        "executor_function": "generate_operating_window",
        "supports_global": False,
    },
    "interaction_scatter": {
        "category": "Optimization",
        "description": "[三參數] 兩參數交互作用散佈圖 (Color=目標值),自動識別最佳操作窗口 (Sweet Spot), 需指定 x_param + y_param + color_param",
        "required_params": ["x_param", "y_param", "color_param"],
        "optional_params": ["direction"],
        "executor_function": "interaction_scatter",
        "supports_global": False,
    },
    "interaction_effect_test": {
        "category": "Optimization",
        "description": "[三參數] 兩因子交互作用統計檢定 (Two-Way ANOVA): 量化 A, B 主效應和 A*B 交互效應, 需指定 param_a + param_b + target",
        "required_params": ["param_a", "param_b", "target"],
        "optional_params": [],
        "executor_function": "interaction_effect_test",
        "supports_global": False,
    },
    "partial_dependence": {
        "category": "Optimization",
        "description": "[多參數] Partial Dependence 邊際效應: 看單一參數變化對目標的非線性影響曲線, 需指定 target + features 列表",
        "required_params": ["target", "features"],
        "optional_params": ["n_grid_points"],
        "executor_function": "partial_dependence",
        "supports_global": False,
    },
    # === H. 系統級分析 (System-Level Analysis) ===
    "correlation_network": {
        "category": "System Analysis",
        "description": "[全域] 相關性網路分析: 找出 Hub 中樞參數 (Degree/Betweenness Centrality)",
        "required_params": [],
        "optional_params": ["threshold", "top_k"],
        "executor_function": "correlation_network",
        "supports_global": True,
    },
    "cv_ranking": {
        "category": "System Analysis",
        "description": "[全域] 變異係數 CV 排名: 跨量綱比較所有參數的波動性,找出最不穩定的變數",
        "required_params": [],
        "optional_params": ["top_k", "focus_range"],
        "executor_function": "cv_ranking",
        "supports_global": True,
    },
    "regime_detection": {
        "category": "System Analysis",
        "description": "[全域] 操作模式識別: K-Means 聚類分群,找出不同操作 Regime 及切換時間點",
        "required_params": [],
        "optional_params": ["n_clusters", "max_clusters", "top_features"],
        "executor_function": "regime_detection",
        "supports_global": True,
    },
    "multi_objective_analysis": {
        "category": "Optimization",
        "description": "[多參數] 多目標優化: 同時分析多個目標的 Synergy/Trade-off,生成多劇本調整建議, 需指定 targets 列表",
        "required_params": ["targets"],
        "optional_params": ["top_k"],
        "executor_function": "multi_objective_analysis",
        "supports_global": False,
    },
    "batch_aggregation": {
        "category": "System Analysis",
        "description": "[單參數] 批次/區域維度聚合分析: 按批次 ID 或自動分段,對目標參數進行跨批次 ANOVA 差異檢定和最差批次排名",
        "required_params": ["target"],
        "optional_params": ["batch_column", "batch_count"],
        "executor_function": "batch_aggregation",
        "supports_global": False,
    },
    "wavelet_analysis": {
        "category": "Advanced Diagnostics",
        "description": "[單參數] 連續小波變換 (CWT) 時頻分析: 偵測頻率隨時間的變化 (瞬態干擾/狀態切換)",
        "required_params": ["parameter"],
        "optional_params": ["n_scales", "sampling_rate"],
        "executor_function": "wavelet_analysis",
        "supports_global": False,
    },
    "scan_anomaly_segments": {
        "category": "Anomaly Detection",
        "description": "[全域] 全域異常區段掃描: 自動掃描所有數值欄位,偵測異常 Row 範圍 (FREEZE/DRIFT/SPIKE/OSCILLATION/LEVEL_SHIFT),按嚴重程度排名。適用於無目標分析的初始掃描。",
        "required_params": [],
        "optional_params": [],
        "executor_function": "scan_anomaly_segments",
        "supports_global": True,
    },
    "parallel_coordinates": {
        "category": "Visualization",
        "description": "[多參數] 平行座標圖: 多參數歸一化比較,好批 vs 壞批差異視覺化, 需指定 target_columns 列表",
        "required_params": ["target_columns"],
        "optional_params": ["color_param", "focus_range", "top_k"],
        "executor_function": "parallel_coordinates",
        "supports_global": True,
    },
    "radar_chart": {
        "category": "Visualization",
        "description": "[多參數] 雷達圖: 多維度參數特徵對比 (好批 vs 壞批 / 各組 Regime), 需指定 target_columns 列表",
        "required_params": ["target_columns"],
        "optional_params": ["color_param", "group_by", "top_k"],
        "executor_function": "radar_chart",
        "supports_global": True,
    },
    "event_sequence_analysis": {
        "category": "Advanced Diagnostics",
        "description": "[單參數] 事件序列關聯: 偵測上游參數突變事件與目標異常的時序因果關係 (Hit Rate + Lift)",
        "required_params": ["target"],
        "optional_params": ["lookback_window", "event_threshold", "top_k"],
        "executor_function": "event_sequence_analysis",
        "supports_global": False,
    },
    "stratified_interaction": {
        "category": "Performance & Optimization",
        "description": "[三參數] 分層交互效應: 在各批次/區段內分別做兩因子交互分析, 需指定 param_a + param_b + target",
        "required_params": ["param_a", "param_b", "target"],
        "optional_params": ["batch_column", "batch_count"],
        "executor_function": "stratified_interaction",
        "supports_global": False,
    },
    "trend_prediction": {
        "category": "Advanced Diagnostics",
        "description": "[單參數] 趨勢預測: 線性/指數趨勢擬合 + 管制線超限預估 (預測漂移何時超出 UCL/LCL)",
        "required_params": ["target"],
        "optional_params": ["ucl", "lcl", "forecast_horizon", "method"],
        "executor_function": "trend_prediction",
        "supports_global": False,
    },
    # === I. 參數降維 (Parameter Reduction) ===
    "cluster_trend": {
        "category": "Parameter Reduction",
        "description": "[多參數] 分群代表趨勢圖: 將大量相關參數依相關性分群, 每群選 CV 最高的代表畫趨勢疊圖。適合概念(如溫度)對應太多欄位時使用",
        "required_params": [],
        "optional_params": ["parameters", "concept", "n_clusters"],
        "executor_function": "cluster_trend",
        "supports_global": True,
    },
    "pca_trend": {
        "category": "Parameter Reduction",
        "description": "[多參數] PCA 降維趨勢圖: 將大量相關參數做主成分分析, 畫各主成分的時間序列趨勢, 顯示解釋方差與主要貢獻參數。適合概念(如溫度)對應太多欄位時用降維壓縮觀察整體趨勢",
        "required_params": [],
        "optional_params": ["parameters", "concept", "n_components"],
        "executor_function": "pca_trend",
        "supports_global": True,
    },
    # === J. 組合工具 (Combo Tools) ===
    "combo_parameter_profiling": {
        "category": "Combo",
        "description": "[組合·多參數] 四合一參數掃描 (趨勢+分佈+相關性排名+異常偵測)",
        "required_params": [],
        "optional_params": ["parameters", "focus_range"],
        "executor_function": "combo_parameter_profiling",
        "supports_global": False,
        "covers": [
            "draw_trend",
            "analyze_distribution",
            "get_top_correlations",
            "detect_outliers",
        ],
    },
    "combo_anomaly_diagnosis": {
        "category": "Combo",
        "description": "[組合·單參數] 異常深度診斷 (異常類型分類+時序穩定性+頻域分析)",
        "required_params": ["parameter"],
        "optional_params": ["focus_range"],
        "executor_function": "combo_anomaly_diagnosis",
        "supports_global": False,
        "covers": [
            "classify_anomaly_type",
            "find_temporal_patterns",
            "frequency_analysis",
        ],
    },
    "combo_optimization": {
        "category": "Combo",
        "description": "[組合·單參數] 最佳化全流程 (好壞批分割+因子排名+SOP建議表)",
        "required_params": ["target"],
        "optional_params": ["split_method", "top_k"],
        "executor_function": "combo_optimization",
        "supports_global": False,
        "covers": [
            "performance_segmentation",
            "analyze_feature_importance",
            "generate_operating_window",
        ],
    },
    "combo_causal_tracing": {
        "category": "Combo",
        "description": "[組合·單參數] 因果鏈追蹤 (Lead-Lag交叉相關+Granger因果+事件序列)",
        "required_params": ["target"],
        "optional_params": ["reference", "max_lag"],
        "executor_function": "combo_causal_tracing",
        "supports_global": False,
        "covers": [
            "cross_correlation_lag",
            "causal_relationship_analysis",
            "event_sequence_analysis",
        ],
    },
}


def get_tool_spec(technique: str) -> Optional[Dict[str, Any]]:
    """取得工具規格"""
    return TOOL_REGISTRY.get(technique)


def validate_technique(technique: str) -> bool:
    """驗證工具名稱是否存在"""
    return technique in TOOL_REGISTRY


def get_executor_function(technique: str) -> Optional[str]:
    """取得對應的 Executor 函數名稱"""
    spec = get_tool_spec(technique)
    return spec.get("executor_function") if spec else None


def list_all_tools() -> List[str]:
    """列出所有可用工具名稱"""
    return list(TOOL_REGISTRY.keys())


def get_tools_by_category(category: str) -> List[str]:
    """依類別取得工具清單"""
    return [
        name for name, spec in TOOL_REGISTRY.items() if spec.get("category") == category
    ]


def get_combo_coverage_map() -> Dict[str, Dict]:
    """
    取得所有 combo 工具的覆蓋映射表。
    回傳格式: { "被覆蓋的原子工具": { "combo_tool": "combo名稱", "covers_list": [...] } }
    """
    coverage = {}
    for tool_name, spec in TOOL_REGISTRY.items():
        covers = spec.get("covers", [])
        if covers:
            for covered_tool in covers:
                coverage[covered_tool] = {
                    "combo_tool": tool_name,
                    "all_covers": covers,
                }
    return coverage


def shield_covered_experiments(experiments: list) -> list:
    """
    通用複合工具遮蔽函數。
    如果實驗列表中存在 combo 工具, 自動移除被其覆蓋的原子工具 (同 target 才遮蔽)。

    Args:
        experiments: ExperimentContext 列表
    Returns:
        過濾後的 ExperimentContext 列表
    """
    # 1. 掃描所有 combo 工具及其覆蓋的 targets
    combo_coverage = {}  # { "被覆蓋工具名": {覆蓋的 targets set} }
    for exp in experiments:
        spec = TOOL_REGISTRY.get(exp.technique, {})
        covers = spec.get("covers", [])
        if covers:
            targets = set(exp.target_columns or ["all"])
            has_all = "all" in targets
            for covered_tool in covers:
                if covered_tool not in combo_coverage:
                    combo_coverage[covered_tool] = {"targets": set(), "has_all": False}
                combo_coverage[covered_tool]["targets"].update(targets)
                if has_all:
                    combo_coverage[covered_tool]["has_all"] = True

    if not combo_coverage:
        return experiments

    # 2. 過濾被覆蓋的原子工具
    filtered = []
    removed_count = 0
    for exp in experiments:
        if exp.technique in combo_coverage:
            coverage_info = combo_coverage[exp.technique]
            exp_targets = set(exp.target_columns or ["all"])
            # 如果 combo 覆蓋 'all' 或原子工具的所有 targets 都被覆蓋
            if coverage_info["has_all"] or exp_targets.issubset(
                coverage_info["targets"]
            ):
                print(
                    f"[SHIELD] {exp.technique}({exp_targets}) 已被 combo 工具覆蓋, 移除"
                )
                removed_count += 1
                continue
        filtered.append(exp)

    if removed_count > 0:
        print(f"[SHIELD] 共移除 {removed_count} 個被 combo 覆蓋的原子工具實驗")

    return filtered
