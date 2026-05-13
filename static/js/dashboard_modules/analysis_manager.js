import { DOM, API, WINDOW_SIZE } from './utils.js';
import { SESSION_ID } from './session.js';

// Safe imports: switchView and FileMgr may not be available in iframe context
let switchView, FileMgr;
try {
    const uiCore = await import('./ui_core.js');
    switchView = uiCore.switchView;
} catch (e) {
    switchView = () => {}; // No-op in iframe
}
try {
    FileMgr = await import('./file_manager.js');
} catch (e) {
    FileMgr = { loadFileList: () => {} }; // No-op in iframe
}

// --- CSV Parser (handles quoted fields with commas) ---
function _parseCsvLine(line) {
    const result = [];
    let cur = '';
    let inQuotes = false;
    for (let i = 0; i < line.length; i++) {
        const ch = line[i];
        if (inQuotes) {
            if (ch === '"') {
                if (i + 1 < line.length && line[i + 1] === '"') {
                    cur += '"'; i++; // escaped quote
                } else {
                    inQuotes = false;
                }
            } else {
                cur += ch;
            }
        } else {
            if (ch === '"') {
                inQuotes = true;
            } else if (ch === ',') {
                result.push(cur.trim());
                cur = '';
            } else {
                cur += ch;
            }
        }
    }
    result.push(cur.trim());
    return result;
}

// --- Full CSV content parser (handles multi-line quoted fields from Excel Alt+Enter) ---
// Returns array of rows, where each row is an array of field strings.
function _parseCsvContent(content) {
    const rows = [];
    let cur = '';
    let inQuotes = false;
    let currentRow = [];
    for (let i = 0; i < content.length; i++) {
        const ch = content[i];
        if (inQuotes) {
            if (ch === '"') {
                if (i + 1 < content.length && content[i + 1] === '"') {
                    cur += '"'; i++; // escaped quote
                } else {
                    inQuotes = false;
                }
            } else if (ch === '\r') {
                // ignore carriage returns inside quoted field
            } else if (ch === '\n') {
                cur += ' '; // Convert embedded newlines to space (Excel Alt+Enter cells)
            } else {
                cur += ch;
            }
        } else {
            if (ch === '"') {
                inQuotes = true;
            } else if (ch === ',') {
                currentRow.push(cur.trim());
                cur = '';
            } else if (ch === '\r') {
                // ignore carriage returns
            } else if (ch === '\n') {
                currentRow.push(cur.trim());
                cur = '';
                rows.push(currentRow);
                currentRow = [];
            } else {
                cur += ch;
            }
        }
    }
    // Push last field/row
    currentRow.push(cur.trim());
    if (currentRow.some(f => f !== '')) rows.push(currentRow);
    return rows;
}

// --- Column Alias (from localStorage, set by file_manager) ---
function _applyAliases(headers) {
    try {
        if (localStorage.getItem('sigma2_useAlias') !== '1') return headers;
        const map = JSON.parse(localStorage.getItem('sigma2_aliases') || '{}');
        if (!map || Object.keys(map).length === 0) return headers;
        return headers.map(h => map[h] || h);
    } catch (_) {
        return headers;
    }
}

// --- Constants & State ---
let analysisCurrentPage = 1;
let analysisFilename = '';
export let originalTableData = []; // Export for external access if needed
export let tableHeaders = [];
export let analysisTotalLines = 0;

// 使用者手動覆蓋的欄位型別 { colName: '數值'|'類別'|'文字'|'日期' }
let _colTypeOverrides = {};
const _DTYPE_CYCLE = ['數值', '類別', '文字', '日期'];
const _DTYPE_STYLE = {
    '數值': { color: '#16a34a', bg: '#dcfce7' },
    '類別': { color: '#9333ea', bg: '#faf5ff' },
    '文字': { color: '#64748b', bg: '#f1f5f9' },
    '日期': { color: '#0369a1', bg: '#e0f2fe' },
};
function _getDtype(header, inferredDtype) {
    return _colTypeOverrides[header] || inferredDtype;
}
function _fileStem(filename) {
    return filename ? filename.replace(/\.[^.]+$/, '') : null;
}
function _getSessionId() {
    let sid = localStorage.getItem('sigma2_session_id');
    if (!sid) { sid = 'sess-' + Math.random().toString(36).substr(2,9) + Date.now().toString(36); localStorage.setItem('sigma2_session_id', sid); }
    return sid;
}
function _saveDtypeOverrides(filename) {
    const stem = _fileStem(filename);
    if (!stem) return;
    const sid = _getSessionId();
    const payload = JSON.stringify({ col_types: _colTypeOverrides });
    // Save file-specific
    fetch(`/api/files/col_types?session_id=${encodeURIComponent(sid)}&file_stem=${encodeURIComponent(stem)}`, {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: payload
    }).catch(() => {});
    // Also merge into global store (so new files with same column names inherit)
    fetch(`/api/files/col_types?session_id=${encodeURIComponent(sid)}&file_stem=__global__`, {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: payload
    }).catch(() => {});
}
async function _loadDtypeOverrides(filename) {
    _colTypeOverrides = {};
    const stem = _fileStem(filename);
    if (!stem) return;
    const sid = _getSessionId();
    try {
        // 1. Load global defaults first (columns set in any previous file)
        let globalTypes = {};
        const rg = await fetch(`/api/files/col_types?session_id=${encodeURIComponent(sid)}&file_stem=__global__`);
        if (rg.ok) {
            const dg = await rg.json();
            globalTypes = dg.col_types || {};
            Object.assign(_colTypeOverrides, globalTypes);
        }
        // 2. Load file-specific overrides (takes priority over global)
        let fileTypes = {};
        const r = await fetch(`/api/files/col_types?session_id=${encodeURIComponent(sid)}&file_stem=${encodeURIComponent(stem)}`);
        if (r.ok) {
            const d = await r.json();
            fileTypes = d.col_types || {};
            Object.assign(_colTypeOverrides, fileTypes);
        }
        // 3. Bootstrap: if this file had settings not yet in global, propagate them now
        const newEntries = {};
        for (const [col, type] of Object.entries(fileTypes)) {
            if (!globalTypes[col]) newEntries[col] = type;
        }
        if (Object.keys(newEntries).length > 0) {
            fetch(`/api/files/col_types?session_id=${encodeURIComponent(sid)}&file_stem=__global__`, {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ col_types: newEntries })
            }).catch(() => {});
        }
    } catch(e) {}
}
function _renderDtypeBadge(header, dtype) {
    const s = _DTYPE_STYLE[dtype] || _DTYPE_STYLE['文字'];
    return `<span class="dtype-badge" data-col="${header.replace(/"/g,'&quot;')}" title="點擊切換型別" style="font-size:10px;color:${s.color};background:${s.bg};border:1px solid ${s.color}33;padding:2px 6px;border-radius:4px;flex-shrink:0;cursor:pointer;pointer-events:auto;min-width:28px;text-align:center;">${dtype}</span>`;
}

// Allow external modules to refresh the table display
export function refreshTableDisplay() {
    renderTable(tableHeaders, originalTableData, 1, analysisTotalLines);
}

export function addVisibleColumn(idx) {
    if (!visibleColumnIndices.includes(idx)) visibleColumnIndices.push(idx);
}

let currentSortColumn = -1;
let currentSortOrder = 'asc';
let activeFilters = [];
let visibleColumnIndices = [];

// --- Loading Overlay Helpers ---
function _showLoading() {
    const el = document.getElementById('global-loading-overlay');
    if (el) el.style.display = 'flex';
}
function _hideLoading() {
    const el = document.getElementById('global-loading-overlay');
    if (el) el.style.display = 'none';
}

// Datetime X axis mode: 'timegap' = linear scale with gaps (no boxplot), 'category' = category scale (boxplot ok)
let datetimeXMode = 'timegap';

export function toggleDatetimeMode(mode) {
    if (mode) datetimeXMode = mode;
    else datetimeXMode = datetimeXMode === 'timegap' ? 'category' : 'timegap';
    // Sync radio buttons
    const radios = document.querySelectorAll('input[name="datetime-mode"]');
    radios.forEach(r => { r.checked = r.value === datetimeXMode; });
    _updateScatterAvailability();
    tryUpdateChart();
    extraPanels.forEach(p => _renderExtraPanel(p));
}

// Chart State
let chartConfig = { x: null, y: null, y2: null, type: 'scatter',
    yColor: '#7c3aed', y2Color: '#06b6d4',
    yMin: null, yMax: null, y2Min: null, y2Max: null,
    yFeature: null, y2Feature: null };
let analysisChart = null; // Chart.js instance

// Dynamic extra chart panels
let extraPanels = []; // [{ id, yLeft, yRight, chart, type, yLeftColor, yRightColor, ... }]
let _panelIdCounter = 0;
let _xManuallyClearedByUser = false; // Prevents auto-fill of X after user explicitly clears it
let _yAxisPopupState = { panelId: null, axis: null };
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
    // Always close popup/backdrop on file load
    closeYAxisPopup();

    analysisFilename = filename;
    originalTableData = [];
    activeFilters = [];
    _loadDtypeOverrides(filename); // 載入此檔案的欄位型別設定

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
    _showLoading();
    analysisCurrentPage = page;
    DOM.setText('analysis-filename', analysisFilename);
    const contentDiv = DOM.get('analysis-content');

    if (originalTableData.length === 0 || page === -1) {
        contentDiv.innerHTML = '<div style="text-align: center; color: #64748b; padding: 40px;">⏳ 正在由伺服器下載全量數據 (預計 1-3 秒)...</div>';
        try {
            const sid = window.SESSION_ID || SESSION_ID;
            // Use page_size=50 to ensure multi-line quoted header cells are fully captured
            // (Excel Alt+Enter cells export as multi-raw-line quoted fields in CSV)
            const infoRes = await fetch(`/api/view_file/${analysisFilename}?page=1&page_size=50&session_id=${sid}`);
            const infoData = await infoRes.json();
            analysisTotalLines = infoData.total_lines || 0;
            DOM.setText('analysis-header-count', `(載入中...)`);

            if (analysisFilename.toLowerCase().endsWith('.csv')) {
                const parsedInfo = _parseCsvContent(infoData.content.trim());
                tableHeaders = parsedInfo[0] || [];
                // Apply column aliases if enabled
                tableHeaders = _applyAliases(tableHeaders);
                visibleColumnIndices = tableHeaders.map((_, i) => i);

                const totalRows = analysisTotalLines - 1; // Exclude header (may be slightly off for multi-line headers)
                const totalCells = totalRows * tableHeaders.length;
                const isLargeFile = totalCells > 5000000;

                if (isLargeFile) {
                    // Show control bar + load with default settings
                    const previewCount = window._largePreviewCount || 1000;
                    const previewMode = window._largePreviewMode || 'sample'; // 'head' or 'sample'
                    // 確保全域變數有值，供框選擴散判斷用
                    window._largePreviewMode = previewMode;
                    window._largePreviewCount = previewCount;

                    contentDiv.innerHTML = `<div style="text-align:center;padding:20px;color:#64748b;">⏳ 載入預覽中...</div>`;

                    // Insert control bar (only once)
                    let ctrlBar = document.getElementById('large-preview-ctrl');
                    if (!ctrlBar) {
                        ctrlBar = document.createElement('div');
                        ctrlBar.id = 'large-preview-ctrl';
                        ctrlBar.style.cssText = 'background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:10px 16px;margin-bottom:8px;font-size:13px;color:#92400e;display:flex;align-items:center;gap:10px;flex-wrap:wrap;';
                        ctrlBar.innerHTML = `
                            <span>⚠️ 大型資料集 (${totalRows.toLocaleString()} 行 × ${tableHeaders.length} 欄)</span>
                            <select id="preview-mode-select" style="padding:3px 6px;border-radius:4px;border:1px solid #fde68a;font-size:12px;">
                                <option value="head" ${previewMode==='head'?'selected':''}>前 N 筆</option>
                                <option value="sample" ${previewMode==='sample'?'selected':''}>等距取樣</option>
                            </select>
                            <input id="preview-count-input" type="number" value="${previewCount}" min="10" max="10000" step="50"
                                style="width:70px;padding:3px 6px;border-radius:4px;border:1px solid #fde68a;font-size:12px;text-align:center;">
                            <span style="font-size:11px;color:#b45309;">筆</span>
                            <button onclick="window.applyLargePreview()" style="padding:3px 10px;border-radius:4px;border:1px solid #d97706;background:#fef3c7;color:#92400e;font-size:12px;cursor:pointer;font-weight:600;">套用</button>
                        `;
                        contentDiv.parentElement.insertBefore(ctrlBar, contentDiv);
                    }

                    // Fetch data based on mode
                    let fetchUrl;
                    if (previewMode === 'sample') {
                        fetchUrl = `/api/view_file/${analysisFilename}?page=1&page_size=1000000&sample_count=${previewCount}&session_id=${sid}`;
                    } else {
                        fetchUrl = `/api/view_file/${analysisFilename}?page=1&page_size=${previewCount + 1}&session_id=${sid}`;
                    }
                    const previewRes = await fetch(fetchUrl);
                    const previewData = await previewRes.json();
                    const parsedPreview = _parseCsvContent(previewData.content.trim());
                    originalTableData = parsedPreview.slice(1).map((arr, idx) => {
                        arr.__idx = idx;
                        return arr;
                    });
                } else {
                    // Normal file: remove large-dataset banner if present from previous file
                    const oldCtrl = document.getElementById('large-preview-ctrl');
                    if (oldCtrl) oldCtrl.remove();
                    // Load all at once
                    const fullRes = await fetch(`/api/view_file/${analysisFilename}?page=1&page_size=1000000&session_id=${sid}`);
                    const fullData = await fullRes.json();
                    const parsedFull = _parseCsvContent(fullData.content.trim());
                    originalTableData = parsedFull.slice(1).map((arr, idx) => {
                        arr.__idx = idx;
                        return arr;
                    });
                    // Correct the row count using actual parsed data (server count may be inflated by embedded newlines in headers)
                    analysisTotalLines = originalTableData.length + 1;
                    DOM.setText('analysis-header-count', `(目前顯示: ${originalTableData.length} / 總計: ${originalTableData.length} | 欄位: ${tableHeaders.length})`);
                }
            } else {
                const res = await fetch(`/api/view_file/${analysisFilename}?page=1&page_size=5000&session_id=${sid}`);
                const data = await res.json();
                contentDiv.innerHTML = `<div class="analysis-table-container"><pre style="font-family: monospace; white-space: pre-wrap; padding: 15px;">${data.content}</pre></div>`;
                renderPagination(1, analysisTotalLines, 0);
                _hideLoading();
                return;
            }
        } catch (err) {
            contentDiv.innerHTML = `<div style="color: red; text-align: center; padding: 40px;">載入失敗: ${err.message}</div>`;
            _hideLoading();
            return;
        }
    }

    analysisCurrentPage = page === -1 ? 1 : page;
    renderTable(tableHeaders, originalTableData, analysisCurrentPage, analysisTotalLines);
    updateFilterBar();
    _hideLoading();
}

