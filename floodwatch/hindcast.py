"""Hindcast of the forecast levels (docs/protocol.md §9.5): how much of the observed-rainfall skill survives on forecast
rainfall, by lead.

Rainfall: Open-Meteo previous-runs API (as §9.4), hourly precipitation_previous_day1..5 of ECMWF IFS 0.25 and GFS, on the
0.5-degree forecast grid (155 points; the 0.25-degree grid would take about six days of the free quota, decision log
2026-11-24), basin means with the operational weights, 12-12 UTC days. Lead L of day D = previous_day{L} over D's window.
Chain: issuance day X, observed basin rainfall through X-1, forecast rainfall for X .. X+4 (lead D - X + 1 = 1..5),
operational indices and frozen rules. Nothing is fitted.
    python -m floodwatch.hindcast download   # resumable; paced under the free-tier limits
    python -m floodwatch.hindcast evaluate   # -> data/processed/study/hindcast.json (+ hindcast_levels_<model>.csv.gz)
"""
import json
import sys
import time
from datetime import datetime, timezone

import pandas as pd
import requests

from . import upstream
from .forecast_skill import API, UA, Budget, weight
from .paths import RAW

ARCHIVE = RAW / 'hindcast'
MODELS = {'ECMWF': 'ecmwf_ifs025', 'GFS': 'gfs_global'}
LEADS = [1, 2, 3, 4, 5]
START, END = pd.Timestamp('2024-03-01'), pd.Timestamp('2025-12-31')
STEP = 0.5
CHUNK_DAYS = 92
BATCH = 20


def download():
    points, _ = upstream.forecast_grid(step=STEP)
    budget = Budget()
    hourly = ','.join(f'precipitation_previous_day{n}' for n in LEADS)
    chunks = pd.date_range(START - pd.Timedelta(days=1), END, freq=f'{CHUNK_DAYS}D')  # day D's window starts D-1 13 UTC
    for name, code in MODELS.items():
        folder = ARCHIVE / code
        folder.mkdir(parents=True, exist_ok=True)
        for c0 in chunks:
            c1 = min(c0 + pd.Timedelta(days=CHUNK_DAYS - 1), END)
            for off in range(0, len(points), BATCH):
                b = points.iloc[off:off + BATCH]
                path = folder / f'{c0:%Y%m%d}_{c1:%Y%m%d}_{off:03d}.json'
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
                    raise RuntimeError('rate limited repeatedly; stopping (run again later, it resumes)')
                path.write_text(r.text, encoding='utf-8')
                path.with_suffix('.http.json').write_text(json.dumps({
                    'url': r.url, 'time_utc': datetime.now(timezone.utc).isoformat(), 'bytes': len(r.content),
                    'points': b.point.tolist()}), encoding='utf-8')
                print(f'{name} {c0:%Y-%m-%d}..{c1:%Y-%m-%d} points {off}-{off + len(b) - 1} ok', flush=True)


# ---------------------------------------------------------------- analysis
SEED = 20261124


def forecast_frames(model):
    """{lead: basin forecast rainfall (date x codarea)} from the downloaded previous-runs files. Hourly series are
    joined across chunks before the 12-12 UTC sums, so no window is cut at a chunk boundary."""
    from .forecast import basin_mean, daily_12utc
    code = MODELS[model]
    _, weights = upstream.forecast_grid(step=STEP)
    hourly = {}  # (point, lead) -> list of Series
    for path in sorted((ARCHIVE / code).glob('*.json')):
        if path.name.endswith('.http.json'):
            continue
        meta = json.loads(path.with_suffix('.http.json').read_text(encoding='utf-8'))
        bodies = json.loads(path.read_text(encoding='utf-8'))
        bodies = bodies if isinstance(bodies, list) else [bodies]
        for point, body in zip(meta['points'], bodies):
            t = pd.to_datetime(body['hourly']['time'], utc=True)
            for lead in LEADS:
                hourly.setdefault((point, lead), []).append(
                    pd.Series(body['hourly'][f'precipitation_previous_day{lead}'], index=t, dtype=float))
    frames = {}
    for lead in LEADS:
        cols = {}
        for (point, l), parts in hourly.items():
            if l != lead:
                continue
            s = pd.concat(parts)
            cols[point] = daily_12utc(s[~s.index.duplicated()].sort_index())
        frames[lead] = basin_mean(pd.DataFrame(cols), weights)
    return frames


