# 即時看板 400 錯誤 - 快速修復指南

## 問題狀態
- ✅ Session ID: Mantle (正確)
- ❌ 錯誤: `loadSimulationFile is not defined`
- ❌ 結果: 400 Bad Request (檔案未載入)

## 根本原因
JavaScript 模組載入有時序問題。下拉選單的 `onchange` 事件在 dashboard 初始化之前就觸發了。

## 已修正
1. ✅ 添加延遲重試機制（500ms）
2. ✅ 添加錯誤處理和日誌
3. ✅ 改進初始化檢查

## 立即解決方案

### 方案 1：重新整理頁面（推薦）⭐

1. 按 `Ctrl + F5` 強制重新整理頁面（清除快取）
2. 等待頁面完全載入（看到所有選單都正常）
3. 選擇檔案 → 選擇模型 → Run Simulation

### 方案 2：使用瀏覽器 Console 手動載入

如果方案 1 還是有問題，請在瀏覽器 Console (F12) 執行：

```javascript
// 1. 檢查初始化狀態
console.log('Dashboard Ready:', window.Sigma2?.dashboard ? 'YES' : 'NO');

// 2. 如果 Dashboard Ready 是 NO，等待並重試
await new Promise(r => setTimeout(r, 1000));
console.log('Dashboard Ready (after wait):', window.Sigma2?.dashboard ? 'YES' : 'NO');

// 3. 手動載入檔案
const fileSelect = document.getElementById('dashboard-file-select');
const modelSelect = document.getElementById('dashboard-model-select');

if (window.Sigma2?.dashboard) {
    // 載入檔案
    const filename = fileSelect.value;
    console.log('Loading file:', filename);
    await window.Sigma2.dashboard.loadSimulationFile(filename);
    
    // 載入模型
    const modelPath = modelSelect.value;
    console.log('Loading model:', modelPath);
    await window.Sigma2.dashboard.loadModel(modelPath);
    
    console.log('✅ Both loaded successfully');
} else {
    console.error('❌ Dashboard still not ready');
}
```

### 方案 3：檢查後端日誌

在後端終端查看是否有這些訊息：

**成功載入檔案：**
```
INFO: Session Mantle 載入模擬檔案: XXX.csv (N rows)
```

**成功載入模型：**
```
✅ RL Model: Loaded config job_xxx.json pointing to ...
✅ Prediction Model: Using run_path from config: ...
```

**如果沒有這些訊息**，表示前端調用沒有送達後端。

## 預期正常流程

### 1. 選擇檔案時
- **前端**: `loadSimulationFile("xxx.csv")` 被調用
- **後端**: 收到 `/api/simulator/load_file` 請求
- **日誌**: `Session Mantle 載入模擬檔案: xxx.csv (244 rows)`
- **提示**: 彈出 "已載入模擬檔案: xxx.csv (244 筆數據)"

### 2. 選擇模型時
- **前端**: `loadModel("job_xxx.json")` 被調用
- **後端**: 收到 `/api/model/load` 請求
- **日誌**: 
  ```
  ✅ RL Model: Loaded config ...
  ✅ Prediction Model: Using run_path ...
  AgenticReasoning: Session Mantle models reloaded successfully
  ```

### 3. 點擊 Run Simulation
- **前端**: `runFullSimulation()` 被調用
- **後端**: 收到 `/api/simulator/next` 請求
- **日誌**: 正常的推理日誌
- **結果**: 即時看板更新數據

## 診斷檢查清單

請逐項檢查並回報：

- [ ] 1. 強制重新整理頁面 (Ctrl+F5)
- [ ] 2. Console 顯示 "Dashboard Ready: YES"
- [ ] 3. 檔案下拉選單有選項（非"載入中..."）
- [ ] 4. 模型下拉選單有選項（非"載入中..."）
- [ ] 5. 選擇檔案後看到「已載入」提示
- [ ] 6. 選擇模型後看到「載入成功」提示或後端日誌
- [ ] 7. 後端終端有看到檔案載入日誌
- [ ] 8. 後端終端有看到模型載入日誌
- [ ] 9. 點擊 Run Simulation 沒有 400 錯誤
- [ ] 10. 即時看板成功顯示數據

## 如果還是有問題

請提供以下資訊：

1. **Console 輸出**（完整的錯誤訊息）
2. **後端日誌**（最近 20 行）
3. **哪些檢查清單項目失敗**

這樣我就能準確定位問題。

## 臨時解決方案

如果上述方法都不work，可以嘗試在 dashboard.html 的末尾添加這段代碼：

```javascript
// 確保 dashboard 初始化後才啟用下拉選單
document.addEventListener('DOMContentLoaded', () => {
    const fileSelect = document.getElementById('dashboard-file-select');
    const modelSelect = document.getElementById('dashboard-model-select');
    
    if (fileSelect) fileSelect.disabled = true;
    if (modelSelect) modelSelect.disabled = true;
    
    // 等待 dashboard 初始化
    const checkInit = setInterval(() => {
        if (window.Sigma2?.dashboard) {
            clearInterval(checkInit);
            if (fileSelect) fileSelect.disabled = false;
            if (modelSelect) modelSelect.disabled = false;
            console.log('✅ Dashboard controls enabled');
        }
    }, 100);
});
```

這會在 dashboard 初始化完成前禁用下拉選單，避免時序問題。
