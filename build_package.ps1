<#
.SYNOPSIS
    Sigma2 Offline Deployment Packaging Tool
.DESCRIPTION
    Run on dev machine to produce a complete offline deployment package.
    Copies embedded Python + system site-packages + application code.
    Target machine needs ZERO installation.
#>

param(
    [string]$OutputDir = "Sigma2_Deploy_$(Get-Date -Format 'MMdd')",
    [string]$PythonVersion = "3.12.10",
    [string]$SystemPython = "C:/Users/foresight/AppData/Local/Programs/Python/Python312/python.exe",
    [switch]$SkipPythonDownload,
    [switch]$SkipSettings,
    [switch]$AppOnly
)

$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"

$ScriptDir = $PSScriptRoot
$DeployDir = Join-Path $ScriptDir $OutputDir
$AppDir = Join-Path $DeployDir "app"
$PythonDir = Join-Path $DeployDir "python"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Sigma2 Offline Deploy Packager" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ==========================================
# Step 1: Clean old deploy directory
# ==========================================
if (Test-Path $DeployDir) {
    Write-Host "[1/5] Cleaning old deploy directory..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force $DeployDir
}
New-Item -ItemType Directory -Path $DeployDir -Force | Out-Null
New-Item -ItemType Directory -Path $AppDir -Force | Out-Null

# ==========================================
# Step 2-3: Python environment
# ==========================================
if ($AppOnly) {
    Write-Host "[2/5] 跳過 Python（-AppOnly 模式）" -ForegroundColor DarkGray
    Write-Host "[3/5] 跳過 site-packages（-AppOnly 模式）" -ForegroundColor DarkGray
} else {
    $PythonZip = "python-$PythonVersion-embed-amd64.zip"
    $PythonUrl = "https://www.python.org/ftp/python/$PythonVersion/$PythonZip"
    $PythonZipPath = Join-Path $ScriptDir $PythonZip

    if (-not $SkipPythonDownload) {
        Write-Host "[2/5] Setting up embedded Python $PythonVersion ..." -ForegroundColor Yellow
        if (-not (Test-Path $PythonZipPath)) {
            Write-Host "  Downloading $PythonUrl ..."
            Invoke-WebRequest -Uri $PythonUrl -OutFile $PythonZipPath
            Write-Host "  Download complete" -ForegroundColor Green
        } else {
            Write-Host "  Zip already exists, skipping download" -ForegroundColor DarkGray
        }
    } else {
        Write-Host "[2/5] Skipping Python download (--SkipPythonDownload)" -ForegroundColor DarkGray
    }

    Write-Host "  Extracting to $PythonDir ..."
    Expand-Archive -Path $PythonZipPath -DestinationPath $PythonDir -Force

    $pthFile = Join-Path $PythonDir "python312._pth"
    if (Test-Path $pthFile) {
        $pthContent = "python312.zip`r`n.`r`nLib/site-packages`r`n../app`r`nimport site`r`n"
        [System.IO.File]::WriteAllText($pthFile, $pthContent)
        Write-Host "  Modified python312._pth" -ForegroundColor Green
    }
    Write-Host "  Embedded Python ready" -ForegroundColor Green

    # ==========================================
    # Step 3: Copy system site-packages
    # ==========================================
    Write-Host "[3/5] Copying site-packages from system Python..." -ForegroundColor Yellow
    Write-Host "  Source: $SystemPython"

    $sysPackagesPath = & $SystemPython -c "import sysconfig; print(sysconfig.get_paths()['purelib'])" 2>&1
    $sysPackagesPath = $sysPackagesPath.Trim()
    Write-Host "  System site-packages: $sysPackagesPath"

    $targetSitePackages = Join-Path (Join-Path $PythonDir "Lib") "site-packages"
    New-Item -ItemType Directory -Path $targetSitePackages -Force | Out-Null

    Write-Host "  Copying (this may take a few minutes)..."
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    robocopy $sysPackagesPath $targetSitePackages /E /NFL /NDL /NJH /NJS /NC /NS /NP /MT:8 | Out-Null
    $sw.Stop()

    $sizeGB = [math]::Round((Get-ChildItem -Recurse -Path $targetSitePackages | Measure-Object -Property Length -Sum).Sum / 1GB, 2)
    Write-Host "  Copied $sizeGB GB in $([math]::Round($sw.Elapsed.TotalSeconds, 1))s" -ForegroundColor Green

    $sysDLLsPath = Join-Path (Split-Path $SystemPython) "DLLs"
    if (Test-Path $sysDLLsPath) {
        $targetDLLs = Join-Path $PythonDir "DLLs"
        if (-not (Test-Path $targetDLLs)) {
            New-Item -ItemType Directory -Path $targetDLLs -Force | Out-Null
        }
        robocopy $sysDLLsPath $targetDLLs /E /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
        Write-Host "  Copied DLLs directory" -ForegroundColor Green
    }

    $userPackagesPath = & $SystemPython -c "import site; print(site.getusersitepackages())" 2>&1
    $userPackagesPath = $userPackagesPath.Trim()
if (Test-Path $userPackagesPath) {
    Write-Host "  User site-packages: $userPackagesPath"
    Write-Host "  Copying user site-packages..."
    robocopy $userPackagesPath $targetSitePackages /E /NFL /NDL /NJH /NJS /NC /NS /NP /MT:8 | Out-Null
    Write-Host "  Copied user site-packages" -ForegroundColor Green
} else {
    Write-Host "  No user site-packages found, skipping" -ForegroundColor DarkGray
}
} # end else (not AppOnly)

