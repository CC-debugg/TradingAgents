"""Kraken live runner: 5 meme sleeves on DOGE/WIF (margin-capable)."""

from __future__ import annotations

import os
from dataclasses import asdict
from typing import Any

import pandas as pd

from tradingagents.execution.kraken_spot import execute_kraken_intent, kraken_health_check
from tradingagents.execution.polymarket_clob import OrderIntent
from tradingagents.execution.sleeve_intents import (
    _beta_neutral_legs,
    _spread_legs,
)
from tradingagents.quant.alpha_sleeve_signals import (
    latest_beta_neutral_signal,
    latest_cs_momentum_signal,
    latest_short_term_reversal_signal,
)
from tradingagents.quant.news_gate import apply_news_gate, score_macro_news
from tradingagents.quant.pairs_stat_arb import pairs_execution_detail

KRAKEN_MEME_SLEEVE_IDS: tuple[str, ...] = (
    "pairs_stat_arb",
    "ts_momentum_meme",
    "cs_momentum_rank",
    "short_term_reversal",
    "vol_risk_parity",
)


def kraken_meme_live_enabled() -> bool:
    return os.environ.get("KRAKEN_MEME_LIVE", "").strip().lower() in ("1", "true", "yes")


def _notional_usd() -> float:
    raw = os.environ.get("KRAKEN_MEME_NOTIONAL_USD", os.environ.get("LIVE_NOTIONAL_USD", "100")).strip()
    try:
        return max(10.0, float(raw))
    except ValueError:
        return 100.0


def _sleeve_slice(notional: float) -> float:
    return notional / len(KRAKEN_MEME_SLEEVE_IDS)


def _gate_signals(doge: float, wif: float) -> tuple[float, float, dict[str, Any]]:
    if os.environ.get("KRAKEN_NEWS_GATE", "1").strip().lower() in ("0", "false", "no"):
        return doge, wif, {"score": 0.0, "label": "disabled", "blocked": False}
    from tradingagents.dataflows.macro_news import fetch_macro_news_snapshot

    gate = score_macro_news(fetch_macro_news_snapshot())
    doge_g, _ = apply_news_gate(doge, gate)
    wif_g, _ = apply_news_gate(wif, gate)
    return doge_g, wif_g, gate


