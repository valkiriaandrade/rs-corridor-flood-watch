"""ANA-based analyses registered in docs/protocol.md (§3, §8.2, §9.1, §9.2).

B. EDI and API from upstream-basin rainfall (Ottobacias) vs the municipal versions: same samples, procedure and tests.
C. River levels (HidroWeb) as an extra validation target, with the frozen 2013-2024 thresholds (no refit).
D. River in flood on D-1 as an extra predictor next to the basin indices (§9.2).
The study itself uses upstream-basin rainfall (§3); here the municipal-only version is rebuilt explicitly.
    python -m floodwatch.ana_validation upstream   -> data/processed/study/upstream_results.json
    python -m floodwatch.ana_validation rivers     -> data/processed/study/river_validation.json
    python -m floodwatch.ana_validation river-predictor -> data/processed/study/river_predictor.json
"""
import argparse
import json

import numpy as np
import pandas as pd

from . import indices, study
from .paths import STUDY
from .stats import BlockBootstrap as Boot, ci, paired, scores

UP = ['EDI_bacia', 'API_bacia']
MIN_VALID_SHARE, MIN_YEARS, MIN_DAYS_YEAR = 0.70, 8, 300


def index_frames(rain, end):
    """EDI and API (date x codarea) from daily rainfall, study calibration."""
    edi, api = {}, {}
    for code in rain.columns:
        r, _ = indices.compute(rain[code], study.CAL[0], study.CAL[1], end)
        edi[code], api[code] = r.edi.to_numpy(), indices.api(rain[code])
    return pd.DataFrame(edi, index=rain.index), pd.DataFrame(api, index=rain.index)


def windowed_long(frames):
    long = [f.rolling(2, min_periods=2).max().stack(future_stack=True).rename(n) for n, f in frames.items()]
    t = pd.concat(long, axis=1)
    t.index.names = ['date', 'codarea']
    return t.reset_index()


def upstream_rain():
    r = pd.read_csv(STUDY / 'upstream_rain.csv.gz', index_col=0, parse_dates=True)
    r.columns = r.columns.astype(str)
    return r


def municipal_rain_frame(end):
    r = pd.read_csv(STUDY / 'municipal_rain.csv.gz', index_col=0, parse_dates=True)
    r.columns = r.columns.astype(str)
    return r.loc[:end]


def municipal_table(end):
    """EDI and API from municipal-only rainfall (the comparison version), windowed like every predictor."""
    edi, api = index_frames(municipal_rain_frame(end), end)
    return windowed_long({'EDI': edi, 'API': api})


def upstream_table(end):
    rain = upstream_rain().loc[:end]
    edi, api = index_frames(rain, end)
    return windowed_long({'EDI_bacia': edi, 'API_bacia': api})


