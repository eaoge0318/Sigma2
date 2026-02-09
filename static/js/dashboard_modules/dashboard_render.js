import { DOM, API, WINDOW_SIZE } from './utils.js';
import { createMainChart, getChart, registerChart } from './charts_manager.js';

let lastLogTimestamp = 0;

export async function updateDashboard() {
    try {
        const history = await API.get('/api/history');
        if (history && history.length > 0) {
            renderDashboardData(history);
        }
    } catch (err) {
        console.error("Dashboard Update Failed:", err);
    }
}

export function renderDashboardData(history) {
    try {
        if (!history || history.length === 0) return;

        const last = history[history.length - 1];

        // 1. 更新 Console 資訊
        const diagText = DOM.get('diag-text');
        if (diagText) diagText.innerText = last.diagnosis || "穩定運行中";

        const simText = DOM.get('sim-text');
        if (simText) {
            simText.innerText = last.predicted_y_next
                ? `預計建議後效果穩定，目標值預計為: ${last.predicted_y_next.toFixed(4)}`
                : "不執行調整";
        }

        const curInfluencers = last.current_top_influencers || [];
        const curFactors = curInfluencers.map(f => `<span class="influencer-tag">${f}</span>`).join('');
        const smInfluencers = last.smoothed_top_influencers || [];
        const smFactors = smInfluencers.map(f => `<span class="influencer-tag" style="border-color:#a855f7">${f}</span>`).join('');

        const factorList = DOM.get('factor-list');
        if (factorList) {
            factorList.innerHTML = `<div style="margin-bottom:5px;"><small>[當前]</small> ${curFactors}</div><div><small>[平滑]</small> ${smFactors}</div>`;
        }

        // Sync to Analysis Chart Sidebar if in analysis mode
        // We'll export syncImportantChartColumns logic or ensure it's available.
        // For now, checking if function exists on window/global or importing it.
        // It's not yet extracted, so I will include a placeholder or try to find it.
        if (typeof window.syncImportantChartColumns === 'function') {
            window.syncImportantChartColumns([...new Set([...curInfluencers, ...smInfluencers])]);
        }

        // 2. 更新歷史推理日誌
        if (last.timestamp > lastLogTimestamp) {
            const logContainer = DOM.get('reasoning-logs');
            if (logContainer) {
                const emptyMsg = DOM.get('log-empty-msg');
                if (emptyMsg) emptyMsg.remove();

                const timeStr = new Date(last.timestamp * 1000).toLocaleTimeString();
                const curHtml = (last.current_top_influencers || []).map(f => `<span class="log-factor-tag">${f}</span>`).join('');
                const smHtml = (last.smoothed_top_influencers || []).map(f => `<span class="log-factor-tag" style="border-color:#a855f7; color:#7e22ce">${f}</span>`).join('');

                const logHtml = `
                            <div class="log-item">
                                <div class="log-ts">[${timeStr}]</div>
                                <div class="log-body">
                                    <div class="log-diag">${last.diagnosis || '無診斷數據'}</div>
                                    <div class="log-meta">
                                        影響因子: ${curHtml} | 平滑傾向: ${smHtml}
                                    </div>
                                </div>
                            </div>
                        `;
                logContainer.insertAdjacentHTML('afterbegin', logHtml);
                if (logContainer.children.length > 50) logContainer.lastElementChild.remove();
            }
            lastLogTimestamp = last.timestamp;
        }

        // 3. 更新圖表
        const actionNames = Object.keys(last.recommendations);
        const targetRange = last.target_range;
        const goalName = last.goal_name || "G_std";

        const statusText = DOM.get('status-text');
        if (statusText) {
            statusText.innerText = `[數據流 #${history.length.toString().padStart(4, '0')}] ${goalName}: ${last.current_measure.toFixed(3)} | 狀態: ${last.status}`;
        }

        // Update Real-time Value Cards
        const actualValueElem = DOM.get('current-actual-value');
        const predictedValueElem = DOM.get('current-predicted-value');
        if (actualValueElem) {
            actualValueElem.textContent = last.current_measure.toFixed(3);
        }
        if (predictedValueElem && last.predicted_measure !== undefined) {
            predictedValueElem.textContent = last.predicted_measure.toFixed(3);
        } else if (predictedValueElem) {
            // 如果沒有預測值,顯示當前量測值作為預測基準
            predictedValueElem.textContent = last.current_measure.toFixed(3);
        }

        // Side Panel Hook
        window.lastDashboardData = last;
        if (typeof window.renderSidePanelParams === 'function') window.renderSidePanelParams(last.current_measure, last);

        const wrapper = DOM.get('charts-wrapper');
        if (wrapper) {
            if (actionNames.length === 0) {
                // 如果沒有建議项（可能是模型報錯或處於 HOLD），顯示空狀態提示
                if (wrapper.innerHTML === '') {
                    wrapper.innerHTML = `
                        <div style="padding: 40px; text-align: center; background: #f8fafc; border: 1px dashed #cbd5e1; border-radius: 8px; color: #64748b;">
                            <div style="font-size: 24px; margin-bottom: 10px;">📉</div>
                            目前無模型建議。請確保已載入正確模型，或檢查 AI 診斷訊息。
                        </div>`;
                }
            } else {
                // 清除空狀態提示
                const emptyMsg = wrapper.querySelector('div[style*="dashed"]');
                if (emptyMsg) wrapper.innerHTML = '';

                actionNames.forEach(name => {
                    const safeId = `chart-${name.replace(/[^a-zA-Z0-9]/g, '-')}`;
                    if (!getChart(name)) { // Check via charts_manager
                        const div = document.createElement('div');
                        div.className = 'chart-container';
                        div.innerHTML = `<canvas id="${safeId}" height="100"></canvas>`;
                        wrapper.appendChild(div);
                        // Use charts_manager to create and register
                        const newChart = createMainChart(safeId, name, targetRange, goalName);
                        registerChart(name, newChart);
                    }
                });
            }
        }

        const startIndex = Math.max(0, history.length - WINDOW_SIZE);
        const recentHistory = history.slice(startIndex);
        const labels = Array.from({ length: recentHistory.length }, (_, i) => startIndex + i);
        const nextIdx = history.length;

        actionNames.forEach(name => {
            const chart = getChart(name);
            if (!chart) return;

            const kappaData = recentHistory.map(d => d.current_measure);
            const actionData = recentHistory.map(d => d.recommendations[name].current);

            const predData = recentHistory.map((d, i) => {
                const globalIndex = startIndex + i;
                if (globalIndex === 0) return null;
                const prevRecord = history[globalIndex - 1];
                return prevRecord ? prevRecord.predicted_y_next : null;
            });

            const pastSuggestions = recentHistory.slice(0, -1).map((d, i) => {
                return { x: startIndex + i + 1, y: d.recommendations[name].suggested_next };
            });

            chart.data.labels = labels;
            chart.data.datasets[0].data = kappaData;
            chart.data.datasets[1].data = actionData;
            chart.data.datasets[2].data = pastSuggestions;
            chart.data.datasets[4].data = predData;

            const lastRec = last.recommendations[name];
            if (last.status !== 'HOLD') {
                chart.data.datasets[3].data = [{ x: nextIdx, y: lastRec.suggested_next }];
                chart.data.datasets[3].pointStyle = 'triangle';
                chart.data.datasets[3].rotation = lastRec.suggested_delta > 0 ? 0 : 180;
                chart.data.datasets[3].backgroundColor = lastRec.suggested_delta > 0 ? '#38bdf8' : '#22c55e';

                chart.options.plugins.annotation.annotations.vLine = {
                    type: 'line', xMin: nextIdx, xMax: nextIdx,
                    borderColor: '#cbd5e1', borderDash: [4, 4], borderWidth: 1
                };
                chart.options.plugins.annotation.annotations.hLine = {
                    type: 'line', yScaleID: 'yAction', yMin: lastRec.suggested_next, yMax: lastRec.suggested_next,
                    borderColor: '#a855f7', borderDash: [4, 4], borderWidth: 1
                };
            } else {
                chart.data.datasets[3].data = [];
                chart.options.plugins.annotation.annotations.vLine = { display: false };
                chart.options.plugins.annotation.annotations.hLine = { display: false };
            }

            chart.options.scales.x.min = startIndex;
            chart.options.scales.x.max = startIndex + WINDOW_SIZE + 5;
            chart.update('none');
        });
    } catch (err) { console.error(err); }
}

