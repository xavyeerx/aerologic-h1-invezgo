# ============================================================
# LEARNING / OUTCOME_CHECKER.PY — Evaluasi hasil sinyal
# ============================================================
# Dijalankan setiap hari jam 16:30 WIB (setelah market close).
# Mengambil semua sinyal yang belum di-evaluasi dari DB,
# fetch data harga harian, lalu tentukan outcome-nya.
#
# Outcome evaluation strategy:
#   - Proses bar OHLC hari per hari secara berurutan
#   - Jika LOW <= SL → HIT_SL (stop, SL prioritas)
#   - Jika HIGH >= TP2 → HIT_TP2
#   - Jika HIGH >= TP1 → tp1_hit = True (terus pantau TP2)
#   - Setelah 10 trading days → final outcome
#
# PRINSIP: Error di sini TIDAK BOLEH menghentikan bot.
# ============================================================

import logging
import pytz
from datetime import datetime, timedelta, date
from typing import Optional

import pandas as pd
import yfinance as yf

from learning.db import get_connection, is_available
from notifications.telegram_bot import send_telegram_message

logger = logging.getLogger(__name__)

WIB = pytz.timezone('Asia/Jakarta')

SL_PERCENT     = 0.05  # 5% di bawah entry
MAX_EVAL_DAYS  = 10    # evaluasi final di hari ke-10
PARTIAL_WIN_PCT = 2.0  # min gain untuk PARTIAL_WIN

# Kandidat outcome per hari
PENDING   = 'PENDING'
HIT_TP2   = 'HIT_TP2'
HIT_TP1   = 'HIT_TP1'
PARTIAL   = 'PARTIAL_WIN'
BREAKEVEN = 'BREAKEVEN'
HIT_SL    = 'HIT_SL'
NO_MOVE   = 'NO_MOVEMENT'
REVERSAL  = 'REVERSAL'


# ─────────────────────────────────────────────────────────────
# Helper: Fetch & Utility
# ─────────────────────────────────────────────────────────────

def _count_trading_days(from_date: date, to_date: date) -> int:
    """Hitung trading days (Senin-Jumat) antara dua tanggal"""
    current = from_date + timedelta(days=1)
    count = 0
    while current <= to_date:
        if current.weekday() < 5:
            count += 1
        current += timedelta(days=1)
    return count


def _fetch_daily_ohlc(ticker: str, from_date: date, to_date: date) -> Optional[pd.DataFrame]:
    """Fetch data OHLC harian untuk satu ticker dalam rentang tanggal"""
    try:
        start_str = from_date.strftime('%Y-%m-%d')
        # +2 hari buffer untuk memastikan data hari terakhir masuk
        end_str = (to_date + timedelta(days=2)).strftime('%Y-%m-%d')

        data = yf.download(
            ticker,
            start=start_str,
            end=end_str,
            interval='1d',
            progress=False,
            auto_adjust=True
        )
        if data is None or data.empty:
            return None
        data.columns = data.columns.str.lower()
        if data.index.tz is not None:
            data.index = data.index.tz_localize(None)
        # Ambil hanya bar setelah signal date
        data = data[data.index.date > from_date]
        return data if not data.empty else None
    except Exception as e:
        logger.warning(f"[OutcomeChecker] Gagal fetch {ticker}: {e}")
        return None


# ─────────────────────────────────────────────────────────────
# Core: Evaluate outcome dari OHLC data
# ─────────────────────────────────────────────────────────────

