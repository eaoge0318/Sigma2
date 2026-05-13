/**
 * heatmap_manager.js — 時間序列熱力圖模組
 * X = 欄位名稱, Y = 時間軸, Color = 正規化數值
 */

let _hmHeaders = [];
let _hmRows = [];
let _hmXCol = '';           // X 軸 (時間) 欄位名
let _hmSelectedCols = [];   // 勾選要畫的數值欄位
let _hmAllCols = [];        // 所有可用欄位
let _hmCanvas = null;
let _hmCtx = null;
let _hmTipEl = null;
let _hmColorScheme = 'bluered';
let _lastDrawnColsKey = '';  // track column selection for pin clearing
let _hmLastFilename = '';    // track last loaded filename to reset state
let _hmChartMode = 'heatmap'; // 'heatmap' | 'boxplot'
let _hmRowOrder = 'asc';      // 'asc' (原始) | 'desc' (逆排)
let _hmColOrder = 'asc';      // 'asc' (原始) | 'desc' (逆排)

// Brush selection mode state
let _brushMode = false;
let _brushDragging = false;
let _brushStartClient = null;
let _brushOverlay = null;
let _brushModeSetup = false;
let _hmTrendChart = null;

// Layout constants
const HM_PAD = { top: 10, bottom: 60, left: 140, right: 60 };
const HM_LEGEND_W = 20;

// ─── Color scales ───
function colorBluered(t) {
    // t: 0..1 → blue(0) → white(0.5) → red(1)
    if (t <= 0.5) {
        const s = t * 2; // 0..1
        const r = Math.round(59 + (255 - 59) * s);
        const g = Math.round(130 + (255 - 130) * s);
        const b = Math.round(246 + (255 - 246) * s);
        return `rgb(${r},${g},${b})`;
    } else {
        const s = (t - 0.5) * 2; // 0..1
        const r = 255;
        const g = Math.round(255 - (255 - 68) * s);
        const b = Math.round(255 - (255 - 68) * s);
        return `rgb(${r},${g},${b})`;
    }
}

function colorViridis(t) {
    // Simplified viridis approximation
    const r = Math.round(68 + (253 - 68) * t);
    const g = Math.round(1 + (231 - 1) * Math.sin(t * Math.PI * 0.9));
    const b = Math.round(84 + (37 - 84) * t);
    return `rgb(${r},${g},${b})`;
}

function getColor(t) {
    t = Math.max(0, Math.min(1, t));
    return _hmColorScheme === 'viridis' ? colorViridis(t) : colorBluered(t);
}

// ─── Public API ───

export function initHeatmap(headers, rows, filename = '') {
    // Guard: don't overwrite existing data with empty
    if ((!rows || rows.length === 0) && _hmRows.length > 0) {
        console.log('[Heatmap] initHeatmap called with empty rows, keeping existing', _hmRows.length, 'rows');
        // Still update headers/cols if needed
        if (headers && headers.length > 0) _hmHeaders = headers;
    } else {
        _hmHeaders = headers || [];
        _hmRows = rows || [];
    }
    if (!_hmHeaders.length) return;

    // Reset column selection if filename changed
    let fileChanged = false;
    if (filename && filename !== _hmLastFilename) {
        _hmLastFilename = filename;
        _hmSelectedCols = [];
        fileChanged = true;
        
        // Clear user inputs and modified flags so the new file auto-calculates ranges and height
        const minIn = document.getElementById('hm-color-min');
        const maxIn = document.getElementById('hm-color-max');
        const rowHIn = document.getElementById('hm-row-height');
        if (minIn) { minIn.value = ''; minIn.dataset.userModified = ''; }
        if (maxIn) { maxIn.value = ''; maxIn.dataset.userModified = ''; }
        if (rowHIn) { rowHIn.value = ''; rowHIn.dataset.userModified = ''; }
        
        // Clear canvas immediately
        if (_hmCanvas && _hmCtx) {
            _hmCtx.clearRect(0, 0, _hmCanvas.width, _hmCanvas.height);
        }
        unpinHeatmapTooltip();
    }

    _hmCanvas = document.getElementById('hm-canvas');
    _hmCtx = _hmCanvas ? _hmCanvas.getContext('2d') : null;

    // Setup tooltip
    const wrap = document.getElementById('hm-canvas-wrap');
    if (wrap && !document.getElementById('hm-tooltip')) {
        _hmTipEl = document.createElement('div');
        _hmTipEl.id = 'hm-tooltip';
        _hmTipEl.style.cssText = 'position:absolute;pointer-events:none;display:none;background:rgba(15,23,42,.92);color:#fff;padding:6px 10px;border-radius:6px;font-size:11px;line-height:1.5;white-space:nowrap;z-index:100;box-shadow:0 2px 8px rgba(0,0,0,.25);';
        wrap.appendChild(_hmTipEl);
    } else {
        _hmTipEl = document.getElementById('hm-tooltip');
    }

    // Classify columns
    _hmAllCols = [];
    _hmXCol = '';
    headers.forEach(h => {
        const lower = h.toLowerCase();
        if (!_hmXCol && (lower.includes('time') || lower.includes('date') || lower === 'datetime')) {
            _hmXCol = h;
        }
    });
    // If no time col found, use first column
    if (!_hmXCol) _hmXCol = headers[0];

    // All columns except X col are candidates
    _hmAllCols = headers.filter(h => h !== _hmXCol);

    // Auto-select numeric columns (sample up to 5 rows) ONLY if file changed or empty
    if (fileChanged || _hmSelectedCols.length === 0) {
        _hmSelectedCols = [];
        _hmAllCols.forEach(h => {
            const idx = headers.indexOf(h);
            let numCount = 0;
            const sampleN = Math.min(_hmRows.length, 5);
            for (let r = 0; r < sampleN; r++) {
                const v = _hmRows[r][idx];
                if (v !== null && v !== undefined && v !== '' && isFinite(parseFloat(v))) {
                    numCount++;
                }
            }
            if (numCount > 0) _hmSelectedCols.push(h);
        });
    }
    console.log('[Heatmap] init:', _hmHeaders.length, 'headers,', _hmRows.length, 'rows,', _hmSelectedCols.length, 'numeric cols, file:', filename);

    renderColumnSelector();
    setupHeatmapTooltip();
}

export function setHeatmapXCol(colName) {
    _hmXCol = colName;
    _hmAllCols = _hmHeaders.filter(h => h !== _hmXCol);
    // Keep selected cols that are still available
    _hmSelectedCols = _hmSelectedCols.filter(c => _hmAllCols.includes(c));
    renderColumnSelector();
    renderHeatmap();
}

export function toggleHeatmapCol(colName) {
    const idx = _hmSelectedCols.indexOf(colName);
    if (idx >= 0) _hmSelectedCols.splice(idx, 1);
    else _hmSelectedCols.push(colName);
    renderColumnSelector();
}

export function selectAllHeatmapCols() {
    _hmSelectedCols = [];
    _hmAllCols.forEach(h => {
        const idx = _hmHeaders.indexOf(h);
        const sampleN = Math.min(_hmRows.length, 5);
        for (let r = 0; r < sampleN; r++) {
            const v = _hmRows[r][idx];
            if (v !== null && v !== undefined && v !== '' && isFinite(parseFloat(v))) {
                _hmSelectedCols.push(h);
                break;
            }
        }
    });
    renderColumnSelector();
}

export function clearAllHeatmapCols() {
    _hmSelectedCols = [];
    renderColumnSelector();
}

export function invertHeatmapCols() {
    const inverted = _hmAllCols.filter(c => !_hmSelectedCols.includes(c));
    _hmSelectedCols.length = 0;
    _hmSelectedCols.push(...inverted);
    renderColumnSelector();
}

export function setHeatmapColorScheme(scheme) {
    _hmColorScheme = scheme;
}

export function drawHeatmap() {
    console.log('[Heatmap] draw:', _hmRows.length, 'rows,', _hmSelectedCols.length, 'selected cols, mode:', _hmChartMode);
    if (_hmChartMode === 'boxplot') {
        renderBoxPlot();
    } else {
        renderHeatmap();
    }
}

