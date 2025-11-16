#!/bin/bash

# Test script to manually trigger the frontend error check
# This is useful for testing before waiting for the hourly cron job

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "🧪 Testing frontend error check script..."
echo ""

cd "$SCRIPT_DIR"
./check-frontend-errors.sh

echo ""
echo "✅ Test complete. Check the log file for details:"
echo "   tail -f $SCRIPT_DIR/frontend-error-check.log"

