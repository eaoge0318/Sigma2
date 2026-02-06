


// --- Helper Functions (Deduplication) ---
const DOM = {
    get: (id) => document.getElementById(id),
    show: (id, type = 'block') => { const el = document.getElementById(id); if (el) el.style.display = type; },
    hide: (id) => { const el = document.getElementById(id); if (el) el.style.display = 'none'; },
    toggle: (id) => {
        const el = document.getElementById(id);
        if (el) el.style.display = (el.style.display === 'none' ? 'block' : 'none');
    },
    addClass: (id, cls) => { const el = document.getElementById(id); if (el) el.classList.add(cls); },
    removeClass: (id, cls) => { const el = document.getElementById(id); if (el) el.classList.remove(cls); },
    toggleClass: (id, cls) => { const el = document.getElementById(id); if (el) el.classList.toggle(cls); },
    setText: (id, txt) => { const el = document.getElementById(id); if (el) el.innerText = txt; },
    setHTML: (id, html) => { const el = document.getElementById(id); if (el) el.innerHTML = html; },
    val: (id, v) => {
        const el = document.getElementById(id);
        if (el) {
            if (v !== undefined) el.value = v;
            return el.value;
        }
        return null;
    },
    on: (id, event, handler) => {
        const el = document.getElementById(id);
        if (el) el.addEventListener(event, handler);
    }
};

const API = {
    headers: { 'Content-Type': 'application/json' },
    _url: (url, params = {}) => {
        const u = new URL(url, window.location.origin);
        if (window.SESSION_ID) u.searchParams.set('session_id', window.SESSION_ID);
        Object.keys(params).forEach(k => u.searchParams.set(k, params[k]));
        return u.toString();
    },
    get: async (url, params = {}) => {
        const res = await fetch(API._url(url, params));
        return res.ok ? res.json() : Promise.reject(res.statusText);
    },
    post: async (url, body = {}) => {
        if (window.SESSION_ID) body.session_id = window.SESSION_ID;
        const res = await fetch(url, {
            method: 'POST',
            headers: API.headers,
            body: JSON.stringify(body)
        });
        return res.ok ? res.json() : Promise.reject(res.statusText);
    },
    delete: async (url, params = {}) => {
        const res = await fetch(API._url(url, params), { method: 'DELETE' });
        return res.ok ? res.json() : Promise.reject(res.statusText);
    }
};

let charts = {};
const WINDOW_SIZE = 40;
let lastLogTimestamp = 0;
let autoPlayTimer = null;
let latestImportantFactors = []; // Store AI-suggested factors globally
let currentChartColumnOrder = []; // Store current visual order of columns for cycling
let dashboardPopupWindow = null; // 獨立視窗參照
let logAutoRefreshTimer = null; // 日誌自動刷新計時器
let registryRefreshTimer = null; // 模型列表自動刷新計時器
let modelRegistryCurrentPage = 1; // 模型列表目前分頁
const MODEL_REGISTRY_PAGE_SIZE = 9 // 模型列表每頁筆數

// Y 軸範圍控制
let yAxisMode = 'auto';  // 'auto' 或 'manual'
let yAxisManualMin = null;
let yAxisManualMax = null;


let fileListCurrentPage = 1; // 檔案列表目前分頁
const FILE_LIST_PAGE_SIZE = 9; // 檔案列表每頁筆數

// --- Session ID Management (Isolation) ---
// --- Session ID Management (Isolation) ---
function getSessionId() {
    let sid = localStorage.getItem("sigma2_session_id");
    if (!sid) {
        // Generate simple UUID-like string
        sid = 'sess-' + Math.random().toString(36).substr(2, 9) + Date.now().toString(36);
        localStorage.setItem("sigma2_session_id", sid);
    }
    return sid;
}
const SESSION_ID = getSessionId();
window.SESSION_ID = SESSION_ID; // Expose for popup
console.log("Current Session ID:", SESSION_ID);

// Global Switch User Function
window.switchUser = function () {
    const currentSid = localStorage.getItem("sigma2_session_id") || "default";
    const newSid = prompt("請輸入您的 User ID (Session ID):\n\n輸入 'default' 可檢視舊版檔案。", currentSid);
    if (newSid && newSid.trim() !== "") {
        localStorage.setItem("sigma2_session_id", newSid.trim());
        alert(`身份已切換為: ${newSid.trim()}\n頁面即將重整...`);
        window.location.reload();
    }
};
console.log("Current Session ID:", SESSION_ID);

async function triggerSimulatorNext() {
    try {
        const data = await API.post('/api/simulator/next');
        if (data.status === 'EOF') {
            alert(data.message);
            stopAutoPlay();
        } else {
            updateDashboard();
        }
    } catch (err) { console.error("Simulator Error:", err); }
}

async function runFullSimulation() {
    stopAutoPlay(); // 先停止現有的
    await API.post('/api/clear');

    // 清空前端顯示狀態
    lastLogTimestamp = 0;
    DOM.setHTML('reasoning-logs', '<div id="log-empty-msg" style="color: #94a3b8; text-align: center; padding: 30px;">目前沒有數據，請先啟動系統以收集數據。</div>');
    DOM.setHTML('ai-report-content', '<div class="ai-bubble chat-bubble">👋 模擬已重設，正在重新讀取數據集...</div>');
    DOM.setText('status-text', "Initializing Simulator...");

    // 由於核心數據已清空，調用一次 updateDashboard 來重置圖表
    setTimeout(async () => {
        await updateDashboard();
        startAutoPlay();
    }, 100);
}

function startAutoPlay() {
    const btn = document.getElementById('btn-autoplay');
    if (autoPlayTimer) return;
    btn.innerText = "Stop Auto ⏹️";
    btn.style.background = "#fee2e2";
    btn.style.borderColor = "#ef4444";
    triggerSimulatorNext(); // 立即跑第一筆
    autoPlayTimer = setInterval(triggerSimulatorNext, 2000);
}

function toggleAutoPlay() {
    if (autoPlayTimer) {
        stopAutoPlay();
    } else {
        startAutoPlay();
    }
}

function stopAutoPlay() {
    const btn = document.getElementById('btn-autoplay');
    if (autoPlayTimer) {
        clearInterval(autoPlayTimer);
        autoPlayTimer = null;
    }
    btn.innerText = "Auto Play ▶️";
    btn.style.background = "";
    btn.style.borderColor = "";
}

function toggleAssistant() {
    const win = DOM.get('ai-assistant-window');
    const isOpen = win.classList.contains('active');

    if (!isOpen) {
        // Open window
        DOM.show('ai-assistant-window', 'flex');
        // Delay adding active class to trigger CSS transition
        setTimeout(() => {
            DOM.addClass('ai-assistant-window', 'active');
            DOM.addClass('assistant-trigger', 'active');
            DOM.setText('fab-icon', '×');
        }, 10);
    } else {
        // Close window
        DOM.removeClass('ai-assistant-window', 'active');
        DOM.removeClass('assistant-trigger', 'active');
        DOM.setText('fab-icon', '🤖');
        // Wait for transition to finish before hiding
        setTimeout(() => {
            if (!win.classList.contains('active')) {
                DOM.hide('ai-assistant-window');
            }
        }, 300);
    }
}

/**
 * 智慧控制側邊欄邏輯 (點擊收合模式)
 */
function initAutoSidebar() {
    const sidebar = document.getElementById('sidebar');
    const mainContent = document.getElementById('main-content');
    if (!sidebar || !mainContent) return;

    // 模式：點擊主要畫面任何地方 -> 側邊欄縮進 (釋放空間)
    document.addEventListener('click', (e) => {
        // 檢查點擊是否在 main-content 內部
        const isClickInsideMain = mainContent.contains(e.target);

        // 如果點擊是在主區域內，且側邊欄不是收合狀態，則縮排
        if (isClickInsideMain && !sidebar.classList.contains('collapsed')) {
            sidebar.classList.add('collapsed');
            document.body.classList.add('sidebar-collapsed');
            triggerChartResize();
        }
    });
}

function triggerChartResize() {
    setTimeout(() => {
        if (window.charts) {
            Object.values(window.charts).forEach(c => c.resize());
        }
    }, 360);
}

function toggleSidebar() {
    const sidebar = DOM.get('sidebar');
    if (sidebar.classList.contains('collapsed')) {
        DOM.removeClass('sidebar', 'collapsed');
        document.body.classList.remove('sidebar-collapsed');
    } else {
        DOM.addClass('sidebar', 'collapsed');
        document.body.classList.add('sidebar-collapsed');
    }
    triggerChartResize();
}

function toggleExpand() {
    const win = document.getElementById('ai-assistant-window');
    win.classList.toggle('expanded');
}

// --- Popup Logic ---
function openDashboardChatPopup() {
    // Close internal window
    const win = document.getElementById('ai-assistant-window');
    if (win.classList.contains('active')) toggleAssistant();

    const w = 450;
    const h = 600;
    const left = (screen.width / 2) - (w / 2);
    const top = (screen.height / 2) - (h / 2);

    dashboardPopupWindow = window.open(
        '/static/dashboard_ai_popup.html',
        'DashboardAIChat',
        `width=${w},height=${h},top=${top},left=${left},resizable=yes,scrollbars=yes,status=no`
    );
}

window.registerDashboardPopup = function (popupWin) {
    dashboardPopupWindow = popupWin;
};

window.onDashboardPopupClose = function () {
    dashboardPopupWindow = null;
    const win = document.getElementById('ai-assistant-window');
    if (!win.classList.contains('active')) toggleAssistant();
};

window.handleDashboardPopupMessage = function (msg) {
    const input = document.getElementById('chat-input');
    input.value = msg;
    sendChatMessage();
};

window.handleDashboardPopupFileSelect = function (popupInput) {
    processFiles(popupInput.files);
    popupInput.value = '';
};

window.processFilesPopup = function (fileList) {
    processFiles(fileList);
};

// Lightweight sync from Popup to Main Window
window.receivePopupMessage = function (msg) {
    // 1. Update Data
    chatMessages.push(msg);

    // 2. Update UI asynchronously to avoid blocking prediction chart
    requestAnimationFrame(() => {
        const content = document.getElementById('ai-report-content');
        const bubble = document.createElement('div');
        bubble.className = msg.role === 'user' ? "user-bubble chat-bubble" : "ai-bubble chat-bubble";

        if (msg.images && msg.images.length > 0 && msg.role === 'user') {
            let html = msg.content;
            html += `<div class="bubble-attachments">`;
            msg.images.forEach(imgData => {
                html += `<img src="data:image/png;base64,${imgData}" class="bubble-attach-img">`;
            });
            html += `</div>`;
            bubble.innerHTML = html;
        } else if (msg.role === 'assistant') {
            bubble.innerHTML = marked.parse(msg.content);
            // Render charts lazily with FULL ROBUST LOGIC
            setTimeout(() => {
                const codeBlocks = bubble.querySelectorAll('pre code');
                codeBlocks.forEach(block => {
                    try {
                        const config = JSON.parse(block.innerText);
                        if (config.type === 'chart') {
                            block.parentElement.style.display = 'none';
                            const chartDiv = document.createElement('div');
                            chartDiv.style.height = "250px";
                            chartDiv.style.background = "#fff";
                            chartDiv.style.borderRadius = "8px";
                            chartDiv.style.padding = "10px";
                            chartDiv.style.marginBottom = "10px";
                            const canvas = document.createElement('canvas');
                            chartDiv.appendChild(canvas);
                            bubble.appendChild(chartDiv);

                            // --- Robust Chart Logic (Same as sendChatMessage) ---
                            if (!config.datasets || !config.datasets[0]) return;

                            let chartType = config.chart_type || 'line';
                            let chartData = { datasets: [] };
                            let chartOptions = config.options || {};

                            const hasTwoDatasets = config.datasets && config.datasets.length >= 2;
                            const missingLabels = !config.labels || config.labels.length === 0;
                            const isExplicitScatter = chartType === 'scatter';
                            const isExplicitLine = chartType === 'line';
                            const autoDetectScatter = !chartType && (hasTwoDatasets && missingLabels);

                            if (isExplicitScatter || (!isExplicitLine && autoDetectScatter)) {
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
                                if (!chartOptions.scales) chartOptions.scales = {};
                                chartOptions.scales.x = { type: 'linear', position: 'bottom', title: { display: true, text: config.datasets[0].label } };
                            } else {
                                chartType = 'line';
                                let labels = config.labels || [];
                                if (labels.length === 0 && config.datasets[0].data) {
                                    const dataLen = config.datasets[0].data.length;
                                    for (let i = dataLen - 1; i >= 0; i--) labels.push(`T-${i}`);
                                }
                                chartData.labels = labels;
                                chartData.datasets = config.datasets.map((ds, idx) => {
                                    const color = idx === 0 ? '#7c3aed' : (idx === 1 ? '#f59e0b' : '#3b82f6');
                                    const bgColor = idx === 0 ? 'rgba(124, 58, 237, 0.1)' : (idx === 1 ? 'rgba(245, 158, 11, 0.1)' : 'rgba(59, 130, 246, 0.1)');
                                    return {
                                        label: ds.label || `Series ${idx + 1}`,
                                        data: ds.data,
                                        borderColor: color,
                                        backgroundColor: bgColor,
                                        borderWidth: 2,
                                        fill: true, // Show area fill
                                        tension: 0.3,
                                        pointRadius: 3, // Show points
                                        pointHoverRadius: 5,
                                        pointBackgroundColor: '#fff',
                                        pointBorderWidth: 2
                                    };
                                });
                            }

                            const defaultOptions = {
                                responsive: true, maintainAspectRatio: false,
                                interaction: { mode: 'index', intersect: false },
                                plugins: { legend: { position: 'top', labels: { usePointStyle: true, boxWidth: 6 } } },
                                scales: { y: { beginAtZero: false, grid: { borderDash: [2, 2], color: '#f0f0f0' } }, x: { grid: { display: false } } }
                            };
                            const finalOptions = Object.assign({}, defaultOptions, chartOptions);

                            new Chart(canvas, { type: chartType, data: chartData, options: finalOptions });
                        }
                    } catch (e) {
                        console.error("Popup sync chart render failed:", e);
                    }
                });
            }, 100);
        } else {
            bubble.textContent = msg.content;
        }

        content.appendChild(bubble);
        content.scrollTop = content.scrollHeight;
    });
};

function syncDashboardToPopup(htmlContent, isUser) {
    // Non-blocking async version to prevent UI freeze
    if (!dashboardPopupWindow || dashboardPopupWindow.closed || !dashboardPopupWindow.document) {
        return;
    }

    // Schedule sync in next idle moment to avoid blocking main thread
    requestAnimationFrame(() => {
        setTimeout(() => {
            try {
                const content = document.getElementById('ai-report-content');
                const popupContent = dashboardPopupWindow.document.getElementById('ai-report-content');

                if (!popupContent || !content.lastElementChild) return;

                const clone = content.lastElementChild.cloneNode(true);
                popupContent.appendChild(clone);
                popupContent.scrollTop = popupContent.scrollHeight;

                // Defer chart rendering to avoid blocking
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

                // Fallback pixel copy (also deferred)
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

function syncDashboardPreviewToPopup() {
    const mainPreview = document.getElementById('file-preview');
    if (dashboardPopupWindow && !dashboardPopupWindow.closed && dashboardPopupWindow.document) {
        const popupPreview = dashboardPopupWindow.document.getElementById('file-preview');
        if (popupPreview) {
            popupPreview.innerHTML = mainPreview.innerHTML;
            popupPreview.style.display = mainPreview.style.display;
        }
    }
}

function initEventListeners() {
    // Chat Drag & Drop
    const chatBody = DOM.get('ai-report-content');
    const chatInput = DOM.get('chat-input');

    if (chatBody) {
        DOM.on('ai-report-content', 'dragover', (e) => {
            e.preventDefault();
            chatBody.classList.add('drag-over');
        });

        DOM.on('ai-report-content', 'dragleave', () => {
            chatBody.classList.remove('drag-over');
        });

        DOM.on('ai-report-content', 'drop', (e) => {
            e.preventDefault();
            chatBody.classList.remove('drag-over');
            if (e.dataTransfer.files.length > 0) {
                processFiles(e.dataTransfer.files);
            }
        });
    }

    // Chat Paste Image
    if (chatInput) {
        DOM.on('chat-input', 'paste', (e) => {
            const items = (e.clipboardData || e.originalEvent.clipboardData).items;
            const files = [];
            for (let i = 0; i < items.length; i++) {
                if (items[i].kind === 'file') {
                    files.push(items[i].getAsFile());
                }
            }
            if (files.length > 0) {
                processFiles(files);
            }
        });
    }

    // Global ESC Handler for Dashboard AI (Internal Window)
    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') {
            const win = document.getElementById('ai-assistant-window');
            // Only close if it is currently active (open) and NOT inside the popup (which handles its own ESC)
            if (win && win.classList.contains('active')) {
                toggleAssistant();
            }
        }
    });

    // Initialize Auto Sidebar
    initAutoSidebar();
}

document.addEventListener('DOMContentLoaded', () => {
    initEventListeners();
});

// --- View Switching Logic ---
let currentStep2SubIdx = 1;

const ALGO_CONFIG_MANIFEST = {
    "IQL": {
        "batch_size": { label: "批量大小 (Batch)", val: 1024, type: "number", hint: "推薦 1024" },
        "actor_learning_rate": { label: "Actor 學習率 (LR)", val: 0.0003, type: "number", step: 0.0001 },
        "critic_learning_rate": { label: "Critic 學習率 (LR)", val: 0.0003, type: "number", step: 0.0001 },
        "expectile": { label: "決策激進度 (Expectile)", val: 0.8, type: "number", step: 0.01, hint: "越接近 1 越激進" },
        "weight_temp": { label: "🔥 策略權重溫度", val: 0.5, type: "number", step: 0.01, hint: "重要參數" },
        "gamma": { label: "折扣因子 (Gamma)", val: 0.99, type: "number", step: 0.01 },
        "tau": { label: "目標更新率 (Tau)", val: 0.01, type: "number", step: 0.001 }
    }
};

const PRED_ALGO_CONFIG_MANIFEST = {
    "XGBoost": {
        "max_depth": { label: "最大樹深 (Max Depth)", val: 6, type: "number", hint: "推薦 3-10" },
        "learning_rate": { label: "學習率 (LR)", val: 0.1, type: "number", step: 0.01 },
        "subsample": { label: "樣本採樣比 (Subsample)", val: 0.8, type: "number", step: 0.1 },
        "colsample_bytree": { label: "特徵採樣比", val: 0.8, type: "number", step: 0.1 }
    },
    "RandomForest": {
        "n_estimators": { label: "樹木數量 (Trees)", val: 100, type: "number" },
        "max_depth": { label: "最大深度", val: 10, type: "number" },
        "min_samples_split": { label: "分裂所需樣本數", val: 2, type: "number" }
    },
    "LightGBM": {
        "num_leaves": { label: "葉子節點數", val: 31, type: "number" },
        "learning_rate": { label: "學習率", val: 0.05, type: "number", step: 0.01 },
        "feature_fraction": { label: "特徵隨機比例", val: 0.9, type: "number", step: 0.1 }
    }
};

/**
 * 根據輸入參數更新影響力評估 (Mock Logic)
 */
function updateConfigImpact() {
    const batchSize = parseInt(document.getElementById('hp-batch_size')?.value || 1024);
    const lr = parseFloat(document.getElementById('hp-actor_learning_rate')?.value || 0.0003);

    // 收斂速度計算 (簡化公式)
    // LR 越大越快，Batch 越大單次步進越穩(略快)
    let speedIdx = (lr * 10000 * 25) + (batchSize / 1024 * 30);
    speedIdx = Math.min(Math.max(speedIdx, 10), 95); // 限制在 10-95%

    // 記憶體佔用計算
    let memIdx = (batchSize / 2048 * 80);
    memIdx = Math.min(Math.max(memIdx, 5), 98);

    // 更新 DOM
    const speedBar = document.getElementById('impact-speed-bar');
    const speedText = document.getElementById('impact-speed-text');
    const memBar = document.getElementById('impact-memory-bar');
    const memText = document.getElementById('impact-memory-text');

    if (speedBar) speedBar.style.width = `${speedIdx}%`;
    if (speedText) speedText.innerText = `收斂速度: ${speedIdx > 80 ? '極速' : (speedIdx > 50 ? '優良' : '一般')}`;

    if (memBar) memBar.style.width = `${memIdx}%`;
    if (memText) memText.innerText = `記憶體佔用: ${memIdx > 70 ? '極高' : (memIdx > 30 ? '中等' : '低')}`;
}

/**
 * 動態渲染超參數面板
 */
function renderHyperParameters(algo) {
    const container = document.getElementById('dynamic-hyper-params');
    if (!container) return;

    // 更新演算法描述
    const descEl = document.getElementById('algo-desc');
    if (descEl) {
        if (algo === 'IQL') descEl.innerText = "* 離線數據建議使用 IQL，能穩定從歷史紀錄中學習最佳決策。";
        else descEl.innerText = "* 此演算法為實驗性配置。";
    }

    // 更新子導航標籤顯示演算法名稱
    const subNav1 = document.getElementById('sub-nav-1');
    if (subNav1) {
        subNav1.innerHTML = `<div class="dot">1</div> 學習演算法 (${algo})`;
    }

    const config = ALGO_CONFIG_MANIFEST[algo];
    if (!config) {
        container.innerHTML = '<div style="grid-column: span 2; color: #94a3b8; font-size: 11px; padding: 20px;">此演算法尚無預設配置</div>';
        return;
    }

    container.innerHTML = Object.entries(config).map(([key, item]) => `
        <div class="config-item" style="animation: fadeIn 0.3s ease forwards;">
            <label>${item.label}</label>
            <input type="${item.type || 'text'}" 
                   id="hp-${key}" 
                   oninput="updateConfigImpact()"
                   value="${item.val}" 
                   step="${item.step || ''}">
            ${item.hint ? `<span class="hint">${item.hint}</span>` : ''}
        </div>
    `).join('');

    // 初始執行一次更新
    setTimeout(updateConfigImpact, 50);
}

function switchStep2SubSection(idx) {
    currentStep2SubIdx = idx;

    // Update Sub-Nav active class
    document.querySelectorAll('.step2-sub-item').forEach(el => {
        if (el.id.startsWith('sub-nav-3-')) return; // Skip Step 3 buttons
        el.classList.remove('active');
    });
    const activeNav = document.getElementById(`sub-nav-${idx}`);
    if (activeNav) activeNav.classList.add('active');

    // Update Panel visibility
    document.querySelectorAll('.step2-panel').forEach(el => {
        if (el.id.startsWith('step3-panel-')) return; // Skip Step 3 panels
        el.classList.remove('active');
    });
    const activePanel = document.getElementById(`step2-panel-${idx}`);
    if (activePanel) activePanel.classList.add('active');

    // Trigger chart resize if in panel 2/3
    if (idx === 2 || idx === 3) {
        setTimeout(triggerChartResize, 100);
    }
}

let currentStep3SubIdx = 1;
function switchStep3SubSection(idx) {
    currentStep3SubIdx = idx;

    // Update Sub-Nav
    document.querySelectorAll('.step2-sub-item').forEach(el => {
        if (el.id.startsWith('sub-nav-3-')) el.classList.remove('active');
    });
    const activeNav = document.getElementById(`sub-nav-3-${idx}`);
    if (activeNav) activeNav.classList.add('active');

    // Update Panel
    document.querySelectorAll('.step2-panel').forEach(el => {
        if (el.id.startsWith('step3-panel-')) el.classList.remove('active');
    });
    const activePanel = document.getElementById(`step3-panel-${idx}`);
    if (activePanel) activePanel.classList.add('active');

    if (idx === 2) {
        initStep3Lists();
        setTimeout(triggerChartResize, 100);
    }
    if (idx === 3) {
        triggerPredictionPreCheck();
    }
}

function navigateStep2Sub(dir) {
    let nextIdx = currentStep2SubIdx + dir;
    if (nextIdx < 1) nextIdx = 1;
    if (nextIdx > 3) nextIdx = 3;
    switchStep2SubSection(nextIdx);
}

function switchView(viewName) {
    // Update Nav State
    const navItems = ['dashboard', 'files', 'analysis', 'training'];
    navItems.forEach(name => {
        const navId = 'nav-' + name;
        if (name === viewName) DOM.addClass(navId, 'active');
        else DOM.removeClass(navId, 'active');
    });

    // Toggle Views
    const views = {
        'dashboard': 'view-dashboard',
        'files': 'view-files',
        'analysis': 'view-analysis',
        'training': 'view-training'
    };

    Object.entries(views).forEach(([name, id]) => {
        if (name === viewName) DOM.show(id);
        else DOM.hide(id);
    });

    // Specific logic per view
    if (viewName === 'dashboard') {
        // Trigger chart resize after layout change
        setTimeout(() => {
            if (window.charts) Object.values(window.charts).forEach(c => c.resize());
        }, 50);
    } else if (viewName === 'training') {
        switchTrainingMainTab('build');
    } else if (viewName === 'files') {
        loadFileList();
    }

    // ✨ 新增：若非模型庫分頁，停止其刷新定時器
    if (viewName !== 'training') {
        clearAllTrainingTimers();
    }
}

/**
 * 切換模型訓練子分頁
 */
/**
 * 切換模型訓練主分頁 (L1): 建立模型 vs 模型庫管理
 */
function switchTrainingMainTab(tab) {
    const isBuild = (tab === 'build');

    // Toggle Content
    if (isBuild) {
        DOM.show('training-main-build-content');
        DOM.hide('training-main-registry-content');
    } else {
        DOM.hide('training-main-build-content');
        DOM.show('training-main-registry-content');
    }

    // Update Buttons
    const btnBuild = DOM.get('tab-train-main-build');
    const btnRegistry = DOM.get('tab-train-main-registry');
    setActiveTabStyle(isBuild ? btnBuild : btnRegistry, isBuild ? [btnRegistry] : [btnBuild]);

    if (isBuild) {
        // 預設切換到子分頁的「配置」
        switchTrainingSubTab('config');
        clearAllTrainingTimers();
    } else {
        loadModelRegistry();
        // ✨ 新增：進入模型庫時啟動自動刷新 (每 5 秒)
        if (registryRefreshTimer) clearInterval(registryRefreshTimer);
        registryRefreshTimer = setInterval(loadModelRegistry, 5000);
    }
}

/**
 * 切換模型訓練子分頁 (L2): 建模配置 vs 訓練報告
 */
function switchTrainingSubTab(tab) {
    const isConfig = (tab === 'config');
    const viewTitle = DOM.get('training-view-title');

    if (isConfig) {
        DOM.show('training-sub-config-content');
        DOM.hide('training-sub-report-content');
        if (viewTitle) viewTitle.innerText = '配置訓練參數';

        setActiveTabStyle(DOM.get('tab-train-sub-config'), [DOM.get('tab-train-sub-report')]);
        buildModelTrainingUI();
        switchTrainingStep(1); // 進入配置時自動重置到第一步
    } else {
        DOM.hide('training-sub-config-content');
        DOM.show('training-sub-report-content');
        if (viewTitle) viewTitle.innerText = '訓練報告介面';

        setActiveTabStyle(DOM.get('tab-train-sub-report'), [DOM.get('tab-train-sub-config')]);
    }
}

/**
 * 清理全局定時器 (Helper)
 */
function clearAllTrainingTimers() {
    if (registryRefreshTimer) {
        clearInterval(registryRefreshTimer);
        registryRefreshTimer = null;
    }
}

/**
 * 通用標籤樣式設定
 */
function setActiveTabStyle(activeBtn, inactiveBtns) {
    const isMainTab = (btn) => btn && btn.id.includes('main');

    const updateButtonStyle = (btn, isActive) => {
        if (!btn) return;
        if (isMainTab(btn)) {
            const isBuild = btn.id.includes('build');
            const color = isBuild ? '#3b82f6' : '#10b981';
            if (isActive) {
                btn.style.background = color;
                btn.style.color = '#fff';
                btn.style.boxShadow = `0 4px 12px ${isBuild ? 'rgba(59, 130, 246, 0.3)' : 'rgba(16, 185, 129, 0.3)'}`;
                btn.style.opacity = '1';
                btn.style.transform = 'translateY(-1px)';
            } else {
                btn.style.background = '#f1f5f9';
                btn.style.color = '#64748b';
                btn.style.boxShadow = 'none';
                btn.style.opacity = '0.6';
                btn.style.transform = 'none';
            }
        } else {
            // Pill style for sub-tabs
            if (isActive) {
                btn.style.background = '#fff';
                btn.style.color = '#3b82f6';
                btn.style.boxShadow = '0 1px 2px rgba(0,0,0,0.1)';
            } else {
                btn.style.background = 'transparent';
                btn.style.color = '#64748b';
                btn.style.boxShadow = 'none';
            }
        }
    };

    if (activeBtn) updateButtonStyle(activeBtn, true);
    inactiveBtns.forEach(btn => updateButtonStyle(btn, false));
}

/**
 * 載入模擬的模型分佈清單
 */
async function loadModelRegistry() {
    const tbody = DOM.get('model-list-body');
    const countText = DOM.get('model-count-text');
    if (!tbody) return;

    try {
        const models = await API.get('/api/analysis/list_models');

        if (countText) countText.innerText = models.length;
        tbody.innerHTML = '';

        if (models.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8" style="text-align: center; padding: 50px; color: #94a3b8; font-style: italic;">目前模型庫中尚未儲存任何模型</td></tr>';
            const paginationContainer = document.getElementById('model-registry-pagination');
            if (paginationContainer) paginationContainer.innerHTML = '';
            return;
        }

        // --- 分頁邏輯 ---
        const totalItems = models.length;
        const totalPages = Math.ceil(totalItems / MODEL_REGISTRY_PAGE_SIZE);

        // 防呆：如果當前頁碼超過總頁數（例如刪除動作後），回到最後一頁
        if (modelRegistryCurrentPage > totalPages) {
            modelRegistryCurrentPage = Math.max(1, totalPages);
        }

        const startIdx = (modelRegistryCurrentPage - 1) * MODEL_REGISTRY_PAGE_SIZE;
        const endIdx = startIdx + MODEL_REGISTRY_PAGE_SIZE;
        const displayedModels = models.slice(startIdx, endIdx);

        displayedModels.forEach((m) => {
            const tr = document.createElement('tr');
            tr.style.borderBottom = '1px solid #f1f5f9';
            tr.style.transition = 'background 0.2s';
            tr.onmouseover = () => tr.style.background = '#f8fafc';
            tr.onmouseout = () => tr.style.background = 'transparent';

            const pillStyle = "padding: 4px 14px; border-radius: 20px; font-size: 11px; font-weight: 700; color: #fff; display: inline-block; min-width: 80px; text-align: center; cursor: pointer;";
            const tagStyle = "padding: 2px 10px; border: 1px solid #3b82f6; border-radius: 12px; color: #3b82f6; font-size: 11px; font-weight: 600; background: rgba(59, 130, 246, 0.05);";
            const actionBtnStyle = "padding: 6px 10px; border: 1px solid #3b82f6; border-radius: 6px; background: #fff; color: #3b82f6; font-size: 11px; font-weight: 600; cursor: pointer; display: flex; align-items: center; gap: 4px; transition: all 0.2s;";

            // 格式化顯示 (相容舊版 snake_case 與新版 camelCase)
            const displayName = m.modelName || m.model_name || m.name || '未命名項目';
            const displayTarget = m.target || m.goal || '-';
            const mType = m.missionType || m.type;

            // 優先從專用欄位讀取，若無則根據任務類型推斷
            const displayStrategy = m.strategyAlgo && m.strategyAlgo !== '-' ? m.strategyAlgo : (mType === 'rl' ? m.algorithm : '-');
            const displayPred = m.predAlgo && m.pred_algo !== '-' ? m.predAlgo : (mType === 'supervised' ? m.algorithm : '-');

            // 組合資訊詳情
            let infoText = `模型名稱：${displayName}\\n`;
            infoText += `Job ID：${m.job_id}\\n`;
            infoText += `任務類型：${mType === 'rl' ? '最佳策略 (RL)' : '數據預測 (ML)'}\\n`;
            infoText += `目標標的：${displayTarget}\\n`;
            if (m.actions && m.actions.length > 0) infoText += `控制參數 (Actions)：${m.actions.join(', ')}\\n`;
            if (m.states && m.states.length > 0) infoText += `環境狀態 (States)：${m.states.join(', ')}\\n`;
            if (m.features && m.features.length > 0) infoText += `預測特徵 (Features)：${m.features.join(', ')}\\n`;

            const isTraining = m.status === 'training';

            tr.innerHTML = `
                <td style="padding: 12px 15px; font-weight: 500; color: #1e293b; font-size: 14px;">${displayName}</td>
                <td style="padding: 12px 15px;">
                    <span title="點擊查看訓練日誌" 
                          onclick="viewTrainingLog('${m.job_id}', '${displayName}')"
                          style="${pillStyle} ${m.status === 'completed' ? 'background: #2e7d32;' : (m.status === 'failed' ? 'background: #d32f2f;' : 'background: #1976d2;')}">
                        ${m.status === 'completed' ? '訓練完成' : (m.status === 'failed' ? '任務失敗/停止' : '訓練中')}
                    </span>
                </td>
                <td style="padding: 12px 15px;">
                    <span style="${tagStyle}">${displayTarget}</span>
                </td>
                <td style="padding: 12px 15px;">
                    <span style="${tagStyle}">${displayStrategy}</span>
                </td>
                <td style="padding: 12px 15px;">
                    <span style="${tagStyle}">${displayPred}</span>
                </td>
                <td style="padding: 12px 15px; color: #1e293b; font-size: 14px;">${m.rows || '-'}</td>
                <td style="padding: 12px 15px; color: #64748b; font-size: 14px;">${m.created_at || '-'}</td>
                <td style="padding: 12px 15px;">
                    <div style="display: flex; gap: 6px; align-items: center; justify-content: center;">
                        <button style="${actionBtnStyle.replace(/#3b82f6/g, '#64748b')}" 
                                onclick="alert('${infoText}')">資訊</button>
                        ${isTraining ? `
                            <button style="padding: 6px 10px; border: 1px solid #f97316; border-radius: 6px; background: #fff; color: #f97316; font-size: 11px; font-weight: 600; cursor: pointer; transition: all 0.2s;" 
                                    onmouseover="this.style.background='#fff7ed'" onmouseout="this.style.background='#fff'"
                                    onclick="stopModel('${m.job_id}', '${displayName}')">停止</button>
                        ` : ''}
                        <button style="padding: 6px 10px; border: 1px solid #ef4444; border-radius: 6px; background: #fff; color: #ef4444; font-size: 11px; font-weight: 600; cursor: pointer; transition: all 0.2s;" 
                                onmouseover="this.style.background='#fef2f2'" onmouseout="this.style.background='#fff'"
                                onclick="deleteModel('${m.job_id}', '${displayName}')">刪除</button>
                    </div>
                </td>
            `;
            tbody.appendChild(tr);
        });

        // 渲染分頁控制按鈕
        renderModelRegistryPagination(totalPages);

    } catch (err) {
        console.error('Failed to sync model registry:', err);
    }
}

/**
 * 渲染模型列表分頁控制
 */
function renderModelRegistryPagination(totalPages) {
    const container = document.getElementById('model-registry-pagination');
    if (!container) return;

    if (totalPages <= 1) {
        container.innerHTML = '';
        return;
    }

    const btnStyle = "padding: 6px 14px; border: 1px solid #e2e8f0; border-radius: 6px; background: #fff; color: #64748b; font-size: 12px; font-weight: 600; cursor: pointer; transition: all 0.2s;";
    const activeBtnStyle = "padding: 6px 14px; border: 1px solid #3b82f6; border-radius: 6px; background: #eff6ff; color: #3b82f6; font-size: 12px; font-weight: 700; cursor: default;";

    let html = '';

    // 上一頁
    html += `<button style="${btnStyle}" ${modelRegistryCurrentPage === 1 ? 'disabled style="opacity:0.5; cursor:not-allowed;"' : `onclick="changeModelRegistryPage(${modelRegistryCurrentPage - 1})"`}>上一頁</button>`;

    // 頁碼
    html += `<span style="display: flex; align-items: center; gap: 5px; color: #64748b; font-size: 12px; margin: 0 10px;">
        第 ${modelRegistryCurrentPage} / ${totalPages} 頁
    </span>`;

    // 下一頁
    html += `<button style="${btnStyle}" ${modelRegistryCurrentPage === totalPages ? 'disabled style="opacity:0.5; cursor:not-allowed;"' : `onclick="changeModelRegistryPage(${modelRegistryCurrentPage + 1})"`}>下一頁</button>`;

    container.innerHTML = html;
}

/**
 * 切換模型列表分頁
 */
function changeModelRegistryPage(newPage) {
    modelRegistryCurrentPage = newPage;
    loadModelRegistry();
}

/**
 * 刪除模型任務
 */
async function deleteModel(jobId, modelName) {
    if (!jobId) return;
    if (!confirm(`確定要刪除模型「${modelName}」及其訓練日誌嗎？\n此動作無法還原。`)) return;

    try {
        const res = await fetch(`/api/analysis/delete_model/${jobId}?session_id=${SESSION_ID}`, {
            method: 'DELETE'
        });
        const result = await res.json();

        if (result.status === 'success') {
            // 重新載入列表
            loadModelRegistry();
            if (window.Swal) {
                Swal.fire({
                    icon: 'success',
                    title: '刪除成功',
                    text: result.message,
                    timer: 1500,
                    showConfirmButton: false
                });
            } else {
                alert('✅ ' + result.message);
            }
        } else {
            alert('❌ 刪除失敗: ' + result.message);
        }
    } catch (err) {
        alert('API 請求異常: ' + err.message);
    }
}

/**
 * 強制停止運行的模型
 */
async function stopModel(jobId, modelName) {
    if (!jobId) return;
    if (!confirm(`確定要強制停止模型「${modelName}」的訓練進程嗎？`)) return;

    try {
        const res = await fetch(`/api/analysis/stop_model/${jobId}?session_id=${SESSION_ID}`, {
            method: 'POST'
        });
        const result = await res.json();

        if (result.status === 'success') {
            loadModelRegistry();
            if (window.Swal) {
                Swal.fire({ icon: 'success', title: '已停止', text: result.message, timer: 1500, showConfirmButton: false });
            } else {
                alert('✅ ' + result.message);
            }
        } else {
            alert('❌ 停止失敗: ' + result.message);
        }
    } catch (err) {
        alert('API 請求異常: ' + err.message);
    }
}

/**
 * 關閉日誌視窗並清理計時器
 */
function closeLogViewer() {
    if (logAutoRefreshTimer) {
        clearInterval(logAutoRefreshTimer);
        logAutoRefreshTimer = null;
    }
    const modal = document.getElementById('log-viewer-modal');
    if (modal) modal.remove();
}

// 支援 ESC 關閉視窗
window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closeLogViewer();
    }
});

