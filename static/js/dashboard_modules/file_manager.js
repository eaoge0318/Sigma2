import { DOM, API, WINDOW_SIZE } from './utils.js';
// We assume these will be available globally or imported in main
// import { analyzeFile } from './analysis_manager.js';
// import { trainModel } from './training_manager.js';
// import { switchView } from './ui_core.js';

let fileListCurrentPage = 1;
const FILE_LIST_PAGE_SIZE = 10;
let tempModalFileSelection = null;
let fileSelectorPurpose = 'analysis';
let selectedFiles = []; // For chat preview

export function handleMainFileUpload(input) {
    for (let i = 0; i < input.files.length; i++) {
        uploadFile(input.files[i]);
    }
}

export function handleDroppedFiles(files) {
    const allowed = ['.csv', '.xml', '.xlsx', '.xls'];
    for (let i = 0; i < files.length; i++) {
        const file = files[i];
        const ext = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
        if (!allowed.includes(ext)) {
            const statusDiv = DOM.get('upload-status');
            if (statusDiv) {
                statusDiv.innerText = `不支援的格式: ${ext}，僅支援 CSV, XML, Excel`;
                statusDiv.style.color = '#ef4444';
            }
            continue;
        }
        uploadFile(file);
    }
}

export async function uploadFile(file) {
    const statusDiv = DOM.get('upload-status');
    if (!statusDiv) return;

    statusDiv.innerText = `⏳ 正在上傳 ${file.name}...`;
    statusDiv.style.color = '#3b82f6';

    const formData = new FormData();
    formData.append('file', file);
    // Ensure SESSION_ID is available
    const sid = window.SESSION_ID || localStorage.getItem("sigma2_session_id");
    formData.append('session_id', sid);

    try {
        const res = await fetch('/api/upload_file', {
            method: 'POST',
            body: formData
        });
        const data = await res.json();

        if (res.ok) {
            // Multi-sheet Excel: show sheet selection dialog
            if (data.needs_sheet_selection && data.sheets) {
                statusDiv.innerText = `📑 Excel 包含 ${data.sheets.length} 個工作表，請選擇`;
                statusDiv.style.color = '#f59e0b';
                showSheetSelector(data.filename, data.sheets, sid);
                return;
            }
            statusDiv.innerText = `✅ ${data.filename} 上傳成功`;
            statusDiv.style.color = '#22c55e';
            await loadFileList(); // Refresh list
        } else {
            statusDiv.innerText = `❌ 上傳失敗: ${data.detail}`;
            statusDiv.style.color = '#ef4444';
        }
    } catch (err) {
        statusDiv.innerText = `❌ 上傳錯誤: ${err.message}`;
        statusDiv.style.color = '#ef4444';
    }
}

