/* Dashboard JavaScript */

window.charts = {}; // Use window property to ensure global access
const WINDOW_SIZE = 40;
let lastLogTimestamp = 0;
let autoPlayTimer = null;
let latestImportantFactors = []; // Store AI-suggested factors globally

// --- Session ID Management (Isolation) ---
function getSessionId() {
    let sid = sessionStorage.getItem("sigma2_session_id");
    if (!sid) {
        // Generate simple UUID-like string
        sid = 'sess-' + Math.random().toString(36).substr(2, 9) + Date.now().toString(36);
        sessionStorage.setItem("sigma2_session_id", sid);
    }
    return sid;
}
const SESSION_ID = getSessionId();
console.log("Current Session ID:", SESSION_ID);

async function triggerSimulatorNext() {
    try {
        // Pass session_id in body
        const response = await fetch('/api/simulator/next', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: SESSION_ID })
        });
        const data = await response.json();
        if (data.status === 'EOF') {
            alert(data.message);
            stopAutoPlay();
        } else {
            updateDashboard();
        }
    } catch (err) { console.error("Simulator Error:", err); }
}

async function runFullSimulation() {
    stopAutoPlay(); // 先停止現有的
    // Pass session_id
    await fetch('/api/clear', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: SESSION_ID })
    });

    // 清空前端顯示狀態
    lastLogTimestamp = 0;
    document.getElementById('reasoning-logs').innerHTML = '<div id="log-empty-msg" style="color: #94a3b8; text-align: center; padding: 30px;">等待即時數據流中...</div>';
    document.getElementById('ai-report-content').innerHTML = '<div class="ai-bubble chat-bubble">👋 模擬已重設，正在重新讀取數據集...</div>';
    document.getElementById('status-text').innerText = "Initializing Simulator...";

    // 由於核心數據已清空，調用一次 updateDashboard 來重置圖表
    setTimeout(async () => {
        await updateDashboard();
        startAutoPlay();
    }, 100);
}

function startAutoPlay() {
    const btn = document.getElementById('btn-autoplay');
    if (autoPlayTimer) return;
    btn.innerText = "Stop Auto ⏹️";
    btn.style.background = "#fee2e2";
    btn.style.borderColor = "#ef4444";
    triggerSimulatorNext(); // 立即跑第一筆
    autoPlayTimer = setInterval(triggerSimulatorNext, 2000);
}

function toggleAutoPlay() {
    if (autoPlayTimer) {
        stopAutoPlay();
    } else {
        startAutoPlay();
    }
}

function stopAutoPlay() {
    const btn = document.getElementById('btn-autoplay');
    if (autoPlayTimer) {
        clearInterval(autoPlayTimer);
        autoPlayTimer = null;
    }
    btn.innerText = "Auto Play ▶️";
    btn.style.background = "";
    btn.style.borderColor = "";
}

function toggleAssistant() {
    const win = document.getElementById('ai-assistant-window');
    const fab = document.getElementById('assistant-trigger');
    const icon = document.getElementById('fab-icon');

    const isOpen = win.classList.contains('active');

    if (!isOpen) {
        // Open window
        win.style.display = 'flex';
        // Delay adding active class to trigger CSS transition
        setTimeout(() => {
            win.classList.add('active');
            fab.classList.add('active');
            if (icon) icon.innerText = '×';
        }, 10);
    } else {
        // Close window
        win.classList.remove('active');
        fab.classList.remove('active');
        if (icon) icon.innerText = '🤖';
        // Wait for transition to finish before hiding
        setTimeout(() => {
            if (!win.classList.contains('active')) {
                win.style.display = 'none';
            }
        }, 300);
    }
}

function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    const charts = Object.values(window.charts || {});

    if (sidebar.classList.contains('collapsed')) {
        sidebar.classList.remove('collapsed');
        document.body.classList.remove('sidebar-collapsed');
    } else {
        sidebar.classList.add('collapsed');
        document.body.classList.add('sidebar-collapsed');
    }

    // Trigger chart resize after transition (300ms)
    setTimeout(() => {
        charts.forEach(c => c.resize());
    }, 350);
}

function toggleExpand() {
    const win = document.getElementById('ai-assistant-window');
    win.classList.toggle('expanded');
}

document.addEventListener('DOMContentLoaded', () => {
    const chatBody = document.getElementById('ai-report-content');
    const chatInput = document.getElementById('chat-input');

    if (chatBody) {
        chatBody.addEventListener('dragover', (e) => {
            e.preventDefault();
            chatBody.classList.add('drag-over');
        });

        chatBody.addEventListener('dragleave', () => {
            chatBody.classList.remove('drag-over');
        });

        chatBody.addEventListener('drop', (e) => {
            e.preventDefault();
            chatBody.classList.remove('drag-over');
            if (e.dataTransfer.files.length > 0) {
                processFiles(e.dataTransfer.files);
            }
        });
    }

    if (chatInput) {
        // 新增：貼上圖片功能
        chatInput.addEventListener('paste', (e) => {
            const items = (e.clipboardData || e.originalEvent.clipboardData).items;
            const files = [];
            for (let i = 0; i < items.length; i++) {
                if (items[i].kind === 'file') {
                    files.push(items[i].getAsFile());
                }
            }
            if (files.length > 0) {
                processFiles(files);
            }
        });
    }

    // Auto refresh file list if we are in file view (or just always load it)
    loadFileList();

    const dropzone = document.getElementById('upload-dropzone');
    if (dropzone) {
        dropzone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropzone.classList.add('drag-over');
        });
        dropzone.addEventListener('dragleave', () => {
            dropzone.classList.remove('drag-over');
        });
        dropzone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropzone.classList.remove('drag-over');
            if (e.dataTransfer.files.length > 0) {
                const file = e.dataTransfer.files[0];
                if (file.name.toLowerCase().endsWith('.csv') || file.name.toLowerCase().endsWith('.xml')) {
                    uploadFile(file);
                } else {
                    const statusDiv = document.getElementById('upload-status');
                    statusDiv.innerText = "❌ 僅支援 CSV 或 XML 格式檔案";
                    statusDiv.style.color = '#ef4444';
                }
            }
        });
    }


    // Initialize View
    // Check URL hash or default to 'files' as per HTML default active class
    // But user wants dashboard likely? Let's respect the HTML 'active' class which is on 'files'
    // Actually, let's force a switch to ensure state consistency
    if (document.getElementById('nav-dashboard').classList.contains('active')) {
        switchView('dashboard');
    } else {
        switchView('files');
    }
});

// --- View Switching Logic ---
function switchView(viewName) {
    // Update Nav State
    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
    document.getElementById('nav-' + viewName).classList.add('active');

    // Toggle Views
    try {
        if (viewName === 'dashboard') {
            document.getElementById('view-dashboard').style.display = 'block';
            document.getElementById('view-files').style.display = 'none';
            document.getElementById('view-analysis').style.display = 'none';

            // Trigger chart resize after layout change
            setTimeout(() => {
                try {
                    if (window.charts) {
                        Object.values(window.charts).forEach(c => {
                            if (c && typeof c.resize === 'function') c.resize();
                        });
                    }
                } catch (e) {
                    console.warn("Chart resize failed:", e);
                }
            }, 50);

        } else if (viewName === 'analysis') {
            document.getElementById('view-dashboard').style.display = 'none';
            document.getElementById('view-files').style.display = 'none';
            document.getElementById('view-analysis').style.display = 'block';
        } else {
            document.getElementById('view-dashboard').style.display = 'none';
            document.getElementById('view-files').style.display = 'block';
            document.getElementById('view-analysis').style.display = 'none';
            loadFileList();
        }
    } catch (err) {
        console.error("switchView failed:", err);
        // Fallback: Try to show dashboard at least
        if (viewName === 'dashboard') document.getElementById('view-dashboard').style.display = 'block';
    }
}

// --- File Manager Logic ---
function handleMainFileUpload(input) {
    if (input.files.length > 0) {
        uploadFile(input.files[0]);
    }
}

async function uploadFile(file) {
    const statusDiv = document.getElementById('upload-status');
    statusDiv.innerText = `⏳ 正在上傳 ${file.name}...`;
    statusDiv.style.color = '#3b82f6';

    const formData = new FormData();
    formData.append('file', file);

    try {
        const res = await fetch('/api/upload_file', {
            method: 'POST',
            body: formData
        });
        const data = await res.json();

        if (res.ok) {
            statusDiv.innerText = `✅ ${data.message}`;
            statusDiv.style.color = '#22c55e';
            loadFileList(); // Refresh list
        } else {
            statusDiv.innerText = `❌ 上傳失敗: ${data.detail}`;
            statusDiv.style.color = '#ef4444';
        }
    } catch (err) {
        statusDiv.innerText = `❌ 上傳錯誤: ${err.message}`;
        statusDiv.style.color = '#ef4444';
    }
}

