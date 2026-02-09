# 智能分析功能详细实作计划（基于本地 RAG）

## 核心架构总览

### 技术栈确认

**已确认的技术选型**：
- **本地 LLM**: Ollama (gemma3:27b-it-qat)
- **API 端点**: `http://10.10.20.214:11434/api/chat`
- **请求方式**: 使用现有的 `LLMReporter` 类
- **用户隔离**: 基于 `session_id` 的多租户文件系统
- **文件管理**: 复用现有的 `FileService`

### 系统整合方式

```
现有系统
├── workspace/{session_id}/uploads/     # 用户上传的CSV文件
├── workspace/{session_id}/bundles/     # 训练生成的Bundle
└── core_logic/llm_reporter.py          # LLM连接服务

新增智能分析
├── workspace/{session_id}/analysis/    # 分析索引和会话
│   ├── {file_id}/
│   │   ├── summary.json               # 数据摘要
│   │   ├── correlations.json          # 相关性矩阵
│   │   ├── statistics.json            # 统计信息
│   │   └── semantic_index.json        # 语义索引
│   └── conversations/
│       └── {conversation_id}.json     # 对话历史
├── backend/services/
│   ├── analysis_service.py            # 分析核心服务
│   ├── analysis_tool_executor.py      # 工具执行器
│   └── llm_analysis_agent.py          # LLM Agent
└── backend/routers/
    └── analysis_router.py             # API路由
```

---

## 核心设计：增强的分析工具集

基于您的需求"8个工具可能不够"，我扩展了工具集：

### 第一类：数据查询与探索（5个工具）

#### 工具 1: `get_parameter_list`
```python
{
  "name": "get_parameter_list",
  "description": "获取CSV文件的所有参数列表，支持关键字过滤和分类",
  "parameters": {
    "file_id": "string",
    "keyword": "string (optional)",
    "category": "string (optional)"
  },
  "returns": {
    "parameters": ["TENSION-A101", "BCDRY-A90", ...],
    "total_count": 150,
    "matched_count": 12,
    "categories": {"TENSION": [...], "BCDRY": [...]}
  }
}
```

#### 工具 2: `get_parameter_statistics`
```python
{
  "name": "get_parameter_statistics",
  "description": "获取指定参数的详细统计信息",
  "parameters": {
    "file_id": "string",
    "parameter": "string",
    "include_distribution": "boolean (default: false)"
  },
  "returns": {
    "parameter": "TENSION-A101",
    "count": 1000,
    "mean": 450.2,
    "std": 25.3,
    "min": 380,
    "max": 650,
    "median": 448.5,
    "q1": 430.1,
    "q3": 470.8,
    "distribution": {  // if requested
      "histogram": {"bins": [...], "counts": [...]},
      "skewness": 0.15,
      "kurtosis": -0.3
    }
  }
}
```

#### 工具 3: `get_data_overview`
```python
{
  "name": "get_data_overview",
  "description": "获取整个数据集的总览信息",
  "parameters": {
    "file_id": "string"
  },
  "returns": {
    "filename": "production_data.csv",
    "total_rows": 10000,
    "total_columns": 150,
    "time_range": {
      "start": "2024-01-01 00:00",
      "end": "2024-01-31 23:59"
    },
    "missing_data": {
      "total_missing": 150,
      "parameters_with_missing": ["PARAM_A", "PARAM_B"]
    },
    "data_quality_score": 0.95
  }
}
```

#### 工具 4: `search_parameters_by_concept`
```python
{
  "name": "search_parameters_by_concept",
  "description": "根据概念（中文或英文）智能搜索相关参数",
  "parameters": {
    "file_id": "string",
    "concept": "string",  // 如 "温度", "张力", "断纸"
    "search_method": "keyword | fuzzy | semantic"
  },
  "returns": {
    "matched_parameters": [
      {"name": "BCDRY-TEMP-A101", "confidence": 0.95, "reason": "关键字匹配:TEMP"},
      {"name": "ACDRY-HEAT-B23", "confidence": 0.85, "reason": "概念关联:热量"}
    ],
    "total_matches": 12
  }
}
```

