#!/usr/bin/env bash
# Remote execution script for watchlist consistency check
#
# Usage:
#   cd /Users/carloscruz/automated-trading-platform
#   bash scripts/watchlist_consistency_remote.sh

set -e

echo "🔍 Running watchlist consistency check on AWS..."

ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose exec -T backend-aws python scripts/watchlist_consistency_check.py'

echo ""
echo "✅ Consistency check complete."
echo ""
echo "To view the latest report, run:"
echo "  ssh hilovivo-aws 'cat /home/ubuntu/automated-trading-platform/docs/monitoring/watchlist_consistency_report_latest.md'"

