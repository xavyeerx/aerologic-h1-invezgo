import unittest
from types import SimpleNamespace

from notifications.telegram_bot import (
    _format_transaction_value,
    format_bullish_break_message,
    format_early_entry_message,
    format_reversal_watch_message,
    format_strong_buy_message,
)


def result(**overrides):
    values = {
        "ticker": "PACK.JK", "price": 510.0, "change_percent": 9.4,
        "score": 85, "volume_ratio": 1.4, "daily_turnover": 1_200_000_000.0,
        "market_regime": "SIDEWAYS", "tp1": 541.0, "tp2": 587.0,
        "tp2_source": "ATR", "early_entry_strength": 6,
        "correction_percent": -4.5, "return20_pct": -10.0, "rsi": 32.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class TelegramAlertFormattingTests(unittest.TestCase):
    def test_transaction_value_uses_compact_indonesian_decimal(self):
        self.assertEqual(_format_transaction_value(1_200_000_000), "1,2B")
        self.assertEqual(_format_transaction_value(850_000_000), "850,0M")

    def test_all_alert_types_include_volume_value_and_footer(self):
        for formatter in (
            format_strong_buy_message,
            format_bullish_break_message,
            format_early_entry_message,
            format_reversal_watch_message,
        ):
            with self.subTest(formatter=formatter.__name__):
                message = formatter([result()])
                self.assertIn("Vol 1.4x | Val 1,2B", message)
                self.assertEqual(message.count("Vol 1.4x | Val 1,2B"), 1)
                self.assertTrue(message.endswith("Powered by Aeerologic"))


if __name__ == "__main__":
    unittest.main()
