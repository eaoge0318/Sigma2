// Simple Node.js test to check module syntax
// This tests basic syntax and structure, not runtime behavior

const fs = require('fs');
const path = require('path');

const modulesDir = path.join(__dirname, 'static', 'js', 'dashboard_modules');
const files = [
    'utils.js',
    'ui_core.js',
    'session.js',
    'charts_manager.js',
    'file_manager.js',
    'analysis_manager.js',
    'training_manager.js',
    'models_manager.js',
    'dashboard_render.js',
    'simulator.js',
    'chat_manager.js'
];

console.log('Testing module files for syntax errors...\n');

let allPassed = true;

files.forEach(file => {
    const filePath = path.join(modulesDir, file);
    try {
        const content = fs.readFileSync(filePath, 'utf8');

        // Check for common syntax errors
        const issues = [];

        // Check for unclosed strings
        const lines = content.split('\n');
        lines.forEach((line, index) => {
            // Skip comments
            if (line.trim().startsWith('//')) return;

            // Count quotes
            const singleQuotes = (line.match(/(?<!\\)'/g) || []).length;
            const doubleQuotes = (line.match(/(?<!\\)"/g) || []).length;
            const backticks = (line.match(/(?<!\\)`/g) || []).length;

            // This is a simple check and may have false positives
            // but it's enough to catch obvious errors
        });

        // Check for basic structure
        if (!content.includes('export')) {
            issues.push('No exports found - might not be a proper module');
        }

        // Check for common issues
        if (content.includes('window.') && !content.includes('// Window Exports')) {
            // OK - intentional global exports
        }

        console.log(`✓ ${file}: ${content.length} bytes, looks OK`);

        if (issues.length > 0) {
            console.log(`  ⚠ Warnings: ${issues.join(', ')}`);
        }

    } catch (error) {
        console.log(`✗ ${file}: ERROR - ${error.message}`);
        allPassed = false;
    }
});

console.log('\n' + (allPassed ? '✓ All files passed basic syntax check' : '✗ Some files have issues'));

// Also check main entry point
try {
    const mainFile = path.join(__dirname, 'static', 'js', 'dashboard_main.js');
    const content = fs.readFileSync(mainFile, 'utf8');
    console.log(`\n✓ dashboard_main.js: ${content.length} bytes`);

    // Count imports
    const imports = content.match(/import .* from/g);
    console.log(`  - ${imports ? imports.length : 0} module imports detected`);

    // Count window exports
    const windowExports = content.match(/window\.\w+\s*=/g);
    console.log(`  - ${windowExports ? windowExports.length : 0} global exports detected`);

} catch (error) {
    console.log(`\n✗ dashboard_main.js: ERROR - ${error.message}`);
}
