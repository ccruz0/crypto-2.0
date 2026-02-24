#!/usr/bin/env bash
# Print OpenClaw LAB command blocks to paste into SSM Session Manager.
# Usage: ./scripts/openclaw/print_lab_commands.sh [step]
#   step: 1|2|3|4|5 or empty (print all).
# Run from repo root. Connect to LAB first: aws ssm start-session --target i-0d82c172235770a0d --region ap-southeast-1

set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

STEP="${1:-}"

print_step1() {
  cat << 'STEP1'
# --- Step 1: Prepare host (Docker, repo) ---
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 2>/dev/null || true
sudo usermod -aG docker "$(whoami)"
cd /home/ubuntu
[ -d automated-trading-platform ] || git clone https://github.com/ccruz0/crypto-2.0.git automated-trading-platform
cd automated-trading-platform
git fetch origin main && git checkout main
STEP1
}

print_step2() {
  cat << 'STEP2'
# --- Step 2: GitHub token (paste PAT when prompted) ---
mkdir -p ~/secrets
chmod 700 ~/secrets
touch ~/secrets/openclaw_token
chmod 600 ~/secrets/openclaw_token
read -r -s -p 'Paste GitHub fine-grained PAT: ' TOKEN
echo -n "$TOKEN" > ~/secrets/openclaw_token
unset TOKEN
test -r ~/secrets/openclaw_token && echo "OK: token readable"
STEP2
}

print_step3() {
  cat << 'STEP3'
# --- Step 3: .env.lab ---
cd /home/ubuntu/automated-trading-platform
cp .env.lab.example .env.lab
chmod 600 .env.lab
nano .env.lab
# Set: GIT_REPO_URL, OPENCLAW_TOKEN_PATH=/home/ubuntu/secrets/openclaw_token, OPENCLAW_IMAGE=ghcr.io/ccruz0/openclaw:latest
grep -i token .env.lab
STEP3
}

print_step4() {
  cat << 'STEP4'
# --- Step 4: Start OpenClaw ---
cd /home/ubuntu/automated-trading-platform
docker compose -f docker-compose.openclaw.yml up -d
docker compose -f docker-compose.openclaw.yml ps
docker compose -f docker-compose.openclaw.yml logs -f openclaw
STEP4
}

print_step5() {
  cat << 'STEP5'
# --- Step 5 (optional): systemd for reboot ---
sudo cp /home/ubuntu/automated-trading-platform/scripts/openclaw/openclaw.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable openclaw
sudo systemctl start openclaw
STEP5
}

case "$STEP" in
  1) print_step1 ;;
  2) print_step2 ;;
  3) print_step3 ;;
  4) print_step4 ;;
  5) print_step5 ;;
  "")
    echo "Paste each block into your SSM session (LAB). Connect: aws ssm start-session --target i-0d82c172235770a0d --region ap-southeast-1"
    echo ""
    print_step1
    echo ""
    print_step2
    echo ""
    print_step3
    echo ""
    print_step4
    echo ""
    print_step5
    ;;
  *)
    echo "Usage: $0 [1|2|3|4|5]" >&2
    exit 1
    ;;
esac
