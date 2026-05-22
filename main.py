# ============================================
# IHSG SUPERTREND SCANNER - MAIN ENTRY POINT
# ============================================

import sys
import os
import gc
import logging
import logging.handlers
from datetime import datetime
import pytz

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.settings import *
from config.stocks_list import get_all_stocks, get_stock_count
from core.data_fetcher import fetch_multiple_stocks, compute_session_change_percent
from core.scanner import scan_all_stocks, filter_signals, filter_all_current_signals, has_any_signal
from database.state_manager import StateManager
from notifications.telegram_bot import send_all_alerts, send_startup_message, send_daily_recap_message, send_chart_pattern_morning_digest

# ── Learning system (graceful degradation jika DB tidak ada) ───────────
try:
    from learning.db import init_db, is_available as db_available
    from learning.market_regime import get_market_regime
    from learning.signal_tracker import track_all_signals, get_active_signal_tickers_by_type
    _LEARNING_IMPORTS_OK = True
except ImportError as e:
    _LEARNING_IMPORTS_OK = False
    def db_available(): return False
    def get_market_regime(**kw): return {'regime': 'UNKNOWN', 'adx': 0.0, 'momentum_5d': 0.0}
    def track_all_signals(*a, **kw): return 0
    def get_active_signal_tickers_by_type(*a, **kw):
        return {'strong_buy': set(), 'accumulation': set(), 'early_entry': set()}
    def init_db(): return False

# Setup logging
os.makedirs('logs', exist_ok=True)
os.makedirs('database', exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            'logs/scanner.log',
            encoding='utf-8',
            maxBytes=5 * 1024 * 1024,  # 5 MB max per file
            backupCount=3              # keep last 3 files
        )
    ]
)
logger = logging.getLogger(__name__)

# Timezone
WIB = pytz.timezone('Asia/Jakarta')


def is_trading_hours() -> bool:
    """Check if current time is within trading hours"""
    now = datetime.now(WIB)
    
    # Skip weekends
    if now.weekday() >= 5:
        return False
    
    # Check trading hours (08:45 - 16:00 WIB)
    current_time = now.hour * 100 + now.minute
    start_time = TRADING_START_HOUR * 100 + TRADING_START_MINUTE
    end_time = TRADING_END_HOUR * 100 + TRADING_END_MINUTE
    
    return start_time <= current_time <= end_time


def is_market_open_time() -> bool:
    """Check if current time is market open time (08:45) — for opening recap"""
    now = datetime.now(WIB)
    return now.hour == TRADING_START_HOUR and now.minute == TRADING_START_MINUTE


def is_market_close_time() -> bool:
    """Check if current time is market close time (16:00) — for closing recap"""
    now = datetime.now(WIB)
    return now.hour == TRADING_END_HOUR and now.minute >= TRADING_END_MINUTE and now.minute <= TRADING_END_MINUTE + 5


def collect_new_chart_pattern_alerts(
    stock_data: dict,
    state_manager: StateManager,
    *,
    telegram_test_mode: bool = False,
) -> list:
    """
    Kumpulkan baris pola chart TF-D yang lolos filter dan belum pernah di-alert hari ini.
    Tidak menulis dedup ke disk — caller memanggil persist setelah Telegram sukses.
    """
    from core.chart_patterns import (
        detect_bullish_chart_patterns,
        PATTERN_LABELS,
        CHART_MIN_BARS,
        passes_chart_alert_quality_filters,
    )

    alerts: list = []
    for ticker, df in stock_data.items():
        if df is None or len(df) < CHART_MIN_BARS:
            continue
        try:
            dx = df.copy()
            dx["turnover"] = dx["close"] * dx["volume"]
            avg_to = dx["turnover"].rolling(window=5).mean().iloc[-1]
            if avg_to < MIN_DAILY_TURNOVER:
                continue

            flags = detect_bullish_chart_patterns(dx)
            if not any(flags.values()):
                continue
            if not passes_chart_alert_quality_filters(dx):
                continue

            _rsi_raw = dx["rsi"].iloc[-1]
            try:
                rsi14 = float(_rsi_raw)
                if rsi14 != rsi14:  # NaN
                    rsi14 = None
            except (TypeError, ValueError):
                rsi14 = None

            price = float(dx["close"].iloc[-1])
            chg = compute_session_change_percent(dx, ticker)
            avg_vol = float(dx["volume"].rolling(window=VOLUME_PERIOD).mean().iloc[-1])
            vm = float(dx["volume"].iloc[-1] / avg_vol) if avg_vol > 0 else 1.0

            for pk, fired in flags.items():
                if not fired:
                    continue
                if (not telegram_test_mode) and state_manager.is_chart_combo_alerted(ticker, pk):
                    continue
                alerts.append({
                    "ticker": ticker,
                    "pattern_key": pk,
                    "label": PATTERN_LABELS.get(pk, pk),
                    "price": price,
                    "change_pct": chg,
                    "vol_vs_avg": vm,
                    "rsi14": rsi14,
                })
        except Exception as e:
            logger.warning(f"Chart pattern skip {ticker}: {e}")
    return alerts


