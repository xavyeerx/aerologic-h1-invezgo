import logging
import re
from html import escape
from datetime import datetime
from typing import List

import pytz
import requests

from core.news_context import format_context_date

from config.settings import (
    BACKEND_WEBHOOK_SECRET,
    SCANNER_BUILD_ID,
    SIGNAL_API_ENABLED,
    SIGNAL_API_URL,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    TELEGRAM_SCANNER_TOPIC_ID,
    TELEGRAM_TEST_CHAT_ID,
)

logger = logging.getLogger(__name__)
WIB = pytz.timezone("Asia/Jakarta")
ALERT_FOOTER = "<i>Powered by Aerologic</i>"
ALERT_DISCLAIMER = "<i>DYOR. Bukan rekomendasi beli atau jual. Risiko di tangan masing-masing.</i>"


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
    lines.extend(["", ALERT_DISCLAIMER, ALERT_FOOTER])


def _sanitize_context_text(value: object) -> str:
    without_source_brand = re.sub(
        r"\binvezgo(?:\s+(?:news|report))?\b[\s,:-]*",
        "",
        str(value or ""),
        flags=re.IGNORECASE,
    )
    return escape(" ".join(without_source_brand.split()))


def _format_context_item(item) -> str:
    return f"• {format_context_date(item.published_at)}: {_sanitize_context_text(item.title)}"


def _append_news_context(lines: List[str], result) -> None:
    context = getattr(result, "news_context", None)
    if context is None:
        return

    ticker = escape(str(result.ticker).replace(".JK", ""))
    lines.extend(["", f"<b>📰 KONTEKS &amp; KATALIS {ticker}</b>"])
    if context.direct is None:
        lines.append("Katalis langsung: Tidak ditemukan")
    else:
        sentiment = "Positif" if context.direct.sentiment == "positive" else "Negatif/Risiko"
        lines.extend([
            f"Katalis langsung: {sentiment} — "
            f"{format_context_date(context.direct.published_at)}:",
            _sanitize_context_text(context.direct.title),
        ])

    if context.positives:
        lines.append("Positif:")
        lines.extend(_format_context_item(item) for item in context.positives)
    if context.risks:
        lines.append("Negatif/Risiko:")
        lines.extend(_format_context_item(item) for item in context.risks)

    if context.direct is None:
        conclusion = (
            "Momentum teknikal belum didukung katalis baru yang terverifikasi. "
            "Waspadai volatilitas dan risiko aksi harga spekulatif."
        )
    elif context.direct.sentiment == "positive":
        conclusion = (
            "Momentum teknikal memiliki katalis positif terbaru yang teridentifikasi. "
            "Konfirmasi keberlanjutan respons harga dan tetap disiplin pada batas risiko."
        )
    else:
        conclusion = (
            "Momentum teknikal disertai risiko material terbaru yang perlu diperhatikan. "
            "Waspadai volatilitas dan tetap disiplin pada batas risiko."
        )
    lines.extend(["", f"Kesimpulannya {conclusion}"])

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


