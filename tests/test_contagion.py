"""Every test checks against a known answer. Run: python -m pytest  (or python tests/test_contagion.py)"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from contagion.core import (cholesky_fevd, connectedness, gfevd, ma_coefs, rolling_total, select_lag,
                            simulate_var, spillover, var_fit)
from contagion.data import load_bundled, returns, weekly_log_vol


def test_gfevd_closed_form_no_dynamics():
    """No lags, shocks correlated rho: theta_12 = rho^2 / (1 + rho^2) at every horizon."""
    for rho in (0.0, 0.3, 0.6, 0.9):
        for s1, s2 in ((1.0, 1.0), (1.0, 2.0), (3.0, 0.5)):           # unequal variances must not matter
            S = np.array([[s1 * s1, rho * s1 * s2], [rho * s1 * s2, s2 * s2]])
            th = gfevd([np.zeros((2, 2))], S, H=10)
            assert np.isclose(th[0, 1], rho ** 2 / (1 + rho ** 2)) and np.isclose(th[1, 0], th[0, 1])


def test_ma_coefficients_are_powers_for_var1():
    A = np.array([[0.5, 0.1], [0.2, 0.3]])
    P = ma_coefs([A], 6)
    assert max(np.abs(P[h] - np.linalg.matrix_power(A, h)).max() for h in range(6)) < 1e-15


def test_generalized_equals_cholesky_when_shocks_uncorrelated():
    A = [np.array([[0.2, 0.3, 0.0], [0.0, 0.1, 0.4], [0.1, 0.0, 0.3]])]
    S = np.diag([1.0, 2.0, 0.5])
    assert np.abs(gfevd(A, S) - cholesky_fevd(A, S)).max() < 1e-14


def test_var_ols_recovers_coefficients_and_lag():
    A = [np.array([[0.3, 0.1, 0.0], [0.0, 0.2, 0.1], [0.2, 0.0, 0.1]]),
         np.array([[0.2, 0.0, 0.0], [0.0, -0.2, 0.0], [0.0, 0.1, 0.2]])]
    Y = simulate_var(A, np.eye(3), 30000, seed=2)
    Ah, Sh = var_fit(Y, 2)
    assert max(np.abs(Ah[k] - A[k]).max() for k in range(2)) < 0.02 and np.abs(Sh - np.eye(3)).max() < 0.03
    assert select_lag(Y) == 2


def test_recovers_known_contagion_network():
    """Oil and ruble shocks feed the tenge, nothing feeds back. True network computed exactly from the model."""
    A = [np.array([[0.1, 0.0, 0.0], [0.0, 0.1, 0.0], [0.3, 0.3, 0.1]])]
    S = np.array([[1.0, 0.2, 0.0], [0.2, 1.0, 0.0], [0.0, 0.0, 1.0]])
    true = connectedness(gfevd(A, S))
    for seed in range(3):
        est = spillover(simulate_var(A, S, 20000, seed=seed), p=1)
        assert abs(est["total"] - true["total"]) < 1.5 and np.abs(est["net"] - true["net"]).max() < 1.5, seed
        assert est["net"][2] < 0 and est["net"][0] > 0 and est["net"][1] > 0   # tenge receives


def test_connectedness_accounting():
    rng = np.random.default_rng(0)
    th = rng.random((4, 4))
    th /= th.sum(1, keepdims=True)
    c = connectedness(th)
    assert np.isclose(c["net"].sum(), 0) and np.isclose(c["total"], c["from_"].mean())
    assert np.isclose(c["total"], c["to"].mean()) and np.allclose(c["pairwise"], -c["pairwise"].T)


def test_generalized_fevd_does_not_depend_on_variable_order():
    Y = simulate_var([np.array([[0.2, 0.1, 0.0], [0.1, 0.2, 0.1], [0.0, 0.2, 0.3]])],
                     np.array([[1, 0.4, 0.2], [0.4, 1, 0.3], [0.2, 0.3, 1.0]]), 5000, seed=4)
    a = spillover(Y, p=1)
    perm = [2, 0, 1]
    b = spillover(Y[:, perm], p=1)
    assert np.isclose(a["total"], b["total"]) and np.allclose(a["net"][perm], b["net"])


def test_rolling_uses_only_past_data():
    Y = simulate_var([np.eye(3) * 0.2], np.eye(3), 600, seed=5)
    Z = Y.copy()
    Z[400:] *= 3.0
    e1, t1, _ = rolling_total(Y, window=200, p=1, step=10)
    e2, t2, _ = rolling_total(Z, window=200, p=1, step=10)
    keep = e1 < 400
    assert np.allclose(t1[keep], t2[keep]) and not np.allclose(t1[~keep], t2[~keep])


def test_real_oil_and_commodity_currencies():
    """Bundled EIA Brent + Fed H.10 rates, 2000-2026. Facts that must hold on real data."""
    P = load_bundled()
    W = returns(P, "W-FRI")
    c = spillover(W.values, names=list(W.columns))
    assert 30 < c["total"] < 60 and np.isclose(c["net"].sum(), 0, atol=1e-9)
    assert 20 < spillover(weekly_log_vol(P).values)["total"] < 50
    ends, tot, _ = rolling_total(W.values, window=104, p=1)
    year = W.index[ends].year
    assert tot[(year >= 2009) & (year <= 2012)].mean() > tot[(year >= 2003) & (year <= 2006)].mean() + 15


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok  ", name)
