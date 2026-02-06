// 共用工具函數模組
export class Utils {
    // View 切換
    static switchView(viewName) {
        // Update Nav State
        document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
        const navItem = document.getElementById('nav-' + viewName);
        if (navItem) navItem.classList.add('active');

        // Toggle Views
        const dashboardView = document.getElementById('view-dashboard');
        const filesView = document.getElementById('view-files');
        const analysisView = document.getElementById('view-analysis');

        if (viewName === 'dashboard') {
            dashboardView.style.display = 'block';
            filesView.style.display = 'none';
            analysisView.style.display = 'none';

            // Trigger chart resize after layout change
            setTimeout(() => {
                if (window.Sigma2 && window.Sigma2.charts) {
                    window.Sigma2.charts.resizeAll();
                }
            }, 50);

        } else if (viewName === 'analysis') {
            dashboardView.style.display = 'none';
            filesView.style.display = 'none';
            analysisView.style.display = 'block';
        } else {
            dashboardView.style.display = 'none';
            filesView.style.display = 'block';
            analysisView.style.display = 'none';
            if (window.Sigma2 && window.Sigma2.fileManager) {
                window.Sigma2.fileManager.loadFileList();
            }
        }
    }

    // Sidebar 切換
    static toggleSidebar() {
        const sidebar = document.getElementById('sidebar');

        if (sidebar.classList.contains('collapsed')) {
            sidebar.classList.remove('collapsed');
            document.body.classList.remove('sidebar-collapsed');
        } else {
            sidebar.classList.add('collapsed');
            document.body.classList.add('sidebar-collapsed');
        }

        // Trigger chart resize after transition (300ms)
        setTimeout(() => {
            if (window.Sigma2 && window.Sigma2.charts) {
                window.Sigma2.charts.resizeAll();
            }
        }, 350);
    }

    // 格式化檔案大小
    static formatFileSize(bytes) {
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1048576) return (bytes / 1024).toFixed(2) + ' KB';
        return (bytes / 1048576).toFixed(2) + ' MB';
    }

    // 格式化日期時間
    static formatDateTime(timestamp) {
        const date = new Date(timestamp);
        return date.toLocaleString('zh-TW');
    }
}

// 掛載到 window 供 HTML 調用
window.switchView = Utils.switchView;
window.toggleSidebar = Utils.toggleSidebar;
