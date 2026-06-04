#!/usr/bin/env python3
"""
Polymarket whale tracking + arbitrage analysis.

Features:
  1) Whale — top holders, large trades, concentration
  2) Arbitrage — Yes+No bundle (<$1), latency lag vs DOGE, tx cost gate
  3) Long-short — on Polymarket implied probability
  4) Patterns — recurring profitable arb windows

Usage:
  python scripts/polymarket_whale_arb_analysis.py
  python scripts/polymarket_whale_arb_analysis.py --min-trade-usd 1000 --latency-ms 800
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import pandas as pd

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from scripts.polymarket_whale_arb_charts import render_whale_arb_dashboard
from tradingagents.dataflows.polymarket_gamma import fetch_polymarket_daily_ohlcv, resolve_market_slug
from tradingagents.dataflows.polymarket_whale import (
    fetch_large_trades,
    fetch_top_holders,
    whale_concentration,
)
from tradingagents.quant.polymarket_arbitrage import (
    ArbEconomics,
    crypto_proxy_arb_vs_poly,
    find_arb_patterns,
    latency_delayed_arbitrage,
    long_short_poly_returns,
    parse_outcome_prices,
    scan_yes_no_arb_panel,
    yes_no_bundle_arbitrage,
)
from tradingagents.quant.polymarket_strategy import StrategyConfig, load_universe_prices, sharpe_ratio

OUTPUT_DIR = os.path.join(REPO_ROOT, "assets", "dashboard_outputs")
DEFAULT_SLUG = "gta-vi-released-before-june-2026"


def _load_doge(start: str, end: str) -> pd.Series:
    prices = load_universe_prices(StrategyConfig(start=start, end=end))
    return prices.get("DOGE", pd.Series(dtype=float))


def main() -> int:
    parser = argparse.ArgumentParser(description="Whale + arb analysis")
    parser.add_argument("--slug", default=DEFAULT_SLUG)
    parser.add_argument("--min-trade-usd", type=float, default=500.0)
    parser.add_argument("--latency-ms", type=float, default=500.0)
    parser.add_argument("--latency-days", type=int, default=1, help="POLY lags CEX by N days")
    parser.add_argument("--min-profit-bps", type=float, default=5.0)
    parser.add_argument("--start", default="2024-01-01")
    args = parser.parse_args()
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    econ = ArbEconomics(
        latency_ms=args.latency_ms,
        min_net_profit_bps=args.min_profit_bps,
    )
    end = pd.Timestamp.utcnow().strftime("%Y-%m-%d")

    print("=" * 65)
    print("  POLYMARKET WHALE + ARBITRAGE")
    print("=" * 65)

    meta = resolve_market_slug(args.slug)
    if not meta:
        print(f"  Market not found: {args.slug}")
        return 1
    cid = meta.get("conditionId", "")
    yes_p, no_p = parse_outcome_prices(meta)
    spot = yes_no_bundle_arbitrage(yes_p, no_p, econ)
    print(f"\n[1/5] Market: {meta.get('question', args.slug)[:70]}")
    print(f"    Yes={yes_p:.4f}  No={no_p:.4f}  Sum={spot['sum_asks']:.4f}")
    print(f"    Bundle arb NOW: net_bps={spot['net_bps']:+.1f}  profitable={spot['profitable']}")

    print("\n[2/5] Whale analytics ...")
    holders = fetch_top_holders(cid, limit=25)
    trades = fetch_large_trades(min_cash_usd=args.min_trade_usd, limit=150, market_slug=args.slug)
    conc = whale_concentration(holders)
    for k, v in conc.items():
        print(f"    {k}: {v:.3f}" if isinstance(v, float) else f"    {k}: {v}")
    print(f"    Large trades fetched: {len(trades)}")

    print("\n[3/5] Historical Yes/No bundle arb + patterns ...")
    yes_ohlcv = fetch_polymarket_daily_ohlcv(args.slug, args.start, end)
    no_slug = args.slug
    yes_s = yes_ohlcv["Close"] if not yes_ohlcv.empty else pd.Series(dtype=float)
    no_s = pd.Series(dtype=float)
    if yes_s.empty:
        arb_panel = pd.DataFrame()
    else:
        no_s = yes_s.map(lambda y: max(0.0, 1.0 - float(y)))
        arb_panel = scan_yes_no_arb_panel(yes_s, no_s, econ)
    patterns = find_arb_patterns(arb_panel)
    if not patterns.empty:
        print(patterns.to_string(index=False))

    print("\n[4/5] Latency + long-short ...")
    doge = _load_doge(args.start, end)
    lag_scan = crypto_proxy_arb_vs_poly(doge, yes_s, econ, max_lag=5) if len(yes_s) and len(doge) else pd.DataFrame()
    if not lag_scan.empty:
        best = lag_scan.loc[lag_scan["correlation"].abs().idxmax()]
        print(f"    Best |corr| lag: {int(best['lag_days'])}d  corr={best['correlation']:.3f}")
    poly_ls = long_short_poly_returns(yes_s, econ) if len(yes_s) else pd.Series(dtype=float)
    if len(poly_ls):
        print(f"    POLY long-short Sharpe: {sharpe_ratio(poly_ls):+.3f}")

    delay_bars = max(1, args.latency_days)
    lat_arb = latency_delayed_arbitrage(doge, yes_s, econ, delay_bars=delay_bars) if len(doge) and len(yes_s) else pd.DataFrame()
    latency_hit_1d = None
    if not lat_arb.empty:
        latency_hit_1d = float(lat_arb["profitable"].mean())
        print(f"    Latency arb hit rate ({delay_bars}d delay): {latency_hit_1d:.1%}")

    scan_stats = {}
    if not lag_scan.empty:
        best_row = lag_scan.loc[lag_scan["correlation"].abs().idxmax()]
        scan_stats["best_lag_days"] = int(best_row["lag_days"])
        scan_stats["best_corr"] = float(best_row["correlation"])
    scan_stats["latency_hit_1d"] = latency_hit_1d
    if len(poly_ls):
        scan_stats["poly_ls_sharpe"] = float(sharpe_ratio(poly_ls))

    print("\n[5/5] Saving outputs ...")
    econ_summary = {
        "fee_bps": econ.poly_fee_bps_per_leg,
        "slip_bps": econ.slippage_bps_per_leg,
        "gas_usd": econ.gas_usd_per_bundle,
        "latency_ms": econ.latency_ms,
        "min_profit_bps": econ.min_net_profit_bps,
        "min_gross_edge": econ.min_gross_edge(),
    }
    png = os.path.join(OUTPUT_DIR, "polymarket_whale_arb_analysis.png")
    csv = os.path.join(OUTPUT_DIR, "polymarket_whale_arb_metrics.csv")
    render_whale_arb_dashboard(
        holders,
        trades,
        arb_panel,
        lag_scan,
        poly_ls,
        patterns,
        econ_summary,
        png,
        market_title=str(meta.get("question", "")),
        market_slug=args.slug,
        scan_stats=scan_stats,
    )

    with open(csv, "w") as f:
        f.write("=== SPOT BUNDLE ARB ===\n")
        pd.DataFrame([spot]).to_csv(f, index=False)
        f.write("\n=== WHALE CONCENTRATION ===\n")
        pd.DataFrame([conc]).to_csv(f, index=False)
        f.write("\n=== TOP HOLDERS ===\n")
        holders.to_csv(f, index=False)
        f.write("\n=== LARGE TRADES ===\n")
        trades.to_csv(f, index=False)
        f.write("\n=== ARB PATTERNS ===\n")
        patterns.to_csv(f, index=False)
        f.write("\n=== LAG SCAN (CEX vs POLY) ===\n")
        lag_scan.to_csv(f, index=False)
        f.write("\n=== ECONOMICS ===\n")
        pd.DataFrame([econ_summary]).to_csv(f, index=False)
        if not arb_panel.empty:
            f.write("\n=== HISTORICAL ARB PANEL (tail) ===\n")
            arb_panel.tail(100).reset_index().to_csv(f, index=False)

    print(f"  📊  {png}")
    print(f"  📋  {csv}")
    print("=" * 65)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
