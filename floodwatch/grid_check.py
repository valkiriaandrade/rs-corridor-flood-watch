"""Basin rainfall on the 0.5-degree vs the 0.25-degree forecast grid (decision log 2026-11-28; protocol §9.7 note).

The ensembles (§9.7) and the hindcast (§9.5) use the 0.5-degree forecast points (180), the deterministic forecasts the
0.25-degree points (632). Same source on both grids: Open-Meteo previous-runs API, ECMWF IFS 0.25 and GFS, hourly
precipitation_previous_day1..3 (the same runs), at the union of both point sets, days 3-27 Nov 2026. Basin means with the
operational weights of each grid; levels with the frozen rules (observed MERGE through X-1, forecast X .. X+2).
Nothing in the pipeline, rules or dashboard changes.
    python -m floodwatch.grid_check download   # 657 points x 25 days x 3 leads x 2 models: ~2,350 weighted calls
    python -m floodwatch.grid_check evaluate   # -> data/processed/study/grid_check.json
"""

import json
import sys
import time
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import requests

from . import upstream
from .forecast_skill import API, UA, Budget, weight
from .paths import RAW, STUDY

ARCHIVE = RAW / 'grid_check'
MODELS = {'ECMWF': 'ecmwf_ifs025', 'GFS': 'gfs_global'}
LEADS = [1, 2, 3]
START, END = pd.Timestamp('2026-11-03'), pd.Timestamp('2026-11-27')  # hourly data; day D's window starts D-1 13 UTC
FIRST_ISSUE = pd.Timestamp('2026-11-04')
GRIDS = {'0.25': 0.25, '0.5': 0.5}
BATCH = 40
AGREEMENT_MIN, BIAS_MAX = 0.90, 0.10  # criterion, stated in the decision log before computing
LEVELS = ['Normal', 'Watch', 'Warning']


def points():
    """Union of the 0.25- and 0.5-degree forecast points, keyed by coordinates."""
    p = pd.concat([upstream.forecast_grid(step=s)[0][['lat', 'lon']] for s in GRIDS.values()])
    p = p.round(4).drop_duplicates().sort_values(['lat', 'lon']).reset_index(drop=True)
    p['key'] = [f'{a:.2f},{b:.2f}' for a, b in zip(p.lat, p.lon)]
    return p


def download():
    pts = points()
    budget = Budget()
    hourly = ','.join(f'precipitation_previous_day{n}' for n in LEADS)
    total = 0.0
    for name, code in MODELS.items():
        folder = ARCHIVE / code
        folder.mkdir(parents=True, exist_ok=True)
        for off in range(0, len(pts), BATCH):
            b = pts.iloc[off : off + BATCH]
            path = folder / f'{START:%Y%m%d}_{END:%Y%m%d}_{off:03d}.json'
            if path.exists():
                continue
            params = {
                'latitude': ','.join(f'{x:.2f}' for x in b.lat),
                'longitude': ','.join(f'{x:.2f}' for x in b.lon),
                'hourly': hourly,
                'models': code,
                'start_date': f'{START:%Y-%m-%d}',
                'end_date': f'{END:%Y-%m-%d}',
                'timezone': 'UTC',
            }
            w = weight(len(b), (END - START).days + 1, len(LEADS))
            for attempt in range(6):
                budget.wait(w)
                r = requests.get(API, params=params, headers=UA, timeout=300)
                if r.status_code == 429:
                    pause = int(r.headers.get('Retry-After', 0)) or 900 * (attempt + 1)
                    print(f'  429 {r.text[:120]} -> waiting {pause}s', flush=True)
                    time.sleep(pause)
                    continue
                r.raise_for_status()
                break
            else:
                raise RuntimeError('rate limited repeatedly; stopping (run again later, it resumes)')
            total += w
            path.write_text(r.text, encoding='utf-8')
            path.with_suffix('.http.json').write_text(
                json.dumps(
                    {
                        'url': r.url,
                        'time_utc': datetime.now(UTC).isoformat(),
                        'bytes': len(r.content),
                        'keys': b.key.tolist(),
                    }
                ),
                encoding='utf-8',
            )
            print(f'{name} points {off}-{off + len(b) - 1} ok', flush=True)
    print('weighted calls', round(total))


