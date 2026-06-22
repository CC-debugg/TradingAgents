"""Binance public spot market data (no API key required)."""

from __future__ import annotations

import pandas as pd
import requests

BINANCE_API = "https://api.binance.com/api/v3/klines"


def fetch_binance_daily_close(
    symbol: str = "DOGEUSDT",
    start: str | None = None,
    end: str | None = None,
    interval: str = "1d",
) -> pd.Series:
    """Daily close prices from Binance klines."""
    params: dict = {"symbol": symbol.upper(), "interval": interval, "limit": 1000}
    if start:
        params["startTime"] = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    if end:
        params["endTime"] = int((pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)).timestamp() * 1000)

    r = requests.get(BINANCE_API, params=params, timeout=25)
    r.raise_for_status()
    rows = r.json()
    if not isinstance(rows, list) or not rows:
        return pd.Series(dtype=float)

    idx = pd.to_datetime([row[0] for row in rows], unit="ms", utc=True).tz_convert(None).normalize()
    closes = [float(row[4]) for row in rows]
    s = pd.Series(closes, index=idx, name=symbol).sort_index()
    if start:
        s = s.loc[pd.Timestamp(start) :]
    if end:
        s = s.loc[: pd.Timestamp(end)]
    return s.dropna()
