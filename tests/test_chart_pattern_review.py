import tempfile
import unittest
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd

from core.chart_pattern_review import (
    SCREENER_FORMULA,
    build_review_messages,
    run_daily_chart_pattern_review,
    select_liquid_universe,
)


class ChartPatternReviewTests(unittest.TestCase):
    def test_liquid_universe_is_ranked_and_capped(self):
        rows = [
            {"code": "LOW", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 1, 'sma("value",5)': 10},
            {"code": "HIGH", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 1, 'sma("value",5)': 30},
            {"code": "MID", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 1, 'sma("value",5)': 20},
        ]
        selected = select_liquid_universe(rows, 2)
        self.assertEqual([row["code"] for row in selected], ["HIGH", "MID"])
        self.assertIn('sma("value",5)', SCREENER_FORMULA)

    @patch("core.chart_pattern_review.run_screener")
    @patch("core.chart_pattern_review.fetch_chart")
    @patch("core.chart_pattern_review.fetch_index")
    def test_recurring_run_uses_cache_without_stock_chart_calls(self, fetch_index, fetch_chart, run_screener):
        dates = pd.date_range("2026-06-01", "2026-09-11", freq="B")
        index_frame = pd.DataFrame(
            {"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}, index=dates
        )
        fetch_index.return_value = index_frame
        run_screener.return_value = [
            {
                "code": "TEST", "open": 100, "high": 102, "low": 99,
                "close": 101, "volume": 100_000_000, 'sma("value",5)': 10_000_000_000,
                "prev": 100,
            }
        ]
        historical_dates = dates[:-1]
        records = [
            {
                "date": timestamp.strftime("%Y-%m-%d"), "open": 99, "high": 102,
                "low": 98, "close": float(99 + index % 3), "volume": 100_000_000,
            }
            for index, timestamp in enumerate(historical_dates[-80:])
        ]
        with tempfile.TemporaryDirectory() as folder:
            cache_path = Path(folder) / "cache.json"
            state_path = Path(folder) / "state.json"
            cache_path.write_text(
                __import__("json").dumps({"version": 1, "stocks": {"TEST": records}}),
                encoding="utf-8",
            )
            outcome = run_daily_chart_pattern_review(
                now=datetime(2026, 9, 11, 16, 30), force=True, send=False,
                universe_limit=1, cache_path=cache_path, state_path=state_path,
            )

        self.assertEqual(outcome.universe_size, 1)
        self.assertEqual(outcome.bootstrapped, 0)
        fetch_chart.assert_not_called()

    def test_empty_review_still_has_a_clear_message(self):
        messages = build_review_messages([], datetime(2026, 9, 11, 16, 30), 240)
        self.assertEqual(len(messages), 1)
        self.assertIn("Tidak ada pola", messages[0])
        self.assertIn("240 saham terlikuid", messages[0])

    @patch("core.chart_pattern_review.detect_bullish_chart_patterns", return_value=[])
    @patch("core.chart_pattern_review.run_screener")
    @patch("core.chart_pattern_review.fetch_chart")
    @patch("core.chart_pattern_review.fetch_index")
    def test_empty_review_is_completed_without_sending_telegram(
        self, fetch_index, fetch_chart, run_screener, _detect_patterns
    ):
        dates = pd.date_range("2026-06-01", "2026-09-14", freq="B")
        market_frame = pd.DataFrame(
            {
                "open": 100,
                "high": 102,
                "low": 99,
                "close": 101,
                "volume": 100_000_000,
            },
            index=dates,
        )
        fetch_index.return_value = market_frame
        fetch_chart.return_value = market_frame
        run_screener.return_value = [
            {
                "code": "TEST",
                "open": 100,
                "high": 102,
                "low": 99,
                "close": 101,
                "volume": 100_000_000,
                'sma("value",5)': 10_000_000_000,
                "prev": 100,
            }
        ]
        sender = Mock(return_value=True)

        with tempfile.TemporaryDirectory() as folder:
            state_path = Path(folder) / "state.json"
            outcome = run_daily_chart_pattern_review(
                now=datetime(2026, 9, 14, 16, 30),
                force=True,
                send=True,
                universe_limit=1,
                cache_path=Path(folder) / "cache.json",
                state_path=state_path,
                sender=sender,
            )
            state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(outcome.matches, 0)
        sender.assert_not_called()
        self.assertEqual(state["last_completed_date"], "2026-09-14")
        self.assertEqual(state["matches"], 0)

    @patch("core.chart_pattern_review.run_screener")
    @patch("core.chart_pattern_review.fetch_chart")
    @patch("core.chart_pattern_review.fetch_index")
    def test_latest_bar_bypass_is_available_for_weekend_dry_run(
        self, fetch_index, fetch_chart, run_screener
    ):
        dates = pd.date_range("2026-06-01", "2026-09-11", freq="B")
        fetch_index.return_value = pd.DataFrame(
            {"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}, index=dates
        )
        history = pd.DataFrame(
            {
                "open": np.linspace(90, 100, len(dates)),
                "high": np.linspace(91, 101, len(dates)),
                "low": np.linspace(89, 99, len(dates)),
                "close": np.linspace(90, 100, len(dates)),
                "volume": 100_000_000,
            },
            index=dates,
        )
        fetch_chart.return_value = history
        run_screener.return_value = [
            {
                "code": "TEST", "open": 99, "high": 101, "low": 98,
                "close": 100, "volume": 100_000_000,
                'sma("value",5)': 10_000_000_000, "prev": 99,
            }
        ]
        with tempfile.TemporaryDirectory() as folder:
            outcome = run_daily_chart_pattern_review(
                now=datetime(2026, 9, 13, 18, 30), force=True, send=False,
                use_latest_available_bar=True, universe_limit=1,
                cache_path=Path(folder) / "cache.json",
                state_path=Path(folder) / "state.json",
            )

        self.assertEqual(outcome.status, "completed")
        self.assertIn("Data candle: 11 Sep 2026", outcome.messages[0])

    def test_large_review_is_split_below_telegram_limit(self):
        from core.chart_patterns import PatternMatch
        from core.chart_pattern_review import ReviewItem

        items = [
            ReviewItem(
                f"T{index:03d}", PatternMatch("break_base", 100, 90),
                {"close": 100, "change_pct": 2, "volume_ratio": 1.5, "rsi14": 60, "turnover5": 1e10},
            )
            for index in range(240)
        ]
        messages = build_review_messages(items, datetime(2026, 9, 11, 16, 30), 240)
        self.assertGreater(len(messages), 1)
        self.assertTrue(all(len(message) <= 4096 for message in messages))
        self.assertEqual(sum(message.count("<code>T") for message in messages), 240)


if __name__ == "__main__":
    unittest.main()
