import unittest
from datetime import datetime

import pytz

from core.data_provider import _rows_to_h1_ohlc_df
from scheduler import scan_slots_for_day


WIB = pytz.timezone("Asia/Jakarta")


class H1MarketSessionTests(unittest.TestCase):
    def test_incomplete_bar_is_excluded(self):
        rows = [
            {"date": "2026-09-07T09:00:00Z", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 10},
            {"date": "2026-09-07T10:00:00Z", "open": 2, "high": 3, "low": 2, "close": 3, "volume": 20},
        ]
        frame = _rows_to_h1_ohlc_df(
            rows, now=WIB.localize(datetime(2026, 9, 7, 10, 30))
        )
        self.assertEqual(len(frame), 1)
        self.assertEqual(frame.index[0].hour, 9)

    def test_scheduler_uses_exchange_bucket_closes(self):
        monday = WIB.localize(datetime(2026, 9, 7, 8, 0))
        self.assertEqual(
            [slot.strftime("%H:%M") for slot in scan_slots_for_day(monday)],
            ["09:01", "10:01", "11:01", "12:01", "14:01", "15:01", "15:51", "16:16"],
        )


if __name__ == "__main__":
    unittest.main()
