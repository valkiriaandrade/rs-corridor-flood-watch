"""Tests for the operational paths of the daily job: Open-Meteo run selection, catch-up dates, the SQLite archive
and the dashboard pages. Open-Meteo is replaced by recorded-style fake responses; nothing is downloaded."""

import json
import shutil
import socket
import sqlite3
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest
import requests

from floodwatch import forecast, forecast_db

RUN_12Z = pd.Timestamp('2026-11-20T12:00', tz='UTC')
NOT_AVAILABLE = {'error': True, 'reason': 'The requested model run is not available'}


def _response(status, body, url='https://example.invalid'):
    r = requests.Response()
    r.status_code, r._content, r.url = status, json.dumps(body).encode(), url
    return r


def _hourly_body(start='2026-11-20T13:00', hours=72, mm=1.0):
    times = pd.date_range(start, periods=hours, freq='h').strftime('%Y-%m-%dT%H:%M').tolist()
    return {'hourly': {'time': times, 'precipitation': [mm] * hours}}


class FakeOpenMeteo:
    """single-runs API: answers 400 'not available' for the runs in `missing`, otherwise hourly rain of 1 mm."""

    def __init__(self, missing=(), status=400, body=NOT_AVAILABLE):
        self.missing, self.status, self.body, self.runs = set(missing), status, body, []

    def __call__(self, url, timeout=None):
        query = parse_qs(urlparse(url).query)
        run = query['run'][0]
        self.runs.append(run)
        if run in self.missing:
            return _response(self.status, self.body, url)
        n = len(query['latitude'][0].split(','))
        return _response(200, [_hourly_body()] * n if n > 1 else _hourly_body(), url)


@pytest.fixture
def points():
    return pd.DataFrame({'point': ['p1', 'p2'], 'lat': [-29.0, -29.25], 'lon': [-51.0, -51.25]})


@pytest.fixture
def offline(monkeypatch, tmp_path):
    """Raw responses go to a temporary folder and retries do not wait."""
    monkeypatch.setattr(forecast, 'RAWF', tmp_path / 'forecast_api')
    monkeypatch.setattr(forecast.time, 'sleep', lambda s: None)


def _install(monkeypatch, fake):
    monkeypatch.setattr(forecast.requests, 'get', fake)
    return fake


def test_tests_cannot_reach_the_network():
    with pytest.raises(RuntimeError, match='must not use the network'):
        socket.create_connection(('api.open-meteo.com', 443), timeout=1)


# ---------------------------------------------------------------- Open-Meteo run selection
def test_forecast_uses_the_12utc_run_when_available(monkeypatch, offline, points):
    fake = _install(monkeypatch, FakeOpenMeteo())
    df, run = forecast.forecast_daily(points, 'GFS', 'stamp', run=RUN_12Z, batch_size=1, pause=0)
    assert run == RUN_12Z and fake.runs == ['2026-11-20T12:00'] * 2
    assert list(df.index) == list(pd.date_range('2026-11-21', '2026-11-23'))  # windows of the nominal 12 UTC issuance
    assert (df == 24.0).all().all() and list(df.columns) == ['p1', 'p2']


def test_missing_12utc_run_falls_back_to_06utc_and_every_batch_uses_it(monkeypatch, offline, points):
    fake = _install(monkeypatch, FakeOpenMeteo(missing={'2026-11-20T12:00'}))
    df, run = forecast.forecast_daily(points, 'GFS', 'stamp', run=RUN_12Z, batch_size=1, pause=0)
    assert run == RUN_12Z - pd.Timedelta(hours=6)
    assert fake.runs == ['2026-11-20T12:00', '2026-11-20T06:00', '2026-11-20T06:00']
    assert df.index.min() == pd.Timestamp('2026-11-21')  # still the windows of the 12 UTC issuance
    assert (forecast.RAWF / 'stamp' / 'GFS_0.json').exists() and (forecast.RAWF / 'stamp' / 'GFS_1.json').exists()


