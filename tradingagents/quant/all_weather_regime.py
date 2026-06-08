"""Bridgewater / BlackRock–style macro regime + All Weather sleeve tilts (research overlay)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingagents.quant.macro_regime_tilt import classify_regime
from tradingagents.quant.trading_costs import FEE_BPS_PER_LEG, ROUND_TRIP_BPS

# Regime → narrative + production sleeve multipliers (All Weather–style balance)
REGIME_META: dict[str, dict[str, Any]] = {
    "risk_on": {
        "label": "Risk-on",
        "style": "Bridgewater: growth + liquidity",
        "description": "Equities up, rates stable/down — favor pairs momentum & whale trend.",
        "sleeve_tilt": {"whale_flow": 1.0, "pairs_stat_arb": 1.15, "live_composite": 1.08,
                        "ts_momentum_meme": 1.2, "cs_momentum_rank": 1.15, "short_term_reversal": 0.85,
                        "poly_mean_reversion": 0.9, "vol_risk_parity": 1.0},
        "all_weather_weight_hint": "↑ risk assets, ↓ defensive",
    },
    "risk_off": {
        "label": "Risk-off",
        "style": "BlackRock: flight to quality",
        "description": "Equities down, bonds bid — cut risk; news gate may block entries.",
        "sleeve_tilt": {"whale_flow": 0.65, "pairs_stat_arb": 0.75, "live_composite": 0.70,
                        "ts_momentum_meme": 0.5, "poly_mean_reversion": 0.8, "vol_risk_parity": 1.1},
        "all_weather_weight_hint": "↑ Treasuries / cash, ↓ beta",
    },
    "inflation": {
        "label": "Inflation",
        "style": "All Weather: inflation sleeve",
        "description": "Inflation factor elevated — reduce duration-sensitive beta.",
        "sleeve_tilt": {"whale_flow": 0.85, "pairs_stat_arb": 0.90, "live_composite": 0.88,
                        "ts_momentum_meme": 0.7, "poly_mean_reversion": 1.0, "vol_risk_parity": 1.15},
        "all_weather_weight_hint": "↑ TIPS / commodities proxy",
    },
    "neutral": {
        "label": "Neutral",
        "style": "Balanced book",
        "description": "No strong macro tilt — run base 40/60 composite.",
        "sleeve_tilt": {"whale_flow": 1.0, "pairs_stat_arb": 1.0, "live_composite": 1.0,
                        "ts_momentum_meme": 1.0, "poly_mean_reversion": 1.0, "vol_risk_parity": 1.0},
        "all_weather_weight_hint": "Target balanced risk parity",
    },
}


WORKFLOW_STEPS: list[dict[str, Any]] = [
    {
        "id": "data",
        "title": "1 · Data ingest",
        "detail": "Polymarket CLOB/Gamma (POLY), whale trades API, DOGE/WIF spot (Yahoo/Kraken/CoinGecko).",
    },
    {
        "id": "regime",
        "title": "2 · Macro regime (Barra ETF proxy)",
        "detail": "Ang & Bekaert 2-state + JPM 4-quadrant growth×inflation → merged sleeve tilts.",
    },
    {
        "id": "news",
        "title": "3 · News gate",
        "detail": "ECB RSS (+ FRED) → macro score; block or half size before signals hit CLOB.",
    },
    {
        "id": "signals",
        "title": "4 · Alpha signals",
        "detail": "Whale v2 (flow + EMA) → POLY; Pairs v2 (|z|>2) → DOGE/WIF.",
    },
    {
        "id": "composite",
        "title": "5 · Live composite",
        "detail": "40% whale + 60% pairs; apply regime tilt + news gate → CLOB intents (dry-run default).",
    },
    {
        "id": "risk",
        "title": "6 · Risk & attribution",
        "detail": "Barra-style factor β per sleeve; monitor drawdown / Sharpe on rolling backtest window.",
    },
]


def build_regime_snapshot(barra: pd.DataFrame) -> dict[str, Any]:
    """Latest regime + distribution over lookback window."""
    if barra.empty:
        return {
            "current": "neutral",
            "meta": REGIME_META["neutral"],
            "distribution": {},
            "as_of": None,
            "model": "Barra ETF proxy · Bridgewater/BlackRock All Weather overlay",
        }

    regime = classify_regime(barra)
    if regime.empty:
        current = "neutral"
    else:
        current = str(regime.iloc[-1])
    meta = REGIME_META.get(current, REGIME_META["neutral"])
    dist = regime.value_counts(normalize=True).to_dict() if len(regime) else {}
    dist_pct = {str(k): round(float(v) * 100, 1) for k, v in dist.items()}

    history = []
    if len(regime):
        for dt, r in regime.tail(90).items():
            history.append({"t": str(pd.Timestamp(dt).date()), "regime": str(r)})

    return {
        "current": current,
        "meta": meta,
        "sleeve_tilt": meta.get("sleeve_tilt", {}),
        "distribution": dist_pct,
        "as_of": str(regime.index[-1].date()) if len(regime) else None,
        "model": "Barra ETF proxy · Bridgewater All Weather + BlackRock smart-beta macro overlay",
        "bridgewater": {
            "label": "Bridgewater All Weather",
            "pdf": "Macro Regimes - Dynamic_Asset_Allocation_Through_the_Business_Cycle.pdf",
            "note": "Four macro sleeves: growth / inflation / deflation / neutral balance.",
        },
        "blackrock": {
            "label": "BlackRock · Andrew Ang smart beta",
            "pdf": "Smart Beta - Blackrock Guide by Andrew Ang.pdf",
            "note": "Macro factor tilts via Barra ETF proxies (equity, rates, inflation, credit).",
        },
        "history": history,
        "all_regimes": [
            {
                "id": k,
                "label": v["label"],
                "style": v["style"],
                "description": v["description"],
                "all_weather_weight_hint": v["all_weather_weight_hint"],
                "sleeve_tilt": v.get("sleeve_tilt", {}),
            }
            for k, v in REGIME_META.items()
        ],
    }


def transaction_costs_json() -> dict[str, Any]:
    return {
        "fee_bps_per_leg": FEE_BPS_PER_LEG,
        "round_trip_bps": ROUND_TRIP_BPS,
        "note": "5 bps on each buy or sell (10 bps round-trip). Applied on every signal change in backtest + live.",
    }
