"""Continuous verification of every forecast model, the same way for all of them (dashboard: "How the models are
verifying now").

Five models: ECMWF and GFS (deterministic, 0.25-degree grid), Consensus (the lower level of the two; rain = their mean)
and the ensembles ECMWF ENS and GEFS (0.5-degree grid, protocol §9.7). Every model is verified exactly as the
deterministic forecasts always were (`verification` view, sql/schema.sql):

- the same observed truth: the frozen rule applied to MERGE rainfall (`observed` view);
- the same lead_days (date - observed_cutoff of the run) and the same issuances (last refresh of each issuance);
- each day scored with the latest forecast issued before it, per lead;
- an event is a municipality-day at Watch or above with observed rain.

The ensemble forecast level is the highest level reached with probability >= ENSEMBLE_P (share of members), a display
and verification rule fixed before any result (docs/protocol.md §9.7), never tuned. Ensemble rain = member mean.

    verification_frame(con)   -> one row per forecast municipality-day, all five models (verification columns)
    daily_table(v, prov)      -> per day x model x lead x index: contingency, rain sums, Brier sums
                                 (written to data/processed/forecast/verification_daily.csv by forecast_db)
    accuracy(daily, ix, ...)  -> scores per model and lead in a window (pure; used by the dashboard)
"""

import json

import pandas as pd

ENSEMBLE_P = 0.5  # ensemble level = highest level reached by >= 50 % of the members (protocol §9.7; never tuned)
MODELS = ['ECMWF', 'GFS', 'Consensus', 'ECMWF ENS', 'GEFS']
ENSEMBLES = ['ECMWF ENS', 'GEFS']
LEADS = (1, 2, 3)
WINDOW_DAYS = 30
MIN_DAYS = 10  # below this, a model shows "accumulating since <date>" instead of a percentage
SMALL_DAYS = 30  # below this, a "small sample" note
INDEX_COLS = {
    'EDI': ('fc_level', 'obs_level', 'p_watch', 'p_warning'),
    'API': ('fc_level_api', 'obs_level_api', 'p_watch_api', 'p_warning_api'),
}
VCOLS = [
    'run_id',
    'date',
    'lead_days',
    'model',
    'codarea',
    'nome',
    'corridors',
    'fc_rain',
    'obs_rain',
    'fc_level',
    'obs_level',
    'fc_level_api',
    'obs_level_api',
    'p_watch',
    'p_warning',
    'p_watch_api',
    'p_warning_api',
]
DAILY_COLS = [
    'date',
    'model',
    'lead',
    'index',
    'n',
    'hits',
    'false_alarms',
    'misses',
    'correct_negatives',
    'fc_rain_sum',
    'obs_rain_sum',
    'abs_err_sum',
    'n_rain',
    'brier_watch_sum',
    'brier_warning_sum',
    'n_prob',
    'provisional',
]


def ensemble_level(p_watch, p_warning):
    """Highest level reached with probability >= ENSEMBLE_P (NaN where the probability is missing)."""
    level = pd.Series(0.0, index=p_watch.index)
    level[p_watch >= ENSEMBLE_P] = 1
    level[p_warning >= ENSEMBLE_P] = 2
    return level.where(p_watch.notna() & p_warning.notna())


def _consensus(det):
    """Consensus = the lower level of ECMWF and GFS (as on the map); rain = mean of the two forecasts."""
    keys = ['run_id', 'date', 'lead_days', 'codarea']
    e, g = det[det.model == 'ECMWF'], det[det.model == 'GFS']
    m = e.merge(g[keys + ['fc_rain', 'fc_level', 'fc_level_api']], on=keys, suffixes=('', '_g'))
    m['fc_rain'] = (m.fc_rain + m.fc_rain_g) / 2
    for c in ('fc_level', 'fc_level_api'):
        m[c] = m[[c, c + '_g']].min(axis=1, skipna=False)
    return m.drop(columns=['fc_rain_g', 'fc_level_g', 'fc_level_api_g']).assign(model='Consensus')


