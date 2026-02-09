# Part 5: 测试与验证计划

## 测试策略

```
测试金字塔
├── 单元测试 (40%) - 工具函数、数据处理
├── 集成测试 (40%) - API端点、工具调用
└── 用户验收测试 (20%) - 完整流程、真实场景
```

---

## 1. 单元测试

### 测试范围

#### 1.1 分析服务 (`AnalysisService`)

```python
# tests/test_analysis_service.py

import pytest
from backend.services.analysis_service import AnalysisService
import pandas as pd
import os

@pytest.fixture
def sample_csv():
    """创建测试用的CSV文件"""
    data = {
        'TENSION-A101': [450, 460, 470, 480, 490],
        'MOISTURE-B23': [65, 67, 66, 68, 70],
        'QUALITY': [0.95, 0.94, 0.96, 0.93, 0.92]
    }
    df = pd.DataFrame(data)
    
    test_path = 'test_data.csv'
    df.to_csv(test_path, index=False)
    yield test_path
    os.remove(test_path)

def test_build_analysis_index(sample_csv):
    """测试索引建立"""
    service = AnalysisService(base_dir='test_workspace')
    
    summary = service.build_analysis_index(
        csv_path=sample_csv,
        session_id='test_user',
        filename='test_data.csv'
    )
    
    assert summary['total_rows'] == 5
    assert summary['total_columns'] == 3
    assert 'TENSION-A101' in summary['parameters']

def test_categorize_parameters():
    """测试参数分类"""
    service = AnalysisService()
    
    params = ['TENSION-A101', 'TENSION-B23', 'MOISTURE-C45']
    categories = service._categorize_parameters(params)
    
    assert 'TENSION' in categories
    assert len(categories['TENSION']) == 2
```

#### 1.2 工具执行器 (`AnalysisToolExecutor`)

```python
# tests/test_tool_executor.py

def test_get_parameter_list():
    """测试参数列表获取"""
    executor = AnalysisToolExecutor(analysis_service)
    
    result = executor.get_parameter_list({
        'file_id': 'test_file_id',
        'keyword': 'TENSION'
    }, session_id='test_user')
    
    assert result['matched_count'] > 0
    assert all('TENSION' in p for p in result['parameters'])

def test_calculate_correlation():
    """测试相关性计算"""
    result = executor.calculate_correlation({
        'file_id': 'test_file_id',
        'method': 'pearson',
        'parameters': ['TENSION-A101', 'QUALITY']
    }, session_id='test_user')
    
    assert 'results' in result
    assert result['results'][0]['correlation'] is not None

def test_detect_outliers():
    """测试异常值检测"""
    result = executor.detect_outliers({
        'file_id': 'test_file_id',
        'parameter': 'TENSION-A101',
        'method': 'zscore'
    }, session_id='test_user')
    
    assert 'outliers' in result
    assert 'outlier_count' in result
```

---

## 2. 集成测试

### 2.1 API 端点测试

```python
# tests/test_api_endpoints.py

from fastapi.testclient import TestClient
from api_entry import app

client = TestClient(app)

def test_prepare_file():
    """测试文件准备接口"""
    response = client.post('/api/analysis/prepare', json={
        'filename': 'test_data.csv',
        'session_id': 'test_user'
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'success'
    assert 'file_id' in data

def test_chat():
    """测试智能对话接口"""
    # 先准备文件
    prepare_response = client.post('/api/analysis/prepare', json={
        'filename': 'test_data.csv',
        'session_id': 'test_user'
    })
    file_id = prepare_response.json()['file_id']
    
    # 发送问题
    chat_response = client.post('/api/analysis/chat', json={
        'session_id': 'test_user',
        'file_id': file_id,
        'message': '有哪些参数？'
    })
    
    assert chat_response.status_code == 200
    data = chat_response.json()
    assert 'response' in data
    assert data['tool_used'] is not None

def test_list_files():
    """测试文件列表接口"""
    response = client.get('/api/analysis/files?session_id=test_user')
    
    assert response.status_code == 200
    data = response.json()
    assert 'files' in data
```

### 2.2 LLM Agent 测试

```python
# tests/test_llm_agent.py

def test_intent_identification():
    """测试意图识别"""
    agent = LLMAnalysisAgentSimple(tool_executor)
    
    # 测试参数列表意图
    intent = agent._identify_intent("有哪些温度参数？", "test_file_id")
    assert intent['tool'] == 'search_parameters_by_concept'
    assert intent['params']['concept'] == '温度'
    
    # 测试相关性意图
    intent = agent._identify_intent("分析相关性", "test_file_id")
    assert intent['tool'] == 'calculate_correlation'

def test_analyze():
    """测试完整分析流程"""
    result = agent.analyze(
        session_id='test_user',
        file_id='test_file_id',
        user_question='张力参数有哪些？'
    )
    
    assert 'response' in result
    assert result['tool_used'] is not None
```

---

## 3. 用户验收测试（UAT）

### 测试场景

#### 场景1：新用户首次使用

**步骤**：
1. 用户登录系统
2. 进入"智能分析"页面
3. 上传一个CSV文件
4. 选择文件并点击"准备分析索引"
5. 等待索引建立完成（约1-2分钟）
6. 输入问题："有哪些参数？"
7. 查看AI回答

**验收标准**：
- ✅ 文件上传成功
- ✅ 索引建立进度有提示
- ✅ 索引建立完成后状态变为"已准备"
- ✅ AI回答准确列出所有参数
- ✅ 响应时间 < 10秒

---

#### 场景2：相关性分析

