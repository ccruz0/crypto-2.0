#!/usr/bin/env bash
# Apply health-alert auto-fix on EC2: update snapshot timer to every 5 min, deploy alert script (heal-on-alert), reload systemd.
# Run from your machine: ./scripts/deploy_health_alert_autofix.sh
# Or on the server: REPO_DIR=/path/to/repo bash scripts/deploy_health_alert_autofix.sh --on-server

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_DIR="${REPO_DIR:-/home/ubuntu/crypto-2.0}"
ON_SERVER="${1:-}"

run_on_server() {
  local repo_dir="$1"
  cd "$repo_dir" || exit 1
  chmod +x scripts/selfheal/remediate_market_data.sh 2>/dev/null || true
  echo "=== Copying atp-health-snapshot.timer (every 5 min) ==="
  sudo cp scripts/selfheal/systemd/atp-health-snapshot.timer /etc/systemd/system/
  echo "=== Reloading systemd ==="
  sudo systemctl daemon-reload
  echo "=== Restarting atp-health-snapshot.timer ==="
  sudo systemctl restart atp-health-snapshot.timer
  sudo systemctl enable atp-health-snapshot.timer 2>/dev/null || true
  echo "=== Timer status ==="
  sudo systemctl status atp-health-snapshot.timer --no-pager || true
  echo "=== Self-heal timer (should be active) ==="
  sudo systemctl status atp-selfheal.timer --no-pager || true
  echo "=== Done ==="
}

if [[ "$ON_SERVER" == "--on-server" ]]; then
  run_on_server "$REPO_DIR"
  exit 0
fi

# From local: copy files to server, then run deployment steps
EC2_HOST="${EC2_HOST:-hilovivo-aws}"
echo "Deploying health-alert auto-fix to $EC2_HOST..."

# Copy updated timer and alert script to server
scp "$REPO_ROOT/scripts/selfheal/systemd/atp-health-snapshot.timer" "$EC2_HOST:/tmp/atp-health-snapshot.timer"
scp "$REPO_ROOT/scripts/diag/health_snapshot_telegram_alert.sh" "$EC2_HOST:$REPO_DIR/scripts/diag/health_snapshot_telegram_alert.sh"
scp "$REPO_ROOT/scripts/selfheal/remediate_market_data.sh" "$EC2_HOST:$REPO_DIR/scripts/selfheal/remediate_market_data.sh"

# Copy timer to systemd and run deployment
ssh "$EC2_HOST" "chmod +x $REPO_DIR/scripts/selfheal/remediate_market_data.sh 2>/dev/null; sudo cp /tmp/atp-health-snapshot.timer /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl restart atp-health-snapshot.timer && sudo systemctl enable atp-health-snapshot.timer 2>/dev/null || true"
echo "=== atp-health-snapshot.timer (every 5 min) ==="
ssh "$EC2_HOST" "sudo systemctl status atp-health-snapshot.timer --no-pager" || true
echo "=== atp-selfheal.timer ==="
ssh "$EC2_HOST" "sudo systemctl status atp-selfheal.timer --no-pager" || true
echo "Done. Alert script updated; snapshot runs every 5 min; heal runs when alert fires."
