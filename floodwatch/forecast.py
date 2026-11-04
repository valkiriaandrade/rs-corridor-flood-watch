"""Daily corridor forecast: frozen study rules applied to ECMWF / GFS deterministic runs.

Rainfall of each municipality is the area-weighted mean over its upstream basin (ANA ottobacias, floodwatch.upstream):
  observed  MERGE daily (V07B final to 2024, IMERG late/early afterwards, product flagged per day)
  forecast  Open-Meteo single-runs API, latest 12 UTC run, hourly totals on a 0.25-degree grid covering every
            upstream basin, summed over the 12-12 UTC window (MERGE convention) and aggregated to each basin by area
EDI (calibration 1999-2012) and API (k = 0.90) are computed on observed + forecast rainfall and classified with
floodwatch.rules (Watch / Warning thresholds plus the frozen 3-day trigger).
Run: python -m floodwatch.forecast
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


def forecast_daily(points, model, stamp, batch_size=50, pause=1.0):
    """Daily 12-12 UTC forecast rainfall (date x point id) for `points` (columns point, lat, lon); raw JSON archived."""
    identifier, meta_id = MODELS[model]
    run = latest_run(meta_id)
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


def run():
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    units = gpd.read_file(study.OUT / 'units.geojson')
    units['codarea'] = units.codarea.astype(str)
    try:  # refresh recent MERGE (missing days, 'early' -> newer versions); offline keeps the local files
        from .fetch import merge as fetch_merge
        today = pd.Timestamp.now(tz='UTC').tz_localize(None).normalize()
        fetch_merge(today - pd.Timedelta(days=14), today)
    except Exception as error:
        print('MERGE recente não atualizado:', type(error).__name__)
    hist = study.study_rain('2024-12-31')
    recent, states = upstream.compute_rain('2025-01-01')
    observed = pd.concat([hist, recent[hist.columns]])
    cutoff = observed.index.max()
    points, point_weights = upstream.forecast_grid()
    rule = rules.load_rules()
    tables, runs = [], {}
    for model in MODELS:
        fc_points, init = forecast_daily(points, model, stamp)
        runs[model] = init.isoformat()
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
            'note': 'Regras validadas com chuva observada (MERGE V07B final, 2013-2024); na previsão herdam o erro do modelo.'}
    (run_dir / 'metadata.json').write_text(json.dumps(meta, indent=1, default=str), encoding='utf-8')
    (OUT / 'latest.json').write_text(json.dumps({'run': run_dir.relative_to(ROOT).as_posix()}), encoding='utf-8')
    try:  # archive for later verification (sql/validation.sql); never blocks the forecast itself
        from .forecast_db import ingest
        ingest(run_dir)
    except Exception as error:
        print('forecast_db ingest failed:', error)
    print(json.dumps(meta, indent=1, default=str))


if __name__ == '__main__':
    run()
