// ==================== Y 軸點擊調整功能 ====================

// 在 createChart 函數中加入 Y 軸點擊事件
// 需要在 Chart.js 的 options.onClick 中處理

// 顯示 Y 軸範圍調整模態框
function showYAxisRangeModal(chartName) {
    // 建立模態框 (如果不存在)
    let modal = document.getElementById('y-axis-range-modal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'y-axis-range-modal';
        modal.style.cssText = `
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.5);
            z-index: 10000;
            align-items: center;
            justify-content: center;
        `;

        modal.innerHTML = `
            <div style="background: white; border-radius: 12px; padding: 24px; width: 400px; box-shadow: 0 10px 25px rgba(0,0,0,0.3);">
                <h3 style="margin: 0 0 16px 0; font-size: 18px; color: #1e293b;">Y 軸範圍設定</h3>
                
                <!-- 模式切換 -->
                <div style="margin-bottom: 16px;">
                    <label style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
                        <input type="radio" name="y-axis-mode-radio" value="auto" checked onchange="updateYAxisModeInModal()">
                        <span style="font-size: 14px; font-weight: 600;">🔄 自動範圍</span>
                        <span style="font-size: 12px; color: #64748b;">(根據 LSL/USL 自動計算)</span>
                    </label>
                </div>
                
                <div style="margin-bottom: 20px;">
                    <label style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
                        <input type="radio" name="y-axis-mode-radio" value="manual" onchange="updateYAxisModeInModal()">
                        <span style="font-size: 14px; font-weight: 600;">✏️ 手動範圍</span>
                    </label>
                </div>
                
                <!-- 手動範圍輸入 -->
                <div id="modal-manual-inputs" style="display: none; margin-bottom: 20px; padding: 12px; background: #f8fafc; border-radius: 8px;">
                    <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 8px;">
                        <label style="width: 60px; font-size: 13px; color: #64748b; font-weight: 600;">最小值:</label>
                        <input type="number" id="modal-y-min" step="0.1" 
                               style="flex: 1; padding: 8px; border: 1px solid #cbd5e1; border-radius: 6px; font-size: 13px; outline: none;">
                    </div>
                    <div style="display: flex; align-items: center; gap: 12px;">
                        <label style="width: 60px; font-size: 13px; color: #64748b; font-weight: 600;">最大值:</label>
                        <input type="number" id="modal-y-max" step="0.1" 
                               style="flex: 1; padding: 8px; border: 1px solid #cbd5e1; border-radius: 6px; font-size: 13px; outline: none;">
                    </div>
                </div>
                
                <!-- 當前範圍顯示 -->
                <div style="margin-bottom: 20px; padding: 10px; background: #eff6ff; border-radius: 6px; border: 1px solid #bfdbfe;">
                    <div style="font-size: 12px; color: #1e40af; font-weight: 600;">當前範圍:</div>
                    <div id="modal-current-range" style="font-size: 13px; color: #3b82f6; margin-top: 4px;"></div>
                </div>
                
                <!-- 按鈕 -->
                <div style="display: flex; gap: 10px; justify-content: flex-end;">
                    <button onclick="closeYAxisRangeModal()" 
                            style="padding: 8px 16px; border: 1px solid #cbd5e1; border-radius: 6px; background: white; color: #64748b; cursor: pointer; font-size: 13px; font-weight: 600;">
                        取消
                    </button>
                    <button onclick="applyYAxisRangeFromModal()" 
                            style="padding: 8px 16px; border: none; border-radius: 6px; background: #3b82f6; color: white; cursor: pointer; font-size: 13px; font-weight: 600;">
                        套用
                    </button>
                </div>
            </div>
        `;

        document.body.appendChild(modal);

        // 點擊背景關閉
        modal.addEventListener('click', (e) => {
            if (e.target === modal) closeYAxisRangeModal();
        });
    }

    // 顯示模態框
    modal.style.display = 'flex';

    // 更新當前範圍顯示
    updateCurrentRangeDisplay();

    // 設定當前模式
    const autoRadio = document.querySelector('input[name="y-axis-mode-radio"][value="auto"]');
    const manualRadio = document.querySelector('input[name="y-axis-mode-radio"][value="manual"]');

    if (yAxisMode === 'manual') {
        manualRadio.checked = true;
        document.getElementById('modal-manual-inputs').style.display = 'block';
        document.getElementById('modal-y-min').value = yAxisManualMin?.toFixed(2) || '';
        document.getElementById('modal-y-max').value = yAxisManualMax?.toFixed(2) || '';
    } else {
        autoRadio.checked = true;
        document.getElementById('modal-manual-inputs').style.display = 'none';
    }
}

// 關閉模態框
function closeYAxisRangeModal() {
    const modal = document.getElementById('y-axis-range-modal');
    if (modal) modal.style.display = 'none';
}

// 更新模態框中的模式
function updateYAxisModeInModal() {
    const selectedMode = document.querySelector('input[name="y-axis-mode-radio"]:checked').value;
    const manualInputs = document.getElementById('modal-manual-inputs');

    if (selectedMode === 'manual') {
        manualInputs.style.display = 'block';

        // 如果還沒設定過,使用當前範圍
        const minInput = document.getElementById('modal-y-min');
        const maxInput = document.getElementById('modal-y-max');

        if (!minInput.value || !maxInput.value) {
            const firstChart = Object.values(charts)[0];
            if (firstChart) {
                minInput.value = firstChart.options.scales.yKappa.min.toFixed(2);
                maxInput.value = firstChart.options.scales.yKappa.max.toFixed(2);
            }
        }
    } else {
        manualInputs.style.display = 'none';
    }
}

// 更新當前範圍顯示
function updateCurrentRangeDisplay() {
    const display = document.getElementById('modal-current-range');
    if (!display) return;

    const firstChart = Object.values(charts)[0];
    if (firstChart) {
        const min = firstChart.options.scales.yKappa.min;
        const max = firstChart.options.scales.yKappa.max;
        display.textContent = `${min.toFixed(2)} ~ ${max.toFixed(2)}`;
    }
}

// 從模態框套用設定
function applyYAxisRangeFromModal() {
    const selectedMode = document.querySelector('input[name="y-axis-mode-radio"]:checked').value;

    if (selectedMode === 'manual') {
        const minInput = document.getElementById('modal-y-min');
        const maxInput = document.getElementById('modal-y-max');

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

        yAxisMode = 'manual';
        yAxisManualMin = min;
        yAxisManualMax = max;
    } else {
        yAxisMode = 'auto';
        yAxisManualMin = null;
        yAxisManualMax = null;
    }

    // 重新建立所有圖表
    recreateAllCharts();

    // 關閉模態框
    closeYAxisRangeModal();
}
