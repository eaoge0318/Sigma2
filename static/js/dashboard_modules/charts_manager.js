
// =========================
// charts_manager.js - Chart.js Handling
// =========================
import { DOM, API } from './utils.js';

let charts = {};
// Global state for chart dragging
let goalChartDragState = {
    active: false,
    targetId: null
};

// Global Y-Axis State
let yAxisConfig = {
    mode: 'auto', // 'auto' or 'manual'
    min: null,
    max: null
};

// Global Y2-Axis State (Right Axis)
let y2AxisConfig = {
    min: null,
    max: null
};

// Global Y2-Axis Ranges (Per Parameter)
let y2AxisRanges = {};

export function setAllY2Ranges(ranges) {
    console.log("Setting Y2 Ranges:", ranges);
    y2AxisRanges = ranges || {};
    updateAllChartsYAxis();
}
window.setAllY2Ranges = setAllY2Ranges;

export function setY2Range(min, max) {
    y2AxisConfig.min = min;
    y2AxisConfig.max = max;
    updateAllChartsYAxis();
}
window.setY2Range = setY2Range;


export function getChart(id) {
    return charts[id];
}

export function destroyChart(id) {
    if (charts[id]) {
        charts[id].destroy();
        delete charts[id];
    }
}

export function registerChart(id, instance) {
    charts[id] = instance;
}

export function resizeAllCharts() {
    Object.values(charts).forEach(chart => {
        if (chart && typeof chart.resize === 'function') {
            chart.resize();
        }
    });
}

