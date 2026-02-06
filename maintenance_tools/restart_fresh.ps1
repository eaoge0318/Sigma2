# Complete Cache-Busting and Server Restart Script
# This script ensures NO cached versions are served

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  FULL CACHE CLEAR + SERVER RESTART" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

# Step 1: Kill all Python processes
Write-Host "[1/4] Terminating all Python processes..." -ForegroundColor Yellow
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 1
Write-Host "      ✓ All Python processes killed`n" -ForegroundColor Green

# Step 2: Update CSS file timestamp to force reload
Write-Host "[2/4] Touching CSS file to force browser reload..." -ForegroundColor Yellow
$(Get-Item "static\css\styles.css").LastWriteTime = Get-Date
Write-Host "      ✓ CSS file timestamp updated`n" -ForegroundColor Green

# Step 3: Start server
Write-Host "[3/4] Starting server..." -ForegroundColor Yellow
Start-Process python -ArgumentList "api_entry.py" -WindowStyle Normal
Start-Sleep -Seconds 3
Write-Host "      ✓ Server started on http://localhost:8001`n" -ForegroundColor Green

# Step 4: Open browser with cache-busting URL
Write-Host "[4/4] Opening browser with cache-busting..." -ForegroundColor Yellow
$timestamp = (Get-Date).Ticks
Start-Process "http://localhost:8001?nocache=$timestamp"
Start-Sleep -Seconds 2
Write-Host "      ✓ Browser opened`n" -ForegroundColor Green

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  🎉 COMPLETE!" -ForegroundColor Green
Write-Host "========================================`n" -ForegroundColor Cyan
Write-Host "IMPORTANT: Press Ctrl + Shift + R in the browser to hard refresh!`n" -ForegroundColor Yellow
