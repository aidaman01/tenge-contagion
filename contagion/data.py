"""Data: bundled public-domain series (EIA Brent, Federal Reserve H.10 exchange rates), and loaders for
Kazakhstan (National Bank of Kazakhstan USD/KZT, Bank of Russia USD/RUB) used on the user's machine."""
import io
import os
import re
import xml.etree.ElementTree as ET
import zipfile

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


# ---------- Kazakhstan network: parsers for official sources (downloaded by scripts/fetch_kz.py) ----------

def parse_nbk(html):
    """USD/KZT from the National Bank of Kazakhstan report page: rows of (date, units, rate), every calendar day."""
    rows = re.findall(r"<td[^>]*>(\d{4}-\d{2}-\d{2})</td>\s*<td[^>]*>(\d+)</td>\s*<td[^>]*>([\d.]+)</td>", html)
    s = pd.Series({pd.Timestamp(d): float(v) / int(q) for d, q, v in rows}, name="KZT")
    return s.sort_index()


def parse_cbr(xml_bytes):
    """Bank of Russia XML_dynamic: <Record Date="dd.mm.yyyy"><Nominal>..</Nominal><Value>12,34</Value>."""
    root = ET.fromstring(xml_bytes)
    s = pd.Series({pd.to_datetime(r.get("Date"), format="%d.%m.%Y"):
                   float(r.find("Value").text.replace(",", ".")) / int(r.find("Nominal").text)
                   for r in root.iter("Record")}, name="RUB")
    return s.sort_index()


def parse_kase_xlsx(xlsx_bytes):
    """KASE index archive (xlsx with inline strings): column A date dd.mm.yy, column E close."""
    sheet = zipfile.ZipFile(io.BytesIO(xlsx_bytes)).read("xl/worksheets/sheet1.xml").decode()
    out = {}
    for body in re.findall(r"<row [^>]*>(.*?)</row>", sheet):
        cells = dict(re.findall(r'<c r="([A-Z]+)\d+"[^>]*>(?:<is>)?<[tv]>([^<]*)</[tv]>', body))
        if re.fullmatch(r"\d{2}\.\d{2}\.\d{2}", cells.get("A", "")) and cells.get("E"):
            out[pd.to_datetime(cells["A"], format="%d.%m.%y")] = float(cells["E"])
    return pd.Series(out, name="KASE").sort_index()


def to_trade_date(s):
    """Official rates dated D (NBK, Bank of Russia) are set from the previous business day's exchange trading.
    Move each value to the day it was traded: keep Tuesday-Saturday stamps and shift them back one day
    (a Monday stamp repeats Saturday's rate)."""
    s = s[s.index.dayofweek.isin([1, 2, 3, 4, 5])]
    s.index = s.index - pd.Timedelta(days=1)
    return s
