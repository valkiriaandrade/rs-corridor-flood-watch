"""SQLite archive of every forecast run, so the forecasts can be verified later.

Each run of `python -m floodwatch.forecast` is ingested automatically (runs, municipal and corridor tables).
Every run also carries the last observed days (source = 'observado'), so a forecast made for day D is verified
by the observed rows of later runs. Official flood records (S2iD/Atlas) can be loaded when a new Atlas release
covers the period: `python -m floodwatch.forecast_db events <atlas.csv>`.

    python -m floodwatch.forecast_db ingest-all          # (re)load every run folder
    python -m floodwatch.forecast_db events PATH.csv     # load official records for verification
    python -m floodwatch.forecast_db report              # runs sql/validation.sql
    python -m floodwatch.forecast_db summary             # forecast vs observed -> verification.json (shown in the app)
    sqlite3 data/processed/forecast/forecasts.sqlite < sql/validation.sql   # same, with the sqlite3 CLI
"""
import argparse
import json
import sqlite3

import pandas as pd

from .rules import run_rules
from .paths import FORECAST, ROOT

DB = FORECAST / 'forecasts.sqlite'
SCHEMA = ROOT / 'sql' / 'schema.sql'
CORRIDORS = ['116', '386', '290']
CORRIDOR_SHARE = 0.20  # same display rule as the forecast page


MIGRATIONS = {'runs': ['thr_api_attention REAL', 'thr_api_alert REAL', 'trigger_p3_edi REAL', 'trigger_p3_api REAL'],
              'municipal': ['API REAL', 'level_api INTEGER', 'rain_mm REAL'],
              'corridor': ['level_api INTEGER', 'n_att_api INTEGER', 'n_alert_api INTEGER']}


def connect(path=DB):
    con = sqlite3.connect(path)
    for table, columns in MIGRATIONS.items():  # databases created before the API columns existed
        have = {r[1] for r in con.execute(f'PRAGMA table_info({table})')}
        for col in columns:
            if have and col.split()[0] not in have:
                con.execute(f'ALTER TABLE {table} ADD COLUMN {col}')
    con.executescript(SCHEMA.read_text(encoding='utf-8'))
    return con


def corridor_level(levels):
    valid = levels[levels >= 0]
    if valid.empty:
        return -1
    return 2 if (valid == 2).mean() >= CORRIDOR_SHARE else (1 if (valid >= 1).mean() >= CORRIDOR_SHARE else 0)


def corridor_rows(df):
    rows = []
    has_api = 'level_api' in df
    for (date, model), g in df.groupby(['date', 'model']):
        for br in CORRIDORS:
            sub = g[g.corridors.astype(str).str.split('/').apply(lambda x: br in x)]
            row = {'date': date, 'model': model, 'br': 'BR-' + br, 'level': corridor_level(sub.level),
                   'n_att': int((sub.level >= 1).sum()), 'n_alert': int((sub.level == 2).sum()), 'n': int(len(sub)),
                   'source': sub.source.iloc[0] if len(sub) else None, 'level_api': None, 'n_att_api': None, 'n_alert_api': None}
            if has_api:
                row.update(level_api=corridor_level(sub.level_api), n_att_api=int((sub.level_api >= 1).sum()),
                           n_alert_api=int((sub.level_api == 2).sum()))
            rows.append(row)
    return pd.DataFrame(rows)


