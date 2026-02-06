# DEBUG 日志使用指南 - 2026-02-04

## ✅ 已配置完成

现在系统使用了 Python logging 模块，设置为 DEBUG 级别，所有日志都会输出到终端。

## 🎯 如何查看DEBUG日志

### 步骤 1：重新启动后端

```bash
# 在后端终端按 Ctrl + C 停止
python api_entry.py
```

### 步骤 2：观察启动日志

现在会看到更详细的输出：

```
2026-02-04 08:40:00 [INFO] __main__: ============================================================
2026-02-04 08:40:00 [INFO] __main__: 🚀 Starting Sigma2 API Server with DEBUG logging
2026-02-04 08:40:00 [INFO] __main__: ============================================================
2026-02-04 08:40:01 [INFO] agent_logic: ℹ️ No specific model specified, searching for latest model in ...
2026-02-04 08:40:01 [INFO] agent_logic: ✅ Found latest model: ...
2026-02-04 08:40:01 [INFO] agent_logic: 🔄 Loading policy bundle from: ...
2026-02-04 08:40:02 [INFO] agent_logic: ✅ Policy bundle loaded successfully
2026-02-04 08:40:02 [INFO] agent_logic:    - bg_features: 237 features
2026-02-04 08:40:02 [INFO] agent_logic:    - action_stds: [0.617 0.021 0.172]
2026-02-04 08:40:03 [INFO] agent_logic: ✅ XGBoost model loaded successfully
2026-02-04 08:40:03 [INFO] agent_logic: ✅ SHAP explainer initialized
2026-02-04 08:40:03 [INFO] agent_logic: AgenticReasoning: Session Mantle models reloaded successfully
2026-02-04 08:40:03 [INFO] agent_logic:   - RL Model: workspace/Mantle/bundles/rl_run_xxx...
2026-02-04 08:40:03 [INFO] agent_logic:   - Prediction Model Dir: workspace/Mantle/bundles/pred_run_xxx...
2026-02-04 08:40:03 [INFO] agent_logic:   - IQL Available: True  ← 关键！
2026-02-04 08:40:03 [INFO] agent_logic:   - XGBoost Available: True
```

### 步骤 3：执行推理并查看DEBUG日志

访问测试页面或 Dashboard，执行模拟。会看到：

```
2026-02-04 08:41:00 [DEBUG] backend.services.prediction_service: ============================================================
2026-02-04 08:41:00 [DEBUG] backend.services.prediction_service: 🎯 PredictionService.predict() 被调用
2026-02-04 08:41:00 [DEBUG] backend.services.prediction_service: ============================================================
2026-02-04 08:41:00 [DEBUG] backend.services.prediction_service: Session ID: Mantle
2026-02-04 08:41:00 [DEBUG] backend.services.prediction_service: Measure Value: 998.7405
2026-02-04 08:41:00 [DEBUG] backend.services.prediction_service: Row data keys: ['MEDIC-ABB_B41', 'SHAP-DCS_A50', ...]...
2026-02-04 08:41:00 [DEBUG] backend.services.prediction_service: ✅ Agent found, calling get_reasoned_advice()...
2026-02-04 08:41:00 [DEBUG] agent_logic: ============================================================
2026-02-04 08:41:00 [DEBUG] agent_logic: 🔍 get_reasoned_advice 调试信息
2026-02-04 08:41:00 [DEBUG] agent_logic: ============================================================
2026-02-04 08:41:00 [DEBUG] agent_logic: Session ID: Mantle
2026-02-04 08:41:00 [DEBUG] agent_logic: IQL Model Available: True  ← 关键！
2026-02-04 08:41:00 [DEBUG] agent_logic: Simulator Available: True
2026-02-04 08:41:00 [DEBUG] agent_logic: XGBoost Model Available: True
2026-02-04 08:41:00 [DEBUG] agent_logic: BG Features Count: 237
2026-02-04 08:41:00 [DEBUG] agent_logic: Action STDs: [0.61694056 0.02061815 0.17201719]
2026-02-04 08:41:00 [DEBUG] agent_logic: Current Y: 998.7405
2026-02-04 08:41:00 [INFO] agent_logic: ✅ All models loaded successfully, proceeding with inference...
2026-02-04 08:41:00 [DEBUG] agent_logic: ============================================================
```

### 步骤 4：如果出错，会看到 ERROR 级别日志

```
2026-02-04 08:41:00 [ERROR] agent_logic: ❌ IQL model not loaded!
2026-02-04 08:41:00 [ERROR] agent_logic:    Reason: self.iql_algo is None
```

## 📋 日志级别说明

日志按重要性分为：

- **DEBUG**: 详细的调试信息（蓝色 🔍）
  - 显示所有内部状态、变量值
  - 用于诊断问题
  
- **INFO**: 一般信息（绿色 ✅）
  - 显示正常的操作流程
  - 模型加载成功等
  
- **WARNING**: 警告信息（黄色 ⚠️）
  - 不影响运行但需要注意的情况
  - 例如：没有找到指定的模型，使用最新的
  
- **ERROR**: 错误信息（红色 ❌）
  - 操作失败
  - 例如：模型加载失败、特征未找到

## 🔍 如何诊断问题

### 问题 1：看不到 DEBUG 日志  

**症状**: 只看到 INFO 日志
**原因**: logging配置没有生效
**解决**: 
1. 确认代码已保存
2. 重新启动后端
3. 如果仍然没有，检查是否有其他地方覆盖了 logging 配置

### 问题 2：日志输出乱码

**症状**: 看到 `�` 等乱码字符
**原因**: 终端编码问题
**解决**:
```bash
# Windows PowerShell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# 或者使用 Windows Terminal，默认支持 UTF-8
```

### 问题 3：日志太多看不清

**症状**: 日志刷屏
**解决**: 使用 `findstr` (Windows) 或 `grep` (Linux) 过滤：

```bash
# 只看 ERROR
python api_entry.py 2>&1 | findstr ERROR

# 只看特定模块
python api_entry.py 2>&1 | findstr agent_logic

# 只看关键信息
python api_entry.py 2>&1 | findstr "IQL Available"
```

## 📤 如何提供日志给我

### 方法 1：复制完整日志

1. 启动后端
2. 等待模型加载完成
3. 选中终端内容（从 "Starting Sigma2" 到 "IQL Available"）
4. 右键复制
5. 粘贴给我

### 方法 2：保存日志到文件

```bash
# 将日志输出到文件
python api_entry.py > debug.log 2>&1

# 然后查看文件
type debug.log
```

### 方法 3：只提供关键部分

如果日志太长，请提供：

1. **模型加载部分** (从 "Starting Sigma2" 到 "IQL Available")
2. **推理调用部分** (如果执行了推理，包含所有 `====` 分隔的部分)
3. **错误部分** (所有 [ERROR] 行)

## ✅ 现在可以开始了

请：

1. **重新启动后端** (`python api_entry.py`)
2. **复制启动日志** (包含 "IQL Available" 的部分)
3. **执行一次推理测试** (访问 Dashboard 或测试页面)
4. **复制推理日志** (包含 "get_reasoned_advice" 的部分)
5. **把两部分日志都粘贴给我**

这样我就能看到完整的执行流程和问题所在了！🎯
