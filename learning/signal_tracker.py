# ============================================================
# LEARNING / SIGNAL_TRACKER.PY — Catat sinyal ke PostgreSQL
# ============================================================
# Dipanggil dari main.py setelah send_all_alerts() berhasil.
# Menyimpan setiap sinyal + seluruh konteks teknikalnya ke DB
# sehingga outcome engine bisa mengevaluasi hasilnya nanti.
#
# PRINSIP: Error di sini TIDAK BOLEH menghentikan bot.
#          Semua exception ditangkap dan di-log saja.
# ============================================================

import logging
from typing import Optional
from datetime import datetime
import pytz

from learning.db import get_connection, is_available

logger = logging.getLogger(__name__)

WIB = pytz.timezone('Asia/Jakarta')

_INSERT_SQL = """
    INSERT INTO signal_history (
        ticker, signal_type, sent_at,
        entry_price, tp1_price, tp2_price, tp2_source, sl_price,
        score, adx, volume_ratio, stoch_k, macd_bullish, obv_bullish,
        market_regime, bars_since_breakout, price_vs_supertrend_pct,
        ihsg_adx, ihsg_momentum_5d_pct, prev_signal_outcome,
        atr_pct, correction_depth_pct
    ) VALUES (
        %(ticker)s, %(signal_type)s, %(sent_at)s,
        %(entry_price)s, %(tp1_price)s, %(tp2_price)s, %(tp2_source)s, %(sl_price)s,
        %(score)s, %(adx)s, %(volume_ratio)s, %(stoch_k)s, %(macd_bullish)s, %(obv_bullish)s,
        %(market_regime)s, %(bars_since_breakout)s, %(price_vs_supertrend_pct)s,
        %(ihsg_adx)s, %(ihsg_momentum_5d_pct)s, %(prev_signal_outcome)s,
        %(atr_pct)s, %(correction_depth_pct)s
    )
"""

_PREV_OUTCOME_SQL = """
    SELECT outcome_10d
    FROM signal_history
    WHERE ticker = %s
      AND evaluation_done = TRUE
    ORDER BY sent_at DESC
    LIMIT 1
"""

_SIGNAL_TYPE_MAP = {
    'strong_buy':   'STRONG_BUY',
    'early_entry': 'EARLY_ENTRY',
    'reversal_watch': 'REVERSAL_WATCH',
}


def _get_prev_outcome(conn, ticker: str) -> str:
    """Ambil outcome sinyal terakhir untuk ticker ini (None jika belum ada)"""
    try:
        with conn.cursor() as cur:
            cur.execute(_PREV_OUTCOME_SQL, (ticker,))
            row = cur.fetchone()
            return row[0] if row else 'NONE'
    except Exception:
        return 'NONE'


def _safe_float(val, default: float = 0.0) -> float:
    """Convert ke float, return default jika None atau NaN"""
    try:
        f = float(val)
        return f if f == f else default   # NaN check
    except (TypeError, ValueError):
        return default


