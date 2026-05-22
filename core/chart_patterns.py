# ============================================
# DAILY CHART PATTERN HEURISTICS (MVP)
# ============================================
# Bar sinyal = candle harian TERAKHIR di seri (= sesi H / hari yang sama untuk reviu malam).
# Dengan anchor fetch WIB + slot ~20:00, itu sesuai tutup IDX hari H — bukan skenario pagi yang
# umumnya memakai bar "kemarin" (efek H-1). Panjang riwayat OHLC tetap mengikuti DATA_PERIOD
# (biasanya 90d) dari data_fetcher. Heuristik kasar — bukan gambar pola manual.

from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

from config.settings import (
    CHART_BASE_LOOKBACK,
    CHART_BREAK_BUFFER,
    CHART_CONVERGENCE_CORR_THRESHOLD,
    CHART_CONVERGENCE_LOOKBACK,
    CHART_FALLING_WEDGE_CORR_HI,
    CHART_FALLING_WEDGE_SLOPE_MIN,
    CHART_NARROWING_RATIO,
    CHART_PENNANT_IMPULSE_LOOKBACK,
    CHART_PENNANT_IMPULSE_MIN_PCT,
    CHART_PENNANT_MAX_RANGE_PCT,
    CHART_TOUCH_ATR_MULT,
    CHART_HARM_FIB_RATIO,
    CHART_HARM_ZONE_ATR_MULT,
    CHART_FALSE_BREAK_LOOKBACK,
    CHART_MIN_BARS,
    EMA_FAST,
    EMA_MEDIUM,
    VOLUME_PERIOD,
    ATR_PERIOD,
)
from .indicators import calculate_rsi, calculate_sma, calculate_volume_analysis


