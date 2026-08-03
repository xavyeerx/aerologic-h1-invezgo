# Runbook Deployment QuantPilot ke VPS

Dokumen ini adalah source of truth untuk push ke GitHub, deployment pertama ke VPS
Linux, operasi `systemd`, update, dan rollback.

## 1. Kondisi Repo dan Arsitektur

Target deployment GitHub adalah repo berikut. Arahkan remote `origin` ke repo ini sebelum push release:

```text
https://github.com/xavyeerx/quantpilotbot.git
```

Jangan langsung push tanpa meninjau file modified, deleted, dan untracked. Working tree lokal saat audit masih berisi banyak perubahan yang belum di-commit.

Arsitektur production yang dipakai:

```text
systemd -> flock -> scheduler.py -> main.run_scan(...)
```

`systemd` menjaga proses, auto-start setelah reboot, restart setelah crash, dan log.
`flock` mencegah instance ganda. Jadwal tetap dikelola `scheduler.py` agar state
scanner hidup sepanjang hari.

### Jadwal saat ini (WIB)

| Hari | Slot | Aksi |
| --- | --- | --- |
| Senin-Kamis | 09:01-12:00 | Scan setiap 5 menit |
| Senin-Kamis | 12:01-13:30 | Istirahat |
| Senin-Kamis | 13:31-16:01 | Scan setiap 5 menit |
| Jumat | 09:01-12:00 | Scan setiap 5 menit |
| Jumat | 12:01-14:00 | Istirahat |
| Jumat | 14:01-16:01 | Scan setiap 5 menit |
| Sabtu-Minggu | Sepanjang hari | Tidak scan |

Service tetap `active (running)` saat malam/weekend karena proses sedang tidur.

Jadwal Jumat sudah diselaraskan agar sesi sore dimulai pukul 14:01 WIB.

## 2. Quality Gate Lokal

Jalankan dari root repo:

```powershell
git status --short
git diff
git diff --cached
git diff --check
git diff --cached --check
git check-ignore -v .env
git ls-files .env
git ls-files --others --exclude-standard
```

Ekspektasi: `.env` di-ignore, `git ls-files .env` kosong, dan tidak ada secret, log,
atau state runtime di diff. File `database/*.json` dan `database/*.jsonl` tidak boleh
masuk Git.

