@echo off
chcp 65001 >nul
echo ========================================
echo   Sigma2 換版資料搬移
echo ========================================
echo.

set OLD=Sigma2_Deploy
set NEW=Sigma2_Deploy_v2

echo 從 %OLD% 搬到 %NEW%
echo.

robocopy "%OLD%\app\data"      "%NEW%\app\data"      /E /NFL /NDL /NJH /NJS
robocopy "%OLD%\app\model"     "%NEW%\app\model"     /E /NFL /NDL /NJH /NJS
robocopy "%OLD%\app\workspace" "%NEW%\app\workspace" /E /NFL /NDL /NJH /NJS

if exist "%OLD%\.env" (
    copy /Y "%OLD%\.env" "%NEW%\.env"
    echo Copied .env
)

echo.
echo ========================================
echo   完成！請開啟 %NEW%\start.bat
echo ========================================
pause