export function setHmChartMode(mode) {
    _hmChartMode = mode;
    // Toggle button styles
    const btnHm = document.getElementById('hm-chartmode-heatmap');
    const btnBp = document.getElementById('hm-chartmode-boxplot');
    if (btnHm) {
        btnHm.style.background = mode === 'heatmap' ? '#fff' : '#e2e8f0';
        btnHm.style.color = mode === 'heatmap' ? '#3b82f6' : '#64748b';
        btnHm.style.boxShadow = mode === 'heatmap' ? '0 1px 3px rgba(0,0,0,0.1)' : 'none';
    }
    if (btnBp) {
        btnBp.style.background = mode === 'boxplot' ? '#fff' : '#e2e8f0';
        btnBp.style.color = mode === 'boxplot' ? '#3b82f6' : '#64748b';
        btnBp.style.boxShadow = mode === 'boxplot' ? '0 1px 3px rgba(0,0,0,0.1)' : 'none';
    }
    drawHeatmap();
}

export function setHmRowOrder(order) {
    _hmRowOrder = order;  // 'asc' | 'desc'
    // Update toggle button styles
    const btnAsc = document.getElementById('hm-order-asc');
    const btnDesc = document.getElementById('hm-order-desc');
    if (btnAsc) {
        btnAsc.style.background = order === 'asc' ? '#fff' : '#e2e8f0';
        btnAsc.style.color = order === 'asc' ? '#3b82f6' : '#64748b';
        btnAsc.style.boxShadow = order === 'asc' ? '0 1px 3px rgba(0,0,0,0.1)' : 'none';
    }
    if (btnDesc) {
        btnDesc.style.background = order === 'desc' ? '#fff' : '#e2e8f0';
        btnDesc.style.color = order === 'desc' ? '#3b82f6' : '#64748b';
        btnDesc.style.boxShadow = order === 'desc' ? '0 1px 3px rgba(0,0,0,0.1)' : 'none';
    }
    drawHeatmap();
}

// Map display row index to data row index (handles row order reversal)
function _rowIdx(displayRow, nRows) {
    return _hmRowOrder === 'desc' ? (nRows - 1 - displayRow) : displayRow;
}

export function setHmColOrder(order) {
    _hmColOrder = order;
    const btnAsc = document.getElementById('hm-col-order-asc');
    const btnDesc = document.getElementById('hm-col-order-desc');
    if (btnAsc) {
        btnAsc.style.background = order === 'asc' ? '#fff' : '#e2e8f0';
        btnAsc.style.color = order === 'asc' ? '#3b82f6' : '#64748b';
        btnAsc.style.boxShadow = order === 'asc' ? '0 1px 3px rgba(0,0,0,0.1)' : 'none';
    }
    if (btnDesc) {
        btnDesc.style.background = order === 'desc' ? '#fff' : '#e2e8f0';
        btnDesc.style.color = order === 'desc' ? '#3b82f6' : '#64748b';
        btnDesc.style.boxShadow = order === 'desc' ? '0 1px 3px rgba(0,0,0,0.1)' : 'none';
    }
    drawHeatmap();
}

export function filterHeatmapCols(keyword) {
    const list = document.getElementById('hm-col-list');
    if (!list) return;
    const kw = keyword.toLowerCase();
    list.querySelectorAll('.hm-col-item').forEach(el => {
        const name = el.dataset.col || '';
        el.style.display = name.toLowerCase().includes(kw) ? '' : 'none';
    });
}

// ─── Column Selector ───

function renderColumnSelector() {
    // X axis dropdown
    const xSel = document.getElementById('hm-x-select');
    if (xSel) {
        xSel.innerHTML = _hmHeaders.map(h =>
            `<option value="${h}" ${h === _hmXCol ? 'selected' : ''}>${h}</option>`
        ).join('');
    }

    // Column checkboxes — use event delegation to avoid inline onclick issues
    const list = document.getElementById('hm-col-list');
    if (!list) return;
    list.innerHTML = _hmAllCols.map((h, i) => {
        const checked = _hmSelectedCols.includes(h);
        return `<div class="hm-col-item" data-col-idx="${i}" data-col="${h}" style="display:flex;align-items:center;gap:6px;padding:4px 0;cursor:pointer;">
            <div style="width:16px;height:16px;border-radius:3px;border:1.5px solid ${checked ? '#3b82f6' : '#cbd5e1'};background:${checked ? '#3b82f6' : '#fff'};display:flex;align-items:center;justify-content:center;flex-shrink:0;">
                ${checked ? '<span style="color:#fff;font-size:10px;font-weight:bold;">✓</span>' : ''}
            </div>
            <span style="font-size:12px;color:#334155;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${h}">${h}</span>
        </div>`;
    }).join('');

    // Event delegation for clicks (with Shift+Click range select)
    if (!list._hmClickBound) {
        list._hmClickBound = true;
        let _lastClickIdx = -1;
        let _rangeStart = -1;
        let _rangeEnd = -1;

        // Helper: update checkbox visuals in-place
        function _syncVisuals() {
            list.querySelectorAll('.hm-col-item').forEach(el => {
                const idx = parseInt(el.dataset.colIdx);
                if (isNaN(idx)) return;
                const checked = _hmSelectedCols.includes(_hmAllCols[idx]);
                const box = el.firstElementChild;
                if (box) {
                    box.style.borderColor = checked ? '#3b82f6' : '#cbd5e1';
                    box.style.background = checked ? '#3b82f6' : '#fff';
                    box.innerHTML = checked ? '<span style="color:#fff;font-size:10px;font-weight:bold;">✓</span>' : '';
                }
                // Range highlight: orange bar on anchor or range
                const inRange = (_rangeStart >= 0 && _rangeEnd >= 0 && idx >= _rangeStart && idx <= _rangeEnd);
                const isAnchor = (idx === _lastClickIdx && _rangeStart < 0);
                el.style.borderLeft = (inRange || isAnchor) ? '3px solid #f59e0b' : '3px solid transparent';
            });
            const countEl = document.getElementById('hm-col-count');
            if (countEl) countEl.textContent = `${_hmSelectedCols.length} / ${_hmAllCols.length}`;
        }

        list.addEventListener('click', e => {
            const item = e.target.closest('.hm-col-item');
            if (!item) return;
            const colIdx = parseInt(item.dataset.colIdx);
            if (isNaN(colIdx) || colIdx >= _hmAllCols.length) return;

            if (e.shiftKey && _lastClickIdx >= 0) {
                // Extend range
                _rangeStart = Math.min(_lastClickIdx, colIdx);
                _rangeEnd = Math.max(_lastClickIdx, colIdx);
                for (let i = _rangeStart; i <= _rangeEnd; i++) {
                    const col = _hmAllCols[i];
                    if (!_hmSelectedCols.includes(col)) _hmSelectedCols.push(col);
                }
            } else if (_rangeStart >= 0 && _rangeEnd >= 0 && colIdx >= _rangeStart && colIdx <= _rangeEnd) {
                // Click inside range: toggle ALL items in range together
                const clickedCol = _hmAllCols[colIdx];
                const shouldSelect = !_hmSelectedCols.includes(clickedCol);
                for (let i = _rangeStart; i <= _rangeEnd; i++) {
                    const col = _hmAllCols[i];
                    const idx = _hmSelectedCols.indexOf(col);
                    if (shouldSelect && idx < 0) _hmSelectedCols.push(col);
                    else if (!shouldSelect && idx >= 0) _hmSelectedCols.splice(idx, 1);
                }
                // Exit group mode after action
                _rangeStart = -1;
                _rangeEnd = -1;
            } else {
                // Click outside range: reset range, toggle single
                _rangeStart = -1;
                _rangeEnd = -1;
                const col = _hmAllCols[colIdx];
                const idx = _hmSelectedCols.indexOf(col);
                if (idx >= 0) _hmSelectedCols.splice(idx, 1);
                else _hmSelectedCols.push(col);
            }
            _lastClickIdx = colIdx;
            _syncVisuals();
        });

        // V key: invert selection
        document.addEventListener('keydown', e => {
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;
            if (e.key === 'v' || e.key === 'V') {
                const newSelected = _hmAllCols.filter(c => !_hmSelectedCols.includes(c));
                _hmSelectedCols.length = 0;
                _hmSelectedCols.push(...newSelected);
                _syncVisuals();
            }
        });
    }

    // Count
    const countEl = document.getElementById('hm-col-count');
    if (countEl) countEl.textContent = `${_hmSelectedCols.length} / ${_hmAllCols.length}`;
}

