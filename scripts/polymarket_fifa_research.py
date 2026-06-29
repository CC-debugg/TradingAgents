#!/usr/bin/env python3
"""Scan FIFA / World Cup 2026 Polymarket markets; backtest whale + shock MR; pick live candidate.

Usage:
  python scripts/polymarket_fifa_research.py
  python scripts/polymarket_fifa_research.py --top 8 --max-trades 4000
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tradingagents.dataflows.polymarket_discovery import fetch_active_markets
from tradingagents.dataflows.polymarket_gamma import fetch_polymarket_daily_ohlcv, resolve_market_slug
from tradingagents.dataflows.polymarket_whale import fetch_large_trades_history
from tradingagents.quant.alpha_sleeves import poly_mean_reversion_returns
from tradingagents.quant.whale_strategy import (
    WhaleStrategyConfig,
    backtest_whale_strategy,
    daily_whale_flow,
    strategy_metrics,
    whale_flow_signal_v2,
)

NY = ZoneInfo("America/New_York")
OUTPUT_DIR = os.path.join(REPO_ROOT, "assets", "dashboard_outputs")
SAVE_CSV = os.path.join(OUTPUT_DIR, "polymarket_fifa_research.csv")
SAVE_JSON = os.path.join(OUTPUT_DIR, "polymarket_fifa_live_pick.json")

FIFA_KEYWORDS = ("fifa", "world cup", "world-cup")


def _volume(m: dict) -> float:
    for key in ("volumeNum", "volume", "volume24hr"):
        raw = m.get(key)
        if raw is None:
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return 0.0


def discover_fifa_markets(limit: int = 40) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for kw in FIFA_KEYWORDS:
        for m in fetch_active_markets(limit=100, keyword=kw):
            slug = (m.get("slug") or "").strip()
            if not slug or slug in seen:
                continue
            seen.add(slug)
            out.append(m)
    out.sort(key=_volume, reverse=True)
    return out[:limit]


def _prob_from_trades(trades: pd.DataFrame) -> pd.Series:
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


def _load_market_series(slug: str, start: str, end: str, max_trades: int) -> tuple[pd.Series, pd.DataFrame]:
    meta = resolve_market_slug(slug)
    if not meta:
        raise ValueError(f"unknown slug: {slug}")
    trades = fetch_large_trades_history(
        market_slug=slug,
        max_trades=max_trades,
        min_cash_usd=500.0,
    )
    try:
        ohlc = fetch_polymarket_daily_ohlcv(slug, start, end)
        prob = ohlc["Close"].dropna().sort_index() if ohlc is not None and not ohlc.empty else pd.Series(dtype=float)
    except Exception:
        prob = pd.Series(dtype=float)
    if prob.empty:
        prob = _prob_from_trades(trades)
    flow = daily_whale_flow(trades)
    return prob, flow


def _oos_metrics(returns: pd.Series, oos_days: int = 30) -> dict[str, float]:
    r = returns.dropna()
    if len(r) <= oos_days + 5:
        return strategy_metrics(r)
    split = r.index[-oos_days]
    oos = r[r.index >= split]
    return strategy_metrics(oos)


def backtest_market(slug: str, start: str, end: str, max_trades: int) -> list[dict]:
    prob, flow = _load_market_series(slug, start, end, max_trades)
    if len(prob) < 40:
        return []

    cfg = WhaleStrategyConfig(flow_window=5, min_flow_usd=8000.0, min_whale_trades=3)
    sig = whale_flow_signal_v2(flow, prob, cfg)
    whale_r, whale_log = backtest_whale_strategy(prob, sig)
    shock_r = poly_mean_reversion_returns(prob, shock=0.025, hold_days=3)

    rows = []
    for name, rets in (("whale_flow_v2", whale_r), ("poly_shock_mr", shock_r)):
        full = strategy_metrics(rets, whale_log if name == "whale_flow_v2" else None)
        oos = _oos_metrics(rets)
        score = float(oos.get("sharpe", 0)) * (1.0 if oos.get("total_return", 0) >= 0 else -0.5)
        rows.append(
            {
                "slug": slug,
                "strategy": name,
                "n_days": int(full.get("n_days", 0)),
                "n_trades": int(full.get("n_trades", 0)),
                "win_rate": round(float(full.get("win_rate", 0)), 4),
                "sharpe_full": round(float(full.get("sharpe", 0)), 3),
                "return_full_pct": round(float(full.get("total_return", 0)) * 100, 2),
                "sharpe_oos_30d": round(float(oos.get("sharpe", 0)), 3),
                "return_oos_30d_pct": round(float(oos.get("total_return", 0)) * 100, 2),
                "max_dd_pct": round(float(full.get("max_dd", 0)) * 100, 2),
                "score": round(score, 3),
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="FIFA 2026 Polymarket strategy scan + backtest")
    parser.add_argument("--top", type=int, default=10, help="Top N markets by volume")
    parser.add_argument("--max-trades", type=int, default=4000, help="Whale trade fetch cap per market")
    parser.add_argument("--oos-days", type=int, default=30, help="OOS window (days)")
    args = parser.parse_args()

    end = datetime.now(NY).strftime("%Y-%m-%d")
    start = (datetime.now(NY) - timedelta(days=330)).strftime("%Y-%m-%d")

    markets = discover_fifa_markets(limit=args.top)
    if not markets:
        print("ERROR: no FIFA markets found on Gamma API")
        return 1

    print("=" * 72)
    print("  FIFA / World Cup 2026 — Polymarket strategy research")
    print(f"  Window: {start} → {end}  |  markets: {len(markets)}")
    print("=" * 72)

    all_rows: list[dict] = []
    for i, m in enumerate(markets, 1):
        slug = m.get("slug") or ""
        q = (m.get("question") or slug)[:70]
        vol = _volume(m)
        print(f"\n[{i}/{len(markets)}] {q}  vol≈${vol:,.0f}")
        try:
            rows = backtest_market(slug, start, end, args.max_trades)
            for r in rows:
                r["question"] = m.get("question") or ""
                r["volume_usd"] = vol
                print(
                    f"    {r['strategy']:16}  OOS Sharpe {r['sharpe_oos_30d']:+.2f}  "
                    f"OOS ret {r['return_oos_30d_pct']:+.1f}%  trades {r['n_trades']}"
                )
            all_rows.extend(rows)
        except Exception as exc:
            print(f"    SKIP: {exc}")

    if not all_rows:
        print("\nERROR: no backtest rows")
        return 1

    df = pd.DataFrame(all_rows)

    def _live_score(row: pd.Series) -> float:
        sharpe = float(row["sharpe_oos_30d"])
        ret = float(row["return_oos_30d_pct"])
        vol = float(row.get("volume_usd") or 0)
        score = sharpe
        if row["strategy"] == "whale_flow_v2":
            score *= 1.15
        if vol >= 90_000_000:
            score *= 1.1
        elif vol < 50_000_000:
            score *= 0.6
        # Longshot % returns (penny contracts) inflate MR backtests — down-rank.
        if ret > 80:
            score *= 0.35
        if int(row.get("n_trades") or 0) < 8:
            score *= 0.7
        return score

    df["live_score"] = df.apply(_live_score, axis=1)
    df = df.sort_values("live_score", ascending=False)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    df.to_csv(SAVE_CSV, index=False)

    best = df.iloc[0].to_dict()
    pick = {
        "generated_at": datetime.now(NY).isoformat(),
        "recommended_slug": best["slug"],
        "recommended_strategy": best["strategy"],
        "question": best.get("question", ""),
        "volume_usd": best.get("volume_usd", 0),
        "oos_sharpe": best.get("sharpe_oos_30d"),
        "oos_return_pct": best.get("return_oos_30d_pct"),
        "live_env": {
            "POLYMARKET_MARKET_SLUG": best["slug"],
            "POLYMARKET_LIVE_NOTIONAL_USD": "50",
            "LIVE_NOTIONAL_USD": "50",
            "LIVE_MAX_TRADES": str(args.max_trades),
        },
        "next_steps": [
            "Fund Polymarket ~$50-100 USDC (Polygon)",
            "Manual trade once + export private key",
            f"python scripts/polymarket_whale_strategy.py --slug {best['slug']}",
            "POLYMARKET_LIVE=1 after dry-run",
        ],
    }
    with open(SAVE_JSON, "w", encoding="utf-8") as f:
        json.dump(pick, f, indent=2)

    print("\n" + "=" * 72)
    print("  TOP 5 (by OOS score)")
    print("=" * 72)
    cols = ["strategy", "slug", "sharpe_oos_30d", "return_oos_30d_pct", "n_trades", "score"]
    print(df[["strategy", "slug", "sharpe_oos_30d", "return_oos_30d_pct", "n_trades", "live_score"]].head(5).to_string(index=False))

    print(f"\nCSV  → {SAVE_CSV}")
    print(f"PICK → {SAVE_JSON}")
    print(f"\nRECOMMENDED LIVE: {best['strategy']} on slug:\n  {best['slug']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
