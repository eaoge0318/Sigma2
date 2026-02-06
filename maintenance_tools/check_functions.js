// Comprehensive function comparison script
const fs = require('fs');
const path = require('path');

const fullFile = path.join(__dirname, 'static', 'js', 'dashboard_full.js');
const mainFile = path.join(__dirname, 'static', 'js', 'dashboard_main.js');
const modulesDir = path.join(__dirname, 'static', 'js', 'dashboard_modules');

console.log('=== Function Export Analysis ===\n');

// Read files
const fullContent = fs.readFileSync(fullFile, 'utf8');
const mainContent = fs.readFileSync(mainFile, 'utf8');

// Find all function definitions in dashboard_full.js
const funcPattern = /(?:async\s+)?function\s+(\w+)\s*\(/g;
const fullFunctions = new Set();
let match;

while ((match = funcPattern.exec(fullContent)) !== null) {
    fullFunctions.add(match[1]);
}

console.log(`Found ${fullFunctions.size} functions in dashboard_full.js\n`);

// Find all window exports in dashboard_main.js
const exportPattern = /window\.(\w+)\s*=/g;
const exports = new Set();

while ((match = exportPattern.exec(mainContent)) !== null) {
    exports.add(match[1]);
}

console.log(`Found ${exports.size} window exports in dashboard_main.js\n`);

// Read all module files
const moduleFiles = fs.readdirSync(modulesDir);
const allModuleFunctions = new Set();

moduleFiles.forEach(file => {
    if (file.endsWith('.js')) {
        const content = fs.readFileSync(path.join(modulesDir, file), 'utf8');
        const exportFunc = /export\s+(?:async\s+)?function\s+(\w+)\s*\(/g;
        while ((match = exportFunc.exec(content)) !== null) {
            allModuleFunctions.add(match[1]);
        }
    }
});

console.log(`Found ${allModuleFunctions.size} exported functions across all modules\n`);

// Check which exports are missing implementations
const missingImplementations = [];
exports.forEach(exp => {
    if (!allModuleFunctions.has(exp) && exp !== 'DOM' && exp !== 'API' && exp !== 'SESSION_ID') {
        missingImplementations.push(exp);
    }
});

if (missingImplementations.length > 0) {
    console.log('⚠ MISSING IMPLEMENTATIONS (exported in main but not in modules):');
    missingImplementations.forEach(fn => console.log(`  - ${fn}`));
    console.log();
} else {
    console.log('✓ All exports have implementations\n');
}

// Check critical functions from dashboard_full.js
const criticalFunctions = [
    'trainModel',
    'saveCurrentTrainingDraft',
    'loadTrainingDraft',
    'checkTrainingFileBeforeSelect',
    'finishModelNameEdit',
    'loadTrainingMetadata',
    'collectTrainingUIState',
    'startModelTraining',
    'switchTrainingStep',
    'switchTrainingMainTab',
    'switchTrainingSubTab',
    'loadModelRegistry',
    'viewTrainingLog',
    'stopModel',
    'deleteModel'
];

console.log('=== Critical Training Functions Check ===\n');
const missingCritical = [];
criticalFunctions.forEach(fn => {
    const exported = exports.has(fn);
    const implemented = allModuleFunctions.has(fn);
    const status = exported && implemented ? '✓' : (exported ? '⚠' : '✗');
    console.log(`${status} ${fn}: ${exported ? 'exported' : 'not exported'}, ${implemented ? 'implemented' : 'NOT IMPLEMENTED'}`);
    if (exported && !implemented) {
        missingCritical.push(fn);
    }
});

if (missingCritical.length > 0) {
    console.log(`\n⚠ ${missingCritical.length} functions are exported but not implemented!`);
    console.log('These need to be copied from dashboard_full.js:');
    missingCritical.forEach(fn => console.log(`  - ${fn}`));
}
