// ==========================================
// 圖表 AI 專家助手功能（完整專業版，與即時看板一致）
// ==========================================

// 全局變量
let chartChatMessages = [];
let chartSelectedFiles = [];
let chartPopupWindow = null; // 獨立視窗參照

// 切換圖表AI助手顯示/隱藏
function toggleChartAssistant() {
    const win = document.getElementById('chart-ai-assistant-window');
    const fab = document.getElementById('chart-assistant-trigger');
    const icon = document.getElementById('chart-fab-icon');

    const isOpen = win.classList.contains('active');

    if (!isOpen) {
        // 打開助手
        win.style.display = 'flex';
        setTimeout(() => {
            win.classList.add('active');
            fab.classList.add('active');
            if (icon) icon.innerText = '×';
        }, 10);
    } else {
        // 關閉助手
        win.classList.remove('active');
        fab.classList.remove('active');
        if (icon) icon.innerText = '📊';
        setTimeout(() => {
            if (!win.classList.contains('active')) {
                win.style.display = 'none';
            }
        }, 300);
    }
}

// 切換圖表助手寬度
function toggleChartExpand() {
    const win = document.getElementById('chart-ai-assistant-window');
    win.classList.toggle('expanded');
}



// 開啟獨立聊天視窗 (Pop-out)
function openChartChatPopup() {
    // 關閉內嵌視窗
    const win = document.getElementById('chart-ai-assistant-window');
    if (win.classList.contains('active')) toggleChartAssistant();

    const w = 450;
    const h = 600;
    const left = (screen.width / 2) - (w / 2);
    const top = (screen.height / 2) - (h / 2);

    chartPopupWindow = window.open(
        '/static/chart_chat_popup.html',
        'ChartAIChat',
        `width=${w},height=${h},top=${top},left=${left},resizable=yes,scrollbars=yes,status=no`
    );
}

// 註冊彈出視窗 (供 popup 呼叫)
window.registerPopup = function (popupWin) {
    chartPopupWindow = popupWin;
};

// 處理彈出視窗關閉 (供 popup 呼叫)
window.onPopupClose = function () {
    chartPopupWindow = null;
    // 自動打開內嵌視窗
    const win = document.getElementById('chart-ai-assistant-window');
    if (!win.classList.contains('active')) toggleChartAssistant();
};

// 處理彈出視窗文本訊息
window.handlePopupMessage = function (msg) {
    const input = document.getElementById('chart-chat-input');
    input.value = msg;
    // Files are already in `chartSelectedFiles` via handleChartPopupFileSelect or generic handling
    sendChartChatMessage();
};

// 處理彈出視窗檔案選擇 (Important New Function)
window.handleChartPopupFileSelect = function (popupInput) {
    // Using the file object from popup directly
    chartProcessFiles(popupInput.files);
    // Clear popup input
    popupInput.value = '';
};

// 處理彈出視窗拖拽檔案
window.chartProcessFilesPopup = function (fileList) {
    chartProcessFiles(fileList);
};

// 輔助函式：同步內容到 Popup
function syncToPopup(htmlContent, isUser) {
    const content = document.getElementById('chart-ai-report-content'); // Main window content source

    if (chartPopupWindow && !chartPopupWindow.closed && chartPopupWindow.document) {
        const popupContent = chartPopupWindow.document.getElementById('chart-ai-report-content');
        if (popupContent) {
            if (content.lastElementChild) {
                const clone = content.lastElementChild.cloneNode(true);
                popupContent.appendChild(clone);
                popupContent.scrollTop = popupContent.scrollHeight;

                // Canvas Sync Logic: Copy Image Data
                const originalCanvases = content.lastElementChild.querySelectorAll('canvas');
                const clonedCanvases = clone.querySelectorAll('canvas');
                originalCanvases.forEach((orig, index) => {
                    if (clonedCanvases[index]) {
                        const destCtx = clonedCanvases[index].getContext('2d');
                        destCtx.drawImage(orig, 0, 0);
                    }
                });
            }
        }
    }
}

// 輔助函式：同步預覽到 Popup
function syncPreviewToPopup() {
    const mainPreview = document.getElementById('chart-file-preview');
    if (chartPopupWindow && !chartPopupWindow.closed && chartPopupWindow.document) {
        const popupPreview = chartPopupWindow.document.getElementById('chart-file-preview');
        if (popupPreview) {
            popupPreview.innerHTML = mainPreview.innerHTML;
            popupPreview.style.display = mainPreview.style.display;
        }
    }
}

