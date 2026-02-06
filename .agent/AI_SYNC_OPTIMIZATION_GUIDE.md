# AI 助手視窗同步與效能優化完全指南 (Comprehensive AI Sync & Optimization Guide)

**版本**: 1.0  
**日期**: 2026-02-05  
**專案**: Sigma2 Agentic Reasoning System

本指南提供了關於解決「前後端卡頓」、「跨視窗同步」以及「LLM 生成圖表渲染」的完整技術細節。
當未來需要維護或重新實作 AI 助手功能時，請以此文件為核心參考標準。

---

## 1. 後端架構優化 (Backend Architecture)

### 核心問題：GIL 阻塞 (The Blocking Problem)
Python 的 Global Interpreter Lock (GIL) 限制了同一時間只能有一個執行緒執行 Python Bytecode。
FastAPI 雖然是異步 (Async) 框架，但如果在 `async def` 路徑中直接呼叫同步函數（例如 `requests.post` 去呼叫 LLM API），整個 Event Loop 會被該函數**卡死**，直到它返回為止。這會導致伺服器無法回應任何其他請求（如前端的 `Simulate` 狀態查詢或圖表更新）。

### ✅ 解決方案：Thread Offloading
必須使用 `asyncio.to_thread` 將同步的 CPU/IO 密集型任務移至背景執行緒池。

#### 程式碼範例 (`backend/services/ai_service.py`)

```python
import asyncio

class AIService:
    def __init__(self):
        # 假設 LLMReporter 內部使用 requests (同步庫)
        self.llm_worker = LLMReporter()

    async def chat_with_expert(self, messages, context_data):
        """
        異步接口：將阻塞操作移交給線程池
        """
        # ❌ 錯誤：這會卡住伺服器 5~10 秒
        # reply = self.llm_worker.chat_with_expert(messages, context_data)

        # ✅ 正確：在獨立線程運行，主線程可繼續處理其他 API
        reply = await asyncio.to_thread(
            self.llm_worker.chat_with_expert, 
            messages, 
            context_data
        )
        return {"reply": reply}

    async def generate_report(self, history_data):
        # 同樣適用於報告生成
        report_content = await asyncio.to_thread(
            self.llm_worker.generate_report, 
            history_data
        )
        return {"report": report_content}
```

### 🛡️ 防禦性編碼：處理 Coroutine 錯誤
當程式碼在同步/異步之間切換時，容易出現 `TypeError: 'coroutine' object is not iterable` (500 Error)。這通常是因為在 Router 中返回了未 Await 的 Coroutine。

#### 程式碼範例 (`backend/routers/ai_router.py`)

```python
import asyncio

@router.get("/report_status/{job_id}")
async def get_report_status(job_id: str):
    job = ai_jobs.get(job_id)
    if not job:
        return {"status": "not_found"}

    if job["status"] == "completed":
        result = job["result"].get("report", "")
        
        # 🛡️ 防禦性檢查：如果不小心存入了 coroutine 對象，嘗試補救
        if asyncio.iscoroutine(result):
            try:
                result = await result
            except Exception as e:
                result = str(e)
                
        return {"status": "completed", "report": result}
```

---

## 2. 前端跨視窗同步 (Frontend Window Sync)

### 核心問題：DOM 操作凍結 (UI Freeze)
若試圖從主視窗腳本直接操作彈出視窗的 DOM（或由彈出視窗操作主視窗），例如 `window.opener.document.getElementById(...)`，會觸發瀏覽器極其昂貴的跨 Context 渲染同步，導致 UI 畫面瞬間凍結。

### ✅ 解決方案：輕量級訊息傳遞 (Message Passing)
建立「發送者-接收者」模型。只傳遞純數據 (JSON)，渲染邏輯由各視窗自己負責。

#### A. 主視窗接收器 (`static/js/dashboard_full.js`)
在主視窗掛載一個全局函數，供彈出視窗呼叫。

```javascript
window.receivePopupMessage = function (msg) {
    // 1. 更新數據模型
    chatMessages.push(msg);

    // 2. 異步 UI 更新 (避免阻塞主線程)
    requestAnimationFrame(() => {
        const content = document.getElementById('ai-report-content');
        const bubble = document.createElement('div');
        // ... 構建 bubble HTML ...
        
        if (msg.role === 'assistant') {
            bubble.innerHTML = marked.parse(msg.content);
            // 3. 延遲圖表渲染 (關鍵：不卡住即時文字顯示)
            setTimeout(() => {
                renderChartsInBubble(bubble); // 詳見第 3 節
            }, 100);
        }
        content.appendChild(bubble);
        content.scrollTop = content.scrollHeight;
    });
};
```

#### B. 彈出視窗發送器 (`static/dashboard_ai_popup.html`)
當彈出視窗收到 AI 回覆時，除了自己顯示，也同步給主視窗。

```javascript
function appendMessage(role, content, images) {
    // ... 在彈出視窗顯示 ...

    // 同步回主視窗
    if (window.opener && !window.opener.closed && window.opener.receivePopupMessage) {
        const msg = { role: role, content: content, images: images };
        window.opener.receivePopupMessage(msg);
    }
}
```

#### C. Session 身份同步
確保兩邊視窗讀寫同一份後端數據。

