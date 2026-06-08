"""Live paper book: $1M from sim start date → PnL on dashboard."""

from __future__ import annotations

import os

import pandas as pd
DEFAULT_CAPITAL = 1_000_000.0


def sim_start_date() -> str:
    raw = os.environ.get("LIVE_SIM_START", "").strip()
    if raw:
        return raw
    # Default paper book start (override via LIVE_SIM_START)
    return "2026-06-04"


def sim_capital() -> float:
    raw = os.environ.get("LIVE_SIM_CAPITAL", "").strip()
    try:
        return float(raw) if raw else DEFAULT_CAPITAL
    except ValueError:
        return DEFAULT_CAPITAL


def portfolio_pnl_snapshot(
    daily_returns: pd.Series,
    start: str | None = None,
    capital: float | None = None,
) -> dict:
    """PnL from sim start on a daily return series."""
    start = start or sim_start_date()
    capital = capital if capital is not None else sim_capital()
    all_r = daily_returns.dropna().sort_index()
    if all_r.empty:
        return {
            "sim_start": start,
            "official_sim_start": start,
            "sim_capital_usd": capital,
            "pnl_usd": 0.0,
            "pnl_pct": 0.0,
            "equity_usd": capital,
            "n_days": 0,
            "equity_curve": [],
            "status": "no_data",
            "note": "No return series yet — refresh after price feeds load.",
        }

    start_ts = pd.Timestamp(start).normalize()
    last_ts = pd.Timestamp(all_r.index[-1]).normalize()
    today = pd.Timestamp.today().normalize()

    r = all_r.loc[start_ts:]
    status = "live"
    note = ""
    official_start = start

    if r.empty and start_ts > last_ts:
        # Official book start is in the future — show preview on recent history.
        preview_days = min(90, len(all_r))
        r = all_r.tail(preview_days)
        status = "preview"
        days_until = int((start_ts - today).days)
        note = (
            f"Official ${capital/1e6:.1f}M book starts {start} "
            f"({days_until} day(s) away). Preview uses last {len(r)} trading days."
        )

    if r.empty:
        return {
            "sim_start": start,
            "official_sim_start": official_start,
            "sim_capital_usd": capital,
            "pnl_usd": 0.0,
            "pnl_pct": 0.0,
            "equity_usd": capital,
            "n_days": 0,
            "equity_curve": [],
            "status": "pending_start",
            "days_until_start": max(0, int((start_ts - today).days)),
            "note": note or f"Paper book begins {start}.",
        }

    cum = (1 + r).cumprod()
    equity = capital * cum
    pnl = float(equity.iloc[-1] - capital)
    curve = []
    step = max(1, len(equity) // 120)
    for dt, v in equity.iloc[::step].items():
        curve.append({"t": str(pd.Timestamp(dt).date()), "v": round(float(v), 2)})

    out = {
        "sim_start": str(r.index[0].date()) if status == "preview" else start,
        "official_sim_start": official_start,
        "sim_capital_usd": capital,
        "pnl_usd": round(pnl, 2),
        "pnl_pct": round(pnl / capital, 4),
        "equity_usd": round(float(equity.iloc[-1]), 2),
        "n_days": int(len(r)),
        "last_date": str(r.index[-1].date()),
        "equity_curve": curve,
        "status": status,
    }
    if note:
        out["note"] = note
    if status == "preview":
        out["days_until_start"] = max(0, int((start_ts - today).days))
    return out
