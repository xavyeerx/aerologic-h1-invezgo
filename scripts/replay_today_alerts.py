#!/usr/bin/env python3
"""
Replay alert hari ini dalam format Telegram (Strong Buy / Acc / Early Entry).

Tidak mengubah evaluasi harian 16:30 — hanya untuk cek manual / sekali jalan di lokal.

Usage:
  python scripts/replay_today_alerts.py
  python scripts/replay_today_alerts.py --date 2026-05-25
  python scripts/replay_today_alerts.py --telegram

Data (salah satu):
  1) Salin dari VM: database/signal_tracker.json (+ optional daily_alerts.json)
  2) Salin daily_alerts.json lalu: --rescan (fetch Yahoo + format lengkap)

  scp user@VM:~/ihsg-scanner/database/signal_tracker.json database/
  scp user@VM:~/ihsg-scanner/database/daily_alerts.json database/
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from notifications.telegram_bot import (
    format_accumulation_message,
    format_early_entry_message,
    format_strong_buy_message,
    send_chunked_alert,
    send_telegram_message,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _AlertView:
    """Adaptor entri signal_tracker / hasil scan → formatter alert."""

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
        self.pattern_name = sig.get("pattern_name", "") or ""
        self.is_bullish_engulfing = bool(sig.get("is_bullish_engulfing", False))
        self.is_price_breakout = bool(sig.get("is_price_breakout", False))


def _paths(data_dir: str) -> tuple[str, str]:
    base = data_dir if os.path.isabs(data_dir) else os.path.join(ROOT, data_dir)
    return (
        os.path.join(base, "signal_tracker.json"),
        os.path.join(base, "daily_alerts.json"),
    )


def _load_tracker(tracker_path: str) -> dict:
    if not os.path.isfile(tracker_path):
        return {}
    with open(tracker_path, encoding="utf-8") as f:
        return json.load(f)


def _tracker_dates(tracker: dict) -> list[str]:
    dates = {str(v.get("alert_date", "")) for v in tracker.values() if v.get("alert_date")}
    return sorted(d for d in dates if d)


def _load_from_tracker(tracker: dict, target_date: str) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {
        "strong_buy": [],
        "accumulation": [],
        "early_entry": [],
    }
    for sig in tracker.values():
        if sig.get("alert_date") != target_date:
            continue
        st = sig.get("signal_type")
        if st in grouped:
            grouped[st].append(sig)
    for st in grouped:
        grouped[st].sort(key=lambda s: (s.get("alert_time", ""), s.get("ticker", "")))
    return grouped


def _load_tickers_from_daily_alerts(daily_path: str, target_date: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {
        "strong_buy": [],
        "accumulation": [],
        "early_entry": [],
    }
    if not os.path.isfile(daily_path):
        return out
    with open(daily_path, encoding="utf-8") as f:
        data = json.load(f)
    if data.get("date") != target_date:
        return out
    for key in out:
        out[key] = list(data.get(key) or [])
    return out


def _result_to_sig(result, signal_type: str) -> dict:
    sl = result.price * 0.95
    return {
        "ticker": result.ticker,
        "signal_type": signal_type,
        "entry_price": result.price,
        "tp1": getattr(result, "tp1", 0),
        "tp2": getattr(result, "tp2", 0) or getattr(result, "tp_swing", 0),
        "sl": sl,
        "change_percent": getattr(result, "change_percent", 0.0),
        "volume_ratio": getattr(result, "volume_ratio", 0.0),
        "macd_status": getattr(result, "macd_status", "") or "",
        "obv_status": getattr(result, "obv_status", "") or "",
        "tp2_source": getattr(result, "tp2_source", "ATR") or "ATR",
        "correction_percent": getattr(result, "correction_percent", 0.0),
        "early_entry_strength": getattr(result, "early_entry_strength", 0),
        "score": getattr(result, "score", 0),
        "alert_time": "",
        "pattern_name": getattr(result, "pattern_name", "") or "",
        "is_bullish_engulfing": bool(getattr(result, "is_bullish_engulfing", False)),
        "is_price_breakout": bool(getattr(result, "is_price_breakout", False)),
    }


def _rescan_grouped(tickers_by_type: dict[str, list[str]]) -> dict[str, list[dict]]:
    from config.settings import DATA_INTERVAL, DATA_PERIOD
    from core.data_fetcher import fetch_multiple_stocks
    from core.scanner import analyze_stock

    all_tickers = list({t for v in tickers_by_type.values() for t in v})
    if not all_tickers:
        return {"strong_buy": [], "accumulation": [], "early_entry": []}

    print(f"Fetching {len(all_tickers)} ticker(s) dari Yahoo...")
    stock_data = fetch_multiple_stocks(
        all_tickers, period=DATA_PERIOD, interval=DATA_INTERVAL
    )

    grouped: dict[str, list[dict]] = {
        "strong_buy": [],
        "accumulation": [],
        "early_entry": [],
    }
    for signal_type, tickers in tickers_by_type.items():
        for ticker in tickers:
            df = stock_data.get(ticker)
            if df is None or len(df) < 50:
                print(f"  skip {ticker}: data tidak cukup")
                continue
            result = analyze_stock(ticker, df, {})
            grouped[signal_type].append(_result_to_sig(result, signal_type))
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
        note = (
            "<i>(--rescan: data live, bukan snapshot persis saat alert)</i>\n\n"
            if rows and not times
            else ""
        )
        out.append(note + header + msg)
    return out


def _print_help_missing(
    target_date: str,
    tracker_path: str,
    daily_path: str,
    tracker: dict,
) -> None:
    print(f"Tidak ada alert untuk tanggal {target_date}.")
    print()
    print("File yang dicek:")
    print(f"  signal_tracker: {'ADA' if os.path.isfile(tracker_path) else 'TIDAK ADA'}")
    print(f"    {tracker_path}")
    print(f"  daily_alerts:   {'ADA' if os.path.isfile(daily_path) else 'TIDAK ADA'}")
    print(f"    {daily_path}")
    if tracker:
        dates = _tracker_dates(tracker)
        if dates:
            print()
            print("Tanggal di signal_tracker:")
            for d in dates:
                print(f"  - {d}")
    if os.path.isfile(daily_path):
        with open(daily_path, encoding="utf-8") as f:
            da = json.load(f)
        print()
        print(f"daily_alerts.json date = {da.get('date', '?')}")
    print()
    print("Langkah dari VM (Git Bash / terminal):")
    print(
        '  scp anugrahdwikiar@algotrade-bot-server:~/ihsg-scanner/database/signal_tracker.json '
        f'"{os.path.join(ROOT, "database")}/"'
    )
    print(
        '  scp anugrahdwikiar@algotrade-bot-server:~/ihsg-scanner/database/daily_alerts.json '
        f'"{os.path.join(ROOT, "database")}/"'
    )
    print()
    print("Lalu jalankan lagi, atau jika hanya punya daily_alerts:")
    print(f"  python scripts/replay_today_alerts.py --date {target_date} --rescan")


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay alert TF hari tertentu")
    parser.add_argument(
        "--date",
        default=datetime.now().strftime("%Y-%m-%d"),
        help="Tanggal alert (YYYY-MM-DD), default hari ini",
    )
    parser.add_argument(
        "--data-dir",
        default="database",
        help="Folder berisi signal_tracker.json / daily_alerts.json",
    )
    parser.add_argument(
        "--rescan",
        action="store_true",
        help="Bangun ulang dari daily_alerts.json + fetch Yahoo (format lengkap)",
    )
    parser.add_argument(
        "--telegram",
        action="store_true",
        help="Kirim ke Telegram (default: cetak ke terminal)",
    )
    args = parser.parse_args()

    tracker_path, daily_path = _paths(args.data_dir)
    tracker = _load_tracker(tracker_path)
    grouped = _load_from_tracker(tracker, args.date)

    if sum(len(v) for v in grouped.values()) == 0 and args.rescan:
        tickers = _load_tickers_from_daily_alerts(daily_path, args.date)
        if sum(len(v) for v in tickers.values()) > 0:
            grouped = _rescan_grouped(tickers)

    total = sum(len(v) for v in grouped.values())
    if total == 0:
        _print_help_missing(args.date, tracker_path, daily_path, tracker)
        return

    messages = _build_messages(grouped) if not args.telegram else []
    banner = (
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 RIWAYAT ALERT — {args.date}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Total: {total} sinyal\n"
    )

    if args.telegram:
        send_telegram_message(banner)
        sent = 0
        for key, formatter in (
            ("strong_buy", format_strong_buy_message),
            ("accumulation", format_accumulation_message),
            ("early_entry", format_early_entry_message),
        ):
            rows = grouped.get(key) or []
            if not rows:
                continue
            views = [_AlertView(s) for s in rows]
            sent += send_chunked_alert(views, formatter)
        print(f"Terkirim {sent} blok ke Telegram.")
    else:
        print(_strip_html(banner))
        for msg in messages:
            print(_strip_html(msg))
            print()


if __name__ == "__main__":
    main()
