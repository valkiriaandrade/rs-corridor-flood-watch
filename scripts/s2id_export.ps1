# S2iD export from the project PC (in Brazil): S2iD blocks IP addresses outside Brazil, including GitHub's runners.
# Exports the report "Danos informados" (RS, flood COBRADEs, last 60 days of registrations) and force-pushes it to the
# branch `s2id` as a single commit; the daily-forecast workflow restores it before every run.
# Scheduled at logon by scripts/install_s2id_task.ps1 (the PC is switched on about once a week). Log: logs/s2id_export.log
#   ./scripts/s2id_export.ps1            # export now
#   ./scripts/s2id_export.ps1 -MinAgeHours 20   # skip if the last export is newer than that (what the task runs)
param([string]$Python = '', [double]$MinAgeHours = 0)
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if (-not $Python) {
    if (Test-Path (Join-Path $root '.venv\Scripts\python.exe')) { $Python = Join-Path $root '.venv\Scripts\python.exe' }
    else { $Python = 'python' }
}
New-Item -ItemType Directory -Force (Join-Path $root 'logs') | Out-Null
$log = Join-Path $root 'logs\s2id_export.log'
function Log($text) { "$text" | Out-File $log -Append -Encoding utf8; "$text" }
$src = Join-Path $root 'data\raw\s2id'
$audit = Join-Path $src 'danos_informados_RS.csv.http.json'

if ($MinAgeHours -gt 0 -and (Test-Path $audit)) {
    $last = [datetime]::Parse((Get-Content $audit -Raw | ConvertFrom-Json).downloaded_at_utc).ToUniversalTime()
    $age = ((Get-Date).ToUniversalTime() - $last).TotalHours
    if ($age -lt $MinAgeHours) { Log ("==== {0:u} skipped: last export {1:N1} h old" -f (Get-Date).ToUniversalTime(), $age); exit 0 }
}
Log ("==== {0:u} start" -f (Get-Date).ToUniversalTime())
$env:PYTHONUTF8 = '1'
& $Python -m floodwatch.official_records export-s2id 2>&1 | ForEach-Object { Log $_ }
if ($LASTEXITCODE -ne 0) { Log "export failed (exit $LASTEXITCODE): nothing pushed"; exit 1 }

$tmp = Join-Path $env:TEMP "s2id-export-$PID"
& git worktree add -q --detach $tmp 2>&1 | ForEach-Object { Log $_ }
try {
    Push-Location $tmp
    & git checkout -q --orphan s2id-export 2>&1 | ForEach-Object { Log $_ }
    & git rm -rfq . 2>$null | Out-Null
    Copy-Item (Join-Path $src 'danos_informados_RS.csv'), $audit .
    # bytes kept as exported (the sha256 in the provenance must still match)
    [IO.File]::WriteAllText((Join-Path $tmp '.gitattributes'), "* -text`n")
    & git add .gitattributes danos_informados_RS.csv danos_informados_RS.csv.http.json
    & git commit -q -m ("S2iD export {0:yyyyMMddTHHmmssZ}" -f (Get-Date).ToUniversalTime()) 2>&1 | ForEach-Object { Log $_ }
    & git push -q -f origin HEAD:s2id 2>&1 | ForEach-Object { Log $_ }
    $code = $LASTEXITCODE
} finally {
    Pop-Location
    & git worktree remove --force $tmp 2>&1 | Out-Null
    & git branch -q -D s2id-export 2>&1 | Out-Null
}
if ($code -ne 0) { Log "push failed (exit $code)"; exit $code }
Log ("==== {0:u} pushed to branch s2id" -f (Get-Date).ToUniversalTime())
