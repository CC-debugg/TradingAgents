"""Tests for news gate + whale v2 conviction signal."""

import pandas as pd

from tradingagents.quant.news_gate import apply_news_gate, score_macro_news
from tradingagents.quant.whale_strategy import (
    WhaleStrategyConfig,
    daily_whale_flow,
    whale_flow_signal,
    whale_flow_signal_v2,
)


def test_news_gate_blocks_risk_off():
    snap = {
        "ecb_headlines": pd.DataFrame(
            {"title": ["ECB warns on inflation and tightening amid crisis stress"]}
        )
    }
    gate = score_macro_news(snap)
    assert gate["score"] < 0
    sig, reason = apply_news_gate(1.0, gate)
    assert sig == 0.0
    assert reason == "blocked_by_news_gate"


def test_whale_v2_fewer_trades_than_legacy():
    idx = pd.date_range("2025-01-01", periods=30, freq="D")
    flow = pd.DataFrame(
        {
            "flow_net_usd": [8000.0 if i % 7 == 0 else 500.0 for i in range(30)],
            "n_trades": [5 if i % 7 == 0 else 1 for i in range(30)],
        },
        index=idx,
    )
    prob = pd.Series([0.4 + 0.01 * (i % 5) for i in range(30)], index=idx)
    legacy = whale_flow_signal(flow, WhaleStrategyConfig(flow_window=5, min_flow_usd=5000, min_whale_trades=1))
    v2 = whale_flow_signal_v2(flow, prob, WhaleStrategyConfig())
    assert (v2.abs() > 0).sum() <= (legacy.abs() > 0).sum()