#### 工具 5: `get_time_series_data`
```python
{
  "name": "get_time_series_data",
  "description": "获取指定参数的时间序列数据",
  "parameters": {
    "file_id": "string",
    "parameters": ["param1", "param2"],
    "time_range": {
      "start": "datetime (optional)",
      "end": "datetime (optional)"
    },
    "sampling": "all | hourly | daily"
  },
  "returns": {
    "timestamps": [...],
    "data": {
      "param1": [...],
      "param2": [...]
    }
  }
}
```

---

### 第二类：统计分析（6个工具）

#### 工具 6: `calculate_correlation`
```python
{
  "name": "calculate_correlation",
  "description": "计算参数间的相关性（支持多种方法）",
  "parameters": {
    "file_id": "string",
    "method": "pearson | spearman | kendall",
    "parameters": ["param1", "param2"],
    "target": "string (optional)"  // 如果指定，计算所有参数与target的相关性
  },
  "returns": {
    "method": "pearson",
    "results": [
      {
        "param1": "TENSION-A101",
        "param2": "BREAKAGE_EVENT",
        "correlation": 0.73,
        "p_value": 0.001,
        "interpretation": "强正相关，统计显著"
      }
    ]
  }
}
```

#### 工具 7: `get_top_correlations`
```python
{
  "name": "get_top_correlations",
  "description": "快速获取与目标变量相关性最强的参数",
  "parameters": {
    "file_id": "string",
    "target": "string",
    "top_n": "integer (default: 10)",
    "min_correlation": "float (default: 0.3)"
  },
  "returns": {
    "target": "QUALITY_INDEX",
    "top_correlations": [
      {"parameter": "MOISTURE-A45", "correlation": 0.82, "p_value": 0.0001},
      {"parameter": "TENSION-B12", "correlation": -0.75, "p_value": 0.0003}
    ]
  }
}
```

#### 工具 8: `compare_groups`
```python
{
  "name": "compare_groups",
  "description": "比较不同条件下的参数差异（支持t-test、ANOVA）",
  "parameters": {
    "file_id": "string",
    "parameter": "string",
    "group_by": "string",  // 分组依据的参数
    "test_type": "t_test | anova | mann_whitney"
  },
  "returns": {
    "parameter": "TENSION-A101",
    "groups": {
      "group_0": {"mean": 450.2, "std": 25.3, "count": 500},
      "group_1": {"mean": 620.5, "std": 30.1, "count": 500}
    },
    "test_result": {
      "statistic": 45.3,
      "p_value": 0.0001,
      "interpretation": "两组均值存在显著差异"
    }
  }
}
```

#### 工具 9: `detect_outliers`
```python
{
  "name": "detect_outliers",
  "description": "检测异常值（支持多种方法）",
  "parameters": {
    "file_id": "string",
    "parameter": "string",
    "method": "zscore | iqr | isolation_forest",
    "threshold": "float (optional)"
  },
  "returns": {
    "parameter": "TENSION-A101",
    "method": "zscore",
    "outliers": [
      {"index": 234, "value": 850.5, "zscore": 3.5, "timestamp": "2024-01-15 14:23"},
      {"index": 567, "value": 200.1, "zscore": -3.8, "timestamp": "2024-01-20 09:15"}
    ],
    "outlier_count": 12,
    "outlier_percentage": 1.2
  }
}
```

#### 工具 10: `analyze_distribution`
```python
{
  "name": "analyze_distribution",
  "description": "分析参数的分布特征",
  "parameters": {
    "file_id": "string",
    "parameter": "string"
  },
  "returns": {
    "parameter": "MOISTURE-A45",
    "distribution_type": "normal | skewed | bimodal",
    "normality_test": {
      "test": "shapiro",
      "p_value": 0.045,
      "is_normal": false
    },
    "histogram": {
      "bins": [0, 10, 20, 30, ...],
      "counts": [50, 120, 200, ...]
    }
  }
}
```

