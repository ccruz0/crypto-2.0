#!/bin/bash
INSTANCE_ID="i-08726dc37133b2454"
REGION="ap-southeast-1"
echo "Enabling Sell Alerts..."
CMD_ID=$(aws ssm send-command --instance-ids "$INSTANCE_ID" --document-name "AWS-RunShellScript" --parameters 'commands=["CONTAINER=$(docker ps --format \"{{.Names}}\" | grep -i backend | head -1); docker exec -i $CONTAINER python3 -c \"import sys; sys.path.insert(0, '\''/app'\''); from sqlalchemy import text; from app.database import SessionLocal; db = SessionLocal(); r = db.execute(text('\''UPDATE watchlist_items SET sell_alert_enabled = TRUE WHERE alert_enabled = TRUE AND (sell_alert_enabled IS NULL OR sell_alert_enabled = FALSE)'\'')); db.commit(); print('\''Updated'\'', r.rowcount, '\''symbols'\''); r2 = db.execute(text('\''SELECT COUNT(*) FROM watchlist_items WHERE alert_enabled = TRUE AND sell_alert_enabled = TRUE'\'')); print('\''Total enabled:'\'', r2.scalar()); db.close()\""]' --region "$REGION" --output text --query 'Command.CommandId')
echo "Command ID: $CMD_ID"
echo "Waiting 60 seconds..."
sleep 60
aws ssm get-command-invocation --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" --region "$REGION" --query '[Status, StandardOutputContent, StandardErrorContent]' --output text




