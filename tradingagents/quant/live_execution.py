"""Live production sleeve: whale v2 + pairs v2, gated by macro news."""

from __future__ import annotations

import pandas as pd

from tradingagents.dataflows.macro_news import fetch_macro_news_snapshot
from tradingagents.execution.polymarket_clob import target_positions_from_signals
from tradingagents.execution.sleeve_intents import alpha_sleeves_live_enabled, build_sleeve_intent_map, merge_execution_intents
from tradingagents.quant.news_gate import apply_news_gate, score_macro_news
from tradingagents.quant.pairs_stat_arb import pairs_execution_detail, pairs_spread_returns_v2
from tradingagents.quant.whale_strategy import (
    WhaleStrategyConfig,
    backtest_whale_strategy,
    daily_whale_flow,
    whale_execution_detail,
    whale_flow_signal_v2,
)

# Production weights — pairs higher win rate (≈47%) vs whale (≈22%)
WHALE_WEIGHT = 0.40
PAIRS_WEIGHT = 0.60

LIVE_PRODUCTION_IDS = ("whale_flow", "pairs_stat_arb", "live_composite")


def build_live_composite_returns(
    whale_r: pd.Series,
    pairs_r: pd.Series,
) -> pd.Series:
    """Align and blend top two sleeves."""
    df = pd.DataFrame({"w": whale_r, "p": pairs_r}).dropna(how="all").fillna(0)
    if df.empty:
        return pd.Series(dtype=float)
    return WHALE_WEIGHT * df["w"] + PAIRS_WEIGHT * df["p"]


def build_live_execution_snapshot(
    flow: pd.DataFrame,
    poly: pd.Series,
    doge: pd.Series | None,
    wif: pd.Series | None,
    notional_usd: float = 100.0,
    trades: pd.DataFrame | None = None,
    binance: pd.Series | None = None,
) -> dict:
    """
    News-gated signals for CLOB + meme legs.
    POLY from whale v2; DOGE/WIF from pairs v2; blocked when macro gate is off.
    """
    news = fetch_macro_news_snapshot()
    gate = score_macro_news(news)
    whale = whale_execution_detail(flow, poly, trades, WhaleStrategyConfig())
    pairs = (
        pairs_execution_detail(doge, wif)
        if doge is not None and wif is not None
        else {"spread_z": 0.0, "doge": 0.0, "wif": 0.0}
    )

    poly_raw = float(whale.get("signal", 0))
    poly_sig, poly_reason = apply_news_gate(poly_raw, gate)
    doge_raw = float(pairs.get("doge", 0))
    wif_raw = float(pairs.get("wif", 0))
    doge_sig, doge_reason = apply_news_gate(doge_raw, gate)
    wif_sig, wif_reason = apply_news_gate(wif_raw, gate)

    intents = target_positions_from_signals(poly_sig, doge_sig, wif_sig, notional_usd=notional_usd)
    sleeve_pack = build_sleeve_intent_map(
        flow,
        poly,
        doge,
        wif,
        binance=binance,
        notional_usd=notional_usd,
        trades=trades,
    )
    all_intents = merge_execution_intents(intents, sleeve_pack["all_alpha_intents"])

    return {
        "news_gate": gate,
        "whale": whale,
        "pairs": pairs,
        "signals_raw": {"POLY_GTA": poly_raw, "DOGE": doge_raw, "WIF": wif_raw},
        "signals": {"POLY_GTA": poly_sig, "DOGE": doge_sig, "WIF": wif_sig},
        "gate_reason": {
            "POLY_GTA": poly_reason,
            "DOGE": doge_reason,
            "WIF": wif_reason,
        },
        "clob_intents": intents,
        "sleeve_intents": sleeve_pack["intents_by_sleeve"],
        "sleeve_signals": sleeve_pack["signals"],
        "notional_per_sleeve_usd": sleeve_pack["notional_per_sleeve_usd"],
        "all_intents": all_intents,
        "alpha_sleeves_live": alpha_sleeves_live_enabled(),
        "production_strategies": list(LIVE_PRODUCTION_IDS),
    }


def backtest_whale_v2(poly: pd.Series, flow: pd.DataFrame, cfg: WhaleStrategyConfig | None = None) -> pd.Series:
    cfg = cfg or WhaleStrategyConfig()
    sig = whale_flow_signal_v2(flow, poly, cfg)
    wr, _ = backtest_whale_strategy(poly, sig, fee_bps=cfg.fee_bps)
    return wr
