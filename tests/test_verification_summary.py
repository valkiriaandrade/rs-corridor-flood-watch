"""Continuous verification of the five forecast models (floodwatch.verification_summary), on a small SQLite archive."""

import json
import math

import pandas as pd
import pytest

from floodwatch import forecast_db, verification_summary as VS

CODES = [('4300001', 'A', '116'), ('4300002', 'B', '116/386')]


def _run(con, run_id, cutoff, early=1, ecmwf_run=None):
    con.execute(
        'INSERT INTO runs (run_id, created_utc, ecmwf_run, gfs_run, observed_cutoff, antecedent_json) VALUES (?,?,?,?,?,?)',
        (
            run_id,
            run_id,
            ecmwf_run or f'{cutoff}T12',
            f'{cutoff}T12',
            cutoff,
            json.dumps({'late': 30 - early, 'early': early}),
        ),
    )


def _mun(con, run_id, date, lead, model, source, levels, rain=10.0, api_levels=None):
    for (code, nome, corr), lv, la in zip(CODES, levels, api_levels or levels):
        con.execute(
            'INSERT INTO municipal (run_id, date, codarea, nome, corridors, model, source, lead_days, level, level_api, '
            'rain_mm) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            (run_id, date, code, nome, corr, model, source, lead, lv, la, rain),
        )


def _ens(con, run_id, date, lead, model, p_watch, p_warning, p_watch_api=None, p_warning_api=None, rain=12.0):
    for k, (code, _, _) in enumerate(CODES):
        pwa = p_watch if p_watch_api is None else p_watch_api
        paa = p_warning if p_warning_api is None else p_warning_api
        con.execute(
            'INSERT INTO ensemble (run_id, model, init_utc, members, date, codarea, lead_days, rain_mean, rain_p90, '
            'p_watch, p_warning, p_watch_api, p_warning_api) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (
                run_id,
                model,
                '2026-11-24T18:00',
                51,
                date,
                code,
                lead,
                rain,
                rain * 2,
                p_watch[k],
                p_warning[k],
                pwa[k],
                paa[k],
            ),
        )


@pytest.fixture
def con(tmp_path):
    """Issuance r1 (cutoff 20 Nov) forecasts 21 Nov at D+1; run r2 (cutoff 21 Nov) holds 21 Nov as observed.
    Observed on 21 Nov: A at Watch, B Normal (EDI); A at Warning, B Watch (API)."""
    c = forecast_db.connect(tmp_path / 'forecasts.sqlite')
    _run(c, 'r1', '2026-11-20')
    _run(c, 'r2', '2026-11-21', early=1)
    _mun(c, 'r2', '2026-11-21', 0, 'ECMWF', 'observado', [1, 0], rain=10.0, api_levels=[2, 1])
    _mun(c, 'r1', '2026-11-21', 1, 'ECMWF', 'previsão', [1, 1], rain=20.0)  # hit + false alarm (EDI)
    _mun(c, 'r1', '2026-11-21', 1, 'GFS', 'previsão', [0, 0], rain=4.0)  # miss
    # ensembles: ECMWF ENS reaches Watch in A only (0.5 is enough); GEFS stays below 0.5 (EDI) but not for the API
    _ens(c, 'r1', '2026-11-21', 1, 'ECMWF ENS', [0.5, 0.49], [0.1, 0.0])
    _ens(c, 'r1', '2026-11-21', 1, 'GEFS', [0.2, 0.4], [0.0, 0.0], p_watch_api=[0.9, 0.6], p_warning_api=[0.7, 0.1])
    c.commit()
    yield c
    c.close()


def _row(daily, model, ix='EDI', lead=1):
    r = daily[(daily.model == model) & (daily['index'] == ix) & (daily.lead == lead)]
    assert len(r) == 1, (model, ix, lead)
    return r.iloc[0]


