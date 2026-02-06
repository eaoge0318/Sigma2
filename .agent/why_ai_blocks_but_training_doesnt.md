# 為什麼 AI 機器人會卡但模型訓練不會？

## 🔍 核心問題

### 架構差異

**模型訓練（不會卡）：**
```
獨立進程模式
├─ FastAPI 主進程（處理 API 請求）
│  └─ 快速響應 /api/history ✅
│
└─ 訓練子進程（subprocess）
   └─ 完全獨立運行 ✅
   
結果：兩者互不干擾
```

**AI 機器人（會卡）：**
```
共享進程模式
└─ FastAPI 主進程（單 worker）
   ├─ /api/ai_chat（佔用 30 秒）⏳
   └─ /api/history（排隊等待）⏸️
   
結果：LLM 請求阻塞其他請求
```

---

## ❌ 為什麼會卡？

### 1. 單 Worker 限制

FastAPI 默認單個 worker 處理所有請求：

```python
# 當前配置
uvicorn.run(app, host="0.0.0.0", port=config.API_PORT)
# ↑ 默認只有 1 個 worker
```

**問題：**
- LLM 請求需要 30 秒
- 在這 30 秒內，其他請求無法處理
- Dashboard 的 `/api/history` 輪詢被阻塞

### 2. 線程池不足

雖然使用了 `run_in_executor`，但：

```python
loop = asyncio.get_running_loop()
result = await loop.run_in_executor(None, _make_request)
```

- `None` 使用默認線程池（可能只有幾個線程）
- Windows 上線程池較小
- 多個 LLM 請求會耗盡線程池

### 3. 事件循環佔用

即使在線程中執行，`await` 仍會：
- 佔用事件循環的一個"槽位"
- 影響其他異步操作的調度

---

## ✅ 解決方案

### 方案 1：優化 FastAPI 並發（Windows 限制）

**問題：**
- Windows 上 `workers` 參數無效
- 需要使用其他方式

**替代方案：**
```python
# 使用 limit_concurrency 中間件
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

# 設定並發限制但允許同時處理多個請求
```

---

### 方案 2：使用 ASGI 服務器 Gunicorn（Linux）

**僅適用於 Linux/Mac：**
```bash
gunicorn api_entry:app \
    --workers 4 \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:8001
```

**效果：**
- 4 個獨立的 worker 進程
- 真正的並發處理
- **Windows 不支持**

---

### 方案 3：改用後台任務（推薦）

將 LLM 請求改為類似模型訓練的獨立處理：

#### 後端修改

```python
# 添加後台任務存儲
from fastapi import BackgroundTasks
import uuid

llm_results = {}  # job_id -> result

def process_llm_background(job_id: str, messages, session_id):
    """在背景處理 LLM 請求"""
    try:
        reporter = LLMReporter()
        result = reporter.chat_with_expert_sync(messages, {})  # 同步版本
        llm_results[job_id] = {"status": "completed", "reply": result}
    except Exception as e:
        llm_results[job_id] = {"status": "error", "message": str(e)}

@router.post("/ai_chat_async")
async def ai_chat_async(
    request: ChatRequest,
    background_tasks: BackgroundTasks
):
    """立即返回 job_id，在背景處理"""
    job_id = str(uuid.uuid4())
    llm_results[job_id] = {"status": "processing"}
    
    # 添加背景任務
    background_tasks.add_task(
        process_llm_background,
        job_id,
        request.messages,
        request.session_id
    )
    
    return {"job_id": job_id, "status": "processing"}

@router.get("/ai_chat_result/{job_id}")
async def get_chat_result(job_id: str):
    """輪詢結果"""
    result = llm_results.get(job_id, {"status": "not_found"})
    return result
```

#### 前端修改

```javascript
// 1. 發送請求，立即獲得 job_id
const {job_id} = await fetch('/api/ai_chat_async', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({messages, session_id})
}).then(r => r.json());

// 2. 輪詢結果
const pollInterval = setInterval(async () => {
    const result = await fetch(`/api/ai_chat_result/${job_id}`).then(r => r.json());
    
    if (result.status === 'completed') {
        clearInterval(pollInterval);
        // 顯示結果
        this._appendMessage('assistant', result.reply);
    } else if (result.status === 'error') {
        clearInterval(pollInterval);
        // 顯示錯誤
        this._appendMessage('assistant', '❌ ' + result.message);
    }
}, 1000);  // 每秒檢查一次

// 3. 30 秒後超時
setTimeout(() => {
    clearInterval(pollInterval);
}, 30000);
```

---

## 📊 方案對比

| 方案 | 優點 | 缺點 | 適用性 |
|------|------|------|--------|
| 增加 Workers | 簡單 | Windows 不支持 | ❌ Windows |
| Gunicorn | 真正並發 | 需 Linux | ❌ Windows |
| **後台任務** | **完全不阻塞** | **需改代碼** | **✅ 所有平台** |

---

## 🎯 推薦實施：後台任務方案

這是最徹底的解決方案，類似模型訓練的方式：

**工作流程：**
```
1. 用戶發送訊息
   ↓
2. 後端立即返回 job_id (< 10ms)
   ↓
3. 前端開始輪詢結果
   ↓（同時）
4. 後端在背景處理 LLM 請求（30 秒）
   ↓（期間）
5. Dashboard 正常更新 ✅
6. 預測功能正常 ✅
   ↓
7. LLM 完成，前端獲取結果
```

**優勢：**
- ✅ 完全不阻塞主進程
- ✅ Dashboard 始終響應
- ✅ 可以處理多個並發 LLM 請求
- ✅ 跨平台支持（Windows/Linux/Mac）
- ✅ 與模型訓練一致的架構

---

## 💡 臨時解決方案

如果暫時不想改代碼，可以：

1. **縮短超時**：15-20 秒而非 30 秒
2. **避免並發**：不要在模擬運行時使用 AI
3. **重啟服務器**：如果卡住，重啟 API

---

**建議：實施後台任務方案，徹底解決問題**

要我現在幫您實施後台任務方案嗎？這樣就能像模型訓練一樣，AI 請求完全不會阻塞其他功能。
