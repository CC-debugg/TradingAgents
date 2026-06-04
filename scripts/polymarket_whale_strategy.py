#!/usr/bin/env python3
"""
Whale trade-flow → strategy backtest + walk-forward (win rate, Sharpe, OOS).

Uses Polymarket Data API paginated large trades + Yes price history.
NOT live execution — research / paper-trading metrics only.

Usage:
  python scripts/polymarket_whale_strategy.py
  python scripts/polymarket_whale_strategy.py --slug gta-vi-released-before-june-2026 --max-trades 8000
"""

from __future__ import annotations

import argparse
import os
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tradingagents.dataflows.polymarket_gamma import fetch_polymarket_daily_ohlcv
from tradingagents.dataflows.polymarket_whale import (
    DEFAULT_CONDITION_IDS,
    fetch_large_trades_history,
    fetch_market_meta,
)
from tradingagents.quant.whale_strategy import (
    WhaleStrategyConfig,
    backtest_whale_strategy,
    daily_whale_flow,
    strategy_metrics,
    walk_forward_whale,
    whale_flow_signal,
)

OUTPUT_DIR = os.path.join(REPO_ROOT, "assets", "dashboard_outputs")
SAVE_PNG = os.path.join(OUTPUT_DIR, "polymarket_whale_strategy.png")
SAVE_CSV = os.path.join(OUTPUT_DIR, "polymarket_whale_strategy_metrics.csv")

def _prob_series_from_trades(trades: pd.DataFrame) -> pd.Series:
    """Daily Yes implied % from trade prints when CLOB history is missing."""
    if trades.empty:
        return pd.Series(dtype=float)
    df = trades.copy()
    df["date"] = pd.to_datetime(df["timestamp"]).dt.tz_convert(None).dt.normalize()
    yes = df[df["outcome"].str.upper() == "YES"].groupby("date")["price"].last()
    no = df[df["outcome"].str.upper() == "NO"].groupby("date")["price"].last()
    idx = pd.date_range(df["date"].min(), df["date"].max(), freq="D")
    yes = yes.reindex(idx).ffill()
    no = no.reindex(idx).ffill()
    prob = yes.copy()
    miss = prob.isna()
    prob[miss] = (1.0 - no[miss]).clip(0, 1)
    return prob.dropna().sort_index()

BG = "#0D1117"
PBG = "#161B22"
ACCENT = "#00D4FF"
GREEN = "#00FF88"
RED = "#FF4466"
GOLD = "#FFD700"
GRAY = "#7A8899"


