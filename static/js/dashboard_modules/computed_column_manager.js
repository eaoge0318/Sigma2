/**
 * computed_column_manager.js
 * Manages computed/calculated columns for the data analysis table.
 * Supports arithmetic operations, column references, and aggregate functions.
 */

import { tableHeaders, originalTableData, refreshTableDisplay, addVisibleColumn } from './analysis_manager.js';

// Track computed columns for UI
let _computedCols = []; // [{name, formula}]

// Placeholder token used in templates that need a column substituted later
const _PLACEHOLDER = '欄位';

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

    // Use live getters to access the correct module instance's data
    const liveHeaders = (window.getAnalysisTableHeaders ? window.getAnalysisTableHeaders() : null) || tableHeaders;
    const liveData    = (window.getAnalysisOriginalData ? window.getAnalysisOriginalData()  : null) || originalTableData;

    if (!name) { errEl.textContent = '請輸入欄位名稱'; return; }
    if (!formula) { errEl.textContent = '請輸入公式'; return; }
    if (liveHeaders.includes(name)) { errEl.textContent = `欄位 "${name}" 已存在`; return; }

    try {
        const values = _computeFormula(formula, liveHeaders, liveData);
        // Add to data via window mutators (ensures we modify the correct module instance)
        if (window.pushAnalysisHeader) {
            window.pushAnalysisHeader(name);
        } else {
            liveHeaders.push(name);
        }
        for (let i = 0; i < liveData.length; i++) {
            if (window.pushAnalysisRowValue) {
                window.pushAnalysisRowValue(i, values[i]);
            } else {
                liveData[i].push(values[i]);
            }
        }
        _computedCols.push({ name, formula });
        addVisibleColumn(liveHeaders.length - 1);
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

    const liveHeaders = (window.getAnalysisTableHeaders ? window.getAnalysisTableHeaders() : null) || tableHeaders;
    const liveData    = (window.getAnalysisOriginalData ? window.getAnalysisOriginalData()  : null) || originalTableData;

    try {
        const values = _computeFormula(formula, liveHeaders, liveData);
        const sample = values.slice(0, 5).map((v, i) => `Row ${i + 1}: ${v}`);
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

    // If template placeholder [欄位] exists in formula, replace all instances first
    const placeholder = `[${_PLACEHOLDER}]`;
    if (formulaEl.value.includes(placeholder)) {
        formulaEl.value = formulaEl.value.split(placeholder).join(`[${colName}]`);
        // Also update the column name field if it still has the placeholder
        const nameEl = document.getElementById('cc-col-name');
        if (nameEl && nameEl.value.includes(_PLACEHOLDER)) {
            nameEl.value = nameEl.value.split(_PLACEHOLDER).join(colName);
        }
        // Hide hint since placeholder is resolved
        const hint = document.getElementById('cc-tmpl-hint');
        if (hint) hint.style.display = 'none';
        formulaEl.focus();
        return;
    }

    // Otherwise insert at cursor
    const pos = formulaEl.selectionStart ?? formulaEl.value.length;
    const before = formulaEl.value.slice(0, pos);
    const after = formulaEl.value.slice(pos);
    formulaEl.value = before + `[${colName}]` + after;
    formulaEl.focus();
}

// ─── Formula Engine ───

function _computeFormula(formula, headers, rows) {
    let processed = formula;

    // Step -1: Pre-compute global aggregates GAVG/GSTD/GMAX/GMIN/GSUM
    // Pattern: GAVG([colName]) etc. — replaced with numeric constant before per-row eval
    const globalFnPat = /G(AVG|STD|MAX|MIN|SUM)\s*\(\s*\[([^\]]+)\]\s*\)/gi;
    processed = processed.replace(globalFnPat, (match, fn, colName) => {
        const idx = headers.indexOf(colName);
        if (idx === -1) throw new Error(`找不到欄位: ${colName}`);
        const vals = rows.map(r => Number(r[idx])).filter(v => !isNaN(v));
        if (vals.length === 0) return '0';
        fn = fn.toUpperCase();
        if (fn === 'AVG') return String(vals.reduce((a,b) => a+b, 0) / vals.length);
        if (fn === 'SUM') return String(vals.reduce((a,b) => a+b, 0));
        if (fn === 'MAX') return String(Math.max(...vals));
        if (fn === 'MIN') return String(Math.min(...vals));
        if (fn === 'STD') {
            const m = vals.reduce((a,b) => a+b, 0) / vals.length;
            return String(Math.sqrt(vals.reduce((a,v) => a + (v-m)**2, 0) / vals.length));
        }
        return '0';
    });

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

    // ── String functions (must be processed BEFORE numeric [col] replacement) ──

    // Helper: split top-level comma-separated args (respects quotes and brackets)
    function _splitArgs(str) {
        const parts = [];
        let cur = '', depth = 0, inStr = false, strCh = '';
        for (const ch of str) {
            if (inStr) { cur += ch; if (ch === strCh) inStr = false; }
            else if (ch === '"' || ch === "'") { inStr = true; strCh = ch; cur += ch; }
            else if (ch === '(' || ch === '[') { depth++; cur += ch; }
            else if (ch === ')' || ch === ']') { depth--; cur += ch; }
            else if (ch === ',' && depth === 0) { parts.push(cur.trim()); cur = ''; }
            else cur += ch;
        }
        if (cur.trim()) parts.push(cur.trim());
        return parts;
    }

    // TEXT([col]) → raw string value of column
    processed = processed.replace(/TEXT\s*\(\s*\[([^\]]+)\]\s*\)/gi, (match, colName) => {
        const idx = headers.indexOf(colName);
        if (idx === -1) throw new Error(`找不到欄位: ${colName}`);
        return `String(row[${idx}] ?? '')`;
    });

    // STRIPMS([col]) → remove milliseconds (.xxx) from time/datetime string
    processed = processed.replace(/STRIPMS\s*\(\s*\[([^\]]+)\]\s*\)/gi, (match, colName) => {
        const idx = headers.indexOf(colName);
        if (idx === -1) throw new Error(`找不到欄位: ${colName}`);
        return `String(row[${idx}] ?? '').replace(/\\.\\d+$/, '')`;
    });

    // CONCAT(arg1, arg2, ...) → string concatenation; args can be [col], "literal", or expressions
    let concatPos;
    while ((concatPos = processed.search(/CONCAT\s*\(/i)) !== -1) {
        const parenStart = processed.indexOf('(', concatPos);
        let depth = 0, parenEnd = -1;
        for (let i = parenStart; i < processed.length; i++) {
            if (processed[i] === '(') depth++;
            else if (processed[i] === ')') { depth--; if (depth === 0) { parenEnd = i; break; } }
        }
        if (parenEnd === -1) throw new Error('CONCAT() 括號不匹配');
        const concatArgs = _splitArgs(processed.slice(parenStart + 1, parenEnd));
        const converted = concatArgs.map(arg => {
            if (/^["']/.test(arg)) return arg; // string literal already quoted
            const colMatch = arg.match(/^\[([^\]]+)\]$/);
            if (colMatch) {
                const idx = headers.indexOf(colMatch[1]);
                if (idx === -1) throw new Error(`找不到欄位: ${colMatch[1]}`);
                return `String(row[${idx}] ?? '')`;
            }
            return `String(${arg})`; // expression
        });
        processed = processed.slice(0, concatPos) + `(${converted.join(' + ')})` + processed.slice(parenEnd + 1);
    }

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
    // Skip purely-numeric tokens like [5] which were already emitted by string-function
    // expansion above (e.g. String(row[5] ?? '') → the [5] must not be re-matched here).
    processed = processed.replace(colRefPattern, (match, colName) => {
        if (/^[\d,\s]+$/.test(colName)) return match; // already a numeric index, leave it
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
            if (v === null || v === undefined) return '';
            // Allow both numeric and string results
            return isFinite(v) ? String(v) : (typeof v === 'string' ? v : '');
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

    // Use live getter to avoid closure staleness
    const allHeaders = (window.getAnalysisTableHeaders ? window.getAnalysisTableHeaders() : null) || tableHeaders;

    const cols = allHeaders.filter(h => {
        if (kw && !h.toLowerCase().includes(kw)) return false;
        return true;
    });

    container.innerHTML = cols.map(h =>
        `<div class="cc-col-tag" onclick="window.insertColRef('${h.replace(/\\/g,'\\\\').replace(/'/g, "\\'")}')"
            style="display:inline-block;padding:2px 8px;margin:2px;background:#eff6ff;border:1px solid #bfdbfe;border-radius:12px;font-size:11px;color:#1d4ed8;cursor:pointer;white-space:nowrap;max-width:200px;overflow:hidden;text-overflow:ellipsis;"
            title="${h}">${h}</div>`
    ).join('');

    // Sync template column dropdown
    const tmplSel = document.getElementById('cc-tmpl-col');
    if (tmplSel) {
        const cur = tmplSel.value;
        tmplSel.innerHTML = '<option value="">選擇欄位…</option>' +
            allHeaders.map(h => `<option value="${h}"${h===cur?' selected':''}>${h}</option>`).join('');
    }
}

window._ccToggleFnRef = function() {
    const el = document.getElementById('cc-fn-ref');
    if (!el) return;
    el.style.display = el.style.display === 'none' ? 'block' : 'none';
};

window._ccInsertTemplate = function(type) {
    const nameEl = document.getElementById('cc-col-name');
    const formulaEl = document.getElementById('cc-formula');
    const errEl = document.getElementById('cc-error');
    const hint = document.getElementById('cc-tmpl-hint');
    if (!formulaEl) return;
    if (errEl) errEl.textContent = '';

    // datetime: auto-detect date and time columns — no placeholder needed
    if (type === 'datetime') {
        const liveH = (window.getAnalysisTableHeaders ? window.getAnalysisTableHeaders() : null) || tableHeaders;
        const dateCol = liveH.find(h => /日期|date/i.test(h)) || liveH[0] || '日期';
        const timeCol = liveH.find(h => /時間|time/i.test(h)) || liveH[1] || '時間';
        formulaEl.value = `CONCAT([${dateCol}], " ", [${timeCol}])`;
        if (nameEl && !nameEl.value) nameEl.value = '日期時間';
        if (hint) hint.style.display = 'none';
        return;
    }

    // Other templates: insert with placeholder, then user clicks a column tag to substitute
    const P = _PLACEHOLDER;
    const templates = {
        std:    { formula: `GSTD([${P}])`,                                    name: `${P}_標準差` },
        avg:    { formula: `GAVG([${P}])`,                                    name: `${P}_平均值` },
        zscore: { formula: `([${P}] - GAVG([${P}])) / GSTD([${P}])`,         name: `${P}_Z分數` },
        norm:   { formula: `([${P}] - GMIN([${P}])) / (GMAX([${P}]) - GMIN([${P}]))`, name: `${P}_正規化` },
    };
    const t = templates[type];
    if (!t) return;
    formulaEl.value = t.formula;
    if (nameEl && !nameEl.value) nameEl.value = t.name;
    // Show hint to guide user to click a column tag
    if (hint) hint.style.display = 'block';
    // Focus formula so user can see it
    formulaEl.focus();
};

// ─── Modal Creation ───

function _createModal() {
    const modal = document.createElement('div');
    modal.id = 'computed-col-modal';
    modal.style.cssText = 'display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.4);z-index:10000;align-items:center;justify-content:center;';
    modal.innerHTML = `
    <div style="background:#fff;border-radius:12px;width:500px;max-height:85vh;overflow-y:auto;box-shadow:0 20px 60px rgba(0,0,0,0.3);padding:20px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
            <h3 style="margin:0;font-size:15px;color:#1e293b;">➕ 新增計算欄位</h3>
            <button onclick="window.hideAddColumnModal()" style="background:none;border:none;font-size:20px;cursor:pointer;color:#94a3b8;">✕</button>
        </div>

        <div style="margin-bottom:12px;">
            <label style="font-size:12px;font-weight:600;color:#475569;display:block;margin-bottom:4px;">欄位名稱</label>
            <input id="cc-col-name" type="text" placeholder="例: 日期時間"
                style="width:100%;padding:8px 12px;border:1px solid #cbd5e1;border-radius:6px;font-size:13px;box-sizing:border-box;">
        </div>

        <div style="margin-bottom:12px;">
            <label style="font-size:12px;font-weight:600;color:#475569;display:block;margin-bottom:6px;">快速範本</label>
            <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:6px;">
                <button onclick="window._ccInsertTemplate('datetime')" style="padding:4px 12px;border:1px solid #0891b2;border-radius:6px;background:#ecfeff;color:#0891b2;font-size:12px;font-weight:600;cursor:pointer;">📅 合併日期時間</button>
                <button onclick="window._ccInsertTemplate('zscore')"   style="padding:4px 12px;border:1px solid #059669;border-radius:6px;background:#ecfdf5;color:#059669;font-size:12px;font-weight:600;cursor:pointer;">Z 分數</button>
                <button onclick="window._ccInsertTemplate('norm')"     style="padding:4px 12px;border:1px solid #ea580c;border-radius:6px;background:#fff7ed;color:#ea580c;font-size:12px;font-weight:600;cursor:pointer;">0~1 正規化</button>
                <button onclick="window._ccInsertTemplate('avg')"      style="padding:4px 12px;border:1px solid #2563eb;border-radius:6px;background:#eff6ff;color:#2563eb;font-size:12px;font-weight:600;cursor:pointer;">平均值</button>
                <button onclick="window._ccInsertTemplate('std')"      style="padding:4px 12px;border:1px solid #7c3aed;border-radius:6px;background:#faf5ff;color:#7c3aed;font-size:12px;font-weight:600;cursor:pointer;">標準差</button>
            </div>
            <div id="cc-tmpl-hint" style="font-size:11px;color:#94a3b8;display:none;">
                ↓ 從下方「可用欄位」點一個欄位，公式中的 <code style="background:#f1f5f9;padding:1px 4px;border-radius:3px;">欄位</code> 會自動替換
            </div>
        </div>

        <div style="margin-bottom:12px;">
            <label style="font-size:12px;font-weight:600;color:#475569;display:block;margin-bottom:4px;">
                公式 <span style="color:#94a3b8;font-weight:400;font-size:11px;">— 也可直接手動修改</span>
                <span onclick="window._ccToggleFnRef()" title="函式說明"
                    style="display:inline-flex;align-items:center;justify-content:center;margin-left:6px;width:16px;height:16px;border-radius:50%;background:#3b82f6;color:#fff;font-size:10px;font-weight:700;cursor:pointer;vertical-align:middle;user-select:none;">?</span>
            </label>
            <div id="cc-fn-ref" style="display:none;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:10px 12px;margin-bottom:8px;font-size:11px;line-height:1.8;">
                <div style="font-weight:700;color:#1e293b;margin-bottom:6px;">可用函式</div>
                <table style="border-collapse:collapse;width:100%;">
                    <tr style="color:#64748b;border-bottom:1px solid #e2e8f0;">
                        <td style="padding:3px 8px 3px 0;font-weight:600;color:#1d4ed8;font-family:monospace;white-space:nowrap;">STRIPMS([欄位])</td>
                        <td style="padding:3px 0;color:#475569;">去除毫秒　<span style="color:#94a3b8;">08:30:45.123 → 08:30:45</span></td>
                    </tr>
                    <tr style="color:#64748b;border-bottom:1px solid #e2e8f0;">
                        <td style="padding:3px 8px 3px 0;font-family:monospace;color:#1d4ed8;white-space:nowrap;">TEXT([欄位])</td>
                        <td style="padding:3px 0;color:#475569;">轉為文字字串</td>
                    </tr>
                    <tr style="color:#64748b;border-bottom:1px solid #e2e8f0;">
                        <td style="padding:3px 8px 3px 0;font-family:monospace;color:#1d4ed8;white-space:nowrap;">CONCAT(A, B, …)</td>
                        <td style="padding:3px 0;color:#475569;">合併文字　<span style="color:#94a3b8;">CONCAT([日期], " ", [時間])</span></td>
                    </tr>
                    <tr style="color:#64748b;border-bottom:1px solid #e2e8f0;">
                        <td style="padding:3px 8px 3px 0;font-family:monospace;color:#1d4ed8;white-space:nowrap;">IF(條件, 真, 假)</td>
                        <td style="padding:3px 0;color:#475569;">條件判斷　<span style="color:#94a3b8;">IF([A] > 0, [A], 0)</span></td>
                    </tr>
                    <tr style="color:#64748b;border-bottom:1px solid #e2e8f0;">
                        <td style="padding:3px 8px 3px 0;font-family:monospace;color:#1d4ed8;white-space:nowrap;">ABS([欄位])</td>
                        <td style="padding:3px 0;color:#475569;">絕對值</td>
                    </tr>
                    <tr style="color:#64748b;border-bottom:1px solid #e2e8f0;">
                        <td style="padding:3px 8px 3px 0;font-family:monospace;color:#1d4ed8;white-space:nowrap;">SQRT([欄位])</td>
                        <td style="padding:3px 0;color:#475569;">平方根</td>
                    </tr>
                    <tr style="color:#64748b;border-bottom:1px solid #e2e8f0;">
                        <td style="padding:3px 8px 3px 0;font-family:monospace;color:#1d4ed8;white-space:nowrap;">GAVG / GSTD / GMAX / GMIN([欄位])</td>
                        <td style="padding:3px 0;color:#475569;">整欄平均 / 標準差 / 最大 / 最小</td>
                    </tr>
                    <tr>
                        <td style="padding:3px 8px 3px 0;font-family:monospace;color:#1d4ed8;white-space:nowrap;">+ - * / ( )</td>
                        <td style="padding:3px 0;color:#475569;">四則運算　<span style="color:#94a3b8;">([A] - [B]) / [C]</span></td>
                    </tr>
                </table>
            </div>
            <textarea id="cc-formula" rows="3" placeholder="點上方範本按鈕自動填入，或手動輸入&#10;範例: [欄位A] * 2 + [欄位B]"
                style="width:100%;padding:8px 12px;border:1px solid #cbd5e1;border-radius:6px;font-size:13px;font-family:monospace;box-sizing:border-box;resize:vertical;"></textarea>
        </div>

        <div style="margin-bottom:12px;">
            <label style="font-size:12px;font-weight:600;color:#475569;display:block;margin-bottom:4px;">可用欄位 <span style="color:#94a3b8;font-weight:400;font-size:11px;">— 點擊即插入公式</span></label>
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

    const allHeaders = (window.getAnalysisTableHeaders ? window.getAnalysisTableHeaders() : null) || tableHeaders;
    const options = allHeaders.map(h => `<option value="${h}">${h}</option>`).join('');
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
