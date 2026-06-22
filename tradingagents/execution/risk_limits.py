"""Shared risk limits for live CEX / CLOB execution."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _notional_tracker_path() -> Path:
    root = os.environ.get("LIVE_DATA_DIR", "data/live")
    return Path(root) / "kraken_daily_notional.json"


@dataclass(frozen=True)
class RiskLimits:
    max_order_usd: float
    max_daily_notional_usd: float
    min_order_usd: float

    @classmethod
    def from_env(cls) -> RiskLimits:
        return cls(
            max_order_usd=_env_float("KRAKEN_MAX_ORDER_USD", 50.0),
            max_daily_notional_usd=_env_float("KRAKEN_MAX_DAILY_NOTIONAL_USD", 200.0),
            min_order_usd=_env_float("KRAKEN_MIN_ORDER_USD", 5.0),
        )


def check_order_notional(size_usd: float, limits: RiskLimits | None = None) -> tuple[bool, str]:
    limits = limits or RiskLimits.from_env()
    if size_usd < limits.min_order_usd:
        return False, f"below min order ${limits.min_order_usd:.2f}"
    if size_usd > limits.max_order_usd:
        return False, f"exceeds max order ${limits.max_order_usd:.2f}"
    return True, ""


def _load_daily_notional() -> dict[str, float]:
    path = _notional_tracker_path()
    if not path.is_file():
        return {}
    try:
        with path.open(encoding="utf-8") as f:
            raw = json.load(f)
        return {str(k): float(v) for k, v in raw.items()}
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return {}


def _save_daily_notional(data: dict[str, float]) -> None:
    path = _notional_tracker_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f)


def check_daily_notional(size_usd: float, limits: RiskLimits | None = None) -> tuple[bool, str]:
    limits = limits or RiskLimits.from_env()
    today = date.today().isoformat()
    spent = _load_daily_notional().get(today, 0.0)
    if spent + size_usd > limits.max_daily_notional_usd:
        return (
            False,
            f"daily cap ${limits.max_daily_notional_usd:.2f} (spent ${spent:.2f}, request ${size_usd:.2f})",
        )
    return True, ""


def record_daily_notional(size_usd: float) -> None:
    today = date.today().isoformat()
    data = _load_daily_notional()
    data[today] = data.get(today, 0.0) + size_usd
    _save_daily_notional(data)


def validate_order_size(size_usd: float, limits: RiskLimits | None = None) -> tuple[bool, str]:
    ok, msg = check_order_notional(size_usd, limits)
    if not ok:
        return ok, msg
    return check_daily_notional(size_usd, limits)
