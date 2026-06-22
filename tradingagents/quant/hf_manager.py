"""HF manager books: equal-weight index + regime-dynamic multi-sleeve blend."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingagents.quant.regime_allocator import blend_returns, regime_dynamic_weights

BASE_SLEEVE_IDS: tuple[str, ...] = (
    "whale_flow",
    "pairs_stat_arb",
    "ts_momentum_meme",
    "cs_momentum_rank",
    "binance_poly_latency",
    "short_term_reversal",
    "poly_mean_reversion",
    "vol_risk_parity",
)

SLEEVE_LOGIC: dict[str, dict[str, str]] = {
    "whale_flow": {
        "logic_type": "order_flow",
        "venue": "POLY",
        "description": "Large-trade net flow + EMA trend",
    },
    "pairs_stat_arb": {
        "logic_type": "spread_mr",
        "venue": "DOGE/WIF",
        "description": "Slow z-score MR on log(DOGE/WIF)",
    },
    "ts_momentum_meme": {
        "logic_type": "beta_neutral_mom",
        "venue": "DOGE",
        "description": "15d residual momentum vs WIF beta",
    },
    "cs_momentum_rank": {
        "logic_type": "lead_lag",
        "venue": "DOGE/WIF",
        "description": "DOGE leads WIF spread microstructure",
    },
    "binance_poly_latency": {
        "logic_type": "venue_lead_lag",
        "venue": "Binance→POLY",
        "description": "Binance DOGE leads POLY GTA prob (cross-venue latency)",
    },
    "short_term_reversal": {
        "logic_type": "extreme_reversal",
        "venue": "DOGE/WIF",
        "description": "Fade |5d|≥8% EW basket moves",
    },
    "poly_mean_reversion": {
        "logic_type": "shock_fade",
        "venue": "POLY",
        "description": "Fade large daily Yes-prob shocks",
    },
    "vol_risk_parity": {
        "logic_type": "slow_beta_neutral",
        "venue": "DOGE",
        "description": "25d slow beta-neutral residual",
    },
}


def available_sleeves(returns_map: dict[str, pd.Series]) -> list[str]:
    return [
        sid
        for sid in BASE_SLEEVE_IDS
        if sid in returns_map and returns_map[sid] is not None and len(returns_map[sid].dropna())
    ]


def equal_weight_allocation(returns_map: dict[str, pd.Series]) -> dict[str, float]:
    ids = available_sleeves(returns_map)
    if not ids:
        return {}
    w = 1.0 / len(ids)
    out = {sid: round(w, 4) for sid in ids}
    diff = round(1.0 - sum(out.values()), 4)
    if diff and ids:
        out[ids[-1]] = round(out[ids[-1]] + diff, 4)
    return out


def equal_weight_returns(returns_map: dict[str, pd.Series]) -> pd.Series:
    """Multi-strategy index: 1/n on each available base sleeve."""
    weights = equal_weight_allocation(returns_map)
    return blend_returns(returns_map, weights)


def hf_manager_returns(
    returns_map: dict[str, pd.Series],
    merged_tilt: dict[str, float] | None = None,
) -> tuple[pd.Series, dict[str, float]]:
    """Regime tilt × inverse-correlation blend across all base sleeves."""
    weights = regime_dynamic_weights(returns_map, merged_tilt, production_only=False)
    return blend_returns(returns_map, weights), weights


def sleeve_logic_meta() -> list[dict[str, Any]]:
    return [{"id": sid, **meta} for sid, meta in SLEEVE_LOGIC.items()]
