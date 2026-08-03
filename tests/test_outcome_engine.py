import unittest

import pandas as pd

from learning.outcome_engine import OutcomePolicy, evaluate_signal_path


ENTRY_AT = pd.Timestamp("2026-07-13 09:00")


def frame(rows):
    return pd.DataFrame(rows).set_index("timestamp")


class OutcomeEngineTests(unittest.TestCase):
    def test_tp_first(self):
        result = evaluate_signal_path(frame([
            {"timestamp": ENTRY_AT, "high": 200, "low": 1, "close": 100},
            {"timestamp": pd.Timestamp("2026-07-13 10:00"), "high": 101.2, "low": 99, "close": 101},
        ]), entry_price=100, entry_at=ENTRY_AT)
        self.assertEqual(result["first_hit"], "TP_FIRST")
        self.assertIsNotNone(result["tp_touched"]["1.0"])

    def test_sl_first(self):
        result = evaluate_signal_path(frame([
            {"timestamp": pd.Timestamp("2026-07-13 10:00"), "high": 100.5, "low": 96.5, "close": 97},
        ]), entry_price=100, entry_at=ENTRY_AT)
        self.assertEqual(result["first_hit"], "SL_FIRST")

    def test_same_bar_is_ambiguous(self):
        result = evaluate_signal_path(frame([
            {"timestamp": pd.Timestamp("2026-07-13 10:00"), "high": 102, "low": 96, "close": 101},
        ]), entry_price=100, entry_at=ENTRY_AT)
        self.assertEqual(result["first_hit"], "AMBIGUOUS")
        self.assertEqual(result["barrier_order_quality"], "FINEST_BAR_AMBIGUOUS")

    def test_no_barrier_expires_and_reports_mfe_mae(self):
        result = evaluate_signal_path(frame([
            {"timestamp": pd.Timestamp("2026-07-13 10:00"), "high": 100.8, "low": 98, "close": 100.2},
        ]), entry_price=100, entry_at=ENTRY_AT)
        self.assertEqual(result["first_hit"], "EXPIRED")
        self.assertAlmostEqual(result["mfe_pct"], 0.8)
        self.assertAlmostEqual(result["mae_pct"], -2.0)

    def test_sixth_trading_day_is_excluded(self):
        dates = pd.bdate_range("2026-07-13", periods=6)
        rows = [
            {"timestamp": day + pd.Timedelta(hours=10), "high": 100.5, "low": 99, "close": 100}
            for day in dates
        ]
        rows[-1]["high"] = 105
        result = evaluate_signal_path(frame(rows), entry_price=100,
                                      entry_at=pd.Timestamp("2026-07-13 09:00"))
        self.assertEqual(result["trading_days_observed"], 5)
        self.assertIsNone(result["tp_touched"]["1.0"])

    def test_invalid_policy_is_rejected(self):
        with self.assertRaises(ValueError):
            OutcomePolicy(primary_tp_percentage=1.5)


if __name__ == "__main__":
    unittest.main()
