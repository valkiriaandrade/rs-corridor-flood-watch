"""Pre-registered threshold study (docs/protocol.md).

Corridor municipalities of BR-116/386/290 (RS) x day, 2013-2024.
Positives: Atlas Digital flood-type records (COBRADE 12100/12200/12300/13214).
Rainfall: MERGE V07B daily, area-weighted over the upstream basin of each municipality (ANA ottobacias,
floodwatch.upstream); the municipal-only rainfall is kept for comparison (docs/protocol.md §3, §9.1).
Predictors: rainfall accumulations, PE and EDI (calibration 1999-2012) and the API (climate-indices, k=0.90).
Run: python -m floodwatch.study --stage units   (then python -m floodwatch.upstream basins/rain)
     python -m floodwatch.study [--stage all|data|eval]
"""
import argparse
import json

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box

from . import indices
from .paths import RAW, STUDY as OUT
from .stats import (N_BOOT, BlockBootstrap, alert_threshold, auc, best_tss, candidates, ci, contingency,
                    holdout_folds, oos_alert, oos_predictions, score, year_folds)
CODES = [12100, 12200, 12300, 13214]
CAL = (1999, 2012)
START, END = pd.Timestamp('2013-01-01'), pd.Timestamp('2024-12-31')
DEDUP_DAYS, EXCLUDE_DAYS, EPISODE_GAP = 7, 15, 5
PREDICTORS = ['P1', 'P3', 'P7', 'P30', 'PE', 'EDI', 'API']
INDICES = ['EDI', 'API']  # flood-potential indices with thresholds and levels
MIN_ROAD_KM = 0.5


# ---------------------------------------------------------------- data stage
def corridor_units():
    mun = gpd.read_file(RAW / 'spatial/ibge_rs_municipios.geojson')
    names = pd.DataFrame(json.loads((RAW / 'spatial/ibge_rs_municipios_nomes.json').read_text(encoding='utf-8')))
    names['codarea'] = names.id.astype(str)
    mun = mun.merge(names[['codarea', 'nome']], on='codarea', how='left')
    roads = gpd.read_file(RAW / 'spatial/snv202404_corridors_rs.geojson')
    roads = roads[roads.Superficie_Federal != 'PLA']  # planned (unbuilt) segments are not roads yet
    # A municipality belongs to a corridor only with >= MIN_ROAD_KM of that BR inside it (no boundary slivers).
    inter = gpd.overlay(roads[['Codigo_BR', 'geometry']].to_crs('EPSG:5880'), mun[['codarea', 'geometry']].to_crs('EPSG:5880'),
                        how='intersection', keep_geom_type=True)
    inter['km'] = inter.length / 1000
    km = inter.groupby(['codarea', 'Codigo_BR']).km.sum().reset_index()
    km = km[km.km >= MIN_ROAD_KM]
    brs = km.groupby('codarea').Codigo_BR.apply(lambda x: '/'.join(sorted(set(x))))
    units = mun[mun.codarea.isin(brs.index)].copy()
    units['corridors'] = units.codarea.map(brs)
    return units.reset_index(drop=True), roads


def cell_weights(units, lat, lon, step=0.1):
    """Area of overlap of each grid cell (default 0.1 deg MERGE) with each municipality (equal-area CRS)."""
    half = step / 2
    cells = [{'iy': i, 'ix': j, 'geometry': box(lo - half, la - half, lo + half, la + half)}
             for i, la in enumerate(lat) for j, lo in enumerate(lon)]
    grid = gpd.GeoDataFrame(cells, crs='EPSG:4326')
    region = units.total_bounds
    grid = grid.cx[region[0] - .2:region[2] + .2, region[1] - .2:region[3] + .2]
    inter = gpd.overlay(units[['codarea', 'geometry']], grid, how='intersection', keep_geom_type=True)
    inter['area'] = inter.to_crs('EPSG:5880').area
    return inter[['codarea', 'iy', 'ix', 'area']]


def municipal_rain(units):
    cube = np.load(OUT / 'merge_rs_cube.npz', allow_pickle=True)
    rain, lat, lon, dates = cube['rain'], cube['lat'], cube['lon'], pd.to_datetime(cube['dates'])
    weights = cell_weights(units, lat, lon)
    series = {}
    for code, w in weights.groupby('codarea'):
        values = rain[:, w.iy.to_numpy(), w.ix.to_numpy()]  # days x cells
        area = np.broadcast_to(w.area.to_numpy(), values.shape)
        finite = np.isfinite(values)
        total = np.where(finite, area, 0).sum(axis=1)
        mean = np.where(finite, values * area, 0).sum(axis=1) / np.where(total > 0, total, np.nan)
        # A day counts only when cells covering >= 99% of the municipality are valid.
        mean[total < 0.99 * w.area.sum()] = np.nan
        series[code] = mean
    frame = pd.DataFrame(series, index=dates)
    return frame.loc[:END], weights