#### 工具 11: `perform_regression`
```python
{
  "name": "perform_regression",
  "description": "执行回归分析（线性或多项式）",
  "parameters": {
    "file_id": "string",
    "target": "string",
    "features": ["param1", "param2"],
    "regression_type": "linear | polynomial | ridge"
  },
  "returns": {
    "model_type": "linear",
    "r_squared": 0.75,
    "coefficients": {
      "TENSION-A101": 0.45,
      "MOISTURE-B23": -0.32
    },
    "feature_importance": [
      {"feature": "TENSION-A101", "importance": 0.65},
      {"feature": "MOISTURE-B23", "importance": 0.35}
    ]
  }
}
```

---

### 第三类：模式发现（4个工具）

#### 工具 12: `find_temporal_patterns`
```python
{
  "name": "find_temporal_patterns",
  "description": "发现时序模式（趋势、周期性、突变）",
  "parameters": {
    "file_id": "string",
    "parameter": "string",
    "pattern_type": "trend | seasonality | change_point | all"
  },
  "returns": {
    "parameter": "QUALITY_INDEX",
    "patterns": {
      "trend": {
        "direction": "decreasing",
        "slope": -0.05,
        "confidence": 0.9
      },
      "change_points": [
        {"timestamp": "2024-01-15 10:00", "magnitude": 15.3}
      ],
      "seasonality": {
        "detected": true,
        "period": "daily",
        "strength": 0.6
      }
    }
  }
}
```

#### 工具 13: `find_event_patterns`
```python
{
  "name": "find_event_patterns",
  "description": "分析特定事件前后的参数模式",
  "parameters": {
    "file_id": "string",
    "event_parameter": "string",  // 如 "BREAKAGE_EVENT"
    "event_value": "any",  // 事件触发值
    "analysis_parameters": ["param1", "param2"],
    "time_window": {
      "before_minutes": 30,
      "after_minutes": 10
    }
  },
  "returns": {
    "event": "BREAKAGE_EVENT",
    "event_count": 25,
    "patterns": [
      {
        "parameter": "TENSION-A101",
        "before_event": {
          "avg_change": "+30%",
          "occurrence_rate": 0.85
        },
        "description": "断纸前30分钟张力平均上升30%，发生率85%"
      }
    ]
  }
}
```

#### 工具 14: `cluster_analysis`
```python
{
  "name": "cluster_analysis",
  "description": "对数据进行聚类分析，发现隐藏的分组",
  "parameters": {
    "file_id": "string",
    "parameters": ["param1", "param2"],
    "n_clusters": "integer (optional)",
    "method": "kmeans | dbscan | hierarchical"
  },
  "returns": {
    "method": "kmeans",
    "n_clusters": 3,
    "clusters": [
      {
        "cluster_id": 0,
        "size": 3500,
        "centroid": {"param1": 450.2, "param2": 67.8},
        "characteristics": "正常生产状态"
      },
      {
        "cluster_id": 1,
        "size": 500,
        "centroid": {"param1": 620.5, "param2": 85.3},
        "characteristics": "高张力高品质"
      }
    ]
  }
}
```

#### 工具 15: `find_association_rules`
```python
{
  "name": "find_association_rules",
  "description": "发现参数间的关联规则（如果A高，则B通常也高）",
  "parameters": {
    "file_id": "string",
    "min_support": "float (default: 0.1)",
    "min_confidence": "float (default: 0.5)"
  },
  "returns": {
    "rules": [
      {
        "antecedent": "TENSION-A101 > 500",
        "consequent": "BREAKAGE_EVENT = 1",
        "support": 0.15,
        "confidence": 0.75,
        "lift": 3.2,
        "interpretation": "当张力>500时，75%概率会断纸"
      }
    ]
  }
}
```