def persist_chart_pattern_alert_rows(state_manager: StateManager, alerts: list) -> None:
    for row in alerts:
        state_manager.add_chart_pattern_alert(row["ticker"], row["pattern_key"])


def run_scan(state_manager: StateManager, force: bool = False) -> dict:
    """
    Run a single scan cycle.
    Only sends alerts for NEW signals that haven't been alerted today.
    
    Args:
        state_manager: StateManager instance
        force: If True, run even outside trading hours
    
    Returns:
        Dictionary with scan results summary
    """
    # Check trading hours
    if not force and not is_trading_hours():
        logger.info("Outside trading hours. Skipping scan.")
        return {'skipped': True, 'reason': 'Outside trading hours'}
    
    logger.info("=" * 50)
    logger.info("Starting IHSG Supertrend Scan")
    logger.info("=" * 50)
    
    # Get stock list
    stocks = get_all_stocks()
    logger.info(f"Scanning {len(stocks)} stocks...")
    
    # Fetch data
    logger.info("Fetching data from Yahoo Finance...")
    stock_data = fetch_multiple_stocks(stocks, period=DATA_PERIOD, interval=DATA_INTERVAL)
    logger.info(f"Fetched data for {len(stock_data)} stocks")
    
    if len(stock_data) == 0:
        logger.error("No data fetched. Aborting scan.")
        return {'error': 'No data fetched'}
    
    # Get previous states
    previous_states = state_manager.get_all_states()
    
    # Reset daily alerts if new day
    state_manager.reset_daily_if_new_day()

    # Scan all stocks
    logger.info("Analyzing stocks...")
    results = scan_all_stocks(stock_data, previous_states)

    chart_pattern_new_rows = 0

    # ── Ambil kondisi pasar IHSG (untuk learning tracking) ───────────
    regime_info = {'regime': 'UNKNOWN', 'adx': 0.0, 'momentum_5d': 0.0}
    if _LEARNING_IMPORTS_OK:
        try:
            regime_info = get_market_regime()
        except Exception as e:
            logger.warning(f"[Learning] Gagal ambil market regime: {e}")

    # Filter signals
    all_signals = filter_signals(results)
    
    # Filter for NEW signals only (not already alerted today)
    new_signals = {}
    for signal_type, signal_list in all_signals.items():
        new_only = [r for r in signal_list if not state_manager.is_already_alerted(signal_type, r.ticker)]
        new_signals[signal_type] = new_only
        
        # Log signal counts
        if len(signal_list) > 0:
            logger.info(f"  {signal_type}: {len(signal_list)} total, {len(new_only)} new")
    
    # Send alerts for NEW signals only (skip if nothing new)
    if has_any_signal(new_signals):
        logger.info("Sending Telegram alerts for NEW signals...")
        messages_sent = send_all_alerts(new_signals)
        logger.info(f"Sent {messages_sent} alert messages")
        
        # Mark these stocks as alerted for today + track for TP/SL evaluation
        for signal_type, signal_list in new_signals.items():
            for r in signal_list:
                state_manager.add_alerted_stock(signal_type, r.ticker)
                state_manager.track_signal(r, signal_type)

        # ── Learning: catat sinyal ke DB ──────────────────────────────
        if _LEARNING_IMPORTS_OK:
            try:
                tracked = track_all_signals(new_signals, regime_info)
                if tracked > 0:
                    logger.info(f"[Learning] {tracked} sinyal direcord ke DB")
            except Exception as e:
                logger.warning(f"[Learning] Tracking error (bot tetap jalan): {e}")
    else:
        logger.info("No NEW signals detected this scan")

    # Pola chart hanya lewat scheduler (15:30) kecuali CHART_PATTERN_REALTIME=true
    # dan CHART_PATTERN_FORCE_SCHEDULED_ONLY=false di settings/.env
    if CHART_PATTERN_REALTIME:
        try:
            cp_alerts = collect_new_chart_pattern_alerts(
                stock_data, state_manager, telegram_test_mode=False
            )
            if cp_alerts:
                ok_cp = send_chart_pattern_morning_digest(
                    cp_alerts, test_mode=False, realtime=True
                )
                if ok_cp:
                    persist_chart_pattern_alert_rows(state_manager, cp_alerts)
                    chart_pattern_new_rows = len(cp_alerts)
                    logger.info(
                        f"Chart patterns (realtime): {chart_pattern_new_rows} new row(s) sent"
                    )
                else:
                    logger.warning(
                        "Chart patterns (realtime): Telegram send failed; dedup not updated"
                    )
        except Exception as e:
            logger.warning(f"Chart patterns (realtime): {e}")

    del stock_data
    gc.collect()

    # Update states
    logger.info("Updating stock states...")
    for ticker, result in results.items():
        state_manager.update_from_scan_result(result)
    state_manager.save()
    
    # Summary
    stocks_count = len(results)
    summary = {
        'stocks_scanned': stocks_count,
        'strong_buys': len(new_signals['strong_buy']),
        'accumulations': len(new_signals['accumulation']),
        'early_entries': len(new_signals['early_entry']),
        'chart_pattern_new_rows': chart_pattern_new_rows,
        'timestamp': datetime.now(WIB).isoformat()
    }
    
    logger.info("Scan complete!")
    logger.info(f"Summary: {summary}")
    logger.info("=" * 50)
    
    return summary


