# ============================================
# TECHNICAL INDICATORS
# ============================================
# Matches Pine Script v5 logic

import pandas as pd
import numpy as np
from typing import Tuple, Dict

# Import settings
import sys
sys.path.append('..')
from config.settings import *


def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    """Calculate Exponential Moving Average"""
    return series.ewm(span=period, adjust=False).mean()


def calculate_sma(series: pd.Series, period: int) -> pd.Series:
    """Calculate Simple Moving Average"""
    return series.rolling(window=period).mean()


def calculate_emas(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate all EMAs (20, 50, 200) and MAs (5, 10, 100)"""
    df = df.copy()
    df['ema20'] = calculate_ema(df['close'], EMA_FAST)
    df['ema50'] = calculate_ema(df['close'], EMA_MEDIUM)
    df['ema200'] = calculate_ema(df['close'], EMA_SLOW)
    
    # Additional MAs from v5
    df['ma5'] = calculate_sma(df['close'], 5)
    df['ma10'] = calculate_sma(df['close'], 10)
    df['ma100'] = calculate_sma(df['close'], 100)
    
    # EMA Alignment
    df['ema_bullish_alignment'] = (df['ema20'] > df['ema50']) & (df['ema50'] > df['ema200'])
    df['ema_bearish_alignment'] = (df['ema20'] < df['ema50']) & (df['ema50'] < df['ema200'])
    
    # Price position relative to EMAs
    df['price_above_ema20'] = df['close'] > df['ema20']
    df['price_above_ema50'] = df['close'] > df['ema50']
    df['price_above_ema200'] = df['close'] > df['ema200']
    
    return df


def calculate_rsi(df: pd.DataFrame, period: int = RSI_PERIOD) -> pd.DataFrame:
    """Calculate RSI"""
    df = df.copy()
    delta = df['close'].diff()
    
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    return df


def calculate_stochastic_rsi(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate Stochastic RSI (matching Pine Script)"""
    df = df.copy()
    
    if 'rsi' not in df.columns:
        df = calculate_rsi(df)
    
    # Stochastic of RSI
    lowest_rsi = df['rsi'].rolling(window=STOCH_PERIOD).min()
    highest_rsi = df['rsi'].rolling(window=STOCH_PERIOD).max()
    
    stoch_rsi_raw = 100 * (df['rsi'] - lowest_rsi) / (highest_rsi - lowest_rsi)
    stoch_rsi_raw = stoch_rsi_raw.fillna(50)  # Default to 50 if undefined
    
    df['stoch_k'] = stoch_rsi_raw.rolling(window=SMOOTH_K).mean()
    df['stoch_d'] = df['stoch_k'].rolling(window=SMOOTH_D).mean()
    
    # Overbought/Oversold conditions
    df['stoch_overbought'] = df['stoch_k'] > STOCH_OVERBOUGHT
    df['stoch_oversold'] = df['stoch_k'] < STOCH_OVERSOLD
    
    # Crossovers
    df['stoch_k_cross_up'] = (df['stoch_k'] > df['stoch_d']) & (df['stoch_k'].shift(1) <= df['stoch_d'].shift(1))
    df['stoch_k_cross_down'] = (df['stoch_k'] < df['stoch_d']) & (df['stoch_k'].shift(1) >= df['stoch_d'].shift(1))
    
    return df


def calculate_atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.DataFrame:
    """Calculate Average True Range"""
    df = df.copy()
    
    tr1 = df['high'] - df['low']
    tr2 = abs(df['high'] - df['close'].shift(1))
    tr3 = abs(df['low'] - df['close'].shift(1))
    
    df['tr'] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df['atr'] = df['tr'].rolling(window=period).mean()
    df['atr_percent'] = (df['atr'] / df['close']) * 100
    
    # Volatility check (v5: minATR = 0.5%)
    df['is_volatile_enough'] = df['atr_percent'] >= MIN_ATR_PERCENT
    
    return df


def calculate_adx(df: pd.DataFrame, period: int = ADX_PERIOD) -> pd.DataFrame:
    """Calculate ADX (Average Directional Index) with DMI"""
    df = df.copy()
    
    # Calculate +DM and -DM
    df['high_diff'] = df['high'].diff()
    df['low_diff'] = -df['low'].diff()
    
    df['plus_dm'] = np.where((df['high_diff'] > df['low_diff']) & (df['high_diff'] > 0), df['high_diff'], 0)
    df['minus_dm'] = np.where((df['low_diff'] > df['high_diff']) & (df['low_diff'] > 0), df['low_diff'], 0)
    
    # Calculate TR if not already calculated
    if 'atr' not in df.columns:
        df = calculate_atr(df, period)
    
    # Smooth the values
    df['plus_di'] = 100 * (df['plus_dm'].rolling(window=period).mean() / df['atr'])
    df['minus_di'] = 100 * (df['minus_dm'].rolling(window=period).mean() / df['atr'])
    
    # Calculate DX and ADX
    df['dx'] = 100 * abs(df['plus_di'] - df['minus_di']) / (df['plus_di'] + df['minus_di'])
    df['adx'] = df['dx'].rolling(window=period).mean()
    
    # Trending vs Sideways
    df['is_trending'] = df['adx'] > ADX_THRESHOLD
    df['is_sideways'] = df['adx'] <= ADX_THRESHOLD
    
    # DMI Crossovers (new in v5)
    df['dmi_cross_up'] = (df['plus_di'] > df['minus_di']) & (df['plus_di'].shift(1) <= df['minus_di'].shift(1))
    df['dmi_cross_down'] = (df['plus_di'] < df['minus_di']) & (df['plus_di'].shift(1) >= df['minus_di'].shift(1))
    
    # Clean up
    df = df.drop(columns=['high_diff', 'low_diff', 'plus_dm', 'minus_dm', 'dx'], errors='ignore')
    
    return df


def calculate_volume_analysis(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate volume indicators including OBV"""
    df = df.copy()
    
    # Average volume
    df['avg_volume'] = df['volume'].rolling(window=VOLUME_PERIOD).mean()
    df['volume_ratio'] = df['volume'] / df['avg_volume']
    
    # Volume conditions (v5 thresholds)
    df['is_volume_spike'] = df['volume_ratio'] >= VOLUME_SPIKE_THRESHOLD
    df['is_unusual_volume'] = df['volume_ratio'] >= UNUSUAL_VOLUME_THRESHOLD
    df['is_high_volume'] = df['volume'] > MIN_VOLUME
    
    # Volume on up/down bars
    df['price_change'] = df['close'].diff()
    df['volume_on_up'] = np.where(df['price_change'] > 0, df['volume'], 0)
    df['volume_on_down'] = np.where(df['price_change'] < 0, df['volume'], 0)
    
    df['avg_volume_up'] = pd.Series(df['volume_on_up']).rolling(window=VOLUME_PERIOD).mean()
    df['avg_volume_down'] = pd.Series(df['volume_on_down']).rolling(window=VOLUME_PERIOD).mean()
    df['volume_bias_bullish'] = df['avg_volume_up'] > df['avg_volume_down']
    
    # === OBV (On Balance Volume) — NEW in v5 ===
    obv_change = np.where(df['close'] > df['close'].shift(1), df['volume'],
                 np.where(df['close'] < df['close'].shift(1), -df['volume'], 0))
    df['obv'] = pd.Series(obv_change, index=df.index).cumsum()
    df['obv_ema'] = calculate_ema(df['obv'], 20)
    df['obv_bullish'] = df['obv'] > df['obv_ema']
    
    return df


def calculate_macd(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate MACD (Moving Average Convergence Divergence) — NEW in v5"""
    df = df.copy()
    
    ema_fast = calculate_ema(df['close'], MACD_FAST)
    ema_slow = calculate_ema(df['close'], MACD_SLOW)
    
    df['macd_line'] = ema_fast - ema_slow
    df['macd_signal'] = calculate_ema(df['macd_line'], MACD_SIGNAL)
    df['macd_hist'] = df['macd_line'] - df['macd_signal']
    
    # Conditions
    df['macd_bullish'] = df['macd_line'] > df['macd_signal']
    df['macd_bearish'] = df['macd_line'] < df['macd_signal']
    df['macd_cross_up'] = (df['macd_line'] > df['macd_signal']) & (df['macd_line'].shift(1) <= df['macd_signal'].shift(1))
    df['macd_cross_down'] = (df['macd_line'] < df['macd_signal']) & (df['macd_line'].shift(1) >= df['macd_signal'].shift(1))
    df['macd_hist_rising'] = df['macd_hist'] > df['macd_hist'].shift(1)
    
    return df


def calculate_candlestick_patterns(df: pd.DataFrame) -> pd.DataFrame:
    """Recognize 6 candlestick patterns — NEW in v5"""
    df = df.copy()
    
    body = abs(df['close'] - df['open'])
    upper_wick = df['high'] - df[['close', 'open']].max(axis=1)
    lower_wick = df[['close', 'open']].min(axis=1) - df['low']
    total_range = df['high'] - df['low']
    is_bull = df['close'] > df['open']
    is_bear = df['close'] < df['open']
    
    body1 = abs(df['close'].shift(1) - df['open'].shift(1))
    is_bull1 = df['close'].shift(1) > df['open'].shift(1)
    is_bear1 = df['close'].shift(1) < df['open'].shift(1)
    
    body2 = abs(df['close'].shift(2) - df['open'].shift(2))
    is_bull2 = df['close'].shift(2) > df['open'].shift(2)
    is_bear2 = df['close'].shift(2) < df['open'].shift(2)
    
    # Need supertrend direction for context
    is_bullish_trend = df.get('direction', pd.Series(0, index=df.index)) == 1
    is_bearish_trend = df.get('direction', pd.Series(0, index=df.index)) == -1
    
    # 1. Bullish Engulfing
    df['bullish_engulfing'] = (is_bear1 & is_bull & 
                               (df['close'] > df['open'].shift(1)) & 
                               (df['open'] < df['close'].shift(1)) & 
                               (body > body1))
    
    # 2. Bearish Engulfing  
    df['bearish_engulfing'] = (is_bull1 & is_bear & 
                               (df['close'] < df['open'].shift(1)) & 
                               (df['open'] > df['close'].shift(1)) & 
                               (body > body1))
    
    # 3. Hammer (bullish reversal at bottom)
    df['is_hammer'] = ((lower_wick >= body * 2) & 
                        (upper_wick < body * 0.5) & 
                        (body > 0) & is_bearish_trend)
    
    # 4. Shooting Star (bearish reversal at top)
    df['is_shooting_star'] = ((upper_wick >= body * 2) & 
                               (lower_wick < body * 0.5) & 
                               (body > 0) & is_bullish_trend)
    
    # 5. Morning Star (3-candle bullish reversal)
    small_body1 = body1 < (total_range * 0.3)
    df['morning_star'] = (is_bear2 & (body2 > 0) & small_body1 & is_bull & 
                          (df['close'] > (df['open'].shift(2) + df['close'].shift(2)) / 2))
    
    # 6. Evening Star (3-candle bearish reversal)
    df['evening_star'] = (is_bull2 & (body2 > 0) & small_body1 & is_bear & 
                          (df['close'] < (df['open'].shift(2) + df['close'].shift(2)) / 2))
    
    # Combined pattern flags
    df['bullish_pattern'] = df['bullish_engulfing'] | df['is_hammer'] | df['morning_star']
    df['bearish_pattern'] = df['bearish_engulfing'] | df['is_shooting_star'] | df['evening_star']
    
    # Pattern name for display
    def _pattern_name(row):
        if row.get('bullish_engulfing', False): return "ENGULF▲"
        if row.get('is_hammer', False): return "HAMMER"
        if row.get('morning_star', False): return "M.STAR"
        if row.get('bearish_engulfing', False): return "ENGULF▼"
        if row.get('is_shooting_star', False): return "S.STAR"
        if row.get('evening_star', False): return "E.STAR"
        return ""
    
    df['pattern_name'] = df.apply(_pattern_name, axis=1)
    
    return df


def calculate_support_resistance(df: pd.DataFrame, lookback: int = PIVOT_LOOKBACK) -> pd.DataFrame:
    """Detect Support/Resistance using pivots — NEW in v5"""
    df = df.copy()
    
    # Pivot highs and lows
    df['pivot_high'] = df['high'].rolling(window=lookback*2+1, center=True).apply(
        lambda x: x.iloc[lookback] if x.iloc[lookback] == x.max() else np.nan, raw=False
    )
    df['pivot_low'] = df['low'].rolling(window=lookback*2+1, center=True).apply(
        lambda x: x.iloc[lookback] if x.iloc[lookback] == x.min() else np.nan, raw=False
    )
    
    # Forward fill to carry the latest S/R levels
    df['resistance'] = df['pivot_high'].ffill()
    df['support'] = df['pivot_low'].ffill()
    
    # Near S/R detection
    df['near_support'] = df['support'].notna() & (df['close'] <= df['support'] * 1.02)
    df['near_resistance'] = df['resistance'].notna() & (df['close'] >= df['resistance'] * 0.98)
    
    return df


def _find_pivot_lows(df: pd.DataFrame, lookback: int = DIV_PIVOT_LOOKBACK) -> pd.Series:
    """Find swing lows: bar where low is the lowest within lookback bars on each side."""
    pivot = df['low'].rolling(window=lookback * 2 + 1, center=True).apply(
        lambda x: x.iloc[lookback] if x.iloc[lookback] == x.min() else np.nan, raw=False
    )
    return pivot


def _find_pivot_highs(df: pd.DataFrame, lookback: int = DIV_PIVOT_LOOKBACK) -> pd.Series:
    """Find swing highs: bar where high is the highest within lookback bars on each side."""
    pivot = df['high'].rolling(window=lookback * 2 + 1, center=True).apply(
        lambda x: x.iloc[lookback] if x.iloc[lookback] == x.max() else np.nan, raw=False
    )
    return pivot


def calculate_divergence(df: pd.DataFrame) -> pd.DataFrame:
    """
    Detect RSI/Price divergence using pivot-based detection (v5.1 Enhanced).
    
    Bullish divergence criteria (all must be met):
      1. Two confirmed pivot lows separated by DIV_MIN_SEPARATION..DIV_MAX_SEPARATION bars
      2. Price: second pivot low < first pivot low (lower low) by >= DIV_PRICE_MIN_DROP %
      3. RSI: second pivot RSI > first pivot RSI + DIV_RSI_MIN_DIFF (higher low)
      4. First pivot RSI was in oversold territory (< DIV_RSI_OVERSOLD)
      5. Freshness: second pivot must be within DIV_FRESHNESS_BARS of the current bar
      6. Stoch K on signal bar <= DIV_STOCH_MAX_K (not already overbought)
      7. Volume at second low <= DIV_VOLUME_DECLINE_RATIO × volume at first low (selling exhaustion)
    
    Strength scoring (0-5):
      +1 confirmed by bullish candlestick pattern
      +1 MACD histogram rising at second low
      +1 volume declining significantly (< 0.6× first low)
      +1 OBV bullish
      +1 near support level
    """
    df = df.copy()

    if 'rsi' not in df.columns:
        df = calculate_rsi(df)

    n = len(df)
    bull_div = np.zeros(n, dtype=bool)
    bear_div = np.zeros(n, dtype=bool)
    div_strength = np.zeros(n, dtype=int)

    pivot_lows = _find_pivot_lows(df)
    pivot_highs = _find_pivot_highs(df)

    pivot_low_indices = pivot_lows.dropna().index.tolist()
    pivot_high_indices = pivot_highs.dropna().index.tolist()

    has_stoch = 'stoch_k' in df.columns
    has_macd = 'macd_hist' in df.columns and 'macd_hist_rising' in df.columns
    has_volume = 'volume' in df.columns
    has_pattern = 'bullish_pattern' in df.columns
    has_obv = 'obv_bullish' in df.columns
    has_support = 'near_support' in df.columns

    # Effective freshness window accounts for pivot confirmation delay
    max_freshness = DIV_PIVOT_LOOKBACK + DIV_FRESHNESS_BARS

    # --- BULLISH DIVERGENCE ---
    best_bull_strength = 0
    found_bull_div = False

    for i in range(1, len(pivot_low_indices)):
        idx2 = pivot_low_indices[i]   # second (more recent) pivot low
        idx1 = pivot_low_indices[i-1] # first (earlier) pivot low

        pos2 = df.index.get_loc(idx2)
        pos1 = df.index.get_loc(idx1)
        separation = pos2 - pos1

        if separation < DIV_MIN_SEPARATION or separation > DIV_MAX_SEPARATION:
            continue

        price1 = df.loc[idx1, 'low']
        price2 = df.loc[idx2, 'low']
        rsi1 = df.loc[idx1, 'rsi']
        rsi2 = df.loc[idx2, 'rsi']

        if pd.isna(rsi1) or pd.isna(rsi2):
            continue

        price_drop_pct = ((price1 - price2) / price1) * 100

        if price2 >= price1:
            continue
        if price_drop_pct < DIV_PRICE_MIN_DROP:
            continue
        if rsi2 <= rsi1 + DIV_RSI_MIN_DIFF:
            continue
        if rsi1 >= DIV_RSI_OVERSOLD:
            continue

        freshness = (n - 1) - pos2
        if freshness > max_freshness:
            continue

        if has_stoch:
            stoch_k_val = df.iloc[-1].get('stoch_k', 50.0)
            if stoch_k_val > DIV_STOCH_MAX_K:
                continue

        if has_volume:
            vol1 = df.loc[idx1, 'volume']
            vol2 = df.loc[idx2, 'volume']
            if vol1 > 0 and vol2 > vol1 * DIV_VOLUME_DECLINE_RATIO:
                continue

        strength = 0
        if has_pattern and df.loc[idx2, 'bullish_pattern']:
            strength += 1
        if has_macd and df.iloc[min(pos2 + 1, n - 1)].get('macd_hist_rising', False):
            strength += 1
        if has_volume and vol1 > 0 and vol2 < vol1 * 0.6:
            strength += 1
        if has_obv and df.iloc[-1].get('obv_bullish', False):
            strength += 1
        if has_support and df.loc[idx2, 'near_support']:
            strength += 1

        bull_div[pos2] = True
        div_strength[pos2] = strength

        if strength > best_bull_strength:
            best_bull_strength = strength
        found_bull_div = True

    # Propagate the best divergence signal to the latest bar so the scanner picks it up
    if found_bull_div:
        bull_div[-1] = True
        div_strength[-1] = best_bull_strength

    # --- BEARISH DIVERGENCE (also enhanced with pivots) ---
    found_bear_div = False

    for i in range(1, len(pivot_high_indices)):
        idx2 = pivot_high_indices[i]
        idx1 = pivot_high_indices[i-1]

        pos2 = df.index.get_loc(idx2)
        pos1 = df.index.get_loc(idx1)
        separation = pos2 - pos1

        if separation < DIV_MIN_SEPARATION or separation > DIV_MAX_SEPARATION:
            continue

        price1 = df.loc[idx1, 'high']
        price2 = df.loc[idx2, 'high']
        rsi1 = df.loc[idx1, 'rsi']
        rsi2 = df.loc[idx2, 'rsi']

        if pd.isna(rsi1) or pd.isna(rsi2):
            continue

        if price2 <= price1:
            continue
        if rsi2 >= rsi1:
            continue

        freshness = (n - 1) - pos2
        if freshness > max_freshness:
            continue

        bear_div[pos2] = True
        found_bear_div = True

    if found_bear_div:
        bear_div[-1] = True

    df['bullish_divergence'] = bull_div
    df['bearish_divergence'] = bear_div
    df['div_strength'] = div_strength

    return df


def calculate_targets(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate TP1 (quick target) and TP Swing (swing target)"""
    df = df.copy()
    
    if 'atr' not in df.columns:
        df = calculate_atr(df)
    
    # TP1 = target terdekat & tercepat (close + 1×ATR)
    df['tp1'] = df['close'] + df['atr']
    
    # TP Swing = target swing lebih besar (close + 1.5×ATR)
    # If resistance is available and closer than ATR-based, use resistance
    atr_swing = df['close'] + (df['atr'] * TP1_MULTIPLIER)
    
    if 'resistance' in df.columns:
        # Use nearest resistance if it's above price, else use ATR-based
        resistance_valid = df['resistance'].notna() & (df['resistance'] > df['close'])
        df['tp_swing'] = np.where(resistance_valid, df['resistance'], atr_swing)
    else:
        df['tp_swing'] = atr_swing
    
    return df


def calculate_momentum(df: pd.DataFrame, period: int = MOMENTUM_PERIOD) -> pd.DataFrame:
    """Calculate momentum indicators"""
    df = df.copy()
    
    # Rate of Change
    df['roc'] = ((df['close'] - df['close'].shift(period)) / df['close'].shift(period)) * 100
    df['is_positive_momentum'] = df['roc'] > 0
    df['is_strong_momentum'] = abs(df['roc']) > 5
    
    return df


def calculate_dca_zones(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate DCA zones based on Fibonacci retracement"""
    df = df.copy()
    
    # Swing high/low
    df['swing_high'] = df['high'].rolling(window=DCA_LOOKBACK).max()
    df['swing_low'] = df['low'].rolling(window=DCA_LOOKBACK).min()
    df['swing_range'] = df['swing_high'] - df['swing_low']
    
    # Fibonacci levels
    df['fib_618'] = df['swing_high'] - (df['swing_range'] * FIB_LEVEL_1 / 100)
    df['fib_850'] = df['swing_high'] - (df['swing_range'] * FIB_LEVEL_2 / 100)
    
    # DCA zones
    df['in_dca_zone1'] = (df['close'] <= df['fib_618']) & (df['close'] > df['fib_850'])
    df['in_dca_zone2'] = df['close'] <= df['fib_850']
    
    # Healthy correction detection
    short_term_vol = df['volume'].rolling(window=5).mean()
    df['is_low_volume_correction'] = short_term_vol < (df['avg_volume'] * DCA_VOLUME_THRESHOLD)
    
    # Distribution detection
    recent_down_vol = pd.Series(df['volume_on_down']).rolling(window=5).mean()
    recent_up_vol = pd.Series(df['volume_on_up']).rolling(window=5).mean()
    df['is_distribution'] = recent_down_vol > (recent_up_vol * 1.5)
    
    df['is_healthy_correction'] = df['is_low_volume_correction'] & ~df['is_distribution']
    
    # Price from recent high
    recent_high = df['high'].rolling(window=10).max()
    df['price_from_high'] = (recent_high - df['close']) / recent_high * 100
    df['is_in_correction'] = df['price_from_high'] > 3  # Min 3% from high
    
    # EMA touch detection
    if 'ema20' in df.columns:
        df['ema20_touch'] = (df['low'] <= df['ema20']) & (df['close'] > df['ema20'] * 0.99)
    else:
        df['ema20_touch'] = False
    if 'ema50' in df.columns:
        df['ema50_touch'] = (df['low'] <= df['ema50']) & (df['close'] > df['ema50'] * 0.99)
    else:
        df['ema50_touch'] = False
    
    return df


def calculate_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate all technical indicators (v5)"""
    df = calculate_emas(df)
    df = calculate_rsi(df)
    df = calculate_stochastic_rsi(df)
    df = calculate_atr(df)
    df = calculate_adx(df)
    df = calculate_volume_analysis(df)
    df = calculate_macd(df)           # NEW v5
    df = calculate_momentum(df)
    df = calculate_dca_zones(df)
    df = calculate_candlestick_patterns(df)  # NEW v5
    df = calculate_support_resistance(df)     # NEW v5
    df = calculate_divergence(df)             # NEW v5
    df = calculate_targets(df)                # TP1 + TP Swing
    
    return df
