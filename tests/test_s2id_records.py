"""Official S2iD records (floodwatch.s2id_records): protocol date parsing, registration lag, corridor membership,
pre-archive records, forecasts per model and alarms without a record. Small CSV fixture in the export's format."""

import pandas as pd
import pytest

from floodwatch import s2id_records as R, verification_summary as VS

HEADER = (
    'Ministério da Integração e do Desenvolvimento Regional\n'
    'Secretaria Nacional de Proteção e Defesa Civil \n'
    'Relatório Gerencial - Danos Informados\n'
    'Data Inicial: 27/09/2026 Data Final: 26/11/2026 UF: RS\n'
    'UF;Município;Registro;Protocolo;COBRADE;Status;População\n'
)
ROWS = [
    # corridor municipality A (4300001), event 24 Nov registered 25 Nov (lag 1)
    'RS;Alfa;25/11/2026;RS-F-4300001-12300-20261124;12300 - Alagamentos;Registro;100',
    # corridor municipality B, event 10 Oct (before the archive) registered 20 Oct (lag 10)
    'RS;Beta;20/10/2026;RS-F-4300002-13214-20261010;13214 - Tempestade Local/Convectiva - Chuvas Intensas;Registro;200',
    # outside the corridors, event 06 Nov registered 09 Nov (lag 3)
    'RS;Gama;09/11/2026;RS-F-4399999-12100-20261106;12100 - Inundações;Registro;300',
    # not a flood type (drought): left out
    'RS;Delta;09/11/2026;RS-F-4300001-14110-20261106;14110 - Estiagem;Registro;400',
    # malformed protocol: left out
    'RS;Épsilon;09/11/2026;RS-F-XXXX;12300 - Alagamentos;Registro;500',
]


@pytest.fixture
def export_csv(tmp_path):
    path = tmp_path / 'danos_informados_RS.csv'
    path.write_bytes((HEADER + '\n'.join(ROWS) + '\n').encode('cp1252'))
    return path


@pytest.fixture
def records(export_csv):
    return R.parse_export(export_csv)


def test_event_date_comes_from_the_protocol_not_the_registration(records):
    assert list(records.protocol) == [
        'RS-F-4300001-12300-20261124',
        'RS-F-4300002-13214-20261010',
        'RS-F-4399999-12100-20261106',
    ]  # drought and malformed protocol dropped
    a = records.iloc[0]
    assert (a.date, a.registered, a.codarea, a.cobrade, a.municipio) == (
        '2026-11-24',
        '2026-11-25',
        '4300001',
        '12300',
        'Alfa',
    )
    assert records.lag_days.tolist() == [1, 10, 3]
    assert R.lag_median(records) == 3.0
    assert R.lag_median(records.iloc[:0]) is None


UNITS = pd.DataFrame({'codarea': ['4300001', '4300002'], 'nome': ['Alfa', 'Beta'], 'corridors': ['116', '116/386']})
OBSERVED = pd.DataFrame(
    {
        'date': ['2026-11-24', '2026-11-24', '2026-10-10', '2026-10-10', '2026-11-20', '2026-11-20'],
        'codarea': ['4300001', '4300002', '4300001', '4300002', '4300001', '4300002'],
        'rain_mm': [40.0, 5.0, 1.0, 60.0, 0.0, 0.0],
        'P3': [80.0, 10.0, 2.0, 90.0, 0.0, 0.0],
        'level': [1, 0, 0, 2, 0, 0],
        'level_api': [2, 0, 0, 1, 0, 0],
    }
)


def _fc(model, date, code, lead, edi, api, run='r1', p=(None, None, None, None)):
    return {
        'run_id': run,
        'date': date,
        'lead_days': lead,
        'model': model,
        'codarea': code,
        'nome': '',
        'corridors': '',
        'fc_rain': 1.0,
        'obs_rain': 1.0,
        'fc_level': edi,
        'obs_level': 0,
        'fc_level_api': api,
        'obs_level_api': 0,
        'p_watch': p[0],
        'p_warning': p[1],
        'p_watch_api': p[2],
        'p_warning_api': p[3],
    }


@pytest.fixture
def vframe():
    rows = [
        _fc('ECMWF', '2026-11-24', '4300001', 1, 1, 2),  # hit at D+1 (EDI and API)
        _fc('ECMWF', '2026-11-24', '4300001', 2, 0, 1, run='r0'),
        _fc('GFS', '2026-11-24', '4300001', 1, 0, None),  # missed (EDI); no API forecast
        _fc('GEFS', '2026-11-24', '4300001', 1, 1, 1, p=(0.6, 0.1, 0.7, 0.2)),
        # alarms on other days: one next to a record (B on 20 Nov has none; A on 23 Nov is one day before A's record)
        _fc('ECMWF', '2026-11-23', '4300001', 1, 1, 1),
        _fc('ECMWF', '2026-11-20', '4300002', 1, 1, 1),
    ]
    return pd.DataFrame(rows, columns=VS.VCOLS)


