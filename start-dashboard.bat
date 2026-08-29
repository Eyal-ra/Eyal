@echo off
REM הפעלת דשבורד הצוות בלחיצה כפולה.
REM בהרצה ראשונה הסקריפט יבקש שם משתמש וסיסמה, ואז יעלה את השרת.
chcp 65001 >nul
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    set "PY=python"
)

%PY% scripts\start_dashboard.py %*

echo.
echo הדשבורד נעצר.
pause
