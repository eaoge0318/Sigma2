/* chat_manager.js - Refactored */
import { DOM } from './utils.js';
import { SESSION_ID } from './session.js';
import { toggleAssistant } from './ui_core.js';

let dashboardPopupWindow = null;
let chatMessages = [];
let selectedFiles = [];

export function handleChatKey(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendChatMessage();
    }
}

export function handleFileSelect(input) {
    processFiles(input.files);
    input.value = "";
}

export function processFiles(files) {
    const preview = document.getElementById('file-preview');
    if (files.length > 0) preview.style.display = 'flex';

    Array.from(files).forEach(file => {
        const reader = new FileReader();
        const item = document.createElement('div');
        item.className = 'preview-item';

        if (file.type.startsWith('image/')) {
            reader.onload = (e) => {
                item.innerHTML = `<img src="${e.target.result}"><div class="preview-remove" onclick="removeFile('${file.name}')">×</div>`;
                selectedFiles.push({ name: file.name, type: 'image', data: e.target.result.split(',')[1] });
            };
            reader.readAsDataURL(file);
        } else {
            reader.onload = (e) => {
                item.innerHTML = `<span>📄</span><div class="preview-remove" onclick="removeFile('${file.name}')">×</div>`;
                selectedFiles.push({ name: file.name, type: 'text', data: e.target.result });
            };
            reader.readAsText(file);
        }
        preview.appendChild(item);
    });
}

export function clearHistory() {
    chatMessages = [];
    DOM.setHTML('ai-report-content', '');
    selectedFiles = [];
    const preview = document.getElementById('file-preview');
    if (preview) {
        preview.innerHTML = '';
        preview.style.display = 'none';
    }
}

export function toggleExpand() {
    const win = document.getElementById('ai-assistant-window');
    win.classList.toggle('expanded');
}

export function openDashboardChatPopup() {
    const win = document.getElementById('ai-assistant-window');
    if (win && win.classList.contains('active')) toggleAssistant();

    const w = 450;
    const h = 600;
    const left = (screen.width / 2) - (w / 2);
    const top = (screen.height / 2) - (h / 2);

    dashboardPopupWindow = window.open(
        '/static/dashboard_ai_popup.html',
        'DashboardAIChat',
        `width=${w},height=${h},top=${top},left=${left},resizable=yes,scrollbars=yes,status=no`
    );
    window.dashboardPopupWindow = dashboardPopupWindow;
    console.log("Popup opened and assigned to window.dashboardPopupWindow");
}

export function getDashboardPopupWindow() {
    return dashboardPopupWindow;
}

export function removeFile(name) {
    selectedFiles = selectedFiles.filter(f => f.name !== name);
    const preview = document.getElementById('file-preview');
    preview.innerHTML = "";
    selectedFiles.forEach(f => {
        const item = document.createElement('div');
        item.className = 'preview-item';
        item.innerHTML = f.type === 'image' ? `<img src="data:image/png;base64,${f.data}">` : `<span>📄</span>`;
        item.innerHTML += `<div class="preview-remove" onclick="removeFile('${f.name}')">×</div>`;
        preview.appendChild(item);
    });

    if (selectedFiles.length === 0) {
        preview.style.display = 'none';
    }
}