// --- Data Management Functions ---
async function deleteFile(filename) {
    if (!confirm(`確定要刪除 ${filename} 嗎？`)) return;

    try {
        const res = await fetch(`/api/delete_file/${filename}`, { method: 'DELETE' });
        const data = await res.json();
        if (res.ok) {
            loadFileList(); // Refresh
        } else {
            alert(`刪除失敗: ${data.detail}`);
        }
    } catch (err) {
        alert(`錯誤: ${err.message}`);
    }
}

async function viewFile(filename) {
    try {
        const res = await fetch(`/api/view_file/${filename}`);
        const data = await res.json();
        if (res.ok) {
            document.getElementById('viewDataContent').innerText = data.content;
            document.getElementById('viewDataTitle').innerText = `預覽: ${filename}`;
            document.getElementById('viewDataModal').classList.add('show');
        } else {
            alert(`無法預覽: ${data.detail}`);
        }
    } catch (err) {
        alert(`錯誤: ${err.message}`);
    }
}

function closeViewModal() {
    document.getElementById('viewDataModal').classList.remove('show');
}

async function trainModel(filename) {
    try {
        alert(`🚀 正在對 ${filename} 啟動訓練任務...\n(Mock 模式)`);
        const res = await fetch('/api/train_model', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filename: filename })
        });
        const data = await res.json();
        if (res.ok) {
            console.log("Training started:", data);
        }
    } catch (err) {
        console.error(err);
    }
}

