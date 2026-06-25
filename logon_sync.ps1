# logon_sync.ps1 -- delayed post-logon TRUTH sync.
#
# Fired by the "Claude Logon Sync" task ~5 min after logon (native trigger delay),
# so the network/session has time to come up after a cold boot. It is the truth
# half of the two-part logon recovery:
#
#   * "Claude Rearm Watchdog" runs INSTANTLY at logon -> pure-arithmetic fossil
#     arm (schedule_rearm.ps1). Can't fail; guarantees you're always scheduled.
#   * THIS task runs 5 min later -> only if the chain looks DEAD does it scrape
#     claude.ai, re-anchor last_reset.txt to the real reset, and re-arm from
#     truth (autosend.py --once). A healthy chain is left alone (no browser).
#
# "Dead" = reset_schedule.py --stale prints STALE (anchor older than one send
# cycle + grace). When healthy it prints FRESH and we do nothing -- the instant
# fossil arm already did the right thing, so no needless boot-time browser launch.

$ErrorActionPreference = "Stop"

$ProjectDir = $PSScriptRoot
$Python  = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$PythonW = Join-Path $ProjectDir ".venv\Scripts\pythonw.exe"   # no console flash
if (-not (Test-Path $PythonW)) { $PythonW = $Python }

$state = (& $Python (Join-Path $ProjectDir "reset_schedule.py") "--stale").Trim()
Write-Host "Logon sync: anchor is $state."

if ($state -eq "STALE") {
    # Chain likely died across a power-off. Do a real scrape-and-resync: this
    # re-anchors last_reset.txt to the live usage timer (sending only if there is
    # no active window) and then re-arms the next send + pings from that truth.
    Write-Host "Re-syncing from claude.ai (scrape + re-anchor + re-arm)..."
    & $PythonW (Join-Path $ProjectDir "autosend.py") "--once"
} else {
    # Healthy chain -- the instant fossil arm already scheduled correctly.
    Write-Host "Chain healthy; nothing to do."
}
