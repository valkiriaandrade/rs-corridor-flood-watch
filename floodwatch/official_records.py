"""Official flood records (S2iD, via the Atlas Digital de Desastres no Brasil) and preliminary flood reports.

Official: the Atlas Digital publishes the consolidated S2iD database (BD_Atlas_<first>_<last>_v<x>_<date>_Consolidado.csv)
about once a year. `update()` looks at its download page at most once every CHECK_DAYS days; when a newer release
appears it is downloaded (with provenance) and its flood-type records (COBRADE 12100/12200/12300/13214) for the
corridor municipalities are loaded into the forecast archive. A release covers every date up to 31 Dec of <last>.

Preliminary: data/raw/reports/preliminary_reports.csv, filled by hand from Civil Defence bulletins and the press
(date, municipality, type, source, url). Only water-related types count (alagamento, enxurrada, inundação). For dates
covered by an official release, the official records replace the preliminary ones.
    python -m floodwatch.official_records          # check now (ignores the weekly interval) and reload the reports
"""
import json
import re
import unicodedata
from datetime import datetime, timezone

import pandas as pd

from .paths import ATLAS, RAW, STUDY

DOWNLOADS = 'https://atlasdigital.mdr.gov.br/paginas/downloads.xhtml'
BASE = 'https://atlasdigital.mdr.gov.br/'
RELEASE = re.compile(r'arquivos/\d{4}/(BD_Atlas_(\d{4})_(\d{4})_v[\d.]+_(\d{4})\.(\d{2})\.(\d{2})_Consolidado\.csv)')
STATE = ATLAS / 'official_release.json'
REPORTS = RAW / 'reports' / 'preliminary_reports.csv'
FLOOD_TYPES = {'alagamento', 'enxurrada', 'inundacao', 'cheia'}
CHECK_DAYS = 7
UA = {'User-Agent': 'rs-corridor-flood-watch/1.0 (research)'}


def _plain(text):
    """Lower case without accents, for matching municipality names and report types."""
    return unicodedata.normalize('NFKD', str(text)).encode('ascii', 'ignore').decode().strip().lower()


def state():
    return json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {}


def coverage_end():
    """Last date covered by the loaded official release (None if no release was loaded by this module)."""
    end = state().get('coverage_end')
    return pd.Timestamp(end) if end else None


def latest_release():
    """(file name, release date, last covered year) of the newest consolidated CSV listed on the download page."""
    import requests
    html = requests.get(DOWNLOADS, headers=UA, timeout=30).text
    found = [(m.group(0), m.group(1), pd.Timestamp(f'{m.group(4)}-{m.group(5)}-{m.group(6)}'), int(m.group(3)))
             for m in RELEASE.finditer(html)]
    if not found:
        return None
    return max(found, key=lambda x: (x[2], x[3]))


def update(force=False):
    """Weekly check for a new official release; loads it when found. Never raises on network errors."""
    from .fetch import download
    from .forecast_db import load_events
    st = state()
    now = datetime.now(timezone.utc)
    last = pd.Timestamp(st['checked_utc']) if st.get('checked_utc') else None
    if not force and last is not None and (pd.Timestamp(now) - last).days < CHECK_DAYS:
        return st
    try:
        rel = latest_release()
    except Exception as error:
        print('official release check failed:', type(error).__name__)
        return st
    st['checked_utc'] = now.isoformat()
    if rel and rel[1] != st.get('file'):
        path, name, released, last_year = rel
        local = ATLAS / name
        for audit in ATLAS.glob('*.http.json'):  # the same release may already be on disk under another name
            if json.loads(audit.read_text(encoding='utf-8')).get('url', '').endswith(name):
                local = audit.with_name(audit.name[:-len('.http.json')])
        download(BASE + path, local)
        n = load_events(local)
        st.update(file=name, released=str(released.date()), coverage_end=f'{last_year}-12-31', records_loaded=n,
                  loaded_utc=now.isoformat())
        print(f'official release {name}: {n} corridor flood records loaded')
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, indent=1), encoding='utf-8')
    return st


def preliminary_reports():
    """Water-related preliminary reports in the corridor municipalities: date, codarea, nome, tipo, fonte, url."""
    cols = ['date', 'codarea', 'nome', 'tipo', 'fonte', 'url']
    if not REPORTS.exists():
        return pd.DataFrame(columns=cols)
    r = pd.read_csv(REPORTS, dtype=str).fillna('')
    units = pd.read_csv(STUDY / 'units.csv', dtype=str)
    by_name = {_plain(n): (c, n) for c, n in zip(units.codarea, units.nome)}
    r['key'] = r.municipio.map(_plain)
    unknown = sorted(set(r.loc[~r.key.isin(by_name), 'municipio']))
    if unknown:
        print('reports outside the corridor municipalities (ignored):', unknown)
    r = r[r.key.isin(by_name) & r.tipo.map(_plain).isin(FLOOD_TYPES)].copy()
    r['codarea'] = r.key.map(lambda k: by_name[k][0])
    r['nome'] = r.key.map(lambda k: by_name[k][1])
    r['date'] = pd.to_datetime(r.date).dt.strftime('%Y-%m-%d')
    return r[cols]


if __name__ == '__main__':
    print(json.dumps(update(force=True), indent=1))
    print(preliminary_reports().to_string(index=False))