def study_rain(end=END):
    """Daily rainfall used by the study and the forecast: mean over the upstream basin (floodwatch.upstream)."""
    path = OUT / 'upstream_rain.csv.gz'
    if not path.exists():
        raise SystemExit('Falta upstream_rain.csv.gz: rode python -m floodwatch.upstream basins e rain')
    rain = pd.read_csv(path, index_col=0, parse_dates=True)
    rain.columns = rain.columns.astype(str)
    return rain.loc[:end]


def compute_indices(rain):
    pe, edi, api, meta = {}, {}, {}, {}
    for code in rain.columns:
        result, info = indices.compute(rain[code], CAL[0], CAL[1], END)
        pe[code] = result.pe_mm.to_numpy()
        edi[code] = result.edi.to_numpy()
        api[code] = indices.api(rain[code])
        meta[code] = {k: info[k] for k in ('missing_rain_days', 'pe_valid_days', 'edi_valid_days',
                                           'calibration_pe_samples_per_calendar_position')}
    frame = lambda d: pd.DataFrame(d, index=rain.index)
    return frame(pe), frame(edi), frame(api), meta


def predictors(rain, pe, edi, api=None):
    """Long table code x day; each value is the max over days d-1 and d (no post-d data)."""
    frames = {'P1': rain}
    for n in (3, 7, 30):
        frames[f'P{n}'] = rain.rolling(n, min_periods=n).sum()
    frames['PE'], frames['EDI'] = pe, edi
    if api is not None:
        frames['API'] = api
    long = []
    for name, frame in frames.items():
        windowed = frame.rolling(2, min_periods=2).max()
        long.append(windowed.stack(future_stack=True).rename(name))
    table = pd.concat(long, axis=1)
    table.index.names = ['date', 'codarea']
    return table.reset_index()


def chain_events(records, dedup_days=None, episode_gap=None):
    """Records of one municipality separated by <= dedup_days (chained on the previous record) form one event,
    dated by its first record. Events of any municipality chained with gaps <= episode_gap form an episode."""
    dedup_days = DEDUP_DAYS if dedup_days is None else dedup_days
    episode_gap = EPISODE_GAP if episode_gap is None else episode_gap
    records = records.sort_values(['codarea', 'date'])
    keep, last = [], {}
    for idx, row in records.iterrows():
        prev = last.get(row.codarea)
        if prev is None or (row.date - prev).days > dedup_days:
            keep.append(idx)
        last[row.codarea] = row.date
    cols = [c for c in ['Protocolo_S2iD', 'codarea', 'Nome_Municipio', 'date', 'Cod_Cobrade', 'Status'] if c in records]
    events = records.loc[keep, cols].sort_values('date').reset_index(drop=True)
    gap = events.date.diff().dt.days.fillna(episode_gap + 1)
    events['episode'] = (gap > episode_gap).cumsum()
    events['episode_id'] = 'EP-' + events.groupby('episode').date.transform('min').dt.strftime('%Y%m%d')
    return events


def atlas_events(units):
    atlas = pd.read_csv(RAW / 'atlas/BD_Atlas_1991_2025_v1.1.csv', sep=';', encoding='latin1', low_memory=False)
    atlas = atlas[(atlas.Sigla_UF == 'RS') & atlas.Cod_Cobrade.isin(CODES)].copy()
    atlas['date'] = pd.to_datetime(atlas.Data_Evento, dayfirst=True)
    atlas['codarea'] = atlas.Cod_IBGE_Mun.astype(str)
    all_rs = atlas.copy()
    atlas = atlas[atlas.codarea.isin(units.codarea) & atlas.date.between(START, END)]
    return chain_events(atlas), atlas, all_rs


