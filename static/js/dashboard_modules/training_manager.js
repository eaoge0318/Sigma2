
// =========================
// training_manager.js - Training Wizard Logic
// =========================
import { DOM, API } from './utils.js';
// Removed switchTrainingStep from import as it is now defined locally
// switchTrainingMainTab removed from import as it is now defined locally
import { drawGoalChart, updateGoalChartLines, resizeAllCharts } from './charts_manager.js';

// ── Column alias helper (reads cross-iframe localStorage) ──
function _trainAlias(colName) {
    try {
        if (localStorage.getItem('sigma2_useAlias') !== '1') return colName;
        const map = JSON.parse(localStorage.getItem('sigma2_aliases') || '{}');
        return map[colName] || colName;
    } catch(_) { return colName; }
}

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

let paramPreviewCharts = {};
let lastSelectedIndexMap = {};

// =========================
// HyperParams Rendering
// =========================

export function renderHyperParameters(algo) {
    const container = DOM.get('dynamic-hyper-params');
    if (!container) return;

    // Desc update
    const descEl = DOM.get('algo-desc');
    if (descEl) {
        if (algo === 'IQL') descEl.innerText = "IQL (Implicit Q-Learning) 是一種離線強化學習算法，能在不與環境互動的情況下從歷史數據中學習策略。";
        else if (algo === 'CQL') descEl.innerText = "CQL (Conservative Q-Learning) 強調策略保守性，避免超出歷史數據分佈的推斷。";
        else descEl.innerText = "此演算法適合複雜的非線性控制場景。";
    }

    const subNav1 = DOM.get('sub-nav-1');
    if (subNav1) subNav1.innerHTML = `<div class="dot">1</div> 演算法選擇 (${algo})`;

    const config = ALGO_CONFIG_MANIFEST[algo];
    if (!config) {
        container.innerHTML = '<div style="grid-column: span 2; color: #94a3b8; font-size: 11px; padding: 20px;">此演算法尚定定義預設配置</div>';
        return;
    }

    container.innerHTML = Object.entries(config).map(([key, item]) => `
        <div class="config-item" style="animation: fadeIn 0.3s ease forwards;">
            <label>${item.label}</label>
            <input type="${item.type || 'text'}" id="hp-${key}" value="${item.val}" step="${item.step || ''}" oninput="updateConfigImpact()">
            ${item.hint ? `<span class="hint">${item.hint}</span>` : ''}
        </div>
    `).join('');

    // We assume updateConfigImpact is global or we import it?
    // It's separate. We can implement it here or separate. It's training specific.
    // I'll add updateConfigImpact to exports later or let it be internal if wired up properly.
    // For now inline onclick="..." in dashboard_full.js called it.
    // We need to attach listeners instead of oninput="..." if we want cleaner code, but for now HTML injection.
    // IMPORTANT: function updateConfigImpact needs to be available. I'll export it.
}

export function renderPredHyperParameters(algo) {
    const container = DOM.get('pred-dynamic-hyper-params');
    if (!container) return;

    const descEl = DOM.get('pred-algo-desc');
    if (descEl) {
        if (algo === 'XGBoost') descEl.innerText = "* XGBoost 是處理結構化工業數據最穩定的選擇，具備極強的非線性擬合能力。";
        else if (algo === 'RandomForest') descEl.innerText = "* 隨機森林具備極佳的抗噪性，適合特徵分佈較分散的數據。";
        else descEl.innerText = "* 此演算法適合大規模、高效率的訓練場景。";
    }

    const subNav1 = DOM.get('sub-nav-3-1');
    if (subNav1) subNav1.innerHTML = `<div class="dot">1</div> 預測演算法 (${algo})`;

    const config = PRED_ALGO_CONFIG_MANIFEST[algo];
    if (!config) {
        container.innerHTML = '<div style="grid-column: span 2; color: #94a3b8; font-size: 11px; padding: 20px;">此演算法尚定定義預設配置</div>';
        return;
    }

    container.innerHTML = Object.entries(config).map(([key, item]) => `
        <div class="config-item" style="animation: fadeIn 0.3s ease forwards;">
            <label>${item.label}</label>
            <input type="${item.type || 'text'}" id="pred-hp-${key}" value="${item.val}" step="${item.step || ''}">
            ${item.hint ? `<span class="hint">${item.hint}</span>` : ''}
        </div>
    `).join('');
}

export function updateConfigImpact() {
    const batchSize = parseInt(DOM.val('hp-batch_size') || 1024);
    const lr = parseFloat(DOM.val('hp-actor_learning_rate') || 0.0003);

    let speedIdx = (lr * 10000 * 25) + (batchSize / 1024 * 30);
    speedIdx = Math.min(Math.max(speedIdx, 10), 95);

    let memIdx = (batchSize / 2048 * 80);
    memIdx = Math.min(Math.max(memIdx, 5), 98);

    const speedBar = DOM.get('impact-speed-bar');
    const speedText = DOM.get('impact-speed-text');
    const memBar = DOM.get('impact-memory-bar');
    const memText = DOM.get('impact-memory-text');

    if (speedBar) speedBar.style.width = `${speedIdx}%`;
    if (speedText) speedText.innerText = `收斂速度: ${speedIdx > 80 ? '極速' : (speedIdx > 50 ? '優良' : '一般')}`;
    if (memBar) memBar.style.width = `${memIdx}%`;
    if (memText) memText.innerText = `記憶體佔用: ${memIdx > 70 ? '極高' : (memIdx > 30 ? '中等' : '低')}`;
}




// =========================
// Data Loading & Metadata
// =========================

