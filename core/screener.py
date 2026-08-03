from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, time as dtime
from typing import Optional

import pytz

from .data_provider import InvezgoError, run_screener
from .market_session import expected_daily_volume_fraction

logger = logging.getLogger(__name__)
WIB = pytz.timezone("Asia/Jakarta")

MAX_CANDIDATES = 30
MIN_AVG_VALUE_20 = 5_000_000_000
LANE_CAPS = {"momentum": 18, "constructive": 6, "reversal": 6}
SCREEN_VOLUME_MIN_FACTOR = float(os.getenv("SCREEN_VOLUME_MIN_FACTOR", "0.005"))


@dataclass(frozen=True)
class ScreenWindow:
    label: str
    vol_factor: float   # computed absolute factor for screener formula (set by current_window)
    require_positive: bool
    cap_15: bool


_DEFAULT_WINDOW = ScreenWindow("default", 0.0, False, False)

def current_window(now: Optional[datetime] = None) -> ScreenWindow:
    """Hitung ScreenWindow dengan vol_factor dinamis (expected_fraction × vol_ratio).

    Menghasilkan window secara dinamis setiap 5 menit dengan curve ratio yang menurun
    perlahan dari 5.0x di pagi hari (09:00) hingga 2.0x di sore hari (16:00) menyesuaikan 
    tingkat keramaian pasar (market pace).
    """
    now = now or datetime.now(WIB)
    t = now.timetz().replace(tzinfo=None)
    
    if t < dtime(9, 0) or t > dtime(16, 15):
        return _DEFAULT_WINDOW

    # Hitung elapsed trading minutes (max 330 menit pada 16:00)
    if t < dtime(12, 0):
        mins = (t.hour - 9) * 60 + t.minute
    elif t < dtime(13, 30):
        mins = 180
    else:
        mins = 180 + (t.hour - 13) * 60 + t.minute - 30
        
    # Curve ratio (piecewise linear decay dari 5.0 -> 2.0)
    if mins <= 30:
        ratio = 5.0 - (mins / 30.0) * 1.0         # 0..30m: 5.0 -> 4.0
    elif mins <= 60:
        ratio = 4.0 - ((mins - 30) / 30.0) * 0.8  # 30..60m: 4.0 -> 3.2
    elif mins <= 120:
        ratio = 3.2 - ((mins - 60) / 60.0) * 0.6  # 60..120m: 3.2 -> 2.6
    elif mins <= 180:
        ratio = 2.6 - ((mins - 120) / 60.0) * 0.3 # 120..180m: 2.6 -> 2.3
    else:
        ratio = 2.3 - ((mins - 180) / 150.0) * 0.3 # 180..330m: 2.3 -> 2.0
        
    ratio = max(2.0, round(ratio, 2))
    
    # Build 5-minute block label (contoh: 09:05-09:10)
    block_start_min = (t.minute // 5) * 5
    start_dt = datetime.combine(now.date(), dtime(t.hour, block_start_min))
    end_dt = start_dt + timedelta(minutes=5)
    label = f"{start_dt.strftime('%H:%M')}-{end_dt.strftime('%H:%M')}"
    
    # Syarat tambahan pagi hari
    require_positive = mins < 20
    cap_15 = mins < 15
    
    expected = expected_daily_volume_fraction(now)
    factor = max(SCREEN_VOLUME_MIN_FACTOR, expected * ratio)
    return ScreenWindow(label, round(factor, 4), require_positive, cap_15)


def build_formula(win: ScreenWindow) -> str:
    parts = [
        f'volume > avg("volume",20) * {win.vol_factor}',
        f'avg("value",20) > {MIN_AVG_VALUE_20}',
        "change_pct > -8",
        "change_pct < 15",
    ]
    return " && ".join(parts)


def _number(row: dict, key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key, default))
    except (TypeError, ValueError):
        return default


def _volume_ratio(row: dict) -> float:
    volume = row.get("volume")
    if volume is None:
        return 0.0
    for key, value in row.items():
        if key.startswith('avg("volume",20)') and value:
            try:
                return float(volume) / float(value)
            except (TypeError, ValueError, ZeroDivisionError):
                pass
    try:
        return float(volume)
    except (TypeError, ValueError):
        return 0.0


def _lane_for(row: dict) -> str:
    change_pct = _number(row, "change_pct")
    if change_pct >= 1.0:
        return "momentum"
    if change_pct >= 0.0:
        return "constructive"
    return "reversal"


def allocate_candidate_lanes(rows: list[dict], max_candidates: int = MAX_CANDIDATES) -> list[dict]:
    unique: dict[str, dict] = {}
    for original in rows:
        code = str(original.get("code") or "").strip().upper()
        if not code:
            continue
        candidate = dict(original)
        candidate["code"] = code
        candidate["lane"] = _lane_for(candidate)
        candidate["activity_ratio"] = _volume_ratio(candidate)
        previous = unique.get(code)
        if previous is None or candidate["activity_ratio"] > previous["activity_ratio"]:
            unique[code] = candidate

    ordered = sorted(
        unique.values(),
        key=lambda row: (-row["activity_ratio"], -_number(row, "value"), row["code"]),
    )
    selected: list[dict] = []
    selected_codes: set[str] = set()
    for lane, cap in LANE_CAPS.items():
        for candidate in [row for row in ordered if row["lane"] == lane][:cap]:
            selected.append(candidate)
            selected_codes.add(candidate["code"])

    for candidate in ordered:
        if len(selected) >= max_candidates:
            break
        if candidate["code"] not in selected_codes:
            selected.append(candidate)
            selected_codes.add(candidate["code"])
    return selected[:max_candidates]


def get_candidates(now: Optional[datetime] = None) -> tuple[list[str], ScreenWindow, dict]:
    """Return (codes, window, screener_prices).

    screener_prices: {ticker: {"close": float, "change_pct": float}} — harga
    realtime dari response screener yang lebih fresh daripada candle daily terakhir.
    Dipakai scanner untuk override result.price / result.change_percent.
    """
    win = current_window(now)
    formula = build_formula(win)
    logger.info("Screener [%s] formula: %s", win.label, formula)

    rows = run_screener(formula)
    logger.info("Screener [%s]: %d kandidat lolos", win.label, len(rows))

    picked = allocate_candidate_lanes(rows, MAX_CANDIDATES)
    codes = [row["code"] for row in picked if row.get("code")]
    dropped = max(0, len(rows) - len(codes))
    logger.info(
        "[SLOT] window=%s candidates=%d picked=%d dropped_by_cap=%d",
        win.label,
        len(rows),
        len(codes),
        dropped,
    )
    logger.info(
        "[LANES] momentum=%d constructive=%d reversal=%d",
        sum(row["lane"] == "momentum" for row in picked),
        sum(row["lane"] == "constructive" for row in picked),
        sum(row["lane"] == "reversal" for row in picked),
    )

    # Kumpulkan harga realtime dari response screener untuk setiap kandidat.
    # Field 'close' dan 'change_pct' sudah di-compute server-side Invezgo
    # (tick terakhir sesi berjalan) — jauh lebih fresh dari candle daily terakhir.
    screener_prices: dict = {}
    for row in picked:
        code = row.get("code")
        if not code:
            continue
        try:
            close = float(row["close"]) if row.get("close") is not None else None
            change_pct = float(row["change_pct"]) if row.get("change_pct") is not None else None
        except (TypeError, ValueError):
            continue
        if close is not None:
            screener_prices[code] = {"close": close, "change_pct": change_pct or 0.0}

    return codes, win, screener_prices
