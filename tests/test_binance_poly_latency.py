import unittest

import numpy as np
import pandas as pd

from tradingagents.quant.alpha_sleeve_signals import latest_binance_poly_latency_signal
from tradingagents.quant.alpha_sleeves import binance_poly_latency_returns


class BinancePolyLatencyTests(unittest.TestCase):
    def test_returns_non_empty(self):
        idx = pd.date_range("2025-01-01", periods=60, freq="D")
        rng = np.random.default_rng(42)
        binance = pd.Series(0.1 * (1 + rng.normal(0, 0.02, len(idx))).cumprod(), index=idx)
        poly = pd.Series(0.4 + rng.normal(0, 0.01, len(idx)).cumsum() * 0.01, index=idx).clip(0.05, 0.95)
        r = binance_poly_latency_returns(binance, poly)
        self.assertGreater(len(r), 0)

    def test_signal_on_large_binance_move(self):
        idx = pd.date_range("2025-01-01", periods=30, freq="D")
        binance = pd.Series(np.linspace(0.1, 0.15, len(idx)), index=idx)
        poly = pd.Series(0.4, index=idx)
        sig = latest_binance_poly_latency_signal(binance, poly, lag=1, move_thresh=0.01)
        self.assertIn("binance_lag_1d_pct", sig)
        self.assertIn("poly", sig)


if __name__ == "__main__":
    unittest.main()
