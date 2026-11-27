# Runbook — rebuild everything from raw data

All commands run from the project root with Python 3.11.

```bash
python -m venv .venv && .venv/Scripts/activate      # Windows; bin/activate on Linux/macOS
pip install -r requirements-dev.txt
export PYTHONUTF8=1                                   # Git Bash; PowerShell: $env:PYTHONUTF8=1
export FLOODWATCH_MERGE_ARCHIVE=data/raw/merge        # folder holding the 1998-2024 MERGE GRIB2 files
```

## Full pipeline (in order)

| # | Command | Output | Time |
|---|---|---|---|
| 1 | `python -m floodwatch.fetch static` | Atlas, IBGE, DNIT SNV in `data/raw/` | ~2 min |
| 2 | `python -m floodwatch.fetch merge 1998-01-01 2024-12-31` | ~9,900 daily GRIB2 + CTL files (~4.5 GB) | 1–3 h |
| 3 | `python -m floodwatch.fetch merge-recent` | 2025 → today (IMERG late/early) | ~10 min |
| 4 | `python -m floodwatch.merge_cube` | `merge_rs_cube.npz` (RS crop, V07B final) | ~20 min |
| 5 | `python -m floodwatch.study --stage units` | corridor units, municipal cell weights, municipal rainfall | ~5 min |
| 6 | download `geoft_bho_ach_otto_nivel_06.gpkg` (1.7 GB, metadados.snirh.gov.br) to `data/raw/ana/bho/` | ANA ottobacias level 6 | ~10 min |
| 7 | `python -m floodwatch.upstream basins` | `upstream_weights.csv`, `upstream_units.csv`, `upstream_basins.geojson` | ~10 min |
| 8 | `python -m floodwatch.upstream rain` | `upstream_rain.csv.gz` (1998 → today) | ~20 min |
| 9 | `python -m floodwatch.study --stage data` | indices, events, case-control sample | ~5 min |
| 10 | `python -m floodwatch.study --stage eval` | `results.json` | ~30 min |
| 11 | `python -m floodwatch.validation_2025` | `validation_2025.json` | ~3 min |
| 12 | `python -m floodwatch.second_trigger` | `second_trigger.json` (frozen 3-day trigger) | ~5 min |
| 13 | `python -m floodwatch.figures` | ROC, risk multiplier, May-2024 timeline, event leads, road check (EDI; `_API` files) | ~3 min |
| 14 | `python -m floodwatch.ana download` then `series` | HidroWeb stages (sequential, paced), `ana_levels.csv.gz` | ~15 min |
| 15 | `python -m floodwatch.ana_validation upstream`, `rivers`, `river-predictor` | `upstream_results.json`, `river_validation.json`, `river_predictor.json` | ~40 min |
| 16 | `python -m floodwatch.forecast_skill download` then `evaluate` | ECMWF × GFS verification (paced; can take hours) | hours |
| 17 | `python -m floodwatch.forecast` | `data/processed/forecast/runs/<utc>/` + SQLite archive | ~3 min |
| 18 | `streamlit run app.py` | http://localhost:8501 | – |
| – | `pytest -q` | 46 tests (no network) | ~1 min |

### Supplementary analyses (protocol §§9.5–9.11)

Copernicus downloads need a free ECMWF account token in `~/.cdsapirc` (`url: https://cds.climate.copernicus.eu/api`,
`key: <token>`) and, once per account, the ERA5-Land licence (CDS) plus the EWDS terms and the CEMS-FLOODS licence
(EWDS). Both stores accept one request at a time per dataset; the downloaders wait 15 min and retry while the queue is full.

| Command | Output | Time |
|---|---|---|
| `python -m floodwatch.stats_extra` | `stats_extra.json` (SEDI, economic value, power; §9.10) | ~10 min |
| `python -m floodwatch.ground_truth download`, then without arguments | `ground_truth.json` (PRF, Copernicus EMS; §9.9) | ~5 min |
| `python -m floodwatch.hindcast download` | `data/raw/hindcast/` (Open-Meteo past runs, paced by the free quota) | 1–2 days |
| `python -m floodwatch.hindcast evaluate`, then `bias-correction` | `hindcast.json`, `bias_correction.json` (§9.5, §9.6) | ~1 h |
| `python -m floodwatch.glofas download` then `evaluate` | `glofas.json` (§9.8) | hours (queue) |
| `python -m floodwatch.soil_moisture download` then `evaluate` | `soil_moisture.json` (§9.11) | hours (queue) |

Order matters: step 12 must follow step 10 (it needs the final thresholds), and steps 13 and 17 read the rule built from
both (`floodwatch/rules.py`).

## Daily operation

Only step 17 is needed. It refreshes the last 14 days of MERGE (missing or *early* days), recomputes the basin rainfall
from 2025 onwards, fetches the latest 12 UTC ECMWF and GFS runs on the 632-point basin grid (paced requests, `Retry-After`
honoured; if a 12 UTC run is not available yet, the 06 and then the 00 UTC run is used) and applies the frozen rules.
If CPTEC is unreachable the local MERGE files are kept; Open-Meteo is required. It then archives the ensemble
probabilities (ECMWF ENS and GEFS on the 180-point 0.5° grid, table `ensemble`, protocol §9.7; about 20 min, and a
failure is printed but never blocks the forecast); this run's probabilities also go to
`runs/<utc>/ensemble_levels.csv` for the dashboard. Last, `forecast_db.write_summary` writes `verification.json`
and `verification_daily.csv` (the same verification for ECMWF, GFS, Consensus, ECMWF ENS and GEFS, per day, model,
lead and index), both published with the run. A cloud run takes about 20 min in total.

