# 即時看板改進摘要（更新版）

## 修改日期
2026-02-04 00:05

## 問題修正

### 問題 1：模型名稱顯示錯誤
**現象**：下拉選單顯示 `job_7ba3af9e.json | 2026/02/03 23:37:36` 而非模型名稱

**根本原因**：
- 後端代碼在 JSON 中查找 `job_name` 欄位
- 實際 JSON 檔案使用的欄位是 `model_name` 或 `modelName`

**解決方案**：
```python
# 修改前
job_name = data.get("job_name", f)

# 修改後
model_name = data.get("model_name") or data.get("modelName") or f
r2 = data.get("r2")
r2_text = f"R2: {r2:.4f}" if r2 is not None else "N/A"
created = data.get("created_at", "")

if created:
    display_name = f"{model_name} | {r2_text} | {created}"
else:
    display_name = f"{model_name} | {r2_text}"
```

**預期顯示格式**：
- `Model_KL00_041_22_1818 | R2: 0.3516 | 2026/02/03 23:37:36`

### 問題 2：按下模擬後出現 400 錯誤
**現象**：
```
INFO: 10.10.91.3:57425 - "POST /api/simulator/next HTTP/1.1" 400 Bad Request
```

**根本原因**：
- 移除 config.py 依賴時，也移除了自動載入預設檔案的功能
- 用戶未選擇模擬檔案就點擊 "Run Simulation"
- 前端沒有正確處理 HTTP 400 錯誤，導致錯誤訊息不可見

**解決方案**：

1. **後端改進**（已在前一次修改中完成）：
```python
# /api/simulator/next endpoint
if session.sim_df is None:
    raise HTTPException(
        400,
        detail="請先選擇模擬檔案。請在即時看板頁面的 SIMULATOR 區域選擇要模擬的檔案。",
    )
```

2. **前端錯誤處理**：
```javascript
// triggerSimulatorNext() 函數
if (!response.ok) {
    const errorData = await response.json();
    const errorMsg = errorData.detail || '模擬器執行失敗';
    alert(errorMsg);
    this.stopAutoPlay();
    return;
}
```

3. **前置檢查**：
```javascript
// runFullSimulation() 函數
const fileSelect = document.getElementById('dashboard-file-select');
const modelSelect = document.getElementById('dashboard-model-select');

if (!fileSelect.value) {
    alert('⚠️ 請先選擇模擬檔案');
    return;
}

if (!modelSelect.value) {
    alert('⚠️ 請先選擇模型');
    return;
}
```

## 已修改的檔案

### 1. `backend/routers/dashboard_router.py`
- **第 189-265 行**：`/api/simulator/models` endpoint
  - 修正讀取 `model_name` 欄位（而非 `job_name`）
  - 添加 R2 分數顯示
  - 改善錯誤日誌記錄

- **第 94-145 行**：`/api/simulator/next` endpoint（前次修改）
  - 移除對 `config.RAW_DATA_PATH` 的依賴
  - 移除對 `config.MEASURE_COL` 的依賴
  - 添加智能測量欄位檢測

### 2. `static/js/modules/dashboard.js`
- **第 13-42 行**：`triggerSimulatorNext()` 函數
  - 添加 HTTP 錯誤處理
  - 顯示詳細錯誤訊息
  - 錯誤時停止自動播放

- **第 33-68 行**：`runFullSimulation()` 函數
  - 添加檔案選擇檢查
  - 添加模型選擇檢查
  - 提供清晰的用戶提示

## JSON 檔案結構示例

```json
{
    "modelName": "Model_KL00_041_22_1818",
    "model_name": "Model_KL00_041_22_1818",
    "filename": "KL00_0411_ALL_4_filtered.csv",
    "missionType": "rl",
    "type": "rl",
    "goal": "METROLOGY-P21-MO1-SP-2SIGMA",
    ...
    "job_id": "job_7ba3af9e",
    "session_id": "Mantle",
    "created_at": "2026/02/03 23:37:36",
    "status": "completed",
    "r2": 0.3516063094139099,
    "mae": 0.09528383612632751,
    ...
}
```

## 使用流程（修正後）

### 正確的操作步驟：

1. **選擇模擬檔案**：
   - 點擊「檔案選擇」下拉選單
   - 選擇要模擬的 CSV 檔案
   - 系統自動載入檔案

2. **選擇模型**：
   - 點擊「模型選擇」下拉選單
   - 看到格式：`Model_KL00_041_22_1818 | R2: 0.3516 | 2026/02/03 23:37:36`
   - 選擇要使用的模型

3. **開始模擬**：
   - 點擊「🚀 Run Simulation」按鈕
   - 或使用 Auto Play 自動播放

### 錯誤提示：

- **未選擇檔案**：顯示 "⚠️ 請先選擇模擬檔案"
- **未選擇模型**：顯示 "⚠️ 請先選擇模型"
- **無可用檔案**：下拉選單顯示 "無可用檔案"
- **無可用模型**：下拉選單顯示 "無可用模型"

## 測試確認項目

- [x] 模型列表正確顯示模型名稱（非 job_id）
- [x] 模型列表包含 R2 分數
- [x] 模型列表包含建立時間
- [x] 未選擇檔案時顯示清晰錯誤訊息
- [x] 未選擇模型時顯示清晰錯誤訊息
- [x] HTTP 400 錯誤正確傳遞到前端
- [x] 自動播放在錯誤時正確停止

## 技術改進

### 1. 智能欄位檢測
```python
# 自動檢測測量欄位
measure_col_candidates = [
    col for col in row.index 
    if "std" in col.lower() or "measure" in col.lower()
]
```

### 2. 多重後援機制
```python
# 模型名稱讀取
model_name = data.get("model_name") or data.get("modelName") or f
```

### 3. 完整錯誤處理
```javascript
// 檢查 HTTP 狀態碼
if (!response.ok) {
    const errorData = await response.json();
    const errorMsg = errorData.detail || '模擬器執行失敗';
    alert(errorMsg);
    this.stopAutoPlay();
    return;
}
```

## 兼容性

- ✅ 支持 `model_name` 和 `modelName` 欄位
- ✅ 支持有無 R2 分數的模型
- ✅ 支持有無時間戳的模型
- ✅ 向後兼容舊的模型檔案格式

## 注意事項

⚠️ **重要變更**：
- 模擬器不再自動載入預設檔案
- 用戶必須明確選擇檔案和模型
- 這提高了系統的可控性和安全性

✅ **改進成果**：
- 模型名稱顯示符合用戶期望
- 錯誤訊息清晰易懂
- 用戶體驗更加友好
- 系統更加穩定可靠