# ---------------------------------------------------------------- B. upstream
def evaluate_upstream():
    df = pd.read_csv(STUDY / 'samples.csv.gz', parse_dates=['date'], dtype={'codarea': str})
    df = df.drop(columns=['EDI', 'API']).merge(municipal_table(study.END), on=['date', 'codarea'], how='left')
    df = df.merge(upstream_table(study.END), on=['date', 'codarea'], how='left')
    cols = ['EDI', 'API', 'EDI_bacia', 'API_bacia']  # EDI/API = municipal rainfall; *_bacia = upstream basin
    before = len(df)
    df = df.dropna(subset=study.PREDICTORS + UP).reset_index(drop=True)
    y = df.label.to_numpy()
    W = Boot(df)
    pos = W.pos
    res = {'n': {'rows': int(len(df)), 'rows_dropped_missing_upstream': int(before - len(df)),
                 'positives': int(pos.sum()), 'episodes': int(df.block[pos].nunique())},
           'auc': {}, 'out_of_sample': {}, 'paired': {}, 'final_thresholds_all_years': {}}
    for c in cols:
        p_, n_ = df.loc[pos, c].to_numpy(), df.loc[~pos, c].to_numpy()
        res['auc'][c] = {'AUC': float(study.auc(p_, n_)),
                         'CI95': ci([study.auc(p_, n_, W[b][pos], W[b][~pos]) for b in range(W.n)])}
    designs = {'LOYO': [(str(yr), (df.year == yr).to_numpy()) for yr in sorted(df.year.unique())],
               'holdout_2013-2020_vs_2021-2024': [('2021-2024', (df.year >= 2021).to_numpy())]}
    preds = {}
    for dn, folds in designs.items():
        res['out_of_sample'][dn] = {}
        m = np.zeros(len(df), bool)
        for _, t in folds:
            m |= t
        for c in cols:
            p, thr = study.oos_predictions(df, c, folds)
            pa, thr_a = study.oos_alert(df, c, folds)
            preds[(dn, c)], preds[(dn, c + '_alert')] = p, pa
            for name, pp, th in ((c, p, thr), (c + '_alert', pa, thr_a)):
                res['out_of_sample'][dn][name] = {**scores(pp[m], y[m], W.subset(m)),
                                                  'fold_thresholds': [min(th.values()), max(th.values())]}
    for a, b in [('EDI_bacia', 'EDI'), ('API_bacia', 'API'), ('API', 'EDI'), ('API_bacia', 'EDI')]:
        res['paired'][f'{a}-{b}'] = paired(preds[('LOYO', a)], preds[('LOYO', b)], y, W)
    for c in cols:
        p_, n_ = df.loc[pos, c].to_numpy(), df.loc[~pos, c].to_numpy()
        grid = study.candidates(np.concatenate([p_, n_]))
        thr, pod, pofd = study.best_tss(p_, n_, grid)
        bs_thr = []
        for b in range(W.n):
            pd_, pf_ = study.contingency(p_, n_, grid, W[b][pos], W[b][~pos])
            bs_thr.append(grid[int(np.argmax(pd_ - pf_))])
        alert = study.alert_threshold(n_, grid)
        res['final_thresholds_all_years'][c] = {'attention': float(thr), 'attention_CI95': ci(bs_thr), 'POD': float(pod),
                                                'POFD': float(pofd), 'alert_pofd2pct': float(alert),
                                                'alert_POD': float((p_ >= alert).mean())}
    try:
        res['test_2025'] = test_2025_upstream(res['final_thresholds_all_years'])
    except Exception as e:  # keep 2013-2024 results if 2025 rainfall is incomplete
        res['test_2025'] = {'error': f'{type(e).__name__}: {e}'}
    res['units'] = pd.read_csv(STUDY / 'upstream_units.csv', dtype={'codarea': str}).to_dict('records')
    (STUDY / 'upstream_results.json').write_text(json.dumps(res, indent=1, default=float), encoding='utf-8')
    print(json.dumps({k: res[k] for k in ('n', 'auc', 'paired')}, indent=1))
    return res


def test_2025_upstream(final):
    from . import validation_2025 as V
    from .merge_cube import area_series, municipal_weights
    recent, _ = area_series(municipal_weights(), str(V.START.date()), str(V.END.date()))
    rain, _ = V.rain_through_2025(municipal_rain_frame('2024-12-31'), recent)   # municipal-only rainfall
    up, _ = V.rain_through_2025()                                                # upstream-basin rainfall
    edi, api = index_frames(rain, V.END + pd.Timedelta(days=1))
    eb, ab = index_frames(up, V.END + pd.Timedelta(days=1))
    sample, _, _ = V.sample_2025(windowed_long({'EDI': edi, 'API': api, 'EDI_bacia': eb, 'API_bacia': ab}))
    sample = sample.dropna(subset=['EDI', 'API'] + UP).reset_index(drop=True)
    y = sample.label.to_numpy()
    W = Boot(sample)
    out = {'events': int(W.pos.sum()), 'episodes': int(sample.block[W.pos].nunique())}
    preds = {}
    for c in ['EDI', 'API'] + UP:
        preds[c] = (sample[c] >= final[c]['attention']).to_numpy(float)
        preds[c + '_alert'] = (sample[c] >= final[c]['alert_pofd2pct']).to_numpy(float)
    for c, p in preds.items():
        out[c] = scores(p, y, W)
    out['paired'] = {f'{a}-{b}': paired(preds[a], preds[b], y, W)
                     for a, b in [('EDI_bacia', 'EDI'), ('API_bacia', 'API'), ('API', 'EDI')]}
    pos = sample[W.pos]
    out['by_episode'] = {str(k): {'events': int(len(g)), **{f'{c}_at_watch': float((g[c] >= final[c]['attention']).mean())
                                                            for c in ['EDI', 'API'] + UP}}
                         for k, g in pos.groupby('block') if len(g) >= 5}
    return out