def test_ensemble_level_is_the_highest_level_reached_with_half_the_members():
    p_watch = pd.Series([0.49, 0.5, 0.9, 0.9, float('nan')])
    p_warning = pd.Series([0.0, 0.1, 0.5, 0.49, 0.1])
    level = VS.ensemble_level(p_watch, p_warning)
    assert level.iloc[:4].tolist() == [0, 1, 2, 1] and math.isnan(level.iloc[4])
    assert VS.ENSEMBLE_P == 0.5


def test_every_model_is_verified_on_the_same_day_lead_and_observed_level(con):
    daily = VS.daily_table(VS.verification_frame(con))
    for ix in ('EDI', 'API'):
        assert set(daily[daily['index'] == ix].model) == set(VS.MODELS)
    assert set(daily.date) == {'2026-11-21'} and set(daily.lead) == {1}
    e, g = _row(daily, 'ECMWF'), _row(daily, 'GFS')
    assert (e.hits, e.false_alarms, e.misses, e.correct_negatives) == (1, 1, 0, 0)
    assert (g.hits, g.false_alarms, g.misses, g.correct_negatives) == (0, 0, 1, 1)
    c = _row(daily, 'Consensus')  # lower level of the two models, rain = their mean
    assert (c.hits, c.misses) == (0, 1) and c.fc_rain_sum == pytest.approx(2 * 12.0)
    ens = _row(daily, 'ECMWF ENS')  # P = 0.5 counts as Watch, 0.49 does not
    assert (ens.hits, ens.false_alarms, ens.misses, ens.correct_negatives) == (1, 0, 0, 1)
    assert ens.fc_rain_sum == pytest.approx(2 * 12.0) and ens.obs_rain_sum == pytest.approx(2 * 10.0)  # rain_mean


def test_ensemble_events_use_the_probabilities_of_the_selected_index(con):
    daily = VS.daily_table(VS.verification_frame(con))
    edi, api = _row(daily, 'GEFS', 'EDI'), _row(daily, 'GEFS', 'API')
    assert (edi.hits, edi.misses) == (0, 1)  # p_watch 0.2 / 0.4: Normal
    assert (api.hits, api.misses, api.false_alarms) == (2, 0, 0)  # p_watch_api 0.9 / 0.6: both at Watch or above
    # Brier: P(Watch) against observed Watch-or-above, P(Warning) against observed Warning
    assert api.brier_watch_sum == pytest.approx((0.9 - 1) ** 2 + (0.6 - 1) ** 2)
    assert api.brier_warning_sum == pytest.approx((0.7 - 1) ** 2 + (0.1 - 0) ** 2)
    assert _row(daily, 'ECMWF', 'API').n_prob == 0  # deterministic models have no Brier score


def test_each_day_uses_the_latest_forecast_issued_before_it(con):
    # a later refresh of the same issuance (same model runs) replaces the earlier one
    _run(con, 'r1b', '2026-11-20', ecmwf_run='2026-11-20T12')
    _mun(con, 'r1b', '2026-11-21', 1, 'ECMWF', 'previsão', [0, 0])
    _mun(con, 'r1b', '2026-11-21', 1, 'GFS', 'previsão', [0, 0])
    _ens(con, 'r1b', '2026-11-21', 1, 'ECMWF ENS', [0.0, 0.0], [0.0, 0.0])
    con.commit()
    daily = VS.daily_table(VS.verification_frame(con))
    assert _row(daily, 'ECMWF').false_alarms == 0 and _row(daily, 'ECMWF').misses == 1
    assert _row(daily, 'ECMWF ENS').hits == 0


def test_provisional_days_are_the_early_merge_days_of_the_latest_run(con):
    assert VS.provisional_days(con) == ['2026-11-21']
    daily = VS.daily_table(VS.verification_frame(con), VS.provisional_days(con))
    assert daily.provisional.all()


