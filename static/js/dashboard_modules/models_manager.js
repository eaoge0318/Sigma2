
// =========================
// models_manager.js - Model Registry & Logs
// =========================
import { DOM, API } from './utils.js';

const MODEL_REGISTRY_PAGE_SIZE = 9;
let modelRegistryCurrentPage = 1;
let logAutoRefreshTimer = null;

export async function loadModelRegistry() {
    const tbody = DOM.get('model-list-body');
    const countText = DOM.get('model-count-text');
    if (!tbody) return;

    try {
        const models = await API.get('/api/analysis/list_models');

        if (countText) countText.innerText = models.length;
        tbody.innerHTML = '';

        if (models.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8" style="text-align: center; padding: 50px; color: #94a3b8; font-style: italic;">目前模型庫中尚未儲存任何模型</td></tr>';
            const paginationContainer = DOM.get('model-registry-pagination');
            if (paginationContainer) paginationContainer.innerHTML = '';
            return;
        }

        // --- Pagination Logic ---
        const totalItems = models.length;
        const totalPages = Math.ceil(totalItems / MODEL_REGISTRY_PAGE_SIZE);

        if (modelRegistryCurrentPage > totalPages) {
            modelRegistryCurrentPage = Math.max(1, totalPages);
        }

        const startIdx = (modelRegistryCurrentPage - 1) * MODEL_REGISTRY_PAGE_SIZE;
        const endIdx = startIdx + MODEL_REGISTRY_PAGE_SIZE;
        const displayedModels = models.slice(startIdx, endIdx);

        displayedModels.forEach((m) => {
            const tr = document.createElement('tr');
            tr.style.borderBottom = '1px solid #f1f5f9';
            tr.style.transition = 'background 0.2s';
            tr.onmouseover = () => tr.style.background = '#f8fafc';
            tr.onmouseout = () => tr.style.background = 'transparent';

            const pillStyle = "padding: 4px 14px; border-radius: 20px; font-size: 11px; font-weight: 700; color: #fff; display: inline-block; min-width: 80px; text-align: center; cursor: pointer;";
            const tagStyle = "padding: 2px 10px; border: 1px solid #3b82f6; border-radius: 12px; color: #3b82f6; font-size: 11px; font-weight: 600; background: rgba(59, 130, 246, 0.05);";
            const actionBtnStyle = "padding: 6px 10px; border: 1px solid #3b82f6; border-radius: 6px; background: #fff; color: #3b82f6; font-size: 11px; font-weight: 600; cursor: pointer; display: flex; align-items: center; gap: 4px; transition: all 0.2s;";

            const displayName = m.modelName || m.model_name || m.name || '未命名項目';
            const displayTarget = m.target || m.goal || '-';
            const mType = m.missionType || m.type;

            const displayStrategy = m.strategyAlgo && m.strategyAlgo !== '-' ? m.strategyAlgo : (mType === 'rl' ? m.algorithm : '-');
            const displayPred = m.predAlgo && m.pred_algo !== '-' ? m.predAlgo : (mType === 'supervised' ? m.algorithm : '-');

            let infoText = `模型名稱：${displayName}\n`;
            infoText += `Job ID：${m.job_id}\n`;
            infoText += `任務類型：${mType === 'rl' ? '最佳策略 (RL)' : '數據預測 (ML)'}\n`;
            infoText += `目標標的：${displayTarget}\n`;
            if (m.actions && m.actions.length > 0) infoText += `控制參數 (Actions)：${m.actions.join(', ')}\n`;
            if (m.states && m.states.length > 0) infoText += `環境狀態 (States)：${m.states.join(', ')}\n`;
            if (m.features && m.features.length > 0) infoText += `預測特徵 (Features)：${m.features.join(', ')}\n`;

            const isTraining = m.status === 'training';

            tr.innerHTML = `
                <td style="padding: 12px 15px; font-weight: 500; color: #1e293b; font-size: 14px;">${displayName}</td>
                <td style="padding: 12px 15px;">
                    <span title="點擊查看訓練日誌" 
                          onclick="viewTrainingLog('${m.job_id}', '${displayName}')"
                          style="${pillStyle} ${m.status === 'completed' ? 'background: #2e7d32;' : (m.status === 'failed' ? 'background: #d32f2f;' : 'background: #1976d2;')}">
                        ${m.status === 'completed' ? '訓練完成' : (m.status === 'failed' ? '任務失敗/停止' : '訓練中')}
                    </span>
                </td>
                <td style="padding: 12px 15px;">
                    <span style="${tagStyle}">${displayTarget}</span>
                </td>
                <td style="padding: 12px 15px;">
                    <span style="${tagStyle}">${displayStrategy}</span>
                </td>
                <td style="padding: 12px 15px;">
                    <span style="${tagStyle}">${displayPred}</span>
                </td>
                <td style="padding: 12px 15px; color: #1e293b; font-size: 14px;">${m.rows || '-'}</td>
                <td style="padding: 12px 15px; color: #64748b; font-size: 14px;">${m.created_at || '-'}</td>
                <td style="padding: 12px 15px;">
                    <div style="display: flex; gap: 6px; align-items: center; justify-content: center;">
                        <button style="${actionBtnStyle.replace(/#3b82f6/g, '#64748b')}" 
                                onclick="alert('${infoText.replace(/\n/g, '\\n')}')">資訊</button>
                        ${isTraining ? `
                            <button style="padding: 6px 10px; border: 1px solid #f97316; border-radius: 6px; background: #fff; color: #f97316; font-size: 11px; font-weight: 600; cursor: pointer; transition: all 0.2s;" 
                                    onmouseover="this.style.background='#fff7ed'" onmouseout="this.style.background='#fff'"
                                    onclick="stopModel('${m.job_id}', '${displayName}')">停止</button>
                        ` : ''}
                        <button style="padding: 6px 10px; border: 1px solid #ef4444; border-radius: 6px; background: #fff; color: #ef4444; font-size: 11px; font-weight: 600; cursor: pointer; transition: all 0.2s;" 
                                onmouseover="this.style.background='#fef2f2'" onmouseout="this.style.background='#fff'"
                                onclick="deleteModel('${m.job_id}', '${displayName}')">刪除</button>
                    </div>
                </td>
            `;
            tbody.appendChild(tr);
        });

        renderModelRegistryPagination(totalPages);

    } catch (err) {
        console.error('Failed to sync model registry:', err);
    }
}

