# restart.ps1 — 殺掉所有 Python process 並重啟 server
# 用法: .\restart.ps1

Write-Host "=== 殺掉所有 Python process ===" -ForegroundColor Yellow
$procs = Get-Process python -ErrorAction SilentlyContinue
if ($procs) {
    $procs | ForEach-Object {
        Write-Host "  Kill PID $($_.Id) (started $($_.StartTime))"
        Stop-Process -Id $_.Id -Force
    }
    Start-Sleep -Seconds 1
    Write-Host "全部殺掉完成" -ForegroundColor Green
} else {
    Write-Host "沒有在跑的 Python process" -ForegroundColor Cyan
}

Write-Host "`n=== 啟動 Server ===" -ForegroundColor Yellow
Set-Location $PSScriptRoot
& "C:/Users/foresight/AppData/Local/Programs/Python/Python312/python.exe" api_entry.py