def point_rain(model):
    """{lead: daily 12-12 UTC point rainfall (date x 'lat,lon')} from the downloaded files."""
    from .forecast import daily_12utc

    out = {lead: {} for lead in LEADS}
    for path in sorted((ARCHIVE / MODELS[model]).glob('*.json')):
        if path.name.endswith('.http.json'):
            continue
        keys = json.loads(path.with_suffix('.http.json').read_text(encoding='utf-8'))['keys']
        bodies = json.loads(path.read_text(encoding='utf-8'))
        for key, body in zip(keys, bodies if isinstance(bodies, list) else [bodies]):
            t = pd.to_datetime(body['hourly']['time'], utc=True)
            for lead in LEADS:
                s = pd.Series(body['hourly'][f'precipitation_previous_day{lead}'], index=t, dtype=float)
                out[lead][key] = daily_12utc(s)
    return {lead: pd.DataFrame(cols) for lead, cols in out.items()}


def basin_rain(rain, step):
    """Point rainfall (date x 'lat,lon') -> basin rainfall (date x codarea) with the weights of the grid `step`."""
    from .forecast import basin_mean

    pts, w = upstream.forecast_grid(step=step)
    pts = pts.assign(key=[f'{a:.2f},{b:.2f}' for a, b in zip(pts.lat, pts.lon)])
    return basin_mean(rain[pts.key].set_axis(pts.point, axis=1), w)


def rain_stats(coarse, fine):
    """Basin rain on the coarse grid vs the fine grid (same municipality-days; NaN pairs dropped)."""
    a, b = np.asarray(coarse, float), np.asarray(fine, float)
    ok = ~(np.isnan(a) | np.isnan(b))
    a, b = a[ok], b[ok]
    d = a - b
    return {
        'n': int(ok.sum()),
        'mean_fine_mm': float(b.mean()),
        'bias_mm': float(d.mean()),
        'relative_bias': float(d.sum() / b.sum()) if b.sum() else None,
        'mean_abs_diff_mm': float(np.abs(d).mean()),
        'p95_abs_diff_mm': float(np.quantile(np.abs(d), 0.95)),
        'correlation': float(np.corrcoef(a, b)[0, 1]) if len(a) > 1 else None,
    }


def level_agreement(coarse, fine):
    """Share of municipality-days with the same level on both grids, the confusion table (rows: 0.25°, columns: 0.5°)
    and the agreement on days at Watch or above on either grid."""
    a, b = np.asarray(coarse, float), np.asarray(fine, float)
    ok = ~(np.isnan(a) | np.isnan(b))
    a, b = a[ok].astype(int), b[ok].astype(int)
    table = {LEVELS[i]: {LEVELS[j]: int(((b == i) & (a == j)).sum()) for j in range(3)} for i in range(3)}
    alert = (a >= 1) | (b >= 1)
    return {
        'n': int(ok.sum()),
        'agreement': float((a == b).mean()) if ok.any() else None,
        'confusion_fine_rows_coarse_cols': table,
        'alert_days': int(alert.sum()),
        'agreement_on_alert_days': float((a[alert] == b[alert]).mean()) if alert.any() else None,
    }


def passes(stats, agreement):
    return agreement >= AGREEMENT_MIN and abs(stats['relative_bias']) <= BIAS_MAX


def size_classes():
    """Upstream-basin area tercile of each municipality: small / medium / large."""
    area = upstream.weights().groupby('codarea').area.sum()
    return pd.qcut(area, 3, labels=['small', 'medium', 'large']).astype(str).rename(index=str)


def size_ranges_km2():
    """Smallest and largest upstream-basin area (km²) of each size tercile."""
    area = upstream.weights().groupby('codarea').area.sum() / 1e6  # weights are in m²
    g = area.groupby(size_classes().reindex(area.index.astype(str)).values).agg(['min', 'max'])
    return {c: [round(float(g.at[c, 'min'])), round(float(g.at[c, 'max']))] for c in ['small', 'medium', 'large']}


