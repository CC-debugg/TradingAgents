"""Live whale-flow monitor on an active Polymarket market.

The whale_flow backtest stays on its (resolved) research market; this module
picks a still-trading market by a fixed, performance-blind rule and reports the
same v2 signal plus the latest large trades on every dashboard refresh.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

from tradingagents.dataflows.polymarket_gamma import GAMMA_BASE, fetch_polymarket_daily_ohlcv
from tradingagents.dataflows.polymarket_whale import fetch_large_trades_history
from tradingagents.quant.whale_strategy import (
    WhaleStrategyConfig,
    daily_whale_flow,
    whale_execution_detail,
)

MIN_DAYS_TO_RESOLUTION = 90
PROB_BAND = (0.05, 0.95)
SELECTION_CACHE_SECONDS = 3600
PRICE_LOOKBACK_DAYS = 60
MAX_RECENT_TRADES = 25
MIN_TRADE_USD = 500.0

SELECTION_RULE = (
    f"Highest lifetime volume among active Yes/No markets resolving ≥{MIN_DAYS_TO_RESOLUTION} days out "
    f"with Yes priced {PROB_BAND[0]:.0%}–{PROB_BAND[1]:.0%}; re-selected hourly, rolls when it resolves."
)

_selection_cache: dict = {"at": 0.0, "market": None}


def _yes_price(market: dict) -> float | None:
    try:
        outcomes = json.loads(market.get("outcomes") or "[]")
        prices = [float(x) for x in json.loads(market.get("outcomePrices") or "[]")]
    except (TypeError, ValueError):
        return None
    if outcomes != ["Yes", "No"] or not prices:
        return None
    return prices[0]


def _eligible(market: dict) -> bool:
    yes = _yes_price(market)
    if yes is None or not (PROB_BAND[0] <= yes <= PROB_BAND[1]):
        return False
    return bool(market.get("clobTokenIds") and market.get("conditionId"))


def select_monitor_market(force: bool = False) -> dict | None:
    """Apply SELECTION_RULE (or POLYMARKET_MONITOR_SLUG override) and cache for an hour."""
    override = os.environ.get("POLYMARKET_MONITOR_SLUG", "").strip()
    now = time.time()
    cached = _selection_cache.get("market")
    if not force and cached and now - _selection_cache["at"] < SELECTION_CACHE_SECONDS:
        if not override or cached.get("slug") == override:
            return cached

    end_min = (datetime.now(timezone.utc) + timedelta(days=MIN_DAYS_TO_RESOLUTION)).strftime("%Y-%m-%dT%H:%M:%SZ")
    params: dict = {"active": "true", "closed": "false", "limit": 100}
    if override:
        params["slug"] = override
    else:
        params.update({"order": "volumeNum", "ascending": "false", "end_date_min": end_min})

    picked = None
    for offset in (0, 100, 200):
        try:
            r = requests.get(f"{GAMMA_BASE}/markets", params={**params, "offset": offset}, timeout=15)
            r.raise_for_status()
            batch = r.json()
        except Exception:
            break
        if not isinstance(batch, list) or not batch:
            break
        picked = next((m for m in batch if override or _eligible(m)), None)
        if picked or override:
            break

    if picked:
        _selection_cache.update({"at": now, "market": picked})
        return picked
    return cached


def _recent_trade_rows(trades: pd.DataFrame, limit: int = MAX_RECENT_TRADES) -> list[dict]:
    if trades.empty:
        return []
    rows = []
    for _, t in trades.sort_values("timestamp", ascending=False).head(limit).iterrows():
        wallet = str(t.get("wallet") or "")
        rows.append(
            {
                "time_utc": pd.Timestamp(t["timestamp"]).strftime("%Y-%m-%d %H:%M"),
                "side": t.get("side", ""),
                "outcome": t.get("outcome", ""),
                "price": round(float(t.get("price", 0) or 0), 4),
                "cash_usd": round(float(t.get("cash_usd", 0) or 0), 0),
                "trader": (t.get("name") or "") or (wallet[:6] + "…" + wallet[-4:] if len(wallet) > 10 else wallet),
            }
        )
    return rows


def build_whale_monitor(max_trades: int = 2000) -> dict:
    """Current v2 whale signal, daily flow and latest large trades on the monitor market."""
    market = select_monitor_market()
    if not market:
        return {"ok": False, "error": "no eligible active market", "selection_rule": SELECTION_RULE}

    slug = market["slug"]
    today = pd.Timestamp(datetime.now(timezone.utc).date())
    start = (today - pd.Timedelta(days=PRICE_LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    trades = fetch_large_trades_history(
        min_cash_usd=MIN_TRADE_USD,
        market_slug=slug,
        condition_id=market.get("conditionId"),
        max_trades=max_trades,
    )
    ohlcv = fetch_polymarket_daily_ohlcv(slug, start, today.strftime("%Y-%m-%d"))
    prob = ohlcv["Close"].dropna() if not ohlcv.empty else pd.Series(dtype=float)
    if len(prob):
        idx = pd.to_datetime(prob.index)
        prob.index = (idx.tz_convert(None) if idx.tz is not None else idx).normalize()
    yes_now = _yes_price(market)
    if yes_now is not None:
        prob.loc[today] = yes_now
    if prob.empty:
        return {"ok": False, "error": "no price history", "slug": slug, "selection_rule": SELECTION_RULE}
    prob = prob.groupby(level=0).last().sort_index()
    prob = prob.reindex(pd.date_range(prob.index.min(), today, freq="D")).ffill()

    flow = daily_whale_flow(trades).reindex(prob.index).fillna(0) if not trades.empty else pd.DataFrame()
    detail = whale_execution_detail(flow, prob, trades, WhaleStrategyConfig())

    end_date = str(market.get("endDate") or "")[:10]
    days_left = (pd.Timestamp(end_date) - today).days if end_date else None
    return {
        "ok": True,
        "slug": slug,
        "question": market.get("question"),
        "url": f"https://polymarket.com/market/{slug}",
        "end_date": end_date,
        "days_to_resolution": days_left,
        "volume_usd": round(float(market.get("volumeNum") or market.get("volume") or 0), 0),
        "volume_24h_usd": round(float(market.get("volume24hr") or 0), 0),
        "yes_prob": yes_now,
        "as_of_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "selection_rule": SELECTION_RULE,
        "min_trade_usd": MIN_TRADE_USD,
        "detail": detail,
        "recent_trades": _recent_trade_rows(trades),
    }
