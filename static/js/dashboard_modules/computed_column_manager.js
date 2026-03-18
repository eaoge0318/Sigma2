/**
 * computed_column_manager.js
 * Manages computed/calculated columns for the data analysis table.
 * Supports arithmetic operations, column references, and aggregate functions.
 */

import { tableHeaders, originalTableData, refreshTableDisplay, addVisibleColumn } from './analysis_manager.js';

// Track computed columns for UI
let _computedCols = []; // [{name, formula}]

// ─── Public API ───

export function showAddColumnModal() {
    let modal = document.getElementById('computed-col-modal');
    if (!modal) {
        modal = _createModal();
        document.body.appendChild(modal);
    }
    // Reset form
    document.getElementById('cc-col-name').value = '';
    document.getElementById('cc-formula').value = '';
    document.getElementById('cc-error').textContent = '';
    document.getElementById('cc-preview').innerHTML = '';
    _renderColPicker();
    modal.style.display = 'flex';
}

export function hideAddColumnModal() {
    const modal = document.getElementById('computed-col-modal');
    if (modal) modal.style.display = 'none';
}

export function applyComputedColumn() {
    const nameEl = document.getElementById('cc-col-name');
    const formulaEl = document.getElementById('cc-formula');
    const errEl = document.getElementById('cc-error');
    const name = nameEl.value.trim();
    const formula = formulaEl.value.trim();

    if (!name) { errEl.textContent = '請輸入欄位名稱'; return; }
    if (!formula) { errEl.textContent = '請輸入公式'; return; }
    if (tableHeaders.includes(name)) { errEl.textContent = `欄位 "${name}" 已存在`; return; }

    try {
        const values = _computeFormula(formula, tableHeaders, originalTableData);
        // Add to data
        tableHeaders.push(name);
        for (let i = 0; i < originalTableData.length; i++) {
            originalTableData[i].push(values[i]);
        }
        _computedCols.push({ name, formula });
        addVisibleColumn(tableHeaders.length - 1);
        hideAddColumnModal();
        refreshTableDisplay();
    } catch (e) {
        errEl.textContent = '公式錯誤: ' + e.message;
    }
}

export function previewComputedColumn() {
    const formulaEl = document.getElementById('cc-formula');
    const previewEl = document.getElementById('cc-preview');
    const errEl = document.getElementById('cc-error');
    const formula = formulaEl.value.trim();

    if (!formula) { previewEl.innerHTML = ''; errEl.textContent = ''; return; }

    try {
        const values = _computeFormula(formula, tableHeaders, originalTableData);
        const sample = values.slice(0, 5).map((v, i) => `Row ${i + 1}: ${typeof v === 'number' ? v.toFixed(4) : v}`);
        previewEl.innerHTML = `<div style="font-size:11px;color:#64748b;margin-top:6px;">
            <b>預覽 (前5行):</b><br>${sample.join('<br>')}
        </div>`;
        errEl.textContent = '';
    } catch (e) {
        errEl.textContent = '公式錯誤: ' + e.message;
        previewEl.innerHTML = '';
    }
}

export function insertColRef(colName) {
    const formulaEl = document.getElementById('cc-formula');
    if (!formulaEl) return;
    const pos = formulaEl.selectionStart || formulaEl.value.length;
    const before = formulaEl.value.slice(0, pos);
    const after = formulaEl.value.slice(pos);
    formulaEl.value = before + `[${colName}]` + after;
    formulaEl.focus();
}

// ─── Formula Engine ───

