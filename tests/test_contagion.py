"""Every test checks against a known answer. Run: python -m pytest  (or python tests/test_contagion.py)"""
import io
import os
import sys
import zipfile

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from contagion.core import (cholesky_fevd, connectedness, gfevd, ma_coefs, rolling_total, select_lag,
                            simulate_var, spillover, var_fit)
from contagion.data import (load_bundled, parse_cbr, parse_kase_xlsx, parse_nbk, returns, to_trade_date,
                            weekly_log_vol)


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


def test_official_source_parsers_and_trade_dates():
    """Snippets in each source's format (no network). Rates per unit; official stamps move to the trading day."""
    nbk = parse_nbk('<tr>\n\t<td class="text-center" style="width: 120px;">2015-08-21</td>\n\t\t'
                    '<td class="text-center">1</td>\n<td class="text-center">255.26</td></tr>')
    assert nbk.to_dict() == {pd.Timestamp("2015-08-21"): 255.26}
    cbr = parse_cbr('<?xml version="1.0" encoding="windows-1251"?><ValCurs ID="R01235">'
                    '<Record Date="25.02.2022" Id="R01235"><Nominal>10</Nominal><Value>869,288</Value></Record>'
                    '</ValCurs>'.encode("cp1251"))
    assert np.isclose(cbr[pd.Timestamp("2022-02-25")], 86.9288)
    sheet = ('<worksheet><sheetData><row r="2"><c r="A2" t="inlineStr"><is><t>Дата</t></is></c></row>'
             '<row r="3"><c r="A3" t="inlineStr"><is><t>16.10.26</t></is></c><c r="B3" t="inlineStr"><is>'
             '<t>7830.68</t></is></c><c r="E3" t="inlineStr"><is><t>7862.65</t></is></c></row></sheetData></worksheet>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    assert parse_kase_xlsx(buf.getvalue()).to_dict() == {pd.Timestamp("2026-10-16"): 7862.65}
    stamps = pd.Series([1.0, 2.0, 3.0, 4.0], pd.to_datetime(["2022-02-25", "2022-02-26", "2022-02-27", "2022-02-28"]))
    moved = to_trade_date(stamps)                    # Fri, Sat stamps -> Thu, Fri; Sun, Mon repeat Sat: dropped
    assert moved.to_dict() == {pd.Timestamp("2022-02-24"): 1.0, pd.Timestamp("2022-02-25"): 2.0}


def test_cli_start_focus_and_logvol():
    """CLI on a synthetic price CSV: --start trims the sample; --focus shares of the market's variance sum to 100%."""
    import contextlib, re, tempfile
    from contagion.__main__ import main
    r = simulate_var([np.array([[0.1, 0.0, 0.0], [0.0, 0.1, 0.0], [0.3, 0.3, 0.1]])], np.eye(3), 2000, seed=6)
    P = pd.DataFrame(np.exp(np.cumsum(r * 0.01, axis=0)), pd.bdate_range("2012-01-02", periods=2000),
                     ["OIL", "RUB", "KZT"])
    argv = sys.argv
    with tempfile.TemporaryDirectory() as d:
        P.to_csv(os.path.join(d, "p.csv"))
        for measure in ("returns", "logvol"):
            sys.argv = ["contagion", "--csv", os.path.join(d, "p.csv"), "--start", "2015-01-01", "--focus", "KZT",
                        "--measure", measure, "--window", "52", "--compare-window", "26",
                        "--out", os.path.join(d, "c.png")]
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                main()
            text = out.getvalue()
            assert text.startswith("\n2015-01-") and os.path.exists(os.path.join(d, "c.png"))
            shares = [float(x) for x in re.findall(r"^  \w+\s+([\d.]+)%", text, re.M)]
            assert len(shares) == 3 and abs(sum(shares) - 100) < 0.2
    sys.argv = argv


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok  ", name)
