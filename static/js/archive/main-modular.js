/**
 * Sigma2 主入口 - 完整模組化版本
 * 
 * 架構說明：
 * - 所有模組透過 window.Sigma2 命名空間管理
 * - 避免全域變數污染
 * - 各功能模組獨立，修改一個不影響其他
 */

import { SessionManager } from './modules/session.js';
import { Utils } from './modules/utils.js';
import { FileManager } from './modules/file-manager.js';
import { ChartsManager } from './modules/charts.js';
import { DashboardManager } from './modules/dashboard.js';
import { AnalysisManager } from './modules/analysis.js';
import { AIAssistant } from './modules/ai-assistant.js';

// 初始化 Sigma2 命名空間
window.Sigma2 = window.Sigma2 || {};

// 初始化所有模組
document.addEventListener('DOMContentLoaded', () => {
    console.log('🚀 Sigma2 完整模組化系統初始化中...');

    try {
        // 1. Session 管理
        window.Sigma2.session = new SessionManager();
        console.log('✅ Session 管理模組已載入');

        // 2. 工具函數
        window.Sigma2.utils = Utils;
        console.log('✅ 工具函數模組已載入');

        // 3. 圖表管理（需要在 Dashboard 之前）
        window.Sigma2.charts = new ChartsManager();
        window.Sigma2.charts.initCharts();
        console.log('✅ 圖表管理模組已載入');

        // 4. Dashboard 即時看板
        window.Sigma2.dashboard = new DashboardManager(
            window.Sigma2.session,
            window.Sigma2.charts
        );
        console.log('✅ Dashboard 模組已載入');

        // 5. 檔案管理
        window.Sigma2.fileManager = new FileManager(window.Sigma2.session);
        window.Sigma2.fileManager.setupDropzone();
        window.Sigma2.fileManager.loadFileList();
        console.log('✅ 檔案管理模組已載入');

        // 6. 數據分析
        window.Sigma2.analysis = new AnalysisManager(window.Sigma2.session);
        console.log('✅ 數據分析模組已載入');

        // 7. AI 助手
        window.Sigma2.aiAssistant = new AIAssistant(window.Sigma2.session);
        window.Sigma2.aiAssistant.setupEventListeners();
        console.log('✅ AI 助手模組已載入');

        // 初始化 User UI
        if (window.Sigma2.session) {
            const sidSpan = document.getElementById('current-user-id');
            if (sidSpan) sidSpan.innerText = window.Sigma2.session.getSessionId();
        }

        console.log('✨ Sigma2 完整模組化系統初始化完成！');
        console.log('📦 已載入模組:', Object.keys(window.Sigma2));
        console.log('');
        console.log('📘 模組說明：');
        console.log('  • Sigma2.session      - Session 管理');
        console.log('  • Sigma2.utils        - 工具函數');
        console.log('  • Sigma2.charts       - 圖表管理');
        console.log('  • Sigma2.dashboard    - 即時看板');
        console.log('  • Sigma2.fileManager  - 檔案管理');
        console.log('  • Sigma2.analysis     - 數據分析');
        console.log('  • Sigma2.aiAssistant  - AI 助手');
        console.log('');
        console.log('🎯 優勢：各模組獨立，修改一個不影響其他！');

    } catch (error) {
        console.error('❌ 模組初始化失敗:', error);
    }
});

// 匯出供外部使用
export default window.Sigma2;

// 全域功能
// 全域功能
// 全域功能
window.switchUser = function () {
    const defaultSid = 'default';
    let currentSid = defaultSid;

    if (window.Sigma2 && window.Sigma2.session && typeof window.Sigma2.session.getSessionId === 'function') {
        currentSid = window.Sigma2.session.getSessionId();
    } else {
        currentSid = localStorage.getItem("sigma2_session_id") || defaultSid;
    }

    const newSid = prompt("請輸入您的 User ID (Session ID):\n\n輸入 'default' 可檢視舊版檔案。", currentSid);

    if (newSid && newSid.trim() !== "") {
        const sidToSet = newSid.trim();

        if (window.Sigma2 && window.Sigma2.session && typeof window.Sigma2.session.setSessionId === 'function') {
            window.Sigma2.session.setSessionId(sidToSet);
        } else {
            console.warn("setSessionId method missing or module validation failed. Writing to localStorage directly.");
            localStorage.setItem("sigma2_session_id", sidToSet);
        }

        alert(`身份已切換為: ${sidToSet}\n頁面即將重整...`);
        window.location.reload();
    }
};

// UI 互動功能 (委派給 Dashboard 或其他模組)
window.openFileSelector = function () {
    if (window.Sigma2 && window.Sigma2.dashboard) window.Sigma2.dashboard.openFileSelector();
};
window.closeFileSelector = function () {
    if (window.Sigma2 && window.Sigma2.dashboard) window.Sigma2.dashboard.closeFileSelector();
};
window.confirmFileSelection = function () {
    if (window.Sigma2 && window.Sigma2.dashboard) window.Sigma2.dashboard.confirmFileSelection();
};
window.toggleSidebar = function () {
    document.getElementById('sidebar').classList.toggle('collapsed');
    document.querySelector('.main-view-area').classList.toggle('expanded');
};
window.toggleAssistant = function () {
    if (window.Sigma2 && window.Sigma2.aiAssistant) window.Sigma2.aiAssistant.toggleAssistant();
};
window.toggleChartAssistant = function () {
    if (window.Sigma2 && window.Sigma2.aiAssistant) window.Sigma2.aiAssistant.toggleChartAssistant();
};
window.openDashboardChatPopup = function () {
    if (window.Sigma2 && window.Sigma2.aiAssistant) window.Sigma2.aiAssistant.openDashboardChatPopup();
};
window.openChartChatPopup = function () {
    if (window.Sigma2 && window.Sigma2.aiAssistant) window.Sigma2.aiAssistant.openChartChatPopup();
};
window.generateAIReport = function () {
    if (window.Sigma2 && window.Sigma2.aiAssistant) window.Sigma2.aiAssistant.generateAIReport();
};
window.generateChartAIReport = function () {
    if (window.Sigma2 && window.Sigma2.aiAssistant) window.Sigma2.aiAssistant.generateChartAIReport();
};
window.switchView = function (viewName) {
    if (window.Sigma2 && window.Sigma2.utils) window.Sigma2.utils.switchView(viewName);
};
