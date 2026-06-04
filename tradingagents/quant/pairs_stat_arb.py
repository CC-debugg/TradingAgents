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
    d = pairs_execution_detail(price_a, price_b, lookback=lookback, entry_z=entry_z)
    return {"spread_z": float(d["spread_z"]), "doge": float(d["doge"]), "wif": float(d["wif"])}


def pairs_execution_detail(
    price_a: pd.Series,
    price_b: pd.Series,
    lookback: int = 20,
    entry_z: float = 2.0,
    exit_z: float = 0.75,
) -> dict[str, float | str | list | bool | None]:
    """Pairs sleeve snapshot with prices and threshold checks."""
    sig = {"spread_z": 0.0, "doge": 0.0, "wif": 0.0}
    checks: list[dict] = []
    a = price_a.dropna().sort_index() if price_a is not None else pd.Series(dtype=float)
    b = price_b.dropna().sort_index() if price_b is not None else pd.Series(dtype=float)
    if a.empty or b.empty:
        return {
            **sig,
            "doge_price": None,
            "wif_price": None,
            "doge_as_of": None,
            "wif_as_of": None,
            "log_ratio": None,
            "entry_z": entry_z,
            "exit_z": exit_z,
            "lookback": lookback,
            "checks": [
                {"id": "data", "label": "DOGE & WIF prices loaded", "ok": False, "value": "missing"},
            ],
        }

    common = a.index.intersection(b.reindex(a.index).dropna().index)
    if len(common) < lookback + 2:
        return {
            **sig,
            "doge_price": round(float(a.iloc[-1]), 6),
            "wif_price": round(float(b.reindex(a.index).ffill().iloc[-1]), 6),
            "doge_as_of": str(a.index[-1].date()),
            "wif_as_of": str(b.reindex(a.index).ffill().index[-1].date()),
            "log_ratio": None,
            "entry_z": entry_z,
            "exit_z": exit_z,
            "lookback": lookback,
            "checks": [{"id": "data", "label": "Enough history for z-score", "ok": False, "value": str(len(common))}],
        }

    aa = a.loc[common]
    bb = b.reindex(common).ffill()
    spread = np.log(aa / bb)
    mu = spread.rolling(lookback).mean()
    sd = spread.rolling(lookback).std().replace(0, np.nan)
    z = float(((spread - mu) / sd).iloc[-1])
    doge_sig, wif_sig = 0.0, 0.0
    if z < -entry_z:
        doge_sig, wif_sig = 1.0, -1.0
    elif z > entry_z:
        doge_sig, wif_sig = -1.0, 1.0

    doge_px = float(aa.iloc[-1])
    wif_px = float(bb.iloc[-1])
    doge_chg = None
    if len(aa) >= 2:
        doge_chg = round(float((aa.iloc[-1] / aa.iloc[-2] - 1) * 100), 2)
    wif_chg = None
    if len(bb) >= 2:
        wif_chg = round(float((bb.iloc[-1] / bb.iloc[-2] - 1) * 100), 2)

    checks = [
        {
            "id": "entry",
            "label": f"|z| > {entry_z} to open spread",
            "ok": abs(z) > entry_z,
            "value": f"z = {z:.3f}",
        },
        {
            "id": "exit",
            "label": f"|z| < {exit_z} to flatten",
            "ok": abs(z) < exit_z,
            "value": f"z = {z:.3f}",
        },
    ]

    return {
        "spread_z": round(z, 4),
        "doge": doge_sig,
        "wif": wif_sig,
        "doge_price": round(doge_px, 6),
        "wif_price": round(wif_px, 6),
        "doge_as_of": str(aa.index[-1].date()),
        "wif_as_of": str(bb.index[-1].date()),
        "doge_chg_1d_pct": doge_chg,
        "wif_chg_1d_pct": wif_chg,
        "log_ratio": round(float(spread.iloc[-1]), 4),
        "spread_mean": round(float(mu.iloc[-1]), 4) if not pd.isna(mu.iloc[-1]) else None,
        "spread_std": round(float(sd.iloc[-1]), 4) if not pd.isna(sd.iloc[-1]) else None,
        "entry_z": entry_z,
        "exit_z": exit_z,
        "lookback": lookback,
        "checks": checks,
    }
