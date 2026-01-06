#!/bin/bash
set -e

cd /home/ubuntu/automated-trading-platform

echo "=== Step 1: Get API Token ==="
TOKEN=$(docker compose --profile aws exec -T backend-aws python3 -c "
from app.database import SessionLocal
from app.models.user import User
db = SessionLocal()
user = db.query(User).first()
if user and user.api_key:
    print(user.api_key)
else:
    print('test')
db.close()
" 2>/dev/null | head -1)

if [ -z "$TOKEN" ] || [ "$TOKEN" = "None" ]; then
    TOKEN="test"
fi

echo "Token: ${TOKEN:0:20}..."
echo ""

echo "=== Step 2: Test API Endpoint ==="
curl -s -m 15 -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/market/top-coins-data -o /tmp/api_response.json 2>&1

if [ $? -eq 0 ] && [ -s /tmp/api_response.json ]; then
    echo "✅ API responded successfully"
    echo "Response size: $(wc -c < /tmp/api_response.json) bytes"
else
    echo "❌ API request failed or empty response"
    cat /tmp/api_response.json | head -20
    exit 1
fi

echo ""
echo "=== Step 3: Verify Strategy Fields ==="
python3 << 'PYEOF'
import json
import sys

try:
    with open("/tmp/api_response.json", "r") as f:
        data = json.load(f)
    
    coins = data.get("coins", [])
    print(f"Total coins in response: {len(coins)}")
    print("\n=== Checking first 10 coins ===")
    
    missing_strategy_key = []
    missing_preset = []
    missing_risk = []
    
    for i, coin in enumerate(coins[:10], 1):
        name = coin.get("instrument_name", "?")
        sk = coin.get("strategy_key")
        preset = coin.get("strategy_preset")
        risk = coin.get("strategy_risk")
        
        status = "✅"
        issues = []
        if not sk:
            status = "❌"
            issues.append("missing strategy_key")
            missing_strategy_key.append(name)
        if not preset:
            issues.append("missing preset")
            missing_preset.append(name)
        if not risk:
            issues.append("missing risk")
            missing_risk.append(name)
        
        issues_str = ", ".join(issues) if issues else ""
        print(f"{status} {i}. {name}: strategy_key=\"{sk}\" preset=\"{preset}\" risk=\"{risk}\" {issues_str}")
    
    # Check all coins
    total_missing_key = sum(1 for c in coins if not c.get("strategy_key"))
    total_missing_preset = sum(1 for c in coins if not c.get("strategy_preset"))
    total_missing_risk = sum(1 for c in coins if not c.get("strategy_risk"))
    
    print("\n=== Summary ===")
    print(f"Total coins: {len(coins)}")
    print(f"Coins with strategy_key: {len(coins) - total_missing_key} / {len(coins)}")
    print(f"Coins with strategy_preset: {len(coins) - total_missing_preset} / {len(coins)}")
    print(f"Coins with strategy_risk: {len(coins) - total_missing_risk} / {len(coins)}")
    
    if total_missing_key == 0 and total_missing_preset == 0 and total_missing_risk == 0:
        print("\n✅ SUCCESS: All coins have complete strategy information!")
        sys.exit(0)
    else:
        print(f"\n❌ FAILURE: {total_missing_key} coins missing strategy_key, {total_missing_preset} missing preset, {total_missing_risk} missing risk")
        if missing_strategy_key:
            print(f"Coins missing strategy_key: {missing_strategy_key[:10]}")
        sys.exit(1)
        
except json.JSONDecodeError as e:
    print(f"❌ Error parsing JSON: {e}")
    print("\nFirst 500 chars of response:")
    with open("/tmp/api_response.json", "r") as f:
        print(f.read()[:500])
    sys.exit(1)
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
PYEOF

echo ""
echo "=== Verification Complete ==="