async function loadFileList() {
    const tbody = document.getElementById('file-list-body');
    try {
        const res = await fetch('/api/list_files');
        const data = await res.json();

        tbody.innerHTML = '';
        if (data.files.length === 0) {
            tbody.innerHTML = '<tr><td colspan="2" style="text-align: center; color: #94a3b8;">尚無已上傳檔案</td></tr>';
            return;
        }

        data.files.forEach(f => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td style="font-weight: bold;">${f.filename}</td>
                <td style="color: #64748b;">${(f.size / 1024).toFixed(2)} KB</td>
                <td style="color: #64748b;">${f.uploaded_at}</td>
                <td>
                    <div style="display: flex; align-items: center;">
                        <button onclick="analyzeFile('${f.filename}')" class="action-btn btn-view">分析</button>
                        <button onclick="trainModel('${f.filename}')" class="action-btn btn-train">訓練</button>
                        <button onclick="deleteFile('${f.filename}')" class="action-btn btn-delete">刪除</button>
                    </div>
                </td>
            `;
            tbody.appendChild(tr);
        });
    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="4" style="color: red;">無法載入列表: ${err.message}</td></tr>`;
    }
}


// Modal Logic
function openUploadModal() {
    document.getElementById('uploadModal').classList.add('show');
    document.getElementById('upload-status').innerText = ''; // Clear status
}

function closeUploadModal() {
    document.getElementById('uploadModal').classList.remove('show');
}

// Close modal when clicking outside
window.onclick = function (event) {
    const uploadModal = document.getElementById('uploadModal');
    const viewModal = document.getElementById('viewDataModal');
    const selectionModal = document.getElementById('selection-modal'); // Added for new modal
    if (event.target == uploadModal) {
        closeUploadModal();
    }
    if (event.target == viewModal) {
        closeViewModal();
    }
    if (event.target == document.getElementById('fileSelectorModal')) {
        closeFileSelector();
    }
    if (event.target == selectionModal) { // Added for new modal
        clearChartSelection();
    }
    if (event.target == document.getElementById('advanced-param-modal')) {
        closeAdvancedModal();
    }
}

// --- File Selector Logic ---
let selectedAnalysisFilename = null;

async function openFileSelector() {
    const res = await fetch('/api/list_files');
    const data = await res.json();
    const list = document.getElementById('file-selector-list');
    list.innerHTML = '';
    selectedAnalysisFilename = null; // Reset selection

    const confirmBtn = document.getElementById('btn-confirm-file');
    if (confirmBtn) {
        confirmBtn.disabled = true;
        confirmBtn.style.opacity = '0.5';
        confirmBtn.style.cursor = 'not-allowed';
    }

    if (data.files.length === 0) {
        list.innerHTML = '<div style="color: #94a3b8; text-align: center; padding: 20px;">尚無檔案，請先上傳</div>';
    } else {
        // Sort by uploaded_at desc and take top 5
        data.files.sort((a, b) => {
            return b.uploaded_at.localeCompare(a.uploaded_at);
        });
        const recentFiles = data.files.slice(0, 5);

        recentFiles.forEach(f => {
            const item = document.createElement('div');
            item.className = 'file-item';
            item.style.padding = '12px 10px';
            item.style.borderBottom = '1px solid #f8fafc';
            item.style.cursor = 'pointer';
            item.style.display = 'flex';
            item.style.justifyContent = 'space-between';
            item.style.alignItems = 'center';
            item.style.borderRadius = '6px';
            item.style.transition = 'all 0.2s';

            item.onclick = () => {
                // Remove selected from others
                const allItems = list.querySelectorAll('.file-item');
                allItems.forEach(el => {
                    el.style.background = 'transparent';
                    el.dataset.selected = 'false';
                });

                // Select this one
                item.style.background = '#eff6ff';
                item.dataset.selected = 'true';
                selectedAnalysisFilename = f.filename;

                // Enable confirm button
                if (confirmBtn) {
                    confirmBtn.disabled = false;
                    confirmBtn.style.opacity = '1';
                    confirmBtn.style.cursor = 'pointer';
                }
            };

            // Add hover effect via JS since inline styles override CSS hover
            item.onmouseenter = () => {
                if (item.dataset.selected !== 'true') item.style.background = '#f8fafc';
            };
            item.onmouseleave = () => {
                if (item.dataset.selected !== 'true') item.style.background = 'transparent';
            };

            let icon = '📄';
            if (f.filename.endsWith('.csv')) icon = '📊';
            if (f.filename.endsWith('.xml')) icon = '📑';

            item.innerHTML = `
                <div style="display:flex; align-items:center; gap:8px;">
                    <span style="font-size:16px;">${icon}</span>
                    <div style="display:flex; flex-direction:column;">
                        <span style="font-weight: 500; color: #334155; font-size: 14px;">${f.filename}</span>
                        <span style="font-size: 10px; color: #94a3b8;">${f.uploaded_at}</span>
                    </div>
                </div>
                <span style="font-size: 12px; color: #94a3b8;">${(f.size / 1024).toFixed(1)} KB</span>
            `;
            list.appendChild(item);
        });
    }

    document.getElementById('fileSelectorModal').classList.add('show');
}

function confirmFileSelection() {
    if (selectedAnalysisFilename) {
        analyzeFile(selectedAnalysisFilename);
        closeFileSelector();
    }
}

function closeFileSelector() {
    document.getElementById('fileSelectorModal').classList.remove('show');
}

// --- Analysis Logic ---
let analysisCurrentPage = 1;
let analysisFilename = '';
let originalTableData = []; // Store full page rows
let tableHeaders = [];     // Store current headers
let currentSortColumn = -1;
let currentSortOrder = 'asc';
let activeFilters = [];    // Array of {colIdx, colName, value}
let analysisTotalLines = 0; // Store total lines of current file
let visibleColumnIndices = []; // Stores indices of columns to show

async function analyzeFile(filename) {
    analysisFilename = filename;
    originalTableData = []; // 重置數據
    activeFilters = [];

    // 1. Reset Chart Configuration and UI
    clearChartConfig();
    resetAdvancedResults(); // 清除先前的分析結果
    latestImportantFactors = []; // 清除 AI 建議

    // 2. Switch to Table View
    switchAnalysisMode('table');

    switchView('analysis');
    await loadAnalysisPage(-1); // 使用 -1 代表強製重新載入全量數據
}

async function loadAnalysisPage(page) {
    analysisCurrentPage = page;
    document.getElementById('analysis-filename').innerText = analysisFilename;
    const contentDiv = document.getElementById('analysis-content');

    // 只有第一次進入或切換檔案時才需要載入全部數據
    if (originalTableData.length === 0 || page === -1) {
        contentDiv.innerHTML = '<div style="text-align: center; color: #64748b; padding: 40px;">⏳ 正在由伺服器下載全量數據 (預計 1-3 秒)...</div>';
        try {
            // 先拿標頭
            const infoRes = await fetch(`/api/view_file/${analysisFilename}?page=1&page_size=1`);
            const infoData = await infoRes.json();
            analysisTotalLines = infoData.total_lines || 0;
            document.getElementById('analysis-header-count').innerText = `(總計 ${analysisTotalLines - 1} 筆數據)`;

            if (analysisFilename.toLowerCase().endsWith('.csv')) {
                tableHeaders = infoData.content.trim().split('\n')[0].split(',').map(h => h.trim());

                // Default to show all columns initially
                visibleColumnIndices = tableHeaders.map((_, i) => i);

                // 下載全量數據 (設定一個極大的 pageSize 確保拿完)
                const fullRes = await fetch(`/api/view_file/${analysisFilename}?page=1&page_size=1000000`);
                const fullData = await fullRes.json();
                const lines = fullData.content.trim().split('\n');
                originalTableData = lines.slice(1).map((row, idx) => {
                    const arr = row.split(',').map(c => c.trim());
                    arr.__idx = idx; // Assign persistent unique ID based on original position
                    return arr;
                });
            } else {
                // XML/其他格式維持原樣預覽
                const res = await fetch(`/api/view_file/${analysisFilename}?page=1&page_size=5000`);
                const data = await res.json();
                contentDiv.innerHTML = `<div class="analysis-table-container"><pre style="font-family: monospace; white-space: pre-wrap; padding: 15px;">${data.content}</pre></div>`;
                renderPagination(1, analysisTotalLines, 0);
                return;
            }
        } catch (err) {
            contentDiv.innerHTML = `<div style="color: red; text-align: center; padding: 40px;">載入失敗: ${err.message}</div>`;
            return;
        }
    }

    // 執行渲染 (前端處理分頁與過濾)
    analysisCurrentPage = page === -1 ? 1 : page;
    renderTable(tableHeaders, originalTableData, analysisCurrentPage, analysisTotalLines);
    updateFilterBar();
}

function getFilteredRows(data) {
    if (!data) return [];
    return data.filter(row => {
        // Group filters by column to handle Range OR logic
        const colFilters = {};
        activeFilters.forEach(f => {
            if (!colFilters[f.colIdx]) colFilters[f.colIdx] = [];
            colFilters[f.colIdx].push(f);
        });

        return Object.values(colFilters).every(filters => {
            const indexKeepFilters = filters.filter(f => f.type === 'indices');
            const indexExcludeFilters = filters.filter(f => f.type === 'exclude_indices');

            if (indexKeepFilters.length > 0 || indexExcludeFilters.length > 0) {
                // 🛠️ CRITICAL FALLBACK: If __idx is missing (current session), sync it now
                if (row.__idx === undefined) {
                    row.__idx = originalTableData.indexOf(row);
                }

                const origIdx = row.__idx;

                let passed = true;
                if (indexKeepFilters.length > 0) {
                    // Sequential Narrowing: Must be in ALL Keep filters (Intersection)
                    passed = indexKeepFilters.every(f => f.indices.includes(origIdx));
                }
                if (passed && indexExcludeFilters.length > 0) {
                    // Cumulative Exclusion: Must NOT be in ANY Exclude filter
                    passed = !indexExcludeFilters.some(f => f.indices.includes(origIdx));
                }
                return passed;
            }

            const rangeFilters = filters.filter(f => f.type === 'range');
            const otherFilters = filters.filter(f => f.type !== 'range');

            const passOthers = otherFilters.every(f => {
                const cellVal = row[f.colIdx];
                if (f.type === 'not_empty') return cellVal && cellVal.trim() !== '';
                if (f.type === 'exclude_range') {
                    const num = parseFloat(cellVal);
                    return isNaN(num) || num < f.min || num > f.max;
                }
                const rowVal = cellVal ? cellVal.toLowerCase() : '';
                return rowVal.includes(f.value.toLowerCase());
            });

            if (!passOthers) return false;

            if (rangeFilters.length > 0) {
                return rangeFilters.some(f => {
                    const num = parseFloat(row[f.colIdx]);
                    return !isNaN(num) && num >= f.min && num <= f.max;
                });
            }
            return true;
        });
    });
}

function renderTable(headers, rows, currentPage, totalLines) {
    // 1. 全域過濾 (針對所有下載下來的 Rows)
    let filteredRows = getFilteredRows(rows);

    // Update Header Count
    const headerCount = document.getElementById('analysis-header-count');
    if (headerCount) {
        headerCount.innerHTML = `(目前顯示: <b style="color: #3b82f6;">${filteredRows.length}</b> / 總計: ${totalLines - 1})`;
    }

    // 2. 排序
    if (currentSortColumn !== -1) {
        filteredRows.sort((a, b) => {
            let valA = a[currentSortColumn] || '';
            let valB = b[currentSortColumn] || '';
            if (!isNaN(valA) && !isNaN(valB) && valA !== "" && valB !== "") {
                return currentSortOrder === 'asc' ? Number(valA) - Number(valB) : Number(valB) - Number(valA);
            }
            return currentSortOrder === 'asc' ? valA.localeCompare(valB) : valB.localeCompare(valA);
        });
    }

    // 3. 處理顯示邏輯：一律強制分頁 (每頁 100 筆) 以優化效能
    const pageSize = 100;

    // 校正當前頁碼 (若過濾後頁數變少)
    const totalPages = Math.ceil(filteredRows.length / pageSize);
    if (currentPage > totalPages && totalPages > 0) currentPage = 1;
    if (currentPage < 1) currentPage = 1;

    const start = (currentPage - 1) * pageSize;
    const end = start + pageSize;
    const rowsToDisplay = filteredRows.slice(start, end);

    let html = '<div class="analysis-table-container">';
    html += '<table class="analysis-table">';
    html += '<thead><tr>';

    // Only render visible headers
    visibleColumnIndices.forEach(idx => {
        const h = headers[idx];
        const sortIcon = currentSortColumn === idx ? (currentSortOrder === 'asc' ? ' 🔼' : ' 🔽') : '';
        html += `<th onclick="handleSort(${idx}, '${h}')">${h}${sortIcon}</th>`;
    });
    html += '</tr></thead><tbody>';

    rowsToDisplay.forEach(row => {
        html += '<tr>';
        // Only render visible cells
        visibleColumnIndices.forEach(idx => {
            html += `<td>${row[idx] || ''}</td>`;
        });
        html += '</tr>';
    });

    if (rowsToDisplay.length === 0) {
        html += `<tr><td colspan="${headers.length}" style="text-align: center; padding: 40px; color: #94a3b8;">無符合篩選條件的數據</td></tr>`;
    }

    html += '</tbody></table></div>';
    document.getElementById('analysis-content').innerHTML = html;

    // Pass the corrected currentPage back to pagination
    renderPagination(currentPage, totalLines, filteredRows.length);
}

function updateFilterBar() {
    const bar = document.getElementById('filter-bar-area');
    if (!bar) return;
    bar.style.display = 'flex';

    const leftActions = bar.querySelector('.filter-actions-left');
    if (!leftActions) return;

    // Keep the action buttons, remove only pills
    const existingPills = leftActions.querySelectorAll('.filter-pill');
    existingPills.forEach(p => p.remove());

    activeFilters.forEach((f, idx) => {
        const pill = document.createElement('div');
        pill.className = 'filter-pill';
        let displayText = f.value;
        if (f.type === 'not_empty') displayText = '移除空值';
        if (f.type === 'range') {
            displayText = `${f.min.toFixed(2)} ~ ${f.max.toFixed(2)}`;
            pill.style.background = '#fffbeb';
            pill.style.color = '#92400e';
            pill.style.borderColor = '#fde68a';
        }
        if (f.type === 'indices') {
            displayText = `精確選取: ${f.indices.length} 筆`;
            pill.style.background = '#f0fdf4'; // Green-50
            pill.style.color = '#166534';      // Green-800
            pill.style.borderColor = '#bbf7d0'; // Green-200
        }
        if (f.type === 'exclude_indices') {
            displayText = `精確排除: ${f.indices.length} 筆`;
            pill.style.background = '#fef2f2'; // Red-50
            pill.style.color = '#991b1b';      // Red-800
            pill.style.borderColor = '#fecaca'; // Red-200
        }
        if (f.type === 'exclude_range') {
            displayText = `排除: ${f.min.toFixed(2)} ~ ${f.max.toFixed(2)}`;
            pill.style.background = '#fff1f2'; // Rose-50
            pill.style.color = '#9f1239';      // Rose-800
            pill.style.borderColor = '#fecdd3'; // Rose-200
        }

        pill.innerHTML = `
            <span style="font-weight:600;">${f.colName}:</span> <span>${displayText}</span>
            <span class="remove-pill" onclick="removeFilter(${idx})">&times;</span>
        `;
        const menuContainer = leftActions.querySelector('.filter-menu-container');
        leftActions.insertBefore(pill, menuContainer);
    });
}

function toggleFilterMenu(event) {
    if (event) event.stopPropagation();
    const menu = document.getElementById('filter-menu');
    const isVisible = menu.style.display === 'flex';

    if (!isVisible) {
        // Populate dropdown with current headers
        const select = document.getElementById('filter-column-select');
        select.innerHTML = tableHeaders.map((h, i) => `<option value="${i}">${h}</option>`).join('');

        menu.style.display = 'flex';
        document.getElementById('filter-value-input').focus();
        // Reset checkbox
        document.getElementById('filter-not-empty-check').checked = false;

        // Close menu if clicking outside
        const closeHandler = (e) => {
            if (!menu.contains(e.target) && !e.target.closest('.add-filter-btn')) {
                menu.style.display = 'none';
                document.removeEventListener('click', closeHandler);
            }
        };
        setTimeout(() => document.addEventListener('click', closeHandler), 10);
    } else {
        menu.style.display = 'none';
    }
}

function handleFilterKey(event) {
    if (event.key === 'Enter') {
        addFilterFromMenu();
    } else if (event.key === 'Escape') {
        toggleFilterMenu();
    }
}

function addFilterFromMenu() {
    const select = document.getElementById('filter-column-select');
    const input = document.getElementById('filter-value-input');
    const notEmptyCheck = document.getElementById('filter-not-empty-check');

    const colIdx = parseInt(select.value);
    const colName = tableHeaders[colIdx];
    const value = input.value.trim();
    const isNotEmpty = notEmptyCheck.checked;

    if (value || isNotEmpty) {
        if (isNotEmpty) {
            activeFilters.push({ colIdx, colName, value: '', type: 'not_empty' });
        } else if (value) {
            activeFilters.push({ colIdx, colName, value, type: 'text' });
        }

        input.value = ""; // Clear for next time
        notEmptyCheck.checked = false;
        document.getElementById('filter-menu').style.display = 'none';
        updateFilterBar();
        renderTable(tableHeaders, originalTableData, 1, analysisTotalLines); // Reset to page 1
    }
}

function removeFilter(idx) {
    activeFilters.splice(idx, 1);
    renderTable(tableHeaders, originalTableData, 1, analysisTotalLines);
    updateFilterBar();
    // Sync chart if in chart mode
    if (document.getElementById('chart-view-container').style.display !== 'none') {
        renderAnalysisChart();
    }
}

function resetAllFilters() {
    activeFilters = [];
    renderTable(tableHeaders, originalTableData, 1, analysisTotalLines);
    updateFilterBar();
    // Sync chart if in chart mode
    if (document.getElementById('chart-view-container').style.display !== 'none') {
        renderAnalysisChart();
    }
}

function handleSort(colIdx, headerText) {
    if (currentSortColumn === colIdx) {
        currentSortOrder = currentSortOrder === 'asc' ? 'desc' : 'asc';
    } else {
        currentSortColumn = colIdx;
        currentSortOrder = 'asc';
    }
    renderTable(tableHeaders, originalTableData, analysisCurrentPage, analysisTotalLines);
}

function renderPagination(currentPage, totalLines, filteredCount) {
    const pageSize = 100;
    // Use filteredCount for calculating pages actually displayed
    // (Use Math.max(1, ...) to ensure at least 1 page if 0 results)
    const countForCalc = filteredCount > 0 ? filteredCount : 1;
    const totalPages = Math.ceil(countForCalc / pageSize);
    const container = document.getElementById('analysis-pagination-container');

    // 1. Prepare Content Strings
    const totalText = `總計: ${filteredCount} 筆 (原始: ${totalLines - 1})`;

    // Update Top Bar Count Display (Next to filter conditions) - Always Hidden as requested
    const topBarCount = document.getElementById('filter-bar-count-display');
    if (topBarCount) topBarCount.style.display = 'none';

    // 3. Normal Pagination Case
    // Show navigation ALWAYS unless there's only 1 page
    const showNavigation = totalPages > 1;

    let html = `
        <div class="pagination-bar">
            <div style="flex: 1;"></div>
            
            <div style="flex: 1; display: flex; align-items: center; justify-content: center; gap: 15px;">
                ${showNavigation ? `
                    <button class="btn-page" onclick="loadAnalysisPage(${currentPage - 1})" ${currentPage <= 1 ? 'disabled' : ''}>上一頁</button>
                    <span class="page-info">第 ${currentPage} / ${totalPages} 頁</span>
                    <button class="btn-page" onclick="loadAnalysisPage(${currentPage + 1})" ${currentPage >= totalPages ? 'disabled' : ''}>下一頁</button>
                ` : `<div class="page-info" style="color: #64748b;">第 1 / 1 頁</div>`}
            </div>

            <div style="flex: 1; font-size: 13px; color: #64748b; font-weight: 600; text-align: right;">
                ${totalText}
            </div>
        </div>
    `;
    container.innerHTML = html;
}

// --- Column Picker Functions ---
function openColumnPicker() {
    const modal = document.getElementById('col-picker-modal');
    const list = document.getElementById('col-picker-list');
    modal.style.display = 'flex';

    list.innerHTML = tableHeaders.map((h, i) => {
        const isChecked = visibleColumnIndices.includes(i);
        return `
            <div class="col-item" onclick="toggleColCheckbox(event, ${i})">
                <input type="checkbox" id="col-check-${i}" ${isChecked ? 'checked' : ''} onclick="event.stopPropagation()">
                <label>${h}</label>
            </div>
        `;
    }).join('');

    updateColSelectCount();
}

function closeColumnPicker() {
    document.getElementById('col-picker-modal').style.display = 'none';
}

function toggleColCheckbox(event, idx) {
    const cb = document.getElementById(`col-check-${idx}`);
    cb.checked = !cb.checked;
    updateColSelectCount();
}

function toggleAllColumns(isSelected) {
    const checkboxes = document.querySelectorAll('#col-picker-list input[type="checkbox"]');
    checkboxes.forEach(cb => {
        // If filtered, only toggle visible ones in list
        if (cb.parentElement.style.display !== 'none') {
            cb.checked = isSelected;
        }
    });
    updateColSelectCount();
}

function filterColumnList() {
    const q = document.getElementById('col-search-input').value.toLowerCase();
    const items = document.querySelectorAll('.col-item');
    items.forEach(item => {
        const text = item.querySelector('label').innerText.toLowerCase();
        item.style.display = text.includes(q) ? 'flex' : 'none';
    });
}

function updateColSelectCount() {
    const total = tableHeaders.length;
    const selected = document.querySelectorAll('#col-picker-list input[type="checkbox"]:checked').length;
    document.getElementById('col-select-count').innerText = `已選擇: ${selected} / ${total} 欄位`;
}

function applyColumnVisibility() {
    const checkboxes = document.querySelectorAll('#col-picker-list input[type="checkbox"]');
    visibleColumnIndices = [];
    checkboxes.forEach((cb, i) => {
        if (cb.checked) visibleColumnIndices.push(i);
    });

    closeColumnPicker();
    renderTable(tableHeaders, originalTableData, analysisCurrentPage, analysisTotalLines);
}


// --- Chat / AI Logic ---
let selectedFiles = [];

function handleChatKey(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendChatMessage();
    }
}

