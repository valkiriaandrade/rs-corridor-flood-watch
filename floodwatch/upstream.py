"""Upstream-basin rainfall per corridor municipality (ANA Ottobacias, BHO 2017 5k, level 6) - docs/protocol.md §3.

For each municipality: level-6 ottobacias with >= 5 km2 inside it (seeds) plus every ottobacia upstream of a seed
(Pfafstetter rule). Daily MERGE rainfall is the area-weighted mean over that union (day valid with >= 99% of the area
covered by valid cells), 1998 onward, from the archived GRIB2 files (full MERGE grid, so headwaters outside RS count).
    python -m floodwatch.upstream basins      # seeds, upstream sets, cell weights, summary, simplified geometry
    python -m floodwatch.upstream rain        # daily upstream rainfall -> data/processed/study/upstream_rain.csv.gz
Archive of 1998-2024 GRIB2 files: env FLOODWATCH_MERGE_ARCHIVE (default data/raw/merge), see floodwatch.merge_cube.
"""
import argparse
import json

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
from shapely.geometry import box

from .merge_cube import LAT, LON, area_series
from .paths import RAW, STUDY

BHO = RAW / 'ana' / 'bho' / 'geoft_bho_ach_otto_nivel_06.gpkg'
CODE = 'wts_cd_pfafstetterbasin'
MIN_SEED_KM2 = 5.0


def upstream_mask(digits, a):
    """Rows of `digits` (N x L, padded with -1) that are `a` itself or upstream of `a`, ANA/Pfafstetter rule:
    cobacia(b) >= cobacia(a) and cobacia(b) starts with cocursodag(a), the watercourse code = a's code up to its last
    even digit. A code without an even digit lies on the coast (coastal/lagoon interbasin): the coastline is not a
    river, so nothing is upstream of it but itself."""
    diff = digits != a
    has = diff.any(axis=1)
    first = diff.argmax(axis=1)
    real = a >= 0
    even = np.where(real & (a % 2 == 0))[0]
    if len(even) == 0:
        return ~has
    last_even = even.max()
    larger = digits[np.arange(len(digits)), first] > a[first]
    return ~has | (larger & (first > last_even))


def basins():
    units = gpd.read_file(STUDY / 'units.geojson')
    units['codarea'] = units.codarea.astype(str)
    attrs = pyogrio.read_dataframe(BHO, columns=[CODE, 'wts_gm_area'], read_geometry=False)
    codes = attrs[CODE].astype(str).to_numpy()
    # Basins that are not subdivided down to level 6 keep shorter codes. Codes of one level never nest, so the first
    # differing digit always falls inside both codes; padding (-1) is never compared.
    if len(set(codes)) != len(codes):
        raise ValueError('Código Pfafstetter repetido')
    width = max(len(c) for c in codes)
    digits = np.full((len(codes), width), -1, dtype=np.int8)
    for i, c in enumerate(codes):
        digits[i, :len(c)] = [int(ch) for ch in c]
    x0, y0, x1, y1 = units.to_crs('EPSG:4674').total_bounds
    local = pyogrio.read_dataframe(BHO, columns=[CODE], bbox=(x0 - .1, y0 - .1, x1 + .1, y1 + .1))
    local[CODE] = local[CODE].astype(str)
    inter = gpd.overlay(local.to_crs('EPSG:5880'), units[['codarea', 'geometry']].to_crs('EPSG:5880'),
                        how='intersection', keep_geom_type=True)
    inter['km2'] = inter.area / 1e6
    seeds = inter[inter.km2 >= MIN_SEED_KM2].groupby('codarea')[CODE].apply(lambda s: sorted(set(s)))
    index = {c: i for i, c in enumerate(codes)}
    sets = {}
    for codarea, seed in seeds.items():
        mask = np.zeros(len(codes), bool)
        for c in seed:
            mask |= upstream_mask(digits, digits[index[c]])
        sets[codarea] = set(codes[mask])
    needed = sorted(set().union(*sets.values()))
    geo = []
    for i in range(0, len(needed), 900):  # read only the needed basins
        chunk = ','.join(f"'{c}'" for c in needed[i:i + 900])
        geo.append(pyogrio.read_dataframe(BHO, columns=[CODE], where=f'{CODE} IN ({chunk})'))
    geo = pd.concat(geo, ignore_index=True)
    geo[CODE] = geo[CODE].astype(str)
    geo = gpd.GeoDataFrame(geo, geometry='geometry', crs='EPSG:4674').to_crs('EPSG:4326')
    # Basin x MERGE cell overlap (equal-area), full-grid indices.
    bx0, by0, bx1, by1 = geo.total_bounds
    iy = np.where((LAT >= by0 - .1) & (LAT <= by1 + .1))[0]
    ix = np.where((LON >= bx0 - .1) & (LON <= bx1 + .1))[0]
    cells = gpd.GeoDataFrame([{'iy': i, 'ix': j, 'geometry': box(LON[j] - .05, LAT[i] - .05, LON[j] + .05, LAT[i] + .05)}
                              for i in iy for j in ix], crs='EPSG:4326')
    pieces = gpd.overlay(geo, cells, how='intersection', keep_geom_type=True)
    pieces['area'] = pieces.to_crs('EPSG:5880').area
    pieces = pieces[[CODE, 'iy', 'ix', 'area']]
    rows, summary, shapes = [], [], []
    area_by_code = geo.set_index(CODE).to_crs('EPSG:5880').area / 1e6
    for codarea, s in sets.items():
        w = pieces[pieces[CODE].isin(s)].groupby(['iy', 'ix']).area.sum().reset_index()
        w['codarea'] = codarea
        rows.append(w)
        u = units.loc[units.codarea == codarea].iloc[0]
        summary.append({'codarea': codarea, 'nome': u.nome, 'corridors': u.corridors, 'seed_basins': len(seeds[codarea]),
                        'upstream_basins': len(s), 'upstream_km2': float(area_by_code[list(s)].sum()),
                        'municipality_km2': float(units.loc[units.codarea == codarea].to_crs('EPSG:5880').area.iloc[0] / 1e6)})
        shapes.append({'codarea': codarea, 'geometry': geo[geo[CODE].isin(s)].union_all().simplify(0.01)})
    weights = pd.concat(rows, ignore_index=True)[['codarea', 'iy', 'ix', 'area']]
    weights.to_csv(STUDY / 'upstream_weights.csv', index=False)
    summary = pd.DataFrame(summary)
    summary['ratio'] = summary.upstream_km2 / summary.municipality_km2
    summary.to_csv(STUDY / 'upstream_units.csv', index=False)
    gpd.GeoDataFrame(shapes, crs='EPSG:4326').to_file(STUDY / 'upstream_basins.geojson', driver='GeoJSON')
    meta = {'source': 'ANA BHO 2017 5k, Ottobacias nível 6 (geoft_bho_ach_otto_nivel_06.gpkg)', 'units': len(sets),
            'min_seed_km2': MIN_SEED_KM2, 'basins_used': len(needed), 'bounds': [float(v) for v in geo.total_bounds],
            'grid_rows': [int(iy.min()), int(iy.max())], 'grid_cols': [int(ix.min()), int(ix.max())]}
    (STUDY / 'upstream.metadata.json').write_text(json.dumps(meta, indent=1), encoding='utf-8')
    print(json.dumps(meta, indent=1))
    print(summary.sort_values('upstream_km2').to_string())


