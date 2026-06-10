# Panduan Deploy Lengkap — Bot v2 dari Awal (GCP + Telegram Channel)

Panduan ini menjelaskan **seluruh alur** deploy bot **bot-teknikal-v2** ke VM Google Cloud, mulai dari pull GitHub, setup folder baru, memakai **channel Telegram yang sama dengan bot v1** (`ihsg-scanner`), sampai bot jalan 24/7.

---

## Ringkasan

| Item | Nilai |
|------|--------|
| Repo GitHub | https://github.com/xavyeerx/bot-teknikal-v2 |
| VM | `algotrade-bot-server` |
| Zone | `asia-southeast2-a` (Jakarta) |
| User Linux | `anugrahdwikiar` |
| Folder bot v1 (lama) | `/home/anugrahdwikiar/ihsg-scanner` |
| Folder bot v2 (baru) | `/home/anugrahdwikiar/bot-teknikal-v2` |
| Service v1 (matikan) | `ihsg-bot.service` |
| Service v2 (aktif) | `ihsg-scanner-v2.service` |
| File secret | `/home/anugrahdwikiar/.ihsg-scanner.env` |

> **Aturan emas:** Hanya **satu** `scheduler.py` yang boleh jalan. Bot v1 dan v2 bersamaan = alert dobel ke channel.

---

## Diagram alur deploy

```
[Laptop] git push  →  [GitHub bot-teknikal-v2]
                              ↓ git clone / pull
[VM algotrade-bot-server]  ~/bot-teknikal-v2
                              ↓
                    ~/.ihsg-scanner.env  (token + channel ID sama v1)
                              ↓
                    ihsg-scanner-v2.service (systemd)
                              ↓
                    [Channel Telegram]  ← sama seperti bot v1
```

---

## Bagian A — Stop bot v1 (wajib pertama)

SSH ke VM:

```bash
gcloud compute ssh algotrade-bot-server --zone=asia-southeast2-a
```

Atau: Google Cloud Console → VM instances → `algotrade-bot-server` → **SSH**

```bash
# Stop service lama
sudo systemctl stop ihsg-bot
sudo systemctl disable ihsg-bot

# Kill proses sisa (kalau masih ada)
pkill -f "/home/anugrahdwikiar/ihsg-scanner/scheduler.py" || true
sleep 2

# Harus kosong — tidak boleh ada scheduler jalan
ps aux | grep scheduler | grep -v grep
```

---

## Bagian B — Ambil config Telegram dari bot v1 (channel yang sama)

Bot v2 memakai variabel yang sama:

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

`TELEGRAM_CHAT_ID` untuk **channel** biasanya format **`-100xxxxxxxxxx`**, bukan ID pribadi.

### B.1 Cari config lama di VM

Jalankan satu per satu sampai ketemu:

```bash
# Opsi 1: env file umum
cat ~/.ihsg-scanner.env 2>/dev/null

# Opsi 2: env di folder v1
cat ~/ihsg-scanner/.env 2>/dev/null

# Opsi 3: dari systemd service lama
sudo systemctl cat ihsg-bot 2>/dev/null | grep -i environment

# Opsi 4: grep di folder lama
grep -r "TELEGRAM" ~/ihsg-scanner/ 2>/dev/null | grep -v ".pyc" | head -20
```

**Salin** nilai `TELEGRAM_BOT_TOKEN` dan `TELEGRAM_CHAT_ID` yang dipakai v1.

### B.2 Kalau tidak ketemu file env — cek channel manual

1. Buka channel Telegram tempat alert v1 biasanya masuk
2. Pastikan **bot yang sama** (atau bot baru) sudah jadi **Admin** channel dengan izin **Post Messages**
3. Ambil Chat ID channel:
   - Forward satu pesan dari channel ke **@RawDataBot** atau **@getidsbot**
   - Atau kirim pesan di channel, lalu di VM:

```bash
# Ganti TOKEN dengan bot token v1
curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates" | python3 -m json.tool | tail -50
```

Cari `"chat":{"id":-100...` — itu `TELEGRAM_CHAT_ID` channel.

