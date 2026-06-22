"""Polymarket CLOB live order submission (py-clob-client v1 or v2)."""

from __future__ import annotations

import os
from typing import Any

from tradingagents.dataflows.polymarket_gamma import clob_outcome_token_ids, market_order_options, resolve_market_slug

CLOB_HOST = os.environ.get("POLYMARKET_CLOB_HOST", "https://clob.polymarket.com")


def _chain_id() -> int:
    return int(os.environ.get("POLYMARKET_CHAIN_ID", "137"))


def _private_key() -> str:
    pk = os.environ.get("POLYMARKET_PRIVATE_KEY", "").strip()
    if not pk:
        raise KeyError("POLYMARKET_PRIVATE_KEY not set")
    return pk


def _size_shares(size_usd: float, price: float) -> float:
    p = max(price, 0.01)
    return max(1.0, round(size_usd / p, 2))


def _build_client_v2():
    from py_clob_client_v2 import ClobClient  # type: ignore

    kwargs: dict[str, Any] = {
        "host": CLOB_HOST,
        "chain_id": _chain_id(),
        "key": _private_key(),
    }
    funder = os.environ.get("POLYMARKET_FUNDER", "").strip()
    if funder:
        kwargs["funder"] = funder
        kwargs["signature_type"] = int(os.environ.get("POLYMARKET_SIGNATURE_TYPE", "1"))
    client = ClobClient(**kwargs)
    creds = client.create_or_derive_api_key()
    client.set_api_creds(creds)
    return client


def _build_client_v1():
    from py_clob_client.client import ClobClient  # type: ignore

    client = ClobClient(CLOB_HOST, key=_private_key(), chain_id=_chain_id())
    client.set_api_creds(client.create_or_derive_api_creds())
    return client


def submit_polymarket_intent(
    market_slug: str,
    outcome: str,
    side: str,
    size_usd: float,
    limit_price: float,
) -> dict[str, Any]:
    """Sign and post a limit order to Polymarket CLOB."""
    market = resolve_market_slug(market_slug)
    if not market:
        raise RuntimeError(f"market not found: {market_slug}")

    opts = market_order_options(market)
    yes_id, no_id = clob_outcome_token_ids(market)

    outcome_u = outcome.strip().lower()
    if outcome_u == "yes":
        token_id = yes_id
        price = limit_price if limit_price > 0 else 0.5
    elif outcome_u == "no":
        token_id = no_id
        price = limit_price if limit_price > 0 else 0.5
    else:
        raise RuntimeError(f"unsupported outcome: {outcome}")

    if not token_id:
        raise RuntimeError(f"no token_id for {market_slug} {outcome}")

    size = _size_shares(size_usd, price)
    side_u = side.upper()
    if side_u not in ("BUY", "SELL"):
        raise ValueError(f"invalid side: {side}")

    # Prefer v2 client; fall back to v1 package name.
    try:
        from py_clob_client_v2 import OrderArgs, OrderType, PartialCreateOrderOptions  # type: ignore
        from py_clob_client_v2.order_builder.constants import BUY, SELL  # type: ignore

        client = _build_client_v2()
        order_side = BUY if side_u == "BUY" else SELL
        order = OrderArgs(token_id=token_id, price=round(price, 4), size=size, side=order_side)
        options = PartialCreateOrderOptions(
            tick_size=str(opts["tick_size"]),
            neg_risk=bool(opts["neg_risk"]),
        )
        if hasattr(client, "create_and_post_order"):
            resp = client.create_and_post_order(
                order_args=order,
                options=options,
                order_type=OrderType.GTC,
            )
        else:
            signed = client.create_order(order, options)
            resp = client.post_order(signed, OrderType.GTC)
        return {
            "status": "submitted",
            "message": str(resp.get("status", "ok") if isinstance(resp, dict) else resp)[:200],
            "order_id": resp.get("orderID") if isinstance(resp, dict) else None,
            "token_id": token_id,
            "size_shares": size,
            "price": price,
            "raw": resp if isinstance(resp, dict) else {"response": str(resp)[:500]},
        }
    except ImportError:
        from py_clob_client.clob_types import OrderArgs, OrderType, PartialCreateOrderOptions  # type: ignore
        from py_clob_client.order_builder.constants import BUY, SELL  # type: ignore

        client = _build_client_v1()
        order_side = BUY if side_u == "BUY" else SELL
        order = OrderArgs(token_id=token_id, price=round(price, 4), size=size, side=order_side)
        options = PartialCreateOrderOptions(tick_size=str(opts["tick_size"]))
        signed = client.create_order(order, options)
        resp = client.post_order(signed, OrderType.GTC)
        return {
            "status": "submitted",
            "message": str(resp.get("status", "ok") if isinstance(resp, dict) else resp)[:200],
            "order_id": resp.get("orderID") if isinstance(resp, dict) else None,
            "token_id": token_id,
            "size_shares": size,
            "price": price,
            "raw": resp if isinstance(resp, dict) else {"response": str(resp)[:500]},
        }
