"""Polymarket whale analytics via public Data API + Gamma."""

from __future__ import annotations

from typing import Any

import pandas as pd
import requests

from .polymarket_gamma import resolve_market_slug

DATA_API = "https://data-api.polymarket.com"
GAMMA_BASE = "https://gamma-api.polymarket.com"

DEFAULT_CONDITION_IDS = {
    "gta-vi-released-before-june-2026": (
        "0xcccb7e7613a087c132b69cbf3a02bece3fdcb824c1da54ae79acc8d4a562d902"
    ),
}


def fetch_market_meta(slug: str) -> dict | None:
    return resolve_market_slug(slug)


def fetch_top_holders(condition_id: str, limit: int = 20) -> pd.DataFrame:
    """Top Yes/No token holders for a market."""
    try:
        r = requests.get(
            f"{DATA_API}/holders",
            params={"market": condition_id, "limit": limit},
            timeout=15,
        )
        r.raise_for_status()
        payload = r.json()
    except Exception:
        return pd.DataFrame()

    rows = []
    for block in payload if isinstance(payload, list) else []:
        outcome = "Yes" if block.get("outcomeIndex") == 0 else "No"
        token = block.get("token", "")
        for h in block.get("holders", []):
            rows.append(
                {
                    "token": token,
                    "outcome": outcome,
                    "wallet": h.get("proxyWallet", ""),
                    "name": h.get("name") or h.get("pseudonym", ""),
                    "amount": float(h.get("amount", 0)),
                }
            )
    return pd.DataFrame(rows)


def _resolve_condition_id(market_slug: str | None, condition_id: str | None) -> str | None:
    if condition_id:
        return condition_id
    if not market_slug:
        return None
    meta = fetch_market_meta(market_slug)
    if meta and meta.get("conditionId"):
        return meta["conditionId"]
    return DEFAULT_CONDITION_IDS.get(market_slug)


def _fetch_trades_page(params: dict[str, Any], timeout: int = 25) -> tuple[list[dict], str | None]:
    """One page of Data API v2 /trades (v1 was retired in 2026)."""
    r = requests.get(f"{DATA_API}/v2/trades", params=params, timeout=timeout)
    r.raise_for_status()
    payload = r.json()
    rows = payload.get("data") or []
    cursor = (payload.get("pagination") or {}).get("next_cursor")
    return (rows if isinstance(rows, list) else []), cursor


def _trade_params(min_cash_usd: float, limit: int, cid: str | None) -> dict[str, Any]:
    params: dict[str, Any] = {
        "limit": limit,
        "filter_type": "CASH",
        "filter_amount": min_cash_usd,
        "taker_only": "true",
    }
    if cid:
        params["condition"] = cid
    return params


def fetch_large_trades(
    min_cash_usd: float = 500.0,
    limit: int = 100,
    market_slug: str | None = None,
    condition_id: str | None = None,
) -> pd.DataFrame:
    """Recent large trades (whale flow) from Data API."""
    cid = _resolve_condition_id(market_slug, condition_id)
    try:
        trades, _ = _fetch_trades_page(_trade_params(min_cash_usd, min(limit, 1000), cid), timeout=20)
    except Exception:
        return pd.DataFrame()
    if not trades:
        return pd.DataFrame()
    return _normalize_trades(trades)


def fetch_large_trades_history(
    min_cash_usd: float = 500.0,
    market_slug: str | None = None,
    condition_id: str | None = None,
    max_trades: int = 5000,
    page_size: int = 1000,
) -> pd.DataFrame:
    """Cursor-paginate Data API v2 /trades for deeper history (newest → older)."""
    cid = _resolve_condition_id(market_slug, condition_id)
    params = _trade_params(min_cash_usd, min(page_size, 1000), cid)

    rows: list[dict] = []
    cursor: str | None = None
    while len(rows) < max_trades:
        page_params = dict(params)
        if cursor:
            page_params["cursor"] = cursor
        try:
            batch, cursor = _fetch_trades_page(page_params)
        except Exception:
            break
        rows.extend(batch)
        if not cursor:
            break

    if not rows:
        return pd.DataFrame()
    df = _normalize_trades(rows[:max_trades])
    if market_slug and "slug" in df.columns:
        df = df[df["slug"].fillna("").str.contains(market_slug, case=False, na=False)]
    return df.sort_values("timestamp")


def _normalize_trades(trades: list) -> pd.DataFrame:
    rows = []
    for t in trades:
        price = float(t.get("price", 0) or 0)
        size = float(t.get("size", 0) or 0)
        rows.append(
            {
                "timestamp": pd.to_datetime(int(t.get("timestamp", 0)), unit="s", utc=True),
                "wallet": t.get("proxy_wallet") or t.get("proxyWallet", ""),
                "name": t.get("name") or t.get("pseudonym", ""),
                "side": str(t.get("side", "")).upper(),
                "price": price,
                "size": size,
                "cash_usd": price * size,
                "outcome": t.get("outcome", ""),
                "outcome_index": int(t.get("outcome_index", t.get("outcomeIndex", 0)) or 0),
                "slug": t.get("slug", ""),
                "title": (t.get("title") or "")[:80],
                "condition_id": t.get("condition_id") or t.get("conditionId", ""),
            }
        )
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("timestamp", ascending=False)
    return df


def fetch_leaderboard(limit: int = 25) -> pd.DataFrame:
    """Top traders by PnL (public leaderboard)."""
    try:
        r = requests.get(
            f"{DATA_API}/v1/leaderboard",
            params={"limit": limit, "timePeriod": "ALL"},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
    except Exception:
        try:
            r = requests.get(f"{DATA_API}/leaderboard", params={"limit": limit}, timeout=15)
            r.raise_for_status()
            data = r.json()
        except Exception:
            return pd.DataFrame()

    rows = data if isinstance(data, list) else data.get("data", data.get("leaderboard", []))
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def whale_concentration(holders: pd.DataFrame) -> dict[str, float]:
    """HHI-style concentration on holder amounts per outcome."""
    if holders.empty:
        return {}
    out = {}
    for outcome, grp in holders.groupby("outcome"):
        amounts = grp["amount"].astype(float)
        total = amounts.sum()
        if total <= 0:
            continue
        shares = amounts / total
        out[f"{outcome}_top10_share"] = float(shares.head(10).sum())
        out[f"{outcome}_hhi"] = float((shares**2).sum())
        out[f"{outcome}_whale_count_10k"] = int((amounts >= 10_000).sum())
    return out
