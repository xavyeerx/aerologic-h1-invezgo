# ============================================
# DATA FETCHER - YAHOO FINANCE (v5.1)
# ============================================
# Uses yf.download() batch mode to avoid rate limiting.
# 657 tickers -> ~13 batch calls instead of 657 individual requests.

import yfinance as yf
import pandas as pd
from typing import Optional, List
import time
import logging

logger = logging.getLogger(__name__)

BATCH_SIZE = 50
BATCH_DELAY = 1.0
MAX_RETRIES = 3


def fetch_stock_data(ticker: str, period: str = "60d", interval: str = "15m") -> Optional[pd.DataFrame]:
    """Fetch single stock data (fallback / utility)."""
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period=period, interval=interval)

        if df.empty:
            return None

        df.columns = df.columns.str.lower()
        required_cols = ['open', 'high', 'low', 'close', 'volume']
        if not all(col in df.columns for col in required_cols):
            return None

        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        return df

    except Exception as e:
        logger.error(f"Error fetching {ticker}: {str(e)}")
        return None


def _download_batch(tickers: List[str], period: str, interval: str, attempt: int = 1) -> dict:
    """Download a batch of tickers using yf.download (single API call)."""
    results = {}
    try:
        data = yf.download(
            tickers=tickers,
            period=period,
            interval=interval,
            group_by='ticker',
            threads=True,
            progress=False,
        )

        if data is None or data.empty:
            return results

        if len(tickers) == 1:
            ticker = tickers[0]
            df = data.copy()
            df.columns = df.columns.str.lower()
            if df.index.tz is not None:
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
                    df.columns = df.columns.str.lower()
                    if df.index.tz is not None:
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
                return _download_batch(tickers, period, interval, attempt + 1)
        logger.error(f"Batch download error: {err_msg}")

    return results


def fetch_multiple_stocks(tickers: List[str], period: str = "60d", interval: str = "15m",
                          delay: float = 0.1) -> dict:
    """
    Fetch data for multiple stocks using batch download.
    Splits tickers into chunks processed via yf.download() to avoid rate limiting.
    """
    results = {}
    total = len(tickers)

    chunks = [tickers[i:i + BATCH_SIZE] for i in range(0, total, BATCH_SIZE)]
    total_chunks = len(chunks)

    logger.info(f"Batch download: {total} tickers in {total_chunks} chunks of {BATCH_SIZE}")

    for idx, chunk in enumerate(chunks):
        batch_results = _download_batch(chunk, period, interval)
        results.update(batch_results)

        fetched_so_far = len(results)
        logger.info(f"Chunk {idx + 1}/{total_chunks} done | "
                     f"Got {len(batch_results)}/{len(chunk)} | "
                     f"Total: {fetched_so_far}/{total}")

        if idx < total_chunks - 1:
            time.sleep(BATCH_DELAY)

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


def get_price_change(df: pd.DataFrame) -> float:
    """Calculate price change percentage from previous close"""
    if df is None or len(df) < 2:
        return 0.0
    
    current = df['close'].iloc[-1]
    previous = df['close'].iloc[-2]
    
    if previous == 0:
        return 0.0
    
    return ((current - previous) / previous) * 100
