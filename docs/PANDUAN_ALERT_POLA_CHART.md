# Buku panduan — Alert pola chart (TF harian)

Dokumen ini menjelaskan **alert pola chart** pada *IHSG Supertrend Scanner*: fungsi, asumsi teknis, dan **apa yang masuk akal disimpulkan** ketika sebuah saham muncul di alert — serta **biasanya apa yang diharapkan ke depannya** (secara probabilistik, bukan jaminan).

---

## 1. Ini alert apa — dan apa bukan?

- **Alert pola chart** adalah **penyaring otomatis** berbasis data **OHLC harian** (via Yahoo Finance / `yfinance`). Sistem menghitung **patokan kuantitatif** yang *mendasari* beberapa pola klasik breakout / reject support / struktur bullish ringan di chart.
- Ini **bukan** penggambar trendline manual seperti di TradingView oleh analis, dan **bukan** sinyal “wajib entry”.
- Ini **berbeda jalur** dari alert utama scanner (mis. Strong Buy, Accumulation, Early Entry, Bullish Divergence). **Telegram pola chart** dikirim **terpisah**, pada slot **08:00 WIB** (scheduler), **maksimal sekali per hari**, memakai **candle harian yang sudah close** (“kemarin”).

---

## 2. Kapan sistem mengecek?

- Mode produksi umumnya: **`scheduler.py`** memicu scan pola pada **jam 08:00** dalam **jendela eksekusi singkat** (lebih dari itu dianggap lewat dan **tidak di-catch-up** sampai hari berikutnya).

- **Uji + kirim hasil langsung ke Telegram** (universe penuh; pesan bertanda 🧪, tidak menyentuh dedup / “sudah scan hari ini”):
  ```bash
  python main.py morning-patterns --telegram-test
  ```
  Alias flag: `--test`.

- **Uji cepat tanpa Telegram** (konsol saja):
  ```bash
  CHART_TEST_LIMIT=200 python scripts/test_chart_pattern_alerts.py
  ```
  Lingkungan penuh:
  ```bash
  CHART_TEST_ALL=1 python scripts/test_chart_pattern_alerts.py
  ```

---

## 3. Jenis pola yang dilaporkan (ringkas)

Semua bernada **bullish idea** dalam kerangka *screening*. Nama di Telegram mengikuti label berikut:

| ID (internal) | Label |
|---------------|--------|
| `break_base` | Break the Base |
| `sym_triangle_break` | Symmetrical Triangle Breakout |
| `falling_wedge_break` | Falling Wedge Breakout |
| `bullish_pennant` | Bullish Pennant |
| `reject_dynamic_support` | Reject Dynamic Support (dekat/zona sentuh EMA50) |
| `reject_harmonic_support` | Reject Harmonic Support (zona fib kasar dari range terbaru) |
| `false_break_support` | False Break Support (bear trap ringan) |

Satu emiten bisa muncul **lebih dari satu baris** jika beberapa pola cocok bersamaan.

---

## 4. Filter kualitas (setelah pola terpicu)

Agar alert tidak “banjir”, hanya kombinasi **pola + filter** ini yang sampai ke Telegram:

1. **RSI(14) &lt; 70** — menghindari kondisi overbought yang sering menyusul koreksi jangka pendek.  
   (Ambang: `CHART_ALERT_MAX_RSI` di `config/settings.py`.)

2. **Volume vs MA20 volume** pada candle sinyal:  
   - **Close naik** vs hari sebelumnya → volume **minimal sebanding aktivitas normal**: **≥ 1× MA20**.  
   - **Close turun atau doji** → volume **tidak membengkak** di atas aktivitas normal: **≤ 1× MA20** (penurunan yang tidak didominasi jual besar).

3. **OBV akumulasi** — **OBV &gt; EMA20 OBV** (indikator arah modal yang sama seperti modul utama).

**Tesis filtering:** pola saja bisa muncul di saat ekstensi harga atau distribusi tidak sehat; RSI + volume + OBV bertujuan memilih situasi dengan **stretch belum berlebihan** dan **preferensi modal yang tidak negatif**.

---

