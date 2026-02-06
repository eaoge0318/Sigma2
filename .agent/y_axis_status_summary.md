# Y 軸配置問題總結

## 當前狀態

### ✅ 後端 - 完全正常
從 console 輸出可以確認:
```
[DEBUG] ✅ Goal column from model config: METROLOGY-P21-MO1-SP-2SIGMA
[DEBUG] ✅ Using goal column 'METROLOGY-P21-MO1-SP-2SIGMA' as measure: 2.369226
[DEBUG] Measure value: 2.369226
```

API 返回的數據結構:
```json
{
  "status": "HOLD",
  "current_measure": 2.369226,
  "target_range": [Y_LOW, Y_HIGH],
  "recommendations": [...],
  ...
}
```

### ❌ 前端 - 圖表未更新
- 圖表 Y 軸顯示範圍: 0-2.0
- 正確的數值應該是: 2.369226
- 問題: 前端沒有正確使用 `current_measure` 來繪製圖表

## 問題原因

前端 JavaScript 在處理 `/api/simulator/next` 的響應時,可能:
1. 使用了錯誤的欄位 (不是 `current_measure`)
2. 使用了舊的緩存數據
3. 圖表沒有正確更新

## 需要的資訊

要修正前端問題,需要知道:
1. 使用的是哪個頁面? (`dashboard.html` 的哪個功能?)
2. 圖表是如何繪製的? (Chart.js? ECharts?)
3. 處理 `/api/simulator/next` 響應的 JavaScript 程式碼在哪裡?

## 臨時解決方案

### 方案 1: 使用 test_simulator.html 驗證
1. 打開 `http://localhost:8001/test_simulator.html`
2. 選擇檔案
3. 選擇模型
4. 執行模擬
5. 查看 console 中的 API 響應,確認 `current_measure` 的數值

### 方案 2: 瀏覽器開發者工具檢查
1. 打開 dashboard 頁面
2. 按 F12 打開開發者工具
3. 切換到 Network 標籤
4. 執行模擬
5. 找到 `/api/simulator/next` 請求
6. 查看 Response,確認 `current_measure` 是否為 2.369226
7. 如果是,則問題在前端 JavaScript

### 方案 3: 清除緩存
1. 按 Ctrl + Shift + Delete
2. 清除瀏覽器緩存
3. 重新載入頁面
4. 重新執行模擬

## 下一步

需要找到前端處理模擬響應的 JavaScript 程式碼,並確保它正確使用 `result.current_measure` 來更新圖表。

可能的位置:
- `dashboard.html` 中的 `<script>` 標籤
- `static/js/dashboard_full.js`
- `static/js/modules/dashboard.js`

搜尋關鍵字:
- `/api/simulator/next`
- `current_measure`
- `chart.data.datasets`
- `.push(`
