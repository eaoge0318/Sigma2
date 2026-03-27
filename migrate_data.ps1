<#
.SYNOPSIS
    Sigma2 換版資料搬移腳本
.DESCRIPTION
    把舊版部署資料夾的使用者資料（CSV、模型、workspace）搬到新版。
    程式碼由新版提供，資料由舊版帶過來。
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File "migrate_data.ps1" -OldDir "Sigma2_Deploy" -NewDir "Sigma2_Deploy_v2"
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$OldDir,   # 舊版資料夾名稱，例如 "Sigma2_Deploy"

    [Parameter(Mandatory=$true)]
    [string]$NewDir    # 新版資料夾名稱，例如 "Sigma2_Deploy_v2"
)

$ErrorActionPreference = "Continue"
$ScriptDir = $PSScriptRoot
$OldApp    = Join-Path $ScriptDir "$OldDir\app"
$NewApp    = Join-Path $ScriptDir "$NewDir\app"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Sigma2 換版資料搬移" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  舊版: $OldDir" -ForegroundColor DarkGray
Write-Host "  新版: $NewDir" -ForegroundColor DarkGray
Write-Host ""

# 檢查目錄存在
if (-not (Test-Path $OldApp)) {
    Write-Host "[錯誤] 找不到舊版目錄: $OldApp" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $NewApp)) {
    Write-Host "[錯誤] 找不到新版目錄: $NewApp" -ForegroundColor Red
    Write-Host "  請先執行 build_package.ps1 -OutputDir $NewDir" -ForegroundColor Yellow
    exit 1
}

# ==========================================
# 搬移使用者資料目錄
# ==========================================
Write-Host "[1/2] 搬移使用者資料..." -ForegroundColor Yellow

$dataDirs = @(
    @{ name="data";         desc="CSV 資料集" },
    @{ name="model";        desc="訓練模型" },
    @{ name="workspace";    desc="工作階段" },
    @{ name="user_uploads"; desc="上傳暫存" },
    @{ name="user_models";  desc="使用者模型" },
    @{ name="user_cache";   desc="快取" },
    @{ name="monitor_dashboard"; desc="看板資料" }
)

foreach ($d in $dataDirs) {
    $src = Join-Path $OldApp $d.name
    $dst = Join-Path $NewApp $d.name
    if (Test-Path $src) {
        $count = (Get-ChildItem -Recurse $src -ErrorAction SilentlyContinue | Measure-Object).Count
        if ($count -gt 0) {
            robocopy $src $dst /E /NFL /NDL /NJH /NJS /NC /NS /NP /MT:8 | Out-Null
            Write-Host "  Migrated $($d.name)/  ($count 個項目，$($d.desc))" -ForegroundColor Green
        } else {
            Write-Host "  Skipped  $($d.name)/  (空目錄)" -ForegroundColor DarkGray
        }
    } else {
        Write-Host "  Skipped  $($d.name)/  (舊版無此目錄)" -ForegroundColor DarkGray
    }
}

# ==========================================
# 搬移 .env（客戶設定）
# ==========================================
Write-Host ""
Write-Host "[2/2] 搬移 .env 設定..." -ForegroundColor Yellow

$oldEnv = Join-Path $ScriptDir "$OldDir\.env"
$newEnv = Join-Path $ScriptDir "$NewDir\.env"
$newEnvExample = Join-Path $ScriptDir "$NewDir\.env.example"

if (Test-Path $oldEnv) {
    Copy-Item -Force $oldEnv $newEnv
    Write-Host "  Migrated .env" -ForegroundColor Green

    # 比對新版 .env.example，提示有沒有新增的設定項
    if (Test-Path $newEnvExample) {
        $oldKeys = (Get-Content $oldEnv | Where-Object { $_ -match "^[^#].*=" } | ForEach-Object { ($_ -split "=")[0].Trim() })
        $exampleKeys = (Get-Content $newEnvExample | Where-Object { $_ -match "^[^#].*=" } | ForEach-Object { ($_ -split "=")[0].Trim() })
        $newKeys = $exampleKeys | Where-Object { $_ -notin $oldKeys }
        if ($newKeys) {
            Write-Host ""
            Write-Host "  [注意] 新版新增了以下設定項，請手動補進 .env：" -ForegroundColor Yellow
            foreach ($k in $newKeys) {
                $defaultLine = Get-Content $newEnvExample | Where-Object { $_ -match "^$k=" }
                Write-Host "    $defaultLine" -ForegroundColor Yellow
            }
        }
    }
} else {
    Write-Host "  找不到舊版 .env，使用新版預設值" -ForegroundColor Yellow
    if (Test-Path $newEnvExample) {
        Copy-Item -Force $newEnvExample $newEnv
    }
}

# ==========================================
# 完成
# ==========================================
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  搬移完成！" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  下一步：" -ForegroundColor White
Write-Host "  1. 確認 $NewDir\.env 設定正確" -ForegroundColor White
Write-Host "  2. 雙擊 $NewDir\start.bat 啟動新版" -ForegroundColor White
Write-Host "  3. 確認功能正常後，可刪除舊版 $OldDir" -ForegroundColor White
Write-Host ""