# ---------------------------------------------------------------- C. rivers
def river_events():
    """Station flood days (level >= median of annual maxima) -> municipality events and the days with a valid level."""
    levels = pd.read_csv(STUDY / 'ana_levels.csv.gz', index_col=0, parse_dates=True)
    st = pd.read_csv(STUDY / 'ana_stations.csv', dtype={'Codigo': str, 'codarea': str})
    levels = levels.loc[study.START:study.END]
    rows, valid, used = [], [], []
    for s in st.itertuples():
        if s.Codigo not in levels:
            continue
        v = levels[s.Codigo]
        per_year = v.groupby(v.index.year).count()
        good_years = per_year[per_year >= MIN_DAYS_YEAR].index
        share = v.notna().mean()
        if share < MIN_VALID_SHARE or len(good_years) < MIN_YEARS:
            used.append({'station': s.Codigo, 'used': False, 'valid_share': float(share), 'years_ok': int(len(good_years))})
            continue
        annual_max = v[v.index.year.isin(good_years)].groupby(v.index.year[v.index.year.isin(good_years)]).max()
        thr = float(annual_max.median())
        over = v[v >= thr].index
        rows += [{'codarea': s.codarea, 'date': d, 'station': s.Codigo} for d in over]
        valid.append(pd.DataFrame({'codarea': s.codarea, 'date': v.dropna().index}))
        used.append({'station': s.Codigo, 'name': s.Nome, 'river': s.RioNome, 'codarea': s.codarea, 'municipio': s.nome,
                     'drainage_km2': float(s.AreaDrenagem), 'used': True, 'valid_share': float(share),
                     'years_ok': int(len(good_years)), 'threshold_cm': thr, 'days_over': int(len(over))})
    over = pd.DataFrame(rows).drop_duplicates(['codarea', 'date'])
    valid = pd.concat(valid).drop_duplicates()
    events = study.chain_events(over[['codarea', 'date']].copy())
    return events, over, valid, pd.DataFrame(used)


def evaluate_rivers():
    events, over, valid, stations = river_events()
    codes = sorted(valid.codarea.unique())
    basin = study.study_rain()[codes]
    p30 = windowed_long({'P30': basin.rolling(30, min_periods=30).sum(), 'P3': basin.rolling(3, min_periods=3).sum()})
    edi_m, api_m = index_frames(municipal_rain_frame(study.END)[codes], study.END)
    table = windowed_long({'EDI': edi_m, 'API': api_m}).merge(p30, on=['date', 'codarea'])
    table = table.merge(upstream_table(study.END), on=['date', 'codarea'], how='left')
    sample = study.samples(table, events, over)
    key = set(zip(valid.codarea, valid.date))
    has_level = np.array([k in key for k in zip(sample.codarea, sample.date)])
    sample = sample[(sample.label == 1) | has_level]
    cols = ['P30', 'EDI', 'API', 'EDI_bacia', 'API_bacia']
    sample = sample.dropna(subset=cols + ['P3']).reset_index(drop=True)
    y = sample.label.to_numpy()
    W = Boot(sample)
    res_main = json.loads((STUDY / 'results.json').read_text(encoding='utf-8'))['final_thresholds_all_years']
    res_up = json.loads((STUDY / 'upstream_results.json').read_text(encoding='utf-8'))['final_thresholds_all_years']
    frozen = {c: (res_main if c == 'P30' else res_up)[c] for c in cols}  # P30: basin rainfall (study)
    out = {'stations': stations.to_dict('records'), 'municipalities': len(codes),
           'events': int(W.pos.sum()), 'episodes': int(sample.block[W.pos].nunique()), 'negatives': int((~W.pos).sum()),
           'frozen_thresholds': {c: {'attention': frozen[c]['attention'], 'alert': frozen[c]['alert_pofd2pct']} for c in cols},
           'auc': {}, 'scores': {}, 'paired': {}}
    preds = {}
    for c in cols:
        p_, n_ = sample.loc[W.pos, c].to_numpy(), sample.loc[~W.pos, c].to_numpy()
        out['auc'][c] = {'AUC': float(study.auc(p_, n_)),
                         'CI95': ci([study.auc(p_, n_, W[b][W.pos], W[b][~W.pos]) for b in range(W.n)])}
        preds[c] = (sample[c] >= frozen[c]['attention']).to_numpy(float)
        if c != 'P30':
            preds[c + '_alert'] = (sample[c] >= frozen[c]['alert_pofd2pct']).to_numpy(float)
    # dashboard rule (basin index OR frozen 3-day trigger), frozen thresholds; descriptive, nothing re-tuned
    trig = STUDY / 'second_trigger.json'
    if trig.exists():
        final = json.loads(trig.read_text(encoding='utf-8'))['final_frozen']
        out['dashboard_rule'] = {}
        for ix in ('EDI', 'API'):
            f = final[ix]
            preds[ix + '_bacia_rule'] = ((sample[ix + '_bacia'] >= f['index_attention']) | (sample.P3 >= f['P3_mm'])).to_numpy(float)
            out['dashboard_rule'][ix] = {'index_attention': f['index_attention'], 'P3_mm': f['P3_mm']}
    for c, p in preds.items():
        out['scores'][c] = scores(p, y, W)
    for a, b in [('API', 'EDI'), ('EDI_bacia', 'EDI'), ('API_bacia', 'API'), ('EDI', 'P30')]:
        out['paired'][f'{a}-{b}'] = paired(preds[a], preds[b], y, W)
    out['events_by_year'] = sample[W.pos].groupby('year').size().to_dict()
    (STUDY / 'river_validation.json').write_text(json.dumps(out, indent=1, default=float), encoding='utf-8')
    print(json.dumps({k: out[k] for k in ('municipalities', 'events', 'episodes', 'auc', 'paired')}, indent=1, default=float))
    print(json.dumps({c: (round(v['TSS'], 3), v['TSS_CI95']) for c, v in out['scores'].items()}, default=float))
    return out