@pytest.fixture
def built(records, vframe):
    return R.build(records, UNITS, OBSERVED, vframe, '2026-11-04', '2026-11-26')


def test_corridor_membership_and_counts_since_the_archive(built):
    assert built['since_archive'] == {'rs': 2, 'corridor': 1}  # Alfa (corridor) and Gama (outside); Beta is older
    state = {x['municipio']: x['in_corridor'] for x in built['statewide']}
    assert state == {'Alfa': True, 'Beta': True, 'Gama': False}
    assert [i['nome'] for i in built['corridor']] == ['Alfa', 'Beta']  # every corridor record, newest first


def test_lag_marks_the_recent_days(built):
    assert built['lag_days_median'] == 3.0 and built['recent_from'] == '2026-11-23'
    recent = {i['nome']: i['recent'] for i in built['corridor']}
    assert recent == {'Alfa': True, 'Beta': False}


def test_pre_archive_record_has_no_forecast_but_keeps_the_observed_rule(built):
    beta = next(i for i in built['corridor'] if i['nome'] == 'Beta')
    assert beta['archived'] is False and beta['forecast'] == {}
    assert beta['observed'] == {'rain_mm': 60.0, 'P3': 90.0, 'EDI': 2, 'API': 1}
    assert built['observed_rule']['EDI'] == {'records': 2, 'at_watch': 2}
    assert built['observed_rule']['API'] == {'records': 2, 'at_watch': 2}


def test_forecasts_per_model_lead_and_outcome(built):
    alfa = built['corridor'][0]
    assert alfa['forecast']['ECMWF']['1'] == {'EDI': 1, 'API': 2} and alfa['forecast']['ECMWF']['2']['API'] == 1
    assert alfa['outcome']['ECMWF'] == {'EDI': 'hit', 'API': 'hit'}
    assert alfa['outcome']['GFS'] == {'EDI': 'missed', 'API': None}  # no API forecast: out of the API counts
    assert alfa['forecast']['GEFS']['1']['p'] == {'EDI': [0.6, 0.1], 'API': [0.7, 0.2]}
    assert built['forecast_outcome']['GFS']['API'] == {'records': 0, 'hits': 0}
    assert built['forecast_outcome']['ECMWF']['EDI'] == {'records': 1, 'hits': 1}


def test_alarms_without_a_record_within_one_day(built):
    # ECMWF EDI alarms: A 24 Nov (record that day), A 23 Nov (record one day later), B 20 Nov (no record)
    e = built['alarms_without_record']['ECMWF']['EDI']
    assert (e['alarms'], e['without_record']) == (3, 1) and e['share'] == pytest.approx(1 / 3)
    assert 'EDI' not in built['alarms_without_record']['GFS']  # GFS had no alarm


def test_preliminary_reports_count_as_records(records, vframe):
    pre = pd.DataFrame({'date': ['2026-11-21'], 'codarea': ['4300002']})
    out = R.build(records, UNITS, OBSERVED, vframe, '2026-11-04', '2026-11-26', pre)
    assert out['alarms_without_record']['ECMWF']['EDI']['without_record'] == 0


def test_base_rate_over_all_corridor_municipality_days(built):
    # every observed corridor municipality-day (6), not only the record days: 2 at Watch or above for each index
    b = built['observed_base_rate']
    assert (b['from'], b['to']) == ('2026-10-10', '2026-11-24')
    assert b['EDI'] == {'municipality_days': 6, 'at_watch': 2, 'share': pytest.approx(1 / 3)}
    assert b['API'] == {'municipality_days': 6, 'at_watch': 2, 'share': pytest.approx(1 / 3)}


def test_base_rate_period_and_corridor_only():
    outside = pd.DataFrame({'date': ['2026-11-24'], 'codarea': ['4399999'], 'level': [2], 'level_api': [2]})
    obs = pd.concat([OBSERVED, outside], ignore_index=True).assign(
        level_api=lambda x: x.level_api.where(x.date != '2026-11-20')  # API missing on 20 Nov: left out of the API
    )
    b = R.base_rate(obs, UNITS.codarea, start='2026-11-01')
    assert (b['from'], b['to']) == ('2026-11-20', '2026-11-24')
    assert b['EDI'] == {'municipality_days': 4, 'at_watch': 1, 'share': 0.25}
    assert b['API'] == {'municipality_days': 2, 'at_watch': 1, 'share': 0.5}
    assert R.base_rate(obs.iloc[:0], UNITS.codarea)['API'] == {'municipality_days': 0, 'at_watch': 0, 'share': None}