function getFilteredRows(data) {
    if (!data) return [];
    return data.filter(row => {
        const colFilters = {};
        activeFilters.forEach(f => {
            // 跳過純顯示用的 filter（擴散框選後的資訊 pill）
            if (f.type === 'time_range_display' || f.type === 'exclude_time_range_display') return;
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

            // 時間範圍 filter（取樣模式的框選擴散）
            const timeKeep = filters.filter(f => f.type === 'time_range');
            const timeExclude = filters.filter(f => f.type === 'exclude_time_range');
            if (timeKeep.length > 0 || timeExclude.length > 0) {
                const cellVal = String(row[filters[0].colIdx] || '').trim();
                let passed = true;
                if (timeKeep.length > 0) {
                    passed = timeKeep.every(f => cellVal >= f.timeMin && cellVal <= f.timeMax);
                }
                if (passed && timeExclude.length > 0) {
                    passed = !timeExclude.some(f => cellVal >= f.timeMin && cellVal <= f.timeMax);
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
                const rowVal = cellVal != null ? String(cellVal).trim().toLowerCase() : '';
                const fVal = f.value.trim().toLowerCase();
                // Exact match first; fall back to contains only if filter value contains wildcard '*'
                if (fVal.includes('*')) {
                    const pattern = fVal.replace(/[.+?^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*');
                    return new RegExp('^' + pattern + '$').test(rowVal);
                }
                return rowVal === fVal;
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
        headerCount.innerHTML = `(目前顯示: <b style="color: #3b82f6;">${filteredRows.length}</b> / 總計: ${totalLines - 1} | 欄位: ${headers.length})`;
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
        if (f.type === 'time_range' || f.type === 'time_range_display') {
            displayText = `時間選取: ${f.timeMin} ~ ${f.timeMax}`;
            pill.style.background = '#f0fdf4';
            pill.style.color = '#166534';
            pill.style.borderColor = '#bbf7d0';
        }
        if (f.type === 'exclude_time_range' || f.type === 'exclude_time_range_display') {
            displayText = `時間排除: ${f.timeMin} ~ ${f.timeMax}`;
            pill.style.background = '#fef2f2';
            pill.style.color = '#991b1b';
            pill.style.borderColor = '#fecaca';
        }

        pill.innerHTML = `
                    <span style="font-weight:600;">${f.colName}:</span> <span>${displayText}</span>
                    <span class="remove-pill" onclick="removeFilter(${idx})">&times;</span>
                `;
        const menuContainer = leftActions.querySelector('.filter-menu-container');
        leftActions.insertBefore(pill, menuContainer);
    });
}

let _filterColValues = [];

function _updateFilterValueDatalist(colIdx) {
    _filterColValues = [];
    if (!originalTableData.length) return;
    const seen = new Set();
    for (const row of originalTableData) {
        const v = row[colIdx];
        if (v != null && String(v).trim() !== '') seen.add(String(v).trim());
        if (seen.size >= 500) break;
    }
    _filterColValues = [...seen].sort((a, b) => a.localeCompare(b, undefined, {numeric: true, sensitivity: 'base'}));
}

window._filterInputKey = function(e) {
    const input = document.getElementById('filter-value-input');
    const list = document.getElementById('filter-autocomplete-list');
    if (!input || !list) return;
    const q = input.value.trim().toLowerCase();
    const matches = q === ''
        ? _filterColValues.slice(0, 50)
        : _filterColValues.filter(v => v.toLowerCase().includes(q)).slice(0, 50);
    if (!matches.length) { list.style.display = 'none'; return; }
    list.innerHTML = matches.map(v =>
        `<div onclick="document.getElementById('filter-value-input').value=this.dataset.v;document.getElementById('filter-autocomplete-list').style.display='none';"
              data-v="${v.replace(/"/g,'&quot;')}"
              style="padding:6px 10px;font-size:13px;cursor:pointer;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"
              onmouseenter="this.style.background='#f1f5f9'" onmouseleave="this.style.background=''">${v}</div>`
    ).join('');
    // Use fixed positioning anchored to input rect — bypasses all CSS container constraints
    const rect = input.getBoundingClientRect();
    list.style.position = 'fixed';
    list.style.top = (rect.bottom + 2) + 'px';
    list.style.left = rect.left + 'px';
    list.style.width = rect.width + 'px';
    list.style.display = 'block';
};

// Close dropdowns on outside click
document.addEventListener('click', (e) => {
    const valList = document.getElementById('filter-autocomplete-list');
    const valInput = document.getElementById('filter-value-input');
    if (valList && valInput && !valInput.contains(e.target) && !valList.contains(e.target)) {
        valList.style.display = 'none';
    }
    const colPanel = document.getElementById('filter-col-panel');
    const colDisplay = document.getElementById('filter-col-display');
    const colArrow = document.getElementById('filter-col-arrow');
    if (colPanel && colDisplay && !colDisplay.contains(e.target) && !colPanel.contains(e.target)) {
        colPanel.style.display = 'none';
        if (colArrow) colArrow.style.transform = '';
    }
});

// 欄位選擇下拉開關（inline 展開）
window._toggleColDropdown = function(e) {
    if (e) e.stopPropagation();
    const panel = document.getElementById('filter-col-panel');
    const arrow = document.getElementById('filter-col-arrow');
    if (!panel) return;
    const isOpen = panel.style.display !== 'none';
    if (isOpen) {
        panel.style.display = 'none';
        if (arrow) arrow.style.transform = '';
    } else {
        panel.style.display = 'block';
        if (arrow) arrow.style.transform = 'rotate(180deg)';
        window._filterColSearch('');
        const searchInput = document.getElementById('filter-col-search');
        if (searchInput) { searchInput.value = ''; searchInput.focus(); }
    }
};

// 欄位清單搜尋渲染
window._filterColSearch = function(q) {
    const list = document.getElementById('filter-col-list');
    if (!list) return;
    // Use live getter from window if available (ensures we always get the current tableHeaders)
    const headers = (window.getAnalysisTableHeaders ? window.getAnalysisTableHeaders() : null) || tableHeaders;
    const lq = (q || '').toLowerCase();
    const filtered = headers
        .map((h, i) => ({ h, i }))
        .filter(({ h }) => !lq || h.toLowerCase().includes(lq));
    const hidden = document.getElementById('filter-column-select');
    const currentIdx = hidden ? parseInt(hidden.value) : -1;
    list.innerHTML = filtered.map(({ h, i }) => {
        const safeH = h.replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/\r?\n/g, ' ');
        const safeDisplay = h.replace(/\r?\n/g, ' ');
        return `<div data-idx="${i}"
              style="padding:7px 12px;font-size:13px;cursor:pointer;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;${i === currentIdx ? 'background:#eff6ff;color:#3b82f6;font-weight:600;' : ''}"
              onmouseenter="this.style.background='${i === currentIdx ? '#eff6ff' : '#f8fafc'}'"
              onmouseleave="this.style.background='${i === currentIdx ? '#eff6ff' : ''}'"
              onclick="window._selectFilterCol(${i},'${safeH}')">
            ${safeDisplay}
        </div>`;
    }).join('');
};

// 選定欄位
window._selectFilterCol = function(idx, name) {
    const displayText = document.getElementById('filter-col-display-text');
    const hidden = document.getElementById('filter-column-select');
    const panel = document.getElementById('filter-col-panel');
    const arrow = document.getElementById('filter-col-arrow');
    if (displayText) displayText.textContent = name;
    if (hidden) hidden.value = idx;
    if (panel) panel.style.display = 'none';
    if (arrow) arrow.style.transform = '';
    _updateFilterValueDatalist(idx);
    const valInput = document.getElementById('filter-value-input');
    if (valInput) {
        valInput.value = '';
        // 延遲 focus，等 click 冒泡結束後再觸發，避免 outside-click handler 把下拉藏掉
        setTimeout(() => { valInput.focus(); }, 0);
    }
};

export function toggleFilterMenu(event) {
    if (event) event.stopPropagation();
    const menu = DOM.get('filter-menu');
    const btn = event && event.currentTarget ? event.currentTarget : document.querySelector('.add-filter-btn');
    const isVisible = menu.style.display === 'flex';

    if (!isVisible) {
        menu.style.position = 'fixed';
        menu.style.display = 'flex';

        // Position relative to trigger button, clamp to viewport
        const btnRect = btn ? btn.getBoundingClientRect() : { bottom: 50, left: 10, top: 50 };
        const menuH = menu.offsetHeight || 280;
        const menuW = 300; // CSS width
        const vw = window.innerWidth;
        const vh = window.innerHeight;

        let top = btnRect.bottom + 8;
        let left = btnRect.left;

        if (top + menuH > vh - 10) top = Math.max(10, btnRect.top - menuH - 8);
        if (left + menuW > vw - 10) left = Math.max(10, vw - menuW - 10);

        menu.style.top = top + 'px';
        menu.style.left = left + 'px';

        // Init column display
        if (tableHeaders.length) {
            const displayText = DOM.get('filter-col-display-text');
            const hidden = DOM.get('filter-column-select');
            const currentIdx = hidden ? parseInt(hidden.value) || 0 : 0;
            if (displayText && displayText.textContent === '選擇欄位...') {
                displayText.textContent = tableHeaders[0];
                if (hidden) hidden.value = '0';
            }
            _updateFilterValueDatalist(parseInt((hidden && hidden.value) || '0'));
        }

        DOM.get('filter-value-input').value = '';
        DOM.get('filter-not-empty-check').checked = false;

        // 不自動關閉，只透過「取消」或「新增篩選」按鈕關閉
    } else {
        menu.style.display = 'none';
        const panel = document.getElementById('filter-col-panel');
        const arrow = document.getElementById('filter-col-arrow');
        if (panel) panel.style.display = 'none';
        if (arrow) arrow.style.transform = '';
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
    const btnHeatmap = document.getElementById('btn-mode-heatmap');
    const viewTable = document.getElementById('analysis-table-container') || document.getElementById('analysis-table-view');
    const viewChart = document.getElementById('analysis-chart-view');
    const viewHeatmap = document.getElementById('analysis-heatmap-view');

    // Reset all buttons
    [btnTable, btnChart, btnHeatmap].forEach(btn => {
        if (btn) { btn.style.background = 'transparent'; btn.style.color = '#64748b'; btn.style.boxShadow = 'none'; }
    });
    // Hide all views
    if (viewTable) viewTable.style.display = 'none';
    if (viewChart) viewChart.style.display = 'none';
    if (viewHeatmap) viewHeatmap.style.display = 'none';

    // Hide/show chart AI FAB
    const chartFab = document.getElementById('chart-assistant-trigger');
    const chartAiWindow = document.getElementById('chart-ai-assistant-window');

    if (mode === 'table') {
        if (viewTable) viewTable.style.display = 'block';
        if (btnTable) { btnTable.style.background = '#fff'; btnTable.style.color = '#3b82f6'; btnTable.style.boxShadow = '0 1px 2px rgba(0,0,0,0.1)'; }
        if (chartFab) chartFab.style.display = 'none';
        if (chartAiWindow) chartAiWindow.style.display = 'none';
    } else if (mode === 'chart') {
        if (viewChart) viewChart.style.display = 'flex';
        if (btnChart) { btnChart.style.background = '#fff'; btnChart.style.color = '#7e22ce'; btnChart.style.boxShadow = '0 1px 2px rgba(0,0,0,0.1)'; }
        initChartColumns();
        setTimeout(() => {
            renderAnalysisChart();
            if (analysisChart) analysisChart.resize();
        }, 50);
    } else if (mode === 'heatmap') {
        if (viewHeatmap) viewHeatmap.style.display = 'flex';
        if (btnHeatmap) { btnHeatmap.style.background = '#fff'; btnHeatmap.style.color = '#ef4444'; btnHeatmap.style.boxShadow = '0 1px 2px rgba(0,0,0,0.1)'; }
        if (chartFab) chartFab.style.display = 'none';
        if (chartAiWindow) chartAiWindow.style.display = 'none';
        // Init heatmap with current data
        if (typeof window.initHeatmap === 'function') {
            setTimeout(() => window.initHeatmap(tableHeaders, originalTableData, analysisFilename), 50);
        }
    }
}

export function initChartColumns() {
    const container = document.getElementById('chart-column-source');
    if (!container) return;
    container.innerHTML = ''; // Clear

    // 型別標籤點擊切換（用事件委派，只綁一次）
    if (!container._dtypeHandlerBound) {
        container._dtypeHandlerBound = true;
        container.addEventListener('click', (e) => {
            const badge = e.target.closest('.dtype-badge');
            if (!badge) return;
            e.stopPropagation();
            const col = badge.dataset.col;
            const cur = badge.textContent.trim();
            const idx = _DTYPE_CYCLE.indexOf(cur);
            const next = _DTYPE_CYCLE[(idx + 1) % _DTYPE_CYCLE.length];
            _colTypeOverrides[col] = next;
            _saveDtypeOverrides(analysisFilename);
            const s = _DTYPE_STYLE[next];
            badge.textContent = next;
            badge.style.color = s.color;
            badge.style.background = s.bg;
            badge.style.borderColor = s.color + '33';
        });
    }

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
            // Infer column type from data
            const colIdx = tableHeaders.indexOf(header);
            let dtype = '文字';
            let dtypeColor = '#64748b';
            let dtypeBg = '#f1f5f9';
            if (colIdx >= 0 && originalTableData.length > 0) {
                const samples = originalTableData.slice(0, 20).map(r => r[colIdx]).filter(v => v != null && v !== '');
                // 同時接受 number 型別和可解析的字串
                const numCount = samples.filter(v => {
                    if (typeof v === 'number') return !isNaN(v);
                    return typeof v === 'string' && v.trim() !== '' && !isNaN(Number(v));
                }).length;
                const datePattern = /^\d{4}[\/\-]\d{1,2}[\/\-]\d{1,2}|^\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}/;
                const dateCount = samples.filter(v => datePattern.test(String(v))).length;
                if (dateCount > samples.length * 0.5) {
                    dtype = '日期';
                } else if (samples.length > 0 && numCount >= Math.ceil(samples.length * 0.4)) {
                    dtype = '數值';
                } else {
                    const uniq = new Set(samples).size;
                    if (uniq <= Math.min(20, samples.length * 0.5)) {
                        dtype = '類別';
                    }
                }
            }
            const activeDtype = _getDtype(header, dtype);
            chip.innerHTML = `<div style="display:flex; justify-content:space-between; align-items:center; width:100%;"><span style="pointer-events:none;">${header}</span>${_renderDtypeBadge(header, activeDtype)}</div>`;
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

        // Auto-fill X with row index if not set
        if ((axis === 'y' || axis === 'y2') && !chartConfig.x) {
            chartConfig.x = '__row_index__';
            updateDropzoneUI('x', '__row_index__');
        }

        if (axis === 'x') _updateScatterAvailability();
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

    // Auto-fill X with row index if not set
    if (!chartConfig.x) {
        chartConfig.x = '__row_index__';
        updateDropzoneUI('x', '__row_index__');
    }

    tryUpdateChart();
    updateChartSourceInfo();
}

function updateDropzoneUI(axis, colName) {
    const dropzone = DOM.get('drop-' + axis);
    if (!dropzone) return;

    const isVertical = axis === 'y' || axis === 'y2';
    const style = isVertical ? 'writing-mode: vertical-rl; text-orientation: mixed;' : '';

    const _fMap = { mean:'均值', std1:'標準差', std:'標準差', max:'最大', min:'最小', range:'值域', count:'Count' };
    const _fVal = axis === 'y' ? chartConfig.yFeature : axis === 'y2' ? chartConfig.y2Feature : null;
    const _fLbl = _fVal ? (_fMap[_fVal] || _fVal) : null;
    const displayName = (colName === '__row_index__' ? '行號' : colName) + (_fLbl ? ` (${_fLbl})` : '');
    const popupCall = (colName !== '__row_index__' && axis !== 'x') ? `onclick="window.openYAxisPopup(null,'${axis}',event)" title="點擊設定軸屬性"` : '';
    dropzone.innerHTML = `
        <div style="display:flex; align-items:center; gap:4px; width:100%; justify-content:center; ${isVertical ? 'flex-direction:column;' : ''}">
             <span onclick="window.cycleChartAxis('${axis}', -1)" style="cursor:pointer; font-size:10px;">▲</span>
             <span ${popupCall} style="color: #2563eb; font-weight: bold; white-space:nowrap; cursor:pointer; ${style}">${displayName}</span>
             <span onclick="window.cycleChartAxis('${axis}', 1)" style="cursor:pointer; font-size:10px;">▼</span>
             <span style="font-size:10px; cursor:pointer; color:#ef4444;" onclick="window.resetAxis('${axis}')">✕</span>
        </div>`;
    dropzone.classList.add('filled');
}

export function cycleChartAxis(axis, offset) {
    if (!chartConfig[axis]) return;
    if (axis === 'x') return; // Disable X cycling
    // y3 / y4 are valid cycle axes

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

    if (axis === 'x' && nextCol === '__row_index__') {
        // Skip index if waiting for real columns, OR allow it?
        // Let's allow cycling into index? No, current logic cycles through headers.
        // If x is '__row_index__', nextCol will probably be headers[0].
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
    // Clear associated feature when Y column is removed
    if (axis === 'y') chartConfig.yFeature = null;
    if (axis === 'y2') chartConfig.y2Feature = null;
    const dropzone = DOM.get('drop-' + axis);
    if (dropzone) {
        dropzone.classList.remove('filled');
        const isVert = axis === 'y' || axis === 'y2';
        const label = axis === 'y2' ? '(選填)' : '拖曳至此';
        if (isVert) {
            dropzone.innerHTML = `<span class="placeholder" style="transform: rotate(-90deg); white-space: nowrap; font-size: 11px; letter-spacing: 2px; display: inline-block;">${label}</span>`;
        } else {
            dropzone.innerHTML = `<span class="placeholder">拖曳至此</span>`;
        }
    }

    // If clearing X and Y still has data, revert X to row index
    if (axis === 'x' && (chartConfig.y || chartConfig.y2)) {
        chartConfig.x = '__row_index__';
        updateDropzoneUI('x', '__row_index__');
    }

    // If clearing Y/Y2 and X was auto-set to row index (not manually set), clear X too
    if ((axis === 'y' || axis === 'y2') && chartConfig.x === '__row_index__' && !chartConfig.y && !chartConfig.y2) {
        chartConfig.x = null;
        const xDz = DOM.get('drop-x');
        if (xDz) { xDz.classList.remove('filled'); xDz.innerHTML = `<span class="placeholder">拖曳至此</span>`; }
    }
    // If clearing X and Y was auto-set to row index, clear Y too
    if (axis === 'x' && chartConfig.y === '__row_index__' && !chartConfig.y2) {
        chartConfig.y = null;
        const yDz = DOM.get('drop-y');
        if (yDz) { yDz.classList.remove('filled'); yDz.innerHTML = `<span class="placeholder" style="transform:rotate(-90deg);white-space:nowrap;font-size:11px;letter-spacing:2px;display:inline-block;">拖曳至此</span>`; }
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
    if (axis === 'x') _updateScatterAvailability();
    tryUpdateChart(); // Re-render if partial config exists
}

export function clearChartConfig() {
    chartConfig = { x: null, y: null, y2: null, type: 'scatter',
        yColor: '#7c3aed', y2Color: '#06b6d4',
        yMin: null, yMax: null, y2Min: null, y2Max: null,
        yFeature: null, y2Feature: null };
    _xManuallyClearedByUser = false;
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
    // Clear all extra panels
    extraPanels.forEach(p => { if (p.chart) p.chart.destroy(); });
    extraPanels = [];
    _panelIdCounter = 0;
    const ec = document.getElementById('extra-panels-container');
    if (ec) ec.innerHTML = '';
    const sourceContainer = DOM.get('chart-column-source');
    if (sourceContainer) sourceContainer.innerHTML = '';
    _updateScatterAvailability(); // Re-enable scatter/line buttons on clear
}

export function tryUpdateChart() {
    if (chartConfig.x && (chartConfig.y || chartConfig.y2)) {
        renderAnalysisChart();
    } else {
        if (typeof analysisChart !== 'undefined' && analysisChart) {
            analysisChart.destroy();
            analysisChart = null;
        }
        updateChartSourceInfo();
    }
    // Re-render all extra panels (X axis may have changed)
    extraPanels.forEach(p => {
        if (chartConfig.x && (p.yLeft || p.yRight)) _renderExtraPanel(p);
    });
    _syncXAxisVisibility();
}


export function renderAnalysisChart() {
    const canvas = document.getElementById('analysis-chart-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    if (analysisChart) analysisChart.destroy();

    // Prepare Data Indices
    const xIdx = chartConfig.x === '__row_index__' ? -2 : tableHeaders.indexOf(chartConfig.x);
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
    let isDatetimeX = false;
    let isCatMappedX = false; // category X mapped to numeric indices
    let dataPoints1 = [];
    let dataPoints2 = [];

    // --- DATA PREPARATION STRATEGY ---

    if (chartType === 'boxplot') {
        // Boxplot always uses category scale (chartjs-chart-box-and-violin-plot limitation)
        isNumericX = false;
        const groups = {};

        // Detect datetime X for boxplot; respect datetimeXMode
        const _DT_RE_BP = /^\d{4}[-/]\d{2}[-/]\d{2}([T ]\d{2}:\d{2})?/;
        const _bpSampleX = chartConfig.x !== '__row_index__' ? sourceRows.slice(0, 20).map(r => r[xIdx]).filter(v => v != null) : [];
        const _bpIsRawDT = _bpSampleX.length > 0 && _bpSampleX.filter(v => _DT_RE_BP.test(String(v))).length > _bpSampleX.length * 0.7;
        // In 'category' mode: treat datetime as plain strings (aligns with scatter isCatMappedX labels)
        isDatetimeX = _bpIsRawDT && datetimeXMode === 'timegap';

        sourceRows.forEach((row, i) => {
            let xVal;
            if (chartConfig.x === '__row_index__') xVal = i + 1;
            else xVal = row[xIdx];
            let yVal1 = yIdx !== -1 ? row[yIdx] : null;
            let yVal2 = y2Idx !== -1 ? row[y2Idx] : null;

            if (xVal === null || xVal === undefined) return;
            const key = String(xVal);

            if (yVal1 !== null && !isNaN(parseFloat(yVal1))) yVal1 = parseFloat(yVal1);
            else yVal1 = null;

            if (yVal2 !== null && !isNaN(parseFloat(yVal2))) yVal2 = parseFloat(yVal2);
            else yVal2 = null;

            if (!groups[key]) {
                const ts = isDatetimeX ? new Date(key.replace(' ', 'T')).getTime() : null;
                groups[key] = { y1: [], y2: [], ts };
            }
            if (yVal1 !== null) groups[key].y1.push(yVal1);
            if (yVal2 !== null) groups[key].y2.push(yVal2);
        });

        // Auto-bin numeric X when too many unique values (>30) — only for truly numeric axes
        const _xTypeForBin = _detectXAxisType();
        if (!isDatetimeX && (_xTypeForBin === 'numeric' || _xTypeForBin === 'rowindex') && Object.keys(groups).length > 30) {
            const numKeys = Object.keys(groups).map(k => parseFloat(k));
            if (numKeys.every(v => !isNaN(v))) {
                const xMin = Math.min(...numKeys), xMax = Math.max(...numKeys);
                if (xMax > xMin) {
                    const numBins = 20, binW = (xMax - xMin) / numBins;
                    const binned = {};
                    Object.keys(groups).forEach(k => {
                        const v = parseFloat(k);
                        const bi = Math.min(Math.floor((v - xMin) / binW), numBins - 1);
                        const ctr = parseFloat((xMin + (bi + 0.5) * binW).toPrecision(4)).toString();
                        if (!binned[ctr]) binned[ctr] = { y1: [], y2: [], ts: null };
                        binned[ctr].y1.push(...groups[k].y1);
                        binned[ctr].y2.push(...groups[k].y2);
                    });
                    Object.keys(groups).forEach(k => delete groups[k]);
                    Object.assign(groups, binned);
                }
            }
        }

        const sortedKeys = Object.keys(groups).sort((a, b) => {
            if (isDatetimeX) return (groups[a].ts || 0) - (groups[b].ts || 0);
            const nav = parseFloat(a), nbv = parseFloat(b);
            if (!isNaN(nav) && !isNaN(nbv)) return nav - nbv;
            return a.localeCompare(b);
        });

        const _yC = chartConfig.yColor||'#7c3aed', _y2C = chartConfig.y2Color||'#06b6d4';

        // Boxplot always uses category scale (plugin limitation)
        // Datetime X: labels are formatted time strings, sorted chronologically
        labels = isDatetimeX
            ? sortedKeys.map(k => {
                const d = new Date(k.replace(' ', 'T'));
                if (isNaN(d)) return k;
                const first = sortedKeys[0], last = sortedKeys[sortedKeys.length-1];
                const sameDay = new Date(first.replace(' ','T')).toDateString() === new Date(last.replace(' ','T')).toDateString();
                return sameDay
                    ? d.toLocaleTimeString('zh-TW',{hour:'2-digit',minute:'2-digit',second:'2-digit'})
                    : d.toLocaleDateString('zh-TW',{month:'2-digit',day:'2-digit'})+' '+d.toLocaleTimeString('zh-TW',{hour:'2-digit',minute:'2-digit'});
            })
            : sortedKeys;
        const _bpAgg = (yVals, type) => {
            if (type === 'count') return yVals.length;
            const v = yVals.filter(n => !isNaN(n));
            if (!v.length) return null;
            const mean = v.reduce((a,b)=>a+b,0)/v.length;
            const s = Math.sqrt(v.reduce((a,n)=>a+(n-mean)**2,0)/v.length);
            return { mean, max: Math.max(...v), min: Math.min(...v), std: s }[type] ?? null;
        };
        const _bpFeatureLine = (grpKey, feature, yAxisID, color, lbl) => {
            const aggData = sortedKeys.map(k => _bpAgg(groups[k][grpKey], feature));
            datasets.push({ label: lbl, data: aggData, type: 'line', yAxisID,
                borderColor: color, backgroundColor: _hexToRgba(color, 0.5),
                borderWidth: 2, pointRadius: 3, showLine: true, tension: 0.3, order: -2 });
        };

        if (yIdx !== -1) {
            if (chartConfig.yFeature) {
                if (chartConfig.yFeature === 'range') {
                    _bpFeatureLine('y1', 'max', 'y', _yC, '最大');
                    _bpFeatureLine('y1', 'min', 'y', _yC, '最小');
                } else {
                    const f = chartConfig.yFeature === 'std1' || chartConfig.yFeature === 'std' ? 'std' : chartConfig.yFeature;
                    const lbl = { mean:'均值', std:'標準差', max:'最大', min:'最小', count:'Count' }[f] || f;
                    _bpFeatureLine('y1', f, 'y', _yC, lbl);
                }
            } else {
                const data1 = sortedKeys.map(k => groups[k].y1);
                datasets.push({ label: chartConfig.y, data: data1, backgroundColor: _hexToRgba(_yC,0.5), borderColor: _yC, borderWidth:1, outlierColor:'#999', padding:10, itemRadius:2, meanRadius:0, yAxisID:'y' });
            }
        }
        if (y2Idx !== -1) {
            if (chartConfig.y2Feature) {
                if (chartConfig.y2Feature === 'range') {
                    _bpFeatureLine('y2', 'max', 'y1', _y2C, '最大');
                    _bpFeatureLine('y2', 'min', 'y1', _y2C, '最小');
                } else {
                    const f = chartConfig.y2Feature === 'std1' || chartConfig.y2Feature === 'std' ? 'std' : chartConfig.y2Feature;
                    const lbl = { mean:'均值', std:'標準差', max:'最大', min:'最小', count:'Count' }[f] || f;
                    _bpFeatureLine('y2', f, 'y1', _y2C, lbl);
                }
            } else {
                const data2 = sortedKeys.map(k => groups[k].y2);
                datasets.push({ label: chartConfig.y2, data: data2, backgroundColor: _hexToRgba(_y2C,0.5), borderColor: _y2C, borderWidth:1, outlierColor:'#999', itemRadius:2, meanRadius:0, yAxisID:'y1' });
            }
        }

        updateChartSourceInfo(sourceRows.length);
    } else {
        // SCATTER or LINE Logic
        const maxPoints = 5000;
        const step = Math.ceil(sourceRows.length / maxPoints);

        dataPoints1 = [];
        dataPoints2 = [];

        // Detect datetime X; respect datetimeXMode setting
        const _DT_RE = /^\d{4}[-/]\d{2}[-/]\d{2}([T ]\d{2}:\d{2})?/;
        const _sampleX = chartConfig.x !== '__row_index__' ? sourceRows.slice(0, 20).map(r => r[xIdx]).filter(v => v != null) : [];
        const _isRawDatetime = _sampleX.length > 0 && _sampleX.filter(v => _DT_RE.test(String(v))).length > _sampleX.length * 0.7;
        // timegap mode: convert to timestamp (linear scale with gaps)
        // category mode: keep as string (isCatMappedX, boxplot aligned)
        isDatetimeX = _isRawDatetime && datetimeXMode === 'timegap';
        const _dtLabels = [];

        for (let i = 0; i < sourceRows.length; i += step) {
            const row = sourceRows[i];
            let xVal;
            if (chartConfig.x === '__row_index__') xVal = i + 1;
            else xVal = row[xIdx];
            let yVal1 = yIdx !== -1 ? row[yIdx] : null;
            let yVal2 = y2Idx !== -1 ? row[y2Idx] : null;

            if (isDatetimeX && xVal != null) {
                const ts = new Date(String(xVal).replace(' ', 'T')).getTime();
                xVal = isNaN(ts) ? xVal : ts;
            } else if (xVal != null) {
                const s = String(xVal).trim();
                if (s !== '' && isFinite(s)) {
                    xVal = parseFloat(s);
                } else if (s === '') {
                    xVal = null; // treat empty/blank as missing
                }
            }
            if (yVal1 !== null && !isNaN(parseFloat(yVal1))) yVal1 = parseFloat(yVal1); else yVal1 = null;
            if (yVal2 !== null && !isNaN(parseFloat(yVal2))) yVal2 = parseFloat(yVal2); else yVal2 = null;

            // Skip rows where X is NaN/null/empty
            if (xVal == null || (typeof xVal === 'number' && isNaN(xVal))) continue;
            if (yVal1 !== null) dataPoints1.push({ x: xVal, y: yVal1, _origIdx: row.__idx });
            if (yVal2 !== null) dataPoints2.push({ x: xVal, y: yVal2, _origIdx: row.__idx });
        }

        updateChartSourceInfo(sourceRows.length);

        isNumericX = dataPoints1.length > 0 && dataPoints1.every(p => typeof p.x === 'number' && !isNaN(p.x));

        // Detect if Y is numeric
        const isNumericY = dataPoints1.length > 0 && dataPoints1.filter(p => typeof p.y === 'number' && !isNaN(p.y)).length > dataPoints1.length * 0.5;
        const isNumericY2 = dataPoints2.length > 0 && dataPoints2.filter(p => typeof p.y === 'number' && !isNaN(p.y)).length > dataPoints2.length * 0.5;

        // If Y is non-numeric, show a warning
        if (!isNumericY && yIdx !== -1) {
            const info = document.getElementById('chart-info-overlay');
            if (info) info.innerHTML = `⚠️ Y 軸「${chartConfig.y}」為文字/類別型欄位，散布圖/折線圖需要數值型欄位。<br>請改用盒鬚圖或選擇數值欄位。`;
            updateChartSourceInfo(sourceRows.length);
            return;
        }

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

            // 🛠️ For scatter/line: map category labels to numeric indices so Chart.js
            // scatter can render multiple points per category correctly.
            // X axis uses linear scale + tick callback to show label names.
            if (labels.length === 1) {
                labels = ['', labels[0], ' '];
            }
            const catIndexMap = {};
            labels.forEach((l, i) => catIndexMap[l] = i);
            dataPoints1.forEach(p => { p._catLabel = String(p.x); p.x = catIndexMap[String(p.x)] ?? 0; });
            dataPoints2.forEach(p => { p._catLabel = String(p.x); p.x = catIndexMap[String(p.x)] ?? 0; });
            isNumericX = true; // treat as numeric (indices) for rendering
            isCatMappedX = true;
        }

        const _yC = chartConfig.yColor||'#7c3aed', _y2C = chartConfig.y2Color||'#06b6d4';
        // If feature selected: show only aggregated line, hide raw points
        if (yIdx !== -1) {
            if (chartConfig.yFeature) {
                _addStatLineDatasets(datasets, null, chartConfig.yFeature, 'y', _yC, isNumericX, null, null, labels, dataPoints1);
            } else {
                datasets.push({ label: chartConfig.y, data: dataPoints1, yAxisID:'y',
                    borderColor: _yC, backgroundColor: _hexToRgba(_yC,0.5),
                    pointRadius: chartType==='scatter'?4:2, showLine: chartType==='line', tension:0.1 });
            }
        }
        if (y2Idx !== -1) {
            if (chartConfig.y2Feature) {
                _addStatLineDatasets(datasets, null, chartConfig.y2Feature, 'y1', _y2C, isNumericX, null, null, labels, dataPoints2);
            } else {
                datasets.push({ label: chartConfig.y2, data: dataPoints2, yAxisID:'y1',
                    borderColor: _y2C, backgroundColor: _hexToRgba(_y2C,0.5),
                    pointRadius: chartType==='scatter'?4:2, showLine: chartType==='line', tension:0.1 });
            }
        }
    }

    // Sanitize min/max (swap if inverted, clear if equal)
    if (chartConfig.yMin != null && chartConfig.yMax != null && chartConfig.yMin >= chartConfig.yMax)
        [chartConfig.yMin, chartConfig.yMax] = [chartConfig.yMax, chartConfig.yMin];
    if (chartConfig.y2Min != null && chartConfig.y2Max != null && chartConfig.y2Min >= chartConfig.y2Max)
        [chartConfig.y2Min, chartConfig.y2Max] = [chartConfig.y2Max, chartConfig.y2Min];

    const _featureLblMap = { mean:'均值', std1:'標準差', std:'標準差', max:'最大', min:'最小', range:'值域', count:'Count' };
    const _yFLbl = chartConfig.yFeature ? (_featureLblMap[chartConfig.yFeature] || chartConfig.yFeature) : null;
    const _y2FLbl = chartConfig.y2Feature ? (_featureLblMap[chartConfig.y2Feature] || chartConfig.y2Feature) : null;

    const options = {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
            x: {
                type: isNumericX ? 'linear' : 'category',
                // offset:true makes line chart categories centre-aligned like boxplot (avoids misalignment in multi-panel)
                offset: !isNumericX,
                title: { display: false },
                grid: { color: '#f1f5f9' },
                beginAtZero: false,
                ticks: extraPanels.length === 0
                    ? (isCatMappedX ? {
                        callback: (val) => labels[Math.round(val)] ?? '',
                        stepSize: 1, maxRotation: 45, autoSkip: true,
                        maxTicksLimit: Math.min(labels.length, 12), font: { size: 10 }
                    } : isDatetimeX ? {
                        callback: (val) => {
                            const pts = dataPoints1.length > 0 ? dataPoints1 : dataPoints2;
                            const rangeMs = pts.length > 1 ? pts[pts.length-1].x - pts[0].x : 0;
                            return _fmtDt(val, rangeMs);
                        },
                        maxRotation: 30, autoSkip: true, maxTicksLimit: 10, font:{size:10}
                    } : chartType === 'boxplot' ? {
                        callback: (val, idx) => (labels || [])[val] ?? (labels || [])[idx] ?? String(val),
                        maxRotation: 45, autoSkip: true, maxTicksLimit: Math.min((labels||[]).length || 12, 12), font: { size: 10 }
                    } : {
                        callback: (val) => {
                            if (typeof val !== 'number') return val;
                            const range = (dataPoints1.length > 1 ? Math.max(...dataPoints1.map(p => p.x)) - Math.min(...dataPoints1.map(p => p.x)) : 1) || 1;
                            const decimals = range < 0.01 ? 4 : range < 0.1 ? 3 : range < 1 ? 2 : range < 100 ? 1 : 0;
                            return val.toFixed(decimals);
                        },
                        maxRotation: 45, autoSkip: true, maxTicksLimit: 8, font: { size: 10 }
                    })
                    : { display: false }
            },
            y: {
                title: { display: true, text: chartConfig.y + (_yFLbl ? ` (${_yFLbl})` : ''), color: chartConfig.yColor||'#7c3aed' },
                type: (chartType !== 'boxplot' && typeof isNumericY !== 'undefined' && !isNumericY) ? 'category' : 'linear',
                display: true, position: 'left',
                grid: { color: '#f1f5f9' },
                grace: chartConfig.yMin != null || chartConfig.yMax != null ? 0 : '5%',
                beginAtZero: false,
                ...(chartConfig.yMin != null ? { min: chartConfig.yMin } : {}),
                ...(chartConfig.yMax != null ? { max: chartConfig.yMax } : {}),
                afterFit(scale) { scale.width = 85; }
            },
            y1: {
                title: { display: !!chartConfig.y2, text: chartConfig.y2 + (_y2FLbl ? ` (${_y2FLbl})` : ''), color: chartConfig.y2Color||'#06b6d4' },
                type: 'linear', display: true,
                ticks: { display: !!chartConfig.y2 },
                position: 'right',
                grid: { drawOnChartArea: false, display: !!chartConfig.y2 },
                grace: chartConfig.y2Min != null || chartConfig.y2Max != null ? 0 : '5%',
                beginAtZero: false,
                ...(chartConfig.y2Min != null ? { min: chartConfig.y2Min } : {}),
                ...(chartConfig.y2Max != null ? { max: chartConfig.y2Max } : {}),
                afterFit(scale) { scale.width = 85; }
            }
        },
        plugins: {
            legend: { display: extraPanels.length === 0 },
            tooltip: {
                mode: chartType === 'scatter' ? 'nearest' : 'index',
                intersect: chartType === 'scatter',
                callbacks: isCatMappedX ? {
                    title: (items) => {
                        const idx = Math.round(items[0]?.parsed?.x ?? 0);
                        return labels[idx] ?? String(idx);
                    }
                } : isDatetimeX ? {
                    title: (items) => {
                        const ts = items[0]?.parsed?.x;
                        if (ts == null) return '';
                        const pts = dataPoints1.length > 0 ? dataPoints1 : dataPoints2;
                        const rangeMs = pts.length > 1 ? pts[pts.length-1].x - pts[0].x : 0;
                        return _fmtDt(ts, rangeMs);
                    }
                } : {}
            }
        }
    };

    // If feature active on boxplot, render as line chart on category scale
    const hasFeature = (chartConfig.yFeature || chartConfig.y2Feature);
    const renderType = (chartType === 'boxplot' && hasFeature) ? 'line' : chartType;
    analysisChart = new Chart(ctx, {
        type: renderType,
        data: {
            labels: (isCatMappedX || (chartType === 'boxplot' && hasFeature)) ? labels : (labels || null),
            datasets: datasets
        },
        options: options
    });

    // Sync X-axis visibility across panels
    _syncXAxisVisibility();

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

// ─── Dynamic Extra Panel System ─────────────────────────────────────────────

export function handleAddPanelDrop(ev) {
    ev.preventDefault();
    const dz = ev.target.closest('.axis-dropzone');
    if (dz) dz.classList.remove('drag-over');
    let colData = ev.dataTransfer.getData('text');
    if (!colData) return;
    let colName = '';
    try { const p = JSON.parse(colData); colName = Array.isArray(p) ? p[0] : p; }
    catch (e) { colName = colData; }
    if (!colName) return;
    if (!chartConfig.x) { chartConfig.x = '__row_index__'; updateDropzoneUI('x', '__row_index__'); }
    _addExtraPanel(colName);
}

function _addExtraPanel(colName) {
    _panelIdCounter++;
    const id = _panelIdCounter;
    // Adjust default type based on X axis type
    let defaultType = chartConfig.type;
    const _xType = _detectXAxisType();
    if (_xType === 'category' && (defaultType === 'scatter' || defaultType === 'line')) defaultType = 'boxplot';
    if (_xType === 'datetime' && defaultType === 'boxplot') defaultType = 'scatter';
    const panel = { id, yLeft: colName, yRight: null, chart: null, type: defaultType,
        yLeftColor: '#ea580c', yRightColor: '#10b981',
        yLeftMin: null, yLeftMax: null, yRightMin: null, yRightMax: null,
        yLeftFeature: null, yRightFeature: null };
    extraPanels.push(panel);

    const container = document.getElementById('extra-panels-container');
    const div = document.createElement('div');
    div.id = `extra-panel-${id}`;
    div.style.cssText = 'flex:1; min-height:0; display:flex; flex-direction:column;';
    div.innerHTML = `
        <div style="flex:1; min-height:0; display:flex; align-items:stretch; padding:4px 8px 0 8px;">
            <div style="width:36px; flex-shrink:0; display:flex; flex-direction:column; margin-right:6px; overflow:hidden;">
                <div id="drop-yleft-${id}" class="axis-dropzone vertical"
                    ondragover="allowDrop(event)" ondragleave="handleDragLeave(event)"
                    ondrop="handleExtraPanelDrop(event,${id},'left')"
                    style="width:100%; height:100%; overflow:hidden;">
                    <span class="placeholder" style="transform:rotate(-90deg);white-space:nowrap;font-size:11px;letter-spacing:2px;display:inline-block;">拖曳至此</span>
                </div>
            </div>
            <div style="flex:1; min-width:0; position:relative; border:1px solid #f1f5f9; border-radius:8px; padding:0; box-shadow:inset 0 0 10px #f8fafc; overflow:hidden;">
                <div style="position:relative; width:100%; height:100%;">
                <canvas id="canvas-extra-${id}" style="display:block; width:100%; height:100%;"></canvas>
                </div>
                <div style="position:absolute;top:5px;right:5px;display:flex;gap:4px;align-items:center;z-index:10;">
                    <span id="type-btn-scatter-${id}" onclick="changePanelType(${id},'scatter')"
                        style="cursor:pointer;font-size:10px;padding:2px 6px;border-radius:3px;border:1px solid #cbd5e1;background:#fff;color:#475569;">散布</span>
                    <span id="type-btn-line-${id}" onclick="changePanelType(${id},'line')"
                        style="cursor:pointer;font-size:10px;padding:2px 6px;border-radius:3px;border:1px solid #cbd5e1;background:#fff;color:#475569;">折線</span>
                    <span id="type-btn-boxplot-${id}" onclick="changePanelType(${id},'boxplot')"
                        style="cursor:pointer;font-size:10px;padding:2px 6px;border-radius:3px;border:1px solid #cbd5e1;background:#fff;color:#475569;">盒鬚</span>
                    <button onclick="removeExtraPanel(${id})"
                        style="background:#fee2e2;border:none;border-radius:4px;color:#dc2626;font-size:11px;cursor:pointer;padding:2px 7px;">✕</button>
                </div>
            </div>
            <div style="width:36px; flex-shrink:0; display:flex; flex-direction:column; margin-left:6px; overflow:hidden;">
                <div id="drop-yright-${id}" class="axis-dropzone vertical"
                    ondragover="allowDrop(event)" ondragleave="handleDragLeave(event)"
                    ondrop="handleExtraPanelDrop(event,${id},'right')"
                    style="width:100%; height:100%; overflow:hidden;">
                    <span class="placeholder" style="transform:rotate(-90deg);white-space:nowrap;font-size:11px;letter-spacing:2px;display:inline-block;">(選填)</span>
                </div>
            </div>
        </div>
        `;
    container.appendChild(div);

    _updateExtraPanelDropzoneUI(id, 'left', colName);
    _updatePanelTypeButtons(id, panel.type);
    _syncXAxisVisibility();
    _renderExtraPanel(panel);
    renderAnalysisChart(); // re-render main chart to update legend visibility
}

export function handleExtraPanelDrop(ev, panelId, side) {
    ev.preventDefault();
    const dz = ev.target.closest('.axis-dropzone');
    if (dz) dz.classList.remove('drag-over');
    let colData = ev.dataTransfer.getData('text');
    if (!colData) return;
    let colName = '';
    try { const p = JSON.parse(colData); colName = Array.isArray(p) ? p[0] : p; }
    catch (e) { colName = colData; }
    if (!colName) return;
    const panel = extraPanels.find(p => p.id === panelId);
    if (!panel) return;
    if (side === 'left') { panel.yLeft = colName; _updateExtraPanelDropzoneUI(panelId, 'left', colName, panel.yLeftFeature); }
    else { panel.yRight = colName; _updateExtraPanelDropzoneUI(panelId, 'right', colName, panel.yRightFeature); }
    _renderExtraPanel(panel);
}

export function removeExtraPanel(panelId) {
    const idx = extraPanels.findIndex(p => p.id === panelId);
    if (idx === -1) return;
    if (extraPanels[idx].chart) extraPanels[idx].chart.destroy();
    const el = document.getElementById(`extra-panel-${panelId}`);
    if (el) el.remove();
    extraPanels.splice(idx, 1);
    _syncXAxisVisibility();
    // Re-render new last panel to update its X axis
    if (extraPanels.length > 0) _renderExtraPanel(extraPanels[extraPanels.length - 1]);
    renderAnalysisChart(); // re-render main chart to update legend visibility
}

function _updateExtraPanelDropzoneUI(panelId, side, colName, feature) {
    const dzId = side === 'left' ? `drop-yleft-${panelId}` : `drop-yright-${panelId}`;
    const dz = document.getElementById(dzId);
    if (!dz) return;
    const style = 'writing-mode:vertical-rl;text-orientation:mixed;';
    const _fMap = { mean:'均值', std1:'標準差', std:'標準差', max:'最大', min:'最小', range:'值域', count:'Count' };
    const _fLbl = feature ? (_fMap[feature] || feature) : null;
    const displayName = colName + (_fLbl ? ` (${_fLbl})` : '');
    // onclick on the outer div as fallback for when user misses the span
    dz.onclick = (e) => { window.openYAxisPopup(panelId, side, e); };
    dz.innerHTML = `
        <div style="display:flex;align-items:center;gap:4px;width:100%;justify-content:center;flex-direction:column;">
            <span onclick="event.stopPropagation();window.resetExtraPanelAxis(${panelId},'${side}',-1)" style="cursor:pointer;font-size:10px;">▲</span>
            <span onclick="event.stopPropagation();window.openYAxisPopup(${panelId},'${side}',event)" title="點擊設定軸屬性" style="color:#2563eb;font-weight:bold;white-space:nowrap;overflow:hidden;max-height:70%;cursor:pointer;${style}">${displayName}</span>
            <span onclick="event.stopPropagation();window.resetExtraPanelAxis(${panelId},'${side}',1)" style="cursor:pointer;font-size:10px;">▼</span>
            <span style="font-size:10px;cursor:pointer;color:#ef4444;" onclick="event.stopPropagation();window.clearExtraPanelAxis(${panelId},'${side}')">✕</span>
        </div>`;
    dz.classList.add('filled');
}

export function clearExtraPanelAxis(panelId, side) {
    const panel = extraPanels.find(p => p.id === panelId);
    if (!panel) return;
    const dzId = side === 'left' ? `drop-yleft-${panelId}` : `drop-yright-${panelId}`;
    const dz = document.getElementById(dzId);
    const label = side === 'right' ? '(選填)' : '拖曳至此';
    if (dz) {
        dz.classList.remove('filled');
        dz.innerHTML = `<span class="placeholder" style="transform:rotate(-90deg);white-space:nowrap;font-size:11px;letter-spacing:2px;display:inline-block;">${label}</span>`;
    }
    if (side === 'left') panel.yLeft = null; else panel.yRight = null;
    if (!panel.yLeft && !panel.yRight) { removeExtraPanel(panelId); return; }
    _renderExtraPanel(panel);
}

export function resetExtraPanelAxis(panelId, side, offset) {
    const panel = extraPanels.find(p => p.id === panelId);
    if (!panel) return;
    const cur = side === 'left' ? panel.yLeft : panel.yRight;
    if (!cur) return;
    const list = currentChartColumnOrder.length > 0 ? currentChartColumnOrder : tableHeaders;
    let idx = list.indexOf(cur) + offset;
    if (idx < 0) idx = list.length - 1;
    if (idx >= list.length) idx = 0;
    const next = list[idx];
    if (side === 'left') panel.yLeft = next; else panel.yRight = next;
    const _nf = side === 'left' ? panel.yLeftFeature : panel.yRightFeature;
    _updateExtraPanelDropzoneUI(panelId, side, next, _nf);
    _renderExtraPanel(panel);
}

export function changePanelType(panelId, type) {
    const panel = extraPanels.find(p => p.id === panelId);
    if (!panel) return;
    panel.type = type;
    _updatePanelTypeButtons(panelId, type);
    _renderExtraPanel(panel);
}

function _updatePanelTypeButtons(panelId, activeType) {
    const xType = _detectXAxisType();
    const isCatX = xType === 'category';
    const isDatetimeGap = xType === 'datetime';
    const isNumericX = xType === 'numeric' || xType === 'rowindex';

    const types = { scatter: '散布', line: '折線', boxplot: '盒鬚' };
    Object.keys(types).forEach(t => {
        const btn = document.getElementById(`type-btn-${t}-${panelId}`);
        if (!btn) return;
        if (isCatX && (t === 'scatter' || t === 'line')) { btn.style.display = 'none'; return; }
        if ((isDatetimeGap || isNumericX) && t === 'boxplot') { btn.style.display = 'none'; return; }
        btn.style.display = '';
        if (t === activeType) {
            btn.style.background = '#7c3aed';
            btn.style.color = '#fff';
            btn.style.borderColor = '#7c3aed';
        } else {
            btn.style.background = '#fff';
            btn.style.color = '#475569';
            btn.style.borderColor = '#cbd5e1';
        }
    });
}

function _syncXAxisVisibility() {
    // Top chart: hide X axis when there are extra panels
    if (analysisChart) {
        const show = extraPanels.length === 0;
        const xScale = analysisChart.options.scales.x;
        if (xScale) {
            if (!xScale.ticks) xScale.ticks = {};
            xScale.ticks.display = show;  // mutate directly, don't replace object
            if (!xScale.title) xScale.title = {};
            xScale.title.display = show;
            analysisChart.update('none');
        }
    }
    // Extra panels: only last one shows X axis
    extraPanels.forEach((panel, i) => {
        if (!panel.chart) return;
        const show = (i === extraPanels.length - 1);
        const xScale = panel.chart.options.scales.x;
        if (xScale) {
            if (!xScale.ticks) xScale.ticks = {};
            xScale.ticks.display = show;  // mutate directly, don't replace object
            if (!xScale.title) xScale.title = {};
            xScale.title.display = show;
            panel.chart.update('none');
        }
    });
}

function _renderExtraPanel(panel) {
    // Sanitize inverted min/max
    if (panel.yLeftMin != null && panel.yLeftMax != null && panel.yLeftMin >= panel.yLeftMax)
        [panel.yLeftMin, panel.yLeftMax] = [panel.yLeftMax, panel.yLeftMin];
    if (panel.yRightMin != null && panel.yRightMax != null && panel.yRightMin >= panel.yRightMax)
        [panel.yRightMin, panel.yRightMax] = [panel.yRightMax, panel.yRightMin];

    const isLast = extraPanels[extraPanels.length - 1] === panel;
    const canvas = document.getElementById(`canvas-extra-${panel.id}`);
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (panel.chart) panel.chart.destroy();

    const xIdx = chartConfig.x === '__row_index__' ? -2 : tableHeaders.indexOf(chartConfig.x);
    const yLIdx = panel.yLeft ? tableHeaders.indexOf(panel.yLeft) : -1;
    const yRIdx = panel.yRight ? tableHeaders.indexOf(panel.yRight) : -1;
    let sourceRows = getFilteredRows(originalTableData);
    if (sourceRows.length === 0) return;

    const chartType = panel.type || chartConfig.type;
    const datasets = [];
    let labels = null;
    let isNumericX = false;
    let isDatetimeX = false;
    let isCatMappedX = false;
    let dpL = [], dpR = [];

    const _xTypeForBin = _detectXAxisType();
    if (chartType === 'boxplot') {
        const _DT_RE_BP = /^\d{4}[-/]\d{2}[-/]\d{2}([T ]\d{2}:\d{2})?/;
        const _bpSX = chartConfig.x !== '__row_index__' ? sourceRows.slice(0,20).map(r=>r[xIdx]).filter(v=>v!=null) : [];
        const _bpRawDT = _bpSX.length > 0 && _bpSX.filter(v=>_DT_RE_BP.test(String(v))).length > _bpSX.length * 0.7;
        isDatetimeX = _bpRawDT && datetimeXMode === 'timegap';

        const groups = {};
        sourceRows.forEach((row, i) => {
            let xVal = chartConfig.x === '__row_index__' ? i + 1 : row[xIdx];
            if (xVal == null) return;
            const key = String(xVal);
            let vL = yLIdx !== -1 ? row[yLIdx] : null;
            let vR = yRIdx !== -1 ? row[yRIdx] : null;
            if (vL !== null && !isNaN(parseFloat(vL))) vL = parseFloat(vL); else vL = null;
            if (vR !== null && !isNaN(parseFloat(vR))) vR = parseFloat(vR); else vR = null;
            if (!groups[key]) {
                const ts = isDatetimeX ? new Date(key.replace(' ','T')).getTime() : null;
                groups[key] = { L: [], R: [], ts };
            }
            if (vL !== null) groups[key].L.push(vL);
            if (vR !== null) groups[key].R.push(vR);
        });
        // Auto-bin numeric X when too many unique values (>30) — only for truly numeric axes
        if (!isDatetimeX && (_xTypeForBin === 'numeric' || _xTypeForBin === 'rowindex') && Object.keys(groups).length > 30) {
            const numKeys = Object.keys(groups).map(k => parseFloat(k));
            if (numKeys.every(v => !isNaN(v))) {
                const xMin = Math.min(...numKeys), xMax = Math.max(...numKeys);
                if (xMax > xMin) {
                    const numBins = 20, binW = (xMax - xMin) / numBins;
                    const binned = {};
                    Object.keys(groups).forEach(k => {
                        const v = parseFloat(k);
                        const bi = Math.min(Math.floor((v - xMin) / binW), numBins - 1);
                        const ctr = parseFloat((xMin + (bi + 0.5) * binW).toPrecision(4)).toString();
                        if (!binned[ctr]) binned[ctr] = { L: [], R: [], ts: null };
                        binned[ctr].L.push(...groups[k].L);
                        binned[ctr].R.push(...groups[k].R);
                    });
                    Object.keys(groups).forEach(k => delete groups[k]);
                    Object.assign(groups, binned);
                }
            }
        }

        const sk = Object.keys(groups).sort((a, b) => {
            if (isDatetimeX) return (groups[a].ts||0) - (groups[b].ts||0);
            const na=parseFloat(a),nb=parseFloat(b);
            return (!isNaN(na)&&!isNaN(nb))?na-nb:a.localeCompare(b);
        });
        const _pLC = panel.yLeftColor||'#ea580c', _pRC = panel.yRightColor||'#10b981';

        // Boxplot always uses category scale; datetime labels are formatted strings sorted chronologically
        labels = isDatetimeX
            ? sk.map(k => {
                const d = new Date(k.replace(' ', 'T'));
                if (isNaN(d)) return k;
                const first = sk[0], last = sk[sk.length-1];
                const sameDay = new Date(first.replace(' ','T')).toDateString() === new Date(last.replace(' ','T')).toDateString();
                return sameDay
                    ? d.toLocaleTimeString('zh-TW',{hour:'2-digit',minute:'2-digit',second:'2-digit'})
                    : d.toLocaleDateString('zh-TW',{month:'2-digit',day:'2-digit'})+' '+d.toLocaleTimeString('zh-TW',{hour:'2-digit',minute:'2-digit'});
            })
            : sk;
        const _epBpAgg = (yVals, type) => {
            if (type === 'count') return yVals.length;
            const v = yVals.filter(n => !isNaN(n));
            if (!v.length) return null;
            const mean = v.reduce((a,b)=>a+b,0)/v.length;
            const s = Math.sqrt(v.reduce((a,n)=>a+(n-mean)**2,0)/v.length);
            return { mean, max: Math.max(...v), min: Math.min(...v), std: s }[type] ?? null;
        };
        const _epBpLine = (side, f, yAxisID, color, lbl) => {
            const grpKey = side === 'L' ? 'L' : 'R';
            const aggData = sk.map(k => _epBpAgg(groups[k][grpKey], f));
            datasets.push({ label: lbl, data: aggData, type: 'line', yAxisID,
                borderColor: color, backgroundColor: _hexToRgba(color, 0.5),
                borderWidth: 2, pointRadius: 3, showLine: true, tension: 0.3, order: -2 });
        };
        if (yLIdx !== -1) {
            if (panel.yLeftFeature) {
                if (panel.yLeftFeature === 'range') {
                    _epBpLine('L', 'max', 'y', _pLC, '最大');
                    _epBpLine('L', 'min', 'y', _pLC, '最小');
                } else {
                    const f = panel.yLeftFeature === 'std1' || panel.yLeftFeature === 'std' ? 'std' : panel.yLeftFeature;
                    const lbl = { mean:'均值', std:'標準差', max:'最大', min:'最小', count:'Count' }[f] || f;
                    _epBpLine('L', f, 'y', _pLC, lbl);
                }
            } else {
                datasets.push({ label: panel.yLeft, data: sk.map(k=>groups[k].L), backgroundColor:_hexToRgba(_pLC,0.5), borderColor:_pLC, borderWidth:1, outlierColor:'#999', itemRadius:2, meanRadius:0, yAxisID:'y' });
            }
        }
        if (yRIdx !== -1) {
            if (panel.yRightFeature) {
                if (panel.yRightFeature === 'range') {
                    _epBpLine('R', 'max', 'y1', _pRC, '最大');
                    _epBpLine('R', 'min', 'y1', _pRC, '最小');
                } else {
                    const f = panel.yRightFeature === 'std1' || panel.yRightFeature === 'std' ? 'std' : panel.yRightFeature;
                    const lbl = { mean:'均值', std:'標準差', max:'最大', min:'最小', count:'Count' }[f] || f;
                    _epBpLine('R', f, 'y1', _pRC, lbl);
                }
            } else {
                datasets.push({ label: panel.yRight, data: sk.map(k=>groups[k].R), backgroundColor:_hexToRgba(_pRC,0.5), borderColor:_pRC, borderWidth:1, outlierColor:'#999', itemRadius:2, meanRadius:0, yAxisID:'y1' });
            }
        }
    } else {
        const step = Math.ceil(sourceRows.length / 5000);
        const _DT_RE = /^\d{4}[-/]\d{2}[-/]\d{2}([T ]\d{2}:\d{2})?/;
        const _sX = chartConfig.x !== '__row_index__' ? sourceRows.slice(0,20).map(r=>r[xIdx]).filter(v=>v!=null) : [];
        const _isRawDT = _sX.length > 0 && _sX.filter(v=>_DT_RE.test(String(v))).length > _sX.length * 0.7;
        isDatetimeX = _isRawDT && datetimeXMode === 'timegap';
        for (let i = 0; i < sourceRows.length; i += step) {
            const row = sourceRows[i];
            let xVal = chartConfig.x === '__row_index__' ? i+1 : row[xIdx];
            let vL = yLIdx !== -1 ? row[yLIdx] : null;
            let vR = yRIdx !== -1 ? row[yRIdx] : null;
            if (isDatetimeX && xVal != null) {
                const ts = new Date(String(xVal).replace(' ', 'T')).getTime();
                xVal = isNaN(ts) ? xVal : ts;
            } else if (xVal != null) {
                const s = String(xVal).trim();
                if (s !== '' && isFinite(s)) {
                    xVal = parseFloat(s);
                } else if (s === '') {
                    xVal = null;
                }
            }
            if (vL !== null && !isNaN(parseFloat(vL))) vL = parseFloat(vL); else vL = null;
            if (vR !== null && !isNaN(parseFloat(vR))) vR = parseFloat(vR); else vR = null;
            // Skip rows where X is NaN/null/empty
            if (xVal == null || (typeof xVal === 'number' && isNaN(xVal))) continue;
            if (vL !== null) dpL.push({ x: xVal, y: vL });
            if (vR !== null) dpR.push({ x: xVal, y: vR });
        }
        isNumericX = (dpL.length > 0 ? dpL : dpR).every(p => typeof p.x==='number' && !isNaN(p.x));
        if (isNumericX && chartType === 'line') { dpL.sort((a,b)=>a.x-b.x); dpR.sort((a,b)=>a.x-b.x); }
        if (!isNumericX) {
            const uX = [...new Set([...dpL.map(p=>String(p.x)),...dpR.map(p=>String(p.x))])].sort((a,b)=>{ const na=parseFloat(a),nb=parseFloat(b); return (!isNaN(na)&&!isNaN(nb))?na-nb:a.localeCompare(b,undefined,{numeric:true,sensitivity:'base'}); });
            labels = uX.length===1 ? ['', uX[0], ' '] : uX;
            // Map category strings to numeric indices for correct scatter rendering
            const cmap = {};
            labels.forEach((l, i) => cmap[l] = i);
            dpL.forEach(p => { p._catLabel = String(p.x); p.x = cmap[String(p.x)] ?? 0; });
            dpR.forEach(p => { p._catLabel = String(p.x); p.x = cmap[String(p.x)] ?? 0; });
            isNumericX = true;
            isCatMappedX = true;
        }
        const _pLC = panel.yLeftColor||'#ea580c', _pRC2 = panel.yRightColor||'#10b981';
        if (yLIdx !== -1) {
            if (panel.yLeftFeature) {
                _addStatLineDatasets(datasets, null, panel.yLeftFeature, 'y', _pLC, isNumericX, null, null, labels, dpL);
            } else {
                datasets.push({ label: panel.yLeft, data: dpL, yAxisID:'y', borderColor:'#ea580c', backgroundColor:'rgba(234,88,12,0.5)', pointRadius: chartType==='scatter'?4:2, showLine: chartType==='line', tension:0.1 });
            }
        }
        if (yRIdx !== -1) {
            if (panel.yRightFeature) {
                _addStatLineDatasets(datasets, null, panel.yRightFeature, 'y1', _pRC2, isNumericX, null, null, labels, dpR);
            } else {
                datasets.push({ label: panel.yRight, data: dpR, yAxisID:'y1', borderColor:'#10b981', backgroundColor:'rgba(16,185,129,0.5)', pointRadius: chartType==='scatter'?4:2, showLine: chartType==='line', tension:0.1 });
            }
        }
    }

    const _dtTickCb = (val) => {
        const pts = dpL.length > 0 ? dpL : dpR;
        const rangeMs = pts.length > 1 ? pts[pts.length-1].x - pts[0].x : 0;
        return _fmtDt(val, rangeMs);
    };
    const xTickOpts = isCatMappedX ? {
        callback: (val) => (labels || [])[Math.round(val)] ?? '',
        stepSize: 1, maxRotation: 45, autoSkip: true,
        maxTicksLimit: Math.min((labels||[]).length, 12), font: { size: 10 }
    } : isDatetimeX ? {
        callback: _dtTickCb, maxRotation:30, autoSkip:true, maxTicksLimit:10, font:{size:10}
    } : chartType === 'boxplot' ? {
        // category scale: val is the category index, look up label string
        callback: (val, idx) => (labels || [])[val] ?? (labels || [])[idx] ?? String(val),
        maxRotation: 45, autoSkip: true, maxTicksLimit: Math.min((labels||[]).length || 12, 12), font: { size: 10 }
    } : {
        callback: (val) => {
            if (typeof val !== 'number') return val;
            const pts = dpL.length > 0 ? dpL : dpR;
            const range = (pts.length > 1 ? Math.max(...pts.map(p => p.x)) - Math.min(...pts.map(p => p.x)) : 1) || 1;
            const decimals = range < 0.01 ? 4 : range < 0.1 ? 3 : range < 1 ? 2 : range < 100 ? 1 : 0;
            return val.toFixed(decimals);
        },
        maxRotation: 45, minRotation: 0, autoSkip: true, maxTicksLimit: 8, font: { size: 10 }
    };

    const _epHasFeature = panel.yLeftFeature || panel.yRightFeature;
    const _epRenderType = (chartType === 'boxplot' && _epHasFeature) ? 'line' : chartType;
    const _epFLblMap = { mean:'均值', std1:'標準差', std:'標準差', max:'最大', min:'最小', range:'值域', count:'Count' };
    const _epYLFLbl = panel.yLeftFeature ? (_epFLblMap[panel.yLeftFeature] || panel.yLeftFeature) : null;
    const _epYRFLbl = panel.yRightFeature ? (_epFLblMap[panel.yRightFeature] || panel.yRightFeature) : null;
    panel.chart = new Chart(ctx, {
        type: _epRenderType,
        data: { labels: (isCatMappedX || (chartType === 'boxplot' && _epHasFeature)) ? labels : (labels || null), datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            layout: { padding: { right: 0 } },
            scales: {
                x: { type: chartType === 'boxplot' ? 'category' : 'linear', offset: chartType === 'boxplot' || isCatMappedX, title:{ display: false }, ticks:{ display: isLast, ...xTickOpts }, grid:{color:'#f1f5f9'}, beginAtZero:false },
                y: { title:{display:true, text:(panel.yLeft||'') + (_epYLFLbl ? ` (${_epYLFLbl})` : ''), color: panel.yLeftColor||'#ea580c'}, type:'linear', display:true, position:'left', grid:{color:'#f1f5f9'}, grace: panel.yLeftMin!=null||panel.yLeftMax!=null ? 0 : '5%', beginAtZero:false, ...(panel.yLeftMin!=null?{min:panel.yLeftMin}:{}), ...(panel.yLeftMax!=null?{max:panel.yLeftMax}:{}), afterFit(scale){ scale.width = 85; } },
                y1: { title:{display:!!panel.yRight, text:(panel.yRight||'') + (_epYRFLbl ? ` (${_epYRFLbl})` : ''), color: panel.yRightColor||'#10b981'}, ticks:{display:!!panel.yRight}, type:'linear', display:true, position:'right', grid:{drawOnChartArea:false, display:!!panel.yRight}, grace: panel.yRightMin!=null||panel.yRightMax!=null ? 0 : '5%', beginAtZero:false, ...(panel.yRightMin!=null?{min:panel.yRightMin}:{}), ...(panel.yRightMax!=null?{max:panel.yRightMax}:{}), afterFit(scale){ scale.width = 85; } }
            },
            plugins: { legend:{display:false}, tooltip:{mode:'__row_index__',intersect:false} }
        }
    });
}

// ─── End Dynamic Extra Panel System ─────────────────────────────────────────

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
            // Refresh file list: works in both dashboard (direct) and iframe (postMessage) context
            if (FileMgr && FileMgr.loadFileList) FileMgr.loadFileList();
            if (window.parent !== window) window.parent.postMessage({ type: 'sigma2:refreshFiles' }, '*');
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

let _filterChartTimer = null;
export function filterChartColumns(query) {
    clearTimeout(_filterChartTimer);
    _filterChartTimer = setTimeout(() => {
        const chips = document.querySelectorAll('.draggable-chip');
        const q = query.toLowerCase();
        chips.forEach(chip => {
            const match = (chip.dataset.header || '').toLowerCase().includes(q);
            chip.style.display = match ? 'block' : 'none';
        });
    }, 120);
}

// --- Selection Mode & Chart Types ---


export function toggleSelectionMode() {
    selectionMode = !selectionMode;
    const btn = document.getElementById('btn-selection-mode');
    const cvs = document.getElementById('analysis-chart-canvas');
    if (selectionMode) {
        btn.innerText = '🖱️ 框選模式: 開啟';
        btn.style.background = '#eff6ff';
        btn.style.color = '#3b82f6';
        btn.style.borderColor = '#3b82f6';
        if (cvs) cvs.style.cursor = 'crosshair';
    } else {
        btn.innerText = '🖱️ 框選模式: 關閉';
        btn.style.background = '#fff';
        btn.style.color = '#475569';
        btn.style.borderColor = '#cbd5e1';
        if (cvs) cvs.style.cursor = '';
    }
}

function _detectXAxisType() {
    // Returns: 'category' | 'datetime' | 'datetime-cat' | 'numeric' | 'text' | 'rowindex'
    // 'datetime'     = linear timescale with gaps (datetimeXMode === 'timegap')
    // 'datetime-cat' = category scale, boxplot allowed (datetimeXMode === 'category')
    if (!chartConfig.x || chartConfig.x === '__row_index__') return 'rowindex';
    const dtype = _getDtype(chartConfig.x, null);
    if (dtype === '類別') return 'category';
    if (dtype === '數值') return 'numeric';
    if (dtype === '文字') return 'text';

    const _DT_RE = /^\d{4}[-/]\d{2}[-/]\d{2}([T ]\d{2}:\d{2})?/;
    let isDatetime = dtype === '日期';
    if (!isDatetime && tableHeaders.includes(chartConfig.x)) {
        const xIdx = tableHeaders.indexOf(chartConfig.x);
        const samples = originalTableData.slice(0, 20).map(r => r[xIdx]).filter(v => v != null);
        if (samples.length > 0 && samples.filter(v => _DT_RE.test(String(v))).length > samples.length * 0.7) isDatetime = true;
        else if (samples.length > 0) {
            const numericCount = samples.filter(v => !isNaN(parseFloat(v)) && String(v).trim() === String(parseFloat(v))).length;
            if (numericCount < samples.length * 0.5) {
                // High cardinality (many unique values) → text; low cardinality → category
                const uniq = new Set(samples.map(v => String(v))).size;
                return uniq > Math.min(20, samples.length * 0.5) ? 'text' : 'category';
            }
        }
    }
    if (isDatetime) return datetimeXMode === 'timegap' ? 'datetime' : 'datetime-cat';
    return 'numeric';
}

function _updateScatterAvailability() {
    const scatterBtn = document.getElementById('btn-chart-scatter');
    const lineBtn = document.getElementById('btn-chart-line');
    const boxBtn = document.getElementById('btn-chart-boxplot');
    if (!scatterBtn) return;

    const xType = _detectXAxisType();
    const isCatX = xType === 'category';
    const isNumericX = xType === 'numeric' || xType === 'rowindex';
    const isDatetimeGap = xType === 'datetime'; // timegap mode: no boxplot
    const noBoxplot = isDatetimeGap || isNumericX; // boxplot not supported for numeric/datetime-gap X

    // Category X: hide scatter+line
    scatterBtn.style.display = isCatX ? 'none' : '';
    if (lineBtn) lineBtn.style.display = isCatX ? 'none' : '';
    // Numeric / datetime timegap: hide boxplot
    if (boxBtn) boxBtn.style.display = noBoxplot ? 'none' : '';

    if (isCatX && (chartConfig.type === 'scatter' || chartConfig.type === 'line')) setChartType('boxplot');
    if (noBoxplot && chartConfig.type === 'boxplot') setChartType('scatter');

    extraPanels.forEach(panel => {
        _updatePanelTypeButtons(panel.id, panel.type);
        if (isCatX && (panel.type === 'scatter' || panel.type === 'line')) {
            panel.type = 'boxplot'; _updatePanelTypeButtons(panel.id, 'boxplot'); _renderExtraPanel(panel);
        }
        if (noBoxplot && panel.type === 'boxplot') {
            panel.type = 'scatter'; _updatePanelTypeButtons(panel.id, 'scatter'); _renderExtraPanel(panel);
        }
    });
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

// ─── Box Statistics Helper ───────────────────────────────────────────────────

function _computeBoxStats(values) {
    if (!values.length) return null;
    const sorted = [...values].sort((a, b) => a - b);
    const n = sorted.length;
    const q1 = sorted[Math.floor(n * 0.25)];
    const median = n % 2 === 0 ? (sorted[n/2-1] + sorted[n/2]) / 2 : sorted[Math.floor(n/2)];
    const q3 = sorted[Math.floor(n * 0.75)];
    const iqr = q3 - q1;
    const whiskerLow  = q1 - 1.5 * iqr;
    const whiskerHigh = q3 + 1.5 * iqr;
    const min = Math.max(sorted[0], whiskerLow);
    const max = Math.min(sorted[n-1], whiskerHigh);
    const outliers = sorted.filter(v => v < min || v > max);
    const mean = values.reduce((a, b) => a + b, 0) / n;
    return { min, q1, median, mean, q3, max, outliers, items: sorted };
}

// ─── Y-Axis Config Popup ─────────────────────────────────────────────────────

// Format a timestamp adaptively based on the range of the data
// range < 2 days → show time only; < 1 year → show MM/DD HH:MM; else → show YYYY/MM
function _fmtDt(ts, rangeMs) {
    const d = new Date(ts);
    if (isNaN(d)) return String(ts);
    const DAY = 86400000, YEAR = 365 * DAY;
    if (rangeMs < 2 * DAY) {
        return d.toLocaleTimeString('zh-TW', {hour:'2-digit', minute:'2-digit', second:'2-digit'});
    } else if (rangeMs < YEAR) {
        return d.toLocaleDateString('zh-TW', {month:'2-digit', day:'2-digit'}) + ' ' +
               d.toLocaleTimeString('zh-TW', {hour:'2-digit', minute:'2-digit'});
    } else {
        return d.toLocaleDateString('zh-TW', {year:'numeric', month:'2-digit'});
    }
}

function _hexToRgba(hex, alpha) {
    try {
        const r = parseInt(hex.slice(1,3),16), g = parseInt(hex.slice(3,5),16), b = parseInt(hex.slice(5,7),16);
        return `rgba(${r},${g},${b},${alpha})`;
    } catch(e) { return `rgba(124,58,237,${alpha})`; }
}

function _addStatLineDatasets(datasets, sourceVals, feature, yAxisID, color, isNumericX, xMin, xMax, labels, dataPoints) {
    if (!feature) return;

    // ── Per-X aggregation mode (scatter / line) ──────────────────────────────
    if (dataPoints && dataPoints.length > 0) {
        const groupMap = new Map();
        dataPoints.forEach(p => {
            if (p.y == null || isNaN(p.y)) return;
            const key = p.x;
            if (!groupMap.has(key)) groupMap.set(key, []);
            groupMap.get(key).push(p.y);
        });

        const sortedKeys = [...groupMap.keys()].sort((a, b) => a - b);

        const _statFn = (yVals, mult, side) => {
            const v = yVals.filter(n => !isNaN(n));
            if (!v.length) return null;
            const mean = v.reduce((a,b)=>a+b,0)/v.length;
            const s = Math.sqrt(v.reduce((a,n)=>a+(n-mean)**2,0)/v.length);
            if (side === 'mean') return mean;
            if (side === 'max') return Math.max(...v);
            if (side === 'min') return Math.min(...v);
            if (side === 'up') return mean + mult * s;
            if (side === 'dn') return mean - mult * s;
            return null;
        };

        const _agg = (yVals, type) => {
            if (type === 'count') return yVals.length;
            const v = yVals.filter(n => !isNaN(n));
            if (!v.length) return null;
            const mean = v.reduce((a,b)=>a+b,0)/v.length;
            const s = Math.sqrt(v.reduce((a,n)=>a+(n-mean)**2,0)/v.length);
            return { mean, max: Math.max(...v), min: Math.min(...v), std: s }[type] ?? null;
        };

        // Check if all groups are single-point (aggregation would be meaningless for std)
        const allSinglePoint = sortedKeys.every(k => groupMap.get(k).length <= 1);

        const makeLine = (aggType, lbl) => {
            // For std on single-point groups, std=0 which plots at y=0 and is invisible/misleading
            // Fall back to mean so user sees something useful
            const effectiveType = (aggType === 'std' && allSinglePoint) ? 'mean' : aggType;
            const effectiveLbl = lbl;
            const pts = sortedKeys.map(xk => {
                const y = _agg(groupMap.get(xk), effectiveType);
                return y != null ? { x: xk, y } : null;
            }).filter(Boolean);
            if (!pts.length) return;
            datasets.push({
                label: effectiveLbl, data: pts, type: 'line', yAxisID,
                borderColor: color, backgroundColor: _hexToRgba(color, 0.5),
                borderWidth: 2, pointRadius: 3, showLine: true, tension: 0.3,
                order: -2
            });
        };

        if (feature === 'mean')  { makeLine('mean', '均值'); }
        else if (feature === 'std1' || feature === 'std') { makeLine('std', '標準差'); }
        else if (feature === 'max')   { makeLine('max', '最大'); }
        else if (feature === 'min')   { makeLine('min', '最小'); }
        else if (feature === 'range') { makeLine('max', '最大'); makeLine('min', '最小'); }
        else if (feature === 'count') { makeLine('count', 'Count'); }
        return;
    }

    // ── Fallback: global horizontal reference line (boxplot / no dataPoints) ─
    const vals = (sourceVals || []).filter(v => typeof v === 'number' && !isNaN(v));
    if (!vals.length) return;
    const mean = vals.reduce((a,b)=>a+b,0)/vals.length;
    const entries = [];
    const s = Math.sqrt(vals.reduce((a,v)=>a+(v-mean)**2,0)/vals.length);
    if (feature === 'mean') entries.push([mean, `均值: ${mean.toFixed(3)}`]);
    else if (feature === 'max') entries.push([Math.max(...vals), `最大: ${Math.max(...vals).toFixed(3)}`]);
    else if (feature === 'min') entries.push([Math.min(...vals), `最小: ${Math.min(...vals).toFixed(3)}`]);
    else if (feature === 'std' || feature === 'std1') {
        entries.push([mean+s, `+1σ: ${(mean+s).toFixed(3)}`], [mean-s, `-1σ: ${(mean-s).toFixed(3)}`]);
    } else if (feature === 'range') {
        entries.push([Math.max(...vals), `最大: ${Math.max(...vals).toFixed(3)}`], [Math.min(...vals), `最小: ${Math.min(...vals).toFixed(3)}`]);
    } else if (feature === 'count') {
        entries.push([vals.length, `Count: ${vals.length}`]);
    }
    entries.forEach(([v, lbl]) => {
        let dotData;
        if (isNumericX) {
            const xMid = (xMin + xMax) / 2;
            dotData = [{ x: xMid, y: v }];
        } else {
            const midIdx = Math.floor(((labels || []).length - 1) / 2);
            dotData = (labels || []).map((_, i) => i === midIdx ? v : null);
        }
        datasets.push({
            label: lbl, data: dotData, type: 'scatter', yAxisID,
            backgroundColor: color, borderColor: '#fff',
            borderWidth: 2, pointRadius: 9, pointHoverRadius: 11,
            pointStyle: 'circle', order: -2
        });
    });
}

export function openYAxisPopup(panelId, axis, event) {
    event.stopPropagation();
    _yAxisPopupState = { panelId, axis };
    const popup = document.getElementById('yaxis-config-popup');
    if (!popup) return;
    let color, min, max, feature, title;
    if (panelId === null) {
        if (axis === 'y') {
            color = chartConfig.yColor||'#7c3aed'; min = chartConfig.yMin??''; max = chartConfig.yMax??''; feature = chartConfig.yFeature||'';
            const _yName = chartConfig.y || DOM.get('drop-y')?.querySelector('span[onclick*="openYAxisPopup"]')?.textContent?.replace(/\s*\(.*\)$/, '').trim() || '—';
            title = `Y1: ${_yName}`;
        } else {
            color = chartConfig.y2Color||'#06b6d4'; min = chartConfig.y2Min??''; max = chartConfig.y2Max??''; feature = chartConfig.y2Feature||'';
            const _y2Name = chartConfig.y2 || DOM.get('drop-y2')?.querySelector('span[onclick*="openYAxisPopup"]')?.textContent?.replace(/\s*\(.*\)$/, '').trim() || '—';
            title = `Y2: ${_y2Name}`;
        }
    } else {
        const panel = extraPanels.find(p => p.id === panelId);
        if (!panel) return;
        if (axis === 'left') {
            color = panel.yLeftColor||'#ea580c'; min = panel.yLeftMin??''; max = panel.yLeftMax??''; feature = panel.yLeftFeature||'';
            title = `Y1: ${panel.yLeft || '—'}`;
        } else {
            color = panel.yRightColor||'#10b981'; min = panel.yRightMin??''; max = panel.yRightMax??''; feature = panel.yRightFeature||'';
            title = `Y2: ${panel.yRight || '—'}`;
        }
    }
    document.getElementById('yaxis-popup-title').textContent = title;
    document.getElementById('yaxis-popup-color').value = color;
    document.getElementById('yaxis-popup-min').value = min;
    document.getElementById('yaxis-popup-max').value = max;
    document.getElementById('yaxis-popup-feature').value = feature;
    // Sync swatch highlight
    document.querySelectorAll('#yaxis-popup-swatches .yap-swatch').forEach(s => {
        s.style.outline = s.dataset.c.toLowerCase() === color.toLowerCase() ? '2.5px solid #3b82f6' : 'none';
    });
    const px = Math.min(event.clientX + 12, window.innerWidth - 260);
    const py = Math.min(event.clientY - 10, window.innerHeight - 340);
    popup.style.left = px + 'px';
    popup.style.top = py + 'px';
    popup.style.display = 'block';
    const bd = document.getElementById('yaxis-popup-backdrop');
    if (bd) bd.style.display = 'block';
}

window._yapPickColor = function(el) {
    const c = el.dataset.c;
    document.getElementById('yaxis-popup-color').value = c;
    document.querySelectorAll('#yaxis-popup-swatches .yap-swatch').forEach(s => {
        s.style.outline = s.dataset.c === c ? '2.5px solid #3b82f6' : 'none';
    });
};

export function closeYAxisPopup() {
    const popup = document.getElementById('yaxis-config-popup');
    if (popup) popup.style.display = 'none';
    const bd = document.getElementById('yaxis-popup-backdrop');
    if (bd) bd.style.display = 'none';
}

export function applyYAxisConfig() {
    const color = document.getElementById('yaxis-popup-color').value;
    const minRaw = document.getElementById('yaxis-popup-min').value;
    const maxRaw = document.getElementById('yaxis-popup-max').value;
    const feature = document.getElementById('yaxis-popup-feature').value;
    let min = minRaw === '' ? null : parseFloat(minRaw);
    let max = maxRaw === '' ? null : parseFloat(maxRaw);
    // Validate: if both set and min >= max, swap them
    if (min != null && max != null && min >= max) {
        [min, max] = [max, min];
        document.getElementById('yaxis-popup-min').value = min;
        document.getElementById('yaxis-popup-max').value = max;
    }
    const { panelId, axis } = _yAxisPopupState;
    if (panelId === null) {
        if (axis === 'y') { chartConfig.yColor=color; chartConfig.yMin=min; chartConfig.yMax=max; chartConfig.yFeature=feature||null; }
        else              { chartConfig.y2Color=color; chartConfig.y2Min=min; chartConfig.y2Max=max; chartConfig.y2Feature=feature||null; }
        if (chartConfig.y) updateDropzoneUI('y', chartConfig.y);
        if (chartConfig.y2) updateDropzoneUI('y2', chartConfig.y2);
        renderAnalysisChart();
    } else {
        const panel = extraPanels.find(p => p.id === panelId);
        if (!panel) return;
        if (axis === 'left') { panel.yLeftColor=color; panel.yLeftMin=min; panel.yLeftMax=max; panel.yLeftFeature=feature||null; }
        else                 { panel.yRightColor=color; panel.yRightMin=min; panel.yRightMax=max; panel.yRightFeature=feature||null; }
        if (panel.yLeft) _updateExtraPanelDropzoneUI(panelId, 'left', panel.yLeft, panel.yLeftFeature);
        if (panel.yRight) _updateExtraPanelDropzoneUI(panelId, 'right', panel.yRight, panel.yRightFeature);
        _renderExtraPanel(panel);
    }
    closeYAxisPopup();
}

let _chartFsOverlay = null;
let _chartFsOrigParent = null;
let _chartFsOrigNextSibling = null;
let _chartFsActive = false;

function _chartFsEscHandler(e) { if (e.key === 'Escape') toggleChartFullscreen(); }

export function toggleChartFullscreen() {
    const container = document.getElementById('analysis-chart-view');
    const btn = document.getElementById('btn-chart-fullscreen');
    if (!container) return;
    if (!_chartFsActive) {
        _chartFsOrigParent = container.parentElement;
        _chartFsOrigNextSibling = container.nextSibling;
        _chartFsOverlay = document.createElement('div');
        _chartFsOverlay.style.cssText = 'position:fixed;inset:0;z-index:8000;background:#fff;display:flex;flex-direction:column;box-sizing:border-box;';
        container.style.flex = '1';
        container.style.minHeight = '0';
        container.style.display = 'flex';
        _chartFsOverlay.appendChild(container);
        document.body.appendChild(_chartFsOverlay);
        if (btn) btn.textContent = '✕ 縮小';
        _chartFsActive = true;
        document.addEventListener('keydown', _chartFsEscHandler);
    } else {
        container.style.flex = '';
        container.style.minHeight = '';
        if (_chartFsOrigNextSibling) _chartFsOrigParent.insertBefore(container, _chartFsOrigNextSibling);
        else _chartFsOrigParent.appendChild(container);
        if (_chartFsOverlay) { _chartFsOverlay.remove(); _chartFsOverlay = null; }
        if (btn) btn.textContent = '⛶';
        _chartFsActive = false;
        document.removeEventListener('keydown', _chartFsEscHandler);
    }
}
document.addEventListener('click', (e) => {
    const popup = document.getElementById('yaxis-config-popup');
    if (popup && popup.style.display !== 'none' && !popup.contains(e.target)) closeYAxisPopup();
});

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
window.openYAxisPopup = openYAxisPopup;
window.closeYAxisPopup = closeYAxisPopup;
window.applyYAxisConfig = applyYAxisConfig;
window.resetExtraPanelAxis = resetExtraPanelAxis;
window.clearExtraPanelAxis = clearExtraPanelAxis;
window.toggleChartFullscreen = toggleChartFullscreen;
window.toggleDatetimeMode = toggleDatetimeMode;

// Large file preview control
export function applyLargePreview() {
    const mode = document.getElementById('preview-mode-select')?.value || 'head';
    const count = parseInt(document.getElementById('preview-count-input')?.value) || 100;
    window._largePreviewMode = mode;
    window._largePreviewCount = Math.max(10, Math.min(10000, count));
    // Remove old ctrl bar so it gets re-created with updated values
    const old = document.getElementById('large-preview-ctrl');
    if (old) old.remove();
    originalTableData = [];
    loadAnalysisPage(-1);
}
window.applyLargePreview = applyLargePreview;

function updateSelectionUI() {
    const modal = document.getElementById('selection-modal');
    const countText = document.getElementById('selection-count-text');

    if (!currentChartSelectionRange) {
        modal.style.display = 'none';
        return;
    }

    const count = currentChartSelectionRange._selectedIndices ? currentChartSelectionRange._selectedIndices.length : 0;
    modal.style.display = 'flex';
    countText.innerHTML = `📍 已選取 <b style="color:#7c3aed; font-size:16px;">${count}</b> 筆`;
}

function highlightPointsInChart() {
    if (!analysisChart || !currentChartSelectionRange) return;

    const selectedSet = new Set(currentChartSelectionRange._selectedIndices || []);

    analysisChart.data.datasets.forEach((ds, dsIdx) => {
        const pointColors = [];
        const pointSizes = [];

        ds.data.forEach(p => {
            const isSelected = p._origIdx !== undefined && selectedSet.has(p._origIdx);

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

    const selectedIndices = currentChartSelectionRange._selectedIndices || [];

    if (selectedIndices.length === 0) return;

    // 判斷是否為取樣模式（大型資料集）
    const isSampled = window._largePreviewMode === 'sample' && originalTableData.length < analysisTotalLines - 1;

    console.log('[框選擴散] mode:', mode, 'selectedIndices:', selectedIndices.length,
        'isSampled:', isSampled, '_largePreviewMode:', window._largePreviewMode,
        'tableLen:', originalTableData.length, 'totalLines:', analysisTotalLines);

    if (isSampled) {
        const uniqueIndices = [...new Set(selectedIndices)];
        // 取樣模式：偵測時間欄位，用時間區間擴散到完整資料
        const timeColIdx = _findTimeColumnIndex(tableHeaders);
        console.log('[框選擴散] timeColIdx:', timeColIdx,
            timeColIdx >= 0 ? 'timeCol=' + tableHeaders[timeColIdx] : '(無時間欄位，改用 row index)');

        if (timeColIdx >= 0) {
            const timeValues = uniqueIndices
                .map(i => originalTableData[i] ? originalTableData[i][timeColIdx] : null)
                .filter(v => v != null && String(v).trim() !== '')
                .map(v => String(v).trim())
                .sort();

            console.log('[框選擴散] timeValues:', timeValues.length, 'first:', timeValues[0], 'last:', timeValues[timeValues.length-1]);

            if (timeValues.length > 0) {
                const tMin = timeValues[0];
                const tMax = timeValues[timeValues.length - 1];
                clearChartSelection();

                // 從後端載入完整資料中該時間範圍的所有 row
                _loadFullTimeRange(timeColIdx, tMin, tMax, mode, uniqueIndices.length);
                return;
            }
        }

        // 找不到時間欄位：用 row index 範圍做擴散
        // 取樣是等距的，所以 __idx 對應到取樣陣列中的位置
        // 我們把 min/max __idx 映射回原始 CSV 的 row index 範圍
        const idxValues = uniqueIndices
            .map(i => originalTableData[i] ? originalTableData[i].__idx : null)
            .filter(v => v != null);
        console.log('[框選擴散] row index fallback — idxValues:', idxValues.length,
            'min:', Math.min(...idxValues), 'max:', Math.max(...idxValues));

        if (idxValues.length > 0) {
            const minIdx = Math.min(...idxValues);
            const maxIdx = Math.max(...idxValues);
            const totalOriginal = analysisTotalLines - 1;
            const sampleSize = originalTableData.length;
            // 等距取樣: sample index i → original row ≈ i * (totalOriginal / sampleSize)
            const rowMin = Math.floor(minIdx * (totalOriginal / sampleSize));
            const rowMax = Math.min(totalOriginal - 1, Math.ceil(maxIdx * (totalOriginal / sampleSize)));
            console.log('[框選擴散] rowMin:', rowMin, 'rowMax:', rowMax, 'totalOriginal:', totalOriginal, 'sampleSize:', sampleSize);
            clearChartSelection();
            _loadFullRowRange(rowMin, rowMax, mode, uniqueIndices.length);
            return;
        }
    }

    // 非取樣模式（或找不到時間欄位）：用原始 index 精確選取
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
        tryUpdateChart();
    }
}

/** 從後端載入完整時間範圍資料，替換 originalTableData */
async function _loadFullTimeRange(timeColIdx, tMin, tMax, mode, sampledCount) {
    const sid = _getSessionId();
    const timeCol = tableHeaders[timeColIdx];
    const pillText = mode === 'keep'
        ? `時間選取: ${tMin} ~ ${tMax}`
        : `時間排除: ${tMin} ~ ${tMax}`;

    // 顯示載入中（只更新 analysis-content，不破壞 analysis-table-view 的子結構）
    const loadingEl = document.getElementById('analysis-content');
    const oldHtml = loadingEl ? loadingEl.innerHTML : '';
    if (loadingEl) {
        loadingEl.innerHTML = `<div style="text-align:center;padding:40px;color:#64748b;">
            <div style="font-size:14px;font-weight:600;margin-bottom:8px;">擴散框選中...</div>
            <div style="font-size:12px;">從取樣 ${sampledCount} 筆擴散到完整資料的時間區間 ${tMin} ~ ${tMax}</div>
        </div>`;
    }

    try {
        const resp = await fetch(`/api/files/view-time-range/${encodeURIComponent(analysisFilename)}?session_id=${encodeURIComponent(sid)}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ time_col: timeCol, time_min: tMin, time_max: tMax, mode })
        });
        if (!resp.ok) throw new Error('API failed');
        const data = await resp.json();

        // 解析回傳的 CSV
        const csvText = (data.content || '').trim();
        if (!csvText) throw new Error('後端回傳空白內容');

        const parsed = _parseCsvContent(csvText);
        if (parsed.length < 2) throw new Error('回傳資料不足');

        // parsed[0] 是 header，之後是 data rows
        tableHeaders = parsed[0];
        originalTableData = parsed.slice(1).map((arr, idx) => { arr.__idx = idx; return arr; });

        const filteredCount = data.filtered_count || originalTableData.length;
        const sampledReturnCount = data.sampled_count || originalTableData.length;
        const originalCount = data.original_count || 0;
        const isSampledResponse = data.is_sampled || false;

        // analysisTotalLines = header + data rows actually loaded
        analysisTotalLines = originalTableData.length + 1;

        // 清除所有舊 filter（資料已經換了，舊的 index filter 無效）
        activeFilters.length = 0;

        // 標記不再是取樣模式（已載入實際時間範圍資料）
        window._largePreviewMode = 'filtered';

        // 移除大型資料集的取樣 banner
        const ctrlBar = document.getElementById('large-preview-ctrl');
        if (ctrlBar) ctrlBar.remove();

        // 組合顯示文字
        let expandInfo = pillText;
        if (isSampledResponse) {
            expandInfo += ` (符合 ${filteredCount} 筆，取樣顯示 ${sampledReturnCount} 筆)`;
        } else {
            expandInfo += ` (符合 ${filteredCount} 筆)`;
        }

        // 加上 filter pill 顯示（純顯示用，資料已在後端篩選過，不需前端再 filter）
        activeFilters.push({
            colIdx: 'time_expand_info',
            colName: timeCol,
            type: mode === 'keep' ? 'time_range_display' : 'exclude_time_range_display',
            timeMin: tMin,
            timeMax: tMax,
            value: expandInfo,
            _sampledCount: sampledCount,
            _filteredCount: filteredCount,
            _isExpanded: true
        });

        // 更新顯示
        const headerText = isSampledResponse
            ? `(篩選: ${filteredCount} 筆，取樣顯示: ${sampledReturnCount} / 原始: ${originalCount} | 欄位: ${tableHeaders.length})`
            : `(目前顯示: ${originalTableData.length} / 原始: ${originalCount} | 欄位: ${tableHeaders.length})`;
        DOM.setText('analysis-header-count', headerText);
        renderTable(tableHeaders, originalTableData, 1, analysisTotalLines);
        updateFilterBar();

        // 圖表更新獨立 try-catch，避免 Chart.js 錯誤影響已成功的表格渲染
        try {
            if (document.getElementById('analysis-chart-view').style.display !== 'none') {
                // 先銷毀舊圖表再重建，避免 stale canvas 引用
                if (analysisChart) { analysisChart.destroy(); analysisChart = null; }
                tryUpdateChart();
            }
        } catch (chartErr) {
            console.warn('擴散後圖表更新失敗（表格資料已正常載入）:', chartErr.message);
        }
    } catch (e) {
        console.error('Time range load failed:', e);
        if (loadingEl) loadingEl.innerHTML = oldHtml;
        alert('擴散選取失敗: ' + e.message);
    }
}

/** 從後端用 row index 範圍載入資料（無時間欄位時的 fallback） */
async function _loadFullRowRange(rowMin, rowMax, mode, sampledCount) {
    const sid = _getSessionId();
    const pillText = mode === 'keep'
        ? `行號選取: ${rowMin} ~ ${rowMax}`
        : `行號排除: ${rowMin} ~ ${rowMax}`;

    const loadingEl = document.getElementById('analysis-content');
    const oldHtml = loadingEl ? loadingEl.innerHTML : '';
    if (loadingEl) {
        loadingEl.innerHTML = `<div style="text-align:center;padding:40px;color:#64748b;">
            <div style="font-size:14px;font-weight:600;margin-bottom:8px;">擴散框選中...</div>
            <div style="font-size:12px;">從取樣 ${sampledCount} 筆擴散到原始行號 ${rowMin} ~ ${rowMax}</div>
        </div>`;
    }

    try {
        const resp = await fetch(`/api/files/view-time-range/${encodeURIComponent(analysisFilename)}?session_id=${encodeURIComponent(sid)}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ row_min: rowMin, row_max: rowMax, mode })
        });
        if (!resp.ok) throw new Error('API failed');
        const data = await resp.json();

        const csvText = (data.content || '').trim();
        if (!csvText) throw new Error('後端回傳空白內容');
        const parsed = _parseCsvContent(csvText);
        if (parsed.length < 2) throw new Error('回傳資料不足');

        tableHeaders = parsed[0];
        originalTableData = parsed.slice(1).map((arr, idx) => { arr.__idx = idx; return arr; });

        const filteredCount = data.filtered_count || originalTableData.length;
        const sampledReturnCount = data.sampled_count || originalTableData.length;
        const originalCount = data.original_count || 0;
        const isSampledResponse = data.is_sampled || false;

        analysisTotalLines = originalTableData.length + 1;
        activeFilters.length = 0;
        window._largePreviewMode = 'filtered';

        const ctrlBar = document.getElementById('large-preview-ctrl');
        if (ctrlBar) ctrlBar.remove();

        let expandInfo = pillText;
        if (isSampledResponse) {
            expandInfo += ` (符合 ${filteredCount} 筆，取樣顯示 ${sampledReturnCount} 筆)`;
        } else {
            expandInfo += ` (符合 ${filteredCount} 筆)`;
        }

        activeFilters.push({
            colIdx: 'row_expand_info',
            colName: '行號範圍',
            type: mode === 'keep' ? 'time_range_display' : 'exclude_time_range_display',
            value: expandInfo,
            _sampledCount: sampledCount,
            _filteredCount: filteredCount,
            _isExpanded: true
        });

        const headerText = isSampledResponse
            ? `(篩選: ${filteredCount} 筆，取樣顯示: ${sampledReturnCount} / 原始: ${originalCount} | 欄位: ${tableHeaders.length})`
            : `(目前顯示: ${originalTableData.length} / 原始: ${originalCount} | 欄位: ${tableHeaders.length})`;
        DOM.setText('analysis-header-count', headerText);
        renderTable(tableHeaders, originalTableData, 1, analysisTotalLines);
        updateFilterBar();

        try {
            if (document.getElementById('analysis-chart-view').style.display !== 'none') {
                if (analysisChart) { analysisChart.destroy(); analysisChart = null; }
                tryUpdateChart();
            }
        } catch (chartErr) {
            console.warn('擴散後圖表更新失敗（表格資料已正常載入）:', chartErr.message);
        }
    } catch (e) {
        console.error('Row range load failed:', e);
        if (loadingEl) loadingEl.innerHTML = oldHtml;
        alert('擴散選取失敗: ' + e.message);
    }
}

/** 偵測時間欄位 index：找含有 TIME/DATE/時間/日期 的欄位（也檢查原始欄位名，避免別名遮蔽） */
function _findTimeColumnIndex(headers) {
    const patterns = [/time/i, /date/i, /時間/, /日期/, /timestamp/i, /TIMETAG/i];
    // 先搜尋目前的 header（可能是別名）
    for (let i = 0; i < headers.length; i++) {
        if (patterns.some(p => p.test(headers[i]))) return i;
    }
    // 別名模式下，也搜尋原始欄位名稱
    try {
        if (localStorage.getItem('sigma2_useAlias') === '1') {
            const map = JSON.parse(localStorage.getItem('sigma2_aliases') || '{}');
            // 建立反查: aliased_name → original_name
            const rev = {};
            for (const [orig, alias] of Object.entries(map)) { rev[alias] = orig; }
            for (let i = 0; i < headers.length; i++) {
                const orig = rev[headers[i]];
                if (orig && patterns.some(p => p.test(orig))) return i;
            }
        }
    } catch (_) {}
    return -1;
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

export function calculateCorrelation() {
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

    function toNumeric(val) {
        if (val == null || String(val).trim() === '') return NaN;
        const n = Number(val);
        if (!isNaN(n)) return n;
        // Try parsing as date → timestamp (ms)
        const d = new Date(val);
        return isNaN(d.getTime()) ? NaN : d.getTime();
    }

    function getPearson(idx1, idx2) {
        if (idx1 === -1 || idx2 === -1) return null;
        let x = [], y = [];
        sourceRows.forEach(row => {
            const v1 = toNumeric(row[idx1]);
            const v2 = toNumeric(row[idx2]);
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

// Global Chart Selection Handlers — use Pointer Events + setPointerCapture for reliable drag tracking
function _initSelectionHandlers() {
    const canvas = document.getElementById('analysis-chart-canvas');
    if (!canvas) return;

    canvas.addEventListener('pointerdown', (e) => {
        if (!selectionMode || !analysisChart) return;
        e.preventDefault();
        canvas.setPointerCapture(e.pointerId); // lock all pointer events to this canvas
        isSelecting = true;
        const canvasRect = canvas.getBoundingClientRect();
        const cx = e.clientX - canvasRect.left;
        const cy = e.clientY - canvasRect.top;
        selectionStart = { cx, cy };

        const box = document.getElementById('selection-box');
        box.style.display = 'block';
        box.style.left = cx + 'px';
        box.style.top = cy + 'px';
        box.style.width = '0';
        box.style.height = '0';
    });

    canvas.addEventListener('pointermove', (e) => {
        if (!isSelecting) return;
        const canvasRect = canvas.getBoundingClientRect();
        const currentX = e.clientX - canvasRect.left;
        const currentY = e.clientY - canvasRect.top;

        const box = document.getElementById('selection-box');
        const left = Math.min(selectionStart.cx, currentX);
        const top = Math.min(selectionStart.cy, currentY);
        const width = Math.abs(currentX - selectionStart.cx);
        const height = Math.abs(currentY - selectionStart.cy);

        box.style.left = left + 'px';
        box.style.top = top + 'px';
        box.style.width = width + 'px';
        box.style.height = height + 'px';
    });

    canvas.addEventListener('pointerup', (e) => {
        if (!isSelecting) return;
        isSelecting = false;
        const box = document.getElementById('selection-box');
        box.style.display = 'none';

        if (!analysisChart) return;

        const canvasRect = canvas.getBoundingClientRect();
        const endCX = e.clientX - canvasRect.left;
        const endCY = e.clientY - canvasRect.top;

        const pXMin = Math.min(selectionStart.cx, endCX);
        const pXMax = Math.max(selectionStart.cx, endCX);
        const pYMin = Math.min(selectionStart.cy, endCY);
        const pYMax = Math.max(selectionStart.cy, endCY);

        if (Math.abs(pXMax - pXMin) > 5 || Math.abs(pYMax - pYMin) > 5) {
            const resDiv = document.getElementById('correlation-result');
            if (resDiv) resDiv.innerHTML = '';

            const selectedOrigIndices = [];
            analysisChart.data.datasets.forEach((ds, dsIdx) => {
                const meta = analysisChart.getDatasetMeta(dsIdx);
                ds.data.forEach((p, pIdx) => {
                    const el = meta.data[pIdx];
                    if (!el) return;
                    if (el.x >= pXMin && el.x <= pXMax && el.y >= pYMin && el.y <= pYMax) {
                        if (p._origIdx !== undefined) selectedOrigIndices.push(p._origIdx);
                    }
                });
            });

            currentChartSelectionRange = {
                x: chartConfig.x,
                y: chartConfig.y,
                _selectedIndices: selectedOrigIndices
            };
            updateSelectionUI();
            highlightPointsInChart();
        }
    });

    // Cancel selection if pointer leaves and is released outside
    canvas.addEventListener('pointercancel', () => {
        isSelecting = false;
        const box = document.getElementById('selection-box');
        if (box) box.style.display = 'none';
    });
}

setTimeout(_initSelectionHandlers, 500);
