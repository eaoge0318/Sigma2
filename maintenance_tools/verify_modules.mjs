
// Verification Script for Dashboard Modules
// Run with: node verify_modules.js

// 1. Mock Browser Environment
global.window = {
    location: { origin: 'http://localhost', hash: '' },
    localStorage: {
        getItem: () => 'test-session-id',
        setItem: () => { }
    },
    confirm: () => true,
    alert: console.log,
};
global.document = {
    getElementById: () => ({
        style: {},
        classList: { add: () => { }, remove: () => { }, toggle: () => { } },
        addEventListener: () => { },
        appendChild: () => { },
        getContext: () => ({})
    }),
    createElement: () => ({
        style: {},
        classList: { add: () => { }, remove: () => { }, toggle: () => { } },
        addEventListener: () => { },
        appendChild: () => { },
        getContext: () => ({})
    }),
    querySelector: () => ({
        style: {},
        classList: { add: () => { }, remove: () => { }, toggle: () => { } },
        innerText: ''
    }),
    querySelectorAll: () => [],
    addEventListener: () => { },
    body: { classList: { add: () => { }, remove: () => { }, toggle: () => { } } }
};
global.fetch = async () => ({ ok: true, json: async () => ({}) });
global.FormData = class { };
global.Chart = class { update() { } destroy() { } };
global.console = {
    ...console,
    log: (msg) => console.log(`[LOG] ${msg}`),
    error: (msg) => console.log(`[ERROR] ${msg}`)
};

// 2. Import Main Module
// Note: Node.js requires .mjs extension or "type": "module" in package.json for ES modules.
// We will rename this file to verify_modules.mjs temporarily or just rely on 'import' working if environment supports it.
// Given the environment likely defaults to CJS, we might need to use dynamic import.

(async () => {
    try {
        console.log("Starting Module Verification...");

        // Dynamic import of the module
        await import('./static/js/dashboard_main.js');

        console.log("--------------------------------------------------");
        console.log("✅ Main Module Loaded Successfully (No Syntax Errors)");

        // 3. Verify Exports
        const expectedGlobals = [
            'loadFileList',
            'loadModelRegistry',
            'trainModel',
            'updateDashboard',
            'SESSION_ID'
        ];

        const missing = expectedGlobals.filter(key => window[key] === undefined);

        if (missing.length > 0) {
            console.log("❌ Missing Global Exports:", missing);
            console.log("⚠️  The module loaded, but didn't attach these functions to window.");
            process.exit(1);
        } else {
            console.log("✅ All Key Globals are Present on Window.");
            process.exit(0);
        }

    } catch (err) {
        console.log("\n❌ CRITICAL ERROR LOADING MODULES:");
        console.log(err);
        process.exit(1);
    }
})();
