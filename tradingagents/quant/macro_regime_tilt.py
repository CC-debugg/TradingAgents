"""Macro regime classification + tilted portfolio returns (Ang-inspired)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .polymarket_strategy import StrategyConfig, load_universe_prices, run_portfolio_backtest


def classify_regime(macro: pd.DataFrame) -> pd.Series:
    """
    Daily regime from macro factor returns.
    risk_on | risk_off | inflation | neutral
    """
    if macro.empty:
        return pd.Series(dtype=str)
    m = macro.copy()
    idx = m.index
    regime = pd.Series("neutral", index=idx, dtype=object)
    if "BARRA_EQUITY_MARKET" in m.columns or "ECON_GROWTH" in m.columns:
        eq = m.get("BARRA_EQUITY_MARKET", m.get("ECON_GROWTH"))
        tlt = m.get("BARRA_RATES", m.get("POLICY_RATES"))
        infl = m.get("BARRA_INFLATION", m.get("INFLATION"))
        roll_eq = eq.rolling(20).mean()
        roll_tlt = tlt.rolling(20).mean() if tlt is not None else pd.Series(0, index=idx)
        roll_infl = infl.rolling(20).mean() if infl is not None else pd.Series(0, index=idx)
        regime[(roll_eq > 0) & (roll_tlt <= 0)] = "risk_on"
        regime[(roll_eq < 0) & (roll_tlt > 0)] = "risk_off"
        regime[roll_infl > roll_infl.quantile(0.7)] = "inflation"
    return regime


def regime_tilted_portfolio_returns(
    cfg: StrategyConfig,
    regime: pd.Series,
    tilt: dict[str, float] | None = None,
) -> tuple[pd.Series, pd.Series]:
    """
    Scale base portfolio returns by regime multiplier.
    tilt e.g. risk_on=1.2, risk_off=0.5, inflation=0.8, neutral=1.0
    """
    tilt = tilt or {
        "risk_on": 1.15,
        "risk_off": 0.55,
        "inflation": 0.85,
        "neutral": 1.0,
    }
    prices = load_universe_prices(cfg)
    base, _, _ = run_portfolio_backtest(prices, cfg)
    mult = regime.reindex(base.index).map(lambda r: tilt.get(str(r), 1.0)).fillna(1.0)
    return base * mult, regime.reindex(base.index).ffill()
