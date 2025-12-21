#!/bin/bash
# Script to run the alert fix on the AWS server
# Usage: ./run_fix_alerts_server.sh

set -e

echo "🔧 FIXING ALERTS ON AWS SERVER"
echo "================================"

# Copy the script to server and execute it
SERVER_IP="${SERVER_IP:-47.130.143.159}"
HOST="ubuntu@${SERVER_IP}"
SSH_OPTS="-o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=15"

echo "📤 Copying fix script to server..."
scp $SSH_OPTS -i ~/.ssh/id_rsa fix_alerts_fallback.py $HOST:~/

echo "🚀 Executing fix script on server..."
ssh $SSH_OPTS -i ~/.ssh/id_rsa $HOST "cd /home/ubuntu && python3 fix_alerts_fallback.py"

echo ""
echo "🔎 Verifying alert flags counts (container)..."
# Try both possible backend container names
ssh $SSH_OPTS -i ~/.ssh/id_rsa $HOST "set -e; \
  found=''; \
  for name in backend-aws backend; do \
    while IFS= read -r running; do \
      if [ \"\$running\" = \"\$name\" ]; then found=\"\$name\"; fi; \
    done <<EOF\n\$(docker ps --format '{{.Names}}')\nEOF\n \
    if [ -n \"\$found\" ]; then break; fi; \
  done; \
  if [ -z \"\$found\" ]; then echo 'No backend container found to verify.'; exit 2; fi; \
  echo \"Found container: \$found\"; \
  docker exec \"\$found\" python3 - <<'PY'\nfrom app.database import SessionLocal\nfrom app.models.watchlist import WatchlistItem\n\ndb = SessionLocal()\ntry:\n    # total active (exclude deleted if column exists)\n    q = db.query(WatchlistItem)\n    if hasattr(WatchlistItem, 'is_deleted'):\n        q = q.filter(WatchlistItem.is_deleted == False)\n    total = q.count()\n\n    master = db.query(WatchlistItem).filter(WatchlistItem.alert_enabled == True).count()\n    buy = db.query(WatchlistItem).filter(getattr(WatchlistItem, 'buy_alert_enabled', False) == True).count() if hasattr(WatchlistItem, 'buy_alert_enabled') else 0\n    sell = db.query(WatchlistItem).filter(getattr(WatchlistItem, 'sell_alert_enabled', False) == True).count() if hasattr(WatchlistItem, 'sell_alert_enabled') else 0\n\n    print(f\"total_items={total}\")\n    print(f\"alert_enabled_true={master}\")\n    print(f\"buy_alert_enabled_true={buy}\")\n    print(f\"sell_alert_enabled_true={sell}\")\nfinally:\n    db.close()\nPY"

echo ""
echo "✅ ALERT FIX COMPLETED!"
echo ""
echo "🔍 NEXT STEPS:"
echo "   1. Check the dashboard to verify alerts are enabled"
echo "   2. Monitor logs for alert notifications"
echo "   3. Test with coins that meet BUY/SELL conditions"
echo ""
echo "📊 TO VERIFY ALERT STATUS:"
echo "   Run: ssh -i ~/.ssh/id_rsa $HOST 'docker exec backend-aws python3 -c \""
echo "   from app.database import SessionLocal"
echo "   from app.models.watchlist import WatchlistItem"
echo "   db = SessionLocal()"
echo "   items = db.query(WatchlistItem).filter(WatchlistItem.alert_enabled == True).count()"
echo "   buy_items = db.query(WatchlistItem).filter(WatchlistItem.buy_alert_enabled == True).count()"
echo "   sell_items = db.query(WatchlistItem).filter(WatchlistItem.sell_alert_enabled == True).count()"
echo "   print(f'Alert enabled: {items}, Buy alerts: {buy_items}, Sell alerts: {sell_items}')"
echo "   db.close()"
echo "   \""










