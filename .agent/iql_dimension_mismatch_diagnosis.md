# IQL 模型特徵維度不匹配問題 - 診斷報告

## 問題描述

**錯誤訊息**: "警告: IQL 模型特徵維度不匹配 (期望: 8 個特徵)"

## 問題根源

### 特徵來源不一致

1. **JSON 配置檔** (`job_27acde4b.json`):
   - `states` (背景參數): 4 個
   - `actions` (活動參數): 4 個
   - **總計**: 8 個特徵

2. **IQL 模型 Metadata**:
   - 程式碼從 `self.meta["bg_features"]` 讀取
   - 這是**訓練時儲存**的特徵列表
   - 可能與當前 JSON 配置不同!

### 程式碼邏輯

```python
# agent_logic.py, line 135-136
self.bg_features = self.meta["bg_features"]  # 從模型 metadata 讀取
self.action_stds = self.meta["action_stds"]
```

```python
# agent_logic.py, line 247-249
bg_vals = [row[f] for f in self.bg_features]  # 使用 metadata 中的特徵
act_vals = [row[f] for f in config.ACTION_FEATURES]
state_iql = np.concatenate([bg_vals, act_vals, [current_y]], axis=0)
```

**問題**: 
- `self.bg_features` 來自模型訓練時的 metadata
- `config.ACTION_FEATURES` 來自 config.py
- 如果這兩者的總數不等於 8,就會出現維度不匹配!

## 診斷步驟

### 1. 檢查後端日誌

查看模型載入時的輸出:
```
✅ Policy bundle loaded successfully
   - bg_features: X features  <-- 這個數字是多少?
   - action_stds: ...
```

### 2. 檢查 config.py

查看 `config.ACTION_FEATURES` 有多少個:
```python
# config.py
ACTION_FEATURES = [...]  # 有幾個?
```

### 3. 計算總特徵數

```
總特徵數 = len(bg_features) + len(ACTION_FEATURES) + 1 (current_y)
```

如果這個數字不等於 8,就會出錯!

## 可能的原因

### 原因 1: config.ACTION_FEATURES 數量不對

- JSON 中 `actions` 有 4 個
- 但 `config.ACTION_FEATURES` 可能有不同數量
- **解決方案**: 修改 `config.py`,確保 `ACTION_FEATURES` 有 4 個

### 原因 2: 模型訓練時使用了不同的特徵

- IQL 模型訓練時使用了不同數量的 `bg_features`
- **解決方案**: 使用當前配置重新訓練 IQL 模型

### 原因 3: 程式碼沒有從 JSON 讀取特徵

- 程式碼應該從 JSON 的 `states` 和 `actions` 讀取
- 而不是從 `config.py` 讀取
- **解決方案**: 修改程式碼,從 JSON 配置讀取特徵

## 建議的修復方案

### 方案 1: 修改程式碼,從 JSON 讀取特徵 (推薦)

修改 `agent_logic.py` 的 `reload_model` 方法:

```python
# 在載入 JSON 配置後
if target_bundle_name.endswith(".json"):
    with open(config_path, "r", encoding="utf-8") as f:
        job_conf = json.load(f)
        
        # 讀取 IQL 特徵
        self.bg_features = job_conf.get("states", [])
        self.action_features = job_conf.get("actions", [])
        
        # 更新 config.ACTION_FEATURES
        config.ACTION_FEATURES = self.action_features
```

### 方案 2: 檢查並修正 config.py

確保 `config.ACTION_FEATURES` 與 JSON 中的 `actions` 一致:

```python
# config.py
ACTION_FEATURES = [
    "BCDRY-ABB_B23",
    "FORMULA-DCS_A1",
    "MEDIC-ABB_B40",
    "MEDIC-ABB_B84"
]
```

### 方案 3: 重新訓練模型

使用當前的 JSON 配置重新訓練 IQL 模型,確保特徵一致。

## 下一步

1. **檢查後端日誌**,確認實際載入的 `bg_features` 數量
2. **檢查 config.py**,確認 `ACTION_FEATURES` 數量
3. **根據診斷結果選擇修復方案**
