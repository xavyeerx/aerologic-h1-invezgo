# ============================================
# DATA FETCHER - YAHOO FINANCE (v5.1)
# ============================================
# Uses yf.download() batch mode to avoid rate limiting.
# 657 tickers -> ~13 batch calls instead of 657 individual requests.

import warnings
import yfinance as yf
import pandas as pd
from typing import Optional, List, Tuple
import time
import logging
from datetime import datetime, timedelta

import pytz

# yfinance (scrapers/history.py) memanggil Timestamp.utcnow() yang di-deprecate pandas 2.2+ —
# muncul berulang tiap batch; bukan bug aplikasi. Filter spesifik supaya log tetap bersih.
warnings.filterwarnings(
    "ignore",
    message=r".*[Tt]imestamp\.utcnow.*",
)

logger = logging.getLogger(__name__)

BATCH_SIZE = 50
BATCH_DELAY = 1.0
MAX_RETRIES = 3

# DATA_PERIOD (mis. 90d) = target lebar seri; buffer kalender tambah hari non-dagang/libur IDX
# agar Yahoo mengembalikan cukup bar harian tanpa mengubah makna "90d" di settings.
DAILY_FETCH_CALENDAR_BUFFER_DAYS = 45
WIB = pytz.timezone("Asia/Jakarta")


def _yahoo_daily_start_end(period: str) -> tuple[str, str]:
    """
    Harian: parse N dari string period (mis. 90d -> N=90). Start mundur N + buffer kalender
    (bukan memperlebar "90d" secara konfigurasi — hanya supaya cukup bar dagang di Yahoo).

    End = besok WIB (eksklusif yfinance) supaya **bar penutupan sesi hari H** ikut (reviu malam),
    bukan pola jadwal pagi yang sering setara memakai candle "kemarin".
    """
    hint = 90
    if isinstance(period, str) and period.endswith("d"):
        try:
            hint = int(period[:-1])
        except ValueError:
            pass
    days_back = hint + DAILY_FETCH_CALENDAR_BUFFER_DAYS
    today_wib = datetime.now(WIB).date()
    start = today_wib - timedelta(days=days_back)
    end_excl = today_wib + timedelta(days=1)
    return start.strftime("%Y-%m-%d"), end_excl.strftime("%Y-%m-%d")


def _yahoo_current_month_daily_start_end() -> Tuple[str, str]:
    """Unduhan singkat dari tgl 1 bulan berjalan (WIB) — memperbaiki bug yfinance OHLC NaN pada bar terakhir saat rentang panjang."""
    today_wib = datetime.now(WIB).date()
    tail_s = today_wib.replace(day=1).strftime("%Y-%m-%d")
    end_s = (today_wib + timedelta(days=1)).strftime("%Y-%m-%d")
    return tail_s, end_s


def _repair_yahoo_daily_nan_close(df: pd.DataFrame) -> pd.DataFrame:
    """
    Yahoo sering mengembalikan bar harian terakhir dengan volume terisi
    tetapi Close (dan kadang Open) NaN pada unduhan rentang panjang.
    Isi close dengan mid H–L bila memungkinkan (harga khas masuk akal untuk IDX).
    """
    if df is None or df.empty or "close" not in df.columns:
        return df
    out = df.copy()
    na_c = out["close"].isna()
    if not na_c.any():
        return out
    hi = pd.to_numeric(out["high"], errors="coerce")
    lo = pd.to_numeric(out["low"], errors="coerce")
    hl2 = (hi + lo) / 2.0
    fix = na_c & hi.notna() & lo.notna()
    if fix.any():
        out.loc[fix, "close"] = hl2.loc[fix]
        op_bad = fix & out["open"].isna()
        if op_bad.any():
            out.loc[op_bad, "open"] = out.loc[op_bad, "close"]
    return out


