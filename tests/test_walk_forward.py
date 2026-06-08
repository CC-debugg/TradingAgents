import unittest

import numpy as np
import pandas as pd

from tradingagents.quant.polymarket_strategy import StrategyConfig, sharpe_ratio
from tradingagents.quant.walk_forward import (
    WalkForwardConfig,
    generate_walk_forward_windows,
    run_walk_forward,
)


class WalkForwardTests(unittest.TestCase):
    def test_generate_windows(self):
        idx = pd.date_range("2020-01-01", periods=400, freq="D")
        wins = generate_walk_forward_windows(idx, train_days=100, test_days=30, step_days=30)
        self.assertGreater(len(wins), 0)
        tr_s, tr_e, te_s, te_e = wins[0]
        self.assertLess(tr_s, tr_e)
        self.assertLess(te_s, te_e)

    def test_run_walk_forward_synthetic(self):
        rng = np.random.default_rng(42)
        idx = pd.date_range("2021-01-01", periods=500, freq="D")
        price = pd.Series(100 * np.cumprod(1 + rng.normal(0.001, 0.02, len(idx))), index=idx)
        prices = {"DOGE": price, "WIF": price * 0.9}
        cfg = StrategyConfig(meme_long_only=True, portfolio_weight_mode="equal")
        wf = WalkForwardConfig(
            train_days=120,
            test_days=40,
            step_days=40,
            ema_fast_grid=(10, 20),
            ema_slow_grid=(40, 60),
            min_train_bars=60,
        )
        folds, oos = run_walk_forward(prices, cfg, wf)
        self.assertFalse(folds.empty)
        self.assertGreater(len(oos), 0)
        self.assertIn("test_sharpe", folds.columns)
        self.assertIn("ema_fast", folds.columns)


class SharpeTests(unittest.TestCase):
    def test_sharpe_finite(self):
        r = pd.Series(np.random.default_rng(0).normal(0.0005, 0.01, 200))
        sh = sharpe_ratio(r)
        self.assertIsInstance(sh, float)
