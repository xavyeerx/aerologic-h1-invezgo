# ============================================
# SCHEDULER - aerologic H1 (closed candles only)
# ============================================
# Runs one minute after each Invezgo H1 exchange bucket closes; weekend is off.

import logging
import logging.handlers
import os
import subprocess
import sys
import time
from datetime import datetime, time as dtime, timedelta

import pytz

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _PROJECT_ROOT)
_LOG_DIR = os.path.join(_PROJECT_ROOT, "logs")
_SCHEDULER_LOG = os.path.join(_LOG_DIR, "scheduler.log")
os.makedirs(_LOG_DIR, exist_ok=True)

WIB = pytz.timezone("Asia/Jakarta")

from config.settings import SCANNER_BUILD_ID
from database.state_manager import StateManager
from main import run_scan
from notifications.telegram_bot import send_startup_message, send_telegram_message

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            _SCHEDULER_LOG, encoding="utf-8", maxBytes=5 * 1024 * 1024, backupCount=3
        ),
    ],
)
logger = logging.getLogger(__name__)

MORNING_SCAN_START = dtime(9, 1)
MORNING_SCAN_END = dtime(12, 0)
AFTERNOON_SCAN_START = dtime(13, 31)
FRIDAY_AFTERNOON_SCAN_START = dtime(14, 1)
AFTERNOON_SCAN_END = dtime(16, 1)
SCAN_INTERVAL_SECONDS = 60 * 60

# One minute after each Invezgo exchange bucket closes. The irregular IDX lunch
# break and closing auction mean these are intentionally not a simple cron */60.
H1_CLOSE_SLOTS_MON_THU = (
    dtime(9, 1), dtime(10, 1), dtime(11, 1), dtime(12, 1),
    dtime(14, 1), dtime(15, 1), dtime(15, 51), dtime(16, 16),
)
H1_CLOSE_SLOTS_FRIDAY = (
    dtime(9, 1), dtime(10, 1), dtime(11, 1), dtime(11, 31),
    dtime(15, 1), dtime(15, 51), dtime(16, 16),
)


def _today_at(t: dtime, tz=WIB) -> datetime:
    return datetime.now(tz).replace(hour=t.hour, minute=t.minute, second=t.second, microsecond=0)


def _next_weekday_scan(tz=WIB) -> datetime:
    candidate = _today_at(MORNING_SCAN_START, tz) + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def seconds_until(target: datetime) -> float:
    return max(0.0, (target - datetime.now(WIB)).total_seconds())


def smart_sleep_until(target: datetime, label: str) -> None:
    secs = seconds_until(target)
    if secs <= 0:
        return
    logger.info(
        "Tidur %dj %dm hingga %s (%s WIB)",
        int(secs // 3600),
        int((secs % 3600) // 60),
        label,
        target.strftime("%d-%b %H:%M"),
    )
    while True:
        remaining = seconds_until(target)
        if remaining <= 1:
            break
        time.sleep(min(remaining, 30 * 60))


def scan_slots_for_day(now: datetime) -> list[datetime]:
    labels = H1_CLOSE_SLOTS_FRIDAY if now.weekday() == 4 else H1_CLOSE_SLOTS_MON_THU
    return [
        now.replace(hour=value.hour, minute=value.minute, second=0, microsecond=0)
        for value in labels
    ]


def next_scan_slot(now: datetime) -> datetime | None:
    if now.weekday() >= 5:
        return None
    for slot in scan_slots_for_day(now):
        if now <= slot:
            return slot
    return None


def next_event(now: datetime) -> tuple[datetime, str]:
    scan_at = next_scan_slot(now)
    if scan_at is not None:
        return scan_at, f"Scan ({scan_at.strftime('%H:%M')})"
    return _next_weekday_scan(), "Scan hari kerja berikutnya"


def _other_scheduler_pids() -> list[int]:
    try:
        result = subprocess.run(
            ["pgrep", "-f", os.path.join(_PROJECT_ROOT, "scheduler.py")],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return []
        me = os.getpid()
        return [
            int(pid)
            for pid in result.stdout.split()
            if pid.strip().isdigit() and int(pid) != me
        ]
    except Exception:
        return []


def ensure_single_scheduler_process() -> None:
    peers = _other_scheduler_pids()
    if peers:
        logger.error("Scheduler duplikat (PID lain: %s). Hentikan yang lain dulu.", peers)
        sys.exit(1)


def main() -> None:
    os.makedirs(os.path.join(_PROJECT_ROOT, "database"), exist_ok=True)
    pause_file = os.path.join(_PROJECT_ROOT, "database", "PAUSE_SCHEDULER")
    if os.path.exists(pause_file):
        logger.warning("PAUSE_SCHEDULER aktif. Hapus %s untuk mulai.", pause_file)
        return

    ensure_single_scheduler_process()
    logger.info("=" * 50)
    logger.info("aerologic H1 scheduler")
    logger.info("Build: %s", SCANNER_BUILD_ID)
    logger.info("Scan satu menit setelah setiap candle Invezgo H1 ditutup")
    logger.info("=" * 50)

    state_manager = StateManager()
    send_startup_message()

    last_scan_slot: datetime | None = None

    while True:
        try:
            now = datetime.now(WIB)
            target, label = next_event(now)
            if seconds_until(target) > 2:
                smart_sleep_until(target, label)

            # Setelah bangun: `target` adalah slot yang harus dijalankan.
            # JANGAN panggil next_scan_slot lagi — fungsi itu selalu
            # mengembalikan slot masa depan, bukan slot yang baru saja tiba.
            now = datetime.now(WIB)
            elapsed = (now - target).total_seconds()
            slot_window = 5 * 60  # do not process a stale close much later

            if target != last_scan_slot and elapsed < slot_window:
                last_scan_slot = target
                logger.info(
                    "Menjalankan scan untuk slot %s (terlambat %.0fs)",
                    target.strftime("%H:%M"),
                    max(0.0, elapsed),
                )
                try:
                    run_scan(state_manager, force=True)
                except Exception as exc:
                    logger.exception("Scan error")
                    send_telegram_message(f"Warning Scanner Error: {type(exc).__name__}: {exc}")
            elif elapsed >= slot_window:
                logger.warning(
                    "Slot %s dilewati (terlambat %.0fs > window %.0fs), skip.",
                    target.strftime("%H:%M"),
                    elapsed,
                    slot_window,
                )

            time.sleep(30)

        except KeyboardInterrupt:
            logger.info("Scheduler dihentikan.")
            send_telegram_message("aerologic H1 scanner stopped")
            break
        except Exception as exc:
            logger.error("Scheduler error tak terduga: %s", exc)
            time.sleep(60)


if __name__ == "__main__":
    main()