def _flatten_yfinance_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    yfinance unduhan satu simbol: kolom bisa MultiIndex (Ticker, Price) bukan (Price, Ticker).
    Samakan nama kolom menjadi open/high/low/close/volume (lower-case).
    """
    if df is None or df.empty:
        return df
    out = df.copy()
    OHLC_HINT = {"open", "high", "low", "close", "volume", "adj close"}

    if isinstance(out.columns, pd.MultiIndex):
        lvl0 = out.columns.get_level_values(0).astype(str).str.strip()
        lvl1 = out.columns.get_level_values(1).astype(str).str.strip().str.lower()
        if lvl1.isin(OHLC_HINT).any():
            names = list(lvl1)
        elif lvl0.str.lower().isin(OHLC_HINT).any():
            names = list(lvl0.str.lower())
        else:
            names = list(lvl1)
        out.columns = names
    else:
        out.columns = [str(c).lower().strip() for c in out.columns]

    if "adj close" in out.columns:
        aj = pd.to_numeric(out["adj close"], errors="coerce")
        if "close" not in out.columns:
            out["close"] = aj
        else:
            oc = pd.to_numeric(out["close"], errors="coerce")
            miss = oc.isna()
            out.loc[miss, "close"] = aj.loc[miss]
        out = out.drop(columns=["adj close"], errors="ignore")
    return out


def _finalize_daily_ohlc_index(df: pd.DataFrame) -> pd.DataFrame:
    """Samakan label tanggal ke kalender Jakarta (naive date, tanpa shift UTC)."""
    if df is None or df.empty:
        return df
    out = df.copy()
    ix = pd.DatetimeIndex(pd.to_datetime(out.index))
    if ix.tz is not None:
        ix = ix.tz_convert("Asia/Jakarta")
    out.index = pd.to_datetime(ix.strftime("%Y-%m-%d"))
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out


def fetch_stock_data(ticker: str, period: str = "60d", interval: str = "15m") -> Optional[pd.DataFrame]:
    """Fetch single stock data (fallback / utility)."""
    try:
        stock = yf.Ticker(ticker)
        if interval == "1d":
            start_s, end_s = _yahoo_daily_start_end(period)
            df = stock.history(start=start_s, end=end_s, interval=interval, auto_adjust=True)
            if df.empty:
                return None
            df = _flatten_yfinance_columns(df)
            required_cols = ['open', 'high', 'low', 'close', 'volume']
            if not all(col in df.columns for col in required_cols):
                return None
            df = _finalize_daily_ohlc_index(df)
            df = _repair_yahoo_daily_nan_close(df)
            mt_s, mt_e = _yahoo_current_month_daily_start_end()
            tail = stock.history(start=mt_s, end=mt_e, interval=interval, auto_adjust=True)
            if not tail.empty:
                tail = _flatten_yfinance_columns(tail)
                if all(col in tail.columns for col in required_cols):
                    tail = _finalize_daily_ohlc_index(tail)
                    tail = _repair_yahoo_daily_nan_close(tail)
                    df = (
                        pd.concat([df, tail])
                        .sort_index()
                        .drop_duplicates(keep="last")
                    )
                    df = _repair_yahoo_daily_nan_close(df)
            df = df.dropna(subset=["close"])
        else:
            df = stock.history(period=period, interval=interval, auto_adjust=True)
            if df.empty:
                return None
            df = _flatten_yfinance_columns(df)
            required_cols = ['open', 'high', 'low', 'close', 'volume']
            if not all(col in df.columns for col in required_cols):
                return None

        if interval != "1d" and df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        return df

    except Exception as e:
        logger.error(f"Error fetching {ticker}: {str(e)}")
        return None


def _download_batch(
    tickers: List[str],
    period: str,
    interval: str,
    attempt: int = 1,
    *,
    daily_start: Optional[str] = None,
    daily_end: Optional[str] = None,
) -> dict:
    """Download a batch of tickers using yf.download (single API call)."""
    results = {}
    try:
        kwargs: dict = {
            "tickers": tickers,
            "interval": interval,
            "group_by": "ticker",
            "threads": True,
            "progress": False,
            "auto_adjust": True,
        }
        if interval == "1d":
            if daily_start and daily_end:
                kwargs["start"] = daily_start
                kwargs["end"] = daily_end
            else:
                ds, de = _yahoo_daily_start_end(period)
                kwargs["start"] = ds
                kwargs["end"] = de
        else:
            kwargs["period"] = period

        data = yf.download(**kwargs)

        if data is None or data.empty:
            return results

        if len(tickers) == 1:
            ticker = tickers[0]
            df = data.copy()
            df = _flatten_yfinance_columns(df)
            if interval == "1d":
                df = _finalize_daily_ohlc_index(df)
                df = _repair_yahoo_daily_nan_close(df)
            elif df.index.tz is not None:
                df.index = df.index.tz_localize(None)
            df = df.dropna(subset=['close'])
            if not df.empty:
                results[ticker] = df
        else:
            for ticker in tickers:
                try:
                    if ticker not in data.columns.get_level_values(0):
                        continue
                    df = data[ticker].copy()
                    df = _flatten_yfinance_columns(df)
                    if interval == "1d":
                        df = _finalize_daily_ohlc_index(df)
                        df = _repair_yahoo_daily_nan_close(df)
                    elif df.index.tz is not None:
                        df.index = df.index.tz_localize(None)
                    df = df.dropna(subset=['close'])
                    if not df.empty and len(df) > 0:
                        results[ticker] = df
                except Exception:
                    pass

    except Exception as e:
        err_msg = str(e)
        if 'Rate' in err_msg or 'Too Many' in err_msg or '429' in err_msg:
            if attempt < MAX_RETRIES:
                wait = BATCH_DELAY * (2 ** attempt)
                logger.warning(f"Rate limited on batch (attempt {attempt}), waiting {wait:.0f}s...")
                time.sleep(wait)
                return _download_batch(
                    tickers, period, interval, attempt + 1,
                    daily_start=daily_start, daily_end=daily_end,
                )
        logger.error(f"Batch download error: {err_msg}")

    return results


def _merge_daily_month_tail_overlay(results: dict, period: str, interval: str, delay: float) -> dict:
    """
    yfinance dapat merusak OHLC bar terakhir bila rentang start terlalu jauh.
    Gabung overlay dari tgl 1 bulan kalender WIB — bar atas tanggal yang sama diganti versi pendek itu.
    """
    if interval != "1d" or not results:
        return results
    mt_s, mt_e = _yahoo_current_month_daily_start_end()
    logger.info(
        "Daily OHLC tail overlay WIB %s .. %s (gabung perbaikan bar terakhir)",
        mt_s,
        mt_e,
    )
    tickers_all = list(results.keys())
    subchunks = [tickers_all[i : i + BATCH_SIZE] for i in range(0, len(tickers_all), BATCH_SIZE)]
    for idx, chunk in enumerate(subchunks):
        overlay = _download_batch(chunk, period, interval, daily_start=mt_s, daily_end=mt_e)
        for t in chunk:
            ov = overlay.get(t)
            if ov is None or t not in results:
                continue
            merged = (
                pd.concat([results[t], ov])
                .sort_index()
                .drop_duplicates(keep="last")
            )
            merged = _repair_yahoo_daily_nan_close(merged)
            results[t] = merged.dropna(subset=["close"])
        if idx < len(subchunks) - 1:
            time.sleep(delay)
    return results


def fetch_multiple_stocks(tickers: List[str], period: str = "60d", interval: str = "15m",
                          delay: float = 0.1) -> dict:
    """
    Fetch data for multiple stocks using batch download.
    Splits tickers into chunks processed via yf.download() to avoid rate limiting.
    Untuk interval 1d: parse DATA_PERIOD (mis. 90d), anchor end ke hari ini WIB (bar sinyal = H
    untuk reviu malam), tail overlay perbaiki bug OHLC Yahoo; buffer kalender hanya untuk cukup bar dagang.
    """
    results = {}
    total = len(tickers)

    if interval == "1d":
        s, e = _yahoo_daily_start_end(period)
        logger.info("Daily OHLC: WIB anchored range start=%s end=%s (Yahoo exclusive)", s, e)

    chunks = [tickers[i:i + BATCH_SIZE] for i in range(0, total, BATCH_SIZE)]
    total_chunks = len(chunks)

    logger.info(f"Batch download: {total} tickers in {total_chunks} chunks of {BATCH_SIZE}")

    for idx, chunk in enumerate(chunks):
        batch_results = _download_batch(chunk, period, interval)
        results.update(batch_results)

        fetched_so_far = len(results)
        logger.debug(f"Chunk {idx + 1}/{total_chunks} done | "
                     f"Got {len(batch_results)}/{len(chunk)} | "
                     f"Total: {fetched_so_far}/{total}")

        if idx < total_chunks - 1:
            time.sleep(BATCH_DELAY)

    if interval == "1d" and results:
        results = _merge_daily_month_tail_overlay(results, period, interval, BATCH_DELAY)

    logger.info(f"Successfully fetched {len(results)}/{total} stocks")
    return results


def get_latest_data(df: pd.DataFrame) -> dict:
    """Get latest candle data as dictionary"""
    if df is None or len(df) == 0:
        return {}
    
    latest = df.iloc[-1]
    return {
        'open': latest['open'],
        'high': latest['high'],
        'low': latest['low'],
        'close': latest['close'],
        'volume': latest['volume'],
        'timestamp': df.index[-1]
    }


def resolve_previous_close(df: pd.DataFrame, ticker: Optional[str] = None) -> float:
    """
    Close sesi sebelumnya untuk hitung % perubahan hari ini.

    Saat pasar IDX masih buka, Yahoo kadang mengisi bar kemarin dengan close yang
    mendekati harga live (mis. 134 vs 109) sehingga iloc[-2] salah dan % jadi ~0,7%
    padahal naik >20%. Perbaikan: quote previousClose dulu, lalu heuristik open vs bar.
    """
    if df is None or len(df) < 1:
        return 0.0

    current = float(df["close"].iloc[-1])
    if ticker and current > 0:
        quoted = _yahoo_previous_close_quote(ticker)
        if quoted and quoted > 0:
            return quoted

    if len(df) < 2:
        return 0.0

    prior = df.iloc[:-1]
    prev_close = float(prior["close"].iloc[-1])
    if prev_close <= 0:
        return 0.0

    today_open = None
    if "open" in df.columns:
        try:
            o = float(df["open"].iloc[-1])
            if o > 0 and o == o:
                today_open = o
        except (TypeError, ValueError):
            pass

    if today_open is None:
        return prev_close

    gap_open_prev = abs(today_open - prev_close) / prev_close
    chg_vs_prev = abs((current - prev_close) / prev_close) if prev_close else 0.0

    # Pola bug Yahoo intraday: prev_close ~ harga sekarang, open jauh di bawah/atas
    if gap_open_prev > 0.12 and chg_vs_prev < 0.025:
        for i in range(len(prior) - 1, -1, -1):
            pc = float(prior["close"].iloc[i])
            if pc > 0 and abs(today_open - pc) / pc <= 0.06:
                if ticker:
                    quoted = _yahoo_previous_close_quote(ticker)
                    if quoted and quoted > 0 and abs(today_open - quoted) / quoted <= 0.06:
                        return quoted
                return pc
        if ticker:
            repaired = _yahoo_previous_close_quote(ticker)
            if repaired and repaired > 0:
                return repaired

    return prev_close


def _yahoo_previous_close_quote(ticker: str) -> Optional[float]:
    """Fallback: previous close dari quote Yahoo (biasanya selaras broker IDX)."""
    try:
        fi = yf.Ticker(ticker).fast_info
        for key in ("regularMarketPreviousClose", "previous_close", "previousClose"):
            v = getattr(fi, key, None)
            if v is None and hasattr(fi, "get"):
                v = fi.get(key)
            if v is not None:
                f = float(v)
                if f > 0:
                    return f
    except Exception:
        pass
    return None


def compute_session_change_percent(df: pd.DataFrame, ticker: Optional[str] = None) -> float:
    """% perubahan close terakhir vs penutupan sesi sebelumnya (diperbaiki untuk intraday)."""
    if df is None or len(df) < 1:
        return 0.0
    current = float(df["close"].iloc[-1])
    prev = resolve_previous_close(df, ticker)
    if prev <= 0:
        return 0.0
    return ((current - prev) / prev) * 100.0


def get_price_change(df: pd.DataFrame, ticker: Optional[str] = None) -> float:
    """Calculate price change percentage from previous session close."""
    return compute_session_change_percent(df, ticker)