def run_morning_chart_pattern_scan(state_manager: StateManager, stock_data=None, telegram_test_mode: bool = False):
    """
    Deteksi pola chart bullish TF daily pada **bar terakhir seri** (= sesi H setelah pasar tutup;
    tidak memaksa H-1 seperti skenario digest pagi). Dipanggil maksimal sekali per hari —
    scheduler slot reviu ~20:00 WIB (jendela singkat). Fetch memakai DATA_PERIOD (mis. 90d).
    Jika stock_data hasil fetch sudah ada (mis. dari run_scan), dipakai lagi agar tidak fetch ganda.

    telegram_test_mode: jalankan lagi + kirim Telegram tanpa blokir "sudah scan hari ini" dan tanpa tulis dedup pola
                         (uji manual: ``python main.py morning-patterns --telegram-test``).
    """
    from core.data_fetcher import fetch_multiple_stocks

    state_manager.reset_daily_if_new_day()

    if (
        not telegram_test_mode
        and state_manager.morning_chart_patterns_already_scanned_today()
    ):
        logger.info("Morning chart patterns: skip — sudah diproses hari ini.")
        return

    logger.info("=" * 50)
    logger.info("MORNING CHART PATTERN SCAN (TF-D)" + (" [TELEGRAM TEST]" if telegram_test_mode else ""))
    logger.info("=" * 50)

    own_fetch = stock_data is None
    if own_fetch:
        stocks = get_all_stocks()
        logger.info(f"Chart patterns: fetching {len(stocks)} tickers ({DATA_INTERVAL})...")
        stock_data = fetch_multiple_stocks(stocks, period=DATA_PERIOD, interval=DATA_INTERVAL)
    elif not stock_data:
        logger.warning("Morning chart patterns: stock_data kosong, skip.")
        if not telegram_test_mode:
            state_manager.mark_morning_chart_patterns_scan_complete()
        return

    if len(stock_data) == 0:
        logger.warning("Morning chart patterns: tidak ada data, skip.")
        if not telegram_test_mode:
            state_manager.mark_morning_chart_patterns_scan_complete()
        return

    alerts = collect_new_chart_pattern_alerts(
        stock_data, state_manager, telegram_test_mode=telegram_test_mode
    )

    if own_fetch:
        del stock_data
        gc.collect()

    if alerts:
        logger.info(
            "Morning chart patterns: %s%s alert row(s)"
            % (len(alerts), " (telegram test)" if telegram_test_mode else " new")
        )
        ok = send_chart_pattern_morning_digest(
            alerts, test_mode=telegram_test_mode, realtime=False
        )
        if ok and not telegram_test_mode:
            persist_chart_pattern_alert_rows(state_manager, alerts)
    else:
        logger.info("Morning chart patterns: no new setups")
        if telegram_test_mode:
            send_chart_pattern_morning_digest([], test_mode=True, realtime=False)

    if not telegram_test_mode:
        state_manager.mark_morning_chart_patterns_scan_complete()

    logger.info("=" * 50)