function showSheetSelector(filename, sheets, sessionId) {
    // Close upload modal so dialog is visible
    if (typeof closeUploadModal === 'function') closeUploadModal();
    let existing = document.getElementById('sheet-selector-modal');
    if (existing) existing.remove();

    const overlay = document.createElement('div');
    overlay.id = 'sheet-selector-modal';
    overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.45);z-index:10001;display:flex;align-items:center;justify-content:center;';

    let html = `<div style="background:#fff;border-radius:14px;padding:28px;min-width:420px;max-width:540px;box-shadow:0 24px 64px rgba(0,0,0,0.25);">
        <h3 style="margin:0 0 6px;font-size:17px;color:#1e293b;">📑 選擇要匯入的工作表</h3>
        <p style="margin:0 0 4px;font-size:12px;color:#94a3b8;">${filename} — ${sheets.length} 個工作表（可多選）</p>
        <div style="display:flex;gap:8px;margin-bottom:12px;">
            <a href="#" id="sSelectAll" style="font-size:11px;color:#818cf8;text-decoration:none;">全選</a>
            <a href="#" id="sSelectNone" style="font-size:11px;color:#818cf8;text-decoration:none;">全不選</a>
        </div>
        <div style="max-height:340px;overflow-y:auto;padding-right:4px;">`;

    sheets.forEach((s, i) => {
        html += `<label class="sheet-opt" style="padding:10px 14px;border:1.5px solid #e2e8f0;border-radius:8px;margin-bottom:6px;cursor:pointer;transition:all 0.15s;display:flex;align-items:center;gap:10px;"
            onmouseenter="this.style.background='#f8fafc'" onmouseleave="if(!this.querySelector('input').checked)this.style.background='#fff'">
            <input type="checkbox" value="${s.name.replace(/"/g, '&quot;')}" style="width:16px;height:16px;accent-color:#818cf8;flex-shrink:0;">
            <div style="flex:1;min-width:0;">
                <div style="font-weight:600;color:#334155;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${s.name}</div>
                <div style="font-size:11px;color:#94a3b8;margin-top:1px;">${s.rows.toLocaleString()} 筆 × ${s.cols} 欄</div>
            </div>
            <span style="font-size:11px;color:#cbd5e1;flex-shrink:0;">${i + 1}</span>
        </label>`;
    });

    html += `</div>
        <div style="display:flex;gap:8px;margin-top:16px;justify-content:flex-end;align-items:center;">
            <span id="sCount" style="font-size:12px;color:#94a3b8;margin-right:auto;">已選 0 個</span>
            <button id="sCancel" style="padding:8px 16px;border:1px solid #e2e8f0;border-radius:8px;background:#fff;color:#64748b;font-size:13px;cursor:pointer;">取消</button>
            <button id="sConfirm" disabled style="padding:8px 20px;border:none;border-radius:8px;background:#818cf8;color:#fff;font-size:13px;font-weight:600;cursor:pointer;opacity:0.5;">匯入選定工作表</button>
        </div></div>`;

    overlay.innerHTML = html;
    document.body.appendChild(overlay);

    const cfm = overlay.querySelector('#sConfirm');
    const countEl = overlay.querySelector('#sCount');
    const checkboxes = overlay.querySelectorAll('input[type="checkbox"]');

    function updateCount() {
        const n = overlay.querySelectorAll('input[type="checkbox"]:checked').length;
        countEl.textContent = `已選 ${n} 個`;
        cfm.disabled = n === 0;
        cfm.style.opacity = n > 0 ? '1' : '0.5';
        overlay.querySelectorAll('.sheet-opt').forEach(o => {
            const cb = o.querySelector('input');
            o.style.borderColor = cb.checked ? '#818cf8' : '#e2e8f0';
            o.style.background = cb.checked ? '#f5f3ff' : '#fff';
        });
    }
    checkboxes.forEach(cb => cb.addEventListener('change', updateCount));
    overlay.querySelector('#sSelectAll').addEventListener('click', e => { e.preventDefault(); checkboxes.forEach(cb => cb.checked = true); updateCount(); });
    overlay.querySelector('#sSelectNone').addEventListener('click', e => { e.preventDefault(); checkboxes.forEach(cb => cb.checked = false); updateCount(); });
    if (checkboxes.length > 0) { checkboxes[0].checked = true; updateCount(); }

    overlay.querySelector('#sCancel').addEventListener('click', () => overlay.remove());
    cfm.addEventListener('click', async () => {
        const selected = Array.from(overlay.querySelectorAll('input[type="checkbox"]:checked')).map(cb => cb.value);
        if (selected.length === 0) return;
        cfm.textContent = '⏳ 匯入中...'; cfm.disabled = true;

        let successCount = 0, failMsg = '';
        for (let si = 0; si < selected.length; si++) {
            const sheetName = selected[si];
            const isLast = si === selected.length - 1;
            const form = new FormData();
            form.append('filename', filename);
            form.append('sheet_name', sheetName);
            form.append('session_id', sessionId);
            if (isLast) form.append('delete_excel', 'true');
            try {
                const resp = await fetch('/api/convert_sheet', { method: 'POST', body: form });
                if (resp.ok) successCount++;
                else { const r = await resp.json(); failMsg += `${sheetName}: ${r.detail}\n`; }
            } catch (err) { failMsg += `${sheetName}: ${err.message}\n`; }
        }
        overlay.remove();
        if (successCount > 0) {
            const toast = document.createElement('div');
            toast.style.cssText = 'position:fixed;top:20px;right:20px;background:#22c55e;color:#fff;padding:12px 20px;border-radius:10px;font-size:14px;font-weight:600;z-index:10002;box-shadow:0 4px 12px rgba(0,0,0,0.15);';
            toast.textContent = `✅ 已匯入 ${successCount} 個工作表`;
            document.body.appendChild(toast);
            setTimeout(() => toast.remove(), 3000);
            await loadFileList();
        }
        if (failMsg) alert('部分工作表匯入失敗:\n' + failMsg);
    });
}

