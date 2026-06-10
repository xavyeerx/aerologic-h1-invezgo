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
    "require_adx_breakout": False,
    "require_bullish_trend_engulf": False,
    "require_bullish_trend_breakout": False,
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
    },
    "BEAR": {
        "engulf_min_score": 30,
        "breakout_min_score": 45,
        "st_min_score": 38,
        "div_min_score": 28,
        "require_adx_breakout": False,
        "require_bullish_trend_engulf": False,
        "require_bullish_trend_breakout": False,
    },
    "SIDEWAYS": {
        "engulf_min_score": 35,
        "breakout_min_score": 50,
        "st_min_score": 45,
        "div_min_score": 32,
        "require_adx_breakout": False,
        "require_bullish_trend_engulf": False,
        "require_bullish_trend_breakout": False,
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
        or latest.get("bullish_divergence", False)
    )
