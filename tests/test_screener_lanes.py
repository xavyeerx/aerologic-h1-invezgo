import unittest

from core.screener import ScreenWindow, build_formula, select_candidates


def candidate(code, change_pct, ratio):
    factor = 0.5
    return {
        "code": code,
        "change_pct": change_pct,
        "volume": ratio * 100 * factor,
        'sma("volume",20) * 0.5': 100 * factor,
        "value": 10_000_000_000,
    }


class ScreenerLaneTests(unittest.TestCase):
    def test_formula_uses_historical_liquidity_and_broad_price_envelope(self):
        formula = build_formula(ScreenWindow("test", 0.5, True, True))
        self.assertIn("close > 0", formula)
        self.assertIn('sma("value",20) > 5000000000', formula)
        self.assertIn('volume > sma("volume",20) * 0.5', formula)
        self.assertIn("change_pct > -8", formula)
        self.assertNotIn("change_pct < 15", formula)
        self.assertNotIn(" && value > 5000000000", formula)

    def test_candidates_are_ranked_without_lane_reservations(self):
        rows = [candidate(f"M{i:02}", 2.0, 100 - i) for i in range(40)]
        rows += [candidate(f"C{i:02}", 0.5, 30 - i) for i in range(15)]
        rows += [candidate(f"R{i:02}", -2.0, 15 - i) for i in range(15)]
        picked = select_candidates(rows)
        self.assertEqual(len(picked), 50)
        self.assertNotIn("lane", picked[0])
        self.assertEqual(
            [row["activity_ratio"] for row in picked],
            sorted((row["activity_ratio"] for row in picked), reverse=True),
        )

    def test_duplicate_ticker_is_fetched_once_using_best_activity(self):
        rows = [candidate("BBCA", 2.0, 1.2), candidate("bbca", 2.0, 2.5)]
        picked = select_candidates(rows)
        self.assertEqual([row["code"] for row in picked], ["BBCA"])
        self.assertAlmostEqual(picked[0]["activity_ratio"], 2.5)


if __name__ == "__main__":
    unittest.main()
