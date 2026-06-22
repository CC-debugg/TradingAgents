"""Per-sleeve order intents for all base strategies + beta-neutral hedges."""

from __future__ import annotations

import os
from dataclasses import asdict
from typing import Any

import pandas as pd

from tradingagents.execution.polymarket_clob import OrderIntent, poly_intent_from_signal
from tradingagents.quant.alpha_sleeve_signals import (
    latest_beta_neutral_signal,
    latest_binance_poly_latency_signal,
    latest_cs_momentum_signal,
    latest_poly_mean_reversion_signal,
    latest_short_term_reversal_signal,
)
from tradingagents.quant.hf_manager import BASE_SLEEVE_IDS
from tradingagents.quant.pairs_stat_arb import pairs_execution_detail
from tradingagents.quant.whale_strategy import WhaleStrategyConfig, whale_execution_detail

DEFAULT_SLUG = "gta-vi-released-before-june-2026"
SIGNAL_THRESH = 0.25

ALPHA_SLEEVE_IDS = (
    "ts_momentum_meme",
    "cs_momentum_rank",
    "short_term_reversal",
    "poly_mean_reversion",
    "vol_risk_parity",
)


def _notional_usd() -> float:
    raw = os.environ.get("LIVE_NOTIONAL_USD", "100").strip()
    try:
        return max(5.0, float(raw))
    except ValueError:
        return 100.0


def _sleeve_slice(notional: float) -> float:
    return notional / len(BASE_SLEEVE_IDS)


def _kraken_leg(market: str, side: str, size_usd: float, reason: str) -> OrderIntent | None:
    if size_usd < 1.0:
        return None
    return OrderIntent(market, "spot", side.upper(), round(size_usd, 2), 0.0, reason)


def _spread_legs(
    doge_leg: float,
    wif_leg: float,
    slice_usd: float,
    reason: str,
    *,
    thresh: float = SIGNAL_THRESH,
) -> list[OrderIntent]:
    out: list[OrderIntent] = []
    leg_usd = slice_usd * 0.45
    if abs(doge_leg) > thresh:
        side = "BUY" if doge_leg > 0 else "SELL"
        intent = _kraken_leg("DOGE-USD", side, leg_usd, f"{reason}:doge")
        if intent:
            out.append(intent)
    if abs(wif_leg) > thresh:
        side = "BUY" if wif_leg > 0 else "SELL"
        intent = _kraken_leg("WIF-USD", side, leg_usd, f"{reason}:wif")
        if intent:
            out.append(intent)
    return out


def _beta_neutral_legs(
    sig: dict[str, float],
    slice_usd: float,
    sleeve_id: str,
    *,
    thresh: float = SIGNAL_THRESH,
) -> list[OrderIntent]:
    signal = float(sig.get("signal", 0))
    if abs(signal) <= thresh:
        return []
    doge_usd = slice_usd * 0.5
    doge_side = "BUY" if signal > 0 else "SELL"
    out: list[OrderIntent] = []
    main = _kraken_leg("DOGE-USD", doge_side, doge_usd, f"{sleeve_id}:doge_residual")
    if main:
        out.append(main)
    hedge_ratio = float(sig.get("wif_hedge_ratio", 0))
    if hedge_ratio > 0.05:
        hedge_usd = min(doge_usd, doge_usd * hedge_ratio)
        hedge_side = "SELL" if signal > 0 else "BUY"
        hedge = _kraken_leg("WIF-USD", hedge_side, hedge_usd, f"{sleeve_id}:wif_beta_hedge")
        if hedge:
            out.append(hedge)
    return out


