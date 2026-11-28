"""GloFAS files from the EWDS (floodwatch.glofas.discharge): valid time -> day of the 24-hour mean, longitudes
0..360 -> -180..180. Small synthetic NetCDF files in the downloaded layout."""

import numpy as np
import pandas as pd
import pytest

from floodwatch import glofas as G

xr = pytest.importorskip('xarray')
pytest.importorskip('scipy')


def _year_file(path, first_valid, days, value):
    t = pd.date_range(first_valid, periods=days, freq='D')
    da = xr.DataArray(
        np.full((days, 2, 3), value, float),
        dims=('valid_time', 'latitude', 'longitude'),
        coords={'valid_time': t, 'latitude': [-29.0, -30.0], 'longitude': [309.95, 302.55, 306.0]},
        name='dis24',
    )
    da.to_dataset().to_netcdf(path, engine='scipy')  # NetCDF3: CI has no HDF5 writer


def test_days_and_longitudes(tmp_path, monkeypatch):
    # as served: the request for year Y returns valid times Y-01-02 .. (Y+1)-01-01
    _year_file(tmp_path / 'glofas_2023.nc', '2023-01-02', 365, 1.0)
    _year_file(tmp_path / 'glofas_2024.nc', '2024-01-02', 366, 2.0)
    monkeypatch.setattr(G, 'ARCHIVE', tmp_path)
    q = G.discharge()
    days = pd.to_datetime(q['time'].to_numpy())
    assert (days[0], days[-1]) == (pd.Timestamp('2023-01-01'), pd.Timestamp('2024-12-31'))
    assert len(days) == 731 and days.is_monotonic_increasing
    assert float(q.sel(time='2023-12-31').mean()) == 1.0  # valid 2024-01-01 00 UTC = mean of 31 Dec 2023
    assert float(q.sel(time='2024-01-01').mean()) == 2.0
    assert np.allclose(q['longitude'].to_numpy(), [-57.45, -54.0, -50.05])
