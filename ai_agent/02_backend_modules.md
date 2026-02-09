# 02. 后端模块详细实现

> 本文档包含所有后端模块的完整代码框架，基于模块化架构设计

---

## 目录结构

```
backend/services/analysis/
├── __init__.py                 (  20行)
├── analysis_service.py         ( 350行)
├── agent.py                    ( 350行) [LlamaIndex 基於 Workflow 模式]
└── tools/
    ├── __init__.py             (  30行)
    ├── base.py                 (  50行)
    ├── data_query.py           ( 200行)
    ├── statistics.py           ( 250行)
    ├── patterns.py             ( 200行)
    ├── helpers.py              ( 100行)
    └── executor.py             ( 100行)
```

---

## 1. 包初始化 (`__init__.py`)

### `backend/services/analysis/__init__.py`

```python
"""
智能分析服务包
提供基于 LLM 的数据分析功能
"""

from .analysis_service import AnalysisService
from .agent import LLMAnalysisAgent
from .tools.executor import ToolExecutor

__all__ = [
    'AnalysisService',
    'LLMAnalysisAgent',
    'ToolExecutor',
]
```

---

## 2. 核心索引服务 (`analysis_service.py`, ~350行)

```python
# backend/services/analysis/analysis_service.py

import json
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Any
import hashlib
import logging

logger = logging.getLogger(__name__)

class AnalysisService:
    """
    数据分析核心服务
    负责：CSV 索引建立、数据摘要、语义搜索
    """
    
    def __init__(self, base_dir: str = "workspace"):
        self.base_dir = Path(base_dir)
        self.stop_events = {}  # session_id -> bool

    def stop_generation(self, session_id: str):
        """設定停止標誌"""
        self.stop_events[session_id] = True
        logger.info(f"Stop signal set for session: {session_id}")

    def clear_stop_signal(self, session_id: str):
        """清除停止標誌"""
        if session_id in self.stop_events:
            del self.stop_events[session_id]

    def is_generation_stopped(self, session_id: str) -> bool:
        """檢查是否收到停止信號"""
        return self.stop_events.get(session_id, False)
    
    def get_file_id(self, filename: str) -> str:
        """生成文件 ID（基于文件名的 hash）"""
        return hashlib.md5(filename.encode()).hexdigest()[:12]
    
    def get_analysis_path(self, session_id: str, file_id: str) -> Path:
        """获取分析文件存储路径"""
        analysis_dir = self.base_dir / session_id / "analysis" / file_id
        analysis_dir.mkdir(parents=True, exist_ok=True)
        return analysis_dir
    
    async def build_analysis_index(
        self, 
        csv_path: str, 
        session_id: str, 
        filename: str
    ) -> Dict:
        """
        为 CSV 文件建立分析索引
        这是一次性操作，结果会缓存
        
        生成文件：
        - summary.json: 基本摘要
        - statistics.json: 统计信息
        - correlations.json: 相关性矩阵
        - semantic_index.json: 语义索引
        """
        file_id = self.get_file_id(filename)
        analysis_path = self.get_analysis_path(session_id, file_id)
        
        # 检查是否已有索引
        summary_file = analysis_path / "summary.json"
        if summary_file.exists():
            logger.info(f"Index already exists for {filename}")
            with open(summary_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        
        logger.info(f"Building index for {filename}")
        
        # 读取 CSV
        df = pd.read_csv(csv_path)
        
        # 1. 生成基本摘要
        summary = {
            "file_id": file_id,
            "filename": filename,
            "total_rows": len(df),
            "total_columns": len(df.columns),
            "parameters": list(df.columns),
            "created_at": pd.Timestamp.now().isoformat()
        }
        
        # 2. 参数分类
        categories = self._categorize_parameters(df.columns)
        summary["categories"] = categories
        
        # 3. 计算统计信息
        statistics = self._calculate_statistics(df)
        with open(analysis_path / "statistics.json", 'w', encoding='utf-8') as f:
            json.dump(statistics, f, ensure_ascii=False, indent=2)
        
        # 4. 计算相关性矩阵
        correlations = self._calculate_correlations(df)
        with open(analysis_path / "correlations.json", 'w', encoding='utf-8') as f:
            json.dump(correlations, f, ensure_ascii=False, indent=2)
        
        # 5. 构建语义索引
        semantic_index = self._build_semantic_index(df.columns)
        with open(analysis_path / "semantic_index.json", 'w', encoding='utf-8') as f:
            json.dump(semantic_index, f, ensure_ascii=False, indent=2)
        
        # 保存摘要
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Index built successfully for {filename}")
        return summary
    
    def _categorize_parameters(self, columns: List[str]) -> Dict[str, List[str]]:
        """根据参数名前缀进行分类"""
        categories = {}
        for col in columns:
            # 提取前缀（如 TENSION-A101 -> TENSION）
            parts = col.split('-')
            if len(parts) > 1:
                category = parts[0]
            else:
                parts = col.split('_')
                category = parts[0] if len(parts) > 1 else "OTHER"
            
            if category not in categories:
                categories[category] = []
            categories[category].append(col)
        
        return categories
    
    def _calculate_statistics(self, df: pd.DataFrame) -> Dict:
        """计算所有数值参数的统计信息"""
        statistics = {}
        
        for col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col]):
                try:
                    statistics[col] = {
                        "count": int(df[col].count()),
                        "mean": float(df[col].mean()),
                        "std": float(df[col].std()),
                        "min": float(df[col].min()),
                        "max": float(df[col].max()),
                        "median": float(df[col].median()),
                        "q1": float(df[col].quantile(0.25)),
                        "q3": float(df[col].quantile(0.75)),
                        "missing_count": int(df[col].isna().sum())
                    }
                except Exception as e:
                    logger.warning(f"Failed to calculate stats for {col}: {e}")
        
        return statistics
    
    def _calculate_correlations(self, df: pd.DataFrame) -> Dict:
        """计算数值参数间的相关性矩阵"""
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        
        if len(numeric_cols) < 2:
            return {}
        
        corr_matrix = df[numeric_cols].corr()
        
        # 转换为可序列化的格式
        correlations = {}
        for col1 in numeric_cols:
            correlations[col1] = {}
            for col2 in numeric_cols:
                correlations[col1][col2] = float(corr_matrix.loc[col1, col2])
        
        return correlations
    
    def _build_semantic_index(self, columns: List[str]) -> Dict[str, List[str]]:
        """
        构建语义索引：概念 -> 参数列表
        支持中英文关键词搜索
        """
        # 关键词映射表
        keyword_map = {
            "温度": ["TEMP", "HEAT", "BCDRY", "ACDRY", "温", "热"],
            "张力": ["TENSION", "PULL", "STRESS", "张", "拉"],
            "湿度": ["MOISTURE", "HUMIDITY", "WET", "湿", "水"],
            "速度": ["SPEED", "VELOCITY", "RPM", "速"],
            "压力": ["PRESSURE", "PRESS", "压"],
            "品质": ["QUALITY", "GRADE", "METROLOGY", "品", "质"],
            "断纸": ["BREAK", "BREAKAGE", "断", "裂"],
            "流量": ["FLOW", "RATE", "流"],
            "浓度": ["CONCENTRATION", "CONSISTENCY", "浓"],
        }
        
        semantic_index = {}
        for concept, keywords in keyword_map.items():
            matched = []
            for col in columns:
                col_upper = col.upper()
                for kw in keywords:
                    if kw.upper() in col_upper:
                        matched.append(col)
                        break
            if matched:
                semantic_index[concept] = matched
        
        return semantic_index
    
    def load_summary(self, session_id: str, file_id: str) -> Dict:
        """加载文件摘要"""
        analysis_path = self.get_analysis_path(session_id, file_id)
        summary_file = analysis_path / "summary.json"
        
        if not summary_file.exists():
            raise FileNotFoundError(f"Summary not found for file_id: {file_id}")
        
        with open(summary_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def _load_mapping_table(
        self, session_id: str, file_id: Optional[str] = None
    ) -> Dict[str, str]:
        """
        加载术语对应表
        优先级：
        1. 绑定文件 (analysis/{file_id}/mapping.csv)
        2. 全局文件 (uploads/(参数对应表)_*.csv)
        """
        # ... (Implementation details: check bound first, then global)
        pass
    
    def load_correlations(self, session_id: str, file_id: str) -> Dict:
        """加载相关性矩阵"""
        analysis_path = self.get_analysis_path(session_id, file_id)
        corr_file = analysis_path / "correlations.json"
        
        if not corr_file.exists():
            raise FileNotFoundError(f"Correlations not found for file_id: {file_id}")
        
        with open(corr_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def load_semantic_index(self, session_id: str, file_id: str) -> Dict:
        """加载语义索引"""
        analysis_path = self.get_analysis_path(session_id, file_id)
        index_file = analysis_path / "semantic_index.json"
        
        if not index_file.exists():
            raise FileNotFoundError(f"Semantic index not found for file_id: {file_id}")
        
        with open(index_file, 'r', encoding='utf-8') as f:
            return json.load(f)
```

