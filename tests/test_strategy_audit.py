"""Tests for unified strategy audit JSON."""

from __future__ import annotations

import numpy as np
import pandas as pd

from tradingagents.quant.hf_manager import BASE_SLEEVE_IDS
from tradingagents.quant.strategy_audit import audit_single, build_strategy_audit


def _returns_map(n: int = 120) -> dict[str, pd.Series]:
    rng = np.random.default_rng(42)
    idx = pd.bdate_range("2024-01-01", periods=n)
    rm = {}
    for i, sid in enumerate(BASE_SLEEVE_IDS):
        rm[sid] = pd.Series(rng.normal(0.0003, 0.012, n), index=idx)
    # Highly correlated pair with same logic_type would trigger overlap — use distinct series
    rm["multi_strategy_index"] = pd.Series(rng.normal(0.0004, 0.011, n), index=idx)
    return rm


def test_audit_single_has_required_fields():
    rm = _returns_map()
    out = audit_single("whale_flow", rm["whale_flow"], rm)
    assert out["id"] == "whale_flow"
    m = out["metrics"]
    for key in ("sharpe", "cagr", "total_return", "vol_ann", "max_dd", "win_rate", "n_trades", "turnover", "tc_drag_bps"):
        assert key in m
    assert "rolling_60d" in out
    assert "walk_forward" in out


def test_build_strategy_audit_structure():
    rm = _returns_map()
    audit = build_strategy_audit(rm)
    assert "entries" in audit
    assert "summary" in audit
    assert "correlation" in audit
    assert "overlap_warnings" in audit
    assert "whale_flow" in audit["entries"]
    assert len(audit["correlation"]) >= 2


def test_overlap_warning_same_logic_type():
    idx = pd.bdate_range("2024-01-01", periods=80)
    base = pd.Series(np.linspace(0.001, 0.002, 80), index=idx)
    rm = {sid: base + np.random.default_rng(i).normal(0, 0.0001, 80) for i, sid in enumerate(BASE_SLEEVE_IDS)}
    # Force ts_momentum_meme and vol_risk_parity to be identical (both beta_neutral family in logic - actually different logic types)
    rm["ts_momentum_meme"] = base.copy()
    rm["vol_risk_parity"] = base.copy()
    audit = build_strategy_audit(rm)
    # Different logic_type — should NOT warn despite high corr
    warns = audit["overlap_warnings"]
    pair_ids = {(w["a"], w["b"]) for w in warns}
    assert ("ts_momentum_meme", "vol_risk_parity") not in pair_ids
    assert ("vol_risk_parity", "ts_momentum_meme") not in pair_ids
