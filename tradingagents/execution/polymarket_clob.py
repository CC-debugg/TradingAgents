"""Polymarket CLOB execution (live when POLYMARKET_LIVE=1 + credentials).

Universe live sleeve: POLY_GTA + DOGE + WIF (POLY via CLOB; crypto via separate venue TBD).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import requests

from tradingagents.dataflows.polymarket_gamma import resolve_market_slug

CLOB_HOST = os.environ.get("POLYMARKET_CLOB_HOST", "https://clob.polymarket.com")


@dataclass
class OrderIntent:
    market_slug: str
    outcome: str  # Yes | No
    side: str  # BUY | SELL
    size_usd: float
    limit_price: float
    reason: str


def live_trading_enabled() -> bool:
    return os.environ.get("POLYMARKET_LIVE", "").strip().lower() in ("1", "true", "yes")


def _resolve_poly_prices(slug: str) -> tuple[float, float]:
    meta = resolve_market_slug(slug) or {}
    yes_p, no_p = 0.5, 0.5
    raw = meta.get("outcomePrices")
    if isinstance(raw, str):
        try:
            op = json.loads(raw)
            yes_p, no_p = float(op[0]), float(op[1])
        except (json.JSONDecodeError, IndexError, TypeError):
            pass
    return yes_p, no_p


def poly_intent_from_signal(
    poly_signal: float,
    notional_usd: float,
    slug: str,
    reason: str,
    *,
    thresh: float = 0.25,
) -> list[OrderIntent]:
    """Map poly signal in [-1,1] to Yes/No buy intents."""
    intents: list[OrderIntent] = []
    if abs(poly_signal) <= thresh:
        return intents
    yes_p, no_p = _resolve_poly_prices(slug)
    size = notional_usd * min(1.0, abs(poly_signal))
    if poly_signal > thresh:
        intents.append(OrderIntent(slug, "Yes", "BUY", size, yes_p, reason))
    elif poly_signal < -thresh:
        intents.append(OrderIntent(slug, "No", "BUY", size, no_p, reason))
    return intents


def target_positions_from_signals(
    poly_signal: float,
    doge_signal: float,
    wif_signal: float,
    notional_usd: float | None = None,
) -> list[OrderIntent]:
    """Map [-1,1] signals to POLY Yes/No + Kraken DOGE/WIF intents."""
    if notional_usd is None:
        raw = os.environ.get("LIVE_NOTIONAL_USD", "100").strip()
        try:
            notional_usd = float(raw)
        except ValueError:
            notional_usd = 100.0
    intents: list[OrderIntent] = []
    slug = "gta-vi-released-before-june-2026"
    intents.extend(poly_intent_from_signal(poly_signal, notional_usd, slug, "poly_signal"))

    # Crypto legs → Kraken
    if abs(doge_signal) > 0.25:
        intents.append(
            OrderIntent("DOGE-USD", "spot", "BUY" if doge_signal > 0 else "SELL", notional_usd * 0.3, 0, "doge_signal")
        )
    if abs(wif_signal) > 0.25:
        intents.append(
            OrderIntent("WIF-USD", "spot", "BUY" if wif_signal > 0 else "SELL", notional_usd * 0.3, 0, "wif_signal")
        )
    return intents


def _is_kraken_intent(intent: OrderIntent) -> bool:
    return intent.market_slug in ("DOGE-USD", "WIF-USD")


def execute_intents(intents: list[OrderIntent], dry_run: bool | None = None) -> list[dict]:
    """
    Live: Polymarket CLOB (py-clob-client) + Kraken CEX (REST).
    Default dry_run per venue unless POLYMARKET_LIVE=1 / KRAKEN_LIVE=1.
    """
    from tradingagents.execution.kraken_spot import execute_kraken_intent, live_trading_enabled as kraken_live

    results = []
    for intent in intents:
        if _is_kraken_intent(intent):
            kr = execute_kraken_intent(
                intent,
                dry_run=dry_run if dry_run is not None else not kraken_live(),
            )
            results.append(
                {
                    "venue": kr.get("venue", "kraken"),
                    "market": intent.market_slug,
                    "outcome": intent.outcome,
                    "side": intent.side,
                    "size_usd": intent.size_usd,
                    "limit_price": intent.limit_price,
                    "reason": intent.reason,
                    "status": kr.get("status", "error"),
                    "message": kr.get("message", ""),
                    "pair": kr.get("pair"),
                    "txids": kr.get("txids"),
                }
            )
            continue

        poly_dry = dry_run if dry_run is not None else not live_trading_enabled()
        row = {
            "venue": "polymarket",
            "market": intent.market_slug,
            "outcome": intent.outcome,
            "side": intent.side,
            "size_usd": intent.size_usd,
            "limit_price": intent.limit_price,
            "reason": intent.reason,
            "status": "dry_run" if poly_dry else "pending",
            "message": "",
        }
        if poly_dry:
            row["message"] = "DRY_RUN — no order sent (set POLYMARKET_LIVE=1 to enable)"
            results.append(row)
            continue
        try:
            from tradingagents.execution.polymarket_clob_live import submit_polymarket_intent

            result = submit_polymarket_intent(
                intent.market_slug,
                intent.outcome,
                intent.side,
                intent.size_usd,
                intent.limit_price,
            )
            row["status"] = result.get("status", "submitted")
            row["message"] = result.get("message", "")
            row["order_id"] = result.get("order_id")
            row["size_shares"] = result.get("size_shares")
        except ImportError:
            row["status"] = "error"
            row["message"] = "pip install py-clob-client or py-clob-client-v2 for live CLOB"
        except KeyError:
            row["status"] = "error"
            row["message"] = "POLYMARKET_PRIVATE_KEY not set"
        except Exception as e:
            row["status"] = "error"
            row["message"] = str(e)[:200]
        results.append(row)
    return results


def clob_health_check() -> dict:
    try:
        r = requests.get(f"{CLOB_HOST}/time", timeout=5)
        return {"clob_reachable": r.ok, "live_flag": live_trading_enabled()}
    except Exception as e:
        return {"clob_reachable": False, "error": str(e), "live_flag": live_trading_enabled()}
