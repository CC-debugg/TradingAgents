"""Tests for whale flow signal + metrics."""

import pandas as pd

from tradingagents.quant.whale_strategy import (
    WhaleStrategyConfig,
    daily_whale_flow,
    strategy_metrics,
    whale_flow_signal,
)


def test_daily_flow_and_signal():
    trades = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2025-01-01", "2025-01-01", "2025-01-02"], utc=True),
            "side": ["BUY", "SELL", "BUY"],
            "cash_usd": [10_000.0, 2000.0, 8000.0],
            "outcome": ["Yes", "Yes", "No"],
        }
    )
    flow = daily_whale_flow(trades)
    assert len(flow) == 2
    cfg = WhaleStrategyConfig(flow_window=2, min_flow_usd=5000.0)
    sig = whale_flow_signal(flow, cfg)
    assert sig.iloc[-1] in (-1.0, 0.0, 1.0)


def test_strategy_metrics():
    r = pd.Series([0.01, -0.005, 0.02, 0.0], index=pd.date_range("2025-01-01", periods=4, freq="D"))
    m = strategy_metrics(r)
    assert "win_rate" in m
    assert m["n_days"] == 4
