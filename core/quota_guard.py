# ============================================
# QUOTA GUARD — counter bulanan persisten + circuit breaker
# ============================================
# Melacak total request Invezgo per BULAN (persisten via JSON) dan menegakkan:
#   • Early-warning: pemakaian >= WARN_PCT (default 90%) → kirim peringatan Telegram (1×/bulan)
#   • Circuit breaker: pemakaian >= BREAK_PCT (default 95%) → blokir fetch chart
#     (screener tetap boleh — jauh lebih murah), kirim alarm (1×/bulan)
#
# Kuota paket Prime: 65.000 request/bulan (PRD §2).
# Thread-safe (dipanggil dari fetch paralel).

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime

import pytz

logger = logging.getLogger(__name__)

WIB = pytz.timezone("Asia/Jakarta")

MONTHLY_QUOTA = int(os.getenv("INVEZGO_MONTHLY_QUOTA", "65000"))
WARN_PCT = float(os.getenv("INVEZGO_QUOTA_WARN_PCT", "90"))
BREAK_PCT = float(os.getenv("INVEZGO_QUOTA_BREAK_PCT", "95"))

_QUOTA_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "database", "quota_usage.json",
)

_lock = threading.Lock()

# Struktur state: {"month": "YYYY-MM", "total": int, "by_cat": {..}, "warned": bool, "broke": bool}
_state: dict | None = None


def _current_month() -> str:
    return datetime.now(WIB).strftime("%Y-%m")


def _blank_state() -> dict:
    return {"month": _current_month(), "total": 0, "by_cat": {}, "warned": False, "broke": False}


def _load() -> dict:
    """Muat state dari file; reset bila ganti bulan atau file rusak/hilang."""
    global _state
    if _state is not None and _state.get("month") == _current_month():
        return _state
    try:
        with open(_QUOTA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("month") != _current_month():
            data = _blank_state()
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        data = _blank_state()
    _state = data
    return _state


def _save() -> None:
    try:
        os.makedirs(os.path.dirname(_QUOTA_FILE), exist_ok=True)
        tmp = _QUOTA_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_state, f)
        os.replace(tmp, _QUOTA_FILE)
    except OSError as e:
        logger.warning("[Quota] Gagal simpan counter: %s", e)


def _pct() -> float:
    st = _load()
    return (st["total"] / MONTHLY_QUOTA) * 100.0 if MONTHLY_QUOTA else 0.0


def record(category: str, n: int = 1) -> None:
    """Catat n request kategori tsb ke counter bulanan (dipanggil setelah request sukses/terkirim)."""
    with _lock:
        st = _load()
        st["total"] += n
        st["by_cat"][category] = st["by_cat"].get(category, 0) + n
        _save()
        _maybe_alert(st)


def chart_allowed() -> bool:
    """False bila circuit breaker aktif (pemakaian >= BREAK_PCT). Fetch chart harus dihentikan."""
    return _pct() < BREAK_PCT


def snapshot() -> dict:
    st = _load()
    return {
        "month": st["month"],
        "total": st["total"],
        "quota": MONTHLY_QUOTA,
        "pct": round(_pct(), 1),
        "by_cat": dict(st["by_cat"]),
        "circuit_open": _pct() >= BREAK_PCT,
    }


def _maybe_alert(st: dict) -> None:
    """Kirim peringatan/alarm Telegram sekali per bulan saat ambang terlampaui."""
    pct = _pct()
    # Import lokal supaya tidak circular (telegram_bot → settings, tidak balik ke sini).
    if pct >= BREAK_PCT and not st.get("broke"):
        st["broke"] = True
        st["warned"] = True
        _save()
        _notify(
            f"🛑 <b>KUOTA INVEZGO {pct:.0f}%</b> ({st['total']:,}/{MONTHLY_QUOTA:,})\n"
            f"Circuit breaker AKTIF — fetch chart DIHENTIKAN sampai bulan depan. "
            f"Screener tetap jalan. Bulan: {st['month']}"
        )
        logger.error("[Quota] CIRCUIT BREAKER aktif — %.1f%% (%d/%d)", pct, st["total"], MONTHLY_QUOTA)
    elif pct >= WARN_PCT and not st.get("warned"):
        st["warned"] = True
        _save()
        _notify(
            f"⚠️ <b>KUOTA INVEZGO {pct:.0f}%</b> ({st['total']:,}/{MONTHLY_QUOTA:,})\n"
            f"Mendekati limit bulanan. Pada {BREAK_PCT:.0f}% fetch chart auto-stop. "
            f"Bulan: {st['month']}"
        )
        logger.warning("[Quota] EARLY-WARNING — %.1f%% (%d/%d)", pct, st["total"], MONTHLY_QUOTA)


def _notify(msg: str) -> None:
    try:
        from notifications.telegram_bot import send_telegram_message
        send_telegram_message(msg)
    except Exception as e:
        logger.warning("[Quota] Gagal kirim notif kuota: %s", e)
