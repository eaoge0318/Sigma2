// === 全域 Lightbox (ESC 關閉 / 左右箭頭切換同組圖片) ===
window._openLightbox = function (srcs, startIdx = 0) {
    let current = startIdx;
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.8);display:flex;align-items:center;justify-content:center;z-index:9999;cursor:zoom-out;';

    const bigImg = document.createElement('img');
    bigImg.src = srcs[current];
    bigImg.style.cssText = 'max-width:90vw;max-height:85vh;border-radius:8px;box-shadow:0 8px 32px rgba(0,0,0,0.5);transition:opacity 0.15s ease;';
    bigImg.onclick = (e) => e.stopPropagation();
    bigImg.style.cursor = 'default';

    // 計數器
    const counter = document.createElement('div');
    counter.style.cssText = 'position:absolute;bottom:20px;left:50%;transform:translateX(-50%);color:rgba(255,255,255,0.7);font-size:13px;font-family:sans-serif;pointer-events:none;';
    const updateCounter = () => { counter.textContent = srcs.length > 1 ? `${current + 1} / ${srcs.length}` : ''; };
    updateCounter();

    // 左右箭頭按鈕
    if (srcs.length > 1) {
        const makeBtn = (text, dir) => {
            const btn = document.createElement('div');
            btn.textContent = text;
            btn.style.cssText = `position:absolute;top:50%;${dir}:16px;transform:translateY(-50%);color:rgba(255,255,255,0.7);font-size:36px;cursor:pointer;user-select:none;padding:8px 12px;border-radius:50%;transition:all 0.15s;`;
            btn.onmouseenter = () => { btn.style.color = '#fff'; btn.style.background = 'rgba(255,255,255,0.15)'; };
            btn.onmouseleave = () => { btn.style.color = 'rgba(255,255,255,0.7)'; btn.style.background = 'none'; };
            btn.onclick = (e) => { e.stopPropagation(); navigate(text === '‹' ? -1 : 1); };
            return btn;
        };
        overlay.appendChild(makeBtn('‹', 'left'));
        overlay.appendChild(makeBtn('›', 'right'));
    }

    const navigate = (delta) => {
        current = (current + delta + srcs.length) % srcs.length;
        bigImg.style.opacity = '0.3';
        setTimeout(() => { bigImg.src = srcs[current]; bigImg.style.opacity = '1'; updateCounter(); }, 80);
    };

    const onKey = (e) => {
        if (e.key === 'Escape') { cleanup(); }
        else if (e.key === 'ArrowLeft') { navigate(-1); }
        else if (e.key === 'ArrowRight') { navigate(1); }
    };
    const cleanup = () => { document.removeEventListener('keydown', onKey); overlay.remove(); };

    overlay.onclick = cleanup;
    overlay.appendChild(bigImg);
    overlay.appendChild(counter);
    document.addEventListener('keydown', onKey);
    document.body.appendChild(overlay);
};

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
        this.pendingAttachments = []; // [{name, type, dataUrl}]

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
            mappingFileName: document.getElementById('mapping-file-name'),

            // Sidebar - Data Description
            dataDescriptionInput: document.getElementById('data-description-input'),
            dataDescStatus: document.getElementById('data-desc-status'),
            dataDescCount: document.getElementById('data-desc-count')
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
        // 載入聊天室列表
        await this.loadSessionList();
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

        // File Selection Change -> 每次選檔都開啟新對話 (新資料夾)
        this.elements.fileSelect.addEventListener('change', async (e) => {
            const fileId = e.target.value;
            if (fileId) {
                const selectedOption = e.target.options[e.target.selectedIndex];
                const filename = selectedOption.text;

                // 每次選檔都生成新的 conversationId → 建立新的 analysis 資料夾
                this.conversationId = crypto.randomUUID().slice(0, 12);
                console.log(`[Sessions] File selected: ${filename}, new conversation: ${this.conversationId}`);

                // 清空聊天區
                this.currentFileId = null;
                this.currentFilename = null;
                this.elements.chatContainer.innerHTML = '';
                if (this.elements.welcomeScreen) {
                    this.elements.welcomeScreen.style.display = '';
                    this.elements.welcomeScreen.classList.remove('hidden');
                }

                this.handleFileSelect(fileId, filename);
            }
        });

        // Attachment Button
        this.elements.btnAttach.addEventListener('click', () => {
            this.elements.fileAttachment.click();
        });

        // File attachment change handler
        this.elements.fileAttachment.addEventListener('change', (e) => {
            Array.from(e.target.files).forEach(f => this._addAttachment(f));
            e.target.value = ''; // reset so same file can be re-selected
        });

        // Paste screenshot from clipboard
        this.elements.userInput.addEventListener('paste', (e) => {
            const items = e.clipboardData?.items;
            if (!items) return;
            for (const item of items) {
                if (item.type.startsWith('image/')) {
                    e.preventDefault();
                    const blob = item.getAsFile();
                    if (blob) this._addAttachment(blob);
                    break;
                }
            }
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

        // 聊天室列表在 init() 中載入, 不自動切換 (用戶手動點擊)

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
                    console.log('[Sessions] Switching to:', item.dataset.sessionId, 'file:', item.dataset.fileId, 'conv:', item.dataset.conversationId);
                    this.switchSession(
                        item.dataset.sessionId,
                        item.dataset.fileId || '',
                        item.dataset.filename || '',
                        item.dataset.conversationId || 'default'
                    );
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

                // Intercept "統計工具" Button
                if (btn.id === 'btn-open-stat-tool' || query === '統計工具') {
                    e.preventDefault();
                    e.stopPropagation();
                    this.openStatToolModal();
                    return;
                }

                // Intercept "Draw Trend Chart"
                if (query === '趨勢圖' || query === '繪製趨勢圖') {
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

                const statModal = document.getElementById('stat-tool-modal');
                if (statModal) statModal.classList.add('hidden');

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
            } else if (e.target.closest('#btn-confirm-optim')) {
                this.confirmOptimization();
            } else if (e.target.closest('#btn-confirm-stat-tool')) {
                this.confirmStatTool();
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

        // --- Data Description: blur = save, input = counter ---
        if (this.elements.dataDescriptionInput) {
            this.elements.dataDescriptionInput.addEventListener('blur', () => {
                this.saveDataDescription();
            });
            this.elements.dataDescriptionInput.addEventListener('input', () => {
                const len = this.elements.dataDescriptionInput.value.length;
                if (this.elements.dataDescCount) {
                    this.elements.dataDescCount.textContent = `${len}/500`;
                }
            });
        }
    }

    // === File Attachment Helpers ===
    _addAttachment(file) {
        if (this.pendingAttachments.length >= 5) {
            alert('最多附加 5 個檔案');
            return;
        }
        if (file.size > 10 * 1024 * 1024) {
            alert('檔案過大（上限 10MB）');
            return;
        }
        const reader = new FileReader();
        reader.onload = () => {
            const name = file.name || `screenshot_${Date.now()}.png`;
            this.pendingAttachments.push({ name, type: file.type, dataUrl: reader.result });
            this._renderAttachmentPreview();
            // Enable send button even if no text
            this.elements.btnSend.disabled = false;
        };
        reader.readAsDataURL(file);
    }

    _renderAttachmentPreview() {
        let strip = document.getElementById('attachment-preview-strip');
        if (!strip) {
            strip = document.createElement('div');
            strip.id = 'attachment-preview-strip';
            strip.style.cssText = 'display:flex;gap:6px;flex-wrap:wrap;padding:6px 12px 0;';
            // Insert before the input flex row
            const inputArea = this.elements.userInput.closest('.p-4');
            if (inputArea) {
                const flexRow = inputArea.querySelector('.flex.items-center.gap-3');
                if (flexRow) inputArea.insertBefore(strip, flexRow);
            }
        }
        strip.innerHTML = '';
        if (this.pendingAttachments.length === 0) {
            strip.style.display = 'none';
            return;
        }
        strip.style.display = 'flex';
        this.pendingAttachments.forEach((att, i) => {
            const chip = document.createElement('div');
            chip.style.cssText = 'display:flex;align-items:center;gap:4px;padding:4px 8px;background:#f1f5f9;border:1px solid #e2e8f0;border-radius:8px;font-size:11px;color:#475569;max-width:180px;';
            if (att.type.startsWith('image/')) {
                const thumb = document.createElement('img');
                thumb.src = att.dataUrl;
                thumb.style.cssText = 'width:24px;height:24px;object-fit:cover;border-radius:4px;';
                chip.appendChild(thumb);
            } else {
                const icon = document.createElement('span');
                icon.textContent = '📄';
                chip.appendChild(icon);
            }
            const label = document.createElement('span');
            label.textContent = att.name.length > 15 ? att.name.slice(0, 12) + '...' : att.name;
            label.style.cssText = 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
            chip.appendChild(label);
            const removeBtn = document.createElement('span');
            removeBtn.textContent = '×';
            removeBtn.style.cssText = 'cursor:pointer;color:#94a3b8;font-size:14px;font-weight:bold;margin-left:2px;';
            removeBtn.onclick = () => { this.pendingAttachments.splice(i, 1); this._renderAttachmentPreview(); };
            chip.appendChild(removeBtn);
            strip.appendChild(chip);
        });
    }
    async sendMessage() {
        const message = this.elements.userInput.value.trim();
        const attachments = [...this.pendingAttachments];
        if ((!message && attachments.length === 0) || this.isLoading) return;

        this.stopRequested = false; // Reset stop state

        if (!this.currentFileId) {
            alert('請先選擇一個要分析的文件！');
            return;
        }

        // 1. Show User Message (with attachment previews)
        let displayMsg = message;
        if (attachments.length > 0) {
            const names = attachments.map(a => `📎 ${a.name}`).join('\n');
            displayMsg = (message ? message + '\n' : '') + names;
        }
        this.addMessage('user', displayMsg, null, null, false, attachments);
        this.elements.userInput.value = '';
        this.elements.userInput.style.height = 'auto';
        this.pendingAttachments = [];
        this._renderAttachmentPreview();

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
                mode: this.analysisMode,
                attachments: attachments.length > 0 ? attachments.map(a => ({ name: a.name, type: a.type, data: a.dataUrl })) : undefined
            };

            // Add mining metadata if available
            if (this.miningMetadata) {
                if (this.miningMetadata.suspect_params) {
                    requestBody.suspect_params = this.miningMetadata.suspect_params;
                }
                if (this.miningMetadata.target_range) {
                    requestBody.target_range = this.miningMetadata.target_range;
                }
                if (this.miningMetadata.baseline_range) {
                    requestBody.baseline_range = this.miningMetadata.baseline_range;
                }
                // Clear metadata after use
                this.miningMetadata = null;
            }

            // 2. Start Request
            const response = await fetch('/api/analysis/chat/stream/v3', {
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

                                // Inject event type: SSE event name takes priority
                                if (currentEventName) {
                                    eventData.type = currentEventName;
                                }

                                // Debug: chart events
                                if (eventData.type === 'chart_image' || eventData.type === 'mini_chart') {
                                    console.log(`[SSE] ${eventData.type} event received`, Object.keys(eventData));
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
            // 刷新聊天室列表
            this.loadSessionList();
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
                    session_id: this.sessionId,
                    conversation_id: this.conversationId
                })
            });

            if (!res.ok) {
                let detail = '索引建立失敗';
                try {
                    const errBody = await res.json();
                    detail = errBody.detail || detail;
                } catch (_) { /* ignore parse error */ }
                throw new Error(detail);
            }
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

            // Show Panel + Toggle Button
            this.elements.fileLoadingIndicator.classList.add('hidden');
            this.elements.fileInfoPanel.classList.remove('hidden');
            const toggleBtn = document.getElementById('file-info-toggle');
            if (toggleBtn) toggleBtn.classList.remove('hidden');

            // Load data description for this file
            this.loadDataDescription(this.currentFileId);

            // Refresh mapping status for this file
            this.checkMappingStatus();

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

            // Refresh session list so new chatroom appears in sidebar
            this.loadSessionList();

        } catch (error) {
            alert(`文件準備失敗: ${error.message}`);
            this.elements.fileLoadingIndicator.classList.add('hidden');
            this.elements.fileSelect.value = ""; // Reset selection
        }
    }

    // --- UI Helpers ---

    addMessage(role, content, allToolCalls = null, thoughts = null, animate = false, attachments = []) {
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

        // Render image attachment thumbnails for user messages
        if (role === 'user' && attachments && attachments.length > 0) {
            const bubble = div.querySelector('.message-bubble');
            const strip = document.createElement('div');
            strip.style.cssText = 'display:flex;gap:6px;flex-wrap:wrap;margin-top:8px;';
            const imgAtts = attachments.filter(a => a.type.startsWith('image/'));
            const otherAtts = attachments.filter(a => !a.type.startsWith('image/'));
            imgAtts.forEach(att => {
                const thumb = document.createElement('img');
                thumb.src = att.dataUrl;
                thumb.title = att.name;
                thumb.style.cssText = 'width:80px;height:80px;object-fit:cover;border-radius:8px;border:2px solid rgba(255,255,255,0.3);cursor:pointer;transition:transform 0.15s;';
                thumb.onmouseenter = () => { thumb.style.transform = 'scale(1.08)'; };
                thumb.onmouseleave = () => { thumb.style.transform = ''; };
                thumb.onclick = () => { window._openLightbox([att.dataUrl], 0); };
                strip.appendChild(thumb);
            });
            otherAtts.forEach(att => {
                const chip = document.createElement('span');
                chip.textContent = `📄 ${att.name}`;
                chip.style.cssText = 'font-size:11px;background:rgba(255,255,255,0.15);padding:3px 8px;border-radius:6px;';
                strip.appendChild(chip);
            });
            bubble.appendChild(strip);
        }

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
                    <summary style="display:flex; align-items:center; gap:8px;">
                        <svg class="w-3.5 h-3.5 group-open:rotate-90 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path></svg>
                        <span class="thought-label">Thought for 0s</span>
                        <span class="status-log-latest text-[11px] text-gray-400 font-mono" style="flex:1; text-align:right; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;"></span>
                        <button class="status-log-toggle text-[9px] text-gray-400 hover:text-gray-600 cursor-pointer" style="flex-shrink:0; background:none; border:none; padding:2px 4px; display:none;" title="展開/收起歷史">▼</button>
                    </summary>
                    
                    <div class="details-content mt-2 space-y-3">
                        <!-- 狀態日誌歷史 (摺疊) -->
                        <div class="status-log space-y-0.5 text-xs text-gray-500 font-mono border-l-2 border-gray-200 pl-2 bg-gray-50/30 py-1 rounded-r" style="display:none;"></div>

                        <!-- 思考區塊 -->
                        <div class="ai-thoughts p-2.5 bg-blue-50/20 border-l-2 border-blue-400 rounded-r hidden">
                            <div class="text-[10px] font-bold text-blue-500 uppercase tracking-widest mb-1 opacity-60">AI 思考流程</div>
                            <div class="thoughts-content space-y-1"></div>
                        </div>
                        
                        <!-- 工具鏈區塊 -->
                        <div class="tool-execution-chain space-y-2 hidden"></div>
                    </div>
                </details>
                
                <!-- 圖表容器 (在報告上方) -->
                <div class="chart-container"></div>
                <!-- 回應內容區塊 -->
                <div class="markdown-body">
                    <span class="typing-output"></span><span class="typing-cursor">◍</span>
                </div>
            </div>
        `;

        const statusLogToggle = row.querySelector('.status-log-toggle');
        const statusLogHistory = row.querySelector('.status-log');
        if (statusLogToggle && statusLogHistory) {
            statusLogToggle.addEventListener('click', () => {
                const isHidden = statusLogHistory.style.display === 'none';
                statusLogHistory.style.display = isHidden ? 'block' : 'none';
                statusLogToggle.textContent = isHidden ? '▲' : '▼';
            });
        }

        return {
            row: row,
            detailsWrapper: row.querySelector('.workflow-details'),
            detailsLabel: row.querySelector('.thought-label'),
            statusLog: row.querySelector('.status-log'),
            statusLogLatest: row.querySelector('.status-log-latest'),
            thoughtsContainer: row.querySelector('.ai-thoughts'),
            thoughtsContent: row.querySelector('.thoughts-content'),
            toolsContainer: row.querySelector('.tool-execution-chain'),
            contentOutput: row.querySelector('.typing-output'),
            cursorCb: row.querySelector('.typing-cursor'),
            typingIndicator: row.querySelector('.typing-indicator'),
            timerLabel: row.querySelector('.timer-label'),
            markdownBody: row.querySelector('.markdown-body'),
            chartContainer: row.querySelector('.chart-container'),
            fullText: '', // 用於存儲原始 Markdown 文字，實作即時渲染
            chartImages: [], // 存儲圖表 {base64, title, index}
            chartMapping: null // chart_index → finding_index mapping
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

            // 如果已收到 chart mapping，嵌入圖表
            if (state.chartMapping && state.chartImages.length > 0) {
                this._injectInlineCharts(state);
            }
        } catch (e) {
            console.error("Markdown rendering error:", e);
        }
    }

    _injectInlineCharts(state) {
        // 找所有「發現 N:」標題 (h2/h3/h4 containing "發現")
        const headings = state.markdownBody.querySelectorAll('h2, h3, h4');
        const findingHeadings = [];
        headings.forEach(h => {
            // 匹配「發現 N」或「📊 參數名」格式的標題
            if (h.textContent.match(/發現\s*\d+/) || h.textContent.match(/📊/)) {
                findingHeadings.push(h);
            }
        });

        if (findingHeadings.length === 0) return;

        const mapping = state.chartMapping; // {chart_idx: finding_idx}

        // 收集每個 finding 的圖表
        const findingCharts = {}; // finding_idx → [chart objects]
        const globalCharts = []; // finding_idx === -1

        for (const [chartIdx, findingIdx] of Object.entries(mapping)) {
            const ci = parseInt(chartIdx);
            const fi = parseInt(findingIdx);
            const chart = state.chartImages[ci];
            if (!chart) continue;

            if (fi >= 0 && fi < findingHeadings.length) {
                if (!findingCharts[fi]) findingCharts[fi] = [];
                findingCharts[fi].push(chart);
            } else {
                globalCharts.push(chart);
            }
        }

        // 在每個「發現 N」標題下方插入圖表行
        for (const [fi, charts] of Object.entries(findingCharts)) {
            const heading = findingHeadings[parseInt(fi)];
            if (!heading) continue;

            // 找到這個 heading 後的下一個 heading (或末尾) 之間的內容節點
            // 插入在 heading 的下一個兄弟位置
            const thumbRow = document.createElement('div');
            thumbRow.className = 'inline-chart-row flex gap-2 my-2 flex-wrap';
            thumbRow.style.cssText = 'max-width: 100%; overflow-x: auto;';

            charts.forEach(chart => {
                const thumb = document.createElement('div');
                thumb.className = 'inline-chart-thumb border border-slate-200 rounded-lg overflow-hidden shadow-sm';
                thumb.style.cssText = 'width: 180px; flex-shrink: 0; cursor: pointer;';

                if (chart.title) {
                    const titleDiv = document.createElement('div');
                    titleDiv.className = 'text-[9px] font-medium text-slate-500 px-1.5 py-0.5 bg-slate-50 truncate';
                    titleDiv.textContent = chart.title;
                    titleDiv.title = chart.title; // tooltip
                    thumb.appendChild(titleDiv);
                }

                const img = document.createElement('img');
                img.src = `data:image/png;base64,${chart.base64}`;
                img.alt = chart.title || 'Chart';
                img.style.cssText = 'width: 100%; cursor: zoom-in;';
                img.onclick = () => {
                    const isZoomed = thumb.dataset.zoomed === 'true';
                    thumb.style.width = isZoomed ? '180px' : '640px';
                    thumb.dataset.zoomed = isZoomed ? 'false' : 'true';
                };
                thumb.appendChild(img);
                thumbRow.appendChild(thumb);
            });

            // 插入到 heading 後面
            heading.after(thumbRow);
        }

        // === 第二輪: 用參數名把 global charts 配對到 📊 段落 ===
        if (globalCharts.length > 0) {
            // 抽取 📊 headings 的參數名
            const paramHeadings = findingHeadings
                .map((h, i) => ({ heading: h, idx: i, text: h.textContent }))
                .filter(item => item.text.includes('📊'));

            // 參數名匹配: chart title 包含 heading 中的參數名
            const _extractParam = (text) => {
                // 從 "📊 METROLOGY-COATINGWEIGHT: 正常" 取 "METROLOGY-COATINGWEIGHT"
                const m = text.match(/📊\s*([A-Z][A-Z0-9\-_]+)/i);
                return m ? m[1] : null;
            };

            const usedGlobal = new Set();
            for (const ph of paramHeadings) {
                const paramName = _extractParam(ph.text);
                if (!paramName) continue;

                const matchedCharts = [];
                globalCharts.forEach((chart, gi) => {
                    if (usedGlobal.has(gi)) return;
                    if (chart.title && chart.title.includes(paramName)) {
                        matchedCharts.push(chart);
                        usedGlobal.add(gi);
                    }
                });

                if (matchedCharts.length === 0) continue;

                const thumbRow = document.createElement('div');
                thumbRow.className = 'inline-chart-row flex gap-2 my-2 flex-wrap';
                thumbRow.style.cssText = 'max-width: 100%; overflow-x: auto;';

                matchedCharts.forEach(chart => {
                    const thumb = document.createElement('div');
                    thumb.className = 'inline-chart-thumb border border-slate-200 rounded-lg overflow-hidden shadow-sm';
                    thumb.style.cssText = 'width: 180px; flex-shrink: 0; cursor: pointer;';

                    if (chart.title) {
                        const titleDiv = document.createElement('div');
                        titleDiv.className = 'text-[9px] font-medium text-slate-500 px-1.5 py-0.5 bg-slate-50 truncate';
                        titleDiv.textContent = chart.title;
                        titleDiv.title = chart.title;
                        thumb.appendChild(titleDiv);
                    }

                    const img = document.createElement('img');
                    img.src = `data:image/png;base64,${chart.base64}`;
                    img.alt = chart.title || 'Chart';
                    img.style.cssText = 'width: 100%; cursor: zoom-in;';
                    img.onclick = () => {
                        const isZoomed = thumb.dataset.zoomed === 'true';
                        thumb.style.width = isZoomed ? '180px' : '640px';
                        thumb.dataset.zoomed = isZoomed ? 'false' : 'true';
                    };
                    thumb.appendChild(img);
                    thumbRow.appendChild(thumb);
                });

                ph.heading.after(thumbRow);
            }

            console.log(`[ChartMapping] Name-matched ${usedGlobal.size} global charts to 📊 headings`);
        }

        console.log(`[ChartMapping] Injected charts: ${Object.keys(findingCharts).length} findings, ${globalCharts.length} global`);
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
                } else if (event.content && event.content.startsWith('[MINI_CHART]')) {
                    // [NEW] Mini Chart in thinking flow
                    try {
                        const chartJsonStr = event.content.substring('[MINI_CHART]'.length);
                        const chartData = JSON.parse(chartJsonStr);
                        if (chartData && chartData.type === 'chart') {
                            const chartWrapper = document.createElement('div');
                            chartWrapper.className = "mb-2 p-2 bg-white border border-slate-200 rounded-lg shadow-sm";
                            chartWrapper.style.cssText = "max-width: 320px;";

                            // Title
                            if (chartData.title) {
                                const titleEl = document.createElement('div');
                                titleEl.className = "text-[10px] font-medium text-slate-500 mb-1 truncate";
                                titleEl.textContent = chartData.title;
                                chartWrapper.appendChild(titleEl);
                            }

                            // Canvas
                            const canvasContainer = document.createElement('div');
                            canvasContainer.style.cssText = "width: 280px; height: 160px;";
                            const canvas = document.createElement('canvas');
                            canvas.width = 280;
                            canvas.height = 160;
                            canvasContainer.appendChild(canvas);
                            chartWrapper.appendChild(canvasContainer);

                            state.thoughtsContent.appendChild(chartWrapper);

                            // Render Chart.js
                            try {
                                const ctx = canvas.getContext('2d');
                                const miniConfig = {
                                    type: chartData.chart_type || 'line',
                                    data: {
                                        labels: chartData.labels || [],
                                        datasets: (chartData.datasets || []).map(ds => ({
                                            ...ds,
                                            borderWidth: ds.borderWidth || 1.5,
                                            pointRadius: Math.min(ds.pointRadius || 2, 3),
                                            tension: 0.2,
                                        }))
                                    },
                                    options: {
                                        responsive: true,
                                        maintainAspectRatio: false,
                                        animation: { duration: 300 },
                                        plugins: {
                                            legend: {
                                                display: (chartData.datasets || []).length > 1,
                                                position: 'bottom',
                                                labels: { font: { size: 9 }, boxWidth: 10, padding: 4 }
                                            },
                                            title: { display: false }
                                        },
                                        scales: {
                                            x: {
                                                display: true,
                                                ticks: { font: { size: 8 }, maxRotation: 0, autoSkip: true, maxTicksLimit: 6 },
                                                grid: { display: false }
                                            },
                                            y: {
                                                display: true,
                                                ticks: { font: { size: 8 }, maxTicksLimit: 5 },
                                                grid: { color: 'rgba(0,0,0,0.04)' }
                                            },
                                            ...(chartData.options?.scales || {})
                                        }
                                    }
                                };
                                new Chart(ctx, miniConfig);
                            } catch (chartErr) {
                                console.error('[MiniChart] Render error:', chartErr);
                                canvasContainer.innerHTML = '<span class="text-[10px] text-red-400">chart render failed</span>';
                            }
                        }
                    } catch (parseErr) {
                        console.warn('[MiniChart] Parse error:', parseErr);
                    }
                } else if (event.content && event.content.startsWith('[EVIDENCE_IMG]')) {
                    // [Multimodal] Evidence chart image from matplotlib
                    try {
                        const payload = event.content.substring('[EVIDENCE_IMG]'.length);
                        const pipeIdx = payload.indexOf('|');
                        const toolName = pipeIdx > 0 ? payload.substring(0, pipeIdx) : 'chart';
                        const imgBase64 = pipeIdx > 0 ? payload.substring(pipeIdx + 1) : payload;

                        const chartWrapper = document.createElement('div');
                        chartWrapper.className = "mb-2 p-2 bg-white border border-slate-200 rounded-lg shadow-sm";
                        chartWrapper.style.cssText = "max-width: 480px; cursor: pointer; overflow: visible; position: relative; z-index: 10;";

                        // Title
                        const titleEl = document.createElement('div');
                        titleEl.className = "text-[10px] font-medium text-slate-500 mb-1 flex items-center gap-1";
                        titleEl.innerHTML = `<span style="color:#6366f1">&#9632;</span> ${toolName}`;
                        chartWrapper.appendChild(titleEl);

                        // Image
                        const img = document.createElement('img');
                        img.src = `data:image/png;base64,${imgBase64}`;
                        img.alt = toolName;
                        img.style.cssText = "width: 100%; border-radius: 4px; transition: transform 0.2s; transform-origin: left center;";
                        img.onmouseover = () => { img.style.transform = "scale(1.8)"; chartWrapper.style.zIndex = "999"; };
                        img.onmouseout = () => { img.style.transform = "scale(1)"; chartWrapper.style.zIndex = "10"; };
                        chartWrapper.appendChild(img);

                        state.thoughtsContent.appendChild(chartWrapper);
                    } catch (imgErr) {
                        console.warn('[EvidenceImg] Parse error:', imgErr);
                    }
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

                // [Safety] Detect if accumulated text is accidentally JSON
                if (state.fullText.length > 200 && !state._jsonCheckDone) {
                    const trimmed = state.fullText.trim();
                    if (trimmed.startsWith('{') && trimmed.includes('"response"')) {
                        state._jsonCheckDone = true;
                        console.warn('[Analysis] Detected JSON structure in text_chunk stream, will extract on completion');
                        state._suspectedJson = true;
                    } else {
                        state._jsonCheckDone = true;
                    }
                }

                this.updateMarkdown(state);
                this.scrollToBottom();
                break;

            case 'status':
                // Append to log instead of replacing statusText header
                if (event.content && state.statusLog) {
                    // Turn Numbering (from backend)
                    const turn = event.turn ?? state._lastKnownTurn ?? 0;
                    if (event.turn !== undefined && event.turn > 0) state._lastKnownTurn = event.turn;

                    // [MINI_CHART] 檢測: 圖表渲染到 "AI 思考流程" 區塊
                    if (event.content.startsWith('[MINI_CHART]')) {
                        // Status log 只顯示簡短文字
                        const logItem = document.createElement('div');
                        logItem.textContent = `Step ${turn}: [圖表已渲染至思考流程]`;
                        logItem.style.color = '#94a3b8';
                        state.statusLog.appendChild(logItem);

                        // 圖表渲染到 thoughtsContent
                        try {
                            const chartJsonStr = event.content.substring('[MINI_CHART]'.length);
                            const chartData = JSON.parse(chartJsonStr);
                            if (chartData && chartData.type === 'chart' && state.thoughtsContent) {
                                // 確保 思考區塊 可見
                                if (state.thoughtsContainer) {
                                    state.thoughtsContainer.classList.remove('hidden');
                                }

                                const chartWrapper = document.createElement('div');
                                chartWrapper.className = "mb-2 p-2 bg-white border border-slate-200 rounded-lg shadow-sm";

                                // 動態尺寸: 複雜圖表類型給更大空間
                                const complexTypes = ['radar', 'scatter', 'bubble'];
                                const isComplex = complexTypes.includes(chartData.chart_type) ||
                                    (chartData.title && chartData.title.includes('平行座標'));
                                const chartW = isComplex ? 480 : 320;
                                const chartH = isComplex ? 280 : 180;
                                chartWrapper.style.cssText = `max-width: ${chartW + 20}px; margin: 6px 0;`;

                                // Title
                                if (chartData.title) {
                                    const titleEl = document.createElement('div');
                                    titleEl.className = "text-[11px] font-medium text-slate-600 mb-1";
                                    titleEl.textContent = chartData.title;
                                    chartWrapper.appendChild(titleEl);
                                }

                                // Canvas
                                const canvasContainer = document.createElement('div');
                                canvasContainer.style.cssText = `width: ${chartW}px; height: ${chartH}px;`;
                                const canvas = document.createElement('canvas');
                                canvas.width = chartW;
                                canvas.height = chartH;
                                canvasContainer.appendChild(canvas);
                                chartWrapper.appendChild(canvasContainer);

                                state.thoughtsContent.appendChild(chartWrapper);

                                // Render Chart.js
                                try {
                                    const ctx = canvas.getContext('2d');
                                    const miniConfig = {
                                        type: chartData.chart_type || 'line',
                                        data: {
                                            labels: chartData.labels || [],
                                            datasets: (chartData.datasets || []).map(ds => ({
                                                ...ds,
                                                borderWidth: ds.borderWidth || 1.5,
                                                pointRadius: Array.isArray(ds.pointRadius)
                                                    ? ds.pointRadius
                                                    : Math.min(ds.pointRadius || 2, 3),
                                                tension: 0.2,
                                            }))
                                        },
                                        options: {
                                            responsive: true,
                                            maintainAspectRatio: false,
                                            animation: { duration: 300 },
                                            plugins: {
                                                legend: {
                                                    display: (chartData.datasets || []).length > 1 && (chartData.datasets || []).length <= 5,
                                                    position: 'bottom',
                                                    labels: { font: { size: 9 }, boxWidth: 10, padding: 4 }
                                                },
                                                title: { display: false }
                                            },
                                            scales: {
                                                x: {
                                                    display: true,
                                                    ticks: { font: { size: 8 }, maxRotation: 0, autoSkip: true, maxTicksLimit: 6 },
                                                    grid: { display: false }
                                                },
                                                y: {
                                                    display: true,
                                                    ticks: { font: { size: 8 }, maxTicksLimit: 5 },
                                                    grid: { color: 'rgba(0,0,0,0.04)' }
                                                },
                                                ...(chartData.options?.scales || {})
                                            }
                                        }
                                    };
                                    new Chart(ctx, miniConfig);
                                } catch (chartErr) {
                                    console.error('[MiniChart] Render error:', chartErr);
                                    canvasContainer.innerHTML = '<span class="text-[10px] text-red-400">chart render failed</span>';
                                }
                            }
                        } catch (parseErr) {
                            console.warn('[MiniChart] Parse error:', parseErr);
                        }
                    } else {
                        // 普通 status 訊息: 只顯示最新一筆，舊的收進摺疊
                        if (!state._statusCounter) state._statusCounter = 0;
                        state._statusCounter++;
                        const stepNum = state._statusCounter;

                        const latestEl = state.statusLogLatest;
                        if (latestEl) {
                            latestEl.textContent = event.content;
                        }
                        // 超過 1 筆時顯示 toggle
                        if (stepNum > 1) {
                            const toggleBtn = state.row.querySelector('.status-log-toggle');
                            if (toggleBtn) toggleBtn.style.display = '';
                        }
                        // 同時加進完整歷史
                        const logItem = document.createElement('div');
                        logItem.textContent = `Step ${stepNum}: ${event.content}`;
                        state.statusLog.appendChild(logItem);
                    }

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

            // === Code Interpreter Events ===

            case 'code_block':
                // Code block: create container (may be empty for streaming)
                if (state.thoughtsContainer) {
                    state.thoughtsContainer.classList.remove('hidden');
                    if (state.detailsWrapper) state.detailsWrapper.open = true;
                }
                if (state.thoughtsContent) {
                    const codeDetails = document.createElement('details');
                    codeDetails.className = "mb-2 rounded-lg overflow-hidden border border-slate-300 shadow-sm";

                    const codeSummary = document.createElement('summary');
                    codeSummary.className = "flex items-center gap-2 px-3 py-1.5 bg-slate-700 text-slate-300 text-[10px] font-mono cursor-pointer select-none";
                    codeSummary.innerHTML = `<span style="color:#f472b6">&#9654;</span> Python <span class="ml-auto text-slate-500">Round ${event.round || 1}</span>`;
                    codeDetails.appendChild(codeSummary);

                    const codeBody = document.createElement('pre');
                    codeBody.className = "p-3 bg-slate-900 text-green-300 text-[11px] font-mono leading-relaxed overflow-auto max-h-80 whitespace-pre-wrap";
                    codeBody.style.resize = "vertical";
                    codeBody.id = `code-body-round-${event.round || 1}`;
                    if (event.code) {
                        codeBody.textContent = event.code;
                    }
                    codeDetails.appendChild(codeBody);

                    state.thoughtsContent.appendChild(codeDetails);
                    this.scrollToBottom();
                }
                break;

            case 'code_chunk':
                // Typewriter: append chunk to current round's code body
                if (state.thoughtsContent && event.chunk) {
                    const roundNum = event.round || 1;
                    // 用 state.row 做 scoped 搜尋，避免跨分析 ID 碰撞
                    if (!state._msgId) state._msgId = Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
                    const codeId = `code-body-${state._msgId}-r${roundNum}`;
                    let codeBody = document.getElementById(codeId);

                    // Race condition fix: code_chunk may arrive before code_block
                    if (!codeBody) {
                        // Auto-create code container
                        if (state.thoughtsContainer) {
                            state.thoughtsContainer.classList.remove('hidden');
                            if (state.detailsWrapper) state.detailsWrapper.open = true;
                        }
                        const codeDetails = document.createElement('details');
                        codeDetails.className = "mb-2 rounded-lg overflow-hidden border border-slate-300 shadow-sm";
                        const codeSummary = document.createElement('summary');
                        codeSummary.className = "flex items-center gap-2 px-3 py-1.5 bg-slate-700 text-slate-300 text-[10px] font-mono cursor-pointer select-none";
                        codeSummary.innerHTML = `<span style="color:#f472b6">&#9654;</span> Python <span class="ml-auto text-slate-500">Round ${roundNum}</span>`;
                        codeDetails.appendChild(codeSummary);
                        codeBody = document.createElement('pre');
                        codeBody.className = "p-3 bg-slate-900 text-green-300 text-[11px] font-mono leading-relaxed overflow-auto max-h-80 whitespace-pre-wrap";
                        codeBody.style.resize = "vertical";
                        codeBody.id = codeId;
                        codeDetails.appendChild(codeBody);
                        state.thoughtsContent.appendChild(codeDetails);
                    }

                    codeBody.textContent += event.chunk;
                    this.scrollToBottom();
                }
                break;

            case 'mini_chart':
                // Tool mode chart: render in chartContainer (survives markdown re-render)
                if (state.chartContainer && event.chart) {
                    try {
                        const chartData = event.chart;
                        const chartWrapper = document.createElement('div');
                        chartWrapper.className = "my-3 p-3 bg-white border border-slate-200 rounded-lg shadow-sm";

                        if (chartData.title) {
                            const title = document.createElement('div');
                            title.className = "text-sm font-semibold text-slate-700 mb-2";
                            title.textContent = chartData.title;
                            chartWrapper.appendChild(title);
                        }

                        const canvas = document.createElement('canvas');
                        canvas.style.maxHeight = '350px';
                        chartWrapper.appendChild(canvas);
                        state.chartContainer.appendChild(chartWrapper);

                        if (typeof Chart !== 'undefined' && chartData.data) {
                            // Apply default styling to datasets
                            if (chartData.data.datasets) {
                                const colors = ['#3B82F6', '#EF4444', '#10B981', '#F59E0B', '#8B5CF6'];
                                chartData.data.datasets.forEach((ds, i) => {
                                    ds.borderWidth = ds.borderWidth || 2;
                                    ds.borderColor = ds.borderColor || colors[i % colors.length];
                                    ds.backgroundColor = ds.backgroundColor || colors[i % colors.length] + '20';
                                    ds.pointRadius = ds.pointRadius === undefined ? 0 : ds.pointRadius;
                                    ds.tension = ds.tension || 0.1;
                                });
                            }
                            new Chart(canvas, {
                                type: chartData.chart_type || 'line',
                                data: chartData.data,
                                options: {
                                    responsive: true,
                                    maintainAspectRatio: false,
                                    plugins: { legend: { display: true } },
                                    scales: { y: { beginAtZero: false } }
                                }
                            });
                        }
                        this.scrollToBottom();
                    } catch (e) {
                        console.error('[mini_chart] render error:', e);
                    }
                }
                break;

            case 'code_output':
                // 程式執行輸出
                if (state.thoughtsContent) {
                    // 即時行輸出 (is_line=true): 追加到既有容器
                    if (event.is_line && event.stdout) {
                        // 找或建立即時輸出容器
                        let liveContainer = state.thoughtsContent.querySelector('.code-output-live-' + (event.round || 1));
                        if (!liveContainer) {
                            const outDetails = document.createElement('details');
                            outDetails.className = `mb-2 rounded-lg overflow-hidden border border-slate-200 shadow-sm code-output-wrapper-${event.round || 1}`;

                            const outSummary = document.createElement('summary');
                            outSummary.className = "flex items-center gap-2 px-3 py-1.5 bg-slate-100 text-slate-600 text-[10px] font-mono cursor-pointer select-none";
                            outSummary.innerHTML = `<span style="color:#22c55e">&#9632;</span> 執行結果 <span class="ml-auto text-slate-400">Round ${event.round || 1}</span>`;
                            outDetails.appendChild(outSummary);

                            liveContainer = document.createElement('pre');
                            liveContainer.className = `p-3 bg-white text-slate-700 text-[11px] font-mono leading-relaxed overflow-auto max-h-80 whitespace-pre-wrap code-output-live-${event.round || 1}`;
                            liveContainer.style.resize = "vertical";
                            outDetails.appendChild(liveContainer);

                            state.thoughtsContent.appendChild(outDetails);
                        }
                        liveContainer.textContent += event.stdout + '\n';
                        this.scrollToBottom();
                    }
                    // 最終輸出 (error/stderr): 建立新容器
                    else if (event.stdout || event.stderr || event.error) {
                        const outWrapper = document.createElement('div');
                        outWrapper.className = "mb-2 rounded-lg overflow-hidden border border-slate-200 shadow-sm";

                        // Header
                        const outHeader = document.createElement('div');
                        outHeader.className = "flex items-center gap-2 px-3 py-1.5 bg-slate-100 text-slate-600 text-[10px] font-mono";
                        outHeader.innerHTML = `<span style="color:#22c55e">&#9632;</span> 執行結果 <span class="ml-auto text-slate-400">Round ${event.round || 1}</span>`;
                        outWrapper.appendChild(outHeader);

                        // Output body
                        const outBody = document.createElement('pre');
                        outBody.className = "p-3 bg-white text-slate-700 text-[11px] font-mono leading-relaxed overflow-auto max-h-60 whitespace-pre-wrap";

                        let outputText = '';
                        if (event.stdout) outputText += event.stdout;
                        if (event.stderr) outputText += (outputText ? '\n' : '') + event.stderr;
                        if (event.error) {
                            outBody.className = "p-3 bg-red-50 text-red-700 text-[11px] font-mono leading-relaxed overflow-auto max-h-60 whitespace-pre-wrap";
                            outputText += (outputText ? '\n' : '') + '--- ERROR ---\n' + event.error;
                        }
                        outBody.textContent = outputText;
                        outWrapper.appendChild(outBody);

                        state.thoughtsContent.appendChild(outWrapper);
                        this.scrollToBottom();
                    }
                }
                break;

            case 'chart_image':
                // matplotlib 圖表: 同一 Round 的圖表收在同一個摺疊裡
                if (event.image_base64) {
                    const targetContainer = state.chartContainer || state.markdownBody;
                    if (!targetContainer) break;

                    const roundKey = event.round || 'pre';
                    const containerId = `chart-group-round-${roundKey}`;

                    // 找或建立該 Round 的摺疊容器
                    let chartDetails = targetContainer.querySelector(`#${containerId}`);
                    let chartBody;
                    if (!chartDetails) {
                        chartDetails = document.createElement('details');
                        chartDetails.id = containerId;
                        chartDetails.className = "mb-2 rounded-lg overflow-hidden border border-slate-200 shadow-sm";

                        const chartSummary = document.createElement('summary');
                        chartSummary.className = "flex items-center gap-2 px-3 py-1.5 bg-blue-50 text-slate-600 text-[10px] font-mono cursor-pointer select-none";
                        const roundLabel = roundKey === 'pre' ? '前處理' : `Round ${roundKey}`;
                        chartSummary.innerHTML = `<span style="color:#3B82F6">&#9632;</span> 分析圖表 <span class="chart-count-badge ml-1 text-[9px] bg-blue-100 text-blue-600 px-1.5 rounded-full">1</span> <span class="ml-auto text-slate-400">${roundLabel}</span>`;
                        chartDetails.appendChild(chartSummary);

                        chartBody = document.createElement('div');
                        chartBody.className = "p-2 bg-white space-y-2 chart-body";
                        chartDetails.appendChild(chartBody);

                        // 底部「收起」按鈕（避免滑到最下面後要滾回去關）
                        const collapseBtn = document.createElement('div');
                        collapseBtn.className = "text-center py-1.5 bg-blue-50 text-blue-500 text-[10px] cursor-pointer select-none hover:bg-blue-100 transition-colors";
                        collapseBtn.textContent = "▲ 收起圖表";
                        collapseBtn.onclick = (e) => {
                            e.preventDefault();
                            chartDetails.removeAttribute('open');
                            chartDetails.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                        };
                        chartDetails.appendChild(collapseBtn);

                        targetContainer.appendChild(chartDetails);
                    } else {
                        chartBody = chartDetails.querySelector('.chart-body');
                        // 更新計數
                        const badge = chartDetails.querySelector('.chart-count-badge');
                        if (badge) {
                            const count = chartBody.querySelectorAll('img').length + 1;
                            badge.textContent = count;
                        }
                    }

                    // 圖片 wrapper (含標題)
                    const imgWrapper = document.createElement('div');
                    imgWrapper.className = "border border-slate-100 rounded-lg overflow-hidden";
                    imgWrapper.style.cssText = "max-width: 640px; cursor: pointer;";

                    if (event.title) {
                        const imgTitle = document.createElement('div');
                        imgTitle.className = "text-[10px] font-medium text-slate-500 px-2 py-1 bg-slate-50";
                        imgTitle.textContent = event.title;
                        imgWrapper.appendChild(imgTitle);
                    }

                    const chartImg = document.createElement('img');
                    chartImg.src = `data:image/png;base64,${event.image_base64}`;
                    chartImg.alt = event.title || 'Analysis Chart';
                    chartImg.style.cssText = "width: 100%; border-radius: 0 0 6px 6px; transition: transform 0.3s ease; transform-origin: left center; cursor: zoom-in;";
                    chartImg.onclick = () => {
                        const isZoomed = chartImg.dataset.zoomed === 'true';
                        chartImg.style.transform = isZoomed ? "scale(1)" : "scale(1.5)";
                        chartImg.style.cursor = isZoomed ? "zoom-in" : "zoom-out";
                        imgWrapper.style.overflow = isZoomed ? "hidden" : "visible";
                        imgWrapper.style.zIndex = isZoomed ? "10" : "999";
                        imgWrapper.style.position = isZoomed ? "" : "relative";
                        chartImg.dataset.zoomed = isZoomed ? 'false' : 'true';
                    };
                    imgWrapper.appendChild(chartImg);
                    chartBody.appendChild(imgWrapper);

                    // 存儲圖表以供 chart_mapping 使用
                    state.chartImages.push({
                        base64: event.image_base64,
                        title: event.title || '',
                        round: event.round || 0,
                    });

                    this.scrollToBottom();
                }
                break;

            case 'chart_mapping':
                // 收到 chart-to-finding mapping (from Evidence Evaluator)
                console.log('[ChartMapping] Received mapping:', event);
                state.chartMapping = event; // {"0": 0, "1": 1, "2": -1, ...}
                break;

            case 'intent_confirmation':
                // Route intent 需要用戶確認分析參數
                console.log('[IntentConfirmation] Received:', event);
                // Remove empty streaming message row (analysis didn't run)
                if (state && state.row) {
                    state.row.remove();
                }
                this.showIntentConfirmation(event);
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

                    // [Enhanced] 更積極地檢測和提取 JSON 包裝的內容
                    if (typeof finalContent === 'string' && finalContent.trim().startsWith('{')) {
                        try {
                            const parsed = JSON.parse(finalContent.trim());
                            if (parsed.response || parsed.content || parsed.summary) {
                                finalContent = parsed.response || parsed.content || parsed.summary;
                                console.log("[Analysis] Extracted content from JSON-wrapped output");
                            }
                        } catch (e) {
                            // 不是完整的 JSON，嘗試 regex 提取
                            const jsonMatch = finalContent.match(/^\s*\{\s*"response"\s*:\s*"([\s\S]+?)"\s*[,}]/);
                            if (jsonMatch && jsonMatch[1] && jsonMatch[1].length > 50) {
                                // 還原 JSON 轉義字元
                                finalContent = jsonMatch[1]
                                    .replace(/\\n/g, '\n')
                                    .replace(/\\t/g, '\t')
                                    .replace(/\\\\/g, '\\')
                                    .replace(/\\"/g, '"');
                                console.log("[Analysis] Regex-extracted content from partial JSON");
                            }
                        }
                    }

                    // [Safety] 如果 fullText 被標記為疑似 JSON 且 backendContent 可用，優先使用 backendContent
                    if (state._suspectedJson && backendContent && typeof backendContent === 'string' && !backendContent.trim().startsWith('{')) {
                        finalContent = backendContent;
                        console.log("[Analysis] Used backendContent over suspected JSON fullText");
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

                    // === 方案 E: Inline Chart Injection ===
                    // 報告渲染完後，把匹配的圖表插入「發現 N」段落下方
                    // Stream 上方的圖預設收合
                    setTimeout(() => {
                        try {
                            const msgRow = state.markdownBody.closest('.message-row');
                            if (!msgRow) return;
                            const allChartImgs = Array.from(msgRow.querySelectorAll('.chart-body img'));
                            if (allChartImgs.length === 0) return;

                            // 1) 收合 stream 上方的圖表 <details>
                            msgRow.querySelectorAll('.chart-container details[open]').forEach(d => {
                                d.removeAttribute('open');
                            });

                            // 1.5) 前處理圖表縮圖 → 插入到「分析概述」後面
                            //      但如果有 📊 heading (目標參數模式)，不放概述，改由 _injectInlineCharts 處理
                            const hasParamHeadings = Array.from(state.markdownBody.querySelectorAll('h2, h3, h4')).some(h => h.textContent.includes('\u{1F4CA}'));
                            const preprocessImgs = allChartImgs.filter(img =>
                                (img.alt || '').includes('前處理') || (img.closest('div')?.textContent || '').includes('前處理')
                            );
                            if (preprocessImgs.length > 0 && !hasParamHeadings) {
                                // 找「分析概述」或報告第一個 heading / 第一個 <p>
                                const allEls = state.markdownBody.querySelectorAll('h2, h3, p');
                                let summaryAnchor = null;
                                for (const el of allEls) {
                                    const t = el.textContent || '';
                                    if (/分析概述|概覽|Overview|Summary|報告/i.test(t)) {
                                        summaryAnchor = el;
                                        break;
                                    }
                                }
                                // fallback: 第一個 <p>
                                if (!summaryAnchor) {
                                    summaryAnchor = state.markdownBody.querySelector('p');
                                }
                                if (summaryAnchor) {
                                    const prepBlock = document.createElement('div');
                                    prepBlock.style.cssText = 'margin: 8px 0 12px; display: flex; gap: 6px; flex-wrap: wrap;';
                                    preprocessImgs.forEach(img => {
                                        const thumb = document.createElement('img');
                                        thumb.src = img.src;
                                        thumb.alt = img.alt || '前處理圖表';
                                        thumb.title = img.alt || '點擊放大';
                                        thumb.style.cssText = 'height: 80px; border-radius: 6px; border: 1px solid rgba(0,0,0,0.08); cursor: pointer; opacity: 0.85; transition: all 0.2s ease;';
                                        thumb.onmouseenter = () => { thumb.style.opacity = '1'; thumb.style.transform = 'scale(1.05)'; thumb.style.boxShadow = '0 3px 10px rgba(0,0,0,0.12)'; };
                                        thumb.onmouseleave = () => { thumb.style.opacity = '0.85'; thumb.style.transform = 'scale(1)'; thumb.style.boxShadow = 'none'; };
                                        thumb.onclick = () => {
                                            const srcs = preprocessImgs.map(i => i.src);
                                            window._openLightbox(srcs, srcs.indexOf(img.src));
                                        };
                                        prepBlock.appendChild(thumb);
                                    });
                                    if (summaryAnchor.nextSibling) {
                                        summaryAnchor.parentNode.insertBefore(prepBlock, summaryAnchor.nextSibling);
                                    } else {
                                        summaryAnchor.parentNode.appendChild(prepBlock);
                                    }
                                }
                            }

                            // 2) 掃描 markdown 裡的「發現」區段
                            //    可能是 h2/h3 heading 或 **發現 N:** 等
                            const allElements = state.markdownBody.querySelectorAll('h2, h3, p, li, strong');
                            const findingPattern = /發現\s*\d+|Finding\s*\d+/i;
                            const sections = []; // [{heading, textBlock, element}]

                            allElements.forEach(el => {
                                const txt = el.textContent || '';
                                if (findingPattern.test(txt)) {
                                    // 收集這個 heading 和後續兄弟元素的文字作為 section
                                    let fullText = txt;
                                    let lastEl = el;
                                    let sib = el.nextElementSibling;
                                    // 往下收集直到下一個 finding、行動建議標題、或最多 8 個兄弟
                                    const stopPattern = /行動|建議|結論|摘要|Action|Recommend|Summary/i;
                                    let sibCount = 0;
                                    while (sib && sibCount < 8) {
                                        const sibText = sib.textContent || '';
                                        if (findingPattern.test(sibText)) break;
                                        if (stopPattern.test(sibText) && (sib.tagName === 'H2' || sib.tagName === 'H3' || sib.tagName === 'H4' || sib.tagName === 'STRONG')) break;
                                        fullText += ' ' + sibText;
                                        lastEl = sib;
                                        sib = sib.nextElementSibling;
                                        sibCount++;
                                    }
                                    sections.push({ heading: el, fullText, insertAfter: lastEl });
                                }
                            });

                            if (sections.length === 0) return;

                            // 3) 對每個 section，提取 keywords 並匹配圖表
                            const usedSrcs = new Set();
                            sections.forEach(sec => {
                                const colMatches = sec.fullText.match(/[A-Z][A-Z0-9_-]{4,}/g) || [];
                                const ivMatches = sec.fullText.match(/#(\d+-\d+)/g) || [];
                                const intervals = ivMatches.map(m => m.replace('#', ''));
                                const keywords = [...new Set([...intervals, ...colMatches])].filter(k => k.length > 3);
                                if (keywords.length === 0) return;

                                const matched = [];
                                const localSeen = new Set(); // 同一 finding 內避免重複
                                allChartImgs.forEach(img => {
                                    const wrapperText = img.closest('div')?.textContent || '';
                                    const searchText = `${img.alt || ''} ${wrapperText}`.toLowerCase();
                                    const isMatch = keywords.some(kw => searchText.includes(kw.toLowerCase()));
                                    if (isMatch && !localSeen.has(img.src) && matched.length < 6) {
                                        localSeen.add(img.src);
                                        usedSrcs.add(img.src); // 只用來決定「其他圖表」
                                        matched.push({ src: img.src, alt: img.alt || wrapperText.trim().slice(0, 60) || '' });
                                    }
                                });
                                console.log(`[ChartMatch] Section: "${sec.fullText.slice(0, 80)}..." | keywords:`, keywords, `| matched: ${matched.length}/${allChartImgs.length}`);
                                if (matched.length === 0) {
                                    console.log(`[ChartMatch] ❌ No match. Chart alts:`, allChartImgs.map(i => i.alt));
                                    return;
                                }

                                // 4) 建立 inline 縮圖列
                                const chartBlock = document.createElement('div');
                                chartBlock.style.cssText = 'margin: 8px 0 16px; display: flex; gap: 6px; flex-wrap: wrap;';

                                matched.forEach(m => {
                                    const thumb = document.createElement('img');
                                    thumb.src = m.src;
                                    thumb.alt = m.alt;
                                    thumb.title = m.alt || '點擊放大';
                                    thumb.style.cssText = 'height: 100px; border-radius: 6px; border: 1px solid rgba(0,0,0,0.08); cursor: pointer; opacity: 0.8; transition: all 0.2s ease;';
                                    thumb.onmouseenter = () => { thumb.style.opacity = '1'; thumb.style.transform = 'scale(1.05)'; thumb.style.boxShadow = '0 3px 10px rgba(0,0,0,0.12)'; };
                                    thumb.onmouseleave = () => { thumb.style.opacity = '0.8'; thumb.style.transform = 'scale(1)'; thumb.style.boxShadow = 'none'; };
                                    thumb.onclick = () => {
                                        window._openLightbox(matched.map(x => x.src), matched.indexOf(m));
                                    };
                                    chartBlock.appendChild(thumb);
                                });

                                // 5) 插入到該段落後面
                                if (sec.insertAfter.nextSibling) {
                                    sec.insertAfter.parentNode.insertBefore(chartBlock, sec.insertAfter.nextSibling);
                                } else {
                                    sec.insertAfter.parentNode.appendChild(chartBlock);
                                }
                            });

                            // 6) 沒有被任何 finding 匹配的圖，放最後作為「其他圖表」
                            const unmatchedImgs = allChartImgs.filter(img => !usedSrcs.has(img.src));
                            if (unmatchedImgs.length > 0) {
                                const otherBlock = document.createElement('details');
                                otherBlock.style.cssText = 'margin-top: 16px; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden;';
                                const otherSummary = document.createElement('summary');
                                otherSummary.style.cssText = 'padding: 8px 12px; background: #f8fafc; font-size: 11px; font-weight: 600; color: #94a3b8; cursor: pointer; letter-spacing: 0.5px;';
                                otherSummary.textContent = `📊 其他圖表 (${unmatchedImgs.length})`;
                                otherBlock.appendChild(otherSummary);
                                const otherBody = document.createElement('div');
                                otherBody.style.cssText = 'padding: 8px; display: flex; gap: 6px; flex-wrap: wrap;';
                                unmatchedImgs.forEach(img => {
                                    const thumb = document.createElement('img');
                                    thumb.src = img.src;
                                    thumb.alt = img.alt || '';
                                    thumb.style.cssText = 'height: 72px; border-radius: 6px; border: 1px solid rgba(0,0,0,0.08); cursor: pointer; opacity: 0.8;';
                                    thumb.onclick = () => {
                                        const allSrcs = unmatchedImgs.map(x => x.src);
                                        window._openLightbox(allSrcs, allSrcs.indexOf(img.src));
                                    };
                                    otherBody.appendChild(thumb);
                                });
                                otherBlock.appendChild(otherBody);
                                state.markdownBody.appendChild(otherBlock);
                            }
                        } catch (e) { console.warn('[Analysis] Inline chart injection error:', e); }
                    }, 150);

                    // --- Render Scene Suggestion Buttons (場景選擇按鈕) ---
                    // follow_up_items 在 StopEvent 的 data 子物件中
                    const eventData = (event && event.data) || event || {};
                    console.log('[Analysis] response event keys:', Object.keys(event));
                    console.log('[Analysis] event.data keys:', event.data ? Object.keys(event.data) : 'no data');
                    console.log('[Analysis] follow_up_items:', eventData.follow_up_items);
                    const followUpItems = eventData.follow_up_items || event.follow_up_items || [];
                    const sceneItems = followUpItems.filter(item =>
                        item && typeof item === 'object' && item.scene_id
                    );
                    if (sceneItems.length > 0) {
                        const sceneDiv = document.createElement('div');
                        sceneDiv.style.cssText = 'margin-top: 20px; border-top: 2px solid rgba(139,92,246,0.2); padding-top: 16px;';

                        const sceneTitleEl = document.createElement('div');
                        sceneTitleEl.style.cssText = 'font-size: 13px; font-weight: 700; color: #7c3aed; margin-bottom: 10px; display: flex; align-items: center; gap: 6px;';
                        sceneTitleEl.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#7c3aed" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 8v4l3 3"/></svg> 可深入分析的方向`;
                        sceneDiv.appendChild(sceneTitleEl);

                        const sceneGrid = document.createElement('div');
                        sceneGrid.style.cssText = 'display: flex; flex-wrap: wrap; gap: 8px;';

                        sceneItems.forEach(item => {
                            const btn = document.createElement('button');
                            btn.style.cssText = `
                                padding: 8px 14px;
                                background: linear-gradient(135deg, #f5f3ff 0%, #ede9fe 100%);
                                border: 1px solid #c4b5fd;
                                border-radius: 8px;
                                font-size: 12px;
                                color: #5b21b6;
                                font-weight: 500;
                                cursor: pointer;
                                transition: all 0.2s ease;
                                display: flex;
                                align-items: center;
                                gap: 6px;
                                text-align: left;
                                line-height: 1.4;
                            `;
                            btn.onmouseenter = () => {
                                btn.style.background = 'linear-gradient(135deg, #ede9fe 0%, #ddd6fe 100%)';
                                btn.style.borderColor = '#a78bfa';
                                btn.style.transform = 'translateY(-1px)';
                                btn.style.boxShadow = '0 2px 8px rgba(139,92,246,0.15)';
                            };
                            btn.onmouseleave = () => {
                                btn.style.background = 'linear-gradient(135deg, #f5f3ff 0%, #ede9fe 100%)';
                                btn.style.borderColor = '#c4b5fd';
                                btn.style.transform = 'translateY(0)';
                                btn.style.boxShadow = 'none';
                            };

                            const badge = document.createElement('span');
                            badge.style.cssText = 'font-size: 10px; font-weight: 700; background: #7c3aed; color: white; padding: 1px 6px; border-radius: 4px; flex-shrink: 0;';
                            badge.textContent = item.scene_id;

                            const label = document.createElement('span');
                            label.textContent = item.label;

                            btn.appendChild(badge);
                            btn.appendChild(label);

                            // Click handler: send scene select message
                            btn.addEventListener('click', () => {
                                const sceneMsg = `[SCENE_SELECT:${item.scene_id}] ${item.label}`;
                                this.elements.userInput.value = sceneMsg;
                                this.sendMessage();
                            });

                            sceneGrid.appendChild(btn);
                        });

                        sceneDiv.appendChild(sceneGrid);
                        state.markdownBody.appendChild(sceneDiv);
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
                state.contentOutput.textContent += `❌ ${event.detail || event.content || event.message || '未知錯誤'}`;
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
            let url = `/api/analysis/mapping-status?session_id=${this.sessionId}`;
            if (this.currentFileId) {
                url += `&file_id=${this.currentFileId}`;
            }
            const response = await fetch(url);
            const badge = document.getElementById('mapping-badge');
            const modalName = document.getElementById('mapping-modal-name');
            const deleteBtn = document.getElementById('btn-mapping-delete');

            if (response.ok) {
                const data = await response.json();
                if (data.active_mapping) {
                    this.elements.mappingFileName.textContent = data.active_mapping;
                    if (badge) {
                        badge.textContent = '已就緒';
                        badge.className = 'px-1.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-600 cursor-pointer hover:opacity-80 transition-opacity';
                    }
                    if (modalName) {
                        modalName.textContent = data.active_mapping;
                        modalName.className = 'font-medium ml-1 text-green-600';
                    }
                    if (deleteBtn) deleteBtn.classList.remove('hidden');
                } else {
                    this.elements.mappingFileName.textContent = '尚未設定';
                    if (badge) {
                        badge.textContent = '未設定';
                        badge.className = 'px-1.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-400 cursor-pointer hover:opacity-80 transition-opacity';
                    }
                    if (modalName) {
                        modalName.textContent = '尚未設定';
                        modalName.className = 'font-medium ml-1 text-gray-400';
                    }
                    if (deleteBtn) deleteBtn.classList.add('hidden');
                }
            }
        } catch (error) {
            console.error('Failed to check mapping status:', error);
        }
    }

    openMappingModal() {
        const modal = document.getElementById('mapping-modal');
        if (modal) { modal.classList.remove('hidden'); modal.classList.add('flex'); }
    }

    closeMappingModal() {
        const modal = document.getElementById('mapping-modal');
        if (modal) { modal.classList.add('hidden'); modal.classList.remove('flex'); }
    }

    async deleteMapping() {
        if (!confirm('確定要移除術語對應表嗎？')) return;
        try {
            let url = `/api/analysis/mapping?session_id=${this.sessionId}`;
            if (this.currentFileId) {
                url += `&file_id=${this.currentFileId}`;
            }
            const response = await fetch(url, { method: 'DELETE' });
            if (response.ok) {
                await this.checkMappingStatus();
                this.closeMappingModal();
            } else {
                const err = await response.json();
                alert(`移除失敗: ${err.detail || '未知錯誤'}`);
            }
        } catch (error) {
            console.error('Delete mapping error:', error);
            alert('移除對應表時發生錯誤');
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
        }

        try {
            this.elements.mappingFileName.textContent = '上傳中...';
            const badge = document.getElementById('mapping-badge');
            if (badge) badge.textContent = '上傳中...';

            const response = await fetch('/api/analysis/upload', {
                method: 'POST',
                body: formData
            });

            if (response.ok) {
                await this.checkMappingStatus();
                this.closeMappingModal();
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

    // --- Data Description (資料描述) ---
    _updateDescriptionBadge(description) {
        const badge = document.getElementById('description-badge');
        if (!badge) return;
        if (description && description.trim()) {
            badge.textContent = '已設定';
            badge.className = 'px-1.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-600 cursor-pointer hover:opacity-80 transition-opacity';
        } else {
            badge.textContent = '未設定';
            badge.className = 'px-1.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-400 cursor-pointer hover:opacity-80 transition-opacity';
        }
    }

    async loadDataDescription(fileId) {
        if (!fileId) return;
        const input = this.elements.dataDescriptionInput;
        if (!input) return;

        input.value = '';
        this._updateDescriptionBadge('');

        try {
            const res = await fetch(`/api/analysis/data_description/${fileId}`);
            if (res.ok) {
                const data = await res.json();
                const desc = data.description || '';
                input.value = desc;
                this._updateDescriptionBadge(desc);
            }
        } catch (err) {
            console.error('[DataDesc] Load failed:', err);
        }
    }

    async saveDataDescription() {
        const input = this.elements.dataDescriptionInput;
        if (!input || !this.currentFileId) return;

        const description = input.value.trim();

        try {
            const res = await fetch('/api/analysis/data_description', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    file_id: this.currentFileId,
                    description: description
                })
            });
            if (res.ok) {
                this._updateDescriptionBadge(description);
            }
        } catch (err) {
            console.error('[DataDesc] Save failed:', err);
        }
    }

    openDescriptionModal() {
        const modal = document.getElementById('description-modal');
        const modalInput = document.getElementById('description-modal-input');
        const counter = document.getElementById('description-modal-count');
        if (!modal) return;

        // Sync value from hidden input to modal textarea
        const currentDesc = this.elements.dataDescriptionInput ? this.elements.dataDescriptionInput.value : '';
        if (modalInput) {
            modalInput.value = currentDesc;
            // Live counter
            if (counter) counter.textContent = `${currentDesc.length}/500`;
            modalInput.oninput = () => {
                if (counter) counter.textContent = `${modalInput.value.length}/500`;
            };
        }
        modal.classList.remove('hidden');
        modal.classList.add('flex');
        if (modalInput) modalInput.focus();
    }

    closeDescriptionModal() {
        const modal = document.getElementById('description-modal');
        if (modal) { modal.classList.add('hidden'); modal.classList.remove('flex'); }
    }

    async saveDescriptionFromModal() {
        const modalInput = document.getElementById('description-modal-input');
        const statusEl = document.getElementById('description-modal-status');
        if (!modalInput || !this.currentFileId) return;

        const description = modalInput.value.trim();
        // Sync to hidden input
        if (this.elements.dataDescriptionInput) this.elements.dataDescriptionInput.value = description;

        if (statusEl) { statusEl.textContent = '儲存中...'; statusEl.className = 'text-[10px] text-gray-400'; }

        try {
            const res = await fetch('/api/analysis/data_description', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ file_id: this.currentFileId, description })
            });
            if (res.ok) {
                this._updateDescriptionBadge(description);
                if (statusEl) { statusEl.textContent = '已儲存'; statusEl.className = 'text-[10px] text-green-500'; }
                setTimeout(() => this.closeDescriptionModal(), 600);
            } else {
                if (statusEl) { statusEl.textContent = '儲存失敗'; statusEl.className = 'text-[10px] text-red-400'; }
            }
        } catch (err) {
            console.error('[DataDesc] Save failed:', err);
            if (statusEl) { statusEl.textContent = '儲存失敗'; statusEl.className = 'text-[10px] text-red-400'; }
        }
    }

    async clearDescriptionFromModal() {
        const modalInput = document.getElementById('description-modal-input');
        if (modalInput) modalInput.value = '';
        if (this.elements.dataDescriptionInput) this.elements.dataDescriptionInput.value = '';
        const counter = document.getElementById('description-modal-count');
        if (counter) counter.textContent = '0/500';

        if (!this.currentFileId) return;
        try {
            await fetch('/api/analysis/data_description', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ file_id: this.currentFileId, description: '' })
            });
            this._updateDescriptionBadge('');
            this.closeDescriptionModal();
        } catch (err) {
            console.error('[DataDesc] Clear failed:', err);
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

        let query = `[DRAW:${col}] 請幫我繪製 ${col} 的趨勢圖`;
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

            // Initialize range rows container with one empty row
            const rangeContainer = document.getElementById('dm-range-rows');
            if (rangeContainer) {
                rangeContainer.innerHTML = '';
                addDmRangeRow();
            }

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
            div.ondblclick = () => this.moveMiningItem(p, 'source', 'y');
            div.innerHTML = `<span class="truncate text-sm flex-1 pointer-events-none select-none" title="${p}">${p}</span>`;
            sourceList.appendChild(div);
        });

        // 2. Render Y List
        this.miningState.y.forEach(p => {
            const isSelected = this.miningState.selectedY.has(p);
            const div = document.createElement('div');
            div.className = `flex items-center gap-2 py-2 px-3 border border-transparent rounded-lg cursor-pointer transition-all select-none ${isSelected ? 'bg-blue-200 border-blue-400 text-blue-900' : 'hover:bg-blue-100 text-gray-700'}`;
            div.onclick = (e) => this.toggleSelection(p, 'y', e);
            div.ondblclick = () => this.moveMiningItem(p, 'y', 'source');
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

        // Read multi-segment target ranges from row inputs
        const rangeRows = document.querySelectorAll('#dm-range-rows .dm-range-row');
        const ranges = [];
        rangeRows.forEach(row => {
            const start = row.querySelector('.dm-range-start')?.value?.trim();
            const end = row.querySelector('.dm-range-end')?.value?.trim();
            if (start && end) ranges.push(`${start}-${end}`);
            else if (start) ranges.push(start);
        });
        let targetRange = ranges.length > 0 ? ranges.join(', ') : null;

        let query = '';

        // Build query based on selections
        if (targets.length === 0) {
            query = `深度資料探勘: 1) 找出異常欄位（哪些參數有問題）2) 找出異常區間（哪些資料點/樣本是異常的，標出第幾筆到第幾筆）3) 分析異常欄位之間的關聯性。三個維度都要分析，不要只做欄位分析`;
        } else {
            query = `請對目標欄位 ${targets.join(', ')} 進行深度資料探勘與異常分析`;
        }

        if (targetRange) {
            query += `，分析區間為第 ${targetRange} 筆`;
        } else {
            query += `，分析全域數據`;
        }

        query += `。找出關聯影響因子、異常區段與區間差異。`;

        // Store structured metadata for sendMessage
        this.miningMetadata = {
            suspect_params: targets.length > 0 ? targets : null,
            target_range: targetRange
        };

        // Read baseline mode from radio
        const baselineMode = document.querySelector('input[name="dm-baseline-mode"]:checked')?.value || 'auto';
        if (baselineMode === 'auto' && targetRange) {
            this.miningMetadata.baseline_range = '__AUTO__';
        } else if (baselineMode === 'specify') {
            const blStart = document.getElementById('dm-baseline-start')?.value?.trim();
            const blEnd = document.getElementById('dm-baseline-end')?.value?.trim();
            if (blStart && blEnd) this.miningMetadata.baseline_range = `${blStart}-${blEnd}`;
            else if (blStart) this.miningMetadata.baseline_range = blStart;
        }
        // baselineMode === 'none' → don't set baseline_range

        // If triggered from intent_confirmation, use pending query & task prefix
        if (this._pendingIntentTaskType) {
            const taskType = this._pendingIntentTaskType;
            const intentQuery = this._pendingIntentQuery || '';
            query = `[TASK:${taskType}] ${intentQuery || query}`;
            this._pendingIntentTaskType = null;
            this._pendingIntentQuery = null;
        }

        this.elements.userInput.value = query;
        this.elements.userInput.style.height = 'auto';
        this.elements.userInput.style.height = this.elements.userInput.scrollHeight + 'px';
        this.elements.btnSend.disabled = false;
        this.sendMessage();

        closeMiningPanel();
    }

    showIntentConfirmation(intentData) {
        // Store pending intent info for use when user confirms via modal
        this._pendingIntentQuery = intentData.restatement;
        this._pendingIntentTaskType = intentData.task_type;

        // Open the mining modal (reuse wizard UI)
        this.openDataMiningModal();

        // Pre-fill target range rows
        if (intentData.target_range) {
            const container = document.getElementById('dm-range-rows');
            if (container) {
                container.innerHTML = ''; // clear the default empty row
                const rawRanges = Array.isArray(intentData.target_range)
                    ? intentData.target_range
                    : [intentData.target_range];
                rawRanges.forEach(r => {
                    const str = String(r);
                    const match = str.match(/(\d+)\s*[-~]\s*(\d+)/);
                    if (match) addDmRangeRow(match[1], match[2]);
                    else addDmRangeRow(str, '');
                });
            }
        }

        // Pre-fill baseline range
        if (intentData.baseline_range) {
            const specifyRadio = document.querySelector('input[name="dm-baseline-mode"][value="specify"]');
            if (specifyRadio) {
                specifyRadio.checked = true;
                document.getElementById('dm-baseline-custom')?.classList.remove('hidden');
            }
            const blStr = String(intentData.baseline_range);
            const blMatch = blStr.match(/(\d+)\s*[-~]\s*(\d+)/);
            if (blMatch) {
                const blStart = document.getElementById('dm-baseline-start');
                const blEnd = document.getElementById('dm-baseline-end');
                if (blStart) blStart.value = blMatch[1];
                if (blEnd) blEnd.value = blMatch[2];
            }
        }

        // Pre-select target params in the transfer list
        if (intentData.target_params && intentData.target_params.length > 0 && this.miningState) {
            intentData.target_params.forEach(p => {
                if (this.currentFileParams.includes(p)) {
                    this.miningState.y.add(p);
                }
            });
            this.renderMiningLists();
        }

        // Switch to Step 1 (range) to let user review
        switchDmStep(1);
    }

    confirmIntentAnalysis(skip = false) {
        // Legacy: no longer used separately, confirmDataMining handles it
        // But keep for safety in case anything still calls it
        const panel = document.getElementById('intent-confirm-panel');
        if (panel) panel.remove();

        if (skip) {
            const query = this._pendingIntentQuery || '開始分析';
            const taskType = this._pendingIntentTaskType || 'anomaly_detection';
            this.miningMetadata = {};
            this.elements.userInput.value = `[TASK:${taskType}] ${query}`;
            this.elements.userInput.style.height = 'auto';
            this.elements.userInput.style.height = this.elements.userInput.scrollHeight + 'px';
            this.sendMessage();
        }
    }

    confirmOptimization() {
        console.log('[DEBUG] confirmOptimization called');
        const targets = Array.from(this.miningState.y);
        console.log('[DEBUG] optimization targets:', targets);

        const start = document.getElementById('dm-range-start').value.trim();
        const end = document.getElementById('dm-range-end').value.trim();

        let query = '';
        let targetRange = null;

        if (start && end) {
            targetRange = `${start}-${end}`;
        } else if (start) {
            targetRange = `${start}-`;
        } else if (end) {
            targetRange = `-${end}`;
        }

        if (targets.length === 0) {
            query = `請進行全域參數最佳化分析，找出影響品質的關鍵可控參數，並給出最佳操作建議`;
        } else {
            query = `請針對 ${targets.join(', ')} 進行最佳化分析，找出哪些可控參數對其影響最大，以及最佳操作區間`;
        }

        if (targetRange) {
            query += `，分析區間為第 ${targetRange} 筆`;
        } else {
            query += `，分析全域數據`;
        }

        query += `。找出關鍵影響因子與最佳操作條件。`;

        this.miningMetadata = {
            suspect_params: targets.length > 0 ? targets : null,
            target_range: targetRange
        };

        this.elements.userInput.value = query;
        this.elements.userInput.style.height = 'auto';
        this.elements.userInput.style.height = this.elements.userInput.scrollHeight + 'px';
        this.elements.btnSend.disabled = false;
        this.sendMessage();

        closeMiningPanel();
    }

    // ========== Statistical Tool Methods ==========

    static STAT_TOOL_REGISTRY = {
        '資料清理': [
            { id: 'filter_dead_columns', name: '過濾死水欄位', desc: '移除標準差 ≈ 0 的常數欄位', params: [] },
        ],
        '異常偵測': [
            {
                id: 'find_anomalies', name: '異常偵測 (IF/Zscore)', desc: 'Isolation Forest 或 Z-score 整體異常偵測', params: [
                    { key: 'method', label: '方法', type: 'select', options: ['isolation_forest', 'zscore'], default: 'isolation_forest' },
                    { key: 'contamination', label: '異常比例', type: 'number', default: 0.05, min: 0.01, max: 0.5, step: 0.01 },
                ]
            },
            { id: 'detect_outliers_iqr', name: 'IQR 離群值偵測', desc: '用 IQR 方法找每個欄位的離群值', params: [] },
            {
                id: 'hotelling_t2', name: 'Hotelling T²', desc: '多變量異常偵測 (高維自動 PCA 降維)', params: [
                    { key: 'alpha', label: '顯著水準', type: 'number', default: 0.01, min: 0.001, max: 0.1, step: 0.005 },
                ]
            },
            { id: 't2_contribution', name: 'T² 貢獻分解', desc: '找出哪些原始參數導致 T² 超標', params: [] },
            {
                id: 'robust_zscore', name: 'Robust Z-score', desc: '用 MAD 找系統性偏移欄位', params: [
                    { key: 'threshold', label: 'Z-score 閾值', type: 'number', default: 3.0, min: 1.5, max: 5.0, step: 0.5 },
                ]
            },
            {
                id: 'classify_anomaly_type', name: '異常類型分類', desc: '將異常分類：Freeze/Spike/Drift/Oscillation/Level Shift', params: [
                    { key: 'target_col', label: '目標欄位', type: 'column', required: true },
                ]
            },
        ],
        '相關性分析': [
            {
                id: 'top_correlations', name: '相關性分析', desc: '找出相關性最高的欄位對', params: [
                    { key: 'target', label: '目標欄位 (選填)', type: 'column', required: false },
                    { key: 'min_abs_corr', label: '最低相關係數', type: 'number', default: 0.3, min: 0.1, max: 0.9, step: 0.1 },
                ]
            },
            {
                id: 'correlation_network', name: '相關性網路', desc: '找出 Hub 參數 (Degree + Betweenness Centrality)', params: [
                    { key: 'threshold', label: '相關性閾值', type: 'number', default: 0.5, min: 0.2, max: 0.9, step: 0.1 },
                ]
            },
            { id: 'collinearity_analysis', name: '共線性分析 (VIF)', desc: 'VIF + Condition Number + 高共線性群組', params: [] },
        ],
        '偏移偵測': [
            {
                id: 'segment_drift', name: '區間偏移偵測', desc: 'CUSUM 或 EWMA 偵測單一欄位偏移', params: [
                    { key: 'target_col', label: '目標欄位', type: 'column', required: true },
                    { key: 'method', label: '方法', type: 'select', options: ['cusum', 'ewma'], default: 'cusum' },
                ]
            },
            {
                id: 'scan_all_drift', name: '全域偏移掃描', desc: '對所有欄位做偏移掃描，回傳最嚴重 Top-N', params: [
                    { key: 'method', label: '方法', type: 'select', options: ['cusum', 'ewma'], default: 'cusum' },
                ]
            },
            {
                id: 'distribution_shift', name: '分佈偏移 (KS-test)', desc: '前後半段分佈偏移偵測', params: [
                    { key: 'target_col', label: '目標欄位', type: 'column', required: true },
                ]
            },
        ],
        '分組比較': [
            {
                id: 'compare_groups', name: '分組比較', desc: '比較兩組資料的差異，找出差異最大的欄位', params: [
                    { key: 'group_a_range', label: 'A 組 (起-迄)', type: 'text', placeholder: '例：1-50' },
                    { key: 'group_b_range', label: 'B 組 (起-迄)', type: 'text', placeholder: '例：51-100' },
                ]
            },
        ],
        '進階分析': [
            {
                id: 'frequency_analysis', name: '頻率分析 (FFT)', desc: '用 FFT 找主要頻率成分', params: [
                    { key: 'target_col', label: '目標欄位', type: 'column', required: true },
                ]
            },
            {
                id: 'residual_analysis', name: '殘差分析', desc: '線性回歸預測 target 後分析殘差', params: [
                    { key: 'target_col', label: '目標欄位', type: 'column', required: true },
                ]
            },
            {
                id: 'pca_analysis', name: 'PCA 降維', desc: '主成分分析 + 各 PC 的 loading', params: [
                    { key: 'n_components', label: '主成分數', type: 'number', default: 5, min: 2, max: 20, step: 1 },
                ]
            },
            {
                id: 'control_loop_assessment', name: '控制迴路評估', desc: 'Harris Index + 追蹤誤差評估', params: [
                    { key: 'target_col', label: '目標欄位 (PV)', type: 'column', required: true },
                ]
            },
            {
                id: 'operating_window', name: '操作窗口', desc: '根據好壞分組找最佳操作範圍', params: [
                    { key: 'target_col', label: '目標欄位', type: 'column', required: true },
                    { key: 'direction', label: '方向', type: 'select', options: ['maximize', 'minimize'], default: 'maximize' },
                ]
            },
            {
                id: 'feature_importance', name: '特徵重要性', desc: 'Random Forest 或 Mutual Info 排名', params: [
                    { key: 'target_col', label: '目標欄位', type: 'column', required: true },
                    { key: 'method', label: '方法', type: 'select', options: ['random_forest', 'mutual_info'], default: 'random_forest' },
                ]
            },
            {
                id: 'cross_correlation_lag', name: '交叉相關 (時間延遲)', desc: '找兩序列最佳延遲', params: [
                    { key: 'col_a', label: '欄位 A', type: 'column', required: true },
                    { key: 'col_b', label: '欄位 B', type: 'column', required: true },
                ]
            },
            {
                id: 'wavelet_analysis', name: '小波分析', desc: 'Morlet 小波分解多尺度結構', params: [
                    { key: 'target_col', label: '目標欄位', type: 'column', required: true },
                ]
            },
            {
                id: 'trend_prediction', name: '趨勢預測', desc: '線性回歸 + 信賴區間預測', params: [
                    { key: 'target_col', label: '目標欄位', type: 'column', required: true },
                    { key: 'forecast_horizon', label: '預測長度', type: 'number', default: 20, min: 5, max: 100, step: 5 },
                ]
            },
        ],
        '繪圖工具': [
            { id: 'plot_correlation_heatmap', name: '相關性熱圖', desc: '繪製 Top-N 子集的相關性熱圖', params: [] },
            {
                id: 'plot_scatter', name: '散佈圖', desc: '兩欄位的散佈圖', params: [
                    { key: 'x_col', label: 'X 軸欄位', type: 'column', required: true },
                    { key: 'y_col', label: 'Y 軸欄位', type: 'column', required: true },
                ]
            },
            {
                id: 'plot_trend', name: '趨勢圖', desc: '欄位趨勢圖 + 移動平均', params: [
                    { key: 'target_col', label: '目標欄位', type: 'column', required: true },
                ]
            },
            {
                id: 'plot_distribution_compare', name: '分佈對比圖', desc: '兩組的直方圖對比', params: [
                    { key: 'target_col', label: '目標欄位', type: 'column', required: true },
                    { key: 'group_a_range', label: 'A 組 (起-迄)', type: 'text', placeholder: '例：1-50' },
                    { key: 'group_b_range', label: 'B 組 (起-迄)', type: 'text', placeholder: '例：51-100' },
                ]
            },
        ],
    };

    openStatToolModal() {
        if (!this.currentFileParams || this.currentFileParams.length === 0) {
            alert('無法獲取參數列表，請確認檔案已正確加載。');
            return;
        }

        const modal = document.getElementById('stat-tool-modal');
        if (!modal) return;

        // Populate tool selector
        const select = document.getElementById('st-tool-select');
        if (!select) return;

        select.innerHTML = '<option value="" disabled selected>-- 請選擇工具 --</option>';
        const registry = IntelligentAnalysis.STAT_TOOL_REGISTRY;
        for (const [category, tools] of Object.entries(registry)) {
            const group = document.createElement('optgroup');
            group.label = category;
            tools.forEach(t => {
                const opt = document.createElement('option');
                opt.value = t.id;
                opt.textContent = t.name;
                group.appendChild(opt);
            });
            select.appendChild(group);
        }

        // Bind change event
        select.onchange = () => this.renderStatToolParams(select.value);

        // Reset
        document.getElementById('st-tool-desc').classList.add('hidden');
        document.getElementById('st-params-area').classList.add('hidden');
        document.getElementById('st-params-container').innerHTML = '';

        modal.classList.remove('hidden');
    }

    renderStatToolParams(toolId) {
        const descEl = document.getElementById('st-tool-desc');
        const paramsArea = document.getElementById('st-params-area');
        const container = document.getElementById('st-params-container');
        container.innerHTML = '';

        // Find tool in registry
        let tool = null;
        for (const tools of Object.values(IntelligentAnalysis.STAT_TOOL_REGISTRY)) {
            tool = tools.find(t => t.id === toolId);
            if (tool) break;
        }
        if (!tool) return;

        // Show description
        descEl.textContent = tool.desc;
        descEl.classList.remove('hidden');

        if (tool.params.length === 0) {
            paramsArea.classList.add('hidden');
            return;
        }

        paramsArea.classList.remove('hidden');

        tool.params.forEach(p => {
            const wrapper = document.createElement('div');
            wrapper.className = 'flex flex-col gap-1';

            const label = document.createElement('label');
            label.className = 'text-xs text-gray-600 font-medium';
            label.textContent = p.label + (p.required ? ' *' : '');
            wrapper.appendChild(label);

            if (p.type === 'column') {
                const sel = document.createElement('select');
                sel.id = `st-param-${p.key}`;
                sel.className = 'w-full border border-gray-300 rounded-lg py-2 px-3 text-sm focus:ring-2 focus:ring-purple-500 focus:border-purple-500';
                if (!p.required) {
                    const emptyOpt = document.createElement('option');
                    emptyOpt.value = '';
                    emptyOpt.textContent = '(不指定)';
                    sel.appendChild(emptyOpt);
                }
                this.currentFileParams.forEach(col => {
                    const opt = document.createElement('option');
                    opt.value = col;
                    opt.textContent = col;
                    sel.appendChild(opt);
                });
                wrapper.appendChild(sel);
            } else if (p.type === 'select') {
                const sel = document.createElement('select');
                sel.id = `st-param-${p.key}`;
                sel.className = 'w-full border border-gray-300 rounded-lg py-2 px-3 text-sm focus:ring-2 focus:ring-purple-500 focus:border-purple-500';
                p.options.forEach(o => {
                    const opt = document.createElement('option');
                    opt.value = o;
                    opt.textContent = o;
                    if (o === p.default) opt.selected = true;
                    sel.appendChild(opt);
                });
                wrapper.appendChild(sel);
            } else if (p.type === 'number') {
                const input = document.createElement('input');
                input.type = 'number';
                input.id = `st-param-${p.key}`;
                input.className = 'w-full border border-gray-300 rounded-lg py-2 px-3 text-sm focus:ring-2 focus:ring-purple-500 focus:border-purple-500';
                input.value = p.default ?? '';
                if (p.min !== undefined) input.min = p.min;
                if (p.max !== undefined) input.max = p.max;
                if (p.step !== undefined) input.step = p.step;
                wrapper.appendChild(input);
            } else {
                const input = document.createElement('input');
                input.type = 'text';
                input.id = `st-param-${p.key}`;
                input.className = 'w-full border border-gray-300 rounded-lg py-2 px-3 text-sm focus:ring-2 focus:ring-purple-500 focus:border-purple-500';
                if (p.placeholder) input.placeholder = p.placeholder;
                wrapper.appendChild(input);
            }

            container.appendChild(wrapper);
        });
    }

    confirmStatTool() {
        const select = document.getElementById('st-tool-select');
        const toolId = select?.value;
        if (!toolId) {
            alert('請先選擇工具');
            return;
        }

        // Find tool
        let tool = null;
        for (const tools of Object.values(IntelligentAnalysis.STAT_TOOL_REGISTRY)) {
            tool = tools.find(t => t.id === toolId);
            if (tool) break;
        }
        if (!tool) return;

        // Collect params
        const params = {};
        for (const p of tool.params) {
            const el = document.getElementById(`st-param-${p.key}`);
            const val = el?.value?.trim() ?? '';
            if (p.required && !val) {
                alert(`請填寫必要參數：${p.label}`);
                return;
            }
            if (val) {
                params[p.key] = p.type === 'number' ? parseFloat(val) : val;
            }
        }

        // Build [DIRECT_TOOL] message
        const paramStr = Object.keys(params).length > 0
            ? '(' + Object.entries(params).map(([k, v]) => `${k}=${typeof v === 'string' ? `"${v}"` : v}`).join(', ') + ')'
            : '()';

        const query = `[DIRECT_TOOL] ${tool.id}${paramStr}`;

        this.elements.userInput.value = query;
        this.elements.userInput.style.height = 'auto';
        this.elements.userInput.style.height = this.elements.userInput.scrollHeight + 'px';
        this.elements.btnSend.disabled = false;
        this.sendMessage();

        document.getElementById('stat-tool-modal').classList.add('hidden');
    }

    // ========== Session Management ==========


    async loadSessionList(autoLoadLatest = false) {
        try {
            const response = await fetch(`/api/analysis/sessions?user_id=${encodeURIComponent(this.sessionId)}`);
            if (!response.ok) throw new Error('Failed to load sessions');
            const data = await response.json();
            const sessions = data.sessions || [];
            this.renderSessionList(sessions);

            // 首次載入時自動切換到最近的聊天室
            if (autoLoadLatest && sessions.length > 0) {
                const latest = sessions[0]; // sessions 已按時間排序
                const fid = latest.file_id || '';
                const fname = latest.filename || '';
                if (fid && (fid !== (this.currentFileId || '') || this.elements.chatContainer.children.length === 0)) {
                    await this.switchSession(latest.session_id, fid, fname);
                }
            }
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
            const isActive = s.session_id === this.sessionId && (s.file_id || '') === (this.currentFileId || '') && (s.conversation_id || 'default') === (this.conversationId || 'default');
            const title = this._escapeHtml(s.title || '新對話');
            const count = s.message_count || 0;
            const timeStr = s.last_active
                ? new Date(s.last_active).toLocaleString('zh-TW', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
                : '';
            const activeIcon = isActive
                ? '<span class="inline-block w-2 h-2 rounded-full bg-blue-500 mr-1.5 flex-shrink-0" title="目前聊天室"></span>'
                : '';
            const fileId = s.file_id || '';
            const filename = s.filename ? this._escapeHtml(s.filename) : '';
            const convId = s.conversation_id || 'default';

            return `
                <div class="session-item group flex items-center gap-1.5 px-2 py-1.5 rounded-lg cursor-pointer transition-all
                    ${isActive ? 'bg-blue-50 border border-blue-200 ring-1 ring-blue-300' : 'bg-white border border-transparent hover:bg-gray-100 hover:border-gray-200'}"
                    data-session-id="${s.session_id}" data-file-id="${fileId}" data-filename="${filename}" data-conversation-id="${convId}">
                    <div class="flex-1 min-w-0 flex items-center">
                        ${activeIcon}
                        <div class="min-w-0 flex-1">
                            <div class="text-[13px] font-medium leading-snug line-clamp-2 ${isActive ? 'text-blue-700' : 'text-gray-800'}">
                                ${title}
                            </div>
                            <div class="text-[9px] text-gray-400 truncate mt-0.5">
                                ${count}條 ${timeStr ? '· ' + timeStr : ''}${filename ? ' · ' + filename : ''}
                            </div>
                        </div>
                    </div>
                    ${!isActive ? `
                    <button onclick="event.stopPropagation(); window.ia.deleteSession('${s.session_id}', '${fileId}')"
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
        // 在同一 Session 內建立新對話（新 conversationId，保持檔案存取權）
        this.conversationId = crypto.randomUUID().slice(0, 12);
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

        // 重新載入聊天室列表
        this.loadSessionList();
        console.log(`[Sessions] New conversation: ${this.conversationId} in session: ${this.sessionId}`);
    }

    async switchSession(sessionId, fileId = '', filename = '', conversationId = 'default') {

        // Guard: 分析進行中時警告用戶
        if (this.isLoading) {
            const confirmed = confirm('分析正在進行中，切換聊天室可能導致當前分析結果遺失。\n\n確定要切換嗎？');
            if (!confirmed) return;
            // 中斷當前分析
            this.stopGeneration();
        }

        // 1. 更新 Session 狀態
        this.sessionId = sessionId;
        this.currentFileId = fileId || null;
        this.currentFilename = filename || null;
        this.conversationId = conversationId || 'default';

        // 2. 清空聊天區（準備載入歷史）
        this.elements.chatContainer.innerHTML = '';
        if (this.elements.welcomeScreen) {
            this.elements.welcomeScreen.style.display = 'none';
        }

        // 3. 恢復檔案上下文（靜默呼叫 prepare API，不觸發 handleFileSelect）
        if (filename) {
            // 同步檔案選擇器（僅視覺更新，不觸發 change 事件）
            if (this.elements.fileSelect) {
                for (let i = 0; i < this.elements.fileSelect.options.length; i++) {
                    const optText = this.elements.fileSelect.options[i].text;
                    if (optText === filename) {
                        this.elements.fileSelect.selectedIndex = i;
                        break;
                    }
                }
            }
            // 呼叫 prepare API 恢復檔案摘要（已索引的檔案會直接回傳，不會重建）
            try {
                const res = await fetch('/api/analysis/prepare', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ filename: filename, session_id: this.sessionId, conversation_id: this.conversationId })
                });
                if (res.ok) {
                    const result = await res.json();
                    if (result.file_id) this.currentFileId = result.file_id;
                    const summary = result.summary || {};
                    this.currentFileParams = summary.parameters || [];
                    this.currentFileCategories = summary.categories || {};
                    if (this.elements.infoRows) this.elements.infoRows.textContent = summary.total_rows ? summary.total_rows.toLocaleString() : '-';
                    if (this.elements.infoCols) this.elements.infoCols.textContent = summary.total_columns || '-';
                    if (this.elements.infoStatus) this.elements.infoStatus.textContent = '已就緒';
                    if (this.elements.fileLoadingIndicator) this.elements.fileLoadingIndicator.classList.add('hidden');
                    if (this.elements.fileInfoPanel) this.elements.fileInfoPanel.classList.remove('hidden');
                    if (this.elements.userInput) this.elements.userInput.disabled = false;
                    // 恢復術語對應與資料描述
                    this.loadDataDescription(this.currentFileId);
                    this.checkMappingStatus();
                }
            } catch (e) {
                console.warn('[Sessions] 恢復檔案上下文失敗:', e);
            }
        }

        // 4. 載入聊天歷史
        await this._loadSessionHistory(this.sessionId, this.currentFileId || '', this.conversationId);

        // 5. 更新側欄 (高亮 active session)
        this.loadSessionList();
        console.log(`[Sessions] Switched to session: ${sessionId}, file: ${this.currentFileId}, filename: ${filename}`);
    }

    async _loadSessionHistory(sessionId, fileId = '', conversationId = 'default') {
        console.log(`[History] Loading history: sessionId=${sessionId}, fileId=${fileId}, conv=${conversationId}`);
        try {
            let url = `/api/analysis/sessions/${encodeURIComponent(sessionId)}/history?last_n=50`;
            if (fileId) url += `&file_id=${encodeURIComponent(fileId)}`;
            if (conversationId) url += `&conversation_id=${encodeURIComponent(conversationId)}`;
            console.log(`[History] Fetching: ${url}`);
            const response = await fetch(url);
            console.log(`[History] Response status: ${response.status}`);
            if (!response.ok) {
                console.warn(`[History] API returned ${response.status}`);
                return;
            }
            const data = await response.json();
            const messages = data.messages || [];
            console.log(`[History] Got ${messages.length} messages`);

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
                const contentHtml = isUser
                    ? this._escapeHtml(msg.content)
                    : (typeof marked !== 'undefined' ? marked.parse(msg.content || '') : this._escapeHtml(msg.content || ''));
                const row = document.createElement('div');
                row.className = `flex ${isUser ? 'justify-end' : 'justify-start'} mb-3`;
                row.innerHTML = `
                    <div class="${isUser
                        ? 'bg-blue-500 text-white rounded-2xl rounded-br-md px-4 py-2.5 max-w-[75%]'
                        : 'bg-white border border-gray-100 rounded-2xl rounded-bl-md px-4 py-2.5 max-w-[85%] shadow-sm'}">
                        <div class="${isUser ? 'text-sm whitespace-pre-wrap leading-relaxed' : 'text-sm leading-relaxed markdown-body'}">${contentHtml}</div>
                    </div>
                `;
                this.elements.chatContainer.appendChild(row);
            }
            this.scrollToBottom();
        } catch (err) {
            console.warn('[Sessions] Failed to load history:', err);
        }
    }

    async deleteSession(sessionId, fileId = '') {
        if (!confirm('確定要刪除此聊天室嗎？')) return;
        try {
            let url = `/api/analysis/sessions/${sessionId}`;
            if (fileId) url += `?file_id=${encodeURIComponent(fileId)}`;
            await fetch(url, { method: 'DELETE' });
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
window.addDmRangeRow = (startVal = '', endVal = '') => {
    const container = document.getElementById('dm-range-rows');
    if (!container) return;
    const row = document.createElement('div');
    row.className = 'dm-range-row flex items-center gap-2';
    row.innerHTML = `
        <input type="number" class="dm-range-start w-24 text-sm border border-gray-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-400" placeholder="起始" value="${startVal}">
        <span class="text-gray-400 text-sm">~</span>
        <input type="number" class="dm-range-end w-24 text-sm border border-gray-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-400" placeholder="結束" value="${endVal}">
        <button type="button" onclick="removeDmRangeRow(this)" class="text-gray-300 hover:text-red-500 transition-colors p-1" title="移除">
            <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
            </svg>
        </button>
    `;
    container.appendChild(row);
};
window.removeDmRangeRow = (btn) => {
    const row = btn.closest('.dm-range-row');
    if (row) row.remove();
};
window.openDataMiningModal = () => window.ia?.openDataMiningModal();
window.switchDmStep = (step) => {
    // Toggle content panels
    document.querySelectorAll('.dm-step-content').forEach(el => el.classList.add('hidden'));
    const target = document.getElementById(`dm-step-${step}`);
    if (target) target.classList.remove('hidden');
    // Toggle nav button styles
    document.querySelectorAll('.dm-step-btn').forEach(btn => {
        btn.className = 'dm-step-btn text-left px-3 py-3 rounded-lg transition-all text-gray-500 hover:bg-gray-100 border-l-[3px] border-transparent';
    });
    const activeBtn = document.getElementById(`dm-step-btn-${step}`);
    if (activeBtn) {
        activeBtn.className = 'dm-step-btn text-left px-3 py-3 rounded-lg transition-all text-blue-600 bg-white shadow-sm border-l-[3px] border-blue-500';
    }
};
window.closeMiningPanel = () => {
    const modal = document.getElementById('data-mining-modal');
    if (modal) modal.classList.add('hidden');
};
window.openStatToolModal = () => window.ia?.openStatToolModal();
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
