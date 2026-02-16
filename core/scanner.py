# ============================================
# SCANNER - MAIN SCANNING LOGIC v5.0
# ============================================

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple
import logging

from config.settings import *
from .supertrend import calculate_supertrend, is_bullish, just_turned_bullish, just_turned_bearish
from .indicators import calculate_all_indicators
from .scoring import calculate_total_score

logger = logging.getLogger(__name__)


class ScanResult:
    """Container for scan results (v5)"""
    def __init__(self, ticker: str):
        self.ticker = ticker
        self.price = 0.0
        self.change_percent = 0.0
        self.supertrend_value = 0.0
        self.is_bullish = False
        self.score = 0
        self.status = "UNKNOWN"
        self.status_emoji = "⚪"
        
        # Signals (v5: removed stoch_crossover & bearish_break, renamed bullish_break → strong_buy)
        self.is_strong_buy = False        # v5: confirmed breakout + high score
        self.is_accumulation = False
        self.is_early_entry = False
        self.is_bull_div = False           # NEW v5: bullish divergence
        
        # Entry strategy info
        self.stop_loss = 0.0
        self.tp1 = 0.0
        self.entry_zone_lower = 0.0
        self.entry_zone_upper = 0.0
        
        # Additional info
        self.volume_ratio = 0.0
        self.stoch_k = 0.0
        self.stoch_d = 0.0
        self.daily_turnover = 0.0
        self.avg_turnover_5d = 0.0
        self.correction_percent = 0.0
        self.early_entry_strength = 0
        
        # v5 new data
        self.adx = 0.0
        self.macd_status = ""
        self.obv_status = ""
        self.pattern_name = ""
        self.divergence_status = ""
        self.is_trending = False
        self.support = 0.0
        self.resistance = 0.0


