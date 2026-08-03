import unittest

from core.risk_engine import RiskPolicy, build_long_risk_plan


class RiskEngineTests(unittest.TestCase):
    def test_position_is_lot_rounded_and_within_risk_budget(self):
        policy = RiskPolicy(risk_fraction=0.005, min_stop_pct=1, max_stop_pct=5)
        plan = build_long_risk_plan(
            entry_price=1000, setup_low=960, atr=15, equity=100_000_000,
            tick_size=5, policy=policy,
        )
        self.assertTrue(plan.eligible)
        self.assertEqual(plan.shares % 100, 0)
        self.assertLessEqual(plan.capital_at_risk, plan.risk_budget)
        self.assertLessEqual(plan.position_value, 20_000_000)

    def test_exhausted_portfolio_budget_returns_zero_size(self):
        plan = build_long_risk_plan(
            entry_price=1000, setup_low=950, atr=20, equity=100_000_000,
            open_risk=2_000_000,
        )
        self.assertFalse(plan.eligible)
        self.assertEqual(plan.reason, "RISK_BUDGET_EXHAUSTED")
        self.assertEqual(plan.shares, 0)

    def test_too_tight_stop_is_rejected(self):
        plan = build_long_risk_plan(
            entry_price=1000, setup_low=999, atr=1, equity=100_000_000,
        )
        self.assertFalse(plan.eligible)
        self.assertEqual(plan.reason, "STOP_TOO_TIGHT")

    def test_maximum_stop_loss_is_capped(self):
        plan = build_long_risk_plan(
            entry_price=1000, setup_low=800, atr=200, equity=100_000_000,
        )
        self.assertTrue(plan.eligible)
        self.assertAlmostEqual(plan.stop_price, 950)
        self.assertAlmostEqual(plan.stop_pct, 5)

    def test_invalid_policy_is_rejected(self):
        with self.assertRaises(ValueError):
            RiskPolicy(min_stop_pct=6, max_stop_pct=5)


if __name__ == "__main__":
    unittest.main()