/**
 * 切换自動刷新狀態
 */
function toggleLogAutoRefresh(jobId, modelName, checked) {
    if (logAutoRefreshTimer) {
        clearInterval(logAutoRefreshTimer);
        logAutoRefreshTimer = null;
    }

    if (checked) {
        // 設定每 3 秒自動刷新一次
        logAutoRefreshTimer = setInterval(() => {
            viewTrainingLog(jobId, modelName);
        }, 3000);
    }
}

/**
 * 查看特定任務的訓練日誌
 */
async function viewTrainingLog(jobId, modelName) {
    if (!jobId) {
        alert('找不到任務代碼 (Job ID)');
        return;
    }

    // 建立或獲取 Modal
    const modalId = 'log-viewer-modal';
    let modal = document.getElementById(modalId);
    let pre = document.getElementById('log-viewer-pre');

    try {
        const res = await fetch(`/api/analysis/get_log/${jobId}?session_id=${SESSION_ID}`);
        const logContent = await res.text();
        const cleanLog = logContent.startsWith('"') && logContent.endsWith('"') ? logContent.slice(1, -1).replace(/\\n/g, '\n').replace(/\\r/g, '') : logContent;

        // 如果 Modal 已經存在，只更新內容，實現無縫刷新（不會閃爍）
        if (modal && pre) {
            pre.innerText = cleanLog || "正在讀取日誌內容中...";
            pre.scrollTop = pre.scrollHeight;
            return;
        }

        // 第一次打開，建立完整 Modal
        modal = document.createElement('div');
        modal.id = modalId;
        modal.className = "log-modal-overlay";
        modal.style = "position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.8); z-index:99999; display:flex; align-items:center; justify-content:center; padding:20px; animation: fadeIn 0.15s ease;";
        modal.innerHTML = `
            <div style="background:#fff; width:95%; max-width:1100px; height:85vh; border-radius:16px; display:flex; flex-direction:column; overflow:hidden; box-shadow:0 25px 50px -12px rgba(0,0,0,0.5);">
                <div style="padding:15px 25px; background:#1e293b; color:#fff; display:flex; justify-content:space-between; align-items:center;">
                    <div style="display:flex; align-items:center; gap:10px;">
                        <span style="font-size:20px;">📜</span>
                        <div>
                            <div style="font-weight:800; font-size:15px;">訓練日誌監控</div>
                            <div style="font-size:11px; color:#94a3b8;">${modelName} - ${jobId}</div>
                        </div>
                    </div>
                    <div style="display:flex; gap:15px; align-items:center;">
                        <label style="display:flex; align-items:center; gap:8px; font-size:12px; color:#94a3b8; cursor:pointer; background:rgba(255,255,255,0.05); padding:5px 10px; border-radius:6px;">
                            <input type="checkbox" onchange="toggleLogAutoRefresh('${jobId}', '${modelName}', this.checked)" ${logAutoRefreshTimer ? 'checked' : ''}>
                            自動重新整理
                        </label>
                        <button onclick="viewTrainingLog('${jobId}', '${modelName}')" 
                                class="log-refresh-btn"
                                style="background:rgba(255,255,255,0.1); border:1px solid rgba(255,255,255,0.2); color:#fff; padding:5px 12px; border-radius:6px; font-size:12px; cursor:pointer; transition:all 0.2s;">
                            🔄 重新整理
                        </button>
                        <button onclick="closeLogViewer()" style="background:transparent; border:none; color:#fff; font-size:24px; cursor:pointer; line-height:1;">&times;</button>
                    </div>
                </div>
                <pre id="log-viewer-pre" style="flex:1; padding:25px; background:#0f172a; color:#38bdf8; margin:0; overflow:auto; font-family:'Roboto Mono', 'Fira Code', monospace; font-size:13px; line-height:1.6; white-space:pre-wrap; word-break:break-all;">${cleanLog || "正在讀取日誌..."}</pre>
                <div style="padding:15px 25px; background:#f8fafc; border-top:1px solid #e2e8f0; display:flex; justify-content:space-between; align-items:center;">
                    <div style="font-size:12px; color:#64748b;">💡 提示：此日誌僅顯示最後 2000 行，若需完整內容請至伺服器讀取。</div>
                    <button onclick="closeLogViewer()" style="padding:8px 25px; background:#3b82f6; color:#fff; border:none; border-radius:8px; font-weight:700; cursor:pointer; transition:all 0.2s;" onmouseover="this.style.background='#2563eb'" onmouseout="this.style.background='#3b82f6'">關閉視窗</button>
                </div>
            </div>
        `;
        document.body.appendChild(modal);

        // 捲動到底部
        const newPre = document.getElementById('log-viewer-pre');
        if (newPre) newPre.scrollTop = newPre.scrollHeight;

    } catch (err) {
        if (modal) {
            console.error('Refresh log failed:', err);
        } else {
            alert('獲取日誌失敗: ' + err.message);
        }
    }
}

/**
 * 建立模型訓練 UI 框架的資料內容
 */
async function buildModelTrainingUI() {
    const activeFileEl = document.getElementById('training-active-file');
    const filename = activeFileEl ? activeFileEl.innerText : '';

    if (filename && filename !== '未選擇') {
        // await loadTrainingMetadata(filename); // 這裡不需要重複載入，由 Context 選取控制
    }
}

// ==========================================
// ✨ Smart Workspace: 模型名稱與上下文控制
// ==========================================

function makeModelNameEditable() {
    const label = document.getElementById('training-model-name-label');
    const input = document.getElementById('training-model-name-input');
    if (label && input) {
        input.value = label.innerText;
        label.style.display = 'none';
        input.style.display = 'block';
        input.focus();
        input.select();
    }
}

function finishModelNameEdit() {
    const label = document.getElementById('training-model-name-label');
    const input = document.getElementById('training-model-name-input');
    if (label && input) {
        label.innerText = input.value.trim() || '未命名模型';
        label.style.display = 'block';
        input.style.display = 'none';

        // 觸發自動暫存提醒或視覺效果
        label.style.color = '#3b82f6';
        setTimeout(() => label.style.color = '', 500);
    }
}

// ------------------------------------------
// 納編中心 (Universal Loader) 邏輯
// ------------------------------------------

let currentContextTab = 'files';
let selectedContextItem = null;

function openTrainingContextModal() {
    const modal = document.getElementById('trainingContextModal');
    if (modal) {
        modal.classList.add('show');
        switchContextTab(currentContextTab);
    }
}

function closeTrainingContextModal() {
    const modal = document.getElementById('trainingContextModal');
    if (modal) modal.classList.remove('show');
}

async function switchContextTab(tab) {
    currentContextTab = tab;
    selectedContextItem = null;

    // UI 標籤切換
    document.querySelectorAll('.modal-tab').forEach(el => el.classList.remove('active'));
    document.getElementById(`tab-context-${tab}`).classList.add('active');

    const listArea = document.getElementById('context-list-area');
    const confirmBtn = document.getElementById('btn-confirm-context');
    const configOnlyBtn = document.getElementById('btn-load-config-only');
    const loadFullBtn = document.getElementById('btn-load-full');

    if (confirmBtn) {
        confirmBtn.style.display = 'flex';
        confirmBtn.disabled = true;
        confirmBtn.style.opacity = '0.5';
        confirmBtn.style.cursor = 'not-allowed';
    }
    if (configOnlyBtn) configOnlyBtn.style.display = 'none';
    if (loadFullBtn) loadFullBtn.style.display = 'none';

    const hint = document.getElementById('context-selection-hint');
    if (hint) hint.innerText = '請選擇來源以載入...';

    listArea.innerHTML = '<div style="text-align: center; padding: 40px; color: #94a3b8;">🔍 檢索中...</div>';

    try {
        let items = [];
        if (tab === 'files') {
            const res = await fetch(`/api/list_files?session_id=${SESSION_ID}`);
            const data = await res.json();
            // --- ✨ 改動：只取最近五筆 ---
            items = data.files
                .sort((a, b) => b.uploaded_at.localeCompare(a.uploaded_at))
                .slice(0, 5)
                .map(f => ({
                    id: f.filename,
                    title: f.filename,
                    meta: `${(f.size / 1024).toFixed(1)} KB | ${f.uploaded_at}`,
                    icon: '📊',
                    type: 'file'
                }));
        } else if (tab === 'models') {
            // 從後端獲取真實模型清单
            const res = await fetch('/api/analysis/list_models?session_id=' + SESSION_ID);
            const models = await res.json();
            items = models.map(m => ({
                id: m.job_id,
                title: m.modelName || m.model_name || '未命名模型',
                meta: `R2: ${m.r2 || 'N/A'} | ${m.created_at}`,
                icon: '🧠',
                type: 'model',
                data: m
            }));
        } else if (tab === 'drafts') {
            // 從後端 API 獲取草稿
            const res = await fetch(`/api/draft/list?session_id=${SESSION_ID}`);
            const data = await res.json();
            const drafts = data.drafts || [];

            items = drafts.map(d => ({
                id: d.id,
                title: d.modelName || '無標題草稿',
                meta: `來源: ${d.filename} | ${new Date(d.timestamp).toLocaleString()}`,
                icon: '💾',
                type: 'draft',
                data: d
            }));
        }

        renderContextList(items);
    } catch (err) {
        listArea.innerHTML = `<div style="text-align: center; padding: 40px; color: #ef4444;">❌ 載入失敗: ${err.message}</div>`;
    }
}

function renderContextList(items) {
    const listArea = document.getElementById('context-list-area');
    if (items.length === 0) {
        listArea.innerHTML = '<div style="text-align: center; padding: 60px; color: #94a3b8;"><span style="font-size: 40px;">📂</span><br>目前沒有任何項目</div>';
        return;
    }

    listArea.innerHTML = '';
    items.forEach(item => {
        const div = document.createElement('div');
        div.className = 'workspace-item';
        div.innerHTML = `
            <div class="workspace-item-icon">${item.icon}</div>
            <div class="workspace-item-info">
                <div class="workspace-item-name">${item.title}</div>
                <div class="workspace-item-meta">${item.meta}</div>
            </div>
        `;
        div.onclick = () => selectContextItem(div, item);
        div.ondblclick = () => { selectContextItem(div, item); confirmContextSelection(); };
        listArea.appendChild(div);
    });

    // --- ✨ 改動：如果在原始數據頁，加入「查看更多」按鈕 ---
    if (currentContextTab === 'files' && items.length > 0) {
        const moreBtn = document.createElement('div');
        moreBtn.style.cssText = 'padding: 15px; text-align: center; border-top: 1px dashed #e2e8f0; margin-top: 5px;';
        moreBtn.innerHTML = `
            <button onclick="closeTrainingContextModal(); switchView('files');" 
                    style="background: transparent; border: 1px solid #3b82f6; color: #3b82f6; padding: 6px 14px; border-radius: 6px; font-size: 11px; font-weight: 700; cursor: pointer; transition: all 0.2s;">
                &raquo; 檢索更多檔案 (進入檔案管理)
            </button>
        `;
        listArea.appendChild(moreBtn);
    }
}

function selectContextItem(el, item) {
    document.querySelectorAll('.workspace-item').forEach(it => it.classList.remove('selected'));
    el.classList.add('selected');
    selectedContextItem = item;

    const confirmBtn = document.getElementById('btn-confirm-context');
    const configOnlyBtn = document.getElementById('btn-load-config-only');
    const loadFullBtn = document.getElementById('btn-load-full');

    // 防呆處理：檢查當前主介面是否有選中數據檔案
    const activeFileEl = document.getElementById('training-active-file');
    const hasActiveFile = activeFileEl && activeFileEl.innerText !== '未選擇' && activeFileEl.innerText !== '';

    if (item.type === 'file') {
        if (confirmBtn) {
            confirmBtn.style.display = 'flex';
            confirmBtn.disabled = false;
            confirmBtn.style.opacity = '1';
            confirmBtn.style.cursor = 'pointer';
        }
        if (configOnlyBtn) configOnlyBtn.style.display = 'none';
        if (loadFullBtn) loadFullBtn.style.display = 'none';
    } else {
        // 模型或草稿模式
        if (confirmBtn) confirmBtn.style.display = 'none';

        if (configOnlyBtn) {
            configOnlyBtn.style.display = 'flex';
            if (!hasActiveFile) {
                configOnlyBtn.disabled = true;
                configOnlyBtn.style.opacity = '0.4';
                configOnlyBtn.style.background = '#e2e8f0';
                configOnlyBtn.style.borderColor = '#cbd5e1';
                configOnlyBtn.style.color = '#94a3b8';
                configOnlyBtn.style.cursor = 'not-allowed';
                configOnlyBtn.title = '請先選擇一個數據檔案，才能執行「僅套用設定」';
            } else {
                configOnlyBtn.disabled = false;
                configOnlyBtn.style.opacity = '1';
                configOnlyBtn.style.background = '#fff';
                configOnlyBtn.style.borderColor = '#3b82f6';
                configOnlyBtn.style.color = '#3b82f6';
                configOnlyBtn.style.cursor = 'pointer';
                configOnlyBtn.title = '';
            }
        }

        if (loadFullBtn) loadFullBtn.style.display = 'flex';
    }

    const hint = document.getElementById('context-selection-hint');
    if (hint) {
        if (!hasActiveFile && item.type !== 'file') {
            hint.innerHTML = `<span style="color: #ef4444;">⚠️ 尚未挑選數據 : </span> ${item.title}`;
        } else {
            hint.innerText = item.title;
        }
    }
}

async function confirmContextSelection(mode = 'full') {
    if (!selectedContextItem) return;

    const item = selectedContextItem;
    const fileLabel = document.getElementById('training-active-file');
    const modelLabel = document.getElementById('training-model-name-label');
    const ctxIcon = document.getElementById('context-icon');

    // 預設視覺重置
    if (fileLabel) fileLabel.style.color = '#3b82f6';
    if (ctxIcon) ctxIcon.innerText = item.icon || '📊';

    if (item.type === 'file') {
        const activeFileEl = document.getElementById('training-active-file');
        if (activeFileEl) {
            activeFileEl.innerText = item.id;
            activeFileEl.style.color = '#3b82f6';
        }
        window.currentTrainingFilename = item.id;

        // 自動生成預設名稱
        const now = new Date();
        const timestamp = `${now.getMonth() + 1}${now.getDate()}_${now.getHours()}${now.getMinutes()}`;
        if (modelLabel) modelLabel.innerText = `Model_${item.id.split('.')[0].substring(0, 8)}_${timestamp}`;

        // --- ✨ 全面重置訓練介面狀態 ---
        // 1. 重置 Step 1: 目標設定
        const goalSelect = document.getElementById('model-goal-col');
        if (goalSelect) goalSelect.value = '';
        if (document.getElementById('goal-target')) document.getElementById('goal-target').value = '';
        if (document.getElementById('goal-usl')) document.getElementById('goal-usl').value = '';
        if (document.getElementById('goal-lsl')) document.getElementById('goal-lsl').value = '';

        // 清除目標圖表
        if (typeof goalChart !== 'undefined' && goalChart) {
            goalChart.destroy();
            goalChart = null;
        }

        // 2. 重置 Step 2: 選取清單
        const ctrlSel = document.getElementById('control-selected');
        const stateSel = document.getElementById('state-selected');
        if (ctrlSel) ctrlSel.innerHTML = '<div style="padding: 20px; text-align: center; color: #94a3b8; font-size: 11px;">尚未選擇</div>';
        if (stateSel) stateSel.innerHTML = '<div style="padding: 20px; text-align: center; color: #94a3b8; font-size: 11px;">尚未選擇</div>';

        // 重置清單標題
        if (document.getElementById('control-selected-header')) document.getElementById('control-selected-header').innerText = '已選動作';
        if (document.getElementById('state-selected-header')) document.getElementById('state-selected-header').innerText = '已選狀態';

        // 3. 重置 Step 2: 監督式特徵勾選
        document.querySelectorAll('input[name="model-feature"]').forEach(cb => cb.checked = false);
        if (typeof updateSelectedFeaturesCount === 'function') updateSelectedFeaturesCount();

        // 4. 重置導航狀態 (移除 "完成" 標記)
        document.querySelectorAll('.step-title').forEach(el => {
            if (el.innerText.includes('(完成)')) {
                el.innerText = el.innerText.replace(' (完成)', '');
                el.style.color = '';
            }
        });
        document.querySelectorAll('.step2-sub-item').forEach(el => {
            el.classList.remove('done');
            // 重置子步驟文字 (移除計數)
            const text = el.innerText;
            if (text.includes('(')) {
                el.innerHTML = `<div class="dot">${el.querySelector('.dot')?.innerText || ''}</div> ${text.split('(')[0].trim()}`;
            }
        });

        // 5. 強制更新 UI
        if (typeof updateStep2UIStatus === 'function') updateStep2UIStatus();

        await loadTrainingMetadata(item.id);
        switchTrainingStep(1);
    }
    else if (item.type === 'model') {
        const modelData = item.data;
        if (!modelData) return;

        if (fileLabel) fileLabel.innerText = modelData.filename || '未知檔案';
        if (modelLabel) modelLabel.innerText = (modelData.modelName || modelData.model_name) + '_再訓練';

        // 既有模型配置的回填邏輯與草稿高度一致
        // 直接調用草稿回填函數，因為模型 JSON 本身就是一份完整的訓練配置
        await hydrateTrainingFromDraft(modelData, mode);

        if (window.Swal) {
            Swal.fire({
                icon: 'success',
                title: '模型納編成功',
                text: `已成功載入「${item.title}」的建模參數。`,
                timer: 1500,
                showConfirmButton: false
            });
        }
    }
    else if (item.type === 'draft') {
        // 根據 mode 決定是否更新檔名顯示
        if (mode === 'full') {
            if (fileLabel) fileLabel.innerText = item.data.filename;
        }
        if (modelLabel) modelLabel.innerText = item.data.modelName;

        // 執行深度回填 (帶入 mode 參數)
        await hydrateTrainingFromDraft(item.data, mode);
    }

    closeTrainingContextModal();
}

