# 05. 分阶段实作步骤

> 基于模块化架构的详细实作指南，预计 7-10 个工作日

---

## 实作总览

```
階段一: 後端核心 (5-6天)
  ├─ Day 1-2: 基礎服務 + 查詢工具（5個）
  ├─ Day 3-4: 統計工具（6個）+ LlamaIndex Agent 遷移
  ├─ Day 5: 模式工具（4個）+ 輔助工具（3個）
  └─ Day 6: API 層 + 工具執行器

阶段二: 前端 (2天)
  ├─ Day 7: UI 基础
  └─ Day 8: 交互完善

阶段三: 测试部署 (2天)
  ├─ Day 9: 集成测试 + 优化
  └─ Day 10: 部署与文档

总计: 9-10 个工作日完成全部18个工具
```

---

## 阶段一：后端核心 (Day 1-4)

### Day 1-2: 基础服务 + 全部查询工具 (5个)

#### 1.1 创建目录结构

```bash
cd C:\Users\foresight\Desktop\MantleTemp\pythaon\Sigma2

# 创建目录
mkdir backend\services\analysis
mkdir backend\services\analysis\tools

# 创建空文件
New-Item backend\services\analysis\__init__.py
New-Item backend\services\analysis\analysis_service.py
New-Item backend\services\analysis\tools\__init__.py
New-Item backend\services\analysis\tools\base.py
```

#### 1.2 实现工具基类 (~50行)

**文件**: `backend/services/analysis/tools/base.py`

参考 `02_backend_modules.md` 中的完整代码

✅ **检查点**:
```python
from backend.services.analysis.tools.base import AnalysisTool
# 成功导入即可
```

#### 1.3 实现核心索引服务 (~350行)

**文件**: `backend/services/analysis/analysis_service.py`

**关键方法**:
- `build_analysis_index()` - CSV 索引建立
- `_categorize_parameters()` - 参数分类
- `_calculate_statistics()` - 统计计算
- `_calculate_correlations()` - 相关性矩阵
- `_build_semantic_index()` - 语义索引

✅ **测试**:
```python
# 测试脚本
from backend.services.analysis import AnalysisService

service = AnalysisService()
result = await service.build_analysis_index(
    csv_path="workspace/default/uploads/test.csv",
    session_id="default",
    filename="test.csv"
)
print(result)  # 应输出摘要信息
```

#### 1.4 实现全部5个查询工具 (~200行)

**文件**: `backend/services/analysis/tools/data_query.py`

**全部实现**:
1. `GetParameterListTool` (~40行) - 参数列表
2. `GetParameterStatisticsTool` (~40行) - 参数统计
3. `SearchParametersByConceptTool` (~60行) - 概念搜索
4. `GetDataOverviewTool` (~30行) - 数据总览
5. `GetTimeSeriesDataTool` (~30行) - 时序数据

✅ **测试**:
```python
from backend.services.analysis import AnalysisService
from backend.services.analysis.tools.data_query import *

service = AnalysisService()

# 测试每个工具
tools = [
    GetParameterListTool(service),
    GetParameterStatisticsTool(service),
    SearchParametersByConceptTool(service),
    GetDataOverviewTool(service),
    GetTimeSeriesDataTool(service)
]

for tool in tools:
    print(f"Testing {tool.name}...")
    # 测试逻辑
```

---

### Day 3-4: 全部统计工具 (6个) + Agent

#### 3.1 实现全部统计工具 (~250行)

**文件**: `backend/services/analysis/tools/statistics.py`

**全部6个工具**:
1. `CalculateCorrelationTool` (~80行) - 计算相关性
2. `GetTopCorrelationsTool` (~60行) - Top相关性
3. `CompareGroupsTool` (~80行) - 组间比较
4. `DetectOutliersTool` (~60行) - 异常检测
5. `AnalyzeDistributionTool` (~50行) - 分布分析
6. `PerformRegressionTool` (~70行) - 回归分析

#### 3.2 實現 LlamaIndex Agent (~300行)

