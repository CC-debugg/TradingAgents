"""Dynamic sleeve weights from dual macro regimes + correlation overlay."""

from __future__ import annotations

import numpy as np
import pandas as pd

BASE_SLEEVES = (
    "whale_flow",
    "pairs_stat_arb",
    "ts_momentum_meme",
    "cs_momentum_rank",
    "binance_poly_latency",
    "short_term_reversal",
    "poly_mean_reversion",
    "vol_risk_parity",
)


def _corr_matrix(returns_map: dict[str, pd.Series]) -> pd.DataFrame:
    df = pd.DataFrame({k: v for k, v in returns_map.items() if v is not None and len(v)}).dropna(how="all")
    if df.shape[1] < 2 or len(df) < 20:
        return pd.DataFrame()
    return df.corr()


def inverse_corr_weights(corr: pd.DataFrame, base: dict[str, float]) -> dict[str, float]:
    if corr.empty:
        total = sum(base.values()) or 1.0
        return {k: round(v / total, 4) for k, v in base.items()}
    avg_corr = corr.mean(axis=1)
    adj = {sid: max(0.05, w * (1.0 - max(0.0, float(avg_corr.get(sid, 0.5))))) for sid, w in base.items()}
    total = sum(adj.values()) or 1.0
    return {k: round(v / total, 4) for k, v in adj.items()}


def regime_dynamic_weights(
    returns_map: dict[str, pd.Series],
    merged_tilt: dict[str, float] | None = None,
    production_only: bool = False,
) -> dict[str, float]:
    """Merged Ang & Bekaert + JPM tilts × inverse-correlation blend."""
    tilt = merged_tilt or {}
    base: dict[str, float] = {}
    for sid in BASE_SLEEVES:
        if production_only and sid not in ("whale_flow", "pairs_stat_arb"):
            continue
        if sid not in returns_map or returns_map[sid].dropna().empty:
            continue
        base[sid] = float(tilt.get(sid, 1.0))
    if not base:
        return {"whale_flow": 0.4, "pairs_stat_arb": 0.6}
    corr = _corr_matrix({k: returns_map[k] for k in base})
    return inverse_corr_weights(corr, base)


def blend_returns(returns_map: dict[str, pd.Series], weights: dict[str, float]) -> pd.Series:
    cols = {k: returns_map[k] for k in weights if k in returns_map and len(returns_map[k])}
    if not cols:
        return pd.Series(dtype=float)
    df = pd.DataFrame(cols).fillna(0)
    w = pd.Series({k: weights[k] for k in df.columns})
    w = w / w.sum()
    return df.dot(w)
