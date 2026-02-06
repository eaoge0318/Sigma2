// 檔案管理模組
export class FileManager {
    constructor(sessionManager) {
        this.sessionManager = sessionManager;
    }

    async uploadFile(file) {
        const statusDiv = document.getElementById('upload-status');
        statusDiv.innerText = `⏳ 正在上傳 ${file.name}...`;
        statusDiv.style.color = '#3b82f6';

        const formData = new FormData();
        formData.append('file', file);
        formData.append('session_id', this.sessionManager.getSessionId());

        try {
            const res = await fetch('/api/upload_file', {
                method: 'POST',
                body: formData
            });
            const data = await res.json();

            if (res.ok) {
                statusDiv.innerText = `✅ ${data.message}`;
                statusDiv.style.color = '#22c55e';
                this.loadFileList();
            } else {
                statusDiv.innerText = `❌ 上傳失敗: ${data.detail}`;
                statusDiv.style.color = '#ef4444';
            }
        } catch (err) {
            statusDiv.innerText = `❌ 上傳錯誤: ${err.message}`;
            statusDiv.style.color = '#ef4444';
        }
    }

    async deleteFile(filename) {
        if (!confirm(`確定要刪除 ${filename} 嗎？`)) return;

        try {
            const sid = this.sessionManager.getSessionId();
            const res = await fetch(`/api/delete_file/${filename}?session_id=${sid}`, { method: 'DELETE' });
            const data = await res.json();
            if (res.ok) {
                this.loadFileList();
            } else {
                alert(`刪除失敗: ${data.detail}`);
            }
        } catch (err) {
            alert(`錯誤: ${err.message}`);
        }
    }

    async viewFile(filename) {
        try {
            const sid = this.sessionManager.getSessionId();
            const res = await fetch(`/api/view_file/${filename}?session_id=${sid}`);
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

    async trainModel(filename) {
        try {
            alert(`🚀 正在對 ${filename} 啟動訓練任務...\\n(Mock 模式)`);
            const sid = this.sessionManager.getSessionId();
            const res = await fetch(`/api/train_model?session_id=${sid}`, {
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

    async loadFileList() {
        const tbody = document.getElementById('file-list-body');
        try {
            const sid = this.sessionManager.getSessionId();
            const res = await fetch(`/api/list_files?session_id=${sid}`);
            const data = await res.json();

            tbody.innerHTML = '';
            if (data.files.length === 0) {
                tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: #94a3b8;">尚無已上傳檔案</td></tr>';
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
                            <button onclick="window.Sigma2.analysis.analyzeFile('${f.filename}')" class="action-btn btn-view">資料</button>
                            <button onclick="window.Sigma2.fileManager.trainModel('${f.filename}')" class="action-btn btn-train">訓練</button>
                            <button onclick="window.Sigma2.fileManager.deleteFile('${f.filename}')" class="action-btn btn-delete">刪除</button>
                        </div>
                    </td>
                `;
                tbody.appendChild(tr);
            });
        } catch (err) {
            tbody.innerHTML = `<tr><td colspan="4" style="color: red;">無法載入列表: ${err.message}</td></tr>`;
        }
    }

    openUploadModal() {
        document.getElementById('uploadModal').classList.add('show');
        document.getElementById('upload-status').innerText = '';
    }

    closeUploadModal() {
        document.getElementById('uploadModal').classList.remove('show');
    }

    closeViewModal() {
        document.getElementById('viewDataModal').classList.remove('show');
    }

    handleMainFileUpload(input) {
        if (input.files.length > 0) {
            this.uploadFile(input.files[0]);
        }
    }

    setupDropzone() {
        const dropzone = document.getElementById('upload-dropzone');
        if (!dropzone) return;

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
                const fileName = file.name.toLowerCase();
                if (fileName.endsWith('.csv') || fileName.endsWith('.xlsx') || fileName.endsWith('.xls')) {
                    this.uploadFile(file);
                } else {
                    const statusDiv = document.getElementById('upload-status');
                    statusDiv.innerText = "❌ 僅支援 CSV、Excel (.xlsx, .xls) 格式檔案";
                    statusDiv.style.color = '#ef4444';
                }
            }
        });
    }
}

// 掛載到 window 供 HTML 調用
window.handleMainFileUpload = function (input) {
    if (window.Sigma2 && window.Sigma2.fileManager) {
        window.Sigma2.fileManager.handleMainFileUpload(input);
    }
};
window.openUploadModal = function () {
    if (window.Sigma2 && window.Sigma2.fileManager) {
        window.Sigma2.fileManager.openUploadModal();
    }
};
window.closeUploadModal = function () {
    if (window.Sigma2 && window.Sigma2.fileManager) {
        window.Sigma2.fileManager.closeUploadModal();
    }
};
window.closeViewModal = function () {
    if (window.Sigma2 && window.Sigma2.fileManager) {
        window.Sigma2.fileManager.closeViewModal();
    }
};
window.deleteFile = function (filename) {
    if (window.Sigma2 && window.Sigma2.fileManager) {
        window.Sigma2.fileManager.deleteFile(filename);
    }
};
window.viewFile = function (filename) {
    if (window.Sigma2 && window.Sigma2.fileManager) {
        window.Sigma2.fileManager.viewFile(filename);
    }
};
window.trainModel = function (filename) {
    if (window.Sigma2 && window.Sigma2.fileManager) {
        window.Sigma2.fileManager.trainModel(filename);
    }
};