export async function deleteFile(filename) {
    if (!confirm(`確定要刪除 ${filename} 嗎？`)) return;

    try {
        const sid = window.SESSION_ID || localStorage.getItem("sigma2_session_id");
        const res = await fetch(`/api/delete_file/${filename}?session_id=${sid}`, { method: 'DELETE' });
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

export async function viewFile(filename) {
    try {
        const sid = window.SESSION_ID || localStorage.getItem("sigma2_session_id");
        const res = await fetch(`/api/view_file/${filename}?session_id=${sid}`);
        const data = await res.json();
        if (res.ok) {
            DOM.setText('viewDataContent', data.content);
            DOM.setText('viewDataTitle', `預覽: ${filename}`);
            DOM.addClass('viewDataModal', 'show');
        } else {
            alert(`無法預覽: ${data.detail}`);
        }
    } catch (err) {
        alert(`錯誤: ${err.message}`);
    }
}

export function closeViewModal() {
    DOM.removeClass('viewDataModal', 'show');
}

export async function loadFileList() {
    const tbody = DOM.get('file-list-body');
    if (!tbody) return;

    try {
        const sid = window.SESSION_ID || localStorage.getItem("sigma2_session_id");
        const res = await fetch(`/api/list_files?session_id=${sid}`);
        const data = await res.json();

        tbody.innerHTML = '';
        if (data.files.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: #94a3b8;">尚無已上傳檔案</td></tr>';
            const paginationContainer = DOM.get('file-list-pagination');
            if (paginationContainer) paginationContainer.innerHTML = '';
            return;
        }

        // --- 分頁邏輯 ---
        const totalItems = data.files.length;
        const totalPages = Math.ceil(totalItems / FILE_LIST_PAGE_SIZE);

        if (fileListCurrentPage > totalPages) {
            fileListCurrentPage = Math.max(1, totalPages);
        }

        const startIdx = (fileListCurrentPage - 1) * FILE_LIST_PAGE_SIZE;
        const endIdx = startIdx + FILE_LIST_PAGE_SIZE;
        // DESC sort
        const sortedFiles = data.files.sort((a, b) => b.uploaded_at.localeCompare(a.uploaded_at));
        const displayedFiles = sortedFiles.slice(startIdx, endIdx);

        displayedFiles.forEach(f => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                        <td style="font-weight: bold;">${f.filename}</td>
                        <td style="color: #64748b;">${(f.size / 1024).toFixed(2)} KB</td>
                        <td style="color: #64748b;">${f.uploaded_at}</td>
                        <td>
                            <div style="display: flex; align-items: center;">
                                <button onclick="window.analyzeFile('${f.filename}')" class="action-btn btn-view">資料</button>
                                <button onclick="window.trainModel('${f.filename}')" class="action-btn btn-train">訓練</button>
                                <button onclick="window.deleteFile('${f.filename}')" class="action-btn btn-delete">刪除</button>
                            </div>
                        </td>
                    `;
            tbody.appendChild(tr);
        });

        renderFileListPagination(totalPages);

    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="4" style="color: red;">無法載入列表: ${err.message}</td></tr>`;
    }
}

function renderFileListPagination(totalPages) {
    const container = DOM.get('file-list-pagination');
    if (!container) return;

    if (totalPages <= 1) {
        container.innerHTML = '';
        return;
    }

    const btnStyle = "padding: 6px 14px; border: 1px solid #e2e8f0; border-radius: 6px; background: #fff; color: #64748b; font-size: 12px; font-weight: 600; cursor: pointer; transition: all 0.2s;";

    let html = '';
    html += `<button style="${btnStyle}" ${fileListCurrentPage === 1 ? 'disabled style="opacity:0.5; cursor:not-allowed;"' : `onclick="changeFileListPage(${fileListCurrentPage - 1})"`}>上一頁</button>`;
    html += `<span style="display: flex; align-items: center; gap: 5px; color: #64748b; font-size: 12px; margin: 0 10px;">
        第 ${fileListCurrentPage} / ${totalPages} 頁
    </span>`;
    html += `<button style="${btnStyle}" ${fileListCurrentPage === totalPages ? 'disabled style="opacity:0.5; cursor:not-allowed;"' : `onclick="changeFileListPage(${fileListCurrentPage + 1})"`}>下一頁</button>`;

    container.innerHTML = html;
}

export function changeFileListPage(newPage) {
    fileListCurrentPage = newPage;
    loadFileList();
}

export function openUploadModal() {
    DOM.addClass('uploadModal', 'show');
    DOM.setText('upload-status', '');
}

export function closeUploadModal() {
    DOM.removeClass('uploadModal', 'show');
}

export async function openFileSelector(purpose = 'analysis') {
    fileSelectorPurpose = purpose;
    const sid = window.SESSION_ID || localStorage.getItem("sigma2_session_id");
    const res = await fetch(`/api/list_files?session_id=${sid}`);
    const data = await res.json();
    const list = DOM.get('file-selector-list');
    list.innerHTML = '';
    tempModalFileSelection = null;

    const confirmBtn = DOM.get('btn-confirm-file');
    if (confirmBtn) {
        confirmBtn.disabled = true;
        confirmBtn.style.opacity = '0.5';
        confirmBtn.style.cursor = 'not-allowed';
    }

    if (data.files.length === 0) {
        list.innerHTML = `
            <div style="color: #94a3b8; text-align: center; padding: 30px 20px;">
                <div style="font-size: 24px; margin-bottom: 10px;">📂</div>
                <div style="font-size: 13px; margin-bottom: 20px;">尚無近期檔案</div>
                <button onclick="closeFileSelector(); switchView('files');" 
                        style="padding: 8px 16px; background: #3b82f6; color: white; border: none; border-radius: 6px; font-size: 12px; font-weight: 600; cursor: pointer; transition: all 0.2s;">
                    前往檔案管理上傳
                </button>
            </div>
        `;
    } else {
        data.files.sort((a, b) => b.uploaded_at.localeCompare(a.uploaded_at));
        const allFiles = data.files;

        allFiles.forEach(f => {
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
                const allItems = list.querySelectorAll('.file-item');
                allItems.forEach(el => {
                    el.style.background = 'transparent';
                    el.dataset.selected = 'false';
                });

                item.style.background = '#eff6ff';
                item.dataset.selected = 'true';
                tempModalFileSelection = f.filename;

                if (confirmBtn) {
                    confirmBtn.disabled = false;
                    confirmBtn.style.opacity = '1';
                    confirmBtn.style.cursor = 'pointer';
                }
            };

            item.onmouseenter = () => {
                if (item.dataset.selected !== 'true') item.style.background = '#f8fafc';
            };
            item.onmouseleave = () => {
                if (item.dataset.selected !== 'true') item.style.background = 'transparent';
            };

            let icon = '📄';
            if (f.filename.endsWith('.csv')) icon = '📊';
            if (f.filename.endsWith('.xlsx') || f.filename.endsWith('.xls')) icon = '📗';

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

        const footerLink = document.createElement('div');
        footerLink.style.padding = '15px';
        footerLink.style.textAlign = 'center';
        footerLink.style.borderTop = '1px dashed #e2e8f0';
        footerLink.style.marginTop = '10px';
        footerLink.innerHTML = `
            <button onclick="closeFileSelector(); switchView('files');" 
                    style="background: transparent; border: 1px solid #3b82f6; color: #3b82f6; padding: 6px 14px; border-radius: 6px; font-size: 11px; font-weight: 700; cursor: pointer; transition: all 0.2s;">
                &raquo; 查看所有檔案 (進入檔案管理)
            </button>
        `;
        list.appendChild(footerLink);
    }

    DOM.addClass('fileSelectorModal', 'show');
}

export function confirmFileSelection() {
    if (tempModalFileSelection) {
        if (fileSelectorPurpose === 'training') {
            if (window.trainModel) window.trainModel(tempModalFileSelection);
        } else {
            if (window.analyzeFile) window.analyzeFile(tempModalFileSelection);
        }
        closeFileSelector();
    }
}

export function closeFileSelector() {
    DOM.removeClass('fileSelectorModal', 'show');
}


export function handleFileSelect(input) {
    processFiles(input.files);
    input.value = "";
}

export function processFiles(files) {
    const preview = DOM.get('file-preview');
    if (!preview) return;
    if (files.length > 0) preview.style.display = 'flex';

    Array.from(files).forEach(file => {
        const reader = new FileReader();
        const item = document.createElement('div');
        item.className = 'preview-item';

        if (file.type.startsWith('image/')) {
            reader.onload = (e) => {
                item.innerHTML = `<img src="${e.target.result}"><div class="preview-remove" onclick="removeChatFile('${file.name}')">×</div>`;
                selectedFiles.push({ name: file.name, type: 'image', data: e.target.result.split(',')[1] });
                // We might need to export selectedFiles or provide a getter for chat
                // For now, attaching to window for quick access? No, cleaner to export.
            };
            reader.readAsDataURL(file);
        } else {
            reader.onload = (e) => {
                item.innerHTML = `<span>📄</span><div class="preview-remove" onclick="removeChatFile('${file.name}')">×</div>`;
                selectedFiles.push({ name: file.name, type: 'text', data: e.target.result });
            };
            reader.readAsText(file);
        }
        preview.appendChild(item);
    });
}

export function removeChatFile(name) {
    selectedFiles = selectedFiles.filter(f => f.name !== name);
    const preview = DOM.get('file-preview');
    if (!preview) return;
    preview.innerHTML = "";
    selectedFiles.forEach(f => {
        const item = document.createElement('div');
        item.className = 'preview-item';
        item.innerHTML = f.type === 'image' ? `<img src="data:image/png;base64,${f.data}">` : `<span>📄</span>`;
        item.innerHTML += `<div class="preview-remove" onclick="removeChatFile('${f.name}')">×</div>`;
        preview.appendChild(item);
    });
}

// Getter for chat module
export function getSelectedFiles() {
    return selectedFiles;
}
export function clearSelectedFiles() {
    selectedFiles = [];
    const preview = DOM.get('file-preview');
    if (preview) preview.innerHTML = '';
}
