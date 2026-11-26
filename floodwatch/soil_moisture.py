"""Soil moisture as antecedent state (docs/protocol.md §9.11).

ERA5-Land volumetric soil water, layers 1-3 (0-7, 7-28, 28-100 cm), from the Copernicus Climate Data Store (dataset
reanalysis-era5-land at 00/06/12/18 UTC, averaged per day; decision log 2026-11-24 and 2026-11-26),
combined as the 0-100 cm mean (7 L1 + 21 L2 + 72 L3) / 100. Basin means with the MERGE cell weights of the upstream
basins (each 0.1-degree MERGE cell takes the nearest ERA5-Land point; ties to the north/east), standardised per
calendar day on 1999-2012 (Feb 29 uses Feb 28), predictor = max of d-1 and d like every other predictor.
Tests, leave-one-year-out, same samples and bootstrap as §7:
  (i)  SM anomaly alone as an index (threshold = max TSS on the training years), paired vs the API alone;
  (ii) "API dashboard rule OR (SM anomaly >= s AND P1 >= q)", s and q fitted in each training fold on grids of their
       training quantiles 0.80-0.995, paired vs the API dashboard rule. Improvement only if the paired CI is above 0.
    python -m floodwatch.soil_moisture download   # resumable, one CDS request per year
    python -m floodwatch.soil_moisture check      # 4-hour mean vs 24-hour mean on the months fetched both ways
    python -m floodwatch.soil_moisture evaluate   # -> data/processed/study/soil_moisture.json
"""
import json
import pathlib
import sys

import numpy as np
import pandas as pd

from .paths import RAW, STUDY

ARCHIVE = RAW / 'era5land'
AREA = [-26.0, -57.5, -34.5, -49.0]   # N, W, S, E: every upstream MERGE cell (-34.45..-26.25, -57.35..-49.25)
YEARS = range(1999, 2026)
CAL = (1999, 2012)
LAYERS = {'swvl1': 7, 'swvl2': 21, 'swvl3': 72}  # thickness (cm) within 0-100 cm
SEED = 20261124
SYNOPTIC = ['00:00', '06:00', '12:00', '18:00']


def _client():
    import cdsapi
    return cdsapi.Client(quiet=True, progress=False)


def _retrieve(dataset, request, path):
    """One request at a time; wait while the dataset's global queue is full. Only complete files count as done."""
    import time
    tmp = path.with_suffix('.part')
    while True:
        try:
            _client().retrieve(dataset, request, str(tmp))
            break
        except Exception as error:
            if 'queued requests' not in str(error):
                raise
            print(dataset, 'queue full, waiting 15 min', flush=True)
            time.sleep(900)
    tmp.replace(path)


def download():
    """Hourly ERA5-Land at 00, 06, 12 and 18 UTC, one request per year (8,928 of the 12,000 cost units allowed).
    The daily-statistics dataset allows only ~4 months per request and its queue held each request ~6 h (decision log
    2026-11-26); the daily mean of the four synoptic hours replaces the 24-hour mean."""
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    for year in YEARS:
        path = ARCHIVE / f'sm6h_{year}.nc'
        if path.exists():
            continue
        _retrieve('reanalysis-era5-land', {
            'variable': ['volumetric_soil_water_layer_1', 'volumetric_soil_water_layer_2', 'volumetric_soil_water_layer_3'],
            'year': str(year), 'month': [f'{m:02d}' for m in range(1, 13)], 'day': [f'{d:02d}' for d in range(1, 32)],
            'time': SYNOPTIC, 'data_format': 'netcdf', 'download_format': 'unarchived', 'area': AREA}, path)
        print('ERA5-Land', year, 'ok', flush=True)


def _daily(d):
    """0-100 cm daily mean (time x lat x lon) from a 6-hourly file."""
    sm = sum(d[v] * k for v, k in LAYERS.items()) / 100
    sm = sm.rename({'valid_time': 'time'}) if 'valid_time' in sm.dims else sm
    return sm.resample(time='1D').mean(skipna=False)


def basin_sm():
    """Daily 0-100 cm soil moisture (m3/m3) per upstream basin (date x codarea)."""
    import xarray as xr

    from . import upstream
    w = upstream.weights()
    lat = np.floor(upstream.LAT[w.iy] * 10 + 0.5) / 10
    lon = np.floor(upstream.LON[w.ix] * 10 + 0.5) / 10
    frames = []
    for path in sorted(ARCHIVE.glob('sm6h_*.nc')):
        with xr.open_dataset(path) as d:
            sm = _daily(d)
            pick = sm.sel(latitude=xr.DataArray(lat, dims='cell'), longitude=xr.DataArray(lon, dims='cell'), method='nearest')
            vals = pick.to_numpy()  # time x cell
            times = pd.to_datetime(pick['time'].to_numpy()).normalize()
        cell = pd.DataFrame(vals, index=times)
        out = {}
        for code, g in w.reset_index(drop=True).groupby('codarea'):
            v = cell[g.index.to_numpy()]
            out[code] = (v * g.area.to_numpy()).sum(axis=1).where(v.notna().all(axis=1)) / g.area.sum()
        frames.append(pd.DataFrame(out))
    return pd.concat(frames).sort_index()


