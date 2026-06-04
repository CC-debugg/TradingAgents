#!/usr/bin/env python3
"""
Bridge to PDF Solana arbitrage repos — implements #3 ChangeYourself0613 (Rust/Jito).

Usage:
  python scripts/solana_arb_bridge.py setup
  python scripts/solana_arb_bridge.py clone
  python scripts/solana_arb_bridge.py doctor
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
INTEGRATION_DIR = os.path.join(REPO_ROOT, "integrations", "solana_arbitrage")
VENDOR_DIR = os.path.join(INTEGRATION_DIR, "vendor", "Solana-Arbitrage-Bot")

SELECTED = {
    "name": "ChangeYourself0613/Solana-Arbitrage-Bot",
    "url": "https://github.com/ChangeYourself0613/Solana-Arbitrage-Bot",
    "dexs": "Raydium, Orca, Meteora, Jupiter",
    "stack": "Rust/Anchor, Jito-MEV",
}

ALTERNATIVES = [
    {
        "name": "WSOL12/Solana-Arbitrage-Bot",
        "url": "https://github.com/WSOL12/Solana-Arbitrage-Bot",
        "note": "JS, pump.fun, Jito gRPC",
    },
    {
        "name": "0xNineteen/solana-arbitrage-bot",
        "url": "https://github.com/0xNineteen/solana-arbitrage-bot",
        "note": "Lightweight JS multi-DEX",
    },
]


def cmd_setup() -> int:
    print("=" * 60)
    print("  Solana Arb — selected implementation")
    print("=" * 60)
    print(f"  Repo:   {SELECTED['name']}")
    print(f"  URL:    {SELECTED['url']}")
    print(f"  DEXs:   {SELECTED['dexs']}")
    print(f"  Stack:  {SELECTED['stack']}")
    print("\n  Alternatives (PDF, not installed):")
    for alt in ALTERNATIVES:
        print(f"    - {alt['name']}: {alt['note']}")
    env_ex = os.path.join(INTEGRATION_DIR, ".env.example")
    print(f"\n  Env template: {env_ex}")
    print("  Next: python scripts/solana_arb_bridge.py clone")
    print("        python scripts/solana_arb_bridge.py doctor")
    return 0


def cmd_clone() -> int:
    if os.path.isdir(os.path.join(VENDOR_DIR, ".git")):
        print(f"Already cloned: {VENDOR_DIR}")
        return 0
    os.makedirs(os.path.dirname(VENDOR_DIR), exist_ok=True)
    print(f"Cloning {SELECTED['url']} ...")
    rc = subprocess.call(
        ["git", "clone", "--depth", "1", SELECTED["url"], VENDOR_DIR],
        cwd=REPO_ROOT,
    )
    if rc == 0:
        print(f"  ✅  {VENDOR_DIR}")
        print("  Build/run per upstream README (cargo build --release).")
    return rc


def cmd_doctor() -> int:
    tools = ["git", "rustc", "cargo", "solana"]
    print("Toolchain check:")
    for t in tools:
        path = shutil.which(t)
        print(f"  {t:<8} {'OK ' + path if path else 'MISSING'}")
    if os.path.isdir(VENDOR_DIR):
        print(f"\nVendor repo: present at {VENDOR_DIR}")
    else:
        print("\nVendor repo: not cloned — run: solana_arb_bridge.py clone")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Solana DEX arb bridge (PDF #3)")
    parser.add_argument("command", choices=["setup", "clone", "doctor"])
    args = parser.parse_args()
    if args.command == "setup":
        return cmd_setup()
    if args.command == "clone":
        return cmd_clone()
    return cmd_doctor()


if __name__ == "__main__":
    raise SystemExit(main())
