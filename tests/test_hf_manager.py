"""Tests for HF manager equal-weight and regime-dynamic books."""

from __future__ import annotations

import numpy as np
import pandas as pd

from tradingagents.quant.hf_manager import (
    BASE_SLEEVE_IDS,
    equal_weight_allocation,
    equal_weight_returns,
    hf_manager_returns,
)


def _fake_returns(n: int = 100, seed: int = 0) -> dict[str, pd.Series]:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2024-01-01", periods=n)
    out = {}
    for i, sid in enumerate(BASE_SLEEVE_IDS):
        out[sid] = pd.Series(rng.normal(0.0005 + i * 0.0001, 0.01, n), index=idx)
    return out


def test_equal_weight_sums_to_one():
    rm = _fake_returns()
    w = equal_weight_allocation(rm)
    assert len(w) == len(BASE_SLEEVE_IDS)
    assert abs(sum(w.values()) - 1.0) < 1e-6
    target = 1 / len(BASE_SLEEVE_IDS)
    for v in w.values():
        assert abs(v - target) < 5e-4


def test_equal_weight_adjusts_when_sleeve_missing():
    rm = _fake_returns()
    del rm["vol_risk_parity"]
    w = equal_weight_allocation(rm)
    assert len(w) == len(BASE_SLEEVE_IDS) - 1
    assert abs(sum(w.values()) - 1.0) < 1e-6


def test_equal_weight_returns_non_empty():
    rm = _fake_returns()
    r = equal_weight_returns(rm)
    assert len(r.dropna()) > 0


def test_hf_manager_weights_sum_to_one():
    rm = _fake_returns()
    _, w = hf_manager_returns(rm, merged_tilt={sid: 1.0 for sid in BASE_SLEEVE_IDS})
    assert w
    assert abs(sum(w.values()) - 1.0) < 1e-4
