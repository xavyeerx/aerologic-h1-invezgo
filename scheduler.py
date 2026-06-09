# ============================================
# SCHEDULER - SMART SLEEP (COST OPTIMIZED)
# ============================================
# Strategi: tidur PANJANG di luar jam trading, bangun TEPAT saat dibutuhkan.
#
# Jadwal utama (hari kerja / Senin–Jumat):
#   Pola chart TF-D: terjadwal CHART_PATTERN_ALERT_* (default 16:45); realtime hanya jika CHART_PATTERN_REALTIME=1
#   08:40 → Pre-wake sebelum recap
#   08:45 → Opening recap (tidak lagi mengirit pola chart di sini)
#   08:46 – 15:59 → Scan setiap 1 menit
#   16:00 → Closing recap
#   16:30 → Outcome check / evaluasi harian
#   Selain itu → tidur hingga waktu event berikutnya
#
# Akhir pekan:
#   → Tidur hingga hari kerja berikutnya pre-wake 08:40
#
# Di luar sesi rutin scanner:
#   → Tidur hingga event berikutnya (slot pol chart / dll.)

import time
import logging
import logging.handlers
import subprocess
import sys
import os
from datetime import datetime, timedelta
import pytz

# Add project root to path (absolut — systemd tidak selalu set WorkingDirectory)
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _PROJECT_ROOT)
_LOG_DIR = os.path.join(_PROJECT_ROOT, "logs")
_SCHEDULER_LOG = os.path.join(_LOG_DIR, "scheduler.log")
os.makedirs(_LOG_DIR, exist_ok=True)

WIB = pytz.timezone('Asia/Jakarta')

from config.settings import (
    CHART_PATTERN_ALERT_HOUR,
    CHART_PATTERN_ALERT_MINUTE,
    CHART_PATTERN_EXECUTION_WINDOW_MINUTES,
    CHART_PATTERN_FORCE_SCHEDULED_ONLY,
    CHART_PATTERN_REALTIME,
    SCANNER_BUILD_ID,
    chart_pattern_slot_bounds,
    is_chart_pattern_alert_window,
)

