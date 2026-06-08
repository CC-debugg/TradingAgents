"""Transaction cost conventions for production backtests."""

from __future__ import annotations

import pandas as pd

from tradingagents.quant.trading_costs import (
    FEE_BPS_PER_LEG,
    ROUND_TRIP_BPS,
    cost_on_signal_change,
    round_trip_cost_pairs_spread,
)


def test_fee_constants():
    assert FEE_BPS_PER_LEG == 5.0
    assert ROUND_TRIP_BPS == 10.0


def test_single_leg_round_trip():
    assert cost_on_signal_change(True, legs=1) == 5e-4
    assert cost_on_signal_change(True, legs=2) == 1e-3


def test_pairs_spread_two_legs_on_flip():
    sig = pd.Series([0.0, 1.0, 1.0, 0.0], index=pd.date_range("2025-01-01", periods=4, freq="D"))
    tc = round_trip_cost_pairs_spread(sig)
    assert tc.iloc[1] == 10e-4
    assert tc.iloc[3] == 10e-4
    assert tc.iloc[2] == 0.0
