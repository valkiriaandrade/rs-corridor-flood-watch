"""Independent ground truth for the frozen rules (docs/protocol.md §9.9; descriptive, nothing is fitted).

PRF accident records (datatran, data/raw/prf/, provenance.json) on BR-116, BR-386 and BR-290 in RS whose cause is water
on the road. Categories fixed from the category list only (decision log 2026-11-24): primary "Acumulo de água sobre o
pavimento", sensitivity + "Chuva"; both exist only from 2021, so the test covers 2021-2025. Unit: municipality-day
(the record's municipality, corridor municipalities only). Levels: frozen dashboard rules on observed basin rainfall
(MERGE), the same table as the 2025 test. Also the first test of the corridor display rule (20 %).
Water on the road also follows ordinary heavy rain: this measures road impact, not flooding.
    python -m floodwatch.ground_truth            -> data/processed/study/ground_truth.json
    python -m floodwatch.ground_truth download   # PRF files from provenance.json (sha256 checked)
"""

import io
import json
import zipfile

import numpy as np
import pandas as pd

from . import rules
from .forecast_db import CORRIDOR_SHARE
from .official_records import _plain
from .paths import RAW, STUDY

PRF = RAW / 'prf'
YEARS = range(2021, 2026)
CAUSES = {
    'primary': ['Acumulo de água sobre o pavimento'],
    'sensitivity': ['Acumulo de água sobre o pavimento', 'Chuva'],
}
BRS = (116, 386, 290)
N_BOOT, SEED = 2000, 20261124


def download():
    """Re-download the PRF files listed in provenance.json (Google Drive links of the PRF open-data page) and check
    their sha256 (a changed file is reported, not silently used)."""
    import hashlib

    import requests

    prov = json.loads((PRF / 'provenance.json').read_text(encoding='utf-8'))
    for year, p in prov.items():
        path = PRF / f'datatran{year}.zip'
        if not path.exists():
            r = requests.get(
                'https://drive.usercontent.google.com/download',
                params={'id': p['drive_id'], 'export': 'download', 'confirm': 't'},
                timeout=600,
            )
            r.raise_for_status()
            path.write_bytes(r.content)
        if hashlib.sha256(path.read_bytes()).hexdigest() != p['sha256']:
            print(f'PRF {year}: file differs from the one analysed (sha256)')


def prf_records():
    units = pd.read_csv(STUDY / 'units.csv', dtype={'codarea': str})
    by_name = {_plain(n): c for c, n in zip(units.codarea, units.nome)}
    out = []
    for year in YEARS:
        with zipfile.ZipFile(PRF / f'datatran{year}.zip') as z:
            name = z.namelist()[0]
            d = pd.read_csv(io.BytesIO(z.read(name)), sep=';', encoding='latin1', dtype=str)
        d['br'] = pd.to_numeric(d.br, errors='coerce')
        d = d[(d.uf == 'RS') & d.br.isin(BRS)].copy()
        d['cause'] = d.causa_acidente.str.strip()
        d['date'] = pd.to_datetime(d.data_inversa)
        d['codarea'] = d.municipio.map(lambda n: by_name.get(_plain(n)))
        out.append(d[['id', 'date', 'br', 'km', 'municipio', 'codarea', 'cause']])
    return pd.concat(out, ignore_index=True)


def level_table():
    """Frozen-rule levels on observed basin rainfall for every corridor municipality-day 2021-2025."""
    from . import validation_2025 as V

    rain, _ = V.rain_through_2025()
    t = V.predictor_table(rain)
    t = t[(t.date >= '2021-01-01') & (t.date <= '2025-12-31')].copy()
    rule = rules.load_rules()
    t['level_EDI'] = rules.classify(t.EDI, t.P3, rule['EDI'])
    t['level_API'] = rules.classify(t.API, t.P3, rule['API'])
    t['codarea'] = t.codarea.astype(str)
    return t[['date', 'codarea', 'level_EDI', 'level_API']]


def _boot_share(hit, groups, rng):
    """Share of hits with a 95 % CI, resampling whole days (records of one storm day are not independent)."""
    g = pd.Series(hit).groupby(np.asarray(groups))
    s, n = g.sum().to_numpy(), g.size().to_numpy()
    reps = []
    for _ in range(N_BOOT):
        i = rng.integers(0, len(s), len(s))
        reps.append(s[i].sum() / n[i].sum())
    return [float(np.quantile(reps, 0.025)), float(np.quantile(reps, 0.975))]


def municipal_scores(levels, days, rng):
    m = levels.merge(days.assign(acc=1), on=['date', 'codarea'], how='left').fillna({'acc': 0})
    out = {'accident_municipality_days': int(m.acc.sum()), 'all_municipality_days': int(len(m))}
    for ix in ('EDI', 'API'):
        lv = m[f'level_{ix}']
        ok = lv >= 0
        acc, watch, warn = m.acc[ok] == 1, lv[ok] >= 1, lv[ok] == 2
        base = acc.mean()
        out[ix] = {
            'n_with_level': int(acc.sum()),
            'share_at_watch_or_above': float(watch[acc].mean()),
            'share_at_watch_CI95': _boot_share(watch[acc].to_numpy(), m.date[ok][acc].to_numpy(), rng),
            'share_at_warning': float(warn[acc].mean()),
            'share_of_all_days_at_watch_or_above': float(watch.mean()),
            'rate_ratio_watch': float(acc[watch].mean() / base) if watch.any() else None,
            'rate_ratio_warning': float(acc[warn].mean() / base) if warn.any() else None,
        }
    return out


