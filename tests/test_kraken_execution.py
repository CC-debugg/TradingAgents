import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from tradingagents.execution.kraken_spot import (
    PAIR_MAP,
    execute_kraken_intent,
    kraken_health_check,
    live_trading_enabled,
    place_market_order,
    resolve_pair,
)
from tradingagents.execution.polymarket_clob import OrderIntent, execute_intents
from tradingagents.execution.risk_limits import RiskLimits, validate_order_size


class KrakenExecutionTests(unittest.TestCase):
    def test_pair_map(self):
        self.assertEqual(resolve_pair("DOGE-USD"), "DOGEUSD")
        self.assertEqual(resolve_pair("WIF-USD"), "WIFUSD")
        self.assertIn("DOGE-USD", PAIR_MAP)

    def test_live_flag_default_off(self):
        env = os.environ.copy()
        env.pop("KRAKEN_LIVE", None)
        with patch.dict(os.environ, env, clear=True):
            self.assertFalse(live_trading_enabled())

    def test_dry_run_intent(self):
        intent = OrderIntent("DOGE-USD", "spot", "BUY", 10.0, 0.0, "test")
        out = execute_kraken_intent(intent, dry_run=True)
        self.assertEqual(out["status"], "dry_run")
        self.assertEqual(out["venue"], "kraken")

    def test_risk_max_order(self):
        limits = RiskLimits(max_order_usd=50, max_daily_notional_usd=200, min_order_usd=5)
        ok, msg = validate_order_size(100, limits)
        self.assertFalse(ok)
        self.assertIn("max order", msg)

    def test_risk_min_order(self):
        limits = RiskLimits(max_order_usd=50, max_daily_notional_usd=200, min_order_usd=5)
        ok, _ = validate_order_size(10, limits)
        self.assertTrue(ok)

    @patch("tradingagents.execution.kraken_spot.fetch_ticker_price", return_value=0.2)
    @patch("tradingagents.execution.kraken_spot.fetch_balances", return_value={"ZUSD": 1000.0})
    @patch("tradingagents.execution.kraken_spot._pair_spec")
    @patch("tradingagents.execution.kraken_spot._private_request")
    def test_place_market_order_submitted(self, mock_priv, mock_spec, _bal, _px):
        mock_spec.return_value = {"lot_decimals": 8, "ordermin": "50", "costmin": "0.5"}
        mock_priv.return_value = {"txid": ["OABC-123"]}
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["LIVE_DATA_DIR"] = tmp
            out = place_market_order("DOGEUSD", "BUY", 10.0, use_margin=False)
        self.assertEqual(out["status"], "submitted")
        self.assertEqual(out["txids"], ["OABC-123"])
        mock_priv.assert_called_once()
        order = mock_priv.call_args[0][1]
        self.assertNotIn("oflags", order)
        self.assertEqual(order["volume"], "50")

    @patch("tradingagents.execution.kraken_spot.fetch_ticker_price", return_value=0.2)
    @patch("tradingagents.execution.kraken_spot.fetch_balances", return_value={"ZUSD": 1000.0})
    def test_spot_sell_rejected_without_balance(self, _bal, _px):
        out = place_market_order("DOGEUSD", "SELL", 10.0, use_margin=False)
        self.assertEqual(out["status"], "rejected")
        self.assertIn("margin", out["message"].lower())

    def test_execute_intents_routes_kraken(self):
        intents = [
            OrderIntent("DOGE-USD", "spot", "BUY", 10.0, 0.0, "doge"),
            OrderIntent("gta-vi-released-before-june-2026", "Yes", "BUY", 20.0, 0.5, "poly"),
        ]
        rows = execute_intents(intents, dry_run=True)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["venue"], "kraken")
        self.assertEqual(rows[0]["status"], "dry_run")
        self.assertEqual(rows[1]["venue"], "polymarket")

    @patch("tradingagents.execution.kraken_spot._public_request")
    def test_health_check_public(self, mock_pub):
        mock_pub.return_value = {"unixtime": 1}
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KRAKEN_API_KEY", None)
            os.environ.pop("KRAKEN_API_SECRET", None)
        out = kraken_health_check()
        self.assertTrue(out["rest_reachable"])


if __name__ == "__main__":
    unittest.main()
