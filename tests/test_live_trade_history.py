"""Tests for live trade history logging."""

from __future__ import annotations

import pandas as pd

from tradingagents.execution.polymarket_clob import OrderIntent
from tradingagents.quant import live_trade_history as lth


def test_whale_trade_extraction():
    idx = pd.bdate_range("2026-01-01", periods=5)
    sig = pd.Series([0.0, 1.0, 1.0, -1.0, 0.0], index=idx)
    price = pd.Series([0.5, 0.51, 0.52, 0.48, 0.49], index=idx)
    rows = lth.trades_from_signal_series("whale_flow", "POLY_GTA", sig, price=price)
    actions = [r["action"] for r in rows]
    assert "OPEN" in actions
    assert "FLIP" in actions or "CLOSE" in actions


def test_pairs_trade_extraction():
    idx = pd.bdate_range("2026-01-01", periods=4)
    sig = pd.Series([0.0, 1.0, 1.0, 0.0], index=idx)
    rows = lth.trades_from_signal_series("pairs_stat_arb", "DOGE/WIF", sig)
    assert len(rows) >= 2
    assert any(r["asset"] == "DOGE" for r in rows)


def test_record_live_refresh_persists(tmp_path, monkeypatch):
    path = tmp_path / "trade_history.csv"
    monkeypatch.setattr(lth, "_history_path", lambda: path)
    intents = [
        OrderIntent("gta-vi-released-before-june-2026", "Yes", "BUY", 50.0, 0.55, "poly_signal_long"),
    ]
    results = [{"status": "dry_run", "message": "DRY_RUN"}]
    gate = {"score": 0.1, "label": "ok"}
    signals = {"POLY_GTA": 1.0, "DOGE": 0.0, "WIF": 0.0}
    out1 = lth.record_live_refresh("2026-06-11 12:00 EDT", intents, results, gate, signals)
    out2 = lth.record_live_refresh("2026-06-11 12:01 EDT", intents, results, gate, signals)
    assert out1["n_saved"] == 1
    assert out2["n_saved"] == 1
    assert len(out1["current_orders"]) == 1
    assert out1["current_orders"][0]["action"].startswith("BUY")
