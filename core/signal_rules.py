# ============================================
# REGIME-ADAPTIVE STRONG BUY THRESHOLDS
# ============================================
# Pasar BEAR/SIDEWAYS: skor momentum & posisi EMA cenderung rendah —
# longgarkan gate agar sinyal reversal dini (ST flip / engulf / div) tetap lolos.

from __future__ import annotations

_DEFAULT = {
    "engulf_min_score": 38,
    "breakout_min_score": 52,
    "st_min_score": 50,
    "div_min_score": 35,
    "require_adx_breakout": True,
    "require_bullish_trend_engulf": False,
    "require_bullish_trend_breakout": False,
    "st_use_spike_volume": True,
    "enable_counter_trend": False,
    "counter_trend_min_change_pct": 2.0,
    "counter_trend_min_score": 28,
    "counter_trend_min_vol": 1.2,
}

_PROFILES: dict[str, dict] = {
    "BULL": {
        "engulf_min_score": 40,
        "breakout_min_score": 60,
        "st_min_score": 60,
        "div_min_score": 45,
        "require_adx_breakout": True,
        "require_bullish_trend_engulf": True,
        "require_bullish_trend_breakout": True,
        "st_use_spike_volume": True,
        "enable_counter_trend": False,
    },
    "BEAR": {
        "engulf_min_score": 26,
        "breakout_min_score": 42,
        "st_min_score": 28,
        "div_min_score": 25,
        "require_adx_breakout": False,
        "require_bullish_trend_engulf": False,
        "require_bullish_trend_breakout": False,
        "st_use_spike_volume": False,
        "enable_counter_trend": True,
        "counter_trend_min_change_pct": 1.2,
        "counter_trend_min_score": 22,
        "counter_trend_min_vol": 1.15,
    },
    "SIDEWAYS": {
        "engulf_min_score": 35,
        "breakout_min_score": 50,
        "st_min_score": 45,
        "div_min_score": 32,
        "require_adx_breakout": True,
        "require_bullish_trend_engulf": False,
        "require_bullish_trend_breakout": False,
        "st_use_spike_volume": True,
        "enable_counter_trend": False,  # nonaktif — hanya BEAR yang pakai counter-trend
        "counter_trend_min_change_pct": 1.5,
        "counter_trend_min_score": 25,
        "counter_trend_min_vol": 1.2,
    },
    "UNKNOWN": _DEFAULT,
}


def strong_buy_regime_profile(regime: str | None) -> dict:
    key = (regime or "UNKNOWN").upper()
    base = dict(_DEFAULT)
    base.update(_PROFILES.get(key, _DEFAULT))
    return base


def has_early_reversal_bias(
    latest,
    *,
    is_bullish_trend: bool,
    is_st_flip: bool,
    require_full_trend: bool,
) -> bool:
    """Trend penuh (BULL) vs reversal dini (BEAR/SIDEWAYS)."""
    if require_full_trend:
        return is_bullish_trend
    return bool(
        is_bullish_trend
        or is_st_flip
        or latest.get("price_above_ema20", False)
    )


def has_reversal_candle(latest) -> bool:
    """Pola candle bullish (engulf, hammer, morning star)."""
    return bool(
        latest.get("bullish_engulfing", False)
        or latest.get("is_hammer", False)
        or latest.get("morning_star", False)
    )


def has_momentum_trigger(latest) -> bool:
    """Trigger teknikal selain pola candle."""
    return bool(
        latest.get("macd_cross_up", False)
        or latest.get("stoch_k_cross_up", False)
        or latest.get("obv_bullish", False)
        or latest.get("price_above_ema20", False)
    )


def counter_trend_strong_buy(
    *,
    change_percent: float,
    score: int,
    vol_ratio: float,
    latest,
    is_st_flip: bool,
    is_price_breakout: bool,
    profile: dict,
    market_momentum_5d: float = 0.0,
) -> bool:
    """
    BEAR/SIDEWAYS: saham hijau + volume saat IHSG lemah (relative strength harian).
    Tidak wajib event fresh (ST/breakout) — tangkap pemimpin bounce lebih dini.
    """
    if not profile.get("enable_counter_trend"):
        return False
    min_chg = float(profile.get("counter_trend_min_change_pct", 2.0))
    min_score = int(profile.get("counter_trend_min_score", 28))
    min_vol = float(profile.get("counter_trend_min_vol", 1.2))

    if change_percent < min_chg or vol_ratio < min_vol or score < min_score:
        return False

    # Outperform IHSG: kalau index turun, saham harus cukup hijau
    if market_momentum_5d < -1.0 and change_percent < min_chg + 0.5:
        return False

    return bool(
        is_st_flip
        or is_price_breakout
        or has_reversal_candle(latest)
        or has_momentum_trigger(latest)
    )