// ─── Canvas Rendering ───

// ─── Box Plot Renderer ───
function renderBoxPlot() {
    if (!_hmCanvas || !_hmCtx) return;
    const wrap = document.getElementById('hm-canvas-wrap');
    if (!wrap) return;

    const cols = _hmSelectedCols.slice().sort((a, b) => {
        const d = _hmAllCols.indexOf(a) - _hmAllCols.indexOf(b);
        return _hmColOrder === 'desc' ? -d : d;
    });
    const nCols = cols.length;
    const nRows = _hmRows.length;

    const dpr = window.devicePixelRatio || 1;
    const W = wrap.clientWidth || 800;
    const H = Math.max(400, window.innerHeight - 200);
    _hmCanvas.width = W * dpr;
    _hmCanvas.height = H * dpr;
    _hmCanvas.style.width = W + 'px';
    _hmCanvas.style.height = H + 'px';

    const ctx = _hmCtx;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, W, H);

    if (nCols === 0 || nRows === 0) {
        ctx.fillStyle = '#94a3b8';
        ctx.font = '14px Inter, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(nCols === 0 ? '請勾選要顯示的欄位' : '無資料', W / 2, H / 2);
        return;
    }

    const pad = { top: 46, bottom: 80, left: 60, right: 20 };
    const plotW = W - pad.left - pad.right;
    const plotH = H - pad.top - pad.bottom;
    const colW = plotW / nCols;
    const boxW = Math.min(colW * 0.5, 40);

    // Compute stats per column (respecting normalize mode)
    const normalizeMode = document.getElementById('hm-normalize')?.value || 'raw';
    const colIndices = cols.map(c => _hmHeaders.indexOf(c));
    const stats = [];

    for (let c = 0; c < nCols; c++) {
        const raw = [];
        for (let r = 0; r < nRows; r++) {
            const v = Number(_hmRows[r][colIndices[c]]);
            if (!isNaN(v) && isFinite(v)) raw.push(v);
        }
        if (raw.length === 0) { stats.push(null); continue; }

        // Apply normalization
        let vals;
        if (normalizeMode === 'zscore') {
            const mean = raw.reduce((a, b) => a + b, 0) / raw.length;
            const std = Math.sqrt(raw.reduce((a, b) => a + (b - mean) ** 2, 0) / raw.length) || 1;
            vals = raw.map(v => (v - mean) / std);
        } else {
            vals = raw.slice();
        }

        vals.sort((a, b) => a - b);
        const n = vals.length;
        const q1 = vals[Math.floor(n * 0.25)];
        const median = vals[Math.floor(n * 0.5)];
        const q3 = vals[Math.floor(n * 0.75)];
        const iqr = q3 - q1;
        const wLo = Math.max(vals[0], q1 - 1.5 * iqr);
        const wHi = Math.min(vals[n - 1], q3 + 1.5 * iqr);
        const outliers = vals.filter(v => v < wLo || v > wHi);
        stats.push({ q1, median, q3, iqr, wLo, wHi, min: vals[0], max: vals[n - 1], n, outliers, mean: vals.reduce((a, b) => a + b, 0) / n });
    }

    // Global Y range across all columns
    let gMin = Infinity, gMax = -Infinity;
    for (const s of stats) {
        if (!s) continue;
        const lo = s.outliers.length > 0 ? Math.min(s.min, ...s.outliers) : s.min;
        const hi = s.outliers.length > 0 ? Math.max(s.max, ...s.outliers) : s.max;
        if (lo < gMin) gMin = lo;
        if (hi > gMax) gMax = hi;
    }
    const gMargin = (gMax - gMin) * 0.05 || 1;
    gMin -= gMargin;
    gMax += gMargin;

    function yMap(val) {
        const t = (val - gMin) / (gMax - gMin);
        return pad.top + plotH * (1 - t);
    }

    // Y-axis grid lines and labels
    ctx.strokeStyle = '#f1f5f9';
    ctx.lineWidth = 1;
    const nTicks = 8;
    ctx.font = '12px Inter, sans-serif';
    ctx.fillStyle = '#94a3b8';
    ctx.textAlign = 'right';
    for (let i = 0; i <= nTicks; i++) {
        const val = gMin + (gMax - gMin) * (i / nTicks);
        const y = Math.round(pad.top + plotH * (1 - i / nTicks)) + 0.5;
        ctx.beginPath();
        ctx.moveTo(pad.left, y);
        ctx.lineTo(W - pad.right, y);
        ctx.stroke();
        const label = Math.abs(val) >= 1000 ? val.toFixed(0) : Math.abs(val) >= 1 ? val.toFixed(2) : val.toPrecision(3);
        ctx.fillText(label, pad.left - 6, Math.round(y + 4));
    }

    // Draw each box
    for (let c = 0; c < nCols; c++) {
        const s = stats[c];
        const cx = Math.round(pad.left + colW * c + colW / 2) + 0.5;

        // X-axis label
        ctx.save();
        ctx.font = '11px Inter, sans-serif';
        ctx.fillStyle = '#475569';
        ctx.textAlign = 'right';
        ctx.translate(Math.round(cx), Math.round(H - pad.bottom + 10));
        ctx.rotate(-Math.PI / 4);
        ctx.fillText(cols[c], 0, 0);
        ctx.restore();

        if (!s) continue;

        const yFn = v => yMap(v);
        const x1 = cx - boxW / 2;
        const x2 = cx + boxW / 2;

        // Whisker line (vertical)
        ctx.strokeStyle = '#64748b';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(cx, yFn(s.wLo));
        ctx.lineTo(cx, yFn(s.wHi));
        ctx.stroke();

        // Whisker caps
        const capW = boxW * 0.4;
        ctx.beginPath();
        ctx.moveTo(cx - capW, yFn(s.wLo));
        ctx.lineTo(cx + capW, yFn(s.wLo));
        ctx.moveTo(cx - capW, yFn(s.wHi));
        ctx.lineTo(cx + capW, yFn(s.wHi));
        ctx.stroke();

        // Box (Q1 to Q3)
        const yQ1 = yFn(s.q1);
        const yQ3 = yFn(s.q3);
        const boxTop = Math.min(yQ1, yQ3);
        const boxH = Math.abs(yQ1 - yQ3) || 1;
        ctx.fillStyle = 'rgba(59, 130, 246, 0.15)';
        ctx.fillRect(x1, boxTop, boxW, boxH);
        ctx.strokeStyle = '#3b82f6';
        ctx.lineWidth = 1.5;
        ctx.strokeRect(x1, boxTop, boxW, boxH);

        // Median line
        ctx.strokeStyle = '#ef4444';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(x1, yFn(s.median));
        ctx.lineTo(x2, yFn(s.median));
        ctx.stroke();

        // Mean dot
        ctx.fillStyle = '#22c55e';
        ctx.beginPath();
        ctx.arc(cx, yFn(s.mean), 3, 0, Math.PI * 2);
        ctx.fill();

        // Outliers
        ctx.fillStyle = 'rgba(239, 68, 68, 0.5)';
        for (const o of s.outliers) {
            ctx.beginPath();
            ctx.arc(cx, yFn(o), 2, 0, Math.PI * 2);
            ctx.fill();
        }

    }

    // Legend (above plot area)
    ctx.font = '12px Inter, sans-serif';
    ctx.textAlign = 'left';
    const lgX = pad.left;
    const lgY = 14;
    ctx.fillStyle = '#ef4444'; ctx.fillRect(lgX, lgY, 12, 2); ctx.fillStyle = '#475569'; ctx.fillText('中位數', lgX + 16, lgY + 4);
    ctx.fillStyle = '#22c55e'; ctx.beginPath(); ctx.arc(lgX + 80, lgY + 1, 3, 0, Math.PI * 2); ctx.fill(); ctx.fillStyle = '#475569'; ctx.fillText('平均', lgX + 86, lgY + 4);
    ctx.fillStyle = 'rgba(239, 68, 68, 0.5)'; ctx.beginPath(); ctx.arc(lgX + 130, lgY + 1, 2, 0, Math.PI * 2); ctx.fill(); ctx.fillStyle = '#475569'; ctx.fillText('離群值', lgX + 136, lgY + 4);

    // Store layout for tooltip
    _hmCanvas._bpLayout = { cols, stats, colW, padLeft: pad.left };
}

