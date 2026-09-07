# Cara Menjalankan Bot Lokal

Bot berjalan di PC ini. Pastikan PC menyala dan tidak sleep selama jam bursa.

## Menjalankan Bot H1

```powershell
py scheduler.py
```

Jadwal scan:

| Waktu | Aksi |
| --- | --- |
| Senin-Kamis 09:01-12:01 | Scan setiap 5 menit; forming H1 eligible |
| Senin-Kamis 12:01-13:30 | Istirahat |
| Senin-Kamis 13:31-16:16 | Scan setiap 5 menit; forming H1 eligible |
| Jumat 09:01-11:31 | Scan setiap 5 menit; forming H1 eligible |
| Jumat 12:01-14:00 | Istirahat |
| Jumat 14:01-16:16 | Scan setiap 5 menit; forming H1 eligible |

Alert dikirim ke topic Telegram yang diset di `.env`.

## Test Satu Kali Scan

```powershell
py main.py
```

## Konfigurasi Telegram

```env
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
TELEGRAM_TEST_CHAT_ID=
TELEGRAM_SCANNER_TOPIC_ID=699
```

Untuk mencari `message_thread_id`, kirim satu pesan di topic tujuan lalu jalankan:

```powershell
py scripts/find_topic_ids.py
```

## Catatan

- Bot memakai scanner H1 intrabar; forming candle dapat memicu alert sebelum close.
- Log scanner ada di `logs/scanner.log`; log scheduler ada di `logs/scheduler.log`.
- Kuota Invezgo dipantau oleh `core/quota_guard.py`.
