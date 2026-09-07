import unittest
from types import SimpleNamespace

import pandas as pd

from core.indicators import calculate_supertrend

from core.scanner import (
    _idx_tick_size,
    _next_idx_price_above,
    _is_bullish_supertrend_break,
    _is_live_bullish_supertrend_break,
    _is_bullish_supertrend_bounce,
    _is_strong_buy,
    filter_signals,
)


class SupertrendBreakTests(unittest.TestCase):
    def test_tradingview_initializes_at_first_atr_bar_on_upper_band(self):
        frame = pd.DataFrame({
            "high": [11, 12, 13, 14],
            "low": [9, 10, 11, 12],
            "close": [10, 11, 12, 13],
        })
        calculate_supertrend(frame, period=3, multiplier=2)
        self.assertTrue(pd.isna(frame["supertrend"].iloc[1]))
        self.assertEqual(frame["direction"].iloc[2], -1)
        self.assertEqual(frame["supertrend"].iloc[2], 16.0)

    def test_idx_tick_ladder(self):
        self.assertEqual(_idx_tick_size(199), 1.0)
        self.assertEqual(_idx_tick_size(200), 2.0)
        self.assertEqual(_idx_tick_size(500), 5.0)
        self.assertEqual(_idx_tick_size(2_000), 10.0)
        self.assertEqual(_idx_tick_size(5_000), 25.0)

    def test_fractional_indicator_line_uses_next_valid_idx_price(self):
        self.assertEqual(_next_idx_price_above(86.2468), 87.0)
        self.assertEqual(_next_idx_price_above(178.0605), 179.0)
        self.assertEqual(_next_idx_price_above(747.1542), 750.0)

    def test_requires_one_tick_above_supertrend_line(self):
        frame = pd.DataFrame(
            {
                "close": [490.0, 500.0],
                "supertrend": [500.0, 480.0],
                "st_upper_band": [500.0, 500.0],
            }
        )
        self.assertFalse(_is_bullish_supertrend_break(frame, 504.0))
        self.assertTrue(_is_bullish_supertrend_break(frame, 505.0))

    def test_does_not_repeat_after_price_was_already_above_line(self):
        frame = pd.DataFrame(
            {
                "close": [510.0, 515.0],
                "supertrend": [500.0, 500.0],
                "st_upper_band": [500.0, 500.0],
            }
        )
        self.assertFalse(_is_bullish_supertrend_break(frame, 515.0))

    def test_live_break_requires_last_regular_h1_bar_to_be_bearish(self):
        mncn = pd.DataFrame({
            "close": [202.0], "direction": [-1],
            "supertrend": [204.0], "st_upper_band": [204.0],
        })
        rsch = pd.DataFrame({
            "close": [398.0], "direction": [1],
            "supertrend": [365.0], "st_upper_band": [390.0],
        })
        self.assertTrue(_is_live_bullish_supertrend_break(mncn, 208.0))
        self.assertFalse(_is_live_bullish_supertrend_break(rsch, 428.0))

    def test_bullish_break_is_not_blocked_by_other_signal_liquidity_gate(self):
        result = SimpleNamespace(
            avg_turnover_5d=0.0,
            is_bullish_break=True,
            is_strong_buy=False,
            is_early_entry=False,
            is_reversal_watch=False,
        )
        self.assertEqual(filter_signals({"TEST": result})["bullish_break"], [result])


class SupertrendBounceTests(unittest.TestCase):
    def test_one_tick_reclaim_from_bullish_line_is_strong_buy_input(self):
        frame = pd.DataFrame(
            {
                "direction": [1, 1],
                "low": [152.0, 150.0],
                "supertrend": [149.0, 150.0],
                "st_lower_band": [149.0, 150.0],
            }
        )
        self.assertTrue(_is_bullish_supertrend_bounce(frame, 151.0))
        self.assertTrue(_is_strong_buy(False, True, 5.0))

    def test_price_on_line_has_not_reclaimed_one_tick(self):
        frame = pd.DataFrame(
            {
                "direction": [1, 1],
                "low": [152.0, 150.0],
                "supertrend": [149.0, 150.0],
                "st_lower_band": [149.0, 150.0],
            }
        )
        self.assertFalse(_is_bullish_supertrend_bounce(frame, 150.0))

    def test_no_bounce_when_price_never_tested_the_line(self):
        frame = pd.DataFrame(
            {
                "direction": [1, 1],
                "low": [160.0, 155.0],
                "supertrend": [149.0, 150.0],
                "st_lower_band": [149.0, 150.0],
            }
        )
        self.assertFalse(_is_bullish_supertrend_bounce(frame, 160.0))


class StrongBuyCapTests(unittest.TestCase):
    def test_ten_percent_is_allowed(self):
        self.assertTrue(_is_strong_buy(True, False, 10.0))

    def test_more_than_ten_percent_is_rejected(self):
        self.assertFalse(_is_strong_buy(True, False, 10.01))

    def test_bounce_above_ten_percent_is_also_rejected(self):
        self.assertFalse(_is_strong_buy(False, True, 10.01))

    def test_reversal_watch_alert_is_disabled(self):
        result = SimpleNamespace(
            avg_turnover_5d=10_000_000_000,
            is_bullish_break=False,
            is_strong_buy=False,
            is_early_entry=False,
            is_reversal_watch=True,
        )
        self.assertEqual(filter_signals({"TEST": result})["reversal_watch"], [])


if __name__ == "__main__":
    unittest.main()
