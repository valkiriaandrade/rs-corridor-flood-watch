"""Download every raw input with provenance (.http.json: url, time, bytes, sha256).

    python -m floodwatch.fetch static                 # Atlas, IBGE, DNIT SNV corridors
    python -m floodwatch.fetch merge 1998-01-01 2024-12-31
    python -m floodwatch.fetch merge-recent            # 2025-01-01 .. today, refreshing 'early' days

Existing files are kept unless their provenance is missing; MERGE days whose product is
'early' are re-downloaded (CPTEC replaces them with 'late' and later 'final' versions).
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .paths import ATLAS, MERGE, SPATIAL

MERGE_BASE = 'https://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM/DAILY/'
STATIC = [
    (ATLAS / 'BD_Atlas_1991_2025_v1.1.csv',
     'https://atlasdigital.mdr.gov.br/arquivos/2026/BD_Atlas_1991_2025_v1.1_2026.08.06_Consolidado.csv'),
    (ATLAS / 'Atlas_Manual.pdf', 'https://atlasdigital.mdr.gov.br/arquivos/Atlas_Digital_Desastres_Manual_Aplicacao.pdf'),
    (SPATIAL / 'ibge_rs_municipios.geojson',
     'https://servicodados.ibge.gov.br/api/v3/malhas/estados/43?intrarregiao=municipio'
     '&formato=application/vnd.geo%2Bjson&qualidade=intermediaria'),
    (SPATIAL / 'ibge_rs_municipios_nomes.json', 'https://servicodados.ibge.gov.br/api/v1/localidades/estados/43/municipios'),
    (SPATIAL / 'snv202404_corridors_rs.geojson',
     'https://servicos.dnit.gov.br/dnitgeo/geoserver/ows?service=WFS&version=2.0.0&request=GetFeature'
     '&typeNames=vgeo%3Avw_snv_rod&outputFormat=application%2Fjson&srsName=EPSG%3A4326&count=2000'
     '&CQL_FILTER=Unidade_Federacao%3D%27RS%27+AND+Versao_SNV%3D%27202404A%27+AND+Codigo_BR+IN+%28%27116%27%2C%27386%27%2C%27290%27%29'),
]


def session():
    s = requests.Session()
    s.mount('https://', HTTPAdapter(max_retries=Retry(total=3, backoff_factor=.5, status_forcelist=[429, 500, 502, 503, 504])))
    return s


def download(url, path, s=None, force=False, timeout=(15, 120)):
    audit = path.with_name(path.name + '.http.json')
    if path.exists() and audit.exists() and not force:
        return json.loads(audit.read_text(encoding='utf-8'))
    r = (s or session()).get(url, timeout=timeout)
    r.raise_for_status()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.part')
    tmp.write_bytes(r.content)
    tmp.replace(path)
    meta = {'url': url, 'downloaded_at_utc': datetime.now(timezone.utc).isoformat(), 'bytes': len(r.content),
            'sha256': hashlib.sha256(r.content).hexdigest(), 'last_modified': r.headers.get('Last-Modified')}
    audit.write_text(json.dumps(meta, indent=1), encoding='utf-8')
    return meta


def merge_state(day):
    ctl = MERGE / f'MERGE_CPTEC_{pd.Timestamp(day):%Y%m%d}.ctl'
    if not ctl.exists():
        return None
    title = next((x for x in ctl.read_text(encoding='utf-8', errors='replace').splitlines() if x.lower().startswith('title')), '')
    return next((k for k in ('final', 'late', 'early') if k in title.lower()), 'unknown')


def merge(start, end, refresh=('early',), workers=6):
    s = session()

    def one(day):
        name = f'MERGE_CPTEC_{day:%Y%m%d}'
        url = MERGE_BASE + f'{day:%Y/%m/}' + name
        force = merge_state(day) in refresh
        try:
            download(url + '.ctl', MERGE / (name + '.ctl'), s, force=force)
            download(url + '.grib2', MERGE / (name + '.grib2'), s, force=force)
            return merge_state(day)
        except requests.HTTPError as error:
            return f'http_{error.response.status_code}'
        except requests.RequestException as error:
            return 'error:' + type(error).__name__

    days = pd.date_range(start, end)
    with ThreadPoolExecutor(workers) as pool:
        states = list(pool.map(one, days))
    return pd.Series(states, index=days).value_counts().to_dict()


def static():
    s = session()
    return {str(p.name): download(u, p, s)['sha256'][:12] for p, u in STATIC}


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('what', choices=['static', 'merge', 'merge-recent'])
    ap.add_argument('start', nargs='?')
    ap.add_argument('end', nargs='?')
    a = ap.parse_args()
    if a.what == 'static':
        print(static())
    elif a.what == 'merge':
        print(merge(a.start, a.end))
    else:
        print(merge('2025-01-01', pd.Timestamp.now(tz='UTC').tz_localize(None).normalize()))
