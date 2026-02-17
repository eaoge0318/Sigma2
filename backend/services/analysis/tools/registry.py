"""
統一工具註冊表 (Unified Tool Registry)
確保 Planner 和 Executor 對工具的理解完全一致
"""

from typing import Dict, List, Any, Optional

TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {
    # === A. 基礎統計與查詢 (Data & Stats) ===
    "basic_stats": {
        "category": "Data & Stats",
        "description": "快速摘要 (mean, std, min, max, missing)",
        "required_params": [],
        "optional_params": ["parameter"],
        "executor_function": "basic_stats",
        "supports_global": False,
    },
    "analyze_distribution": {
        "category": "Data & Stats",
        "description": "檢查常態性 (Shapiro-Wilk) 與基本分佈形狀",
        "required_params": ["parameter"],
        "optional_params": [],
        "executor_function": "analyze_distribution",
        "supports_global": False,
    },
    "get_data_overview": {
        "category": "Data & Stats",
        "description": "取得資料的整體維度與欄位清單",
        "required_params": [],
        "optional_params": [],
        "executor_function": "get_data_overview",
        "supports_global": True,
    },
    "search_parameters_by_concept": {
        "category": "Data & Stats",
        "description": "根據關鍵字找出生產參數",
        "required_params": ["concept"],
        "optional_params": [],
        "executor_function": "search_parameters_by_concept",
        "supports_global": False,
    },
    # === B. 關聯性與影響力 (Relationships & Drivers) ===
    "correlation_analysis": {
        "category": "Relationships",
        "description": "計算兩個變數間的 Pearson/Spearman 相關係數",
        "required_params": ["target"],
        "optional_params": ["reference"],
        "executor_function": "get_correlation_matrix",
        "supports_global": False,
    },
    "get_top_correlations": {
        "category": "Relationships",
        "description": "找出與目標變數最相關的前 K 個因子",
        "required_params": ["target"],
        "optional_params": ["top_k"],
        "executor_function": "get_top_correlations",
        "supports_global": True,
        "global_target": "all",
    },
    "analyze_feature_importance": {
        "category": "Relationships",
        "description": "使用 ML 模型 (Random Forest/XGBoost) 找出非線性關鍵因子",
        "required_params": ["target"],
        "optional_params": ["method"],
        "executor_function": "analyze_feature_importance",
        "supports_global": False,
    },
    "analyze_category_correlation": {
        "category": "Relationships",
        "description": "分析類別型變數 (ANOVA/Kruskal-Wallis)",
        "required_params": ["target", "category"],
        "optional_params": [],
        "executor_function": "analyze_category_correlation",
        "supports_global": False,
    },
    # === C. 異常偵測與比較 (Anomaly & Comparison) ===
    "hotelling_t2_analysis": {
        "category": "Anomaly Detection",
        "description": "多變量異常偵測 (Mahalanobis Distance)，適合 Global Health Check",
        "required_params": ["target_columns"],
        "optional_params": ["focus_range"],
        "executor_function": "hotelling_t2_analysis",
        "supports_global": True,
        "global_target": "all",
    },
    "detect_outliers": {
        "category": "Anomaly Detection",
        "description": "單變量 IQR/Z-Score 檢測",
        "required_params": ["parameter"],
        "optional_params": ["method"],
        "executor_function": "detect_outliers",
        "supports_global": False,
    },
    "multivariate_anomaly_detection": {
        "category": "Anomaly Detection",
        "description": "使用 Isolation Forest / LOF 偵測複雜異常",
        "required_params": [],
        "optional_params": ["method"],
        "executor_function": "multivariate_anomaly_detection",
        "supports_global": True,
    },
    "compare_distributions": {
        "category": "Comparison",
        "description": "比較兩個區間 (Focus vs Baseline) 的分佈差異 (KS Test)",
        "required_params": ["parameter", "focus_range", "baseline_range"],
        "optional_params": [],
        "executor_function": "distribution_shift_analysis",
        "supports_global": False,
    },
    "compare_data_segments": {
        "category": "Comparison",
        "description": "比較兩個資料片段的統計特性",
        "required_params": ["target_segments"],
        "optional_params": ["baseline_segments"],
        "executor_function": "compare_data_segments",
        "supports_global": False,
    },
    "distribution_shift_analysis": {
        "category": "Comparison",
        "description": "使用 Wasserstein Distance 量化分佈的漂移程度",
        "required_params": ["parameter", "focus_range", "baseline_range"],
        "optional_params": [],
        "executor_function": "distribution_shift_analysis",
        "supports_global": False,
    },
    # === D. 時間序列與模式 (Time Series & Patterns) ===
    "draw_trend": {
        "category": "Time Series",
        "description": "繪製時間序列圖，觀察趨勢與週期",
        "required_params": ["parameter"],
        "optional_params": ["focus_range"],
        "executor_function": "get_time_series_data",
        "supports_global": False,
    },
    "get_time_series_data": {
        "category": "Time Series",
        "description": "取得時間序列資料",
        "required_params": ["parameter"],
        "optional_params": ["start_index", "end_index"],
        "executor_function": "get_time_series_data",
        "supports_global": False,
    },
    "find_temporal_patterns": {
        "category": "Patterns",
        "description": "偵測週期性 (Seasonality) 與趨勢 (Trend)",
        "required_params": ["parameter"],
        "optional_params": [],
        "executor_function": "find_temporal_patterns",
        "supports_global": False,
    },
    "find_event_patterns": {
        "category": "Patterns",
        "description": "偵測特定事件序列",
        "required_params": [],
        "optional_params": ["event_type"],
        "executor_function": "find_event_patterns",
        "supports_global": False,
    },
    "causal_relationship_analysis": {
        "category": "Causal",
        "description": "使用 Granger Causality 檢定時間序列因果關係 (Lag Effect)",
        "required_params": ["target_parameter"],
        "optional_params": ["reference_parameters", "max_lag"],
        "executor_function": "causal_relationship_analysis",
        "supports_global": False,
    },
    # === E. 進階分析 (Advanced) ===
    "systemic_pca_analysis": {
        "category": "Advanced",
        "description": "降維分析，觀察資料在主成分空間的分佈",
        "required_params": [],
        "optional_params": ["n_components"],
        "executor_function": "systemic_pca_analysis",
        "supports_global": True,
    },
    "analyze_residuals": {
        "category": "Advanced",
        "description": "分析模型殘差，尋找未被解釋的變異",
        "required_params": ["target"],
        "optional_params": ["predictors"],
        "executor_function": "analyze_residuals",
        "supports_global": False,
    },
    # === F. 進階診斷工具 (Advanced Diagnostics) ===
    "classify_anomaly_type": {
        "category": "Advanced Diagnostics",
        "description": "將異常區間分類為具體模式 (Freeze/Oscillation/Spike/Drift/Level Shift)",
        "required_params": ["parameter"],
        "optional_params": ["focus_range"],
        "executor_function": "classify_anomaly_type",
        "supports_global": False,
    },
    "cross_correlation_lag": {
        "category": "Advanced Diagnostics",
        "description": "計算交叉相關找出兩變數的前導-滯後關係 (Lead-Lag)",
        "required_params": ["target"],
        "optional_params": ["reference", "max_lag"],
        "executor_function": "cross_correlation_lag",
        "supports_global": False,
    },
    "frequency_analysis": {
        "category": "Advanced Diagnostics",
        "description": "使用 PSD 頻域分析偵測週期性干擾與傳感器凍結",
        "required_params": ["parameter"],
        "optional_params": ["focus_range", "baseline_range"],
        "executor_function": "frequency_analysis",
        "supports_global": False,
    },
    "control_loop_assessment": {
        "category": "Advanced Diagnostics",
        "description": "評估控制回路品質 (Harris Index, 追蹤誤差, 飽和偵測)",
        "required_params": ["process_variable"],
        "optional_params": ["setpoint", "controller_output"],
        "executor_function": "control_loop_assessment",
        "supports_global": False,
    },
    # === G. 效能分析與優化 (Performance & Optimization) ===
    "performance_segmentation": {
        "category": "Optimization",
        "description": "依目標變數分割好批/壞批 (Top/Bottom 25%),比較參數差異找出關鍵因子",
        "required_params": ["target"],
        "optional_params": ["split_method", "threshold", "top_k"],
        "executor_function": "performance_segmentation",
        "supports_global": False,
    },
    "generate_operating_window": {
        "category": "Optimization",
        "description": "基於好批次統計生成 SOP 建議表 (建議設定值 + 操作範圍 + 調整方向)",
        "required_params": ["target"],
        "optional_params": ["direction", "top_k"],
        "executor_function": "generate_operating_window",
        "supports_global": False,
    },
    "interaction_scatter": {
        "category": "Optimization",
        "description": "兩參數交互作用散佈圖 (Color=目標值),自動識別最佳操作窗口 (Sweet Spot)",
        "required_params": ["x_param", "y_param", "color_param"],
        "optional_params": ["direction"],
        "executor_function": "interaction_scatter",
        "supports_global": False,
    },
    "interaction_effect_test": {
        "category": "Optimization",
        "description": "兩因子交互作用統計檢定 (Two-Way ANOVA): 量化 A, B 主效應和 A*B 交互效應的 F-value / p-value",
        "required_params": ["param_a", "param_b", "target"],
        "optional_params": [],
        "executor_function": "interaction_effect_test",
        "supports_global": False,
    },
    "partial_dependence": {
        "category": "Optimization",
        "description": "Partial Dependence 邊際效應: 看單一參數變化對目標的非線性影響曲線",
        "required_params": ["target", "features"],
        "optional_params": ["n_grid_points"],
        "executor_function": "partial_dependence",
        "supports_global": False,
    },
    # === H. 系統級分析 (System-Level Analysis) ===
    "correlation_network": {
        "category": "System Analysis",
        "description": "相關性網路分析: 找出 Hub 中樞參數 (Degree/Betweenness Centrality)",
        "required_params": [],
        "optional_params": ["threshold", "top_k"],
        "executor_function": "correlation_network",
        "supports_global": True,
    },
    "cv_ranking": {
        "category": "System Analysis",
        "description": "變異係數 CV 排名: 跨量綱比較所有參數的波動性,找出最不穩定的變數",
        "required_params": [],
        "optional_params": ["top_k", "focus_range"],
        "executor_function": "cv_ranking",
        "supports_global": True,
    },
    "regime_detection": {
        "category": "System Analysis",
        "description": "操作模式識別: K-Means 聚類分群,找出不同操作 Regime 及切換時間點",
        "required_params": [],
        "optional_params": ["n_clusters", "max_clusters", "top_features"],
        "executor_function": "regime_detection",
        "supports_global": True,
    },
    "multi_objective_analysis": {
        "category": "Optimization",
        "description": "多目標優化: 同時分析多個目標的 Synergy/Trade-off,生成多劇本調整建議",
        "required_params": ["targets"],
        "optional_params": ["top_k"],
        "executor_function": "multi_objective_analysis",
        "supports_global": False,
    },
    "batch_aggregation": {
        "category": "System Analysis",
        "description": "批次/區域維度聚合分析: 按批次 ID 或自動分段,對目標參數進行跨批次 ANOVA 差異檢定和最差批次排名",
        "required_params": ["target"],
        "optional_params": ["batch_column", "batch_count"],
        "executor_function": "batch_aggregation",
        "supports_global": False,
    },
    "wavelet_analysis": {
        "category": "Advanced Diagnostics",
        "description": "連續小波變換 (CWT) 時頻分析: 偵測頻率隨時間的變化 (瞬態干擾/狀態切換)",
        "required_params": ["parameter"],
        "optional_params": ["n_scales", "sampling_rate"],
        "executor_function": "wavelet_analysis",
        "supports_global": False,
    },
    "parallel_coordinates": {
        "category": "Visualization",
        "description": "平行座標圖: 多參數歸一化比較,好批 vs 壞批差異視覺化",
        "required_params": ["target_columns"],
        "optional_params": ["color_param", "focus_range", "top_k"],
        "executor_function": "parallel_coordinates",
        "supports_global": True,
    },
    "radar_chart": {
        "category": "Visualization",
        "description": "雷達圖: 多維度參數特徵對比 (好批 vs 壞批 / 各組 Regime)",
        "required_params": ["target_columns"],
        "optional_params": ["color_param", "group_by", "top_k"],
        "executor_function": "radar_chart",
        "supports_global": True,
    },
    "event_sequence_analysis": {
        "category": "Advanced Diagnostics",
        "description": "事件序列關聯: 偵測上游參數突變事件與目標異常的時序因果關係 (Hit Rate + Lift)",
        "required_params": ["target"],
        "optional_params": ["lookback_window", "event_threshold", "top_k"],
        "executor_function": "event_sequence_analysis",
        "supports_global": False,
    },
    "stratified_interaction": {
        "category": "Performance & Optimization",
        "description": "分層交互效應: 在各批次/區段內分別做兩因子交互分析,比較跨批次交互效應差異",
        "required_params": ["param_a", "param_b", "target"],
        "optional_params": ["batch_column", "batch_count"],
        "executor_function": "stratified_interaction",
        "supports_global": False,
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
