# ============================================
# STATE MANAGER - TRACK STOCK STATES
# ============================================

import json
import os
from datetime import datetime, timedelta
from typing import Dict, Optional, List
import logging
import threading

try:
    import fcntl
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False

logger = logging.getLogger(__name__)


class StateManager:
    """Manage persistent state for stocks"""
    
    def __init__(self, state_file: str = "database/stock_states.json"):
        self.state_file = state_file
        self.daily_alerts_file = "database/daily_alerts.json"
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
    # DAILY ALERT TRACKING
    # ============================================
    
    def _load_daily_alerts(self):
        """Load daily alerts from file"""
        try:
            if os.path.exists(self.daily_alerts_file):
                with open(self.daily_alerts_file, 'r') as f:
                    self.daily_alerts = json.load(f)
                
                # Check if it's a new day - reset if so
                today = datetime.now().strftime('%Y-%m-%d')
                if self.daily_alerts.get('date') != today:
                    self._reset_daily_alerts()
            else:
                self._reset_daily_alerts()
        except Exception as e:
            logger.error(f"Error loading daily alerts: {str(e)}")
            self._reset_daily_alerts()
    
    def _reset_daily_alerts(self):
        """Reset daily alerts for a new day"""
        today = datetime.now().strftime('%Y-%m-%d')
        self.daily_alerts = {
            'date': today,
            'strong_buy': [],
            'accumulation': [],
            'early_entry': [],
            'chart_patterns': [],
            'morning_patterns_scanned_done_on': '',
        }
        self._save_daily_alerts()
        logger.info(f"Daily alerts reset for {today}")
    
    def _save_daily_alerts(self):
        """Save daily alerts to file"""
        try:
            with open(self.daily_alerts_file, 'w') as f:
                json.dump(self.daily_alerts, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving daily alerts: {str(e)}")
    
    def is_already_alerted(self, signal_type: str, ticker: str) -> bool:
        """Check if stock was already alerted for this signal type today"""
        # Make sure we're on the same day
        today = datetime.now().strftime('%Y-%m-%d')
        if self.daily_alerts.get('date') != today:
            self._reset_daily_alerts()
        
        return ticker in self.daily_alerts.get(signal_type, [])

    def try_claim_daily_alert(self, signal_type: str, ticker: str) -> bool:
        """
        Klaim slot alert harian (atomik). True = boleh kirim Telegram sekarang.
        Mencegah dobel jika dua proses scheduler jalan bersamaan.
        """
        with self._daily_alerts_lock:
            if _HAS_FCNTL:
                os.makedirs(os.path.dirname(self._alert_lock_file) or ".", exist_ok=True)
                with open(self._alert_lock_file, "w") as lf:
                    fcntl.flock(lf, fcntl.LOCK_EX)
                    try:
                        self._load_daily_alerts()
                        if self.is_already_alerted(signal_type, ticker):
                            return False
                        self.add_alerted_stock(signal_type, ticker)
                        return True
                    finally:
                        fcntl.flock(lf, fcntl.LOCK_UN)
            if self.is_already_alerted(signal_type, ticker):
                return False
            self.add_alerted_stock(signal_type, ticker)
            return True
    
    def add_alerted_stock(self, signal_type: str, ticker: str):
        """Mark stock as alerted for this signal type today"""
        if signal_type not in self.daily_alerts:
            self.daily_alerts[signal_type] = []

        if ticker not in self.daily_alerts[signal_type]:
            self.daily_alerts[signal_type].append(ticker)
            self._save_daily_alerts()

    def is_chart_combo_alerted(self, ticker: str, pattern_key: str) -> bool:
        """Cegah kirim pola chart yang sama dua kali dalam satu hari."""
        needle = f"{ticker}|{pattern_key}"
        return needle in self.daily_alerts.get('chart_patterns', [])

    def add_chart_pattern_alert(self, ticker: str, pattern_key: str):
        if 'chart_patterns' not in self.daily_alerts:
            self.daily_alerts['chart_patterns'] = []
        needle = f"{ticker}|{pattern_key}"
        if needle not in self.daily_alerts['chart_patterns']:
            self.daily_alerts['chart_patterns'].append(needle)
            self._save_daily_alerts()

    def morning_chart_patterns_already_scanned_today(self) -> bool:
        today = datetime.now().strftime('%Y-%m-%d')
        if self.daily_alerts.get('date') != today:
            self._reset_daily_alerts()
        return self.daily_alerts.get('morning_patterns_scanned_done_on') == today

    def mark_morning_chart_patterns_scan_complete(self):
        self.reset_daily_if_new_day()
        self.daily_alerts['morning_patterns_scanned_done_on'] = datetime.now().strftime('%Y-%m-%d')
        self._save_daily_alerts()
    
    def add_alerted_stocks(self, signal_type: str, tickers: List[str]):
        """Mark multiple stocks as alerted"""
        for ticker in tickers:
            self.add_alerted_stock(signal_type, ticker)
    
    def get_daily_summary(self) -> dict:
        """Get summary of all stocks alerted today per signal type"""
        return self.daily_alerts.copy()
    
    def reset_daily_if_new_day(self):
        """Check and reset if it's a new day"""
        today = datetime.now().strftime('%Y-%m-%d')
        if self.daily_alerts.get('date') != today:
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
            'early_entry_strength': getattr(result, 'early_entry_strength', 0),
        }
        self._save_tracker(tracker)
        logger.info(f"[Tracker] Recorded {signal_type} for {result.ticker} "
                     f"@ {result.price:.0f} | TP1={getattr(result, 'tp1', 0):.0f} SL={sl_price:.0f}")

    def get_today_alert_snapshots(self) -> Dict[str, List[dict]]:
        """Sinyal yang pernah di-alert hari ini (untuk replay di evaluasi 16:30)."""
        today = datetime.now().strftime('%Y-%m-%d')
        grouped: Dict[str, List[dict]] = {
            'strong_buy': [],
            'accumulation': [],
            'early_entry': [],
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
