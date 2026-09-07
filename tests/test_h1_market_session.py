import unittest
from datetime import datetime

import pytz

from core.data_provider import _rows_to_h1_ohlc_df
from scheduler import scan_slots_for_day


WIB = pytz.timezone("Asia/Jakarta")


class H1MarketSessionTests(unittest.TestCase):
    def test_incomplete_bar_is_included_for_live_h1_signals(self):
        rows = [
            {"date": "2026-09-07T09:00:00Z", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 10},
            {"date": "2026-09-07T10:00:00Z", "open": 2, "high": 3, "low": 2, "close": 3, "volume": 20},
        ]
        frame = _rows_to_h1_ohlc_df(
            rows, now=WIB.localize(datetime(2026, 9, 7, 10, 30))
        )
        self.assertEqual(len(frame), 2)
        self.assertEqual(frame.index[-1].hour, 10)
        self.assertFalse(frame.attrs["latest_bar_closed"])

    def test_closed_only_mode_remains_available_for_research(self):
        rows = [
            {"date": "2026-09-07T09:00:00Z", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 10},
            {"date": "2026-09-07T10:00:00Z", "open": 2, "high": 3, "low": 2, "close": 3, "volume": 20},
        ]
        frame = _rows_to_h1_ohlc_df(
            rows, now=WIB.localize(datetime(2026, 9, 7, 10, 30)), closed_only=True
        )
        self.assertEqual(len(frame), 1)
        self.assertTrue(frame.attrs["latest_bar_closed"])

    def test_scheduler_runs_every_five_minutes_and_includes_bucket_closes(self):
        monday = WIB.localize(datetime(2026, 9, 7, 8, 0))
        slots = scan_slots_for_day(monday)
        labels = [slot.strftime("%H:%M") for slot in slots]
        self.assertEqual(labels[0], "09:01")
        self.assertEqual((slots[1] - slots[0]).total_seconds(), 300)
        self.assertIn("10:01", labels)
        self.assertIn("12:01", labels)
        self.assertIn("16:16", labels)


if __name__ == "__main__":
    unittest.main()
