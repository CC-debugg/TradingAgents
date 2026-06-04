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


# Production book only — unprofitable sleeves (poly EMA LS, latency, etc.) removed from UI.
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
        "whale_flow",
        "Whale flow (conviction v2)",
        "PM / Microstructure",
        "POLY only: large-trade net flow ≥$12k, ≥4 trades, aligned with EMA trend.",
        True,
        "whale_strategy.whale_flow_signal_v2",
        True,
    ),
    StrategySpec(
        "pairs_stat_arb",
        "Pairs stat arb (DOGE vs WIF)",
        "StatArb",
        "Meme pair: enter |z|>2, exit |z|<0.75 on log(DOGE/WIF).",
        True,
        "pairs_stat_arb.pairs_spread_returns_v2",
        True,
    ),
]

DASHBOARD_VERSION = "2.1-production"
