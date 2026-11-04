"""Focused tests for the rules that the published numbers depend on."""
import numpy as np
import pandas as pd
import pytest

from floodwatch import indices, merge_cube, rules, stats, study
from floodwatch.forecast import basin_mean, daily_12utc
from floodwatch.upstream import upstream_mask


# ---------------------------------------------------------------- statistics
def test_frac_at_or_above_matches_brute_force():
    rng = np.random.default_rng(1)
    v, w = rng.normal(size=500), rng.integers(0, 4, 500).astype(float)
    thr = np.array([-1.0, 0.0, 0.3, v[10], 5.0])
    fast = stats.frac_at_or_above(v, w, thr)
    brute = np.array([(w * (v >= t)).sum() / w.sum() for t in thr])
    assert np.allclose(fast, brute)


def test_tss_and_auc_basic():
    pos, neg = np.array([3.0, 4.0]), np.array([0.0, 1.0, 2.0, 3.0])
    pod, pofd = stats.contingency(pos, neg, np.array([3.0]))
    assert pod[0] == 1.0 and pofd[0] == 0.25
    assert stats.auc(pos, neg) == pytest.approx((4 + 3.5) / 8)


def test_block_bootstrap_resamples_whole_blocks():
    df = pd.DataFrame({'label': [1, 1, 1, 0, 0, 0, 0], 'block': ['E1', 'E1', 'E2', 'M1', 'M1', 'M2', 'M2']})
    W = stats.BlockBootstrap(df, n=50)
    for b in range(W.n):
        w = W[b]
        assert w[0] == w[1] and w[3] == w[4] and w[5] == w[6]   # rows of one block always move together
        assert w[0] + w[2] == 2 and w[3] + w[5] == 2             # two blocks drawn per class
    mask = np.array([True] * 3 + [False] * 4)
    assert np.array_equal(W.subset(mask)[0], W[0][:3])


# ---------------------------------------------------------------- events and calendar
def test_chain_events_uses_previous_record_and_episodes():
    rec = pd.DataFrame({'codarea': ['A', 'A', 'A', 'A', 'B'],
                        'date': pd.to_datetime(['2020-01-01', '2020-01-06', '2020-01-12', '2020-02-01', '2020-01-03'])})
    ev = study.chain_events(rec, dedup_days=7, episode_gap=5)
    # A: 01-01, 01-06 (5 d), 01-12 (6 d from previous) -> one event; 02-01 new event. B separate municipality.
    assert sorted(ev[ev.codarea == 'A'].date.dt.strftime('%m-%d')) == ['01-01', '02-01']
    assert ev.loc[ev.codarea == 'B', 'episode_id'].iloc[0] == ev.loc[ev.date == '2020-01-01', 'episode_id'].iloc[0]


def test_daily_12utc_window_and_completeness():
    t = pd.date_range('2026-01-01 13:00', '2026-01-03 12:00', freq='h', tz='UTC')
    s = pd.Series(1.0, index=t)
    d = daily_12utc(s)
    assert list(d.index.strftime('%Y-%m-%d')) == ['2026-01-02', '2026-01-03'] and (d == 24).all()
    d2 = daily_12utc(s.iloc[1:])  # first window misses one hour
    assert np.isnan(d2.loc['2026-01-02'])


# ---------------------------------------------------------------- operational rule
def test_levels_never_report_normal_without_data_and_trigger_only_lifts_to_watch():
    rule = rules.Rule('EDI', attention=1.25, alert=3.37, trigger_p3_mm=60.0)
    edi = np.array([np.nan, 0.0, 0.0, 1.3, 3.5, np.nan])
    p3 = np.array([10.0, 10.0, 80.0, 10.0, 80.0, 90.0])
    assert list(rules.classify(edi, p3, rule)) == [-1, 0, 1, 1, 2, -1]
    assert list(rules.classify(edi, p3, rule, use_trigger=False)) == [-1, 0, 0, 1, 2, -1]


def test_run_rules_reads_old_and_new_metadata():
    new = {'rules': {'EDI': {'index': 'EDI', 'attention': 1.0, 'alert': 3.0, 'trigger_p3_mm': 60.0}}}
    old = {'thresholds': {'predictor': 'EDI', 'attention': 1.25, 'alert': 3.37},
           'thresholds_api': {'predictor': 'API', 'attention': 72.0, 'alert': 128.0}}
    assert rules.run_rules(new) == new['rules']
    assert set(rules.run_rules(old)) == {'EDI', 'API'} and rules.run_rules(old)['API']['attention'] == 72.0


# ---------------------------------------------------------------- upstream basins and forecast aggregation
def _digits(*codes):
    width = max(map(len, codes))
    return np.array([[int(c) for c in s] + [-1] * (width - len(s)) for s in codes])


def test_pfafstetter_upstream_rule():
    codes = ['7963', '7965', '7964', '7969', '7971', '7962', '79631']
    d = _digits(*codes)
    up = dict(zip(codes, upstream_mask(d, d[0])))
    assert up == {'7963': True, '7965': True, '7964': True, '7969': True, '7971': False, '7962': False, '79631': True}
    # a coastal / lagoon interbasin (no even digit) has nothing upstream but itself
    coast = ['795997', '795999', '86', '79612']
    d = _digits(*coast)
    assert list(upstream_mask(d, d[0])) == [True, False, False, False]


def test_basin_mean_is_area_weighted_and_never_fills_gaps():
    rain = pd.DataFrame({'p0': [10.0, 10.0], 'p1': [0.0, np.nan]}, index=pd.to_datetime(['2026-01-01', '2026-01-02']))
    w = pd.DataFrame({'codarea': ['A', 'A'], 'point': ['p0', 'p1'], 'area': [3.0, 1.0]})
    out = basin_mean(rain, w)
    assert out.A.iloc[0] == pytest.approx(7.5) and np.isnan(out.A.iloc[1])


# ---------------------------------------------------------------- data and indices
def test_merge_crop_covers_rio_grande_do_sul():
    lat, lon = merge_cube.LAT[merge_cube.IY], merge_cube.LON[merge_cube.IX]
    assert lat.min() <= -33.7 and lat.max() >= -27.1 and lon.min() <= -57.6 and lon.max() >= -49.7


def test_edi_calibration_must_precede_analysis():
    days = pd.date_range('1998-01-01', '2001-12-31')
    rain = pd.Series(np.random.default_rng(0).gamma(0.5, 6, len(days)), index=days)
    with pytest.raises(ValueError):
        indices.compute(rain, 1999, 2001, '2001-06-01')


def test_api_is_the_library_recursion_and_propagates_gaps():
    days = pd.date_range('2000-01-01', periods=5)
    rain = pd.Series([10.0, 0.0, 5.0, np.nan, 1.0], index=days)
    api = indices.api(rain, k=0.9)
    assert api[:3] == pytest.approx([10.0, 9.0, 13.1])
    assert np.isnan(api[3:]).all()   # a missing day never becomes zero rain


def test_study_keeps_indices_module_reachable():
    # regression: a function named `indices` once shadowed the module and broke `--stage data`
    assert callable(study.indices.compute) and callable(study.compute_indices)
