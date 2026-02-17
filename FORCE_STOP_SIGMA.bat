@echo off
chcp 65001 > nul
echo ===================================================
echo   Sigma2 強制關閉程式 (Force Stop Script)
echo   正在清理系統背景殘留程序...
echo ===================================================
echo.

:: 1. 根據 Port 8001 (API Service) 刪除進程
echo [1/3] 正在掃描 Port 8001 (API Service)...
set found_port=0
for /f "tokens=5" %%a in ('netstat -aon ^| find ":8001" ^| find "LISTENING"') do (
    echo     - 發現 PID: %%a，正在強制終止...
    taskkill /F /PID %%a /T > nul 2>&1
    set found_port=1
)
if %found_port%==0 echo     - Port 8001 無佔用。

:: 2. 根據 Port 6006 (Tensorboard - 如果有開啟) 刪除進程
echo [2/3] 正在掃描 Port 6006 (Tensorboard)...
for /f "tokens=5" %%a in ('netstat -aon ^| find ":6006" ^| find "LISTENING"') do (
    echo     - 發現 PID: %%a，正在強制終止...
    taskkill /F /PID %%a /T > nul 2>&1
)

:: 3. 根據進程名稱與命令行特徵刪除 (雙重保險)
echo [3/3] 正在掃描殘留的 Python 後台進程 (wmic)...

:: 終止包含 api_entry 的 Python 進程
wmic process where "name='python.exe' and commandline like '%api_entry%'" call terminate > nul 2>&1

:: 終止包含 uvicorn 的 Python 進程
wmic process where "name='python.exe' and commandline like '%uvicorn%'" call terminate > nul 2>&1

echo.
echo ---------------------------------------------------
echo   清理完成。
echo   如果仍有問題，請檢查是否有其他 Python 視窗未關閉。
echo ---------------------------------------------------
pause
