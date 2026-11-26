"""Ensemble probabilities of the flood-potential levels (protocol §9.7, prospective).

Open-Meteo keeps no archive of past ensemble runs, so this module archives, with every daily run, the latest ECMWF ENS
(51 members) and GEFS (31 members) run on the 0.5-degree forecast grid (the 0.25-degree grid with 51 + 31 members would
exceed the API's hourly quota). Each member's basin rainfall is appended to the same observed series as the
deterministic run, the operational indices and frozen rules are applied, and the share of members at Watch or above /
Warning is stored per municipality and day (table `ensemble`). Verification (Brier score, reliability) runs only after
a full year of archive.
    python -m floodwatch.ensemble        # archive for the latest deterministic run (data/processed/forecast/latest.json)
"""

import json
import time
from urllib.parse import urlencode

import numpy as np
import pandas as pd

from . import rules, upstream
from .forecast import _get, basin_mean, daily_12utc, observed_rain
from .paths import FORECAST as OUT, FORECAST_RAW as RAWF, ROOT

ENSEMBLES = {'ECMWF ENS': ('ecmwf_ifs025', 'ecmwf_ifs025_ensemble'), 'GEFS': ('gfs025', 'ncep_gefs025')}
URL = 'https://ensemble-api.open-meteo.com/v1/ensemble?'
FORECAST_DAYS = 7
STEP = 0.5
COLS = [
    'run_id',
    'model',
    'init_utc',
    'members',
    'date',
    'codarea',
    'lead_days',
    'rain_mean',
    'rain_p90',
    'p_watch',
    'p_warning',
    'p_watch_api',
    'p_warning_api',
]


def init_time(meta_id):
    meta = _get(
        f'https://ensemble-api.open-meteo.com/data/{meta_id}/static/meta.json', timeout=20, retry_on=(404,)
    ).json()
    return pd.Timestamp(meta['last_run_initialisation_time'], unit='s', tz='UTC')


def member_rain(points, model, stamp, batch_size=40, pause=6.0):
    """Daily 12-12 UTC rainfall per member: dict member -> DataFrame (date x point); complete windows only."""
    identifier, meta_id = ENSEMBLES[model]
    init = init_time(meta_id)
    pts = list(zip(points.point, points.lat, points.lon))
    rows, negative = [], 0
    for off in range(0, len(pts), batch_size):
        if off:
            time.sleep(pause)  # members weigh as variables: keep well under the per-minute quota
        batch = pts[off : off + batch_size]
        params = {
            'latitude': ','.join(f'{p[1]:.4f}' for p in batch),
            'longitude': ','.join(f'{p[2]:.4f}' for p in batch),
            'hourly': 'precipitation',
            'models': identifier,
            'forecast_days': FORECAST_DAYS,
            'past_days': 1,
            'timezone': 'UTC',
        }
        r = _get(URL + urlencode(params))
        path = RAWF / stamp / f'ens_{identifier}_{off}.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(r.content)
        bodies = r.json()
        bodies = bodies if isinstance(bodies, list) else [bodies]
        if len(bodies) != len(batch):
            raise ValueError('Open-Meteo ensemble: incomplete answer')
        for (point, _, _), body in zip(batch, bodies):
            h = body['hourly']
            t = pd.to_datetime(h['time'], utc=True)
            # Hours up to the initialisation come from the first hours of earlier runs of the same ensemble (the API
            # stitches them). They are kept: the latest run usually starts at 00/06 UTC, and without them the window
            # ending 12 UTC today would be incomplete, leaving a one-day gap that the API index propagates as missing.
            for key in (k for k in h if k.startswith('precipitation')):
                member = 0 if key == 'precipitation' else int(key.rsplit('member', 1)[1])
                s = pd.Series(h[key], index=t, dtype=float)
                negative += int((s < 0).sum())
                s = s.clip(lower=0)  # ECMWF ENS members carry small negative hourly values (de-accumulation)
                for day, val in daily_12utc(s).items():
                    rows.append((member, point, day, val))
    if negative:
        print(f'ensemble {model}: {negative} negative hourly values set to 0')
    df = pd.DataFrame(rows, columns=['member', 'point', 'date', 'rain'])
    out = {m: g.pivot(index='date', columns='point', values='rain').dropna(how='all') for m, g in df.groupby('member')}
    return out, init


def _share(levels, at):
    valid = levels[levels >= 0]
    return (valid >= at).mean() if len(valid) else np.nan