export function createMainChart(canvasId, actionName, deadzone, goalName, yAxisMode, yAxisManualMin, yAxisManualMax) {
    const ctx = DOM.get(canvasId).getContext('2d');
    const displayGoalName = goalName || "G_std";

    // Calculate Y Axis Range
    let yMin, yMax;
    if (yAxisMode === 'manual' && yAxisManualMin !== null && yAxisManualMax !== null) {
        yMin = yAxisManualMin;
        yMax = yAxisManualMax;
    } else {
        yMin = deadzone[0] * 0.9;
        yMax = deadzone[1] * 1.1;
    }

    const chart = new Chart(ctx, {
        type: 'line',
        data: {
            datasets: [
                { label: `實際 ${displayGoalName}`, data: [], borderColor: '#ef4444', yAxisID: 'yKappa', borderWidth: 2.5, pointRadius: 0, order: 1 },
                { label: '控制項真實路徑', data: [], borderColor: '#1e293b', yAxisID: 'yAction', borderWidth: 2.5, pointRadius: 0, order: 2, stepped: false, tension: 0 },
                { label: '歷史建議', data: [], type: 'scatter', yAxisID: 'yAction', pointStyle: 'triangle', backgroundColor: 'rgba(148, 163, 184, 0.5)', pointRadius: 5, borderWidth: 0, order: 3 },
                { label: '當前建議', data: [], type: 'scatter', yAxisID: 'yAction', pointRadius: 10, pointBorderWidth: 2, order: 0 },
                { label: '物理預測', data: [], borderColor: '#3b82f6', yAxisID: 'yKappa', borderWidth: 1.5, borderDash: [5, 5], pointRadius: 0, order: 4 }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            onHover: (e, elements, chart) => {
                // Change cursor when hovering Y-Axis area (Left or Right)
                if (e.x < chart.chartArea.left || e.x > chart.chartArea.right) {
                    e.native.target.style.cursor = 'pointer';
                } else {
                    e.native.target.style.cursor = 'default';
                }
            },
            layout: {
                padding: { left: 0, right: 0, top: 0, bottom: 0 }
            },
            scales: {
                x: { type: 'linear', display: true, grid: { color: '#f1f5f9' }, beginAtZero: false },
                yKappa: {
                    position: 'left',
                    min: yAxisConfig.mode === 'manual' ? yAxisConfig.min : yMin,
                    max: yAxisConfig.mode === 'manual' ? yAxisConfig.max : yMax,
                    title: { display: true, text: displayGoalName, color: '#ef4444' }
                },
                yAction: {
                    position: 'right',
                    grid: { display: false },
                    title: { display: true, text: actionName },
                    beginAtZero: false,
                    min: y2AxisConfig.min,
                    max: y2AxisConfig.max
                }
            },
            plugins: {
                legend: { position: 'top', align: 'end', labels: { boxWidth: 10, font: { size: 10 } } },
                annotation: {
                    annotations: {
                        deadzone: { type: 'box', yScaleID: 'yKappa', yMin: deadzone[0], yMax: deadzone[1], backgroundColor: 'rgba(34, 197, 94, 0.08)', borderWidth: 0, z: -10 }
                    }
                }
            }
        }
    });

    // Native Click Handler for Y-Axis
    const canvas = DOM.get(canvasId);
    if (canvas) {
        canvas.addEventListener('click', (e) => {
            const rect = canvas.getBoundingClientRect();
            const x = e.clientX - rect.left;

            if (!chart.chartArea) return;

            // Check Y1 Axis (Left)
            if (x < chart.chartArea.left) {
                console.log('Y1 Axis Clicked');
                if (typeof window.openYAxisModal === 'function') {
                    window.openYAxisModal();
                } else {
                    console.error('window.openYAxisModal missing');
                }
            }
            // Check Y2 Axis (Right)
            else if (x > chart.chartArea.right) {
                console.log('Y2 Axis Clicked:', actionName);
                if (typeof window.openY2AxisModal === 'function') {
                    window.openY2AxisModal(actionName);
                } else {
                    console.error('window.openY2AxisModal missing');
                }
            }
        });
    }

    return chart;
}

export function initGoalChartDrag() {
    const canvas = DOM.get('goal-column-chart-canvas');
    if (!canvas) return;

    canvas.addEventListener('mousemove', function (e) {
        const goalChart = charts['goal'];
        if (!goalChart || !goalChart.scales || !goalChart.scales.y) return;

        const rect = canvas.getBoundingClientRect();
        const y = e.clientY - rect.top;
        const scaleY = goalChart.scales.y;

        // 1. Handling Drag
        if (goalChartDragState.active && goalChartDragState.targetId) {
            const newVal = scaleY.getValueForPixel(y);
            const input = DOM.get(goalChartDragState.targetId);
            if (input) {
                input.value = newVal.toFixed(4);
                updateGoalChartLines(); // Update chart & UI
            }
            return;
        }

        // 2. Handling Hover Check
        const inputs = {
            'goal-target': DOM.val('goal-target'),
            'goal-usl': DOM.val('goal-usl'),
            'goal-lsl': DOM.val('goal-lsl')
        };

        let hit = null;
        let minDist = 10; // Pixel tolerance

        for (const [id, valStr] of Object.entries(inputs)) {
            if (!valStr || isNaN(parseFloat(valStr))) continue;
            const val = parseFloat(valStr);
            const pixel = scaleY.getPixelForValue(val);
            if (Math.abs(pixel - y) < minDist) {
                hit = id;
                break;
            }
        }

        if (hit) {
            canvas.style.cursor = 'row-resize';
            goalChartDragState.hoverTarget = hit;
        } else {
            canvas.style.cursor = 'default';
            goalChartDragState.hoverTarget = null;
        }
    });

    canvas.addEventListener('mousedown', function (e) {
        if (goalChartDragState.hoverTarget) {
            goalChartDragState.active = true;
            goalChartDragState.targetId = goalChartDragState.hoverTarget;
            e.preventDefault(); // Prevent text selection
        }
    });

    const stopDrag = () => {
        goalChartDragState.active = false;
        goalChartDragState.targetId = null;
    };

    canvas.addEventListener('mouseup', stopDrag);
    canvas.addEventListener('mouseleave', stopDrag);
}

export function updateGoalChartLines() {
    const goalChart = charts['goal'];
    if (!goalChart) return;

    const target = parseFloat(DOM.val('goal-target'));
    const usl = parseFloat(DOM.val('goal-usl'));
    const lsl = parseFloat(DOM.val('goal-lsl'));

    const annotations = {};
    if (!isNaN(target)) {
        annotations.targetLine = {
            type: 'line', yMin: target, yMax: target, borderColor: '#10b981', borderWidth: 2,
            label: { display: true, content: 'Target', position: 'end', backgroundColor: '#10b981', color: '#fff', font: { size: 10 } }
        };
    }
    if (!isNaN(usl)) {
        annotations.uslLine = {
            type: 'line', yMin: usl, yMax: usl, borderColor: '#ef4444', borderWidth: 1, borderDash: [5, 5],
            label: { display: true, content: 'USL', position: 'start', backgroundColor: '#ef4444', color: '#fff', font: { size: 10 } }
        };
    }
    if (!isNaN(lsl)) {
        annotations.lslLine = {
            type: 'line', yMin: lsl, yMax: lsl, borderColor: '#f59e0b', borderWidth: 1, borderDash: [5, 5],
            label: { display: true, content: 'LSL', position: 'start', backgroundColor: '#f59e0b', color: '#fff', font: { size: 10 } }
        };
    }

    goalChart.options.plugins.annotation.annotations = annotations;
    goalChart.update();

    // Stats update
    if (window.lastGoalValues && window.lastGoalValues.length > 0) {
        let outCount = 0;
        window.lastGoalValues.forEach(v => {
            if (!isNaN(usl) && v > usl) outCount++;
            else if (!isNaN(lsl) && v < lsl) outCount++;
        });

        const total = window.lastGoalValues.length;
        const ratio = (outCount / total) * 100;

        DOM.setText('goal-out-count', outCount);
        DOM.setText('goal-total-count', `(${total})`);
        DOM.setText('goal-out-ratio', ratio.toFixed(2) + '%');
    }

    // 更新側邊欄狀態為完成
    const goalCol = DOM.val('model-goal-col');
    const step1Title = document.querySelector('#train-step-nav-1 .step-title');
    if (step1Title) {
        if (goalCol && (!isNaN(target) || !isNaN(usl) || !isNaN(lsl))) {
            if (!step1Title.innerText.includes('(完成)')) {
                step1Title.innerText = '任務標的 (完成)';
                step1Title.style.color = '#10b981';
            }
        } else {
            step1Title.innerText = '任務標的';
            step1Title.style.color = '';
        }
    }
    // 觸發全局完成度檢查
    if (typeof window.checkGlobalTrainingStatus === 'function') window.checkGlobalTrainingStatus();
}

export async function drawGoalChart(colName) {
    const canvas = DOM.get('goal-column-chart-canvas');
    if (!canvas) return;

    if (!colName || !window.currentTrainingFilename) {
        if (charts['goal']) {
            charts['goal'].destroy();
            delete charts['goal'];
        }
        DOM.val('goal-target', '');
        DOM.val('goal-usl', '');
        DOM.val('goal-lsl', '');
        DOM.setText('goal-out-count', '0');
        DOM.setText('goal-out-ratio', '0.00%');
        return;
    }

    try {
        const data = await API.get(`/api/view_file/${window.currentTrainingFilename}`, { page: 1, page_size: 500 });

        let headerRow = [];
        let rows = [];
        if (data.headers) {
            headerRow = data.headers;
            rows = data.rows || [];
        } else if (data.content) {
            const rawLines = data.content.trim().split('\n');
            headerRow = rawLines[0].split(',').map(h => h.trim());
            rows = rawLines.slice(1).map(l => l.split(',').map(v => v.trim()));
        }

        const colIdx = headerRow.indexOf(colName);
        if (colIdx === -1) return;

        const seriesData = rows.map((r, i) => ({
            x: i,
            y: parseFloat(r[colIdx])
        })).filter(d => !isNaN(d.y));

        const values = seriesData.map(d => d.y);
        window.lastGoalValues = values; // Store globally for stats

        // Auto Calc Limits
        if (values.length > 0) {
            const mean = values.reduce((a, b) => a + b, 0) / values.length;
            const sqDiffs = values.map(v => Math.pow(v - mean, 2));
            const std = Math.sqrt(sqDiffs.reduce((a, b) => a + b, 0) / values.length);

            DOM.val('goal-target', mean.toFixed(4));
            DOM.val('goal-usl', (mean + 3 * std).toFixed(4));
            DOM.val('goal-lsl', (mean - 3 * std).toFixed(4));
        }

        if (charts['goal']) charts['goal'].destroy();

        charts['goal'] = new Chart(canvas.getContext('2d'), {
            type: 'scatter',
            data: {
                datasets: [{
                    label: colName,
                    data: seriesData,
                    backgroundColor: 'rgba(59, 130, 246, 0.6)',
                    borderColor: '#3b82f6',
                    borderWidth: 1,
                    pointRadius: 3
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: { title: { display: true, text: 'Index', font: { size: 10 } } },
                    y: { title: { display: true, text: 'Value', font: { size: 10 } } }
                },
                plugins: {
                    legend: { display: false },
                    annotation: { annotations: {} }
                }
            }
        });

        updateGoalChartLines();
    } catch (err) {
        console.error("Draw goal chart failed:", err);
    }
}

export function calculateThreeSigma() {
    if (!window.lastGoalValues || window.lastGoalValues.length === 0) {
        alert('無可用數據，請先選擇目標欄位。');
        return;
    }
    const values = window.lastGoalValues;
    const mean = values.reduce((a, b) => a + b, 0) / values.length;
    const sqDiffs = values.map(v => Math.pow(v - mean, 2));
    const std = Math.sqrt(sqDiffs.reduce((a, b) => a + b, 0) / values.length);

    DOM.val('goal-target', mean.toFixed(4));
    DOM.val('goal-usl', (mean + 3 * std).toFixed(4));
    DOM.val('goal-lsl', (mean - 3 * std).toFixed(4));

    updateGoalChartLines();
}

// Window Exports for HTML Access
window.calculateThreeSigma = calculateThreeSigma;
window.updateGoalChartLines = updateGoalChartLines;
window.drawGoalChart = drawGoalChart;
window.initGoalChartDrag = initGoalChartDrag;
window.createMainChart = createMainChart;

// --- Y-Axis Control Functions ---

// Helper for Esc key
function settingsModalEscHandler(e) {
    if (e.key === 'Escape') {
        closeYAxisSettings();
    }
}

export function openYAxisModal() {
    const modal = document.getElementById('yaxis-settings-modal');
    if (modal) {
        modal.style.display = 'flex';
        modal.style.zIndex = '99999'; // Force high z-index
        modal.style.visibility = 'visible';
        modal.style.opacity = '1';

        // Add Esc listener
        window.addEventListener('keydown', settingsModalEscHandler);

        if (yAxisConfig.mode === 'manual') {
            document.getElementById('yaxis-min-input').value = yAxisConfig.min;
            document.getElementById('yaxis-max-input').value = yAxisConfig.max;
        } else {
            // Auto-fill current bounds from the first available chart
            const firstChart = Object.values(charts).find(c => c && c.scales && c.scales.yKappa);
            if (firstChart && firstChart.scales.yKappa) {
                // Use .min and .max from the scale instance (computed values), rounded to 3 decimals
                document.getElementById('yaxis-min-input').value = firstChart.scales.yKappa.min.toFixed(3);
                document.getElementById('yaxis-max-input').value = firstChart.scales.yKappa.max.toFixed(3);
            } else {
                document.getElementById('yaxis-min-input').value = '';
                document.getElementById('yaxis-max-input').value = '';
            }
        }
    }
}

export function closeYAxisSettings() {
    DOM.hide('yaxis-settings-modal');
    window.removeEventListener('keydown', settingsModalEscHandler);
}

export function applyYAxisSettings() {
    const minVal = parseFloat(document.getElementById('yaxis-min-input').value);
    const maxVal = parseFloat(document.getElementById('yaxis-max-input').value);

    if (isNaN(minVal) || isNaN(maxVal)) {
        alert("請輸入有效的數字");
        return;
    }

    if (minVal >= maxVal) {
        alert("最小值必須小於最大值");
        return;
    }

    yAxisConfig.mode = 'manual';
    yAxisConfig.min = minVal;
    yAxisConfig.max = maxVal;

    closeYAxisSettings();
    updateAllChartsYAxis();
}

export function resetYAxisSettings() {
    yAxisConfig.mode = 'auto';
    yAxisConfig.min = null;
    yAxisConfig.max = null;

    closeYAxisSettings();
    updateAllChartsYAxis();
}

function updateAllChartsYAxis() {
    Object.values(charts).forEach(chart => {
        // Fix: chart.id can be 0, so !chart.id would be true, skipping the chart.
        if (!chart) return;

        // Only update yKappa axis (the left one)
        if (chart.options.scales.yKappa) {
            if (yAxisConfig.mode === 'manual') {
                chart.options.scales.yKappa.min = yAxisConfig.min;
                chart.options.scales.yKappa.max = yAxisConfig.max;
            } else {
                delete chart.options.scales.yKappa.min;
                delete chart.options.scales.yKappa.max;
            }
            // chart.update(); // Move update to end
        }

        // Update Y2 Action Axis
        // Update Y2 Action Axis
        if (chart.options.scales.yAction) {
            // Try to find parameter specific range first
            const paramName = chart.options.scales.yAction.title.text;
            const specificRange = y2AxisRanges[paramName];

            if (specificRange && Array.isArray(specificRange)) {
                // Apply specific 6-sigma range
                chart.options.scales.yAction.min = specificRange[0];
                chart.options.scales.yAction.max = specificRange[1];
            } else if (y2AxisConfig.min !== null && y2AxisConfig.max !== null) {
                // Fallback to global manual setting
                chart.options.scales.yAction.min = y2AxisConfig.min;
                chart.options.scales.yAction.max = y2AxisConfig.max;
            } else {
                delete chart.options.scales.yAction.min;
                delete chart.options.scales.yAction.max;
            }
        }

        chart.update();
    });
}

window.openYAxisModal = openYAxisModal;
window.closeYAxisSettings = closeYAxisSettings;
window.applyYAxisSettings = applyYAxisSettings;
window.resetYAxisSettings = resetYAxisSettings;
window.destroyChart = destroyChart;
window.getChart = getChart;
window.registerChart = registerChart;
window.resizeAllCharts = resizeAllCharts;

// --- Y2-Axis Control Functions ---
let currentY2ParamName = null;

function y2SettingsModalEscHandler(e) {
    if (e.key === 'Escape') {
        closeY2AxisSettings();
    }
}

export function openY2AxisModal(paramName) {
    currentY2ParamName = paramName;
    const modal = document.getElementById('y2axis-settings-modal');
    if (modal) {
        modal.style.display = 'flex';
        modal.style.zIndex = '99999';
        modal.style.visibility = 'visible';
        modal.style.opacity = '1';

        // Update modal title with parameter name
        const titleElem = document.getElementById('y2axis-modal-title');
        if (titleElem) {
            titleElem.textContent = `Y2 軸範圍設定 (${paramName})`;
        }

        // Add Esc listener
        window.addEventListener('keydown', y2SettingsModalEscHandler);

        // Pre-fill with current range if exists
        const currentRange = y2AxisRanges[paramName];
        if (currentRange && Array.isArray(currentRange)) {
            document.getElementById('y2axis-min-input').value = currentRange[0].toFixed(3);
            document.getElementById('y2axis-max-input').value = currentRange[1].toFixed(3);
        } else {
            // Try to get from chart
            const targetChart = Object.values(charts).find(c =>
                c && c.options.scales.yAction && c.options.scales.yAction.title.text === paramName
            );
            if (targetChart && targetChart.scales.yAction) {
                document.getElementById('y2axis-min-input').value = targetChart.scales.yAction.min ? targetChart.scales.yAction.min.toFixed(3) : '';
                document.getElementById('y2axis-max-input').value = targetChart.scales.yAction.max ? targetChart.scales.yAction.max.toFixed(3) : '';
            } else {
                document.getElementById('y2axis-min-input').value = '';
                document.getElementById('y2axis-max-input').value = '';
            }
        }
    }
}

export function closeY2AxisSettings() {
    const modal = document.getElementById('y2axis-settings-modal');
    if (modal) {
        modal.style.display = 'none';
    }
    window.removeEventListener('keydown', y2SettingsModalEscHandler);
    currentY2ParamName = null;
}

export function applyY2AxisSettings() {
    if (!currentY2ParamName) {
        alert("錯誤：未指定參數名稱");
        return;
    }

    const minVal = parseFloat(document.getElementById('y2axis-min-input').value);
    const maxVal = parseFloat(document.getElementById('y2axis-max-input').value);

    if (isNaN(minVal) || isNaN(maxVal)) {
        alert("請輸入有效的數字");
        return;
    }

    if (minVal >= maxVal) {
        alert("最小值必須小於最大值");
        return;
    }

    // Update specific parameter range
    y2AxisRanges[currentY2ParamName] = [minVal, maxVal];
    console.log(`Updated Y2 range for ${currentY2ParamName}:`, [minVal, maxVal]);

    closeY2AxisSettings();
    updateAllChartsYAxis();
}

export function resetY2AxisSettings() {
    if (!currentY2ParamName) {
        alert("錯誤：未指定參數名稱");
        return;
    }

    // Remove specific parameter range (fallback to auto or backend 6-sigma)
    delete y2AxisRanges[currentY2ParamName];
    console.log(`Reset Y2 range for ${currentY2ParamName} to auto`);

    closeY2AxisSettings();
    updateAllChartsYAxis();
}

window.openY2AxisModal = openY2AxisModal;
window.closeY2AxisSettings = closeY2AxisSettings;
window.applyY2AxisSettings = applyY2AxisSettings;
window.resetY2AxisSettings = resetY2AxisSettings;

// Auto-init drag listeners when loaded
setTimeout(initGoalChartDrag, 1000);
