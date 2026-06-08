"""Catalog of strategies shown on live / multi-strategy dashboards."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class StrategySpec:
    id: str
    name: str
    category: str
    description: str
    runnable: bool
    reference: str
    live_production: bool = False


STRATEGY_CATALOG: list[StrategySpec] = [
    StrategySpec(
        "live_composite",
        "Live composite (whale + pairs · news-gated)",
        "PM · PRODUCTION",
        "Default for real money: 40% whale v2 + 60% pairs v2, regime-tilted. "
        "Orders only when macro news gate allows. Research α sleeves in separate tabs.",
        True,
        "live_execution.py · regime_models Ang/JPM + Bridgewater/BlackRock overlay",
        True,
    ),
    StrategySpec(
        "whale_flow",
        "Whale flow (conviction v2)",
        "PM / Microstructure",
        "POLY only: large-trade net flow ≥$12k, ≥4 trades, aligned with EMA trend.",
        True,
        "whale_strategy.whale_flow_signal_v2 · WorldQuant flow alpha",
        True,
    ),
    StrategySpec(
        "pairs_stat_arb",
        "Pairs stat arb (DOGE vs WIF)",
        "StatArb",
        "Enter |z|>2, exit |z|<0.75 on log(DOGE/WIF). Low corr vs whale.",
        True,
        "pairs_stat_arb.pairs_spread_returns_v2",
        True,
    ),
    StrategySpec(
        "ts_momentum_meme",
        "TS momentum (DOGE+WIF)",
        "Trend · Moskowitz",
        "20d time-series momentum, long-only meme basket. Uncorrelated to pairs MR.",
        True,
        "alpha_sleeves.ts_momentum_meme · Moskowitz/Ooi/Pedersen 2012 JFE",
        False,
    ),
    StrategySpec(
        "cs_momentum_rank",
        "CS momentum rank (DOGE vs WIF)",
        "Alpha · WorldQuant",
        "12d relative strength: long winner, short loser. Low corr vs TS mom & pairs.",
        True,
        "alpha_sleeves.cross_sectional_momentum · Kakushadze 101 Alphas",
        False,
    ),
    StrategySpec(
        "short_term_reversal",
        "Short-term reversal (meme basket)",
        "Alpha · WorldQuant / Lehmann",
        "3d reversal on DOGE+WIF EW basket — negative corr to 20d momentum.",
        True,
        "alpha_sleeves.short_term_reversal · Lehmann 1990 · WQ Alpha #12 family",
        False,
    ),
    StrategySpec(
        "poly_mean_reversion",
        "POLY mean reversion",
        "PM · MR",
        "Z-score MR on Yes probability — distinct from whale order flow.",
        True,
        "alpha_sleeves.poly_mean_reversion",
        False,
    ),
    StrategySpec(
        "vol_risk_parity",
        "Meme risk parity",
        "Smart beta · Ang",
        "Inverse-vol weights on DOGE/WIF (BlackRock smart-beta style).",
        True,
        "alpha_sleeves.vol_risk_parity · Ang Smart Beta guide",
        False,
    ),
]

DASHBOARD_VERSION = "2.5-whale-pairs-regime"
