# ============================================
# SCHEDULER - RUN SCANS
# ============================================
# Recap: 08:45 (market open) and 16:00 (market close)
# Alerts: every 1 minute during trading hours (only NEW signals)

import schedule
import time
import logging
import logging.handlers
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import run_scan, is_trading_hours, is_market_open_time, is_market_close_time, run_full_recap, run_daily_evaluation
from database.state_manager import StateManager
from notifications.telegram_bot import send_startup_message, send_telegram_message

# Learning system (graceful degradation)
try:
    from main import init_db, _LEARNING_IMPORTS_OK
    from learning.outcome_checker import run_outcome_check
    _LEARNING_OK = True
except ImportError:
    _LEARNING_OK = False
    def run_outcome_check(): return 0

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            'logs/scheduler.log',
            encoding='utf-8',
            maxBytes=5 * 1024 * 1024,  # 5 MB max
            backupCount=3
        )
    ]
)
logger = logging.getLogger(__name__)

# Global state
state_manager      = None
recap_sent_open    = False
recap_sent_close   = False
outcome_check_done = False   # Outcome check 16:30, reset tiap hari


def scheduled_scan():
    """Run scheduled scan"""
    global state_manager, recap_sent_open, recap_sent_close, outcome_check_done

    from datetime import datetime
    import pytz
    WIB = pytz.timezone('Asia/Jakarta')
    now = datetime.now(WIB)

    # Reset flags di tengah malam
    if now.hour == 0 and now.minute <= 5:
        recap_sent_open    = False
        recap_sent_close   = False
        outcome_check_done = False
    
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

    # ── Outcome Check 16:30 WIB ────────────────────────────────
    # Evaluasi TP/SL semua sinyal aktif + learning outcome check
    if (now.hour == 16 and now.minute >= 30 and
            now.weekday() < 5 and not outcome_check_done):
        logger.info("[Evaluation] Menjalankan evaluasi sinyal harian (16:30 WIB)...")
        try:
            run_daily_evaluation(state_manager)
        except Exception as e:
            logger.error(f"[Evaluation] Error: {e}")
        try:
            if _LEARNING_OK:
                n = run_outcome_check()
                logger.info(f"[OutcomeChecker] Selesai: {n} sinyal dievaluasi")
        except Exception as e:
            logger.error(f"[OutcomeChecker] Error: {e}")
        outcome_check_done = True
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
    logger.info("Scan interval   : 1 menit")
    logger.info("Opening recap   : 08:45 WIB")
    logger.info("Closing recap   : 16:00 WIB")
    logger.info("Outcome check   : 16:30 WIB (setelah market close)")
    logger.info("Trading hours   : 08:45 - 16:00 WIB")
    logger.info(f"Learning system : {'Aktif' if _LEARNING_OK else 'Tidak aktif (no DB)'}")
    logger.info("=" * 50)

    # Init learning DB
    if _LEARNING_OK:
        try:
            ok = init_db()
            logger.info(f"[Learning] DB: {'Siap ✅' if ok else 'Tidak tersedia ⚠️'}")
        except Exception as e:
            logger.warning(f"[Learning] DB init warning: {e}")
    
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
