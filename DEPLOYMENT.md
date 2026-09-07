# Runbook Deployment aerologic ke VPS

Target GitHub:

```text
git@github.com:xavyeerx/aerologic-h1-invezgo.git
```

Bot jalan sebagai service `systemd` dari user VPS default `ubuntu`, dengan folder aplikasi:

```text
/home/ubuntu/aerologic-h1-invezgo
```

Scheduler berjalan setiap 5 menit selama sesi IDX. Indikator dan trigger memakai latest H1 Invezgo, termasuk forming candle; weekend libur.

## 1. Push dari Lokal ke GitHub

Pastikan remote pakai SSH:

```bash
git remote -v
git remote set-url origin git@github.com:xavyeerx/aerologic-h1-invezgo.git
```

Untuk push perubahan:

```bash
git status --short
git diff --check
git add .
git status --short
git diff --cached --stat
git commit -m "Prepare aerologic VPS deployment"
git push -u origin main
```

Untuk push berikutnya cukup:

```bash
git status --short
git diff --check
git add .
git status --short
git diff --cached --stat
git commit -m "Describe your change"
git push origin main
```

Sebelum commit, pastikan `.env`, `database/*.json*`, dan log tidak ikut staged. Kalau ada yang nyasar:

```bash
git restore --staged PATH
```

## 2. Clone dan Install di VPS

Login ke VPS sebagai `ubuntu`, lalu jalankan:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip util-linux nano
sudo timedatectl set-timezone Asia/Jakarta
```

Setup SSH key untuk akses GitHub dari VPS (lakukan sekali):

```bash
ssh-keygen -t ed25519 -C "ubuntu@vps" -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub
```

Salin output pubkey di atas, lalu tambahkan ke GitHub → Settings → SSH and GPG keys → New SSH key. Setelah itu:

```bash
ssh -T git@github.com
cd /home/ubuntu
git clone git@github.com:xavyeerx/aerologic-h1-invezgo.git aerologic-h1-invezgo
cd /home/ubuntu/aerologic-h1-invezgo
python3 -m venv venv
./venv/bin/python -m pip install --upgrade pip
./venv/bin/pip install -r requirements.txt
mkdir -p database logs
```

Kalau folder `aerologic` sudah ada dan ingin ambil update terbaru:

```bash
cd /home/ubuntu/aerologic-h1-invezgo
git pull --ff-only origin main
./venv/bin/pip install -r requirements.txt
```

## 3. Isi Secret

Buat `.env` langsung di folder app:

```bash
cd /home/ubuntu/aerologic-h1-invezgo
nano .env
chmod 600 .env
```

Isi minimal:

```dotenv
TELEGRAM_BOT_TOKEN=replace_me
TELEGRAM_CHAT_ID=-1004302626864
TELEGRAM_TEST_CHAT_ID=replace_me
INVEZGO_API_KEY=replace_me
```

Kalau pakai Telegram Topics, tambahkan:

```dotenv
TELEGRAM_SCANNER_TOPIC_ID=699
```

## 4. Test Sebelum Service

```bash
cd /home/ubuntu/aerologic-h1-invezgo
./venv/bin/python -m compileall -q -f main.py scheduler.py config core database learning notifications scripts
./venv/bin/python -c "import main, scheduler; print('runtime imports: OK')"
./venv/bin/python -m unittest discover -s tests -v
```

## 5. Pasang Systemd

Service template sudah disiapkan untuk user `ubuntu` dan path `/home/ubuntu/aerologic-h1-invezgo`.

```bash
sudo cp /home/ubuntu/aerologic-h1-invezgo/deploy/ihsg-scanner.service.example /etc/systemd/system/aerologic-h1-invezgo.service
sudo systemd-analyze verify /etc/systemd/system/aerologic-h1-invezgo.service
sudo systemctl daemon-reload
sudo systemctl enable --now aerologic-h1-invezgo.service
sudo systemctl status aerologic-h1-invezgo.service --no-pager
```

Cek log:

```bash
sudo journalctl -u aerologic-h1-invezgo.service -n 100 --no-pager
sudo journalctl -u aerologic-h1-invezgo.service -f
```

## 6. Update Production

Setelah push perubahan baru ke GitHub:

```bash
sudo systemctl stop aerologic-h1-invezgo.service
cd /home/ubuntu/aerologic-h1-invezgo
git pull --ff-only origin main
./venv/bin/pip install -r requirements.txt
./venv/bin/python -m compileall -q -f main.py scheduler.py config core database learning notifications scripts
./venv/bin/python -c "import main, scheduler; print('runtime imports: OK')"
sudo systemctl start aerologic-h1-invezgo.service
sudo systemctl status aerologic-h1-invezgo.service --no-pager
```

## 7. Operasi Cepat

```bash
sudo systemctl status aerologic-h1-invezgo.service --no-pager
sudo systemctl restart aerologic-h1-invezgo.service
sudo systemctl stop aerologic-h1-invezgo.service
sudo journalctl -u aerologic-h1-invezgo.service -f
pgrep -af scheduler.py
```

Jangan jalankan `python scheduler.py` manual bersamaan dengan systemd karena bisa bikin scan/alert dobel.
