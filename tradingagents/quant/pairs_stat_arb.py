"""Pairs / spread stat-arb on meme legs (DOGE vs WIF z-score)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def pairs_spread_returns(
    price_a: pd.Series,
    price_b: pd.Series,
    lookback: int = 20,
    entry_z: float = 1.5,
    fee_bps: float = 10.0,
) -> pd.Series:
    """
    Mean-reversion on log price ratio z-score.
    Long spread (long A short B) when z < -entry; opposite when z > entry.
    """
    a = price_a.dropna().sort_index()
    b = price_b.reindex(a.index).ffill().dropna()
    common = a.index.intersection(b.index)
    if len(common) < lookback + 5:
        return pd.Series(dtype=float)
    a, b = a.loc[common], b.loc[common]
    spread = np.log(a / b)
    mu = spread.rolling(lookback).mean()
    sd = spread.rolling(lookback).std().replace(0, np.nan)
    z = (spread - mu) / sd
    sig = pd.Series(0.0, index=common)
    sig[z < -entry_z] = 1.0
    sig[z > entry_z] = -1.0
    ret_a = a.pct_change()
    ret_b = b.pct_change()
    spread_ret = sig.shift(1) * (ret_a - ret_b)
    tc = (sig.diff().abs() > 0) * (fee_bps / 10_000) * 2
    return (spread_ret - tc).dropna()


def pairs_spread_returns_v2(
    price_a: pd.Series,
    price_b: pd.Series,
    lookback: int = 20,
    entry_z: float = 2.0,
    exit_z: float = 0.75,
    fee_bps: float = 10.0,
) -> pd.Series:
    """Stricter entry (|z|>2) + exit when |z|<0.75 — fewer but higher-quality trades."""
    a = price_a.dropna().sort_index()
    b = price_b.reindex(a.index).ffill().dropna()
    common = a.index.intersection(b.index)
    if len(common) < lookback + 5:
        return pd.Series(dtype=float)
    a, b = a.loc[common], b.loc[common]
    spread = np.log(a / b)
    mu = spread.rolling(lookback).mean()
    sd = spread.rolling(lookback).std().replace(0, np.nan)
    z = (spread - mu) / sd
    sig = pd.Series(0.0, index=common)
    pos = 0.0
    for dt in common:
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
    ret_a = a.pct_change()
    ret_b = b.pct_change()
    spread_ret = sig.shift(1) * (ret_a - ret_b)
    tc = (sig.diff().abs() > 0) * (fee_bps / 10_000) * 2
    return (spread_ret - tc).dropna()


def latest_pairs_signal(
    price_a: pd.Series,
    price_b: pd.Series,
    lookback: int = 20,
    entry_z: float = 2.0,
) -> dict[str, float]:
    a = price_a.dropna().sort_index()
    b = price_b.reindex(a.index).ffill().dropna()
    common = a.index.intersection(b.index)
    if len(common) < lookback + 2:
        return {"spread_z": 0.0, "doge": 0.0, "wif": 0.0}
    spread = np.log(a.loc[common] / b.loc[common])
    mu = spread.rolling(lookback).mean()
    sd = spread.rolling(lookback).std().replace(0, np.nan)
    z = float(((spread - mu) / sd).iloc[-1])
    doge, wif = 0.0, 0.0
    if z < -entry_z:
        doge, wif = 1.0, -1.0
    elif z > entry_z:
        doge, wif = -1.0, 1.0
    return {"spread_z": round(z, 4), "doge": doge, "wif": wif}
