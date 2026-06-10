# ============================================
# TELEGRAM BOT - SEND ALERTS v5.0
# ============================================

import requests
from typing import List, Dict, Any
import logging
from datetime import datetime
import pytz

import sys
sys.path.append('..')
from config.settings import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    BUY_THRESHOLD,
    ENGULF_MIN_VOLUME_RATIO,
    STRONG_BUY_ENGULF_MIN_SCORE,
    CHART_PATTERN_ALERT_HOUR,
    CHART_PATTERN_ALERT_MINUTE,
    CHART_PATTERN_FORCE_SCHEDULED_ONLY,
    CHART_PATTERN_REALTIME,
    SCANNER_BUILD_ID,
)

logger = logging.getLogger(__name__)

# Timezone
WIB = pytz.timezone('Asia/Jakarta')


def get_current_time_wib() -> str:
    """Get current time in WIB format"""
    now = datetime.now(WIB)
    return now.strftime("%d %b %Y, %H:%M WIB")


def _chart_pattern_mode_line() -> str:
    if CHART_PATTERN_REALTIME:
        return "realtime tiap scan sesi"
    slot = f"reviu terjadwal {CHART_PATTERN_ALERT_HOUR:02d}:{CHART_PATTERN_ALERT_MINUTE:02d} WIB (1×/hari)"
    if CHART_PATTERN_FORCE_SCHEDULED_ONLY:
        return f"{slot} — tidak realtime"
    return slot


def send_telegram_message(message: str) -> bool:
    """
    Send message via Telegram Bot API
    """
    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE" or TELEGRAM_CHAT_ID == "YOUR_CHAT_ID_HERE":
        logger.warning("Telegram not configured. Message would be:")
        print("\n" + "="*50)
        print(message)
        print("="*50 + "\n")
        return True
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            'chat_id': TELEGRAM_CHAT_ID,
            'text': message,
            'parse_mode': 'HTML',
            'disable_web_page_preview': True
        }
        
        response = requests.post(url, json=payload, timeout=10)
        
        if response.status_code == 200:
            logger.info("Telegram message sent successfully")
            return True
        else:
            logger.error(f"Telegram error: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"Error sending Telegram message: {str(e)}")
        return False


def _format_tp_info(r) -> str:
    """Format target price info (TP1, TP2, SL) for a stock"""
    lines = []
    if getattr(r, 'tp1', 0) > 0:
        tp1_pct = ((r.tp1 - r.price) / r.price) * 100
        lines.append(f"   🎯 TP1: {r.tp1:,.0f} (+{tp1_pct:.1f}%)")
    
    if getattr(r, 'tp2', 0) > 0:
        tp2_pct = ((r.tp2 - r.price) / r.price) * 100
        source = getattr(r, 'tp2_source', 'ATR')
        src_label = "📋 resist" if source == "RESISTANCE" else "ATR"
        lines.append(f"   🚀 TP2: {r.tp2:,.0f} (+{tp2_pct:.1f}%) {src_label}")
    
    # Tambah SL 5% dari harga terkini
    sl_price = r.price * 0.95
    lines.append(f"   🛑 SL: {sl_price:,.0f} (-5.0%)")
    
    return "\n".join(lines)


TELEGRAM_MAX_CHARS = 3800  # Telegram hard limit 4096; leave buffer for HTML entities


def format_strong_buy_message(
    results: List,
    *,
    total_count: int | None = None,
    part: int = 1,
) -> str:
    """Format Strong Buy (confirmed breakout) alert message"""
    if not results:
        return ""

    title = "🚀 <b>STRONG BUY SIGNAL</b>"
    if part > 1:
        title += f" <i>(bagian {part})</i>"

    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        title,
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"⏰ {get_current_time_wib()}",
        ""
    ]
    
    for r in results:
        ticker_clean = r.ticker.replace('.JK', '')
        change_str = f"+{r.change_percent:.1f}%" if r.change_percent >= 0 else f"{r.change_percent:.1f}%"
        lines.append(f"🟢 <b>{ticker_clean}</b> | {r.price:,.0f} ({change_str})")
        trigger = "ENGULF▲" if getattr(r, "is_bullish_engulfing", False) else (
            "RS-BEAR▲" if getattr(r, "is_counter_trend", False) else (
                "BULL-DIV▲" if getattr(r, "is_bull_div", False) else (
                    "ST▲" if getattr(r, "is_supertrend_flip", False) else (
                        "BREAKOUT+VOL" if getattr(r, "is_price_breakout", False) else "VOL"
                    )
                )
            )
        )
        regime_tag = getattr(r, "market_regime", "") or ""
        regime_suffix = f" | Mkt:{regime_tag}" if regime_tag and regime_tag != "UNKNOWN" else ""
        lines.append(
            f"   └─ Score: {r.score} | {trigger} | Vol: {r.volume_ratio:.1f}x | "
            f"{getattr(r, 'pattern_name', None) or '-'}{regime_suffix}"
        )
        tp_info = _format_tp_info(r)
        if tp_info:
            lines.append(tp_info)
        lines.append("")
    
    lines.append(f"━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(
        f"💡 <i>Threshold adaptif per regime IHSG. BEAR: counter-trend (hijau + vol + trigger) "
        f"selain ST/engulf/breakout fresh. BULL: breakout + ADX + score ≥{BUY_THRESHOLD}</i>"
    )
    total = total_count if total_count is not None else len(results)
    if total_count and len(results) < total_count:
        lines.append(f"Tampil: {len(results)} dari {total} saham strong buy")
    else:
        lines.append(f"Total: {total} saham strong buy")
    
    return "\n".join(lines)


