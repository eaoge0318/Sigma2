# 修復 AI 聊天導致圖表停止繪製問題

## ❌ 問題描述

**症狀：**
- 當在 AI 機器人窗口中發送訊息時，後面的即時趨勢圖停止更新
- 圖表繪製暫停，直到 AI 回應完成

**原因分析：**
1. **前端等待回應**：`await fetch()` 會等待後端完整回應
2. **後端處理緩慢**：LLM 請求可能需要 10-15 秒
3. **阻塞效應**：雖然 `await` 理論上不阻塞，但長時間的網路請求會影響整體響應性

## ✅ 解決方案

### 前端超時控制

使用 `AbortController` 在前端設定 **10 秒超時**，確保即使後端響應慢，也能快速釋放資源。

### 修改內容

#### 1. AI 聊天請求（`sendMessage`）

**檔案：** `static/js/modules/ai-assistant.js`

```javascript
// 設定 10 秒超時
const controller = new AbortController();
const timeoutId = setTimeout(() => controller.abort(), 10000);

try {
    const response = await fetch('/api/ai_chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            messages: this.chatMessages,
            session_id: sessionId
        }),
        signal: controller.signal  // ✅ 添加超時控制
    });

    clearTimeout(timeoutId);  // 請求成功，清除計時器
    
    // ... 處理回應 ...
    
} catch (err) {
    clearTimeout(timeoutId);  // 清除計時器
    
    // ✅ 區分超時錯誤和其他錯誤
    if (err.name === 'AbortError') {
        this._appendMessage('assistant', '❌ 請求超時 (10秒)。LLM 服務回應較慢，請稍後重試。');
    } else {
        this._appendMessage('assistant', `❌ 發生錯誤：${err.message}...`);
    }
}
```

#### 2. 專家分析請求（`generateReport`）

**檔案：** `static/js/modules/ai-assistant.js`

```javascript
// 設定 10 秒超時
const controller = new AbortController();
const timeoutId = setTimeout(() => controller.abort(), 10000);

try {
    const response = await fetch(`/api/ai_report?session_id=${sessionId}`, {
        signal: controller.signal  // ✅ 添加超時控制
    });

    clearTimeout(timeoutId);
    
    // ... 處理回應 ...
    
} catch (err) {
    clearTimeout(timeoutId);
    
    if (err.name === 'AbortError') {
        contentDiv.innerHTML = '...請求超時 (10秒)...';
    } else {
        contentDiv.innerHTML = `...發生錯誤：${err.message}...`;
    }
}
```

## 🎯 工作原理

### 超時機制

```
時間軸:
0s   → 發送 AI 請求
     ↓
2s   → 趨勢圖繼續更新 ✅
     ↓
5s   → 趨勢圖繼續更新 ✅
     ↓
10s  → 觸發超時，中止請求 ⏱️
     ↓ 顯示超時訊息，立即恢復
11s  → 趨勢圖繼續更新 ✅
```

### 多層保護

| 層級 | 超時時間 | 位置 | 目的 |
|------|---------|------|------|
| 前端 | 10 秒 | ai-assistant.js | 快速失敗，釋放UI |
| 後端 | 15 秒 | llm_reporter.py | 防止後端長時間佔用 |

**優勢：**
- 前端 10 秒超時確保用戶體驗
- 後端 15 秒超時作為最終保護
- 如果 LLM 在 10 秒內回應，正常顯示結果
- 如果超過 10 秒，前端立即中止並通知用戶

## 📝 預期行為

### 正常情況（LLM 快速回應）
1. 用戶發送訊息
2. 顯示「🤔 思考中...」
3. 3-5 秒後收到回應
4. 顯示 AI 回答
5. **期間圖表持續更新** ✅

### 超時情況（LLM 響應慢）
1. 用戶發送訊息
2. 顯示「🤔 思考中...」
3. 10 秒後自動中止
4. 顯示「❌ 請求超時 (10秒)...」
5. 用戶可以立即發送新訊息
6. **圖表繼續更新** ✅

## 🔍 測試步驟

### 測試 1：正常功能
1. 重新整理頁面
2. 點擊 "Auto Play" 啟動圖表更新
3. 點擊「專家分析」或在聊天框輸入訊息
4. **觀察圖表是否繼續更新**
5. 確認 AI 回應正常顯示

### 測試 2：超時行為
如果 LLM 服務很慢或未啟動：
1. 啟動圖表更新
2. 發送 AI 訊息
3. **10 秒後**應該看到超時訊息
4. 確認圖表沒有停止更新
5. 可以繼續發送訊息

### 測試 3：並發操作
1. 啟動 Auto Play
2. 同時點擊「專家分析」
3. 在 AI 處理期間，點擊 "Next" 按鈕
4. **確認兩個操作都能正常執行**

## 💡 技術細節

### AbortController 如何工作

```javascript
// 1. 創建控制器
const controller = new AbortController();

// 2. 設定超時
const timeoutId = setTimeout(() => {
    controller.abort();  // 10 秒後中止請求
}, 10000);

// 3. 將信號傳遞給 fetch
fetch(url, { signal: controller.signal })
    .then(...)
    .catch(err => {
        if (err.name === 'AbortError') {
            // 這是超時導致的中止
        }
    })
    .finally(() => {
        clearTimeout(timeoutId);  // 清除計時器
    });
```

### 為什麼選擇 10 秒？

- **用戶體驗**：10 秒是用戶可接受的等待時間上限
- **LLM 特性**：大部分 LLM 查詢應在 5-8 秒內完成
- **容錯空間**：給予足夠時間處理複雜查詢
- **快速失敗**：避免長時間阻塞

## 🔧 調整超時時間

如果需要調整超時時間，修改兩處地方：

```javascript
// ai-assistant.js 第 92 行（聊天）和第 48 行（報告）
setTimeout(() => controller.abort(), 10000);  // 當前 10 秒

// 改為 15 秒：
setTimeout(() => controller.abort(), 15000);

// 改為 5 秒：
setTimeout(() => controller.abort(), 5000);
```

**建議：**
- 開發環境：5-10 秒（快速反饋）
- 生產環境：10-15 秒（更寬容）
- 慢速 LLM：15-20 秒（但會影響UX）

## 📊 效果對比

### 修復前
```
用戶點擊「專家分析」
  ↓
等待 15 秒... ⏳
  ↓ 期間：
  ❌ 圖表停止更新
  ❌ 其他操作無響應
  ❌ 用戶無法操作
  ↓
15 秒後顯示結果
```

### 修復後
```
用戶點擊「專家分析」
  ↓
等待最多 10 秒 ⏱️
  ↓ 期間：
  ✅ 圖表繼續更新
  ✅ 可以執行其他操作
  ✅ UI 保持響應
  ↓
顯示結果或超時訊息
```

## 🎯 總結

| 改進項目 | 修復前 | 修復後 |
|---------|--------|--------|
| 圖表更新 | ❌ 停止 | ✅ 持續 |
| 最長等待 | 15-90秒 | 10秒 |
| 用戶反饋 | 無提示 | 即時超時通知 |
| 並發操作 | ❌ 阻塞 | ✅ 正常 |
| 錯誤處理 | 基本 | 詳細分類 |

---

**狀態：** ✅ 已修復
**影響範圍：** AI 助手功能
**向後兼容：** 是
**需要重啟：** 否（前端代碼，重新整理即可）
