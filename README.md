# aerologic

aerologic adalah scanner saham Indonesia berbasis data Daily untuk riset kuantitatif dan market intelligence. Bot menyaring kandidat melalui Invezgo, mengevaluasi tiga keluarga sinyal, menerapkan pengaman alert, lalu mengirim hasilnya ke Telegram.

> Alert adalah keluaran riset, bukan rekomendasi investasi. Validasi strategi, kualitas data, likuiditas, slippage, dan manajemen risiko tetap diperlukan sebelum mengambil keputusan.

## Cara Kerja

Alur produksi saat ini:

1. Scheduler menjalankan scan setiap lima menit selama jendela operasional WIB.
2. Invezgo Screener memilih maksimal 50 kandidat berdasarkan aktivitas volume dan rata-rata nilai transaksi 20 hari.
3. Kandidat dibagi ke lane `momentum` (maksimal 18), `constructive` (6), dan `reversal` (6).
4. Bot mengambil OHLCV Daily dari Invezgo untuk setiap kandidat.
5. Scanner menghitung indikator, market regime, target, volume ratio, dan nilai transaksi harian.
6. Kandidat dengan rata-rata nilai transaksi lima hari di bawah Rp5 miliar tidak diteruskan menjadi alert.
7. ARB cooldown dan frequency gate menyaring sinyal yang tidak aman atau terlalu sering muncul.
8. Alert yang lolos diklaim secara atomik, dicatat ke event log, dikirim ke Telegram, dan disimpan untuk evaluasi outcome.

Harga dan persentase perubahan pada alert dapat dioverride dengan data screener yang lebih baru, sedangkan analisis teknikal tetap menggunakan candle Daily.

## Jenis Alert

### Strong Buy Daily

Keluarga sinyal `MOMENTUM_EXPANSION`. Kondisi utamanya:

- market regime `BULL` atau `SIDEWAYS`;
- `close > EMA20 > EMA50`;
- return 20 bar minimal 5%;
- volume ratio minimal 1,2x;
- candle ditutup dekat high, body cukup kuat, dan upper wick terbatas.

Ambang return dan volume dapat dioverride melalui environment variable.

### Early Entry Daily

Sinyal koreksi sehat pada struktur bullish. Bot mencari koreksi sekitar 3–12% dengan konfirmasi seperti low yang bertahan, range mengecil, volume meningkat, candle hijau, atau lower-wick rejection. Alert ini adalah sinyal dini dan bukan auto-entry.

### Reversal Watch Daily

Keluarga sinyal `SELLING_CLIMAX_REVERSAL`. Kondisi utamanya:

- return 20 bar maksimal -8%;
- RSI maksimal 35;
- volume ratio minimal 1,5x;
- candle bullish, close berada di bagian atas range, dan memiliki lower wick yang memadai.

Alert ini merupakan watchlist berisiko tinggi dan membutuhkan follow-through.

## Pengaman Alert

Pembatas berlaku per ticker dan lintas seluruh jenis alert:

- satu ticker hanya dapat dikirim sekali pada tanggal yang sama;
- maksimal tiga call dalam rolling window 14 hari kalender;
- maksimal dua sesi bursa berturut-turut—call pada sesi ketiga diblokir;
- `PACK`, `pack`, dan `PACK.JK` dianggap ticker yang sama;
- jika call sesi sebelumnya diikuti penurunan minimal 13%, ticker masuk ARB cooldown sampai muncul candle hijau.

Riwayat frequency gate disimpan di `database/daily_alerts.json` dan saat migrasi dibootstrap dari `database/signal_events.jsonl` serta `database/signal_tracker.json`. Perhitungan sesi berturut-turut melewati Sabtu dan Minggu, tetapi belum memakai kalender hari libur khusus BEI.

Klaim dilakukan sebelum pengiriman batch. Karena itu, kegagalan Telegram setelah klaim tetap dapat menghabiskan slot call sebagai tindakan konservatif untuk mencegah duplikasi.

