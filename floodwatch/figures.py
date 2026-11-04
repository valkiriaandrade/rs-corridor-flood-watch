"""Derived tables for the study page: ROC curves, risk multiplier, May-2024 timeline, event leads, road check.

Levels use the operational rule of floodwatch.rules (thresholds + frozen 3-day trigger), i.e. exactly what the
forecast page shows. Run after the evaluation and the second-trigger test: python -m floodwatch.figures
Index-specific outputs: EDI (no suffix) and API (suffix _API).
"""
import json
import unicodedata

import numpy as np
import pandas as pd

from . import rules as R
from . import study as s
from .paths import ROAD_IMPACTS
IMPACTS = ROAD_IMPACTS / 'impact_precision_review.csv'


def norm(x):
    return unicodedata.normalize('NFKD', str(x)).encode('ascii', 'ignore').decode().lower().strip()


def roc_tables(df):
    rows = []
    y = df.label.to_numpy() == 1
    for col in s.PREDICTORS:
        v = df[col].to_numpy()
        for t in np.unique(np.quantile(v, np.linspace(0, 1, 300))):
            rows.append({'predictor': col, 'threshold': t, 'POD': (v[y] >= t).mean(), 'POFD': (v[~y] >= t).mean()})
    return pd.DataFrame(rows)


def run():
    df = pd.read_csv(s.OUT / 'samples.csv.gz', parse_dates=['date'], dtype={'codarea': str}).dropna(subset=s.PREDICTORS)
    roc_tables(df).to_csv(s.OUT / 'roc.csv', index=False)
    # all municipality-days (not only samples) for timelines and road check
    frames = {'rain': s.study_rain().loc['2012-12-01':]}
    for name in ('pe', 'edi', 'api'):
        f = pd.read_csv(s.OUT / f'index_{name}.csv.gz', index_col=0, parse_dates=True)
        f.columns = f.columns.astype(str)
        frames[name] = f.loc['2012-12-01':]
    table = s.predictors(frames['rain'], frames['pe'], frames['edi'], frames['api'])
    table = table[(table.date >= '2013-01-01') & (table.date <= s.END)]
    for index, rule in R.load_rules().items():
        index_outputs(table.copy(), rule, '' if index == 'EDI' else f'_{index}')


def index_outputs(table, rule, suffix):
    index = rule.index
    table['level'] = R.classify(table[index], table.P3, rule)
    units = pd.read_csv(s.OUT / 'units.csv', dtype={'codarea': str})
    events = pd.read_csv(s.OUT / 'events.csv', parse_dates=['date'], dtype={'codarea': str})

    # Risk multiplier per level on ALL municipality-days 2013-2024 (not the case-control sample).
    onset = set(zip(events.codarea, events.date))
    table['onset'] = [k in onset for k in zip(table.codarea, table.date)]
    full = table[table.level >= 0]
    base = full.onset.mean()
    lift = {'population': f'todos os município-dias 2013-2024 com {index} válido (in-sample: regra final)', 'index': index,
            'rule': rule.as_dict(),
            'n_days': int(len(full)), 'n_onsets': int(full.onset.sum()), 'base_rate': float(base)}
    for name, mask in [('normal', full.level == 0), ('atencao', full.level == 1), ('alerta', full.level == 2),
                       ('atencao_ou_alerta', full.level >= 1)]:
        rate = full.onset[mask].mean()
        lift[name] = {'share_days': float(mask.mean()), 'share_events': float(full.onset[mask].sum() / full.onset.sum()),
                      'event_rate': float(rate), 'lift_vs_base': float(rate / base)}
    lift['alert_pofd_all_non_onset_days'] = float((full.level[~full.onset] == 2).mean())
    lift['attention_or_alert_pofd_all_non_onset_days'] = float((full.level[~full.onset] >= 1).mean())
    (s.OUT / f'level_lift{suffix}.json').write_text(json.dumps(lift, indent=1), encoding='utf-8')

    # May 2024 timeline: share of corridor municipalities at each level + records per day
    w = table[table.date.between('2024-04-10', '2024-05-31')]
    tl = w.groupby('date')['level'].agg(attention=lambda x: (x >= 1).mean(), alert=lambda x: (x == 2).mean()).reset_index()
    rec = events[events.date.between('2024-04-10', '2024-05-31')].groupby('date').size().rename('records')
    tl = tl.merge(rec, left_on='date', right_index=True, how='left').fillna({'records': 0})
    tl.to_csv(s.OUT / f'timeline_2024{suffix}.csv', index=False)

    # Lead time: for each event, days before onset that the municipality was already >= attention (continuous run)
    lv = table.set_index(['codarea', 'date'])['level']
    leads = []
    for e in events.itertuples():
        d, n = e.date, 0
        while (e.codarea, d - pd.Timedelta(days=n + 1)) in lv.index and lv[(e.codarea, d - pd.Timedelta(days=n + 1))] >= 1:
            n += 1
        at = lv.get((e.codarea, d), np.nan)
        leads.append({'codarea': e.codarea, 'date': e.date, 'episode_id': e.episode_id, 'level_on_day': at,
                      'days_before_at_attention': n if at >= 1 else 0})
    pd.DataFrame(leads).to_csv(s.OUT / f'event_leads{suffix}.csv', index=False)

    # Independent road check (never used in calibration)
    imp = pd.read_csv(IMPACTS)
    imp = imp[imp.road.str.extract(r'BR-(\d+)')[0].isin(['116', '386', '290'])].copy()
    names = {norm(n): c for n, c in zip(units.nome, units.codarea)}
    rows = []
    for r in imp.itertuples():
        dates = json.loads(r.status_dates_before) if isinstance(r.status_dates_before, str) else []
        cond = json.loads(r.condition_dates_before) if isinstance(r.condition_dates_before, str) else []
        when = sorted(cond or dates)
        muni = str(r.municipality).split('–')[0].split('(')[0].split(',')[0].strip()
        code = names.get(norm(muni))
        if not when or code is None:
            rows.append({'impact_id': r.impact_id, 'road': r.road, 'km': r.km_start_original, 'municipio': muni,
                         'data': when[0] if when else None, 'status': 'sem data ou município no corredor'})
            continue
        d = pd.Timestamp(when[0])
        window = [lv.get((code, d - pd.Timedelta(days=k)), np.nan) for k in range(0, 8)]
        best = np.nanmax(window[:3]) if np.isfinite(window[:3]).any() else np.nan
        first = next((k for k in range(7, -1, -1) if np.isfinite(window[k]) and window[k] >= 1), None)
        rows.append({'impact_id': r.impact_id, 'road': r.road, 'km': r.km_start_original, 'municipio': muni,
                     'data': str(d.date()), 'nivel_max_d-2_a_d': best,
                     'primeiro_dia_atencao_ate_7d_antes': (-first if first is not None else None),
                     'status': 'avaliado' if np.isfinite(best) else 'fora do período (2013–2024)', 'episodio': r.episode_id})
    pd.DataFrame(rows).to_csv(s.OUT / f'road_check{suffix}.csv', index=False)
    print(index, pd.DataFrame(rows).status.value_counts().to_dict())


if __name__ == '__main__':
    run()
