@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

:: 1. 取得時間戳記 (YYYYMMDD_HHMM)
for /f "skip=1" %%x in ('wmic os get localdatetime') do if not defined datetime set datetime=%%x
set TIMESTAMP=%datetime:~0,8%_%datetime:~8,4%

:: 2. 設定備份目標資料夾 (位於當前目錄下)
set "BACKUP_NAME=Backup_%TIMESTAMP%"
set "SOURCE_DIR=%~dp0"
set "DEST_DIR=%SOURCE_DIR%%BACKUP_NAME%"

echo ========================================================
echo  正在備份專案到: %BACKUP_NAME%
echo  排除項目: Log, Cache, Git, 舊備份
echo ========================================================

if not exist "%DEST_DIR%" mkdir "%DEST_DIR%"

:: 3. 執行複製 (Robocopy)
:: /E  :: 複製子目錄 (包含空目錄)
:: /XO :: 排除較舊檔案 (若目標已存在)
:: /XD :: 排除目錄 (包含備份目錄本身，避免遞迴複製)
:: /XF :: 排除檔案

robocopy "%SOURCE_DIR%." "%DEST_DIR%" /E ^
    /XD "%BACKUP_NAME%" "Backup_*" ".git" ".vscode" "__pycache__" "d3rlpy_logs" "legacy_files" "venv" "model" ^
    /XF "*.log" "*.tmp" "err.txt" "error_log.txt" "llm_debug.log" "*.bat"

echo.
echo ========================================================
echo  備份完成！
echo  新專案位置: %DEST_DIR%
echo ========================================================
pause