def issuance_levels(model, observed, rule, fc=None):
    """Levels of every issuance X (observed through X-1, forecast X .. X+4) -> long table date, codarea, lead, levels.
    fc: {lead: date x codarea} forecast rainfall (default: the raw previous-runs frames)."""
    import numpy as np
    from . import indices, rules, study
    fc = forecast_frames(model) if fc is None else fc
    cols = observed.columns
    out = []
    for x in pd.date_range(START, END - pd.Timedelta(days=len(LEADS) - 1)):
        days = [x + pd.Timedelta(days=lead - 1) for lead in LEADS]
        f = pd.DataFrame([fc[lead].reindex(columns=cols).loc[d] if d in fc[lead].index else pd.Series(np.nan, index=cols)
                          for lead, d in zip(LEADS, days)], index=pd.DatetimeIndex(days))
        series = pd.concat([observed.loc[:x - pd.Timedelta(days=1)], f])
        start_api = pd.Timestamp(series.index.max().year - 1, 1, 1)
        pe, edi, api = {}, {}, {}
        for code in cols:
            r, _ = indices.compute(series[code], study.CAL[0], study.CAL[1], series.index.max())
            pe[code], edi[code] = r.pe_mm.to_numpy(), r.edi.to_numpy()
            a = np.full(len(series), np.nan)
            tail = series.index >= start_api
            a[tail] = indices.api(series.loc[tail, code])  # identical to the full-series API (tests/test_ensemble.py)
            api[code] = a
        frame = lambda d: pd.DataFrame(d, index=series.index).iloc[-40:]
        t = study.predictors(series.iloc[-40:], frame(pe), frame(edi), frame(api))
        t = t[t.date >= x].copy()
        t['lead'] = (t.date - x).dt.days + 1
        t['level_EDI'] = rules.classify(t.EDI, t.P3, rule['EDI'])
        t['level_API'] = rules.classify(t.API, t.P3, rule['API'])
        t['issued'] = x
        out.append(t[['issued', 'date', 'codarea', 'lead', 'level_EDI', 'level_API']])
    return pd.concat(out, ignore_index=True)


