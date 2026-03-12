
// =========================
// dashboard_main.js - Main Entry Point
// =========================
import { DOM, API, WINDOW_SIZE } from './dashboard_modules/utils.js';
import * as UI from './dashboard_modules/ui_core.js';
import * as Session from './dashboard_modules/session.js';
import * as Charts from './dashboard_modules/charts_manager.js';
import * as FileMgr from './dashboard_modules/file_manager.js';
import * as Analysis from './dashboard_modules/analysis_manager.js';
import * as Training from './dashboard_modules/training_manager.js';
import * as Models from './dashboard_modules/models_manager.js';
import * as Dashboard from './dashboard_modules/dashboard_render.js';
import * as Simulator from './dashboard_modules/simulator.js';
import * as Chat from './dashboard_modules/chat_manager.js';

// =========================
// Global Exposure (Bridge for HTML onclicks)
// =========================
window.DOM = DOM;
window.API = API;
window.SESSION_ID = Session.SESSION_ID;

// UI Core
window.toggleAssistant = UI.toggleAssistant;
window.toggleSidebar = UI.toggleSidebar;
window.switchView = UI.switchView;
window.switchTrainingMainTab = UI.switchTrainingMainTab;
window.switchTrainingSubTab = UI.switchTrainingSubTab;

// Dashboard Render
window.updateDashboard = Dashboard.updateDashboard;
window.renderDashboardData = Dashboard.renderDashboardData;

// Files (only fileSelectorModal/confirmFileSelection still used in parent for training)
window.openFileSelector = FileMgr.openFileSelector;
window.closeFileSelector = FileMgr.closeFileSelector;
window.confirmFileSelection = FileMgr.confirmFileSelection;

// Analysis (now in iframe — only analyzeFile needed for cross-iframe forwarding)
window.analyzeFile = Analysis.analyzeFile;

// Chat / AI
window.generateAIReport = Chat.generateAIReport;
window.sendChatMessage = Chat.sendChatMessage;
window.handleChatKey = Chat.handleChatKey;
window.handleFileSelect = Chat.handleFileSelect; // This overlaps with FileMgr? No, this is for chat file input
window.removeFile = Chat.removeFile; // This overwrites FileMgr.removeFile?
// Check: FileMgr doesn't seem to export removeFile based on previous grep.
// Let's assume Chat's removeFile is specific to chat preview.
window.clearHistory = Chat.clearHistory;
window.toggleExpand = Chat.toggleExpand;
window.openDashboardChatPopup = Chat.openDashboardChatPopup;
window.receivePopupMessage = Chat.receivePopupMessage;

// Training
window.switchTrainingStep = Training.switchTrainingStep;
window.openTrainingContextModal = Training.openTrainingContextModal;
window.closeTrainingContextModal = Training.closeTrainingContextModal;
window.switchContextTab = Training.switchContextTab;
window.selectContextItem = Training.selectContextItem;
window.confirmContextSelection = Training.confirmContextSelection;
window.renderContextList = Training.renderContextList;
window.makeModelNameEditable = Training.makeModelNameEditable;
window.finishModelNameEdit = Training.finishModelNameEdit;
window.trainModel = Training.trainModel;
window.saveCurrentTrainingDraft = Training.saveCurrentTrainingDraft;
window.loadTrainingDraft = Training.loadTrainingDraft;
window.onMissionTypeChange = Training.onMissionTypeChange;
window.initTrainingChangeListeners = Training.initTrainingChangeListeners;
window.markTrainingConfigChanged = Training.markTrainingConfigChanged;
window.syncGoalToAll = Training.syncGoalToAll;
window.switchStep2SubSection = Training.switchStep2SubSection;
window.switchStep3SubSection = Training.switchStep3SubSection;
window.navigateStep2Sub = Training.navigateStep2Sub;

