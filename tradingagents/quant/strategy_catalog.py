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
        "Default for real money: 40% whale v2 + 60% pairs v2. Orders only when macro news gate allows.",
        True,
        "live_execution.py — use this sleeve for CLOB",
        True,
    ),
    StrategySpec(
        "multi_strategy_index",
        "Multi-Strategy Index (1/n)",
        "HF · Equal-weight book",
        "Equal 1/n blend of all 7 base sleeves. Official $1M paper PnL tracks this index from sim start.",
        True,
        "hf_manager.equal_weight_returns · benchmark + paper book",
        False,
    ),
    StrategySpec(
        "hf_manager_book",
        "HF Manager (regime dynamic)",
        "HF · Regime allocator",
        "Bridgewater + Ang & Bekaert + JPM tilt × inverse-correlation weights across 7 sleeves. Refreshed each /api/live.",
        True,
        "hf_manager.hf_manager_returns · regime_allocator",
        False,
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
        "Beta-neutral momentum (DOGE)",
        "Trend · Moskowitz / Ang",
        "15d residual momentum on DOGE vs WIF β. Factor-neutral — low corr vs pairs MR.",
        True,
        "alpha_sleeves.ts_momentum_meme · Moskowitz JFE 2012 · Ang Smart Beta",
        False,
    ),
    StrategySpec(
        "cs_momentum_rank",
        "Lead–lag spread (DOGE→WIF)",
        "StatArb · Microstructure",
        "Fade lagged DOGE moves vs WIF — HF cross-asset stat arb sleeve.",
        True,
        "alpha_sleeves.cs_momentum_rank · JPM / HF stat-arb microstructure",
        False,
    ),
    StrategySpec(
        "short_term_reversal",
        "Extreme-move reversal",
        "Alpha · Lehmann / WQ",
        "Fade only |5d|≥8% EW basket moves — cuts churn vs naive 3d reversal.",
        True,
        "alpha_sleeves.short_term_reversal · Lehmann 1990 · WQ 101 Alphas",
        False,
    ),
    StrategySpec(
        "poly_mean_reversion",
        "POLY shock fade",
        "PM · Microstructure",
        "Fade ≥2.5% daily Yes-prob shocks — uncorrelated to whale order flow.",
        True,
        "alpha_sleeves.poly_mean_reversion · HF prediction-market shock MR",
        False,
    ),
    StrategySpec(
        "vol_risk_parity",
        "Slow beta-neutral (DOGE)",
        "Smart beta · Ang",
        "25d residual momentum — low-turnover diversifier vs fast β-neutral sleeve.",
        True,
        "alpha_sleeves.vol_risk_parity · Ang Smart Beta guide",
        False,
    ),
    StrategySpec(
        "rl_tensortrade",
        "RL sleeve (TensorTrade · research)",
        "RL · Research track",
        "Offline Q-learning on DOGE features (MOM/VOL/RSI grid), OOS only, 5 bps/leg TC. "
        "Trained in py3.12 TensorTrade env — research only, excluded from Equal Index and PROD.",
        True,
        "integrations/rl_tensortrade · TensorTrade (Apache 2.0) · Kelly & Xiu ML survey",
        False,
    ),
]

DASHBOARD_VERSION = "2.8-rl-purged-audit"
