#!/usr/bin/env python3
"""Repair a corrupted .env (e.g. terminal commands pasted into nano).

Finds Kraken API key/secret fragments, restores from backup if present,
then applies live-trading defaults via kraken_patch_live_env.

Usage:
  cd ~/TradingAgents
  python scripts/kraken_repair_env.py
"""

from __future__ import annotations

import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = REPO_ROOT / ".env"

# Obvious shell tokens that should never appear in .env values.
_SHELL_TOKENS = (
    "conda activate",
    "cd ~/TradingAgents",
    "cd /",
    "git pull",
    "python scripts/",
    "grep '^KRAKEN",
    "nohup ",
    "tail -",
    "pkill ",
)

_KEY_RE = re.compile(
    r"KRAKEN_API_KEY\s*=\s*([A-Za-z0-9/+]{20,}?)(?:conda|cd |git |python |grep |#|\s|$)",
    re.IGNORECASE,
)
_SECRET_RE = re.compile(
    r"KRAKEN_API_SECRET\s*=\s*([A-Za-z0-9/+=]{40,}?)(?:conda|cd |git |python |grep |#|\s|$)",
    re.IGNORECASE,
)
# Fallback: long base64-ish blob after mangled LIVE_ALPHA_SLEEVES=0
_SECRET_BLOB_RE = re.compile(r"LIVE_ALPHA_SLEEVES=0([A-Za-z0-9/+=]{40,})")


def _latest_backup() -> Path | None:
    backups = sorted(ENV_PATH.parent.glob(".env.bak*"), key=lambda p: p.stat().st_mtime, reverse=True)
    return backups[0] if backups else None


def _extract_credentials(text: str) -> tuple[str, str]:
    key = ""
    secret = ""
    m = _KEY_RE.search(text)
    if m:
        key = m.group(1)
    m = _SECRET_RE.search(text)
    if m:
        secret = m.group(1)
    if not secret:
        m = _SECRET_BLOB_RE.search(text)
        if m:
            secret = m.group(1)
    return key, secret


def _is_corrupted(text: str) -> bool:
    if any(tok in text for tok in _SHELL_TOKENS):
        return True
    if re.search(r"KRAKEN_LIVE=0*1{2,}", text):
        return True
    if "conda activate" in text.replace(" ", ""):
        return False
    return False


def _clean_template(key: str, secret: str) -> str:
  """Minimal valid .env for Kraken live; keeps unrelated keys out."""
  lines = [
      "# Repaired by scripts/kraken_repair_env.py — do not paste shell commands here.",
      "",
      f"KRAKEN_API_KEY={key}",
      f"KRAKEN_API_SECRET={secret}",
      "",
  ]
  return "\n".join(lines)


def main() -> int:
    if not ENV_PATH.is_file():
        print(f"ERROR: {ENV_PATH} not found", file=sys.stderr)
        return 1

    raw = ENV_PATH.read_text(encoding="utf-8", errors="replace")
    backup = _latest_backup()

    if backup and _is_corrupted(raw):
        print(f"Found backup: {backup}")
        print("Restoring from backup …")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(ENV_PATH, ENV_PATH.parent / f".env.corrupt.{stamp}")
        shutil.copy2(backup, ENV_PATH)
        raw = ENV_PATH.read_text(encoding="utf-8")

    if not _is_corrupted(raw):
        print(".env looks OK (no shell-command corruption detected).")
        print("Run: python scripts/kraken_patch_live_env.py")
        return 0

    key, secret = _extract_credentials(raw)
    if not key or not secret:
        print("ERROR: could not extract KRAKEN_API_KEY / KRAKEN_API_SECRET from corrupted file.", file=sys.stderr)
        print("Options:", file=sys.stderr)
        print("  1) cp .env.bak.TIMESTAMP .env   (if backup exists: ls -lt .env.bak*)", file=sys.stderr)
        print("  2) Re-copy key+secret from Kraken → Settings → API", file=sys.stderr)
        return 1

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(ENV_PATH, ENV_PATH.parent / f".env.corrupt.{stamp}")
    ENV_PATH.write_text(_clean_template(key, secret), encoding="utf-8")
    print(f"Saved corrupt copy → .env.corrupt.{stamp}")
    print("Wrote clean Kraken credentials block.")

    import subprocess

    subprocess.run([sys.executable, str(REPO_ROOT / "scripts/kraken_patch_live_env.py")], check=True)
    print("\nDone. Verify:")
    print("  grep '^KRAKEN_' .env | grep -v SECRET")
    print("  python scripts/kraken_health_check.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