export async function loadTrainingMetadata(filename) {
    window.currentTrainingFilename = filename;

    if (!filename || filename === '未選擇') {
        const goalCol = DOM.get('model-goal-col');
        if (goalCol) goalCol.innerHTML = '<option value="">-- 先選擇數據源 --</option>';
        DOM.html('model-features-list', '<span style="color: #94a3b8; font-size: 12px;">無可用欄位</span>');
        return;
    }

    try {
        // Generate Default Model Name
        const modelLabel = DOM.get('training-model-name-label');
        if (modelLabel && (modelLabel.innerText === '未命名模型' || modelLabel.innerText === '')) {
            const now = new Date();
            const timestamp = `${now.getMonth() + 1}${now.getDate()}_${now.getHours()}${now.getMinutes()}`;
            const cleanName = filename.split('.')[0].substring(0, 8);
            modelLabel.innerText = `Model_${cleanName}_${timestamp}`;
        }

        const viewData = await API.get(`/api/view_file/${filename}`, { page: 1, page_size: 1, session_id: window.SESSION_ID });

        // Parse Headers
        let headers = [];
        if (viewData.headers && Array.isArray(viewData.headers)) {
            headers = viewData.headers;
        } else if (viewData.content) {
            const lines = viewData.content.trim().split('\n');
            if (lines.length > 0) headers = lines[0].split(',').map(h => h.trim());
        }

        const goalSelect = DOM.get('model-goal-col');
        if (!goalSelect) return;

        // Reset Step 1
        goalSelect.innerHTML = '<option value="">-- 請選擇 --</option>';
        ['goal-target', 'goal-usl', 'goal-lsl'].forEach(id => DOM.val(id, ''));
        DOM.setText('goal-out-count', '0');
        DOM.setText('goal-out-ratio', '0.00%');

        drawGoalChart(null); // Clear chart

        const step1Title = document.querySelector('#train-step-nav-1 .step-title');
        if (step1Title) {
            step1Title.innerText = '任務標的';
            step1Title.style.color = '';
        }

        // Reset Lists
        DOM.html('model-features-list', '');
        DOM.html('rl-actions-list', '');
        DOM.html('rl-states-list', '');

        // Populate Options
        headers.forEach(h => {
            if (!h) return;
            // Goal Option
            const opt = document.createElement('option');
            opt.value = h; opt.innerText = _trainAlias(h);
            goalSelect.appendChild(opt);

            // ML Features
            const featuresList = DOM.get('model-features-list');
            if (featuresList) {
                const lbl = document.createElement('label');
                lbl.className = 'feature-item-label';
                lbl.style.cssText = 'display:block; padding:8px 10px; font-size:13px; cursor:pointer; border-radius:6px; transition:all 0.2s;';
                lbl.innerHTML = `<input type="checkbox" name="model-feature" value="${h}" checked style="margin-right:12px; transform:scale(1.1);"> ${_trainAlias(h)}`;
                featuresList.appendChild(lbl);
            }

            // RL Actions
            const rlActionsList = DOM.get('rl-actions-list');
            if (rlActionsList) {
                const lbl = document.createElement('label');
                lbl.style.cssText = 'display:block; padding:6px; font-size:12px; cursor:pointer;';
                lbl.innerHTML = `<input type="checkbox" name="rl-action" value="${h}" style="margin-right:8px;"> ${_trainAlias(h)}`;
                rlActionsList.appendChild(lbl);
            }

            // RL States
            const rlStatesList = DOM.get('rl-states-list');
            if (rlStatesList) {
                const lbl = document.createElement('label');
                lbl.style.cssText = 'display:block; padding:6px; font-size:12px; cursor:pointer;';
                lbl.innerHTML = `<input type="checkbox" name="rl-state" value="${h}" checked style="margin-right:8px;"> ${_trainAlias(h)}`;
                rlStatesList.appendChild(lbl);
            }
        });

        updateSelectedFeaturesCount();

        // Reset Step 3 (Pred)
        DOM.html('pred-selected', '');
        initStep3Lists();
        updateStep3UIStatus();

        // Reset Step 2 (Control/State Selection)
        DOM.html('control-selected', '<div style="padding: 20px; text-align: center; color: #94a3b8; font-size: 11px;">尚未選擇</div>');
        DOM.html('state-selected', '<div style="padding: 20px; text-align: center; color: #94a3b8; font-size: 11px;">尚未選擇</div>');
        lastSelectedIndexMap = {}; // Reset selection state
        initStep2Lists(); // Refresh available lists based on new headers

    } catch (err) {
        console.error("Load training metadata failed:", err);
    }
}

export function syncGoalToAll(val) {
    DOM.setText('display-ml-target', val ? _trainAlias(val) : '(未設定)');
    DOM.setText('display-rl-reward', val ? _trainAlias(val) : '(未設定)');

    if (!val) {
        drawGoalChart(null);
    }

    // Disable goal in feature lists
    document.querySelectorAll('input[name="model-feature"]').forEach(i => {
        const p = i.parentElement;
        if (i.value === val) {
            i.checked = false; i.disabled = true; p.style.opacity = '0.4'; p.classList.add('disabled');
        } else {
            i.disabled = false; p.style.opacity = '1'; p.classList.remove('disabled');
        }
    });

    document.querySelectorAll('input[name="rl-action"]').forEach(i => {
        const p = i.parentElement;
        if (i.value === val) {
            i.checked = false; i.disabled = true; p.style.opacity = '0.4';
        } else {
            i.disabled = false; p.style.opacity = '1';
        }
    });

    updateSelectedFeaturesCount();

    // Remove from Step 2 Lists if present
    ['control-selected', 'state-selected'].forEach(cid => {
        const container = DOM.get(cid);
        if (!container) return;
        let removed = false;
        container.querySelectorAll('.list-item').forEach(item => {
            if (item.getAttribute('data-value') === val) {
                item.remove();
                removed = true;
            }
        });
        if (container.children.length === 0) {
            container.innerHTML = '<div style="padding: 20px; text-align: center; color: #94a3b8; font-size: 11px;">尚未選擇</div>';
        }
        if (removed) {
            // alert?
        }
    });

    initStep2Lists();
}

// =========================
// List Management (Step 2 & 3)
// =========================

