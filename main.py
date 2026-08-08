import gc
import logging
import logging.handlers
import os
import sys
import time
from datetime import datetime

import pytz

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.settings import *
from core.data_fetcher import fetch_multiple_stocks
from core.data_provider import InvezgoError
from core.market_session import is_scan_session
from core.scanner import filter_signals, has_any_signal, scan_all_stocks
from core.screener import get_candidates
from database.state_manager import StateManager
from learning.signal_events import SignalEventStore, new_signal_id, signal_snapshot
from notifications.telegram_bot import send_all_alerts, send_startup_message

try:
    from learning.market_regime import get_market_regime
    _REGIME_OK = True
except ImportError:
    _REGIME_OK = False

    def get_market_regime(**kw):
        return {"regime": "UNKNOWN", "adx": 0.0, "momentum_5d": 0.0}


try:
    from learning.db import init_db
    from learning.signal_tracker import track_all_signals
    _LEARNING_IMPORTS_OK = True
except ImportError:
    _LEARNING_IMPORTS_OK = False

    def init_db():
        return False

    def track_all_signals(*a, **kw):
        return 0


os.makedirs("logs", exist_ok=True)
os.makedirs("database", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            "logs/scanner.log",
            encoding="utf-8",
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
        ),
    ],
)
logger = logging.getLogger(__name__)
signal_event_store = SignalEventStore()
WIB = pytz.timezone("Asia/Jakarta")


def is_trading_hours() -> bool:
    return is_scan_session(datetime.now(WIB), include_preopen=True)


def _empty_summary() -> dict:
    return {
        "stocks_scanned": 0,
        "strong_buys": 0,
        "early_entries": 0,
        "reversal_watches": 0,
        "timestamp": datetime.now(WIB).isoformat(),
    }