// 生成圖表分析報告（專業版）
async function generateChartAIReport() {
    const btn = document.getElementById('btn-chart-report');
    const content = document.getElementById('chart-ai-report-content');
    btn.disabled = true;
    btn.innerText = '⏳ 專家分析中...';

    try {
        const response = await fetch(`/api/chart_ai/report?session_id=${SESSION_ID}`);
        const data = await response.json();
        const reportText = data.report || 'AI 未能返回數據。';

        chartChatMessages = [
            { role: 'user', content: '請根據最近的圖表分析記錄提供診斷報告。' },
            { role: 'assistant', content: reportText }
        ];

        content.innerHTML = `<div class="ai-bubble chat-bubble">${marked.parse(reportText)}</div>`;
        setTimeout(() => { content.scrollTop = content.scrollHeight; }, 100);

        // Sync Initial Report
        if (chartPopupWindow && !chartPopupWindow.closed) {
            const popupContent = chartPopupWindow.document.getElementById('chart-ai-report-content');
            if (popupContent) {
                popupContent.innerHTML = content.innerHTML;
                popupContent.scrollTop = popupContent.scrollHeight;
            }
        }
    } catch (err) {
        const errBubble = document.createElement('div');
        errBubble.className = 'ai-bubble chat-bubble';
        errBubble.style.color = '#ef4444';
        errBubble.innerHTML = `❌ 調用失敗。`;
        content.appendChild(errBubble);
    } finally {
        btn.disabled = false;
        btn.innerText = '✨ 生成報告';
    }
}

// 發送圖表對話訊息（專業版，完整檔案處理）
async function sendChartChatMessage() {
    const input = document.getElementById('chart-chat-input');
    const content = document.getElementById('chart-ai-report-content');
    const text = input.value.trim();
    if (!text && chartSelectedFiles.length === 0) return;

    // 1. 處理檔案與使用者訊息
    let userContent = text;
    const images = chartSelectedFiles.filter(f => f.type === 'image').map(f => f.data);
    const texts = chartSelectedFiles.filter(f => f.type === 'text');

    if (texts.length > 0) {
        userContent += "\n\n【附件文件內容】:";
        texts.forEach(f => {
            userContent += `\n--- 檔案: ${f.name} ---\n${f.data}\n`;
        });
    }

    input.value = '';
    input.value = '';
    document.getElementById('chart-file-preview').innerHTML = '';
    document.getElementById('chart-file-preview').style.display = 'none'; // Ensure hide
    syncPreviewToPopup(); // Clear popup preview too

    const msgObj = { role: 'user', content: userContent };
    if (images.length > 0) msgObj.images = images;

    chartChatMessages.push(msgObj);

    const userBubble = document.createElement('div');
    userBubble.className = 'user-bubble chat-bubble';
    let bubbleHtml = `${text || '<i>發送附件...</i>'}`;
    if (chartSelectedFiles.length > 0) {
        bubbleHtml += `<div class="bubble-attachments">`;
        chartSelectedFiles.forEach(f => {
            if (f.type === 'image') {
                bubbleHtml += `<img src="data:image/png;base64,${f.data}" class="bubble-attach-img" title="${f.name}">`;
            } else {
                bubbleHtml += `<div class="bubble-attach-file" title="${f.name}">📄</div>`;
            }
        });
        bubbleHtml += `</div>`;
    }
    userBubble.innerHTML = bubbleHtml;
    userBubble.innerHTML = bubbleHtml;
    content.appendChild(userBubble);

    syncToPopup(null, true); // Sync User Message

    while (content.children.length > 50) content.removeChild(content.firstChild);
    content.scrollTop = content.scrollHeight;

    chartSelectedFiles = []; // 清空已選擇檔案

    const thinkingId = 'thinking-' + Date.now();
    const thinkingBubble = document.createElement('div');
    thinkingBubble.id = thinkingId;
    thinkingBubble.className = 'ai-bubble chat-bubble';
    thinkingBubble.innerHTML = `<i>AI 專家正在思考中...</i>`;
    thinkingBubble.innerHTML = `<i>AI 專家正在思考中...</i>`;
    content.appendChild(thinkingBubble);
    syncToPopup(null, false); // Sync Thinking
    content.scrollTop = content.scrollHeight;

    try {
        if (chartChatMessages.length > 10) chartChatMessages = chartChatMessages.slice(-10);

        const response = await fetch('/api/chart_ai/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ messages: chartChatMessages, session_id: SESSION_ID })
        });
        const data = await response.json();
        const loader = document.getElementById(thinkingId);
        if (loader) loader.remove();

        // Remove loader from popup too
        if (chartPopupWindow && !chartPopupWindow.closed) {
            const pLoader = chartPopupWindow.document.getElementById(thinkingId);
            if (pLoader) pLoader.remove();
        }

        const reply = data.reply;
        if (reply) {
            chartChatMessages.push({ role: 'assistant', content: reply });

            const bubble = document.createElement('div');
            bubble.className = 'ai-bubble chat-bubble';
            bubble.innerHTML = marked.parse(reply);
            bubble.innerHTML = marked.parse(reply);
            content.appendChild(bubble);

            syncToPopup(null, false); // Sync AI Reply

            content.scrollTop = content.scrollHeight;
        }
    } catch (err) {
        const loader = document.getElementById(thinkingId);
        if (loader) loader.remove();

        const errBubble = document.createElement('div');
        errBubble.className = 'ai-bubble chat-bubble';
        errBubble.style.color = '#ef4444';
        errBubble.innerHTML = `❌ 調用失敗: ${err.message}`;
        errBubble.innerHTML = `❌ 調用失敗: ${err.message}`;
        content.appendChild(errBubble);
        syncToPopup(null, false);
    }
}

