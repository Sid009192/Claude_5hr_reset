# Installs the self-rescheduling (Option A) scheduling core.
#     powershell -ExecutionPolicy Bypass -File .\setup_task.ps1
#
# What it sets up:
#   * "Claude Auto Sender"   -- one-time task that smart-syncs the window and
#                               re-arms itself + the pings each run. (Created by
#                               schedule_rearm.ps1; this script triggers the first
#                               arming, which REPLACES any old repetition-based
#                               "Claude Auto Sender" cleanly.)
#   * "Claude Reset Ping 2h" / "...1.5h" -- one-time ping tasks, re-armed each cycle.
#   * "Claude Rearm Watchdog" -- runs INSTANTLY at logon to fossil-arm from the
#                                current anchor (pure arithmetic, can't fail).
#   * "Claude Logon Sync"     -- runs ~5 min after logon; only if the chain looks
#                                dead (stale anchor) does it scrape claude.ai and
#                                re-anchor from truth. Covers power-off where the
#                                self-arm chain died, after the network is up.
#
# Nothing runs continuously. Re-run any time; -Force re-registers cleanly.

$ErrorActionPreference = "Stop"

$ProjectDir = $PSScriptRoot
$Rearm     = Join-Path $ProjectDir "schedule_rearm.ps1"
$LogonSync = Join-Path $ProjectDir "logon_sync.ps1"
$CurrentUser = "$env:USERDOMAIN\$env:USERNAME"

# --- Watchdog: re-arm at every logon (safety net for power-off) -------------
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

$wdAction = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Rearm`"" `
    -WorkingDirectory $ProjectDir
# Scope the logon trigger to THIS user. A bare -AtLogOn means "any user" and
# needs admin to register; "this user" does not. ($CurrentUser set at top.)
$wdTrigger = New-ScheduledTaskTrigger -AtLogOn -User $CurrentUser

Register-ScheduledTask -TaskName "Claude Rearm Watchdog" `
    -Action $wdAction -Trigger $wdTrigger -Settings $settings `
    -Description "Re-arms the Claude sender + ping triggers at logon." -Force | Out-Null
Write-Host "Registered 'Claude Rearm Watchdog' (at logon, instant fossil arm)." -ForegroundColor Green

# --- Logon Sync: delayed truth-resync after a dead-chain power-off ----------
# Fires 5 min after logon (native trigger delay) so the network is up, then
# logon_sync.ps1 scrapes + re-anchors ONLY if the anchor is stale. Allow a
# longer run window than the watchdog since it may launch a browser.
$syncSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

$syncAction = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$LogonSync`"" `
    -WorkingDirectory $ProjectDir
$syncTrigger = New-ScheduledTaskTrigger -AtLogOn -User $CurrentUser
$syncTrigger.Delay = "PT5M"   # wait 5 min after logon for boot/network to settle

Register-ScheduledTask -TaskName "Claude Logon Sync" `
    -Action $syncAction -Trigger $syncTrigger -Settings $syncSettings `
    -Description "5 min after logon, re-syncs from claude.ai if the schedule chain died." -Force | Out-Null
Write-Host "Registered 'Claude Logon Sync' (logon +5 min, truth re-sync if stale)." -ForegroundColor Green

# --- Arm the self-rescheduling sender + pings now ---------------------------
Write-Host ""
& powershell -NoProfile -ExecutionPolicy Bypass -File $Rearm

Write-Host ""
Write-Host "Core installed. Inspect:  Get-ScheduledTask -TaskName 'Claude*' | Get-ScheduledTaskInfo"
Write-Host "Remove all:  Get-ScheduledTask -TaskName 'Claude*' | Unregister-ScheduledTask -Confirm:`$false"
