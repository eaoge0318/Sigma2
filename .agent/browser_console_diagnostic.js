// 在瀏覽器控制台執行此腳本來診斷問題

console.log("=== JavaScript 診斷 ===");

// 檢查關鍵變數是否存在
console.log("charts:", typeof charts);
console.log("yAxisMode:", typeof yAxisMode);
console.log("yAxisManualMin:", typeof yAxisManualMin);
console.log("yAxisManualMax:", typeof yAxisManualMax);

// 檢查關鍵函數是否存在
console.log("showYAxisRangeModal:", typeof showYAxisRangeModal);
console.log("closeYAxisRangeModal:", typeof closeYAxisRangeModal);
console.log("recreateAllCharts:", typeof recreateAllCharts);
console.log("updateDashboard:", typeof updateDashboard);
console.log("createChart:", typeof createChart);

// 檢查是否有錯誤
console.log("=== 檢查完成 ===");
console.log("如果看到 'undefined',表示該變數或函數未正確載入");