def run_full_recap(state_manager: StateManager, recap_type: str = "OPENING"):
    """
    Run a full recap scan at market open (08:45) or close (16:00).
    This scans ALL stocks and sends a comprehensive overview.
    No duplicate check here — this is a full overview, sent only once.
    """
    logger.info("=" * 50)
    logger.info(f"{recap_type} RECAP SCAN")
    logger.info("=" * 50)
    
    # Get stock list
    stocks = get_all_stocks()
    logger.info(f"Recap scan: {len(stocks)} stocks...")
    
    # Fetch data
    logger.info("Fetching data from Yahoo Finance...")
    stock_data = fetch_multiple_stocks(stocks, period=DATA_PERIOD, interval=DATA_INTERVAL)
    logger.info(f"Fetched data for {len(stock_data)} stocks")
    
    if len(stock_data) == 0:
        logger.error("No data fetched. Aborting recap scan.")
        return
    
    # Get previous states
    previous_states = state_manager.get_all_states()
    
    # Scan all stocks
    logger.info("Analyzing stocks for recap...")
    results = scan_all_stocks(stock_data, previous_states)
    
    # ✅ FREE MEMORY: release large DataFrames immediately after scan
    del stock_data
    gc.collect()
    
    # Get ALL current matching signals, excluding those that already hit TP/SL
    all_current_signals = filter_all_current_signals(results, state_manager=state_manager)

    # Recap filter mode:
    # - BROAD  (default): tampilkan semua sinyal current match
    # - STRICT           : batasi hanya ticker ACTIVE dari DB tracker
    recap_filter_mode = os.getenv("RECAP_FILTER_MODE", "BROAD").strip().upper()
    if recap_filter_mode == "STRICT" and _LEARNING_IMPORTS_OK and db_available():
        active_map = get_active_signal_tickers_by_type(lookback_days=14)
        logger.info(
            "[Recap] Active signals from DB: "
            f"SB={len(active_map['strong_buy'])}, "
            f"ACC={len(active_map['accumulation'])}, "
            f"EE={len(active_map['early_entry'])}, "
        )

        for signal_type in ('strong_buy', 'accumulation', 'early_entry'):
            allowed_tickers = active_map.get(signal_type, set())
            all_current_signals[signal_type] = [
                r for r in all_current_signals[signal_type] if r.ticker in allowed_tickers
            ]

        # Bullish category has no direct DB signal_type. Keep only tickers that are active
        # in at least one actionable bucket to avoid stale bullish names.
        actionable = (
            active_map.get('strong_buy', set())
            | active_map.get('accumulation', set())
            | active_map.get('early_entry', set())
        )
        all_current_signals['bullish'] = [
            r for r in all_current_signals['bullish'] if r.ticker in actionable
        ]
    else:
        logger.info(f"[Recap] Filter mode: {recap_filter_mode} (tanpa pembatas ACTIVE-only DB)")
    
    # Count total signals
    total_signals = sum(len(v) for v in all_current_signals.values())
    
    if total_signals == 0:
        logger.info("No matching signals found in recap scan.")
        return

    if recap_type == "OPENING":
        # Opening recap: scan + update state saja — tidak kirim "EVENING SCAN" ke Telegram
        logger.info(
            f"Opening recap: {total_signals} saham match (state diperbarui, tanpa broadcast Telegram)."
        )
    elif recap_type == "CLOSING":
        daily_summary = state_manager.get_daily_summary()
        total_daily = sum(len(v) for k, v in daily_summary.items() if k != 'date')
        if total_daily > 0:
            send_daily_recap_message(daily_summary)
    
    # Update states
    logger.info("Updating stock states...")
    for ticker, result in results.items():
        state_manager.update_from_scan_result(result)
    state_manager.save()
    
    logger.info(f"{recap_type} recap complete!")
    logger.info("=" * 50)