def build_kraken_meme_intents(
    doge: pd.Series,
    wif: pd.Series,
    *,
    notional_usd: float | None = None,
) -> dict[str, Any]:
    """Build DOGE/WIF intents for the 5 Kraken meme sleeves only."""
    notional = notional_usd if notional_usd is not None else _notional_usd()
    slice_usd = _sleeve_slice(notional)
    out: dict[str, list[OrderIntent]] = {sid: [] for sid in KRAKEN_MEME_SLEEVE_IDS}
    signals: dict[str, dict[str, float]] = {}

    pairs = pairs_execution_detail(doge, wif)
    doge_p = float(pairs.get("doge", 0))
    wif_p = float(pairs.get("wif", 0))
    doge_p, wif_p, gate = _gate_signals(doge_p, wif_p)
    signals["pairs_stat_arb"] = {
        "signal": doge_p,
        "doge": doge_p,
        "wif": wif_p,
        "spread_z": float(pairs.get("spread_z", 0)),
    }
    out["pairs_stat_arb"] = _spread_legs(doge_p, wif_p, slice_usd, "pairs_stat_arb")

    ts_sig = latest_beta_neutral_signal(doge, wif, lookback=15)
    ts_d, _ = apply_news_gate(float(ts_sig.get("signal", 0)), gate)
    ts_sig = {**ts_sig, "signal": ts_d}
    signals["ts_momentum_meme"] = ts_sig
    out["ts_momentum_meme"] = _beta_neutral_legs(ts_sig, slice_usd, "ts_momentum_meme")

    vol_sig = latest_beta_neutral_signal(doge, wif, lookback=25)
    vol_d, _ = apply_news_gate(float(vol_sig.get("signal", 0)), gate)
    vol_sig = {**vol_sig, "signal": vol_d}
    signals["vol_risk_parity"] = vol_sig
    out["vol_risk_parity"] = _beta_neutral_legs(vol_sig, slice_usd, "vol_risk_parity")

    cs_sig = latest_cs_momentum_signal(doge, wif)
    cs_d, cs_w, _ = _gate_signals(float(cs_sig["doge"]), float(cs_sig["wif"]))
    cs_sig = {**cs_sig, "doge": cs_d, "wif": cs_w}
    signals["cs_momentum_rank"] = cs_sig
    out["cs_momentum_rank"] = _spread_legs(cs_d, cs_w, slice_usd, "cs_momentum_rank")

    rev_sig = latest_short_term_reversal_signal(doge, wif)
    rev_d, rev_w, _ = _gate_signals(float(rev_sig["doge"]), float(rev_sig["wif"]))
    rev_sig = {**rev_sig, "doge": rev_d, "wif": rev_w}
    signals["short_term_reversal"] = rev_sig
    out["short_term_reversal"] = _spread_legs(rev_d, rev_w, slice_usd, "short_term_reversal")

    flat: list[OrderIntent] = []
    for sid in KRAKEN_MEME_SLEEVE_IDS:
        flat.extend(out[sid])

    return {
        "signals": signals,
        "intents_by_sleeve": {k: [asdict(i) for i in v] for k, v in out.items()},
        "raw_intents": flat,
        "netted_intents": net_kraken_intents(flat),
        "notional_usd": notional,
        "notional_per_sleeve_usd": round(slice_usd, 2),
        "news_gate": gate,
        "sleeve_ids": list(KRAKEN_MEME_SLEEVE_IDS),
    }


def net_kraken_intents(intents: list[OrderIntent]) -> list[OrderIntent]:
    """Aggregate by (market, side) to reduce duplicate Kraken market orders."""
    buckets: dict[tuple[str, str], float] = {}
    reasons: dict[tuple[str, str], list[str]] = {}
    for intent in intents:
        if intent.market_slug not in ("DOGE-USD", "WIF-USD"):
            continue
        key = (intent.market_slug, intent.side.upper())
        buckets[key] = buckets.get(key, 0.0) + intent.size_usd
        reasons.setdefault(key, []).append(intent.reason)

    min_usd = float(os.environ.get("KRAKEN_MIN_ORDER_USD", "5"))
    out: list[OrderIntent] = []
    for (market, side), size in sorted(buckets.items()):
        if size < min_usd:
            continue
        reason = "kraken_meme_net:" + "+".join(sorted(set(reasons.get((market, side), []))))[:120]
        out.append(OrderIntent(market, "spot", side, round(size, 2), 0.0, reason))
    return out


def execute_kraken_meme_pack(pack: dict[str, Any], *, dry_run: bool | None = None) -> list[dict[str, Any]]:
    """Execute netted Kraken intents from build_kraken_meme_intents."""
    intents: list[OrderIntent] = pack.get("netted_intents") or []
    # Spot buys before sells so USD-funded longs land before any sell uses inventory.
    intents = sorted(intents, key=lambda i: (0 if i.side.upper() == "BUY" else 1, i.market_slug))
    results = []
    for intent in intents:
        results.append(execute_kraken_intent(intent, dry_run=dry_run))
    return results


def run_kraken_meme_cycle(
    doge: pd.Series,
    wif: pd.Series,
    *,
    notional_usd: float | None = None,
    dry_run: bool | None = None,
) -> dict[str, Any]:
    pack = build_kraken_meme_intents(doge, wif, notional_usd=notional_usd)
    pack["health"] = kraken_health_check()
    pack["execution"] = execute_kraken_meme_pack(pack, dry_run=dry_run)
    pack["kraken_live"] = os.environ.get("KRAKEN_LIVE", "0")
    pack["margin"] = os.environ.get("KRAKEN_USE_MARGIN", "0")
    return pack
