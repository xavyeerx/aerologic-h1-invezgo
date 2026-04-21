# ============================================
# TELEGRAM BOT - SEND ALERTS v5.0
# ============================================

import requests
from typing import List
import logging
from datetime import datetime
import pytz

import sys
sys.path.append('..')
from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)

# Timezone
WIB = pytz.timezone('Asia/Jakarta')


def get_current_time_wib() -> str:
    """Get current time in WIB format"""
    now = datetime.now(WIB)
    return now.strftime("%d %b %Y, %H:%M WIB")


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


def format_strong_buy_message(results: List) -> str:
    """Format Strong Buy (confirmed breakout) alert message"""
    if not results:
        return ""
    
    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "🚀 <b>STRONG BUY SIGNAL</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"⏰ {get_current_time_wib()}",
        ""
    ]
    
    for r in results:
        ticker_clean = r.ticker.replace('.JK', '')
        change_str = f"+{r.change_percent:.1f}%" if r.change_percent >= 0 else f"{r.change_percent:.1f}%"
        lines.append(f"🟢 <b>{ticker_clean}</b> | {r.price:,.0f} ({change_str})")
        lines.append(f"   └─ Score: {r.score} | MACD: {r.macd_status} | Vol: {r.volume_ratio:.1f}x")
        tp_info = _format_tp_info(r)
        if tp_info:
            lines.append(tp_info)
        lines.append("")
    
    lines.append(f"━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"💡 <i>Breakout terkonfirmasi + score ≥ {70}</i>")
    lines.append(f"Total: {len(results)} saham strong buy")
    
    return "\n".join(lines)


def format_accumulation_message(results: List) -> str:
    """Format accumulation signal message"""
    if not results:
        return ""
    
    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "🔵 <b>ACCUMULATION SIGNAL</b>",
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
    lines.append(f"Total: {len(results)} saham accumulation")
    
    return "\n".join(lines)


def format_bull_div_message(results: List) -> str:
    """Format Bullish Divergence alert message (v5.1 Enhanced)"""
    if not results:
        return ""

    strong = [r for r in results if getattr(r, 'div_grade', '') == 'STRONG']
    moderate = [r for r in results if getattr(r, 'div_grade', '') == 'MODERATE']
    weak = [r for r in results if getattr(r, 'div_grade', '') == 'WEAK']

    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "🔀 <b>BULLISH DIVERGENCE</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"⏰ {get_current_time_wib()}",
        ""
    ]

    if strong:
        lines.append("🔥 <b>STRONG</b>")
        for r in strong:
            ticker_clean = r.ticker.replace('.JK', '')
            change_str = f"+{r.change_percent:.1f}%" if r.change_percent >= 0 else f"{r.change_percent:.1f}%"
            strength = getattr(r, 'div_strength', 0)
            lines.append(f"🟢 <b>{ticker_clean}</b> | {r.price:,.0f} ({change_str})")
            lines.append(f"   └─ Score: {r.score} | Stoch: K{r.stoch_k:.0f}/D{r.stoch_d:.0f} | Str: {strength}/6")
            tp_info = _format_tp_info(r)
            if tp_info:
                lines.append(tp_info)
            lines.append("")

    if moderate:
        lines.append("📊 <b>MODERATE</b>")
        for r in moderate:
            ticker_clean = r.ticker.replace('.JK', '')
            change_str = f"+{r.change_percent:.1f}%" if r.change_percent >= 0 else f"{r.change_percent:.1f}%"
            strength = getattr(r, 'div_strength', 0)
            lines.append(f"🟡 <b>{ticker_clean}</b> | {r.price:,.0f} ({change_str})")
            lines.append(f"   └─ Score: {r.score} | Stoch: K{r.stoch_k:.0f}/D{r.stoch_d:.0f} | Str: {strength}/6")
            tp_info = _format_tp_info(r)
            if tp_info:
                lines.append(tp_info)
            lines.append("")

    if weak:
        lines.append("⚪ <b>WEAK</b>")
        for r in weak:
            ticker_clean = r.ticker.replace('.JK', '')
            change_str = f"+{r.change_percent:.1f}%" if r.change_percent >= 0 else f"{r.change_percent:.1f}%"
            lines.append(f"⚪ {ticker_clean} | {r.price:,.0f} ({change_str})")
            lines.append(f"   └─ Score: {r.score} | Stoch: K{r.stoch_k:.0f}/D{r.stoch_d:.0f}")
            lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("💡 <i>Pivot low + RSI higher low = potensi reversal</i>")
    lines.append(f"Total: {len(results)} ({len(strong)} strong, {len(moderate)} moderate, {len(weak)} weak)")

    return "\n".join(lines)


def format_early_entry_message(results: List) -> str:
    """Format Early Entry (Serok Bawah) message"""
    if not results:
        return ""
    
    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "🎯 <b>EARLY ENTRY (SEROK BAWAH)</b>",
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
    lines.append(f"Total: {len(results)} saham early entry")
    
    return "\n".join(lines)


def send_all_alerts(signals: dict) -> int:
    """
    Send all alert messages (v5)
    Signal types: strong_buy, accumulation, early_entry, bull_div
    """
    messages_sent = 0
    
    # Strong Buy (was bullish_break)
    if signals.get('strong_buy'):
        msg = format_strong_buy_message(signals['strong_buy'])
        if send_telegram_message(msg):
            messages_sent += 1
    
    # Accumulation
    if signals.get('accumulation'):
        msg = format_accumulation_message(signals['accumulation'])
        if send_telegram_message(msg):
            messages_sent += 1
    
    # Bullish Divergence (NEW)
    if signals.get('bull_div'):
        msg = format_bull_div_message(signals['bull_div'])
        if send_telegram_message(msg):
            messages_sent += 1
    
    # Early Entry (Serok Bawah)
    if signals.get('early_entry'):
        msg = format_early_entry_message(signals['early_entry'])
        if send_telegram_message(msg):
            messages_sent += 1
    
    return messages_sent


def send_startup_message():
    """Send startup notification"""
    msg = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━
🤖 <b>IHSG SCANNER v5.0 STARTED</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━
⏰ {get_current_time_wib()}

Scanner is now running.
Scan interval: setiap 1 menit
Trading hours: 08:45 - 16:00 WIB

📊 Alerts:
• 🚀 Strong Buy (confirmed breakout)
• 🔵 Accumulation
• 🔀 Bullish Divergence
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
    
    # Bullish Divergence
    div = daily_summary.get('bull_div', [])
    if div:
        lines.append(f"🔀 <b>BULL DIVERGENCE</b> ({len(div)} saham)")
        tickers = [t.replace('.JK', '') for t in div]
        lines.append(f"   {', '.join(tickers)}")
        lines.append("")
        total_signals += len(div)
    
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
    Send evening recap message at 18:00 with ALL stocks matching screener criteria (v5).
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
    
    # Bullish Divergence
    div = signals.get('bull_div', [])
    if div:
        section_lines = [f"🔀 <b>BULL DIVERGENCE</b> ({len(div)} saham)"]
        for r in div:
            ticker_clean = r.ticker.replace('.JK', '')
            section_lines.append(f"• {ticker_clean} | {r.price:,.0f} | Score: {r.score}")
            if r.tp1 and r.tp1 > 0:
                sl_price = r.price * 0.95
                section_lines.append(f"  🎯 TP1: {r.tp1:,.0f} | 🛑 SL: {sl_price:,.0f}")
        section_lines.append("")
        sections.append("\n".join(section_lines))
        total_signals += len(div)
    
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
