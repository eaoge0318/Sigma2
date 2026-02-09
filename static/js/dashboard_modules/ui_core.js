
// =========================
// ui_core.js - UI & Layout Management
// =========================
import { DOM } from './utils.js';

export function toggleAssistant() {
    const win = DOM.get('ai-assistant-window');
    if (!win) return;

    if (win.classList.contains('active')) {
        DOM.hide('ai-assistant-window');
        DOM.removeClass('ai-assistant-window', 'active');
        DOM.setText('fab-icon', '🤖');
    } else {
        DOM.show('ai-assistant-window', 'flex');
        DOM.addClass('ai-assistant-window', 'active');
        DOM.setText('fab-icon', '×');

        // Focus input
        setTimeout(() => {
            const input = DOM.get('chat-input');
            if (input) input.focus();
        }, 100);
    }
}

export function toggleSidebar() {
    const sidebar = DOM.get('sidebar');
    if (sidebar) {
        DOM.toggleClass('sidebar', 'collapsed');
        document.body.classList.toggle('sidebar-collapsed');
    }
}

export function initAutoSidebar() {
    const sidebar = DOM.get('sidebar');
    const trigger = DOM.get('sidebar-trigger');

    if (!sidebar || !trigger) return;

    let timeout;

    trigger.addEventListener('mouseenter', () => {
        sidebar.classList.remove('collapsed');
        document.body.classList.remove('sidebar-collapsed');
    });

    sidebar.addEventListener('mouseleave', () => {
        timeout = setTimeout(() => {
            sidebar.classList.add('collapsed');
            document.body.classList.add('sidebar-collapsed');
        }, 300); // Delay before hiding
    });

    sidebar.addEventListener('mouseenter', () => {
        clearTimeout(timeout);
    });
}

export function switchView(viewName) {
    const navItems = ['dashboard', 'files', 'analysis', 'training', 'intelligent-analysis'];
    const views = {
        'dashboard': 'view-dashboard',
        'files': 'view-files',
        'analysis': 'view-analysis',
        'training': 'view-training',
        'intelligent-analysis': 'view-intelligent-analysis'
    };

    // Update Nav State
    navItems.forEach(name => {
        const btn = DOM.get(`nav-${name}`);
        if (btn) {
            if (name === viewName) btn.classList.add('active');
            else btn.classList.remove('active');
        }
    });

    // Toggle Sections
    Object.entries(views).forEach(([name, id]) => {
        if (name === viewName) DOM.show(id);
        else DOM.hide(id);
    });

    // Toggle Chart AI Assistant Button
    const chartFab = DOM.get('chart-assistant-trigger');
    if (chartFab) {
        chartFab.style.display = (viewName === 'analysis') ? 'flex' : 'none';
    }
}

/* --- Internal Helpers for Training Tabs --- */
function setActiveTabStyle(activeBtn, inactiveBtns) {
    if (activeBtn) {
        activeBtn.classList.add('active');
        activeBtn.style.background = '#e0e7ff';
        activeBtn.style.color = '#3730a3';
        activeBtn.style.fontWeight = '700';
    }
    inactiveBtns.forEach(btn => {
        if (btn) {
            btn.classList.remove('active');
            btn.style.background = 'transparent';
            btn.style.color = '#64748b';
            btn.style.fontWeight = '500';
        }
    });
}

/* --- Exported for Main Module Usage --- */
export function switchTrainingMainTab(tab) {
    const btnBuild = DOM.get('tab-train-main-build');
    const btnRegistry = DOM.get('tab-train-main-registry');

    const isBuild = (tab === 'build');
    if (isBuild) {
        DOM.show('training-main-build-content');
        DOM.hide('training-main-registry-content');
    } else {
        DOM.hide('training-main-build-content');
        DOM.show('training-main-registry-content');
    }

    setActiveTabStyle(isBuild ? btnBuild : btnRegistry, isBuild ? [btnRegistry] : [btnBuild]);
}

export function switchTrainingSubTab(tab) {
    const btnConfig = DOM.get('tab-train-sub-config');
    const btnReport = DOM.get('tab-train-sub-report');

    const isConfig = (tab === 'config');
    if (isConfig) {
        DOM.show('training-sub-config-content');
        DOM.hide('training-sub-report-content');
    } else {
        DOM.hide('training-sub-config-content');
        DOM.show('training-sub-report-content');
    }

    setActiveTabStyle(isConfig ? btnConfig : btnReport, isConfig ? [btnReport] : [btnConfig]);
}

