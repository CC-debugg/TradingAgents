"""Tests for the CSV-backed RL research sleeve loader."""

from __future__ import annotations

import pandas as pd

import tradingagents.quant.rl_sleeve as rl_sleeve
from tradingagents.quant.hf_manager import BASE_SLEEVE_IDS, equal_weight_allocation


def test_missing_csv_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(rl_sleeve, "RL_RETURNS_CSV", tmp_path / "nope.csv")
    assert rl_sleeve.load_rl_sleeve_returns().empty


def test_loads_and_filters_csv(tmp_path, monkeypatch):
    csv = tmp_path / "rl.csv"
    pd.DataFrame(
        {"date": ["2026-01-01", "2026-01-02", "2026-01-03"], "rl_tensortrade": [0.01, -0.02, 0.005]}
    ).to_csv(csv, index=False)
    monkeypatch.setattr(rl_sleeve, "RL_RETURNS_CSV", csv)
    s = rl_sleeve.load_rl_sleeve_returns(start="2026-01-02")
    assert len(s) == 2
    assert s.iloc[0] == -0.02


def test_rl_sleeve_excluded_from_equal_index():
    assert "rl_tensortrade" not in BASE_SLEEVE_IDS
    idx = pd.bdate_range("2026-01-01", periods=50)
    rm = {sid: pd.Series(0.001, index=idx) for sid in BASE_SLEEVE_IDS}
    rm["rl_tensortrade"] = pd.Series(0.01, index=idx)
    w = equal_weight_allocation(rm)
    assert "rl_tensortrade" not in w
    assert abs(sum(w.values()) - 1.0) < 1e-6