function handleFileSelect(input) {
    if (input.files.length > 0) {
        processFiles(input.files);
    }
}

function processFiles(fileList) {
    for (let file of fileList) {
        selectedFiles.push(file);
    }
    updateFilePreview();
}

function updateFilePreview() {
    const container = document.getElementById('file-preview-area');
    container.innerHTML = '';

    if (selectedFiles.length === 0) {
        container.style.display = 'none';
        return;
    }

    container.style.display = 'flex';
    selectedFiles.forEach((file, index) => {
        const item = document.createElement('div');
        item.className = 'preview-item';

        if (file.type.startsWith('image/')) {
            const img = document.createElement('img');
            img.file = file;
            const reader = new FileReader();
            reader.onload = (e) => img.src = e.target.result;
            reader.readAsDataURL(file);
            item.appendChild(img);
        } else {
            item.innerHTML = '<span style="font-size: 20px;">📄</span>';
        }

        const removeBtn = document.createElement('div');
        removeBtn.className = 'preview-remove';
        removeBtn.innerHTML = '×';
        removeBtn.onclick = () => removeFile(index);
        item.appendChild(removeBtn);

        container.appendChild(item);
    });
}

function removeFile(index) {
    selectedFiles.splice(index, 1);
    updateFilePreview();
}

async function generateAIReport() {
    const btn = document.querySelector('.btn-primary'); // Assuming this refers to the 'Ask AI' button if it had that class, but here we use sendChatMessage manually.
    // This function might be deprecated or used differently. 
    // In original code, it was called by button. We'll integrate it into sendChatMessage logic if needed or keep separate.
    // The original code had separate "Generate Report" button logic sometimes.
    // But here we rely on sendChatMessage for interaction.
    // We will keep it if it was used in UI buttons.
    // Checking previous code... it seems sendChatMessage handles everything.
}

