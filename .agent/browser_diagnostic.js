// ==========================================
// 即時診斷腳本 - 在瀏覽器 Console 執行
// ==========================================

// 步驟 1: 檢查當前狀態
console.log('=== 系統狀態診斷 ===');
console.log('Session ID:', window.Sigma2?.session?.getSessionId());
console.log('Dashboard Ready:', window.Sigma2?.dashboard ? 'YES' : 'NO');
console.log('File Select Value:', document.getElementById('dashboard-file-select')?.value);
console.log('Model Select Value:', document.getElementById('dashboard-model-select')?.value);

// 步驟 2: 測試檔案載入
async function testFileLoad() {
    console.log('\n=== 測試檔案載入 ===');
    const fileSelect = document.getElementById('dashboard-file-select');
    const filename = fileSelect.value;

    if (!filename) {
        console.error('❌ 未選擇檔案');
        return;
    }

    console.log('正在載入檔案:', filename);

    const response = await fetch('/api/simulator/load_file', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            filename: filename,
            session_id: window.Sigma2?.session?.getSessionId() || 'default'
        })
    });

    const result = await response.json();
    console.log('檔案載入結果:', result);

    if (result.status === 'success') {
        console.log(`✅ 成功: ${filename} (${result.rows} 筆數據)`);
    } else {
        console.error(`❌ 失敗: ${result.message}`);
    }
}

// 步驟 3: 測試模型載入
async function testModelLoad() {
    console.log('\n=== 測試模型載入 ===');
    const modelSelect = document.getElementById('dashboard-model-select');
    const modelPath = modelSelect.value;

    if (!modelPath) {
        console.error('❌ 未選擇模型');
        return;
    }

    console.log('正在載入模型:', modelPath);

    const response = await fetch('/api/model/load', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            model_path: modelPath,
            session_id: window.Sigma2?.session?.getSessionId() || 'default'
        })
    });

    const result = await response.json();
    console.log('模型載入結果:', result);

    if (result.status === 'success') {
        console.log(`✅ 成功: ${modelPath}`);
    } else {
        console.error(`❌ 失敗: ${result.message}`);
    }
}

// 步驟 4: 測試模擬
async function testSimulation() {
    console.log('\n=== 測試模擬 ===');

    const response = await fetch('/api/simulator/next', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            session_id: window.Sigma2?.session?.getSessionId() || 'default'
        })
    });

    if (!response.ok) {
        const error = await response.json();
        console.error('❌ 模擬失敗:', error.detail);
        return;
    }

    const result = await response.json();
    console.log('✅ 模擬成功:', result);
}

// 執行完整測試流程
async function runFullTest() {
    console.clear();
    console.log('========================================');
    console.log('   即時看板完整測試流程');
    console.log('========================================\n');

    // 1. 檢查狀態
    console.log('=== 系統狀態 ===');
    console.log('Session ID:', window.Sigma2?.session?.getSessionId());
    console.log('Dashboard Ready:', window.Sigma2?.dashboard ? 'YES' : 'NO');

    const fileSelect = document.getElementById('dashboard-file-select');
    const modelSelect = document.getElementById('dashboard-model-select');

    console.log('File Select:', fileSelect?.value || '(未選擇)');
    console.log('Model Select:', modelSelect?.value || '(未選擇)');

    // 2. 測試檔案載入
    if (!fileSelect?.value) {
        console.warn('\n⚠️  請先從下拉選單選擇檔案');
        return;
    }
    await testFileLoad();

    // 3. 等待 1 秒
    await new Promise(r => setTimeout(r, 1000));

    // 4. 測試模型載入
    if (!modelSelect?.value) {
        console.warn('\n⚠️  請先從下拉選單選擇模型');
        return;
    }
    await testModelLoad();

    // 5. 等待 1 秒
    await new Promise(r => setTimeout(r, 1000));

    // 6. 測試模擬
    await testSimulation();

    console.log('\n========================================');
    console.log('   測試完成');
    console.log('========================================');
}

// 顯示使用說明
console.log(`
========================================
即時診斷腳本已載入
========================================

可用命令：

1. runFullTest()
   執行完整測試流程（推薦）

2. testFileLoad()
   僅測試檔案載入

3. testModelLoad()
   僅測試模型載入

4. testSimulation()
   僅測試模擬執行

========================================
快速開始：請執行 runFullTest()
========================================
`);
