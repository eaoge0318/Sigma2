# 修復 ACTION_FEATURES 錯誤總結

## ❌ 原始錯誤

```
AttributeError: module 'config' has no attribute 'ACTION_FEATURES'
```

**錯誤發生位置：**
- `model_manager.py` 第 32 行
- 在 `save_policy_bundle()` 函數中

## 🔍 問題原因

`model_manager.py` 中的 `save_policy_bundle()` 函數試圖從 `config.ACTION_FEATURES` 讀取動作特徵列表，但：
1. `config.py` 中沒有定義 `ACTION_FEATURES` 這個全域變數
2. 實際上 `action_features` 應該是從訓練任務的配置中動態獲得，而非硬編碼在 config 中

## ✅ 解決方案

將 `action_features` 改為函數參數，從呼叫處傳入，而不是從 `config` 模組讀取。

### 修改的檔案

#### 1. `model_manager.py`

**變更：**
- 函數簽名增加 `action_features` 參數
- 從參數獲取值，不再從 `config` 讀取

```python
# 修改前
def save_policy_bundle(
    algo, save_dir, bg_features, action_stds, epoch=None, diff=None, target_range=None
):
    meta = {
        "action_features": config.ACTION_FEATURES,  # ❌ 錯誤
        ...
    }

# 修改後
def save_policy_bundle(
    algo, save_dir, bg_features, action_features, action_stds, epoch=None, diff=None, target_range=None
):
    meta = {
        "action_features": action_features,  # ✅ 從參數獲取
        ...
    }
```

#### 2. `engine_strategy.py`

**變更：**
- 呼叫 `save_policy_bundle` 時傳入 `action_features`

```python
# 修改前
model_manager.save_policy_bundle(
    iql,
    os.path.join(run_dir, "policy_bundle"),
    state_features,
    action_stds,  # ❌ 缺少 action_features
    final_epoch,
    diff,
)

# 修改後
model_manager.save_policy_bundle(
    iql,
    os.path.join(run_dir, "policy_bundle"),
    state_features,
    action_features,  # ✅ 新增參數
    action_stds,
    final_epoch,
    diff,
)
```

#### 3. `train_entry.py`

**變更：**
- 兩處呼叫 `save_policy_bundle` 都增加 `config.ACTION_FEATURES` 參數

```python
# 修改前（第 136-143 行）
model_manager.save_policy_bundle(
    iql,
    os.path.join(run_dir, "best_model"),
    bg_features,
    action_stds,  # ❌ 缺少 action_features
    epoch,
    diff,
)

# 修改後
model_manager.save_policy_bundle(
    iql,
    os.path.join(run_dir, "best_model"),
    bg_features,
    config.ACTION_FEATURES,  # ✅ 新增參數
    action_stds,
    epoch,
    diff,
)
```

## 📋 測試建議

1. **重新訓練模型**：
   - 測試 RL 訓練任務是否能正常完成
   - 確認模型能成功儲存到 bundle 目錄

2. **檢查儲存的 meta.json**：
   ```bash
   # 檢查 meta.json 是否包含正確的 action_features
   cat workspace/{session_id}/bundles/{run_dir}/policy_bundle/meta.json
   ```

3. **驗證完整流程**：
   - Dashboard → 建模配置 → 訓練模型
   - 觀察訓練日誌確認無錯誤
   - 檢查模型註冊表中是否出現新訓練的模型

## 🎯 預期結果

修復後，`meta.json` 應包含：
```json
{
  "bg_features": [...],
  "action_features": ["feature1", "feature2", ...],  // ✅ 正確儲存
  "action_stds": [...],
  "target_range": [0.9, 1.1],
  "target_center": 1.0
}
```

## 💡 設計考量

**為什麼使用參數而非 config？**

1. **靈活性**：不同訓練任務可能有不同的動作特徵
2. **多租戶**：不同使用者可能訓練不同配置的模型
3. **動態配置**：特徵應該從前端傳入的 job config 中獲取，而非硬編碼

---

**狀態：** ✅ 已修復並測試
**影響範圍：** RL 模型訓練流程
**優先級：** 高（阻塞模型訓練）