export async function generateAIReport() {
    const btn = document.getElementById('btn-report');
    const content = document.getElementById('ai-report-content');
    btn.disabled = true; btn.innerText = "⏳ 專家分析中...(後台)";

    try {
        const response = await fetch(`/api/ai/report?session_id=${SESSION_ID}`);
        const data = await response.json();

        let reportText = "";

        if (data.job_id) {
            if (typeof window.pollAIResult === 'function') {
                const result = await window.pollAIResult(data.job_id, 'report');
                reportText = result.report;
            } else {
                console.warn("window.pollAIResult not found, falling back to data.report if available");
                reportText = data.report || "AI Polling unavailable";
            }
        } else {
            reportText = data.report;
        }

        reportText = reportText || "AI 未能返回數據。";

        chatMessages = [
            { role: "user", content: "請根據最近的製程數據提供診斷報告。" },
            { role: "assistant", content: reportText }
        ];

        content.innerHTML = `<div class="ai-bubble chat-bubble">${marked.parse(reportText)}</div>`;
        setTimeout(() => { content.scrollTop = content.scrollHeight; }, 100);

        if (window.dashboardPopupWindow && !window.dashboardPopupWindow.closed) {
            const popupContent = window.dashboardPopupWindow.document.getElementById('ai-report-content');
            if (popupContent) {
                popupContent.innerHTML = content.innerHTML;
                popupContent.scrollTop = popupContent.scrollHeight;
            }
        }
    } catch (err) {
        const message = `❌ 調用失敗：${err.message || '未知錯誤'}`;
        const errBubble = document.createElement('div');
        errBubble.className = "ai-bubble chat-bubble";
        errBubble.style.color = "#ef4444";
        errBubble.innerHTML = message;
        content.appendChild(errBubble);

        if (window.dashboardPopupWindow && !window.dashboardPopupWindow.closed) {
            const popupContent = window.dashboardPopupWindow.document.getElementById('ai-report-content');
            if (popupContent) {
                const pBubble = document.createElement('div');
                pBubble.className = "ai-bubble chat-bubble";
                pBubble.style.color = "#ef4444";
                pBubble.innerHTML = message;
                popupContent.appendChild(pBubble);
                popupContent.scrollTop = popupContent.scrollHeight;
            }
        }
    } finally {
        btn.disabled = false;
        btn.innerText = "✨ 生成核心對稱報告";
    }
}



