#!/usr/bin/env python3
"""
Multi-strategy tabs: each strategy → PnL backtest + Ang/BlackRock macro factor attribution.

Timezone for daily ops: America/New_York (16:00 ET portfolio update target).

Usage:
  python scripts/polymarket_multi_strategy_dashboard.py
"""

from __future__ import annotations

import os
import sys
from zoneinfo import ZoneInfo

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tradingagents.quant.barra_risk_factors import BARRA_FACTOR_META, barra_display_name
from tradingagents.quant.live_dashboard_payload import build_strategy_tab_results
from tradingagents.quant.strategy_catalog import StrategySpec

OUTPUT_DIR = os.path.join(REPO_ROOT, "assets", "dashboard_outputs")
SAVE_PNG = os.path.join(OUTPUT_DIR, "polymarket_strategy_tabs.png")
SAVE_HTML = os.path.join(OUTPUT_DIR, "polymarket_strategy_tabs.html")
SAVE_CSV = os.path.join(OUTPUT_DIR, "polymarket_strategy_tabs_metrics.csv")
NY = ZoneInfo("America/New_York")
DEFAULT_SLUG = "gta-vi-released-before-june-2026"

BG = "#0D1117"
PBG = "#161B22"
ACCENT = "#00D4FF"
GREEN = "#00FF88"
RED = "#FF4466"
GRAY = "#7A8899"


def _render_tabs_png(
    results: list[dict],
    path: str,
    as_of_ny: str,
):
    n = min(len(results), 8)
    if n == 0:
        return
    results = results[:n]
    plt.style.use("dark_background")
    fig_h = min(max(3.2 * n, 8), 28)
    fig = plt.figure(figsize=(20, fig_h), facecolor=BG)
    fig.suptitle(
        "STRATEGY TABS · LIVE · PnL + MSCI Barra-style factor attribution (ETF proxy)\n"
        f"As of {as_of_ny} (America/New_York)  ·  Daily target update: 16:00 ET",
        fontsize=13,
        fontweight="bold",
        color=ACCENT,
        y=0.995,
    )
    for i, res in enumerate(results):
        spec: StrategySpec = res["spec"]
        r: pd.Series = res["returns"]
        m: dict = res["metrics"]
        attr: pd.DataFrame = res["attribution"]

        ax0 = fig.add_subplot(n, 3, i * 3 + 1)
        ax0.axis("off")
        status = "RUNNABLE" if spec.runnable else "RESEARCH ONLY"
        lines = [
            f"Tab {i + 1}: {spec.name}  [{status}]",
            f"Category: {spec.category}",
            f"ID: {spec.id}",
            "",
            spec.description[:200],
            "",
            f"Reference: {spec.reference}",
            "",
            f"Win rate (in pos): {m.get('win_rate', 0):.1%}",
            f"Sharpe: {m.get('sharpe', 0):+.3f}",
            f"Return (ann.): {m.get('cagr', 0):+.1%}",
            f"Cum. return: {m.get('total_return', 0):+.1%}",
            f"Max DD: {m.get('max_dd', 0):.1%}",
            f"R² Barra fit: {res.get('r2', 0):.3f}",
        ]
        ax0.text(0.02, 0.98, "\n".join(lines), va="top", fontsize=8, color="white", family="monospace")

        ax1 = fig.add_subplot(n, 3, i * 3 + 2)
        if len(r) > 2:
            cum = (1 + r.fillna(0)).cumprod()
            ax1.plot(cum.index, cum, color=GREEN if cum.iloc[-1] >= 1 else RED, lw=1.5)
            ax1.axhline(1, color=GRAY, lw=0.5)
        ax1.set_title(f"{spec.name} · Equity", fontsize=9, color="white", fontweight="bold")
        ax1.set_ylabel("Cumulative ($1)", color=GRAY, fontsize=7)
        ax1.set_xlabel("Date", color=GRAY, fontsize=7)
        ax1.grid(True, alpha=0.3)

        ax2 = fig.add_subplot(n, 3, i * 3 + 3)
        if not attr.empty:
            plot_df = attr[attr["factor"] != "ALPHA"].tail(8)
            labels = [barra_display_name(str(x)) for x in plot_df["factor"]]
            y_pos = np.arange(len(labels))
            betas = plot_df["beta"].values
            colors = [ACCENT if b >= 0 else RED for b in betas]
            ax2.barh(y_pos, betas, color=colors, alpha=0.9)
            ax2.set_yticks(y_pos)
            ax2.set_yticklabels(labels, fontsize=6, color="white")
            ax2.axvline(0, color=GRAY, lw=0.5)
        ax2.set_title("MSCI Barra-style factor β (proxy)", fontsize=9, color="white", fontweight="bold")
        ax2.set_xlabel("Exposure β", color=GRAY, fontsize=7)
        ax2.grid(True, alpha=0.3, axis="x")

    fig.tight_layout(rect=[0, 0, 1, 0.94])
    plt.savefig(path, dpi=100, facecolor=BG)
    plt.close(fig)


