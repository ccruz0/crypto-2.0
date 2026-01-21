#!/bin/bash
# Script to execute alert_enabled fix on AWS
# This script runs the migration to set alert_enabled=True for all active coins

set -e

echo "🔧 Alert System Fix - Execution Script"
echo "========================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Step 1: Check database state BEFORE migration
echo "📊 Step 1: Checking database state BEFORE migration..."
echo ""

docker exec -it postgres_hardened psql -U trader -d atp <<EOF
SELECT 
    COUNT(*) as total_active,
    COUNT(*) FILTER (WHERE alert_enabled = true) as enabled,
    COUNT(*) FILTER (WHERE alert_enabled = false) as disabled
FROM watchlist_items
WHERE is_deleted = false;
EOF

echo ""
echo "Press Enter to continue with migration, or Ctrl+C to cancel..."
read

# Step 2: Execute migration
echo ""
echo "🔧 Step 2: Executing migration to set alert_enabled=True for all active coins..."
echo ""

docker exec -i postgres_hardened psql -U trader -d atp < backend/migrations/enable_alerts_for_all_coins.sql

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Migration executed successfully${NC}"
else
    echo -e "${RED}❌ Migration failed${NC}"
    exit 1
fi

# Step 3: Verify database state AFTER migration
echo ""
echo "📊 Step 3: Verifying database state AFTER migration..."
echo ""

docker exec -it postgres_hardened psql -U trader -d atp <<EOF
SELECT 
    COUNT(*) as total_active,
    COUNT(*) FILTER (WHERE alert_enabled = true) as enabled,
    COUNT(*) FILTER (WHERE alert_enabled = false) as disabled
FROM watchlist_items
WHERE is_deleted = false;
EOF

# Step 4: Show sample symbols
echo ""
echo "📋 Step 4: Sample symbols (first 10):"
echo ""

docker exec -it postgres_hardened psql -U trader -d atp <<EOF
SELECT symbol, alert_enabled, buy_alert_enabled, sell_alert_enabled 
FROM watchlist_items 
WHERE is_deleted = false 
ORDER BY symbol 
LIMIT 10;
EOF

echo ""
echo -e "${GREEN}✅ Alert fix complete!${NC}"
echo ""
echo "Next steps:"
echo "1. Restart backend container to see startup configuration logs"
echo "2. Check logs for [STARTUP_ALERT_CONFIG] messages"
echo "3. Monitor alerts to verify they are not blocked"
echo ""
echo "To check startup logs:"
echo "  docker logs <backend_container> | grep 'STARTUP_ALERT_CONFIG' | head -30"
