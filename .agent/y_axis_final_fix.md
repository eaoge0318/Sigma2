# Y 軸配置功能 - 最終修正

## 問題發現

從 API 響應中發現:
```json
{
  "current_measure": 2.467593,  // ✅ 正確
  "target_range": [0, 1.1]      // ❌ 錯誤!應該是 [0, 2.0]
}
```

而 `job_7ba3af9e.json` 中定義的是:
```json
{
  "goalSettings": {
    "target": "1",
    "usl": "2.0",
    "lsl": "0"
  }
}
```

## 根本原因

`prediction_service.py` 的 `predict` 方法中,`target_range` 使用了 `config.py` 的固定值:
```python
"target_range": [config.Y_LOW, config.Y_HIGH]  # [0, 1.1]
```

而不是從 `job_xxx.json` 的 `goalSettings` 中讀取。

前端圖表使用 `target_range` 來設定 Y 軸範圍,所以即使 `current_measure` 是正確的 2.467593,圖表的 Y 軸範圍仍然被限制在 [0, 1.1],導致自動擴展到 0-2.0。

## 解決方案

修改 `backend/services/prediction_service.py` 的 `predict` 方法:

1. 從 `session.current_model_config` 中讀取 `goalSettings`
2. 提取 `lsl` 和 `usl` 作為 `target_range`
3. 如果無法讀取,則回退到 `config.py` 的預設值

```python
# 從 session 的 current_model_config 中讀取 target_range
target_range = [config.Y_LOW, config.Y_HIGH]  # 預設值

# 嘗試從 session 中獲取 goalSettings
dashboard_session = self.session_service.get_dashboard_session(session_id)
if hasattr(dashboard_session, 'current_model_config') and dashboard_session.current_model_config:
    goal_settings = dashboard_session.current_model_config.get('goalSettings') or dashboard_session.current_model_config.get('goal_settings')
    if goal_settings:
        try:
            lsl = float(goal_settings.get('lsl', config.Y_LOW))
            usl = float(goal_settings.get('usl', config.Y_HIGH))
            target_range = [lsl, usl]
            logger.info(f"Using target_range from model config: {target_range}")
        except (ValueError, TypeError) as e:
            logger.warning(f"Failed to parse goalSettings, using default: {e}")
```

## 修改的檔案

1. **`backend/models/session_models.py`**
   - 新增 `current_model_config` 屬性到 `DashboardSession`

2. **`backend/routers/dashboard_router.py`**
   - `load_specific_model`: 載入 `job_xxx.json` 並儲存到 session
   - `simulator_next`: 從 session 中讀取 `goal` 欄位作為 Y 軸數據

3. **`backend/services/prediction_service.py`**
   - `predict`: 從 session 中讀取 `goalSettings` 作為 `target_range`

4. **`api_entry.py`**
   - 修正向後相容路由,傳遞所有必要的服務依賴

5. **`agent_logic.py`**
   - 新增 IQL 維度不匹配的錯誤處理

## 預期結果

執行模擬後,API 應該返回:
```json
{
  "current_measure": 2.467593,
  "target_range": [0, 2.0],  // ✅ 正確!
  ...
}
```

前端圖表的 Y 軸範圍應該顯示 0-2.0,並正確繪製 2.467593 的數據點。

## 測試步驟

1. 重新啟動伺服器
2. 載入模型 (`job_7ba3af9e.json`)
3. 載入模擬檔案
4. 執行模擬
5. 檢查:
   - Console 中應顯示: `Using target_range from model config: [0.0, 2.0]`
   - API 響應中 `target_range` 應為 `[0, 2.0]`
   - 圖表 Y 軸範圍應為 0-2.0
   - 數據點應正確顯示在 2.467593 附近

## 狀態

✅ **所有修改已完成**
- Y 軸數據來源: 使用 `job_xxx.json` 的 `goal` 欄位
- Y 軸範圍: 使用 `job_xxx.json` 的 `goalSettings` (LSL/USL)
- 錯誤處理: IQL 維度不匹配時跳過推理
- 向後相容: 修正 API 路由的依賴注入

請重新啟動伺服器並測試!