def _render_chart(
    flow: pd.DataFrame,
    prob: pd.Series,
    full_r: pd.Series,
    oos_r: pd.Series,
    folds: pd.DataFrame,
    cfg: WhaleStrategyConfig,
    metrics: dict,
    oos_metrics: dict,
    holdout_metrics: dict,
    path: str,
    title: str,
):
    plt.style.use("dark_background")
    fig = plt.figure(figsize=(18, 14), facecolor=BG)
    fig.suptitle(
        "WHALE-FLOW STRATEGY · Backtest + Walk-Forward\n"
        "(follow large-trade net pressure on Yes vs No — NOT live bot)",
        fontsize=13,
        fontweight="bold",
        color=ACCENT,
        y=0.98,
    )
    fig.text(0.5, 0.93, title[:100], ha="center", color=GRAY, fontsize=9)
    gs = fig.add_gridspec(2, 2, hspace=0.35, wspace=0.25, top=0.88, bottom=0.08)

    ax0 = fig.add_subplot(gs[0, 0])
    if not flow.empty:
        colors = [GREEN if v >= 0 else RED for v in flow["flow_net_usd"]]
        ax0.bar(flow.index, flow["flow_net_usd"] / 1000, color=colors, alpha=0.85, width=0.8)
        ax0.axhline(0, color=GRAY, lw=0.6)
        ax0.set_title("Daily whale net flow (Yes − No, $k)", fontweight="bold", color="white")
        ax0.set_ylabel("Signed USD (thousands)", color=GRAY, fontsize=8)
        ax0.set_xlabel("Date", color=GRAY, fontsize=8)
    ax0.grid(True, alpha=0.3)

    ax1 = fig.add_subplot(gs[0, 1])
    if len(full_r):
        cum = (1 + full_r.fillna(0)).cumprod()
        ax1.plot(cum.index, cum, color=GREEN, lw=1.6, label="Full-sample whale strategy")
    if len(oos_r):
        cum_o = (1 + oos_r.fillna(0)).cumprod()
        ax1.plot(cum_o.index, cum_o, color=ACCENT, lw=1.4, ls="--", label="Walk-forward OOS stitched")
    ax1.axhline(1, color=GRAY, lw=0.5)
    ax1.legend(fontsize=8, facecolor=PBG)
    ax1.set_title("Equity curve ($1 start)", fontweight="bold", color="white")
    ax1.set_ylabel("Cumulative value", color=GRAY, fontsize=8)
    ax1.set_xlabel("Date", color=GRAY, fontsize=8)
    ax1.grid(True, alpha=0.3)

    ax2 = fig.add_subplot(gs[1, 0])
    if not folds.empty and "test_win_rate" in folds.columns:
        x = np.arange(len(folds))
        ax2.bar(x, folds["test_win_rate"] * 100, color=ACCENT, alpha=0.85)
        ax2.axhline(50, color=GOLD, ls="--", lw=0.8)
        ax2.set_title("Per-fold OOS win rate (% days in position with ret>0)", fontweight="bold", color="white")
        ax2.set_ylabel("Win rate %", color=GRAY, fontsize=8)
        ax2.set_xlabel("Fold #", color=GRAY, fontsize=8)
    ax2.grid(True, alpha=0.3, axis="y")

    ax3 = fig.add_subplot(gs[1, 1])
    ax3.axis("off")
    lines = [
        "Strategy rule (whale → signal)",
        f"  Rolling {cfg.flow_window}d sum(flow_yes − flow_no)",
        f"  Long Yes pressure if net ≥ ${cfg.min_flow_usd:,.0f}",
        f"  Short Yes pressure if net ≤ −${cfg.min_flow_usd:,.0f}",
        f"  PnL = signal × Δ(Yes probability) − {cfg.fee_bps:.0f} bps on flip",
        "",
        "FULL SAMPLE (all trade history aligned to prices)",
        f"  Win rate (in position): {metrics.get('win_rate', 0):.1%}",
        f"  Win rate (all days):     {metrics.get('win_rate_all_days', 0):.1%}",
        f"  Sharpe:  {metrics.get('sharpe', 0):+.3f}",
        f"  Return:  {metrics.get('total_return', 0):+.1%}",
        f"  Trades (signal changes): {int(metrics.get('n_trades', 0))}",
        "",
        "WALK-FORWARD OOS (train 60d / test 21d, grid search window & threshold)",
        f"  Folds: {len(folds)}",
        f"  OOS Win rate: {oos_metrics.get('win_rate', 0):.1%}",
        f"  OOS Sharpe:   {oos_metrics.get('sharpe', 0):+.3f}",
        f"  OOS Return:   {oos_metrics.get('total_return', 0):+.1%}",
        "",
        "HOLDOUT (last 30% of timeline — never used in WFO grid search)",
        f"  Win rate: {holdout_metrics.get('win_rate', 0):.1%}",
        f"  Sharpe:   {holdout_metrics.get('sharpe', 0):+.3f}",
        f"  Return:   {holdout_metrics.get('total_return', 0):+.1%}",
        "",
        "GO LIVE?",
        "  Paper-only until CLOB execution + slippage tests.",
        "  More trades fetched = longer backtest (use --max-trades).",
    ]
    ax3.text(0.04, 0.96, "\n".join(lines), va="top", fontsize=8.5, color="white", family="monospace")

    plt.savefig(path, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description="Whale-flow strategy backtest")
    parser.add_argument("--slug", default="gta-vi-released-before-june-2026")
    parser.add_argument("--min-trade-usd", type=float, default=500.0)
    parser.add_argument("--max-trades", type=int, default=8000)
    parser.add_argument("--flow-window", type=int, default=5)
    parser.add_argument("--min-flow-usd", type=float, default=5000.0)
    args = parser.parse_args()
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    meta = fetch_market_meta(args.slug) or {}
    cid = meta.get("conditionId") or DEFAULT_CONDITION_IDS.get(args.slug, "")
    end = pd.Timestamp.utcnow().strftime("%Y-%m-%d")

    print("=" * 65)
    print("  WHALE-FLOW STRATEGY BACKTEST")
    print("=" * 65)

    print("\n[1/4] Fetch whale trades (paginated) ...")
    trades = fetch_large_trades_history(
        min_cash_usd=args.min_trade_usd,
        market_slug=args.slug,
        condition_id=cid or None,
        max_trades=args.max_trades,
    )
    if trades.empty:
        print("    No trades — check slug / API.")
        return 1
    t0, t1 = trades["timestamp"].min(), trades["timestamp"].max()
    print(f"    Trades: {len(trades)}  from {t0} to {t1}")

    start = (t0 - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
    print("\n[2/4] Fetch Yes price history ...")
    ohlcv = fetch_polymarket_daily_ohlcv(args.slug, start, end)
    if ohlcv.empty:
        print("    CLOB/Gamma empty — building Yes % from whale trade prints (daily ffill).")
        prob = _prob_series_from_trades(trades)
    else:
        prob = ohlcv["Close"].dropna()
        prob.index = pd.to_datetime(prob.index).tz_localize(None).normalize()
    if prob.empty:
        print("    No price series.")
        return 1
    print(f"    Price bars: {len(prob)}  {prob.index.min().date()} → {prob.index.max().date()}")

    print("\n[3/4] Backtest + walk-forward ...")
    flow = daily_whale_flow(trades)
    flow = flow.reindex(prob.index).fillna(0)
    cfg = WhaleStrategyConfig(flow_window=args.flow_window, min_flow_usd=args.min_flow_usd)
    sig = whale_flow_signal(flow, cfg)
    full_r, tlog = backtest_whale_strategy(prob, sig)
    metrics = strategy_metrics(full_r, tlog)

    folds, oos_r, best_cfg = walk_forward_whale(prob, flow)
    oos_metrics = strategy_metrics(oos_r)

    split = int(len(prob) * 0.7)
    hold_idx = prob.index[split:]
    hold_r, hold_log = backtest_whale_strategy(prob.loc[hold_idx], sig.loc[hold_idx])
    holdout_metrics = strategy_metrics(hold_r, hold_log)

    print(f"    Full sample: win={metrics['win_rate']:.1%}  Sharpe={metrics['sharpe']:+.3f}  "
          f"ret={metrics['total_return']:+.1%}  trades={int(metrics['n_trades'])}")
    print(f"    WFO OOS:     win={oos_metrics['win_rate']:.1%}  Sharpe={oos_metrics['sharpe']:+.3f}  "
          f"ret={oos_metrics['total_return']:+.1%}  folds={len(folds)}")
    print(f"    Holdout 30%: win={holdout_metrics['win_rate']:.1%}  Sharpe={holdout_metrics['sharpe']:+.3f}  "
          f"ret={holdout_metrics['total_return']:+.1%}")

    print("\n[4/4] Save outputs ...")
    title = meta.get("question", args.slug)
    _render_chart(flow, prob, full_r, oos_r, folds, best_cfg, metrics, oos_metrics, holdout_metrics, SAVE_PNG, title)

    with open(SAVE_CSV, "w") as f:
        f.write("=== CONFIG ===\n")
        pd.DataFrame([cfg.__dict__]).to_csv(f, index=False)
        f.write("\n=== DATA ===\n")
        pd.DataFrame(
            [
                {
                    "n_trades": len(trades),
                    "trade_start": str(t0),
                    "trade_end": str(t1),
                    "n_price_bars": len(prob),
                    "price_start": str(prob.index.min().date()),
                    "price_end": str(prob.index.max().date()),
                }
            ]
        ).to_csv(f, index=False)
        f.write("\n=== FULL SAMPLE ===\n")
        pd.DataFrame([metrics]).to_csv(f, index=False)
        f.write("\n=== WALK FORWARD OOS ===\n")
        pd.DataFrame([oos_metrics]).to_csv(f, index=False)
        f.write("\n=== HOLDOUT 30pct ===\n")
        pd.DataFrame([holdout_metrics]).to_csv(f, index=False)
        f.write("\n=== FOLDS ===\n")
        folds.to_csv(f, index=False)

    print(f"  📊  {SAVE_PNG}")
    print(f"  📋  {SAVE_CSV}")
    print("=" * 65)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
