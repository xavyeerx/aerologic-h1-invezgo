"""Daily chart-pattern review orchestration with a quota-efficient OHLCV cache."""

from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path
from typing import Callable

import pandas as pd
import pytz

from config.settings import (
    CHART_PATTERN_BOOTSTRAP_LIMIT,
    CHART_PATTERN_CACHE_BARS,
    CHART_PATTERN_HISTORY_DAYS,
    CHART_PATTERN_MIN_TURNOVER,
    CHART_PATTERN_UNIVERSE_LIMIT,
    SCANNER_BUILD_ID,
)
from notifications.telegram_bot import send_telegram_message
from .bar_contract import INVEZGO_DAILY_PATTERN_CONTRACT, attach_bar_contract
from .chart_patterns import PATTERN_LABELS, PatternMatch, detect_bullish_chart_patterns, pattern_metrics
from .data_provider import fetch_chart, fetch_index, run_screener


logger = logging.getLogger(__name__)
WIB = pytz.timezone("Asia/Jakarta")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE_PATH = PROJECT_ROOT / "database" / "chart_pattern_daily_cache.json"
DEFAULT_STATE_PATH = PROJECT_ROOT / "database" / "chart_pattern_review_state.json"

SCREENER_FORMULA = (
    'close > 0 && open > 0 && high > 0 && low > 0 && volume > 0 '
    '&& prev > 0 && sma("value",5) > 0'
)


@dataclass(frozen=True)
class ReviewItem:
    ticker: str
    match: PatternMatch
    metrics: dict[str, float]


@dataclass(frozen=True)
class ReviewOutcome:
    status: str
    universe_size: int
    analyzed: int
    bootstrapped: int
    matches: int
    messages: tuple[str, ...]


def _load_json(path: Path, default: dict) -> dict:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else default
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def _save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
    os.replace(temporary, path)


