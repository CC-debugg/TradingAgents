#!/usr/bin/env python3
"""Patch repo-root .env for Kraken live trading (no nano required).

Usage (remote Mac):
  cd ~/TradingAgents
  python scripts/kraken_patch_live_env.py
  python scripts/kraken_patch_live_env.py --dry-run
"""

from __future__ import annotations

import argparse
import re
import shutil
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = REPO_ROOT / ".env"

# Keys we set for live 5-sleeve loop ($100 total ≈ $20/sleeve).
LIVE_DEFAULTS: dict[str, str] = {
    "KRAKEN_LIVE": "1",
    "KRAKEN_MEME_LIVE": "1",
    "KRAKEN_USE_MARGIN": "1",
    "KRAKEN_VALIDATE_ONLY": "0",
    "KRAKEN_MEME_NOTIONAL_USD": "100",
    "KRAKEN_MAX_ORDER_USD": "50",
    "KRAKEN_MAX_DAILY_NOTIONAL_USD": "2000",
    "KRAKEN_MIN_ORDER_USD": "5",
    "KRAKEN_NEWS_GATE": "1",
    "KRAKEN_MARGIN_LEVERAGE": "2",
}

_KEY_LINE = re.compile(r"^\s*#?\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Enable Kraken live flags in .env")
    p.add_argument("--dry-run", action="store_true", help="Print changes without writing")
    p.add_argument("--env", type=Path, default=ENV_PATH, help="Path to .env (default: repo .env)")
    return p.parse_args()


def patch_env(path: Path, updates: dict[str, str], *, dry_run: bool) -> None:
    if not path.is_file():
        raise SystemExit(f"ERROR: {path} not found — create it first (cp .env.example .env)")

    original = path.read_text(encoding="utf-8")
    lines = original.splitlines()
    keys = set(updates)
    kept: list[str] = []
    removed: list[str] = []

    for line in lines:
        m = _KEY_LINE.match(line)
        if m and m.group(1) in keys:
            removed.append(line)
            continue
        kept.append(line)

    while kept and kept[-1].strip() == "":
        kept.pop()

    block = ["", "# --- Kraken live (patched by kraken_patch_live_env.py) ---"]
    block.extend(f"{k}={v}" for k, v in updates.items())
    new_text = "\n".join(kept + block) + "\n"

    if dry_run:
        print(f"Would update {path}")
        for k, v in updates.items():
            print(f"  {k}={v}")
        if removed:
            print("\nWould remove/replace old lines:")
            for line in removed:
                print(f"  {line}")
        return

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_suffix(f".env.bak.{stamp}")
    shutil.copy2(path, backup)
    path.write_text(new_text, encoding="utf-8")
    print(f"Backup → {backup}")
    print(f"Patched → {path}")
    for k, v in updates.items():
        print(f"  {k}={v}")

    text = path.read_text(encoding="utf-8")
    for req in ("KRAKEN_API_KEY", "KRAKEN_API_SECRET"):
        if not re.search(rf"^{req}=.+", text, re.MULTILINE):
            print(f"\nWARN: {req} missing or empty — add your Kraken API credentials to .env")


def main() -> int:
    args = _parse_args()
    patch_env(args.env, LIVE_DEFAULTS, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
