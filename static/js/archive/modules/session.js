// Session 模組 - 管理 Session ID 和 Session Storage
export class SessionManager {
    constructor() {
        this.sessionId = this.getSessionId();
        console.log("Session Manager initialized. Session ID:", this.sessionId);
    }

    getSessionId() {
        let sid = localStorage.getItem("sigma2_session_id");
        if (!sid) {
            sid = 'sess-' + Math.random().toString(36).substr(2, 9) + Date.now().toString(36);
            localStorage.setItem("sigma2_session_id", sid);
        }
        return sid;
    }

    clearSession() {
        localStorage.removeItem("sigma2_session_id");
        this.sessionId = this.getSessionId();
    }

    getItem(key) {
        return localStorage.getItem(key);
    }

    setItem(key, value) {
        localStorage.setItem(key, value);
    }

    setSessionId(newId) {
        localStorage.setItem("sigma2_session_id", newId);
        this.sessionId = newId;
    }
}
