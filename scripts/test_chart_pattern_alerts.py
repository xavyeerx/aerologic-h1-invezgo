#!/usr/bin/env python3
"""
Uji deteksi pola chart + filter kualitas (sama pipeline reviu TF-D / anchor H).
Default: subset awal list agar cepat; set env CHART_TEST_ALL=1 untuk semua ticker.

  python scripts/test_chart_pattern_alerts.py
  CHART_TEST_LIMIT=200 python scripts/test_chart_pattern_alerts.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import (
    DATA_PERIOD,
    DATA_INTERVAL,
    MIN_DAILY_TURNOVER,
    VOLUME_PERIOD,
)
from config.stocks_list import get_all_stocks
from core.data_fetcher import fetch_multiple_stocks
from core.chart_patterns import (
    CHART_MIN_BARS,
    PATTERN_LABELS,
    detect_bullish_chart_patterns,
    passes_chart_alert_quality_filters,
)


def main():
    stocks = get_all_stocks()
    if os.getenv("CHART_TEST_ALL") != "1":
        limit = int(os.getenv("CHART_TEST_LIMIT", "150"))
        stocks = stocks[:limit]
        print(f"[test] subset: {len(stocks)} ticker (CHART_TEST_ALL=1 untuk penuh)\n")
    else:
        print(f"[test] universe penuh: {len(stocks)} ticker\n")

    print(f"Mengambil OHLC ({DATA_PERIOD}, {DATA_INTERVAL})...")
    data = fetch_multiple_stocks(stocks, period=DATA_PERIOD, interval=DATA_INTERVAL)
    print(f"Data ter-fetch: {len(data)}\n")

    rows_raw = []
    rows_ok = []

    for t, df in data.items():
        if df is None or len(df) < CHART_MIN_BARS:
            continue
        dx = df.copy()
        dx["turnover"] = dx["close"] * dx["volume"]
        if dx["turnover"].rolling(5).mean().iloc[-1] < MIN_DAILY_TURNOVER:
            continue

        flags = detect_bullish_chart_patterns(dx)
        fired = [(k, PATTERN_LABELS.get(k, k)) for k, v in flags.items() if v]
        if not fired:
            continue

        prev_close = float(dx["close"].iloc[-2]) if len(dx) >= 2 else float(dx["close"].iloc[-1])
        price = float(dx["close"].iloc[-1])
        chg = ((price - prev_close) / prev_close * 100.0) if prev_close > 0 else 0.0
        avg_vol = float(dx["volume"].rolling(window=VOLUME_PERIOD).mean().iloc[-1])
        vm = float(dx["volume"].iloc[-1] / avg_vol) if avg_vol > 0 else 1.0

        for pk, lbl in fired:
            rows_raw.append((t.replace(".JK", ""), pk, lbl, price, chg, vm))

        if passes_chart_alert_quality_filters(dx):
            for pk, lbl in fired:
                rows_ok.append((t.replace(".JK", ""), pk, lbl, price, chg, vm))

    print("=" * 78)
    print(f"RAW (pola tanpa filter kualitas): {len(rows_raw)} baris")
    print(f"PASS (lolos volume + OBV): {len(rows_ok)} baris")
    print("=" * 78)

    if rows_ok:
        rows_ok.sort(key=lambda x: (x[2], x[0]))
        print("\nContoh sampai 40 baris (lolos filter):\n")
        for row in rows_ok[:40]:
            ticker, pk, lbl, price, chg, vm = row
            cs = f"+{chg:.1f}%" if chg >= 0 else f"{chg:.1f}%"
            print(f"  {ticker:7} {lbl:42} close {price:>12,.2f}  {cs:>8}  vol {vm:.2f}x")

        if len(rows_ok) > 40:
            print(f"\n  ... +{len(rows_ok) - 40} baris lainnya")
    else:
        print("\n(Tidak ada yang lolos filter pada subset ini — coba naikkan CHART_TEST_LIMIT atau CHART_TEST_ALL=1)")
    print("\n" + "=" * 78)


if __name__ == "__main__":
    main()