def test_no_run_of_the_day_available_raises(monkeypatch, offline, points):
    fake = _install(monkeypatch, FakeOpenMeteo(missing={'2026-11-20T12:00', '2026-11-20T06:00', '2026-11-20T00:00'}))
    with pytest.raises(RuntimeError, match='no run available'):
        forecast.forecast_daily(points, 'GFS', 'stamp', run=RUN_12Z, pause=0)
    assert fake.runs == ['2026-11-20T12:00', '2026-11-20T06:00', '2026-11-20T00:00']  # never a later run


def test_other_http_errors_are_not_treated_as_a_missing_run(monkeypatch, offline, points):
    fake = _install(
        monkeypatch, FakeOpenMeteo(missing={'2026-11-20T12:00'}, body={'error': True, 'reason': 'Bad latitude'})
    )
    with pytest.raises(requests.HTTPError):
        forecast.forecast_daily(points, 'GFS', 'stamp', run=RUN_12Z, pause=0)
    assert fake.runs == ['2026-11-20T12:00']


def test_run_missing_only_for_400_not_available():
    assert forecast._run_missing(_response(400, NOT_AVAILABLE))
    assert not forecast._run_missing(_response(400, {'reason': 'Parameter hourly is invalid'}))
    assert not forecast._run_missing(_response(404, NOT_AVAILABLE))
    r = _response(400, {})
    r._content = b'<html>not json</html>'
    assert not forecast._run_missing(r)


def test_latest_run_retries_a_transient_404_and_picks_the_last_12utc_run(monkeypatch, offline):
    answers = [
        _response(404, {}),
        _response(200, {'last_run_initialisation_time': pd.Timestamp('2026-11-20T18:00Z').timestamp()}),
    ]
    monkeypatch.setattr(forecast.requests, 'get', lambda url, timeout=None: answers.pop(0))
    assert forecast.latest_run('ncep_gfs013') == RUN_12Z and not answers
    early = pd.Timestamp('2026-11-20T06:00Z').timestamp()
    monkeypatch.setattr(
        forecast.requests, 'get', lambda url, timeout=None: _response(200, {'last_run_initialisation_time': early})
    )
    assert forecast.latest_run('ncep_gfs013') == RUN_12Z - pd.Timedelta(days=1)


def test_get_gives_up_after_the_last_try(monkeypatch, offline):
    calls = []
    monkeypatch.setattr(forecast.requests, 'get', lambda url, timeout=None: calls.append(url) or _response(503, {}))
    with pytest.raises(requests.HTTPError):
        forecast._get('https://example.invalid', tries=3)
    assert len(calls) == 3


# ---------------------------------------------------------------- catch-up dates
@pytest.fixture
def archive(monkeypatch, tmp_path):
    """A fresh archive in a temporary folder, used by every forecast_db.connect() call."""
    path = tmp_path / 'forecasts.sqlite'
    real = forecast_db.connect
    monkeypatch.setattr(forecast_db, 'connect', lambda p=path: real(p))
    return path


def _add_runs(path, ecmwf_runs):
    con = forecast_db.connect(path)
    con.executemany(
        'INSERT INTO runs (run_id, ecmwf_run) VALUES (?, ?)', [(f'r{i}', r) for i, r in enumerate(ecmwf_runs)]
    )
    con.commit()
    con.close()


def test_missing_issues_fresh_archive_starts_today(archive):
    assert forecast.missing_issues(pd.Timestamp('2026-11-23T12:00Z')) == []


def test_missing_issues_after_the_last_archived_run(archive):
    # 06 UTC fallback runs and naive timestamps count as the issuance of their day
    _add_runs(archive, ['2026-11-18T12:00:00+00:00', '2026-11-20T06:00:00+00:00', None])
    todo = forecast.missing_issues(pd.Timestamp('2026-11-23T12:00Z'))
    assert todo == list(pd.date_range('2026-11-21', '2026-11-22'))  # 19 Nov is older than the last run: not redone


