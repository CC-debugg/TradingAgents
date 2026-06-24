#!/usr/bin/env python3
"""Kraken live loop — 5 meme sleeves (DOGE/WIF) with optional margin.

Phases (run in order before --live):
  1. python scripts/kraken_health_check.py
  2. python scripts/kraken_meme_live_loop.py --once              # dry-run
  3. python scripts/kraken_meme_live_loop.py --once --validate   # Kraken validate-only
  4. python scripts/kraken_meme_live_loop.py --interval 300    # live loop (KRAKEN_LIVE=1 in .env)

Requires .env (never commit):
  KRAKEN_API_KEY, KRAKEN_API_SECRET
  KRAKEN_LIVE=1
  KRAKEN_USE_MARGIN=1
  KRAKEN_MEME_LIVE=1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tradingagents.execution.load_env import load_repo_env  # noqa: E402

load_repo_env(REPO_ROOT)

from tradingagents.execution.kraken_meme_live import (  # noqa: E402
    KRAKEN_MEME_SLEEVE_IDS,
    kraken_meme_live_enabled,
    run_kraken_meme_cycle,
)
from tradingagents.execution.kraken_spot import credentials_configured, kraken_health_check, live_trading_enabled

NY = ZoneInfo("America/New_York")
LOG_DIR = REPO_ROOT / "data" / "live"


def _log_path() -> Path:
    return LOG_DIR / "kraken_meme_loop.jsonl"


def _append_log(record: dict) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with _log_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


def _load_prices(bundle: dict) -> tuple[pd.Series, pd.Series]:
    prices = bundle.get("prices") or {}
    doge = prices.get("DOGE")
    wif = prices.get("WIF")
    if doge is None or wif is None or len(doge) < 30 or len(wif) < 30:
        raise RuntimeError("missing DOGE/WIF price history — check yfinance / network")
    return doge, wif


def _load_prices_quick(days: int = 90) -> tuple[pd.Series, pd.Series]:
    """Fast path: DOGE/WIF only (yfinance if available, else Kraken public OHLC)."""
    end = datetime.now(NY)
    start = end - pd.Timedelta(days=days)
    out: dict[str, pd.Series] = {}

    try:
        import yfinance as yf

        for sym in ("DOGE-USD", "WIF-USD"):
            label = sym.split("-")[0]
            print(f"  downloading {sym} (yfinance) ...", flush=True)
            df = yf.download(sym, start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"), progress=False)
            if df is None or df.empty:
                raise RuntimeError(f"yfinance returned no data for {sym}")
            col = "Close" if "Close" in df.columns else df.columns[0]
            s = df[col].dropna()
            if isinstance(s, pd.DataFrame):
                s = s.iloc[:, 0]
            s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
            out[label] = s
    except Exception as exc:
        print(f"  yfinance unavailable ({exc}); using Kraken public OHLC ...", flush=True)
        import requests

        for pair, label in (("DOGEUSD", "DOGE"), ("WIFUSD", "WIF")):
            print(f"  downloading {pair} (Kraken) ...", flush=True)
            r = requests.get(
                "https://api.kraken.com/0/public/OHLC",
                params={"pair": pair, "interval": 1440},
                timeout=60,
            )
            r.raise_for_status()
            res = r.json()["result"]
            key = [k for k in res if k != "last"][0]
            rows = res[key]
            idx = pd.to_datetime([row[0] for row in rows], unit="s", utc=True).tz_convert(None).normalize()
            out[label] = pd.Series([float(row[4]) for row in rows], index=idx).sort_index()

    doge, wif = out.get("DOGE"), out.get("WIF")
    if doge is None or wif is None or len(doge) < 30 or len(wif) < 30:
        raise RuntimeError("insufficient DOGE/WIF history")
    return doge, wif


def run_once(*, dry_run: bool, validate_only: bool, quick: bool = False) -> int:
    if validate_only:
        os.environ["KRAKEN_VALIDATE_ONLY"] = "1"

    now = datetime.now(NY)
    print("=" * 60)
    print("  KRAKEN MEME LIVE — 5 sleeves")
    print(f"  {now.strftime('%Y-%m-%d %H:%M %Z')}")
    print(f"  sleeves: {', '.join(KRAKEN_MEME_SLEEVE_IDS)}")
    print("=" * 60)

    health = kraken_health_check()
    print("\nHealth:", json.dumps(health, indent=2))

    if not health.get("rest_reachable"):
        print("ERROR: Kraken REST unreachable")
        return 1
    if not credentials_configured():
        print("ERROR: set KRAKEN_API_KEY + KRAKEN_API_SECRET in .env")
        return 1

    end = now.strftime("%Y-%m-%d")
    start = (now - pd.Timedelta(days=120)).strftime("%Y-%m-%d")
    if quick:
        print(f"\n[quick] Fetching DOGE/WIF only (~90d, no Polymarket whale) ...", flush=True)
        doge, wif = _load_prices_quick()
    else:
        from tradingagents.quant.live_strategies import fetch_live_data_bundle

        print(f"\nFetching full bundle {start} → {end} (can take 2–5 min) ...", flush=True)
        bundle = fetch_live_data_bundle(start, end)
        doge, wif = _load_prices(bundle)

    effective_dry = dry_run or not live_trading_enabled()
    if not effective_dry and not kraken_meme_live_enabled():
        print("WARN: KRAKEN_LIVE=1 but KRAKEN_MEME_LIVE not set — enabling for this run")
        os.environ["KRAKEN_MEME_LIVE"] = "1"

    pack = run_kraken_meme_cycle(doge, wif, dry_run=effective_dry)

    print(f"\nNotional ${pack['notional_usd']} · ${pack['notional_per_sleeve_usd']}/sleeve")
    print(f"News gate: {pack.get('news_gate', {})}")
    print(f"Raw intents: {len(pack.get('raw_intents', []))} · Netted: {len(pack.get('netted_intents', []))}")

    for row in pack.get("execution") or []:
        print(
            f"  {row.get('status'):10} {row.get('side')} {row.get('market')} "
            f"${row.get('size_usd')} — {row.get('message', '')[:80]}"
        )

    record = {
        "ts": now.isoformat(),
        "dry_run": effective_dry,
        "kraken_live": live_trading_enabled(),
        "margin": os.environ.get("KRAKEN_USE_MARGIN", "0"),
        "notional_usd": pack.get("notional_usd"),
        "news_gate": pack.get("news_gate"),
        "signals": pack.get("signals"),
        "execution": pack.get("execution"),
        "netted_intents": [i.__dict__ if hasattr(i, "__dict__") else i for i in pack.get("netted_intents", [])],
    }
    _append_log(record)
    print(f"\nLog → {_log_path()}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Kraken 5-sleeve meme live loop")
    parser.add_argument("--once", action="store_true", help="Single cycle then exit")
    parser.add_argument("--interval", type=int, default=300, help="Seconds between cycles (default 300)")
    parser.add_argument("--dry-run", action="store_true", help="Force dry-run even if KRAKEN_LIVE=1")
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Kraken validate-only path (KRAKEN_VALIDATE_ONLY=1)",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Fast dry-run: yfinance DOGE/WIF only (skip Polymarket whale fetch)",
    )
    args = parser.parse_args()

    if args.once or args.interval <= 0:
        return run_once(dry_run=args.dry_run, validate_only=args.validate, quick=args.quick)

    print(f"Starting loop every {args.interval}s (Ctrl+C to stop)")
    while True:
        try:
            code = run_once(dry_run=args.dry_run, validate_only=args.validate, quick=args.quick)
            if code != 0:
                print(f"Cycle failed ({code}), retrying in {args.interval}s")
        except KeyboardInterrupt:
            print("\nStopped.")
            return 0
        except Exception as exc:
            print(f"ERROR: {exc}")
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
