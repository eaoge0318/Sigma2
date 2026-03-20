// ================================================================
// ME Manager - 主效應圖三步驟精靈
// Depends on globals from data_preparation.html:
//   currentFileId, allFields, getSessionId(), _mvaFilters,
//   _clOutlierIndices, _clExcludedCols, _activeDataset
// ================================================================

(function () {
    'use strict';

    // ============ STATE ============
    let _meStep = 1;
    let _meTargets = [];        // [{ col, weight }]
    let _meAllCols = [];        // all non-excluded numeric col names
    let _meControlFactors = []; // selected control factors
    let _meBgFactors = [];      // selected background factors
    let _meAlgorithm = 'xgboost';
    let _meAnalysisMethod = 'ale';
    let _meHyperparams = {};
    // (last result stored in _meRenderCtx)
    let _meCurrentTrendCol = null;          // column currently shown in trend area
    let _meTargetStats = {};                // col → { mean, usl, lsl, std, n }
    let _meTrendVals = [];                  // raw values of the currently displayed trend
    let _meColStats = {};      // col → {min, max, median, mean, std}
    let _meSliderVals = {};    // factor → current slider value
    let _meFixedFactors = new Set(); // factors locked from simulation
    let _meSimSigmas = {};   // { factorName: sigma } – persists between panel opens
    let _meSimDists  = {};   // { factorName: 'normal'|'uniform' }
    let _meParamSpecs = {};  // { factorName: { usl, lsl } } – X-axis operating limits
    let _meSimResults = null; // last simulation result data { data, targetSpecs }
    let _meShowRealData = false;     // overlay scatter data toggle
    let _meCellHeight   = 100;       // chart cell height in px (user-adjustable)
    // ── Display / analysis settings (sent to backend on each run) ──
    let _meSettings = {
        max_scatter:     2000,   // scatter points per factor-target pair
        grid_resolution: 50,    // ALE/PDP grid bins
        show_y_spec:     true,   // Y-axis USL/LSL/T horizontal lines
        show_x_spec:     true,   // X-axis USL/LSL vertical lines
        show_pred:       true,   // purple Pred line
    };

    let _meDragFi     = null;  // column index currently being dragged
    let _meDragTarget = 'slider'; // 'slider' | 'xusl' | 'xlsl'

    // ============ TARGET PALETTE (colors per target) ============
    const TARGET_COLORS = [
        '#3b82f6', '#f97316', '#10b981', '#a855f7', '#ef4444',
        '#eab308', '#06b6d4', '#ec4899',
    ];

    // ============ PUBLIC API ============
    window.meInit = function () {
        if (typeof allFields === 'undefined' || allFields.length === 0) return;
        _populateColumns();
        meGotoStep(1);
    };

    window.meGotoStep = meGotoStep;
    window.meRun = meRunAnalysis;

    // Called when data cleaning rules change — clears results to avoid stale data
    window.meReset = function () {
        // Only invalidate the result panel — keep Target/factor selections intact
        _meRenderCtx = null;
        _meSimResults = null;
        const resultArea = document.getElementById('me-step3-content');
        if (resultArea) resultArea.innerHTML = `
            <div style="display:flex;align-items:center;justify-content:center;width:100%;height:100%;flex-direction:column;gap:8px;color:#94a3b8;">
                <div style="font-size:28px;">⚠️</div>
                <div style="font-size:13px;color:#f59e0b;font-weight:600;">清洗規則已變更</div>
                <div style="font-size:12px;">請重新執行分析以使用最新資料</div>
            </div>`;
        // If currently on step 3, return to step 2
        if (_meStep === 3) meGotoStep(2);
    };

    // Full reset when dataset/file changes
    window.meFullReset = function () {
        _meRenderCtx = null;
        _meSimResults = null;
        _meTargets = [];
        _meControlFactors = [];
        _meBgFactors = [];
        const resultArea = document.getElementById('me-step3-content');
        if (resultArea) resultArea.innerHTML = _emptyState('請重新設定並執行分析');
        _renderTargetChips();
        meGotoStep(1);
    };

    // ============ STEP NAVIGATION ============
    function meGotoStep(n) {
        _meStep = n;
        ['me-step1', 'me-step2', 'me-step3'].forEach((id, i) => {
            const el = document.getElementById(id);
            if (el) el.style.display = (i + 1 === n) ? 'flex' : 'none';
        });

        // Update sidebar indicators
        for (let i = 1; i <= 3; i++) {
            const tab = document.getElementById('me-tab-' + i);
            if (!tab) continue;
            tab.classList.remove('rsm-step-active', 'rsm-step-done');
            const doneText = tab.querySelector('.rsm-step-done-text');
            if (doneText) doneText.textContent = '';
            if (i === n) tab.classList.add('rsm-step-active');
            else if (i < n) {
                tab.classList.add('rsm-step-done');
                if (doneText) doneText.textContent = ' ✓';
            }
        }

        // Update title
        const titles = ['第一步: 🎯 選擇目標變數 (Y)', '第二步: ⚙️ 選擇特徵與演算法', '第三步: 📊 分析結果'];
        const titleEl = document.getElementById('me-content-title');
        if (titleEl) titleEl.textContent = titles[n - 1];

        // Refresh factor lists when entering step 2 (ensures target cols are removed)
        if (n === 2) _renderFactorLists();

        // Run button state
        _updateRunBtn();
    }

    function _updateRunBtn() {
        const btn = document.getElementById('me-sidebar-run-btn');
        if (!btn) return;
        const canRun = _meTargets.length > 0 && _meControlFactors.length > 0;
        btn.disabled = !canRun;
        btn.style.background = canRun ? '#2563eb' : '#e2e8f0';
        btn.style.color = canRun ? '#fff' : '#64748b';
        btn.style.cursor = canRun ? 'pointer' : 'not-allowed';
    }

    // ============ COLUMN POPULATION ============
    function _isNumericDtype(dtype) {
        if (!dtype) return false;
        const d = dtype.toLowerCase();
        return d.includes('int') || d.includes('float') || d.includes('number') ||
               d === 'numeric' || d === 'double' || d === 'decimal';
    }

    function _populateColumns() {
        const numFields = allFields.filter(f => _isNumericDtype(f.dtype));
        // Only fall back to allFields if NONE are numeric (edge case for unusual dtype strings)
        let cols = numFields.length > 0 ? numFields : allFields.filter(f => {
            // Last-resort: exclude obviously non-numeric types
            const d = (f.dtype || '').toLowerCase();
            return !['object', 'string', 'str', 'bool', 'boolean',
                     'datetime', 'datetime64', 'timedelta', 'category'].includes(d);
        });

        if (typeof _clExcludedCols !== 'undefined' && _clExcludedCols) {
            cols = cols.filter(f => {
                if (_clExcludedCols instanceof Set) return !_clExcludedCols.has(f.name);
                if (Array.isArray(_clExcludedCols)) return !_clExcludedCols.includes(f.name);
                return true;
            });
        }

        _meAllCols = cols.map(c => c.name);
        
        // Update the native select for targets
        const targetSel = document.getElementById('me-target-select');
        if (targetSel) {
            targetSel.innerHTML = '<option value="">— 選擇目標變數 —</option>';
            _meAllCols.forEach(name => {
                const opt = document.createElement('option');
                opt.value = name;
                opt.textContent = name;
                targetSel.appendChild(opt);
            });
            targetSel.onchange = function () {
                if (typeof window.meTargetChange === 'function') window.meTargetChange();
            };
        }

        // Re-populate factor lists
        _renderFactorLists();
    }

    // ============ TARGET TREND CHART ============

    window.meTargetChange = function () {
        const sel = document.getElementById('me-target-select');
        const chartArea = document.getElementById('me-trend-area');
        if (!sel || !chartArea) return;
        const col = sel.value;
        if (col) {
            _meCurrentTrendCol = col;
            _loadTrend(col);
            _renderTargetChips(); // refresh highlight
        } else {
            _meCurrentTrendCol = null;
            chartArea.innerHTML = '<div style="color:#94a3b8;font-size:12px;text-align:center;">選擇目標後顯示數據趨勢</div>';
        }
    };

    async function _loadTrend(col) {
        const chartArea = document.getElementById('me-trend-area');
        if (!chartArea) return;
        chartArea.innerHTML = '<div style="padding:20px;text-align:center;color:#94a3b8;">⏳ 載入趨勢...</div>';

        try {
            const sid = typeof getSessionId === 'function' ? getSessionId() : 'default';
            const filters = (typeof _activeDataset !== 'undefined' && _activeDataset?.filters) ? 
                _activeDataset.filters.map(f => ({
                    column: f.col, keyword: '==' + String(f.value || ''), exclude_empty: false
                })) : [];
            const excludeIndices = (typeof _clOutlierIndices !== 'undefined') ? _clOutlierIndices : [];
            const excludeCols = (typeof _clExcludedCols !== 'undefined') ? _clExcludedCols : [];
            const queryUrl = `/api/data-prep/gb-column-values?file_id=${currentFileId}&column=${encodeURIComponent(col)}&session_id=${sid}&filters=${encodeURIComponent(JSON.stringify(filters))}&exclude_indices=${encodeURIComponent(JSON.stringify(excludeIndices))}&exclude_cols=${encodeURIComponent(JSON.stringify(excludeCols))}`;
            
            const res = await fetch(queryUrl);
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Failed');

            _drawTrend(chartArea, data);
        } catch (e) {
            chartArea.innerHTML = `<div style="padding:20px;text-align:center;color:#ef4444;">❌ ${e.message}</div>`;
        }
    }

    function _drawTrend(container, data) {
        const vals = data.values || [];
        const nums = vals.filter(v => v != null);
        if (nums.length === 0) {
            container.innerHTML = '<div style="color:#94a3b8;font-size:12px;text-align:center;padding:20px;">此欄位無有效數值</div>';
            return;
        }

        // Compute defaults
        const mean0 = nums.reduce((a, b) => a + b, 0) / nums.length;
        const std0  = Math.sqrt(nums.reduce((a, b) => a + (b - mean0) ** 2, 0) / nums.length);

        // Keep user-edited stats if they exist, else use computed defaults
        if (!_meTargetStats[_meCurrentTrendCol]) {
            _meTargetStats[_meCurrentTrendCol] = {
                mean: mean0,
                usl:  mean0 + 3 * std0,
                lsl:  mean0 - 3 * std0,
                std:  std0,
                n:    nums.length,
            };
        }
        const s = _meTargetStats[_meCurrentTrendCol];
        data.stats = s;
        _meTrendVals = vals;

        const inp = (label, domId, val, color) =>
            `<label style="display:flex;align-items:center;gap:3px;color:${color};font-size:11px;white-space:nowrap;">
                <span style="display:inline-block;width:14px;height:0;border-top:2px dashed ${color};"></span>
                <span>${label}:</span>
                <input id="${domId}" type="number" step="0.001" value="${val.toFixed(3)}"
                    oninput="meTrendStatsUpdate()"
                    style="width:72px;padding:1px 4px;border:1px solid ${color}44;border-radius:4px;font-size:11px;font-weight:600;color:${color};background:#fff;text-align:center;">
            </label>`;

        container.innerHTML = `
            <div style="position:absolute;top:0;left:0;right:0;bottom:38px;">
                <div style="position:relative;width:100%;height:100%;">
                    <canvas id="me-trend-canvas" style="position:absolute;top:0;left:0;width:100%;height:100%;display:block;"></canvas>
                </div>
            </div>
            <div style="position:absolute;left:0;right:0;bottom:0;height:38px;display:flex;align-items:center;gap:10px;padding:0 12px;background:#f8fafc;border-top:1px solid #e2e8f0;">
                <span style="font-size:11px;color:#64748b;white-space:nowrap;flex-shrink:0;">n=<b style="color:#1e293b;">${nums.length}</b></span>
                <div style="flex:1;display:flex;align-items:center;gap:8px;justify-content:flex-end;min-width:0;">
                    ${inp('Target', 'me-stat-target', s.mean, '#0d9488')}
                    ${inp('USL',    'me-stat-usl',    s.usl,  '#ef4444')}
                    ${inp('LSL',    'me-stat-lsl',    s.lsl,  '#ef4444')}
                </div>
            </div>`;

        _redrawCanvas();
    }

    // Redraw only the canvas using current _meTargetStats & _meTrendVals
    function _redrawCanvas() {
        const canvas = document.getElementById('me-trend-canvas');
        if (!canvas || !_meCurrentTrendCol) return;
        const s = _meTargetStats[_meCurrentTrendCol];
        if (!s) return;
        const vals = _meTrendVals;
        const mean = s.mean;
        const usl  = s.usl  ?? s.ucl;
        const lsl  = s.lsl  ?? s.lcl;
        const nums = vals.filter(v => v != null);
        const n = vals.length;

        const chartDiv = canvas.parentElement;
        const dpr0 = window.devicePixelRatio || 1;
        const w0   = chartDiv.clientWidth  || 400;
        const h0   = chartDiv.clientHeight || 160;
        canvas.width  = w0 * dpr0;
        canvas.height = h0 * dpr0;
        canvas.style.width  = w0 + 'px';
        canvas.style.height = h0 + 'px';

        const ctx = canvas.getContext('2d');
        ctx.scale(dpr0, dpr0);
        const w = w0, h = h0;
        const pad = { t: 18, r: 52, b: 30, l: 52 };
        const cw = w - pad.l - pad.r, ch = h - pad.t - pad.b;

        const dataMin = Math.min(...nums), dataMax = Math.max(...nums);
        let vMin = Math.min(dataMin, lsl, mean);
        let vMax = Math.max(dataMax, usl, mean);
        const range = vMax - vMin || 1;
        vMin -= range * 0.08; vMax += range * 0.08;
        const totalRange = vMax - vMin;
        const sx = i => pad.l + (i / (n - 1 || 1)) * cw;
        const sy = v => pad.t + ch - ((v - vMin) / totalRange) * ch;

        ctx.clearRect(0, 0, w, h);

        // Grid
        ctx.strokeStyle = '#f1f5f9'; ctx.lineWidth = 1;
        for (let i = 0; i <= 5; i++) {
            const y = pad.t + (ch / 5) * i;
            ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(pad.l + cw, y); ctx.stroke();
        }
        // Y axis labels
        ctx.fillStyle = '#94a3b8'; ctx.font = '10px Arial'; ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
        for (let i = 0; i <= 5; i++) {
            const v = vMax - (totalRange / 5) * i;
            ctx.fillText(v.toFixed(2), pad.l - 4, pad.t + (ch / 5) * i);
        }
        // X axis labels
        ctx.textAlign = 'center'; ctx.textBaseline = 'top';
        [0, Math.floor(n / 4), Math.floor(n / 2), Math.floor(n * 3 / 4), n - 1].forEach(i => {
            if (i >= 0 && i < n) ctx.fillText(i, sx(i), pad.t + ch + 4);
        });

        // Dots (drawn first so lines appear on top)
        ctx.lineWidth = 0.5;
        vals.forEach((v, i) => {
            if (v == null) return;
            const oos = v > usl || v < lsl;
            ctx.fillStyle   = oos ? '#fca5a5' : '#93c5fd';
            ctx.strokeStyle = oos ? '#ef4444' : '#2563eb';
            ctx.beginPath(); ctx.arc(sx(i), sy(v), 2.5, 0, Math.PI * 2);
            ctx.fill(); ctx.stroke();
        });

        // Reference lines (drawn last so they appear above dots)
        const drawRef = (v, color, label) => {
            if (v < vMin || v > vMax) return;
            const y = sy(v);
            ctx.save();
            ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.setLineDash([6, 3]);
            ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(pad.l + cw, y); ctx.stroke();
            ctx.setLineDash([]);
            ctx.fillStyle = color; ctx.font = 'bold 10px Arial';
            ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
            ctx.fillText(label, pad.l + cw + 4, y);
            ctx.restore();
        };
        drawRef(usl,  '#ef4444', 'USL');
        drawRef(lsl,  '#ef4444', 'LSL');
        drawRef(mean, '#0d9488', 'Target');
    }

    // Called when user edits Target/USL/LSL inputs in trend stats bar
    window.meTrendStatsUpdate = function () {
        if (!_meCurrentTrendCol || !_meTargetStats[_meCurrentTrendCol]) return;
        const mean = parseFloat(document.getElementById('me-stat-target')?.value);
        const usl  = parseFloat(document.getElementById('me-stat-usl')?.value);
        const lsl  = parseFloat(document.getElementById('me-stat-lsl')?.value);
        if (isNaN(mean) || isNaN(usl) || isNaN(lsl)) return;
        Object.assign(_meTargetStats[_meCurrentTrendCol], { mean, usl, lsl, target_mean: mean });
        // Sync with chip inputs if visible
        _syncChipInputs(_meCurrentTrendCol, mean, usl, lsl);
        _redrawCanvas();
        _refreshStep3Cells(_meCurrentTrendCol);
    };

    // ============ STEP 1: TARGET MANAGEMENT ============
    window.meAddTarget = function () {
        const sel = document.getElementById('me-target-select');
        if (!sel) return;
        const col = sel.value;
        if (!col) { alert('請先選擇一個欄位'); return; }
        if (_meTargets.find(t => t.col === col)) { alert(`${col} 已加入`); return; }
        // Snapshot any user-edited stats before leaving this column
        _snapshotStats();
        const defaultWeight = parseFloat((1 / (_meTargets.length + 1)).toFixed(2));
        _meTargets.push({ col, weight: defaultWeight });
        _normalizeWeights();
        // Reset the select box to default and clear trend
        sel.value = '';
        _meCurrentTrendCol = null;
        const chartArea = document.getElementById('me-trend-area');
        if (chartArea) chartArea.innerHTML = '<div style="color:#94a3b8;font-size:12px;text-align:center;">選擇目標後顯示數據趨勢</div>';
        _renderTargetChips();
        _renderFactorLists(); // Remove this col from control/bg lists immediately
        _updateRunBtn();
    };

    // Save editable input values back to _meTargetStats
    function _snapshotStats() {
        if (!_meCurrentTrendCol) return;
        const mean = parseFloat(document.getElementById('me-stat-target')?.value);
        const usl  = parseFloat(document.getElementById('me-stat-usl')?.value);
        const lsl  = parseFloat(document.getElementById('me-stat-lsl')?.value);
        if (!isNaN(mean) && !isNaN(usl) && !isNaN(lsl)) {
            if (_meTargetStats[_meCurrentTrendCol])
                Object.assign(_meTargetStats[_meCurrentTrendCol], { mean, usl, lsl });
        }
    }

    // Sync chip inline inputs for a given col (without re-rendering chips)
    function _syncChipInputs(col, mean, usl, lsl) {
        const chip = document.querySelector(`[data-chip-col="${CSS.escape(col)}"]`);
        if (!chip) return;
        const t = chip.querySelector('[data-field="mean"]'); if (t) t.value = mean.toFixed(3);
        const u = chip.querySelector('[data-field="usl"]');  if (u) u.value = usl.toFixed(3);
        const l = chip.querySelector('[data-field="lsl"]');  if (l) l.value = lsl.toFixed(3);
    }

    // Click a chip to show its trend
    window.meChipClick = function (col) {
        _snapshotStats();
        _meCurrentTrendCol = col;
        const sel = document.getElementById('me-target-select');
        if (sel) sel.value = col;
        _loadTrend(col);
        _renderTargetChips();
    };

    // Called when user edits Target/USL/LSL inputs inside a chip
    window.meChipStatsUpdate = function (el) {
        const chip = el.closest('[data-chip-col]');
        if (!chip) return;
        const col   = chip.getAttribute('data-chip-col');
        const field = el.getAttribute('data-field');
        const v = parseFloat(el.value);
        if (isNaN(v) || !col || !field) return;
        if (!_meTargetStats[col]) _meTargetStats[col] = {};
        _meTargetStats[col][field] = v;
        if (field === 'mean') _meTargetStats[col].target_mean = v;
        // If this col is currently displayed in the trend chart, sync & redraw
        if (_meCurrentTrendCol === col) {
            const idMap = { mean: 'me-stat-target', usl: 'me-stat-usl', lsl: 'me-stat-lsl' };
            const trendEl = document.getElementById(idMap[field]);
            if (trendEl) trendEl.value = el.value;
            _redrawCanvas();
        }
        _refreshStep3Cells(col);
    };

    // Redraw all Step 3 cells for a given target column after spec changes
    function _refreshStep3Cells(col) {
        if (!_meRenderCtx) return;
        const { factorOrder, targetOrder, byTarget, targetYRange } = _meRenderCtx;
        const ti = targetOrder.indexOf(col);
        if (ti < 0) return;

        // Recompute Y range using updated ts.mean (aleOffset may have changed)
        const ts = _meTargetStats[col] || {};
        const analysisMethod = _meRenderCtx.analysisMethod || 'ale';
        const aleOffset = analysisMethod === 'ale' ? (ts.mean || 0) : 0;
        let vals = [];
        factorOrder.forEach(f => {
            const d = byTarget[col]?.[f];
            if (d?.ale) vals = vals.concat(d.ale.filter(v => v != null).map(v => v + aleOffset));
        });
        if (ts.usl != null) vals.push(ts.usl);
        if (ts.lsl != null) vals.push(ts.lsl);
        if (ts.ucl != null) vals.push(ts.ucl);
        if (ts.lcl != null) vals.push(ts.lcl);
        if (ts.target_mean != null) vals.push(ts.target_mean);
        if (ts.mean != null) vals.push(ts.mean);
        if (vals.length) {
            const mn = Math.min(...vals), mx = Math.max(...vals);
            const margin = (mx - mn) * 0.12 || 1;
            targetYRange[col] = { min: mn - margin, max: mx + margin };
        }

        factorOrder.forEach((factor, fi) => {
            const d = byTarget[col]?.[factor];
            if (d) _drawCell(ti, fi, factor, col, d, targetYRange[col]);
        });
    }

    window.meRemoveTarget = function (col) {
        _meTargets = _meTargets.filter(t => t.col !== col);
        _normalizeWeights();
        _renderTargetChips();
        _updateRunBtn();
    };

    window.meWeightChange = function (col, val) {
        const t = _meTargets.find(t => t.col === col);
        if (t) t.weight = parseFloat(val) || 0;
    };

    function _normalizeWeights() {
        if (_meTargets.length === 0) return;
        const equal = parseFloat((1 / _meTargets.length).toFixed(3));
        _meTargets.forEach(t => t.weight = equal);
    }

    function _renderTargetChips() {
        const container = document.getElementById('me-target-chips');
        if (!container) return;
        if (_meTargets.length === 0) {
            container.innerHTML = '<div style="color:#94a3b8;font-size:12px;padding:8px 0;">尚未選擇任何 Target</div>';
            return;
        }
        container.innerHTML = _meTargets.map((t, i) => {
            const color = TARGET_COLORS[i % TARGET_COLORS.length];
            const active = t.col === _meCurrentTrendCol;
            const s = _meTargetStats[t.col];

            const chipInp = (label, field, val, clr) =>
                `<label onclick="event.stopPropagation()" style="display:flex;align-items:center;gap:2px;font-size:10px;color:${clr};white-space:nowrap;">
                    ${label}:
                    <input type="number" step="0.001" value="${val.toFixed(3)}"
                        data-field="${field}"
                        onclick="event.stopPropagation()"
                        oninput="event.stopPropagation();meChipStatsUpdate(this)"
                        style="width:66px;padding:1px 4px;border:1px solid ${clr}55;border-radius:3px;font-size:10px;font-weight:600;color:${clr};background:#fff;text-align:center;">
                </label>`;

            const statsRow = s
                ? `<div style="display:flex;gap:8px;margin-top:5px;flex-wrap:wrap;">
                       ${chipInp('Target', 'mean', s.mean, '#0d9488')}
                       ${chipInp('USL',    'usl',  s.usl,  '#ef4444')}
                       ${chipInp('LSL',    'lsl',  s.lsl,  '#ef4444')}
                   </div>`
                : `<div style="font-size:10px;color:#94a3b8;margin-top:4px;">點擊查看趨勢後可設定規格</div>`;

            return `<div onclick="meChipClick('${t.col}')"
                data-chip-col="${t.col}"
                style="cursor:pointer;display:flex;flex-direction:column;padding:8px 12px;
                       background:${active ? '#eff6ff' : '#f8fafc'};
                       border:1px solid ${active ? '#3b82f6' : '#e2e8f0'};
                       border-radius:8px;border-left:4px solid ${color};
                       transition:background 0.15s,border-color 0.15s;">
                <div style="display:flex;align-items:center;gap:8px;">
                    <span style="font-size:13px;font-weight:600;color:#1e293b;flex:1;">${t.col}</span>
                    <label onclick="event.stopPropagation()" style="font-size:11px;color:#64748b;flex-shrink:0;">權重</label>
                    <input type="number" onclick="event.stopPropagation()" min="0" max="1" step="0.1" value="${t.weight.toFixed(2)}"
                        onchange="meWeightChange('${t.col}', this.value)"
                        style="width:52px;padding:2px 5px;border:1px solid #cbd5e1;border-radius:4px;font-size:12px;text-align:center;flex-shrink:0;">
                    <button onclick="event.stopPropagation();meRemoveTarget('${t.col}')"
                        style="background:none;border:none;color:#94a3b8;cursor:pointer;font-size:14px;padding:0 2px;flex-shrink:0;">✕</button>
                </div>
                ${statsRow}
            </div>`;
        }).join('');
    }

    // ============ STEP 2: FACTOR SUB-TABS ============
    window.meSwitchSubTab = function (tab) {
        ['algo', 'control', 'bg'].forEach(t => {
            const btn  = document.getElementById('me-subtab-' + t);
            const pane = document.getElementById('me-subtab-pane-' + t);
            if (btn) {
                const active = t === tab;
                btn.style.background = active ? '#2563eb' : '#fff';
                btn.style.color      = active ? '#fff'    : '#64748b';
                // Update badge colours inside the button
                const badge = btn.querySelector('span');
                if (badge) {
                    badge.style.background = active ? 'rgba(255,255,255,0.25)' : '#e2e8f0';
                    badge.style.color      = active ? '#fff' : '#475569';
                }
            }
            if (pane) pane.style.display = t === tab ? 'flex' : 'none';
        });
    };

    window.meAlgorithmChange = function (val) {
        _meAlgorithm = val;
        _renderAlgoParams();
    };

    function _renderAlgoParams() {
        const area = document.getElementById('me-algo-params');
        if (!area) return;
        if (_meAlgorithm === 'xgboost') {
            area.innerHTML = `
                <div class="me-param-grid">
                    <div class="me-param-item">
                        <label>樹的數量 (N_ESTIMATORS)</label>
                        <input type="number" value="100" min="10" max="1000" id="me-hp-n_estimators">
                    </div>
                    <div class="me-param-item">
                        <label>最大深度 (MAX DEPTH)</label>
                        <input type="number" value="4" min="1" max="10" id="me-hp-max_depth">
                    </div>
                    <div class="me-param-item">
                        <label>學習率 (LR)</label>
                        <input type="number" value="0.1" min="0.001" max="1" step="0.001" id="me-hp-learning_rate">
                    </div>
                    <div class="me-param-item">
                        <label>子採樣比 (SUBSAMPLE)</label>
                        <input type="number" value="0.8" min="0.1" max="1" step="0.1" id="me-hp-subsample">
                    </div>
                </div>`;
        } else {  // pls
            area.innerHTML = `
                <div class="me-param-grid">
                    <div class="me-param-item">
                        <label>潛在成分數 (N_COMPONENTS)</label>
                        <input type="number" value="5" min="1" max="30" id="me-hp-n_components">
                    </div>
                </div>`;
        }
    }

    function _collectHyperparams() {
        _meHyperparams = {};
        if (_meAlgorithm === 'xgboost') {
            ['n_estimators', 'max_depth', 'learning_rate', 'subsample'].forEach(k => {
                const el = document.getElementById('me-hp-' + k);
                if (el) _meHyperparams[k] = parseFloat(el.value);
            });
        } else {
            const el = document.getElementById('me-hp-n_components');
            if (el) _meHyperparams['n_components'] = parseInt(el.value);
        }
    }

    // ============ FACTOR DUAL-LIST ============
    function _renderFactorLists() {
        // Remove target columns from selected factor lists (targets can't be factors)
        const targetCols = new Set(_meTargets.map(t => t.col));
        _meControlFactors = _meControlFactors.filter(c => !targetCols.has(c));
        _meBgFactors      = _meBgFactors.filter(c => !targetCols.has(c));

        const excluded = new Set([
            ..._meTargets.map(t => t.col),
            ..._meControlFactors,
            ..._meBgFactors,
        ]);
        const available = _meAllCols.filter(c => !excluded.has(c));

        // Sort both available lists by smart score if available
        const hasScores = Object.keys(_smartScores).length > 0;
        const availSorted = hasScores
            ? [...available].sort((a, b) => (_smartScores[b] ?? -1) - (_smartScores[a] ?? -1))
            : available;
        _renderList('me-avail-control', availSorted, 'me-ctrl-preview', 'me-sel-control', hasScores ? _smartScores : null);
        _renderList('me-avail-bg',      availSorted, 'me-bg-preview',   'me-sel-bg',      hasScores ? _smartScores : null);
        _renderList('me-sel-control',   _meControlFactors, 'me-ctrl-preview', 'me-avail-control');
        _renderList('me-sel-bg',        _meBgFactors,      'me-bg-preview',   'me-avail-bg');

        const cntEl = document.getElementById('me-control-count');
        if (cntEl) cntEl.textContent = _meControlFactors.length;
        const bgEl = document.getElementById('me-bg-count');
        if (bgEl) bgEl.textContent = _meBgFactors.length;
        const ctrlBadge = document.getElementById('me-sel-control-badge');
        if (ctrlBadge) ctrlBadge.textContent = _meControlFactors.length;
        const bgBadge = document.getElementById('me-sel-bg-badge');
        if (bgBadge) bgBadge.textContent = _meBgFactors.length;
        const hasS = Object.keys(_smartScores).length > 0;
        ['me-smart-clear-btn', 'me-smart-clear-btn-ctrl'].forEach(id => {
            const btn = document.getElementById(id);
            if (btn) btn.style.display = hasS ? 'inline-block' : 'none';
        });
    }

    // Track last-clicked index per list for shift-range selection
    const _listLastClick = {};

    // ============ COLUMN DISTRIBUTION PREVIEW ============
    async function _showColPreview(col, containerId) {
        const container = document.getElementById(containerId);
        if (!container) return;
        container.innerHTML = '<span style="font-size:11px;color:#94a3b8;">⏳ 載入...</span>';

        try {
            const sid = typeof getSessionId === 'function' ? getSessionId() : 'default';
            const filters = (typeof _activeDataset !== 'undefined' && _activeDataset?.filters) ?
                _activeDataset.filters.map(f => ({
                    column: f.col, keyword: '==' + String(f.value || ''), exclude_empty: false
                })) : [];
            const excludeIndices = (typeof _clOutlierIndices !== 'undefined') ? _clOutlierIndices : [];
            const excludeCols    = (typeof _clExcludedCols   !== 'undefined') ? _clExcludedCols   : [];
            const url = `/api/data-prep/gb-column-values?file_id=${currentFileId}&column=${encodeURIComponent(col)}&session_id=${sid}&filters=${encodeURIComponent(JSON.stringify(filters))}&exclude_indices=${encodeURIComponent(JSON.stringify(excludeIndices))}&exclude_cols=${encodeURIComponent(JSON.stringify(excludeCols))}`;

            const res  = await fetch(url);
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Failed');

            const vals = (data.values || []).filter(v => v != null);
            if (vals.length === 0) {
                container.innerHTML = '<span style="font-size:11px;color:#94a3b8;">無數值</span>';
                return;
            }

            // Y-axis: use 1st–99th percentile range to avoid outlier squish
            const sorted = [...vals].sort((a, b) => a - b);
            const p01 = sorted[Math.max(0, Math.floor(sorted.length * 0.01))];
            const p99 = sorted[Math.min(sorted.length - 1, Math.ceil(sorted.length * 0.99) - 1)];
            const pRange = (p99 - p01) || 1;
            const mn = p01 - pRange * 0.05;
            const mx = p99 + pRange * 0.05;

            // Keep container as flex column; use position:relative wrapper for canvas
            container.style.flexDirection = 'column';
            container.style.alignItems    = '';
            container.style.justifyContent = '';
            container.innerHTML = `
                <div style="flex:1;min-height:0;position:relative;">
                    <canvas id="${containerId}-canvas" style="position:absolute;top:0;left:0;width:100%;height:100%;display:block;"></canvas>
                </div>
                <div style="height:22px;flex-shrink:0;display:flex;align-items:center;justify-content:center;background:#f8fafc;border-top:1px solid #e2e8f0;gap:6px;">
                    <span style="font-size:10px;color:#475569;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:60%;">${col}</span>
                    <span style="font-size:10px;color:#94a3b8;flex-shrink:0;">n=${vals.length}</span>
                </div>`;

            const canvas = document.getElementById(containerId + '-canvas');
            if (!canvas) return;

            // Downsample for performance if too many points
            const MAX_PTS = 300;
            const step = vals.length > MAX_PTS ? Math.ceil(vals.length / MAX_PTS) : 1;
            const pts = [];
            for (let i = 0; i < vals.length; i += step) pts.push(vals[i]);

            const drawTrend = () => {
                const W = canvas.offsetWidth || 200;
                const H = canvas.offsetHeight || 120;
                if (W < 10 || H < 10) { requestAnimationFrame(drawTrend); return; }
                const dprT = window.devicePixelRatio || 1;
                canvas.width  = W * dprT;
                canvas.height = H * dprT;
                canvas.style.width  = W + 'px';
                canvas.style.height = H + 'px';

                const ctx = canvas.getContext('2d');
                ctx.scale(dprT, dprT);
                const pad = { t: 10, r: 8, b: 20, l: 34 };
                const cw = W - pad.l - pad.r, ch = H - pad.t - pad.b;
                const range = mx - mn || 1;

                ctx.clearRect(0, 0, W, H);

                // Grid lines
                ctx.strokeStyle = '#f1f5f9'; ctx.lineWidth = 1;
                for (let i = 0; i <= 4; i++) {
                    const y = pad.t + ch / 4 * i;
                    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(pad.l + cw, y); ctx.stroke();
                }

                // Trend line
                ctx.strokeStyle = '#3b82f6'; ctx.lineWidth = 1.5;
                ctx.lineJoin = 'round'; ctx.lineCap = 'round';
                ctx.beginPath();
                pts.forEach((v, i) => {
                    const x = pad.l + (i / (pts.length - 1 || 1)) * cw;
                    const y = pad.t + ch - ((v - mn) / range) * ch;
                    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
                });
                ctx.stroke();

                // Mean line
                const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
                const meanY = pad.t + ch - ((mean - mn) / range) * ch;
                ctx.strokeStyle = '#f97316'; ctx.lineWidth = 1; ctx.setLineDash([4, 3]);
                ctx.beginPath(); ctx.moveTo(pad.l, meanY); ctx.lineTo(pad.l + cw, meanY); ctx.stroke();
                ctx.setLineDash([]);

                // Y axis labels
                ctx.fillStyle = '#94a3b8'; ctx.font = '9px Arial';
                ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
                ctx.fillText(mx.toFixed(1), pad.l - 3, pad.t);
                ctx.fillText(mn.toFixed(1), pad.l - 3, pad.t + ch);

                // X axis labels
                ctx.textAlign = 'left'; ctx.textBaseline = 'top';
                ctx.fillText('1', pad.l, pad.t + ch + 3);
                ctx.textAlign = 'right';
                ctx.fillText(String(vals.length), pad.l + cw, pad.t + ch + 3);
            };
            requestAnimationFrame(drawTrend);
        } catch (e) {
            container.innerHTML = `<span style="font-size:10px;color:#ef4444;">❌ ${e.message}</span>`;
        }
    }

    function _renderList(elId, items, previewId, partnerId, scoreMap = null) {
        const el = document.getElementById(elId);
        if (!el) return;
        el.innerHTML = '';
        const maxScore = scoreMap ? Math.max(...Object.values(scoreMap).filter(v => v > 0), 1e-9) : 1;
        items.forEach((name, idx) => {
            const div = document.createElement('div');
            div.className = 'list-item rsm-pick-item';
            div.dataset.col = name;
            div.dataset.idx = idx;

            if (scoreMap && scoreMap[name] != null) {
                const score = scoreMap[name];
                const pct = Math.min((score / maxScore) * 100, 100).toFixed(1);
                div.style.display = 'flex';
                div.style.alignItems = 'center';
                div.style.gap = '6px';
                div.innerHTML = `
                    <div style="flex:1;min-width:0;">
                        <div style="font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${name}</div>
                        <div style="height:3px;background:#e2e8f0;border-radius:2px;margin-top:3px;">
                            <div style="height:100%;width:${pct}%;background:#7c3aed;border-radius:2px;"></div>
                        </div>
                    </div>
                    <span style="font-size:11px;color:#6d28d9;font-weight:600;flex-shrink:0;min-width:36px;text-align:right;">${score.toFixed(3)}</span>`;
            } else {
                div.textContent = name;
            }

            div.onclick = (e) => {
                // Clear partner list selection so only one side is highlighted at a time
                if (partnerId) {
                    const partner = document.getElementById(partnerId);
                    if (partner) partner.querySelectorAll('.rsm-pick-item.selected')
                        .forEach(i => i.classList.remove('selected'));
                }

                const allItems = Array.from(el.querySelectorAll('.rsm-pick-item'));
                if (e.shiftKey && _listLastClick[elId] != null) {
                    // Range select between last click and current
                    const from = Math.min(_listLastClick[elId], idx);
                    const to   = Math.max(_listLastClick[elId], idx);
                    allItems.forEach((item, i) => {
                        if (i >= from && i <= to) item.classList.add('selected');
                    });
                } else if (e.ctrlKey || e.metaKey) {
                    // Ctrl/Cmd: toggle single item, keep others
                    div.classList.toggle('selected');
                } else {
                    // Plain click: toggle single item (clear others)
                    const wasSelected = div.classList.contains('selected');
                    allItems.forEach(item => item.classList.remove('selected'));
                    if (!wasSelected) div.classList.add('selected');
                }
                _listLastClick[elId] = idx;
                // Show distribution preview on click
                if (previewId) _showColPreview(name, previewId);
            };

            div.ondblclick = () => {
                if (elId.startsWith('me-avail')) {
                    if (elId.includes('control')) _moveControl([name]);
                    else _moveBg([name]);
                } else {
                    if (elId.includes('control')) _removeControl([name]);
                    else _removeBg([name]);
                }
            };
            el.appendChild(div);
        });
    }

    function _getSelectedInList(elId) {
        const el = document.getElementById(elId);
        if (!el) return [];
        return Array.from(el.querySelectorAll('.rsm-pick-item.selected')).map(e => e.dataset.col);
    }

    function _moveControl(names) {
        names.forEach(n => { if (!_meControlFactors.includes(n)) _meControlFactors.push(n); });
        _renderFactorLists();
    }
    function _removeControl(names) {
        _meControlFactors = _meControlFactors.filter(n => !names.includes(n));
        _renderFactorLists();
    }
    function _moveBg(names) {
        names.forEach(n => { if (!_meBgFactors.includes(n)) _meBgFactors.push(n); });
        _renderFactorLists();
    }
    function _removeBg(names) {
        _meBgFactors = _meBgFactors.filter(n => !names.includes(n));
        _renderFactorLists();
    }

    window.meMoveToControl = function () { _moveControl(_getSelectedInList('me-avail-control')); };
    window.meRemoveFromControl = function () { _removeControl(_getSelectedInList('me-sel-control')); };
    window.meMoveAllToControl = function () {
        const all = Array.from(document.querySelectorAll('#me-avail-control .rsm-pick-item')).map(e => e.dataset.col);
        _moveControl(all);
    };
    window.meClearControl = function () { _meControlFactors = []; _renderFactorLists(); };

    window.meMoveToBg = function () { _moveBg(_getSelectedInList('me-avail-bg')); };
    window.meRemoveFromBg = function () { _removeBg(_getSelectedInList('me-sel-bg')); };

    // ============ SMART SELECT ============
    // col → score (shown in me-avail-bg list, cleared when list refreshes without scores)
    let _smartScores = {};   // { col: number }

    window.meOpenSmartModal = function () {
        if (!_meTargets || _meTargets.length === 0) {
            alert('請先選擇目標 Target');
            return;
        }
        const modal = document.getElementById('me-smart-modal');
        if (!modal) return;
        modal.style.display = 'flex';
        document.getElementById('me-smart-status').textContent = '';
        const runBtn = document.getElementById('me-smart-run-btn');
        runBtn.textContent = '開始智慧分析';
        runBtn.disabled = false;
        runBtn.onclick = window.meRunSmartAnalysis;
    };

    window.meCloseSmartModal = function () {
        const modal = document.getElementById('me-smart-modal');
        if (modal) modal.style.display = 'none';
    };

    window.meClearSmartScores = function () {
        _smartScores = {};
        _renderFactorLists();
    };

    window.meRunSmartAnalysis = async function () {
        const algo = (document.querySelector('input[name="me-smart-algo"]:checked') || {}).value || 'correlation';
        const statusEl = document.getElementById('me-smart-status');
        const runBtn = document.getElementById('me-smart-run-btn');

        statusEl.textContent = '⏳ 分析中，請稍候...';
        statusEl.style.color = '#7c3aed';
        runBtn.disabled = true;
        runBtn.textContent = '分析中...';

        try {
            const sid = typeof getSessionId === 'function' ? getSessionId() : 'default';
            const filters = (typeof _activeDataset !== 'undefined' && _activeDataset?.filters) ?
                _activeDataset.filters.map(f => ({ column: f.col, keyword: '==' + String(f.value || ''), exclude_empty: false })) : [];
            const excludeIndices = (typeof _clOutlierIndices !== 'undefined') ? _clOutlierIndices : [];
            const excludeCols    = (typeof _clExcludedCols   !== 'undefined') ? [..._clExcludedCols] : [];

            const res = await fetch(`/api/data-prep/smart-select?session_id=${sid}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    file_id: currentFileId,
                    target_columns: _meTargets.map(t => t.col),
                    target_weights: _meTargets.map(t => t.weight),
                    algorithm: algo,
                    filters,
                    exclude_indices: excludeIndices,
                    exclude_cols: excludeCols,
                }),
            });
            const data = await res.json();
            if (!res.ok) {
                const msg = typeof data.detail === 'string' ? data.detail
                    : Array.isArray(data.detail) ? data.detail.map(e => e.msg || JSON.stringify(e)).join('; ')
                    : JSON.stringify(data.detail);
                throw new Error(msg);
            }

            // Store scores and re-render lists
            _smartScores = {};
            (data.results || []).forEach(r => { _smartScores[r.col] = r.score; });

            _renderFactorLists();
            window.meCloseSmartModal();

        } catch (e) {
            statusEl.textContent = `❌ 失敗：${e.message}`;
            statusEl.style.color = '#ef4444';
            runBtn.textContent = '重試';
            runBtn.disabled = false;
        }
    };

    function _syncFactors() {
        // Already maintained in state
    }

    // Analysis method toggle
    window.meSetMethod = function (method) {
        _meAnalysisMethod = method;
        ['ale', 'pdp'].forEach(m => {
            const btn = document.getElementById('me-method-' + m);
            if (btn) {
                btn.style.background = m === method ? '#2563eb' : '#f1f5f9';
                btn.style.color = m === method ? '#fff' : '#64748b';
            }
        });
    };

    // ============ STEP 3: ANALYSIS ============
    async function meRunAnalysis() {
        if (_meTargets.length === 0) { alert('請選擇 Target'); meGotoStep(1); return; }
        _syncFactors();
        if (_meControlFactors.length === 0) { alert('請選擇控制參數'); meGotoStep(2); return; }

        _meSimResults = null;
        _collectHyperparams();
        meGotoStep(3);

        const resultArea = document.getElementById('me-step3-content');
        if (resultArea) resultArea.innerHTML = `
            <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;gap:16px;">
                <div style="font-size:36px;">⚙️</div>
                <div style="color:#3b82f6;font-size:15px;font-weight:700;">正在訓練模型並計算效應曲線...</div>
                <div style="color:#94a3b8;font-size:12px;">目標: ${_meTargets.map(t=>t.col).join(', ')} | 控制參數: ${_meControlFactors.length} 個</div>
                <div style="width:280px;height:8px;background:#f1f5f9;border-radius:6px;overflow:hidden;">
                    <div id="me-progress-bar" style="width:5%;height:100%;background:linear-gradient(90deg,#3b82f6,#6366f1);transition:width 0.4s;"></div>
                </div>
            </div>`;

        let progress = 5;
        const bar = () => { const el = document.getElementById('me-progress-bar'); if (el) el.style.width = (progress += 8) + '%'; };
        const pTimer = setInterval(bar, 400);

        try {
            const sid = typeof getSessionId === 'function' ? getSessionId() : 'default';
            const ds = typeof _activeDataset !== 'undefined' ? _activeDataset : null;
            const dsFilters = (ds && ds.filters || []).map(f => ({ column: f.col, keyword: '==' + String(f.value || ''), exclude_empty: false }));

            // Attach user-defined USL/LSL/Target to each target entry
            const targetsWithSpec = _meTargets.map(t => {
                const s = _meTargetStats[t.col] || {};
                return { ...t, usl: s.usl ?? null, lsl: s.lsl ?? null, target_mean: s.mean ?? null };
            });

            const body = {
                file_id: currentFileId,
                targets: targetsWithSpec,
                control_factors: _meControlFactors,
                background_factors: _meBgFactors,
                algorithm: _meAlgorithm,
                hyperparams: _meHyperparams,
                analysis_method: _meAnalysisMethod,
                filters: dsFilters,
                exclude_indices: typeof _clOutlierIndices !== 'undefined' ? _clOutlierIndices : [],
                exclude_cols: typeof _clExcludedCols !== 'undefined' ? [..._clExcludedCols] : [],
                grid_resolution: _meSettings.grid_resolution,
                max_scatter:     _meSettings.max_scatter,
            };

            const resp = await fetch(`/api/data-prep/main-effect?session_id=${sid}`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const data = await resp.json();
            if (!resp.ok) throw new Error(data.detail || '分析失敗');

            clearInterval(pTimer);
            _renderResults(data, resultArea);
        } catch (err) {
            clearInterval(pTimer);
            if (resultArea) resultArea.innerHTML = `
                <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;width:100%;height:100%;gap:12px;">
                    <div style="font-size:32px;">❌</div>
                    <div style="color:#ef4444;font-size:14px;font-weight:600;">分析失敗</div>
                    <div style="color:#64748b;font-size:12px;max-width:420px;text-align:center;">${err.message}</div>
                </div>`;
        }
    }

    // ── stored for redraw ──────────────────────────────────────────────
    let _meRenderCtx = null; // { factorOrder, targetOrder, byTarget, targetYRange }

    function _renderResults(data, container) {
        const { models, results, n_rows, algorithm } = data;
        _meColStats = data.col_stats || {};
        // Merge backend stats (ucl/lcl) into _meTargetStats, preserving user-set usl/lsl from Step 1
        Object.entries(data.target_stats || {}).forEach(([t, st]) => {
            if (!_meTargetStats[t]) _meTargetStats[t] = {};
            Object.assign(_meTargetStats[t], st);
            // Keep usl/lsl as aliases so _drawTrend/_redrawCanvas still work
            if (_meTargetStats[t].usl == null) _meTargetStats[t].usl = st.ucl;
            if (_meTargetStats[t].lsl == null) _meTargetStats[t].lsl = st.lcl;
        });

        // Slider initial values = median
        _meSliderVals = {};
        results.forEach(r => {
            const st = _meColStats[r.factor];
            _meSliderVals[r.factor] = st ? st.median : 0;
        });

        const factorOrder = results.map(r => r.factor);
        const targetOrder = models.map(m => m.target);
        const scatterData = data.scatter_data || {};
        const analysisMethod = data.analysis_method || 'ale';

        // Reorganise: byTarget[t][f] = {grid, ale}
        const byTarget = {};
        results.forEach(r => {
            r.effects.forEach(e => {
                if (!byTarget[e.target]) byTarget[e.target] = {};
                byTarget[e.target][r.factor] = { grid: e.grid, ale: e.ale };
            });
        });

        // Per-target Y range.
        // ALE values are relative (centered at 0); shift by data mean so they align with
        // absolute spec lines (USL/LSL) and scatter data.
        // PDP values are already absolute (model predictions), no shift needed.
        const targetYRange = {};
        targetOrder.forEach(t => {
            const ts = _meTargetStats[t] || {};
            const aleOffset = analysisMethod === 'ale' ? (ts.mean || 0) : 0;
            let vals = [];
            factorOrder.forEach(f => {
                const d = byTarget[t]?.[f];
                if (d?.ale) vals = vals.concat(d.ale.filter(v => v != null).map(v => v + aleOffset));
            });
            if (ts.usl != null) vals.push(ts.usl);
            if (ts.lsl != null) vals.push(ts.lsl);
            if (ts.ucl != null) vals.push(ts.ucl);
            if (ts.lcl != null) vals.push(ts.lcl);
            if (ts.target_mean != null) vals.push(ts.target_mean);
            if (ts.mean != null) vals.push(ts.mean);
            if (vals.length === 0) vals = [0, 1];
            const rawMin = Math.min(...vals), rawMax = Math.max(...vals);
            const pad12  = (rawMax - rawMin) * 0.12 || 1;
            targetYRange[t] = { min: rawMin - pad12, max: rawMax + pad12 };
        });

        // Store a deep copy of the base y-range (without ale_pred) for dynamic expansion
        const targetBaseYRange = {};
        targetOrder.forEach(t => {
            targetBaseYRange[t] = { min: targetYRange[t].min, max: targetYRange[t].max };
        });

        _meRenderCtx = { factorOrder: [...factorOrder], targetOrder, byTarget, targetYRange, targetBaseYRange, scatterData, analysisMethod, container, algorithm, n_rows };

        _buildGrid();
    }

    // ── Build / rebuild the result grid from _meRenderCtx ─────────────
    function _buildGrid() {
        const { factorOrder, targetOrder, byTarget, targetYRange, container, algorithm, n_rows } = _meRenderCtx;
        const N = factorOrder.length;

        // ── Slider style (injected once) ──────────────────────────────
        const sliderStyle = `
            <style id="me-sl-style">
            .me-sl{-webkit-appearance:none;appearance:none;background:transparent;cursor:pointer;width:100%;margin:0;}
            .me-sl::-webkit-slider-runnable-track{height:3px;background:#e2e8f0;border-radius:2px;}
            .me-sl::-webkit-slider-thumb{-webkit-appearance:none;width:14px;height:14px;border-radius:50%;background:#3b82f6;margin-top:-5.5px;cursor:pointer;box-shadow:0 1px 3px rgba(0,0,0,.25);}
            .me-sl::-moz-range-track{height:3px;background:#e2e8f0;border-radius:2px;}
            .me-sl::-moz-range-thumb{width:14px;height:14px;border-radius:50%;background:#3b82f6;border:none;cursor:pointer;}
            </style>`;

        // ── Target rows ───────────────────────────────────────────────
        const hasSim = !!((_meSimResults?.data?.targets));
        const SIM_COL_W = 72;
        const targetRows = targetOrder.map((t, ti) => {
            const clr = TARGET_COLORS[ti % TARGET_COLORS.length];
            const labelCell = `
                <div style="padding:4px 6px;border-right:2px solid #e2e8f0;border-bottom:1px solid #f1f5f9;
                            display:flex;flex-direction:column;justify-content:center;align-items:flex-start;
                            gap:3px;background:#fafafa;min-width:0;overflow:hidden;
                            position:sticky;left:0;z-index:3;">
                    <div style="font-size:9px;font-weight:700;color:${clr};word-break:break-all;line-height:1.3;">${t}</div>
                    <div id="me-pred-${ti}" style="font-size:13px;font-weight:700;color:#ef4444;">—</div>
                    <button onclick="meSortByTarget(${ti})" title="按此目標排序"
                        style="font-size:8px;color:#6366f1;background:none;border:1px solid #c7d2fe;border-radius:3px;
                               padding:1px 4px;cursor:pointer;line-height:1.4;margin-top:1px;">↓ 排序</button>
                </div>`;
            const chartCells = factorOrder.map((_, fi) =>
                `<div style="border-bottom:1px solid #e2e8f0;border-left:2px solid ${fi%2===0?'#d1d5db':'#e2e8f0'};height:${_meCellHeight}px;position:relative;background:#fff;"
                     onmouseenter="this.querySelector('.me-zoom-btn').style.opacity='1'"
                     onmouseleave="this.querySelector('.me-zoom-btn').style.opacity='0'">
                    <canvas id="me-c-${ti}-${fi}" style="width:100%;height:100%;display:block;cursor:col-resize;"
                        onmousedown="meCellDragStart(event,${fi})"
                        ontouchstart="meCellDragStart(event,${fi})"></canvas>
                    <button class="me-zoom-btn" onclick="meZoomCell(${ti},${fi})"
                        style="position:absolute;top:3px;right:3px;width:18px;height:18px;border:none;border-radius:3px;
                               background:rgba(99,102,241,0.85);color:#fff;font-size:10px;cursor:pointer;
                               display:flex;align-items:center;justify-content:center;opacity:0;
                               transition:opacity 0.15s;z-index:2;padding:0;line-height:1;">⛶</button>
                </div>`
            ).join('');
            const simCell = hasSim ? `<div style="border-bottom:1px solid #e2e8f0;border-left:2px solid #a855f7;height:${_meCellHeight}px;background:#fdf4ff;position:relative;"
                     onmouseenter="this.querySelector('.me-sim-zoom-btn').style.opacity='1'"
                     onmouseleave="this.querySelector('.me-sim-zoom-btn').style.opacity='0'">
                <canvas id="me-sim-col-${ti}" style="width:100%;height:100%;display:block;"></canvas>
                <button class="me-sim-zoom-btn" onclick="meZoomSimCell(${ti})"
                    style="position:absolute;top:3px;right:3px;width:18px;height:18px;border:none;border-radius:3px;
                           background:rgba(168,85,247,0.85);color:#fff;font-size:10px;cursor:pointer;
                           display:flex;align-items:center;justify-content:center;opacity:0;
                           transition:opacity 0.15s;z-index:2;padding:0;line-height:1;">⛶</button>
            </div>` : '';
            return labelCell + chartCells + simCell;
        }).join('');

        // ── Bottom row: slider + value + factor name ───────────────────
        const bottomLeft = `
            <div style="padding:4px 6px;border-right:2px solid #e2e8f0;display:flex;flex-direction:column;
                        align-items:center;justify-content:center;background:#f8fafc;gap:2px;
                        position:sticky;left:0;z-index:3;">
                <div style="font-size:8px;color:#94a3b8;font-weight:700;">${algorithm.toUpperCase()}</div>
                <div style="font-size:8px;color:#94a3b8;">${n_rows}筆</div>
                <div id="me-pred-status" style="font-size:9px;color:#94a3b8;"></div>
            </div>`;

        const bottomCells = factorOrder.map((f, fi) => {
            const st  = _meColStats[f] || { min: 0, max: 1, median: 0.5 };
            const cur = _meSliderVals[f] ?? st.median;
            const stp = ((st.max - st.min) / 200) || 0.001;
            const fixed = _meFixedFactors.has(f);
            return `<div style="padding:4px 6px 5px;border-left:2px solid ${fi%2===0?'#d1d5db':'#e2e8f0'};background:${fi%2===0?'#f1f5f9':'#f8fafc'};
                                display:flex;flex-direction:column;align-items:center;gap:3px;">
                <input type="number" id="me-sv-${fi}"
                    value="${cur.toFixed(4)}" step="${stp}"
                    min="${st.min}" max="${st.max}"
                    ${fixed ? 'disabled' : ''}
                    onchange="meSliderChange2(${fi},+this.value)"
                    style="width:90%;border:1px solid #cbd5e1;border-radius:5px;padding:3px 5px;
                           font-size:12px;font-weight:700;color:#3b82f6;text-align:center;
                           background:${fixed ? '#f1f5f9' : '#fff'};outline:none;
                           -moz-appearance:textfield;"
                    title="拖曳上方圖形或直接輸入數值 (${st.min.toFixed(3)} ~ ${st.max.toFixed(3)})">
                <div style="font-size:8px;color:#475569;text-align:center;line-height:1.2;
                            word-break:break-all;max-width:100%;">${f}</div>
                <div id="me-xspec-lbl-${fi}" style="font-size:9px;text-align:center;line-height:1.4;display:flex;gap:3px;justify-content:center;flex-wrap:wrap;">${_meXSpecLabelHtml(f)}</div>
            </div>`;
        }).join('');

        // ── Histogram row ──────────────────────────────────────────────
        const histLeft = `<div style="border-right:2px solid #e2e8f0;border-top:1px solid #f1f5f9;background:#fafafa;height:${Math.round(_meCellHeight * 0.4)}px;position:sticky;left:0;z-index:3;"></div>`;
        const histH = Math.round(_meCellHeight * 0.4);
        const histCells = factorOrder.map((_f, fi) =>
            `<div style="border-left:2px solid ${fi%2===0?'#d1d5db':'#e2e8f0'};border-top:1px solid #e2e8f0;height:${histH}px;background:#fff;position:relative;">
                <canvas id="me-hist-${fi}" style="width:100%;height:100%;display:block;"></canvas>
            </div>`
        ).join('');

        const bgBar = '';
        const simHistCell = hasSim ? `<div style="border-left:2px solid #a855f7;border-top:1px solid #e2e8f0;height:${histH}px;background:#fdf4ff;"></div>` : '';
        const simBottomCell = hasSim ? `<div style="border-left:2px solid #a855f7;background:#f5f3ff;display:flex;align-items:center;justify-content:center;">
            <button onclick="meShowAnalysisPanel('simulate')"
                style="font-size:10px;color:#fff;background:#8b5cf6;border:none;border-radius:5px;
                       padding:4px 10px;cursor:pointer;font-weight:700;">🎲 模擬</button>
        </div>` : '';

        // ── Assemble ───────────────────────────────────────────────────
        const minCellW = Math.max(100, Math.round(_meCellHeight * 1.35));
        const gridCols = `70px repeat(${N}, ${minCellW}px)${hasSim ? ` ${SIM_COL_W}px` : ''}`;
        const minW     = 70 + N * minCellW + (hasSim ? SIM_COL_W : 0);

        const TOOLBAR_H = 38;
        container.innerHTML = `
            ${sliderStyle}
            <div style="position:absolute;inset:0;">
                <div style="position:absolute;top:0;left:0;right:0;height:${TOOLBAR_H}px;
                            background:#f8fafc;border-bottom:1px solid #e2e8f0;
                            display:flex;align-items:center;gap:10px;flex-wrap:nowrap;overflow-x:auto;padding:0 10px;box-sizing:border-box;z-index:4;">
                    <button onclick="meShowSettings()"
                        style="font-size:11px;background:#fff;color:#475569;border:1px solid #e2e8f0;border-radius:5px;
                               padding:3px 10px;cursor:pointer;font-weight:600;flex-shrink:0;">⚙ 設定</button>
                    <button onclick="meShowAnalysisPanel('params')"
                        style="font-size:11px;background:#6366f1;color:#fff;border:none;border-radius:5px;
                               padding:3px 10px;cursor:pointer;font-weight:600;flex-shrink:0;">⚙ 參數</button>
                    <button onclick="meShowAnalysisPanel('optimize')"
                        style="font-size:11px;background:#10b981;color:#fff;border:none;border-radius:5px;
                               padding:3px 10px;cursor:pointer;font-weight:600;flex-shrink:0;">⚡ 最佳化</button>
                    <button onclick="meShowAnalysisPanel('simulate')"
                        style="font-size:11px;background:#8b5cf6;color:#fff;border:none;border-radius:5px;
                               padding:3px 10px;cursor:pointer;font-weight:600;flex-shrink:0;">🎲 量測模擬</button>
                    <label style="font-size:11px;color:#475569;display:flex;align-items:center;gap:4px;cursor:pointer;flex-shrink:0;">
                        <input type="checkbox" id="me-show-real-data" ${_meShowRealData ? 'checked' : ''}
                            onchange="meToggleRealData(this.checked)"
                            style="width:12px;height:12px;cursor:pointer;">
                        真實資料
                    </label>
                    <div style="display:flex;align-items:center;gap:5px;margin-left:6px;border-left:1px solid #e2e8f0;padding-left:10px;flex-shrink:0;">
                        <span style="font-size:11px;color:#64748b;">圖高</span>
                        <button onclick="meCellSizeStep(-20)"
                            style="width:22px;height:22px;border:1px solid #e2e8f0;border-radius:4px;background:#fff;
                                   font-size:14px;cursor:pointer;color:#475569;line-height:1;padding:0;">−</button>
                        <input type="range" id="me-cell-height-slider" min="60" max="260" step="1"
                            value="${_meCellHeight}" oninput="meCellSizeSet(+this.value)"
                            style="width:80px;cursor:pointer;accent-color:#6366f1;">
                        <button onclick="meCellSizeStep(10)"
                            style="width:22px;height:22px;border:1px solid #e2e8f0;border-radius:4px;background:#fff;
                                   font-size:14px;cursor:pointer;color:#475569;line-height:1;padding:0;">+</button>
                        <input type="number" id="me-cell-height-label" min="60" max="260"
                            value="${_meCellHeight}"
                            onchange="meCellSizeSet(+this.value)"
                            style="width:46px;border:1px solid #e2e8f0;border-radius:4px;padding:2px 4px;
                                   font-size:11px;color:#475569;text-align:center;-moz-appearance:textfield;">
                        <span style="font-size:11px;color:#94a3b8;">px</span>
                    </div>
                    <div style="display:flex;align-items:center;gap:4px;margin-left:6px;border-left:1px solid #e2e8f0;padding-left:10px;flex-shrink:0;">
                        <button onclick="document.getElementById('me-chart-scroll').scrollBy({left:-300,behavior:'smooth'})"
                            style="width:26px;height:22px;border:1px solid #e2e8f0;border-radius:4px;background:#fff;
                                   font-size:13px;cursor:pointer;color:#475569;line-height:1;padding:0;">◀</button>
                        <button onclick="document.getElementById('me-chart-scroll').scrollBy({left:300,behavior:'smooth'})"
                            style="width:26px;height:22px;border:1px solid #e2e8f0;border-radius:4px;background:#fff;
                                   font-size:13px;cursor:pointer;color:#475569;line-height:1;padding:0;">▶</button>
                    </div>
                </div>
                <div id="me-chart-scroll" style="position:absolute;top:${TOOLBAR_H}px;left:0;right:0;bottom:0;overflow:auto;">
                    <div style="display:grid;grid-template-columns:${gridCols};width:${minW}px;">
                        ${targetRows}
                        ${histLeft}${histCells}${simHistCell}
                        ${bottomLeft}
                        ${bottomCells}${simBottomCell}
                        ${bgBar}
                    </div>
                </div>
            </div>`;

        // Draw all cells + histograms
        targetOrder.forEach((t, ti) => {
            factorOrder.forEach((f, fi) => {
                const d = byTarget[t]?.[f];
                if (d) requestAnimationFrame(() => _drawCell(ti, fi, f, t, d, targetYRange[t]));
            });
        });
        factorOrder.forEach((f, fi) => requestAnimationFrame(() => _drawHistCell(fi, f)));

        if (hasSim) {
            targetOrder.forEach((t, ti) => {
                requestAnimationFrame(() => _drawSimColCell(ti, t, targetYRange[t]));
            });
        }

        _updatePredictions();
    }

    function _meXSpecLabelHtml(factor) {
        const ps = _meParamSpecs[factor] || {};
        const fmt = v => Math.abs(v) >= 100 ? v.toFixed(1) : Math.abs(v) >= 1 ? v.toFixed(2) : v.toFixed(3);
        const parts = [];
        if (ps.usl != null) parts.push(`<span style="color:#f97316;font-weight:700;">U:${fmt(ps.usl)}</span>`);
        if (ps.lsl != null) parts.push(`<span style="color:#0891b2;font-weight:700;">L:${fmt(ps.lsl)}</span>`);
        return parts.join('');
    }

    function _updateXSpecLabels() {
        if (!_meRenderCtx) return;
        _meRenderCtx.factorOrder.forEach((f, fi) => {
            const el = document.getElementById(`me-xspec-lbl-${fi}`);
            if (el) el.innerHTML = _meXSpecLabelHtml(f);
        });
    }

    // Draw histogram for factor fi
    function _drawHistCell(fi, factor) {
        const canvas = document.getElementById(`me-hist-${fi}`);
        if (!canvas) return;
        const st = _meColStats[factor];
        if (!st?.hist_counts) return;
        const W = canvas.clientWidth || 120, H = canvas.clientHeight || 44;
        if (W < 4 || H < 4) return;
        const dpr = window.devicePixelRatio || 1;
        canvas.width = W * dpr; canvas.height = H * dpr;
        canvas.style.width = W + 'px'; canvas.style.height = H + 'px';
        const ctx = canvas.getContext('2d');
        ctx.scale(dpr, dpr);

        const counts = st.hist_counts, edges = st.hist_edges;
        const maxCount = Math.max(...counts, 1);
        const pad = { t: 2, r: 2, b: 12, l: fi === 0 ? 32 : 2 };
        const cw = W - pad.l - pad.r, ch = H - pad.t - pad.b;
        const nBins = counts.length;

        // Use full data range (st.min ~ st.max) — consistent with ALE chart above
        const xMin = st.min ?? edges[0];
        const xMax = st.max ?? edges[edges.length - 1];
        const xSpan = (xMax - xMin) || 1;

        ctx.clearRect(0, 0, W, H);
        ctx.fillStyle = 'rgba(99,102,241,0.35)';
        for (let i = 0; i < nBins; i++) {
            const barLeft  = pad.l + ((edges[i]     - xMin) / xSpan) * cw;
            const barRight = pad.l + ((edges[i + 1] - xMin) / xSpan) * cw;
            const bh = (counts[i] / maxCount) * ch;
            const bw = Math.max(barRight - barLeft - 0.5, 1);
            ctx.fillRect(Math.max(barLeft, pad.l), pad.t + ch - bh, Math.min(bw, pad.l + cw - Math.max(barLeft, pad.l)), bh);
        }

        // X axis: show min, mid, max (same values as ALE X labels above)
        const fmtX = v => Math.abs(v) >= 1000 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2);
        ctx.fillStyle = '#94a3b8'; ctx.font = '7px Arial'; ctx.textBaseline = 'top';
        ctx.textAlign = 'left';   ctx.fillText(fmtX(xMin), pad.l, pad.t + ch + 2);
        ctx.textAlign = 'center'; ctx.fillText(fmtX((xMin + xMax) / 2), pad.l + cw / 2, pad.t + ch + 2);
        ctx.textAlign = 'right';  ctx.fillText(fmtX(xMax), pad.l + cw, pad.t + ch + 2);

        // X-axis parameter spec lines (X-USL / X-LSL) + value labels below
        const ps = _meParamSpecs[factor] || {};
        const drawHistVLine = (val, clr, label) => {
            if (_meSettings.show_x_spec === false) return;
            if (val == null || isNaN(val)) return;
            const px = pad.l + ((val - xMin) / xSpan) * cw;
            if (px < pad.l - 1 || px > pad.l + cw + 1) return;
            ctx.strokeStyle = clr; ctx.lineWidth = 1.2; ctx.setLineDash([3, 2]);
            ctx.beginPath(); ctx.moveTo(px, pad.t); ctx.lineTo(px, pad.t + ch); ctx.stroke();
            ctx.setLineDash([]);
            // Value label below x-axis (override min/mid/max at that position)
            ctx.fillStyle = clr; ctx.font = 'bold 7px Arial'; ctx.textBaseline = 'top';
            ctx.textAlign = 'center';
            ctx.fillText(`${label}${fmtX(val)}`, Math.min(Math.max(px, pad.l + 10), pad.l + cw - 10), pad.t + ch + 2);
        };
        drawHistVLine(ps.usl, '#f97316', 'U:');
        drawHistVLine(ps.lsl, '#0891b2', 'L:');

        // Current value marker — always in range since slider is limited to [st.min, st.max]
        const cur = _meSliderVals[factor] ?? st.median;
        const mxH = pad.l + ((cur - xMin) / xSpan) * cw;
        ctx.strokeStyle = '#ef4444'; ctx.lineWidth = 1.5; ctx.setLineDash([3, 2]);
        ctx.beginPath(); ctx.moveTo(mxH, pad.t); ctx.lineTo(mxH, pad.t + ch); ctx.stroke();
        ctx.setLineDash([]);
    }

    // Sort columns by effect size of target[ti] then rebuild
    window.meSortByTarget = function (ti) {
        if (!_meRenderCtx) return;
        const { factorOrder, targetOrder, byTarget } = _meRenderCtx;
        const t = targetOrder[ti];
        if (!t) return;
        factorOrder.sort((a, b) => {
            const aleRange = f => {
                const d = byTarget[t]?.[f];
                if (!d?.ale) return 0;
                const v = d.ale.filter(x => x != null);
                return v.length ? Math.max(...v) - Math.min(...v) : 0;
            };
            return aleRange(b) - aleRange(a); // descending
        });
        _buildGrid();
    };

    // ── Canvas drag to move red marker ────────────────────────────────
    function _dragXtoVal(e, fi) {
        const isTouch = e.touches;
        const clientX = isTouch ? e.touches[0].clientX : e.clientX;
        const canvas  = document.getElementById(`me-c-0-${fi}`);
        if (!canvas || !_meRenderCtx) return;
        const { factorOrder, targetOrder, byTarget, targetYRange } = _meRenderCtx;
        const factor = factorOrder[fi];
        if (!factor) return;
        const st    = _meColStats[factor] || { min: 0, max: 1 };
        const rect  = canvas.getBoundingClientRect();
        const padL  = fi === 0 ? 32 : 4;
        const cw    = rect.width - padL - 4;
        const ratio = Math.max(0, Math.min(1, (clientX - rect.left - padL) / cw));
        const val   = st.min + ratio * (st.max - st.min);

        if (_meDragTarget === 'xusl' || _meDragTarget === 'xlsl') {
            if (!_meParamSpecs[factor]) _meParamSpecs[factor] = {};
            if (_meDragTarget === 'xusl') _meParamSpecs[factor].usl = val;
            else                          _meParamSpecs[factor].lsl = val;
            // Sync back to the modal input (if panel is open)
            const k = factor.replace(/[^a-zA-Z0-9]/g, '_');
            const inputId = _meDragTarget === 'xusl' ? 'mp-xusl-' + k : 'mp-xlsl-' + k;
            const inputEl = document.getElementById(inputId);
            if (inputEl) inputEl.value = val.toFixed(4);
            // Redraw all cells in this column + histogram
            targetOrder.forEach((t, ti) => {
                const d = byTarget[t]?.[factor];
                if (d) _drawCell(ti, fi, factor, t, d, targetYRange[t]);
            });
            _drawHistCell(fi, factor);
            _updateXSpecLabels();
        } else {
            meSliderChange2(fi, val);
            const inp = document.querySelector(`input.me-sl[oninput="meSliderChange2(${fi},this.value)"]`);
            if (inp) inp.value = val;
        }
    }

    function _meDragMove(e) {
        if (_meDragFi === null) return;
        e.preventDefault();
        _dragXtoVal(e, _meDragFi);
    }
    function _meDragEnd() {
        _meDragFi = null;
        document.removeEventListener('mousemove', _meDragMove);
        document.removeEventListener('mouseup',   _meDragEnd);
        document.removeEventListener('touchmove', _meDragMove);
        document.removeEventListener('touchend',  _meDragEnd);
        // Fire XGBoost immediately on release for accurate final value
        _scheduleXGBoostPred(0);
    }

    window.meCellDragStart = function (e, fi) {
        if (!_meRenderCtx) return;
        const { factorOrder } = _meRenderCtx;
        const factor = factorOrder[fi];
        if (!factor) return;

        // Detect whether click landed near X-USL, X-LSL, or the slider
        const clientX  = e.touches ? e.touches[0].clientX : e.clientX;
        const refCanvas = document.getElementById(`me-c-0-${fi}`);
        if (refCanvas) {
            const st    = _meColStats[factor] || { min: 0, max: 1 };
            const rect  = refCanvas.getBoundingClientRect();
            const padL  = fi === 0 ? 32 : 4;
            const cw    = rect.width - padL - 4;
            const xSpan = (st.max - st.min) || 1;
            const toPx  = v => rect.left + padL + ((v - st.min) / xSpan) * cw;
            const ps    = _meParamSpecs[factor] || {};
            const THRESH = 10;
            if (ps.usl != null && Math.abs(clientX - toPx(ps.usl)) <= THRESH) {
                _meDragTarget = 'xusl';
            } else if (ps.lsl != null && Math.abs(clientX - toPx(ps.lsl)) <= THRESH) {
                _meDragTarget = 'xlsl';
            } else {
                if (_meFixedFactors.has(factor)) return; // slider locked
                _meDragTarget = 'slider';
            }
        } else {
            if (_meFixedFactors.has(factor)) return;
            _meDragTarget = 'slider';
        }

        e.preventDefault();
        _meDragFi = fi;
        _dragXtoVal(e, fi);
        document.addEventListener('mousemove', _meDragMove);
        document.addEventListener('mouseup',   _meDragEnd);
        document.addEventListener('touchmove', _meDragMove, { passive: false });
        document.addEventListener('touchend',  _meDragEnd);
    };

    // Core drawing logic — reused by both normal cells and the zoom modal
    function _paintCell(canvas, ti, fi, factor, target, data, yRange, opts) {
        const zoom = opts?.zoom || false;
        const W = canvas.width  / (window.devicePixelRatio || 1);
        const H = canvas.height / (window.devicePixelRatio || 1);
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        if (zoom) ctx.scale(window.devicePixelRatio || 1, window.devicePixelRatio || 1);

        const showY  = zoom || fi === 0;
        const padL   = showY ? (zoom ? 48 : 32) : 4;
        const padB   = zoom ? 28 : 16;
        const pad    = { t: zoom ? 14 : 6, r: zoom ? 10 : 4, b: padB, l: padL };
        const cw     = W - pad.l - pad.r;
        const ch     = H - pad.t - pad.b;
        const yMin   = yRange.min, yMax = yRange.max, ySpan = yMax - yMin || 1;
        const ts     = _meTargetStats[target] || {};
        const color  = TARGET_COLORS[ti % TARGET_COLORS.length];
        const isFixed = _meFixedFactors?.has(factor);
        const analysisMethod = _meRenderCtx?.analysisMethod || 'ale';
        const aleOffset = analysisMethod === 'ale' ? (ts.mean || 0) : 0;
        const lw     = zoom ? 2.5 : 2;
        const fontSize = zoom ? 11 : (showY ? 8 : 7);

        // Grid
        ctx.strokeStyle = '#f1f5f9'; ctx.lineWidth = 1;
        for (let i = 0; i <= 4; i++) {
            const y = pad.t + ch / 4 * i;
            ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(pad.l + cw, y); ctx.stroke();
        }

        // X display range — shared by scatter, ALE curve, slider, and X labels
        const st  = _meColStats[factor] || { min: 0, max: 1 };
        const xDispMin  = st.min;
        const xDispMax  = st.max;
        const xDispSpan = (xDispMax - xDispMin) || 1;

        // Real data scatter
        if (_meShowRealData && _meRenderCtx?.scatterData?.[target]?.[factor]) {
            const sc = _meRenderCtx.scatterData[target][factor];
            const xVals = sc.x, yVals = sc.y;
            ctx.fillStyle = zoom ? 'rgba(100,116,139,0.3)' : 'rgba(100,116,139,0.18)';
            const r = zoom ? 2.5 : 1.2;
            for (let i = 0; i < xVals.length; i++) {
                const px = pad.l + ((xVals[i] - xDispMin) / xDispSpan) * cw;
                const py = pad.t + ch - ((yVals[i] - yMin) / ySpan) * ch;
                if (px < pad.l || px > pad.l + cw) continue;
                ctx.beginPath(); ctx.arc(px, py, r, 0, Math.PI * 2); ctx.fill();
            }
        }

        // Spec lines
        const specUsl    = ts.usl ?? ts.ucl;
        const specLsl    = ts.lsl ?? ts.lcl;
        const specTarget = ts.target_mean ?? ts.mean;
        const drawHLine  = (val, clr, dash, label) => {
            if (val == null) return;
            const py = pad.t + ch - ((val - yMin) / ySpan) * ch;
            if (py < pad.t - 2 || py > pad.t + ch + 2) return;
            ctx.strokeStyle = clr; ctx.lineWidth = zoom ? 1.5 : 1.2; ctx.setLineDash(dash);
            ctx.beginPath(); ctx.moveTo(pad.l, py); ctx.lineTo(pad.l + cw, py); ctx.stroke();
            ctx.setLineDash([]);
            if (label) {
                ctx.fillStyle = clr; ctx.font = `bold ${fontSize}px Arial`;
                ctx.textAlign = 'left'; ctx.textBaseline = 'bottom';
                ctx.fillText(label, pad.l + 2, py - 1);
            }
        };
        if (_meSettings.show_y_spec !== false) {
            drawHLine(specUsl,    '#ef4444', [4, 2], 'USL');
            drawHLine(specLsl,    '#3b82f6', [4, 2], 'LSL');
            drawHLine(specTarget, '#22c55e', [5, 3], 'T');
        }
        if (_meSettings.show_pred !== false) {
            drawHLine(ts.ale_pred, '#a855f7', [3, 3], zoom ? 'Pred' : '');
        }

        const cur = _meSliderVals[factor] ?? st.median;
        const { grid, ale } = data;

        // ALE curve — shifted vertically so it passes through Pred line at the current slider position
        // curveOffset = other factors' combined contribution = ale_pred - mean - ALE_thisF(slider)
        if (grid && ale && grid.length >= 2) {
            const avgBinWidth = xDispSpan / grid.length;
            const gapThreshold = avgBinWidth * 3;
            const aleAtSlider = _interpolateAle(grid, ale, cur) ?? 0;
            const curveOffset = (ts.ale_pred != null) ? (ts.ale_pred - aleOffset - aleAtSlider) : 0;
            const nPerBin = data.n_per_bin || [];
            const SPARSE_N = 5; // < 5筆 → 虛線低信心；≥ 5筆 → 實線

            const drawSegments = (sparse) => {
                ctx.beginPath();
                let started = false;
                for (let i = 0; i < grid.length; i++) {
                    if (ale[i] == null) { started = false; continue; }
                    const n = nPerBin[i] ?? 999;
                    const isSparse = n < SPARSE_N;
                    if (isSparse !== sparse) { started = false; continue; }
                    const px = pad.l + ((grid[i] - xDispMin) / xDispSpan) * cw;
                    const py = pad.t + ch - ((ale[i] + aleOffset + curveOffset - yMin) / ySpan) * ch;
                    const hasGap = started && i > 0 && (grid[i] - grid[i - 1]) > gapThreshold;
                    if (!started || hasGap) { ctx.moveTo(px, py); started = true; } else ctx.lineTo(px, py);
                }
                ctx.stroke();
            };

            ctx.strokeStyle = color; ctx.lineWidth = lw; ctx.lineJoin = 'round';

            // Pass 1: sparse bins → dashed + semi-transparent
            ctx.globalAlpha = 0.38;
            ctx.setLineDash([3, 4]);
            drawSegments(true);

            // Pass 2: dense bins → solid + full opacity
            ctx.globalAlpha = 1;
            ctx.setLineDash([]);
            drawSegments(false);

            ctx.globalAlpha = 1; // reset
        }

        // X-axis parameter spec lines (operating range USL/LSL)
        const ps = _meParamSpecs[factor] || {};
        const drawXSpec = (val, clr, label) => {
            if (_meSettings.show_x_spec === false) return;
            if (val == null || isNaN(val)) return;
            const px = pad.l + ((val - xDispMin) / xDispSpan) * cw;
            if (px < pad.l - 2 || px > pad.l + cw + 2) return;
            ctx.strokeStyle = clr; ctx.lineWidth = zoom ? 1.8 : 1.2; ctx.setLineDash([3, 2]);
            ctx.beginPath(); ctx.moveTo(px, pad.t); ctx.lineTo(px, pad.t + ch); ctx.stroke();
            ctx.setLineDash([]);
            ctx.fillStyle = clr; ctx.font = `bold ${fontSize}px Arial`;
            ctx.textAlign = 'center'; ctx.textBaseline = 'bottom';
            ctx.fillText(label, px, pad.t + ch - 1);
        };
        drawXSpec(ps.usl, '#f97316', 'U');
        drawXSpec(ps.lsl, '#0891b2', 'L');

        // Slider marker — always within range since cur is clamped to [st.min, st.max]
        const mx = pad.l + ((cur - xDispMin) / xDispSpan) * cw;
        const sliderColor = isFixed ? '#94a3b8' : '#ef4444';
        ctx.strokeStyle = sliderColor; ctx.lineWidth = zoom ? 2 : 1.5; ctx.setLineDash([4, 3]);
        ctx.beginPath(); ctx.moveTo(mx, pad.t); ctx.lineTo(mx, pad.t + ch); ctx.stroke();
        ctx.setLineDash([]);
        if (zoom) {
            ctx.fillStyle = sliderColor; ctx.font = `bold ${fontSize}px Arial`;
            ctx.textAlign = 'center'; ctx.textBaseline = 'top';
            ctx.fillText(cur.toFixed(3), mx, pad.t + ch + 4);
        }

        // Y labels
        if (showY) {
            ctx.fillStyle = '#64748b'; ctx.font = `${fontSize}px Arial`;
            ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
            const fmtY = v => Math.abs(v) >= 1000 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2);
            ctx.fillText(fmtY(yMax), pad.l - 3, pad.t);
            ctx.fillText(fmtY((yMax + yMin) / 2), pad.l - 3, pad.t + ch / 2);
            ctx.fillText(fmtY(yMin), pad.l - 3, pad.t + ch);
        }

        // X axis labels (full data range)
        const fmtX = v => Math.abs(v) >= 1000 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2);
        ctx.fillStyle = '#94a3b8'; ctx.font = `${zoom ? 10 : 7}px Arial`; ctx.textBaseline = 'top';
        ctx.textAlign = 'left';   ctx.fillText(fmtX(xDispMin), pad.l, pad.t + ch + 2);
        ctx.textAlign = 'center'; ctx.fillText(fmtX((xDispMin + xDispMax) / 2), pad.l + cw / 2, pad.t + ch + 2);
        ctx.textAlign = 'right';  ctx.fillText(fmtX(xDispMax), pad.l + cw, pad.t + ch + 2);
    }

    function _drawCell(ti, fi, factor, target, data, yRange) {
        const canvas = document.getElementById(`me-c-${ti}-${fi}`);
        if (!canvas) return;
        const drawFn = () => {
            const W = canvas.clientWidth || 140;
            const H = canvas.clientHeight || 130;
            if (W < 10 || H < 10) { requestAnimationFrame(drawFn); return; }
            const dpr = window.devicePixelRatio || 1;
            canvas.width  = W * dpr;
            canvas.height = H * dpr;
            canvas.style.width  = W + 'px';
            canvas.style.height = H + 'px';
            const ctx = canvas.getContext('2d');
            ctx.scale(dpr, dpr);
            _paintCell(canvas, ti, fi, factor, target, data, yRange, { zoom: false });
            // Keep side-panel in sync if it's showing this cell
            const panel = document.getElementById('me-zoom-panel');
            if (panel && +panel.dataset.ti === ti && +panel.dataset.fi === fi) {
                _redrawZoomPanel();
            }
        };
        requestAnimationFrame(drawFn);
    }

    // Zoom modal: shows a large high-res version of a single cell
    // Redraw the zoom panel canvas (called on slider change while panel is open)
    function _redrawZoomPanel() {
        const panel = document.getElementById('me-zoom-panel');
        if (!panel || !_meRenderCtx) return;
        const ti = +panel.dataset.ti, fi = +panel.dataset.fi;
        const { factorOrder, targetOrder, byTarget, targetYRange } = _meRenderCtx;
        const factor = factorOrder[fi], target = targetOrder[ti];
        const data = byTarget[target]?.[factor];
        if (!data) return;
        const canvas = document.getElementById('me-zoom-canvas');
        if (!canvas) return;
        _paintCell(canvas, ti, fi, factor, target, data, targetYRange[target], { zoom: true });
    }

    window.meZoomCell = function (ti, fi) {
        if (!_meRenderCtx) return;
        const { factorOrder, targetOrder, byTarget, targetYRange } = _meRenderCtx;
        const factor = factorOrder[fi], target = targetOrder[ti];
        if (!factor || !target) return;
        const data = byTarget[target]?.[factor];
        if (!data) return;
        const clr = TARGET_COLORS[ti % TARGET_COLORS.length];

        // Remove previous panel if any
        document.getElementById('me-zoom-panel')?.remove();

        // Side panel — slides in from the right, does not block interaction
        const step3Rect = document.getElementById('me-step3-content')?.getBoundingClientRect();
        const panelW = 360;
        const panelTop  = step3Rect ? Math.round(step3Rect.top  + window.scrollY + 8) : 80;
        const panelRight = 16; // from viewport right edge

        const panel = document.createElement('div');
        panel.id = 'me-zoom-panel';
        panel.dataset.ti = ti;
        panel.dataset.fi = fi;
        panel.style.cssText = `position:fixed;top:${panelTop}px;right:${panelRight}px;
            width:${panelW}px;background:#fff;border-radius:10px;
            box-shadow:0 8px 32px rgba(0,0,0,0.18);border:1px solid #e2e8f0;
            z-index:10001;display:flex;flex-direction:column;
            animation:meSlideIn 0.18s ease-out;`;
        panel.innerHTML = `
            <style>@keyframes meSlideIn{from{opacity:0;transform:translateX(20px)}to{opacity:1;transform:translateX(0)}}</style>
            <div style="padding:7px 12px;border-bottom:1px solid #f1f5f9;display:flex;align-items:center;justify-content:space-between;">
                <div style="font-size:11px;font-weight:700;">
                    <span style="color:${clr};">${target}</span>
                    <span style="color:#94a3b8;margin:0 4px;">×</span>
                    <span style="color:#1e293b;">${factor}</span>
                </div>
                <button onclick="document.getElementById('me-zoom-panel').remove()"
                    style="background:none;border:none;font-size:16px;cursor:pointer;color:#94a3b8;line-height:1;padding:0;">✕</button>
            </div>
            <div style="padding:8px;">
                <canvas id="me-zoom-canvas" style="width:100%;display:block;border-radius:4px;background:#fff;"></canvas>
            </div>`;
        document.body.appendChild(panel);

        const _escZoom = e => { if (e.key === 'Escape') { panel.remove(); document.removeEventListener('keydown', _escZoom); } };
        document.addEventListener('keydown', _escZoom);

        requestAnimationFrame(() => {
            const canvas = document.getElementById('me-zoom-canvas');
            if (!canvas) return;
            const W = canvas.clientWidth || (panelW - 16);
            const H = Math.round(W * 0.55);
            const dpr = window.devicePixelRatio || 1;
            canvas.width  = W * dpr;
            canvas.height = H * dpr;
            canvas.style.height = H + 'px';
            _paintCell(canvas, ti, fi, factor, target, data, targetYRange[target], { zoom: true });
        });
    };

    window.meSliderChange2 = function (fi, rawVal) {
        if (!_meRenderCtx) return;
        const { factorOrder, targetOrder, byTarget, targetYRange } = _meRenderCtx;
        const factor = factorOrder[fi];
        if (!factor) return;
        const val = parseFloat(rawVal);
        _meSliderVals[factor] = val;
        const valEl = document.getElementById('me-sv-' + fi);
        if (valEl) { if (valEl.tagName === 'INPUT') valEl.value = val.toFixed(4); else valEl.textContent = val.toFixed(3); }
        // Redraw entire column
        targetOrder.forEach((t, ti) => {
            const d = byTarget[t]?.[factor];
            if (d) _drawCell(ti, fi, factor, t, d, targetYRange[t]);
        });
        _drawHistCell(fi, factor); // sync histogram red marker
        _updatePredictions();
    };

    // legacy – kept for safety
    window.meSliderChange = window.meSliderChange2;

    // Linearly interpolate ALE curve value at x from grid/ale arrays
    function _interpolateAle(grid, ale, x) {
        if (!grid || !ale || grid.length === 0) return null;
        if (x <= grid[0]) return ale[0] ?? null;
        if (x >= grid[grid.length - 1]) return ale[grid.length - 1] ?? null;
        for (let i = 0; i < grid.length - 1; i++) {
            if (x >= grid[i] && x <= grid[i + 1]) {
                const t = (grid[i + 1] === grid[i]) ? 0 : (x - grid[i]) / (grid[i + 1] - grid[i]);
                const a0 = ale[i] ?? 0, a1 = ale[i + 1] ?? 0;
                return a0 + t * (a1 - a0);
            }
        }
        return ale[ale.length - 1] ?? null;
    }


    // Compute ALE-based predictions client-side (consistent with chart visualization):
    // prediction = target_mean + Σ interpolated_ale(factor_slider) across all factors
    function _updatePredictions() {
        if (!_meRenderCtx) return;
        const { factorOrder, targetOrder, byTarget, targetYRange } = _meRenderCtx;
        const analysisMethod = _meRenderCtx.analysisMethod || 'ale';
        const statusEl = document.getElementById('me-pred-status');
        if (statusEl) { statusEl.textContent = '✓'; statusEl.style.color = '#10b981'; }

        targetOrder.forEach((target, ti) => {
            const el = document.getElementById('me-pred-' + ti);
            if (!el) return;
            const ts = _meTargetStats[target] || {};

            // PDP values are absolute predictions — summing them gives N×mean (wrong).
            // Keep stale ts.ale_pred so the Pred line stays at the last accurate
            // XGBoost position while waiting for the next XGBoost response.
            if (analysisMethod !== 'ale') {
                el.textContent = '…';
                el.style.color = '#94a3b8';
                // ts.ale_pred intentionally NOT cleared — keeps last accurate position
                return;
            }

            const baseVal = ts.target_mean ?? ts.mean ?? 0;
            let totalEffect = 0;
            factorOrder.forEach(factor => {
                const d = byTarget[target]?.[factor];
                if (!d?.grid || !d?.ale) return;
                const x = _meSliderVals[factor] ?? (_meColStats[factor]?.median ?? 0);
                const effect = _interpolateAle(d.grid, d.ale, x);
                if (effect != null) totalEffect += effect;
            });

            const p = baseVal + totalEffect;
            const usl = ts.usl ?? ts.ucl;
            const lsl = ts.lsl ?? ts.lcl;
            const ok  = (usl != null && lsl != null) ? (p >= lsl && p <= usl) : true;
            el.textContent = isNaN(p) ? '—' : p.toFixed(3);
            el.style.color = ok ? '#10b981' : '#ef4444';
            // Store for drawing combined-prediction line on chart cells
            ts.ale_pred = isNaN(p) ? null : p;

            // Center y-range on pred using spec lines only (excludes ALE extremes)
            if (!isNaN(p) && p != null) {
                targetYRange[target] = _predCenteredYRange(p, target);
            }
        });

        // After ALE update, also fetch real XGBoost prediction (debounced 400ms)
        _scheduleXGBoostPred();

        // Redraw all cells so the Pred line reflects updated values
        if (_meRenderCtx) {
            const { factorOrder, targetOrder, byTarget, targetYRange } = _meRenderCtx;
            targetOrder.forEach((t, ti) => {
                factorOrder.forEach((f, fi) => {
                    const d = byTarget[t]?.[f];
                    if (d) _drawCell(ti, fi, f, t, d, targetYRange[t]);
                });
            });
        }
    }

    // ── XGBoost real-model prediction (replaces inaccurate ALE sum) ──────
    let _xgbPredTimer = null;
    // Compute a symmetric y-range centered on pred.
    // Only uses user-set USL/LSL and T/mean — excludes UCL/LCL (statistical limits)
    // and ALE extremes which can be very wide and distort the scale.
    function _predCenteredYRange(p, target) {
        const ts = _meTargetStats[target] || {};
        // ucl/lcl intentionally excluded — they can be extreme
        const refs = [ts.usl, ts.lsl, ts.target_mean, ts.mean].filter(v => v != null);
        const half = Math.max(
            refs.reduce((m, v) => Math.max(m, Math.abs(p - v)), 0),
            Math.abs(p) * 0.1 || 0.5    // fallback: at least 10% of pred
        ) * 1.15;
        return { min: p - half, max: p + half };
    }

    function _scheduleXGBoostPred(delayMs = 150) {
        if (_xgbPredTimer) clearTimeout(_xgbPredTimer);
        _xgbPredTimer = setTimeout(_fetchXGBoostPred, delayMs);
    }

    async function _fetchXGBoostPred() {
        if (!_meRenderCtx) return;
        const sid = typeof getSessionId === 'function' ? getSessionId() : 'default';
        const control_values = {};
        _meRenderCtx.factorOrder.forEach(f => {
            const v = _meSliderVals[f] ?? (_meColStats[f]?.median ?? 0);
            control_values[f] = v;
        });
        try {
            const resp = await fetch(`/api/data-prep/me-predict?session_id=${sid}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ control_values }),
            });
            if (!resp.ok) return;
            const data = await resp.json();
            if (!data?.predictions) return;
            _applyXGBoostPred(data.predictions);
        } catch { /* ignore fetch errors */ }
    }

    function _applyXGBoostPred(predictions) {
        if (!_meRenderCtx) return;
        const { targetOrder, factorOrder, byTarget, targetYRange } = _meRenderCtx;
        let needRedraw = false;
        targetOrder.forEach((target, ti) => {
            const p = predictions[target]?.predicted;
            if (p == null || isNaN(p)) return;
            const ts = _meTargetStats[target] || {};
            const usl = ts.usl ?? ts.ucl;
            const lsl = ts.lsl ?? ts.lcl;
            const ok  = (usl != null && lsl != null) ? (p >= lsl && p <= usl) : true;
            const el = document.getElementById('me-pred-' + ti);
            if (el) {
                el.textContent = p.toFixed(3);
                el.style.color = ok ? '#10b981' : '#ef4444';
            }
            ts.ale_pred = p;

            // Center y-range on pred using spec lines only (excludes ALE extremes)
            targetYRange[target] = _predCenteredYRange(p, target);
            needRedraw = true;
        });
        if (needRedraw) {
            targetOrder.forEach((t, ti) => {
                factorOrder.forEach((f, fi) => {
                    const d = byTarget[t]?.[f];
                    if (d) _drawCell(ti, fi, f, t, d, targetYRange[t]);
                });
            });
        }
    }

    // Toggle real data scatter overlay
    // Cell height controls
    window.meCellSizeSet = function (val) {
        _meCellHeight = Math.max(60, Math.min(260, val));
        const lbl = document.getElementById('me-cell-height-label');
        if (lbl) lbl.value = _meCellHeight;
        const sl = document.getElementById('me-cell-height-slider');
        if (sl) sl.value = _meCellHeight;
        if (!_meRenderCtx) return;
        // Full rebuild so grid column widths also update
        _buildGrid();
    };
    window.meCellSizeStep = function (delta) {
        window.meCellSizeSet(_meCellHeight + delta);
    };

    window.meRunOptimize = async function () {
        if (!_meRenderCtx) return;
        const { targetOrder } = _meRenderCtx;
        const directions = {}, targetValues = {};
        targetOrder.forEach(t => {
            const key = t.replace(/[^a-zA-Z0-9]/g, '_');
            directions[t] = document.getElementById('mo-dir-' + key)?.value || 'min';
            // Read target value from _meTargetStats (set by the Target Specs tab)
            const tv = _meTargetStats[t]?.target_mean ?? _meTargetStats[t]?.mean;
            if (tv != null && !isNaN(tv)) targetValues[t] = tv;
        });

        // Recompute base y-ranges to include updated USL/LSL, then redraw all cells
        if (_meRenderCtx) {
            const { targetOrder, factorOrder, byTarget, targetBaseYRange, targetYRange } = _meRenderCtx;
            const analysisMethod = _meRenderCtx.analysisMethod || 'ale';
            targetOrder.forEach(t => {
                const ts = _meTargetStats[t] || {};
                const aleOffset = analysisMethod === 'ale' ? (ts.mean || 0) : 0;
                let vals = [];
                factorOrder.forEach(f => {
                    const d = byTarget[t]?.[f];
                    if (d?.ale) vals = vals.concat(d.ale.filter(v => v != null).map(v => v + aleOffset));
                });
                if (ts.usl != null) vals.push(ts.usl);
                if (ts.lsl != null) vals.push(ts.lsl);
                if (ts.ucl != null) vals.push(ts.ucl);
                if (ts.lcl != null) vals.push(ts.lcl);
                if (ts.target_mean != null) vals.push(ts.target_mean);
                if (ts.mean != null) vals.push(ts.mean);
                if (vals.length === 0) vals = [0, 1];
                const rawMin = Math.min(...vals), rawMax = Math.max(...vals);
                const pad12 = (rawMax - rawMin) * 0.12 || 1;
                targetBaseYRange[t] = { min: rawMin - pad12, max: rawMax + pad12 };
                targetYRange[t] = { ...targetBaseYRange[t] };
            });
            targetOrder.forEach((t, ti) => {
                factorOrder.forEach((f, fi) => {
                    const d = byTarget[t]?.[f];
                    if (d) _drawCell(ti, fi, f, t, d, targetYRange[t]);
                });
            });
        }

        const nSolutions = parseInt(document.getElementById('mo-n-solutions')?.value) || 50;
        const progress    = document.getElementById('mo-progress');
        const progressBar = document.getElementById('mo-progress-bar');
        const progressPct = document.getElementById('mo-progress-pct');
        const progressPhase = document.getElementById('mo-progress-phase');
        if (progress) progress.style.display = 'block';

        const runBtn = document.getElementById('me-panel-action-btn');
        if (runBtn) {
            runBtn.disabled = true;
            runBtn.style.background = '#6ee7b7';
            runBtn.style.cursor = 'not-allowed';
            runBtn.textContent = '⏳ 最佳化中…';
        }

        const sid = typeof getSessionId === 'function' ? getSessionId() : 'default';

        // Poll progress every 500 ms
        let _pollTimer = null;
        const _startPoll = () => {
            _pollTimer = setInterval(async () => {
                try {
                    const r = await fetch(`/api/data-prep/me-optimize-progress?session_id=${sid}`);
                    const p = await r.json();
                    if (p.total > 0) {
                        const pct = Math.min(100, Math.round(p.done / p.total * 100));
                        if (progressBar)  progressBar.style.width  = pct + '%';
                        if (progressPct)  progressPct.textContent  = pct + '%';
                        if (progressPhase) progressPhase.textContent = p.phase || '執行中…';
                    }
                } catch { /* ignore poll errors */ }
            }, 500);
        };
        const _stopPoll = () => { if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; } };

        _startPoll();
        try {
            // Background factors must never be disturbed — add them to fixed set
            const allFixed = new Set([..._meFixedFactors, ..._meBgFactors]);
            const body = {
                directions,
                target_values: targetValues,
                fixed_factors: [...allFixed],
                fixed_values: Object.fromEntries(
                    [...allFixed].map(f => [f, _meSliderVals[f] ?? (_meColStats[f]?.median ?? 0)])
                ),
                n_solutions: nSolutions,
                n_gen: 50,
            };
            const resp = await fetch(`/api/data-prep/me-optimize?session_id=${sid}`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const data = await resp.json();
            _stopPoll();
            if (!resp.ok) throw new Error(data.detail || '最佳化失敗');
            document.getElementById('me-analysis-panel')?.remove();
            _showOptimizeResults(data, directions, targetValues);
        } catch (e) {
            _stopPoll();
            if (progressBar) progressBar.style.background = '#ef4444';
            if (progressPhase) progressPhase.style.color = '#ef4444';
            if (progressPhase) progressPhase.textContent = '❌ ' + e.message;
            if (progressPct) progressPct.textContent = '';
            const runBtn2 = document.getElementById('me-panel-action-btn');
            if (runBtn2) {
                runBtn2.disabled = false;
                runBtn2.style.background = '#10b981';
                runBtn2.style.cursor = 'pointer';
                runBtn2.textContent = '▶ 執行最佳化';
            }
        }
    };

    // ── Opt drawer sort state ────────────────────────────────────────────
    let _meOptSort = { key: 'score', dir: 1 }; // dir: 1=asc, -1=desc

    function _renderOptTable() {
        const ctx = window._meOptDrawerCtx;
        if (!ctx) return;
        const { scored, target_order, free_factors } = ctx;
        const fmtN = v => (v == null ? '—' : (Math.abs(v) >= 100 ? v.toFixed(2) : Math.abs(v) >= 1 ? v.toFixed(3) : v.toFixed(4)));

        // Apply current sort
        const key = _meOptSort.key, dir = _meOptSort.dir;
        const sorted = [...scored].sort((a, b) => {
            let va, vb;
            if (key === 'inSpec')       { va = a.inSpec;    vb = b.inSpec; }
            else if (key === 'score')   { va = a.normErr;   vb = b.normErr; }
            else if (key.startsWith('t:')) {
                const t = key.slice(2);
                va = a.sol.targets[t] ?? 0;
                vb = b.sol.targets[t] ?? 0;
            } else if (key.startsWith('p:')) {
                const f = key.slice(2);
                va = a.sol.params[f] ?? 0; vb = b.sol.params[f] ?? 0;
            } else { va = a.normErr; vb = b.normErr; }
            return (va - vb) * dir;
        });

        // Update solutions order so meApplyOptSolution uses correct row
        window._meOptSolutions.solutions = sorted.map(s => s.sol);

        // Update header arrows
        document.querySelectorAll('#me-opt-drawer th[data-col]').forEach(th => {
            const arrow = th.querySelector('.sort-arrow');
            if (!arrow) return;
            arrow.textContent = th.dataset.col === key ? (dir === 1 ? ' ▲' : ' ▼') : ' ⇅';
        });

        // Rebuild tbody
        const tbody = document.querySelector('#me-opt-drawer tbody');
        if (!tbody) return;
        tbody.innerHTML = sorted.map(({ sol, inSpec, normErr }, rank) => {
            const tCells = target_order.map(t => {
                const ts  = _meTargetStats[t] || {};
                const v   = sol.targets[t];
                const usl = ts.usl ?? ts.ucl, lsl = ts.lsl ?? ts.lcl;
                const ok  = (usl != null && lsl != null) ? (v >= lsl && v <= usl) : true;
                return `<td style="padding:4px 8px;font-size:11px;font-weight:600;border-left:2px solid #e2e8f0;
                    color:${ok ? '#10b981' : '#ef4444'};text-align:right;">${fmtN(v)}</td>`;
            }).join('');
            const pCells = free_factors.slice(0, 15).map(f =>
                `<td style="padding:4px 8px;font-size:11px;color:#334155;text-align:right;">${fmtN(sol.params[f])}</td>`
            ).join('');
            const inSpecColor = inSpec === target_order.length ? '#10b981' : inSpec === 0 ? '#ef4444' : '#f59e0b';
            return `<tr id="me-opt-row-${rank}" style="border-bottom:1px solid #f1f5f9;cursor:pointer;transition:background 0.1s;"
                onmouseenter="this.style.background='#f0fdf4'" onmouseleave="if(window._meOptSelected!=${rank})this.style.background=''"
                onclick="meApplyOptSolution(${rank})">
                <td style="padding:4px 8px;font-size:11px;font-weight:700;color:#6366f1;text-align:center;">${rank + 1}</td>
                <td style="padding:4px 8px;font-size:11px;font-weight:700;color:${inSpecColor};text-align:center;">${inSpec}/${target_order.length}</td>
                <td style="padding:4px 8px;font-size:11px;color:#64748b;text-align:right;">${normErr.toFixed(2)}</td>
                ${tCells}${pCells}
            </tr>`;
        }).join('');
    }

    window.meOptSortBy = function (key) {
        if (_meOptSort.key === key) _meOptSort.dir *= -1;
        else { _meOptSort.key = key; _meOptSort.dir = key === 'inSpec' ? -1 : 1; }
        _renderOptTable();
    };

    function _thSort(label, key, color, align) {
        const al = align || 'right';
        return `<th data-col="${key}" onclick="meOptSortBy('${key}')"
            style="padding:4px 8px;font-size:10px;font-weight:700;color:${color};white-space:nowrap;
                   text-align:${al};cursor:pointer;user-select:none;">
            ${label}<span class="sort-arrow"> ⇅</span></th>`;
    }

    function _showOptimizeResults(data, directions, targetValues) {
        directions   = directions   || {};
        targetValues = targetValues || {};
        const { target_order, free_factors, solutions } = data;
        const fmtSpec = v => v == null ? '—' : (Math.abs(v) >= 100 ? v.toFixed(2) : Math.abs(v) >= 1 ? v.toFixed(3) : v.toFixed(4));

        // Use sol.targets (XGBoost predictions from backend optimization) for scoring and display
        // sol.targets is already accurate — no need for ALE approximation
        const scored = solutions.map(sol => {
            let inSpec = 0, normErr = 0;
            target_order.forEach(t => {
                const ts  = _meTargetStats[t] || {};
                const v   = sol.targets[t];
                const usl = ts.usl ?? ts.ucl, lsl = ts.lsl ?? ts.lcl;
                const mean = ts.mean ?? 0;
                if (usl != null && lsl != null && v >= lsl && v <= usl) inSpec++;
                const dir = directions[t] || 'min';
                const ref = (dir === 'target' && targetValues[t] != null) ? targetValues[t] : mean;
                // Normalize by spec range (USL-LSL) so each target is equally weighted
                // regardless of its natural variability. Falls back to std if no spec.
                const specRange = (usl != null && lsl != null) ? (usl - lsl) : (ts.std ?? 1);
                normErr += Math.abs(v - ref) / (specRange || 1);
            });
            return { sol, inSpec, normErr };
        });
        // Default sort: more in-spec first, then lower error
        scored.sort((a, b) => b.inSpec - a.inSpec || a.normErr - b.normErr);
        _meOptSort = { key: 'score', dir: 1 };

        window._meOptSolutions = { solutions: scored.map(s => s.sol), free_factors };
        window._meOptDrawerCtx = { scored, target_order, free_factors, directions, targetValues };

        // Update T line on charts for targets with "接近目標值" direction
        let tLinesChanged = false;
        target_order.forEach(t => {
            const ts = _meTargetStats[t] || (_meTargetStats[t] = {});
            if (directions[t] === 'target' && targetValues[t] != null) {
                if (ts._origTargetMean === undefined) ts._origTargetMean = ts.target_mean; // save original
                ts.target_mean = targetValues[t];
                // Also extend base y-range to include new T value
                if (_meRenderCtx?.targetBaseYRange?.[t]) {
                    const base = _meRenderCtx.targetBaseYRange[t];
                    base.min = Math.min(base.min, targetValues[t]);
                    base.max = Math.max(base.max, targetValues[t]);
                }
                tLinesChanged = true;
            }
        });
        // Redraw all cells so new T lines appear
        if (tLinesChanged && _meRenderCtx) {
            const { factorOrder, targetOrder: tOrd, byTarget, targetYRange } = _meRenderCtx;
            tOrd.forEach((t, ti) => {
                factorOrder.forEach((f, fi) => {
                    const d = byTarget[t]?.[f];
                    if (d) _drawCell(ti, fi, f, t, d, targetYRange[t]);
                });
            });
        }

        // Build thead with target borders
        const theadTargetCols = target_order.map(t =>
            `<th data-col="t:${t}" onclick="meOptSortBy('t:${encodeURIComponent(t)}')"
                style="padding:4px 8px;font-size:10px;font-weight:700;color:#6366f1;white-space:nowrap;
                       text-align:right;cursor:pointer;user-select:none;border-left:2px solid #e2e8f0;">
                ${t}<span class="sort-arrow"> ⇅</span></th>`
        ).join('');
        const theadParamCols = free_factors.slice(0, 15).map(f =>
            `<th data-col="p:${f}" onclick="meOptSortBy('p:${f}')"
                style="padding:4px 8px;font-size:10px;font-weight:700;color:#475569;white-space:nowrap;
                       text-align:right;cursor:pointer;user-select:none;">
                ${f}<span class="sort-arrow"> ⇅</span></th>`
        ).join('');

        // Spec sub-header row (USL / T / LSL under each target)
        const specRow = `<tr style="background:#fff7ed;border-bottom:1px solid #fed7aa;">
            <td colspan="3" style="padding:2px 8px;font-size:9px;color:#94a3b8;white-space:nowrap;">規格</td>
            ${target_order.map(t => {
                const ts = _meTargetStats[t] || {};
                const usl = ts.usl, lsl = ts.lsl;
                const dir = directions[t] || 'min';
                const tv  = (dir === 'target' && targetValues[t] != null) ? targetValues[t] : null;
                const dirLabel = dir === 'max' ? '↑最大化' : dir === 'min' ? '↓最小化' : null;
                return `<td style="padding:2px 8px;font-size:9px;text-align:right;border-left:2px solid #e2e8f0;line-height:1.8;white-space:nowrap;">
                    ${usl != null ? `<span style="color:#dc2626;font-weight:700;">USL ${fmtSpec(usl)}</span><br>` : ''}
                    ${tv != null ? `<span style="color:#6366f1;font-weight:700;">T ${fmtSpec(tv)}</span><br>` : ''}
                    ${dirLabel != null ? `<span style="color:#94a3b8;">${dirLabel}</span><br>` : ''}
                    ${lsl != null ? `<span style="color:#2563eb;font-weight:700;">LSL ${fmtSpec(lsl)}</span>` : ''}</td>`;
            }).join('')}
            ${free_factors.slice(0, 15).map(() => '<td></td>').join('')}
        </tr>`;

        // Remove old drawer
        document.getElementById('me-opt-drawer')?.remove();

        const DRAWER_H = 240;
        // Compute left offset so drawer aligns with the chart area (not the sidebar)
        const _step3Rect = document.getElementById('me-step3-content')?.getBoundingClientRect();
        const _drawerLeft = _step3Rect ? Math.round(_step3Rect.left) : 0;
        const drawer = document.createElement('div');
        drawer.id = 'me-opt-drawer';
        drawer.dataset.expandedLeft = _drawerLeft; // stored for expand/collapse toggle
        // position:fixed so it stays above zoom/settings modals (z-index > 9999)
        drawer.style.cssText = `position:fixed;bottom:0;left:${_drawerLeft}px;right:16px;height:${DRAWER_H}px;
            background:#fff;border-top:2px solid #6366f1;border-radius:8px 8px 0 0;
            display:flex;flex-direction:column;
            transition:height 0.2s;z-index:10000;box-shadow:0 -2px 12px rgba(0,0,0,0.12);`;
        drawer.innerHTML = `
            <div style="padding:6px 14px;display:flex;align-items:center;gap:8px;
                        border-bottom:1px solid #e2e8f0;flex-shrink:0;background:#f8fafc;">
                <div style="display:flex;align-items:center;gap:10px;flex:1;min-width:0;overflow:hidden;">
                    <span style="font-size:12px;font-weight:700;color:#6366f1;flex-shrink:0;">⚡ 柏拉圖前緣解集</span>
                    <span style="font-size:11px;color:#94a3b8;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${scored.length} 個方案 · 點選欄位標題排序 · 點選列套用至圖表</span>
                </div>
                <div style="display:flex;align-items:center;gap:6px;flex-shrink:0;">
                    <select id="me-smart-range-threshold"
                        style="font-size:11px;padding:2px 5px;border:1px solid #e2e8f0;border-radius:5px;color:#475569;background:#fff;">
                        <option value="0.3">OOS ≤ 0.3%</option>
                        <option value="1" selected>OOS ≤ 1%</option>
                        <option value="3">OOS ≤ 3%</option>
                        <option value="5">OOS ≤ 5%</option>
                    </select>
                    <button onclick="meRunSmartRange()"
                        style="font-size:11px;padding:2px 10px;border:none;border-radius:5px;
                               background:#0ea5e9;color:#fff;cursor:pointer;font-weight:600;flex-shrink:0;">🎯 智慧化區間</button>
                    <button id="me-opt-collapse-btn"
                        onclick="(function(){const d=document.getElementById('me-opt-drawer');const sc=document.getElementById('me-chart-scroll');const collapsed=d.style.height==='32px';const newH=collapsed?${DRAWER_H}:32;d.style.height=newH+'px';if(collapsed){d.style.left=d.dataset.expandedLeft+'px';d.style.width=''}else{d.style.left='auto';d.style.width='360px';}if(sc)sc.style.bottom=newH+'px';document.getElementById('me-opt-collapse-btn').textContent=collapsed?'收合 ▾':'展開 ▴';})()"
                        style="font-size:11px;padding:2px 8px;border:1px solid #e2e8f0;border-radius:5px;background:#fff;cursor:pointer;color:#475569;">收合 ▾</button>
                    <button onclick="(function(){const sc=document.getElementById('me-chart-scroll');if(sc)sc.style.bottom='0';document.getElementById('me-opt-drawer').remove();window._meOptSelected=null;window.meRestoreOptTargets&&window.meRestoreOptTargets();})()"
                        style="font-size:11px;padding:2px 8px;border:1px solid #e2e8f0;border-radius:5px;background:#fff;cursor:pointer;color:#475569;">✕</button>
                </div>
            </div>
            <div style="overflow-x:scroll;overflow-y:auto;flex:1;min-height:0;min-width:0;">
                <table style="width:max-content;min-width:100%;border-collapse:collapse;">
                    <thead style="position:sticky;top:0;z-index:1;background:#f8fafc;">
                        <tr style="background:#f8fafc;border-bottom:1px solid #e2e8f0;">
                            <th style="padding:4px 8px;font-size:10px;font-weight:700;color:#94a3b8;text-align:center;">#</th>
                            ${_thSort('在規/總計', 'inSpec', '#10b981', 'center')}
                            ${_thSort('綜合誤差', 'score', '#64748b', 'right')}
                            ${theadTargetCols}
                            ${theadParamCols}
                        </tr>
                        ${specRow}
                    </thead>
                    <tbody></tbody>
                </table>
            </div>`;

        // Append to body so _buildGrid()'s container.innerHTML doesn't destroy the drawer
        document.body.appendChild(drawer);

        // Push chart scroll area up so it's not hidden behind the drawer
        const chartScroll = document.getElementById('me-chart-scroll');
        if (chartScroll) chartScroll.style.bottom = DRAWER_H + 'px';

        // Initial render + auto-apply best solution
        _renderOptTable();
        setTimeout(() => window.meApplyOptSolution(0), 80);
    };

    // Restore original T lines when optimization drawer is closed
    window.meRestoreOptTargets = function () {
        if (!_meRenderCtx) return;
        const { factorOrder, targetOrder, byTarget, targetYRange } = _meRenderCtx;
        let changed = false;
        targetOrder.forEach(t => {
            const ts = _meTargetStats[t] || {};
            if (ts._origTargetMean !== undefined) {
                ts.target_mean = ts._origTargetMean;
                delete ts._origTargetMean;
                changed = true;
            }
        });
        if (changed) {
            targetOrder.forEach((t, ti) => {
                factorOrder.forEach((f, fi) => {
                    const d = byTarget[t]?.[f];
                    if (d) _drawCell(ti, fi, f, t, d, targetYRange[t]);
                });
            });
        }
    };

    window.meRunSmartRange = async function () {
        if (!_meRenderCtx || !window._meOptSolutions) return;
        const { solutions, free_factors } = window._meOptSolutions;
        const { targetOrder } = _meRenderCtx;

        // Use selected solution or #1
        const selIdx = window._meOptSelected ?? 0;
        const sol = solutions[selIdx];
        if (!sol) return;

        const threshold = parseFloat(document.getElementById('me-smart-range-threshold')?.value || '1');

        // Build center_x from solution
        const centerX = {};
        free_factors.forEach(f => { if (sol.params[f] != null) centerX[f] = sol.params[f]; });

        // Build target specs
        const targetSpecs = {};
        targetOrder.forEach(t => {
            const ts = _meTargetStats[t] || {};
            if (ts.usl != null || ts.lsl != null)
                targetSpecs[t] = { usl: ts.usl ?? null, lsl: ts.lsl ?? null };
        });

        // Show loading in button
        const btn = document.querySelector('[onclick="meRunSmartRange()"]');
        if (btn) { btn.disabled = true; btn.textContent = '⏳ 計算中…'; }

        // Remove old result panel
        document.getElementById('me-smart-range-result')?.remove();

        const sid = typeof getSessionId === 'function' ? getSessionId() : 'default';
        try {
            const resp = await fetch(`/api/data-prep/me-smart-range?session_id=${sid}`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    center_x: centerX,
                    oos_threshold: threshold,
                    n_simulations: 5000,
                    target_specs: targetSpecs,
                    fixed_factors: [..._meFixedFactors, ..._meBgFactors],
                    fixed_values: Object.fromEntries([..._meFixedFactors, ..._meBgFactors].map(f => [f, _meSliderVals[f] ?? (_meColStats[f]?.median ?? 0)])),
                }),
            });
            const data = await resp.json();
            if (!resp.ok) throw new Error(data.detail || '計算失敗');
            _meShowSmartRangeResult(data, selIdx);
        } catch (e) {
            alert('智慧化區間計算失敗：' + e.message);
        } finally {
            if (btn) { btn.disabled = false; btn.textContent = '🎯 智慧化區間'; }
        }
    };

    function _meShowSmartRangeResult(data, solIdx) {
        document.getElementById('me-smart-range-result')?.remove();
        const factors = data.factors || {};
        const factorList = Object.entries(factors).sort((a, b) => b[1].sensitivity - a[1].sensitivity);

        const rows = factorList.map(([f, r]) => {
            const atLimit = r.at_limit;
            const limitTag = atLimit ? `<span style="font-size:9px;color:#f59e0b;margin-left:4px;">▲資料邊界</span>` : '';
            return `<tr style="border-bottom:1px solid #f1f5f9;">
                <td style="padding:5px 8px;font-size:11px;color:#334155;max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${f}">${f}${limitTag}</td>
                <td style="padding:5px 8px;font-size:11px;text-align:center;color:#0ea5e9;font-weight:700;">${r.center.toFixed(4)}</td>
                <td style="padding:5px 8px;font-size:11px;text-align:center;color:#2563eb;">${r.lsl.toFixed(4)}</td>
                <td style="padding:5px 8px;font-size:11px;text-align:center;color:#dc2626;">${r.usl.toFixed(4)}</td>
                <td style="padding:5px 8px;font-size:11px;text-align:center;color:#64748b;">±${r.half_width.toFixed(4)}</td>
            </tr>`;
        }).join('');

        const oosColor = data.oos_achieved > data.oos_threshold ? '#dc2626' : '#10b981';
        const panel = document.createElement('div');
        panel.id = 'me-smart-range-result';
        panel.style.cssText = `position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);
            z-index:20000;background:#fff;border-radius:12px;box-shadow:0 8px 32px rgba(0,0,0,0.18);
            min-width:520px;max-width:700px;max-height:80vh;display:flex;flex-direction:column;`;
        panel.innerHTML = `
            <div style="padding:14px 18px;border-bottom:1px solid #e2e8f0;display:flex;align-items:center;justify-content:space-between;flex-shrink:0;">
                <div>
                    <span style="font-size:14px;font-weight:700;color:#0ea5e9;">🎯 智慧化 X 操作區間</span>
                    <span style="font-size:11px;color:#94a3b8;margin-left:8px;">以方案 #${solIdx + 1} 為中心點</span>
                </div>
                <div style="display:flex;align-items:center;gap:8px;">
                    <span style="font-size:11px;color:${oosColor};font-weight:700;">實際 OOS: ${data.oos_achieved.toFixed(2)}%（目標 ≤ ${data.oos_threshold}%）</span>
                    <button onclick="document.getElementById('me-smart-range-result').remove()"
                        style="border:none;background:none;font-size:16px;cursor:pointer;color:#94a3b8;padding:0 4px;">✕</button>
                </div>
            </div>
            <div style="overflow-y:auto;flex:1;">
                <table style="width:100%;border-collapse:collapse;">
                    <thead style="background:#f8fafc;position:sticky;top:0;">
                        <tr>
                            <th style="padding:6px 8px;font-size:10px;color:#94a3b8;text-align:left;font-weight:600;">參數</th>
                            <th style="padding:6px 8px;font-size:10px;color:#0ea5e9;text-align:center;font-weight:600;">建議中心</th>
                            <th style="padding:6px 8px;font-size:10px;color:#2563eb;text-align:center;font-weight:600;">建議 LSL</th>
                            <th style="padding:6px 8px;font-size:10px;color:#dc2626;text-align:center;font-weight:600;">建議 USL</th>
                            <th style="padding:6px 8px;font-size:10px;color:#64748b;text-align:center;font-weight:600;">容許範圍</th>
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
            <div style="padding:10px 18px;border-top:1px solid #e2e8f0;display:flex;gap:8px;justify-content:flex-end;flex-shrink:0;">
                <button onclick="_meApplySmartRange()"
                    style="font-size:12px;padding:5px 16px;background:#0ea5e9;color:#fff;border:none;
                           border-radius:6px;cursor:pointer;font-weight:600;">套用至 X 參數規格</button>
                <button onclick="document.getElementById('me-smart-range-result').remove()"
                    style="font-size:12px;padding:5px 16px;background:#f1f5f9;color:#475569;border:1px solid #e2e8f0;
                           border-radius:6px;cursor:pointer;">關閉</button>
            </div>`;
        document.body.appendChild(panel);
        window._meLastSmartRange = data;
    }

    window._meApplySmartRange = function () {
        const data = window._meLastSmartRange;
        if (!data?.factors) return;
        Object.entries(data.factors).forEach(([f, r]) => {
            if (!_meParamSpecs[f]) _meParamSpecs[f] = {};
            _meParamSpecs[f].usl = r.usl;
            _meParamSpecs[f].lsl = r.lsl;
        });
        // Redraw charts + histograms with new X-spec lines
        if (_meRenderCtx) {
            const { factorOrder, targetOrder, byTarget, targetYRange } = _meRenderCtx;
            targetOrder.forEach((t, ti) => {
                factorOrder.forEach((f, fi) => {
                    const d = byTarget[t]?.[f];
                    if (d) _drawCell(ti, fi, f, t, d, targetYRange[t]);
                });
            });
            factorOrder.forEach((f, fi) => _drawHistCell(fi, f));
            _updateXSpecLabels();
        }
        document.getElementById('me-smart-range-result')?.remove();
    };

    window.meApplyOptSolution = function (idx) {
        if (!window._meOptSolutions || !_meRenderCtx) return;
        const { solutions, free_factors } = window._meOptSolutions;
        const sol = solutions[idx];
        if (!sol) return;

        // Highlight selected row in drawer
        if (window._meOptSelected != null) {
            const prev = document.getElementById('me-opt-row-' + window._meOptSelected);
            if (prev) prev.style.background = '';
        }
        window._meOptSelected = idx;
        const row = document.getElementById('me-opt-row-' + idx);
        if (row) row.style.background = '#ede9fe';

        const { factorOrder } = _meRenderCtx;
        free_factors.forEach(f => {
            const val = sol.params[f];
            if (val == null) return;
            _meSliderVals[f] = val;
            const fi = factorOrder.indexOf(f);
            if (fi >= 0) {
                const sv = document.getElementById('me-sv-' + fi);
                if (sv) { if (sv.tagName === 'INPUT') sv.value = val.toFixed(4); else sv.textContent = val.toFixed(3); }
                _drawHistCell(fi, f);
            }
        });
        // Immediately show sol.targets (XGBoost values from optimization) in left panel
        // This avoids the brief flash of inaccurate ALE approximation
        if (sol.targets && _meRenderCtx) {
            _applyXGBoostPred(
                Object.fromEntries(
                    Object.entries(sol.targets).map(([t, v]) => [t, { predicted: v }])
                )
            );
        } else {
            _updatePredictions();
        }
    };

    window.meToggleRealData = function (checked) {
        _meShowRealData = checked;
        if (!_meRenderCtx) return;
        const { factorOrder, targetOrder, byTarget, targetYRange } = _meRenderCtx;
        targetOrder.forEach((t, ti) => {
            factorOrder.forEach((f, fi) => {
                const d = byTarget[t]?.[f];
                if (d) _drawCell(ti, fi, f, t, d, targetYRange[t]);
            });
        });
    };

    // Parameter panel modal
    window.meShowSettings = function () {
        const existing = document.getElementById('me-settings-modal');
        if (existing) { existing.remove(); return; }
        const modal = document.createElement('div');
        modal.id = 'me-settings-modal';
        modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.4);z-index:9999;display:flex;align-items:center;justify-content:center;';
        modal.innerHTML = `
            <div style="background:#fff;border-radius:12px;box-shadow:0 20px 60px rgba(0,0,0,.25);
                        width:400px;max-width:95vw;">
                <div style="padding:14px 18px;border-bottom:1px solid #e2e8f0;display:flex;align-items:center;justify-content:space-between;">
                    <div style="font-size:14px;font-weight:700;color:#1e293b;">⚙ 基礎設定</div>
                    <button onclick="document.getElementById('me-settings-modal').remove()"
                        style="background:none;border:none;font-size:18px;cursor:pointer;color:#94a3b8;line-height:1;">✕</button>
                </div>
                <div style="padding:18px 20px;display:flex;flex-direction:column;gap:16px;">

                    <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;">
                        <div>
                            <div style="font-size:12px;font-weight:600;color:#1e293b;">散佈點數量</div>
                            <div style="font-size:11px;color:#94a3b8;margin-top:2px;">「真實資料」疊加點數（重新分析後生效）</div>
                        </div>
                        <select id="ms-max-scatter"
                            style="border:1px solid #e2e8f0;border-radius:6px;padding:4px 8px;font-size:12px;color:#1e293b;background:#fff;">
                            <option value="100"  ${_meSettings.max_scatter===100  ?'selected':''}>100 點</option>
                            <option value="300"  ${_meSettings.max_scatter===300  ?'selected':''}>300 點</option>
                            <option value="500"  ${_meSettings.max_scatter===500  ?'selected':''}>500 點</option>
                            <option value="1000" ${_meSettings.max_scatter===1000 ?'selected':''}>1000 點</option>
                            <option value="2000" ${_meSettings.max_scatter===2000 ?'selected':''}>2000 點（預設）</option>
                            <option value="9999" ${_meSettings.max_scatter===9999 ?'selected':''}>全部</option>
                        </select>
                    </div>

                    <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;">
                        <div>
                            <div style="font-size:12px;font-weight:600;color:#1e293b;">ALE / PDP 格子數</div>
                            <div style="font-size:11px;color:#94a3b8;margin-top:2px;">格子越多曲線越細緻，但計算越慢（重新分析後生效）</div>
                        </div>
                        <input type="number" id="ms-grid-res" min="10" max="200" step="10"
                            value="${_meSettings.grid_resolution}"
                            style="width:72px;border:1px solid #e2e8f0;border-radius:6px;padding:4px 8px;font-size:12px;text-align:center;">
                    </div>

                    <div style="border-top:1px solid #f1f5f9;padding-top:14px;">
                        <div style="font-size:12px;font-weight:600;color:#1e293b;margin-bottom:10px;">圖表線條顯示</div>
                        ${[
                            ['ms-show-y-spec',  _meSettings.show_y_spec, 'Y 軸規格線',  'USL / LSL / T 水平虛線'],
                            ['ms-show-x-spec',  _meSettings.show_x_spec, 'X 軸規格線',  '參數 USL / LSL 垂直虛線（橘 / 青）'],
                            ['ms-show-pred',    _meSettings.show_pred,   '預測線',       '紫色 Pred 水平線'],
                        ].map(([id, checked, label, desc]) => `
                        <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:8px;">
                            <div>
                                <div style="font-size:12px;color:#1e293b;">${label}</div>
                                <div style="font-size:11px;color:#94a3b8;">${desc}</div>
                            </div>
                            <input type="checkbox" id="${id}" ${checked?'checked':''}
                                style="width:16px;height:16px;cursor:pointer;accent-color:#6366f1;">
                        </div>`).join('')}
                    </div>

                </div>
                <div style="padding:12px 18px;border-top:1px solid #e2e8f0;display:flex;justify-content:flex-end;gap:8px;">
                    <button onclick="document.getElementById('me-settings-modal').remove()"
                        style="padding:6px 16px;border:1px solid #e2e8f0;border-radius:6px;background:#f8fafc;font-size:12px;cursor:pointer;color:#475569;">取消</button>
                    <button onclick="meSaveSettings()"
                        style="padding:6px 16px;background:#6366f1;color:#fff;border:none;border-radius:6px;font-size:12px;cursor:pointer;font-weight:600;">儲存</button>
                </div>
            </div>`;
        document.body.appendChild(modal);
        modal.addEventListener('click', e => { if (e.target === modal) modal.remove(); });
        const _esc = e => { if (e.key === 'Escape') { modal.remove(); document.removeEventListener('keydown', _esc); } };
        document.addEventListener('keydown', _esc);
    };

    window.meSaveSettings = function () {
        const scatter = parseInt(document.getElementById('ms-max-scatter')?.value) || 2000;
        const gridRes = parseInt(document.getElementById('ms-grid-res')?.value) || 50;
        _meSettings.max_scatter     = Math.max(50, scatter);
        _meSettings.grid_resolution = Math.max(10, Math.min(200, gridRes));
        _meSettings.show_y_spec = document.getElementById('ms-show-y-spec')?.checked ?? true;
        _meSettings.show_x_spec = document.getElementById('ms-show-x-spec')?.checked ?? true;
        _meSettings.show_pred   = document.getElementById('ms-show-pred')?.checked   ?? true;
        document.getElementById('me-settings-modal')?.remove();
        // Redraw all cells immediately
        if (_meRenderCtx) {
            const { targetOrder, factorOrder, byTarget, targetYRange } = _meRenderCtx;
            targetOrder.forEach((t, ti) => {
                factorOrder.forEach((f, fi) => {
                    const d = byTarget[t]?.[f];
                    if (d) _drawCell(ti, fi, f, t, d, targetYRange[t]);
                });
            });
            factorOrder.forEach((f, fi) => _drawHistCell(fi, f));
        }
    };

    // ── Unified Analysis Settings Panel ───────────────────────────────
    window.meShowAnalysisPanel = function (tab) {
        tab = tab || 'params';
        // Close any legacy modals
        ['me-param-modal','me-opt-modal','me-sim-modal'].forEach(id => document.getElementById(id)?.remove());
        // Toggle if already open on same tab
        const existing = document.getElementById('me-analysis-panel');
        if (existing) { existing.remove(); return; }
        if (!_meRenderCtx) return;

        const { targetOrder, factorOrder } = _meRenderCtx;
        const allFactors = [
            ...factorOrder.map(f => ({ name: f, type: '控制' })),
            ..._meBgFactors.filter(f => !factorOrder.includes(f)).map(f => ({ name: f, type: '背景' })),
        ];
        const fmtV = (v, d=4) => (v != null && !isNaN(v)) ? Number(v).toFixed(d) : '';
        const keyOf = s => s.replace(/[^a-zA-Z0-9]/g, '_');

        // ── Tab 1: 參數設定 ──────────────────────────────────────────
        const paramRows = allFactors.map(({ name, type }) => {
            const st   = _meColStats[name] || { min: 0, max: 1, median: 0.5 };
            const cur  = _meSliderVals[name] ?? st.median;
            const isCtrl = type === '控制';
            const fixed  = _meFixedFactors.has(name);
            const defSig = ((st.p95 ?? st.max ?? cur+1) - (st.p5 ?? st.min ?? cur-1)) / 6;
            const sig    = _meSimSigmas[name] ?? defSig;
            const ps     = _meParamSpecs[name] || {};
            const k      = keyOf(name);
            const specInp = (id, val, clr) => isCtrl
                ? `<input type="number" step="any" value="${fmtV(val)}" id="${id}" placeholder="—"
                    style="width:68px;border:1px solid ${clr}55;border-radius:4px;padding:2px 4px;font-size:11px;text-align:center;color:${clr};">`
                : '<span style="color:#cbd5e1;font-size:11px;">—</span>';
            return `<tr style="border-bottom:1px solid #f1f5f9;">
                <td style="padding:5px 8px;font-size:11px;max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${name}">${name}</td>
                <td style="padding:5px 8px;text-align:center;">
                    <span style="padding:1px 6px;border-radius:10px;font-size:10px;font-weight:600;
                        background:${isCtrl?'#ede9fe':'#e0f2fe'};color:${isCtrl?'#6d28d9':'#0369a1'};">${type}</span>
                </td>
                <td style="padding:5px 8px;text-align:center;">
                    <input type="number" step="any" value="${fmtV(cur)}" id="mp-val-${k}"
                        style="width:82px;border:1px solid #e2e8f0;border-radius:4px;padding:2px 5px;font-size:11px;text-align:center;">
                </td>
                <td style="padding:5px 8px;font-size:11px;text-align:center;color:#475569;">${fmtV(st.max)}</td>
                <td style="padding:5px 8px;font-size:11px;text-align:center;color:#475569;">${fmtV(st.min)}</td>
                <td style="padding:5px 8px;text-align:center;">
                    ${isCtrl
                        ? `<input type="checkbox" ${fixed?'checked':''} onchange="meToggleFixed('${name}',this.checked)" style="width:13px;height:13px;cursor:pointer;">`
                        : '<span style="color:#cbd5e1;font-size:11px;">—</span>'}
                </td>
                <td style="padding:5px 4px;text-align:center;">${specInp('mp-xusl-'+k, ps.usl, '#f97316')}</td>
                <td style="padding:5px 4px;text-align:center;">${specInp('mp-xlsl-'+k, ps.lsl, '#0891b2')}</td>
                <td style="padding:5px 8px;text-align:center;">
                    ${isCtrl
                        ? `<input type="number" step="any" min="0" value="${fmtV(sig)}" id="mp-sig-${k}"
                            style="width:66px;border:1px solid #e2e8f0;border-radius:4px;padding:2px 5px;font-size:11px;text-align:center;">`
                        : '<span style="color:#cbd5e1;font-size:11px;">—</span>'}
                </td>
            </tr>`;
        }).join('');

        const tabParams = `
            <div style="display:flex;align-items:center;justify-content:flex-end;gap:6px;padding:6px 8px 4px;border-bottom:1px solid #f1f5f9;">
                <span style="font-size:11px;color:#64748b;">X-USL/LSL 試算：</span>
                <select id="mp-calc-method"
                    style="border:1px solid #e2e8f0;border-radius:5px;padding:3px 6px;font-size:11px;color:#334155;">
                    <option value="p5p95">p5 / p95</option>
                    <option value="mean3s">mean ± 3σ</option>
                    <option value="minmax">min / max</option>
                </select>
                <button onclick="meCalcParamSpecs()"
                    style="padding:3px 10px;background:#f97316;color:#fff;border:none;border-radius:5px;font-size:11px;font-weight:600;cursor:pointer;">⟳ 試算</button>
                <button onclick="meClearParamSpecs()"
                    style="padding:3px 8px;background:#f8fafc;color:#64748b;border:1px solid #e2e8f0;border-radius:5px;font-size:11px;cursor:pointer;">✕ 清除</button>
            </div>
            <table style="width:100%;border-collapse:collapse;">
                <thead>
                    <tr style="background:#f8fafc;border-bottom:2px solid #e2e8f0;position:sticky;top:0;z-index:1;">
                        <th style="padding:7px 8px;font-size:11px;font-weight:700;color:#475569;text-align:left;">參數名稱</th>
                        <th style="padding:7px 8px;font-size:11px;font-weight:700;color:#475569;text-align:center;">類型</th>
                        <th style="padding:7px 8px;font-size:11px;font-weight:700;color:#475569;text-align:center;">目前值</th>
                        <th style="padding:7px 8px;font-size:11px;font-weight:700;color:#475569;text-align:center;">最大值</th>
                        <th style="padding:7px 8px;font-size:11px;font-weight:700;color:#475569;text-align:center;">最小值</th>
                        <th style="padding:7px 8px;font-size:11px;font-weight:700;color:#475569;text-align:center;">固定</th>
                        <th style="padding:7px 8px;font-size:11px;font-weight:700;color:#f97316;text-align:center;" title="X軸上限（橘線）">X-USL</th>
                        <th style="padding:7px 8px;font-size:11px;font-weight:700;color:#0891b2;text-align:center;" title="X軸下限（青線）">X-LSL</th>
                        <th style="padding:7px 8px;font-size:11px;font-weight:700;color:#8b5cf6;text-align:center;" title="模擬用標準差">σ (模擬)</th>
                    </tr>
                </thead>
                <tbody>${paramRows}</tbody>
            </table>`;

        // ── Tab 2: 目標規格 ──────────────────────────────────────────
        const targetSpecRows = targetOrder.map(t => {
            const ts  = _meTargetStats[t] || {};
            const k   = keyOf(t);
            const inp = (id, val, ph, col) =>
                `<input type="number" id="${id}" value="${fmtV(val)}" step="any" placeholder="${ph}"
                    style="width:86px;border:1px solid ${col}44;border-radius:4px;padding:3px 5px;font-size:11px;text-align:center;color:${col};">`;
            return `<tr style="border-bottom:1px solid #f1f5f9;">
                <td style="padding:6px 8px;font-size:11px;font-weight:600;color:#334155;">${t}</td>
                <td style="padding:6px 8px;">${inp('mt-tv-'+k, ts.target_mean??ts.mean, '目標值', '#6366f1')}</td>
                <td style="padding:6px 8px;">${inp('mt-usl-'+k, ts.usl, 'USL', '#dc2626')}</td>
                <td style="padding:6px 8px;">${inp('mt-lsl-'+k, ts.lsl, 'LSL', '#2563eb')}</td>
            </tr>`;
        }).join('');

        const tabTarget = `
            <div style="font-size:11px;color:#94a3b8;margin:10px 14px 8px;">此設定供「最佳化」與「量測模擬」共用</div>
            <table style="width:100%;border-collapse:collapse;">
                <thead>
                    <tr style="background:#f8fafc;border-bottom:2px solid #e2e8f0;">
                        <th style="padding:7px 8px;font-size:11px;font-weight:700;color:#475569;text-align:left;">目標</th>
                        <th style="padding:7px 8px;font-size:11px;font-weight:700;color:#6366f1;text-align:center;">目標值</th>
                        <th style="padding:7px 8px;font-size:11px;font-weight:700;color:#dc2626;text-align:center;">USL</th>
                        <th style="padding:7px 8px;font-size:11px;font-weight:700;color:#2563eb;text-align:center;">LSL</th>
                    </tr>
                </thead>
                <tbody>${targetSpecRows}</tbody>
            </table>`;

        // ── Tab 3: 最佳化 ─────────────────────────────────────────────
        const optDirRows = targetOrder.map(t => {
            const k = keyOf(t);
            const dirOpts = ['target','min','max'].map(d =>
                `<option value="${d}" ${d==='target'?'selected':''}>${d==='max'?'最大化':d==='min'?'最小化':'接近目標值'}</option>`
            ).join('');
            return `<tr style="border-bottom:1px solid #f1f5f9;">
                <td style="padding:6px 8px;font-size:11px;font-weight:600;color:#334155;">${t}</td>
                <td style="padding:6px 8px;">
                    <select id="mo-dir-${k}"
                        style="border:1px solid #e2e8f0;border-radius:4px;padding:3px 8px;font-size:11px;">${dirOpts}</select>
                </td>
            </tr>`;
        }).join('');

        const tabOptimize = `
            <div style="font-size:11px;color:#94a3b8;margin:10px 14px 6px;">USL / LSL 請至「目標規格」tab 設定</div>
            <table style="width:100%;border-collapse:collapse;margin-bottom:12px;">
                <thead>
                    <tr style="background:#f8fafc;border-bottom:2px solid #e2e8f0;">
                        <th style="padding:7px 8px;font-size:11px;font-weight:700;color:#475569;text-align:left;">目標</th>
                        <th style="padding:7px 8px;font-size:11px;font-weight:700;color:#475569;text-align:left;">最佳化方向</th>
                    </tr>
                </thead>
                <tbody>${optDirRows}</tbody>
            </table>
            <div style="display:flex;align-items:center;gap:10px;padding:0 8px 10px;">
                <span style="font-size:12px;font-weight:600;color:#475569;">解的數量</span>
                <input type="number" id="mo-n-solutions" value="50" min="5" max="200" step="5"
                    style="width:80px;border:1px solid #e2e8f0;border-radius:6px;padding:4px 8px;font-size:12px;">
            </div>
            <div id="mo-progress" style="display:none;padding:0 8px 8px;">
                <div style="display:flex;justify-content:space-between;font-size:11px;color:#64748b;margin-bottom:4px;">
                    <span id="mo-progress-phase">執行中…</span>
                    <span id="mo-progress-pct"></span>
                </div>
                <div style="background:#e2e8f0;border-radius:4px;height:6px;">
                    <div id="mo-progress-bar" style="background:#10b981;height:6px;border-radius:4px;width:0%;transition:width .3s;"></div>
                </div>
            </div>
            <div id="me-opt-results-area"></div>`;

        // ── Tab 4: 量測模擬 ────────────────────────────────────────────
        const allFixed = new Set([..._meFixedFactors, ..._meBgFactors]);
        const freeFactors = factorOrder.filter(f => !allFixed.has(f));
        const simDistRows = freeFactors.map(f => {
            const k      = keyOf(f);
            const cs     = _meColStats[f] || {};
            const ps     = _meParamSpecs[f] || {};
            const hasSpec = ps.usl != null && ps.lsl != null;
            // If X-USL/LSL are set, derive distribution from them; otherwise fall back to data stats
            const defMean = hasSpec ? (ps.usl + ps.lsl) / 2 : (_meSliderVals[f] ?? cs.median ?? 0);
            const defSig  = hasSpec ? (ps.usl - ps.lsl) / 6
                                    : ((cs.p95 ?? cs.max ?? defMean+1) - (cs.p5 ?? cs.min ?? defMean-1)) / 6;
            const mean   = defMean;
            const sig    = hasSpec ? defSig : (_meSimSigmas[f] ?? defSig);
            const dist   = _meSimDists[f]  ?? 'normal';
            const low    = hasSpec ? ps.lsl : (cs.p5  ?? cs.min  ?? defMean - defSig * 3);
            const high   = hasSpec ? ps.usl : (cs.p95 ?? cs.max  ?? defMean + defSig * 3);
            return `<tr style="border-bottom:1px solid #f8fafc;">
                <td style="padding:5px 8px;font-size:11px;color:#334155;max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${f}">${f}</td>
                <td style="padding:5px 6px;">
                    <select id="ms-dist-${k}" onchange="meSimDistChange('${k}')"
                        style="border:1px solid #e2e8f0;border-radius:4px;padding:2px 5px;font-size:11px;width:72px;">
                        <option value="normal"  ${dist==='normal' ?'selected':''}>常態</option>
                        <option value="uniform" ${dist==='uniform'?'selected':''}>均勻</option>
                    </select>
                </td>
                <td id="ms-cell-normal-${k}" style="padding:5px 4px;display:${dist==='normal'?'flex':'none'};gap:4px;align-items:center;">
                    <span style="font-size:10px;color:#64748b;">μ</span>
                    <input type="number" id="ms-mean-${k}" value="${fmtV(mean)}" step="any"
                        style="width:72px;border:1px solid #e2e8f0;border-radius:4px;padding:2px 4px;font-size:11px;text-align:center;">
                    <span style="font-size:10px;color:#64748b;">σ</span>
                    <input type="number" id="ms-std-${k}" value="${fmtV(sig)}" step="any" min="0"
                        style="width:60px;border:1px solid #e2e8f0;border-radius:4px;padding:2px 4px;font-size:11px;text-align:center;">
                </td>
                <td id="ms-cell-uniform-${k}" style="padding:5px 4px;display:${dist==='uniform'?'flex':'none'};gap:4px;align-items:center;">
                    <span style="font-size:10px;color:#64748b;">Min</span>
                    <input type="number" id="ms-low-${k}" value="${fmtV(low)}" step="any"
                        style="width:70px;border:1px solid #e2e8f0;border-radius:4px;padding:2px 4px;font-size:11px;text-align:center;">
                    <span style="font-size:10px;color:#64748b;">Max</span>
                    <input type="number" id="ms-high-${k}" value="${fmtV(high)}" step="any"
                        style="width:70px;border:1px solid #e2e8f0;border-radius:4px;padding:2px 4px;font-size:11px;text-align:center;">
                </td>
            </tr>`;
        }).join('');

        const tabSimulate = `
            <div style="font-size:11px;color:#94a3b8;margin:10px 14px 6px;">規格從「目標規格」tab 讀取</div>
            <div style="overflow:auto;max-height:280px;border:1px solid #e2e8f0;border-radius:8px;margin:0 2px 10px;">
                <table style="width:100%;border-collapse:collapse;">
                    <thead>
                        <tr style="background:#f8fafc;position:sticky;top:0;z-index:1;">
                            <th style="padding:6px 8px;font-size:11px;color:#64748b;font-weight:600;text-align:left;">參數</th>
                            <th style="padding:6px 8px;font-size:11px;color:#64748b;font-weight:600;text-align:left;">分佈</th>
                            <th style="padding:6px 8px;font-size:11px;color:#64748b;font-weight:600;text-align:left;" colspan="2">數值</th>
                        </tr>
                    </thead>
                    <tbody>${simDistRows}</tbody>
                </table>
            </div>
            <div style="display:flex;align-items:center;gap:10px;padding:0 8px 10px;">
                <span style="font-size:12px;font-weight:600;color:#475569;">模擬次數</span>
                <input type="number" id="ms-n-sim" value="1000" min="100" max="10000" step="100"
                    style="width:90px;border:1px solid #e2e8f0;border-radius:6px;padding:4px 8px;font-size:12px;">
                <span style="font-size:11px;color:#94a3b8;">(100 ~ 10000)</span>
            </div>
            <div id="ms-progress" style="display:none;padding:0 8px 8px;">
                <div style="font-size:11px;color:#64748b;margin-bottom:4px;" id="ms-progress-phase">模擬中…</div>
                <div style="background:#e2e8f0;border-radius:4px;height:6px;">
                    <div id="ms-progress-bar" style="background:#8b5cf6;height:6px;border-radius:4px;width:0%;transition:width .3s;"></div>
                </div>
            </div>
            <div id="ms-results"></div>`;

        // ── Build modal ───────────────────────────────────────────────
        const modal = document.createElement('div');
        modal.id = 'me-analysis-panel';
        modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.45);z-index:9999;display:flex;align-items:center;justify-content:center;';
        modal.innerHTML = `
            <div style="background:#fff;border-radius:12px;box-shadow:0 20px 60px rgba(0,0,0,.25);
                        width:740px;max-width:96vw;max-height:88vh;display:flex;flex-direction:column;">
                <!-- Header -->
                <div style="padding:12px 18px;border-bottom:1px solid #e2e8f0;display:flex;align-items:center;justify-content:space-between;flex-shrink:0;">
                    <div style="font-size:14px;font-weight:700;color:#1e293b;">⚙ 主效應分析設定</div>
                    <button onclick="document.getElementById('me-analysis-panel').remove()"
                        style="background:none;border:none;font-size:20px;cursor:pointer;color:#94a3b8;line-height:1;">✕</button>
                </div>
                <!-- Tab bar -->
                <div style="display:flex;border-bottom:2px solid #e2e8f0;flex-shrink:0;padding:0 4px;">
                    <button id="me-panel-tab-params"   onclick="meAnalysisSwitchTab('params')"   style="${_tabBtnStyle(false)}">參數設定</button>
                    <button id="me-panel-tab-target"   onclick="meAnalysisSwitchTab('target')"   style="${_tabBtnStyle(false)}">目標規格</button>
                    <button id="me-panel-tab-optimize" onclick="meAnalysisSwitchTab('optimize')" style="${_tabBtnStyle(false)}">⚡ 最佳化</button>
                    <button id="me-panel-tab-simulate" onclick="meAnalysisSwitchTab('simulate')" style="${_tabBtnStyle(false)}">🎲 量測模擬</button>
                </div>
                <!-- Tab contents -->
                <div style="overflow:auto;flex:1;padding:4px 10px 10px;">
                    <div id="me-panel-content-params">${tabParams}</div>
                    <div id="me-panel-content-target">${tabTarget}</div>
                    <div id="me-panel-content-optimize" style="padding:4px 4px;">${tabOptimize}</div>
                    <div id="me-panel-content-simulate" style="padding:4px 4px;">${tabSimulate}</div>
                </div>
                <!-- Footer -->
                <div style="padding:10px 18px;border-top:1px solid #e2e8f0;display:flex;justify-content:flex-end;gap:8px;flex-shrink:0;">
                    <button onclick="document.getElementById('me-analysis-panel').remove()"
                        style="padding:6px 16px;border:1px solid #e2e8f0;border-radius:6px;background:#f8fafc;font-size:12px;cursor:pointer;color:#475569;">取消</button>
                    <button id="me-panel-action-btn"
                        style="padding:6px 18px;background:#6366f1;color:#fff;border:none;border-radius:6px;font-size:12px;cursor:pointer;font-weight:600;">套用</button>
                </div>
            </div>`;
        document.body.appendChild(modal);
        modal.addEventListener('click', e => { if (e.target === modal) modal.remove(); });
        const _esc = e => { if (e.key === 'Escape') { modal.remove(); document.removeEventListener('keydown', _esc); } };
        document.addEventListener('keydown', _esc);
        meAnalysisSwitchTab(tab);
    };

    function _tabBtnStyle(active) {
        return active
            ? 'background:none;border:none;border-bottom:2px solid #6366f1;margin-bottom:-2px;padding:8px 14px;font-size:12px;font-weight:600;color:#6366f1;cursor:pointer;'
            : 'background:none;border:none;border-bottom:2px solid transparent;margin-bottom:-2px;padding:8px 14px;font-size:12px;color:#64748b;cursor:pointer;';
    }

    window.meAnalysisSwitchTab = function (tab) {
        ['params','target','optimize','simulate'].forEach(t => {
            const btn  = document.getElementById('me-panel-tab-' + t);
            const cont = document.getElementById('me-panel-content-' + t);
            const active = t === tab;
            if (btn) btn.style.cssText = _tabBtnStyle(active);
            if (cont) cont.style.display = active ? 'block' : 'none';
        });
        const actionBtn = document.getElementById('me-panel-action-btn');
        if (!actionBtn) return;
        if (tab === 'params') {
            actionBtn.textContent = '套用';
            actionBtn.style.background = '#6366f1';
            actionBtn.onclick = window.meApplyParamPanel;
        } else if (tab === 'target') {
            actionBtn.textContent = '套用';
            actionBtn.style.background = '#6366f1';
            actionBtn.onclick = window.meApplyTargetSpecs;
        } else if (tab === 'optimize') {
            actionBtn.textContent = '▶ 執行最佳化';
            actionBtn.style.background = '#10b981';
            actionBtn.dataset.role = 'optimize';
            actionBtn.onclick = window.meRunOptimize;
        } else if (tab === 'simulate') {
            actionBtn.textContent = '▶ 執行模擬';
            actionBtn.style.background = '#8b5cf6';
            actionBtn.dataset.role = 'simulate';
            actionBtn.onclick = window.meRunSimulation;
        }
    };

    window.meCalcParamSpecs = function () {
        if (!_meRenderCtx) return;
        const { factorOrder } = _meRenderCtx;
        const method = document.getElementById('mp-calc-method')?.value || 'p5p95';
        const allFactors = [...factorOrder, ..._meBgFactors.filter(f => !factorOrder.includes(f))];
        allFactors.forEach(name => {
            if (_meBgFactors.includes(name) && !factorOrder.includes(name)) return; // skip bg-only
            const st = _meColStats[name] || {};
            let usl, lsl;
            if (method === 'p5p95') {
                usl = st.p95 ?? st.max;
                lsl = st.p5  ?? st.min;
            } else if (method === 'mean3s') {
                const m = st.mean ?? st.median ?? 0;
                const s = st.std  ?? ((st.max - st.min) / 6) ?? 1;
                usl = m + 3 * s;
                lsl = m - 3 * s;
            } else { // minmax
                usl = st.max;
                lsl = st.min;
            }
            const k = name.replace(/[^a-zA-Z0-9]/g, '_');
            const xuslEl = document.getElementById('mp-xusl-' + k);
            const xlslEl = document.getElementById('mp-xlsl-' + k);
            const fmt = v => (v != null && !isNaN(v)) ? Number(v).toFixed(4) : '';
            if (xuslEl) xuslEl.value = fmt(usl);
            if (xlslEl) xlslEl.value = fmt(lsl);
        });
    };

    window.meClearParamSpecs = function () {
        if (!_meRenderCtx) return;
        const { factorOrder } = _meRenderCtx;
        const allFactors = [...factorOrder, ..._meBgFactors.filter(f => !factorOrder.includes(f))];
        allFactors.forEach(name => {
            const k = name.replace(/[^a-zA-Z0-9]/g, '_');
            const xuslEl = document.getElementById('mp-xusl-' + k);
            const xlslEl = document.getElementById('mp-xlsl-' + k);
            if (xuslEl) xuslEl.value = '';
            if (xlslEl) xlslEl.value = '';
        });
    };

    window.meApplyTargetSpecs = function () {
        if (!_meRenderCtx) return;
        const { targetOrder, factorOrder, byTarget, targetBaseYRange, targetYRange } = _meRenderCtx;
        const keyOf = s => s.replace(/[^a-zA-Z0-9]/g, '_');
        targetOrder.forEach(t => {
            const k = keyOf(t);
            if (!_meTargetStats[t]) _meTargetStats[t] = {};
            const tv  = parseFloat(document.getElementById('mt-tv-'  + k)?.value);
            const usl = parseFloat(document.getElementById('mt-usl-' + k)?.value);
            const lsl = parseFloat(document.getElementById('mt-lsl-' + k)?.value);
            if (!isNaN(tv))  _meTargetStats[t].target_mean = tv;
            if (!isNaN(usl)) _meTargetStats[t].usl = usl;
            if (!isNaN(lsl)) _meTargetStats[t].lsl = lsl;
        });
        // Recompute y-ranges and redraw
        const analysisMethod = _meRenderCtx.analysisMethod || 'ale';
        targetOrder.forEach(t => {
            const ts = _meTargetStats[t] || {};
            const aleOffset = analysisMethod === 'ale' ? (ts.mean || 0) : 0;
            let vals = [];
            factorOrder.forEach(f => {
                const d = byTarget[t]?.[f];
                if (d?.ale) vals = vals.concat(d.ale.filter(v => v != null).map(v => v + aleOffset));
            });
            if (ts.usl != null) vals.push(ts.usl);
            if (ts.lsl != null) vals.push(ts.lsl);
            if (ts.ucl != null) vals.push(ts.ucl);
            if (ts.lcl != null) vals.push(ts.lcl);
            if (ts.target_mean != null) vals.push(ts.target_mean);
            if (ts.mean != null) vals.push(ts.mean);
            if (vals.length === 0) vals = [0, 1];
            const rawMin = Math.min(...vals), rawMax = Math.max(...vals);
            const pad12 = (rawMax - rawMin) * 0.12 || 1;
            targetBaseYRange[t] = { min: rawMin - pad12, max: rawMax + pad12 };
            targetYRange[t] = { ...targetBaseYRange[t] };
        });
        targetOrder.forEach((t, ti) => {
            factorOrder.forEach((f, fi) => {
                const d = byTarget[t]?.[f];
                if (d) _drawCell(ti, fi, f, t, d, targetYRange[t]);
            });
        });
        document.getElementById('me-analysis-panel')?.remove();
    };

    window.meToggleFixed = function (name, checked) {
        if (checked) _meFixedFactors.add(name);
        else _meFixedFactors.delete(name);
        // Disable/enable the corresponding slider immediately
        if (!_meRenderCtx) return;
        const { factorOrder } = _meRenderCtx;
        const fi = factorOrder.indexOf(name);
        if (fi < 0) return;
        const inp = document.getElementById('me-sv-' + fi);
        if (inp) { inp.disabled = checked; inp.style.background = checked ? '#f1f5f9' : '#fff'; }
    };

    window.meApplyParamPanel = function () {
        if (!_meRenderCtx) return;
        const { factorOrder } = _meRenderCtx;
        const allFactors = [...factorOrder, ..._meBgFactors.filter(f => !factorOrder.includes(f))];
        allFactors.forEach(name => {
            const id = 'mp-val-' + name.replace(/[^a-zA-Z0-9]/g,'_');
            const inp = document.getElementById(id);
            if (!inp) return;
            const val = parseFloat(inp.value);
            if (isNaN(val)) return;
            _meSliderVals[name] = val;
            const fi = factorOrder.indexOf(name);
            if (fi >= 0) {
                const sv = document.getElementById('me-sv-' + fi);
                if (sv) { if (sv.tagName === 'INPUT') sv.value = val.toFixed(4); else sv.textContent = val.toFixed(3); }
            }
            const k = name.replace(/[^a-zA-Z0-9]/g,'_');
            const sigInp = document.getElementById('mp-sig-' + k);
            if (sigInp) {
                const sigVal = parseFloat(sigInp.value);
                if (!isNaN(sigVal) && sigVal >= 0) _meSimSigmas[name] = sigVal;
            }
            // X-axis parameter specs
            if (!_meParamSpecs[name]) _meParamSpecs[name] = {};
            const xuslVal = parseFloat(document.getElementById('mp-xusl-' + k)?.value);
            const xlslVal = parseFloat(document.getElementById('mp-xlsl-' + k)?.value);
            _meParamSpecs[name].usl = isNaN(xuslVal) ? null : xuslVal;
            _meParamSpecs[name].lsl = isNaN(xlslVal) ? null : xlslVal;
        });
        // Redraw all cells + histograms
        const { targetOrder, byTarget, targetYRange } = _meRenderCtx;
        targetOrder.forEach((t, ti) => {
            factorOrder.forEach((f, fi) => {
                const d = byTarget[t]?.[f];
                if (d) _drawCell(ti, fi, f, t, d, targetYRange[t]);
            });
        });
        factorOrder.forEach((f, fi) => _drawHistCell(fi, f));
        _updateXSpecLabels();
        _updatePredictions();
        document.getElementById('me-analysis-panel')?.remove();
    };

    window.meShowFactorChart = function () {};

    function _emptyState(msg) {
        return `<div style="display:flex;align-items:center;justify-content:center;width:100%;height:100%;color:#94a3b8;flex-direction:column;gap:8px;">
            <div style="font-size:28px;">📊</div><div style="font-size:13px;">${msg}</div></div>`;
    }

    // ============ FILTER HELPERS ============
    window.meFilterAvailControl = function (v) { _filterList('me-avail-control', v); };
    window.meFilterSelControl = function (v) { _filterList('me-sel-control', v); };
    window.meFilterAvailBg = function (v) { _filterList('me-avail-bg', v); };
    window.meFilterSelBg = function (v) { _filterList('me-sel-bg', v); };

    // ── Measurement Simulation (Monte Carlo) ─────────────────────────

    window.meSimDistChange = function (key) {
        const sel = document.getElementById('ms-dist-' + key);
        if (!sel) return;
        const isNormal = sel.value === 'normal';
        const nc = document.getElementById('ms-cell-normal-' + key);
        const uc = document.getElementById('ms-cell-uniform-' + key);
        if (nc) nc.style.display = isNormal ? 'flex' : 'none';
        if (uc) uc.style.display = isNormal ? 'none' : 'flex';
    };

    window.meRunSimulation = async function () {
        if (!_meRenderCtx) return;

        const { targetOrder, factorOrder } = _meRenderCtx;
        const allFixed = new Set([..._meFixedFactors, ..._meBgFactors]);
        const freeFactors = factorOrder.filter(f => !allFixed.has(f));

        const paramDists = freeFactors.map(f => {
            const key = f.replace(/[^a-zA-Z0-9]/g, '_');
            const distType = document.getElementById('ms-dist-' + key)?.value || 'normal';
            // Save dist type to persistent state
            _meSimDists[f] = distType;
            const mean = parseFloat(document.getElementById('ms-mean-' + key)?.value) || 0;
            const std  = parseFloat(document.getElementById('ms-std-'  + key)?.value) || 1;
            // Save sigma to persistent state
            if (!isNaN(std) && std >= 0) _meSimSigmas[f] = std;
            const low  = parseFloat(document.getElementById('ms-low-'  + key)?.value) || 0;
            const high = parseFloat(document.getElementById('ms-high-' + key)?.value) || 1;
            return { factor: f, dist_type: distType, mean, std, low, high };
        });

        // Read target specs from _meTargetStats (shared via Target Specs tab)
        const targetSpecs = {};
        targetOrder.forEach(t => {
            const ts = _meTargetStats[t] || {};
            targetSpecs[t] = {};
            if (ts.usl != null) targetSpecs[t].usl = ts.usl;
            if (ts.lsl != null) targetSpecs[t].lsl = ts.lsl;
        });

        const nSim = parseInt(document.getElementById('ms-n-sim')?.value) || 1000;

        const runBtn = document.getElementById('me-panel-action-btn');
        if (runBtn) { runBtn.disabled = true; runBtn.style.background = '#a78bfa'; runBtn.style.cursor = 'not-allowed'; runBtn.textContent = '⏳ 模擬中…'; }

        const prog = document.getElementById('ms-progress');
        const progBar = document.getElementById('ms-progress-bar');
        const progPhase = document.getElementById('ms-progress-phase');
        if (prog) prog.style.display = 'block';
        if (progBar) { progBar.style.width = '0%'; progBar.style.background = '#8b5cf6'; }

        // Animate progress bar (no backend polling, just fake progress)
        let _fakeTimer = null;
        let _fakePct = 0;
        _fakeTimer = setInterval(() => {
            _fakePct = Math.min(_fakePct + (100 - _fakePct) * 0.08, 95);
            if (progBar) progBar.style.width = _fakePct + '%';
        }, 200);

        const sid = typeof getSessionId === 'function' ? getSessionId() : 'default';
        try {
            const body = {
                param_distributions: paramDists,
                fixed_factors: [...allFixed],
                fixed_values: Object.fromEntries([...allFixed].map(f => [f, _meSliderVals[f] ?? (_meColStats[f]?.median ?? 0)])),
                n_simulations: nSim,
                target_specs: targetSpecs,
            };
            const resp = await fetch(`/api/data-prep/me-simulate?session_id=${sid}`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            clearInterval(_fakeTimer);
            if (progBar) progBar.style.width = '100%';
            const data = await resp.json();
            if (!resp.ok) throw new Error(data.detail || '模擬失敗');

            if (progPhase) progPhase.textContent = `✓ 完成 ${data.n_simulations} 次模擬`;
            _renderSimResults(data, targetOrder, targetSpecs);

            // Store results and rebuild main grid to show sim column
            _meSimResults = { data, targetSpecs };
            _buildGrid();

            // Close panel and scroll to the simulation column on the right
            document.getElementById('me-analysis-panel')?.remove();
            requestAnimationFrame(() => {
                const scroll = document.getElementById('me-chart-scroll');
                if (scroll) scroll.scrollTo({ left: scroll.scrollWidth, behavior: 'smooth' });
            });

            if (runBtn) { runBtn.disabled = false; runBtn.style.background = '#8b5cf6'; runBtn.style.cursor = 'pointer'; runBtn.textContent = '▶ 重新模擬'; }
        } catch (e) {
            clearInterval(_fakeTimer);
            if (progBar) { progBar.style.width = '100%'; progBar.style.background = '#ef4444'; }
            if (progPhase) { progPhase.style.color = '#ef4444'; progPhase.textContent = '❌ ' + e.message; }
            if (runBtn) { runBtn.disabled = false; runBtn.style.background = '#8b5cf6'; runBtn.style.cursor = 'pointer'; runBtn.textContent = '▶ 執行模擬'; }
        }
    };

    function _renderSimResults(data, targetOrder, targetSpecs) {
        const container = document.getElementById('ms-results');
        if (!container) return;

        const targets = data.targets || {};
        const cards = targetOrder.map(t => {
            const r = targets[t];
            if (!r) return '';
            const oosPct = r.out_of_spec_pct;
            const oosStr = oosPct != null ? `${oosPct.toFixed(2)}%` : '—';
            const oosColor = oosPct == null ? '#64748b' : oosPct > 5 ? '#dc2626' : oosPct > 1 ? '#d97706' : '#10b981';
            const canvasId = 'ms-canvas-' + t.replace(/[^a-zA-Z0-9]/g, '_');
            return `<div style="border:1px solid #e2e8f0;border-radius:10px;padding:12px;margin-bottom:12px;">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                    <span style="font-size:12px;font-weight:700;color:#1e293b;">${t}</span>
                    <div style="display:flex;gap:16px;font-size:11px;">
                        <span style="color:#475569;">μ = <b>${r.mean.toFixed(4)}</b></span>
                        <span style="color:#475569;">σ = <b>${r.std.toFixed(4)}</b></span>
                        <span style="color:${oosColor};font-weight:700;">超規: ${oosStr}</span>
                    </div>
                </div>
                <canvas id="${canvasId}" width="560" height="120"
                    style="width:100%;height:120px;display:block;border-radius:6px;"></canvas>
            </div>`;
        }).join('');

        container.innerHTML = `<div style="font-size:12px;font-weight:600;color:#475569;margin-bottom:8px;">模擬結果</div>${cards}`;

        // Draw funnel charts after DOM update
        requestAnimationFrame(() => {
            targetOrder.forEach(t => {
                const r = targets[t];
                if (!r) return;
                const specs = targetSpecs[t] || {};
                const canvasId = 'ms-canvas-' + t.replace(/[^a-zA-Z0-9]/g, '_');
                _drawSimFunnel(canvasId, r.values, specs.usl ?? null, specs.lsl ?? null, r.mean);
            });
        });
    }

    function _drawSimFunnel(canvasId, values, usl, lsl, mean) {
        const canvas = document.getElementById(canvasId);
        if (!canvas) return;
        const dpr = window.devicePixelRatio || 1;
        const W = canvas.offsetWidth || 560;
        const H = 120;
        canvas.width  = W * dpr;
        canvas.height = H * dpr;
        const ctx = canvas.getContext('2d');
        ctx.scale(dpr, dpr);

        const PAD_L = 8, PAD_R = 8, PAD_T = 10, PAD_B = 22;
        const innerW = W - PAD_L - PAD_R;
        const innerH = H - PAD_T - PAD_B;
        const midY = PAD_T + innerH / 2;

        // Value range for x-axis
        const arr = values;
        let vMin = Math.min(...arr), vMax = Math.max(...arr);
        if (usl != null) { vMax = Math.max(vMax, usl); }
        if (lsl != null) { vMin = Math.min(vMin, lsl); }
        const span = vMax - vMin || 1;
        const margin = span * 0.08;
        vMin -= margin; vMax += margin;
        const vSpan = vMax - vMin;
        const xScale = v => PAD_L + (v - vMin) / vSpan * innerW;

        // KDE using Gaussian kernel (Silverman bandwidth)
        const n = arr.length;
        const std = Math.sqrt(arr.reduce((s, v) => s + (v - mean) ** 2, 0) / n) || 1;
        const bw = 1.06 * std * Math.pow(n, -0.2);
        const KDE_PTS = 200;
        const kdeX = [], kdeY = [];
        for (let i = 0; i <= KDE_PTS; i++) {
            const x = vMin + (i / KDE_PTS) * vSpan;
            let dens = 0;
            for (let j = 0; j < n; j++) {
                const u = (x - arr[j]) / bw;
                dens += Math.exp(-0.5 * u * u);
            }
            dens /= (n * bw * Math.sqrt(2 * Math.PI));
            kdeX.push(x);
            kdeY.push(dens);
        }
        const maxDens = Math.max(...kdeY) || 1;
        const halfH = innerH / 2 * 0.88;
        const pyScale = d => d / maxDens * halfH;

        // Background
        ctx.fillStyle = '#f8fafc';
        ctx.fillRect(0, 0, W, H);

        // Out-of-spec shading
        const drawOosShade = (xA, xB, color) => {
            const xa = Math.max(xA, PAD_L), xb = Math.min(xB, PAD_L + innerW);
            if (xa >= xb) return;
            ctx.fillStyle = color;
            ctx.fillRect(xa, PAD_T, xb - xa, innerH);
        };
        if (usl != null) drawOosShade(xScale(usl), PAD_L + innerW, 'rgba(239,68,68,0.08)');
        if (lsl != null) drawOosShade(PAD_L, xScale(lsl), 'rgba(37,99,235,0.08)');

        // KDE filled funnel shape (upper + lower symmetric)
        const buildPath = (upper) => {
            ctx.beginPath();
            for (let i = 0; i <= KDE_PTS; i++) {
                const px = xScale(kdeX[i]);
                const py = upper ? midY - pyScale(kdeY[i]) : midY + pyScale(kdeY[i]);
                i === 0 ? ctx.moveTo(px, midY) : ctx.lineTo(px, py);
            }
            ctx.lineTo(xScale(kdeX[KDE_PTS]), midY);
            ctx.closePath();
        };

        // Fill upper half
        ctx.save();
        buildPath(true);
        const grad = ctx.createLinearGradient(PAD_L, 0, PAD_L + innerW, 0);
        grad.addColorStop(0, 'rgba(139,92,246,0.15)');
        grad.addColorStop(0.5, 'rgba(139,92,246,0.55)');
        grad.addColorStop(1, 'rgba(139,92,246,0.10)');
        ctx.fillStyle = grad;
        ctx.fill();
        ctx.restore();

        // Fill lower half (mirror)
        ctx.save();
        buildPath(false);
        ctx.fillStyle = grad;
        ctx.fill();
        ctx.restore();

        // KDE outline
        ctx.beginPath();
        for (let i = 0; i <= KDE_PTS; i++) {
            const px = xScale(kdeX[i]);
            const pyU = midY - pyScale(kdeY[i]);
            i === 0 ? ctx.moveTo(px, pyU) : ctx.lineTo(px, pyU);
        }
        ctx.strokeStyle = 'rgba(109,40,217,0.7)';
        ctx.lineWidth = 1.5;
        ctx.stroke();

        ctx.beginPath();
        for (let i = 0; i <= KDE_PTS; i++) {
            const px = xScale(kdeX[i]);
            const pyL = midY + pyScale(kdeY[i]);
            i === 0 ? ctx.moveTo(px, pyL) : ctx.lineTo(px, pyL);
        }
        ctx.strokeStyle = 'rgba(109,40,217,0.7)';
        ctx.lineWidth = 1.5;
        ctx.stroke();

        // Center dashed line
        ctx.beginPath();
        ctx.setLineDash([4, 3]);
        ctx.moveTo(PAD_L, midY); ctx.lineTo(PAD_L + innerW, midY);
        ctx.strokeStyle = 'rgba(109,40,217,0.35)';
        ctx.lineWidth = 1;
        ctx.stroke();
        ctx.setLineDash([]);

        // USL / LSL vertical lines
        const drawVLine = (v, color, label) => {
            const px = xScale(v);
            if (px < PAD_L || px > PAD_L + innerW) return;
            ctx.beginPath();
            ctx.setLineDash([4, 3]);
            ctx.moveTo(px, PAD_T); ctx.lineTo(px, PAD_T + innerH);
            ctx.strokeStyle = color;
            ctx.lineWidth = 1.5;
            ctx.stroke();
            ctx.setLineDash([]);
            ctx.fillStyle = color;
            ctx.font = '9px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText(label, px, PAD_T - 2);
        };
        if (usl != null) drawVLine(usl, '#dc2626', 'USL');
        if (lsl != null) drawVLine(lsl, '#2563eb', 'LSL');

        // Mean line
        drawVLine(mean, '#0f172a', '');
        const meanPx = xScale(mean);
        ctx.fillStyle = '#0f172a';
        ctx.font = 'bold 9px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('μ', meanPx, PAD_T - 2);

        // X-axis tick labels
        ctx.fillStyle = '#94a3b8';
        ctx.font = '9px sans-serif';
        ctx.textAlign = 'center';
        const ticks = 5;
        for (let i = 0; i <= ticks; i++) {
            const v = vMin + (i / ticks) * vSpan;
            const px = xScale(v);
            const lbl = Math.abs(v) >= 100 ? v.toFixed(1) : Math.abs(v) >= 1 ? v.toFixed(2) : v.toFixed(3);
            ctx.fillText(lbl, px, H - 4);
        }
    }

    // Draw vertical violin (KDE) for simulation results in the sim column
    function _drawSimColCell(ti, target, yRange, opts) {
        const zoom = opts?.zoom || false;
        const canvasId = opts?.canvasId ?? `me-sim-col-${ti}`;
        const canvas = document.getElementById(canvasId);
        if (!canvas) return;
        const simData = _meSimResults?.data?.targets?.[target];
        if (!simData?.values?.length) return;

        const dpr = zoom ? (window.devicePixelRatio || 1) : (window.devicePixelRatio || 1);
        const W = canvas.clientWidth || (zoom ? 340 : 72);
        const H = canvas.clientHeight || (zoom ? 400 : _meCellHeight);
        if (W < 4 || H < 4) return;
        canvas.width = W * dpr; canvas.height = H * dpr;
        canvas.style.width = W + 'px'; canvas.style.height = H + 'px';
        const ctx = canvas.getContext('2d');
        ctx.scale(dpr, dpr);

        const PAD_T = 6, PAD_B = zoom ? 36 : 24, PAD_L = zoom ? 10 : 4, PAD_R = zoom ? 10 : 4;
        const innerW = W - PAD_L - PAD_R;
        const innerH = H - PAD_T - PAD_B;
        const midX = PAD_L + innerW / 2;

        // Y-axis matches main chart range
        const yMin = yRange?.min ?? Math.min(...simData.values);
        const yMax = yRange?.max ?? Math.max(...simData.values);
        const ySpan = yMax - yMin || 1;
        const yScale = v => PAD_T + (1 - (v - yMin) / ySpan) * innerH;

        // KDE using Gaussian kernel
        const arr = simData.values;
        const n = arr.length;
        const mean = simData.mean;
        const std = Math.sqrt(arr.reduce((s, v) => s + (v - mean) ** 2, 0) / n) || 1;
        const bw = 1.06 * std * Math.pow(n, -0.2);
        const KDE_PTS = 120;
        const kdeV = [], kdeD = [];
        for (let i = 0; i <= KDE_PTS; i++) {
            const v = yMin + (i / KDE_PTS) * ySpan;
            let dens = 0;
            for (let j = 0; j < n; j++) {
                const u = (v - arr[j]) / bw;
                dens += Math.exp(-0.5 * u * u);
            }
            dens /= (n * bw * Math.sqrt(2 * Math.PI));
            kdeV.push(v);
            kdeD.push(dens);
        }
        const maxDens = Math.max(...kdeD) || 1;
        const halfW = innerW / 2 * 0.88;
        const dxScale = d => d / maxDens * halfW;

        // Background
        ctx.fillStyle = '#fdf4ff';
        ctx.fillRect(0, 0, W, H);

        const specs = _meSimResults.targetSpecs?.[target] || {};
        const usl = specs.usl ?? null;
        const lsl = specs.lsl ?? null;

        // Out-of-spec shading (above USL = red, below LSL = blue)
        const drawOosShade = (vA, vB, color) => {
            const ya = Math.min(yScale(vA), yScale(vB));
            const yb = Math.max(yScale(vA), yScale(vB));
            const yTop = Math.max(ya, PAD_T), yBot = Math.min(yb, PAD_T + innerH);
            if (yTop >= yBot) return;
            ctx.fillStyle = color;
            ctx.fillRect(PAD_L, yTop, innerW, yBot - yTop);
        };
        if (usl != null) drawOosShade(usl, yMax, 'rgba(239,68,68,0.10)');
        if (lsl != null) drawOosShade(yMin, lsl, 'rgba(37,99,235,0.10)');

        // Violin fill (left + right symmetric)
        const grad = ctx.createLinearGradient(0, PAD_T, 0, PAD_T + innerH);
        grad.addColorStop(0,   'rgba(139,92,246,0.12)');
        grad.addColorStop(0.5, 'rgba(139,92,246,0.55)');
        grad.addColorStop(1,   'rgba(139,92,246,0.12)');

        ctx.save();
        ctx.beginPath();
        // Right outline
        ctx.moveTo(midX, yScale(kdeV[0]));
        for (let i = 1; i <= KDE_PTS; i++) ctx.lineTo(midX + dxScale(kdeD[i]), yScale(kdeV[i]));
        // Left outline (reverse)
        for (let i = KDE_PTS; i >= 0; i--) ctx.lineTo(midX - dxScale(kdeD[i]), yScale(kdeV[i]));
        ctx.closePath();
        ctx.fillStyle = grad;
        ctx.fill();
        // Outline
        ctx.strokeStyle = 'rgba(109,40,217,0.65)';
        ctx.lineWidth = 1.2;
        ctx.stroke();
        ctx.restore();

        // Center dashed line (vertical center axis)
        ctx.beginPath();
        ctx.setLineDash([3, 3]);
        ctx.moveTo(midX, PAD_T); ctx.lineTo(midX, PAD_T + innerH);
        ctx.strokeStyle = 'rgba(109,40,217,0.25)';
        ctx.lineWidth = 1;
        ctx.stroke();
        ctx.setLineDash([]);

        // USL / LSL horizontal lines
        const drawHSpec = (v, color, label) => {
            if (v == null || v < yMin || v > yMax) return;
            const py = yScale(v);
            ctx.beginPath();
            ctx.setLineDash([4, 3]);
            ctx.moveTo(PAD_L, py); ctx.lineTo(PAD_L + innerW, py);
            ctx.strokeStyle = color;
            ctx.lineWidth = 1.5;
            ctx.stroke();
            ctx.setLineDash([]);
            const fs = zoom ? 11 : 8;
            ctx.fillStyle = color;
            ctx.font = `bold ${fs}px Arial`;
            ctx.textAlign = 'right';
            ctx.textBaseline = 'middle';
            ctx.fillText(label, PAD_L + innerW - 1, py - (zoom ? 7 : 5));
        };
        drawHSpec(usl, '#dc2626', 'USL');
        drawHSpec(lsl, '#2563eb', 'LSL');

        // Mean horizontal line
        const meanPy = yScale(mean);
        if (meanPy >= PAD_T && meanPy <= PAD_T + innerH) {
            ctx.beginPath();
            ctx.moveTo(PAD_L, meanPy); ctx.lineTo(PAD_L + innerW, meanPy);
            ctx.strokeStyle = '#0f172a';
            ctx.lineWidth = zoom ? 2 : 1.5;
            ctx.stroke();
            ctx.fillStyle = '#0f172a';
            ctx.font = `bold ${zoom ? 11 : 8}px Arial`;
            ctx.textAlign = 'right';
            ctx.textBaseline = 'middle';
            ctx.fillText('μ', PAD_L + innerW - 1, meanPy + (zoom ? 8 : 6));
        }

        // Real OOS from scatter data
        const scatterY = (() => {
            const sc = _meRenderCtx?.scatterData?.[target];
            if (!sc) return null;
            const firstFactor = Object.keys(sc)[0];
            return firstFactor ? sc[firstFactor].y : null;
        })();
        let realOosPct = null;
        if (scatterY && scatterY.length > 0 && (usl != null || lsl != null)) {
            const oos = scatterY.filter(v => (usl != null && v > usl) || (lsl != null && v < lsl)).length;
            realOosPct = oos / scatterY.length * 100;
        }

        const fsOos  = zoom ? 12 : 10;
        const fsReal = zoom ? 11 : 10;

        // 實際 OOS — top
        if (realOosPct != null) {
            const realColor = realOosPct > 5 ? '#dc2626' : realOosPct > 1 ? '#d97706' : '#10b981';
            ctx.fillStyle = realColor;
            ctx.font = `bold ${fsReal}px Arial`;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'top';
            ctx.fillText(`實際 ${realOosPct.toFixed(1)}%`, midX, PAD_T + 2);
        }

        // 模擬 OOS — bottom
        const oosPct = simData.out_of_spec_pct;
        if (oosPct != null) {
            const oosColor = oosPct > 5 ? '#dc2626' : oosPct > 1 ? '#d97706' : '#10b981';
            ctx.fillStyle = oosColor;
            ctx.font = `bold ${fsOos}px Arial`;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'bottom';
            ctx.fillText(`模擬 ${oosPct.toFixed(1)}%`, midX, H - 2);
        }
    }

    window.meZoomSimCell = function (ti) {
        if (!_meRenderCtx || !_meSimResults) return;
        const { targetOrder, targetYRange } = _meRenderCtx;
        const target = targetOrder[ti];
        if (!target) return;
        const clr = TARGET_COLORS[ti % TARGET_COLORS.length];

        document.getElementById('me-zoom-sim-panel')?.remove();
        const step3Rect = document.getElementById('me-step3-content')?.getBoundingClientRect();
        const panelW = 320;
        const panelTop = step3Rect ? Math.round(step3Rect.top + window.scrollY + 8) : 80;

        const panel = document.createElement('div');
        panel.id = 'me-zoom-sim-panel';
        panel.style.cssText = `position:fixed;top:${panelTop}px;right:16px;
            width:${panelW}px;background:#fff;border-radius:10px;
            box-shadow:0 8px 32px rgba(0,0,0,0.18);border:1px solid #e2e8f0;
            z-index:10001;display:flex;flex-direction:column;
            animation:meSlideIn 0.18s ease-out;`;

        const simData = _meSimResults.data?.targets?.[target];
        panel.innerHTML = `
            <div style="padding:7px 12px;border-bottom:1px solid #f1f5f9;display:flex;align-items:center;justify-content:space-between;">
                <div style="font-size:11px;font-weight:700;">
                    <span style="color:#a855f7;">🎲 量測模擬</span>
                    <span style="color:#94a3b8;margin:0 4px;">—</span>
                    <span style="color:${clr};">${target}</span>
                </div>
                <div style="display:flex;gap:8px;align-items:center;">
                    ${simData ? `<span style="font-size:10px;color:#64748b;">μ=${simData.mean.toFixed(3)} σ=${simData.std.toFixed(3)}</span>` : ''}
                    <button onclick="document.getElementById('me-zoom-sim-panel').remove()"
                        style="background:none;border:none;font-size:16px;cursor:pointer;color:#94a3b8;line-height:1;padding:0;">✕</button>
                </div>
            </div>
            <div style="padding:8px;">
                <canvas id="me-zoom-sim-canvas" style="width:100%;display:block;border-radius:4px;background:#fdf4ff;"></canvas>
            </div>`;
        document.body.appendChild(panel);

        const _esc = e => { if (e.key === 'Escape') { panel.remove(); document.removeEventListener('keydown', _esc); } };
        document.addEventListener('keydown', _esc);

        requestAnimationFrame(() => {
            const canvas = document.getElementById('me-zoom-sim-canvas');
            if (!canvas) return;
            const W = canvas.clientWidth || (panelW - 16);
            const H = Math.round(W * 1.4);
            canvas.style.height = H + 'px';
            _drawSimColCell(ti, target, targetYRange[target], { zoom: true, canvasId: 'me-zoom-sim-canvas' });
        });
    };

    function _filterList(id, kw) {
        const el = document.getElementById(id);
        if (!el) return;
        const lower = kw.toLowerCase();
        el.querySelectorAll('.rsm-pick-item').forEach(item => {
            item.style.display = item.dataset.col.toLowerCase().includes(lower) ? '' : 'none';
        });
    }

})(); // end IIFE
