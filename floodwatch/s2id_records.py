"""Official S2iD flood records vs the rule and the forecasts (dashboard section "Official records").

The S2iD "Danos informados" export (last 60 days of registrations, exported from the PC in Brazil; see
official_records) lists every record in Rio Grande do Sul. For each record:

- event date = the date in the protocol number (RS-F-<ibge>-<cobrade>-YYYYMMDD), not the registration date;
- registration lag = registration date - event date (days);
- in or out of the 86 corridor municipalities.

For the corridor records, the level the frozen rule gives with OBSERVED MERGE rainfall (EDI and API), the observed
rain of the day and of 3 days, and, when a forecast was archived, the level forecast by each model at D+1..D+3 (and
the ensemble probabilities). Next to 'X of Y records at Watch or Warning', the base rate: the share of all corridor
municipality-days of the same period at Watch or Warning. Presentation only: no rule, threshold or archive is changed.

    parse_export(path)  -> records (pure parsing, tested)
    build(...)          -> the dictionary written to data/processed/forecast/official_records.json (pure, tested)
    export(con)         -> reads the files and writes that JSON (called by forecast_db.write_summary)
"""

import json

import pandas as pd

from . import verification_summary as VS
from .paths import FORECAST, STUDY

OUT = FORECAST / 'official_records.json'
OBSERVED_LEVELS = FORECAST / 'observed_levels.csv'  # written by forecast.run: the rule on observed rain, last 75 days
CODES = (12100, 12200, 12300, 13214)  # flood-related COBRADEs, as in the study
LEADS = (1, 2, 3)
LEVEL_COLS = {'EDI': 'fc_level', 'API': 'fc_level_api'}
PROB_COLS = {'EDI': ('p_watch', 'p_warning'), 'API': ('p_watch_api', 'p_warning_api')}


def parse_export(path):
    """Records of the S2iD export with the flood COBRADEs: protocol, codarea, municipio, date (event, from the
    protocol), registered (ISO date), cobrade, cobrade_label, lag_days (registration - event)."""
    from .official_records import read_s2id

    r = read_s2id(path)
    r = r[r.cobrade.astype(int).isin(CODES)].copy()
    r['registered'] = pd.to_datetime(r.registered, format='%d/%m/%Y', errors='coerce').dt.strftime('%Y-%m-%d')
    r['lag_days'] = (pd.to_datetime(r.registered) - pd.to_datetime(r.date)).dt.days
    return r.reset_index(drop=True)


def lag_median(records):
    """Median days between the event and its registration (None without records)."""
    lag = records.lag_days.dropna()
    return float(lag.median()) if len(lag) else None


def _lvl(x):
    return None if x is None or x != x else int(x)


def _num(x):
    return None if x is None or x != x else round(float(x), 1)


def _prob(x):
    return None if x is None or x != x else round(float(x), 3)


def _near(alarms, records):
    """For each alarm row (date, codarea), whether a record exists in the same municipality within one day."""
    if alarms.empty:
        return pd.Series(dtype=bool)
    if records.empty:
        return pd.Series(False, index=alarms.index)
    r = records[['codarea', 'date']].assign(rd=pd.to_datetime(records.date)).drop(columns='date')
    a = alarms[['codarea', 'date']].reset_index().assign(ad=lambda x: pd.to_datetime(x.date))
    m = a.merge(r, on='codarea', how='left')
    m['hit'] = (m.ad - m.rd).abs() <= pd.Timedelta(days=1)
    return m.groupby('index').hit.any().reindex(alarms.index, fill_value=False)


def base_rate(observed, codes, start=None):
    """How often the rule on observed rainfall was at Watch or Warning on ANY corridor municipality-day, from `start`
    (default: the first observed day) to the last observed day: the base rate to read 'X of Y records' against.

    observed: date (ISO), codarea, level, level_api; codes: the corridor municipalities."""
    o = observed[observed.codarea.astype(str).isin(set(codes))]
    if start is not None:
        o = o[o.date >= start]
    out = {'from': o.date.min() if len(o) else None, 'to': o.date.max() if len(o) else None}
    for ix, col in (('EDI', 'level'), ('API', 'level_api')):
        lv = o[col].dropna()
        n, k = int(len(lv)), int((lv >= 1).sum())
        out[ix] = {'municipality_days': n, 'at_watch': k, 'share': k / n if n else None}
    return out