def member_index_table(series):
    """forecast.index_table with the API computed from 1 January of the year before the last day (365-730 days; the
    library requires a 1 January start, and 0.90**365 ~ 2e-17 leaves older rain with no numerical weight). The
    library's API takes ~0.7 s per basin on the full 1998- series, ~1 min per member. EDI and windows exactly as
    index_table; equality on the recent days is checked by tests/test_ensemble.py."""
    from . import indices, study

    start = pd.Timestamp(series.index.max().year - 1, 1, 1)
    tail = series.index >= start
    pe, edi, api = {}, {}, {}
    for code in series.columns:
        r, _ = indices.compute(series[code], study.CAL[0], study.CAL[1], series.index.max())
        pe[code], edi[code] = r.pe_mm.to_numpy(), r.edi.to_numpy()
        a = np.full(len(series), np.nan)
        a[tail] = indices.api(series.loc[tail, code])
        api[code] = a
    frame = lambda d: pd.DataFrame(d, index=series.index)
    return study.predictors(series, frame(pe), frame(edi), frame(api))


def probabilities(observed, member_fc, weights, rule):
    """Frozen rule on observed + each member's forecast -> level probabilities per date and codarea (long table)."""
    cutoff = observed.index.max()
    levels, rain = [], []
    for member, fc_points in member_fc.items():
        fc = basin_mean(fc_points, weights)
        fc = fc.loc[fc.index > cutoff, observed.columns]
        if fc.empty:
            continue
        gap = pd.date_range(cutoff + pd.Timedelta(days=1), fc.index.min() - pd.Timedelta(days=1))
        series = pd.concat([observed, pd.DataFrame(np.nan, index=gap, columns=observed.columns), fc])
        t = member_index_table(series)
        t = t[t.date > cutoff]
        levels.append(
            pd.DataFrame(
                {
                    'date': t.date.to_numpy(),
                    'codarea': t.codarea.to_numpy(),
                    'member': member,
                    'edi': np.asarray(rules.classify(t.EDI, t.P3, rule['EDI'])),
                    'api': np.asarray(rules.classify(t.API, t.P3, rule['API'])),
                }
            )
        )
        r = fc.stack().rename('rain').reset_index()
        r.columns = ['date', 'codarea', 'rain']
        rain.append(r)
    lv, rn = pd.concat(levels), pd.concat(rain)
    g = lv.groupby(['date', 'codarea'])
    out = pd.DataFrame(
        {
            'members': g.member.nunique(),
            'p_watch': g.edi.apply(_share, at=1),
            'p_warning': g.edi.apply(_share, at=2),
            'p_watch_api': g.api.apply(_share, at=1),
            'p_warning_api': g.api.apply(_share, at=2),
        }
    ).reset_index()
    rg = rn.groupby(['date', 'codarea']).rain
    out = out.merge(
        pd.DataFrame({'rain_mean': rg.mean(), 'rain_p90': rg.quantile(0.9)}).reset_index(),
        on=['date', 'codarea'],
        how='left',
    )
    out['lead_days'] = (pd.to_datetime(out.date) - cutoff).dt.days
    return out


def archive(run_dir=None, observed=None):
    """Ensemble probabilities for the deterministic run in run_dir (default: latest.json), stored in `ensemble`."""
    from .forecast_db import connect

    if run_dir is None:
        run_dir = ROOT / json.loads((OUT / 'latest.json').read_text(encoding='utf-8'))['run']
    meta = json.loads((run_dir / 'metadata.json').read_text(encoding='utf-8'))
    if observed is None:
        observed, _ = observed_rain()
    observed = observed.loc[: meta['observed_cutoff']]
    points, weights = upstream.forecast_grid(step=STEP)
    rule = rules.load_rules()
    con = connect()
    for model in ENSEMBLES:
        try:
            member_fc, init = member_rain(points, model, run_dir.name)
            p = probabilities(observed, member_fc, weights, rule)
        except Exception as error:  # one ensemble failing never blocks the other or the forecast
            print(f'ensemble {model} failed:', type(error).__name__, str(error)[:200])
            continue
        p = p.assign(
            run_id=run_dir.name,
            model=model,
            init_utc=init.isoformat(),
            date=pd.to_datetime(p.date).dt.strftime('%Y-%m-%d'),
            codarea=p.codarea.astype(str),
        )
        rows = p[COLS].astype(object).where(p[COLS].notna(), None).itertuples(index=False, name=None)
        con.executemany(
            f'INSERT OR REPLACE INTO ensemble ({",".join(COLS)}) VALUES ({",".join("?" * len(COLS))})', rows
        )
        con.commit()
        print(f'ensemble {model} (init {init:%Y-%m-%dT%HZ}, {int(p.members.max())} members): {len(p)} rows')
    con.close()


if __name__ == '__main__':
    archive()