// List Management
window.toggleListItem = Training.toggleListItem;
window.moveItems = Training.moveItems;
window.moveSingleItem = Training.moveSingleItem;
window.handleTrainingDragStart = Training.handleTrainingDragStart;
window.handleTrainingDrop = Training.handleTrainingDrop;
window.filterList = Training.filterList;
window.filterFeatureList = Training.filterFeatureList;
window.toggleAllFeatures = Training.toggleAllFeatures;
window.updateSelectedFeaturesCount = Training.updateSelectedFeaturesCount;

// Charts for Training
window.drawGoalChart = Charts.drawGoalChart;
window.updateGoalChartLines = Charts.updateGoalChartLines;
window.calculateThreeSigma = Charts.calculateThreeSigma;
window.initGoalChartDrag = Charts.initGoalChartDrag;

// Models
window.loadModelRegistry = Models.loadModelRegistry;
window.changeModelRegistryPage = Models.changeModelRegistryPage;
window.viewTrainingLog = Models.viewTrainingLog;
window.stopModel = Models.stopModel;
window.deleteModel = Models.deleteModel;
window.toggleLogAutoRefresh = Models.toggleLogAutoRefresh;
window.closeLogViewer = Models.closeLogViewer;

// File Manager (parent still needs file selector for training context)
window.confirmFileSelection = FileMgr.confirmFileSelection;

// Simulator
window.runFullSimulation = Simulator.runFullSimulation;
window.triggerSimulatorNext = Simulator.triggerSimulatorNext;
window.startAutoPlay = Simulator.startAutoPlay;
window.stopAutoPlay = Simulator.stopAutoPlay;
window.toggleAutoPlay = Simulator.toggleAutoPlay;
window.clearHistory = Simulator.clearHistory;
window.initSimulatorSelectors = Simulator.initSimulatorSelectors;


// =========================
// Worker & Polling System
// =========================
const timerWorkerScript = `
    let dashboardInterval = null;
    let pollInterval = null;

    self.onmessage = async function(e) {
        const data = e.data;

        // 1. Dashboard 更新 (Worker Fetch)
        if (data.cmd === 'start_dashboard') {
            const sessionId = data.sessionId;
            if (dashboardInterval) clearInterval(dashboardInterval);
            dashboardInterval = setInterval(async () => {
                try {
                    const response = await fetch('/api/history?session_id=' + sessionId);
                    if (response.ok) {
                        const history = await response.json();
                        self.postMessage({ type: 'dashboard_data', history: history });
                    }
                } catch(err) { /* ignore */ }
            }, 1500);
        } else if (data.cmd === 'stop_dashboard') {
            if (dashboardInterval) clearInterval(dashboardInterval);
        }
        // 2. AI 輪詢 (Worker 驅動)
        else if (data.cmd === 'start_polling') {
            if (pollInterval) clearInterval(pollInterval);
            pollInterval = setInterval(() => {
                self.postMessage({ type: 'poll_tick', id: data.id, jobType: data.jobType });
            }, 1000);
        }
        else if (data.cmd === 'stop_polling') {
            if (pollInterval) clearInterval(pollInterval);
        }
    };
`;

const timerBlob = new Blob([timerWorkerScript], { type: 'application/javascript' });
const timerWorker = new Worker(URL.createObjectURL(timerBlob));
const aiPollingCallbacks = {};

