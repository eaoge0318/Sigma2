# 智能分析功能 - 完整实作计划总览

## 📚 文档结构

本实作计划包含以下文档，位于：
`C:\Users\foresight\.gemini\antigravity\brain\4613f727-44b8-4d58-8782-d08bbd4c1c48\`

### 核心规划文档

1. **[README.md](./README.md)** (本文档)
   - 总览与快速导航

2. **[intelligent_analysis_implementation_plan.md](./intelligent_analysis_implementation_plan.md)** (Part 1)
   - 核心概念与架构设计
   - 18个分析工具的详细规格
   - `AnalysisService` 核心实现
   - `AnalysisToolExecutor` 部分实现

3. **[part2_llm_agent_implementation.md](./part2_llm_agent_implementation.md)**
   - LLM Agent 完整版实现
   - LLM Agent 简化版实现（推荐）
   - 意图识别与工具调用机制

4. **[part3_api_router_design.md](./part3_api_router_design.md)**
   - 6个 RESTful API 端点设计
   - 请求/响应模型定义
   - 依赖注入配置
   - API 使用流程示例

5. **[part4_frontend_integration.md](./part4_frontend_integration.md)**
   - HTML 页面结构
   - CSS 样式设计
   - JavaScript 交互逻辑
   - 导航栏整合方案

6. **[part5_testing_validation.md](./part5_testing_validation.md)**
   - 单元测试、集成测试计划
   - 用户验收测试场景（5个）
   - 性能测试标准
   - 分阶段实作步骤（7-9天）

7. **[task.md](./task.md)**
   - 任务清单与进度追踪

---

## 🎯 核心目标

构建一个**基于本地 RAG 的智能数据分析系统**，让用户能够：
- 用自然语言提问
- AI 自动调用分析工具
- 获得有数据支持的专业分析

---

## 🏗️ 技术架构

### 整体架构图

```
前端 (dashboard.html)
    ↓
智能分析页面 (IntelligentAnalysis.js)
    ↓
