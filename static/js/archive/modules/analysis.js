// 數據分析模組 - 管理數據表格、過濾、排序和高級分析
export class AnalysisManager {
    constructor(sessionManager) {
        this.sessionManager = sessionManager;
        this.currentPage = 1;
        this.filename = '';
        this.originalTableData = [];
        this.tableHeaders = [];
        this.currentSortColumn = -1;
        this.currentSortOrder = 'asc';
        this.activeFilters = [];
        this.totalLines = 0;
        this.visibleColumnIndices = [];
        this.latestImportantFactors = [];
    }

    async analyzeFile(filename) {
        this.filename = filename;
        this.originalTableData = [];
        this.activeFilters = [];
        this.latestImportantFactors = [];

        // 切換到分析視圖
        if (window.Sigma2 && window.Sigma2.utils) {
            window.Sigma2.utils.switchView('analysis');
        }

        // 重置 UI
        this.clearChartConfig();
        this.resetAdvancedResults();
        this.switchAnalysisMode('table');

        // 載入數據
        await this.loadAnalysisPage(-1);
    }

    async loadAnalysisPage(page) {
        this.currentPage = page;
        document.getElementById('analysis-filename').innerText = this.filename;
        const contentDiv = document.getElementById('analysis-content');

        if (this.originalTableData.length === 0 || page === -1) {
            contentDiv.innerHTML = '<div style="text-align: center; color: #64748b; padding: 40px;">⏳ 正在載入數據...</div>';

            try {
                // 獲取檔案資訊
                const sid = this.sessionManager.getSessionId();
                const infoRes = await fetch(`/api/view_file/${this.filename}?page=1&page_size=1&session_id=${sid}`);
                const infoData = await infoRes.json();
                this.totalLines = infoData.total_lines || 0;
                document.getElementById('analysis-header-count').innerText = `(總計 ${this.totalLines - 1} 筆數據)`;

                if (this.filename.toLowerCase().endsWith('.csv')) {
                    this.tableHeaders = infoData.content.trim().split('\n')[0].split(',').map(h => h.trim());
                    this.visibleColumnIndices = this.tableHeaders.map((_, i) => i);

                    // 載入全量數據
                    const fullRes = await fetch(`/api/view_file/${this.filename}?page=1&page_size=1000000&session_id=${sid}`);
                    const fullData = await fullRes.json();
                    const lines = fullData.content.trim().split('\n');
                    this.originalTableData = lines.slice(1).map((row, idx) => {
                        const arr = row.split(',').map(c => c.trim());
                        arr.__idx = idx;
                        return arr;
                    });
                } else {
                    // 非 CSV 格式直接預覽
                    const res = await fetch(`/api/view_file/${this.filename}?page=1&page_size=5000&session_id=${sid}`);
                    const data = await res.json();
                    contentDiv.innerHTML = `<div class="analysis-table-container"><pre style="font-family: monospace; white-space: pre-wrap; padding: 15px;">${data.content}</pre></div>`;
                    this.renderPagination(1, this.totalLines, 0);
                    return;
                }
            } catch (err) {
                contentDiv.innerHTML = `<div style="color: red; text-align: center; padding: 40px;">載入失敗: ${err.message}</div>`;
                return;
            }
        }

        this.currentPage = page === -1 ? 1 : page;
        this.renderTable(this.tableHeaders, this.originalTableData, this.currentPage, this.totalLines);
        this.updateFilterBar();
    }

    renderTable(headers, rows, currentPage, totalLines) {
        const filteredRows = this.getFilteredRows(rows);

        // 更新計數
        const headerCount = document.getElementById('analysis-header-count');
        if (headerCount) {
            headerCount.innerHTML = `(目前顯示: <b style="color: #3b82f6;">${filteredRows.length}</b> / 總計: ${totalLines - 1})`;
        }

        // 排序
        if (this.currentSortColumn !== -1) {
            filteredRows.sort((a, b) => {
                let valA = a[this.currentSortColumn] || '';
                let valB = b[this.currentSortColumn] || '';
                if (!isNaN(valA) && !isNaN(valB) && valA !== "" && valB !== "") {
                    return this.currentSortOrder === 'asc' ? Number(valA) - Number(valB) : Number(valB) - Number(valA);
                }
                return this.currentSortOrder === 'asc' ? valA.localeCompare(valB) : valB.localeCompare(valA);
            });
        }

        // 分頁
        const pageSize = 100;
        const totalPages = Math.ceil(filteredRows.length / pageSize);
        if (currentPage > totalPages && totalPages > 0) currentPage = 1;
        if (currentPage < 1) currentPage = 1;

        const start = (currentPage - 1) * pageSize;
        const end = start + pageSize;
        const rowsToDisplay = filteredRows.slice(start, end);

        // 渲染表格
        let html = '<div class="analysis-table-container"><table class="analysis-table"><thead><tr>';

        this.visibleColumnIndices.forEach(idx => {
            const h = headers[idx];
            const sortIcon = this.currentSortColumn === idx ? (this.currentSortOrder === 'asc' ? ' 🔼' : ' 🔽') : '';
            html += `<th onclick="window.Sigma2.analysis.handleSort(${idx}, '${h}')">${h}${sortIcon}</th>`;
        });

        html += '</tr></thead><tbody>';

        rowsToDisplay.forEach(row => {
            html += '<tr>';
            this.visibleColumnIndices.forEach(idx => {
                html += `<td>${row[idx] || ''}</td>`;
            });
            html += '</tr>';
        });

        if (rowsToDisplay.length === 0) {
            html += `<tr><td colspan="${headers.length}" style="text-align: center; padding: 40px; color: #94a3b8;">無符合篩選條件的數據</td></tr>`;
        }

        html += '</tbody></table></div>';
        document.getElementById('analysis-content').innerHTML = html;

        this.renderPagination(currentPage, totalLines, filteredRows.length);
    }

