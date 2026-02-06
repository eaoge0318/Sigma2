"""
Session 資料模型
分離不同功能的 Session，避免互相干擾
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field


@dataclass
class DashboardSession:
    """即時看板 Session"""

    prediction_history: List[Dict[str, Any]] = field(default_factory=list)
    sim_index: int = 0
    sim_df: Any = None
    sim_file_name: Optional[str] = None
    current_model_config: Optional[Dict[str, Any]] = None  # 當前載入的模型配置


@dataclass
class AnalysisSession:
    """數據分析 Session"""

    current_file: Optional[str] = None
    filters: List[Dict[str, Any]] = field(default_factory=list)
    selected_columns: List[str] = field(default_factory=list)
    chart_analysis_history: List[Dict[str, Any]] = field(
        default_factory=list
    )  # 圖表分析歷史


@dataclass
class AISession:
    """AI 對話 Session"""

    chat_history: List[Dict[str, Any]] = field(default_factory=list)
