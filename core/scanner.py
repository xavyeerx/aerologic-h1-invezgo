import logging
import math
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import pytz

from config.settings import *
from .arb_filter import apply_post_alert_arb_gate
from .data_fetcher import compute_session_change_percent
from .indicators import calculate_all_indicators
from .scoring import calculate_total_score
from .signal_engine import (
    SignalFeatures,
    is_momentum_expansion,
    is_selling_climax_reversal,
)

logger = logging.getLogger(__name__)
WIB = pytz.timezone("Asia/Jakarta")


class ScanResult:
    """Container for one stock scan result."""

    def __init__(self, ticker: str):
        self.ticker = ticker
        self.signal_id = None
        self.price = 0.0
        self.change_percent = 0.0
        self.score = 0
        self.status = "UNKNOWN"
        self.status_emoji = "⚪"
        self.is_strong_buy = False
        self.is_early_entry = False
        self.is_reversal_watch = False
        self.early_entry_strength = 0
        self.correction_percent = 0.0
        self.is_bullish = False
        self.is_momentum_expansion = False
        self.signal_family = "NONE"
        self.tp1 = 0.0
        self.tp2 = 0.0
        self.tp2_source = "ATR"
        self.tp_swing = 0.0
        self.volume_ratio = 0.0
        self.stoch_k = 0.0
        self.stoch_d = 0.0
        self.rsi = 50.0
        self.daily_turnover = 0.0
        self.avg_turnover_5d = 0.0
        self.return20_pct = 0.0
        self.market_regime = "UNKNOWN"
        self.adx = 0.0
        self.macd_status = ""
        self.obv_status = ""
        self.pattern_name = ""
        self.divergence_status = ""
        self.is_trending = False
        self.support = 0.0
        self.resistance = 0.0
        self.atr_pct = 0.0
        self.is_bullish_engulfing = False
        self.is_counter_trend = False
        self.is_supertrend_flip = False
        self.is_bullish_break = False
        self.is_supertrend_bounce = False
        self.supertrend_value = 0.0
        self.is_st_continuation = False
        self.bars_since_breakout = 0
        self.price_vs_supertrend_pct = 0.0


def _macd_status(latest: pd.Series) -> str:
    if latest.get("macd_cross_up", False):
        return "CROSS UP"
    if latest.get("macd_cross_down", False):
        return "CROSS DOWN"
    if latest.get("macd_bullish", False):
        return "BULL"
    return "BEAR"


def _candle_features(latest: pd.Series) -> tuple[bool, float, float, float, float]:
    candle_open = float(latest.get("open", latest.get("close", 0.0)) or 0.0)
    candle_high = float(latest.get("high", latest.get("close", 0.0)) or 0.0)
    candle_low = float(latest.get("low", latest.get("close", 0.0)) or 0.0)
    candle_close = float(latest.get("close", 0.0) or 0.0)
    candle_range = candle_high - candle_low
    bullish_body = candle_close > candle_open
    if candle_range <= 0:
        return bullish_body, 0.0, 0.0, 1.0, 0.0
    close_location = (candle_close - candle_low) / candle_range
    body_fraction = (candle_close - candle_open) / candle_range
    upper_wick_fraction = (candle_high - candle_close) / candle_range
    lower_wick_fraction = (min(candle_open, candle_close) - candle_low) / candle_range
    return (
        bullish_body,
        close_location,
        body_fraction,
        upper_wick_fraction,
        lower_wick_fraction,
    )


def _idx_tick_size(price: float) -> float:
    """Return the IDX price fraction applicable around ``price``."""
    if price < 200:
        return 1.0
    if price < 500:
        return 2.0
    if price < 2_000:
        return 5.0
    if price < 5_000:
        return 10.0
    return 25.0


def _next_idx_price_above(price: float) -> float:
    """Return the first valid IDX price fraction strictly above an indicator line."""
    tick = _idx_tick_size(price)
    return (math.floor(price / tick) + 1) * tick


def _is_bullish_supertrend_break(df: pd.DataFrame, current_price: float) -> bool:
    """Detect the first move from below the bearish ST line to one tick above it."""
    if len(df) < 2 or current_price <= 0:
        return False
    previous = df.iloc[-2]
    latest = df.iloc[-1]
    previous_close = float(previous.get("close", 0.0) or 0.0)
    previous_line = float(previous.get("supertrend", 0.0) or 0.0)
    break_line = float(
        latest.get("st_upper_band", latest.get("supertrend", 0.0)) or 0.0
    )
    if previous_line <= 0 or break_line <= 0 or previous_close > previous_line:
        return False
    return current_price >= _next_idx_price_above(break_line)


