"""Live production sleeve: whale v2 + pairs v2, gated by macro news."""

from __future__ import annotations

import pandas as pd

from tradingagents.dataflows.macro_news import fetch_macro_news_snapshot
from tradingagents.execution.polymarket_clob import OrderIntent, target_positions_from_signals
from tradingagents.quant.news_gate import apply_news_gate, score_macro_news
from tradingagents.quant.pairs_stat_arb import latest_pairs_signal, pairs_spread_returns_v2
from tradingagents.quant.whale_strategy import (
    WhaleStrategyConfig,
    backtest_whale_strategy,
    daily_whale_flow,
    latest_whale_signal,
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
) -> dict:
    """
    News-gated signals for CLOB + meme legs.
    POLY from whale v2; DOGE/WIF from pairs v2; blocked when macro gate is off.
    """
    news = fetch_macro_news_snapshot()
    gate = score_macro_news(news)
    whale = latest_whale_signal(flow, poly, WhaleStrategyConfig())
    pairs = (
        latest_pairs_signal(doge, wif)
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
        "production_strategies": list(LIVE_PRODUCTION_IDS),
    }


def backtest_whale_v2(poly: pd.Series, flow: pd.DataFrame, cfg: WhaleStrategyConfig | None = None) -> pd.Series:
    cfg = cfg or WhaleStrategyConfig()
    sig = whale_flow_signal_v2(flow, poly, cfg)
    wr, _ = backtest_whale_strategy(poly, sig, fee_bps=cfg.fee_bps)
    return wr