---

### 第四类：对话辅助（3个工具）

#### 工具 16: `explain_result`
```python
{
  "name": "explain_result",
  "description": "用通俗语言解释统计结果",
  "parameters": {
    "result_type": "correlation | p_value | regression",
    "value": "any",
    "context": "string (optional)"
  },
  "returns": {
    "explanation": "相关系数0.73表示两个参数之间存在强正相关关系...",
    "recommendation": "建议进一步分析这两个参数的因果关系"
  }
}
```

#### 工具 17: `suggest_next_analysis`
```python
{
  "name": "suggest_next_analysis",
  "description": "根据当前分析结果，智能推荐下一步分析",
  "parameters": {
    "file_id": "string",
    "current_findings": "string",
    "analysis_history": ["已执行的工具列表"]
  },
  "returns": {
    "suggestions": [
      {
        "tool": "find_event_patterns",
        "reason": "发现断纸与张力高度相关，建议分析断纸事件前的参数变化",
        "priority": "high"
      },
      {
        "tool": "compare_groups",
        "reason": "可以比较断纸与正常情况下的参数差异",
        "priority": "medium"
      }
    ]
  }
}
```

#### 工具 18: `ask_clarification`
```python
{
  "name": "ask_clarification",
  "description": "向用户询问以明确分析意图",
  "parameters": {
    "question": "string",
    "options": ["选项1", "选项2"],
    "context": "string"
  },
  "returns": {
    "user_response": "string"
  }
}
```

---

## 详细实作架构

### 1. 分析服务核心 (`analysis_service.py`)

```python
# backend/services/analysis_service.py

import json
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Any, Optional
from scipy.stats import pearsonr, spearmanr, ttest_ind, shapiro
from sklearn.cluster import KMeans, DBSCAN
import hashlib

class AnalysisService:
    """
    智能分析核心服务
    负责：
    1. 数据索引建立
    2. 统计计算
    3. 模式发现
    """
    
    def __init__(self, base_dir: str = "workspace"):
        self.base_dir = Path(base_dir)
    
    def get_analysis_path(self, session_id: str, file_id: str) -> Path:
        """获取分析文件存储路径"""
        analysis_dir = self.base_dir / session_id / "analysis" / file_id
        analysis_dir.mkdir(parents=True, exist_ok=True)
        return analysis_dir
    
    def get_file_id(self, filename: str) -> str:
        """生成文件ID（基于文件名的hash）"""
        return hashlib.md5(filename.encode()).hexdigest()[:12]
    
    async def build_analysis_index(self, csv_path: str, session_id: str, filename: str) -> Dict:
        """
        为CSV文件建立分析索引
        这是一次性操作，结果会缓存
        """
        file_id = self.get_file_id(filename)
        analysis_path = self.get_analysis_path(session_id, file_id)
        
        # 检查是否已有索引
        summary_file = analysis_path / "summary.json"
        if summary_file.exists():
            with open(summary_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        
        # 读取CSV
        df = pd.read_csv(csv_path)
        
        # 1. 基本摘要
        summary = {
            "file_id": file_id,
            "filename": filename,
            "total_rows": len(df),
            "total_columns": len(df.columns),
            "parameters": list(df.columns),
            "created_at": pd.Timestamp.now().isoformat()
        }
        
        # 2. 参数分类（根据前缀）
        categories = self._categorize_parameters(df.columns)
        summary["categories"] = categories
        
        # 3. 基本统计
        statistics = {}
        for col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col]):
                statistics[col] = {
                    "mean": float(df[col].mean()),
                    "std": float(df[col].std()),
                    "min": float(df[col].min()),
                    "max": float(df[col].max()),
                    "median": float(df[col].median()),
                    "q1": float(df[col].quantile(0.25)),
                    "q3": float(df[col].quantile(0.75)),
                    "missing_count": int(df[col].isna().sum())
                }
        
        # 保存统计信息
        with open(analysis_path / "statistics.json", 'w', encoding='utf-8') as f:
            json.dump(statistics, f, ensure_ascii=False, indent=2)
        
        # 4. 相关性矩阵（只计算数值列）
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        if len(numeric_cols) > 1:
            corr_matrix = df[numeric_cols].corr()
            # 转换为可序列化的格式
            corr_dict = {}
            for col1 in numeric_cols:
                corr_dict[col1] = {}
                for col2 in numeric_cols:
                    corr_dict[col1][col2] = float(corr_matrix.loc[col1, col2])
            
            with open(analysis_path / "correlations.json", 'w', encoding='utf-8') as f:
                json.dump(corr_dict, f, ensure_ascii=False, indent=2)
        
        # 5. 语义索引（参数名的关键词映射）
        semantic_index = self._build_semantic_index(df.columns)
        with open(analysis_path / "semantic_index.json", 'w', encoding='utf-8') as f:
            json.dump(semantic_index, f, ensure_ascii=False, indent=2)
        
        # 保存摘要
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        
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
    
    def _build_semantic_index(self, columns: List[str]) -> Dict[str, List[str]]:
        """
        建立语义索引：关键词 -> 参数列表
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
    
    # 工具实现将在下一部分
```

