# ============================================
# IHSG SUPERTREND SCANNER - SETTINGS
# ============================================

import os
from datetime import datetime, timedelta
from pathlib import Path

import pytz
from dotenv import load_dotenv

# Load repo-root .env for local dev (does not override existing env vars)
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Naikkan saat deploy agar mudah cek VM sudah pull versi terbaru (lihat log/Telegram startup).
SCANNER_BUILD_ID = "20260610-regime-adaptive"

# === TELEGRAM CONFIGURATION ===
# For Railway: set these as environment variables
# For local development: values below are used as fallback
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# === SUPERTREND SETTINGS ===
# Same as Pine Script v3 — set True untuk aktifkan lagi (strong buy lama pakai konfirmasi bar ST)
USE_SUPERTREND = False
SUPERTREND_PERIOD = 10
SUPERTREND_MULTIPLIER = 3.0

# === BREAKOUT (tanpa supertrend) ===
# Close > high N hari sebelumnya (exclude bar hari ini)
BREAKOUT_LOOKBACK = 20

# === EMA SETTINGS ===
EMA_FAST = 20
EMA_MEDIUM = 50
EMA_SLOW = 200

# === VOLUME SETTINGS ===
VOLUME_PERIOD = 20
VOLUME_SPIKE_THRESHOLD = 1.2   # >= 1.2× MA20
UNUSUAL_VOLUME_THRESHOLD = 2.0  # >= 2× MA20
ENGULF_MIN_VOLUME_RATIO = 1.0  # bullish engulfing: volume minimal ≥ MA20 (1×)
# Jalur engulfing: score minimum (lebih longgar dari breakout karena pola candle konfirmasi)
STRONG_BUY_ENGULF_MIN_SCORE = 40
# Jalur tambahan: flip bullish supertrend (crossover close > ST) + volume + score
STRONG_BUY_SUPERTREND_ENABLED = True
MIN_VOLUME = 100000

# === STOCHASTIC RSI SETTINGS ===
RSI_PERIOD = 14
STOCH_PERIOD = 14
SMOOTH_K = 3
SMOOTH_D = 3
STOCH_OVERBOUGHT = 80
STOCH_OVERSOLD = 20  # flag indikator (overbought/oversold ketat di chart logic)
# Accumulation + skor: K di zona bawah ATAU golden cross (cross diabaikan jika K >= overbought cross)
ACCUM_STOCH_K_MAX = 35
ACCUM_STOCH_CROSS_K_MAX = 70  # golden cross valid selama K belum zona jual ekstrem (>= 70)

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

# === FALSE BREAKOUT FILTER (hanya dipakai jika USE_SUPERTREND=True) ===
CONFIRMATION_BARS = 2

# === POST-ALERT ARB FILTER (IDX) ===
# Call kemarin → hari ini ARB (turun >= 13%) → skip alert sampai candle hijau
ARB_DROP_PCT_MIN = 13.0

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
BUY_THRESHOLD = 60
ACCUMULATE_THRESHOLD = 50
HOLD_THRESHOLD = 40

# === SCANNER SETTINGS ===
SCAN_INTERVAL_MINUTES = 0  # 0 = back-to-back saat sesi buka (scheduler tidak idle antar scan)
DATA_PERIOD = "90d"   # Target lebar seri (~90 sesi IDX); Yahoo: tambah buffer kalender di data_fetcher
DATA_INTERVAL = "1d"  # DAILY candlestick for ALL signals

# === TRADING HOURS (WIB) ===
TRADING_START_HOUR = 8
TRADING_START_MINUTE = 30
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

# === DAILY CHART PATTERNS (TF-D heuristic; anchor candle = H untuk reviu malam) ===
CHART_BASE_LOOKBACK = 22
CHART_BREAK_BUFFER = 0.00125  # 0.125% di atas tinggi basis / neckline

CHART_CONVERGENCE_LOOKBACK = 34
CHART_CONVERGENCE_CORR_THRESHOLD = 0.36
CHART_NARROWING_RATIO = 0.78  # rentang konsolidasi akhir vs awal (~78% tighter)
CHART_FALLING_WEDGE_CORR_HI = 0.32
CHART_FALLING_WEDGE_SLOPE_MIN = 8e-6  # jarak relatif (m_l - m_h)/close — highs turun lebih tajam dari lows

