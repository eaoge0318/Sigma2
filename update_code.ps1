<#
.SYNOPSIS
    Sigma2 程式碼熱更新包 — 打包程式碼 + Python，不含模型/設定/使用者資料
.DESCRIPTION
    在開發機跑這個腳本，產出一個更新 zip。
    到目標機器解壓後覆蓋對應目錄即可。
    預設包含 Python 環境（含 site-packages），加 -NoPython 可跳過。
.EXAMPLE
    .\update_code.ps1                          # 程式碼 + Python
    .\update_code.ps1 -NoPython                # 只有程式碼
    .\update_code.ps1 -OutputName "Update_v2"  # 自訂名稱
#>

param(
    [string]$OutputName = "Sigma2_Update_$(Get-Date -Format 'MMdd_HHmm')",
    [string]$SystemPython = "C:/Users/foresight/AppData/Local/Programs/Python/Python312/python.exe",
    [switch]$NoPython
)

$ErrorActionPreference = "Continue"
$ScriptDir = $PSScriptRoot
$TempDir = Join-Path $ScriptDir $OutputName
$ZipPath = Join-Path $ScriptDir "$OutputName.zip"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Sigma2 程式碼更新包" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Clean
if (Test-Path $TempDir) { Remove-Item -Recurse -Force $TempDir }
if (Test-Path $ZipPath) { Remove-Item -Force $ZipPath }
New-Item -ItemType Directory -Path $TempDir -Force | Out-Null

# ── 要打包的程式碼目錄（不含使用者資料/模型/Python）──
$codeDirs = @("backend", "core_logic", "engines", "static", "lib", "ai_agent")