    getFilteredRows(data) {
        if (!data) return [];
        return data.filter(row => {
            return this.activeFilters.every(f => {
                const cellVal = row[f.colIdx];
                if (f.type === 'not_empty') return cellVal && cellVal.trim() !== '';
                if (f.type === 'range') {
                    const num = parseFloat(cellVal);
                    return !isNaN(num) && num >= f.min && num <= f.max;
                }
                const rowVal = cellVal ? cellVal.toLowerCase() : '';
                return rowVal.includes(f.value.toLowerCase());
            });
        });
    }

    renderPagination(currentPage, totalLines, filteredCount) {
        const pageSize = 100;
        const totalPages = Math.ceil(filteredCount / pageSize);
        const paginationDiv = document.getElementById('analysis-pagination');

        if (!paginationDiv) return;

        let html = `<span>第 ${currentPage} / ${totalPages} 頁</span>`;
        html += `<button onclick="window.Sigma2.analysis.loadAnalysisPage(${currentPage - 1})" ${currentPage <= 1 ? 'disabled' : ''}>上一頁</button>`;
        html += `<button onclick="window.Sigma2.analysis.loadAnalysisPage(${currentPage + 1})" ${currentPage >= totalPages ? 'disabled' : ''}>下一頁</button>`;

        paginationDiv.innerHTML = html;
    }

    handleSort(colIdx, colName) {
        if (this.currentSortColumn === colIdx) {
            this.currentSortOrder = this.currentSortOrder === 'asc' ? 'desc' : 'asc';
        } else {
            this.currentSortColumn = colIdx;
            this.currentSortOrder = 'asc';
        }
        this.renderTable(this.tableHeaders, this.originalTableData, this.currentPage, this.totalLines);
    }

    addFilter(colIdx, colName, value, type = 'text') {
        this.activeFilters.push({ colIdx, colName, value, type });
        this.updateFilterBar();
        this.renderTable(this.tableHeaders, this.originalTableData, this.currentPage, this.totalLines);
    }

    removeFilter(index) {
        this.activeFilters.splice(index, 1);
        this.updateFilterBar();
        this.renderTable(this.tableHeaders, this.originalTableData, this.currentPage, this.totalLines);
    }

    updateFilterBar() {
        const bar = document.getElementById('filter-bar-area');
        if (!bar) return;

        const existingPills = bar.querySelectorAll('.filter-pill');
        existingPills.forEach(p => p.remove());

        this.activeFilters.forEach((f, idx) => {
            const pill = document.createElement('div');
            pill.className = 'filter-pill';
            let displayText = f.value;
            if (f.type === 'not_empty') displayText = '移除空值';
            if (f.type === 'range') displayText = `${f.min.toFixed(2)} ~ ${f.max.toFixed(2)}`;

            pill.innerHTML = `
                <span style="font-weight:600;">${f.colName}:</span> <span>${displayText}</span>
                <span class="remove-pill" onclick="window.Sigma2.analysis.removeFilter(${idx})">&times;</span>
            `;
            bar.appendChild(pill);
        });
    }

    switchAnalysisMode(mode) {
        const modes = ['table', 'chart', 'advanced'];
        modes.forEach(m => {
            const view = document.getElementById(`analysis-mode-${m}`);
            const btn = document.getElementById(`btn-mode-${m}`);
            if (view) view.style.display = m === mode ? 'block' : 'none';
            if (btn) btn.classList.toggle('active', m === mode);
        });
    }

    clearChartConfig() {
        // 清除圖表配置
        console.log('Chart config cleared');
    }

    resetAdvancedResults() {
        // 重置高級分析結果
        const resultsDiv = document.getElementById('advanced-results');
        if (resultsDiv) resultsDiv.innerHTML = '';
    }

    //===== 高級分析功能（簡化版，可擴展） =====
    async performAdvancedAnalysis() {
        const resultsDiv = document.getElementById('advanced-results');
        if (!resultsDiv) return;

        resultsDiv.innerHTML = '<div style="text-align: center; padding: 20px;">⏳ 分析中...</div>';

        try {
            const sid = this.sessionManager.getSessionId();
            const response = await fetch(`/api/advanced_analysis?session_id=${sid}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    filename: this.filename,
                    filters: this.activeFilters
                })
            });
            const data = await response.json();

            resultsDiv.innerHTML = `
                <div class="analysis-results">
                    <h3>分析結果</h3>
                    <pre>${JSON.stringify(data, null, 2)}</pre>
                </div>
            `;
        } catch (err) {
            resultsDiv.innerHTML = `<div style="color: red;">分析失敗: ${err.message}</div>`;
        }
    }
}

// 掛載到 window 供 HTML 調用
window.analyzeFile = function (filename) {
    if (window.Sigma2 && window.Sigma2.analysis) {
        window.Sigma2.analysis.analyzeFile(filename);
    }
};
window.loadAnalysisPage = function (page) {
    if (window.Sigma2 && window.Sigma2.analysis) {
        window.Sigma2.analysis.loadAnalysisPage(page);
    }
};
window.handleSort = function (colIdx, colName) {
    if (window.Sigma2 && window.Sigma2.analysis) {
        window.Sigma2.analysis.handleSort(colIdx, colName);
    }
};
window.switchAnalysisMode = function (mode) {
    if (window.Sigma2 && window.Sigma2.analysis) {
        window.Sigma2.analysis.switchAnalysisMode(mode);
    }
};
