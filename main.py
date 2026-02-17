# ============================================
# IHSG SUPERTREND SCANNER - MAIN ENTRY POINT
# ============================================

import sys
import os
import logging
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

# Setup logging
os.makedirs('logs', exist_ok=True)
os.makedirs('database', exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/scanner.log', encoding='utf-8')
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
    
    # Check trading hours (08:50 - 16:15 WIB)
    current_time = now.hour * 100 + now.minute
    start_time = TRADING_START_HOUR * 100 + TRADING_START_MINUTE
    end_time = TRADING_END_HOUR * 100 + TRADING_END_MINUTE
    
    return start_time <= current_time <= end_time


def is_market_open_time() -> bool:
    """Check if current time is market open time (08:50) — for opening recap"""
    now = datetime.now(WIB)
    return now.hour == TRADING_START_HOUR and now.minute == TRADING_START_MINUTE


def is_market_close_time() -> bool:
    """Check if current time is market close time (16:15) — for closing recap"""
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
    else:
        logger.info("No NEW signals detected this scan")
    
    # Update states
    logger.info("Updating stock states...")
    for ticker, result in results.items():
        state_manager.update_from_scan_result(result)
    state_manager.save()
    
    # Summary
    summary = {
        'stocks_scanned': len(stock_data),
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
    Run a full recap scan at market open (08:50) or close (16:15).
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
    
    # Get ALL current matching signals (not filtering for new-only)
    all_current_signals = filter_all_current_signals(results)
    
    # Count total signals
    total_signals = sum(len(v) for v in all_current_signals.values())
    
    if total_signals == 0:
        logger.info("No matching signals found in recap scan.")
        return
    
    # Send recap message
    logger.info(f"Sending {recap_type} recap with {total_signals} total signals...")
    send_morning_recap_message(all_current_signals)
    
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
