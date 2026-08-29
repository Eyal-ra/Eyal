@echo off
REM הוספת כרטיס "סקירת דוחות כספיים" ללוח הבקרה.
REM גררו את קובץ ה-HTML של הלוח על הקובץ הזה, או הריצו:
REM     add-card-to-board.bat "C:\נתיב\אל\הלוח\index.html"
chcp 65001 >nul
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    set "PY=python"
)

if "%~1"=="" (
    echo.
    echo גררו את קובץ ה-HTML של לוח הבקרה על הקובץ הזה,
    echo או הריצו:  add-card-to-board.bat "C:\נתיב\אל\index.html"
    echo.
    pause
    exit /b 1
)

%PY% scripts\add_card_to_board.py --board "%~1"
pause