export async function sendChatMessage() {
    const input = document.getElementById('chat-input');
    const content = document.getElementById('ai-report-content');
    const text = input.value.trim();
    if (!text && selectedFiles.length === 0) return;

    // 1. 處理檔案與使用者訊息
    let userContent = text;
    const images = selectedFiles.filter(f => f.type === 'image').map(f => f.data);
    const texts = selectedFiles.filter(f => f.type === 'text');

    if (texts.length > 0) {
        userContent += "\n\n【附件文件內容】:";
        texts.forEach(f => {
            userContent += `\n--- 檔案: ${f.name} ---\n${f.data}\n`;
        });
    }

    input.value = "";
    document.getElementById('file-preview').innerHTML = "";
    document.getElementById('file-preview').style.display = 'none';

    const msgObj = { role: "user", content: userContent };
    if (images.length > 0) msgObj.images = images;

    chatMessages.push(msgObj);

    const userBubble = document.createElement('div');
    userBubble.className = "user-bubble chat-bubble";
    let bubbleHtml = `${text || "<i>發送附件...</i>"}`;
    if (selectedFiles.length > 0) {
        bubbleHtml += `<div class="bubble-attachments">`;
        selectedFiles.forEach(f => {
            if (f.type === 'image') {
                bubbleHtml += `<img src="data:image/png;base64,${f.data}" class="bubble-attach-img" title="${f.name}">`;
            } else {
                bubbleHtml += `<div class="bubble-attach-file" title="${f.name}">📄</div>`;
            }
        });
        bubbleHtml += `</div>`;
    }
    userBubble.innerHTML = bubbleHtml;
    content.appendChild(userBubble);
    syncDashboardToPopup(null, true);

    while (content.children.length > 50) content.removeChild(content.firstChild);
    content.scrollTop = content.scrollHeight;

    selectedFiles = [];

    const thinkingId = 'thinking-' + Date.now();
    const thinkingBubble = document.createElement('div');
    thinkingBubble.id = thinkingId;
    thinkingBubble.className = "ai-bubble chat-bubble";
    thinkingBubble.innerHTML = `<i>AI 專家正在思考中...</i>`;
    content.appendChild(thinkingBubble);
    syncDashboardToPopup(null, false);
    content.scrollTop = content.scrollHeight;

    try {
        if (chatMessages.length > 10) chatMessages = chatMessages.slice(-10);

        const response = await fetch('/api/ai/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ messages: chatMessages, session_id: SESSION_ID })
        });
        const data = await response.json();

        let reply = "";

        if (data.job_id) {
            if (typeof window.pollAIResult === 'function') {
                const result = await window.pollAIResult(data.job_id, 'chat');
                reply = result.reply;
            } else {
                reply = data.reply || "Polling unavailable";
            }
        } else {
            reply = data.reply;
        }

        const loader = document.getElementById(thinkingId);
        if (loader) loader.remove();

        if (window.dashboardPopupWindow && !window.dashboardPopupWindow.closed) {
            const pLoader = window.dashboardPopupWindow.document.getElementById(thinkingId);
            if (pLoader) pLoader.remove();
        } else if (dashboardPopupWindow && !dashboardPopupWindow.closed) {
            const pLoader = dashboardPopupWindow.document.getElementById(thinkingId);
            if (pLoader) pLoader.remove();
        }

        if (reply) {
            chatMessages.push({ role: "assistant", content: reply });

            // 1. 建立訊息泡泡容器
            const bubble = document.createElement('div');
            bubble.className = "ai-bubble chat-bubble";
            bubble.innerHTML = marked.parse(reply);
            content.appendChild(bubble);

            // 2. 解析並渲染嵌入式圖表
            const codeBlocks = bubble.querySelectorAll('pre code');
            const renderPromises = [];
            codeBlocks.forEach(block => {
                try {
                    let config;
                    try {
                        let jsonStr = block.innerText.trim();
                        if (jsonStr.includes('&quot;')) jsonStr = jsonStr.replace(/&quot;/g, '"');
                        config = JSON.parse(jsonStr);
                    } catch (e) { return; }

                    if (config.type === 'chart') {
                        // 隱藏原始 JSON
                        block.parentElement.style.display = 'none';

                        // 創建圖表容器
                        const chartDiv = document.createElement('div');
                        chartDiv.style.margin = "15px 0";
                        chartDiv.style.background = "#fff";
                        chartDiv.style.borderRadius = "8px";
                        chartDiv.style.padding = "12px";
                        chartDiv.style.border = "1px solid #e2e8f0";
                        chartDiv.style.minHeight = "210px";
                        chartDiv.style.boxShadow = "0 2px 4px rgba(0,0,0,0.05)";
                        chartDiv.innerHTML = `<canvas height="200"></canvas>`;
                        // Store config for popup sync
                        chartDiv.dataset.chartConfig = JSON.stringify(config);
                        block.parentElement.after(chartDiv);

                        const p = new Promise(resolve => {
                            setTimeout(() => {
                                const ctx = chartDiv.querySelector('canvas').getContext('2d');
                                if (!config.datasets || !config.datasets[0]) {
                                    resolve();
                                    return;
                                }

                                let chartType = config.chart_type || 'line';
                                let chartData = { datasets: [] };

                                const hasTwoDatasets = config.datasets && config.datasets.length >= 2;
                                const missingLabels = !config.labels || config.labels.length === 0;
                                const isExplicitLine = config.chart_type === 'line';
                                const autoDetectScatter = !config.chart_type && (hasTwoDatasets && missingLabels);

                                if (chartType === 'scatter' || (!isExplicitLine && autoDetectScatter)) {
                                    chartType = 'scatter';
                                    const d1 = config.datasets[0].data;
                                    const d2 = config.datasets[1].data;
                                    const len = Math.min(d1.length, d2.length);
                                    const scatterPoints = [];
                                    for (let i = 0; i < len; i++) {
                                        scatterPoints.push({ x: Number(d1[i]), y: Number(d2[i]) });
                                    }
                                    chartData.datasets = [{
                                        label: `${config.datasets[0].label} vs ${config.datasets[1].label}`,
                                        data: scatterPoints,
                                        borderColor: '#7e22ce',
                                        backgroundColor: 'rgba(126, 34, 206, 0.5)',
                                        pointRadius: 6,
                                        pointHoverRadius: 8
                                    }];
                                } else {
                                    chartType = 'line';
                                    let labels = config.labels || [];
                                    if (labels.length === 0 && config.datasets[0].data) {
                                        const dataLen = config.datasets[0].data.length;
                                        for (let i = dataLen - 1; i >= 0; i--) labels.push(`T-${i}`);
                                    }
                                    chartData.labels = labels;

                                    if (config.datasets.length > 0) {
                                        const getMag = (arr) => {
                                            const valid = arr.filter(n => typeof n === 'number' && !isNaN(n) && n !== 0);
                                            if (valid.length === 0) return 0;
                                            const avg = valid.reduce((a, b) => a + Math.abs(b), 0) / valid.length;
                                            return avg === 0 ? 0 : Math.log10(avg);
                                        };

                                        const baseMag = getMag(config.datasets[0].data || []);

                                        chartData.datasets = config.datasets.map((ds, idx) => {
                                            if (idx === 0) {
                                                return {
                                                    ...ds,
                                                    yAxisID: 'y',
                                                    borderColor: '#7e22ce',
                                                    backgroundColor: 'rgba(126, 34, 206, 0.1)',
                                                    tension: 0.35, fill: true, pointRadius: 3
                                                };
                                            }

                                            const myMag = getMag(ds.data || []);
                                            const diff = Math.abs(myMag - baseMag);
                                            const useLeft = (diff < 1.0) || (baseMag === 0 && myMag === 0);
                                            const axisID = useLeft ? 'y' : 'y1';
                                            const colors = ['#38bdf8', '#ef4444', '#f59e0b', '#10b981'];
                                            const color = colors[(idx - 1) % colors.length];

                                            return {
                                                ...ds,
                                                yAxisID: axisID,
                                                borderColor: color,
                                                backgroundColor: color.replace(')', ', 0.1)').replace('rgb', 'rgba'),
                                                tension: 0.35, fill: false, pointRadius: 3
                                            };
                                        });
                                    }
                                }

                                const chartOptions = {
                                    responsive: true,
                                    maintainAspectRatio: false,
                                    animation: {
                                        onComplete: () => {
                                            resolve();
                                        }
                                    },
                                    plugins: {
                                        legend: { labels: { boxWidth: 12, font: { size: 10 } } },
                                        title: { display: true, text: config.title || '製程數據分析', font: { weight: 'bold' } }
                                    },
                                    scales: {
                                        y: { type: 'linear', display: true, position: 'left', beginAtZero: false },
                                        y1: { type: 'linear', display: chartData.datasets.length > 1 && chartType !== 'scatter', position: 'right', grid: { drawOnChartArea: false }, beginAtZero: false }
                                    }
                                };

                                if (chartType === 'scatter') {
                                    chartOptions.scales = {
                                        x: { type: 'linear', position: 'bottom', title: { display: true, text: config.datasets[0].label, font: { weight: 'bold' } }, beginAtZero: false },
                                        y: { type: 'linear', title: { display: true, text: config.datasets[1].label, font: { weight: 'bold' } }, beginAtZero: false }
                                    };
                                    delete chartOptions.scales.y1;
                                }

                                const finalChartConfig = {
                                    type: chartType,
                                    data: chartData,
                                    options: chartOptions
                                };

                                new Chart(ctx, finalChartConfig);
                                chartDiv.dataset.processedConfig = JSON.stringify(finalChartConfig);

                            }, 100);
                        });
                        renderPromises.push(p);
                    }
                } catch (e) {
                    console.warn("Chart parse error:", e);
                    const errDiv = document.createElement('div');
                    errDiv.style.color = '#ef4444';
                    errDiv.style.fontSize = '12px';
                    errDiv.style.marginTop = '5px';
                    errDiv.innerText = "❌ 圖表數據解析異常 (JSON Error)";
                    block.parentElement.after(errDiv);
                }
            });

            if (renderPromises.length > 0) {
                await Promise.all(renderPromises);
            }
            syncDashboardToPopup(null, false);
        }
        while (content.children.length > 50) content.removeChild(content.firstChild);
        content.scrollTop = content.scrollHeight;
    } catch (err) {
        const message = `❌ 對話失敗：${err.message || '未知錯誤'}`;
        const loader = document.getElementById(thinkingId);
        if (loader) loader.innerHTML = message;

        if (window.dashboardPopupWindow && !window.dashboardPopupWindow.closed) {
            const pLoader = window.dashboardPopupWindow.document.getElementById(thinkingId);
            if (pLoader) pLoader.innerHTML = message;
        } else if (dashboardPopupWindow && !dashboardPopupWindow.closed) {
            const pLoader = dashboardPopupWindow.document.getElementById(thinkingId);
            if (pLoader) pLoader.innerHTML = message;
        }
    }
}

