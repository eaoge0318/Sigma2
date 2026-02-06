
// =========================
// session.js - User Session Management
// =========================

export function getSessionId() {
    let sid = localStorage.getItem("sigma2_session_id");
    if (!sid) {
        sid = 'sess-' + Math.random().toString(36).substr(2, 9) + Date.now().toString(36);
        localStorage.setItem("sigma2_session_id", sid);
    }
    return sid;
}

export const SESSION_ID = getSessionId();

// Expose to window for legacy compatibility and other modules relying on global
window.SESSION_ID = SESSION_ID;
console.log("Current Session ID:", SESSION_ID);

export function switchUser() {
    const currentSid = localStorage.getItem("sigma2_session_id") || "default";
    const newSid = prompt("請輸入您的 User ID (Session ID):\n\n輸入 'default' 可檢視舊版檔案。", currentSid);
    if (newSid && newSid.trim() !== "") {
        localStorage.setItem("sigma2_session_id", newSid.trim());
        alert(`身份已切換為: ${newSid.trim()}\n頁面即將重整...`);
        window.location.reload();
    }
}

// Attach switchUser to window so it can be called from onclick in HTML if needed
window.switchUser = switchUser;