function renderModelRegistryPagination(totalPages) {
    const container = DOM.get('model-registry-pagination');
    if (!container) return;

    if (totalPages <= 1) {
        container.innerHTML = '';
        return;
    }

    const btnStyle = "padding: 6px 14px; border: 1px solid #e2e8f0; border-radius: 6px; background: #fff; color: #64748b; font-size: 12px; font-weight: 600; cursor: pointer; transition: all 0.2s;";
    let html = '';

    html += `<button style="${btnStyle}" ${modelRegistryCurrentPage === 1 ? 'disabled style="opacity:0.5; cursor:not-allowed;"' : `onclick="changeModelRegistryPage(${modelRegistryCurrentPage - 1})"`}>上一頁</button>`;
    html += `<span style="display: flex; align-items: center; gap: 5px; color: #64748b; font-size: 12px; margin: 0 10px;">第 ${modelRegistryCurrentPage} / ${totalPages} 頁</span>`;
    html += `<button style="${btnStyle}" ${modelRegistryCurrentPage === totalPages ? 'disabled style="opacity:0.5; cursor:not-allowed;"' : `onclick="changeModelRegistryPage(${modelRegistryCurrentPage + 1})"`}>下一頁</button>`;

    container.innerHTML = html;
}

export function changeModelRegistryPage(newPage) {
    modelRegistryCurrentPage = newPage;
    loadModelRegistry();
}

export async function deleteModel(jobId, modelName) {
    if (!jobId) return;
    if (!confirm(`確定要刪除模型「${modelName}」及其訓練日誌嗎？\n此動作無法還原。`)) return;

    try {
        const result = await API.delete(`/api/analysis/delete_model/${jobId}`);
        if (result.status === 'success') {
            loadModelRegistry();
            if (window.Swal) Swal.fire({ icon: 'success', title: '刪除成功', text: result.message, timer: 1500, showConfirmButton: false });
            else alert('✅ ' + result.message);
        } else {
            alert('❌ 刪除失敗: ' + result.message);
        }
    } catch (err) {
        alert('API 請求異常: ' + err.message);
    }
}

export async function stopModel(jobId, modelName) {
    if (!jobId) return;
    if (!confirm(`確定要強制停止模型「${modelName}」的訓練進程嗎？`)) return;

    try {
        const result = await API.post(`/api/analysis/stop_model/${jobId}`);
        if (result.status === 'success') {
            loadModelRegistry();
            if (window.Swal) Swal.fire({ icon: 'success', title: '已停止', text: result.message, timer: 1500, showConfirmButton: false });
            else alert('✅ ' + result.message);
        } else {
            alert('❌ 停止失敗: ' + result.message);
        }
    } catch (err) {
        alert('API 請求異常: ' + err.message);
    }
}

export function closeLogViewer() {
    if (logAutoRefreshTimer) {
        clearInterval(logAutoRefreshTimer);
        logAutoRefreshTimer = null;
    }
    const modal = DOM.get('log-viewer-modal');
    if (modal) modal.remove();
}