def samples(table, events, atlas_records, start=START, end=END):
    """Case-control sample: event onsets (label 1, block = episode) and municipality-days more than EXCLUDE_DAYS from
    any flood-type record (label 0, block = year-month), within [start, end]."""
    table = table[table.date.between(start, end)].copy()
    table['label'] = 0
    table['block'] = 'NEG-' + table.date.dt.strftime('%Y-%m')
    pos_key = set(zip(events.codarea, events.date))
    episode = dict(zip(zip(events.codarea, events.date), events.episode_id))
    is_pos = [k in pos_key for k in zip(table.codarea, table.date)]
    table.loc[is_pos, 'label'] = 1
    table.loc[is_pos, 'block'] = [episode[k] for k in zip(table.codarea[is_pos], table.date[is_pos])]
    # negatives: exclude +-15 days around ANY flood-type record (not only deduplicated onsets)
    excluded = np.zeros(len(table), bool)
    by_code = atlas_records.groupby('codarea').date.apply(lambda s: s.to_numpy(dtype='datetime64[D]'))
    days = table.date.to_numpy(dtype='datetime64[D]')
    for code, recs in by_code.items():
        mask = (table.codarea == code).to_numpy()
        d = days[mask]
        near = np.zeros(mask.sum(), bool)
        for r in recs:
            near |= np.abs((d - r).astype(int)) <= EXCLUDE_DAYS
        excluded[np.where(mask)[0][near]] = True
    table = table[(table.label == 1) | ~excluded]
    table['year'] = table.date.dt.year
    table['month'] = table.date.dt.month
    return table.reset_index(drop=True)


def build_units():
    """Corridor municipalities, municipal cell weights and municipal-only rainfall (comparison and basin seeds)."""
    OUT.mkdir(parents=True, exist_ok=True)
    units, roads = corridor_units()
    rain, weights = municipal_rain(units)
    units.drop(columns='geometry').to_csv(OUT / 'units.csv', index=False)
    units[['codarea', 'nome', 'corridors', 'geometry']].to_file(OUT / 'units.geojson', driver='GeoJSON')
    weights.to_csv(OUT / 'cell_weights.csv', index=False)
    rain.to_csv(OUT / 'municipal_rain.csv.gz')
    return units


def build():
    units = build_units()
    rain = study_rain()[units.codarea.astype(str).tolist()]
    pe, edi, api, index_meta = compute_indices(rain)
    table = predictors(rain, pe, edi, api)
    events, atlas_corr, atlas_rs = atlas_events(units)
    sample = samples(table, events, atlas_corr)
    pe.to_csv(OUT / 'index_pe.csv.gz')
    edi.to_csv(OUT / 'index_edi.csv.gz')
    api.to_csv(OUT / 'index_api.csv.gz')
    events.to_csv(OUT / 'events.csv', index=False)
    sample.to_csv(OUT / 'samples.csv.gz', index=False)
    meta = {'protocol': 'docs/protocol.md', 'units': len(units), 'calibration': CAL,
            'rainfall': 'MERGE V07B final, area-weighted mean over the upstream basin (ANA ottobacias level 6)',
            'period': [str(START.date()), str(END.date())], 'codes': CODES,
            'atlas_records_corridor_period': int(len(atlas_corr)), 'events_after_dedup': int(len(events)),
            'episodes': int(events.episode_id.nunique()),
            'samples': {'positives': int(sample.label.sum()), 'negatives': int((sample.label == 0).sum())},
            'positives_with_all_predictors': int(sample[sample.label == 1][PREDICTORS].notna().all(axis=1).sum()),
            'rain_missing_days_by_unit_max': int(rain.loc[START:END].isna().sum().max()),
            'index_meta_example': next(iter(index_meta.values()))}
    (OUT / 'data.metadata.json').write_text(json.dumps(meta, indent=1, default=str), encoding='utf-8')
    print(json.dumps(meta, indent=1, default=str))


# ---------------------------------------------------------------- eval stage
def oos_combined(df, folds, a_col='EDI', b_col='P3'):
    pred = np.full(len(df), np.nan)
    thresholds = {}
    for name, test in folds:
        train = ~test
        tr = df[train]
        ga = np.unique(np.quantile(tr[a_col], np.linspace(0.0, 0.98, 25)))
        gb = np.unique(np.quantile(tr[b_col], np.linspace(0.5, 0.999, 40)))
        y = tr.label.to_numpy() == 1
        A, B = tr[a_col].to_numpy(), tr[b_col].to_numpy()
        best = (-1, None, None)
        for a in ga:
            ma = A >= a
            hit = (ma[:, None] & (B[:, None] >= gb[None, :]))
            tss = hit[y].mean(axis=0) - hit[~y].mean(axis=0)
            j = int(np.argmax(tss))
            if tss[j] > best[0]:
                best = (tss[j], a, gb[j])
        thresholds[name] = {'a': float(best[1]), 'b': float(best[2])}
        te = df[test]
        pred[test] = ((te[a_col].to_numpy() >= best[1]) & (te[b_col].to_numpy() >= best[2])).astype(float)
    return pred, thresholds