async function sendChatMessage() {
    const input = document.getElementById('chat-input');
    const message = input.value.trim();
    if (!message && selectedFiles.length === 0) return;

    const chatContent = document.getElementById('ai-report-content');

    // User Message
    const userDiv = document.createElement('div');
    userDiv.className = 'chat-bubble user-bubble';

    let userHtml = '';
    // Display attachments
    if (selectedFiles.length > 0) {
        userHtml += '<div class="bubble-attachments">';
        for (let file of selectedFiles) {
            if (file.type.startsWith('image/')) {
                const reader = new FileReader();
                reader.readAsDataURL(file); // Trigger read for display? Async issue.
                // Simple workaround: create object URL or standard placeholder.
                userHtml += `<div class="bubble-attach-file">📷</div>`;
            } else {
                userHtml += `<div class="bubble-attach-file">📄</div>`;
            }
        }
        userHtml += '</div>';
    }
    userHtml += `<p>${message}</p>`; // Basic escaping might be needed in real app
    userDiv.innerHTML = userHtml;
    chatContent.appendChild(userDiv);

    input.value = '';
    chatContent.scrollTop = chatContent.scrollHeight;

    // AI Loading
    const loadingDiv = document.createElement('div');
    loadingDiv.className = 'chat-bubble ai-bubble';
    loadingDiv.innerHTML = 'Thinking...';
    chatContent.appendChild(loadingDiv);

    try {
        const formData = new FormData();
        formData.append('prompt', message);
        formData.append('session_id', SESSION_ID);
        // formData.append('model', 'gemini-1.5-pro'); // Default to pro

        selectedFiles.forEach(file => {
            formData.append('files', file);
        });

        // Clear selection
        selectedFiles = [];
        updateFilePreview();

        const res = await fetch('/api/details_gemini', {
            method: 'POST',
            body: formData
        });

        const data = await res.json();
        chatContent.removeChild(loadingDiv);

        if (res.ok) {
            const aiDiv = document.createElement('div');
            aiDiv.className = 'chat-bubble ai-bubble';
            // Render Markdown
            aiDiv.innerHTML = marked.parse(data.analysis);
            chatContent.appendChild(aiDiv);

            // Handle charts
            if (data.charts && data.charts.length > 0) {
                data.charts.forEach((chartData, idx) => {
                    const chartId = `ai-chart-${Date.now()}-${idx}`;
                    const chartContainer = document.createElement('div');
                    chartContainer.style.width = '100%';
                    chartContainer.style.height = '200px';
                    chartContainer.style.marginTop = '10px';
                    chartContainer.innerHTML = `<canvas id="${chartId}"></canvas>`;
                    aiDiv.appendChild(chartContainer);

                    setTimeout(() => {
                        createChart(chartId, chartData);
                    }, 100);
                });
            }

            // Sync Important Factors
            if (data.analysis.includes("重要因子")) {
                // Parsing logic could be complex, for now we assume backend suggests via specific field if needed
                // Or we parse text. But original code called syncImportantChartColumns logic elsewhere or manually.
                // If backend returns 'suggested_columns', we use it.
            }

        } else {
            const errDiv = document.createElement('div');
            errDiv.className = 'chat-bubble ai-bubble';
            errDiv.style.color = 'red';
            errDiv.innerText = `Error: ${data.detail}`;
            chatContent.appendChild(errDiv);
        }

    } catch (err) {
        chatContent.removeChild(loadingDiv);
        const errDiv = document.createElement('div');
        errDiv.className = 'chat-bubble ai-bubble';
        errDiv.style.color = 'red';
        errDiv.innerText = `Connection Error: ${err.message}`;
        chatContent.appendChild(errDiv);
    }
    chatContent.scrollTop = chatContent.scrollHeight;
}

function clearHistory() {
    document.getElementById('ai-report-content').innerHTML = `
        <div class="chat-bubble ai-bubble">
            <p>👋 你好！我是你的 AI 數據分析助手。</p>
            <p>你可以問我關於這些數據的問題，或者讓我幫你找出異常原因。</p>
        </div>
    `;
    // Also clear backend history if API supports it
}

// --- Dashboard Polling Logic ---
async function updateDashboard() {
    if ((Date.now() - lastLogTimestamp) < 1000 && lastLogTimestamp !== 0) return;

    try {
        const res = await fetch(`/api/state?session_id=${SESSION_ID}&ts=${lastLogTimestamp}`);
        const data = await res.json();

        if (data.logs && data.logs.length > 0) {
            const logContainer = document.getElementById('reasoning-logs');
            if (document.getElementById('log-empty-msg')) {
                logContainer.innerHTML = '';
            }

            let newLogsHtml = '';
            data.logs.forEach(log => {
                const ts = new Date(log.timestamp * 1000).toLocaleTimeString();
                newLogsHtml += `
                    <div class="log-item">
                        <span class="log-ts">[${ts}]</span>
                        <span class="log-body">${log.message}</span>
                    </div>
                `;
            });
            logContainer.innerHTML += newLogsHtml;
            logContainer.scrollTop = logContainer.scrollHeight;
            lastLogTimestamp = Date.now() / 1000;
        }

        // Update Charts
        if (data.charts) {
            Object.keys(data.charts).forEach(key => {
                const chartData = data.charts[key];
                if (charts[key]) {
                    charts[key].data = chartData;
                    charts[key].update();
                } else {
                    createChart(key, chartData);
                }
            });
        }

        // Update Status
        if (data.status) {
            // document.getElementById('status-text').innerText = data.status;
        }

    } catch (err) {
        // console.warn("Polling error:", err);
    }
}

function createChart(canvasId, chartData) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    // Destroy existing if re-creating on same canvas (though usually we update)
    // Here we assume createChart is called only when chart doesn't exist in our 'charts' map
    // UNLESS it's an AI embedded chart which is handled differently.

    // If it's a main dashboard chart (managed in 'charts' obj)
    if (['chart-sales', 'chart-inventory'].includes(canvasId)) {
        if (charts[canvasId]) {
            charts[canvasId].destroy();
        }
        charts[canvasId] = new Chart(ctx, {
            type: chartData.type || 'line',
            data: chartData,
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { position: 'bottom' } }, // simplified
                animation: false // Performance
            }
        });
    } else {
        // AI embedded chart (one-off)
        new Chart(ctx, {
            type: chartData.type || 'bar',
            data: chartData,
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } }
            }
        });
    }
}

// Start Polling 
// setInterval(updateDashboard, 2000); // 2 seconds

// --- Charting Logic (Main Analysis Chart) ---
let chartConfig = {
    x: null,
    y: null,
    y2: null,
    type: 'scatter'
};
let analysisChart = null;
let selectionMode = false;
let isSelecting = false;
let selectionStart = { x: 0, y: 0 };
let currentChartSelectionRange = null; // {x, y, xMin, xMax, yMin, yMax}

function toggleSelectionMode() {
    selectionMode = !selectionMode;
    const btn = document.getElementById('btn-select-mode');
    if (selectionMode) {
        btn.classList.add('active');
        btn.style.background = '#eff6ff';
        btn.style.color = '#2563eb';
        btn.style.borderColor = '#3b82f6';
        document.getElementById('analysis-chart-canvas').style.cursor = 'crosshair';
        alert('框選模式已開啟：請在圖表上拖曳滑鼠進行框選');
    } else {
        btn.classList.remove('active');
        btn.style.background = '';
        btn.style.color = '#64748b';
        btn.style.borderColor = '#cbd5e1';
        document.getElementById('analysis-chart-canvas').style.cursor = 'default';
        clearChartSelection();
    }
}

function setChartType(type) {
    chartConfig.type = type;
    document.querySelectorAll('.chart-type-btn').forEach(b => b.classList.remove('active'));
    document.getElementById('btn-chart-' + type).classList.add('active');
    tryUpdateChart();
}