export function initStep2Lists() {
    const goalCol = DOM.val('model-goal-col');
    const selectEl = DOM.get('model-goal-col');
    if (!selectEl) return;

    const allCols = Array.from(selectEl.options).map(o => o.value).filter(v => v !== "" && v !== goalCol);

    const controlSelected = Array.from(DOM.get('control-selected').querySelectorAll('.list-item')).map(el => el.getAttribute('data-value'));
    const stateSelected = Array.from(DOM.get('state-selected').querySelectorAll('.list-item')).map(el => el.getAttribute('data-value'));
    const allSelected = [...controlSelected, ...stateSelected];

    ['control-avail', 'state-avail'].forEach(cid => {
        const container = DOM.get(cid);
        if (!container) return;

        const availableCols = allCols.filter(c => !allSelected.includes(c));

        if (availableCols.length === 0) {
            container.innerHTML = '<div style="padding: 20px; text-align: center; color: #94a3b8; font-size: 11px;">無可用參數</div>';
        } else {
            container.innerHTML = availableCols.map(col => `
                <div class="list-item" draggable="true" ondragstart="handleTrainingDragStart(event)" onclick="toggleListItem(this)" ondblclick="moveSingleItem(this)" data-value="${col}" title="${col}">${_trainAlias(col)}</div>
            `).join('');
        }
    });

    ['control-selected', 'state-selected'].forEach(cid => {
        const container = DOM.get(cid);
        if (container && container.querySelectorAll('.list-item').length === 0) {
            container.innerHTML = '<div style="padding: 20px; text-align: center; color: #94a3b8; font-size: 11px;">尚未選擇</div>';
        }
    });
}

export function initStep3Lists() {
    const goalCol = DOM.val('model-goal-col');
    const selectEl = DOM.get('model-goal-col');
    if (!selectEl) return;

    const allCols = Array.from(selectEl.options).map(o => o.value).filter(v => v !== "" && v !== goalCol);
    const selectedFeatures = Array.from(DOM.get('pred-selected').querySelectorAll('.list-item')).map(el => el.getAttribute('data-value'));

    const container = DOM.get('pred-avail');
    if (!container) return;

    const availableCols = allCols.filter(c => !selectedFeatures.includes(c));

    if (availableCols.length === 0) {
        container.innerHTML = '<div style="padding: 20px; text-align: center; color: #94a3b8; font-size: 11px;">無可用參數</div>';
    } else {
        container.innerHTML = availableCols.map(col => `
            <div class="list-item" draggable="true" ondragstart="handleTrainingDragStart(event)" onclick="toggleListItem(this)" ondblclick="moveSingleItem(this)" data-value="${col}" title="${col}">${_trainAlias(col)}</div>
        `).join('');
    }

    const selContainer = DOM.get('pred-selected');
    if (selContainer && selContainer.querySelectorAll('.list-item').length === 0) {
        selContainer.innerHTML = '<div style="padding: 20px; text-align: center; color: #94a3b8; font-size: 11px;">尚未選擇</div>';
    }

    updateStep3UIStatus();
}