def analyze_stock(ticker: str, df: pd.DataFrame, previous_state: dict = None) -> ScanResult:
    """
    Analyze a single stock and detect signals (v5 logic)
    """
    result = ScanResult(ticker)
    
    if df is None or len(df) < 50:
        return result
    
    try:
        # Calculate turnover (Price * Volume)
        df['turnover'] = df['close'] * df['volume']
        avg_turnover_5d = df['turnover'].rolling(window=5).mean().iloc[-1]
        
        result.daily_turnover = df['turnover'].iloc[-1]
        result.avg_turnover_5d = avg_turnover_5d
        
        # Calculate all indicators (v5)
        df = calculate_supertrend(df)
        df = calculate_all_indicators(df)
        
        latest = df.iloc[-1]
        
        # Basic info
        result.price = latest['close']
        result.supertrend_value = latest['supertrend']
        result.is_bullish = latest['direction'] == 1
        result.volume_ratio = latest.get('volume_ratio', 1.0)
        result.stoch_k = latest.get('stoch_k', 50.0)
        result.stoch_d = latest.get('stoch_d', 50.0)
        
        # Entry strategy info
        result.stop_loss = latest.get('stop_loss', 0.0)
        result.tp1 = latest.get('tp1', 0.0)
        result.entry_zone_lower = latest.get('entry_zone_lower', 0.0)
        result.entry_zone_upper = latest.get('entry_zone_upper', 0.0)
        
        # v5 additional data
        result.adx = latest.get('adx', 0.0)
        result.is_trending = latest.get('is_trending', False)
        result.support = latest.get('support', 0.0)
        result.resistance = latest.get('resistance', 0.0)
        
        # MACD status
        if latest.get('macd_cross_up', False):
            result.macd_status = "⬆️ CROSS UP"
        elif latest.get('macd_cross_down', False):
            result.macd_status = "⬇️ CROSS DN"
        elif latest.get('macd_bullish', False):
            result.macd_status = "🟢 BULL"
        else:
            result.macd_status = "🔴 BEAR"
        
        # OBV status
        result.obv_status = "📈 ACC" if latest.get('obv_bullish', False) else "📉 DIST"
        
        # Pattern name
        result.pattern_name = latest.get('pattern_name', '')
        
        # Divergence status
        if latest.get('bullish_divergence', False):
            result.divergence_status = "🟢 BULL DIV"
        elif latest.get('bearish_divergence', False):
            result.divergence_status = "🔴 BEAR DIV"
        else:
            result.divergence_status = ""
        
        # Price change
        if len(df) >= 2:
            prev_close = df['close'].iloc[-2]
            if prev_close > 0:
                result.change_percent = ((result.price - prev_close) / prev_close) * 100
        
        # Score and status (v5)
        result.score, result.status, result.status_emoji = calculate_total_score(df)
        
        # ═══════════════════════════════════════════
        # SIGNAL DETECTION v5
        # ═══════════════════════════════════════════
        
        # 1. STRONG BUY Signal (v5: confirmed breakout + score threshold)
        # Uses False Breakout Filter: need CONFIRMATION_BARS above supertrend
        is_bullish_trend = latest['direction'] == 1
        breakout_up = just_turned_bullish(df)
        
        # Count consecutive bars above supertrend after breakout
        if is_bullish_trend:
            bars_above = 0
            for i in range(len(df) - 1, max(len(df) - CONFIRMATION_BARS - 5, 0), -1):
                if df.iloc[i]['direction'] == 1 and df.iloc[i]['close'] > df.iloc[i]['supertrend']:
                    bars_above += 1
                else:
                    break
            breakout_confirmed = bars_above >= CONFIRMATION_BARS
        else:
            breakout_confirmed = False
        
        # Check if recent breakout occurred (within last CONFIRMATION_BARS+1 bars)
        recent_breakout = False
        for i in range(1, min(CONFIRMATION_BARS + 2, len(df))):
            idx = len(df) - 1 - i
            if idx >= 1:
                prev_dir = df.iloc[idx - 1]['direction']
                curr_dir = df.iloc[idx]['direction']
                if prev_dir == -1 and curr_dir == 1:
                    recent_breakout = True
                    break
        
        # Also count current bar breakout
        if breakout_up:
            recent_breakout = True
        
        # Strong Buy = confirmed breakout + high score + trending
        if is_bullish_trend and (breakout_confirmed or breakout_up) and recent_breakout and result.score >= BUY_THRESHOLD:
            result.is_strong_buy = True
        
        # 2. ACCUMULATION Signal (v5 logic)
        # Smart Stochastic RSI: different logic for trending vs ranging
        stoch_k = latest.get('stoch_k', 50.0)
        stoch_d = latest.get('stoch_d', 50.0)
        stoch_k_cross_up = latest.get('stoch_k_cross_up', False)
        is_stoch_oversold = latest.get('stoch_oversold', False)
        is_trending = latest.get('is_trending', False)
        
        # Smart Stoch Buy (v5)
        stoch_buy_trending = is_trending and stoch_k_cross_up and stoch_k > 20
        stoch_buy_ranging = not is_trending and is_stoch_oversold and stoch_k_cross_up
        smart_stoch_buy = stoch_buy_trending or stoch_buy_ranging
        
        # ACC = bullish + (oversold OR smartStochBuy) + (spike OR unusual) + score >= acc + not sideways
        acc_has_momentum = is_stoch_oversold or smart_stoch_buy
        acc_has_volume = latest.get('is_volume_spike', False) or latest.get('is_unusual_volume', False)
        is_not_sideways = not latest.get('is_sideways', False)
        
        if is_bullish_trend and acc_has_momentum and acc_has_volume and result.score >= ACCUMULATE_THRESHOLD and is_not_sideways:
            result.is_accumulation = True
        
        # 3. BULLISH DIVERGENCE Signal (NEW)
        if latest.get('bullish_divergence', False) and not is_bullish_trend:
            result.is_bull_div = True
        
        # 4. EARLY ENTRY (Serok Bawah)
        if len(df) >= 2:
            prev_close = df['close'].iloc[-2]
            current_close = latest.get('close', 0)
            drop_from_prev_close = ((prev_close - current_close) / prev_close) * 100
        else:
            drop_from_prev_close = 0
        
        is_healthy_correction = latest.get('is_healthy_correction', False)
        result.correction_percent = drop_from_prev_close
        
        # Condition 1: DRY CORRECTION (3-12% drop)
        is_dry_correction = (3 <= drop_from_prev_close <= 12) and is_healthy_correction
        
        # Condition 2: PRICE HOLDING
        if len(df) >= 2:
            no_lower_low = df['low'].iloc[-1] >= df['low'].iloc[-2]
            today_range = (df['high'].iloc[-1] - df['low'].iloc[-1]) / df['close'].iloc[-1] * 100
            yesterday_range = (df['high'].iloc[-2] - df['low'].iloc[-2]) / df['close'].iloc[-2] * 100
            range_shrinking = today_range < yesterday_range
            low_diff = abs(df['low'].iloc[-1] - df['low'].iloc[-2]) / df['close'].iloc[-1] * 100
            price_defended = low_diff < 1.5
        else:
            no_lower_low = False
            range_shrinking = False
            price_defended = False
        
        is_price_holding = no_lower_low or price_defended or range_shrinking
        
        # Condition 3: EARLY BUYING PRESSURE
        if len(df) >= 2:
            volume_increasing = df['volume'].iloc[-1] > df['volume'].iloc[-2]
        else:
            volume_increasing = False
        price_stable_or_up = latest.get('close', 0) >= df['close'].iloc[-2] if len(df) >= 2 else False
        is_green_candle = latest.get('close', 0) > latest.get('open', 0) if 'open' in df.columns else False
        body_size = abs(latest.get('close', 0) - latest.get('open', 0))
        lower_wick = min(latest.get('close', 0), latest.get('open', 0)) - latest.get('low', 0)
        has_wick_rejection = lower_wick > body_size * 0.5 if body_size > 0 else False
        
        has_early_buying = volume_increasing or price_stable_or_up or is_green_candle or has_wick_rejection
        
        # Signal strength
        strength = sum([
            is_dry_correction,
            no_lower_low,
            price_defended,
            range_shrinking,
            volume_increasing,
            is_green_candle,
            has_wick_rejection
        ])
        result.early_entry_strength = strength
        
        # EARLY ENTRY = Bullish + Dry Correction + (Price Holding OR Early Buying)
        if is_bullish_trend and is_dry_correction and (is_price_holding or has_early_buying):
            result.is_early_entry = True
        
    except Exception as e:
        logger.error(f"Error analyzing {ticker}: {str(e)}")
    
    return result