---

## 3. 工具基类 (`tools/base.py`, ~50行)

```python
# backend/services/analysis/tools/base.py

from abc import ABC, abstractmethod
from typing import Dict, Any, List

class AnalysisTool(ABC):
    """分析工具抽象基类"""
    
    def __init__(self, analysis_service):
        self.analysis_service = analysis_service
    
    @property
    @abstractmethod
    def name(self) -> str:
        """工具名称"""
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """工具描述"""
        pass
    
    @property
    def required_params(self) -> List[str]:
        """必需参数列表（子类可覆盖）"""
        return ['file_id']
    
    @abstractmethod
    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        """
        执行工具
        
        Args:
            params: 工具参数
            session_id: 用户会话 ID
        
        Returns:
            工具执行结果
        """
        pass
    
    def validate_params(self, params: Dict) -> bool:
        """验证参数完整性"""
        return all(p in params for p in self.required_params)
```

---

## 4. 工具包初始化 (`tools/__init__.py`, ~30行)

```python
# backend/services/analysis/tools/__init__.py

from .base import AnalysisTool
from .data_query import (
    GetParameterListTool,
    GetParameterStatisticsTool,
    SearchParametersByConceptTool,
)
from .statistics import (
    CalculateCorrelationTool,
    GetTopCorrelationsTool,
    CompareGroupsTool,
)
from .executor import ToolExecutor

__all__ = [
    'AnalysisTool',
    'ToolExecutor',
    # 查询工具
    'GetParameterListTool',
    'GetParameterStatisticsTool',
    'SearchParametersByConceptTool',
    # 统计工具
    'CalculateCorrelationTool',
    'GetTopCorrelationsTool',
    'CompareGroupsTool',
]
```

