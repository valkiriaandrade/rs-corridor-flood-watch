"""ANA HidroWeb river levels (stations with a gauge) inside the corridor municipalities: download and daily series.

Selection, daily value and flood rule follow docs/protocol.md §8.2.
    python -m floodwatch.ana download     # inventory + HidroSerieHistorica (cota) per station, polite and sequential
    python -m floodwatch.ana series       # daily level per station -> data/processed/study/ana_levels.csv.gz
"""
import argparse
import json
import time
import xml.etree.ElementTree as ET

import geopandas as gpd
import numpy as np
import pandas as pd

from .fetch import download, session
from .paths import RAW, STUDY

DIR = RAW / 'ana' / 'hidroweb'
WS = 'http://telemetriaws1.ana.gov.br/ServiceANA.asmx/'
INVENTORY = DIR / 'inventario_fluviometricas_RS.xml'
INVENTORY_URL = (WS + 'HidroInventario?codEstDE=&codEstATE=&tpEst=1&nmEst=&nmRio=&codSubBacia=&codBacia=&nmMunicipio='
                 '&nmEstado=RIO%20GRANDE%20DO%20SUL&sgResp=&sgOper=&telemetrica=')
START, END = '01/01/2012', '31/12/2025'
REGULATED = 'UHE|PCH|CGH|BARRAG|RESERVAT|USINA|REPRESA'
MIN_AREA_KM2 = 100


def _rows(path, tag):
    root = ET.parse(path).getroot()
    return pd.DataFrame([{c.tag: c.text for c in t} for t in root.iter(tag)])


def stations():
    """Gauged stations inside a corridor municipality, drainage area >= 100 km2, not regulated (protocol C)."""
    inv = _rows(INVENTORY, 'Table')
    inv = inv[inv.TipoEstacaoEscala == '1'].copy()
    for c in ('Latitude', 'Longitude', 'AreaDrenagem'):
        inv[c] = pd.to_numeric(inv[c], errors='coerce')
    units = gpd.read_file(STUDY / 'units.geojson')[['codarea', 'nome', 'geometry']].to_crs('EPSG:4326')
    pts = gpd.GeoDataFrame(inv, geometry=gpd.points_from_xy(inv.Longitude, inv.Latitude), crs='EPSG:4326')
    st = gpd.sjoin(pts, units, predicate='within').drop(columns=['index_right', 'geometry'])
    regulated = st.Nome.fillna('').str.upper().str.contains(REGULATED, regex=True)
    st = st[~regulated & (st.AreaDrenagem >= MIN_AREA_KM2)]
    # A station that started after 2016 cannot reach 8 years in 2013-2024: not downloaded.
    st = st[pd.to_datetime(st.PeriodoEscalaInicio, errors='coerce') <= '2016-12-31']
    return st[['Codigo', 'Nome', 'RioNome', 'codarea', 'nome', 'AreaDrenagem', 'Latitude', 'Longitude']].reset_index(drop=True)


def fetch_all(pause=1.0):
    s = session()
    download(INVENTORY_URL, INVENTORY, s)
    st = stations()
    out = {}
    for code in st.Codigo:
        url = (WS + f'HidroSerieHistorica?codEstacao={code}&dataInicio={START}&dataFim={END}'
               '&tipoDados=1&nivelConsistencia=')
        path = DIR / f'cota_{code}.xml'
        try:
            existed = path.exists()
            out[code] = download(url, path, s, timeout=(20, 300))['bytes']
            if not existed:
                time.sleep(pause)  # sequential and paced: public service
        except Exception as e:
            out[code] = f'{type(e).__name__}'
    st.to_csv(DIR / 'stations_selected.csv', index=False)
    return out


def daily_levels(path):
    """Daily level (cm): max of the day's readings; consistent (level 2) months replace raw (level 1) months."""
    df = _rows(path, 'SerieHistorica')
    if df.empty:
        return pd.Series(dtype=float)
    df['month'] = pd.to_datetime(df.DataHora).dt.to_period('M')
    df['lvl'] = pd.to_numeric(df.NivelConsistencia)
    df = df[df.lvl == df.groupby('month').lvl.transform('max')]  # prefer consistent data per month
    out = {}
    for month, g in df.groupby('month'):
        readings = g[g.MediaDiaria == '0']
        src = readings if len(readings) else g
        for d in range(1, month.days_in_month + 1):
            col = f'Cota{d:02d}'
            if col not in src:
                continue
            v = pd.to_numeric(src[col], errors='coerce').to_numpy(float)
            v = v[np.isfinite(v)]
            if len(v):
                out[pd.Timestamp(month.year, month.month, d)] = float(v.max())
    return pd.Series(out).sort_index()


def build_series():
    st = pd.read_csv(DIR / 'stations_selected.csv', dtype={'Codigo': str, 'codarea': str})
    series = {}
    for code in st.Codigo:
        path = DIR / f'cota_{code}.xml'
        if path.exists():
            s = daily_levels(path)
            if len(s):
                series[code] = s
    frame = pd.DataFrame(series).reindex(pd.date_range('2012-01-01', '2025-12-31'))
    frame.to_csv(STUDY / 'ana_levels.csv.gz')
    st[st.Codigo.isin(frame.columns)].to_csv(STUDY / 'ana_stations.csv', index=False)
    return frame


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('what', choices=['download', 'series'])
    a = ap.parse_args()
    if a.what == 'download':
        print(json.dumps(fetch_all(), indent=1))
    else:
        f = build_series()
        print(f.shape, f.loc['2013':'2024'].notna().mean().round(2).to_dict())
