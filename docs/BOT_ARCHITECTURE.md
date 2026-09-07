# Dokumentasi Arsitektur Bot Aerologic

Dokumen ini menjelaskan arsitektur teknis dan alur eksekusi dari Telegram Bot yang digunakan dalam sistem **aerologic**. Bot ini merupakan sistem notifikasi *push-only* (satu arah) yang bertugas mengirimkan *alert* hasil *screening* dan *scanning* pasar saham secara berkala ke grup Telegram. 

## 1. Gambaran Umum (Overview)

Tidak seperti Telegram bot konvensional yang berjalan menggunakan mekanisme *long-polling* atau *webhook* untuk merespons pesan *user*, bot aerologic bersifat pasif. Bot dipicu (*triggered*) secara internal oleh modul `scheduler` untuk menjalankan *pipeline scan* dan mengirimkan sinyal temuan (seperti *Strong Buy*, *Early Entry*, dan *Reversal Watch*) ke spesifik *thread/topic* di grup Telegram.

## 2. Arsitektur Komponen Utama

Sistem bot ini terdiri dari 4 komponen utama:

1. **Scheduler (`scheduler.py`)**
   Merupakan *entry point* yang menjaga agar proses berjalan terus-menerus di *background*.
   - **Tugas**: Menjadwalkan scan satu menit setelah setiap bucket H1 Invezgo ditutup dan melakukan `smart_sleep_until` untuk menghemat resource.
   - **Concurrency Control**: Menjalankan fungsi `ensure_single_scheduler_process()` dengan mendeteksi *Process ID* (PID) menggunakan *command* `pgrep` di OS, guna memastikan tidak ada duplikasi *scheduler* yang berjalan secara bersamaan.
   
2. **Main Runner (`main.py`)**
   Komponen utama penggerak *pipeline* analisis (fungsi `run_scan()`).
   - **Tugas**: Menghubungkan modul *screener*, *data fetcher* (Invezgo), *scanner*, *state manager*, dan modul *notifications*.
   - Menginisialisasi koneksi *database* (opsional, untuk modul `learning`).

3. **State Manager (`database/state_manager.py`)**
   Modul pengelola *state* yang bertugas memastikan bot tidak melakukan *spam* pesan.
   - **Tugas**: Melacak status saham yang sudah dikirimkan notifikasinya hari ini (`daily_alerts`).
   - Memastikan saham yang sama tidak dikirimkan dua kali dalam sehari jika kondisinya tidak berubah (mekanisme `try_claim_daily_alert`).

4. **Telegram Bot Notifier (`notifications/telegram_bot.py`)**
   Komponen yang memformat hasil analisis menjadi pesan teks dan mengirimkannya ke API Telegram.

## 3. Alur Kerja Eksekusi (Execution Flow)

Proses eksekusi bot berjalan secara kronologis sebagai berikut:

1. **Inisialisasi**: Proses *worker* dijalankan (sesuai definisi di `Procfile`: `python scheduler.py`). Pesan *startup* dikirim ke topik *default* via `send_startup_message()`.
2. **Waiting / Sleep**: `scheduler.py` mencari jadwal terdekat (interval 5 menit di jam bursa). Jika belum waktunya, proses melakukan `sleep`.
3. **Triggering Scan**: Setelah waktu target tercapai, `scheduler.py` mengeksekusi `run_scan(force=True)` dari `main.py`.
4. **Data Pipeline**:
   - `get_candidates()`: Menjalankan *screener* awal.
   - **Filtering**: *State Manager* membuang *ticker* yang sudah pernah dikirim *alert*-nya di hari yang sama.
   - `fetch_multiple_stocks()`: Menarik data OHLC terbaru secara asinkron/paralel.
   - `scan_all_stocks()`: Menjalankan algoritma pemeringkatan dan mendeteksi kondisi teknikal setiap saham.