def test_missing_issues_never_goes_back_more_than_backfill_days(archive):
    _add_runs(archive, ['2026-10-01T12:00:00'])
    todo = forecast.missing_issues(pd.Timestamp('2026-11-23T12:00Z'))
    assert (
        len(todo) == forecast.BACKFILL_DAYS
        and todo[0] == pd.Timestamp('2026-11-09')
        and todo[-1] == pd.Timestamp('2026-11-22')
    )


# ---------------------------------------------------------------- SQLite archive
RULES = {
    'EDI': {'index': 'EDI', 'attention': 1.25, 'alert': 3.37, 'trigger_p3_mm': 60.0},
    'API': {'index': 'API', 'attention': 72.0, 'alert': 128.0, 'trigger_p3_mm': 60.0},
}


def _run_folder(root, name, cutoff, fc_level=1, obs_level=0):
    """A run folder as forecast.run() writes it: two municipalities, both models, one observed and one forecast day."""
    run_dir = root / name
    run_dir.mkdir(parents=True)
    meta = {
        'created_utc': name,
        'runs': {'ECMWF': f'{cutoff}T12:00:00+00:00', 'GFS': f'{cutoff}T12:00:00+00:00'},
        'observed_cutoff': cutoff,
        'rules': RULES,
        'antecedent_product_last_30d': {'early': 30},
    }
    (run_dir / 'metadata.json').write_text(json.dumps(meta), encoding='utf-8')
    rows = []
    for date, source, level in [
        (cutoff, 'observado', obs_level),
        (str((pd.Timestamp(cutoff) + pd.Timedelta(days=1)).date()), 'previsão', fc_level),
    ]:
        for model in ('ECMWF', 'GFS'):
            for code, nome, corridors in [('4300001', 'A', '116'), ('4300002', 'B', '116/386')]:
                rows.append(
                    {
                        'date': date,
                        'codarea': code,
                        'nome': nome,
                        'corridors': corridors,
                        'model': model,
                        'source': source,
                        'P1': 5.0,
                        'P3': 20.0,
                        'P7': 30.0,
                        'P30': 90.0,
                        'PE': 40.0,
                        'EDI': 0.5,
                        'level': level,
                        'API': 50.0,
                        'level_api': level,
                        'rain_mm': 5.0,
                    }
                )
    pd.DataFrame(rows).to_csv(run_dir / 'municipal_levels.csv', index=False)
    return run_dir


def _counts(path):
    con = sqlite3.connect(path)
    counts = forecast_db.table_counts(con)
    con.close()
    return counts


def test_ingest_writes_run_municipal_and_corridor_rows_and_is_idempotent(archive, tmp_path):
    run_dir = _run_folder(tmp_path / 'runs', '20261120T200000Z', '2026-11-20')
    assert forecast_db.ingest(run_dir) == ('20261120T200000Z', 8)
    counts = _counts(archive)
    assert counts['runs'] == 1 and counts['municipal'] == 8 and counts['corridor'] == 2 * 2 * len(forecast_db.CORRIDORS)
    con = sqlite3.connect(archive)
    leads = dict(con.execute('SELECT source, MAX(lead_days) FROM municipal GROUP BY source').fetchall())
    br386 = con.execute(
        "SELECT n, level FROM corridor WHERE br = 'BR-386' AND source = 'previsão' AND model = 'ECMWF'"
    ).fetchone()
    thr = con.execute('SELECT thr_attention, thr_api_alert, trigger_p3_edi FROM runs').fetchone()
    con.close()
    assert leads == {'observado': 0, 'previsão': 1}
    assert br386 == (1, 1)  # only municipality B is on BR-386, at Watch
    assert thr == (1.25, 128.0, 60.0)
    forecast_db.ingest(run_dir)  # re-ingesting the same run replaces its rows
    assert _counts(archive) == counts


def test_verification_pairs_a_forecast_with_the_later_observed_day(archive, tmp_path):
    forecast_db.ingest(_run_folder(tmp_path / 'runs', '20261120T200000Z', '2026-11-20', fc_level=1))
    forecast_db.ingest(_run_folder(tmp_path / 'runs', '20261121T200000Z', '2026-11-21', obs_level=2))
    con = sqlite3.connect(archive)
    rows = con.execute(
        "SELECT DISTINCT run_id, date, lead_days, fc_level, obs_level FROM verification WHERE date = '2026-11-21'"
    ).fetchall()
    con.close()
    assert rows == [('20261120T200000Z', '2026-11-21', 1, 1, 2)]


