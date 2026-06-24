"""Load repo-root .env for CLI scripts (works without python-dotenv)."""

from __future__ import annotations

import os
from pathlib import Path


def load_repo_env(repo_root: str | Path | None = None) -> bool:
    """Load TradingAgents/.env into os.environ. Returns True if file found."""
    root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[2]
    env_path = root / ".env"
    if not env_path.is_file():
        return False

    try:
        from dotenv import load_dotenv

        load_dotenv(env_path, override=False)
        return True
    except ImportError:
        pass

    with env_path.open(encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
    return True
