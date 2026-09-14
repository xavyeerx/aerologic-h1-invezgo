import unittest

import numpy as np
import pandas as pd

from core.bar_contract import INVEZGO_DAILY_PATTERN_CONTRACT, attach_bar_contract
from core.chart_patterns import (
    _converging_lines,
    _detect_base,
    _detect_pennant,
    detect_bullish_chart_patterns,
    pattern_metrics,
)


def _frame(close, high=None, low=None, volume=None):
    close = np.asarray(close, dtype=float)
    high = np.asarray(high if high is not None else close + 1.0, dtype=float)
    low = np.asarray(low if low is not None else close - 1.0, dtype=float)
    volume = np.asarray(volume if volume is not None else np.full(len(close), 1_000_000), dtype=float)
    frame = pd.DataFrame(
        {
            "open": close - 0.2,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=pd.date_range("2026-05-01", periods=len(close), freq="B"),
    )
    return attach_bar_contract(frame, INVEZGO_DAILY_PATTERN_CONTRACT)


class ChartPatternTests(unittest.TestCase):
    def test_base_requires_repeated_touches_and_fresh_close_breakout(self):
        prefix = np.linspace(95, 100, 47)
        base = np.tile([99, 104, 100, 95], 6)[:22]
        close = np.concatenate([prefix, base, [106]])
        high = close + 1
        low = close - 1
        # Stable horizontal boundaries with repeated touches.
        high[-23:-1] = np.tile([100, 105, 101, 96], 6)[:22]
        low[-23:-1] = np.tile([98, 103, 99, 95], 6)[:22]
        volume = np.full(len(close), 1_000_000.0)
        volume[-1] = 2_000_000.0
        frame = _frame(close, high, low, volume)

        match = _detect_base(frame, atr_value=4.0)

        self.assertIsNotNone(match)
        self.assertEqual(match.key, "break_base")

    def test_symmetrical_triangle_uses_opposing_converging_pivot_lines(self):
        x = np.arange(34, dtype=float)
        upper = 120 - 0.35 * x
        lower = 80 + 0.35 * x
        phase = np.cos(2 * np.pi * x / 6)
        center = (upper + lower) / 2
        amplitude = (upper - lower) / 2 - 0.5
        close = center + amplitude * phase
        segment = _frame(close, close + 0.3, close - 0.3)

        lines = _converging_lines(segment, falling=False)

        self.assertIsNotNone(lines)
        resistance, support, _, quality = lines
        self.assertGreater(resistance, support)
        self.assertGreaterEqual(quality, 0.30)

    def test_falling_wedge_requires_three_high_and_two_low_pivots(self):
        x = np.arange(34, dtype=float)
        upper = 130 - 0.55 * x
        lower = 100 - 0.20 * x
        phase = np.cos(2 * np.pi * x / 6)
        center = (upper + lower) / 2
        amplitude = (upper - lower) / 2 - 0.5
        close = center + amplitude * phase
        segment = _frame(close, close + 0.3, close - 0.3)

        lines = _converging_lines(segment, falling=True)

        self.assertIsNotNone(lines)
        self.assertGreater(lines[0], lines[1])

    def test_bullish_pennant_requires_pole_convergence_and_breakout(self):
        prefix = np.linspace(90, 100, 47)
        impulse = np.linspace(100, 112, 20)
        x = np.arange(12, dtype=float)
        upper = 112 - 0.2 * x
        lower = 106 + 0.2 * x
        phase = np.cos(2 * np.pi * x / 4)
        consolidation = (upper + lower) / 2 + ((upper - lower) / 2 - 0.2) * phase
        close = np.concatenate([prefix, impulse, consolidation, [113]])
        volume = np.full(len(close), 1_000_000.0)
        volume[-1] = 2_000_000.0
        frame = _frame(close, close + 0.2, close - 0.2, volume)

        match = _detect_pennant(frame)

        self.assertIsNotNone(match)
        self.assertEqual(match.key, "bullish_pennant")

    def test_volume_and_obv_are_hard_quality_gates_but_rsi_is_not(self):
        close = np.linspace(80, 100, 69).tolist() + [110]
        volume = np.full(70, 1_000_000.0)
        volume[-1] = 500_000.0
        frame = _frame(close, volume=volume)

        self.assertEqual(detect_bullish_chart_patterns(frame), [])
        self.assertGreater(pattern_metrics(frame)["rsi14"], 70)


if __name__ == "__main__":
    unittest.main()
