"""Build data/kz_prices.csv: daily prices for the Kazakhstan contagion network, and print data checks.

    python scripts/fetch_kz.py

Columns (all in US dollars or per US dollar, so a rise in KZT/RUB means the currency weakens):
  KZT    USD/KZT official rate, National Bank of Kazakhstan (nationalbank.kz)
  RUB    USD/RUB official rate, Bank of Russia (cbr.ru XML_dynamic, R01235)
  Brent  Brent spot, U.S. Energy Information Administration (bundled data/brent-daily.csv)
  USD    Nominal broad U.S. dollar index, Federal Reserve Board H.10, via FRED (DTWEXBGS)
  EEM    iShares MSCI Emerging Markets ETF, dividend-adjusted close, Yahoo Finance
  KASE   KASE share index close, Kazakhstan Stock Exchange (kase.kz archive)

The CSV is not committed: Yahoo and KASE terms do not allow redistribution. Run this script to rebuild it.
"""
import io
import os
import sys

import numpy as np
import pandas as pd
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from contagion.data import DATA, parse_cbr, parse_kase_xlsx, parse_nbk, to_trade_date  # noqa: E402

START, END = pd.Timestamp("2006-01-01"), pd.Timestamp.today().normalize()


def get(url, **params):
    r = requests.get(url, params=params, timeout=120)   # default header: FRED drops browser-like ones
    r.raise_for_status()
    return r


def nbk():
    r = get("https://nationalbank.kz/ru/exchangerates/ezhednevnye-oficialnye-rynochnye-kursy-valyut/report",
            **{"rates[]": 5, "beginDate": f"{START:%d.%m.%Y}", "endDate": f"{END:%d.%m.%Y}"})
    return parse_nbk(r.text)


def cbr():
    params = dict(date_req1=f"{START:%d/%m/%Y}", date_req2=f"{END:%d/%m/%Y}", VAL_NM_RQ="R01235")
    try:
        r = get("https://www.cbr.ru/scripts/XML_dynamic.asp", **params)
    except requests.exceptions.SSLError:          # cbr.ru refuses TLS from some networks; same file over http
        print("cbr.ru: https handshake failed, using http")
        r = get("http://www.cbr.ru/scripts/XML_dynamic.asp", **params)
    return parse_cbr(r.content)


def brent():
    s = pd.read_csv(os.path.join(DATA, "brent-daily.csv"), parse_dates=["Date"]).set_index("Date")["Price"]
    return s.rename("Brent")


def fred_dollar():
    r = get("https://fred.stlouisfed.org/graph/fredgraph.csv", id="DTWEXBGS")
    s = pd.read_csv(io.StringIO(r.text), index_col=0, parse_dates=True, na_values=".").iloc[:, 0]
    return s.dropna().rename("USD")


def eem():
    import yfinance as yf
    d = yf.download("EEM", start=f"{START:%Y-%m-%d}", auto_adjust=True, progress=False)
    s = d["Close"].iloc[:, 0] if isinstance(d.columns, pd.MultiIndex) else d["Close"]
    s.index = s.index.tz_localize(None)
    return s.dropna().rename("EEM")


def kase():
    r = get("https://kase.kz/api/indicators/index-kase/archive-xls/",
            start_date=f"{START:%Y-%m-%d}", end_date=f"{END:%Y-%m-%d}")
    return parse_kase_xlsx(r.content)


def check(s):
    """First/last date, observations, longest gap (business days), share of zero-change days,
    and the largest moves (log returns, flagged if beyond 8 robust standard deviations)."""
    s = s[s.index >= START]
    s = s[s.index.dayofweek < 5]
    r = np.log(s).diff().dropna()
    gaps = np.diff(np.searchsorted(pd.bdate_range(s.index[0], s.index[-1]), s.index))
    g = int(gaps.argmax())
    sd = 1.4826 * np.median(np.abs(r - r.median()))
    big = r.abs().sort_values(ascending=False).head(3)
    return dict(name=s.name, first=s.index[0].date(), last=s.index[-1].date(), n=len(s),
                gap=f"{gaps[g] - 1} ({s.index[g].date()})", zero=f"{(r == 0).mean() * 100:.1f}%",
                outliers=int((r.abs() > 8 * sd).sum()),
                top=", ".join(f"{d.date()} {r[d] * 100:+.1f}%" for d in big.index))


def main():
    raw = {"KZT": to_trade_date(nbk()), "RUB": to_trade_date(cbr()), "Brent": brent(), "USD": fred_dollar(),
           "EEM": eem(), "KASE": kase()}
    print("\nRaw series (weekdays; NBK and Bank of Russia moved to the trading day):")
    rows = [check(s.rename(k)) for k, s in raw.items()]
    print(pd.DataFrame(rows).set_index("name").to_string())

    # Holidays differ across markets: carry a price over at most 2 days, so a longer outage (NBK publishes
    # nothing for 2023-07-28..08-28) leaves missing weeks instead of flat ones. End where every series ends.
    P = pd.concat(raw, axis=1, sort=True)
    P = P[(P.index >= START) & (P.index.dayofweek < 5)].ffill(limit=2).dropna()
    P = P[P.index <= min(s.index[-1] for s in raw.values())]
    out = os.path.join(DATA, "kz_prices.csv")
    P.round(6).to_csv(out, index_label="Date")
    print(f"\n{out}: {len(P)} weekdays, {P.index[0].date()} to {P.index[-1].date()}")


if __name__ == "__main__":
    main()
