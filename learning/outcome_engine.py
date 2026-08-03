"""Point-in-time outcome labels for executable five-trading-day opportunities."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

import pandas as pd


@dataclass(frozen=True)
class OutcomePolicy:
    tp_percentages: tuple[float, ...] = (0.5, 1.0, 2.0, 3.0, 5.0)
    primary_tp_percentage: float = 1.0
    stop_percentage: float = 3.0
    max_trading_days: int = 5

    def __post_init__(self):
        if self.primary_tp_percentage not in self.tp_percentages:
            raise ValueError("primary_tp_percentage must be included in tp_percentages")
        if self.stop_percentage <= 0 or self.max_trading_days <= 0:
            raise ValueError("stop_percentage and max_trading_days must be positive")


def _iso_timestamp(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).isoformat()


def evaluate_signal_path(
    bars: pd.DataFrame,
    *,
    entry_price: float,
    entry_at: datetime | pd.Timestamp,
    policy: OutcomePolicy | None = None,
) -> dict:
    """Evaluate future OHLC bars without inventing order inside one bar.

    Bars at or before ``entry_at`` are excluded. Only the first configured number of
    trading dates are inspected. If TP and SL occur inside the same finest available
    bar, the first-hit label remains ``AMBIGUOUS``.
    """
    policy = policy or OutcomePolicy()
    if entry_price <= 0:
        raise ValueError("entry_price must be positive")
    required = {"high", "low", "close"}
    if not required.issubset(bars.columns):
        raise ValueError(f"bars must contain {sorted(required)}")

    path = bars.copy().sort_index()
    path.index = pd.DatetimeIndex(path.index)
    entry_timestamp = pd.Timestamp(entry_at)
    if path.index.tz is not None and entry_timestamp.tzinfo is None:
        entry_timestamp = entry_timestamp.tz_localize(path.index.tz)
    elif path.index.tz is None and entry_timestamp.tzinfo is not None:
        entry_timestamp = entry_timestamp.tz_localize(None)
    path = path[path.index > entry_timestamp]

    trading_dates = list(dict.fromkeys(path.index.date))[: policy.max_trading_days]
    path = path[[day in trading_dates for day in path.index.date]]
    targets = {
        percentage: entry_price * (1.0 + percentage / 100.0)
        for percentage in policy.tp_percentages
    }
    stop_price = entry_price * (1.0 - policy.stop_percentage / 100.0)
    touched_at: dict[float, pd.Timestamp | None] = {percentage: None for percentage in targets}
    first_hit = "EXPIRED"
    first_tp_at = None
    first_sl_at = None
    primary_target = targets[policy.primary_tp_percentage]

    max_favorable_price = entry_price
    max_adverse_price = entry_price
    for timestamp, row in path.iterrows():
        high = float(row["high"])
        low = float(row["low"])
        max_favorable_price = max(max_favorable_price, high)
        max_adverse_price = min(max_adverse_price, low)
        for percentage, target in targets.items():
            if touched_at[percentage] is None and high >= target:
                touched_at[percentage] = timestamp

        if first_hit != "EXPIRED":
            continue
        tp_touched = high >= primary_target
        sl_touched = low <= stop_price
        if tp_touched and sl_touched:
            first_hit = "AMBIGUOUS"
            first_tp_at = timestamp
            first_sl_at = timestamp
        elif tp_touched:
            first_hit = "TP_FIRST"
            first_tp_at = timestamp
        elif sl_touched:
            first_hit = "SL_FIRST"
            first_sl_at = timestamp

    last_close = float(path["close"].iloc[-1]) if not path.empty else entry_price
    return {
        "policy": asdict(policy),
        "bars_observed": len(path),
        "trading_days_observed": len(trading_dates),
        "first_hit": first_hit,
        "first_tp_at": _iso_timestamp(first_tp_at),
        "first_sl_at": _iso_timestamp(first_sl_at),
        "tp_touched": {str(level): _iso_timestamp(at) for level, at in touched_at.items()},
        "mfe_pct": (max_favorable_price / entry_price - 1.0) * 100.0,
        "mae_pct": (max_adverse_price / entry_price - 1.0) * 100.0,
        "last_close_return_pct": (last_close / entry_price - 1.0) * 100.0,
        "barrier_order_quality": "FINEST_BAR_AMBIGUOUS" if first_hit == "AMBIGUOUS" else "OBSERVED",
    }