### B.3 Bot baru + channel lama (setup production saat ini)

| Variabel | Sumber |
|----------|--------|
| `TELEGRAM_BOT_TOKEN` | **Bot baru** dari @BotFather |
| `TELEGRAM_CHAT_ID` | **Channel sama v1** — salin dari `~/ihsg-scanner/.env` (`-1003752913925`) |

**Wajib:** Tambahkan **bot baru** sebagai **Admin** di channel (izin **Post Messages**), kalau tidak alert gagal kirim.

| Situasi | Yang dilakukan |
|---------|----------------|
| Bot baru + channel lama | Token baru + `TELEGRAM_CHAT_ID=-100...` dari v1 |
| Bot lama (v1) | Token & channel sama persis dari `ihsg-scanner/.env` |

---

## Bagian C — Pull / clone repo dari GitHub

Masih di VM:

```bash
cd ~

# Kalau folder belum ada — clone
git clone https://github.com/xavyeerx/bot-teknikal-v2.git bot-teknikal-v2

# Kalau folder sudah ada — update
cd ~/bot-teknikal-v2
git pull origin main
```

Verifikasi versi kode:

```bash
grep SCANNER_BUILD_ID ~/bot-teknikal-v2/config/settings.py
# Contoh: SCANNER_BUILD_ID = "20260609-engulf-vol1x"
```

---

## Bagian D — Setup Python & dependency

```bash
cd ~/bot-teknikal-v2

# Install utilitas (sekali saja, kalau belum)
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git

# Virtual environment
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Folder runtime
mkdir -p logs database
```

Cek Python venv ada:

```bash
ls -la ~/bot-teknikal-v2/venv/bin/python
```

Harus ada file executable.

### Timezone VM (WIB)

Scheduler memakai `pytz` (`Asia/Jakarta`), jadi **jam trading tetap benar** meski timezone OS VM UTC. Tetap disarankan set timezone VM ke WIB agar log `journalctl` mudah dibaca:

```bash
# Cek timezone saat ini
timedatectl

# Set ke WIB (sekali saja)
sudo timedatectl set-timezone Asia/Jakarta

# Verifikasi — Local time harus WIB (+07)
date
timedatectl | grep 'Time zone'
```

Contoh benar: `Time zone: Asia/Jakarta (WIB, +0700)` dan `date` menunjukkan jam lokal yang sama dengan jam Anda.

---

## Bagian E — Buat file env (channel sama dengan v1)

```bash
nano ~/.ihsg-scanner.env
```

Isi (bot **baru**, channel **sama v1**):

```env
TELEGRAM_BOT_TOKEN=TOKEN_BOT_BARU_DARI_BOTFATHER
TELEGRAM_CHAT_ID=-1003752913925
```

> `TELEGRAM_CHAT_ID` salin dari `~/ihsg-scanner/.env` (channel v1).
> Token pakai bot **baru** — jangan token bot v1 (`8421417558:...`).
> **Tanpa spasi** setelah `=`.

Cek config v1:
```bash
cat ~/ihsg-scanner/.env
```

Simpan: `Ctrl+O` → Enter → `Ctrl+X`

```bash
chmod 600 ~/.ihsg-scanner.env
```

---

## Bagian F — Test Telegram ke channel (sebelum systemd)

```bash
cd ~/bot-teknikal-v2
source venv/bin/activate
set -a && source ~/.ihsg-scanner.env && set +a
python test_telegram.py
```

**Berhasil** = pesan test muncul di **channel yang sama** tempat alert v1 dulu masuk.

Kalau gagal:

| Error | Solusi |
|-------|--------|
| `401 Unauthorized` | Token salah — cek `TELEGRAM_BOT_TOKEN` |
| `400 Bad Request: chat not found` | Chat ID salah atau bot belum admin channel |
| `403 Forbidden: bot is not a member` | Tambahkan bot sebagai **admin** channel |

---

## Bagian G — Test scheduler manual (opsional)