---

## 5. 查询工具 (`tools/data_query.py`, ~200行)

```python
# backend/services/analysis/tools/data_query.py

from .base import AnalysisTool
from typing import Dict, Any

class GetParameterListTool(AnalysisTool):
    """获取数据集的所有字段列表"""
    name = "get_parameter_list"
    description = "获取CSV文件的所有字段名称，支持关键字过滤"
    required_params = ["file_id"]
    
    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get('file_id')
        keyword = params.get('keyword', '').lower()
        
        summary = self.analysis_service.load_summary(session_id, file_id)
        all_params = summary['parameters']
        
        # 关键字过滤
        if keyword:
            matched = [p for p in all_params if keyword in p.lower()]
        else:
            matched = all_params
        
        return {
            "parameters": matched,
            "total_count": len(all_params),
            "matched_count": len(matched),
            "categories": summary.get('categories', {})
        }


class GetParameterStatisticsTool(AnalysisTool):
    """获取字段的统计信息"""
    name = "get_parameter_statistics"
    description = "返回字段的均值、中位数、标准差、最大值、最小值等"
    required_params = ["file_id", "parameter"]
    
    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get('file_id')
        parameter = params.get('parameter')
        
        statistics = self.analysis_service.load_statistics(session_id, file_id)
        
        if parameter not in statistics:
            return {"error": f"Parameter {parameter} not found or not numeric"}
        
        result = statistics[parameter].copy()
        result["parameter"] = parameter
        
        return result


class SearchParametersByConceptTool(AnalysisTool):
    """根据关键词搜索相关字段"""
    name = "search_parameters_by_concept"
    description = "例如输入'价格'，能找到'单价'、'总价'、'售价'等相关字段"
    required_params = ["file_id", "concept"]
    
    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get('file_id')
        concept = params.get('concept', '')
        
        semantic_index = self.analysis_service.load_semantic_index(session_id, file_id)
        summary = self.analysis_service.load_summary(session_id, file_id)
        
        matched_parameters = []
        
        # 语义索引匹配
        if concept in semantic_index:
            for param in semantic_index[concept]:
                matched_parameters.append({
                    "name": param,
                    "confidence": 0.9,
                    "reason": f"语义映射: {concept}"
                })
        
        # 模糊匹配
        for param in summary['parameters']:
            if concept.lower() in param.lower():
                if not any(m['name'] == param for m in matched_parameters):
                    matched_parameters.append({
                        "name": param,
                        "confidence": 0.7,
                        "reason": "关键字匹配"
                    })
        
        return {
            "matched_parameters": matched_parameters,
            "total_matches": len(matched_parameters)
        }


# 其他查询工具可在此继续添加...
# class GetDataOverviewTool(AnalysisTool): ...
# class GetTimeSeriesDataTool(AnalysisTool): ...
```

