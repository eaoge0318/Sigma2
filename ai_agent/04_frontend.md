# 04. 前端實現

> 智能分析頁面 - 使用 iframe 獨立頁面架構

---

## 1. 架構說明

為了避免 `dashboard.html` 過於肥大並確保智能分析功能的獨立性，本功能採用 **iframe 嵌入獨立頁面** 的方式實現。

### 架構優點

- ✅ **檔案分離**：維持主儀表板 (Dashboard) 邏輯精簡。
- ✅ **獨立測試**：智能分析功能可作為獨立頁面開發與測試。
- ✅ **樣式隔離**：CSS 與 JavaScript 全域變數互不衝突。
- ✅ **按需載入**：只有在用戶切換到「智能分析」頁籤時才載入資源。

### 檔案結構

```
static/
└── html/
    └── intelligent_analysis.html  # 獨立完整頁面（HTML + CSS + JS）
```

---

## 2. 獨立頁面實現 (`intelligent_analysis.html`)

這是一個包含完整 HTML、CSS 和 JavaScript 的單一檔案，負責處理所有的智能分析交互。

### UI 設計特點 (最終版)

- **全螢幕佈局**：頁面完全填滿 iframe，無邊距 (`margin: 0`, `padding: 0`)。
- **配色方案**：
  - **主色調**：藍色漸變 (`linear-gradient(135deg, #3b82f6 0%, #2563eb 100%)`)，用於按鈕和用戶訊息氣泡。
  - **背景色**：`#eceff4` (整體背景)，白色 (`#ffffff`) 用於卡片和聊天區。
  - **文字色**：`#2c3e50` (標題/正文)，`#7f8c8d` (次要資訊)。
- **組件樣式**：
  - **扁平化設計**：移除 header、sidebar 和 chat area 的圓角 (`border-radius: 0`) 和陰影，以實現無縫拼接。
  - **輸入區域**：
    - **附件按鈕**：位於輸入框左側，藍色方形圖標。
    - **輸入框**：底部對齊，支援 **Shift+Enter 自動增高** (最高 150px)，單行預設。
    - **發送按鈕**：位於輸入框右側，藍色實心按鈕。
    - **移除**：麥克風和 Emoji 按鈕 (精簡介面)。

### 關鍵 CSS 實現

```css
/* 主容器：確保填滿 */
.ia-wrapper {
    height: 100vh;
    display: flex;
    flex-direction: column;
}

/* 網格佈局：側邊欄 + 聊天區 */
.ia-container {
    display: grid;
    grid-template-columns: 340px 1fr;
    flex: 1;
    min-height: 0;
}

/* 輸入框自動增高 */
.ia-input-wrapper textarea {
    min-height: 44px;
    max-height: 150px;
    overflow-y: hidden;
    resize: none;
}

/* 藍色漸變按鈕 */
.ia-attach-btn, .ia-send-btn {
    background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
    color: white;
}
```

---

## 3. JavaScript 實現邏輯

### 核心類設計 (`IntelligentAnalysis`)

雖然目前前端僅為演示 (Demo)，但完整實作應包含以下邏輯類：

