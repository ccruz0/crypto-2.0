#!/usr/bin/env bash
# Run on EC2: deploy main, install systemd timer, run audit once, capture evidence.
# Usage: from repo root on EC2: bash scripts/aws/run_nightly_audit_deploy_and_validate.sh
# Output: PASS/FAIL and evidence to stdout; no secrets.
set -euo pipefail

REPO_ROOT="${1:-/home/ubuntu/automated-trading-platform}"
cd "$REPO_ROOT"

echo "=== 1) Git pull main ==="
git fetch --all --prune
git checkout main
git pull --ff-only origin main
echo "EC2_HEAD=$(git rev-parse --short HEAD)"

echo ""
echo "=== 2) Syntax + executable ==="
bash -n scripts/aws/nightly_integrity_audit.sh
bash -n scripts/aws/_notify_telegram_fail.sh
chmod +x scripts/aws/nightly_integrity_audit.sh scripts/aws/_notify_telegram_fail.sh

echo ""
echo "=== 3) Manual run (PASS/FAIL only) ==="
AUDIT_OUT=$(bash scripts/aws/nightly_integrity_audit.sh 2>&1) || true
echo "$AUDIT_OUT"
LAST_RESULT=$(echo "$AUDIT_OUT" | tail -1)

echo ""
echo "=== 4) Install systemd ==="
sudo cp scripts/aws/systemd/nightly-integrity-audit.service /etc/systemd/system/
sudo cp scripts/aws/systemd/nightly-integrity-audit.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable nightly-integrity-audit.timer
sudo systemctl restart nightly-integrity-audit.timer

echo ""
echo "=== 5) Timer status + next run ==="
sudo systemctl status nightly-integrity-audit.timer --no-pager || true
sudo systemctl list-timers nightly-integrity-audit.timer --no-pager || true

echo ""
echo "=== 6) Trigger service once ==="
sudo systemctl start nightly-integrity-audit.service || true
sleep 2
echo "--- Last 80 lines journalctl ---"
sudo journalctl -u nightly-integrity-audit.service -n 80 --no-pager || true

echo ""
echo "=== 7) Ports 8002/3000 (127.0.0.1 only) ==="
ss -ltnp 2>/dev/null | grep -E "(:8002|:3000)" || true

echo ""
echo "=== 8) Docker compose aws ps ==="
docker compose --profile aws ps 2>/dev/null || true

echo ""
echo "=== 9) Health endpoints ==="
curl -s -o /dev/null -w "8002/health=%{http_code}\n" http://127.0.0.1:8002/health 2>/dev/null || true
curl -s -o /dev/null -w "8002/api/health/system=%{http_code}\n" http://127.0.0.1:8002/api/health/system 2>/dev/null || true

echo ""
echo "=== REPORT SUMMARY ==="
echo "EC2_HEAD=$(git rev-parse --short HEAD)"
echo "LAST_AUDIT_RESULT=$LAST_RESULT"
