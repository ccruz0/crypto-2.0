#!/bin/bash
# Deploy and run enable_sell_alerts via AWS SSM - exact pattern from update_coins_aws_ssm.sh

set -e

INSTANCE_ID="i-08726dc37133b2454"
REGION="ap-southeast-1"

echo "========================================="
echo "Enabling Sell Alerts in AWS"
echo "========================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Create Python script content (exact same pattern as update_coins_aws_ssm.sh)
PYTHON_SCRIPT='import sys
sys.path.insert(0, "/app")
from app.database import SessionLocal
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

db = SessionLocal()
try:
    result = db.execute(text("UPDATE watchlist_items SET sell_alert_enabled = TRUE WHERE alert_enabled = TRUE AND (sell_alert_enabled IS NULL OR sell_alert_enabled = FALSE)"))
    db.commit()
    count = result.rowcount
    logger.info("✅ Enabled sell alerts for {} symbols".format(count))
    
    result2 = db.execute(text("SELECT COUNT(*) FROM watchlist_items WHERE alert_enabled = TRUE AND sell_alert_enabled = TRUE"))
    total = result2.scalar()
    logger.info("📊 Total symbols with sell alerts enabled: {}".format(total))
    
    print("✅ Enabled sell alerts for {} symbols".format(count))
    print("📊 Total symbols with sell alerts enabled: {}".format(total))
except Exception as e:
    logger.error("❌ Error: {}".format(e), exc_info=True)
    print("❌ Error: {}".format(e))
    db.rollback()
    raise
finally:
    db.close()'

# Base64 encode the script
ENCODED_SCRIPT=$(echo "$PYTHON_SCRIPT" | base64)

# Create command to decode and execute (exact same pattern as update_coins_aws_ssm.sh)
COMMAND="cd /home/ubuntu/automated-trading-platform && echo '$ENCODED_SCRIPT' | base64 -d > /tmp/enable_sell_alerts.py && docker compose --profile aws exec -T backend-aws python3 /tmp/enable_sell_alerts.py 2>/dev/null || docker compose exec -T backend-aws python3 /tmp/enable_sell_alerts.py 2>/dev/null || docker compose exec -T backend python3 /tmp/enable_sell_alerts.py 2>/dev/null || docker exec -i \$(docker ps --filter 'name=backend' --format '{{.Names}}' | head -1) python3 /tmp/enable_sell_alerts.py"

print_status "Enviando comando a AWS EC2 instance $INSTANCE_ID..."

# Send command via AWS SSM
COMMAND_ID=$(aws ssm send-command \
    --instance-ids "$INSTANCE_ID" \
    --document-name "AWS-RunShellScript" \
    --parameters "commands=[\"$COMMAND\"]" \
    --region "$REGION" \
    --output text \
    --query 'Command.CommandId')

if [ -z "$COMMAND_ID" ]; then
    print_error "Failed to send command"
    exit 1
fi

print_status "Comando enviado. Command ID: $COMMAND_ID"
print_status "Esperando resultado (esto puede tomar 30-90 segundos)..."

# Wait for command to complete
MAX_WAIT=90
WAIT_TIME=0
while [ $WAIT_TIME -lt $MAX_WAIT ]; do
    sleep 5
    WAIT_TIME=$((WAIT_TIME + 5))
    
    STATUS=$(aws ssm get-command-invocation \
        --command-id "$COMMAND_ID" \
        --instance-id "$INSTANCE_ID" \
        --region "$REGION" \
        --query 'Status' \
        --output text 2>/dev/null || echo "Pending")
    
    if [ "$STATUS" = "Success" ] || [ "$STATUS" = "Failed" ]; then
        break
    fi
    
    echo -n "."
done
echo ""

# Get final output
print_status "Obteniendo resultado..."
aws ssm get-command-invocation \
    --command-id "$COMMAND_ID" \
    --instance-id "$INSTANCE_ID" \
    --region "$REGION" \
    --query '[Status, StandardOutputContent, StandardErrorContent]' \
    --output text 2>&1

echo ""
echo "✅ Proceso completado!"