def send_operational_event(event: str, *details: str) -> bool:
    """Send scheduler lifecycle/error events to the isolated monitoring chat."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_TEST_CHAT_ID:
        logger.warning(
            "Telegram operational channel not configured; event %s was not sent",
            event,
        )
        return False

    lines = [
        f"<b>AEROLOGIC H1 {escape(str(event).upper())}</b>",
        get_current_time_wib(),
        f"Build: <code>{escape(SCANNER_BUILD_ID)}</code>",
    ]
    lines.extend(escape(str(detail)) for detail in details if detail)
    return send_telegram_message(
        "\n".join(lines),
        chat_id=TELEGRAM_TEST_CHAT_ID,
        use_default_thread=False,
    )


def _format_tp_info(result, *, spaced_labels: bool = False) -> str:
    lines = []
    tp1_label = "TP 1" if spaced_labels else "TP1"
    tp2_label = "TP 2" if spaced_labels else "TP2"
    if getattr(result, "tp1", 0) > result.price:
        tp1_pct = ((result.tp1 - result.price) / result.price) * 100
        lines.append(f"{tp1_label}: {result.tp1:,.0f} (+{tp1_pct:.1f}%)")
    if getattr(result, "tp2", 0) > result.price:
        tp2_pct = ((result.tp2 - result.price) / result.price) * 100
        lines.append(f"{tp2_label}: {result.tp2:,.0f} (+{tp2_pct:.1f}%)")
    return "\n".join(lines)


def _format_entry_and_sl(result) -> str:
    price = float(getattr(result, "price", 0.0) or 0.0)
    entry_low = float(getattr(result, "entry_zone_low", 0.0) or 0.0)
    entry_high = float(getattr(result, "entry_zone_high", 0.0) or 0.0)
    sl = float(getattr(result, "sl", 0.0) or 0.0)
    lines = []
    if 0 < entry_low <= entry_high:
        lines.append(f"Entry Area: {entry_low:,.0f} - {entry_high:,.0f}")
    if price > 0 and 0 < sl < price:
        sl_pct = ((sl - price) / price) * 100
        lines.append(f"SL: {sl:,.0f} ({sl_pct:.1f}%)")
    return "\n".join(lines)


def _format_market_regime(result) -> str:
    regime = str(getattr(result, "market_regime", "UNKNOWN") or "UNKNOWN").upper()
    return {"BULL": "BULLISH", "BEAR": "BEARISH"}.get(regime, regime)


def _positive_price(value) -> "int | None":
    value = float(value or 0.0)
    return round(value) if value > 0 else None


def _build_api_payload(result, alert_type: str) -> dict:
    """Payload ticker alert untuk web app; harga yang tidak tampil di Telegram dikirim null."""
    price = float(getattr(result, "price", 0.0) or 0.0)
    entry_low = _positive_price(getattr(result, "entry_zone_low", None))
    entry_high = _positive_price(getattr(result, "entry_zone_high", None))
    if entry_low is None or entry_high is None or entry_low > entry_high:
        entry_low = entry_high = None
    tp_price = _positive_price(getattr(result, "tp1", None))
    sl = _positive_price(getattr(result, "sl", None))
    return {
        "ticker": result.ticker.replace(".JK", ""),
        "entry_low": entry_low,
        "entry_high": entry_high,
        "tp_price": tp_price if tp_price and tp_price > price else None,
        "sl": sl if sl and sl < price else None,
        "alert_type": alert_type,
        "alerted_at": datetime.now(WIB).isoformat(timespec="seconds"),
    }


def _send_to_api(result, alert_type: str) -> None:
    """Kirim satu ticker alert ke web app setelah pesan Telegram-nya terkirim."""
    if not SIGNAL_API_ENABLED or not SIGNAL_API_URL or not alert_type:
        return
    if not BACKEND_WEBHOOK_SECRET:
        logger.warning("BACKEND_WEBHOOK_SECRET not configured; ticker alert API skipped")
        return
    try:
        response = requests.post(
            SIGNAL_API_URL,
            json=_build_api_payload(result, alert_type),
            headers={"x-webhook-secret": BACKEND_WEBHOOK_SECRET},
            timeout=10,
        )
        if not response.ok:
            logger.warning("Ticker alert API error: %s - %s", response.status_code, response.text)
    except Exception as exc:
        logger.warning("Ticker alert API call failed: %s", exc)


def _format_sector(result) -> str:
    sector = str(getattr(result, "sector", "UNKNOWN") or "UNKNOWN").strip()
    return escape(sector or "UNKNOWN")


def _format_supertrend_support(result) -> float:
    return float(getattr(result, "supertrend_support", 0.0) or 0.0)


def format_reversal_watch_message(results: List) -> str:
    if not results:
        return ""
    lines = [
        "--------------------------",
        "👁️ <b>REVERSAL WATCH</b>",
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
            f"RSI {getattr(result, 'rsi', 50.0):.1f} | {_format_volume_and_value(result)}"
        )
        _append_news_context(lines, result)
        lines.append("")
    _append_alert_footer(lines)
    return "\n".join(lines)


def _format_stock_header(result) -> str:
    ticker = result.ticker.replace(".JK", "")
    change = f"{result.change_percent:+.1f}%"
    return f"<b>{ticker} | {result.price:,.0f} ({change})</b>"


def format_bullish_break_message(results: List) -> str:
    if not results:
        return ""
    lines = [
        "<b>🔥 BULLISH BREAKOUT</b>",
        "--------------------------",
        get_current_time_wib(),
        "",
    ]
    for result in results:
        resistance = float(getattr(result, "supertrend_value", 0.0) or 0.0)
        lines.append(_format_stock_header(result))
        lines.append(f"Resistance {resistance:,.0f} | {_format_volume_and_value(result)}")
        lines.append("")
        lines.append(f"Trend IHSG: {_format_market_regime(result)}")
        lines.append(f"Sector: {_format_sector(result)}")
        lines.append("")
        entry_info = _format_entry_and_sl(result)
        if entry_info:
            lines.append(entry_info)
        tp_info = _format_tp_info(result, spaced_labels=True)
        if tp_info:
            lines.append(tp_info)
        if resistance > 0:
            lines.append(f"RBS: {resistance:,.0f}")
            lines.extend([
                "",
                "Pantau area RBS (resistance become support), pastikan closing di atas harga tersebut agar bukan false breakout.",
            ])
        _append_news_context(lines, result)
        lines.append("")
    _append_alert_footer(lines)
    return "\n".join(lines)


def format_strong_buy_message(results: List) -> str:
    if not results:
        return ""
    lines = [
        "<b>🚀 STRONG BUY</b>",
        "--------------------------",
        get_current_time_wib(),
        "",
    ]
    for result in results:
        lines.append(_format_stock_header(result))
        lines.append(_format_volume_and_value(result))
        lines.append("")
        lines.append(f"Trend IHSG: {_format_market_regime(result)}")
        lines.append(f"Sector: {_format_sector(result)}")
        lines.append("")
        entry_info = _format_entry_and_sl(result)
        if entry_info:
            lines.append(entry_info)
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
        _append_news_context(lines, result)
        lines.append("")
    _append_alert_footer(lines)
    return "\n".join(lines)


def format_early_entry_message(results: List) -> str:
    if not results:
        return ""
    lines = [
        "<b>🎯 EARLY ENTRY</b>",
        "--------------------------",
        get_current_time_wib(),
        "<i>Sinyal dini — tunggu konfirmasi, bukan auto-entry.</i>",
        "",
    ]
    for result in sorted(results, key=lambda item: item.early_entry_strength, reverse=True):
        lines.append(_format_stock_header(result))
        lines.append(
            f"Koreksi {getattr(result, 'correction_percent', 0.0):.1f}% | "
            f"{_format_volume_and_value(result)}"
        )
        lines.append("")
        lines.append(f"Trend IHSG: {_format_market_regime(result)}")
        lines.append(f"Sector: {_format_sector(result)}")
        lines.append("")
        entry_info = _format_entry_and_sl(result)
        if entry_info:
            lines.append(entry_info)
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
        _append_news_context(lines, result)
        lines.append("")
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
    return [format_fn([result]) for result in _dedupe_results_by_ticker(results)]


def send_chunked_alert(results: List, format_fn, thread_id: "int | None" = None, alert_type: str = "") -> int:
    sent = 0
    for result in _dedupe_results_by_ticker(results):
        if send_telegram_message(format_fn([result]), thread_id=thread_id):
            sent += 1
            _send_to_api(result, alert_type)
    return sent


def send_all_alerts(signals: dict) -> int:
    messages_sent = 0
    if signals.get("bullish_break"):
        messages_sent += send_chunked_alert(
            signals["bullish_break"], format_bullish_break_message,
            thread_id=TELEGRAM_SCANNER_TOPIC_ID, alert_type="Breakout",
        )
    if signals.get("strong_buy"):
        messages_sent += send_chunked_alert(
            signals["strong_buy"], format_strong_buy_message, thread_id=TELEGRAM_SCANNER_TOPIC_ID, alert_type="Strong Buy"
        )
    if signals.get("early_entry"):
        messages_sent += send_chunked_alert(
            signals["early_entry"], format_early_entry_message, thread_id=TELEGRAM_SCANNER_TOPIC_ID, alert_type="Early Entry"
        )
    if signals.get("reversal_watch"):
        messages_sent += send_chunked_alert(
            signals["reversal_watch"], format_reversal_watch_message, thread_id=TELEGRAM_SCANNER_TOPIC_ID, alert_type="Reversal Watch"
        )
    return messages_sent
