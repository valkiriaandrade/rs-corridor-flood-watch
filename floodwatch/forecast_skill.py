"""Forecast verification: which weather model forecast corridor rainfall best (archived runs vs MERGE).

Pre-registered before looking at any result (2026-11-04):
- Models: the two used on the forecast page, ECMWF IFS and NOAA GFS (Open-Meteo previous-runs archive;
  ECMWF as the 0.25-degree open-data output), 2024-03-01 .. last MERGE day. Amended 2026-11-04 before any
  evaluation: other models (ICON, GEM, JMA, AIFS, UKMO) dropped, since only the page's two models matter.
- Unit: 0.5-degree boxes containing the representative point of the 86 corridor municipalities.
  Observation = MERGE box mean (0.1-degree cells inside the box). Forecast = model value at the box centre.
- Day = 12-12 UTC window (MERGE convention), all 24 hours required. Lead N uses `precipitation_previous_dayN`
  (the run issued N days before each hour), N = 1..5.
- Primary metric: ETS (equitable threat score) for daily rain >= 20 mm, averaged over leads 1-3.
  Secondary: ETS >= 50 mm, 3-day total >= 50 mm, MAE, bias (forecast/observed total), Pearson r,
  rain forecast on S2iD event days.
- Uncertainty: paired block bootstrap by year-month on the common sample, 2,000 replicates, seed 20261104.
  A model is called the more accurate only if the CI of its difference to the other excludes 0.
Run: python -m floodwatch.forecast_skill download | evaluate
"""
import argparse
import json
import time
from collections import deque
from datetime import datetime, timezone

import geopandas as gpd
import numpy as np
import pandas as pd
import requests

from .forecast import daily_12utc
from .paths import RAW, ROOT, STUDY

ARCHIVE = RAW / 'forecast_archive'
OUT = ROOT / 'data' / 'processed' / 'forecast_skill'
API = 'https://previous-runs-api.open-meteo.com/v1/forecast'
MODELS = {'ECMWF IFS': ('ecmwf_ifs025', '2024-03-01'), 'GFS': ('gfs_global', '2024-03-01')}
PRIMARY = ['ECMWF IFS', 'GFS']
LEADS = [1, 2, 3, 4, 5]
BOX = 0.5
CHUNK_DAYS = 91
HOUR_BUDGET, DAY_BUDGET = 4000, 9000   # stay below the free-tier limits (5,000/h, 10,000/day)
UA = {'User-Agent': 'rs-corridor-flood-watch/1.0 (research)'}


def boxes():
    u = gpd.read_file(STUDY / 'units.geojson')
    p = u.to_crs(5880).geometry.representative_point().to_crs(4326)
    u['by'], u['bx'] = np.floor(p.y / BOX).astype(int), np.floor(p.x / BOX).astype(int)
    b = u.groupby(['by', 'bx']).agg(n=('codarea', 'size'), codareas=('codarea', lambda s: ','.join(map(str, s)))).reset_index()
    b['lat'], b['lon'] = (b.by + .5) * BOX, (b.bx + .5) * BOX
    b['box'] = [f'B{i:02d}' for i in range(len(b))]
    return b


def weight(n_loc, n_days, n_vars):
    return n_loc * max(1.0, n_days / 14) * max(1.0, n_vars / 10)


class Budget:
    """Client-side pacing so the free-tier limits are respected (no retry storms)."""
    def __init__(self):
        self.log = deque()

    def wait(self, w):
        while True:
            now = time.time()
            while self.log and now - self.log[0][0] > 86400:
                self.log.popleft()
            hour = sum(x for t, x in self.log if now - t < 3600)
            day = sum(x for _, x in self.log)
            if hour + w <= HOUR_BUDGET and day + w <= DAY_BUDGET:
                self.log.append((now, w))
                return
            pause = 300 if day + w <= DAY_BUDGET else 1800
            print(f'  pacing: hour {hour:.0f} day {day:.0f}, waiting {pause}s', flush=True)
            time.sleep(pause)


def last_obs_day():
    """Last day with a MERGE file in the local archive (2025+ comes from IMERG late/early)."""
    days = sorted(f.stem[-8:] for f in (RAW / 'merge').glob('MERGE_CPTEC_*.grib2'))
    return pd.Timestamp(days[-1])


