@echo off
echo ========================================
echo 檢查 Python 環境並安裝 httpx
echo ========================================
echo.

echo 1. 當前 Python 路徑:
python -c "import sys; print(sys.executable)"
echo.

echo 2. 嘗試安裝 httpx...
python -m pip install httpx
echo.

echo 3. 驗證安裝:
python -c "import httpx; print('✅ httpx 版本:', httpx.__version__)"
echo.

echo 4. 啟動後端...
python api_entry.py

pause