function filterChartColumns() {
    const q = document.getElementById('chart-col-search').value.toLowerCase();
    const chips = document.querySelectorAll('#chart-column-source .draggable-chip');
    chips.forEach(chip => {
        const text = chip.innerText.toLowerCase();
        chip.style.display = text.includes(q) ? 'block' : 'none';
    });
}

function switchAnalysisMode(mode) {
    const tableContainer = document.getElementById('analysis-table-view');
    const chartContainer = document.getElementById('analysis-chart-view');
    const tableBtn = document.getElementById('btn-view-table');
    const chartBtn = document.getElementById('btn-view-chart');

    if (mode === 'table') {
        tableContainer.style.display = 'block';
        chartContainer.style.display = 'none';
        tableBtn.classList.add('active');
        chartBtn.classList.remove('active');
    } else {
        tableContainer.style.display = 'none';
        chartContainer.style.display = 'flex';
        tableBtn.classList.remove('active');
        chartBtn.classList.add('active');
        initChartColumns();
        // Resize chart
        if (analysisChart) analysisChart.resize();
    }
}

async function saveFilteredData() {
    // Collect filtered data
    const filtered = getFilteredRows(originalTableData);
    if (filtered.length === 0) {
        alert("目前無數據可儲存");
        return;
    }

    // Constuct CSV content
    const headerStr = tableHeaders.join(',');
    const bodyStr = filtered.map(row => {
        // Exclude internal props like __idx if any (it's non-enumerable usually but row is array)
        // row is Array with props.
        // We just map indices.
        return tableHeaders.map((_, i) => row[i]).join(',');
    }).join('\n');

    const csvContent = headerStr + '\n' + bodyStr;
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.setAttribute("href", url);
    link.setAttribute("download", `filtered_${analysisFilename || 'data'}.csv`);
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

function updateChartSourceInfo(count = null) {
    const info = document.getElementById('chart-source-info');
    if (!analysisFilename) return;

    if (count === null) {
        // Count filtered rows
        const filtered = getFilteredRows(originalTableData);
        count = filtered.length;
    }
    info.innerText = `來源: ${analysisFilename} (共 ${count} 筆)`;
}

// --- Advanced Analysis & Chart Config ---
let advancedAnalysisResults = null;

function initChartColumns() {
    const container = document.getElementById('chart-column-source');
    if (!container) return; // Not in chart mode or DOM not ready
    container.innerHTML = '';

    // Strategy: Use AI suggestions first, then others
    let columns = [...tableHeaders];

    // Sort logic? Keep original order for now.

    columns.forEach(col => {
        const chip = document.createElement('div');
        chip.className = 'draggable-chip';
        chip.draggable = true;
        chip.innerText = col;

        // Highlight AI factors
        if (latestImportantFactors.includes(col)) {
            chip.style.borderColor = '#fbbf24';
            chip.style.background = '#fffbeb';
            chip.innerHTML += ' <span style="font-size:10px;">★</span>';
        }

        chip.ondragstart = (ev) => {
            ev.dataTransfer.setData("text", col);
            chip.classList.add('dragging');
        };
        chip.ondragend = () => {
            chip.classList.remove('dragging');
        };

        container.appendChild(chip);
    });
}

function openAdvancedModal() {
    // Populate target select
    const sel = document.getElementById('adv-target-select');
    sel.innerHTML = tableHeaders.map(h => `<option value="${h}">${h}</option>`).join('');
    document.getElementById('advanced-param-modal').style.display = 'flex';
}

function closeAdvancedModal() {
    document.getElementById('advanced-param-modal').style.display = 'none';
}

async function runAdvancedAnalysis() {
    const target = document.getElementById('adv-target-select').value;
    const methodCbs = document.querySelectorAll('input[name="adv-method"]:checked');
    if (!target) { alert("請選擇目標欄位"); return; }
    if (methodCbs.length === 0) { alert("請至少選擇一種分析方法"); return; }

    const methods = Array.from(methodCbs).map(cb => cb.value);

    const btn = document.querySelector('#advanced-param-modal .btn-primary-sm'); // Run button
    const originalText = btn.innerText;
    btn.innerText = "分析中...";
    btn.disabled = true;

    try {
        const res = await fetch('/api/advanced_analysis', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                filename: analysisFilename,
                target: target,
                methods: methods
            })
        });
        const data = await res.json();

        if (res.ok) {
            advancedAnalysisResults = data.results;
            applyAdvancedResults();
            closeAdvancedModal();
            alert("進階分析完成！已將關鍵因子標記於圖表選單。");
        } else {
            alert(`分析失敗: ${data.detail}`);
        }
    } catch (err) {
        alert(`錯誤: ${err.message}`);
    } finally {
        btn.innerText = originalText;
        btn.disabled = false;
    }
}

function applyAdvancedResults() {
    if (!advancedAnalysisResults) return;

    // Merge factors from all results
    let factors = new Set();
    Object.values(advancedAnalysisResults).forEach(res => {
        if (res.important_factors) {
            res.important_factors.forEach(f => factors.add(f));
        }
    });

    syncImportantChartColumns(Array.from(factors));
}

function resetAdvancedResults() {
    advancedAnalysisResults = null;
    initChartColumns();
}

function syncImportantChartColumns(factors) {
    if (factors && factors.length > 0) {
        latestImportantFactors = factors;
    }
    initChartColumns();
}



function allowDrop(ev) {
    ev.preventDefault();
    const dropzone = ev.target.closest('.axis-dropzone');
    if (dropzone) dropzone.classList.add('drag-over');
}

// Global dragleave to clear styling
document.addEventListener('dragleave', (e) => {
    if (e.target.classList && e.target.classList.contains('axis-dropzone')) {
        e.target.classList.remove('drag-over');
    }
}, true);

function handleDrop(ev, axis) {
    ev.preventDefault();
    const dropzone = ev.target.closest('.axis-dropzone');
    if (!dropzone) return;

    dropzone.classList.remove('drag-over');
    const colName = ev.dataTransfer.getData("text");

    if (colName) {
        // Clear correlation when changing parameters
        const resDiv = document.getElementById('correlation-result');
        if (resDiv) resDiv.innerHTML = '';

        chartConfig[axis] = colName;
        const isVertical = axis === 'y' || axis === 'y2';
        const style = isVertical ? 'writing-mode: vertical-rl; text-orientation: mixed;' : '';

        dropzone.innerHTML = `<span style="color: #2563eb; font-weight: bold; ${style}">${colName}</span> <span style="font-size:10px; cursor:pointer;" onclick="event.stopPropagation(); resetAxis('${axis}')">❌</span>`;
        dropzone.classList.add('filled');
        tryUpdateChart();
        updateChartSourceInfo();
    }
}

function clearChartConfig() {
    chartConfig = { x: null, y: null, y2: null, type: 'scatter' };
    clearChartSelection(); // Also clear selection UI
    if (analysisChart) {
        analysisChart.destroy();
        analysisChart = null;
    }

    const resDiv = document.getElementById('correlation-result');
    if (resDiv) resDiv.innerHTML = '';

    // Reset dropzone buttons
    const axes = ['x', 'y', 'y2'];
    axes.forEach(axis => {
        const dropzone = document.getElementById('drop-' + axis);
        if (dropzone) {
            dropzone.classList.remove('filled');
            const isVertical = axis === 'y' || axis === 'y2';
            const phStyle = isVertical ? 'writing-mode: vertical-rl;' : '';
            const phText = axis === 'y2' ? '(選填)' : '拖曳至此';
            dropzone.innerHTML = `<span class="placeholder" style="${phStyle}">${phText}</span>`;
        }
    });

    // Clear source columns list
    const sourceContainer = document.getElementById('chart-column-source');
    if (sourceContainer) sourceContainer.innerHTML = '';
}

function resetAxis(axis) {
    chartConfig[axis] = null;

    // Clear correlation when removing parameters
    const resDiv = document.getElementById('correlation-result');
    if (resDiv) resDiv.innerHTML = '';

    const dropzone = document.getElementById('drop-' + axis);
    dropzone.classList.remove('filled');
    const isVertical = axis === 'y' || axis === 'y2';
    const phStyle = isVertical ? 'writing-mode: vertical-rl;' : '';
    dropzone.innerHTML = `<span class="placeholder" style="${phStyle}">拖曳至此</span>`;
    if (analysisChart) {
        analysisChart.destroy();
        analysisChart = null;
    }
    updateChartSourceInfo();
}

