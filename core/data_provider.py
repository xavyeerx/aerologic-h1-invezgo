# ============================================
# INVEZGO DATA PROVIDER (HTTP client terpusat)
# ============================================
# Semua request ke Invezgo REST API lewat modul ini.
# Menerapkan: pacing (anti burst-429), retry+backoff, timeout, quota counter.
#
# Referensi kontrak API (dari skill invezgo-data/screener):
#   Base URL : https://api.invezgo.com/
#   Auth     : header Authorization: Bearer <INVEZGO_API_KEY>
#   Header   : accept=application/json, accept-language=id, Referer=https://invezgo.com/
#
# Paket Prime: 500 req/menit, 65.000 req/bulan. Throttle = burst limiter (req/detik),
# jadi WAJIB pacing ~1.5s antar request (lihat PRD §10.5, §11.9).

from __future__ import annotations

import os
import time
import logging
import threading
from datetime import datetime, time as dtime
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import httpx
import pandas as pd
import pytz
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from .bar_contract import (
    INVEZGO_DAILY_CONTRACT,
    INVEZGO_H1_CONTRACT,
    attach_bar_contract,
)

logger = logging.getLogger(__name__)

WIB = pytz.timezone("Asia/Jakarta")

# ── Konfigurasi (bisa override via env) ─────────────────────────────
BASE_URL = os.getenv("INVEZGO_BASE_URL", "https://api.invezgo.com/").rstrip("/") + "/"
_API_KEY = os.getenv("INVEZGO_API_KEY", "")

REQUEST_TIMEOUT = float(os.getenv("INVEZGO_TIMEOUT", "10"))   # detik per request
# Rate limiter global: laju maksimum request/detik (token bucket). Prime = 500/menit
# nominal, tapi ada burst limiter. 3 req/detik = 180/menit, aman & jauh lebih cepat
# dari pacing kaku. Konkurensi (thread paralel) dibatasi terpisah oleh caller.
MIN_INTERVAL = 1.0 / float(os.getenv("INVEZGO_RATE_PER_SEC", "3"))
MAX_RETRIES = int(os.getenv("INVEZGO_MAX_RETRIES", "3"))
BACKOFF_BASE = float(os.getenv("INVEZGO_BACKOFF_BASE", "2"))  # 2s, 4s, 8s (error jaringan)
# 429 throttle: retry hingga 4× dengan jeda makin panjang (5s, 10s, 15s, 20s).
# Diperbesar dari default 2×/3s karena jam peak buka bursa (09:00-09:20) server
# Invezgo sering throttle sementara — lebih baik tunggu daripada langsung skip.
THROTTLE_RETRY_MAX = int(os.getenv("INVEZGO_THROTTLE_RETRY_MAX", "4"))
THROTTLE_RETRY_WAIT = float(os.getenv("INVEZGO_THROTTLE_RETRY_WAIT", "5"))  # 5s, 10s, 15s, 20s

_HEADERS = {
    "accept": "application/json",
    "accept-language": "id",
    "Referer": "https://invezgo.com/",
}


class InvezgoError(RuntimeError):
    """Kegagalan request Invezgo setelah retry habis."""


# ── Pacing global + quota counter (thread-safe) ─────────────────────
_lock = threading.Lock()
_last_request_ts = 0.0

# Quota counter harian: {kategori: jumlah}. Reset saat ganti hari (WIB).
_quota_date: Optional[str] = None
_quota_counts: dict[str, int] = {}


def _reset_quota_if_new_day() -> None:
    global _quota_date, _quota_counts
    today = datetime.now(WIB).strftime("%Y-%m-%d")
    if _quota_date != today:
        if _quota_date is not None and _quota_counts:
            logger.info("[QUOTA] %s final: %s total=%d",
                        _quota_date, _quota_counts, sum(_quota_counts.values()))
        _quota_date = today
        _quota_counts = {}


def _bump_quota(category: str) -> None:
    _reset_quota_if_new_day()
    _quota_counts[category] = _quota_counts.get(category, 0) + 1
    # Counter bulanan persisten + circuit breaker (early-warning 90% / stop 95%).
    try:
        from .quota_guard import record as _quota_record
        _quota_record(category)
    except Exception:  # quota guard tidak boleh menggagalkan request
        pass


