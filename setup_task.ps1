# Registers the "Claude Auto Sender" scheduled task.
# Run from PowerShell (no admin needed):
#     powershell -ExecutionPolicy Bypass -File .\setup_task.ps1

$ErrorActionPreference = "Stop"

$TaskName    = "Claude Auto Sender"
$ProjectDir  = "D:\OJAS\Claude\5hr window reset"
$PythonW     = Join-Path $ProjectDir ".venv\Scripts\pythonw.exe"   # no console window
$Script      = Join-Path $ProjectDir "autosend.py"

if (-not (Test-Path $PythonW)) {
    # Fall back to python.exe if pythonw is missing (will flash a brief console).
    $PythonW = Join-Path $ProjectDir ".venv\Scripts\python.exe"
}

# What runs each fire: send one message headless, then exit.
$action = New-ScheduledTaskAction `
    -Execute $PythonW `
    -Argument "`"$Script`" --once" `
    -WorkingDirectory $ProjectDir

# When: first at 2:32 AM today, then repeat every 5 hours 2 minutes, ~indefinitely.
$interval = New-TimeSpan -Hours 5 -Minutes 2
$duration = New-TimeSpan -Days 3650
$startAt  = Get-Date -Hour 2 -Minute 32 -Second 0
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
    -Description "Sends a message to claude.ai every 5h2m starting 2:32 AM, headless, in the background." `
    -Force | Out-Null

Write-Host "Task '$TaskName' registered." -ForegroundColor Green
Write-Host "First run: $startAt  then every 5h 2m."
Write-Host ""
Write-Host "Useful commands:"
Write-Host "  Run now:    Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Inspect:    Get-ScheduledTask -TaskName '$TaskName' | Get-ScheduledTaskInfo"
Write-Host "  Remove:     Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
