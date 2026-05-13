// ================================================================
// RSM Manager - 響應曲面法三步驟精靈
// Depends on globals from data_preparation.html:
//   currentFileId, allFields, getSessionId(), _mvaFilters,
//   _mvaExcludedIndices, _mvaExcludedCols
// ================================================================

(function () {
    'use strict';

    // Helper: safely convert _clExcludedCols (Set or Array or anything) to plain Array
    function _getExcludedCols() {
        if (typeof _clExcludedCols === 'undefined') return [];
        if (_clExcludedCols instanceof Set) return [..._clExcludedCols];
        if (Array.isArray(_clExcludedCols)) return _clExcludedCols;
        return [];
    }

    let _rsmStep = 1;
    let _rsmTarget = '';        // primary target (first in _rsmTargets)
    let _rsmTargets = [];       // all selected targets (multi-target)
    let _rsmSelectedFactors = [];
    let _rsmTrendData = null;
    let _rsmColsPopulated = false;
    let _rsmLastResult = null;
    let _rsmSortState = { key: 'coefficient', dir: 'desc' };
    let _rsmTypeFilter = 'all';
    let _rsmNameFilter = '';
    let _rsmShapInterFilter = '';
    let _rsmActiveTargetTab = 'combined';  // 'combined' or target name
    let _rsmSmartScores = {};              // col → score from smart filter
    let _rsmShapInterMode = false;         // SHAP interaction mode toggle
    let _rsmShapInterData = null;          // cached SHAP interaction results
    let _rsmShapBgFactor = '';            // 背景條件因子（空=無背景）
    let _rsmColDtypes = {};               // col → 'numeric' | 'categorical'（從 SHAP API 回傳）
    let _rsmShapSingleSortDir = 'desc';  // 3因子表格排序方向
    let _rsmCurrentSingleTarget = '';      // target for single-tab row clicks
    let _rsmMultiCharts = [];              // mini charts in combined mode
    // 4F trellis state
    let _rsmTrellis4FOuterFactor = '';
    let _rsmTrellis4FInnerFactor = '';
    let _rsmTrellis4FXFactor = '';
    let _rsmTrellis4FTarget = '';
    let _rsmTrellis4FOuterGroups = 2;     // outer split: 2 or 3
    let _rsmTrellis4FInnerGroups = 3;     // inner split: 2 or 3
    let _rsmTrellis4FShowNodeCharts = false; // show mini charts on A/B nodes
    let _rsmTrellis4FLastData = null;    // cached last response for re-render
    let _rsmTree4FCharts = [];           // Chart.js instances from _rsmBuildTreeHTML4F

    // ============ PUBLIC API ============

    // Called by switchTool / switchDataset when RSM panel becomes visible
    let _rsmLastFileId = null;

    window.rsmInit = function () {
        const fileId = typeof currentFileId !== 'undefined' ? currentFileId : null;
        const fileChanged = fileId !== _rsmLastFileId;
        _rsmLastFileId = fileId;

        if (fileChanged) {
            // 換檔案時才完整清空
            _rsmSelectedFactors = [];
            _rsmTargets = [];
            _rsmTarget = '';
            _rsmSmartScores = {};
            _rsmColsPopulated = false;
            _rsmShapResult = null;
            _rsmShapInterData = null;
            _rsmShapInterMode = false;
            _rsmShapBgFactor = '';
            _rsmColDtypes = {};
            _rsmShapSingleSortDir = 'desc';
            _rsmTrellis4FOuterFactor = '';
            _rsmTrellis4FInnerFactor = '';
            _rsmTrellis4FXFactor = '';
            _rsmTrellis4FTarget = '';
            _rsmTrellis4FOuterGroups = 2;
            _rsmTrellis4FInnerGroups = 3;
            _rsmTrellis4FLastData = null;
            _rsmTrellisAGroups = 2;
            _rsmTrellisBGroups = 2;
            _rsmTrellisShowNodeCharts = false;
            _rsmTrellisLastData = null;
            _rsmTrellisTreeMode = false;
        }

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
        } else {
            // allFields not ready yet — retry up to 20 times every 150ms
            let _retryCount = 0;
            const _retryPopulate = setInterval(() => {
                _retryCount++;
                if (typeof allFields !== 'undefined' && allFields.length > 0) {
                    clearInterval(_retryPopulate);
                    _populateColumns();
                    if (typeof _clExcludedCols !== 'undefined') {
                        _rsmTargets = _rsmTargets.filter(t => {
                            if (_clExcludedCols instanceof Set) return !_clExcludedCols.has(t);
                            if (Array.isArray(_clExcludedCols)) return !_clExcludedCols.includes(t);
                            return true;
                        });
                        _rsmTarget = _rsmTargets[0] || '';
                        _renderTargetTags();
                    }
                } else if (_retryCount >= 20) {
                    clearInterval(_retryPopulate);
                }
            }, 150);
        }
        rsmGotoStep(_rsmStep || 1);
    };

    window.rsmGotoStep = rsmGotoStep;
    window.rsmRun = rsmRunAnalysis;
    window.rsmResetCols = function () { _rsmColsPopulated = false; };

    // ── Fullscreen toggle for adv scatter (Step 3 multi-target) ──
    let _rsmAdvIsFullscreen = false;
    let _rsmAdvFsOverlay = null;
    let _rsmAdvFsOrigParent = null;
    let _rsmAdvFsOrigNextSibling = null;

    window.rsmAdvToggleFullscreen = function() {
        const pane = document.getElementById('rsm-step2-adv');
        const btn  = document.getElementById('rsm-adv-fullscreen-btn');
        if (!pane) return;
        if (!_rsmAdvIsFullscreen) {
            _rsmAdvFsOrigParent      = pane.parentElement;
            _rsmAdvFsOrigNextSibling = pane.nextSibling;
            _rsmAdvFsOverlay = document.createElement('div');
            _rsmAdvFsOverlay.style.cssText = 'position:fixed;inset:0;z-index:9000;background:#fff;display:flex;flex-direction:column;box-sizing:border-box;';
            pane.style.flex = '1';
            pane.style.minHeight = '0';
            pane.style.display = 'flex';
            _rsmAdvFsOverlay.appendChild(pane);
            document.body.appendChild(_rsmAdvFsOverlay);
            if (btn) btn.textContent = '✕ 縮小';
            _rsmAdvIsFullscreen = true;
            document.addEventListener('keydown', _rsmAdvFsEscHandler);
        } else {
            _rsmAdvExitFullscreen();
        }
    };

    function _rsmAdvFsEscHandler(e) {
        if (e.key === 'Escape' && _rsmAdvIsFullscreen) _rsmAdvExitFullscreen();
    }

    function _rsmAdvExitFullscreen() {
        if (!_rsmAdvIsFullscreen) return;
        const pane = document.getElementById('rsm-step2-adv');
        if (pane && _rsmAdvFsOrigParent) {
            pane.style.flex = '1';
            pane.style.minHeight = '0';
            if (_rsmAdvFsOrigNextSibling) _rsmAdvFsOrigParent.insertBefore(pane, _rsmAdvFsOrigNextSibling);
            else _rsmAdvFsOrigParent.appendChild(pane);
        }
        if (_rsmAdvFsOverlay) { _rsmAdvFsOverlay.remove(); _rsmAdvFsOverlay = null; }
        const btn = document.getElementById('rsm-adv-fullscreen-btn');
        if (btn) btn.textContent = '⛶ 全螢幕';
        _rsmAdvIsFullscreen = false;
        document.removeEventListener('keydown', _rsmAdvFsEscHandler);
    }

    // ── Fullscreen toggle for result area ──
    let _rsmIsFullscreen = false;
    let _rsmFsOverlay = null;
    let _rsmFsOrigParent = null;
    let _rsmFsOrigNextSibling = null;

    window.rsmToggleFullscreen = function() {
        const step3 = document.getElementById('rsm-step3');
        const btn = document.getElementById('rsm-fullscreen-btn');
        if (!step3) return;
        if (!_rsmIsFullscreen) {
            _rsmFsOrigParent = step3.parentElement;
            _rsmFsOrigNextSibling = step3.nextSibling;
            _rsmFsOverlay = document.createElement('div');
            _rsmFsOverlay.style.cssText = 'position:fixed;inset:0;z-index:9000;background:#fff;display:flex;flex-direction:column;box-sizing:border-box;';
            step3.style.flex = '1';
            step3.style.minHeight = '0';
            step3.style.display = 'flex';
            _rsmFsOverlay.appendChild(step3);
            document.body.appendChild(_rsmFsOverlay);
            if (btn) btn.textContent = '✕ 縮小';
            _rsmIsFullscreen = true;
            document.addEventListener('keydown', _rsmFsEscHandler);
        } else {
            _rsmExitFullscreen();
        }
    };

    function _rsmFsEscHandler(e) {
        if (e.key === 'Escape' && _rsmIsFullscreen) _rsmExitFullscreen();
    }

    function _rsmExitFullscreen() {
        if (!_rsmIsFullscreen) return;
        const step3 = document.getElementById('rsm-step3');
        if (step3 && _rsmFsOrigParent) {
            step3.style.flex = '1';
            step3.style.minHeight = '0';
            step3.style.display = 'flex';
            if (_rsmFsOrigNextSibling) _rsmFsOrigParent.insertBefore(step3, _rsmFsOrigNextSibling);
            else _rsmFsOrigParent.appendChild(step3);
        }
        // Restore original ratio
        const layout = document.getElementById('rsm-result-layout');
        if (layout && !_rsmShapInterMode) layout.style.gridTemplateColumns = '1fr 2fr';
        if (_rsmFsOverlay) { _rsmFsOverlay.remove(); _rsmFsOverlay = null; }
        const btn = document.getElementById('rsm-fullscreen-btn');
        if (btn) btn.textContent = '⛶ 全螢幕';
        _rsmIsFullscreen = false;
        document.removeEventListener('keydown', _rsmFsEscHandler);
    }


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
            const dispT = (typeof _dpAlias === 'function') ? _dpAlias(t) : t;
            return `<span title="${t}" style="display:inline-flex;align-items:center;gap:4px;background:${c}18;color:${c};border:1.5px solid ${c}44;border-radius:20px;padding:3px 10px 3px 10px;font-size:12px;font-weight:600;">
                ${dispT}
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
                    exclude_cols: _getExcludedCols(),
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

    function rsmGotoStep(n, forceResults) {
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
        const s2adv = document.getElementById('rsm-step2-adv');
        const s3 = document.getElementById('rsm-step3');
        if (!s1) return;

        const isMultiTarget = _rsmTargets.length > 1;

        s1.style.display = n === 1 ? 'flex' : 'none';

        // Step 2: 單目標與多目標都使用原本的雙清單選取
        if (n === 2) {
            s2.style.display = 'flex';
            if (s2adv) s2adv.style.display = 'none';
            if (typeof window.meRestoreScatterContext === 'function') window.meRestoreScatterContext();
        } else {
            s2.style.display = 'none';
        }

        // Step 3: 多目標 → 進階散佈圖篩選（forceResults 時直接顯示結果）；單目標 → 原始結果
        if (n === 3) {
            const showScatter = isMultiTarget && !forceResults;
            if (showScatter) {
                if (s2adv) { s2adv.style.display = 'flex'; s2adv.style.flex = '1'; s2adv.style.minHeight = '0'; }
                s3.style.display = 'none';
                if (typeof window.meActivateScatterPane === 'function') {
                    // Step 3 scatter 只顯示 Step 2 已選的因子
                    window.meActivateScatterPane('rsm-adv-',
                        _rsmTargets.map(t => ({ col: t.col || t, weight: 1 })),
                        _rsmSelectedFactors.slice(),
                        function(selectedCols) {
                            selectedCols.forEach(col => {
                                if (!_rsmSelectedFactors.includes(col)) _rsmSelectedFactors.push(col);
                            });
                            _populateAvailableFactors();
                        }
                    );
                }
            } else {
                if (s2adv) s2adv.style.display = 'none';
                s3.style.display = 'flex';
                if (typeof window.meRestoreScatterContext === 'function') window.meRestoreScatterContext();
            }
        } else {
            if (s2adv) s2adv.style.display = 'none';
            s3.style.display = 'none';
            if (n !== 2 && typeof window.meRestoreScatterContext === 'function') window.meRestoreScatterContext();
        }

        const showingScatterInStep3 = n === 3 && isMultiTarget && !forceResults;
        const stepTitles = [
            '第一步: 🎯 選擇目標變數 (Y)',
            '第二步: 🔧 選擇因子 (X)',
            showingScatterInStep3 ? '第三步: 🔍 篩選因子 (進階)' : '第三步: 📊 分析結果'
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
        colNames.forEach(n => sel.add(new Option((typeof _dpAlias === 'function') ? _dpAlias(n) : n, n)));

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
            const excludeCols = _getExcludedCols();
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
            const dispName = (typeof _dpAlias === 'function') ? _dpAlias(name) : name;
            if (score != null) {
                const barPct = Math.min((score / maxScore) * 100, 100).toFixed(1);
                li.style.display = 'flex';
                li.style.alignItems = 'center';
                li.style.gap = '6px';
                li.innerHTML = `
                    <div style="flex:1;min-width:0;">
                        <div style="font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${name}">${dispName}</div>
                        <div style="height:3px;background:#e2e8f0;border-radius:2px;margin-top:3px;">
                            <div style="height:100%;width:${barPct}%;background:#7c3aed;border-radius:2px;"></div>
                        </div>
                    </div>
                    <span style="font-size:11px;color:#6d28d9;font-weight:600;flex-shrink:0;min-width:36px;text-align:right;">${score.toFixed(3)}</span>`;
            } else {
                li.textContent = dispName;
                li.title = name;
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
            const excludeCols = _getExcludedCols();

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
            const col = el.dataset.col.toLowerCase();
            const alias = (typeof _dpAlias === 'function') ? _dpAlias(el.dataset.col).toLowerCase() : col;
            el.style.display = (col.includes(kw) || alias.includes(kw)) ? '' : 'none';
        });
    };

    window.rsmFilterSel = function (val) {
        const list = document.getElementById('rsm-sel-list');
        if (!list) return;
        const kw = val.toLowerCase();
        list.querySelectorAll('.rsm-pick-item').forEach(el => {
            const col = el.dataset.col.toLowerCase();
            const alias = (typeof _dpAlias === 'function') ? _dpAlias(el.dataset.col).toLowerCase() : col;
            el.style.display = (col.includes(kw) || alias.includes(kw)) ? '' : 'none';
        });
    };

    // ============ STEP 3: ANALYSIS ============

    async function rsmRunAnalysis() {
        if (_rsmTargets.length === 0) { alert('請先選擇 Target'); rsmGotoStep(1); return; }
        _syncSelectedFromList();
        if (_rsmSelectedFactors.length < 1) { alert('請先選擇 Factors'); rsmGotoStep(2); return; }

        // 多目標 → Step 3 scatter 就是最終結果，不執行舊版分析
        if (_rsmTargets.length > 1) {
            rsmGotoStep(3);
            return;
        }

        rsmGotoStep(3, true);

        // Always reset to poly tab immediately, before any async work
        _rsmShapResult = null;
        _rsmActiveAnalysisTab = 'poly';
        const shapAreaReset = document.getElementById('rsm-shap-area');
        if (shapAreaReset) shapAreaReset.style.display = 'none';
        const polyBtnReset = document.getElementById('rsm-tab-poly');
        const shapBtnReset = document.getElementById('rsm-tab-shap');
        if (polyBtnReset) { polyBtnReset.style.background = '#2563eb'; polyBtnReset.style.color = '#fff'; }
        if (shapBtnReset) { shapBtnReset.style.background = 'transparent'; shapBtnReset.style.color = '#64748b'; }

        const resultArea = document.getElementById('rsm-result-area');
        if (resultArea) resultArea.style.display = '';
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
                exclude_cols: _getExcludedCols(),
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

        // Reset SHAP state for new analysis
        _rsmShapResult = null;
        _rsmShapInterMode = false;
        _rsmShapInterData = null;
        _rsmActiveAnalysisTab = 'poly';
        const shapArea = document.getElementById('rsm-shap-area');
        if (shapArea) shapArea.style.display = 'none';
        // Always make sure poly area is visible
        if (container) container.style.display = '';
        // Switch tab buttons back to poly active
        const polyBtn = document.getElementById('rsm-tab-poly');
        const shapBtn = document.getElementById('rsm-tab-shap');
        if (polyBtn) { polyBtn.style.background = '#2563eb'; polyBtn.style.color = '#fff'; }
        if (shapBtn) { shapBtn.style.background = 'transparent'; shapBtn.style.color = '#64748b'; }
        // Show the tab bar
        _showAnalysisTabBar();

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
            <div id="rsm-result-layout" style="display:grid;grid-template-columns:3fr 2fr;grid-template-rows:1fr;gap:20px;flex:1;min-height:0;align-items:stretch;">
                <div id="rsm-result-left-panel" style="overflow-y:auto;min-height:0;">
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
            <div id="rsm-result-layout" style="display:grid;grid-template-columns:1fr 1fr;grid-template-rows:1fr;gap:20px;flex:1;min-height:0;align-items:stretch;">
                <div id="rsm-result-left-panel" style="overflow-y:auto;min-height:0;">
                    <div id="rsm-table-container"></div>
                </div>
                <div id="rsm-result-right-panel" style="background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:16px;display:flex;flex-direction:column;overflow:hidden;min-height:0;">
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
            <th style="padding:4px 6px;text-align:left;font-weight:600;">
                <input id="rsm-name-filter-input" type="text" placeholder="搜尋因子名稱…" value="${_rsmNameFilter}"
                    oninput="window._rsmChangeNameFilter(this.value)"
                    style="width:100%;border:1px solid #cbd5e1;border-radius:4px;font-size:11px;padding:3px 6px;outline:none;background:#fff;color:#1e293b;">
            </th>
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
            <th style="padding:4px 6px;text-align:left;">
                <input id="rsm-name-filter-input" type="text" placeholder="搜尋因子名稱…" value="${_rsmNameFilter}"
                    oninput="window._rsmChangeNameFilter(this.value)"
                    style="width:100%;border:1px solid #cbd5e1;border-radius:4px;font-size:11px;padding:3px 6px;outline:none;background:#fff;color:#1e293b;">
            </th>
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

    let _rsmCondMode = false;
    let _rsmLastTerm = null;

    // ── Right panel HTML helper (single-target) ──
    function _rightPanelHTML() {
        return `<div id="rsm-result-right-panel" style="background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:16px;display:flex;flex-direction:column;overflow:hidden;min-height:0;">
            <div style="font-size:13px;font-weight:700;color:#1e293b;margin-bottom:10px;display:flex;align-items:center;gap:6px;flex-shrink:0;overflow:hidden;">
                📈 <span id="rsm-plot-title" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0;flex:1;">點擊左側項目查看散佈圖</span>
                <div style="display:flex;gap:4px;flex-shrink:0;">
                    <button id="rsm-mode-scatter" onclick="window._rsmSetMode('scatter')"
                        style="padding:3px 10px;font-size:11px;border-radius:6px;border:1px solid #3b82f6;background:#3b82f6;color:#fff;cursor:pointer;font-weight:600;">散佈圖</button>
                    <button id="rsm-mode-cond" onclick="window._rsmSetMode('cond')"
                        style="padding:3px 10px;font-size:11px;border-radius:6px;border:1px solid #e2e8f0;background:#f8fafc;color:#64748b;cursor:pointer;font-weight:600;" title="以第一個因子切 Low/Mid/High，觀察交互作用方向">條件式</button>
                </div>
            </div>
            <div id="rsm-scatter-area" style="flex:1;min-height:0;position:relative;">
                <div id="rsm-single-scatter" style="position:absolute;inset:0;">
                    <canvas id="rsm-scatter-canvas" style="width:100%;height:100%;"></canvas>
                    <div id="rsm-plot-placeholder" style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#94a3b8;font-size:12px;background:#f8fafc;border-radius:8px;">
                        請從左表選擇一項分析因子或交互作用項
                    </div>
                </div>
                <div id="rsm-cond-scatter" style="display:none;position:absolute;inset:0;overflow-y:auto;"></div>
                <div id="rsm-multi-scatter" style="display:none;"></div>
            </div>
            <div id="rsm-plot-stats" style="margin-top:10px;font-size:11px;color:#64748b;border-top:1px dashed #e2e8f0;padding-top:8px;flex-shrink:0;"></div>
        </div>`;
    }

    window._rsmSetMode = function(mode) {
        _rsmCondMode = (mode === 'cond');
        const btnS = document.getElementById('rsm-mode-scatter');
        const btnC = document.getElementById('rsm-mode-cond');
        if (btnS) { btnS.style.background = _rsmCondMode ? '#f8fafc' : '#3b82f6'; btnS.style.color = _rsmCondMode ? '#64748b' : '#fff'; btnS.style.borderColor = _rsmCondMode ? '#e2e8f0' : '#3b82f6'; }
        if (btnC) { btnC.style.background = _rsmCondMode ? '#7c3aed' : '#f8fafc'; btnC.style.color = _rsmCondMode ? '#fff' : '#64748b'; btnC.style.borderColor = _rsmCondMode ? '#7c3aed' : '#e2e8f0'; }
        // Re-render with current term if any (not in SHAP inter mode — always conditional there)
        if (_rsmLastTerm && !_rsmShapInterMode) {
            const activeRow = document.querySelector('.rsm-table-row.active') || document.createElement('tr');
            window._rsmRowClick(activeRow, _rsmLastTerm);
        }
    };

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
            exclude_cols: _getExcludedCols(),
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

    window._rsmToggleShapInterMode = function() {
        _rsmShapInterMode = !_rsmShapInterMode;
        if (_rsmShapInterMode) {
            _rsmRenderShapInterTable();
        } else {
            _rsmShapInterData = null;
            document.removeEventListener('keydown', _rsmShapInterKeyNav);
            // Restore layout
            const layout = document.getElementById('rsm-result-layout');
            if (layout) layout.style.gridTemplateColumns = '1fr 1fr';
            const rightPanel = document.getElementById('rsm-result-right-panel');
            if (rightPanel) rightPanel.style.minHeight = '400px';
            const btnS = document.getElementById('rsm-mode-scatter');
            const btnC = document.getElementById('rsm-mode-cond');
            if (btnS) btnS.style.display = '';
            if (btnC) btnC.style.display = '';
            _renderResultsTable();
        }
    };

    async function _rsmRenderShapInterTable() {
        const container = document.getElementById('rsm-table-container');
        if (!container) return;

        // Show loading
        const shapInterBtnStyle = 'padding:4px 10px;font-size:11px;background:#f59e0b;border:none;border-radius:6px;cursor:pointer;color:#fff;font-weight:700;';
        container.innerHTML = `
            <div style="font-size:13px;font-weight:700;color:#1e293b;margin-bottom:8px;display:flex;justify-content:space-between;align-items:center;">
                <span>⚡ SHAP 交互模式</span>
                <button onclick="window._rsmToggleShapInterMode()" style="${shapInterBtnStyle}">✕ 關閉 SHAP 交互</button>
            </div>
            <div style="padding:30px;text-align:center;color:#94a3b8;font-size:13px;">
                <div style="font-size:24px;margin-bottom:8px;">🧠</div>
                計算 SHAP Interaction Values 中...
            </div>`;

        try {
            const sid = typeof getSessionId === 'function' ? getSessionId() : 'default';
            const body = {
                file_id: currentFileId,
                targets: _rsmTargets,
                factors: _rsmSelectedFactors,
                filters: (typeof _activeDataset !== 'undefined' && _activeDataset?.filters) ?
                    _activeDataset.filters.map(f => ({ column: f.col, keyword: '==' + String(f.value || ''), exclude_empty: false })) : [],
                exclude_indices: (typeof _clOutlierIndices !== 'undefined') ? _clOutlierIndices : [],
                exclude_cols: _getExcludedCols(),
            };
            if (_rsmShapBgFactor) body.background_factor = _rsmShapBgFactor;
            const res = await fetch(`/api/data-prep/rsm-shap-analysis?session_id=${sid}`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'SHAP 分析失敗');
            _rsmShapInterData = data;
            _rsmDrawShapInterTable(data, container);
        } catch(e) {
            container.innerHTML = `<div style="padding:20px;color:#ef4444;font-size:13px;">❌ ${e.message}</div>`;
            _rsmShapInterMode = false;
        }
    }

    window._rsmToggleShapSingleSort = function() {
        _rsmShapSingleSortDir = _rsmShapSingleSortDir === 'desc' ? 'asc' : 'desc';
        if (_rsmShapInterData) _rsmDrawShapInterTable(_rsmShapInterData, document.getElementById('rsm-table-container'));
    };

    window._rsmChangeShapBgFactor = async function(val) {
        _rsmShapBgFactor = val;
        _rsmShapInterData = null;
        _rsmShapSingleActiveIdx = 0;
        _rsmShapInterActiveIdx = -1;
        _rsmShapKeySection = val ? 'single' : 'pair';
        await _rsmRenderShapInterTable();
    };

    let _rsmShapInterActiveIdx = -1;
    let _rsmShapSingleActiveIdx = 0;   // 目前在 3因子區段的游標
    let _rsmShapKeySection = 'single'; // 'single' | 'pair' — 目前鍵盤在哪一區

    function _rsmShapInterKeyNav(e) {
        if (!_rsmShapInterMode || !_rsmShapInterData) return;
        if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
        e.preventDefault();

        const activeTarget = _rsmCurrentSingleTarget || _rsmTargets[0] || '';
        const targetResult = _rsmShapInterData.results?.[activeTarget] || Object.values(_rsmShapInterData.results || {})[0];
        if (!targetResult) return;

        const dir = e.key === 'ArrowDown' ? 1 : -1;

        if (_rsmShapBgFactor && targetResult.background?.factors_by_group) {
            // 有背景：兩個區段，single（3因子）在上，pair（4因子）在下
            // 用 DOM 行數，避免排序後索引與陣列順序不符
            const singleRows = document.querySelectorAll('[data-shap-single-idx]');
            const singleTotal = singleRows.length;
            const pairTotal = targetResult.shap_interaction?.length || 0;

            function _factorAtIdx(idx) {
                const row = document.querySelector(`[data-shap-single-idx="${idx}"]`);
                return row ? row.getAttribute('data-shap-factor') : null;
            }

            if (_rsmShapKeySection === 'single') {
                const next = _rsmShapSingleActiveIdx + dir;
                if (next < 0) return; // 已在最頂端
                if (next >= singleTotal) {
                    // 切換到 pair 區段第一列
                    _rsmShapKeySection = 'pair';
                    _rsmShapInterActiveIdx = 0;
                    window._rsmShapInterRowClick(0);
                    _scrollShapInterRow(0);
                } else {
                    _rsmShapSingleActiveIdx = next;
                    _highlightSingleRow(next);
                    const factor = _factorAtIdx(next);
                    if (factor) window._rsmShapSingleFactorClick(factor);
                    _scrollShapSingleRow(next);
                }
            } else {
                // pair 區段
                const next = _rsmShapInterActiveIdx + dir;
                if (next < 0) {
                    // 切換回 single 最後一列
                    _rsmShapKeySection = 'single';
                    _rsmShapSingleActiveIdx = singleTotal - 1;
                    _highlightSingleRow(_rsmShapSingleActiveIdx);
                    const factor = _factorAtIdx(_rsmShapSingleActiveIdx);
                    if (factor) window._rsmShapSingleFactorClick(factor);
                    _scrollShapSingleRow(_rsmShapSingleActiveIdx);
                } else {
                    _rsmShapInterActiveIdx = Math.min(next, pairTotal - 1);
                    window._rsmShapInterRowClick(_rsmShapInterActiveIdx);
                    _scrollShapInterRow(_rsmShapInterActiveIdx);
                }
            }
        } else {
            // 無背景：只有 pair 區段
            const total = targetResult.shap_interaction?.length || 0;
            if (total === 0) return;
            _rsmShapInterActiveIdx = Math.max(0, Math.min(_rsmShapInterActiveIdx + dir, total - 1));
            window._rsmShapInterRowClick(_rsmShapInterActiveIdx);
            _scrollShapInterRow(_rsmShapInterActiveIdx);
        }
    }

    function _highlightSingleRow(idx) {
        document.querySelectorAll('[data-shap-single-idx]').forEach(r => {
            r.style.background = '';
            r.style.boxShadow = '';
            r.style.borderLeft = '';
        });
        const row = document.querySelector(`[data-shap-single-idx="${idx}"]`);
        if (row) {
            row.style.background = '#dbeafe';
            row.style.borderLeft = '3px solid #2563eb';
        }
    }

    function _scrollShapSingleRow(idx) {
        const row = document.querySelector(`[data-shap-single-idx="${idx}"]`);
        if (row) row.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }

    function _scrollShapInterRow(idx) {
        const row = document.querySelector(`[data-shap-inter-idx="${idx}"]`);
        if (row) row.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }

    function _rsmDrawShapInterTable(shapData, container) {
        // Capture col_dtypes from response for dropdown icons
        if (shapData.col_dtypes) _rsmColDtypes = shapData.col_dtypes;

        const activeTarget = _rsmCurrentSingleTarget || _rsmTargets[0] || '';
        const targetResult = shapData.results?.[activeTarget] || Object.values(shapData.results || {})[0];
        if (!targetResult || !targetResult.shap_interaction) {
            container.innerHTML = `<div style="padding:20px;color:#94a3b8;font-size:13px;">無交互資料</div>`;
            return;
        }

        let pairs = targetResult.shap_interaction; // [{factor_a, factor_b, interaction}]
        if (_rsmShapInterFilter) {
            const f = _rsmShapInterFilter.toLowerCase();
            pairs = pairs.filter(p => p.factor_a.toLowerCase().includes(f) || p.factor_b.toLowerCase().includes(f));
        }
        const maxVal = Math.max(...pairs.map(p => p.interaction), 0.0001);
        const r2 = targetResult.r2;
        const r2Color = r2 == null ? '#94a3b8' : r2 >= 0.8 ? '#059669' : r2 >= 0.5 ? '#d97706' : '#dc2626';
        const shapInterBtnStyle = 'padding:4px 10px;font-size:11px;background:#f59e0b;border:none;border-radius:6px;cursor:pointer;color:#fff;font-weight:700;';

        // All available factors for background selector (numeric model factors + categorical cols)
        const allFactors = (targetResult.shap_importance || []).map(s => s.factor);
        const catCols = Object.entries(_rsmColDtypes)
            .filter(([col, t]) => t === 'categorical' && !allFactors.includes(col))
            .map(([col]) => col)
            .sort();
        const bgOptions = [
            `<option value="">— 無背景條件 —</option>`,
            allFactors.length ? `<optgroup label="# 數值欄位">` : '',
            ...allFactors.map(f =>
                `<option value="${f}" ${f === _rsmShapBgFactor ? 'selected' : ''}># ${f}</option>`
            ),
            allFactors.length ? `</optgroup>` : '',
            catCols.length ? `<optgroup label="Aa 類別欄位">` : '',
            ...catCols.map(c =>
                `<option value="${c}" ${c === _rsmShapBgFactor ? 'selected' : ''}>Aa ${c}</option>`
            ),
            catCols.length ? `</optgroup>` : '',
        ].join('');

        // Target tabs if multi-target
        const targets = shapData.targets || [activeTarget];
        const tabsHtml = targets.length > 1 ? `<div style="display:flex;gap:4px;margin-bottom:6px;flex-wrap:wrap;">
            ${targets.map(t => `<button onclick="window._rsmShapInterSwitchTarget('${t}')"
                style="padding:3px 8px;font-size:11px;border-radius:4px;cursor:pointer;border:1px solid ${t===activeTarget?'#f59e0b':'#e2e8f0'};background:${t===activeTarget?'#fef3c7':'#fff'};color:${t===activeTarget?'#92400e':'#64748b'};font-weight:${t===activeTarget?700:400};">${t}</button>`).join('')}
        </div>` : '';

        let html = `<div style="font-size:13px;font-weight:700;color:#1e293b;margin-bottom:6px;display:flex;justify-content:space-between;align-items:center;">
            <span>⚡ SHAP 交互模式 <span style="font-size:11px;font-weight:400;color:#94a3b8;">對 ${activeTarget} 的貢獻</span>
            ${r2 != null ? `<span style="margin-left:8px;padding:2px 8px;border-radius:10px;background:${r2Color}18;color:${r2Color};font-size:11px;font-weight:700;">R² = ${r2.toFixed(4)}</span>` : ''}
            </span>
            <button onclick="window._rsmToggleShapInterMode()" style="${shapInterBtnStyle}" title="關閉並回到多項式展開">✕ 關閉 SHAP 交互</button>
        </div>
        <div style="margin-bottom:8px;display:flex;align-items:center;gap:6px;background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:6px 10px;">
            <span style="font-size:11px;color:#92400e;font-weight:600;white-space:nowrap;">🔒 背景條件：</span>
            <select onchange="window._rsmChangeShapBgFactor(this.value)"
                style="flex:1;border:1px solid #fde68a;border-radius:4px;font-size:11px;padding:3px 6px;background:#fff;color:#92400e;outline:none;cursor:pointer;">
                ${bgOptions}
            </select>
            ${_rsmShapBgFactor ? `<span style="font-size:10px;color:#92400e;white-space:nowrap;">3因子↑ 4因子↓</span>` : ''}
        </div>
        ${tabsHtml}`;

        if (_rsmShapBgFactor && targetResult.background?.factors_by_group) {
            // ── Section 1: 3-factor (single factor, conditioned on background) ──
            const bgData = targetResult.background;
            const isCatBg = bgData.bg_type === 'categorical';
            const bgGroupNames = bgData.group_names || ['低組', '中組', '高組'];
            const bgSubtitle = isCatBg
                ? bgGroupNames.map(n => `<span style="background:#e0f2fe;color:#0369a1;border-radius:3px;padding:1px 5px;margin:0 2px;">${n}</span>`).join('')
                : `<span style="font-weight:400;color:#64748b;font-size:10px;">分位 ≤${bgData.p33} / ≤${bgData.p67}</span>`;
            const singleFactors = bgData.factors_by_group;
            const maxAvg = Math.max(...singleFactors.map(f => f.avg), 0.0001);
            html += `<div style="font-size:11px;font-weight:700;color:#0369a1;padding:4px 6px;background:#f0f9ff;border-radius:6px 6px 0 0;border:1px solid #bae6fd;margin-bottom:0;">
                🔵 3 因子（目標 + <b>${_rsmShapBgFactor.substring(0,14)}</b> + 因子）— 點列查看條件式分析
                <span style="font-weight:400;margin-left:4px;">${bgSubtitle}</span>
            </div>
            <div style="border:1px solid #bae6fd;border-top:none;border-radius:0 0 8px 8px;overflow:hidden;margin-bottom:10px;background:#fff;">
            <table style="width:100%;border-collapse:collapse;font-size:11px;table-layout:fixed;">
            <colgroup><col style="width:24px;"><col><col style="width:66px;"></colgroup>
            <thead><tr style="background:#f0f9ff;color:#0369a1;border-bottom:1px solid #bae6fd;">
                <th style="padding:5px 3px;text-align:center;">#</th>
                <th style="padding:5px 6px;text-align:left;">因子</th>
                <th style="padding:5px 6px;text-align:center;cursor:pointer;user-select:none;white-space:nowrap;"
                    title="三組 SHAP 重要度最大差值，越大代表與背景條件交互越強"
                    onclick="window._rsmToggleShapSingleSort()">
                    交互 Δ ${_rsmShapSingleSortDir === 'desc' ? '▼' : '▲'}
                </th>
            </tr></thead><tbody>
            ${[...singleFactors].sort((a,b) => _rsmShapSingleSortDir === 'desc' ? b.delta - a.delta : a.delta - b.delta).slice(0,30).map((f, i) => {
                const deltaColor = f.delta > f.avg * 0.5 ? '#7c3aed' : f.delta > f.avg * 0.2 ? '#0369a1' : '#94a3b8';
                const factorEsc = f.factor.replace(/'/g, "\\'");
                return `<tr data-shap-single-idx="${i}" data-shap-factor="${f.factor.replace(/"/g,'&quot;')}" onclick="window._rsmShapSingleFactorClick('${factorEsc}')"
                    style="border-bottom:1px solid #f1f5f9;cursor:pointer;" onmouseover="this.style.background='#eff6ff'" onmouseout="if(this.style.borderLeft!=='3px solid rgb(37, 99, 235)')this.style.background=''">
                    <td style="padding:5px 3px;text-align:center;color:#94a3b8;">${i+1}</td>
                    <td style="padding:5px 6px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#1e293b;font-weight:500;" title="${f.factor}">${f.factor}</td>
                    <td style="padding:5px 6px;text-align:center;font-weight:700;color:${deltaColor};">${f.delta.toFixed(3)}</td>
                </tr>`;
            }).join('')}
            </tbody></table></div>`;

            // ── Section 2: 4-factor (pair, conditioned on background × B) ──
            html += `<div style="font-size:11px;font-weight:700;color:#7c3aed;padding:4px 6px;background:#faf5ff;border-radius:6px 6px 0 0;border:1px solid #e9d5ff;margin-bottom:0;">
                🟣 4 因子（目標 + <b>${_rsmShapBgFactor.substring(0,12)}</b> + A + B）— 點列查看 6 格樹狀圖
            </div>
            <div style="border:1px solid #e9d5ff;border-top:none;border-radius:0 0 8px 8px;overflow:hidden;background:#fff;">
            <table style="width:100%;border-collapse:collapse;font-size:11px;table-layout:fixed;">
            <colgroup><col style="width:24px;"><col style="width:40%;"><col style="width:40%;"><col></colgroup>
            <thead><tr style="background:#faf5ff;color:#7c3aed;border-bottom:1px solid #e9d5ff;">
                <th style="padding:5px 3px;text-align:center;">#</th>
                <th style="padding:4px 6px;text-align:left;">
                    <input type="text" placeholder="搜尋 A 或 B…" value="${_rsmShapInterFilter}"
                        oninput="window._rsmChangeShapInterFilter(this.value)"
                        style="width:100%;border:1px solid #e9d5ff;border-radius:4px;font-size:10px;padding:2px 5px;outline:none;background:#faf5ff;color:#7c3aed;">
                </th>
                <th style="padding:5px 6px;text-align:left;">因子 B</th>
                <th style="padding:5px 6px;text-align:left;">SHAP 強度</th>
            </tr></thead><tbody>
            ${pairs.map((p, i) => {
                const bar = Math.round((p.interaction / maxVal) * 100);
                return `<tr data-shap-inter-idx="${i}" onclick="window._rsmShapInterRowClick(${i})"
                    style="border-bottom:1px solid #f1f5f9;cursor:pointer;" onmouseover="this.style.background='#faf5ff'" onmouseout="this.style.background=''">
                    <td style="padding:5px 3px;text-align:center;color:#94a3b8;">${i+1}</td>
                    <td style="padding:5px 6px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#1e293b;font-weight:500;" title="${p.factor_a}">${p.factor_a}</td>
                    <td style="padding:5px 6px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#1e293b;" title="${p.factor_b}">${p.factor_b}</td>
                    <td style="padding:5px 6px;overflow:hidden;">
                        <div style="display:flex;align-items:center;gap:4px;">
                            <div style="flex:1;min-width:0;height:6px;background:#f1f5f9;border-radius:3px;overflow:hidden;">
                                <div style="width:${bar}%;height:100%;background:linear-gradient(90deg,#8b5cf6,#ec4899);border-radius:3px;"></div>
                            </div>
                            <span style="font-size:10px;color:#7c3aed;font-weight:700;white-space:nowrap;">${p.interaction.toFixed(4)}</span>
                        </div>
                    </td>
                </tr>`;
            }).join('')}
            </tbody></table></div>`;
        } else {
            // ── No background: original pairs table (3-factor on click) ──
            html += `<div style="border:1px solid #e2e8f0;border-radius:10px;overflow:hidden;background:#fff;">
            <table style="width:100%;border-collapse:collapse;font-size:12px;table-layout:fixed;">
            <colgroup><col style="width:28px;"><col style="width:33%;"><col style="width:33%;"><col></colgroup>
            <thead><tr style="background:#fef3c7;color:#92400e;border-bottom:1px solid #fde68a;">
                <th style="padding:8px 4px;text-align:center;">#</th>
                <th colspan="2" style="padding:4px 8px;text-align:left;">
                    <input type="text" placeholder="搜尋因子 A 或 B…" value="${_rsmShapInterFilter}"
                        oninput="window._rsmChangeShapInterFilter(this.value)"
                        style="width:100%;border:1px solid #fde68a;border-radius:4px;font-size:11px;padding:3px 6px;outline:none;background:#fffbeb;color:#92400e;">
                </th>
                <th style="padding:8px 10px;text-align:left;">SHAP 交互強度</th>
            </tr></thead><tbody>
            ${pairs.map((p, i) => {
                const bar = Math.round((p.interaction / maxVal) * 100);
                return `<tr data-shap-inter-idx="${i}" onclick="window._rsmShapInterRowClick(${i})"
                    style="border-bottom:1px solid #f1f5f9;cursor:pointer;transition:background 0.1s;"
                    onmouseover="this.style.background='#fffbeb'" onmouseout="this.style.background=''">
                    <td style="padding:7px 4px;text-align:center;color:#94a3b8;font-size:11px;">${i+1}</td>
                    <td style="padding:7px 10px;font-size:11px;color:#1e293b;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${p.factor_a}">${p.factor_a}</td>
                    <td style="padding:7px 10px;font-size:11px;color:#1e293b;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${p.factor_b}">${p.factor_b}</td>
                    <td style="padding:7px 10px;overflow:hidden;">
                        <div style="display:flex;align-items:center;gap:5px;">
                            <div style="flex:1;min-width:0;height:8px;background:#f1f5f9;border-radius:4px;overflow:hidden;">
                                <div style="width:${bar}%;height:100%;background:linear-gradient(90deg,#f59e0b,#ef4444);border-radius:4px;"></div>
                            </div>
                            <span style="font-size:11px;color:#92400e;font-weight:700;white-space:nowrap;">${p.interaction.toFixed(4)}</span>
                        </div>
                    </td>
                </tr>`;
            }).join('')}
            </tbody></table></div>`;
        }

        container.innerHTML = html;

        // Keyboard navigation: ↑↓ to move between rows
        document.removeEventListener('keydown', _rsmShapInterKeyNav);
        document.addEventListener('keydown', _rsmShapInterKeyNav);

        // Keep side-by-side layout, hide scatter/cond buttons
        const layout = document.getElementById('rsm-result-layout');
        if (layout) layout.style.gridTemplateColumns = '1fr 2fr';
        const rightPanel = document.getElementById('rsm-result-right-panel');
        if (rightPanel) rightPanel.style.minHeight = '0';
        const btnS = document.getElementById('rsm-mode-scatter');
        const btnC = document.getElementById('rsm-mode-cond');
        if (btnS) btnS.style.display = 'none';
        if (btnC) btnC.style.display = 'none';
        _rsmCondMode = true;
    }

    window._rsmShapInterSwitchTarget = function(target) {
        _rsmCurrentSingleTarget = target;
        if (_rsmShapInterData) _rsmDrawShapInterTable(_rsmShapInterData, document.getElementById('rsm-table-container'));
    };

    // 3-factor click: target + bgFactor + singleFactor (conditioned on bgFactor Low/Mid/High)
    window._rsmShapSingleFactorClick = async function(factorName) {
        // Clear both tables' highlights
        document.querySelectorAll('[data-shap-inter-idx]').forEach(r => { r.style.background = ''; r.style.borderLeft = ''; });
        document.querySelectorAll('[data-shap-single-idx]').forEach(r => { r.style.background = ''; r.style.borderLeft = ''; });
        // Find and highlight the matching single row
        document.querySelectorAll('[data-shap-single-idx]').forEach(r => {
            if (r.getAttribute('data-shap-factor') === factorName) {
                r.style.background = '#dbeafe';
                r.style.borderLeft = '3px solid #2563eb';
            }
        });
        // Show conditional: conditioned on bgFactor, x = singleFactor
        const activeTarget = _rsmCurrentSingleTarget || _rsmTargets[0] || '';
        const fakeTerm = {
            name: `${_rsmShapBgFactor} × ${factorName}`,
            type: 'interaction',
            factors: [_rsmShapBgFactor, factorName],
            correlation: 0, lasso_coef: null
        };
        await _rsmRowClickConditional(fakeTerm, activeTarget);
    };

    window._rsmShapInterRowClick = async function(idx) {
        if (!_rsmShapInterData) return;
        _rsmShapInterActiveIdx = idx;
        const activeTarget = _rsmCurrentSingleTarget || _rsmTargets[0] || '';
        const targetResult = _rsmShapInterData.results?.[activeTarget] || Object.values(_rsmShapInterData.results || {})[0];
        if (!targetResult?.shap_interaction?.[idx]) return;
        const p = targetResult.shap_interaction[idx];
        // Highlight row — clear both tables, then mark active
        document.querySelectorAll('[data-shap-single-idx]').forEach(r => { r.style.background = ''; r.style.borderLeft = ''; });
        document.querySelectorAll('[data-shap-inter-idx]').forEach(r => { r.style.background = ''; r.style.borderLeft = ''; });
        const row = document.querySelector(`[data-shap-inter-idx="${idx}"]`);
        if (row) {
            row.style.background = _rsmShapBgFactor ? '#ede9fe' : '#fef3c7';
            row.style.borderLeft = _rsmShapBgFactor ? '3px solid #7c3aed' : '3px solid #f59e0b';
        }

        if (_rsmShapBgFactor) {
            // 4-factor: call trellis-4f → 6-grid tree
            await _rsmShapInterRow4FClick(p.factor_a, p.factor_b, activeTarget);
        } else {
            // 3-factor: normal conditional
            const fakeTerm = { name: `${p.factor_a} × ${p.factor_b}`, type: 'interaction', factors: [p.factor_a, p.factor_b], correlation: 0, lasso_coef: null };
            await _rsmRowClickConditional(fakeTerm, activeTarget);
        }
    };

    async function _rsmShapInterRow4FClick(factorA, factorB, activeTarget, outerGroups, innerGroups, outerFactor) {
        // Store state for swap/rerender
        // outerFactor 由 swap 傳入時，不動 _rsmShapBgFactor（下拉選單的背景條件）
        _rsmTrellis4FOuterFactor = outerFactor !== undefined ? outerFactor : _rsmShapBgFactor;
        _rsmTrellis4FInnerFactor = factorB;
        _rsmTrellis4FXFactor = factorA;
        _rsmTrellis4FTarget = activeTarget;
        if (outerGroups !== undefined) _rsmTrellis4FOuterGroups = outerGroups;
        if (innerGroups !== undefined) _rsmTrellis4FInnerGroups = innerGroups;

        const condDiv = document.getElementById('rsm-cond-scatter');
        const singleDiv = document.getElementById('rsm-single-scatter');
        const multiDiv = document.getElementById('rsm-multi-scatter');
        const plotTitle = document.getElementById('rsm-plot-title');
        const statsEl = document.getElementById('rsm-plot-stats');
        if (singleDiv) singleDiv.style.display = 'none';
        if (multiDiv) multiDiv.style.display = 'none';
        if (condDiv) { condDiv.style.cssText = 'position:absolute;inset:0;overflow:auto;'; condDiv.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#94a3b8;font-size:12px;">載入中...</div>'; }
        if (statsEl) statsEl.innerHTML = '';
        if (plotTitle) plotTitle.textContent = `4 因子：${_rsmTrellis4FOuterFactor.substring(0,10)} × ${_rsmTrellis4FInnerFactor.substring(0,10)} × ${_rsmTrellis4FXFactor.substring(0,10)} → ${activeTarget}`;

        const sid = typeof getSessionId === 'function' ? getSessionId() : 'default';
        const body = {
            file_id: currentFileId,
            target: activeTarget,
            outer_factor: _rsmTrellis4FOuterFactor,
            inner_factor: _rsmTrellis4FInnerFactor,
            x_factor: _rsmTrellis4FXFactor,
            outer_groups: _rsmTrellis4FOuterGroups,
            inner_groups: _rsmTrellis4FInnerGroups,
            filters: (typeof _activeDataset !== 'undefined' && _activeDataset?.filters) ?
                _activeDataset.filters.map(f => ({ column: f.col, keyword: '==' + String(f.value || ''), exclude_empty: false })) : [],
            exclude_indices: (typeof _clOutlierIndices !== 'undefined') ? _clOutlierIndices : [],
            exclude_cols: _getExcludedCols(),
        };
        try {
            const res = await fetch(`/api/data-prep/rsm-trellis-data-4f?session_id=${sid}`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || '載入失敗');
            _rsmTrellis4FLastData = { data, activeTarget };
            if (condDiv) condDiv.innerHTML = _rsmBuildTreeHTML4F(data, activeTarget);
        } catch(e) {
            if (condDiv) condDiv.innerHTML = `<div style="padding:20px;color:#ef4444;font-size:13px;">❌ ${e.message}</div>`;
        }
    }

    window._rsmTrellis4FSwap = async function(pair) {
        // pair: 'outer-inner' | 'outer-x' | 'inner-x'
        let a = _rsmTrellis4FOuterFactor, b = _rsmTrellis4FInnerFactor, c = _rsmTrellis4FXFactor;
        if (pair === 'outer-inner') { [a, b] = [b, a]; }
        else if (pair === 'outer-x') { [a, c] = [c, a]; }
        else if (pair === 'inner-x') { [b, c] = [c, b]; }
        // 不修改 _rsmShapBgFactor，避免影響 3 因子表格的條件式
        await _rsmShapInterRow4FClick(c, b, _rsmTrellis4FTarget, undefined, undefined, a);
    };

    window._rsmTrellis4FToggleNodeCharts = function() {
        _rsmTrellis4FShowNodeCharts = !_rsmTrellis4FShowNodeCharts;
        if (_rsmTrellis4FLastData) {
            const condDiv = document.getElementById('rsm-cond-scatter');
            if (condDiv) condDiv.innerHTML = _rsmBuildTreeHTML4F(_rsmTrellis4FLastData.data, _rsmTrellis4FLastData.activeTarget);
        }
    };

    window._rsmTrellis4FSetGroups = async function(which, n) {
        if (which === 'outer') _rsmTrellis4FOuterGroups = n;
        else _rsmTrellis4FInnerGroups = n;
        await _rsmShapInterRow4FClick(
            _rsmTrellis4FXFactor, _rsmTrellis4FInnerFactor, _rsmTrellis4FTarget,
            undefined, undefined, _rsmTrellis4FOuterFactor
        );
    };

    function _renderResultsTable() {
        const data = _rsmLastResult;
        const container = document.getElementById('rsm-table-container');
        if (!data || !container) return;

        // SHAP interaction mode
        if (_rsmShapInterMode) {
            if (_rsmShapInterData) { _rsmDrawShapInterTable(_rsmShapInterData, container); return; }
            _rsmRenderShapInterTable();
            return;
        }

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

        // Apply name filter
        if (_rsmNameFilter) {
            terms = terms.filter(t => t.name.toLowerCase().includes(_rsmNameFilter));
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

        const shapInterBtnStyle = _rsmShapInterMode
            ? 'padding:4px 10px;font-size:11px;background:#f59e0b;border:none;border-radius:6px;cursor:pointer;color:#fff;font-weight:700;'
            : 'padding:4px 10px;font-size:11px;background:#f1f5f9;border:1px solid #cbd5e1;border-radius:6px;cursor:pointer;color:#64748b;font-weight:600;';

        let html = `<div style="font-size:13px;font-weight:700;color:#1e293b;margin-bottom:8px;display:flex;justify-content:space-between;align-items:center;">
            <span>🎯 顯著相關項 (${terms.length})</span>
            <div style="display:flex;align-items:center;gap:8px;">
                <button onclick="window._rsmToggleShapInterMode()" style="${shapInterBtnStyle}" title="用 SHAP Interaction Values 排名交互項">⚡ SHAP 交互模式</button>
                <button onclick="window._rsmDownloadCsv()" style="padding:4px 8px;font-size:11px;background:#f1f5f9;border:1px solid #cbd5e1;border-radius:4px;cursor:pointer;color:#475569;display:flex;align-items:center;gap:4px;" title="匯出成 CSV">
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
            <th style="padding:4px 8px;text-align:left;">
                <input id="rsm-name-filter-input" type="text" placeholder="搜尋因子名稱…" value="${_rsmNameFilter}"
                    oninput="window._rsmChangeNameFilter(this.value)"
                    style="width:100%;border:1px solid #cbd5e1;border-radius:4px;font-size:11px;padding:3px 6px;outline:none;background:#fff;color:#1e293b;">
            </th>
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
        if (v == null || isNaN(v)) return '—';
        const a = Math.abs(v);
        if (a === 0) return '0';
        const sign = v >= 0 ? '+' : '';
        if (a >= 0.001) return sign + v.toFixed(4);
        return sign + v.toExponential(2);
    }

    function _safeR(v, d) { return (v != null && !isNaN(v)) ? v.toFixed(d) : '—'; }

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

    window._rsmChangeNameFilter = function(val) {
        _rsmNameFilter = val.trim().toLowerCase();
        _renderResultsTable();
    };

    window._rsmChangeShapInterFilter = function(val) {
        _rsmShapInterFilter = val.trim().toLowerCase();
        if (_rsmShapInterData) {
            _rsmDrawShapInterTable(_rsmShapInterData, document.getElementById('rsm-table-container'));
        }
    };

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
        _rsmLastTerm = term;

        const activeTarget = _rsmCurrentSingleTarget || _rsmTarget;
        if (!activeTarget) return;

        // Route to conditional or normal scatter
        if (_rsmCondMode && (term.type === 'interaction' || term.type === 'cubic')) {
            // Cubic A³ (single factor) cannot be used for conditional analysis
            const parsedFactors = term.type === 'interaction'
                ? term.name.split(' × ')
                : term.name.replace(/[²³]/g, '').split(' × ');
            if (parsedFactors.length < 2) {
                // Fall through to normal scatter
            } else {
                await _rsmRowClickConditional(term, activeTarget);
                return;
            }
        }

        const plotTitle = document.getElementById('rsm-plot-title');
        const placeholder = document.getElementById('rsm-plot-placeholder');
        const statsEl = document.getElementById('rsm-plot-stats');

        if (plotTitle) plotTitle.textContent = `${_truncateName(term.name, 30)} vs ${activeTarget}`;

        // Show single scatter
        const singleDiv = document.getElementById('rsm-single-scatter');
        const condDiv = document.getElementById('rsm-cond-scatter');
        const multiDiv = document.getElementById('rsm-multi-scatter');
        if (singleDiv) singleDiv.style.display = 'block';
        if (condDiv) condDiv.style.display = 'none';
        if (multiDiv) multiDiv.style.display = 'none';
        if (statsEl) { statsEl.style.display = ''; statsEl.innerHTML = ''; }

        if (placeholder) placeholder.innerHTML = '<div class="spinner"></div><div style="margin-top:8px;">載入數據中...</div>';

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
                filters: (typeof _activeDataset !== 'undefined' && _activeDataset?.filters) ?
                    _activeDataset.filters.map(f => ({
                        column: f.col, keyword: '==' + String(f.value || ''), exclude_empty: false
                    })) : [],
                exclude_indices: (typeof _clOutlierIndices !== 'undefined') ? _clOutlierIndices : [],
                exclude_cols: _getExcludedCols()
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

    let _rsmCondCharts = [];

    async function _rsmRowClickConditional(term, activeTarget) {
        const plotTitle = document.getElementById('rsm-plot-title');
        const statsEl = document.getElementById('rsm-plot-stats');
        const singleDiv = document.getElementById('rsm-single-scatter');
        const condDiv = document.getElementById('rsm-cond-scatter');
        const multiDiv = document.getElementById('rsm-multi-scatter');

        if (singleDiv) singleDiv.style.display = 'none';
        // Destroy any orphaned 4F trellis charts before replacing condDiv content
        _rsmTree4FCharts.forEach(c => { try { c.destroy(); } catch(e) {} });
        _rsmTree4FCharts = [];
        if (condDiv) {
            condDiv.style.cssText = 'position:absolute;inset:0;overflow-x:scroll;overflow-y:auto;';
            condDiv.className = 'rsm-cond-scroll';
            // Inject scoped scrollbar style if not present
            if (!document.getElementById('rsm-cond-scroll-style')) {
                const st = document.createElement('style');
                st.id = 'rsm-cond-scroll-style';
                st.textContent = '.rsm-cond-scroll::-webkit-scrollbar{height:10px!important;}.rsm-cond-scroll::-webkit-scrollbar-track{background:#f1f5f9!important;border-radius:5px!important;}.rsm-cond-scroll::-webkit-scrollbar-thumb{background:#94a3b8!important;border-radius:5px!important;}.rsm-cond-scroll::-webkit-scrollbar-thumb:hover{background:#64748b!important;}';
                document.head.appendChild(st);
            }
            condDiv.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#94a3b8;font-size:12px;">載入中...</div>';
        }
        if (multiDiv) multiDiv.style.display = 'none';
        if (statsEl) { statsEl.innerHTML = ''; statsEl.style.display = 'none'; }

        let factors = [];
        if (term.type === 'interaction') factors = term.name.split(' × ');
        else if (term.type === 'cubic') factors = term.name.replace(/[²³]/g, '').split(' × ');

        // 3-factor cubic → trellis 2×2
        const isTrellis = (term.type === 'cubic') && (factors.length >= 3);

        const sid = typeof getSessionId === 'function' ? getSessionId() : 'default';
        const body = {
            file_id: currentFileId,
            target: activeTarget,
            term_name: term.name,
            factors,
            term_type: term.type,
            filters: (typeof _activeDataset !== 'undefined' && _activeDataset?.filters) ?
                _activeDataset.filters.map(f => ({ column: f.col, keyword: '==' + String(f.value || ''), exclude_empty: false })) : [],
            exclude_indices: (typeof _clOutlierIndices !== 'undefined') ? _clOutlierIndices : [],
            exclude_cols: _getExcludedCols(),
        };

        try {
            const endpoint = isTrellis ? 'rsm-trellis-data' : 'rsm-conditional-data';
            const res = await fetch(`/api/data-prep/${endpoint}?session_id=${sid}`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
            });
            const data = await res.json();

            if (isTrellis) {
                _rsmRenderTrellis(data, activeTarget, condDiv, statsEl, plotTitle);
                window._rsmCondData = { data, term, activeTarget, isTrellis: true, body, sid };
                // Save trellis entry to notebook history
                (() => {
                    if (!window._rsmConditionalHistory) window._rsmConditionalHistory = [];
                    const cells = data.cells || [];
                    const _sr = v => v != null ? ((v >= 0 ? '+' : '') + v.toFixed(3)) : '—';
                    const lines = [
                        `Trellis：「${term.name}」× 目標「${activeTarget}」`,
                        `  A: ${data.factor_a}（中位=${data.a_median}）  B: ${data.factor_b}（中位=${data.b_median}）`,
                    ];
                    cells.forEach(c => {
                        const dir = c.r != null ? (c.r > 0.05 ? '正相關' : c.r < -0.05 ? '負相關' : '無相關') : '—';
                        lines.push(`  [${c.label.replace('_Low','↓').replace('_High','↑')}] n=${c.n}  r=${_sr(c.r)}  → ${dir}`);
                    });
                    const aSplits = data.a_splits || [
                        { label: 'A低', range_min: data.a_min ?? '?', range_max: data.a_median ?? '?' },
                        { label: 'A高', range_min: data.a_median ?? '?', range_max: data.a_max ?? '?' },
                    ];
                    const bSplits = data.b_splits || [
                        { label: 'B低', range_min: data.b_min ?? '?', range_max: data.b_median ?? '?' },
                        { label: 'B高', range_min: data.b_median ?? '?', range_max: data.b_max ?? '?' },
                    ];
                    const key = `${term.name}||trellis||${activeTarget}`;
                    const entry = {
                        key, text: lines.join('\n'), fisherP: 1.0,
                        termName: term.name, condVar: data.factor_a,
                        isTrellis: true, cells,
                        trellisData: {
                            factor_a: data.factor_a, factor_b: data.factor_b, factor_c: data.factor_c,
                            a_median: data.a_median, b_median: data.b_median,
                            nA: aSplits.length, nB: bSplits.length,
                            aSplits, bSplits,
                        },
                    };
                    const idx = window._rsmConditionalHistory.findIndex(e => e.key === key);
                    if (idx >= 0) window._rsmConditionalHistory[idx] = entry;
                    else window._rsmConditionalHistory.push(entry);
                })();
                return;
            }
            if (!res.ok) throw new Error(data.detail || '載入失敗');

            if (plotTitle) plotTitle.textContent = `條件式：${_truncateName(term.name, 24)} [依 ${data.condition_var.substring(0, 10)}…]`;

            // Destroy old cond charts
            _rsmCondCharts.forEach(c => { try { c.destroy(); } catch(e) {} });
            _rsmCondCharts = [];

            const groupColors = ['#3b82f6', '#f59e0b', '#10b981', '#8b5cf6', '#ec4899'];
            const groupBg = ['#3b82f633', '#f59e0b33', '#10b98133', '#8b5cf633', '#ec489933'];

            // r range verdict
            const rVals = data.groups.map(g => g.r);
            const rRange = Math.max(...rVals) - Math.min(...rVals);
            const verdictColor = rRange > 0.3 ? '#dc2626' : rRange > 0.1 ? '#f59e0b' : '#94a3b8';
            const verdictText = rRange > 0.3 ? '交互顯著' : rRange > 0.1 ? '輕微交互' : '無明顯交互';

            const isCatCond = data.bg_type === 'categorical';
            const nGroups = data.groups.length;
            const condSubtitle = isCatCond
                ? data.groups.map((g, gi) => `<span style="background:${groupBg[gi % groupBg.length]};color:${groupColors[gi % groupColors.length]};border-radius:3px;padding:1px 6px;font-size:11px;">${g.label}</span>`).join(' ')
                : `Low≤${data.p33} Mid≤${data.p67}`;

            const colW = 220;
            const gridW = nGroups * colW + (nGroups - 1) * 6;

            // ★ Measure available width BEFORE adding wide content, then lock condDiv
            const availW = condDiv.clientWidth || condDiv.parentElement?.clientWidth || 600;
            condDiv.style.width = availW + 'px';
            condDiv.style.maxWidth = availW + 'px';
            // Use flex-column so header stays at top, grid fills remaining height
            condDiv.style.display = 'flex';
            condDiv.style.flexDirection = 'column';

            let html = `<div style="display:flex;justify-content:space-between;align-items:center;padding:2px 0 6px;font-size:12px;color:#64748b;white-space:nowrap;flex-shrink:0;">
                <span>條件: <b style="color:#1e293b;">${data.condition_var.substring(0,22)}</b> &nbsp; ${condSubtitle}</span>
                <span style="display:flex;align-items:center;gap:6px;">
                    <b style="color:${verdictColor};">${verdictText} (Δr=${rRange.toFixed(2)})</b>
                    <button onclick="window._rsmCondExpand()" style="padding:2px 8px;font-size:10px;border:1px solid #e2e8f0;border-radius:4px;background:#f8fafc;cursor:pointer;color:#475569;">⛶ 放大</button>
                </span>
            </div>`;
            html += `<div style="display:grid;grid-template-columns:repeat(${nGroups},${colW}px);gap:6px;width:${gridW}px;flex:1;min-height:0;">`;
            data.groups.forEach((g, gi) => {
                const gc = groupColors[gi % groupColors.length];
                const rColor = Math.abs(g.r ?? 0) > 0.5 ? ((g.r ?? 0) > 0 ? '#16a34a' : '#dc2626') : '#64748b';
                const sig = (g.p_value ?? 1) < 0.05 ? '✓' : '';
                const condRange = (!isCatCond && g.cond_min != null && g.cond_max != null)
                    ? `<div style="font-size:10px;color:#94a3b8;margin-bottom:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="${data.condition_var}: ${g.cond_min} ~ ${g.cond_max}">${data.condition_var.substring(0,16)}: <b style="color:${gc};">${g.cond_min} ~ ${g.cond_max}</b></div>`
                    : '';
                html += `<div style="display:flex;flex-direction:column;border:1px solid #e2e8f0;border-radius:6px;padding:8px;background:#fafafa;">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:2px;">
                        <span style="font-size:13px;font-weight:700;color:${gc};">${g.label} (${g.n})</span>
                        <span style="font-size:13px;font-family:monospace;color:${rColor};font-weight:600;">r=${_safeR(g.r,2)}${sig}</span>
                    </div>
                    ${condRange}
                    <div style="font-size:11px;color:#64748b;margin-bottom:4px;" id="rsm-cond-beta-${gi}"></div>
                    <div style="flex:1;min-height:0;position:relative;"><canvas id="rsm-cond-canvas-${gi}"></canvas></div>
                </div>`;
            });
            html += `</div>`;
            condDiv.innerHTML = html;

            // store for expand
            window._rsmCondData = { data, term, activeTarget, groupColors, groupBg, body, sid };
            // Accumulate conditional entries for notebook auto-pack
            (() => {
                const rVals = data.groups.map(g => g.r);
                const nVals = data.groups.map(g => g.n);
                const rMax = Math.max(...rVals), rMin = Math.min(...rVals);
                const rRange = rMax - rMin;
                const verdict = rRange > 0.3 ? '交互顯著' : rRange > 0.1 ? '輕微交互' : '無明顯交互';
                const _sr = v => (v >= 0 ? '+' : '') + v.toFixed(3);
                const p33 = data.p33, p67 = data.p67, cv = data.condition_var;
                const isCatCondNote = data.bg_type === 'categorical';
                const _range = (g) => {
                    if (isCatCondNote) return g.label;
                    const lo = g.label.toLowerCase();
                    if (lo === 'low')  return `${cv} ≤ ${p33}`;
                    if (lo === 'mid')  return `${p33} < ${cv} ≤ ${p67}`;
                    if (lo === 'high') return `${cv} > ${p67}`;
                    return g.label;
                };

                // Fisher Z 檢定：compare first vs last group
                const _fisherZ = (r) => 0.5 * Math.log((1 + r) / (1 - Math.max(-0.9999, Math.min(0.9999, r))));
                const gFirst = data.groups[0];
                const gLast  = data.groups[data.groups.length - 1];
                let fisherP = 1;
                if (gFirst && gLast && gFirst !== gLast && gFirst.n > 3 && gLast.n > 3) {
                    const zDiff = _fisherZ(gLast.r) - _fisherZ(gFirst.r);
                    const se = Math.sqrt(1 / (gFirst.n - 3) + 1 / (gLast.n - 3));
                    const zStat = Math.abs(zDiff / se);
                    const erfApprox = (x) => {
                        const t = 1 / (1 + 0.3275911 * x);
                        return 1 - (0.254829592*t - 0.284496736*t*t + 1.421413741*t*t*t
                            - 1.453152027*t*t*t*t + 1.061405429*t*t*t*t*t) * Math.exp(-x*x);
                    };
                    fisherP = 2 * (1 - 0.5 * (1 + erfApprox(zStat / Math.sqrt(2))));
                }
                const interSig = fisherP < 0.05 ? '★ 顯著' : fisherP < 0.1 ? '△ 邊緣顯著' : '○ 不顯著';
                const condDesc = isCatCondNote
                    ? `分 ${data.groups.length} 類：${data.groups.map(g => g.label).join(' / ')}`
                    : `分三組，閾值 p33=${p33}，p67=${p67}`;

                const lines = [
                    `條件式分析：「${term.name}」對「${activeTarget}」的相關係數，隨條件因子改變`,
                    `  條件因子: ${cv}（${condDesc}）`,
                    `  交互顯著性: ${interSig}（Fisher Z，p=${fisherP < 0.001 ? '<0.001' : fisherP.toFixed(3)}）`,
                ];
                data.groups.forEach(g => {
                    const sig = g.p_value < 0.05 ? '（p<0.05 顯著）' : '（n.s.）';
                    const dir = g.r > 0.05 ? '正相關' : g.r < -0.05 ? '負相關' : '無相關';
                    lines.push(`  ${g.label}（${_range(g)}, n=${g.n}）: r = ${_sr(g.r)}  → ${dir} ${sig}`);
                });
                lines.push(`  Δr = ${rRange.toFixed(3)}  ${verdict}`);
                const pos = data.groups.filter(g => g.r > 0.05).length;
                const neg = data.groups.filter(g => g.r < -0.05).length;
                if (pos > 0 && neg > 0) lines.push(`  ⚠ 方向反轉：在不同條件下正負相關並存`);

                // 累積到 history（依 termName + condVar 去重，相同組合更新）
                if (!window._rsmConditionalHistory) window._rsmConditionalHistory = [];
                const key = `${term.name}||${cv}||${activeTarget}`;
                const existing = window._rsmConditionalHistory.findIndex(e => e.key === key);
                const entry = { key, text: lines.join('\n'), fisherP, termName: term.name, condVar: cv, groups: data.groups };
                if (existing >= 0) window._rsmConditionalHistory[existing] = entry;
                else window._rsmConditionalHistory.push(entry);
            })();

            // Draw charts after DOM update
            await new Promise(r => setTimeout(r, 0));

            // Compute global X/Y range across all groups for axis sync
            const allGX = data.groups.flatMap(g => g.x);
            const allGY = data.groups.flatMap(g => g.y);
            const gxMin = Math.min(...allGX), gxMax = Math.max(...allGX);
            const gyMin = Math.min(...allGY), gyMax = Math.max(...allGY);
            const gxPad = (gxMax - gxMin) * 0.08 || 0.5;
            const gyPad = (gyMax - gyMin) * 0.08 || 0.5;
            const syncXMin = gxMin - gxPad, syncXMax = gxMax + gxPad;
            const syncYMin = gyMin - gyPad, syncYMax = gyMax + gyPad;

            const groupSlopes = [];
            data.groups.forEach((g, gi) => {
                const canvas = document.getElementById(`rsm-cond-canvas-${gi}`);
                if (!canvas || g.x.length < 2) { groupSlopes.push(null); return; }
                const points = g.x.map((x, i) => ({ x, y: g.y[i] }));
                const n = points.length;
                const sumX = points.reduce((a, b) => a + b.x, 0);
                const sumY = points.reduce((a, b) => a + b.y, 0);
                const sumXY = points.reduce((a, b) => a + b.x * b.y, 0);
                const sumXX = points.reduce((a, b) => a + b.x * b.x, 0);
                const slope = (n * sumXY - sumX * sumY) / (n * sumXX - sumX * sumX) || 0;
                groupSlopes.push(slope);
                const intercept = (sumY - slope * sumX) / n;
                const gxMinG = Math.min(...g.x), gxMaxG = Math.max(...g.x);


                const chart = new Chart(canvas.getContext('2d'), {
                    type: 'scatter',
                    data: { datasets: [
                        { data: points, backgroundColor: groupBg[gi % groupBg.length], borderColor: groupColors[gi % groupColors.length], borderWidth: 1, pointRadius: 3 },
                        { data: [{ x: gxMinG, y: slope * gxMinG + intercept }, { x: gxMaxG, y: slope * gxMaxG + intercept }],
                          type: 'line', borderColor: groupColors[gi % groupColors.length], borderWidth: 2, fill: false, pointRadius: 0, showLine: true }
                    ]},
                    options: {
                        responsive: true, maintainAspectRatio: false, animation: { duration: 200 },
                        plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => `X:${c.parsed.x.toFixed(2)}, Y:${c.parsed.y.toFixed(2)}` } } },
                        scales: {
                            x: { min: syncXMin, max: syncXMax, title: { display: true, text: data.x_label.substring(0, 24), font: { size: 12 } }, ticks: { font: { size: 11 }, maxTicksLimit: 5 }, grid: { color: '#f1f5f9' } },
                            y: { min: syncYMin, max: syncYMax, title: { display: true, text: activeTarget.substring(0, 16), font: { size: 12 } }, ticks: { font: { size: 11 }, maxTicksLimit: 5 }, grid: { color: '#f1f5f9' } },
                        },
                    }
                });
                _rsmCondCharts.push(chart);
            });

            // Stats bar: β comparison + sign flip detection
            if (statsEl) {
                const validSlopes = groupSlopes.filter(s => s !== null);
                const signs = validSlopes.map(s => s > 0 ? 1 : s < 0 ? -1 : 0);
                const signFlip = signs.some(s => s !== signs[0] && s !== 0);
                const labels = ['Low', 'Mid', 'High'];
                const flipWarn = signFlip ? `<span style="color:#dc2626;font-weight:700;">⚠ 斜率方向相反</span>` : '';
                statsEl.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:4px;font-size:10px;">
                    <span>${flipWarn}</span>
                    <span><span style="color:#94a3b8;">✓=p&lt;0.05</span></span>
                </div>`;
            }

        } catch (err) {
            if (condDiv) condDiv.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#ef4444;font-size:12px;">❌ ${err.message}</div>`;
        }
    }

    let _rsmTrellisCharts = [];
    let _rsmTrellisAGroups = 2;
    let _rsmTrellisBGroups = 2;
    let _rsmTrellisShowNodeCharts = false;
    let _rsmTrellisLastData = null; // cached for re-render

    window._rsmTrellisSetGroups = async function(which, n) {
        if (which === 'a') _rsmTrellisAGroups = n;
        else _rsmTrellisBGroups = n;
        const d = window._rsmCondData;
        if (!d || !d.isTrellis) return;
        const newBody = { ...d.body, a_groups: _rsmTrellisAGroups, b_groups: _rsmTrellisBGroups };
        const condDiv = document.getElementById('rsm-cond-scatter');
        const statsEl = document.getElementById('rsm-plot-stats');
        const plotTitle = document.getElementById('rsm-plot-title');
        if (condDiv) condDiv.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#94a3b8;font-size:12px;">載入中...</div>';
        try {
            const res = await fetch(`/api/data-prep/rsm-trellis-data?session_id=${d.sid}`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(newBody)
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || '載入失敗');
            _rsmTrellisTreeMode = false;
            _rsmTrellisLastData = data;
            _rsmRenderTrellis(data, d.activeTarget, condDiv, statsEl, plotTitle);
            window._rsmCondData = { ...d, data, body: newBody };
        } catch(e) {
            if (condDiv) condDiv.innerHTML = `<div style="padding:20px;color:#ef4444;">❌ ${e.message}</div>`;
        }
    };

    window._rsmTrellisToggleNodeCharts = function() {
        _rsmTrellisShowNodeCharts = !_rsmTrellisShowNodeCharts;
        if (_rsmTrellisTreeMode && _rsmTrellisLastData) {
            const body = document.getElementById('rsm-trellis-body');
            if (body) body.innerHTML = _rsmBuildTreeHTML(_rsmTrellisLastData, window._rsmCondData?.activeTarget);
        }
    };

    function _rsmRenderTrellis(data, activeTarget, condDiv, statsEl, plotTitle) {
        if (plotTitle) plotTitle.textContent = `2×2 切片：${data.factor_a.substring(0,10)} × ${data.factor_b.substring(0,10)} | C=${data.factor_c.substring(0,10)}`;

        _rsmTrellisCharts.forEach(c => { try { c.destroy(); } catch(e) {} });
        _rsmTrellisCharts = [];

        const nA = data.a_splits?.length || 2;
        const nB = data.b_splits?.length || 2;
        const nCells = data.cells.length;
        // Generate enough colors for nA*nB cells
        const allColors = ['#6366f1','#0ea5e9','#f59e0b','#10b981','#ec4899','#8b5cf6','#14b8a6','#f97316','#06b6d4'];
        const quadColors = data.cells.map((_, i) => allColors[i % allColors.length]);
        const quadBg = quadColors.map(c => c + '33');

        const isSquared = !!data.is_squared;
        _rsmTrellisLastData = data;
        const swapBtnStyle = 'padding:2px 7px;font-size:10px;border:1px solid #e2e8f0;border-radius:4px;background:#f8fafc;cursor:pointer;color:#475569;white-space:nowrap;';
        const grpBtnBase = 'padding:2px 6px;font-size:10px;border:1px solid #cbd5e1;border-radius:4px;background:#fff;color:#475569;cursor:pointer;';
        const grpBtnActive = 'padding:2px 6px;font-size:10px;border:1px solid #6366f1;border-radius:4px;background:#ede9fe;color:#6366f1;font-weight:700;cursor:pointer;';
        const ncBtnStyle = _rsmTrellisShowNodeCharts
            ? 'padding:2px 8px;font-size:10px;border:1px solid #6366f1;border-radius:4px;background:#ede9fe;color:#6366f1;font-weight:700;cursor:pointer;'
            : swapBtnStyle;
        const groupControls = isSquared ? '' : `
            <span style="font-size:10px;color:#94a3b8;">A 組數：</span>
            <button style="${_rsmTrellisAGroups===2?grpBtnActive:grpBtnBase}" onclick="window._rsmTrellisSetGroups('a',2)">2</button>
            <button style="${_rsmTrellisAGroups===3?grpBtnActive:grpBtnBase}" onclick="window._rsmTrellisSetGroups('a',3)">3</button>
            <span style="font-size:10px;color:#94a3b8;margin-left:4px;">B 組數：</span>
            <button style="${_rsmTrellisBGroups===2?grpBtnActive:grpBtnBase}" onclick="window._rsmTrellisSetGroups('b',2)">2</button>
            <button style="${_rsmTrellisBGroups===3?grpBtnActive:grpBtnBase}" onclick="window._rsmTrellisSetGroups('b',3)">3</button>`;
        let html = `<div style="display:flex;justify-content:space-between;align-items:center;padding:2px 0 6px;font-size:11px;color:#64748b;flex-shrink:0;flex-wrap:wrap;gap:4px;">
            <span>${isSquared
                ? `A²=<b style="color:#6366f1;">${data.factor_a.substring(0,16)}</b>（自乘，三分位切割）`
                : `A=<b style="color:#6366f1;">${data.factor_a.substring(0,16)}</b> &nbsp; B=<b style="color:#0ea5e9;">${data.factor_b.substring(0,16)}</b>`
            } &nbsp; C（X軸）=<b style="color:#1e293b;">${data.factor_c.substring(0,16)}</b></span>
            <span style="display:flex;gap:4px;align-items:center;flex-wrap:wrap;">
                <button onclick="window._rsmTrellisSwap('AB')" style="${swapBtnStyle}" title="交換 A 和 B（切換分組方式）">⇄ A↔B</button>
                <button onclick="window._rsmTrellisSwap('AC')" style="${swapBtnStyle}" title="交換 A 和 C（A 變 X 軸）">⇄ A↔C</button>
                <button onclick="window._rsmTrellisSwap('BC')" style="${swapBtnStyle}" title="交換 B 和 C（B 變 X 軸）">⇄ B↔C</button>
                ${groupControls}
                <button onclick="window._rsmTrellisToggleNodeCharts()" style="${ncBtnStyle}">節點趨勢圖</button>
                <button onclick="window._rsmTrellisToggleTree()" id="rsm-trellis-tree-btn" style="padding:2px 8px;font-size:11px;border:1px solid #e2e8f0;border-radius:4px;background:#f8fafc;cursor:pointer;color:#475569;">🌳 樹狀圖</button>
                <button onclick="window._rsmCondExpand()" style="padding:2px 8px;font-size:11px;border:1px solid #e2e8f0;border-radius:4px;background:#f8fafc;cursor:pointer;color:#475569;">⛶ 放大</button>
            </span>
        </div>
        <div id="rsm-trellis-body" style="flex:1;min-height:0;overflow:auto;">
        <div style="display:grid;grid-template-columns:repeat(${isSquared ? 3 : nB},1fr);gap:6px;height:100%;">`;

        data.cells.forEach((cell, ci) => {
            const rColor = Math.abs(cell.r ?? 0) > 0.4 ? ((cell.r ?? 0) > 0 ? '#16a34a' : '#dc2626') : '#64748b';
            const sig = (cell.p_value ?? 1) < 0.05 ? '✓' : '';
            const bColor = (cell.slope ?? 0) > 0 ? '#16a34a' : (cell.slope ?? 0) < 0 ? '#dc2626' : '#94a3b8';
            html += `<div style="display:flex;flex-direction:column;border:1px solid #e2e8f0;border-radius:6px;padding:4px;background:#fafafa;">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1px;">
                    <span style="font-size:9px;font-weight:700;color:${quadColors[ci]};">${cell.label.replace('_Low','↓').replace('_High','↑')} (${cell.n})</span>
                    <span style="font-size:9px;font-family:monospace;color:${rColor};">r=${_safeR(cell.r,2)}${sig}</span>
                </div>
                <div style="font-size:9px;color:#64748b;margin-bottom:1px;" id="rsm-trellis-beta-${ci}">β=<b style="color:${bColor};">${_fmtSlope(cell.slope)}</b></div>
                <div style="flex:1;min-height:0;position:relative;"><canvas id="rsm-trellis-canvas-${ci}"></canvas></div>
            </div>`;
        });
        html += `</div></div>`;
        condDiv.innerHTML = html;

        setTimeout(() => {
            data.cells.forEach((cell, ci) => {
                const canvas = document.getElementById(`rsm-trellis-canvas-${ci}`);
                if (!canvas || cell.x.length < 2) return;
                const points = cell.x.map((x, i) => ({ x, y: cell.y[i] }));
                const n = points.length;
                const sX = points.reduce((a,b) => a+b.x, 0), sY = points.reduce((a,b) => a+b.y, 0);
                const sXY = points.reduce((a,b) => a+b.x*b.y, 0), sXX = points.reduce((a,b) => a+b.x*b.x, 0);
                const slope = (n*sXY - sX*sY)/(n*sXX - sX*sX) || 0;
                const intercept = (sY - slope*sX)/n;
                const xMin = Math.min(...cell.x), xMax = Math.max(...cell.x);
                const chart = new Chart(canvas.getContext('2d'), {
                    type: 'scatter',
                    data: { datasets: [
                        { data: points, backgroundColor: quadBg[ci], borderColor: quadColors[ci], borderWidth: 1, pointRadius: 3 },
                        { data: [{ x: xMin, y: slope*xMin+intercept },{ x: xMax, y: slope*xMax+intercept }],
                          type: 'line', borderColor: quadColors[ci], borderWidth: 2, fill: false, pointRadius: 0, showLine: true }
                    ]},
                    options: {
                        responsive: true, maintainAspectRatio: false, animation: { duration: 150 },
                        plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => `C:${c.parsed.x.toFixed(2)}, Y:${c.parsed.y.toFixed(2)}` } } },
                        scales: {
                            x: { title: { display: true, text: data.factor_c.substring(0,14), font: { size: 8 } }, ticks: { font: { size: 8 }, maxTicksLimit: 4 }, grid: { color: '#f1f5f9' } },
                            y: { title: { display: true, text: activeTarget.substring(0,10), font: { size: 8 } }, ticks: { font: { size: 8 }, maxTicksLimit: 4 }, grid: { color: '#f1f5f9' } },
                        }
                    }
                });
                _rsmTrellisCharts.push(chart);
            });
        }, 0);

        // Stats: detect if slope direction changes across cells
        if (statsEl) {
            const slopes = data.cells.map(c => c.slope);
            const signs = slopes.map(s => s > 0 ? 1 : s < 0 ? -1 : 0).filter(s => s !== 0);
            const flip = signs.length > 1 && signs.some(s => s !== signs[0]);
            const betaRow = data.cells.map((c, ci) => {
                const bc = c.slope > 0 ? '#16a34a' : c.slope < 0 ? '#dc2626' : '#94a3b8';
                const lbl = c.label.replace('A_低','A↓').replace('A_中','A→').replace('A_高','A↑')
                                   .replace('B_低','B↓').replace('B_中','B→').replace('B_高','B↑')
                                   .replace(' · ','');
                return `<span style="color:${quadColors[ci]};">${lbl}</span> β=<b style="color:${bc};">${_fmtSlope(c.slope)}</b>`;
            }).join(' &nbsp; ');
            const warn = flip ? `<span style="color:#dc2626;font-weight:700;">⚠ 三階交互存在</span>` : `<span style="color:#94a3b8;">斜率方向一致</span>`;
            statsEl.innerHTML = `<div style="display:flex;justify-content:space-between;font-size:10px;flex-wrap:wrap;gap:4px;">
                <span>${betaRow}</span><span>${warn}</span></div>`;
        }
    }

    let _rsmTrellisTreeMode = false;

    window._rsmTrellisSwap = async function(pair) {
        const d = window._rsmCondData;
        if (!d || !d.isTrellis) return;
        // Reorder factors: [A, B, C]
        let factors = [...d.body.factors];
        if (pair === 'AB') { [factors[0], factors[1]] = [factors[1], factors[0]]; }
        else if (pair === 'AC') { [factors[0], factors[2]] = [factors[2], factors[0]]; }
        else if (pair === 'BC') { [factors[1], factors[2]] = [factors[2], factors[1]]; }

        const newBody = { ...d.body, factors, a_groups: _rsmTrellisAGroups, b_groups: _rsmTrellisBGroups };
        const condDiv = document.getElementById('rsm-cond-scatter');
        const statsEl = document.getElementById('rsm-plot-stats');
        const plotTitle = document.getElementById('rsm-plot-title');
        if (condDiv) condDiv.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#94a3b8;font-size:12px;">載入中...</div>';

        try {
            const res = await fetch(`/api/data-prep/rsm-trellis-data?session_id=${d.sid}`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(newBody)
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || '載入失敗');
            _rsmTrellisTreeMode = false;
            _rsmTrellisLastData = data;
            _rsmRenderTrellis(data, d.activeTarget, condDiv, statsEl, plotTitle);
            window._rsmCondData = { ...d, data, body: newBody };
        } catch(e) {
            if (condDiv) condDiv.innerHTML = `<div style="padding:20px;color:#ef4444;">❌ ${e.message}</div>`;
        }
    };

    window._rsmTrellisToggleTree = function() {
        _rsmTrellisTreeMode = !_rsmTrellisTreeMode;
        const btn = document.getElementById('rsm-trellis-tree-btn');
        const body = document.getElementById('rsm-trellis-body');
        if (!body || !window._rsmCondData?.isTrellis) return;
        const data = window._rsmCondData.data;
        if (_rsmTrellisTreeMode) {
            if (btn) { btn.style.background = '#6366f1'; btn.style.color = '#fff'; btn.style.borderColor = '#6366f1'; }
            body.innerHTML = _rsmBuildTreeHTML(data, window._rsmCondData.activeTarget);
        } else {
            if (btn) { btn.style.background = '#f8fafc'; btn.style.color = '#475569'; btn.style.borderColor = '#e2e8f0'; }
            // Re-render scatter grids
            _rsmRenderTrellis(data, window._rsmCondData.activeTarget,
                document.getElementById('rsm-cond-scatter'),
                document.getElementById('rsm-plot-stats'),
                document.getElementById('rsm-plot-title'));
            _rsmTrellisTreeMode = false; // reset since _rsmRenderTrellis rebuilds HTML
        }
    };

    function _rsmBuildTreeHTML(data, activeTarget) {
        const cells = data.cells;
        if (data.is_squared) return _rsmBuildTreeHTMLSquared(data, activeTarget);

        const aSplits = data.a_splits || [{ label:'低', range_min: data.a_min, range_max: data.a_median }, { label:'高', range_min: data.a_median, range_max: data.a_max }];
        const bSplits = data.b_splits || [{ label:'低', range_min: data.b_min, range_max: data.b_median }, { label:'高', range_min: data.b_median, range_max: data.b_max }];
        const nA = aSplits.length, nB = bSplits.length;

        const allColors = ['#6366f1','#0ea5e9','#f59e0b','#10b981','#ec4899','#8b5cf6','#14b8a6','#f97316','#06b6d4'];
        const aPalettes = [['#6366f1','#0ea5e9'],['#f59e0b','#10b981'],['#ec4899','#8b5cf6']];
        const leafColors = cells.map((_, i) => allColors[i % allColors.length]);
        const leafBgs = leafColors.map(c => c + '20');

        const aName = data.factor_a.substring(0, 22);
        const bName = data.factor_b.substring(0, 22);
        const cName = data.factor_c.substring(0, 26);
        const yName = (activeTarget || '目標').substring(0, 22);

        function fmtR(v) { if (v == null || isNaN(v)) return '—'; return (Math.abs(v) >= 1000 || (v !== 0 && Math.abs(v) < 0.01)) ? v.toFixed(2) : Number(v.toPrecision(4)).toString(); }

        // Sync axes (filter nulls)
        const allX = cells.flatMap(c => (c.x||[]).filter(v=>v!=null&&!isNaN(v))), allY = cells.flatMap(c => (c.y||[]).filter(v=>v!=null&&!isNaN(v)));
        const gXMin = Math.min(...allX), gXMax = Math.max(...allX);
        const gYMin = Math.min(...allY), gYMax = Math.max(...allY);
        const padX = (gXMax - gXMin) * 0.08 || 0.1, padY = (gYMax - gYMin) * 0.08 || 0.1;
        const syncXMin = gXMin - padX, syncXMax = gXMax + padX;
        const syncYMin = gYMin - padY, syncYMax = gYMax + padY;

        function drawNodeChart(canvasId, px, py, color, xMinOverride, xMaxOverride) {
            const canvas = document.getElementById(canvasId);
            if (!canvas || px.length < 2) return;
            const points = px.map((x, i) => ({ x, y: py[i] }));
            const n = points.length;
            const sX = points.reduce((a,b)=>a+b.x,0), sY = points.reduce((a,b)=>a+b.y,0);
            const sXY = points.reduce((a,b)=>a+b.x*b.y,0), sXX = points.reduce((a,b)=>a+b.x*b.x,0);
            const slope = (n*sXY-sX*sY)/(n*sXX-sX*sX) || 0;
            const intercept = (sY-slope*sX)/n;
            const lxMin = Math.min(...px), lxMax = Math.max(...px);
            const xMin = xMinOverride !== undefined ? xMinOverride : lxMin;
            const xMax = xMaxOverride !== undefined ? xMaxOverride : lxMax;
            new Chart(canvas.getContext('2d'), {
                type: 'scatter',
                data: { datasets: [
                    { data: points, backgroundColor: color+'30', borderColor: color, borderWidth: 1, pointRadius: 3 },
                    { data: [{x:lxMin,y:slope*lxMin+intercept},{x:lxMax,y:slope*lxMax+intercept}],
                      type:'line', borderColor:color, borderWidth:2, fill:false, pointRadius:0, showLine:true }
                ]},
                options: { responsive:true, maintainAspectRatio:false, animation:{duration:0},
                    plugins:{legend:{display:false}},
                    scales:{ x:{min:xMin,max:xMax,ticks:{font:{size:8},maxTicksLimit:3},grid:{color:'#f1f5f9'}},
                             y:{min:syncYMin,max:syncYMax,ticks:{font:{size:8},maxTicksLimit:3},grid:{color:'#f1f5f9'}} }}
            });
        }

        // Pre-compute A and B axis sync ranges for node charts
        const allAX = cells.flatMap(c => c.a_x || []);
        const allBX = cells.flatMap(c => c.b_x || []);
        const aXMin = allAX.length ? Math.min(...allAX) - (Math.max(...allAX)-Math.min(...allAX))*0.08 : syncXMin;
        const aXMax = allAX.length ? Math.max(...allAX) + (Math.max(...allAX)-Math.min(...allAX))*0.08 : syncXMax;
        const bXMin = allBX.length ? Math.min(...allBX) - (Math.max(...allBX)-Math.min(...allBX))*0.08 : syncXMin;
        const bXMax = allBX.length ? Math.max(...allBX) + (Math.max(...allBX)-Math.min(...allBX))*0.08 : syncXMax;

        setTimeout(() => {
            cells.forEach((cell, ci) => {
                const canvas = document.getElementById(`rsm-tree-canvas-${ci}`);
                if (!canvas || cell.x.length < 2) return;
                const points = cell.x.map((x, i) => ({ x, y: cell.y[i] }));
                const n = points.length;
                const sX = points.reduce((a,b)=>a+b.x,0), sY = points.reduce((a,b)=>a+b.y,0);
                const sXY = points.reduce((a,b)=>a+b.x*b.y,0), sXX = points.reduce((a,b)=>a+b.x*b.x,0);
                const slope = (n*sXY-sX*sY)/(n*sXX-sX*sX) || 0;
                const intercept = (sY-slope*sX)/n;
                const gxMin = Math.min(...cell.x), gxMax = Math.max(...cell.x);
                new Chart(canvas.getContext('2d'), {
                    type: 'scatter',
                    data: { datasets: [
                        { data: points, backgroundColor: leafBgs[ci], borderColor: leafColors[ci], borderWidth:1, pointRadius:4 },
                        { data: [{x:gxMin,y:slope*gxMin+intercept},{x:gxMax,y:slope*gxMax+intercept}],
                          type:'line', borderColor:leafColors[ci], borderWidth:2, fill:false, pointRadius:0, showLine:true }
                    ]},
                    options: { responsive:true, maintainAspectRatio:false, animation:{duration:150},
                        plugins:{legend:{display:false}, tooltip:{callbacks:{label:c=>`C:${c.parsed.x.toFixed(2)}, Y:${c.parsed.y.toFixed(2)}`}}},
                        scales:{ x:{min:syncXMin,max:syncXMax,ticks:{font:{size:9},maxTicksLimit:4},grid:{color:'#f1f5f9'}},
                                 y:{min:syncYMin,max:syncYMax,ticks:{font:{size:9},maxTicksLimit:4},grid:{color:'#f1f5f9'}} }}
                });
            });
            if (_rsmTrellisShowNodeCharts) {
                // A node: aggregate all cells in that A group, use A factor values on X
                aSplits.forEach((_, ai) => {
                    const ax = cells.slice(ai*nB, ai*nB+nB).flatMap(c => c.a_x || c.x);
                    const ay = cells.slice(ai*nB, ai*nB+nB).flatMap(c => c.y);
                    drawNodeChart(`rsm-tree-anode-${ai}`, ax, ay, aPalettes[ai % 3][0], aXMin, aXMax);
                });
                // B node: use B factor values on X
                cells.forEach((cell, ci) => drawNodeChart(`rsm-tree-bnode-${ci}`, cell.b_x || cell.x, cell.y, leafColors[ci], bXMin, bXMax));
            }
        }, 0);

        function leafCard(cell, ci) {
            const sig = (cell.p_value ?? 1) < 0.05 ? ' ✓' : '';
            const bColor = (cell.slope ?? 0) > 0 ? '#16a34a' : (cell.slope ?? 0) < 0 ? '#dc2626' : '#94a3b8';
            const rColor = Math.abs(cell.r ?? 0) > 0.4 ? bColor : '#64748b';
            return `<div style="background:#fff;border:2px solid ${leafColors[ci]};border-radius:10px;padding:8px 12px;min-width:220px;max-width:260px;box-shadow:0 2px 8px #0001;">
                <div style="font-size:10px;color:#94a3b8;margin-bottom:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${cName}">X: ${cName}</div>
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:3px;">
                    <span style="font-size:11px;color:#64748b;">n = ${cell.n}</span>
                    <span style="font-size:11px;color:${rColor};font-weight:600;">r = ${_safeR(cell.r,3)}${sig}</span>
                </div>
                <div style="font-size:14px;font-weight:700;color:${bColor};margin-bottom:1px;">${(cell.slope ?? 0) > 0 ? '+' : ''}${_fmtSlope(cell.slope)}</div>
                <div style="font-size:10px;color:#94a3b8;margin-bottom:6px;">β（C 對 Y 斜率）</div>
                <div style="height:130px;position:relative;"><canvas id="rsm-tree-canvas-${ci}"></canvas></div>
            </div>`;
        }

        function nodeCard(label, name, range, color, canvasId) {
            return `<div style="background:#fff;border:2px solid ${color};border-radius:10px;padding:8px 12px;min-width:220px;max-width:260px;box-shadow:0 2px 8px #0001;">
                <div style="font-size:10px;color:#94a3b8;margin-bottom:2px;">${label}</div>
                <div style="font-size:10px;font-weight:700;color:${color};overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-bottom:1px;" title="${name}">${name}</div>
                <div style="font-size:10px;color:${color};font-weight:600;margin-bottom:4px;">${range}</div>
                <div style="height:130px;position:relative;"><canvas id="${canvasId}"></canvas></div>
            </div>`;
        }

        const showNC = _rsmTrellisShowNodeCharts;

        return `<div style="display:flex;align-items:stretch;justify-content:center;height:100%;padding:12px 8px;gap:0;overflow:auto;">
            <div style="display:flex;flex-direction:column;justify-content:center;align-items:center;padding:0 12px;">
                <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:8px 12px;text-align:center;max-width:110px;">
                    <div style="font-size:10px;color:#94a3b8;margin-bottom:2px;">目標（Y）</div>
                    <div style="font-size:11px;font-weight:700;color:#1e293b;">${yName}</div>
                    <div style="font-size:9px;color:#94a3b8;margin-top:4px;border-top:1px solid #f1f5f9;padding-top:3px;">X: ${cName}</div>
                </div>
            </div>
            <div style="display:flex;flex-direction:column;justify-content:center;"><div style="width:32px;height:2px;background:#cbd5e1;"></div></div>
            <div style="display:flex;flex-direction:column;justify-content:space-around;gap:20px;">
                ${aSplits.map((asp, ai) => {
                    const aColor = aPalettes[ai % 3][0];
                    const aRange = `${fmtR(asp.range_min)} ~ ${fmtR(asp.range_max)}`;
                    const aNodeHtml = showNC
                        ? nodeCard(`A ${asp.label}`, aName, aRange, aColor, `rsm-tree-anode-${ai}`)
                        : `<div style="display:flex;flex-direction:column;align-items:center;padding:0 12px;">
                            <div style="font-size:10px;color:#94a3b8;">A ${asp.label}</div>
                            <div style="font-size:11px;font-weight:700;color:${aColor};max-width:90px;text-align:center;word-break:break-all;">${aName}</div>
                            <div style="font-size:10px;color:${aColor};font-weight:600;">${aRange}</div>
                          </div>`;
                    return `<div style="display:flex;align-items:center;gap:0;">
                        ${aNodeHtml}
                        <div style="width:32px;height:2px;background:#cbd5e1;"></div>
                        <div style="display:flex;flex-direction:column;gap:16px;">
                            ${bSplits.map((bsp, bi) => {
                                const ci = ai * nB + bi;
                                const bColor = aPalettes[ai % 3][1];
                                const bRange = `${fmtR(bsp.range_min)} ~ ${fmtR(bsp.range_max)}`;
                                const bNodeHtml = showNC
                                    ? nodeCard(`B ${bsp.label}`, bName, bRange, bColor, `rsm-tree-bnode-${ci}`)
                                    : `<div style="display:flex;flex-direction:column;align-items:center;">
                                        <div style="font-size:10px;color:#94a3b8;">B ${bsp.label}</div>
                                        <div style="font-size:10px;font-weight:600;color:${bColor};">${bName.substring(0,14)}</div>
                                        <div style="font-size:10px;color:${bColor};font-weight:600;">${bRange}</div>
                                      </div>`;
                                return `<div style="display:flex;align-items:center;gap:8px;">
                                    ${bNodeHtml}
                                    <div style="width:20px;height:2px;background:#cbd5e1;"></div>
                                    ${leafCard(cells[ci], ci)}
                                </div>`;
                            }).join('')}
                        </div>
                    </div>`;
                }).join('')}
            </div>
        </div>`;
    }

    function _rsmBuildTreeHTMLSquared(data, activeTarget) {
        const cells = data.cells; // [Low, Mid, High]
        const maxAbs = Math.max(...cells.map(c => Math.abs(c.slope)), 0.0001);
        const colors = ['#3b82f6', '#f59e0b', '#10b981'];
        const bgs = ['#3b82f620', '#f59e0b20', '#10b98120'];
        const labels = ['A 低', 'A 中', 'A 高'];
        const ranges = [
            `${data.a_min} ~ ${data.a_p33}`,
            `${data.a_p33} ~ ${data.a_p67}`,
            `${data.a_p67} ~ ${data.a_max}`,
        ];

        let _sqCharts = [];
        function leafCard(cell, ci) {
            const sig = (cell.p_value ?? 1) < 0.05 ? ' ✓' : '';
            const bColor = (cell.slope ?? 0) > 0 ? '#16a34a' : (cell.slope ?? 0) < 0 ? '#dc2626' : '#94a3b8';
            const rColor = Math.abs(cell.r ?? 0) > 0.4 ? bColor : '#64748b';
            return `<div style="background:#fff;border:2px solid ${colors[ci]};border-radius:10px;padding:8px 12px;min-width:200px;max-width:240px;box-shadow:0 2px 8px #0001;">
                <div style="font-size:10px;color:#94a3b8;margin-bottom:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${cName}">X: ${cName}</div>
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:3px;">
                    <span style="font-size:11px;color:#64748b;">n = ${cell.n}</span>
                    <span style="font-size:11px;color:${rColor};font-weight:600;">r = ${_safeR(cell.r,3)}${sig}</span>
                </div>
                <div style="font-size:14px;font-weight:700;color:${bColor};margin-bottom:1px;">${(cell.slope ?? 0) > 0 ? '+' : ''}${_fmtSlope(cell.slope)}</div>
                <div style="font-size:10px;color:#94a3b8;margin-bottom:6px;">β（C 對 Y 斜率）</div>
                <div style="height:130px;position:relative;"><canvas id="rsm-tree-canvas-sq-${ci}"></canvas></div>
            </div>`;
        }

        const allX = cells.flatMap(c => c.x);
        const allY = cells.flatMap(c => c.y);
        const gXMin = Math.min(...allX), gXMax = Math.max(...allX);
        const gYMin = Math.min(...allY), gYMax = Math.max(...allY);
        const padX = (gXMax - gXMin) * 0.08 || 0.1;
        const padY = (gYMax - gYMin) * 0.08 || 0.1;
        const syncXMin = gXMin - padX, syncXMax = gXMax + padX;
        const syncYMin = gYMin - padY, syncYMax = gYMax + padY;

        setTimeout(() => {
            cells.forEach((cell, ci) => {
                const canvas = document.getElementById(`rsm-tree-canvas-sq-${ci}`);
                if (!canvas || cell.x.length < 2) return;
                const points = cell.x.map((x, i) => ({ x, y: cell.y[i] }));
                const n = points.length;
                const sX = points.reduce((a,b) => a+b.x, 0), sY = points.reduce((a,b) => a+b.y, 0);
                const sXY = points.reduce((a,b) => a+b.x*b.y, 0), sXX = points.reduce((a,b) => a+b.x*b.x, 0);
                const slope = (n*sXY - sX*sY)/(n*sXX - sX*sX) || 0;
                const intercept = (sY - slope*sX)/n;
                const gxMin = Math.min(...cell.x), gxMax = Math.max(...cell.x);
                new Chart(canvas.getContext('2d'), {
                    type: 'scatter',
                    data: { datasets: [
                        { data: points, backgroundColor: bgs[ci], borderColor: colors[ci], borderWidth: 1, pointRadius: 4 },
                        { data: [{ x: gxMin, y: slope*gxMin+intercept },{ x: gxMax, y: slope*gxMax+intercept }],
                          type: 'line', borderColor: colors[ci], borderWidth: 2, fill: false, pointRadius: 0, showLine: true }
                    ]},
                    options: {
                        responsive: true, maintainAspectRatio: false, animation: { duration: 150 },
                        plugins: { legend: { display: false } },
                        scales: {
                            x: { min: syncXMin, max: syncXMax, ticks: { font: { size: 9 }, maxTicksLimit: 4 }, grid: { color: '#f1f5f9' } },
                            y: { min: syncYMin, max: syncYMax, ticks: { font: { size: 9 }, maxTicksLimit: 4 }, grid: { color: '#f1f5f9' } },
                        }
                    }
                });
            });
        }, 0);

        const cName = data.factor_c.substring(0, 26);
        const aName = data.factor_a.substring(0, 22);
        const yNameSq = (activeTarget || '目標').substring(0, 22);
        return `<div style="display:flex;align-items:center;justify-content:center;height:100%;padding:12px 8px;gap:0;overflow:auto;">
            <div style="display:flex;flex-direction:column;justify-content:center;align-items:center;padding:0 12px;">
                <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:8px 12px;text-align:center;max-width:110px;">
                    <div style="font-size:10px;color:#94a3b8;margin-bottom:2px;">目標（Y）</div>
                    <div style="font-size:11px;font-weight:700;color:#1e293b;">${yNameSq}</div>
                    <div style="font-size:9px;color:#94a3b8;margin-top:4px;border-top:1px solid #f1f5f9;padding-top:3px;">X: ${cName}</div>
                </div>
            </div>
            <div style="width:32px;height:2px;background:#cbd5e1;"></div>
            <div style="display:flex;flex-direction:column;justify-content:space-around;gap:16px;">
                ${cells.map((cell, ci) => `
                <div style="display:flex;align-items:center;gap:8px;">
                    <div style="display:flex;flex-direction:column;align-items:center;padding:0 8px;">
                        <div style="font-size:10px;color:#94a3b8;">${labels[ci]}</div>
                        <div style="font-size:10px;font-weight:600;color:${colors[ci]};max-width:80px;text-align:center;">${aName.substring(0,12)}</div>
                        <div style="font-size:10px;color:${colors[ci]};font-weight:600;">${ranges[ci]}</div>
                    </div>
                    <div style="width:20px;height:2px;background:#cbd5e1;"></div>
                    ${leafCard(cell, ci)}
                </div>`).join('')}
            </div>
        </div>`;
    }

    function _rsmBuildTreeHTML4F(data, activeTarget) {
        const cells = data.cells;
        const outerName = data.outer_factor.substring(0, 16);
        const innerName = data.inner_factor.substring(0, 16);
        const xName     = data.x_factor.substring(0, 26);
        const outerSplits = data.outer_splits || [];
        const innerSplits = data.inner_splits || [];
        const nOuter = outerSplits.length;
        const nInner = innerSplits.length;
        const outerIsCat = !!data.outer_is_cat;
        const innerIsCat = !!data.inner_is_cat;

        // Sync X/Y axes across all cells (filter nulls)
        const allX = cells.flatMap(c => (c.x || []).filter(v => v != null && !isNaN(v)));
        const allY = cells.flatMap(c => (c.y || []).filter(v => v != null && !isNaN(v)));
        const gXMin = Math.min(...allX), gXMax = Math.max(...allX);
        const gYMin = Math.min(...allY), gYMax = Math.max(...allY);
        const padX = (gXMax - gXMin) * 0.08 || 0.1;
        const padY = (gYMax - gYMin) * 0.08 || 0.1;
        const syncXMin = gXMin - padX, syncXMax = gXMax + padX;
        const syncYMin = gYMin - padY, syncYMax = gYMax + padY;

        // Color palette: outer groups get distinct hue families (extended for categorical)
        const outerPalettes = [
            ['#6366f1','#3b82f6','#0ea5e9'],  // outer 0: blues
            ['#f59e0b','#f97316','#ef4444'],  // outer 1: oranges/reds
            ['#10b981','#14b8a6','#06b6d4'],  // outer 2: greens
            ['#8b5cf6','#a855f7','#d946ef'],  // outer 3: purples
            ['#ec4899','#f43f5e','#fb923c'],  // outer 4: pinks
            ['#0d9488','#0891b2','#2563eb'],  // outer 5: teals
        ];
        const colors = [];
        for (let oi = 0; oi < nOuter; oi++) {
            for (let ii = 0; ii < nInner; ii++) {
                colors.push(outerPalettes[oi % outerPalettes.length][ii % 3]);
            }
        }
        const bgs = colors.map(c => c + '25');

        function fmtRange(rmin, rmax) {
            // Categorical: range_min === range_max and is a string label
            if (typeof rmin === 'string' && rmin === rmax) return rmin;
            const fmt = v => (v == null || isNaN(v)) ? '?' : (Math.abs(v) >= 1000 || Math.abs(v) < 0.01) ? v.toFixed(2) : Number(v.toPrecision(4)).toString();
            return `${fmt(rmin)}~${fmt(rmax)}`;
        }

        function leafCard(cell, ci) {
            const sig = (cell.p_value ?? 1) < 0.05 ? ' ✓' : '';
            const bColor = (cell.slope ?? 0) > 0 ? '#16a34a' : (cell.slope ?? 0) < 0 ? '#dc2626' : '#94a3b8';
            const rColor = Math.abs(cell.r ?? 0) > 0.4 ? bColor : '#64748b';
            return `<div style="background:#fff;border:2px solid ${colors[ci]};border-radius:8px;padding:8px 10px;min-width:190px;max-width:230px;box-shadow:0 1px 6px #0001;">
                <div style="font-size:10px;color:#94a3b8;margin-bottom:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${xName}">X: ${xName}</div>
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:2px;">
                    <span style="font-size:10px;color:#64748b;">n=${cell.n}</span>
                    <span style="font-size:10px;color:${rColor};font-weight:600;">r=${_safeR(cell.r,3)}${sig}</span>
                </div>
                <div style="font-size:13px;font-weight:700;color:${bColor};margin-bottom:4px;">${(cell.slope ?? 0) >= 0 ? '+' : ''}${_fmtSlope(cell.slope)}</div>
                <div style="height:110px;position:relative;"><canvas id="rsm-tree4f-canvas-${ci}"></canvas></div>
            </div>`;
        }

        function drawMiniChart(canvasId, px, py, color, bg, xMinOverride, xMaxOverride) {
            const canvas = document.getElementById(canvasId);
            if (!canvas || px.length < 2) return;
            const points = px.map((x, i) => ({ x, y: py[i] }));
            const n = points.length;
            const sX = points.reduce((a,b) => a+b.x, 0), sY = points.reduce((a,b) => a+b.y, 0);
            const sXY = points.reduce((a,b) => a+b.x*b.y, 0), sXX = points.reduce((a,b) => a+b.x*b.x, 0);
            const slope = (n*sXY - sX*sY) / (n*sXX - sX*sX) || 0;
            const intercept = (sY - slope*sX) / n;
            const lxMin = Math.min(...px), lxMax = Math.max(...px);
            const xMin = xMinOverride !== undefined ? xMinOverride : syncXMin;
            const xMax = xMaxOverride !== undefined ? xMaxOverride : syncXMax;
            const _c = new Chart(canvas.getContext('2d'), {
                type: 'scatter',
                data: { datasets: [
                    { data: points, backgroundColor: bg, borderColor: color, borderWidth: 1, pointRadius: 2.5 },
                    { data: [{ x: lxMin, y: slope*lxMin+intercept }, { x: lxMax, y: slope*lxMax+intercept }],
                      type: 'line', borderColor: color, borderWidth: 2, fill: false, pointRadius: 0, showLine: true }
                ]},
                options: {
                    responsive: true, maintainAspectRatio: false, animation: { duration: 0 },
                    plugins: { legend: { display: false } },
                    scales: {
                        x: { min: xMin, max: xMax, ticks: { font: { size: 8 }, maxTicksLimit: 3 }, grid: { color: '#f1f5f9' } },
                        y: { min: syncYMin, max: syncYMax, ticks: { font: { size: 8 }, maxTicksLimit: 3 }, grid: { color: '#f1f5f9' } },
                    }
                }
            });
            _rsmTree4FCharts.push(_c);
        }

        // Pre-compute outer/inner axis ranges for node charts (numeric only)
        const allOuterX = outerIsCat ? [] : cells.flatMap(c => (c.outer_x || []).filter(v => v != null && !isNaN(v)));
        const allInnerX = innerIsCat ? [] : cells.flatMap(c => (c.inner_x || []).filter(v => v != null && !isNaN(v)));
        function _axRange(arr) {
            if (!arr.length) return [syncXMin, syncXMax];
            const mn = Math.min(...arr), mx = Math.max(...arr), pad = (mx-mn)*0.08||0.1;
            return [mn-pad, mx+pad];
        }
        const [outerXMin, outerXMax] = _axRange(allOuterX);
        const [innerXMin, innerXMax] = _axRange(allInnerX);

        setTimeout(() => {
            // Destroy previous 4F charts before creating new ones
            _rsmTree4FCharts.forEach(c => { try { c.destroy(); } catch(e) {} });
            _rsmTree4FCharts = [];
            // Leaf card charts (use C axis)
            cells.forEach((cell, ci) => drawMiniChart(`rsm-tree4f-canvas-${ci}`, cell.x, cell.y, colors[ci], bgs[ci]));

            // A-node (outer) aggregate charts — X = outer factor (skip for categorical)
            if (_rsmTrellis4FShowNodeCharts) {
                if (!outerIsCat) {
                    outerSplits.forEach((_, oi) => {
                        const offset = oi * nInner;
                        const ax = cells.slice(offset, offset + nInner).flatMap(c => c.outer_x || c.x);
                        const ay = cells.slice(offset, offset + nInner).flatMap(c => c.y);
                        const aColor = outerPalettes[oi % outerPalettes.length][1];
                        drawMiniChart(`rsm-tree4f-anode-${oi}`, ax, ay, aColor, aColor + '25', outerXMin, outerXMax);
                    });
                }
                // B-node (inner) charts — X = inner factor (skip for categorical)
                if (!innerIsCat) {
                    cells.forEach((cell, ci) => drawMiniChart(`rsm-tree4f-bnode-${ci}`, cell.inner_x || cell.x, cell.y, colors[ci], bgs[ci], innerXMin, innerXMax));
                }
            }
        }, 0);

        const showNC = _rsmTrellis4FShowNodeCharts;

        function nodeCard(label, name, range, color, canvasId, isCat) {
            // For categorical factors, show a compact card without chart canvas
            if (isCat) {
                return `<div style="background:#fff;border:2px solid ${color};border-radius:8px;padding:8px 10px;min-width:120px;max-width:200px;box-shadow:0 1px 6px #0001;">
                    <div style="font-size:10px;color:#94a3b8;margin-bottom:2px;">${label}</div>
                    <div style="font-size:10px;font-weight:700;color:${color};overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-bottom:1px;" title="${name}">${name}</div>
                    <div style="font-size:12px;color:${color};font-weight:700;">${range}</div>
                </div>`;
            }
            return `<div style="background:#fff;border:2px solid ${color};border-radius:8px;padding:8px 10px;min-width:190px;max-width:230px;box-shadow:0 1px 6px #0001;">
                <div style="font-size:10px;color:#94a3b8;margin-bottom:2px;">${label}</div>
                <div style="font-size:10px;font-weight:700;color:${color};overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-bottom:1px;" title="${name}">${name}</div>
                <div style="font-size:10px;color:${color};font-weight:600;margin-bottom:4px;">${range}</div>
                <div style="height:110px;position:relative;"><canvas id="${canvasId}"></canvas></div>
            </div>`;
        }

        function outerBranch(oi, cellOffset) {
            const sp = outerSplits[oi];
            const oLabel = sp ? sp.label : String(oi);
            const oRange = sp ? fmtRange(sp.range_min, sp.range_max) : '';
            const oColor = outerPalettes[oi % outerPalettes.length][1];
            const showOuterChart = showNC && !outerIsCat;
            const aNodeHtml = (showNC || outerIsCat)
                ? nodeCard(`A（外層）`, data.outer_factor, outerIsCat ? oLabel : oRange, oColor, `rsm-tree4f-anode-${oi}`, outerIsCat)
                : `<div style="display:flex;flex-direction:column;align-items:center;padding:0 6px;min-width:88px;">
                    <div style="font-size:10px;color:#94a3b8;">A（外層）${oLabel}</div>
                    <div style="font-size:10px;font-weight:700;color:${oColor};max-width:86px;text-align:center;word-break:break-all;">${outerName}</div>
                    <div style="font-size:10px;color:${oColor};font-weight:600;word-break:break-all;text-align:center;">${oRange}</div>
                  </div>`;
            return `<div style="display:flex;align-items:center;gap:0;">
                <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;padding:0 ${(showNC||outerIsCat)?'4':'10'}px;">
                    ${aNodeHtml}
                </div>
                <div style="width:20px;height:2px;background:#cbd5e1;"></div>
                <div style="display:flex;flex-direction:column;gap:10px;">
                    ${innerSplits.map((isp, j) => {
                        const iColor = colors[cellOffset + j];
                        const iRange = fmtRange(isp.range_min, isp.range_max);
                        const showInnerChart = showNC && !innerIsCat;
                        const bNodeHtml = (showNC || innerIsCat)
                            ? nodeCard(`B（內層）`, data.inner_factor, innerIsCat ? isp.label : iRange, iColor, `rsm-tree4f-bnode-${cellOffset+j}`, innerIsCat)
                            : `<div style="display:flex;flex-direction:column;align-items:center;min-width:64px;">
                                <div style="font-size:10px;color:#94a3b8;">B（內層）${isp.label}</div>
                                <div style="font-size:9px;font-weight:600;color:${iColor};max-width:62px;text-align:center;word-break:break-all;">${innerName.substring(0,10)}</div>
                                <div style="font-size:9px;color:${iColor};word-break:break-all;text-align:center;">${iRange}</div>
                              </div>`;
                        return `<div style="display:flex;align-items:center;gap:6px;">
                            ${bNodeHtml}
                            <div style="width:14px;height:2px;background:#cbd5e1;"></div>
                            ${leafCard(cells[cellOffset + j], cellOffset + j)}
                        </div>`;
                    }).join('')}
                </div>
            </div>`;
        }

        const btnBase = 'padding:3px 8px;border-radius:5px;border:1px solid #cbd5e1;background:#fff;color:#475569;font-size:10px;cursor:pointer;white-space:nowrap;';
        const btnActive = 'padding:3px 8px;border-radius:5px;border:1px solid #7c3aed;background:#ede9fe;color:#7c3aed;font-size:10px;cursor:pointer;white-space:nowrap;font-weight:700;';
        const curOuter = _rsmTrellis4FOuterGroups;
        const curInner = _rsmTrellis4FInnerGroups;

        const tagStyle = (color) => `display:inline-block;padding:1px 5px;border-radius:4px;font-size:10px;font-weight:700;color:${color};background:${color}18;margin-right:3px;flex-shrink:0;`;
        const factorLegend = `<div style="display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:6px;padding:5px 8px;background:#fafafa;border-radius:6px;border:1px solid #e2e8f0;font-size:11px;color:#1e293b;">
            <span><span style="${tagStyle('#6366f1')}">A 外層</span>${data.outer_factor}</span>
            <span><span style="${tagStyle('#0ea5e9')}">B 內層</span>${data.inner_factor}</span>
            <span><span style="${tagStyle('#10b981')}">C X軸</span>${data.x_factor}</span>
            <span><span style="${tagStyle('#7c3aed')}">Y 目標</span>${activeTarget}</span>
        </div>`;

        const outerGroupBtns = outerIsCat ? `<span style="font-size:10px;color:#94a3b8;">A 類別×${nOuter}</span>` : `
            <span style="font-size:10px;color:#94a3b8;">A（外層）組數：</span>
            <button style="${curOuter===2 ? btnActive : btnBase}" onclick="window._rsmTrellis4FSetGroups('outer',2)">2</button>
            <button style="${curOuter===3 ? btnActive : btnBase}" onclick="window._rsmTrellis4FSetGroups('outer',3)">3</button>`;
        const innerGroupBtns = innerIsCat ? `<span style="font-size:10px;color:#94a3b8;">B 類別×${nInner}</span>` : `
            <span style="font-size:10px;color:#94a3b8;">B（內層）組數：</span>
            <button style="${curInner===2 ? btnActive : btnBase}" onclick="window._rsmTrellis4FSetGroups('inner',2)">2</button>
            <button style="${curInner===3 ? btnActive : btnBase}" onclick="window._rsmTrellis4FSetGroups('inner',3)">3</button>`;

        const toolbar = `<div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:6px;padding:6px 8px;background:#f8fafc;border-radius:8px;border:1px solid #e2e8f0;">
            <span style="font-size:10px;color:#94a3b8;margin-right:2px;">換軸：</span>
            <button style="${btnBase}" onclick="window._rsmTrellis4FSwap('outer-inner')">⇄ A↔B</button>
            <button style="${btnBase}" onclick="window._rsmTrellis4FSwap('outer-x')">⇄ A↔C(X)</button>
            <button style="${btnBase}" onclick="window._rsmTrellis4FSwap('inner-x')">⇄ B↔C(X)</button>
            <span style="width:1px;height:18px;background:#e2e8f0;margin:0 4px;"></span>
            ${outerGroupBtns}
            <span style="width:1px;height:18px;background:#e2e8f0;margin:0 4px;"></span>
            ${innerGroupBtns}
            <span style="width:1px;height:18px;background:#e2e8f0;margin:0 4px;"></span>
            <button style="${showNC ? btnActive : btnBase}" onclick="window._rsmTrellis4FToggleNodeCharts()">節點趨勢圖</button>
        </div>`;

        return `<div style="padding:8px 4px;overflow:auto;height:100%;box-sizing:border-box;">
            ${factorLegend}
            ${toolbar}
            <div style="display:flex;align-items:stretch;gap:0;overflow:auto;">
                <!-- Root: target (Y) label -->
                <div style="display:flex;flex-direction:column;justify-content:center;align-items:center;padding:0 10px;">
                    <div style="background:#faf5ff;border:1px solid #e9d5ff;border-radius:8px;padding:8px 10px;text-align:center;max-width:100px;">
                        <div style="font-size:10px;color:#7c3aed;margin-bottom:2px;">目標（Y）</div>
                        <div style="font-size:10px;font-weight:700;color:#1e293b;">${activeTarget.substring(0,20)}</div>
                        <div style="font-size:9px;color:#94a3b8;margin-top:3px;border-top:1px solid #f1f5f9;padding-top:2px;">X(C): ${xName.substring(0,16)}</div>
                    </div>
                </div>
                <div style="display:flex;flex-direction:column;justify-content:center;"><div style="width:24px;height:2px;background:#cbd5e1;"></div></div>
                <!-- Outer branches -->
                <div style="display:flex;flex-direction:column;justify-content:space-around;gap:24px;">
                    ${outerSplits.map((_, oi) => outerBranch(oi, oi * nInner)).join('')}
                </div>
            </div>
        </div>`;
    }

    window._rsmCondExpand = function(overrideData, syncY) {
        const d = window._rsmCondData;
        if (!d) return;
        const { groupColors, groupBg, isTrellis, activeTarget } = d;
        const data = overrideData || d.data;
        const doSyncY = syncY !== undefined ? !!syncY : true;
        window._rsmCondExpandState = { data, syncY: doSyncY };

        let existing = document.getElementById('rsm-cond-modal');
        if (existing) existing.remove();

        const quadColors = ['#6366f1','#0ea5e9','#f59e0b','#10b981'];
        const quadBg     = ['#6366f133','#0ea5e933','#f59e0b33','#10b98133'];

        const cells = isTrellis ? data.cells : data.groups;
        const isCatCondExp = !isTrellis && data.bg_type === 'categorical';
        const cols = isTrellis ? 2 : cells.length;
        const titleText = isTrellis
            ? `2×2 切片：A=${data.factor_a} × B=${data.factor_b} | C=${data.factor_c}`
            : `條件式分析：${data.condition_var}`;
        const subtitleText = isTrellis
            ? `A 中位=${data.a_median}　B 中位=${data.b_median}`
            : isCatCondExp
                ? cells.map(g => g.label).join(' | ')
                : `Low ≤ ${data.p33} | Mid ≤ ${data.p67} | High > ${data.p67}`;

        // Global Y range for sync
        let yMin, yMax, xMin, xMax;
        if (doSyncY) {
            const allY = cells.flatMap(g => g.y);
            yMin = Math.min(...allY); yMax = Math.max(...allY);
            const padY = (yMax - yMin) * 0.06 || 0.1;
            yMin -= padY; yMax += padY;

            const allX = cells.flatMap(g => g.x);
            xMin = Math.min(...allX); xMax = Math.max(...allX);
            const padX = (xMax - xMin) * 0.12 || 0.1;
            xMin -= padX; xMax += padX;
        }

        const syncBtnStyle = doSyncY
            ? 'padding:4px 10px;border-radius:6px;border:1px solid #6366f1;background:#6366f1;color:#fff;font-size:11px;font-weight:600;cursor:pointer;'
            : 'padding:4px 10px;border-radius:6px;border:1px solid #cbd5e1;background:#fff;color:#64748b;font-size:11px;font-weight:600;cursor:pointer;';
        const swapBtnStyle = 'padding:4px 10px;border-radius:6px;border:1px solid #cbd5e1;background:#fff;color:#64748b;font-size:11px;font-weight:600;cursor:pointer;';
        const swapBtn = isTrellis ? '' : `<button onclick="window._rsmCondSwap()" style="${swapBtnStyle}">⇄ 切換條件/X軸</button>`;

        const modal = document.createElement('div');
        modal.id = 'rsm-cond-modal';
        modal.style.cssText = 'position:fixed;inset:0;background:#00000066;z-index:9999;display:flex;align-items:center;justify-content:center;';
        modal.innerHTML = `
            <div style="background:#fff;border-radius:16px;padding:20px;width:90vw;max-width:1100px;height:80vh;display:flex;flex-direction:column;gap:12px;">
                <div style="display:flex;justify-content:space-between;align-items:center;flex-shrink:0;">
                    <div style="font-size:13px;font-weight:700;color:#1e293b;">${titleText}</div>
                    <div style="display:flex;align-items:center;gap:8px;">
                        <button onclick="window._rsmCondExpand(window._rsmCondExpandState.data, !window._rsmCondExpandState.syncY)" style="${syncBtnStyle}">座標軸同步</button>
                        ${swapBtn}
                        <button onclick="document.getElementById('rsm-cond-modal').remove()" style="background:none;border:none;font-size:20px;cursor:pointer;color:#64748b;">×</button>
                    </div>
                </div>
                <div style="font-size:11px;color:#64748b;flex-shrink:0;">${subtitleText}</div>
                <div style="overflow-x:auto;flex:1;min-height:0;">
                <div style="display:grid;grid-template-columns:repeat(${cols},${isCatCondExp && cols > 3 ? '260px' : '1fr'});gap:16px;height:100%;${isCatCondExp && cols > 3 ? `min-width:${cols * 276}px;` : ''}">
                    ${cells.map((g, gi) => {
                        const colors = isTrellis ? quadColors : groupColors;
                        const rColor = Math.abs(g.r ?? 0) > 0.4 ? ((g.r ?? 0) > 0 ? '#16a34a' : '#dc2626') : '#64748b';
                        const sig = (g.p_value ?? 1) < 0.05 ? '✓' : '';
                        const lbl = isTrellis ? g.label.replace('_Low','↓').replace('_High','↑') : g.label;
                        // Calculate slope from x/y arrays since backend doesn't return it
                        let calcSlope = 0;
                        if (g.x && g.x.length >= 2) {
                            const _n = g.x.length;
                            const _sX = g.x.reduce((a,b)=>a+b,0), _sY = g.y.reduce((a,b)=>a+b,0);
                            const _sXY = g.x.reduce((a,b,i)=>a+b*g.y[i],0), _sXX = g.x.reduce((a,b)=>a+b*b,0);
                            calcSlope = (_n*_sXY - _sX*_sY) / (_n*_sXX - _sX*_sX) || 0;
                        }
                        const bColor = calcSlope > 0 ? '#16a34a' : calcSlope < 0 ? '#dc2626' : '#94a3b8';
                        // Range label: category name for categorical, min~max for numeric
                        let rangeLabel = '';
                        if (!isTrellis) {
                            if (isCatCondExp) {
                                rangeLabel = ''; // label already shown in header
                            } else if (g.cond_min != null && g.cond_max != null) {
                                rangeLabel = `${g.cond_min} ~ ${g.cond_max}`;
                            }
                        }
                        return `<div style="display:flex;flex-direction:column;border:1px solid #e2e8f0;border-radius:10px;padding:10px;background:#fafafa;">
                            <div style="display:flex;justify-content:space-between;margin-bottom:2px;">
                                <span style="font-size:12px;font-weight:700;color:${colors[gi]};">${lbl} (n=${g.n})</span>
                                <span style="font-size:12px;font-family:monospace;color:${rColor};font-weight:700;">r=${_safeR(g.r,3)}${sig}</span>
                            </div>
                            ${rangeLabel ? `<div style="font-size:10px;color:#94a3b8;margin-bottom:2px;">${data.condition_var.substring(0,20)}: <b style="color:${colors[gi]};">${rangeLabel}</b></div>` : ''}
                            <div style="font-size:10px;color:#64748b;margin-bottom:4px;">β=<b style="color:${bColor};">${_fmtSlope(calcSlope)}</b></div>
                            <div style="flex:1;min-height:0;position:relative;"><canvas id="rsm-cond-exp-${gi}"></canvas></div>
                        </div>`;
                    }).join('')}
                </div>
                </div>
            </div>`;
        document.body.appendChild(modal);
        modal.addEventListener('click', e => { if (e.target === modal) modal.remove(); });
        const _escHandler = e => { if (e.key === 'Escape') { modal.remove(); document.removeEventListener('keydown', _escHandler); } };
        document.addEventListener('keydown', _escHandler);

        setTimeout(() => {
            cells.forEach((g, gi) => {
                const canvas = document.getElementById(`rsm-cond-exp-${gi}`);
                if (!canvas || g.x.length < 2) return;
                const colors = isTrellis ? quadColors : groupColors;
                const bgs = isTrellis ? quadBg : groupBg;
                const xLabel = isTrellis ? data.factor_c.substring(0, 25) : (data.x_label || '').substring(0, 25);
                const points = g.x.map((x, i) => ({ x, y: g.y[i] }));
                const n = points.length;
                const sumX = points.reduce((a, b) => a + b.x, 0), sumY = points.reduce((a, b) => a + b.y, 0);
                const sumXY = points.reduce((a, b) => a + b.x * b.y, 0), sumXX = points.reduce((a, b) => a + b.x * b.x, 0);
                const slope = (n * sumXY - sumX * sumY) / (n * sumXX - sumX * sumX) || 0;
                const intercept = (sumY - slope * sumX) / n;
                const gxMin = Math.min(...g.x), gxMax = Math.max(...g.x);
                const xScaleOpts = doSyncY
                    ? { min: xMin, max: xMax, title: { display: true, text: xLabel, font: { size: 10 } }, ticks: { font: { size: 9 }, maxTicksLimit: 5 }, grid: { color: '#f1f5f9' } }
                    : { title: { display: true, text: xLabel, font: { size: 10 } }, ticks: { font: { size: 9 }, maxTicksLimit: 5 }, grid: { color: '#f1f5f9' } };
                const yScaleOpts = doSyncY
                    ? { min: yMin, max: yMax, title: { display: true, text: activeTarget.substring(0, 15), font: { size: 10 } }, ticks: { font: { size: 9 }, maxTicksLimit: 5 }, grid: { color: '#f1f5f9' } }
                    : { title: { display: true, text: activeTarget.substring(0, 15), font: { size: 10 } }, ticks: { font: { size: 9 }, maxTicksLimit: 5 }, grid: { color: '#f1f5f9' } };
                new Chart(canvas.getContext('2d'), {
                    type: 'scatter',
                    data: { datasets: [
                        { data: points, backgroundColor: bgs[gi], borderColor: colors[gi], borderWidth: 1, pointRadius: 4 },
                        { data: [{ x: gxMin, y: slope * gxMin + intercept }, { x: gxMax, y: slope * gxMax + intercept }],
                          type: 'line', borderColor: colors[gi], borderWidth: 2, fill: false, pointRadius: 0, showLine: true }
                    ]},
                    options: {
                        responsive: true, maintainAspectRatio: false, animation: { duration: 200 },
                        plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => `X:${c.parsed.x.toFixed(2)}, Y:${c.parsed.y.toFixed(2)}` } } },
                        scales: { x: xScaleOpts, y: yScaleOpts },
                    }
                });
            });
        }, 50);
    };

    window._rsmCondSwap = async function() {
        const d = window._rsmCondData;
        if (!d || d.isTrellis || !d.body || !d.sid) return;
        const swappedBody = { ...d.body, factors: [...d.body.factors].reverse() };
        const swapBtn = document.querySelector('#rsm-cond-modal button[onclick*="_rsmCondSwap"]');
        if (swapBtn) { swapBtn.disabled = true; swapBtn.textContent = '載入中...'; }
        try {
            const res = await fetch(`/api/data-prep/rsm-conditional-data?session_id=${d.sid}`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(swappedBody),
            });
            const newData = await res.json();
            window._rsmCondData = { ...d, data: newData, body: swappedBody };
            window._rsmCondExpand(newData, window._rsmCondExpandState?.syncY);
        } catch(e) {
            if (swapBtn) { swapBtn.disabled = false; swapBtn.textContent = '⇄ 切換條件/X軸'; }
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

    // ============ SHAP ANALYSIS TAB ============

    let _rsmActiveAnalysisTab = 'poly';  // 'poly' or 'shap'
    let _rsmShapResult = null;
    let _rsmShapChart = null;          // Chart.js instance for prediction vs actual
    let _rsmShapOverlayFactor = '';    // currently overlaid factor name

    // Show the analysis tab bar (called after polynomial results are rendered)
    function _showAnalysisTabBar() {
        const tabs = document.getElementById('rsm-analysis-tabs');
        if (tabs) { tabs.style.display = 'flex'; tabs.style.gap = '2px'; }
    }

    window.rsmSwitchAnalysisTab = function (tab) {
        _rsmActiveAnalysisTab = tab;
        const polyArea = document.getElementById('rsm-result-area');
        const shapArea = document.getElementById('rsm-shap-area');
        const polyBtn = document.getElementById('rsm-tab-poly');
        const shapBtn = document.getElementById('rsm-tab-shap');

        if (tab === 'poly') {
            if (polyArea) polyArea.style.display = '';
            if (shapArea) shapArea.style.display = 'none';
            if (polyBtn) { polyBtn.style.background = '#2563eb'; polyBtn.style.color = '#fff'; }
            if (shapBtn) { shapBtn.style.background = 'transparent'; shapBtn.style.color = '#64748b'; }
        } else {
            if (polyArea) polyArea.style.display = 'none';
            if (shapArea) shapArea.style.display = '';
            if (polyBtn) { polyBtn.style.background = 'transparent'; polyBtn.style.color = '#64748b'; }
            if (shapBtn) { shapBtn.style.background = '#f59e0b'; shapBtn.style.color = '#fff'; }
            // Always re-render to avoid stale/empty DOM state
            if (_rsmShapResult) {
                _renderShapResults(_rsmShapResult, shapArea);
            } else {
                _renderShapPrompt(shapArea);
            }
        }
    };

    function _renderShapPrompt(container) {
        const factorCount = _rsmSelectedFactors.length;
        const targetLabel = _rsmTargets.join(' / ');
        container.innerHTML = `
            <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;padding:60px 20px;gap:16px;">
                <div style="font-size:48px;">🔥</div>
                <div style="font-size:16px;font-weight:700;color:#1e293b;">SHAP 重要性分析</div>
                <div style="font-size:13px;color:#64748b;text-align:center;max-width:360px;line-height:1.6;">
                    使用 <b>XGBoost + SHAP</b> 評估每個因子對目標的真實影響力<br>
                    包含 MI 排名、SHAP 重要性、方向性，以及因子交互熱圖
                </div>
                <div style="font-size:12px;color:#94a3b8;background:#f8fafc;padding:8px 16px;border-radius:8px;border:1px solid #e2e8f0;">
                    目標: <b style="color:#2563eb;">${targetLabel}</b> &nbsp;|&nbsp; 因子數: <b style="color:#059669;">${factorCount}</b>
                </div>
                <div style="font-size:11px;color:#f59e0b;font-weight:600;">⚠ 含交互值計算，可能需要 1-3 分鐘</div>
                <button onclick="window.rsmRunShap()" id="rsm-shap-run-btn"
                    style="padding:12px 32px;background:linear-gradient(135deg,#f59e0b,#ef4444);color:#fff;border:none;border-radius:10px;font-size:14px;font-weight:700;cursor:pointer;box-shadow:0 4px 12px rgba(245,158,11,0.3);">
                    ▶ 執行 SHAP 分析
                </button>
            </div>`;
    }

    window.rsmRunShap = async function () {
        const shapArea = document.getElementById('rsm-shap-area');
        if (!shapArea) return;

        const sid = typeof getSessionId === 'function' ? getSessionId() : 'default';
        const targetLabel = _rsmTargets.join(' / ');

        // Show progress UI
        shapArea.innerHTML = `
            <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;padding:60px 20px;gap:16px;">
                <div style="font-size:40px;">🧠</div>
                <div style="font-size:15px;font-weight:700;color:#1e293b;">正在執行 SHAP 分析...</div>
                <div style="color:#64748b;font-size:12px;">目標: ${targetLabel} | 因子: ${_rsmSelectedFactors.length} 個</div>
                <div style="width:320px;height:10px;background:#f1f5f9;border-radius:5px;overflow:hidden;">
                    <div id="rsm-shap-progress" style="width:0%;height:100%;background:linear-gradient(90deg,#f59e0b,#ef4444);transition:width 0.4s;"></div>
                </div>
                <div id="rsm-shap-progress-text" style="font-size:11px;color:#64748b;">初始化...</div>
            </div>`;

        let prog = 0;
        const progEl = document.getElementById('rsm-shap-progress');
        const progText = document.getElementById('rsm-shap-progress-text');
        const progInterval = setInterval(() => {
            if (prog < 90) {
                prog += prog < 20 ? 4 : prog < 60 ? 1.5 : 0.4;
                if (progEl) progEl.style.width = prog + '%';
                if (progText) {
                    let msg = prog < 15 ? '載入資料...' : prog < 35 ? '計算 MI 排名...' : prog < 60 ? '訓練 XGBoost...' : prog < 80 ? '計算 SHAP 值...' : '計算交互矩陣...';
                    progText.textContent = `${msg} ${Math.floor(prog)}%`;
                }
            }
        }, 500);

        try {
            const body = {
                file_id: currentFileId,
                targets: _rsmTargets,
                factors: _rsmSelectedFactors,
                filters: (typeof _activeDataset !== 'undefined' && _activeDataset?.filters) ?
                    _activeDataset.filters.map(f => ({ column: f.col, keyword: '==' + String(f.value || ''), exclude_empty: false })) : [],
                exclude_indices: (typeof _clOutlierIndices !== 'undefined') ? _clOutlierIndices : [],
                exclude_cols: _getExcludedCols(),
            };
            const res = await fetch(`/api/data-prep/rsm-shap-analysis?session_id=${sid}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'SHAP 分析失敗');
            _rsmShapResult = data;
            clearInterval(progInterval);
            if (progEl) progEl.style.width = '100%';
            await new Promise(r => setTimeout(r, 300));
            _renderShapResults(data, shapArea);
        } catch (err) {
            clearInterval(progInterval);
            shapArea.innerHTML = `
                <div style="display:flex;flex-direction:column;align-items:center;gap:12px;padding:60px 20px;">
                    <div style="font-size:32px;">❌</div>
                    <div style="color:#ef4444;font-size:14px;font-weight:600;">SHAP 分析失敗</div>
                    <div style="color:#64748b;font-size:12px;max-width:400px;text-align:center;">${err.message}</div>
                    <button onclick="window.rsmRunShap()" style="padding:8px 20px;background:#f59e0b;color:#fff;border:none;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;">重試</button>
                </div>`;
        }
    };

    function _renderShapResults(data, container) {
        // data: { targets: [...], results: { targetName: { mi, shap_importance, shap_interaction } } }
        if (!data || !data.targets || data.targets.length === 0) {
            _renderShapPrompt(container);
            return;
        }
        const targets = data.targets || [];
        const results = data.results || {};

        // Build tab bar for multiple targets
        let tabsHtml = '';
        if (targets.length > 1) {
            tabsHtml = `<div style="display:flex;gap:6px;margin-bottom:16px;flex-wrap:wrap;">
                ${targets.map((t, i) => `
                    <button onclick="window._rsmShapShowTarget(${i})" id="rsm-shap-target-tab-${i}"
                        style="padding:4px 12px;border:none;border-radius:16px;font-size:12px;font-weight:600;cursor:pointer;
                               background:${i===0?'#f59e0b':'#f1f5f9'};color:${i===0?'#fff':'#64748b'};">
                        ${t}
                    </button>`).join('')}
            </div>`;
        }

        // Use a unique ID each render to avoid stale getElementById lookups
        const contentId = 'rsm-shap-content-' + Date.now();
        container.innerHTML = `
            <div style="padding:0 0 20px 0;">
                ${tabsHtml}
                <div id="${contentId}"></div>
            </div>`;

        const contentEl = document.getElementById(contentId);

        window._rsmShapCurrentIdx = 0;
        window._rsmShapShowTarget = function (idx) {
            window._rsmShapCurrentIdx = idx;
            targets.forEach((_, i) => {
                const btn = document.getElementById(`rsm-shap-target-tab-${i}`);
                if (btn) { btn.style.background = i === idx ? '#f59e0b' : '#f1f5f9'; btn.style.color = i === idx ? '#fff' : '#64748b'; }
            });
            const tName = targets[idx];
            _renderShapForTarget(results[tName], tName, contentEl);
        };

        const firstName = targets[0];
        _renderShapForTarget(results[firstName], firstName, contentEl);
    }

    function _renderShapForTarget(res, targetName, container) {
        if (!container) return;
        if (!res) {
            // No data at all → show full prompt
            _renderShapPrompt(container);
            return;
        }
        if (res.error_shap || (!res.mi || res.mi.length === 0) && (!res.shap_importance || res.shap_importance.length === 0)) {
            const errMsg = res.error_shap || '無資料，請重新執行 SHAP 分析';
            container.innerHTML = `<div style="padding:40px;text-align:center;color:#94a3b8;font-size:13px;">
                ⚠ ${errMsg}<br><br>
                <button onclick="window.rsmRunShap()" style="padding:8px 20px;background:#f59e0b;color:#fff;border:none;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;">重新執行</button>
            </div>`;
            return;
        }
        const mi = res.mi || [];
        const shapImp = res.shap_importance || [];
        const heatmap = res.heatmap || null;
        const r2 = res.r2 != null ? res.r2 : null;
        const r2Color = r2 == null ? '#94a3b8' : r2 >= 0.8 ? '#059669' : r2 >= 0.5 ? '#d97706' : '#dc2626';
        const r2Label = r2 == null ? 'N/A' : r2.toFixed(4);
        const r2Badge = r2 == null ? '' : `<span style="margin-left:8px;padding:2px 8px;border-radius:10px;background:${r2Color}18;color:${r2Color};font-size:11px;font-weight:700;">R² = ${r2Label}</span>`;
        const interLabels = heatmap ? (heatmap.factors || []) : [];
        const interMatrix = heatmap ? (heatmap.matrix || null) : null;

        // ── Prediction vs Actual chart ──
        const chartId = 'rsm-shap-pred-chart-' + Date.now();
        const hasChart = res.y_actual && res.y_pred && res.y_actual.length > 0;
        const overlayInfo = hasChart ? `<span id="rsm-shap-overlay-info" style="font-size:10px;color:#94a3b8;margin-left:auto;"></span>` : '';
        const chartHtml = hasChart ? `
            <div style="background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:12px 16px;margin-bottom:16px;">
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
                    <div style="font-size:13px;font-weight:700;color:#1e293b;">📈 預測 vs 實際</div>
                    <span style="font-size:10px;color:#94a3b8;">點擊下方因子可疊加副軸</span>
                    ${overlayInfo}
                </div>
                <div style="height:180px;position:relative;"><canvas id="${chartId}"></canvas></div>
            </div>` : '';

        // Click handler for overlay
        const escFactor = f => f.replace(/'/g, "\\'");

        // ── Section 1: MI ranking ──
        const miRows = mi.slice(0, 15).map((item, i) => {
            const bar = Math.round((item.mi / (mi[0]?.mi || 1)) * 100);
            return `<tr style="border-bottom:1px solid #f1f5f9;cursor:pointer;" onclick="window._rsmShapOverlay('${escFactor(item.factor)}')" title="點擊疊加 ${item.factor} 到圖表">
                <td style="padding:5px 8px;font-size:12px;color:#64748b;font-weight:600;">${i + 1}</td>
                <td style="padding:5px 8px;font-size:12px;color:#1e293b;font-weight:500;">${item.factor}</td>
                <td style="padding:5px 8px;">
                    <div style="display:flex;align-items:center;gap:6px;">
                        <div style="flex:1;height:8px;background:#f1f5f9;border-radius:4px;overflow:hidden;">
                            <div style="width:${bar}%;height:100%;background:#6366f1;border-radius:4px;"></div>
                        </div>
                        <span style="font-size:11px;color:#6366f1;font-weight:700;min-width:40px;">${item.mi.toFixed(4)}</span>
                    </div>
                </td>
            </tr>`;
        }).join('');

        // ── Section 2: SHAP importance with direction ──
        const maxShap = Math.max(...shapImp.map(s => s.importance), 0.0001);
        const shapRows = shapImp.slice(0, 15).map((item, i) => {
            const bar = Math.round((item.importance / maxShap) * 100);
            const dir = item.direction;
            const dirColor = dir > 0 ? '#059669' : '#dc2626';
            const dirSymbol = dir > 0 ? '▲ +' : '▼ ';
            const dirVal = Math.abs(dir) < 0.001 ? dir.toExponential(2) : dir.toFixed(4);
            return `<tr style="border-bottom:1px solid #f1f5f9;cursor:pointer;" onclick="window._rsmShapOverlay('${escFactor(item.factor)}')" title="點擊疊加 ${item.factor} 到圖表">
                <td style="padding:5px 8px;font-size:12px;color:#64748b;font-weight:600;">${i + 1}</td>
                <td style="padding:5px 8px;font-size:12px;color:#1e293b;font-weight:500;">${item.factor}</td>
                <td style="padding:5px 8px;">
                    <div style="display:flex;align-items:center;gap:6px;">
                        <div style="flex:1;height:8px;background:#f1f5f9;border-radius:4px;overflow:hidden;">
                            <div style="width:${bar}%;height:100%;background:#f59e0b;border-radius:4px;"></div>
                        </div>
                        <span style="font-size:11px;color:#f59e0b;font-weight:700;min-width:44px;">${item.importance.toFixed(4)}</span>
                    </div>
                </td>
                <td style="padding:5px 8px;font-size:11px;font-weight:700;color:${dirColor};">${dirSymbol}${dirVal}</td>
            </tr>`;
        }).join('');

        // ── Section 3: Interaction heatmap ──
        const heatmapId = 'rsm-shap-heatmap-' + Date.now();
        let heatmapHtml = '';
        if (interMatrix && interLabels.length > 0) {
            heatmapHtml = `
                <div style="margin-top:20px;">
                    <div style="font-size:13px;font-weight:700;color:#1e293b;margin-bottom:8px;">🔀 SHAP 交互效應矩陣 (Top ${interLabels.length})</div>
                    <div style="font-size:11px;color:#94a3b8;margin-bottom:12px;">顏色越深 = 交互效應越強 | 對角線 = 主效應</div>
                    <div id="${heatmapId}" style="overflow-x:auto;"></div>
                </div>`;
        }

        container.innerHTML = `
            ${chartHtml}
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;">
                <!-- MI -->
                <div style="background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:16px;">
                    <div style="font-size:13px;font-weight:700;color:#1e293b;margin-bottom:12px;">📈 MI 互訊息排名</div>
                    <div style="font-size:11px;color:#94a3b8;margin-bottom:8px;">衡量非線性相依程度（與 Y: ${targetName}）</div>
                    <table style="width:100%;border-collapse:collapse;">
                        <thead><tr style="border-bottom:2px solid #f1f5f9;">
                            <th style="padding:5px 8px;font-size:11px;color:#94a3b8;text-align:left;">#</th>
                            <th style="padding:5px 8px;font-size:11px;color:#94a3b8;text-align:left;">因子</th>
                            <th style="padding:5px 8px;font-size:11px;color:#94a3b8;text-align:left;">MI 分數</th>
                        </tr></thead>
                        <tbody>${miRows}</tbody>
                    </table>
                </div>
                <!-- SHAP -->
                <div style="background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:16px;">
                    <div style="font-size:13px;font-weight:700;color:#1e293b;margin-bottom:4px;display:flex;align-items:center;">🔥 SHAP 重要性 + 方向${r2Badge}</div>
                    <div style="font-size:11px;color:#94a3b8;margin-bottom:8px;">XGBoost TreeSHAP | 控制其他因子後的邊際貢獻</div>
                    <table style="width:100%;border-collapse:collapse;">
                        <thead><tr style="border-bottom:2px solid #f1f5f9;">
                            <th style="padding:5px 8px;font-size:11px;color:#94a3b8;text-align:left;">#</th>
                            <th style="padding:5px 8px;font-size:11px;color:#94a3b8;text-align:left;">因子</th>
                            <th style="padding:5px 8px;font-size:11px;color:#94a3b8;text-align:left;">|SHAP|</th>
                            <th style="padding:5px 8px;font-size:11px;color:#94a3b8;text-align:left;">方向</th>
                        </tr></thead>
                        <tbody>${shapRows}</tbody>
                    </table>
                </div>
            </div>
            ${heatmapHtml}`;

        // Render prediction vs actual chart
        if (hasChart) {
            if (_rsmShapChart) { try { _rsmShapChart.destroy(); } catch(e) {} _rsmShapChart = null; }
            _rsmShapOverlayFactor = '';
            const cvs = document.getElementById(chartId);
            if (cvs) {
                const yActual = res.y_actual;
                const yPred = res.y_pred;
                const indices = yActual.map((_, i) => i);
                _rsmShapChart = new Chart(cvs.getContext('2d'), {
                    type: 'line',
                    data: {
                        labels: indices,
                        datasets: [
                            {
                                label: targetName + ' (實際)',
                                data: yActual,
                                borderColor: '#3b82f6',
                                backgroundColor: '#3b82f620',
                                borderWidth: 1.5,
                                pointRadius: 1.5,
                                tension: 0.1,
                                yAxisID: 'y',
                                order: 2,
                            },
                            {
                                label: '預測 (XGBoost)',
                                data: yPred,
                                borderColor: '#f97316',
                                backgroundColor: 'transparent',
                                borderWidth: 2,
                                pointRadius: 2.5,
                                pointStyle: 'triangle',
                                pointBackgroundColor: '#f97316',
                                pointBorderColor: '#f97316',
                                borderDash: [6, 3],
                                tension: 0.1,
                                yAxisID: 'y',
                                order: 1,
                            },
                        ],
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        animation: { duration: 0 },
                        interaction: { mode: 'index', intersect: false },
                        plugins: {
                            legend: { position: 'top', labels: { font: { size: 10 }, boxWidth: 14, padding: 8, usePointStyle: true } },
                            tooltip: { titleFont: { size: 10 }, bodyFont: { size: 10 } },
                        },
                        scales: {
                            x: { display: true, ticks: { font: { size: 9 }, maxTicksLimit: 10 }, grid: { color: '#f1f5f9' } },
                            y: { position: 'left', ticks: { font: { size: 9 } }, grid: { color: '#f1f5f9' } },
                        },
                    },
                });

                // Store data reference for overlay
                _rsmShapChart._shapRes = res;
                _rsmShapChart._chartId = chartId;
            }
        }

        // Overlay handler: add/remove factor line
        window._rsmShapOverlay = function (factorName) {
            if (!_rsmShapChart || !_rsmShapChart._shapRes) return;
            const sRes = _rsmShapChart._shapRes;
            const fv = sRes.factor_values && sRes.factor_values[factorName];
            if (!fv) return;

            const chart = _rsmShapChart;
            const infoEl = document.getElementById('rsm-shap-overlay-info');

            // Toggle: if same factor, remove overlay
            if (_rsmShapOverlayFactor === factorName) {
                // Remove the overlay dataset (always the 3rd one, index 2)
                if (chart.data.datasets.length > 2) {
                    chart.data.datasets.splice(2, 1);
                }
                // Remove secondary axis
                delete chart.options.scales.y1;
                chart.update('none');
                _rsmShapOverlayFactor = '';
                if (infoEl) infoEl.textContent = '';
                return;
            }

            // Add or replace overlay dataset
            const ovDataset = {
                label: factorName,
                data: fv,
                borderColor: '#94a3b8',
                backgroundColor: 'transparent',
                borderWidth: 1,
                pointRadius: 0,
                tension: 0.1,
                yAxisID: 'y1',
            };

            if (chart.data.datasets.length > 2) {
                chart.data.datasets[2] = ovDataset;
            } else {
                chart.data.datasets.push(ovDataset);
            }

            // Add secondary Y axis
            chart.options.scales.y1 = {
                position: 'right',
                grid: { drawOnChartArea: false },
                ticks: { font: { size: 9 }, color: '#94a3b8' },
                title: { display: true, text: factorName.length > 20 ? factorName.substring(0,18) + '…' : factorName, font: { size: 10 }, color: '#94a3b8' },
            };

            chart.update('none');
            _rsmShapOverlayFactor = factorName;
            if (infoEl) infoEl.innerHTML = `副軸: <b style="color:#64748b;">${factorName}</b> <span style="cursor:pointer;color:#94a3b8;" onclick="window._rsmShapOverlay('${factorName.replace(/'/g, "\\'")}')" title="清除副軸">✕</span>`;
        };

        // Render heatmap if data available
        if (interMatrix && interLabels.length > 0) {
            _renderShapHeatmap(interMatrix, interLabels, heatmapId);
        }
    }

    function _renderShapHeatmap(matrix, labels, containerId) {
        const n = labels.length;
        const cellSize = Math.max(28, Math.min(52, Math.floor(560 / n)));
        const fontSize = Math.max(8, Math.min(12, cellSize - 14));

        // Find max value for color scaling (exclude diagonal)
        let maxVal = 0;
        for (let i = 0; i < n; i++) {
            for (let j = 0; j < n; j++) {
                if (i !== j) maxVal = Math.max(maxVal, matrix[i][j]);
            }
        }
        if (maxVal < 1e-10) maxVal = 1;

        // Build SVG heatmap
        const labelPad = 90;
        const totalW = labelPad + n * cellSize + 10;
        const totalH = labelPad + n * cellSize + 10;

        function _heatColor(val, isMain) {
            if (isMain) {
                // diagonal: blue scale
                const t = Math.min(1, val / maxVal);
                const r = Math.round(59 + (37 - 59) * t);
                const g = Math.round(130 + (99 - 130) * t);
                const b = Math.round(246 + (235 - 246) * t);
                return `rgb(${r},${g},${b})`;
            }
            // off-diagonal: orange-red scale
            const t = Math.min(1, val / maxVal);
            const r = Math.round(255);
            const g = Math.round(251 - 200 * t);
            const b = Math.round(235 - 235 * t);
            return `rgb(${r},${g},${b})`;
        }

        let cells = '';
        for (let i = 0; i < n; i++) {
            for (let j = 0; j < n; j++) {
                const val = matrix[i][j];
                const x = labelPad + j * cellSize;
                const y = labelPad + i * cellSize;
                const col = _heatColor(val, i === j);
                const textColor = (i === j || (val / maxVal) > 0.5) ? '#fff' : '#64748b';
                const displayVal = val < 0.001 ? val.toExponential(1) : val.toFixed(3);
                cells += `<g>
                    <rect x="${x}" y="${y}" width="${cellSize}" height="${cellSize}" fill="${col}" stroke="#fff" stroke-width="1"/>
                    <text x="${x + cellSize/2}" y="${y + cellSize/2 + fontSize/3}" text-anchor="middle" font-size="${fontSize}" fill="${textColor}" font-family="monospace">${displayVal}</text>
                </g>`;
            }
        }

        // X labels (top)
        let xLabels = '', yLabels = '';
        for (let i = 0; i < n; i++) {
            const x = labelPad + i * cellSize + cellSize / 2;
            const lbl = labels[i].length > 12 ? labels[i].slice(0, 11) + '…' : labels[i];
            xLabels += `<text x="${x}" y="${labelPad - 4}" text-anchor="end" transform="rotate(-45,${x},${labelPad-4})" font-size="${fontSize}" fill="#475569" font-family="sans-serif">${lbl}</text>`;
            const y = labelPad + i * cellSize + cellSize / 2;
            const lbl2 = labels[i].length > 12 ? labels[i].slice(0, 11) + '…' : labels[i];
            yLabels += `<text x="${labelPad - 6}" y="${y + fontSize/3}" text-anchor="end" font-size="${fontSize}" fill="#475569" font-family="sans-serif">${lbl2}</text>`;
        }

        const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${totalW}" height="${totalH}" style="max-width:100%;">
            ${cells}${xLabels}${yLabels}
        </svg>`;

        const el = document.getElementById(containerId);
        if (el) el.innerHTML = svg;
    }

    // ============ INITIALIZATION ============

    window._rsmGetShapBgFactor = () => _rsmShapBgFactor;

    // ── 靜默抓取 SHAP 資料（供筆記自動打包，不修改 UI） ──────────────────────
    window._rsmFetchShapForNote = async function () {
        if (!_rsmTargets.length) { console.warn('[SHAP note] no targets'); return null; }
        // 優先用已勾選的 factors，否則從 displayed terms 回推
        let _noteFactors = _rsmSelectedFactors.length ? _rsmSelectedFactors : (() => {
            const s = new Set();
            (window._rsmDisplayedTerms || []).forEach(t => {
                const base = t.name.replace(/[²³]/g, '');
                if (t.type === 'main') s.add(t.name);
                else base.split(' × ').forEach(f => s.add(f.trim()));
            });
            return [...s];
        })();
        if (!_noteFactors.length) { console.warn('[SHAP note] no factors'); return null; }
        console.log('[SHAP note] fetch with', _noteFactors.length, 'factors, targets:', _rsmTargets);
        const _buildBody = (bgFactor) => {
            const body = {
                file_id: currentFileId,
                targets: _rsmTargets,
                factors: _noteFactors,
                filters: (typeof _activeDataset !== 'undefined' && _activeDataset?.filters) ?
                    _activeDataset.filters.map(f => ({ column: f.col, keyword: '==' + String(f.value || ''), exclude_empty: false })) : [],
                exclude_indices: (typeof _clOutlierIndices !== 'undefined') ? _clOutlierIndices : [],
                exclude_cols: _getExcludedCols(),
            };
            if (bgFactor) body.background_factor = bgFactor;
            return body;
        };
        const sid = typeof getSessionId === 'function' ? getSessionId() : 'default';
        const _doFetch = async (bgFactor) => {
            const res = await fetch(`/api/data-prep/rsm-shap-analysis?session_id=${sid}`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(_buildBody(bgFactor)),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'SHAP 分析失敗');
            return data;
        };
        try {
            // Step 1: 取得基本 SHAP（無 bg factor）
            let basicData = _rsmShapResult;
            if (!basicData) {
                basicData = await _doFetch(null);
                _rsmShapResult = basicData;
                window._rsmShapResult = basicData;  // expose for data_preparation.html
            }
            // Step 2: 自動挑選 SHAP 重要性第一名的因子做 bg，取得 3因子資料
            const autoTarget = basicData.targets?.[0];
            const autoTopFactor = basicData.results?.[autoTarget]?.shap_importance?.[0]?.factor;
            // 若 _rsmShapInterData 已含有 background 資料，直接重用
            const existingBgData = _rsmShapInterData;
            const existingBgHasData = existingBgData && autoTarget &&
                existingBgData.results?.[autoTarget]?.background?.factors_by_group?.length > 0;
            let bgData = existingBgHasData ? existingBgData : null;
            if (!bgData && autoTopFactor) {
                bgData = await _doFetch(autoTopFactor);
                _rsmShapInterData = bgData;
                window._rsmShapInterData = bgData;  // expose for data_preparation.html
                window._rsmNoteAutoBgFactor = autoTopFactor;
            }
            return bgData || basicData;
        } catch (e) {
            console.error('[RSM note] SHAP fetch failed:', e.message, e);
            return null;
        }
    };

    // ── 自動抓取前N大主效應的條件式分析（供筆記自動打包） ──────────────────
    window._rsmFetchConditionalForNote = async function (topN) {
        const terms = window._rsmDisplayedTerms;
        if (!terms || !terms.length) return;
        const target = _rsmTargets[0] || _rsmTarget;
        if (!target) return;
        const sid = typeof getSessionId === 'function' ? getSessionId() : 'default';

        if (!window._rsmConditionalHistory) window._rsmConditionalHistory = [];

        // 取主效應前 topN 大（|r| 排序）
        const mainTerms = [...terms]
            .filter(t => t.type === 'main' && t.correlation != null)
            .sort((a, b) => Math.abs(b.correlation) - Math.abs(a.correlation))
            .slice(0, topN || 5);

        // 為每個主效應因子，找最強的交互夥伴（取 interaction terms 中含此因子、|r| 最大者）
        const interTerms = terms.filter(t => t.type === 'interaction' && t.correlation != null);
        const _bestPartner = (factorName) => {
            let best = null, bestR = -1;
            interTerms.forEach(t => {
                const parts = t.name.split(' × ');
                if (parts.includes(factorName)) {
                    const r = Math.abs(t.correlation);
                    if (r > bestR) { bestR = r; best = t; }
                }
            });
            if (!best) return null;
            const parts = best.name.split(' × ');
            const partner = parts.find(p => p !== factorName) || parts[1];
            return { termName: best.name, factors: [factorName, partner] };
        };

        const _buildCondBody = (termName, factors) => ({
            file_id: currentFileId,
            target,
            term_name: termName,
            factors,
            term_type: 'interaction',
            filters: (typeof _activeDataset !== 'undefined' && _activeDataset?.filters) ?
                _activeDataset.filters.map(f => ({ column: f.col, keyword: '==' + String(f.value || ''), exclude_empty: false })) : [],
            exclude_indices: (typeof _clOutlierIndices !== 'undefined') ? _clOutlierIndices : [],
            exclude_cols: _getExcludedCols(),
        });

        const _fisherZ = (r) => 0.5 * Math.log((1 + r) / (1 - Math.max(-0.9999, Math.min(0.9999, r))));
        const _erfApprox = (x) => {
            const t = 1 / (1 + 0.3275911 * x);
            return 1 - (0.254829592*t - 0.284496736*t*t + 1.421413741*t*t*t
                - 1.453152027*t*t*t*t + 1.061405429*t*t*t*t*t) * Math.exp(-x*x);
        };

        for (const tm of mainTerms) {
            // 找最強交互夥伴（後端要求 term_type=interaction, factors 至少2個）
            const partner = _bestPartner(tm.name);
            if (!partner) continue; // 此因子無交互項，跳過

            const key = `${tm.name}||auto||${target}`;
            if (window._rsmConditionalHistory.find(e => e.key === key)) continue; // 已有快取
            try {
                const res = await fetch(`/api/data-prep/rsm-conditional-data?session_id=${sid}`, {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(_buildCondBody(partner.termName, partner.factors)),
                });
                const data = await res.json();
                if (!res.ok || !data.groups) continue;

                const rVals = data.groups.map(g => g.r);
                const rRange = Math.max(...rVals) - Math.min(...rVals);
                const verdict = rRange > 0.3 ? '交互顯著' : rRange > 0.1 ? '輕微交互' : '無明顯交互';
                const _sr = v => (v >= 0 ? '+' : '') + v.toFixed(3);
                const p33 = data.p33, p67 = data.p67, cv = data.condition_var;
                const _range = (label) => {
                    const lo = label.toLowerCase();
                    if (lo === 'low')  return `${cv} ≤ ${p33}`;
                    if (lo === 'mid')  return `${p33} < ${cv} ≤ ${p67}`;
                    if (lo === 'high') return `${cv} > ${p67}`;
                    return label;
                };

                // Fisher Z (Low vs High)
                const gLow  = data.groups.find(g => g.label.toLowerCase() === 'low');
                const gHigh = data.groups.find(g => g.label.toLowerCase() === 'high');
                let fisherP = 1;
                if (gLow && gHigh && gLow.n > 3 && gHigh.n > 3) {
                    const zDiff = _fisherZ(gHigh.r) - _fisherZ(gLow.r);
                    const se = Math.sqrt(1 / (gLow.n - 3) + 1 / (gHigh.n - 3));
                    const zStat = Math.abs(zDiff / se);
                    fisherP = 2 * (1 - 0.5 * (1 + _erfApprox(zStat / Math.sqrt(2))));
                }
                const interSig = fisherP < 0.05 ? '★ 顯著' : fisherP < 0.1 ? '△ 邊緣顯著' : '○ 不顯著';

                // x 軸是第一個因子（tm.name），條件是 cv（後端自動挑的條件因子）
                const lines = [
                    `條件式分析：「${tm.name}」對「${target}」的相關係數，隨條件因子改變`,
                    `  分析項: ${partner.termName}  條件因子: ${cv}（分三組，閾值 p33=${p33}，p67=${p67}）`,
                    `  交互顯著性: ${interSig}（Fisher Z Low vs High，p=${fisherP < 0.001 ? '<0.001' : fisherP.toFixed(3)}）`,
                ];
                data.groups.forEach(g => {
                    const sig = g.p_value < 0.05 ? '（p<0.05 顯著）' : '（n.s.）';
                    const dir = g.r > 0.05 ? '正相關' : g.r < -0.05 ? '負相關' : '無相關';
                    lines.push(`  ${g.label}（${_range(g.label)}, n=${g.n}）: r = ${_sr(g.r)}  → ${dir} ${sig}`);
                });
                lines.push(`  Δr = ${rRange.toFixed(3)}  ${verdict}`);
                const pos = data.groups.filter(g => g.r > 0.05).length;
                const neg = data.groups.filter(g => g.r < -0.05).length;
                if (pos > 0 && neg > 0) lines.push(`  ⚠ 方向反轉：在不同條件下正負相關並存`);

                window._rsmConditionalHistory.push({ key, text: lines.join('\n'), fisherP, termName: tm.name, condVar: cv, groups: data.groups });
            } catch (e) {
                console.warn('[RSM note] auto conditional fetch failed:', tm.name, e.message);
            }
        }

        // ── 自動抓取三階項前 N 大（3唯一因子→Trellis，2唯一因子→條件式） ────────
        const cubicTerms = [...terms]
            .filter(t => t.type === 'cubic' && t.correlation != null)
            .sort((a, b) => Math.abs(b.correlation) - Math.abs(a.correlation))
            .slice(0, topN || 5);

        const _commonBody = (termName, factors, termType) => ({
            file_id: currentFileId, target,
            term_name: termName, factors, term_type: termType,
            filters: (typeof _activeDataset !== 'undefined' && _activeDataset?.filters) ?
                _activeDataset.filters.map(f => ({ column: f.col, keyword: '==' + String(f.value || ''), exclude_empty: false })) : [],
            exclude_indices: (typeof _clOutlierIndices !== 'undefined') ? _clOutlierIndices : [],
            exclude_cols: _getExcludedCols(),
        });

        for (const ct of cubicTerms) {
            // 去掉次方符號後取唯一因子
            const rawFactors = ct.name.replace(/[²³]/g, '').split(' × ').map(f => f.trim());
            const uniqueFactors = [...new Set(rawFactors)];
            if (uniqueFactors.length < 2) continue;

            const isTrellisTerm = uniqueFactors.length >= 3;
            const key = `${ct.name}||${isTrellisTerm ? 'trellis' : 'auto'}||${target}`;
            if (window._rsmConditionalHistory.find(e => e.key === key)) continue;

            try {
                if (isTrellisTerm) {
                    // ── Trellis（真正 3+ 因子）──
                    const res = await fetch(`/api/data-prep/rsm-trellis-data?session_id=${sid}`, {
                        method: 'POST', headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(_commonBody(ct.name, uniqueFactors, 'cubic')),
                    });
                    const data = await res.json();
                    if (!res.ok || !data.cells) continue;
                    const cells = data.cells || [];
                    const _sr = v => v != null ? ((v >= 0 ? '+' : '') + v.toFixed(3)) : '—';
                    const lines = [
                        `Trellis：「${ct.name}」× 目標「${target}」`,
                        `  A: ${data.factor_a}（中位=${data.a_median}）  B: ${data.factor_b}（中位=${data.b_median}）`,
                    ];
                    cells.forEach(c => {
                        const dir = c.r > 0.05 ? '正相關' : c.r < -0.05 ? '負相關' : '無相關';
                        lines.push(`  [${c.label.replace('_Low','↓').replace('_High','↑')}] n=${c.n}  r=${_sr(c.r)}  → ${dir}`);
                    });
                    const aSplits = data.a_splits || [
                        { label: 'A低', range_min: data.a_min ?? '?', range_max: data.a_median ?? '?' },
                        { label: 'A高', range_min: data.a_median ?? '?', range_max: data.a_max ?? '?' },
                    ];
                    const bSplits = data.b_splits || [
                        { label: 'B低', range_min: data.b_min ?? '?', range_max: data.b_median ?? '?' },
                        { label: 'B高', range_min: data.b_median ?? '?', range_max: data.b_max ?? '?' },
                    ];
                    window._rsmConditionalHistory.push({
                        key, text: lines.join('\n'), fisherP: 1.0,
                        termName: ct.name, condVar: data.factor_a,
                        isTrellis: true, cells,
                        trellisData: {
                            factor_a: data.factor_a, factor_b: data.factor_b, factor_c: data.factor_c,
                            a_median: data.a_median, b_median: data.b_median,
                            nA: aSplits.length, nB: bSplits.length, aSplits, bSplits,
                        },
                    });
                } else {
                    // ── 條件式（2唯一因子的 cubic，走同 interaction 路徑）──
                    const res = await fetch(`/api/data-prep/rsm-conditional-data?session_id=${sid}`, {
                        method: 'POST', headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(_commonBody(ct.name, uniqueFactors, 'interaction')),
                    });
                    const data = await res.json();
                    if (!res.ok || !data.groups) continue;
                    const rVals = data.groups.map(g => g.r);
                    const rRange = Math.max(...rVals) - Math.min(...rVals);
                    const verdict = rRange > 0.3 ? '交互顯著' : rRange > 0.1 ? '輕微交互' : '無明顯交互';
                    const _sr = v => (v >= 0 ? '+' : '') + v.toFixed(3);
                    const cv = data.condition_var, p33 = data.p33, p67 = data.p67;
                    const gLow = data.groups.find(g => g.label.toLowerCase() === 'low');
                    const gHigh = data.groups.find(g => g.label.toLowerCase() === 'high');
                    let fisherP = 1;
                    if (gLow && gHigh && gLow.n > 3 && gHigh.n > 3) {
                        const zDiff = _fisherZ(gHigh.r) - _fisherZ(gLow.r);
                        const se = Math.sqrt(1 / (gLow.n - 3) + 1 / (gHigh.n - 3));
                        fisherP = 2 * (1 - 0.5 * (1 + _erfApprox(Math.abs(zDiff / se) / Math.sqrt(2))));
                    }
                    const lines = [
                        `條件式（三階）：「${ct.name}」對「${target}」`,
                        `  條件因子: ${cv}（p33=${p33}, p67=${p67}）  ${fisherP < 0.05 ? '★顯著' : fisherP < 0.1 ? '△邊緣' : '○不顯著'}（p=${fisherP.toFixed(3)}）`,
                    ];
                    data.groups.forEach(g => {
                        const dir = g.r > 0.05 ? '正相關' : g.r < -0.05 ? '負相關' : '無相關';
                        lines.push(`  ${g.label}（n=${g.n}）: r=${_sr(g.r)} → ${dir}`);
                    });
                    lines.push(`  Δr=${rRange.toFixed(3)}  ${verdict}`);
                    window._rsmConditionalHistory.push({ key, text: lines.join('\n'), fisherP, termName: ct.name, condVar: cv, groups: data.groups });
                }
            } catch (e) {
                console.warn('[RSM note] auto cubic fetch failed:', ct.name, e.message);
            }
        }
    };

    // ── 產生 SHAP 交互文字摘要（topN 對/因子） ──────────────────────────────
    window._rsmGetShapInterNoteText = function (topN) {
        // bgData 含 background.factors_by_group（3因子），basicData 含 shap_interaction（4因子交互對）
        const bgData = _rsmShapInterData;
        const basicData = _rsmShapResult;
        const shapData = bgData || basicData;
        if (!shapData) return null;
        const N = topN || 5;
        // 優先用使用者手動選的 bg factor，其次用筆記自動挑的
        const bgFactor = _rsmShapBgFactor || window._rsmNoteAutoBgFactor || null;
        const targets = shapData.targets || [];
        const bgResults = bgData?.results || {};
        const basicResults = basicData?.results || bgResults;
        const lines = [];

        targets.forEach(t => {
            const bgRes = bgResults[t];
            const baseRes = basicResults[t] || bgRes;
            if (!bgRes && !baseRes) return;
            const r2 = (baseRes?.r2 ?? bgRes?.r2) != null
                ? `  R²=${(baseRes?.r2 ?? bgRes?.r2).toFixed(4)}` : '';
            lines.push(`  目標: ${t}${r2}${bgFactor ? `  背景條件因子: ${bgFactor}` : ''}`);

            // ── 共用 helpers（3因子 + 4因子都會用到） ──
            const bgMeta = bgRes?.background;
            const bgGroups = bgMeta?.factors_by_group;
            const _f3 = v => v != null ? Number(v).toFixed(3) : '?';
            const p33Str = _f3(bgMeta?.p33), p67Str = _f3(bgMeta?.p67);
            const minStr = _f3(bgMeta?.min), maxStr = _f3(bgMeta?.max);
            const _sg = v => v == null ? '—' : (v >= 0 ? '+' : '') + v.toFixed(3);
            const _sr4 = v => v != null ? ((v >= 0 ? '+' : '') + v.toFixed(4)) : '—';
            const _flipTag = (rLow, rHigh) => {
                if (rLow == null || rHigh == null) return '';
                const posLow = rLow > 0.03, negLow = rLow < -0.03;
                const posHigh = rHigh > 0.03, negHigh = rHigh < -0.03;
                if ((posLow && negHigh) || (negLow && posHigh)) return '  ⚠方向反轉';
                return '';
            };
            const _mainCorrMap = {};
            (window._rsmDisplayedTerms || []).forEach(tm => {
                if (tm.type === 'main' && tm.correlation != null) _mainCorrMap[tm.name] = tm.correlation;
            });

            // Shared bg metadata (used in both 3-factor and 4-factor note sections)
            const isCatNote     = bgMeta?.bg_type === 'categorical';
            const noteGroupKeys  = bgMeta?.group_keys  || ['low', 'mid', 'high'];
            const noteGroupNames = bgMeta?.group_names || ['低組', '中組', '高組'];

            // 3因子：因子在 bgFactor 各分組下的 SHAP 差異（delta 排序）
            if (bgGroups?.length && bgFactor) {
                const sorted = [...bgGroups].sort((a, b) => b.delta - a.delta);

                // ── 群組優先的樹狀結構 ──
                lines.push(`  ▶ 條件效應分析`);
                if (isCatNote) {
                    lines.push(`    條件因子「${bgFactor}」類別：${noteGroupNames.join(' / ')}`);
                } else {
                    lines.push(`    條件因子「${bgFactor}」∈ [${minStr}, ${maxStr}]，分三組`);
                }
                lines.push('');

                const grpDefs = noteGroupKeys.map((gk, gi) => ({
                    key:   gk,
                    label: noteGroupNames[gi] || gk,
                    range: isCatNote ? '' : (gi === 0 ? `[${minStr}, ${p33Str}]` : gi === 1 ? `[${p33Str}, ${p67Str}]` : `[${p67Str}, ${maxStr}]`),
                    shap:  f => f[gk]    ?? 0,
                    r:     f => f[`${gk}_r`] ?? 0,
                }));
                const topN = sorted.slice(0, N);
                grpDefs.forEach((g, gi) => {
                    const branch = gi < grpDefs.length - 1 ? '├─' : '└─';
                    const inner  = gi < grpDefs.length - 1 ? '│' : ' ';
                    lines.push(`    ${branch} ${g.label}${g.range ? ' ' + g.range : ''}`);
                    // 在本組內依 SHAP 大小重新排序
                    const inGroup = [...topN].sort((a, b) => g.shap(b) - g.shap(a));
                    inGroup.forEach((f, fi) => {
                        const isLast = fi === inGroup.length - 1;
                        const fb = isLast ? '└─' : '├─';
                        const globalR = _mainCorrMap[f.factor];
                        const globalStr = globalR != null ? `  整體r=${_sr4(globalR)}` : '';
                        const flip = !isCatNote ? _flipTag(f.low_r, f.high_r) : '';
                        lines.push(`    ${inner}   ${fb} ${f.factor}`);
                        lines.push(`    ${inner}   │   SHAP=${_sg(g.shap(f))}  r(${g.label})=${_sr4(g.r(f))}${globalStr}${flip}`);
                    });
                    lines.push(`    ${inner}`);
                });

                // 跨組摘要（Δ排序）
                lines.push(`    跨組影響差異摘要（Δ排序）：`);
                topN.forEach((f, i) => {
                    const globalR = _mainCorrMap[f.factor];
                    const flip = !isCatNote ? _flipTag(f[`${noteGroupKeys[0]}_r`], f[`${noteGroupKeys[noteGroupKeys.length-1]}_r`]) : '';
                    const branch = i < topN.length - 1 ? '├─' : '└─';
                    lines.push(`    ${branch} ${f.factor}`);
                    lines.push(`    │   整體r=${_sr4(globalR)}  Δ(SHAP)=${f.delta.toFixed(4)}`);
                    const rSummary = noteGroupKeys.map((gk, gi) => `${noteGroupNames[gi]}r=${_sr4(f[`${gk}_r`])}`).join(' → ');
                    lines.push(`    │   ${rSummary}${flip}`);
                });
                lines.push('');
            }

            // 雙因子 SHAP 交互對
            const pairs = ((bgRes || baseRes)?.shap_interaction || []).slice(0, N);
            if (pairs.length) {
                const _termMap = {}, _termMapMain = {};
                (window._rsmDisplayedTerms || []).forEach(tm => {
                    if (tm.correlation != null) {
                        if (tm.type === 'interaction') _termMap[tm.name] = tm.correlation;
                        if (tm.type === 'main')        _termMapMain[tm.name] = tm.correlation;
                    }
                });
                const _lookupR = (fa, fb) => _termMap[`${fa} × ${fb}`] ?? _termMap[`${fb} × ${fa}`] ?? null;
                const _sr = v => (v >= 0 ? '+' : '') + v.toFixed(4);
                const bgCtx = bgFactor
                    ? (isCatNote
                        ? `  條件背景因子：${bgFactor}（${noteGroupNames.join('/')}）`
                        : `  條件背景因子：${bgFactor} ∈ [${minStr ?? '?'}, ${maxStr ?? '?'}]`)
                    : '';
                lines.push(`  ▶ 雙因子 SHAP 交互前${N}名${bgCtx}`);
                lines.push(`    說明：SHAP交互強度 = 兩因子對目標預測的聯合貢獻量`);
                lines.push('');
                pairs.forEach((p, i) => {
                    const r   = _lookupR(p.factor_a, p.factor_b);
                    const rA  = _termMapMain[p.factor_a];
                    const rB  = _termMapMain[p.factor_b];
                    const dir = r != null ? (r > 0 ? '同向協同↑' : '反向拮抗↕') : '—';
                    const isLast = i === pairs.length - 1;
                    const branch = isLast ? '└─' : '├─';
                    const inner  = isLast ? ' ' : '│';
                    lines.push(`    ${branch} #${i+1}  SHAP交互強度=${p.interaction.toFixed(4)}  交互項r=${r != null ? _sr(r) : '—'}（${dir}）`);
                    lines.push(`    ${inner}   ├─ ${p.factor_a}  整體r=${_sr4(rA)}`);
                    lines.push(`    ${inner}   └─ ${p.factor_b}  整體r=${_sr4(rB)}`);
                });
                lines.push('');
            }
        });

        return lines.length > 0 ? lines.join('\n') : null;
    };

})();
