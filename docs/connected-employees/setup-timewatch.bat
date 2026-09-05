@echo off
REM ============================================================
REM  TimeWatch presence - one-click setup for EYAL
REM
REM  Downloads the code, asks for the password once, and runs the
REM  check. Leaves a report at C:\timewatch-test\result.txt.
REM
REM  ASCII only on purpose: cmd mangles Hebrew in .bat files.
REM  The Hebrew you see below comes from node, not from here.
REM ============================================================
setlocal
chcp 65001 >nul
title TimeWatch presence - setup

set "DIR=C:\timewatch-test"
set "ENVF=C:\OfficeSecrets\timewatch.env"
set "BASE=https://raw.githubusercontent.com/Eyal-ra/Eyal/claude/connected-employees-dashboard-08zle6/docs/connected-employees"

where node >nul 2>&1
if errorlevel 1 (
  echo.
  echo   [X] Node.js not found on PATH.
  echo       Tell Claude - there is another way to run this.
  echo.
  pause
  exit /b 1
)

echo.
echo   === 1/3  Downloading the code ===
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; New-Item -ItemType Directory -Force -Path '%DIR%' | Out-Null; foreach($f in 'timewatch-client.js','login-form.js','attendance-form.js','employees.json','verify-setup.js'){ Invoke-WebRequest ('%BASE%/'+$f) -OutFile ('%DIR%\'+$f) -UseBasicParsing }"
if errorlevel 1 (
  echo   [X] Download failed. Check the internet connection.
  pause
  exit /b 1
)
echo   [v] 5 files downloaded

echo.
echo   === 2/3  Credentials ===
if exist "%ENVF%" (
  echo   [v] %ENVF% already exists - keeping it
) else (
  if not exist "C:\OfficeSecrets" mkdir "C:\OfficeSecrets"
  REM Everything except the password is written here in the clear;
  REM the password is read without echo and appended by PowerShell,
  REM so it never appears on screen or in the command history.
  > "%ENVF%" echo TIMEWATCH_COMPANY=6979
  >> "%ENVF%" echo TIMEWATCH_USER=eyal@cpateam.co.il
  >> "%ENVF%" echo TIMEWATCH_BASE_URL=https://a.timewatch.co.il
  >> "%ENVF%" echo TIMEWATCH_LOGIN_PATH=/user/login.php
  >> "%ENVF%" echo TIMEWATCH_ATTENDANCE_PATH=/update.php
  echo.
  echo   Type the TimeWatch password (it will not be shown):
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=Read-Host '  password' -AsSecureString; $b=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($s); $t=[Runtime.InteropServices.Marshal]::PtrToStringAuto($b); [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b); Add-Content -Path '%ENVF%' -Value ('TIMEWATCH_PASSWORD=' + $t)"
  echo   [v] saved to %ENVF%
)

echo.
echo   === 3/3  Checking against TimeWatch ===
echo.
cd /d "%DIR%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "node verify-setup.js 2>&1 | Tee-Object -FilePath '%DIR%\result.txt'"

echo.
echo   ============================================================
echo   Report saved to: %DIR%\result.txt
echo   Send that file (or a screenshot of this window) to Claude.
echo   ============================================================
echo.
pause
