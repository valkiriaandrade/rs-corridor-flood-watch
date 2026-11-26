"""GloFAS benchmark (docs/protocol.md §9.8).

GloFAS v4.0 consolidated reanalysis, daily mean river discharge (CEMS Early Warning Data Store, dataset
cems-glofas-historical; decision log 2026-11-24). For each corridor municipality, the GloFAS cell (0.05 degree) whose
centre lies inside the municipality with the largest mean discharge 1999-2012 (its main river). Predictor: discharge
divided by the cell's median annual maximum 1999-2012 (the EDI calibration years), max of d-1 and d. Threshold fitted
exactly as §7 (leave-one-year-out, maximum TSS) on the same samples. Primary: paired TSS difference API dashboard rule -
GloFAS rule (LOYO); secondary: temporal holdout and the 2025 test. GloFAS reanalysis is forced by reanalysed weather, so
it is compared with the observed-rainfall study, not with the forecast levels.
    python -m floodwatch.glofas download   # sequential (the EWDS rejects parallel requests), one request per year
    python -m floodwatch.glofas evaluate   # -> data/processed/study/glofas.json
"""
import json
import pathlib
import sys

import numpy as np
import pandas as pd

from .paths import RAW, STUDY

ARCHIVE = RAW / 'glofas'
AREA = [-27.0, -57.5, -32.8, -49.9]   # N, W, S, E: the 86 corridor municipalities (-57.33..-50.06, -32.66..-27.17)
YEARS = range(1999, 2026)
CAL = (1999, 2012)
SEED = 20261124
URL = 'https://ewds.climate.copernicus.eu/api'


def _client():
    import cdsapi
    key = [l.split(':', 1)[1].strip() for l in (pathlib.Path.home() / '.cdsapirc').read_text().splitlines()
           if l.startswith('key:')][0]  # same ECMWF account token as the CDS
    return cdsapi.Client(url=URL, key=key, quiet=True, progress=False)


def download():
    import time
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    c = _client()
    for year in YEARS:
        path = ARCHIVE / f'glofas_{year}.nc'
        if path.exists():
            continue
        while True:
            try:
                c.retrieve('cems-glofas-historical', {
                    'system_version': ['version_4_0'], 'hydrological_model': ['lisflood'], 'product_type': ['consolidated'],
                    'timespan': ['time_mean'], 'variable': ['average_river_discharge_in_the_last_24_hours'],
                    'year': [str(year)], 'month': [f'{m:02d}' for m in range(1, 13)], 'day': [f'{d:02d}' for d in range(1, 32)],
                    'data_format': 'netcdf', 'download_format': 'unarchived', 'area': AREA}, str(path.with_suffix('.part')))
                path.with_suffix('.part').replace(path)
                print('GloFAS', year, 'ok', flush=True)
                break
            except Exception as error:
                if 'queued requests' not in str(error):
                    raise
                print('GloFAS queue full, waiting 15 min', flush=True)
                time.sleep(900)


def discharge():
    """Daily discharge (time x lat x lon) for all downloaded years, as one DataArray."""
    import xarray as xr
    arrays = []
    for path in sorted(ARCHIVE.glob('glofas_*.nc')):
        with xr.open_dataset(path) as d:
            v = d[list(d.data_vars)[0]]
            v = v.rename({'valid_time': 'time'}) if 'valid_time' in v.dims else v
            arrays.append(v.load())
    return xr.concat(arrays, 'time').sortby('time')


def municipal_ratio():
    """Discharge / median annual maximum 1999-2012 at each municipality's main-river cell (date x codarea)."""
    import geopandas as gpd

    from . import study
    q = discharge()
    times = pd.to_datetime(q['time'].to_numpy()).normalize()
    lat, lon = q['latitude'].to_numpy(), q['longitude'].to_numpy()
    grid = gpd.GeoDataFrame({'iy': np.repeat(np.arange(len(lat)), len(lon)), 'ix': np.tile(np.arange(len(lon)), len(lat))},
                            geometry=gpd.points_from_xy(np.tile(lon, len(lat)), np.repeat(lat, len(lon))), crs=4326)
    units = gpd.read_file(study.OUT / 'units.geojson')
    inside = gpd.sjoin(grid, units[['codarea', 'geometry']], predicate='within')
    vals = q.to_numpy()  # time x lat x lon
    cal = (times.year >= CAL[0]) & (times.year <= CAL[1])
    out, cells = {}, {}
    for code, g in inside.groupby('codarea'):
        series = vals[:, g.iy.to_numpy(), g.ix.to_numpy()]  # time x cells
        best = int(np.nanargmax(np.nanmean(series[cal], axis=0)))
        s = pd.Series(series[:, best], index=times)
        ann_max = s[cal].groupby(s[cal].index.year).max()
        out[str(code)] = s / ann_max.median()
        cells[str(code)] = {'lat': float(lat[g.iy.iloc[best]]), 'lon': float(lon[g.ix.iloc[best]]),
                            'median_annual_max_m3s': float(ann_max.median())}
    return pd.DataFrame(out), cells