def _number(row: dict, key: str) -> float:
    try:
        return float(row.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _average_value(row: dict) -> float:
    for key, value in row.items():
        normalized = str(key).lower().replace(" ", "")
        if "sma" in normalized and "value" in normalized:
            try:
                return float(value or 0)
            except (TypeError, ValueError):
                return 0.0
    return _number(row, "value")


def select_liquid_universe(rows: list[dict], limit: int) -> list[dict]:
    """Rank active stocks by Invezgo's 5-day average traded value."""
    valid: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        ticker = str(row.get("code") or "").replace(".JK", "").strip().upper()
        if not ticker or ticker in seen:
            continue
        if min(_number(row, field) for field in ("open", "high", "low", "close", "volume")) <= 0:
            continue
        average_value = _average_value(row)
        if average_value <= 0:
            continue
        normalized = dict(row)
        normalized["code"] = ticker
        normalized["average_value_5d"] = average_value
        valid.append(normalized)
        seen.add(ticker)
    return sorted(valid, key=lambda item: item["average_value_5d"], reverse=True)[:limit]


def _frame_to_records(frame: pd.DataFrame) -> list[dict]:
    output: list[dict] = []
    for timestamp, row in frame.tail(CHART_PATTERN_CACHE_BARS).iterrows():
        output.append(
            {
                "date": pd.Timestamp(timestamp).strftime("%Y-%m-%d"),
                **{field: float(row[field]) for field in ("open", "high", "low", "close", "volume")},
            }
        )
    return output


def _records_to_frame(records: list[dict]) -> pd.DataFrame | None:
    if not records:
        return None
    frame = pd.DataFrame(records)
    required = {"date", "open", "high", "low", "close", "volume"}
    if not required.issubset(frame.columns):
        return None
    frame.index = pd.to_datetime(frame.pop("date"), errors="coerce")
    frame = frame.loc[~frame.index.isna(), ["open", "high", "low", "close", "volume"]]
    for column in frame.columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna().sort_index()
    frame = frame[~frame.index.duplicated(keep="last")].tail(CHART_PATTERN_CACHE_BARS)
    if frame.empty:
        return None
    return attach_bar_contract(frame, INVEZGO_DAILY_PATTERN_CONTRACT)


def _merge_today(frame: pd.DataFrame, row: dict, market_date: date) -> pd.DataFrame:
    current = pd.DataFrame(
        [{field: _number(row, field) for field in ("open", "high", "low", "close", "volume")}],
        index=[pd.Timestamp(market_date)],
    )
    merged = pd.concat([frame, current])
    merged = merged[~merged.index.duplicated(keep="last")].sort_index().tail(CHART_PATTERN_CACHE_BARS)
    return attach_bar_contract(merged, INVEZGO_DAILY_PATTERN_CONTRACT)


def _fetch_histories(tickers: list[str], from_date: str, to_date: str) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    workers = min(4, max(1, len(tickers)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(fetch_chart, ticker, from_date, to_date): ticker for ticker in tickers}
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                frame = future.result()
            except Exception as exc:
                logger.warning("Bootstrap Daily %s gagal: %s", ticker, exc)
                continue
            if frame is not None and not frame.empty:
                frames[ticker] = attach_bar_contract(frame, INVEZGO_DAILY_PATTERN_CONTRACT)
    return frames


def _format_number(value: float) -> str:
    return f"{value:,.0f}".replace(",", ".")


def _format_decimal(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def build_review_messages(
    items: list[ReviewItem],
    now: datetime,
    universe_size: int,
    *,
    market_date: date | None = None,
) -> tuple[str, ...]:
    header = [
        "<b>📐 CHART PATTERNS|</b>",
        f"⏰ {now.strftime('%d %b %Y, %H:%M')} WIB",
        *(
            [f"Data candle: {market_date.strftime('%d %b %Y')}"]
            if market_date is not None and market_date != now.date()
            else []
        ),
        f"Universe: {universe_size} saham terlikuid • build <code>{escape(SCANNER_BUILD_ID)}</code>",
        "Konfirmasi: close breakout • vol ≥ MA20 • OBV &gt; EMA20 • RSI14 info",
        "",
    ]
    grouped: dict[str, list[ReviewItem]] = {key: [] for key in PATTERN_LABELS}
    for item in items:
        grouped[item.match.key].append(item)

    body_lines: list[str] = []
    for key, label in PATTERN_LABELS.items():
        matches = sorted(grouped[key], key=lambda item: item.metrics["volume_ratio"], reverse=True)
        if not matches:
            continue
        if body_lines:
            body_lines.append("")
        body_lines.append(f"<b>{label}</b>")
        for item in matches:
            metrics = item.metrics
            sign = "+" if metrics["change_pct"] >= 0 else ""
            body_lines.append(
                f"• <code>{escape(item.ticker)}</code> | {_format_number(metrics['close'])} "
                f"({sign}{_format_decimal(metrics['change_pct'])}%) | "
                f"Vol {_format_decimal(metrics['volume_ratio'], 2)}× • RSI14 {_format_decimal(metrics['rsi14'])}"
            )
    if not body_lines:
        body_lines.append("Tidak ada pola yang lolos seluruh konfirmasi hari ini.")

    footer = "\n\n<i>Heuristik otomatis setelah candle Daily tersedia. DYOR; bukan rekomendasi beli/jual.</i>"
    messages: list[str] = []
    current = "\n".join(header).rstrip()
    for line in body_lines:
        addition = "\n" + line
        if len(current) + len(addition) + len(footer) > 3900:
            messages.append(current + footer)
            current = "<b>📐 CHART PATTERNS|</b>\n" + line
        else:
            current += addition
    messages.append(current + footer)
    return tuple(messages)


def _already_completed(state_path: Path, market_date: date) -> bool:
    state = _load_json(state_path, {})
    return state.get("last_completed_date") == market_date.isoformat()


def _mark_completed(state_path: Path, market_date: date, outcome: ReviewOutcome) -> None:
    _save_json(
        state_path,
        {
            "last_completed_date": market_date.isoformat(),
            "completed_at": datetime.now(WIB).isoformat(),
            "status": outcome.status,
            "universe_size": outcome.universe_size,
            "analyzed": outcome.analyzed,
            "bootstrapped": outcome.bootstrapped,
            "matches": outcome.matches,
        },
    )


def run_daily_chart_pattern_review(
    now: datetime | None = None,
    *,
    force: bool = False,
    send: bool = True,
    use_latest_available_bar: bool = False,
    universe_limit: int | None = None,
    cache_path: Path = DEFAULT_CACHE_PATH,
    state_path: Path = DEFAULT_STATE_PATH,
    sender: Callable[[str], bool] = send_telegram_message,
) -> ReviewOutcome:
    """Build and optionally send one Daily review.

    Normal recurring cost is two successful Invezgo calls (COMPOSITE + screener).
    Full stock histories are requested only for missing or discontinuous cache rows.
    """
    now = now or datetime.now(WIB)
    if now.tzinfo is None:
        now = WIB.localize(now)
    if use_latest_available_bar and send:
        raise ValueError("use_latest_available_bar hanya diizinkan untuk dry-run")
    market_date = now.date()
    if not force and _already_completed(state_path, market_date):
        return ReviewOutcome("already_completed", 0, 0, 0, 0, ())

    start = (market_date - timedelta(days=CHART_PATTERN_HISTORY_DAYS)).isoformat()
    end = market_date.isoformat()
    index_frame = fetch_index("COMPOSITE", start, end)
    if index_frame is None or index_frame.empty:
        raise RuntimeError("Candle Daily COMPOSITE tidak tersedia; review tidak dikirim")
    latest_market_date = pd.Timestamp(index_frame.index[-1]).date()
    if latest_market_date != market_date and not use_latest_available_bar:
        message = (
            "<b>📐 CHART PATTERNS|</b>\n"
            f"⏰ {now.strftime('%d %b %Y, %H:%M')} WIB\n"
            f"Tidak dijalankan: candle Daily terbaru masih {latest_market_date.isoformat()}."
        )
        outcome = ReviewOutcome("no_fresh_daily_bar", 0, 0, 0, 0, (message,))
        if send and not sender(message):
            raise RuntimeError("Telegram menolak pesan review tanpa candle baru")
        if send:
            _mark_completed(state_path, market_date, outcome)
        return outcome
    if use_latest_available_bar:
        market_date = latest_market_date
    previous_market_date = (
        pd.Timestamp(index_frame.index[-2]).date() if len(index_frame) >= 2 else None
    )

    rows = run_screener(SCREENER_FORMULA)
    limit = universe_limit or CHART_PATTERN_UNIVERSE_LIMIT
    universe = select_liquid_universe(rows, limit)
    if not universe:
        raise RuntimeError("Screener Daily tidak menghasilkan universe likuid")

    cache = _load_json(cache_path, {"version": 1, "stocks": {}})
    stocks = cache.setdefault("stocks", {})
    frames: dict[str, pd.DataFrame] = {}
    missing: list[str] = []
    for row in universe:
        ticker = row["code"]
        frame = _records_to_frame(stocks.get(ticker, []))
        cached_date = pd.Timestamp(frame.index[-1]).date() if frame is not None else None
        if frame is None or len(frame) < 60 or cached_date != previous_market_date:
            missing.append(ticker)
        else:
            frames[ticker] = frame

    bootstrap = missing[:CHART_PATTERN_BOOTSTRAP_LIMIT]
    fetched_histories: dict[str, pd.DataFrame] = {}
    if bootstrap:
        logger.info("Bootstrap/repair cache Daily untuk %d saham", len(bootstrap))
        fetched_histories = _fetch_histories(bootstrap, start, end)
        frames.update(fetched_histories)
    deferred = set(missing) - set(bootstrap)
    if deferred:
        logger.warning("%d saham ditunda karena bootstrap limit", len(deferred))

    analyzed = 0
    items: list[ReviewItem] = []
    for row in universe:
        ticker = row["code"]
        frame = frames.get(ticker)
        if frame is None:
            continue
        frame = _merge_today(frame, row, market_date)
        stocks[ticker] = _frame_to_records(frame)
        if len(frame) < 60:
            continue
        metrics = pattern_metrics(frame)
        # Exact local liquidity gate remains independent of the top-240 ranking.
        if metrics["turnover5"] < CHART_PATTERN_MIN_TURNOVER:
            continue
        analyzed += 1
        for match in detect_bullish_chart_patterns(frame):
            items.append(ReviewItem(ticker, match, metrics))

    cache.update({"version": 1, "updated_at": now.isoformat(), "stocks": stocks})
    _save_json(cache_path, cache)
    messages = build_review_messages(items, now, len(universe), market_date=market_date)
    outcome = ReviewOutcome(
        "completed", len(universe), analyzed, len(fetched_histories), len(items), messages
    )
    if send and outcome.matches > 0:
        for message in messages:
            if not sender(message):
                raise RuntimeError("Telegram menolak pesan chart-pattern review")
    elif send:
        logger.info("Chart-pattern review tidak dikirim: tidak ada pola yang lolos")
    if send:
        _mark_completed(state_path, market_date, outcome)
    logger.info(
        "Chart-pattern review selesai: universe=%d analyzed=%d bootstrap=%d matches=%d",
        outcome.universe_size,
        outcome.analyzed,
        outcome.bootstrapped,
        outcome.matches,
    )
    return outcome