**主視窗 (`dashboard_full.js`):**
```javascript
const SESSION_ID = getSessionId();
window.SESSION_ID = SESSION_ID; // 必須顯式暴露
```

**彈出視窗 (`popup.html`):**
```javascript
// 嘗試繼承，失敗則新建
const SESSION_ID = (window.opener && window.opener.SESSION_ID) 
                 ? window.opener.SESSION_ID 
                 : 'popup_' + Date.now();
```

---

## 3. 圖表渲染核心邏輯 (Robust Chart Engine)

### 核心問題：數據格式與樣式不一致
LLM 返回的 JSON 通常很簡陋（例如兩組 Array，沒有標籤）。Chart.js 直接吃這些數據會畫不出圖（Scatter 需要 `{x,y}`）或很醜（無線條、無填充）。

### ✅ 解決方案：智慧圖表增強代碼
這段代碼必須同時存在於 `dashboard_full.js` 和 `popup.html` 中，確保兩邊看到的圖表一致且美觀。

```javascript
function renderChartsInBubble(container) {
    const codeBlocks = container.querySelectorAll('pre code');
    codeBlocks.forEach(block => {
        try {
            const config = JSON.parse(block.innerText);
            if (config.type !== 'chart') return;

            // 隱藏原始 JSON，創建 Canvas
            block.parentElement.style.display = 'none';
            const canvas = document.createElement('canvas');
            // ... (設置容器樣式 width/height) ...
            
            // --- 核心邏輯開始 ---
            if (!config.datasets || !config.datasets[0]) return;

            let chartType = config.chart_type || 'line';
            let chartData = { datasets: [] };
            let chartOptions = config.options || {};
            
            // 1. 自動偵測 Scatter (當有兩組數據但沒有 Label 時)
            const hasTwoDatasets = config.datasets.length >= 2;
            const missingLabels = !config.labels || config.labels.length === 0;
            const autoDetectScatter = !config.chart_type && (hasTwoDatasets && missingLabels);

            if (chartType === 'scatter' || autoDetectScatter) {
                // Scatter 模式：轉換數據為 X/Y 點
                chartType = 'scatter';
                const d1 = config.datasets[0].data;
                const d2 = config.datasets[1].data;
                const scatterPoints = d1.map((v, i) => ({ x: Number(v), y: Number(d2[i]) }));
                
                chartData.datasets = [{
                    label: `${config.datasets[0].label} vs ${config.datasets[1].label}`,
                    data: scatterPoints,
                    borderColor: '#7e22ce', // 紫色
                    backgroundColor: 'rgba(126, 34, 206, 0.5)',
                    pointRadius: 6
                }];
                // ... 設置 X 軸標題 ...
            } else {
                // Line 模式：自動補全 Label
                chartType = 'line';
                let labels = config.labels || [];
                if (labels.length === 0) {
                    // 自動生成 T-0, T-1...
                    const len = config.datasets[0].data.length;
                    for (let i = len - 1; i >= 0; i--) labels.push(`T-${i}`);
                }
                chartData.labels = labels;
                
                // 2. 樣式美化 (Style Injection)
                chartData.datasets = config.datasets.map((ds, idx) => {
                    // 固定配色方案
                    const colorMap = ['#7c3aed', '#f59e0b', '#3b82f6']; // 紫, 琥珀, 藍
                    const bgMap = ['rgba(124, 58, 237, 0.1)', 'rgba(245, 158, 11, 0.1)', 'rgba(59, 130, 246, 0.1)'];
                    
                    const color = colorMap[idx] || '#999';
                    const bgColor = bgMap[idx] || 'rgba(0,0,0,0.1)';
                    
                    return {
                        label: ds.label || `Series ${idx+1}`,
                        data: ds.data,
                        borderColor: color,
                        backgroundColor: bgColor, // ✅ 解法的核心：使用明確的 rgba 背景
                        borderWidth: 2,
                        fill: true,           // ✅ 開啟填充
                        tension: 0.3,         // ✅ 平滑曲線
                        pointRadius: 3,       // ✅ 顯示數據點
                        pointHoverRadius: 5
                    };
                });
            }
            
            new Chart(canvas, {
                type: chartType,
                data: chartData,
                options: chartOptions
            });
            // --- 核心邏輯結束 ---
            
        } catch(e) { console.error(e); }
    });
}
```

---

## 4. 懶人檢查表 (Implementation Checklist)

在發布新功能前，請檢查：

- [ ] **Python**: 所有長時間運行的 LLM 呼叫是否都包在 `await asyncio.to_thread(...)` 裡？
- [ ] **Python**: Router 是否有 `try/except` 包裹並檢查不小心返回的 coroutine？
- [ ] **JS (Popup)**: 獲取 `SESSION_ID` 時是否檢查了 `window.opener.SESSION_ID`？
- [ ] **JS (Sync)**: 跨視窗通訊是否只傳遞纯數據 (JSON) 而非 DOM 元素？
- [ ] **JS (Chart)**: 圖表配置是否包含 `fill: true` 和 `pointRadius > 0` 以確保可視性？
- [ ] **JS (Color)**: 背景色是否使用了正確的 `rgba` 值而非無效的Hex字串？