def _evaluate_signal(entry: float, tp1: float, tp2: float, sl: float,
                     ohlc: pd.DataFrame, trading_days_passed: int) -> dict:
    """
    Proses bar OHLC hari per hari dan tentukan outcome.

    Return dict:
      outcome_1d, outcome_3d, outcome_5d, outcome_10d
      tp1_hit, tp2_hit
      max_gain_pct, max_drawdown_pct
      days_to_tp1, days_to_tp2, days_to_outcome
    """
    result = {
        'outcome_1d':       PENDING,
        'outcome_3d':       PENDING,
        'outcome_5d':       PENDING,
        'outcome_10d':      PENDING,
        'tp1_hit':          False,
        'tp2_hit':          False,
        'max_gain_pct':     0.0,
        'max_drawdown_pct': 0.0,
        'days_to_tp1':      None,
        'days_to_tp2':      None,
        'days_to_outcome':  None,
        'evaluation_done':  False,
    }

    if ohlc is None or ohlc.empty or entry <= 0:
        return result

    final_outcome   = PENDING
    trade_day       = 0
    max_gain        = 0.0
    max_drawdown    = 0.0

    for _, bar in ohlc.iterrows():
        trade_day += 1
        high  = float(bar['high'])
        low   = float(bar['low'])
        close = float(bar['close'])

        # Update max gain & drawdown
        day_gain = (high  - entry) / entry * 100
        day_loss = (low   - entry) / entry * 100
        max_gain     = max(max_gain,     day_gain)
        max_drawdown = min(max_drawdown, day_loss)

        # ── Evaluasi per bar (prioritas: SL > TP2 > TP1) ──────────
        if low <= sl:
            # Stop Loss kena
            if final_outcome == PENDING:
                final_outcome = HIT_SL
                result['days_to_outcome'] = trade_day
            break   # trade selesai

        if high >= tp2:
            result['tp2_hit']    = True
            result['tp1_hit']    = True  # TP2 berarti TP1 juga sudah terlewati
            if result['days_to_tp2'] is None:
                result['days_to_tp2'] = trade_day
            if result['days_to_tp1'] is None:
                result['days_to_tp1'] = trade_day
            if final_outcome == PENDING:
                final_outcome = HIT_TP2
                result['days_to_outcome'] = trade_day
            break   # trade selesai (ambil profit)

        if high >= tp1:
            result['tp1_hit'] = True
            if result['days_to_tp1'] is None:
                result['days_to_tp1'] = trade_day
            if final_outcome == PENDING:
                final_outcome = HIT_TP1
                # Tidak break — terus pantau apakah TP2 bisa tercapai

        # ── Update checkpoint outcomes ──────────────────────────────
        current_label = final_outcome if final_outcome != PENDING else _classify_partial(close, entry, max_gain)

        if trade_day == 1:
            result['outcome_1d'] = current_label
        if trade_day == 3:
            result['outcome_3d'] = current_label
        if trade_day == 5:
            result['outcome_5d'] = current_label
        if trade_day >= MAX_EVAL_DAYS:
            result['outcome_10d']     = current_label
            result['evaluation_done'] = True
            if result['days_to_outcome'] is None:
                result['days_to_outcome'] = trade_day
            break

    # Jika belum MAX_EVAL_DAYS tapi data habis — update snapshot terakhir
    if result['outcome_1d'] == PENDING and trading_days_passed >= 1:
        result['outcome_1d'] = final_outcome if final_outcome != PENDING else NO_MOVE
    if result['outcome_3d'] == PENDING and trading_days_passed >= 3:
        result['outcome_3d'] = final_outcome if final_outcome != PENDING else NO_MOVE
    if result['outcome_5d'] == PENDING and trading_days_passed >= 5:
        result['outcome_5d'] = final_outcome if final_outcome != PENDING else NO_MOVE

    # Final jika sudah 10 hari
    if trading_days_passed >= MAX_EVAL_DAYS and not result['evaluation_done']:
        result['outcome_10d']     = final_outcome if final_outcome != PENDING else NO_MOVE
        result['evaluation_done'] = True

    result['max_gain_pct']     = round(max_gain, 2)
    result['max_drawdown_pct'] = round(max_drawdown, 2)
    return result


def _classify_partial(current_close: float, entry: float, max_gain: float) -> str:
    """Tentukan label untuk sinyal yang tidak hit TP/SL"""
    change_pct = (current_close - entry) / entry * 100
    if max_gain >= PARTIAL_WIN_PCT:
        if current_close < entry:
            return REVERSAL    # sempat naik tapi balik turun
        return PARTIAL
    elif abs(change_pct) <= 0.5:
        return BREAKEVEN
    elif change_pct > 0:
        return PARTIAL
    else:
        return NO_MOVE


# ─────────────────────────────────────────────────────────────
# Telegram Notification
# ─────────────────────────────────────────────────────────────