def _is_bullish_supertrend_bounce(df: pd.DataFrame, current_price: float) -> bool:
    """Detect a one-tick reclaim after testing an established bullish ST line."""
    if len(df) < 2 or current_price <= 0:
        return False
    previous = df.iloc[-2]
    latest = df.iloc[-1]
    if int(previous.get("direction", 0) or 0) != 1:
        return False
    if int(latest.get("direction", 0) or 0) != 1:
        return False
    bullish_line = float(
        latest.get("st_lower_band", latest.get("supertrend", 0.0)) or 0.0
    )
    latest_low = float(latest.get("low", 0.0) or 0.0)
    if bullish_line <= 0 or latest_low <= 0:
        return False
    trigger_price = _next_idx_price_above(bullish_line)
    tested_line = latest_low <= trigger_price
    reclaimed_one_tick = current_price >= trigger_price
    return tested_line and reclaimed_one_tick


def _is_strong_buy(
    momentum_expansion: bool,
    supertrend_bounce: bool,
    change_percent: float,
) -> bool:
    return bool(
        (momentum_expansion or supertrend_bounce)
        and change_percent <= STRONG_BUY_MAX_CHANGE_PCT
    )


def analyze_stock(
    ticker: str,
    df: pd.DataFrame,
    previous_state: dict = None,
    state_manager=None,
    market_regime: str = "UNKNOWN",
    market_momentum_5d: float = 0.0,
    now: Optional[datetime] = None,
    screener_price: Optional[dict] = None,
) -> ScanResult:
    result = ScanResult(ticker)
    result.market_regime = (market_regime or "UNKNOWN").upper()

    if df is None or len(df) < 50:
        return result

    try:
        df = df.copy()
        df["turnover"] = df["close"] * df["volume"]
        trade_dates = pd.DatetimeIndex(df.index).date
        turnover_by_day = df["turnover"].groupby(trade_dates).sum()
        result.daily_turnover = float(turnover_by_day.iloc[-1])
        completed_days = turnover_by_day.iloc[:-1]
        result.avg_turnover_5d = float(
            completed_days.tail(5).mean()
            if not completed_days.empty
            else turnover_by_day.tail(5).mean()
        )

        df = calculate_all_indicators(df)
        latest = df.iloc[-1]

        result.price = float(latest.get("close", 0.0) or 0.0)
        # direction==1 (bullish supertrend) adalah primary signal;
        # EMA alignment/price_above_ema50 sebagai fallback jika ST belum valid
        st_direction = int(latest.get("direction", 0))
        result.is_bullish = bool(
            st_direction == 1
            or latest.get("ema_bullish_alignment", False)
            or latest.get("price_above_ema50", False)
        )
        result.supertrend_value = float(
            latest.get("st_upper_band", latest.get("supertrend", 0.0)) or 0.0
        )
        result.price_vs_supertrend_pct = float(latest.get("price_vs_supertrend_pct", 0.0) or 0.0)
        result.volume_ratio = float(latest.get("volume_ratio", 0.0) or 0.0)
        result.stoch_k = float(latest.get("stoch_k", 50.0) or 50.0)
        result.stoch_d = float(latest.get("stoch_d", 50.0) or 50.0)
        result.rsi = float(latest.get("rsi", 50.0) or 50.0)
        result.tp1 = float(latest.get("tp1", 0.0) or 0.0)
        result.tp2 = float(latest.get("tp2", 0.0) or 0.0)
        result.tp2_source = latest.get("tp2_source", "ATR")
        result.tp_swing = result.tp2
        result.adx = float(latest.get("adx", 0.0) or 0.0)
        result.is_trending = bool(latest.get("is_trending", False))
        result.support = float(latest.get("support", 0.0) or 0.0)
        result.resistance = float(latest.get("resistance", 0.0) or 0.0)
        result.atr_pct = round(float(latest.get("atr_percent", 0.0) or 0.0), 2)
        result.macd_status = _macd_status(latest)
        result.obv_status = "ACC" if latest.get("obv_bullish", False) else "DIST"
        result.pattern_name = latest.get("pattern_name", "")
        result.is_bullish_engulfing = bool(latest.get("bullish_engulfing", False))
        result.divergence_status = "BEAR DIV" if latest.get("bearish_divergence", False) else ""
        result.change_percent = compute_session_change_percent(df, ticker)
        result.score, result.status, result.status_emoji = calculate_total_score(df)

        # Override harga & change_pct dengan data realtime dari screener —
        # lebih fresh daripada close candle daily terakhir.
        # Analisis teknikal tetap pakai daily candle.
        if screener_price:
            sp_close = screener_price.get("close")
            sp_change = screener_price.get("change_pct")
            if sp_close and sp_close > 0:
                result.price = float(sp_close)
                logger.debug("[%s] price override: Daily=%.0f → screener=%.0f",
                             ticker, float(latest.get("close", 0) or 0), result.price)
            if sp_change is not None:
                result.change_percent = float(sp_change)

        result.is_bullish_break = _is_bullish_supertrend_break(df, result.price)
        result.is_supertrend_flip = result.is_bullish_break
        result.is_supertrend_bounce = _is_bullish_supertrend_bounce(df, result.price)

        candle_close = result.price
        close20 = float(df["close"].iloc[-21]) if len(df) >= 21 else 0.0
        result.return20_pct = (candle_close / close20 - 1.0) * 100.0 if close20 > 0 else 0.0
        (
            bullish_body,
            close_location,
            body_fraction,
            upper_wick_fraction,
            lower_wick_fraction,
        ) = _candle_features(latest)

        signal_features = SignalFeatures(
            market_regime=result.market_regime,
            close=candle_close,
            ema20=float(latest.get("ema20", candle_close)),
            ema50=float(latest.get("ema50", candle_close)),
            return20_pct=result.return20_pct,
            volume_ratio=result.volume_ratio,
            rsi=result.rsi,
            bullish_body=bullish_body,
            close_location=close_location,
            body_fraction=body_fraction,
            upper_wick_fraction=upper_wick_fraction,
            lower_wick_fraction=lower_wick_fraction,
        )

        result.is_momentum_expansion = is_momentum_expansion(
            signal_features,
            min_return20=CONTINUATION_MIN_RETURN20,
            min_volume_ratio=CONTINUATION_MIN_VOLUME_RATIO,
        )
        result.is_reversal_watch = is_selling_climax_reversal(
            signal_features,
            max_return20=REVERSAL_MAX_RETURN20,
            max_rsi=REVERSAL_MAX_RSI,
            min_volume_ratio=REVERSAL_MIN_VOLUME_RATIO,
        )
        result.is_strong_buy = _is_strong_buy(
            result.is_momentum_expansion,
            result.is_supertrend_bounce,
            result.change_percent,
        )
        result.signal_family = (
            "SUPERTREND_BOUNCE"
            if result.is_supertrend_bounce
            else "MOMENTUM_EXPANSION"
            if result.is_momentum_expansion
            else "SELLING_CLIMAX_REVERSAL"
            if result.is_reversal_watch
            else "NONE"
        )

        if len(df) >= 2:
            prev_close = float(df["close"].iloc[-2])
            drop_from_prev_close = (
                ((prev_close - candle_close) / prev_close) * 100.0 if prev_close > 0 else 0.0
            )
        else:
            drop_from_prev_close = 0.0

        is_healthy_correction = bool(latest.get("is_healthy_correction", False))
        result.correction_percent = drop_from_prev_close
        is_dry_correction = (3 <= drop_from_prev_close <= 12) and is_healthy_correction

        if len(df) >= 2:
            no_lower_low = float(df["low"].iloc[-1]) >= float(df["low"].iloc[-2])
            today_range = (float(df["high"].iloc[-1]) - float(df["low"].iloc[-1])) / candle_close * 100.0
            yesterday_range = (
                (float(df["high"].iloc[-2]) - float(df["low"].iloc[-2])) / float(df["close"].iloc[-2]) * 100.0
            )
            range_shrinking = today_range < yesterday_range
            low_diff = abs(float(df["low"].iloc[-1]) - float(df["low"].iloc[-2])) / candle_close * 100.0
            price_defended = low_diff < 1.5
            volume_increasing = float(df["volume"].iloc[-1]) > float(df["volume"].iloc[-2])
            price_stable_or_up = candle_close >= float(df["close"].iloc[-2])
        else:
            no_lower_low = False
            range_shrinking = False
            price_defended = False
            volume_increasing = False
            price_stable_or_up = False

        is_price_holding = no_lower_low or price_defended or range_shrinking
        is_green_candle = bullish_body
        has_wick_rejection = lower_wick_fraction > body_fraction * 0.5 if body_fraction > 0 else False
        has_early_buying = volume_increasing or price_stable_or_up or is_green_candle or has_wick_rejection

        result.early_entry_strength = sum(
            [
                is_dry_correction,
                no_lower_low,
                price_defended,
                range_shrinking,
                volume_increasing,
                is_green_candle,
                has_wick_rejection,
            ]
        )
        if (
            result.is_bullish
            and is_dry_correction
            and (is_price_holding or has_early_buying)
        ):
            result.is_early_entry = True

        apply_post_alert_arb_gate(result, df, state_manager)

    except Exception as exc:
        logger.error("Error analyzing %s: %s", ticker, exc)

    return result


