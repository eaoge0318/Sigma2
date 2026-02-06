# 重新啟動伺服器指南

## 問題
Y 軸仍然沒有使用 job_xxx.json 中的 goal 欄位

## 可能原因
1. **伺服器沒有重新啟動** - 修改的程式碼沒有生效
2. **模型配置沒有載入** - 需要先載入模型才能設定 goal 欄位

## 解決步驟

### 步驟 1: 重新啟動伺服器
1. 在執行 `api_entry.py` 的終端機視窗按 `Ctrl+C` 停止伺服器
2. 重新執行: `python api_entry.py`
3. 等待伺服器啟動完成

### 步驟 2: 在前端重新載入模型
在執行模擬**之前**,必須先載入模型配置:

1. 在模擬頁面選擇模型 (例如: `job_7ba3af9e.json`)
2. 點擊"載入模型"按鈕
3. 等待載入完成

### 步驟 3: 載入模擬檔案
選擇要模擬的 CSV 檔案

### 步驟 4: 執行模擬
點擊"執行模擬"或"下一筆"按鈕

### 步驟 5: 檢查 Console 輸出
在伺服器的 console 中,應該會看到以下訊息:

**如果成功:**
```
[DEBUG] Goal column from model config: METROLOGY-P21-MO1-SP-2SIGMA
[DEBUG] Using goal column 'METROLOGY-P21-MO1-SP-2SIGMA' as measure: 1.234
```

**如果失敗:**
```
[WARNING] Goal column not found in session or data, falling back to auto-detection
[DEBUG] Measure column found: G_std = 0.567
```

## 重要提醒
- **必須先載入模型,再執行模擬**
- 如果跳過載入模型的步驟,系統會使用舊的自動檢測邏輯
- 每次重新啟動伺服器後,都需要重新載入模型

## 檢查清單
- [ ] 伺服器已重新啟動
- [ ] 已載入 job_xxx.json 模型配置
- [ ] 已載入模擬 CSV 檔案
- [ ] Console 顯示正確的 goal 欄位名稱
- [ ] 圖表 Y 軸顯示正確的數據範圍