def ingest(run_dir, con=None):
    own = con is None
    con = con or connect()
    meta = json.loads((run_dir / 'metadata.json').read_text(encoding='utf-8'))
    run_id = run_dir.name
    rules = run_rules(meta)
    con.execute('DELETE FROM municipal WHERE run_id = ?', (run_id,))
    con.execute('DELETE FROM corridor WHERE run_id = ?', (run_id,))
    edi, api = rules.get('EDI', {}), rules.get('API', {})
    con.execute('INSERT OR REPLACE INTO runs (run_id, created_utc, ecmwf_run, gfs_run, observed_cutoff, predictor, thr_attention, '
                'thr_alert, antecedent_json, thr_api_attention, thr_api_alert, trigger_p3_edi, trigger_p3_api) '
                'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (run_id, meta['created_utc'], meta['runs'].get('ECMWF'), meta['runs'].get('GFS'), meta['observed_cutoff'],
                 'EDI', edi.get('attention'), edi.get('alert'), json.dumps(meta.get('antecedent_product_last_30d', {})),
                 api.get('attention'), api.get('alert'), edi.get('trigger_p3_mm'), api.get('trigger_p3_mm')))
    df = pd.read_csv(run_dir / 'municipal_levels.csv', dtype={'codarea': str})
    cutoff = pd.Timestamp(meta['observed_cutoff'])
    df['lead_days'] = (pd.to_datetime(df.date) - cutoff).dt.days
    df['run_id'] = run_id
    cols = ['run_id', 'date', 'codarea', 'nome', 'corridors', 'model', 'source', 'lead_days', 'P1', 'P3', 'P7', 'P30', 'PE', 'EDI', 'level']
    cols += [c for c in ('API', 'level_api', 'rain_mm') if c in df]  # older runs lack them
    con.executemany(f'INSERT INTO municipal ({",".join(cols)}) VALUES ({",".join("?" * len(cols))})',
                    df[cols].astype(object).where(df[cols].notna(), None).itertuples(index=False, name=None))
    c = corridor_rows(df)
    c['run_id'] = run_id
    c['lead_days'] = (pd.to_datetime(c.date) - cutoff).dt.days
    ccols = ['run_id', 'date', 'model', 'br', 'source', 'lead_days', 'level', 'n_att', 'n_alert', 'n', 'level_api', 'n_att_api',
             'n_alert_api']
    con.executemany(f'INSERT INTO corridor ({",".join(ccols)}) VALUES ({",".join("?" * len(ccols))})',
                    c[ccols].astype(object).itertuples(index=False, name=None))
    con.commit()
    if own:
        con.close()
    return run_id, len(df)


def ingest_all():
    con = connect()
    n = 0
    for run_dir in sorted((FORECAST / 'runs').iterdir()):
        if (run_dir / 'metadata.json').exists() and (run_dir / 'municipal_levels.csv').exists():
            ingest(run_dir, con)
            n += 1
    con.close()
    return n


def load_events(path):
    """Official flood records (Atlas Digital CSV: ';', latin1) for the corridor municipalities."""
    from .study import CODES
    atlas = pd.read_csv(path, sep=';', encoding='latin1', low_memory=False)
    atlas = atlas[(atlas.Sigla_UF == 'RS') & atlas.Cod_Cobrade.isin(CODES)].copy()
    atlas['date'] = pd.to_datetime(atlas.Data_Evento, dayfirst=True).dt.strftime('%Y-%m-%d')
    atlas['codarea'] = atlas.Cod_IBGE_Mun.astype(str)
    con = connect()
    units = {r[0] for r in con.execute('SELECT DISTINCT codarea FROM municipal')}
    atlas = atlas[atlas.codarea.isin(units)]
    con.executemany('INSERT OR REPLACE INTO events (protocol, codarea, date, cobrade) VALUES (?,?,?,?)',
                    atlas[['Protocolo_S2iD', 'codarea', 'date', 'Cod_Cobrade']].astype(str).itertuples(index=False, name=None))
    con.commit()
    con.close()
    return len(atlas)


SUMMARY = FORECAST / 'verification.json'
LEVEL_COLS = {'EDI': ('fc_level', 'obs_level'), 'API': ('fc_level_api', 'obs_level_api')}


