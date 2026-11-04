"""MERGE/CPTEC daily GRIB2 reading (one checked reader for the whole project) and the auditable RS cube.

Every reader goes through `read_grid`, which checks variable, date, grid size, origin and scan order, and turns
missing / negative / non-finite values into NaN. Days whose file is missing, unreadable or of the wrong product
are gaps (NaN), never zero rain. Study years (1998-2024) must be the V07B final product.
    python -m floodwatch.merge_cube     # 1998-2024 cube cropped to RS -> data/processed/study/merge_rs_cube.npz
"""
from concurrent.futures import ProcessPoolExecutor
import json
import os
from pathlib import Path

import eccodes
import numpy as np
import pandas as pd

from .paths import MERGE, STUDY as OUT

VERSION = 'MERGE GENERATED FROM GPM-IMERG_V07B-final'
NI, NJ, LAT0, LON0, STEP = 1001, 924, -60.05, -120.05, 0.1   # MERGE regular 0.1-degree grid
LAT = LAT0 + np.arange(NJ) * STEP
LON = LON0 + np.arange(NI) * STEP
LAT_MIN, LAT_MAX, LON_MIN, LON_MAX = -34.0, -26.9, -58.0, -49.4  # RS bounding box with a margin (study cube)
IY = np.where((LAT >= LAT_MIN) & (LAT <= LAT_MAX))[0]
IX = np.where((LON >= LON_MIN) & (LON <= LON_MAX))[0]
# Archive of the 1998-2024 V07B final files (study period); recent files always live in data/raw/merge.
ARCHIVE = Path(os.environ.get('FLOODWATCH_MERGE_ARCHIVE', MERGE))
VALID_STATES = ('final', 'late', 'early')


def files(day, folder):
    stamp = pd.Timestamp(day).strftime('%Y%m%d')
    return stamp, folder / f'MERGE_CPTEC_{stamp}.grib2', folder / f'MERGE_CPTEC_{stamp}.ctl'


def product_title(ctl):
    return next((x for x in ctl.read_text(encoding='utf-8', errors='replace').splitlines()
                 if x.lower().startswith('title')), '')


def product_state(title):
    """'final' | 'late' | 'early' | 'unknown' from the CTL title."""
    return next((s for s in VALID_STATES if s in title.lower()), 'unknown')


def read_grid(grib, stamp):
    """Full MERGE grid (NJ x NI, float64, NaN for missing) or None if the file does not match the expected grid."""
    with grib.open('rb') as f:
        g = eccodes.codes_grib_new_from_file(f)
        try:
            if (eccodes.codes_get(g, 'shortName') != 'rdp' or eccodes.codes_get(g, 'dataDate') != int(stamp)
                    or eccodes.codes_get(g, 'Ni') != NI or eccodes.codes_get(g, 'Nj') != NJ
                    or abs(eccodes.codes_get(g, 'latitudeOfFirstGridPointInDegrees') - LAT0) > 1e-6
                    or abs((eccodes.codes_get(g, 'longitudeOfFirstGridPointInDegrees') + 180) % 360 - 180 - LON0) > 1e-6
                    or eccodes.codes_get(g, 'jScansPositively') != 1 or eccodes.codes_get(g, 'iScansNegatively') != 0):
                return None
            values = eccodes.codes_get_values(g).reshape(NJ, NI).astype('float64')
            missing = eccodes.codes_get(g, 'missingValue')
        finally:
            eccodes.codes_release(g)
    values[(values == missing) | ~np.isfinite(values) | (values < 0)] = np.nan
    return values


def read_day(day):
    """(day, full grid or None, state). Study years (<= 2024) come from the archive and must be V07B final."""
    day = pd.Timestamp(day)
    study_year = day.year <= 2024
    stamp, grib, ctl = files(day, ARCHIVE if study_year else MERGE)
    if not grib.exists() or not ctl.exists():
        return day, None, 'missing'
    title = product_title(ctl)
    if study_year and VERSION not in title:
        return day, None, 'not_v07b'
    state = 'final' if study_year else product_state(title)
    try:
        grid = read_grid(grib, stamp)
    except Exception as error:  # unreadable file is a gap, not zero rain
        return day, None, 'unreadable:' + type(error).__name__
    return (day, None, 'grid_mismatch') if grid is None else (day, grid, state)


