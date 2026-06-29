#!/usr/bin/env python3
"""
Polymarket + Meme Coins project runner.

Combines resources from QuantFin_RiskManagement.pdf:
  - TradingAgents (multi-agent LLM) — this repo
  - NautilusTrader / Polymarket CLOB — prediction market OHLCV
  - Quant dashboard — trend following + volatility targeting

Usage:
  python scripts/polymarket_meme_run.py dashboard
  python scripts/polymarket_meme_run.py walkforward
  python scripts/polymarket_meme_run.py whale-arb
  python scripts/polymarket_meme_run.py whale-strategy
  python scripts/polymarket_meme_run.py multi-strategy
  python scripts/polymarket_meme_run.py daily-ops
  python scripts/polymarket_meme_run.py live-daily
  python scripts/polymarket_meme_run.py live-app
  python scripts/polymarket_meme_run.py master
  python scripts/polymarket_meme_run.py solana-setup
  python scripts/polymarket_meme_run.py agents --ticker DOGE-USD --date 2025-05-01
  python scripts/polymarket_meme_run.py all --ticker DOGE-USD --date 2025-05-01
"""

from __future__ import annotations

import argparse
import copy
import os
import subprocess
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

MEME_TICKERS = [
    "DOGE-USD",
    "SHIB-USD",
    "PEPE24478-USD",
    "WIF-USD",
    "BONK-USD",
    "UMA-USD",
]


def run_dashboard() -> int:
    script = os.path.join(REPO_ROOT, "scripts", "polymarket_meme_dashboard.py")
    print("Running quantitative dashboard ...\n")
    return subprocess.call([sys.executable, script])


def run_walkforward() -> int:
    script = os.path.join(REPO_ROOT, "scripts", "polymarket_walkforward_qlib.py")
    print("Running walk-forward + Qlib pipeline ...\n")
    return subprocess.call([sys.executable, script])


def run_solana_setup() -> int:
    script = os.path.join(REPO_ROOT, "scripts", "solana_arb_bridge.py")
    return subprocess.call([sys.executable, script, "setup"])


def run_whale_arb() -> int:
    script = os.path.join(REPO_ROOT, "scripts", "polymarket_whale_arb_analysis.py")
    print("Running Polymarket whale + arbitrage analysis ...\n")
    return subprocess.call([sys.executable, script])


def run_fifa_research() -> int:
    script = os.path.join(REPO_ROOT, "scripts", "polymarket_fifa_research.py")
    print("Running FIFA / World Cup Polymarket strategy scan + backtest ...\n")
    return subprocess.call([sys.executable, script])


def run_whale_strategy() -> int:
    script = os.path.join(REPO_ROOT, "scripts", "polymarket_whale_strategy.py")
    print("Running whale-flow strategy backtest (win rate + WFO) ...\n")
    return subprocess.call([sys.executable, script])


def run_multi_strategy() -> int:
    script = os.path.join(REPO_ROOT, "scripts", "polymarket_multi_strategy_dashboard.py")
    print("Running multi-strategy tabs (Ang macro factors per strategy) ...\n")
    return subprocess.call([sys.executable, script])


def run_daily_ops() -> int:
    script = os.path.join(REPO_ROOT, "scripts", "polymarket_daily_ops.py")
    print("Running daily ops pipeline (NY 16:00 target) ...\n")
    return subprocess.call([sys.executable, script])


def run_live_daily() -> int:
    script = os.path.join(REPO_ROOT, "scripts", "polymarket_live_daily.py")
    print("Running live daily update (Barra tabs + news + CLOB intents) ...\n")
    return subprocess.call([sys.executable, script])


def run_live_app(public: bool = False) -> int:
    script = os.path.join(REPO_ROOT, "scripts", "serve_polymarket_live.py")
    print("Starting interactive LIVE dashboard (browser) ...\n")
    cmd = [sys.executable, script]
    if public:
        cmd.append("--public")
    return subprocess.call(cmd)


def run_master_dashboard() -> int:
    script = os.path.join(REPO_ROOT, "scripts", "polymarket_master_dashboard.py")
    print("Building master dashboard (all PNG outputs) ...\n")
    return subprocess.call([sys.executable, script])


def run_agents(ticker: str, trade_date: str, debug: bool) -> int:
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    config = copy.deepcopy(DEFAULT_CONFIG)
    config["data_vendors"] = dict(config.get("data_vendors", {}))
    config["data_vendors"]["core_stock_apis"] = "nautilus"
    config["global_news_queries"] = [
        "Bitcoin Ethereum meme coin regulation SEC",
        "Polymarket prediction markets election crypto policy",
        "Solana DeFi funding rates whale wallet flows",
        "Federal Reserve risk assets crypto correlation",
    ]

    print(f"TradingAgents analysis: {ticker} @ {trade_date}\n")
    ta = TradingAgentsGraph(debug=debug, config=config)
    _, decision = ta.propagate(ticker, trade_date)
    print("\n=== Decision ===\n")
    print(decision)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Polymarket + Meme Coins project (TradingAgents + quant dashboard)"
    )
    parser.add_argument(
        "command",
        choices=[
            "dashboard",
            "walkforward",
            "whale-arb",
            "whale-strategy",
            "fifa-research",
            "multi-strategy",
            "daily-ops",
            "live-daily",
            "live-app",
            "master",
            "solana-setup",
            "agents",
            "all",
        ],
        help="dashboard | walkforward | whale-arb | whale-strategy | multi-strategy | daily-ops | master | ...",
    )
    parser.add_argument("--ticker", default="DOGE-USD", help="yfinance-style crypto ticker")
    parser.add_argument("--date", default="2025-05-01", help="trade date YYYY-MM-DD")
    parser.add_argument("--debug", action="store_true", help="verbose agent graph")
    parser.add_argument(
        "--public",
        action="store_true",
        help="live-app only: bind 0.0.0.0 for LAN/cloud deploy",
    )
    args = parser.parse_args()

    if args.command == "walkforward":
        return run_walkforward()

    if args.command == "whale-arb":
        return run_whale_arb()

    if args.command == "whale-strategy":
        return run_whale_strategy()

    if args.command == "fifa-research":
        return run_fifa_research()

    if args.command == "multi-strategy":
        return run_multi_strategy()

    if args.command == "daily-ops":
        return run_daily_ops()

    if args.command == "live-daily":
        return run_live_daily()

    if args.command == "live-app":
        return run_live_app(public=args.public)

    if args.command == "master":
        return run_master_dashboard()

    if args.command == "solana-setup":
        return run_solana_setup()

    if args.command in ("dashboard", "all"):
        rc = run_dashboard()
        if rc != 0:
            return rc

    if args.command == "all":
        for fn in (run_dashboard, run_walkforward, run_whale_arb, run_whale_strategy):
            rc = fn()
            if rc != 0:
                return rc
        rc = run_master_dashboard()
        if rc != 0:
            return rc
        return run_agents(args.ticker, args.date, args.debug)

    if args.command == "agents":
        return run_agents(args.ticker, args.date, args.debug)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