Validasi tanpa memanggil API:

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
python -m compileall -q -f main.py scheduler.py config core database learning notifications scripts
python -c "import main, scheduler; print('runtime imports: OK')"
python -m unittest discover -s tests -v
```

Jalankan seluruh quality gate sebelum rilis. Build hanya boleh dianggap siap deploy jika `compileall`, import runtime, dan test suite relevan lulus.

## 3. Commit dan Push ke GitHub

Gunakan HTTPS sebagai jalur utama. Remote lokal seharusnya mengarah ke:

```powershell
git remote -v
# origin  https://github.com/xavyeerx/quantpilotbot.git (fetch)
# origin  https://github.com/xavyeerx/quantpilotbot.git (push)
```

Jika belum sesuai, ubah remote:

```powershell
git remote set-url origin https://github.com/xavyeerx/quantpilotbot.git
git remote -v
```

GitHub tidak menerima password akun untuk `git push`. Saat diminta login, gunakan
Git Credential Manager atau Personal Access Token dengan izin repo yang cukup.

Untuk workflow harian yang praktis, boleh pakai `git add .` setelah mengecek status:

```powershell
git status --short
git ls-files --others --exclude-standard
git diff --check
git add .
git status --short
git diff --cached --stat
git diff --cached
git commit -m "Prepare QuantPilot Daily scanner for VPS deployment"
git push -u origin main
```

Sebelum commit, baca lagi output `git status --short` dan `git diff --cached --stat`. Kalau ada `.env`, file `database/*.json*`, log, atau file runtime lain yang ikut staged, keluarkan dulu dengan `git restore --staged PATH`.

Pastikan `.env` dan `database/*.json*` tidak terlihat di GitHub. Verifikasi hash lokal
dan remote sama:

```powershell
git rev-parse HEAD
git ls-remote origin refs/heads/main
```

### Push perubahan berikutnya

Untuk perubahan kecil setelah release awal, alurnya sama tetapi commit message-nya
sesuaikan dengan perubahan. Contoh untuk update dokumentasi/settings:

```powershell
git remote -v
git status --short
git diff -- README.md DEPLOYMENT.md config/settings.py scheduler.py
python -m unittest discover -s tests -v
git diff --check
git add .
git status --short
git diff --cached --stat
git diff --cached
git commit -m "Update deployment docs and parameter notes"
git push origin main
```

Jika yang berubah hanya dokumentasi, test boleh diganti dengan minimal:

```powershell
git diff --check
git diff --cached --check
```

Setelah push berhasil, GitHub menjadi source of truth. Jika VPS sudah live, lanjutkan
ke bagian **Update Production** untuk `git pull --ff-only` dan restart service.

## 4. Provisioning VPS

Baseline yang disarankan: Debian 12, 2 vCPU, 2 GB RAM, dan disk 20 GB. Repo
mendeklarasikan Python 3.11. Jika memakai OS/Python lain, ulangi semua quality gate.

```bash
ssh YOUR_ADMIN_USER@VPS_IP
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip util-linux ca-certificates ufw nano
python3 --version
sudo timedatectl set-timezone Asia/Jakarta
timedatectl
```

Bot tidak memerlukan port HTTP/HTTPS untuk menerima traffic. HTTPS di sini hanya dipakai Git untuk clone/push keluar ke GitHub. Sebelum mengaktifkan UFW, cek port SSH aktual
dan pastikan firewall milik provider juga mengizinkannya:

```bash
sudo sshd -T | grep '^port '
```

Jika hasilnya port 22, gunakan profile `OpenSSH`. Untuk port khusus, ganti `SSH_PORT`:

```bash
sudo ufw allow OpenSSH
# atau: sudo ufw allow SSH_PORT/tcp
sudo ufw enable
sudo ufw status verbose
```

Buat user service tanpa akses `sudo`:

```bash
sudo adduser --disabled-password --gecos "" quantpilot
sudo install -d -o quantpilot -g quantpilot -m 0750 /home/quantpilot/backups
```

## 5. Akses Repo dan Install Aplikasi

Untuk repo public, clone langsung via HTTPS:

```bash
sudo -iu quantpilot
git clone https://github.com/xavyeerx/quantpilotbot.git /home/quantpilot/app
cd /home/quantpilot/app
git switch main
git pull --ff-only origin main
python3 -m venv /home/quantpilot/venv
/home/quantpilot/venv/bin/python -m pip install --upgrade pip
/home/quantpilot/venv/bin/pip install -r requirements.txt
mkdir -p database logs
exit
```

Jika repo dibuat private, HTTPS clone/pull di VPS butuh kredensial GitHub. Untuk
production private repo, opsi yang lebih rapi adalah deploy key read-only via SSH,
tetapi runbook ini memakai HTTPS sebagai default karena repo target saat ini diarahkan
ke URL HTTPS.

## 6. Konfigurasi Secret

Simpan secret di luar repo:

```bash
sudo install -d -o root -g quantpilot -m 0750 /etc/quantpilot
sudo touch /etc/quantpilot/quantpilot.env
sudo chown root:quantpilot /etc/quantpilot/quantpilot.env
sudo chmod 0640 /etc/quantpilot/quantpilot.env
sudo nano /etc/quantpilot/quantpilot.env
```

Isi minimal:

```dotenv
TELEGRAM_BOT_TOKEN=replace_me
TELEGRAM_CHAT_ID=replace_me
INVEZGO_API_KEY=replace_me
```

Jika Telegram memakai Topics:

```dotenv
TELEGRAM_TOPIC_DEFAULT=replace_me
TELEGRAM_TOPIC_STRONG_BUY=replace_me
TELEGRAM_TOPIC_STARTUP=replace_me
```

Postgres learning bersifat opsional: `DATABASE_URL=replace_me`. Jangan menambahkan
`export`; gunakan satu `KEY=value` per baris. Bungkus value dengan tanda kutip jika
mengandung spasi atau karakter `#`.

```bash
sudo chown root:quantpilot /etc/quantpilot/quantpilot.env
sudo chmod 0640 /etc/quantpilot/quantpilot.env
sudo ls -l /etc/quantpilot/quantpilot.env
```

## 7. Preflight VPS dan Install Systemd

Jalankan pemeriksaan yang tidak melakukan live scan:

```bash
sudo -u quantpilot bash -lc '
  set -euo pipefail
  set -a
  source /etc/quantpilot/quantpilot.env
  set +a
  : "${TELEGRAM_BOT_TOKEN:?TELEGRAM_BOT_TOKEN kosong}"
  : "${TELEGRAM_CHAT_ID:?TELEGRAM_CHAT_ID kosong}"
  : "${INVEZGO_API_KEY:?INVEZGO_API_KEY kosong}"
  cd /home/quantpilot/app
  /home/quantpilot/venv/bin/python -m compileall -q -f \
    main.py scheduler.py config core database learning notifications
  /home/quantpilot/venv/bin/python -c "import main, scheduler; print(\"runtime imports: OK\")"
  /home/quantpilot/venv/bin/python -m unittest discover -s tests -v
'
```

Jangan lanjut jika ada kegagalan yang belum dipahami dan disetujui. Kegagalan test
obsolete pada bagian 2 harus diperbaiki, bukan sekadar diabaikan di VPS.

Install template service:

```bash
sudo cp /home/quantpilot/app/deploy/ihsg-scanner.service.example \
  /etc/systemd/system/quantpilot-scanner.service
sudo systemd-analyze verify /etc/systemd/system/quantpilot-scanner.service
sudo systemctl daemon-reload
sudo systemctl enable --now quantpilot-scanner.service
```

Periksa hasil:

```bash
sudo systemctl status quantpilot-scanner.service --no-pager
sudo journalctl -u quantpilot-scanner.service -n 100 --no-pager
sudo systemctl is-enabled quantpilot-scanner.service
sudo systemctl is-active quantpilot-scanner.service
pgrep -af '/home/quantpilot/app/scheduler.py'
```

Ekspektasi: service `enabled` dan `active`, hanya ada satu scheduler, journal
menunjukkan build ID serta slot berikutnya, dan Telegram menerima startup notification.

## 8. Validasi Go-Live

Pada hari kerja, observasi satu slot penuh:

```bash
sudo journalctl -u quantpilot-scanner.service -f
```

Validasi dua hal yang berbeda:

1. Implementasi benar: service aktif, satu proses, slot terpicu, tidak ada exception,
   dan state/log dapat ditulis.
2. Tujuan tercapai: request Invezgo berhasil, kandidat dianalisis, deduplikasi alert
   bekerja, Telegram menuju chat/topic yang benar, dan weekend tidak scan.

Checklist:

- [ ] Hash commit VPS sama dengan release GitHub.
- [ ] `systemd-analyze verify` tidak melaporkan error.
- [ ] Service enabled dan active; hanya satu proses scheduler.
- [ ] Timezone VPS `Asia/Jakarta`.
- [ ] Telegram startup dan satu scan hari kerja berhasil.
- [ ] State JSON/JSONL dapat dibuat atau diperbarui.
- [ ] Jadwal Jumat 14:01-16:01 sudah terverifikasi di scheduler.
- [ ] Test suite relevan sudah hijau.

## 9. Update Production

Lakukan di luar jam bursa jika memungkinkan:

```bash
sudo systemctl stop quantpilot-scanner.service
sudo -u quantpilot cp -a /home/quantpilot/app/database \
  /home/quantpilot/backups/database-$(date +%Y%m%d-%H%M%S)

sudo -iu quantpilot bash -lc '
  set -euo pipefail
  cd /home/quantpilot/app
  test -z "$(git status --porcelain)" || {
    echo "ABORT: working tree VPS tidak bersih" >&2
    git status --short
    exit 1
  }
  git fetch origin
  git pull --ff-only origin main
  /home/quantpilot/venv/bin/pip install -r requirements.txt
  /home/quantpilot/venv/bin/python -m compileall -q -f \
    main.py scheduler.py config core database learning notifications
  /home/quantpilot/venv/bin/python -c "import main, scheduler; print(\"runtime imports: OK\")"
'

# Jalankan start hanya jika seluruh blok update di atas exit 0.
sudo systemctl start quantpilot-scanner.service
sudo systemctl status quantpilot-scanner.service --no-pager
sudo journalctl -u quantpilot-scanner.service -n 100 --no-pager
```

`git pull --ff-only` mencegah merge commit tak terkontrol di VPS. Semua perubahan kode
harus berasal dari GitHub.

## 10. Rollback

Sebelum update, catat commit:

```bash
sudo -u quantpilot git -C /home/quantpilot/app rev-parse HEAD
```

Jika release baru rusak:

```bash
sudo systemctl stop quantpilot-scanner.service
sudo -iu quantpilot bash -lc '
  set -euo pipefail
  cd /home/quantpilot/app
  git switch --detach PREVIOUS_COMMIT_HASH
  /home/quantpilot/venv/bin/pip install -r requirements.txt
  /home/quantpilot/venv/bin/python -m compileall -q -f \
    main.py scheduler.py config core database learning notifications
  /home/quantpilot/venv/bin/python -c "import main, scheduler; print(\"rollback preflight: OK\")"
'
# Jalankan start hanya jika rollback preflight di atas exit 0.
sudo systemctl start quantpilot-scanner.service
sudo journalctl -u quantpilot-scanner.service -n 100 --no-pager
```

Kembali ke release terbaru setelah perbaikan:

```bash
sudo systemctl stop quantpilot-scanner.service
sudo -iu quantpilot bash -lc '
  cd /home/quantpilot/app
  git switch main
  git pull --ff-only origin main
  /home/quantpilot/venv/bin/pip install -r requirements.txt
'
sudo systemctl start quantpilot-scanner.service
```

Rollback kode tidak otomatis me-rollback state. Pulihkan backup `database` hanya jika
dampaknya terhadap deduplikasi alert dan penghitung kuota sudah dipahami.

## 11. Operasi dan Troubleshooting

| Aksi | Perintah |
| --- | --- |
| Status | `sudo systemctl status quantpilot-scanner --no-pager` |
| Log live | `sudo journalctl -u quantpilot-scanner -f` |
| 200 log terakhir | `sudo journalctl -u quantpilot-scanner -n 200 --no-pager` |
| Restart | `sudo systemctl restart quantpilot-scanner` |
| Stop/pause | `sudo systemctl stop quantpilot-scanner` |
| Start | `sudo systemctl start quantpilot-scanner` |
| Cek proses | `pgrep -af '/home/quantpilot/app/scheduler.py'` |
| Cek commit | `sudo -u quantpilot git -C /home/quantpilot/app rev-parse --short HEAD` |

Jangan menjalankan `nohup python scheduler.py`, cron, atau service kedua bersamaan.
Itu meningkatkan pemakaian API dan risiko alert ganda.

Jika service gagal:

```bash
sudo systemctl status quantpilot-scanner.service --no-pager -l
sudo journalctl -u quantpilot-scanner.service -b --no-pager
sudo systemd-analyze verify /etc/systemd/system/quantpilot-scanner.service
sudo namei -l /home/quantpilot/app/scheduler.py
sudo namei -l /etc/quantpilot/quantpilot.env
```

Jika diduga ada proses ganda:

```bash
pgrep -af 'scheduler.py'
systemctl list-units --type=service --all | grep -i quantpilot
systemctl list-timers --all | grep -i quantpilot
sudo crontab -l
crontab -l
```

Weekend tanpa scan adalah perilaku yang diinginkan. Service tetap aktif dan journal
menunjukkan waktu bangun berikutnya pada Senin 09:01 WIB.

## 12. Risiko Lanjutan

1. Full test suite harus tetap dijalankan ulang sebelum setiap release.
2. Kalender hanya membedakan weekday/weekend. Pada hari libur Bursa yang jatuh Senin-Jumat, scheduler masih dapat mencoba scan.
3. Dependency hanya memakai lower bounds (`>=`), sehingga install belum sepenuhnya
   reproducible. Buat lock file setelah baseline production tervalidasi.
4. State runtime berada di disk VPS lokal; backup off-host dan restore belum otomatis.

Go-live harus diperlakukan sebagai rollout terobservasi, bukan sekadar service yang
berhasil berstatus `active`.
