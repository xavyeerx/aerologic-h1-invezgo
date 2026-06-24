#!/usr/bin/env python3
# ============================================================
# SCRIPTS / BACKFILL_TODAY.PY
# ============================================================
# Script sekali jalan untuk insert sinyal hari ini ke DB.
# Berguna kalau DB baru konek setelah trading hours.
#
# Cara jalankan di Railway:
#   railway run python scripts/backfill_today.py
#
# Cara jalankan lokal (harus ada DATABASE_PUBLIC_URL di .env):
#   python scripts/backfill_today.py
# ============================================================

import sys
import os
import logging
import json
from datetime import datetime
import pytz

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

WIB = pytz.timezone('Asia/Jakarta')


def main():
    logger.info("=" * 60)
    logger.info("BACKFILL TODAY'S SIGNALS → Learning DB")
    logger.info("=" * 60)

    # ── 1. Cek DB tersedia ────────────────────────────────────
    from learning.db import init_db, is_available
    if not is_available():
        logger.error("❌ DATABASE_PUBLIC_URL tidak di-set. Tambahkan variable dulu.")
        sys.exit(1)

    ok = init_db()
    if not ok:
        logger.error("❌ Gagal konek ke DB. Cek DATABASE_PUBLIC_URL.")
        sys.exit(1)
    logger.info("✅ DB siap")

    # ── 2. Cek daily_alerts.json untuk tahu siapa yang di-alert ──
    daily_alerts_file = "database/daily_alerts.json"
    today = datetime.now(WIB).strftime('%Y-%m-%d')
    alerted_today = {}

    if os.path.exists(daily_alerts_file):
        with open(daily_alerts_file, 'r') as f:
            data = json.load(f)
        if data.get('date') == today:
            alerted_today = {
                'strong_buy':   data.get('strong_buy',   []),
                'accumulation': data.get('accumulation', []),
                'early_entry':  data.get('early_entry',  []),
            }
            total = sum(len(v) for v in alerted_today.values())
            logger.info(f"✅ Ditemukan {total} sinyal hari ini dari daily_alerts.json")
            for sig_type, tickers in alerted_today.items():
                if tickers:
                    logger.info(f"   {sig_type}: {len(tickers)} tickers")
        else:
            logger.warning(f"daily_alerts.json bukan hari ini ({data.get('date')} vs {today})")
    else:
        logger.warning("daily_alerts.json tidak ditemukan — akan scan ulang semua")

    # ── 3. Kalau daily_alerts tidak ada, scan ulang ───────────
    if not alerted_today or sum(len(v) for v in alerted_today.values()) == 0:
        logger.info("Melakukan scan ulang untuk menemukan sinyal hari ini...")
        alerted_today = _run_fresh_scan()
        if not alerted_today:
            logger.info("Tidak ada sinyal ditemukan. Selesai.")
            return

    # ── 4. Fetch data hanya untuk tickers yang di-alert ───────
    all_tickers = list({t for v in alerted_today.values() for t in v})
    logger.info(f"Fetching data untuk {len(all_tickers)} tickers...")

    from core.data_fetcher import fetch_multiple_stocks
    from config.settings import DATA_PERIOD, DATA_INTERVAL
    stock_data = fetch_multiple_stocks(all_tickers, period=DATA_PERIOD, interval=DATA_INTERVAL)
    logger.info(f"Fetched {len(stock_data)} stocks")

    # ── 5. Analyze dan insert ke DB ───────────────────────────
    from core.scanner import analyze_stock
    from learning.signal_tracker import track_signal
    from learning.market_regime import get_market_regime

    regime_info = get_market_regime(force_refresh=True)
    logger.info(f"Market Regime: {regime_info.get('regime')} | ADX={regime_info.get('adx')}")

    tracked = 0
    for signal_type, tickers in alerted_today.items():
        for ticker in tickers:
            if ticker not in stock_data:
                logger.warning(f"  {ticker}: data tidak ada, dilewati")
                continue
            try:
                result = analyze_stock(ticker, stock_data[ticker])
                if result is None:
                    continue
                # Set signal type explicitly (override auto-detect)
                result.signal_type = signal_type.upper()
                ok = track_signal(result, signal_type, regime_info)
                if ok:
                    tracked += 1
                    logger.info(f"  ✅ {ticker} ({signal_type}) @ {result.price:.0f} → DB")
                else:
                    logger.warning(f"  ⚠️ {ticker}: gagal insert")
            except Exception as e:
                logger.warning(f"  ❌ {ticker}: error — {e}")

    logger.info("=" * 60)
    logger.info(f"Backfill selesai: {tracked} sinyal berhasil diinsert ke DB")
    logger.info("Sinyal ini akan dievaluasi outcome-nya besok jam 16:30 WIB")
    logger.info("=" * 60)


def _run_fresh_scan() -> dict:
    """Scan semua saham dan return sinyal yang ditemukan"""
    from config.stocks_list import get_all_stocks
    from core.data_fetcher import fetch_multiple_stocks
    from core.scanner import scan_all_stocks
    from core.scanner import filter_signals
    from config.settings import DATA_PERIOD, DATA_INTERVAL

    stocks = get_all_stocks()
    logger.info(f"Scanning {len(stocks)} stocks...")
    stock_data = fetch_multiple_stocks(stocks, period=DATA_PERIOD, interval=DATA_INTERVAL)
    results = scan_all_stocks(stock_data)
    signals = filter_signals(results)
    return {k: [r.ticker for r in v] for k, v in signals.items()}


if __name__ == "__main__":
    main()