// ------------------------------------------
// 暫存與回填邏輯 (Draft System)
// ------------------------------------------

/**
 * ✨ 核心重構：統一收集目前的建模 UI 狀態
 * 這樣「暫存草稿」與「執行訓練時存入模型的 config.json」格式會完全一致。
 */
function collectTrainingUIState() {
    const modelName = document.getElementById('training-model-name-label')?.innerText || '未命名模型';
    const filename = document.getElementById('training-active-file')?.innerText || '未選擇';
    const missionType = document.querySelector('input[name="mission-type"]:checked')?.value || 'supervised';
    const goalCol = document.getElementById('model-goal-col')?.value;

    const state = {
        modelName: modelName,
        model_name: modelName, // 相容舊版
        filename: filename,
        missionType: missionType,
        type: missionType,     // 相容舊版
        goal: goalCol,
        goalSettings: {
            target: document.getElementById('goal-target')?.value || "",
            usl: document.getElementById('goal-usl')?.value || "",
            lsl: document.getElementById('goal-lsl')?.value || ""
        },
        // 給引擎看的別名
        goal_settings: {
            target: document.getElementById('goal-target')?.value || "",
            usl: document.getElementById('goal-usl')?.value || "",
            lsl: document.getElementById('goal-lsl')?.value || ""
        }
    };

    // 收集監督式 / 預測式相關 (Step 2 & Step 3)
    const predAlgo = document.getElementById('pred-algorithm')?.value || 'XGBoost';
    const predFeaturesList = Array.from(document.querySelectorAll('#pred-selected .list-item'))
        .filter(el => el.hasAttribute('data-value'))
        .map(el => ({ val: el.getAttribute('data-value'), text: el.innerText }));

    state.predAlgo = predAlgo;
    state.pred_algo = predAlgo; // 相容性
    state.predFeatures = predFeaturesList;
    state.features = predFeaturesList.map(f => f.val); // 引擎所需的純清單

    state.predHyperparams = Array.from(document.querySelectorAll('[id^="pred-hp-"]')).reduce((acc, el) => {
        acc[el.id.replace('pred-hp-', '')] = el.value;
        return acc;
    }, {});

    state.predCommon = {
        n_estimators: document.getElementById('pred-n-estimators')?.value,
        early_stop: document.getElementById('pred-early-stop')?.value,
        val_split: document.getElementById('pred-val-split')?.value
    };

    // 收集策略學習相關 (RL)
    const rlAlgo = document.getElementById('rl-algorithm')?.value || 'IQL';
    const rlActionsList = Array.from(document.querySelectorAll('#control-selected .list-item'))
        .filter(el => el.hasAttribute('data-value'))
        .map(el => ({ val: el.getAttribute('data-value'), text: el.innerText }));
    const rlStatesList = Array.from(document.querySelectorAll('#state-selected .list-item'))
        .filter(el => el.hasAttribute('data-value'))
        .map(el => ({ val: el.getAttribute('data-value'), text: el.innerText }));

    state.rlAlgo = rlAlgo;
    state.strategyAlgo = rlAlgo; // ✨ 修正：對齊 UI 列表顯示所需的欄位
    state.strategy_algo = rlAlgo;
    state.rlActions = rlActionsList;
    state.rlStates = rlStatesList;
    state.actions = rlActionsList.map(a => a.val); // 引擎所需的純清單
    state.states = rlStatesList.map(s => s.val);   // 引擎所需的純清單

    state.rlHyperparams = Array.from(document.querySelectorAll('[id^="hp-"]')).reduce((acc, el) => {
        acc[el.id.replace('hp-', '')] = el.value;
        return acc;
    }, {});

    // ✨ 根據任務類型決定主演算法 (用於列表顯示 fallback)
    if (missionType === 'rl') {
        state.algorithm = rlAlgo;
        state.hyperparams = { ...state.rlHyperparams };
        state.common = {
            epochs: document.getElementById('common-max-epochs')?.value,
            precision: document.getElementById('common-stable-threshold')?.value,
            stable_count: document.getElementById('common-stable-count')?.value,
            n_steps: document.getElementById('common-n-steps')?.value,
            n_steps_per_epoch: document.getElementById('common-n-steps-per-epoch')?.value
        };
    } else {
        state.algorithm = predAlgo;
        state.hyperparams = { ...state.predHyperparams };
        state.common = state.predCommon;
    }

    state.commonSettings = {
        epochs: document.getElementById('common-max-epochs')?.value,
        precision: document.getElementById('common-stable-threshold')?.value,
        stableCount: document.getElementById('common-stable-count')?.value,
        nSteps: document.getElementById('common-n-steps')?.value,
        n_steps: document.getElementById('common-n-steps')?.value, // 同步 snake_case
        nStepsPerEpoch: document.getElementById('common-n-steps-per-epoch')?.value,
        n_steps_per_epoch: document.getElementById('common-n-steps-per-epoch')?.value // 同步 snake_case
    };

    // 為聯合任務補足後端結構
    state.rl_common = {
        epochs: state.commonSettings.epochs,
        precision: state.commonSettings.precision,
        stable_count: state.commonSettings.stableCount,
        n_steps: state.commonSettings.nSteps || state.commonSettings.n_steps,
        n_steps_per_epoch: state.commonSettings.nStepsPerEpoch || state.commonSettings.n_steps_per_epoch
    };
    state.rl_hyperparams = state.rlHyperparams;

    // 其他元數據
    state.rows = document.getElementById('file-row-count-summary')?.innerText || '未知';
    state.timestamp = Date.now();

    return state;
}