// ─── Copy / Download Chart ───
export async function copyCanvasToClipboard() {
    if (!_hmCanvas) return;
    const _toast = (msg) => {
        const t = document.createElement('div');
        t.style.cssText = 'position:fixed;bottom:28px;left:50%;transform:translateX(-50%);background:#1e293b;color:#fff;padding:10px 22px;border-radius:8px;font-size:13px;font-weight:600;z-index:99999;box-shadow:0 4px 16px rgba(0,0,0,0.2);pointer-events:none;white-space:nowrap;';
        t.textContent = msg;
        document.body.appendChild(t);
        setTimeout(() => { t.style.transition = 'opacity 0.5s'; t.style.opacity = '0'; setTimeout(() => t.remove(), 500); }, 1800);
    };

    // Try Clipboard API (requires HTTPS or localhost)
    if (navigator.clipboard && typeof ClipboardItem !== 'undefined') {
        try {
            const blob = await new Promise(resolve => _hmCanvas.toBlob(resolve, 'image/png'));
            await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
            _toast('✓ 圖表已複製到剪貼簿');
            return;
        } catch (_) { /* fall through to download */ }
    }

    // Fallback: download PNG
    const link = document.createElement('a');
    link.download = `chart_${new Date().toISOString().slice(0,19).replace(/[T:]/g,'-')}.png`;
    link.href = _hmCanvas.toDataURL('image/png');
    link.click();
    _toast('📥 已下載圖表 PNG');
}

// ─── Box Plot Tooltip ───
// (tooltip reuses heatmap tooltip infrastructure, box plot hover handled via mousemove)

