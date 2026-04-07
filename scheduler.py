# ============================================
# SCHEDULER - RUN SCANS
# ============================================
# Recap: 08:45 (market open) and 16:00 (market close)
# Alerts: every 1 minute during trading hours (only NEW signals)

import schedule
import time
import logging
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import run_scan, is_trading_hours, is_market_open_time, is_market_close_time, run_full_recap
from database.state_manager import StateManager
from notifications.telegram_bot import send_startup_message, send_telegram_message

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/scheduler.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# Global state
state_manager = None
recap_sent_open = False
recap_sent_close = False


def scheduled_scan():
    """Run scheduled scan"""
    global state_manager, recap_sent_open, recap_sent_close
    
    # Reset recap flags at midnight
    from datetime import datetime
    import pytz
    WIB = pytz.timezone('Asia/Jakarta')
    now = datetime.now(WIB)
    if now.hour == 0 and now.minute <= 5:
        recap_sent_open = False
        recap_sent_close = False
    
    # Market Open Recap (08:45) — full overview, sent ONCE
    if is_market_open_time() and not recap_sent_open:
        logger.info("Market open time! Running opening recap...")
        try:
            run_full_recap(state_manager, recap_type="OPENING")
            recap_sent_open = True
        except Exception as e:
            logger.error(f"Error during opening recap: {str(e)}")
            send_telegram_message(f"⚠️ Opening Recap Error: {str(e)}")
        return
    
    # Market Close Recap (16:00) — full overview + daily summary, sent ONCE
    if is_market_close_time() and not recap_sent_close:
        logger.info("Market close time! Running closing recap...")
        try:
            run_full_recap(state_manager, recap_type="CLOSING")
            recap_sent_close = True
        except Exception as e:
            logger.error(f"Error during closing recap: {str(e)}")
            send_telegram_message(f"⚠️ Closing Recap Error: {str(e)}")
        return
    
    # Outside trading hours — skip
    if not is_trading_hours():
        logger.info("Outside trading hours. Waiting...")
        return
    
    # Regular scan during trading hours — only sends NEW signals
    try:
        run_scan(state_manager, force=False)
    except Exception as e:
        logger.error(f"Error during scheduled scan: {str(e)}")
        send_telegram_message(f"⚠️ Scanner Error: {str(e)}")


def main():
    """Main scheduler loop"""
    global state_manager
    
    # Ensure directories exist
    os.makedirs('logs', exist_ok=True)
    os.makedirs('database', exist_ok=True)
    
    logger.info("=" * 50)
    logger.info("IHSG SUPERTREND SCANNER v5.0 - SCHEDULER")
    logger.info("=" * 50)
    logger.info("Scan interval: 1 minute")
    logger.info("Opening recap: 08:45 WIB")
    logger.info("Closing recap: 16:00 WIB")
    logger.info("Trading hours: 08:45 - 16:00 WIB")
    logger.info("=" * 50)
    
    # Initialize state manager
    state_manager = StateManager()
    
    # Send startup notification
    send_startup_message()
    
    # Schedule scans every 1 minute
    for minute in range(0, 60, 1):
        schedule.every().hour.at(f":{minute:02d}").do(scheduled_scan)
    
    logger.info("Scheduler started. Waiting for next scan...")
    
    # Main loop
    while True:
        try:
            schedule.run_pending()
            time.sleep(30)  # Check every 30 seconds
        except KeyboardInterrupt:
            logger.info("Scheduler stopped by user")
            send_telegram_message("🛑 IHSG Scanner stopped")
            break
        except Exception as e:
            logger.error(f"Scheduler error: {str(e)}")
            time.sleep(60)


if __name__ == "__main__":
    main()
