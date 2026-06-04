#!/usr/bin/env python3
"""
Daily ops pipeline (target: 16:00 America/New_York).

Runs live daily (PNG+CSV) then optional full research pipeline + master.

Usage:
  python scripts/polymarket_daily_ops.py              # live + tabs + master
  python scripts/polymarket_daily_ops.py --full       # + dashboard walkforward whale
  python scripts/polymarket_daily_ops.py --live-clob  # POLYMARKET_LIVE=1 on CLOB intents
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
NY = ZoneInfo("America/New_York")


def _run(script: str, extra: list[str] | None = None) -> int:
    cmd = [sys.executable, os.path.join(REPO_ROOT, "scripts", script)] + (extra or [])
    print(f"\n>>> {' '.join(cmd)}\n")
    return subprocess.call(cmd)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="Also run dashboard, walkforward, whale-arb")
    parser.add_argument("--live-clob", action="store_true", help="Enable POLYMARKET_LIVE=1 for CLOB")
    args = parser.parse_args()

    now = datetime.now(NY)
    print("=" * 65)
    print("  DAILY OPS · America/New_York")
    print(f"  Run time: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print("  Target schedule: 16:00 ET (configure cron/launchd separately)")
    print("=" * 65)

    live_args = ["--live"] if args.live_clob else []
    rc = _run("polymarket_live_daily.py", live_args)
    if args.full:
        rc |= _run("polymarket_meme_dashboard.py")
        rc |= _run("polymarket_walkforward_qlib.py")
        rc |= _run("polymarket_whale_arb_analysis.py")
        rc |= _run("polymarket_whale_strategy.py")
    rc |= _run("polymarket_multi_strategy_dashboard.py")
    rc |= _run("polymarket_master_dashboard.py")
    print("\nDone. Outputs: assets/dashboard_outputs/")
    return min(rc, 1)


if __name__ == "__main__":
    raise SystemExit(main())