def build_sleeve_intent_map(
    flow: pd.DataFrame,
    poly: pd.Series,
    doge: pd.Series | None,
    wif: pd.Series | None,
    *,
    binance: pd.Series | None = None,
    notional_usd: float | None = None,
    trades: pd.DataFrame | None = None,
    slug: str = DEFAULT_SLUG,
) -> dict[str, Any]:
    """Build intents for each base sleeve independently (research + optional live)."""
    notional = notional_usd if notional_usd is not None else _notional_usd()
    slice_usd = _sleeve_slice(notional)
    out: dict[str, list[OrderIntent]] = {}
    signals: dict[str, dict[str, float]] = {}

    whale = whale_execution_detail(flow, poly, trades, WhaleStrategyConfig())
    poly_whale = float(whale.get("signal", 0))
    signals["whale_flow"] = {"signal": poly_whale, "poly": poly_whale}
    out["whale_flow"] = poly_intent_from_signal(poly_whale, slice_usd, slug, "whale_flow")

    if doge is not None and wif is not None:
        pairs = pairs_execution_detail(doge, wif)
        doge_p = float(pairs.get("doge", 0))
        wif_p = float(pairs.get("wif", 0))
        signals["pairs_stat_arb"] = {
            "signal": doge_p,
            "doge": doge_p,
            "wif": wif_p,
            "spread_z": float(pairs.get("spread_z", 0)),
        }
        out["pairs_stat_arb"] = _spread_legs(doge_p, wif_p, slice_usd, "pairs_stat_arb")

        ts_sig = latest_beta_neutral_signal(doge, wif, lookback=15)
        signals["ts_momentum_meme"] = ts_sig
        out["ts_momentum_meme"] = _beta_neutral_legs(ts_sig, slice_usd, "ts_momentum_meme")

        vol_sig = latest_beta_neutral_signal(doge, wif, lookback=25)
        signals["vol_risk_parity"] = vol_sig
        out["vol_risk_parity"] = _beta_neutral_legs(vol_sig, slice_usd, "vol_risk_parity")

        cs_sig = latest_cs_momentum_signal(doge, wif)
        signals["cs_momentum_rank"] = cs_sig
        out["cs_momentum_rank"] = _spread_legs(
            float(cs_sig["doge"]),
            float(cs_sig["wif"]),
            slice_usd,
            "cs_momentum_rank",
        )

        if binance is not None and len(poly):
            lat_sig = latest_binance_poly_latency_signal(binance, poly)
            signals["binance_poly_latency"] = lat_sig
            out["binance_poly_latency"] = poly_intent_from_signal(
                float(lat_sig.get("poly", 0)),
                slice_usd,
                slug,
                "binance_poly_latency",
            )
        else:
            signals["binance_poly_latency"] = {"signal": 0.0}
            out["binance_poly_latency"] = []

        rev_sig = latest_short_term_reversal_signal(doge, wif)
        signals["short_term_reversal"] = rev_sig
        out["short_term_reversal"] = _spread_legs(
            float(rev_sig["doge"]),
            float(rev_sig["wif"]),
            slice_usd,
            "short_term_reversal",
        )
    else:
        for sid in ("pairs_stat_arb", "binance_poly_latency", *ALPHA_SLEEVE_IDS):
            if sid != "poly_mean_reversion":
                signals[sid] = {"signal": 0.0}
                out[sid] = []

    if len(poly):
        poly_mr = latest_poly_mean_reversion_signal(poly)
        signals["poly_mean_reversion"] = poly_mr
        out["poly_mean_reversion"] = poly_intent_from_signal(
            float(poly_mr.get("poly", 0)),
            slice_usd,
            slug,
            "poly_mean_reversion",
        )
    else:
        signals["poly_mean_reversion"] = {"signal": 0.0}
        out["poly_mean_reversion"] = []

    serialized = {k: [asdict(i) for i in v] for k, v in out.items()}
    flat: list[OrderIntent] = []
    for intents in out.values():
        flat.extend(intents)
    return {
        "signals": signals,
        "intents_by_sleeve": serialized,
        "all_alpha_intents": flat,
        "notional_per_sleeve_usd": round(slice_usd, 2),
    }


def alpha_sleeves_live_enabled() -> bool:
    return os.environ.get("LIVE_ALPHA_SLEEVES", "").strip().lower() in ("1", "true", "yes")


def merge_execution_intents(prod_intents: list[OrderIntent], alpha_intents: list[OrderIntent]) -> list[OrderIntent]:
    """PROD intents first; append α sleeves when LIVE_ALPHA_SLEEVES=1."""
    if not alpha_sleeves_live_enabled():
        return list(prod_intents)
    return list(prod_intents) + list(alpha_intents)
