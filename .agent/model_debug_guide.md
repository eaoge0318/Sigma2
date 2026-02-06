# 策略模型诊断调试指南 - 2026-02-04

## 🎯 问题

策略模型（RL/IQL）无法提供预测建议，返回：
```
"警告：尚未載入有效的策略模型，無法提供建議。請先執行模型訓練。"
```

## ✅ 已添加的调试日志

### 1. 模型加载日志（agent_logic.py - reload_model）

启动后端时会显示：

```
ℹ️ No specific model specified, searching for latest model in ...
✅ Found latest model: ... (或 ⚠️ No model found in ...)
🔄 Loading policy bundle from: ...
✅ Policy bundle loaded successfully
   - bg_features: XXX features
   - action_stds: [...]
🔄 Loading XGBoost simulator from: ...
✅ XGBoost model loaded successfully
✅ SHAP explainer initialized
AgenticReasoning: Session Mantle models reloaded successfully
  - RL Model: ...
  - Prediction Model Dir: ...
  - IQL Available: True/False  ← 关键指标！
  - XGBoost Available: True/False
```

### 2. 推理调用日志（prediction_service.py - predict）

每次执行推理时会显示：

```
============================================================
🎯 PredictionService.predict() 被调用
============================================================
Session ID: Mantle
Measure Value: 998.7405
Row data keys: ['MEDIC-ABB_B41', 'SHAP-DCS_A50', ...]...
✅ Agent found, calling get_reasoned_advice()...
```

### 3. 推理详细日志（agent_logic.py - get_reasoned_advice）

```
============================================================
🔍 get_reasoned_advice 调试信息
============================================================
Session ID: Mantle
IQL Model Available: True/False  ← 关键！
Simulator Available: True/False
XGBoost Model Available: True/False
BG Features Count: 237
Action STDs: [0.617 0.021 0.172]
Current Y: 998.7405

❌ IQL model not loaded!  (如果失败)
   Reason: self.iql_algo is None

或

❌ BG features not loaded!  (如果失败)
   Reason: self.bg_features is None or empty

或

✅ All models loaded successfully, proceeding with inference...
============================================================
```

## 📋 诊断步骤

### 步骤 1：重新启动后端

```bash
# 停止当前后端（Ctrl + C）
python api_entry.py
```

### 步骤 2：观察启动日志

查找以下关键信息：

1. **模型搜索**
   ```
   ℹ️ No specific model specified, searching for latest model in workspace/Mantle/bundles
   ```
   
2. **找到模型** ← 如果这里显示 "⚠️ No model found"，就是问题所在！
   ```
   ✅ Found latest model: workspace/Mantle/bundles/rl_run_20260204_002750
   ```

3. **模型加载**
   ```
   🔄 Loading policy bundle from: ...
   ✅ Policy bundle loaded successfully
   ```

4. **最终状态** ← 这是关键！
   ```
   - IQL Available: True  ← 必须是 True
   - XGBoost Available: True
   ```

### 步骤 3：执行推理测试

访问测试页面：
```
http://10.10.20.109:8001/test_simulator.html
```

1. 选择文件
2. 选择模型（job_7ba3af9e.json）
3. 点击 "Run Simulation"

### 步骤 4：查看后端终端输出

应该看到完整的调用链：

```
🎯 PredictionService.predict() 被调用
  ↓
✅ Agent found, calling get_reasoned_advice()...
  ↓
🔍 get_reasoned_advice 调试信息
  ↓
IQL Model Available: True  ← 如果是 False，这就是问题！
```

## 🔍 常见问题和解决方案

### 问题 1：找不到模型

**日志**:
```
⚠️ No model found in workspace/Mantle/bundles
- IQL Available: False
```

**原因**: bundles 目录中没有 RL 模型，或者目录结构不对

**解决方案**:
1. 检查是否有训练好的模型：
   ```bash
   dir workspace\Mantle\bundles\rl_run_*
   ```
2. 如果没有，需要先训练模型
3. 如果有，检查目录结构是否正确：
   ```
   rl_run_xxxx/
   └── policy_bundle/
       ├── policy.d3rlpy
       ├── meta.json
       └── algo_meta.json
   ```

### 问题 2：模型加载失败

**日志**:
```
🔄 Loading policy bundle from: ...
❌ Failed to load policy bundle: ...
- IQL Available: False
```

**原因**: 模型文件损坏或版本不兼容

**解决方案**:
1. 运行测试脚本验证模型：
   ```bash
   python test_model_loading.py
   ```
2. 如果失败，需要重新训练模型

### 问题 3：加载成功但仍无法预测

**日志**:
```
✅ Policy bundle loaded successfully
- IQL Available: True
但推理时：
❌ IQL model not loaded!
```

**原因**: 可能是 session 隔离问题，不同 session 使用了不同的 Agent 实例

**解决方案**:
1. 检查 session_id 是否一致
2. 确认使用的是同一个 session（例如都是 "Mantle"）

### 问题 4：bg_features 未加载

**日志**:
```
❌ BG features not loaded!
   Reason: self.bg_features is None or empty
```

**原因**: meta.json 中没有 bg_features，或加载时出错

**解决方案**:
1. 检查 meta.json：
   ```bash
   type workspace\Mantle\bundles\rl_run_xxx\policy_bundle\meta.json
   ```
2. 确认包含 "bg_features" 字段
3. 如果没有，需要重新训练模型

## 🎯 快速诊断清单

请依次检查并回答：

- [ ] 后端启动时显示 "✅ Found latest model"？
- [ ] 后端启动时显示 "✅ Policy bundle loaded successfully"？
- [ ] 后端启动时显示 "IQL Available: True"？
- [ ] 执行推理时显示 "✅ Agent found"？
- [ ] 执行推理时显示 "IQL Model Available: True"？
- [ ] 执行推理时显示 "BG Features Count: > 0"？

如果任何一项是 ❌，请根据上面的解决方案处理。

## 📤 需要提供的信息

如果问题仍未解决，请提供：

1. **后端启动日志**（完整的模型加载部分）
2. **推理调用日志**（包含所有 ============ 分隔的部分）
3. **test_model_loading.py 的输出**（如果运行了）

这些信息将帮助我们精确定位问题！