def track_signal(scan_result, signal_type_key: str, regime_info: dict) -> bool:
    """
    Catat satu sinyal ke database learning.

    Args:
        scan_result    : ScanResult object dari scanner.py
        signal_type_key: key dari dict sinyal ('strong_buy', 'accumulation', dll)
        regime_info    : dict dari market_regime.get_market_regime()

    Return True jika berhasil, False jika gagal/DB tidak ada.
    """
    if not is_available():
        return False

    conn = get_connection()
    if not conn:
        return False

    try:
        r = scan_result
        signal_type_db = _SIGNAL_TYPE_MAP.get(signal_type_key, signal_type_key.upper())
        entry_price    = _safe_float(r.price)
        sl_price       = _safe_float(getattr(r, 'sl', 0)) or round(entry_price * 0.95, 2)

        # Ambil prev outcome untuk ticker ini
        prev_outcome = _get_prev_outcome(conn, r.ticker)

        record = {
            'ticker':                  r.ticker,
            'signal_type':             signal_type_db,
            'sent_at':                 datetime.now(WIB).isoformat(),

            # Harga & target
            'entry_price':             entry_price,
            'tp1_price':               _safe_float(getattr(r, 'tp1', 0)),
            'tp2_price':               _safe_float(getattr(r, 'tp2', 0)),
            'tp2_source':              getattr(r, 'tp2_source', 'ATR'),
            'sl_price':                sl_price,

            # Indikator teknikal
            'score':                   int(getattr(r, 'score', 0)),
            'adx':                     _safe_float(getattr(r, 'adx', 0)),
            'volume_ratio':            _safe_float(getattr(r, 'volume_ratio', 0)),
            'stoch_k':                 _safe_float(getattr(r, 'stoch_k', 50)),
            'macd_bullish':            bool(getattr(r, 'macd_status', '').startswith('🟢') or
                                           'BULL' in getattr(r, 'macd_status', '') or
                                           'UP'   in getattr(r, 'macd_status', '')),
            'obv_bullish':             'ACC' in getattr(r, 'obv_status', ''),

            # Konteks teknikal tambahan
            'market_regime':           regime_info.get('regime', 'UNKNOWN'),
            'bars_since_breakout':     int(getattr(r, 'bars_since_breakout', 0)),
            'price_vs_supertrend_pct': _safe_float(getattr(r, 'price_vs_supertrend_pct', 0)),
            'ihsg_adx':                _safe_float(regime_info.get('adx', 0)),
            # Legacy DB column; value now means five closed H1 bars.
            'ihsg_momentum_5d_pct':    _safe_float(regime_info.get('momentum_5bar', 0)),
            'prev_signal_outcome':     prev_outcome,
            'atr_pct':                 _safe_float(getattr(r, 'atr_pct', 0)),
            'correction_depth_pct':    _safe_float(getattr(r, 'correction_percent', 0)),
        }

        with conn.cursor() as cur:
            cur.execute(_INSERT_SQL, record)
        conn.commit()

        logger.info(f"[SignalTracker] ✅ Recorded: {r.ticker} {signal_type_db} "
                    f"@ {entry_price:.0f} | TP1={record['tp1_price']:.0f} "
                    f"TP2={record['tp2_price']:.0f} ({record['tp2_source']}) "
                    f"SL={sl_price:.0f} | Regime={record['market_regime']}")
        return True

    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"[SignalTracker] ❌ Gagal record {scan_result.ticker}: {e}")
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


def track_all_signals(new_signals: dict, regime_info: dict) -> int:
    """
    Record semua sinyal baru ke DB dalam satu batch.

    Args:
        new_signals : dict dari main.py {'strong_buy': [...], 'accumulation': [...], ...}
        regime_info : dict dari market_regime.get_market_regime()

    Return jumlah sinyal yang berhasil direcord.
    """
    if not is_available():
        logger.debug("[SignalTracker] DB tidak tersedia — tracking dilewati")
        return 0

    tracked = 0
    for signal_type_key, signal_list in new_signals.items():
        for result in signal_list:
            ok = track_signal(result, signal_type_key, regime_info)
            if ok:
                tracked += 1

    if tracked > 0:
        logger.info(f"[SignalTracker] Total {tracked} sinyal berhasil direcord ke DB")
    return tracked


def get_active_signal_tickers_by_type(lookback_days: int = 14) -> dict:
    """
    Ambil sinyal ACTIVE terbaru dari PostgreSQL untuk kebutuhan recap.

    ACTIVE didefinisikan sebagai:
      - evaluation_done = FALSE
      - dan belum pernah hit TP1/TP2

    Return format:
      {'strong_buy': {'BBCA.JK', ...}, 'early_entry': {...}, 'reversal_watch': {...}}
    """
    active = {
        'strong_buy': set(),
        'early_entry': set(),
        'reversal_watch': set(),
    }

    if not is_available():
        return active

    conn = get_connection()
    if not conn:
        return active

    sql = """
        SELECT DISTINCT ON (ticker, signal_type)
            ticker, signal_type, sent_at, evaluation_done, tp1_hit, tp2_hit
        FROM signal_history
        WHERE sent_at >= NOW() - (%s || ' days')::interval
        ORDER BY ticker, signal_type, sent_at DESC
    """

    reverse_map = {v: k for k, v in _SIGNAL_TYPE_MAP.items()}

    try:
        with conn.cursor() as cur:
            cur.execute(sql, (lookback_days,))
            rows = cur.fetchall()

        for ticker, signal_type, _sent_at, evaluation_done, tp1_hit, tp2_hit in rows:
            signal_key = reverse_map.get(signal_type)
            if signal_key is None:
                continue

            # Done signals are excluded from recap:
            # - already fully evaluated, or
            # - already hit TP1/TP2
            done = bool(evaluation_done) or bool(tp1_hit) or bool(tp2_hit)
            if not done:
                active[signal_key].add(ticker)

    except Exception as e:
        logger.warning(f"[SignalTracker] Gagal ambil active signals: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return active
