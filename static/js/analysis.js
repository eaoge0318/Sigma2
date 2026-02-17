class IntelligentAnalysis {
    constructor() {
        // 帳號 ID: 從父視窗繼承 (Dashboard 的 SESSION_ID)，用於隔離不同帳號
        const parentSessionId = window.parent && window.parent.SESSION_ID;
        this.accountId = parentSessionId || localStorage.getItem('sigma2_session_id') || 'default';
        // 聊天室 Session ID: 預設為帳號 ID (主聊天室)
        this.sessionId = this.accountId;
        console.log(`Initialized Analysis: account=${this.accountId}, session=${this.sessionId}`);
        this.currentFileId = null;
        this.currentFilename = null;
        this.conversationId = 'default';
        this.analysisMode = 'fast'; // 'fast' or 'full'
        this.isLoading = false;
        this.currentFileParams = []; // Store current file parameters

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

            // Sidebar - Session Management
            sessionList: document.getElementById('session-list'),
            btnNewChat: document.getElementById('btn-new-chat'),

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

        // New Chat Button
        if (this.elements.btnNewChat) {
            this.elements.btnNewChat.addEventListener('click', () => {
                this.createNewSession();
            });
        }

        // Load existing sessions on startup
        this.loadSessionList();

        // Session click event delegation (一次性綁定，避免重複)
        if (this.elements.sessionList) {
            console.log('[Sessions] Event delegation bound on #session-list');
            this.elements.sessionList.addEventListener('click', (e) => {
                console.log('[Sessions] Click detected on:', e.target.tagName, e.target.className);
                // Delete button
                const deleteBtn = e.target.closest('[data-delete-session]');
                if (deleteBtn) {
                    e.stopPropagation();
                    const sid = deleteBtn.dataset.deleteSession;
                    if (confirm('確定要刪除這個聊天室嗎？')) {
                        this.deleteSession(sid);
                    }
                    return;
                }
                // Session card click
                const item = e.target.closest('.session-item');
                if (item && item.dataset.sessionId) {
                    console.log('[Sessions] Switching to:', item.dataset.sessionId);
                    this.switchSession(item.dataset.sessionId);
                }
            });
        } else {
            console.warn('[Sessions] #session-list element NOT FOUND!');
        }

        // Suggested Queries Click
        // Suggested Queries Click (Modified to listen on body for Sidebar buttons)
        document.body.addEventListener('click', (e) => {
            const btn = e.target.closest('.suggested-query');
            if (btn) {
                const query = (btn.getAttribute('data-query') || btn.innerText).trim();

                // Intercept "Data Mining" Button (Check ID or Text)
                if (btn.id === 'btn-open-mining-modal' || query === '資料探勘') {
                    e.preventDefault();
                    e.stopPropagation();
                    console.log('Opening Data Mining Modal');

                    // Close other popovers
                    const sidebar = document.getElementById('param-select-menu');
                    if (sidebar) sidebar.classList.add('hidden');

                    this.openDataMiningModal();
                    return;
                }

                // Intercept "Draw Trend Chart"
                if (query === '繪製趨勢圖') {
                    e.preventDefault();
                    e.stopPropagation();

                    // Close Mining Modal
                    const miningModal = document.getElementById('data-mining-modal');
                    if (miningModal) miningModal.classList.add('hidden');

                    this.openParamSelectionModal(btn);
                    return;
                }

                this.elements.userInput.value = query;
                this.elements.userInput.style.height = 'auto'; // Reset height
                this.elements.userInput.style.height = this.elements.userInput.scrollHeight + 'px';
                this.elements.btnSend.disabled = false;
                this.sendMessage();
            }
        });

        // Trend Param Keyword Search (Filter the dropdown)
        document.addEventListener('input', (e) => {
            if (e.target.id === 'trend-keyword-input') {
                this.populateParamDropdown(e.target.value);
            }
        });

        // Add Enter Key Shortcut for Trend Search
        document.addEventListener('keydown', (e) => {
            if (e.target.id === 'trend-keyword-input' && e.key === 'Enter') {
                const select = document.getElementById('trend-column-select');
                if (select && select.value) {
                    this.confirmParamSelection();
                } else if (select && select.options.length > 1) {
                    // Auto-select first matching option if none selected
                    select.selectedIndex = 1;
                    this.confirmParamSelection();
                }
            }
        });

        // Global ESC to close modals/popovers
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                const miningModal = document.getElementById('data-mining-modal');
                if (miningModal) miningModal.classList.add('hidden');

                const paramMenu = document.getElementById('param-select-menu');
                if (paramMenu) paramMenu.classList.add('hidden');
            }
        });

        // --- Data Mining Modal Listeners ---
        document.addEventListener('click', (e) => {
            // Opening logic moved to suggested-query listener above
            if (e.target.closest('#btn-close-mining-modal') || e.target.id === 'btn-cancel-mining') {
                const modal = document.getElementById('data-mining-modal');
                if (modal) modal.classList.add('hidden');
            } else if (e.target.closest('#btn-confirm-mining')) {
                this.confirmDataMining();
            } else if (e.target.id === 'dm-target-clear') {
                this.toggleMiningSelection('target', 'none');
            } else if (e.target.id === 'dm-feature-clear') {
                this.toggleMiningSelection('feature', 'none');
            } else if (e.target.id === 'dm-feature-select-all') {
                this.toggleMiningSelection('feature', 'all');
            }
        });

        document.addEventListener('input', (e) => {
            if (e.target.id === 'dm-target-search') {
                this.filterMiningList('target', e.target.value);
            } else if (e.target.id === 'dm-feature-search') {
                this.filterMiningList('feature', e.target.value);
            }
        });
    }

    async sendMessage() {
        const message = this.elements.userInput.value.trim();
        if (!message || this.isLoading) return;

        this.stopRequested = false; // Reset stop state

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
            // Prepare request body
            const requestBody = {
                session_id: this.sessionId,
                file_id: this.currentFileId,
                message: message,
                conversation_id: this.conversationId,
                mode: this.analysisMode
            };

            // Add mining metadata if available
            if (this.miningMetadata) {
                if (this.miningMetadata.suspect_params) {
                    requestBody.suspect_params = this.miningMetadata.suspect_params;
                }
                if (this.miningMetadata.target_range) {
                    requestBody.target_range = this.miningMetadata.target_range;
                }
                // Clear metadata after use
                this.miningMetadata = null;
            }

            // 2. Start Request
            const response = await fetch('/api/analysis/chat/stream', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(requestBody),
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
            this.stopRequested = false; // Ensure reset on finish
        }
    }

    async stopGeneration() {
        // [MODIFIED] Two-stage stop:
        // 1. First click: "Immediate Answer" -> triggers backend summary
        // 2. Second click: "Hard Stop" -> aborts frontend connection

        if (this.stopRequested) {
            // Stage 2: Hard Stop
            if (this.abortController) {
                this.abortController.abort();
                // Visual feedback is handled by AbortError in sendMessage catch block
            }
            return;
        }

        // Stage 1: Request Summary
        this.stopRequested = true;

        // Change button to Hard Stop state immediately
        const btn = this.elements.btnSend;
        btn.innerHTML = `
            <span>停止輸出</span>
            <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
        `;
        btn.classList.remove('bg-gray-500', 'hover:bg-gray-600');
        btn.classList.add('bg-gray-700', 'hover:bg-gray-800');
        btn.title = "強制停止所有輸出";

        if (this.sessionId) {
            try {
                if (this.isLoading) {
                    const lastMsg = this.elements.chatContainer.lastElementChild;
                    if (lastMsg) {
                        const statusLog = lastMsg.querySelector('.status-log');
                        if (statusLog) {
                            const logItem = document.createElement('div');
                            logItem.textContent = "正在請求立即結論... (若太久可再次點擊停止)";
                            logItem.className = "text-orange-600 font-bold";
                            statusLog.appendChild(logItem);
                        }
                    }
                }

                await fetch('/api/analysis/chat/stop', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ session_id: this.sessionId })
                });
            } catch (e) {
                console.error("Failed to send stop signal", e);
                // Fallback: abort if API fails
                if (this.abortController) this.abortController.abort();
            }
        } else {
            if (this.abortController) this.abortController.abort();
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
                <span>立即回答</span>
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
            this.currentFileParams = summary.parameters || []; // Store parameters
            this.currentFileCategories = summary.categories || {}; // Store categories for grouping

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
                            ${false ? `<div class="text-[10px] text-slate-400 font-mono mt-0.5 ml-5 truncate" title='${toolParams}'>參數: ${toolParams}</div>` : ''}
                            
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
            case 'thought':
                // 強制展開細節區域
                if (state.detailsWrapper) state.detailsWrapper.open = true;
                state.thoughtsContainer.classList.remove('hidden');

                // [Enhanced Visualization for QC]
                if (event.content && event.content.includes("【QC 判決】")) {
                    const qcDiv = document.createElement('div');
                    qcDiv.className = "mb-2 p-3 bg-white border border-gray-200 rounded-lg shadow-sm";

                    // Parse Content
                    // Expected Format: "【QC 判決】\n結果: ✅ PASS\n原因: ...\n指引: ..."
                    const lines = event.content.split('\n');
                    const resultLine = lines.find(l => l.includes('結果:')) || '結果: 未知';
                    const reasonLine = lines.find(l => l.includes('原因:')) || '原因: 無';
                    const guideLine = lines.find(l => l.includes('指引:')) || '指引: 無';

                    const isPass = resultLine.includes('✅') || resultLine.includes('PASS');
                    const statusColor = isPass ? 'text-green-600 bg-green-50 border-green-200' : 'text-red-600 bg-red-50 border-red-200';
                    const icon = isPass ? '✅' : '❌';

                    qcDiv.innerHTML = `
                        <div class="flex items-center gap-2 mb-2 pb-2 border-b border-gray-100">
                            <span class="text-lg">⚖️</span>
                            <span class="font-bold text-gray-700 text-sm">品質檢核報告 (QC Report)</span>
                            <span class="ml-auto text-xs font-mono px-2 py-0.5 rounded border ${statusColor}">
                                ${resultLine.split(':')[1].trim()}
                            </span>
                        </div>
                        <div class="space-y-1.5 text-xs">
                            <div class="flex gap-2">
                                <span class="text-gray-400 font-medium min-w-[30px]">原因</span>
                                <span class="text-gray-600">${reasonLine.split(':')[1].trim()}</span>
                            </div>
                            <div class="flex gap-2">
                                <span class="text-gray-400 font-medium min-w-[30px]">指引</span>
                                <span class="text-blue-600 font-medium">${guideLine.split(':')[1].trim()}</span>
                            </div>
                        </div>
                    `;
                    state.thoughtsContent.appendChild(qcDiv);
                } else {
                    // Regular Thought
                    const tDiv = document.createElement('div');
                    tDiv.className = "mb-1.5 last:mb-0 line-clamp-3 hover:line-clamp-none cursor-default transition-all";
                    tDiv.textContent = `Thought: ${event.content}`;
                    state.thoughtsContent.appendChild(tDiv);
                }

                this.scrollToBottom();
                break;

            case 'tool_call':
                // 強制展開細節區域
                if (state.detailsWrapper) state.detailsWrapper.open = true;
                state.toolsContainer.classList.remove('hidden');
                const toolIndex = state.toolsContainer.children.length + 1;
                const toolDiv = document.createElement('div');
                // [MODIFIED] Hide the tool execution block entirely per user request
                toolDiv.className = "tool-step border-l-2 border-blue-200 pl-3 py-1 bg-slate-50/50 rounded-r hidden";
                toolDiv.dataset.toolName = event.tool;

                const paramsStr = JSON.stringify(event.params || {});

                toolDiv.innerHTML = `
                    <div class="text-[11px] text-slate-500 flex items-center gap-1.5 font-medium">
                        <span class="flex items-center justify-center w-4 h-4 rounded-full bg-blue-100 text-blue-600 text-[9px]">${toolIndex}</span>
                        執行分析: <span class="text-blue-700 font-mono">${event.tool}</span>
                        <span class="tool-status ml-auto text-[9px] text-yellow-600 bg-yellow-50 px-1 rounded">執行中...</span>
                    </div>
                    <div class="text-[10px] text-slate-400 font-mono mt-0.5 ml-5 truncate hidden" title='${paramsStr}'>參數: ${paramsStr}</div>
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

                    // Add Step Numbering
                    if (!state.logStepCount) state.logStepCount = 1;

                    // Only number significant steps (skip simple status updates if needed, currently numbering all)
                    logItem.textContent = `Step ${state.logStepCount}: ${event.content}`;
                    state.logStepCount++;

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
                    let rawData = event;
                    let backendContent = null;

                    // 1. 優先從事件物件中提取內容 (SSE 結構)
                    if (typeof rawData === 'object' && rawData !== null) {
                        backendContent = rawData.content || rawData.response || rawData.summary || rawData.message;
                    }

                    // 2. 如果沒抓到或是字串，嘗試解析它 (可能是 JSON 字串)
                    if (!backendContent && typeof rawData === 'string' && (rawData.trim().startsWith('{') || rawData.trim().startsWith('['))) {
                        try {
                            const parsed = JSON.parse(rawData);
                            backendContent = parsed.response || parsed.summary || parsed.content || parsed.message;
                        } catch (e) {
                            console.error("[Analysis] Failed to parse backend rawData JSON:", e);
                        }
                    }

                    // 3. 備援：如果累積的 fullText 本身就是 JSON (AI 誤輸出的情況)
                    let finalContent = backendContent || state.fullText;
                    if (typeof finalContent === 'string' && (finalContent.trim().startsWith('{') || finalContent.trim().startsWith('['))) {
                        try {
                            const parsed = JSON.parse(finalContent);
                            if (parsed.response || parsed.content || parsed.summary) {
                                finalContent = parsed.response || parsed.content || parsed.summary;
                                console.log("[Analysis] Extracted content from accidentally JSON-wrapped fullText");
                            }
                        } catch (e) { /* Not a valid JSON, keep as is */ }
                    }

                    // 徹底清除物件雜訊
                    if (typeof finalContent === 'string' && finalContent.includes('[object Object]')) {
                        finalContent = finalContent.replace(/\[object Object\]/g, '');
                        if (backendContent) finalContent = backendContent;
                    }

                    // 最終 Markdown 渲染 (包含圖表)
                    state.markdownBody.innerHTML = marked.parse(finalContent || '');
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

                    // --- Render Structured Report Cards (if available) ---
                    const sr = (event.tool_result && event.tool_result.structured_report) || null;
                    if (sr && sr.findings && sr.findings.length > 0) {
                        const reportDiv = document.createElement('div');
                        reportDiv.style.cssText = 'margin-top: 24px; border-top: 2px solid rgba(99,102,241,0.2); padding-top: 20px;';

                        // Section Title
                        const titleEl = document.createElement('div');
                        titleEl.style.cssText = 'font-size: 13px; font-weight: 700; color: #6366f1; text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 12px;';
                        titleEl.textContent = 'Structured Findings';
                        reportDiv.appendChild(titleEl);

                        // Executive Summary Banner
                        if (sr.executive_summary) {
                            const summaryBanner = document.createElement('div');
                            summaryBanner.style.cssText = 'padding: 12px 16px; background: linear-gradient(135deg, #eef2ff 0%, #e0e7ff 100%); border: 1px solid #c7d2fe; border-radius: 10px; font-size: 13px; color: #3730a3; font-weight: 500; margin-bottom: 14px; line-height: 1.6;';
                            summaryBanner.textContent = sr.executive_summary;
                            reportDiv.appendChild(summaryBanner);
                        }

                        // Severity style maps
                        const sevStyles = {
                            'CRITICAL': { bg: 'linear-gradient(135deg, #fef2f2 0%, #fee2e2 100%)', border: '#fca5a5', badge: '#dc2626', badgeBg: '#fee2e2', text: '#991b1b' },
                            'HIGH': { bg: 'linear-gradient(135deg, #fff7ed 0%, #ffedd5 100%)', border: '#fdba74', badge: '#ea580c', badgeBg: '#ffedd5', text: '#9a3412' },
                            'MEDIUM': { bg: 'linear-gradient(135deg, #fffbeb 0%, #fef3c7 100%)', border: '#fcd34d', badge: '#d97706', badgeBg: '#fef3c7', text: '#92400e' },
                            'LOW': { bg: 'linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%)', border: '#86efac', badge: '#16a34a', badgeBg: '#dcfce7', text: '#166534' },
                        };

                        // Findings Cards
                        sr.findings.forEach(finding => {
                            const card = document.createElement('div');
                            const sev = (finding.severity || 'LOW').toUpperCase();
                            const s = sevStyles[sev] || sevStyles['LOW'];
                            card.style.cssText = `padding: 12px 16px; background: ${s.bg}; border: 1px solid ${s.border}; border-left: 4px solid ${s.badge}; border-radius: 8px; margin-bottom: 8px; transition: transform 0.15s ease;`;
                            card.onmouseenter = () => card.style.transform = 'translateX(4px)';
                            card.onmouseleave = () => card.style.transform = 'translateX(0)';

                            // Badge + Title row
                            const header = document.createElement('div');
                            header.style.cssText = 'display: flex; align-items: center; gap: 8px; margin-bottom: 4px;';

                            const badge = document.createElement('span');
                            badge.style.cssText = `font-size: 10px; font-weight: 800; padding: 2px 8px; border-radius: 4px; background: ${s.badgeBg}; color: ${s.badge}; letter-spacing: 0.5px;`;
                            badge.textContent = sev;

                            const title = document.createElement('span');
                            title.style.cssText = `font-size: 13px; font-weight: 600; color: ${s.text};`;
                            title.textContent = finding.title || '';

                            header.appendChild(badge);
                            header.appendChild(title);
                            card.appendChild(header);

                            if (finding.detail) {
                                const detail = document.createElement('div');
                                detail.style.cssText = 'font-size: 12px; color: #64748b; margin-top: 4px; line-height: 1.5;';
                                detail.textContent = finding.detail;
                                card.appendChild(detail);
                            }

                            reportDiv.appendChild(card);
                        });

                        // Action Items
                        if (sr.action_items && sr.action_items.length > 0) {
                            const actionsDiv = document.createElement('div');
                            actionsDiv.style.cssText = 'margin-top: 14px; padding: 12px 16px; background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%); border: 1px solid #e2e8f0; border-radius: 10px;';

                            const actTitle = document.createElement('div');
                            actTitle.style.cssText = 'font-size: 11px; font-weight: 700; color: #94a3b8; text-transform: uppercase; letter-spacing: 1.2px; margin-bottom: 10px;';
                            actTitle.textContent = 'Action Items';
                            actionsDiv.appendChild(actTitle);

                            const prioColors = { 'HIGH': '#ef4444', 'MEDIUM': '#f59e0b', 'LOW': '#22c55e' };
                            sr.action_items.forEach(item => {
                                const li = document.createElement('div');
                                li.style.cssText = 'font-size: 13px; color: #475569; display: flex; align-items: flex-start; gap: 8px; margin-bottom: 6px; line-height: 1.5;';
                                const prio = (item.priority || 'MEDIUM').toUpperCase();
                                const dot = document.createElement('span');
                                dot.style.cssText = `width: 8px; height: 8px; border-radius: 50%; background: ${prioColors[prio] || '#94a3b8'}; margin-top: 5px; flex-shrink: 0;`;
                                const text = document.createElement('span');
                                text.textContent = item.action || item;
                                li.appendChild(dot);
                                li.appendChild(text);
                                actionsDiv.appendChild(li);
                            });

                            reportDiv.appendChild(actionsDiv);
                        }

                        state.markdownBody.appendChild(reportDiv);
                    }
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
                                    beginAtZero: false,
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


    // --- Param Selection Modal Logic ---
    openParamSelectionModal(btn) {
        if (!this.currentFileParams || this.currentFileParams.length === 0) {
            alert('無法獲取參數列表，請確認檔案已正確加載。');
            return;
        }
        const menu = document.getElementById('param-select-menu');
        if (menu) {
            menu.classList.remove('hidden');

            // ✨ Position Beside Button
            if (btn) {
                const rect = btn.getBoundingClientRect();
                const menuWidth = 280;

                // Position to the right of button
                let top = rect.top + window.scrollY;
                let left = rect.right + 12;

                // Adjust if overflowing vertically
                const windowHeight = window.innerHeight;
                const menuHeight = 450; // Max height
                if (top + menuHeight > windowHeight + window.scrollY) {
                    top = Math.max(10, windowHeight + window.scrollY - menuHeight - 10);
                }

                menu.style.top = `${top}px`;
                menu.style.left = `${left}px`;
                menu.style.position = 'absolute';
            }

            this.populateParamDropdown();
            // Reset keyword input & Focus
            const kwInput = document.getElementById('trend-keyword-input');
            if (kwInput) {
                kwInput.value = '';
                setTimeout(() => kwInput.focus(), 100);
            }
        }
    }

    closeParamSelectionModal() {
        const menu = document.getElementById('param-select-menu');
        if (menu) menu.classList.add('hidden');
    }

    populateParamDropdown(filter = '') {
        const select = document.getElementById('trend-column-select');
        if (!select) return;

        const lowerFilter = (filter || '').toLowerCase();

        // Keep the placeholder
        select.innerHTML = '<option value="" disabled selected>-- 請選擇參數 --</option>';

        if (!this.currentFileParams || this.currentFileParams.length === 0) return;

        // Use categories if available for better grouping
        if (this.currentFileCategories && Object.keys(this.currentFileCategories).length > 0) {
            Object.entries(this.currentFileCategories).forEach(([catName, params]) => {
                const filteredParams = params.filter(p => p.toLowerCase().includes(lowerFilter));
                if (filteredParams.length > 0) {
                    const group = document.createElement('optgroup');
                    group.label = catName;
                    filteredParams.forEach(param => {
                        const opt = document.createElement('option');
                        opt.value = param;
                        opt.text = param;
                        group.appendChild(opt);
                    });
                    select.appendChild(group);
                }
            });
        } else {
            // Fallback to flat list
            this.currentFileParams.forEach(param => {
                if (param.toLowerCase().includes(lowerFilter)) {
                    const opt = document.createElement('option');
                    opt.value = param;
                    opt.text = param;
                    select.appendChild(opt);
                }
            });
        }

        // If filtering and we have results, auto-select the first one for better UX
        if (filter && select.options.length > 1) {
            select.selectedIndex = 1;
        } else {
            // Otherwise keep placeholder selected
            select.value = "";
        }
    }

    confirmParamSelection() {
        const select = document.getElementById('trend-column-select');
        const kwInput = document.getElementById('trend-keyword-input');

        const col = select ? select.value : '';
        const keyword = kwInput ? kwInput.value.trim() : '';

        if (!col) {
            alert('請選擇一個參數欄位！');
            return;
        }

        let query = `請幫我繪製 ${col} 的趨勢圖`;
        if (keyword) {
            query += `，並篩選包含關鍵字 "${keyword}" 的數據`;
        }

        this.elements.userInput.value = query;
        this.elements.userInput.style.height = 'auto';
        this.elements.userInput.style.height = this.elements.userInput.scrollHeight + 'px';
        this.elements.btnSend.disabled = false;

        this.closeParamSelectionModal();
        this.sendMessage();
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
    // --- Data Mining Modal Methods ---
    openDataMiningModal() {
        if (!this.currentFileParams || this.currentFileParams.length === 0) {
            alert('無法獲取參數列表，請確認檔案已正確加載。');
            return;
        }

        try {
            const modal = document.getElementById('data-mining-modal');
            if (!modal) {
                console.error('Data Mining Modal element not found');
                alert('系統錯誤：找不到視窗元件，請嘗試重新整理頁面。');
                return;
            }

            modal.classList.remove('hidden');

            // Initialize State
            this.miningState = {
                y: new Set(),
                x: new Set(),
                selectedSource: new Set(),
                selectedY: new Set(),
                selectedX: new Set()
            };

            // Bind Middle Buttons
            const btnToY = document.getElementById('btn-to-y');
            const btnToX = document.getElementById('btn-to-x');
            const btnReturn = document.getElementById('btn-return');

            if (btnToY) btnToY.onclick = () => this.moveSelectedSourceTo('y');
            if (btnToX) btnToX.onclick = () => this.moveSelectedSourceTo('x');
            if (btnReturn) btnReturn.onclick = () => this.moveAnySelectedBack();

            // Populate lists
            this.renderMiningLists();

            // Reset Inputs (Safe check)
            const ids = ['dm-range-start', 'dm-range-end', 'dm-source-search'];
            ids.forEach(id => {
                const el = document.getElementById(id);
                if (el) el.value = '';
            });

            // Bind search event
            const searchInput = document.getElementById('dm-source-search');
            if (searchInput) {
                searchInput.oninput = (e) => this.filterMiningSource(e.target.value);
            }

            // Bind select all remaining to X
            const selectAllBtn = document.getElementById('dm-x-select-all');
            if (selectAllBtn) {
                selectAllBtn.onclick = () => this.moveAllSourceToX();
            }

        } catch (err) {
            console.error('Error opening mining modal:', err);
            alert('開啟視窗時發生錯誤：' + err.message);
        }
    }

    renderMiningLists() {
        const sourceList = document.getElementById('dm-source-list');
        const yList = document.getElementById('dm-y-list');

        if (!sourceList || !yList) return;

        // Clear current content
        const searchInput = document.getElementById('dm-source-search');

        sourceList.innerHTML = '';
        yList.innerHTML = '';

        if (this.miningState.y.size === 0) {
            yList.innerHTML = '<div id="dm-y-placeholder" class="absolute inset-0 flex items-center justify-center text-gray-400 text-sm pointer-events-none select-none">無選取</div>';
        }

        // 1. Render Source List
        this.currentFileParams.forEach(p => {
            if (this.miningState.y.has(p)) return;

            const isSelected = this.miningState.selectedSource.has(p);
            const div = document.createElement('div');
            div.className = `flex items-center gap-2 py-2 px-3 border border-transparent rounded-lg cursor-pointer transition-all select-none ${isSelected ? 'bg-blue-100 border-blue-300 text-blue-900' : 'hover:bg-gray-100 text-gray-700'}`;
            div.onclick = (e) => this.toggleSelection(p, 'source', e);
            div.innerHTML = `<span class="truncate text-sm flex-1 pointer-events-none select-none" title="${p}">${p}</span>`;
            sourceList.appendChild(div);
        });

        // 2. Render Y List
        this.miningState.y.forEach(p => {
            const isSelected = this.miningState.selectedY.has(p);
            const div = document.createElement('div');
            div.className = `flex items-center gap-2 py-2 px-3 border border-transparent rounded-lg cursor-pointer transition-all select-none ${isSelected ? 'bg-blue-200 border-blue-400 text-blue-900' : 'hover:bg-blue-100 text-gray-700'}`;
            div.onclick = (e) => this.toggleSelection(p, 'y', e);
            div.innerHTML = `<span class="truncate text-sm flex-1 pointer-events-none select-none" title="${p}">${p}</span>`;
            yList.appendChild(div);
        });

        this.updateMiningCounts();

        // Re-apply filter if keyword exists
        if (searchInput && searchInput.value) {
            this.filterMiningSource(searchInput.value);
        }
    }

    moveMiningItem(item, from, to) {
        if (!this.miningState) return;

        // Update State
        if (to === 'y') {
            this.miningState.y.add(item);
        } else if (to === 'source') {
            this.miningState.y.delete(item);
        }

        // Re-render
        this.renderMiningLists();
    }

    moveAllSourceToX() {
        if (!this.miningState) return;
        this.currentFileParams.forEach(p => {
            if (!this.miningState.y.has(p)) {
                this.miningState.x.add(p);
            }
        });
        this.renderMiningLists();
    }

    updateMiningCounts() {
        if (!this.miningState) return;
        const sourceCount = this.currentFileParams.length - this.miningState.y.size;

        const sCountEl = document.getElementById('dm-source-count');
        const yCountEl = document.getElementById('dm-y-count');

        if (sCountEl) sCountEl.innerText = sourceCount;
        if (yCountEl) yCountEl.innerText = this.miningState.y.size;

        this.updateButtonStates();
    }

    updateButtonStates() {
        const btnToY = document.getElementById('btn-to-y');
        const btnReturn = document.getElementById('btn-return');

        const hasSource = this.miningState.selectedSource && this.miningState.selectedSource.size > 0;
        const hasDest = this.miningState.selectedY && this.miningState.selectedY.size > 0;

        if (btnToY) btnToY.disabled = !hasSource;
        if (btnReturn) btnReturn.disabled = !hasDest;

        [btnToY, btnReturn].forEach(btn => {
            if (btn) {
                if (btn.disabled) btn.classList.add('opacity-50', 'cursor-not-allowed');
                else btn.classList.remove('opacity-50', 'cursor-not-allowed');
            }
        });
    }

    toggleSelection(item, type, event) {
        if (!this.miningState) return;

        let targetSet, lastProp;
        if (type === 'source') {
            targetSet = this.miningState.selectedSource;
            lastProp = 'lastSource';
        } else if (type === 'y') {
            targetSet = this.miningState.selectedY;
            lastProp = 'lastY';
        } else return;

        // Shift Click (Range)
        if (event && event.shiftKey && this.miningState[lastProp]) {
            let list;
            if (type === 'source') {
                list = this.currentFileParams.filter(p => !this.miningState.y.has(p));
            } else {
                list = Array.from(this.miningState.y);
            }
            const startIdx = list.indexOf(this.miningState[lastProp]);
            const endIdx = list.indexOf(item);

            if (startIdx !== -1 && endIdx !== -1) {
                const low = Math.min(startIdx, endIdx);
                const high = Math.max(startIdx, endIdx);
                if (!(event.ctrlKey || event.metaKey)) targetSet.clear();
                for (let i = low; i <= high; i++) targetSet.add(list[i]);
            }
        }
        // Ctrl Click (Toggle)
        else if (event && (event.ctrlKey || event.metaKey)) {
            if (targetSet.has(item)) targetSet.delete(item);
            else targetSet.add(item);
            this.miningState[lastProp] = item;
        }
        // Single Click
        else {
            targetSet.clear();
            targetSet.add(item);
            this.miningState[lastProp] = item;
        }
        this.renderMiningLists();
    }

    moveSelectedSourceTo(target) {
        if (!this.miningState) return;
        const items = this.miningState.selectedSource;
        if (items.size === 0) return;
        items.forEach(item => this.miningState.y.add(item));
        this.miningState.selectedSource.clear();
        this.renderMiningLists();
    }

    moveAnySelectedBack() {
        if (!this.miningState) return;
        if (this.miningState.selectedY) {
            this.miningState.selectedY.forEach(item => this.miningState.y.delete(item));
            this.miningState.selectedY.clear();
        }
        this.renderMiningLists();
    }

    filterMiningSource(keyword) {
        const list = document.getElementById('dm-source-list');
        if (!list) return;
        const items = list.querySelectorAll('.dm-source-item');
        const lowerKw = keyword.toLowerCase();
        items.forEach(item => {
            const textSpan = item.querySelector('span.truncate');
            if (textSpan) {
                const text = textSpan.innerText.toLowerCase();
                if (text.includes(lowerKw)) {
                    item.style.display = 'flex';
                } else {
                    item.style.display = 'none';
                }
            }
        });
    }

    confirmDataMining() {
        console.log('[DEBUG] confirmDataMining called');
        const targets = Array.from(this.miningState.y);
        console.log('[DEBUG] targets:', targets);

        const start = document.getElementById('dm-range-start').value.trim();
        const end = document.getElementById('dm-range-end').value.trim();

        let query = '';
        let targetRange = null;

        // Build target range
        if (start && end) {
            targetRange = `${start}-${end}`;
        } else if (start) {
            targetRange = `${start}-`;
        } else if (end) {
            targetRange = `-${end}`;
        }

        // Build query based on selections
        if (targets.length === 0) {
            // No specific targets - analyze all fields
            query = `請對所有欄位進行深度資料探勘與異常分析`;
        } else {
            // Specific targets selected
            query = `請對目標欄位 ${targets.join(', ')} 進行深度資料探勘與異常分析`;
        }

        // Add range if specified
        if (targetRange) {
            query += `，分析區間為第 ${targetRange} 筆`;
        } else {
            query += `，分析全域數據`;
        }

        // Add instruction for AI
        query += `。請自動關聯其他所有可能的影響因子，找出與目標變數相關性最高的特徵。`;

        // Store structured metadata for sendMessage
        this.miningMetadata = {
            suspect_params: targets.length > 0 ? targets : null,
            target_range: targetRange
        };

        this.elements.userInput.value = query;
        this.elements.userInput.style.height = 'auto';
        this.elements.userInput.style.height = this.elements.userInput.scrollHeight + 'px';
        this.elements.btnSend.disabled = false;
        this.sendMessage();

        document.getElementById('data-mining-modal').classList.add('hidden');
    }

    // ========== Session Management ==========

    async loadSessionList() {
        try {
            const response = await fetch(`/api/analysis/sessions?user_id=${encodeURIComponent(this.accountId)}`);
            if (!response.ok) throw new Error('Failed to load sessions');
            const data = await response.json();
            this.renderSessionList(data.sessions || []);
        } catch (err) {
            console.error('[Sessions] Load error:', err);
            if (this.elements.sessionList) {
                this.elements.sessionList.innerHTML =
                    '<div class="text-xs text-gray-400 text-center py-4">無法載入聊天室列表</div>';
            }
        }
    }

    renderSessionList(sessions) {
        const container = this.elements.sessionList;
        if (!container) return;

        if (!sessions || sessions.length === 0) {
            container.innerHTML =
                '<div class="text-xs text-gray-300 text-center py-4">暫無聊天室</div>';
            return;
        }

        container.innerHTML = sessions.map(s => {
            const isActive = s.session_id === this.sessionId;
            const title = this._escapeHtml(s.title || '新對話');
            const count = s.message_count || 0;
            const timeStr = s.last_active
                ? new Date(s.last_active).toLocaleString('zh-TW', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
                : '';

            return `
                <div class="session-item group flex items-center gap-2 p-2 rounded-lg cursor-pointer transition-all
                    ${isActive ? 'bg-blue-50 border border-blue-200' : 'bg-white border border-transparent hover:bg-gray-100 hover:border-gray-200'}"
                    data-session-id="${s.session_id}">
                    <div class="flex-1 min-w-0" onclick="window.ia.switchSession('${s.session_id}')">
                        <div class="text-xs font-medium truncate ${isActive ? 'text-blue-700' : 'text-gray-700'}">
                            ${title}
                        </div>
                        <div class="text-[10px] text-gray-400 mt-0.5">
                            ${count} 條訊息 ${timeStr ? '· ' + timeStr : ''}
                        </div>
                    </div>
                    ${!isActive ? `
                    <button onclick="event.stopPropagation(); window.ia.deleteSession('${s.session_id}')"
                        class="hidden group-hover:flex w-5 h-5 items-center justify-center text-gray-300 hover:text-red-500 rounded transition-colors flex-shrink-0"
                        title="刪除">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                        </svg>
                    </button>` : ''}
                </div>
            `;
        }).join('');
    }

    async createNewSession() {
        // 新聊天室 ID 以帳號名為前綴，確保帳號隔離
        const uuid = window.crypto.randomUUID();
        const newId = `${this.accountId}_${uuid}`;
        try {
            await fetch('/api/analysis/sessions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: newId }),
            });
        } catch (err) {
            console.warn('[Sessions] Create API failed, continuing anyway:', err);
        }

        // Switch to new session
        this.sessionId = newId;
        this.currentFileId = null;
        this.currentFilename = null;

        // Reset UI
        this.elements.chatContainer.innerHTML = '';
        if (this.elements.welcomeScreen) {
            this.elements.welcomeScreen.style.display = '';
        }
        this.elements.fileSelect.value = '';
        if (this.elements.fileInfoPanel) {
            this.elements.fileInfoPanel.classList.add('hidden');
        }

        // Reload file list for new session and refresh session list
        this.loadSessionList();
        console.log(`[Sessions] Created new session: ${newId}`);
    }

    async switchSession(sessionId) {
        if (sessionId === this.sessionId) return;

        // Guard: 分析進行中時警告用戶
        if (this.isLoading) {
            const confirmed = confirm('分析正在進行中，切換聊天室可能導致當前分析結果遺失。\n\n確定要切換嗎？');
            if (!confirmed) return;
            // 中斷當前分析
            this.stopGeneration();
        }

        this.sessionId = sessionId;
        this.currentFileId = null;
        this.currentFilename = null;

        // Reset UI
        this.elements.chatContainer.innerHTML = '';
        if (this.elements.welcomeScreen) {
            this.elements.welcomeScreen.style.display = 'none';
        }
        this.elements.fileSelect.value = '';
        if (this.elements.fileInfoPanel) {
            this.elements.fileInfoPanel.classList.add('hidden');
        }

        // Load chat history for this session
        await this._loadSessionHistory(sessionId);

        // Refresh sidebar (highlight active session)
        this.loadSessionList();
        // Reload file list for this session
        this.loadFileList();
        console.log(`[Sessions] Switched to session: ${sessionId}`);
    }

    async _loadSessionHistory(sessionId) {
        try {
            const response = await fetch(`/api/analysis/sessions/${encodeURIComponent(sessionId)}/history?last_n=50`);
            if (!response.ok) return;
            const data = await response.json();
            const messages = data.messages || [];

            if (messages.length === 0) {
                // No history, show welcome screen
                if (this.elements.welcomeScreen) {
                    this.elements.welcomeScreen.style.display = '';
                }
                return;
            }

            // Render each historical message
            for (const msg of messages) {
                if (msg.role === 'system') continue; // Skip system messages
                const isUser = msg.role === 'user';
                const row = document.createElement('div');
                row.className = `flex ${isUser ? 'justify-end' : 'justify-start'} mb-3`;
                row.innerHTML = `
                    <div class="${isUser
                        ? 'bg-blue-500 text-white rounded-2xl rounded-br-md px-4 py-2.5 max-w-[75%]'
                        : 'bg-white border border-gray-100 rounded-2xl rounded-bl-md px-4 py-2.5 max-w-[85%] shadow-sm'}">
                        <div class="text-sm whitespace-pre-wrap leading-relaxed">${isUser ? this._escapeHtml(msg.content) : this._renderMarkdown(msg.content || '')
                    }</div>
                    </div>
                `;
                this.elements.chatContainer.appendChild(row);
            }
            this.scrollToBottom();
        } catch (err) {
            console.warn('[Sessions] Failed to load history:', err);
        }
    }

    async deleteSession(sessionId) {
        if (!confirm('確定要刪除此聊天室嗎？')) return;
        try {
            await fetch(`/api/analysis/sessions/${sessionId}`, { method: 'DELETE' });
        } catch (err) {
            console.warn('[Sessions] Delete failed:', err);
        }
        this.loadSessionList();
    }

    _escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    // ========== Session Management ==========

    async loadSessionList() {
        if (!this.elements.sessionList) {
            console.warn('[Sessions] sessionList element is null');
            return;
        }
        try {
            this.elements.sessionList.innerHTML = '<div class="text-xs text-gray-400 text-center py-3">載入中...</div>';
            const response = await fetch('/api/analysis/sessions');
            if (!response.ok) throw new Error('Failed to load sessions, status: ' + response.status);
            const data = await response.json();
            console.log('[Sessions] Loaded', (data.sessions || []).length, 'sessions');
            this.renderSessionList(data.sessions || []);
        } catch (err) {
            console.error('[Sessions] Load error:', err);
            if (this.elements.sessionList) {
                this.elements.sessionList.innerHTML = '<div class="text-xs text-red-400 text-center py-3">無法載入聊天室</div>';
            }
        }
    }

    async createNewSession() {
        try {
            const response = await fetch('/api/analysis/sessions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title: '新對話' })
            });
            if (!response.ok) throw new Error('Failed to create session');
            const data = await response.json();
            this.sessionId = data.session_id;
            // Clear chat and reload session list
            if (this.elements.chatContainer) {
                this.elements.chatContainer.innerHTML = '';
            }
            this.conversationId = null;
            await this.loadSessionList();
        } catch (err) {
            console.error('[Sessions] Create error:', err);
        }
    }

    async switchSession(sessionId) {
        console.log('[Sessions] switchSession called:', sessionId, 'current:', this.sessionId);
        if (sessionId === this.sessionId) {
            console.log('[Sessions] Same session, skipping');
            return;
        }
        this.sessionId = sessionId;
        // Clear current chat
        if (this.elements.chatContainer) {
            this.elements.chatContainer.innerHTML = '';
        }
        this.conversationId = null;

        // Load chat history for this session
        try {
            const response = await fetch(`/api/analysis/sessions/${sessionId}/history`);
            if (response.ok) {
                const data = await response.json();
                const messages = data.messages || [];
                for (const msg of messages) {
                    this.addMessage(msg.role, msg.content);
                }
            }
        } catch (err) {
            console.error('[Sessions] History load error:', err);
        }

        // Update active state in UI
        this.renderActiveSession(sessionId);
    }

    renderActiveSession(activeId) {
        if (!this.elements.sessionList) return;
        const items = this.elements.sessionList.querySelectorAll('[data-session-id]');
        items.forEach(item => {
            if (item.dataset.sessionId === activeId) {
                item.classList.add('bg-blue-50', 'border-blue-200');
                item.classList.remove('border-transparent', 'hover:bg-gray-50');
            } else {
                item.classList.remove('bg-blue-50', 'border-blue-200');
                item.classList.add('border-transparent', 'hover:bg-gray-50');
            }
        });
    }

    renderSessionList(sessions) {
        if (!this.elements.sessionList) return;

        if (!sessions || sessions.length === 0) {
            this.elements.sessionList.innerHTML = '<div class="text-xs text-gray-400 text-center py-3">暫無聊天室</div>';
            return;
        }

        console.log('[Sessions] renderSessionList:', sessions.length, 'sessions');
        this.elements.sessionList.innerHTML = sessions.map(s => {
            const isActive = s.session_id === this.sessionId;
            const title = s.title || s.session_id;
            const msgCount = s.message_count || 0;
            const lastActive = s.last_active ? new Date(s.last_active).toLocaleString('zh-TW', {
                month: 'numeric', day: 'numeric',
                hour: '2-digit', minute: '2-digit'
            }) : '';
            const activeCls = isActive
                ? 'bg-blue-50 border-blue-200'
                : 'border-transparent hover:bg-gray-50';

            return `
                <div class="session-item p-2 rounded-lg border cursor-pointer transition-colors ${activeCls}"
                     data-session-id="${s.session_id}"
                     onclick="window.ia && window.ia.switchSession('${s.session_id}')">
                    <div class="flex items-center justify-between">
                        <div class="flex-1 min-w-0">
                            <div class="text-sm font-medium text-gray-700 truncate">${this._escapeHtml(title)}</div>
                            <div class="text-xs text-gray-400 mt-0.5">
                                ${msgCount} 條訊息${lastActive ? ' · ' + lastActive : ''}
                            </div>
                        </div>
                        <button class="session-delete-btn ml-1 p-1 text-gray-300 hover:text-red-500 transition-colors"
                                data-delete-session="${s.session_id}" title="刪除"
                                onclick="event.stopPropagation(); window.ia && window.ia.deleteSession('${s.session_id}')">
                            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                            </svg>
                        </button>
                    </div>
                </div>
            `;
        }).join('');

        // Event delegation 已移到 init() 中，避免重複綁定
    }

    async deleteSession(sessionId) {
        try {
            const response = await fetch(`/api/analysis/sessions/${sessionId}`, {
                method: 'DELETE'
            });
            if (!response.ok) throw new Error('Delete failed');
            // If deleted the current session, switch to new
            if (sessionId === this.sessionId) {
                this.sessionId = 'default';
                if (this.elements.chatContainer) {
                    this.elements.chatContainer.innerHTML = '';
                }
            }
            await this.loadSessionList();
        } catch (err) {
            console.error('[Sessions] Delete error:', err);
        }
    }
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    window.ia = new IntelligentAnalysis();
});

// Global accessor for HTML onclick
// Global accessor for HTML onclick
window.setAnalysisMode = (mode) => {
    if (window.ia) window.ia.setMode(mode);
};

window.openParamSelectionModal = () => window.ia?.openParamSelectionModal();
window.closeParamSelectionModal = () => window.ia?.closeParamSelectionModal();
window.confirmParamSelection = () => window.ia?.confirmParamSelection();
window.updateParamCount = () => {
    const checkboxes = document.querySelectorAll('input[name="trend-param"]:checked');
    const countSpan = document.getElementById('trend-param-count');
    if (countSpan) countSpan.innerText = checkboxes.length;
};

// Data Mining Modal Global Accessors
window.openDataMiningModal = () => window.ia?.openDataMiningModal();
window.closeDataMiningModal = () => {
    const modal = document.getElementById('data-mining-modal');
    if (modal) modal.classList.add('hidden');
};
window.confirmParamSelection = () => window.ia?.confirmParamSelection();
window.updateParamCount = () => {
    const checkboxes = document.querySelectorAll('input[name="trend-param"]:checked');
    const countEl = document.getElementById('param-selected-count');
    if (countEl) countEl.textContent = checkboxes.length;
};
