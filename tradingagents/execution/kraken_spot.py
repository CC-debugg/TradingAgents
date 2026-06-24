"""Kraken spot / margin execution via REST API (dry-run by default)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
import urllib.parse
from typing import Any

import requests

from tradingagents.execution.polymarket_clob import OrderIntent
from tradingagents.execution.risk_limits import RiskLimits, record_daily_notional, validate_order_size

KRAKEN_REST = os.environ.get("KRAKEN_REST_URL", "https://api.kraken.com")

# Dashboard slug -> Kraken pair name (see polymarket_strategy UNIVERSE).
PAIR_MAP: dict[str, str] = {
    "DOGE-USD": "DOGEUSD",
    "WIF-USD": "WIFUSD",
}

ASSET_ALIASES: dict[str, tuple[str, ...]] = {
    "DOGE": ("DOGE", "XDG", "XXDG"),
    "WIF": ("WIF",),
    "USD": ("ZUSD", "USD"),
}


def live_trading_enabled() -> bool:
    return os.environ.get("KRAKEN_LIVE", "").strip().lower() in ("1", "true", "yes")


def margin_enabled() -> bool:
    return os.environ.get("KRAKEN_USE_MARGIN", "").strip().lower() in ("1", "true", "yes")


def credentials_configured() -> bool:
    return bool(os.environ.get("KRAKEN_API_KEY", "").strip() and os.environ.get("KRAKEN_API_SECRET", "").strip())


def _margin_leverage() -> str:
    raw = os.environ.get("KRAKEN_MARGIN_LEVERAGE", "2").strip()
    return raw or "2"


def _api_key() -> str:
    key = os.environ.get("KRAKEN_API_KEY", "").strip()
    if not key:
        raise KeyError("KRAKEN_API_KEY not set")
    return key


def _api_secret() -> str:
    secret = os.environ.get("KRAKEN_API_SECRET", "").strip()
    if not secret:
        raise KeyError("KRAKEN_API_SECRET not set")
    return secret


def _kraken_sign(urlpath: str, data: dict[str, Any], secret: str) -> str:
    postdata = urllib.parse.urlencode(data)
    encoded = (str(data["nonce"]) + postdata).encode()
    message = urlpath.encode() + hashlib.sha256(encoded).digest()
    mac = hmac.new(base64.b64decode(secret), message, hashlib.sha512)
    return base64.b64encode(mac.digest()).decode()


def _private_request(path: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    data = dict(data or {})
    data["nonce"] = int(time.time() * 1000)
    urlpath = f"/0/private/{path}"
    headers = {
        "API-Key": _api_key(),
        "API-Sign": _kraken_sign(urlpath, data, _api_secret()),
    }
    r = requests.post(
        f"{KRAKEN_REST}{urlpath}",
        headers=headers,
        data=data,
        timeout=30,
    )
    r.raise_for_status()
    payload = r.json()
    errors = payload.get("error") or []
    if errors:
        raise RuntimeError("; ".join(str(e) for e in errors))
    return payload.get("result") or {}


def _public_request(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    r = requests.get(f"{KRAKEN_REST}/0/public/{path}", params=params or {}, timeout=20)
    r.raise_for_status()
    payload = r.json()
    errors = payload.get("error") or []
    if errors:
        raise RuntimeError("; ".join(str(e) for e in errors))
    return payload.get("result") or {}


def resolve_pair(market_slug: str) -> str | None:
    return PAIR_MAP.get(market_slug)


def fetch_ticker_price(pair: str) -> float:
    result = _public_request("Ticker", {"pair": pair})
    key = next(iter(result), None)
    if not key:
        raise RuntimeError(f"no ticker for {pair}")
    last = result[key].get("c", [None])[0]
    if last is None:
        raise RuntimeError(f"no last price for {pair}")
    return float(last)


def fetch_balances() -> dict[str, float]:
    if not credentials_configured():
        return {}
    result = _private_request("Balance")
    return {k: float(v) for k, v in result.items()}


def _asset_balance(balances: dict[str, float], asset: str) -> float:
    for alias in ASSET_ALIASES.get(asset, (asset,)):
        if alias in balances:
            return balances[alias]
    return 0.0


def kraken_health_check() -> dict[str, Any]:
    out: dict[str, Any] = {
        "rest_reachable": False,
        "live_flag": live_trading_enabled(),
        "margin_flag": margin_enabled(),
        "credentials_configured": credentials_configured(),
        "pairs": list(PAIR_MAP.values()),
    }
    try:
        _public_request("Time")
        out["rest_reachable"] = True
    except Exception as exc:
        out["error"] = str(exc)[:200]
        return out

    if credentials_configured():
        try:
            balances = fetch_balances()
            out["balance_keys"] = sorted(balances.keys())
            out["usd_balance"] = _asset_balance(balances, "USD")
            out["doge_balance"] = _asset_balance(balances, "DOGE")
            out["wif_balance"] = _asset_balance(balances, "WIF")
            out["auth_ok"] = True
        except Exception as exc:
            out["auth_ok"] = False
            out["auth_error"] = str(exc)[:200]
    return out


def _intent_asset(market_slug: str) -> str:
    if market_slug.startswith("DOGE"):
        return "DOGE"
    if market_slug.startswith("WIF"):
        return "WIF"
    return market_slug.split("-")[0]


def _can_spot_sell(balances: dict[str, float], asset: str, size_usd: float, price: float) -> bool:
    need = size_usd / max(price, 1e-12)
    return _asset_balance(balances, asset) >= need * 0.98


def place_market_order(
    pair: str,
    side: str,
    size_usd: float,
    *,
    use_margin: bool | None = None,
    validate_only: bool = False,
    reason: str = "",
) -> dict[str, Any]:
    """Market order with volume in quote currency (USD) via viqc."""
    use_margin = margin_enabled() if use_margin is None else use_margin
    side_l = side.upper()
    if side_l not in ("BUY", "SELL"):
        raise ValueError(f"invalid side: {side}")

    price = fetch_ticker_price(pair)
    limits = RiskLimits.from_env()
    ok, risk_msg = validate_order_size(size_usd, limits)
    if not ok:
        return {
            "status": "rejected",
            "message": f"risk limit: {risk_msg}",
            "pair": pair,
            "side": side_l,
            "size_usd": size_usd,
            "price": price,
            "reason": reason,
        }

    balances = fetch_balances() if credentials_configured() else {}
    asset = "DOGE" if "DOGE" in pair else "WIF" if "WIF" in pair else pair[:3]

    if side_l == "SELL" and not use_margin:
        if not _can_spot_sell(balances, asset, size_usd, price):
            return {
                "status": "rejected",
                "message": "spot SELL requires existing balance — enable KRAKEN_USE_MARGIN=1 for shorts",
                "pair": pair,
                "side": side_l,
                "size_usd": size_usd,
                "price": price,
                "reason": reason,
            }

    if validate_only:
        return {
            "status": "validated",
            "message": "credentials and risk checks passed (validate-only)",
            "pair": pair,
            "side": side_l,
            "size_usd": size_usd,
            "price": price,
            "use_margin": use_margin,
            "reason": reason,
        }

    order: dict[str, Any] = {
        "pair": pair,
        "type": side_l.lower(),
        "ordertype": "market",
        "volume": str(round(size_usd, 2)),
        "oflags": "viqc",
    }
    if use_margin:
        order["leverage"] = _margin_leverage()

    result = _private_request("AddOrder", order)
    txids = result.get("txid") or []
    record_daily_notional(size_usd)
    return {
        "status": "submitted",
        "message": "order accepted",
        "pair": pair,
        "side": side_l,
        "size_usd": size_usd,
        "price": price,
        "txids": txids,
        "use_margin": use_margin,
        "reason": reason,
    }


def execute_kraken_intent(intent: OrderIntent, dry_run: bool | None = None) -> dict[str, Any]:
    """Execute or dry-run a single DOGE-USD / WIF-USD intent."""
    if dry_run is None:
        dry_run = not live_trading_enabled()

    pair = resolve_pair(intent.market_slug)
    base = {
        "venue": "kraken",
        "market": intent.market_slug,
        "pair": pair,
        "side": intent.side,
        "size_usd": intent.size_usd,
        "reason": intent.reason,
    }
    if not pair:
        return {**base, "status": "error", "message": f"unsupported Kraken market {intent.market_slug}"}

    if dry_run:
        msg = "DRY_RUN — no order sent (set KRAKEN_LIVE=1 to enable)"
        if credentials_configured():
            msg += "; credentials present"
        return {**base, "status": "dry_run", "message": msg}

    if not credentials_configured():
        return {**base, "status": "error", "message": "KRAKEN_API_KEY / KRAKEN_API_SECRET not set"}

    validate_only = os.environ.get("KRAKEN_VALIDATE_ONLY", "").strip().lower() in ("1", "true", "yes")

    try:
        result = place_market_order(
            pair,
            intent.side,
            intent.size_usd,
            validate_only=validate_only,
            reason=intent.reason,
        )
        return {**base, **result}
    except Exception as exc:
        return {**base, "status": "error", "message": str(exc)[:200]}