# ------------------------------------------------------------------ rainfall
def weights():
    return pd.read_csv(STUDY / 'upstream_weights.csv', dtype={'codarea': str})


def compute_rain(start='1998-01-01', end=None, workers=6, verbose=False):
    """Daily upstream-basin rainfall (date x codarea) and the MERGE product state of each day, up to the last valid day."""
    return area_series(weights(), start, end, workers, verbose)


def forecast_grid(step=0.25):
    """Forecast points on a regular grid covering every upstream MERGE cell, and per-municipality area weights.

    Each 0.1-degree MERGE cell is assigned to the nearest grid point; returns (points: point, lat, lon) and
    (weights: codarea, point, area)."""
    w = weights()
    w['lat'] = np.round(LAT[w.iy] / step) * step
    w['lon'] = np.round(LON[w.ix] / step) * step
    pts = w[['lat', 'lon']].drop_duplicates().sort_values(['lat', 'lon']).reset_index(drop=True)
    pts['point'] = [f'p{i}' for i in range(len(pts))]
    w = w.merge(pts, on=['lat', 'lon'])
    return pts[['point', 'lat', 'lon']], w.groupby(['codarea', 'point'], as_index=False).area.sum()


def rain(start='1998-01-01', end=None, workers=6):
    frame, states = compute_rain(start, end, workers, verbose=True)
    last_ok = frame.index.max()
    frame.to_csv(STUDY / 'upstream_rain.csv.gz')
    counts = pd.Series(states).loc[:str(last_ok.date())].value_counts().to_dict()
    meta = json.loads((STUDY / 'upstream.metadata.json').read_text(encoding='utf-8'))
    meta['rain'] = {'first_day': str(frame.index.min().date()), 'last_day': str(last_ok.date()), 'status_counts': counts,
                    'not_final_days_to_2024': [d for d, s in states.items() if s != 'final' and d <= '2024-12-31'],
                    'rule': 'area-weighted mean; day valid only with >= 99% of the upstream area in valid cells'}
    (STUDY / 'upstream.metadata.json').write_text(json.dumps(meta, indent=1), encoding='utf-8')
    print(json.dumps(meta['rain'], indent=1)[:2000])


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('what', choices=['basins', 'rain'])
    a = ap.parse_args()
    basins() if a.what == 'basins' else rain()
