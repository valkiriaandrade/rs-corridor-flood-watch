"""Daily corridor forecast: frozen study rules applied to ECMWF / GFS deterministic runs.

Rainfall of each municipality is the area-weighted mean over its upstream basin (ANA ottobacias, floodwatch.upstream):
  observed  MERGE daily (V07B final to 2024, IMERG late/early afterwards, product flagged per day)
  forecast  Open-Meteo single-runs API, latest 12 UTC run, hourly totals on a 0.25-degree grid covering every
            upstream basin, summed over the 12-12 UTC window (MERGE convention) and aggregated to each basin by area
EDI (calibration 1999-2012) and API (k = 0.90) are computed on observed + forecast rainfall and classified with
floodwatch.rules (Watch / Warning thresholds plus the frozen 3-day trigger).

Catch-up: days without a run (computer off) are reconstructed first, each from that day's 12 UTC runs (Open-Meteo
keeps past runs) and the observed rainfall up to that day, so the verification archive has no gaps. Their metadata
says `backfill: true`; the observed rainfall used is the version available when they were processed.
    python -m floodwatch.forecast                 # catch up missing days (up to 14), then today's run
    python -m floodwatch.forecast --no-catchup    # today's run only
"""
from datetime import datetime, timezone
import json
import time
from urllib.parse import urlencode

import geopandas as gpd
import numpy as np
import pandas as pd
import requests

from . import indices, rules, study, upstream
from .paths import FORECAST as OUT, FORECAST_RAW as RAWF, ROOT

MODELS = {'ECMWF': ('ecmwf_ifs', 'ecmwf_ifs'), 'GFS': ('gfs_global', 'ncep_gfs013')}  # Open-Meteo model, metadata id
FORECAST_DAYS = 10
BACKFILL_DAYS = 14  # how far back missing issuances are reconstructed
OBSERVED_DAYS_KEPT = 3  # last observed days stored with each run (verification of earlier forecasts)


def daily_12utc(hourly):
    """Hourly totals (value at hour h accumulates (h-1, h], UTC index) -> 24-h totals for windows ending 12 UTC.

    The window labelled D covers 13 UTC of D-1 .. 12 UTC of D (the MERGE convention). Incomplete windows are NaN.
    """
    t = hourly.index
    label = (t - pd.Timedelta(hours=12, minutes=1)).floor('D') + pd.Timedelta(days=1)
    g = hourly.groupby(label.tz_localize(None))
    return g.sum(min_count=24).where(g.count() == 24)


def latest_run(meta_id):
    """Most recent 12 UTC initialisation already published by Open-Meteo for this model."""
    meta = requests.get(f'https://api.open-meteo.com/data/{meta_id}/static/meta.json', timeout=20).json()
    latest = pd.Timestamp(meta['last_run_initialisation_time'], unit='s', tz='UTC')
    run = latest.floor('D') + pd.Timedelta(hours=12)
    return run if run <= latest else run - pd.Timedelta(days=1)


def _get(url, tries=4):
    """GET with polite pacing: honours 429/5xx by waiting (Retry-After when given), never hammers the server."""
    for attempt in range(tries):
        r = requests.get(url, timeout=90)
        if r.status_code in (429, 500, 502, 503, 504) and attempt < tries - 1:
            time.sleep(float(r.headers.get('Retry-After', 20 * (attempt + 1))))
            continue
        r.raise_for_status()
        return r


def forecast_daily(points, model, stamp, run=None, batch_size=50, pause=1.0):
    """Daily 12-12 UTC forecast rainfall (date x point id) for `points` (columns point, lat, lon); raw JSON archived.

    run: initialisation time (UTC); default = the latest 12 UTC run published for the model."""
    identifier, meta_id = MODELS[model]
    run = latest_run(meta_id) if run is None else pd.Timestamp(run)
    pts = list(zip(points.point, points.lat, points.lon))
    rows = []
    for off in range(0, len(pts), batch_size):
        if off:
            time.sleep(pause)
        batch = pts[off:off + batch_size]
        params = {'latitude': ','.join(f'{p[1]:.4f}' for p in batch), 'longitude': ','.join(f'{p[2]:.4f}' for p in batch),
                  'hourly': 'precipitation', 'models': identifier, 'forecast_days': FORECAST_DAYS, 'timezone': 'UTC',
                  'run': run.strftime('%Y-%m-%dT%H:%M')}
        r = _get('https://single-runs-api.open-meteo.com/v1/forecast?' + urlencode(params))
        path = RAWF / stamp / f'{model}_{off}.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(r.content)
        bodies = r.json()
        bodies = bodies if isinstance(bodies, list) else [bodies]
        if len(bodies) != len(batch):
            raise ValueError('Open-Meteo: resposta incompleta')
        for (point, _, _), body in zip(batch, bodies):
            t = pd.to_datetime(body['hourly']['time'], utc=True)
            for day, val in daily_12utc(pd.Series(body['hourly']['precipitation'], index=t, dtype=float)).items():
                rows.append({'point': point, 'date': day, 'rain_mm': val})
    df = pd.DataFrame(rows).pivot(index='date', columns='point', values='rain_mm')
    df.columns.name = None
    first_full = (run + pd.Timedelta(days=1)).tz_localize(None).normalize()
    return df.loc[first_full:].dropna(how='all'), run


