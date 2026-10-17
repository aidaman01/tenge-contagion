"""Data: bundled public-domain series (EIA Brent, Federal Reserve H.10 exchange rates), and loaders for
Kazakhstan (National Bank of Kazakhstan USD/KZT, Bank of Russia USD/RUB) used on the user's machine."""
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data")


def load_bundled(countries=("Norway", "Canada", "Mexico", "Brazil", "South Africa"), start="2000-01-01"):
    """Daily Brent (USD/bbl) and USD exchange rates, inner-joined on common dates."""
    oil = pd.read_csv(os.path.join(DATA, "brent-daily.csv"), parse_dates=["Date"]).set_index("Date")["Price"]
    fx = pd.read_csv(os.path.join(DATA, "fx-daily.csv"), parse_dates=["Date"])
    fx = fx[fx["Country"].isin(countries)].pivot(index="Date", columns="Country", values="Exchange rate")
    df = pd.concat([oil.rename("Brent"), fx[list(countries)]], axis=1, join="inner")
    return df[df.index >= start].dropna()


def returns(prices, freq="D"):
    """Log returns at daily ("D") or weekly ("W-FRI", last price of each week) frequency."""
    p = prices if freq == "D" else prices.resample(freq).last()
    r = np.log(p).diff().dropna()
    return r[(r != 0).any(axis=1)]


def weekly_log_vol(prices):
    """Weekly realised volatility from daily log returns, in logs (Diebold-Yilmaz use log volatilities).
    Weeks where a series did not move at all (pegs, holidays) are dropped."""
    r = np.log(prices).diff().dropna()
    rv = (r ** 2).resample("W-FRI").sum()
    rv = rv[(rv > 0).all(axis=1)]
    return 0.5 * np.log(rv)