def verification_frame(con):
    """Forecast municipality-days of all five models paired with the observed level, in the `verification` columns."""
    det = pd.read_sql_query('SELECT * FROM verification', con)
    det = det.assign(p_watch=float('nan'), p_warning=float('nan'), p_watch_api=float('nan'), p_warning_api=float('nan'))
    frames = [det[VCOLS], _consensus(det)[VCOLS]]
    have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'ensemble'")}
    if have:
        ens = pd.read_sql_query(
            """SELECT e.run_id, e.date, e.lead_days, e.model, e.codarea, o.nome, o.corridors,
                      e.rain_mean AS fc_rain, o.rain_mm AS obs_rain, o.level AS obs_level, o.level_api AS obs_level_api,
                      e.p_watch, e.p_warning, e.p_watch_api, e.p_warning_api
               FROM ensemble e JOIN observed o ON o.date = e.date AND o.codarea = e.codarea
               WHERE e.lead_days >= 1
                 AND e.run_id IN (SELECT MAX(run_id) FROM runs GROUP BY ecmwf_run, gfs_run, observed_cutoff)""",
            con,
        )
        ens['fc_level'] = ensemble_level(ens.p_watch, ens.p_warning)
        ens['fc_level_api'] = ensemble_level(ens.p_watch_api, ens.p_warning_api)
        frames.append(ens[VCOLS])
    return pd.concat([f for f in frames if len(f)], ignore_index=True) if any(len(f) for f in frames) else det[VCOLS]


def provisional_days(con):
    """Observed days still on the preliminary MERGE product ('early') in the most recent run: refined later."""
    row = con.execute('SELECT observed_cutoff, antecedent_json FROM runs ORDER BY run_id DESC LIMIT 1').fetchone()
    if not row or not row[0]:
        return []
    early = json.loads(row[1] or '{}').get('early', 0)
    cutoff = pd.Timestamp(row[0])
    return [(cutoff - pd.Timedelta(days=k)).strftime('%Y-%m-%d') for k in range(early)]


def daily_table(v, provisional=()):
    """Per verified day, model, lead and index: Watch-or-above contingency (latest forecast issued before the day for
    that lead), rain sums and, for the ensembles, Brier-score sums for P(Watch) and P(Warning)."""
    if v.empty:
        return pd.DataFrame(columns=DAILY_COLS)
    v = v[v.run_id == v.groupby(['model', 'date', 'lead_days']).run_id.transform('max')]
    rows = []
    for (date, model, lead), g in v.groupby(['date', 'model', 'lead_days']):
        r = g.dropna(subset=['fc_rain', 'obs_rain'])
        rain = {
            'fc_rain_sum': float(r.fc_rain.sum()),
            'obs_rain_sum': float(r.obs_rain.sum()),
            'abs_err_sum': float((r.fc_rain - r.obs_rain).abs().sum()),
            'n_rain': int(len(r)),
        }
        for ix, (fc, ob, pw, pa) in INDEX_COLS.items():
            ok = (g[fc] >= 0) & (g[ob] >= 0)
            if not ok.any():
                continue
            f, o = g.loc[ok, fc] >= 1, g.loc[ok, ob] >= 1
            row = {
                'date': date,
                'model': model,
                'lead': int(lead),
                'index': ix,
                'n': int(ok.sum()),
                'hits': int((f & o).sum()),
                'false_alarms': int((f & ~o).sum()),
                'misses': int((~f & o).sum()),
                'correct_negatives': int((~f & ~o).sum()),
                **rain,
                'brier_watch_sum': None,
                'brier_warning_sum': None,
                'n_prob': 0,
                'provisional': date in set(provisional),
            }
            p = g[ok & g[pw].notna() & g[pa].notna()]
            if len(p):
                row.update(
                    brier_watch_sum=float(((p[pw] - (p[ob] >= 1)) ** 2).sum()),
                    brier_warning_sum=float(((p[pa] - (p[ob] == 2)) ** 2).sum()),
                    n_prob=int(len(p)),
                )
            rows.append(row)
    return pd.DataFrame(rows, columns=DAILY_COLS)


