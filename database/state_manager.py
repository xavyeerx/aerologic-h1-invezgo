# ============================================
# STATE MANAGER - TRACK STOCK STATES
# ============================================

import json
import os
from datetime import datetime
from typing import Dict, Optional, List
import logging

logger = logging.getLogger(__name__)


class StateManager:
    """Manage persistent state for stocks"""
    
    def __init__(self, state_file: str = "database/stock_states.json"):
        self.state_file = state_file
        self.daily_alerts_file = "database/daily_alerts.json"
        self.states = {}
        self.daily_alerts = {}
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
            'bull_div': []
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
    
    def add_alerted_stock(self, signal_type: str, ticker: str):
        """Mark stock as alerted for this signal type today"""
        if signal_type not in self.daily_alerts:
            self.daily_alerts[signal_type] = []
        
        if ticker not in self.daily_alerts[signal_type]:
            self.daily_alerts[signal_type].append(ticker)
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