def run_daily_evaluation(state_manager: StateManager):
    """
    Evaluate all tracked signals at 16:30 WIB.
    Check which signals hit TP1, TP2, or SL today, and send performance recap.
    """
    logger.info("=" * 50)
    logger.info("DAILY SIGNAL EVALUATION (16:30)")
    logger.info("=" * 50)

    active_signals = state_manager.get_active_signals()
    if not active_signals:
        logger.info("No active signals to evaluate.")
        return

    tickers_needed = list(set(s['ticker'] for s in active_signals))
    logger.info(f"Evaluating {len(active_signals)} active signals across {len(tickers_needed)} tickers...")

    from core.data_fetcher import fetch_multiple_stocks
    stock_data = fetch_multiple_stocks(tickers_needed, period='5d', interval='1d')

    current_prices = {}
    high_prices = {}
    for ticker, df in stock_data.items():
        if df is not None and len(df) > 0:
            current_prices[ticker] = df['close'].iloc[-1]
            high_prices[ticker] = df['high'].iloc[-1]

    for s in active_signals:
        ticker = s['ticker']
        if ticker in high_prices:
            intraday_high = high_prices[ticker]
            if intraday_high > s.get('high_since_entry', s['entry_price']):
                current_prices[ticker] = max(current_prices.get(ticker, 0), intraday_high)

    eval_prices = {}
    for s in active_signals:
        ticker = s['ticker']
        if ticker in high_prices and ticker in current_prices:
            tp1 = s.get('tp1', 0)
            tp2 = s.get('tp2', 0)
            if (tp1 and high_prices[ticker] >= tp1) or (tp2 and high_prices[ticker] >= tp2):
                eval_prices[ticker] = high_prices[ticker]
            else:
                sl = s.get('sl', 0)
                if sl and current_prices[ticker] <= sl:
                    eval_prices[ticker] = current_prices[ticker]
                else:
                    eval_prices[ticker] = current_prices[ticker]
        elif ticker in current_prices:
            eval_prices[ticker] = current_prices[ticker]

    outcome = state_manager.evaluate_signals(eval_prices)

    state_manager.cleanup_old_signals(max_age_days=30)

    from notifications.telegram_bot import send_evaluation_message
    send_evaluation_message(outcome)

    logger.info(f"Evaluation complete: {len(outcome['tp1_hit'])} TP1, "
                 f"{len(outcome['tp2_hit'])} TP2, {len(outcome['sl_hit'])} SL, "
                 f"{len(outcome['active'])} still active")
    logger.info("=" * 50)


def main():
    """Main entry point"""
    os.makedirs('logs', exist_ok=True)
    os.makedirs('database', exist_ok=True)

    logger.info("IHSG Supertrend Scanner starting...")

    # Init learning DB (tidak wajib — bot tetap jalan tanpa DB)
    if _LEARNING_IMPORTS_OK:
        try:
            ok = init_db()
            if ok:
                logger.info("[Learning] ✅ PostgreSQL learning database siap")
            else:
                logger.info("[Learning] ⚠️ DB tidak tersedia — learning dinonaktifkan")
        except Exception as e:
            logger.warning(f"[Learning] DB init error: {e}")

    # Initialize state manager
    state_manager = StateManager()

    # Check if this is first run
    if len(state_manager.get_all_states()) == 0:
        logger.info("First run detected. Initial scan will not generate alerts.")
        logger.info("This is to establish baseline states for all stocks.")

    # Run scan
    run_scan(state_manager, force=True)


def run_with_notification():
    """Run with startup notification"""
    os.makedirs('logs', exist_ok=True)
    os.makedirs('database', exist_ok=True)
    
    logger.info("IHSG Supertrend Scanner starting with notification...")
    
    # Send startup message
    send_startup_message()
    
    # Initialize and run
    state_manager = StateManager()
    run_scan(state_manager, force=True)


if __name__ == "__main__":
    argv = sys.argv[1:]
    if argv and argv[0] in ("morning-patterns", "morning-charts"):
        os.makedirs("logs", exist_ok=True)
        os.makedirs("database", exist_ok=True)
        _telegram_test = "--telegram-test" in argv or "--test" in argv
        _sm = StateManager()
        run_morning_chart_pattern_scan(_sm, telegram_test_mode=_telegram_test)
    else:
        main()
