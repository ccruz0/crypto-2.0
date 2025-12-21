# Code Review: check_btc_usd_sell_alert.sh

## Issues Found

### 1. **Quote Escaping Problem** ⚠️

The script has complex nested quotes that may cause parsing issues:

```bash
print('Symbol:', item.symbol if item else 'NOT FOUND')
```

The single quotes inside the Python string conflict with the shell's quote handling. The working script (`enable_sell_alerts_ultra_simple.sh`) uses a simpler approach without quotes in print statements.

### 2. **Error Handling Missing** ⚠️

No validation of:
- Command ID validity
- AWS CLI availability
- Command execution success

### 3. **Wait Time Too Short** ⚠️

30 seconds might not be enough for command execution. The working script uses 60 seconds.

## Recommended Fix

Use the same pattern as `enable_sell_alerts_ultra_simple.sh` which successfully worked:

```bash
#!/bin/bash
INSTANCE_ID="i-08726dc37133b2454"
REGION="ap-southeast-1"
echo "Checking BTC_USD sell alert configuration..."
CMD_ID=$(aws ssm send-command --instance-ids "$INSTANCE_ID" --document-name "AWS-RunShellScript" --parameters 'commands=["CONTAINER=$(docker ps --format \"{{.Names}}\" | grep -i backend | head -1); docker exec -i $CONTAINER python3 -c \"import sys; sys.path.insert(0, '\''/app'\''); from sqlalchemy.orm import Session; from app.database import SessionLocal; from app.models.watchlist import WatchlistItem; db = SessionLocal(); item = db.query(WatchlistItem).filter(WatchlistItem.symbol == '\''BTC_USD'\'').first(); print('Symbol:', item.symbol if item else 'NOT FOUND'); print('alert_enabled:', item.alert_enabled if item else None); print('sell_alert_enabled:', getattr(item, '\''sell_alert_enabled'\'', False) if item else None); print('buy_alert_enabled:', getattr(item, '\''buy_alert_enabled'\'', False) if item else None); db.close()\""]' --region "$REGION" --output text --query 'Command.CommandId')
echo "Command ID: $CMD_ID"
echo "Waiting 60 seconds..."
sleep 60
aws ssm get-command-invocation --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" --region "$REGION" --query '[Status, StandardOutputContent, StandardErrorContent]' --output text
```

**Key changes:**
1. Removed quotes from print statements (use Python's default string formatting)
2. Increased wait time to 60 seconds
3. Simplified structure (single line for command)

## Alternative: Use Base64 Encoding

If quote issues persist, use base64 encoding like other scripts:

```bash
# Encode Python script
PYTHON_SCRIPT='import sys
sys.path.insert(0, "/app")
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
db = SessionLocal()
item = db.query(WatchlistItem).filter(WatchlistItem.symbol == "BTC_USD").first()
if item:
    print(f"Symbol: {item.symbol}")
    print(f"alert_enabled: {item.alert_enabled}")
    print(f"sell_alert_enabled: {getattr(item, 'sell_alert_enabled', False)}")
    print(f"buy_alert_enabled: {getattr(item, 'buy_alert_enabled', False)}")
else:
    print("BTC_USD NOT FOUND")
db.close()'

ENCODED=$(echo "$PYTHON_SCRIPT" | base64)
# Then use base64 -d in the command
```

## Testing

After fixing, test with:
```bash
./check_btc_usd_sell_alert.sh
```

Expected output:
```
Symbol: BTC_USD
alert_enabled: True
sell_alert_enabled: True
buy_alert_enabled: True/False
```