function renderHeatmap() {
    if (!_hmCanvas || !_hmCtx) return;
    const wrap = document.getElementById('hm-canvas-wrap');
    if (!wrap) return;

    // Sort selected columns to match sidebar (top→bottom = _hmAllCols order)
    const cols = _hmSelectedCols.slice().sort((a, b) => {
        const d = _hmAllCols.indexOf(a) - _hmAllCols.indexOf(b);
        return _hmColOrder === 'desc' ? -d : d;
    });
    const nCols = cols.length;
    const nRows = _hmRows.length;

    // Auto-clear pins if columns or row height changed
    const rowHVal = document.getElementById('hm-row-height')?.value || 'auto';
    const layoutKey = cols.slice().sort().join('|') + '##' + rowHVal;
    if (layoutKey !== _lastDrawnColsKey) {
        unpinHeatmapTooltip();
        _lastDrawnColsKey = layoutKey;
    }

    // Size canvas — user controls row height, empty=auto-fit viewport
    const W = wrap.clientWidth || 800;
    const plotW = W - HM_PAD.left - HM_PAD.right - HM_LEGEND_W - 20;
    const rowHInputObj = document.getElementById('hm-row-height');
    const userRowH = rowHInputObj?.dataset.userModified ? parseFloat(rowHInputObj.value) : NaN;
    let cellH;
    if (isFinite(userRowH) && userRowH > 0) {
        cellH = userRowH;
    } else {
        // Auto: fit to viewport
        const viewH = window.innerHeight - 200;
        const availH = viewH - HM_PAD.top - HM_PAD.bottom;
        cellH = Math.max(0.5, availH / Math.max(nRows, 1));
        
        // Write it to value if user hasn't explicitly modified it
        const rowHInput = document.getElementById('hm-row-height');
        if (rowHInput && !rowHInput.dataset.userModified) {
            rowHInput.value = cellH.toFixed(2);
        }
    }
    const dpr = window.devicePixelRatio || 1;
    const plotH = Math.round(nRows * cellH);
    const H = HM_PAD.top + plotH + HM_PAD.bottom;
    _hmCanvas.width = W * dpr;
    _hmCanvas.height = H * dpr;
    _hmCanvas.style.width = W + 'px';
    _hmCanvas.style.height = H + 'px';

    const ctx = _hmCtx;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, W, H);

    if (nCols === 0 || nRows === 0) {
        ctx.fillStyle = '#94a3b8';
        ctx.font = '14px Inter, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(nCols === 0 ? '請勾選要顯示的欄位' : '無資料', W / 2, H / 2);
        return;
    }

    const cellW = plotW / nCols;

    // Normalization mode
    const normalizeMode = document.getElementById('hm-normalize')?.value || 'raw';

    // Compute per-column stats
    const colIndices = cols.map(c => _hmHeaders.indexOf(c));
    const mins = new Float64Array(nCols).fill(Infinity);
    const maxs = new Float64Array(nCols).fill(-Infinity);
    const means = new Float64Array(nCols).fill(0);
    const stds = new Float64Array(nCols).fill(0);
    const counts = new Float64Array(nCols).fill(0);

    // Pass 1: compute min, max, mean
    for (let r = 0; r < nRows; r++) {
        const row = _hmRows[r];
        for (let c = 0; c < nCols; c++) {
            const v = Number(row[colIndices[c]]);
            if (isNaN(v)) continue;
            if (v < mins[c]) mins[c] = v;
            if (v > maxs[c]) maxs[c] = v;
            means[c] += v;
            counts[c]++;
        }
    }
    for (let c = 0; c < nCols; c++) {
        means[c] = counts[c] > 0 ? means[c] / counts[c] : 0;
    }

    // Pass 2: compute std (only for z-score)
    if (normalizeMode === 'zscore') {
        for (let r = 0; r < nRows; r++) {
            const row = _hmRows[r];
            for (let c = 0; c < nCols; c++) {
                const v = Number(row[colIndices[c]]);
                if (isNaN(v)) continue;
                stds[c] += (v - means[c]) ** 2;
            }
        }
        for (let c = 0; c < nCols; c++) {
            stds[c] = counts[c] > 1 ? Math.sqrt(stds[c] / counts[c]) : 1;
            if (stds[c] === 0) stds[c] = 1; // Prevent passing 0 to division, generating NaN
        }
        // For z-score, set min/max to ±3σ range for consistent coloring
        mins.fill(-3);
        maxs.fill(3);
    }

    // For raw mode, use global min/max so that the color scale matches the single global legend.
    if (normalizeMode !== 'zscore') {
        let gMin = Infinity, gMax = -Infinity;
        for (let c = 0; c < nCols; c++) {
            if (mins[c] < gMin) gMin = mins[c];
            if (maxs[c] > gMax) gMax = maxs[c];
        }
        mins.fill(gMin);
        maxs.fill(gMax);
    }

    // Override with user-specified min/max (applies to all columns)
    const minInputObj = document.getElementById('hm-color-min');
    const maxInputObj = document.getElementById('hm-color-max');
    const userMin = minInputObj?.dataset.userModified ? parseFloat(minInputObj.value) : NaN;
    const userMax = maxInputObj?.dataset.userModified ? parseFloat(maxInputObj.value) : NaN;
    if (isFinite(userMin)) mins.fill(userMin);
    if (isFinite(userMax)) maxs.fill(userMax);

    // Fast rendering via ImageData (scaled for HiDPI)
    const imgW = Math.ceil(plotW * dpr);
    const imgH = Math.ceil(plotH * dpr);
    const imgData = ctx.createImageData(imgW, imgH);
    const pixels = imgData.data;

    for (let r = 0; r < nRows; r++) {
        const dataR = _rowIdx(r, nRows);
        const row = _hmRows[dataR];
        const pyStart = Math.floor(r * cellH * dpr);
        const pyEnd = Math.min(Math.ceil((r + 1) * cellH * dpr), imgH);
        for (let c = 0; c < nCols; c++) {
            const rawV = Number(row[colIndices[c]]);
            let red, green, blue;
            if (isNaN(rawV)) {
                red = 241; green = 245; blue = 249;
            } else {
                // Apply normalization
                const v = normalizeMode === 'zscore' ? (rawV - means[c]) / stds[c] : rawV;
                const range = maxs[c] - mins[c];
                const t = range > 0 ? Math.max(0, Math.min(1, (v - mins[c]) / range)) : 0.5;
                if (_hmColorScheme === 'viridis') {
                    red = Math.round(68 + (253 - 68) * t);
                    green = Math.round(1 + 230 * Math.sin(t * Math.PI * 0.9));
                    blue = Math.round(84 + (37 - 84) * t);
                } else {
                    if (t <= 0.5) {
                        const s = t * 2;
                        red = Math.round(59 + 196 * s);
                        green = Math.round(130 + 125 * s);
                        blue = Math.round(246 + 9 * s);
                    } else {
                        const s = (t - 0.5) * 2;
                        red = 255;
                        green = Math.round(255 - 187 * s);
                        blue = Math.round(255 - 187 * s);
                    }
                }
            }
            const pxStart = Math.floor(c * cellW * dpr);
            const pxEnd = Math.min(Math.ceil((c + 1) * cellW * dpr), imgW);
            for (let dy = pyStart; dy < pyEnd; dy++) {
                const rowOff = dy * imgW;
                for (let px = pxStart; px < pxEnd; px++) {
                    const idx = (rowOff + px) * 4;
                    pixels[idx] = red;
                    pixels[idx + 1] = green;
                    pixels[idx + 2] = blue;
                    pixels[idx + 3] = 255;
                }
            }
        }
    }
    ctx.putImageData(imgData, HM_PAD.left * dpr, HM_PAD.top * dpr);

    // Grid lines between columns
    ctx.strokeStyle = 'rgba(255,255,255,0.3)';
    ctx.lineWidth = 0.5;
    for (let c = 1; c < nCols; c++) {
        const x = HM_PAD.left + c * cellW;
        ctx.beginPath();
        ctx.moveTo(x, HM_PAD.top);
        ctx.lineTo(x, HM_PAD.top + plotH);
        ctx.stroke();
    }

    // X axis labels (column names, rotated, show every Nth)
    ctx.fillStyle = '#334155';
    ctx.font = '11px Inter, sans-serif';
    ctx.textAlign = 'left';
    const maxXLabels = Math.max(1, Math.floor(plotW / 80));
    const xStep = Math.max(1, Math.ceil(nCols / maxXLabels));
    ctx.save();
    for (let c = 0; c < nCols; c += xStep) {
        const x = HM_PAD.left + (c + 0.5) * cellW;
        const y = HM_PAD.top + plotH + 6;
        ctx.save();
        ctx.translate(Math.round(x), Math.round(y));
        ctx.rotate(Math.PI / 4);
        const label = cols[c].length > 8 ? cols[c].slice(0, 7) + '…' : cols[c];
        ctx.fillText(label, 0, 0);
        ctx.restore();
    }
    ctx.restore();

    // Y axis labels (time ticks)
    const xColIdx = _hmHeaders.indexOf(_hmXCol);
    ctx.fillStyle = '#64748b';
    ctx.font = '11px Inter, sans-serif';
    ctx.textAlign = 'right';
    const yTickCount = Math.min(nRows, 20);
    for (let i = 0; i < yTickCount; i++) {
        const rowIdx = Math.round(i * (nRows - 1) / Math.max(yTickCount - 1, 1));
        if (rowIdx >= nRows) continue;
        const dataR = _rowIdx(rowIdx, nRows);
        const label = String(_hmRows[dataR][xColIdx] || rowIdx);
        const short = label.length > 20 ? label.slice(0, 18) + '…' : label;
        const y = Math.round(HM_PAD.top + rowIdx * cellH + cellH / 2) + 0.5;
        ctx.fillText(short, HM_PAD.left - 6, y + 3);
    }

    // Color legend
    const legX = W - HM_PAD.right - HM_LEGEND_W;
    const legY = HM_PAD.top;
    const legH = plotH;
    for (let i = 0; i < legH; i++) {
        const t = 1 - i / legH;
        ctx.fillStyle = getColor(t);
        ctx.fillRect(legX, legY + i, HM_LEGEND_W, 1);
    }
    ctx.strokeStyle = '#cbd5e1';
    ctx.lineWidth = 1;
    ctx.strokeRect(legX, legY, HM_LEGEND_W, legH);

    // Show actual min/max values (global across all columns)
    let globalMin = Infinity, globalMax = -Infinity;
    for (let c = 0; c < nCols; c++) {
        if (mins[c] < globalMin) globalMin = mins[c];
        if (maxs[c] > globalMax) globalMax = maxs[c];
    }
    
    // Write back to value if user hasn't modified it
    const minInput = document.getElementById('hm-color-min');
    const maxInput = document.getElementById('hm-color-max');
    if (minInput && !minInput.dataset.userModified && isFinite(globalMin)) {
        minInput.value = globalMin.toFixed(2);
    }
    if (maxInput && !maxInput.dataset.userModified && isFinite(globalMax)) {
        maxInput.value = globalMax.toFixed(2);
    }

    ctx.fillStyle = '#64748b';
    ctx.font = '11px Inter, sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText(isFinite(globalMax) ? globalMax.toFixed(2) : '—', legX + HM_LEGEND_W + 4, legY + 8);
    const globalMid = (globalMin + globalMax) / 2;
    ctx.fillText(isFinite(globalMid) ? globalMid.toFixed(2) : '—', legX + HM_LEGEND_W + 4, legY + legH / 2 + 3);
    ctx.fillText(isFinite(globalMin) ? globalMin.toFixed(2) : '—', legX + HM_LEGEND_W + 4, legY + legH);

    // Store layout for tooltip
    _hmCanvas._hmLayout = {
        plotW, plotH, cellW, cellH, nCols, nRows,
        colIndices, cols, xColIdx, mins, maxs,
        normalizeMode, means, stds
    };
}

// ─── Tooltip ───

let _hmPinned = false; // is tooltip pinned?

function _buildTooltipContent(L, col, row) {
    const dataR = _rowIdx(row, L.nRows);
    const colName = L.cols[col];
    const timeVal = _hmRows[dataR] ? String(_hmRows[dataR][L.xColIdx] || '') : '';
    const rawV = Number(_hmRows[dataR][L.colIndices[col]]);
    const valStr = isNaN(rawV) ? 'NaN' : rawV.toFixed(4);

    let lines = [];
    lines.push(`<b>${colName}</b>`);
    lines.push(`<span style="color:#94a3b8">${_hmXCol}:</span> ${timeVal}`);
    lines.push(`<span style="color:#94a3b8">值:</span> ${valStr}`);
    if (L.normalizeMode === 'zscore' && !isNaN(rawV)) {
        const z = (rawV - L.means[col]) / L.stds[col];
        lines.push(`<span style="color:#94a3b8">Z-score:</span> ${z.toFixed(3)}`);
    }
    return lines;
}

function _getHeatmapCell(e) {
    if (!_hmCanvas?._hmLayout) return null;
    const L = _hmCanvas._hmLayout;
    const rect = _hmCanvas.getBoundingClientRect();
    // Use logical (CSS) coordinates — layout values are in CSS space
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const col = Math.floor((mx - HM_PAD.left) / L.cellW);
    const row = Math.floor((my - HM_PAD.top) / L.cellH);
    if (col < 0 || col >= L.nCols || row < 0 || row >= L.nRows) return null;
    return { col, row, L, rect };
}