def quota_snapshot() -> dict[str, Any]:
    """Snapshot pemakaian kuota hari ini (untuk observability §10)."""
    _reset_quota_if_new_day()
    return {
        "date": _quota_date,
        "counts": dict(_quota_counts),
        "total": sum(_quota_counts.values()),
    }


def _pace() -> None:
    """
    Rate limiter global (token bucket sederhana): jamin jeda >= MIN_INTERVAL antar
    request lintas SEMUA thread. Aman untuk fetch paralel — thread akan antre di sini
    sehingga laju total tetap <= INVEZGO_RATE_PER_SEC req/detik (cegah burst 429).
    """
    global _last_request_ts
    with _lock:
        now = time.monotonic()
        wait = MIN_INTERVAL - (now - _last_request_ts)
        if wait > 0:
            time.sleep(wait)
        _last_request_ts = time.monotonic()


# ── Client HTTP (lazy singleton) ────────────────────────────────────
_client: Optional[httpx.Client] = None


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(base_url=BASE_URL, timeout=REQUEST_TIMEOUT, headers=_HEADERS)
    return _client


def _auth_header() -> dict[str, str]:
    # Baca key saat request (bukan import-time) supaya .env yang di-load setelah
    # import tetap terpakai; env var lebih diutamakan bila di-set langsung.
    key = os.getenv("INVEZGO_API_KEY", _API_KEY)
    if not key:
        raise InvezgoError(
            "INVEZGO_API_KEY tidak diset. Isi di .env atau environment. "
            "Ambil/rotasi di https://invezgo.com/setting/api"
        )
    return {"authorization": f"Bearer {key}"}


def _request(method: str, path: str, *, category: str,
             params: Optional[dict] = None, json_body: Optional[dict] = None) -> Any:
    """
    Request terpusat: pacing + retry/backoff (429 & error transient) + quota count.
    Mengembalikan payload JSON (dict/list). Raise InvezgoError bila gagal permanen.
    """
    client = _get_client()
    headers = _auth_header()
    last_err: Optional[Exception] = None

    for attempt in range(1, MAX_RETRIES + 1):
        _pace()
        try:
            resp = client.request(method, path, params=params, json=json_body, headers=headers)
        except httpx.HTTPError as e:
            last_err = e
            logger.warning("Invezgo %s %s network error (attempt %d): %s", method, path, attempt, e)
            if attempt < MAX_RETRIES:
                time.sleep(BACKOFF_BASE ** attempt)
                continue
            raise InvezgoError(f"Network error {path}: {e}") from e

        if resp.status_code == 429:
            # Throttle — JANGAN hitung ke kuota (request tidak dilayani). Retry
            # ringan sekali dengan backoff panjang; kalau tetap 429, menyerah cepat
            # supaya tidak makin membebani endpoint yang sedang di-throttle.
            wait = THROTTLE_RETRY_WAIT * attempt
            last_err = InvezgoError(f"429 throttled {path}")
            if attempt < THROTTLE_RETRY_MAX:
                logger.warning("Invezgo 429 %s attempt %d — tunggu %.0fs", path, attempt, wait)
                time.sleep(wait)
                continue
            logger.error("Invezgo 429 %s — menyerah (throttle). Skip request ini.", path)
            raise last_err

        _bump_quota(category)  # hanya hitung request yang benar-benar dilayani

        if resp.status_code >= 400:
            # Error non-transient (400/401/403/404 dst) — jangan retry
            body = resp.text[:300]
            raise InvezgoError(f"HTTP {resp.status_code} {path}: {body}")

        try:
            return resp.json()
        except ValueError as e:
            raise InvezgoError(f"Response bukan JSON {path}: {resp.text[:200]}") from e

    raise InvezgoError(f"Gagal {path}: {last_err}")