def corridor_scores(levels, rec):
    """Corridor display rule (highest level present in >= 20 % of the corridor's municipalities) vs corridor-days with
    >= 1 accident on that highway in RS."""
    units = pd.read_csv(STUDY / 'units.csv', dtype={'codarea': str})
    out = {}
    for ix in ('EDI', 'API'):
        rows = []
        for br in BRS:
            codes = units.codarea[units.corridors.astype(str).str.split('/').apply(lambda x: str(br) in x)]
            sub = levels[levels.codarea.isin(codes)]
            lv = sub.groupby('date')[f'level_{ix}'].apply(lambda v: _corridor_level(v.to_numpy()))
            acc_days = set(rec.loc[rec.br == br, 'date'])
            rows.append(pd.DataFrame({'br': br, 'level': lv.to_numpy(), 'acc': lv.index.isin(acc_days)}))
        c = pd.concat(rows)
        c = c[c.level >= 0]
        pod, pofd = float((c.level[c.acc] >= 1).mean()), float((c.level[~c.acc] >= 1).mean())
        out[ix] = {
            'corridor_days': int(len(c)),
            'accident_corridor_days': int(c.acc.sum()),
            'POD_watch': pod,
            'POFD_watch': pofd,
            'TSS_watch': pod - pofd,
            'POD_warning': float((c.level[c.acc] == 2).mean()),
            'POFD_warning': float((c.level[~c.acc] == 2).mean()),
        }
    return out


def _corridor_level(v):
    v = v[v >= 0]
    if not len(v):
        return -1
    return 2 if (v == 2).mean() >= CORRIDOR_SHARE else (1 if (v >= 1).mean() >= CORRIDOR_SHARE else 0)


def ems_overlap():
    """Copernicus EMS rapid mapping EMSR720 (April-May 2024): corridor municipalities intersecting a mapped AOI.
    data/raw/copernicus_ems/EMSR720_activation.json = the public activation record (rapidmapping.emergency.copernicus.eu)."""
    import geopandas as gpd
    from shapely import wkt

    from . import study

    act = json.loads((RAW / 'copernicus_ems' / 'EMSR720_activation.json').read_text(encoding='utf-8'))['results'][0]
    aoi = gpd.GeoDataFrame([{'aoi': a['name'], 'geometry': wkt.loads(a['extent'])} for a in act['aois']], crs=4326)
    units = gpd.read_file(study.OUT / 'units.geojson')
    hit = gpd.sjoin(units[['codarea', 'nome', 'geometry']], aoi, predicate='intersects')
    return {
        'activation': act['code'],
        'aois': aoi.aoi.tolist(),
        'corridor_municipalities_intersecting': hit[['codarea', 'nome', 'aoi']].astype(str).to_dict('records'),
        'note': 'No AOI intersects a corridor municipality: the test is not informative.' if hit.empty else '',
    }


def run():
    rec_all = prf_records()
    levels = level_table()
    out = {'source': 'PRF datatran 2021-2025, BR-116/386/290 in RS', 'years': list(YEARS), 'sets': {}}
    for name, causes in CAUSES.items():
        rec = rec_all[rec_all.cause.isin(causes)]
        inside = rec[rec.codarea.notna()]
        days = inside[['date', 'codarea']].drop_duplicates()
        rng = np.random.default_rng(SEED)
        res = {
            'causes': causes,
            'records': int(len(rec)),
            'records_in_corridor_municipalities': int(len(inside)),
            'records_by_year': {str(k): int(v) for k, v in rec.date.dt.year.value_counts().sort_index().items()},
            'municipal': municipal_scores(levels, days, rng),
            'corridor_rule': corridor_scores(levels, rec),
        }
        out['sets'][name] = res
        for ix in ('EDI', 'API'):
            m = res['municipal'][ix]
            print(
                name,
                ix,
                'accident days at Watch+',
                round(m['share_at_watch_or_above'], 3),
                m['share_at_watch_CI95'],
                'all days at Watch+',
                round(m['share_of_all_days_at_watch_or_above'], 3),
                'rate ratio',
                m['rate_ratio_watch'],
                '| corridor TSS',
                round(res['corridor_rule'][ix]['TSS_watch'], 3),
            )
    out['copernicus_ems'] = ems_overlap()
    out['cemaden'] = 'no open occurrence data found; to be requested through the access-to-information law'
    (STUDY / 'ground_truth.json').write_text(json.dumps(out, indent=1, default=float), encoding='utf-8')
    return out


if __name__ == '__main__':
    import sys

    download() if sys.argv[1:] == ['download'] else run()
