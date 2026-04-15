# ============================================================
# LEARNING / MARKET_REGIME.PY — IHSG Market Regime Detection
# ============================================================
# Mendeteksi kondisi pasar IHSG (BULL/BEAR/SIDEWAYS) menggunakan
# 3 konfirmasi: MA posisi, ADX, dan momentum 5 hari.
#
# Dipakai oleh signal_tracker untuk mencatat konteks pasar
# saat sinyal dikirim — salah satu fitur pembelajaran terpenting.
# ============================================================

import logging
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional

import yfinance as yf

logger = logging.getLogger(__name__)

IHSG_TICKER   = "^JKSE"
FETCH_PERIOD  = "120d"    # data historis yang diambil
ADX_PERIOD    = 14
MA_SHORT      = 20
MA_LONG       = 50

# Cache hasil agar tidak re-fetch setiap scan (maks 1 fetch per 4 jam)
_cache: dict = {
    "regime":       "UNKNOWN",
    "adx":          0.0,
    "momentum_5d":  0.0,
    "ma20":         0.0,
    "ma50":         0.0,
    "last_fetch":   None,
}
_CACHE_TTL_HOURS = 4


def _calculate_adx(df: pd.DataFrame, period: int = ADX_PERIOD) -> pd.Series:
    """Simple ADX calculation (tidak import dari core untuk hindari circular import)"""
    high  = df['high']
    low   = df['low']
    close = df['close']

    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low  - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()

    plus_dm  = high.diff().clip(lower=0)
    minus_dm = (-low.diff()).clip(lower=0)
    plus_dm  = plus_dm.where(plus_dm > (-low.diff()).clip(lower=0), 0)
    minus_dm = minus_dm.where(minus_dm > high.diff().clip(lower=0), 0)

    plus_di  = 100 * (plus_dm.rolling(period).mean()  / atr)
    minus_di = 100 * (minus_dm.rolling(period).mean() / atr)

    dx  = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx = dx.rolling(period).mean()
    return adx


def _fetch_ihsg() -> Optional[pd.DataFrame]:
    """Fetch IHSG daily data dari Yahoo Finance"""
    try:
        data = yf.download(
            IHSG_TICKER,
            period=FETCH_PERIOD,
            interval="1d",
            progress=False,
            auto_adjust=True
        )
        if data is None or data.empty or len(data) < MA_LONG + ADX_PERIOD:
            logger.warning("[MarketRegime] Data IHSG tidak cukup")
            return None

        data.columns = data.columns.str.lower()
        if data.index.tz is not None:
            data.index = data.index.tz_localize(None)
        return data.dropna(subset=['close'])
    except Exception as e:
        logger.warning(f"[MarketRegime] Gagal fetch IHSG: {e}")
        return None


def _detect_regime(df: pd.DataFrame) -> dict:
    """
    Tentukan market regime berdasarkan 3 indikator:

    BULL   → IHSG di atas MA20 DAN MA50
              AND ADX > 20 (ada momentum)
              AND momentum 5d > +1%

    BEAR   → IHSG di bawah MA20 DAN MA50
              AND momentum 5d < -1.5%

    SIDEWAYS → semua kondisi lainnya
               (IHSG antara dua MA, atau ADX lemah)
    """
    close = df['close']

    ma20 = close.rolling(MA_SHORT).mean()
    ma50 = close.rolling(MA_LONG).mean()
    adx  = _calculate_adx(df)

    latest_close = close.iloc[-1]
    latest_ma20  = ma20.iloc[-1]
    latest_ma50  = ma50.iloc[-1]
    latest_adx   = adx.iloc[-1]

    # Momentum 5 hari
    if len(close) >= 6:
        momentum_5d = ((latest_close - close.iloc[-6]) / close.iloc[-6]) * 100
    else:
        momentum_5d = 0.0

    # Tentukan regime
    above_ma20 = latest_close > latest_ma20
    above_ma50 = latest_close > latest_ma50
    strong_trend = latest_adx > 20

    if above_ma20 and above_ma50 and strong_trend and momentum_5d > 1.0:
        regime = "BULL"
    elif (not above_ma20) and (not above_ma50) and momentum_5d < -1.5:
        regime = "BEAR"
    else:
        regime = "SIDEWAYS"

    return {
        "regime":      regime,
        "adx":         round(float(latest_adx), 2) if not np.isnan(latest_adx) else 0.0,
        "momentum_5d": round(float(momentum_5d), 2),
        "ma20":        round(float(latest_ma20), 2) if not np.isnan(latest_ma20) else 0.0,
        "ma50":        round(float(latest_ma50), 2) if not np.isnan(latest_ma50) else 0.0,
        "close":       round(float(latest_close), 2),
    }


def get_market_regime(force_refresh: bool = False) -> dict:
    """
    Ambil kondisi pasar IHSG.

    Return dict dengan keys:
      regime      : 'BULL' / 'BEAR' / 'SIDEWAYS' / 'UNKNOWN'
      adx         : float — ADX IHSG composite
      momentum_5d : float — % change IHSG 5 hari terakhir
      ma20        : float
      ma50        : float
      close       : float — harga penutupan IHSG terakhir

    Menggunakan cache (TTL 4 jam) agar tidak re-fetch setiap scan.
    """
    global _cache

    now = datetime.now()
    cache_expired = (
        _cache["last_fetch"] is None or
        (now - _cache["last_fetch"]) > timedelta(hours=_CACHE_TTL_HOURS)
    )

    if force_refresh or cache_expired:
        df = _fetch_ihsg()
        if df is not None:
            result = _detect_regime(df)
            _cache = {**result, "last_fetch": now}
            logger.info(
                f"[MarketRegime] IHSG: {result['regime']} | "
                f"ADX={result['adx']} | Mom5d={result['momentum_5d']:+.1f}% | "
                f"MA20={result['ma20']:.0f} MA50={result['ma50']:.0f}"
            )
        else:
            # Pertahankan cache lama jika fetch gagal
            logger.warning("[MarketRegime] Fetch gagal, pakai data cache lama")
            if _cache["last_fetch"] is None:
                # Belum pernah berhasil fetch sama sekali
                return {
                    "regime": "UNKNOWN", "adx": 0.0,
                    "momentum_5d": 0.0, "ma20": 0.0,
                    "ma50": 0.0, "close": 0.0
                }

    return {k: v for k, v in _cache.items() if k != "last_fetch"}
