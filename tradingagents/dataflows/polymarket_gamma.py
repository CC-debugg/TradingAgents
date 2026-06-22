"""Polymarket public market data (Gamma + CLOB APIs).

Used as a lightweight fallback when NautilusTrader is not installed.
See: https://docs.polymarket.com/ and Polymarket/agent-skills market-data.md
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated

import pandas as pd
import requests

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d")


def resolve_market_slug(slug: str) -> dict | None:
    """Return Gamma market metadata for a URL slug."""
    slug = slug.strip()
    if not slug:
        return None
    try:
        r = requests.get(
            f"{GAMMA_BASE}/markets",
            params={"slug": slug, "limit": 1},
            timeout=15,
        )
        r.raise_for_status()
        markets = r.json()
        if isinstance(markets, list) and markets:
            return markets[0]
    except Exception:
        pass
    return None


def _parse_clob_token_ids(market: dict) -> list[str]:
    raw = market.get("clobTokenIds")
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            ids = json.loads(raw)
        except json.JSONDecodeError:
            return []
    else:
        ids = raw
    return [str(x) for x in ids] if isinstance(ids, list) else []


def clob_outcome_token_ids(market: dict) -> tuple[str | None, str | None]:
    """Return (yes_token_id, no_token_id) from Gamma market metadata."""
    ids = _parse_clob_token_ids(market)
    if not ids:
        return None, None
    yes_id = ids[0]
    no_id = ids[1] if len(ids) > 1 else None
    return yes_id, no_id


def market_order_options(market: dict) -> dict[str, str | bool]:
    tick = market.get("orderPriceMinTickSize") or market.get("minimum_tick_size") or "0.01"
    return {
        "tick_size": str(tick),
        "neg_risk": bool(market.get("negRisk") or market.get("neg_risk") or False),
    }


def _yes_token_id(market: dict) -> str | None:
    yes_id, _ = clob_outcome_token_ids(market)
    return yes_id


def fetch_polymarket_daily_ohlcv(
    market_slug: Annotated[str, "Polymarket market URL slug"],
    start_date: Annotated[str, "Start date yyyy-mm-dd"],
    end_date: Annotated[str, "End date yyyy-mm-dd"],
) -> pd.DataFrame:
    """Daily OHLCV from CLOB price history (Yes outcome, 0–1 probability scale)."""
    _parse_date(start_date)
    _parse_date(end_date)

    market = resolve_market_slug(market_slug)
    if not market:
        return pd.DataFrame()

    token_id = _yes_token_id(market)
    if not token_id:
        return pd.DataFrame()

    start_ts = int(pd.Timestamp(start_date, tz="UTC").timestamp())
    end_ts = int((pd.Timestamp(end_date, tz="UTC") + pd.Timedelta(days=1)).timestamp())
    span_days = (pd.Timestamp(end_date) - pd.Timestamp(start_date)).days

    params: dict = {"market": token_id, "fidelity": 1440}
    # CLOB rejects very long startTs/endTs windows; use interval=max and filter locally.
    if span_days <= 90:
        params["startTs"] = start_ts
        params["endTs"] = end_ts
    else:
        params["interval"] = "max"

    try:
        r = requests.get(f"{CLOB_BASE}/prices-history", params=params, timeout=20)
        if r.status_code == 400 and "interval" not in params:
            r = requests.get(
                f"{CLOB_BASE}/prices-history",
                params={"market": token_id, "interval": "max", "fidelity": 1440},
                timeout=20,
            )
        r.raise_for_status()
        payload = r.json()
    except Exception:
        return pd.DataFrame()

    history = payload.get("history", payload) if isinstance(payload, dict) else payload
    if not isinstance(history, list) or not history:
        return pd.DataFrame()

    rows = []
    for pt in history:
        ts = pt.get("t")
        price = pt.get("p")
        if ts is None or price is None:
            continue
        rows.append(
            {
                "Datetime": pd.to_datetime(int(ts), unit="s", utc=True),
                "Price": float(price),
            }
        )
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows).sort_values("Datetime")
    df = df[(df["Datetime"] >= pd.Timestamp(start_date, tz="UTC")) &
            (df["Datetime"] < pd.Timestamp(end_date, tz="UTC") + pd.Timedelta(days=1))]
    if df.empty:
        return pd.DataFrame()

    daily = df.set_index("Datetime").resample("1D").agg(
        Open=("Price", "first"),
        High=("Price", "max"),
        Low=("Price", "min"),
        Close=("Price", "last"),
    ).dropna()
    if daily.empty:
        return daily
    daily.index = daily.index.tz_convert(None)
    return daily.loc[start_date:end_date]


def get_polymarket_data_online(
    symbol: Annotated[str, "POLY:slug or POLYMARKET:slug"],
    start_date: Annotated[str, "Start date yyyy-mm-dd"],
    end_date: Annotated[str, "End date yyyy-mm-dd"],
) -> str:
    """CSV string compatible with other dataflow vendors."""
    upper = symbol.upper()
    if upper.startswith("POLY:") or upper.startswith("POLYMARKET:"):
        slug = symbol.split(":", 1)[1].strip()
    else:
        slug = symbol.strip()

    if not slug:
        return "Invalid Polymarket symbol. Use POLY:<market-slug>."

    ohlcv = fetch_polymarket_daily_ohlcv(slug, start_date, end_date)
    if ohlcv.empty:
        return (
            f"No Polymarket CLOB data for '{slug}' between {start_date} and {end_date}."
        )

    header = f"# Polymarket (Gamma/CLOB) data for {slug}\n"
    header += f"# Total records: {len(ohlcv)}\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    return header + ohlcv.to_csv()
