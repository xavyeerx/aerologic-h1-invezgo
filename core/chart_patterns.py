"""Deterministic bullish Daily chart-pattern detection.

The rules deliberately model the structural properties of each pattern: pivot
touches, trendline direction, convergence and a close-confirmed breakout. They
do not attempt to predict a pattern before it completes.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from config.settings import CHART_PATTERN_BREAK_BUFFER, CHART_PATTERN_TOUCH_ATR_MULT
from .bar_contract import require_price_signal_eligible


PATTERN_LABELS = {
    "break_base": "Break the Base",
    "sym_triangle_break": "Symmetrical Triangle Breakout",
    "falling_wedge_break": "Falling Wedge Breakout",
    "bullish_pennant": "Bullish Pennant",
}


@dataclass(frozen=True)
class PatternMatch:
    key: str
    resistance: float
    support: float


def _atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    previous = frame["close"].shift(1)
    true_range = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous).abs(),
            (frame["low"] - previous).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.rolling(period).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    relative_strength = gain / loss.replace(0, np.nan)
    result = 100 - (100 / (1 + relative_strength))
    return result.where(loss > 0, 100.0)


def _obv_bullish(frame: pd.DataFrame) -> bool:
    direction = np.sign(frame["close"].diff()).fillna(0.0)
    obv = (direction * frame["volume"]).cumsum()
    return bool(obv.iloc[-1] > obv.ewm(span=20, adjust=False).mean().iloc[-1])


def _pivot_indices(values: np.ndarray, kind: str, radius: int = 2) -> np.ndarray:
    indices: list[int] = []
    for index in range(radius, len(values) - radius):
        window = values[index - radius : index + radius + 1]
        value = values[index]
        if kind == "high" and value == np.max(window) and value > np.min(window):
            indices.append(index)
        elif kind == "low" and value == np.min(window) and value < np.max(window):
            indices.append(index)
    return np.asarray(indices, dtype=float)


def _fit_line(indices: np.ndarray, values: np.ndarray) -> tuple[float, float, float] | None:
    if len(indices) < 2:
        return None
    selected = values[indices.astype(int)]
    slope, intercept = np.polyfit(indices, selected, 1)
    fitted = slope * indices + intercept
    residual = float(np.sum((selected - fitted) ** 2))
    total = float(np.sum((selected - selected.mean()) ** 2))
    r_squared = 1.0 - residual / total if total > 0 else 1.0
    return float(slope), float(intercept), r_squared


def _fresh_breakout(close: pd.Series, resistance_now: float, resistance_previous: float) -> bool:
    buffer = CHART_PATTERN_BREAK_BUFFER
    return bool(
        close.iloc[-2] <= resistance_previous * (1.0 + buffer)
        and close.iloc[-1] > resistance_now * (1.0 + buffer)
    )


def _touch_count(values: np.ndarray, level: float, tolerance: float) -> int:
    return int(np.count_nonzero(np.abs(values - level) <= tolerance))


def _detect_base(frame: pd.DataFrame, atr_value: float) -> PatternMatch | None:
    segment = frame.iloc[-23:-1]
    if len(segment) < 20:
        return None
    resistance = float(segment["high"].max())
    support = float(segment["low"].min())
    midpoint = (resistance + support) / 2.0
    if midpoint <= 0 or (resistance - support) / midpoint > 0.18:
        return None
    tolerance = max(atr_value * CHART_PATTERN_TOUCH_ATR_MULT, resistance * 0.008)
    highs = segment["high"].to_numpy(float)
    lows = segment["low"].to_numpy(float)
    high_pivots = _pivot_indices(highs, "high")
    low_pivots = _pivot_indices(lows, "low")
    if len(high_pivots) < 2 or _touch_count(highs[high_pivots.astype(int)], resistance, tolerance) < 2:
        return None
    if len(low_pivots) < 2 or _touch_count(lows[low_pivots.astype(int)], support, tolerance) < 2:
        return None
    if not _fresh_breakout(frame["close"], resistance, resistance):
        return None
    return PatternMatch("break_base", resistance, support)


def _converging_lines(
    segment: pd.DataFrame,
    *,
    falling: bool,
) -> tuple[float, float, float, float] | None:
    highs = segment["high"].to_numpy(float)
    lows = segment["low"].to_numpy(float)
    high_pivots = _pivot_indices(highs, "high")
    low_pivots = _pivot_indices(lows, "low")
    required_highs, required_lows = ((3, 2) if falling else (2, 2))
    if len(high_pivots) < required_highs or len(low_pivots) < required_lows:
        return None
    high_fit = _fit_line(high_pivots, highs)
    low_fit = _fit_line(low_pivots, lows)
    if high_fit is None or low_fit is None:
        return None
    high_slope, high_intercept, high_r2 = high_fit
    low_slope, low_intercept, low_r2 = low_fit
    if min(high_r2, low_r2) < 0.30:
        return None
    if falling:
        direction_ok = high_slope < low_slope < 0
    else:
        direction_ok = high_slope < 0 < low_slope
    if not direction_ok:
        return None
    start_width = high_intercept - low_intercept
    final_x = float(len(segment))
    previous_x = final_x - 1.0
    final_high = high_slope * final_x + high_intercept
    final_low = low_slope * final_x + low_intercept
    if start_width <= 0 or final_high <= final_low or (final_high - final_low) / start_width > 0.80:
        return None
    previous_high = high_slope * previous_x + high_intercept
    return final_high, final_low, previous_high, min(high_r2, low_r2)


def _detect_triangle(frame: pd.DataFrame, falling: bool) -> PatternMatch | None:
    segment = frame.iloc[-35:-1]
    if len(segment) < 30:
        return None
    lines = _converging_lines(segment, falling=falling)
    if lines is None:
        return None
    resistance, support, previous_resistance, _ = lines
    if not _fresh_breakout(frame["close"], resistance, previous_resistance):
        return None
    key = "falling_wedge_break" if falling else "sym_triangle_break"
    return PatternMatch(key, resistance, support)


def _detect_pennant(frame: pd.DataFrame) -> PatternMatch | None:
    consolidation_length = 12
    impulse_length = 20
    if len(frame) < consolidation_length + impulse_length + 2:
        return None
    consolidation = frame.iloc[-(consolidation_length + 1) : -1]
    impulse = frame.iloc[-(consolidation_length + impulse_length + 1) : -(consolidation_length + 1)]
    impulse_low = float(impulse["low"].min())
    impulse_high = float(impulse["high"].max())
    if impulse_low <= 0 or (impulse_high - impulse_low) / impulse_low < 0.055:
        return None
    # The pole must finish near its high and before the consolidation starts.
    if float(impulse["close"].iloc[-1]) < impulse_low + 0.70 * (impulse_high - impulse_low):
        return None
    resistance = float(consolidation["high"].max())
    support = float(consolidation["low"].min())
    if (resistance - support) / float(frame["close"].iloc[-1]) > 0.10:
        return None
    lines = _converging_lines(consolidation, falling=False)
    if lines is None:
        return None
    resistance, support, previous_resistance, _ = lines
    if not _fresh_breakout(frame["close"], resistance, previous_resistance):
        return None
    return PatternMatch("bullish_pennant", resistance, support)


def detect_bullish_chart_patterns(frame: pd.DataFrame) -> list[PatternMatch]:
    """Return completed patterns on the final bar; incomplete setups are omitted."""
    if frame is None or len(frame) < 60:
        return []
    require_price_signal_eligible(frame)
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(frame.columns) or frame[list(required)].tail(60).isna().any().any():
        return []
    if (frame[["open", "high", "low", "close", "volume"]].tail(60) < 0).any().any():
        return []
    # Avoid obvious split/reverse-split discontinuities becoming false patterns.
    if frame["close"].pct_change().tail(60).abs().max() > 0.60:
        return []
    volume_average = float(frame["volume"].iloc[-21:-1].mean())
    if volume_average <= 0 or float(frame["volume"].iloc[-1]) < volume_average:
        return []
    if not _obv_bullish(frame):
        return []
    atr_value = float(_atr(frame).iloc[-1])
    if not np.isfinite(atr_value) or atr_value <= 0:
        return []

    matches = [
        _detect_base(frame, atr_value),
        _detect_triangle(frame, falling=False),
        _detect_triangle(frame, falling=True),
        _detect_pennant(frame),
    ]
    return [match for match in matches if match is not None]


def pattern_metrics(frame: pd.DataFrame) -> dict[str, float]:
    """Metrics rendered in the review; RSI is informational, never a gate."""
    close = float(frame["close"].iloc[-1])
    previous = float(frame["close"].iloc[-2])
    average_volume = float(frame["volume"].iloc[-21:-1].mean())
    return {
        "close": close,
        "change_pct": ((close / previous) - 1.0) * 100.0 if previous else 0.0,
        "volume_ratio": float(frame["volume"].iloc[-1]) / average_volume if average_volume else 0.0,
        "rsi14": float(_rsi(frame["close"]).iloc[-1]),
        "turnover5": float((frame["close"] * frame["volume"]).tail(5).mean()),
    }