```javascript
class IntelligentAnalysis {
    constructor() {
        this.sessionId = localStorage.getItem('session_id') || 'default';
        this.currentFileId = null;
        this.currentFilename = null;
        this.conversationId = 'default'; // 或生成新的 UUID
        
        this.init();
    }
    
    async init() {
        this.bindEvents();
        await this.loadFiles();
        await this.loadTools(); // 加載可用工具列表 (可選)
    }
    
    bindEvents() {
        // 文件選擇
        document.getElementById('analysis-file-selector').addEventListener('change', (e) => {
            this.onFileSelect(e.target.value);
        });
        
        // 附件按鈕 (目前僅演示)
        document.getElementById('attach-btn').addEventListener('click', () => {
             alert('附加檔案功能演示（實際功能待實現）');
        });

        // 輸入框自動增高與發送處理
        const input = document.getElementById('user-question');
        input.addEventListener('input', function() {
            this.style.height = 'auto';
            this.style.height = (this.scrollHeight) + 'px';
            if (this.scrollHeight > 150) {
                this.style.overflowY = 'auto';
            } else {
                this.style.overflowY = 'hidden';
            }
        });

        // 鍵盤事件：Enter 發送, Shift+Enter 換行
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });
        
        // 發送按鈕
        document.getElementById('send-question-btn').addEventListener('click', () => {
             this.sendMessage();
        });
        
        // 清除歷史 (目前僅演示)
        document.getElementById('clear-history-btn').addEventListener('click', () => {
            if(confirm('確定要清空所有歷史記錄嗎？')) {
                alert('清空歷史功能演示');
            }
        });
    }
    
    async loadFiles() {
        try {
            // 實際應調用後端 API: /api/analysis/files
            // 演示數據：
            const files = [
                { file_id: 'demo1', filename: '銷售資料.csv', is_indexed: true },
                { file_id: 'demo2', filename: '房地產資訊.csv', is_indexed: false },
                { file_id: 'demo3', filename: '股票歷史.csv', is_indexed: true }
            ];
            
            const selector = document.getElementById('analysis-file-selector');
            // 清空並重新填充 selector...
        } catch (error) {
            console.error('加載文件列表失敗:', error);
        }
    }
    
    onFileSelect(fileId) {
        if (!fileId) {
            this.currentFileId = null;
            document.getElementById('file-info-card').style.display = 'none'; // 隱藏資訊卡
            return;
        }
        
        this.currentFileId = fileId;
        // 顯示文件詳細資訊 (演示數據)
        // 實際應調用 API: /api/analysis/summary/{fileId}
        document.getElementById('file-info-card').style.display = 'block';
        // 更新 UI 顯示文件名、行數等...
    }
    
    async sendMessage() {
        const input = document.getElementById('user-question');
        const message = input.value.trim();
        
        if (!message) return;
        
        // 1. 顯示用戶消息
        this.addMessage('ia-user', message);
        input.value = '';
        input.style.height = 'auto'; // 重置高度
        
        // 2. 顯示思考中狀態 (可選)
        
        // 3. 調用後端 API (實際邏輯)
            // 3. 調用後端 API (SSE 串流實作)
        try {
            const formData = new FormData();
            formData.append('file_id', this.currentFileId);
            formData.append('message', message);
            // ... (其他參數)

            const response = await fetch('/api/analysis/chat/stream', {
                method: 'POST',
                // ...
            });
            // ...
        } catch (error) {
            // ...
        }
    }

    async handleMappingUpload(file) {
        // 處理術語對應表上傳
        // 若當前有選中檔案，則傳入 file_id 進行綁定
        const formData = new FormData();
        formData.append('is_mapping', 'true');
        if (this.currentFileId) {
             formData.append('file_id', this.currentFileId);
        }
        // ... 調用 /api/files/upload
    }
            
            // 建立一個空的 message bubble
            // this.addMessage('ia-assistant', '', true); // animate=true

            while (true) {
                const {value, done} = await reader.read();
                if (done) break;
                
                const chunk = decoder.decode(value, {stream: true});
                // 解析 SSE 格式 (data: {...})
                // 更新 UI: 
                // - type="thought" -> update thought box
                // - type="tool_call" -> render tool block
                // - type="response" -> typewrite text
            }

        } catch (error) {
            this.addMessage('ia-assistant', '錯誤: ' + error.message);
        }
    }
    
    addMessage(role, content) {
        const container = document.getElementById('chat-messages');
        const msgDiv = document.createElement('div');
        msgDiv.className = `ia-message ${role}`; // 使用 ia- 前綴
        msgDiv.innerHTML = `<div class="ia-message-content">${content}</div>`;
        container.appendChild(msgDiv);
        container.scrollTop = container.scrollHeight;
    }
}

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    new IntelligentAnalysis();
});
```

---

## 4. API 整合規劃

前端將與以下後端 API 進行交互 (詳見 `03_api_design.md`)：

| 功能 | 方法 | 路徑 | 說明 |
| --- | --- | --- | --- |
| 獲取文件列表 | GET | `/api/analysis/files` | 獲取可分析的 CSV 文件 |
| 準備索引 | POST | `/api/analysis/prepare` | 對文件建立語義索引 |
| 獲取文件摘要 | GET | `/api/analysis/summary/{file_id}` | 獲取列名、資料量等資訊 |
| 發送對話 | POST | `/api/analysis/chat` | 核心對話接口，包含工具調用 |
| 獲取歷史 | GET | `/api/analysis/history` | 載入過去的對話記錄 |
| 清除對話 | DELETE | `/api/analysis/clear-session` | 清空當前對話歷史 |
| 獲取工具列表 | GET | `/api/analysis/tools` | 顯示系統支援的所有分析工具 |

---

## 5. Dashboard 整合

在 `dashboard.html` 中，透過 iframe 引入智能分析頁面。

### HTML 結構

```html
<!-- 智能分析 iframe 區塊 -->
<section id="intelligent-analysis-section" class="main-section" style="display: none;">
    <iframe 
        id="analysis-iframe"
        src="/static/html/intelligent_analysis.html" 
        frameborder="0"
        style="width: 100%; height: calc(100vh - 100px); border: none;">
    </iframe>
</section>
```

### 切換邏輯

在 dashboard 的 `showSection` 函數中加入對應邏輯：

```javascript
function showSection(sectionName) {
    // ... 隱藏其他 section ...
    
    if (sectionName === 'analysis') {
        document.getElementById('intelligent-analysis-section').style.display = 'block';
        // 可選：重新載入 iframe 或通知 iframe 更新狀態
    }
}
```

---

## 6. 使用流程

1.  **進入頁面**：用戶點擊 Dashboard 導航欄的「智能分析」。
2.  **載入資源**：Dashboard 顯示 iframe，載入 `intelligent_analysis.html`。
3.  **選擇檔案**：用戶在左側邊欄選擇一個 CSV 檔案。
    - 若檔案未索引：顯示「準備分析索引」按鈕。
    - 若已索引：顯示檔案詳細資訊 (行數、列數)。
4.  **提問分析**：
    - 用戶在輸入框輸入問題 (支援 Shift+Enter 換行)。
    - 點擊附件按鈕可上傳參考圖片 (未來功能)。
    - 按 Enter 發送問題。
5.  **查看結果**：AI 回傳分析結果、圖表或數據摘要，顯示在對話區。
