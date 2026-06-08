"""
Dual macro regime stack (HF allocator literature).

Primary models implemented:
1. Ang & Bekaert — 2-state stock–bond Markov-style risk regime
2. JPMorgan AM — 4-quadrant growth × inflation business-cycle regime
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingagents.quant.macro_regime_tilt import classify_regime

# --- Ang & Bekaert (2002) two-state tilts ---
# Ref: Ang & Bekaert, "International Asset Allocation with Regime Shifts in Stock Returns"
#      JFE 2002; summary in user PDF "Markov Regimes - How Regimes Affect Asset Allocation - Ang and Bekaert.pdf"
AB_REGIME_META: dict[str, dict[str, Any]] = {
    "ab_bull": {
        "label": "AB bull (low vol · risk-on)",
        "source": "Ang & Bekaert (2002) · Markov risk-on state",
        "pdf": "Markov Regimes - How Regimes Affect Asset Allocation - By Ang and Bekaert.pdf",
        "description": "Equity vol below median, equity momentum positive — favor trend & stat-arb risk.",
        "sleeve_tilt": {
            "whale_flow": 1.1,
            "pairs_stat_arb": 1.15,
            "ts_momentum_meme": 1.25,
            "cs_momentum_rank": 1.2,
            "poly_mean_reversion": 0.85,
            "short_term_reversal": 0.7,
            "vol_risk_parity": 0.95,
        },
    },
    "ab_bear": {
        "label": "AB bear (high vol · risk-off)",
        "source": "Ang & Bekaert (2002) · Markov risk-off state",
        "pdf": "Markov Regimes - How Regimes Affect Asset Allocation - By Ang and Bekaert.pdf",
        "description": "Elevated equity vol or negative equity trend — cut beta, favor MR & risk parity.",
        "sleeve_tilt": {
            "whale_flow": 0.6,
            "pairs_stat_arb": 0.75,
            "ts_momentum_meme": 0.45,
            "cs_momentum_rank": 0.5,
            "poly_mean_reversion": 1.15,
            "short_term_reversal": 1.2,
            "vol_risk_parity": 1.25,
        },
    },
}

# --- JPMorgan AM 4-quadrant growth × inflation ---
# Ref: JPMorgan Asset Management "Regime-based investing" (Macro Quant team)
#      + business-cycle allocation (user PDFs: JPM Regime-based investing;
#        Macro Regimes - Dynamic_Asset_Allocation_Through_the_Business_Cycle.pdf)
JPM_REGIME_META: dict[str, dict[str, Any]] = {
    "jpm_goldilocks": {
        "label": "Goldilocks (growth↑ inflation↓)",
        "source": "JPM AM Regime-based investing · business-cycle quadrant",
        "pdf": "Markov Regimes - JPM Regime-based investing.pdf",
        "description": "Best for risk assets + pairs momentum.",
        "sleeve_tilt": {
            "whale_flow": 1.05,
            "pairs_stat_arb": 1.2,
            "ts_momentum_meme": 1.15,
            "cs_momentum_rank": 1.15,
            "poly_mean_reversion": 0.9,
            "short_term_reversal": 0.85,
            "vol_risk_parity": 1.0,
        },
    },
    "jpm_reflation": {
        "label": "Reflation (growth↑ inflation↑)",
        "source": "JPM AM · inflationary expansion",
        "pdf": "Macro Regimes - Dynamic_Asset_Allocation_Through_the_Business_Cycle.pdf",
        "description": "Favor real assets / reduce duration-sensitive trend.",
        "sleeve_tilt": {
            "whale_flow": 0.95,
            "pairs_stat_arb": 1.0,
            "ts_momentum_meme": 0.9,
            "cs_momentum_rank": 0.95,
            "poly_mean_reversion": 1.05,
            "short_term_reversal": 1.0,
            "vol_risk_parity": 1.1,
        },
    },
    "jpm_stagflation": {
        "label": "Stagflation (growth↓ inflation↑)",
        "source": "JPM AM · worst quadrant for beta",
        "pdf": "Macro Regimes - Dynamic_Asset_Allocation_Through_the_Business_Cycle.pdf",
        "description": "Defensive: MR + vol parity; cut momentum.",
        "sleeve_tilt": {
            "whale_flow": 0.55,
            "pairs_stat_arb": 0.7,
            "ts_momentum_meme": 0.4,
            "cs_momentum_rank": 0.45,
            "poly_mean_reversion": 1.1,
            "short_term_reversal": 1.15,
            "vol_risk_parity": 1.2,
        },
    },
    "jpm_deflation": {
        "label": "Deflation (growth↓ inflation↓)",
        "source": "JPM AM · flight to quality",
        "pdf": "Markov Regimes - JPM Regime-based investing.pdf",
        "description": "Bond-friendly; low beta sleeves only.",
        "sleeve_tilt": {
            "whale_flow": 0.65,
            "pairs_stat_arb": 0.8,
            "ts_momentum_meme": 0.5,
            "cs_momentum_rank": 0.55,
            "poly_mean_reversion": 1.0,
            "short_term_reversal": 1.1,
            "vol_risk_parity": 1.15,
        },
    },
}


def ang_bekaert_regime(barra: pd.DataFrame, vol_lb: int = 60) -> pd.Series:
    """
    Two-state proxy for Ang & Bekaert Markov risk regimes.
    Bull: equity vol < rolling median AND 20d equity return > 0.
    """
    if barra.empty:
        return pd.Series(dtype=str)
    eq = barra.get("BARRA_EQUITY_MARKET", barra.get("ECON_GROWTH"))
    if eq is None or eq.dropna().empty:
        return pd.Series("ab_bull", index=barra.index, dtype=object)
    eq = eq.dropna()
    vol = eq.rolling(vol_lb).std()
    med_vol = vol.expanding(min_periods=vol_lb).median()
    mom20 = eq.rolling(20).sum()
    regime = pd.Series("ab_bear", index=eq.index, dtype=object)
    regime[(vol <= med_vol) & (mom20 > 0)] = "ab_bull"
    return regime.reindex(barra.index).ffill().fillna("ab_bull")


def jpm_growth_inflation_regime(barra: pd.DataFrame, lb: int = 20) -> pd.Series:
    """Four-quadrant growth × inflation from Barra ETF factor returns."""
    if barra.empty:
        return pd.Series(dtype=str)
    growth = barra.get("BARRA_EQUITY_MARKET", barra.get("ECON_GROWTH"))
    infl = barra.get("BARRA_INFLATION", barra.get("INFLATION"))
    if growth is None:
        return pd.Series("jpm_goldilocks", index=barra.index, dtype=object)
    g = growth.rolling(lb).mean()
    if infl is not None and not infl.dropna().empty:
        i = infl.rolling(lb).mean()
    else:
        rates = barra.get("BARRA_RATES", barra.get("POLICY_RATES"))
        i = -rates.rolling(lb).mean() if rates is not None else pd.Series(0, index=g.index)
    regime = pd.Series("jpm_goldilocks", index=g.index, dtype=object)
    regime[(g > 0) & (i > 0)] = "jpm_reflation"
    regime[(g <= 0) & (i > 0)] = "jpm_stagflation"
    regime[(g <= 0) & (i <= 0)] = "jpm_deflation"
    return regime.reindex(barra.index).ffill().fillna("jpm_goldilocks")


def _merge_tilts(ab_id: str, jpm_id: str) -> dict[str, float]:
    ab = AB_REGIME_META.get(ab_id, AB_REGIME_META["ab_bull"])["sleeve_tilt"]
    jpm = JPM_REGIME_META.get(jpm_id, JPM_REGIME_META["jpm_goldilocks"])["sleeve_tilt"]
    keys = set(ab) | set(jpm)
    merged = {}
    for k in keys:
        merged[k] = float(np.sqrt(ab.get(k, 1.0) * jpm.get(k, 1.0)))
    return merged


def build_dual_regime_snapshot(barra: pd.DataFrame) -> dict[str, Any]:
    """Combined Ang & Bekaert + JPM regime state for dashboard & allocator."""
    legacy = classify_regime(barra)
    ab_s = ang_bekaert_regime(barra)
    jpm_s = jpm_growth_inflation_regime(barra)

    ab_cur = str(ab_s.iloc[-1]) if len(ab_s) else "ab_bull"
    jpm_cur = str(jpm_s.iloc[-1]) if len(jpm_s) else "jpm_goldilocks"
    leg_cur = str(legacy.iloc[-1]) if len(legacy) else "neutral"

    ab_meta = AB_REGIME_META.get(ab_cur, AB_REGIME_META["ab_bull"])
    jpm_meta = JPM_REGIME_META.get(jpm_cur, JPM_REGIME_META["jpm_goldilocks"])
    merged_tilt = _merge_tilts(ab_cur, jpm_cur)

    return {
        "primary_model": "Ang & Bekaert (2002) + JPM AM business-cycle quadrants",
        "ang_bekaert": {
            "current": ab_cur,
            "meta": ab_meta,
            "distribution": _dist_pct(ab_s),
        },
        "jpm_quadrant": {
            "current": jpm_cur,
            "meta": jpm_meta,
            "distribution": _dist_pct(jpm_s),
        },
        "legacy_barra": {"current": leg_cur, "distribution": _dist_pct(legacy)},
        "merged_sleeve_tilt": merged_tilt,
        "as_of": str(barra.index[-1].date()) if len(barra) else None,
        "literature": [
            {
                "authors": "Ang & Bekaert",
                "year": 2002,
                "title": "International Asset Allocation with Regime Shifts in Stock Returns",
                "pdf": "Markov Regimes - How Regimes Affect Asset Allocation - By Ang and Bekaert.pdf",
                "use": "2-state risk-on / risk-off → scales beta sleeves",
            },
            {
                "authors": "JPMorgan Asset Management",
                "year": "2018+",
                "title": "Regime-based investing / Dynamic asset allocation through the business cycle",
                "pdf": "Markov Regimes - JPM Regime-based investing.pdf; Macro Regimes - Dynamic_Asset_Allocation_Through_the_Business_Cycle.pdf",
                "use": "4-quadrant growth×inflation → sleeve rotation",
            },
        ],
    }


def _dist_pct(s: pd.Series) -> dict[str, float]:
    if s is None or s.empty:
        return {}
    vc = s.value_counts(normalize=True)
    return {str(k): round(float(v) * 100, 1) for k, v in vc.items()}