def model_start(code):
    """First day with lead-5 data (probe one location)."""
    for d in pd.date_range('2024-03-01', '2026-06-01', freq='MS'):
        r = requests.get(API, params={'latitude': -30.0, 'longitude': -51.2, 'hourly': 'precipitation_previous_day5',
                                      'models': code, 'start_date': f'{d:%Y-%m-%d}', 'end_date': f'{d:%Y-%m-%d}',
                                      'timezone': 'UTC'}, headers=UA, timeout=60)
        r.raise_for_status()
        if any(v is not None for v in r.json()['hourly']['precipitation_previous_day5']):
            return d
    return None


def download(models=None):
    b = boxes()
    budget = Budget()
    end = last_obs_day()
    hourly = ','.join(f'precipitation_previous_day{n}' for n in LEADS)
    for name in models or MODELS:
        code, start = MODELS[name]
        start = pd.Timestamp(start) if start else model_start(code)
        if start is None:
            print(name, 'no archive', flush=True)
            continue
        folder = ARCHIVE / code
        folder.mkdir(parents=True, exist_ok=True)
        # the 12-12 UTC window of day D starts at D-1 13 UTC
        for c0 in pd.date_range(start - pd.Timedelta(days=1), end, freq=f'{CHUNK_DAYS}D'):
            c1 = min(c0 + pd.Timedelta(days=CHUNK_DAYS - 1), end)
            path = folder / f'{c0:%Y%m%d}_{c1:%Y%m%d}.json'
            if path.exists():
                continue
            params = {'latitude': ','.join(f'{x:.2f}' for x in b.lat), 'longitude': ','.join(f'{x:.2f}' for x in b.lon),
                      'hourly': hourly, 'models': code, 'start_date': f'{c0:%Y-%m-%d}', 'end_date': f'{c1:%Y-%m-%d}',
                      'timezone': 'UTC'}
            for attempt in range(6):
                budget.wait(weight(len(b), (c1 - c0).days + 1, len(LEADS)))
                r = requests.get(API, params=params, headers=UA, timeout=300)
                if r.status_code == 429:
                    pause = int(r.headers.get('Retry-After', 0)) or 900 * (attempt + 1)
                    print(f'  429 {r.text[:120]} -> waiting {pause}s', flush=True)
                    time.sleep(pause)
                    continue
                r.raise_for_status()
                break
            else:
                raise RuntimeError('rate limited repeatedly; stopping')
            path.write_text(r.text, encoding='utf-8')
            (path.with_suffix('.http.json')).write_text(json.dumps({
                'url': r.url, 'time_utc': datetime.now(timezone.utc).isoformat(), 'bytes': len(r.content)}), encoding='utf-8')
            print(f'{name} {c0:%Y-%m-%d}..{c1:%Y-%m-%d} ok', flush=True)


# ---------------------------------------------------------------- evaluation
def forecast_table(b):
    rows = []
    for name, (code, _) in MODELS.items():
        files = sorted((ARCHIVE / code).glob('*_*.json')) if (ARCHIVE / code).exists() else []
        files = [f for f in files if not f.name.endswith('.http.json')]
        if not files:
            continue
        per_box = {bx: {n: [] for n in LEADS} for bx in b.box}
        for f in files:
            data = json.loads(f.read_text(encoding='utf-8'))
            data = data if isinstance(data, list) else [data]
            for bx, d in zip(b.box, data):
                t = pd.to_datetime(d['hourly']['time'], utc=True)
                for n in LEADS:
                    per_box[bx][n].append(pd.Series(d['hourly'][f'precipitation_previous_day{n}'], index=t, dtype=float))
        for bx, leads in per_box.items():
            for n, parts in leads.items():
                s = pd.concat(parts).sort_index()
                s = s[~s.index.duplicated()]
                daily = daily_12utc(s.dropna())
                daily.index = pd.to_datetime(daily.index)
                rows.append(pd.DataFrame({'model': name, 'box': bx, 'lead': n, 'date': daily.index, 'fc': daily.values}))
    return pd.concat(rows, ignore_index=True)