**文件**: `backend/services/analysis/agent.py`

**安裝依賴**:
```bash
pip install llama-index-core llama-index-llms-ollama llama-index-embeddings-ollama
```

**核心方法**:
- `__init__()` - 初始化 Ollama 與 ReAct Agent
- `_wrap_tools()` - 將原生工具封裝為 FunctionTool
- `analyze()` - 呼叫 LlamaIndex `achat` 進行推理

✅ **測試**:
```python
from backend.services.analysis import AnalysisService, LLMAnalysisAgent
from backend.services.analysis.tools import ToolExecutor

service = AnalysisService()
executor = ToolExecutor(service)
agent = LLMAnalysisAgent(executor)

result = await agent.analyze(
    session_id='default',
    file_id='abc123',
    user_question='有哪些溫度參數？'
)
print(result['response'])
```

---

### Day 5: 模式工具 (4个) + 辅助工具 (3个)

#### 5.1 实现模式发现工具 (~200行)

**文件**: `backend/services/analysis/tools/patterns.py`

**全部4个工具**:
1. `FindTemporalPatternsTool` (~60行) - 时序模式
2. `FindEventPatternsTool` (~70行) - 事件模式
3. `ClusterAnalysisTool` (~40行) - 聚类分析
4. `FindAssociationRulesTool` (~30行) - 关联规则

#### 5.2 实现对话辅助工具 (~100行)

**文件**: `backend/services/analysis/tools/helpers.py`

**全部3个工具**:
1. `ExplainResultTool` (~40行) - 结果解释
2. `SuggestNextAnalysisTool` (~30行) - 推荐分析
3. `AskClarificationTool` (~30行) - 询问澄清

---

### Day 6: 工具执行器 + API 层

#### 6.1 实现完整工具执行器 (~100行)

**文件**: `backend/services/analysis/tools/executor.py`

```python
class ToolExecutor:
    def __init__(self, analysis_service):
        self.analysis_service = analysis_service
        self.tools = self._register_tools()
    
    def _register_tools(self):
        """注册全部18个工具"""
        from .data_query import (
            GetParameterListTool, GetParameterStatisticsTool,
            SearchParametersByConceptTool, GetDataOverviewTool,
            GetTimeSeriesDataTool
        )
        from .statistics import (
            CalculateCorrelationTool, GetTopCorrelationsTool,
            CompareGroupsTool, DetectOutliersTool,
            AnalyzeDistributionTool, PerformRegressionTool
        )
        from .patterns import (
            FindTemporalPatternsTool, FindEventPatternsTool,
            ClusterAnalysisTool, FindAssociationRulesTool
        )
        from .helpers import (
            ExplainResultTool, SuggestNextAnalysisTool,
            AskClarificationTool
        )
        
        return {
            # 查询工具 (5个)
            'get_parameter_list': GetParameterListTool(self.analysis_service),
            'get_parameter_statistics': GetParameterStatisticsTool(self.analysis_service),
            'search_parameters_by_concept': SearchParametersByConceptTool(self.analysis_service),
            'get_data_overview': GetDataOverviewTool(self.analysis_service),
            'get_time_series_data': GetTimeSeriesDataTool(self.analysis_service),
            
            # 统计工具 (6个)
            'calculate_correlation': CalculateCorrelationTool(self.analysis_service),
            'get_top_correlations': GetTopCorrelationsTool(self.analysis_service),
            'compare_groups': CompareGroupsTool(self.analysis_service),
            'detect_outliers': DetectOutliersTool(self.analysis_service),
            'analyze_distribution': AnalyzeDistributionTool(self.analysis_service),
            'perform_regression': PerformRegressionTool(self.analysis_service),
            
            # 模式工具 (4个)
            'find_temporal_patterns': FindTemporalPatternsTool(self.analysis_service),
            'find_event_patterns': FindEventPatternsTool(self.analysis_service),
            'cluster_analysis': ClusterAnalysisTool(self.analysis_service),
            'find_association_rules': FindAssociationRulesTool(self.analysis_service),
            
            # 辅助工具 (3个)
            'explain_result': ExplainResultTool(self.analysis_service),
            'suggest_next_analysis': SuggestNextAnalysisTool(self.analysis_service),
            'ask_clarification': AskClarificationTool(self.analysis_service),
        }
    
    def execute_tool(self, tool_name, params, session_id):
        tool = self.tools.get(tool_name)
        if not tool:
            return {"error": f"Tool not found: {tool_name}"}
        return tool.execute(params, session_id)
    
    def list_tools(self):
        """返回所有工具信息"""
        return [
            {
                "name": name,
                "description": tool.description,
                "required_params": tool.required_params
            }
            for name, tool in self.tools.items()
        ]
```

