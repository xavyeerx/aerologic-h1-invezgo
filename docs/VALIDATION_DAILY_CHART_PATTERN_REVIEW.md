# Validation Report: Daily Chart-Pattern Review

## Verified by automated tests

- top-liquid ranking memakai `sma("value",5)` dan limit universe;
- recurring run dengan cache kontinu tidak memanggil stock-chart endpoint;
- base memerlukan repeated pivot touches dan fresh breakout;
- symmetrical triangle memiliki opposing converging pivot lines;
- falling wedge memiliki minimal tiga pivot high dan dua pivot low;
- bullish pennant memiliki pole, convergence, dan breakout;
- volume/OBV adalah hard gate sedangkan RSI bukan gate;
- review kosong tetap menghasilkan pesan;
- scheduler memilih event 16:30 setelah scan H1 terakhir.

Automated suite pada 13 September 2026: 90 test dan 10 subtest lulus.

## Live smoke test

Smoke test end-to-end terhadap Invezgo memakai tanggal pasar 11 September 2026 dan
limit lima ticker berhasil: universe 5, analyzed 5, bootstrap 5, satu bagian pesan,
tanpa pengiriman Telegram. Ini memvalidasi kontrak response aktual dan alur cache,
tetapi bukan validasi penuh terhadap 240 ticker.

## Validation still required

- jalankan bootstrap produksi dan pastikan 240 ticker terisi tanpa 429;
- bandingkan sampel positif/negatif dengan anotasi chart manual independen;
- backtest precision, forward return, false-positive rate, dan stability terhadap
  perubahan threshold;
- audit split/dividend adjustment dan survivorship bias;
- integrasikan kalender libur resmi IDX; saat ini freshness sentinel mencegah sinyal
  dari candle H-1 tetapi tetap melakukan satu request index pada weekday holiday.

Fitur telah tervalidasi secara mekanis, tetapi profitability/edge belum terbukti.
