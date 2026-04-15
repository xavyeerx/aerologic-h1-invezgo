# Panduan Deployment IHSG Scanner Bot

---

## 🚀 DEPLOY KE RENDER (GRATIS)

Render adalah platform cloud modern yang mendukung **Background Worker** — cocok untuk bot ini karena tidak membutuhkan web server.

### Langkah 1: Pastikan Project Ada di GitHub

**Dari folder project, jalankan di terminal:**
```bash
cd "d:\ALGO TRADE\ihsg-supertrend-scanner"

# Jika belum di-init:
git init
git add .
git commit -m "Migrate to Render"

# Jika repo sudah ada, cukup push:
git add .
git commit -m "Add render.yaml for Render deployment"
git push origin main
```

> ⚠️ **PENTING:** Pastikan `.gitignore` sudah mengecualikan file yang berisi token/secret!

### Langkah 2: Buat Akun Render
1. Buka https://render.com
2. Klik **Get Started for Free**
3. Sign up menggunakan akun **GitHub** (lebih mudah)

### Langkah 3: Buat Background Worker Baru
1. Di Render dashboard, klik **+ New** → **Background Worker**
2. Pilih **Connect a repository** → pilih repo `ihsg-scanner`
3. Klik **Connect**

### Langkah 4: Konfigurasi Service
Isi form dengan pengaturan berikut:

| Field | Value |
|-------|-------|
| **Name** | `ihsg-supertrend-scanner` |
| **Region** | `Singapore (Southeast Asia)` |
| **Branch** | `main` |
| **Runtime** | `Python 3` |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `python scheduler.py` |
| **Instance Type** | `Free` |

> [!TIP]
> Render akan otomatis mendeteksi `render.yaml` yang sudah ada di repo — konfigurasi bisa langsung ter-import!

### Langkah 5: Set Environment Variables
Sebelum klik **Create Background Worker**, scroll ke bawah ke bagian **Environment Variables** dan tambahkan:

| Key | Value |
|-----|-------|
| `TELEGRAM_BOT_TOKEN` | Token bot Telegram Anda |
| `TELEGRAM_CHAT_ID` | Chat ID Telegram Anda |

Klik **Add Environment Variable** untuk setiap entri.

### Langkah 6: Deploy
1. Klik **Create Background Worker**
2. Render akan mulai build dan deploy otomatis
3. Waktu build pertama biasanya 2-5 menit

### Langkah 7: Cek Logs
1. Di dashboard Render, klik service `ihsg-supertrend-scanner`
2. Klik tab **Logs**
3. Harusnya ada output: `IHSG SUPERTREND SCANNER v5.0 - SCHEDULER`

---

### ✅ Selesai!
Bot akan berjalan otomatis 24/7 di Render. Cek Telegram untuk menerima alerts.

### ⚠️ Keterbatasan Free Tier Render
| Hal | Detail |
|-----|--------|
| **Sleep** | Free worker **TIDAK sleep** (berbeda dengan Web Service) ✅ |
| **RAM** | 512 MB — cukup untuk bot ini |
| **CPU** | Shared, terbatas untuk free tier |
| **Auto-deploy** | Otomatis setiap kali push ke GitHub |

### Troubleshooting
| Issue | Solusi |
|-------|--------|
| Build gagal | Cek tab **Logs** → bagian **Build** |
| Bot tidak jalan | Cek **Runtime Logs** di dashboard |
| Telegram error | Pastikan `TELEGRAM_BOT_TOKEN` dan `TELEGRAM_CHAT_ID` sudah di-set di Environment Variables |
| Crash loop | Render auto-restart, cek error di logs untuk penyebabnya |

---
---

| Platform | Harga | Kelebihan |
|----------|-------|-----------|
| **Render** | Free tier | Gratis, tidak sleep untuk worker, mudah setup |
| **DigitalOcean** | $6/bulan | Murah, stabil, tutorial lengkap |
| **Vultr** | $6/bulan | Banyak lokasi Asia |
| **Google Cloud** | Free tier 1 tahun | Gratis e2-micro |

> [!TIP]
> Rekomendasi: **Render Free Tier** untuk percobaan, **DigitalOcean $6/bulan** jika butuh lebih stabil

---

## Quick Deploy ke VPS (Ubuntu)

### Step 1: Buat VPS
1. Daftar di [DigitalOcean](https://digitalocean.com) atau [Vultr](https://vultr.com)
2. Buat Droplet/Instance:
   - OS: **Ubuntu 22.04 LTS**
   - Plan: **$6/bulan (1 vCPU, 1GB RAM)**
   - Region: **Singapore** (terdekat ke IHSG)
3. Catat IP address dan password/SSH key

### Step 2: Koneksi ke Server
```bash
ssh root@YOUR_SERVER_IP
```

### Step 3: Setup Environment
```bash
# Update system
apt update && apt upgrade -y

# Install Python dan tools
apt install -y python3 python3-pip python3-venv git

# Buat folder project
mkdir -p /opt/ihsg-scanner
cd /opt/ihsg-scanner
```

### Step 4: Upload Files
Dari komputer lokal (PowerShell/CMD):
```bash
scp -r "d:\ALGO TRADE\ihsg-supertrend-scanner\*" root@YOUR_SERVER_IP:/opt/ihsg-scanner/
```

### Step 5: Install Dependencies
```bash
cd /opt/ihsg-scanner
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Step 6: Test Manual
```bash
source venv/bin/activate
python scheduler.py
# Ctrl+C untuk stop jika berhasil
```

---

## Setup Auto-Start dengan Systemd

### Step 7: Buat Service File
```bash
nano /etc/systemd/system/ihsg-scanner.service
```

Paste isi berikut:
```ini
[Unit]
Description=IHSG Supertrend Scanner Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/ihsg-scanner
ExecStart=/opt/ihsg-scanner/venv/bin/python scheduler.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Step 8: Aktifkan Service
```bash
# Reload systemd
systemctl daemon-reload

# Enable auto-start on boot
systemctl enable ihsg-scanner

# Start service
systemctl start ihsg-scanner

# Cek status
systemctl status ihsg-scanner
```

---

## Perintah Berguna

| Aksi | Command |
|------|---------|
| Lihat status | `systemctl status ihsg-scanner` |
| Lihat log | `journalctl -u ihsg-scanner -f` |
| Restart | `systemctl restart ihsg-scanner` |
| Stop | `systemctl stop ihsg-scanner` |
| Start | `systemctl start ihsg-scanner` |

---

## Checklist Sebelum Deploy

- [ ] Pastikan `config/settings.py` sudah diisi TELEGRAM_BOT_TOKEN dan CHAT_ID
- [ ] Test dulu di lokal bahwa bot mengirim Telegram
- [ ] Pastikan `stocks_list.py` sudah berisi saham yang ingin di-scan