def format_accumulation_message(
    results: List,
    *,
    total_count: int | None = None,
    part: int = 1,
) -> str:
    """Format accumulation signal message"""
    if not results:
        return ""

    title = "🔵 <b>ACCUMULATION SIGNAL</b>"
    if part > 1:
        title += f" <i>(bagian {part})</i>"

    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        title,
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"⏰ {get_current_time_wib()}",
        ""
    ]
    
    for r in results:
        ticker_clean = r.ticker.replace('.JK', '')
        change_str = f"+{r.change_percent:.1f}%" if r.change_percent >= 0 else f"{r.change_percent:.1f}%"
        lines.append(f"📊 <b>{ticker_clean}</b> | {r.price:,.0f} ({change_str})")
        lines.append(f"   └─ Score: {r.score} | OBV: {r.obv_status} | Vol: {r.volume_ratio:.1f}x")
        tp_info = _format_tp_info(r)
        if tp_info:
            lines.append(tp_info)
        lines.append("")
    
    lines.append(f"━━━━━━━━━━━━━━━━━━━━━━━━━━")
    total = total_count if total_count is not None else len(results)
    if total_count and len(results) < total_count:
        lines.append(f"Tampil: {len(results)} dari {total} saham accumulation")
    else:
        lines.append(f"Total: {total} saham accumulation")
    
    return "\n".join(lines)


def format_early_entry_message(
    results: List,
    *,
    total_count: int | None = None,
    part: int = 1,
) -> str:
    """Format Early Entry (Serok Bawah) message"""
    if not results:
        return ""

    title = "🎯 <b>EARLY ENTRY (SEROK BAWAH)</b>"
    if part > 1:
        title += f" <i>(bagian {part})</i>"

    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        title,
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"⏰ {get_current_time_wib()}",
        ""
    ]
    
    # Sort by strength (highest first)
    sorted_results = sorted(results, key=lambda x: x.early_entry_strength, reverse=True)
    
    for r in sorted_results:
        ticker_clean = r.ticker.replace('.JK', '')
        change_str = f"+{r.change_percent:.1f}%" if r.change_percent >= 0 else f"{r.change_percent:.1f}%"
        
        # Strength indicator
        strength = r.early_entry_strength
        emoji = "🔥" if strength >= 5 else "💎" if strength >= 3 else "📍"
        
        lines.append(f"{emoji} <b>{ticker_clean}</b> | {r.price:,.0f} ({change_str})")
        lines.append(f"   └─ Koreksi: {r.correction_percent:.1f}% | Strength: {strength}/7")
        tp_info = _format_tp_info(r)
        if tp_info:
            lines.append(tp_info)
        lines.append("")
    
    lines.append(f"━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("⚠️ <i>Sinyal dini - DYOR!</i>")
    total = total_count if total_count is not None else len(results)
    if total_count and len(results) < total_count:
        lines.append(f"Tampil: {len(results)} dari {total} saham early entry")
    else:
        lines.append(f"Total: {total} saham early entry")
    
    return "\n".join(lines)


def format_chart_pattern_morning_message(
    items: List[Dict[str, Any]],
    test_mode: bool = False,
    realtime: bool = False,
) -> str:
    """
    Digest pola chart bullish (TF daily), selalu judul terjadwal (bukan realtime).
    """
    if not items:
        return ""

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for it in sorted(items, key=lambda x: (x["pattern_key"], x["ticker"])):
        grouped.setdefault(it["pattern_key"], []).append(it)

    badge = ""
    if test_mode:
        badge = (
            "🧪 <b>MODE UJI TELEGRAM</b> • tidak menyentuh dedup / kuota sekali-scan harian •"
        )

    slot = f"{CHART_PATTERN_ALERT_HOUR:02d}:{CHART_PATTERN_ALERT_MINUTE:02d}"
    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "📐 <b>CHART PATTERNS — REVIU HARIAN (TF-D)</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    if badge:
        lines.extend([badge, ""])
    lines.extend(
        [
            f"⏰ {get_current_time_wib()}",
            f"<i>Slot terjadwal: {slot} WIB (1×/hari) • build {SCANNER_BUILD_ID}</i>",
            "<i>Filter info: RSI(14) hanya dicantumkan per baris (bukan syarat).</i>",
            "<i>Konfirmasi kualitas: naik ⇒ vol ≥ MA20 • turun/doji ⇒ vol ≤ MA20 • OBV &gt; EMA OBV.</i>",
            "<i>Heuristik otomatis. Candle harian setelah tutup IDX (hari perdagangan yang sama).</i>",
            "",
        ]
    )

    for pkey in sorted(grouped.keys()):
        rows = grouped[pkey]
        label = rows[0].get("label", pkey)
        lines.append(f"<b>{label}</b>")
        for r in rows:
            t = str(r["ticker"]).replace(".JK", "")
            ch = r.get("change_pct", 0.0)
            chs = f"+{ch:.1f}%" if ch >= 0 else f"{ch:.1f}%"
            vm = r.get("vol_vs_avg", 1.0)
            rsi = r.get("rsi14")
            rsi_txt = f" • RSI14 {rsi:.1f}" if rsi is not None else ""
            lines.append(
                f"• <b>{t}</b> | {r['price']:,.0f} ({chs}) | Vol {vm:.2f}×{rsi_txt}"
            )
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"Total: {len(items)} baris pola (bisa 1 ticker → beberapa pola)")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")

    return "\n".join(lines)