## 5. Thesis inti — kalau ada saham masuk alert, apa yang bisa disimpulkan?

Gunakan formulasi seperti ini secara mental:

> **Ada indikasi kuantitatif** bahwa, pada timeframe **harian**, harga baru-baru ini menyerupai struktur bullish (break/konfirmasi support/false break dll.) **dan** beberapa filter **risk/reward pendek** (RSI tidak terlalu tinggi, volume bermakna atau tidak rusuh saat turun, OBV bullish).

Ini **tidak sama** dengan:

> “Saham pasti lanjut naik besar” atau “wajib dibeli besok pembukaan”.

Yang tepat lebih mirip:

> **Ini nama masuk radar kualitas idea** untuk **review manual** atau **aksi lanjutan** menurut rencana trading kamu sendiri.

---

## 6. Informasi apa yang kamu dapat?

Dari satu baris alert (telegram / log) biasanya tersedia setidaknya:

- **Ticker**  
- **Jenis pola** (label bahasa Inggris)  
- **Harga referensi** (close candle terakhir yang dipakai)  
- **Perubahan harian ±%** dan **volume vs rata-rata** (dibantu filter)

Yang **tidak** otomatis diberikan oleh modul pola chart ini secara penuh: target TP/SL lengkap seperti alert supertrend (kecuali nanti kamu menghubungkannya secara terpisah). **Disiplin manajemen risiko tetap kamu.**

---

## 7. Setelah masuk alert — narasi probabilistik ke depannya

Tidak ada rumus satu-satunya. Kerangka **non-jaminan** yang sering dipakai trader penyaring pola:

**Skenario umum positif** (continuation / pullback dangkal kemudian lanjut):  
Breakout tertahan, volume akumulasi terbaca OBV bullish, RSI belum overstretched → **bias** ke arah “**masih ada ruang bagi lanjutan**” **jika** tidak ada reversal struktur besar (kalah support utama, dll.).

**Risiko utamanya**  
- Breakout gagal (**false breakout**).  
- **Data delay / error Yahoo** mempengaruhi candle.  
- **Satu timeframe harian saja**: noise intraday bisa berbeda.  
- Saham bisa ** sideways** atau koreksi walaupun pola awalnya terlihat bagus.

**Praktik yang masuk akal setelah alert**  
1. Buka chart sendiri konfirmasi *level* penting (support resistance, struktur mingguan).  
2. Tentukan **invalidasi ide** (di bawah area mana struktur bullish dianggap gagal).  
3. Paralelkan dengan **konteks indeks / sektor** jika relevan.  
4. **Position size** dan **cut loss** mengikuti aturan pribadi, bukan default bot.

---

## 8. Batasan teknis (wajib dibaca)

- **Sumber data:** `yfinance` — kadang batch gagal; hasil scan adalah subset yang berhasil diunduh.  
- **Heuristik:** ambang (lookback, korelasi, buffer breakout, dll.) ada di `config/settings.py` (`CHART_*`). Mengubah angka = mengubah sensitivitas *false positive* vs *missed opportunity*.  
- **Bukan nasihat investasi:** dokumen dan bot ini alat bantu; keputusan dan risiko di tangan pengguna.

---

## 9. Rujukan kode cepat

| Topik | Lokasi utama |
|--------|----------------|
| Definisi pola | `core/chart_patterns.py` (`detect_bullish_chart_patterns`) |
| Filter RSI / volume / OBV | `core/chart_patterns.py` (`passes_chart_alert_quality_filters`) |
| Alur kirim pagi | `main.py` (`run_morning_chart_pattern_scan`), `scheduler.py` |
| Threshold | `config/settings.py` (`CHART_*`, `CHART_ALERT_MAX_RSI`) |
| Format Telegram | `notifications/telegram_bot.py` |
| Uji konsol | `scripts/test_chart_pattern_alerts.py` |

---

## 10. Rekap satu kalimat

**Alert pola chart** = radar harian untuk **nama-nama dengan struktur breakout/reject bullish yang lolos RSI–volume–OBV**; gunakan sebagai **prioritas pantau**, lalu konfirmasi manusia dan kelola risiko — **bukan autopilot profit**.
