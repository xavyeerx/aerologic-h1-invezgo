# ============================================
# SCORING SYSTEM v5.0
# ============================================
# Matches Pine Script v5 scoring logic exactly
# TREND:25 | REGIME:12 | VOLUME:18 | MOMENTUM:25 | POSITION:15 | PATTERN:5

import pandas as pd
import numpy as np
from typing import Tuple

import sys
sys.path.append('..')
from config.settings import *


def calculate_trend_score(df: pd.DataFrame) -> float:
    """Calculate trend score (max 25 points)"""
    if len(df) == 0:
        return 0.0
    
    row = df.iloc[-1]
    score = 0.0
    
    bullish_trend = (
        row.get('direction', -1) == 1
        if USE_SUPERTREND
        else bool(row.get('ema_bullish_alignment', False) or row.get('price_above_ema50', False))
    )

    if bullish_trend:
        score += 10.0

    if row.get('ema_bullish_alignment', False):
        score += 10.0

    if bullish_trend:
        score += 5.0
    
    return min(score, 25.0)


def calculate_regime_score(df: pd.DataFrame) -> float:
    """Calculate market regime score (max 12 points) — FIXED v5"""
    if len(df) == 0:
        return 0.0
    
    row = df.iloc[-1]
    score = 0.0
    
    # Trending market: +8 (was 10 in v3)
    if row.get('is_trending', False):
        score += 8.0
    
    # Volatile enough: +4 (was 5 in v3)
    if row.get('is_volatile_enough', False):
        score += 4.0
    
    return min(score, 12.0)


def calculate_volume_score(df: pd.DataFrame) -> float:
    """Calculate volume score (max 18 points) — FIXED v5: no double counting"""
    if len(df) == 0:
        return 0.0
    
    row = df.iloc[-1]
    score = 0.0
    
    # High volume (volume > min threshold): +4
    if row.get('is_high_volume', False):
        score += 4.0
    
    # Volume: unusual OR spike (NOT both — fixed double counting!)
    if row.get('is_unusual_volume', False):
        score += 10.0
    elif row.get('is_volume_spike', False):
        score += 7.0
    
    # OBV bullish + bullish trend: +4 (NEW v5)
    obv_bullish_trend = (
        row.get('direction', -1) == 1
        if USE_SUPERTREND
        else bool(row.get('price_above_ema20', False))
    )
    if row.get('obv_bullish', False) and obv_bullish_trend:
        score += 4.0
    
    return min(score, 18.0)


def calculate_momentum_score(df: pd.DataFrame) -> float:
    """Calculate momentum score (max 25 points) — FIXED v5: removed stoch_neutral, added MACD"""
    if len(df) == 0:
        return 0.0
    
    row = df.iloc[-1]
    score = 0.0
    
    # Positive momentum: +8 (was 10 in v3)
    if row.get('is_positive_momentum', False):
        score += 8.0
    
    # Strong momentum + positive: +4 (was 7 in v3)
    if row.get('is_strong_momentum', False) and row.get('is_positive_momentum', False):
        score += 4.0
    
    # Stoch: K < zona ATAU golden cross dengan K < 70 (+ bullish, hindari cross overbought)
    stoch_k = float(row.get('stoch_k', 50.0))
    stoch_cross_up = row.get('stoch_k_cross_up', False)
    stoch_cross_valid = stoch_cross_up and stoch_k < ACCUM_STOCH_CROSS_K_MAX
    stoch_zone = stoch_k < ACCUM_STOCH_K_MAX
    mom_bullish = (
        row.get('direction', -1) == 1
        if USE_SUPERTREND
        else bool(row.get('price_above_ema50', False))
    )
    if mom_bullish and (stoch_cross_valid or stoch_zone):
        score += 8.0
    
    # MACD bullish: +5 (NEW v5, replaces stoch_neutral)
    if row.get('macd_bullish', False):
        score += 5.0
    
    return min(score, 25.0)


def calculate_position_score(df: pd.DataFrame) -> float:
    """Calculate position score (max 15 points) — FIXED v5"""
    if len(df) == 0:
        return 0.0
    
    row = df.iloc[-1]
    score = 0.0
    
    # Price above EMA200: +6 (was 8 in v3)
    if row.get('price_above_ema200', False):
        score += 6.0
    
    # Price above EMA50: +5 (was 6 in v3)
    if row.get('price_above_ema50', False):
        score += 5.0
    
    # Price above EMA20: +4 (same)
    if row.get('price_above_ema20', False):
        score += 4.0
    
    return min(score, 15.0)


def calculate_pattern_score(df: pd.DataFrame) -> float:
    """Calculate pattern score (max 5 points) — NEW v5"""
    if len(df) == 0:
        return 0.0
    
    row = df.iloc[-1]
    score = 0.0
    
    if row.get('bullish_engulfing', False):
        score += 5.0
    elif row.get('bullish_pattern', False):
        score += 3.0
    
    # Bullish divergence: +1 to +4 based on strength
    if row.get('bullish_divergence', False):
        strength = row.get('div_strength', 0)
        if strength >= 3:
            score += 4.0
        elif strength >= 1:
            score += 2.0
        else:
            score += 1.0
    
    return min(score, 5.0)


def calculate_total_score(df: pd.DataFrame) -> Tuple[int, str, str]:
    """
    Calculate total score and determine status (v5)
    
    Returns:
        Tuple of (score, status, status_emoji)
    """
    if len(df) == 0:
        return 0, "AVOID", "🔴"
    
    trend = calculate_trend_score(df)
    regime = calculate_regime_score(df)
    volume = calculate_volume_score(df)
    momentum = calculate_momentum_score(df)
    position = calculate_position_score(df)
    pattern = calculate_pattern_score(df)  # NEW v5
    
    total = trend + regime + volume + momentum + position + pattern

    row = df.iloc[-1]
    final_score = int(round(total))
    is_trending = row.get('is_trending', False)
    
    # Determine status (v5 thresholds)
    if final_score >= BUY_THRESHOLD and is_trending:
        return final_score, "STRONG BUY", "🟢"
    elif final_score >= ACCUMULATE_THRESHOLD:
        return final_score, "ACCUMULATE", "🔵"
    elif final_score >= HOLD_THRESHOLD:
        return final_score, "HOLD", "🟡"
    else:
        return final_score, "AVOID", "🔴"


def get_score_breakdown(df: pd.DataFrame) -> dict:
    """Get detailed score breakdown (v5)"""
    return {
        'trend': calculate_trend_score(df),
        'regime': calculate_regime_score(df),
        'volume': calculate_volume_score(df),
        'momentum': calculate_momentum_score(df),
        'position': calculate_position_score(df),
        'pattern': calculate_pattern_score(df)  # NEW v5
    }
