#!/usr/bin/env python3
"""Verify Kraken REST connectivity and API credentials (no orders unless --live)."""

from __future__ import annotations

import argparse
import json
import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tradingagents.execution.load_env import load_repo_env  # noqa: E402

load_repo_env(REPO_ROOT)

from tradingagents.execution.kraken_spot import (  # noqa: E402
    credentials_configured,
    execute_kraken_intent,
    fetch_ticker_price,
    kraken_health_check,
    live_trading_enabled,
    resolve_pair,
)
from tradingagents.execution.polymarket_clob import OrderIntent  # noqa: E402
from tradingagents.execution.risk_limits import RiskLimits  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Kraken API health check")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Set KRAKEN_LIVE=1 and submit a tiny validation order path (still blocked unless size passes)",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="With --live, call AddOrder path in validate-only mode (no submit)",
    )
    parser.add_argument("--pair", default="DOGEUSD", help="Kraken pair for ticker probe")
    args = parser.parse_args()

    if args.live:
        os.environ["KRAKEN_LIVE"] = "1"
    if args.validate_only:
        os.environ["KRAKEN_VALIDATE_ONLY"] = "1"

    print("Kraken health check")
    print("=" * 50)
    health = kraken_health_check()
    print(json.dumps(health, indent=2))

    limits = RiskLimits.from_env()
    print("\nRisk limits:", limits)

    slug = "DOGE-USD" if "DOGE" in args.pair.upper() else "WIF-USD"
    pair = resolve_pair(slug) or args.pair
    try:
        px = fetch_ticker_price(pair)
        print(f"\nTicker {pair}: last={px}")
    except Exception as exc:
        print(f"\nTicker error: {exc}")

    if not credentials_configured():
        print("\nNo KRAKEN_API_KEY / KRAKEN_API_SECRET in environment.")
        print("Copy .env.example → .env and export keys (never commit).")
        return 0 if health.get("rest_reachable") else 1

    intent = OrderIntent(slug, "spot", "BUY", limits.min_order_usd, 0.0, "health_check")
    result = execute_kraken_intent(intent)
    print("\nSample intent (min size BUY):", json.dumps(result, indent=2))
    print(f"\nKRAKEN_LIVE={live_trading_enabled()}")
    return 0 if health.get("rest_reachable") else 1


if __name__ == "__main__":
    raise SystemExit(main())