def basin_mean(point_rain, weights):
    """Point forecasts (date x point) -> basin rainfall (date x codarea), area-weighted; NaN if any point is missing."""
    out = {}
    for code, w in weights.groupby('codarea'):
        v = point_rain[w.point.to_numpy()]
        mean = (v * w.area.to_numpy()).sum(axis=1) / w.area.sum()
        out[code] = mean.where(v.notna().all(axis=1))
    return pd.DataFrame(out)


def index_table(series):
    """Windowed predictors (P1..P30, PE, EDI, API) for observed + forecast rainfall, long format."""
    pe, edi, api = {}, {}, {}
    for code in series.columns:
        r, _ = indices.compute(series[code], study.CAL[0], study.CAL[1], series.index.max())
        pe[code], edi[code], api[code] = r.pe_mm.to_numpy(), r.edi.to_numpy(), indices.api(series[code])
    frame = lambda d: pd.DataFrame(d, index=series.index)
    return study.predictors(series, frame(pe), frame(edi), frame(api))


def refresh_merge(days):
    """Refresh recent MERGE files (missing days, 'early' -> newer versions); offline keeps the local files."""
    try:
        from .fetch import merge as fetch_merge
        today = pd.Timestamp.now(tz='UTC').tz_localize(None).normalize()
        fetch_merge(today - pd.Timedelta(days=days), today)
    except Exception as error:
        print('MERGE recente não atualizado:', type(error).__name__)


def observed_rain():
    """Observed basin rainfall: study series to 2024 + recomputed MERGE from 2025; and the MERGE product per day."""
    hist = study.study_rain('2024-12-31')
    # 2 workers: each spawned worker re-imports this module (~600 MB on Windows); 6 workers ran out of memory on an
    # 8 GB machine (MemoryError, 2026-11-05) and were no faster (28 s vs 24 s for ~700 days).
    recent, states = upstream.compute_rain('2025-01-01', workers=2)
    return pd.concat([hist, recent[hist.columns]]), states