5. **Signal Validation**:
   - Fungsi `filter_signals()` memisahkan hasil menjadi beberapa kategori: `strong_buy`, `early_entry`, dan `reversal_watch`.
   - Menggunakan `try_claim_h1_alert` pada *State Manager* untuk memastikan hanya sinyal closed-H1 yang *fresh* dieksekusi untuk dikirim; daily risk cap lama tetap dipertahankan.
6. **Dispatch & Notification**:
   - Jika terdapat sinyal baru, fungsi `send_all_alerts(new_signals)` di modul Telegram akan dieksekusi.
   - Hasil dikelompokkan ke dalam format *message* yang sesuai dengan kriteria (judul tebal, emoji penanda) lalu di-POST ke Telegram API menggunakan `TELEGRAM_SCANNER_TOPIC_ID`.
   - *State* terbaru disimpan kembali oleh *State Manager* ke dalam penyimpanan lokal agar tersinkronisasi.

## 4. Detail Modul Telegram Bot

Modul `notifications/telegram_bot.py` memiliki mekanisme internal yang adaptif untuk memastikan pengiriman berjalan dengan stabil dan mematuhi batasan limit yang diterapkan oleh Telegram:

- **Request Method**: Menggunakan modul Python `requests` dengan metode standard HTTP POST via URI API Telegram: `https://api.telegram.org/bot<TOKEN>/sendMessage`.
- **Formatting Template**: Masing-masing jenis sinyal (Strong Buy, Early Entry, dll.) diproses menggunakan fungsi *formatter* (seperti `format_strong_buy_message`). Template dirancang untuk mendukung opsi `HTML` `parse_mode` untuk efek teks tebal (`<b>`) dan miring (`<i>`).
- **Chunking (Pemecahan Pesan)**: Terdapat batasan maksimum karakter per pesan pada Telegram API (`TELEGRAM_MAX_CHARS = 3800`). Bila *list result* sangat banyak (hingga ribuan kata), fungsi `_chunked_alert_messages` bertugas memecah array hasil menjadi beberapa buah pesan berseri (*Part* 1, *Part* 2, dst.) yang dikirim secara sekuensial.
- **Deduplication**: Fungsi helper `_dedupe_results_by_ticker` diselipkan untuk memastikan tidak ada emiten/ticker yang kebetulan masuk ke dalam array yang sama dan merusak validitas *alert*.
- **Thread Targeting**: Untuk grup yang diset menjadi *Supergroup* yang diaktifkan mode topiknya, setiap API *call* akan menyertakan parameter payload opsional `message_thread_id`. 

## 5. Konfigurasi 

Bot ini mengandalkan beberapa variabel terpusat dari modul `config/settings.py` (yang nilainya ditarik dari berkas `.env` atau variabel sistem operasi):
- `TELEGRAM_BOT_TOKEN`: *Access token* unik dari BotFather.
- `TELEGRAM_CHAT_ID`: Supergroup tujuan alert scanner.
- `TELEGRAM_SCANNER_TOPIC_ID`: ID topik tunggal untuk seluruh alert scanner.
- `TELEGRAM_TEST_CHAT_ID`: Grup terpisah untuk pengujian serta notifikasi startup/restart tanpa topic.

## Kesimpulan

Bot Aerologic dirancang dengan pendekatan *scheduler-driven* yang sangat spesifik dan efisien (berjalan sesuai *event-loop* per 5 menit pada jam aktif). Arsitekturnya difokuskan penuh untuk analisis independen secara lokal dan disalurkan secara *push notification*. Arsitektur yang pasif dalam artian tidak menampung masukan (no webhook/polling incoming messages) membuat bot ini sangat aman dari eksekusi peretasan dari perintah chat eksternal, disamping meminimalisir sumber daya (resources). Komponen `StateManager` bertindak sebagai pembatas *(rate limiter/throttler)* alami untuk membatasi frekuensi duplikasi dan melanggar aturan internal batasan API Telegram.