# ── API publik ──────────────────────────────────────────────────────
def run_screener(formula: str) -> list[dict]:
    """
    Jalankan formula screener Invezgo. Mengembalikan list saham yang match
    (tiap item minimal punya 'code'; field lain tergantung formula, mis.
    close/value/volume). Raise InvezgoError bila API error.
    """
    payload = _request(
        "POST", "screener/screen",
        category="screener",
        json_body={"formula": formula},
    )
    # Sukses = list. Error = dict {message/error/...}.
    if isinstance(payload, dict):
        msg = payload.get("message") or payload.get("error") or str(payload)
        raise InvezgoError(f"Screener error: {msg}")
    if not isinstance(payload, list):
        raise InvezgoError(f"Screener output tak terduga: {type(payload)}")
    return payload


@lru_cache(maxsize=256)
def fetch_stock_sector(code: str) -> str:
    """Return the IDX sector for a stock code, with a per-process cache."""
    normalized_code = str(code or "").replace(".JK", "").strip().upper()
    if not normalized_code:
        return "UNKNOWN"

    try:
        payload = _request(
            "GET",
            f"analysis/information/{normalized_code}",
            category="stock_information",
        )
    except InvezgoError as exc:
        logger.warning("Gagal mengambil sector %s: %s", normalized_code, exc)
        return "UNKNOWN"

    if not isinstance(payload, dict):
        logger.warning("Stock information %s bukan object", normalized_code)
        return "UNKNOWN"

    sector = str(payload.get("sector") or "").strip()
    return sector or "UNKNOWN"


def _extract_post_rows(payload: Any) -> list[dict]:
    if isinstance(payload, dict):
        payload = payload.get("data", [])
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def fetch_stock_news(code: str) -> list[dict]:
    """Return the latest stock-specific news posts."""
    normalized_code = str(code or "").replace(".JK", "").strip().upper()
    if not normalized_code:
        return []
    payload = _request(
        "GET",
        f"posts/space/category/{normalized_code}/NEWS",
        category="stock_news",
        params={"page": 1, "limit": 10},
    )
    return _extract_post_rows(payload)


def fetch_stock_disclosures(code: str) -> list[dict]:
    """Return the latest exchange disclosures for one stock."""
    normalized_code = str(code or "").replace(".JK", "").strip().upper()
    if not normalized_code:
        return []
    payload = _request(
        "GET",
        f"posts/space/category/{normalized_code}/REPORT",
        category="stock_disclosure",
        params={"page": 1, "limit": 10},
    )
    return _extract_post_rows(payload)


def _rows_to_ohlc_df(rows: list[dict]) -> Optional[pd.DataFrame]:
    """
    Konversi array {date, open, high, low, close, volume} Invezgo → DataFrame
    kolom lowercase open/high/low/close/volume, index = tanggal naive WIB.
    Bentuk identik dengan yang dikonsumsi core/indicators.py.
    """
    if not rows:
        return None
    df = pd.DataFrame(rows)
    required = {"date", "open", "high", "low", "close", "volume"}
    if not required.issubset(df.columns):
        logger.warning("Chart row kekurangan kolom: punya %s", list(df.columns))
        return None

    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # date ISO (UTC) → tanggal kalender WIB, naive (samakan dgn data_fetcher lama)
    idx = pd.to_datetime(df["date"], utc=True).dt.tz_convert("Asia/Jakarta")
    df.index = pd.to_datetime(idx.dt.strftime("%Y-%m-%d"))
    df = df.drop(columns=["date"])
    df = df[["open", "high", "low", "close", "volume"]]
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df.dropna(subset=["close"])
    return attach_bar_contract(df, INVEZGO_DAILY_CONTRACT) if not df.empty else None


