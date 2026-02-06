// 即時看板模組 - 管理即時數據流和預測
export class DashboardManager {
    constructor(sessionManager, chartsManager) {
        console.log('[Dashboard] Constructor called');
        this.sessionManager = sessionManager;
        this.chartsManager = chartsManager;
        this.lastLogTimestamp = 0;
        this.autoPlayTimer = null;

        // 立即初始化控制項（而不是延遲）
        console.log('[Dashboard] Preparing to init controls...');
        this.initDashboardControls().catch(err => {
            console.error('[Dashboard] Failed to init controls:', err);
        });
    }

    async triggerSimulatorNext() {
        try {
            const response = await fetch('/api/simulator/next', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: this.sessionManager.sessionId })
            });

            // 檢查 HTTP 狀態碼
            if (!response.ok) {
                const errorData = await response.json();
                const errorMsg = errorData.detail || '模擬器執行失敗';
                alert(errorMsg);
                this.stopAutoPlay();
                return;
            }

            const data = await response.json();

            if (data.status === 'EOF') {
                alert(data.message);
                this.stopAutoPlay();
            } else {
                await this.updateDashboard();
            }
        } catch (err) {
            console.error("Simulator Error:", err);
            alert(`模擬器錯誤: ${err.message}`);
            this.stopAutoPlay();
        }
    }

    async runFullSimulation() {
        // 檢查是否已選擇檔案和模型
        const fileSelect = document.getElementById('dashboard-file-select');
        const modelSelect = document.getElementById('dashboard-model-select');

        if (!fileSelect.value) {
            alert('⚠️ 請先選擇模擬檔案');
            return;
        }

        if (!modelSelect.value) {
            alert('⚠️ 請先選擇模型');
            return;
        }

        this.stopAutoPlay();

        await fetch('/api/clear', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: this.sessionManager.sessionId })
        });

        // 清空前端顯示狀態
        this.lastLogTimestamp = 0;
        '<div id="log-empty-msg" style="color: #94a3b8; text-align: center; padding: 30px;">目前沒有數據，請先啟動系統以收集數據。</div>';
        document.getElementById('ai-report-content').innerHTML =
            '<div class="ai-bubble chat-bubble">👋 模擬已重設，正在重新讀取數據集...</div>';
        document.getElementById('status-text').innerText = "Initializing Simulator...";

        setTimeout(async () => {
            await this.updateDashboard();
            this.startAutoPlay();
        }, 100);
    }

    startAutoPlay() {
        const btn = document.getElementById('btn-autoplay');
        if (this.autoPlayTimer) return;

        btn.innerText = "Stop Auto ⏹️";
        btn.style.background = "#fee2e2";
        btn.style.borderColor = "#ef4444";

        this.triggerSimulatorNext();
        this.autoPlayTimer = setInterval(() => this.triggerSimulatorNext(), 2000);
    }

    stopAutoPlay() {
        const btn = document.getElementById('btn-autoplay');
        if (this.autoPlayTimer) {
            clearInterval(this.autoPlayTimer);
            this.autoPlayTimer = null;
        }
        btn.innerText = "Auto Play ▶️";
        btn.style.background = "";
        btn.style.borderColor = "";
    }

    toggleAutoPlay() {
        if (this.autoPlayTimer) {
            this.stopAutoPlay();
        } else {
            this.startAutoPlay();
        }
    }

    async updateDashboard() {
        const sessionId = this.sessionManager.sessionId;

        try {
            const response = await fetch(`/api/history?session_id=${sessionId}`);
            const data = await response.json();

            // 更新狀態
            const statusText = document.getElementById('status-text');
            if (statusText) {
                statusText.innerText = data.status || "Ready";
            }

            // 更新圖表
            if (data.chart_data) {
                this.chartsManager.updateFeatureChart(data.chart_data);
                this.chartsManager.updateRewardChart(data.chart_data);
                this.chartsManager.updateActionChart(data.chart_data);
                this.chartsManager.updateQValueChart(data.chart_data);
            }

            // 更新推理日誌
            if (data.logs && data.logs.length > 0) {
                this._updateReasoningLogs(data.logs);
            }

            // 更新統計數據
            if (data.stats) {
                this._updateStats(data.stats);
            }

        } catch (err) {
            console.error('Update dashboard error:', err);
        }
    }

    _updateReasoningLogs(logs) {
        const logContainer = document.getElementById('reasoning-logs');
        const emptyMsg = document.getElementById('log-empty-msg');
        if (emptyMsg) emptyMsg.remove();

        logs.forEach(log => {
            if (log.timestamp > this.lastLogTimestamp) {
                const logDiv = document.createElement('div');
                logDiv.className = 'log-entry';
                logDiv.innerHTML = `
                    <div class="log-time">${new Date(log.timestamp).toLocaleTimeString()}</div>
                    <div class="log-message">${log.message}</div>
                `;
                logContainer.appendChild(logDiv);
                this.lastLogTimestamp = log.timestamp;
            }
        });

        // 滾動到底部
        logContainer.scrollTop = logContainer.scrollHeight;
    }

    _updateStats(stats) {
        // 更新統計數據顯示
        const statsElements = {
            'total-steps': stats.total_steps,
            'avg-reward': stats.avg_reward,
            'success-rate': stats.success_rate
        };

        Object.entries(statsElements).forEach(([id, value]) => {
            const elem = document.getElementById(id);
            if (elem) elem.textContent = value;
        });
    }

    // === Dashboard Controls ===
    async initDashboardControls() {
        console.log("Initializing Dashboard Controls...");

        // 綁定下拉選單的事件監聽器
        const fileSelect = document.getElementById('dashboard-file-select');
        const modelSelect = document.getElementById('dashboard-model-select');

        console.log('📂 File select element:', fileSelect ? '找到' : '未找到');
        console.log('🤖 Model select element:', modelSelect ? '找到' : '未找到');

        if (fileSelect) {
            fileSelect.addEventListener('change', (e) => {
                const filename = e.target.value;
                console.log('🔔 檔案下拉選單變更事件觸發！選擇的檔案:', filename);
                if (filename) {
                    console.log('📂 準備調用 loadSimulationFile...');
                    this.loadSimulationFile(filename);
                } else {
                    console.log('⚠️ 檔案名稱為空，不執行載入');
                }
            });
            console.log('✅ 檔案選單事件監聽器已綁定');
        } else {
            console.error('❌ 找不到 dashboard-file-select 元素！');
        }

        if (modelSelect) {
            modelSelect.addEventListener('change', (e) => {
                const modelPath = e.target.value;
                console.log('🔔 模型下拉選單變更事件觸發！選擇的模型:', modelPath);
                if (modelPath) {
                    console.log('🤖 準備調用 loadModel...');
                    this.loadModel(modelPath);
                } else {
                    console.log('⚠️ 模型路徑為空，不執行載入');
                }
            });
            console.log('✅ 模型選單事件監聽器已綁定');
        } else {
            console.error('❌ 找不到 dashboard-model-select 元素！');
        }

        console.log('✅ Event listeners attached');

        await this.fetchFileList();
        await this.fetchModelList();
    }

    async fetchFileList() {
        try {
            const sessionId = this.sessionManager.sessionId;
            const res = await fetch(`/api/list_files?session_id=${sessionId}`);
            const data = await res.json();
            const select = document.getElementById('dashboard-file-select');

            if (!select) return;

            select.innerHTML = '<option value="">選擇模擬檔案...</option>';

            if (data.files && data.files.length > 0) {
                data.files.forEach(f => {
                    const option = document.createElement('option');
                    option.value = f.filename;
                    option.text = f.filename;
                    select.appendChild(option);
                });
            } else {
                select.innerHTML = '<option value="">無可用檔案</option>';
            }
        } catch (e) {
            console.error("Fetch file list failed:", e);
        }
    }

    async fetchModelList() {
        try {
            const sessionId = this.sessionManager.sessionId;
            const res = await fetch(`/api/simulator/models?session_id=${sessionId}`);
            const models = await res.json();
            const select = document.getElementById('dashboard-model-select');

            if (!select) return;

            select.innerHTML = '<option value="">選擇模型版本...</option>';

            if (models && models.length > 0) {
                models.forEach(m => {
                    const option = document.createElement('option');
                    // 正確處理物件格式（與 Universal Loader 一致）
                    if (typeof m === 'object' && m !== null) {
                        option.value = m.id;
                        option.text = m.name;
                    } else {
                        // 向後相容舊格式
                        option.value = m;
                        option.text = m.length > 20 ? m.substring(0, 20) + '...' : m;
                    }
                    select.appendChild(option);
                });
            } else {
                select.innerHTML = '<option value="">無可用模型</option>';
            }
        } catch (e) {
            console.error("Fetch model list failed:", e);
        }
    }

    async loadSimulationFile(filename) {
        console.log('📂 === loadSimulationFile 被調用 ===');
        console.log('📂 檔案名稱:', filename);
        console.log('📂 Session ID:', this.sessionManager.sessionId);

        if (!filename) {
            console.warn('⚠️ 檔案名稱為空，中止載入');
            return;
        }

        try {
            console.log('📂 發送 API 請求到 /api/simulator/load_file...');

            const response = await fetch('/api/simulator/load_file', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    filename: filename,
                    session_id: this.sessionManager.sessionId
                })
            });

            console.log('📂 API 回應狀態:', response.status, response.statusText);

            if (!response.ok) {
                const errorText = await response.text();
                console.error('❌ API 回應錯誤:', errorText);
                alert(`❌ 檔案載入失敗 (${response.status})\n${errorText}`);
                return;
            }

            const result = await response.json();
            console.log('📂 API 回應結果:', result);

            if (result.status === 'success') {
                const message = `✅ 已載入模擬檔案:\n${filename}\n(${result.rows} 筆數據)`;
                console.log('✅ 檔案載入成功！');
                alert(message);
            } else {
                const errorMsg = `❌ 載入失敗: ${result.message}`;
                console.error('❌ 載入失敗:', result.message);
                alert(errorMsg);
            }
        } catch (e) {
            const errorMsg = `❌ 載入錯誤: ${e.message}`;
            console.error('❌ Exception:', e);
            alert(errorMsg);
        }

        console.log('📂 === loadSimulationFile 結束 ===');
    }

    async loadModel(modelPath) {
        if (!modelPath) return;
        try {
            const response = await fetch('/api/model/load', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    model_path: modelPath,
                    session_id: this.sessionManager.sessionId
                })
            });
            const result = await response.json();
            if (result.status === 'success') {
                alert("模型載入成功！請點擊 Run Simulation 或 Auto Play 開始。");
                // Update status text
                document.getElementById('status-text').innerText = "Model Ready";
            } else {
                alert("模型載入失敗: " + (result.message || "未知錯誤"));
            }
        } catch (e) {
            alert("模型載入錯誤: " + e.message);
        }
    }

    // === UI Interaction Methods ===
    openFileSelector() {
        const modal = document.getElementById('fileSelectorModal');
        if (modal) {
            modal.classList.add('show');
            this.loadFileSelectorList();
        }
    }

    closeFileSelector() {
        const modal = document.getElementById('fileSelectorModal');
        if (modal) modal.classList.remove('show');
    }

    async loadFileSelectorList() {
        const listDiv = document.getElementById('file-selector-list');
        listDiv.innerHTML = '<div style="text-align:center; color:#94a3b8;">載入中...</div>';

        try {
            // Use FileManager to get list
            if (!this.sessionManager.sessionId) return;

            const res = await fetch(`/api/list_files?session_id=${this.sessionManager.sessionId}`);
            const data = await res.json();

            if (!data.files || data.files.length === 0) {
                listDiv.innerHTML = '<div style="text-align:center; color:#94a3b8;">無可用檔案</div>';
                return;
            }

            let html = '';
            data.files.forEach(f => {
                html += `
                    <div class="file-select-item" onclick="window.Sigma2.dashboard.selectFileItem(this, '${f.filename}')" 
                         style="padding: 10px; border-bottom: 1px solid #f1f5f9; cursor: pointer; transition: background 0.2s;">
                        <div style="font-weight: bold; color: #334155;">${f.filename}</div>
                        <div style="font-size: 12px; color: #94a3b8;">${f.uploaded_at}</div>
                    </div>
                `;
            });
            listDiv.innerHTML = html;

        } catch (e) {
            listDiv.innerHTML = `<div style="color:red;">載入錯誤: ${e.message}</div>`;
        }
    }

    selectFileItem(elem, filename) {
        // Clear previous selection
        document.querySelectorAll('.file-select-item').forEach(el => el.style.background = '');
        elem.style.background = '#f1f5f9';

        this.selectedFileForAnalysis = filename;
        const btn = document.getElementById('btn-confirm-file');
        if (btn) {
            btn.disabled = false;
            btn.style.opacity = '1';
            btn.style.cursor = 'pointer';
        }
    }

    confirmFileSelection() {
        if (this.selectedFileForAnalysis) {
            // Trigger Analysis
            if (window.Sigma2.analysis) {
                window.Sigma2.analysis.analyzeFile(this.selectedFileForAnalysis);
            }
            this.closeFileSelector();
        }
    }
    async refreshLists() {
        console.log("Refreshing lists...");
        await this.fetchFileList();
        await this.fetchModelList();
    }
}