foreach ($dir in $codeDirs) {
    $src = Join-Path $ScriptDir $dir
    if (Test-Path $src) {
        $dst = Join-Path $TempDir $dir
        robocopy $src $dst /E /NFL /NDL /NJH /NJS /NC /NS /NP `
            /XD "__pycache__" ".pytest_cache" "node_modules" | Out-Null
        Write-Host "  v $dir/" -ForegroundColor Green
    }
}

# ── 要打包的根目錄程式檔（不含 .env / settings.json）──
$codeFiles = @(
    "api_entry.py",
    "config.py",
    "_train_entry.py",
    "dashboard.html",
    "reindex.py",
    "start.bat",
    "restart.ps1",
    "FORCE_STOP_SIGMA.bat",
    "requirements.txt"
)

foreach ($f in $codeFiles) {
    $src = Join-Path $ScriptDir $f
    if (Test-Path $src) {
        Copy-Item -Force $src (Join-Path $TempDir $f)
        Write-Host "  v $f" -ForegroundColor Green
    }
}

# ── 不打包的東西（確認清單）──
Write-Host ""
Write-Host "  ── 以下不包含在更新包中 ──" -ForegroundColor DarkGray
Write-Host "  x .env（目標機器自己的設定）" -ForegroundColor DarkGray
Write-Host "  x settings.json（目標機器自己的 LLM 設定）" -ForegroundColor DarkGray
Write-Host "  x model/（訓練模型）" -ForegroundColor DarkGray
Write-Host "  x data/ user_uploads/ user_cache/（使用者資料）" -ForegroundColor DarkGray
Write-Host ""

# ── Python 環境（預設包含）──
if (-not $NoPython) {
    Write-Host "[Python] 打包 Python 環境 + site-packages..." -ForegroundColor Yellow

    $PythonZip = "python-3.12.10-embed-amd64.zip"
    $PythonZipPath = Join-Path $ScriptDir $PythonZip
    $PythonDir = Join-Path $TempDir "python"

    if (Test-Path $PythonZipPath) {
        Write-Host "  Extracting embedded Python..." -ForegroundColor DarkGray
        Expand-Archive -Path $PythonZipPath -DestinationPath $PythonDir -Force

        # Modify python312._pth
        $pthFile = Join-Path $PythonDir "python312._pth"
        if (Test-Path $pthFile) {
            $pthContent = "python312.zip`r`n.`r`nLib/site-packages`r`n../app`r`nimport site`r`n"
            [System.IO.File]::WriteAllText($pthFile, $pthContent)
        }

        # Copy system site-packages
        $sysPackagesPath = & $SystemPython -c "import sysconfig; print(sysconfig.get_paths()['purelib'])" 2>&1
        $sysPackagesPath = $sysPackagesPath.Trim()
        $targetSitePackages = Join-Path (Join-Path $PythonDir "Lib") "site-packages"
        New-Item -ItemType Directory -Path $targetSitePackages -Force | Out-Null

        Write-Host "  Copying site-packages (this may take a few minutes)..." -ForegroundColor DarkGray
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        robocopy $sysPackagesPath $targetSitePackages /E /NFL /NDL /NJH /NJS /NC /NS /NP /MT:8 | Out-Null
        $sw.Stop()

        # Copy DLLs
        $sysDLLsPath = Join-Path (Split-Path $SystemPython) "DLLs"
        if (Test-Path $sysDLLsPath) {
            $targetDLLs = Join-Path $PythonDir "DLLs"
            New-Item -ItemType Directory -Path $targetDLLs -Force | Out-Null
            robocopy $sysDLLsPath $targetDLLs /E /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
        }

        # Copy user site-packages
        $userPackagesPath = & $SystemPython -c "import site; print(site.getusersitepackages())" 2>&1
        $userPackagesPath = $userPackagesPath.Trim()
        if (Test-Path $userPackagesPath) {
            robocopy $userPackagesPath $targetSitePackages /E /NFL /NDL /NJH /NJS /NC /NS /NP /MT:8 | Out-Null
        }

        $sizeGB = [math]::Round((Get-ChildItem -Recurse -Path $PythonDir -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum / 1GB, 2)
        Write-Host "  v Python 環境 ($sizeGB GB) in $([math]::Round($sw.Elapsed.TotalSeconds, 1))s" -ForegroundColor Green
    } else {
        Write-Host "  ! 找不到 $PythonZip，跳過 Python 打包" -ForegroundColor Red
        Write-Host "    請先跑一次 build_package.ps1 下載 Python zip" -ForegroundColor Red
    }
} else {
    Write-Host "[Python] 跳過（-NoPython）" -ForegroundColor DarkGray
}

# ── 產生部署說明 ──
$hasPython = (-not $NoPython) -and (Test-Path (Join-Path $TempDir "python"))
$deployInstructions = if ($hasPython) {
    "覆蓋整個 Sigma2_Deploy 目錄（app/ 和 python/ 都覆蓋）"
} else {
    "覆蓋 Sigma2_Deploy\app\ 目錄"
}
$readme = @"
# Sigma2 程式碼更新包
# 產生時間: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
# 包含 Python: $(if($hasPython){'是'}else{'否'})
#
# 使用方式:
#   1. 在目標機器停止 Sigma2 服務
#   2. $deployInstructions
#   3. 重新啟動 start.bat
#
# 注意: 此更新包不包含 .env、settings.json、模型、使用者資料
#       目標機器的設定和資料不會被覆蓋
"@
$readme | Out-File -FilePath (Join-Path $TempDir "_UPDATE_README.txt") -Encoding utf8

# ── 壓縮 ──
Write-Host "Compressing..." -ForegroundColor Yellow
Compress-Archive -Path "$TempDir\*" -DestinationPath $ZipPath -Force

$sizeMB = [math]::Round((Get-Item $ZipPath).Length / 1MB, 1)

# Clean temp
Remove-Item -Recurse -Force $TempDir

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  更新包已產生!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  檔案: $ZipPath" -ForegroundColor Cyan
Write-Host "  大小: $sizeMB MB" -ForegroundColor Cyan
Write-Host ""
Write-Host "  部署方式:" -ForegroundColor White
Write-Host "  1. 複製 zip 到目標機器" -ForegroundColor White
Write-Host "  2. 停止 Sigma2" -ForegroundColor White
Write-Host "  3. 解壓覆蓋到 Sigma2_Deploy\app\" -ForegroundColor White
Write-Host "  4. 重新 start.bat" -ForegroundColor White
Write-Host ""