def send_chart_pattern_morning_digest(
    items: List[Dict[str, Any]],
    test_mode: bool = False,
    realtime: bool = False,
) -> bool:
    msg = format_chart_pattern_morning_message(items, test_mode=test_mode, realtime=False)
    if not msg:
        if test_mode:
            nm = (
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "📐 <b>CHART PATTERNS — UJI TELEGRAM (TF-D)</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "🧪 <i>Mode uji • tidak ada baris pola yang lolos filter.</i>\n"
                f"⏰ {get_current_time_wib()}"
            )
            return send_telegram_message(nm)
        return False
    return send_telegram_message(msg)


def _dedupe_results_by_ticker(results: List) -> List:
    seen = set()
    out = []
    for r in results:
        t = getattr(r, "ticker", None)
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(r)
    return out


def _chunked_alert_messages(results: List, format_fn) -> List[str]:
    """Split alert into multiple messages under TELEGRAM_MAX_CHARS."""
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

        msg = format_fn(results[lo:hi], total_count=total, part=part)
        messages.append(msg)
        idx = hi
        part += 1

    return messages


def send_chunked_alert(results: List, format_fn) -> int:
    """Send one alert type, splitting into multiple Telegram messages if needed."""
    sent = 0
    for msg in _chunked_alert_messages(results, format_fn):
        if send_telegram_message(msg):
            sent += 1
    return sent


def send_all_alerts(signals: dict) -> int:
    """
    Send all alert messages (v5)
    Signal types: strong_buy, accumulation, early_entry
    """
    messages_sent = 0
    
    if signals.get('strong_buy'):
        messages_sent += send_chunked_alert(signals['strong_buy'], format_strong_buy_message)
    
    if signals.get('accumulation'):
        messages_sent += send_chunked_alert(signals['accumulation'], format_accumulation_message)
    
    if signals.get('early_entry'):
        messages_sent += send_chunked_alert(signals['early_entry'], format_early_entry_message)
    
    return messages_sent


def send_startup_message():
    """Send startup notification"""
    msg = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━
🤖 <b>IHSG SCANNER v5.0 STARTED</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━
⏰ {get_current_time_wib()}
🔖 Build: <code>{SCANNER_BUILD_ID}</code>

Scanner is now running.
Scan interval: back-to-back (langsung setelah selesai)
Trading hours: 08:30 - 16:00 WIB

📊 Alerts:
• 📐 Chart Patterns — {_chart_pattern_mode_line()}
• 🚀 Strong Buy (confirmed breakout)
• 🔵 Accumulation
• 🎯 Early Entry (Serok Bawah)
━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    send_telegram_message(msg.strip())