// 處理Enter鍵發送
function handleChartChatKey(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendChartChatMessage();
    }
}

// Global ESC Handler for Internal Chat Window
document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') {
        const win = document.getElementById('chart-ai-assistant-window');
        // Only close if it is currently active (open)
        if (win && win.classList.contains('active')) {
            toggleChartAssistant();
        }
    }
});

// 處理圖表檔案選擇（專業版）
function handleChartFileSelect(input) {
    chartProcessFiles(input.files);
    input.value = ''; // 重設以支援重複選取
}

// 處理多個檔案（專業版，與即時看板一致）
function chartProcessFiles(files) {
    const preview = document.getElementById('chart-file-preview');

    // 確保預覽區域可見
    if (preview) {
        preview.style.display = 'flex';
    }

    Array.from(files).forEach(file => {
        const reader = new FileReader();
        const item = document.createElement('div');
        item.className = 'preview-item';

        if (file.type.startsWith('image/')) {
            reader.onload = (e) => {
                item.innerHTML = `<img src="${e.target.result}"><div class="preview-remove" onclick="chartRemoveFile('${file.name}')">×</div>`;
                chartSelectedFiles.push({ name: file.name, type: 'image', data: e.target.result.split(',')[1] });
                syncPreviewToPopup();
            };
            reader.readAsDataURL(file);
        } else {
            reader.onload = (e) => {
                item.innerHTML = `<span>📄</span><div class="preview-remove" onclick="chartRemoveFile('${file.name}')">×</div>`;
                chartSelectedFiles.push({ name: file.name, type: 'text', data: e.target.result });
                syncPreviewToPopup();
            };
            reader.readAsText(file);
        }
        preview.appendChild(item);
    });
}

// 移除檔案
function chartRemoveFile(filename) {
    chartSelectedFiles = chartSelectedFiles.filter(f => f.name !== filename);
    const preview = document.getElementById('chart-file-preview');
    const items = preview.querySelectorAll('.preview-item');
    items.forEach(item => {
        if (item.textContent.includes(filename) || item.querySelector('img[title="' + filename + '"]')) {
            item.remove();
        }
    });

    // 如果沒有檔案了，隱藏preview
    if (chartSelectedFiles.length === 0) {
        preview.style.display = 'none';
    }
    syncPreviewToPopup(); // Sync removals
}

// 更新圖表分析數據（當用戶繪製圖表時調用）
async function updateChartAnalysisData(chartConfig) {
    if (!chartConfig) return;

    // 已停用歷史記錄儲存
    /*
    try {
        await fetch('/api/chart_ai/update_data', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: SESSION_ID,
                chart_type: chartConfig.type,
                x_axis: chartConfig.x_axis,
                y_axis: chartConfig.y_axis,
                y2_axis: chartConfig.y2_axis,
                data_summary: chartConfig.data_summary || {}
            })
        });
    } catch (error) {
        console.error('Failed to update chart analysis data:', error);
    }
    */
}

// 視圖切換邏輯已整合至 ui_core.js
// const originalSwitchView = switchView;
// switchView = function (viewName) {
//     originalSwitchView(viewName);
//     // Logic moved to ui_core.js
// };