API 路由 (/api/analysis/*)
    ↓
LLM Agent (LLMAnalysisAgentSimple)
    ↓
┌─────────────────┬─────────────────┐
│ Tool Executor   │  LLM Reporter   │
│ (18个工具)      │  (Ollama连接)   │
└─────────────────┴─────────────────┘
    ↓                    ↓
Analysis Service    Ollama API
    ↓               (gemma3:27b)
CSV 数据 + 索引
```

### 关键技术决策

| 决策点 | 选择 | 原因 |
|-------|------|------|
| LLM 方案 | 本地 Ollama | 用户已有配置，成本可控 |
| Agent 模式 | 简化版规则匹配 | 本地模型不完全支持 Function Calling |
| 数据隔离 | 基于 session_id | 复用现有的 FileService |
| 索引策略 | 一次性预计算 | 加速后续查询 |
| 工具数量 | 18个 | 覆盖查询、统计、模式发现 |

---

## 📁 文件结构（新增部分）

```
Sigma2/
├── workspace/
│   └── {session_id}/
│       ├── uploads/              # CSV文件（现有）
│       └── analysis/             # 新增
│           └── {file_id}/
│               ├── summary.json
│               ├── statistics.json
│               ├── correlations.json
│               └── semantic_index.json
│
├── backend/
│   ├── services/
│   │   ├── analysis_service.py           # 新增
│   │   ├── analysis_tool_executor.py     # 新增
│   │   └── llm_analysis_agent_simple.py  # 新增
│   └── routers/
│       └── analysis_router.py            # 新增
│
└── static/
    └── js/
        └── intelligent_analysis.js       # 新增
```

---

## 🔧 18个分析工具速览

### 数据查询（5个）
1. `get_parameter_list` - 获取参数列表
2. `get_parameter_statistics` - 参数统计
3. `get_data_overview` - 数据总览
4. `search_parameters_by_concept` - 概念搜索
5. `get_time_series_data` - 时序数据

### 统计分析（6个）
6. `calculate_correlation` - 计算相关性
7. `get_top_correlations` - Top相关性
8. `compare_groups` - 组间比较
9. `detect_outliers` - 异常检测
10. `analyze_distribution` - 分布分析
11. `perform_regression` - 回归分析

### 模式发现（4个）
12. `find_temporal_patterns` - 时序模式
13. `find_event_patterns` - 事件模式
14. `cluster_analysis` - 聚类分析
15. `find_association_rules` - 关联规则

### 对话辅助（3个）
16. `explain_result` - 结果解释
17. `suggest_next_analysis` - 推荐分析
18. `ask_clarification` - 询问澄清

---

## 🚀 快速开始（实作顺序）

### MVP 版本（5-6天）

#### Day 1-2: 后端核心
```bash
# 1. 创建服务文件
backend/services/analysis_service.py
backend/services/analysis_tool_executor.py

# 2. 实现6个核心工具
- get_parameter_list
- get_parameter_statistics
- search_parameters_by_concept
- calculate_correlation
- get_top_correlations
- compare_groups

# 3. 单元测试
pytest tests/test_analysis_service.py
```

#### Day 3: LLM Agent
```bash
# 1. 创建简化版Agent
backend/services/llm_analysis_agent_simple.py

# 2. 实现意图识别规则

# 3. 测试工具调用
pytest tests/test_llm_agent.py
```

#### Day 4: API 层
```bash
# 1. 创建路由
backend/routers/analysis_router.py

# 2. 实现6个端点
- POST /api/analysis/prepare
- POST /api/analysis/chat
- GET  /api/analysis/files
- GET  /api/analysis/summary/{file_id}
- DELETE /api/analysis/clear-session
- GET  /api/analysis/tools

# 3. 注册到主应用
# 在 api_entry.py 中添加:
app.include_router(analysis_router.router)

# 4. 测试API
pytest tests/test_api_endpoints.py
```

#### Day 5-6: 前端
```bash
# 1. 在 dashboard.html 添加新section

# 2. 创建 JavaScript
static/js/intelligent_analysis.js

# 3. 实现交互
- 文件选择
- 索引准备
- 对话发送
- 消息渲染

# 4. 样式优化
```

### 完整版本（+2-3天）

- 实现剩余12个工具
- 性能优化
- 错误处理完善
- 用户体验优化

---

## ✅ 验收标准

### 功能性
- [x] 支持CSV文件上传与索引
- [x] 用户间数据隔离
- [x] 至少6个分析工具可用
- [x] AI能理解常见问题并调用正确工具
- [x] 对话界面流畅

### 性能
- [x] 索引建立：10MB文件 < 30秒
- [x] 对话响应：< 20秒
- [x] 支持文件：< 100MB

### 用户体验
- [x] 界面直观易用
- [x] 错误提示友好
- [x] Loading状态清晰

---

## 🎓 使用示例

### 场景：分析断纸原因

```
1. 用户: "为什么会断纸？"
   ↓
2. Agent: 识别意图 → search_parameters_by_concept("断纸")
   ↓
3. Tool: 返回 ["BREAKAGE_EVENT", "TENSION-A101", ...]
   ↓
4. Agent: 调用 find_event_patterns
   ↓
5. Tool: 分析断纸前的参数变化
   ↓
6. LLM: 生成自然语言回答
   ↓
7. 显示: "根据分析，断纸前30分钟张力平均上升30%，
         建议监控 TENSION-A101 参数..."
```

---

## 📊 预期成果

### 对用户
- ⚡ 极大降低数据分析门槛
- 🎯 快速发现关键问题
- 📈 基于数据的决策支持

### 对系统
- 🔧 可扩展的工具架构
- 🔄 复用现有基础设施
- 📦 模块化设计，易维护

---

## 🔍 后续扩展方向

1. **图表可视化**
   - 集成 Charts Manager
   - AI生成图表配置

2. **报告生成**
   - 导出PDF分析报告
   - 定期自动分析

3. **模型整合**
   - 结合现有训练模型
   - AI推荐模型参数

4. **高级分析**
   - 因果推断
   - 预测分析
   - 优化建议

---

## 📞 支持与反馈

实作过程中如有问题，参考对应章节的详细设计文档。

**关键决策点**：
- Part 2: Agent实现方式选择
- Part 3: API错误处理策略
- Part 5: 测试覆盖范围

**成功关键**：
1. 先做最小可用版本
2. 及时测试和验证
3. 根据用户反馈调整