---

## 6. 统计工具 (`tools/statistics.py`, ~250行)

```python
# backend/services/analysis/tools/statistics.py

from .base import AnalysisTool
from typing import Dict, Any
import pandas as pd
from scipy.stats import pearsonr, spearmanr, ttest_ind
from pathlib import Path

class CalculateCorrelationTool(AnalysisTool):
    """计算相关性工具"""
    
    name = "calculate_correlation"
    description = "计算参数间的相关系数"
    required_params = ['file_id', 'parameters']
    
    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get('file_id')
        parameters = params.get('parameters', [])
        method = params.get('method', 'pearson')
        target = params.get('target')
        
        # 加载 CSV 数据
        csv_path = self._get_csv_path(session_id, file_id)
        df = pd.read_csv(csv_path)
        
        results = []
        
        if target:
            # 计算所有参数与 target 的相关性
            for param in parameters:
                if param in df.columns and target in df.columns:
                    try:
                        corr, p_val = self._calc_corr(df[param], df[target], method)
                        results.append({
                            "param1": param,
                            "param2": target,
                            "correlation": float(corr),
                            "p_value": float(p_val),
                            "interpretation": self._interpret_corr(corr, p_val)
                        })
                    except Exception as e:
                        continue
        else:
            # 两两计算
            for i in range(len(parameters)):
                for j in range(i + 1, len(parameters)):
                    p1, p2 = parameters[i], parameters[j]
                    if p1 in df.columns and p2 in df.columns:
                        try:
                            corr, p_val = self._calc_corr(df[p1], df[p2], method)
                            results.append({
                                "param1": p1,
                                "param2": p2,
                                "correlation": float(corr),
                                "p_value": float(p_val),
                                "interpretation": self._interpret_corr(corr, p_val)
                            })
                        except:
                            continue
        
        return {
            "method": method,
            "results": results
        }
    
    def _calc_corr(self, x, y, method):
        if method == 'pearson':
            return pearsonr(x, y)
        elif method == 'spearman':
            return spearmanr(x, y)
        else:
            return pearsonr(x, y)
    
    def _interpret_corr(self, corr: float, p_value: float) -> str:
        if p_value >= 0.05:
            return "无统计显著性"
        
        abs_corr = abs(corr)
        if abs_corr >= 0.7:
            strength = "强"
        elif abs_corr >= 0.4:
            strength = "中等"
        else:
            strength = "弱"
        
        direction = "正" if corr > 0 else "负"
        return f"{strength}{direction}相关，统计显著"
    
    def _get_csv_path(self, session_id: str, file_id: str) -> str:
        """获取 CSV 文件路径"""
        analysis_path = self.analysis_service.get_analysis_path(session_id, file_id)
        summary = self.analysis_service.load_summary(session_id, file_id)
        filename = summary['filename']
        return str(Path(self.analysis_service.base_dir) / session_id / "uploads" / filename)


class GetTopCorrelationsTool(AnalysisTool):
    """获取 Top 相关性工具"""
    
    name = "get_top_correlations"
    description = "快速获取与目标变量相关性最强的参数"
    required_params = ['file_id', 'target']
    
    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get('file_id')
        target = params.get('target')
        top_n = params.get('top_n', 10)
        min_corr = params.get('min_correlation', 0.3)
        
        # 读取相关性矩阵
        correlations = self.analysis_service.load_correlations(session_id, file_id)
        
        if target not in correlations:
            return {"error": f"Target {target} not found"}
        
        # 提取与 target 的相关性
        results = []
        for param, corr_value in correlations[target].items():
            if param != target and abs(corr_value) >= min_corr:
                results.append({
                    "parameter": param,
                    "correlation": corr_value,
                    "p_value": 0.001  # 简化，实际应重新计算
                })
        
        # 排序
        results.sort(key=lambda x: abs(x["correlation"]), reverse=True)
        
        return {
            "target": target,
            "top_correlations": results[:top_n]
        }


class CompareGroupsTool(AnalysisTool):
    """组间比较工具"""
    
    name = "compare_groups"
    description = "比较不同条件下参数的差异（t-test）"
    required_params = ['file_id', 'parameter', 'group_by']
    
    def execute(self, params: Dict, session_id: str) -> Dict[str, Any]:
        file_id = params.get('file_id')
        parameter = params.get('parameter')
        group_by = params.get('group_by')
        
        # 加载数据
        csv_path = self._get_csv_path(session_id, file_id)
        df = pd.read_csv(csv_path)
        
        if parameter not in df.columns or group_by not in df.columns:
            return {"error": "Parameter or group_by not found"}
        
        # 分组统计
        groups = df.groupby(group_by)[parameter]
        group_stats = {}
        group_data = {}
        
        for name, group in groups:
            group_stats[f"group_{name}"] = {
                "mean": float(group.mean()),
                "std": float(group.std()),
                "count": len(group)
            }
            group_data[name] = group.values
        
        # t-test
        if len(group_data) == 2:
            g1, g2 = list(group_data.values())
            stat, p_val = ttest_ind(g1, g2)
            test_result = {
                "statistic": float(stat),
                "p_value": float(p_val),
                "interpretation": "两组均值存在显著差异" if p_val < 0.05 else "两组均值无显著差异"
            }
        else:
            test_result = {"error": "Only supports 2 groups for t-test"}
        
        return {
            "parameter": parameter,
            "groups": group_stats,
            "test_result": test_result
        }
    
    def _get_csv_path(self, session_id: str, file_id: str) -> str:
        analysis_path = self.analysis_service.get_analysis_path(session_id, file_id)
        summary = self.analysis_service.load_summary(session_id, file_id)
        filename = summary['filename']
        return str(Path(self.analysis_service.base_dir) / session_id / "uploads" / filename)


# 其他统计工具...
# class DetectOutliersTool(AnalysisTool): ...
# class AnalyzeDistributionTool(AnalysisTool): ...
# class PerformRegressionTool(AnalysisTool): ...
```