def evaluate():
    from . import forecast, hindcast, rules

    rule = rules.load_rules()
    observed, _ = forecast.observed_rain()
    last_obs = observed.index.max()
    last_issue = min(last_obs + pd.Timedelta(days=1), END - pd.Timedelta(days=len(LEADS) - 1))
    sizes = size_classes()
    out = {
        'source': 'Open-Meteo previous-runs API, precipitation_previous_day1..3',
        'hourly_period': [str(START.date()), str(END.date())],
        'issuances': [str(FIRST_ISSUE.date()), str(last_issue.date())],
        'last_observed_day': str(last_obs.date()),
        'points': {g: int(len(upstream.forecast_grid(step=s)[0])) for g, s in GRIDS.items()},
        'criterion': {'agreement_min': AGREEMENT_MIN, 'abs_relative_bias_max': BIAS_MAX},
        'size_terciles_km2': size_ranges_km2(),
        'models': {},
    }
    verdict = True
    for model in MODELS:
        pr = point_rain(model)
        fc = {g: {lead: basin_rain(pr[lead], s) for lead in LEADS} for g, s in GRIDS.items()}
        lv = {
            g: hindcast.issuance_levels(
                model,
                observed,
                rule,
                fc[g],
                start=FIRST_ISSUE,
                end=last_issue + pd.Timedelta(days=len(LEADS) - 1),
                leads=LEADS,
            )
            for g in GRIDS
        }
        rows = []
        for lead in LEADS:
            a = fc['0.5'][lead].stack(future_stack=True).rename('coarse')
            b = fc['0.25'][lead].stack(future_stack=True).rename('fine')
            r = pd.concat([a, b], axis=1).reset_index()
            r.columns = ['date', 'codarea', 'coarse', 'fine']
            rows.append(r.assign(lead=lead))
        rain = pd.concat(rows)
        rain = rain[(rain.date >= FIRST_ISSUE) & (rain.date <= last_issue + pd.Timedelta(days=len(LEADS) - 1))]
        rain['size'] = rain.codarea.astype(str).map(sizes)
        keys = ['issued', 'date', 'codarea', 'lead']
        lev = lv['0.5'].merge(lv['0.25'], on=keys, suffixes=('_coarse', '_fine'))
        lev['size'] = lev.codarea.astype(str).map(sizes)
        res = {'rain': rain_stats(rain.coarse, rain.fine), 'rain_by_lead': {}, 'rain_by_size': {}, 'levels': {}}
        for lead, g in rain.groupby('lead'):
            res['rain_by_lead'][str(lead)] = rain_stats(g.coarse, g.fine)
        for size, g in rain.groupby('size'):
            res['rain_by_size'][size] = rain_stats(g.coarse, g.fine)
        for ix in ('API', 'EDI'):
            c, f = f'level_{ix}_coarse', f'level_{ix}_fine'
            agr = level_agreement(lev[c], lev[f])
            agr['by_lead'] = {str(k): level_agreement(g[c], g[f]) for k, g in lev.groupby('lead')}
            agr['by_size'] = {k: level_agreement(g[c], g[f]) for k, g in lev.groupby('size')}
            agr['passes'] = passes(res['rain'], agr['agreement'])
            verdict &= agr['passes']
            res['levels'][ix] = agr
        out['models'][model] = res
        print(
            model,
            'rel bias',
            round(res['rain']['relative_bias'], 3),
            'corr',
            round(res['rain']['correlation'], 3),
            {ix: round(res['levels'][ix]['agreement'], 3) for ix in ('API', 'EDI')},
            flush=True,
        )
    out['acceptable_for_ensemble_display'] = bool(verdict)
    (STUDY / 'grid_check.json').write_text(json.dumps(out, indent=1), encoding='utf-8')
    return out


if __name__ == '__main__':  # compute_rain spawns worker processes (Windows re-imports the main module)
    {'download': download, 'evaluate': evaluate}[sys.argv[1]]()