def check_synoptic_mean():
    """Difference between the 4-synoptic-hour mean and the 24-hour daily mean, on the months downloaded from the
    daily-statistics dataset (sm_YYYYMM.nc, zip archives with one file per layer)."""
    import tempfile
    import zipfile

    import xarray as xr
    rows = []
    for path in sorted(ARCHIVE.glob('sm_[0-9]*.nc')):
        year = int(path.stem[3:7])
        six = ARCHIVE / f'sm6h_{year}.nc'
        if not six.exists():
            continue
        with tempfile.TemporaryDirectory() as tmp:
            zipfile.ZipFile(path).extractall(tmp)
            layers = {}
            for f in pathlib.Path(tmp).glob('*.nc'):
                with xr.open_dataset(f) as d:
                    v = d[list(d.data_vars)[0]].load()
                layers[v.name] = v
        full = sum(layers[v] * k for v, k in LAYERS.items()) / 100
        full = full.rename({'valid_time': 'time'}) if 'valid_time' in full.dims else full
        with xr.open_dataset(six) as d:
            syn = _daily(d).sel(time=full['time']).load()
        diff = (syn - full).to_numpy().ravel()
        diff = diff[np.isfinite(diff)]
        rows.append({'month': path.stem[3:], 'mean_diff': float(diff.mean()), 'p99_abs_diff': float(np.quantile(abs(diff), 0.99)),
                     'sd_full': float(np.nanstd(full.to_numpy()))})
    print(pd.DataFrame(rows).to_string(index=False))
    return rows


def anomaly(sm):
    """Standardised per calendar day on CAL (Feb 29 uses Feb 28's climatology)."""
    key = sm.index.strftime('%m-%d').str.replace('02-29', '02-28')
    cal = sm[(sm.index.year >= CAL[0]) & (sm.index.year <= CAL[1])]
    ckey = cal.index.strftime('%m-%d').str.replace('02-29', '02-28')
    mean, sd = cal.groupby(ckey).mean(), cal.groupby(ckey).std()
    return (sm - mean.loc[key].to_numpy()) / sd.loc[key].to_numpy()


def _fit_or(df, train, thr_api, b_api, s_grid_q=np.linspace(0.80, 0.995, 40)):
    tr = df[train]
    base = ((tr.API >= thr_api) | (tr.P3 >= b_api)).to_numpy()
    y = tr.label.to_numpy()
    pos, neg = y == 1, y == 0
    sg = np.unique(np.quantile(tr.SM.dropna(), s_grid_q))
    qg = np.unique(np.quantile(tr.P1.dropna(), s_grid_q))
    sm, p1 = tr.SM.to_numpy(), tr.P1.to_numpy()
    best = (-np.inf, None, None)
    for s in sg:
        hs = sm >= s
        for q in qg:
            hit = base | (hs & (p1 >= q))
            tss = hit[pos].mean() - hit[neg].mean()
            if tss > best[0]:
                best = (tss, float(s), float(q))
    return best[1], best[2]


def evaluate():
    from . import study
    from .second_trigger import fit_rule
    from .stats import BlockBootstrap, auc, oos_predictions, paired, scores, year_folds
    an = anomaly(basin_sm())
    windowed = an.rolling(2, min_periods=2).max().stack(future_stack=True).rename('SM').reset_index()
    windowed.columns = ['date', 'codarea', 'SM']
    windowed['codarea'] = windowed.codarea.astype(str)
    df = pd.read_csv(STUDY / 'samples.csv.gz', parse_dates=['date'], dtype={'codarea': str})
    df = df.dropna(subset=study.PREDICTORS).merge(windowed, on=['date', 'codarea'], how='left')
    missing = int(df.SM.isna().sum())
    df = df.dropna(subset=['SM']).reset_index(drop=True)
    y = df.label.to_numpy()
    W = BlockBootstrap(df, seed=SEED)
    folds = year_folds(df)
    sm_alone, sm_thr = oos_predictions(df, 'SM', folds)
    api_alone, _ = oos_predictions(df, 'API', folds)
    api_rule, combo = np.full(len(df), np.nan), np.full(len(df), np.nan)
    params = {}
    for name, test in folds:
        thr, b = fit_rule(df, 'API', ~test)
        s, q = _fit_or(df, ~test, thr, b)
        params[name] = {'API': thr, 'P3': b, 'SM': s, 'P1': q}
        te = df[test]
        rule = (te.API >= thr) | (te.P3 >= b)
        api_rule[test] = rule.to_numpy(float)
        combo[test] = (rule | ((te.SM >= s) & (te.P1 >= q))).to_numpy(float)
    pos, neg = df.label == 1, df.label == 0
    out = {'rows': int(len(df)), 'rows_without_sm': missing, 'positives': int(y.sum()),
           'AUC_SM': auc(df.SM[pos].to_numpy(), df.SM[neg].to_numpy()),
           'i_SM_alone': scores(sm_alone, y, W), 'i_API_alone': scores(api_alone, y, W),
           'i_paired_SM_minus_API': paired(sm_alone, api_alone, y, W), 'SM_thresholds_by_fold': sm_thr,
           'ii_API_rule': scores(api_rule, y, W), 'ii_API_rule_OR_SM_and_P1': scores(combo, y, W),
           'ii_paired_combo_minus_rule': paired(combo, api_rule, y, W), 'ii_params_by_fold': params}
    (STUDY / 'soil_moisture.json').write_text(json.dumps(out, indent=1, default=float), encoding='utf-8')
    for k in ('i_SM_alone', 'i_API_alone', 'ii_API_rule', 'ii_API_rule_OR_SM_and_P1'):
        print(k, round(out[k]['TSS'], 3), out[k]['TSS_CI95'])
    print('i paired', out['i_paired_SM_minus_API'], '| ii paired', out['ii_paired_combo_minus_rule'])
    return out


if __name__ == '__main__':
    {'download': download, 'evaluate': evaluate, 'check': check_synoptic_mean}[sys.argv[1]]()
