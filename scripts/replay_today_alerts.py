#!/usr/bin/env python3
"""
Replay alert hari ini dalam format Telegram (Strong Buy / Acc / Early Entry).

Tidak mengubah evaluasi harian 16:30 — hanya untuk cek manual / sekali jalan di lokal.

Usage:
  python scripts/replay_today_alerts.py
  python scripts/replay_today_alerts.py --telegram
  python scripts/replay_today_alerts.py --date 2026-05-25
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.state_manager import StateManager
from notifications.telegram_bot import (
    format_accumulation_message,
    format_early_entry_message,
    format_strong_buy_message,
    send_telegram_message,
)


class _AlertView:
    """Adaptor entri signal_tracker → formatter alert."""

    def __init__(self, sig: dict):
        self.ticker = sig.get("ticker", "")
        self.price = float(sig.get("entry_price", 0) or 0)
        self.change_percent = float(sig.get("change_percent", 0) or 0)
        self.score = int(sig.get("score", 0) or 0)
        self.volume_ratio = float(sig.get("volume_ratio", 0) or 0)
        self.macd_status = sig.get("macd_status", "") or "—"
        self.obv_status = sig.get("obv_status", "") or "—"
        self.tp1 = float(sig.get("tp1", 0) or 0)
        self.tp2 = float(sig.get("tp2", 0) or 0)
        self.tp2_source = sig.get("tp2_source", "ATR") or "ATR"
        self.correction_percent = float(sig.get("correction_percent", 0) or 0)
        self.early_entry_strength = int(sig.get("early_entry_strength", 0) or 0)
        self.alert_time = sig.get("alert_time", "")


def _load_by_date(target_date: str) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {
        "strong_buy": [],
        "accumulation": [],
        "early_entry": [],
    }
    for sig in StateManager()._load_tracker().values():
        if sig.get("alert_date") != target_date:
            continue
        st = sig.get("signal_type")
        if st in grouped:
            grouped[st].append(sig)
    for st in grouped:
        grouped[st].sort(key=lambda s: (s.get("alert_time", ""), s.get("ticker", "")))
    return grouped


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


def _build_messages(grouped: dict[str, list[dict]]) -> list[str]:
    out: list[str] = []
    for key, formatter in (
        ("strong_buy", format_strong_buy_message),
        ("accumulation", format_accumulation_message),
        ("early_entry", format_early_entry_message),
    ):
        rows = grouped.get(key) or []
        if not rows:
            continue
        views = [_AlertView(s) for s in rows]
        msg = formatter(views)
        if not msg:
            continue
        times = ", ".join(sorted({v.alert_time for v in views if v.alert_time}))
        header = f"🕐 Terkirim: {times or '—'} WIB\n\n" if times else ""
        out.append(header + msg)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay alert TF hari tertentu")
    parser.add_argument(
        "--date",
        default=datetime.now().strftime("%Y-%m-%d"),
        help="Tanggal alert (YYYY-MM-DD), default hari ini",
    )
    parser.add_argument(
        "--telegram",
        action="store_true",
        help="Kirim ke Telegram (default: cetak ke terminal saja)",
    )
    args = parser.parse_args()

    grouped = _load_by_date(args.date)
    total = sum(len(v) for v in grouped.values())
    if total == 0:
        print(f"Tidak ada alert di signal_tracker untuk tanggal {args.date}.")
        print("Pastikan database/signal_tracker.json dari server VM sudah disalin ke lokal.")
        return

    messages = _build_messages(grouped)
    banner = (
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 RIWAYAT ALERT — {args.date}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Total: {total} sinyal\n"
    )

    if args.telegram:
        send_telegram_message(banner)
        for msg in messages:
            send_telegram_message(msg)
        print(f"Ter kirim {len(messages)} blok ke Telegram.")
    else:
        print(_strip_html(banner))
        for msg in messages:
            print(_strip_html(msg))
            print()


if __name__ == "__main__":
    main()