async function saveCurrentTrainingDraft() {
    const config = collectTrainingUIState();
    if (!config.filename || config.filename === '未選擇') {
        alert('請先選擇一個數據來源檔案才能暫存！');
        return;
    }

    const draft = {
        ...config,
        id: 'draft_' + Date.now(),
    };

    // 呼叫後端 API 儲存暫存
    try {
        const res = await fetch(`/api/draft/save?session_id=${SESSION_ID}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(draft)
        });

        if (!res.ok) throw new Error('儲存失敗');

        const btn = document.getElementById('btn-save-draft');
        if (btn) {
            btn.innerText = '✅ 已暫存';
            btn.style.color = '#10b981';
            btn.dataset.saved = 'true';
        }
    } catch (err) {
        console.error("Save draft failed:", err);
        alert("暫存失敗，請檢查網路連線或伺服器狀態。");
    }
}

function markTrainingConfigChanged() {
    const btn = document.getElementById('btn-save-draft');
    if (btn && btn.dataset.saved === 'true') {
        btn.innerText = '💾 暫存';
        btn.style.color = '#94a3b8';
        btn.dataset.saved = 'false';
    }
}

function initTrainingChangeListeners() {
    const subConfig = document.getElementById('training-sub-config-content');
    if (subConfig) {
        // 使用集中式事件委託監控所有配置項目的變動
        ['input', 'change'].forEach(evtName => {
            subConfig.addEventListener(evtName, (e) => {
                const tag = e.target.tagName;
                // 排除列表搜尋框，這類變動不屬於配置修改
                if (e.target.closest('.list-search')) return;

                if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') {
                    markTrainingConfigChanged();
                }
            });
        });
    }

    // 模型名稱輸入框在 subConfig 之外，單獨加強監聽
    const modelNameInput = document.getElementById('training-model-name-input');
    if (modelNameInput) {
        modelNameInput.addEventListener('input', markTrainingConfigChanged);
    }

    // 監督式學習的特徵勾選 (由於其動態特性，確保事件有傳遞)
    const featuresList = document.getElementById('model-features-list');
    if (featuresList) {
        featuresList.addEventListener('change', markTrainingConfigChanged);
    }
}

async function hydrateTrainingFromDraft(draft, mode = 'full') {
    if (!draft) return;
    try {
        console.log(`🚀 Restoring draft (Mode: ${mode}):`, draft);

        // 1. 處理數據檔案載入
        const activeFileEl = document.getElementById('training-active-file');
        const currentFilename = activeFileEl ? activeFileEl.innerText : '未選擇';

        if (mode === 'full') {
            // 完整模式：強制切換數據檔案
            await loadTrainingMetadata(draft.filename);
            if (activeFileEl) activeFileEl.innerText = draft.filename;
        } else {
            // 僅設定模式：如果當前沒檔案，才載入草稿的檔案；否則保留現有的
            if (currentFilename === '未選擇' || !currentFilename) {
                await loadTrainingMetadata(draft.filename);
                if (activeFileEl) activeFileEl.innerText = draft.filename;
            } else {
                console.log(`ℹ️ Keeping current file: ${currentFilename}`);
            }
        }

        // 2. 切換任務類型
        if (draft.missionType) {
            const missionRadio = document.querySelector(`input[name="mission-type"][value="${draft.missionType}"]`);
            if (missionRadio) {
                missionRadio.checked = true;
                if (typeof onMissionTypeChange === 'function') onMissionTypeChange();
            }
        }

        // 3. 回填標題與標的 (Step 1)
        const modelLabel = document.getElementById('training-model-name-label');
        if (modelLabel && draft.modelName) modelLabel.innerText = draft.modelName;

        const goalColEl = document.getElementById('model-goal-col');
        if (goalColEl && draft.goal) {
            goalColEl.value = draft.goal;

            // ✨ BUG FIX: 校驗下拉選單是否成功選中該值，若無效則清空並跳過繪圖
            if (goalColEl.value !== draft.goal) {
                console.warn(`⚠️ Goal column "${draft.goal}" not found in current dataset options.`);
                goalColEl.value = "";
                if (typeof syncGoalToAll === 'function') syncGoalToAll("");
                if (typeof drawGoalChart === 'function') drawGoalChart("");
            } else {
                // 成功選中，同步並繪圖
                if (typeof syncGoalToAll === 'function') syncGoalToAll(draft.goal);
                if (typeof drawGoalChart === 'function') {
                    await drawGoalChart(draft.goal);
                }
            }
        }

        if (draft.goalSettings) {
            if (document.getElementById('goal-target')) document.getElementById('goal-target').value = draft.goalSettings.target || '';
            if (document.getElementById('goal-usl')) document.getElementById('goal-usl').value = draft.goalSettings.usl || '';
            if (document.getElementById('goal-lsl')) document.getElementById('goal-lsl').value = draft.goalSettings.lsl || '';

            // ✨ Force update lines to reflect restored values
            if (typeof updateGoalChartLines === 'function') {
                updateGoalChartLines();
            }
        }

        // 4. 還原 Step 2 / Step 3 (監督式 / 預測式)
        if (draft.supervisedAlgo) {
            const algoRadio = document.querySelector(`input[name="model-algo"][value="${draft.supervisedAlgo}"]`);
            if (algoRadio) algoRadio.checked = true;
        }
        if (draft.features) {
            document.querySelectorAll('input[name="model-feature"]').forEach(cb => {
                cb.checked = draft.features.includes(cb.value);
            });
        }

        // --- ✨ 全新 Step 03 還原邏輯 ---
        if (draft.predAlgo) {
            const predAlgoEl = document.getElementById('pred-algorithm');
            if (predAlgoEl) {
                predAlgoEl.value = draft.predAlgo;
                if (typeof renderPredHyperParameters === 'function') renderPredHyperParameters(draft.predAlgo);
            }
        }

        if (draft.predFeatures && draft.predFeatures.length > 0) {
            const predTarget = document.getElementById('pred-selected');
            if (predTarget) {
                predTarget.innerHTML = '';
                draft.predFeatures.forEach(f => {
                    const item = document.createElement('div');
                    item.className = 'list-item';
                    item.setAttribute('data-value', f.val);
                    item.setAttribute('draggable', 'true');
                    item.setAttribute('ondragstart', 'handleTrainingDragStart(event)');
                    item.setAttribute('onclick', 'toggleListItem(this)');
                    item.setAttribute('ondblclick', 'moveSingleItem(this)');
                    item.innerText = f.text;
                    predTarget.appendChild(item);
                });
            }
        }

        if (draft.predHyperparams) {
            Object.entries(draft.predHyperparams).forEach(([id, val]) => {
                const el = document.getElementById(`pred-hp-${id}`); // 注意這裡的 ID 格式
                if (el) el.value = val;
            });
        }

        if (draft.predCommon) {
            if (document.getElementById('pred-n-estimators')) document.getElementById('pred-n-estimators').value = draft.predCommon.n_estimators || '';
            if (document.getElementById('pred-early-stop')) document.getElementById('pred-early-stop').value = draft.predCommon.early_stop || '';
            if (document.getElementById('pred-val-split')) document.getElementById('pred-val-split').value = draft.predCommon.val_split || '';
        }

        if (typeof updateSelectedFeaturesCount === 'function') updateSelectedFeaturesCount();
        if (typeof updateStep3UIStatus === 'function') updateStep3UIStatus();

        // 5. 還原 Step 2: 強化學習配置 (RL)
        if (draft.rlAlgo) {
            const rlAlgoEl = document.getElementById('rl-algorithm');
            if (rlAlgoEl) {
                rlAlgoEl.value = draft.rlAlgo;
                // ✨ 必須顯式調用渲染，否則超參數輸入項不會出現在 DOM 中，導致回填失敗
                if (typeof renderHyperParameters === 'function') renderHyperParameters(draft.rlAlgo);
            }
            const rlAlgoRadio = document.querySelector(`input[name="rl-algo"][value="${draft.rlAlgo.toLowerCase()}"]`);
            if (rlAlgoRadio) rlAlgoRadio.checked = true;
        }

        const ctrlTarget = document.getElementById('control-selected');
        const stateTarget = document.getElementById('state-selected');

        if (ctrlTarget && draft.rlActions && draft.rlActions.length > 0) {
            ctrlTarget.innerHTML = '';
            draft.rlActions.forEach(a => {
                const item = document.createElement('div');
                item.className = 'list-item';
                item.setAttribute('data-value', a.val);
                item.setAttribute('draggable', 'true');
                item.setAttribute('ondragstart', 'handleTrainingDragStart(event)');
                item.setAttribute('onclick', 'toggleListItem(this)');
                item.setAttribute('ondblclick', 'moveSingleItem(this)');
                item.innerText = a.text;
                ctrlTarget.appendChild(item);
            });
        }

        if (stateTarget && draft.rlStates && draft.rlStates.length > 0) {
            stateTarget.innerHTML = '';
            draft.rlStates.forEach(s => {
                const item = document.createElement('div');
                item.className = 'list-item';
                item.setAttribute('data-value', s.val);
                item.setAttribute('draggable', 'true');
                item.setAttribute('ondragstart', 'handleTrainingDragStart(event)');
                item.setAttribute('onclick', 'toggleListItem(this)');
                item.setAttribute('ondblclick', 'moveSingleItem(this)');
                item.innerText = s.text;
                stateTarget.appendChild(item);
            });
        }

        // 重置選取狀態 map 以防錯亂
        lastSelectedIndexMap = {};

        // 同步刷新列表
        if (typeof initStep2Lists === 'function') initStep2Lists();
        if (typeof updateStep2UIStatus === 'function') updateStep2UIStatus();

        // 6. 回填 Step 3: 超參數與共通設定
        if (draft.rlHyperparams) { // 使用 rlHyperparams
            Object.entries(draft.rlHyperparams).forEach(([key, val]) => {
                const el = document.getElementById(`hp-${key}`); // 注意這裡的 ID 格式
                if (el) el.value = val;
            });
        }
        if (draft.commonSettings) {
            if (document.getElementById('common-max-epochs')) document.getElementById('common-max-epochs').value = draft.commonSettings.epochs || '500';
            if (document.getElementById('common-stable-threshold')) document.getElementById('common-stable-threshold').value = draft.commonSettings.precision || '0.001';
            if (document.getElementById('common-stable-count')) document.getElementById('common-stable-count').value = draft.commonSettings.stableCount || '5';

            // 強化回填步數 (相容多種命名格式)
            const nSteps = draft.commonSettings.nSteps || draft.commonSettings.n_steps || '500';
            const nStepsPerEpoch = draft.commonSettings.nStepsPerEpoch || draft.commonSettings.n_steps_per_epoch || '500';

            if (document.getElementById('common-n-steps')) document.getElementById('common-n-steps').value = nSteps;
            if (document.getElementById('common-n-steps-per-epoch')) document.getElementById('common-n-steps-per-epoch').value = nStepsPerEpoch;
        } else if (draft.hyperparams && draft.hyperparams.epochs) {
            // 向後相容舊格式
            if (document.getElementById('common-max-epochs')) document.getElementById('common-max-epochs').value = draft.hyperparams.epochs;
            const nStepsLegacy = draft.hyperparams.n_steps || draft.hyperparams.nSteps || '500';
            if (document.getElementById('common-n-steps')) document.getElementById('common-n-steps').value = nStepsLegacy;
        }

        // alert(`🎯 進度已恢復：${draft.modelName || '未命名'}\n已完整還原配置資訊。`);
    } catch (err) {
        console.error("❌ Hydration failed:", err);
        alert(`載入暫存時發生錯誤：${err.message}\n請確認數據檔案 "${draft.filename}" 是否仍然存在。`);
    }
}

/**
 * 載入指定檔案的訓練元數據 (標頭、目標、特徵)
 */
async function loadTrainingMetadata(filename) {
    window.currentTrainingFilename = filename; // Store globally
    if (!filename || filename === '未選擇') {
        const goalCol = document.getElementById('model-goal-col');
        if (goalCol) goalCol.innerHTML = '<option value="">-- 先選擇數據源 --</option>';
        const featuresList = document.getElementById('model-features-list');
        if (featuresList) featuresList.innerHTML = '<span style="color: #94a3b8; font-size: 12px;">無可用欄位</span>';
        return;
    }

    try {
        // --- ✨ 新贈：生成預設模型名稱 (僅在新選擇檔案時) ---
        const modelLabel = document.getElementById('training-model-name-label');
        if (modelLabel && (modelLabel.innerText === '未命名模型' || modelLabel.innerText === '')) {
            const now = new Date();
            const timestamp = `${now.getMonth() + 1}${now.getDate()}_${now.getHours()}${now.getMinutes()}`;
            const cleanName = filename.split('.')[0].substring(0, 8);
            modelLabel.innerText = `Model_${cleanName}_${timestamp}`;
        }
        // ------------------------------

        const viewRes = await fetch(`/api/view_file/${filename}?page=1&page_size=1&session_id=${SESSION_ID}`);
        const viewData = await viewRes.json();

        // 解析標頭內容 (後端 api 僅回傳 content 文字)
        let headers = [];
        if (viewData.headers && Array.isArray(viewData.headers)) {
            headers = viewData.headers;
        } else if (viewData.content) {
            const lines = viewData.content.trim().split('\n');
            if (lines.length > 0) {
                headers = lines[0].split(',').map(h => h.trim());
            }
        }

        const goalSelect = document.getElementById('model-goal-col');
        const featuresList = document.getElementById('model-features-list');
        const rlActionsList = document.getElementById('rl-actions-list');
        const rlStatesList = document.getElementById('rl-states-list');

        if (!goalSelect) return;

        // --- BUG FIX: 重置 Step 1 狀態 ---
        goalSelect.innerHTML = '<option value="">-- 請選擇 --</option>';
        ['goal-target', 'goal-usl', 'goal-lsl'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.value = '';
        });
        const countEl = document.getElementById('goal-out-count');
        const ratioEl = document.getElementById('goal-out-ratio');
        if (countEl) countEl.innerText = '0';
        if (ratioEl) ratioEl.innerText = '0.00%';

        if (goalChart) {
            goalChart.destroy();
            goalChart = null;
        }

        const step1Title = document.querySelector('#train-step-nav-1 .step-title');
        if (step1Title) {
            step1Title.innerText = '任務標的';
            step1Title.style.color = ''; // 恢復原色
        }
        // ------------------------------

        [featuresList, rlActionsList, rlStatesList].forEach(l => { if (l) l.innerHTML = ''; });

        if (headers.length > 0) {
            headers.forEach(h => {
                if (!h) return;

                // 1. 填入 Step 1 的目標選擇
                const opt = document.createElement('option');
                opt.value = h; opt.innerText = h;
                goalSelect.appendChild(opt);

                // 2. 填入 Step 2 的特徵勾選 (ML)
                if (featuresList) {
                    const lblML = document.createElement('label');
                    lblML.className = 'feature-item-label';
                    lblML.style.cssText = 'display:block; padding:8px 10px; font-size:13px; cursor:pointer; border-radius:6px; transition:all 0.2s;';
                    lblML.innerHTML = `<input type="checkbox" name="model-feature" value="${h}" checked style="margin-right:12px; transform:scale(1.1);"> ${h}`;
                    featuresList.appendChild(lblML);
                }

                // 3. 填入 Step 2 的 RL 動作與狀態
                if (rlActionsList) {
                    const lblAction = document.createElement('label');
                    lblAction.style.cssText = 'display:block; padding:6px; font-size:12px; cursor:pointer;';
                    lblAction.innerHTML = `<input type="checkbox" name="rl-action" value="${h}" style="margin-right:8px;"> ${h}`;
                    rlActionsList.appendChild(lblAction);
                }

                if (rlStatesList) {
                    const lblState = document.createElement('label');
                    lblState.style.cssText = 'display:block; padding:6px; font-size:12px; cursor:pointer;';
                    lblState.innerHTML = `<input type="checkbox" name="rl-state" value="${h}" checked style="margin-right:8px;"> ${h}`;
                    rlStatesList.appendChild(lblState);
                }
            });
        }
        updateSelectedFeaturesCount();

        // --- ✨ 重置 Step 3 狀態 ---
        const predSelected = document.getElementById('pred-selected');
        if (predSelected) predSelected.innerHTML = '';
        if (typeof updateStep3UIStatus === 'function') updateStep3UIStatus();
        if (typeof initStep3Lists === 'function') initStep3Lists();
        // -----------------------

    } catch (err) {
        console.error("Load training metadata failed:", err);
    }
}

/**
 * 同步 Step 1 的目標欄位到各模型模式的顯示與互斥邏輯
 */
function syncGoalToAll(val) {
    // 更新 Step 2 的顯示標籤
    const mlTargetEl = document.getElementById('display-ml-target');
    const rlRewardEl = document.getElementById('display-rl-reward');
    if (mlTargetEl) mlTargetEl.innerText = val || '(未設定)';
    if (rlRewardEl) rlRewardEl.innerText = val || '(未設定)';

    // 如果沒有選擇，清除圖表
    if (!val) {
        if (goalChart) {
            goalChart.destroy();
            goalChart = null;
        }
    }

    // 互斥邏輯：自動取消勾選與目標相同的特徵
    document.querySelectorAll('input[name="model-feature"]').forEach(i => {
        const p = i.parentElement;
        if (i.value === val) {
            i.checked = false; i.disabled = true; p.style.opacity = '0.4'; p.classList.add('disabled');
        } else {
            i.disabled = false; p.style.opacity = '1'; p.classList.remove('disabled');
        }
    });

    // 動作控制也應排除目標欄位 (通常不會控制目標本身)
    document.querySelectorAll('input[name="rl-action"]').forEach(i => {
        const p = i.parentElement;
        if (i.value === val) {
            i.checked = false; i.disabled = true; p.style.opacity = '0.4';
        } else {
            i.disabled = false; p.style.opacity = '1';
        }
    });

    updateSelectedFeaturesCount();

    // --- ✨ Step 2 防呆：如果目標被控制參數或背景參數挑到，將其移除 ---
    const step2Containers = ['control-selected', 'state-selected'];
    let removedFromStep2 = false;
    step2Containers.forEach(cid => {
        const container = document.getElementById(cid);
        if (!container) return;
        const items = Array.from(container.querySelectorAll('.list-item'));
        items.forEach(item => {
            if (item.getAttribute('data-value') === val) {
                item.remove();
                removedFromStep2 = true;
            }
        });

        // 如果搬空了，加入提示
        if (container.querySelectorAll('.list-item').length === 0) {
            container.innerHTML = '<div style="padding: 20px; text-align: center; color: #94a3b8; font-size: 11px;">尚未選擇</div>';
        }
    });

    if (removedFromStep2) {
        console.warn(`參數 ${val} 已被設為標的，從第二步選取清單中移除。`);
        if (window.Swal) {
            Swal.fire({
                icon: 'warning',
                title: '參數衝突',
                text: `「${val}」已被重新設定為任務標的，系統已自動將其從 Step 2 的選取清單中移除。`,
                confirmButtonColor: '#3b82f6'
            });
        }
    }

    // 重新初始化第二步的可用清單 (排除新的目標參數)
    if (typeof initStep2Lists === 'function') {
        initStep2Lists();
    }
}

/**
 * 繪製目標欄位的數據趨勢圖 (Scatter Plot)
 */
let goalChart = null;
async function drawGoalChart(colName) {
    const canvas = document.getElementById('goal-column-chart-canvas');
    if (!canvas) return;

    if (!colName || !window.currentTrainingFilename) {
        if (goalChart) {
            goalChart.destroy();
            goalChart = null;
        }
        // ✨ BUG FIX: 當標的不存在時，必須清空規格參數輸入框與統計資訊
        const inputs = ['goal-target', 'goal-usl', 'goal-lsl'];
        inputs.forEach(id => {
            const el = document.getElementById(id);
            if (el) el.value = '';
        });
        const countEl = document.getElementById('goal-out-count');
        const ratioEl = document.getElementById('goal-out-ratio');
        if (countEl) countEl.innerText = '0';
        if (ratioEl) ratioEl.innerText = '0.00%';

        return;
    }

    try {
        const res = await fetch(`/api/view_file/${window.currentTrainingFilename}?page=1&page_size=500&session_id=${SESSION_ID}`);
        const data = await res.json();

        let headerRow = [];
        let rows = [];
        if (data.headers) {
            headerRow = data.headers;
            rows = data.rows || [];
        } else if (data.content) {
            const rawLines = data.content.trim().split('\n');
            headerRow = rawLines[0].split(',').map(h => h.trim());
            rows = rawLines.slice(1).map(l => l.split(',').map(v => v.trim()));
        }

        const colIdx = headerRow.indexOf(colName);
        if (colIdx === -1) return;

        const seriesData = rows.map((r, i) => ({
            x: i,
            y: parseFloat(r[colIdx])
        })).filter(d => !isNaN(d.y));

        // 自動計算 Mean 與 3-Sigma
        const values = seriesData.map(d => d.y);
        if (values.length > 0) {
            const mean = values.reduce((a, b) => a + b, 0) / values.length;
            const sqDiffs = values.map(v => Math.pow(v - mean, 2));
            const avgSqDiff = sqDiffs.reduce((a, b) => a + b, 0) / values.length;
            const std = Math.sqrt(avgSqDiff);

            document.getElementById('goal-target').value = mean.toFixed(4);
            document.getElementById('goal-usl').value = (mean + 3 * std).toFixed(4);
            document.getElementById('goal-lsl').value = (mean - 3 * std).toFixed(4);
        }

        window.lastGoalValues = values; // 儲存數據供統計使用

        if (goalChart) {
            goalChart.destroy();
        }

        const ctx = canvas.getContext('2d');
        goalChart = new Chart(ctx, {
            type: 'scatter',
            data: {
                datasets: [{
                    label: colName,
                    data: seriesData,
                    backgroundColor: 'rgba(59, 130, 246, 0.6)',
                    borderColor: '#3b82f6',
                    borderWidth: 1,
                    pointRadius: 3
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: { title: { display: true, text: 'Index', font: { size: 10 } } },
                    y: { title: { display: true, text: 'Value', font: { size: 10 } }, beginAtZero: false }
                },
                plugins: {
                    legend: { display: false },
                    annotation: {
                        annotations: {}
                    }
                }
            }
        });

        updateGoalChartLines();
    } catch (err) {
        console.error("Draw goal chart failed:", err);
    }
}

function updateGoalChartLines() {
    if (!goalChart) return;

    const target = parseFloat(document.getElementById('goal-target').value);
    const usl = parseFloat(document.getElementById('goal-usl').value);
    const lsl = parseFloat(document.getElementById('goal-lsl').value);

    const annotations = {};
    if (!isNaN(target)) {
        annotations.targetLine = {
            type: 'line',
            yMin: target,
            yMax: target,
            borderColor: '#10b981',
            borderWidth: 2,
            label: { display: true, content: 'Target', position: 'end', backgroundColor: '#10b981', color: '#fff', font: { size: 10 } }
        };
    }
    if (!isNaN(usl)) {
        annotations.uslLine = {
            type: 'line',
            yMin: usl,
            yMax: usl,
            borderColor: '#ef4444',
            borderWidth: 1,
            borderDash: [5, 5],
            label: { display: true, content: 'USL', position: 'start', backgroundColor: '#ef4444', color: '#fff', font: { size: 10 } }
        };
    }
    if (!isNaN(lsl)) {
        annotations.lslLine = {
            type: 'line',
            yMin: lsl,
            yMax: lsl,
            borderColor: '#f59e0b',
            borderWidth: 1,
            borderDash: [5, 5],
            label: { display: true, content: 'LSL', position: 'start', backgroundColor: '#f59e0b', color: '#fff', font: { size: 10 } }
        };
    }

    goalChart.options.plugins.annotation.annotations = annotations;
    goalChart.update();

    // 計算超規筆數
    if (window.lastGoalValues && window.lastGoalValues.length > 0) {
        let outCount = 0;
        window.lastGoalValues.forEach(v => {
            if (!isNaN(usl) && v > usl) outCount++;
            else if (!isNaN(lsl) && v < lsl) outCount++;
        });

        const total = window.lastGoalValues.length;
        const ratio = (outCount / total) * 100;

        const countEl = document.getElementById('goal-out-count');
        const ratioEl = document.getElementById('goal-out-ratio');
        const totalEl = document.getElementById('goal-total-count');

        if (countEl) countEl.innerText = outCount;
        if (totalEl) totalEl.innerText = `(${total})`;
        if (ratioEl) ratioEl.innerText = ratio.toFixed(2) + '%';
    }

    // 更新側邊欄狀態為完成
    const goalCol = document.getElementById('model-goal-col').value;
    const step1Title = document.querySelector('#train-step-nav-1 .step-title');
    if (step1Title) {
        if (goalCol && (!isNaN(target) || !isNaN(usl) || !isNaN(lsl))) {
            if (!step1Title.innerText.includes('(完成)')) {
                step1Title.innerText = '任務標的 (完成)';
                step1Title.style.color = '#10b981';
            }
        } else {
            step1Title.innerText = '任務標的';
            step1Title.style.color = '';
        }
    }
    // 觸發全局完成度檢查
    if (typeof checkGlobalTrainingStatus === 'function') checkGlobalTrainingStatus();
}

/**
 * 手動計算 3倍標準差並填入比較欄位
 */
function calculateThreeSigma() {
    if (!window.lastGoalValues || window.lastGoalValues.length === 0) {
        if (window.Swal) {
            Swal.fire({
                icon: 'info',
                title: '無可用數據',
                text: '請先選擇目標欄位以進行計算。',
                confirmButtonColor: '#3b82f6'
            });
        } else {
            alert('無可用數據，請先選擇目標欄位。');
        }
        return;
    }

    const values = window.lastGoalValues;
    const mean = values.reduce((a, b) => a + b, 0) / values.length;
    const sqDiffs = values.map(v => Math.pow(v - mean, 2));
    const avgSqDiff = sqDiffs.reduce((a, b) => a + b, 0) / values.length;
    const std = Math.sqrt(avgSqDiff);

    document.getElementById('goal-target').value = mean.toFixed(4);
    document.getElementById('goal-usl').value = (mean + 3 * std).toFixed(4);
    document.getElementById('goal-lsl').value = (mean - 3 * std).toFixed(4);

    updateGoalChartLines();
}

// 綁定輸入事件
// 綁定輸入事件
document.addEventListener('DOMContentLoaded', () => {
    const inputs = ['goal-target', 'goal-usl', 'goal-lsl'];
    inputs.forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.addEventListener('input', updateGoalChartLines);
        }
    });
    // ✨ Initialize Chart Dragging
    initGoalChartDrag();
});

// --- ✨ Interactive Line Dragging Logic ---
let goalChartDragState = {
    active: false,
    targetId: null
};

function initGoalChartDrag() {
    const canvas = document.getElementById('goal-column-chart-canvas');
    if (!canvas) return;

    canvas.addEventListener('mousemove', function (e) {
        if (!goalChart || !goalChart.scales || !goalChart.scales.y) return;

        const rect = canvas.getBoundingClientRect();
        const y = e.clientY - rect.top;
        const scaleY = goalChart.scales.y;

        // 1. Handling Drag
        if (goalChartDragState.active && goalChartDragState.targetId) {
            const newVal = scaleY.getValueForPixel(y);
            const input = document.getElementById(goalChartDragState.targetId);
            if (input) {
                input.value = newVal.toFixed(4);
                updateGoalChartLines(); // Update chart & UI
            }
            return;
        }

        // 2. Handling Hover Check
        const inputs = {
            'goal-target': document.getElementById('goal-target').value,
            'goal-usl': document.getElementById('goal-usl').value,
            'goal-lsl': document.getElementById('goal-lsl').value
        };

        let hit = null;
        let minDist = 10; // Pixel tolerance

        for (const [id, valStr] of Object.entries(inputs)) {
            if (!valStr || isNaN(parseFloat(valStr))) continue;
            const val = parseFloat(valStr);
            const pixel = scaleY.getPixelForValue(val);
            if (Math.abs(pixel - y) < minDist) {
                hit = id;
                break;
            }
        }

        if (hit) {
            canvas.style.cursor = 'row-resize';
            goalChartDragState.hoverTarget = hit;
        } else {
            canvas.style.cursor = 'default';
            goalChartDragState.hoverTarget = null;
        }
    });

    canvas.addEventListener('mousedown', function (e) {
        if (goalChartDragState.hoverTarget) {
            goalChartDragState.active = true;
            goalChartDragState.targetId = goalChartDragState.hoverTarget;
            e.preventDefault(); // Prevent text selection
        }
    });

    const stopDrag = () => {
        goalChartDragState.active = false;
        goalChartDragState.targetId = null;
    };

    canvas.addEventListener('mouseup', stopDrag);
    canvas.addEventListener('mouseleave', stopDrag);
}

/**
 * 訓練流程步驟切換
 */
// function switchTrainingStep(step) {
//     // 強制隱藏所有步驟面板
//     document.querySelectorAll('.train-step-panel').forEach(p => {
//         p.style.setProperty('display', 'none', 'important');
//     });
//     document.querySelectorAll('.flow-nav-item').forEach(n => n.classList.remove('active'));

//     // 顯示目前步驟面板
//     const targetPanel = document.getElementById(`train-step-panel-${step}`);
//     if (targetPanel) {
//         targetPanel.style.setProperty('display', 'flex', 'important');
//     }
//     const targetNav = document.getElementById(`train-step-nav-${step}`);
//     if (targetNav) {
//         targetNav.classList.add('active');
//     }

//     if (step === 2) {
//         initStep2Lists(); // 嘗試初始化清單
//         renderHyperParameters(document.getElementById('rl-algorithm')?.value || 'IQL');
//         setTimeout(() => {
//             updateStep2UIStatus();
//             switchStep2SubSection(1); // 預設顯示第一個子分頁
//         }, 50);
//     }
// }

/**
 * ✨ Step 1 防呆：在選取標的欄位前檢查是否已選擇檔案
 */
function checkTrainingFileBeforeSelect(ev) {
    const filenameLabel = document.getElementById('training-active-file');
    const filename = filenameLabel ? filenameLabel.innerText.trim() : '';

    if (!filename || filename === '未選擇') {
        if (ev) {
            ev.preventDefault();
            ev.stopPropagation();
        }
        // 直接開啟檔案選擇器
        openFileSelector('training');
        return false;
    }
}

function switchTrainingStep(step) {
    // 1. Reset all panels to hidden
    const panels = document.querySelectorAll('.train-step-panel');
    panels.forEach(p => {
        p.style.display = 'none';
        p.classList.remove('active-step');
    });

    const navs = document.querySelectorAll('.flow-nav-item');
    navs.forEach(n => n.classList.remove('active'));

    // 2. Activate target
    const currentPanel = document.getElementById(`train-step-panel-${step}`);
    if (currentPanel) {
        currentPanel.style.display = 'flex';
    }

    const currentNav = document.getElementById(`train-step-nav-${step}`);
    if (currentNav) {
        currentNav.classList.add('active');
    }

    // 3. 任務類型與步驟初始化 (✨ 自動感應任務模式)
    if (step === 2) {
        // 進入「最佳策略」代表進入強化學習模式
        const rlRadio = document.querySelector('input[name="mission-type"][value="rl"]');
        if (rlRadio) {
            rlRadio.checked = true;
            onMissionTypeChange();
        }
        switchStep2SubSection(1);
        initStep2Lists();
        const algo = document.getElementById('rl-algorithm')?.value || 'IQL';
        renderHyperParameters(algo);
        setTimeout(updateStep2UIStatus, 100);
    }
    else if (step === 3) {
        // 進入「預測配置」代表進入監督式學習模式
        const mlRadio = document.querySelector('input[name="mission-type"][value="supervised"]');
        if (mlRadio) {
            mlRadio.checked = true;
            onMissionTypeChange();
        }
        switchStep3SubSection(1);
        const algo = document.getElementById('pred-algorithm')?.value || 'XGBoost';
        renderPredHyperParameters(algo);
        updateStep3UIStatus();
    }
}

/**
 * 動態渲染預測超參數面板
 */
function renderPredHyperParameters(algo) {
    const container = document.getElementById('pred-dynamic-hyper-params');
    if (!container) return;

    // 更新描述
    const descEl = document.getElementById('pred-algo-desc');
    if (descEl) {
        if (algo === 'XGBoost') descEl.innerText = "* XGBoost 是處理結構化工業數據最穩定的選擇，具備極強的非線性擬合能力。";
        else if (algo === 'RandomForest') descEl.innerText = "* 隨機森林具備極佳的抗噪性，適合特徵分佈較分散的數據。";
        else descEl.innerText = "* 此演算法適合大規模、高效率的訓練場景。";
    }

    // 更新導航文字
    const subNav1 = document.getElementById('sub-nav-3-1');
    if (subNav1) subNav1.innerHTML = `<div class="dot">1</div> 預測演算法 (${algo})`;

    const config = PRED_ALGO_CONFIG_MANIFEST[algo];
    if (!config) {
        container.innerHTML = '<div style="grid-column: span 2; color: #94a3b8; font-size: 11px; padding: 20px;">此演算法尚定定義預設配置</div>';
        return;
    }

    container.innerHTML = Object.entries(config).map(([key, item]) => `
        <div class="config-item" style="animation: fadeIn 0.3s ease forwards;">
            <label>${item.label}</label>
            <input type="${item.type || 'text'}" 
                   id="pred-hp-${key}" 
                   value="${item.val}" 
                   step="${item.step || ''}">
            ${item.hint ? `<span class="hint">${item.hint}</span>` : ''}
        </div>
    `).join('');
}

/**
 * 初始化第三步的預測製程參數清單 (Dual List)
 */
function initStep3Lists() {
    const goalCol = document.getElementById('model-goal-col')?.value;
    const selectEl = document.getElementById('model-goal-col');
    if (!selectEl) return;

    const allCols = Array.from(selectEl.options)
        .map(opt => opt.value)
        .filter(val => val !== "" && val !== goalCol);

    const selectedFeatures = Array.from(document.getElementById('pred-selected').querySelectorAll('.list-item'))
        .map(el => el.getAttribute('data-value'));

    const container = document.getElementById('pred-avail');
    if (!container) return;

    const availableCols = allCols.filter(c => !selectedFeatures.includes(c));

    if (availableCols.length === 0) {
        container.innerHTML = '<div style="padding: 20px; text-align: center; color: #94a3b8; font-size: 11px;">無可用參數</div>';
    } else {
        container.innerHTML = availableCols.map(col => `
            <div class="list-item" draggable="true" ondragstart="handleTrainingDragStart(event)" onclick="toggleListItem(this)" ondblclick="moveSingleItem(this)" data-value="${col}">${col}</div>
        `).join('');
    }

    // 確保已選清單有預設 UI
    const selContainer = document.getElementById('pred-selected');
    if (selContainer && selContainer.querySelectorAll('.list-item').length === 0) {
        selContainer.innerHTML = '<div style="padding: 20px; text-align: center; color: #94a3b8; font-size: 11px;">尚未選擇</div>';
    }

    updateStep3UIStatus();
}

/**
 * 更新 STEP 03 UI 完成度狀態
 */
function updateStep3UIStatus() {
    const selectedCount = document.getElementById('pred-selected')?.querySelectorAll('.list-item').length || 0;

    // 更新診斷頁面計數
    const countEl = document.getElementById('pred-feat-count');
    if (countEl) countEl.innerText = selectedCount;

    // 更新導航項目狀態
    const subNav2 = document.getElementById('sub-nav-3-2');
    if (subNav2) {
        if (selectedCount > 0) {
            // 使用特殊的 done-blue 類別以區別於綠色的完成狀態
            subNav2.classList.add('done-blue');
            subNav2.innerHTML = `<div class="dot">2</div> 製程參數 (${selectedCount})`;
        } else {
            subNav2.classList.remove('done-blue');
            subNav2.innerHTML = `<div class="dot">2</div> 製程參數`;
        }
    }

    // 當製程參數有設定，主步驟即可標記為 (完成)
    const stepTitle = document.querySelector('#train-step-nav-3 .step-title');
    if (stepTitle) {
        if (selectedCount > 0) {
            stepTitle.innerText = '預測配置 (完成)';
            stepTitle.style.color = '#10b981'; // 改回綠色風格，保持一致性
        } else {
            stepTitle.innerText = '預測配置';
            stepTitle.style.color = '';
        }
    }

    // 觸發全局完成度檢查
    checkGlobalTrainingStatus();
}

/**
 * 全局檢查三個步驟是否都完成，若是則開啟「模型建立」按鈕
 */
function checkGlobalTrainingStatus() {
    const s1 = document.querySelector('#train-step-nav-1 .step-title')?.innerText.includes('(完成)');
    const s2 = document.querySelector('#train-step-nav-2 .step-title')?.innerText.includes('(完成)');
    const s3 = document.querySelector('#train-step-nav-3 .step-title')?.innerText.includes('(完成)');

    const btn = document.getElementById('final-train-btn');
    if (!btn) return;

    if (s1 && s2 && s3) {
        btn.disabled = false;
        btn.style.background = '#3b82f6';
        btn.style.cursor = 'pointer';
        btn.style.opacity = '1';
    } else {
        btn.disabled = true;
        btn.style.background = '#cbd5e1';
        btn.style.cursor = 'not-allowed';
        btn.style.opacity = '0.7';
    }
}

/**
 * 預測前的診斷動畫邏輯
 */
function triggerPredictionPreCheck() {
    const targetStatus = document.getElementById('pred-target-status');
    const goalCol = document.getElementById('model-goal-col')?.value;
    if (!targetStatus) return;

    if (!goalCol) {
        targetStatus.innerText = "❌ 尚未選擇標的";
        targetStatus.style.color = "#ef4444";
        return;
    }

    targetStatus.innerText = "🔍 診斷中...";
    targetStatus.style.color = "#f59e0b";

    setTimeout(() => {
        targetStatus.innerText = "✅ 正嚮分佈 (健康)";
        targetStatus.style.color = "#10b981";
    }, 1200);
}

/**
 * 手風琴切換
 */
function toggleAcc(id) {
    const item = document.getElementById(id);
    const isOpen = item.classList.contains('open');

    // 我們可以選擇是否互斥，這裡讓其他收起來增加專注度
    document.querySelectorAll('.acc-item').forEach(it => it.classList.remove('open'));

    if (!isOpen) {
        item.classList.add('open');
    }
}

/**
 * 初始化第二步的參數清單
 */
function initStep2Lists() {
    const goalCol = document.getElementById('model-goal-col').value;
    const selectEl = document.getElementById('model-goal-col');
    if (!selectEl) return;

    // 從下拉選單取得所有可用的欄位名，並排除目標參數 (防呆 1)
    const allCols = Array.from(selectEl.options)
        .map(opt => opt.value)
        .filter(val => val !== "" && val !== goalCol);

    // 取得所有已選中的值 (跨類別)
    const controlSelected = Array.from(document.getElementById('control-selected').querySelectorAll('.list-item'))
        .map(el => el.getAttribute('data-value'));
    const stateSelected = Array.from(document.getElementById('state-selected').querySelectorAll('.list-item'))
        .map(el => el.getAttribute('data-value'));
    const allSelected = [...controlSelected, ...stateSelected];

    const containers = ['control-avail', 'state-avail'];
    containers.forEach(cid => {
        const container = document.getElementById(cid);
        if (!container) return;

        // 防呆 2: 排除目前已在任何一邊選中的項目 (互斥)
        const availableCols = allCols.filter(c => !allSelected.includes(c));

        if (availableCols.length === 0) {
            container.innerHTML = '<div style="padding: 20px; text-align: center; color: #94a3b8; font-size: 11px;">無可用參數</div>';
        } else {
            container.innerHTML = availableCols.map(col => `
                <div class="list-item" draggable="true" ondragstart="handleTrainingDragStart(event)" onclick="toggleListItem(this)" ondblclick="moveSingleItem(this)" data-value="${col}">${col}</div>
            `).join('');
        }
    });

    // 確保已選清單也有預設 UI (如果沒內容)
    ['control-selected', 'state-selected'].forEach(cid => {
        const container = document.getElementById(cid);
        if (container && container.querySelectorAll('.list-item').length === 0) {
            container.innerHTML = '<div style="padding: 20px; text-align: center; color: #94a3b8; font-size: 11px;">尚未選擇</div>';
        }
    });
}

/**
 * 切換清單項目選中狀態並顯示預覽
 */
let paramPreviewCharts = {}; // 暫存參數預覽圖表實例
let lastSelectedIndexMap = {}; // 暫存最後選取的索引 (用於 Shift 多選)

function toggleListItem(el) {
    const parent = el.parentElement;
    const containerId = parent.id || 'default-list';
    const items = Array.from(parent.querySelectorAll('.list-item'));
    const currentIndex = items.indexOf(el);

    const ev = window.event;
    const isShift = ev && ev.shiftKey;
    const isCtrl = ev && (ev.ctrlKey || ev.metaKey);

    if (isShift && lastSelectedIndexMap[containerId] !== undefined) {
        // Shift 範圍選取
        const start = Math.min(currentIndex, lastSelectedIndexMap[containerId]);
        const end = Math.max(currentIndex, lastSelectedIndexMap[containerId]);
        items.forEach((item, idx) => {
            if (idx >= start && idx <= end) {
                item.classList.add('selected');
            } else if (!isCtrl) {
                item.classList.remove('selected');
            }
        });
    } else if (isCtrl) {
        // Ctrl 切換選取
        el.classList.toggle('selected');
        if (el.classList.contains('selected')) {
            lastSelectedIndexMap[containerId] = currentIndex;
        }
    } else {
        // 單選 (清空其他)
        items.forEach(it => it.classList.remove('selected'));
        el.classList.add('selected');
        lastSelectedIndexMap[containerId] = currentIndex;
    }

    // --- ✨ 互斥選擇邏輯：按下左邊時，右邊取消；反之亦然 ---
    if (containerId.includes('avail') || containerId.includes('selected')) {
        const type = containerId.split('-')[0]; // 'control' or 'state'
        const isAvail = containerId.includes('avail');
        const otherId = isAvail ? `${type}-selected` : `${type}-avail`;
        const otherContainer = document.getElementById(otherId);

        if (otherContainer) {
            // 清除另一邊的所有選取
            otherContainer.querySelectorAll('.list-item').forEach(it => it.classList.remove('selected'));
        }

        // 更新按鈕狀態
        updateMoveButtons(type);
    }

    // 取得目前選取的數量
    const selectedCount = parent.querySelectorAll('.list-item.selected').length;

    // 如果選取數量不等於 1，則不進行繪圖
    if (selectedCount === 1) {
        const val = el.getAttribute('data-value');
        let chartCanvasId = "";
        if (containerId.includes('control')) {
            chartCanvasId = 'control-preview-chart';
        } else if (containerId.includes('state')) {
            chartCanvasId = 'state-preview-chart';
        } else if (containerId.includes('pred')) {
            chartCanvasId = 'pred-preview-chart';
        }

        if (chartCanvasId && document.getElementById(chartCanvasId)) {
            drawParamPreview(val, chartCanvasId);
        }
    } else {
        // 當選取多個或正在滑動時，清空預覽圖以符合「多個時不用繪圖」的要求
        let chartCanvasId = "";
        if (containerId.includes('control')) chartCanvasId = 'control-preview-chart';
        else if (containerId.includes('state')) chartCanvasId = 'state-preview-chart';
        else if (containerId.includes('pred')) chartCanvasId = 'pred-preview-chart';

        const canvas = document.getElementById(chartCanvasId);
        if (canvas) {
            const ctx = canvas.getContext('2d');
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            if (paramPreviewCharts[chartCanvasId]) {
                paramPreviewCharts[chartCanvasId].destroy();
                delete paramPreviewCharts[chartCanvasId];
            }
        }
    }
}

/**
 * 繪製參數分佈預覽圖
 */
async function drawParamPreview(colName, canvasId) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    // 如果先前有圖表，先銷毀
    if (paramPreviewCharts[canvasId]) {
        paramPreviewCharts[canvasId].destroy();
    }

    // 模擬或從緩存中獲取數據數據 (實作中應從後端獲取)
    // 嘗試從全域變數或 DOM 取得目前檔案名稱 (優先順序: window.currentTrainingFilename > innerText)
    const activeFile = (window.currentTrainingFilename || document.getElementById('training-active-file').innerText).trim();
    if (!activeFile || activeFile === '未選擇') return;

    try {
        const response = await fetch(`/api/get_column_data?filename=${encodeURIComponent(activeFile)}&column=${encodeURIComponent(colName)}&session_id=${SESSION_ID}`);
        const result = await response.json();

        if (result.success) {
            const ctx = canvas.getContext('2d');
            paramPreviewCharts[canvasId] = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: result.data.map((_, i) => i),
                    datasets: [{
                        label: colName,
                        data: result.data,
                        borderColor: '#3b82f6',
                        backgroundColor: 'rgba(59, 130, 246, 0.1)',
                        borderWidth: 1.5,
                        pointRadius: 0,
                        fill: true,
                        tension: 0.4
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: { mode: 'index', intersect: false }
                    },
                    scales: {
                        x: { display: false },
                        y: {
                            grid: { color: '#f1f5f9' },
                            ticks: { font: { size: 10 } }
                        }
                    }
                }
            });
        }
    } catch (err) {
        console.error("Preview draw error:", err);
    }
}

/**
 * 移動清單項目
 */
function moveItems(type, direction) {
    const availId = `${type}-avail`;
    const selectedId = `${type}-selected`;

    const sourceId = direction === 'to-selected' ? availId : selectedId;
    const targetId = direction === 'to-selected' ? selectedId : availId;

    const sourceEl = document.getElementById(sourceId);
    const targetEl = document.getElementById(targetId);
    if (!sourceEl || !targetEl) return;

    const selectedItems = Array.from(sourceEl.querySelectorAll('.list-item.selected'));
    if (selectedItems.length === 0) return;

    // 如果目標清單目前只有預設提示文字，清空它
    if (targetEl.innerHTML.includes('尚未選擇')) {
        targetEl.innerHTML = '';
    }

    selectedItems.forEach(item => {
        item.classList.remove('selected');
        item.setAttribute('ondblclick', 'moveSingleItem(this)');
        targetEl.appendChild(item);
    });

    // 重新排序已選清單
    const allItems = Array.from(targetEl.children).filter(el => el.classList.contains('list-item'));
    if (allItems.length > 1) {
        allItems.sort((a, b) => a.innerText.localeCompare(b.innerText)).forEach(node => targetEl.appendChild(node));
    }

    // ✨ 根據類型決定刷新哪個清單
    if (type === 'pred') {
        initStep3Lists();
        updateStep3UIStatus();
    } else {
        initStep2Lists();
        updateStep2UIStatus();
    }

    // 移動後重置按鈕狀態
    updateMoveButtons(type);

    // ✨ 內容異動，標記需要重新暫存
    markTrainingConfigChanged();
}

/**
 * 更新移動按鈕的可用狀態 (✨)
 */
function updateMoveButtons(type) {
    const availContainer = document.getElementById(`${type}-avail`);
    const selectedContainer = document.getElementById(`${type}-selected`);

    if (!availContainer || !selectedContainer) return;

    const hasAvailSelected = availContainer.querySelectorAll('.list-item.selected').length > 0;
    const hasSelectedSelected = selectedContainer.querySelectorAll('.list-item.selected').length > 0;

    const toSelectedBtn = document.getElementById(`${type}-to-selected-btn`);
    const toAvailBtn = document.getElementById(`${type}-to-avail-btn`);

    if (toSelectedBtn) {
        if (hasAvailSelected) toSelectedBtn.classList.remove('disabled');
        else toSelectedBtn.classList.add('disabled');
    }

    if (toAvailBtn) {
        if (hasSelectedSelected) toAvailBtn.classList.remove('disabled');
        else toAvailBtn.classList.add('disabled');
    }
}

/**
 * 快速移動單一項目 (雙擊時觸發)
 */
function moveSingleItem(el) {
    const parentId = el.parentElement.id;
    let type = parentId.split('-')[0];
    let direction = parentId.includes('avail') ? 'to-selected' : 'to-avail';

    // 清除其他選取，只移動目前這個
    el.parentElement.querySelectorAll('.list-item').forEach(it => it.classList.remove('selected'));
    el.classList.add('selected');

    moveItems(type, direction);
}

/**
 * 處理訓練清單拖曳開始
 */
function handleTrainingDragStart(ev) {
    const el = ev.target;
    const parent = el.parentElement;
    const selected = parent.querySelectorAll('.list-item.selected');

    let dragData = [];
    if (el.classList.contains('selected') && selected.length > 1) {
        // 如果拖曳的是已選中的項目之一，則拖曳所有選中的項目
        dragData = Array.from(selected).map(item => item.getAttribute('data-value'));
    } else {
        // 否則只拖曳目前這一個
        dragData = [el.getAttribute('data-value')];
        // 也順便把目前這個設為選中，以便後續邏輯一致
        parent.querySelectorAll('.list-item').forEach(it => it.classList.remove('selected'));
        el.classList.add('selected');
    }

    // 儲存來源與類型資訊
    const type = parent.id.split('-')[0];
    ev.dataTransfer.setData("training-data", JSON.stringify({
        type: type,
        values: dragData
    }));
    ev.dataTransfer.effectAllowed = "move";
}

/**
 * 處理訓練清單放下
 */
function handleTrainingDrop(ev, targetType, direction) {
    ev.preventDefault();
    const rawData = ev.dataTransfer.getData("training-data");
    if (!rawData) return;

    try {
        const data = JSON.parse(rawData);
        // 只有同類型（control/state）的項目可以在其對應的清單間移動
        if (data.type === targetType) {
            moveItems(targetType, direction);
        }
    } catch (e) {
        console.error("Drop error:", e);
    }
}
function filterList(listId, query) {
    const container = document.getElementById(listId);
    if (!container) return;

    const lowerQuery = query.toLowerCase();
    const items = container.querySelectorAll('.list-item');
    items.forEach(item => {
        const text = item.innerText.toLowerCase();
        item.style.display = text.includes(lowerQuery) ? 'block' : 'none';
    });
}

/**
 * 更新第二步完成狀態
 */
function updateStep2UIStatus() {
    const ctrlBox = document.getElementById('control-selected');
    const stateBox = document.getElementById('state-selected');
    if (!ctrlBox || !stateBox) return;

    const ctrlCount = ctrlBox.querySelectorAll('.list-item').length;
    const stateCount = stateBox.querySelectorAll('.list-item').length;

    // 額外檢查：如果容器內包含「尚未選擇」，則視為 0
    const hasCtrl = ctrlCount > 0 && !ctrlBox.innerText.includes('尚未選擇');
    const hasState = stateCount > 0 && !stateBox.innerText.includes('尚未選擇');

    const warningBar = document.getElementById('step2-validation-warning');
    const warnMsg = document.getElementById('step2-warn-msg');

    if (warningBar && warnMsg) {
        if (!hasCtrl || !hasState) {
            warningBar.style.setProperty('display', 'flex', 'important');
            const missing = [];
            if (!hasCtrl) missing.push('控制參數');
            if (!hasState) missing.push('背景參數');
            warnMsg.innerText = `尚未完成選取：${missing.join(' 及 ')}`;
        } else {
            warningBar.style.display = 'none';
        }
    }

    // --- ✨ 更新子步驟 (1, 2, 3) 的完成狀態與顏色 ---
    const subNav1 = document.getElementById('sub-nav-1');
    const subNav2 = document.getElementById('sub-nav-2');
    const subNav3 = document.getElementById('sub-nav-3');

    // 步驟 1 (演算法) 通常預設就有選，視為完成
    if (subNav1) subNav1.classList.add('done');

    // 步驟 2 (控制參數)
    if (subNav2) {
        if (hasCtrl) {
            subNav2.classList.add('done');
            subNav2.innerHTML = `<div class="dot">2</div> 控制參數 (${ctrlCount})`;
        } else {
            subNav2.classList.remove('done');
            subNav2.innerHTML = `<div class="dot">2</div> 控制參數`;
        }
    }

    // 步驟 3 (背景參數)
    if (subNav3) {
        if (hasState) {
            subNav3.classList.add('done');
            subNav3.innerHTML = `<div class="dot">3</div> 背景參數 (${stateCount})`;
        } else {
            subNav3.classList.remove('done');
            subNav3.innerHTML = `<div class="dot">3</div> 背景參數`;
        }
    }

    // --- ✨ 更新右欄標題顯示個數 ---
    const ctrlHeader = document.getElementById('control-selected-header');
    const stateHeader = document.getElementById('state-selected-header');
    if (ctrlHeader) ctrlHeader.innerText = `已選動作 (${ctrlCount})`;
    if (stateHeader) stateHeader.innerText = `已選狀態 (${stateCount})`;

    // 更新導航條(左側 STEP 02) 勾選狀態
    const navTitle = document.querySelector('#train-step-nav-2 .step-title');
    if (hasCtrl && hasState) {
        if (navTitle && !navTitle.innerText.includes('(完成)')) {
            navTitle.innerText = '最佳策略 (完成)';
            navTitle.style.color = '#10b981';
        }
    } else {
        if (navTitle) {
            navTitle.innerText = '最佳策略';
            navTitle.style.color = '#64748b';
        }
    }

    // 觸發全局完成度檢查
    if (typeof checkGlobalTrainingStatus === 'function') checkGlobalTrainingStatus();
}

/**
 * 任務類型變換 (ML / RL)
 */
function onMissionTypeChange() {
    const missionTypeEl = document.querySelector('input[name="mission-type"]:checked');
    if (!missionTypeEl) return;

    const isML = missionTypeEl.value === 'supervised';

    const fSuper = document.getElementById('fields-supervised-section');
    const fRL = document.getElementById('fields-rl-section');
    const aSuper = document.getElementById('algo-supervised-section');
    const aRL = document.getElementById('algo-rl-section');
    const step2Desc = document.getElementById('step2-desc');

    if (fSuper) fSuper.style.display = isML ? 'flex' : 'none';
    if (fRL) fRL.style.display = isML ? 'none' : 'grid';
    if (aSuper) aSuper.style.display = isML ? 'block' : 'none';
    if (aRL) aRL.style.display = isML ? 'none' : 'block';
    if (step2Desc) {
        step2Desc.innerText = isML ? '定義模型學習所需的製程參數輸入。' : '定義環境觀察狀態與可開發的動作控制集合。';
    }
}

function updateSelectedFeaturesCount() {
    const checked = document.querySelectorAll('input[name="model-feature"]:checked').length;
    const countEl = document.getElementById('selected-features-count');
    if (countEl) {
        countEl.innerText = checked;
        countEl.style.color = checked === 0 ? '#ef4444' : '#3b82f6';
    }
}

/**
 * 過濾製程參數列表
 */
function filterFeatureList(query) {
    const lowerQuery = query.toLowerCase();
    const labels = document.querySelectorAll('.feature-item-label');
    labels.forEach(label => {
        const text = label.innerText.toLowerCase();
        if (text.includes(lowerQuery)) {
            label.style.display = 'block';
        } else {
            label.style.display = 'none';
        }
    });
}

/**
 * 快速切換所有特徵欄位的選取狀態
 */
function toggleAllFeatures(checked) {
    const items = document.querySelectorAll('input[name="model-feature"]');
    items.forEach(it => { if (!it.disabled) it.checked = checked; });
    updateSelectedFeaturesCount();
}

/**
 * 啟動模型訓練邏輯
 * ✨ 現在直接調用 collectTrainingUIState，確保存入引擎的 config 本身就是一份完整的 Draft
 */
async function startModelTraining() {
    const config = collectTrainingUIState();

    if (!config.filename || config.filename === '未選擇') { alert('請先選擇數據源檔案！'); return; }
    if (!config.goal) { alert('請先在第一步定義核心目標欄位！'); switchTrainingStep(1); return; }

    // 業務校驗
    if (config.missionType === 'supervised') {
        if (config.features.length === 0) {
            alert('請至少選擇一個製程參數作為預測特徵！'); switchTrainingStep(3); return;
        }
    } else {
        if (config.actions.length === 0 || config.states.length === 0) {
            alert('請定義動作空間與環境狀態參數！'); switchTrainingStep(2); return;
        }
    }

    try {
        const response = await fetch(`/api/analysis/train?session_id=${SESSION_ID}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ config: config })
        });
        const result = await response.json();

        if (result.status === 'success') {
            alert(`🚀 啟動建模任務：\n任務編號：${result.job_id}\n\n系統已啟動訓練腳本，將自動轉跳至模型庫。`);
            switchTrainingMainTab('registry');
        } else {
            alert('訓練啟動失敗：' + result.message);
        }
    } catch (err) {
        alert('API 請求異常：' + err.message);
    }
}

