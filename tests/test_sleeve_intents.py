import os
import unittest
from unittest import mock

import pandas as pd

from tradingagents.execution.sleeve_intents import build_sleeve_intent_map, merge_execution_intents
from tradingagents.execution.polymarket_clob import OrderIntent
from tradingagents.quant.alpha_sleeve_signals import (
    latest_beta_neutral_signal,
    latest_short_term_reversal_signal,
)


class SleeveIntentTests(unittest.TestCase):
    def _prices(self):
        idx = pd.date_range("2025-01-01", periods=40, freq="D")
        doge = pd.Series(0.1 + (idx.dayofyear % 7) * 0.001, index=idx)
        wif = pd.Series(2.0 + (idx.dayofyear % 5) * 0.01, index=idx)
        return doge, wif

    def test_beta_neutral_includes_hedge(self):
        doge, wif = self._prices()
        sig = latest_beta_neutral_signal(doge, wif, lookback=15)
        self.assertIn("beta", sig)
        self.assertIn("wif_hedge_ratio", sig)

    def test_build_sleeve_intent_map_has_eight_keys(self):
        doge, wif = self._prices()
        poly = pd.Series(0.4, index=doge.index)
        binance = pd.Series(0.08, index=doge.index)
        flow = pd.DataFrame({"flow_net_usd": [0] * len(doge), "volume_usd": [0] * len(doge)}, index=doge.index)
        pack = build_sleeve_intent_map(flow, poly, doge, wif, binance=binance, notional_usd=80)
        self.assertEqual(len(pack["intents_by_sleeve"]), 8)
        self.assertAlmostEqual(pack["notional_per_sleeve_usd"], 10.0)

    def test_merge_alpha_off_by_default(self):
        prod = [OrderIntent("DOGE-USD", "spot", "BUY", 10, 0, "prod")]
        alpha = [OrderIntent("WIF-USD", "spot", "SELL", 5, 0, "alpha")]
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LIVE_ALPHA_SLEEVES", None)
        merged = merge_execution_intents(prod, alpha)
        self.assertEqual(len(merged), 1)

    def test_reversal_signal_bounded(self):
        doge, wif = self._prices()
        sig = latest_short_term_reversal_signal(doge, wif)
        self.assertIn("basket_5d_pct", sig)


if __name__ == "__main__":
    unittest.main()
