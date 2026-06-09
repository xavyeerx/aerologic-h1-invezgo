#!/bin/bash
# Diagnosa ihsg-scanner gagal start (jalankan di VM: bash scripts/service_doctor.sh)
set -e
cd "$(dirname "$0")/.."
echo "=== IHSG Scanner Doctor ==="
echo "PWD: $(pwd)"
echo "Python: $(./venv/bin/python --version 2>&1)"
echo ""
echo "--- Proses scheduler ---"
ps aux | grep -E "scheduler\.py|flock.*scheduler" | grep -v grep || echo "(tidak ada)"
echo ""
echo "--- Lock files ---"
ls -la database/.scheduler*.lock 2>/dev/null || echo "(tidak ada lock file)"
echo ""
echo "--- Import test ---"
./venv/bin/python -c "
from config.settings import SCANNER_BUILD_ID
from database.state_manager import StateManager
from core.arb_filter import apply_post_alert_arb_gate
print('Build:', SCANNER_BUILD_ID)
print('Import OK')
" || echo "IMPORT GAGAL (lihat error di atas)"
echo ""
echo "--- systemd (butuh sudo) ---"
sudo systemctl status ihsg-scanner --no-pager -l 2>/dev/null | head -15 || true
echo ""
echo "--- journal terakhir ---"
sudo journalctl -u ihsg-scanner -n 25 --no-pager 2>/dev/null || true
echo ""
echo "=== Fix cepat ==="
echo "sudo systemctl stop ihsg-scanner"
echo "pkill -f ihsg-scanner/scheduler.py || true"
echo "rm -f database/.scheduler.lock database/.scheduler_py.lock"
echo "sudo systemctl reset-failed ihsg-scanner"
echo "sudo systemctl start ihsg-scanner"
