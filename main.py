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
from core.data_fetcher import fetch_multiple_stocks
from core.scanner import scan_all_stocks, filter_signals, filter_all_current_signals, has_any_signal
from database.state_manager import StateManager
from notifications.telegram_bot import send_all_alerts, send_startup_message, send_daily_recap_message, send_morning_recap_message

# ── Learning system (graceful degradation jika DB tidak ada) ───────────
try:
    from learning.db import init_db, is_available as db_available
    from learning.market_regime import get_market_regime
    from learning.signal_tracker import track_all_signals
    _LEARNING_IMPORTS_OK = True
except ImportError as e:
    _LEARNING_IMPORTS_OK = False
    def db_available(): return False
    def get_market_regime(**kw): return {'regime': 'UNKNOWN', 'adx': 0.0, 'momentum_5d': 0.0}
    def track_all_signals(*a, **kw): return 0
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
    
    # ✅ FREE MEMORY: release large DataFrames immediately after scan
    del stock_data
    gc.collect()

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
        
        # Mark these stocks as alerted for today
        for signal_type, signal_list in new_signals.items():
            for r in signal_list:
                state_manager.add_alerted_stock(signal_type, r.ticker)

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
        'bull_divs': len(new_signals['bull_div']),
        'timestamp': datetime.now(WIB).isoformat()
    }
    
    logger.info("Scan complete!")
    logger.info(f"Summary: {summary}")
    logger.info("=" * 50)
    
    return summary


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
    
    # Get ALL current matching signals (not filtering for new-only)
    all_current_signals = filter_all_current_signals(results)
    
    # Count total signals
    total_signals = sum(len(v) for v in all_current_signals.values())
    
    if total_signals == 0:
        logger.info("No matching signals found in recap scan.")
        return
    
    # (Dihapus/dimatikan sesuai permintaan: hanya gunakan realtime & end of day recap)
    # logger.info(f"Sending {recap_type} recap with {total_signals} total signals...")
    # send_morning_recap_message(all_current_signals)
    
    # If it's market close, also send daily summary
    if recap_type == "CLOSING":
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
    main()
