import logging
from html import escape
from datetime import datetime
from typing import List

import pytz
import requests

from config.settings import (
    SCANNER_BUILD_ID,
    SIGNAL_API_ENABLED,
    SIGNAL_API_URL,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    TELEGRAM_TEST_CHAT_ID,
    TELEGRAM_SCANNER_TOPIC_ID,
)

logger = logging.getLogger(__name__)
WIB = pytz.timezone("Asia/Jakarta")
TELEGRAM_MAX_CHARS = 3800
ALERT_FOOTER = "<i>Powered by Aerologic</i>"


def get_current_time_wib() -> str:
    return datetime.now(WIB).strftime("%d %b %Y, %H:%M WIB")


def _format_transaction_value(value: float) -> str:
    """Format nilai transaksi rupiah secara ringkas untuk alert Telegram."""
    value = float(value or 0.0)
    for divisor, suffix in ((1_000_000_000_000, "T"), (1_000_000_000, "B"), (1_000_000, "M")):
        if abs(value) >= divisor:
            return f"{value / divisor:.1f}".replace(".", ",") + suffix
    return f"{value:,.0f}".replace(",", ".")


def _format_volume_and_value(result) -> str:
    return (
        f"Vol {result.volume_ratio:.1f}x | "
        f"Val {_format_transaction_value(getattr(result, 'daily_turnover', 0.0))}"
    )


def _append_alert_footer(lines: List[str]) -> None:
    lines.extend(["", ALERT_FOOTER])