```bash
cd ~/bot-teknikal-v2
source venv/bin/activate
set -a && source ~/.ihsg-scanner.env && set +a
python scheduler.py
```

Harus muncul log scheduler + pesan **STARTED** di channel.  
Stop dengan `Ctrl+C`, lalu lanjut systemd.

---

## Bagian H — Deploy dengan systemd (24/7)

### H.1 Buat service file

```bash
sudo nano /etc/systemd/system/ihsg-scanner-v2.service
```

Paste:

```ini
[Unit]
Description=IHSG Scanner Bot v2 (bot-teknikal-v2)
After=network.target

[Service]
Type=simple
User=anugrahdwikiar
WorkingDirectory=/home/anugrahdwikiar/bot-teknikal-v2
EnvironmentFile=-/home/anugrahdwikiar/.ihsg-scanner.env
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/anugrahdwikiar/bot-teknikal-v2/venv/bin/python /home/anugrahdwikiar/bot-teknikal-v2/scheduler.py
Restart=on-failure
RestartSec=15
KillMode=control-group
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
```

> Versi ini **tanpa flock** agar lebih mudah jalan di VM. Cegah double bot dengan memastikan v1 sudah stop (Bagian A).

### H.2 Aktifkan

```bash
sudo systemctl daemon-reload
sudo systemctl enable ihsg-scanner-v2
sudo systemctl start ihsg-scanner-v2
sudo systemctl status ihsg-scanner-v2
```

Status harus: **`active (running)`**

### H.3 Verifikasi deploy

```bash
# Hanya 1 proses, path bot-teknikal-v2
ps aux | grep scheduler | grep -v grep

# Build ID terbaru
grep SCANNER_BUILD_ID ~/bot-teknikal-v2/config/settings.py

# Log
sudo journalctl -u ihsg-scanner-v2 -n 30 --no-pager
```

**Channel Telegram** harus menerima:

```
🤖 IHSG SCANNER v5.0 STARTED
🔖 Build: 20260609-engulf-vol1x
```

Jika build ID masih `chart-dedup` atau path `ihsg-scanner` → bot lama masih jalan, ulangi Bagian A.

---

## Bagian I — Update kode setelah ada perubahan di GitHub

Di laptop: `git push origin main`

Di VM:

```bash
cd ~/bot-teknikal-v2
sudo systemctl stop ihsg-scanner-v2
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl start ihsg-scanner-v2
sudo systemctl status ihsg-scanner-v2
```

---

## Bagian J — Perintah operasional

| Aksi | Command |
|------|---------|
| Status | `sudo systemctl status ihsg-scanner-v2` |
| Restart | `sudo systemctl restart ihsg-scanner-v2` |
| Stop | `sudo systemctl stop ihsg-scanner-v2` |
| Log live | `sudo journalctl -u ihsg-scanner-v2 -f` |
| Cek proses | `ps aux \| grep scheduler \| grep -v grep` |
| Cek service ihsg | `systemctl list-units --all \| grep -i ihsg` |

---

## Bagian K — Troubleshooting

### K.1 `Job failed because of unavailable resources`

```bash
sudo journalctl -xeu ihsg-scanner-v2 -n 20 --no-pager
ls -la ~/bot-teknikal-v2/venv/bin/python
ls -la ~/.ihsg-scanner.env
```

Perbaikan umum:
- Buat ulang venv: `cd ~/bot-teknikal-v2 && python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt`
- Buat env file: Bagian E
- `mkdir -p ~/bot-teknikal-v2/database ~/bot-teknikal-v2/logs`

### K.2 Alert dobel di channel

```bash
sudo systemctl stop ihsg-bot ihsg-scanner-v2 2>/dev/null
pkill -f "scheduler.py" || true
sleep 3
ps aux | grep scheduler | grep -v grep   # harus kosong
sudo systemctl start ihsg-scanner-v2
```

### K.3 Pesan STARTED tapi build lama

Bot v1 masih aktif. Ulangi Bagian A, pastikan hanya `bot-teknikal-v2` yang jalan.

### K.4 Service `ihsg-scanner-v2` not found

