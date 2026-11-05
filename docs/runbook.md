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
| – | `pytest -q` | 15 focused tests | < 1 min |

Order matters: step 12 must follow step 10 (it needs the final thresholds), and steps 13 and 17 read the rule built from
both (`floodwatch/rules.py`).

## Daily operation

Only step 17 is needed. It refreshes the last 14 days of MERGE (missing or *early* days), recomputes the basin rainfall
from 2025 onwards, fetches the latest 12 UTC ECMWF and GFS runs on the 632-point basin grid (paced requests, `Retry-After`
honoured) and applies the frozen rules. If CPTEC is unreachable the local MERGE files are kept; Open-Meteo is required.

- `scripts/install_daily_task.ps1 [-Python <path to python.exe>]` registers a Windows scheduled task (21:30 local,
  catches up after the PC was off, also on battery) that runs `scripts/daily_update.ps1`: forecast, log in
  `logs/daily_update.log`, local run folders older than 30 days pruned. Remove it with
  `Unregister-ScheduledTask -TaskName 'RS Corridor Flood Watch - daily update'`.
- **Catch-up.** `python -m floodwatch.forecast` first reconstructs the issuances of days without a run (computer off),
  up to 14 days back, from each day's 12 UTC runs (Open-Meteo keeps past runs) and the rainfall observed up to that day
  (`backfill: true` in the run metadata), then makes today's run. `--no-catchup` skips the reconstruction.
- **Flood occurrences.** Preliminary reports go in `data/raw/reports/preliminary_reports.csv`
  (`date,municipio,tipo,fonte,url,observacao`; types alagamento, enxurrada, inundação). Each run checks, at most once a
  week, the Atlas Digital download page (`floodwatch.official_records`); a new S2iD release is downloaded with
  provenance, loaded into the archive and replaces the preliminary reports for the dates it covers
  (`data/raw/atlas/official_release.json`). `python -m floodwatch.official_records` forces the check.
- **Publishing.** When the folder is a git repository with a remote, the same script keeps only the newest run folder
  in git (`data/processed/forecast/runs/` is ignored; the latest one is force-added), commits it as
  `Daily forecast <run id>` and pushes. Streamlit Community Cloud redeploys from the push, so the hosted app shows the
  new run a few minutes later. Pass `-NoPublish` to skip this step. The hosted app only changes on days the PC runs
  the task; after 36 h without a new run the page shows a warning.
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
