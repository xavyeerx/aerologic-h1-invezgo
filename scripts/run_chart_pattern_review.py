"""Manual Daily chart-pattern review runner."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.chart_pattern_review import run_daily_chart_pattern_review


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Build review without Telegram send")
    parser.add_argument("--force", action="store_true", help="Ignore completion state")
    parser.add_argument("--limit", type=int, help="Override universe size for smoke tests")
    parser.add_argument(
        "--use-latest-bar",
        action="store_true",
        help="Dry-run against the latest available market candle (weekend/holiday testing)",
    )
    args = parser.parse_args()
    if args.use_latest_bar and not args.dry_run:
        parser.error("--use-latest-bar wajib dipakai bersama --dry-run")
    outcome = run_daily_chart_pattern_review(
        force=args.force,
        send=not args.dry_run,
        use_latest_available_bar=args.use_latest_bar,
        universe_limit=args.limit,
    )
    print(
        f"status={outcome.status} universe={outcome.universe_size} "
        f"analyzed={outcome.analyzed} bootstrap={outcome.bootstrapped} matches={outcome.matches}"
    )
    if args.dry_run:
        for message in outcome.messages:
            print("\n" + message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
