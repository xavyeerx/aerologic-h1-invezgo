import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import pytz
import numpy as np

from learning.signal_events import SignalEventStore, new_signal_id


class SignalEventStoreTests(unittest.TestCase):
    def test_repeated_ticker_setup_creates_distinct_immutable_histories(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SignalEventStore(Path(temp_dir) / "events.jsonl")
            first, second = new_signal_id(), new_signal_id()
            at = pytz.timezone("Asia/Jakarta").localize(datetime(2026, 7, 17, 9, 5))
            store.append("SIGNAL_CREATED", signal_id=first, ticker="BBCA", occurred_at=at)
            store.append("SIGNAL_CREATED", signal_id=second, ticker="BBCA", occurred_at=at)
            store.append("TP_TOUCHED", signal_id=first, ticker="BBCA", occurred_at=at)
            self.assertNotEqual(first, second)
            self.assertEqual(len(store.load()), 3)
            self.assertEqual(len(store.events_for(first)), 2)
            self.assertEqual(len(store.events_for(second)), 1)

    def test_naive_timestamp_is_stored_as_wib(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SignalEventStore(Path(temp_dir) / "events.jsonl")
            event = store.append("SIGNAL_CREATED", signal_id=new_signal_id(), ticker="BBRI",
                                 occurred_at=datetime(2026, 7, 17, 13, 30))
            self.assertTrue(event["occurred_at"].endswith("+07:00"))

    def test_invalid_json_is_reported_instead_of_silently_skipped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "events.jsonl"
            path.write_text("not-json\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "line 1"):
                SignalEventStore(path).load()

    def test_numpy_values_and_nan_are_json_safe(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SignalEventStore(Path(temp_dir) / "events.jsonl")
            signal_id = new_signal_id()
            store.append(
                "SIGNAL_CREATED", signal_id=signal_id, ticker="TLKM",
                payload={"score": np.int64(42), "flag": np.bool_(True), "line": np.nan},
            )
            payload = store.load()[0]["payload"]
            self.assertEqual(payload["score"], 42)
            self.assertIs(payload["flag"], True)
            self.assertIsNone(payload["line"])


if __name__ == "__main__":
    unittest.main()
