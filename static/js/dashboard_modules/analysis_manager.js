import { DOM, API, WINDOW_SIZE } from './utils.js';
import { switchView } from './ui_core.js';
import { SESSION_ID } from './session.js';
import * as FileMgr from './file_manager.js'; // Need for openFileSelector

// --- Constants & State ---
let analysisCurrentPage = 1;
let analysisFilename = '';
export let originalTableData = []; // Export for external access if needed
export let tableHeaders = [];
export let analysisTotalLines = 0;

let currentSortColumn = -1;
let currentSortOrder = 'asc';
let activeFilters = [];
let visibleColumnIndices = [];

// Chart State
let chartConfig = { x: null, y: null, y2: null, type: 'scatter' };
let analysisChart = null; // Chart.js instance
let isSelecting = false;
let selectionStart = { x: 0, y: 0 };
let currentChartSelectionRange = null;
let selectionMode = false;
// For boxplot / category handling
let currentChartColumnOrder = [];

// Advanced Analysis State
let advancedAnalysisResults = null;
let latestImportantFactors = [];
let lastSelectedIndexMap = {}; // For multi-select chips

// --- Main Analysis Entry ---

export async function analyzeFile(filename) {
    analysisFilename = filename;
    originalTableData = [];
    activeFilters = [];

    // 1. Reset Chart Configuration and UI
    clearChartConfig();
    resetAdvancedResults();
    latestImportantFactors = [];
    currentChartColumnOrder = []; // Reset column order for new file

    // Reset specific UI
    const summaryDiv = document.getElementById('ai-summary-result'); // If exists
    if (summaryDiv) summaryDiv.innerHTML = '';


    // 2. Switch to Table View
    switchAnalysisMode('table');
    switchView('analysis');
    await loadAnalysisPage(-1);
}