def _format_outcome_message(signal: dict, outcome: dict) -> str:
    """Format pesan Telegram untuk hasil sinyal"""
    ticker       = signal['ticker']
    sig_type     = signal['signal_type'].replace('_', ' ')
    entry        = signal['entry_price']
    tp1          = signal['tp1_price']
    tp2          = signal['tp2_price']
    tp2_src      = signal.get('tp2_source', 'ATR')
    sl           = signal['sl_price']
    sent_at      = signal['sent_at']
    regime       = signal.get('market_regime', 'N/A')
    adx          = signal.get('adx', 0)
    vol_ratio    = signal.get('volume_ratio', 0)
    bars_bo      = signal.get('bars_since_breakout', 0)
    pct_vs_st    = signal.get('price_vs_supertrend_pct', 0)

    final        = outcome.get('outcome_10d') or outcome.get('outcome_5d', PENDING)
    tp1_hit      = outcome.get('tp1_hit', False)
    tp2_hit      = outcome.get('tp2_hit', False)
    max_gain     = outcome.get('max_gain_pct', 0)
    max_dd       = outcome.get('max_drawdown_pct', 0)
    days         = outcome.get('days_to_outcome') or 10
    now          = datetime.now(WIB)

    # Berapa hari lalu sinyal dikirim
    if hasattr(sent_at, 'date'):
        days_ago = (now.date() - sent_at.date()).days
    else:
        days_ago = days

    # Emoji & status
    status_map = {
        HIT_TP2:   ('🏆', 'HIT TP2 — Swing Target!'),
        HIT_TP1:   ('✅', 'HIT TP1 — Quick Target'),
        PARTIAL:   ('📈', 'PARTIAL WIN — Profit tanpa TP'),
        BREAKEVEN: ('➖', 'BREAKEVEN'),
        HIT_SL:    ('❌', 'HIT STOP LOSS'),
        REVERSAL:  ('🔄', 'REVERSAL — Balik setelah naik'),
        NO_MOVE:   ('😴', 'NO MOVEMENT — Stagnan 10 hari'),
    }
    emoji, status_label = status_map.get(final, ('❓', final))

    # TP2 source label
    tp2_label = '📋 resist' if tp2_src == 'RESISTANCE' else '📐 ATR'

    msg = (
        f"📊 <b>HASIL SINYAL — {ticker}</b>\n\n"
        f"📌 {sig_type} | {days_ago} hari lalu\n"
        f"💰 Entry: {entry:,.0f}\n"
        f"🎯 TP1: {tp1:,.0f} {'✅' if tp1_hit else '○'} | "
        f"TP2: {tp2:,.0f} {'✅' if tp2_hit else '○'} {tp2_label}\n"
        f"🛑 SL: {sl:,.0f}\n\n"
        f"{emoji} <b>{status_label}</b>\n"
    )

    if final in (HIT_TP2, HIT_TP1, PARTIAL):
        msg += f"📈 Max Gain: +{max_gain:.1f}%\n"
    elif final == HIT_SL:
        msg += f"📉 Max Drawdown: {max_dd:.1f}%\n"
    elif final == REVERSAL:
        msg += f"📈 Sempat naik: +{max_gain:.1f}% → lalu turun\n"

    msg += (
        f"\n📋 <b>Konteks saat sinyal:</b>\n"
        f"• ADX: {adx:.0f} {'✔️' if adx >= 25 else '⚠️'}\n"
        f"• Volume: {vol_ratio:.1f}× {'✔️' if vol_ratio >= 1.5 else '⚠️'}\n"
        f"• IHSG Regime: {regime}\n"
        f"• Hari breakout ke-{bars_bo} | {pct_vs_st:.1f}% di atas supertrend\n"
    )

    return msg


# ─────────────────────────────────────────────────────────────
# Main: Run outcome check
# ─────────────────────────────────────────────────────────────

