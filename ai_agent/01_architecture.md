# 01. 详细架构设计

## 系统架构总览

```
┌─────────────────────────────────────────────────────┐
│                   前端层 (Frontend)                  │
│                                                      │
│  dashboard.html + intelligent_analysis.js            │
│  - 文件选择                                           │
│  - 对话界面                                           │
│  - 结果展示                                           │
└──────────────────────┬──────────────────────────────┘
                       │ HTTP/JSON
┌──────────────────────▼──────────────────────────────┐
│                 API 層 (Router)                      │
│                                                      │
│  analysis_router.py                                  │
│  - /prepare         (索引建立)                       │
│  - /chat/stream     (Workflow 驅動)                  │
│  - /stop_generation (中斷信號)                       │
└──────────────────────┬──────────────────────────────┘
                       │
        ┌──────────────┴──────────────┐
        │                             │
┌───────▼────────┐           ┌────────▼────────┐
│  Analysis      │           │ Analysis        │
│  Workflow      │           │ Service         │
│  (LlamaIndex)  │           │                 │
│  agent.py      │◄─────────►│ - 索引建立      │
│  - 事件驅動      │           │ - 數據摘要      │
│  - 狀態機管理    │           │ - 語義搜索      │
│  - 意圖分流      │           │ - 停止信號管理  │
└───────┬────────┘           └────────┬────────┘
        │                             │
        │    ┌────────────────────────┘
        │    │
┌───────▼────▼───────────────────────────────────────┐
│              Tool Executor (工具执行器)              │
│                                                      │
│  ┌──────────┬──────────┬──────────┬──────────┐     │
│  │ Query    │ Stats    │ Pattern  │ Helper   │     │
│  │ Tools    │ Tools    │ Tools    │ Tools    │     │
│  │ (5个)    │ (6个)    │ (4个)    │ (3个)    │     │
│  └──────────┴──────────┴──────────┴──────────┘     │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│                  数据层 (Storage)                     │
│                                                      │
│  workspace/{session_id}/                             │
│  ├── uploads/{filename}.csv     (原始数据)           │
│  └── analysis/{file_id}/        (索引与缓存)         │
│      ├── summary.json                                │
│      ├── statistics.json                             │
│      ├── correlations.json                           │
│      └── semantic_index.json                         │
└──────────────────────────────────────────────────────┘

外部依賴:
┌────────────────┐
│  Ollama API    │  http://localhost:11434/api/chat
│  (llama3)      │  透過 LlamaIndex LLM 套件連接
└────────────────┘
┌────────────────┐
│  LlamaIndex    │  核心 Agent 框架
│  Framework     │  提供 ReAct 運作邏輯
└────────────────┘
```

---

## 模块分层设计

### Layer 1: 数据处理层

**文件**: `analysis_service.py` (350行)

**职责**:
- CSV 文件解析与验证
- 数据索引建立（一次性）
- 统计信息预计算
- 统计信息预计算
- 语义索引构建
- 生成控制 (停止信號管理)

**核心方法**:
```python
class AnalysisService:
    async def build_analysis_index(csv_path, session_id, filename) -> Dict
    def get_analysis_path(session_id, file_id) -> Path
    def _categorize_parameters(columns) -> Dict
    def _build_semantic_index(columns) -> Dict
```

---

### Layer 2: 工具层

**目录**: `analysis/tools/` (6个文件，共930行)

#### 2.1 基类 (`base.py`, 50行)

```python
class AnalysisTool(ABC):
    """所有工具的抽象基类"""
    
    @property
    @abstractmethod
    def name(self) -> str: pass
    
    @property
    @abstractmethod
    def description(self) -> str: pass
    
    @abstractmethod
    def execute(self, params: Dict, session_id: str) -> Dict: pass
```

#### 2.2 查询工具 (`data_query.py`, 200行)

- GetParameterList
- GetParameterStatistics
- GetDataOverview
- SearchParametersByConcept
- GetTimeSeriesData

#### 2.3 统计工具 (`statistics.py`, 250行)

- CalculateCorrelation
- GetTopCorrelations
- CompareGroups
- DetectOutliers
- AnalyzeDistribution
- PerformRegression

#### 2.4 模式工具 (`patterns.py`, 200行)

- FindTemporalPatterns
- FindEventPatterns
- ClusterAnalysis
- FindAssociationRules

#### 2.5 辅助工具 (`helpers.py`, 100行)

- ExplainResult
- SuggestNextAnalysis
- AskClarification

#### 2.6 执行器 (`executor.py`, 100行)

```python
class ToolExecutor:
    """统一的工具执行入口"""
    
    def __init__(self, analysis_service):
        self.tools = self._register_tools()
    
    def execute_tool(self, tool_name: str, params: Dict, session_id: str) -> Dict:
        tool = self.tools.get(tool_name)
        if not tool:
            return {"error": f"Tool not found: {tool_name}"}
        return tool.execute(params, session_id)
```

---

### Layer 3: 智能層 (LlamaIndex Workflow)

**文件**: `agent.py` (改版為 Workflow 架構)

