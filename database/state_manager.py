# ============================================
# STATE MANAGER - TRACK STOCK STATES
# ============================================

import json
import os
from datetime import date, datetime, timedelta
from typing import Dict, Optional, List
import logging
import threading

try:
    import fcntl
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False

logger = logging.getLogger(__name__)

ALERT_LOOKBACK_DAYS = 14
ALERT_MAX_CALLS = 3
ALERT_MAX_CONSECUTIVE_SESSIONS = 2
ALERT_CATEGORIES = ("bullish_break", "strong_buy", "early_entry", "reversal_watch")


def _canonical_ticker(ticker: str) -> str:
    ticker = str(ticker or "").strip().upper()
    return ticker[:-3] if ticker.endswith(".JK") else ticker


def _previous_weekday(day: date) -> date:
    previous = day - timedelta(days=1)
    while previous.weekday() >= 5:
        previous -= timedelta(days=1)
    return previous


def evaluate_alert_frequency(call_dates: List[str], on_date: date) -> tuple[bool, str]:
    """Evaluate ticker-level call limits using unique alert dates."""
    parsed_dates = set()
    for value in call_dates:
        try:
            parsed_dates.add(datetime.strptime(value, "%Y-%m-%d").date())
        except (TypeError, ValueError):
            logger.warning("Ignoring invalid alert history date: %r", value)

    window_start = on_date - timedelta(days=ALERT_LOOKBACK_DAYS - 1)
    calls_in_window = sum(window_start <= alert_date <= on_date for alert_date in parsed_dates)
    if calls_in_window >= ALERT_MAX_CALLS:
        return False, f"sudah {calls_in_window}x dalam {ALERT_LOOKBACK_DAYS} hari"

    previous_sessions = []
    session = on_date
    for _ in range(ALERT_MAX_CONSECUTIVE_SESSIONS):
        session = _previous_weekday(session)
        previous_sessions.append(session)
    if all(session in parsed_dates for session in previous_sessions):
        return False, f"sudah call {ALERT_MAX_CONSECUTIVE_SESSIONS} sesi bursa berturut-turut"

    return True, ""


