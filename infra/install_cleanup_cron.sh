#!/bin/bash
# Install daily Docker cleanup cron job

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLEANUP_SCRIPT="$SCRIPT_DIR/cleanup_disk.sh"

# Make sure the cleanup script is executable
chmod +x "$CLEANUP_SCRIPT"

# Create a temporary crontab file
TEMP_CRON=$(mktemp)

# Get existing crontab (if any)
crontab -l 2>/dev/null > "$TEMP_CRON" || touch "$TEMP_CRON"

# Check if cleanup job already exists
if grep -q "cleanup_disk.sh" "$TEMP_CRON"; then
    echo "⚠️  Cleanup cron job already exists"
    echo "Current crontab:"
    crontab -l
    exit 0
fi

# Add daily cleanup job at 2 AM
echo "# Daily Docker cleanup - runs at 2 AM" >> "$TEMP_CRON"
echo "0 2 * * * $CLEANUP_SCRIPT >> /tmp/docker-cleanup.log 2>&1" >> "$TEMP_CRON"

# Install the new crontab
crontab "$TEMP_CRON"

# Clean up
rm "$TEMP_CRON"

echo "✅ Daily Docker cleanup cron job installed!"
echo "   Schedule: Daily at 2:00 AM"
echo "   Script: $CLEANUP_SCRIPT"
echo "   Log: /tmp/docker-cleanup.log"
echo ""
echo "Current crontab:"
crontab -l

