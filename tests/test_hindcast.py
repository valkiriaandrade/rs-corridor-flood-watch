import numpy as np

from floodwatch.hindcast import quantile_map


def test_quantile_map_identity_and_bias():
    rng = np.random.default_rng(1)
    obs = rng.gamma(0.5, 10, 20000)
    same = quantile_map(obs, obs)
    np.testing.assert_allclose(same(np.quantile(obs, [0.5, 0.9])), np.quantile(obs, [0.5, 0.9]), rtol=1e-9)
    wet = quantile_map(obs * 1.5, obs)          # forecast 50 % too wet
    x = np.quantile(obs * 1.5, [0.6, 0.95])
    np.testing.assert_allclose(wet(x), x / 1.5, rtol=0.02)
    assert (wet(np.array([0.0, 1e6])) >= 0).all()
