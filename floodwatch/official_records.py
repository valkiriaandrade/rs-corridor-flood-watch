"""Official flood records (S2iD) and preliminary flood reports, for the prospective verification.

Recent S2iD records: `update_s2id()` exports, once a day, the public report "Relatório Gerencial - Danos informados"
(RS, COBRADE 12100/12200/12300/13214, last 60 days of registrations) with a headless browser, since the report is a
JSF form without a data endpoint. The event date and the IBGE code come from the protocol (UF-F-<IBGE>-<COBRADE>-<date>).

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


S2ID_REPORTS = 'https://s2id.mi.gov.br/paginas/relatorios/'
S2ID_DIR = RAW / 's2id'
S2ID_LABELS = ('12100', '12200', '12300', '13214')   # same flood types as the study (COBRADE label prefixes)
S2ID_DAYS = 60                                       # registration window re-read every day (the report allows 365)
PROTOCOL = re.compile(r'^[A-Z]{2}-[A-Z]-(\d{7})-(\d{5})-(\d{8})$')   # UF-F-<IBGE>-<COBRADE>-<event date>


def fetch_s2id(days=S2ID_DAYS):
    """Exports S2iD 'Relatório Gerencial - Danos informados' (RS, flood COBRADEs, last `days` of registrations) with a
    headless browser: the report is a JSF form with no data endpoint. One export per call; saved with provenance."""
    import hashlib
    from playwright.sync_api import sync_playwright
    end = pd.Timestamp.now(tz='America/Sao_Paulo').tz_localize(None).normalize()
    start = end - pd.Timedelta(days=days)
    s, e = start.strftime('%d/%m/%Y'), end.strftime('%d/%m/%Y')
    S2ID_DIR.mkdir(parents=True, exist_ok=True)
    path = S2ID_DIR / 'danos_informados_RS.csv'
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge')
        ctx = browser.new_context(accept_downloads=True, user_agent=UA['User-Agent'])
        pg = ctx.new_page()
        pg.goto(S2ID_REPORTS, wait_until='networkidle', timeout=120000)
        pg.get_by_text('Relatório Gerencial - Danos informados').click()
        pg.wait_for_timeout(1500)
        boxes = pg.evaluate("""() => [...document.querySelectorAll("input[name='abas:sanfonas:cobrades3']")].map(i => {
            const l = document.querySelector(`label[for='${i.id}']`); return [i.id, l ? l.textContent.trim() : ''];})""")
        picked = [cid for cid, label in boxes if label.startswith(S2ID_LABELS)]
        if len(picked) != len(S2ID_LABELS):
            raise RuntimeError(f'S2iD form changed: found {len(picked)} of {len(S2ID_LABELS)} flood types')
        for cid in picked:
            pg.locator(f"[id='{cid}']").check(force=True)
            pg.wait_for_timeout(500)
        uf = pg.locator("input[name='abas:sanfonas:estadosDanosInformados'][value='RS']")
        uf.check(force=True)
        pg.wait_for_timeout(500)
        for widget, field, value in (('widget_abas_sanfonas_j_idt74', 'abas:sanfonas:j_idt74_input', s),
                                     ('widget_abas_sanfonas_dt_final_danos', 'abas:sanfonas:dt_final_danos_input', e)):
            pg.evaluate(f"() => PF('{widget}').setDate($.datepicker.parseDate('dd/mm/yy', '{value}'))")
            pg.locator(f"[id='{field}']").evaluate(f"(el) => {{ el.value = '{value}'; }}")
        pg.wait_for_timeout(800)
        with pg.expect_download(timeout=180000) as dl:
            pg.get_by_role('button', name='Exportar CSV').click()
        dl.value.save_as(str(path))
        browser.close()
    raw = path.read_bytes()
    meta = {'url': S2ID_REPORTS, 'report': 'Relatório Gerencial - Danos informados', 'uf': 'RS', 'cobrade': list(S2ID_LABELS),
            'registration_period': [str(start.date()), str(end.date())], 'downloaded_at_utc': datetime.now(timezone.utc).isoformat(),
            'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    path.with_name(path.name + '.http.json').write_text(json.dumps(meta, indent=1), encoding='utf-8')
    return path


def read_s2id(path):
    """Records of the exported report: protocol, codarea, event date (from the protocol), cobrade, status, registration."""
    import io
    raw = path.read_bytes()
    text = next(raw.decode(enc) for enc in ('utf-8', 'cp1252', 'latin1') if _decodes(raw, enc))
    lines = text.splitlines()
    head = next(i for i, line in enumerate(lines) if line.startswith('UF;'))
    d = pd.read_csv(io.StringIO('\n'.join(lines[head:])), sep=';', dtype=str).fillna('')
    parts = d.Protocolo.str.strip().str.extract(PROTOCOL)
    d = d.assign(codarea=parts[0], cobrade=parts[1], date=pd.to_datetime(parts[2], format='%Y%m%d', errors='coerce'))
    d = d.dropna(subset=['date'])
    return pd.DataFrame({'protocol': d.Protocolo.str.strip(), 'codarea': d.codarea, 'date': d.date.dt.strftime('%Y-%m-%d'),
                         'cobrade': d.cobrade, 'status': d.Status, 'registered': d.Registro})


def _decodes(raw, enc):
    try:
        raw.decode(enc)
        return True
    except UnicodeDecodeError:
        return False


def update_s2id(force=False):
    """Daily: export the recent S2iD records and load the corridor ones into the archive (protocol is the key)."""
    from .forecast_db import connect
    from .study import CODES
    st = state()
    last = pd.Timestamp(st['s2id_checked_utc']) if st.get('s2id_checked_utc') else None
    if not force and last is not None and (pd.Timestamp(datetime.now(timezone.utc)) - last).total_seconds() < 20 * 3600:
        return st
    try:
        path = fetch_s2id()
    except Exception as error:
        print('S2iD export failed:', type(error).__name__, str(error)[:200])
        return st
    rec = read_s2id(path)
    rec = rec[rec.cobrade.astype(int).isin(CODES)]
    con = connect()
    units = {r[0] for r in con.execute('SELECT DISTINCT codarea FROM municipal')}
    rec = rec[rec.codarea.isin(units)]
    con.executemany('INSERT OR REPLACE INTO events (protocol, codarea, date, cobrade) VALUES (?,?,?,?)',
                    rec[['protocol', 'codarea', 'date', 'cobrade']].itertuples(index=False, name=None))
    con.commit()
    con.close()
    st.update(s2id_checked_utc=datetime.now(timezone.utc).isoformat(), s2id_corridor_records=int(len(rec)))
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, indent=1), encoding='utf-8')
    print(f'S2iD: {len(rec)} corridor flood records in the last {S2ID_DAYS} days of registrations')
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
    print(json.dumps(update_s2id(force=True), indent=1))
    print(preliminary_reports().to_string(index=False))
