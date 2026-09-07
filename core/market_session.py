"""IDX regular-market schedule and empirically observed intraday volume seasonality."""

from __future__ import annotations

from datetime import date, datetime, time as dtime

import pandas as pd


# Median share of final daily volume per Invezgo 60-minute bucket.
# Research sample: 10 liquid IDX stocks, 2026-06-15..2026-07-17 (230 stock-days).
# Keep this configurable/re-estimable; it is a candidate-generation prior, not a
# trading rule. Stock-specific normalization happens against Daily chart context.
VOLUME_PROFILE_MON_THU = {
    8: 0.0140,
    9: 0.2481,
    10: 0.1241,
    11: 0.0948,
    13: 0.0816,
    14: 0.1275,
    15: 0.1834,
    16: 0.1266,
}
VOLUME_PROFILE_FRIDAY = {
    8: 0.0149,
    9: 0.2604,
    10: 0.1632,
    11: 0.0574,
    14: 0.1818,
    15: 0.1944,
    16: 0.1280,
}


def regular_sessions(day: date) -> tuple[tuple[dtime, dtime], tuple[dtime, dtime]]:
    """Return official IDX regular-market sessions for a weekday (WIB)."""
    if day.weekday() == 4:  # Friday
        return (dtime(9, 0), dtime(11, 30)), (dtime(14, 0), dtime(15, 50))
    return (dtime(9, 0), dtime(12, 0)), (dtime(13, 30), dtime(15, 50))


def is_scan_session(now: datetime, *, include_preopen: bool = True) -> bool:
    """Whether a scan may run now, including the final pre-open matching minute."""
    if now.weekday() >= 5:
        return False
    t = now.timetz().replace(tzinfo=None)
    morning, afternoon = regular_sessions(now.date())
    morning_start = dtime(8, 59, 5) if include_preopen else morning[0]
    # Scan through 16:00 to observe pre-closing input; continuous trading ends 15:49:59.
    return morning_start <= t < morning[1] or afternoon[0] <= t < dtime(16, 0)




def bucket_interval(day: date, hour: int) -> tuple[dtime, dtime] | None:
    """Trading interval represented by an Invezgo hourly bucket label."""
    friday = day.weekday() == 4
    intervals = {
        8: (dtime(8, 58), dtime(9, 0)),
        9: (dtime(9, 0), dtime(10, 0)),
        10: (dtime(10, 0), dtime(11, 0)),
        11: (dtime(11, 0), dtime(11, 30) if friday else dtime(12, 0)),
        14: (dtime(14, 0), dtime(15, 0)),
        15: (dtime(15, 0), dtime(15, 50)),
        16: (dtime(16, 0), dtime(16, 15)),
    }
    if not friday:
        intervals[13] = (dtime(13, 30), dtime(14, 0))
    return intervals.get(hour)


def is_h1_bar_closed(label, now: datetime) -> bool:
    """Whether an Invezgo 60-minute exchange bucket is complete at ``now``."""
    timestamp = pd.Timestamp(label)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(now.tzinfo)
    else:
        timestamp = timestamp.tz_convert(now.tzinfo)
    if timestamp.date() < now.date():
        return True
    if timestamp.date() > now.date() or timestamp.weekday() >= 5:
        return False
    interval = bucket_interval(timestamp.date(), timestamp.hour)
    if interval is None:
        return False
    naive_end = datetime.combine(timestamp.date(), interval[1])
    end = (
        now.tzinfo.localize(naive_end)
        if hasattr(now.tzinfo, "localize")
        else naive_end.replace(tzinfo=now.tzinfo)
    )
    return now >= end


def _interval_progress(now: datetime, interval: tuple[dtime, dtime]) -> float:
    start, end = interval
    day_start = datetime.combine(now.date(), start, tzinfo=now.tzinfo)
    day_end = datetime.combine(now.date(), end, tzinfo=now.tzinfo)
    if now <= day_start:
        return 0.0
    if now >= day_end:
        return 1.0
    return (now - day_start).total_seconds() / (day_end - day_start).total_seconds()


def expected_daily_volume_fraction(now: datetime) -> float:
    """Expected completed share of daily volume at ``now`` from the research prior."""
    if now.weekday() >= 5:
        return 0.0
    profile = VOLUME_PROFILE_FRIDAY if now.weekday() == 4 else VOLUME_PROFILE_MON_THU
    expected = 0.0
    for hour, share in profile.items():
        interval = bucket_interval(now.date(), hour)
        if interval is not None:
            expected += share * _interval_progress(now, interval)
    return min(1.0, max(0.0, expected))
