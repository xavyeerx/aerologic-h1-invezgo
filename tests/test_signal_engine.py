import unittest

from core.signal_engine import (
    SignalFeatures,
    is_momentum_expansion,
    is_selling_climax_reversal,
)


def features(**overrides):
    values = dict(
        market_regime="BULL", close=110.0, ema20=105.0, ema50=100.0,
        return20_pct=8.0, volume_ratio=1.5, rsi=55.0, bullish_body=True,
        close_location=0.8, body_fraction=0.5, upper_wick_fraction=0.1,
        lower_wick_fraction=0.2,
    )
    values.update(overrides)
    return SignalFeatures(**values)


class SignalEngineTests(unittest.TestCase):
    def test_momentum_expansion_requires_trend_quality_and_regime(self):
        self.assertTrue(is_momentum_expansion(
            features(), min_return20=5.0, min_volume_ratio=1.2,
        ))
        self.assertFalse(is_momentum_expansion(
            features(market_regime="BEAR"), min_return20=5.0, min_volume_ratio=1.2,
        ))
        self.assertFalse(is_momentum_expansion(
            features(upper_wick_fraction=0.45), min_return20=5.0, min_volume_ratio=1.2,
        ))

    def test_selling_climax_is_watchlist_not_momentum(self):
        candidate = features(
            market_regime="BEAR", return20_pct=-12.0, volume_ratio=2.0,
            rsi=29.0, lower_wick_fraction=0.3,
        )
        self.assertTrue(is_selling_climax_reversal(
            candidate, max_return20=-8.0, max_rsi=35.0, min_volume_ratio=1.5,
        ))
        self.assertFalse(is_momentum_expansion(
            candidate, min_return20=5.0, min_volume_ratio=1.2,
        ))


if __name__ == "__main__":
    unittest.main()
