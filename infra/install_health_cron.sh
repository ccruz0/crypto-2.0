#!/bin/bash
#
# Installation script for health monitoring cron job
#
# This script helps install the health monitoring cron job that runs every 5 minutes.
#
# Usage:
#   bash infra/install_health_cron.sh
#

set -e

PROJECT_DIR="/home/ubuntu/automated-trading-platform"
CRON_LOG="/var/log/atp_health_monitor.log"
PYTHON_PATH="/usr/bin/python3"
SCRIPT_PATH="$PROJECT_DIR/infra/monitor_health.py"
CRON_SCHEDULE="*/5 * * * *"

echo "=========================================="
echo "Health Monitor Cron Installation"
echo "=========================================="
echo ""
echo "This script will add a cron job to monitor your application health every 5 minutes."
echo ""
echo "Configuration:"
echo "  Project directory: $PROJECT_DIR"
echo "  Script path: $SCRIPT_PATH"
echo "  Log file: $CRON_LOG"
echo "  Schedule: Every 5 minutes"
echo ""

# Check if script exists
if [ ! -f "$SCRIPT_PATH" ]; then
    echo "❌ Error: Script not found at $SCRIPT_PATH"
    echo "   Please ensure you're running this from the project root."
    exit 1
fi

# Make script executable
chmod +x "$SCRIPT_PATH"
echo "✅ Script is executable"

# Create log file if it doesn't exist
sudo touch "$CRON_LOG"
sudo chmod 666 "$CRON_LOG" 2>/dev/null || echo "⚠️  Could not set permissions on log file (may need sudo)"
echo "✅ Log file ready: $CRON_LOG"

# Build cron command
CRON_COMMAND="cd $PROJECT_DIR && $PYTHON_PATH $SCRIPT_PATH >> $CRON_LOG 2>&1"
CRON_LINE="$CRON_SCHEDULE $CRON_COMMAND"

echo ""
echo "=========================================="
echo "Cron Job Configuration"
echo "=========================================="
echo ""
echo "The following cron job will be added:"
echo ""
echo "$CRON_LINE"
echo ""
echo "This will:"
echo "  1. Change to project directory: $PROJECT_DIR"
echo "  2. Run the health monitor script"
echo "  3. Append output to: $CRON_LOG"
echo ""

# Check if cron job already exists
if crontab -l 2>/dev/null | grep -q "monitor_health.py"; then
    echo "⚠️  Warning: A cron job for monitor_health.py already exists!"
    echo ""
    echo "Current crontab entries:"
    crontab -l 2>/dev/null | grep "monitor_health.py" || true
    echo ""
    read -p "Do you want to replace it? (y/N): " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Installation cancelled."
        exit 0
    fi
    
    # Remove existing entry
    crontab -l 2>/dev/null | grep -v "monitor_health.py" | crontab -
    echo "✅ Removed existing cron job"
fi

# Add new cron job
(crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -

echo "✅ Cron job installed successfully!"
echo ""
echo "=========================================="
echo "Next Steps"
echo "=========================================="
echo ""
echo "1. Verify the cron job is installed:"
echo "   crontab -l"
echo ""
echo "2. Check the logs after 5 minutes:"
echo "   tail -f $CRON_LOG"
echo ""
echo "3. To remove the cron job later:"
echo "   crontab -l | grep -v 'monitor_health.py' | crontab -"
echo ""
echo "4. To manually test the script:"
echo "   cd $PROJECT_DIR"
echo "   $PYTHON_PATH $SCRIPT_PATH"
echo ""
echo "=========================================="
echo "Installation Complete!"
echo "=========================================="

