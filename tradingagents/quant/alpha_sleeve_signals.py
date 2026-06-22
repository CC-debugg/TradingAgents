"""Latest live signals for α sleeves (maps backtest logic → execution legs)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from tradingagents.quant.alpha_sleeves import _align_meme, _ew_ret


def _last_beta(doge: pd.Series, wif: pd.Series, lookback: int) -> tuple[float, float, float, float]:
    a, b, common = _align_meme(doge, wif)
    if len(common) < lookback + 2:
        return 0.0, 0.0, 0.0, 0.0
    ra, rb = a.pct_change(), b.pct_change()
    beta_s = ra.rolling(lookback).cov(rb) / rb.rolling(lookback).var().replace(0, np.nan)
    beta = float(beta_s.iloc[-1]) if not pd.isna(beta_s.iloc[-1]) else 0.0
    return beta, float(a.iloc[-1]), float(b.iloc[-1]), float(np.sign((ra - beta_s * rb).rolling(lookback).mean().iloc[-1]))


def latest_beta_neutral_signal(
    doge: pd.Series,
    wif: pd.Series,
    lookback: int = 15,
) -> dict[str, float]:
    """Residual momentum on DOGE with rolling WIF β (ts_momentum / vol_risk_parity)."""
    beta, doge_px, wif_px, sig = _last_beta(doge, wif, lookback)
    if np.isnan(sig):
        sig = 0.0
    hedge_usd_ratio = min(1.5, abs(beta))
    return {
        "signal": sig,
        "beta": beta,
        "doge_px": doge_px,
        "wif_px": wif_px,
        "wif_hedge_ratio": hedge_usd_ratio,
        "lookback": float(lookback),
    }


def latest_cs_momentum_signal(
    doge: pd.Series,
    wif: pd.Series,
    lag: int = 1,
    move_thresh: float = 0.04,
) -> dict[str, float]:
    a, b, common = _align_meme(doge, wif)
    if len(common) < 20:
        return {"signal": 0.0, "doge": 0.0, "wif": 0.0}
    ra, rb = a.pct_change(), b.pct_change()
    lag_d = float(ra.shift(lag).iloc[-1])
    rb_last = float(rb.iloc[-1])
    half = move_thresh / 2.0
    sig = 0.0
    if lag_d > move_thresh and rb_last < half:
        sig = -1.0
    elif lag_d < -move_thresh and rb_last > -half:
        sig = 1.0
    doge_leg, wif_leg = 0.0, 0.0
    if sig > 0:
        doge_leg, wif_leg = 1.0, -1.0
    elif sig < 0:
        doge_leg, wif_leg = -1.0, 1.0
    return {"signal": sig, "doge": doge_leg, "wif": wif_leg, "lag_doge_pct": lag_d, "wif_1d_pct": rb_last}


def latest_short_term_reversal_signal(
    doge: pd.Series,
    wif: pd.Series,
    lookback: int = 5,
    move_thresh: float = 0.08,
) -> dict[str, float]:
    a, b, common = _align_meme(doge, wif)
    if len(common) < lookback + 2:
        return {"signal": 0.0, "doge": 0.0, "wif": 0.0}
    past = float(_ew_ret(a, b).rolling(lookback).sum().iloc[-1])
    sig = 0.0
    if past <= -move_thresh:
        sig = 1.0
    elif past >= move_thresh:
        sig = -1.0
    leg = float(np.sign(sig)) if sig != 0 else 0.0
    return {"signal": sig, "doge": leg, "wif": leg, "basket_5d_pct": past}


def latest_binance_poly_latency_signal(
    binance: pd.Series,
    poly: pd.Series,
    lag: int = 1,
    move_thresh: float = 0.025,
) -> dict[str, float]:
    b = binance.dropna().sort_index()
    p = poly.reindex(b.index).ffill().dropna()
    common = b.index.intersection(p.index)
    if len(common) < 20:
        return {"signal": 0.0, "poly": 0.0}
    b, p = b.loc[common], p.loc[common]
    rb, rp = b.pct_change(), p.pct_change()
    lag_b = float(rb.shift(lag).iloc[-1])
    poly_today = float(rp.iloc[-1])
    half = move_thresh / 2.0
    sig = 0.0
    if lag_b > move_thresh and poly_today < half:
        sig = 1.0
    elif lag_b < -move_thresh and poly_today > -half:
        sig = -1.0
    return {
        "signal": sig,
        "poly": sig,
        "binance_lag_1d_pct": lag_b,
        "poly_1d_pct": poly_today,
    }


def latest_poly_mean_reversion_signal(
    prob: pd.Series,
    shock: float = 0.025,
    hold_days: int = 3,
) -> dict[str, float]:
    p = prob.dropna().sort_index()
    if len(p) < 5:
        return {"signal": 0.0, "poly": 0.0}
    dr = p.pct_change()
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
    return {"signal": pos, "poly": pos, "last_prob": float(p.iloc[-1])}