def _contingency(fc, obs):
    """Watch-or-above (level >= 1) forecast vs the same rule on observed rainfall; days without data excluded."""
    ok = (fc >= 0) & (obs >= 0)
    f, o = fc[ok] >= 1, obs[ok] >= 1
    hits, fa, miss = int((f & o).sum()), int((f & ~o).sum()), int((~f & o).sum())
    return {'n': int(ok.sum()), 'hits': hits, 'false_alarms': fa, 'misses': miss, 'correct_negatives': int((~f & ~o).sum()),
            'POD': hits / (hits + miss) if hits + miss else None, 'FAR': fa / (hits + fa) if hits + fa else None}


def _rain(v):
    v = v.dropna(subset=['fc_rain', 'obs_rain'])
    if v.empty:
        return None
    return {'n': int(len(v)), 'fc_mean': float(v.fc_rain.mean()), 'obs_mean': float(v.obs_rain.mean()),
            'bias_ratio': float(v.fc_rain.sum() / v.obs_rain.sum()) if v.obs_rain.sum() > 0 else None,
            'mae': float((v.fc_rain - v.obs_rain).abs().mean()),
            'heavy_observed': int((v.obs_rain >= 20).sum()), 'heavy_hits': int(((v.fc_rain >= 20) & (v.obs_rain >= 20)).sum()),
            'heavy_forecast': int((v.fc_rain >= 20).sum())}


def occurrences(con):
    """Flood occurrences for verification: official S2iD records (events table) where an official release covers the
    date, preliminary reports after that. Columns: date, codarea, source ('S2iD' | 'preliminar'), tipo, fonte, url."""
    from .official_records import coverage_end, preliminary_reports
    end = coverage_end()
    off = pd.read_sql_query('SELECT date, codarea, cobrade FROM events', con)
    off = off.assign(source='S2iD', tipo='COBRADE ' + off.cobrade.astype(str), fonte='S2iD', url='')
    pre = preliminary_reports().assign(source='preliminar')
    if end is not None:
        off = off[pd.to_datetime(off.date) <= end]
        pre = pre[pd.to_datetime(pre.date) > end]
    cols = ['date', 'codarea', 'source', 'tipo', 'fonte', 'url']
    return pd.concat([off[cols], pre[cols]], ignore_index=True).drop_duplicates(['date', 'codarea', 'source'])


def _occurrence_block(v, occ):
    """Each occurrence on a verified day with the level of the latest forecast issued before that day, per model."""
    if occ.empty:
        return {'items': [], 'by_model': {}}
    last = v[v.run_id == v.groupby(['date', 'model']).run_id.transform('max')]
    m = last.merge(occ, on=['date', 'codarea'], how='inner')
    items = [{'date': r.date, 'nome': r.nome, 'model': r.model, 'lead_days': int(r.lead_days), 'source': r.source,
              'tipo': r.tipo, 'fonte': r.fonte, 'url': r.url,
              'EDI': {'forecast': r.fc_level, 'observed': r.obs_level},
              'API': {'forecast': r.fc_level_api, 'observed': r.obs_level_api}} for r in m.itertuples()]
    by_model = {}
    for model, g in m.groupby('model'):
        by_model[model] = {ix: {'n': int(g[fc].notna().sum()), 'at_watch': int((g[fc] >= 1).sum()),
                                'at_warning': int((g[fc] == 2).sum())} for ix, (fc, _) in LEVEL_COLS.items()}
    return {'items': items, 'by_model': by_model}