def evaluate():
    """§9.5 scores: TSS (Watch or above) of the forecast levels vs official records, by model and lead, and the paired
    skill loss against the same rule on observed rainfall (same rows, block bootstrap, seed 20261124)."""
    import numpy as np
    from . import rules, study
    from . import validation_2025 as V
    from .paths import STUDY
    from .stats import BlockBootstrap, ci, score
    rain, _ = V.rain_through_2025()
    observed = rain.copy()
    table = V.predictor_table(rain)
    rule = rules.load_rules()
    table['obs_EDI'] = rules.classify(table.EDI, table.P3, rule['EDI'])
    table['obs_API'] = rules.classify(table.API, table.P3, rule['API'])
    units = pd.read_csv(STUDY / 'units.csv', dtype={'codarea': str})
    atlas = pd.read_csv(study.RAW / 'atlas/BD_Atlas_1991_2025_v1.1.csv', sep=';', encoding='latin1', low_memory=False)
    atlas = atlas[(atlas.Sigla_UF == 'RS') & atlas.Cod_Cobrade.isin(study.CODES)].copy()
    atlas['date'] = pd.to_datetime(atlas.Data_Evento, dayfirst=True)
    atlas['codarea'] = atlas.Cod_IBGE_Mun.astype(str)
    records = atlas[atlas.codarea.isin(units.codarea) & atlas.date.between(START, END)]
    events = study.chain_events(records)
    table['codarea'] = table.codarea.astype(str)
    sample = study.samples(table, events, records, START, END)
    out = {'period': [str(START.date()), str(END.date())], 'grid_deg': STEP, 'events': int(sample.label.sum()),
           'episodes': int(sample.loc[sample.label == 1, 'block'].nunique()), 'models': {}}
    for model in MODELS:
        lv = issuance_levels(model, observed, rule)
        lv['codarea'] = lv.codarea.astype(str)
        lv.to_csv(STUDY / f'hindcast_levels_{model}.csv.gz', index=False)
        res = {}
        for period, years in {'2024': [2024], '2025': [2025], 'all': [2024, 2025]}.items():
            s = sample[sample.year.isin(years)]
            wide = s[['date', 'codarea', 'label', 'block', 'year', 'month', 'obs_EDI', 'obs_API']]
            for lead in LEADS:
                part = lv[lv.lead == lead][['date', 'codarea', 'level_EDI', 'level_API']].rename(
                    columns={'level_EDI': f'fc{lead}_EDI', 'level_API': f'fc{lead}_API'})
                wide = wide.merge(part, on=['date', 'codarea'], how='left')
            res[period] = {}
            for ix in ('EDI', 'API'):
                need = [f'fc{lead}_{ix}' for lead in (1, 2, 3)] + [f'obs_{ix}']
                ok = wide[need].notna().all(axis=1) & (wide[need] >= 0).all(axis=1)
                w = wide[ok].reset_index(drop=True)
                if w.label.sum() == 0:
                    continue
                y = w.label.to_numpy()
                boot = BlockBootstrap(w, seed=SEED)
                obs_pred = (w[f'obs_{ix}'] >= 1).to_numpy(float)
                r = {'rows': int(len(w)), 'events': int(y.sum()), 'observed': score(obs_pred, y), 'leads': {}}
                for lead in LEADS:
                    col = f'fc{lead}_{ix}'
                    v = w[col].notna() & (w[col] >= 0)
                    p = (w[col] >= 1).to_numpy(float)
                    r['leads'][lead] = {k: float(x) for k, x in score(p[v], y[v]).items()}
                fc_preds = [(w[f'fc{lead}_{ix}'] >= 1).to_numpy(float) for lead in (1, 2, 3)]
                point_fc = float(np.mean([score(p, y)['TSS'] for p in fc_preds]))
                loss_reps = []
                for b in range(boot.n):
                    wb = boot[b]
                    loss_reps.append(np.mean([score(p, y, wb)['TSS'] for p in fc_preds]) - score(obs_pred, y, wb)['TSS'])
                r['primary_TSS_leads_1_3'] = point_fc
                r['skill_loss_vs_observed'] = {'diff': point_fc - float(score(obs_pred, y)['TSS']), 'CI95': ci(loss_reps)}
                res[period][ix] = r
                print(model, period, ix, 'obs TSS', round(r['observed']['TSS'], 3), 'fc TSS L1-3', round(point_fc, 3),
                      'loss', round(r['skill_loss_vs_observed']['diff'], 3), r['skill_loss_vs_observed']['CI95'], flush=True)
        out['models'][model] = res
    (STUDY / 'hindcast.json').write_text(json.dumps(out, indent=1, default=float), encoding='utf-8')
    return out


# ---------------------------------------------------------------- §9.6 bias correction
FIT = (pd.Timestamp('2024-03-01'), pd.Timestamp('2024-12-31'))
TEST_YEAR = 2025


def quantile_map(fc, obs):
    """Empirical quantile mapping (99 percentiles, all basins pooled, linear interpolation, constant correction beyond
    the fitted range): returns f(x) mapping forecast to observed quantiles."""
    import numpy as np
    q = np.linspace(0.01, 0.99, 99)
    f = np.asarray(fc, float)
    o = np.asarray(obs, float)
    ok = np.isfinite(f) & np.isfinite(o)
    fq, oq = np.quantile(f[ok], q), np.quantile(o[ok], q)
    fq, idx = np.unique(fq, return_index=True)  # dry quantiles repeat (0 mm): keep the first of each
    oq = oq[idx]
    lo_shift, hi_shift = oq[0] - fq[0], oq[-1] - fq[-1]

    def apply(x):
        x = np.asarray(x, float)
        y = np.interp(x, fq, oq)
        y = np.where(x < fq[0], x + lo_shift, y)
        y = np.where(x > fq[-1], x + hi_shift, y)
        return np.clip(y, 0, None)
    return apply


