import numpy as np
import pandas as pd

from floodwatch import ensemble, forecast


def test_member_index_table_matches_operational_on_recent_days():
    """The truncated-API table equals forecast.index_table on the last days (where forecasts sit)."""
    idx = pd.date_range('1998-01-01', '2026-11-30')
    rng = np.random.default_rng(0)
    rain = pd.DataFrame({'4300001': rng.gamma(0.4, 10, len(idx)), '4300002': rng.gamma(0.3, 12, len(idx))}, index=idx)
    full = forecast.index_table(rain)
    fast = ensemble.member_index_table(rain)
    last = idx[-30]
    a = full[full.date >= last].reset_index(drop=True)
    b = fast[fast.date >= last].reset_index(drop=True)
    for col in ('EDI', 'API', 'P3', 'P1'):
        np.testing.assert_allclose(a[col].to_numpy(float), b[col].to_numpy(float), rtol=1e-9, atol=1e-9)