def _atr(df: pd.DataFrame) -> float:
    if len(df) < ATR_PERIOD + 1:
        return 0.0
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - df["close"].shift(1)).abs()
    tr3 = (df["low"] - df["close"].shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return float(tr.rolling(window=ATR_PERIOD).mean().iloc[-1])


def _avg_volume_ratio(df: pd.DataFrame) -> float:
    if "volume" not in df.columns or len(df) < VOLUME_PERIOD + 1:
        return 1.0
    av = df["volume"].rolling(window=VOLUME_PERIOD).mean().iloc[-1]
    if av <= 0:
        return 1.0
    return float(df["volume"].iloc[-1] / av)


def _poly_line(x: np.ndarray, y: np.ndarray) -> tuple[float, float] | None:
    if len(x) < 5 or np.any(~np.isfinite(y)):
        return None
    try:
        m, b = np.polyfit(x, y, 1)
        if not np.isfinite(m) or not np.isfinite(b):
            return None
        return float(m), float(b)
    except (np.linalg.LinAlgError, ValueError):
        return None


def detect_bullish_chart_patterns(df: pd.DataFrame) -> Dict[str, bool]:
    """
    Kembalikan flag pola bullish pada bar terakhir DataFrame (= sesi H ketika fetch di-anchor
    ke kalender WIB untuk analisis malam; bukan memaksa H-1). Tanpa bullish divergence
    (sudah ditangani di indicators terpisah).
    """
    out = {
        "break_base": False,
        "sym_triangle_break": False,
        "falling_wedge_break": False,
        "bullish_pennant": False,
        "reject_dynamic_support": False,
        "reject_harmonic_support": False,
        "false_break_support": False,
    }

    if df is None or len(df) < CHART_MIN_BARS:
        return out

    last = df.iloc[-1]
    close = float(last["close"])
    if close <= 0:
        return out

    atr = _atr(df)
    vol_mult = _avg_volume_ratio(df)

    # --- Break the base (range breakout) ---
    w = CHART_BASE_LOOKBACK
    if len(df) >= w + 3:
        box = df.iloc[-(w + 1) : -1]
        bh = float(box["high"].max())
        bl = float(box["low"].min())
        box_range = bh - bl
        if bh > 0 and box_range / bh <= 0.18 and close > bh * (1.0 + CHART_BREAK_BUFFER):
            out["break_base"] = vol_mult >= 1.0

    # --- Convergence patterns (sym triangle / falling wedge) on pre-signal window ---
    K = CHART_CONVERGENCE_LOOKBACK
    if len(df) >= K + 3:
        seg = df.iloc[-(K + 1) : -1]
        n = len(seg)
        x = np.arange(n, dtype=float)
        hi = seg["high"].to_numpy(dtype=float)
        lo = seg["low"].to_numpy(dtype=float)

        c_hi = np.corrcoef(x, hi)[0, 1]
        c_lo = np.corrcoef(x, lo)[0, 1]
        if not np.isfinite(c_hi) or not np.isfinite(c_lo):
            c_hi = c_lo = 0.0

        rh = _poly_line(x, hi)
        rl = _poly_line(x, lo)
        if rh and rl:
            m_h, b_h = rh
            m_l, b_l = rl
            early = seg.iloc[: max(5, n // 3)]
            late = seg.iloc[-max(5, n // 3) :]
            range_early = float(early["high"].max() - early["low"].min())
            range_late = float(late["high"].max() - late["low"].min())
            narrowing_ok = range_early > 0 and range_late / range_early <= CHART_NARROWING_RATIO

            proj_x = float(n)
            res = m_h * proj_x + b_h
            sup = m_l * proj_x + b_l

            if narrowing_ok and res > sup and close > res * (1.0 + CHART_BREAK_BUFFER):
                th = CHART_CONVERGENCE_CORR_THRESHOLD
                if (
                    c_hi <= -th
                    and c_lo >= th
                    and m_h < 0
                    and m_l > 0
                ):
                    out["sym_triangle_break"] = vol_mult >= 0.95
                if (
                    close > 0
                    and m_h < 0
                    and m_l < 0
                    and c_hi <= -CHART_FALLING_WEDGE_CORR_HI
                    and (m_l - m_h) / close >= CHART_FALLING_WEDGE_SLOPE_MIN
                ):
                    out["falling_wedge_break"] = vol_mult >= 0.95

    # --- Bullish pennant: impulse lalu konsolidasi sempit, close break high konsolidasi ---
    imp = CHART_PENNANT_IMPULSE_LOOKBACK
    pen = max(8, CHART_CONVERGENCE_LOOKBACK // 2)
    if len(df) >= imp + pen + 5:
        impulse_seg = df.iloc[-(imp + pen + 1) : -(pen + 1)]
        flag_seg = df.iloc[-(pen + 1) : -1]
        if len(impulse_seg) > 3 and len(flag_seg) > 3:
            lo_i = float(impulse_seg["low"].min())
            hi_i = float(impulse_seg["high"].max())
            if lo_i > 0:
                impulse_pct = (hi_i - lo_i) / lo_i * 100.0
                fh = float(flag_seg["high"].max())
                fl = float(flag_seg["low"].min())
                flag_range_pct = (fh - fl) / close * 100.0 if close else 99.0
                if (
                    impulse_pct >= CHART_PENNANT_IMPULSE_MIN_PCT
                    and flag_range_pct <= CHART_PENNANT_MAX_RANGE_PCT
                    and close > fh * (1.0 + CHART_BREAK_BUFFER * 0.5)
                ):
                    out["bullish_pennant"] = vol_mult >= 0.9

    # --- Reject dynamic support (SMA20 / SMA50): sentuh salah satu, close di atas keduanya ---
    low = float(last["low"])
    open_ = float(last.get("open", close))
    ma20 = float(calculate_sma(df["close"], EMA_FAST).iloc[-1])
    ma50 = float(calculate_sma(df["close"], EMA_MEDIUM).iloc[-1])
    if atr > 0 and np.isfinite(ma20) and np.isfinite(ma50) and ma20 > 0 and ma50 > 0:
        tb20 = (CHART_TOUCH_ATR_MULT * atr) / ma20
        tb50 = (CHART_TOUCH_ATR_MULT * atr) / ma50
        touch20 = low <= ma20 * (1.0 + tb20) and low >= ma20 * (1.0 - tb20 * 1.5)
        touch50 = low <= ma50 * (1.0 + tb50) and low >= ma50 * (1.0 - tb50 * 1.5)
        touched = touch20 or touch50
        reclaimed = close > ma20 and close > ma50 and close >= open_
        if touched and reclaimed:
            out["reject_dynamic_support"] = True

    # --- Reject "harmonic" support (zona fib kasar pada range terakhir) ---
    if atr > 0:
        win = df.iloc[-45:-3]
        if len(win) > 10:
            hi = float(win["high"].max())
            lo = float(win["low"].min())
            if hi > lo:
                lvl = lo + CHART_HARM_FIB_RATIO * (hi - lo)
                band = CHART_HARM_ZONE_ATR_MULT * atr
                low = float(last["low"])
                if low <= lvl + band and low >= lvl - band * 2 and close > lvl:
                    out["reject_harmonic_support"] = True

    # --- False break support (bear trap ringan) ---
    lb = CHART_FALSE_BREAK_LOOKBACK
    if len(df) >= lb + 3:
        support = float(df["low"].iloc[-(lb + 1) : -1].min())
        if support > 0:
            prior = df.iloc[-2]
            broke_down = float(prior["low"]) < support * (1.0 - CHART_BREAK_BUFFER * 0.5)
            reclaimed = close > support and close > float(last.get("open", close))
            if broke_down and reclaimed:
                out["false_break_support"] = True

    return out


PATTERN_LABELS = {
    "break_base": "Break the Base",
    "sym_triangle_break": "Symmetrical Triangle Breakout",
    "falling_wedge_break": "Falling Wedge Breakout",
    "bullish_pennant": "Bullish Pennant",
    "reject_dynamic_support": "Reject Dynamic Support",
    "reject_harmonic_support": "Reject Harmonic Support",
    "false_break_support": "False Break Support",
}


def passes_chart_alert_quality_filters(df: pd.DataFrame) -> bool:
    """
    Konfirmasi sebelum alert pola: aturan volume vs MA20,
    OBV di atas EMA-nya (akumulasi). RSI tidak difilter — nilai RSI(14)
    dibawa ke Telegram agar pengguna menilai sendiri.

    - Close naik vs hari sebelumnya: volume >= 1× MA20
    - Close turun / doji: volume <= 1× MA20 (penurunan tanpa dominasi jual besar)
    """
    if len(df) < VOLUME_PERIOD + 3:
        return False

    if "rsi" not in df.columns:
        calculate_rsi(df)
    if "obv_bullish" not in df.columns:
        calculate_volume_analysis(df)

    row = df.iloc[-1]

    vr = row.get("volume_ratio")
    if pd.isna(vr) or float(vr) <= 0:
        return False
    vr = float(vr)

    c = float(row["close"])
    pc = float(df["close"].iloc[-2])
    if c > pc:
        if vr < 1.0:
            return False
    else:
        if vr > 1.0:
            return False

    if not bool(row.get("obv_bullish", False)):
        return False
    return True