def _scores(g):
    h, fa, m = int(g.hits.sum()), int(g.false_alarms.sum()), int(g.misses.sum())
    obs, n_rain, n_prob = float(g.obs_rain_sum.sum()), int(g.n_rain.sum()), int(g.n_prob.sum())
    return {
        'days': int(g.date.nunique()),
        'events': h + m,  # municipality-days at observed Watch or above
        'n': int(g.n.sum()),
        'hits': h,
        'false_alarms': fa,
        'misses': m,
        'CSI': h / (h + fa + m) if h + fa + m else None,
        'POD': h / (h + m) if h + m else None,
        'FAR': fa / (h + fa) if h + fa else None,
        'bias': float(g.fc_rain_sum.sum()) / obs if obs > 0 else None,
        'MAE': float(g.abs_err_sum.sum()) / n_rain if n_rain else None,
        'brier_watch': float(g.brier_watch_sum.sum()) / n_prob if n_prob else None,
        'brier_warning': float(g.brier_warning_sum.sum()) / n_prob if n_prob else None,
        'provisional_days': int(g.loc[g.provisional.astype(bool), 'date'].nunique()),
    }


def _status(days):
    return 'accumulating' if days < MIN_DAYS else ('small' if days < SMALL_DAYS else 'ok')


def periods(daily):
    """First and last verified day of each model, the latest day overall and the common period of all models."""
    if daily.empty:
        return {'models': {}, 'end': None, 'common_start': None}
    first = daily.groupby('model').date.min().to_dict()
    end = daily.date.max()
    return {
        'models': {m: {'first': first[m], 'last': daily[daily.model == m].date.max()} for m in first},
        'end': end,
        'common_start': max(first.values()),
    }


def window_start(daily, window):
    """'30d': last WINDOW_DAYS days; 'common': the common period of all models; 'all': each model's whole archive."""
    p = periods(daily)
    if p['end'] is None or window == 'all':
        return None
    if window == 'common':
        return p['common_start']
    return (pd.Timestamp(p['end']) - pd.Timedelta(days=WINDOW_DAYS - 1)).strftime('%Y-%m-%d')


def accuracy(daily, ix, window='30d', leads=LEADS):
    """Scores per model for each lead and pooled over `leads`, for index ix, in the window. Each entry carries the
    number of verified days and events and a status: 'accumulating' (< MIN_DAYS days), 'small' (< SMALL_DAYS), 'ok'."""
    start = window_start(daily, window)
    p = periods(daily)
    d = daily[(daily['index'] == ix) & daily.lead.isin(leads)]
    if start is not None:
        d = d[d.date >= start]
    out = {
        'index': ix,
        'window': window,
        'start': start,
        'end': p['end'],
        'common_start': p['common_start'],
        'models': {},
    }
    for model in MODELS:
        g = d[d.model == model]
        if model not in p['models']:
            continue
        pooled = _scores(g)
        out['models'][model] = {
            'first': p['models'][model]['first'],
            'pooled': {**pooled, 'status': _status(pooled['days'])},
            'leads': {n: {**(s := _scores(g[g.lead == n])), 'status': _status(s['days'])} for n in leads},
        }
    return out


def best_model(acc):
    """Model with the highest pooled CSI among those with at least MIN_DAYS verified days (None if none qualifies)."""
    ok = {
        m: x['pooled']['CSI']
        for m, x in acc['models'].items()
        if x['pooled']['status'] != 'accumulating' and x['pooled']['CSI'] is not None
    }
    return max(ok, key=ok.get) if ok else None


def trend(daily, ix, window='30d', leads=LEADS):
    """Daily CSI per model, pooled over `leads` (NaN on days without any forecast or observed Watch)."""
    start = window_start(daily, window)
    d = daily[(daily['index'] == ix) & daily.lead.isin(leads)]
    if start is not None:
        d = d[d.date >= start]
    g = d.groupby(['date', 'model'])[['hits', 'false_alarms', 'misses']].sum().reset_index()
    tot = g.hits + g.false_alarms + g.misses
    g['CSI'] = (g.hits / tot).where(tot > 0)
    return g[['date', 'model', 'CSI']]