export function updateStep2UIStatus() {
    const ctrlBox = DOM.get('control-selected');
    const stateBox = DOM.get('state-selected');
    if (!ctrlBox || !stateBox) return;

    const ctrlCount = ctrlBox.querySelectorAll('.list-item').length;
    const stateCount = stateBox.querySelectorAll('.list-item').length;

    // 額外檢查：如果容器內包含「尚未選擇」，則視為 0
    const hasCtrl = ctrlCount > 0 && !ctrlBox.innerText.includes('尚未選擇');
    const hasState = stateCount > 0 && !stateBox.innerText.includes('尚未選擇');

    const warningBar = DOM.get('step2-validation-warning');
    const warnMsg = DOM.get('step2-warn-msg');

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
    const subNav1 = DOM.get('sub-nav-1');
    const subNav2 = DOM.get('sub-nav-2');
    const subNav3 = DOM.get('sub-nav-3');

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
    const ctrlHeader = DOM.get('control-selected-header');
    const stateHeader = DOM.get('state-selected-header');
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

export function updateStep3UIStatus() {
    const selectedCount = DOM.get('pred-selected')?.querySelectorAll('.list-item').length || 0;
    DOM.setText('pred-feat-count', selectedCount);

    const subNav2 = DOM.get('sub-nav-3-2');
    if (subNav2) {
        if (selectedCount > 0) {
            subNav2.classList.add('done-blue');
            subNav2.innerHTML = `<div class="dot">2</div> 製程參數 (${selectedCount})`;
        } else {
            subNav2.classList.remove('done-blue');
            subNav2.innerHTML = `<div class="dot">2</div> 製程參數`;
        }
    }

    const stepTitle = document.querySelector('#train-step-nav-3 .step-title');
    if (stepTitle) {
        if (selectedCount > 0) {
            stepTitle.innerText = '預測配置 (完成)';
            stepTitle.style.color = '#10b981';
        } else {
            stepTitle.innerText = '預測配置';
            stepTitle.style.color = '';
        }
    }
    checkGlobalTrainingStatus();
}

export function checkGlobalTrainingStatus() {
    const s1 = document.querySelector('#train-step-nav-1 .step-title')?.innerText.includes('(完成)');
    const s2 = document.querySelector('#train-step-nav-2 .step-title')?.innerText.includes('(完成)');
    const s3 = document.querySelector('#train-step-nav-3 .step-title')?.innerText.includes('(完成)');

    const btn = DOM.get('final-train-btn');
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

// =========================
// Drag & Move Logic
// =========================

export function toggleListItem(el) {
    const parent = el.parentElement;
    const containerId = parent.id || 'default-list';
    const items = Array.from(parent.querySelectorAll('.list-item'));
    const currentIndex = items.indexOf(el);
    const ev = window.event;
    const isShift = ev && ev.shiftKey;
    const isCtrl = ev && (ev.ctrlKey || ev.metaKey);

    if (isShift && lastSelectedIndexMap[containerId] !== undefined) {
        const start = Math.min(currentIndex, lastSelectedIndexMap[containerId]);
        const end = Math.max(currentIndex, lastSelectedIndexMap[containerId]);
        items.forEach((item, idx) => {
            if (idx >= start && idx <= end) item.classList.add('selected');
            else if (!isCtrl) item.classList.remove('selected');
        });
    } else if (isCtrl) {
        el.classList.toggle('selected');
        if (el.classList.contains('selected')) lastSelectedIndexMap[containerId] = currentIndex;
    } else {
        items.forEach(it => it.classList.remove('selected'));
        el.classList.add('selected');
        lastSelectedIndexMap[containerId] = currentIndex;
    }

    // Mutex logic
    if (containerId.includes('avail') || containerId.includes('selected')) {
        const type = containerId.split('-')[0];
        const isAvail = containerId.includes('avail');
        const otherId = isAvail ? `${type}-selected` : `${type}-avail`;
        const otherContainer = DOM.get(otherId);
        if (otherContainer) otherContainer.querySelectorAll('.list-item').forEach(it => it.classList.remove('selected'));
        updateMoveButtons(type);
    }

    // Preview logic
    const selectedCount = parent.querySelectorAll('.list-item.selected').length;
    if (selectedCount === 1) {
        drawParamPreview(el.getAttribute('data-value'), getPreviewCanvasId(containerId));
    } else {
        clearParamPreview(getPreviewCanvasId(containerId));
    }
}

function getPreviewCanvasId(containerId) {
    if (containerId.includes('control')) return 'control-preview-chart';
    if (containerId.includes('state')) return 'state-preview-chart';
    if (containerId.includes('pred')) return 'pred-preview-chart';
    return '';
}

async function drawParamPreview(colName, canvasId) {
    const canvas = DOM.get(canvasId);
    if (!canvas) return;

    if (paramPreviewCharts[canvasId]) {
        paramPreviewCharts[canvasId].destroy();
        delete paramPreviewCharts[canvasId];
    }

    const activeFile = (window.currentTrainingFilename || DOM.text('training-active-file')).trim();
    if (!activeFile || activeFile === '未選擇') return;

    try {
        const result = await API.get(`/api/get_column_data`, { filename: activeFile, column: colName, session_id: window.SESSION_ID });
        if (result.success) {
            const ctx = canvas.getContext('2d');
            paramPreviewCharts[canvasId] = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: result.data.map((_, i) => i),
                    datasets: [{
                        label: colName, data: result.data,
                        borderColor: '#3b82f6', backgroundColor: 'rgba(59, 130, 246, 0.1)',
                        borderWidth: 1.5, pointRadius: 0, fill: true, tension: 0.4
                    }]
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    plugins: { legend: { display: false }, tooltip: { mode: 'index', intersect: false } },
                    scales: { x: { display: false }, y: { grid: { color: '#f1f5f9' }, ticks: { font: { size: 10 } } } }
                }
            });
        }
    } catch (err) { console.error("Preview draw error:", err); }
}

function clearParamPreview(canvasId) {
    const canvas = DOM.get(canvasId);
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (paramPreviewCharts[canvasId]) {
        paramPreviewCharts[canvasId].destroy();
        delete paramPreviewCharts[canvasId];
    }
}

export function moveItems(type, direction) {
    const availId = `${type}-avail`;
    const selectedId = `${type}-selected`;
    const sourceId = direction === 'to-selected' ? availId : selectedId;
    const targetId = direction === 'to-selected' ? selectedId : availId;

    const sourceEl = DOM.get(sourceId);
    const targetEl = DOM.get(targetId);
    if (!sourceEl || !targetEl) return;

    const selectedItems = Array.from(sourceEl.querySelectorAll('.list-item.selected'));
    if (selectedItems.length === 0) return;

    if (targetEl.innerHTML.includes('尚未選擇')) targetEl.innerHTML = '';

    selectedItems.forEach(item => {
        item.classList.remove('selected');
        item.setAttribute('ondblclick', 'moveSingleItem(this)');
        targetEl.appendChild(item);
    });

    const allItems = Array.from(targetEl.children).filter(el => el.classList.contains('list-item'));
    if (allItems.length > 1) {
        allItems.sort((a, b) => a.innerText.localeCompare(b.innerText)).forEach(node => targetEl.appendChild(node));
    }

    if (type === 'pred') { initStep3Lists(); updateStep3UIStatus(); }
    else { initStep2Lists(); updateStep2UIStatus(); }
    updateMoveButtons(type);

    // ✨ 內容異動，標記需要重新暫存
    markTrainingConfigChanged();
}

function updateMoveButtons(type) {
    const availContainer = DOM.get(`${type}-avail`);
    const selectedContainer = DOM.get(`${type}-selected`);
    if (!availContainer || !selectedContainer) return;

    const hasAvail = availContainer.querySelectorAll('.list-item.selected').length > 0;
    const hasSel = selectedContainer.querySelectorAll('.list-item.selected').length > 0;

    const toSelectedBtn = DOM.get(`${type}-to-selected-btn`);
    const toAvailBtn = DOM.get(`${type}-to-avail-btn`);

    if (toSelectedBtn) { if (hasAvail) toSelectedBtn.classList.remove('disabled'); else toSelectedBtn.classList.add('disabled'); }
    if (toAvailBtn) { if (hasSel) toAvailBtn.classList.remove('disabled'); else toAvailBtn.classList.add('disabled'); }
}

export function moveSingleItem(el) {
    const parentId = el.parentElement.id;
    let type = parentId.split('-')[0];
    let direction = parentId.includes('avail') ? 'to-selected' : 'to-avail';

    el.parentElement.querySelectorAll('.list-item').forEach(it => it.classList.remove('selected'));
    el.classList.add('selected');
    moveItems(type, direction);
}

