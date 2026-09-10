import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from database.state_manager import (
    StateManager,
    _previous_weekday,
    evaluate_alert_frequency,
)


class AlertFrequencyRuleTests(unittest.TestCase):
    def test_third_call_inside_fourteen_calendar_days_is_blocked(self):
        on_date = date(2026, 8, 31)
        allowed, reason = evaluate_alert_frequency(
            ["2026-08-22", "2026-08-27"], on_date
        )
        self.assertFalse(allowed)
        self.assertIn("2x dalam 14 hari", reason)

    def test_call_before_fourteen_day_window_does_not_count(self):
        allowed, _ = evaluate_alert_frequency(
            ["2026-08-17", "2026-08-27"], date(2026, 8, 31)
        )
        self.assertTrue(allowed)

    def test_third_consecutive_trading_session_is_blocked_by_two_call_cap(self):
        monday = date(2026, 8, 31)
        previous = _previous_weekday(monday)
        two_sessions_ago = _previous_weekday(previous)
        allowed, reason = evaluate_alert_frequency(
            [two_sessions_ago.isoformat(), previous.isoformat()], monday
        )
        self.assertFalse(allowed)
        self.assertIn("2x dalam 14 hari", reason)

    def test_second_consecutive_trading_session_is_allowed(self):
        on_date = date(2026, 9, 1)
        allowed, _ = evaluate_alert_frequency(["2026-08-31"], on_date)
        self.assertTrue(allowed)


class AlertClaimIntegrationTests(unittest.TestCase):
    def test_same_ticker_is_claimed_only_once_across_alert_types(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = StateManager(str(Path(temp_dir) / "stock_states.json"))
            self.assertTrue(manager.try_claim_daily_alert("strong_buy", "PACK.JK"))
            self.assertFalse(manager.try_claim_daily_alert("early_entry", "pack"))
            self.assertEqual(manager.daily_alerts["history"]["PACK"], [date.today().isoformat()])

    def test_bullish_break_is_blocked_after_another_alert(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = StateManager(str(Path(temp_dir) / "stock_states.json"))
            self.assertTrue(manager.try_claim_daily_alert("strong_buy", "PACK.JK"))
            self.assertFalse(manager.try_claim_daily_alert("bullish_break", "PACK.JK"))

    def test_early_entry_blocks_all_later_categories(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = StateManager(str(Path(temp_dir) / "stock_states.json"))
            self.assertTrue(manager.try_claim_daily_alert("early_entry", "PACK.JK"))
            self.assertFalse(manager.try_claim_daily_alert("strong_buy", "pack"))
            self.assertFalse(manager.try_claim_daily_alert("bullish_break", "PACK"))

    def test_legacy_event_log_bootstraps_history(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            event = {
                "event_type": "SIGNAL_CREATED",
                "ticker": "PACK.JK",
                "occurred_at": datetime.now().isoformat(),
            }
            (root / "signal_events.jsonl").write_text(
                json.dumps(event) + "\n", encoding="utf-8"
            )
            manager = StateManager(str(root / "stock_states.json"))
            self.assertEqual(manager.daily_alerts["history"]["PACK"], [date.today().isoformat()])
            self.assertFalse(manager.try_claim_daily_alert("strong_buy", "PACK"))


if __name__ == "__main__":
    unittest.main()
