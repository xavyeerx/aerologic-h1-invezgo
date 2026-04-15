# ============================================
# IHSG SUPERTREND SCANNER - SETTINGS
# ============================================

import os

# === TELEGRAM CONFIGURATION ===
# For Railway: set these as environment variables
# For local development: values below are used as fallback
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8421417558:AAGSldYyzkQ59uxpuPeGIaz8sW_GUtISSq8")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "-1003752913925")

# === SUPERTREND SETTINGS ===
# Same as Pine Script v3
SUPERTREND_PERIOD = 10
SUPERTREND_MULTIPLIER = 3.0

# === EMA SETTINGS ===
EMA_FAST = 20
EMA_MEDIUM = 50
EMA_SLOW = 200

# === VOLUME SETTINGS ===
VOLUME_PERIOD = 20
VOLUME_SPIKE_THRESHOLD = 1.5
UNUSUAL_VOLUME_THRESHOLD = 2.5
MIN_VOLUME = 100000

# === STOCHASTIC RSI SETTINGS ===
RSI_PERIOD = 14
STOCH_PERIOD = 14
SMOOTH_K = 3
SMOOTH_D = 3
STOCH_OVERBOUGHT = 80
STOCH_OVERSOLD = 20

# === ATR & ADX SETTINGS ===
ATR_PERIOD = 14
ATR_MULTIPLIER = 1.5
MIN_ATR_PERCENT = 0.5
ADX_PERIOD = 14
ADX_THRESHOLD = 25

# === MACD SETTINGS ===
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# === MOMENTUM SETTINGS ===
MOMENTUM_PERIOD = 10

# === FALSE BREAKOUT FILTER ===
CONFIRMATION_BARS = 2

# === SUPPORT/RESISTANCE ===
PIVOT_LOOKBACK = 10

# === EXIT STRATEGY ===
TP1_MULTIPLIER = 1.0    # TP1 = entry + 1.0×ATR  (quick target)
TP2_MULTIPLIER = 2.5    # TP2 = entry + 2.5×ATR  (swing target, fallback)
TP2_MIN_MULTIPLIER = 1.3  # Resistance hanya jadi TP2 jika > entry + 1.3×ATR
                           # (hindari TP2 yang terlalu dekat dengan TP1)
TP2_MAX_MULTIPLIER = 3.0  # Resistance hanya jadi TP2 jika < entry + 3.0×ATR
                           # (hindari TP2 yang terlalu jauh tidak realistis)
SL_SWING_LOOKBACK = 10

# === DCA SETTINGS ===
FIB_LEVEL_1 = 61.8  # First DCA zone
FIB_LEVEL_2 = 85.0  # Second DCA zone (deeper)
DCA_LOOKBACK = 20
DCA_VOLUME_THRESHOLD = 0.7  # Healthy correction = vol < 70% avg

# === SCORING THRESHOLDS (v5) ===
BUY_THRESHOLD = 70
ACCUMULATE_THRESHOLD = 55
HOLD_THRESHOLD = 40

# === SCANNER SETTINGS ===
SCAN_INTERVAL_MINUTES = 1  # Scan every 1 minute
DATA_PERIOD = "120d"  # Historical data to fetch (need more for daily TF)
DATA_INTERVAL = "1d"  # DAILY candlestick for ALL signals

# === TRADING HOURS (WIB) ===
TRADING_START_HOUR = 8
TRADING_START_MINUTE = 45
TRADING_END_HOUR = 16
TRADING_END_MINUTE = 0

# === DIVERGENCE SETTINGS (v5.1 - Enhanced) ===
DIV_PIVOT_LOOKBACK = 5          # Bars each side to confirm a swing low/high
DIV_MIN_SEPARATION = 8          # Min bars between two pivot lows
DIV_MAX_SEPARATION = 60         # Max bars between two pivot lows
DIV_RSI_OVERSOLD = 40           # RSI must be below this at first low (EM market oversold zone)
DIV_RSI_MIN_DIFF = 2            # Min RSI difference (higher low) for bullish div
DIV_PRICE_MIN_DROP = 0.5        # Min % price lower low to count as meaningful
DIV_STOCH_MAX_K = 85            # Max Stoch K on signal bar (reject extreme overbought only)
DIV_FRESHNESS_BARS = 10         # Extra bars beyond pivot lookback (effective = PIVOT_LOOKBACK + this)
DIV_VOLUME_DECLINE_RATIO = 1.5  # Volume filter relaxed as hard gate, used more for strength scoring

# === LOGIC SETTINGS ===
MIN_DAILY_TURNOVER = 5_000_000_000  # 5 Miliar (Billion) IDR

# === FILE PATHS ===
STATE_FILE = "database/stock_states.json"
LOG_FILE = "logs/scanner.log"
