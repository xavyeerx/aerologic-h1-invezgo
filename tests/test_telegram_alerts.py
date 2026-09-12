import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import notifications.telegram_bot as telegram_bot
import pytz
from core.news_context import NewsContext, NewsContextItem
from notifications.telegram_bot import (
    _send_to_api,
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
        "sector": "Barang Baku & Industri",
        "tp2_source": "ATR", "early_entry_strength": 6,
        "correction_percent": -4.5, "return20_pct": -10.0, "rsi": 32.0,
        "supertrend_value": 505.0, "supertrend_support": 480.0,
        "entry_zone_low": 500.0, "entry_zone_high": 510.0,
        "sl": 480.0, "sl_source": "SUPPORT",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class TelegramAlertFormattingTests(unittest.TestCase):
    def test_backend_sync_is_disabled_by_default(self):
        with patch.object(telegram_bot, "SIGNAL_API_ENABLED", False), patch.object(
            telegram_bot.requests, "post"
        ) as post:
            _send_to_api([result()], "strong_buy")
        post.assert_not_called()

    def test_backend_sync_runs_once_for_an_alert_batch(self):
        with patch.object(
            telegram_bot, "_chunked_alert_messages", return_value=["part 1", "part 2"]
        ), patch.object(
            telegram_bot, "send_telegram_message", return_value=True
        ), patch.object(telegram_bot, "_send_to_api") as send_api:
            sent = telegram_bot.send_chunked_alert(
                [result()], format_strong_buy_message, alert_type="strong_buy"
            )
        self.assertEqual(sent, 2)
        send_api.assert_called_once()

    def test_targets_at_or_below_alert_price_are_hidden(self):
        message = format_strong_buy_message([result(price=550.0, tp1=540.0, tp2=550.0)])
        self.assertNotIn("TP1:", message)
        self.assertNotIn("TP2:", message)

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
                self.assertIn(
                    "DYOR. Bukan rekomendasi beli atau jual. Risiko di tangan masing-masing.",
                    message,
                )
                self.assertLess(message.index("DYOR."), message.index("Powered by Aerologic"))
                self.assertTrue(message.endswith("<i>Powered by Aerologic</i>"))

    def test_all_alert_types_omit_h1_candle_status_and_total(self):
        for formatter in (
            format_strong_buy_message,
            format_bullish_break_message,
            format_early_entry_message,
            format_reversal_watch_message,
        ):
            with self.subTest(formatter=formatter.__name__):
                message = formatter([result(bar_closed=False)])
                self.assertNotIn("H1", message)
                self.assertNotIn("Candle", message)
                self.assertNotIn("Total:", message)

    def test_each_unique_ticker_is_sent_as_a_separate_message(self):
        results = [result(ticker="PACK.JK"), result(ticker="RAJA.JK"), result(ticker="PACK.JK")]

        messages = telegram_bot._chunked_alert_messages(results, format_strong_buy_message)

        self.assertEqual(len(messages), 2)
        self.assertIn("<b>PACK |", messages[0])
        self.assertNotIn("RAJA", messages[0])
        self.assertIn("<b>RAJA |", messages[1])
        self.assertNotIn("PACK", messages[1])

    def test_bullish_breakout_format(self):
        message = format_bullish_break_message([result()])
        self.assertIn("<b>🔥 BULLISH BREAKOUT</b>", message)
        self.assertIn("<b>PACK | 510 (+9.4%)</b>", message)
        self.assertIn("Resistance 505 | Vol 1.4x | Val 1,2B", message)
        self.assertIn("Vol 1.4x | Val 1,2B\n\nTrend IHSG", message)
        self.assertIn("Trend IHSG: SIDEWAYS", message)
        self.assertIn("Sector: Barang Baku &amp; Industri", message)
        self.assertIn("Sector: Barang Baku &amp; Industri\n\nEntry Area", message)
        self.assertIn("TP 1: 541 (+6.1%)", message)
        self.assertIn("RBS: 505", message)
        self.assertNotIn("Total:", message)

    def test_strong_buy_uses_supertrend_support_without_stop_loss(self):
        message = format_strong_buy_message([result()])
        self.assertIn("<b>🚀 STRONG BUY</b>", message)
        self.assertNotIn("Score", message)
        self.assertIn("Vol 1.4x | Val 1,2B", message)
        self.assertIn("Trend IHSG: SIDEWAYS", message)
        self.assertIn("Sector: Barang Baku &amp; Industri", message)
        self.assertIn("Val 1,2B\n\nTrend IHSG", message)
        self.assertIn("Sector: Barang Baku &amp; Industri\n\nEntry Area", message)
        self.assertIn("Support: 480", message)
        self.assertIn("Pastikan area Support (480) dijaga", message)
        self.assertIn("Entry Area: 500 - 510", message)
        self.assertIn("SL: 480 (-5.9%)", message)
        self.assertNotIn("SUPPORT", message)

    def test_strong_buy_appends_sanitized_recent_news_context(self):
        published_at = pytz.timezone("Asia/Jakarta").localize(
            datetime(2026, 8, 24, 14, 26)
        )
        context = NewsContext(
            direct=None,
            positives=(),
            risks=(
                NewsContextItem(
                    "Invezgo News - BEI Buka Kembali Perdagangan Saham PACK",
                    published_at,
                    "risk",
                ),
            ),
        )

        message = format_strong_buy_message([result(news_context=context)])

        self.assertIn("📰 KONTEKS &amp; KATALIS PACK", message)
        self.assertIn("Katalis langsung: Tidak ditemukan", message)
        self.assertIn("• 24 Agu: BEI Buka Kembali Perdagangan Saham PACK", message)
        self.assertIn("Momentum teknikal belum didukung katalis baru", message)
        self.assertNotIn("Invezgo", message)

    def test_early_entry_maps_bull_regime_and_uses_support(self):
        message = format_early_entry_message([result(market_regime="BULL")])
        self.assertIn("<b>🎯 EARLY ENTRY</b>", message)
        self.assertIn("Trend IHSG: BULLISH", message)
        self.assertIn("Sector: Barang Baku &amp; Industri", message)
        self.assertIn("Val 1,2B\n\nTrend IHSG", message)
        self.assertIn("Sector: Barang Baku &amp; Industri\n\nEntry Area", message)
        self.assertIn("Support: 480", message)
        self.assertNotIn("Strength", message)
        self.assertIn("Entry Area: 500 - 510", message)
        self.assertIn("SL: 480 (-5.9%)", message)


if __name__ == "__main__":
    unittest.main()