def _analyze_stock_job(args: tuple) -> tuple:
    ticker, df, prev_state, market_regime, market_momentum_5d, now, screener_price = args
    return ticker, analyze_stock(
        ticker,
        df,
        prev_state,
        state_manager=None,
        market_regime=market_regime,
        market_momentum_5d=market_momentum_5d,
        now=now,
        screener_price=screener_price,
    )


def log_signal_diagnostics(results: Dict[str, ScanResult], market_regime: str) -> None:
    if not results:
        return
    logger.info(
        "Signal diagnostics (%s): strong_buy=%d early_entry=%d reversal_watch=%d",
        market_regime,
        sum(1 for r in results.values() if r.is_strong_buy),
        sum(1 for r in results.values() if r.is_early_entry),
        sum(1 for r in results.values() if r.is_reversal_watch),
    )


def scan_all_stocks(
    stock_data: Dict[str, pd.DataFrame],
    previous_states: dict = None,
    state_manager=None,
    market_regime: str = "UNKNOWN",
    market_momentum_5d: float = 0.0,
    screener_prices: Optional[dict] = None,
) -> Dict[str, ScanResult]:
    results: Dict[str, ScanResult] = {}
    previous_states = previous_states or {}
    screener_prices = screener_prices or {}
    now = datetime.now(WIB)
    items = [
        (
            ticker, df, previous_states.get(ticker, {}),
            market_regime, market_momentum_5d, now,
            screener_prices.get(ticker),
        )
        for ticker, df in stock_data.items()
    ]
    workers = int(SCAN_ANALYZE_WORKERS)
    analyze_t0 = time.perf_counter()

    if workers > 1 and len(items) >= workers * 2:
        logger.info("Parallel analyze: %d stocks, %d workers", len(items), workers)
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for ticker, result in pool.map(_analyze_stock_job, items, chunksize=24):
                results[ticker] = result
    else:
        for ticker, df, prev_state, regime, mom5d, now_, sp in items:
            results[ticker] = analyze_stock(
                ticker,
                df,
                prev_state,
                state_manager=None,
                market_regime=regime,
                market_momentum_5d=mom5d,
                now=now_,
                screener_price=sp,
            )

    if state_manager is not None:
        for ticker, result in results.items():
            df = stock_data.get(ticker)
            if df is not None:
                apply_post_alert_arb_gate(result, df, state_manager)

    log_signal_diagnostics(results, market_regime)
    logger.info(
        "Analyze duration: %.1fs (%d stocks, workers=%d)",
        time.perf_counter() - analyze_t0,
        len(results),
        workers if workers > 1 else 1,
    )
    return results


