# 最終修正：移除 onchange 屬性，使用事件監聽器

## 問題根源
HTML 中的 `onchange="loadSimulationFile(this.value)"` 在頁面載入時立即執行，但此時 JavaScript 模組還沒載入完成，導致：
```
Uncaught ReferenceError: loadSimulationFile is not defined
```

## 解決方案

### 1. 修改 HTML：移除 onchange 屬性
**檔案**: `dashboard.html` (第 990-1003 行)

**修改前**:
```html
<select id="dashboard-file-select" onchange="loadSimulationFile(this.value)" ...>
<select id="dashboard-model-select" onchange="loadModel(this.value)" ...>
```

**修改後**:
```html
<select id="dashboard-file-select" ...>
<select id="dashboard-model-select" ...>
```

### 2. JavaScript 添加事件監聽器
**檔案**: `static/js/modules/dashboard.js` (第 186-217 行)

**新增內容**:
```javascript
async initDashboardControls() {
    console.log("Initializing Dashboard Controls...");
    
    // 綁定下拉選單的事件監聽器
    const fileSelect = document.getElementById('dashboard-file-select');
    const modelSelect = document.getElementById('dashboard-model-select');
    
    if (fileSelect) {
        fileSelect.addEventListener('change', (e) => {
            const filename = e.target.value;
            if (filename) {
                console.log('File selected:', filename);
                this.loadSimulationFile(filename);
            }
        });
    }
    
    if (modelSelect) {
        modelSelect.addEventListener('change', (e) => {
            const modelPath = e.target.value;
            if (modelPath) {
                console.log('Model selected:', modelPath);
                this.loadModel(modelPath);
            }
        });
    }
    
    console.log('✅ Event listeners attached');
    
    await this.fetchFileList();
    await this.fetchModelList();
}
```

## 優勢

### 修改前（onchange 屬性）
- ❌ 執行時間：頁面載入時
- ❌ 模組狀態：可能還沒載入
- ❌ 結果：ReferenceError

### 修改後（addEventListener）
- ✅ 執行時間：dashboard 初始化後（延遲 1 秒）
- ✅ 模組狀態：已完全載入
- ✅ 結果：正常工作
- ✅ 附加功能：Console 日誌追蹤

## 測試步驟

1. **強制重新整理頁面** (Ctrl + F5)
2. **檢查 Console 輸出**，應該看到：
   ```
   Initializing Dashboard Controls...
   ✅ Event listeners attached
   ```
3. **選擇檔案**，應該看到：
   ```
   File selected: xxx.csv
   ```
   並彈出提示：「已載入模擬檔案: xxx.csv (N 筆數據)」

4. **選擇模型**，應該看到：
   ```
   Model selected: job_xxx.json
   ```
   後端日誌顯示：
   ```
   ✅ RL Model: Loaded config job_xxx.json pointing to ...
   ✅ Prediction Model: Using run_path from config: ...
   ```

5. **點擊 Run Simulation**
   - ❌ 如果還有 400 錯誤 → 檔案沒有正確載入
   - ✅ 如果正常 → 問題解決！

## 預期 Console 輸出（完整流程）

```
# 頁面載入
Initializing Dashboard Controls...
✅ Event listeners attached

# 選擇檔案
File selected: KL00_0411_ALL_4.csv

# 選擇模型
Model selected: job_7ba3af9e.json

# 點擊 Run Simulation
Session ID: Mantle
(正常的推理日誌...)
```

## 如果還是有問題

請提供完整的 Console 輸出，特別是：
- 是否看到 "✅ Event listeners attached"
- 選擇檔案/模型時的日誌
- 任何錯誤訊息

## 技術說明

這個修正採用了 **事件委派** 和 **延遲初始化** 的模式：

1. **HTML 保持簡潔**：只有 id，沒有內聯事件處理器
2. **JavaScript 控制邏輯**：在模組載入後綁定事件
3. **時序保證**：`setTimeout(..., 1000)` 確保 DOM 和模組都已就緒
4. **錯誤隔離**：event listener 中的錯誤不會影響頁面載入

這是現代 Web 開發的最佳實踐，比內聯 `onchange` 更可靠、更易維護。
