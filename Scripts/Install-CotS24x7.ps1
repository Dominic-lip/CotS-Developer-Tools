param(
    [switch]$Uninstall,
    [switch]$DisableSleepOnAC,
    [switch]$StartNow = $true
)

$ErrorActionPreference = "Stop"
$TaskName = "CotS Autonomous Factory 24x7"
$Repo = Split-Path -Parent $PSScriptRoot
$Watchdog = Join-Path $PSScriptRoot "CotSWatchdog24x7Enhanced.py"

if ($Uninstall) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed scheduled task: $TaskName"
    exit 0
}

$PythonW = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $PythonW) {
    $Python = (Get-Command python.exe -ErrorAction Stop).Source
    $Candidate = Join-Path (Split-Path -Parent $Python) "pythonw.exe"
    if (Test-Path $Candidate) { $PythonW = $Candidate } else { $PythonW = $Python }
}

$Action = New-ScheduledTaskAction -Execute $PythonW -Argument "`"$Watchdog`"" -WorkingDirectory $Repo
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
$Task = New-ScheduledTask -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings
Register-ScheduledTask -TaskName $TaskName -InputObject $Task -Force | Out-Null

if ($DisableSleepOnAC) {
    powercfg /change standby-timeout-ac 0 | Out-Null
    powercfg /change hibernate-timeout-ac 0 | Out-Null
    Write-Host "AC sleep/hibernate disabled. Display sleep settings are unchanged."
}

if ($StartNow) { Start-ScheduledTask -TaskName $TaskName }
Write-Host ""
Write-Host "Installed: $TaskName"
Write-Host "Watchdog:  $Watchdog"
Write-Host "Telemetry: http://127.0.0.1:8765/"
Write-Host "The enhanced watchdog includes quota protection, hardware gates, rollback canaries and local telemetry."
Write-Host "It starts at user logon and Windows restarts it after process failure."
Write-Host "For real 24/7 operation keep Windows signed in and prevent AC sleep."