function _computeFormula(formula, headers, rows) {
    let processed = formula;

    // Step 0: Handle IF(condition, trueVal, falseVal) → ternary
    // Recursively parse from innermost IF first
    function _replaceIfs(expr) {
        // Find IF( with balanced parens
        const ifIdx = expr.search(/IF\s*\(/i);
        if (ifIdx === -1) return expr;

        // Find matching closing paren
        let depth = 0, start = expr.indexOf('(', ifIdx);
        let end = -1;
        for (let i = start; i < expr.length; i++) {
            if (expr[i] === '(') depth++;
            else if (expr[i] === ')') { depth--; if (depth === 0) { end = i; break; } }
        }
        if (end === -1) throw new Error('IF() 括號不匹配');

        const inner = expr.slice(start + 1, end);
        // Split by top-level commas (not inside parens)
        const parts = [];
        let d = 0, last = 0;
        for (let i = 0; i < inner.length; i++) {
            if (inner[i] === '(') d++;
            else if (inner[i] === ')') d--;
            else if (inner[i] === ',' && d === 0) { parts.push(inner.slice(last, i).trim()); last = i + 1; }
        }
        parts.push(inner.slice(last).trim());
        if (parts.length !== 3) throw new Error('IF() 需要 3 個參數: IF(條件, 真值, 假值)');

        // Recurse on each part in case of nested IF
        const cond = _replaceIfs(parts[0]);
        const trueVal = _replaceIfs(parts[1]);
        const falseVal = _replaceIfs(parts[2]);

        const replacement = `((${cond}) ? (${trueVal}) : (${falseVal}))`;
        const result = expr.slice(0, ifIdx) + replacement + expr.slice(end + 1);
        return _replaceIfs(result); // check for more IFs
    }
    processed = _replaceIfs(processed);

    // Replace AND/OR for logical conditions
    processed = processed.replace(/\bAND\b/gi, '&&');
    processed = processed.replace(/\bOR\b/gi, '||');

    // Step 1: Replace aggregate functions
    const aggPattern = /(AVG|SUM|MAX|MIN|STDEV|ABS|SQRT)\s*\(([^)]+)\)/gi;

    const colRefPattern = /\[([^\]]+)\]/g;

    // First handle aggregate functions
    processed = processed.replace(aggPattern, (match, fn, args) => {
        fn = fn.toUpperCase();
        const colRefs = [];
        let m;
        const innerPattern = /\[([^\]]+)\]/g;
        while ((m = innerPattern.exec(args)) !== null) {
            const idx = headers.indexOf(m[1]);
            if (idx === -1) throw new Error(`找不到欄位: ${m[1]}`);
            colRefs.push(idx);
        }
        if (colRefs.length === 0) throw new Error(`${fn}() 需要至少一個欄位引用`);

        if (fn === 'ABS' || fn === 'SQRT') {
            if (colRefs.length !== 1) throw new Error(`${fn}() 只能一個參數`);
            return fn === 'ABS' ? `Math.abs(Number(row[${colRefs[0]}]))` : `Math.sqrt(Number(row[${colRefs[0]}]))`;
        }
        return `_agg("${fn}", row, [${colRefs.join(',')}])`;
    });

    // Then replace remaining [colName] refs
    processed = processed.replace(colRefPattern, (match, colName) => {
        const idx = headers.indexOf(colName);
        if (idx === -1) throw new Error(`找不到欄位: ${colName}`);
        return `Number(row[${idx}])`;
    });

    // Build function
    const fnBody = `
        function _agg(fn, row, indices) {
            const vals = indices.map(i => Number(row[i])).filter(v => !isNaN(v));
            if (vals.length === 0) return NaN;
            switch(fn) {
                case 'AVG': return vals.reduce((a,b) => a+b, 0) / vals.length;
                case 'SUM': return vals.reduce((a,b) => a+b, 0);
                case 'MAX': return Math.max(...vals);
                case 'MIN': return Math.min(...vals);
                case 'STDEV': {
                    const m = vals.reduce((a,b) => a+b, 0) / vals.length;
                    return Math.sqrt(vals.reduce((a,v) => a + (v-m)*(v-m), 0) / vals.length);
                }
                default: return NaN;
            }
        }
        return ${processed};
    `;

    const computeFn = new Function('row', fnBody);

    // Test with first row
    try {
        computeFn(rows[0]);
    } catch (e) {
        throw new Error('公式語法錯誤: ' + e.message);
    }

    // Compute all rows
    return rows.map(row => {
        try {
            const v = computeFn(row);
            return isFinite(v) ? String(v) : '';
        } catch {
            return '';
        }
    });
}

// ─── Column Picker ───

function _renderColPicker() {
    const container = document.getElementById('cc-col-picker');
    if (!container) return;
    const searchEl = document.getElementById('cc-col-search');
    const kw = searchEl ? searchEl.value.toLowerCase() : '';

    const cols = tableHeaders.filter(h => {
        if (kw && !h.toLowerCase().includes(kw)) return false;
        return true;
    });

    container.innerHTML = cols.map(h =>
        `<div class="cc-col-tag" onclick="window.insertColRef('${h.replace(/'/g, "\\'")}')"
            style="display:inline-block;padding:2px 8px;margin:2px;background:#eff6ff;border:1px solid #bfdbfe;border-radius:12px;font-size:11px;color:#1d4ed8;cursor:pointer;white-space:nowrap;max-width:200px;overflow:hidden;text-overflow:ellipsis;"
            title="${h}">${h}</div>`
    ).join('');
}

