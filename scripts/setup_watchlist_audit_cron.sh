#!/usr/bin/env bash
#
# Setup Cron Job for Daily Watchlist Audit
# This script configures a cron job to run watchlist audit tests daily at 2 AM Bali time (UTC+8)
#
# Usage:
#   bash scripts/setup_watchlist_audit_cron.sh
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
AUDIT_SCRIPT="$PROJECT_ROOT/scripts/run_watchlist_audit_daily.sh"

# Bali timezone is UTC+8
# 2 AM Bali time = 18:00 UTC (previous day)
# We'll use TZ environment variable to set Bali timezone

CRON_SCHEDULE="0 2 * * *"  # 2 AM daily (will use TZ to set Bali time)

# Check if script exists
if [ ! -f "$AUDIT_SCRIPT" ]; then
    echo "❌ Error: Audit script not found at $AUDIT_SCRIPT"
    exit 1
fi

# Make sure script is executable
chmod +x "$AUDIT_SCRIPT"

# Create cron job entry
CRON_ENTRY="$CRON_SCHEDULE TZ=Asia/Makassar cd $PROJECT_ROOT && bash $AUDIT_SCRIPT >> $PROJECT_ROOT/logs/cron_audit.log 2>&1"

# Check if cron job already exists
if crontab -l 2>/dev/null | grep -q "run_watchlist_audit_daily.sh"; then
    echo "⚠️  Cron job already exists. Removing old entry..."
    crontab -l 2>/dev/null | grep -v "run_watchlist_audit_daily.sh" | crontab -
fi

# Add new cron job
(crontab -l 2>/dev/null; echo "$CRON_ENTRY") | crontab -

echo "✅ Cron job configured successfully!"
echo ""
echo "Schedule: Daily at 2:00 AM Bali time (Asia/Makassar, UTC+8)"
echo "Script: $AUDIT_SCRIPT"
echo "Logs: $PROJECT_ROOT/logs/"
echo ""
echo "Current crontab:"
crontab -l | grep "run_watchlist_audit_daily.sh"
echo ""
echo "To view cron logs:"
echo "  tail -f $PROJECT_ROOT/logs/cron_audit.log"
echo ""
echo "To remove the cron job:"
echo "  crontab -e  # Then delete the line with run_watchlist_audit_daily.sh"












