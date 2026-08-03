# Cara Menjalankan Bot Lokal

Bot berjalan di PC ini. Pastikan PC menyala dan tidak sleep selama jam bursa.

## Menjalankan Bot Harian

```powershell
py scheduler.py
```

Jadwal scan:

| Waktu | Aksi |
| --- | --- |
| Senin-Kamis 09:01-12:00 | Scan screener tiap 5 menit |
| Senin-Kamis 12:01-13:30 | Istirahat |
| Senin-Kamis 13:31-16:01 | Scan screener tiap 5 menit |
| Jumat 09:01-12:00 | Scan screener tiap 5 menit |
| Jumat 12:01-14:00 | Istirahat |
| Jumat 14:01-16:01 | Scan screener tiap 5 menit |

Alert dikirim ke topic Telegram yang diset di `.env`.

## Test Satu Kali Scan

```powershell
py main.py
```

## Konfigurasi Telegram

```env
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
TELEGRAM_TOPIC_DEFAULT=98
TELEGRAM_TOPIC_STRONG_BUY=98
TELEGRAM_TOPIC_STARTUP=98
```

Untuk mencari `message_thread_id`, kirim satu pesan di topic tujuan lalu jalankan:

```powershell
py scripts/find_topic_ids.py
```

## Catatan

- Bot ini memakai scanner Daily; log scanner ada di `logs/scanner.log` dan log scheduler ada di `logs/scheduler.log`.
- Log scanner ada di `logs/scanner.log`; log scheduler ada di `logs/scheduler.log`.
- Kuota Invezgo dipantau oleh `core/quota_guard.py`.
