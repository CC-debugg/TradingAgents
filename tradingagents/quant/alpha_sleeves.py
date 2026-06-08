"""Additional HF-style sleeves (low correlation vs whale flow / pairs stat arb)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from tradingagents.quant.trading_costs import FEE_BPS_PER_LEG, round_trip_cost_pairs_spread


def ts_momentum_meme_returns(
    doge: pd.Series,
    wif: pd.Series,
    lookback: int = 20,
    fee_bps: float = FEE_BPS_PER_LEG,
) -> pd.Series:
    """
    Time-series momentum on equal-weight meme basket (Moskowitz et al. 2012 style).
    Long-only; uncorrelated to pairs spread MR.
    """
    a = doge.dropna().sort_index()
    b = wif.reindex(a.index).ffill().dropna()
    common = a.index.intersection(b.index)
    if len(common) < lookback + 5:
        return pd.Series(dtype=float)
    a, b = a.loc[common], b.loc[common]
    ret = 0.5 * a.pct_change() + 0.5 * b.pct_change()
    mom = (1 + ret).rolling(lookback).apply(lambda x: float(np.prod(1 + x) - 1), raw=False)
    sig = pd.Series(0.0, index=common)
    sig[mom > 0] = 1.0
    sig[mom <= 0] = 0.0
    tc = round_trip_cost_pairs_spread(sig, fee_bps) * 0.5  # single synthetic leg
    return (sig.shift(1) * ret - tc).dropna()


def poly_mean_reversion_returns(
    prob: pd.Series,
    lookback: int = 20,
    entry_z: float = 1.5,
    exit_z: float = 0.5,
    fee_bps: float = FEE_BPS_PER_LEG,
) -> pd.Series:
    """Mean-reversion on Yes probability (distinct from whale order-flow)."""
    p = prob.dropna().sort_index()
    if len(p) < lookback + 5:
        return pd.Series(dtype=float)
    mu = p.rolling(lookback).mean()
    sd = p.rolling(lookback).std().replace(0, np.nan)
    z = (p - mu) / sd
    sig = pd.Series(0.0, index=p.index)
    pos = 0.0
    for dt in p.index:
        zi = z.loc[dt]
        if np.isnan(zi):
            sig.loc[dt] = pos
            continue
        if pos == 0.0:
            if zi < -entry_z:
                pos = 1.0
            elif zi > entry_z:
                pos = -1.0
        elif abs(zi) < exit_z:
            pos = 0.0
        sig.loc[dt] = pos
    dr = p.pct_change()
    tc = (sig.diff().abs() > 0) * (fee_bps / 10_000)
    return (sig.shift(1) * dr - tc).dropna()


def vol_risk_parity_meme_returns(
    doge: pd.Series,
    wif: pd.Series,
    vol_lb: int = 20,
    fee_bps: float = FEE_BPS_PER_LEG,
) -> pd.Series:
    """Inverse-vol risk parity long basket (Ang / BlackRock smart-beta style)."""
    a = doge.dropna().sort_index()
    b = wif.reindex(a.index).ffill().dropna()
    common = a.index.intersection(b.index)
    if len(common) < vol_lb + 5:
        return pd.Series(dtype=float)
    a, b = a.loc[common], b.loc[common]
    ra, rb = a.pct_change(), b.pct_change()
    va = ra.rolling(vol_lb).std()
    vb = rb.rolling(vol_lb).std()
    inv = (1 / va.replace(0, np.nan)).fillna(0) + (1 / vb.replace(0, np.nan)).fillna(0)
    wa = (1 / va.replace(0, np.nan)).fillna(0) / inv.replace(0, np.nan)
    wb = (1 / vb.replace(0, np.nan)).fillna(0) / inv.replace(0, np.nan)
    port = wa.shift(1) * ra + wb.shift(1) * rb
    sig = (wa + wb).fillna(0)
    tc = (sig.diff().abs() > 0.05) * (fee_bps / 10_000) * 2
    return (port - tc).dropna()


def cross_sectional_momentum_returns(
    doge: pd.Series,
    wif: pd.Series,
    lookback: int = 12,
    fee_bps: float = FEE_BPS_PER_LEG,
) -> pd.Series:
    """
    Relative-strength long winner / short loser (WorldQuant 101 Alphas rank style).
    Ref: Kakushadze (2016) "101 Formulaic Alphas" — cross-sectional rank momentum.
    PDF: Paper - 101 Alphas - WorldQuant World Quant.pdf
    """
    a = doge.dropna().sort_index()
    b = wif.reindex(a.index).ffill().dropna()
    common = a.index.intersection(b.index)
    if len(common) < lookback + 5:
        return pd.Series(dtype=float)
    a, b = a.loc[common], b.loc[common]
    ra = a.pct_change(lookback)
    rb = b.pct_change(lookback)
    sig = pd.Series(0.0, index=common)
    sig[ra > rb] = 1.0
    sig[ra < rb] = -1.0
    ret_a, ret_b = a.pct_change(), b.pct_change()
    spread_ret = sig.shift(1) * (ret_a - ret_b) * 0.5
    tc = round_trip_cost_pairs_spread(sig, fee_bps)
    return (spread_ret - tc).dropna()


def short_term_reversal_returns(
    doge: pd.Series,
    wif: pd.Series,
    lookback: int = 3,
    fee_bps: float = FEE_BPS_PER_LEG,
) -> pd.Series:
    """
    Short-horizon reversal on equal-weight meme basket.
    Ref: Lehmann (1990) + Jegadeesh (1990); WorldQuant 101 Alphas reversal family (e.g. Alpha #12).
    PDF: Paper - 101 Alphas - WorldQuant World Quant.pdf
    """
    a = doge.dropna().sort_index()
    b = wif.reindex(a.index).ffill().dropna()
    common = a.index.intersection(b.index)
    if len(common) < lookback + 5:
        return pd.Series(dtype=float)
    a, b = a.loc[common], b.loc[common]
    ret = 0.5 * a.pct_change() + 0.5 * b.pct_change()
    past = ret.rolling(lookback).sum()
    sig = pd.Series(0.0, index=common)
    sig[past < 0] = 1.0
    sig[past > 0] = -1.0
    tc = round_trip_cost_pairs_spread(sig, fee_bps) * 0.5
    return (sig.shift(1) * ret - tc).dropna()