## Contoh Alert Telegram

```text
🚀 STRONG BUY DAILY
--------------------------
28 Aug 2026, 14:01 WIB

PACK | 510 (+9.4%)
Score 85 | Vol 1.4x | Val 1,2B
Trend IHSG: SIDEWAYS
TP1: 541 (+6.1%)
TP2: 587 (+15.1%) ATR
Support: 480

Pastikan area Support (480) dijaga agar momentum masih bullish.

Total: 1 saham strong buy

Powered by Aerologic
```

`Val` adalah estimasi nilai transaksi hari berjalan dari `close × volume`, ditampilkan ringkas dalam `M`, `B`, atau `T`.

## Jadwal

Scheduler menggunakan zona waktu `Asia/Jakarta`:

| Hari | Sesi scan |
| --- | --- |
| Senin–Kamis | 09:01–12:00 dan 13:31–16:01 WIB |
| Jumat | 09:01–12:00 dan 14:01–16:01 WIB |
| Sabtu–Minggu | Tidak ada scan |

Interval scan adalah lima menit. Scheduler menolak proses duplikat pada sistem yang mendukung `pgrep`. Membuat file `database/PAUSE_SCHEDULER` sebelum startup akan mencegah scheduler berjalan.

## Persyaratan

- Python 3.11
- Invezgo API key
- Telegram bot token dan chat ID
- PostgreSQL opsional untuk learning dan evaluasi historis

## Instalasi Lokal

