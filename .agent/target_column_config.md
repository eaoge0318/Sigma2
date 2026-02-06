# 目标列配置说明 - 2026-02-04

## 🎯 问题

目标列（MEASURE_COL）不应该硬编码在 `config.py` 中，因为：
1. 每个训练任务可能有不同的目标列
2. 目标列信息已经存储在 `job_xxx.json` 配置文件中

## 📋 当前状态

### config.py（旧的硬编码方式）❌
```python
MEASURE_COL = "G_std"  # 硬编码，不适合多任务场景
```

### job_xxx.json（正确的配置）✅
```json
{
    "goal": "METROLOGY-P21-MO1-SP-2SIGMA",  // 实际的目标列名
    "goalSettings": {
        "target": "1",
        "usl": "2.0",
        "lsl": "0"
    },
    ...
}
```

## 🔧 需要修改的地方

### 1. 后端 API（已完成）✅

后端 API 已经从 `job_xxx.json` 读取模型配置：
- `agent_logic.py` - 正确加载 RL 模型和预测模型路径
- 推理时不需要使用 MEASURE_COL

### 2. 训练脚本（需要修改）⚠️

以下脚本可能还在使用 `config.MEASURE_COL`：
- `train_entry.py` - 训练入口
- `engine_strategy.py` - RL 策略训练
- `engine_pred.py` - 预测模型训练
- 其他训练相关脚本

### 修改方案

training时应该：

```python
# 原来的方式 ❌
from config import MEASURE_COL
df[MEASURE_COL]

# 新的方式 ✅
# 从前端传来的训练请求中获取 job config
with open(job_config_path, 'r') as f:
    job_conf = json.load(f)
    
target_col = job_conf.get('goal')  # 从 JSON 读取
df[target_col]
```

## 📝 建议行动

### 选项 A：保持现状（临时方案