function tryUpdateChart() {
    if (chartConfig.x && (chartConfig.y || chartConfig.y2)) {
        renderAnalysisChart();
    }
}

function renderAnalysisChart() {
    const canvas = document.getElementById('analysis-chart-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    if (analysisChart) analysisChart.destroy();

    // Prepare Data Indices
    const xIdx = tableHeaders.indexOf(chartConfig.x);
    const yIdx = tableHeaders.indexOf(chartConfig.y);
    const y2Idx = tableHeaders.indexOf(chartConfig.y2);

    // Re-apply current filters using helper
    let sourceRows = getFilteredRows(originalTableData);

    if (sourceRows.length === 0) {
        return;
    }

    const chartType = chartConfig.type;
    const datasets = [];
    let labels = null; // For categorical axis
    let isNumericX = false;

    // --- DATA PREPARATION STRATEGY ---

    if (chartType === 'boxplot') {
        isNumericX = false;
        const groups = {};

        sourceRows.forEach(row => {
            let xVal = row[xIdx];
            let yVal1 = yIdx !== -1 ? row[yIdx] : null;
            let yVal2 = y2Idx !== -1 ? row[y2Idx] : null;

            if (xVal === null || xVal === undefined) return;
            const key = String(xVal);

            if (yVal1 !== null && !isNaN(parseFloat(yVal1))) yVal1 = parseFloat(yVal1);
            else yVal1 = null;

            if (yVal2 !== null && !isNaN(parseFloat(yVal2))) yVal2 = parseFloat(yVal2);
            else yVal2 = null;

            if (!groups[key]) groups[key] = { y1: [], y2: [] };
            if (yVal1 !== null) groups[key].y1.push(yVal1);
            if (yVal2 !== null) groups[key].y2.push(yVal2);
        });

        const sortedKeys = Object.keys(groups).sort((a, b) => {
            const nav = parseFloat(a);
            const nbv = parseFloat(b);
            if (!isNaN(nav) && !isNaN(nbv)) return nav - nbv;
            return a.localeCompare(b);
        });

        labels = sortedKeys;

        // 🛠️ Feature: If only 1 category, pad with empty labels to center it
        if (labels.length === 1) {
            labels = ['', labels[0], ' '];
        }

        if (yIdx !== -1) {
            const data1 = sortedKeys.map(k => groups[k].y1);
            // If padded, data must align with index 1
            const boxData1 = labels.length === 3 ? [null, data1[0], null] : data1;
            datasets.push({
                label: chartConfig.y,
                data: boxData1,
                backgroundColor: 'rgba(124, 58, 237, 0.5)',
                borderColor: '#7c3aed',
                borderWidth: 1,
                outlierColor: '#999999',
                padding: 10,
                itemRadius: 2,
                meanRadius: 0,
                yAxisID: 'y'
            });
        }

        if (y2Idx !== -1) {
            const data2 = sortedKeys.map(k => groups[k].y2);
            const boxData2 = labels.length === 3 ? [null, data2[0], null] : data2;
            datasets.push({
                label: chartConfig.y2,
                data: boxData2,
                backgroundColor: 'rgba(6, 182, 212, 0.5)',
                borderColor: '#06b6d4',
                borderWidth: 1,
                outlierColor: '#999999',
                itemRadius: 2,
                meanRadius: 0,
                yAxisID: 'y1'
            });
        }

        updateChartSourceInfo(sourceRows.length);
    } else {
        // SCATTER or LINE Logic
        const maxPoints = 5000;
        const step = Math.ceil(sourceRows.length / maxPoints);

        let dataPoints1 = [];
        let dataPoints2 = [];

        for (let i = 0; i < sourceRows.length; i += step) {
            const row = sourceRows[i];
            let xVal = row[xIdx];
            let yVal1 = yIdx !== -1 ? row[yIdx] : null;
            let yVal2 = y2Idx !== -1 ? row[y2Idx] : null;

            if (!isNaN(parseFloat(xVal))) xVal = parseFloat(xVal);
            if (yVal1 !== null && !isNaN(parseFloat(yVal1))) yVal1 = parseFloat(yVal1);
            if (yVal2 !== null && !isNaN(parseFloat(yVal2))) yVal2 = parseFloat(yVal2);

            if (yVal1 !== null) dataPoints1.push({ x: xVal, y: yVal1, _origIdx: row.__idx });
            if (yVal2 !== null) dataPoints2.push({ x: xVal, y: yVal2, _origIdx: row.__idx });
        }

        updateChartSourceInfo(sourceRows.length);

        isNumericX = dataPoints1.length > 0 && dataPoints1.every(p => typeof p.x === 'number' && !isNaN(p.x));

        if (isNumericX) {
            if (chartType === 'line') {
                dataPoints1.sort((a, b) => a.x - b.x);
                dataPoints2.sort((a, b) => a.x - b.x);
            }
        } else {
            const uniqueX = [...new Set([
                ...dataPoints1.map(p => String(p.x)),
                ...dataPoints2.map(p => String(p.x))
            ])];

            uniqueX.sort((a, b) => {
                const na = parseFloat(a), nb = parseFloat(b);
                if (!isNaN(na) && !isNaN(nb)) return na - nb;
                return a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' });
            });

            labels = uniqueX;

            // 🛠️ Feature: If only 1 category, pad with empty labels to center it
            if (labels.length === 1) {
                labels = ['', labels[0], ' '];
                // Adjust data points to align with the new labels (index 1)
                dataPoints1.forEach(p => p.x = labels[1]);
                dataPoints2.forEach(p => p.x = labels[1]);
            }
        }

        if (yIdx !== -1) {
            datasets.push({
                label: chartConfig.y,
                data: dataPoints1,
                yAxisID: 'y',
                borderColor: '#7c3aed',
                backgroundColor: 'rgba(124, 58, 237, 0.5)',
                pointRadius: chartType === 'scatter' ? 4 : 2,
                showLine: chartType === 'line',
                tension: 0.1
            });
        }

        if (y2Idx !== -1) {
            datasets.push({
                label: chartConfig.y2,
                data: dataPoints2,
                yAxisID: 'y1',
                borderColor: '#06b6d4',
                backgroundColor: 'rgba(6, 182, 212, 0.5)',
                pointRadius: chartType === 'scatter' ? 4 : 2,
                showLine: chartType === 'line',
                tension: 0.1
            });
        }
    }

    const options = {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
            x: {
                type: isNumericX ? 'linear' : 'category',
                title: { display: true, text: chartConfig.x },
                grid: { color: '#f1f5f9' },
                beginAtZero: false
            },
            y: {
                title: { display: true, text: chartConfig.y },
                type: 'linear',
                display: true,
                position: 'left',
                grid: { color: '#f1f5f9' },
                beginAtZero: false
            },
            y1: {
                title: { display: true, text: chartConfig.y2 },
                type: 'linear',
                display: datasets.some(d => d.yAxisID === 'y1'),
                position: 'right',
                grid: { drawOnChartArea: false },
                beginAtZero: false
            }
        },
        plugins: {
            legend: { position: 'top' },
            tooltip: {
                mode: 'index',
                intersect: false,
            }
        }
    };

    analysisChart = new Chart(ctx, {
        type: chartType,
        data: {
            labels: labels,
            datasets: datasets
        },
        options: options
    });
}

