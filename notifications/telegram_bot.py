import logging
from datetime import datetime
from typing import List

import pytz
import requests

from config.settings import (
    SCANNER_BUILD_ID,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    TELEGRAM_TOPIC_DEFAULT,
    TELEGRAM_TOPIC_STARTUP,
    TELEGRAM_TOPIC_STRONG_BUY,
)

logger = logging.getLogger(__name__)
WIB = pytz.timezone("Asia/Jakarta")
TELEGRAM_MAX_CHARS = 3800


def get_current_time_wib() -> str:
    return datetime.now(WIB).strftime("%d %b %Y, %H:%M WIB")


def send_telegram_message(message: str, thread_id: "int | None" = None) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured. Message would be:\n%s", message)
        return True

    if thread_id is None:
        thread_id = TELEGRAM_TOPIC_DEFAULT

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if thread_id is not None:
        payload["message_thread_id"] = thread_id

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            logger.info("Telegram message sent successfully")
            return True
        logger.error("Telegram error: %s - %s", response.status_code, response.text)
        return False
    except Exception as exc:
        logger.error("Error sending Telegram message: %s", exc)
        return False


def _format_tp_info(result) -> str:
    lines = []
    if getattr(result, "tp1", 0) > 0:
        tp1_pct = ((result.tp1 - result.price) / result.price) * 100
        lines.append(f"   TP1: {result.tp1:,.0f} (+{tp1_pct:.1f}%)")
    if getattr(result, "tp2", 0) > 0:
        tp2_pct = ((result.tp2 - result.price) / result.price) * 100
        source = getattr(result, "tp2_source", "ATR")
        lines.append(f"   TP2: {result.tp2:,.0f} (+{tp2_pct:.1f}%) {source}")
    if getattr(result, "price", 0) > 0:
        lines.append(f"   SL: {result.price * 0.95:,.0f} (-5.0%)")
    return "\n".join(lines)


def format_strong_buy_message(results: List, *, total_count: int | None = None, part: int = 1) -> str:
    if not results:
        return ""
    title = "<b>STRONG BUY DAILY</b>"
    if part > 1:
        title += f" <i>(bagian {part})</i>"
    lines = [
        "--------------------------",
        title,
        "--------------------------",
        get_current_time_wib(),
        "",
    ]
    for result in results:
        ticker = result.ticker.replace(".JK", "")
        change = f"+{result.change_percent:.1f}%" if result.change_percent >= 0 else f"{result.change_percent:.1f}%"
        regime = getattr(result, "market_regime", "UNKNOWN")
        lines.append(f"<b>{ticker}</b> | {result.price:,.0f} ({change})")
        lines.append(
            f"   MOM-EXP | Score {result.score} | Vol {result.volume_ratio:.1f}x | "
            f"Ret20 {getattr(result, 'return20_pct', 0.0):+.1f}% | Mkt {regime}"
        )
        tp_info = _format_tp_info(result)
        if tp_info:
            lines.append(tp_info)
        lines.append("")
    total = total_count if total_count is not None else len(results)
    lines.append(f"Total: {total} saham strong buy")
    return "\n".join(lines)


def format_early_entry_message(results: List, *, total_count: int | None = None, part: int = 1) -> str:
    if not results:
        return ""
    title = "<b>EARLY ENTRY DAILY (SEROK BAWAH)</b>"
    if part > 1:
        title += f" <i>(bagian {part})</i>"
    lines = [
        "--------------------------",
        title,
        "--------------------------",
        get_current_time_wib(),
        "<i>Sinyal dini — tunggu konfirmasi, bukan auto-entry.</i>",
        "",
    ]
    for result in sorted(results, key=lambda x: x.early_entry_strength, reverse=True):
        ticker = result.ticker.replace(".JK", "")
        change = f"+{result.change_percent:.1f}%" if result.change_percent >= 0 else f"{result.change_percent:.1f}%"
        strength = getattr(result, "early_entry_strength", 0)
        lines.append(f"<b>{ticker}</b> | {result.price:,.0f} ({change})")
        lines.append(
            f"   Koreksi {getattr(result, 'correction_percent', 0.0):.1f}% | "
            f"Strength {strength}/7 | Score {result.score}"
        )
        tp_info = _format_tp_info(result)
        if tp_info:
            lines.append(tp_info)
        lines.append("")
    total = total_count if total_count is not None else len(results)
    lines.append(f"Total: {total} saham early entry")
    return "\n".join(lines)


