# Y 軸手動調整功能

## 功能說明

加入 Y 軸範圍的手動調整功能,讓使用者可以:
1. 切換自動/手動模式
2. 手動設定 Y 軸的最小值和最大值
3. 即時套用設定到所有圖表

## 實現方式

### 1. 全域變數

在 `dashboard_full.js` 中加入:

```javascript
// Y 軸範圍控制
let yAxisMode = 'auto';  // 'auto' 或 'manual'
let yAxisManualMin = null;
let yAxisManualMax = null;
```

### 2. 修改 createChart 函數

```javascript
function createChart(canvasId, actionName, deadzone, goalName) {
    const ctx = document.getElementById(canvasId).getContext('2d');
    const displayGoalName = goalName || "G_std";
    
    // 計算 Y 軸範圍
    let yMin, yMax;
    if (yAxisMode === 'manual' && yAxisManualMin !== null && yAxisManualMax !== null) {
        yMin = yAxisManualMin;
        yMax = yAxisManualMax;
    } else {
        // 自動模式: 根據 deadzone (LSL/USL) 計算
        yMin = deadzone[0] * 0.9;
        yMax = deadzone[1] * 1.1;
    }
    
    return new Chart(ctx, {
        type: 'line',
        data: {
            datasets: [
                { label: \`實際 \${displayGoalName}\`, data: [], borderColor: '#ef4444', yAxisID: 'yKappa', borderWidth: 2.5, pointRadius: 0, order: 1 },
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
            scales: {
                x: { type: 'linear', display: true, grid: { color: '#f1f5f9' }, beginAtZero: false },
                yKappa: { 
                    position: 'left', 
                    min: yMin,
                    max: yMax,
                    title: { display: true, text: displayGoalName, color: '#ef4444' } 
                },
                yAction: { position: 'right', grid: { display: false }, title: { display: true, text: actionName }, beginAtZero: false }
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
}
```

### 3. 加入控制函數

```javascript
// 切換 Y 軸模式
function toggleYAxisMode() {
    yAxisMode = yAxisMode === 'auto' ? 'manual' : 'auto';
    
    if (yAxisMode === 'manual') {
        // 切換到手動模式時,顯示輸入框
        document.getElementById('y-axis-manual-controls').style.display = 'flex';
        
        // 如果還沒設定過,使用當前的自動範圍作為預設值
        if (yAxisManualMin === null || yAxisManualMax === null) {
            const firstChart = Object.values(charts)[0];
            if (firstChart) {
                yAxisManualMin = firstChart.options.scales.yKappa.min;
                yAxisManualMax = firstChart.options.scales.yKappa.max;
                document.getElementById('y-axis-min-input').value = yAxisManualMin.toFixed(2);
                document.getElementById('y-axis-max-input').value = yAxisManualMax.toFixed(2);
            }
        }
    } else {
        // 切換到自動模式時,隱藏輸入框
        document.getElementById('y-axis-manual-controls').style.display = 'none';
    }
    
    // 更新按鈕文字
    updateYAxisModeButton();
    
    // 重新建立所有圖表
    recreateAllCharts();
}

// 更新按鈕文字
function updateYAxisModeButton() {
    const btn = document.getElementById('y-axis-mode-btn');
    if (btn) {
        btn.innerText = yAxisMode === 'auto' ? '🔄 自動範圍' : '✏️ 手動範圍';
        btn.style.background = yAxisMode === 'auto' ? '#10b981' : '#f59e0b';
    }
}

// 套用手動設定的 Y 軸範圍
function applyManualYAxisRange() {
    const minInput = document.getElementById('y-axis-min-input');
    const maxInput = document.getElementById('y-axis-max-input');
    
    const min = parseFloat(minInput.value);
    const max = parseFloat(maxInput.value);
    
    if (isNaN(min) || isNaN(max)) {
        alert('請輸入有效的數值');
        return;
    }
    
    if (min >= max) {
        alert('最小值必須小於最大值');
        return;
    }
    
    yAxisManualMin = min;
    yAxisManualMax = max;
    
    // 重新建立所有圖表
    recreateAllCharts();
}

// 重新建立所有圖表
function recreateAllCharts() {
    // 清空現有圖表
    Object.keys(charts).forEach(name => {
        charts[name].destroy();
    });
    charts = {};
    
    // 清空圖表容器
    const wrapper = document.getElementById('charts-wrapper');
    wrapper.innerHTML = '';
    
    // 觸發一次更新,重新建立圖表
    updateDashboard();
}
```

### 4. HTML UI (加入到 dashboard.html)

在適當的位置加入以下 HTML:

```html
<!-- Y 軸範圍控制 -->
<div style="display: flex; align-items: center; gap: 10px; margin: 10px 0;">
    <button id="y-axis-mode-btn" onclick="toggleYAxisMode()" 
            style="padding: 8px 16px; border: none; border-radius: 6px; color: white; 
                   background: #10b981; cursor: pointer; font-weight: 600; font-size: 13px;">
        🔄 自動範圍
    </button>
    
    <div id="y-axis-manual-controls" style="display: none; align-items: center; gap: 8px;">
        <label style="font-size: 13px; color: #64748b; font-weight: 600;">Y 軸範圍:</label>
        <input type="number" id="y-axis-min-input" placeholder="最小值" step="0.1"
               style="width: 80px; padding: 6px; border: 1px solid #cbd5e1; border-radius: 6px; font-size: 12px;">
        <span style="color: #94a3b8;">~</span>
        <input type="number" id="y-axis-max-input" placeholder="最大值" step="0.1"
               style="width: 80px; padding: 6px; border: 1px solid #cbd5e1; border-radius: 6px; font-size: 12px;">
        <button onclick="applyManualYAxisRange()" 
                style="padding: 6px 12px; border: none; border-radius: 6px; background: #3b82f6; 
                       color: white; cursor: pointer; font-size: 12px; font-weight: 600;">
            套用
        </button>
    </div>
</div>
```

## 使用方式

1. **自動模式** (預設):
   - Y 軸範圍根據 LSL/USL 自動計算
   - 範圍 = [LSL × 0.9, USL × 1.1]

2. **切換到手動模式**:
   - 點擊 "🔄 自動範圍" 按鈕
   - 按鈕變為 "✏️ 手動範圍"
   - 顯示輸入框,預設值為當前的自動範圍

3. **調整範圍**:
   - 在輸入框中輸入最小值和最大值
   - 點擊 "套用" 按鈕
   - 所有圖表立即更新

4. **切換回自動模式**:
   - 再次點擊 "✏️ 手動範圍" 按鈕
   - 按鈕變回 "🔄 自動範圍"
   - 隱藏輸入框,恢復自動計算

## 注意事項

1. 手動設定的範圍會保留,直到切換回自動模式
2. 切換模式時會重新建立所有圖表
3. 手動模式下,即使載入新的模型,範圍也不會改變
4. 建議在模擬開始前設定好範圍

## 位置建議

建議將 Y 軸控制 UI 放在以下位置之一:
1. 圖表區域的頂部 (與 "Reset Monitor" 按鈕同一行)
2. 側邊欄的控制面板中
3. 模擬控制區域

根據您的 UI 布局,選擇最合適的位置。