def observed_table(b, start='2024-02-25'):
    """MERGE box means: V07B final cube up to 2024, then the IMERG late/early daily files (state recorded)."""
    from concurrent.futures import ProcessPoolExecutor
    from .merge_cube import read_crop
    z = np.load(STUDY / 'merge_rs_cube.npz', allow_pickle=True)
    dates = pd.to_datetime(z['dates'])
    keep = (dates >= start) & (dates <= '2024-12-31')
    grids, lat, lon = list(z['rain'][keep]), z['lat'], z['lon']
    days, states = list(dates[keep]), ['final'] * int(keep.sum())
    recent = pd.date_range('2025-01-01', last_obs_day())
    with ProcessPoolExecutor(6) as pool:
        for day, crop, state in pool.map(read_crop, recent, chunksize=16):
            grids.append(crop if crop is not None else np.full((len(lat), len(lon)), np.nan, 'float32'))
            days.append(pd.Timestamp(day)); states.append(state)
    rain = np.stack(grids)
    out = []
    for x in b.itertuples():
        iy = (lat >= x.by * BOX) & (lat < (x.by + 1) * BOX)
        ix = (lon >= x.bx * BOX) & (lon < (x.bx + 1) * BOX)
        v = rain[:, iy][:, :, ix].reshape(rain.shape[0], -1)
        ok = np.isfinite(v).mean(axis=1) >= 0.9
        with np.errstate(all='ignore'):
            m = np.where(ok, np.nanmean(v, axis=1), np.nan)
        out.append(pd.DataFrame({'box': x.box, 'date': days, 'obs': m, 'obs_state': states}))
    return pd.concat(out, ignore_index=True), pd.Series(states, index=days).value_counts().to_dict()


def cat_scores(f, o, thr):
    fy, oy = f >= thr, o >= thr
    a, bb, c = (fy & oy).sum(), (fy & ~oy).sum(), (~fy & oy).sum()
    n = len(f)
    ar = (a + bb) * (a + c) / n if n else 0
    ets = (a - ar) / (a + bb + c - ar) if (a + bb + c - ar) > 0 else np.nan
    pod = a / (a + c) if a + c else np.nan
    far = bb / (a + bb) if a + bb else np.nan
    return ets, pod, far, int(a + c)


def ets20(df):
    return cat_scores(df.fc.to_numpy(), df.obs.to_numpy(), 20)[0]


def scores(df):
    f, o = df.fc.to_numpy(), df.obs.to_numpy()
    e20, p20, f20, n20 = cat_scores(f, o, 20)
    e50, p50, f50, n50 = cat_scores(f, o, 50)
    return {'n': len(df), 'obs_days_ge20': n20, 'ETS20': e20, 'POD20': p20, 'FAR20': f20, 'ETS50': e50, 'POD50': p50,
            'FAR50': f50, 'obs_days_ge50': n50, 'MAE': float(np.abs(f - o).mean()), 'bias': float(f.sum() / o.sum()),
            'r': float(np.corrcoef(f, o)[0, 1])}


def three_day(df):
    df = df.sort_values('date')
    g = df.groupby(['model', 'box', 'lead'], group_keys=False)
    df = df.assign(fc3=g.fc.transform(lambda s: s.rolling(3).sum()), obs3=g.obs.transform(lambda s: s.rolling(3).sum()))
    return df