def send_telegram_message(
    message: str,
    thread_id: "int | None" = None,
    *,
    chat_id: "str | None" = None,
    use_default_thread: bool = True,
) -> bool:
    destination_chat_id = chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not destination_chat_id:
        logger.warning("Telegram not configured. Message would be:\n%s", message)
        return True

    if thread_id is None and use_default_thread:
        thread_id = TELEGRAM_SCANNER_TOPIC_ID

    payload = {
        "chat_id": destination_chat_id,
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


def _format_tp_info(result, *, spaced_labels: bool = False) -> str:
    lines = []
    tp1_label = "TP 1" if spaced_labels else "TP1"
    tp2_label = "TP 2" if spaced_labels else "TP2"
    if getattr(result, "tp1", 0) > result.price:
        tp1_pct = ((result.tp1 - result.price) / result.price) * 100
        lines.append(f"{tp1_label}: {result.tp1:,.0f} (+{tp1_pct:.1f}%)")
    if getattr(result, "tp2", 0) > result.price:
        tp2_pct = ((result.tp2 - result.price) / result.price) * 100
        source = getattr(result, "tp2_source", "ATR")
        lines.append(f"{tp2_label}: {result.tp2:,.0f} (+{tp2_pct:.1f}%) {source}")
    return "\n".join(lines)


def _format_market_regime(result) -> str:
    regime = str(getattr(result, "market_regime", "UNKNOWN") or "UNKNOWN").upper()
    return {"BULL": "BULLISH", "BEAR": "BEARISH"}.get(regime, regime)
def _build_api_payload(results: List, alert_type: str) -> List[dict]:
    """Membangun list payload terstruktur dari result objects untuk dikirim ke Next.js API.
    
    Semua nilai numerik (tp1_pct, tp2_pct, sl_pct) sudah dikalkulasi di sini,
    identik dengan yang dirender ke pesan Telegram — menjamin konsistensi data.
    """
    payload = []
    for r in results:
        tp1 = getattr(r, "tp1", None)
        tp2 = getattr(r, "tp2", None)
        tp1_valid = bool(tp1 and tp1 > r.price)
        tp2_valid = bool(tp2 and tp2 > r.price)
        tp1 = tp1 if tp1_valid else None
        tp2 = tp2 if tp2_valid else None
        tp1_pct = round(((tp1 - r.price) / r.price) * 100, 1) if tp1_valid else None
        tp2_pct = round(((tp2 - r.price) / r.price) * 100, 1) if tp2_valid else None
        payload.append({
            "ticker": r.ticker.replace(".JK", ""),
            "alert_price": r.price,
            "change_percent": round(r.change_percent, 1),
            "score": r.score,
            "volume_ratio": round(r.volume_ratio, 1),
            "daily_turnover": _format_transaction_value(getattr(r, "daily_turnover", 0)),
            "market_regime": getattr(r, "market_regime", "UNKNOWN"),
            "tp1": tp1,
            "tp1_pct": tp1_pct,
            "tp2": tp2,
            "tp2_pct": tp2_pct,
            "tp2_source": getattr(r, "tp2_source", None),
            "sl": round(r.price * 0.95, 0),
            "sl_pct": -5.0,
            "alert_type": alert_type,
            "alerted_at": datetime.now(WIB).isoformat(),
            "status": "open",
        })
    return payload


def _send_to_api(results: List, alert_type: str) -> None:
    """Kirim data signal terstruktur ke Next.js API."""
    if not SIGNAL_API_ENABLED or not SIGNAL_API_URL or not alert_type:
        return
    try:
        api_payload = _build_api_payload(results, alert_type)
        response = requests.post(
            SIGNAL_API_URL,
            json=api_payload,
            timeout=10,
        )
        if response.status_code != 200:
            logger.warning("Custom API error: %s", response.text)
    except Exception as exc:
        logger.warning("Custom API call failed: %s", exc)


def format_strong_buy_message(results: List, *, total_count: int | None = None, part: int = 1) -> str:
    if not results:
        return ""
    title = "<b>STRONG BUY H1</b>"
    if part > 1:
        title += f" <i>(bagian {part})</i>"
    lines = [
        "--------------------------",
        "🚀" + title,
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
            f"   Score {result.score} | {_format_volume_and_value(result)} | Mkt {regime}"
        )
        tp_info = _format_tp_info(result)
        if tp_info:
            lines.append(tp_info)
        lines.append("")
    total = total_count if total_count is not None else len(results)
    lines.append(f"Total: {total} saham strong buy")
    _append_alert_footer(lines)
    return "\n".join(lines)


def _format_sector(result) -> str:
    sector = str(getattr(result, "sector", "UNKNOWN") or "UNKNOWN").strip()
    return escape(sector or "UNKNOWN")


def _format_supertrend_support(result) -> float:
    return float(getattr(result, "supertrend_support", 0.0) or 0.0)


def format_reversal_watch_message(results: List, *, total_count: int | None = None, part: int = 1) -> str:
    if not results:
        return ""
    title = "<b>REVERSAL WATCH H1</b>"
    if part > 1:
        title += f" <i>(bagian {part})</i>"
    lines = [
        "--------------------------",
        "👁️" + title,
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
            "Candle H1: CLOSED"
            if getattr(result, "bar_closed", True)
            else "Candle H1: LIVE (belum close)"
        )
        lines.append(
            f"   Return 20 bar {getattr(result, 'return20_pct', 0.0):+.1f}% | "
            f"RSI {getattr(result, 'rsi', 50.0):.1f} | {_format_volume_and_value(result)}"
        )
        lines.append("")
    total = total_count if total_count is not None else len(results)
    lines.append(f"Total: {total} saham reversal watch")
    _append_alert_footer(lines)
    return "\n".join(lines)


def _format_title(title: str, part: int) -> str:
    formatted = f"<b>{title}</b>"
    if part > 1:
        formatted += f" <i>(bagian {part})</i>"
    return formatted


def _format_stock_header(result) -> str:
    ticker = result.ticker.replace(".JK", "")
    change = f"{result.change_percent:+.1f}%"
    return f"<b>{ticker} | {result.price:,.0f} ({change})</b>"


def _format_h1_bar_status(result) -> str:
    return "Candle H1: CLOSED" if getattr(result, "bar_closed", True) else "Candle H1: LIVE (belum close)"


def format_bullish_break_message(
    results: List, *, total_count: int | None = None, part: int = 1
) -> str:
    if not results:
        return ""
    lines = [
        _format_title("🔥 BULLISH BREAKOUT", part),
        "--------------------------",
        get_current_time_wib(),
        "",
    ]
    for result in results:
        resistance = float(getattr(result, "supertrend_value", 0.0) or 0.0)
        lines.append(_format_stock_header(result))
        lines.append(_format_h1_bar_status(result))
        lines.append(f"Resistance {resistance:,.0f} | {_format_volume_and_value(result)}")
        lines.append(f"Trend IHSG: {_format_market_regime(result)}")
        lines.append(f"Sector: {_format_sector(result)}")
        tp_info = _format_tp_info(result, spaced_labels=True)
        if tp_info:
            lines.append(tp_info)
        if resistance > 0:
            lines.append(f"RBS: {resistance:,.0f}")
            lines.extend([
                "",
                "Pantau area RBS (resistance become support), pastikan closing di atas harga tersebut agar bukan false breakout.",
            ])
        lines.append("")
    total = total_count if total_count is not None else len(results)
    lines.append(f"Total: {total} saham bullish breakout")
    _append_alert_footer(lines)
    return "\n".join(lines)


def format_strong_buy_message(
    results: List, *, total_count: int | None = None, part: int = 1
) -> str:
    if not results:
        return ""
    lines = [
        _format_title("🚀 STRONG BUY H1", part),
        "--------------------------",
        get_current_time_wib(),
        "",
    ]
    for result in results:
        lines.append(_format_stock_header(result))
        lines.append(_format_h1_bar_status(result))
        lines.append(f"Score {result.score} | {_format_volume_and_value(result)}")
        lines.append(f"Trend IHSG: {_format_market_regime(result)}")
        lines.append(f"Sector: {_format_sector(result)}")
        tp_info = _format_tp_info(result)
        if tp_info:
            lines.append(tp_info)
        support = _format_supertrend_support(result)
        if support > 0:
            lines.append(f"Support: {support:,.0f}")
            lines.extend([
                "",
                f"Pastikan area Support ({support:,.0f}) dijaga agar momentum masih bullish.",
            ])
        lines.append("")
    total = total_count if total_count is not None else len(results)
    lines.append(f"Total: {total} saham strong buy")
    _append_alert_footer(lines)
    return "\n".join(lines)


def format_early_entry_message(
    results: List, *, total_count: int | None = None, part: int = 1
) -> str:
    if not results:
        return ""
    lines = [
        _format_title("🎯 EARLY ENTRY H1 (SEROK BAWAH)", part),
        "--------------------------",
        get_current_time_wib(),
        "<i>Sinyal dini — tunggu konfirmasi, bukan auto-entry.</i>",
        "",
    ]
    for result in sorted(results, key=lambda item: item.early_entry_strength, reverse=True):
        lines.append(_format_stock_header(result))
        lines.append(_format_h1_bar_status(result))
        lines.append(
            f"Koreksi {getattr(result, 'correction_percent', 0.0):.1f}% | "
            f"{_format_volume_and_value(result)}"
        )
        lines.append(f"Trend IHSG: {_format_market_regime(result)}")
        lines.append(f"Sector: {_format_sector(result)}")
        tp_info = _format_tp_info(result)
        if tp_info:
            lines.append(tp_info)
        support = _format_supertrend_support(result)
        if support > 0:
            lines.append(f"Support: {support:,.0f}")
            lines.extend([
                "",
                f"Pastikan area Support ({support:,.0f}) dijaga agar momentum masih bullish.",
            ])
        lines.append("")
    total = total_count if total_count is not None else len(results)
    lines.append(f"Total: {total} saham early entry")
    _append_alert_footer(lines)
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


def send_chunked_alert(results: List, format_fn, thread_id: "int | None" = None, alert_type: str = "") -> int:
    sent = 0
    for msg in _chunked_alert_messages(results, format_fn):
        if send_telegram_message(msg, thread_id=thread_id):
            sent += 1
    if sent > 0:
        _send_to_api(results, alert_type)
    return sent


def send_all_alerts(signals: dict) -> int:
    messages_sent = 0
    if signals.get("bullish_break"):
        messages_sent += send_chunked_alert(
            signals["bullish_break"], format_bullish_break_message,
            thread_id=TELEGRAM_SCANNER_TOPIC_ID,
        )
    if signals.get("strong_buy"):
        messages_sent += send_chunked_alert(
            signals["strong_buy"], format_strong_buy_message, thread_id=TELEGRAM_SCANNER_TOPIC_ID, alert_type="strong_buy"
        )
    if signals.get("early_entry"):
        messages_sent += send_chunked_alert(
            signals["early_entry"], format_early_entry_message, thread_id=TELEGRAM_SCANNER_TOPIC_ID, alert_type="early_entry"
        )
    if signals.get("reversal_watch"):
        messages_sent += send_chunked_alert(
            signals["reversal_watch"], format_reversal_watch_message, thread_id=TELEGRAM_SCANNER_TOPIC_ID, alert_type="reversal_watch"
        )
    return messages_sent


def send_startup_message():
    if not TELEGRAM_TEST_CHAT_ID:
        logger.warning("TELEGRAM_TEST_CHAT_ID belum dikonfigurasi; notifikasi startup tidak dikirim")
        return
    message = f"""
--------------------------
<b>AEROLOGIC H1 STARTED</b>
--------------------------
{get_current_time_wib()}
Build: <code>{SCANNER_BUILD_ID}</code>

Schedule: every 5 minutes during IDX sessions; forming H1 bars are eligible.
Alerts: Bullish Breakout H1, Strong Buy H1, Early Entry H1.
--------------------------
"""
    send_telegram_message(
        message.strip(),
        chat_id=TELEGRAM_TEST_CHAT_ID,
        use_default_thread=False,
    )
