"""0.5 vs 0.25 degree basin-rainfall check (floodwatch.grid_check): rain statistics, level agreement and the criterion
stated in the decision log."""

import numpy as np
import pandas as pd
import pytest

from floodwatch import grid_check as G


def test_rain_stats_bias_spread_and_missing_pairs():
    fine = [10.0, 0.0, 20.0, 30.0, np.nan]
    coarse = [11.0, 1.0, 18.0, 33.0, 5.0]  # the last pair is dropped
    s = G.rain_stats(coarse, fine)
    assert s['n'] == 4
    assert s['bias_mm'] == pytest.approx(0.75)  # (1 + 1 - 2 + 3) / 4
    assert s['relative_bias'] == pytest.approx(3 / 60)
    assert s['mean_abs_diff_mm'] == pytest.approx(7 / 4)
    assert s['p95_abs_diff_mm'] == pytest.approx(np.quantile([1, 1, 2, 3], 0.95))
    assert s['correlation'] == pytest.approx(np.corrcoef([11, 1, 18, 33], [10, 0, 20, 30])[0, 1])


def test_level_agreement_and_confusion():
    fine = [0, 0, 0, 1, 2, 2, np.nan]
    coarse = [0, 0, 1, 1, 1, 2, 0]
    a = G.level_agreement(coarse, fine)
    assert a['n'] == 6 and a['agreement'] == pytest.approx(4 / 6)
    t = a['confusion_fine_rows_coarse_cols']
    assert t['Normal'] == {'Normal': 2, 'Watch': 1, 'Warning': 0}
    assert t['Warning'] == {'Normal': 0, 'Watch': 1, 'Warning': 1}
    assert sum(sum(r.values()) for r in t.values()) == 6
    # days at Watch or above on either grid: rows 3-6 -> 2 of 4 agree
    assert a['alert_days'] == 4 and a['agreement_on_alert_days'] == pytest.approx(0.5)


def test_criterion_needs_both_agreement_and_bias():
    assert G.passes({'relative_bias': 0.10}, 0.90)
    assert G.passes({'relative_bias': -0.05}, 0.97)
    assert not G.passes({'relative_bias': 0.11}, 0.99)
    assert not G.passes({'relative_bias': 0.0}, 0.89)


def test_basin_rain_uses_each_grids_points(monkeypatch):
    def grid(step):
        if step == 0.5:
            return (
                pd.DataFrame({'point': ['p0'], 'lat': [-30.0], 'lon': [-51.0]}),
                pd.DataFrame({'codarea': ['A'], 'point': ['p0'], 'area': [4.0]}),
            )
        return (
            pd.DataFrame({'point': ['p0', 'p1'], 'lat': [-30.0, -30.25], 'lon': [-51.0, -51.0]}),
            pd.DataFrame({'codarea': ['A', 'A'], 'point': ['p0', 'p1'], 'area': [1.0, 3.0]}),
        )

    monkeypatch.setattr(G.upstream, 'forecast_grid', grid)
    rain = pd.DataFrame({'-30.00,-51.00': [8.0], '-30.25,-51.00': [4.0]}, index=pd.to_datetime(['2026-11-10']))
    assert G.basin_rain(rain, 0.5).loc['2026-11-10', 'A'] == pytest.approx(8.0)
    assert G.basin_rain(rain, 0.25).loc['2026-11-10', 'A'] == pytest.approx((8 * 1 + 4 * 3) / 4)
