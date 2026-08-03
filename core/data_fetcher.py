# ============================================
# DATA FETCHER — INVEZGO (v6)
# ============================================
# Menggantikan sumber data Yahoo Finance dengan Invezgo REST API.
# Semua request lewat core.data_provider (pacing + retry + quota counter).
#
# Signature fungsi publik DIPERTAHANKAN agar caller (scanner, main) tidak berubah:
#   fetch_multiple_stocks(tickers, period, interval) -> dict[ticker, DataFrame]
#   compute_session_change_percent(df, ticker) -> float
#   get_price_change(df, ticker) -> float
#   get_latest_data(df) -> dict
#   resolve_previous_close(df, ticker) -> float
#
# Arsitektur baru: filtering universe dilakukan di layer screener (main.py),
# modul ini hanya fetch OHLC detail untuk daftar kandidat yang sudah disaring.

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import List, Optional

import pandas as pd
import pytz

from .data_provider import fetch_chart, InvezgoError

# Konkurensi fetch chart. Rate limiter global di data_provider (token bucket)
# tetap membatasi laju total req/detik, jadi thread hanya mengisi waktu tunggu
# I/O — bukan mem-bypass rate limit. 4 thread + 3 req/s = ~4 menit? tidak: rate
# limiter yang jadi bottleneck (3 req/s -> 30 req ~10s), thread cukup 3-4.
FETCH_WORKERS = max(1, int(os.getenv("INVEZGO_FETCH_WORKERS", "4")))

logger = logging.getLogger(__name__)

WIB = pytz.timezone("Asia/Jakarta")

# DATA_PERIOD (mis. "90d") = target lebar seri; buffer kalender menambah hari
# non-dagang/libur agar cukup bar dagang harian terkumpul.
DAILY_FETCH_CALENDAR_BUFFER_DAYS = 45


def _period_to_range(period: str) -> tuple[str, str]:
    """
    Parse N dari string period (mis. "90d" -> 90). Start mundur N + buffer kalender;
    end = hari ini WIB (inklusif). Format 'YYYY-MM-DD'.
    """
    hint = 90
    if isinstance(period, str) and period.endswith("d"):
        try:
            hint = int(period[:-1])
        except ValueError:
            pass
    days_back = hint + DAILY_FETCH_CALENDAR_BUFFER_DAYS
    today = datetime.now(WIB).date()
    start = today - timedelta(days=days_back)
    return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")


def strip_suffix(ticker: str) -> str:
    """Normalkan ke kode Invezgo polos: 'BBCA.JK' -> 'BBCA'. Idempotent."""
    return ticker.replace(".JK", "").strip().upper()


def fetch_stock_data(ticker: str, period: str = "90d", interval: str = "1d") -> Optional[pd.DataFrame]:
    """
    Fetch OHLC harian 1 saham dari Invezgo (always daily candle).
    Parameter `interval` dipertahankan untuk kompatibilitas signature tapi diabaikan.
    """
    code = strip_suffix(ticker)
    start_s, end_s = _period_to_range(period)
    try:
        df = fetch_chart(code, start_s, end_s)
    except InvezgoError as e:
        logger.error("Error fetching %s: %s", code, e)
        return None
    if df is None or df.empty:
        return None
    return df


def fetch_multiple_stocks(tickers: List[str], period: str = "90d", interval: str = "1d") -> dict:
    """
    Fetch OHLC harian untuk daftar ticker (kandidat hasil screener), 1 request per ticker.
    Kembalikan dict {ticker_asli: DataFrame}. Kegagalan 1 ticker di-skip (tidak menggagalkan
    seluruh batch). Pacing & retry ditangani di data_provider.

    Catatan: ticker dikembalikan dengan bentuk asli yang diminta caller (mis. tetap 'BBCA'
    kalau caller kasih 'BBCA'), supaya konsisten dengan state_manager & signal_tracker.
    """
    results: dict = {}
    start_s, end_s = _period_to_range(period)
    total = len(tickers)
    if total == 0:
        return results

    logger.info("Fetching OHLC Invezgo untuk %d kandidat (range %s..%s, %d workers)",
                total, start_s, end_s, FETCH_WORKERS)

    def _one(ticker: str) -> tuple[str, Optional[pd.DataFrame]]:
        code = strip_suffix(ticker)
        try:
            return ticker, fetch_chart(code, start_s, end_s)
        except InvezgoError as e:
            logger.warning("Skip %s: %s", code, e)
            return ticker, None

    # Fetch paralel — rate limiter global di data_provider tetap membatasi laju
    # total req/detik, jadi thread hanya menutupi latensi I/O tanpa memicu burst.
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
        futures = [pool.submit(_one, t) for t in tickers]
        for fut in as_completed(futures):
            ticker, df = fut.result()
            if df is not None and not df.empty:
                results[ticker] = df

    logger.info("Berhasil fetch %d/%d kandidat", len(results), total)
    return results


def get_latest_data(df: pd.DataFrame) -> dict:
    """Data candle terakhir sebagai dict."""
    if df is None or len(df) == 0:
        return {}
    latest = df.iloc[-1]
    return {
        "open": latest["open"],
        "high": latest["high"],
        "low": latest["low"],
        "close": latest["close"],
        "volume": latest["volume"],
        "timestamp": df.index[-1],
    }


def resolve_previous_close(df: pd.DataFrame, ticker: Optional[str] = None) -> float:
    """
    Close sesi sebelumnya untuk hitung % perubahan hari ini.

    Data Invezgo (OHLC harian resmi IDX) tidak punya glitch intraday seperti Yahoo,
    jadi cukup pakai close bar sebelum-terakhir — tanpa heuristik repair/quote fallback
    yang dulu diperlukan untuk yfinance.
    """
    if df is None or len(df) < 2:
        return 0.0
    try:
        dates = pd.DatetimeIndex(df.index).date
        latest_date = dates[-1]
        previous_positions = [i for i, day in enumerate(dates) if day < latest_date]
        if not previous_positions:
            return 0.0
        prev_close = float(df["close"].iloc[previous_positions[-1]])
    except (TypeError, ValueError, AttributeError):
        prev_close = float(df["close"].iloc[-2])
    return prev_close if prev_close > 0 else 0.0


def compute_session_change_percent(df: pd.DataFrame, ticker: Optional[str] = None) -> float:
    """% perubahan close terakhir vs penutupan sesi sebelumnya."""
    if df is None or len(df) < 1:
        return 0.0
    current = float(df["close"].iloc[-1])
    prev = resolve_previous_close(df, ticker)
    if prev <= 0:
        return 0.0
    return ((current - prev) / prev) * 100.0


def get_price_change(df: pd.DataFrame, ticker: Optional[str] = None) -> float:
    """Alias — % perubahan dari penutupan sesi sebelumnya."""
    return compute_session_change_percent(df, ticker)
