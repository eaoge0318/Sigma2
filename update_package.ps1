<#
.SYNOPSIS
    Sigma2 快速更新腳本 — 只更新程式碼，不重建 Python 環境
.DESCRIPTION
    適用於：只修改了 HTML / JS / Python 邏輯，套件沒有變動。
    比 build_package.ps1 快很多（秒級完成）。
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File "update_package.ps1"
    powershell -ExecutionPolicy Bypass -File "update_package.ps1" -OutputDir "Sigma2_Deploy"
#>

param(
    [string]$OutputDir = "Sigma2_Deploy"
)

$ErrorActionPreference = "Continue"
$ScriptDir  = $PSScriptRoot
$DeployDir  = Join-Path $ScriptDir $OutputDir
$AppDir     = Join-Path $DeployDir "app"

# ==========================================
# 客戶端資料目錄（不碰，永不覆蓋）
# ==========================================
# data/        → 客戶上傳的 CSV 資料集
# model/       → 客戶訓練好的模型
# workspace/   → 工作階段資料
# user_uploads/→ 上傳暫存
# user_models/ → 使用者模型
# user_cache/  → 快取
# logs/        → 日誌
$protectedDirs = @("data", "model", "workspace", "user_uploads", "user_models", "user_cache", "logs", "monitor_dashboard")

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Sigma2 快速更新 (程式碼)" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  [保護] 以下目錄不會被更動：" -ForegroundColor Green
foreach ($d in $protectedDirs) { Write-Host "    - $d/" -ForegroundColor DarkGreen }
Write-Host ""

if (-not (Test-Path $DeployDir)) {
    Write-Host "[錯誤] 找不到部署目錄: $DeployDir" -ForegroundColor Red
    Write-Host "  請先執行 build_package.ps1 建立完整封裝" -ForegroundColor Yellow
    exit 1
}

# ==========================================
# 更新程式碼目錄（排除受保護的資料目錄）
# ==========================================
Write-Host "[1/2] 更新程式碼目錄..." -ForegroundColor Yellow

$copyDirs = @("backend", "core_logic", "engines", "static", "lib", "ai_agent")
foreach ($dir in $copyDirs) {
    $src = Join-Path $ScriptDir $dir
    if (Test-Path $src) {
        $dst = Join-Path $AppDir $dir
        robocopy $src $dst /E /NFL /NDL /NJH /NJS /NC /NS /NP /MT:8 `
            /XD "__pycache__" ".pytest_cache" | Out-Null
        Write-Host "  Updated $dir/" -ForegroundColor DarkGray
    }
}

# ==========================================
# 更新程式碼檔案
# ==========================================
Write-Host "[2/2] 更新程式碼檔案..." -ForegroundColor Yellow

$copyFiles = @(
    "api_entry.py",
    "config.py",
    "_train_entry.py",
    "dashboard.html",
    "reindex.py"
)
foreach ($f in $copyFiles) {
    $src = Join-Path $ScriptDir $f
    if (Test-Path $src) {
        Copy-Item -Force $src (Join-Path $AppDir $f)
        Write-Host "  Updated $f" -ForegroundColor DarkGray
    }
}

# .env.example 同步（但不覆蓋客戶端已編輯的 .env）
$envExampleSrc = Join-Path $ScriptDir ".env.example"
$envExampleDst = Join-Path $DeployDir ".env.example"
if (Test-Path $envExampleSrc) {
    Copy-Item -Force $envExampleSrc $envExampleDst
    Write-Host "  Updated .env.example" -ForegroundColor DarkGray
    Write-Host "  (注意: .env 未被覆蓋，請手動確認新增的設定項)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  更新完成！" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "  目標: $AppDir" -ForegroundColor Cyan
Write-Host ""
Write-Host "  重啟 Server 後生效（關閉再雙擊 start.bat）" -ForegroundColor White
Write-Host ""
