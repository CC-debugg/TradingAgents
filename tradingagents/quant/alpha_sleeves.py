"""HF-style α sleeves — low correlation vs whale flow / pairs stat arb (v2 tuned)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from tradingagents.quant.trading_costs import FEE_BPS_PER_LEG, round_trip_cost_pairs_spread


def _align_meme(doge: pd.Series, wif: pd.Series) -> tuple[pd.Series, pd.Series, pd.Index]:
    a = doge.dropna().sort_index()
    b = wif.reindex(a.index).ffill().dropna()
    common = a.index.intersection(b.index)
    return a.loc[common], b.loc[common], common


def _ew_ret(a: pd.Series, b: pd.Series) -> pd.Series:
    return 0.5 * a.pct_change() + 0.5 * b.pct_change()


def ts_momentum_meme_returns(
    doge: pd.Series,
    wif: pd.Series,
    lookback: int = 15,
    fee_bps: float = FEE_BPS_PER_LEG,
) -> pd.Series:
    """
    Beta-neutral residual momentum on DOGE (Moskowitz 2012 + Ang factor-neutral).
    Long DOGE residual vs WIF beta — uncorrelated to pairs spread MR.
    PDF: Moskowitz/Ooi/Pedersen JFE 2012; Smart Beta - Blackrock Guide by Andrew Ang.pdf
    """
    a, b, common = _align_meme(doge, wif)
    if len(common) < lookback + 10:
        return pd.Series(dtype=float)
    ra, rb = a.pct_change(), b.pct_change()
    beta = ra.rolling(lookback).cov(rb) / rb.rolling(lookback).var().replace(0, np.nan)
    resid = ra - beta * rb
    sig = np.sign(resid.rolling(lookback).mean()).fillna(0.0)
    tc = round_trip_cost_pairs_spread(sig, fee_bps) * 0.5
    return (sig.shift(1) * ra - tc).dropna()


def cs_momentum_rank_returns(
    doge: pd.Series,
    wif: pd.Series,
    lag: int = 1,
    move_thresh: float = 0.04,
    fee_bps: float = FEE_BPS_PER_LEG,
) -> pd.Series:
    """
    Cross-asset lead–lag spread (DOGE leads WIF) — HF stat-arb / microstructure sleeve.
    Distinct from production pairs z-score MR (different signal, lower corr).
    Ref: JPMorgan stat-arb / cross-asset microstructure ( practitioner HF ).
    """
    a, b, common = _align_meme(doge, wif)
    if len(common) < 20:
        return pd.Series(dtype=float)
    ra, rb = a.pct_change(), b.pct_change()
    sig = pd.Series(0.0, index=common)
    half = move_thresh / 2.0
    sig[(ra.shift(lag) > move_thresh) & (rb < half)] = -1.0
    sig[(ra.shift(lag) < -move_thresh) & (rb > -half)] = 1.0
    spread = ra - rb
    tc = round_trip_cost_pairs_spread(sig, fee_bps)
    return (sig.shift(1) * spread - tc).dropna()


def cross_sectional_momentum_returns(
    doge: pd.Series,
    wif: pd.Series,
    lookback: int = 12,
    fee_bps: float = FEE_BPS_PER_LEG,
) -> pd.Series:
    """Alias for lead–lag sleeve (legacy id cs_momentum_rank)."""
    return cs_momentum_rank_returns(doge, wif, lag=1, move_thresh=0.04, fee_bps=fee_bps)


def short_term_reversal_returns(
    doge: pd.Series,
    wif: pd.Series,
    lookback: int = 5,
    move_thresh: float = 0.08,
    fee_bps: float = FEE_BPS_PER_LEG,
) -> pd.Series:
    """
    Extreme-move reversal on EW meme basket (only fade |5d|≥8% moves).
    Ref: Lehmann (1990); WorldQuant 101 Alphas reversal family.
    PDF: Paper - 101 Alphas - WorldQuant World Quant.pdf
    """
    a, b, common = _align_meme(doge, wif)
    if len(common) < lookback + 10:
        return pd.Series(dtype=float)
    ret = _ew_ret(a, b)
    past = ret.rolling(lookback).sum()
    sig = pd.Series(0.0, index=common)
    sig[past <= -move_thresh] = 1.0
    sig[past >= move_thresh] = -1.0
    tc = round_trip_cost_pairs_spread(sig, fee_bps) * 0.5
    return (sig.shift(1) * ret - tc).dropna()


def poly_mean_reversion_returns(
    prob: pd.Series,
    shock: float = 0.025,
    hold_days: int = 3,
    fee_bps: float = FEE_BPS_PER_LEG,
) -> pd.Series:
    """
    Fade large 1-day shocks in Yes probability (prediction-market microstructure).
    Uncorrelated to whale order-flow (which follows size, not shock fade).
    Ref: HF PM desks — shock mean-reversion on event contracts.
    """
    p = prob.dropna().sort_index()
    if len(p) < 30:
        return pd.Series(dtype=float)
    dr = p.pct_change()
    sig = pd.Series(0.0, index=p.index)
    pos = 0.0
    hold = 0
    for dt in p.index:
        if hold > 0:
            hold -= 1
        if pos != 0.0 and hold == 0:
            pos = 0.0
        d = dr.loc[dt]
        if pos == 0.0 and not np.isnan(d) and abs(d) >= shock:
            pos = -float(np.sign(d))
            hold = hold_days
        sig.loc[dt] = pos
    tc = (sig.diff().abs() > 0) * (fee_bps / 10_000)
    return (sig.shift(1) * dr - tc).dropna()


def vol_risk_parity_meme_returns(
    doge: pd.Series,
    wif: pd.Series,
    lookback: int = 25,
    fee_bps: float = FEE_BPS_PER_LEG,
) -> pd.Series:
    """
    Slow beta-neutral residual momentum (low turnover vs fast sleeve).
    Ang / BlackRock smart-beta: secondary horizon diversifier.
    PDF: Smart Beta - Blackrock Guide by Andrew Ang.pdf
    """
    return ts_momentum_meme_returns(doge, wif, lookback=lookback, fee_bps=fee_bps)
