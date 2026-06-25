# Installs the daily DIGEST tasks (prep + publish). The pings are NOT here --
# they are one-time tasks armed by schedule_rearm.ps1 (see setup_task.ps1).
#     powershell -ExecutionPolicy Bypass -File .\setup_notify_tasks.ps1

$ErrorActionPreference = "Stop"

$ProjectDir = $PSScriptRoot
$Python  = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$PythonW = Join-Path $ProjectDir ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $PythonW)) { $PythonW = $Python }

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

function Register-Daily([int]$Hour, [int]$Minute, [string]$Arg, [string]$Name, [string]$Desc) {
    $action = New-ScheduledTaskAction -Execute $PythonW `
        -Argument "`"$(Join-Path $ProjectDir 'digest.py')`" $Arg" -WorkingDirectory $ProjectDir
    $trigger = New-ScheduledTaskTrigger -Daily -At (Get-Date -Hour $Hour -Minute $Minute -Second 0)
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger `
        -Settings $settings -Description $Desc -Force | Out-Null
    Write-Host ("  {0} -> daily at {1:00}:{2:00}  ({3})" -f $Name, $Hour, $Minute, $Arg)
}

# 10 PM stages TOMORROW's digest; just after midnight publishes TODAY -- which,
# now that the date has rolled, IS the same day that was "tomorrow" at 10 PM, so
# the staged file matches and is used (no rebuild).
Register-Daily 22 0 "--prep tomorrow" "Claude Digest Prep"    "Stage tomorrow's Claude window digest (10 PM)."
Register-Daily 0  5 "--publish today" "Claude Digest Publish" "Publish today's Claude window digest to Telegram + calendar (just after midnight)."

Write-Host ""
Write-Host "Digest tasks registered."
Write-Host "Remove:  Get-ScheduledTask -TaskName 'Claude Digest*' | Unregister-ScheduledTask -Confirm:`$false"