function setupHeatmapTooltip() {
    if (!_hmCanvas) return;
    if (_hmCanvas._hmTooltipBound) return;
    _hmCanvas._hmTooltipBound = true;
    // Create crosshair guide elements
    const wrap = document.getElementById('hm-canvas-wrap');
    const crossH = document.createElement('div');
    crossH.className = 'hm-crosshair';
    crossH.style.cssText = 'position:absolute;left:0;right:0;height:0;border-top:2px dashed rgba(100,116,139,0.7);pointer-events:none;z-index:55;display:none;';
    wrap?.appendChild(crossH);
    const crossV = document.createElement('div');
    crossV.className = 'hm-crosshair';
    crossV.style.cssText = 'position:absolute;top:0;bottom:0;width:0;border-left:2px dashed rgba(100,116,139,0.7);pointer-events:none;z-index:55;display:none;';
    wrap?.appendChild(crossV);

    // Hover tooltip + crosshairs
    _hmCanvas.addEventListener('mousemove', e => {
        const wrapRect = wrap?.getBoundingClientRect();
        const mx = e.clientX - (wrapRect?.left || 0);
        const my = e.clientY - (wrapRect?.top || 0);

        // Always show crosshairs
        crossH.style.display = 'block';
        crossH.style.top = my + 'px';
        crossV.style.display = 'block';
        crossV.style.left = mx + 'px';

        if (!_hmTipEl) return;

        // Box plot mode tooltip
        if (_hmChartMode === 'boxplot' && _hmCanvas._bpLayout) {
            const bpL = _hmCanvas._bpLayout;
            const rect = _hmCanvas.getBoundingClientRect();
            const canvasX = e.clientX - rect.left;
            const col = Math.floor((canvasX - bpL.padLeft) / bpL.colW);
            if (col >= 0 && col < bpL.stats.length && bpL.stats[col]) {
                const s = bpL.stats[col];
                const lines = [
                    `<b style="color:#93c5fd;">${bpL.cols[col]}</b>  (n=${s.n})`,
                    `Max: ${s.max.toFixed(4)}`,
                    `Q3: ${s.q3.toFixed(4)}`,
                    `<span style="color:#ef4444;">中位數: ${s.median.toFixed(4)}</span>`,
                    `Q1: ${s.q1.toFixed(4)}`,
                    `Min: ${s.min.toFixed(4)}`,
                    `<span style="color:#86efac;">平均: ${s.mean.toFixed(4)}</span>`,
                    `IQR: ${s.iqr.toFixed(4)}`,
                    `離群值: ${s.outliers.length} 個`,
                ];
                _hmTipEl.innerHTML = lines.join('<br>');
                _hmTipEl.style.display = 'block';
                _hmTipEl.style.left = (e.clientX - rect.left + 14) + 'px';
                _hmTipEl.style.top = (e.clientY - rect.top - 10) + 'px';
            } else {
                _hmTipEl.style.display = 'none';
            }
            return;
        }

        // Heatmap mode tooltip
        const hit = _getHeatmapCell(e);
        if (!hit) { _hmTipEl.style.display = 'none'; return; }

        const lines = _buildTooltipContent(hit.L, hit.col, hit.row);
        _hmTipEl.innerHTML = lines.join('<br>');
        _hmTipEl.style.display = 'block';
        _hmTipEl.style.left = (e.clientX - hit.rect.left + 14) + 'px';
        _hmTipEl.style.top = (e.clientY - hit.rect.top - 10) + 'px';
    });

    _hmCanvas.addEventListener('mouseleave', () => {
        if (_hmTipEl) _hmTipEl.style.display = 'none';
        crossH.style.display = 'none';
        crossV.style.display = 'none';
    });

    // ESC key: close settings panel or pop last pin
    if (!window._hmEscBound) {
        window._hmEscBound = true;
        document.addEventListener('keydown', e => {
            if (e.key === 'Escape') {
                const panel = document.getElementById('hm-settings-panel');
                if (panel && panel.style.display !== 'none') {
                    panel.style.display = 'none';
                } else if (_hmPinned) {
                    const wrap = document.getElementById('hm-canvas-wrap');
                    if (wrap) {
                        const markers = wrap.querySelectorAll('.hm-pin-marker');
                        if (markers.length > 0) {
                            const lastMarker = markers[markers.length - 1];
                            _removePin(lastMarker.dataset.pinId);
                        }
                    }
                }
            }
        });
    }

    // Click to pin (supports multiple pins) — skip in brush mode
    _hmCanvas.addEventListener('click', e => {
        if (_brushMode) return;
        const hit = _getHeatmapCell(e);
        if (!hit) return;

        _hmPinned = true;
        // Hide the floating hover tooltip
        if (_hmTipEl) _hmTipEl.style.display = 'none';
        const wrap = document.getElementById('hm-canvas-wrap');
        if (!wrap) return;
        const wrapRect = wrap.getBoundingClientRect();
        const dotX = e.clientX - wrapRect.left;
        const dotY = e.clientY - wrapRect.top;

        // Pin color from settings
        const pinColor = document.getElementById('hm-pin-color')?.value || '#f59e0b';

        // Unique ID for this pin group
        const pinId = 'hm-pin-' + Date.now();

        // Create dot
        const dot = document.createElement('div');
        dot.className = 'hm-pin-marker';
        dot.dataset.pinId = pinId;
        dot.style.cssText = `position:absolute;left:${dotX - 4}px;top:${dotY - 4}px;width:8px;height:8px;border-radius:50%;background:${pinColor};border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,0.4);z-index:60;pointer-events:none;`;
        wrap.appendChild(dot);

        // Create tooltip
        const tip = document.createElement('div');
        tip.className = 'hm-pin-tooltip';
        tip.dataset.pinId = pinId;
        const tipX = dotX + 20;
        const tipY = dotY - 10;
        const tipBg = document.getElementById('hm-tip-bg-color')?.value || '#0f172a';
        // Auto text color: light bg → black text, dark bg → white text
        const r = parseInt(tipBg.slice(1,3),16), g = parseInt(tipBg.slice(3,5),16), b = parseInt(tipBg.slice(5,7),16);
        const lum = (0.299*r + 0.587*g + 0.114*b) / 255;
        const tipTextColor = lum > 0.5 ? '#1e293b' : '#fff';
        tip.style.cssText = `position:absolute;left:${tipX}px;top:${tipY}px;background:${tipBg};color:${tipTextColor};padding:6px 10px;border-radius:6px;font-size:11px;line-height:1.5;white-space:nowrap;z-index:100;box-shadow:0 2px 8px rgba(0,0,0,.25);cursor:move;user-select:none;`;

        const lines = _buildTooltipContent(hit.L, hit.col, hit.row);
        lines.unshift(`<span class="hm-pin-close" style="float:right;cursor:pointer;color:#94a3b8;font-size:14px;margin:-2px -4px 0 8px;">✕</span>`);
        tip.innerHTML = lines.join('<br>');
        wrap.appendChild(tip);

        // Create SVG leader line
        let svg = wrap.querySelector('.hm-pin-svg');
        if (!svg) {
            svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
            svg.classList.add('hm-pin-svg');
            svg.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:59;overflow:visible;';
            wrap.appendChild(svg);
        }
        const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        line.dataset.pinId = pinId;
        line.setAttribute('x1', dotX);
        line.setAttribute('y1', dotY);
        line.setAttribute('x2', tipX);
        line.setAttribute('y2', tipY + 10);
        line.setAttribute('stroke', pinColor);
        line.setAttribute('stroke-width', '1.5');
        line.setAttribute('stroke-dasharray', '4,3');
        svg.appendChild(line);

        // Close button
        tip.querySelector('.hm-pin-close').addEventListener('click', () => {
            _removePin(pinId);
        });

        // Drag to move tooltip
        let dragging = false, dx = 0, dy = 0;
        tip.addEventListener('mousedown', ev => {
            if (ev.target.classList.contains('hm-pin-close')) return;
            dragging = true;
            const tipRect = tip.getBoundingClientRect();
            dx = ev.clientX - tipRect.left;
            dy = ev.clientY - tipRect.top;
            ev.preventDefault();
        });
        document.addEventListener('mousemove', ev => {
            if (!dragging) return;
            const wr = wrap.getBoundingClientRect();
            const newX = ev.clientX - wr.left - dx;
            const newY = ev.clientY - wr.top - dy;
            tip.style.left = newX + 'px';
            tip.style.top = newY + 'px';
            // Update leader line
            line.setAttribute('x2', newX);
            line.setAttribute('y2', newY + 10);
        });
        document.addEventListener('mouseup', () => { dragging = false; });
    });

    // Initialize brush selection mode handlers
    setupBrushMode();
}