```powershell
py -3.11 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Isi minimal pada `.env`:

```dotenv
TELEGRAM_BOT_TOKEN=replace_me
TELEGRAM_CHAT_ID=replace_me
TELEGRAM_TEST_CHAT_ID=replace_me
INVEZGO_API_KEY=replace_me
```

Jika grup Telegram menggunakan Topics:

```dotenv
TELEGRAM_SCANNER_TOPIC_ID=replace_me
```

Secret tidak boleh ditulis langsung ke source code atau di-commit. `.env` sudah dikecualikan oleh `.gitignore`.

## Menjalankan Bot

Menjalankan scheduler produksi lokal:

```powershell
python scheduler.py
```

Menjalankan satu scan secara paksa:

```powershell
python main.py
```

`main.py` menggunakan `force=True`; perintah ini dapat melakukan request API dan mengirim alert jika sinyal lolos. Untuk detail operasi lokal lihat [CARA_RUN.md](CARA_RUN.md), dan untuk VPS/systemd lihat [DEPLOYMENT.md](DEPLOYMENT.md).

## Konfigurasi Utama

Nilai default berada di `config/settings.py`; parameter operasional tertentu dapat dioverride melalui `.env`.

| Environment variable | Default | Fungsi |
| --- | ---: | --- |
| `SCAN_ANALYZE_WORKERS` | `4` | Jumlah process worker analisis |
| `INVEZGO_FETCH_WORKERS` | `4` | Jumlah thread fetch chart |
| `INVEZGO_RATE_PER_SEC` | `3` | Batas laju request global |
| `INVEZGO_TIMEOUT` | `10` | Timeout request dalam detik |
| `INVEZGO_MAX_RETRIES` | `3` | Retry error jaringan |
| `INVEZGO_MONTHLY_QUOTA` | `65000` | Kuota bulanan yang dipantau |
| `INVEZGO_QUOTA_WARN_PCT` | `90` | Ambang peringatan kuota |
| `INVEZGO_QUOTA_BREAK_PCT` | `95` | Ambang penghentian fetch chart |
| `SCREEN_VOLUME_MIN_FACTOR` | `0.005` | Floor faktor volume screener |
| `CONTINUATION_MIN_RETURN20` | `5.0` | Minimum return Strong Buy |
| `CONTINUATION_MIN_VOLUME_RATIO` | `1.2` | Minimum volume ratio Strong Buy |
| `REVERSAL_MAX_RETURN20` | `-8.0` | Maximum return Reversal Watch |
| `REVERSAL_MAX_RSI` | `35` | Maximum RSI Reversal Watch |
| `REVERSAL_MIN_VOLUME_RATIO` | `1.5` | Minimum volume ratio Reversal Watch |

Sumber data yang didukung scanner produksi saat ini hanya Invezgo dengan candle `1d`.

## State, Learning, dan Observability

File runtime utama:

| Path | Fungsi |
| --- | --- |
| `database/stock_states.json` | State hasil scan terakhir |
| `database/daily_alerts.json` | Klaim harian dan riwayat frequency gate |
| `database/signal_events.jsonl` | Event lifecycle append-only |
| `database/signal_tracker.json` | Tracking TP/SL lokal dan snapshot alert |
| `database/arb_cooldown.json` | Ticker dalam cooldown pasca-ARB |
| `database/quota_usage.json` | Pemakaian kuota Invezgo bulanan |
| `logs/scanner.log` | Log scan dan alert gate |
| `logs/scheduler.log` | Log scheduler |

PostgreSQL bersifat opsional. Jika `DATABASE_URL` atau `DATABASE_PUBLIC_URL` tersedia, bot mencatat signal history untuk learning dan evaluasi tambahan. Kegagalan layer learning tidak menghentikan scanner utama.

Quota guard mengirim peringatan pada 90% dan menghentikan fetch chart pada 95% kuota. Screener tetap dapat berjalan ketika circuit breaker chart aktif.

## Struktur Proyek

```text
aerologic/
├── config/          # Settings dan universe pendukung
├── core/            # Data provider, screener, indikator, signal engine, scanner
├── database/        # State manager dan file runtime lokal
├── learning/        # Event lifecycle, PostgreSQL tracker, outcome learning
├── notifications/   # Formatter dan pengiriman Telegram
├── deploy/          # Template deployment systemd
├── docs/            # Dokumen riset, desain, dan validasi
├── scripts/         # Utility operasional
├── tests/           # Automated tests
├── main.py          # Orkestrasi satu scan
└── scheduler.py     # Scheduler produksi
```

## Validasi

Jalankan seluruh test:

```powershell
python -m pytest -q
```

Pemeriksaan ringan sebelum deployment:

```powershell
python -m compileall -q -f main.py scheduler.py config core database learning notifications scripts
python -c "import main, scheduler; print('runtime imports: OK')"
```

## Troubleshooting

### `INVEZGO_API_KEY tidak diset`

Pastikan `INVEZGO_API_KEY` tersedia di `.env` atau environment service.

### Telegram tidak mengirim pesan

Periksa `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, topic ID, koneksi jaringan, dan log `logs/scanner.log`. Tanpa konfigurasi Telegram, fungsi pengiriman hanya mencatat warning dan menganggap operasi berhasil untuk mode lokal.

### Tidak ada alert

Periksa secara berurutan:

1. kandidat lolos screener;
2. fetch OHLC berhasil;
3. rata-rata nilai transaksi lima hari minimal Rp5 miliar;
4. kondisi salah satu keluarga sinyal terpenuhi;
5. ticker tidak terkena ARB cooldown;
6. ticker belum mencapai frequency gate;
7. ticker belum diklaim pada hari yang sama.

Cari log `[AlertGate]`, `[ARB]`, `Signal diagnostics`, error Invezgo, atau status quota circuit breaker.

### Scheduler tidak berjalan

Pastikan tidak ada `database/PAUSE_SCHEDULER`, tidak ada scheduler lain yang aktif, dan waktu sistem menggunakan zona `Asia/Jakarta`.

## Lisensi

Belum ada file lisensi eksplisit di repository ini. Jangan mengasumsikan kode dapat digunakan atau didistribusikan sebagai MIT sampai lisensi proyek ditetapkan.