// ─── Modal Creation ───

function _createModal() {
    const modal = document.createElement('div');
    modal.id = 'computed-col-modal';
    modal.style.cssText = 'display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.4);z-index:10000;align-items:center;justify-content:center;';
    modal.innerHTML = `
    <div style="background:#fff;border-radius:12px;width:560px;max-height:80vh;overflow-y:auto;box-shadow:0 20px 60px rgba(0,0,0,0.3);padding:24px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
            <h3 style="margin:0;font-size:16px;color:#1e293b;">➕ 新增計算欄位</h3>
            <button onclick="window.hideAddColumnModal()" style="background:none;border:none;font-size:20px;cursor:pointer;color:#94a3b8;">✕</button>
        </div>

        <div style="margin-bottom:12px;">
            <label style="font-size:12px;font-weight:600;color:#475569;display:block;margin-bottom:4px;">欄位名稱</label>
            <input id="cc-col-name" type="text" placeholder="例: 差值_A_B"
                style="width:100%;padding:8px 12px;border:1px solid #cbd5e1;border-radius:6px;font-size:13px;box-sizing:border-box;">
        </div>

        <div style="margin-bottom:12px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
                <label style="font-size:12px;font-weight:600;color:#475569;">條件產生器 <span style="color:#94a3b8;font-weight:400;">(選填，自動產生公式)</span></label>
                <button onclick="window._ccAddCondRow()" style="padding:2px 8px;border:1px solid #3b82f6;border-radius:4px;background:#eff6ff;color:#3b82f6;font-size:11px;cursor:pointer;">+ 新增條件</button>
            </div>
            <div id="cc-cond-rows" style="display:flex;flex-direction:column;gap:6px;"></div>
            <div id="cc-cond-default" style="display:none;margin-top:6px;display:flex;align-items:center;gap:6px;">
                <span style="font-size:11px;color:#64748b;white-space:nowrap;">其他 →</span>
                <input id="cc-default-val" type="text" placeholder="預設值" style="width:80px;padding:4px 6px;border:1px solid #cbd5e1;border-radius:4px;font-size:11px;">
            </div>
            <button onclick="window._ccGenFormula()" style="margin-top:6px;padding:4px 12px;border:1px solid #10b981;border-radius:4px;background:#ecfdf5;color:#059669;font-size:11px;cursor:pointer;display:none;" id="cc-gen-btn">⚡ 產生公式</button>
        </div>

        <div style="margin-bottom:12px;">
            <label style="font-size:12px;font-weight:600;color:#475569;display:block;margin-bottom:4px;">公式 <span style="color:#94a3b8;font-weight:400;">(可手動編輯或由上方自動產生)</span></label>
            <textarea id="cc-formula" rows="3" placeholder="例: ([欄位A] - [欄位B]) / [欄位C]&#10;IF: IF([A] > 100, 1, 0)&#10;多層: IF([A] > 100, 2, IF([A] > 50, 1, 0))"
                style="width:100%;padding:8px 12px;border:1px solid #cbd5e1;border-radius:6px;font-size:13px;font-family:monospace;box-sizing:border-box;resize:vertical;"></textarea>
            <div style="font-size:10px;color:#94a3b8;margin-top:4px;">
                支援 +, -, *, /, (, ) | 函數: IF, AVG, SUM, MAX, MIN, STDEV, ABS, SQRT | 邏輯: AND, OR
            </div>
        </div>

        <div style="margin-bottom:12px;">
            <label style="font-size:12px;font-weight:600;color:#475569;display:block;margin-bottom:4px;">可用欄位 <span style="color:#94a3b8;font-weight:400;">(點擊插入)</span></label>
            <input id="cc-col-search" type="text" placeholder="搜尋欄位..." oninput="window._ccFilterCols()"
                style="width:100%;padding:6px 10px;border:1px solid #e2e8f0;border-radius:4px;font-size:11px;margin-bottom:6px;box-sizing:border-box;">
            <div id="cc-col-picker" style="max-height:120px;overflow-y:auto;border:1px solid #e2e8f0;border-radius:6px;padding:6px;"></div>
        </div>

        <div id="cc-error" style="color:#ef4444;font-size:12px;min-height:16px;margin-bottom:8px;"></div>
        <div id="cc-preview"></div>

        <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px;">
            <button onclick="window.previewComputedColumn()"
                style="padding:8px 16px;border:1px solid #cbd5e1;border-radius:6px;background:#f8fafc;color:#475569;font-size:13px;cursor:pointer;">
                👁 預覽
            </button>
            <button onclick="window.applyComputedColumn()"
                style="padding:8px 20px;border:none;border-radius:6px;background:linear-gradient(135deg,#3b82f6,#2563eb);color:#fff;font-size:13px;font-weight:600;cursor:pointer;box-shadow:0 2px 6px rgba(37,99,235,0.3);">
                ✅ 套用
            </button>
        </div>
    </div>`;

    // Close on backdrop click
    modal.addEventListener('click', e => {
        if (e.target === modal) hideAddColumnModal();
    });

    // Close on ESC
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape' && modal.style.display !== 'none') hideAddColumnModal();
    });

    return modal;
}