from main import (
    run_scan,
    run_full_recap,
    run_daily_evaluation,
    run_morning_chart_pattern_scan,
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
            _SCHEDULER_LOG,
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

OPEN_HOUR,  OPEN_MIN   = 8,  45   # Opening recap / market open
CLOSE_HOUR, CLOSE_MIN  = 16,  0   # Closing recap
EVAL_HOUR,  EVAL_MIN   = 16, 30   # Outcome check
SCAN_INTERVAL_SEC      = 60       # Scan tiap 1 menit saat market buka
PRE_WAKE_MIN           = 5        # Bangun beberapa menit sebelum event pagi


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

def next_event_sleep(now: datetime, state: dict, sm: StateManager) -> tuple[datetime, str]:
    """
    Tentukan event berikutnya dan kembalikan (target_datetime, label).
    state berisi flag: recap_open_done, recap_close_done, eval_done.
    """
    weekday = now.weekday()  # 0=Senin … 4=Jumat, 5=Sabtu, 6=Minggu

    chart_at, chart_end = chart_pattern_slot_bounds(now, tz=WIB)
    pre_open = _today_at(OPEN_HOUR, OPEN_MIN - PRE_WAKE_MIN, tz=WIB)  # 08:40
    market_open = _today_at(OPEN_HOUR, OPEN_MIN, tz=WIB)
    market_close = _today_at(CLOSE_HOUR, CLOSE_MIN, tz=WIB)
    eval_time = _today_at(EVAL_HOUR, EVAL_MIN, tz=WIB)
    chart_evening = chart_at >= market_close
    chart_pre_market = chart_at < market_open

    # ── Akhir pekan → tidur hingga hari kerja berikutnya (pre-open) ─
    if weekday >= 5:
        next_pre_open = _next_weekday_at(OPEN_HOUR, OPEN_MIN - PRE_WAKE_MIN, tz=WIB)
        return next_pre_open, "Pre-wake hari kerja (08:40)"

    need_chart = (not CHART_PATTERN_REALTIME) and not sm.morning_chart_patterns_already_scanned_today()

    # ── Slot pola chart sebelum buka (bukan slot intraday/sore) ──
    if need_chart and chart_pre_market:
        if now < chart_at:
            return chart_at, "Chart patterns TF-D (pre-open)"
        if now < chart_end:
            urgent = now.replace(second=0, microsecond=0) + timedelta(seconds=3)
            return urgent, "Chart patterns (jendela pre-open)"
        urgent = now.replace(second=0, microsecond=0) + timedelta(seconds=3)
        return urgent, "Chart patterns (lewat jendela — tandai selesai)"

    # ── Sebelum recap 08:45 ──
    if now < pre_open:
        return pre_open, "Pre-wake (08:40)"

    # ── Opening recap 08:45 ───────────────────────────────────────────
    if now < market_open and not state['recap_open_done']:
        return market_open, "Opening Recap (08:45)"

    # ── Sesi trading 08:46 – 15:59 (pola chart sore hanya jika slot < tutup; default 16:45 = malam) ──
    if market_open <= now < market_close:
        if need_chart and is_chart_pattern_alert_window(now):
            urgent = now.replace(second=0, microsecond=0) + timedelta(seconds=3)
            return urgent, (
                f"Chart patterns TF-D ({CHART_PATTERN_ALERT_HOUR:02d}:"
                f"{CHART_PATTERN_ALERT_MINUTE:02d})"
            )
        if need_chart and now < chart_at:
            next_scan = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
            return min(next_scan, chart_at), "Scan / chart slot"
        next_scan = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        return next_scan, "Scan (1-menit)"

    # ── Market close 16:00 ────────────────────────────────────────────
    if market_close <= now < eval_time and not state['recap_close_done']:
        return market_close, "Closing Recap (16:00)"

    # ── Outcome 16:30 ─────────────────────────────────────────────────
    if now >= market_close and not state['eval_done']:
        target = max(now, eval_time)
        return target, "Outcome Check (16:30)"

    # ── Chart TF-D malam (setelah tutup; candle = hari perdagangan yang sama) ─
    if need_chart and chart_evening and now >= market_close:
        if now < chart_at:
            return chart_at, f"Chart patterns TF-D ({CHART_PATTERN_ALERT_HOUR:02d}:{CHART_PATTERN_ALERT_MINUTE:02d})"
        if now < chart_end:
            urgent = now.replace(second=0, microsecond=0) + timedelta(seconds=3)
            return urgent, "Chart patterns (jendela malam)"
        urgent = now.replace(second=0, microsecond=0) + timedelta(seconds=3)
        return urgent, "Chart patterns (lewat jendela — tandai selesai)"

    # ── Selesai → hari kerja berikutnya pre-open (jangan skip sesi pagi) ─
    next_pre_open = _next_weekday_at(OPEN_HOUR, OPEN_MIN - PRE_WAKE_MIN, tz=WIB)
    return next_pre_open, "Pre-wake besok (08:40)"


def _other_scheduler_pids() -> list[int]:
    """Proses scheduler.py lain di repo ini (bukan PID saat ini)."""
    try:
        marker = os.path.join(_PROJECT_ROOT, "scheduler.py")
        r = subprocess.run(
            ["pgrep", "-f", marker],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode != 0:
            return []
        me = os.getpid()
        out = []
        for line in r.stdout.split():
            line = line.strip()
            if line.isdigit():
                pid = int(line)
                if pid != me:
                    out.append(pid)
        return out
    except Exception:
        return []


def ensure_single_scheduler_process() -> None:
    peers = _other_scheduler_pids()
    if peers:
        logger.error(
            "Scheduler duplikat (PID lain: %s). Hanya jalankan via systemd. "
            "Fix: sudo systemctl stop ihsg-scanner && "
            "pkill -f 'ihsg-scanner/scheduler.py' && "
            "sudo systemctl start ihsg-scanner",
            peers,
        )
        sys.exit(1)


def main():
    """Main scheduler loop — pendekatan smart sleep."""
    global _LEARNING_OK

    os.makedirs(os.path.join(_PROJECT_ROOT, "database"), exist_ok=True)
    ensure_single_scheduler_process()

    logger.info("=" * 50)
    logger.info("IHSG SUPERTREND SCANNER v5.0 - SCHEDULER (Smart Sleep)")
    logger.info(f"Build ID: {SCANNER_BUILD_ID}")
    logger.info("=" * 50)
    if CHART_PATTERN_REALTIME:
        chart_mode = "realtime (tiap scan sesi)"
    else:
        chart_mode = (
            f"terjadwal {CHART_PATTERN_ALERT_HOUR:02d}:"
            f"{CHART_PATTERN_ALERT_MINUTE:02d} WIB (1×/hari)"
        )
    if CHART_PATTERN_FORCE_SCHEDULED_ONLY:
        chart_mode += " [scheduled-only: env realtime diabaikan]"
    logger.info(f"Pola chart TF-D: {chart_mode}")
    logger.info("Opening recap        : 08:45 WIB")
    logger.info("Scan interval   : 1 menit (08:46–15:59)")
    logger.info("Closing recap   : 16:00 WIB")
    logger.info("Outcome check   : 16:30 WIB")
    logger.info("Akhir pekan     : Server idle (tidur hingga hari kerja 08:40)")
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
                target = _next_weekday_at(OPEN_HOUR, OPEN_MIN - PRE_WAKE_MIN, tz=WIB)
                smart_sleep_until(
                    target,
                    "Hari kerja pre-wake 08:40",
                )
                continue

            # ── Tentukan event berikutnya & tidur ─────────────────────
            target, label = next_event_sleep(now, state, state_manager)
            secs = seconds_until(target)

            # Kalau masih perlu tidur lebih dari 5 detik → tidur dulu
            if secs > 5:
                smart_sleep_until(target, label)
                # Jangan continue — biarkan flow lanjut ke eksekusi event

            # ─── Eksekusi event ───────────────────────────────────────
            now = datetime.now(WIB)
            weekday = now.weekday()

            market_open  = _today_at(OPEN_HOUR, OPEN_MIN)
            market_close = _today_at(CLOSE_HOUR, CLOSE_MIN)
            eval_time    = _today_at(EVAL_HOUR,  EVAL_MIN)

            chart_at, chart_end = chart_pattern_slot_bounds(now)

            # Pola chart terjadwal 1×/hari (tidak dari run_scan kecuali CHART_PATTERN_REALTIME)
            if (
                not CHART_PATTERN_REALTIME
                and weekday < 5
                and not state_manager.morning_chart_patterns_already_scanned_today()
            ):
                if is_chart_pattern_alert_window(now):
                    logger.info(
                        f"📐 Alert pola chart TF-D (slot "
                        f"{CHART_PATTERN_ALERT_HOUR:02d}:{CHART_PATTERN_ALERT_MINUTE:02d}, "
                        "terpisah dari sinyal utama)..."
                    )
                    try:
                        run_morning_chart_pattern_scan(state_manager)
                    except Exception as e2:
                        logger.error(f"Chart patterns error: {e2}")
                        send_telegram_message(
                            f"⚠️ Chart Patterns ({CHART_PATTERN_ALERT_HOUR:02d}:"
                            f"{CHART_PATTERN_ALERT_MINUTE:02d}): {e2}"
                        )
                        state_manager.mark_morning_chart_patterns_scan_complete()
                    continue
                if now >= chart_end and now >= chart_at:
                    logger.info(
                        f"📐 Chart patterns: lewat jendela "
                        f"{CHART_PATTERN_ALERT_HOUR:02d}:{CHART_PATTERN_ALERT_MINUTE:02d} "
                        "— tidak dijalankan hari ini."
                    )
                    state_manager.mark_morning_chart_patterns_scan_complete()
                    continue

            # Opening recap (08:45)
            if (now >= market_open and now < market_open + timedelta(minutes=2)
                    and not state['recap_open_done']):
                logger.info("🔔 Market open! Menjalankan opening recap...")
                try:
                    run_full_recap(state_manager, recap_type="OPENING")
                except Exception as e:
                    logger.error(f"Opening recap error: {e}")
                    send_telegram_message(f"⚠️ Opening Recap Error: {e}")
                state['recap_open_done'] = True
                continue

            # Scan rutin 08:46 – 15:59
            if market_open + timedelta(minutes=1) <= now < market_close:
                try:
                    run_scan(state_manager, force=False)
                except Exception as e:
                    logger.exception("Scan error")
                    send_telegram_message(
                        f"⚠️ Scanner Error: {type(e).__name__}: {e}"
                    )
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
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        logger.exception("Scheduler gagal start")
        raise
