@echo off
:: 切換編碼以避免中文路徑問題
chcp 65001 > nul
echo Installing d3rlpy...
python -m pip install d3rlpy
if %errorlevel% neq 0 (
    echo Installation failed.
    exit /b %errorlevel%
)
echo Installation successful.