#### 6.2 实现 API 路由 (~200行)

**文件**: `backend/routers/analysis_router.py`

参考 `his/part3_api_router_design.md`

**端点**:
- `POST /api/analysis/prepare`
- `POST /api/analysis/chat`
- `GET /api/analysis/files`
- `GET /api/analysis/summary/{file_id}`
- `DELETE /api/analysis/clear-session`
- `GET /api/analysis/tools`

#### 4.2 更新依赖注入

**文件**: `backend/dependencies.py`

```python
# 新增
from backend.services.analysis import AnalysisService, LLMAnalysisAgent
from backend.services.analysis.tools import ToolExecutor

_analysis_service = None
_tool_executor = None
_llm_agent = None

def get_analysis_service():
    global _analysis_service
    if _analysis_service is None:
        _analysis_service = AnalysisService()
    return _analysis_service

def get_tool_executor():
    global _tool_executor
    if _tool_executor is None:
        _tool_executor = ToolExecutor(get_analysis_service())
    return _tool_executor

def get_llm_agent():
    global _llm_agent
    if _llm_agent is None:
        _llm_agent = LLMAnalysisAgent(get_tool_executor())
    return _llm_agent
```

#### 4.3 注册路由

**文件**: `api_entry.py`

```python
from backend.routers import analysis_router
app.include_router(analysis_router.router)
```

✅ **测试 API**:
```bash
# 启动服务器
python api_entry.py

# 测试端点
curl http://localhost:8001/api/analysis/tools
```

---

## 阶段二：前端 (Day 7-8)

### Day 7: UI 基础

#### 5.1 修改 dashboard.html

参考 `his/part4_frontend_integration.md`

**新增内容**:
1. 智能分析 section HTML (~150行)
2. CSS 样式 (~250行)
3. 导航整合 (~20行)

#### 5.2 创建 JavaScript 文件

**文件**: `static/js/intelligent_analysis.js` (~450行)

**主要类和方法**:
```javascript
class IntelligentAnalysis {
    constructor()
    async loadFiles()
    onFileSelect(fileId)
    async prepareFile()
    async sendMessage()
    addMessage(role, content, metadata)
    clearChat()
}
```

---

### Day 8: 交互完善

#### 8.1 完善对话功能
- 消息渲染优化
- Loading 状态
- 错误处理

#### 8.2 添加快捷操作
- 快捷按钮
- 工具列表展示

✅ **端到端测试**:
1. 打开浏览器访问 Dashboard
2. 切换到"智能分析"页面
3. 选择文件 -> 准备索引 -> 提问 -> 查看回答

---

## 阶段三：测试与部署 (Day 9-10)

### Day 9: 集成测试与优化

#### 7.1 功能测试场景

**场景 1: 参数查询**
```
用户: "有哪些参数？"
预期: 列出所有参数
验证: 参数数量正确
```

**场景 2: 概念搜索**
```
用户: "温度相关的参数有哪些？"
预期: 调用 search_parameters_by_concept
验证: 返回 TEMP, HEAT 相关参数
```

**场景 3: 相关性分析**
```
用户: "分析相关性"
预期: 调用 calculate_correlation
验证: 返回相关系数和 p 值
```

#### 7.2 性能测试