# ---------------------------------------------------------------- D. river state as predictor
def river_flood_days():
    """Set of (codarea, date) with any valid station of the municipality at or above its flood level (§8.2 rule)."""
    _, over, valid, stations = river_events()
    return set(zip(over.codarea, over.date)), set(zip(valid.codarea, valid.date)), stations


def evaluate_river_predictor():
    over, valid, stations = river_flood_days()
    codes = sorted({c for c, _ in valid})
    df = pd.read_csv(STUDY / 'samples.csv.gz', parse_dates=['date'], dtype={'codarea': str})
    df = df[df.codarea.isin(codes)].dropna(subset=['EDI', 'API']).reset_index(drop=True)
    prev = df.date - pd.Timedelta(days=1)
    df['river_d1'] = [float((c, d) in over) for c, d in zip(df.codarea, prev)]
    df['river_d1_valid'] = [(c, d) in valid for c, d in zip(df.codarea, prev)]
    df = df[df.river_d1_valid].reset_index(drop=True)  # only days whose D-1 stage is known
    fin = json.loads((STUDY / 'results.json').read_text(encoding='utf-8'))['final_thresholds_all_years']
    y = df.label.to_numpy()
    W = Boot(df)
    out = {'municipalities': len(codes), 'events': int(W.pos.sum()), 'episodes': int(df.block[W.pos].nunique()),
           'negatives': int((~W.pos).sum()), 'rules': {}, 'paired': {}}
    river = df.river_d1.to_numpy()
    out['rules']['river_d1'] = scores(river, y, W)
    for ix in ('EDI', 'API'):
        idx = (df[ix] >= fin[ix]['attention']).to_numpy(float)
        both = np.maximum(idx, river)
        out['rules'][ix] = scores(idx, y, W)
        out['rules'][f'{ix}_or_river'] = scores(both, y, W)
        out['paired'][f'{ix}_or_river-{ix}'] = paired(both, idx, y, W)
    out['thresholds'] = {ix: fin[ix]['attention'] for ix in ('EDI', 'API')}
    (STUDY / 'river_predictor.json').write_text(json.dumps(out, indent=1, default=float), encoding='utf-8')
    print(json.dumps(out, indent=1, default=float))
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('what', choices=['upstream', 'rivers', 'river-predictor'])
    a = ap.parse_args()
    {'upstream': evaluate_upstream, 'rivers': evaluate_rivers, 'river-predictor': evaluate_river_predictor}[a.what]()
