"""Append-only local truth layer for signal lifecycle events."""

from __future__ import annotations

import json
import math
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import pytz

WIB = pytz.timezone("Asia/Jakarta")
DEFAULT_EVENT_PATH = Path("database/signal_events.jsonl")


def new_signal_id() -> str:
    return str(uuid.uuid4())


def _json_safe(value):
    """Normalize pandas/NumPy scalars and non-finite numbers before persistence."""
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except (ValueError, TypeError):
            pass
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


class SignalEventStore:
    """Durable JSONL event store; lifecycle transitions are append-only."""

    def __init__(self, path: str | Path = DEFAULT_EVENT_PATH):
        self.path = Path(path)
        self._lock = threading.Lock()

    def append(self, event_type: str, *, signal_id: str, ticker: str,
               payload: dict[str, Any] | None = None, origin: str = "LIVE",
               occurred_at: datetime | None = None) -> dict[str, Any]:
        timestamp = occurred_at or datetime.now(WIB)
        if timestamp.tzinfo is None:
            timestamp = WIB.localize(timestamp)
        event = {
            "event_id": str(uuid.uuid4()), "event_type": event_type,
            "signal_id": signal_id, "ticker": ticker,
            "occurred_at": timestamp.astimezone(WIB).isoformat(),
            "origin": origin, "payload": _json_safe(payload or {}),
        }
        encoded = (json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            descriptor = os.open(self.path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
            try:
                os.write(descriptor, encoded)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        return event

    def load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        events = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid signal event JSON at line {line_number}") from exc
        return events

    def events_for(self, signal_id: str) -> list[dict[str, Any]]:
        return [event for event in self.load() if event.get("signal_id") == signal_id]


def signal_snapshot(scan_result, signal_type: str, regime_info: dict) -> dict[str, Any]:
    """Serialize point-in-time evidence needed for replay and audit."""
    fields: Iterable[str] = (
        "price", "change_percent", "score", "volume_ratio", "adx", "stoch_k",
        "stoch_d", "supertrend_value", "is_supertrend_flip", "is_bullish_break",
        "is_st_continuation",
        "is_counter_trend", "is_bullish_engulfing", "is_price_breakout", "atr_pct",
        "tp1", "tp2", "tp2_source", "entry_zone_low", "entry_zone_high",
        "sl", "sl_source", "daily_atr", "support", "resistance",
    )
    settings = __import__("config.settings", fromlist=["SCANNER_BUILD_ID"])
    setup_families = {
        "bullish_break": "SUPERTREND_BREAK",
        "strong_buy": "SUPERTREND_CONFIRMATION",
        "early_entry": "HEALTHY_CORRECTION",
        "reversal_watch": "SELLING_CLIMAX_REVERSAL",
    }
    formula_versions = {
        "strong_buy": "strong_buy_supertrend_v2",
    }
    return {
        "signal_type": signal_type,
        "setup_family": setup_families.get(
            signal_type, getattr(scan_result, "signal_family", "NONE")
        ),
        "mode": "PRODUCTION",
        "formula_version": formula_versions.get(signal_type, "h1_intrabar_v1"),
        "build_id": settings.SCANNER_BUILD_ID,
        "timeframe": "H1",
        "bar_timestamp": getattr(scan_result, "bar_timestamp", None),
        "bar_closed": getattr(scan_result, "bar_closed", None),
        "market_regime": regime_info.get("regime", "UNKNOWN"),
        "features": {name: getattr(scan_result, name, None) for name in fields},
    }