| 测试项 | 目标 | 实际 | 状态 |
|--------|------|------|------|
| 索引建立 (10MB) | < 30秒 | | |
| 查询响应 | < 5秒 | | |
| 对话响应 | < 20秒 | | |

---

### Day 10: 部署与文档

#### 10.1 部署检查清单

- [ ] 所有依赖已安装
- [ ] 配置文件正确（LLM_API_URL）
- [ ] 数据目录权限正确
- [ ] Ollama 服务正常运行
- [ ] 全部18个工具已注册

#### 10.2 用户文档

创建简单的用户手册：
1. 如何上传文件
2. 如何准备索引
3. 18个工具的使用示例
4. 常见问题FAQ
5. 故障排除

---

## 验收标准

### 功能完整性

- [ ] 文件上传与索引建立
- [ ] **全部18个工具**可用并测试通过
- [ ] 智能对话正常
- [ ] 用户隔离正确
- [ ] 错误处理友好

### 性能要求

- [ ] 索引建立时间符合预期
- [ ] 对话响应及时
- [ ] 无明显卡顿
- [ ] 支持并发访问

### 代码质量

- [ ] 单文件不超过 350 行 ✅
- [ ] 有完整注释
- [ ] 符合 Python 规范
- [ ] 模块化清晰

---

## 故障排除

### 常见问题

**问题 1**: 索引建立失败
```
解决: 检查 CSV 格式，确保是 UTF-8 编码
```

**问题 2**: LLM 连接失败
```
检查: config.LLM_API_URL 是否正确
测试: curl http://10.10.20.214:11434/api/chat
```

**问题 3**: 用户看不到文件
```
检查: session_id 是否一致
确认: workspace/{session_id}/uploads/ 目录存在
验证: 调用 /api/analysis/files 查看返回结果
```

**问题 4**: 某个工具调用失败
```
检查: 工具是否在 executor.py 中正确注册
验证: 查看后端日志，定位具体错误
测试: 单独测试该工具的 execute 方法
```

---

## 总结

遵循此步骤，可在 **9-10 个工作日**内完成：
- ✅ **完整功能版本** (全部18个工具)
- ✅ 完整的前后端整合
- ✅ 全面测试和部署
- ✅ 用户文档和培训

### 时间分配

| 阶段 | 工作日 | 产出 |
|------|--------|------|
| 后端开发 | 6天 | 全部18个工具 + Agent + API |
| 前端开发 | 2天 | 完整UI |
| 测试部署 | 2天 | 集成测试 + 文档 |
| **总计** | **9-10天** | **完整可用系统** |

---

## 阶段四：功能增強與優化 (Current)

### 4.1 術語對應綁定 (File-Specific Mapping)
- **需求**：不同檔案可能有相同的參數代碼 (如 A1)，需支援針對特定檔案綁定術語表。
- **後端**：
    - `POST /api/files/upload` 新增 `file_id` 參數。
    - `FileService` 支援將對應表存入 `analysis/{file_id}/mapping.csv`。
    - `AnalysisService` 優先讀取綁定的對應表，其次才是全域對應表。
- **前端**：
    - 上傳對應表時，若有選中檔案，自動帶入 `file_id` 進行綁定。

### 4.2 列表狀態優化
- **需求**：使用者需知道哪些檔案已分析，且不應看到系統生成的對應表檔案。
- **後端**：
    - `GET /api/analysis/files` 回傳 `is_indexed` 狀態 (檢查 `summary.json`)。
    - 過濾掉檔名包含 `(參數對應表)_` 的檔案。
- **前端**：
    - 檔案列表顯示 `(已索引)` 標記。

### 4.3 圖表渲染修復
- **問題**：JSON 字串包含特殊字符導致 HTML 屬性截斷，圖表無法顯示。
- **修復**：前端改用 `encodeURIComponent` 傳遞圖表數據，並在渲染時 `decodeURIComponent`。

### 4.4 移除自動選擇
- **需求**：進入頁面不自動選擇第一個檔案，避免誤導用戶。
- **修改**：移除 `loadFileList` 中的自動選擇邏輯。