def evaluate(models, label, rng_seed=20261104, reps=2000):
    b = boxes()
    fc = forecast_table(b)
    fc = fc[fc.model.isin(models)]
    obs, obs_states = observed_table(b)
    df = fc.merge(obs, on=['box', 'date']).dropna(subset=['fc', 'obs'])
    # common sample: box-date-lead present for every model
    key = ['box', 'date', 'lead']
    cnt = df.groupby(key).model.nunique()
    common = cnt[cnt == len(models)].index
    df = df.set_index(key).loc[common].reset_index()
    df = three_day(df)
    res = {'label': label, 'models': models, 'period': [str(df.date.min().date()), str(df.date.max().date())],
           'boxes': int(df.box.nunique()), 'by_model_lead': {}, 'primary': {}, 'three_day_ge50': {}}
    for (m, n), g in df.groupby(['model', 'lead']):
        res['by_model_lead'].setdefault(m, {})[int(n)] = scores(g)
        g3 = g.dropna(subset=['fc3', 'obs3'])
        res['three_day_ge50'].setdefault(m, {})[int(n)] = dict(zip(['ETS', 'POD', 'FAR', 'n_obs'], cat_scores(g3.fc3.to_numpy(), g3.obs3.to_numpy(), 50)))
    prim = df[df.lead.isin([1, 2, 3])]
    for m, g in prim.groupby('model'):
        res['primary'][m] = float(np.mean([ets20(x) for _, x in g.groupby('lead')]))
    # paired block bootstrap by year-month
    prim = prim.assign(ym=prim.date.dt.to_period('M').astype(str))
    blocks = sorted(prim.ym.unique())
    stats = {}  # (model, block, lead) -> contingency counts for ETS >= 20
    for (m, ym, n), g in prim.groupby(['model', 'ym', 'lead']):
        fy, oy = g.fc.to_numpy() >= 20, g.obs.to_numpy() >= 20
        stats[(m, ym, n)] = np.array([(fy & oy).sum(), (fy & ~oy).sum(), (~fy & oy).sum(), len(g)], float)
    rng = np.random.default_rng(rng_seed)
    boot = {m: [] for m in models}
    for _ in range(reps):
        pick = rng.choice(blocks, len(blocks), replace=True)
        for m in models:
            e = []
            for n in [1, 2, 3]:
                a, bb, c, N = sum(stats.get((m, ym, n), np.zeros(4)) for ym in pick)
                ar = (a + bb) * (a + c) / N
                e.append((a - ar) / (a + bb + c - ar))
            boot[m].append(np.mean(e))
    boot = {m: np.array(v) for m, v in boot.items()}
    ranking = sorted(models, key=lambda m: -res['primary'][m])
    res['ranking'] = ranking
    res['primary_CI95'] = {m: [float(np.percentile(boot[m], 2.5)), float(np.percentile(boot[m], 97.5))] for m in models}
    best = ranking[0]
    res['best_vs_others'] = {m: {'diff': float(res['primary'][best] - res['primary'][m]),
                                 'CI95': [float(np.percentile(boot[best] - boot[m], 2.5)), float(np.percentile(boot[best] - boot[m], 97.5))]}
                             for m in ranking[1:]}
    res['best_is_significant'] = all(v['CI95'][0] > 0 for v in res['best_vs_others'].values())
    # event days (S2iD) inside the period: forecast vs observed rain of the 3 days ending on the event day, lead 1 and 3
    ev = pd.concat([pd.read_csv(STUDY / f) for f in ('events.csv', 'events_2025.csv') if (STUDY / f).exists()])
    ev['date'] = pd.to_datetime(ev.date)
    code2box = {int(c): x.box for x in b.itertuples() for c in x.codareas.split(',')}
    ev['box'] = ev.codarea.astype(int).map(code2box)
    ev = ev.dropna(subset=['box']).drop_duplicates(['box', 'date'])
    evd = df.merge(ev[['box', 'date']], on=['box', 'date'])
    res['event_days'] = {m: {int(n): {'n': len(g), 'fc3_over_obs3': float(g.fc3.sum() / g.obs3.sum()) if g.obs3.sum() else None,
                                      'share_fc3_ge50_when_obs3_ge50': float((g[g.obs3 >= 50].fc3 >= 50).mean()) if (g.obs3 >= 50).any() else None}
                             for n, g in gg.groupby('lead') if n in (1, 3)} for m, gg in evd.dropna(subset=['fc3', 'obs3']).groupby('model')}
    res['observation_note'] = 'MERGE V07B final to 2024; IMERG late/early from 2025 (preliminary).'
    # data-quality flag found after download (before interpretation): the archived GFS lead-5 series holds about half
    # the rainfall of leads 1-4 in every quarter (archive artefact); it is reported but not interpreted.
    res['suspect'] = {'GFS': {'5': 'archived previous_day5 series holds ~50% of the rainfall of leads 1-4 in every chunk'}}
    res['observation_states_days'] = {str(k): int(v) for k, v in obs_states.items()}
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['download', 'evaluate'])
    ap.add_argument('--models', nargs='*')
    a = ap.parse_args()
    if a.cmd == 'download':
        download(a.models)
    else:
        OUT.mkdir(parents=True, exist_ok=True)
        have = [m for m, (c, _) in MODELS.items() if (ARCHIVE / c).exists() and any((ARCHIVE / c).glob('*_*.json'))]
        prim = [m for m in PRIMARY if m in have]
        out = {'primary': evaluate(prim, 'common period, primary models')}
        (OUT / 'forecast_skill.json').write_text(json.dumps(out, indent=1, default=float), encoding='utf-8')
        print(json.dumps({k: {'ranking': v['ranking'], 'primary': v['primary'], 'sig': v['best_is_significant']} for k, v in out.items()}, indent=1))


if __name__ == '__main__':
    main()