def corrected_frames(model, observed):
    """Raw frames and frames corrected with maps fitted on FIT (one per lead, basins pooled)."""
    raw = forecast_frames(model)
    corr = {}
    for lead, f in raw.items():
        fit = f.loc[FIT[0]:FIT[1]]
        o = observed.reindex(index=fit.index, columns=fit.columns)
        qm = quantile_map(fit.to_numpy().ravel(), o.to_numpy().ravel())
        corr[lead] = pd.DataFrame(qm(f.to_numpy()), index=f.index, columns=f.columns).where(f.notna())
    return raw, corr


def evaluate_bias_correction():
    """§9.6 primary: paired TSS difference (corrected - raw), Watch or above vs official records, mean of leads 1-3,
    TEST_YEAR only; adopted only if the whole 95 % CI lies above 0."""
    import numpy as np
    from . import rules, study
    from . import validation_2025 as V
    from .paths import STUDY
    from .stats import BlockBootstrap, ci, score
    rain, _ = V.rain_through_2025()
    rule = rules.load_rules()
    table = V.predictor_table(rain)
    table['codarea'] = table.codarea.astype(str)
    sample, _, _ = V.sample_2025(table)
    out = {'fit': [str(FIT[0].date()), str(FIT[1].date())], 'test_year': TEST_YEAR, 'models': {}}
    global START
    for model in MODELS:
        raw, corr = corrected_frames(model, rain)
        start0, START = START, pd.Timestamp(f'{TEST_YEAR}-01-01')
        try:
            lv = {'raw': issuance_levels(model, rain, rule, raw), 'corrected': issuance_levels(model, rain, rule, corr)}
        finally:
            START = start0
        res = {}
        for ix in ('EDI', 'API'):
            wide = sample[['date', 'codarea', 'label', 'block', 'year', 'month']].copy()
            for name, l in lv.items():
                l = l.assign(codarea=l.codarea.astype(str))
                for lead in (1, 2, 3):
                    part = l[l.lead == lead][['date', 'codarea', f'level_{ix}']].rename(columns={f'level_{ix}': f'{name}{lead}'})
                    wide = wide.merge(part, on=['date', 'codarea'], how='left')
            cols = [f'{n}{lead}' for n in lv for lead in (1, 2, 3)]
            w = wide[(wide[cols] >= 0).all(axis=1)].reset_index(drop=True)
            y = w.label.to_numpy()
            boot = BlockBootstrap(w, seed=SEED)
            preds = {n: [(w[f'{n}{lead}'] >= 1).to_numpy(float) for lead in (1, 2, 3)] for n in lv}
            tss = lambda n, wb=None: float(np.mean([score(p, y, wb)['TSS'] for p in preds[n]]))
            reps = [tss('corrected', boot[b]) - tss('raw', boot[b]) for b in range(boot.n)]
            c = ci(reps)
            res[ix] = {'rows': int(len(w)), 'events': int(y.sum()), 'TSS_raw': tss('raw'), 'TSS_corrected': tss('corrected'),
                       'diff': tss('corrected') - tss('raw'), 'CI95': c, 'adopt': bool(c[0] is not None and c[0] > 0)}
            print(model, ix, res[ix], flush=True)
        out['models'][model] = res
    (STUDY / 'bias_correction.json').write_text(json.dumps(out, indent=1, default=float), encoding='utf-8')
    return out


if __name__ == '__main__':
    if sys.argv[1:] == ['download']:
        download()
    elif sys.argv[1:] == ['evaluate']:
        evaluate()
    elif sys.argv[1:] == ['bias-correction']:
        evaluate_bias_correction()
