# ============================================
# POST-ALERT ARB GATE
# ============================================
# Call kemarin → hari ini ARB (~-13%+) → skip alert sampai candle hijau (close > open).
# Hanya call TERAKHIR (sesi sebelumnya), bukan riwayat 45 hari.

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from config.settings import ARB_DROP_PCT_MIN

if TYPE_CHECKING:
    from database.state_manager import StateManager

logger = logging.getLogger(__name__)


def _is_green_candle(df) -> bool:
    if df is None or len(df) < 1:
        return False
    last = df.iloc[-1]
    if "open" not in df.columns:
        return False
    try:
        return float(last["close"]) > float(last["open"])
    except (TypeError, ValueError):
        return False


def is_arb_session(change_percent: float) -> bool:
    """True jika turun >= ARB_DROP_PCT_MIN% (mis. -13% atau lebih dalam)."""
    return change_percent <= -float(ARB_DROP_PCT_MIN)


def apply_post_alert_arb_gate(result, df, state_manager: Optional["StateManager"]) -> None:
    """
    Matikan strong_buy / accumulation / early_entry jika:
    - call terakhir = sesi kemarin, hari ini ARB, atau masih dalam cooldown itu, dan
    - belum ada konfirmasi hijau (close > open).
    """
    if state_manager is None:
        return

    ticker = result.ticker
    chg = float(getattr(result, "change_percent", 0.0) or 0.0)
    green = _is_green_candle(df)

    if state_manager.was_latest_call_previous_session(ticker) and is_arb_session(chg):
        state_manager.mark_arb_cooldown(ticker, chg)

    if not state_manager.is_in_arb_cooldown(ticker):
        return

    if green:
        state_manager.clear_arb_cooldown(ticker)
        logger.info(f"[ARB] {ticker}: konfirmasi hijau — cooldown dilepas")
        return

    if result.is_strong_buy or result.is_accumulation or result.is_early_entry:
        logger.info(
            f"[ARB] {ticker}: sinyal diblokir (cooldown pasca-alert, "
            f"chg={chg:.1f}%, tunggu candle hijau)"
        )
    result.is_strong_buy = False
    result.is_accumulation = False
    result.is_early_entry = False
