# 修復 LLM 請求阻塞問題總結

## ❌ 原始問題

**症狀：**
- 當詢問 AI 機器人時，後端的即時預測功能會卡住同步
- 整個 API 伺服器變得無回應

**根本原因：**
1. **httpx 未安裝**：程式碼使用 `httpx.AsyncClient`，但 httpx 套件未安裝
2. **可能的導入失敗**：如果 httpx 導入失敗，可能導致整個模組無法載入
3. **事件循環阻塞**：即使 httpx 可用，長時間的 LLM 請求也可能影響其他請求

## ✅ 解決方案

改用 `requests` 庫搭配 `asyncio.ThreadPoolExecutor`，將同步的 HTTP 請求放到獨立線程執行，避免阻塞 FastAPI 的主事件循環。

### 修改內容

#### `llm_reporter.py`

**變更 1：移除 httpx 依賴**
```python
# 修改前
import httpx  # 異步 HTTP 客戶端

# 修改後
# import httpx  # 移除 httpx 依賴，改用 requests + asyncio
```

**變更 2：使用 ThreadPoolExecutor**
```python
# 修改前（使用 httpx）
async with httpx.AsyncClient(timeout=90.0) as client:
    response = await client.post(self.api_url, json=payload)
    response.raise_for_status()
    result = response.json()
    return result.get("message", {}).get("content", "無法取得 AI 回覆內容")

# 修改後（使用 requests + ThreadPoolExecutor）
import asyncio
from concurrent.futures import ThreadPoolExecutor

def _make_request():
    """在線程池中執行的同步 HTTP 請求"""
    try:
        response = requests.post(self.api_url, json=payload, timeout=90.0)
        response.raise_for_status()
        result = response.json()
        return result.get("message", {}).get("content", "無法取得 AI 回覆內容")
    except requests.exceptions.Timeout:
        return f"❌ LLM 請求超時 (90s)..."
    except requests.exceptions.ConnectionError:
        return f"❌ LLM 連線失敗..."
    except Exception as e:
        return f"❌ LLM 調用失敗: {str(e)}..."

# 在線程池中執行請求，避免阻塞 FastAPI 事件循環
loop = asyncio.get_event_loop()
with ThreadPoolExecutor(max_workers=1) as executor:
    result = await loop.run_in_executor(executor, _make_request)
    return result
```

## 🎯 技術說明

### 為什麼使用 ThreadPoolExecutor？

1. **非阻塞執行**：
   - LLM 請求可能需要數十秒
   - 在獨立線程中執行，不會阻塞 FastAPI 的主事件循環
   - 其他 API 請求（如即時預測）可以正常處理

2. **簡化依賴**：
   - 不需要安裝 httpx
   - 使用標準庫的 `requests`（通常已安裝）
   - 使用 Python 內建的 `concurrent.futures`

3. **保持異步介面**：
   - 函數仍然是 `async def`
   - 使用 `await loop.run_in_executor()`
   - 對呼叫者來說仍是異步的

### 工作原理

```
┌─────────────────────────────────┐
│ FastAPI 主事件循環              │
│                                 │
│  ┌──────────────────────────┐  │
│  │ /api/ai_report 請求      │  │
│  │ (不阻塞)                 │  │
│  └──────┬───────────────────┘  │
│         │                       │
│         │ await run_in_executor │
│         ▼                       │
│  ┌──────────────────────────┐  │
│  │ 線程池                   │  │
│  │ ┌──────────────────────┐ │  │
│  │ │ LLM HTTP 請求        │ │  │
│  │ │ (在獨立線程中執行)   │ │  │
│  │ │ 等待 90 秒...        │ │  │
│  │ └──────────────────────┘ │  │
│  └──────────────────────────┘  │
│                                 │
│  ┌──────────────────────────┐  │
│  │ /predict 請求            │  │
│  │ (同時正常處理)           │  │
│  └──────────────────────────┘  │
└─────────────────────────────────┘
```

## 📝 測試驗證

### 測試步驟

1. **重新啟動 API 伺服器**
2. **測試即時預測**：
   - 載入模擬檔案
   - 點擊 "Auto Play"
   - 確認預測正常執行

3. **測試 AI 報告**：
   - 點擊「專家分析」按鈕
   - 觀察是否顯示載入提示

4. **並發測試**：
   - 在 AI 報告生成過程中（等待 LLM 回應時）
   - 同時執行即時預測
   - **預期結果**：即時預測應該不會被阻塞

### 預期行為

✅ **正常情況**：
- AI 報告生成時顯示「⏳ 正在分析數據，請稍候...」
- 等待 LLM 回應（可能需要 10-30 秒）
- 其他 API 請求（如 `/predict`）正常運作
- 最終顯示 AI 分析結果或錯誤訊息

❌ **異常情況**（修復前）：
- AI 報告請求後，整個伺服器卡住
- 即時預測無法執行
- 需要等待 LLM 請求完成或超時

## 🔧 如果還有問題

### 問題 1：requests 未安裝
```bash
pip install requests
```

### 問題 2：LLM 超時設定太長
可以在 `llm_reporter.py` 中調整超時時間：
```python
response = requests.post(self.api_url, json=payload, timeout=30.0)  # 改為 30 秒
```

### 問題 3：仍然阻塞
檢查是否有其他同步代碼在主線程執行：
- 搜尋 `llm_reporter.py` 中的其他函數
- 確保所有長時間操作都在 ThreadPoolExecutor 中執行

## 📦 優點與限制

### 優點
✅ 不需要額外安裝 httpx
✅ 不阻塞 FastAPI 事件循環
✅ 保持異步 API 介面
✅ 錯誤處理完善

### 限制
⚠️ 每個 LLM 請求佔用一個線程（但已限制為 max_workers=1）
⚠️ Python GIL 的影響（但對 I/O 密集型操作影響不大）
⚠️ 不如純異步 httpx 高效（但對單一 LLM 請求影響可忽略）

---

**狀態：** ✅ 已修復
**測試狀態：** 待驗證
**影響範圍：** AI 助手功能，不影響其他模組
