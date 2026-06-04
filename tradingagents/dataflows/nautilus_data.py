from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Annotated

import pandas as pd

from .polymarket_gamma import get_polymarket_data_online
from .y_finance import get_YFin_data_online


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d")


def get_nautilus_data_online(
    symbol: Annotated[str, "ticker symbol or instrument id"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
):
    """Fetch OHLCV via NautilusTrader Polymarket loader when symbol is a market slug.

    Supported symbol formats for real Nautilus pulls:
    - ``POLY:market-slug``
    - ``POLYMARKET:market-slug``

    For regular symbols (e.g. ``DOGE-USD``), this falls back to yfinance so
    callers can keep using one vendor setting while incrementally adopting
    Nautilus-backed sources.
    """
    _parse_date(start_date)
    _parse_date(end_date)

    upper = symbol.upper()
    if ":" not in symbol or (not upper.startswith("POLY:") and not upper.startswith("POLYMARKET:")):
        return get_YFin_data_online(symbol=symbol, start_date=start_date, end_date=end_date)

    market_slug = symbol.split(":", 1)[1].strip()
    if not market_slug:
        return "Invalid Nautilus symbol format. Use POLY:<market-slug>."

    try:
        from nautilus_trader.adapters.polymarket import PolymarketDataLoader  # type: ignore
    except Exception:
        return get_polymarket_data_online(symbol, start_date, end_date)

    async def _load_market_ohlcv() -> pd.DataFrame:
        loader = await PolymarketDataLoader.from_market_slug(market_slug)
        trades = await loader.load_trades(
            start=pd.Timestamp(start_date, tz="UTC"),
            end=pd.Timestamp(end_date, tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1),
        )
        if not trades:
            return pd.DataFrame()

        rows = []
        for t in trades:
            ts = pd.to_datetime(int(t.ts_event), unit="ns", utc=True)
            rows.append(
                {
                    "Datetime": ts,
                    "Price": float(t.price),
                    "Volume": float(t.size),
                }
            )
        df = pd.DataFrame(rows).sort_values("Datetime")
        daily = df.set_index("Datetime").resample("1D").agg(
            Open=("Price", "first"),
            High=("Price", "max"),
            Low=("Price", "min"),
            Close=("Price", "last"),
            Volume=("Volume", "sum"),
        ).dropna()
        if daily.empty:
            return daily
        daily.index = daily.index.tz_convert(None)
        return daily.loc[start_date:end_date]

    def _run_coro(coro):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)

        result = {}
        error = {}

        def _target():
            try:
                result["value"] = asyncio.run(coro)
            except Exception as exc:  # pragma: no cover - defensive thread path
                error["exc"] = exc

        import threading

        th = threading.Thread(target=_target, daemon=True)
        th.start()
        th.join()
        if "exc" in error:
            raise error["exc"]
        return result.get("value")

    try:
        ohlcv = _run_coro(_load_market_ohlcv())
    except Exception as exc:
        return f"Failed to fetch Nautilus Polymarket data for '{market_slug}': {exc}"

    min_bars = max(30, (pd.Timestamp(end_date) - pd.Timestamp(start_date)).days // 4)
    if ohlcv is None or ohlcv.empty or len(ohlcv) < min_bars:
        return get_polymarket_data_online(symbol, start_date, end_date)

    header = f"# Nautilus Polymarket data for {market_slug}\n"
    header += f"# Total records: {len(ohlcv)}\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    return header + ohlcv.to_csv()
