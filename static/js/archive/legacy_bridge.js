/**
 * Legacy Bridge Script
 * 
 * 此腳本負責定義全域函數，確保在模組載入前 HTML 的 onclick 事件不會報錯。
 * 若模組尚未載入，則顯示載入中提示。
 * 若模組已載入，則轉發請求。
 */

console.log("🌉 Legacy Bridge Initializing...");

function safeCall(moduleName, methodName, ...args) {
    if (window.Sigma2 && window.Sigma2[moduleName] && typeof window.Sigma2[moduleName][methodName] === 'function') {
        return window.Sigma2[moduleName][methodName](...args);
    } else {
        console.warn(`⏳ 模組 ${moduleName} 尚未就緒，無法執行 ${methodName}`);
        // 嘗試從備用入口執行 (Failsafe)
        if (moduleName === 'fileManager' && window.Sigma2.failsafeFileManager) {
            return window.Sigma2.failsafeFileManager[methodName](...args);
        }
        alert("系統模組正在載入中，請稍候再試...");
    }
}

// === 檔案管理相關 ===
window.openFileSelector = function () {
    if (window.Sigma2 && window.Sigma2.dashboard) {
        window.Sigma2.dashboard.openFileSelector();
    } else {
        // Fallback checks
        alert("儀表板模組尚未載入");
    }
};

window.closeFileSelector = function () { safeCall('dashboard', 'closeFileSelector'); };
window.confirmFileSelection = function () { safeCall('dashboard', 'confirmFileSelection'); };

window.handleMainFileUpload = function (input) { safeCall('fileManager', 'handleMainFileUpload', input); };
window.openUploadModal = function () { safeCall('fileManager', 'openUploadModal'); };
window.closeUploadModal = function () { safeCall('fileManager', 'closeUploadModal'); };
window.closeViewModal = function () { safeCall('fileManager', 'closeViewModal'); };
window.deleteFile = function (f) { safeCall('fileManager', 'deleteFile', f); };
window.viewFile = function (f) { safeCall('fileManager', 'viewFile', f); };
window.trainModel = function (f) { safeCall('fileManager', 'trainModel', f); };

// === 分析相關 ===
window.analyzeFile = function (f) { safeCall('analysis', 'analyzeFile', f); };
window.loadAnalysisPage = function (p) { safeCall('analysis', 'loadAnalysisPage', p); };
window.handleSort = function (c, n) { safeCall('analysis', 'handleSort', c, n); };
window.switchAnalysisMode = function (m) { safeCall('analysis', 'switchAnalysisMode', m); };

// === 介面相關 ===
window.toggleSidebar = function () {
    const sb = document.getElementById('sidebar');
    const mv = document.querySelector('.main-view-area');
    if (sb) sb.classList.toggle('collapsed');
    if (mv) mv.classList.toggle('expanded');
};

window.toggleAssistant = function () { safeCall('aiAssistant', 'toggleAssistant'); };
window.toggleChartAssistant = function () { safeCall('aiAssistant', 'toggleChartAssistant'); };
window.openDashboardChatPopup = function () { safeCall('aiAssistant', 'openDashboardChatPopup'); };
window.openChartChatPopup = function () { safeCall('aiAssistant', 'openChartChatPopup'); };
window.generateAIReport = function () { safeCall('aiAssistant', 'generateAIReport'); };
window.generateChartAIReport = function () { safeCall('aiAssistant', 'generateChartAIReport'); };
window.switchView = function (v) { safeCall('utils', 'switchView', v); };

console.log("🌉 Legacy Bridge Ready.");
