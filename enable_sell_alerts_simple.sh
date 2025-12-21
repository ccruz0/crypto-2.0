#!/bin/bash
# Simplest method - direct SQL update via Python one-liner

INSTANCE_ID="i-08726dc37133b2454"
REGION="ap-southeast-1"

echo "🔧 Enabling Sell Alerts (Simplest Method)"
echo "=========================================="
echo ""

if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI not found"
    exit 1
fi

echo "📤 Executing SQL update..."

# Simplest possible - single Python command, no emojis, no complex formatting
COMMAND_ID=$(aws ssm send-command \
    --instance-ids "$INSTANCE_ID" \
    --document-name "AWS-RunShellScript" \
    --parameters commands="
CONTAINER=\$(docker ps --format '{{.Names}}' | grep -i backend | head -1 || docker ps -q | head -1)
if [ -z \"\$CONTAINER\" ]; then echo 'Container not found'; exit 1; fi
docker exec -i \$CONTAINER python3 -c \"import sys; sys.path.insert(0, '/app'); from sqlalchemy import text; from app.database import SessionLocal; db = SessionLocal(); r = db.execute(text('UPDATE watchlist_items SET sell_alert_enabled = TRUE WHERE alert_enabled = TRUE AND (sell_alert_enabled IS NULL OR sell_alert_enabled = FALSE)')); db.commit(); print('Updated', r.rowcount, 'symbols'); r2 = db.execute(text('SELECT COUNT(*) FROM watchlist_items WHERE alert_enabled = TRUE AND sell_alert_enabled = TRUE')); print('Total enabled:', r2.scalar()); db.close()\"
" \
    --region "$REGION" \
    --output text \
    --query 'Command.CommandId' 2>&1)

if [[ "$COMMAND_ID" =~ ^Error ]] || [ -z "$COMMAND_ID" ]; then
    echo "❌ Failed: $COMMAND_ID"
    exit 1
fi

echo "✅ Command ID: $COMMAND_ID"
echo "⏳ Waiting 60 seconds..."
sleep 60

echo ""
echo "📊 Result:"
aws ssm get-command-invocation \
    --command-id "$COMMAND_ID" \
    --instance-id "$INSTANCE_ID" \
    --region "$REGION" \
    --query '[Status, StandardOutputContent, StandardErrorContent]' \
    --output text 2>&1

echo ""
echo "✅ Done!"




