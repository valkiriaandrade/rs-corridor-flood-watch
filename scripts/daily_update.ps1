# Daily forecast refresh: last 14 days of MERGE observed rainfall + latest 12 UTC ECMWF/GFS runs.
# Scheduled by scripts/install_daily_task.ps1. Log: logs/daily_update.log. Keeps 30 days of runs locally.
# With -Publish (default when the folder is a git repository with a remote), the new run replaces the previous one
# in git and is pushed, so the hosted app (Streamlit Community Cloud) shows it.
param([string]$Python = '', [int]$KeepDays = 30, [switch]$NoPublish)
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if (-not $Python) {
    if ($env:FLOODWATCH_PYTHON) { $Python = $env:FLOODWATCH_PYTHON }
    elseif (Test-Path (Join-Path $root '.venv\Scripts\python.exe')) { $Python = Join-Path $root '.venv\Scripts\python.exe' }
    else { $Python = 'python' }
}
New-Item -ItemType Directory -Force (Join-Path $root 'logs') | Out-Null
$log = Join-Path $root 'logs\daily_update.log'
function Log($text) { "$text" | Out-File $log -Append -Encoding utf8 }
$env:PYTHONUTF8 = '1'
Log "==== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz') start ($Python)"
& $Python -m floodwatch.forecast 2>&1 | ForEach-Object { Log $_ }
$code = $LASTEXITCODE
Log "exit $code"
if ($code -ne 0) { exit $code }

$latest = ((Get-Content (Join-Path $root 'data\processed\forecast\latest.json') -Raw | ConvertFrom-Json).run) -replace '\\', '/'
$keep = Split-Path $latest -Leaf
$limit = (Get-Date).AddDays(-$KeepDays)
foreach ($dir in @('data\processed\forecast\runs', 'data\raw\forecast_api')) {
    Get-ChildItem (Join-Path $root $dir) -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -ne $keep -and $_.LastWriteTime -lt $limit } |
        ForEach-Object { Remove-Item $_.FullName -Recurse -Force -Confirm:$false; Log "pruned $dir\$($_.Name)" }
}

# publish: git keeps only the latest run folder (runs/ is ignored; the latest one is force-added)
$isRepo = Test-Path (Join-Path $root '.git')
$hasRemote = $isRepo -and ((& git remote) -ne $null)
if ($NoPublish -or -not $hasRemote) { Log 'publish skipped'; exit 0 }
foreach ($old in (& git ls-files 'data/processed/forecast/runs' | Where-Object { $_ -notlike "$latest/*" })) {
    & git rm --cached --quiet -- $old 2>&1 | ForEach-Object { Log $_ }
}
& git add -f -- 'data/processed/forecast/latest.json' $latest 2>&1 | ForEach-Object { Log $_ }
& git diff --cached --quiet
if ($LASTEXITCODE -eq 0) { Log 'publish: nothing new'; exit 0 }
& git commit --quiet -m "Daily forecast $keep" 2>&1 | ForEach-Object { Log $_ }
& git push --quiet 2>&1 | ForEach-Object { Log $_ }
Log "publish exit $LASTEXITCODE"
exit $LASTEXITCODE