- **Where it runs (since 2026-11-07).** `.github/workflows/daily-forecast.yml` (windows-latest, cron 20:00 UTC = 17:00
  Brasília, also `workflow_dispatch`) runs `scripts/daily_update.ps1` in the cloud. State between runs: MERGE files in
  the Actions cache (`merge-v1-*`, re-downloadable) and `forecasts.sqlite` on the branch `archive` (restored before the
  run, force-pushed as a single commit after it; this is the authoritative archive, a local copy is stale). The push
  only happens if `python -m floodwatch.forecast_db check` passes (SQLite integrity, no table has fewer rows than
  before the run); the copy restored at the start of each run is kept 30 days as the artifact
  `forecast-archive-before-<run id>` (download it from the run page to recover an earlier archive). Start a
  run by hand with `gh workflow run daily-forecast.yml`. S2iD blocks IP addresses outside Brazil, so the workflow does
  not export it: the project PC (in Brazil, switched on about once a week) pushes the export to the branch `s2id`
  and every run loads the latest one (`FLOODWATCH_S2ID=file`; re-loading is harmless, the 60-day registration window
  covers the weeks between exports, and the log warns when it is over 10 days old). On the PC,
  `scripts/install_s2id_task.ps1` registers the task "RS Corridor Flood Watch - S2iD export" (5 min after logon and
  12:00, skipped if the last export is under 20 h old; log `logs/s2id_export.log`); export by hand with
  `./scripts/s2id_export.ps1`. A VM in Brazil is an alternative that needs no PC: [s2id-vm.md](s2id-vm.md). When a
  browser export fails, the page the site served (`logs/s2id_failure/`) is uploaded as the run artifact
  `s2id-failure-<run id>`.
- `scripts/install_daily_task.ps1 [-Python <path to python.exe>]` registers the former local alternative, a Windows
  scheduled task (21:30 local, catches up after the PC was off) running the same `scripts/daily_update.ps1`. Its task
  is disabled; do not enable it alongside the workflow (both push to `main`). Remove it with
  `Unregister-ScheduledTask -TaskName 'RS Corridor Flood Watch - daily update'`.
- **Catch-up.** `python -m floodwatch.forecast` first reconstructs the issuances of days without a run (computer off),
  up to 14 days back, from each day's 12 UTC runs (Open-Meteo keeps past runs) and the rainfall observed up to that day
  (`backfill: true` in the run metadata), then makes today's run. `--no-catchup` skips the reconstruction.
- **Flood occurrences.** Preliminary reports go in `data/raw/reports/preliminary_reports.csv`
  (`date,municipio,tipo,fonte,url,observacao`; types alagamento, enxurrada, inundação). Each run checks, at most once a
  week, the Atlas Digital download page (`floodwatch.official_records`); a new S2iD release is downloaded with
  provenance and loaded into the archive (`data/raw/atlas/official_release.json`). The public S2iD report "Danos
  informados" (RS, flood COBRADEs, last 60 days of registrations) is exported with a headless Microsoft Edge driven by
  Playwright (`requirements-pipeline.txt`; Edge must be installed) on the PC in Brazil (see above), saved to
  `data/raw/s2id/` (ignored by git) with provenance, and its corridor records are loaded into the archive; in the
  workflow (`FLOODWATCH_S2ID=file`) the run only loads the export restored from the branch `s2id`. A preliminary
  report counts only when no official record exists in the same municipality within ±1 day. If the export fails
  (form changed, site down) the run continues and prints `S2iD export failed`. `python -m floodwatch.official_records`
  forces both checks.
- **Publishing.** When the folder is a git repository with a remote, the same script keeps only the newest run folder
  in git (`data/processed/forecast/runs/` is ignored; the latest one is force-added), commits it as
  `Daily forecast <run id>` and pushes. Streamlit Community Cloud redeploys from the push, so the hosted app shows the
  new run a few minutes later. Pass `-NoPublish` to skip this step. The hosted app only changes on days a run
  succeeds; after 36 h without a new run the page shows a warning.
- Every run is ingested into `data/processed/forecast/forecasts.sqlite` (schema `sql/schema.sql`), with the rule it
  used. Each run also stores the last observed days, so later runs verify earlier forecasts (view `verification`).
  Queries: `python -m floodwatch.forecast_db report` or `sqlite3 data/processed/forecast/forecasts.sqlite < sql/validation.sql`.
  Rebuild from the run folders: `python -m floodwatch.forecast_db ingest-all` (the daily task prunes folders older
  than 30 days, so the SQLite file — not the folders — is the long-term archive; back it up before rebuilding). Load official records of a new Atlas
  release: `python -m floodwatch.forecast_db events <atlas.csv>`.

## Reproducibility

- Bootstrap: seed `20261103`, 2,000 replicates (forecast verification: seed `20261104`).
- MERGE product version checked per day (V07B final required for 1998–2024).
- Every downloaded file has a sibling `.http.json` (URL, time, size, SHA-256).
- `climate-indices` is pinned to 3.0.0 and the index code refuses any other version.
