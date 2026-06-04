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


def target_positions_from_signals(
    poly_signal: float,
    doge_signal: float,
    wif_signal: float,
    notional_usd: float = 100.0,
) -> list[OrderIntent]:
    """Map [-1,1] signals to POLY Yes/No intents (meme legs logged only until CEX wired)."""
    intents: list[OrderIntent] = []
    meta = resolve_market_slug("gta-vi-released-before-june-2026") or {}
    yes_p, no_p = 0.5, 0.5
    raw = meta.get("outcomePrices")
    if isinstance(raw, str):
        try:
            op = json.loads(raw)
            yes_p, no_p = float(op[0]), float(op[1])
        except (json.JSONDecodeError, IndexError, TypeError):
            pass

    if poly_signal > 0.25:
        intents.append(
            OrderIntent(
                "gta-vi-released-before-june-2026",
                "Yes",
                "BUY",
                notional_usd * min(1.0, abs(poly_signal)),
                yes_p,
                "poly_signal_long",
            )
        )
    elif poly_signal < -0.25:
        intents.append(
            OrderIntent(
                "gta-vi-released-before-june-2026",
                "No",
                "BUY",
                notional_usd * min(1.0, abs(poly_signal)),
                no_p,
                "poly_signal_short_via_no",
            )
        )

    # Crypto: placeholder intents (require exchange API — not Polymarket CLOB)
    if abs(doge_signal) > 0.25:
        intents.append(
            OrderIntent("DOGE-USD", "spot", "BUY" if doge_signal > 0 else "SELL", notional_usd * 0.3, 0, "doge_signal")
        )
    if abs(wif_signal) > 0.25:
        intents.append(
            OrderIntent("WIF-USD", "spot", "BUY" if wif_signal > 0 else "SELL", notional_usd * 0.3, 0, "wif_signal")
        )
    return intents


def execute_intents(intents: list[OrderIntent], dry_run: bool | None = None) -> list[dict]:
    """
    Live: requires py-clob-client + POLYMARKET_PRIVATE_KEY (optional dep).
    Default dry_run=True unless POLYMARKET_LIVE=1.
    """
    if dry_run is None:
        dry_run = not live_trading_enabled()
    results = []
    for intent in intents:
        row = {
            "market": intent.market_slug,
            "outcome": intent.outcome,
            "side": intent.side,
            "size_usd": intent.size_usd,
            "limit_price": intent.limit_price,
            "reason": intent.reason,
            "status": "dry_run" if dry_run else "pending",
            "message": "",
        }
        if dry_run:
            row["message"] = "DRY_RUN — no order sent (set POLYMARKET_LIVE=1 to enable)"
            results.append(row)
            continue
        if intent.market_slug in ("DOGE-USD", "WIF-USD"):
            row["status"] = "skipped"
            row["message"] = "CEX spot execution not wired — POLY only on CLOB"
            results.append(row)
            continue
        try:
            from py_clob_client.client import ClobClient  # type: ignore

            pk = os.environ["POLYMARKET_PRIVATE_KEY"]
            client = ClobClient(CLOB_HOST, key=pk, chain_id=int(os.environ.get("POLYMARKET_CHAIN_ID", "137")))
            # Production: build signed order from token_id + price + size
            row["status"] = "submitted_stub"
            row["message"] = "ClobClient initialized — wire create_order in next iteration"
        except ImportError:
            row["status"] = "error"
            row["message"] = "pip install py-clob-client for live CLOB"
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
