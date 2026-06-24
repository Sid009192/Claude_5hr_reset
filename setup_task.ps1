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
#   * "Claude Rearm Watchdog" -- runs at logon to re-arm from the current anchor,
#                                covering full power-off where the self-arm chain died.
#
# Nothing runs continuously. Re-run any time; -Force re-registers cleanly.

$ErrorActionPreference = "Stop"

$ProjectDir = $PSScriptRoot
$Rearm = Join-Path $ProjectDir "schedule_rearm.ps1"

# --- Watchdog: re-arm at every logon (safety net for power-off) -------------
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

$wdAction = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Rearm`"" `
    -WorkingDirectory $ProjectDir
# Scope the logon trigger to THIS user. A bare -AtLogOn means "any user" and
# needs admin to register; "this user" does not.
$CurrentUser = "$env:USERDOMAIN\$env:USERNAME"
$wdTrigger = New-ScheduledTaskTrigger -AtLogOn -User $CurrentUser

Register-ScheduledTask -TaskName "Claude Rearm Watchdog" `
    -Action $wdAction -Trigger $wdTrigger -Settings $settings `
    -Description "Re-arms the Claude sender + ping triggers at logon." -Force | Out-Null
Write-Host "Registered 'Claude Rearm Watchdog' (at logon)." -ForegroundColor Green

# --- Arm the self-rescheduling sender + pings now ---------------------------
Write-Host ""
& powershell -NoProfile -ExecutionPolicy Bypass -File $Rearm

Write-Host ""
Write-Host "Core installed. Inspect:  Get-ScheduledTask -TaskName 'Claude*' | Get-ScheduledTaskInfo"
Write-Host "Remove all:  Get-ScheduledTask -TaskName 'Claude*' | Unregister-ScheduledTask -Confirm:`$false"