**職責**:
- 使用 LlamaIndex `Workflow` 框架實作狀態機。
- **事件驅動**: 透過 `Event` 傳遞數據，並具備對話記憶功能。
- **自主糾錯**: 當搜尋失敗時，自動進入語義擴展循環進行重試。
- **地端優先**: 運算百分之百在地端執行。

**核心邏輯 (核心工作站)**:
```python
class SigmaAnalysisWorkflow(Workflow):
    @step
    async def route_intent(self, ev: StartEvent) -> IntentEvent | ErrorEvent:
        # 使用 LLM 辨識意圖 (Analysis / Translation / Chat)
        ...

    @step
    async def execute_analysis(self, ev: AnalysisEvent) -> VisualizingEvent | ConceptExpansionEvent:
        # 地端工具執行。若搜尋結果為空，拋出 ConceptExpansionEvent
        ...

    @step
    async def visualize_data(self, ev: VisualizingEvent) -> SummarizeEvent:
        # 繪圖工作站：專責生成 Chart JSON
        ...

    @step
    async def expand_concept(self, ev: ConceptExpansionEvent) -> AnalysisEvent:
        # 語義擴展站：LLM 聯想專業術語並重試搜尋
        ...

    @step
    async def humanizer(self, ev: SummarizeEvent) -> StopEvent:
        # 結果總結站：專注於生成繁體中文分析報告
        ...
```

---

### Layer 4: API层

**文件**: `analysis_router.py` (200行)

**端点设计**:

| 端点 | 方法 | 用途 |
|------|------|------|
| `/api/analysis/prepare` | POST | 建立文件索引 |
| `/api/analysis/chat` | POST | 智能对话 |
| `/api/analysis/chat/stream` | POST | 串流对话 |
| `/api/analysis/stop_generation` | POST | 停止生成 |
| `/api/analysis/files` | GET | 文件列表 |
| `/api/analysis/summary/{file_id}` | GET | 文件摘要 |
| `/api/analysis/clear-session` | DELETE | 清除会话 |
| `/api/analysis/tools` | GET | 工具列表 |

---

## 数据流设计

### 流程 1: 文件准备

```
用户上传 CSV
    ↓
前端: 选择文件 → 点击"准备索引"
    ↓
API: POST /api/analysis/prepare
    ↓
AnalysisService.build_analysis_index()
    ├─ 读取 CSV
    ├─ 计算基本统计 → statistics.json
    ├─ 计算相关性矩阵 → correlations.json
    ├─ 构建语义索引 → semantic_index.json
    └─ 生成摘要 → summary.json
    ↓
返回: {file_id, summary}
```

### 流程 2: 智能對話與自主糾錯 (Self-Correction)

```
用戶提問: "有沒有斷紙相關參數？"
    │
意圖識別 (route_intent)
    → 識別為: 'analysis'
    │
地端工具執行 (execute_analysis)
    → 嘗試搜尋 "斷紙" → 失敗 (0結果)
    │
語義擴展工作站 (expand_concept) ──┐
    → LLM 聯想: "Paper Break", "WebBreak" 
    │                             │
    └─────────────────────────────┘ (自動重試搜尋)
    │
地端工具執行 (execute_analysis)
    → 搜尋 "Paper Break" → 成功！
    │
數據可視化 (visualize_data)
    → 專屬 Prompt 生成 Chart JSON
    │
結果總結 (humanizer)
    → 生成繁體中文報告 (Expert Summary)
    │
返回前端渲染
```

---

## 文件组织策略

### 按功能分组

```
tools/
├── data_query.py      ← 所有查询类工具
├── statistics.py      ← 所有统计类工具
├── patterns.py        ← 所有模式类工具
└── helpers.py         ← 所有辅助类工具
```

### 命名规范

**类名**: PascalCase + Tool 后缀
- `GetParameterListTool`
- `CalculateCorrelationTool`

**文件名**: snake_case
- `data_query.py`
- `analysis_service.py`

**方法名**: snake_case
- `execute()`
- `_identify_intent()`

---

## 扩展性设计

### 新增工具的步骤

1. 在对应分类文件中新增类（继承 `AnalysisTool`）
2. 实现 `name`, `description`, `execute` 方法
3. 在 `executor.py` 中注册
4. 在 `agent.py` 的意图识别中添加规则

**示例**:
```python
# tools/statistics.py

class NewStatTool(AnalysisTool):
    name = "new_stat_tool"
    description = "新统计工具"
    required_params = ['file_id']
    
    def execute(self, params, session_id):
        # 实现逻辑
        return {"result": "..."}
```

---

## 性能优化策略

### 1. 索引缓存
- 索引文件只生成一次
- 后续查询直接读取 JSON

### 2. 分页加载
- 参数列表分页
- 时序数据采样

### 3. 异步处理
- 索引建立可改为后台任务（Celery）
- 避免阻塞 API 响应

---

## 安全性考虑

### 1. 用户隔离
- 基于 `session_id` 的目录隔离
- 用户A看不到用户B的数据

### 2. 文件验证
- CSV 格式验证
- 文件大小限制（< 100MB）

### 3. SQL注入防护
- 使用 pandas，不直接拼接 SQL

---

## 下一步

阅读 **[02_backend_modules.md](./02_backend_modules.md)** 查看具体代码实现。