def filter_signals(results: Dict[str, ScanResult]) -> Dict[str, List[ScanResult]]:
    signals = {
        "bullish_break": [],
        "strong_buy": [],
        "early_entry": [],
        "reversal_watch": [],
    }
    for result in results.values():
        # A fresh Supertrend break is mandatory for every scanned ticker and is
        # intentionally not gated by the liquidity filters of other signals.
        if result.is_bullish_break:
            signals["bullish_break"].append(result)
        if result.avg_turnover_5d < MIN_DAILY_TURNOVER:
            continue
        if result.is_strong_buy:
            signals["strong_buy"].append(result)
        if result.is_early_entry:
            signals["early_entry"].append(result)
        if REVERSAL_WATCH_ALERT_ENABLED and result.is_reversal_watch:
            signals["reversal_watch"].append(result)
    return signals


def filter_all_current_signals(results: Dict[str, ScanResult], state_manager=None) -> Dict[str, List[ScanResult]]:
    categories = {
        "strong_buy": [],
        "early_entry": [],
        "bullish": [],
        "reversal_watch": [],
    }

    def _is_done(ticker, signal_type):
        return state_manager is not None and state_manager.is_signal_done(ticker, signal_type)

    for ticker, result in results.items():
        if result.avg_turnover_5d < MIN_DAILY_TURNOVER:
            continue
        if result.is_strong_buy and not _is_done(ticker, "strong_buy"):
            categories["strong_buy"].append(result)
        elif result.is_bullish and result.score >= ACCUMULATE_THRESHOLD:
            categories["bullish"].append(result)
        if result.is_early_entry and not _is_done(ticker, "early_entry"):
            categories["early_entry"].append(result)
        if result.is_reversal_watch and not _is_done(ticker, "reversal_watch"):
            categories["reversal_watch"].append(result)

    for key in categories:
        categories[key] = sorted(categories[key], key=lambda x: x.score, reverse=True)
    return categories


def has_any_signal(signals: Dict[str, List[ScanResult]]) -> bool:
    return any(len(v) > 0 for v in signals.values())
