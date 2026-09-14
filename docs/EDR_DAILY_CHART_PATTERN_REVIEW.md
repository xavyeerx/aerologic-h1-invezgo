# EDR: Daily Chart-Pattern Review

## Decision

Scheduler menjalankan review TF-D pukul 16:30 WIB pada Senin–Jumat, dengan catch-up
sampai 17:00 setelah restart. COMPOSITE menjadi freshness sentinel; review hari itu
tidak menganalisis saham bila indeks belum memiliki candle bertanggal hari yang sama.

Satu formula screener mengambil OHLCV dan `sma("value",5)` untuk seluruh saham aktif.
Hasil diurutkan menurun dan dibatasi 240 ticker. Response yang sama menjadi update
OHLCV hari ini untuk rolling cache lokal.

## Data flow

1. Fetch Daily COMPOSITE dan validasi latest market date.
2. Jalankan satu screener, urutkan universe berdasarkan average traded value 5 hari.
3. Baca `database/chart_pattern_daily_cache.json`.
4. Append OHLCV screener bila cache berakhir pada sesi pasar sebelumnya.
5. Fetch full history hanya untuk ticker baru, cache pendek, atau gap; maksimum 240
   repair per run dan tetap tunduk pada quota circuit breaker.
6. Jalankan empat detector dan quality gate deterministik.
7. Kirim digest ke chat/topic scanner. Error dikirim ke test chat tanpa topic.
8. Tandai `database/chart_pattern_review_state.json` hanya setelah semua bagian
   Telegram berhasil dikirim.

Tidak ada request news/disclosure maupun LLM pada chart-pattern review. Pesan panjang
dipecah di bawah batas Telegram dan review kosong tetap menghasilkan status eksplisit.

## Failure modes

- Index/screener gagal: digest tidak dikirim, error operasional dikirim.
- Telegram gagal: tanggal tidak ditandai completed; restart service dapat retry.
- Cache hilang: terjadi bootstrap ulang dan tambahan sampai 240 request.
- Bootstrap limit habis: ticker sisanya ditunda, bukan dianalisis memakai history
  parsial.
- Corporate action ekstrem: ticker dilewati oleh discontinuity guard; aksi yang lebih
  kecil tetap berisiko menghasilkan false pattern.

