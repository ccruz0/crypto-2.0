#!/bin/bash
# Check BTC_USD sell alert configuration via AWS SSM
# Fixed version with better container handling

INSTANCE_ID="i-08726dc37133b2454"
REGION="ap-southeast-1"

echo "Checking BTC_USD sell alert configuration..."
echo ""

# Match exact working pattern from enable_sell_alerts_ultra_simple.sh
# Use same quote escaping that worked
CMD_ID=$(aws ssm send-command --instance-ids "$INSTANCE_ID" --document-name "AWS-RunShellScript" --parameters 'commands=["CONTAINER=$(docker ps --format \"{{.Names}}\" | grep -i backend | head -1); docker exec -i $CONTAINER python3 -c \"import sys; sys.path.insert(0, '\''/app'\''); from sqlalchemy.orm import Session; from app.database import SessionLocal; from app.models.watchlist import WatchlistItem; db = SessionLocal(); item = db.query(WatchlistItem).filter(WatchlistItem.symbol == '\''BTC_USD'\'').first(); s = item.symbol if item else '\''NOT FOUND'\''; a = item.alert_enabled if item else None; sa = getattr(item, '\''sell_alert_enabled'\'', False) if item else None; ba = getattr(item, '\''buy_alert_enabled'\'', False) if item else None; print('\''Symbol:'\'', s, '\''alert_enabled:'\'', a, '\''sell_alert_enabled:'\'', sa, '\''buy_alert_enabled:'\'', ba); db.close()\""]' --region "$REGION" --output text --query 'Command.CommandId')

if [ -z "$CMD_ID" ] || [[ "$CMD_ID" =~ ^Error ]]; then
    echo "❌ Failed to send command: $CMD_ID"
    exit 1
fi

echo "✅ Command ID: $CMD_ID"
echo "⏳ Waiting 60 seconds for execution..."
sleep 60

echo ""
echo "📊 Result:"
aws ssm get-command-invocation --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" --region "$REGION" --query '[Status, StandardOutputContent, StandardErrorContent]' --output text

echo ""
echo "✅ Done!"