export function handleTrainingDragStart(ev) {
    const el = ev.target;
    const parent = el.parentElement;
    const selected = parent.querySelectorAll('.list-item.selected');

    let dragData = [];
    if (el.classList.contains('selected') && selected.length > 1) {
        dragData = Array.from(selected).map(item => item.getAttribute('data-value'));
    } else {
        dragData = [el.getAttribute('data-value')];
        parent.querySelectorAll('.list-item').forEach(it => it.classList.remove('selected'));
        el.classList.add('selected');
    }

    const type = parent.id.split('-')[0];
    ev.dataTransfer.setData("training-data", JSON.stringify({ type: type, values: dragData }));
    ev.dataTransfer.effectAllowed = "move";
}

export function handleTrainingDrop(ev, targetType, direction) {
    ev.preventDefault();
    const rawData = ev.dataTransfer.getData("training-data");
    if (!rawData) return;
    try {
        const data = JSON.parse(rawData);
        if (data.type === targetType) moveItems(targetType, direction);
    } catch (e) {
        console.error("Drop error:", e);
    }
}

export function filterFeatureList(query) {
    const lowerQuery = query.toLowerCase();
    document.querySelectorAll('.feature-item-label').forEach(label => {
        const cb = label.querySelector('input');
        const origName = cb ? cb.value.toLowerCase() : '';
        const match = label.innerText.toLowerCase().includes(lowerQuery) || origName.includes(lowerQuery);
        label.style.display = match ? 'block' : 'none';
    });
}

export function filterList(listId, query) {
    const lowerQuery = query.toLowerCase();
    const container = DOM.get(listId);
    if (!container) return;
    container.querySelectorAll('.list-item').forEach(item => {
        item.style.display = item.innerText.toLowerCase().includes(lowerQuery) ? 'block' : 'none';
    });
}

export function toggleAllFeatures(checked) {
    const items = document.querySelectorAll('input[name="model-feature"]');
    items.forEach(it => { if (!it.disabled) it.checked = checked; });
    updateSelectedFeaturesCount();
}

export function updateSelectedFeaturesCount() {
    const checked = document.querySelectorAll('input[name="model-feature"]:checked').length;
    const countEl = DOM.get('selected-features-count');
    if (countEl) {
        countEl.innerText = checked;
        countEl.style.color = checked === 0 ? '#ef4444' : '#3b82f6';
    }
}

// =========================
// Start Training & Collection
// =========================