// Global Chart Selection Handlers (Add once)
document.addEventListener('DOMContentLoaded', () => {
    const canvas = document.getElementById('analysis-chart-canvas');
    if (!canvas) return;

    canvas.onmousedown = (e) => {
        if (!selectionMode || !analysisChart) return;
        isSelecting = true;
        const rect = canvas.getBoundingClientRect();
        selectionStart = { x: e.clientX - rect.left, y: e.clientY - rect.top };

        const box = document.getElementById('selection-box');
        box.style.display = 'block';
        box.style.left = selectionStart.x + 'px';
        box.style.top = selectionStart.y + 'px';
        box.style.width = '0';
        box.style.height = '0';
    };

    window.addEventListener('mousemove', (e) => {
        if (!isSelecting) return;
        const canvas = document.getElementById('analysis-chart-canvas');
        const rect = canvas.getBoundingClientRect();
        const currentX = e.clientX - rect.left;
        const currentY = e.clientY - rect.top;

        const box = document.getElementById('selection-box');
        const left = Math.min(selectionStart.x, currentX);
        const top = Math.min(selectionStart.y, currentY);
        const width = Math.abs(currentX - selectionStart.x);
        const height = Math.abs(currentY - selectionStart.y);

        box.style.left = left + 'px';
        box.style.top = top + 'px';
        box.style.width = width + 'px';
        box.style.height = height + 'px';
    });

    window.addEventListener('mouseup', (e) => {
        if (!isSelecting) return;
        isSelecting = false;
        const box = document.getElementById('selection-box');
        box.style.display = 'none';

        if (!analysisChart) return;

        const canvas = document.getElementById('analysis-chart-canvas');
        const rect = canvas.getBoundingClientRect();
        const endX = e.clientX - rect.left;
        const endY = e.clientY - rect.top;

        const x1 = selectionStart.x;
        const y1 = selectionStart.y;
        const x2 = endX;
        const y2 = endY;

        // Min/Max Pixels
        const pXMin = Math.min(x1, x2);
        const pXMax = Math.max(x1, x2);
        const pYMin = Math.min(y1, y2);
        const pYMax = Math.max(y1, y2);

        // Convert Pixels to Data Values
        const xScale = analysisChart.scales.x;
        const yScale = analysisChart.scales.y;

        const vXMin = xScale.getValueForPixel(pXMin);
        const vXMax = xScale.getValueForPixel(pXMax);
        const vYMin = yScale.getValueForPixel(pYMax);
        const vYMax = yScale.getValueForPixel(pYMin);

        if (Math.abs(pXMax - pXMin) > 5 || Math.abs(pYMax - pYMin) > 5) {
            // Clear correlation results when selection starts
            const resDiv = document.getElementById('correlation-result');
            if (resDiv) resDiv.innerHTML = '';

            currentChartSelectionRange = {
                x: chartConfig.x,
                y: chartConfig.y,
                xMin: Math.min(vXMin, vXMax),
                xMax: Math.max(vXMin, vXMax),
                yMin: Math.min(vYMin, vYMax),
                yMax: Math.max(vYMin, vYMax)
            };
            updateSelectionUI();
            highlightPointsInChart();
        }
    });
});

function updateSelectionUI() {
    const modal = document.getElementById('selection-modal');
    const countText = document.getElementById('selection-count-text');

    if (!currentChartSelectionRange) {
        modal.style.display = 'none';
        return;
    }

    const xIdx = tableHeaders.indexOf(currentChartSelectionRange.x);
    const yIdx = tableHeaders.indexOf(currentChartSelectionRange.y);

    const sourceRows = getFilteredRows(originalTableData);
    const selected = sourceRows.filter(row => {
        const vx = parseFloat(row[xIdx]);
        const vy = parseFloat(row[yIdx]);
        if (isNaN(vx) || isNaN(vy)) return false;
        return vx >= currentChartSelectionRange.xMin && vx <= currentChartSelectionRange.xMax &&
            vy >= currentChartSelectionRange.yMin && vy <= currentChartSelectionRange.yMax;
    });

    modal.style.display = 'flex';
    countText.innerHTML = `📍 已選取 <b style="color:#7c3aed; font-size:16px;">${selected.length}</b> 筆`;
}

function highlightPointsInChart() {
    if (!analysisChart || !currentChartSelectionRange) return;

    analysisChart.data.datasets.forEach((ds, dsIdx) => {
        const pointColors = [];
        const pointSizes = [];

        ds.data.forEach(p => {
            const isSelected = p.x >= currentChartSelectionRange.xMin && p.x <= currentChartSelectionRange.xMax &&
                p.y >= currentChartSelectionRange.yMin && p.y <= currentChartSelectionRange.yMax;

            if (isSelected) {
                pointColors.push('#fbbf24'); // Bright Gold
                pointSizes.push(8);          // Larger
            } else {
                pointColors.push(dsIdx === 0 ? 'rgba(124, 58, 237, 0.3)' : 'rgba(6, 182, 212, 0.3)');
                pointSizes.push(4);          // Default
            }
        });

        ds.pointBackgroundColor = pointColors;
        ds.pointBorderColor = pointColors.map((c, i) => pointSizes[i] === 8 ? '#92400e' : c);
        ds.pointRadius = pointSizes;
        ds.pointHoverRadius = pointSizes.map(s => s + 2);
    });
    analysisChart.update();
}

function clearChartSelection() {
    currentChartSelectionRange = null;
    document.getElementById('selection-modal').style.display = 'none';
    if (analysisChart) {
        analysisChart.data.datasets.forEach((ds, dsIdx) => {
            const baseColor = dsIdx === 0 ? 'rgba(124, 58, 237, 0.5)' : 'rgba(6, 182, 212, 0.5)';
            ds.pointBackgroundColor = baseColor;
            ds.pointBorderColor = baseColor;
            ds.pointRadius = chartConfig.type === 'scatter' ? 4 : 2;
            ds.pointHoverRadius = ds.pointRadius + 2;
        });
        analysisChart.update();
    }
}

function applySelectionAsFilter(mode) {
    if (!currentChartSelectionRange || !analysisChart) return;

    // Collect precise indices from the current chart instance
    const selectedIndices = [];
    analysisChart.data.datasets.forEach(ds => {
        ds.data.forEach(p => {
            if (p.x >= currentChartSelectionRange.xMin && p.x <= currentChartSelectionRange.xMax &&
                p.y >= currentChartSelectionRange.yMin && p.y <= currentChartSelectionRange.yMax) {
                if (p._origIdx !== undefined) selectedIndices.push(p._origIdx);
            }
        });
    });

    if (selectedIndices.length === 0) return;

    const filterType = mode === 'keep' ? 'indices' : 'exclude_indices';
    const uniqueIndices = [...new Set(selectedIndices)];

    activeFilters.push({
        colIdx: 'index_meta', // Special marker
        colName: '圖表選取',
        type: filterType,
        indices: uniqueIndices,
        value: `Selected ${uniqueIndices.length}`
    });

    renderTable(tableHeaders, originalTableData, 1, analysisTotalLines);
    updateFilterBar();
    clearChartSelection();

    // Corrected ID check: analysis-chart-view
    if (document.getElementById('analysis-chart-view').style.display !== 'none') {
        renderAnalysisChart();
    }
}

function calculateCorrelation() {
    if (!chartConfig.x || (!chartConfig.y && !chartConfig.y2)) {
        alert("請先配置 X 軸與至少一個 Y 軸欄位 (Y1 或 Y2)");
        return;
    }

    // Get filtered data using helper
    const sourceRows = getFilteredRows(originalTableData);

    if (sourceRows.length < 2) {
        alert("數據太少，無法計算相關係數");
        return;
    }

    const xIdx = tableHeaders.indexOf(chartConfig.x);
    const y1Idx = tableHeaders.indexOf(chartConfig.y);
    const y2Idx = tableHeaders.indexOf(chartConfig.y2);

    function getPearson(idx1, idx2) {
        if (idx1 === -1 || idx2 === -1) return null;
        let x = [], y = [];
        sourceRows.forEach(row => {
            const v1 = parseFloat(row[idx1]);
            const v2 = parseFloat(row[idx2]);
            if (!isNaN(v1) && !isNaN(v2)) {
                x.push(v1);
                y.push(v2);
            }
        });
        if (x.length < 2) return null;
        const n = x.length;
        const sumX = x.reduce((a, b) => a + b, 0);
        const sumY = y.reduce((a, b) => a + b, 0);
        const sumXY = x.reduce((a, b, i) => a + b * y[i], 0);
        const sumX2 = x.reduce((a, b) => a + b * b, 0);
        const sumY2 = y.reduce((a, b) => a + b * b, 0);
        const num = n * sumXY - sumX * sumY;
        const den = Math.sqrt((n * sumX2 - sumX * sumX) * (n * sumY2 - sumY * sumY));
        if (den === 0) return 0;
        return num / den;
    }

    const r1 = getPearson(xIdx, y1Idx);
    const r2 = getPearson(xIdx, y2Idx);

    const resultDiv = document.getElementById('correlation-result');
    let html = "";
    let found = false;
    if (r1 !== null) {
        html += `<div style="margin-bottom: 2px;">• <b>${chartConfig.x}</b> vs <b>${chartConfig.y}</b>: <span style="color: #3b82f6; font-weight: 700;">${r1.toFixed(4)}</span></div>`;
        found = true;
    }
    if (r2 !== null) {
        html += `<div>• <b>${chartConfig.x}</b> vs <b>${chartConfig.y2}</b>: <span style="color: #06b6d4; font-weight: 700;">${r2.toFixed(4)}</span></div>`;
        found = true;
    }

    if (!found) {
        resultDiv.innerHTML = '<span style="color: #94a3b8; font-size: 12px;">(無法計算：需為數值欄位)</span>';
    } else {
        resultDiv.innerHTML = html;
    }
}