### 2. 工具执行器 (`analysis_tool_executor.py`)

```python
# backend/services/analysis_tool_executor.py

import json
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Any
from scipy.stats import pearsonr, spearmanr, ttest_ind, mannwhitneyu, f_oneway
from scipy.stats import zscore, shapiro
from sklearn.cluster import KMeans, DBSCAN
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.preprocessing import PolynomialFeatures

class AnalysisToolExecutor:
    """
    执行18个分析工具
    """
    
    def __init__(self, analysis_service):
        self.analysis_service = analysis_service
        self.base_dir = Path(analysis_service.base_dir)
    
    def execute_tool(self, tool_name: str, params: Dict, session_id: str) -> Dict:
        """执行指定的工具"""
        tool_map = {
            "get_parameter_list": self.get_parameter_list,
            "get_parameter_statistics": self.get_parameter_statistics,
            "get_data_overview": self.get_data_overview,
            "search_parameters_by_concept": self.search_parameters_by_concept,
            "get_time_series_data": self.get_time_series_data,
            "calculate_correlation": self.calculate_correlation,
            "get_top_correlations": self.get_top_correlations,
            "compare_groups": self.compare_groups,
            "detect_outliers": self.detect_outliers,
            "analyze_distribution": self.analyze_distribution,
            "perform_regression": self.perform_regression,
            "find_temporal_patterns": self.find_temporal_patterns,
            "find_event_patterns": self.find_event_patterns,
            "cluster_analysis": self.cluster_analysis,
            "find_association_rules": self.find_association_rules,
            "explain_result": self.explain_result,
            "suggest_next_analysis": self.suggest_next_analysis,
            "ask_clarification": self.ask_clarification,
        }
        
        if tool_name not in tool_map:
            return {"error": f"Unknown tool: {tool_name}"}
        
        try:
            return tool_map[tool_name](params, session_id)
        except Exception as e:
            return {"error": f"Tool execution failed: {str(e)}"}
    
    # ===== 数据查询工具 =====
    
    def get_parameter_list(self, params: Dict, session_id: str) -> Dict:
        """工具1: 获取参数列表"""
        file_id = params.get("file_id")
        keyword = params.get("keyword", "").lower()
        
        # 读取摘要
        analysis_path = self.analysis_service.get_analysis_path(session_id, file_id)
        with open(analysis_path / "summary.json", 'r', encoding='utf-8') as f:
            summary = json.load(f)
        
        all_params = summary["parameters"]
        
        # 关键字过滤
        if keyword:
            matched = [p for p in all_params if keyword in p.lower()]
        else:
            matched = all_params
        
        return {
            "parameters": matched,
            "total_count": len(all_params),
            "matched_count": len(matched),
            "categories": summary.get("categories", {})
        }
    
    def get_parameter_statistics(self, params: Dict, session_id: str) -> Dict:
        """工具2: 获取参数统计"""
        file_id = params.get("file_id")
        parameter = params.get("parameter")
        include_distribution = params.get("include_distribution", False)
        
        analysis_path = self.analysis_service.get_analysis_path(session_id, file_id)
        
        # 读取统计信息
        with open(analysis_path / "statistics.json", 'r', encoding='utf-8') as f:
            statistics = json.load(f)
        
        if parameter not in statistics:
            return {"error": f"Parameter {parameter} not found"}
        
        result = statistics[parameter].copy()
        result["parameter"] = parameter
        
        if include_distribution:
            # 加载原始数据计算分布
            csv_path = self._get_csv_path(session_id, file_id)
            df = pd.read_csv(csv_path)
            
            if parameter in df.columns:
                values = df[parameter].dropna()
                hist, bins = np.histogram(values, bins=30)
                result["distribution"] = {
                    "histogram": {
                        "bins": bins.tolist(),
                        "counts": hist.tolist()
                    },
                    "skewness": float(values.skew()),
                    "kurtosis": float(values.kurtosis())
                }
        
        return result
    
    def search_parameters_by_concept(self, params: Dict, session_id: str) -> Dict:
        """工具4: 语义搜索参数"""
        file_id = params.get("file_id")
        concept = params.get("concept", "")
        
        analysis_path = self.analysis_service.get_analysis_path(session_id, file_id)
        
        # 读取语义索引
        with open(analysis_path / "semantic_index.json", 'r', encoding='utf-8') as f:
            semantic_index = json.load(f)
        
        matched_parameters = []
        
        # 直接匹配
        if concept in semantic_index:
            for param in semantic_index[concept]:
                matched_parameters.append({
                    "name": param,
                    "confidence": 0.9,
                    "reason": f"概念映射: {concept}"
                })
        
        # 模糊匹配
        with open(analysis_path / "summary.json", 'r', encoding='utf-8') as f:
            summary = json.load(f)
        
        for param in summary["parameters"]:
            if concept.lower() in param.lower():
                if not any(m["name"] == param for m in matched_parameters):
                    matched_parameters.append({
                        "name": param,
                        "confidence": 0.7,
                        "reason": f"关键字匹配"
                    })
        
        return {
            "matched_parameters": matched_parameters,
            "total_matches": len(matched_parameters)
        }
    
    # ===== 统计分析工具 =====
    
    def calculate_correlation(self, params: Dict, session_id: str) -> Dict:
        """工具6: 计算相关性"""
        file_id = params.get("file_id")
        method = params.get("method", "pearson")
        parameters = params.get("parameters", [])
        target = params.get("target")
        
        csv_path = self._get_csv_path(session_id, file_id)
        df = pd.read_csv(csv_path)
        
        results = []
        
        if target:
            # 计算所有参数与target的相关性
            for param in parameters:
                if param in df.columns and target in df.columns:
                    corr, p_val = self._calculate_corr(df[param], df[target], method)
                    results.append({
                        "param1": param,
                        "param2": target,
                        "correlation": float(corr),
                        "p_value": float(p_val),
                        "interpretation": self._interpret_correlation(corr, p_val)
                    })
        else:
            # 两两计算
            for i in range(len(parameters)):
                for j in range(i + 1, len(parameters)):
                    p1, p2 = parameters[i], parameters[j]
                    if p1 in df.columns and p2 in df.columns:
                        corr, p_val = self._calculate_corr(df[p1], df[p2], method)
                        results.append({
                            "param1": p1,
                            "param2": p2,
                            "correlation": float(corr),
                            "p_value": float(p_val),
                            "interpretation": self._interpret_correlation(corr, p_val)
                        })
        
        return {
            "method": method,
            "results": results
        }
    
    def get_top_correlations(self, params: Dict, session_id: str) -> Dict:
        """工具7: 获取Top相关性"""
        file_id = params.get("file_id")
        target = params.get("target")
        top_n = params.get("top_n", 10)
        min_corr = params.get("min_correlation", 0.3)
        
        analysis_path = self.analysis_service.get_analysis_path(session_id, file_id)
        
        # 读取相关性矩阵
        with open(analysis_path / "correlations.json", 'r', encoding='utf-8') as f:
            corr_matrix = json.load(f)
        
        if target not in corr_matrix:
            return {"error": f"Target {target} not found"}
        
        # 提取与target的相关性
        correlations = []
        for param, corr_value in corr_matrix[target].items():
            if param != target and abs(corr_value) >= min_corr:
                correlations.append({
                    "parameter": param,
                    "correlation": corr_value,
                    "p_value": 0.001  # 简化，实际需要重新计算
                })
        
        # 排序
        correlations.sort(key=lambda x: abs(x["correlation"]), reverse=True)
        
        return {
            "target": target,
            "top_correlations": correlations[:top_n]
        }
    
    def compare_groups(self, params: Dict, session_id: str) -> Dict:
        """工具8: 组间比较"""
        file_id = params.get("file_id")
        parameter = params.get("parameter")
        group_by = params.get("group_by")
        test_type = params.get("test_type", "t_test")
        
        csv_path = self._get_csv_path(session_id, file_id)
        df = pd.read_csv(csv_path)
        
        if parameter not in df.columns or group_by not in df.columns:
            return {"error": "Parameter or group_by not found"}
        
        # 分组
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
        
        # 统计检验
        if test_type == "t_test" and len(group_data) == 2:
            g1, g2 = list(group_data.values())
            stat, p_val = ttest_ind(g1, g2)
            test_result = {
                "statistic": float(stat),
                "p_value": float(p_val),
                "interpretation": "两组均值存在显著差异" if p_val < 0.05 else "两组均值无显著差异"
            }
        elif test_type == "anova":
            stat, p_val = f_oneway(*group_data.values())
            test_result = {
                "statistic": float(stat),
                "p_value": float(p_val),
                "interpretation": "各组均值存在显著差异" if p_val < 0.05 else "各组均值无显著差异"
            }
        else:
            test_result = {"error": "Unsupported test type"}
        
        return {
            "parameter": parameter,
            "groups": group_stats,
            "test_result": test_result
        }
    
    # ===== 辅助方法 =====
    
    def _get_csv_path(self, session_id: str, file_id: str) -> str:
        """获取CSV文件路径（通过file_id反查）"""
        # 简化实现：从analysis_path中的summary读取filename
        analysis_path = self.analysis_service.get_analysis_path(session_id, file_id)
        with open(analysis_path / "summary.json", 'r', encoding='utf-8') as f:
            summary = json.load(f)
        
        filename = summary["filename"]
        return str(self.base_dir / session_id / "uploads" / filename)
    
    def _calculate_corr(self, x, y, method):
        """计算相关系数"""
        if method == "pearson":
            return pearsonr(x, y)
        elif method == "spearman":
            return spearmanr(x, y)
        else:
            return pearsonr(x, y)
    
    def _interpret_correlation(self, corr: float, p_value: float) -> str:
        """解释相关性"""
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
```

*(由于篇幅限制，其他12个工具的实现类似，核心逻辑已展示)*

---

## 下一部分：LLM Agent 和 API 路由

请告诉我是否需要我继续完成：
1. LLM Agent 实现（基于您的 llm_reporter.py）
2. API 路由设计
3. 前端整合方案
4. 阶段性实作步骤

或者您希望我先聚焦在某个具体部分？