// --- File Manager Logic ---
function handleMainFileUpload(input) {
    if (input.files.length > 0) {
        uploadFile(input.files[0]);
    }
}

async function uploadFile(file) {
    const statusDiv = document.getElementById('upload-status');
    statusDiv.innerText = `⏳ 正在上傳 ${file.name}...`;
    statusDiv.style.color = '#3b82f6';

    const formData = new FormData();
    formData.append('file', file);
    formData.append('session_id', SESSION_ID);

    try {
        const res = await fetch('/api/upload_file', {
            method: 'POST',
            body: formData
        });
        const data = await res.json();

        if (res.ok) {
            statusDiv.innerText = `✅ ${data.message}`;
            statusDiv.style.color = '#22c55e';
            loadFileList(); // Refresh list
        } else {
            statusDiv.innerText = `❌ 上傳失敗: ${data.detail}`;
            statusDiv.style.color = '#ef4444';
        }
    } catch (err) {
        statusDiv.innerText = `❌ 上傳錯誤: ${err.message}`;
        statusDiv.style.color = '#ef4444';
    }
}

// --- Data Management Functions ---
async function deleteFile(filename) {
    if (!confirm(`確定要刪除 ${filename} 嗎？`)) return;

    try {
        const res = await fetch(`/api/delete_file/${filename}?session_id=${SESSION_ID}`, { method: 'DELETE' });
        const data = await res.json();
        if (res.ok) {
            loadFileList(); // Refresh
        } else {
            alert(`刪除失敗: ${data.detail}`);
        }
    } catch (err) {
        alert(`錯誤: ${err.message}`);
    }
}

async function viewFile(filename) {
    try {
        const res = await fetch(`/api/view_file/${filename}?session_id=${SESSION_ID}`);
        const data = await res.json();
        if (res.ok) {
            document.getElementById('viewDataContent').innerText = data.content;
            document.getElementById('viewDataTitle').innerText = `預覽: ${filename}`;
            document.getElementById('viewDataModal').classList.add('show');
        } else {
            alert(`無法預覽: ${data.detail}`);
        }
    } catch (err) {
        alert(`錯誤: ${err.message}`);
    }
}

function closeViewModal() {
    document.getElementById('viewDataModal').classList.remove('show');
}

async function trainModel(filename) {
    // 1. 切換主視圖到訓練頁面
    switchView('training');

    // 2. 更新頂部狀態顯示
    const activeFileEl = document.getElementById('training-active-file');
    if (activeFileEl) {
        activeFileEl.innerText = filename;
    }

    // 3. 確保訓練分頁切換到「訓練新模型」子分頁
    switchTrainingMainTab('build');

    // 4. 載入檔案的 Headers/Features
    await loadTrainingMetadata(filename);
}

async function loadFileList() {
    const tbody = document.getElementById('file-list-body');
    try {
        const res = await fetch(`/api/list_files?session_id=${SESSION_ID}`);
        const data = await res.json();

        tbody.innerHTML = '';
        if (data.files.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: #94a3b8;">尚無已上傳檔案</td></tr>';
            const paginationContainer = document.getElementById('file-list-pagination');
            if (paginationContainer) paginationContainer.innerHTML = '';
            return;
        }

        // --- 分頁邏輯 ---
        const totalItems = data.files.length;
        const totalPages = Math.ceil(totalItems / FILE_LIST_PAGE_SIZE);

        // 防呆：如果當前頁碼超過總頁數
        if (fileListCurrentPage > totalPages) {
            fileListCurrentPage = Math.max(1, totalPages);
        }

        const startIdx = (fileListCurrentPage - 1) * FILE_LIST_PAGE_SIZE;
        const endIdx = startIdx + FILE_LIST_PAGE_SIZE;
        // 確保按時間倒序排列
        const sortedFiles = data.files.sort((a, b) => b.uploaded_at.localeCompare(a.uploaded_at));
        const displayedFiles = sortedFiles.slice(startIdx, endIdx);

        displayedFiles.forEach(f => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                        <td style="font-weight: bold;">${f.filename}</td>
                        <td style="color: #64748b;">${(f.size / 1024).toFixed(2)} KB</td>
                        <td style="color: #64748b;">${f.uploaded_at}</td>
                        <td>
                            <div style="display: flex; align-items: center;">
                                <button onclick="analyzeFile('${f.filename}')" class="action-btn btn-view">資料</button>
                                <button onclick="trainModel('${f.filename}')" class="action-btn btn-train">訓練</button>
                                <button onclick="deleteFile('${f.filename}')" class="action-btn btn-delete">刪除</button>
                            </div>
                        </td>
                    `;
            tbody.appendChild(tr);
        });

        // 渲染分頁控制按鈕
        renderFileListPagination(totalPages);

    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="4" style="color: red;">無法載入列表: ${err.message}</td></tr>`;
    }
}

/**
 * 渲染檔案列表分頁控制
 */
function renderFileListPagination(totalPages) {
    const container = document.getElementById('file-list-pagination');
    if (!container) return;

    if (totalPages <= 1) {
        container.innerHTML = '';
        return;
    }

    const btnStyle = "padding: 6px 14px; border: 1px solid #e2e8f0; border-radius: 6px; background: #fff; color: #64748b; font-size: 12px; font-weight: 600; cursor: pointer; transition: all 0.2s;";

    let html = '';

    // 上一頁
    html += `<button style="${btnStyle}" ${fileListCurrentPage === 1 ? 'disabled style="opacity:0.5; cursor:not-allowed;"' : `onclick="changeFileListPage(${fileListCurrentPage - 1})"`}>上一頁</button>`;

    // 頁碼
    html += `<span style="display: flex; align-items: center; gap: 5px; color: #64748b; font-size: 12px; margin: 0 10px;">
        第 ${fileListCurrentPage} / ${totalPages} 頁
    </span>`;

    // 下一頁
    html += `<button style="${btnStyle}" ${fileListCurrentPage === totalPages ? 'disabled style="opacity:0.5; cursor:not-allowed;"' : `onclick="changeFileListPage(${fileListCurrentPage + 1})"`}>下一頁</button>`;

    container.innerHTML = html;
}

/**
 * 切換檔案列表分頁
 */
function changeFileListPage(newPage) {
    fileListCurrentPage = newPage;
    loadFileList();
}

// Modal Logic
function openUploadModal() {
    document.getElementById('uploadModal').classList.add('show');
    document.getElementById('upload-status').innerText = ''; // Clear status
}

function closeUploadModal() {
    document.getElementById('uploadModal').classList.remove('show');
}

// Close modal when clicking outside
// Close modal when clicking outside
window.onclick = function (event) {
    const uploadModal = document.getElementById('uploadModal');
    const viewModal = document.getElementById('viewDataModal');
    const selectionModal = document.getElementById('selection-modal'); // Added for new modal
    if (event.target == uploadModal) {
        closeUploadModal();
    }
    if (event.target == viewModal) {
        closeViewModal();
    }
    if (event.target == document.getElementById('fileSelectorModal')) {
        closeFileSelector();
    }
    if (event.target == selectionModal) { // Added for new modal
        clearChartSelection();
    }
    if (event.target == document.getElementById('advanced-param-modal')) {
        closeAdvancedModal();
    }
}

// --- File Selector Logic ---
let selectedAnalysisFilename = null;
let tempModalFileSelection = null;
let fileSelectorPurpose = 'analysis'; // 'analysis' or 'training'

async function openFileSelector(purpose = 'analysis') {
    fileSelectorPurpose = purpose;
    const res = await fetch(`/api/list_files?session_id=${SESSION_ID}`);
    const data = await res.json();
    const list = document.getElementById('file-selector-list');
    list.innerHTML = '';
    tempModalFileSelection = null; // Reset temp selection only

    const confirmBtn = document.getElementById('btn-confirm-file');
    if (confirmBtn) {
        confirmBtn.disabled = true;
        confirmBtn.style.opacity = '0.5';
        confirmBtn.style.cursor = 'not-allowed';
    }

    if (data.files.length === 0) {
        list.innerHTML = `
            <div style="color: #94a3b8; text-align: center; padding: 30px 20px;">
                <div style="font-size: 24px; margin-bottom: 10px;">📂</div>
                <div style="font-size: 13px; margin-bottom: 20px;">尚無近期檔案</div>
                <button onclick="closeFileSelector(); switchView('files');" 
                        style="padding: 8px 16px; background: #3b82f6; color: white; border: none; border-radius: 6px; font-size: 12px; font-weight: 600; cursor: pointer; transition: all 0.2s;">
                    前往檔案管理上傳
                </button>
            </div>
        `;
    } else {
        // Sort by uploaded_at desc and take top 5
        data.files.sort((a, b) => {
            // uploaded_at format: "YYYY-MM-DD HH:MM:SS"
            // String comparison works for this format
            return b.uploaded_at.localeCompare(a.uploaded_at);
        });
        const allFiles = data.files; // 移除 .slice(0, 5)，載入所有檔案

        allFiles.forEach(f => {
            const item = document.createElement('div');
            item.className = 'file-item';
            // We use CSS class for hover, so no inline JS for hover needed if we have CSS
            // But to be safe let's add inline styles that are not covered by class or class logic
            item.style.padding = '12px 10px';
            item.style.borderBottom = '1px solid #f8fafc';
            item.style.cursor = 'pointer';
            item.style.display = 'flex';
            item.style.justifyContent = 'space-between';
            item.style.alignItems = 'center';
            item.style.borderRadius = '6px';
            item.style.transition = 'all 0.2s';

            item.onclick = () => {
                // Remove selected from others
                const allItems = list.querySelectorAll('.file-item');
                allItems.forEach(el => {
                    el.style.background = 'transparent';
                    el.dataset.selected = 'false';
                });

                // Select this one
                item.style.background = '#eff6ff';
                item.dataset.selected = 'true';
                tempModalFileSelection = f.filename; // Update temp selection

                // Enable confirm button
                if (confirmBtn) {
                    confirmBtn.disabled = false;
                    confirmBtn.style.opacity = '1';
                    confirmBtn.style.cursor = 'pointer';
                }
            };

            // Add hover effect via JS since inline styles override CSS hover
            item.onmouseenter = () => {
                if (item.dataset.selected !== 'true') item.style.background = '#f8fafc';
            };
            item.onmouseleave = () => {
                if (item.dataset.selected !== 'true') item.style.background = 'transparent';
            };

            let icon = '📄';
            if (f.filename.endsWith('.csv')) icon = '📊';
            if (f.filename.endsWith('.xlsx') || f.filename.endsWith('.xls')) icon = '📗';

            item.innerHTML = `
                        <div style="display:flex; align-items:center; gap:8px;">
                            <span style="font-size:16px;">${icon}</span>
                            <div style="display:flex; flex-direction:column;">
                                <span style="font-weight: 500; color: #334155; font-size: 14px;">${f.filename}</span>
                                <span style="font-size: 10px; color: #94a3b8;">${f.uploaded_at}</span>
                            </div>
                        </div>
                        <span style="font-size: 12px; color: #94a3b8;">${(f.size / 1024).toFixed(1)} KB</span>
                    `;
            list.appendChild(item);
        });

        // ✨ 新增：底部跳轉至檔案管理按鈕 (讓使用者可以找更舊的檔案)
        const footerLink = document.createElement('div');
        footerLink.style.padding = '15px';
        footerLink.style.textAlign = 'center';
        footerLink.style.borderTop = '1px dashed #e2e8f0';
        footerLink.style.marginTop = '10px';
        footerLink.innerHTML = `
            <button onclick="closeFileSelector(); switchView('files');" 
                    style="background: transparent; border: 1px solid #3b82f6; color: #3b82f6; padding: 6px 14px; border-radius: 6px; font-size: 11px; font-weight: 700; cursor: pointer; transition: all 0.2s;">
                &raquo; 查看所有檔案 (進入檔案管理)
            </button>
        `;
        list.appendChild(footerLink);
    }

    document.getElementById('fileSelectorModal').classList.add('show');
}

function confirmFileSelection() {
    if (tempModalFileSelection) {
        if (fileSelectorPurpose === 'training') {
            trainModel(tempModalFileSelection);
        } else {
            selectedAnalysisFilename = tempModalFileSelection; // Commit selection
            analyzeFile(selectedAnalysisFilename);
        }
        closeFileSelector();
    }
}

function closeFileSelector() {
    document.getElementById('fileSelectorModal').classList.remove('show');
}


document.addEventListener('DOMContentLoaded', () => {
    // Auto refresh file list if we are in file view (or just always load it)
    loadFileList();
    initTrainingChangeListeners(); // ✨ 新增：初始化訓練監聽

    const dropzone = document.getElementById('upload-dropzone');
    if (dropzone) {
        dropzone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropzone.classList.add('drag-over');
        });
        dropzone.addEventListener('dragleave', () => {
            dropzone.classList.remove('drag-over');
        });
        dropzone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropzone.classList.remove('drag-over');
            if (e.dataTransfer.files.length > 0) {
                const file = e.dataTransfer.files[0];
                const fileName = file.name.toLowerCase();
                if (fileName.endsWith('.csv') || fileName.endsWith('.xlsx') || fileName.endsWith('.xls')) {
                    uploadFile(file);
                } else {
                    const statusDiv = document.getElementById('upload-status');
                    statusDiv.innerText = "❌ 僅支援 CSV、Excel (.xlsx, .xls) 格式檔案";
                    statusDiv.style.color = '#ef4444';
                }
            }
        });
    }
});

// --- Analysis Logic ---
let analysisCurrentPage = 1;
let analysisFilename = '';
let originalTableData = []; // Store full page rows
let tableHeaders = [];     // Store current headers
let currentSortColumn = -1;
let currentSortOrder = 'asc';
let activeFilters = [];    // Array of {colIdx, colName, value}
let analysisTotalLines = 0; // Store total lines of current file
let visibleColumnIndices = []; // Stores indices of columns to show

async function analyzeFile(filename) {
    analysisFilename = filename;
    selectedAnalysisFilename = filename; // Sync for quickAnalysis
    originalTableData = []; // 重置數據
    activeFilters = [];

    // 1. Reset Chart Configuration and UI
    clearChartConfig();
    resetAdvancedResults(); // 清除先前的分析結果
    latestImportantFactors = []; // 清除 AI 建議


    // 2. Switch to Table View
    switchAnalysisMode('table');

    switchView('analysis');
    await loadAnalysisPage(-1); // 使用 -1 代表強製重新載入全量數據
}

async function loadAnalysisPage(page) {
    analysisCurrentPage = page;
    document.getElementById('analysis-filename').innerText = analysisFilename;
    const contentDiv = document.getElementById('analysis-content');

    // 只有第一次進入或切換檔案時才需要載入全部數據
    if (originalTableData.length === 0 || page === -1) {
        contentDiv.innerHTML = '<div style="text-align: center; color: #64748b; padding: 40px;">⏳ 正在由伺服器下載全量數據 (預計 1-3 秒)...</div>';
        try {
            // 先拿標頭
            const infoRes = await fetch(`/api/view_file/${analysisFilename}?page=1&page_size=1&session_id=${SESSION_ID}`);
            const infoData = await infoRes.json();
            analysisTotalLines = infoData.total_lines || 0;
            document.getElementById('analysis-header-count').innerText = `(總計 ${analysisTotalLines - 1} 筆數據)`;

            if (analysisFilename.toLowerCase().endsWith('.csv')) {
                tableHeaders = infoData.content.trim().split('\n')[0].split(',').map(h => h.trim());

                // Default to show all columns initially
                visibleColumnIndices = tableHeaders.map((_, i) => i);

                // 下載全量數據 (設定一個極大的 pageSize 確保拿完)
                const fullRes = await fetch(`/api/view_file/${analysisFilename}?page=1&page_size=1000000&session_id=${SESSION_ID}`);
                const fullData = await fullRes.json();
                const lines = fullData.content.trim().split('\n');
                originalTableData = lines.slice(1).map((row, idx) => {
                    const arr = row.split(',').map(c => c.trim());
                    arr.__idx = idx; // Assign persistent unique ID based on original position
                    return arr;
                });
            } else {
                // XML/其他格式維持原樣預覽
                const res = await fetch(`/api/view_file/${analysisFilename}?page=1&page_size=5000&session_id=${SESSION_ID}`);
                const data = await res.json();
                contentDiv.innerHTML = `<div class="analysis-table-container"><pre style="font-family: monospace; white-space: pre-wrap; padding: 15px;">${data.content}</pre></div>`;
                renderPagination(1, analysisTotalLines, 0);
                return;
            }
        } catch (err) {
            contentDiv.innerHTML = `<div style="color: red; text-align: center; padding: 40px;">載入失敗: ${err.message}</div>`;
            return;
        }
    }

    // 執行渲染 (前端處理分頁與過濾)
    analysisCurrentPage = page === -1 ? 1 : page;
    renderTable(tableHeaders, originalTableData, analysisCurrentPage, analysisTotalLines);
    updateFilterBar();
}

function getFilteredRows(data) {
    if (!data) return [];
    return data.filter(row => {
        // Group filters by column to handle Range OR logic
        const colFilters = {};
        activeFilters.forEach(f => {
            if (!colFilters[f.colIdx]) colFilters[f.colIdx] = [];
            colFilters[f.colIdx].push(f);
        });

        return Object.values(colFilters).every(filters => {
            const indexKeepFilters = filters.filter(f => f.type === 'indices');
            const indexExcludeFilters = filters.filter(f => f.type === 'exclude_indices');

            if (indexKeepFilters.length > 0 || indexExcludeFilters.length > 0) {
                // 🛠️ CRITICAL FALLBACK: If __idx is missing (current session), sync it now
                if (row.__idx === undefined) {
                    row.__idx = originalTableData.indexOf(row);
                }

                const origIdx = row.__idx;

                let passed = true;
                if (indexKeepFilters.length > 0) {
                    // Sequential Narrowing: Must be in ALL Keep filters (Intersection)
                    passed = indexKeepFilters.every(f => f.indices.includes(origIdx));
                }
                if (passed && indexExcludeFilters.length > 0) {
                    // Cumulative Exclusion: Must NOT be in ANY Exclude filter
                    passed = !indexExcludeFilters.some(f => f.indices.includes(origIdx));
                }
                return passed;
            }

            const rangeFilters = filters.filter(f => f.type === 'range');
            const otherFilters = filters.filter(f => f.type !== 'range');

            const passOthers = otherFilters.every(f => {
                const cellVal = row[f.colIdx];
                if (f.type === 'not_empty') return cellVal && cellVal.trim() !== '';
                if (f.type === 'exclude_range') {
                    const num = parseFloat(cellVal);
                    return isNaN(num) || num < f.min || num > f.max;
                }
                const rowVal = cellVal ? cellVal.toLowerCase() : '';
                return rowVal.includes(f.value.toLowerCase());
            });

            if (!passOthers) return false;

            if (rangeFilters.length > 0) {
                return rangeFilters.some(f => {
                    const num = parseFloat(row[f.colIdx]);
                    return !isNaN(num) && num >= f.min && num <= f.max;
                });
            }
            return true;
        });
    });
}