def build(records, units, observed, vframe, archive_start, export_date, preliminary=None, period_start=None):
    """Everything the dashboard shows about the official records (JSON-serialisable).

    records: parse_export output; units: codarea, nome, corridors (the 86 corridor municipalities);
    observed: date, codarea, rain_mm, P3, level, level_api (the rule on observed MERGE rainfall);
    vframe: verification_summary.verification_frame (archived forecasts of the five models);
    preliminary: date, codarea of preliminary reports (count as records for the alarm match);
    period_start: first day of the export's registration period (start of the base-rate period)."""
    units = units.assign(codarea=units.codarea.astype(str))
    corridor = set(units.codarea)
    rec = records.assign(codarea=records.codarea.astype(str), in_corridor=records.codarea.astype(str).isin(corridor))
    lag = lag_median(rec)
    recent_from = (
        (pd.Timestamp(export_date) - pd.Timedelta(days=round(lag))).strftime('%Y-%m-%d') if lag is not None else None
    )
    since = rec[rec.date >= archive_start]
    out = {
        'export_date': export_date,
        'archive_start': archive_start,
        'lag_days_median': lag,
        'recent_from': recent_from,
        'since_archive': {'rs': int(len(since)), 'corridor': int(since.in_corridor.sum())},
        'statewide': [
            {k: (None if v != v else v) for k, v in row.items()}
            for row in rec.sort_values(['date', 'municipio'], ascending=[False, True])[
                [
                    'protocol',
                    'municipio',
                    'codarea',
                    'date',
                    'registered',
                    'cobrade',
                    'cobrade_label',
                    'lag_days',
                    'in_corridor',
                ]
            ]
            .astype(object)
            .to_dict('records')
        ],
    }
    # forecasts: per model, date, codarea and lead, the latest issuance (as in the continuous verification)
    v = vframe[vframe.lead_days.isin(LEADS)]
    v = v[v.run_id == v.groupby(['model', 'date', 'lead_days']).run_id.transform('max')]
    fc = {(r.model, r.date, str(r.codarea), int(r.lead_days)): r for r in v.itertuples()}
    obs = observed.assign(
        codarea=observed.codarea.astype(str), date=pd.to_datetime(observed.date).dt.strftime('%Y-%m-%d')
    )
    obs = obs.set_index(['date', 'codarea'])
    names = units.set_index('codarea')
    items = []
    for r in rec[rec.in_corridor].sort_values('date', ascending=False).itertuples():
        o = obs.loc[(r.date, r.codarea)] if (r.date, r.codarea) in obs.index else None
        item = {
            'protocol': r.protocol,
            'codarea': r.codarea,
            'nome': names.at[r.codarea, 'nome'],
            'corridors': str(names.at[r.codarea, 'corridors']),
            'date': r.date,
            'registered': r.registered,
            'cobrade': r.cobrade,
            'archived': r.date >= archive_start,
            'recent': recent_from is not None and r.date >= recent_from,
            'observed': {
                'rain_mm': _num(o.rain_mm) if o is not None else None,
                'P3': _num(o.P3) if o is not None else None,
                'EDI': _lvl(o.level) if o is not None else None,
                'API': _lvl(o.level_api) if o is not None else None,
            },
            'forecast': {},
            'outcome': {},
        }
        for model in VS.MODELS:
            leads = {}
            for n in LEADS:
                f = fc.get((model, r.date, r.codarea, n))
                if f is None:
                    continue
                cell = {ix: _lvl(getattr(f, col)) for ix, col in LEVEL_COLS.items()}
                if model in VS.ENSEMBLES:
                    cell['p'] = {ix: [_prob(getattr(f, a)), _prob(getattr(f, b))] for ix, (a, b) in PROB_COLS.items()}
                leads[str(n)] = cell
            if leads:
                item['forecast'][model] = leads
                first = leads[min(leads, key=int)]  # the latest forecast issued before the day
                item['outcome'][model] = {
                    ix: (None if first[ix] is None else ('hit' if first[ix] >= 1 else 'missed')) for ix in LEVEL_COLS
                }
        items.append(item)
    out['corridor'] = items
    out['observed_rule'] = {
        ix: {
            'records': sum(1 for i in items if i['observed'][ix] is not None),
            'at_watch': sum(1 for i in items if (i['observed'][ix] or 0) >= 1),
        }
        for ix in LEVEL_COLS
    }
    out['observed_base_rate'] = base_rate(obs.reset_index(), corridor, period_start)
    out['forecast_outcome'] = {
        m: {
            ix: {
                'records': sum(1 for i in items if i['outcome'].get(m, {}).get(ix) is not None),
                'hits': sum(1 for i in items if i['outcome'].get(m, {}).get(ix) == 'hit'),
            }
            for ix in LEVEL_COLS
        }
        for m in VS.MODELS
    }
    # alarms with no official or preliminary record in the same municipality within one day (latest issuance per day)
    known = rec[['date', 'codarea']]
    if preliminary is not None and len(preliminary):
        known = pd.concat([known, preliminary[['date', 'codarea']].astype(str)], ignore_index=True)
    w = vframe[(vframe.date >= archive_start) & (vframe.date <= export_date)].copy()
    w['codarea'] = w.codarea.astype(str)
    w = w[w.run_id == w.groupby(['model', 'date']).run_id.transform('max')]
    alarms = {}
    for model, g in w.groupby('model'):
        alarms[model] = {}
        for ix, col in LEVEL_COLS.items():
            a = g[g[col] >= 1]
            if a.empty:
                continue
            near = _near(a, known)
            alarms[model][ix] = {
                'alarms': int(len(a)),
                'without_record': int((~near).sum()),
                'share': float((~near).mean()),
            }
    out['alarms_without_record'] = alarms
    return out


def export(con):
    """Read the S2iD export, the observed levels and the archive; write official_records.json. None without export."""
    from .official_records import S2ID_DIR, preliminary_reports

    path = S2ID_DIR / 'danos_informados_RS.csv'
    audit = path.with_name(path.name + '.http.json')
    if not (path.exists() and audit.exists() and OBSERVED_LEVELS.exists()):
        return None
    meta = json.loads(audit.read_text(encoding='utf-8'))
    runs = [r[0] for r in con.execute('SELECT run_id FROM runs ORDER BY run_id LIMIT 1')]
    archive_start = pd.Timestamp(runs[0][:8]).strftime('%Y-%m-%d') if runs else meta['registration_period'][0]
    out = build(
        parse_export(path),
        pd.read_csv(STUDY / 'units.csv', dtype=str),
        pd.read_csv(OBSERVED_LEVELS, dtype={'codarea': str}),
        VS.verification_frame(con),
        archive_start,
        pd.Timestamp(meta['downloaded_at_utc']).strftime('%Y-%m-%d'),
        preliminary_reports(),
        (meta.get('registration_period') or [None])[0],
    )
    out['registration_period'] = meta.get('registration_period')
    out['downloaded_utc'] = meta['downloaded_at_utc']
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str), encoding='utf-8')
    return out