function syncDashboardToPopup(htmlContent, isUser) {
    let popup = dashboardPopupWindow;
    if (!popup && window.dashboardPopupWindow) {
        popup = window.dashboardPopupWindow;
        dashboardPopupWindow = popup;
    }

    if (!popup || popup.closed || !popup.document) {
        return;
    }

    requestAnimationFrame(() => {
        setTimeout(() => {
            try {
                const content = document.getElementById('ai-report-content');
                const popupContent = popup.document.getElementById('ai-report-content');

                if (!popupContent || !content.lastElementChild) return;

                const clone = content.lastElementChild.cloneNode(true);
                popupContent.appendChild(clone);
                popupContent.scrollTop = popupContent.scrollHeight;

                const clonedChartDivs = clone.querySelectorAll('div[data-processed-config]');
                clonedChartDivs.forEach(div => {
                    requestAnimationFrame(() => {
                        try {
                            const fullConfig = JSON.parse(div.dataset.processedConfig);
                            const canvas = div.querySelector('canvas');
                            if (canvas && fullConfig) {
                                if (!fullConfig.options) fullConfig.options = {};
                                fullConfig.options.animation = { duration: 0 };
                                new Chart(canvas.getContext('2d'), fullConfig);
                            }
                        } catch (e) { console.error("Popup chart render failed", e); }
                    });
                });

                const originalCanvases = content.lastElementChild.querySelectorAll('canvas');
                const clonedCanvases = clone.querySelectorAll('canvas');
                originalCanvases.forEach((orig, index) => {
                    requestAnimationFrame(() => {
                        const parent = clonedCanvases[index]?.closest('div[data-processed-config]');
                        if (!parent && clonedCanvases[index]) {
                            const destCtx = clonedCanvases[index].getContext('2d');
                            destCtx.drawImage(orig, 0, 0);
                        }
                    });
                });
            } catch (e) {
                console.warn('Popup sync failed (non-critical):', e);
            }
        }, 0);
    });
}

