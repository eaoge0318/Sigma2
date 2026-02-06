
// =========================
// utils.js - General Helpers
// =========================

export const WINDOW_SIZE = 120;

export const DOM = {
    get: (id) => document.getElementById(id),
    show: (id, type = 'block') => { const el = document.getElementById(id); if (el) el.style.display = type; },
    hide: (id) => { const el = document.getElementById(id); if (el) el.style.display = 'none'; },
    toggle: (id) => {
        const el = document.getElementById(id);
        if (el) el.style.display = (el.style.display === 'none' ? 'block' : 'none');
    },
    addClass: (id, cls) => { const el = document.getElementById(id); if (el) el.classList.add(cls); },
    removeClass: (id, cls) => { const el = document.getElementById(id); if (el) el.classList.remove(cls); },
    toggleClass: (id, cls) => { const el = document.getElementById(id); if (el) el.classList.toggle(cls); },
    setText: (id, txt) => { const el = document.getElementById(id); if (el) el.innerText = txt; },
    setHTML: (id, html) => { const el = document.getElementById(id); if (el) el.innerHTML = html; },
    html: (id, html) => {
        const el = document.getElementById(id);
        if (el) {
            if (html !== undefined) el.innerHTML = html;
            return el.innerHTML;
        }
        return null;
    },
    text: (id, txt) => {
        const el = document.getElementById(id);
        if (el) {
            if (txt !== undefined) el.innerText = txt;
            return el.innerText;
        }
        return null;
    },
    val: (id, v) => {
        const el = document.getElementById(id);
        if (el) {
            if (v !== undefined) el.value = v;
            return el.value;
        }
        return null;
    },
    on: (id, event, handler) => {
        const el = document.getElementById(id);
        if (el) el.addEventListener(event, handler);
    }
};

export const API = {
    headers: { 'Content-Type': 'application/json' },
    _url: (url, params = {}) => {
        const u = new URL(url, window.location.origin);
        // We need to ensure SESSION_ID is available. 
        // In modular approach, we might pass it or import it.
        // For now, checks global window.SESSION_ID which will be set by session module.
        if (window.SESSION_ID) u.searchParams.set('session_id', window.SESSION_ID);
        Object.keys(params).forEach(k => u.searchParams.set(k, params[k]));
        return u.toString();
    },
    get: async (url, params = {}) => {
        const res = await fetch(API._url(url, params));
        if (!res.ok) throw new Error(res.statusText);
        return res.json();
    },
    post: async (url, body = {}) => {
        if (window.SESSION_ID) body.session_id = window.SESSION_ID;
        const res = await fetch(url, {
            method: 'POST',
            headers: API.headers,
            body: JSON.stringify(body)
        });
        if (!res.ok) throw new Error(res.statusText);
        return res.json();
    },
    delete: async (url, params = {}) => {
        const res = await fetch(API._url(url, params), { method: 'DELETE' });
        if (!res.ok) throw new Error(res.statusText);
        return res.json();
    }
};

export const Formatters = {
    date: (ts) => new Date(ts).toLocaleString(),
    fixed: (num, digits = 2) => Number(num).toFixed(digits)
};