function _removePin(pinId) {
    const wrap = document.getElementById('hm-canvas-wrap');
    if (!wrap) return;
    wrap.querySelectorAll(`[data-pin-id="${pinId}"]`).forEach(el => el.remove());
    // Check if any pins left
    if (!wrap.querySelector('.hm-pin-marker')) {
        _hmPinned = false;
        // Remove SVG if empty
        const svg = wrap.querySelector('.hm-pin-svg');
        if (svg && !svg.firstChild) svg.remove();
    }
}

export function unpinHeatmapTooltip() {
    _hmPinned = false;
    const wrap = document.getElementById('hm-canvas-wrap');
    if (!wrap) return;
    wrap.querySelectorAll('.hm-pin-marker, .hm-pin-tooltip, .hm-pin-svg').forEach(el => el.remove());
}

// ─── Brush Selection Mode ─────────────────────────────────────────────────────

export function setHeatmapMode(mode) {
    _brushMode = (mode === 'brush');
    // Update toggle buttons in settings panel
    const lblBtn   = document.getElementById('hm-mode-label');
    const brushBtn = document.getElementById('hm-mode-brush');
    if (lblBtn) {
        lblBtn.style.background  = !_brushMode ? '#fff'     : '#e2e8f0';
        lblBtn.style.color       = !_brushMode ? '#3b82f6'  : '#64748b';
        lblBtn.style.boxShadow   = !_brushMode ? '0 1px 2px rgba(0,0,0,0.08)' : 'none';
    }
    if (brushBtn) {
        brushBtn.style.background = _brushMode ? '#fff'     : '#e2e8f0';
        brushBtn.style.color      = _brushMode ? '#3b82f6'  : '#64748b';
        brushBtn.style.boxShadow  = _brushMode ? '0 1px 2px rgba(0,0,0,0.08)' : 'none';
    }
    if (_hmCanvas) _hmCanvas.style.cursor = _brushMode ? 'crosshair' : '';
    if (!_brushMode) _clearBrushOverlay();
}

export function toggleBrushMode() {
    setHeatmapMode(_brushMode ? 'label' : 'brush');
}

function _clearBrushOverlay() {
    if (_brushOverlay) { _brushOverlay.remove(); _brushOverlay = null; }
    _brushDragging = false;
    _brushStartClient = null;
}

function setupBrushMode() {
    if (_brushModeSetup || !_hmCanvas) return;
    _brushModeSetup = true;

    _hmCanvas.addEventListener('mousedown', e => {
        if (!_brushMode) return;
        e.preventDefault();
        _brushDragging = true;
        _brushStartClient = { x: e.clientX, y: e.clientY };
        const wrap = document.getElementById('hm-canvas-wrap');
        if (!wrap) return;
        if (!_brushOverlay) {
            _brushOverlay = document.createElement('div');
            _brushOverlay.style.cssText = 'position:absolute;top:0;bottom:0;border:2px solid #3b82f6;background:rgba(59,130,246,0.1);pointer-events:none;z-index:200;box-sizing:border-box;';
            wrap.appendChild(_brushOverlay);
        }
        const wrapRect = wrap.getBoundingClientRect();
        _brushOverlay.style.left  = (e.clientX - wrapRect.left) + 'px';
        _brushOverlay.style.width = '0px';
    });

    document.addEventListener('mousemove', e => {
        if (!_brushMode || !_brushDragging || !_brushStartClient) return;
        const wrap = document.getElementById('hm-canvas-wrap');
        if (!wrap || !_brushOverlay) return;
        const wrapRect = wrap.getBoundingClientRect();
        _brushOverlay.style.left  = Math.min(_brushStartClient.x, e.clientX) - wrapRect.left + 'px';
        _brushOverlay.style.width = Math.abs(e.clientX - _brushStartClient.x) + 'px';
    });

    document.addEventListener('mouseup', e => {
        if (!_brushMode || !_brushDragging || !_brushStartClient) return;
        _brushDragging = false;

        const L = _hmCanvas?._hmLayout;
        if (!L) { _clearBrushOverlay(); return; }

        const rect   = _hmCanvas.getBoundingClientRect();

        const px1 = Math.min(_brushStartClient.x, e.clientX);
        const px2 = Math.max(_brushStartClient.x, e.clientX);

        if (px2 - px1 < 5) { _clearBrushOverlay(); return; }

        const canvasX1 = px1 - rect.left;
        const canvasX2 = px2 - rect.left;
        const colStart = Math.max(0,           Math.floor((canvasX1 - HM_PAD.left) / L.cellW));
        const colEnd   = Math.min(L.nCols - 1, Math.floor((canvasX2 - HM_PAD.left) / L.cellW));

        if (colStart > colEnd) { _clearBrushOverlay(); return; }

        const selectedCols = L.cols.slice(colStart, colEnd + 1);
        _showBrushPreviewDialog(selectedCols);
    });
}

// ── Stat helpers ──────────────────────────────────────────────────────────────

function _computeStat(rowData, colNames, mode) {
    const nums = colNames
        .map(col => Number(rowData[_hmHeaders.indexOf(col)]))
        .filter(v => !isNaN(v));
    if (nums.length === 0) return null;
    switch (mode) {
        case 'mean':  return nums.reduce((a, b) => a + b, 0) / nums.length;
        case 'std': {
            const m = nums.reduce((a, b) => a + b, 0) / nums.length;
            return Math.sqrt(nums.reduce((a, b) => a + (b - m) ** 2, 0) / nums.length);
        }
        case 'min':   return Math.min(...nums);
        case 'max':   return Math.max(...nums);
        case 'sum':   return nums.reduce((a, b) => a + b, 0);
        case 'range': return Math.max(...nums) - Math.min(...nums);
        default:      return null;
    }
}

// ── Preview Dialog ────────────────────────────────────────────────────────────

