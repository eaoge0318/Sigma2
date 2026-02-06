# httpx 安裝指南

## 問題

後端啟動失敗,錯誤訊息:
```
ModuleNotFoundError: No module named 'httpx'
```

## 解決方案

### 方法 1: 使用您啟動後端的 Python 環境

**重要**: 必須在**啟動後端的同一個 Python 環境**中安裝 httpx!

1. **找到您啟動後端時使用的 Python**
   - 如果使用虛擬環境,先啟動它
   - 如果直接使用系統 Python,記下路徑

2. **安裝 httpx**

   **選項 A - 如果使用虛擬環境**:
   ```powershell
   # 先啟動虛擬環境
   .\venv\Scripts\Activate.ps1
   
   # 然後安裝
   pip install httpx
   ```

   **選項 B - 使用完整 Python 路徑**:
   ```powershell
   # 使用您的 Python 路徑 (例如)
   C:\Users\foresight\AppData\Local\Programs\Python\Python312\python.exe -m pip install httpx
   ```

   **選項 C - 簡單方式**:
   ```powershell
   python -m pip install httpx
   ```

3. **驗證安裝**
   ```powershell
   python -c "import httpx; print(httpx.__version__)"
   ```
   
   如果顯示版本號(例如 `0.27.0`),表示安裝成功!

4. **重新啟動後端**
   ```powershell
   python api_entry.py
   ```

---

## 方法 2: 檢查 Python 環境

如果不確定使用哪個 Python,可以:

1. **查看後端啟動時的 Python 路徑**
   - 後端啟動時會顯示 Python 版本
   - 或執行: `where python`

2. **使用該 Python 安裝 httpx**
   ```powershell
   <該Python路徑> -m pip install httpx
   ```

---

## 方法 3: 更新 requirements.txt (推薦)

1. **建立或更新 requirements.txt**
   ```
   fastapi
   uvicorn
   httpx
   requests
   numpy
   pandas
   ...
   ```

2. **一次安裝所有依賴**
   ```powershell
   pip install -r requirements.txt
   ```

---

## 常見問題

### Q: 我已經安裝了,為什麼還是找不到?

A: 可能安裝到不同的 Python 環境了。請確認:
- 安裝時使用的 Python 路徑
- 啟動後端時使用的 Python 路徑
- 兩者必須相同!

### Q: 如何確認使用哪個 Python?

A: 在啟動後端的終端機中執行:
```powershell
python -c "import sys; print(sys.executable)"
```

### Q: 可以不用 httpx 嗎?

A: 可以,但會有阻塞問題:
- 使用 httpx (異步) → AI 問題不會卡住預測 ✅
- 使用 requests (同步) → AI 問題會阻塞預測 90 秒 ❌

---

## 安裝成功後

1. **重新啟動後端**
2. **測試 AI 功能**
3. **確認預測不會被阻塞**

---

## 需要幫助?

如果安裝仍然失敗,請提供:
1. Python 版本: `python --version`
2. Python 路徑: `python -c "import sys; print(sys.executable)"`
3. 錯誤訊息的完整內容