def run_scan(state_manager: StateManager, force: bool = False) -> dict:
    if not force and not is_trading_hours():
        logger.info("Outside trading hours. Skipping scan.")
        return {"skipped": True, "reason": "Outside trading hours"}

    logger.info("=" * 50)
    logger.info("Starting aerologic Daily scan")
    logger.info("=" * 50)
    scan_t0 = time.perf_counter()
    state_manager.reset_daily_if_new_day()

    try:
        candidates, win, screener_prices = get_candidates()
    except InvezgoError as exc:
        logger.error("Screener gagal, skip scan: %s", exc)
        return {"error": f"Screener error: {exc}"}

    if not candidates:
        logger.info("Tidak ada kandidat lolos screener scan ini.")
        return _empty_summary()

    already_alerted = set()
    for category in ("strong_buy", "early_entry", "reversal_watch"):
        already_alerted.update(state_manager.daily_alerts.get(category, []))
    if already_alerted:
        before = len(candidates)
        candidates = [ticker for ticker in candidates if ticker not in already_alerted]
        skipped = before - len(candidates)
        if skipped:
            logger.info("Skip %d kandidat yang sudah di-alert hari ini", skipped)

    if not candidates:
        logger.info("Semua kandidat sudah pernah di-alert hari ini. Skip scan.")
        return _empty_summary()

    logger.info("Fetching OHLC Invezgo untuk %d kandidat [%s]...", len(candidates), win.label)
    fetch_t0 = time.perf_counter()
    stock_data = fetch_multiple_stocks(candidates, period=DATA_PERIOD, interval=DATA_INTERVAL)
    logger.info("Fetched data for %d stocks in %.1fs", len(stock_data), time.perf_counter() - fetch_t0)

    if not stock_data:
        logger.error("No data fetched. Aborting scan.")
        return {"error": "No data fetched"}

    previous_states = state_manager.get_all_states()
    regime_info = {"regime": "UNKNOWN", "adx": 0.0, "momentum_5d": 0.0}
    if _REGIME_OK:
        try:
            regime_info = get_market_regime()
        except Exception as exc:
            logger.warning("[Regime] Gagal ambil market regime: %s", exc)
    market_regime = regime_info.get("regime", "UNKNOWN")
    logger.info(
        "Market regime: %s | ADX=%s | Mom5d=%+.1f%%",
        market_regime,
        regime_info.get("adx", 0),
        float(regime_info.get("momentum_5d", 0) or 0),
    )

    logger.info("Analyzing stocks...")
    results = scan_all_stocks(
        stock_data,
        previous_states,
        state_manager=state_manager,
        market_regime=market_regime,
        market_momentum_5d=float(regime_info.get("momentum_5d", 0) or 0),
        screener_prices=screener_prices,
    )

    all_signals = filter_signals(results)
    new_signals = {"strong_buy": [], "early_entry": [], "reversal_watch": []}
    for signal_type, signal_list in all_signals.items():
        claimed = []
        for result in signal_list:
            if state_manager.try_claim_daily_alert(signal_type, result.ticker):
                claimed.append(result)
        new_signals[signal_type] = claimed
        if signal_list:
            logger.info("%s: %d total, %d claimed", signal_type, len(signal_list), len(claimed))

    if has_any_signal(new_signals):
        for signal_type, signal_list in new_signals.items():
            for result in signal_list:
                result.signal_id = result.signal_id or new_signal_id()
                signal_event_store.append(
                    "SIGNAL_CREATED",
                    signal_id=result.signal_id,
                    ticker=result.ticker,
                    payload=signal_snapshot(result, signal_type, regime_info),
                )
                signal_event_store.append(
                    "ALERT_DISPATCH_ATTEMPTED",
                    signal_id=result.signal_id,
                    ticker=result.ticker,
                    payload={"signal_type": signal_type},
                )

        logger.info("Sending Telegram alerts for NEW signals...")
        messages_sent = send_all_alerts(new_signals)
        logger.info("Sent %d alert messages", messages_sent)

        for signal_type, signal_list in new_signals.items():
            for result in signal_list:
                signal_event_store.append(
                    "ALERT_BATCH_RESULT",
                    signal_id=result.signal_id,
                    ticker=result.ticker,
                    payload={"signal_type": signal_type, "batch_messages_sent": messages_sent},
                )
                state_manager.track_signal(result, signal_type)

        if _LEARNING_IMPORTS_OK:
            try:
                tracked = track_all_signals(new_signals, regime_info)
                if tracked > 0:
                    logger.info("[Learning] %d sinyal direcord ke DB", tracked)
            except Exception as exc:
                logger.warning("[Learning] Tracking error: %s", exc)
    else:
        logger.info("No NEW signals detected this scan")

    del stock_data
    gc.collect()

    logger.info("Updating stock states...")
    for result in results.values():
        state_manager.update_from_scan_result(result)
    state_manager.save()

    summary = {
        "stocks_scanned": len(results),
        "strong_buys": len(new_signals["strong_buy"]),
        "early_entries": len(new_signals["early_entry"]),
        "reversal_watches": len(new_signals["reversal_watch"]),
        "timestamp": datetime.now(WIB).isoformat(),
    }
    logger.info("Scan complete in %.1fs", time.perf_counter() - scan_t0)
    logger.info("Summary: %s", summary)
    logger.info("=" * 50)
    return summary


def main():
    if _LEARNING_IMPORTS_OK:
        try:
            ok = init_db()
            logger.info("[Learning] PostgreSQL %s", "siap" if ok else "tidak tersedia")
        except Exception as exc:
            logger.warning("[Learning] DB init error: %s", exc)

    state_manager = StateManager()
    if len(state_manager.get_all_states()) == 0:
        logger.info("First run detected. Initial scan will not generate alerts.")
    run_scan(state_manager, force=True)


def run_with_notification():
    logger.info("aerologic Daily scanner starting with notification...")
    send_startup_message()
    run_scan(StateManager(), force=True)


if __name__ == "__main__":
    main()