# ==========================================
# Step 4: Copy application code
# ==========================================
Write-Host "[4/5] Copying application code..." -ForegroundColor Yellow

# Directories to copy (純程式碼，不含使用者資料)
$copyDirs = @("backend", "core_logic", "engines", "static", "lib", "ai_agent")
foreach ($dir in $copyDirs) {
    $src = Join-Path $ScriptDir $dir
    if (Test-Path $src) {
        $dst = Join-Path $AppDir $dir
        robocopy $src $dst /E /NFL /NDL /NJH /NJS /NC /NS /NP `
            /XD "__pycache__" ".pytest_cache" | Out-Null
        Write-Host "  Copied $dir/" -ForegroundColor DarkGray
    }
}

# Files to copy
$copyFiles = @(
    "api_entry.py",
    "config.py",
    "settings.json",
    "_train_entry.py",
    "dashboard.html",
    "reindex.py"
)
if ($SkipSettings) {
    $copyFiles = $copyFiles | Where-Object { $_ -ne "settings.json" }
    Write-Host "  Skipping settings.json (-SkipSettings)" -ForegroundColor DarkGray
}
foreach ($f in $copyFiles) {
    $src = Join-Path $ScriptDir $f
    if (Test-Path $src) {
        Copy-Item -Force $src (Join-Path $AppDir $f)
        Write-Host "  Copied $f" -ForegroundColor DarkGray
    }
}

# Create required empty directories
# model/ data/ → 空目錄，客戶端自行產生資料，不帶入開發機的資料
$emptyDirs = @("workspace", "monitor_dashboard", "user_uploads", "user_cache", "user_models", "logs", "model", "data")
foreach ($dir in $emptyDirs) {
    New-Item -ItemType Directory -Path (Join-Path $AppDir $dir) -Force | Out-Null
}
Write-Host "  Created empty dirs: model/ data/ workspace/ logs/ ..." -ForegroundColor DarkGray

# ==========================================
# Step 5: Copy startup and config files
# ==========================================
Write-Host "[5/5] Finalizing deploy package..." -ForegroundColor Yellow

Copy-Item -Force (Join-Path $ScriptDir "start.bat") (Join-Path $DeployDir "start.bat")
Copy-Item -Force (Join-Path $ScriptDir ".env.example") (Join-Path $DeployDir ".env.example")
Copy-Item -Force (Join-Path $DeployDir ".env.example") (Join-Path $DeployDir ".env")

$deployMd = Join-Path $ScriptDir "DEPLOY.md"
if (Test-Path $deployMd) {
    Copy-Item -Force $deployMd (Join-Path $DeployDir "DEPLOY.md")
}

# Generate README.txt
$readmeContent = @"
========================================
  Sigma2 部署包
  打包時間: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
========================================

【目錄結構】
  $OutputDir/
    app/          程式碼（backend, static, engines, ...）
    python/       Python 執行環境 + site-packages
    start.bat     啟動腳本
    .env          環境設定（LLM IP、API Key 等）

【全新部署】
  1. 將整個 $OutputDir 資料夾複製到目標機器
  2. 編輯 .env 設定 LLM 伺服器 IP
  3. 雙擊 start.bat 啟動
  4. 開啟 http://localhost:8001/dashboard

【更新既有部署】（使用 -SkipSettings 打包時）
  1. 停止目標機器上的 Sigma2 服務
  2. 將 app/ 資料夾覆蓋到目標機器的 Sigma2_Deploy/app/
  3. 將 python/ 資料夾覆蓋到目標機器的 Sigma2_Deploy/python/
  4. 不要覆蓋 .env 和 settings.json（保留目標機器設定）
  5. 重新啟動 start.bat

【注意事項】
  - .env：LLM 伺服器位址、API Key 等，每台機器不同
  - app/settings.json：LLM 模型設定，每台機器可能不同
  - app/model/、app/data/、app/user_uploads/：使用者資料，勿覆蓋
"@
$readmeContent | Out-File -FilePath (Join-Path $DeployDir "README.txt") -Encoding utf8
Write-Host "  Created README.txt" -ForegroundColor DarkGray

# ==========================================
# Verify
# ==========================================
if (-not $AppOnly) {
    Write-Host ""
    Write-Host "Verifying embedded Python..." -ForegroundColor Yellow
    $embPython = Join-Path $PythonDir "python.exe"
    & $embPython -c "import fastapi; import pandas; import numpy; import torch; print('All core imports OK')" 2>&1
    $verifyExit = $LASTEXITCODE
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  PACKAGING COMPLETE" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""

# Calculate total size
$totalSize = (Get-ChildItem -Recurse -Path $DeployDir -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
$totalMB = [math]::Round($totalSize / 1MB, 0)
$totalGB = [math]::Round($totalSize / 1GB, 2)
$sizeText = if ($totalGB -ge 1) { "$totalGB GB" } else { "$totalMB MB" }
Write-Host "Deploy folder: $DeployDir" -ForegroundColor Cyan
Write-Host "Total size: $sizeText" -ForegroundColor Cyan

if ($AppOnly) {
    Write-Host "Mode: AppOnly (只有程式碼)" -ForegroundColor Cyan
} elseif ($verifyExit -eq 0) {
    Write-Host "Verify: PASSED" -ForegroundColor Green
} else {
    Write-Host "Verify: FAILED (some imports may be missing)" -ForegroundColor Red
}

Write-Host ""
if ($AppOnly) {
    Write-Host "部署方式 (AppOnly):" -ForegroundColor White
    Write-Host "  1. 停止目標機器的 Sigma2" -ForegroundColor White
    Write-Host "  2. 覆蓋 app/ → Sigma2_Deploy\app\" -ForegroundColor White
    Write-Host "  3. 重新 start.bat" -ForegroundColor White
} else {
    Write-Host "Deployment steps:" -ForegroundColor White
    Write-Host "  1. Copy the entire $OutputDir folder to target machine" -ForegroundColor White
    Write-Host "  2. Edit .env to set LLM server IP" -ForegroundColor White
    Write-Host "  3. Double-click start.bat" -ForegroundColor White
    Write-Host "  4. Open http://localhost:8001/dashboard" -ForegroundColor White
}
Write-Host ""