**步骤**：
1. 选择已准备好的文件
2. 提问："温度与品质的相关性如何？"
3. 查看分析结果

**验收标准**：
- ✅ AI 自动调用 `search_parameters_by_concept` 找到温度参数
- ✅ AI 调用 `calculate_correlation` 计算相关性
- ✅ 返回具体的相关系数和p值
- ✅ 提供专业解读

---

#### 场景3：断纸原因分析

**步骤**：
1. 选择包含断纸事件的数据文件
2. 提问："为什么会断纸？"
3. 查看分析结果

**验收标准**：
- ✅ AI 识别"断纸"概念并搜索相关参数
- ✅ 自动分析断纸事件前的参数变化
- ✅ 提供可能的原因和建议
- ✅ 回答基于实际数据，不是臆测

---

#### 场景4：多轮对话

**步骤**：
1. 第一轮："有哪些温度参数？"
2. 第二轮："这些参数中哪个最重要？"
3. 第三轮："分析它与品质的关系"

**验收标准**：
- ✅ 每一轮都能正确理解上下文
- ✅ 第二轮能基于第一轮的结果分析
- ✅ 对话连贯，不需要重复说明

---

#### 场景5：错误处理

**步骤**：
1. 未选择文件直接提问
2. 选择未准备的文件提问
3. 提问含糊不清的问题

**验收标准**：
- ✅ 提示"请先选择文件"
- ✅ 提示"文件尚未准备"
- ✅ AI 能主动澄清或提供建议

---

## 4. 性能测试

### 4.1 索引建立性能

| 文件大小 | 参数数 | 行数 | 预期时间 |
|---------|-------|------|---------|
| 1 MB | 50 | 1,000 | < 10秒 |
| 10 MB | 100 | 10,000 | < 30秒 |
| 50 MB | 150 | 50,000 | < 2分钟 |
| 100 MB | 200 | 100,000 | < 5分钟 |

### 4.2 对话响应性能

| 操作 | 预期时间 |
|-----|---------|
| 简单查询（参数列表） | < 5秒 |
| 统计分析（相关性） | < 10秒 |
| 复杂分析（事件模式） | < 20秒 |
| LLM生成回答 | < 15秒 |

### 4.3 并发测试

- 10个用户同时使用：响应时间增加 < 50%
- 文件隔离正确：用户A看不到用户B的文件

---

## 5. 分阶段实作步骤

### 阶段一：核心后端（3-4天）

**Day 1-2: 数据处理与工具**
- [ ] 实现 `AnalysisService.build_analysis_index()`
- [ ] 实现 `AnalysisToolExecutor` 的 6 个核心工具：
  - get_parameter_list
  - get_parameter_statistics
  - search_parameters_by_concept
  - calculate_correlation
  - get_top_correlations
  - compare_groups
- [ ] 编写单元测试
- [ ] 测试通过

**Day 3: LLM Agent**
- [ ] 实现 `LLMAnalysisAgentSimple`
- [ ] 完成意图识别规则
- [ ] 测试工具调用流程
- [ ] 编写集成测试

**Day 4: API 路由**
- [ ] 实现 `analysis_router.py` 的所有端点
- [ ] 测试 API 接口
- [ ] 错误处理完善

---

### 阶段二：前端开发（2-3天）

**Day 5: 基础UI**
- [ ] 创建 HTML 结构
- [ ] 实现 CSS 样式
- [ ] 导航栏整合

**Day 6: 交互逻辑**
- [ ] 实现 `IntelligentAnalysis` 类
- [ ] 文件选择与准备
- [ ] 对话发送与接收
- [ ] 消息渲染

**Day 7: 优化与完善**
- [ ] 快捷按钮功能
- [ ] 工具列表展示
- [ ] Loading 状态
- [ ] 错误提示优化

---

### 阶段三：测试与优化（2天）

**Day 8: 集成测试**
- [ ] 完整流程测试
- [ ] 用户验收测试（5个场景）
- [ ] 性能测试
- [ ] Bug修复

**Day 9: 部署与文档**
- [ ] 部署到生产环境
- [ ] 编写用户手册
- [ ] 系统监控配置
- [ ] 团队培训

---

### 阶段四：增强功能（可选，2-3天）

- [ ] 实现剩余 12 个工具
- [ ] 图表可视化集成（调用 Charts Manager）
- [ ] 对话历史持久化
- [ ] 导出分析报告功能

---

## 6. 验收检查清单

### 功能完整性
- [ ] 文件上传与列表显示
- [ ] 索引建立与状态提示
- [ ] 智能对话与工具调用
- [ ] 用户隔离（session_id）
- [ ] 错误处理与提示

### 性能要求
- [ ] 索引建立时间符合预期
- [ ] 对话响应时间 < 20秒
- [ ] 支持文件大小 < 100MB

### 用户体验
- [ ] 界面美观、布局合理
- [ ] 操作流程清晰
- [ ] 提示信息友好
- [ ] 无明显卡顿

### 代码质量
- [ ] 单元测试覆盖率 > 70%
- [ ] 代码符合 PEP8 规范
- [ ] API 文档完整
- [ ] 有详细注释

---

## 总结

完整实作预计需要 **7-9 个工作日**，包括：
- **核心功能** (6-7天)
- **测试验证** (1-2天)

**推荐实作顺序**：
1. 先做最小可用版本（MVP）：6个核心工具 + 简化版Agent
2. 完成前端界面并集成
3. 用户验收测试
4. 根据反馈优化和扩展

**风险控制**：
- 每完成一个阶段就进行测试
- 及时修复 Bug，不积累技术债
- 与用户保持沟通，及时调整方向