def format_reversal_watch_message(results: List, *, total_count: int | None = None, part: int = 1) -> str:
    if not results:
        return ""
    title = "<b>REVERSAL WATCH DAILY</b>"
    if part > 1:
        title += f" <i>(bagian {part})</i>"
    lines = [
        "--------------------------",
        title,
        "--------------------------",
        get_current_time_wib(),
        "<i>Watchlist risiko tinggi; tunggu follow-through, bukan auto-entry.</i>",
        "",
    ]
    for result in sorted(results, key=lambda x: x.volume_ratio, reverse=True):
        ticker = result.ticker.replace(".JK", "")
        change = f"+{result.change_percent:.1f}%" if result.change_percent >= 0 else f"{result.change_percent:.1f}%"
        lines.append(f"<b>{ticker}</b> | {result.price:,.0f} ({change})")
        lines.append(
            f"   Return 20 bar {getattr(result, 'return20_pct', 0.0):+.1f}% | "
            f"RSI {getattr(result, 'rsi', 50.0):.1f} | Vol {result.volume_ratio:.1f}x"
        )
        lines.append("")
    total = total_count if total_count is not None else len(results)
    lines.append(f"Total: {total} saham reversal watch")
    return "\n".join(lines)


def _dedupe_results_by_ticker(results: List) -> List:
    seen = set()
    output = []
    for result in results:
        ticker = getattr(result, "ticker", None)
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        output.append(result)
    return output


def _chunked_alert_messages(results: List, format_fn) -> List[str]:
    results = _dedupe_results_by_ticker(results)
    if not results:
        return []

    total = len(results)
    messages: List[str] = []
    idx = 0
    part = 1
    while idx < len(results):
        lo = idx
        hi = lo + 1
        while hi <= len(results):
            msg = format_fn(results[lo:hi], total_count=total, part=part)
            if len(msg) > TELEGRAM_MAX_CHARS:
                if hi - lo == 1:
                    break
                hi -= 1
                break
            if hi == len(results):
                break
            hi += 1
        messages.append(format_fn(results[lo:hi], total_count=total, part=part))
        idx = hi
        part += 1
    return messages


def send_chunked_alert(results: List, format_fn, thread_id: "int | None" = None) -> int:
    sent = 0
    for msg in _chunked_alert_messages(results, format_fn):
        if send_telegram_message(msg, thread_id=thread_id):
            sent += 1
    return sent


def send_all_alerts(signals: dict) -> int:
    messages_sent = 0
    if signals.get("strong_buy"):
        messages_sent += send_chunked_alert(
            signals["strong_buy"], format_strong_buy_message, thread_id=TELEGRAM_TOPIC_STRONG_BUY
        )
    if signals.get("early_entry"):
        messages_sent += send_chunked_alert(
            signals["early_entry"], format_early_entry_message, thread_id=TELEGRAM_TOPIC_STRONG_BUY
        )
    if signals.get("reversal_watch"):
        messages_sent += send_chunked_alert(
            signals["reversal_watch"], format_reversal_watch_message, thread_id=TELEGRAM_TOPIC_STRONG_BUY
        )
    return messages_sent


def send_startup_message():
    message = f"""
--------------------------
<b>QUANTPILOT DAILY STARTED</b>
--------------------------
{get_current_time_wib()}
Build: <code>{SCANNER_BUILD_ID}</code>

Schedule: Mon-Thu 09:01-12:00 and 13:31-16:01 WIB; Fri 09:01-12:00 and 14:01-16:01 WIB; every 5 minutes.
Alerts: Strong Buy Daily, Early Entry Daily, Reversal Watch Daily.
--------------------------
"""
    send_telegram_message(message.strip(), thread_id=TELEGRAM_TOPIC_STARTUP)