// Helper for AI Polling (Globally available for Chat/Analysis modules)
window.pollAIResult = async function (jobId, type) {
    const startTime = Date.now();
    const timeout = 45000;

    return new Promise((resolve, reject) => {
        const checkStatus = async () => {
            try {
                const response = await fetch(`/api/ai/${type}_status/${jobId}`);
                // Fallback for some endpoints if needed, but assuming consistent API
                if (!response.ok) {
                    // Try legacy route if strictly needed, but let's stick to standard first
                    throw new Error("Status check failed");
                }
                const data = await response.json();

                if (data.status === 'completed') {
                    timerWorker.postMessage({ cmd: 'stop_polling' });
                    delete aiPollingCallbacks[jobId];
                    resolve(data);
                } else if (data.status === 'error') {
                    timerWorker.postMessage({ cmd: 'stop_polling' });
                    delete aiPollingCallbacks[jobId];
                    reject(new Error(data.error));
                } else if (Date.now() - startTime > timeout) {
                    timerWorker.postMessage({ cmd: 'stop_polling' });
                    delete aiPollingCallbacks[jobId];
                    reject(new Error("Request timed out (45s)"));
                }
            } catch (err) {
                console.error("Polling error:", err);
            }
        };

        aiPollingCallbacks[jobId] = checkStatus;
        timerWorker.postMessage({ cmd: 'start_polling', id: jobId, jobType: type });
    });
};


timerWorker.onmessage = async function (e) {
    const data = e.data;

    // Heartbeat logic could go here (skipped for brevity)

    if (data.type === 'dashboard_data') {
        Dashboard.renderDashboardData(data.history);
    }
    else if (data.type === 'poll_tick') {
        const callback = aiPollingCallbacks[data.id];
        if (callback) {
            await callback();
        }
    }
};

// Start Dashboard Polling
timerWorker.postMessage({ cmd: 'start_dashboard', sessionId: window.SESSION_ID });

// =========================
// Initialization
// =========================
document.addEventListener('DOMContentLoaded', () => {
    // 1. Initial Data Load (file list now loads in iframe)
    Models.loadModelRegistry();

    // 2. Training & Chart Init
    Training.initTrainingChangeListeners();
    Charts.initGoalChartDrag();
    Simulator.initSimulatorSelectors();

    // 3. Event Listeners
    initListeners();

    // 3. UI Init
    // Hide startup loaders if any
});

function initListeners() {
    // Chat Drag & Drop
    const chatBody = DOM.get('ai-report-content');
    if (chatBody) {
        DOM.on('ai-report-content', 'dragover', (e) => { e.preventDefault(); chatBody.classList.add('drag-over'); });
        DOM.on('ai-report-content', 'dragleave', () => { chatBody.classList.remove('drag-over'); });
        DOM.on('ai-report-content', 'drop', (e) => {
            e.preventDefault(); chatBody.classList.remove('drag-over');
            if (e.dataTransfer.files.length > 0) Chat.processFiles(e.dataTransfer.files);
        });
    }

    // Chat Paste
    const chatInput = DOM.get('chat-input');
    if (chatInput) {
        DOM.on('chat-input', 'paste', (e) => {
            const items = (e.clipboardData || e.originalEvent.clipboardData).items;
            const files = [];
            for (let i = 0; i < items.length; i++) {
                if (items[i].kind === 'file') files.push(items[i].getAsFile());
            }
            if (files.length > 0) Chat.processFiles(files);
        });
    }

    // Global ESC Handler for Dashboard AI (Internal Window)
    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') {
            const win = document.getElementById('ai-assistant-window');
            // Only close if it is currently active (open) and NOT inside the popup (which handles its own ESC)
            if (win && win.classList.contains('active')) {
                UI.toggleAssistant();
            }
        }
    });

    // Goal Chart Inputs
    const goalInputs = ['goal-target', 'goal-usl', 'goal-lsl'];
    goalInputs.forEach(id => {
        DOM.on(id, 'input', () => {
            Charts.updateGoalChartLines();
        });
    });

    // Keyboard Shortcuts (analysis-specific shortcuts now live in analysis iframe)
    document.addEventListener('keydown', (e) => {
        // Escape
        if (e.key === 'Escape') {
            FileMgr.closeFileSelector();
            Models.closeLogViewer();
            Training.closeTrainingContextModal();
        }
    });

    // Handle Window Resize for Charts
    window.addEventListener('resize', () => {
        // Debounce resize
        // ...
    });

}
