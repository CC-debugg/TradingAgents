#!/usr/bin/env python3
"""
Walk-forward OOS backtest + Qlib factor pipeline + outputs.

PDF requirements:
  1) Qlib data export + ML signal (qlib LGBModel if installed, else sklearn)
  2) Walking-forward: train less → test more, rolling OOS folds
  3) See integrations/solana_arbitrage for DEX arb (separate process)

Usage:
  python scripts/polymarket_walkforward_qlib.py
  python scripts/polymarket_walkforward_qlib.py --train-days 252 --test-days 63
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

from tradingagents.quant.polymarket_strategy import (
    DEFAULT_UNIVERSE,
    StrategyConfig,
    load_universe_prices,
    sharpe_ratio,
)
from tradingagents.quant.qlib_bridge import (
    build_factor_panel,
    export_qlib_csv,
    factor_attribution,
    qlib_available,
    render_factor_attribution_chart,
    train_signal_model,
)
from tradingagents.quant.walk_forward import WalkForwardConfig, run_walk_forward

OUTPUT_DIR = os.path.join(REPO_ROOT, "assets", "dashboard_outputs")
SAVE_CSV = os.path.join(OUTPUT_DIR, "polymarket_walkforward_metrics.csv")
SAVE_PNG = os.path.join(OUTPUT_DIR, "polymarket_walkforward_oos.png")
SAVE_ATTR_PNG = os.path.join(OUTPUT_DIR, "polymarket_factor_attribution.png")


def _load_macro(start: str, end: str) -> pd.DataFrame:
    import yfinance as yf

    tickers = {"MKT": "SPY", "RATES": "TLT", "COMMOD": "GLD", "USD": "UUP"}
    out = {}
    for name, tk in tickers.items():
        try:
            s = yf.download(tk, start=start, end=end, auto_adjust=True, progress=False)["Close"]
            out[name] = s.squeeze().pct_change()
        except Exception:
            pass
    if "DOGE-USD" not in out:
        try:
            d = yf.download("DOGE-USD", start=start, end=end, auto_adjust=True, progress=False)["Close"]
            out["CRYPTO"] = d.squeeze().pct_change()
        except Exception:
            pass
    return pd.DataFrame(out).dropna(how="all")


def main() -> int:
    parser = argparse.ArgumentParser(description="Walk-forward + Qlib bridge")
    parser.add_argument("--train-days", type=int, default=252, help="Train window (smaller)")
    parser.add_argument("--test-days", type=int, default=63, help="OOS test window (larger step)")
    parser.add_argument("--start", default="2020-01-01")
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    cfg = StrategyConfig(start=args.start, universe=DEFAULT_UNIVERSE)
    wf_cfg = WalkForwardConfig(
        train_days=args.train_days,
        test_days=args.test_days,
        step_days=args.test_days,
    )

    print("=" * 65)
    print("  WALK-FORWARD + QLIB  |  Polymarket + Meme")
    print("=" * 65)
    print(f"  Qlib installed: {qlib_available()}")
    print(f"  Train/Test: {wf_cfg.train_days}d / {wf_cfg.test_days}d  (rolling OOS)\n")

    print("[1/4] Loading prices ...")
    prices = load_universe_prices(cfg)
    for k in prices:
        print(f"    {k}: {len(prices[k])} bars")

    print("\n[2/4] Walking-forward optimization ...")
    folds, oos = run_walk_forward(prices, cfg, wf_cfg)
    if folds.empty:
        print("    No folds — shorten train_days or widen date range.")
        return 1

    oos_sh = sharpe_ratio(oos, cfg.risk_free)
    oos_tot = float((1 + oos).prod() - 1) if len(oos) else 0.0
    print(f"    Folds: {len(folds)}")
    print(f"    Stitched OOS Sharpe: {oos_sh:+.3f}")
    print(f"    Stitched OOS Total Return: {oos_tot:+.1%}")
    print(f"    Mean test Sharpe per fold: {folds['test_sharpe'].mean():+.3f}")

    print("\n[3/4] Qlib factor panel + export (research only — not used in WFO trades) ...")
    panel = build_factor_panel(prices)
    qlib_dir = export_qlib_csv(panel)
    print(f"    Panel rows: {len(panel)}  →  {qlib_dir}")
    model, features, backend = train_signal_model(panel)
    print(f"    Signal model: {backend}  (scores NOT wired into EMA backtest yet)")

    print("\n[4/4] Factor attribution (OOS strategy) ...")
    macro = _load_macro(args.start, cfg.end or pd.Timestamp.utcnow().strftime("%Y-%m-%d"))
    attr = factor_attribution(oos, macro)
    r2 = attr.attrs.get("r_squared", 0) if not attr.empty else 0
    if not attr.empty:
        render_factor_attribution_chart(
            attr,
            SAVE_ATTR_PNG,
            returns_label="walk-forward stitched OOS portfolio returns",
        )
        print(f"    Factor chart → {SAVE_ATTR_PNG}  (R²={r2:.3f})")

    # Chart
    plt.style.use("dark_background")
    fig, axes = plt.subplots(2, 1, figsize=(14, 9), facecolor="#0D1117")
    cum = (1 + oos.fillna(0)).cumprod()
    axes[0].plot(cum.index, cum, color="#00FF88", lw=1.8, label="Stitched OOS equity")
    axes[0].axhline(1, color="#7A8899", lw=0.5)
    axes[0].set_title(
        f"Walk-Forward OOS  ·  Sharpe {oos_sh:+.2f}  ·  {len(folds)} folds",
        fontweight="bold",
    )
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    axes[1].bar(range(len(folds)), folds["test_sharpe"], color="#00D4FF", alpha=0.85)
    axes[1].axhline(0, color="#7A8899", lw=0.6)
    axes[1].set_title("Per-fold OOS Sharpe (test window)", fontweight="bold")
    axes[1].set_xlabel("Fold #")
    plt.tight_layout()
    plt.savefig(SAVE_PNG, dpi=150, bbox_inches="tight", facecolor="#0D1117")
    plt.close(fig)

    with open(SAVE_CSV, "w") as f:
        folds.to_csv(f, index=False)
        f.write("\n=== OOS SUMMARY ===\n")
        pd.DataFrame(
            [
                {
                    "oos_sharpe": oos_sh,
                    "oos_total_return": oos_tot,
                    "n_folds": len(folds),
                    "mean_fold_test_sharpe": folds["test_sharpe"].mean(),
                    "qlib_installed": qlib_available(),
                    "signal_backend": backend,
                }
            ]
        ).to_csv(f, index=False)
        f.write("\n=== FACTOR ATTRIBUTION ===\n")
        if not attr.empty:
            attr[["factor", "beta", "contrib_ann"]].to_csv(f, index=False)
            f.write(f"\nR_squared,{r2}\n")
        f.write(f"\n=== QLIB DATA ===\nqlib_data_dir,{qlib_dir}\n")

    print(f"\n  ✅  {SAVE_PNG}")
    if os.path.isfile(SAVE_ATTR_PNG):
        print(f"  ✅  {SAVE_ATTR_PNG}")
    print(f"  ✅  {SAVE_CSV}")
    print("=" * 65)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
