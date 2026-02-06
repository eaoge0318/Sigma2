# Y_LOW/Y_HIGH 從 JSON 讀取 - 修復完成

## 🎉 問題已修復!

### 問題描述

**錯誤訊息**: `AttributeError: module 'config' has no attribute 'Y_LOW'`

**原因**: 程式碼使用 `config.Y_LOW` 和 `config.Y_HIGH`,但這些值應該從 JSON 配置的 `goalSettings` (LSL/USL) 讀取。

### 修復內容

修改 `agent_logic.py`,從 JSON 配置讀取 LSL/USL 並儲存為實例變數:

#### 1. 在 `__init__` 中初始化 (第 25-26 行)
```python
self.y_low = getattr(config, "Y_LOW", 0)
self.y_high = getattr(config, "Y_HIGH", 1)
```

#### 2. 在 `reload_model` 中從 JSON 讀取 (第 156-165 行)
```python
# 讀取 goalSettings (LSL/USL)
goal_settings = job_conf.get("goalSettings") or job_conf.get("goal_settings")
if goal_settings:
    self.y_low = float(goal_settings.get("lsl", 0))
    self.y_high = float(goal_settings.get("usl", 1))
    print(f"   - Y range from JSON: [{self.y_low}, {self.y_high}]")
else:
    self.y_low = getattr(config, "Y_LOW", 0)
    self.y_high = getattr(config, "Y_HIGH", 1)
```

#### 3. 在 except 和 else 分支設定預設值 (第 175-176, 179-180 行)
```python
self.y_low = getattr(config, "Y_LOW", 0)
self.y_high = getattr(config, "Y_HIGH", 1)
```

#### 4. 在 `get_reasoned_advice` 中使用 (第 345 行)
```python
# 改為使用實例變數
is_locked = self.y_low <= current_y <= self.y_high
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
      - Y range from JSON: [1.7074, 2.2153]
   ```

5. **確認不再出現 AttributeError**

---

## 預期結果

✅ **Y 軸範圍從 JSON 讀取** (LSL/USL)
✅ **不再出現 config.Y_LOW 錯誤**
✅ **HOLD 邏輯正常運作** (在 LSL-USL 範圍內時維持現狀)
✅ **模擬正常執行**

---

## JSON 配置範例

```json
{
    "goalSettings": {
        "target": "2.0270",
        "usl": "2.2153",
        "lsl": "1.7074"
    }
}
```

**對應的 Y 軸範圍**:
- `self.y_low` = 1.7074 (LSL)
- `self.y_high` = 2.2153 (USL)

---

## 完整修復清單

✅ **IQL 特徵維度匹配** - 從 JSON 讀取 `actions`
✅ **Y 軸範圍動態設定** - 從 JSON 讀取 `goalSettings`
✅ **目標變數名稱** - 從 JSON 讀取 `goal`
✅ **綠色區塊顯示** - 使用 LSL/USL

**所有配置都從 JSON 讀取,不再依賴 config.py 的硬編碼值!**
