# Research Notes: Daily Chart-Pattern Review

## Problem and evidence

Tujuan fitur adalah mereviu empat pola bullish pada 240 saham IDX terlikuid setiap
hari kerja setelah candle Daily tersedia, tanpa menghabiskan sekitar 240 request
history pada setiap run.

Fakta yang menjadi dasar desain:

- Invezgo menyediakan Daily OHLCV, formula screener, dan fungsi `sma`; screener
  memiliki limit khusus tiga request per 15 menit. Sumber: [endpoint API](https://docs.invezgo.com/api-usage/endpoint/),
  [formula variables](https://docs.invezgo.com/features/formula-variables/), dan
  [rate limit](https://docs.invezgo.com/api-usage/rate-limit/).
- Hanya response sukses 2xx yang memakai kuota. Paket Advance tercatat 30.000
  request per periode dan Prime 65.000. Sumber: [Invezgo API quota](https://docs.invezgo.com/api-usage/quota/).
- Chart pattern dibatasi trendline dan baru lengkap setelah breakout. Symmetrical
  triangle memerlukan garis atas turun dan garis bawah naik dengan setidaknya dua
  sentuhan per garis. Wedge memerlukan garis searah dan lima sentuhan total (3+2).
  Pennant memerlukan gerak tajam/pole sebelum konsolidasi singkat. Sumber:
  [Fidelity, Identifying Chart Patterns](https://www.fidelity.com/bin-public/060_www_fidelity_com/documents/learning-center/Idenitfying-Chart-Patterns.pdf).
- Volume dipakai sebagai konfirmasi price move. Sumber:
  [Fidelity, Technical Analysis](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/what-is-technical-analysis).
- Pattern recognition tetap heuristik dan bukan jaminan return; otomasi mengurangi
  subjektivitas tetapi memerlukan validasi historis/forward. Sumber: Lo, Mamaysky,
  dan Wang, [Foundations of Technical Analysis](https://doi.org/10.1111/0022-1082.00265).

Observasi API pada 13 September 2026 menunjukkan OHLCV screener INTP sama dengan
bar terakhir endpoint chart untuk 11 September 2026. Ini mendukung penggunaan satu
response screener untuk memperbarui cache semua ticker. Observasi tersebut adalah
spot-check, bukan bukti parity untuk semua ticker dan corporate action.

## Keputusan formula

Common quality gate:

- minimum 60 bar valid dan tanpa discontinuity return absolut di atas 60%;
- candle terakhir harus melakukan fresh close breakout, bukan sekadar berada di
  atas resistance;
- volume breakout minimal rata-rata 20 hari;
- OBV di atas EMA20 OBV;
- RSI14 ditampilkan sebagai informasi, bukan filter;
- rata-rata `close × volume` lima hari minimal Rp5 miliar.

Struktur pola:

- `break_base`: range 22 bar maksimum 18%, minimum dua pivot touch pada resistance
  dan dua pada support, lalu close breakout.
- `sym_triangle_break`: 34 bar pre-breakout, minimum 2 pivot high dan 2 pivot low,
  upper slope negatif, lower slope positif, R² minimum 0,30, width menyempit
  minimal 20%, lalu close breakout garis atas.
- `falling_wedge_break`: minimum 3 pivot high dan 2 pivot low, kedua slope negatif,
  upper slope turun lebih cepat, convergence dan close breakout garis atas.
- `bullish_pennant`: pole 20 bar minimum 5,5%, berakhir dekat high; konsolidasi 12
  bar membentuk triangle konvergen dan range maksimum 10%, lalu close breakout.

Threshold adalah parameter heuristik awal, bukan hasil optimasi atau bukti edge.
Backtest dengan data bebas survivorship bias dan forward validation masih wajib.

## Estimasi kuota

- Bootstrap pertama: 1 index + 1 screener + sampai 240 stock chart = 242 request.
- Hari normal: 1 index + 1 screener = 2 request.
- Saham baru atau cache gap: tambahan satu request per ticker yang perlu diperbaiki.

Dengan 22 hari bursa, baseline setelah bootstrap sekitar 284 request dalam 30 hari,
ditambah churn/repair. Target operasional 300–600 request per 30 hari jauh di bawah
5.000, selama cache persisten tidak dihapus setiap deployment.

