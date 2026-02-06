# 伺服器重啟指南

## 1. 確認當前目錄
```powershell
cd C:\Users\foresight\Desktop\MantleTemp\pythaon\Sigma2
```

## 2. 啟動伺服器
```powershell
python api_entry.py
```

## 3. 確認啟動成功
終端機應該顯示：
```
Server starting in: C:\Users\foresight\Desktop\MantleTemp\pythaon\Sigma2
INFO:     Started server process [XXXXX]
INFO:     Uvicorn running on http://0.0.0.0:8001
```

## 4. 開啟瀏覽器（無痕模式）
按 `Ctrl + Shift + N` 開啟無痕視窗

訪問：`http://10.10.20.109:8001/dashboard`

## 5. 強制重新載入
按 `Ctrl + Shift + R` 清空快取並重新載入

## 預期結果
- ✅ 淺灰色的表格標題（不是深藍色）
- ✅ Inter 字體（不是預設系統字體）
- ✅ 乾淨的白色背景區塊
- ✅ 側邊欄文字正常顯示

## 如果還有問題
檢查終端機是否有 "DEBUG: Serving dashboard from ..." 訊息