function _showBrushPreviewDialog(initialCols) {
    const autoName    = 'Feature_' + Date.now().toString().slice(-4);
    const defaultMode = document.getElementById('hm-brush-stat')?.value || 'mean';
    const xColIdx     = _hmHeaders.indexOf(_hmXCol);
    const rowStart    = 0;
    const rowEnd      = _hmRows.length - 1;

    // Build dialog
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.35);z-index:9990;display:flex;align-items:center;justify-content:center;';

    const dlg = document.createElement('div');
    dlg.style.cssText = 'background:#fff;border-radius:14px;box-shadow:0 20px 60px rgba(0,0,0,0.25);width:660px;max-width:96vw;max-height:90vh;display:flex;flex-direction:column;overflow:hidden;font-family:inherit;';

    // Column chips
    const chipsHtml = initialCols.map(col => {
        const label = col.length > 22 ? col.slice(0, 22) + '…' : col;
        const safe  = col.replace(/&/g,'&amp;').replace(/"/g,'&quot;');
        return `<span class="brush-col-chip active" data-col="${safe}"
            style="display:inline-flex;align-items:center;padding:3px 8px;background:#eff6ff;color:#3b82f6;border:1px solid #bfdbfe;border-radius:20px;font-size:11px;cursor:pointer;margin:2px;user-select:none;"
            onclick="this.classList.toggle('active');const a=this.classList.contains('active');this.style.background=a?'#eff6ff':'#f8fafc';this.style.color=a?'#3b82f6':'#94a3b8';this.style.borderColor=a?'#bfdbfe':'#e2e8f0';window._hmBrushRebuild()"
            title="${safe}">${label}</span>`;
    }).join('');

    dlg.innerHTML = `
        <div style="padding:18px 20px 14px;border-bottom:1px solid #e2e8f0;display:flex;align-items:center;justify-content:space-between;flex-shrink:0;">
            <div style="font-size:15px;font-weight:700;color:#1e293b;">⬚ 框選特徵計算</div>
            <span id="_hm_br_close" style="cursor:pointer;color:#94a3b8;font-size:18px;line-height:1;">✕</span>
        </div>
        <div style="padding:16px 20px;overflow-y:auto;flex:1;min-height:0;">
            <div style="font-size:11px;color:#64748b;margin-bottom:10px;">
                欄位 <b>${initialCols.length}</b> 個，共 <b>${_hmRows.length}</b> 筆樣本
            </div>

            <div style="font-size:11px;font-weight:600;color:#475569;margin-bottom:5px;">
                選取欄位 <span style="color:#94a3b8;font-weight:400">（點擊切換）</span>
            </div>
            <div style="max-height:90px;overflow-y:auto;padding:6px;background:#f8fafc;border-radius:8px;border:1px solid #e2e8f0;margin-bottom:12px;">
                ${chipsHtml}
            </div>

            <div style="margin-bottom:12px;">
                <div style="font-size:11px;font-weight:600;color:#475569;margin-bottom:4px;">計算方式</div>
                <select id="_hm_br_mode" onchange="window._hmBrushRebuild()"
                    style="width:100%;padding:6px 8px;border:1px solid #cbd5e1;border-radius:6px;font-size:12px;">
                    <option value="mean"  ${defaultMode==='mean' ?'selected':''}>Mean（平均值）</option>
                    <option value="std"   ${defaultMode==='std'  ?'selected':''}>Std（標準差）</option>
                    <option value="min"   ${defaultMode==='min'  ?'selected':''}>Min（最小值）</option>
                    <option value="max"   ${defaultMode==='max'  ?'selected':''}>Max（最大值）</option>
                    <option value="sum"   ${defaultMode==='sum'  ?'selected':''}>Sum（總和）</option>
                    <option value="range" ${defaultMode==='range'?'selected':''}>Range（全距）</option>
                </select>
            </div>

            <div style="margin-bottom:12px;">
                <div style="font-size:11px;font-weight:600;color:#475569;margin-bottom:4px;">欄位名稱</div>
                <input id="_hm_br_name" type="text" value="${autoName}"
                    style="width:100%;box-sizing:border-box;padding:7px 10px;border:1px solid #cbd5e1;border-radius:6px;font-size:13px;outline:none;"
                    onfocus="this.select()">
            </div>

            <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:10px 10px 6px;">
                <div id="_hm_br_preview_label" style="font-size:11px;color:#64748b;margin-bottom:6px;"></div>
                <div style="position:relative;height:200px;">
                    <canvas id="_hm_br_chart"></canvas>
                </div>
            </div>
        </div>
        <div style="padding:14px 20px;border-top:1px solid #e2e8f0;display:flex;justify-content:flex-end;gap:10px;flex-shrink:0;">
            <button id="_hm_br_cancel" style="padding:8px 18px;border:1px solid #e2e8f0;background:#fff;color:#475569;border-radius:8px;cursor:pointer;font-size:13px;">取消</button>
            <button id="_hm_br_ok" style="padding:8px 22px;background:#3b82f6;color:#fff;border:none;border-radius:8px;cursor:pointer;font-size:13px;font-weight:600;">建立欄位</button>
        </div>`;

    overlay.appendChild(dlg);
    document.body.appendChild(overlay);

    // Rebuild preview chart
    let _dlgChart = null;
    const TREND_COLORS = ['#3b82f6','#ef4444','#22c55e','#f59e0b','#a855f7','#06b6d4','#f97316','#84cc16','#ec4899','#14b8a6'];

    window._hmBrushRebuild = () => {
        const mode       = dlg.querySelector('#_hm_br_mode').value;
        const activeCols = Array.from(dlg.querySelectorAll('.brush-col-chip.active')).map(el => el.dataset.col);
        const labelEl    = dlg.querySelector('#_hm_br_preview_label');
        const canvas     = dlg.querySelector('#_hm_br_chart');
        if (!canvas) return;

        if (_dlgChart) { _dlgChart.destroy(); _dlgChart = null; }

        if (activeCols.length === 0) {
            if (labelEl) labelEl.textContent = '請至少選取一個欄位';
            return;
        }

        if (labelEl) labelEl.textContent = `趨勢預覽 — ${_hmRows.length} 筆，${activeCols.length} 個欄位 → ${mode.toUpperCase()}`;

        // One value per row: stat across selected columns
        const labels = _hmRows.map((_, i) => i + 1);
        const data   = _hmRows.map(r => _computeStat(r, activeCols, mode));

        _dlgChart = new Chart(canvas.getContext('2d'), {
            type: 'line',
            data: {
                labels,
                datasets: [{
                    label: mode.toUpperCase(),
                    data,
                    borderColor: '#3b82f6',
                    backgroundColor: 'rgba(59,130,246,0.08)',
                    borderWidth: 1.5,
                    pointRadius: 0,
                    tension: 0.2,
                    spanGaps: true,
                    fill: true
                }]
            },
            options: {
                responsive: true, maintainAspectRatio: false, animation: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { ticks: { maxTicksLimit: 10, font: { size: 10 }, maxRotation: 0 }, grid: { color: 'rgba(0,0,0,0.04)' } },
                    y: { ticks: { font: { size: 10 } }, grid: { color: 'rgba(0,0,0,0.04)' } }
                }
            }
        });
    };

    window._hmBrushRebuild();

    const inp = dlg.querySelector('#_hm_br_name');
    inp.focus(); inp.select();

    const close = () => {
        if (_dlgChart) { _dlgChart.destroy(); _dlgChart = null; }
        overlay.remove();
        _clearBrushOverlay();
        delete window._hmBrushRebuild;
    };

    const confirm = () => {
        const name       = inp.value.trim() || autoName;
        const mode       = dlg.querySelector('#_hm_br_mode').value;
        const activeCols = Array.from(dlg.querySelectorAll('.brush-col-chip.active')).map(el => el.dataset.col);
        if (activeCols.length === 0) { alert('請至少選取一個欄位'); return; }
        _addBrushColumn(activeCols, mode, name);
        // 不關閉視窗，更新欄位名稱為下一個自動名稱
        inp.value = 'Feature_' + Date.now().toString().slice(-4);
        inp.select();
        // 在按鈕旁顯示成功提示
        const okBtn = dlg.querySelector('#_hm_br_ok');
        const orig = okBtn.textContent;
        okBtn.textContent = '✓ 已建立';
        okBtn.style.background = '#22c55e';
        setTimeout(() => { okBtn.textContent = orig; okBtn.style.background = '#3b82f6'; }, 1500);
    };

    dlg.querySelector('#_hm_br_close').addEventListener('click', close);
    dlg.querySelector('#_hm_br_cancel').addEventListener('click', close);
    dlg.querySelector('#_hm_br_ok').addEventListener('click', confirm);
    // Do NOT close on overlay click — brush mouseup outside window triggers spurious clicks
    const _escHandler = ev => { if (ev.key === 'Escape') { close(); document.removeEventListener('keydown', _escHandler); } };
    document.addEventListener('keydown', _escHandler);
}

function _addBrushColumn(activeCols, mode, colName) {
    _hmHeaders.push(colName);
    const newIdx = _hmHeaders.length - 1;
    for (let i = 0; i < _hmRows.length; i++) {
        const v = _computeStat(_hmRows[i], activeCols, mode);
        _hmRows[i].push(v !== null ? String(+v.toFixed(6)) : '');
    }

    // Update heatmap column list
    _hmAllCols.push(colName);
    _hmSelectedCols.push(colName);
    renderColumnSelector();

    if (typeof window.addVisibleColumn    === 'function') window.addVisibleColumn(newIdx);
    if (typeof window.refreshTableDisplay === 'function') window.refreshTableDisplay();

    const toast = document.createElement('div');
    toast.style.cssText = 'position:fixed;bottom:28px;left:50%;transform:translateX(-50%);background:#1e293b;color:#fff;padding:10px 22px;border-radius:8px;font-size:13px;font-weight:600;z-index:99999;box-shadow:0 4px 16px rgba(0,0,0,0.2);pointer-events:none;white-space:nowrap;';
    toast.textContent = `✓ 欄位「${colName}」已建立（${mode.toUpperCase()}，${activeCols.length} 個特徵，${_hmRows.length} 筆）`;
    document.body.appendChild(toast);
    setTimeout(() => { toast.style.transition = 'opacity 0.5s'; toast.style.opacity = '0'; setTimeout(() => toast.remove(), 500); }, 2800);
}
