# 修復 LLM 持續阻塞問題 - 背景任務方案

## 問題診斷

即使使用了 `run_in_executor`，API 仍然會等待 LLM 回應完成才返回。這是因為：

1. **await 仍然會等待**：`await loop.run_in_executor()` 會等待線程完成
2. **FastAPI 路由等待回應**：路由函數必須等到有完整回應才能返回給前端
3. **前端也在等待**：fetch 調用會等待 HTTP 回應

## 解決方案：改用背景任務

### 方案 A：立即返回 + 輪詢（推薦）

**工作流程：**
```
1. 前端發送請求 → 後端立即返回 job_id
2. 後端在背景處理 LLM 請求
3. 前端輪詢檢查狀態
4. 完成後顯示結果
```

**優點：**
- 完全不阻塞
- 用戶可以繼續使用其他功能
- 可以顯示進度

### 方案 B：設定較短的超時時間

**簡單修改：**
```python
# 將 LLM 超時從 90 秒改為 10 秒
response = requests.post(self.api_url, json=payload, timeout=10.0)
```

**優點：**
- 最簡單的修改
- 如果 LLM 10 秒內回應不了，顯示錯誤訊息
- 用戶可以繼續操作

**缺點：**
- 可能經常超時
- 無法獲得完整分析

### 方案 C：Server-Sent Events (SSE)

使用 SSE 流式傳輸 LLM 回應。

## 建議：立即實施方案 B

修改超時時間為 10-15 秒，這樣至少不會長時間阻塞：

```python
# llm_reporter.py line 95
response = requests.post(self.api_url, json=payload, timeout=15.0)  # 改為 15 秒

# 並更新錯誤訊息
except requests.exceptions.Timeout:
    return f"❌ LLM 請求超時 (15s)。LLM 服務可能負載過高，請稍後再試。\nURL: {self.api_url}"
```

這樣即使卡住，也只會卡 15 秒，而不是 90 秒。
