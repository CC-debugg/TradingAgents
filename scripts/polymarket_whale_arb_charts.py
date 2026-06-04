"""Charts for whale + arbitrage analysis."""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

BG = "#0D1117"
PBG = "#161B22"
ACCENT = "#00D4FF"
GREEN = "#00FF88"
RED = "#FF4466"
GOLD = "#FFD700"
GRAY = "#7A8899"


def _style():
    plt.style.use("dark_background")
    plt.rcParams.update(
        {
            "axes.facecolor": PBG,
            "figure.facecolor": BG,
            "axes.edgecolor": GRAY,
            "font.family": "monospace",
            "xtick.color": GRAY,
            "ytick.color": GRAY,
        }
    )


def _label_ax(ax, xlabel: str = "", ylabel: str = ""):
    if xlabel:
        ax.set_xlabel(xlabel, color=GRAY, fontsize=9)
    if ylabel:
        ax.set_ylabel(ylabel, color=GRAY, fontsize=9)


def render_whale_arb_dashboard(
    holders: pd.DataFrame,
    trades: pd.DataFrame,
    arb_panel: pd.DataFrame,
    lag_scan: pd.DataFrame,
    poly_ls: pd.Series,
    patterns: pd.DataFrame,
    econ_summary: dict,
    path: str,
    *,
    market_title: str = "",
    market_slug: str = "",
    scan_stats: dict | None = None,
):
    _style()
    fig = plt.figure(figsize=(20, 22), facecolor=BG)
    subtitle = (market_title or market_slug or "single Polymarket market")[:90]
    fig.suptitle(
        "POLYMARKET WHALE + ARBITRAGE ANALYSIS\n"
        "Bundle arb · Latency · Long-Short · Tx costs",
        fontsize=14,
        fontweight="bold",
        color=ACCENT,
        y=0.98,
    )
    fig.text(
        0.5,
        0.935,
        f"Market: {subtitle}  ·  Data: Gamma API (meta) + Data API (whales) + CLOB/Gamma (prices)",
        ha="center",
        color=GRAY,
        fontsize=9,
    )
    gs = fig.add_gridspec(4, 2, hspace=0.48, wspace=0.32, top=0.90, bottom=0.05)

    # Row 0: Whales
    ax0 = fig.add_subplot(gs[0, 0])
    if not holders.empty:
        top = holders.nlargest(12, "amount").copy()
        labels = top.apply(
            lambda r: (r["name"] or r["wallet"][:10]) + f" ({r['outcome']})", axis=1
        )
        ax0.barh(labels, top["amount"], color=ACCENT, alpha=0.85)
        ax0.set_title(
            "[2/5] Whale · Top token holders (Polymarket Data API)",
            fontweight="bold",
            color="white",
            fontsize=10,
        )
        ax0.invert_yaxis()
        _label_ax(ax0, xlabel="Outcome token balance (shares, not USD)", ylabel="Holder · outcome side")
    else:
        ax0.text(0.5, 0.5, "No holder data", ha="center", color=GRAY)
    ax0.grid(True, alpha=0.3, axis="x")

    ax1 = fig.add_subplot(gs[0, 1])
    if not trades.empty and "cash_usd" in trades.columns:
        t = trades.head(40).sort_values("timestamp")
        colors = [GREEN if s == "BUY" else RED for s in t.get("side", "")]
        ax1.scatter(t["timestamp"], t["cash_usd"], c=colors, alpha=0.8, s=40)
        ax1.set_title(
            f"[2/5] Whale · Large trades (n={len(trades)} fetched)",
            fontweight="bold",
            color="white",
            fontsize=10,
        )
        _label_ax(ax1, xlabel="Trade time (UTC)", ylabel="Cash notional (USD)")
        from matplotlib.lines import Line2D

        ax1.legend(
            handles=[
                Line2D([0], [0], marker="o", color="w", markerfacecolor=GREEN, label="BUY", markersize=8),
                Line2D([0], [0], marker="o", color="w", markerfacecolor=RED, label="SELL", markersize=8),
            ],
            fontsize=8,
            loc="upper right",
            facecolor=PBG,
            edgecolor=GRAY,
        )
    else:
        ax1.text(0.5, 0.5, "No large trades", ha="center", color=GRAY)
        _label_ax(ax1, xlabel="Trade time (UTC)", ylabel="Cash notional (USD)")
    ax1.grid(True, alpha=0.3)

    # Row 1: Yes+No bundle arb
    ax2 = fig.add_subplot(gs[1, :])
    if not arb_panel.empty:
        ax2.plot(arb_panel.index, arb_panel["sum_asks"], color=GOLD, lw=1.2, label="Yes+No ask sum")
        ax2.axhline(1.0, color=GRAY, ls="--", lw=0.8, label="Parity $1")
        min_edge = econ_summary.get("min_gross_edge", 0.02)
        ax2.axhline(1.0 - min_edge, color=GREEN, ls=":", lw=0.9, label=f"Arb threshold (costs)")
        prof = arb_panel[arb_panel["profitable"]]
        if not prof.empty:
            ax2.scatter(prof.index, prof["sum_asks"], color=GREEN, s=12, alpha=0.7, label="Profitable arb")
        ax2.set_title(
            "Strategy A · Bundle arb · ask sum = Yes price + No price (daily)",
            fontweight="bold",
            color="white",
            fontsize=10,
        )
        _label_ax(ax2, xlabel="Date", ylabel="Ask sum ($ per $1 payout at resolution)")
        ax2.legend(fontsize=8, facecolor=PBG, edgecolor=GRAY, loc="upper right")
        n_prof = int(arb_panel["profitable"].sum()) if "profitable" in arb_panel.columns else 0
        n_all = len(arb_panel)
        spot_net = float(arb_panel["net_bps"].iloc[-1]) if len(arb_panel) else 0.0
        verdict = "NO bundle edge" if n_prof == 0 else f"{n_prof}/{n_all} days profitable"
        ax2.text(
            0.02,
            0.05,
            f"Strategy A · Bundle arb  →  {verdict}  (sum≈$1 ⇒ gross≈0; last-day net_bps={spot_net:+.0f})",
            transform=ax2.transAxes,
            fontsize=8,
            color=GOLD if n_prof else RED,
            va="bottom",
        )
    else:
        ax2.text(0.5, 0.5, "No Yes/No price history", ha="center", color=GRAY)
        _label_ax(ax2, xlabel="Date", ylabel="Ask sum ($)")
    ax2.grid(True, alpha=0.3)

    # Row 2: Latency + long-short (three strategy demos — not chained)
    scan_stats = scan_stats or {}
    ax3 = fig.add_subplot(gs[2, 0])
    if not lag_scan.empty:
        x = np.arange(len(lag_scan))
        hits = lag_scan["arb_hit_rate"].values * 100
        corrs = lag_scan["correlation"].values
        bars = ax3.bar(x, hits, color=ACCENT, alpha=0.85, label="Hit rate (%)")
        ax3.set_xticks(x)
        ax3.set_xticklabels([f"lag {int(d)}d" for d in lag_scan["lag_days"]], color="white", fontsize=8)
        ax3r = ax3.twinx()
        ax3r.plot(x, corrs, color=GOLD, marker="o", lw=1.8, ms=7, label="Correlation ρ")
        ax3r.axhline(0, color=GRAY, lw=0.5, alpha=0.6)
        ax3r.set_ylabel("Pearson ρ (DOGE vs lagged POLY)", color=GOLD, fontsize=8)
        ax3r.tick_params(axis="y", colors=GOLD)
        for i, (h, c) in enumerate(zip(hits, corrs)):
            ax3.text(i, h + 1.5, f"{h:.0f}%", ha="center", fontsize=7, color="white")
            ax3r.text(i, c, f"ρ={c:+.3f}", ha="center", va="bottom", fontsize=7, color=GOLD)
        best_lag = scan_stats.get("best_lag_days")
        best_corr = scan_stats.get("best_corr")
        lat_hit = scan_stats.get("latency_hit_1d")
        note_lines = [
            "Strategy B · Latency RESEARCH (not a PnL backtest)",
            "⚠ Bar height = % days |DOGE−POLY| > cost — NOT win rate, NOT tradable edge",
        ]
        if lat_hit is not None:
            note_lines.append(
                f"Terminal 'latency hit' (1d delay, spread>|cost|): {lat_hit:.0%} — still NOT strategy return"
            )
        if best_lag is not None and best_corr is not None:
            note_lines.append(f"Best |ρ| at lag {best_lag}d: ρ={best_corr:+.3f}  →  weak if |ρ|≪0.2")
        ax3.text(
            0.02,
            0.98,
            "\n".join(note_lines),
            transform=ax3.transAxes,
            va="top",
            fontsize=7.5,
            color=RED if best_corr is not None and abs(float(best_corr)) < 0.2 else GOLD,
            bbox=dict(boxstyle="round", facecolor=PBG, edgecolor=GRAY, alpha=0.9),
        )
        ax3.set_title(
            "Strategy B · Lag scan (DOGE sentiment proxy vs POLY Yes %)",
            fontweight="bold",
            color="white",
            fontsize=10,
        )
        _label_ax(
            ax3,
            xlabel="Assume POLY daily return lags DOGE by N trading days",
            ylabel="Hit rate: % days |return diff| > threshold",
        )
        lines_l, labs_l = ax3.get_legend_handles_labels()
        lines_r, labs_r = ax3r.get_legend_handles_labels()
        ax3.legend(lines_l + lines_r, labs_l + labs_r, fontsize=7, loc="upper right", facecolor=PBG)
    else:
        ax3.text(0.5, 0.5, "Need DOGE + POLY history", ha="center", color=GRAY)
        _label_ax(ax3, xlabel="Lag (days)", ylabel="Hit rate (%)")
    ax3.grid(True, alpha=0.3, axis="y")

    ax4 = fig.add_subplot(gs[2, 1])
    if len(poly_ls) > 0:
        cum = (1 + poly_ls.fillna(0)).cumprod()
        tot_ret = float(cum.iloc[-1] - 1) if len(cum) else 0.0
        sh = scan_stats.get("poly_ls_sharpe")
        ax4.plot(cum.index, cum, color=GREEN, lw=1.5, label="EMA 5/15 on Yes %")
        ax4.axhline(1, color=GRAY, lw=0.5)
        ax4.set_title(
            "Strategy C · Long-short on POLY Yes % (only this panel is a return backtest)",
            fontweight="bold",
            color="white",
            fontsize=10,
        )
        _label_ax(ax4, xlabel="Date", ylabel="Cumulative equity ($1 start, after fees)")
        ax4.legend(fontsize=8, facecolor=PBG, edgecolor=GRAY)
        sh_txt = f"{sh:+.2f}" if sh is not None else "n/a"
        ax4.text(
            0.02,
            0.95,
            f"Same rule as Step 2 POLY leg: EMA fast=5 / slow=15 on implied probability\n"
            f"Sharpe≈{sh_txt}  ·  Total return≈{tot_ret:+.1%}  ·  Single market — not full portfolio",
            transform=ax4.transAxes,
            va="top",
            fontsize=8,
            color=GREEN if tot_ret > 0 else RED,
            bbox=dict(boxstyle="round", facecolor=PBG, edgecolor=GRAY, alpha=0.9),
        )
    else:
        ax4.text(0.5, 0.5, "Insufficient POLY history", ha="center", color=GRAY)
        _label_ax(ax4, xlabel="Date", ylabel="Cumulative equity")
    ax4.grid(True, alpha=0.3)

    # Row 3: Patterns + cost box
    ax5 = fig.add_subplot(gs[3, 0])
    ax5.axis("off")
    ax5.set_title("[3/5] Cost model + arb patterns", fontweight="bold", color="white", fontsize=10)
    lines = [
        "Transaction cost model (ArbEconomics)",
        f"  Fee/leg:     {econ_summary.get('fee_bps', 20):.0f} bps",
        f"  Slippage:    {econ_summary.get('slip_bps', 10):.0f} bps/leg",
        f"  Gas/bundle:  ${econ_summary.get('gas_usd', 0.05):.2f}",
        f"  Latency:     {econ_summary.get('latency_ms', 500):.0f} ms",
        f"  Min profit:  {econ_summary.get('min_profit_bps', 5):.0f} bps net",
        f"  Min edge:    {econ_summary.get('min_gross_edge', 0):.2%}",
        "",
        "Profitable arb requires:",
        "  gross_edge − fees − gas ≥ min_profit",
    ]
    if not patterns.empty:
        lines.append("")
        lines.append("Patterns found:")
        for _, row in patterns.iterrows():
            lines.append(f"  {row.get('pattern','')}: n={row.get('count',0)}")
    ax5.text(0.05, 0.95, "\n".join(lines), va="top", fontsize=9, color="white", family="monospace")

    ax6 = fig.add_subplot(gs[3, 1])
    if not arb_panel.empty and "net_bps" in arb_panel.columns:
        ax6.hist(arb_panel["net_bps"].dropna(), bins=40, color=ACCENT, alpha=0.75, edgecolor="none")
        ax6.axvline(econ_summary.get("min_profit_bps", 5), color=RED, ls="--", label="Min net bps gate")
        ax6.set_title(
            "[3/5] Bundle arb · daily net edge after fees (histogram)",
            fontweight="bold",
            color="white",
            fontsize=10,
        )
        _label_ax(ax6, xlabel="Net arbitrage (basis points, per $100 notional)", ylabel="Number of days")
        ax6.legend(fontsize=8, facecolor=PBG, edgecolor=GRAY)
    else:
        ax6.text(0.5, 0.5, "No arb panel", ha="center", color=GRAY)
        _label_ax(ax6, xlabel="Net arb (bps)", ylabel="Count")
    ax6.grid(True, alpha=0.3)

    fig.text(
        0.5,
        0.01,
        "Gamma = market metadata API · Latency ms = assumed execution delay in cost model · "
        "Whale = Polymarket-only (holders/trades); DOGE used only for lag scan",
        ha="center",
        color=GRAY,
        fontsize=7.5,
    )

    plt.savefig(path, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