def test_check_archive_accepts_growth_and_rejects_loss_or_damage(archive, tmp_path):
    forecast_db.ingest(_run_folder(tmp_path / 'runs', '20261120T200000Z', '2026-11-20'))
    before = tmp_path / 'before.sqlite'
    shutil.copy(archive, before)
    forecast_db.ingest(_run_folder(tmp_path / 'runs', '20261121T200000Z', '2026-11-21'))
    assert forecast_db.check_archive(before, archive) == []

    con = sqlite3.connect(archive)
    con.execute('DROP TABLE events')
    con.commit()
    con.close()
    assert forecast_db.check_archive(before, archive) == ['table events: 0 rows before, missing after']

    shutil.copy(before, tmp_path / 'emptied.sqlite')
    con = sqlite3.connect(tmp_path / 'emptied.sqlite')
    con.execute('DELETE FROM municipal')
    con.commit()
    con.close()
    assert forecast_db.check_archive(before, tmp_path / 'emptied.sqlite') == ['table municipal: 8 rows before, 0 after']

    truncated = tmp_path / 'truncated.sqlite'
    truncated.write_bytes(before.read_bytes()[:3000])
    assert 'not a readable SQLite database' in forecast_db.check_archive(before, truncated)[0]
    assert 'file not found' in forecast_db.check_archive(before, tmp_path / 'absent.sqlite')[0]


# ---------------------------------------------------------------- dashboard pages
@pytest.mark.parametrize('page', ['page_forecast', 'page_study'])
@pytest.mark.parametrize('lang', ['pt', 'en'])
def test_dashboard_page_renders_without_errors(page, lang):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_string(f'from floodwatch import {page}\n{page}.render()\n', default_timeout=120)
    at.session_state['lang'] = lang
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert len(at.markdown) > 10  # the page drew its content, not just an early return


@pytest.mark.parametrize('lang', ['pt', 'en'])
def test_forecast_page_models_indices_and_windows(lang):
    """API is the default index; every offered model and both indices render; selector labels carry the 30-day
    event hit rate or the 'accumulating' mark; the accuracy cards and the detail section are drawn."""
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_string('from floodwatch import page_forecast\npage_forecast.render()\n', default_timeout=300)
    at.session_state['lang'] = lang
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.radio(key='_ix').value == 'API' and at.radio(key='_ix').options[0] == 'API'
    views = at.radio(key='_view')
    assert views.value == 'ECMWF' and views.options[:3][0].startswith('ECMWF')
    assert all(o.endswith('%') or o.endswith('⏳') for o in views.options)  # 30-day event hit rate, or accumulating
    text = ' '.join(m.value for m in at.markdown)
    assert ('acerto em eventos · D+1–D+3 · 30 d' if lang == 'pt' else 'event hit rate · D+1–D+3 · 30 d') in text
    assert ('Acerto dos modelos em detalhe' if lang == 'pt' else 'Model accuracy in detail') in text
    assert ('Situação atual e histórico' if lang == 'pt' else 'Current status and historical record') in text
    prefix = {'GFS': 'GFS ', 'consensus': 'Consens', 'ECMWF ENS': 'ECMWF ENS ', 'GEFS': 'GEFS '}
    offered = [v for v, p in prefix.items() if any(o.startswith(p) for o in views.options)]
    assert offered[:2] == ['GFS', 'consensus']  # the ensembles are offered when the run published their probabilities
    for v in offered:
        at.radio(key='_view').set_value(v).run()
        assert not at.exception, (v, [e.value for e in at.exception])
    at.radio(key='_ix').set_value('EDI').run()
    assert not at.exception, [e.value for e in at.exception]
    for w in ('common', 'all'):
        at.radio(key='_accwin').set_value(w).run()
        assert not at.exception, (w, [e.value for e in at.exception])
