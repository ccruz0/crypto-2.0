#!/bin/bash
# Simple script to run audit - copy these commands to SSH session

echo "🔍 Audit Commands - Copy and paste these on your AWS server:"
echo ""
echo "=========================================="
echo "# 1. Find container name"
echo "docker compose --profile aws ps"
echo ""
echo "# 2. Run audit"
echo "docker exec automated-trading-platform-backend-aws-1 \\"
echo "  python backend/scripts/audit_no_alerts_no_trades.py --since-hours 24"
echo ""
echo "# 3. View report"
echo "docker exec automated-trading-platform-backend-aws-1 \\"
echo "  cat docs/reports/no-alerts-no-trades-audit.md"
echo ""
echo "# 4. Check heartbeat"
echo "docker logs automated-trading-platform-backend-aws-1 | grep HEARTBEAT | tail -5"
echo ""
echo "# 5. Check global blockers"
echo "docker logs automated-trading-platform-backend-aws-1 | grep GLOBAL_BLOCKER | tail -5"
echo ""
echo "=========================================="
echo ""
echo "Or run via SSH in one command:"
echo ""
echo "ssh your-aws-server 'cd /home/ubuntu/automated-trading-platform && docker exec automated-trading-platform-backend-aws-1 python backend/scripts/audit_no_alerts_no_trades.py --since-hours 24'"