def big_episode_mask(df):
    """Rows of the largest April-May 2024 episode plus the negatives inside its date span (sensitivity analysis)."""
    pos = df.label == 1
    may24 = df[pos & df.date.between('2024-04-01', '2024-05-31')]
    block = may24.block.value_counts().idxmax()
    span = df.loc[df.block == block, 'date']
    mask = ((df.block == block) | (~pos & df.date.between(span.min(), span.max()))).to_numpy()
    return mask, {'block': block, 'start': str(span.min().date()), 'end': str(span.max().date()), 'rows_removed': int(mask.sum())}


def evaluate():
    df = pd.read_csv(OUT / 'samples.csv.gz', parse_dates=['date'], dtype={'codarea': str})
    df = df.dropna(subset=PREDICTORS).reset_index(drop=True)
    y = df.label.to_numpy()
    W = BlockBootstrap(df)  # positives by episode, negatives by year-month
    is_pos = W.pos
    results = {'n': {'rows': int(len(df)), 'positives': int(is_pos.sum()), 'negatives': int((~is_pos).sum()),
                     'episodes': int(W.n_pos_blocks),
                     'episodes_by_year': df[is_pos].groupby('year').block.nunique().to_dict(),
                     'positives_by_year': df[is_pos].groupby('year').size().to_dict()}}

    # 1) discrimination (AUC) on all data, per predictor + month baseline
    month_rate = df.groupby('month').label.mean()
    df['MONTH'] = df.month.map(month_rate)
    aucs = {}
    for col in PREDICTORS + ['MONTH']:
        pos, neg = df.loc[is_pos, col].to_numpy(), df.loc[~is_pos, col].to_numpy()
        point = auc(pos, neg)
        bs = [auc(pos, neg, W[b, is_pos], W[b, ~is_pos]) for b in range(N_BOOT)]
        aucs[col] = {'AUC': point, 'CI95': ci(bs)}
    results['auc'] = aucs

    # 2) leave-one-year-out and temporal holdout
    loyo, holdout = year_folds(df), holdout_folds(df)
    designs = {'LOYO': loyo, 'holdout_2013-2020_vs_2021-2024': holdout}
    # Sensitivity: drop the whole April-May 2024 episode (by block) and the negatives inside its date span.
    in_big24, big24_info = big_episode_mask(df)
    oos = {}
    preds = {}
    for dname, folds in designs.items():
        oos[dname] = {}
        for col in PREDICTORS:
            pred, thr = oos_predictions(df, col, folds)
            preds[(dname, col)] = pred
            oos[dname][col] = {'thresholds': thr}
        pred, thr = oos_combined(df, folds)
        preds[(dname, 'EDI&P3')] = pred
        oos[dname]['EDI&P3'] = {'thresholds': thr}
        for ix in INDICES:
            pred, thr = oos_alert(df, ix, folds)
            preds[(dname, f'{ix}_alert')] = pred
            oos[dname][f'{ix}_alert'] = {'thresholds': thr}
        mask_test = np.zeros(len(df), bool)
        for _, t in folds:
            mask_test |= t
        for col in oos[dname]:
            p = preds[(dname, col)]
            m = mask_test
            point = score(p[m], y[m])
            bs = [score(p[m], y[m], W[b, m]) for b in range(N_BOOT)]
            oos[dname][col].update({k: float(v) for k, v in point.items()})
            for k in ('TSS', 'POD', 'POFD'):
                oos[dname][col][k + '_CI95'] = ci([x[k] for x in bs])
            # sensitivity without the April-May 2024 episode(s)
            no24 = m & ~in_big24
            oos[dname][col]['TSS_without_AprMay2024'] = float(score(p[no24], y[no24])['TSS'])
    results['out_of_sample'] = oos
    results['sensitivity_episode'] = big24_info

    # 3) paired bootstrap: EDI and EDI&P3 vs best rainfall-only predictor (LOYO)
    rain_cols = ['P1', 'P3', 'P7', 'P30']
    best_rain = max(rain_cols, key=lambda c: oos['LOYO'][c]['TSS'])
    paired = {}
    for cand in ['EDI', 'PE', 'EDI&P3', 'API']:
        diffs = [score(preds[('LOYO', cand)], y, W[b])['TSS'] - score(preds[('LOYO', best_rain)], y, W[b])['TSS']
                 for b in range(N_BOOT)]
        paired[cand] = {'vs': best_rain, 'TSS_diff': oos['LOYO'][cand]['TSS'] - oos['LOYO'][best_rain]['TSS'],
                        'CI95': ci(diffs), 'adds_skill': bool(ci(diffs)[0] > 0)}
    results['paired_vs_best_rain'] = paired
    diffs = [score(preds[('LOYO', 'API')], y, W[b])['TSS'] - score(preds[('LOYO', 'EDI')], y, W[b])['TSS']
             for b in range(N_BOOT)]
    results['paired_API_vs_EDI'] = {'TSS_diff': oos['LOYO']['API']['TSS'] - oos['LOYO']['EDI']['TSS'],
                                    'CI95': ci(diffs), 'adds_skill': bool(ci(diffs)[0] > 0)}

    # 4) final thresholds refit on all 2013-2024 (procedure validated above)
    final = {}
    for col in PREDICTORS:
        pos, neg = df.loc[is_pos, col].to_numpy(), df.loc[~is_pos, col].to_numpy()
        grid = candidates(np.concatenate([pos, neg]))
        thr, pod, pofd = best_tss(pos, neg, grid)
        bs_thr = []
        for b in range(N_BOOT):
            wp, wn = W[b, is_pos], W[b, ~is_pos]
            pd_, pf_ = contingency(pos, neg, grid, wp, wn)
            bs_thr.append(grid[int(np.argmax(pd_ - pf_))])
        alert = alert_threshold(neg, grid)
        final[col] = {'attention': float(thr), 'attention_CI95': ci(bs_thr), 'POD': float(pod), 'POFD': float(pofd),
                      'alert_pofd2pct': float(alert),
                      'alert_POD': float((pos >= alert).mean()) if np.isfinite(alert) else None}
    # Combined rule refit on all rows.
    A, B = df.EDI.to_numpy(), df.P3.to_numpy()
    ga = np.unique(np.quantile(A, np.linspace(0, .98, 25)))
    gb = np.unique(np.quantile(B, np.linspace(.5, .999, 40)))
    best = (-1, None, None, None, None)
    for a in ga:
        hit = (A >= a)[:, None] & (B[:, None] >= gb[None, :])
        pod, pofd = hit[is_pos].mean(0), hit[~is_pos].mean(0)
        j = int(np.argmax(pod - pofd))
        if pod[j] - pofd[j] > best[0]:
            best = (pod[j] - pofd[j], a, gb[j], pod[j], pofd[j])
    final['EDI&P3'] = {'a_EDI': float(best[1]), 'b_P3': float(best[2]), 'POD': float(best[3]), 'POFD': float(best[4])}
    results['final_thresholds_all_years'] = final

    # 5) decision rule from the protocol
    dev_eps = df[is_pos & (df.year <= 2020)].block.nunique()
    test_eps = df[is_pos & (df.year >= 2021)].block.nunique()
    validated = {c: bool(oos['LOYO'][c]['TSS_CI95'][0] > 0.2) for c in oos['LOYO']}
    results['decision'] = {'episodes_dev_2013_2020': int(dev_eps), 'episodes_test_2021_2024': int(test_eps),
                           'sample_rule_met': bool(dev_eps >= 30 and test_eps >= 10),
                           'validated_TSS_lower_gt_0.2_LOYO': validated, 'best_rain_predictor': best_rain}
    (OUT / 'results.json').write_text(json.dumps(results, indent=1, default=float), encoding='utf-8')
    print(json.dumps({k: results[k] for k in ('n', 'auc', 'paired_vs_best_rain', 'decision')}, indent=1, default=float))
    for d in oos:
        print(d, {c: (round(v['TSS'], 3), [round(x, 3) for x in v['TSS_CI95']], round(v['POD'], 3), round(v['POFD'], 3))
                  for c, v in oos[d].items()})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', default='all', choices=['all', 'units', 'data', 'eval'])
    stage = parser.parse_args().stage
    if stage == 'units':
        build_units()
    if stage in ('all', 'data'):
        build()
    if stage in ('all', 'eval'):
        evaluate()