def summary(con=None):
    """Forecast vs observed, from the archive: accumulated by model and lead, plus the most recent verified day.

    'Observed' is the same rule applied to MERGE rainfall once it is published (not an official flood record)."""
    own = con is None
    con = con or connect()
    v = pd.read_sql_query('SELECT * FROM verification', con)
    runs = pd.read_sql_query('SELECT run_id, ecmwf_run, gfs_run, observed_cutoff FROM runs', con).set_index('run_id')
    occ = occurrences(con)
    if own:
        con.close()
    from .official_records import state
    out = {'verified_days': sorted(v.date.unique().tolist()), 'issuances': int(v.run_id.nunique()), 'by_lead': {}, 'latest': None,
           'official_release': {k: state().get(k) for k in ('file', 'released', 'coverage_end', 'checked_utc')}}
    if v.empty:
        return out
    out['occurrences'] = _occurrence_block(v, occ)
    v['lead'] = v.lead_days.clip(upper=4)  # D+4 and beyond pooled
    for (model, lead), g in v.groupby(['model', 'lead']):
        out['by_lead'].setdefault(model, {})[str(int(lead))] = {
            'days': int(g.date.nunique()), 'rain': _rain(g),
            **{ix: _contingency(g[fc], g[ob]) for ix, (fc, ob) in LEVEL_COLS.items() if g[fc].notna().any()}}
    day = v.date.max()
    first = v[(v.date == day)]
    first = first[first.run_id == first.run_id.max()]  # the latest forecast issued before the day was observed
    rid = first.run_id.iloc[0]
    latest = {'date': day, 'lead_days': int(first.lead_days.min()), 'run_id': rid, 'model_runs': {
        'ECMWF': runs.at[rid, 'ecmwf_run'], 'GFS': runs.at[rid, 'gfs_run']}, 'observed_cutoff': runs.at[rid, 'observed_cutoff'],
        'models': {}}
    for model, g in first.groupby('model'):
        r = {'rain': _rain(g)}
        if r['rain']:
            fmax, omax = g.loc[g.fc_rain.idxmax()], g.loc[g.obs_rain.idxmax()]
            r['rain'].update(fc_max=float(fmax.fc_rain), fc_max_nome=fmax.nome, obs_max=float(omax.obs_rain), obs_max_nome=omax.nome)
        for ix, (fc, ob) in LEVEL_COLS.items():
            if not g[fc].notna().any():
                continue
            c = _contingency(g[fc], g[ob])
            c['missed'] = sorted(g.loc[(g[fc] == 0) & (g[ob] >= 1), 'nome'].tolist())
            c['false_alarm_names'] = sorted(g.loc[(g[fc] >= 1) & (g[ob] == 0), 'nome'].tolist())
            reported = set(occ.loc[occ.date == day, 'codarea'])  # a flood was reported there: not a false alarm in practice
            c['false_alarm_reported'] = sorted(g.loc[(g[fc] >= 1) & (g[ob] == 0) & g.codarea.isin(reported), 'nome'].tolist())
            c['forecast_watch'], c['observed_watch'] = int((g[fc] >= 1).sum()), int((g[ob] >= 1).sum())
            r[ix] = c
        latest['models'][model] = r
    out['latest'] = latest
    return out


def write_summary():
    s = summary()
    SUMMARY.write_text(json.dumps(s, indent=1, ensure_ascii=False, default=float), encoding='utf-8')
    return s


def report():
    """Run sql/validation.sql without the sqlite3 command-line tool."""
    con = connect()
    nl = chr(10)
    text = nl.join(l for l in (ROOT / 'sql' / 'validation.sql').read_text(encoding='utf-8').splitlines() if not l.startswith('.'))
    for block in [b.strip() for b in text.split(';') if b.strip()]:
        title = [l for l in block.splitlines() if l.startswith('--')]
        sql = nl.join(l for l in block.splitlines() if not l.startswith('--'))
        if not sql.strip():
            continue
        print(nl.join(title))
        print(pd.read_sql_query(sql, con).to_string(index=False))
        print()
    con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['ingest-all', 'events', 'report', 'summary'])
    ap.add_argument('path', nargs='?')
    a = ap.parse_args()
    if a.cmd == 'report':
        report()
    elif a.cmd == 'summary':
        print(json.dumps(write_summary()['latest'], indent=1, ensure_ascii=False, default=float))
    else:
        print(ingest_all() if a.cmd == 'ingest-all' else load_events(a.path))


if __name__ == '__main__':
    main()