File service belum dibuat — ulangi Bagian H.1.

---

## Bagian L — Setup lokal (laptop, opsional)

Untuk development & push ke GitHub:

```bash
cd "d:\ALGO TRADE"
git clone https://github.com/xavyeerx/bot-teknikal-v2.git ihsg-supertrend-scanner-v2
cd ihsg-supertrend-scanner-v2
pip install -r requirements.txt
```

Buat `.env` lokal (bisa pakai chat ID pribadi untuk uji, channel untuk production):

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

```bash
python test_telegram.py
python main.py
```

Push ke GitHub:

```bash
git add .
git commit -m "Pesan commit"
git push origin main
```

Lalu update VM: Bagian I.

---

## Bagian M — Salin data alert VM → laptop (opsional)

```bash
# Dari Git Bash di Windows
scp anugrahdwikiar@algotrade-bot-server:~/bot-teknikal-v2/database/signal_tracker.json "d:/ALGO TRADE/ihsg-supertrend-scanner-v2/database/"
scp anugrahdwikiar@algotrade-bot-server:~/bot-teknikal-v2/database/daily_alerts.json "d:/ALGO TRADE/ihsg-supertrend-scanner-v2/database/"
```

```bash
cd "d:\ALGO TRADE\ihsg-supertrend-scanner-v2"
python scripts/replay_today_alerts.py --telegram
```

---

## Bagian N — Jadwal bot (WIB, Senin–Jumat)

| Waktu | Aktivitas |
|-------|-----------|
| 08:25 | Pre-wake |
| 08:30 | Opening recap |
| 08:30 – 16:00 | Scan back-to-back (tanpa jeda 60 detik) |
| 16:00 | Closing recap |
| 16:30 | Evaluasi TP/SL |
| 16:45 | Chart patterns (1×/hari) |

Luar jam trading = scheduler tidur (normal).

---

## Checklist deploy dari nol

### Persiapan
- [ ] VM `algotrade-bot-server` running
- [ ] SSH berhasil masuk
- [ ] Bot v1 (`ihsg-bot`) **stop + disable**
- [ ] `ps aux | grep scheduler` kosong

### Telegram (channel sama v1)
- [ ] `TELEGRAM_BOT_TOKEN` disalin dari config v1 (atau bot baru + admin channel)
- [ ] `TELEGRAM_CHAT_ID` channel (`-100...`) disalin dari config v1
- [ ] Bot adalah **admin** channel
- [ ] `python test_telegram.py` → pesan muncul di channel

### Deploy
- [ ] `git clone` / `git pull` → `~/bot-teknikal-v2`
- [ ] `venv` + `pip install -r requirements.txt`
- [ ] `~/.ihsg-scanner.env` dibuat (`chmod 600`)
- [ ] `ihsg-scanner-v2.service` dibuat
- [ ] `systemctl status` → **active (running)**
- [ ] Hanya **1** proses scheduler (`bot-teknikal-v2`)
- [ ] Channel dapat startup message build **`engulf-vol1x`** (atau terbaru di repo)

---

## Struktur folder di VM

```
/home/anugrahdwikiar/
├── .ihsg-scanner.env              ← token + channel ID (sama v1)
│
├── ihsg-scanner/                  ← BOT V1 (jangan dijalankan)
│   ├── .env                       ← mungkin config lama ada di sini
│   └── venv/
│
└── bot-teknikal-v2/               ← BOT V2 (aktif)
    ├── venv/
    ├── scheduler.py
    ├── config/settings.py
    ├── database/
    └── logs/
```

---

## Referensi gcloud

```bash
# SSH
gcloud compute ssh algotrade-bot-server --zone=asia-southeast2-a

# Stop VM (hemat biaya)
gcloud compute instances stop algotrade-bot-server --zone=asia-southeast2-a

# Start VM
gcloud compute instances start algotrade-bot-server --zone=asia-southeast2-a
```

---

*Dokumen ini: deploy bot-teknikal-v2 ke algotrade-bot-server, Telegram channel sama dengan ihsg-scanner v1.*
