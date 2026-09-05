# Install the TimeWatch presence poller as a scheduled task.
# ASCII only on purpose: cmd and the PowerShell console mangle Hebrew, and an
# installer that garbles its own error messages is worse than one in English.
# Run it again any time - it updates the files and re-registers the task.

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$AppDir    = 'C:\OfficeSystems\timewatch-presence'
$EnvPath   = 'C:\OfficeSecrets\timewatch.env'
$TaskName  = 'TimeWatchPresence'
$Branch    = 'claude/connected-employees-dashboard-08zle6'
$BaseUrl   = "https://raw.githubusercontent.com/Eyal-ra/Eyal/$Branch/docs/connected-employees"
$Files     = @(
  'timewatch-client.js', 'login-form.js', 'attendance-form.js',
  'presence-watcher.js', 'notify-presence.js', 'notify-toast.js',
  'notifier-bridge.js', 'watch-presence.js', 'update.ps1',
  'verify-setup.js', 'probe.js', 'employees.json'
)

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }

Step "1/6 Checking Node.js"
$node = (Get-Command node -ErrorAction SilentlyContinue)
if (-not $node) { Write-Host "Node.js not found in PATH. Install it, then run this again." -ForegroundColor Red; exit 1 }
Write-Host ("    " + (& node --version) + "  on " + $env:COMPUTERNAME)

Step "2/6 Downloading files to $AppDir"
New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
foreach ($f in $Files) {
  Invoke-WebRequest "$BaseUrl/$f" -OutFile (Join-Path $AppDir $f) -UseBasicParsing
  Write-Host "    $f"
}

Step "3/6 Credentials"
New-Item -ItemType Directory -Force -Path (Split-Path $EnvPath) | Out-Null
$needsPassword = $true
if (Test-Path $EnvPath) {
  $existing = Get-Content $EnvPath -Raw
  if ($existing -match '(?m)^TIMEWATCH_PASSWORD=\S') { $needsPassword = $false; Write-Host "    already set - leaving it alone" }
}
if ($needsPassword) {
  Write-Host "    The password is read here and written only to $EnvPath."
  Write-Host "    It is never echoed and never leaves this machine."
  $secure = Read-Host "    TimeWatch password for eyal@cpateam.co.il" -AsSecureString
  $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
  @(
    'TIMEWATCH_COMPANY=6979',
    'TIMEWATCH_USER=eyal@cpateam.co.il',
    "TIMEWATCH_PASSWORD=$plain",
    'TIMEWATCH_BASE_URL=https://a.timewatch.co.il',
    'TIMEWATCH_LOGIN_PATH=/user/login.php',
    'TIMEWATCH_ATTENDANCE_PATH=/update.php'
    # UTF-8, not ASCII: ASCII would silently turn any non-English character
    # in the password into a question mark, and a corrupted credential looks
    # exactly like a wrong one. The reader trims the BOM PowerShell adds.
  ) | Set-Content -Path $EnvPath -Encoding utf8
  $plain = $null
  Write-Host "    written to $EnvPath"
}

Step "4/6 First run"
Push-Location $AppDir
& node watch-presence.js
$firstRun = $LASTEXITCODE
Pop-Location

Step "5/6 Scheduling every 5 minutes"
# Runs only while you are logged on: no stored password, and alerts you are
# not there to read are not worth a credential sitting in the task scheduler.
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
  -Argument "-NoProfile -WindowStyle Hidden -Command `"& node watch-presence.js --quiet`"" `
  -WorkingDirectory $AppDir
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
  -RepetitionInterval (New-TimeSpan -Minutes 5)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
  -Settings $settings -Description 'Poll TimeWatch and alert on arrivals and departures' | Out-Null
Write-Host "    task '$TaskName' registered"

Step "6/6 Scheduling hourly updates"
# So a fix does not need anyone to paste anything: the updater fetches to a
# temp folder, syntax-checks every file, and swaps only if all of them pass.
# A bad push leaves the working copy alone rather than stopping the alerts.
$updateTask = 'TimeWatchPresenceUpdate'
$uAction = New-ScheduledTaskAction -Execute 'powershell.exe' `
  -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$AppDir\update.ps1`"" `
  -WorkingDirectory $AppDir
$uTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) `
  -RepetitionInterval (New-TimeSpan -Hours 1)
Unregister-ScheduledTask -TaskName $updateTask -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $updateTask -Action $uAction -Trigger $uTrigger `
  -Settings $settings -Description 'Update the TimeWatch presence poller' | Out-Null
Write-Host "    task '$updateTask' registered - fixes arrive on their own"

Write-Host ""
if ($firstRun -eq 0) {
  Write-Host "Done. It polls every 5 minutes while you are logged on." -ForegroundColor Green
  Write-Host "Current state: $AppDir\data\presence.json"
} else {
  Write-Host "Installed, but the first read failed - see the message above." -ForegroundColor Yellow
  Write-Host "For detail run:  cd $AppDir ; node verify-setup.js"
}
Write-Host "To stop it:  Unregister-ScheduledTask -TaskName $TaskName -Confirm:`$false"
Write-Host "             Unregister-ScheduledTask -TaskName $updateTask -Confirm:`$false"
Write-Host ""