def _write_html(results: list[dict], path: str, as_of_ny: str):
    rows = []
    for res in results:
        spec = res["spec"]
        m = res["metrics"]
        rows.append(
            f"<section><h2>{spec.name}</h2>"
            f"<p><b>{spec.category}</b> — {spec.description}</p>"
            f"<ul>"
            f"<li>Win rate: {m.get('win_rate', 0):.1%}</li>"
            f"<li>Sharpe: {m.get('sharpe', 0):+.3f}</li>"
            f"<li>Return: {m.get('total_return', 0):+.1%}</li>"
            f"<li>R²: {res.get('r2', 0):.3f}</li>"
            f"</ul>"
            f"<p><i>{spec.reference}</i></p></section>"
        )
    factor_list = "".join(
        f"<li><b>{k}</b>: {v['title']} ({v['proxy']}) [{v['group']}]</li>"
        for k, v in BARRA_FACTOR_META.items()
    )
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Strategy Tabs</title>
<meta http-equiv="refresh" content="0;url=http://127.0.0.1:8765/">
<style>body{{font-family:monospace;background:#0d1117;color:#e6edf3;padding:20px}}
h1{{color:#00d4ff}} a{{color:#00d4ff}}</style></head>
<body>
<h1>Strategy tabs · NY as-of {as_of_ny}</h1>
<p><b>Interactive LIVE UI</b> (click strategies, auto-refresh):</p>
<p>Run <code>python scripts/serve_polymarket_live.py</code> then open
<a href="http://127.0.0.1:8765/">http://127.0.0.1:8765/</a></p>
<p>Static PNG archive: <a href="polymarket_strategy_tabs.png">polymarket_strategy_tabs.png</a></p>
<h2>MSCI Barra-style factor universe (open-source proxy)</h2><ul>{factor_list}</ul>
{"".join(rows)}
</body></html>"""
    with open(path, "w") as f:
        f.write(html)


def main() -> int:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    end = pd.Timestamp.now(tz=NY).strftime("%Y-%m-%d")
    start = "2020-01-01"
    as_of_ny = pd.Timestamp.now(tz=NY).strftime("%Y-%m-%d %H:%M %Z")

    print("=" * 65)
    print("  MULTI-STRATEGY TABS · Barra factors · NY time")
    print(f"  As of: {as_of_ny}")
    print("=" * 65)

    print("\n[1/3] Loading strategy returns + Barra ...")
    results, barra = build_strategy_tab_results(start, end, DEFAULT_SLUG)
    print(f"    Tabs: {[r['spec'].id for r in results]}")
    print(f"    Barra factors: {list(barra.columns) if not barra.empty else []}")

    print("\n[2/3] Metrics CSV ...")
    csv_rows = []
    for res in results:
        spec = res["spec"]
        r = res["returns"]
        m = res["metrics"]
        csv_rows.append(
            {
                "strategy_id": spec.id,
                "name": spec.name,
                "category": spec.category,
                "runnable": spec.runnable,
                "win_rate": m.get("win_rate"),
                "sharpe": m.get("sharpe"),
                "cagr": m.get("cagr"),
                "total_return": m.get("total_return"),
                "max_dd": m.get("max_dd"),
                "r_squared_barra": res.get("r2"),
                "start": str(r.index.min().date()),
                "end": str(r.index.max().date()),
                "n_days": len(r),
            }
        )

    print("\n[3/3] Save tab dashboard ...")
    plt.close("all")
    _render_tabs_png(results, SAVE_PNG, as_of_ny)
    _write_html(results, SAVE_HTML, as_of_ny)
    pd.DataFrame(csv_rows).to_csv(SAVE_CSV, index=False)

    print(f"  📊  {SAVE_PNG}")
    print(f"  🌐  {SAVE_HTML}")
    print(f"  📋  {SAVE_CSV}")
    print("=" * 65)
    return 0 if results else 1


if __name__ == "__main__":
    raise SystemExit(main())
