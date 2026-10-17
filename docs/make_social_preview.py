"""Social preview image (1280 x 640) for the repository page and link cards.

    python docs/make_social_preview.py docs/social_preview.png    (needs data/kz_prices.csv: scripts/fetch_kz.py)
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from contagion.core import spillover  # noqa: E402
from contagion.data import returns  # noqa: E402

P = pd.read_csv(os.path.join(ROOT, "data", "kz_prices.csv"), index_col=0, parse_dates=True)
Y = returns(P[P.index >= "2015-08-20"], "W-FRI")
c = spillover(Y.values, names=list(Y.columns))
i = c["names"].index("KZT")
sh = c["theta"][i] * 100
label = {"RUB": "Russian ruble", "EEM": "EM equities", "USD": "US dollar", "Brent": "Brent oil", "KASE": "KASE index"}
others = sorted([(sh[j], label[n]) for j, n in enumerate(c["names"]) if j != i])

INK, MUTED, BLUE, GRID = "#0b0b0b", "#52514e", "#2a78d6", "#e4e3df"
fig = plt.figure(figsize=(12.8, 6.4), dpi=100, facecolor="white")
fig.text(0.06, 0.82, "TENGE CONTAGION", fontsize=15, color=BLUE, weight="bold")
for k, line in enumerate([f"{100 - sh[i]:.0f}% of the tenge's", "weekly swings come", "from other markets"]):
    fig.text(0.06, 0.68 - 0.095 * k, line, fontsize=34, color=INK, weight="bold")
fig.text(0.06, 0.36, "Where it comes from: share of USD/KZT forecast variance,\nweekly returns, Aug 2015 to Oct 2026",
         fontsize=14, color=MUTED, va="top", linespacing=1.4)
fig.text(0.06, 0.12, "Diebold-Yilmaz connectedness on official data\ngithub.com/aidaman01/tenge-contagion",
         fontsize=13, color=MUTED, linespacing=1.5)
ax = fig.add_axes([0.70, 0.14, 0.23, 0.62])
v = [s for s, _ in others]
ax.barh(range(len(v)), v, height=0.6, color=BLUE)
for y, s in enumerate(v):
    ax.annotate(f"{s:.1f}%", (s, y), xytext=(6, 0), textcoords="offset points", va="center", fontsize=15, color=INK)
ax.set_yticks(range(len(v)), [n for _, n in others], fontsize=15, color=INK)
ax.tick_params(axis="y", length=0)
ax.set_xlim(0, max(v) * 1.35)
ax.xaxis.set_visible(False)
ax.spines[["top", "right", "bottom"]].set_visible(False)
ax.spines["left"].set_color(GRID)
fig.savefig(sys.argv[1], dpi=100, facecolor="white")
