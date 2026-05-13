/**
 * 全域 Fetch 攔截器：自動處理欄位別名
 *
 * 當別名模式開啟時 (localStorage sigma2_useAlias === '1'):
 * 1. 所有 API 請求自動加上 use_alias=1 參數
 * 2. POST 請求 body 中的別名自動反向映射為原始欄位名
 * 3. URL 查詢參數中的別名自動反向映射
 *
 * 後端中間件負責：
 * - 回應中的原始欄位名 → 別名
 * - 請求 body 中的別名 → 原始欄位名（雙重保險）
 */
(function () {
    'use strict';
    if (window.__aliasFetchInstalled) return;
    window.__aliasFetchInstalled = true;

    const _origFetch = window.fetch;

    // 快取反向映射表
    let _revCache = null;
    let _revCacheKey = '';

    function _getReverseMap() {
        const raw = localStorage.getItem('sigma2_aliases') || '{}';
        if (raw === _revCacheKey) return _revCache;
        try {
            const map = JSON.parse(raw);
            const rev = {};
            for (const [k, v] of Object.entries(map)) {
                if (k && v) rev[v] = k;
            }
            _revCache = rev;
            _revCacheKey = raw;
            return rev;
        } catch (_) {
            _revCache = {};
            _revCacheKey = raw;
            return {};
        }
    }

    function _reverseAliasInString(str, rev) {
        // 同時替換所有別名 → 原始名（JSON 字串值中）
        const keys = Object.keys(rev).filter(k => k);
        if (keys.length === 0) return str;
        // 按長度降序，避免短別名匹配到長別名的子字串
        keys.sort((a, b) => b.length - a.length);
        const escaped = keys.map(k => k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
        const pattern = new RegExp('"(' + escaped.join('|') + ')"', 'g');
        return str.replace(pattern, (m, key) => {
            return rev[key] ? '"' + rev[key] + '"' : m;
        });
    }

    window.fetch = function (input, init) {
        if (localStorage.getItem('sigma2_useAlias') !== '1') {
            return _origFetch.call(window, input, init);
        }

        try {
            // 解析 URL，加上 use_alias=1
            let url;
            if (typeof input === 'string') {
                url = new URL(input, location.origin);
            } else if (input instanceof Request) {
                url = new URL(input.url);
            } else {
                return _origFetch.call(window, input, init);
            }

            // 只處理 /api/ 路徑
            if (!url.pathname.startsWith('/api/')) {
                return _origFetch.call(window, input, init);
            }

            // 跳過別名管理 API 本身
            if (url.pathname.includes('/column-aliases')) {
                return _origFetch.call(window, input, init);
            }

            url.searchParams.set('use_alias', '1');

            const rev = _getReverseMap();

            // 反向替換 query 參數中的別名值
            if (Object.keys(rev).length > 0) {
                for (const [key, val] of url.searchParams.entries()) {
                    if (key === 'use_alias' || key === 'session_id') continue;
                    if (rev[val]) url.searchParams.set(key, rev[val]);
                }
            }

            // 反向替換 POST body 中的別名
            let newInit = init ? { ...init } : {};
            if (newInit.body && typeof newInit.body === 'string' && Object.keys(rev).length > 0) {
                newInit.body = _reverseAliasInString(newInit.body, rev);
            }

            return _origFetch.call(window, url.toString(), newInit);
        } catch (_) {
            return _origFetch.call(window, input, init);
        }
    };
})();