def scan_all_stocks(stock_data: Dict[str, pd.DataFrame], previous_states: dict = None) -> Dict[str, ScanResult]:
    """Scan all stocks and return results"""
    results = {}
    previous_states = previous_states or {}
    
    for ticker, df in stock_data.items():
        prev_state = previous_states.get(ticker, {})
        result = analyze_stock(ticker, df, prev_state)
        results[ticker] = result
    
    return results


def filter_signals(results: Dict[str, ScanResult]) -> Dict[str, List[ScanResult]]:
    """
    Filter and categorize signals (v5)
    Removed: stoch_crossover, bearish_break
    Renamed: bullish_break → strong_buy
    Added: bull_div
    """
    signals = {
        'strong_buy': [],       # Was bullish_break
        'accumulation': [],
        'early_entry': [],
        'bull_div': []          # NEW
    }
    
    for ticker, result in results.items():
        # Only process signals if stock is liquid (> 5B turnover)
        if result.avg_turnover_5d < MIN_DAILY_TURNOVER:
            continue
            
        if result.is_strong_buy:
            signals['strong_buy'].append(result)
        if result.is_accumulation:
            signals['accumulation'].append(result)
        if result.is_early_entry:
            signals['early_entry'].append(result)
        if result.is_bull_div:
            signals['bull_div'].append(result)
    
    return signals


def filter_all_current_signals(results: Dict[str, ScanResult]) -> Dict[str, List[ScanResult]]:
    """
    Filter stocks by their CURRENT status for evening recap (v5).
    
    Categories:
    - strong_buy: Score >= BUY_THRESHOLD, Bullish, Trending
    - accumulation: Is accumulation signal
    - bullish: Currently bullish with good score  
    - early_entry: Early entry signal detected
    - bull_div: Bullish divergence detected
    """
    categories = {
        'strong_buy': [],
        'accumulation': [],
        'bullish': [],
        'early_entry': [],
        'bull_div': []
    }
    
    for ticker, result in results.items():
        # Only process liquid stocks
        if result.avg_turnover_5d < MIN_DAILY_TURNOVER:
            continue
        
        # Strong Buy: Score >= BUY_THRESHOLD, Bullish, Trending
        if result.is_bullish and result.score >= BUY_THRESHOLD and result.is_trending:
            categories['strong_buy'].append(result)
        # Accumulation: actual ACC signal
        elif result.is_accumulation:
            categories['accumulation'].append(result)
        # Bullish: Currently bullish with good score
        elif result.is_bullish and result.score >= ACCUMULATE_THRESHOLD:
            categories['bullish'].append(result)
        
        # Early Entry (can overlap)
        if result.is_early_entry:
            categories['early_entry'].append(result)
        
        # Bullish Divergence (can overlap)
        if result.is_bull_div:
            categories['bull_div'].append(result)
    
    # Sort by score (highest first)
    for key in categories:
        categories[key] = sorted(categories[key], key=lambda x: x.score, reverse=True)
    
    return categories


def has_any_signal(signals: Dict[str, List[ScanResult]]) -> bool:
    """Check if there are any signals to send"""
    return any(len(v) > 0 for v in signals.values())
