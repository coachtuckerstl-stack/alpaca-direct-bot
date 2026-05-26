import unittest
from unittest.mock import patch
import pandas as pd
import bot


class ScannerSafetyTests(unittest.TestCase):
    def setUp(self):
        self.original_cap = bot.MAX_DOLLARS_PER_TRADE
        bot.MAX_DOLLARS_PER_TRADE = 20.0

    def tearDown(self):
        bot.MAX_DOLLARS_PER_TRADE = self.original_cap

    def test_protected_bracket_blocks_fractional_only_budget(self):
        signal = {"symbol": "UMC", "entry": 25.0, "risk_per_share": 1.5}
        with patch.object(bot, "get_account_equity", return_value=100000.0), patch.object(
            bot, "get_open_positions_count", return_value=0
        ):
            approved, reason, qty = bot.risk_check(signal)
        self.assertFalse(approved)
        self.assertEqual(qty, 0)
        self.assertIn("whole share", reason)

    def test_protected_bracket_uses_integer_quantity_when_budget_allows(self):
        signal = {"symbol": "TEST", "entry": 9.0, "risk_per_share": 1.5}
        with patch.object(bot, "get_account_equity", return_value=100000.0), patch.object(
            bot, "get_open_positions_count", return_value=0
        ):
            approved, _, qty = bot.risk_check(signal)
        self.assertTrue(approved)
        self.assertEqual(qty, 2)
        self.assertIsInstance(qty, int)

    def test_watchlist_records_batched_scan_summary(self):
        idx = pd.date_range("2026-01-01", periods=30, freq="D")
        frame = pd.DataFrame({
            "open": [10.0] * 30,
            "high": [11.0] * 30,
            "low": [9.0] * 30,
            "close": [10.0] * 29 + [10.5],
            "volume": [500000] * 30,
        }, index=idx)
        events = []
        with patch.object(bot, "get_tradable_symbols", return_value=["AAA"]), patch.object(
            bot, "get_daily_bars_batch", return_value={"AAA": frame}
        ), patch.object(bot, "log_db_event", side_effect=lambda **kw: events.append(kw)), patch.object(
            bot, "log_event"
        ):
            selected = bot.build_auto_watchlist()
        self.assertEqual(selected, ["AAA"])
        self.assertTrue(any(e.get("event_type") == "WATCHLIST_COMPLETE" for e in events))


if __name__ == "__main__":
    unittest.main()
