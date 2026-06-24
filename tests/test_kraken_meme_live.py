import os
import unittest
from unittest import mock

import pandas as pd

from tradingagents.execution.kraken_meme_live import (
    KRAKEN_MEME_SLEEVE_IDS,
    build_kraken_meme_intents,
    net_kraken_intents,
)
from tradingagents.execution.polymarket_clob import OrderIntent


class KrakenMemeLiveTests(unittest.TestCase):
    def _prices(self):
        idx = pd.date_range("2025-01-01", periods=60, freq="D")
        doge = pd.Series(0.1 + (idx.dayofyear % 7) * 0.002, index=idx)
        wif = pd.Series(2.0 + (idx.dayofyear % 5) * 0.02, index=idx)
        return doge, wif

    def test_five_sleeve_ids(self):
        self.assertEqual(len(KRAKEN_MEME_SLEEVE_IDS), 5)

    def test_build_pack_has_five_sleeves(self):
        doge, wif = self._prices()
        with mock.patch.dict(os.environ, {"KRAKEN_NEWS_GATE": "0"}, clear=False):
            pack = build_kraken_meme_intents(doge, wif, notional_usd=50)
        self.assertEqual(len(pack["intents_by_sleeve"]), 5)
        self.assertAlmostEqual(pack["notional_per_sleeve_usd"], 10.0)

    def test_net_aggregates_same_market_side(self):
        intents = [
            OrderIntent("DOGE-USD", "spot", "BUY", 6, 0, "a"),
            OrderIntent("DOGE-USD", "spot", "BUY", 7, 0, "b"),
            OrderIntent("WIF-USD", "spot", "SELL", 5, 0, "c"),
        ]
        net = net_kraken_intents(intents)
        self.assertEqual(len(net), 2)
        doge_buy = [i for i in net if i.market_slug == "DOGE-USD"][0]
        self.assertAlmostEqual(doge_buy.size_usd, 13.0)


if __name__ == "__main__":
    unittest.main()
