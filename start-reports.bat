@echo off
REM מערכת סקירת וסגירת דוחות כספיים - הפעלה בלחיצה כפולה.
REM עולה על פורט 9998, לצד לוח הבקרה הראשי ב-9999.
chcp 65001 >nul
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    set "PY=python"
)

%PY% scripts\start_reports.py %*

echo.
echo המערכת נעצרה.
pause
