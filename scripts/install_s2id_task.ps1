# Registers the Windows scheduled task "RS Corridor Flood Watch - S2iD export" (current user, no admin needed).
# Runs scripts/s2id_export.ps1 a few minutes after logon and daily at 12:00 (or as soon as the PC is on after that);
# it skips when the last export is under 20 h old, so a PC switched on once a week exports once that day.
# Remove with: Unregister-ScheduledTask -TaskName 'RS Corridor Flood Watch - S2iD export' -Confirm:$false
param([string]$Python = '')
$script = Join-Path $PSScriptRoot 's2id_export.ps1'
$arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`" -MinAgeHours 20"
if ($Python) { $arguments += " -Python `"$Python`"" }
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments
$logon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$logon.Delay = 'PT5M'   # network and git credentials ready
$daily = New-ScheduledTaskTrigger -Daily -At '12:00'
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RunOnlyIfNetworkAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'RS Corridor Flood Watch - S2iD export' -Action $action -Trigger @($logon, $daily) -Settings $settings `
    -Description 'Exports the recent S2iD flood records (geo-blocked outside Brazil) and pushes them to branch s2id for the GitHub forecast.' -Force
