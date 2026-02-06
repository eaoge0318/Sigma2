
// Failsafe initialization
(async function () {
    console.log("🛡️ Failsafe script running...");

    // Check if Sigma2 exists
    window.Sigma2 = window.Sigma2 || {};

    try {
        // Dynamic imports to bypass static import errors
        const { SessionManager } = await import('./modules/session.js');
        const { FileManager } = await import('./modules/file-manager.js');
        const { AnalysisManager } = await import('./modules/analysis.js');

        // 1. Ensure Session
        if (!window.Sigma2.session) {
            console.warn("⚠️ Sigma2.session missing, initializing via failsafe...");
            window.Sigma2.session = new SessionManager();

            // Fix UI Label
            const sid = window.Sigma2.session.getSessionId();
            const sidSpan = document.getElementById('current-user-id');
            if (sidSpan) {
                sidSpan.innerText = sid;
                sidSpan.style.color = '#22c55e';
            }
        }

        // 2. Ensure FileManager
        if (!window.Sigma2.fileManager) {
            console.warn("⚠️ Sigma2.fileManager missing, initializing via failsafe...");
            window.Sigma2.fileManager = new FileManager(window.Sigma2.session);
            window.Sigma2.fileManager.setupDropzone();

            // Global exposure for HTML onclick handlers
            window.handleMainFileUpload = (input) => window.Sigma2.fileManager.handleMainFileUpload(input);
            window.openUploadModal = () => window.Sigma2.fileManager.openUploadModal();
            window.closeUploadModal = () => window.Sigma2.fileManager.closeUploadModal();
            window.closeViewModal = () => window.Sigma2.fileManager.closeViewModal();
            window.deleteFile = (f) => window.Sigma2.fileManager.deleteFile(f);
            window.viewFile = (f) => window.Sigma2.fileManager.viewFile(f);
            window.trainModel = (f) => window.Sigma2.fileManager.trainModel(f);
        }

        // 3. Ensure AnalysisManager
        if (!window.Sigma2.analysis) {
            console.warn("⚠️ Sigma2.analysis missing, initializing via failsafe...");
            window.Sigma2.analysis = new AnalysisManager(window.Sigma2.session);
        }

        // Force reload list
        console.log("🔄 Failsafe forcing file list reload...");
        await window.Sigma2.fileManager.loadFileList();

        console.log("✅ Failsafe initialization complete.");

    } catch (e) {
        console.error("❌ Failsafe failed:", e);
        // Extreme fallback: Alert user
        alert("系統發生嚴重錯誤，無法載入模組。請檢查控制台 (F12)。\nCritical Error: " + e.message);
    }
})();
