#!/bin/bash
# Script para actualizar todas las monedas en AWS usando AWS Session Manager

set -e

INSTANCE_ID="i-08726dc37133b2454"
REGION="ap-southeast-1"

echo "========================================="
echo "Actualizando monedas en AWS"
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

# Create Python script content
PYTHON_SCRIPT='import sys
sys.path.insert(0, "/app")
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

db = SessionLocal()
try:
    all_items = db.query(WatchlistItem).all()
    logger.info("Encontradas {} monedas en el watchlist".format(len(all_items)))
    
    updated_count = 0
    already_set_count = 0
    
    for item in all_items:
        symbol = item.symbol.upper() if item.symbol else ""
        needs_update = False
        
        if item.alert_enabled != False:
            item.alert_enabled = False
            needs_update = True
        if item.trade_enabled != False:
            item.trade_enabled = False
            needs_update = True
        if hasattr(item, "trade_on_margin") and item.trade_on_margin != False:
            item.trade_on_margin = False
            needs_update = True
        
        if needs_update:
            updated_count += 1
            logger.info("{}: alert_enabled=False, trade_enabled=False, trade_on_margin=False".format(symbol))
        else:
            already_set_count += 1
    
    db.commit()
    
    logger.info("\n" + "="*80)
    logger.info("PROCESO COMPLETADO")
    logger.info("="*80)
    logger.info("Total de monedas procesadas: {}".format(len(all_items)))
    logger.info("Monedas actualizadas: {}".format(updated_count))
    logger.info("Monedas que ya tenian los valores correctos: {}".format(already_set_count))
    
    # Verify
    alert_enabled_count = db.query(WatchlistItem).filter(WatchlistItem.alert_enabled == True).count()
    trade_enabled_count = db.query(WatchlistItem).filter(WatchlistItem.trade_enabled == True).count()
    margin_count = db.query(WatchlistItem).filter(WatchlistItem.trade_on_margin == True).count() if hasattr(WatchlistItem, "trade_on_margin") else 0
    
    logger.info("\nVERIFICACION:")
    logger.info("  Monedas con alert_enabled=True: {}".format(alert_enabled_count))
    logger.info("  Monedas con trade_enabled=True: {}".format(trade_enabled_count))
    logger.info("  Monedas con trade_on_margin=True: {}".format(margin_count))
    
    if alert_enabled_count == 0 and trade_enabled_count == 0 and margin_count == 0:
        logger.info("\nPERFECTO: Todas las monedas tienen alert_enabled=False, trade_enabled=False, trade_on_margin=False")
    else:
        logger.warning("\nAUN HAY MONEDAS ACTIVAS: {} alert, {} trade, {} margin".format(alert_enabled_count, trade_enabled_count, margin_count))
    
except Exception as e:
    db.rollback()
    logger.error("Error al actualizar monedas: {}".format(e), exc_info=True)
    raise
finally:
    db.close()'

# Base64 encode the script
ENCODED_SCRIPT=$(echo "$PYTHON_SCRIPT" | base64)

# Create command to decode and execute
# Try different service names and profiles
COMMAND="cd /home/ubuntu/automated-trading-platform && echo '$ENCODED_SCRIPT' | base64 -d > /tmp/update_coins.py && (docker compose --profile aws exec -T backend-aws python3 /tmp/update_coins.py 2>/dev/null || docker compose exec -T backend-aws python3 /tmp/update_coins.py 2>/dev/null || docker compose exec -T backend python3 /tmp/update_coins.py 2>/dev/null || docker exec -i \$(docker ps --filter 'name=backend' --format '{{.Names}}' | head -1) python3 /tmp/update_coins.py)"

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
    --output text

print_status "✅ Comando completado"