function renderTable(headers, rows, currentPage, totalLines) {
    // 1. 全域過濾 (針對所有下載下來的 Rows)
    let filteredRows = getFilteredRows(rows);

    // Update Header Count
    const headerCount = document.getElementById('analysis-header-count');
    if (headerCount) {
        headerCount.innerHTML = `(目前顯示: <b style="color: #3b82f6;">${filteredRows.length}</b> / 總計: ${totalLines - 1})`;
    }

    // 2. 排序
    if (currentSortColumn !== -1) {
        filteredRows.sort((a, b) => {
            let valA = a[currentSortColumn] || '';
            let valB = b[currentSortColumn] || '';
            if (!isNaN(valA) && !isNaN(valB) && valA !== "" && valB !== "") {
                return currentSortOrder === 'asc' ? Number(valA) - Number(valB) : Number(valB) - Number(valA);
            }
            return currentSortOrder === 'asc' ? valA.localeCompare(valB) : valB.localeCompare(valA);
        });
    }

    // 3. 處理顯示邏輯：一律強制分頁 (每頁 100 筆) 以優化效能
    const pageSize = 100;

    // 校正當前頁碼 (若過濾後頁數變少)
    const totalPages = Math.ceil(filteredRows.length / pageSize);
    if (currentPage > totalPages && totalPages > 0) currentPage = 1;
    if (currentPage < 1) currentPage = 1;

    const start = (currentPage - 1) * pageSize;
    const end = start + pageSize;
    const rowsToDisplay = filteredRows.slice(start, end);

    let html = '<div class="analysis-table-container">';
    html += '<table class="analysis-table">';
    html += '<thead><tr>';

    // Only render visible headers
    visibleColumnIndices.forEach(idx => {
        const h = headers[idx];
        const sortIcon = currentSortColumn === idx ? (currentSortOrder === 'asc' ? ' 🔼' : ' 🔽') : '';
        html += `<th onclick="handleSort(${idx}, '${h}')">${h}${sortIcon}</th>`;
    });
    html += '</tr></thead><tbody>';

    rowsToDisplay.forEach(row => {
        html += '<tr>';
        // Only render visible cells
        visibleColumnIndices.forEach(idx => {
            html += `<td>${row[idx] || ''}</td>`;
        });
        html += '</tr>';
    });

    if (rowsToDisplay.length === 0) {
        html += `<tr><td colspan="${headers.length}" style="text-align: center; padding: 40px; color: #94a3b8;">無符合篩選條件的數據</td></tr>`;
    }

    html += '</tbody></table></div>';
    document.getElementById('analysis-content').innerHTML = html;

    // Pass the corrected currentPage back to pagination
    renderPagination(currentPage, totalLines, filteredRows.length);
}



function updateFilterBar() {
    const bar = document.getElementById('filter-bar-area');
    if (!bar) return;
    bar.style.display = 'flex';

    const leftActions = bar.querySelector('.filter-actions-left');
    if (!leftActions) return;

    // Keep the action buttons, remove only pills
    const existingPills = leftActions.querySelectorAll('.filter-pill');
    existingPills.forEach(p => p.remove());

    activeFilters.forEach((f, idx) => {
        const pill = document.createElement('div');
        pill.className = 'filter-pill';
        let displayText = f.value;
        if (f.type === 'not_empty') displayText = '移除空值';
        if (f.type === 'range') {
            displayText = `${f.min.toFixed(2)} ~ ${f.max.toFixed(2)}`;
            pill.style.background = '#fffbeb';
            pill.style.color = '#92400e';
            pill.style.borderColor = '#fde68a';
        }
        if (f.type === 'indices') {
            displayText = `精確選取: ${f.indices.length} 筆`;
            pill.style.background = '#f0fdf4'; // Green-50
            pill.style.color = '#166534';      // Green-800
            pill.style.borderColor = '#bbf7d0'; // Green-200
        }
        if (f.type === 'exclude_indices') {
            displayText = `精確排除: ${f.indices.length} 筆`;
            pill.style.background = '#fef2f2'; // Red-50
            pill.style.color = '#991b1b';      // Red-800
            pill.style.borderColor = '#fecaca'; // Red-200
        }
        if (f.type === 'exclude_range') {
            displayText = `排除: ${f.min.toFixed(2)} ~ ${f.max.toFixed(2)}`;
            pill.style.background = '#fff1f2'; // Rose-50
            pill.style.color = '#9f1239';      // Rose-800
            pill.style.borderColor = '#fecdd3'; // Rose-200
        }

        pill.innerHTML = `
                    <span style="font-weight:600;">${f.colName}:</span> <span>${displayText}</span>
                    <span class="remove-pill" onclick="removeFilter(${idx})">&times;</span>
                `;
        const menuContainer = leftActions.querySelector('.filter-menu-container');
        leftActions.insertBefore(pill, menuContainer);
    });
}

function toggleFilterMenu(event) {
    if (event) event.stopPropagation();
    const menu = document.getElementById('filter-menu');
    const isVisible = menu.style.display === 'flex';

    if (!isVisible) {
        // Populate dropdown with current headers
        const select = document.getElementById('filter-column-select');
        select.innerHTML = tableHeaders.map((h, i) => `<option value="${i}">${h}</option>`).join('');

        menu.style.display = 'flex';
        document.getElementById('filter-value-input').focus();
        // Reset checkbox
        document.getElementById('filter-not-empty-check').checked = false;

        // Close menu if clicking outside
        const closeHandler = (e) => {
            if (!menu.contains(e.target) && !e.target.closest('.add-filter-btn')) {
                menu.style.display = 'none';
                document.removeEventListener('click', closeHandler);
            }
        };
        setTimeout(() => document.addEventListener('click', closeHandler), 10);
    } else {
        menu.style.display = 'none';
    }
}

function handleFilterKey(event) {
    if (event.key === 'Enter') {
        addFilterFromMenu();
    } else if (event.key === 'Escape') {
        toggleFilterMenu();
    }
}

function addFilterFromMenu() {
    const select = document.getElementById('filter-column-select');
    const input = document.getElementById('filter-value-input');
    const notEmptyCheck = document.getElementById('filter-not-empty-check');

    const colIdx = parseInt(select.value);
    const colName = tableHeaders[colIdx];
    const value = input.value.trim();
    const isNotEmpty = notEmptyCheck.checked;

    if (value || isNotEmpty) {
        if (isNotEmpty) {
            activeFilters.push({ colIdx, colName, value: '', type: 'not_empty' });
        } else if (value) {
            activeFilters.push({ colIdx, colName, value, type: 'text' });
        }

        input.value = ""; // Clear for next time
        notEmptyCheck.checked = false;
        document.getElementById('filter-menu').style.display = 'none';
        updateFilterBar();
        renderTable(tableHeaders, originalTableData, 1, analysisTotalLines); // Reset to page 1
    }
}

function removeFilter(idx) {
    activeFilters.splice(idx, 1);
    renderTable(tableHeaders, originalTableData, 1, analysisTotalLines);
    updateFilterBar();
    // Sync chart if in chart mode
    if (document.getElementById('chart-view-container').style.display !== 'none') {
        renderAnalysisChart();
    }
}

function resetAllFilters() {
    activeFilters = [];
    renderTable(tableHeaders, originalTableData, 1, analysisTotalLines);
    updateFilterBar();
    // Sync chart if in chart mode
    if (document.getElementById('chart-view-container').style.display !== 'none') {
        renderAnalysisChart();
    }
}

function handleSort(colIdx, headerText) {
    if (currentSortColumn === colIdx) {
        currentSortOrder = currentSortOrder === 'asc' ? 'desc' : 'asc';
    } else {
        currentSortColumn = colIdx;
        currentSortOrder = 'asc';
    }
    renderTable(tableHeaders, originalTableData, analysisCurrentPage, analysisTotalLines);
}

function renderPagination(currentPage, totalLines, filteredCount) {
    const pageSize = 100;
    // Use filteredCount for calculating pages actually displayed
    // (Use Math.max(1, ...) to ensure at least 1 page if 0 results)
    const countForCalc = filteredCount > 0 ? filteredCount : 1;
    const totalPages = Math.ceil(countForCalc / pageSize);
    const container = document.getElementById('analysis-pagination-container');

    // 1. Prepare Content Strings
    const totalText = `總計: ${filteredCount} 筆 (原始: ${totalLines - 1})`;

    // Update Top Bar Count Display (Next to filter conditions) - Always Hidden as requested
    const topBarCount = document.getElementById('filter-bar-count-display');
    if (topBarCount) topBarCount.style.display = 'none';

    // 3. Normal Pagination Case
    // Show navigation ALWAYS unless there's only 1 page
    const showNavigation = totalPages > 1;

    let html = `
                <div class="pagination-bar">
                    <div style="flex: 1;"></div>
                    
                    <div style="flex: 1; display: flex; align-items: center; justify-content: center; gap: 15px;">
                        ${showNavigation ? `
                            <button class="btn-page" onclick="loadAnalysisPage(${currentPage - 1})" ${currentPage <= 1 ? 'disabled' : ''}>上一頁</button>
                            <span class="page-info">第 ${currentPage} / ${totalPages} 頁</span>
                            <button class="btn-page" onclick="loadAnalysisPage(${currentPage + 1})" ${currentPage >= totalPages ? 'disabled' : ''}>下一頁</button>
                        ` : `<div class="page-info" style="color: #64748b;">第 1 / 1 頁</div>`}
                    </div>

                    <div style="flex: 1; font-size: 13px; color: #64748b; font-weight: 600; text-align: right;">
                        ${totalText}
                    </div>
                </div>
            `;
    container.innerHTML = html;
}

// --- Column Picker Functions ---
function openColumnPicker() {
    const modal = document.getElementById('col-picker-modal');
    const list = document.getElementById('col-picker-list');
    modal.style.display = 'flex';

    list.innerHTML = tableHeaders.map((h, i) => {
        const isChecked = visibleColumnIndices.includes(i);
        return `
                    <div class="col-item" onclick="toggleColCheckbox(event, ${i})">
                        <input type="checkbox" id="col-check-${i}" ${isChecked ? 'checked' : ''} onclick="event.stopPropagation()">
                        <label>${h}</label>
                    </div>
                `;
    }).join('');

    updateColSelectCount();
}

function closeColumnPicker() {
    document.getElementById('col-picker-modal').style.display = 'none';
}

function toggleColCheckbox(event, idx) {
    const cb = document.getElementById(`col-check-${idx}`);
    cb.checked = !cb.checked;
    updateColSelectCount();
}

function toggleAllColumns(isSelected) {
    const checkboxes = document.querySelectorAll('#col-picker-list input[type="checkbox"]');
    checkboxes.forEach(cb => {
        // If filtered, only toggle visible ones in list
        if (cb.parentElement.style.display !== 'none') {
            cb.checked = isSelected;
        }
    });
    updateColSelectCount();
}

function filterColumnList() {
    const q = document.getElementById('col-search-input').value.toLowerCase();
    const items = document.querySelectorAll('.col-item');
    items.forEach(item => {
        const text = item.querySelector('label').innerText.toLowerCase();
        item.style.display = text.includes(q) ? 'flex' : 'none';
    });
}

function updateColSelectCount() {
    const total = tableHeaders.length;
    const selected = document.querySelectorAll('#col-picker-list input[type="checkbox"]:checked').length;
    document.getElementById('col-select-count').innerText = `已選擇: ${selected} / ${total} 欄位`;
}

function applyColumnVisibility() {
    const checkboxes = document.querySelectorAll('#col-picker-list input[type="checkbox"]');
    visibleColumnIndices = [];
    checkboxes.forEach((cb, i) => {
        if (cb.checked) visibleColumnIndices.push(i);
    });

    closeColumnPicker();
    renderTable(tableHeaders, originalTableData, analysisCurrentPage, analysisTotalLines);
}

function handleChatKey(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault(); // 阻止原生換行
        sendChatMessage();
    }
}

let chatMessages = [];
let selectedFiles = [];

function handleFileSelect(input) {
    processFiles(input.files);
    input.value = ""; // 重設以支援重複選取
}

function processFiles(files) {
    const preview = document.getElementById('file-preview');
    // Ensure display is flex if files are added
    if (files.length > 0) preview.style.display = 'flex';

    Array.from(files).forEach(file => {
        const reader = new FileReader();
        const item = document.createElement('div');
        item.className = 'preview-item';

        if (file.type.startsWith('image/')) {
            reader.onload = (e) => {
                item.innerHTML = `<img src="${e.target.result}"><div class="preview-remove" onclick="removeFile('${file.name}')">×</div>`;
                selectedFiles.push({ name: file.name, type: 'image', data: e.target.result.split(',')[1] });
                // Sync after update
                syncDashboardPreviewToPopup();
            };
            reader.readAsDataURL(file);
        } else {
            reader.onload = (e) => {
                item.innerHTML = `<span>📄</span><div class="preview-remove" onclick="removeFile('${file.name}')">×</div>`;
                selectedFiles.push({ name: file.name, type: 'text', data: e.target.result });
                // Sync after update
                syncDashboardPreviewToPopup();
            };
            reader.readAsText(file);
        }
        preview.appendChild(item);
    });
}

function removeFile(name) {
    selectedFiles = selectedFiles.filter(f => f.name !== name);
    const preview = document.getElementById('file-preview');
    preview.innerHTML = "";
    // 重新渲染預覽 (簡化處理)
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
    syncDashboardPreviewToPopup();
}

async function updateDashboard() {
    try {
        const response = await fetch(`/api/history?session_id=${SESSION_ID}`);
        if (response.ok) {
            const history = await response.json();
            renderDashboardData(history);
        }
    } catch (err) { console.error(err); }
}

function renderDashboardData(history) {
    try {
        if (!history || history.length === 0) return;

        const last = history[history.length - 1];

        // 1. 更新 Console 資訊
        document.getElementById('diag-text').innerText = last.diagnosis || "穩定運行中";
        document.getElementById('sim-text').innerText = last.predicted_y_next
            ? `預計建議後效果穩定，目標值預計為: ${last.predicted_y_next.toFixed(4)}`
            : "不執行調整";

        const curInfluencers = last.current_top_influencers || [];
        const curFactors = curInfluencers.map(f => `<span class="influencer-tag">${f}</span>`).join('');
        const smInfluencers = last.smoothed_top_influencers || [];
        const smFactors = smInfluencers.map(f => `<span class="influencer-tag" style="border-color:#a855f7">${f}</span>`).join('');
        document.getElementById('factor-list').innerHTML = `<div style="margin-bottom:5px;"><small>[當前]</small> ${curFactors}</div><div><small>[平滑]</small> ${smFactors}</div>`;

        // Sync to Analysis Chart Sidebar if in analysis mode
        syncImportantChartColumns([...new Set([...curInfluencers, ...smInfluencers])]);

        // 2. 更新歷史推理日誌
        if (last.timestamp > lastLogTimestamp) {
            const logContainer = document.getElementById('reasoning-logs');
            const emptyMsg = document.getElementById('log-empty-msg');
            if (emptyMsg) emptyMsg.remove();

            const timeStr = new Date(last.timestamp * 1000).toLocaleTimeString();
            const curHtml = (last.current_top_influencers || []).map(f => `<span class="log-factor-tag">${f}</span>`).join('');
            const smHtml = (last.smoothed_top_influencers || []).map(f => `<span class="log-factor-tag" style="border-color:#a855f7; color:#7e22ce">${f}</span>`).join('');

            const logHtml = `
                        <div class="log-item">
                            <div class="log-ts">[${timeStr}]</div>
                            <div class="log-body">
                                <div class="log-diag">${last.diagnosis || '無診斷數據'}</div>
                                <div class="log-meta">
                                    影響因子: ${curHtml} | 平滑傾向: ${smHtml}
                                </div>
                            </div>
                        </div>
                    `;
            logContainer.insertAdjacentHTML('afterbegin', logHtml);
            if (logContainer.children.length > 50) logContainer.lastElementChild.remove();
            lastLogTimestamp = last.timestamp;
        }

        // 3. 更新圖表
        const actionNames = Object.keys(last.recommendations);
        const targetRange = last.target_range;
        const goalName = last.goal_name || "G_std";  // 使用 API 返回的 goal_name

        document.getElementById('status-text').innerText =
            `[數據流 #${history.length.toString().padStart(4, '0')}] ${goalName}: ${last.current_measure.toFixed(3)} | 狀態: ${last.status}`;

        // Side Panel Hook
        window.lastDashboardData = last;
        if (typeof window.renderSidePanelParams === 'function') window.renderSidePanelParams(last.current_measure, last);

        const wrapper = document.getElementById('charts-wrapper');
        actionNames.forEach(name => {
            const safeId = `chart-${name.replace(/[^a-zA-Z0-9]/g, '-')}`;
            if (!charts[name]) {
                const div = document.createElement('div');
                div.className = 'chart-container';
                div.innerHTML = `<canvas id="${safeId}" height="100"></canvas>`;
                wrapper.appendChild(div);
                charts[name] = createChart(safeId, name, targetRange, goalName);
            }
        });

        const startIndex = Math.max(0, history.length - WINDOW_SIZE);
        const recentHistory = history.slice(startIndex);
        const labels = Array.from({ length: recentHistory.length }, (_, i) => startIndex + i);
        const nextIdx = history.length;

        actionNames.forEach(name => {
            const chart = charts[name];
            const kappaData = recentHistory.map(d => d.current_measure);
            const actionData = recentHistory.map(d => d.recommendations[name].current);

            const predData = recentHistory.map((d, i) => {
                const globalIndex = startIndex + i;
                if (globalIndex === 0) return null;
                const prevRecord = history[globalIndex - 1];
                return prevRecord ? prevRecord.predicted_y_next : null;
            });

            const pastSuggestions = recentHistory.slice(0, -1).map((d, i) => {
                return { x: startIndex + i + 1, y: d.recommendations[name].suggested_next };
            });

            chart.data.labels = labels;
            chart.data.datasets[0].data = kappaData;
            chart.data.datasets[1].data = actionData;
            chart.data.datasets[2].data = pastSuggestions;
            chart.data.datasets[4].data = predData;

            const lastRec = last.recommendations[name];
            if (last.status !== 'HOLD') {
                chart.data.datasets[3].data = [{ x: nextIdx, y: lastRec.suggested_next }];
                chart.data.datasets[3].pointStyle = 'triangle';
                chart.data.datasets[3].rotation = lastRec.suggested_delta > 0 ? 0 : 180;
                chart.data.datasets[3].backgroundColor = lastRec.suggested_delta > 0 ? '#38bdf8' : '#22c55e';

                chart.options.plugins.annotation.annotations.vLine = {
                    type: 'line', xMin: nextIdx, xMax: nextIdx,
                    borderColor: '#cbd5e1', borderDash: [4, 4], borderWidth: 1
                };
                chart.options.plugins.annotation.annotations.hLine = {
                    type: 'line', yScaleID: 'yAction', yMin: lastRec.suggested_next, yMax: lastRec.suggested_next,
                    borderColor: '#a855f7', borderDash: [4, 4], borderWidth: 1
                };
            } else {
                chart.data.datasets[3].data = [];
                chart.options.plugins.annotation.annotations.vLine = { display: false };
                chart.options.plugins.annotation.annotations.hLine = { display: false };
            }

            chart.options.scales.x.min = startIndex;
            chart.options.scales.x.max = startIndex + WINDOW_SIZE + 5;
            chart.update('none');
        });
    } catch (err) { console.error(err); }
}

