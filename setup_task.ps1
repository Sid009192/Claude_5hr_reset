# Registers the "Claude Auto Sender" scheduled task.
# Run from PowerShell (no admin needed):
#     powershell -ExecutionPolicy Bypass -File .\setup_task.ps1

$ErrorActionPreference = "Stop"

# ======================== EDIT THESE ========================
# When should the FIRST run happen today? (24-hour clock)
$StartHour      = 9     # e.g. 9  = 9 AM,  19 = 7 PM
$StartMinute    = 0     # e.g. 0, 15, 30...

# How often to repeat after the first run.
$IntervalHours  = 5
$IntervalMinutes = 2
# ============================================================

$TaskName   = "Claude Auto Sender"
$ProjectDir = $PSScriptRoot           # this script's own folder — portable, no hardcoded path
$PythonW    = Join-Path $ProjectDir ".venv\Scripts\pythonw.exe"   # no console window
$Script     = Join-Path $ProjectDir "autosend.py"

if (-not (Test-Path $PythonW)) {
    # Fall back to python.exe if pythonw is missing (will flash a brief console).
    $PythonW = Join-Path $ProjectDir ".venv\Scripts\python.exe"
}

# What runs each fire: send one message off-screen, then exit.
$action = New-ScheduledTaskAction `
    -Execute $PythonW `
    -Argument "`"$Script`" --once" `
    -WorkingDirectory $ProjectDir

# When: first at your chosen time today, then repeat on your interval, ~indefinitely.
$interval = New-TimeSpan -Hours $IntervalHours -Minutes $IntervalMinutes
$duration = New-TimeSpan -Days 3650
$startAt  = Get-Date -Hour $StartHour -Minute $StartMinute -Second 0
$trigger  = New-ScheduledTaskTrigger -Once -At $startAt `
                -RepetitionInterval $interval -RepetitionDuration $duration

# Behavior rules, matching your requirements:
#   -AllowStartIfOnBatteries     : run when unplugged
#   -DontStopIfGoingOnBatteries  : don't kill it if you unplug mid-run
#   -StartWhenAvailable          : run a missed fire after waking (never during sleep)
#   -MultipleInstances IgnoreNew : don't stack runs if one is still going
#   WakeToRun is OFF by default  : it will NOT wake the laptop from sleep
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

# Run as you, only when logged on (this also covers the lock screen).
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Sends a message to claude.ai on a fixed schedule, off-screen, in the background." `
    -Force | Out-Null

Write-Host "Task '$TaskName' registered." -ForegroundColor Green
Write-Host "First run: $startAt  then every ${IntervalHours}h ${IntervalMinutes}m."
Write-Host ""
Write-Host "Useful commands:"
Write-Host "  Run now:    Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Inspect:    Get-ScheduledTask -TaskName '$TaskName' | Get-ScheduledTaskInfo"
Write-Host "  Remove:     Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
