# LLM 超時時間調整為 30 秒

## ✅ 調整內容

### 前端超時：10 秒 → **30 秒**

**檔案：** `static/js/modules/ai-assistant.js`

#### 1. 專家分析（generateReport）
```javascript
// 修改前
setTimeout(() => controller.abort(), 10000); // 10 秒

// 修改後
setTimeout(() => controller.abort(), 30000); // 30 秒
```

#### 2. AI 聊天（sendMessage）
```javascript
// 修改前
setTimeout(() => controller.abort(), 10000); // 10 秒

// 修改後
setTimeout(() => controller.abort(), 30000); // 30 秒
```

#### 3. 錯誤訊息更新
```javascript
// 修改前
'❌ 請求超時 (10秒)...'

// 修改後
'❌ 請求超時 (30秒)...'
```

---

### 後端超時：15 秒 → **30 秒**

**檔案：** `llm_reporter.py`

```python
# 修改前
response = requests.post(self.api_url, json=payload, timeout=15.0)
return f"❌ LLM 請求超時 (15s)..."

# 修改後
response = requests.post(self.api_url, json=payload, timeout=30.0)
return f"❌ LLM 請求超時 (30s)..."
```

---

## 📊 新的超時配置

| 層級 | 超時時間 | 位置 | 目的 |
|------|---------|------|------|
| **前端** | **30 秒** | ai-assistant.js | 允許 LLM 有足夠時間處理複雜查詢 |
| **後端** | **30 秒** | llm_reporter.py | 與前端同步，避免不一致 |

**工作流程：**
```
0s   → 用戶發送請求
     ↓
...  → LLM 處理中（圖表繼續更新）
     ↓
30s  → 如果超時，前端和後端同時中止
     ↓ 顯示超時訊息
```

---

## 🎯 優點

### ✅ 給予 LLM 充足時間
- 30 秒足夠處理大部分複雜查詢
- 減少不必要的超時錯誤
- 用戶體驗更友善

### ✅ 仍然保持響應性
- 即使等待 30 秒，圖表仍會繼續更新
- `AbortController` 確保可以隨時中止
- 不會無限期等待

### ✅ 前後端同步
- 前端和後端都是 30 秒
- 避免前端已超時但後端仍在處理的情況
- 資源管理更一致

---

## 📝 測試建議

### 正常情況
1. 點擊「專家分析」或發送聊天訊息
2. 觀察圖表是否繼續更新 ✅
3. LLM 在 30 秒內回應 → 正常顯示結果

### 超時情況
1. LLM 服務較慢或未啟動
2. 等待 30 秒
3. 顯示「❌ 請求超時 (30秒)...」
4. 可以立即重試或繼續其他操作

---

## 🔧 如需進一步調整

**增加到 45 秒：**
```javascript
// 前端 ai-assistant.js
setTimeout(() => controller.abort(), 45000);
```

```python
# 後端 llm_reporter.py
response = requests.post(self.api_url, json=payload, timeout=45.0)
```

**減少到 20 秒：**
```javascript
// 前端
setTimeout(() => controller.abort(), 20000);
```

```python
# 後端
response = requests.post(self.api_url, json=payload, timeout=20.0)
```

**建議：**
- 本地開發/快速 LLM：20-30 秒
- 生產環境/標準 LLM：30-45 秒
- 慢速 LLM/複雜查詢：45-60 秒

---

## 📌 注意事項

1. **重新整理頁面**：前端修改需重新整理頁面生效
2. **重啟後端**：後端修改需重啟 API 伺服器
3. **圖表更新**：即使等待 30 秒，圖表仍應正常更新
4. **用戶體驗**：30 秒是用戶可接受的上限，建議優化 LLM 回應速度

---

**更新時間：** 2026-02-04 17:25
**狀態：** ✅ 已調整
**新超時時間：** 前端 30s / 後端 30s