function createChart(canvasId, actionName, deadzone, goalName) {
    const ctx = document.getElementById(canvasId).getContext('2d');
    const displayGoalName = goalName || "G_std";

    // 計算 Y 軸範圍
    let yMin, yMax;
    if (yAxisMode === 'manual' && yAxisManualMin !== null && yAxisManualMax !== null) {
        // 手動模式: 使用使用者設定的範圍
        yMin = yAxisManualMin;
        yMax = yAxisManualMax;
    } else {
        // 自動模式: 根據 deadzone (LSL/USL) 計算,預留 10% 緩衝
        yMin = deadzone[0] * 0.9;
        yMax = deadzone[1] * 1.1;
    }

    return new Chart(ctx, {
        type: 'line',
        data: {
            datasets: [
                { label: `實際 ${displayGoalName}`, data: [], borderColor: '#ef4444', yAxisID: 'yKappa', borderWidth: 2.5, pointRadius: 0, order: 1 },
                { label: '控制項真實路徑', data: [], borderColor: '#1e293b', yAxisID: 'yAction', borderWidth: 2.5, pointRadius: 0, order: 2, stepped: false, tension: 0 },
                { label: '歷史建議', data: [], type: 'scatter', yAxisID: 'yAction', pointStyle: 'triangle', backgroundColor: 'rgba(148, 163, 184, 0.5)', pointRadius: 5, borderWidth: 0, order: 3 },
                { label: '當前建議', data: [], type: 'scatter', yAxisID: 'yAction', pointRadius: 10, pointBorderWidth: 2, order: 0 },
                { label: '物理預測', data: [], borderColor: '#3b82f6', yAxisID: 'yKappa', borderWidth: 1.5, borderDash: [5, 5], pointRadius: 0, order: 4 }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            scales: {
                x: { type: 'linear', display: true, grid: { color: '#f1f5f9' }, beginAtZero: false },
                yKappa: {
                    position: 'left',
                    min: yMin,
                    max: yMax,
                    title: { display: true, text: displayGoalName, color: '#ef4444' }
                },
                yAction: { position: 'right', grid: { display: false }, title: { display: true, text: actionName }, beginAtZero: false }
            },
            plugins: {
                legend: { position: 'top', align: 'end', labels: { boxWidth: 10, font: { size: 10 } } },
                annotation: {
                    annotations: {
                        deadzone: { type: 'box', yScaleID: 'yKappa', yMin: deadzone[0], yMax: deadzone[1], backgroundColor: 'rgba(34, 197, 94, 0.08)', borderWidth: 0, z: -10 }
                    }
                }
            }
        }
    });
}



async function generateAIReport() {
    const btn = document.getElementById('btn-report');
    const content = document.getElementById('ai-report-content');
    btn.disabled = true; btn.innerText = "⏳ 專家分析中...(後台)";

    try {
        const response = await fetch(`/api/ai/report?session_id=${SESSION_ID}`);
        const data = await response.json();

        let reportText = "";

        if (data.job_id) {
            // New async flow
            const result = await pollAIResult(data.job_id, 'report');
            reportText = result.report;
        } else {
            // Legacy synchronous flow
            reportText = data.report;
        }

        reportText = reportText || "AI 未能返回數據。";

        chatMessages = [
            { role: "user", content: "請根據最近的製程數據提供診斷報告。" },
            { role: "assistant", content: reportText }
        ];

        content.innerHTML = `<div class="ai-bubble chat-bubble">${marked.parse(reportText)}</div>`;
        setTimeout(() => { content.scrollTop = content.scrollHeight; }, 100);

        // Sync Initial Report
        if (dashboardPopupWindow && !dashboardPopupWindow.closed) {
            const popupContent = dashboardPopupWindow.document.getElementById('ai-report-content');
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

        if (dashboardPopupWindow && !dashboardPopupWindow.closed) {
            const popupContent = dashboardPopupWindow.document.getElementById('ai-report-content');
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

async function sendChatMessage() {
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
    document.getElementById('file-preview').style.display = 'none'; // Ensure hide
    // syncDashboardPreviewToPopup(); // Disabled to prevent main window freeze

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
    userBubble.innerHTML = bubbleHtml;
    content.appendChild(userBubble);
    // syncDashboardToPopup(null, true); // Disabled to prevent main window freeze

    while (content.children.length > 50) content.removeChild(content.firstChild);
    content.scrollTop = content.scrollHeight;

    selectedFiles = []; // 清空已選擇檔案

    const thinkingId = 'thinking-' + Date.now();
    const thinkingBubble = document.createElement('div');
    thinkingBubble.id = thinkingId;
    thinkingBubble.className = "ai-bubble chat-bubble";
    thinkingBubble.innerHTML = `<i>AI 專家正在思考中...</i>`;
    content.appendChild(thinkingBubble);
    // syncDashboardToPopup(null, false); // Disabled to prevent main window freeze
    content.scrollTop = content.scrollHeight;

    try {
        if (chatMessages.length > 10) chatMessages = chatMessages.slice(-10);
        // Pass session_id in body
        // Pass session_id in body
        const response = await fetch('/api/ai/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ messages: chatMessages, session_id: SESSION_ID })
        });
        const data = await response.json();

        let reply = "";

        if (data.job_id) {
            // New async flow
            const result = await pollAIResult(data.job_id, 'chat');
            reply = result.reply;
        } else {
            reply = data.reply;
        }

        const loader = document.getElementById(thinkingId);
        if (loader) loader.remove();

        if (dashboardPopupWindow && !dashboardPopupWindow.closed) {
            const pLoader = dashboardPopupWindow.document.getElementById(thinkingId);
            if (pLoader) pLoader.remove();
        }

        if (reply) {
            chatMessages.push({ role: "assistant", content: reply });

            // 1. 建立訊息泡泡容器
            const bubble = document.createElement('div');
            bubble.className = "ai-bubble chat-bubble";
            bubble.innerHTML = marked.parse(reply);
            bubble.innerHTML = marked.parse(reply);
            content.appendChild(bubble);
            // syncDashboardToPopup(null, false); // Removed premature sync

            // 2. 解析並渲染嵌入式圖表
            const codeBlocks = bubble.querySelectorAll('pre code');
            const renderPromises = [];
            codeBlocks.forEach(block => {
                try {
                    const config = JSON.parse(block.innerText);
                    if (config.type === 'chart') {
                        // 隱藏原始 JSON
                        block.parentElement.style.display = 'none';

                        // 創建圖表容器 (加固視覺穩定性)
                        const chartDiv = document.createElement('div');
                        chartDiv.style.margin = "15px 0";
                        chartDiv.style.background = "#fff";
                        chartDiv.style.borderRadius = "8px";
                        chartDiv.style.padding = "12px";
                        chartDiv.style.border = "1px solid #e2e8f0";
                        chartDiv.style.minHeight = "210px"; // 防止容器坍塌
                        chartDiv.style.boxShadow = "0 2px 4px rgba(0,0,0,0.05)";
                        chartDiv.innerHTML = `<canvas height="200"></canvas>`;
                        // 重要：將配置存入 DOM，以便獨立視窗可以讀取並重新渲染 (解決隱藏視窗無法繪圖的問題)
                        chartDiv.dataset.chartConfig = JSON.stringify(config);
                        block.parentElement.after(chartDiv);

                        // 異步渲染確保 DOM 佈局已完成
                        const p = new Promise(resolve => {
                            setTimeout(() => {
                                const ctx = chartDiv.querySelector('canvas').getContext('2d');
                                if (!config.datasets || !config.datasets[0]) {
                                    resolve();
                                    return;
                                }

                                // 智慧型數據容錯與意圖辨識
                                let chartType = config.chart_type || 'line';
                                let chartData = { datasets: [] };

                                // 關鍵修正：若有兩組數據但無標籤，或明確要求 scatter，則強制進入散布圖模式
                                const hasTwoDatasets = config.datasets && config.datasets.length >= 2;
                                const missingLabels = !config.labels || config.labels.length === 0;

                                // 修正邏輯：只有當明確指定 scatter，或未指定類型且符合特徵時才切換
                                // 若 config.chart_type 為 'line'，即使有兩組數據也不應該當作 scatter
                                const isExplicitLine = config.chart_type === 'line';
                                const autoDetectScatter = !config.chart_type && (hasTwoDatasets && missingLabels);

                                if (chartType === 'scatter' || (!isExplicitLine && autoDetectScatter)) {

                                    chartType = 'scatter';
                                    const d1 = config.datasets[0].data;
                                    const d2 = config.datasets[1].data;
                                    // 確保長度一致且過濾非數值
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

                                    // 線圖模式：處理標籤補全
                                    chartType = 'line';
                                    let labels = config.labels || [];
                                    if (labels.length === 0 && config.datasets[0].data) {
                                        const dataLen = config.datasets[0].data.length;
                                        for (let i = dataLen - 1; i >= 0; i--) labels.push(`T-${i}`);
                                    }
                                    chartData.labels = labels;

                                    // --- Smart Axis Assignment (智慧軸分配) ---
                                    // 解決: 當有多個變數且數級差異巨大時 (e.g. 1.5 vs 1200)，避免全部擠在 y1 造成某一條變直線
                                    // 邏輯: 
                                    // 1. 計算每個 dataset 的平均值 magnitude (log10)
                                    // 2. 將 Dataset 0 (主角) 設為基準 (Left Axis 'y')
                                    // 3. 其他 dataset 若 magnitude 與 Dataset 0 接近 (< 1 order)，則併入 Left 'y'
                                    // 4. 否則放入 Right 'y1'
                                    // 5. 若 Right 'y1' 裡面也有 magnitude 差異過大的... 只能取其一或顯示警告 (目前簡化為共用 y1)

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
                                                // 第一筆固定左軸
                                                return {
                                                    ...ds,
                                                    yAxisID: 'y',
                                                    borderColor: '#7e22ce',
                                                    backgroundColor: 'rgba(126, 34, 206, 0.1)',
                                                    tension: 0.35, fill: true, pointRadius: 3
                                                };
                                            }

                                            // 判斷是否適合併入左軸
                                            const myMag = getMag(ds.data || []);
                                            const diff = Math.abs(myMag - baseMag);

                                            // 判斷: 數量級差距小於 1 (10倍內) 且 baseMag 不是 0
                                            const useLeft = (diff < 1.0) || (baseMag === 0 && myMag === 0);
                                            const axisID = useLeft ? 'y' : 'y1';

                                            // 顏色輪詢
                                            const colors = ['#38bdf8', '#ef4444', '#f59e0b', '#10b981'];
                                            const color = colors[(idx - 1) % colors.length];

                                            return {
                                                ...ds,
                                                yAxisID: axisID,
                                                borderColor: color,
                                                backgroundColor: color.replace(')', ', 0.1)').replace('rgb', 'rgba'),
                                                tension: 0.35, fill: false, pointRadius: 3 // 副軸通常不填滿以防遮擋
                                            };
                                        });
                                    }
                                }

                                const chartOptions = {
                                    responsive: true,
                                    maintainAspectRatio: false,
                                    animation: {
                                        onComplete: () => {
                                            resolve(); // Verify animation complete before syncing
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

                                // Store FULL processed config for popup re-rendering
                                chartDiv.dataset.processedConfig = JSON.stringify(finalChartConfig);

                                // Resolver moved to onComplete
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

        if (dashboardPopupWindow && !dashboardPopupWindow.closed) {
            const pLoader = dashboardPopupWindow.document.getElementById(thinkingId);
            if (pLoader) pLoader.innerHTML = message;
        }
    }
}

async function clearHistory() {
    if (!confirm("確定要清除所有監控紀錄並重設模擬進度嗎？")) return;
    // Pass session_id
    await fetch('/api/clear', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: SESSION_ID })
    });
    location.reload();
}


// --- Anti-Throttling Web Worker Timer (Dual Core + Background Fetch) ---
// 使用 Web Worker 同時驅動 [Dashboard 更新] 和 [AI 輪詢]
// 並且將數據獲取 (Fetch) 移至 Worker 執行，徹底解決背景頁面網絡節流問題
const timerWorkerScript = `
    let dashboardInterval = null;
    let pollInterval = null;

    self.onmessage = async function(e) {
        const data = e.data;

        // 1. Dashboard 更新 (Worker Fetch)
        if (data.cmd === 'start_dashboard') {
            const sessionId = data.sessionId;
            if (dashboardInterval) clearInterval(dashboardInterval);
            dashboardInterval = setInterval(async () => {
                try {
                    // Worker Fetch: 擁有獨立網絡優先級
                    // Use absolute path just in case, or relative is fine (same origin)
                    const response = await fetch('/api/history?session_id=' + sessionId);
                    if (response.ok) {
                        const history = await response.json();
                        self.postMessage({ type: 'dashboard_data', history: history });
                    }
                } catch(err) { /* ignore */ }
            }, 1500);
        } else if (data.cmd === 'stop_dashboard') {
            if (dashboardInterval) clearInterval(dashboardInterval);
        }
        // 2. AI 輪詢 (Worker 驅動)
        else if (data.cmd === 'start_polling') {
            if (pollInterval) clearInterval(pollInterval);
            pollInterval = setInterval(() => {
                self.postMessage({ type: 'poll_tick', id: data.id, jobType: data.jobType });
            }, 1000);
        }
        else if (data.cmd === 'stop_polling') {
            if (pollInterval) clearInterval(pollInterval);
        }
    };
`;
const timerBlob = new Blob([timerWorkerScript], { type: 'application/javascript' });
const timerWorker = new Worker(URL.createObjectURL(timerBlob));

// 註冊 AI 輪詢回調
const aiPollingCallbacks = {};

// [Debug] Add Heartbeat UI
const hb = document.createElement('div');
hb.id = 'worker-heartbeat';
hb.style.cssText = "position:fixed; bottom:5px; right:5px; padding:4px 8px; background:#111; color:#fff; font-size:10px; border-radius:12px; z-index:99999; font-family:monospace; pointer-events:none; border: 1px solid #333;";
hb.innerHTML = "FW-Worker: <span id='hb-status' style='color:#ef4444'>INIT</span>";
if (document.body) document.body.appendChild(hb);
else window.addEventListener('load', () => document.body.appendChild(hb));

timerWorker.onmessage = async function (e) {
    const data = e.data;

    // Heartbeat Pulse (Green Blink)
    const statusSpan = document.getElementById('hb-status');
    if (statusSpan && (data.type === 'dashboard_data' || data.type === 'poll_tick')) {
        statusSpan.innerText = "ACTIVE";
        statusSpan.style.color = "#22c55e"; // Green
        statusSpan.style.textShadow = "0 0 5px #22c55e";
        setTimeout(() => {
            if (statusSpan) {
                statusSpan.style.color = "#15803d"; // Dim Green
                statusSpan.style.textShadow = "none";
            }
        }, 200);
    }

    // A. 接收 Dashboard 數據 (from Worker Fetch)
    if (data.type === 'dashboard_data') {
        renderDashboardData(data.history);
    }
    // B. AI 輪詢觸發
    else if (data.type === 'poll_tick') {
        const callback = aiPollingCallbacks[data.id];
        if (callback) {
            await callback();
        }
    }
};

// 啟動 Worker (傳入 SessionID)
timerWorker.postMessage({ cmd: 'start_dashboard', sessionId: SESSION_ID });

// --- Helper for AI Polling (Worker Driven) ---
async function pollAIResult(jobId, type) {
    const startTime = Date.now();
    const timeout = 45000;

    return new Promise((resolve, reject) => {
        // 定義單次檢查邏輯
        const checkStatus = async () => {
            try {
                const response = await fetch(`/api/ai/${type}_status/${jobId}`);
                if (!response.ok) {
                    const legacyResp = await fetch(`/api/ai_${type}_status/${jobId}`);
                    if (!legacyResp.ok) throw new Error("Status check failed");
                }
                const data = await response.json();

                if (data.status === 'completed') {
                    // 成功：停止 Worker 輪詢
                    timerWorker.postMessage({ cmd: 'stop_polling' });
                    delete aiPollingCallbacks[jobId];
                    resolve(data);
                } else if (data.status === 'error') {
                    timerWorker.postMessage({ cmd: 'stop_polling' });
                    delete aiPollingCallbacks[jobId];
                    reject(new Error(data.error));
                } else if (Date.now() - startTime > timeout) {
                    timerWorker.postMessage({ cmd: 'stop_polling' });
                    delete aiPollingCallbacks[jobId];
                    reject(new Error("Request timed out (45s)"));
                }
            } catch (err) {
                console.error("Polling error:", err);
            }
        };

        // 註冊回調並啟動 Worker 輪詢
        aiPollingCallbacks[jobId] = checkStatus;
        timerWorker.postMessage({ cmd: 'start_polling', id: jobId, jobType: type });
    });
}

/* --- Charting Logic --- */
let analysisChart = null;
let chartConfig = { x: null, y: null, y2: null, type: 'scatter' };
let selectionMode = false;
let isSelecting = false;
let selectionStart = { x: 0, y: 0 };
let currentChartSelectionRange = null;

function toggleSelectionMode() {
    selectionMode = !selectionMode;
    const btn = document.getElementById('btn-selection-mode');
    if (selectionMode) {
        btn.innerText = '🖱️ 框選模式: 開啟';
        btn.style.background = '#eff6ff';
        btn.style.color = '#3b82f6';
        btn.style.borderColor = '#3b82f6';
    } else {
        btn.innerText = '🖱️ 框選模式: 關閉';
        btn.style.background = '#fff';
        btn.style.color = '#475569';
        btn.style.borderColor = '#cbd5e1';
    }
}

function setChartType(type) {
    chartConfig.type = type;

    // Clear correlation when changing any parameter
    const resDiv = document.getElementById('correlation-result');
    if (resDiv) resDiv.innerHTML = '';

    // Handle Selection Restriction: Only allow for 'scatter'
    const selectionBtn = document.getElementById('btn-selection-mode');
    if (type !== 'scatter') {
        selectionMode = false;
        if (selectionBtn) selectionBtn.style.display = 'none';
        clearChartSelection(); // Also clear any existing highlight/toolbar
    } else {
        if (selectionBtn) selectionBtn.style.display = 'block';
        // Reset toggle button UI to "OFF"
        const btn = document.getElementById('btn-selection-mode');
        btn.innerText = '🖱️ 框選模式: 關閉';
        btn.style.background = '#fff';
        btn.style.color = '#475569';
        btn.style.borderColor = '#cbd5e1';
    }

    // Update UI buttons
    document.querySelectorAll('.chart-type-btn').forEach(btn => btn.classList.remove('active'));
    document.getElementById(`btn - chart - ${type} `).classList.add('active');

    // Re-render if possible
    if (chartConfig.x && (chartConfig.y || chartConfig.y2)) {
        renderAnalysisChart();
    }
}

function filterChartColumns(query) {
    const chips = document.querySelectorAll('.draggable-chip');
    const q = query.toLowerCase();
    chips.forEach(chip => {
        if (chip.innerText.toLowerCase().includes(q)) {
            chip.style.display = 'block';
        } else {
            chip.style.display = 'none';
        }
    });
}

function switchAnalysisMode(mode) {
    const btnTable = document.getElementById('btn-mode-table');
    const btnChart = document.getElementById('btn-mode-chart');
    const viewTable = document.getElementById('analysis-table-view');
    const viewChart = document.getElementById('analysis-chart-view');
    const filterBar = document.getElementById('filter-bar-area'); // Keep filters visible!

    if (mode === 'table') {
        viewTable.style.display = 'block';
        viewChart.style.display = 'none';
        btnTable.style.background = '#fff';
        btnTable.style.color = '#3b82f6';
        btnTable.style.boxShadow = '0 1px 2px rgba(0,0,0,0.1)';
        btnChart.style.background = 'transparent';
        btnChart.style.color = '#64748b';
        btnChart.style.boxShadow = 'none';
    } else {
        viewTable.style.display = 'none';
        viewChart.style.display = 'flex';
        btnChart.style.background = '#fff';
        btnChart.style.color = '#7e22ce';
        btnChart.style.boxShadow = '0 1px 2px rgba(0,0,0,0.1)';
        btnTable.style.background = 'transparent';
        btnTable.style.color = '#64748b';
        btnTable.style.boxShadow = 'none';
        initChartColumns();
        // Ensure chart is fresh and resized
        setTimeout(() => {
            renderAnalysisChart();
            if (analysisChart) analysisChart.resize();
        }, 50);
    }
}

async function saveFilteredData() {
    if (!selectedAnalysisFilename) {
        alert("請先選擇要分析的檔案");
        return;
    }

    // Get filtered data using helper
    const filteredRows = getFilteredRows(originalTableData);

    if (filteredRows.length === 0) {
        alert("目前沒有過濾後的數據可以儲存");
        return;
    }

    const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    const defaultName = `${selectedAnalysisFilename.replace('.csv', '')}_filtered_${timestamp}.csv`;
    const newName = prompt("請輸入新檔名:", defaultName);

    if (!newName) return;

    try {
        const response = await fetch(`/ api / save_filtered_file ? session_id = ${SESSION_ID} `, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                filename: newName,
                headers: tableHeaders,
                rows: filteredRows
            })
        });

        const result = await response.json();
        if (result.status === 'success') {
            alert(result.message);
            // If we are in file manager, reload it
            loadFileList();
        } else {
            alert("儲存失敗: " + result.detail);
        }
    } catch (err) {
        console.error("Save Error:", err);
        alert("連線後端失敗");
    }
}

async function quickAnalysis() {
    if (!selectedAnalysisFilename) {
        alert("請先選擇要分析的檔案");
        openFileSelector();
        return;
    }

    // 1. 取得過濾後的數據
    const filteredRows = getFilteredRows(originalTableData);
    if (filteredRows.length === 0) {
        alert("目前沒有過濾後的數據可以分析");
        return;
    }

    // 移除 500 筆限制，根據使用者要求傳送全量過濾後的數據
    const limitedRows = filteredRows;

    // 2. 顯示載入狀態
    const btn = event.currentTarget;
    const originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '⏳ 全量空值分析中...';

    try {
        // 3. 呼叫後端 API 生成摘要
        const response = await fetch(`/api/analysis/quick_analysis?session_id=${SESSION_ID}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                filename: selectedAnalysisFilename,
                headers: tableHeaders,
                rows: limitedRows,
                filters: activeFilters
            })
        });

        const result = await response.json();
        if (result.status === 'success') {
            // 4. 打開圖表 AI 助手
            const win = document.getElementById('chart-ai-assistant-window');
            if (!win.classList.contains('active')) {
                toggleChartAssistant();
            }

            // 5. 將摘要發送到 AI 聊天
            const input = document.getElementById('chart-chat-input');
            const summaryPrompt = `${result.summary} \n\n🤖 ** AI 指令 **: 請用極其簡短、精煉的 2~3 句話總結這份數據的關鍵發現或核心建議。`;

            // 模擬輸入並發送
            input.value = summaryPrompt;
            sendChartChatMessage();
        } else {
            alert("分析失敗: " + result.detail);
        }
    } catch (err) {
        console.error("Quick Analysis Error:", err);
        alert("連線分析服務失敗");
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalText;
    }
}

// Add keyboard shortcut: Shift + S to save filtered data
document.addEventListener('keydown', (e) => {
    // Only trigger if in analysis view and Shift+S is pressed
    if (e.shiftKey && e.key.toLowerCase() === 's' && document.getElementById('view-analysis').style.display === 'block') {
        e.preventDefault();
        saveFilteredData();
    }
});

// Add keyboard shortcut: Escape to cancel selection mode
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        // 1. Prioritize closing Modals
        const modals = [
            { id: 'uploadModal', close: closeUploadModal },
            { id: 'fileSelectorModal', close: closeFileSelector },
            { id: 'viewDataModal', close: closeViewModal },
            { id: 'advanced-param-modal', close: closeAdvancedModal },
            { id: 'col-picker-modal', close: closeColumnPicker }
        ];

        for (const m of modals) {
            const el = document.getElementById(m.id);
            if (el && (el.style.display === 'flex' || el.classList.contains('show'))) {
                m.close();
                return; // Stop propagation (don't clear selection if modal was closed)
            }
        }

        // 2. Clear Chart Selection / Mode
        if (currentChartSelectionRange) {
            // User request: Clear selection BUT stay in selection mode
            clearChartSelection();
        } else if (selectionMode) {
            // Only exit mode if no selection exists
            toggleSelectionMode();
        }
    }
});

function updateChartSourceInfo(fCount) {
    // Use current parameter if provided, otherwise calculate
    const filteredCount = fCount !== undefined ? fCount : getFilteredRows(originalTableData).length;

    const infoOverlay = document.getElementById('chart-info-overlay');
    if (chartConfig.x && (chartConfig.y || chartConfig.y2)) {
        infoOverlay.innerText = `📊 繪圖數據來源: ${filteredCount} 筆(已套用篩選)`;
    } else {
        infoOverlay.innerText = `尚未繪圖(可用數據: ${filteredCount} 筆)`;
    }
}

// Analysis state
let advancedAnalysisResults = null;

function initChartColumns() {
    const container = document.getElementById('chart-column-source');
    if (!container) return;
    container.innerHTML = ''; // Clear

    // Update UI Button area based on state
    const btnContainer = document.getElementById('adv-selection-container');
    if (advancedAnalysisResults) {
        const { target } = advancedAnalysisResults;
        btnContainer.innerHTML = `
            <div style="background: #eff6ff; border: 1px solid #93c5fd; border-radius: 6px; padding: 10px; margin-bottom: 8px;">
                <div style="font-size: 11px; font-weight: bold; color: #1e40af; margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center;">
                    <span>🎯 分析目標: ${target}</span>
                    <button onclick="resetAdvancedResults()" style="background:#f1f5f9; border:none; color:#64748b; cursor:pointer; font-size:12px; padding:2px 6px; border-radius:4px; font-weight:bold;">清除</button>
                </div>
                <button onclick="openAdvancedModal()" style="width: 100%; padding: 5px; border: 1px solid #93c5fd; border-radius: 4px; background: #fff; color: #2563eb; font-size: 11px; cursor: pointer; font-weight: bold;">重新分析</button>
            </div>
        `;
    } else {
        btnContainer.innerHTML = `
            <button onclick="openAdvancedModal()" class="btn-adv-selection">
                <span>🔍</span> 進階挑選(分析影響力)
            </button>
        `;
    }

    let orderedHeaders = [...tableHeaders];
    let specialStatus = {};

    if (advancedAnalysisResults) {
        const { results, target } = advancedAnalysisResults;
        const sortedInfluencers = results.map(r => r.col);

        let finalOrder = [];
        // 1. Target First (PER USER REQUEST)
        if (orderedHeaders.includes(target)) {
            finalOrder.push(target);
            specialStatus[target] = { type: 'target' };
        }

        // 2. Ranked Influencers
        sortedInfluencers.forEach(col => {
            if (orderedHeaders.includes(col) && !finalOrder.includes(col)) {
                finalOrder.push(col);
                const resultItem = results.find(r => r.col === col);
                const score = resultItem.score < 0.001 ? resultItem.score.toExponential(2) : resultItem.score.toFixed(3);
                specialStatus[col] = { type: 'influencer', score: score };
            }
        });

        // 3. The rest
        orderedHeaders.forEach(h => {
            if (!finalOrder.includes(h)) finalOrder.push(h);
        });
        orderedHeaders = finalOrder;

    } else if (latestImportantFactors && latestImportantFactors.length > 0) {
        // AI Suggestions Ordering
        let finalOrder = [...latestImportantFactors.filter(f => orderedHeaders.includes(f))];
        orderedHeaders.forEach(h => {
            if (!finalOrder.includes(h)) finalOrder.push(h);
        });
        latestImportantFactors.forEach(f => {
            if (orderedHeaders.includes(f)) specialStatus[f] = { type: 'ai' };
        });
        orderedHeaders = finalOrder;
    }

    // Update global order for cycling
    currentChartColumnOrder = orderedHeaders;

    orderedHeaders.forEach(header => {
        const status = specialStatus[header];
        const chip = document.createElement('div');
        chip.className = 'draggable-chip';
        chip.draggable = true;
        chip.dataset.header = header; // Store header in dataset for multi-drag

        if (status) {
            if (status.type === 'target') {
                chip.style.borderColor = '#2563eb';
                chip.style.background = '#dbeafe';
                chip.style.color = '#1e40af';
                chip.style.fontWeight = 'bold';
                chip.innerHTML = `<div style="display:flex; justify-content:space-between; align-items:center; width:100%; pointer-events:none;"><span>${header}</span><span style="font-size:10px; background: rgba(37, 99, 235, 0.2); padding: 1px 4px; border-radius: 4px;">🎯 目標</span></div>`;
            } else if (status.type === 'influencer') {
                chip.style.borderColor = '#93c5fd';
                chip.style.background = '#eff6ff';
                chip.style.color = '#1e40af';
                const absScore = Math.abs(status.score);
                const displayScore = absScore < 0.001 && absScore > 0 ? Number(status.score).toExponential(2) : Number(status.score).toFixed(3);
                chip.innerHTML = `<div style="display:flex; justify-content:space-between; align-items:center; width:100%; pointer-events:none;"><span>${header}</span><span style="font-size:10px; background: rgba(37, 99, 235, 0.1); padding: 1px 4px; border-radius: 4px; font-family: 'Roboto Mono', monospace;">${displayScore}</span></div>`;
            } else if (status.type === 'ai') {
                chip.style.borderColor = '#d8b4fe';
                chip.style.background = '#faf5ff';
                chip.style.color = '#7e22ce';
                chip.innerHTML = `<div style="display:flex; justify-content:space-between; align-items:center; width:100%; pointer-events:none;"><span>${header}</span><span style="font-size:10px; opacity:0.8;">✨</span></div>`;
            }
        } else {
            chip.innerText = header;
        }

        chip.style.textAlign = 'left';

        // --- ✨ Multi-Select for Chips ---
        chip.onclick = (e) => {
            const isShift = e.shiftKey;
            const isCtrl = e.ctrlKey || e.metaKey;
            const allChips = Array.from(container.querySelectorAll('.draggable-chip'));
            const idx = allChips.indexOf(chip);
            const cid = 'chart-column-source';

            if (isShift && lastSelectedIndexMap[cid] !== undefined) {
                const start = Math.min(idx, lastSelectedIndexMap[cid]);
                const end = Math.max(idx, lastSelectedIndexMap[cid]);
                allChips.forEach((c, i) => {
                    if (i >= start && i <= end) c.classList.add('selected-chip');
                    else if (!isCtrl) c.classList.remove('selected-chip');
                });
            } else if (isCtrl) {
                chip.classList.toggle('selected-chip');
                if (chip.classList.contains('selected-chip')) lastSelectedIndexMap[cid] = idx;
            } else {
                allChips.forEach(c => c.classList.remove('selected-chip'));
                chip.classList.add('selected-chip');
                lastSelectedIndexMap[cid] = idx;
            }
        };

        chip.ondragstart = (e) => {
            const selected = container.querySelectorAll('.selected-chip');
            let dragData = [];
            // If dragging a selected one, drag ALL selected ones
            if (chip.classList.contains('selected-chip') && selected.length > 1) {
                dragData = Array.from(selected).map(c => c.dataset.header);
            } else {
                dragData = [header];
            }
            e.dataTransfer.setData("text", JSON.stringify(dragData));
            e.dataTransfer.effectAllowed = "move";
            chip.classList.add('dragging');
        };
        chip.ondragend = () => chip.classList.remove('dragging');
        container.appendChild(chip);
    });
}

// --- NEW: Advanced Parameter Selection Functions ---

function openAdvancedModal() {
    if (!tableHeaders || tableHeaders.length === 0) {
        alert("請先讀取一個數據檔案");
        return;
    }
    const modal = document.getElementById('advanced-param-modal');
    const select = document.getElementById('adv-target-select');

    // Populate target candidates (all numeric headers)
    select.innerHTML = tableHeaders.map(h => `<option value="${h}">${h}</option>`).join('');

    // Try to pre-select something plausible if not already selected
    if (chartConfig.y) {
        select.value = chartConfig.y;
    }

    modal.classList.add('show');
    document.getElementById('adv-status').innerText = "";
    document.getElementById('adv-btn-text').innerText = "🚀 開始分析";
}

function closeAdvancedModal() {
    document.getElementById('advanced-param-modal').classList.remove('show');
}

async function runAdvancedAnalysis() {
    const target = document.getElementById('adv-target-select').value;
    const algo = document.querySelector('input[name="adv-algo"]:checked').value;
    const status = document.getElementById('adv-status');
    const btnText = document.getElementById('adv-btn-text');

    if (!analysisFilename) {
        alert("找不到當前分析檔案名稱，請確認已讀取檔案。");
        return;
    }

    status.innerText = "⏳ AI 模型分析中，請稍候...";
    status.style.color = "#a855f7";
    btnText.innerText = "分析中...";

    try {
        const res = await fetch(`/api/advanced_analysis?session_id=${SESSION_ID}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                filename: analysisFilename,
                target_column: target,
                algorithm: algo
            })
        });

        const data = await res.json();
        if (res.ok && data.status === 'success') {
            status.innerText = `✅ 分析完成(目標: ${target})`;
            status.style.color = "#16a34a";

            // Display results
            applyAdvancedResults(data.results, target, algo);

            setTimeout(() => closeAdvancedModal(), 800);
        } else {
            status.innerText = "❌ 分析失敗: " + (data.detail || "未知錯誤");
            status.style.color = "#ef4444";
            btnText.innerText = "重試";
        }
    } catch (err) {
        console.error(err);
        status.innerText = "❌ 連線後端時發生錯誤";
        status.style.color = "#ef4444";
        btnText.innerText = "重試";
    }
}

function applyAdvancedResults(results, target, algo) {
    advancedAnalysisResults = { results, target, algo };
    initChartColumns();
}

function resetAdvancedResults() {
    advancedAnalysisResults = null;
    initChartColumns();
}

function syncImportantChartColumns(factors) {
    if (factors && factors.length > 0) {
        latestImportantFactors = factors;
    }
    initChartColumns();
}



function allowDrop(ev) {
    ev.preventDefault();
    const dropzone = ev.target.closest('.axis-dropzone');
    if (dropzone) dropzone.classList.add('drag-over');
}

// Global dragleave to clear styling
document.addEventListener('dragleave', (e) => {
    if (e.target.classList && e.target.classList.contains('axis-dropzone')) {
        e.target.classList.remove('drag-over');
    }
}, true);

function handleDrop(ev, axis) {
    ev.preventDefault();
    const dropzone = ev.target.closest('.axis-dropzone');
    if (!dropzone) return;

    dropzone.classList.remove('drag-over');

    // --- ✨ Support Multiple Columns ---
    const rawData = ev.dataTransfer.getData("text");
    let colNames = [];
    try {
        if (rawData.startsWith('[') && rawData.endsWith(']')) {
            colNames = JSON.parse(rawData);
        } else {
            colNames = [rawData];
        }
    } catch (e) {
        colNames = [rawData];
    }

    if (colNames.length > 0) {
        // Clear correlation when changing parameters
        const resDiv = document.getElementById('correlation-result');
        if (resDiv) resDiv.innerHTML = '';

        // If multiple dragged, distribute them if possible
        const targetCols = colNames.filter(c => c && c.trim());
        if (targetCols.length === 0) return;

        // Primary assignment
        chartConfig[axis] = targetCols[0];

        // If secondary exists and axis was 'y', automatically fill 'y2'
        if (targetCols.length > 1 && axis === 'y') {
            chartConfig['y2'] = targetCols[1];
            updateDropzoneUI('y2', targetCols[1]);
        }

        updateDropzoneUI(axis, targetCols[0]);

        tryUpdateChart();
        updateChartSourceInfo();
    }
}

function updateDropzoneUI(axis, colName) {
    const dropzone = document.getElementById('drop-' + axis);
    if (!dropzone) return;

    const isVertical = axis === 'y' || axis === 'y2';
    const style = isVertical ? 'writing-mode: vertical-rl; text-orientation: mixed;' : '';

    let content = '';
    if (isVertical) {
        content = `
            <div style="display:flex; flex-direction:column; align-items:center; gap:4px; height:100%; justify-content:center;">
                <span onclick="event.stopPropagation(); cycleChartAxis('${axis}', -1)" style="cursor:pointer; font-size:12px; color:#94a3b8; padding:2px;">▲</span>
                <span style="color: #2563eb; font-weight: bold; ${style} white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-height:80%;">${colName}</span>
                <span onclick="event.stopPropagation(); cycleChartAxis('${axis}', 1)" style="cursor:pointer; font-size:12px; color:#94a3b8; padding:2px;">▼</span>
            </div>
            <span style="position:absolute; top:2px; right:2px; font-size:9px; cursor:pointer; color:#ef4444;" onclick="event.stopPropagation(); resetAxis('${axis}')">✕</span>
        `;
    } else {
        content = `
            <div style="display:flex; align-items:center; gap:4px; width:100%; justify-content:center;">
                <span style="color: #2563eb; font-weight: bold; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${colName}</span>
                <span style="font-size:10px; cursor:pointer; color:#ef4444;" onclick="event.stopPropagation(); resetAxis('${axis}')">✕</span>
            </div>
        `;
    }

    dropzone.innerHTML = content;
    dropzone.style.position = 'relative';
    dropzone.classList.add('filled');
}

// ✨ NEW: Quick Axis Cycling (Next/Previous Column)
function cycleChartAxis(axis, offset) {
    if (!chartConfig[axis]) return;

    // Disable X-axis cycling as per user request
    if (axis === 'x') return;

    // Use visual order if available, otherwise fallback to default tableHeaders
    const visibleHeaders = (currentChartColumnOrder && currentChartColumnOrder.length > 0)
        ? currentChartColumnOrder
        : tableHeaders;

    const currentName = chartConfig[axis];
    const currentIndex = visibleHeaders.indexOf(currentName);

    if (currentIndex === -1) return;

    // Calculate new index with wrap-around
    let newIndex = (currentIndex + offset);
    if (newIndex < 0) newIndex = visibleHeaders.length - 1;
    if (newIndex >= visibleHeaders.length) newIndex = 0;

    const nextCol = visibleHeaders[newIndex];
    chartConfig[axis] = nextCol;

    // Clear correlation results
    const resDiv = document.getElementById('correlation-result');
    if (resDiv) resDiv.innerHTML = '';

    // Update UI
    const dropzone = document.getElementById('drop-' + axis);
    if (dropzone) {
        const isVertical = axis === 'y' || axis === 'y2';
        const style = isVertical ? 'writing-mode: vertical-rl; text-orientation: mixed;' : '';

        let content = '';
        if (isVertical) {
            content = `
                <div style="display:flex; flex-direction:column; align-items:center; gap:4px; height:100%; justify-content:center;">
                    <span onclick="event.stopPropagation(); cycleChartAxis('${axis}', -1)" style="cursor:pointer; font-size:12px; color:#94a3b8; padding:2px;">▲</span>
                    <span style="color: #2563eb; font-weight: bold; ${style} white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-height:80%;">${nextCol}</span>
                    <span onclick="event.stopPropagation(); cycleChartAxis('${axis}', 1)" style="cursor:pointer; font-size:12px; color:#94a3b8; padding:2px;">▼</span>
                </div>
                <span style="position:absolute; top:2px; right:2px; font-size:9px; cursor:pointer; color:#ef4444;" onclick="event.stopPropagation(); resetAxis('${axis}')">✕</span>
            `;
        } else {
            content = `
                <div style="display:flex; align-items:center; gap:4px; width:100%; justify-content:center;">
                    <span style="color: #2563eb; font-weight: bold; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${nextCol}</span>
                    <span style="font-size:10px; cursor:pointer; color:#ef4444;" onclick="event.stopPropagation(); resetAxis('${axis}')">✕</span>
                </div>
            `;
        }

        dropzone.innerHTML = content;
        dropzone.style.position = 'relative'; // Ensure absolute close btn works
    }

    // Sync Highlight in Side List
    if (typeof syncSideListHighlight === 'function') {
        syncSideListHighlight(nextCol);
    } else {
        // Find highlightable chips in the source container
        const container = document.getElementById('chart-column-source');
        if (container) {
            const chips = container.querySelectorAll('.draggable-chip');
            chips.forEach(chip => {
                chip.style.outline = 'none';
                chip.style.boxShadow = 'none';
            });
            for (const chip of chips) {
                if (chip.textContent.includes(nextCol)) {
                    chip.style.outline = '2px solid #a855f7';
                    chip.style.boxShadow = '0 0 8px rgba(168, 85, 247, 0.4)';
                    chip.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                    break;
                }
            }
        }
    }

    tryUpdateChart();
    updateChartSourceInfo();
}

// Fix malformed HTML string in clearChartConfig
function clearChartConfig() {
    chartConfig = { x: null, y: null, y2: null, type: 'scatter' };
    clearChartSelection(); // Also clear selection UI
    if (analysisChart) {
        analysisChart.destroy();
        analysisChart = null;
    }

    const resDiv = document.getElementById('correlation-result');
    if (resDiv) resDiv.innerHTML = '';

    // Reset dropzone buttons
    const axes = ['x', 'y', 'y2'];
    axes.forEach(axis => {
        const dropzone = document.getElementById('drop-' + axis);
        if (dropzone) {
            dropzone.classList.remove('filled');
            const isVertical = axis === 'y' || axis === 'y2';
            const phStyle = isVertical ? 'writing-mode: vertical-rl;' : '';
            const phText = axis === 'y2' ? '(選填)' : '拖曳至此';
            dropzone.innerHTML = `<span class="placeholder" style="${phStyle}">${phText}</span>`;
        }
    });

    // Clear source columns list
    const sourceContainer = document.getElementById('chart-column-source');
    if (sourceContainer) sourceContainer.innerHTML = '';
}

function resetAxis(axis) {
    chartConfig[axis] = null;

    // Clear correlation when removing parameters
    const resDiv = document.getElementById('correlation-result');
    if (resDiv) resDiv.innerHTML = '';

    const dropzone = document.getElementById('drop-' + axis);
    dropzone.classList.remove('filled');
    const isVertical = axis === 'y' || axis === 'y2';
    const phStyle = isVertical ? 'writing-mode: vertical-rl;' : '';
    const phText = axis === 'y2' ? '(選填)' : '拖曳至此'; // ✨ FIX: Show "(選填)" for optional Y2 axis
    dropzone.innerHTML = `<span class="placeholder" style="${phStyle}">${phText}</span>`;
    if (analysisChart) {
        analysisChart.destroy();
        analysisChart = null;
    }
    updateChartSourceInfo();
    tryUpdateChart(); // ✨ FIX: Re-render chart if other axes still exist (e.g., Y2 remains after removing Y1)
}

function tryUpdateChart() {
    if (chartConfig.x && (chartConfig.y || chartConfig.y2)) {
        renderAnalysisChart();
    }
}

function renderAnalysisChart() {
    const canvas = document.getElementById('analysis-chart-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    if (analysisChart) analysisChart.destroy();

    // Prepare Data Indices
    const xIdx = tableHeaders.indexOf(chartConfig.x);
    const yIdx = tableHeaders.indexOf(chartConfig.y);
    const y2Idx = tableHeaders.indexOf(chartConfig.y2);

    // Re-apply current filters using helper
    let sourceRows = getFilteredRows(originalTableData);

    if (sourceRows.length === 0) {
        return;
    }

    const chartType = chartConfig.type;
    const datasets = [];
    let labels = null; // For categorical axis
    let isNumericX = false;

    // --- DATA PREPARATION STRATEGY ---

    if (chartType === 'boxplot') {
        isNumericX = false;
        const groups = {};

        sourceRows.forEach(row => {
            let xVal = row[xIdx];
            let yVal1 = yIdx !== -1 ? row[yIdx] : null;
            let yVal2 = y2Idx !== -1 ? row[y2Idx] : null;

            if (xVal === null || xVal === undefined) return;
            const key = String(xVal);

            if (yVal1 !== null && !isNaN(parseFloat(yVal1))) yVal1 = parseFloat(yVal1);
            else yVal1 = null;

            if (yVal2 !== null && !isNaN(parseFloat(yVal2))) yVal2 = parseFloat(yVal2);
            else yVal2 = null;

            if (!groups[key]) groups[key] = { y1: [], y2: [] };
            if (yVal1 !== null) groups[key].y1.push(yVal1);
            if (yVal2 !== null) groups[key].y2.push(yVal2);
        });

        const sortedKeys = Object.keys(groups).sort((a, b) => {
            const nav = parseFloat(a);
            const nbv = parseFloat(b);
            if (!isNaN(nav) && !isNaN(nbv)) return nav - nbv;
            return a.localeCompare(b);
        });

        labels = sortedKeys;

        // 🛠️ Feature: If only 1 category, pad with empty labels to center it
        if (labels.length === 1) {
            labels = ['', labels[0], ' '];
        }

        if (yIdx !== -1) {
            const data1 = sortedKeys.map(k => groups[k].y1);
            // If padded, data must align with index 1
            const boxData1 = labels.length === 3 ? [null, data1[0], null] : data1;
            datasets.push({
                label: chartConfig.y,
                data: boxData1,
                backgroundColor: 'rgba(124, 58, 237, 0.5)',
                borderColor: '#7c3aed',
                borderWidth: 1,
                outlierColor: '#999999',
                padding: 10,
                itemRadius: 2,
                meanRadius: 0,
                yAxisID: 'y'
            });
        }

        if (y2Idx !== -1) {
            const data2 = sortedKeys.map(k => groups[k].y2);
            const boxData2 = labels.length === 3 ? [null, data2[0], null] : data2;
            datasets.push({
                label: chartConfig.y2,
                data: boxData2,
                backgroundColor: 'rgba(6, 182, 212, 0.5)',
                borderColor: '#06b6d4',
                borderWidth: 1,
                outlierColor: '#999999',
                itemRadius: 2,
                meanRadius: 0,
                yAxisID: 'y1'
            });
        }

        updateChartSourceInfo(sourceRows.length);
    } else {
        // SCATTER or LINE Logic
        const maxPoints = 5000;
        const step = Math.ceil(sourceRows.length / maxPoints);

        let dataPoints1 = [];
        let dataPoints2 = [];

        for (let i = 0; i < sourceRows.length; i += step) {
            const row = sourceRows[i];
            let xVal = row[xIdx];
            let yVal1 = yIdx !== -1 ? row[yIdx] : null;
            let yVal2 = y2Idx !== -1 ? row[y2Idx] : null;

            if (!isNaN(parseFloat(xVal))) xVal = parseFloat(xVal);
            if (yVal1 !== null && !isNaN(parseFloat(yVal1))) yVal1 = parseFloat(yVal1);
            if (yVal2 !== null && !isNaN(parseFloat(yVal2))) yVal2 = parseFloat(yVal2);

            if (yVal1 !== null) dataPoints1.push({ x: xVal, y: yVal1, _origIdx: row.__idx });
            if (yVal2 !== null) dataPoints2.push({ x: xVal, y: yVal2, _origIdx: row.__idx });
        }

        updateChartSourceInfo(sourceRows.length);

        isNumericX = dataPoints1.length > 0 && dataPoints1.every(p => typeof p.x === 'number' && !isNaN(p.x));

        if (isNumericX) {
            if (chartType === 'line') {
                dataPoints1.sort((a, b) => a.x - b.x);
                dataPoints2.sort((a, b) => a.x - b.x);
            }
        } else {
            const uniqueX = [...new Set([
                ...dataPoints1.map(p => String(p.x)),
                ...dataPoints2.map(p => String(p.x))
            ])];

            uniqueX.sort((a, b) => {
                const na = parseFloat(a), nb = parseFloat(b);
                if (!isNaN(na) && !isNaN(nb)) return na - nb;
                return a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' });
            });

            labels = uniqueX;

            // 🛠️ Feature: If only 1 category, pad with empty labels to center it
            if (labels.length === 1) {
                labels = ['', labels[0], ' '];
                // Adjust data points to align with the new labels (index 1)
                dataPoints1.forEach(p => p.x = labels[1]);
                dataPoints2.forEach(p => p.x = labels[1]);
            }
        }

        if (yIdx !== -1) {
            datasets.push({
                label: chartConfig.y,
                data: dataPoints1,
                yAxisID: 'y',
                borderColor: '#7c3aed',
                backgroundColor: 'rgba(124, 58, 237, 0.5)',
                pointRadius: chartType === 'scatter' ? 4 : 2,
                showLine: chartType === 'line',
                tension: 0.1
            });
        }

        if (y2Idx !== -1) {
            datasets.push({
                label: chartConfig.y2,
                data: dataPoints2,
                yAxisID: 'y1',
                borderColor: '#06b6d4',
                backgroundColor: 'rgba(6, 182, 212, 0.5)',
                pointRadius: chartType === 'scatter' ? 4 : 2,
                showLine: chartType === 'line',
                tension: 0.1
            });
        }
    }

    const options = {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
            x: {
                type: isNumericX ? 'linear' : 'category',
                title: { display: true, text: chartConfig.x },
                grid: { color: '#f1f5f9' },
                beginAtZero: false
            },
            y: {
                title: { display: true, text: chartConfig.y },
                type: 'linear',
                display: true,
                position: 'left',
                grid: { color: '#f1f5f9' },
                beginAtZero: false
            },
            y1: {
                title: { display: true, text: chartConfig.y2 },
                type: 'linear',
                display: datasets.some(d => d.yAxisID === 'y1'),
                position: 'right',
                grid: { drawOnChartArea: false },
                beginAtZero: false
            }
        },
        plugins: {
            legend: { position: 'top' },
            tooltip: {
                mode: 'index',
                intersect: false,
            }
        }
    };

    analysisChart = new Chart(ctx, {
        type: chartType,
        data: {
            labels: labels,
            datasets: datasets
        },
        options: options
    });

    // [New Code] Inject Data to AI
    if (typeof updateChartAnalysisData === 'function') {
        // Calculate basic stats for AI context
        const summary = {
            rowCount: sourceRows.length,
            totalRows: originalTableData.length,
            isFiltered: sourceRows.length < originalTableData.length,
            x_range: isNumericX && dataPoints1.length > 0 ?
                [Math.min(...dataPoints1.map(p => p.x)), Math.max(...dataPoints1.map(p => p.x))] : null
        };

        // Update the global config with summary
        chartConfig.data_summary = summary;

        // Send to backend
        updateChartAnalysisData(chartConfig);
    }
}

// Global Chart Selection Handlers (Add once)
document.addEventListener('DOMContentLoaded', () => {
    const canvas = document.getElementById('analysis-chart-canvas');
    if (!canvas) return;

    canvas.onmousedown = (e) => {
        if (!selectionMode || !analysisChart) return;
        isSelecting = true;
        const rect = canvas.getBoundingClientRect();
        selectionStart = { x: e.clientX - rect.left, y: e.clientY - rect.top };

        const box = document.getElementById('selection-box');
        box.style.display = 'block';
        box.style.left = selectionStart.x + 'px';
        box.style.top = selectionStart.y + 'px';
        box.style.width = '0';
        box.style.height = '0';
    };

    window.addEventListener('mousemove', (e) => {
        if (!isSelecting) return;
        const canvas = document.getElementById('analysis-chart-canvas');
        const rect = canvas.getBoundingClientRect();
        const currentX = e.clientX - rect.left;
        const currentY = e.clientY - rect.top;

        const box = document.getElementById('selection-box');
        const left = Math.min(selectionStart.x, currentX);
        const top = Math.min(selectionStart.y, currentY);
        const width = Math.abs(currentX - selectionStart.x);
        const height = Math.abs(currentY - selectionStart.y);

        box.style.left = left + 'px';
        box.style.top = top + 'px';
        box.style.width = width + 'px';
        box.style.height = height + 'px';
    });

    window.addEventListener('mouseup', (e) => {
        if (!isSelecting) return;
        isSelecting = false;
        const box = document.getElementById('selection-box');
        box.style.display = 'none';

        if (!analysisChart) return;

        const canvas = document.getElementById('analysis-chart-canvas');
        const rect = canvas.getBoundingClientRect();
        const endX = e.clientX - rect.left;
        const endY = e.clientY - rect.top;

        const x1 = selectionStart.x;
        const y1 = selectionStart.y;
        const x2 = endX;
        const y2 = endY;

        // Min/Max Pixels
        const pXMin = Math.min(x1, x2);
        const pXMax = Math.max(x1, x2);
        const pYMin = Math.min(y1, y2);
        const pYMax = Math.max(y1, y2);

        // Convert Pixels to Data Values
        const xScale = analysisChart.scales.x;
        const yScale = analysisChart.scales.y;

        const vXMin = xScale.getValueForPixel(pXMin);
        const vXMax = xScale.getValueForPixel(pXMax);
        const vYMin = yScale.getValueForPixel(pYMax);
        const vYMax = yScale.getValueForPixel(pYMin);

        if (Math.abs(pXMax - pXMin) > 5 || Math.abs(pYMax - pYMin) > 5) {
            // Clear correlation results when selection starts
            const resDiv = document.getElementById('correlation-result');
            if (resDiv) resDiv.innerHTML = '';

            currentChartSelectionRange = {
                x: chartConfig.x,
                y: chartConfig.y,
                xMin: Math.min(vXMin, vXMax),
                xMax: Math.max(vXMin, vXMax),
                yMin: Math.min(vYMin, vYMax),
                yMax: Math.max(vYMin, vYMax)
            };
            updateSelectionUI();
            highlightPointsInChart();
        }
    });
});

function updateSelectionUI() {
    const modal = document.getElementById('selection-modal');
    const countText = document.getElementById('selection-count-text');

    if (!currentChartSelectionRange) {
        modal.style.display = 'none';
        return;
    }

    const xIdx = tableHeaders.indexOf(currentChartSelectionRange.x);
    const yIdx = tableHeaders.indexOf(currentChartSelectionRange.y);

    const sourceRows = getFilteredRows(originalTableData);
    const selected = sourceRows.filter(row => {
        const vx = parseFloat(row[xIdx]);
        const vy = parseFloat(row[yIdx]);
        if (isNaN(vx) || isNaN(vy)) return false;
        return vx >= currentChartSelectionRange.xMin && vx <= currentChartSelectionRange.xMax &&
            vy >= currentChartSelectionRange.yMin && vy <= currentChartSelectionRange.yMax;
    });

    modal.style.display = 'flex';
    countText.innerHTML = `📍 已選取 <b style="color:#7c3aed; font-size:16px;">${selected.length}</b> 筆`;
}

function highlightPointsInChart() {
    if (!analysisChart || !currentChartSelectionRange) return;

    analysisChart.data.datasets.forEach((ds, dsIdx) => {
        const pointColors = [];
        const pointSizes = [];

        ds.data.forEach(p => {
            const isSelected = p.x >= currentChartSelectionRange.xMin && p.x <= currentChartSelectionRange.xMax &&
                p.y >= currentChartSelectionRange.yMin && p.y <= currentChartSelectionRange.yMax;

            if (isSelected) {
                pointColors.push('#fbbf24'); // Bright Gold
                pointSizes.push(8);          // Larger
            } else {
                pointColors.push(dsIdx === 0 ? 'rgba(124, 58, 237, 0.3)' : 'rgba(6, 182, 212, 0.3)');
                pointSizes.push(4);          // Default
            }
        });

        ds.pointBackgroundColor = pointColors;
        ds.pointBorderColor = pointColors.map((c, i) => pointSizes[i] === 8 ? '#92400e' : c);
        ds.pointRadius = pointSizes;
        ds.pointHoverRadius = pointSizes.map(s => s + 2);
    });
    analysisChart.update();
}

function clearChartSelection() {
    currentChartSelectionRange = null;
    document.getElementById('selection-modal').style.display = 'none';
    if (analysisChart) {
        analysisChart.data.datasets.forEach((ds, dsIdx) => {
            const baseColor = dsIdx === 0 ? 'rgba(124, 58, 237, 0.5)' : 'rgba(6, 182, 212, 0.5)';
            ds.pointBackgroundColor = baseColor;
            ds.pointBorderColor = baseColor;
            ds.pointRadius = chartConfig.type === 'scatter' ? 4 : 2;
            ds.pointHoverRadius = ds.pointRadius + 2;
        });
        analysisChart.update();
    }
}

function applySelectionAsFilter(mode) {
    if (!currentChartSelectionRange || !analysisChart) return;

    // Collect precise indices from the current chart instance
    const selectedIndices = [];
    analysisChart.data.datasets.forEach(ds => {
        ds.data.forEach(p => {
            if (p.x >= currentChartSelectionRange.xMin && p.x <= currentChartSelectionRange.xMax &&
                p.y >= currentChartSelectionRange.yMin && p.y <= currentChartSelectionRange.yMax) {
                if (p._origIdx !== undefined) selectedIndices.push(p._origIdx);
            }
        });
    });

    if (selectedIndices.length === 0) return;

    const filterType = mode === 'keep' ? 'indices' : 'exclude_indices';
    const uniqueIndices = [...new Set(selectedIndices)];

    activeFilters.push({
        colIdx: 'index_meta', // Special marker
        colName: '圖表選取',
        type: filterType,
        indices: uniqueIndices,
        value: `Selected ${uniqueIndices.length} `
    });

    renderTable(tableHeaders, originalTableData, 1, analysisTotalLines);
    updateFilterBar();
    clearChartSelection();

    // Corrected ID check: analysis-chart-view
    if (document.getElementById('analysis-chart-view').style.display !== 'none') {
        renderAnalysisChart();
    }
}

function calculateCorrelation() {
    // ✨ NEW: Toggle behavior - if results already exist, clear them
    const resultDiv = document.getElementById('correlation-result');
    if (resultDiv && resultDiv.innerHTML.trim() !== '') {
        resultDiv.innerHTML = '';
        return; // Exit early after clearing
    }

    if (!chartConfig.x || (!chartConfig.y && !chartConfig.y2)) {
        alert("請先配置 X 軸與至少一個 Y 軸欄位 (Y1 或 Y2)");
        return;
    }

    // Get filtered data using helper
    const sourceRows = getFilteredRows(originalTableData);

    if (sourceRows.length < 2) {
        alert("數據太少，無法計算相關係數");
        return;
    }

    const xIdx = tableHeaders.indexOf(chartConfig.x);
    const y1Idx = tableHeaders.indexOf(chartConfig.y);
    const y2Idx = tableHeaders.indexOf(chartConfig.y2);

    function getPearson(idx1, idx2) {
        if (idx1 === -1 || idx2 === -1) return null;
        let x = [], y = [];
        sourceRows.forEach(row => {
            const v1 = parseFloat(row[idx1]);
            const v2 = parseFloat(row[idx2]);
            if (!isNaN(v1) && !isNaN(v2)) {
                x.push(v1);
                y.push(v2);
            }
        });
        if (x.length < 2) return null;
        const n = x.length;
        const sumX = x.reduce((a, b) => a + b, 0);
        const sumY = y.reduce((a, b) => a + b, 0);
        const sumXY = x.reduce((a, b, i) => a + b * y[i], 0);
        const sumX2 = x.reduce((a, b) => a + b * b, 0);
        const sumY2 = y.reduce((a, b) => a + b * b, 0);
        const num = n * sumXY - sumX * sumY;
        const den = Math.sqrt((n * sumX2 - sumX * sumX) * (n * sumY2 - sumY * sumY));
        if (den === 0) return 0;
        return num / den;
    }

    const r1 = getPearson(xIdx, y1Idx);
    const r2 = getPearson(xIdx, y2Idx);

    // resultDiv already declared at function start
    let html = "";
    let found = false;
    if (r1 !== null) {
        html += `<div style="margin-bottom: 2px;">• <b>${chartConfig.x}</b> vs <b>${chartConfig.y}</b>: <span style="color: #3b82f6; font-weight: 700;">${r1.toFixed(4)}</span></div>`;
        found = true;
    }
    if (r2 !== null) {
        html += `<div>• <b>${chartConfig.x}</b> vs <b>${chartConfig.y2}</b>: <span style="color: #06b6d4; font-weight: 700;">${r2.toFixed(4)}</span></div>`;
        found = true;
    }

    if (!found) {
        resultDiv.innerHTML = '<span style="color: #94a3b8; font-size: 12px;">(無法計算：需為數值欄位)</span>';
    } else {
        resultDiv.innerHTML = html;
    }
}

// Global Keyboard Listener for Axis Cycling (Left/Right -> X, Up/Down -> Y)
document.addEventListener('keydown', (event) => {
    // Only trigger if no input is focused
    const tag = document.activeElement.tagName.toLowerCase();
    const isInput = tag === 'input' || tag === 'textarea' || document.activeElement.isContentEditable;

    // Only in Analysis > Chart view
    const chartView = document.getElementById('analysis-chart-view');
    const isChartView = chartView && chartView.style.display !== 'none';

    if (!isInput && isChartView) {
        switch (event.key) {
            case 'ArrowLeft':
                event.preventDefault(); // Prevent scrolling
                cycleChartAxis('x', -1);
                break;
            case 'ArrowRight':
                event.preventDefault();
                cycleChartAxis('x', 1);
                break;
            case 'ArrowUp':
                event.preventDefault();
                if (event.shiftKey) {
                    cycleChartAxis('y2', -1);
                } else {
                    cycleChartAxis('y', -1);
                }
                break;
            case 'ArrowDown':
                event.preventDefault();
                if (event.shiftKey) {
                    cycleChartAxis('y2', 1);
                } else {
                    cycleChartAxis('y', 1);
                }
                break;
        }
    }
});

// Chart Type Switcher Function
function setChartType(type) {
    if (!chartConfig) {
        chartConfig = { x: null, y: null, y2: null, type: 'scatter' };
    }

    chartConfig.type = type;

    // Update button states
    document.querySelectorAll('.chart-type-btn').forEach(btn => btn.classList.remove('active'));
    const targetBtn = document.getElementById(`btn-chart-${type}`);
    if (targetBtn) targetBtn.classList.add('active');

    // Handle Selection Mode
    const selectionBtn = document.getElementById('btn-selection-mode');
    if (type !== 'scatter') {
        // Disable Selection Mode for Line/Boxplot
        if (selectionBtn) {
            // Check if currently enabled (if text indicates "ON")
            if (selectionBtn.innerText.includes('開啟')) {
                if (typeof toggleSelectionMode === 'function') {
                    toggleSelectionMode();
                } else {
                    // Fallback to click if function not found
                    selectionBtn.click();
                }
            }

            selectionBtn.disabled = true;
            selectionBtn.style.opacity = '0.5';
            selectionBtn.style.cursor = 'not-allowed';
            selectionBtn.title = '此圖表類型不支援框選模式';
        }
    } else {
        // Re-enable for Scatter
        if (selectionBtn) {
            selectionBtn.disabled = false;
            selectionBtn.style.opacity = '1';
            selectionBtn.style.cursor = 'pointer';
            selectionBtn.title = '';
        }
    }

    // Re-render chart if axes are configured
    if (chartConfig.x && (chartConfig.y || chartConfig.y2)) {
        renderAnalysisChart();
    }
}
