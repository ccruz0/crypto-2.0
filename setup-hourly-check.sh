#!/bin/bash

# Setup Hourly Frontend Error Check
# This script sets up a cron job to run the frontend error checker every hour

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECK_SCRIPT="${SCRIPT_DIR}/check-frontend-errors.sh"
CRON_JOB="0 * * * * ${CHECK_SCRIPT} >> ${SCRIPT_DIR}/frontend-error-check-cron.log 2>&1"

echo "Setting up hourly frontend error check..."
echo ""

# Check if cron job already exists
if crontab -l 2>/dev/null | grep -q "$CHECK_SCRIPT"; then
    echo "⚠️  Cron job already exists. Removing old entry..."
    crontab -l 2>/dev/null | grep -v "$CHECK_SCRIPT" | crontab -
fi

# Add new cron job
(crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -

if [ $? -eq 0 ]; then
    echo "✅ Hourly frontend error check has been set up successfully!"
    echo ""
    echo "The script will run every hour at minute 0 (e.g., 1:00, 2:00, 3:00...)"
    echo ""
    echo "To view the current cron jobs:"
    echo "  crontab -l"
    echo ""
    echo "To remove the cron job:"
    echo "  crontab -l | grep -v \"$CHECK_SCRIPT\" | crontab -"
    echo ""
    echo "Log files:"
    echo "  - Detailed log: ${SCRIPT_DIR}/frontend-error-check.log"
    echo "  - Cron log: ${SCRIPT_DIR}/frontend-error-check-cron.log"
else
    echo "❌ Failed to set up cron job"
    exit 1
fi

