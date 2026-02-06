// 在 DOMContentLoaded 後添加拖放和貼上支持（專業版）
document.addEventListener('DOMContentLoaded', () => {
    const chartChatBody = document.getElementById('chart-ai-report-content');
    const chartChatInput = document.getElementById('chart-chat-input');

    if (!chartChatBody || !chartChatInput) return;

    // 拖放支持
    chartChatBody.addEventListener('dragover', (e) => {
        e.preventDefault();
        chartChatBody.classList.add('drag-over');
    });

    chartChatBody.addEventListener('dragleave', () => {
        chartChatBody.classList.remove('drag-over');
    });

    chartChatBody.addEventListener('drop', (e) => {
        e.preventDefault();
        chartChatBody.classList.remove('drag-over');
        if (e.dataTransfer.files.length > 0) {
            chartProcessFiles(e.dataTransfer.files);
        }
    });

    // 貼上圖片支持
    chartChatInput.addEventListener('paste', (e) => {
        const items = (e.clipboardData || e.originalEvent.clipboardData).items;
        const files = [];
        for (let i = 0; i < items.length; i++) {
            if (items[i].kind === 'file') {
                files.push(items[i].getAsFile());
            }
        }
        if (files.length > 0) {
            chartProcessFiles(files);
        }
    });
});
