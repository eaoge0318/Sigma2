class IntelligentAnalysis {
    constructor() {
        this.sessionId = localStorage.getItem('sigma2_session_id') || 'default';
        this.currentFileId = null;
        this.currentFilename = null;
        this.conversationId = 'default';
        this.analysisMode = 'fast'; // 'fast' or 'full'
        this.isLoading = false;

        // DOM Elements
        this.elements = {
            // Main Chat
            chatContainer: document.getElementById('chat-container'),
            userInput: document.getElementById('user-input'),
            btnSend: document.getElementById('btn-send'),
            welcomeScreen: document.getElementById('welcome-screen'),
            btnAttach: document.getElementById('btn-attach'),
            fileAttachment: document.getElementById('file-attachment'),

            // Sidebar - File
            fileSelect: document.getElementById('file-select'),
            fileInfoPanel: document.getElementById('file-info-panel'),
            fileLoadingIndicator: document.getElementById('file-loading-indicator'),
            infoFilename: document.getElementById('info-filename'),
            infoRows: document.getElementById('info-rows'),
            infoCols: document.getElementById('info-cols'),
            infoStatus: document.getElementById('info-status'),

            // Sidebar - History
            historyList: document.getElementById('history-list'),
            btnClearHistory: document.getElementById('btn-clear'),

            // Sidebar - Mapping Table
            mappingUploadInput: document.getElementById('mapping-upload-input'),
            mappingFileName: document.getElementById('mapping-file-name')
        };

        this.init();

        if (window.marked) {
            console.log("[Init] Configuring marked v" + (window.marked.version || 'unknown'));
            const renderer = new marked.Renderer();

            // Modern marked (v11+) might pass an object to renderer functions
            renderer.code = function (argsOrCode, ...rest) {
                let code, language;
                if (typeof argsOrCode === 'object' && argsOrCode !== null) {
                    code = argsOrCode.text || "";
                    language = argsOrCode.lang || "";
                } else {
                    code = argsOrCode || "";
                    language = rest[0] || "";
                }

                console.log(`🛠️ [marked] Processing code block. Lang: ${language}, Code length: ${code.length}`);

                const lang = (language || '').toLowerCase();
                const safeCode = (code || '').toString();

                if (lang === 'json' || !lang) {
                    const trimmed = safeCode.trim();
                    if (trimmed.startsWith('{') && (trimmed.includes('"type": "chart"') || trimmed.includes('"type":"chart"'))) {
                        console.log("[marked] Detected Chart JSON block!");
                        try {
                            // Ensure valid JSON before embedding
                            JSON.parse(safeCode);
                            return `<div class="chart-container" style="position: relative; height: 300px; width: 100%; margin: 10px 0;">
                                <canvas data-chart="${encodeURIComponent(safeCode)}"></canvas>
                            </div>`;
                        } catch (e) {
                            console.error("[marked] Chart JSON parsing failed inside renderer:", e);
                        }
                    }
                }

                if (lang === 'mermaid') {
                    return `<div class="mermaid">${safeCode}</div>`;
                }

                return `<pre><code class="language-${language || ''}">${safeCode}</code></pre>`;
            };

            marked.use({ renderer });
        }
    }

    async init() {
        this.bindEvents();
        await this.loadFileList();
        await this.checkMappingStatus();
        // this.loadHistory(); // Future: Load chat history
    }

    bindEvents() {
        // Auto-resize textarea
        this.elements.userInput.addEventListener('input', (e) => {
            e.target.style.height = 'auto';
            e.target.style.height = (e.target.scrollHeight) + 'px';
            if (e.target.value.trim().length > 0) {
                this.elements.btnSend.disabled = false;
            } else {
                this.elements.btnSend.disabled = true;
            }
        });

        // Enter to send
        this.elements.userInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                // Check if loading to decide action
                if (this.isLoading) {
                    return; // Do nothing if loading
                }
                this.sendMessage();
            }
        });

        // Send / Stop Button Logic
        this.elements.btnSend.addEventListener('click', () => {
            if (this.isLoading) {
                this.stopGeneration();
            } else {
                this.sendMessage();
            }
        });

        // File Selection Change
        this.elements.fileSelect.addEventListener('change', (e) => {
            const fileId = e.target.value;
            if (fileId) {
                const selectedOption = e.target.options[e.target.selectedIndex];
                const filename = selectedOption.text.replace(' (已索引)', ''); // Clean up text if needed
                this.handleFileSelect(fileId, filename);
            }
        });

        // Attachment Button
        this.elements.btnAttach.addEventListener('click', () => {
            this.elements.fileAttachment.click();
        });

        this.elements.mappingUploadInput.addEventListener('change', (e) => {
            if (e.target.files.length > 0) {
                this.handleMappingUpload(e.target.files[0]);
            }
        });

        // Clear History (Sidebar)
        this.elements.btnClearHistory.addEventListener('click', () => {
            if (confirm('確定要清除所有歷史記錄嗎？')) {
                this.elements.historyList.innerHTML = '<div class="text-xs text-gray-300 text-center py-4">暫無歷史記錄</div>';
            }
        });

        // Suggested Queries Click
        this.elements.chatContainer.addEventListener('click', (e) => {
            const btn = e.target.closest('.suggested-query');
            if (btn) {
                const query = btn.textContent.trim();
                this.elements.userInput.value = query;
                this.elements.userInput.style.height = 'auto'; // Reset height
                this.elements.userInput.style.height = this.elements.userInput.scrollHeight + 'px';
                this.elements.btnSend.disabled = false;
                this.sendMessage();
            }
        });
    }

    async sendMessage() {
        const message = this.elements.userInput.value.trim();
        if (!message || this.isLoading) return;

        if (!this.currentFileId) {
            alert('請先選擇一個要分析的文件！');
            return;
        }

        // 1. Show User Message
        this.addMessage('user', message);
        this.elements.userInput.value = '';
        this.elements.userInput.style.height = 'auto';

        // Switch Send button to Stop button
        this.updateSendButtonState('stop');
        this.isLoading = true;

        // Init AbortController
        this.abortController = new AbortController();
        const signal = this.abortController.signal;

        try {
            // 2. Start Request
            const response = await fetch('/api/analysis/chat/stream', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    session_id: this.sessionId,
                    file_id: this.currentFileId,
                    message: message,
                    conversation_id: this.conversationId,
                    mode: this.analysisMode
                }),
                signal: signal // Attach signal
            });

            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || '請求失敗');
            }

            // 3. Create Streaming Message Row
            const streamState = this.createStreamingMessageRow();
            this.elements.chatContainer.appendChild(streamState.row);
            this.scrollToBottom();

            // Start Timer
            this.startTimer(streamState);

            // 4. Read Stream
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            let currentEventName = null;

            try {
                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;

                    buffer += decoder.decode(value, { stream: true });
                    const lines = buffer.split('\n');
                    buffer = lines.pop();

                    for (const line of lines) {
                        if (line.startsWith('event: ')) {
                            currentEventName = line.slice(7).trim();
                        } else if (line.startsWith('data: ')) {
                            try {
                                const jsonStr = line.slice(6);
                                let eventData = {};
                                try {
                                    eventData = JSON.parse(jsonStr);
                                } catch (e) {
                                    // Handle raw string data (like status messages)
                                    eventData = { content: jsonStr };
                                }

                                // Inject event type if missing
                                if (currentEventName && !eventData.type) {
                                    eventData.type = currentEventName;
                                }

                                this.handleStreamEvent(streamState, eventData);
                                currentEventName = null; // Reset for next event
                            } catch (e) {
                                console.error('SSE Parse Error', e);
                            }
                        }
                    }
                }
            } catch (readError) {
                if (readError.name === 'AbortError') {
                    this.addMessage('system', '生成已手動停止');
                } else {
                    throw readError;
                }
            }

        } catch (error) {
            if (error.name !== 'AbortError') {
                this.addMessage('assistant', `錯誤: ${error.message}`);
            }
        } finally {
            this.isLoading = false;
            this.stopTimer();
            this.updateSendButtonState('send');
            this.abortController = null;
        }
    }

    stopGeneration() {
        if (this.abortController) {
            this.abortController.abort();
        }
    }

    startTimer(state) {
        if (this.timerInterval) clearInterval(this.timerInterval);
        const startTime = Date.now();
        state.statusText = '思考中...';

        const update = () => {
            const elapsed = Math.floor((Date.now() - startTime) / 1000);
            const text = `${state.statusText} (${elapsed}s)`;

            if (state.timerLabel) state.timerLabel.textContent = text;
            if (state.detailsLabel) state.detailsLabel.textContent = text;
        };

        update(); // Initial
        this.timerInterval = setInterval(update, 1000);
    }

    stopTimer() {
        if (this.timerInterval) {
            clearInterval(this.timerInterval);
            this.timerInterval = null;
        }
    }

    updateSendButtonState(state) {
        const btn = this.elements.btnSend;
        if (state === 'stop') {
            btn.innerHTML = `
                <span>停止</span>
                <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="currentColor" viewBox="0 0 24 24">
                    <rect x="6" y="6" width="12" height="12" rx="2" />
                </svg>
            `;
            btn.title = '停止生成';
            btn.classList.add('bg-gray-500', 'hover:bg-gray-600');
            btn.classList.remove('bg-blue-500', 'hover:bg-blue-600');
            btn.disabled = false;
        } else {
            btn.innerHTML = `<span>發送</span>`;
            btn.title = '發送訊息';
            btn.classList.remove('bg-gray-500', 'hover:bg-gray-600');
            btn.classList.add('bg-blue-500', 'hover:bg-blue-600');
            btn.disabled = false;
        }
    }

    async loadFileList() {
        try {
            const response = await fetch(`/api/files/list?session_id=${this.sessionId}`);
            const data = await response.json();

            const select = this.elements.fileSelect;
            select.innerHTML = '<option value="" disabled selected>-- 請選擇檔案 --</option>';

            // Store files for lookup
            this.files = data.files;

            if (data.files.length === 0) {
                const opt = document.createElement('option');
                opt.text = "無可用文件";
                opt.disabled = true;
                select.appendChild(opt);
                return;
            }

            data.files.forEach(file => {
                const opt = document.createElement('option');
                opt.value = file.filename; // Use filename as value for prepare API
                opt.text = file.filename;
                // Mark if indexed visually? In dropdown it's hard.
                if (file.is_indexed) {
                    opt.text += ' (已索引)';
                }
                select.appendChild(opt);
            });

            // Auto-select first file if available -> Disabled by user request
            // if (data.files.length > 0) {
            //     const firstFile = data.files[0];
            //     select.value = firstFile.filename;
            //     this.handleFileSelect(firstFile.file_id, firstFile.filename);
            // }

        } catch (error) {
            console.error("Failed to load files", error);
            this.elements.fileSelect.innerHTML = '<option disabled>加載失敗</option>';
        }
    }

    async handleFileSelect(fileId, filename) {
        // Show Loading in Info Panel
        this.elements.fileInfoPanel.classList.add('hidden');
        this.elements.fileLoadingIndicator.classList.remove('hidden');

        // Reset Chat if new file (Keep Welcome Screen!)
        // Remove all message rows
        const messages = this.elements.chatContainer.querySelectorAll('.message-row');
        messages.forEach(msg => msg.remove());

        // Remove any other dynamic elements except welcome screen
        Array.from(this.elements.chatContainer.children).forEach(child => {
            if (child.id !== 'welcome-screen' && !child.classList.contains('message-row')) {
                child.remove();
            }
        });

        if (this.elements.welcomeScreen) {
            this.elements.welcomeScreen.classList.remove('hidden');
        }

        try {
            // Find file object to check if indexed (optimistic)
            const fileObj = this.files.find(f => f.filename === filename);

            // API Call
            const res = await fetch('/api/analysis/prepare', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    filename: filename,
                    session_id: this.sessionId
                })
            });

            if (!res.ok) throw new Error('索引建立失敗');
            const result = await res.json();

            this.currentFileId = result.file_id;
            this.currentFilename = filename;

            const summary = result.summary || {};

            // Update Info Panel
            this.elements.infoRows.textContent = summary.total_rows ? summary.total_rows.toLocaleString() : '-';
            this.elements.infoCols.textContent = summary.total_columns || '-';
            this.elements.infoStatus.textContent = '已就緒';

            // Show Panel
            this.elements.fileLoadingIndicator.classList.add('hidden');
            this.elements.fileInfoPanel.classList.remove('hidden');

            // Enable Input and Focus
            this.elements.userInput.disabled = false;
            this.elements.userInput.focus();

            // Note: We keep the welcome screen until user interacts
            // The "File Ready" message will be added but hidden under welcome screen?
            // Or should we NOT add it if welcome screen is shown?
            // Let's add it, but it will be hidden until welcome screen is dismissed.
            const totalRows = summary.total_rows || 0;
            const totalCols = summary.total_columns || 0;
            this.addMessage('assistant', `已切換至文件 **${filename}**。\n我已經分析了數據結構，共 **${totalRows}** 行數據，包含 **${totalCols}** 個欄位。`);

        } catch (error) {
            alert(`文件準備失敗: ${error.message}`);
            this.elements.fileLoadingIndicator.classList.add('hidden');
            this.elements.fileSelect.value = ""; // Reset selection
        }
    }

    // --- UI Helpers ---

    addMessage(role, content, allToolCalls = null, thoughts = null, animate = false) {
        // Hide welcome screen when adding a user message (interaction starts)
        // OR if the assistant sends a message (e.g. file ready), should we hide it?
        // User wants "Restore to beginning". Beginning has shortcuts.
        // If we hide it immediately on "File Ready", shortcuts are gone.
        // So ONLY hide on USER message.
        if (role === 'user' && this.elements.welcomeScreen) {
            this.elements.welcomeScreen.classList.add('hidden');
        }

        const div = document.createElement('div');
        div.className = `message-row ${role}`;

        let toolHtml = '';

        // --- 思考與工具整合展示 ---
        if ((thoughts && thoughts.length > 0) || (allToolCalls && allToolCalls.length > 0)) {
            // Check if thoughts contain "Thinking..." tags and format them
            // No, backend already formatted them.

            toolHtml += `
                <details class="workflow-details mb-3 group">
                    <summary>
                        <svg class="w-3.5 h-3.5 group-open:rotate-90 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path></svg>
                        <span class="thought-label">分析完成</span>
                    </summary>
                    <div class="details-content mt-2 space-y-3">
            `;

            if (thoughts && thoughts.length > 0) {
                toolHtml += '<div class="ai-thoughts p-2.5 bg-blue-50/20 border-l-2 border-blue-400 rounded-r text-sm text-slate-600 italic font-light">';
                toolHtml += '<div class="text-[10px] font-bold text-blue-500 uppercase tracking-widest mb-1 opacity-60">AI 思考流程</div>';
                thoughts.forEach(t => {
                    toolHtml += `<div class="mb-1.5 last:mb-0 line-clamp-3 hover:line-clamp-none cursor-default transition-all">💭 ${t}</div>`;
                });
                toolHtml += '</div>';
            }

            if (allToolCalls && allToolCalls.length > 0) {
                toolHtml += '<div class="tool-execution-chain space-y-2">';
                allToolCalls.forEach((call, index) => {
                    const toolName = call.tool || '未知工具';
                    const toolParams = call.params ? JSON.stringify(call.params) : '';
                    const toolResult = call.result;

                    toolHtml += `
                        <div class="tool-step border-l-2 border-blue-200 pl-3 py-1 bg-slate-50/50 rounded-r">
                            <div class="text-[11px] text-slate-500 flex items-center gap-1.5 font-medium">
                                <span class="flex items-center justify-center w-4 h-4 rounded-full bg-blue-100 text-blue-600 text-[9px]">${index + 1}</span>
                                執行分析: <span class="text-blue-700 font-mono">${toolName}</span>
                                <span class="ml-auto text-[9px] text-green-600 bg-green-50 px-1 rounded">完成</span>
                            </div>
                            ${toolParams ? `<div class="text-[10px] text-slate-400 font-mono mt-0.5 ml-5 truncate" title='${toolParams}'>參數: ${toolParams}</div>` : ''}
                            
                            <details class="mt-1 ml-5">
                                <summary class="text-[10px] text-blue-500/80 cursor-pointer hover:text-blue-600 transition-colors w-fit">查看執行結果</summary>
                                <div class="mt-1 p-2 bg-white border border-slate-100 rounded shadow-sm overflow-auto max-h-48">
                                    <pre class="tool-result-pre text-[10px] text-slate-600 font-mono leading-tight whitespace-pre-wrap">${typeof toolResult === 'object' ? JSON.stringify(toolResult, null, 2) : toolResult}</pre>
                                </div>
                            </details>
                        </div>
                    `;
                });
                toolHtml += '</div>';
            }

            toolHtml += '</div></details>';
        }

        // 決定是否立即渲染 Markdown
        let contentHtml = '';
        if (animate && role === 'assistant') {
            // 打字機模式：先放一個佔位符
            contentHtml = '<span class="typing-output"></span><span class="typing-cursor">▍</span>';
        } else {
            // 一般模式：直接渲染
            contentHtml = marked.parse(content);
        }

        div.innerHTML = `
            <div class="message-bubble prose prose-sm max-w-none">
                ${toolHtml}
                <div class="markdown-body">${contentHtml}</div>
            </div>
        `;

        this.elements.chatContainer.appendChild(div);
        this.scrollToBottom();

        // 如果需要動畫，啟動打字機
        if (animate && role === 'assistant') {
            const targetEl = div.querySelector('.typing-output');
            const cursorEl = div.querySelector('.typing-cursor');
            this.typeWriter(targetEl, cursorEl, content);
        }

        return div;
    }

    typeWriter(targetEl, cursorEl, text) {
        let i = 0;
        const speed = 1;  // 縮短間隔 (1ms)
        const chunk = 5;  // 增加每次跳出的字數

        targetEl.textContent = '';

        const timer = setInterval(() => {
            if (i < text.length) {
                targetEl.textContent += text.substr(i, chunk);
                i += chunk;
                this.scrollToBottom();
            } else {
                clearInterval(timer);
                // 打字結束：移除光標，渲染最終 Markdown
                if (cursorEl) cursorEl.remove();

                // 將純文本替換為渲染後的 Markdown
                const parent = targetEl.parentElement; // .markdown-body
                parent.innerHTML = marked.parse(text);

                this.scrollToBottom();
            }
        }, speed);
    }

    createStreamingMessageRow() {
        const row = document.createElement('div');
        row.className = 'message-row assistant';

        // 基本結構
        row.innerHTML = `
            <div class="message-bubble prose prose-sm max-w-none">
                <!-- 思考與工具執行詳情 (使用 details 以便縮放) -->
                <details class="workflow-details mb-3 group" open>
                    <summary>
                        <svg class="w-3.5 h-3.5 group-open:rotate-90 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path></svg>
                        <span class="thought-label">Thought for 0s</span>
                    </summary>
                    
                    <div class="details-content mt-2 space-y-3">
                        <!-- 狀態日誌 (新增) -->
                        <div class="status-log space-y-1 text-xs text-gray-600 font-mono border-l-2 border-gray-300 pl-2 bg-gray-50/50 py-1 rounded-r"></div>

                        <!-- 思考區塊 -->
                        <div class="ai-thoughts p-2.5 bg-blue-50/20 border-l-2 border-blue-400 rounded-r hidden">
                            <div class="text-[10px] font-bold text-blue-500 uppercase tracking-widest mb-1 opacity-60">AI 思考流程</div>
                            <div class="thoughts-content space-y-1"></div>
                        </div>
                        
                        <!-- 工具鏈區塊 -->
                        <div class="tool-execution-chain space-y-2 hidden"></div>
                    </div>
                </details>
                
                <!-- 回應內容區塊 -->
                <div class="markdown-body">
                    <span class="typing-output"></span><span class="typing-cursor">▍</span>
                </div>
            </div>
        `;

        return {
            row: row,
            detailsWrapper: row.querySelector('.workflow-details'),
            detailsLabel: row.querySelector('.thought-label'),
            statusLog: row.querySelector('.status-log'),
            thoughtsContainer: row.querySelector('.ai-thoughts'),
            thoughtsContent: row.querySelector('.thoughts-content'),
            toolsContainer: row.querySelector('.tool-execution-chain'),
            contentOutput: row.querySelector('.typing-output'),
            cursorCb: row.querySelector('.typing-cursor'),
            typingIndicator: row.querySelector('.typing-indicator'),
            timerLabel: row.querySelector('.timer-label'),
            markdownBody: row.querySelector('.markdown-body'),
            fullText: '' // 用於存儲原始 Markdown 文字，實作即時渲染
        };
    }

    updateMarkdown(state) {
        if (!state.markdownBody) return;
        try {
            // 提供除錯資訊
            if (state.fullText && state.fullText.includes('[object Object]')) {
                console.warn("[Markdown] fullText contains [object Object] during updateMarkdown.");
            }

            state.markdownBody.innerHTML = marked.parse(state.fullText || '');

            // 渲染完成後，觸發圖表解析
            this.renderCharts(state.markdownBody);
        } catch (e) {
            console.error("Markdown rendering error:", e);
        }
    }

    handleStreamEvent(state, event) {
        // --- 核心除錯日誌 (由用戶要求加強) ---
        console.log("[SSE Event]", event);

        // 移除思考中指示器 和 timer (僅在最終回應或出錯時)
        if (state.typingIndicator && !state.typingIndicator.classList.contains('hidden')) {
            if (event.type === 'response' || event.type === 'error') {
                state.typingIndicator.classList.add('hidden');
                this.stopTimer();
            }
        }

        switch (event.type) {
            case 'thought':
                // 強制展開細節區域
                if (state.detailsWrapper) state.detailsWrapper.open = true;
                state.thoughtsContainer.classList.remove('hidden');
                const tDiv = document.createElement('div');
                tDiv.className = "mb-1.5 last:mb-0 line-clamp-3 hover:line-clamp-none cursor-default transition-all";
                tDiv.textContent = `Thought: ${event.content}`;
                state.thoughtsContent.appendChild(tDiv);
                this.scrollToBottom();
                break;

            case 'tool_call':
                // 強制展開細節區域
                if (state.detailsWrapper) state.detailsWrapper.open = true;
                state.toolsContainer.classList.remove('hidden');
                const toolIndex = state.toolsContainer.children.length + 1;
                const toolDiv = document.createElement('div');
                toolDiv.className = "tool-step border-l-2 border-blue-200 pl-3 py-1 bg-slate-50/50 rounded-r";
                toolDiv.dataset.toolName = event.tool;

                const paramsStr = JSON.stringify(event.params || {});

                toolDiv.innerHTML = `
                    <div class="text-[11px] text-slate-500 flex items-center gap-1.5 font-medium">
                        <span class="flex items-center justify-center w-4 h-4 rounded-full bg-blue-100 text-blue-600 text-[9px]">${toolIndex}</span>
                        執行分析: <span class="text-blue-700 font-mono">${event.tool}</span>
                        <span class="tool-status ml-auto text-[9px] text-yellow-600 bg-yellow-50 px-1 rounded">執行中...</span>
                    </div>
                    <div class="text-[10px] text-slate-400 font-mono mt-0.5 ml-5 truncate" title='${paramsStr}'>參數: ${paramsStr}</div>
                    <details class="mt-1 ml-5 hidden result-details">
                        <summary class="text-[10px] text-blue-500/80 cursor-pointer hover:text-blue-600 transition-colors w-fit">查看執行結果</summary>
                        <div class="mt-1 p-2 bg-white border border-slate-100 rounded shadow-sm overflow-auto max-h-48">
                            <pre class="tool-result-pre text-[10px] text-slate-600 font-mono leading-tight whitespace-pre-wrap">...</pre>
                        </div>
                    </details>
                `;
                state.toolsContainer.appendChild(toolDiv);
                this.scrollToBottom();
                break;

            case 'text_chunk':
                let chunk = event.content;
                if (typeof chunk !== 'string') {
                    try {
                        chunk = JSON.stringify(chunk);
                    } catch (e) {
                        chunk = String(chunk);
                    }
                }
                if (chunk === '[object Object]') {
                    console.error("[Analysis] Caught literal [object Object] in text_chunk event!");
                    return;
                }
                state.fullText += chunk;
                this.updateMarkdown(state);
                this.scrollToBottom();
                break;

            case 'status':
                // Append to log instead of replacing statusText header
                if (event.content && state.statusLog) {
                    const logItem = document.createElement('div');
                    logItem.textContent = event.content;
                    // Add a small timestamp? Optional.
                    // logItem.textContent = `[${new Date().toLocaleTimeString()}] ${event.content}`;
                    state.statusLog.appendChild(logItem);
                    // 修正：狀態更新時也必須滾動，否則思考過程會被擋住
                    this.scrollToBottom();
                }
                break;

            case 'tool_result':
                // state.statusText = '分析數據中...'; // Managed by backend ProgressEvent
                // 找到對應的 tool (假設順序一致，或最後一個)
                // 簡單起見，找最後一個 tool step
                const lastTool = state.toolsContainer.lastElementChild;
                if (lastTool) {
                    const statusSpan = lastTool.querySelector('.tool-status');
                    if (statusSpan) {
                        statusSpan.textContent = "完成";
                        statusSpan.className = "tool-status ml-auto text-[9px] text-green-600 bg-green-50 px-1 rounded";
                    }

                    const details = lastTool.querySelector('.result-details');
                    const pre = lastTool.querySelector('.tool-result-pre');
                    if (details && pre) {
                        details.classList.remove('hidden');
                        let resStr = event.result;
                        if (resStr === '[object Object]') {
                            console.warn("[tool_result] Received literal [object Object] string from backend.");
                            resStr = '{"status": "error", "message": "工具回傳內容損毀 (Received [object Object] string)"}';
                        }

                        try {
                            if (typeof resStr === 'object' && resStr !== null) {
                                resStr = JSON.stringify(resStr, null, 2);
                            } else if (typeof resStr === 'string' && (resStr.startsWith('{') || resStr.startsWith('['))) {
                                try {
                                    resStr = JSON.stringify(JSON.parse(resStr), null, 2);
                                } catch (e) { /* ignore parse error for raw string */ }
                            }
                        } catch (e) {
                            console.error("[tool_result] Error processing tool result:", e);
                            resStr = String(resStr);
                        }

                        // Ensure it's never an object before setting textContent
                        if (typeof resStr === 'object') {
                            resStr = JSON.stringify(resStr);
                        }

                        pre.textContent = resStr;
                    }
                }
                // 修正：工具結果回傳後通常內容很長，必須觸發滾動
                this.scrollToBottom();
                break;

            case 'content':
                // 已廢棄：回歸 text_chunk 命名
                break;

            case 'response':
                // 串流結束後的最終校驗與渲染
                if (state.markdownBody) {
                    let backendContent = event.content || event.summary;
                    let finalContent = state.fullText;

                    if (backendContent && typeof backendContent === 'string' && !backendContent.includes('[object Object]') && backendContent.length >= state.fullText.length) {
                        finalContent = backendContent;
                    }

                    // 最終 Markdown 渲染 (包含圖表)
                    state.markdownBody.innerHTML = marked.parse(finalContent);
                    this.renderCharts(state.markdownBody);

                    // 渲染 Mermaid 圖表 (如果有)
                    if (finalContent.includes('```mermaid')) {
                        setTimeout(() => {
                            if (window.mermaid) {
                                window.mermaid.initialize({ startOnLoad: false, theme: 'neutral' });
                                window.mermaid.init(undefined, state.markdownBody.querySelectorAll('.mermaid'));
                            }
                        }, 50);
                    }

                    // 渲染 Chart.js 圖表
                    setTimeout(() => {
                        this.renderCharts(state.markdownBody);
                    }, 50);
                }

                if (state.cursorCb) state.cursorCb.remove(); // 移除殘留光標

                // --- 分析結束後縮起來 ---
                if (state.detailsWrapper) {
                    state.detailsWrapper.open = false; // 自動折疊
                    if (state.detailsLabel) {
                        const currentText = state.detailsLabel.textContent;
                        // 轉換為已完成狀態
                        state.detailsLabel.textContent = currentText.replace('思考中...', '分析完成');
                        state.detailsLabel.classList.add('opacity-70');
                    }
                }

                this.scrollToBottom();
                break;

            case 'error':
                state.contentOutput.textContent += `❌ ${event.content}`;
                break;
        }
    }

    addLoadingMessage() {
        const id = 'msg-' + Date.now();
        const div = document.createElement('div');
        div.id = id;
        div.className = 'message-row assistant';
        div.innerHTML = `
            <div class="message-bubble bg-gray-50 border-gray-200">
                <div class="flex items-center gap-2">
                    <div class="typing-dots">
                        <div class="typing-dot"></div>
                        <div class="typing-dot"></div>
                        <div class="typing-dot"></div>
                    </div>
                    <span class="text-xs text-gray-400">AI 正在思考中...</span>
                </div>
            </div>
        `;
        this.elements.chatContainer.appendChild(div);
        this.scrollToBottom();
        return id;
    }

    removeMessage(id) {
        const el = document.getElementById(id);
        if (el) el.remove();
    }

    renderCharts(container) {
        if (!window.Chart) {
            console.error("❌ [Chart] Chart.js is NOT loaded!");
            return;
        }

        const canvases = container.querySelectorAll('canvas[data-chart]');
        if (canvases.length > 0) {
            console.log(`🎨 [Chart] Found ${canvases.length} chart placeholders to render.`);
        }
        canvases.forEach(canvas => {
            if (canvas.chartInstance) return; // 避免重複渲染

            try {
                console.log("🎨 [Chart] Raw data-chart attribute (before decode):", canvas.getAttribute('data-chart'));
                // Decode the URI-encoded JSON string
                const jsonStr = decodeURIComponent(canvas.getAttribute('data-chart'));
                console.log("🎨 [Chart] Decoded Chart JSON:", jsonStr);

                // 預防內容為空或 [object Object]
                if (!jsonStr || jsonStr.trim() === "" || jsonStr === "[object Object]") {
                    console.error("🎨 [Chart] Chart content is INVALID [object Object] or empty!");
                    return;
                }

                const data = JSON.parse(jsonStr);
                if (data.type !== 'chart') {
                    console.warn("🎨 [Chart] JSON structure is not a chart type, skipping.");
                    return;
                }

                if (data.type === 'chart') {
                    const ctx = canvas.getContext('2d');
                    const chartConfig = {
                        type: data.chart_type || 'line',
                        data: {
                            labels: data.labels,
                            datasets: data.datasets.map(ds => ({
                                ...ds,
                                borderColor: ds.borderColor || this.getRandomColor(),
                                backgroundColor: ds.backgroundColor || this.getRandomColor(0.2),
                                borderWidth: 2,
                                tension: 0.1,
                                borderRadius: (data.chart_type === 'bar') ? 4 : 0,
                                barPercentage: (data.chart_type === 'bar') ? 0.8 : 0.9,
                                // 如果是散佈圖，Chart.js 需要 data 為物件列表 [{x, y}]
                                // 我們在後端處理好，這裡直接透傳
                            }))
                        },
                        options: {
                            responsive: true,
                            maintainAspectRatio: false,
                            scales: {
                                y: {
                                    beginAtZero: true,
                                    grid: { color: 'rgba(0,0,0,0.05)' }
                                },
                                x: {
                                    grid: { display: false }
                                },
                                // 合併後端傳來的自定義 Scales (如 y1 軸)
                                ...(data.options?.scales || {})
                            },
                            plugins: {
                                title: {
                                    display: !!data.title,
                                    text: data.title || ''
                                },
                                legend: {
                                    position: 'top',
                                },
                                // 合併後端傳來的自定義 Plugins
                                ...(data.options?.plugins || {})
                            },
                            // 合併其餘自定義 Options
                            ...(data.options || {})
                        }
                    };

                    console.log("🎨 [Chart] Final Config:", chartConfig);
                    canvas.chartInstance = new Chart(ctx, chartConfig);
                }
            } catch (e) {
                console.error("Failed to render chart", e);
                canvas.parentNode.innerHTML = `<div class="text-red-500 text-xs">圖表渲染失敗</div>`;
            }
        });
    }

    getRandomColor(alpha = 1) {
        const r = Math.floor(Math.random() * 200);
        const g = Math.floor(Math.random() * 200);
        const b = Math.floor(Math.random() * 200);
        return `rgba(${r}, ${g}, ${b}, ${alpha})`;
    }

    scrollToBottom() {
        const container = this.elements.chatContainer;
        if (!container) return;

        // 增加容錯門檻：如果用戶離底部在 250px 內，都視為「在底部」，應自動滾動
        const threshold = 250;
        const distanceToBottom = container.scrollHeight - container.scrollTop - container.clientHeight;

        if (distanceToBottom < threshold) {
            // 使用自動滾動，並在渲染大量 Markdown 時給予一點點延遲以確保高度計算正確
            container.scrollTop = container.scrollHeight;
        }
    }

    formatSize(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    async checkMappingStatus() {
        try {
            const response = await fetch(`/api/analysis/mapping-status?session_id=${this.sessionId}`);
            if (response.ok) {
                const data = await response.json();
                if (data.active_mapping) {
                    this.elements.mappingFileName.textContent = data.active_mapping;
                    this.elements.mappingFileName.classList.add('text-blue-600');
                    this.elements.mappingFileName.classList.remove('text-gray-600');
                } else {
                    this.elements.mappingFileName.textContent = '尚未設定';
                    this.elements.mappingFileName.classList.remove('text-blue-600');
                    this.elements.mappingFileName.classList.add('text-gray-600');
                }
            }
        } catch (error) {
            console.error('Failed to check mapping status:', error);
        }
    }

    async handleMappingUpload(file) {
        if (!file) return;

        // Verify it's a CSV
        if (!file.name.endsWith('.csv')) {
            alert('請選擇 CSV 格式的檔案');
            return;
        }

        const formData = new FormData();
        formData.append('file', file);
        formData.append('session_id', this.sessionId);
        formData.append('is_mapping', 'true'); // Flag to tell backend this is a mapping table

        // If a file is currently selected, bind mapping to it
        if (this.currentFileId) {
            formData.append('file_id', this.currentFileId);
            console.log(`Binding mapping to file: ${this.currentFilename} (${this.currentFileId})`);
        }

        try {
            this.elements.mappingFileName.textContent = '上傳中...';
            const response = await fetch('/api/analysis/upload', {
                method: 'POST',
                body: formData
            });

            if (response.ok) {
                const result = await response.json();
                alert('對應表上傳成功！AI 現在能看懂您的專業術語了。');
                await this.checkMappingStatus();
            } else {
                const error = await response.json();
                alert(`上傳失敗: ${error.detail || '未知錯誤'}`);
                await this.checkMappingStatus();
            }
        } catch (error) {
            console.error('Mapping upload error:', error);
            alert('對應表上傳發生錯誤，請檢查網路連線。');
            await this.checkMappingStatus();
        } finally {
            this.elements.mappingUploadInput.value = ''; // Reset input
        }
    }
    setMode(mode) {
        this.analysisMode = mode;
        console.log(`🚀 [Mode] Switched to ${mode}`);

        // Update UI
        const fastBtn = document.getElementById('mode-fast');
        const fullBtn = document.getElementById('mode-full');

        if (mode === 'fast') {
            fastBtn.classList.add('active');
            fullBtn.classList.remove('active');
        } else {
            fullBtn.classList.add('active');
            fastBtn.classList.remove('active');
        }
    }
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    window.ia = new IntelligentAnalysis();
});

// Global accessor for HTML onclick
window.setAnalysisMode = (mode) => {
    if (window.ia) window.ia.setMode(mode);
};
