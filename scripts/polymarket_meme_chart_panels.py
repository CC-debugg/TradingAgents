"""Extended chart panels for Polymarket + Meme dashboard outputs."""

from __future__ import annotations

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.dates as mdates
from matplotlib.colors import LinearSegmentedColormap
from scipy import stats

ACCENT = "#00D4FF"
GREEN = "#00FF88"
RED = "#FF4466"
GOLD = "#FFD700"
GRAY = "#7A8899"
BG = "#0D1117"
PBG = "#161B22"
AC = ["#00D4FF", "#FF8C00", "#CC44FF", "#00FF88", "#FF4466", "#FFD700", "#7A8899"]


def _style():
    plt.style.use("dark_background")
    plt.rcParams.update(
        {
            "font.family": "monospace",
            "axes.facecolor": PBG,
            "figure.facecolor": BG,
            "axes.edgecolor": GRAY,
            "xtick.color": GRAY,
            "ytick.color": GRAY,
            "axes.labelcolor": GRAY,
            "grid.color": "#1E2733",
            "grid.linestyle": "-",
            "grid.linewidth": 0.4,
        }
    )


def _sax(ax, title, ylabel=""):
    ax.set_title(title, color="white", fontsize=10, pad=7, fontweight="bold")
    ax.set_ylabel(ylabel, color=GRAY, fontsize=8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.grid(True, alpha=0.5)
    for sp in ax.spines.values():
        sp.set_edgecolor(GRAY)


def render_meme_analysis(
    prices: dict,
    asset_returns: dict,
    asset_metrics: dict,
    meme_names: list[str],
    path: str,
):
    """Meme-coin focused charts (normalized prices, vol, Sharpe bars, correlation)."""
    _style()
    fig = plt.figure(figsize=(22, 18), facecolor=BG)
    fig.suptitle(
        "MEME COINS ANALYSIS  ·  DOGE / SHIB / PEPE / WIF / BONK / UMA",
        fontsize=14,
        fontweight="bold",
        color=ACCENT,
        y=0.98,
    )
    gs = gridspec.GridSpec(3, 2, figure=fig, hspace=0.42, wspace=0.28, top=0.94, bottom=0.05)

    # 1) Rebased price index (100 at start)
    ax0 = fig.add_subplot(gs[0, :])
    for i, nm in enumerate(meme_names):
        if nm not in prices:
            continue
        p = prices[nm].dropna()
        if len(p) < 2:
            continue
        idx = (p / p.iloc[0]) * 100
        ax0.plot(idx.index, idx, color=AC[i % len(AC)], lw=1.2, alpha=0.9, label=nm)
    ax0.axhline(100, color=GRAY, lw=0.5, alpha=0.6)
    ax0.legend(loc="upper left", fontsize=8, facecolor=PBG, edgecolor=GRAY, ncol=4)
    _sax(ax0, "Normalized Price Index (start = 100)", "Index")

    # 2) 20d realized vol
    ax1 = fig.add_subplot(gs[1, 0])
    for i, nm in enumerate(meme_names):
        if nm not in prices:
            continue
        vol = prices[nm].pct_change().rolling(20).std() * np.sqrt(252) * 100
        ax1.plot(vol.index, vol, color=AC[i % len(AC)], lw=0.9, alpha=0.85, label=nm)
    ax1.legend(fontsize=7, facecolor=PBG, edgecolor=GRAY)
    _sax(ax1, "20-Day Realized Volatility (ann. %)", "Vol %")

    # 3) Sharpe / CAGR bars
    ax2 = fig.add_subplot(gs[1, 1])
    names = [n for n in meme_names if n in asset_metrics]
    sharpes = [asset_metrics[n]["Sharpe"] for n in names]
    x = np.arange(len(names))
    colors = [GREEN if s > 0 else RED for s in sharpes]
    ax2.bar(x, sharpes, color=colors, alpha=0.85)
    ax2.set_xticks(x)
    ax2.set_xticklabels(names, color="white", fontsize=9)
    ax2.axhline(0, color=GRAY, lw=0.5)
    _sax(ax2, "Per-Asset Sharpe Ratio", "Sharpe")

    # 4) Meme-only correlation
    ax3 = fig.add_subplot(gs[2, 0])
    rets = {n: prices[n].pct_change() for n in meme_names if n in prices}
    if rets:
        corr = pd.DataFrame(rets).dropna().corr()
        cmap = LinearSegmentedColormap.from_list("rg", [RED, PBG, GREEN], N=256)
        im = ax3.imshow(corr.values, cmap=cmap, vmin=-1, vmax=1, aspect="auto")
        ax3.set_xticks(range(len(corr)))
        ax3.set_xticklabels(corr.columns, color="white", fontsize=8, rotation=35, ha="right")
        ax3.set_yticks(range(len(corr)))
        ax3.set_yticklabels(corr.index, color="white", fontsize=8)
        for i in range(len(corr)):
            for j in range(len(corr)):
                v = corr.values[i, j]
                ax3.text(
                    j, i, f"{v:.2f}", ha="center", va="center", fontsize=8,
                    color="white" if abs(v) > 0.35 else GRAY,
                )
        plt.colorbar(im, ax=ax3, fraction=0.04)
    ax3.set_title("Meme Basket Correlation", color="white", fontsize=10, fontweight="bold")

    # 5) Cumulative strategy return per meme asset
    ax4 = fig.add_subplot(gs[2, 1])
    for i, nm in enumerate(meme_names):
        if nm not in asset_returns:
            continue
        cum = (1 + asset_returns[nm].fillna(0)).cumprod()
        ax4.plot(cum.index, cum, color=AC[i % len(AC)], lw=1.1, label=nm)
    ax4.axhline(1, color=GRAY, lw=0.4)
    ax4.legend(fontsize=7, facecolor=PBG, edgecolor=GRAY)
    _sax(ax4, "Vol-Targeted Trend Strategy P&L (per meme)", "Equity")

    plt.savefig(path, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)


def render_polymarket_analysis(
    prices: dict,
    asset_returns: dict,
    asset_signals: dict,
    poly_names: list[str],
    path: str,
):
    """Polymarket implied-probability charts."""
    _style()
    fig = plt.figure(figsize=(22, 14), facecolor=BG)
    fig.suptitle(
        "POLYMARKET ANALYSIS  ·  Implied Probability (Yes) 0–100%",
        fontsize=14,
        fontweight="bold",
        color=ACCENT,
        y=0.97,
    )
    gs = gridspec.GridSpec(2, 2, figure=fig, hspace=0.38, wspace=0.28, top=0.90, bottom=0.06)

    for idx, nm in enumerate(poly_names[:4]):
        if nm not in prices:
            continue
        ax = fig.add_subplot(gs[idx // 2, idx % 2])
        p = prices[nm].dropna() * 100
        ax.plot(p.index, p, color=ACCENT, lw=1.4)
        ax.fill_between(p.index, p, alpha=0.15, color=ACCENT)
        sig = asset_signals.get(nm, pd.Series())
        if len(sig):
            for i in range(len(sig) - 1):
                if sig.iloc[i] > 0:
                    ax.axvspan(sig.index[i], sig.index[i + 1], alpha=0.08, color=GREEN, lw=0)
        ax.set_ylim(0, max(100, float(p.max()) * 1.05 + 1))
        ax.set_ylabel("Yes %", color=GRAY, fontsize=8)
        ax.set_title(f"{nm} — Implied Probability", color="white", fontsize=10, fontweight="bold")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        ax.grid(True, alpha=0.5)

    if not poly_names:
        ax = fig.add_subplot(gs[0, 0])
        ax.text(0.5, 0.5, "No Polymarket series loaded", ha="center", color=GRAY)

    plt.savefig(path, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)


def render_cross_asset_analysis(
    prices: dict,
    strat_r: pd.Series,
    bench_r: pd.Series,
    weights: pd.Series,
    poly_names: list[str],
    meme_names: list[str],
    path: str,
):
    """Polymarket vs meme rolling correlation, weights, underwater."""
    _style()
    fig = plt.figure(figsize=(22, 14), facecolor=BG)
    fig.suptitle(
        "CROSS-ASSET & RISK  ·  Polymarket × Meme × Portfolio",
        fontsize=14,
        fontweight="bold",
        color=ACCENT,
        y=0.97,
    )
    gs = gridspec.GridSpec(2, 2, figure=fig, hspace=0.38, wspace=0.28, top=0.90, bottom=0.06)

    # Rolling corr POLY vs DOGE
    ax0 = fig.add_subplot(gs[0, 0])
    poly = poly_names[0] if poly_names else None
    if poly and poly in prices and "DOGE" in prices:
        r1 = prices[poly].pct_change()
        r2 = prices["DOGE"].pct_change()
        rc = r1.rolling(30).corr(r2)
        ax0.plot(rc.index, rc, color=ACCENT, lw=1.2)
        ax0.axhline(0, color=GRAY, lw=0.5)
        ax0.fill_between(rc.index, 0, rc, where=(rc > 0), alpha=0.2, color=GREEN)
        ax0.fill_between(rc.index, 0, rc, where=(rc < 0), alpha=0.2, color=RED)
        _sax(ax0, f"30d Rolling Corr: {poly} vs DOGE", "Correlation")
    else:
        ax0.text(0.5, 0.5, "Need POLY + DOGE for rolling corr", ha="center", color=GRAY)

    # Portfolio weights
    ax1 = fig.add_subplot(gs[0, 1])
    w = weights.dropna()
    ax1.barh(w.index, w.values * 100, color=AC[: len(w)], alpha=0.9)
    ax1.set_xlabel("Weight %", color=GRAY)
    ax1.set_title("Inverse-Vol Portfolio Weights", color="white", fontsize=10, fontweight="bold")
    ax1.grid(True, alpha=0.5, axis="x")

    # Underwater (drawdown duration)
    ax2 = fig.add_subplot(gs[1, 0])
    cum = (1 + strat_r.fillna(0)).cumprod()
    rm = cum.cummax()
    dd = (cum - rm) / rm
    underwater = (dd < 0).astype(float)
    ax2.fill_between(underwater.index, 0, underwater, color=RED, alpha=0.5, step="post")
    _sax(ax2, "Underwater Chart (time in drawdown)", "Underwater")

    # Strategy vs benchmark rolling excess
    ax3 = fig.add_subplot(gs[1, 1])
    aligned = pd.DataFrame({"strat": strat_r, "bench": bench_r}).dropna()
    if len(aligned) > 30:
        ex = (aligned["strat"] - aligned["bench"]).rolling(60).sum() * 100
        ax3.plot(ex.index, ex, color=GREEN, lw=1.2)
        ax3.axhline(0, color=GRAY, lw=0.5)
        _sax(ax3, "60d Cumulative Excess Return vs Benchmark (%)", "Excess %")

    plt.savefig(path, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)


def render_market_discovery(markets: list[dict], path: str):
    """Top Polymarket markets by 24h volume (Gamma API — Polymarket/agents pattern)."""
    _style()
    fig, ax = plt.subplots(figsize=(16, max(6, len(markets) * 0.45)), facecolor=BG)
    if not markets:
        ax.text(0.5, 0.5, "No Gamma market data", ha="center", color=GRAY)
        plt.savefig(path, dpi=150, bbox_inches="tight", facecolor=BG)
        plt.close(fig)
        return

    labels, vols, probs = [], [], []
    for m in markets[:12]:
        q = (m.get("question") or m.get("slug") or "?")[:55]
        labels.append(q)
        try:
            vols.append(float(m.get("volume24hr") or m.get("volume_24hr") or 0))
        except (TypeError, ValueError):
            vols.append(0.0)
        op = m.get("outcomePrices")
        if isinstance(op, str):
            import json
            try:
                op = json.loads(op)
            except json.JSONDecodeError:
                op = []
        try:
            probs.append(float(op[0]) * 100 if op else 0)
        except (TypeError, ValueError, IndexError):
            probs.append(0)

    y = np.arange(len(labels))
    ax.barh(y, vols, color=ACCENT, alpha=0.75, label="24h Volume ($)")
    ax2 = ax.twiny()
    ax2.barh(y, probs, color=GOLD, alpha=0.35, height=0.4, label="Yes %")
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=8, color="white")
    ax.set_xlabel("24h Volume", color=GRAY)
    ax2.set_xlabel("Yes Price %", color=GOLD)
    ax.set_title(
        "Active Polymarket Markets (Gamma API)  ·  github.com/Polymarket/agents",
        color="white",
        fontsize=11,
        fontweight="bold",
        pad=10,
    )
    ax.invert_yaxis()
    ax.grid(True, alpha=0.4, axis="x")
    plt.tight_layout()
    plt.savefig(path, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)


def render_performance_summary(
    asset_metrics: dict,
    S: dict,
    path: str,
):
    """CAGR vs MDD scatter + win rate comparison."""
    _style()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 7), facecolor=BG)
    fig.suptitle("PERFORMANCE SUMMARY  ·  Risk-Return Profile", fontsize=13, color=ACCENT, fontweight="bold")

    for nm, m in asset_metrics.items():
        ax1.scatter(abs(m["MDD"]) * 100, m["CAGR"] * 100, s=120, alpha=0.85, label=nm)
        ax1.annotate(nm, (abs(m["MDD"]) * 100, m["CAGR"] * 100), fontsize=8, color="white", xytext=(4, 4), textcoords="offset points")
    ax1.axhline(0, color=GRAY, lw=0.5)
    ax1.set_xlabel("|Max Drawdown| %", color=GRAY)
    ax1.set_ylabel("CAGR %", color=GRAY)
    ax1.set_title("CAGR vs Max Drawdown", color="white", fontweight="bold")
    ax1.grid(True, alpha=0.5)

    names = list(asset_metrics.keys())
    wr = [asset_metrics[n]["WinRate"] * 100 for n in names]
    x = np.arange(len(names))
    ax2.bar(x, wr, color=[GREEN if w > 50 else RED for w in wr], alpha=0.85)
    ax2.axhline(50, color=GOLD, ls="--", lw=0.8, alpha=0.7)
    ax2.set_xticks(x)
    ax2.set_xticklabels(names, color="white", rotation=25, ha="right")
    ax2.set_ylabel("Win Rate %", color=GRAY)
    ax2.set_title("Daily Win Rate by Asset", color="white", fontweight="bold")
    ax2.grid(True, alpha=0.5, axis="y")

    plt.tight_layout()
    plt.savefig(path, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
