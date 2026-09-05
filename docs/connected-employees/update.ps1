# Pull the current files from the branch, but only replace what is running if
# the new copy is actually loadable.
#
# Downloading straight over a live installation means one bad push silently
# stops the alerts, and nothing would say so until an arrival went unnoticed.
# So: fetch to a temp folder, syntax-check every file there, and swap only if
# all of them pass. A failed update leaves yesterday's working copy in place.
#
# ASCII only - cmd and the console mangle Hebrew.

param(
  # Parameters so the updater can be exercised against a throwaway folder
  # instead of the live installation.
  [string]$AppDir = 'C:\OfficeSystems\timewatch-presence',
  [string]$Branch = 'claude/connected-employees-dashboard-08zle6'
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$BaseUrl = "https://raw.githubusercontent.com/Eyal-ra/Eyal/$Branch/docs/connected-employees"
$LogPath = Join-Path $AppDir 'data\update.log'
$Files   = @(
  'timewatch-client.js', 'login-form.js', 'attendance-form.js',
  'presence-watcher.js', 'notify-presence.js', 'notify-toast.js',
  'notifier-bridge.js', 'watch-presence.js', 'verify-setup.js', 'probe.js'
)

function Write-Log($text) {
  $line = "{0}  {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $text
  New-Item -ItemType Directory -Force -Path (Split-Path $LogPath) | Out-Null
  Add-Content -Path $LogPath -Value $line -Encoding utf8
  Write-Host $line
}

$staging = Join-Path ([IO.Path]::GetTempPath()) ("tw-update-" + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $staging | Out-Null

try {
  foreach ($f in $Files) {
    # A cache-buster: raw.githubusercontent serves a CDN copy that can be
    # minutes behind, which once had us testing a file that no longer existed.
    $url = "$BaseUrl/$f`?t=$(Get-Random)"
    Invoke-WebRequest $url -OutFile (Join-Path $staging $f) -UseBasicParsing `
      -Headers @{'Cache-Control' = 'no-cache'}
  }

  $node = (Get-Command node -ErrorAction SilentlyContinue)
  if (-not $node) { Write-Log "no node in PATH - update skipped"; exit 1 }

  foreach ($f in $Files) {
    & node --check (Join-Path $staging $f) 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
      Write-Log "$f failed its syntax check - keeping the current version"
      exit 1
    }
  }

  $changed = @()
  foreach ($f in $Files) {
    $new = Join-Path $staging $f
    $old = Join-Path $AppDir $f
    $newHash = (Get-FileHash $new -Algorithm SHA256).Hash
    $oldHash = if (Test-Path $old) { (Get-FileHash $old -Algorithm SHA256).Hash } else { '' }
    if ($newHash -ne $oldHash) {
      Copy-Item $new $old -Force
      $changed += $f
    }
  }

  if ($changed.Count -eq 0) { Write-Log "no change" }
  else { Write-Log ("updated: " + ($changed -join ', ')) }
  exit 0
}
catch {
  Write-Log ("update failed: " + $_.Exception.Message)
  exit 1
}
finally {
  Remove-Item $staging -Recurse -Force -ErrorAction SilentlyContinue
}
