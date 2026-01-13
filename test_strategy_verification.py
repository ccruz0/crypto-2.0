#!/usr/bin/env python3
"""Verify that all coins have strategy_key, strategy_preset, and strategy_risk"""

import sys
sys.path.insert(0, "/app")

from app.api.routes_market import get_top_coins_with_prices
from app.database import SessionLocal

def main():
    db = SessionLocal()
    try:
        print("=== Calling get_top_coins_with_prices ===")
        result = get_top_coins_with_prices(db=db, current_user=None)
        
        coins = result.get("coins", [])
        print(f"\n✅ Total coins returned: {len(coins)}")
        
        if not coins:
            print("❌ No coins in response")
            return 1
        
        print("\n=== Checking first 10 coins ===")
        missing_key = []
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
                missing_key.append(name)
                issues.append("missing strategy_key")
            if not preset:
                missing_preset.append(name)
                issues.append("missing preset")
            if not risk:
                missing_risk.append(name)
                issues.append("missing risk")
            
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
            print("\n✅✅✅ SUCCESS: All coins have complete strategy information! ✅✅✅")
            return 0
        else:
            print(f"\n❌ FAILURE:")
            print(f"  - {total_missing_key} coins missing strategy_key")
            print(f"  - {total_missing_preset} coins missing preset")
            print(f"  - {total_missing_risk} coins missing risk")
            if missing_key:
                print(f"  Coins missing strategy_key: {missing_key[:10]}")
            return 1
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        db.close()

if __name__ == "__main__":
    sys.exit(main())




