import unittest

from core.screener import ScreenWindow, allocate_candidate_lanes, build_formula


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
        self.assertIn('sma("value",20) > 5000000000', formula)
        self.assertIn('volume > sma("volume",20) * 0.5', formula)
        self.assertIn("change_pct > -8", formula)
        self.assertNotIn("change_pct < 15", formula)
        self.assertNotIn(" && value > 5000000000", formula)

    def test_lane_reservations_prevent_all_momentum_selection(self):
        rows = [candidate(f"M{i:02}", 2.0, 100 - i) for i in range(40)]
        rows += [candidate(f"C{i:02}", 0.5, 30 - i) for i in range(15)]
        rows += [candidate(f"R{i:02}", -2.0, 15 - i) for i in range(15)]
        picked = allocate_candidate_lanes(rows)
        counts = {
            lane: sum(row["lane"] == lane for row in picked)
            for lane in ("momentum", "constructive", "reversal")
        }
        self.assertEqual(len(picked), 50)
        self.assertGreaterEqual(counts["constructive"], 10)
        self.assertGreaterEqual(counts["reversal"], 10)
        self.assertLessEqual(counts["momentum"], 30)

    def test_duplicate_ticker_is_fetched_once_using_best_activity(self):
        rows = [candidate("BBCA", 2.0, 1.2), candidate("bbca", 2.0, 2.5)]
        picked = allocate_candidate_lanes(rows)
        self.assertEqual([row["code"] for row in picked], ["BBCA"])
        self.assertAlmostEqual(picked[0]["activity_ratio"], 2.5)


if __name__ == "__main__":
    unittest.main()