CHART_PENNANT_IMPULSE_LOOKBACK = 24
CHART_PENNANT_IMPULSE_MIN_PCT = 5.5
CHART_PENNANT_MAX_RANGE_PCT = 4.25  # konsolidasi pennant ± sempit (% dari close)

CHART_TOUCH_ATR_MULT = 0.35
# Zona fib kasar untuk reject harmonic (retrace + extension)
CHART_HARM_FIB_RATIOS = (0.618, 0.886, 1.13)
CHART_HARM_ZONE_ATR_MULT = 0.5
CHART_FALSE_BREAK_LOOKBACK = 16

# Minimal bar OHLC: struktural (lookback tertinggi + amortisasi EMA50), bukan ~70 bar seperti scanner utama —
# agar IPO / histori Yahoo pendek (mis. FILM) tetap dievaluasi.
_CHART_PENN_SEG = max(8, CHART_CONVERGENCE_LOOKBACK // 2)
CHART_MIN_BARS = max(
    CHART_BASE_LOOKBACK + 3,
    CHART_CONVERGENCE_LOOKBACK + 3,
    CHART_PENNANT_IMPULSE_LOOKBACK + _CHART_PENN_SEG + 5,
    EMA_MEDIUM + 5,
    CHART_FALSE_BREAK_LOOKBACK + 3,
    46,
)

# Alert pola chart TF-D (terpisah dari Strong Buy / Acc / dll) — reviu terjadwal 1× per hari
CHART_PATTERN_ALERT_HOUR = 16
CHART_PATTERN_ALERT_MINUTE = 45
# Hanya dalam menit pertama setelah CHART_PATTERN_ALERT_* job diizinkan jalan; lewat itu skip sampai besok
CHART_PATTERN_EXECUTION_WINDOW_MINUTES = 2


def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


# True: deteksi pola chart tiap siklus scan (08:30–16:00). False: hanya slot terjadwal CHART_PATTERN_ALERT_*.
# CHART_PATTERN_FORCE_SCHEDULED_ONLY (default True) mengabaikan env realtime — pola chart 1×/hari saja.
CHART_PATTERN_FORCE_SCHEDULED_ONLY = _env_bool("CHART_PATTERN_FORCE_SCHEDULED_ONLY", True)
CHART_PATTERN_REALTIME = (
    _env_bool("CHART_PATTERN_REALTIME", False)
    and not CHART_PATTERN_FORCE_SCHEDULED_ONLY
)

_WIB = pytz.timezone("Asia/Jakarta")


def chart_pattern_slot_bounds(now: datetime | None = None, tz=_WIB) -> tuple[datetime, datetime]:
    """Awal dan akhir jendela eksekusi pola chart hari ini (WIB)."""
    now = now or datetime.now(tz)
    chart_at = now.replace(
        hour=CHART_PATTERN_ALERT_HOUR,
        minute=CHART_PATTERN_ALERT_MINUTE,
        second=0,
        microsecond=0,
    )
    chart_end = chart_at + timedelta(minutes=CHART_PATTERN_EXECUTION_WINDOW_MINUTES)
    return chart_at, chart_end


def is_chart_pattern_alert_window(now: datetime | None = None, tz=_WIB) -> bool:
    """True hanya di dalam jendela terjadwal (Senin–Jumat)."""
    now = now or datetime.now(tz)
    if now.weekday() >= 5:
        return False
    chart_at, chart_end = chart_pattern_slot_bounds(now, tz)
    return chart_at <= now < chart_end

# Filter kualitas alert pola (TF-D): volume vs MA20, OBV accumulation (RSI hanya ditampilkan di pesan Telegram)

# === LOGIC SETTINGS ===
MIN_DAILY_TURNOVER = 5_000_000_000  # 5 Miliar (Billion) IDR

# === FILE PATHS ===
STATE_FILE = "database/stock_states.json"
LOG_FILE = "logs/scanner.log"
