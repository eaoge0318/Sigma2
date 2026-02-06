# 即時看板改進摘要

## 修改日期
2026-02-03

## 問題說明

用戶提出了兩個關於即時看板頁面的問題：

1. **模型命名一致性**：希望即時看板的模型名稱格式與「既有模型」（Universal Loader）保持一致
2. **移除 config.py 依賴**：不再使用 config.py 中的歷史資料配置（RAW_DATA_PATH、MEASURE_COL、ACTION_FEATURES、Y_LOW、Y_HIGH 等）

## 實施的修改

### 1. 後端修改 (`backend/routers/dashboard_router.py`)

#### 移除對 config.py 的依賴
- **修改位置**：`/api/simulator/next` EndPoint (第94-145行)
- **變更內容**：
  - 移除自動載入 `config.RAW_DATA_PATH` 預設檔案的功能
  - 如果 session 沒有載入模擬資料，直接返回 400 錯誤並提示用戶選擇檔案
  - 移除對 `config.MEASURE_COL` 的硬編碼依賴
  - 添加智能檢測邏輯：自動尋找包含 "std" 或 "measure" 的欄位作為測量值
  - 如果沒有明確的測量欄位，使用第一個可轉換為浮點數的欄位

#### 移除未使用的 import
- 移除 `from typing import Dict, Any`（修復 lint 警告）

#### 保留的功能
- `/api/simulator/models` EndPoint 已經正確返回物件格式（包含 id, name, timestamp）
- 模型命名格式已經與 Universal Loader 保持一致

### 2. 前端修改 (`static/js/modules/dashboard.js`)

#### 改進模型列表顯示
- **修改位置**：`fetchModelList()` 函數（第192-220行）
- **變更內容**：
  - 正確處理後端返回的物件格式（`{id, name, timestamp}`）
  - 支持向後相容舊的字串格式
  - 顯示完整的模型資訊（包含 R2 分數和時間戳）

### 3. HTML 確認 (`dashboard.html`)

#### 備援腳本已就位
- 第 2474-2493 行的備援腳本已經正確處理物件格式
- 支持新舊格式的兼容性

## 技術細節

### 自動檢測測量欄位的邏輯
```python
# 優先級 1: 尋找包含 "std" 或 "measure" 的欄位
measure_col_candidates = [col for col in row.index if "std" in col.lower() or "measure" in col.lower()]
if measure_col_candidates:
    measure_value = float(row[measure_col_candidates[0]])

# 優先級 2: 使用第一個可轉換為浮點數的欄位
elif len(row.index) > 0:
    for col in row.index:
        try:
            measure_value = float(row[col])
            break
        except (ValueError, TypeError):
            continue
```

### 模型名稱格式示例
根據上傳的截圖，模型命名格式為：
- `Model_KL00_041_22_1818`
- 包含 R2 分數和時間戳的完整顯示：`Model_KL00_041_22_1818 | 2026/02/03 23:24:47`

## 使用方式

### 即時看板操作流程

1. **選擇模擬檔案**：
   - 在即時看板頁面的 SIMULATOR 區域
   - 從「檔案選擇」下拉選單中選擇要模擬的 CSV 檔案
   - 系統會自動載入該檔案

2. **選擇模型**：
   - 從「模型選擇」下拉選單中選擇訓練好的模型
   - 顯示格式：`模型名稱 | R2: 分數 | 時間戳`

3. **開始模擬**：
   - 點擊「Run Simulation」按鈕開始模擬
   - 或使用「Auto Play」自動播放模式

## 錯誤處理

### 未選擇檔案時的提示
如果用戶未選擇模擬檔案就嘗試運行模擬，系統會顯示：
```
請先選擇模擬檔案。請在即時看板頁面的 SIMULATOR 區域選擇要模擬的檔案。
```

## 影響範圍

### 受影響的檔案
1. `backend/routers/dashboard_router.py`
2. `static/js/modules/dashboard.js`

### 不受影響的功能
- 模型訓練功能
- 檔案上傳和管理
- 數據分析和圖表
- AI 助手功能

## 向後兼容性

- ✅ 支持舊格式的模型列表（字串陣列）
- ✅ 支持新格式的模型列表（物件陣列）
- ✅ 自動檢測測量欄位，適應不同的資料結構

## 測試建議

1. 上傳新的 CSV 檔案到檔案管理
2. 訓練新的模型
3. 在即時看板中選擇該檔案和模型
4. 驗證模型名稱顯示格式是否與 Universal Loader 一致
5. 測試模擬功能是否正常運作

## 注意事項

- ⚠️ 不再支持自動載入 `KL00_0411_ALL_3.csv` 等預設檔案
- ⚠️ 用戶必須明確選擇要模擬的檔案
- ✅ 這提高了系統的靈活性和可維護性
- ✅ 減少了對歷史配置的依賴