// Expose filter function for search input
export function _ccFilterCols() {
    _renderColPicker();
}

// ─── Condition Builder ───

let _ccCondCount = 0;

export function _ccAddCondRow() {
    _ccCondCount++;
    const container = document.getElementById('cc-cond-rows');
    if (!container) return;

    const options = tableHeaders.map(h => `<option value="${h}">${h}</option>`).join('');
    const row = document.createElement('div');
    row.className = 'cc-cond-row';
    row.dataset.condId = _ccCondCount;
    row.style.cssText = 'display:flex;align-items:center;gap:4px;padding:6px 8px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;';
    row.innerHTML = `
        <span style="font-size:11px;color:#64748b;white-space:nowrap;">若</span>
        <select class="cc-cond-col" style="flex:1;min-width:0;padding:3px 4px;border:1px solid #cbd5e1;border-radius:4px;font-size:11px;">
            <option value="">選擇欄位</option>${options}
        </select>
        <select class="cc-cond-op" style="width:50px;padding:3px 2px;border:1px solid #cbd5e1;border-radius:4px;font-size:11px;">
            <option value=">">&gt;</option>
            <option value="<">&lt;</option>
            <option value=">=">&ge;</option>
            <option value="<=">&le;</option>
            <option value="==">＝</option>
            <option value="!=">≠</option>
        </select>
        <input class="cc-cond-val" type="text" placeholder="值" style="width:60px;padding:3px 4px;border:1px solid #cbd5e1;border-radius:4px;font-size:11px;">
        <span style="font-size:11px;color:#64748b;">→</span>
        <input class="cc-cond-result" type="text" placeholder="結果" style="width:60px;padding:3px 4px;border:1px solid #cbd5e1;border-radius:4px;font-size:11px;">
        <button onclick="window._ccRemoveCondRow(this)" style="background:none;border:none;color:#ef4444;cursor:pointer;font-size:14px;padding:0 2px;">✕</button>
    `;
    container.appendChild(row);

    // Show default & generate button
    document.getElementById('cc-cond-default').style.display = 'flex';
    document.getElementById('cc-gen-btn').style.display = 'inline-block';
}

export function _ccRemoveCondRow(btn) {
    const row = btn.closest('.cc-cond-row');
    if (row) row.remove();
    const container = document.getElementById('cc-cond-rows');
    if (container && container.children.length === 0) {
        document.getElementById('cc-cond-default').style.display = 'none';
        document.getElementById('cc-gen-btn').style.display = 'none';
    }
}

export function _ccGenFormula() {
    const rows = document.querySelectorAll('.cc-cond-row');
    const defaultVal = document.getElementById('cc-default-val')?.value.trim() || '0';
    const errEl = document.getElementById('cc-error');

    const conditions = [];
    for (const row of rows) {
        const col = row.querySelector('.cc-cond-col').value;
        const op = row.querySelector('.cc-cond-op').value;
        const val = row.querySelector('.cc-cond-val').value.trim();
        const result = row.querySelector('.cc-cond-result').value.trim();
        if (!col) { errEl.textContent = '請選擇欄位'; return; }
        if (!val) { errEl.textContent = '請輸入比較值'; return; }
        if (!result) { errEl.textContent = '請輸入結果值'; return; }
        conditions.push({ col, op, val, result });
    }

    if (conditions.length === 0) { errEl.textContent = '請至少新增一個條件'; return; }
    errEl.textContent = '';

    // Build nested IF from last to first
    let formula = defaultVal;
    for (let i = conditions.length - 1; i >= 0; i--) {
        const c = conditions[i];
        formula = `IF([${c.col}] ${c.op} ${c.val}, ${c.result}, ${formula})`;
    }

    document.getElementById('cc-formula').value = formula;
}
