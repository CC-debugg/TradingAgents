#!/usr/bin/env python3
"""
LIVE daily update (target 16:00 America/New_York): latest data, news, Barra factors, strategy tabs, CLOB intents.

Outputs PNG + CSV under assets/dashboard_outputs/live/

Usage:
  python scripts/polymarket_live_daily.py
  python scripts/polymarket_live_daily.py --live   # POLYMARKET_LIVE=1 + keys → CLOB (stub)
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from scripts.polymarket_multi_strategy_dashboard import (  # noqa: E402
    OUTPUT_DIR,
    _render_tabs_png,
    _write_html,
)
from tradingagents.dataflows.macro_news import fetch_macro_news_snapshot
from tradingagents.execution.polymarket_clob import (
    clob_health_check,
    execute_intents,
    target_positions_from_signals,
)
from tradingagents.quant.barra_risk_factors import barra_factor_attribution, load_barra_factor_returns
from tradingagents.quant.live_strategies import collect_strategy_returns, latest_signals
from tradingagents.quant.polymarket_strategy import StrategyConfig, load_universe_prices
from tradingagents.quant.strategy_catalog import STRATEGY_CATALOG
from tradingagents.quant.whale_strategy import strategy_metrics

NY = ZoneInfo("America/New_York")
LIVE_DIR = os.path.join(OUTPUT_DIR, "live")
DEFAULT_SLUG = "gta-vi-released-before-june-2026"


def main() -> int:
    parser = argparse.ArgumentParser(description="Live daily NY pipeline")
    parser.add_argument("--live", action="store_true", help="Set POLYMARKET_LIVE=1 for this run")
    args = parser.parse_args()
    if args.live:
        os.environ["POLYMARKET_LIVE"] = "1"

    os.makedirs(LIVE_DIR, exist_ok=True)
    now = datetime.now(NY)
    stamp = now.strftime("%Y%m%d_%H%M")
    as_of = now.strftime("%Y-%m-%d %H:%M %Z")
    end = now.strftime("%Y-%m-%d")
    start = (now - pd.Timedelta(days=400)).strftime("%Y-%m-%d")

    print("=" * 65)
    print("  LIVE DAILY UPDATE · America/New_York")
    print(f"  As of: {as_of}")
    print("=" * 65)

    print("\n[1/5] Latest prices & strategy returns ...")
    returns_map, _ = collect_strategy_returns(start, end, DEFAULT_SLUG)
    barra = load_barra_factor_returns(start, end)
    print(f"    Strategies: {list(returns_map.keys())}")

    print("\n[2/5] Macro news (ECB RSS + optional FRED) ...")
    news = fetch_macro_news_snapshot()
    ecb = news["ecb_headlines"]
    print(f"    ECB headlines: {len(ecb)}  FRED API: {news['fred_api_configured']}")

    print("\n[3/5] Barra-style factor attribution per strategy tab ...")
    results = []
    attr_rows = []
    for spec in STRATEGY_CATALOG:
        r = returns_map.get(spec.id)
        if r is None or r.empty:
            continue
        m = strategy_metrics(r)
        attr = barra_factor_attribution(r, barra) if not barra.empty else pd.DataFrame()
        r2 = float(attr.attrs.get("r_squared", 0)) if not attr.empty else 0.0
        results.append({"spec": spec, "returns": r, "metrics": m, "attribution": attr, "r2": r2})
        if not attr.empty:
            sub = attr[attr["factor"] != "ALPHA"].copy()
            sub["strategy_id"] = spec.id
            attr_rows.append(sub)

    print("\n[4/5] CLOB order intents (POLY_GTA + meme signals) ...")
    cfg = StrategyConfig(start=start, end=end)
    prices = load_universe_prices(cfg)
    sig = latest_signals(cfg, prices, pd.Series(dtype=float))
    poly_sig = float(sig.get("POLY_GTA", 0))
    doge_sig = float(sig.get("DOGE", 0))
    wif_sig = float(sig.get("WIF", 0))
    intents = target_positions_from_signals(poly_sig, doge_sig, wif_sig, notional_usd=100.0)
    orders = execute_intents(intents)
    health = clob_health_check()
    print(f"    CLOB health: {health}  orders: {len(orders)}")

    print("\n[5/5] Save PNG + CSV ...")
    png_live = os.path.join(LIVE_DIR, f"polymarket_strategy_tabs_{stamp}_ny.png")
    png_main = os.path.join(OUTPUT_DIR, "polymarket_strategy_tabs.png")
    csv_live = os.path.join(LIVE_DIR, f"polymarket_live_snapshot_{stamp}_ny.csv")
    csv_main = os.path.join(OUTPUT_DIR, "polymarket_strategy_tabs_metrics.csv")

    import matplotlib.pyplot as plt

    plt.close("all")
    _render_tabs_png(results, png_live, as_of)
    _render_tabs_png(results, png_main, as_of)
    html_path = os.path.join(LIVE_DIR, f"polymarket_strategy_tabs_{stamp}_ny.html")
    _write_html(results, html_path, as_of)

    summary = []
    for res in results:
        spec = res["spec"]
        m = res["metrics"]
        summary.append(
            {
                "as_of_ny": as_of,
                "strategy_id": spec.id,
                "name": spec.name,
                "win_rate": m.get("win_rate"),
                "sharpe": m.get("sharpe"),
                "total_return": m.get("total_return"),
                "r_squared_barra": res.get("r2"),
            }
        )
    df_sum = pd.DataFrame(summary)

    with open(csv_live, "w") as f:
        f.write(f"# LIVE SNAPSHOT as_of_ny={as_of}\n")
        f.write("=== STRATEGY TABS ===\n")
        df_sum.to_csv(f, index=False)
        f.write("\n=== CLOB HEALTH ===\n")
        pd.DataFrame([health]).to_csv(f, index=False)
        f.write("\n=== ORDER INTENTS ===\n")
        pd.DataFrame(orders).to_csv(f, index=False)
        f.write("\n=== SIGNALS ===\n")
        pd.DataFrame([{"POLY_GTA": poly_sig, "DOGE": doge_sig, "WIF": wif_sig}]).to_csv(f, index=False)
        f.write("\n=== ECB HEADLINES ===\n")
        ecb.to_csv(f, index=False)
        if attr_rows:
            f.write("\n=== BARRA FACTOR ATTRIBUTION (all strategies) ===\n")
            pd.concat(attr_rows, ignore_index=True).to_csv(f, index=False)
    df_sum.to_csv(csv_main, index=False)

    print(f"  📊  {png_main}")
    print(f"  📊  {png_live}")
    print(f"  📋  {csv_main}")
    print(f"  📋  {csv_live}")
    print("=" * 65)
    return 0 if results else 1


if __name__ == "__main__":
    raise SystemExit(main())
