# Put the "who is clocked in now" card into dashboard.html and point the
# poller at that folder.
#
# The dashboard is a live file ten people's work depends on, so: back it up
# first, insert between markers that make a re-run replace rather than
# duplicate, and default to showing the change instead of making it.
#
#   .\install-card.ps1              # show what would change
#   .\install-card.ps1 -Apply       # back up and change it
#
# ASCII only - the console mangles Hebrew.

param(
  # Empty by default and found by searching. The path has Hebrew folder names
  # that render right-to-left, so typing it from a screenshot gets the order
  # wrong - which it already did once.
  [string]$Dashboard = '',
  [string]$AppDir = 'C:\OfficeSystems\timewatch-presence',
  [string]$Branch = 'claude/connected-employees-dashboard-08zle6',
  [switch]$Apply
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$BaseUrl = "https://raw.githubusercontent.com/Eyal-ra/Eyal/$Branch/docs/connected-employees"
$Begin = '<!-- BEGIN timewatch-presence-card -->'
$End = '<!-- END timewatch-presence-card -->'

if (-not $Dashboard) {
  Write-Host "looking for dashboard.html ..."
  $roots = @('Y:\Dropbox', "$env:USERPROFILE\Dropbox") | Where-Object { Test-Path $_ }
  $found = @()
  foreach ($root in $roots) {
    $found += Get-ChildItem $root -Filter 'dashboard.html' -Recurse -File `
      -ErrorAction SilentlyContinue -Depth 5
  }
  # Backups and copies keep the same name; the one being edited is the one
  # that changed most recently.
  $found = $found | Where-Object { $_.FullName -notmatch '\.bak|_bak|backup|conflicted copy' } |
    Sort-Object LastWriteTime -Descending
  if ($found.Count -eq 0) {
    Write-Host "no dashboard.html found under: $($roots -join ', ')" -ForegroundColor Red
    Write-Host "pass it directly:  .\install-card.ps1 -Dashboard 'X:\path\dashboard.html'"
    exit 1
  }
  if ($found.Count -gt 1) {
    Write-Host "found $($found.Count) - using the most recently changed:"
    $found | Select-Object -First 5 | ForEach-Object {
      "    {0:yyyy-MM-dd HH:mm}  {1}" -f $_.LastWriteTime, $_.FullName
    }
  }
  $Dashboard = $found[0].FullName
}

if (-not (Test-Path $Dashboard)) {
  Write-Host "dashboard not found: $Dashboard" -ForegroundColor Red
  exit 1
}

$card = (Invoke-WebRequest "$BaseUrl/panel.html`?t=$(Get-Random)" -UseBasicParsing `
  -Headers @{'Cache-Control' = 'no-cache'}).Content
$block = "$Begin`r`n$card`r`n$End"

$html = Get-Content $Dashboard -Raw -Encoding UTF8
$already = $html.Contains($Begin)

if ($already) {
  $pattern = [regex]::Escape($Begin) + '[\s\S]*?' + [regex]::Escape($End)
  $updated = [regex]::Replace($html, $pattern, [System.Text.RegularExpressions.MatchEvaluator]{ param($m) $block })
  $where = 'replacing the card already there'
}
elseif ($html -match '(?i)</body>') {
  $updated = $html -replace '(?i)</body>', "$block`r`n</body>"
  $where = 'before </body> - move the block into the private section if you prefer'
}
else {
  $updated = $html + "`r`n" + $block
  $where = 'appended at the end - the file has no </body>'
}

$folder = Split-Path $Dashboard -Parent
Write-Host ""
Write-Host "dashboard : $Dashboard"
Write-Host "card      : $($card.Length) chars, $where"
Write-Host "data      : the poller will write presence.json into $folder"

if (-not $Apply) {
  Write-Host ""
  Write-Host "Nothing changed. Re-run with -Apply to back up and insert." -ForegroundColor Yellow
  exit 0
}

$backup = "$Dashboard.bak-$(Get-Date -Format 'yyyyMMdd-HHmm')"
Copy-Item $Dashboard $backup
Write-Host "backup    : $backup" -ForegroundColor Green

# UTF-8 with a BOM, which is what the file already is - writing it without
# one would turn every Hebrew label in the dashboard into noise.
$utf8Bom = New-Object System.Text.UTF8Encoding($true)
[System.IO.File]::WriteAllText($Dashboard, $updated, $utf8Bom)
Write-Host "dashboard : card inserted" -ForegroundColor Green

# Tell the poller where to publish, keeping whatever else is configured.
$settingsPath = Join-Path $AppDir 'employees.json'
if (Test-Path $settingsPath) {
  $settings = Get-Content $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
  if (-not $settings.PSObject.Properties.Name.Contains('dashboard')) {
    $settings | Add-Member -NotePropertyName dashboard -NotePropertyValue ([pscustomobject]@{})
  }
  $settings.dashboard | Add-Member -NotePropertyName publishTo -NotePropertyValue @($folder) -Force
  $json = $settings | ConvertTo-Json -Depth 10
  [System.IO.File]::WriteAllText($settingsPath, $json, (New-Object System.Text.UTF8Encoding($false)))
  Write-Host "settings  : publishTo set to $folder" -ForegroundColor Green
}

# A failed poll here must not hide the undo instructions below - the card is
# already in, and the next scheduled run will fill it in anyway.
Push-Location $AppDir
try { & node watch-presence.js }
catch { Write-Host "first poll failed: $($_.Exception.Message)" -ForegroundColor Yellow }
finally { Pop-Location }

Write-Host ""
Write-Host "Done. Reload the dashboard - the card is at the bottom." -ForegroundColor Green
Write-Host "To undo:  Copy-Item '$backup' '$Dashboard' -Force"
Write-Host ""
