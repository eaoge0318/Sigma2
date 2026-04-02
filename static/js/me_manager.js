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

    // ============ ADVANCED MODE: Correlation Scatter ============
    let _meCorrelations = {};       // { x_col: { y_col: corr } }
    let _meShapData     = {};       // { x_col: { y_col: signed_mean_shap } }
    let _meScatterMetric = 'corr';  // 'corr' | 'shap'
    let _meShowBalanceLine = false;
    const _meOverlaySettings = { zero: true, ol03: true, ol05: true, balance: false };
    // Returns active scatter data based on current metric mode
    function _meActiveData() { return _meScatterMetric === 'shap' ? _meShapData : _meCorrelations; }
    let _meScatterSelected = new Set();
    let _meScatterBox = null;       // { x0,y0,x1,y1 } in SVG coords during drag
    let _meScatterDragging = false;
    let _meScatterDragStart = null;
    let _meControlMode = 'normal';  // 'normal' | 'advanced'
    let _meRangeState = {};         // { col: { low, high } }  -100~100
    let _meRangeDrag = null;        // { col, handle, trackEl }
    let _meScatterMode = 'select';  // 'select' | 'zoom' | 'pan'
    let _meScatterZoom = { xMin: -1, xMax: 1, yMin: -1, yMax: 1 };
    let _mePanDrag = null; // { startX, startY, startZoom }

    window.meSetControlMode = function (mode) {
        _meControlMode = mode;
        const normalPane = document.getElementById('me-control-normal-pane');
        const advPane    = document.getElementById('me-control-advanced-pane');
        const btnN = document.getElementById('me-mode-btn-normal');
        const btnA = document.getElementById('me-mode-btn-advanced');
        if (!normalPane || !advPane) return;
        if (mode === 'advanced') {
            normalPane.style.display = 'none';
            advPane.style.display = 'flex';
            btnN.style.background = 'transparent'; btnN.style.color = '#64748b';
            btnA.style.background = '#2563eb';     btnA.style.color = '#fff';
            meFetchAndRenderScatter();
        } else {
            normalPane.style.display = 'grid';
            advPane.style.display = 'none';
            btnN.style.background = '#2563eb'; btnN.style.color = '#fff';
            btnA.style.background = 'transparent'; btnA.style.color = '#64748b';
        }
    };

    async function meFetchAndRenderScatter() {
        if (!_meTargets.length) return;
        const loadEl = document.getElementById('me-scatter-loading');
        if (loadEl) loadEl.style.display = 'flex';
        try {
            const sid    = typeof getSessionId === 'function' ? getSessionId() : (localStorage.getItem('sigma2_session_id') || 'default');
            const fileId = typeof currentFileId !== 'undefined' ? currentFileId : '';
            const yCols  = _meTargets.map(t => t.col);
            // 傳入 x_cols 讓後端只計算清洗後的欄位，排除被規則移除的欄位
            const xCols  = _meAllCols.filter(c => !yCols.includes(c));
            const resp   = await fetch(`/api/data-prep/correlations/${fileId}?session_id=${encodeURIComponent(sid)}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ y_cols: yCols, x_cols: xCols })
            });
            const data = await resp.json();
            _meCorrelations = data.correlations || {};
        } catch (e) {
            console.error('[ME] correlations fetch error:', e);
        }
        if (loadEl) loadEl.style.display = 'none';
        meSetupScatterAxes();
        meRenderScatterFilters();
        meSetScatterView('global');
    }

    // ── SHAP fetch with SSE progress ──────────────────────────────
    window.meFetchShap = async function () {
        if (!_meTargets.length) return;
        const sid    = typeof getSessionId === 'function' ? getSessionId() : (localStorage.getItem('sigma2_session_id') || 'default');
        const fileId = typeof currentFileId !== 'undefined' ? currentFileId : '';
        const yCols  = _meTargets.map(t => t.col);
        const xCols  = _meAllCols.filter(c => !yCols.includes(c));

        // Show progress overlay — 掛在整個散佈區塊 (me-scatter-area)，不管目前顯示哪個 view 都看得到
        let progressEl = document.getElementById('me-shap-progress');
        if (!progressEl) {
            progressEl = document.createElement('div');
            progressEl.id = 'me-shap-progress';
            progressEl.style.cssText = 'position:absolute;inset:0;background:rgba(255,255,255,.92);z-index:200;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;border-radius:8px;';
            const scatterArea = document.getElementById('me-scatter-area');
            if (scatterArea) scatterArea.appendChild(progressEl);
        }
        progressEl.style.display = 'flex';
        progressEl.innerHTML = `
            <div style="font-size:13px;font-weight:600;color:#1e293b;">計算 SHAP 值中…</div>
            <div style="width:260px;background:#e2e8f0;border-radius:99px;height:8px;overflow:hidden;">
                <div id="me-shap-bar" style="height:100%;background:#6366f1;border-radius:99px;width:0%;transition:width .3s;"></div>
            </div>
            <div id="me-shap-prog-text" style="font-size:11px;color:#64748b;">0 / ${yCols.length}</div>`;

        _meShapData = {};
        try {
            const resp = await fetch(`/api/data-prep/shap-scatter/${fileId}?session_id=${encodeURIComponent(sid)}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ y_cols: yCols, x_cols: xCols }),
            });
            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let buf = '';
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buf += decoder.decode(value, { stream: true });
                const lines = buf.split('\n');
                buf = lines.pop();
                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    try {
                        const msg = JSON.parse(line.slice(6));
                        if (msg.shap) _meShapData = msg.shap;
                        const pct = Math.round((msg.done / msg.total) * 100);
                        const bar = document.getElementById('me-shap-bar');
                        const txt = document.getElementById('me-shap-prog-text');
                        if (bar) bar.style.width = pct + '%';
                        if (txt) txt.textContent = `${msg.done} / ${msg.total}`;
                    } catch {}
                }
            }
        } catch (e) {
            console.error('[ME] SHAP fetch error:', e);
        }

        progressEl.style.display = 'none';

        // 正規化：每個 target 的 SHAP 值縮放到 [-1, 1]（保留方向，讓量綱一致）
        const yCols2 = _meTargets.map(t => t.col);
        yCols2.forEach(yCol => {
            const vals = Object.values(_meShapData).map(d => Math.abs(d[yCol] ?? 0)).filter(v => v > 0);
            if (!vals.length) return;
            const maxAbs = Math.max(...vals);
            if (maxAbs === 0) return;
            Object.keys(_meShapData).forEach(xCol => {
                if (_meShapData[xCol][yCol] != null)
                    _meShapData[xCol][yCol] = _meShapData[xCol][yCol] / maxAbs;
            });
        });

        // Switch to SHAP mode and re-render
        _meScatterMetric = 'shap';
        _meUpdateMetricToggle();
        meSetupScatterAxes();
        meRenderScatterFilters();
        _meRefreshPlot();
        if (document.getElementById('me-table-view')?.style.display !== 'none') meRenderCorrelationTable();
    };

    window.meToggleOverlaySettings = function (e) {
        e && e.stopPropagation();
        const panel = document.getElementById('me-overlay-settings-panel');
        if (!panel) return;
        panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
    };
    // Close on outside click
    document.addEventListener('click', function(e) {
        const wrap = document.getElementById('me-overlay-settings-wrap');
        const panel = document.getElementById('me-overlay-settings-panel');
        if (panel && wrap && !wrap.contains(e.target)) panel.style.display = 'none';
    });
    window.meOverlaySettingChange = function () {
        _meOverlaySettings.zero    = document.getElementById('me-ol-zero')?.checked ?? true;
        _meOverlaySettings.ol03    = document.getElementById('me-ol-03')?.checked   ?? true;
        _meOverlaySettings.ol05    = document.getElementById('me-ol-05')?.checked   ?? true;
        _meOverlaySettings.balance = document.getElementById('me-ol-balance')?.checked ?? false;
        _meShowBalanceLine = _meOverlaySettings.balance;
        // Update button style to indicate any non-default state
        const btn = document.getElementById('me-overlay-settings-btn');
        const hasCustom = !_meOverlaySettings.zero || !_meOverlaySettings.ol03 || !_meOverlaySettings.ol05 || _meOverlaySettings.balance;
        if (btn) {
            btn.style.background = hasCustom ? '#ede9fe' : '#f1f5f9';
            btn.style.color      = hasCustom ? '#7c3aed' : '#64748b';
        }
        _meRefreshPlot();
    };

    window.meSetScatterMetric = function (mode) {
        if (mode === 'shap' && !Object.keys(_meShapData).length) {
            meFetchShap();
            return;
        }
        _meScatterMetric = mode;
        _meUpdateMetricToggle();
        _meRefreshPlot();
        if (document.getElementById('me-table-view')?.style.display !== 'none') meRenderCorrelationTable();
    };

    function _meUpdateMetricToggle() {
        const btnCorr = document.getElementById('me-metric-corr-btn');
        const btnShap = document.getElementById('me-metric-shap-btn');
        if (!btnCorr || !btnShap) return;
        const setActive   = btn => { btn.style.background = '#6366f1'; btn.style.color = '#fff';     btn.style.fontWeight = '600'; };
        const setInactive = btn => { btn.style.background = 'transparent'; btn.style.color = '#64748b'; btn.style.fontWeight = '400'; };
        if (_meScatterMetric === 'corr') { setActive(btnCorr); setInactive(btnShap); }
        else                             { setInactive(btnCorr); setActive(btnShap); }
        // Update table header label
        const tableView = document.getElementById('me-table-view');
        if (tableView) {
            const label = _meScatterMetric === 'shap' ? 'SHAP（有方向性）' : 'Pearson r';
            const existing = tableView.querySelector('.me-metric-label');
            if (existing) existing.textContent = label;
        }
    }

    function meSetupScatterAxes() {
        const yCols = _meTargets.map(t => t.col);
        ['x','y'].forEach(axis => {
            const sel = document.getElementById(`me-scatter-axis-${axis}`);
            if (!sel) return;
            const prev = sel.value;
            sel.innerHTML = yCols.map((c,i) => `<option value="${c}">${c}</option>`).join('');
            // Default: X=first Y, Y=second Y (if exists)
            if (axis === 'x') sel.value = yCols[0] || '';
            if (axis === 'y') sel.value = yCols[1] || yCols[0] || '';
            if (yCols.includes(prev)) sel.value = prev;
        });
    }

    // ── Dual-handle range bar helpers ──────────────────────────────
    function _meDualRangeUpdate(col, low, high) {
        _meRangeState[col] = { low, high };
        const esc = CSS.escape(col);
        const lowPct  = (low  + 100) / 200 * 100;
        const highPct = (high + 100) / 200 * 100;
        const lowEl  = document.getElementById(`me-sf-low-${esc}`);
        const highEl = document.getElementById(`me-sf-high-${esc}`);
        const fillEl = document.getElementById(`me-sf-fill-${esc}`);
        const minLbl = document.getElementById(`me-sf-min-lbl-${esc}`);
        const maxLbl = document.getElementById(`me-sf-max-lbl-${esc}`);
        if (lowEl)  { lowEl.style.left  = `${lowPct}%`;  lowEl.dataset.val  = low; }
        if (highEl) { highEl.style.left = `${highPct}%`; highEl.dataset.val = high; }
        if (fillEl) { fillEl.style.left = `${lowPct}%`;  fillEl.style.width = `${highPct - lowPct}%`; }
        if (minLbl) minLbl.value = (low  / 100).toFixed(2);
        if (maxLbl) maxLbl.value = (high / 100).toFixed(2);
    }

    window.meRangeMouseDown = function (e, handle, col) {
        const trackEl = document.getElementById(`me-sf-track-${CSS.escape(col)}`);
        if (!trackEl) return;
        _meRangeDrag = { col, handle, trackEl };
        e.preventDefault();
        e.stopPropagation();
    };

    document.addEventListener('mousemove', function (e) {
        if (!_meRangeDrag) return;
        const { col, handle, trackEl } = _meRangeDrag;
        const rect = trackEl.getBoundingClientRect();
        const pct  = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
        const val  = Math.round(pct * 200 - 100);
        const st   = _meRangeState[col] || { low: -100, high: 100 };
        if (handle === 'low')  _meDualRangeUpdate(col, Math.min(val, st.high), st.high);
        else                   _meDualRangeUpdate(col, st.low, Math.max(val, st.low));
        _meRefreshPlot();
    });

    document.addEventListener('mouseup', function () { _meRangeDrag = null; });

    window.meRenderScatterFilters = function () {
        const container = document.getElementById('me-scatter-filters');
        if (!container) return;
        const filterCols = _meTargets.map(t => t.col);
        const axX = (document.getElementById('me-scatter-axis-x') || {}).value;
        const axY = (document.getElementById('me-scatter-axis-y') || {}).value;
        // Initialise state for new cols
        filterCols.forEach(col => { if (!_meRangeState[col]) _meRangeState[col] = { low: -100, high: 100 }; });
        container.innerHTML = filterCols.map(col => {
            const esc = CSS.escape(col);
            const isAxisX = col === axX, isAxisY = col === axY;
            const axisTag = isAxisX
                ? `<span style="background:#dbeafe;color:#2563eb;font-size:9px;padding:1px 5px;border-radius:4px;margin-left:4px;">X軸</span>`
                : isAxisY
                ? `<span style="background:#ede9fe;color:#7c3aed;font-size:9px;padding:1px 5px;border-radius:4px;margin-left:4px;">Y軸</span>` : '';
            const { low, high } = _meRangeState[col];
            const lowPct  = (low  + 100) / 200 * 100;
            const highPct = (high + 100) / 200 * 100;
            const colSafe = col.replace(/\\/g,'\\\\').replace(/'/g,"\\'");
            return `
            <div style="flex-shrink:0;">
                <div style="font-size:11px;color:#2563eb;margin-bottom:3px;font-weight:700;display:flex;align-items:center;">${col}${axisTag}</div>
                <div style="display:flex;gap:3px;margin-bottom:4px;">
                    <button onclick="meRangePresetOne('${colSafe}','all')"  style="flex:1;padding:3px 0;border:1px solid #e2e8f0;border-radius:4px;font-size:10px;color:#64748b;background:#f8fafc;cursor:pointer;">全選</button>
                    <button onclick="meRangePresetOne('${colSafe}','low')"  style="flex:1;padding:3px 0;border:1px solid #e2e8f0;border-radius:4px;font-size:10px;color:#64748b;background:#f8fafc;cursor:pointer;">低相關</button>
                    <button onclick="meRangePresetOne('${colSafe}','high')" style="flex:1;padding:3px 0;border:1px solid #e2e8f0;border-radius:4px;font-size:10px;color:#64748b;background:#f8fafc;cursor:pointer;">高相關</button>
                </div>
                <div id="me-sf-track-${esc}" style="position:relative;height:20px;margin:0 8px;overflow:visible;">
                    <div style="position:absolute;top:50%;left:0;right:0;height:3px;background:#e2e8f0;border-radius:2px;transform:translateY(-50%);"></div>
                    <div id="me-sf-fill-${esc}" style="position:absolute;top:50%;height:3px;background:#6366f1;border-radius:2px;transform:translateY(-50%);left:${lowPct}%;width:${highPct-lowPct}%;"></div>
                    <div id="me-sf-low-${esc}" data-val="${low}" style="position:absolute;top:50%;left:${lowPct}%;width:14px;height:14px;background:#fff;border:2px solid #6366f1;border-radius:50%;transform:translate(-50%,-50%);cursor:ew-resize;z-index:2;box-shadow:0 1px 3px rgba(0,0,0,.2);" onmousedown="meRangeMouseDown(event,'low','${colSafe}')"></div>
                    <div id="me-sf-high-${esc}" data-val="${high}" style="position:absolute;top:50%;left:${highPct}%;width:14px;height:14px;background:#fff;border:2px solid #6366f1;border-radius:50%;transform:translate(-50%,-50%);cursor:ew-resize;z-index:2;box-shadow:0 1px 3px rgba(0,0,0,.2);" onmousedown="meRangeMouseDown(event,'high','${colSafe}')"></div>
                </div>
                <div style="display:flex;justify-content:space-between;margin-top:2px;">
                    <input id="me-sf-min-lbl-${esc}" type="number" min="-1" max="1" step="0.05" value="${(low/100).toFixed(2)}"
                        style="width:46px;border:1px solid #e2e8f0;border-radius:4px;font-size:10px;padding:1px 3px;text-align:center;color:#475569;"
                        onchange="meRangeSetFromInput('low','${colSafe}',this.value)">
                    <input id="me-sf-max-lbl-${esc}" type="number" min="-1" max="1" step="0.05" value="${(high/100).toFixed(2)}"
                        style="width:46px;border:1px solid #e2e8f0;border-radius:4px;font-size:10px;padding:1px 3px;text-align:center;color:#475569;"
                        onchange="meRangeSetFromInput('high','${colSafe}',this.value)">
                </div>
            </div>`;
        }).join('');
    };

    window.meScatterFilterChange = function () { _meRefreshPlot(); };

    window.meRangeSetFromInput = function (handle, col, rawVal) {
        const v    = Math.max(-1, Math.min(1, parseFloat(rawVal) || 0));
        const intV = Math.round(v * 100);
        const st   = _meRangeState[col] || { low: -100, high: 100 };
        if (handle === 'low')  _meDualRangeUpdate(col, Math.min(intV, st.high), st.high);
        else                   _meDualRangeUpdate(col, st.low, Math.max(intV, st.low));
        _meRefreshPlot();
    };

    window.meRangePreset = function (preset) {
        const map = { all: [-100, 100], low: [-30, 30], high: [30, 100] };
        const [lo, hi] = map[preset] || [-100, 100];
        _meTargets.map(t => t.col).forEach(col => _meDualRangeUpdate(col, lo, hi));
        _meRefreshPlot();
    };

    window.meRangePresetOne = function (col, preset) {
        const map = { all: [-100, 100], low: [-30, 30], high: [30, 100] };
        const [lo, hi] = map[preset] || [-100, 100];
        _meDualRangeUpdate(col, lo, hi);
        _meRefreshPlot();
    };

    window.meSetPlotMode = function (mode) {
        _meScatterMode = mode;
        ['select','zoom','pan'].forEach(m => {
            const btn = document.getElementById(`me-plot-${m}-btn`);
            if (!btn) return;
            btn.style.background = mode === m ? '#2563eb' : '#f1f5f9';
            btn.style.color      = mode === m ? '#fff'    : '#64748b';
        });
    };

    window.meScatterZoomReset = function () {
        _meScatterZoom = { xMin: -1, xMax: 1, yMin: -1, yMax: 1 };
        const btn = document.getElementById('me-zoom-reset-btn');
        if (btn) btn.style.display = 'none';
        meRenderScatterPlot();
    };

    // Refresh the currently visible view (global or detail scatter)
    function _meRefreshPlot() {
        const gv = document.getElementById('me-global-view');
        if (gv && gv.style.display !== 'none') meRenderGlobalView();
        else meRenderScatterPlot();
    }

    function meGetFilteredCols() {
        const filterCols = _meTargets.map(t => t.col);
        return Object.keys(_meActiveData()).filter(xCol => {
            const row = _meActiveData()[xCol];
            return filterCols.every(fc => {
                const st   = _meRangeState[fc] || { low: -100, high: 100 };
                const corr = row[fc] !== undefined ? row[fc] : 0;
                return corr >= st.low / 100 && corr <= st.high / 100;
            });
        });
    }

    // ── View toggle: scatter ↔ table ───────────────────────────────
    window.meSetScatterView = function (view) {
        const gv  = document.getElementById('me-global-view');
        const sv  = document.getElementById('me-scatter-view');
        const tv  = document.getElementById('me-table-view');
        const bG  = document.getElementById('me-view-global-btn');
        const bS  = document.getElementById('me-view-scatter-btn');
        const bT  = document.getElementById('me-view-table-btn');
        if (!sv || !tv) return;
        // Hide all
        if (gv) gv.style.display = 'none';
        sv.style.display = 'none';
        tv.style.display = 'none';
        // Reset button styles
        const inactive = { background: 'transparent', color: '#64748b', fontWeight: 'normal' };
        const active   = { background: '#2563eb',     color: '#fff',     fontWeight: '600' };
        [bG, bS, bT].forEach(b => { if (b) Object.assign(b.style, inactive); });
        if (view === 'global') {
            if (gv) { gv.style.display = 'flex'; }
            if (bG) Object.assign(bG.style, active);
            meRenderGlobalView();
        } else if (view === 'scatter') {
            sv.style.display = 'flex';
            if (bS) Object.assign(bS.style, active);
            meRenderScatterPlot();
        } else {
            tv.style.display = 'block';
            if (bT) Object.assign(bT.style, active);
            meRenderCorrelationTable();
        }
    };

    // ── Global SPLOM view ──────────────────────────────────────────
    // Uses _meCorrelations (same data as 細部散佈圖): each dot = one X parameter,
    // positioned at (corr vs xCol, corr vs yCol) — clicking a cell enters 細部 view.
    let _meGlobalCellSize = 120; // px, user-adjustable

    window.meGlobalZoom = function (dir) {
        _meGlobalCellSize = Math.max(60, _meGlobalCellSize + dir * 30);
        const lbl = document.getElementById('me-global-size-lbl');
        if (lbl) lbl.textContent = _meGlobalCellSize + 'px';
        const gv = document.getElementById('me-global-view');
        if (gv) _meRenderSPLOMGrid(gv, _meTargets.map(t => t.col));
    };

    window.meRenderGlobalView = function () {
        const gv = document.getElementById('me-global-view');
        if (!gv) return;
        const yCols = _meTargets.map(t => t.col);
        const _emptyMsg = msg => {
            gv.innerHTML = `<div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;"><span style="font-size:12px;color:#94a3b8;">${msg}</span></div>`;
        };
        if (yCols.length < 2) { _emptyMsg('至少需要兩個目標參數才能顯示全域散佈圖'); return; }
        if (!Object.keys(_meActiveData()).length) { _emptyMsg('請先計算後顯示全域散佈圖'); return; }
        _meRenderSPLOM(gv, yCols);
    };

    function _meRenderSPLOM(container, yCols) {
        container.style.position = 'relative';

        const cs = _meGlobalCellSize;
        // Use position:absolute so inner content NEVER affects outer flex layout
        container.innerHTML = `
        <div style="position:absolute;inset:0;display:flex;flex-direction:column;">
            <div style="flex-shrink:0;display:flex;align-items:center;gap:6px;padding:7px 12px;border-bottom:1px solid #f1f5f9;">
                <span style="font-size:10px;color:#94a3b8;">格子大小</span>
                <button onclick="meGlobalZoom(-1)" style="width:24px;height:24px;border:1px solid #e2e8f0;border-radius:5px;background:#fff;color:#475569;font-size:15px;cursor:pointer;line-height:1;padding:0;">−</button>
                <span id="me-global-size-lbl" style="font-size:10px;color:#64748b;min-width:34px;text-align:center;">${cs}px</span>
                <button onclick="meGlobalZoom(+1)" style="width:24px;height:24px;border:1px solid #e2e8f0;border-radius:5px;background:#fff;color:#475569;font-size:15px;cursor:pointer;line-height:1;padding:0;">+</button>
            </div>
            <div style="flex:1;overflow:auto;padding:10px 12px;">
                <div id="me-global-grid"></div>
            </div>
        </div>`;
        _meRenderSPLOMGrid(container, yCols);
    }

    function _meRenderSPLOMGrid(container, yCols) {
        const gridEl = container.querySelector
            ? container.querySelector('#me-global-grid')
            : document.getElementById('me-global-grid');
        if (!gridEl) return;
        const n = yCols.length;
        const cs = _meGlobalCellSize;
        const gap = 4;
        const labelFontSize = cs < 100 ? 8 : cs < 150 ? 10 : 12;

        let html = `<div style="display:grid;grid-template-columns:repeat(${n},${cs}px);gap:${gap}px;">`;
        for (let r = 0; r < n; r++) {
            for (let c = 0; c < n; c++) {
                if (r === c) {
                    html += `<div style="width:${cs}px;height:${cs}px;border:1px solid #e2e8f0;border-radius:6px;background:#f8fafc;display:flex;align-items:center;justify-content:center;padding:6px;box-sizing:border-box;">
                        <span style="font-size:${labelFontSize}px;font-weight:700;color:#1e293b;text-align:center;word-break:break-all;line-height:1.4;">${yCols[r]}</span>
                    </div>`;
                } else {
                    const xCol = yCols[c];
                    const yCol = yCols[r];
                    const miniSvg = _meGlobalMiniScatter(xCol, yCol, cs, cs);
                    html += `<div onclick="meSetGlobalAxes('${xCol.replace(/'/g,"\\'")}','${yCol.replace(/'/g,"\\'")}');"
                        style="width:${cs}px;height:${cs}px;border:1px solid #e2e8f0;border-radius:6px;background:#fff;overflow:hidden;cursor:pointer;box-sizing:border-box;"
                        onmouseenter="this.style.borderColor='#6366f1';this.style.boxShadow='0 0 0 2px #e0e7ff'"
                        onmouseleave="this.style.borderColor='#e2e8f0';this.style.boxShadow='none'">
                        ${miniSvg}
                    </div>`;
                }
            }
        }
        html += '</div>';
        gridEl.innerHTML = html;
    }

    // Mini scatter using correlation coefficients (same axes as 細部散佈圖)
    function _meGlobalMiniScatter(xTargetCol, yTargetCol, W, H) {
        const rows = Object.entries(_meActiveData()).map(([col, corrs]) => ({
            col,
            cx: corrs[xTargetCol] ?? 0,
            cy: corrs[yTargetCol] ?? 0,
        }));

        const PAD = { l: 20, r: 4, t: 6, b: 16 };
        const pw = W - PAD.l - PAD.r, ph = H - PAD.t - PAD.b;
        const toSvgX = v => PAD.l + (v + 1) / 2 * pw;
        const toSvgY = v => PAD.t + (1 - (v + 1) / 2) * ph;

        const passFilter = new Set(meGetFilteredCols());

        // Tick values and reference lines
        const ticks = [-1, -0.5, 0, 0.5, 1];
        const refLines = [-0.3, 0.3]; // dashed ±0.3 guide

        let gridLines = '';
        ticks.forEach(v => {
            const sx = toSvgX(v).toFixed(1), sy = toSvgY(v).toFixed(1);
            // light grid lines at each tick
            gridLines += `<line x1="${sx}" y1="${PAD.t}" x2="${sx}" y2="${PAD.t + ph}" stroke="#f1f5f9" stroke-width="1"/>`;
            gridLines += `<line x1="${PAD.l}" y1="${sy}" x2="${PAD.l + pw}" y2="${sy}" stroke="#f1f5f9" stroke-width="1"/>`;
        });
        // zero lines (slightly darker)
        const zx = toSvgX(0).toFixed(1), zy = toSvgY(0).toFixed(1);
        gridLines += `<line x1="${PAD.l}" y1="${zy}" x2="${PAD.l + pw}" y2="${zy}" stroke="#cbd5e1" stroke-width="1"/>`;
        gridLines += `<line x1="${zx}" y1="${PAD.t}" x2="${zx}" y2="${PAD.t + ph}" stroke="#cbd5e1" stroke-width="1"/>`;
        // ±0.3 dashed reference lines
        refLines.forEach(v => {
            const sx = toSvgX(v).toFixed(1), sy = toSvgY(v).toFixed(1);
            gridLines += `<line x1="${sx}" y1="${PAD.t}" x2="${sx}" y2="${PAD.t + ph}" stroke="#a5b4fc" stroke-width="0.8" stroke-dasharray="2,2"/>`;
            gridLines += `<line x1="${PAD.l}" y1="${sy}" x2="${PAD.l + pw}" y2="${sy}" stroke="#a5b4fc" stroke-width="0.8" stroke-dasharray="2,2"/>`;
        });

        let dots = '';
        rows.forEach(({ col, cx, cy }) => {
            const isSelected = _meScatterSelected.has(col);
            const inFilter   = passFilter.has(col);
            const fill    = isSelected ? '#f97316' : inFilter ? '#a855f7' : '#cbd5e1';
            const opacity = isSelected ? '0.9' : inFilter ? '0.7' : '0.4';
            dots += `<circle cx="${toSvgX(cx).toFixed(1)}" cy="${toSvgY(cy).toFixed(1)}" r="${isSelected ? 3 : 2}" fill="${fill}" opacity="${opacity}"/>`;
        });

        // X-axis tick labels at -1, 0, 1
        const xTickLabels = [-1, 0, 1].map(v =>
            `<text x="${toSvgX(v).toFixed(1)}" y="${H - 2}" text-anchor="middle" fill="#94a3b8" font-size="7">${v}</text>`
        ).join('');
        // Y-axis tick labels at -1, 0, 1
        const yTickLabels = [-1, 0, 1].map(v =>
            `<text x="${PAD.l - 2}" y="${(toSvgY(v) + 2.5).toFixed(1)}" text-anchor="end" fill="#94a3b8" font-size="7">${v}</text>`
        ).join('');

        return `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" style="display:block;">
            ${gridLines}
            ${dots}
            ${xTickLabels}
            ${yTickLabels}
        </svg>`;
    }

    window.meSetGlobalAxes = function (xCol, yCol) {
        const selX = document.getElementById('me-scatter-axis-x');
        const selY = document.getElementById('me-scatter-axis-y');
        if (selX) selX.value = xCol;
        if (selY) selY.value = yCol;
        meRenderScatterFilters();
        meSetScatterView('scatter');
    };

    // sort state: { col: 'name'|yColName, dir: 1|-1 }
    let _meTableSort = { col: '__max__', dir: -1 };

    window.meTableSortBy = function (col) {
        if (_meTableSort.col === col) _meTableSort.dir *= -1;
        else { _meTableSort.col = col; _meTableSort.dir = col === 'name' ? 1 : -1; }
        meRenderCorrelationTable();
    };

    window.meRenderCorrelationTable = function () {
        const el = document.getElementById('me-table-view');
        if (!el || !Object.keys(_meActiveData()).length) return;
        const yCols = _meTargets.map(t => t.col);
        const passFilter = new Set(meGetFilteredCols());
        const allXCols = Object.keys(_meActiveData());

        // Sort
        const { col: sCol, dir } = _meTableSort;
        const sorted = allXCols.slice().sort((a, b) => {
            let va, vb;
            if (sCol === 'name') {
                va = a.toLowerCase(); vb = b.toLowerCase();
                return dir * va.localeCompare(vb);
            } else if (sCol === '__max__') {
                va = Math.max(...yCols.map(y => Math.abs(_meActiveData()[a][y] ?? 0)));
                vb = Math.max(...yCols.map(y => Math.abs(_meActiveData()[b][y] ?? 0)));
            } else {
                va = _meActiveData()[a][sCol] ?? 0;
                vb = _meActiveData()[b][sCol] ?? 0;
            }
            return dir * (va - vb);
        });

        const arrow = (col) => {
            if (_meTableSort.col !== col) return `<span style="opacity:.3;font-size:9px;">↕</span>`;
            return `<span style="font-size:9px;">${_meTableSort.dir < 0 ? '↓' : '↑'}</span>`;
        };
        const thBase = `padding:6px 8px;border-bottom:2px solid #e2e8f0;font-weight:600;text-align:center;cursor:pointer;user-select:none;white-space:nowrap;`;
        const thHover = `onmouseenter="this.style.background='#f1f5f9'" onmouseleave="this.style.background='#f8fafc'"`;

        const cellStyle = (r) => {
            const abs = Math.abs(r);
            let bg = '#fff';
            if (r >  0.05) bg = `rgba(37,99,235,${Math.min(abs, 1) * 0.6})`;
            if (r < -0.05) bg = `rgba(239,68,68,${Math.min(abs, 1) * 0.6})`;
            const fg = abs > 0.4 ? '#fff' : '#1e293b';
            return `background:${bg};color:${fg};`;
        };
        let html = `<table style="border-collapse:collapse;width:100%;font-size:11px;">
            <thead>
                <tr style="position:sticky;top:0;z-index:2;background:#f8fafc;">
                    <th style="text-align:left;${thBase}min-width:140px;color:#64748b;" onclick="meTableSortBy('name')" ${thHover}>X 參數 ${arrow('name')}</th>
                    ${yCols.map(y => `<th style="${thBase}min-width:90px;color:#475569;" onclick="meTableSortBy('${y.replace(/'/g,"\\'")}') " ${thHover}>${y} ${arrow(y)}</th>`).join('')}
                </tr>
            </thead><tbody>`;
        sorted.forEach((xCol, idx) => {
            const row = _meActiveData()[xCol];
            const pass = passFilter.has(xCol);
            const rowBg = pass ? (idx % 2 === 0 ? '#fff' : '#fafafe') : '#f1f5f9';
            const nameStyle = pass ? 'color:#1e293b;font-weight:500;' : 'color:#94a3b8;';
            html += `<tr style="background:${rowBg};" onmouseenter="this.style.outline='1px solid #c7d2fe'" onmouseleave="this.style.outline='none'">
                <td style="padding:4px 10px;border-bottom:1px solid #f1f5f9;${nameStyle}white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:200px;" title="${xCol}">${xCol}</td>
                ${yCols.map(y => {
                    const r = row[y] ?? null;
                    if (r === null) return `<td style="padding:4px 8px;border-bottom:1px solid #f1f5f9;text-align:center;color:#cbd5e1;">—</td>`;
                    return `<td style="padding:4px 8px;border-bottom:1px solid #f1f5f9;text-align:center;${cellStyle(r)}">${r.toFixed(3)}</td>`;
                }).join('')}
            </tr>`;
        });
        html += '</tbody></table>';
        el.innerHTML = html;
    };

    // ── Click dot → show mini multi-target scatter modal ──────────
    window.meShowXYScatter = async function (col) {
        if (!_meTargets.length) return;
        const fileId = typeof currentFileId !== 'undefined' ? currentFileId : '';
        const sid    = typeof getSessionId === 'function' ? getSessionId() : (localStorage.getItem('sigma2_session_id') || 'default');
        const yCols  = _meTargets.map(t => t.col).join(',');
        _meXYModalShow(col, null);
        try {
            const resp = await fetch(`/api/data-prep/xy-data/${fileId}?x_col=${encodeURIComponent(col)}&y_cols=${encodeURIComponent(yCols)}&session_id=${encodeURIComponent(sid)}`);
            _meXYModalShow(col, await resp.json());
        } catch (e) { console.error('[ME] xy-data error:', e); }
    };

    let _meXYSyncYAxis = false;

    function _meXYModalShow(col, payload) {
        let modal = document.getElementById('me-xy-modal');
        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'me-xy-modal';
            modal.style.cssText = 'position:fixed;inset:0;background:rgba(15,23,42,.55);z-index:2000;display:flex;align-items:center;justify-content:center;';
            const _closeModal = () => {
                document.removeEventListener('keydown', modal._escHandler);
                modal.remove();
            };
            modal.addEventListener('click', e => { if (e.target === modal) _closeModal(); });
            modal._escHandler = e => { if (e.key === 'Escape') _closeModal(); };
            document.addEventListener('keydown', modal._escHandler);
            modal._close = _closeModal;
            document.body.appendChild(modal);
        }
        if (!payload) {
            modal.innerHTML = `<div style="background:#fff;border-radius:14px;padding:28px 32px;min-width:280px;text-align:center;color:#6366f1;font-size:13px;">載入中…</div>`;
            return;
        }
        // Cache payload so checkbox re-render can reuse it
        modal._payload = payload;

        const { x_col, y_cols, data } = payload;
        const xVals = data[x_col] || [];
        const cols = Math.min(y_cols.length, 3);
        const cachedCorrs = (_meCorrelations[x_col] || {});
        const cachedShap  = (_meScatterMetric === 'shap') ? (_meShapData[x_col] || {}) : null;

        // Compute global Y range if sync is on
        let globalYMin = null, globalYMax = null;
        if (_meXYSyncYAxis) {
            y_cols.forEach(yCol => {
                const vals = (data[yCol] || []).filter(v => v != null);
                if (!vals.length) return;
                const mn = Math.min(...vals), mx = Math.max(...vals);
                if (globalYMin === null || mn < globalYMin) globalYMin = mn;
                if (globalYMax === null || mx > globalYMax) globalYMax = mx;
            });
        }

        const plots = y_cols.map(yCol => _meMiniScatterHTML(
            xVals, data[yCol] || [], x_col, yCol,
            cachedCorrs[yCol], cachedShap ? cachedShap[yCol] : null,
            globalYMin, globalYMax
        )).join('');
        const isShapMode = _meScatterMetric === 'shap';

        modal.innerHTML = `
        <div style="background:#fff;border-radius:14px;box-shadow:0 20px 60px rgba(0,0,0,.25);padding:20px 24px;max-width:92vw;max-height:85vh;overflow:auto;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:${isShapMode ? 4 : 8}px;">
                <div style="font-size:14px;font-weight:700;color:#1e293b;">參數：${x_col}</div>
                <div style="display:flex;align-items:center;gap:12px;">
                    <label style="display:flex;align-items:center;gap:5px;font-size:11px;color:#64748b;cursor:pointer;user-select:none;">
                        <input type="checkbox" id="me-xy-sync-y" ${_meXYSyncYAxis ? 'checked' : ''}
                            onchange="_meXYToggleSyncY()"
                            style="accent-color:#6366f1;width:13px;height:13px;">
                        Y軸同步
                    </label>
                    <button onclick="document.getElementById('me-xy-modal')._close()" style="border:none;background:#f1f5f9;border-radius:6px;width:28px;height:28px;cursor:pointer;font-size:14px;color:#64748b;line-height:1;">✕</button>
                </div>
            </div>
            ${isShapMode ? `<div style="font-size:10px;color:#94a3b8;margin-bottom:12px;">散佈圖為原始資料（Pearson r）；括號內為正規化 SHAP 值</div>` : ''}
            <div id="me-xy-scatter-grid" style="display:grid;grid-template-columns:repeat(${cols},1fr);gap:12px;">${plots}</div>
            ${_meXYSyncYAxis ? `<div style="margin-top:14px;border-top:1px solid #f1f5f9;padding-top:12px;">
                <div style="font-size:11px;font-weight:600;color:#64748b;margin-bottom:6px;">合併時序圖 <span style="font-size:10px;font-weight:400;color:#94a3b8;">— 拖曳框選以高亮散佈圖</span></div>
                <div id="me-xy-trend-wrap">${_meCombinedTrendSVG(y_cols, data, globalYMin, globalYMax)}</div>
            </div>` : ''}
        </div>`;
    }

    let _meXYBrush = null; // { i0, i1 } index range selected on trend chart

    // prefix: 'me-xy' (popup modal) or 'me-ad' (inline analyze-detail panel)
    function _meCombinedTrendSVG(y_cols, data, yMin, yMax, prefix, brushState) {
        if (prefix === undefined) prefix = 'me-xy';
        if (brushState === undefined) brushState = (prefix === 'me-xy' ? _meXYBrush : window._meADBrush);
        const pfxCap = prefix === 'me-xy' ? 'XY' : 'AD';
        const COLORS = ['#2563eb', '#e11d48', '#059669', '#d97706', '#7c3aed'];
        const W = 460, H = 160, PAD = { l:46, r:12, t:10, b:28 };
        const pw = W - PAD.l - PAD.r, ph = H - PAD.t - PAD.b;

        const yRange = (yMax - yMin) || 1;
        const sy = v => PAD.t + (1 - (v - yMin) / yRange) * ph;

        const n = Math.max(...y_cols.map(c => (data[c] || []).length));
        if (n === 0) return '<div style="color:#94a3b8;font-size:12px;">無資料</div>';
        const sx = i => PAD.l + (i / (n - 1 || 1)) * pw;

        function fmt(v) {
            const abs = Math.abs(v);
            const dec = abs >= 100 ? 0 : abs >= 10 ? 1 : abs >= 1 ? 2 : 3;
            return v.toFixed(dec);
        }
        function niceTicks(mn, mx, count) {
            const range = mx - mn || 1;
            const raw = range / count;
            const mag = Math.pow(10, Math.floor(Math.log10(raw)));
            let step = mag;
            for (const f of [1,2,2.5,5,10]) { if (f*mag >= raw) { step = f*mag; break; } }
            const ticks = [];
            for (let v = Math.ceil(mn/step)*step; v <= mx+step*0.001; v = +(v+step).toFixed(10)) ticks.push(parseFloat(v.toPrecision(10)));
            return ticks;
        }

        // Brush rect from current state
        let brushRect = '';
        if (brushState) {
            const bx0 = sx(Math.min(brushState.i0, brushState.i1));
            const bx1 = sx(Math.max(brushState.i0, brushState.i1));
            brushRect = `<rect id="${prefix}-brush-rect" x="${bx0.toFixed(1)}" y="${PAD.t}" width="${(bx1-bx0).toFixed(1)}" height="${ph}" fill="rgba(99,102,241,0.12)" stroke="#6366f1" stroke-width="1" stroke-dasharray="4,3"/>`;
        } else {
            brushRect = `<rect id="${prefix}-brush-rect" x="0" y="0" width="0" height="0" fill="rgba(99,102,241,0.12)" stroke="#6366f1" stroke-width="1" stroke-dasharray="4,3"/>`;
        }

        let svg = `<svg id="${prefix}-trend-svg" width="${W}" height="${H}" style="width:100%;max-width:${W}px;cursor:crosshair;" data-n="${n}" data-padl="${PAD.l}" data-pw="${pw}" data-padt="${PAD.t}" data-ph="${ph}">`;
        svg += `<rect x="${PAD.l}" y="${PAD.t}" width="${pw}" height="${ph}" fill="#f8fafc" rx="3"/>`;

        niceTicks(yMin, yMax, 4).forEach(v => {
            const cy = sy(v);
            svg += `<line x1="${PAD.l}" y1="${cy.toFixed(1)}" x2="${PAD.l+pw}" y2="${cy.toFixed(1)}" stroke="#e2e8f0" stroke-width="0.8"/>`;
            svg += `<text x="${PAD.l-4}" y="${(cy+3.5).toFixed(1)}" text-anchor="end" font-size="8" fill="#94a3b8">${fmt(v)}</text>`;
        });

        const xStep = Math.ceil(n / 6);
        for (let i = 0; i < n; i += xStep) {
            const cx = sx(i);
            svg += `<line x1="${cx.toFixed(1)}" y1="${PAD.t}" x2="${cx.toFixed(1)}" y2="${PAD.t+ph}" stroke="#e2e8f0" stroke-width="0.6"/>`;
            svg += `<text x="${cx.toFixed(1)}" y="${PAD.t+ph+11}" text-anchor="middle" font-size="8" fill="#94a3b8">${i}</text>`;
        }

        svg += `<rect x="${PAD.l}" y="${PAD.t}" width="${pw}" height="${ph}" fill="none" stroke="#cbd5e1" stroke-width="0.8"/>`;

        y_cols.forEach((col, ci) => {
            const vals = data[col] || [];
            const color = COLORS[ci % COLORS.length];
            const pts = vals.map((v, i) => v != null ? `${i === 0 ? 'M' : 'L'}${sx(i).toFixed(1)},${sy(v).toFixed(1)}` : null).filter(Boolean);
            if (pts.length) svg += `<path d="${pts.join(' ')}" fill="none" stroke="${color}" stroke-width="1.5" opacity="0.85"/>`;
            const dotStep = vals.length > 80 ? 4 : vals.length > 40 ? 2 : 1;
            vals.forEach((v, i) => {
                if (v == null || i % dotStep !== 0) return;
                svg += `<circle cx="${sx(i).toFixed(1)}" cy="${sy(v).toFixed(1)}" r="2.5" fill="${color}" opacity="0.7"/>`;
            });
        });

        // Legend
        const legendX = PAD.l + pw - y_cols.length * 80;
        y_cols.forEach((col, ci) => {
            const lx = legendX + ci * 80;
            const color = COLORS[ci % COLORS.length];
            svg += `<line x1="${lx.toFixed(0)}" y1="${(PAD.t+8).toFixed(0)}" x2="${(lx+16).toFixed(0)}" y2="${(PAD.t+8).toFixed(0)}" stroke="${color}" stroke-width="2"/>`;
            svg += `<text x="${(lx+20).toFixed(0)}" y="${(PAD.t+11.5).toFixed(0)}" font-size="9" fill="${color}" font-weight="600">${col.length>10?col.slice(0,9)+'…':col}</text>`;
        });

        // Brush rect (on top)
        svg += brushRect;
        // Hint
        if (!brushState) svg += `<text x="${PAD.l + pw/2}" y="${PAD.t + ph - 4}" text-anchor="middle" font-size="8" fill="#a5b4fc" opacity="0.8">拖曳框選範圍以高亮散佈圖</text>`;
        // Transparent interactive overlay
        svg += `<rect x="${PAD.l}" y="${PAD.t}" width="${pw}" height="${ph}" fill="transparent"
            onmousedown="_me${pfxCap}TrendMD(event)" onmousemove="_me${pfxCap}TrendMM(event)" onmouseup="_me${pfxCap}TrendMU(event)"/>`;
        svg += '</svg>';

        // Reset brush hint button
        const resetBtn = brushState
            ? `<button onclick="_me${pfxCap}ClearBrush()" style="margin-top:4px;font-size:10px;color:#6366f1;background:none;border:none;cursor:pointer;padding:0;">✕ 清除框選</button>`
            : '';
        return `<div style="position:relative;">${svg}${resetBtn}</div>`;
    }

    // Brush interaction state
    let _meXYBrushDragging = false;
    let _meXYBrushStart = null;

    window._meXYTrendMD = function(e) {
        const svg = document.getElementById('me-xy-trend-svg');
        if (!svg) return;
        _meXYBrushDragging = true;
        const rect = svg.getBoundingClientRect();
        const scaleX = parseFloat(svg.dataset.pw) / (rect.width - parseFloat(svg.dataset.padl) - 12);
        const relX = (e.clientX - rect.left) - parseFloat(svg.dataset.padl);
        const n = parseInt(svg.dataset.n);
        _meXYBrushStart = Math.round(Math.max(0, Math.min(n-1, relX / parseFloat(svg.dataset.pw) * (n-1))));
        _meXYBrush = { i0: _meXYBrushStart, i1: _meXYBrushStart };
        e.preventDefault();
    };
    window._meXYTrendMM = function(e) {
        if (!_meXYBrushDragging) return;
        const svg = document.getElementById('me-xy-trend-svg');
        if (!svg) return;
        const rect = svg.getBoundingClientRect();
        const relX = (e.clientX - rect.left) - parseFloat(svg.dataset.padl);
        const n = parseInt(svg.dataset.n);
        const pw = parseFloat(svg.dataset.pw);
        const i1 = Math.round(Math.max(0, Math.min(n-1, relX / pw * (n-1))));
        _meXYBrush = { i0: _meXYBrushStart, i1 };
        // Live-update brush rect only (lightweight)
        const bRect = document.getElementById('me-xy-brush-rect');
        if (bRect) {
            const padL = parseFloat(svg.dataset.padl);
            const bx0 = padL + Math.min(_meXYBrush.i0, _meXYBrush.i1) / (n-1) * pw;
            const bx1 = padL + Math.max(_meXYBrush.i0, _meXYBrush.i1) / (n-1) * pw;
            bRect.setAttribute('x', bx0.toFixed(1));
            bRect.setAttribute('width', Math.max(1, bx1-bx0).toFixed(1));
        }
    };
    window._meXYTrendMU = function(e) {
        if (!_meXYBrushDragging) return;
        _meXYBrushDragging = false;
        if (!_meXYBrush || _meXYBrush.i0 === _meXYBrush.i1) { _meXYBrush = null; }
        _meXYApplyBrush();
    };
    window._meXYClearBrush = function() {
        _meXYBrush = null;
        _meXYApplyBrush();
    };

    function _meXYApplyBrush() {
        const modal = document.getElementById('me-xy-modal');
        if (!modal || !modal._payload) return;
        const { x_col, y_cols, data } = modal._payload;
        const xVals = data[x_col] || [];
        const cachedCorrs = (_meCorrelations[x_col] || {});
        const cachedShap  = (_meScatterMetric === 'shap') ? (_meShapData[x_col] || {}) : null;

        // Build highlight set
        let highlightSet = null;
        if (_meXYBrush) {
            highlightSet = new Set();
            const lo = Math.min(_meXYBrush.i0, _meXYBrush.i1);
            const hi = Math.max(_meXYBrush.i0, _meXYBrush.i1);
            for (let i = lo; i <= hi; i++) highlightSet.add(i);
        }

        // Recompute global Y range
        let globalYMin = null, globalYMax = null;
        if (_meXYSyncYAxis) {
            y_cols.forEach(yCol => {
                const vals = (data[yCol] || []).filter(v => v != null);
                if (!vals.length) return;
                const mn = Math.min(...vals), mx = Math.max(...vals);
                if (globalYMin === null || mn < globalYMin) globalYMin = mn;
                if (globalYMax === null || mx > globalYMax) globalYMax = mx;
            });
        }

        const cols = Math.min(y_cols.length, 3);
        const plots = y_cols.map(yCol => _meMiniScatterHTML(
            xVals, data[yCol] || [], x_col, yCol,
            cachedCorrs[yCol], cachedShap ? cachedShap[yCol] : null,
            globalYMin, globalYMax, highlightSet
        )).join('');

        const grid = document.getElementById('me-xy-scatter-grid');
        if (grid) grid.innerHTML = plots;

        // Rebuild trend chart to reflect brush state (reset button)
        const trendWrap = document.getElementById('me-xy-trend-wrap');
        if (trendWrap) trendWrap.innerHTML = _meCombinedTrendSVG(y_cols, data, globalYMin ?? Math.min(...y_cols.flatMap(c => (data[c]||[]).filter(v=>v!=null))), globalYMax ?? Math.max(...y_cols.flatMap(c => (data[c]||[]).filter(v=>v!=null))));
    }

    window._meXYToggleSyncY = function () {
        _meXYSyncYAxis = document.getElementById('me-xy-sync-y')?.checked ?? false;
        _meXYBrush = null;
        const modal = document.getElementById('me-xy-modal');
        if (modal && modal._payload) _meXYModalShow(modal._payload.x_col, modal._payload);
    };

    // ── Inline analyze-detail panel ────────────────────────────────
    window._meADSyncYAxis = false;
    window._meADPayload   = null;
    window._meADBrush     = null;
    window._meAnalyzeActiveRow = -1;

    window.meAnalyzeRowDetail = async function(idx) {
        const rows = window._meAnalyzeRows;
        if (!rows || !rows[idx]) return;
        const col = rows[idx].name;

        // Highlight clicked row, clear previous
        window._meAnalyzeActiveRow = idx;
        rows.forEach((_, i) => {
            const tr = document.getElementById(`me-analyze-row-${i}`);
            if (!tr) return;
            const bg0 = i % 2 ? '#f8fafc' : '#fff';
            tr.style.background = (i === idx) ? '#e0f2fe' : bg0;
        });

        // Show panel with loading state
        const panel = document.getElementById('me-analyze-detail');
        if (!panel) return;
        panel.style.display = 'block';
        panel.innerHTML = `<div style="padding:24px;text-align:center;color:#6366f1;font-size:13px;">載入中…</div>`;
        panel.scrollIntoView({ behavior:'smooth', block:'nearest' });

        const fileId = typeof currentFileId !== 'undefined' ? currentFileId : '';
        const sid    = typeof getSessionId === 'function' ? getSessionId() : (localStorage.getItem('sigma2_session_id') || 'default');
        // Gather all target cols as Y columns
        const yCols  = _meTargets.map(t => t.col).join(',');
        if (!yCols) { panel.innerHTML = `<div style="padding:16px;color:#94a3b8;font-size:12px;">請先設定目標參數</div>`; return; }

        try {
            const resp = await fetch(`/api/data-prep/xy-data/${fileId}?x_col=${encodeURIComponent(col)}&y_cols=${encodeURIComponent(yCols)}&session_id=${encodeURIComponent(sid)}`);
            const payload = await resp.json();
            window._meADPayload = payload;
            window._meADBrush   = null;
            _meADRender(payload);
        } catch(e) {
            panel.innerHTML = `<div style="padding:16px;color:#ef4444;font-size:12px;">載入失敗</div>`;
        }
    };

    function _meADRender(payload) {
        const panel = document.getElementById('me-analyze-detail');
        if (!panel) return;
        const { x_col, y_cols, data } = payload;
        const xVals = data[x_col] || [];
        const cachedCorrs = (_meCorrelations[x_col] || {});
        const cachedShap  = (_meScatterMetric === 'shap') ? (_meShapData[x_col] || {}) : null;

        // Compute global Y range if sync on
        let globalYMin = null, globalYMax = null;
        if (window._meADSyncYAxis) {
            y_cols.forEach(yCol => {
                const vals = (data[yCol] || []).filter(v => v != null);
                if (!vals.length) return;
                const mn = Math.min(...vals), mx = Math.max(...vals);
                if (globalYMin === null || mn < globalYMin) globalYMin = mn;
                if (globalYMax === null || mx > globalYMax) globalYMax = mx;
            });
        }

        // Build highlight set from brush
        let highlightSet = null;
        if (window._meADBrush) {
            highlightSet = new Set();
            const lo = Math.min(window._meADBrush.i0, window._meADBrush.i1);
            const hi = Math.max(window._meADBrush.i0, window._meADBrush.i1);
            for (let i = lo; i <= hi; i++) highlightSet.add(i);
        }

        const cols = Math.min(y_cols.length, 3);
        const plots = y_cols.map(yCol => _meMiniScatterHTML(
            xVals, data[yCol] || [], x_col, yCol,
            cachedCorrs[yCol], cachedShap ? cachedShap[yCol] : null,
            globalYMin, globalYMax, highlightSet
        )).join('');

        const adGlobalYMin = globalYMin ?? Math.min(...y_cols.flatMap(c => (data[c]||[]).filter(v=>v!=null)));
        const adGlobalYMax = globalYMax ?? Math.max(...y_cols.flatMap(c => (data[c]||[]).filter(v=>v!=null)));

        const trendSection = window._meADSyncYAxis ? `
            <div style="margin-top:12px;border-top:1px solid #e0e7ff;padding-top:10px;">
                <div style="font-size:11px;font-weight:600;color:#64748b;margin-bottom:5px;">合併時序圖 <span style="font-size:10px;font-weight:400;color:#94a3b8;">— 拖曳框選以高亮散佈圖</span></div>
                <div id="me-ad-trend-wrap">${_meCombinedTrendSVG(y_cols, data, adGlobalYMin, adGlobalYMax, 'me-ad', window._meADBrush)}</div>
            </div>` : '';

        panel.innerHTML = `
            <div style="padding:14px 20px;">
                <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;flex-wrap:wrap;gap:6px;">
                    <div style="font-size:13px;font-weight:700;color:#1e293b;">📊 ${x_col}</div>
                    <div style="display:flex;align-items:center;gap:12px;">
                        <label style="display:flex;align-items:center;gap:5px;font-size:11px;color:#64748b;cursor:pointer;user-select:none;">
                            <input type="checkbox" id="me-ad-sync-y" ${window._meADSyncYAxis ? 'checked' : ''}
                                onchange="_meADToggleSyncY()"
                                style="accent-color:#6366f1;width:13px;height:13px;">
                            Y軸同步
                        </label>
                        <button onclick="document.getElementById('me-analyze-detail').style.display='none';window._meAnalyzeActiveRow=-1;(function(){const rows=window._meAnalyzeRows||[];rows.forEach((_,i)=>{const tr=document.getElementById('me-analyze-row-'+i);if(tr)tr.style.background=i%2?'#f8fafc':'#fff';});})();"
                            style="border:none;background:#e0e7ff;border-radius:6px;width:24px;height:24px;cursor:pointer;font-size:12px;color:#4f46e5;line-height:1;">✕</button>
                    </div>
                </div>
                <div id="me-ad-scatter-grid" style="display:grid;grid-template-columns:repeat(${cols},1fr);gap:12px;">${plots}</div>
                ${trendSection}
            </div>`;
    }

    window._meADToggleSyncY = function() {
        window._meADSyncYAxis = document.getElementById('me-ad-sync-y')?.checked ?? false;
        window._meADBrush = null;
        if (window._meADPayload) _meADRender(window._meADPayload);
    };

    // AD brush handlers (mirror of XY brush, but for me-ad-* elements)
    let _meADBrushDragging = false, _meADBrushStart = null;

    window._meADTrendMD = function(e) {
        const svg = document.getElementById('me-ad-trend-svg');
        if (!svg) return;
        _meADBrushDragging = true;
        const rect = svg.getBoundingClientRect();
        const relX = (e.clientX - rect.left) - parseFloat(svg.dataset.padl);
        const n = parseInt(svg.dataset.n);
        _meADBrushStart = Math.round(Math.max(0, Math.min(n-1, relX / parseFloat(svg.dataset.pw) * (n-1))));
        window._meADBrush = { i0: _meADBrushStart, i1: _meADBrushStart };
        e.preventDefault();
    };
    window._meADTrendMM = function(e) {
        if (!_meADBrushDragging) return;
        const svg = document.getElementById('me-ad-trend-svg');
        if (!svg) return;
        const rect = svg.getBoundingClientRect();
        const relX = (e.clientX - rect.left) - parseFloat(svg.dataset.padl);
        const n = parseInt(svg.dataset.n);
        const pw = parseFloat(svg.dataset.pw);
        const i1 = Math.round(Math.max(0, Math.min(n-1, relX / pw * (n-1))));
        window._meADBrush = { i0: _meADBrushStart, i1 };
        const bRect = document.getElementById('me-ad-brush-rect');
        if (bRect) {
            const padL = parseFloat(svg.dataset.padl);
            const bx0 = padL + Math.min(window._meADBrush.i0, i1) / (n-1) * pw;
            const bx1 = padL + Math.max(window._meADBrush.i0, i1) / (n-1) * pw;
            bRect.setAttribute('x', bx0.toFixed(1));
            bRect.setAttribute('width', Math.max(1, bx1-bx0).toFixed(1));
        }
    };
    window._meADTrendMU = function(e) {
        if (!_meADBrushDragging) return;
        _meADBrushDragging = false;
        if (!window._meADBrush || window._meADBrush.i0 === window._meADBrush.i1) { window._meADBrush = null; }
        if (window._meADPayload) _meADRender(window._meADPayload);
    };
    window._meADClearBrush = function() {
        window._meADBrush = null;
        if (window._meADPayload) _meADRender(window._meADPayload);
    };

    function _meMiniScatterHTML(xVals, yVals, xLabel, yLabel, precomputedR, shapVal, yMinForce = null, yMaxForce = null, highlightSet = null) {
        const W = 220, H = 190, PAD = { l:46, r:10, t:8, b:38 };
        const pw = W - PAD.l - PAD.r, ph = H - PAD.t - PAD.b;
        if (!xVals.length || !yVals.length)
            return `<div style="border:1px solid #e2e8f0;border-radius:8px;width:${W}px;height:${H}px;display:flex;align-items:center;justify-content:center;color:#94a3b8;font-size:12px;">無資料</div>`;
        const xMin = Math.min(...xVals), xMax = Math.max(...xVals), xRange = xMax - xMin || 1;
        const yMin = yMinForce !== null ? yMinForce : Math.min(...yVals);
        const yMax = yMaxForce !== null ? yMaxForce : Math.max(...yVals);
        const yRange = yMax - yMin || 1;
        const sx = v => PAD.l + (v - xMin) / xRange * pw;
        const sy = v => PAD.t + (1 - (v - yMin) / yRange) * ph;
        const n = xVals.length;
        const xM = xVals.reduce((a,b) => a+b, 0) / n, yM = yVals.reduce((a,b) => a+b, 0) / n;
        const num = xVals.reduce((s,x,i) => s+(x-xM)*(yVals[i]-yM), 0);
        const dX  = xVals.reduce((s,x) => s+(x-xM)**2, 0);
        const dY  = yVals.reduce((s,y) => s+(y-yM)**2, 0);
        // 優先用主散佈圖的快取 r（與圖上點位置一致），避免 API 採樣差異造成符號錯誤
        const r   = (precomputedR !== undefined && precomputedR !== null) ? precomputedR
                  : ((dX && dY) ? num / Math.sqrt(dX*dY) : 0);
        // 迴歸線斜率方向必須與 r 符號一致
        const rawSlope = dX ? num/dX : 0;
        const slope = (rawSlope === 0 || Math.sign(rawSlope) === Math.sign(r)) ? rawSlope
                    : -rawSlope;
        const intc = yM - slope*xM;
        const rColor = r > 0.2 ? '#2563eb' : r < -0.2 ? '#ef4444' : '#94a3b8';
        const lx1 = sx(xMin), ly1 = Math.max(PAD.t, Math.min(PAD.t+ph, sy(slope*xMin+intc)));
        const lx2 = sx(xMax), ly2 = Math.max(PAD.t, Math.min(PAD.t+ph, sy(slope*xMax+intc)));

        // ── 刻度輔助 ──────────────────────────────────────────────
        function niceTickStep(range, maxTicks) {
            const raw = range / maxTicks;
            const mag = Math.pow(10, Math.floor(Math.log10(raw)));
            for (const f of [1, 2, 2.5, 5, 10]) {
                if (f * mag >= raw) return f * mag;
            }
            return mag * 10;
        }
        function fmt(v) {
            const abs = Math.abs(v);
            if (abs === 0) return '0';
            const dec = abs >= 1000 ? 0 : abs >= 100 ? 0 : abs >= 10 ? 1 : abs >= 1 ? 2 : abs >= 0.1 ? 3 : 4;
            return v.toFixed(dec);
        }
        function axisTicks(min, max, maxTicks) {
            const step = niceTickStep(max - min, maxTicks);
            const start = Math.ceil(min / step) * step;
            const ticks = [];
            for (let v = start; v <= max + step * 0.001; v += step) {
                const rv = parseFloat(v.toPrecision(10));
                if (rv >= min - step * 0.001 && rv <= max + step * 0.001) ticks.push(rv);
            }
            return ticks;
        }
        const xTicks = axisTicks(xMin, xMax, 4);
        const yTicks = axisTicks(yMin, yMax, 4);

        let svg = `<svg width="${W}" height="${H}"><rect x="${PAD.l}" y="${PAD.t}" width="${pw}" height="${ph}" fill="#f8fafc" rx="3"/>`;

        // Grid lines + Y tick labels
        yTicks.forEach(v => {
            const cy = sy(v);
            svg += `<line x1="${PAD.l}" y1="${cy.toFixed(1)}" x2="${PAD.l+pw}" y2="${cy.toFixed(1)}" stroke="#e2e8f0" stroke-width="0.8"/>`;
            svg += `<text x="${PAD.l-3}" y="${(cy+3.5).toFixed(1)}" text-anchor="end" font-size="8" fill="#94a3b8">${fmt(v)}</text>`;
        });
        // Grid lines + X tick labels
        xTicks.forEach(v => {
            const cx = sx(v);
            svg += `<line x1="${cx.toFixed(1)}" y1="${PAD.t}" x2="${cx.toFixed(1)}" y2="${PAD.t+ph}" stroke="#e2e8f0" stroke-width="0.8"/>`;
            svg += `<text x="${cx.toFixed(1)}" y="${PAD.t+ph+11}" text-anchor="middle" font-size="8" fill="#94a3b8">${fmt(v)}</text>`;
        });

        // Axis borders
        svg += `<rect x="${PAD.l}" y="${PAD.t}" width="${pw}" height="${ph}" fill="none" stroke="#cbd5e1" stroke-width="0.8"/>`;

        // Data points — dim non-highlighted when brush is active
        const hasBrush = highlightSet && highlightSet.size > 0;
        xVals.forEach((x, i) => {
            const highlighted = !hasBrush || highlightSet.has(i);
            const opacity = highlighted ? 0.85 : 0.08;
            const r = highlighted ? (hasBrush ? 4 : 3) : 2.5;
            svg += `<circle cx="${sx(x).toFixed(1)}" cy="${sy(yVals[i]).toFixed(1)}" r="${r}" fill="${rColor}" opacity="${opacity}"/>`;
        });
        // Regression line
        svg += `<line x1="${lx1.toFixed(1)}" y1="${ly1.toFixed(1)}" x2="${lx2.toFixed(1)}" y2="${ly2.toFixed(1)}" stroke="${rColor}" stroke-width="1.5" opacity="0.85"/>`;

        // Axis name labels
        svg += `<text x="${PAD.l+pw/2}" y="${H-4}" text-anchor="middle" font-size="9" fill="#94a3b8">${xLabel.length>20?xLabel.slice(0,18)+'…':xLabel}</text>`;
        svg += `<text x="9" y="${PAD.t+ph/2}" text-anchor="middle" font-size="9" fill="#94a3b8" transform="rotate(-90,9,${PAD.t+ph/2})">${yLabel.length>18?yLabel.slice(0,16)+'…':yLabel}</text>`;
        svg += `</svg>`;
        const shapTag = (shapVal != null)
            ? (() => {
                const sColor = shapVal > 0.05 ? '#2563eb' : shapVal < -0.05 ? '#ef4444' : '#94a3b8';
                return `<span style="font-size:10px;font-weight:700;color:${sColor};margin-left:6px;white-space:nowrap;">SHAP ${shapVal >= 0 ? '+' : ''}${shapVal.toFixed(3)}</span>`;
              })()
            : '';
        return `<div style="border:1px solid #e2e8f0;border-radius:8px;padding:8px;background:#fff;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;flex-wrap:wrap;gap:2px;">
                <div style="font-size:10px;color:#475569;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;">${yLabel}</div>
                <div style="display:flex;align-items:center;gap:0;">
                    <span style="font-size:12px;font-weight:700;color:${rColor};white-space:nowrap;">r = ${r.toFixed(3)}</span>
                    ${shapTag}
                </div>
            </div>${svg}</div>`;
    }


    window.meRenderScatterPlot = function () {
        const svg = document.getElementById('me-scatter-svg');
        if (!svg) return;
        const axX = (document.getElementById('me-scatter-axis-x') || {}).value;
        const axY = (document.getElementById('me-scatter-axis-y') || {}).value;
        if (!axX || !axY || !Object.keys(_meActiveData()).length) {
            svg.innerHTML = '<text x="50%" y="50%" text-anchor="middle" fill="#94a3b8" font-size="12">請先計算後顯示</text>';
            return;
        }
        const W = svg.clientWidth || 400, H = svg.clientHeight || 280;
        const PAD = { l:52, r:20, t:24, b:44 };
        const pw = W - PAD.l - PAD.r, ph = H - PAD.t - PAD.b;
        const Z = _meScatterZoom;
        const toSvgX = v => PAD.l + (v - Z.xMin) / (Z.xMax - Z.xMin) * pw;
        const toSvgY = v => PAD.t + (1 - (v - Z.yMin) / (Z.yMax - Z.yMin)) * ph;
        const passFilter = new Set(meGetFilteredCols());
        const rows = Object.entries(_meActiveData()).map(([col, corrs]) => ({
            col, cx: corrs[axX] ?? 0, cy: corrs[axY] ?? 0
        }));

        // Dynamic ticks
        function niceTicks(mn, mx) {
            const range = mx - mn;
            const step = range <= 0.4 ? 0.1 : range <= 1 ? 0.25 : 0.5;
            const ticks = [];
            for (let v = Math.ceil(mn / step) * step; v <= mx + 1e-9; v = +(v + step).toFixed(4)) ticks.push(+v.toFixed(3));
            return ticks;
        }

        let html = `<defs>
            <clipPath id="me-sc-clip"><rect x="${PAD.l}" y="${PAD.t}" width="${pw}" height="${ph}"/></clipPath>
        </defs>`;
        html += `<rect x="${PAD.l}" y="${PAD.t}" width="${pw}" height="${ph}" fill="#f8fafc" rx="4"/>`;
        // Reference grid lines — controlled by _meOverlaySettings
        const OL = _meOverlaySettings;
        if (OL.ol05) {
            [-0.5, 0.5].forEach(v => {
                if (v > Z.xMin && v < Z.xMax) html += `<line x1="${toSvgX(v).toFixed(1)}" y1="${PAD.t}" x2="${toSvgX(v).toFixed(1)}" y2="${PAD.t+ph}" stroke="#e2e8f0" stroke-width="1"/>`;
                if (v > Z.yMin && v < Z.yMax) html += `<line x1="${PAD.l}" y1="${toSvgY(v).toFixed(1)}" x2="${PAD.l+pw}" y2="${toSvgY(v).toFixed(1)}" stroke="#e2e8f0" stroke-width="1"/>`;
            });
        }
        if (OL.ol03) {
            [-0.3, 0.3].forEach(v => {
                if (v > Z.xMin && v < Z.xMax) html += `<line x1="${toSvgX(v).toFixed(1)}" y1="${PAD.t}" x2="${toSvgX(v).toFixed(1)}" y2="${PAD.t+ph}" stroke="#a5b4fc" stroke-width="1" stroke-dasharray="4,3"/>`;
                if (v > Z.yMin && v < Z.yMax) html += `<line x1="${PAD.l}" y1="${toSvgY(v).toFixed(1)}" x2="${PAD.l+pw}" y2="${toSvgY(v).toFixed(1)}" stroke="#a5b4fc" stroke-width="1" stroke-dasharray="4,3"/>`;
            });
        }
        if (OL.zero) {
            if (Z.xMin < 0 && Z.xMax > 0) html += `<line x1="${toSvgX(0).toFixed(1)}" y1="${PAD.t}" x2="${toSvgX(0).toFixed(1)}" y2="${PAD.t+ph}" stroke="#cbd5e1" stroke-width="1.5"/>`;
            if (Z.yMin < 0 && Z.yMax > 0) html += `<line x1="${PAD.l}" y1="${toSvgY(0).toFixed(1)}" x2="${PAD.l+pw}" y2="${toSvgY(0).toFixed(1)}" stroke="#cbd5e1" stroke-width="1.5"/>`;
        }
        // Ticks
        niceTicks(Z.xMin, Z.xMax).forEach(v => {
            const sx = toSvgX(v);
            if (sx >= PAD.l - 1 && sx <= PAD.l + pw + 1)
                html += `<text x="${sx.toFixed(1)}" y="${PAD.t+ph+14}" text-anchor="middle" font-size="9" fill="#94a3b8">${v}</text>`;
        });
        niceTicks(Z.yMin, Z.yMax).forEach(v => {
            const sy = toSvgY(v);
            if (sy >= PAD.t - 1 && sy <= PAD.t + ph + 1)
                html += `<text x="${PAD.l-4}" y="${sy.toFixed(1)+4}" text-anchor="end" font-size="9" fill="#94a3b8">${v}</text>`;
        });
        // Axis labels
        html += `<text x="${PAD.l+pw/2}" y="${H-4}" text-anchor="middle" font-size="11" fill="#475569" font-weight="600">${axX}</text>`;
        html += `<text x="12" y="${PAD.t+ph/2}" text-anchor="middle" font-size="11" fill="#475569" font-weight="600" transform="rotate(-90,12,${PAD.t+ph/2})">${axY}</text>`;
        // Optional balance lines (y=x and y=-x)
        if (_meShowBalanceLine) {
            html += `<g clip-path="url(#me-sc-clip)">`;
            const bMin = Math.max(Z.xMin, Z.yMin), bMax = Math.min(Z.xMax, Z.yMax);
            if (bMin < bMax) {
                html += `<line x1="${toSvgX(bMin).toFixed(1)}" y1="${toSvgY(bMin).toFixed(1)}" x2="${toSvgX(bMax).toFixed(1)}" y2="${toSvgY(bMax).toFixed(1)}" stroke="#a78bfa" stroke-width="1.2" stroke-dasharray="6,4" opacity="0.7"/>`;
                const lx = toSvgX(bMax), ly = toSvgY(bMax);
                html += `<text x="${(lx-4).toFixed(0)}" y="${(ly-6).toFixed(0)}" font-size="8" fill="#7c3aed" opacity="0.85" text-anchor="end">兩者均衡</text>`;
            }
            const nMin = Math.max(Z.xMin, -Z.yMax), nMax = Math.min(Z.xMax, -Z.yMin);
            if (nMin < nMax) {
                html += `<line x1="${toSvgX(nMin).toFixed(1)}" y1="${toSvgY(-nMin).toFixed(1)}" x2="${toSvgX(nMax).toFixed(1)}" y2="${toSvgY(-nMax).toFixed(1)}" stroke="#f87171" stroke-width="1.2" stroke-dasharray="6,4" opacity="0.6"/>`;
                const lx = toSvgX(nMax), ly = toSvgY(-nMax);
                html += `<text x="${(lx-4).toFixed(0)}" y="${(ly-6).toFixed(0)}" font-size="8" fill="#ef4444" opacity="0.8" text-anchor="end">反向均衡</text>`;
            }
            html += `</g>`;
        }
        // Points (draw unselected first, then filtered, then selected on top)
        html += `<g clip-path="url(#me-sc-clip)">`;
        const layers = [
            rows.filter(r => !passFilter.has(r.col) && !_meScatterSelected.has(r.col)),
            rows.filter(r =>  passFilter.has(r.col) && !_meScatterSelected.has(r.col)),
            rows.filter(r =>  _meScatterSelected.has(r.col)),
        ];
        layers.forEach(layer => layer.forEach(({ col, cx, cy }) => {
            const sx = toSvgX(cx), sy = toSvgY(cy);
            const isSelected = _meScatterSelected.has(col);
            const isFiltered = passFilter.has(col);
            const fill   = isSelected ? '#f97316' : (isFiltered ? '#6366f1' : '#d1d5db');
            const stroke = isSelected ? '#ea580c' : (isFiltered ? '#4f46e5' : '#9ca3af');
            const r = isSelected ? 7 : 5;
            const opacity = isFiltered || isSelected ? 1 : 0.25;
            const colSafe = col.replace(/\\/g,'\\\\').replace(/'/g,"\\'");
            html += `<circle cx="${sx.toFixed(1)}" cy="${sy.toFixed(1)}" r="${r}" fill="${fill}" stroke="${stroke}" stroke-width="${isSelected ? 2 : 1}" opacity="${opacity}" style="cursor:pointer;" onclick="meScatterDotClick('${colSafe}')" ondblclick="meShowXYScatter('${colSafe}')">
                <title>${col}\n${axX}: ${cx.toFixed(3)}\n${axY}: ${cy.toFixed(3)}\n單擊選取 / 雙擊查看多目標散佈圖</title>
            </circle>`;
        }));
        // Drag box
        if (_meScatterBox) {
            const { x0: bx0, y0: by0, x1: bx1, y1: by1 } = _meScatterBox;
            const bx = Math.min(bx0,bx1), by = Math.min(by0,by1);
            const bw = Math.abs(bx1-bx0), bh = Math.abs(by1-by0);
            const isZoom = _meScatterMode === 'zoom';
            html += `<rect x="${bx}" y="${by}" width="${bw}" height="${bh}" fill="${isZoom ? 'rgba(251,191,36,.1)' : 'rgba(99,102,241,.08)'}" stroke="${isZoom ? '#f59e0b' : '#6366f1'}" stroke-width="1.5" stroke-dasharray="5,3"/>`;
        }
        html += '</g>';
        svg.innerHTML = html;
        if (typeof _updateScatterGridOverlay === 'function') _updateScatterGridOverlay();
    };

    window.meScatterDotClick = function (col) {
        if (_meScatterSelected.has(col)) _meScatterSelected.delete(col);
        else _meScatterSelected.add(col);
        _updateScatterSelCount();
        _meRefreshPlot();
    };

    window.meScatterToggle = window.meScatterDotClick; // alias

    window.meScatterMouseDown = function (e) {
        if (e.target.tagName === 'circle') return;
        const rect = e.currentTarget.getBoundingClientRect();
        const x = e.clientX - rect.left, y = e.clientY - rect.top;
        if (_meScatterMode === 'pan') {
            _mePanDrag = { startX: x, startY: y, startZoom: { ..._meScatterZoom } };
        } else {
            _meScatterDragging = true;
            _meScatterDragStart = { x, y };
            _meScatterBox = null;
        }
        e.preventDefault();
    };

    window.meScatterMouseMove = function (e) {
        if (_mePanDrag) {
            const rect = e.currentTarget.getBoundingClientRect();
            const x = e.clientX - rect.left, y = e.clientY - rect.top;
            const svg = document.getElementById('me-scatter-svg');
            const W = svg.clientWidth || 400, H = svg.clientHeight || 280;
            const PAD = { l:52, r:20, t:24, b:44 };
            const pw = W - PAD.l - PAD.r, ph = H - PAD.t - PAD.b;
            const Z = _mePanDrag.startZoom;
            const dx = (x - _mePanDrag.startX) / pw * (Z.xMax - Z.xMin);
            const dy = (y - _mePanDrag.startY) / ph * (Z.yMax - Z.yMin);
            _meScatterZoom = { xMin: Z.xMin - dx, xMax: Z.xMax - dx, yMin: Z.yMin + dy, yMax: Z.yMax + dy };
            meRenderScatterPlot();
            return;
        }
        if (!_meScatterDragging) return;
        const rect = e.currentTarget.getBoundingClientRect();
        const cx = e.clientX - rect.left, cy = e.clientY - rect.top;
        _meScatterBox = { x0: _meScatterDragStart.x, y0: _meScatterDragStart.y, x1: cx, y1: cy };
        meRenderScatterPlot();
    };

    window.meScatterMouseUp = function (e) {
        if (_mePanDrag) { _mePanDrag = null; return; }
        if (!_meScatterDragging) return;
        _meScatterDragging = false;
        if (!_meScatterBox) return;
        const axX = (document.getElementById('me-scatter-axis-x') || {}).value;
        const axY = (document.getElementById('me-scatter-axis-y') || {}).value;
        const svg = document.getElementById('me-scatter-svg');
        const W = svg.clientWidth || 400, H = svg.clientHeight || 280;
        const PAD = { l:52, r:20, t:20, b:44 };
        const pw = W - PAD.l - PAD.r, ph = H - PAD.t - PAD.b;
        const Z = _meScatterZoom;
        const toDataX = sx => Z.xMin + (sx - PAD.l) / pw * (Z.xMax - Z.xMin);
        const toDataY = sy => Z.yMin + (1 - (sy - PAD.t) / ph) * (Z.yMax - Z.yMin);
        const toSvgX  = v  => PAD.l + (v - Z.xMin) / (Z.xMax - Z.xMin) * pw;
        const toSvgY  = v  => PAD.t + (1 - (v - Z.yMin) / (Z.yMax - Z.yMin)) * ph;
        const bxMin = Math.min(_meScatterBox.x0, _meScatterBox.x1);
        const bxMax = Math.max(_meScatterBox.x0, _meScatterBox.x1);
        const byMin = Math.min(_meScatterBox.y0, _meScatterBox.y1);
        const byMax = Math.max(_meScatterBox.y0, _meScatterBox.y1);

        if (_meScatterMode === 'zoom' && (bxMax - bxMin) > 10 && (byMax - byMin) > 10) {
            // Zoom into the box region
            _meScatterZoom = {
                xMin: toDataX(bxMin), xMax: toDataX(bxMax),
                yMin: toDataY(byMax), yMax: toDataY(byMin),
            };
            const btn = document.getElementById('me-zoom-reset-btn');
            if (btn) btn.style.display = 'block';
        } else if (_meScatterMode === 'select') {
            // Select points within box
            const passFilter = new Set(meGetFilteredCols());
            Object.entries(_meActiveData()).forEach(([col, corrs]) => {
                if (!passFilter.has(col)) return;
                const sx = toSvgX(corrs[axX] ?? 0), sy = toSvgY(corrs[axY] ?? 0);
                if (sx >= bxMin && sx <= bxMax && sy >= byMin && sy <= byMax) {
                    _meScatterSelected.add(col);
                }
            });
            _updateScatterSelCount();
        }
        _meScatterBox = null;
        _meRefreshPlot();
    };

    window.meScatterClearSelection = function () {
        _meScatterSelected.clear();
        _updateScatterSelCount();
        _meRefreshPlot();
    };

    window.meScatterAddSelected = function () {
        if (!_meScatterSelected.size) return;
        _meScatterSelected.forEach(col => {
            if (!_meControlFactors.includes(col)) _meControlFactors.push(col);
        });
        _meScatterSelected.clear();
        _updateScatterSelCount();
        _renderFactorLists();
        meRenderScatterPlot();
        // Switch back to normal mode to confirm
        meSetControlMode('normal');
    };

    function _updateScatterSelCount() {
        const el = document.getElementById('me-scatter-sel-count');
        if (el) el.textContent = _meScatterSelected.size;
    }

    // --- AI Scatter Grid Summarization ---
    let _meLatestScatterGridSummary = null;

    window.meSummarizeScatterGrid = async function () {
        // Toggle: if labels already showing, clear them
        if (_meLatestScatterGridSummary) {
            _meLatestScatterGridSummary = null;
            const btn = document.getElementById('me-plot-ai-btn');
            if (btn) btn.innerHTML = '<span style="font-size:12px;">✨</span> 九宮格摘要';
            if (typeof _updateScatterGridOverlay === 'function') _updateScatterGridOverlay();
            return;
        }

        const axX = (document.getElementById('me-scatter-axis-x') || {}).value;
        const axY = (document.getElementById('me-scatter-axis-y') || {}).value;
        if (!axX || !axY || !Object.keys(_meActiveData()).length) return;

        const passFilter = new Set(meGetFilteredCols());
        const groups = {
            top_left: [], top_center: [], top_right: [],
            mid_left: [], mid_center: [], mid_right: [],
            bottom_left: [], bottom_center: [], bottom_right: []
        };

        Object.entries(_meActiveData()).forEach(([col, corrs]) => {
            if (!passFilter.has(col)) return;
            const cx = corrs[axX] ?? 0;
            const cy = corrs[axY] ?? 0;
            let row = cy > 0.3 ? 'top' : (cy < -0.3 ? 'bottom' : 'mid');
            let col_name = cx > 0.3 ? 'right' : (cx < -0.3 ? 'left' : 'center');
            groups[`${row}_${col_name}`].push(col);
        });

        const btn = document.getElementById('me-plot-ai-btn');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<span style="font-size:12px;">⏳</span> 分析中...';
        }
        const overlay = document.getElementById('me-scatter-grid-overlay');
        if (overlay) {
            overlay.style.display = 'block';
            overlay.innerHTML = '<div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;background:rgba(255,255,255,0.7);border-radius:8px;pointer-events:auto;"><div style="color:#8b5cf6;font-size:13px;font-weight:600;padding:8px 16px;background:#fff;border-radius:20px;box-shadow:0 4px 6px -1px rgba(0,0,0,0.1);">正在請 AI 摘要九宮格特徵...</div></div>';
        }

        try {
            const sid = typeof getSessionId === 'function' ? getSessionId() : (localStorage.getItem('sigma2_session_id') || 'default');
            const res = await fetch('/api/ai/summarize_scatter_grid', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ x_axis: axX, y_axis: axY, grid_groups: groups, session_id: sid })
            });
            const result = await res.json();
            if (result.error) throw new Error(result.error);
            _meLatestScatterGridSummary = result;
            if (typeof _updateScatterGridOverlay === 'function') _updateScatterGridOverlay();
        } catch (e) {
            console.error('[ME AI Grid Scatter]', e);
            if (overlay) {
                overlay.innerHTML = `<div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;background:rgba(255,255,255,0.75);border-radius:8px;pointer-events:auto;z-index:20;">
                    <div style="color:#ef4444;font-size:13px;font-weight:600;padding:12px 20px;background:#fff;border-radius:8px;box-shadow:0 4px 12px rgba(0,0,0,0.15);display:flex;flex-direction:column;align-items:center;gap:10px;">
                        <div>❌ 分析失敗: ${e.message}</div>
                        <button onclick="document.getElementById('me-scatter-grid-overlay').style.display='none';" style="padding:4px 12px;background:#f1f5f9;border:1px solid #cbd5e1;border-radius:4px;cursor:pointer;font-size:12px;">關閉</button>
                    </div>
                </div>`;
            }
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = _meLatestScatterGridSummary
                    ? '<span style="font-size:12px;">✕</span> 清除摘要'
                    : '<span style="font-size:12px;">✨</span> 九宮格摘要';
            }
        }
    };

    window._updateScatterGridOverlay = function() {
        const overlay = document.getElementById('me-scatter-grid-overlay');
        if (!overlay) return;
        if (!_meLatestScatterGridSummary) {
            overlay.style.display = 'none';
            // Reset button text
            const btn = document.getElementById('me-plot-ai-btn');
            if (btn) btn.innerHTML = '<span style="font-size:12px;">✨</span> 九宮格摘要';
            return;
        }
        overlay.style.display = 'block';

        const svg = document.getElementById('me-scatter-svg');
        const W = svg.clientWidth || 400, H = svg.clientHeight || 280;
        const PAD = { l:52, r:20, t:24, b:44 };
        const pw = W - PAD.l - PAD.r, ph = H - PAD.t - PAD.b;
        const Z = _meScatterZoom;
        const toSvgX = v => PAD.l + (v - Z.xMin) / (Z.xMax - Z.xMin) * pw;
        const toSvgY = v => PAD.t + (1 - (v - Z.yMin) / (Z.yMax - Z.yMin)) * ph;

        const centers = {
            top_left:      { cx: -0.65, cy: 0.65 },
            top_center:    { cx: 0,     cy: 0.65 },
            top_right:     { cx: 0.65,  cy: 0.65 },
            mid_left:      { cx: -0.65, cy: 0 },
            mid_center:    { cx: 0,     cy: 0 },
            mid_right:     { cx: 0.65,  cy: 0 },
            bottom_left:   { cx: -0.65, cy: -0.65 },
            bottom_center: { cx: 0,     cy: -0.65 },
            bottom_right:  { cx: 0.65,  cy: -0.65 }
        };

        let html = '';
        // Close button — z-index 20 to ensure it's above grid labels
        html += `<button onclick="_meLatestScatterGridSummary=null; _updateScatterGridOverlay();" style="position:absolute;top:6px;right:6px;pointer-events:auto;background:rgba(255,255,255,0.95);backdrop-filter:blur(4px);border:1px solid #cbd5e1;border-radius:6px;color:#64748b;cursor:pointer;font-size:11px;padding:3px 8px;font-weight:600;box-shadow:0 2px 6px rgba(0,0,0,0.12);z-index:20;" onmouseenter="this.style.color='#ef4444';this.style.borderColor='#fca5a5'" onmouseleave="this.style.color='#64748b';this.style.borderColor='#cbd5e1'">✕ 關閉標籤</button>`;

        for (let key in centers) {
            if (!_meLatestScatterGridSummary[key]) continue;
            const sx = toSvgX(centers[key].cx);
            const sy = toSvgY(centers[key].cy);
            if (sx < 0 || sx > W || sy < 0 || sy > H) continue;
            html += `<div style="position:absolute;left:${sx}px;top:${sy}px;transform:translate(-50%,-50%);background:rgba(255,255,255,0.95);backdrop-filter:blur(2px);border:1.5px solid #a78bfa;padding:3px 8px;border-radius:6px;color:#6d28d9;font-size:11px;font-weight:700;white-space:nowrap;box-shadow:0 2px 6px rgba(0,0,0,0.15);max-width:200px;overflow:hidden;text-overflow:ellipsis;text-align:center;pointer-events:none;z-index:5;">${_meLatestScatterGridSummary[key]}</div>`;
        }
        overlay.innerHTML = html;
    };

    // --- 分析選取參數 Modal ---
    window._meAnalyzeSortCol = window._meAnalyzeSortCol || 'x';  // 'name' | 'x' | 'y'
    window._meAnalyzeSortAsc = window._meAnalyzeSortAsc ?? false;
    window.meScatterAnalyzeSelected = function () {
        if (!_meScatterSelected.size) {
            alert('請先在散佈圖上框選或點選參數！');
            return;
        }
        const axX = (document.getElementById('me-scatter-axis-x') || {}).value || '（無）';
        const axY = (document.getElementById('me-scatter-axis-y') || {}).value || '（無）';

        // Collect data: always gather both Pearson r AND SHAP independently
        const rows = [];
        _meScatterSelected.forEach(col => {
            const corrData = _meCorrelations[col] || {};
            const shapData = _meShapData[col] || {};
            rows.push({
                name:    col,
                cx:      corrData[axX] != null ? corrData[axX] : null,
                cy:      corrData[axY] != null ? corrData[axY] : null,
                cx_shap: shapData[axX] != null ? shapData[axX] : null,
                cy_shap: shapData[axY] != null ? shapData[axY] : null,
            });
        });

        _meAnalyzeRenderModal(rows, axX, axY);
    };

    function _meAnalyzeRenderModal(rows, axX, axY) {
        // Check if any SHAP data is present in the rows
        const hasShap = rows.some(r => r.cx_shap != null || r.cy_shap != null);

        // Compute a numeric score for 建議 sorting (3=雙指標一致, 2=部分顯著, 1=訊號衝突, 0=不明顯)
        const recScore = (r) => {
            const xCorrSig = r.cx != null && Math.abs(r.cx) >= 0.3;
            const yCorrSig = r.cy != null && Math.abs(r.cy) >= 0.3;
            const xShapSig = r.cx_shap != null && Math.abs(r.cx_shap) >= 0.3;
            const yShapSig = r.cy_shap != null && Math.abs(r.cy_shap) >= 0.3;
            const xAgree = (r.cx != null && r.cx_shap != null) ? Math.sign(r.cx) === Math.sign(r.cx_shap) : null;
            const yAgree = (r.cy != null && r.cy_shap != null) ? Math.sign(r.cy) === Math.sign(r.cy_shap) : null;
            const xConflict = xAgree === false && (xCorrSig || xShapSig);
            const yConflict = yAgree === false && (yCorrSig || yShapSig);
            const xBothSig  = xCorrSig && xShapSig && xAgree === true;
            const yBothSig  = yCorrSig && yShapSig && yAgree === true;
            if (xBothSig || yBothSig) return 3;
            if (xCorrSig || yCorrSig || xShapSig || yShapSig) return xConflict || yConflict ? 1 : 2;
            return 0;
        };

        // Sort
        rows.sort((a, b) => {
            let va, vb;
            if (window._meAnalyzeSortCol === 'name')   { va = a.name; vb = b.name; return window._meAnalyzeSortAsc ? va.localeCompare(vb) : vb.localeCompare(va); }
            if (window._meAnalyzeSortCol === 'x')       { va = Math.abs(a.cx ?? 0);       vb = Math.abs(b.cx ?? 0); }
            else if (window._meAnalyzeSortCol === 'y')  { va = Math.abs(a.cy ?? 0);       vb = Math.abs(b.cy ?? 0); }
            else if (window._meAnalyzeSortCol === 'xs') { va = Math.abs(a.cx_shap ?? 0);  vb = Math.abs(b.cx_shap ?? 0); }
            else if (window._meAnalyzeSortCol === 'ys') { va = Math.abs(a.cy_shap ?? 0);  vb = Math.abs(b.cy_shap ?? 0); }
            else if (window._meAnalyzeSortCol === 'rec'){ va = recScore(a);               vb = recScore(b); }
            else if (window._meAnalyzeSortCol === 'slope') { va = a.slopeDivPct ?? -Infinity; vb = b.slopeDivPct ?? -Infinity; }
            else { va = Math.abs(a.cx ?? 0); vb = Math.abs(b.cx ?? 0); }
            return window._meAnalyzeSortAsc ? va - vb : vb - va;
        });

        const arrow = (col) => {
            if (window._meAnalyzeSortCol !== col) return '<span style="color:#cbd5e1;">⇅</span>';
            return window._meAnalyzeSortAsc ? '↑' : '↓';
        };

        const metricBadge = (v, isShap) => {
            if (v == null) return '<span style="color:#94a3b8;">—</span>';
            const abs = Math.abs(v);
            const color = abs >= 0.5 ? '#dc2626' : abs >= 0.3 ? '#f97316' : '#64748b';
            const bg    = abs >= 0.5 ? '#fef2f2' : abs >= 0.3 ? '#fff7ed' : '#f8fafc';
            const border = isShap ? 'border:1.5px dashed ' + color + ';' : '';
            return `<span style="background:${bg};color:${color};${border}padding:3px 9px;border-radius:10px;font-weight:700;font-size:12px;">${v >= 0 ? '+' : ''}${v.toFixed(3)}</span>`;
        };

        // Recommendation badge
        const recBadge = (r) => {
            if (!hasShap) return '';
            const sc = recScore(r);
            const xCorrSig = r.cx != null && Math.abs(r.cx) >= 0.3;
            const yCorrSig = r.cy != null && Math.abs(r.cy) >= 0.3;
            const xShapSig = r.cx_shap != null && Math.abs(r.cx_shap) >= 0.3;
            const yShapSig = r.cy_shap != null && Math.abs(r.cy_shap) >= 0.3;
            const xAgree = (r.cx != null && r.cx_shap != null) ? Math.sign(r.cx) === Math.sign(r.cx_shap) : null;
            const yAgree = (r.cy != null && r.cy_shap != null) ? Math.sign(r.cy) === Math.sign(r.cy_shap) : null;
            const xConflict = xAgree === false && (xCorrSig || xShapSig);
            const yConflict = yAgree === false && (yCorrSig || yShapSig);
            if (sc === 3)
                return `<span style="background:#f0fdf4;color:#16a34a;border:1px solid #bbf7d0;padding:3px 9px;border-radius:10px;font-size:11px;font-weight:700;">雙指標一致 ✓</span>`;
            if (xConflict || yConflict)
                return `<span style="background:#fff7ed;color:#ea580c;border:1px solid #fed7aa;padding:3px 9px;border-radius:10px;font-size:11px;font-weight:700;">訊號衝突</span>`;
            if (sc === 2)
                return `<span style="background:#eff6ff;color:#2563eb;border:1px solid #bfdbfe;padding:3px 9px;border-radius:10px;font-size:11px;font-weight:700;">部分顯著</span>`;
            return `<span style="color:#94a3b8;font-size:11px;">影響不明顯</span>`;
        };

        const thStyle = (col) => `
            padding:9px 12px;text-align:center;font-size:12px;font-weight:700;color:#475569;
            border-bottom:2px solid #e2e8f0;cursor:pointer;user-select:none;
            background:${window._meAnalyzeSortCol === col ? '#f0f7ff' : '#f8fafc'};
            white-space:nowrap;
        `;
        const thStyleFixed = `padding:9px 12px;text-align:center;font-size:12px;font-weight:700;color:#475569;border-bottom:2px solid #e2e8f0;background:#f8fafc;white-space:nowrap;`;

        const sortFn = (col) => `_meSortAnalyze('${col}')`;
        window._meSortAnalyze = function(col) {
            if (window._meAnalyzeSortCol === col) {
                window._meAnalyzeSortAsc = !window._meAnalyzeSortAsc;
            } else {
                window._meAnalyzeSortCol = col;
                window._meAnalyzeSortAsc = false;
            }
            _meAnalyzeRenderModal(window._meAnalyzeRows, axX, axY);
        };

        // Tiny loading placeholder SVG
        const loadingCell = `<td style="padding:4px 8px;width:176px;">
            <div style="display:flex;gap:4px;">
                <div style="width:82px;height:56px;background:#f1f5f9;border-radius:5px;display:flex;align-items:center;justify-content:center;">
                    <span style="font-size:9px;color:#94a3b8;">⏳</span></div>
                <div style="width:82px;height:56px;background:#f1f5f9;border-radius:5px;display:flex;align-items:center;justify-content:center;">
                    <span style="font-size:9px;color:#94a3b8;">⏳</span></div>
            </div></td>`;

        const slopeLoadCell = `<td id="me-analyze-slope-IDX" style="padding:6px 10px;text-align:center;min-width:160px;"><span style="color:#94a3b8;font-size:11px;">⏳</span></td>`;

        let tableRows = rows.map((r, i) => {
            const bg0 = i % 2 ? '#f8fafc' : '#fff';
            const shapXCell = hasShap ? `<td style="padding:6px 8px;text-align:center;">${metricBadge(r.cx_shap, true)}</td>` : '';
            const shapYCell = hasShap ? `<td style="padding:6px 8px;text-align:center;">${metricBadge(r.cy_shap, true)}</td>` : '';
            const recCell   = hasShap ? `<td style="padding:6px 8px;text-align:center;">${recBadge(r)}</td>` : '';
            return `
            <tr id="me-analyze-row-${i}" style="background:${bg0};cursor:pointer;"
                onclick="meAnalyzeRowDetail(${i})"
                onmouseenter="this.style.background='#eff6ff'"
                onmouseleave="this.style.background=(window._meAnalyzeActiveRow===${i}?'#e0f2fe':'${bg0}')">
                <td style="padding:7px 12px;font-size:13px;color:#1e293b;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${r.name}">${r.name}</td>
                <td style="padding:6px 8px;text-align:center;">${metricBadge(r.cx, false)}</td>
                ${shapXCell}
                <td style="padding:6px 8px;text-align:center;">${metricBadge(r.cy, false)}</td>
                ${shapYCell}
                ${recCell}
                ${slopeLoadCell.replace('IDX', i)}
                ${loadingCell}
            </tr>`;
        }).join('');

        window._meAnalyzeRows = rows;

        // Use a session token so stale async updates don't overwrite a re-opened modal
        const sessionToken = Date.now();
        window._meAnalyzeSession = sessionToken;

        // Build dynamic header columns
        const shapLegend = hasShap
            ? `&nbsp;|&nbsp; <span style="border:1px dashed #f97316;border-radius:4px;padding:0 4px;font-size:10px;color:#ea580c;">虛線框</span> = SHAP（已歸一化）`
            : `&nbsp;|&nbsp; <span style="color:#94a3b8;font-size:10px;">計算 SHAP 後可顯示雙指標</span>`;

        const xHeaders = hasShap ? `
            <th style="${thStyle('x')}" onclick="${sortFn('x')}">r vs X ${arrow('x')}</th>
            <th style="${thStyle('xs')}" onclick="${sortFn('xs')}">SHAP vs X ${arrow('xs')}</th>` : `
            <th style="${thStyle('x')}" onclick="${sortFn('x')}">與 X 軸相關性 ${arrow('x')}</th>`;
        const yHeaders = hasShap ? `
            <th style="${thStyle('y')}" onclick="${sortFn('y')}">r vs Y ${arrow('y')}</th>
            <th style="${thStyle('ys')}" onclick="${sortFn('ys')}">SHAP vs Y ${arrow('ys')}</th>` : `
            <th style="${thStyle('y')}" onclick="${sortFn('y')}">與 Y 軸相關性 ${arrow('y')}</th>`;
        const recHeader = hasShap ? `<th style="${thStyle('rec')}" onclick="${sortFn('rec')}">建議 ${arrow('rec')}</th>` : '';
        const slopeHeader = `
            <th style="${thStyle('slope')}" onclick="${sortFn('slope')}" title="斜率 β（vs X / vs Y）&#10;排序依：|βX − βY| / max(|βX|,|βY|)&#10;= 兩目標斜率差異的百分比&#10;百分比愈高 → 對X、Y的影響差異愈大&#10;顯示值為原始 β">斜率 β ${arrow('slope')}<br><span style="font-size:9px;font-weight:400;color:#94a3b8;">vs X / vs Y</span></th>`;

        const modalWidth = hasShap ? '1200px' : '1020px';

        let existing = document.getElementById('me-analyze-modal');
        if (!existing) {
            existing = document.createElement('div');
            existing.id = 'me-analyze-modal';
            document.body.appendChild(existing);
        }
        existing.style.cssText = 'position:fixed;inset:0;z-index:9999;display:flex;align-items:center;justify-content:center;';
        // Reset detail panel state on each open
        window._meADSyncYAxis = false;
        window._meADPayload = null;
        window._meADBrush = null;
        window._meAnalyzeActiveRow = -1;
        existing.innerHTML = `
            <div style="position:absolute;inset:0;background:rgba(15,23,42,0.45);backdrop-filter:blur(4px);" onclick="document.getElementById('me-analyze-modal').style.display='none';"></div>
            <div style="position:relative;background:#fff;border-radius:16px;box-shadow:0 20px 60px rgba(0,0,0,0.25);width:${modalWidth};max-width:97vw;max-height:85vh;display:flex;flex-direction:column;overflow:hidden;">
                <!-- Header -->
                <div style="padding:16px 20px 12px;border-bottom:1px solid #e2e8f0;display:flex;align-items:center;justify-content:space-between;flex-shrink:0;">
                    <div style="display:flex;align-items:center;gap:8px;">
                        <div>
                            <div style="font-size:15px;font-weight:700;color:#1e293b;">🔍 選取參數分析</div>
                            <div style="font-size:11px;color:#64748b;margin-top:2px;">共 ${rows.length} 個參數 &nbsp;|&nbsp; 點擊列查看完整散佈圖 &nbsp;|&nbsp; 點擊表頭排序${shapLegend}</div>
                        </div>
                        <!-- Help icon -->
                        <div style="position:relative;display:inline-block;" id="me-analyze-help-wrap">
                            <button onclick="(function(){var p=document.getElementById('me-analyze-help-pop');p.style.display=p.style.display==='block'?'none':'block';})();"
                                style="background:#e0f2fe;border:none;border-radius:50%;width:22px;height:22px;cursor:pointer;font-size:12px;font-weight:700;color:#0284c7;display:flex;align-items:center;justify-content:center;line-height:1;flex-shrink:0;"
                                title="指標說明">?</button>
                            <div id="me-analyze-help-pop" style="display:none;position:absolute;left:0;top:28px;z-index:100;background:#fff;border:1px solid #e2e8f0;border-radius:12px;box-shadow:0 8px 32px rgba(0,0,0,0.18);padding:16px 18px;width:340px;max-height:60vh;overflow-y:auto;font-size:11px;color:#334155;line-height:1.7;">
                                <div style="font-weight:700;font-size:12px;color:#1e293b;margin-bottom:8px;">如何解讀兩個指標？</div>
                                <div style="margin-bottom:10px;">
                                    <span style="font-weight:700;color:#2563eb;">相關係數 r</span>（實線框）<br>
                                    衡量線性關係強弱。正值代表同向、負值代表反向。<br>
                                    <span style="color:#dc2626;">|r| ≥ 0.5 強相關</span>，<span style="color:#f97316;">|r| ≥ 0.3 中等</span>，<span style="color:#64748b;">其餘偏低</span>。
                                </div>
                                <div style="margin-bottom:10px;">
                                    <span style="font-weight:700;color:#ea580c;">SHAP 值</span>（虛線框，已歸一化至 ±1）<br>
                                    衡量非線性模型中的實際貢獻度，正負代表影響方向。<br>
                                    比 r 更能捕捉複雜交互作用。
                                </div>
                                <div style="border-top:1px solid #e2e8f0;padding-top:8px;margin-bottom:4px;font-weight:700;font-size:11px;color:#1e293b;">建議欄判讀</div>
                                <div style="display:flex;flex-direction:column;gap:5px;">
                                    <div><span style="background:#f0fdf4;color:#16a34a;border:1px solid #bbf7d0;padding:1px 6px;border-radius:8px;font-weight:700;font-size:10px;">雙指標一致 ✓</span> 兩者均顯著且方向相同 → 高可信度，優先調整</div>
                                    <div><span style="background:#fff7ed;color:#ea580c;border:1px solid #fed7aa;padding:1px 6px;border-radius:8px;font-weight:700;font-size:10px;">訊號衝突</span> 方向相反 → 可能有非線性或分群，需確認散佈圖</div>
                                    <div><span style="background:#eff6ff;color:#2563eb;border:1px solid #bfdbfe;padding:1px 6px;border-radius:8px;font-weight:700;font-size:10px;">部分顯著</span> 僅單一指標超過門檻 → 參考但謹慎</div>
                                    <div><span style="color:#94a3b8;font-size:10px;">影響不明顯</span> 兩者皆低 → 此參數對目標影響有限</div>
                                </div>
                                <div style="margin-top:10px;padding:8px;background:#f8fafc;border-radius:6px;color:#64748b;font-size:10px;">
                                    💡 <b>建議流程：</b>先看「雙指標一致」的參數，再以散佈圖確認趨勢，遇到「訊號衝突」時留意非線性效果。
                                </div>
                            </div>
                        </div>
                    </div>
                    <button onclick="document.getElementById('me-analyze-modal').style.display='none';" style="background:#f1f5f9;border:none;border-radius:8px;width:28px;height:28px;cursor:pointer;font-size:15px;color:#64748b;display:flex;align-items:center;justify-content:center;line-height:1;">✕</button>
                </div>
                <!-- X/Y label -->
                <div style="padding:8px 20px;background:#f8fafc;border-bottom:1px solid #e2e8f0;display:flex;gap:20px;align-items:center;flex-shrink:0;">
                    <div style="font-size:11px;color:#64748b;"><span style="font-weight:700;color:#2563eb;">X軸：</span>${axX}</div>
                    <div style="font-size:11px;color:#64748b;"><span style="font-weight:700;color:#7c3aed;">Y軸：</span>${axY}</div>
                    ${hasShap ? `<button onclick="(function(){var p=document.getElementById('me-consensus-panel');var b=document.getElementById('me-consensus-toggle');var open=p.style.display!=='none';p.style.display=open?'none':'block';b.textContent=open?'▶ 共識分析圖':'▼ 共識分析圖';})()" id="me-consensus-toggle" style="margin-left:auto;background:#eff6ff;color:#2563eb;border:1px solid #bfdbfe;border-radius:6px;font-size:11px;font-weight:600;padding:3px 10px;cursor:pointer;">▼ 共識分析圖</button>` : ''}
                </div>
                ${hasShap ? `<!-- Consensus chart panel -->
                <div id="me-consensus-panel" style="border-bottom:1px solid #e2e8f0;background:#fafbff;padding:14px 20px;flex-shrink:0;">
                    <div id="me-consensus-charts" style="display:flex;gap:16px;align-items:flex-start;"></div>
                </div>` : ''}
                <!-- Table -->
                <div style="overflow-y:auto;flex:1;">
                    <table style="width:100%;border-collapse:collapse;">
                        <thead style="position:sticky;top:0;z-index:2;">
                            <tr>
                                <th style="${thStyle('name')}" onclick="${sortFn('name')}">參數名稱 ${arrow('name')}</th>
                                ${xHeaders}
                                ${yHeaders}
                                ${recHeader}
                                ${slopeHeader}
                                <th style="${thStyleFixed}">散佈圖 <span style="font-weight:400;color:#94a3b8;font-size:10px;">(vs X / vs Y)</span></th>
                            </tr>
                        </thead>
                        <tbody>${tableRows}</tbody>
                    </table>
                </div>
                <!-- Inline row detail panel -->
                <div id="me-analyze-detail" style="display:none;border-top:2px solid #e0e7ff;flex-shrink:0;background:#f5f7ff;max-height:420px;overflow-y:auto;"></div>
                <!-- Footer -->
                <div style="padding:10px 20px;border-top:1px solid #e2e8f0;display:flex;justify-content:flex-end;flex-shrink:0;">
                    <button onclick="meScatterAddSelected();document.getElementById('me-analyze-modal').style.display='none';" style="padding:6px 18px;background:#2563eb;color:#fff;border:none;border-radius:8px;font-size:12px;font-weight:600;cursor:pointer;margin-right:8px;">＋ 加入控制參數</button>
                    <button onclick="document.getElementById('me-analyze-modal').style.display='none';" style="padding:6px 16px;background:#f1f5f9;color:#64748b;border:1px solid #e2e8f0;border-radius:8px;font-size:12px;cursor:pointer;">關閉</button>
                </div>
            </div>
        `;

        // Async load sparklines in batches of 8
        _meLoadSparklines(rows, axX, axY, sessionToken);
    }

    // Render a tiny inline SVG scatter plot
    function _meTinyScatterSvg(xVals, yVals, color) {
        const W = 82, H = 56, PAD = { l:3, r:3, t:3, b:3 };
        const pw = W - PAD.l - PAD.r, ph = H - PAD.t - PAD.b;
        if (!xVals.length || !yVals.length)
            return `<svg width="${W}" height="${H}"><rect x="${PAD.l}" y="${PAD.t}" width="${pw}" height="${ph}" fill="#f1f5f9" rx="3"/><text x="${W/2}" y="${H/2+3}" text-anchor="middle" font-size="8" fill="#94a3b8">無資料</text></svg>`;
        const xMin = Math.min(...xVals), xMax = Math.max(...xVals), xRange = xMax - xMin || 1;
        const yMin = Math.min(...yVals), yMax = Math.max(...yVals), yRange = yMax - yMin || 1;
        const sx = v => PAD.l + (v - xMin) / xRange * pw;
        const sy = v => PAD.t + (1 - (v - yMin) / yRange) * ph;
        const n = xVals.length;
        const xM = xVals.reduce((a,b) => a+b,0)/n, yM = yVals.reduce((a,b) => a+b,0)/n;
        const num = xVals.reduce((s,x,i) => s+(x-xM)*(yVals[i]-yM),0);
        const dX = xVals.reduce((s,x) => s+(x-xM)**2,0);
        const dY = yVals.reduce((s,y) => s+(y-yM)**2,0);
        const r = (dX&&dY) ? num/Math.sqrt(dX*dY) : 0;
        const slope = dX ? num/dX : 0, intc = yM - slope*xM;
        const lx1 = sx(xMin), ly1 = Math.max(PAD.t, Math.min(PAD.t+ph, sy(slope*xMin+intc)));
        const lx2 = sx(xMax), ly2 = Math.max(PAD.t, Math.min(PAD.t+ph, sy(slope*xMax+intc)));
        // sample max 120 pts to keep SVG small
        const step = Math.max(1, Math.floor(n/120));
        let dots = '';
        for (let i = 0; i < n; i += step)
            dots += `<circle cx="${sx(xVals[i]).toFixed(1)}" cy="${sy(yVals[i]).toFixed(1)}" r="2" fill="${color}" opacity="0.5"/>`;
        return `<svg width="${W}" height="${H}">
            <rect x="${PAD.l}" y="${PAD.t}" width="${pw}" height="${ph}" fill="#f8fafc" rx="3"/>
            ${dots}
            <line x1="${lx1.toFixed(1)}" y1="${ly1.toFixed(1)}" x2="${lx2.toFixed(1)}" y2="${ly2.toFixed(1)}" stroke="${color}" stroke-width="1.5" opacity="0.8"/>
        </svg>`;
    }

    async function _meLoadSparklines(rows, axX, axY, sessionToken) {
        const fileId = typeof currentFileId !== 'undefined' ? currentFileId : '';
        const sid = typeof getSessionId === 'function' ? getSessionId() : (localStorage.getItem('sigma2_session_id') || 'default');
        const yCols = encodeURIComponent([axX, axY].join(','));
        const BATCH = 8;

        for (let i = 0; i < rows.length; i += BATCH) {
            const batch = rows.slice(i, i + BATCH);
            await Promise.all(batch.map(async (r, bi) => {
                const idx = i + bi;
                if (window._meAnalyzeSession !== sessionToken) return; // modal re-opened
                try {
                    const resp = await fetch(`/api/data-prep/xy-data/${fileId}?x_col=${encodeURIComponent(r.name)}&y_cols=${yCols}&session_id=${encodeURIComponent(sid)}`);
                    if (window._meAnalyzeSession !== sessionToken) return;
                    const payload = await resp.json();
                    const xVals = payload.data[r.name] || [];
                    const vX = payload.data[axX] || [];
                    const vY = payload.data[axY] || [];
                    const calcStats = (xs, ys) => {
                        const n = xs.length; if (!n) return { r: 0, slope: 0 };
                        const xM = xs.reduce((a,b)=>a+b,0)/n, yM = ys.reduce((a,b)=>a+b,0)/n;
                        const num = xs.reduce((s,x,j)=>s+(x-xM)*(ys[j]-yM),0);
                        const dX = xs.reduce((s,x)=>s+(x-xM)**2,0), dY = ys.reduce((s,y)=>s+(y-yM)**2,0);
                        const r = (dX&&dY)?num/Math.sqrt(dX*dY):0;
                        const slope = dX ? num/dX : 0;
                        return { r, slope };
                    };
                    const stX = calcStats(xVals, vX);
                    const stY = calcStats(xVals, vY);
                    const rX = stX.r, rY = stY.r;
                    const rawBX = stX.slope, rawBY = stY.slope;

                    // Normalize slope by relative range: β × (xMax−xMin) / |xMean|
                    // = "Y change when X moves its full range, relative to X's own level"
                    // This eliminates both unit and scale differences, making slopes comparable.
                    const xMin = xVals.length ? Math.min(...xVals) : 0;
                    const xMax = xVals.length ? Math.max(...xVals) : 0;
                    const paramRange = xMax - xMin || 1;
                    const xMean = xVals.length ? xVals.reduce((a, b) => a + b, 0) / xVals.length : 1;
                    const xMeanAbs = Math.abs(xMean) || paramRange; // fallback if mean ≈ 0
                    const normFactor = paramRange / xMeanAbs;
                    const bX = rawBX * normFactor;
                    const bY = rawBY * normFactor;

                    const _rColor = rv => Math.abs(rv)<0.1?'#94a3b8':rv>0?'#2563eb':'#ef4444';
                    const cX = _rColor(rX);
                    const cY = _rColor(rY);
                    const svgX = _meTinyScatterSvg(xVals, vX, cX);
                    const svgY = _meTinyScatterSvg(xVals, vY, cY);

                    // Format normalized slope
                    const fmtSlope = v => {
                        if (v === 0) return '0';
                        const abs = Math.abs(v);
                        const dec = abs >= 100 ? 1 : abs >= 10 ? 2 : abs >= 1 ? 3 : abs >= 0.1 ? 4 : abs >= 0.01 ? 5 : 6;
                        return (v >= 0 ? '+' : '') + v.toFixed(dec);
                    };
                    const slopeColor = v => Math.abs(v) < 0.0001 ? '#94a3b8' : v > 0 ? '#2563eb' : '#ef4444';

                    // Sort key: |βX − βY| / max(|βX|,|βY|)  — percentage divergence between the two target slopes
                    const maxAbs = Math.max(Math.abs(rawBX), Math.abs(rawBY));
                    const slopeDivPct = maxAbs > 0 ? Math.abs(rawBX - rawBY) / maxAbs : 0;
                    if (window._meAnalyzeRows && window._meAnalyzeRows[idx]) {
                        window._meAnalyzeRows[idx].slopeDivPct = slopeDivPct;
                    }

                    // Update single merged slope cell — show both raw β values + divergence %
                    const slopeTd = document.getElementById(`me-analyze-slope-${idx}`);
                    if (slopeTd) {
                        const divPctStr = (slopeDivPct * 100).toFixed(1) + '%';
                        const divColor  = slopeDivPct > 0.3 ? '#f97316' : slopeDivPct > 0.1 ? '#eab308' : '#94a3b8';
                        slopeTd.innerHTML = `
                            <div style="display:flex;flex-direction:column;gap:2px;align-items:center;">
                                <div style="display:flex;gap:8px;align-items:baseline;">
                                    <span style="font-size:12px;font-weight:700;color:${slopeColor(rawBX)};">${fmtSlope(rawBX)}<span style="font-size:9px;font-weight:400;color:#94a3b8;margin-left:2px;">X</span></span>
                                    <span style="font-size:12px;font-weight:700;color:${slopeColor(rawBY)};">${fmtSlope(rawBY)}<span style="font-size:9px;font-weight:400;color:#94a3b8;margin-left:2px;">Y</span></span>
                                </div>
                                <span style="font-size:9px;color:${divColor};font-weight:600;" title="兩斜率差異百分比 = |βX−βY|/max(|βX|,|βY|)">差異 ${divPctStr}</span>
                            </div>`;
                    }

                    const rowEl = document.getElementById(`me-analyze-row-${idx}`);
                    if (!rowEl) return;
                    const td = rowEl.querySelector('td:last-child');
                    if (!td) return;
                    td.innerHTML = `<div style="display:flex;gap:4px;align-items:flex-end;">
                        <div>
                            <div style="font-size:8px;color:${cX};font-weight:700;text-align:right;margin-bottom:1px;">r=${rX>=0?'+':''}${rX.toFixed(2)}</div>
                            ${svgX}
                        </div>
                        <div>
                            <div style="font-size:8px;color:${cY};font-weight:700;text-align:right;margin-bottom:1px;">r=${rY>=0?'+':''}${rY.toFixed(2)}</div>
                            ${svgY}
                        </div>
                    </div>`;
                } catch(e) { /* quietly ignore */ }
            }));
        }
    }

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
        // Invalidate result panel AND correlations — cleaning rules affect the data
        // so any previously computed correlations / SHAP are no longer valid
        _meRenderCtx = null;
        _meSimResults = null;
        _meCorrelations = {};
        _meShapData = {};
        const resultArea = document.getElementById('me-step3-content');
        if (resultArea) resultArea.innerHTML = `
            <div style="display:flex;align-items:center;justify-content:center;width:100%;height:100%;flex-direction:column;gap:8px;color:#94a3b8;">
                <div style="font-size:28px;">⚠️</div>
                <div style="font-size:13px;color:#f59e0b;font-weight:600;">清洗規則已變更</div>
                <div style="font-size:12px;">請重新執行分析以使用最新資料</div>
            </div>`;
        // Also clear scatter display so stale correlations are not visible
        const advPane = document.getElementById('me-advanced-pane');
        if (advPane && advPane.style.display !== 'none') {
            meFetchAndRenderScatter();
        }
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
        _meCorrelations = {};
        _meShapData = {};
        _meScatterMetric = 'corr';
        _meScatterSelected.clear();
        _updateScatterSelCount();
        _meUpdateMetricToggle();
        const resultArea = document.getElementById('me-step3-content');
        if (resultArea) resultArea.innerHTML = _emptyState('請重新設定並執行分析');
        _renderTargetChips();
        _renderFactorLists();
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
        if (n === 2) {
            _renderFactorLists();
            // If advanced mode is active and correlations not yet computed, auto-fetch
            const advPane = document.getElementById('me-advanced-pane');
            if (advPane && advPane.style.display !== 'none' && !Object.keys(_meCorrelations).length && _meTargets.length > 0) {
                meFetchAndRenderScatter();
            }
        }

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

        // 切換子資料集後，過濾掉已被新資料集清洗規則排除的欄位
        const _allColsSet = new Set(_meAllCols);
        _meControlFactors = _meControlFactors.filter(c => _allColsSet.has(c));
        _meBgFactors      = _meBgFactors.filter(c => _allColsSet.has(c));
        const prevTargetCount = _meTargets.length;
        _meTargets = _meTargets.filter(t => _allColsSet.has(t.col));
        if (_meTargets.length !== prevTargetCount) {
            // 有 target 被排除 → 重新正規化權重、軟性 reset 結果
            _normalizeWeights();
            _meRenderCtx = null;
            _meSimResults = null;
            if (_meStep === 3) meGotoStep(2);
        }

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
        // Rebuild custom target dropdown
        _buildTargetDropdown();
    }

    function _buildTargetDropdown() {
        const wrap = document.getElementById('me-target-dd-wrap');
        if (!wrap) return;
        const cols = _meAllCols.slice();
        const itemsHtml = cols.map(c =>
            `<div class="me-td-item" data-col="${c}" onclick="_meSelectTargetDD(this)"
                style="padding:7px 14px;font-size:13px;color:#1e293b;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;"
                onmouseenter="this.style.background='#eff6ff'" onmouseleave="this.style.background='';">${c}</div>`
        ).join('');
        wrap.innerHTML = `
            <div id="me-target-dd-trigger" onclick="_meToggleTargetDD(event)"
                style="display:flex;align-items:center;border:1px solid #cbd5e1;border-radius:6px;padding:0 10px;height:38px;cursor:pointer;background:#fff;gap:6px;user-select:none;">
                <span id="me-target-dd-label" style="flex:1;font-size:13px;color:#94a3b8;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">— 選擇目標變數 —</span>
                <span style="color:#94a3b8;font-size:10px;flex-shrink:0;">▼</span>
            </div>
            <div id="me-target-dd-panel" style="display:none;position:absolute;top:calc(100% + 4px);left:0;right:0;z-index:600;background:#fff;border:1px solid #e2e8f0;border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,0.18);overflow:hidden;">
                <div style="padding:6px 8px;border-bottom:1px solid #f1f5f9;">
                    <input id="me-target-dd-search" type="text" placeholder="搜尋欄位…" oninput="_meFilterTargetDD()"
                        onclick="event.stopPropagation()"
                        style="width:100%;border:1px solid #e2e8f0;border-radius:4px;padding:5px 8px;font-size:12px;outline:none;box-sizing:border-box;color:#1e293b;">
                </div>
                <div id="me-target-dd-list" style="max-height:40vh;overflow-y:auto;">${itemsHtml}</div>
            </div>`;
        // Close on outside click (re-register each rebuild)
        document.removeEventListener('click', window._meTDDOutsideClick);
        window._meTDDOutsideClick = function(e) {
            const panel = document.getElementById('me-target-dd-panel');
            const wrap2 = document.getElementById('me-target-dd-wrap');
            if (panel && wrap2 && !wrap2.contains(e.target)) panel.style.display = 'none';
        };
        document.addEventListener('click', window._meTDDOutsideClick);
    }

    window._meToggleTargetDD = function(e) {
        e && e.stopPropagation();
        const panel = document.getElementById('me-target-dd-panel');
        if (!panel) return;
        const open = panel.style.display !== 'none';
        panel.style.display = open ? 'none' : 'block';
        if (!open) {
            const s = document.getElementById('me-target-dd-search');
            if (s) { s.value = ''; window._meFilterTargetDD(); s.focus(); }
        }
    };

    window._meFilterTargetDD = function() {
        const kw = (document.getElementById('me-target-dd-search')?.value || '').toLowerCase();
        document.querySelectorAll('#me-target-dd-list .me-td-item').forEach(item => {
            item.style.display = item.dataset.col.toLowerCase().includes(kw) ? '' : 'none';
        });
    };

    window._meSelectTargetDD = function(el) {
        const col = el.dataset.col;
        document.getElementById('me-target-dd-panel').style.display = 'none';
        _meSetTargetDDLabel(col);
        const hiddenSel = document.getElementById('me-target-select');
        if (hiddenSel) { hiddenSel.value = col; }
        if (typeof window.meTargetChange === 'function') window.meTargetChange();
    };

    function _meSetTargetDDLabel(val) {
        const label = document.getElementById('me-target-dd-label');
        if (!label) return;
        if (val) { label.textContent = val; label.style.color = '#1e293b'; }
        else      { label.textContent = '— 選擇目標變數 —'; label.style.color = '#94a3b8'; }
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
            const excludeCols = (typeof _clExcludedCols !== 'undefined') ? [..._clExcludedCols] : [];
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
        _meSetTargetDDLabel('');
        _meCurrentTrendCol = null;
        const chartArea = document.getElementById('me-trend-area');
        if (chartArea) chartArea.innerHTML = '<div style="color:#94a3b8;font-size:12px;text-align:center;">選擇目標後顯示數據趨勢</div>';
        _renderTargetChips();
        _renderFactorLists(); // Remove this col from control/bg lists immediately
        _updateRunBtn();
        _meSyncAdvancedFilters();
        // If advanced mode is open and correlations are stale, auto-refresh scatter
        const advPane = document.getElementById('me-control-advanced-pane');
        if (advPane && advPane.style.display !== 'none' && _meStep === 2) {
            meFetchAndRenderScatter();
        }
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
        _meSetTargetDDLabel(col);
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
        _meSyncAdvancedFilters();
    };

    function _meSyncAdvancedFilters() {
        if (_meControlMode !== 'advanced') return;
        meSetupScatterAxes();
        meRenderScatterFilters();
        // Refresh whichever view is currently visible
        const gv = document.getElementById('me-global-view');
        if (gv && gv.style.display !== 'none') {
            meRenderGlobalView();
        } else {
            meRenderScatterPlot();
        }
    }

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

            // 顯示被略過的欄位警告
            if (data.skipped_factors && data.skipped_factors.length > 0) {
                const warn = document.createElement('div');
                warn.style.cssText = 'margin:8px 16px 0;padding:8px 12px;background:#fffbeb;border:1px solid #fde68a;border-radius:6px;font-size:12px;color:#92400e;';
                warn.innerHTML = `⚠ 以下欄位在資料清洗後不存在，已略過：<b>${data.skipped_factors.join('、')}</b>`;
                resultArea.insertBefore(warn, resultArea.firstChild);
            }
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
        if (ps.lsl != null) parts.push(`<span style="color:#0891b2;font-weight:700;">L:${fmt(ps.lsl)}</span>`);
        if (ps.usl != null) parts.push(`<span style="color:#f97316;font-weight:700;">U:${fmt(ps.usl)}</span>`);
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

    // ═══════════════════════════════════════════════════════════════
    // NOTE SAVING — state exposure & auto-run helpers
    // ═══════════════════════════════════════════════════════════════

    window._meGetNoteData = function () {
        if (!_meRenderCtx) return null;
        const { factorOrder, targetOrder, byTarget, algorithm, n_rows, analysisMethod } = _meRenderCtx;

        // ALE amplitude per factor (max swing across all targets) for ranking
        const aleAmplitude = {};
        factorOrder.forEach(f => {
            let maxAmp = 0;
            targetOrder.forEach(t => {
                const ale = byTarget[t]?.[f]?.ale;
                if (ale && ale.length > 1) {
                    const valid = ale.filter(v => v != null);
                    if (valid.length > 1) maxAmp = Math.max(maxAmp, Math.max(...valid) - Math.min(...valid));
                }
            });
            aleAmplitude[f] = maxAmp;
        });

        // Current predicted values per target (from DOM label)
        const predVals = {};
        targetOrder.forEach((t, ti) => {
            const el = document.getElementById(`me-pred-${ti}`);
            predVals[t] = el?.textContent?.trim() || '—';
        });

        return {
            factorOrder: [...factorOrder],
            targetOrder: [...targetOrder],
            byTarget,
            algorithm: algorithm || 'XGBoost',
            n_rows: n_rows || 0,
            analysisMethod: analysisMethod || 'ale',
            targetStats: { ..._meTargetStats },
            colStats:    { ..._meColStats },
            sliderVals:  { ..._meSliderVals },
            paramSpecs:  { ..._meParamSpecs },
            smartScores: { ..._smartScores },
            simResults:  _meSimResults,
            targets:         [..._meTargets],
            controlFactors:  [..._meControlFactors],
            bgFactors:       [..._meBgFactors],
            fixedFactors:    [..._meFixedFactors],
            aleAmplitude,
            predVals,
            optSolutions:   window._meOptSolutions   || null,
            optDrawerCtx:   window._meOptDrawerCtx   || null,
            lastSmartRange: window._meLastSmartRange || null,
        };
    };

    // Auto-run optimization (uses step-1 targets with direction=target, value=target_mean??mean)
    window._meAutoRunOptimize = async function () {
        if (window._meOptSolutions) return window._meOptSolutions;
        if (!_meRenderCtx) throw new Error('請先執行主效應分析');
        const { targetOrder } = _meRenderCtx;

        const directions = {}, targetValues = {};
        targetOrder.forEach(t => {
            const ts = _meTargetStats[t] || {};
            directions[t] = 'target';
            const tv = ts.target_mean ?? ts.mean;
            if (tv != null && !isNaN(tv)) targetValues[t] = tv;
        });

        const allFixed = new Set([..._meFixedFactors, ..._meBgFactors]);
        const sid = typeof getSessionId === 'function' ? getSessionId() : 'default';
        const resp = await fetch(`/api/data-prep/me-optimize?session_id=${sid}`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                directions,
                target_values: targetValues,
                fixed_factors: [...allFixed],
                fixed_values: Object.fromEntries([...allFixed].map(f => [f, _meSliderVals[f] ?? (_meColStats[f]?.median ?? 0)])),
                n_solutions: 30,
                n_gen: 50,
            }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || '最佳化失敗');

        const { target_order, free_factors, solutions } = data;
        const scored = solutions.map(sol => {
            let inSpec = 0, normErr = 0;
            target_order.forEach(t => {
                const ts = _meTargetStats[t] || {};
                const v = sol.targets[t];
                const usl = ts.usl ?? ts.ucl, lsl = ts.lsl ?? ts.lcl;
                if (usl != null && lsl != null && v >= lsl && v <= usl) inSpec++;
                const ref = targetValues[t] ?? (ts.mean ?? 0);
                const specRange = (usl != null && lsl != null) ? (usl - lsl) : (ts.std ?? 1);
                normErr += Math.abs(v - ref) / (specRange || 1);
            });
            return { sol, inSpec, normErr };
        });
        scored.sort((a, b) => b.inSpec - a.inSpec || a.normErr - b.normErr);

        window._meOptSolutions = { solutions: scored.map(s => s.sol), free_factors };
        window._meOptDrawerCtx = { scored, target_order, free_factors, directions, targetValues };

        // Apply best solution to sliders so prediction display updates
        const best = scored[0]?.sol;
        if (best) {
            free_factors.forEach(f => { if (best.params[f] != null) _meSliderVals[f] = best.params[f]; });
            _updatePredictions();
        }
        return window._meOptSolutions;
    };

    // Auto-run smart range using best optimization solution
    window._meAutoRunSmartRange = async function () {
        if (window._meLastSmartRange) return window._meLastSmartRange;
        if (!window._meOptSolutions) throw new Error('請先執行最佳化');
        const { solutions, free_factors } = window._meOptSolutions;
        const { targetOrder } = _meRenderCtx;

        const sol = solutions[window._meOptSelected ?? 0] || solutions[0];
        if (!sol) throw new Error('無最佳化結果');

        const centerX = {};
        free_factors.forEach(f => { if (sol.params[f] != null) centerX[f] = sol.params[f]; });

        const targetSpecs = {};
        targetOrder.forEach(t => {
            const ts = _meTargetStats[t] || {};
            if (ts.usl != null || ts.lsl != null)
                targetSpecs[t] = { usl: ts.usl ?? null, lsl: ts.lsl ?? null };
        });

        const sid = typeof getSessionId === 'function' ? getSessionId() : 'default';
        const resp = await fetch(`/api/data-prep/me-smart-range?session_id=${sid}`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                center_x: centerX,
                oos_threshold: 1.0,
                n_simulations: 5000,
                target_specs: targetSpecs,
                fixed_factors: [..._meFixedFactors, ..._meBgFactors],
                fixed_values: Object.fromEntries([..._meFixedFactors, ..._meBgFactors].map(f => [f, _meSliderVals[f] ?? (_meColStats[f]?.median ?? 0)])),
            }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || '智慧化區間計算失敗');
        window._meLastSmartRange = data;
        return data;
    };

    // Auto-run Monte Carlo simulation (uses smart range if available, else data percentiles)
    window._meAutoRunSimulate = async function () {
        if (_meSimResults) return _meSimResults;
        if (!_meRenderCtx) throw new Error('請先執行主效應分析');
        const { targetOrder, factorOrder } = _meRenderCtx;
        const allFixed = new Set([..._meFixedFactors, ..._meBgFactors]);
        const freeFactors = factorOrder.filter(f => !allFixed.has(f));

        const paramDists = freeFactors.map(f => {
            const cs = _meColStats[f] || {};
            const ps = _meParamSpecs[f] || {};
            const sr = window._meLastSmartRange?.factors?.[f];
            let mean, std, low, high;
            if (sr) {
                mean = sr.center; std = Math.max(sr.half_width / 3, 1e-9);
                low = sr.lsl; high = sr.usl;
            } else if (ps.usl != null && ps.lsl != null) {
                mean = (ps.usl + ps.lsl) / 2; std = Math.max((ps.usl - ps.lsl) / 6, 1e-9);
                low = ps.lsl; high = ps.usl;
            } else {
                mean = _meSliderVals[f] ?? cs.median ?? 0;
                std  = Math.max(((cs.p95 ?? cs.max ?? mean + 1) - (cs.p5 ?? cs.min ?? mean - 1)) / 6, 1e-9);
                low  = cs.p5  ?? cs.min ?? mean - std * 3;
                high = cs.p95 ?? cs.max ?? mean + std * 3;
            }
            return { factor: f, dist_type: 'normal', mean, std, low, high };
        });

        const targetSpecs = {};
        targetOrder.forEach(t => {
            const ts = _meTargetStats[t] || {};
            targetSpecs[t] = {};
            if (ts.usl != null) targetSpecs[t].usl = ts.usl;
            if (ts.lsl != null) targetSpecs[t].lsl = ts.lsl;
        });

        const sid = typeof getSessionId === 'function' ? getSessionId() : 'default';
        const resp = await fetch(`/api/data-prep/me-simulate?session_id=${sid}`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                param_distributions: paramDists,
                fixed_factors: [...allFixed],
                fixed_values: Object.fromEntries([...allFixed].map(f => [f, _meSliderVals[f] ?? (_meColStats[f]?.median ?? 0)])),
                n_simulations: 1000,
                target_specs: targetSpecs,
            }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || '模擬失敗');
        _meSimResults = { data, targetSpecs };
        return _meSimResults;
    };

    // Draw a simulation funnel chart onto an already-created canvas element (for note export)
    window._meGetShowRealData = function () { return _meShowRealData; };

    // Force real-data scatter + X-spec lines on for grid capture; returns prev state
    window._mePrepareForCapture = function () {
        const prev = { showReal: _meShowRealData, showXSpec: _meSettings.show_x_spec };
        _meShowRealData = true;
        _meSettings.show_x_spec = true;
        if (_meRenderCtx) {
            const { factorOrder, targetOrder, byTarget, targetYRange } = _meRenderCtx;
            targetOrder.forEach((t, ti) => {
                factorOrder.forEach((f, fi) => {
                    const d = byTarget[t]?.[f];
                    if (d) requestAnimationFrame(() => _drawCell(ti, fi, f, t, d, targetYRange[t]));
                });
            });
            factorOrder.forEach((_, fi) => {
                const f = factorOrder[fi];
                requestAnimationFrame(() => _drawHistCell(fi, f));
            });
        }
        return prev;
    };

    // Restore state after capture
    window._meRestoreAfterCapture = function (prev) {
        if (!prev) return;
        _meShowRealData = prev.showReal;
        _meSettings.show_x_spec = prev.showXSpec;
        if (_meRenderCtx) {
            const { factorOrder, targetOrder, byTarget, targetYRange } = _meRenderCtx;
            targetOrder.forEach((t, ti) => {
                factorOrder.forEach((f, fi) => {
                    const d = byTarget[t]?.[f];
                    if (d) requestAnimationFrame(() => _drawCell(ti, fi, f, t, d, targetYRange[t]));
                });
            });
            factorOrder.forEach((_, fi) => {
                const f = factorOrder[fi];
                requestAnimationFrame(() => _drawHistCell(fi, f));
            });
        }
    };

    window._meDrawSimFunnelToEl = function (canvasEl, target) {
        if (!_meSimResults) return;
        const r = _meSimResults.data?.targets?.[target];
        if (!r?.values?.length) return;
        const specs = _meSimResults.targetSpecs?.[target] || {};
        // Temporarily give the canvas an ID so _drawSimFunnel can find it
        const tmpId = '__me_note_sim_' + Date.now() + '_' + Math.random().toString(36).slice(2);
        canvasEl.id = tmpId;
        document.body.appendChild(canvasEl);
        _drawSimFunnel(tmpId, r.values, specs.usl ?? null, specs.lsl ?? null, r.mean);
        canvasEl.remove();
    };

})(); // end IIFE
