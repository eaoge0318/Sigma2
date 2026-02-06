"""
診斷腳本：檢查即時看板 400 錯誤的原因

使用方法：
1. 在瀏覽器開啟即時看板
2. 打開瀏覽器的開發者工具（F12）
3. 切換到 Console 標籤
4. 執行以下 JavaScript 代碼來檢查狀態
"""

# ============ 前端診斷（在瀏覽器 Console 執行）============

"""
// 1. 檢查當前 session ID
console.log('Session ID:', window.Sigma2?.session?.getSessionId());

// 2. 檢查檔案選擇狀態
const fileSelect = document.getElementById('dashboard-file-select');
console.log('Selected File:', fileSelect?.value);

// 3. 檢查模型選擇狀態
const modelSelect = document.getElementById('dashboard-model-select');
console.log('Selected Model:', modelSelect?.value);

// 4. 手動測試載入檔案
async function testLoadFile() {
    const filename = fileSelect.value;
    if (!filename) {
        console.error('❌ 未選擇檔案');
        return;
    }
    
    const response = await fetch('/api/simulator/load_file', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            filename: filename,
            session_id: window.Sigma2?.session?.getSessionId() || 'default'
        })
    });
    const result = await response.json();
    console.log('Load File Result:', result);
}

// 執行測試
testLoadFile();

// 5. 手動測試載入模型
async function testLoadModel() {
    const modelPath = modelSelect.value;
    if (!modelPath) {
        console.error('❌ 未選擇模型');
        return;
    }
    
    const response = await fetch('/api/model/load', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            model_path: modelPath,
            session_id: window.Sigma2?.session?.getSessionId() || 'default'
        })
    });
    const result = await response.json();
    console.log('Load Model Result:', result);
}

// 執行測試
testLoadModel();
"""

# ============ 後端診斷（檢查項目）============

"""
檢查清單：

□ 1. Session ID 是否正確
   - 前端使用的 session_id
   - 後端收到的 session_id
   - 兩者是否一致

□ 2. 檔案是否已載入
   - session.sim_df 是否為 None
   - session.sim_file_name 是什麼
   - session.sim_index 是多少

□ 3. 模型是否已載入
   - agent.iql_algo 是否存在
   - agent.simulator 是否存在
   - agent.simulator.model 是否存在

□ 4. 檔案路徑問題
   - 上傳的檔案是否在正確的目錄
   - user_uploads/[session_id]/ 是否存在
   - 檔案權限是否正確

□ 5. 前端操作順序
   - 是否先選擇檔案
   - 是否等待檔案載入完成
   - 是否先選擇模型
   - 是否等待模型載入完成
"""

# ============ 建議的修正步驟 ============

"""
步驟 1：確認前端選擇
-----------------------
在即時看板頁面：
1. 確認「檔案選擇」下拉選單有值
2. 確認「模型選擇」下拉選單有值
3. 兩者都選擇後再點擊 Run Simulation

步驟 2：手動載入測試
-----------------------
在瀏覽器 Console 執行：
1. 先執行 testLoadFile() 確認檔案載入
2. 再執行 testLoadModel() 確認模型載入
3. 檢查回應是否都是 success

步驟 3：檢查後端日誌
-----------------------
查看後端終端輸出，尋找：
1. "Session XXX 載入模擬檔案" 訊息
2. "RL Model: Loaded config" 訊息
3. "Prediction Model: Using run_path" 訊息
4. 任何錯誤訊息或警告

步驟 4：檢查 Session 狀態
-----------------------
如果問題仍存在，可能是 session_id 不一致。
前端和後端使用的 session_id 必須相同。

常見問題：
- 前端使用 "Mantle"
- 後端收到 "default"
- 導致 session.sim_df 為 None
"""

print(__doc__)
