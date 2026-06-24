# schedule_rearm.ps1 -- the "brain" of the self-rescheduling (Option A) system.
#
# Asks reset_schedule.py for the exact next send + ping fire-times (derived from
# last_reset.txt, the real anchor) and (re)registers them as ONE-TIME triggers on
# the sender + ping tasks. Nothing runs continuously: this is invoked
#   (a) at the end of every sender run (autosend.py --once re-arms the next cycle),
#   (b) by the at-logon watchdog (covers full power-off where the chain died),
#   (c) once by setup_task.ps1 at install.
#
# Idempotent: -Force just overwrites each task's single trigger with the latest
# computed time.

$ErrorActionPreference = "Stop"

$ProjectDir = $PSScriptRoot
$Python  = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$PythonW = Join-Path $ProjectDir ".venv\Scripts\pythonw.exe"   # no console flash
if (-not (Test-Path $PythonW)) { $PythonW = $Python }

# --- get the exact fire-times from the schedule core -----------------------
$times = @{}
foreach ($line in (& $Python (Join-Path $ProjectDir "reset_schedule.py") "--arm-times")) {
    if ($line -match '^(.+?)=(.+)$') { $times[$matches[1]] = [datetime]::Parse($matches[2]) }
}
if (-not $times.ContainsKey("SEND")) { throw "reset_schedule --arm-times gave no SEND time" }

# --- settings profiles -----------------------------------------------------
# Sender wakes the laptop from sleep so the window opens on time, and catches up
# a fire missed during full power-off on next availability.
$senderSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -WakeToRun `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

# Pings do NOT wake the machine and are NOT caught up late (a stale "resets in 2h"
# fired hours later is worthless) -- a missed ping is simply skipped.
$pingSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

function Register-OneShot([string]$Name, [string]$Script, [string]$Arg,
                          [datetime]$At, $Settings) {
    $action = New-ScheduledTaskAction -Execute $PythonW `
        -Argument "`"$(Join-Path $ProjectDir $Script)`" $Arg" -WorkingDirectory $ProjectDir
    $trigger = New-ScheduledTaskTrigger -Once -At $At
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger `
        -Settings $Settings -Force | Out-Null
    Write-Host ("  {0,-22} -> {1:yyyy-MM-dd HH:mm:ss}" -f $Name, $At)
}

Write-Host "Re-arming (anchor-derived):"
Register-OneShot "Claude Auto Sender"   "autosend.py"    "--once" $times["SEND"]    $senderSettings
if ($times.ContainsKey("PING:120")) {
    Register-OneShot "Claude Reset Ping 2h"   "notify_tick.py" "120" $times["PING:120"] $pingSettings
}
if ($times.ContainsKey("PING:90")) {
    Register-OneShot "Claude Reset Ping 1.5h" "notify_tick.py" "90"  $times["PING:90"]  $pingSettings
}
