/**
 * AI Assistant Module - 後台任務版本
 * 使用輪詢機制，避免阻塞主執行緒
 */
export class AIAssistant {
    constructor(sessionManager) {
        this.sessionManager = sessionManager;
        this.chatMessages = [];
    }

    setupEventListeners() {
        // 生成報告按鈕
        const reportBtn = document.getElementById('btn-generate-report');
        if (reportBtn) {
            reportBtn.addEventListener('click', () => this.generateReport());
        }

        // 聊天發送按鈕
        const sendBtn = document.getElementById('btn-send-chat');
        if (sendBtn) {
            sendBtn.addEventListener('click', () => {
                const chatInput = document.getElementById('chat-input');
                if (chatInput) {
                    this.sendMessage(chatInput.value);
                }
            });
        }

        // Enter 鍵發送
        const chatInput = document.getElementById('chat-input');
        if (chatInput) {
            chatInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    this.sendMessage(chatInput.value);
                }
            });
        }
    }

    async generateReport() {
        const sessionId = this.sessionManager.sessionId;
        const contentDiv = document.getElementById('ai-report-content');

        // 顯示載入狀態
        contentDiv.innerHTML = '<div class="ai-bubble chat-bubble">⏳ 正在分析數據，請稍候...<br><small>（後台處理中，不會影響其他功能）</small></div>';

        try {
            // 步驟 1：發送請求，立即獲得 job_id
            const response = await fetch(`/api/ai/report?session_id=${sessionId}`);

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();
            const jobId = data.job_id;

            if (!jobId) {
                throw new Error('未收到 job_id');
            }

            // 步驟 2：輪詢結果（最多 45 秒）
            await this._pollJobStatus(jobId, 'report', contentDiv, 45000);

        } catch (err) {
            console.error('Report generation error:', err);
            contentDiv.innerHTML = `<div class="ai-bubble chat-bubble">❌ 生成報告時發生錯誤：${err.message}<br><br>請檢查：<br>1. 是否已載入模擬數據<br>2. LLM 服務是否正常運作</div>`;
        }
    }

    async sendMessage(message) {
        if (!message.trim()) return;

        const sessionId = this.sessionManager.sessionId;
        const contentDiv = document.getElementById('ai-report-content');

        // 添加用戶消息
        this.chatMessages.push({ role: 'user', content: message });
        this._appendMessage('user', message);

        // 清空輸入框
        const chatInput = document.getElementById('chat-input');
        if (chatInput) chatInput.value = '';

        // 顯示思考中狀態
        const thinkingDiv = document.createElement('div');
        thinkingDiv.className = 'ai-bubble chat-bubble thinking-indicator';
        thinkingDiv.innerHTML = '🤔 思考中...<br><small>（後台處理，不影響其他功能）</small>';
        thinkingDiv.id = 'thinking-indicator';
        contentDiv.appendChild(thinkingDiv);
        contentDiv.scrollTop = contentDiv.scrollHeight;

        try {
            // 步驟 1：發送請求，立即獲得 job_id
            const response = await fetch('/api/ai/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    messages: this.chatMessages,
                    session_id: sessionId
                })
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();
            const jobId = data.job_id;

            if (!jobId) {
                throw new Error('未收到 job_id');
            }

            // 步驟 2：輪詢結果（最多 45 秒）
            await this._pollChatStatus(jobId, 45000);

        } catch (err) {
            // 移除思考指示器
            const indicator = document.getElementById('thinking-indicator');
            if (indicator) indicator.remove();

            console.error('Chat error:', err);
            this._appendMessage('assistant', `❌ 發生錯誤：${err.message}\n\n請檢查 LLM 服務是否正常運作`);
        }
    }

    async _pollJobStatus(jobId, type, contentDiv, timeout = 45000) {
        // 輪詢任務狀態（用於報告生成）
        const startTime = Date.now();
        const pollInterval = setInterval(async () => {
            try {
                const statusResp = await fetch(`/api/ai/${type}_status/${jobId}`);
                const status = await statusResp.json();

                if (status.status === 'completed') {
                    clearInterval(pollInterval);
                    if (status.report) {
                        contentDiv.innerHTML = `<div class="ai-bubble chat-bubble">${status.report}</div>`;
                    } else {
                        contentDiv.innerHTML = '<div class="ai-bubble chat-bubble">❌ 無法生成報告：回應中沒有內容</div>';
                    }
                } else if (status.status === 'error') {
                    clearInterval(pollInterval);
                    contentDiv.innerHTML = `<div class="ai-bubble chat-bubble">❌ 生成報告時發生錯誤：${status.error}</div>`;
                } else if (Date.now() - startTime > timeout) {
                    // 超時
                    clearInterval(pollInterval);
                    contentDiv.innerHTML = `<div class="ai-bubble chat-bubble">❌ 請求超時 (${timeout / 1000}秒)。LLM 服務回應較慢，請稍後重試。</div>`;
                }
                // 否則繼續輪詢（status === 'processing'）
            } catch (pollErr) {
                clearInterval(pollInterval);
                console.error('Polling error:', pollErr);
                contentDiv.innerHTML = '<div class="ai-bubble chat-bubble">❌ 查詢狀態時發生錯誤</div>';
            }
        }, 1000); // 每秒輪詢一次
    }

    async _pollChatStatus(jobId, timeout = 45000) {
        // 輪詢聊天狀態
        const startTime = Date.now();
        const pollInterval = setInterval(async () => {
            try {
                const statusResp = await fetch(`/api/ai/chat_status/${jobId}`);
                const status = await statusResp.json();

                if (status.status === 'completed') {
                    clearInterval(pollInterval);
                    // 移除思考指示器
                    const indicator = document.getElementById('thinking-indicator');
                    if (indicator) indicator.remove();

                    // 添加 AI 回覆
                    if (status.reply) {
                        this.chatMessages.push({ role: 'assistant', content: status.reply });
                        this._appendMessage('assistant', status.reply);
                    } else {
                        this._appendMessage('assistant', '❌ AI 回覆為空，請重試');
                    }
                } else if (status.status === 'error') {
                    clearInterval(pollInterval);
                    // 移除思考指示器
                    const indicator = document.getElementById('thinking-indicator');
                    if (indicator) indicator.remove();

                    this._appendMessage('assistant', `❌ 發生錯誤：${status.error}`);
                } else if (Date.now() - startTime > timeout) {
                    // 超時
                    clearInterval(pollInterval);
                    // 移除思考指示器
                    const indicator = document.getElementById('thinking-indicator');
                    if (indicator) indicator.remove();

                    this._appendMessage('assistant', `❌ 請求超時 (${timeout / 1000}秒)。LLM 服務回應較慢，請稍後重試。`);
                }
                // 否則繼續輪詢（status === 'processing'）
            } catch (pollErr) {
                clearInterval(pollInterval);
                console.error('Polling error:', pollErr);
                // 移除思考指示器
                const indicator = document.getElementById('thinking-indicator');
                if (indicator) indicator.remove();

                this._appendMessage('assistant', '❌ 查詢狀態時發生錯誤');
            }
        }, 1000); // 每秒輪詢一次
    }

    _appendMessage(role, content) {
        const contentDiv = document.getElementById('ai-report-content');
        const bubbleClass = role === 'user' ? 'user-bubble' : 'ai-bubble';
        const messageDiv = document.createElement('div');
        messageDiv.className = `${bubbleClass} chat-bubble`;
        messageDiv.textContent = content;
        contentDiv.appendChild(messageDiv);

        // 自動滾動到底部
        contentDiv.scrollTop = contentDiv.scrollHeight;
    }

    reset() {
        this.chatMessages = [];
        const contentDiv = document.getElementById('ai-report-content');
        if (contentDiv) {
            contentDiv.innerHTML = '<div class="ai-bubble chat-bubble">歡迎使用 AI 診斷助手！<br><br>點擊「專家分析」獲取即時診斷報告，或在下方輸入問題與 AI 對話。</div>';
        }
    }
}