// 掛載到 window 供 HTML 調用
window.triggerSimulatorNext = function () {
    if (window.Sigma2 && window.Sigma2.dashboard) {
        window.Sigma2.dashboard.triggerSimulatorNext();
    } else {
        console.error('Dashboard not initialized yet');
    }
};
window.runFullSimulation = function () {
    if (window.Sigma2 && window.Sigma2.dashboard) {
        window.Sigma2.dashboard.runFullSimulation();
    } else {
        console.error('Dashboard not initialized yet');
    }
};
window.toggleAutoPlay = function () {
    if (window.Sigma2 && window.Sigma2.dashboard) {
        window.Sigma2.dashboard.toggleAutoPlay();
    } else {
        console.error('Dashboard not initialized yet');
    }
};
window.loadSimulationFile = function (val) {
    if (window.Sigma2 && window.Sigma2.dashboard) {
        window.Sigma2.dashboard.loadSimulationFile(val);
    } else {
        console.error('Dashboard not initialized yet, will retry...');
        // 延遲重試
        setTimeout(() => {
            if (window.Sigma2 && window.Sigma2.dashboard) {
                window.Sigma2.dashboard.loadSimulationFile(val);
            } else {
                alert('系統初始化中，請稍後再試');
            }
        }, 500);
    }
}
window.loadModel = function (val) {
    if (window.Sigma2 && window.Sigma2.dashboard) {
        window.Sigma2.dashboard.loadModel(val);
    } else {
        console.error('Dashboard not initialized yet, will retry...');
        // 延遲重試
        setTimeout(() => {
            if (window.Sigma2 && window.Sigma2.dashboard) {
                window.Sigma2.dashboard.loadModel(val);
            } else {
                alert('系統初始化中，請稍後再試');
            }
        }, 500);
    }
}
window.refreshDashboardLists = function () {
    if (window.Sigma2 && window.Sigma2.dashboard) {
        window.Sigma2.dashboard.refreshLists();
    } else {
        console.error('Dashboard not initialized yet');
    }
}
