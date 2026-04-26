# ============================================
# SCHEDULER - SMART SLEEP (COST OPTIMIZED)
# ============================================
# Strategi: tidur PANJANG di luar jam trading, bangun TEPAT saat dibutuhkan.
#
# Jadwal utama (hari kerja / Senin–Jumat):
#   08:45 → Opening recap
#   08:46 – 15:59 → Scan setiap 1 menit
#   16:00 → Closing recap
#   16:30 → Outcome check / evaluasi harian
#   Selain itu → tidur hingga waktu event berikutnya
#
# Akhir pekan (Sabtu & Minggu):
#   → Tidur sepanjang hari, bangun Senin 08:40
#
# Di luar jam trading (17:01 – 08:44):
#   → Tidur hingga 08:40 hari kerja berikutnya

import time
import logging
import logging.handlers
import sys
import os
from datetime import datetime, timedelta
import pytz

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

WIB = pytz.timezone('Asia/Jakarta')

from main import (
    run_scan,
    run_full_recap, run_daily_evaluation,
)
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


# ─────────────────────────────────────────────
# Helper: jadwal hari ini (jam WIB sebagai int tuple)
# ─────────────────────────────────────────────

OPEN_HOUR,  OPEN_MIN   = 8,  45   # Opening recap
CLOSE_HOUR, CLOSE_MIN  = 16,  0   # Closing recap
EVAL_HOUR,  EVAL_MIN   = 16, 30   # Outcome check
SCAN_INTERVAL_SEC      = 60       # Scan tiap 1 menit saat market buka
PRE_WAKE_MIN           = 5        # Bangun 5 menit sebelum market buka


def _today_at(hour: int, minute: int, tz=WIB) -> datetime:
    """Buat datetime untuk hari ini pada jam:menit WIB."""
    now = datetime.now(tz)
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _next_weekday_at(hour: int, minute: int, tz=WIB) -> datetime:
    """Cari hari kerja berikutnya (Senin–Jumat) pada jam:menit WIB."""
    now = datetime.now(tz)
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    # Maju ke hari berikutnya dulu kalau sudah lewat hari ini
    candidate += timedelta(days=1)
    while candidate.weekday() >= 5:  # 5=Sabtu, 6=Minggu
        candidate += timedelta(days=1)
    return candidate


def seconds_until(target: datetime) -> float:
    """Hitung detik yang tersisa hingga target. Min 0."""
    delta = (target - datetime.now(WIB)).total_seconds()
    return max(0.0, delta)