def _synthetic(spec, end='2026-11-26'):
    """spec: {model: (n_days, hits, false_alarms, misses) per day and lead}: a daily table ending on `end`."""
    rows = []
    for model, (n_days, h, fa, m) in spec.items():
        for d in pd.date_range(end=end, periods=n_days):
            for lead in VS.LEADS:
                for ix in ('EDI', 'API'):
                    rows.append(
                        {
                            'date': d.strftime('%Y-%m-%d'),
                            'model': model,
                            'lead': lead,
                            'index': ix,
                            'n': 10,
                            'hits': h,
                            'false_alarms': fa,
                            'misses': m,
                            'correct_negatives': 10 - h - fa - m,
                            'fc_rain_sum': 12.0,
                            'obs_rain_sum': 10.0,
                            'abs_err_sum': 4.0,
                            'n_rain': 2,
                            'brier_watch_sum': None,
                            'brier_warning_sum': None,
                            'n_prob': 0,
                            'provisional': d == pd.Timestamp(end),
                        }
                    )
    return pd.DataFrame(rows, columns=VS.DAILY_COLS)


def test_windows_counts_and_sample_notes():
    daily = _synthetic({'ECMWF': (45, 2, 1, 1), 'GFS': (15, 1, 1, 2), 'GEFS': (5, 3, 0, 0)})
    last30 = VS.accuracy(daily, 'API', '30d')
    e = last30['models']['ECMWF']
    assert last30['start'] == '2026-10-28' and e['pooled']['days'] == 30 and e['pooled']['status'] == 'ok'
    assert e['leads'][1]['events'] == 30 * 3 and e['leads'][1]['CSI'] == pytest.approx(2 / 4)
    assert e['leads'][1]['bias'] == pytest.approx(1.2) and e['leads'][1]['MAE'] == pytest.approx(2.0)
    assert e['pooled']['provisional_days'] == 1
    assert last30['models']['GFS']['pooled']['status'] == 'small'  # 15 days: below 30
    assert last30['models']['GEFS']['pooled']['status'] == 'accumulating'  # 5 days: below 10
    assert last30['models']['GEFS']['first'] == '2026-11-22'
    since = VS.accuracy(daily, 'API', 'all')
    assert since['start'] is None and since['models']['ECMWF']['pooled']['days'] == 45
    common = VS.accuracy(daily, 'API', 'common')  # the period common to all models = the shortest archive
    assert common['start'] == '2026-11-22' and {x['pooled']['days'] for x in common['models'].values()} == {5}


def test_best_model_ignores_models_still_accumulating():
    daily = _synthetic({'ECMWF': (30, 2, 1, 1), 'GFS': (30, 3, 0, 1), 'GEFS': (5, 4, 0, 0)})
    acc = VS.accuracy(daily, 'EDI', '30d')
    assert acc['models']['GEFS']['pooled']['CSI'] == 1.0  # best CSI, but only 5 days
    assert VS.best_model(acc) == 'GFS'
    assert VS.best_model(VS.accuracy(daily, 'EDI', 'common')) is None  # nobody has 10 days in the common period


def test_trend_is_the_daily_csi_pooled_over_leads():
    daily = _synthetic({'ECMWF': (3, 2, 1, 1)})
    t = VS.trend(daily, 'EDI', 'all')
    assert len(t) == 3 and t.CSI.tolist() == pytest.approx([0.5] * 3)


def test_summary_reports_all_five_models_in_the_same_tables_with_brier_for_ensembles(con):
    s = forecast_db.summary(con)
    assert set(s['by_lead']) == set(VS.MODELS)
    assert set(s['latest']['models']) == set(VS.MODELS)
    for m in VS.MODELS:
        x = s['by_lead'][m]['1']
        assert x['days'] == 1 and {'EDI', 'API'} <= set(x)
        assert ('brier' in x) == (m in VS.ENSEMBLES)
    assert s['by_lead']['GEFS']['1']['brier']['API']['n'] == 2
