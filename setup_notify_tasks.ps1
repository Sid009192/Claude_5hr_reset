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

function Register-Daily([int]$Hour, [string]$Arg, [string]$Name, [string]$Desc) {
    $action = New-ScheduledTaskAction -Execute $PythonW `
        -Argument "`"$(Join-Path $ProjectDir 'digest.py')`" $Arg" -WorkingDirectory $ProjectDir
    $trigger = New-ScheduledTaskTrigger -Daily -At (Get-Date -Hour $Hour -Minute 0 -Second 0)
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger `
        -Settings $settings -Description $Desc -Force | Out-Null
    Write-Host "  $Name -> daily at ${Hour}:00"
}

# Prep ~8 PM stages tomorrow's digest; publish at midnight sends it.
Register-Daily 20 "--prep"    "Claude Digest Prep"    "Stage tomorrow's Claude window digest."
Register-Daily 0  "--publish" "Claude Digest Publish" "Send the staged Claude window digest."

Write-Host ""
Write-Host "Digest tasks registered."
Write-Host "Remove:  Get-ScheduledTask -TaskName 'Claude Digest*' | Unregister-ScheduledTask -Confirm:`$false"