def smart_sleep_until(target: datetime, label: str):
    """Tidur hingga target, log setiap 30 menit agar tidak silent total."""
    secs = seconds_until(target)
    if secs <= 0:
        return
    hours  = int(secs // 3600)
    mins   = int((secs % 3600) // 60)
    logger.info(f"💤 Tidur selama {hours}j {mins}m hingga {label} "
                f"({target.strftime('%d-%b %H:%M')} WIB)")

    CHUNK = 30 * 60  # Log tiap 30 menit
    while True:
        remaining = seconds_until(target)
        if remaining <= 1:
            break
        sleep_now = min(remaining, CHUNK)
        time.sleep(sleep_now)
        remaining_after = seconds_until(target)
        if remaining_after > 60:
            h = int(remaining_after // 3600)
            m = int((remaining_after % 3600) // 60)
            logger.info(f"⏳ Sisa waktu tidur: {h}j {m}m hingga {label}")


# ─────────────────────────────────────────────
# Logika utama
# ─────────────────────────────────────────────

def next_event_sleep(now: datetime, state: dict) -> tuple[datetime, str]:
    """
    Tentukan event berikutnya dan kembalikan (target_datetime, label).
    state berisi flag: recap_open_done, recap_close_done, eval_done.
    """
    weekday = now.weekday()  # 0=Senin … 4=Jumat, 5=Sabtu, 6=Minggu

    # ── Akhir pekan → tidur hingga Senin 08:40 ──────────────────────
    if weekday >= 5:
        target = _next_weekday_at(OPEN_HOUR, OPEN_MIN - PRE_WAKE_MIN)
        return target, "Morning Pre-wake (Senin)"

    # ── Sebelum jam market ────────────────────────────────────────────
    pre_wake = _today_at(OPEN_HOUR, OPEN_MIN - PRE_WAKE_MIN)  # 08:40
    market_open = _today_at(OPEN_HOUR, OPEN_MIN)              # 08:45

    if now < pre_wake:
        return pre_wake, "Pre-wake (08:40)"

    # ── Market open recap (08:45) ─────────────────────────────────────
    if now < market_open and not state['recap_open_done']:
        return market_open, "Opening Recap (08:45)"

    # ── Sesi trading 08:46 – 15:59 ───────────────────────────────────
    market_close = _today_at(CLOSE_HOUR, CLOSE_MIN)
    if market_open <= now < market_close:
        # Scan berikutnya = sekarang + 1 menit (bulat ke menit)
        next_scan = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        return next_scan, "Scan (1-menit)"

    # ── Market close recap (16:00) ────────────────────────────────────
    eval_time = _today_at(EVAL_HOUR, EVAL_MIN)
    if market_close <= now < eval_time and not state['recap_close_done']:
        return market_close, "Closing Recap (16:00)"

    # ── Outcome check (16:30) ─────────────────────────────────────────
    if now >= market_close and not state['eval_done']:
        target = max(now, eval_time)
        return target, "Outcome Check (16:30)"

    # ── Semua selesai hari ini → tidur hingga besok 08:40 ────────────
    target = _next_weekday_at(OPEN_HOUR, OPEN_MIN - PRE_WAKE_MIN)
    return target, "Morning Pre-wake (besok)"


def main():
    """Main scheduler loop — pendekatan smart sleep."""
    global _LEARNING_OK

    # Ensure directories exist
    os.makedirs('logs', exist_ok=True)
    os.makedirs('database', exist_ok=True)

    logger.info("=" * 50)
    logger.info("IHSG SUPERTREND SCANNER v5.0 - SCHEDULER (Smart Sleep)")
    logger.info("=" * 50)
    logger.info("Opening recap   : 08:45 WIB")
    logger.info("Scan interval   : 1 menit (08:46–15:59)")
    logger.info("Closing recap   : 16:00 WIB")
    logger.info("Outcome check   : 16:30 WIB")
    logger.info("Akhir pekan     : Server idle (tidur hingga Senin 08:40)")
    logger.info("Luar jam trading: Tidur panjang (tidak polling)")
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

    # Per-day state flags
    state = {
        'recap_open_done':  False,
        'recap_close_done': False,
        'eval_done':        False,
        'last_date':        None,
    }

    logger.info("Scheduler started. Menghitung event berikutnya...")

    while True:
        try:
            now = datetime.now(WIB)

            # ── Reset flag tiap hari baru ─────────────────────────────
            today_str = now.strftime('%Y-%m-%d')
            if state['last_date'] != today_str:
                state['recap_open_done']  = False
                state['recap_close_done'] = False
                state['eval_done']        = False
                state['last_date']       = today_str
                logger.info(f"📅 Hari baru: {today_str} — flag direset")

            weekday = now.weekday()

            # ── Akhir pekan: idle ─────────────────────────────────────
            if weekday >= 5:
                target = _next_weekday_at(OPEN_HOUR, OPEN_MIN - PRE_WAKE_MIN)
                smart_sleep_until(target, "Senin pagi (08:40)")
                continue

            # ── Tentukan event berikutnya & tidur ─────────────────────
            target, label = next_event_sleep(now, state)
            secs = seconds_until(target)

            # Kalau masih perlu tidur lebih dari 5 detik → tidur dulu
            if secs > 5:
                smart_sleep_until(target, label)
                continue

            # ─── Eksekusi event ───────────────────────────────────────
            now = datetime.now(WIB)

            # Opening recap (08:45)
            market_open  = _today_at(OPEN_HOUR, OPEN_MIN)
            market_close = _today_at(CLOSE_HOUR, CLOSE_MIN)
            eval_time    = _today_at(EVAL_HOUR,  EVAL_MIN)

            if (now >= market_open and now < market_open + timedelta(minutes=2)
                    and not state['recap_open_done']):
                logger.info("🔔 Market open! Menjalankan opening recap...")
                try:
                    run_full_recap(state_manager, recap_type="OPENING")
                    state['recap_open_done'] = True
                except Exception as e:
                    logger.error(f"Opening recap error: {e}")
                    send_telegram_message(f"⚠️ Opening Recap Error: {e}")
                continue

            # Scan rutin 08:46 – 15:59
            if market_open + timedelta(minutes=1) <= now < market_close:
                try:
                    run_scan(state_manager, force=False)
                except Exception as e:
                    logger.error(f"Scan error: {e}")
                    send_telegram_message(f"⚠️ Scanner Error: {e}")
                # Tidur 1 menit setelah scan
                time.sleep(SCAN_INTERVAL_SEC)
                continue

            # Closing recap (16:00)
            if (now >= market_close and now < market_close + timedelta(minutes=5)
                    and not state['recap_close_done']):
                logger.info("🔔 Market close! Menjalankan closing recap...")
                try:
                    run_full_recap(state_manager, recap_type="CLOSING")
                    state['recap_close_done'] = True
                except Exception as e:
                    logger.error(f"Closing recap error: {e}")
                    send_telegram_message(f"⚠️ Closing Recap Error: {e}")
                continue

            # Outcome check (16:30)
            if now >= eval_time and not state['eval_done']:
                logger.info("📊 Menjalankan evaluasi sinyal harian (16:30)...")
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
                state['eval_done'] = True
                continue

            # Fallback: tidak ada event yang match → tidur 5 menit
            logger.info("⏸ Tidak ada event aktif. Tidur 5 menit...")
            time.sleep(5 * 60)

        except KeyboardInterrupt:
            logger.info("Scheduler dihentikan oleh user")
            send_telegram_message("🛑 IHSG Scanner stopped")
            break
        except Exception as e:
            logger.error(f"Scheduler error tak terduga: {e}")
            time.sleep(60)


if __name__ == "__main__":
    main()
