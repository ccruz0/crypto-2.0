#!/bin/bash
# Test strategy_key in API response

cd /home/ubuntu/automated-trading-platform

# Get API token
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

# Test API endpoint
echo "Testing /api/market/top-coins-data endpoint..."
echo ""

curl -s -m 10 -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/market/top-coins-data 2>&1 | python3 << 'PYTHON'
import sys
import json

try:
    data = json.load(sys.stdin)
    coins = data.get("coins", [])
    
    if not coins:
        print("❌ No coins returned from API")
        sys.exit(1)
    
    print(f"📊 Total coins returned: {len(coins)}")
    print("\n=== First 5 coins ===")
    
    for i, coin in enumerate(coins[:5], 1):
        name = coin.get("instrument_name", "?")
        strategy_key = coin.get("strategy_key", "MISSING")
        preset = coin.get("strategy_preset", "?")
        risk = coin.get("strategy_risk", "?")
        
        if strategy_key and strategy_key != "MISSING":
            print(f"✅ {i}. {name}: strategy_key='{strategy_key}' (preset={preset}, risk={risk})")
        else:
            print(f"❌ {i}. {name}: strategy_key is MISSING!")
    
    # Check all coins
    missing = [c.get("instrument_name") for c in coins if not c.get("strategy_key")]
    
    print(f"\n📈 Summary:")
    print(f"   Total coins: {len(coins)}")
    print(f"   Coins with strategy_key: {len(coins) - len(missing)}")
    print(f"   Coins missing strategy_key: {len(missing)}")
    
    if missing:
        print(f"\n❌ Coins missing strategy_key: {missing[:10]}")
        sys.exit(1)
    else:
        print(f"\n✅ SUCCESS: All {len(coins)} coins have strategy_key!")
        sys.exit(0)
        
except json.JSONDecodeError as e:
    print(f"❌ Error parsing JSON: {e}")
    print("\nRaw response:")
    sys.stdin.seek(0)
    print(sys.stdin.read()[:500])
    sys.exit(1)
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
PYTHON