def _rows_to_h1_ohlc_df(
    rows: list[dict], now: Optional[datetime] = None, *, closed_only: bool = False
) -> Optional[pd.DataFrame]:
    """Convert multi-time rows to H1 bars with WIB wall-clock labels.

    Invezgo returns IDX bucket labels such as ``08:00Z`` and ``09:00Z``. The
    hour is the exchange bucket label; applying a UTC-to-WIB shift would corrupt
    the session. We therefore localize that wall clock directly to WIB.
    """
    if not rows:
        return None
    df = pd.DataFrame(rows)
    required = {"date", "open", "high", "low", "close", "volume"}
    if not required.issubset(df.columns):
        logger.warning("H1 chart row kekurangan kolom: punya %s", list(df.columns))
        return None
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    labels = pd.to_datetime(df["date"], errors="coerce").dt.tz_localize(None)
    df.index = labels.dt.tz_localize(WIB)
    df = df.drop(columns=["date"])[["open", "high", "low", "close", "volume"]]
    df = df[~df.index.duplicated(keep="last")].sort_index().dropna(subset=["close"])
    # TradingView IDX regular-session H1 excludes Invezgo's 08:xx pre-open and
    # 16:xx closing-auction buckets. Including them changes ATR and Supertrend.
    df = df[~df.index.hour.isin({8, 16})]

    from .market_session import is_h1_bar_closed
    reference = now or datetime.now(WIB)
    if reference.tzinfo is None:
        reference = WIB.localize(reference)
    closed_flags = [is_h1_bar_closed(timestamp, reference) for timestamp in df.index]
    if closed_only:
        df = df[closed_flags]
        closed_flags = [True] * len(df)
    if df.empty:
        return None
    df.attrs["latest_bar_closed"] = bool(closed_flags[-1])
    return attach_bar_contract(df, INVEZGO_H1_CONTRACT) if not df.empty else None




def fetch_chart(code: str, from_date: str, to_date: str) -> Optional[pd.DataFrame]:
    """
    OHLC harian 1 saham. `code` = kode Invezgo polos (mis. 'BBCA', tanpa .JK).
    from_date/to_date format 'YYYY-MM-DD'. Mengembalikan DataFrame atau None.

    Circuit breaker: bila kuota bulanan >= ambang, fetch chart dihentikan (return None)
    supaya kuota tidak jebol. Screener tetap boleh (jauh lebih murah).
    """
    from .quota_guard import chart_allowed
    if not chart_allowed():
        logger.error("[Quota] Circuit breaker aktif — skip chart %s", code)
        return None

    payload = _request(
        "GET", f"analysis/chart/stock/{code}",
        category="chart",
        params={"from": from_date, "to": to_date},
    )
    if isinstance(payload, dict):
        # bisa {data:[...]} atau error
        if "data" in payload and isinstance(payload["data"], list):
            payload = payload["data"]
        else:
            msg = payload.get("message") or payload.get("error") or str(payload)
            logger.warning("Chart %s error: %s", code, msg)
            return None
    if not isinstance(payload, list):
        return None
    return _rows_to_ohlc_df(payload)


def fetch_h1_chart(
    code: str, from_date: str, to_date: str, *, now: Optional[datetime] = None,
    closed_only: bool = False,
) -> Optional[pd.DataFrame]:
    """Fetch Invezgo H1 bars, including the latest forming bar by default."""
    from .quota_guard import chart_allowed
    if not chart_allowed():
        logger.error("[Quota] Circuit breaker aktif — skip H1 chart %s", code)
        return None
    payload = _request(
        "GET", f"analysis/chart/multi-time/{code}", category="chart",
        params={"from": from_date, "to": to_date, "timeframe": "60"},
    )
    if isinstance(payload, dict):
        payload = payload.get("data")
    if not isinstance(payload, list):
        logger.warning("H1 chart %s menghasilkan payload tak terduga", code)
        return None
    return _rows_to_h1_ohlc_df(payload, now=now, closed_only=closed_only)




def fetch_index(code: str, from_date: str, to_date: str) -> Optional[pd.DataFrame]:
    """
    OHLC harian indeks (mis. code='COMPOSITE' untuk IHSG). Untuk market_regime.
    """
    payload = _request(
        "GET", f"analysis/chart/index/{code}",
        category="regime",
        params={"from": from_date, "to": to_date},
    )
    if isinstance(payload, dict):
        if "data" in payload and isinstance(payload["data"], list):
            payload = payload["data"]
        else:
            msg = payload.get("message") or payload.get("error") or str(payload)
            logger.warning("Index-chart %s error: %s", code, msg)
            return None
    if not isinstance(payload, list):
        return None
    return _rows_to_ohlc_df(payload)
