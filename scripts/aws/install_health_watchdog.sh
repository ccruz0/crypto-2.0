#!/usr/bin/env bash
# Install ATP primary backend health watchdog (cron.d + state seed).
# Run on EC2 prod host as root or with sudo. Does not deploy compose or restart stacks.
#
# Usage:
#   cd ~/automated-trading-platform
#   sudo ./scripts/aws/install_health_watchdog.sh
#
# Optional: seed grace without restart (e.g. during exchange_sync storm):
#   sudo ATP_HEALTH_WATCHDOG_SEED_GRACE=1 ./scripts/aws/install_health_watchdog.sh
set -euo pipefail

REPO_ROOT="${ATP_REPO_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
SCRIPT="$REPO_ROOT/scripts/aws/health_watchdog.sh"
CRON_SRC="$REPO_ROOT/scripts/aws/cron.d/atp-health-watchdog"
CRON_DST="/etc/cron.d/atp-health-watchdog"
STATE_DIR="/var/lib/atp"
STATE_FILE="${ATP_HEALTH_WATCHDOG_STATE:-$STATE_DIR/health_watchdog.state}"
LOG_FILE="/var/log/atp/health_watchdog.log"

if [ ! -f "$SCRIPT" ]; then
  echo "Missing $SCRIPT — pull repo first." >&2
  exit 1
fi

chmod +x "$SCRIPT"

mkdir -p "$STATE_DIR"
touch "$LOG_FILE"
chmod 644 "$LOG_FILE" 2>/dev/null || true

# Adjust cron path if repo is not at default location
if [ "$REPO_ROOT" != "/home/ubuntu/automated-trading-platform" ]; then
  sed "s|/home/ubuntu/automated-trading-platform|$REPO_ROOT|g" "$CRON_SRC" | sudo tee "$CRON_DST" >/dev/null
else
  sudo cp "$CRON_SRC" "$CRON_DST"
fi
sudo chmod 644 "$CRON_DST"

if [ ! -f "$STATE_FILE" ] || [ "${ATP_HEALTH_WATCHDOG_SEED_GRACE:-0}" = "1" ]; then
  now="$(date +%s)"
  cat >"$STATE_FILE" <<EOF
consecutive_fails=0
last_restart_epoch=${now}
restart_epochs=
EOF
  echo "Seeded $STATE_FILE (last_restart_epoch=$now) — grace period active; no restart loop during sync storm."
else
  echo "State file exists: $STATE_FILE (not re-seeded; set ATP_HEALTH_WATCHDOG_SEED_GRACE=1 to re-seed)"
fi

echo "Installed:"
echo "  script:  $SCRIPT"
echo "  cron:    $CRON_DST (every 2 min)"
echo "  state:   $STATE_FILE"
echo "  log:     $LOG_FILE"
echo ""
echo "Manual test (dry run): ATP_HEALTH_WATCHDOG_DRY_RUN=1 $SCRIPT"
echo "Disable Telegram:      ATP_HEALTH_WATCHDOG_TELEGRAM=0 $SCRIPT"
