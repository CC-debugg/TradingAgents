#!/usr/bin/env python3
"""
Master dashboard: all project PNG outputs + key metrics on one page.

Usage:
  python scripts/polymarket_master_dashboard.py
"""

from __future__ import annotations

import os
import sys

import matplotlib.pyplot as plt
import matplotlib.image as mpimg
import pandas as pd

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUTPUT_DIR = os.path.join(REPO_ROOT, "assets", "dashboard_outputs")
SAVE_PATH = os.path.join(OUTPUT_DIR, "polymarket_master_dashboard.png")

BG = "#0D1117"
PBG = "#161B22"
ACCENT = "#00D4FF"
GRAY = "#7A8899"
WHITE = "#FFFFFF"

# Order and captions for each panel
PANELS = [
    ("polymarket_meme_dashboard.png", "A · Main backtest\nTrend + vol target · POLY/DOGE/WIF"),
    ("polymarket_walkforward_oos.png", "B · Walk-forward OOS\n252d train / 63d test · 33 folds"),
    ("polymarket_whale_arb_analysis.png", "C · Whale + arbitrage\nHolders · bundle arb · latency · long-short"),
    ("polymarket_meme_charts_meme.png", "D · Meme analytics\nIndex · vol · Sharpe · correlation"),
    ("polymarket_meme_charts_polymarket.png", "E · Polymarket\nYes implied probability %"),
    ("polymarket_meme_charts_cross.png", "F · Cross-asset risk\nPOLY×DOGE corr · weights · underwater"),
    ("polymarket_meme_charts_performance.png", "G · Performance\nCAGR vs drawdown · win rate"),
    ("polymarket_active_markets.png", "H · Market discovery\nGamma API active markets"),
    ("polymarket_factor_attribution.png", "I · Factor attribution\nMacro factors vs strategy"),
    ("polymarket_strategy_tabs.png", "K · Strategy tabs\nEach strategy · Ang macro β"),
    ("polymarket_meme_overview_en.png", "J · Project overview\nArchitecture (EN)"),
]


def _load_metrics_blurb() -> str:
    lines = [
        "KEY RESULTS (latest CSV runs)",
        "─" * 42,
    ]
    meme_csv = os.path.join(OUTPUT_DIR, "polymarket_meme_metrics.csv")
    wf_csv = os.path.join(OUTPUT_DIR, "polymarket_walkforward_metrics.csv")
    if os.path.isfile(meme_csv):
        try:
            raw = open(meme_csv).read()
            if "Sharpe,0.389" in raw or "Sharpe" in raw:
                for block, label in [
                    ("=== PORTFOLIO METRICS ===", "In-sample portfolio"),
                    ("=== PER-ASSET METRICS ===", "Per-asset legs"),
                ]:
                    if block in raw:
                        chunk = raw.split(block)[1].split("===")[0].strip().splitlines()[:6]
                        lines.append(f"\n{label}:")
                        lines.extend("  " + ln for ln in chunk if ln.strip())
        except Exception:
            pass
    if os.path.isfile(wf_csv):
        try:
            df = pd.read_csv(wf_csv, comment="#", on_bad_lines="skip")
            if "oos_sharpe" in str(open(wf_csv).read()):
                for ln in open(wf_csv):
                    if "oos_sharpe" in ln and not ln.startswith("factor"):
                        lines.append("\nWalk-forward OOS:")
                        lines.append("  " + ln.strip())
                        break
        except Exception:
            pass
    lines.extend(
        [
            "",
            "RUN ALL:",
            "  python scripts/polymarket_meme_run.py dashboard",
            "  python scripts/polymarket_meme_run.py walkforward",
            "  python scripts/polymarket_meme_run.py whale-arb",
            "",
            "UNIVERSE: POLY_GTA + DOGE + WIF",
            "STRATEGY: EMA trend · meme long-only · sharpe_tilt",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    plt.style.use("dark_background")
    fig = plt.figure(figsize=(28, 36), facecolor=BG)
    fig.suptitle(
        "POLYMARKET + MEME COINS — MASTER DASHBOARD\n"
        "TradingAgents · Qlib/WFO · Whale/Arb · All outputs",
        fontsize=18,
        fontweight="bold",
        color=ACCENT,
        y=0.995,
    )

    # Layout: 5 rows x 2 cols for images + right column for metrics on row 0-1
    gs = fig.add_gridspec(7, 2, height_ratios=[1.2, 1, 1, 1, 1, 1, 0.35], hspace=0.22, wspace=0.12,
                          top=0.96, bottom=0.02, left=0.02, right=0.98)

    ax_metrics = fig.add_subplot(gs[6, :])
    ax_metrics.axis("off")
    ax_metrics.text(
        0.02, 0.95, _load_metrics_blurb(),
        transform=ax_metrics.transAxes,
        fontsize=9,
        color=WHITE,
        family="monospace",
        va="top",
        ha="left",
        bbox=dict(boxstyle="round", facecolor=PBG, edgecolor=GRAY, alpha=0.9),
    )

    plot_idx = 0
    for row in range(6):
        for col in range(2):
            if plot_idx >= len(PANELS):
                break
            fname, caption = PANELS[plot_idx]
            path = os.path.join(OUTPUT_DIR, fname)
            ax = fig.add_subplot(gs[row, col])
            ax.axis("off")
            if os.path.isfile(path):
                try:
                    img = mpimg.imread(path)
                    ax.imshow(img)
                    ax.set_title(caption, color=WHITE, fontsize=9, fontweight="bold", pad=6)
                except Exception as e:
                    ax.text(0.5, 0.5, f"Load error\n{fname}", ha="center", color=GRAY)
            else:
                ax.text(
                    0.5, 0.5,
                    f"Missing:\n{fname}\n\nRun pipeline to generate",
                    ha="center",
                    va="center",
                    color=GRAY,
                    fontsize=8,
                )
                ax.set_facecolor(PBG)
                ax.set_title(caption, color=GRAY, fontsize=9, pad=6)
            plot_idx += 1

    plt.savefig(SAVE_PATH, dpi=120, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    print(f"Master dashboard saved: {SAVE_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
