# AssertionError 特徵維度不匹配問題

## 錯誤訊息
```
AssertionError
File "agent_logic.py", line 271, in get_reasoned_advice
    action_norm = self.iql_algo.predict(state_iql)[0]
```

## 問題原因

這是一個**模型與數據不兼容**的問題:

1. **IQL 模型**訓練時使用了特定的特徵集 (例如: 100 個特徵)
2. **當前模擬數據**提供了不同的特徵集 (例如: 200 個特徵)
3. d3rlpy 的 observation_scaler 檢測到維度不匹配,拋出 AssertionError

## 根本原因

您載入的 `job_xxx.json` 配置檔案中定義的特徵集,與實際訓練 IQL 模型時使用的特徵集不一致。

### 可能的情況:

1. **配置檔案是給 XGBoost 用的** (supervised learning)
   - XGBoost 可以使用所有特徵
   - 但 IQL 模型只訓練了部分特徵

2. **載入了錯誤的 IQL 模型**
   - 配置檔案指向的 `run_dir` 不是正確的 IQL 模型

3. **特徵順序不一致**
   - 訓練時的特徵順序與推理時不同

## 解決方案

### 方案 1: 使用正確的模型配置組合

確保載入的 `job_xxx.json` 配置檔案中:
- `run_dir` 指向正確的 IQL 模型路徑
- `run_path` 指向正確的 XGBoost 模型路徑
- 兩個模型使用相同的特徵集訓練

### 方案 2: 檢查並修正特徵集

1. 查看 IQL 模型訓練時使用的特徵:
   ```python
   # 在 agent_logic.py 的 reload_model 中會顯示:
   print(f"   - bg_features: {len(self.meta.get('bg_features', []))} features")
   ```

2. 查看當前模擬數據的特徵:
   ```python
   # 在 simulator_next 中會顯示:
   print(f"[DEBUG] Data dict keys: {list(data_dict.keys())[:10]}...")
   ```

3. 確保兩者一致

### 方案 3: 重新訓練模型 (推薦)

如果您想使用新的特徵集進行模擬,需要:

1. 使用新的特徵集重新訓練 IQL 模型
2. 使用新的特徵集重新訓練 XGBoost 模型
3. 更新 `job_xxx.json` 配置檔案

### 方案 4: 暫時跳過 IQL 推理 (快速測試)

如果只是想測試 Y 軸功能,可以暫時修改程式碼跳過 IQL:

```python
# 在 agent_logic.py 的 get_reasoned_advice 中
# 暫時返回 HOLD 狀態
if True:  # 暫時跳過 IQL
    return {
        "current_y": current_y,
        "iql_action_delta": None,
        "iql_action_delta_smoothed": None,
        "predicted_y_next": None,
        "top_influencers": [],
        "current_top_influencers": [],
        "smoothed_top_influencers": [],
        "status": "HOLD",
        "diagnosis": "測試模式: IQL 推理已停用",
    }
```

## 診斷步驟

1. 查看伺服器 console,找到模型載入時的訊息:
   ```
   ✅ Policy bundle loaded successfully
      - bg_features: XXX features
   ```

2. 查看模擬執行時的訊息:
   ```
   [DEBUG] Data dict keys: [...]
   [DEBUG] BG Features count: XXX
   ```

3. 比較兩個數字是否一致

## 當前建議

由於這是**模型兼容性問題**,不是 Y 軸配置問題,建議:

1. **先確認 Y 軸功能是否正常**
   - 查看 console 中是否有: `[DEBUG] Goal column from model config: ...`
   - 如果有,表示 Y 軸配置已經生效

2. **解決模型兼容性問題**
   - 使用匹配的模型配置
   - 或重新訓練模型

3. **如果只是測試 Y 軸**
   - 可以暫時停用 IQL 推理
   - 只使用 XGBoost 模擬器
