// 在瀏覽器控制台執行此腳本來診斷 AI 助手問題

console.log('=== AI 助手診斷工具 ===');

// 測試 1: 檢查 API 報告生成
async function testReport() {
    console.log('\n📋 測試 1: AI 報告生成');
    try {
        const sessionId = localStorage.getItem('sigma2_session_id') || 'default';
        const response = await fetch(`/api/ai_report?session_id=${sessionId}`);

        console.log(`HTTP Status: ${response.status} ${response.statusText}`);
        console.log(`Content-Type: ${response.headers.get('Content-Type')}`);

        const data = await response.json();
        console.log('Response data:', data);

        if (data.report) {
            console.log('✅ 報告內容長度:', data.report.length);
            console.log('報告預覽:', data.report.substring(0, 200));
        } else {
            console.log('❌ 沒有報告內容');
        }
    } catch (error) {
        console.error('❌ 錯誤:', error);
    }
}

// 測試 2: 檢查聊天功能
async function testChat() {
    console.log('\n💬 測試 2: AI 聊天');
    try {
        const sessionId = localStorage.getItem('sigma2_session_id') || 'default';
        const response = await fetch('/api/ai_chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                messages: [{ role: 'user', content: '測試訊息' }],
                session_id: sessionId
            })
        });

        console.log(`HTTP Status: ${response.status} ${response.statusText}`);
        const data = await response.json();
        console.log('Response data:', data);

        if (data.reply) {
            console.log('✅ 回覆內容長度:', data.reply.length);
            console.log('回覆預覽:', data.reply.substring(0, 200));
        } else {
            console.log('❌ 沒有回覆內容');
        }
    } catch (error) {
        console.error('❌ 錯誤:', error);
    }
}

// 測試 3: 檢查歷史數據
async function checkHistory() {
    console.log('\n📊 測試 3: 檢查歷史數據');
    try {
        const sessionId = localStorage.getItem('sigma2_session_id') || 'default';
        const response = await fetch(`/api/history?session_id=${sessionId}`);
        const history = await response.json();

        console.log(`歷史記錄數量: ${history.length}`);
        if (history.length > 0) {
            console.log('最新一筆數據:', history[history.length - 1]);
        } else {
            console.log('⚠️ 沒有歷史數據，請先載入模擬數據並執行推理');
        }
    } catch (error) {
        console.error('❌ 錯誤:', error);
    }
}

// 執行所有測試
async function runAllTests() {
    await checkHistory();
    await testReport();
    await testChat();
    console.log('\n=== 診斷完成 ===');
    console.log('💡 提示：如果看到亂碼，請檢查瀏覽器控制台的編碼設定');
}

// 自動執行
runAllTests();
