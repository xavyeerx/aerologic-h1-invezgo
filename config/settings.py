import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

SCANNER_BUILD_ID = "20260907-h1-migration"

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_TEST_CHAT_ID = os.getenv("TELEGRAM_TEST_CHAT_ID", "")


def _env_int_or_none(name: str):
    value = os.getenv(name, "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


TELEGRAM_SCANNER_TOPIC_ID = _env_int_or_none("TELEGRAM_SCANNER_TOPIC_ID")

# Price and indicator settings
BREAKOUT_LOOKBACK = 20
EMA_FAST = 20
EMA_MEDIUM = 50
EMA_SLOW = 200
VOLUME_PERIOD = 20
VOLUME_SPIKE_THRESHOLD = 1.2
UNUSUAL_VOLUME_THRESHOLD = 2.0
MIN_VOLUME = 100000
RSI_PERIOD = 14
STOCH_PERIOD = 14
SMOOTH_K = 3
SMOOTH_D = 3
STOCH_OVERBOUGHT = 80
STOCH_OVERSOLD = 20
ACCUM_STOCH_K_MAX = 35
ACCUM_STOCH_CROSS_K_MAX = 70
ATR_PERIOD = 14
ATR_MULTIPLIER = 1.5
MIN_ATR_PERCENT = 0.5
ADX_PERIOD = 14
ADX_THRESHOLD = 25
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
MOMENTUM_PERIOD = 10
PIVOT_LOOKBACK = 10

# Supertrend — matches the TradingView chart configuration (10, 3)
SUPERTREND_PERIOD = 10
SUPERTREND_MULTIPLIER = 3.0

# H1 signal engine thresholds. Migration defaults require forward validation.
CONTINUATION_MIN_RETURN20 = float(os.getenv("CONTINUATION_MIN_RETURN20", "5.0"))
CONTINUATION_MIN_VOLUME_RATIO = float(os.getenv("CONTINUATION_MIN_VOLUME_RATIO", "1.2"))
STRONG_BUY_MAX_CHANGE_PCT = float(os.getenv("STRONG_BUY_MAX_CHANGE_PCT", "10.0"))
REVERSAL_MAX_RETURN20 = float(os.getenv("REVERSAL_MAX_RETURN20", "-8.0"))
REVERSAL_MAX_RSI = float(os.getenv("REVERSAL_MAX_RSI", "35"))
REVERSAL_MIN_VOLUME_RATIO = float(os.getenv("REVERSAL_MIN_VOLUME_RATIO", "1.5"))
REVERSAL_WATCH_ALERT_ENABLED = os.getenv(
    "REVERSAL_WATCH_ALERT_ENABLED", "false"
).strip().lower() in {"1", "true", "yes", "on"}

# Risk and targets
ARB_DROP_PCT_MIN = 13.0
TP1_MULTIPLIER = 1.0
TP2_MULTIPLIER = 2.5
TP2_MIN_MULTIPLIER = 1.3
TP2_MAX_MULTIPLIER = 3.0
SL_SWING_LOOKBACK = 10
DCA_LOOKBACK = 20
DCA_VOLUME_THRESHOLD = 0.7
FIB_LEVEL_1 = 61.8
FIB_LEVEL_2 = 85.0

# Scoring thresholds
BUY_THRESHOLD = 60
ACCUMULATE_THRESHOLD = 50
HOLD_THRESHOLD = 40

# Scanner settings
SCAN_ANALYZE_WORKERS = max(1, int(os.getenv("SCAN_ANALYZE_WORKERS", "4")))
DATA_PERIOD = "45d"   # roughly 300 closed H1 bars; enough for EMA200 warm-up
DATA_INTERVAL = "60"  # Invezgo multi-timeframe 60-minute candle

# Trading hours metadata
TRADING_START_HOUR = 9
TRADING_START_MINUTE = 1
TRADING_END_HOUR = 16
TRADING_END_MINUTE = 1

# Divergence fields are still calculated as diagnostics, not as a separate alert.
DIV_PIVOT_LOOKBACK = 5
DIV_MIN_SEPARATION = 8
DIV_MAX_SEPARATION = 60
DIV_RSI_OVERSOLD = 40
DIV_RSI_MIN_DIFF = 2
DIV_PRICE_MIN_DROP = 0.5
DIV_STOCH_MAX_K = 85
DIV_FRESHNESS_BARS = 10
DIV_VOLUME_DECLINE_RATIO = 1.5

# Logic settings
MIN_DAILY_TURNOVER = 5_000_000_000

# File paths
STATE_FILE = "database/stock_states.json"
LOG_FILE = "logs/scanner.log"
