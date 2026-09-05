"""Preview or send representative Telegram alerts to the isolated test group."""

import argparse
import sys
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import TELEGRAM_TEST_CHAT_ID  # noqa: E402
from notifications.telegram_bot import (  # noqa: E402
    format_bullish_break_message,
    format_early_entry_message,
    format_reversal_watch_message,
    format_strong_buy_message,
    send_telegram_message,
)


def _sample(**overrides) -> SimpleNamespace:
    values = {
        "ticker": "PACK.JK",
        "price": 510.0,
        "change_percent": 9.4,
        "score": 85,
        "volume_ratio": 1.4,
        "daily_turnover": 1_200_000_000.0,
        "market_regime": "SIDEWAYS",
        "tp1": 541.0,
        "tp2": 587.0,
        "tp2_source": "ATR",
        "early_entry_strength": 6,
        "correction_percent": 4.5,
        "return20_pct": -10.0,
        "rsi": 32.0,
        "supertrend_value": 505.0,
        "supertrend_support": 480.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def build_sample_alerts() -> list[tuple[str, str]]:
    return [
        (
            "Bullish Breakout",
            format_bullish_break_message([
                _sample(
                    ticker="BBYB.JK",
                    price=270.0,
                    change_percent=6.3,
                    volume_ratio=1.2,
                    daily_turnover=8_700_000_000.0,
                    market_regime="BULL",
                    tp1=286.0,
                    tp2=300.0,
                    supertrend_value=265.0,
                )
            ]),
        ),
        ("Strong Buy", format_strong_buy_message([_sample()])),
        (
            "Early Entry",
            format_early_entry_message([
                _sample(
                    ticker="ABCD.JK",
                    price=500.0,
                    change_percent=-3.1,
                    volume_ratio=1.3,
                    daily_turnover=2_400_000_000.0,
                    market_regime="BULL",
                    tp1=530.0,
                    tp2=560.0,
                    supertrend_support=475.0,
                )
            ]),
        ),
        (
            "Reversal Watch",
            format_reversal_watch_message([
                _sample(
                    ticker="WXYZ.JK",
                    price=320.0,
                    change_percent=-5.2,
                    volume_ratio=2.1,
                    daily_turnover=3_600_000_000.0,
                    return20_pct=-14.0,
                    rsi=28.0,
                )
            ]),
        ),
    ]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Preview alert contoh atau kirim ke TELEGRAM_TEST_CHAT_ID."
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help="Kirim semua alert contoh ke grup test; default hanya preview.",
    )
    args = parser.parse_args()
    alerts = build_sample_alerts()

    if not args.send:
        for label, message in alerts:
            print(f"\n===== {label} =====\n{message}")
        return 0

    if not TELEGRAM_TEST_CHAT_ID:
        print("ERROR: TELEGRAM_TEST_CHAT_ID belum dikonfigurasi.", file=sys.stderr)
        return 1

    failed = []
    for label, message in alerts:
        sent = send_telegram_message(
            message,
            chat_id=TELEGRAM_TEST_CHAT_ID,
            use_default_thread=False,
        )
        print(f"{label}: {'TERKIRIM' if sent else 'GAGAL'}")
        if not sent:
            failed.append(label)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