def send_scan_complete_message(total_stocks: int, signals_count: dict):
    """Send scan completion summary (optional)"""
    total_signals = sum(len(v) for v in signals_count.values())
    
    if total_signals == 0:
        return  # Don't send if no signals


def send_daily_recap_message(daily_summary: dict):
    """
    Send end-of-day recap message with ALL stocks that triggered signals today (v5).
    """
    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "📋 <b>REKAP HARIAN - END OF DAY (opsi BSJP)</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📅 {daily_summary.get('date', 'N/A')}",
        f"⏰ {get_current_time_wib()}",
        ""
    ]
    
    total_signals = 0
    
    # Strong Buy
    strong = daily_summary.get('strong_buy', [])
    if strong:
        lines.append(f"🚀 <b>STRONG BUY</b> ({len(strong)} saham)")
        tickers = [t.replace('.JK', '') for t in strong]
        lines.append(f"   {', '.join(tickers)}")
        lines.append("")
        total_signals += len(strong)
    
    # Accumulation
    acc = daily_summary.get('accumulation', [])
    if acc:
        lines.append(f"🔵 <b>ACCUMULATION</b> ({len(acc)} saham)")
        tickers = [t.replace('.JK', '') for t in acc]
        lines.append(f"   {', '.join(tickers)}")
        lines.append("")
        total_signals += len(acc)
    
    # Early Entry
    early = daily_summary.get('early_entry', [])
    if early:
        lines.append(f"🎯 <b>EARLY ENTRY</b> ({len(early)} saham)")
        tickers = [t.replace('.JK', '') for t in early]
        lines.append(f"   {', '.join(tickers)}")
        lines.append("")
        total_signals += len(early)
    
    # Footer
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"📊 Total: {total_signals} sinyal hari ini")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
    
    message = "\n".join(lines)
    send_telegram_message(message)


def send_evaluation_message(outcome: dict):
    """Send daily TP/SL evaluation recap at 16:30 WIB."""
    tp1_hit = outcome.get('tp1_hit', [])
    tp2_hit = outcome.get('tp2_hit', [])
    sl_hit = outcome.get('sl_hit', [])
    active = outcome.get('active', [])

    total_resolved = len(tp1_hit) + len(tp2_hit) + len(sl_hit)
    if total_resolved == 0 and len(active) == 0:
        return

    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "📊 <b>EVALUASI SINYAL HARIAN</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"⏰ {get_current_time_wib()}",
        ""
    ]

    if tp2_hit:
        lines.append(f"🏆 <b>HIT TP2</b> ({len(tp2_hit)})")
        for s in tp2_hit:
            t = s['ticker'].replace('.JK', '')
            entry = s['entry_price']
            hit = s.get('hit_price', 0)
            pnl = ((hit - entry) / entry) * 100 if entry > 0 else 0
            lines.append(f"  ✅ {t} | Entry: {entry:,.0f} -> {hit:,.0f} (+{pnl:.1f}%)")
            lines.append(f"     {s['signal_type']} | Alert: {s['alert_date']}")
        lines.append("")

    if tp1_hit:
        lines.append(f"🎯 <b>HIT TP1</b> ({len(tp1_hit)})")
        for s in tp1_hit:
            t = s['ticker'].replace('.JK', '')
            entry = s['entry_price']
            hit = s.get('hit_price', 0)
            pnl = ((hit - entry) / entry) * 100 if entry > 0 else 0
            lines.append(f"  ✅ {t} | Entry: {entry:,.0f} -> {hit:,.0f} (+{pnl:.1f}%)")
            lines.append(f"     {s['signal_type']} | Alert: {s['alert_date']}")
        lines.append("")

    if sl_hit:
        lines.append(f"🛑 <b>HIT SL</b> ({len(sl_hit)})")
        for s in sl_hit:
            t = s['ticker'].replace('.JK', '')
            entry = s['entry_price']
            hit = s.get('hit_price', 0)
            pnl = ((hit - entry) / entry) * 100 if entry > 0 else 0
            lines.append(f"  ❌ {t} | Entry: {entry:,.0f} -> {hit:,.0f} ({pnl:.1f}%)")
            lines.append(f"     {s['signal_type']} | Alert: {s['alert_date']}")
        lines.append("")

    if active:
        lines.append(f"⏳ <b>MASIH AKTIF</b> ({len(active)})")
        for s in active:
            t = s['ticker'].replace('.JK', '')
            lines.append(f"  {t} | Entry: {s['entry_price']:,.0f} | "
                         f"TP1: {s.get('tp1', 0):,.0f} | SL: {s.get('sl', 0):,.0f}")
        lines.append("")

    win = len(tp1_hit) + len(tp2_hit)
    lose = len(sl_hit)
    total = win + lose
    winrate = (win / total * 100) if total > 0 else 0

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
    if total > 0:
        lines.append(f"📈 Win: {win} | Loss: {lose} | WR: {winrate:.0f}%")
    lines.append(f"⏳ Masih aktif: {len(active)} sinyal")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")

    send_telegram_message("\n".join(lines))


