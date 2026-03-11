@echo off
chcp 65001 >nul
title Sigma2 Server

echo ========================================
echo   Sigma2 Agentic Reasoning API
echo ========================================

REM --- 讀取 .env 設定 ---
if exist "%~dp0.env" (
    echo [設定] 載入 .env ...
    for /f "usebackq tokens=1,* delims==" %%A in ("%~dp0.env") do (
        REM 跳過註解和空行
        echo %%A | findstr /r "^#" >nul 2>&1
        if errorlevel 1 (
            if not "%%A"=="" (
                set "%%A=%%B"
            )
        )
    )
)

REM --- 偵測 Python ---
if exist "%~dp0python\python.exe" (
    set "PYTHON=%~dp0python\python.exe"
    echo [Python] 使用嵌入式 Python
) else if exist "%~dp0venv\Scripts\python.exe" (
    set "PYTHON=%~dp0venv\Scripts\python.exe"
    echo [Python] 使用 venv Python
) else (
    set "PYTHON=python"
    echo [Python] 使用系統 Python
)

echo [Python] %PYTHON%

REM --- 切換到程式目錄 ---
pushd "%~dp0"

REM --- 如果有 app 子目錄（build_package 產出的結構），切進去 ---
if exist "%~dp0app\api_entry.py" (
    pushd "%~dp0app"
)

echo [啟動] 啟動 Sigma2 Server ...
echo ========================================
"%PYTHON%" api_entry.py

echo.
echo Server 已停止。
pause