export function receivePopupMessage(msg) {
    const content = document.getElementById('ai-report-content');
    if (!content) return;

    // Prevent duplicate user messages (simple check)
    if (msg.role === 'user') {
        const last = chatMessages[chatMessages.length - 1];
        if (last && last.role === 'user' && last.content === msg.content) {
            // Already added?
        } else {
            chatMessages.push({ role: "user", content: msg.content });
        }
    } else {
        chatMessages.push({ role: "assistant", content: msg.content });
    }

    const bubble = document.createElement('div');
    bubble.className = msg.role === 'user' ? "user-bubble chat-bubble" : "ai-bubble chat-bubble";

    if (msg.role === 'user') {
        bubble.innerHTML = msg.content;
    } else {
        bubble.innerHTML = marked.parse(msg.content);
    }

    content.appendChild(bubble);
    content.scrollTop = content.scrollHeight;

    if (msg.role === 'assistant') {
        const codeBlocks = bubble.querySelectorAll('pre code');
        codeBlocks.forEach(block => {
            try {
                let jsonStr = block.innerText.trim();
                if (jsonStr.includes('&quot;')) jsonStr = jsonStr.replace(/&quot;/g, '"');
                const config = JSON.parse(jsonStr);

                if (config.type === 'chart') {
                    block.parentElement.style.display = 'none';
                    const chartDiv = document.createElement('div');
                    chartDiv.style.margin = "15px 0";
                    chartDiv.style.background = "#fff";
                    chartDiv.style.borderRadius = "8px";
                    chartDiv.style.padding = "12px";
                    chartDiv.style.border = "1px solid #e2e8f0";
                    chartDiv.style.minHeight = "210px";
                    chartDiv.innerHTML = `<canvas height="200"></canvas>`;
                    block.parentElement.after(chartDiv);

                    setTimeout(() => {
                        try {
                            const ctx = chartDiv.querySelector('canvas').getContext('2d');
                            if (!config.datasets || !config.datasets[0]) return;

                            let chartType = config.chart_type || 'line';
                            let chartData = { datasets: [] };

                            const hasTwoDatasets = config.datasets && config.datasets.length >= 2;
                            const missingLabels = !config.labels || config.labels.length === 0;
                            const isExplicitLine = config.chart_type === 'line';
                            const autoDetectScatter = !config.chart_type && (hasTwoDatasets && missingLabels);

                            if (chartType === 'scatter' || (!isExplicitLine && autoDetectScatter)) {
                                chartType = 'scatter';
                                const d1 = config.datasets[0].data;
                                const d2 = config.datasets[1].data;
                                const len = Math.min(d1.length, d2.length);
                                const scatterPoints = [];
                                for (let i = 0; i < len; i++) {
                                    scatterPoints.push({ x: Number(d1[i]), y: Number(d2[i]) });
                                }
                                chartData.datasets = [{
                                    label: `${config.datasets[0].label} vs ${config.datasets[1].label}`,
                                    data: scatterPoints,
                                    borderColor: '#7e22ce',
                                    backgroundColor: 'rgba(100, 100, 100, 0.5)',
                                    pointRadius: 5
                                }];

                                if (!config.options) config.options = {};
                                if (!config.options.scales) config.options.scales = {};
                                config.options.scales.x = { type: 'linear', position: 'bottom', title: { display: true, text: config.datasets[0].label } };

                            } else {
                                chartType = 'line';
                                let labels = config.labels || [];
                                if (labels.length === 0 && config.datasets[0].data) {
                                    const dataLen = config.datasets[0].data.length;
                                    for (let i = dataLen - 1; i >= 0; i--) labels.push(`T-${i}`);
                                }
                                chartData.labels = labels;

                                if (config.datasets.length > 0) {
                                    const getMag = (arr) => {
                                        const valid = arr.filter(n => typeof n === 'number' && !isNaN(n) && n !== 0);
                                        if (valid.length === 0) return 0;
                                        const avg = valid.reduce((a, b) => a + Math.abs(b), 0) / valid.length;
                                        return avg === 0 ? 0 : Math.log10(avg);
                                    };

                                    const baseMag = getMag(config.datasets[0].data || []);

                                    chartData.datasets = config.datasets.map((ds, idx) => {
                                        if (idx === 0) {
                                            return {
                                                ...ds,
                                                yAxisID: 'y',
                                                borderColor: '#7e22ce',
                                                backgroundColor: 'rgba(126, 34, 206, 0.1)',
                                                tension: 0.35, fill: true, pointRadius: 3
                                            };
                                        }

                                        const myMag = getMag(ds.data || []);
                                        const diff = Math.abs(myMag - baseMag);
                                        const useLeft = (diff < 1.0) || (baseMag === 0 && myMag === 0);
                                        const axisID = useLeft ? 'y' : 'y1';
                                        const colors = ['#38bdf8', '#ef4444', '#f59e0b', '#10b981'];
                                        const color = colors[(idx - 1) % colors.length];

                                        return {
                                            ...ds,
                                            yAxisID: axisID,
                                            borderColor: color,
                                            backgroundColor: color.replace(')', ', 0.1)').replace('rgb', 'rgba'),
                                            tension: 0.35,
                                            pointRadius: 3,
                                            borderDash: axisID === 'y1' ? [5, 5] : []
                                        };
                                    });

                                    const hasY1 = chartData.datasets.some(d => d.yAxisID === 'y1');
                                    if (!config.options) config.options = {};
                                    if (!config.options.scales) config.options.scales = {};

                                    config.options.scales.y = {
                                        type: 'linear', display: true, position: 'left',
                                        grid: { color: '#f1f5f9' }
                                    };
                                    if (hasY1) {
                                        config.options.scales.y1 = {
                                            type: 'linear', display: true, position: 'right',
                                            grid: { drawOnChartArea: false },
                                            title: { display: true, text: 'Secondary' }
                                        };
                                    }
                                }
                            }

                            const defaultOptions = {
                                responsive: true,
                                maintainAspectRatio: false,
                                interaction: { mode: 'index', intersect: false },
                                plugins: { legend: { position: 'top', labels: { usePointStyle: true, boxWidth: 6 } } }
                            };
                            const finalOptions = Object.assign({}, defaultOptions, config.options || {});

                            new Chart(ctx, {
                                type: chartType,
                                data: chartData,
                                options: finalOptions
                            });
                        } catch (e) { console.warn("Chart sync render error:", e); }
                    }, 100);
                }
            } catch (e) { }
        });
    }
}
