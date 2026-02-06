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
