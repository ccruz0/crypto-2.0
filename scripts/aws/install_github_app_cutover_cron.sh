#!/usr/bin/env bash
# Install hourly GitHub App cutover monitor cron for the current ubuntu user.
# Idempotent — replaces any prior entry for run_github_app_cutover_monitor_with_alerts.sh.
#
# Usage:
#   bash scripts/aws/install_github_app_cutover_cron.sh

set -euo pipefail
set +x 2>/dev/null || true

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT_DIR"

MONITOR_SCRIPT="$ROOT_DIR/scripts/aws/run_github_app_cutover_monitor_with_alerts.sh"
LOG_DIR="$ROOT_DIR/logs"
CRON_TAG="run_github_app_cutover_monitor_with_alerts.sh"
CRON_ENTRY="0 * * * * cd $ROOT_DIR && bash scripts/aws/run_github_app_cutover_monitor_with_alerts.sh"

if [[ ! -f "$MONITOR_SCRIPT" ]]; then
  echo "ERROR: monitor script not found: $MONITOR_SCRIPT" >&2
  exit 1
fi

chmod +x "$MONITOR_SCRIPT"

mkdir -p "$LOG_DIR"
echo "Log directory: $LOG_DIR"

if crontab -l 2>/dev/null | grep -q "$CRON_TAG"; then
  echo "Removing existing cron entry for $CRON_TAG"
  crontab -l 2>/dev/null | grep -v "$CRON_TAG" | crontab -
fi

(crontab -l 2>/dev/null; echo "$CRON_ENTRY") | crontab -

echo
echo "Installed hourly GitHub App cutover monitor cron."
echo
echo "Current crontab:"
crontab -l 2>/dev/null || true
