# Panduan Deployment IHSG Scanner Bot

Platform: **Google Cloud Platform (GCP) — e2-micro VM**

---

## Setup Awal di GCP VM

### Step 1: Buat VM Instance
1. Buka [Google Cloud Console](https://console.cloud.google.com)
2. Compute Engine → VM Instances → **Create Instance**
3. Konfigurasi:
   - **Name:** `ihsg-scanner`
   - **Region:** `asia-southeast1` (Singapore)
   - **Machine type:** `e2-micro` (free tier eligible)
   - **OS:** Ubuntu 22.04 LTS
   - **Disk:** 20 GB standard persistent disk
4. Di bagian **Firewall**, centang *Allow HTTP/HTTPS* tidak perlu — bot ini tidak butuh port terbuka
5. Klik **Create**

### Step 2: Koneksi ke VM
```bash
# Via Google Cloud Shell atau terminal lokal (gcloud sudah terinstall):
gcloud compute ssh ihsg-scanner --zone=asia-southeast1-b

# Atau via SSH langsung jika sudah set SSH key:
ssh username@EXTERNAL_IP
```

### Step 3: Setup Environment
```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python dan tools
sudo apt install -y python3 python3-pip python3-venv git

# Clone repo
cd ~
git clone https://github.com/YOUR_USERNAME/ihsg-supertrend-scanner-v2.git ihsg-scanner
cd ihsg-scanner

# Buat virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Step 4: Set Environment Variables
```bash
# Edit file settings atau buat .env (sesuaikan dengan cara project ini membaca config)
nano config/settings.py
# Isi TELEGRAM_BOT_TOKEN dan TELEGRAM_CHAT_ID
```

### Step 5: Test Manual
```bash
source ~/ihsg-scanner/venv/bin/activate
cd ~/ihsg-scanner
python scheduler.py
# Ctrl+C untuk stop jika berhasil
```

---

## Setup Systemd Service

### Buat Service File
```bash
sudo nano /etc/systemd/system/ihsg-scanner.service
```

Paste isi berikut (sesuaikan username dan path):
```ini
[Unit]
Description=IHSG Supertrend Scanner Bot
After=network.target

[Service]
Type=simple
User=anugrahdwikiar
WorkingDirectory=/home/anugrahdwikiar/ihsg-scanner
ExecStart=/usr/bin/flock -n /home/anugrahdwikiar/ihsg-scanner/database/.scheduler.lock \
  /home/anugrahdwikiar/ihsg-scanner/venv/bin/python /home/anugrahdwikiar/ihsg-scanner/scheduler.py
Restart=on-failure
RestartSec=15
KillMode=control-group
TimeoutStopSec=30
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

> **Penting:** Jangan jalankan `nohup python scheduler.py` bersamaan dengan systemd — itu penyebab 2 proses & alert dobel.

### Aktifkan Service
```bash
sudo systemctl daemon-reload
sudo systemctl enable ihsg-scanner
sudo systemctl start ihsg-scanner
sudo systemctl status ihsg-scanner
```

---

## Update Bot (Git Pull + Restart)

Setiap kali ada perubahan kode yang sudah di-push ke GitHub, jalankan ini di VM:

```bash
# Masuk ke folder project
cd ~/ihsg-scanner

# Pull perubahan terbaru
git pull origin main

# Restart bot
sudo systemctl restart ihsg-scanner

# Cek status (pastikan active/running)
sudo systemctl status ihsg-scanner
```

Untuk lihat log real-time setelah restart:
```bash
journalctl -u ihsg-scanner -f
```

---

## Perintah Berguna

| Aksi | Command |
|------|---------|
| Cek status | `sudo systemctl status ihsg-scanner` |
| Lihat log real-time | `journalctl -u ihsg-scanner -f` |
| Lihat log N baris terakhir | `journalctl -u ihsg-scanner -n 100` |
| Restart | `sudo systemctl restart ihsg-scanner` |
| Stop | `sudo systemctl stop ihsg-scanner` |
| Start | `sudo systemctl start ihsg-scanner` |
| Cek proses berjalan | `ps aux \| grep scheduler \| grep -v grep` |

---

## Troubleshooting

### Bot tidak jalan setelah restart
```bash
# Cek apakah ada 2 proses (penyebab alert dobel)
ps aux | grep scheduler | grep -v grep
# Harus hanya 1 baris

# Jika ada 2 proses, kill semua dan start ulang bersih:
sudo systemctl stop ihsg-scanner
pkill -f "scheduler.py" || true
sleep 3
rm -f ~/ihsg-scanner/database/.scheduler.lock
rm -f ~/ihsg-scanner/database/.scheduler_py.lock
sudo systemctl start ihsg-scanner
sleep 2
ps aux | grep scheduler | grep -v grep
```

### Git pull konflik
```bash
cd ~/ihsg-scanner
git fetch origin
git reset --hard origin/main   # WARNING: buang perubahan lokal
sudo systemctl restart ihsg-scanner
```

### Cek apakah ada service/timer duplikat
```bash
systemctl list-units --all | grep -i ihsg
crontab -l
grep -r scheduler /etc/systemd/system/
```

---

## Checklist Sebelum Deploy Pertama

- [ ] `config/settings.py` sudah diisi `TELEGRAM_BOT_TOKEN` dan `TELEGRAM_CHAT_ID`
- [ ] Test manual (`python scheduler.py`) tidak error
- [ ] Systemd service sudah `enabled` (auto-start saat VM reboot)
- [ ] `.gitignore` sudah mengecualikan file yang berisi token/secret
