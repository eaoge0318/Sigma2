# Sigma2 部署說明

## 系統需求

- **作業系統**: Windows 10/11 (x64)
- **記憶體**: 建議 8GB 以上
- **網路**: 需要能連到 LLM Server（內網）

> 不需要安裝 Python，已包含在部署包內。

---

## 部署步驟

### 1. 複製部署包

將整個 `Sigma2_Deploy` 資料夾複製到目標機器上的任意位置。

### 2. 設定環境

編輯 `.env` 檔案，修改以下設定：

```env
# LLM Server IP（改成目標環境的 IP）
SIGMA_LLM_URL=http://10.10.20.214:8000/v1/chat/completions

# LLM 模型名稱
SIGMA_LLM_MODEL=/models/gemma-3-27b-it-qat-compressed-tensors

# API Port（預設 8001，如有衝突可修改）
SIGMA_API_PORT=8001
```

### 3. 啟動

雙擊 `start.bat`

### 4. 開啟系統

瀏覽器打開: **http://localhost:8001/dashboard**

---

## 目錄結構

```
Sigma2_Deploy/
├── python/          ← Python 執行環境（勿刪）
├── app/             ← 應用程式碼
├── .env             ← 環境設定（可修改）
├── .env.example     ← 設定範本
├── start.bat        ← 啟動腳本
└── DEPLOY.md        ← 本文件
```

---

## 常見問題

### Q: 啟動後瀏覽器打不開？
確認 `start.bat` 的 console 沒有錯誤訊息。如果 port 衝突，修改 `.env` 中的 `SIGMA_API_PORT`。

### Q: 分析功能無法使用？
確認 `.env` 中的 `SIGMA_LLM_URL` 能從目標機器連到 LLM Server。

### Q: 如何更新程式碼？
只需替換 `app/` 資料夾內的檔案即可，不需要重新打包整個部署包。