def _get_pending_signals(conn) -> list:
    """Ambil semua sinyal yang belum evaluation_done dari DB"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT signal_id, ticker, signal_type, sent_at,
                   entry_price, tp1_price, tp2_price, tp2_source, sl_price,
                   score, adx, volume_ratio, stoch_k, macd_bullish, obv_bullish,
                   market_regime, bars_since_breakout, price_vs_supertrend_pct,
                   ihsg_adx, ihsg_momentum_5d_pct, atr_pct,
                   outcome_1d, outcome_3d, outcome_5d, outcome_10d,
                   tp1_hit, tp2_hit
            FROM signal_history
            WHERE evaluation_done = FALSE
            ORDER BY sent_at ASC
        """)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _update_signal_outcome(conn, signal_id, outcome: dict):
    """Update outcome fields untuk satu sinyal"""
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE signal_history SET
                outcome_1d       = %s,
                outcome_3d       = %s,
                outcome_5d       = %s,
                outcome_10d      = %s,
                tp1_hit          = %s,
                tp2_hit          = %s,
                max_gain_pct     = %s,
                max_drawdown_pct = %s,
                days_to_tp1      = %s,
                days_to_tp2      = %s,
                days_to_outcome  = %s,
                evaluation_done  = %s
            WHERE signal_id = %s
        """, (
            outcome['outcome_1d'],
            outcome['outcome_3d'],
            outcome['outcome_5d'],
            outcome['outcome_10d'],
            outcome['tp1_hit'],
            outcome['tp2_hit'],
            outcome['max_gain_pct'],
            outcome['max_drawdown_pct'],
            outcome['days_to_tp1'],
            outcome['days_to_tp2'],
            outcome['days_to_outcome'],
            outcome['evaluation_done'],
            signal_id,
        ))


def run_outcome_check() -> int:
    """
    Main function: evaluasi semua sinyal pending, update DB,
    kirim notifikasi Telegram untuk sinyal yang baru selesai.

    Dipanggil dari scheduler.py setiap hari jam 16:30 WIB.
    Return jumlah sinyal yang baru di-evaluasi.
    """
    if not is_available():
        logger.debug("[OutcomeChecker] DB tidak tersedia — dilewati")
        return 0

    conn = get_connection()
    if not conn:
        return 0

    evaluated = 0
    notified  = 0

    try:
        pending = _get_pending_signals(conn)
        if not pending:
            logger.info("[OutcomeChecker] Tidak ada sinyal pending untuk dievaluasi")
            conn.close()
            return 0

        logger.info(f"[OutcomeChecker] Mengevaluasi {len(pending)} sinyal pending...")

        today = datetime.now(WIB).date()

        for signal in pending:
            ticker   = signal['ticker']
            entry    = signal.get('entry_price', 0) or 0
            tp1      = signal.get('tp1_price',   0) or 0
            tp2      = signal.get('tp2_price',   0) or 0
            sl       = signal.get('sl_price',    entry * 0.95) or (entry * 0.95)
            sent_at  = signal['sent_at']

            # Pastikan sent_at adalah date object
            if hasattr(sent_at, 'date'):
                signal_date = sent_at.date()
            else:
                signal_date = sent_at

            trading_days = _count_trading_days(signal_date, today)

            # Belum cukup 1 hari trading — lewati
            if trading_days < 1:
                continue

            # Fetch OHLC data
            ohlc = _fetch_daily_ohlc(ticker, signal_date, today)

            # Evaluasi
            outcome = _evaluate_signal(entry, tp1, tp2, sl, ohlc, trading_days)

            # Ada perubahan dari PENDING?
            prev_1d = signal.get('outcome_1d', PENDING)
            prev_3d = signal.get('outcome_3d', PENDING)
            prev_5d = signal.get('outcome_5d', PENDING)

            has_update = (
                outcome['outcome_1d'] != prev_1d or
                outcome['outcome_3d'] != prev_3d or
                outcome['outcome_5d'] != prev_5d or
                outcome['evaluation_done']
            )

            if has_update:
                _update_signal_outcome(conn, signal['signal_id'], outcome)
                evaluated += 1

                # Kirim notif Telegram jika evaluation FINAL selesai
                if outcome['evaluation_done']:
                    try:
                        msg = _format_outcome_message(signal, outcome)
                        send_telegram_message(msg)
                        notified += 1
                        logger.info(
                            f"[OutcomeChecker] ✅ {ticker} {signal['signal_type']} "
                            f"→ {outcome['outcome_10d']} "
                            f"(gain={outcome['max_gain_pct']:+.1f}%)"
                        )
                    except Exception as e:
                        logger.warning(f"[OutcomeChecker] Gagal kirim notif {ticker}: {e}")

        conn.commit()
        logger.info(
            f"[OutcomeChecker] Selesai: {evaluated} diupdate, "
            f"{notified} notifikasi dikirim"
        )
        return evaluated

    except Exception as e:
        logger.error(f"[OutcomeChecker] Error: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return 0
    finally:
        try:
            conn.close()
        except Exception:
            pass