export function toggleLogAutoRefresh(jobId, modelName, checked) {
    if (logAutoRefreshTimer) {
        clearInterval(logAutoRefreshTimer);
        logAutoRefreshTimer = null;
    }
    if (checked) {
        logAutoRefreshTimer = setInterval(() => {
            viewTrainingLog(jobId, modelName);
        }, 3000);
    }
}

export async function viewTrainingLog(jobId, modelName) {
    if (!jobId) { alert('找不到任務代碼 (Job ID)'); return; }

    const modalId = 'log-viewer-modal';
    let modal = DOM.get(modalId);
    let pre = DOM.get('log-viewer-pre');

    try {
        // Use raw fetch for text content since API helper expects JSON primarily, 
        // though API helper can verify status. Let's use fetch manually for text.
        // Or improve API helper to handle text. For now manual fetch.
        const res = await fetch(`/api/analysis/get_log/${jobId}?session_id=${window.SESSION_ID}`);
        const logContent = await res.text();
        const cleanLog = logContent.startsWith('"') && logContent.endsWith('"') ? logContent.slice(1, -1).replace(/\\n/g, '\n').replace(/\\r/g, '') : logContent;

        if (modal && pre) {
            pre.innerText = cleanLog || "正在讀取日誌內容中...";
            pre.scrollTop = pre.scrollHeight;
            return;
        }

        modal = document.createElement('div');
        modal.id = modalId;
        modal.className = "log-modal-overlay";
        modal.style = "position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.8); z-index:99999; display:flex; align-items:center; justify-content:center; padding:20px; animation: fadeIn 0.15s ease;";
        modal.innerHTML = `
            <div style="background:#fff; width:95%; max-width:1100px; height:85vh; border-radius:16px; display:flex; flex-direction:column; overflow:hidden; box-shadow:0 25px 50px -12px rgba(0,0,0,0.5);">
                <div style="padding:15px 25px; background:#1e293b; color:#fff; display:flex; justify-content:space-between; align-items:center;">
                    <div style="display:flex; align-items:center; gap:10px;">
                        <span style="font-size:20px;">📜</span>
                        <div>
                            <div style="font-weight:800; font-size:15px;">訓練日誌監控</div>
                            <div style="font-size:11px; color:#94a3b8;">${modelName} - ${jobId}</div>
                        </div>
                    </div>
                    <div style="display:flex; gap:15px; align-items:center;">
                        <label style="display:flex; align-items:center; gap:8px; font-size:12px; color:#94a3b8; cursor:pointer; background:rgba(255,255,255,0.05); padding:5px 10px; border-radius:6px;">
                            <input type="checkbox" onchange="toggleLogAutoRefresh('${jobId}', '${modelName}', this.checked)" ${logAutoRefreshTimer ? 'checked' : ''}>
                            自動重新整理
                        </label>
                        <button onclick="viewTrainingLog('${jobId}', '${modelName}')" 
                                class="log-refresh-btn"
                                style="background:rgba(255,255,255,0.1); border:1px solid rgba(255,255,255,0.2); color:#fff; padding:5px 12px; border-radius:6px; font-size:12px; cursor:pointer; transition:all 0.2s;">
                            🔄 重新整理
                        </button>
                        <button onclick="closeLogViewer()" style="background:transparent; border:none; color:#fff; font-size:24px; cursor:pointer; line-height:1;">&times;</button>
                    </div>
                </div>
                <pre id="log-viewer-pre" style="flex:1; padding:25px; background:#0f172a; color:#38bdf8; margin:0; overflow:auto; font-family:'Roboto Mono', 'Fira Code', monospace; font-size:13px; line-height:1.6; white-space:pre-wrap; word-break:break-all;">${cleanLog || "正在讀取日誌..."}</pre>
                <div style="padding:15px 25px; background:#f8fafc; border-top:1px solid #e2e8f0; display:flex; justify-content:space-between; align-items:center;">
                    <div style="font-size:12px; color:#64748b;">💡 提示：此日誌僅顯示最後 2000 行，若需完整內容請至伺服器讀取。</div>
                    <button onclick="closeLogViewer()" style="padding:8px 25px; background:#3b82f6; color:#fff; border:none; border-radius:8px; font-weight:700; cursor:pointer; transition:all 0.2s;" onmouseover="this.style.background='#2563eb'" onmouseout="this.style.background='#3b82f6'">關閉視窗</button>
                </div>
            </div>
        `;
        document.body.appendChild(modal);

        const newPre = DOM.get('log-viewer-pre');
        if (newPre) newPre.scrollTop = newPre.scrollHeight;

    } catch (err) {
        if (modal) console.error('Refresh log failed:', err);
        else alert('獲取日誌失敗: ' + err.message);
    }
}