// Side Panel Rendering Function
export function renderSidePanelParams(currentMeasure, data) {
    const paramList = DOM.get('side-param-list');
    if (!paramList || !data || !data.recommendations) return;

    const recommendations = data.recommendations;
    const currentValues = data.current_values || {};

    let html = `
        <div style="background: #f8fafc; border-radius: 8px; padding: 12px; margin-bottom: 12px;">
            <div style="font-size: 11px; font-weight: 600; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px;">TARGET</div>
            <div style="font-size: 22px; font-weight: 800; color: #1e293b; font-family: 'Roboto Mono', monospace;">${currentMeasure.toFixed(4)}</div>
        </div>
        
        <div style="font-size: 11px; font-weight: 600; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; margin: 16px 0 8px 0; border-bottom: 1px solid #e2e8f0; padding-bottom: 4px;">
            CONTROL PARAMETERS
        </div>
    `;

    for (const [paramName, recObj] of Object.entries(recommendations)) {
        const currentVal = recObj.current || 0;
        const suggestedNext = recObj.suggested_next || 0;
        const delta = suggestedNext - currentVal;

        console.log(`${paramName}: current=${currentVal}, suggested=${suggestedNext}, delta=${delta}`);

        // 根據變化方向決定顏色
        let deltaColor, deltaIcon, deltaBg;
        if (delta > 0.001) {
            // 往上調（正值）= 藍色
            deltaColor = '#3b82f6';
            deltaBg = '#dbeafe';
            deltaIcon = '↑';
        } else if (delta < -0.001) {
            // 往下調（負值）= 綠色
            deltaColor = '#10b981';
            deltaBg = '#d1fae5';
            deltaIcon = '↓';
        } else {
            // 持平
            deltaColor = '#94a3b8';
            deltaBg = '#f1f5f9';
            deltaIcon = '→';
        }

        html += `
            <div style="border-left: 3px solid ${deltaColor}; padding: 8px 10px; margin-bottom: 8px; background: ${deltaBg}20; border-radius: 4px; cursor: pointer; transition: all 0.2s;" 
                 onclick="window.scrollToChart && window.scrollToChart('${paramName}')">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                    <span style="font-weight: 600; color: #1e293b; font-size: 12px;">${paramName}</span>
                    <span style="font-size: 16px;">${deltaIcon}</span>
                </div>
                <div style="display: flex; justify-content: space-between; font-size: 11px;color: #64748b;">
                    <div>
                        <span style="color: #94a3b8;">實際:</span> <span style="font-weight: 600; font-family: 'Roboto Mono', monospace; color: #475569;">${currentVal.toFixed(3)}</span>
                    </div>
                    <div>
                        <span style="color: #94a3b8;">控制:</span> <span style="font-weight: 600; font-family: 'Roboto Mono', monospace; color: ${deltaColor};">${suggestedNext.toFixed(3)}</span>
                    </div>
                </div>
            </div>
        `;
    }

    paramList.innerHTML = html;
}

// 導出為 window 函數供外部使用
window.renderSidePanelParams = renderSidePanelParams;
