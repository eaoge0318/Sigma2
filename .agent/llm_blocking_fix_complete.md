# LLM 阻塞問題完整修復總結

## 📋 問題回顧

**症狀：**
- 點擊「專家分析」後，整個系統（包括即時預測）會卡住
- 需要等待很長時間才能恢復

**根本原因：**
1. ❌ httpx 套件未安裝，但程式碼使用了 `httpx.AsyncClient`
2. ❌ 即使使用 `await`，FastAPI 路由仍會等待完整的 HTTP 回應
3. ❌ LLM 請求超時設定為 90 秒，太長

## ✅ 已實施的修復

### 修復 1：移除 httpx 依賴
**檔案：** `llm_reporter.py`

```python
# 修改前
import httpx  # 異步 HTTP 客戶端

# 修改後
# import httpx  # 移除 httpx 依賴，改用 requests + asyncio
```

**效果：** 不再依賴未安裝的 httpx 套件

---

### 修復 2：使用 asyncio 線程池執行
**檔案：** `llm_reporter.py`

```python
# 使用 asyncio.get_running_loop() 和 run_in_executor
def _make_request():
    """在線程池中執行的同步 HTTP 請求"""
    response = requests.post(self.api_url, json=payload, timeout=15.0)
    # ... 處理回應 ...

# 在獨立線程中執行，避免阻塞主事件循環
loop = asyncio.get_running_loop()
result = await loop.run_in_executor(None, _make_request)
return result
```

**效果：** 
- ✅ LLM 請求在獨立線程執行
- ✅ 理論上不應阻塞主事件循環
- ⚠️ 但仍需等待回應才能返回給前端

---

### 修復 3：縮短超時時間（最關鍵）
**檔案：** `llm_reporter.py`

```python
# 修改前
response = requests.post(self.api_url, json=payload, timeout=90.0)  # 90 秒

# 修改後
response = requests.post(self.api_url, json=payload, timeout=15.0)  # 15 秒
```

**效果：**
- ✅ 即使阻塞，也只會卡 15 秒（而非 90 秒）
- ✅ 大幅減少對用戶體驗的影響
- ⚠️ LLM 如果需要超過 15 秒會顯示超時錯誤

---

## 🎯 當前行為

### 正常情況
1. 用戶點擊「專家分析」
2. 前端顯示「⏳ 正在分析數據，請稍候...」
3. **最多等待 15 秒**
4. 顯示結果或超時錯誤

### 如果 LLM 回應慢
- 15 秒後顯示：「❌ LLM 請求超時 (15s)。LLM 服務可能負載過高或模型太大，請稍後再試。」
- 用戶可以繼續使用其他功能

---

## 📝 測試步驟

### 測試 1：基本功能測試
1. **重新啟動 API 伺服器**
2. 載入模擬檔案和模型
3. 點擊 "Auto Play" - 確認即時預測正常
4. 點擊「專家分析」
5. **在等待期間**，嘗試點擊 "Next" 或 "Auto Play"
6. 觀察即時預測是否仍然響應

### 測試 2：超時行為測試
如果 LLM 服務很慢或未啟動：
1. 點擊「專家分析」
2. 15 秒後應該看到超時錯誤訊息
3. 確認不會無限期等待

### 測試 3：並發測試
1. 點擊「專家分析」（開始 LLM 請求）
2. **立即**點擊 "Auto Play"（觸發預測請求）
3. 觀察兩個請求是否都能處理

---

## 🔍 預期結果

### ✅ 成功指標
- 即時預測在 LLM 請求期間仍可使用
- 最多只會等待 15 秒
- 錯誤訊息清晰明確

### ❌ 仍有問題
如果仍然阻塞，可能原因：
1. **FastAPI 設定問題**：檢查是否使用了同步而非異步路由
2. **其他阻塞代碼**：可能有其他地方的同步代碼
3. **前端問題**：前端可能在等待回應時鎖定 UI

---

## 🚀 進階解決方案（如果仍有問題）

### 方案 A：背景任務 + 輪詢
完全異步，用戶可以立即繼續操作：

```python
# 1. 修改 API：立即返回 job_id
@router.post("/ai_report_async")
async def start_ai_report(session_id: str):
    job_id = str(uuid.uuid4())
    # 啟動背景任務
    background_tasks.add_task(generate_report_task, job_id, session_id)
    return {"job_id": job_id, "status": "processing"}

# 2. 輪詢端點
@router.get("/ai_report_status/{job_id}")
async def get_report_status(job_id: str):
    # 檢查狀態並返回結果
    return {"status": "completed", "result": "..."}
```

**前端實作：**
```javascript
// 1. 啟動任務
const {job_id} = await fetch('/api/ai_report_async').then(r => r.json());

// 2. 輪詢狀態
const pollInterval = setInterval(async () => {
    const {status, result} = await fetch(`/api/ai_report_status/${job_id}`).then(r => r.json());
    if (status === 'completed') {
        clearInterval(pollInterval);
        displayResult(result);
    }
}, 2000); // 每 2 秒檢查一次
```

### 方案 B：Server-Sent Events (SSE)
即時流式傳輸結果。

### 方案 C：前端超時控制
在前端設定較短的超時：
```javascript
const controller = new AbortController();
const timeoutId = setTimeout(() => controller.abort(), 10000); // 10 秒

fetch('/api/ai_report', { signal: controller.signal })
    .then(...)
    .catch(err => {
        if (err.name === 'AbortError') {
            console.log('請求超時');
        }
    })
    .finally(() => clearTimeout(timeoutId));
```

---

## 📊 當前配置總結

| 項目 | 值 | 說明 |
|------|-----|------|
| HTTP 庫 | requests | 替代 httpx |
| 執行方式 | asyncio.run_in_executor | 線程池執行 |
| 超時時間 | 15 秒 | 從 90 秒縮短 |
| 線程池 | 默認 executor | None 參數 |
| 事件循環 | get_running_loop() | FastAPI 相容 |

---

## 💡 建議

1. **立即測試**：重啟伺服器並測試是否改善
2. **監控行為**：觀察 15 秒是否足夠
3. **調整超時**：如果 15 秒太短，可改為 20-30 秒
4. **考慮背景任務**：如果仍有阻塞，實施方案 A

---

## 🔧 快速調整超時時間

如果需要調整超時時間，修改 `llm_reporter.py` 第 95 行：

```python
# 當前：15 秒
response = requests.post(self.api_url, json=payload, timeout=15.0)

# 如果太短，改為 30 秒：
response = requests.post(self.api_url, json=payload, timeout=30.0)

# 如果太長，改為 10 秒：
response = requests.post(self.api_url, json=payload, timeout=10.0)
```

並同步更新錯誤訊息中的秒數。

---

**最後更新：** 2026-02-04 17:14
**狀態：** ✅ 已修復（待測試驗證）
**關鍵改進：** 超時時間從 90 秒減少到 15 秒