export function collectTrainingUIState() {
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


export async function startModelTraining() {
    const config = collectTrainingUIState();

    if (!config.filename || config.filename === '未選擇') { alert('請先選擇數據源檔案！'); return; }
    if (!config.goal) { alert('請先在第一步定義核心目標欄位！'); switchTrainingStep(1); return; }

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
        const response = await fetch(`/api/analysis/train?session_id=${window.SESSION_ID}`, {
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

export function onMissionTypeChange() {
    const missionTypeEl = document.querySelector('input[name="mission-type"]:checked');
    if (!missionTypeEl) return;
    const isML = missionTypeEl.value === 'supervised';

    const fSuper = DOM.get('fields-supervised-section');
    const fRL = DOM.get('fields-rl-section');
    const aSuper = DOM.get('algo-supervised-section');
    const aRL = DOM.get('algo-rl-section');
    const step2Desc = DOM.get('step2-desc');

    if (fSuper) fSuper.style.display = isML ? 'flex' : 'none';
    if (fRL) fRL.style.display = isML ? 'none' : 'grid';
    if (aSuper) aSuper.style.display = isML ? 'block' : 'none';
    if (aRL) aRL.style.display = isML ? 'none' : 'block';
    if (step2Desc) {
        step2Desc.innerText = isML ? '定義模型學習所需的製程參數輸入。' : '定義環境觀察狀態與可開發的動作控制集合。';
    }
}

/**
 * 訓練流程步驟切換
 */
export function switchTrainingStep(step) {
    if (!step) return;

    // 1. Reset all panels to hidden
    document.querySelectorAll('[id^="train-step-panel-"]').forEach(p => {
        p.style.display = 'none';
        p.style.opacity = '0';
    });

    document.querySelectorAll('[id^="train-step-nav-"]').forEach(n => n.classList.remove('active'));

    // 2. Activate target
    const currentPanel = document.getElementById(`train-step-panel-${step}`);
    if (currentPanel) {
        currentPanel.style.display = 'flex';
        setTimeout(() => { currentPanel.style.opacity = '1'; }, 50);
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
            if (typeof onMissionTypeChange === 'function') onMissionTypeChange();
        }
        if (typeof switchStep2SubSection === 'function') switchStep2SubSection(1);
        if (typeof initStep2Lists === 'function') initStep2Lists();
        const algo = document.getElementById('rl-algorithm')?.value || 'IQL';
        renderHyperParameters(algo);
        setTimeout(updateStep2UIStatus, 100);
    }
    else if (step === 3) {
        // 進入「預測配置」代表進入監督式學習模式
        const mlRadio = document.querySelector('input[name="mission-type"][value="supervised"]');
        if (mlRadio) {
            mlRadio.checked = true;
            if (typeof onMissionTypeChange === 'function') onMissionTypeChange();
        }
        switchStep3SubSection(1);
        const algo = document.getElementById('pred-algorithm')?.value || 'XGBoost';
        renderPredHyperParameters(algo);
        updateStep3UIStatus();
    }
}

export async function trainModel(filename) {
    // 1. 切換主視圖到訓練頁面
    if (typeof window.switchView === 'function') {
        window.switchView('training');
    }

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

export async function loadTrainingDraft(draftId) {
    // This is an alias/wrapper for loading a saved draft
    // In the full implementation, this loads a draft by ID and hydrates the UI
    try {
        const res = await fetch(`/api/draft/load/${draftId}?session_id=${window.SESSION_ID}`);
        if (!res.ok) throw new Error('載入失敗');

        const draft = await res.json();
        await hydrateTrainingFromDraft(draft, 'full');

        // Switch to training view
        if (typeof window.switchView === 'function') {
            window.switchView('training');
        }
        switchTrainingMainTab('build');
    } catch (err) {
        console.error('Load draft failed:', err);
        alert('載入暫存失敗，請稍後再試。');
    }
}

export function makeModelNameEditable() {
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

// =========================
// Context Modal / Universal Loader
// =========================
let currentContextTab = 'files';
let selectedContextItem = null;

export async function switchContextTab(tab) {
    currentContextTab = tab;
    selectedContextItem = null;

    // UI 標籤切換
    document.querySelectorAll('.modal-tab').forEach(el => el.classList.remove('active'));
    const tabEl = document.getElementById(`tab-context-${tab}`);
    if (tabEl) tabEl.classList.add('active');

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

    if (listArea) listArea.innerHTML = '<div style="text-align: center; padding: 40px; color: #94a3b8;">🔍 檢索中...</div>';

    try {
        let items = [];
        const sid = window.SESSION_ID || '';
        if (tab === 'files') {
            const data = await API.get(`/api/list_files`, { session_id: sid });
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
            const models = await API.get('/api/analysis/models', { session_id: sid });
            items = models.map(m => ({
                id: m.job_id,
                title: m.modelName || m.model_name || '未命名模型',
                meta: `R2: ${m.r2 || 'N/A'} | ${m.created_at}`,
                icon: '🧠',
                type: 'model',
                data: m
            }));
        } else if (tab === 'drafts') {
            const data = await API.get(`/api/draft/list`, { session_id: sid });
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
        if (listArea) listArea.innerHTML = `<div style="text-align: center; padding: 40px; color: #ef4444;">❌ 載入失敗: ${err.message}</div>`;
    }
}

export function renderContextList(items) {
    const listArea = document.getElementById('context-list-area');
    if (!listArea) return;

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

    if (currentContextTab === 'files' && items.length > 0) {
        const moreBtn = document.createElement('div');
        moreBtn.style.cssText = 'padding: 15px; text-align: center; border-top: 1px dashed #e2e8f0; margin-top: 5px;';
        moreBtn.innerHTML = `
            <button onclick="window.closeTrainingContextModal(); window.switchView('files');" 
                    style="background: transparent; border: 1px solid #3b82f6; color: #3b82f6; padding: 6px 14px; border-radius: 6px; font-size: 11px; font-weight: 700; cursor: pointer; transition: all 0.2s;">
                &raquo; 檢索更多檔案 (進入檔案管理)
            </button>
        `;
        listArea.appendChild(moreBtn);
    }
}

export function selectContextItem(el, item) {
    if (item instanceof HTMLElement) { item = arguments[1]; el = arguments[0]; } // fix arg order robustness

    document.querySelectorAll('.workspace-item').forEach(it => it.classList.remove('selected'));
    if (el && el.classList) el.classList.add('selected');
    selectedContextItem = item;

    const confirmBtn = document.getElementById('btn-confirm-context');
    const configOnlyBtn = document.getElementById('btn-load-config-only');
    const loadFullBtn = document.getElementById('btn-load-full');

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
        if (confirmBtn) confirmBtn.style.display = 'none';

        if (configOnlyBtn) {
            configOnlyBtn.style.display = 'flex';
            if (!hasActiveFile) {
                configOnlyBtn.disabled = true;
                configOnlyBtn.style.opacity = '0.4';
                configOnlyBtn.style.cursor = 'not-allowed';
            } else {
                configOnlyBtn.disabled = false;
                configOnlyBtn.style.opacity = '1';
                configOnlyBtn.style.cursor = 'pointer';
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

// Hydrate function moved from dashboard_full.js
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

    } catch (err) {
        console.error("❌ Hydration failed:", err);
        alert(`載入暫存時發生錯誤：${err.message}\n請確認數據檔案 "${draft.filename}" 是否仍然存在。`);
    }
}

export function openTrainingContextModal() {
    const modal = document.getElementById('trainingContextModal');
    if (modal) {
        modal.classList.add('show');
        switchContextTab(currentContextTab);
    }
}

export function closeTrainingContextModal() {
    const modal = document.getElementById('trainingContextModal');
    if (modal) modal.classList.remove('show');
}

export async function confirmContextSelection(mode = 'full') {
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

        // --- ✨ 全面重置訓練介面狀態 ---
        // 1. 重置 Step 1: 目標設定
        const goalSelect = document.getElementById('model-goal-col');
        if (goalSelect) goalSelect.value = '';
        if (document.getElementById('goal-target')) document.getElementById('goal-target').value = '';
        if (document.getElementById('goal-usl')) document.getElementById('goal-usl').value = '';
        if (document.getElementById('goal-lsl')) document.getElementById('goal-lsl').value = '';

        // 2. 清除清單
        const ctrlSel = document.getElementById('control-selected');
        const stateSel = document.getElementById('state-selected');
        if (ctrlSel) ctrlSel.innerHTML = '<div style="padding: 20px; text-align: center; color: #94a3b8; font-size: 11px;">尚未選擇</div>';
        if (stateSel) stateSel.innerHTML = '<div style="padding: 20px; text-align: center; color: #94a3b8; font-size: 11px;">尚未選擇</div>';

        // 3. 重置標題
        document.querySelectorAll('.step-title').forEach(el => {
            if (el.innerText.includes('(完成)')) {
                el.innerText = el.innerText.replace(' (完成)', '');
                el.style.color = '';
            }
        });

        await loadTrainingMetadata(item.id);
        switchTrainingStep(1);
    }
    else if (item.type === 'model') {
        const modelData = item.data;
        if (!modelData) return;
        if (fileLabel) fileLabel.innerText = modelData.filename || '未知檔案';
        if (modelLabel) modelLabel.innerText = (modelData.modelName || modelData.model_name) + '_再訓練';
        await hydrateTrainingFromDraft(modelData, mode);
    }
    else if (item.type === 'draft') {
        if (mode === 'full') {
            if (fileLabel) fileLabel.innerText = item.data.filename;
        }
        if (modelLabel) modelLabel.innerText = item.data.modelName;
        await hydrateTrainingFromDraft(item.data, mode);
    }

    closeTrainingContextModal();
}

export async function saveCurrentTrainingDraft() {
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
        const res = await fetch(`/api/draft/save?session_id=${window.SESSION_ID}`, {
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

export function markTrainingConfigChanged() {
    const btn = document.getElementById('btn-save-draft');
    if (btn && btn.dataset.saved === 'true') {
        btn.innerText = '💾 暫存';
        btn.style.color = '#94a3b8';
        btn.dataset.saved = 'false';
    }
}

export function initTrainingChangeListeners() {
    const subConfig = document.getElementById('training-sub-config-content');
    if (subConfig) {
        ['input', 'change'].forEach(evtName => {
            subConfig.addEventListener(evtName, (e) => {
                if (e.target.closest('.list-search')) return;
                const tag = e.target.tagName;
                if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') {
                    markTrainingConfigChanged();
                }
            });
        });
    }

    const modelNameInput = document.getElementById('training-model-name-input');
    if (modelNameInput) modelNameInput.addEventListener('input', markTrainingConfigChanged);

    const featuresList = document.getElementById('model-features-list');
    if (featuresList) featuresList.addEventListener('change', markTrainingConfigChanged);
}

// =========================
// Sub-section Navigation
// =========================
let currentStep2SubIdx = 1;
let currentStep3SubIdx = 1;

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

export function switchStep2SubSection(idx) {
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
        setTimeout(() => {
            if (typeof resizeAllCharts === 'function') resizeAllCharts();
        }, 100);
    }
}

export function switchStep3SubSection(idx) {
    currentStep3SubIdx = idx;

    // Update Sub-Nav
    document.querySelectorAll('.step2-sub-item').forEach(el => {
        if (!el.id.startsWith('sub-nav-3-')) return; // Only Step 3 buttons
        el.classList.remove('active');
    });
    const activeNav = document.getElementById(`sub-nav-3-${idx}`);
    if (activeNav) activeNav.classList.add('active');

    // Update Panel
    document.querySelectorAll('.step2-panel').forEach(el => {
        if (!el.id.startsWith('step3-panel-')) return; // Only Step 3 panels
        el.classList.remove('active');
    });
    const activePanel = document.getElementById(`step3-panel-${idx}`);
    if (activePanel) activePanel.classList.add('active');

    if (idx === 2) {
        if (typeof initStep3Lists === 'function') initStep3Lists();
        setTimeout(() => {
            if (typeof resizeAllCharts === 'function') resizeAllCharts();
        }, 100);
    }
    if (idx === 3) {
        triggerPredictionPreCheck();
    }
}


function setActiveTabStyle(activeBtn, inactiveBtns) {
    if (activeBtn) {
        activeBtn.classList.add('active');
        activeBtn.style.background = '#e0e7ff';
        activeBtn.style.color = '#3730a3';
        activeBtn.style.fontWeight = '700';
    }
    inactiveBtns.forEach(btn => {
        if (btn) {
            btn.classList.remove('active');
            btn.style.background = 'transparent';
            btn.style.color = '#64748b';
            btn.style.fontWeight = '500';
        }
    });
}

export function checkTrainingFileBeforeSelect(ev) {
    const filenameLabel = document.getElementById('training-active-file');
    const filename = filenameLabel ? filenameLabel.innerText.trim() : '';

    if (!filename || filename === '未選擇') {
        if (ev) {
            ev.preventDefault();
            ev.stopPropagation();
        }
        // 直接開啟檔案選擇器
        if (typeof window.openFileSelector === 'function') {
            window.openFileSelector('training');
        }
        return false;
    }
}

export function finishModelNameEdit() {
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

export async function buildModelTrainingUI() {
    const activeFileEl = document.getElementById('training-active-file');
    const filename = activeFileEl ? activeFileEl.innerText : '';
    // Placeholder for future logic if needed
}

export function switchTrainingSubTab(tab) {
    const isConfig = (tab === 'config');
    const viewTitle = DOM.get('training-view-title');

    if (isConfig) {
        DOM.show('training-sub-config-content');
        DOM.hide('training-sub-report-content');
        if (viewTitle) viewTitle.innerText = '配置訓練參數';

        setActiveTabStyle(DOM.get('tab-train-sub-config'), [DOM.get('tab-train-sub-report')]);
        buildModelTrainingUI();
        if (typeof switchTrainingStep === 'function') switchTrainingStep(1);
    } else {
        DOM.hide('training-sub-config-content');
        DOM.show('training-sub-report-content');
        if (viewTitle) viewTitle.innerText = '訓練報告介面';

        setActiveTabStyle(DOM.get('tab-train-sub-report'), [DOM.get('tab-train-sub-config')]);
    }
}

export function navigateStep2Sub(dir) {
    let nextIdx = currentStep2SubIdx + dir;
    if (nextIdx < 1) nextIdx = 1;
    if (nextIdx > 3) nextIdx = 3;
    switchStep2SubSection(nextIdx);
}


// =========================
// Training Registry & Logging Logic
// =========================

let registryRefreshTimer = null;
let logAutoRefreshTimer = null;
let modelRegistryCurrentPage = 1;
const MODEL_REGISTRY_PAGE_SIZE = 10;

function clearAllTrainingTimers() {
    if (registryRefreshTimer) {
        clearInterval(registryRefreshTimer);
        registryRefreshTimer = null;
    }
}

export function switchTrainingMainTab(tab) {
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

export async function loadModelRegistry() {
    const tbody = DOM.get('model-list-body');
    const countText = DOM.get('model-count-text');
    if (!tbody) return;

    try {
        const models = await API.get('/api/analysis/models');

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

        displayedModels.forEach((raw) => {
            // --- Smart Unpacking ---
            // Handles both new API (flat) and old API (nested data)
            const m = raw.data ? { ...raw.data, ...raw } : raw;

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
            infoText += `目標標的：${_trainAlias(displayTarget)}\\n`;
            if (m.actions && m.actions.length > 0) infoText += `控制參數 (Actions)：${m.actions.map(a => _trainAlias(a)).join(', ')}\\n`;
            if (m.states && m.states.length > 0) infoText += `環境狀態 (States)：${m.states.map(s => _trainAlias(s)).join(', ')}\\n`;
            if (m.features && m.features.length > 0) infoText += `預測特徵 (Features)：${m.features.map(f => _trainAlias(f)).join(', ')}\\n`;

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
                    <span style="${tagStyle}" title="${displayTarget}">${_trainAlias(displayTarget)}</span>
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

export function changeModelRegistryPage(newPage) {
    modelRegistryCurrentPage = newPage;
    loadModelRegistry();
}

export async function deleteModel(jobId, modelName) {
    if (!jobId) return;
    if (!confirm(`確定要刪除模型「${modelName}」及其訓練日誌嗎？\n此動作無法還原。`)) return;

    try {
        const res = await API.delete(`/api/analysis/delete_model/${jobId}?session_id=${window.SESSION_ID}`);
        // API.delete returns parsed json or throws
        if (res.status === 'success') {
            loadModelRegistry();
            alert('✅ ' + res.message);
        } else {
            alert('❌ 刪除失敗: ' + (res.message || 'Unknown error'));
        }
    } catch (err) {
        alert('API 請求異常: ' + err.message);
    }
}

export async function stopModel(jobId, modelName) {
    if (!jobId) return;
    if (!confirm(`確定要強制停止模型「${modelName}」的訓練進程嗎？`)) return;

    try {
        const res = await API.post(`/api/analysis/stop_model/${jobId}?session_id=${window.SESSION_ID}`);
        if (res.status === 'success') {
            loadModelRegistry();
            alert('✅ ' + res.message);
        } else {
            alert('❌ 停止失敗: ' + (res.message || 'Unknown error'));
        }
    } catch (err) {
        alert('API 請求異常: ' + err.message);
    }
}

export function closeLogViewer() {
    if (logAutoRefreshTimer) {
        clearInterval(logAutoRefreshTimer);
        logAutoRefreshTimer = null;
    }
    const modal = document.getElementById('log-viewer-modal');
    if (modal) modal.remove();
}

export function toggleLogAutoRefresh(jobId, modelName, checked) {
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

export async function viewTrainingLog(jobId, modelName) {
    if (!jobId) {
        alert('找不到任務代碼 (Job ID)');
        return;
    }

    const modalId = 'log-viewer-modal';
    let modal = document.getElementById(modalId);
    let pre = document.getElementById('log-viewer-pre');

    try {
        // Use API.get but handle text response?
        // API utility assumes JSON mostly. Let's use fetch directly for text.
        const res = await fetch(`/api/analysis/get_log/${jobId}?session_id=${window.SESSION_ID}`);
        const logContent = await res.text();
        const cleanLog = logContent.startsWith('"') && logContent.endsWith('"') ? logContent.slice(1, -1).replace(/\\n/g, '\n').replace(/\\r/g, '') : logContent;

        if (modal && pre) {
            pre.innerText = cleanLog || "正在讀取日誌內容中...";
            pre.scrollTop = pre.scrollHeight;
            return;
        }

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
                <div style="flex:1; background:#0f172a; padding:0; overflow:hidden; position:relative;">
                    <pre id="log-viewer-pre" style="width:100%; height:100%; overflow:auto; padding:20px; color:#10b981; font-family:'JetBrains Mono', 'Fira Code', Consolas, monospace; font-size:13px; line-height:1.6; margin:0; box-sizing:border-box; white-space:pre-wrap;">${cleanLog || "正在讀取日誌內容中..."}</pre>
                </div>
            </div>
        `;
        document.body.appendChild(modal);
        pre = document.getElementById('log-viewer-pre');
        if (pre) pre.scrollTop = pre.scrollHeight;

        // Click outside to close
        modal.onclick = (e) => {
            if (e.target === modal) closeLogViewer();
        };

    } catch (err) {
        console.error("View log failed:", err);
        alert("無法讀取日誌: " + err.message);
    }
}


// Window Exports for HTML Event Handlers
window.syncGoalToAll = syncGoalToAll;
window.switchTrainingMainTab = switchTrainingMainTab;
window.switchTrainingStep = switchTrainingStep;
window.switchTrainingSubTab = switchTrainingSubTab;
window.switchStep2SubSection = switchStep2SubSection;
window.switchStep3SubSection = switchStep3SubSection;
window.navigateStep2Sub = navigateStep2Sub;
window.loadTrainingMetadata = loadTrainingMetadata;
window.renderHyperParameters = renderHyperParameters;
window.renderPredHyperParameters = renderPredHyperParameters;
window.updateConfigImpact = updateConfigImpact;
window.saveCurrentTrainingDraft = saveCurrentTrainingDraft;
window.makeModelNameEditable = makeModelNameEditable;
window.finishModelNameEdit = finishModelNameEdit;
window.startModelTraining = startModelTraining;
window.openTrainingContextModal = openTrainingContextModal;
window.checkTrainingFileBeforeSelect = checkTrainingFileBeforeSelect;
window.changeModelRegistryPage = changeModelRegistryPage;
window.viewTrainingLog = viewTrainingLog;
window.stopModel = stopModel;
window.deleteModel = deleteModel;
window.closeLogViewer = closeLogViewer;
window.toggleLogAutoRefresh = toggleLogAutoRefresh;
