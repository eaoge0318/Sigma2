// ================================================================
// RSM Manager - 響應曲面法三步驟精靈
// Depends on globals from data_preparation.html:
//   currentFileId, allFields, getSessionId(), _mvaFilters,
//   _mvaExcludedIndices, _mvaExcludedCols
// ================================================================

(function () {
    'use strict';

    let _rsmStep = 1;
    let _rsmTarget = '';        // primary target (first in _rsmTargets)
    let _rsmTargets = [];       // all selected targets (multi-target)
    let _rsmSelectedFactors = [];
    let _rsmTrendData = null;
    let _rsmColsPopulated = false;
    let _rsmLastResult = null;
    let _rsmSortState = { key: 'coefficient', dir: 'desc' };
    let _rsmTypeFilter = 'all';
    let _rsmActiveTargetTab = 'combined';  // 'combined' or target name
    let _rsmSmartScores = {};              // col → score from smart filter
    let _rsmCurrentSingleTarget = '';      // target for single-tab row clicks
    let _rsmMultiCharts = [];              // mini charts in combined mode

    // ============ PUBLIC API ============

    // Called by switchTool / switchDataset when RSM panel becomes visible
    window.rsmInit = function () {
        if (typeof allFields !== 'undefined' && allFields.length > 0) {
            _populateColumns();
            // Filter out excluded targets
            if (typeof _clExcludedCols !== 'undefined') {
                _rsmTargets = _rsmTargets.filter(t => {
                    if (_clExcludedCols instanceof Set) return !_clExcludedCols.has(t);
                    if (Array.isArray(_clExcludedCols)) return !_clExcludedCols.includes(t);
                    return true;
                });
                _rsmTarget = _rsmTargets[0] || '';
                _renderTargetTags();
            }
        }
        rsmGotoStep(1);
    };

    window.rsmGotoStep = rsmGotoStep;
    window.rsmRun = rsmRunAnalysis;
    window.rsmResetCols = function () { _rsmColsPopulated = false; };

    // ── Multi-target tag management ──
    window.rsmAddTarget = function () {
        const sel = document.getElementById('rsm-target-select');
        const val = sel ? sel.value : '';
        if (!val) return;
        if (_rsmTargets.includes(val)) { sel.value = ''; return; }
        _rsmTargets.push(val);
        _rsmTarget = _rsmTargets[0];
        _renderTargetTags();
        _loadTrend(_rsmTarget);
        sel.value = '';
        _updateRunBtn();
    };

    function _renderTargetTags() {
        const container = document.getElementById('rsm-target-tags');
        if (!container) return;
        const colors = ['#6366f1','#0ea5e9','#10b981','#f59e0b','#ef4444','#8b5cf6'];
        container.innerHTML = _rsmTargets.map((t, i) => {
            const c = colors[i % colors.length];
            return `<span style="display:inline-flex;align-items:center;gap:4px;background:${c}18;color:${c};border:1.5px solid ${c}44;border-radius:20px;padding:3px 10px 3px 10px;font-size:12px;font-weight:600;">
                ${t}
                <span onclick="rsmRemoveTarget(${i})" style="cursor:pointer;font-size:14px;line-height:1;opacity:0.7;margin-left:2px;">&times;</span>
            </span>`;
        }).join('');
    }

    // Preview trend when user selects from dropdown (before clicking 加入)
    window._rsmPreviewTarget = function (col) {
        _loadTrend(col);
    };

    window.rsmRemoveTarget = function (idx) {
        _rsmTargets.splice(idx, 1);
        _rsmTarget = _rsmTargets[0] || '';
        _renderTargetTags();
        if (_rsmTarget) _loadTrend(_rsmTarget);
        else { const a = document.getElementById('rsm-trend-area'); if (a) a.innerHTML = ''; }
        _updateRunBtn();
    };

    // ── Smart Filter ──
    window.rsmOpenSmartModal = function () {
        if (_rsmTargets.length === 0) { alert('請先在第一步選擇目標 Y'); return; }
        const modal = document.getElementById('rsm-smart-modal');
        if (!modal) return;
        modal.style.display = 'flex';
        document.getElementById('rsm-smart-status').textContent = '';
        const btn = document.getElementById('rsm-smart-run-btn');
        btn.textContent = '開始智慧分析'; btn.disabled = false;
    };
    window.rsmCloseSmartModal = function () {
        const modal = document.getElementById('rsm-smart-modal');
        if (modal) modal.style.display = 'none';
    };
    window.rsmRunSmartFilter = async function () {
        const algo = (document.querySelector('input[name="rsm-smart-algo"]:checked') || {}).value || 'correlation';
        const statusEl = document.getElementById('rsm-smart-status');
        const btn = document.getElementById('rsm-smart-run-btn');
        statusEl.textContent = '⏳ 分析中...'; statusEl.style.color = '#6366f1';
        btn.disabled = true; btn.textContent = '分析中...';
        try {
            const sid = typeof getSessionId === 'function' ? getSessionId() : 'default';
            const filters = (typeof _activeDataset !== 'undefined' && _activeDataset?.filters) ?
                _activeDataset.filters.map(f => ({ column: f.col, keyword: '==' + String(f.value || ''), exclude_empty: false })) : [];
            const res = await fetch(`/api/data-prep/smart-select?session_id=${sid}`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    file_id: currentFileId,
                    target_columns: _rsmTargets,
                    target_weights: _rsmTargets.map(() => 1),
                    algorithm: algo,
                    filters,
                    exclude_indices: (typeof _clOutlierIndices !== 'undefined') ? _clOutlierIndices : [],
                    exclude_cols: (typeof _clExcludedCols !== 'undefined') ? [..._clExcludedCols] : [],
                }),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail));
            _rsmSmartScores = {};
            (data.results || []).forEach(r => { _rsmSmartScores[r.col] = r.score; });
            _populateAvailableFactors();
            window.rsmCloseSmartModal();
        } catch (e) {
            statusEl.textContent = `❌ ${e.message}`; statusEl.style.color = '#ef4444';
            btn.textContent = '重試'; btn.disabled = false;
        }
    };

    // ============ STEP NAVIGATION ============

    function rsmGotoStep(n) {
        if (n > 1) {
            if (_rsmTargets.length === 0) { alert('請先選擇至少 1 個 Target (Y)'); return; }
        }
        if (n > 2) {
            _syncSelectedFromList();
            if (_rsmSelectedFactors.length < 1) { alert('請選擇至少 1 個 Factor (X)'); return; }
        }

        _rsmStep = n;
        const s1 = document.getElementById('rsm-step1');
        const s2 = document.getElementById('rsm-step2');
        const s3 = document.getElementById('rsm-step3');
        if (!s1) return;
        s1.style.display = n === 1 ? 'flex' : 'none';
        s2.style.display = n === 2 ? 'flex' : 'none';
        s3.style.display = n === 3 ? 'flex' : 'none';

        const stepTitles = [
            '第一步: 🎯 選擇目標變數 (Y)',
            '第二步: 🔧 選擇因子 (X)',
            '第三步: 📊 分析結果'
        ];
        const titleEl = document.getElementById('rsm-content-title');
        if (titleEl) titleEl.textContent = stepTitles[n - 1];

        // Step indicators
        for (let i = 1; i <= 3; i++) {
            const el = document.getElementById('rsm-tab-' + i);
            if (el) {
                el.classList.remove('rsm-step-active', 'rsm-step-done');
                const doneText = el.querySelector('.rsm-step-done-text');
                if (doneText) doneText.textContent = '';
                
                if (i === n) {
                    el.classList.add('rsm-step-active');
                } else if (i < n) {
                    el.classList.add('rsm-step-done');
                    if (doneText) doneText.textContent = ' (完成)';
                }
            }
        }

        // Run Button
        const runBtn = document.getElementById('rsm-sidebar-run-btn');
        if (runBtn) {
            const canRun = _rsmTargets.length > 0 && _rsmSelectedFactors.length > 0;
            if (canRun) {
                runBtn.style.background = '#2563eb';
                runBtn.style.color = '#fff';
                runBtn.style.cursor = 'pointer';
                runBtn.disabled = false;
            } else {
                runBtn.style.background = '#e2e8f0';
                runBtn.style.color = '#64748b';
                runBtn.style.cursor = 'not-allowed';
                runBtn.disabled = true;
            }
        }

        // Nav buttons
        const prevBtn = document.getElementById('rsm-prev-btn');
        const nextBtn = document.getElementById('rsm-next-btn');
        if (prevBtn) prevBtn.style.display = n > 1 ? '' : 'none';
        if (nextBtn) {
            if (n === 1) { nextBtn.textContent = '下一步 ▶'; nextBtn.style.display = ''; }
            else if (n === 2) { nextBtn.textContent = '下一步 ▶'; nextBtn.style.display = ''; }
            else { nextBtn.style.display = 'none'; }
        }

        // If entering step 2, populate available list
        if (n === 2) _populateAvailableFactors();
        // If entering step 3
        if (n === 3) {
            const area = document.getElementById('rsm-result-area');
            if (area && !area.querySelector('table')) {
                area.innerHTML = `<div style="text-align:center;padding:40px;color:#94a3b8;">
                    <div style="font-size:28px;margin-bottom:8px;">📊</div>
                    <div>目標變數: <b style="color:#1e293b;">${_rsmTarget}</b></div>
                    <div style="margin-top:4px;">已選因子: <b style="color:#1e293b;">${_rsmSelectedFactors.length} 個</b></div>
                    <button onclick="rsmRun()" style="margin-top:16px;padding:10px 24px;background:#2563eb;color:#fff;border:none;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer;box-shadow:0 2px 4px rgba(37,99,235,0.2);">▶ 建立模型並分析</button>
                    <div id="rsm-status" style="margin-top:8px;font-size:13px;color:#94a3b8;"></div>
                </div>`;
            }
        }
    }

    window.rsmPrev = function () {
        if (_rsmStep > 1) rsmGotoStep(_rsmStep - 1);
    };

    window.rsmNext = function () {
        if (_rsmStep === 1) {
            if (_rsmTargets.length === 0) { alert('請選擇至少 1 個 Target (Y)'); return; }
            rsmGotoStep(2);
        } else if (_rsmStep === 2) {
            _syncSelectedFromList();
            if (_rsmSelectedFactors.length < 1) { alert('請選擇至少 1 個 Factor (X)'); return; }
            const overlap = _rsmSelectedFactors.filter(f => _rsmTargets.includes(f));
            if (overlap.length > 0) { alert(`Factor 不能與 Target 重複：${overlap.join(', ')}`); return; }
            rsmGotoStep(3);
        }
    };

    function _updateRunBtn() {
        const btn = document.getElementById('rsm-sidebar-run-btn');
        if (!btn) return;
        const can = _rsmTargets.length > 0 && _rsmSelectedFactors.length > 0;
        btn.disabled = !can;
        btn.style.background = can ? '#2563eb' : '#e2e8f0';
        btn.style.color = can ? '#fff' : '#64748b';
        btn.style.cursor = can ? 'pointer' : 'not-allowed';
    }

    // ============ STEP 1: TARGET + TREND ============

    function _populateColumns() {
        const numFields = allFields.filter(f =>
            f.dtype === 'number' || f.dtype === 'float64' || f.dtype === 'int64' || f.dtype === 'float' || f.dtype === 'int'
        );
        let cols = numFields.length > 0 ? numFields : allFields;
        
        // Filter out excluded columns from Data Cleaning
        if (typeof _clExcludedCols !== 'undefined' && (_clExcludedCols.size > 0 || _clExcludedCols.length > 0)) {
            cols = cols.filter(f => {
                if (_clExcludedCols instanceof Set) return !_clExcludedCols.has(f.name);
                if (Array.isArray(_clExcludedCols)) return !_clExcludedCols.includes(f.name);
                return true;
            });
        }

        const sel = document.getElementById('rsm-target-select');
        if (!sel) return;
        const colNames = cols.map(c => c.name);
        sel.innerHTML = '<option value="">— 選擇 Target —</option>';
        colNames.forEach(n => sel.add(new Option(n, n)));

        // Also populate the available factors pool
        _rsmAllCols = colNames;
        _rsmColsPopulated = true;

        // Remove invalid targets from _rsmTargets
        _rsmTargets = _rsmTargets.filter(t => colNames.includes(t));
        _rsmTarget = _rsmTargets[0] || '';
        _renderTargetTags();

        if (_rsmTarget) _loadTrend(_rsmTarget);
        else { const a = document.getElementById('rsm-trend-area'); if (a) a.innerHTML = ''; }
    }

    let _rsmAllCols = [];

    async function _loadTrend(col) {
        const chartArea = document.getElementById('rsm-trend-area');
        if (!chartArea) return;
        chartArea.innerHTML = '<div style="padding:20px;text-align:center;color:#94a3b8;">⏳ 載入趨勢...</div>';

        try {
            const sid = typeof getSessionId === 'function' ? getSessionId() : 'default';
            // Package active filters
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

            _rsmTrendData = data;
            _drawTrend(chartArea, data, col);
        } catch (e) {
            chartArea.innerHTML = `<div style="padding:20px;text-align:center;color:#ef4444;">❌ ${e.message}</div>`;
        }
    }

    function _drawTrend(container, data, col) {
        const vals = data.values || [];
        const n = vals.length;

        // Stats
        const nums = vals.filter(v => v != null);
        const mean = nums.reduce((a, b) => a + b, 0) / nums.length;
        const std = Math.sqrt(nums.reduce((a, b) => a + (b - mean) ** 2, 0) / nums.length);
        const min = Math.min(...nums);
        const max = Math.max(...nums);

        // Calculate Specs (3 sigma)
        const usl = mean + 3 * std;
        const lsl = mean - 3 * std;
        const target = mean;

        container.innerHTML = `
            <div style="position:absolute;top:0;left:0;right:0;bottom:0;">
                <canvas id="rsm-trend-canvas" style="width:100%;height:100%;display:block;"></canvas>
            </div>`;

        const canvas = document.getElementById('rsm-trend-canvas');
        if (!canvas) return;
        const rect = canvas.parentElement.getBoundingClientRect();
        canvas.width = rect.width;
        // Fix for height cutoff: ensure height doesn't exceed container, and reduce bottom padding
        canvas.height = rect.height;
        const ctx = canvas.getContext('2d');
        const w = canvas.width, h = canvas.height;
        const pad = { t: 20, r: 40, b: 35, l: 30 };
        const cw = w - pad.l - pad.r, ch = h - pad.t - pad.b;

        let vMin = Math.min(min, lsl);
        let vMax = Math.max(max, usl);
        const range = vMax - vMin || 1;
        vMin -= range * 0.1; vMax += range * 0.1;
        const totalRange = vMax - vMin;
        const sx = i => pad.l + (i / (n - 1 || 1)) * cw;
        const sy = v => pad.t + ch - ((v - vMin) / totalRange) * ch;

        // Grid
        ctx.strokeStyle = '#f1f5f9'; ctx.lineWidth = 1;
        for (let i = 0; i <= 5; i++) {
            const y = pad.t + (ch / 5) * i;
            ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(pad.l + cw, y); ctx.stroke();
        }
        
        ctx.fillStyle = '#94a3b8'; ctx.font = '10px Arial'; ctx.textAlign = 'right'; ctx.textBaseline='middle';
        for (let i = 0; i <= 5; i++) {
            const v = vMax - (totalRange / 5) * i;
            ctx.fillText(v.toFixed(2), pad.l - 8, pad.t + (ch / 5) * i);
        }

        // X axis labels
        ctx.textAlign = 'center'; ctx.textBaseline='top';
        [0, Math.floor(n/4), Math.floor(n/2), Math.floor(n*3/4), n-1].forEach(i => {
            if (i >= 0 && i < n) {
                // Ensure text is printed above the absolute bottom to prevent cropping
                ctx.fillText(i, sx(i), pad.t + ch + 5);
            }
        });

        // Scatter Dots
        ctx.fillStyle = '#60a5fa';
        ctx.strokeStyle = '#2563eb';
        ctx.lineWidth = 0.5;
        vals.forEach((v, i) => {
            if (v == null) return;
            ctx.beginPath();
            ctx.arc(sx(i), sy(v), 3.5, 0, Math.PI * 2);
            ctx.fill();
            ctx.stroke();
        });
    }

    // ============ STEP 2: DUAL-LIST FACTOR PICKER ============

    function _populateAvailableFactors() {
        const availList = document.getElementById('rsm-avail-list');
        const selList = document.getElementById('rsm-sel-list');
        if (!availList || !selList) return;

        // Exclude all targets from factors
        _rsmSelectedFactors = _rsmSelectedFactors.filter(f => !_rsmTargets.includes(f));

        const excluded = new Set([..._rsmTargets, ..._rsmSelectedFactors]);
        let available = _rsmAllCols.filter(c => !excluded.has(c));

        // Sort available by smart score if present
        if (Object.keys(_rsmSmartScores).length > 0) {
            available = available.slice().sort((a, b) => (_rsmSmartScores[b] || 0) - (_rsmSmartScores[a] || 0));
        }

        _renderList(availList, available, true);
        _renderList(selList, _rsmSelectedFactors, false);
        _updateSelCount();
        _updateRunBtn();
    }

    function _renderList(ul, items, showScore) {
        ul.innerHTML = '';
        const scores = showScore ? _rsmSmartScores : {};
        const maxScore = Math.max(...Object.values(scores).filter(v => v > 0), 1e-9);
        items.forEach(name => {
            const score = showScore && scores[name] != null ? scores[name] : null;
            const li = document.createElement('div');
            li.className = 'list-item rsm-pick-item';
            li.draggable = true;
            li.ondragstart = (e) => { e.dataTransfer.setData('text/plain', name); };
            if (score != null) {
                const barPct = Math.min((score / maxScore) * 100, 100).toFixed(1);
                li.style.display = 'flex';
                li.style.alignItems = 'center';
                li.style.gap = '6px';
                li.innerHTML = `
                    <div style="flex:1;min-width:0;">
                        <div style="font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${name}</div>
                        <div style="height:3px;background:#e2e8f0;border-radius:2px;margin-top:3px;">
                            <div style="height:100%;width:${barPct}%;background:#7c3aed;border-radius:2px;"></div>
                        </div>
                    </div>
                    <span style="font-size:11px;color:#6d28d9;font-weight:600;flex-shrink:0;min-width:36px;text-align:right;">${score.toFixed(3)}</span>`;
            } else {
                li.textContent = name;
            }
            li.dataset.col = name;
            li.ondblclick = () => {
                if (ul.id === 'rsm-avail-list') _moveToSelected([name]);
                else _moveToAvailable([name]);
            };
            ul.appendChild(li);
        });
    }

    function _getSelected(listEl) {
        return Array.from(listEl.querySelectorAll('.rsm-pick-item.selected')).map(el => el.dataset.col);
    }

    // Click handler with shift/ctrl
    function _onListClick(e, listEl) {
        const item = e.target.closest('.rsm-pick-item');
        if (!item) return;
        if (e.shiftKey && listEl._lastClicked) {
            // Range select
            const items = Array.from(listEl.querySelectorAll('.rsm-pick-item'));
            const from = items.indexOf(listEl._lastClicked);
            const to = items.indexOf(item);
            const [start, end] = from < to ? [from, to] : [to, from];
            items.forEach((el, i) => {
                if (i >= start && i <= end) el.classList.add('selected');
            });
        } else if (e.ctrlKey || e.metaKey) {
            item.classList.toggle('selected');
        } else {
            listEl.querySelectorAll('.rsm-pick-item.selected').forEach(el => el.classList.remove('selected'));
            item.classList.add('selected');
        }
        listEl._lastClicked = item;
        _loadControlPreview(item.dataset.col);
    }

    async function _loadControlPreview(col) {
        const canvas = document.getElementById('rsm-control-preview-chart');
        if (!canvas) return;
        
        try {
            const sid = typeof getSessionId === 'function' ? getSessionId() : 'default';
            // Need currentFileId which is globally available in the dashboard
            const fileId = typeof currentFileId !== 'undefined' ? currentFileId : 'default';
            const filters = (typeof _activeDataset !== 'undefined' && _activeDataset?.filters) ? 
                _activeDataset.filters.map(f => ({
                    column: f.col, keyword: '==' + String(f.value || ''), exclude_empty: false
                })) : [];
            const excludeIndices = (typeof _clOutlierIndices !== 'undefined') ? _clOutlierIndices : [];
            const excludeCols = (typeof _clExcludedCols !== 'undefined') ? _clExcludedCols : [];
            
            const res = await fetch(`/api/data-prep/gb-column-values?file_id=${fileId}&column=${encodeURIComponent(col)}&session_id=${sid}&filters=${encodeURIComponent(JSON.stringify(filters))}&exclude_indices=${encodeURIComponent(JSON.stringify(excludeIndices))}&exclude_cols=${encodeURIComponent(JSON.stringify(excludeCols))}`);
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Failed');
            
            const wrapper = canvas.parentElement;
            _drawPreviewScatterChart(wrapper, data, col, canvas);
        } catch (e) {
            console.error('Failed to load control preview:', e);
        }
    }

    function _drawPreviewScatterChart(wrapper, data, col, canvas) {
        const vals = data.values || [];
        const n = vals.length;
        if (n === 0) return;

        const nums = vals.filter(v => v != null);
        if (nums.length === 0) return;

        const min = Math.min(...nums);
        const max = Math.max(...nums);
        const range = max - min || 1;
        
        const rect = wrapper.getBoundingClientRect();
        canvas.width = rect.width;
        canvas.height = Math.max(rect.height, 200); // ensure min height
        const ctx = canvas.getContext('2d');
        const w = canvas.width, h = canvas.height;
        const pad = { t: 20, r: 40, b: 35, l: 30 };
        const cw = w - pad.l - pad.r, ch = h - pad.t - pad.b;

        const vMin = min - range * 0.1; 
        const vMax = max + range * 0.1;
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
        
        ctx.fillStyle = '#94a3b8'; ctx.font = '10px Arial'; ctx.textAlign = 'right'; ctx.textBaseline='middle';
        for (let i = 0; i <= 5; i++) {
            const v = vMax - (totalRange / 5) * i;
            ctx.fillText(v.toFixed(2), pad.l - 8, pad.t + (ch / 5) * i);
        }

        // X labels
        ctx.textAlign = 'center'; ctx.textBaseline='top';
        [0, Math.floor(n/4), Math.floor(n/2), Math.floor(n*3/4), n-1].forEach(i => {
            if (i >= 0 && i < n) ctx.fillText(i, sx(i), pad.t + ch + 5);
        });

        // Scatter Dots
        ctx.fillStyle = '#60a5fa'; ctx.strokeStyle = '#2563eb'; ctx.lineWidth = 0.5;
        vals.forEach((v, i) => {
            if (v == null) return;
            ctx.beginPath();
            ctx.arc(sx(i), sy(v), 3.5, 0, Math.PI * 2);
            ctx.fill(); ctx.stroke();
        });
    }

    window.rsmAvailClick = function (e) { _onListClick(e, document.getElementById('rsm-avail-list')); };
    window.rsmSelClick = function (e) { _onListClick(e, document.getElementById('rsm-sel-list')); };

    window.rsmListKeyDown = function(e, listEl) {
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault();
            const items = Array.from(listEl.querySelectorAll('.rsm-pick-item'));
            if (items.length === 0) return;
            
            const currentSelected = listEl.querySelector('.rsm-pick-item.selected');
            let idx = items.indexOf(currentSelected);
            
            if (e.key === 'ArrowDown') {
                idx = (idx < items.length - 1) ? idx + 1 : idx;
            } else {
                idx = (idx > 0) ? idx - 1 : 0;
            }
            // if no selection yet, start from top on arrowDown, bottom on arrowUp
            if (currentSelected == null) {
                idx = e.key === 'ArrowDown' ? 0 : items.length - 1;
            }
            
            const target = items[idx];
            if (target) {
                items.forEach(el => el.classList.remove('selected'));
                target.classList.add('selected');
                listEl._lastClicked = target;
                target.scrollIntoView({ block: 'nearest' });
                _loadControlPreview(target.dataset.col);
            }
        }
    };

    window.rsmHandleDrop = function (e, listId) {
        e.preventDefault();
        const col = e.dataTransfer.getData('text/plain');
        if (!col) return;
        if (listId === 'rsm-avail-list') {
            _moveToAvailable([col]);
        } else if (listId === 'rsm-sel-list') {
            _moveToSelected([col]);
        }
    };

    window.rsmMoveRight = function () {
        const sel = _getSelected(document.getElementById('rsm-avail-list'));
        if (sel.length > 0) _moveToSelected(sel);
    };

    window.rsmMoveLeft = function () {
        const sel = _getSelected(document.getElementById('rsm-sel-list'));
        if (sel.length > 0) _moveToAvailable(sel);
    };

    window.rsmMoveAllRight = function () {
        const all = Array.from(document.getElementById('rsm-avail-list').querySelectorAll('.rsm-pick-item')).map(el => el.dataset.col);
        if (all.length > 0) _moveToSelected(all);
    };

    window.rsmMoveAllLeft = function () {
        _rsmSelectedFactors = [];
        _populateAvailableFactors();
    };

    function _moveToSelected(names) {
        names.forEach(n => { if (!_rsmSelectedFactors.includes(n)) _rsmSelectedFactors.push(n); });
        _populateAvailableFactors();
    }

    function _moveToAvailable(names) {
        _rsmSelectedFactors = _rsmSelectedFactors.filter(f => !names.includes(f));
        _populateAvailableFactors();
    }

    function _syncSelectedFromList() {
        // ensure _rsmSelectedFactors reflects what's in the selected list
        const selList = document.getElementById('rsm-sel-list');
        if (selList) {
            _rsmSelectedFactors = Array.from(selList.querySelectorAll('.rsm-pick-item')).map(el => el.dataset.col);
        }
    }

    function _updateSelCount() {
        const el = document.getElementById('rsm-sel-count');
        if (el) el.textContent = `(${_rsmSelectedFactors.length})`;
    }

    // Search filter
    window.rsmFilterAvail = function (val) {
        const list = document.getElementById('rsm-avail-list');
        if (!list) return;
        const kw = val.toLowerCase();
        list.querySelectorAll('.rsm-pick-item').forEach(el => {
            el.style.display = el.dataset.col.toLowerCase().includes(kw) ? '' : 'none';
        });
    };

    window.rsmFilterSel = function (val) {
        const list = document.getElementById('rsm-sel-list');
        if (!list) return;
        const kw = val.toLowerCase();
        list.querySelectorAll('.rsm-pick-item').forEach(el => {
            el.style.display = el.dataset.col.toLowerCase().includes(kw) ? '' : 'none';
        });
    };

    // ============ STEP 3: ANALYSIS ============

    async function rsmRunAnalysis() {
        if (_rsmTargets.length === 0) { alert('請先選擇 Target'); rsmGotoStep(1); return; }
        _syncSelectedFromList();
        if (_rsmSelectedFactors.length < 1) { alert('請先選擇 Factors'); rsmGotoStep(2); return; }

        rsmGotoStep(3);

        const resultArea = document.getElementById('rsm-result-area');
        const runBtn = document.getElementById('rsm-sidebar-run-btn');
        const targetsLabel = _rsmTargets.join(' / ');
        if (resultArea) {
            resultArea.innerHTML = `
                <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;gap:20px;">
                    <div style="font-size:40px;">🧪</div>
                    <div style="text-align:center;">
                        <div style="color:#3b82f6;font-size:16px;font-weight:700;margin-bottom:4px;">正在進行多項式展開相關分析...</div>
                        <div style="color:#94a3b8;font-size:12px;">目標: ${targetsLabel} | 因子: ${_rsmSelectedFactors.length} 個</div>
                    </div>
                    
                    <div style="width:300px;height:12px;background:#f1f5f9;border-radius:6px;overflow:hidden;border:1px solid #e2e8f0;position:relative;">
                        <div id="rsm-progress-inner" style="width:0%;height:100%;background:linear-gradient(90deg, #3b82f6, #6366f1);transition:width 0.3s ease;"></div>
                    </div>
                    <div id="rsm-progress-text" style="color:#64748b;font-size:11px;font-weight:500;">準備數據中... 0%</div>
                </div>`;
        }
        if (runBtn) { runBtn.disabled = true; runBtn.textContent = '⏳ 分析中...'; }

        // Start progress simulation
        let progress = 0;
        const progressInner = document.getElementById('rsm-progress-inner');
        const progressText = document.getElementById('rsm-progress-text');
        const progressInterval = setInterval(() => {
            if (progress < 95) {
                const inc = progress < 30 ? 5 : (progress < 70 ? 2 : 0.5);
                progress += inc;
                if (progressInner) progressInner.style.width = `${progress}%`;
                if (progressText) {
                    let msg = '建模中...';
                    if (progress < 20) msg = '準備數據中...';
                    else if (progress < 50) msg = '計算二階效應項...';
                    else if (progress < 80) msg = '計算相關係數...';
                    else msg = '優化特徵權重中...';
                    progressText.textContent = `${msg} ${Math.floor(progress)}%`;
                }
            }
        }, 300);

        try {
            const sid = typeof getSessionId === 'function' ? getSessionId() : 'default';
            const body = {
                file_id: currentFileId,
                targets: _rsmTargets,      // multi-target
                target: _rsmTargets[0] || '',  // backwards compat
                factors: _rsmSelectedFactors,
                filters: (typeof _activeDataset !== 'undefined' && _activeDataset?.filters) ?
                    _activeDataset.filters.map(f => ({
                        column: f.col, keyword: '==' + String(f.value || ''), exclude_empty: false
                    })) : [],
                exclude_indices: (typeof _clOutlierIndices !== 'undefined') ? _clOutlierIndices : [],
                exclude_cols: (typeof _clExcludedCols !== 'undefined') ? [..._clExcludedCols] : [],
            };
            const res = await fetch(`/api/data-prep/rsm-analysis?session_id=${sid}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const data = await res.json();
            if (!res.ok) {
                const msg = typeof data.detail === 'object' ? JSON.stringify(data.detail) : (data.detail || '分析失敗');
                throw new Error(msg);
            }

            _renderResults(data, resultArea);
        } catch (err) {
            let errorMsg = err.message;
            if (errorMsg.includes('[object Object]')) {
                errorMsg = 'API 資料格式錯誤或共線性過高';
            }
            if (resultArea) {
                resultArea.innerHTML = `<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;gap:12px;">
                    <div style="font-size:32px;">❌</div>
                    <div style="color:#ef4444;font-size:14px;font-weight:600;">分析失敗</div>
                    <div style="color:#64748b;font-size:12px;max-width:400px;text-align:center;word-break:break-all;">${errorMsg}</div>
                </div>`;
            }
        } finally {
            clearInterval(progressInterval);
            if (progressInner) progressInner.style.width = '100%';
            if (runBtn) { runBtn.disabled = false; runBtn.textContent = '分析'; }
        }
    }

    function _renderResults(data, container) {
        _rsmLastResult = data;
        window._rsmLastResult = data;  // expose for nbSaveRsmNote in HTML
        // Destroy any existing multi charts
        _rsmMultiCharts.forEach(c => { try { c.destroy(); } catch(e) {} });
        _rsmMultiCharts = [];
        if (_rsmLastChart) { try { _rsmLastChart.destroy(); } catch(e) {} _rsmLastChart = null; }

        if (data.multi_target && data.targets && data.targets.length > 1) {
            _renderMultiTargetResults(data, container);
        } else {
            _renderSingleTargetResults(data, container);
        }
    }

    // ── Single-target layout (unchanged behaviour) ──
    function _renderSingleTargetResults(data, container) {
        _rsmCurrentSingleTarget = data.target || _rsmTargets[0] || _rsmTarget;
        window._rsmCurrentTarget = _rsmCurrentSingleTarget;
        _rsmActiveTargetTab = 'single';
        container.style.cssText = 'height:100%;display:flex;flex-direction:column;';
        container.innerHTML = `
            <div id="rsm-result-layout" style="display:grid;grid-template-columns:1fr 1fr;gap:20px;flex:1;min-height:0;align-items:stretch;">
                <div id="rsm-result-left-panel" style="overflow-y:auto;">
                    <div id="rsm-table-container"></div>
                    <div id="rsm-extra-sections" style="margin-top:20px;"></div>
                </div>
                ${_rightPanelHTML()}
            </div>`;
        _renderResultsTable();
    }

    // ── Multi-target layout ──
    function _renderMultiTargetResults(data, container) {
        _rsmActiveTargetTab = 'combined';
        // Set current target to first target so _rsmRowClick / nbSaveRsmNote have a fallback
        _rsmCurrentSingleTarget = (data.targets && data.targets[0]) || '';
        window._rsmCurrentTarget = _rsmCurrentSingleTarget;

        container.style.cssText = 'height:100%;display:flex;flex-direction:column;';
        container.innerHTML = `
            <div id="rsm-result-layout" style="display:grid;grid-template-columns:1fr 1fr;gap:20px;flex:1;min-height:0;align-items:stretch;">
                <div id="rsm-result-left-panel" style="overflow-y:auto;">
                    <div id="rsm-table-container"></div>
                </div>
                <div id="rsm-result-right-panel" style="background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:16px;display:flex;flex-direction:column;overflow:hidden;min-height:400px;">
                    <div style="font-size:13px;font-weight:700;color:#1e293b;margin-bottom:10px;display:flex;align-items:center;gap:6px;flex-shrink:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
                        📈 <span id="rsm-plot-title" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0;">點擊左側項目查看散佈圖</span>
                    </div>
                    <div id="rsm-multi-scatter" style="flex:1;min-height:0;overflow-y:auto;display:flex;flex-direction:column;align-items:center;justify-content:center;color:#94a3b8;font-size:12px;background:#f8fafc;border-radius:8px;padding:12px;">
                        請從左表選擇一項來查看各目標散佈圖
                    </div>
                </div>
            </div>`;

        if (!document.getElementById('rsm-table-style')) {
            const style = document.createElement('style');
            style.id = 'rsm-table-style';
            style.textContent = `
                .rsm-table-row:hover { background-color: #eff6ff !important; }
                .rsm-table-row.active { background-color: #dbeafe !important; box-shadow: inset 2px 0 0 #2563eb; }
            `;
            document.head.appendChild(style);
        }

        _renderCombinedTab(data);
    }

    // ── Tab switcher ──
    window._rsmSwitchTab = function(tab) {
        _rsmActiveTargetTab = tab;
        const data = _rsmLastResult;

        // Update button styles
        const tabColors = ['#6366f1','#0ea5e9','#10b981','#f59e0b','#ef4444','#8b5cf6'];
        document.querySelectorAll('.rsm-tab-btn').forEach(btn => {
            const isActive = btn.dataset.tab === tab;
            if (isActive) {
                if (tab === 'combined') {
                    btn.style.background = '#3b82f6';
                } else {
                    const idx = data.targets.indexOf(tab);
                    btn.style.background = tabColors[idx % tabColors.length];
                }
                btn.style.color = '#fff';
            } else {
                btn.style.background = '#f8fafc';
                btn.style.color = '#64748b';
            }
        });

        // Reset right panel
        const singleScatter = document.getElementById('rsm-single-scatter');
        const multiScatter = document.getElementById('rsm-multi-scatter');
        const plotTitle = document.getElementById('rsm-plot-title');
        if (plotTitle) plotTitle.textContent = '點擊左側項目查看散佈圖';

        if (tab === 'combined') {
            if (singleScatter) singleScatter.style.display = 'none';
            if (multiScatter) {
                multiScatter.style.display = 'flex';
                multiScatter.innerHTML = '<span style="color:#94a3b8;font-size:12px;">請從左表選擇一項來查看各目標散佈圖</span>';
            }
            _renderCombinedTab(data);
        } else {
            if (singleScatter) { singleScatter.style.display = 'block'; }
            if (multiScatter) multiScatter.style.display = 'none';
            // Reset single scatter placeholder
            const placeholder = document.getElementById('rsm-plot-placeholder');
            if (placeholder) { placeholder.style.display = 'flex'; placeholder.textContent = '請從左表選擇一項分析因子或交互作用項'; }
            _renderPerTargetTableForTab(tab, data);
        }
    };

    // ── Combined heatmap table ──
    function _renderCombinedTab(data) {
        const container = document.getElementById('rsm-table-container');
        if (!container) return;
        const terms = data.combined_terms || [];
        const targets = data.targets || [];
        // Expose for nbSaveRsmNote (combined mode: adapt to per-target format using first target's corr)
        window._rsmDisplayedTerms = terms.map(t => ({
            name: t.name, type: t.type,
            coefficient: (t.scores && t.scores[targets[0]] !== undefined) ? t.scores[targets[0]] : 0,
            correlation: (t.scores && t.scores[targets[0]] !== undefined) ? t.scores[targets[0]] : 0,
        }));

        let maxAbs = 0.01;
        terms.forEach(t => Object.values(t.scores || {}).forEach(s => { if (Math.abs(s) > maxAbs) maxAbs = Math.abs(s); }));

        const typeIcons = { main: '📌', interaction: '🔗', quadratic: '📐', cubic: '🧊' };
        const tabColors = ['#6366f1','#0ea5e9','#10b981','#f59e0b','#ef4444','#8b5cf6'];

        // Apply type filter
        let filteredTerms = terms;
        if (_rsmTypeFilter !== 'all') {
            filteredTerms = terms.filter(t => t.type === _rsmTypeFilter);
        }

        // Apply sort
        const sk = _rsmSortState.key;
        if (sk.startsWith('combined_')) {
            const ti = parseInt(sk.replace('combined_', ''), 10);
            const tCol = targets[ti];
            if (tCol !== undefined) {
                filteredTerms = [...filteredTerms].sort((a, b) => {
                    const va = Math.abs((a.scores && a.scores[tCol]) ?? 0);
                    const vb = Math.abs((b.scores && b.scores[tCol]) ?? 0);
                    return _rsmSortState.dir === 'desc' ? vb - va : va - vb;
                });
            }
        }
        // default order (max abs) is already in terms array from backend

        const sortIcon = (key) => _rsmSortState.key !== key ? '<span style="opacity:0.3;font-size:10px;">↕</span>' : (_rsmSortState.dir === 'desc' ? '⬇' : '⬆');

        let html = `<div style="border:1px solid #e2e8f0;border-radius:10px;overflow:hidden;background:#fff;">`;
        html += `<table style="width:100%;border-collapse:collapse;font-size:12px;">`;

        // Header
        html += `<thead><tr style="background:#f8fafc;color:#64748b;border-bottom:1px solid #e2e8f0;">
            <th style="padding:8px 6px;text-align:center;width:26px;font-weight:600;">#</th>
            <th style="padding:8px 10px;text-align:left;font-weight:600;">項名稱</th>
            <th style="padding:8px 6px;text-align:center;width:80px;">
                <select id="rsm-type-filter-select" onchange="window._rsmChangeTypeFilter(this.value)" style="border:1px solid #cbd5e1;border-radius:4px;font-size:11px;padding:2px 4px;background:#fff;outline:none;cursor:pointer;">
                    <option value="all" ${_rsmTypeFilter==='all'?'selected':''}>類型(全)</option>
                    <option value="main" ${_rsmTypeFilter==='main'?'selected':''}>主效應</option>
                    <option value="interaction" ${_rsmTypeFilter==='interaction'?'selected':''}>交互</option>
                    <option value="quadratic" ${_rsmTypeFilter==='quadratic'?'selected':''}>二階</option>
                    <option value="cubic" ${_rsmTypeFilter==='cubic'?'selected':''}>三階</option>
                </select>
            </th>
            ${targets.map((t, i) => {
                const c = tabColors[i % tabColors.length];
                const short = t.length > 9 ? t.substring(0, 8) + '…' : t;
                const isActive = _rsmSortState.key === `combined_${i}`;
                return `<th onclick="window._rsmToggleSort('combined_${i}')" style="padding:8px 6px;text-align:center;min-width:80px;color:${c};font-weight:700;cursor:pointer;user-select:none;${isActive ? 'background:#f0f9ff;' : ''}" title="${t}（點擊排序）">
                    <div style="display:flex;align-items:center;justify-content:center;gap:3px;">${short} ${sortIcon('combined_'+i)}</div>
                </th>`;
            }).join('')}
        </tr></thead><tbody id="rsm-table-tbody">`;

        if (filteredTerms.length === 0) {
            html += `<tr><td colspan="${3 + targets.length}" style="text-align:center;padding:24px;color:#94a3b8;">無符合條件的項目</td></tr>`;
        }

        filteredTerms.forEach((term, idx) => {
            html += `<tr onclick='window._rsmMultiRowClick(this, ${JSON.stringify(term).replace(/'/g, "&apos;")})'
                class="rsm-table-row" tabindex="0"
                style="border-bottom:1px solid #f1f5f9;cursor:pointer;transition:background 0.15s;">
                <td style="padding:7px 6px;text-align:center;color:#94a3b8;font-size:10px;">${idx + 1}</td>
                <td style="padding:7px 10px;color:#1e293b;font-weight:500;" title="${term.name}">${_truncateName(term.name, 20).replace(/²/g, '<span style="color:#f97316;font-weight:700;">²</span>').replace(/³/g, '<span style="color:#a855f7;font-weight:700;">³</span>')}</td>
                <td style="padding:7px 6px;text-align:center;font-size:13px;">${typeIcons[term.type] || ''}</td>
                ${targets.map((t, ti) => {
                    const score = (term.scores && term.scores[t] !== undefined) ? term.scores[t] : 0;
                    const pct = Math.min(Math.abs(score) / maxAbs * 100, 100);
                    const c = tabColors[ti % tabColors.length];
                    const bg = score >= 0
                        ? `linear-gradient(to right, transparent ${100 - pct}%, ${c}28 ${100 - pct}%)`
                        : `linear-gradient(to left, transparent ${100 - pct}%, ${c}28 ${100 - pct}%)`;
                    const bold = Math.abs(score) > 0.3 ? 700 : 400;
                    const textColor = Math.abs(score) > 0.3 ? c : '#94a3b8';
                    return `<td style="padding:7px 6px;text-align:center;background:${bg};">
                        <span style="font-family:monospace;font-size:11px;font-weight:${bold};color:${textColor};">${score >= 0 ? '+' : ''}${score.toFixed(3)}</span>
                    </td>`;
                }).join('')}
            </tr>`;
        });

        html += `</tbody></table></div>
        <div style="margin-top:6px;font-size:11px;color:#94a3b8;text-align:right;padding-right:4px;">
            顯示 ${filteredTerms.length} / ${terms.length} 項 · 點擊列查看各目標散佈圖
        </div>`;
        // Expose for CSV/note save
        window._rsmDisplayedTerms = filteredTerms.map(t => ({
            name: t.name, type: t.type,
            coefficient: (t.scores && t.scores[targets[0]] !== undefined) ? t.scores[targets[0]] : 0,
            correlation: (t.scores && t.scores[targets[0]] !== undefined) ? t.scores[targets[0]] : 0,
        }));
        container.innerHTML = html;
        _setupKeyboardNavigation();
    }

    // ── Per-target tab table ──
    function _renderPerTargetTableForTab(target, data) {
        _rsmCurrentSingleTarget = target;
        window._rsmCurrentTarget = target;
        const container = document.getElementById('rsm-table-container');
        if (!container) return;
        const targetData = (data.results || {})[target];
        if (!targetData) {
            container.innerHTML = `<div style="text-align:center;padding:24px;color:#94a3b8;">無 ${target} 的分析結果</div>`;
            return;
        }

        let terms = [...(targetData.surviving_terms || [])];
        if (_rsmTypeFilter !== 'all') {
            terms = terms.filter(t => t.type === _rsmTypeFilter);
        }
        terms.sort((a, b) => {
            let vA = a[_rsmSortState.key] ?? 0, vB = b[_rsmSortState.key] ?? 0;
            if (_rsmSortState.key === 'coefficient' || _rsmSortState.key === 'lasso_coef') { vA = Math.abs(vA); vB = Math.abs(vB); }
            return _rsmSortState.dir === 'desc' ? vB - vA : vA - vB;
        });

        const maxAbsCoef = Math.max(...terms.map(t => Math.abs(t.coefficient || 0)), 0.01);
        const hasLasso = terms.some(t => t.lasso_coef != null);
        const maxAbsLasso = Math.max(...terms.map(t => Math.abs(t.lasso_coef || 0)), 0.0001);
        const typeIcons = { main: '📌', interaction: '🔗', quadratic: '📐', cubic: '🧊' };
        window._rsmDisplayedTerms = terms;

        const sortIcon = (key) => _rsmSortState.key !== key ? '↕️' : (_rsmSortState.dir === 'desc' ? '⬇️' : '⬆️');

        let html = `<div style="font-size:13px;font-weight:700;color:#1e293b;margin-bottom:4px;display:flex;justify-content:space-between;align-items:center;padding:8px 2px 4px;">
            <span>🎯 顯著相關項 (${terms.length})</span>
            <span style="font-size:11px;font-weight:400;color:#94a3b8;">* 點擊列查看散佈圖</span>
        </div>`;
        html += `<div style="border:1px solid #e2e8f0;border-radius:0 0 10px 10px;overflow:hidden;background:#fff;margin-top:-1px;">`;
        html += `<table style="width:100%;border-collapse:collapse;font-size:12px;">`;
        html += `<thead><tr style="background:#f8fafc;color:#64748b;border-bottom:1px solid #e2e8f0;">
            <th style="padding:8px 6px;text-align:center;width:26px;">#</th>
            <th style="padding:8px 10px;text-align:left;">項名稱</th>
            <th style="padding:8px 6px;text-align:center;width:72px;">
                <select id="rsm-type-filter-select" onchange="window._rsmChangeTypeFilter(this.value)" style="border:1px solid #cbd5e1;border-radius:4px;font-size:11px;padding:2px 4px;background:#fff;outline:none;cursor:pointer;">
                    <option value="all" ${_rsmTypeFilter === 'all' ? 'selected' : ''}>類型(全)</option>
                    <option value="main" ${_rsmTypeFilter === 'main' ? 'selected' : ''}>主效應</option>
                    <option value="interaction" ${_rsmTypeFilter === 'interaction' ? 'selected' : ''}>交互</option>
                    <option value="quadratic" ${_rsmTypeFilter === 'quadratic' ? 'selected' : ''}>二階</option>
                    <option value="cubic" ${_rsmTypeFilter === 'cubic' ? 'selected' : ''}>三階</option>
                </select>
            </th>
            <th onclick="window._rsmToggleSort('coefficient')" style="padding:8px 6px;text-align:center;width:110px;cursor:pointer;user-select:none;color:#1e293b;">相關係數 r ${sortIcon('coefficient')}</th>
            <th onclick="window._rsmToggleSort('lasso_coef')" style="padding:8px 6px;text-align:center;width:100px;cursor:pointer;user-select:none;color:#7c3aed;">Lasso β ${sortIcon('lasso_coef')}</th>
        </tr></thead><tbody id="rsm-table-tbody">`;

        if (terms.length === 0) {
            html += `<tr><td colspan="5" style="text-align:center;padding:20px;color:#94a3b8;">沒有符合此類型的顯著項</td></tr>`;
        }

        terms.forEach((t, idx) => {
            const coefPct = Math.min(Math.abs(t.coefficient) / maxAbsCoef * 100, 100);
            const coefColor = t.coefficient >= 0 ? '#3b82f6' : '#f97316';
            const coefBg = t.coefficient >= 0
                ? `linear-gradient(to right, transparent ${100 - coefPct}%, ${coefColor} ${100 - coefPct}%)`
                : `linear-gradient(to left, transparent ${100 - coefPct}%, ${coefColor} ${100 - coefPct}%)`;
            const lcVal = t.lasso_coef != null ? t.lasso_coef : null;
            const lcPct = lcVal != null ? Math.min(Math.abs(lcVal) / maxAbsLasso * 100, 100) : 0;
            const lcColor = lcVal == null ? '#94a3b8' : lcVal > 0 ? '#7c3aed' : lcVal < 0 ? '#db2777' : '#94a3b8';
            const lcBg = lcVal != null && lcVal !== 0
                ? (lcVal > 0
                    ? `linear-gradient(to right, transparent ${100 - lcPct}%, ${lcColor}33 ${100 - lcPct}%)`
                    : `linear-gradient(to left, transparent ${100 - lcPct}%, ${lcColor}33 ${100 - lcPct}%)`)
                : 'none';
            const lcText = lcVal == null ? '—' : lcVal === 0 ? '<span style="color:#cbd5e1;">0</span>' : _fmtSlope(lcVal);
            const icon = typeIcons[t.type] || '';
            const shortName = _truncateName(t.name, 22);
            html += `<tr onclick='window._rsmRowClick(this, ${JSON.stringify(t).replace(/'/g, "&apos;")})' class="rsm-table-row" tabindex="0" style="border-bottom:1px solid #f1f5f9;cursor:pointer;transition:background 0.15s;${lcVal === 0 ? 'opacity:0.65;' : ''}">
                <td style="padding:7px 6px;text-align:center;color:#94a3b8;font-size:10px;">${idx + 1}</td>
                <td style="padding:7px 10px;color:#1e293b;font-weight:500;" title="${t.name}">${shortName.replace(/²/g, '<span style="color:#f97316;font-weight:700;">²</span>').replace(/³/g, '<span style="color:#a855f7;font-weight:700;">³</span>')}</td>
                <td style="padding:7px 6px;font-size:11px;color:#64748b;text-align:center;">${icon}</td>
                <td style="padding:7px 6px;"><div style="display:flex;align-items:center;gap:6px;">
                    <span style="font-family:monospace;font-size:11px;min-width:48px;text-align:right;">${(t.coefficient || 0).toFixed(4)}</span>
                    <div style="flex:1;height:6px;border-radius:3px;background:${coefBg};"></div>
                </div></td>
                <td style="padding:7px 6px;"><div style="display:flex;align-items:center;gap:6px;">
                    <span style="font-family:monospace;font-size:11px;min-width:48px;text-align:right;color:${lcColor};">${lcText}</span>
                    <div style="flex:1;height:6px;border-radius:3px;background:${lcBg};"></div>
                </div></td>
            </tr>`;
        });
        html += `</tbody></table></div>`;

        // R² badge
        if (targetData.r_squared !== undefined) {
            html += `<div style="margin-top:8px;font-size:11px;color:#64748b;text-align:right;padding-right:4px;">R² = <b>${(targetData.r_squared || 0).toFixed(4)}</b></div>`;
        }
        container.innerHTML = html;

        if (!document.getElementById('rsm-table-style')) {
            const style = document.createElement('style');
            style.id = 'rsm-table-style';
            style.textContent = `.rsm-tab-btn:hover{filter:brightness(0.92);}.rsm-table-row:hover{background-color:#eff6ff!important;}.rsm-table-row.active{background-color:#dbeafe!important;box-shadow:inset 2px 0 0 #2563eb;}`;
            document.head.appendChild(style);
        }
        _setupKeyboardNavigation();
    }

    // ── Right panel HTML helper (single-target) ──
    function _rightPanelHTML() {
        return `<div id="rsm-result-right-panel" style="background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:16px;display:flex;flex-direction:column;overflow:hidden;min-height:400px;">
            <div style="font-size:13px;font-weight:700;color:#1e293b;margin-bottom:10px;display:flex;align-items:center;gap:6px;flex-shrink:0;overflow:hidden;">
                📈 <span id="rsm-plot-title" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0;">點擊左側項目查看散佈圖</span>
            </div>
            <div id="rsm-scatter-area" style="flex:1;min-height:0;position:relative;">
                <div id="rsm-single-scatter" style="position:absolute;inset:0;">
                    <canvas id="rsm-scatter-canvas" style="width:100%;height:100%;"></canvas>
                    <div id="rsm-plot-placeholder" style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#94a3b8;font-size:12px;background:#f8fafc;border-radius:8px;">
                        請從左表選擇一項分析因子或交互作用項
                    </div>
                </div>
                <div id="rsm-multi-scatter" style="display:none;"></div>
            </div>
            <div id="rsm-plot-stats" style="margin-top:10px;font-size:11px;color:#64748b;border-top:1px dashed #e2e8f0;padding-top:8px;flex-shrink:0;"></div>
        </div>`;
    }

    // ── Multi-target combined row click ──
    window._rsmMultiRowClick = async function(rowEl, term) {
        document.querySelectorAll('.rsm-table-row').forEach(el => el.classList.remove('active'));
        rowEl.classList.add('active');

        const plotTitle = document.getElementById('rsm-plot-title');
        if (plotTitle) plotTitle.textContent = `${_truncateName(term.name, 28)} — 多目標對比`;

        const multiScatter = document.getElementById('rsm-multi-scatter');
        if (!multiScatter) return;
        multiScatter.style.alignItems = 'center';
        multiScatter.style.justifyContent = 'center';
        multiScatter.innerHTML = '<div style="color:#94a3b8;font-size:12px;">載入中...</div>';

        // Destroy previous mini charts
        _rsmMultiCharts.forEach(c => { try { c.destroy(); } catch(e) {} });
        _rsmMultiCharts = [];

        const data = _rsmLastResult;

        // Parse factors
        let factors = [];
        if (term.type === 'main') factors = [term.name];
        else if (term.type === 'quadratic') factors = [term.name.replace('²', '')];
        else if (term.type === 'interaction') factors = term.name.split(' × ');
        else if (term.type === 'cubic') factors = term.name.replace(/[²³]/g, '').split(' × ');

        const sid = typeof getSessionId === 'function' ? getSessionId() : 'default';
        const baseBody = {
            file_id: currentFileId,
            term_name: term.name,
            factors: factors,
            term_type: term.type,
            filters: (typeof _activeDataset !== 'undefined' && _activeDataset?.filters)
                ? _activeDataset.filters.map(f => ({ column: f.col, keyword: '==' + String(f.value || ''), exclude_empty: false }))
                : [],
            exclude_indices: (typeof _clOutlierIndices !== 'undefined') ? _clOutlierIndices : [],
            exclude_cols: (typeof _clExcludedCols !== 'undefined') ? [..._clExcludedCols] : [],
        };

        // Fetch all targets in parallel
        const results = await Promise.all(data.targets.map(async t => {
            try {
                const res = await fetch(`/api/data-prep/rsm-scatter-data?session_id=${sid}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ...baseBody, target: t }),
                });
                const d = await res.json();
                if (!res.ok) throw new Error(d.detail || '載入失敗');
                return { target: t, d };
            } catch(e) {
                return { target: t, error: e.message };
            }
        }));

        const tabColors = ['#6366f1','#0ea5e9','#10b981','#f59e0b','#ef4444','#8b5cf6'];
        multiScatter.innerHTML = '';
        multiScatter.style.alignItems = 'stretch';
        multiScatter.style.justifyContent = 'flex-start';

        results.forEach(({ target, d, error }, ti) => {
            const color = tabColors[ti % tabColors.length];
            const score = (term.scores && term.scores[target] !== undefined) ? term.scores[target] : null;
            const corrText = score !== null ? (score >= 0 ? '+' : '') + score.toFixed(3) : '—';
            const corrColor = score !== null && Math.abs(score) > 0.3 ? color : '#94a3b8';

            const wrap = document.createElement('div');
            wrap.style.cssText = 'margin-bottom:14px;padding-bottom:14px;border-bottom:1px solid #f1f5f9;';

            const header = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
                <span style="font-size:11px;font-weight:700;color:${color};">▍${target}</span>
                <span style="font-size:11px;font-family:monospace;color:${corrColor};font-weight:600;">r = ${corrText}</span>
            </div>`;

            if (error) {
                wrap.innerHTML = header + `<div style="height:120px;display:flex;align-items:center;justify-content:center;font-size:11px;color:#ef4444;">❌ ${error}</div>`;
                multiScatter.appendChild(wrap);
                return;
            }

            const canvasId = `rsm-mini-${ti}`;
            wrap.innerHTML = header + `<div style="position:relative;height:170px;"><canvas id="${canvasId}"></canvas></div>`;
            multiScatter.appendChild(wrap);

            const canvas = document.getElementById(canvasId);
            if (!canvas || !d.x || d.x.length === 0) return;

            const points = d.x.map((x, i) => ({ x, y: d.y[i] }));
            const n = points.length;
            const sumX = points.reduce((a, b) => a + b.x, 0);
            const sumY = points.reduce((a, b) => a + b.y, 0);
            const sumXY = points.reduce((a, b) => a + b.x * b.y, 0);
            const sumXX = points.reduce((a, b) => a + b.x * b.x, 0);
            const slope = (n * sumXY - sumX * sumY) / (n * sumXX - sumX * sumX) || 0;
            const intercept = (sumY - slope * sumX) / n;
            const xMin = Math.min(...d.x), xMax = Math.max(...d.x);

            const chart = new Chart(canvas.getContext('2d'), {
                type: 'scatter',
                data: {
                    datasets: [{
                        data: points,
                        backgroundColor: color + '55',
                        borderColor: color,
                        borderWidth: 1,
                        pointRadius: 3,
                        pointHoverRadius: 5,
                    }, {
                        data: [{ x: xMin, y: slope * xMin + intercept }, { x: xMax, y: slope * xMax + intercept }],
                        type: 'line',
                        borderColor: color + 'aa',
                        borderWidth: 1.5,
                        fill: false,
                        pointRadius: 0,
                        showLine: true,
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: { duration: 300 },
                    plugins: {
                        legend: { display: false },
                        tooltip: { callbacks: { label: (c) => `X:${c.parsed.x.toFixed(2)}, Y:${c.parsed.y.toFixed(2)}` } }
                    },
                    scales: {
                        x: { title: { display: true, text: term.name, font: { size: 9 } }, grid: { color: '#f1f5f9' }, ticks: { font: { size: 9 }, maxTicksLimit: 5 } },
                        y: { title: { display: true, text: target, font: { size: 9 } }, grid: { color: '#f1f5f9' }, ticks: { font: { size: 9 }, maxTicksLimit: 5 } }
                    },
                    layout: { padding: { right: 8, top: 4 } }
                }
            });
            _rsmMultiCharts.push(chart);
        });

        // Remove last border
        const last = multiScatter.lastElementChild;
        if (last) last.style.borderBottom = 'none';
    };

    function _renderResultsTable() {
        const data = _rsmLastResult;
        const container = document.getElementById('rsm-table-container');
        if (!data || !container) return;

        // Multi-target: always render combined view
        if (data.multi_target) {
            _renderCombinedTab(data);
            return;
        }

        // Sort & Filter terms
        let terms = [...(data.surviving_terms || [])];
        
        // Apply type filter
        if (_rsmTypeFilter !== 'all') {
            terms = terms.filter(t => t.type === _rsmTypeFilter);
        }

        terms.sort((a, b) => {
            let vA = a[_rsmSortState.key] ?? 0, vB = b[_rsmSortState.key] ?? 0;
            if (_rsmSortState.key === 'coefficient' || _rsmSortState.key === 'lasso_coef') {
                vA = Math.abs(vA); vB = Math.abs(vB);
            }
            return _rsmSortState.dir === 'desc' ? vB - vA : vA - vB;
        });

        const maxAbsCoef = Math.max(...terms.map(t => Math.abs(t.coefficient)), 0.01);
        const typeIcons = { main: '📌', interaction: '🔗', quadratic: '📐', cubic: '🧊' };

        window._rsmDisplayedTerms = terms; // Save for CSV export

        let html = `<div style="font-size:13px;font-weight:700;color:#1e293b;margin-bottom:8px;display:flex;justify-content:space-between;align-items:center;">
            <span>🎯 顯著相關項 (${terms.length})</span>
            <div style="display:flex;align-items:center;gap:12px;">
                <button onclick="window._rsmDownloadCsv()" style="padding:4px 8px;font-size:11px;background:#f1f5f9;border:1px solid #cbd5e1;border-radius:4px;cursor:pointer;color:#475569;display:flex;align-items:center;gap:4px;transition:background 0.2s;" onmouseover="this.style.background='#e2e8f0'" onmouseout="this.style.background='#f1f5f9'" title="匯出成 CSV">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
                    下載 CSV
                </button>
                <span style="font-size:11px;font-weight:400;color:#94a3b8;">* 點擊列可查看散佈圖</span>
            </div>
        </div>`;
        html += `<div style="border:1px solid #e2e8f0;border-radius:10px;overflow:hidden;background:#fff;">`;
        html += `<table style="width:100%;border-collapse:collapse;font-size:12px;">`;
        
        const sortIcon = (key) => {
            if (_rsmSortState.key !== key) return '↕️';
            return _rsmSortState.dir === 'desc' ? '⬇️' : '⬆️';
        };

        const hasLasso = terms.some(t => t.lasso_coef != null);
        const maxAbsLasso = Math.max(...terms.map(t => Math.abs(t.lasso_coef || 0)), 0.0001);
        html += `<thead><tr style="background:#f8fafc;color:#64748b;border-bottom:1px solid #e2e8f0;">
            <th style="padding:10px 8px;text-align:center;width:30px;">#</th>
            <th style="padding:10px 12px;text-align:left;">項名稱</th>
            <th style="padding:10px 8px;text-align:left;width:80px;">
                <select id="rsm-type-filter-select" onchange="window._rsmChangeTypeFilter(this.value)" style="border:1px solid #cbd5e1; border-radius:4px; font-size:11px; padding:2px 4px; background:#fff; outline:none; cursor:pointer;">
                    <option value="all" ${_rsmTypeFilter === 'all' ? 'selected' : ''}>類型 (全)</option>
                    <option value="main" ${_rsmTypeFilter === 'main' ? 'selected' : ''}>主效應</option>
                    <option value="interaction" ${_rsmTypeFilter === 'interaction' ? 'selected' : ''}>交互</option>
                    <option value="quadratic" ${_rsmTypeFilter === 'quadratic' ? 'selected' : ''}>二階</option>
                    <option value="cubic" ${_rsmTypeFilter === 'cubic' ? 'selected' : ''}>三階</option>
                </select>
            </th>
            <th onclick="window._rsmToggleSort('coefficient')" style="padding:10px 8px;text-align:center;width:120px;cursor:pointer;user-select:none;color:#1e293b;">相關係數 r ${sortIcon('coefficient')}</th>
            <th onclick="window._rsmToggleSort('lasso_coef')" style="padding:10px 8px;text-align:center;width:110px;cursor:pointer;user-select:none;color:#7c3aed;" title="Lasso 標準化係數：控制其他 term 後的淨貢獻，可跨 term 直接比較">Lasso β ${sortIcon('lasso_coef')}${hasLasso ? '' : ' <span style="font-size:9px;color:#94a3b8;">(計算中)</span>'}</th>
        </tr></thead><tbody id="rsm-table-tbody">`;

        if (terms.length === 0) {
            html += `<tr><td colspan="5" style="text-align:center;padding:20px;color:#94a3b8;">沒有符合此類型的顯著項</td></tr>`;
        }

        terms.forEach((t, idx) => {
            const coefPct = Math.min(Math.abs(t.coefficient) / maxAbsCoef * 100, 100);
            const coefColor = t.coefficient >= 0 ? '#3b82f6' : '#f97316';
            const coefBg = t.coefficient >= 0
                ? `linear-gradient(to right, transparent ${100 - coefPct}%, ${coefColor} ${100 - coefPct}%)`
                : `linear-gradient(to left, transparent ${100 - coefPct}%, ${coefColor} ${100 - coefPct}%)`;
            const lc = t.lasso_coef;
            const lcVal = lc != null ? lc : null;
            const lcPct = lcVal != null ? Math.min(Math.abs(lcVal) / maxAbsLasso * 100, 100) : 0;
            const lcColor = lcVal == null ? '#94a3b8' : lcVal > 0 ? '#7c3aed' : lcVal < 0 ? '#db2777' : '#94a3b8';
            const lcBg = lcVal != null && lcVal !== 0
                ? (lcVal > 0
                    ? `linear-gradient(to right, transparent ${100 - lcPct}%, ${lcColor}33 ${100 - lcPct}%)`
                    : `linear-gradient(to left, transparent ${100 - lcPct}%, ${lcColor}33 ${100 - lcPct}%)`)
                : 'none';
            const lcText = lcVal == null ? '—' : lcVal === 0 ? '<span style="color:#cbd5e1;">0</span>' : `${_fmtSlope(lcVal)}`;
            const icon = typeIcons[t.type] || '';
            const shortName = _truncateName(t.name, 25);

            html += `<tr onclick='window._rsmRowClick(this, ${JSON.stringify(t).replace(/'/g, "&apos;")})' class="rsm-table-row" tabindex="0" style="border-bottom:1px solid #f1f5f9;cursor:pointer;transition:background 0.2s; outline:none;${lcVal === 0 ? 'opacity:0.65;' : ''}">
                <td style="padding:8px 8px;text-align:center;color:#94a3b8;font-size:10px;">${idx + 1}</td>
                <td style="padding:8px 12px;color:#1e293b;font-weight:500;" title="${t.name}">${shortName.replace(/²/g, '<span style="color:#f97316;font-weight:700;">²</span>').replace(/³/g, '<span style="color:#a855f7;font-weight:700;">³</span>')}</td>
                <td style="padding:8px 8px;font-size:11px;color:#64748b;">${icon} ${t.type === 'main' ? '主效應' : t.type === 'interaction' ? '交互' : t.type === 'quadratic' ? '二階' : '三階'}</td>
                <td style="padding:8px 8px;"><div style="display:flex;align-items:center;gap:6px;">
                    <span style="font-family:monospace;font-size:11px;min-width:52px;text-align:right;">${t.coefficient.toFixed(4)}</span>
                    <div style="flex:1;height:6px;border-radius:3px;background:${coefBg};"></div>
                </div></td>
                <td style="padding:8px 8px;"><div style="display:flex;align-items:center;gap:6px;">
                    <span style="font-family:monospace;font-size:11px;min-width:52px;text-align:right;color:${lcColor};">${lcText}</span>
                    <div style="flex:1;height:6px;border-radius:3px;background:${lcBg};"></div>
                </div></td>
            </tr>`;
        });
        html += `</tbody></table></div>`;
        container.innerHTML = html;

        // Add CSS for hover effect
        if (!document.getElementById('rsm-table-style')) {
            const style = document.createElement('style');
            style.id = 'rsm-table-style';
            style.textContent = `
                .rsm-table-row:hover { background-color: #eff6ff !important; }
                .rsm-table-row.active { background-color: #dbeafe !important; box-shadow: inset 2px 0 0 #2563eb; }
                .rsm-table-row:focus { background-color: #dbeafe !important; outline: 1px solid #2563eb; }
            `;
            document.head.appendChild(style);
        }

        // Setup keyboard navigation
        _setupKeyboardNavigation();
    }

    function _setupKeyboardNavigation() {
        // Remove existing listener if any to avoid duplicates
        if (window._rsmKeydownListener) {
            document.removeEventListener('keydown', window._rsmKeydownListener);
        }

        window._rsmKeydownListener = function(e) {
            // Only handle if we have a table and we are not in an input field
            const tbody = document.getElementById('rsm-table-tbody');
            if (!tbody || document.getElementById('rsm-table-container').offsetParent === null) return;
            if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return;

            if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                e.preventDefault();
                const rows = Array.from(tbody.querySelectorAll('.rsm-table-row'));
                if (rows.length === 0) return;

                let currentIndex = rows.findIndex(r => r.classList.contains('active'));
                
                if (e.key === 'ArrowDown') {
                    currentIndex = currentIndex === -1 ? 0 : Math.min(currentIndex + 1, rows.length - 1);
                } else if (e.key === 'ArrowUp') {
                    currentIndex = currentIndex === -1 ? 0 : Math.max(currentIndex - 1, 0);
                }

                const newActiveRow = rows[currentIndex];
                if (newActiveRow) {
                    newActiveRow.click();
                    newActiveRow.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
                }
            }
        };

        document.addEventListener('keydown', window._rsmKeydownListener);
    }

    function _renderExtraSections(data) {
        const container = document.getElementById('rsm-extra-sections');
        if (!container) return;
        container.innerHTML = '';
    }

    // ============ UI INTERACTION HELPERS ============

    function _fmtSlope(v) {
        const a = Math.abs(v);
        if (a === 0) return '0';
        const sign = v >= 0 ? '+' : '';
        if (a >= 0.001) return sign + v.toFixed(4);
        return sign + v.toExponential(2);
    }

    function _truncateName(name, maxLen) {
        if (!name || name.length <= maxLen) return name;
        // if it's an interaction (contains ' × '), split and truncate each part
        if (name.includes(' × ')) {
            const parts = name.split(' × ');
            // distribute length evenly
            const partLen = Math.floor((maxLen - 3) / parts.length);
            return parts.map(p => {
                if (p.length <= partLen) return p;
                // keep front and back to preserve important identifier like "_07" or "Temp"
                const keepFront = Math.floor(partLen * 0.6);
                const keepBack = partLen - keepFront - 2; // -2 for ..
                return p.substring(0, keepFront) + '..' + p.substring(p.length - keepBack);
            }).join(' × ');
        }
        return name.substring(0, maxLen - 3) + '...';
    }

    window._rsmChangeTypeFilter = function(val) {
        _rsmTypeFilter = val;
        _renderResultsTable();
    };

    window._rsmDownloadCsv = function() {
        if (!window._rsmDisplayedTerms || window._rsmDisplayedTerms.length === 0) {
            alert('沒有可匯出的數據');
            return;
        }
        
        let csvContent = "項名稱,類型,相關係數 r,Lasso β\n";

        window._rsmDisplayedTerms.forEach(t => {
            const name = String(t.name).replace(/"/g, '""');
            const typeText = t.type === 'main' ? '主效應' : t.type === 'interaction' ? '交互' : t.type === 'quadratic' ? '二階' : '三階';
            const lc = (t.lasso_coef != null) ? t.lasso_coef.toFixed(6) : '';
            csvContent += `"${name}","${typeText}",${t.coefficient.toFixed(6)},${lc}\n`;
        });
        
        const blob = new Blob(["\uFEFF" + csvContent], { type: 'text/csv;charset=utf-8;' });
        const link = document.createElement("a");
        const url = URL.createObjectURL(blob);
        link.setAttribute("href", url);
        link.setAttribute("download", `RSM_Analysis_${new Date().toISOString().slice(0,10).replace(/-/g,'')}.csv`);
        link.style.visibility = 'hidden';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    };

    window._rsmToggleSort = function(key) {
        if (_rsmSortState.key === key) {
            _rsmSortState.dir = _rsmSortState.dir === 'desc' ? 'asc' : 'desc';
        } else {
            _rsmSortState.key = key;
            _rsmSortState.dir = 'desc';
        }
        _renderResultsTable();
    };

    let _rsmLastChart = null;

    window._rsmRowClick = async function(rowEl, term) {
        // UI feedback
        document.querySelectorAll('.rsm-table-row').forEach(el => el.classList.remove('active'));
        rowEl.classList.add('active');

        const plotTitle = document.getElementById('rsm-plot-title');
        const placeholder = document.getElementById('rsm-plot-placeholder');
        const statsEl = document.getElementById('rsm-plot-stats');
        
        const activeTarget = _rsmCurrentSingleTarget || _rsmTarget;
        if (!activeTarget) {
            console.warn('[RSM] activeTarget is empty, skipping scatter fetch');
            return;
        }
        if (plotTitle) plotTitle.textContent = `${_truncateName(term.name, 30)} vs ${activeTarget}`;

        // Show single scatter (hide multi-scatter if present)
        const singleDiv = document.getElementById('rsm-single-scatter');
        const multiDiv = document.getElementById('rsm-multi-scatter');
        if (singleDiv) singleDiv.style.display = 'block';
        if (multiDiv) multiDiv.style.display = 'none';

        if (placeholder) placeholder.innerHTML = '<div class="spinner"></div><div style="margin-top:8px;">載入數據中...</div>';
        if (statsEl) statsEl.innerHTML = '';

        try {
            let factors = [];
            if (term.type === 'main') {
                factors = [term.name];
            } else if (term.type === 'quadratic') {
                factors = [term.name.replace('²', '')];
            } else if (term.type === 'interaction') {
                factors = term.name.split(' × ');
            } else if (term.type === 'cubic') {
                factors = term.name.replace(/[²³]/g, '').split(' × ');
            }

            const sid = typeof getSessionId === 'function' ? getSessionId() : 'default';
            const body = {
                file_id: currentFileId,
                target: activeTarget,
                term_name: term.name,
                factors: factors,
                term_type: term.type,
                // Pass current filter state for consistency
                filters: (typeof _activeDataset !== 'undefined' && _activeDataset?.filters) ? 
                    _activeDataset.filters.map(f => ({
                        column: f.col, keyword: '==' + String(f.value || ''), exclude_empty: false
                    })) : [],
                exclude_indices: (typeof _clOutlierIndices !== 'undefined') ? _clOutlierIndices : [],
                exclude_cols: (typeof _clExcludedCols !== 'undefined') ? [..._clExcludedCols] : []
            };

            const res = await fetch(`/api/data-prep/rsm-scatter-data?session_id=${sid}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Fetch failed');

            if (placeholder) placeholder.style.display = 'none';
            _drawScatter(data, term);
            
            if (statsEl) {
                const lcStatVal = term.lasso_coef != null ? term.lasso_coef : null;
                const slopeHtml = lcStatVal != null
                    ? `<span>Lasso β: <b style="color:${lcStatVal > 0 ? '#7c3aed' : lcStatVal < 0 ? '#db2777' : '#94a3b8'};">${lcStatVal === 0 ? '0 (pruned)' : _fmtSlope(lcStatVal)}</b></span>`
                    : '';
                statsEl.innerHTML = `
                    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:4px;">
                        <span>觀測數: <b>${data.n}</b></span>
                        <span>相關係數 r: <b style="color:${Math.abs(term.correlation) > 0.5 ? '#dc2626' : '#64748b'};">${term.correlation.toFixed(4)}</b></span>
                        ${slopeHtml}
                    </div>
                `;
            }
        } catch (err) {
            console.error(err);
            if (placeholder) {
                placeholder.style.display = 'flex';
                placeholder.innerHTML = `<div style="color:#ef4444;">❌ 載入失敗: ${err.message}</div>`;
            }
        }
    };

    function _drawScatter(data, term) {
        const canvas = document.getElementById('rsm-scatter-canvas');
        if (!canvas) return;

        if (_rsmLastChart) {
            _rsmLastChart.destroy();
            _rsmLastChart = null;
        }

        if (!data.x || !data.y || data.x.length === 0) {
            const placeholder = document.getElementById('rsm-plot-placeholder');
            if (placeholder) { placeholder.style.display = 'flex'; placeholder.innerHTML = '<div style="color:#94a3b8;">無資料可顯示</div>'; }
            return;
        }

        const points = data.x.map((x, i) => ({ x: x, y: data.y[i] }));
        const ctx = canvas.getContext('2d');
        
        // Simple linear fit for the trendline
        const n = points.length;
        const sumX = points.reduce((a, b) => a + b.x, 0);
        const sumY = points.reduce((a, b) => a + b.y, 0);
        const sumXY = points.reduce((a, b) => a + b.x * b.y, 0);
        const sumXX = points.reduce((a, b) => a + b.x * b.x, 0);
        const slope = (n * sumXY - sumX * sumY) / (n * sumXX - sumX * sumX);
        const intercept = (sumY - slope * sumX) / n;

        const xMin = Math.min(...data.x);
        const xMax = Math.max(...data.x);
        const trendline = [
            { x: xMin, y: slope * xMin + intercept },
            { x: xMax, y: slope * xMax + intercept }
        ];

        _rsmLastChart = new Chart(ctx, {
            type: 'scatter',
            data: {
                datasets: [{
                    label: '數據點',
                    data: points,
                    backgroundColor: 'rgba(59, 130, 246, 0.5)',
                    borderColor: '#3b82f6',
                    borderWidth: 1,
                    pointRadius: 4,
                    pointHoverRadius: 6
                }, {
                    label: '趨勢線',
                    data: trendline,
                    type: 'line',
                    borderColor: 'rgba(239, 68, 68, 0.8)',
                    borderWidth: 2,
                    fill: false,
                    pointRadius: 0,
                    showLine: true
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: { duration: 500 },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => `X: ${ctx.parsed.x.toFixed(3)}, Y: ${ctx.parsed.y.toFixed(3)}`
                        }
                    }
                },
                scales: {
                    x: {
                        title: { display: true, text: term.name, font: { size: 10 } },
                        grid: { color: '#f1f5f9' },
                        ticks: { font: { size: 10 } }
                    },
                    y: {
                        title: { display: true, text: (_rsmCurrentSingleTarget || _rsmTarget), font: { size: 10 } },
                        grid: { color: '#f1f5f9' },
                        ticks: { font: { size: 10 } }
                    }
                }
            }
        });
    }

    function _summaryCard(label, value, bg, border, color) {
        return `<div style="padding:10px 16px;background:${bg};border-radius:10px;border:1px solid ${border};flex:1;min-width:100px;box-shadow:0 1px 2px rgba(0,0,0,0.05);">
            <div style="font-size:11px;color:#64748b;font-weight:600;margin-bottom:2px;">${label}</div>
            <div style="font-size:18px;font-weight:700;color:${color};">${value}</div>
        </div>`;
    }

    // ============ INITIALIZATION ============

})();
