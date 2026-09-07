"""Read-only historical replay for closed-H1 signal candidates."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytz

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.stocks_list import IHSG_STOCKS  # noqa: E402
from core.data_fetcher import fetch_multiple_stocks  # noqa: E402
from core.data_provider import fetch_h1_chart  # noqa: E402
from core.scanner import analyze_stock, filter_signals  # noqa: E402
from learning.market_regime import _detect_regime  # noqa: E402

WIB = pytz.timezone("Asia/Jakarta")


def previous_weekday(day: date) -> date:
    candidate = day - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay Strong Buy/Bullish Break candidates on closed H1 bars."
    )
    parser.add_argument(
        "--date", default=previous_weekday(datetime.now(WIB).date()).isoformat(),
        help="Replay date in YYYY-MM-DD (default: previous weekday).",
    )
    universe = parser.add_mutually_exclusive_group(required=True)
    universe.add_argument(
        "--tickers", nargs="+", help="Ticker list, e.g. BBCA BBRI TLKM."
    )
    universe.add_argument(
        "--all", action="store_true", help="Scan the local 475-stock liquid universe."
    )
    parser.add_argument("--csv", help="Optional CSV output path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    target = date.fromisoformat(args.date)
    if target.weekday() >= 5:
        raise SystemExit("Replay date must be an IDX weekday")
    tickers = IHSG_STOCKS if args.all else args.tickers
    tickers = [str(ticker).replace(".JK", "").upper() for ticker in tickers]

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    stock_data = fetch_multiple_stocks(tickers, period="45d", interval="60")

    start = (target - timedelta(days=45)).isoformat()
    ihsg = fetch_h1_chart("COMPOSITE", start, target.isoformat())
    if ihsg is None or ihsg.empty:
        raise SystemExit("Unable to fetch H1 COMPOSITE context")

    rows: list[dict] = []
    alerted_tickers: set[str] = set()
    for ticker, full_frame in stock_data.items():
        target_bars = full_frame[full_frame.index.date == target]
        for timestamp in target_bars.index:
            if ticker in alerted_tickers:
                break  # production daily risk gate permits one call per ticker/day
            frame = full_frame.loc[:timestamp].copy()
            ihsg_at_bar = ihsg.loc[:timestamp]
            regime = (
                _detect_regime(ihsg_at_bar)["regime"]
                if len(ihsg_at_bar) >= 64 else "UNKNOWN"
            )
            result = analyze_stock(ticker, frame, market_regime=regime)
            signals = filter_signals({ticker: result})
            signal_types = [
                name for name in ("bullish_break", "strong_buy") if signals[name]
            ]
            if not signal_types:
                continue
            alerted_tickers.add(ticker)
            rows.append({
                "date": target.isoformat(),
                "bar_timestamp": result.bar_timestamp,
                "ticker": ticker,
                "signal": "+".join(signal_types),
                "close": result.price,
                "h1_change_pct": round(result.change_percent, 2),
                "supertrend": round(result.supertrend_value, 4),
                "volume_ratio": round(result.volume_ratio, 2),
                "market_regime": result.market_regime,
            })

    output = pd.DataFrame(rows)
    if output.empty:
        print(f"No Strong Buy/Bullish Break H1 candidates found on {target}.")
    else:
        output = output.sort_values(["bar_timestamp", "ticker"])
        print(output.to_string(index=False))
    print(
        f"\nReplay date={target} universe={len(tickers)} fetched={len(stock_data)} "
        f"candidates={len(output)}"
    )
    print("Read-only: no Telegram message and no alert/state write was performed.")
    if args.csv:
        Path(args.csv).parent.mkdir(parents=True, exist_ok=True)
        output.to_csv(args.csv, index=False)
        print(f"CSV written to {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
