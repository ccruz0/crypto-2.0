#!/usr/bin/env bash
# Remove hourly GitHub App cutover monitor cron entry for the current user.
# Does not delete monitor logs.
#
# Usage:
#   bash scripts/aws/uninstall_github_app_cutover_cron.sh

set -euo pipefail
set +x 2>/dev/null || true

CRON_TAG="run_github_app_cutover_monitor_with_alerts.sh"

if crontab -l 2>/dev/null | grep -q "$CRON_TAG"; then
  echo "Removing cron entry containing $CRON_TAG"
  crontab -l 2>/dev/null | grep -v "$CRON_TAG" | crontab -
else
  echo "No cron entry found for $CRON_TAG"
fi

echo
echo "Current crontab:"
crontab -l 2>/dev/null || echo "(empty)"