export async function loadAnalysisPage(page) {
    analysisCurrentPage = page;
    DOM.setText('analysis-filename', analysisFilename);
    const contentDiv = DOM.get('analysis-content');

    if (originalTableData.length === 0 || page === -1) {
        contentDiv.innerHTML = '<div style="text-align: center; color: #64748b; padding: 40px;">⏳ 正在由伺服器下載全量數據 (預計 1-3 秒)...</div>';
        try {
            const sid = window.SESSION_ID || SESSION_ID;
            const infoRes = await fetch(`/api/view_file/${analysisFilename}?page=1&page_size=1&session_id=${sid}`);
            const infoData = await infoRes.json();
            analysisTotalLines = infoData.total_lines || 0;
            DOM.setText('analysis-header-count', `(總計 ${analysisTotalLines - 1} 筆數據)`);

            if (analysisFilename.toLowerCase().endsWith('.csv')) {
                tableHeaders = infoData.content.trim().split('\n')[0].split(',').map(h => h.trim());
                visibleColumnIndices = tableHeaders.map((_, i) => i);

                const fullRes = await fetch(`/api/view_file/${analysisFilename}?page=1&page_size=1000000&session_id=${sid}`);
                const fullData = await fullRes.json();
                const lines = fullData.content.trim().split('\n');
                originalTableData = lines.slice(1).map((row, idx) => {
                    const arr = row.split(',').map(c => c.trim());
                    arr.__idx = idx;
                    return arr;
                });
            } else {
                const res = await fetch(`/api/view_file/${analysisFilename}?page=1&page_size=5000&session_id=${sid}`);
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

    analysisCurrentPage = page === -1 ? 1 : page;
    renderTable(tableHeaders, originalTableData, analysisCurrentPage, analysisTotalLines);
    updateFilterBar();
}

function getFilteredRows(data) {
    if (!data) return [];
    return data.filter(row => {
        const colFilters = {};
        activeFilters.forEach(f => {
            if (!colFilters[f.colIdx]) colFilters[f.colIdx] = [];
            colFilters[f.colIdx].push(f);
        });

        return Object.values(colFilters).every(filters => {
            const indexKeepFilters = filters.filter(f => f.type === 'indices');
            const indexExcludeFilters = filters.filter(f => f.type === 'exclude_indices');

            if (indexKeepFilters.length > 0 || indexExcludeFilters.length > 0) {
                if (row.__idx === undefined) row.__idx = originalTableData.indexOf(row);
                const origIdx = row.__idx;

                let passed = true;
                if (indexKeepFilters.length > 0) {
                    passed = indexKeepFilters.every(f => f.indices.includes(origIdx));
                }
                if (passed && indexExcludeFilters.length > 0) {
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
    let filteredRows = getFilteredRows(rows);

    const headerCount = DOM.get('analysis-header-count');
    if (headerCount) {
        headerCount.innerHTML = `(目前顯示: <b style="color: #3b82f6;">${filteredRows.length}</b> / 總計: ${totalLines - 1})`;
    }

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

    const pageSize = 100;
    const totalPages = Math.ceil(filteredRows.length / pageSize);
    if (currentPage > totalPages && totalPages > 0) currentPage = 1;
    if (currentPage < 1) currentPage = 1;

    const start = (currentPage - 1) * pageSize;
    const end = start + pageSize;
    const rowsToDisplay = filteredRows.slice(start, end);

    let html = '<div class="analysis-table-container"><table class="analysis-table"><thead><tr>';
    visibleColumnIndices.forEach(idx => {
        const h = headers[idx];
        const sortIcon = currentSortColumn === idx ? (currentSortOrder === 'asc' ? ' 🔼' : ' 🔽') : '';
        html += `<th onclick="window.handleSort(${idx}, '${h}')">${h}${sortIcon}</th>`;
    });
    html += '</tr></thead><tbody>';

    rowsToDisplay.forEach(row => {
        html += '<tr>';
        visibleColumnIndices.forEach(idx => {
            html += `<td>${row[idx] || ''}</td>`;
        });
        html += '</tr>';
    });
    html += '</tbody></table></div>';

    if (rowsToDisplay.length === 0) {
        DOM.setHTML('analysis-content', `<div style="text-align:center; padding:40px; color:#94a3b8;">無符合篩選條件的數據</div>`);
    } else {
        DOM.setHTML('analysis-content', html);
    }

    renderPagination(currentPage, totalLines, filteredRows.length);
}

// --- Filtering ---
export function updateFilterBar() {
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

export function toggleFilterMenu(event) {
    if (event) event.stopPropagation();
    const menu = DOM.get('filter-menu');
    const isVisible = menu.style.display === 'flex';

    if (!isVisible) {
        const select = DOM.get('filter-column-select');
        select.innerHTML = tableHeaders.map((h, i) => `<option value="${i}">${h}</option>`).join('');
        menu.style.display = 'flex';
        DOM.get('filter-value-input').focus();
        DOM.get('filter-not-empty-check').checked = false;

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

export function addFilterFromMenu() {
    const select = DOM.get('filter-column-select');
    const input = DOM.get('filter-value-input');
    const notEmptyCheck = DOM.get('filter-not-empty-check');
    const colIdx = parseInt(select.value);
    const colName = tableHeaders[colIdx];
    const value = input.value.trim();
    const isNotEmpty = notEmptyCheck.checked;

    if (value || isNotEmpty) {
        if (isNotEmpty) activeFilters.push({ colIdx, colName, value: '', type: 'not_empty' });
        else if (value) activeFilters.push({ colIdx, colName, value, type: 'text' });

        input.value = "";
        notEmptyCheck.checked = false;
        DOM.get('filter-menu').style.display = 'none';
        updateFilterBar();
        renderTable(tableHeaders, originalTableData, 1, analysisTotalLines);
    }
}

export function removeFilter(idx) {
    activeFilters.splice(idx, 1);
    renderTable(tableHeaders, originalTableData, 1, analysisTotalLines);
    updateFilterBar();
    if (DOM.get('analysis-chart-view').style.display !== 'none') renderAnalysisChart();
}

export function resetAllFilters() {
    activeFilters = [];
    renderTable(tableHeaders, originalTableData, 1, analysisTotalLines);
    updateFilterBar();
    if (DOM.get('analysis-chart-view').style.display !== 'none') renderAnalysisChart();
}

export function handleSort(colIdx, headerText) {
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
    const countForCalc = filteredCount > 0 ? filteredCount : 1;
    const totalPages = Math.ceil(countForCalc / pageSize);
    const container = DOM.get('analysis-pagination-container');
    const showNavigation = totalPages > 1;

    let html = `
        <div class="pagination-bar">
            <div style="flex: 1;"></div>
            <div style="flex: 1; display: flex; align-items: center; justify-content: center; gap: 15px;">
                ${showNavigation ? `
                    <button class="btn-page" onclick="window.loadAnalysisPage(${currentPage - 1})" ${currentPage <= 1 ? 'disabled' : ''}>上一頁</button>
                    <span class="page-info">第 ${currentPage} / ${totalPages} 頁</span>
                    <button class="btn-page" onclick="window.loadAnalysisPage(${currentPage + 1})" ${currentPage >= totalPages ? 'disabled' : ''}>下一頁</button>
                ` : `<div class="page-info" style="color: #64748b;">第 1 / 1 頁</div>`}
            </div>
            <div style="flex: 1; font-size: 13px; color: #64748b; font-weight: 600; text-align: right;">
                總計: ${filteredCount} 筆 (原始: ${totalLines - 1})
            </div>
        </div>
    `;
    container.innerHTML = html;
}

// --- Analysis Chart ---

// --- Column Picker Functions ---
export function openColumnPicker() {
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

export function closeColumnPicker() {
    document.getElementById('col-picker-modal').style.display = 'none';
}

export function toggleColCheckbox(event, idx) {
    const cb = document.getElementById(`col-check-${idx}`);
    if (cb) cb.checked = !cb.checked;
    updateColSelectCount();
}

export function toggleAllColumns(isSelected) {
    const checkboxes = document.querySelectorAll('#col-picker-list input[type="checkbox"]');
    checkboxes.forEach(cb => {
        if (cb.parentElement.style.display !== 'none') {
            cb.checked = isSelected;
        }
    });
    updateColSelectCount();
}

export function filterColumnList() {
    const q = document.getElementById('col-search-input').value.toLowerCase();
    const items = document.querySelectorAll('.col-item');
    items.forEach(item => {
        const text = item.querySelector('label').innerText.toLowerCase();
        item.style.display = text.includes(q) ? 'flex' : 'none';
    });
}

export function updateColSelectCount() {
    const total = tableHeaders.length;
    const selected = document.querySelectorAll('#col-picker-list input[type="checkbox"]:checked').length;
    const cnt = document.getElementById('col-select-count');
    if (cnt) cnt.innerText = `已選擇: ${selected} / ${total} 欄位`;
}

export function applyColumnVisibility() {
    const checkboxes = document.querySelectorAll('#col-picker-list input[type="checkbox"]');
    visibleColumnIndices = [];
    checkboxes.forEach((cb, i) => {
        if (cb.checked) visibleColumnIndices.push(i);
    });

    closeColumnPicker();
    renderTable(tableHeaders, originalTableData, 1, analysisTotalLines);
}

export function switchAnalysisMode(mode) {
    const btnTable = document.getElementById('btn-mode-table');
    const btnChart = document.getElementById('btn-mode-chart');
    const viewTable = document.getElementById('analysis-table-container') || document.getElementById('analysis-table-view'); // Align with HTML ID
    const viewChart = document.getElementById('analysis-chart-view');
    // const filterBar = document.getElementById('filter-bar-area'); // Keep visible

    if (mode === 'table') {
        if (viewTable) viewTable.style.display = 'block';
        if (viewChart) viewChart.style.display = 'none';
        if (btnTable) {
            btnTable.style.background = '#fff';
            btnTable.style.color = '#3b82f6';
            btnTable.style.boxShadow = '0 1px 2px rgba(0,0,0,0.1)';
        }
        if (btnChart) {
            btnChart.style.background = 'transparent';
            btnChart.style.color = '#64748b';
            btnChart.style.boxShadow = 'none';
        }
    } else {
        if (viewTable) viewTable.style.display = 'none';
        if (viewChart) viewChart.style.display = 'flex'; // Flex for layout
        if (btnChart) {
            btnChart.style.background = '#fff';
            btnChart.style.color = '#7e22ce';
            btnChart.style.boxShadow = '0 1px 2px rgba(0,0,0,0.1)';
        }
        if (btnTable) {
            btnTable.style.background = 'transparent';
            btnTable.style.color = '#64748b';
            btnTable.style.boxShadow = 'none';
        }
        initChartColumns();
        // Ensure chart is fresh and resized
        setTimeout(() => {
            renderAnalysisChart();
            if (analysisChart) analysisChart.resize();
        }, 50);
    }
}

export function initChartColumns() {
    const container = document.getElementById('chart-column-source');
    if (!container) return;
    container.innerHTML = ''; // Clear

    // Update UI Button area based on state
    const btnContainer = document.getElementById('adv-selection-container');
    if (btnContainer) {
        if (advancedAnalysisResults) {
            const { target } = advancedAnalysisResults;
            btnContainer.innerHTML = `
                <div style="background: #eff6ff; border: 1px solid #93c5fd; border-radius: 6px; padding: 10px; margin-bottom: 8px;">
                    <div style="font-size: 11px; font-weight: bold; color: #1e40af; margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center;">
                        <span>🎯 分析目標: ${target}</span>
                        <button onclick="window.resetAdvancedResults()" style="background:#f1f5f9; border:none; color:#64748b; cursor:pointer; font-size:12px; padding:2px 6px; border-radius:4px; font-weight:bold;">清除</button>
                    </div>
                    <button onclick="window.openAdvancedModal()" style="width: 100%; padding: 5px; border: 1px solid #93c5fd; border-radius: 4px; background: #fff; color: #2563eb; font-size: 11px; cursor: pointer; font-weight: bold;">重新分析</button>
                </div>
            `;
        } else {
            btnContainer.innerHTML = `
                <button onclick="window.openAdvancedModal()" class="btn-adv-selection">
                    <span>🔍</span> 進階挑選(分析影響力)
                </button>
            `;
        }
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
            const currentIndex = allChips.indexOf(chip);
            const listId = 'chart-cols';

            if (isShift && lastSelectedIndexMap[listId] !== undefined) {
                const start = Math.min(currentIndex, lastSelectedIndexMap[listId]);
                const end = Math.max(currentIndex, lastSelectedIndexMap[listId]);
                allChips.forEach((c, i) => {
                    if (i >= start && i <= end) c.classList.add('selected');
                    else if (!isCtrl) c.classList.remove('selected');
                });
            } else if (isCtrl) {
                chip.classList.toggle('selected');
                if (chip.classList.contains('selected')) lastSelectedIndexMap[listId] = currentIndex;
            } else {
                allChips.forEach(c => c.classList.remove('selected'));
                chip.classList.add('selected');
                lastSelectedIndexMap[listId] = currentIndex;
            }
        };

        chip.ondragstart = (e) => {
            // 優化效能：僅在必要時操作 DOM
            if (!chip.classList.contains('selected')) {
                const selected = container.querySelector('.draggable-chip.selected');
                if (selected) {
                    // 如果有選取的，但拖曳的是非選取的項目，則清除所有其他項目的選取狀態
                    const allChips = container.querySelectorAll('.draggable-chip.selected');
                    allChips.forEach(c => c.classList.remove('selected'));
                }
                chip.classList.add('selected');
            }

            const selectedChips = container.querySelectorAll('.draggable-chip.selected');
            const data = Array.from(selectedChips).map(c => c.dataset.header);

            // 儲存為 JSON 並提供純文字 fallback
            e.dataTransfer.setData("text", JSON.stringify(data));
            e.dataTransfer.setData("text/plain", data[0] || chip.dataset.header);

            // 設置拖曳效果
            e.dataTransfer.effectAllowed = "copyMove";
        };

        container.appendChild(chip);
    });
}

export function allowDrop(ev) {
    ev.preventDefault();
    ev.dataTransfer.dropEffect = "copy";
    const dropzone = ev.target.closest('.axis-dropzone');
    if (dropzone) dropzone.classList.add('drag-over');
}

export function handleDragLeave(ev) {
    const dropzone = ev.target.closest('.axis-dropzone');
    if (dropzone) dropzone.classList.remove('drag-over');
}

export function handleDrop(ev, axis) {
    ev.preventDefault();
    const dropzone = ev.target.closest('.axis-dropzone');
    if (dropzone) dropzone.classList.remove('drag-over');

    let colData = ev.dataTransfer.getData("text");
    if (!colData) return;

    let finalCol = "";
    try {
        // 嘗試解析 JSON 陣列
        const parsed = JSON.parse(colData);
        if (Array.isArray(parsed)) {
            finalCol = parsed[0]; // 軸向目前僅取第一個
        } else {
            finalCol = parsed;
        }
    } catch (e) {
        // 非 JSON 格式，直接使用
        finalCol = colData;
    }

    if (finalCol) {
        chartConfig[axis] = finalCol;
        updateDropzoneUI(axis, finalCol);

        // ✨ 自動初始化：當 X 或 Y 只有其中一個有值時，另一個先預設為 'index'
        if (axis === 'x') {
            if (!chartConfig.y && !chartConfig.y2) {
                chartConfig.y = 'index';
                updateDropzoneUI('y', 'index');
            }
        } else if (axis === 'y' || axis === 'y2') {
            if (!chartConfig.x) {
                chartConfig.x = 'index';
                updateDropzoneUI('x', 'index');
            }
        }

        tryUpdateChart();
        updateChartSourceInfo();
    }
}

export function handleMainChartDrop(ev) {
    ev.preventDefault();
    let colData = ev.dataTransfer.getData("text");
    if (!colData) return;

    let colName = "";
    try {
        const parsed = JSON.parse(colData);
        colName = Array.isArray(parsed) ? parsed[0] : parsed;
    } catch (e) {
        colName = colData;
    }

    if (!colName) return;

    // 1. Set Y Axis
    chartConfig.y = colName;
    updateDropzoneUI('y', colName);

    // 2. Auto-set X Axis to 'index' if empty
    if (!chartConfig.x) {
        chartConfig.x = 'index';
        updateDropzoneUI('x', 'index');
    }

    tryUpdateChart();
    updateChartSourceInfo();
}

function updateDropzoneUI(axis, colName) {
    const dropzone = DOM.get('drop-' + axis);
    if (!dropzone) return;

    const isVertical = axis === 'y' || axis === 'y2';
    const style = isVertical ? 'writing-mode: vertical-rl; text-orientation: mixed;' : '';

    // Using simple HTML without the cycle buttons for now to save space, unless strongly requested.
    // Ideally we should include cycle buttons.
    dropzone.innerHTML = `
        <div style="display:flex; align-items:center; gap:4px; width:100%; justify-content:center; ${isVertical ? 'flex-direction:column;' : ''}">
             <span onclick="window.cycleChartAxis('${axis}', -1)" style="cursor:pointer; font-size:10px;">▲</span>
             <span style="color: #2563eb; font-weight: bold; white-space:nowrap; ${style}">${colName}</span>
             <span onclick="window.cycleChartAxis('${axis}', 1)" style="cursor:pointer; font-size:10px;">▼</span>
             <span style="font-size:10px; cursor:pointer; color:#ef4444;" onclick="window.resetAxis('${axis}')">✕</span>
        </div>`;
    dropzone.classList.add('filled');
}

export function cycleChartAxis(axis, offset) {
    if (!chartConfig[axis]) return;
    if (axis === 'x') return; // Disable X cycling

    const visibleHeaders = currentChartColumnOrder.length > 0 ? currentChartColumnOrder : tableHeaders;
    const currentName = chartConfig[axis];
    const currentIndex = visibleHeaders.indexOf(currentName);
    if (currentIndex === -1) return;

    let newIndex = (currentIndex + offset);
    if (newIndex < 0) newIndex = visibleHeaders.length - 1;
    if (newIndex >= visibleHeaders.length) newIndex = 0;

    const nextCol = visibleHeaders[newIndex];
    chartConfig[axis] = nextCol;

    // Clear correlation results
    const resDiv = DOM.get('correlation-result');
    if (resDiv) resDiv.innerHTML = '';

    if (axis === 'x' && nextCol === 'index') {
        // Skip index if waiting for real columns, OR allow it?
        // Let's allow cycling into index? No, current logic cycles through headers.
        // If x is 'index', nextCol will probably be headers[0].
    }

    updateDropzoneUI(axis, nextCol);

    // Sync Highlight in Side List
    const container = DOM.get('chart-column-source');
    if (container) {
        const chips = container.querySelectorAll('.draggable-chip');
        chips.forEach(chip => {
            // Only clear outline if it's purely a temporary selection highlight
            // (But here we just clear all outline to be safe, assuming border handle by class)
            // Wait, chips use border for status (target/ai), outline for selection.
            chip.style.outline = 'none';
            chip.style.boxShadow = 'none';
        });
        for (const chip of chips) {
            // Note: chip text might contain score like "ColName (0.9)" or just "ColName"
            // Use dataset if available, fallback to text check
            const chipHeader = chip.dataset.header || chip.innerText;
            if (chipHeader === nextCol || chip.innerText.trim() === nextCol) {
                chip.style.outline = '2px solid #a855f7';
                chip.style.boxShadow = '0 0 8px rgba(168, 85, 247, 0.4)';
                chip.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                break;
            }
        }
    }

    tryUpdateChart();
    updateChartSourceInfo();
}


export function resetAxis(axis) {
    const colName = chartConfig[axis];
    chartConfig[axis] = null;
    const dropzone = DOM.get('drop-' + axis);
    if (dropzone) {
        dropzone.classList.remove('filled');
        dropzone.innerHTML = `<span class="placeholder">拖曳至此</span>`;
    }

    // ✨ UI Sync: Clear highlight in side list if exists
    if (colName) {
        const container = DOM.get('chart-column-source');
        if (container) {
            const chips = container.querySelectorAll('.draggable-chip');
            chips.forEach(chip => {
                const h = chip.dataset.header || chip.innerText.trim();
                if (h === colName) {
                    chip.style.outline = 'none';
                    chip.style.boxShadow = 'none';
                }
            });
        }
    }

    updateChartSourceInfo();
    tryUpdateChart(); // Re-render if partial config exists
}

export function clearChartConfig() {
    chartConfig = { x: null, y: null, y2: null, type: 'scatter' };
    if (analysisChart) {
        analysisChart.destroy();
        analysisChart = null;
    }
    const axes = ['x', 'y', 'y2'];
    axes.forEach(axis => {
        const dropzone = DOM.get('drop-' + axis);
        if (dropzone) {
            dropzone.classList.remove('filled');
            dropzone.innerHTML = `<span class="placeholder">拖曳至此</span>`;
        }
    });
    const sourceContainer = DOM.get('chart-column-source');
    if (sourceContainer) sourceContainer.innerHTML = '';
}

export function tryUpdateChart() {
    if (chartConfig.x && (chartConfig.y || chartConfig.y2)) {
        renderAnalysisChart();
    } else {
        // ✨ FIX: If configuration is incomplete, clear the chart instead of keeping the old one
        if (typeof analysisChart !== 'undefined' && analysisChart) {
            analysisChart.destroy();
            analysisChart = null;
        }
        updateChartSourceInfo();
    }
}


export function renderAnalysisChart() {
    const canvas = document.getElementById('analysis-chart-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    if (analysisChart) analysisChart.destroy();

    // Prepare Data Indices
    const xIdx = chartConfig.x === 'index' ? -2 : tableHeaders.indexOf(chartConfig.x);
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
    let dataPoints1 = [];
    let dataPoints2 = [];

    // --- DATA PREPARATION STRATEGY ---

    if (chartType === 'boxplot') {
        isNumericX = false;
        const groups = {};

        sourceRows.forEach((row, i) => {
            let xVal;
            if (chartConfig.x === 'index') xVal = i + 1; // Use 1-based index
            else xVal = row[xIdx];
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

        dataPoints1 = [];
        dataPoints2 = [];

        for (let i = 0; i < sourceRows.length; i += step) {
            const row = sourceRows[i];
            let xVal;
            if (chartConfig.x === 'index') xVal = i + 1;
            else xVal = row[xIdx];
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
    if (typeof window.updateChartAnalysisData === 'function') {
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
        window.updateChartAnalysisData(chartConfig);
    }
}

export function clearChartColSearch() {
    const input = document.getElementById('chart-col-search');
    if (input) {
        input.value = '';
        filterChartColumns('');
        // Optional: focus back to input?
        // input.focus();
    }
}

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

// --- Quick Analysis ---

export async function quickAnalysis() {
    if (!analysisFilename) {
        alert("請先選擇要分析的檔案");
        if (window.openFileSelector) window.openFileSelector();
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
    const btn = (window.event && window.event.currentTarget) || document.activeElement;
    const originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '⏳ 全量空值分析中...';

    try {
        // 3. 呼叫後端 API 生成摘要
        const response = await fetch(`/api/analysis/quick_analysis?session_id=${SESSION_ID}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                filename: analysisFilename,
                headers: tableHeaders,
                rows: limitedRows,
                filters: activeFilters
            })
        });

        const result = await response.json();
        if (result.status === 'success') {
            // 4. 打開圖表 AI 助手
            const win = document.getElementById('chart-ai-assistant-window');
            if (win && !win.classList.contains('active')) {
                if (window.toggleChartAssistant) window.toggleChartAssistant();
            }

            // 5. 將摘要發送到 AI 聊天
            const input = document.getElementById('chart-chat-input');
            const summaryPrompt = `${result.summary} \n\n🤖 ** AI 指令 **: 請用極其簡短、精煉的 2~3 句話總結這份數據的關鍵發現或核心建議。`;

            // 模擬輸入並發送
            if (input) input.value = summaryPrompt;
            if (window.sendChartChatMessage) window.sendChartChatMessage();
        } else {
            alert("分析失敗: " + result.detail);
        }
    } catch (err) {
        console.error("Quick Analysis Error:", err);
        alert("連線分析服務失敗");
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = originalText;
        }
    }
}


export async function saveFilteredData() {
    if (!analysisFilename) {
        alert("請先選擇要分析的檔案");
        return;
    }
    const filteredRows = getFilteredRows(originalTableData);
    if (filteredRows.length === 0) return;

    const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    const defaultName = `${analysisFilename.replace('.csv', '')}_filtered_${timestamp}.csv`;
    const newName = prompt("請輸入新檔名:", defaultName);

    if (!newName) return;

    try {
        const response = await fetch(`/api/save_filtered_file?session_id=${SESSION_ID}`, {
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
            FileMgr.loadFileList();
        } else {
            alert("儲存失敗");
        }
    } catch (e) {
        console.error(e);
        alert("儲存錯誤");
    }
}

// --- Advanced Analysis (Placeholder for now, logic exists in full) ---
export function openAdvancedModal() {
    // Basic implementation
    const modal = document.getElementById('advanced-param-modal');
    if (!modal) return;
    const select = document.getElementById('adv-target-select');
    if (select) select.innerHTML = tableHeaders.map(h => `<option value="${h}">${h}</option>`).join('');
    modal.classList.add('show');
}

export function closeAdvancedModal() {
    const modal = document.getElementById('advanced-param-modal');
    if (modal) modal.classList.remove('show');
}

export async function runAdvancedAnalysis() {
    // Simplified run logic
    const target = document.getElementById('adv-target-select').value;
    const algo = document.querySelector('input[name="adv-algo"]:checked').value;

    // Call API...
    // Mock response for now or implement full fetch
    // Implementing full fetch
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
        if (data.status === 'success') {
            advancedAnalysisResults = { results: data.results, target, algo };
            initChartColumns();
            closeAdvancedModal();
        } else {
            alert("Analysis failed: " + data.detail);
        }
    } catch (e) {
        console.error(e);
        alert("Network Error");
    }
}

export function resetAdvancedResults() {
    advancedAnalysisResults = null;
    initChartColumns(); // Reload chips
}

export function filterChartColumns(query) {
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

// --- Selection Mode & Chart Types ---


export function toggleSelectionMode() {
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

export function setChartType(type) {
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
    document.getElementById(`btn-chart-${type}`).classList.add('active');

    // Re-render if possible
    if (chartConfig.x && (chartConfig.y || chartConfig.y2)) {
        renderAnalysisChart();
    }
}

// Global Exports
window.toggleSelectionMode = toggleSelectionMode;
window.setChartType = setChartType;
window.cycleChartAxis = cycleChartAxis;
window.resetAxis = resetAxis;
window.openAdvancedModal = openAdvancedModal;
window.closeAdvancedModal = closeAdvancedModal;
window.resetAdvancedResults = resetAdvancedResults;
window.filterChartColumns = filterChartColumns;
window.applySelectionAsFilter = applySelectionAsFilter;
window.clearChartSelection = clearChartSelection;
window.quickAnalysis = quickAnalysis;

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

export function clearChartSelection() {
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

export function applySelectionAsFilter(mode) {
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
            { id: 'uploadModal', close: window.closeUploadModal },
            { id: 'fileSelectorModal', close: window.closeFileSelector },
            { id: 'viewDataModal', close: window.closeViewModal },
            { id: 'advanced-param-modal', close: closeAdvancedModal },
            { id: 'col-picker-modal', close: closeColumnPicker }
        ];

        for (const m of modals) {
            const el = document.getElementById(m.id);
            if (el && (el.style.display === 'flex' || el.classList.contains('show'))) {
                if (typeof m.close === 'function') m.close();
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

// Window export for correlation
window.calculateCorrelation = calculateCorrelation;

// Global Chart Selection Handlers
// (Use setTimeout to ensure DOM is ready if imported early, though usually module is deferred)
setTimeout(() => {
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

        // Threshold to avoid accidental clicks
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

}, 500); // Small delay to ensure HTML is parsed