def area_mean(grid, iy, ix, area, min_cover=0.99):
    """Area-weighted mean over cells; NaN unless valid cells cover >= min_cover of the area."""
    v = grid[iy, ix]
    ok = np.isfinite(v)
    return float((v[ok] * area[ok]).sum() / area[ok].sum()) if area[ok].sum() >= min_cover * area.sum() else np.nan


def read_crop(day):
    """(day, RS crop of the grid or None, state), the cube layout used by the study."""
    d, grid, state = read_day(day)
    return d, (None if grid is None else grid[np.ix_(IY, IX)].astype('float32')), state


def build(workers=6):
    days = pd.date_range('1998-01-01', '2024-12-31', freq='D')
    cube = np.full((len(days), len(IY), len(IX)), np.nan, dtype='float32')
    status = {}
    with ProcessPoolExecutor(workers) as pool:
        for n, (day, crop, state) in enumerate(pool.map(read_crop, days, chunksize=64)):
            status[str(day.date())] = state
            if crop is not None:
                cube[days.get_loc(day)] = crop
            if n % 1000 == 0:
                print(n, day.date(), state, flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(OUT / 'merge_rs_cube.npz', rain=cube, lat=LAT[IY], lon=LON[IX],
                        dates=days.strftime('%Y-%m-%d').to_numpy())
    meta = {'source': 'MERGE/CPTEC daily, GPM-IMERG V07B final, archived GRIB2 files',
            'bbox': [LAT_MIN, LAT_MAX, LON_MIN, LON_MAX], 'shape': list(cube.shape),
            'first_day': str(days[0].date()), 'last_day': str(days[-1].date()),
            'status_counts': pd.Series(status).value_counts().to_dict(),
            'missing_days': [d for d, s in status.items() if s != 'final'],
            'rule': 'non-final days stored as NaN; no zero filling or interpolation'}
    (OUT / 'merge_rs_cube.metadata.json').write_text(json.dumps(meta, indent=1), encoding='utf-8')
    print(json.dumps(meta['status_counts']), flush=True)


# ---------------------------------------------------------------- area means over many days
_W = {}


def _init(weights):
    _W.clear()
    for code, w in weights.groupby('codarea'):
        _W[code] = (w.iy.to_numpy(), w.ix.to_numpy(), w.area.to_numpy())


def _day_means(day):
    d, grid, state = read_day(day)
    if grid is None:
        return d, None, state
    return d, {code: area_mean(grid, *w) for code, w in _W.items()}, state


def area_series(weights, start, end=None, workers=6, verbose=False):
    """Daily area-weighted rainfall (date x codarea) for full-grid cell weights (codarea, iy, ix, area), plus the
    MERGE product state of each day. The frame ends on the last day with a valid product."""
    end = end or pd.Timestamp.now(tz='UTC').tz_localize(None).normalize()
    days = pd.date_range(start, end)
    rows, states = {}, {}
    with ProcessPoolExecutor(workers, initializer=_init, initargs=(weights,)) as pool:
        for n, (day, vals, state) in enumerate(pool.map(_day_means, days, chunksize=32)):
            states[str(day.date())] = state
            if vals is not None:
                rows[day] = vals
            if verbose and n % 2000 == 0:
                print(n, day.date(), state, flush=True)
    frame = pd.DataFrame.from_dict(rows, orient='index').reindex(days)
    frame = frame[sorted(frame.columns)]
    valid = [pd.Timestamp(d) for d, s in states.items() if s in VALID_STATES]
    return frame.loc[:max(valid)], states


def municipal_weights():
    """Municipal cell weights of the study (stored relative to the RS cube) with full-grid indices."""
    w = pd.read_csv(OUT / 'cell_weights.csv', dtype={'codarea': str})
    return w.assign(iy=IY[w.iy.to_numpy()], ix=IX[w.ix.to_numpy()])


if __name__ == '__main__':
    build()
