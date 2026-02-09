# 智能分析功能实作任务清单 (模块化版本)

## 规划阶段
- [x] 理解现有系统架构
- [x] 确认技术选型（本地 Ollama）
- [x] 设计18个分析工具
- [x] 优化为模块化架构（单文件≤350行）
- [x] 创建模块化规划文档
  - [x] README.md - 总览
  - [x] 01_architecture.md - 详细架构
  - [x] 02_backend_modules.md - 后端实现
  - [x] 03_api_design.md - API设计
  - [x] 04_frontend.md - 前端实现
  - [x] 05_implementation_steps.md - 实作步骤

## 实作阶段 - 后端核心 (3-4天)

### Day 1-2: 基础服务 + 查询工具
- [ ] 创建目录结构
  - [ ] `backend/services/analysis/`
  - [ ] `backend/services/analysis/tools/`
- [ ] 实现基础模块
  - [ ] `analysis/__init__.py` (20行)
  - [ ] `tools/__init__.py` (30行)
  - [ ] `tools/base.py` (50行) - 工具基类
- [ ] 实现核心索引服务
  - [ ] `analysis_service.py` (350行)
    - [ ] build_analysis_index()
    - [ ] _categorize_parameters()
    - [ ] _build_semantic_index()
- [ ] 实现查询工具
  - [ ] `tools/data_query.py` (200行)
    - [ ] GetParameterList (3个工具先实现)
    - [ ] GetParameterStatistics
    - [ ] SearchParametersByConcept

### Day 3: 统计工具 + Agent
- [ ] 实现统计工具
  - [ ] `tools/statistics.py` (250行)
    - [ ] CalculateCorrelation (3个核心工具)
    - [ ] GetTopCorrelations
    - [ ] CompareGroups
- [ ] 实现工具执行器
  - [ ] `tools/executor.py` (100行)
- [ ] 实现 LLM Agent
  - [ ] `agent.py` (250行)
    - [ ] 意图识别
    - [ ] 工具调用
    - [ ] 结果生成

### Day 4: API 层
- [ ] 实现 API 路由
  - [ ] `routers/analysis_router.py` (200行)
    - [ ] POST /api/analysis/prepare
    - [ ] POST /api/analysis/chat
    - [ ] GET /api/analysis/files
    - [ ] GET /api/analysis/summary/{file_id}
- [ ] 更新依赖注入
  - [ ] `dependencies.py` (+35行)
- [ ] 注册路由
  - [ ] `api_entry.py` (+2行)
- [ ] 后端测试
  - [ ] 单元测试
  - [ ] API 测试

## 实作阶段 - 前端 (2天)

### Day 5: UI 基础
- [ ] 修改 dashboard.html
  - [ ] 新增智能分析 section
  - [ ] 添加 CSS 样式
  - [ ] 整合导航栏
- [ ] 创建 JavaScript
  - [ ] `static/js/intelligent_analysis.js`
    - [ ] 文件选择逻辑
    - [ ] 索引准备功能

### Day 6: 交互完善
- [ ] 对话功能
  - [ ] 消息发送与接收
  - [ ] 消息渲染
  - [ ] Loading 状态
- [ ] 快捷操作
  - [ ] 快捷按钮
  - [ ] 工具列表展示
- [ ] 错误处理
  - [ ] 友好提示
  - [ ] 状态管理

## 实作阶段 - 测试与部署 (1-2天)

### Day 7: 集成测试
- [ ] 完整流程测试
- [ ] 性能测试
- [ ] Bug 修复

### Day 8: 部署与文档
- [ ] 生产环境部署
- [ ] 用户手册
- [ ] 代码注释完善

## 扩展阶段 (可选，2-3天)

### 剩余工具实现
- [ ] `tools/patterns.py` (200行)
  - [ ] FindTemporalPatterns
  - [ ] FindEventPatterns
  - [ ] ClusterAnalysis
  - [ ] FindAssociationRules
- [ ] `tools/helpers.py` (100行)
  - [ ] ExplainResult
  - [ ] SuggestNextAnalysis
  - [ ] AskClarification
- [ ] 补充查询工具
  - [ ] GetDataOverview
  - [ ] GetTimeSeriesData
- [ ] 补充统计工具
  - [ ] DetectOutliers
  - [ ] AnalyzeDistribution
  - [ ] PerformRegression

### 优化与增强
- [ ] 图表可视化集成
- [ ] 对话历史持久化
- [ ] 导出报告功能
- [ ] 性能优化