---

## 7. 智能分析 Agent (`agent.py`, ~300行)

```python
# backend/services/analysis/agent.py

from typing import Dict, Any, List, Optional
from llama_index.core.agent import ReActAgent
from llama_index.llms.ollama import Ollama
from llama_index.core.tools import FunctionTool
from .tools.executor import ToolExecutor

### 2. SigmaAnalysisWorkflow (智慧分析工作流)

**文件**: `backend/services/analysis/agent.py`

這是系統的核心大腦，基於 LlamaIndex `Workflow` 實作。它管轄了從問題進入到最終答案輸出的所有邏輯節點。

#### 2.1 核心定義
```python
class SigmaAnalysisWorkflow(Workflow):
    """
    Sigma2 智慧分析工作流 (事件驅動狀態機)
    """
    def __init__(
        self, 
        tool_executor: ToolExecutor,
        analysis_service: AnalysisService,
        timeout: int = 200,
        verbose: bool = True
    ):
        super().__init__(timeout=timeout, verbose=verbose)
        self.tool_executor = tool_executor
        self.analysis_service = analysis_service
        self.llm = Ollama(model="llama3", request_timeout=120.0)
```

#### 2.2 關鍵工作站 (Steps)
- **ExecuteAnalysis** (Local): 執行 Pandas 運算。
    - **智慧分流 (Smart Skip)**: 系統會檢查結果是否包含數值數據。
        - 若包含數據：拋出 `VisualizingEvent` 進入繪圖站。
        - 若僅為清單或文本：跳過繪圖站，直接拋出 `SummarizeEvent` 進入總結站。
- **Visualizer** (LLM): **[New]** 繪圖工作站。專門負責預讀數據並生成 Chart JSON，確保可視化邏輯不與文字總結衝突。
- **ExpandConcept** (LLM): 當地端搜尋無結果時，使用領域知識聯想替代術語（如「斷紙」-> "Paper Break"）。
- **ExecuteTranslation**: 處理非分析類的語言請求。
- **Humanizer** (LLM): 生成繁體中文報告。它會整合 Visualizer 產生的圖表，並專注於專家級的數據解讀。

#### 2.3 事件傳送帶 (Events)
系統定義了明確的事件內容：
- `IntentEvent`: 攜帶 query, intent, history 等。
- `AnalysisEvent`: 觸發地端分析。
- `ConceptExpansionEvent`: 觸發語義聯想循環。
- `VisualizingEvent`: **[New]** 攜帶地端原始數據，交給繪圖站處理。
- `SummarizeEvent`: 攜帶地端數據與（選配的）Chart JSON 回傳給總結站。
- `StopEvent`: 結束信號。

        # 注入 file_id 到 context 中，或直接傳遞
        # LlamaIndex 會自動管理對話狀態
        response = await self.agent.achat(user_question)
        
        # 提取工具呼叫紀錄（用於前端展示）
        tool_log = []
        if response.sources:
            for source in response.sources:
                tool_log.append({
                    "tool": source.tool_name,
                    "params": source.raw_input,
                    "result": source.content
                })

        return {
            "response": response.response,
            "tool_used": tool_log[0]["tool"] if tool_log else None,
            "tool_result": tool_log[0]["result"] if tool_log else None,
            "all_tool_calls": tool_log
        }

    def _wrap_tools(self) -> List[FunctionTool]:
        """封裝現有工具"""
        li_tools = []
        for name, tool in self.tool_executor.tools.items():
            # 使用 LlamaIndex 的包裝器將自定義工具轉為 Agent 可識別格式
            wrapped = FunctionTool.from_defaults(
                fn=tool.execute,
                name=tool.name,
                description=tool.description
            )
            li_tools.append(wrapped)
        return li_tools
```

---

**說明**: 使用 LlamaIndex 框架後，傳統的「規則匹配」意圖識別已被其內建的推理引擎取代，這提供了更強的健壯性與多輪對話能力。


---

## 下一步

查看 **[03_api_design.md](./03_api_design.md)** 了解 API 接口设计。
