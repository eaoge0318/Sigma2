/**
 * Association Analysis Manager - Apriori 關聯規則分析
 * 完全獨立模組 (IIFE)
 */
(function () {
    'use strict';

    // ────────────────────────────────────────────────
    // State
    // ────────────────────────────────────────────────
    let _assocStep = 1;
    let _assocSelectedCols = [];        // [{name, dtype, binningRules:[]}]
    let _assocBinningCache = {};        // colName → binningRules[] (for unselected cols)
    let _assocConsequentCol = '';
    let _assocConsequentVal = '';
    let _assocMinSupport = 0.005;
    let _assocMinConfidence = 0.005;
    let _assocMinLift = 0.005;
    let _assocMinCount = 30;
    let _assocLastResult = null;
    let _assocRunning = false;
    let _assocSortCol = 'lift';
    let _assocSortAsc = false;
    let _assocResultView = 'table';  // 'table' | 'chart'
    let _assocFocusedCol = null;
    let _assocSearchTerm = '';
    let _assocLastDistData = null;
    let _assocTypeOverride = {};        // colName → 'histogram'|'categorical'
    let _assocViewModes = {};           // colName → 'histogram'|'scatter'
    let _assocDragState = null;        // scatter box-select drag state
    let _scatterHandlersAdded = false;
    let _assocExcludeValues = {};      // {"*": ["KD8"]} 或 {"col": ["val1"]}

    // ────────────────────────────────────────────────
    // Public API
    // ────────────────────────────────────────────────
    window.assocInit = function () {
        _assocStep = 1;
        _assocSelectedCols = [];
        _assocBinningCache = {};
        _assocConsequentCol = '';
        _assocConsequentVal = '';
        _assocLastResult = null;
        _assocFocusedCol = null;
        _assocSearchTerm = '';
        _assocLastDistData = null;
        _assocTypeOverride = {};
        _assocViewModes = {};
        _assocDragState = null;
        _assocExcludeValues = {};
        const si = document.getElementById('assoc-search-input');
        if (si) si.value = '';
        _renderStep1();
        _gotoStep(1);
    };

    window.assocGotoStep = _gotoStep;
    window.assocRun = _run;

    window.assocOnCleaningChanged = function () {
        if (_assocLastResult !== null) { _assocLastResult = null; _run(); }
    };

    window.assocGetNoteText = function (topN = 15) {
        if (!_assocLastResult) return null;
        const rules = _assocLastResult.rules || [];
        const total = _assocLastResult.total_transactions || 0;

        // 解析目標欄位的分組定義，把 G1/G2 對應的實際條件附上
        const consBinRules = _getRules(_assocConsequentCol) || [];
        const matchedBin = consBinRules.find(r => (r.label || '') === _assocConsequentVal);
        let targetDesc = `${_assocConsequentCol}=${_assocConsequentVal}`;
        if (matchedBin) {
            const op = matchedBin.op;
            if ((op === '~' || op === 'idx~') && matchedBin.lo != null && matchedBin.hi != null) {
                targetDesc += ` (${matchedBin.lo} ~ ${matchedBin.hi})`;
            } else if ((op === '>' || op === 'idx>') && matchedBin.val != null) {
                targetDesc += ` (> ${matchedBin.val})`;
            } else if (['>=','<','<=','=='].includes(op) && matchedBin.val != null) {
                targetDesc += ` (${op} ${matchedBin.val})`;
            }
        }
        const target = targetDesc;
        if (!rules.length) return `關聯分析 共 0 條規則 | 目標: ${target}`;

        // 最低樣本門檻：至少 1% 總筆數 或 50 筆，取較大值
        // 避免以少數樣本撐起高 confidence 的規則混入結果
        const minCount = Math.max(50, Math.round(total * 0.01));
        const filtered = rules.filter(r => Math.round(r.support * total) >= minCount);

        // 排序：符合率（confidence）降冪 → 覆蓋範圍（support）降冪
        const top = [...filtered]
            .sort((a, b) => b.confidence - a.confidence || b.support - a.support)
            .slice(0, topN);

        const lines = top.map((r, i) => {
            const conds = r.antecedents.join(' × ');
            const supN = Math.round(r.support * total);
            const confPct = (r.confidence * 100).toFixed(1);
            return `${i + 1}. ${conds}  符合率 ${confPct}% (${supN}/${total} 筆)  關聯強度 ${r.lift.toFixed(2)}`;
        });

        const filterNote = filtered.length < rules.length
            ? `（已過濾樣本數 < ${minCount} 筆的規則，剩 ${filtered.length} 條）`
            : '';
        return `關聯分析 共 ${rules.length} 條規則 | 目標: ${target} | 交易數: ${total}\n${filterNote}\n\n前 ${top.length} 條（依符合率、覆蓋範圍排序）:\n${lines.join('\n')}`;
    };

    // ────────────────────────────────────────────────
    // Helpers
    // ────────────────────────────────────────────────
    function _getExcludeCols() {
        if (typeof _clExcludedCols === 'undefined') return [];
        return _clExcludedCols instanceof Set ? [..._clExcludedCols] : (_clExcludedCols || []);
    }
    function _getExcludeIndices() {
        return (typeof _clOutlierIndices !== 'undefined' && _clOutlierIndices) ? _clOutlierIndices : [];
    }
    function _getSid() {
        return typeof getSessionId === 'function' ? getSessionId() : 'default';
    }
    function _getNumericFields() {
        if (typeof allFields === 'undefined') return [];
        const ex = new Set(_getExcludeCols());
        return allFields.filter(f => f.dtype === 'numeric' && !ex.has(f.name));
    }
    function _getCategoryFields() {
        if (typeof allFields === 'undefined') return [];
        const ex = new Set(_getExcludeCols());
        return allFields.filter(f => f.dtype !== 'numeric' && !ex.has(f.name));
    }
    function _colEntry(name) { return _assocSelectedCols.find(c => c.name === name); }
    function _esc(str) { return str.replace(/[^a-zA-Z0-9]/g, '_'); }
    function _escStr(str) { return str.replace(/\\/g, '\\\\').replace(/'/g, "\\'"); }

    /** 取得欄位的 binning rules（不管是否已勾選） */
    function _getRules(name) {
        const e = _colEntry(name);
        return e ? e.binningRules : (_assocBinningCache[name] || []);
    }
    /** 新增一條 rule */
    function _pushRule(name, rule) {
        const e = _colEntry(name);
        if (e) { e.binningRules.push(rule); return; }
        if (!_assocBinningCache[name]) _assocBinningCache[name] = [];
        _assocBinningCache[name].push(rule);
    }
    /** 刪除一條 rule */
    function _spliceRule(name, idx) {
        const e = _colEntry(name);
        if (e) { e.binningRules.splice(idx, 1); return; }
        if (_assocBinningCache[name]) _assocBinningCache[name].splice(idx, 1);
    }
    /** 修改 rule 的某個欄位 */
    function _patchRule(name, idx, field, value) {
        const rules = _getRules(name);
        if (!rules[idx]) return;
        rules[idx][field] = value;
    }

    // ────────────────────────────────────────────────
    // Step navigation
    // ────────────────────────────────────────────────
    function _gotoStep(n) {
        _assocStep = n;
        ['assoc-step1', 'assoc-step2', 'assoc-step3'].forEach((id, i) => {
            const el = document.getElementById(id);
            if (el) el.style.display = (i + 1 === n) ? 'flex' : 'none';
        });
        const step1Done = _assocSelectedCols.length >= 1;
        const step2Done = !!(_assocConsequentCol && _assocConsequentVal);
        const stepDone = [false, step1Done, step2Done, false];
        [1, 2, 3].forEach(i => {
            const tab = document.getElementById(`assoc-tab-${i}`);
            if (!tab) return;
            tab.classList.toggle('rsm-step-active', i === n);
            tab.classList.toggle('rsm-step-done', stepDone[i]);
        });
        if (n === 1) _renderStep1();
        if (n === 2) _renderStep2();
        if (n === 3) _renderStep3();
        _updateRunBtn();
    }

    function _updateRunBtn() {
        const btn = document.getElementById('assoc-run-btn');
        if (!btn) return;
        const ready = _assocSelectedCols.length >= 2 && _assocConsequentCol && _assocConsequentVal;
        btn.disabled = !ready || _assocRunning;
        btn.style.background = (ready && !_assocRunning) ? '#7c3aed' : '#e2e8f0';
        btn.style.color = (ready && !_assocRunning) ? '#fff' : '#64748b';
        btn.style.cursor = (ready && !_assocRunning) ? 'pointer' : 'not-allowed';
        btn.textContent = _assocRunning ? '分析中...' : '執行分析';
        // 同步更新步驟完成狀態（綠色打勾）
        const step1Done = _assocSelectedCols.length >= 1;
        const step2Done = !!(_assocConsequentCol && _assocConsequentVal);
        const stepDone = [false, step1Done, step2Done, false];
        [1, 2, 3].forEach(i => {
            const tab = document.getElementById(`assoc-tab-${i}`);
            if (!tab) return;
            tab.classList.toggle('rsm-step-done', stepDone[i] && i !== _assocStep);
        });
    }

    // ────────────────────────────────────────────────
    // Step 1 — 選欄位（左側）
    // ────────────────────────────────────────────────
    function _renderStep1(skipDist = false) {
        const area = document.getElementById('assoc-col-area');
        if (!area) return;
        const q = _assocSearchTerm;
        const numFields = _getNumericFields().filter(f => !q || f.name.toLowerCase().includes(q));
        const catFields = _getCategoryFields().filter(f => !q || f.name.toLowerCase().includes(q));

        let html = ``;

        if (catFields.length) {
            html += `<div style="font-size:11px;font-weight:700;color:#0891b2;margin-bottom:4px;">類別欄位</div>`;
            catFields.forEach(f => {
                const checked = !!_colEntry(f.name);
                const focused = _assocFocusedCol === f.name;
                html += `<div style="display:flex;align-items:center;gap:6px;padding:5px 6px;border-radius:6px;font-size:12px;color:#334155;${focused ? 'background:#e0f2fe;outline:1.5px solid #0891b2;' : checked ? 'background:#f0fdf4;' : ''}">
                    <input type="checkbox" ${checked ? 'checked' : ''} onchange="assocToggleCol('${_escStr(f.name)}','cat')" style="accent-color:#0891b2;flex-shrink:0;">
                    <span onclick="assocFocusCol('${_escStr(f.name)}')" style="cursor:pointer;flex:1;">${f.name}</span>
                </div>`;
            });
        }

        if (numFields.length) {
            html += `<div style="font-size:11px;font-weight:700;color:#7c3aed;margin-top:10px;margin-bottom:4px;">數值欄位（設定分組後勾選）</div>`;
            numFields.forEach(f => {
                const checked = !!_colEntry(f.name);
                const focused = _assocFocusedCol === f.name;
                const ruleCount = _getRules(f.name).length;
                html += `<div style="margin-bottom:2px;">
                    <div style="display:flex;align-items:center;gap:6px;padding:5px 6px;border-radius:6px;font-size:12px;color:#334155;${focused ? 'background:#ede9fe;outline:1.5px solid #7c3aed;' : checked ? 'background:#faf5ff;' : ''}">
                        <input type="checkbox" ${checked ? 'checked' : ''} onchange="assocToggleCol('${_escStr(f.name)}','num')" style="accent-color:#7c3aed;flex-shrink:0;">
                        <span onclick="assocFocusCol('${_escStr(f.name)}')" style="cursor:pointer;flex:1;">${f.name}</span>
                        ${ruleCount ? `<span style="font-size:10px;background:#7c3aed;color:#fff;border-radius:8px;padding:1px 5px;">${ruleCount}</span>` : ''}
                    </div>
                </div>`;
            });
        }

        if (!catFields.length && !numFields.length) {
            html = `<div style="color:#94a3b8;font-size:12px;text-align:center;padding:20px 0;">${_assocSearchTerm ? '無符合搜尋的欄位' : '請先載入資料'}</div>`;
        }

        const _areaSt = area.scrollTop;
        area.innerHTML = html;
        area.scrollTop = _areaSt;
        _updateStep1Count();
        if (!skipDist) _renderDistribution();
    }

    function _updateStep1Count() {
        const cnt = document.getElementById('assoc-sel-count');
        if (cnt) cnt.textContent = `已選 ${_assocSelectedCols.length} 個欄位`;
        _renderChips();
    }

    function _renderChips() {
        const el = document.getElementById('assoc-selected-chips');
        if (!el) return;
        if (!_assocSelectedCols.length) {
            el.innerHTML = '<span style="font-size:11px;color:#cbd5e1;">尚未勾選欄位</span>';
            return;
        }
        el.innerHTML = _assocSelectedCols.map(c => {
            const isCat = c.dtype !== 'numeric';
            const color = isCat ? '#0891b2' : '#7c3aed';
            const bg = isCat ? '#e0f2fe' : '#ede9fe';
            const focused = _assocFocusedCol === c.name;
            const esc = _escStr(c.name);
            return `<div onclick="assocFocusCol('${esc}')" style="display:inline-flex;align-items:center;gap:3px;padding:3px 8px;border-radius:12px;font-size:11px;font-weight:600;cursor:pointer;flex-shrink:0;white-space:nowrap;background:${focused ? color : bg};color:${focused ? '#fff' : color};">
                ${c.name}
                <span onclick="event.stopPropagation();assocToggleCol('${esc}','${c.dtype}')" style="font-size:9px;opacity:0.7;margin-left:1px;line-height:1;">✕</span>
            </div>`;
        }).join('');
    }

    // ────────────────────────────────────────────────
    // Distribution fetch
    // ────────────────────────────────────────────────
    let _distDebounceTimer = null;

    async function _renderDistribution() {
        const distArea = document.getElementById('assoc-dist-area');
        if (!distArea) return;
        if (!_assocFocusedCol) {
            distArea.innerHTML = `<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;color:#cbd5e1;gap:8px;"><div style="font-size:28px;">📊</div><div style="font-size:12px;">點擊欄位名稱查看分布</div></div>`;
            return;
        }
        if (_distDebounceTimer) clearTimeout(_distDebounceTimer);
        _distDebounceTimer = setTimeout(async () => {
            distArea.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:60px;color:#94a3b8;font-size:12px;gap:8px;"><div style="width:16px;height:16px;border:2px solid #e2e8f0;border-top-color:#7c3aed;border-radius:50%;animation:_clSpin 0.7s linear infinite;"></div>載入中...</div>`;
            const col = _colEntry(_assocFocusedCol);
            try {
                const res = await fetch('/api/association/col_distribution', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        file_id: currentFileId,
                        session_id: _getSid(),
                        cols: [_assocFocusedCol],
                        binning_rules: {},     // always fetch raw data; rules are overlaid client-side
                        min_count: col ? _assocMinCount : 1,
                        exclude_indices: _getExcludeIndices(),
                        exclude_cols: _getExcludeCols(),
                    }),
                });
                const data = await res.json();
                _assocLastDistData = data.distributions || {};
                _renderDistCards(_assocLastDistData);
            } catch (e) {
                console.error('[assoc dist]', e);
                distArea.innerHTML = `<div style="color:#ef4444;font-size:12px;padding:12px;">載入失敗: ${e.message}</div>`;
            }
        }, 500);
    }

    // ────────────────────────────────────────────────
    // Distribution render (right panel)
    // ────────────────────────────────────────────────
    function _renderDistCards(distributions) {
        const distArea = document.getElementById('assoc-dist-area');
        if (!distArea) return;
        const colName = _assocFocusedCol;
        if (!colName || !distributions[colName]) {
            distArea.innerHTML = `<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;color:#cbd5e1;gap:8px;"><div style="font-size:28px;">📊</div><div style="font-size:12px;">點擊欄位名稱查看分布</div></div>`;
            return;
        }

        const rawData = distributions[colName];
        const baseData = Array.isArray(rawData) ? { type: 'categorical', items: rawData } : rawData;
        const effectiveType = _assocTypeOverride[colName] || baseData.type;
        const isHist = effectiveType === 'histogram';
        const isScatter = (isHist && (_assocViewModes[colName] === 'scatter'));
        const colorMain = isHist ? '#7c3aed' : '#0891b2';
        const colorBg = isHist ? '#ede9fe' : '#e0f2fe';
        const isSelected = !!_colEntry(colName);
        const esc = _escStr(colName);

        // Header buttons
        let typeBtns = `<button onclick="assocToggleColType('${esc}')" style="padding:3px 8px;font-size:10px;border:1px solid #cbd5e1;border-radius:6px;background:#fff;color:#64748b;cursor:pointer;">${isHist ? '切 Aa' : '切 #'}</button>`;
        if (isHist) {
            const scatterActive = isScatter;
            // 值域分組（直方圖）= 預設；Index分組（散布圖）= 切換後
            typeBtns += `<button onclick="assocToggleScatter('${esc}')" style="padding:3px 8px;font-size:10px;border:1px solid ${scatterActive ? '#0891b2' : '#cbd5e1'};border-radius:6px;background:${scatterActive ? '#e0f2fe' : '#fff'};color:${scatterActive ? '#0891b2' : '#64748b'};cursor:pointer;margin-left:4px;">${scatterActive ? 'Index分組' : '值域分組'}</button>`;
        }

        let html = `<div id="assoc-dist-card" style="padding:14px;background:#f8fafc;border-radius:8px;border:1px solid #e2e8f0;height:100%;box-sizing:border-box;overflow-y:auto;">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;">
                <div style="display:flex;align-items:center;gap:6px;">
                    <span style="font-size:11px;font-weight:700;color:${colorMain};background:${colorBg};padding:2px 7px;border-radius:10px;">${isHist ? '#' : 'Aa'}</span>
                    <span style="font-size:13px;font-weight:700;color:#1e293b;">${colName}</span>
                    ${!isSelected ? '<span style="font-size:10px;color:#94a3b8;font-style:italic;">（未加入分析）</span>' : ''}
                </div>
                <div style="display:flex;align-items:center;">${typeBtns}</div>
            </div>`;

        if (isHist && isScatter) {
            // 散布圖模式
            html += _renderScatterSVG(baseData.samples || [], colorMain, baseData, colName);
            html += `<div style="display:flex;justify-content:space-between;font-size:10px;color:#94a3b8;margin-top:4px;padding:0 2px;">
                <span>min: ${baseData.min}</span><span style="color:#f97316;">avg: ${baseData.mean}</span><span>max: ${baseData.max}</span>
                <span style="color:#64748b;">共 ${baseData.total || '?'} 筆</span>
            </div>`;
            html += _renderBinningEditorInline(colName, isSelected);
        } else if (isHist) {
            // 直方圖模式
            html += _renderHistogramSVG(baseData.bins, colorMain, baseData, colName);
            html += `<div style="display:flex;justify-content:space-between;font-size:10px;color:#94a3b8;margin-top:4px;padding:0 2px;">
                <span>min: ${baseData.min}</span><span style="color:#f97316;">avg: ${baseData.mean}</span><span>max: ${baseData.max}</span>
            </div>`;
            html += _renderBinningEditorInline(colName, isSelected);
        } else {
            // 類別條形圖
            const items = baseData.items || [];
            if (!items.length) {
                html += `<div style="font-size:11px;color:#94a3b8;">（無資料或全被過濾）</div>`;
            } else {
                const maxPct = Math.max(...items.map(i => i.pct), 1);
                items.forEach(item => {
                    const barW = Math.round(item.pct / maxPct * 100);
                    html += `<div style="margin-bottom:5px;">
                        <div style="display:flex;justify-content:space-between;font-size:10px;color:#475569;margin-bottom:1px;">
                            <span style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${item.value}">${item.value}</span>
                            <span style="color:#64748b;flex-shrink:0;margin-left:4px;">${item.count} (${item.pct}%)</span>
                        </div>
                        <div style="height:5px;background:#e2e8f0;border-radius:3px;overflow:hidden;">
                            <div style="height:100%;width:${barW}%;background:${colorMain};border-radius:3px;"></div>
                        </div>
                    </div>`;
                });
            }
        }
        html += `</div>`;
        const _cardSt = document.getElementById('assoc-dist-card')?.scrollTop || 0;
        const _winY = window.scrollY;
        distArea.innerHTML = html;
        const newCard = document.getElementById('assoc-dist-card');
        if (newCard) newCard.scrollTop = _cardSt;
        window.scrollTo({ top: _winY, behavior: 'instant' });
    }

    function _fmtVal(v) {
        if (Math.abs(v) >= 10000) return (v / 1000).toFixed(1) + 'k';
        if (Math.abs(v) >= 100)   return v.toFixed(0);
        if (Math.abs(v) >= 10)    return v.toFixed(1);
        return v.toFixed(2);
    }

    // Y 軸 HTML 欄（固定寬度，文字不受 SVG 拉伸影響）
    function _yAxisCol(labels, chartH) {
        const positions = labels.map((l, i) => {
            const pct = i === 0 ? 0 : i === labels.length - 1 ? 100 : 50;
            const align = i === 0 ? 'flex-start' : i === labels.length - 1 ? 'flex-end' : 'center';
            return `<div style="position:absolute;right:5px;${i===0?'top:0':i===labels.length-1?'bottom:0':'top:50%;transform:translateY(-50%)'};font-size:9px;color:#94a3b8;line-height:1;white-space:nowrap;">${l}</div>`;
        }).join('');
        return `<div style="width:38px;flex-shrink:0;position:relative;height:${chartH}px;border-right:1px solid #e8edf2;">${positions}</div>`;
    }

    // X 軸 HTML 列
    function _xAxisRow(labels, marginLeft) {
        const ml = marginLeft || 38;
        const n = labels.length;
        const items = labels.map((lbl, i) => {
            const align = i === 0 ? 'left' : i === n - 1 ? 'right' : 'center';
            return `<div style="flex:1;text-align:${align};font-size:9px;color:#94a3b8;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${lbl}</div>`;
        }).join('');
        return `<div style="display:flex;margin-left:${ml}px;padding-top:2px;">${items}</div>`;
    }

    // ────────────────────────────────────────────────
    // 共用：依 binning rules 取得顏色
    // ────────────────────────────────────────────────
    const _PALETTE = ['#7c3aed', '#0891b2', '#059669', '#d97706', '#dc2626', '#9333ea', '#0284c7', '#16a34a'];

    function _colorByRules(val, rules, fallback, idx) {
        if (!rules || !rules.length) return fallback;
        for (let i = 0; i < rules.length; i++) {
            const r = rules[i];
            if (r.op === '>'   && r.val !== null && val >  r.val) return _PALETTE[i % _PALETTE.length];
            if (r.op === '>='  && r.val !== null && val >= r.val) return _PALETTE[i % _PALETTE.length];
            if (r.op === '<'   && r.val !== null && val <  r.val) return _PALETTE[i % _PALETTE.length];
            if (r.op === '<='  && r.val !== null && val <= r.val) return _PALETTE[i % _PALETTE.length];
            if (r.op === '~'   && r.lo !== null  && r.hi !== null && val > r.lo && val <= r.hi) return _PALETTE[i % _PALETTE.length];
            if (r.op === 'idx~' && r.lo !== null && r.hi !== null && idx !== undefined && idx >= r.lo && idx <= r.hi) return _PALETTE[i % _PALETTE.length];
            if (r.op === 'idx>' && r.val !== null && idx !== undefined && idx > r.val) return _PALETTE[i % _PALETTE.length];
        }
        return '#cbd5e1';
    }

    function _legendHTML(rules) {
        if (!rules || !rules.length) return '';
        const items = rules.map((r, i) => {
            const lbl = r.label || `G${i + 1}`;
            const col = _PALETTE[i % _PALETTE.length];
            return `<span style="display:inline-flex;align-items:center;gap:3px;font-size:10px;color:${col};font-weight:600;white-space:nowrap;">
                <span style="width:8px;height:8px;border-radius:2px;background:${col};flex-shrink:0;"></span>${lbl}
            </span>`;
        }).join('');
        return `<div style="display:flex;flex-wrap:wrap;gap:6px;margin:4px 0 2px;padding:4px 0;">${items}</div>`;
    }

    // ────────────────────────────────────────────────
    // Histogram
    // ────────────────────────────────────────────────
    function _renderHistogramSVG(bins, colorMain, stats, colName) {
        if (!bins || !bins.length) return '<div style="font-size:11px;color:#94a3b8;padding:8px 0;">（無資料）</div>';
        const VW = 200, pH = 100;   // SVG viewBox（純圖形，無文字）
        const maxCount = Math.max(...bins.map(b => b.count), 1);
        const bw = VW / bins.length;
        const gap = Math.max(0.5, bw * 0.06);
        const rules = _getRules(colName);
        const CHART_H = 180;   // 實際顯示高度 px

        const bars = bins.map((b) => {
            const fill = _colorByRules((b.lo + b.hi) / 2, rules, colorMain);
            const h = Math.max(b.count > 0 ? 1 : 0, (b.count / maxCount) * pH);
            const x = (bins.indexOf(b) * bw + gap / 2).toFixed(2);
            return `<rect x="${x}" y="${(pH - h).toFixed(2)}" width="${Math.max(1, bw - gap).toFixed(2)}" height="${h.toFixed(2)}" fill="${fill}" opacity="0.85" rx="1"><title>${b.lo}~${b.hi}: ${b.count}筆 (${b.pct}%)</title></rect>`;
        }).join('');

        let meanLine = '';
        if (stats && stats.max > stats.min) {
            const mx = ((stats.mean - stats.min) / (stats.max - stats.min) * VW).toFixed(1);
            meanLine = `<line x1="${mx}" y1="0" x2="${mx}" y2="${pH}" stroke="#f97316" stroke-width="1.5" stroke-dasharray="3,2" opacity="0.9"/>`;
        }
        const threshLines = _buildThreshLines(colName, stats, pH, false, VW);

        // HTML 軸標籤
        const yCol = _yAxisCol([_fmtVal(maxCount), _fmtVal(Math.round(maxCount/2)), '0'], CHART_H);
        const step = Math.max(1, Math.floor(bins.length / 4));
        const xIdxs = [];
        for (let i = 0; i < bins.length; i += step) xIdxs.push(i);
        if (xIdxs[xIdxs.length-1] !== bins.length-1) xIdxs.push(bins.length-1);
        const xRow = _xAxisRow(xIdxs.map(i => _fmtVal(bins[i].lo)));

        const clickable = !!(colName && stats && stats.max > stats.min);
        const mousedownStr = clickable ? `onmousedown="assocHistMousedown(event,'${_escStr(colName)}',${stats.min},${stats.max})"` : '';
        const hint = `<div style="font-size:10px;color:#94a3b8;margin-bottom:3px;">↖ 點擊加門檻・拖曳加範圍</div>`;
        return `${hint}<div style="display:flex;align-items:stretch;">
            ${yCol}
            <div style="flex:1;display:flex;flex-direction:column;">
                <div style="height:${CHART_H}px;background:#f8fafc;border-radius:0 4px 4px 0;overflow:hidden;">
                    <svg viewBox="0 0 ${VW} ${pH}" preserveAspectRatio="none" style="width:100%;height:100%;display:block;cursor:${clickable?'crosshair':'default'};" ${mousedownStr} xmlns="http://www.w3.org/2000/svg">
                        ${bars}${meanLine}${threshLines}
                    </svg>
                </div>
                ${xRow}
            </div>
        </div>${_legendHTML(rules)}`;
    }

    // ────────────────────────────────────────────────
    // Scatter SVG
    // ────────────────────────────────────────────────
    function _renderScatterSVG(samples, colorMain, stats, colName) {
        if (!samples || !samples.length) return '<div style="font-size:11px;color:#94a3b8;padding:8px 0;">（無資料點）</div>';
        const VW = 200, pH = 100;
        const minY = stats.min, maxY = stats.max, rangeY = maxY - minY || 1;
        const maxX = samples[samples.length - 1].x || 1;
        const rules = _getRules(colName);
        const CHART_H = 220;

        const dots = samples.map(p => {
            const cx = (p.x / maxX * VW).toFixed(1);
            const cy = ((maxY - p.y) / rangeY * pH).toFixed(1);
            return `<circle cx="${cx}" cy="${cy}" r="1.8" fill="${_colorByRules(p.y, rules, colorMain, p.x)}" opacity="0.65"><title>idx:${p.x} val:${p.y}</title></circle>`;
        }).join('');

        const avgY = ((maxY - stats.mean) / rangeY * pH).toFixed(1);
        const meanLine = `<line x1="0" y1="${avgY}" x2="${VW}" y2="${avgY}" stroke="#f97316" stroke-width="1" stroke-dasharray="3,2" opacity="0.8"/>`;
        const threshLines = _buildThreshLines(colName, stats, pH, true, VW, maxX);

        // HTML 軸標籤
        const yCol = _yAxisCol([_fmtVal(maxY), _fmtVal((minY+maxY)/2), _fmtVal(minY)], CHART_H);
        const xRow = _xAxisRow([0, Math.round(maxX/2), maxX].map(v => v.toString()));

        const clickable = !!(colName && stats);
        const pf = 1.0;
        const mousedownStr = clickable ? `onmousedown="assocScatterMousedown(event,'${_escStr(colName)}',${stats.min},${stats.max},${pf},${maxX})"` : '';
        const hint = `<div style="font-size:10px;color:#94a3b8;margin-bottom:3px;">↖ 拖曳選取 Index 範圍 · 點擊加 Index 門檻 · X 軸為資料序號</div>`;

        return `${hint}<div style="display:flex;align-items:stretch;">
            ${yCol}
            <div style="flex:1;display:flex;flex-direction:column;">
                <div style="height:${CHART_H}px;background:#faf5ff;border-radius:0 4px 4px 0;overflow:hidden;">
                    <svg viewBox="0 0 ${VW} ${pH}" preserveAspectRatio="none" style="width:100%;height:100%;display:block;cursor:${clickable?'crosshair':'default'};user-select:none;" ${mousedownStr} xmlns="http://www.w3.org/2000/svg">
                        ${dots}${meanLine}${threshLines}
                    </svg>
                </div>
                ${xRow}
            </div>
        </div>${_legendHTML(rules)}`;
    }

    /** 產生 threshold 線（horizontal=true 散布圖橫線，false 直方圖縱線；VW 為 SVG viewBox 寬度） */
    function _buildThreshLines(colName, stats, areaH, horizontal, VW, maxIdx) {
        if (!stats) return '';
        const rules = _getRules(colName);
        if (!rules || !rules.length) return '';
        const range = stats.max - stats.min;
        const vw = VW || 200;
        let out = '';
        rules.forEach((rule, i) => {
            const col = _PALETTE[i % _PALETTE.length];

            // ── Index 範圍規則（散布圖 X 軸）────────────────
            if (rule.op === 'idx~' && rule.lo !== null && rule.hi !== null && maxIdx) {
                const x1 = Math.max(0, Math.min(vw, rule.lo / maxIdx * vw)).toFixed(1);
                const x2 = Math.max(0, Math.min(vw, rule.hi / maxIdx * vw)).toFixed(1);
                out += `<rect x="${x1}" y="0" width="${(parseFloat(x2) - parseFloat(x1)).toFixed(1)}" height="${areaH}" fill="${col}" opacity="0.18"/>`;
                out += `<line x1="${x1}" y1="0" x2="${x1}" y2="${areaH}" stroke="${col}" stroke-width="1" stroke-dasharray="3,2" opacity="0.7"/>`;
                out += `<line x1="${x2}" y1="0" x2="${x2}" y2="${areaH}" stroke="${col}" stroke-width="1" stroke-dasharray="3,2" opacity="0.7"/>`;
                return;
            }
            if (rule.op === 'idx>' && rule.val !== null && maxIdx) {
                const x = Math.max(0, Math.min(vw, rule.val / maxIdx * vw)).toFixed(1);
                out += `<line x1="${x}" y1="0" x2="${x}" y2="${areaH}" stroke="${col}" stroke-width="1.5" stroke-dasharray="4,2" opacity="0.85"/>`;
                return;
            }

            // ── 值範圍規則（~ 介於）────────────────────────
            if (rule.op === '~' && rule.lo !== null && rule.hi !== null) {
                if (horizontal && range > 0) {
                    const y2 = ((stats.max - rule.lo) / range * areaH);
                    const y1 = ((stats.max - rule.hi) / range * areaH);
                    const yt = Math.max(0, Math.min(areaH, y1)).toFixed(1);
                    const yb = Math.max(0, Math.min(areaH, y2)).toFixed(1);
                    out += `<rect x="0" y="${yt}" width="${vw}" height="${(parseFloat(yb) - parseFloat(yt)).toFixed(1)}" fill="${col}" opacity="0.15"/>`;
                    out += `<line x1="0" y1="${yt}" x2="${vw}" y2="${yt}" stroke="${col}" stroke-width="1" stroke-dasharray="3,2" opacity="0.6"/>`;
                    out += `<line x1="0" y1="${yb}" x2="${vw}" y2="${yb}" stroke="${col}" stroke-width="1" stroke-dasharray="3,2" opacity="0.6"/>`;
                } else if (!horizontal && range > 0) {
                    const x1 = Math.max(0, Math.min(vw, (rule.lo - stats.min) / range * vw)).toFixed(1);
                    const x2 = Math.max(0, Math.min(vw, (rule.hi - stats.min) / range * vw)).toFixed(1);
                    out += `<rect x="${x1}" y="0" width="${(parseFloat(x2) - parseFloat(x1)).toFixed(1)}" height="${areaH}" fill="${col}" opacity="0.15"/>`;
                    out += `<line x1="${x1}" y1="0" x2="${x1}" y2="${areaH}" stroke="${col}" stroke-width="1" stroke-dasharray="3,2" opacity="0.6"/>`;
                    out += `<line x1="${x2}" y1="0" x2="${x2}" y2="${areaH}" stroke="${col}" stroke-width="1" stroke-dasharray="3,2" opacity="0.6"/>`;
                }
                return;
            }

            // ── 值門檻規則 ─────────────────────────────────
            if (range <= 0) return;
            let tv = null;
            if (['>', '>=', '<', '<=', '=='].includes(rule.op) && rule.val !== null && rule.val !== undefined) tv = rule.val;
            if (tv === null) return;
            if (horizontal) {
                const y = ((stats.max - tv) / range * areaH).toFixed(1);
                if (parseFloat(y) < 0 || parseFloat(y) > areaH) return;
                out += `<line x1="0" y1="${y}" x2="${vw}" y2="${y}" stroke="${col}" stroke-width="1.5" stroke-dasharray="4,2" opacity="0.85"/>`;
            } else {
                const x = ((tv - stats.min) / range * vw).toFixed(1);
                if (parseFloat(x) < 0 || parseFloat(x) > vw) return;
                out += `<line x1="${x}" y1="0" x2="${x}" y2="${areaH}" stroke="${col}" stroke-width="1.5" stroke-dasharray="4,2" opacity="0.85"/>`;
            }
        });
        return out;
    }

    // ────────────────────────────────────────────────
    // Binning editor (below chart)
    // ────────────────────────────────────────────────
    function _renderBinningEditorInline(colName, isSelected) {
        const esc = _escStr(colName);
        const rules = _getRules(colName);

        let html = `<div style="margin-top:12px;padding:10px;background:#faf5ff;border:1px solid #e9d5ff;border-radius:8px;">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;">
                <div style="font-size:11px;font-weight:700;color:#7c3aed;">分組規則 ${rules.length ? `(${rules.length})` : ''}</div>
                <div style="display:flex;align-items:center;gap:6px;">
                    ${rules.length ? `<button onclick="assocClearAllRules('${esc}')" style="padding:2px 7px;font-size:10px;border:1px solid #fca5a5;border-radius:4px;background:#fff;color:#ef4444;cursor:pointer;">全部清除</button>` : ''}
                    ${!isSelected ? '<div style="font-size:10px;color:#f97316;">設定完成後記得勾選欄位加入分析</div>' : ''}
                </div>
            </div>`;

        if (rules.length) {
            html += `<div style="display:flex;flex-direction:column;gap:4px;margin-bottom:8px;">`;
            rules.forEach((r, i) => {
                const ops = ['>', '>=', '<', '<=', '==', '~'];
                const opOpts = ops.map(o => `<option value="${o}" ${r.op === o ? 'selected' : ''}>${o}</option>`).join('');
                const isRange = r.op === '~';
                const isIdxRange = r.op === 'idx~';
                const isIdxThresh = r.op === 'idx>';
                const dotColor = _PALETTE[i % _PALETTE.length];

                let inputsHtml;
                if (isIdxRange) {
                    inputsHtml = `<span style="font-size:9px;color:#0891b2;font-weight:600;padding:0 3px;">索引</span>
                        <input type="number" step="1" value="${r.lo ?? ''}" onchange="assocBinRowChange('${esc}',${i},'lo',this.value)" placeholder="起" style="width:52px;padding:1px 3px;border:1px solid #bae6fd;border-radius:3px;font-size:10px;height:22px;">
                        <span style="font-size:9px;color:#94a3b8;">~</span>
                        <input type="number" step="1" value="${r.hi ?? ''}" onchange="assocBinRowChange('${esc}',${i},'hi',this.value)" placeholder="迄" style="width:52px;padding:1px 3px;border:1px solid #bae6fd;border-radius:3px;font-size:10px;height:22px;">`;
                } else if (isIdxThresh) {
                    inputsHtml = `<span style="font-size:9px;color:#0891b2;font-weight:600;padding:0 3px;">索引 &gt;</span>
                        <input type="number" step="1" value="${r.val ?? ''}" onchange="assocBinRowChange('${esc}',${i},'val',this.value)" placeholder="序號" style="width:72px;padding:1px 3px;border:1px solid #bae6fd;border-radius:3px;font-size:10px;height:22px;">`;
                } else if (isRange) {
                    inputsHtml = `<select onchange="assocBinRowChange('${esc}',${i},'op',this.value)" style="padding:1px 3px;border:1px solid #d8b4fe;border-radius:3px;font-size:10px;height:22px;">${opOpts}</select>
                        <input type="number" value="${r.lo ?? ''}" onchange="assocBinRowChange('${esc}',${i},'lo',this.value)" placeholder="下限" style="width:52px;padding:1px 3px;border:1px solid #d8b4fe;border-radius:3px;font-size:10px;height:22px;">
                        <span style="font-size:9px;color:#94a3b8;">~</span>
                        <input type="number" value="${r.hi ?? ''}" onchange="assocBinRowChange('${esc}',${i},'hi',this.value)" placeholder="上限" style="width:52px;padding:1px 3px;border:1px solid #d8b4fe;border-radius:3px;font-size:10px;height:22px;">`;
                } else {
                    inputsHtml = `<select onchange="assocBinRowChange('${esc}',${i},'op',this.value)" style="padding:1px 3px;border:1px solid #d8b4fe;border-radius:3px;font-size:10px;height:22px;">${opOpts}</select>
                        <input type="number" value="${r.val ?? ''}" onchange="assocBinRowChange('${esc}',${i},'val',this.value)" placeholder="數值" style="width:66px;padding:1px 3px;border:1px solid #d8b4fe;border-radius:3px;font-size:10px;height:22px;">`;
                }

                html += `<div style="display:flex;align-items:center;gap:3px;padding:2px 4px;background:#fff;border-radius:4px;border:1px solid ${isIdxRange||isIdxThresh?'#bae6fd':'#f3e8ff'};height:28px;">
                    <span style="width:8px;height:8px;border-radius:2px;background:${dotColor};flex-shrink:0;"></span>
                    ${inputsHtml}
                    <span style="font-size:9px;color:#94a3b8;">→</span>
                    <input type="text" value="${r.label || ''}" onchange="assocBinRowChange('${esc}',${i},'label',this.value)" placeholder="標籤" style="width:46px;padding:1px 3px;border:1px solid #d8b4fe;border-radius:3px;font-size:10px;height:22px;">
                    <button onclick="assocDelBinRow('${esc}',${i})" style="padding:0 4px;border:none;background:none;color:#f87171;cursor:pointer;font-size:11px;height:22px;margin-left:auto;">✕</button>
                </div>`;
            });
            html += `</div>`;

            // 重疊警示：若某條規則會被前面的規則完全覆蓋
            const overlapWarnings = [];
            rules.forEach((r, i) => {
                if (r.val == null && r.lo == null) return; // 空規則跳過
                for (let j = 0; j < i; j++) {
                    const prev = rules[j];
                    if (!prev || prev.val == null && prev.lo == null) continue;
                    // > / >= 系列：前面規則 val 更小 → 本規則永遠被搶先
                    if ((r.op === '>' || r.op === '>=') && (prev.op === '>' || prev.op === '>=')) {
                        if (Number(prev.val) <= Number(r.val)) {
                            overlapWarnings.push(`規則 ${r.label || 'G'+(i+1)} 可能被 ${prev.label || 'G'+(j+1)} 覆蓋（前者門檻較低，先命中）`);
                            break;
                        }
                    }
                    // < / <= 系列：前面規則 val 更大 → 本規則永遠被搶先
                    if ((r.op === '<' || r.op === '<=') && (prev.op === '<' || prev.op === '<=')) {
                        if (Number(prev.val) >= Number(r.val)) {
                            overlapWarnings.push(`規則 ${r.label || 'G'+(i+1)} 可能被 ${prev.label || 'G'+(j+1)} 覆蓋（前者門檻較高，先命中）`);
                            break;
                        }
                    }
                }
            });
            if (overlapWarnings.length) {
                html += `<div style="background:#fef3c7;border:1px solid #fcd34d;border-radius:5px;padding:5px 8px;margin-bottom:6px;">
                    <div style="font-size:10px;font-weight:700;color:#92400e;margin-bottom:2px;">⚠️ 規則重疊警示（先命中優先）</div>
                    ${overlapWarnings.map(w => `<div style="font-size:10px;color:#b45309;">• ${w}</div>`).join('')}
                </div>`;
            }
        } else {
            html += `<div style="font-size:10px;color:#94a3b8;margin-bottom:8px;">尚無分組規則。點擊上方圖表或手動新增。</div>`;
        }

        html += `<div style="display:flex;gap:6px;">
            <button onclick="assocAddBinRow('${esc}')" style="flex:1;padding:5px;font-size:11px;border:1px dashed #a78bfa;border-radius:5px;background:#fff;color:#7c3aed;cursor:pointer;">+ 新增條件</button>
            <button onclick="assocPreviewBin('${esc}')" style="flex:1;padding:5px;font-size:11px;border:1px solid #c4b5fd;border-radius:5px;background:#ede9fe;color:#5b21b6;cursor:pointer;">預覽分布</button>
        </div>
        <div id="bin-preview-${_esc(colName)}" style="margin-top:4px;font-size:11px;color:#64748b;"></div>
        </div>`;
        return html;
    }

    // ────────────────────────────────────────────────
    // Public callbacks
    // ────────────────────────────────────────────────
    window.assocSearch = function (val) {
        _assocSearchTerm = val.toLowerCase().trim();
        _renderStep1();
    };

    window.assocToggleCol = function (name, dtype) {
        const idx = _assocSelectedCols.findIndex(c => c.name === name);
        if (idx >= 0) {
            // 取消勾選：保留 binning rules 到 cache
            const removed = _assocSelectedCols.splice(idx, 1)[0];
            if (removed.binningRules && removed.binningRules.length) {
                _assocBinningCache[name] = removed.binningRules;
            }
            if (_assocFocusedCol === name)
                _assocFocusedCol = _assocSelectedCols.length ? _assocSelectedCols[_assocSelectedCols.length - 1].name : null;
        } else {
            // 勾選：從 cache 讀取預設好的 binning rules
            const cachedRules = _assocBinningCache[name] || [];
            delete _assocBinningCache[name];
            _assocSelectedCols.push({ name, dtype, binningRules: cachedRules });
            _assocFocusedCol = name;
        }
        _assocConsequentCol = '';
        _assocConsequentVal = '';
        _renderStep1();
        _updateRunBtn();
    };

    window.assocFocusCol = function (name) {
        _assocFocusedCol = name;
        _renderStep1();
    };

    window.assocToggleColType = function () {
        const colName = _assocFocusedCol;
        if (!colName || !_assocLastDistData || !_assocLastDistData[colName]) return;
        const rawData = _assocLastDistData[colName];
        const baseType = Array.isArray(rawData) ? 'categorical' : rawData.type;
        const current = _assocTypeOverride[colName] || baseType;
        _assocTypeOverride[colName] = current === 'histogram' ? 'categorical' : 'histogram';
        if (_assocTypeOverride[colName] === 'histogram') delete _assocViewModes[colName];
        _renderDistCards(_assocLastDistData);
    };

    window.assocToggleScatter = function () {
        const colName = _assocFocusedCol;
        if (!colName) return;
        _assocViewModes[colName] = (_assocViewModes[colName] === 'scatter') ? 'histogram' : 'scatter';
        _renderDistCards(_assocLastDistData || {});
    };

    /** 點擊直方圖 → 垂直位置轉換為 data value → 新增 > rule */
    window.assocHistMousedown = function (event, colName, minVal, maxVal) {
        event.preventDefault();
        _initScatterHandlers();
        if (!document.getElementById('assoc-scatter-drag-overlay')) {
            const div = document.createElement('div');
            div.id = 'assoc-scatter-drag-overlay';
            div.style.cssText = 'position:fixed;pointer-events:none;border:2px dashed #7c3aed;background:rgba(124,58,237,0.12);z-index:9999;display:none;border-radius:2px;';
            document.body.appendChild(div);
        }
        _assocDragState = {
            mode: 'histogram',
            colName, minVal, maxVal,
            plotFrac: 1,
            startClientX: event.clientX,
            startClientY: event.clientY,
            svgEl: event.currentTarget,
            svgRect: event.currentTarget.getBoundingClientRect(),
        };
    };

    /** 初始化散布圖拖曳框選的 document 事件（只執行一次） */
    function _initScatterHandlers() {
        if (_scatterHandlersAdded) return;
        _scatterHandlersAdded = true;

        document.addEventListener('mousemove', function (e) {
            if (!_assocDragState) return;
            const overlay = document.getElementById('assoc-scatter-drag-overlay');
            if (!overlay) return;
            const state = _assocDragState;
            const rect = state.svgRect;
            if (state.mode === 'histogram') {
                // 直方圖：X 跟著滑鼠，Y 固定為圖表全高
                const x1 = Math.min(e.clientX, state.startClientX);
                const x2 = Math.max(e.clientX, state.startClientX);
                overlay.style.left = x1 + 'px';
                overlay.style.top = rect.top + 'px';
                overlay.style.width = (x2 - x1) + 'px';
                overlay.style.height = rect.height + 'px';
            } else {
                // 散布圖 Index 模式：X 跟著滑鼠，Y 固定全高
                const x1 = Math.min(e.clientX, state.startClientX);
                const x2 = Math.max(e.clientX, state.startClientX);
                overlay.style.left = x1 + 'px';
                overlay.style.top = rect.top + 'px';
                overlay.style.width = (x2 - x1) + 'px';
                overlay.style.height = rect.height + 'px';
            }
            overlay.style.display = 'block';
        });

        document.addEventListener('mouseup', function (e) {
            if (!_assocDragState) return;
            const state = _assocDragState;
            _assocDragState = null;
            const overlay = document.getElementById('assoc-scatter-drag-overlay');
            if (overlay) overlay.style.display = 'none';

            const dx = Math.abs(e.clientX - state.startClientX);
            const dy = Math.abs(e.clientY - state.startClientY);
            const rect = state.svgRect;
            const range = state.maxVal - state.minVal;
            const isClick = dx < 15 && dy < 15;

            if (state.mode === 'histogram') {
                // X 軸拖曳
                const relX1 = Math.max(0, Math.min(1, (state.startClientX - rect.left) / rect.width));
                const relX2 = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
                if (isClick) {
                    const value = _smartRound(state.minVal + relX1 * range, range);
                    _pushRule(state.colName, { op: '>', val: value, lo: null, hi: null, label: `G${_getRules(state.colName).length + 1}` });
                } else {
                    const v1 = state.minVal + relX1 * range;
                    const v2 = state.minVal + relX2 * range;
                    const lo = _smartRound(Math.min(v1, v2), range);
                    const hi = _smartRound(Math.max(v1, v2), range);
                    _pushRule(state.colName, { op: '~', val: null, lo, hi, label: `G${_getRules(state.colName).length + 1}` });
                }
            } else {
                // 散布圖 Index 模式（X 軸）
                const relX1 = Math.max(0, Math.min(1, (state.startClientX - rect.left) / rect.width));
                const relX2 = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
                const maxIdx = state.maxIdx;
                if (isClick) {
                    const idxVal = Math.round(relX1 * maxIdx);
                    _pushRule(state.colName, { op: 'idx>', val: idxVal, lo: null, hi: null, label: `G${_getRules(state.colName).length + 1}` });
                } else {
                    const lo = Math.round(Math.min(relX1, relX2) * maxIdx);
                    const hi = Math.round(Math.max(relX1, relX2) * maxIdx);
                    _pushRule(state.colName, { op: 'idx~', val: null, lo, hi, label: `G${_getRules(state.colName).length + 1}` });
                }
                if (_assocLastDistData) _renderDistCards(_assocLastDistData);
                _renderStep1(true);
                return;
            }
            if (_assocLastDistData) _renderDistCards(_assocLastDistData);
            _renderStep1(true);
        });
    }

    /** 散布圖 mousedown — 開始框選或點擊（plotFrac = plotH/totalH，從 SVG 傳入） */
    window.assocScatterMousedown = function (event, colName, minVal, maxVal, plotFrac, maxIdx) {
        event.preventDefault();
        _initScatterHandlers();
        if (!document.getElementById('assoc-scatter-drag-overlay')) {
            const div = document.createElement('div');
            div.id = 'assoc-scatter-drag-overlay';
            div.style.cssText = 'position:fixed;pointer-events:none;border:2px dashed #7c3aed;background:rgba(124,58,237,0.12);z-index:9999;display:none;border-radius:2px;';
            document.body.appendChild(div);
        }
        _assocDragState = {
            mode: 'scatter_idx',
            colName, minVal, maxVal,
            maxIdx: maxIdx || 1,
            plotFrac: plotFrac || 1.0,
            startClientX: event.clientX,
            startClientY: event.clientY,
            svgEl: event.currentTarget,
            svgRect: event.currentTarget.getBoundingClientRect(),
        };
    };

    function _smartRound(value, range) {
        if (range < 0.1) return Math.round(value * 10000) / 10000;
        if (range < 1)   return Math.round(value * 1000) / 1000;
        if (range < 10)  return Math.round(value * 100) / 100;
        if (range < 100) return Math.round(value * 10) / 10;
        return Math.round(value);
    }

    window.assocAddBinRow = function (colName) {
        _pushRule(colName, { op: '>', val: null, lo: null, hi: null, label: '' });
        if (_assocLastDistData) _renderDistCards(_assocLastDistData);
        _renderStep1(true);
    };

    window.assocDelBinRow = function (colName, idx) {
        _spliceRule(colName, idx);
        if (_assocLastDistData) _renderDistCards(_assocLastDistData);
        _renderStep1(true);
    };

    window.assocClearAllRules = function (colName) {
        const col = _assocSelectedCols.find(c => c.name === colName);
        if (col) col.binningRules = [];
        else _assocBinningCache[colName] = [];
        if (_assocLastDistData) _renderDistCards(_assocLastDistData);
        _renderStep1(true);
    };

    window.assocBinRowChange = function (colName, idx, field, value) {
        if (field === 'op') {
            _patchRule(colName, idx, 'op', value);
        } else if (['val', 'lo', 'hi'].includes(field)) {
            _patchRule(colName, idx, field, value === '' ? null : parseFloat(value));
        } else {
            _patchRule(colName, idx, field, value);
        }
        if (_assocLastDistData) _renderDistCards(_assocLastDistData);
        _renderStep1(true);
    };

    window.assocPreviewBin = async function (colName) {
        const rules = _getRules(colName);
        if (!rules.length) return;
        const previewEl = document.getElementById(`bin-preview-${_esc(colName)}`);
        if (previewEl) previewEl.textContent = '載入中...';
        try {
            const res = await fetch('/api/association/binning_preview', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    file_id: currentFileId, session_id: _getSid(),
                    col: colName, rules,
                    exclude_indices: _getExcludeIndices(),
                }),
            });
            const data = await res.json();
            if (previewEl && data.distribution) {
                const items = Object.entries(data.distribution)
                    .filter(([k]) => k !== '_other')
                    .sort((a, b) => a[0].localeCompare(b[0]))
                    .map(([k, v]) => `<span style="margin-right:8px;"><b>${k}</b>: ${v}</span>`)
                    .join('');
                previewEl.innerHTML = items || '(無結果)';
            }
        } catch { if (previewEl) previewEl.textContent = '預覽失敗'; }
    };

    // ────────────────────────────────────────────────
    // Step 2 — Consequent + 參數
    // ────────────────────────────────────────────────
    function _renderStep2() {
        const colSel = document.getElementById('assoc-cons-col');
        const valSel = document.getElementById('assoc-cons-val');
        if (!colSel || !valSel) return;
        colSel.innerHTML = '<option value="">-- 選擇目標欄位 --</option>';
        _assocSelectedCols.forEach(c => {
            const opt = document.createElement('option');
            opt.value = c.name; opt.textContent = c.name;
            if (c.name === _assocConsequentCol) opt.selected = true;
            colSel.appendChild(opt);
        });
        if (_assocConsequentCol) _loadConsValues(_assocConsequentCol);
        else valSel.innerHTML = '<option value="">-- 先選欄位 --</option>';

        // 排除欄位下拉選單
        const excludeColSel = document.getElementById('assoc-exclude-col');
        if (excludeColSel) {
            excludeColSel.innerHTML = '<option value="">所有欄位</option>';
            _assocSelectedCols.forEach(c => {
                const opt = document.createElement('option');
                opt.value = c.name; opt.textContent = c.name;
                excludeColSel.appendChild(opt);
            });
        }
        _renderExcludeTags();

        const minSup = document.getElementById('assoc-min-support');
        const minConf = document.getElementById('assoc-min-confidence');
        const minLift = document.getElementById('assoc-min-lift');
        const minCnt = document.getElementById('assoc-min-count');
        if (minSup) minSup.value = _assocMinSupport;
        if (minConf) minConf.value = _assocMinConfidence;
        if (minLift) minLift.value = _assocMinLift;
        if (minCnt) minCnt.value = _assocMinCount;
        _updateRunBtn();
    }

    async function _loadConsValues(col) {
        const valSel = document.getElementById('assoc-cons-val');
        if (!valSel) return;
        valSel.innerHTML = '<option value="">載入中...</option>';
        const entry = _colEntry(col);
        const rules = entry?.binningRules || [];

        const _doFetch = async (withRules) => {
            const res = await fetch('/api/association/col_values', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    file_id: currentFileId, session_id: _getSid(), col,
                    binning_rules: withRules ? rules : [],
                    // 不帶 exclude_indices：目標值清單應顯示所有分組標籤，
                    // 不受清洗排除影響（否則被排除的組別會消失於選單中）
                    exclude_indices: [], exclude_cols: [],
                }),
            });
            const data = await res.json();
            return data.values || [];
        };

        try {
            let values = rules.length ? await _doFetch(true) : [];
            // 若 binning 後無值（規則未覆蓋資料），改用原始值
            if (!values.length) values = await _doFetch(false);
            valSel.innerHTML = '<option value="">-- 選擇目標值 --</option>';
            values.forEach(v => {
                const opt = document.createElement('option');
                opt.value = v;
                // 找出這個標籤對應的 binning rule，補上值域
                const matchedRule = rules.find(r => String(r.label) === String(v));
                let rangeHint = '';
                if (matchedRule) {
                    const op = matchedRule.op;
                    if ((op === '~' || op === 'idx~') && matchedRule.lo != null && matchedRule.hi != null)
                        rangeHint = ` (${matchedRule.lo} ~ ${matchedRule.hi})`;
                    else if ((op === '>' || op === 'idx>') && matchedRule.val != null)
                        rangeHint = ` (> ${matchedRule.val})`;
                    else if (['>=', '<', '<=', '=='].includes(op) && matchedRule.val != null)
                        rangeHint = ` (${op} ${matchedRule.val})`;
                }
                opt.textContent = v + rangeHint;
                if (v === _assocConsequentVal) opt.selected = true;
                valSel.appendChild(opt);
            });
        } catch { valSel.innerHTML = '<option value="">載入失敗</option>'; }
    }

    // 排除值管理
    window.assocAddExcludeValue = function () {
        const colSel = document.getElementById('assoc-exclude-col');
        const valSel = document.getElementById('assoc-exclude-val');
        if (!colSel || !valSel) return;
        const col = colSel.value || '*';
        const val = valSel.value;
        if (!val) return;
        if (!_assocExcludeValues[col]) _assocExcludeValues[col] = [];
        if (!_assocExcludeValues[col].includes(val)) _assocExcludeValues[col].push(val);
        valSel.value = '';
        _renderExcludeTags();
        // 如果已有結果，自動重跑
        if (_assocLastResult) setTimeout(() => { _gotoStep(3); _run(); }, 100);
    };

    window.assocLoadExcludeVals = async function (col) {
        const valSel = document.getElementById('assoc-exclude-val');
        if (!valSel) return;
        valSel.innerHTML = '<option value="">載入中...</option>';
        if (!col) {
            valSel.innerHTML = '<option value="">-- 選擇值 --</option>';
            return;
        }
        try {
            const entry = _colEntry(col);
            const rules = entry?.binningRules?.length ? entry.binningRules : [];
            const res = await fetch('/api/association/col_values', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    file_id: currentFileId, session_id: _getSid(),
                    col, binning_rules: rules,
                    exclude_indices: _getExcludeIndices(),
                }),
            });
            const data = await res.json();
            valSel.innerHTML = '<option value="">-- 選擇值 --</option>';
            (data.values || []).forEach(v => {
                const opt = document.createElement('option');
                opt.value = v; opt.textContent = v;
                valSel.appendChild(opt);
            });
        } catch {
            valSel.innerHTML = '<option value="">-- 載入失敗 --</option>';
        }
    };
    window.assocRemoveExcludeValue = function (col, val) {
        if (_assocExcludeValues[col]) {
            _assocExcludeValues[col] = _assocExcludeValues[col].filter(v => v !== val);
            if (!_assocExcludeValues[col].length) delete _assocExcludeValues[col];
        }
        _renderExcludeTags();
        if (_assocLastResult) setTimeout(() => _run(), 100);
    };
    function _renderExcludeTags() {
        const container = document.getElementById('assoc-exclude-tags');
        if (!container) return;
        const tags = [];
        Object.entries(_assocExcludeValues).forEach(([col, vals]) => {
            vals.forEach(val => {
                const label = col === '*' ? val : `${col}=${val}`;
                tags.push(`<span style="display:inline-flex;align-items:center;gap:4px;background:#fef3c7;border:1px solid #fcd34d;border-radius:12px;padding:2px 8px;font-size:11px;color:#92400e;">
                    ${label}
                    <span onclick="assocRemoveExcludeValue('${col}','${val}')" style="cursor:pointer;color:#b45309;font-weight:700;">×</span>
                </span>`);
            });
        });
        container.innerHTML = tags.join('') || '<span style="font-size:11px;color:#94a3b8;">（無）</span>';
    }

    window.assocExcludeAndRerun = function (col, val, btnEl) {
        if (!_assocExcludeValues[col]) _assocExcludeValues[col] = [];
        if (!_assocExcludeValues[col].includes(val)) _assocExcludeValues[col].push(val);
        if (btnEl) { btnEl.textContent = '✓'; btnEl.style.pointerEvents = 'none'; }
        _renderExcludeTags();
        setTimeout(() => _run(), 200);
    };

    window.assocOnConsColChange = function (val) {
        _assocConsequentCol = val; _assocConsequentVal = '';
        if (val) _loadConsValues(val);
        else { const vs = document.getElementById('assoc-cons-val'); if (vs) vs.innerHTML = '<option value="">-- 先選欄位 --</option>'; }
        _updateRunBtn();
    };
    window.assocOnConsValChange = function (val) { _assocConsequentVal = val; _updateRunBtn(); };
    window.assocOnParamChange = function () {
        const ms = document.getElementById('assoc-min-support');
        const mc = document.getElementById('assoc-min-confidence');
        const ml = document.getElementById('assoc-min-lift');
        const mct = document.getElementById('assoc-min-count');
        if (ms) _assocMinSupport = Math.max(0.001, parseFloat(ms.value) || 0.05);
        if (mc) _assocMinConfidence = Math.max(0.001, parseFloat(mc.value) || 0.5);
        if (ml) _assocMinLift = Math.max(0.01, parseFloat(ml.value) || 1.0);
        if (mct) _assocMinCount = Math.max(1, parseInt(mct.value) || 30);
    };

    // ────────────────────────────────────────────────
    // Step 3 — Run + Results
    // ────────────────────────────────────────────────
    function _renderStep3() {
        const area = document.getElementById('assoc-result-area');
        if (!area) return;
        if (_assocLastResult) _renderResult(_assocLastResult);
        else area.innerHTML = `<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:200px;color:#94a3b8;gap:8px;"><div style="font-size:28px;">🔗</div><div style="font-size:13px;">請點擊左側「執行分析」按鈕</div></div>`;
    }

    async function _run() {
        if (_assocRunning) return;
        if (!currentFileId) { alert('請先選擇資料集'); return; }
        if (_assocSelectedCols.length < 2) { alert('請至少選擇 2 個欄位'); return; }
        if (!_assocConsequentCol || !_assocConsequentVal) { alert('請設定目標結果（Consequent）'); return; }
        _assocRunning = true; _updateRunBtn(); _gotoStep(3);
        const area = document.getElementById('assoc-result-area');
        const stages = [
            { pct: 15, label: '載入資料...' }, { pct: 35, label: '套用分組規則...' },
            { pct: 55, label: '建立交易矩陣...' }, { pct: 75, label: '挖掘頻繁項目集...' },
            { pct: 88, label: '生成關聯規則...' }, { pct: 95, label: '篩選目標結果...' },
        ];
        if (area) area.innerHTML = `<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:260px;gap:20px;padding:0 40px;">
            <div style="font-size:14px;font-weight:700;color:#1e293b;">關聯分析中</div>
            <div style="width:100%;background:#f1f5f9;border-radius:999px;height:10px;overflow:hidden;"><div id="assoc-progress-bar" style="height:100%;width:0%;background:linear-gradient(90deg,#7c3aed,#a78bfa);border-radius:999px;transition:width 0.5s ease;"></div></div>
            <div style="display:flex;justify-content:space-between;width:100%;"><div id="assoc-progress-label" style="font-size:12px;color:#64748b;">準備中...</div><div id="assoc-progress-pct" style="font-size:12px;font-weight:700;color:#7c3aed;">0%</div></div>
        </div>`;
        let _progressTimer = null, _stageIdx = 0;
        function _advanceProgress() {
            if (_stageIdx >= stages.length) return;
            const s = stages[_stageIdx++];
            const bar = document.getElementById('assoc-progress-bar');
            const lbl = document.getElementById('assoc-progress-label');
            const pct = document.getElementById('assoc-progress-pct');
            if (bar) bar.style.width = s.pct + '%';
            if (lbl) lbl.textContent = s.label;
            if (pct) pct.textContent = s.pct + '%';
            _progressTimer = setTimeout(_advanceProgress, _stageIdx <= 3 ? 400 : 900);
        }
        _advanceProgress();
        const binningRules = {};
        _assocSelectedCols.forEach(c => { if (c.binningRules?.length) binningRules[c.name] = c.binningRules; });
        try {
            const res = await fetch('/api/association/run', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    file_id: currentFileId, session_id: _getSid(),
                    selected_cols: _assocSelectedCols.map(c => c.name),
                    binning_rules: binningRules,
                    consequent_col: _assocConsequentCol, consequent_val: _assocConsequentVal,
                    min_support: _assocMinSupport, min_confidence: _assocMinConfidence,
                    min_lift: _assocMinLift, min_count: _assocMinCount,
                    exclude_indices: _getExcludeIndices(), exclude_cols: _getExcludeCols(),
                    exclude_values: _assocExcludeValues,
                }),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || '分析失敗');
            clearTimeout(_progressTimer);
            const bar = document.getElementById('assoc-progress-bar');
            const lbl = document.getElementById('assoc-progress-label');
            const pct = document.getElementById('assoc-progress-pct');
            if (bar) bar.style.width = '100%';
            if (lbl) lbl.textContent = '完成！';
            if (pct) pct.textContent = '100%';
            await new Promise(r => setTimeout(r, 400));
            _assocLastResult = data; _renderResult(data);
        } catch (e) {
            clearTimeout(_progressTimer);
            if (area) area.innerHTML = `<div style="color:#ef4444;padding:20px;font-size:13px;">❌ ${e.message}</div>`;
        } finally { _assocRunning = false; _updateRunBtn(); }
    }

    function _renderResult(data) {
        const area = document.getElementById('assoc-result-area');
        if (!area) return;
        const rules = data.rules || [], total = data.total_transactions || 0, warning = data.warning || '';

        // Header: summary + view toggle
        const btnBase = `cursor:pointer;padding:4px 12px;font-size:11px;border-radius:6px;border:1px solid #e2e8f0;font-weight:600;`;
        const btnActive = btnBase + `background:#7c3aed;color:#fff;border-color:#7c3aed;`;
        const btnInactive = btnBase + `background:#fff;color:#64748b;`;
        let html = `
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;flex-wrap:wrap;gap:8px;">
            <div style="font-size:12px;color:#64748b;">
                共 <b style="color:#1e293b;">${rules.length}</b> 條規則 ｜
                交易數: <b style="color:#1e293b;">${total}</b> ｜
                目標: <b style="color:#7c3aed;">${_assocConsequentCol}=${_assocConsequentVal}</b>
            </div>
            <div style="display:flex;gap:4px;">
                <button style="${_assocResultView === 'table' ? btnActive : btnInactive}" onclick="assocSetView('table')">📋 表格</button>
                <button style="${_assocResultView === 'chart' ? btnActive : btnInactive}" onclick="assocSetView('chart')">📊 散布圖</button>
            </div>
        </div>`;
        if (warning) html += `<div style="background:#fef9c3;border:1px solid #fde047;border-radius:8px;padding:10px 14px;font-size:12px;color:#854d0e;margin-bottom:12px;">⚠️ ${warning}</div>`;
        if (!rules.length) { html += `<div style="text-align:center;color:#94a3b8;padding:30px;font-size:13px;">找不到符合條件的規則</div>`; area.innerHTML = html; return; }

        if (_assocResultView === 'chart') {
            html += `<div style="position:relative;"><canvas id="assoc-scatter-canvas" style="width:100%;border:1px solid #e2e8f0;border-radius:8px;display:block;"></canvas><div id="assoc-scatter-tip" style="position:fixed;pointer-events:none;display:none;background:rgba(15,23,42,.93);color:#fff;padding:8px 12px;border-radius:8px;font-size:11px;line-height:1.6;white-space:nowrap;z-index:9999;box-shadow:0 2px 10px rgba(0,0,0,.3);max-width:320px;white-space:normal;"></div></div>`;
            area.innerHTML = html;
            _drawAssocScatter(rules, total);
            return;
        }

        // Table view
        const sorted = [...rules].sort((a, b) => { const va = a[_assocSortCol], vb = b[_assocSortCol]; return _assocSortAsc ? va - vb : vb - va; });
        const thStyle = `padding:8px 10px;text-align:left;font-size:11px;font-weight:700;color:#475569;background:#f8fafc;border-bottom:2px solid #e2e8f0;cursor:pointer;white-space:nowrap;user-select:none;`;
        const tdStyle = `padding:7px 10px;font-size:12px;border-bottom:1px solid #f1f5f9;vertical-align:top;`;
        const arrow = col => _assocSortCol === col ? (_assocSortAsc ? ' ▲' : ' ▼') : '';
        html += `<div style="overflow-x:auto;border:1px solid #e2e8f0;border-radius:8px;"><table style="width:100%;border-collapse:collapse;"><thead><tr>
            <th style="${thStyle}" onclick="assocSort('antecedents_str')">條件${arrow('antecedents_str')}</th>
            <th style="${thStyle}text-align:right;" onclick="assocSort('support')">Support${arrow('support')}<div style="font-size:9px;font-weight:400;color:#94a3b8;margin-top:1px;">符合條件且達目標 / 總交易數</div></th>
            <th style="${thStyle}text-align:right;" onclick="assocSort('confidence')">Confidence${arrow('confidence')}<div style="font-size:9px;font-weight:400;color:#94a3b8;margin-top:1px;">符合條件且達目標 / 符合條件筆數</div></th>
            <th style="${thStyle}text-align:right;" onclick="assocSort('lift')">Lift${arrow('lift')}</th>
            <th style="${thStyle}text-align:center;"></th>
        </tr></thead><tbody>`;
        sorted.forEach((r, i) => {
            const bg = i % 2 === 0 ? '#fff' : '#fafafa';
            const antStr = r.antecedents.map(a => {
                const eqIdx = a.indexOf('=');
                const col = eqIdx > 0 ? a.slice(0, eqIdx) : '*';
                const val = eqIdx > 0 ? a.slice(eqIdx + 1) : a;
                return `<span style="display:inline-flex;align-items:center;gap:3px;background:#ede9fe;color:#5b21b6;border-radius:4px;padding:1px 6px;font-size:11px;margin:1px 2px 1px 0;">
                    ${a}
                    <span onclick="assocExcludeAndRerun('${col.replace(/'/g,"\\'")}','${val.replace(/'/g,"\\'")}',this)" title="排除此條件值並重新分析" style="cursor:pointer;color:#7c3aed;font-weight:700;font-size:12px;line-height:1;margin-left:2px;">×</span>
                </span>`;
            }).join('');
            const liftColor = r.lift >= 2 ? '#059669' : r.lift >= 1.5 ? '#0891b2' : '#64748b';
            const supN = Math.round(r.support * total);
            const antN = r.confidence > 0 ? Math.round(supN / r.confidence) : 0;
            const fracStyle = `font-size:10px;color:#94a3b8;margin-left:4px;`;
            const antJson = JSON.stringify(r.antecedents).replace(/'/g, "\\'");
            html += `<tr style="background:${bg};"><td style="${tdStyle}">${antStr}</td>
                <td style="${tdStyle}text-align:right;color:#64748b;">${(r.support * 100).toFixed(1)}%<br><span style="${fracStyle}">${supN} / ${total} 筆</span></td>
                <td style="${tdStyle}text-align:right;color:#64748b;">${(r.confidence * 100).toFixed(1)}%<br><span style="${fracStyle}">${supN} / ${antN} 筆</span></td>
                <td style="${tdStyle}text-align:right;font-weight:700;color:${liftColor};">${r.lift.toFixed(2)}</td>
                <td style="${tdStyle}text-align:center;white-space:nowrap;">
                    <button onclick='assocRulesToDataset(${antJson}, this)' title="建立條件篩選資料集"
                        style="cursor:pointer;padding:3px 8px;font-size:10px;border-radius:5px;border:1px solid #a7f3d0;background:#f0fdf4;color:#059669;font-weight:600;">
                        📁 資料集
                    </button>
                </td></tr>`;
        });
        html += `</tbody></table></div>`;
        area.innerHTML = html;
    }

    function _drawAssocScatter(rules, total) {
        const canvas = document.getElementById('assoc-scatter-canvas');
        if (!canvas) return;
        const wrap = canvas.parentElement;
        const W = wrap.clientWidth || 600;
        const H = 300;
        canvas.width = W; canvas.height = H;
        canvas.style.width = W + 'px'; canvas.style.height = H + 'px';
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, W, H);

        const pad = { t: 30, b: 52, l: 62, r: 24 };
        const cw = W - pad.l - pad.r, ch = H - pad.t - pad.b;

        // Axis ranges
        const supVals = rules.map(r => r.support * 100);
        const confVals = rules.map(r => r.confidence * 100);
        const liftVals = rules.map(r => r.lift);
        const supMax = Math.min(Math.ceil(Math.max(...supVals) * 1.2), 100);
        const supMin = Math.max(0, Math.floor(Math.min(...supVals) * 0.8));
        const confMin = Math.max(0, Math.floor(Math.min(...confVals) * 0.9));
        const liftMax = Math.max(...liftVals);
        const liftMin = Math.min(...liftVals);

        const xScale = v => pad.l + ((v - supMin) / Math.max(supMax - supMin, 0.01)) * cw;
        const yScale = v => pad.t + ch - ((v - confMin) / Math.max(100 - confMin, 0.01)) * ch;
        const rScale = lift => 5 + ((lift - liftMin) / Math.max(liftMax - liftMin, 0.01)) * 12;
        const liftColor = lift => {
            const t = Math.min(1, Math.max(0, (lift - liftMin) / Math.max(liftMax - liftMin, 0.01)));
            if (t > 0.66) return `rgba(5,150,105,${0.75 + t * 0.25})`;   // green
            if (t > 0.33) return `rgba(8,145,178,${0.6 + t * 0.3})`;    // blue
            return `rgba(100,116,139,0.6)`;                               // gray
        };

        // Grid
        const FONT = '10px -apple-system,"Segoe UI",sans-serif';
        ctx.strokeStyle = '#eef1f5'; ctx.lineWidth = 0.5;
        for (let i = 0; i <= 5; i++) {
            const y = pad.t + (ch / 5) * i;
            ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(pad.l + cw, y); ctx.stroke();
        }
        for (let i = 0; i <= 5; i++) {
            const x = pad.l + (cw / 5) * i;
            ctx.beginPath(); ctx.moveTo(x, pad.t); ctx.lineTo(x, pad.t + ch); ctx.stroke();
        }

        // Axes
        ctx.strokeStyle = '#cbd5e1'; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(pad.l, pad.t); ctx.lineTo(pad.l, pad.t + ch); ctx.lineTo(pad.l + cw, pad.t + ch); ctx.stroke();

        // Axis labels & ticks
        ctx.fillStyle = '#94a3b8'; ctx.font = FONT; ctx.textAlign = 'center';
        for (let i = 0; i <= 5; i++) {
            const v = supMin + (supMax - supMin) / 5 * i;
            ctx.fillText(v.toFixed(1) + '%', pad.l + cw / 5 * i, pad.t + ch + 14);
        }
        ctx.textAlign = 'right';
        for (let i = 0; i <= 5; i++) {
            const v = confMin + (100 - confMin) / 5 * (5 - i);
            ctx.fillText(v.toFixed(0) + '%', pad.l - 6, pad.t + (ch / 5) * i + 3);
        }

        // Axis titles
        ctx.textAlign = 'center'; ctx.fillStyle = '#64748b';
        ctx.font = 'bold 10px -apple-system,"Segoe UI",sans-serif';
        ctx.fillText('Support（普遍程度）', pad.l + cw / 2, H - 6);
        ctx.save(); ctx.translate(13, pad.t + ch / 2); ctx.rotate(-Math.PI / 2);
        ctx.fillText('Confidence（準確率）', 0, 0); ctx.restore();

        // Dots (draw low-lift first so high-lift is on top)
        const sorted = [...rules].sort((a, b) => a.lift - b.lift);
        const _dotPositions = [];
        sorted.forEach(r => {
            const x = xScale(r.support * 100);
            const y = yScale(r.confidence * 100);
            const rad = rScale(r.lift);
            const color = liftColor(r.lift);
            ctx.beginPath(); ctx.arc(x, y, rad, 0, Math.PI * 2);
            ctx.fillStyle = color; ctx.fill();
            ctx.strokeStyle = 'rgba(255,255,255,0.6)'; ctx.lineWidth = 1; ctx.stroke();
            _dotPositions.push({ x, y, rad, rule: r });
        });

        // Legend: Lift color scale
        const legX = pad.l + cw - 120, legY = pad.t + 8;
        ctx.font = FONT; ctx.fillStyle = '#64748b'; ctx.textAlign = 'left';
        ctx.fillText('Lift 高低：', legX, legY + 10);
        [['高', '#059669'], ['中', '#0891b2'], ['低', '#94a3b8']].forEach(([label, color], i) => {
            ctx.beginPath(); ctx.arc(legX + 60 + i * 24, legY + 6, 6, 0, Math.PI * 2);
            ctx.fillStyle = color; ctx.fill();
            ctx.fillStyle = '#64748b'; ctx.textAlign = 'center';
            ctx.fillText(label, legX + 60 + i * 24, legY + 20);
        });
        ctx.textAlign = 'left';
        ctx.fillStyle = '#94a3b8'; ctx.font = FONT;
        ctx.fillText('圓圈大小 = Lift 大小', pad.l, pad.t + ch + 30);

        // Hover tooltip
        const tip = document.getElementById('assoc-scatter-tip');
        canvas._dotPositions = _dotPositions;
        canvas._total = total;
        if (!canvas._hoverBound) {
            canvas._hoverBound = true;
            canvas.addEventListener('mousemove', function (e) {
                const rect = canvas.getBoundingClientRect();
                const mx = (e.clientX - rect.left) * (canvas.width / rect.width);
                const my = (e.clientY - rect.top) * (canvas.height / rect.height);
                let nearest = null, minD = Infinity;
                (canvas._dotPositions || []).forEach(p => {
                    const d = Math.hypot(mx - p.x, my - p.y);
                    if (d < p.rad + 6 && d < minD) { minD = d; nearest = p; }
                });
                const tipEl = document.getElementById('assoc-scatter-tip');
                if (!nearest || !tipEl) { if (tipEl) tipEl.style.display = 'none'; return; }
                const r = nearest.rule;
                const supN = Math.round(r.support * (canvas._total || 0));
                const antN = r.confidence > 0 ? Math.round(supN / r.confidence) : 0;
                const conds = r.antecedents.map(a => `<span style="background:#ede9fe;color:#5b21b6;border-radius:3px;padding:1px 5px;">${a}</span>`).join(' ');
                tipEl.innerHTML = `
                    <div style="margin-bottom:5px;">${conds}</div>
                    <div style="color:#94a3b8;font-size:10px;">─────────────────</div>
                    <div>Support: <b>${(r.support * 100).toFixed(1)}%</b> <span style="color:#94a3b8;">(${supN} / ${canvas._total} 筆)</span></div>
                    <div>Confidence: <b>${(r.confidence * 100).toFixed(1)}%</b> <span style="color:#94a3b8;">(${supN} / ${antN} 筆)</span></div>
                    <div>Lift: <b style="color:#059669;">${r.lift.toFixed(2)}</b></div>`;
                tipEl.style.display = 'block';
                tipEl.style.left = (e.clientX + 14) + 'px';
                tipEl.style.top = (e.clientY - 10) + 'px';
                // Flip if near right edge
                const tipW = tipEl.offsetWidth || 220;
                if (e.clientX + 14 + tipW > window.innerWidth - 10) {
                    tipEl.style.left = (e.clientX - tipW - 14) + 'px';
                }
            });
            canvas.addEventListener('mouseleave', function () {
                const tipEl = document.getElementById('assoc-scatter-tip');
                if (tipEl) tipEl.style.display = 'none';
            });
        }
    }

    window.assocSort = function (col) {
        if (_assocSortCol === col) _assocSortAsc = !_assocSortAsc;
        else { _assocSortCol = col; _assocSortAsc = false; }
        if (_assocLastResult) _renderResult(_assocLastResult);
    };

    window.assocSetView = function (view) {
        _assocResultView = view;
        if (_assocLastResult) _renderResult(_assocLastResult);
    };

    window.assocRulesToDataset = function (antecedents = [], clickedBtn = null) {
        if (!window.addDatasetToSidebar) return;

        // Parse antecedents ["col=val", ...] → filters [{col, value}]
        const filters = antecedents.map(item => {
            const idx = item.indexOf('=');
            return idx > 0 ? { col: item.slice(0, idx), value: item.slice(idx + 1) } : null;
        }).filter(Boolean);

        if (!filters.length) return;

        const dsId = 'assoc_' + filters.map(f => String(f.value).replace(/[^a-zA-Z0-9\u4e00-\u9fa5]/g, '_')).join('__');
        const dsName = filters.map(f => `${f.col}=${f.value}`).join(' & ');

        window.addDatasetToSidebar({
            id: dsId,
            name: dsName,
            type: 'association',
            fileId: currentFileId,
            rowCount: '',
            filters,
        });

        // 持久化到後端（建立實體資料夾 + meta.json）
        if (typeof window._dsPersistDataset === 'function') {
            window._dsPersistDataset(dsId, dsName, filters, 'association');
        }

        if (clickedBtn) { clickedBtn.textContent = '✅'; clickedBtn.disabled = true; }
    };

})();