def send_morning_recap_message(signals: dict):
    """
    Digest radar saham (format lama "EVENING SCAN - 18:00").

    Tidak dipanggil scheduler — sebelumnya salah terkirim saat opening recap 08:45.
    Pertahankan untuk uji manual; untuk broadcast terjadwal, wire ke slot WIB terpisah.
    Splits into multiple messages if content exceeds Telegram limit.
    """
    
    # Build header
    header = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "🌙 <b>EVENING SCAN - 18:00</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"⏰ {get_current_time_wib()}",
        ""
    ]
    
    # Collect all sections
    sections = []
    total_signals = 0
    
    # Strong Buy (highest priority)
    strong_buy = signals.get('strong_buy', [])
    if strong_buy:
        section_lines = [f"🚀 <b>STRONG BUY</b> ({len(strong_buy)} saham)"]
        for r in strong_buy:
            ticker_clean = r.ticker.replace('.JK', '')
            section_lines.append(f"• {ticker_clean} | {r.price:,.0f} | Score: {r.score}")
            if r.tp1 and r.tp1 > 0:
                sl_price = r.price * 0.95
                section_lines.append(f"  🎯 TP1: {r.tp1:,.0f} | 🛑 SL: {sl_price:,.0f}")
        section_lines.append("")
        sections.append("\n".join(section_lines))
        total_signals += len(strong_buy)
    
    # Accumulation
    acc = signals.get('accumulation', [])
    if acc:
        section_lines = [f"🔵 <b>ACCUMULATION</b> ({len(acc)} saham)"]
        for r in acc:
            ticker_clean = r.ticker.replace('.JK', '')
            section_lines.append(f"• {ticker_clean} | {r.price:,.0f} | Score: {r.score}")
            if r.tp1 and r.tp1 > 0:
                sl_price = r.price * 0.95
                section_lines.append(f"  🎯 TP1: {r.tp1:,.0f} | 🛑 SL: {sl_price:,.0f}")
        section_lines.append("")
        sections.append("\n".join(section_lines))
        total_signals += len(acc)
    
    # Bullish (good score)
    bullish = signals.get('bullish', [])
    if bullish:
        section_lines = [f"📈 <b>BULLISH</b> ({len(bullish)} saham)"]
        tickers = [r.ticker.replace('.JK', '') for r in bullish]
        section_lines.append(", ".join(tickers))
        section_lines.append("")
        sections.append("\n".join(section_lines))
        total_signals += len(bullish)
    
    # Early Entry
    early = signals.get('early_entry', [])
    if early:
        section_lines = [f"🎯 <b>EARLY ENTRY</b> ({len(early)} saham)"]
        for r in early:
            ticker_clean = r.ticker.replace('.JK', '')
            section_lines.append(f"• {ticker_clean} | {r.price:,.0f} | Koreksi: {r.correction_percent:.1f}%")
            if r.tp1 and r.tp1 > 0:
                sl_price = r.price * 0.95
                section_lines.append(f"  🎯 TP1: {r.tp1:,.0f} | 🛑 SL: {sl_price:,.0f}")
        section_lines.append("")
        sections.append("\n".join(section_lines))
        total_signals += len(early)
    
    # Footer
    footer = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📊 Total: {total_signals} saham dalam radar",
        "💡 <i>Scan lengkap setelah market tutup</i>"
    ]
    
    # Combine and split messages if needed (Telegram limit ~4096 chars)
    MAX_LENGTH = 3800  # Leave some buffer
    
    current_message = "\n".join(header)
    messages_to_send = []
    
    for section in sections:
        # Check if adding this section exceeds limit
        if len(current_message) + len(section) + 2 > MAX_LENGTH:
            # Send current message and start new one
            messages_to_send.append(current_message)
            current_message = "━━━━━━━━━━━━━━━━━━━━━━━━━━\n🌙 <b>EVENING SCAN (lanjutan)</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n" + section
        else:
            current_message += "\n" + section
    
    # Add footer to last message
    current_message += "\n".join(footer)
    messages_to_send.append(current_message)
    
    # Send all messages
    for msg in messages_to_send:
        send_telegram_message(msg)