def run(issue=None, observed=None, states=None):
    """One forecast run. issue=None: today's run (latest 12 UTC runs, every observed day). issue=date: reconstructs
    the issuance of that date (its 12 UTC runs, observed rainfall up to that day); latest.json is not touched."""
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    while (OUT / 'runs' / stamp).exists():
        time.sleep(1)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    units = gpd.read_file(study.OUT / 'units.geojson')
    units['codarea'] = units.codarea.astype(str)
    if observed is None:
        refresh_merge(BACKFILL_DAYS)
        observed, states = observed_rain()
    if issue is not None:
        issue = pd.Timestamp(issue).normalize()
        observed = observed.loc[:issue]
    cutoff = observed.index.max()
    init = None if issue is None else (issue + pd.Timedelta(hours=12)).tz_localize('UTC')
    points, point_weights = upstream.forecast_grid()
    rule = rules.load_rules()
    tables, runs = [], {}
    for model in MODELS:
        fc_points, model_init = forecast_daily(points, model, stamp, run=init)
        runs[model] = model_init.isoformat()
        fc = basin_mean(fc_points, point_weights)
        fc = fc.loc[fc.index > cutoff, observed.columns]
        gap = pd.date_range(cutoff + pd.Timedelta(days=1), fc.index.min() - pd.Timedelta(days=1)) if len(fc) else []
        series = pd.concat([observed, pd.DataFrame(np.nan, index=gap, columns=observed.columns), fc])
        table = index_table(series)
        # daily basin rainfall of the day itself (the predictors take the max over d-1 and d)
        table['rain_mm'] = series.stack(future_stack=True).reindex(pd.MultiIndex.from_frame(table[['date', 'codarea']])).to_numpy()
        table = table[table.date > cutoff - pd.Timedelta(days=OBSERVED_DAYS_KEPT)].copy()
        table['model'] = model
        table['source'] = np.where(table.date > cutoff, 'previsão', 'observado')
        table['level'] = rules.classify(table.EDI, table.P3, rule['EDI'])
        table['level_api'] = rules.classify(table.API, table.P3, rule['API'])
        tables.append(table)
    result = pd.concat(tables).merge(units[['codarea', 'nome', 'corridors']], on='codarea', how='left')
    run_dir = OUT / 'runs' / stamp
    run_dir.mkdir(parents=True)
    result.to_csv(run_dir / 'municipal_levels.csv', index=False)
    last30 = pd.Series(states)
    last30 = last30[(last30.index >= str((cutoff - pd.Timedelta(days=29)).date())) & (last30.index <= str(cutoff.date()))]
    meta = {'created_utc': stamp, 'runs': runs, 'observed_cutoff': str(cutoff.date()),
            'rainfall': f'upstream-basin mean (ANA ottobacias); forecast on a 0.25-degree grid of {len(points)} points',
            'antecedent_product_last_30d': last30.value_counts().to_dict(),
            'rules': {ix: r.as_dict() for ix, r in rule.items()}, 'api_k': indices.API_K, 'units': len(units),
            'backfill': issue is not None,
            'note': 'Regras validadas com chuva observada (MERGE V07B final, 2013-2024); na previsão herdam o erro do modelo.'}
    (run_dir / 'metadata.json').write_text(json.dumps(meta, indent=1, default=str), encoding='utf-8')
    if issue is None:
        (OUT / 'latest.json').write_text(json.dumps({'run': run_dir.relative_to(ROOT).as_posix()}), encoding='utf-8')
    try:  # archive for later verification (sql/validation.sql); never blocks the forecast itself
        from .forecast_db import ingest
        ingest(run_dir)
    except Exception as error:
        print('forecast_db ingest failed:', error)
    print(('backfill ' if issue is not None else '') + f'run {stamp}: observed to {cutoff.date()}, models {runs}')
    return run_dir


def missing_issues(today_run):
    """Issuance dates (12 UTC runs) without an archived run, from BACKFILL_DAYS ago up to the day before today_run."""
    from .forecast_db import connect
    con = connect()
    have = {pd.Timestamp(r[0]).tz_convert(None).normalize() if pd.Timestamp(r[0]).tzinfo else pd.Timestamp(r[0]).normalize()
            for r in con.execute('SELECT ecmwf_run FROM runs WHERE ecmwf_run IS NOT NULL')}
    con.close()
    if not have:
        return []  # a fresh archive starts today; nothing to reconstruct
    last = pd.Timestamp(today_run).tz_convert(None).normalize()
    start = max(max(have) + pd.Timedelta(days=1), last - pd.Timedelta(days=BACKFILL_DAYS))
    return [d for d in pd.date_range(start, last - pd.Timedelta(days=1)) if d not in have]


def daily(catchup=True):
    """What the scheduled task runs: reconstruct the missing issuances, then today's run; refresh the summaries."""
    today_run = latest_run(MODELS['ECMWF'][1])
    todo = missing_issues(today_run) if catchup else []
    if todo:
        print('reconstructing', [str(d.date()) for d in todo])
    refresh_merge(BACKFILL_DAYS + 2)
    observed, states = observed_rain()
    for d in todo:
        try:
            run(issue=d, observed=observed, states=states)
        except Exception as error:  # a missing past run never blocks today's forecast
            print(f'backfill {d.date()} failed:', type(error).__name__, error)
    run(observed=observed, states=states)
    try:
        from . import official_records
        official_records.update()       # weekly: new Atlas Digital release
        official_records.update_s2id()  # daily: recent S2iD records (headless export of the public report)
    except Exception as error:
        print('official records not updated:', type(error).__name__, error)
    try:
        from .forecast_db import write_summary
        write_summary()  # forecast vs observed (and reported floods) -> verification.json, published with the run
    except Exception as error:
        print('verification summary failed:', type(error).__name__, error)


if __name__ == '__main__':
    import sys
    daily(catchup='--no-catchup' not in sys.argv)