class StateManager:
    """Manage persistent state for stocks"""
    
    def __init__(self, state_file: str = "database/stock_states.json"):
        self.state_file = state_file
        database_dir = os.path.dirname(state_file) or "database"
        self.daily_alerts_file = os.path.join(database_dir, "daily_alerts.json")
        self.signal_events_file = os.path.join(database_dir, "signal_events.jsonl")
        self.signal_tracker_file = os.path.join(database_dir, "signal_tracker.json")
        self.states = {}
        self.daily_alerts = {}
        self._daily_alerts_lock = threading.Lock()
        self._alert_lock_file = os.path.join(
            os.path.dirname(self.daily_alerts_file) or ".", ".alert_send.lock"
        )
        self._ensure_directory()
        self.load()
        self._load_daily_alerts()
    
    def _ensure_directory(self):
        """Create directory if not exists"""
        directory = os.path.dirname(self.state_file)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)
    
    def load(self):
        """Load states from file"""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    self.states = json.load(f)
                logger.info(f"Loaded {len(self.states)} stock states")
            else:
                self.states = {}
        except Exception as e:
            logger.error(f"Error loading states: {str(e)}")
            self.states = {}
    
    def save(self):
        """Save states to file"""
        try:
            with open(self.state_file, 'w') as f:
                json.dump(self.states, f, indent=2, default=str)
            logger.info(f"Saved {len(self.states)} stock states")
        except Exception as e:
            logger.error(f"Error saving states: {str(e)}")
    
    def get_state(self, ticker: str) -> dict:
        """Get state for a specific ticker"""
        return self.states.get(ticker, {})
    
    def get_all_states(self) -> dict:
        """Get all states"""
        return self.states
    
    def update_state(self, ticker: str, is_bullish: bool, status: str, score: int):
        """Update state for a specific ticker"""
        now = datetime.now().isoformat()
        
        previous = self.states.get(ticker, {})
        
        self.states[ticker] = {
            'is_bullish': is_bullish,
            'status': status,
            'score': score,
            'updated_at': now,
            'previous_is_bullish': previous.get('is_bullish'),
            'previous_status': previous.get('status')
        }
    
    def update_from_scan_result(self, result):
        """Update state from ScanResult object"""
        self.update_state(
            ticker=result.ticker,
            is_bullish=result.is_bullish,
            status=result.status,
            score=result.score
        )
    
    def is_new_bullish(self, ticker: str, current_is_bullish: bool) -> bool:
        """Check if stock just turned bullish"""
        prev_state = self.get_state(ticker)
        was_bullish = prev_state.get('is_bullish', None)
        
        # First time seeing this stock, or was bearish and now bullish
        if was_bullish is None:
            return False  # Don't alert on first scan
        
        return current_is_bullish and not was_bullish
    
    def is_new_bearish(self, ticker: str, current_is_bullish: bool) -> bool:
        """Check if stock just turned bearish"""
        prev_state = self.get_state(ticker)
        was_bullish = prev_state.get('is_bullish', None)
        
        if was_bullish is None:
            return False  # Don't alert on first scan
        
        return not current_is_bullish and was_bullish
    
    def is_status_upgrade(self, ticker: str, current_status: str) -> bool:
        """Check if status upgraded to STRONG BUY from HOLD/ACC"""
        prev_state = self.get_state(ticker)
        prev_status = prev_state.get('status', '')
        
        return current_status == "STRONG BUY" and prev_status in ["HOLD", "ACCUMULATE"]
    
    def clear_all(self):
        """Clear all states (useful for testing)"""
        self.states = {}
        self.save()
    
    # ============================================
    # DAILY ALERT TRACKING AND FREQUENCY GATE
    # ============================================

    def _load_daily_alerts(self):
        """Load daily claims and durable ticker-level alert history."""
        try:
            if os.path.exists(self.daily_alerts_file):
                with open(self.daily_alerts_file, "r", encoding="utf-8") as f:
                    self.daily_alerts = json.load(f)
            else:
                self.daily_alerts = {}

            if "history" not in self.daily_alerts:
                self.daily_alerts["history"] = self._bootstrap_alert_history()

            today = datetime.now().strftime("%Y-%m-%d")
            if self.daily_alerts.get("date") != today:
                self._reset_daily_alerts()
            else:
                self._save_daily_alerts()
        except Exception as exc:
            logger.error("Error loading daily alerts: %s", exc)
            self.daily_alerts = {"history": {}}
            self._reset_daily_alerts()

    def _bootstrap_alert_history(self) -> dict:
        """Migrate unique ticker/date calls from append-only events and legacy tracker."""
        history: Dict[str, set] = {}
        if os.path.exists(self.signal_events_file):
            try:
                with open(self.signal_events_file, "r", encoding="utf-8") as handle:
                    for line in handle:
                        if not line.strip():
                            continue
                        event = json.loads(line)
                        if event.get("event_type") != "SIGNAL_CREATED":
                            continue
                        ticker = _canonical_ticker(event.get("ticker"))
                        alert_date = str(event.get("occurred_at", ""))[:10]
                        if ticker and alert_date:
                            history.setdefault(ticker, set()).add(alert_date)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                logger.warning("Gagal bootstrap alert history dari event log: %s", exc)

        if os.path.exists(self.signal_tracker_file):
            try:
                with open(self.signal_tracker_file, "r", encoding="utf-8") as handle:
                    for signal in json.load(handle).values():
                        ticker = _canonical_ticker(signal.get("ticker"))
                        alert_date = signal.get("alert_date")
                        if ticker and alert_date:
                            history.setdefault(ticker, set()).add(alert_date)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                logger.warning("Gagal bootstrap alert history dari legacy tracker: %s", exc)

        return {ticker: sorted(dates) for ticker, dates in history.items()}

    def _reset_daily_alerts(self):
        """Reset daily claims while preserving cross-day call history."""
        today = datetime.now().strftime("%Y-%m-%d")
        history = self.daily_alerts.get("history", {})
        self.daily_alerts = {
            "date": today,
            "bullish_break": [],
            "strong_buy": [],
            "early_entry": [],
            "reversal_watch": [],
            "history": history,
        }
        self._save_daily_alerts()
        logger.info("Daily alerts reset for %s", today)

    def _save_daily_alerts(self):
        try:
            os.makedirs(os.path.dirname(self.daily_alerts_file) or ".", exist_ok=True)
            with open(self.daily_alerts_file, "w", encoding="utf-8") as f:
                json.dump(self.daily_alerts, f, indent=2)
        except Exception as exc:
            logger.error("Error saving daily alerts: %s", exc)

    def _was_ticker_alerted_today(self, ticker: str) -> bool:
        canonical = _canonical_ticker(ticker)
        return any(
            canonical in {_canonical_ticker(item) for item in self.daily_alerts.get(category, [])}
            for category in ALERT_CATEGORIES
        )

    def is_already_alerted(self, signal_type: str, ticker: str) -> bool:
        """Check globally across alert categories for the current date."""
        today = datetime.now().strftime("%Y-%m-%d")
        if self.daily_alerts.get("date") != today:
            self._reset_daily_alerts()
        canonical = _canonical_ticker(ticker)
        history_dates = self.daily_alerts.get("history", {}).get(canonical, [])
        if signal_type == "bullish_break":
            return canonical in {
                _canonical_ticker(item)
                for item in self.daily_alerts.get("bullish_break", [])
            }
        return self._was_ticker_alerted_today(ticker) or today in history_dates

    def _claim_alert_unlocked(self, signal_type: str, ticker: str) -> bool:
        if self.is_already_alerted(signal_type, ticker):
            logger.info("[AlertGate] Skip %s: sudah di-alert hari ini", ticker)
            return False

        canonical = _canonical_ticker(ticker)
        call_dates = self.daily_alerts.setdefault("history", {}).get(canonical, [])
        allowed, reason = evaluate_alert_frequency(call_dates, datetime.now().date())
        if not allowed:
            logger.info("[AlertGate] Skip %s: %s", ticker, reason)
            return False

        if signal_type not in self.daily_alerts:
            self.daily_alerts[signal_type] = []
        self.daily_alerts[signal_type].append(ticker)
        today = datetime.now().strftime("%Y-%m-%d")
        self.daily_alerts["history"].setdefault(canonical, []).append(today)
        self.daily_alerts["history"][canonical] = sorted(
            set(self.daily_alerts["history"][canonical])
        )
        self._save_daily_alerts()
        return True

    def try_claim_daily_alert(self, signal_type: str, ticker: str) -> bool:
        """Atomically claim a call after daily and rolling-frequency checks."""
        with self._daily_alerts_lock:
            if _HAS_FCNTL:
                os.makedirs(os.path.dirname(self._alert_lock_file) or ".", exist_ok=True)
                with open(self._alert_lock_file, "w") as lock_file:
                    fcntl.flock(lock_file, fcntl.LOCK_EX)
                    try:
                        self._load_daily_alerts()
                        return self._claim_alert_unlocked(signal_type, ticker)
                    finally:
                        fcntl.flock(lock_file, fcntl.LOCK_UN)
            return self._claim_alert_unlocked(signal_type, ticker)

    def try_claim_h1_alert(self, signal_type: str, ticker: str) -> bool:
        """Claim a closed-H1 signal while preserving the existing daily risk cap."""
        return self.try_claim_daily_alert(signal_type, ticker)

    def add_alerted_stock(self, signal_type: str, ticker: str):
        """Backward-compatible entrypoint; applies the same safety gate."""
        return self.try_claim_daily_alert(signal_type, ticker)

    def add_alerted_stocks(self, signal_type: str, tickers: List[str]):
        return [ticker for ticker in tickers if self.try_claim_daily_alert(signal_type, ticker)]

    def get_daily_summary(self) -> dict:
        return self.daily_alerts.copy()

    def reset_daily_if_new_day(self):
        today = datetime.now().strftime("%Y-%m-%d")
        if self.daily_alerts.get("date") != today:
            self._reset_daily_alerts()
    # ============================================
    # SIGNAL TRACKER - Track TP/SL outcomes
    # ============================================

    _TRACKER_FILE = "database/signal_tracker.json"
    _ARB_COOLDOWN_FILE = "database/arb_cooldown.json"

    def _load_tracker(self) -> dict:
        try:
            if os.path.exists(self._TRACKER_FILE):
                with open(self._TRACKER_FILE, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Error loading signal tracker: {e}")
        return {}

    def _save_tracker(self, tracker: dict):
        try:
            with open(self._TRACKER_FILE, 'w') as f:
                json.dump(tracker, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Error saving signal tracker: {e}")

    def _load_arb_cooldowns(self) -> dict:
        try:
            if os.path.exists(self._ARB_COOLDOWN_FILE):
                with open(self._ARB_COOLDOWN_FILE, encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Error loading ARB cooldowns: {e}")
        return {}

    def _save_arb_cooldowns(self, data: dict) -> None:
        try:
            os.makedirs(os.path.dirname(self._ARB_COOLDOWN_FILE) or ".", exist_ok=True)
            with open(self._ARB_COOLDOWN_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving ARB cooldowns: {e}")

    @staticmethod
    def _previous_trading_date(from_day: Optional[datetime] = None) -> str:
        """Tanggal sesi IDX sebelumnya (skip Sabtu/Minggu)."""
        day = (from_day or datetime.now()).date()
        d = day - timedelta(days=1)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        return d.strftime("%Y-%m-%d")

    def get_latest_alert_for_ticker(self, ticker: str) -> Optional[dict]:
        """Entri alert terbaru untuk ticker (dari signal_tracker)."""
        best: Optional[dict] = None
        best_key = ("", "")
        for sig in self._load_tracker().values():
            if sig.get("ticker") != ticker:
                continue
            key = (sig.get("alert_date") or "", sig.get("alert_time") or "")
            if key > best_key:
                best_key = key
                best = sig
        return best

    def was_latest_call_previous_session(self, ticker: str) -> bool:
        """
        True jika call TERAKHIR ticker jatuh pada sesi perdagangan sebelumnya.
        Contoh: call Senin → filter ARB aktif Selasa (bukan 45 hari ke belakang).
        """
        latest = self.get_latest_alert_for_ticker(ticker)
        if not latest:
            return False
        return latest.get("alert_date") == self._previous_trading_date()

    def is_in_arb_cooldown(self, ticker: str) -> bool:
        return ticker in self._load_arb_cooldowns()

    def mark_arb_cooldown(self, ticker: str, change_percent: float) -> None:
        data = self._load_arb_cooldowns()
        if ticker in data:
            return
        latest = self.get_latest_alert_for_ticker(ticker) or {}
        data[ticker] = {
            "since": datetime.now().strftime("%Y-%m-%d"),
            "arb_change_pct": round(float(change_percent), 2),
            "trigger_alert_date": latest.get("alert_date"),
            "trigger_signal_type": latest.get("signal_type"),
        }
        self._save_arb_cooldowns(data)
        logger.info(
            f"[ARB] Cooldown {ticker} (call {latest.get('alert_date')} → ARB "
            f"{change_percent:.1f}%)"
        )

    def clear_arb_cooldown(self, ticker: str) -> None:
        data = self._load_arb_cooldowns()
        if ticker not in data:
            return
        del data[ticker]
        self._save_arb_cooldowns(data)

    def track_signal(self, result, signal_type: str):
        """Record a new signal with entry price, TP1, TP2, SL for outcome tracking."""
        tracker = self._load_tracker()
        key = f"{result.ticker}_{signal_type}"
        if key in tracker and tracker[key].get('status') == 'ACTIVE':
            return
        sl_price = result.price * 0.95
        tracker[key] = {
            'signal_id': getattr(result, 'signal_id', None),
            'ticker': result.ticker,
            'signal_type': signal_type,
            'entry_price': result.price,
            'tp1': getattr(result, 'tp1', 0),
            'tp2': getattr(result, 'tp2', 0) or getattr(result, 'tp_swing', 0),
            'sl': sl_price,
            'alert_date': datetime.now().strftime('%Y-%m-%d'),
            'alert_time': datetime.now().strftime('%H:%M'),
            'status': 'ACTIVE',
            'hit_price': None,
            'hit_date': None,
            'score': result.score,
            'high_since_entry': result.price,
            # Snapshot untuk replay format alert di evaluasi harian
            'change_percent': getattr(result, 'change_percent', 0.0),
            'volume_ratio': getattr(result, 'volume_ratio', 0.0),
            'macd_status': getattr(result, 'macd_status', '') or '',
            'obv_status': getattr(result, 'obv_status', '') or '',
            'tp2_source': getattr(result, 'tp2_source', 'ATR') or 'ATR',
            'correction_percent': getattr(result, 'correction_percent', 0.0),
        }
        self._save_tracker(tracker)
        logger.info(f"[Tracker] Recorded {signal_type} for {result.ticker} "
                     f"@ {result.price:.0f} | TP1={getattr(result, 'tp1', 0):.0f} SL={sl_price:.0f}")

    def get_today_alert_snapshots(self) -> Dict[str, List[dict]]:
        """Sinyal yang pernah di-alert hari ini (untuk replay di evaluasi 16:30)."""
        today = datetime.now().strftime('%Y-%m-%d')
        grouped: Dict[str, List[dict]] = {
            'strong_buy': [],
            'early_entry': [],
            'reversal_watch': [],
        }
        for sig in self._load_tracker().values():
            if sig.get('alert_date') != today:
                continue
            st = sig.get('signal_type')
            if st in grouped:
                grouped[st].append(sig)
        for st in grouped:
            grouped[st].sort(key=lambda s: (s.get('alert_time', ''), s.get('ticker', '')))
        return grouped

    def evaluate_signals(self, current_prices: dict) -> dict:
        """
        Evaluate all ACTIVE signals against current prices.
        Returns dict with lists: tp1_hit, tp2_hit, sl_hit, still_active.
        """
        tracker = self._load_tracker()
        today = datetime.now().strftime('%Y-%m-%d')

        outcome = {'tp1_hit': [], 'tp2_hit': [], 'sl_hit': [], 'active': []}

        for key, sig in list(tracker.items()):
            if sig['status'] != 'ACTIVE':
                continue

            ticker = sig['ticker']
            price = current_prices.get(ticker)
            if price is None:
                outcome['active'].append(sig)
                continue

            if price > sig.get('high_since_entry', sig['entry_price']):
                sig['high_since_entry'] = price

            tp1 = sig.get('tp1', 0)
            tp2 = sig.get('tp2', 0)
            sl = sig.get('sl', 0)

            if tp2 and price >= tp2:
                sig['status'] = 'TP2_HIT'
                sig['hit_price'] = price
                sig['hit_date'] = today
                outcome['tp2_hit'].append(sig)
            elif tp1 and price >= tp1:
                sig['status'] = 'TP1_HIT'
                sig['hit_price'] = price
                sig['hit_date'] = today
                outcome['tp1_hit'].append(sig)
            elif sl and price <= sl:
                sig['status'] = 'SL_HIT'
                sig['hit_price'] = price
                sig['hit_date'] = today
                outcome['sl_hit'].append(sig)
            else:
                outcome['active'].append(sig)

        self._save_tracker(tracker)
        return outcome

    def is_signal_done(self, ticker: str, signal_type: str) -> bool:
        """Check if a signal already hit TP1/TP2 (i.e. trade is done)."""
        tracker = self._load_tracker()
        key = f"{ticker}_{signal_type}"
        sig = tracker.get(key)
        if sig is None:
            return False
        return sig['status'] in ('TP1_HIT', 'TP2_HIT')

    def get_active_signals(self) -> list:
        """Return all signals with status ACTIVE."""
        tracker = self._load_tracker()
        return [s for s in tracker.values() if s['status'] == 'ACTIVE']

    def cleanup_old_signals(self, max_age_days: int = 30):
        """Remove resolved signals older than max_age_days."""
        tracker = self._load_tracker()
        today = datetime.now()
        to_remove = []
        for key, sig in tracker.items():
            if sig['status'] == 'ACTIVE':
                continue
            try:
                hit_date = datetime.strptime(sig.get('hit_date', sig['alert_date']), '%Y-%m-%d')
                if (today - hit_date).days > max_age_days:
                    to_remove.append(key)
            except (ValueError, TypeError):
                pass
        for key in to_remove:
            del tracker[key]
        if to_remove:
            self._save_tracker(tracker)
            logger.info(f"[Tracker] Cleaned up {len(to_remove)} old signals")