def evaluate():
    from . import study
    from .second_trigger import fit_rule
    from .stats import BlockBootstrap, auc, holdout_folds, oos_predictions, paired, score, scores, year_folds
    ratio, cells = municipal_ratio()
    windowed = ratio.rolling(2, min_periods=2).max().stack(future_stack=True).rename('GLOFAS').reset_index()
    windowed.columns = ['date', 'codarea', 'GLOFAS']
    df = pd.read_csv(STUDY / 'samples.csv.gz', parse_dates=['date'], dtype={'codarea': str})
    df = df.dropna(subset=study.PREDICTORS).merge(windowed, on=['date', 'codarea'], how='left')
    missing = int(df.GLOFAS.isna().sum())
    df = df.dropna(subset=['GLOFAS']).reset_index(drop=True)
    y = df.label.to_numpy()
    W = BlockBootstrap(df, seed=SEED)
    pos, neg = df.label == 1, df.label == 0
    out = {'rows': int(len(df)), 'rows_without_glofas': missing, 'positives': int(y.sum()), 'cells': cells,
           'AUC_GLOFAS': auc(df.GLOFAS[pos].to_numpy(), df.GLOFAS[neg].to_numpy()),
           'AUC_API': auc(df.API[pos].to_numpy(), df.API[neg].to_numpy()), 'designs': {}}
    for dn, make in {'LOYO': year_folds, 'holdout_2013-2020_vs_2021-2024': holdout_folds}.items():
        folds = make(df)
        m = np.zeros(len(df), bool)
        for _, t in folds:
            m |= t
        sub = W.subset(m)
        glofas, thr = oos_predictions(df, 'GLOFAS', folds)
        rule = np.full(len(df), np.nan)
        for _name, test in folds:
            a, b = fit_rule(df, 'API', ~test)
            rule[test] = ((df.API[test] >= a) | (df.P3[test] >= b)).to_numpy(float)
        out['designs'][dn] = {'GLOFAS': scores(glofas[m], y[m], sub), 'API_rule': scores(rule[m], y[m], sub),
                              'paired_API_rule_minus_GLOFAS': paired(rule[m], glofas[m], y[m], sub),
                              'GLOFAS_thresholds': thr}
        d = out['designs'][dn]
        print(dn, 'GloFAS TSS', round(d['GLOFAS']['TSS'], 3), 'API rule', round(d['API_rule']['TSS'], 3),
              'paired', d['paired_API_rule_minus_GLOFAS'])
    out['final_threshold_all_years'] = float(oos_predictions(df, 'GLOFAS', [('all', np.zeros(len(df), bool))])[1]['all'])
    try:  # 2025 test with frozen thresholds (descriptive secondary)
        from . import validation_2025 as V
        rain, _ = V.rain_through_2025()
        s25, _, _ = V.sample_2025(V.predictor_table(rain))
        s25 = s25.assign(codarea=s25.codarea.astype(str)).merge(windowed, on=['date', 'codarea'], how='left').dropna(subset=['GLOFAS'])
        from .rules import load_rules
        r = load_rules()['API']
        y25 = s25.label.to_numpy()
        out['test_2025'] = {'GLOFAS': score((s25.GLOFAS >= out['final_threshold_all_years']).to_numpy(float), y25),
                            'API_rule': score(((s25.API >= r.attention) | (s25.P3 >= r.trigger_p3_mm)).to_numpy(float), y25),
                            'events': int(y25.sum())}
    except Exception as error:
        out['test_2025'] = {'error': f'{type(error).__name__}: {error}'}
    (STUDY / 'glofas.json').write_text(json.dumps(out, indent=1, default=float), encoding='utf-8')
    return out


if __name__ == '__main__':
    {'download': download, 'evaluate': evaluate}[sys.argv[1]]()
