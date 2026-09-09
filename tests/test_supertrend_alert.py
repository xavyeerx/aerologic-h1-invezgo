import unittest
from types import SimpleNamespace

import pandas as pd

from core.indicators import calculate_supertrend

from core.scanner import (
    _idx_tick_size,
    _next_idx_price_above,
    _is_bullish_supertrend_break,
    _is_live_bullish_supertrend_break,
    _has_bullish_supertrend_confirmation,
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


class SupertrendConfirmationTests(unittest.TestCase):
    def test_latest_two_bars_confirm_bullish_supertrend(self):
        frame = pd.DataFrame(
            {
                "direction": [-1, 1, 1],
            }
        )
        self.assertTrue(_has_bullish_supertrend_confirmation(frame))

    def test_one_bullish_bar_is_not_enough(self):
        frame = pd.DataFrame(
            {
                "direction": [-1, -1, 1],
            }
        )
        self.assertFalse(_has_bullish_supertrend_confirmation(frame))

class StrongBuyRuleTests(unittest.TestCase):
    def test_bull_market_ignores_stoch_filter(self):
        self.assertTrue(_is_strong_buy(True, 12.0, "BULL", 90.0, 10.0))

    def test_zero_and_negative_change_are_rejected(self):
        self.assertFalse(_is_strong_buy(True, 0.0, "BULL", 20.0, 10.0))
        self.assertFalse(_is_strong_buy(True, -0.01, "BULL", 20.0, 10.0))

    def test_more_than_twelve_percent_is_rejected(self):
        self.assertFalse(_is_strong_buy(True, 12.01, "BULL", 20.0, 10.0))

    def test_sideways_and_bear_require_stoch_below_sixty_and_k_above_d(self):
        for regime in ("SIDEWAYS", "BEAR"):
            with self.subTest(regime=regime):
                self.assertTrue(_is_strong_buy(True, 5.0, regime, 59.0, 50.0))
                self.assertFalse(_is_strong_buy(True, 5.0, regime, 60.0, 50.0))
                self.assertFalse(_is_strong_buy(True, 5.0, regime, 50.0, 50.0))

    def test_two_bar_confirmation_is_mandatory(self):
        self.assertFalse(_is_strong_buy(False, 5.0, "BULL", 20.0, 10.0))

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
