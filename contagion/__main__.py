"""python -m contagion [--csv prices.csv] [--start DATE] [--measure returns|logvol] [--focus NAME]
                     [--window 104] [--out contagion.png]

Without --csv: bundled public-domain demo (Brent + oil and EM currencies, 2000-2026).
With --csv: a wide CSV of daily prices (first column dates, one column per market).
--focus: also print where that market's forecast variance comes from, and its pairwise net links."""
import argparse

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import FancyArrowPatch

from .core import rolling_total, spillover
from .data import load_bundled, returns, weekly_log_vol

INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"
SEND, RECV, BLUE = "#eb6834", "#2a78d6", "#2a78d6"
EVENTS = {"2008-09-15": "Lehman", "2014-11-28": "OPEC, oil crash", "2020-03-09": "COVID, oil war",
          "2022-02-24": "Russia sanctions"}


def report(c, label):
    print(f"\n{label}: total connectedness {c['total']:.1f}%  (VAR lag {c['lag']})")
    print(f"{'market':16}{'from others':>13}{'to others':>11}{'net':>8}")
    for i, n in enumerate(c["names"]):
        print(f"{n:16}{c['from_'][i]:>12.1f}%{c['to'][i]:>10.1f}%{c['net'][i]:>+8.1f}")


def report_focus(c, name):
    i = c["names"].index(name)
    print(f"\nwhere {name}'s forecast variance comes from, and pairwise net (+ = market transmits to {name}):")
    for j, n in enumerate(c["names"]):
        print(f"  {n:14}{c['theta'][i, j] * 100:>6.1f}%" + ("   (own)" if i == j else f"{c['pairwise'][j, i]:>+8.1f}"))


def report_events(t, tot, weeks=26):
    """Rolling total in the last window ending before each event, and its peak in the following weeks."""
    for d, lab in EVENTS.items():
        d = pd.Timestamp(d)
        if t[0] < d <= t[-1]:
            before = tot[t < d][-1]
            after = (t >= d) & (t < d + pd.Timedelta(weeks=weeks))
            k = np.flatnonzero(after)[tot[after].argmax()]
            print(f"  {lab:18} before {before:5.1f}%  peak within {weeks} weeks {tot[k]:5.1f}% ({t[k].date()})")


def draw_network(ax, c, min_link=1.0):
    """Nodes on a circle; arrow i->j where i transmits more to j than it receives (net pairwise)."""
    n = len(c["names"])
    ang = np.pi / 2 - 2 * np.pi * np.arange(n) / n
    xy = np.c_[np.cos(ang), np.sin(ang)]
    pw = c["pairwise"]
    big = max(np.abs(pw).max(), 1e-9)
    for i in range(n):
        for j in range(n):
            if pw[i, j] > min_link:
                ax.add_patch(FancyArrowPatch(xy[i], xy[j], arrowstyle="-|>", mutation_scale=12,
                                             lw=0.6 + 4 * pw[i, j] / big, color=MUTED, alpha=0.75,
                                             shrinkA=24, shrinkB=24, connectionstyle="arc3,rad=0.08"))
    for k, name in enumerate(c["names"]):
        net = c["net"][k]
        col = SEND if net > 0 else RECV
        ax.scatter(*xy[k], s=900 + 60 * abs(net), color=col, alpha=0.9, zorder=3, edgecolor="white", lw=2)
        ax.annotate(f"{name}\n{net:+.1f}", xy[k] * 1.47, ha="center", va="center", fontsize=9, color=INK)
    ax.set(xlim=(-1.8, 1.8), ylim=(-1.8, 1.8), aspect="equal")
    ax.axis("off")
    ax.set_title(f"Who infects whom (total {c['total']:.0f}%)\norange = net transmitter, blue = net receiver",
                 fontsize=10)


def main():
    ap = argparse.ArgumentParser(description="Diebold-Yilmaz contagion between markets.")
    ap.add_argument("--csv", help="wide CSV of daily prices: date column + one column per market")
    ap.add_argument("--freq", default="W-FRI", help="return frequency: W-FRI (default) or D")
    ap.add_argument("--start", help="first date to use, e.g. 2015-08-20")
    ap.add_argument("--measure", default="returns", choices=["returns", "logvol"],
                    help="returns (default) or weekly log volatility")
    ap.add_argument("--focus", help="market to break down, e.g. KZT")
    ap.add_argument("--window", type=int, default=104, help="rolling window in periods (104 weeks = 2 years)")
    ap.add_argument("--out", default="contagion.png")
    a = ap.parse_args()

    if a.csv:
        P = pd.read_csv(a.csv, index_col=0, parse_dates=True).dropna()
        title = f"Contagion between {', '.join(P.columns)}"
    else:
        P = load_bundled()
        title = "Contagion between oil and commodity currencies (EIA, Federal Reserve H.10)"
    if a.start:
        P = P[P.index >= a.start]
    Y = returns(P, a.freq) if a.measure == "returns" else weekly_log_vol(P)
    what = f"{a.freq} returns" if a.measure == "returns" else "weekly log volatilities"
    c = spillover(Y.values, names=list(Y.columns))
    report(c, f"{Y.index[0].date()} to {Y.index[-1].date()}, {len(Y)} {what}")
    if a.focus:
        report_focus(c, a.focus)
    ends, tot, net = rolling_total(Y.values, window=a.window, p=c["lag"])
    t = Y.index[ends]
    print(f"\nrolling total: min {tot.min():.1f}% ({t[tot.argmin()].date()}), max {tot.max():.1f}% ({t[tot.argmax()].date()})")
    report_events(t, tot)

    plt.rcParams.update({"font.size": 10, "axes.edgecolor": GRID, "axes.labelcolor": MUTED,
                         "xtick.color": MUTED, "ytick.color": MUTED, "text.color": INK})
    fig = plt.figure(figsize=(13, 5.8))
    ax1 = fig.add_axes([0.0, 0.0, 0.34, 0.80])
    ax2 = fig.add_axes([0.42, 0.10, 0.56, 0.70])
    draw_network(ax1, c)
    ax2.plot(t, tot, color=BLUE, lw=1.6)
    for d, lab in EVENTS.items():
        d = pd.Timestamp(d)
        if t[0] <= d <= t[-1]:
            ax2.axvline(d, color=GRID, lw=1.2, zorder=0)
            ax2.annotate(lab, (d, ax2.get_ylim()[1]), xytext=(3, -12), textcoords="offset points",
                         fontsize=8, color=MUTED, rotation=90, va="top")
    ax2.grid(color=GRID, lw=0.8)
    ax2.spines[["top", "right"]].set_visible(False)
    ax2.set(ylabel="total connectedness (%)", title=f"Contagion over time ({a.window}-period rolling window)")
    ax2.set_xlim(t[0], t[-1])
    fig.suptitle(title, x=0.01, y=0.98, ha="left", fontsize=12)
    fig.savefig(a.out, dpi=150, facecolor="white")
    print(f"chart -> {a.out}")


if __name__ == "__main__":
    main()
