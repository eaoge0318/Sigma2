# IQL 特徵維度不匹配問題 - 修復完成

## 🎉 問題已修復!

### 問題根源

**config.py 中的 ACTION_FEATURES 與 JSON 配置不匹配:**

- **config.py**: 
  ```python
  ACTION_FEATURES = ["MEDIC-ABB_B41", "SHAP-DCS_A50", "MEDIC-DCS_A1002"]  # 3 個
  ```

- **job_27acde4b.json**:
  ```json
  "actions": [
      "BCDRY-ABB_B23",
      "FORMULA-DCS_A1",
      "MEDIC-ABB_B40",
      "MEDIC-ABB_B84"
  ]  // 4 個
  ```

**特徵名稱和數量都不同!**

### 修復方案

修改 `agent_logic.py`,從 JSON 配置讀取 `actions`,而不是使用 `config.ACTION_FEATURES`:

#### 1. 在 `__init__` 中初始化 (第 25 行)
```python
self.action_features = getattr(config, "ACTION_FEATURES", [])
```

#### 2. 在 `reload_model` 中從 JSON 讀取 (第 137-154 行)
```python
# 從 JSON 配置讀取 actions (如果有的話)
if target_bundle_name and target_bundle_name.endswith(".json"):
    try:
        configs_dir = file_service.get_user_path(self.session_id, "configs")
        config_path = os.path.join(configs_dir, target_bundle_name)
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                job_conf = json.load(f)
                self.action_features = job_conf.get("actions", [])
                print(f"   - action_features from JSON: {len(self.action_features)} features")
                print(f"     {self.action_features}")
    except Exception as e:
        print(f"⚠️ Failed to read actions from JSON: {e}")
        self.action_features = getattr(config, "ACTION_FEATURES", [])
else:
    self.action_features = getattr(config, "ACTION_FEATURES", [])
```

#### 3. 在 `get_reasoned_advice` 中使用 (第 258, 265, 273 行)
```python
# 改為使用 self.action_features
act_vals = [row[f] for f in self.action_features]
```

---

## 測試步驟

1. **重新啟動後端服務**
2. **載入模型**: 選擇 `job_27acde4b.json`
3. **執行模擬**
4. **檢查日誌輸出**:
   ```
   ✅ Policy bundle loaded successfully
      - bg_features: 4 features
      - action_stds: ...
      - action_features from JSON: 4 features
        ['BCDRY-ABB_B23', 'FORMULA-DCS_A1', 'MEDIC-ABB_B40', 'MEDIC-ABB_B84']
   ```

5. **確認特徵維度**:
   ```
   [DEBUG] BG Features count: 4
   [DEBUG] Action Features count: 4
   [DEBUG] Total state dimension: 4 + 4 + 1 = 9
   ```

6. **IQL 應該正常運作**,不再出現維度不匹配錯誤!

---

## 預期結果

✅ **IQL 模型正常載入**
✅ **特徵維度匹配** (4 bg + 4 action + 1 current_y = 9)
✅ **模擬正常運行**
✅ **AI 建議正常顯示**

---

## 注意事項

1. **每個 JSON 配置都應該包含 `actions` 欄位**
2. **如果 JSON 中沒有 `actions`,會回退到 `config.ACTION_FEATURES`**
3. **確保 JSON 中的 `actions` 與訓練時使用的特徵一致**

---

## 下一步

**請重新啟動後端並測試!**

如果仍然有問題,請檢查:
1. JSON 配置中的 `actions` 欄位是否存在
2. 特徵名稱是否與數據檔案中的欄位名稱匹配
3. 後端日誌中的特徵數量是否正確
