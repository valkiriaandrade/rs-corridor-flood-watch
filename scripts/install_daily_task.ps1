# Registers the Windows scheduled task "RS Corridor Flood Watch - daily update" (current user, no admin needed).
# -Python: interpreter with requirements-pipeline.txt installed (default: the project's .venv, then `python`).
# Remove with: Unregister-ScheduledTask -TaskName 'RS Corridor Flood Watch - daily update' -Confirm:$false
param([string]$At = '21:30', [string]$Python = '')
$script = Join-Path $PSScriptRoot 'daily_update.ps1'
$arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`""
if ($Python) { $arguments += " -Python `"$Python`"" }
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RunOnlyIfNetworkAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'RS Corridor Flood Watch - daily update' -Action $action -Trigger $trigger -Settings $settings `
    -Description 'Refreshes MERGE observed rainfall and the latest ECMWF/GFS 12 UTC runs, then publishes the new run to git.' -Force
