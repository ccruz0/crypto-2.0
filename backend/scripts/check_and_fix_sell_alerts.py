#!/usr/bin/env python3
"""
General-purpose script to check and fix SELL alert configuration for any symbol.
Can be used to:
1. Check a specific symbol
2. Check all symbols
3. Fix a specific symbol
4. Bulk fix all symbols with alert_enabled=True
"""

import sys
import argparse
from pathlib import Path

# Add the app directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem

def check_symbol(symbol: str, db: Session) -> dict:
    """Check configuration for a specific symbol"""
    watchlist_item = db.query(WatchlistItem).filter(
        WatchlistItem.symbol == symbol,
        WatchlistItem.is_deleted == False
    ).first()
    
    if not watchlist_item:
        return {"exists": False, "symbol": symbol}
    
    return {
        "exists": True,
        "symbol": symbol,
        "alert_enabled": watchlist_item.alert_enabled,
        "sell_alert_enabled": getattr(watchlist_item, 'sell_alert_enabled', False),
        "buy_alert_enabled": getattr(watchlist_item, 'buy_alert_enabled', False),
        "trade_enabled": watchlist_item.trade_enabled,
        "trade_amount_usd": watchlist_item.trade_amount_usd,
    }

def fix_symbol(symbol: str, db: Session, set_trade_amount: bool = False) -> dict:
    """Fix configuration for a specific symbol"""
    watchlist_item = db.query(WatchlistItem).filter(
        WatchlistItem.symbol == symbol,
        WatchlistItem.is_deleted == False
    ).first()
    
    if not watchlist_item:
        return {"success": False, "error": f"{symbol} not found in watchlist"}
    
    changes = []
    
    # Enable sell_alert_enabled if alert_enabled is True
    if watchlist_item.alert_enabled and not getattr(watchlist_item, 'sell_alert_enabled', False):
        watchlist_item.sell_alert_enabled = True
        changes.append("sell_alert_enabled: False → True")
    
    # Set trade_amount_usd if requested and not configured
    if set_trade_amount and (not watchlist_item.trade_amount_usd or watchlist_item.trade_amount_usd <= 0):
        watchlist_item.trade_amount_usd = 10.0
        changes.append("trade_amount_usd: not set → 10.0")
    
    if changes:
        try:
            db.add(watchlist_item)
            db.commit()
            db.refresh(watchlist_item)
            return {"success": True, "symbol": symbol, "changes": changes}
        except Exception as e:
            db.rollback()
            return {"success": False, "error": str(e)}
    else:
        return {"success": True, "symbol": symbol, "changes": [], "message": "No changes needed"}

def check_all_symbols(db: Session) -> list:
    """Check all symbols in watchlist"""
    items = db.query(WatchlistItem).filter(
        WatchlistItem.is_deleted == False
    ).all()
    
    results = []
    for item in items:
        results.append({
            "symbol": item.symbol,
            "alert_enabled": item.alert_enabled,
            "sell_alert_enabled": getattr(item, 'sell_alert_enabled', False),
            "buy_alert_enabled": getattr(item, 'buy_alert_enabled', False),
            "trade_enabled": item.trade_enabled,
            "issue": "sell_alert_disabled" if item.alert_enabled and not getattr(item, 'sell_alert_enabled', False) else None
        })
    
    return results

def bulk_fix_symbols(db: Session, set_trade_amount: bool = False) -> dict:
    """Fix all symbols with alert_enabled=True but sell_alert_enabled=False"""
    items = db.query(WatchlistItem).filter(
        WatchlistItem.is_deleted == False,
        WatchlistItem.alert_enabled == True
    ).all()
    
    fixed = []
    skipped = []
    errors = []
    
    for item in items:
        sell_alert_enabled = getattr(item, 'sell_alert_enabled', False)
        
        if not sell_alert_enabled:
            # Fix this symbol
            item.sell_alert_enabled = True
            changes = ["sell_alert_enabled: False → True"]
            
            if set_trade_amount and (not item.trade_amount_usd or item.trade_amount_usd <= 0):
                item.trade_amount_usd = 10.0
                changes.append("trade_amount_usd: not set → 10.0")
            
            try:
                db.add(item)
                db.commit()
                db.refresh(item)
                fixed.append({"symbol": item.symbol, "changes": changes})
            except Exception as e:
                db.rollback()
                errors.append({"symbol": item.symbol, "error": str(e)})
        else:
            skipped.append(item.symbol)
    
    return {
        "fixed": fixed,
        "skipped": skipped,
        "errors": errors,
        "total_fixed": len(fixed),
        "total_skipped": len(skipped),
        "total_errors": len(errors)
    }

def main():
    parser = argparse.ArgumentParser(description="Check and fix SELL alert configuration")
    parser.add_argument("--symbol", "-s", help="Specific symbol to check/fix (e.g., ETC_USDT)")
    parser.add_argument("--check-all", "-a", action="store_true", help="Check all symbols")
    parser.add_argument("--fix", "-f", action="store_true", help="Fix the symbol(s)")
    parser.add_argument("--bulk-fix", "-b", action="store_true", help="Bulk fix all symbols with alert_enabled=True")
    parser.add_argument("--set-trade-amount", action="store_true", help="Set trade_amount_usd to 10.0 if not configured")
    
    args = parser.parse_args()
    
    db: Session = SessionLocal()
    
    try:
        if args.check_all:
            # Check all symbols
            print("\n" + "="*80)
            print("🔍 Checking all symbols in watchlist")
            print("="*80 + "\n")
            
            results = check_all_symbols(db)
            
            issues = [r for r in results if r["issue"]]
            ok = [r for r in results if not r["issue"]]
            
            if issues:
                print(f"⚠️  Found {len(issues)} symbol(s) with potential issues:\n")
                for item in issues:
                    print(f"   {item['symbol']}: alert_enabled={item['alert_enabled']}, sell_alert_enabled={item['sell_alert_enabled']}")
            else:
                print("✅ No issues found - all symbols are configured correctly")
            
            print(f"\n📊 Summary: {len(issues)} with issues, {len(ok)} OK")
            
        elif args.bulk_fix:
            # Bulk fix all symbols
            print("\n" + "="*80)
            print("🔧 Bulk fixing all symbols with alert_enabled=True")
            print("="*80 + "\n")
            
            result = bulk_fix_symbols(db, set_trade_amount=args.set_trade_amount)
            
            if result["fixed"]:
                print(f"✅ Fixed {result['total_fixed']} symbol(s):\n")
                for item in result["fixed"]:
                    print(f"   {item['symbol']}: {', '.join(item['changes'])}")
            
            if result["skipped"]:
                print(f"\n✓ Skipped {result['total_skipped']} symbol(s) (already configured)")
            
            if result["errors"]:
                print(f"\n❌ Errors fixing {result['total_errors']} symbol(s):")
                for item in result["errors"]:
                    print(f"   {item['symbol']}: {item['error']}")
            
        elif args.symbol:
            # Check/fix specific symbol
            symbol = args.symbol.upper()
            
            if args.fix:
                print(f"\n{'='*80}")
                print(f"🔧 Fixing: {symbol}")
                print(f"{'='*80}\n")
                
                result = fix_symbol(symbol, db, set_trade_amount=args.set_trade_amount)
                
                if result["success"]:
                    if result.get("changes"):
                        print(f"✅ Fixed {symbol}:")
                        for change in result["changes"]:
                            print(f"   • {change}")
                    else:
                        print(f"✅ {symbol} is already configured correctly")
                else:
                    print(f"❌ Error: {result.get('error', 'Unknown error')}")
            else:
                # Just check
                print(f"\n{'='*80}")
                print(f"🔍 Checking: {symbol}")
                print(f"{'='*80}\n")
                
                result = check_symbol(symbol, db)
                
                if not result["exists"]:
                    print(f"❌ {symbol} not found in watchlist")
                else:
                    print(f"📋 Configuration:")
                    print(f"   alert_enabled: {result['alert_enabled']}")
                    print(f"   sell_alert_enabled: {result['sell_alert_enabled']}")
                    print(f"   buy_alert_enabled: {result['buy_alert_enabled']}")
                    print(f"   trade_enabled: {result['trade_enabled']}")
                    print(f"   trade_amount_usd: {result['trade_amount_usd']}")
                    
                    if result['alert_enabled'] and not result['sell_alert_enabled']:
                        print(f"\n⚠️  ISSUE: alert_enabled=True but sell_alert_enabled=False")
                        print(f"   Run with --fix to enable sell_alert_enabled")
        else:
            parser.print_help()
            print("\nExamples:")
            print("  # Check ETC_USDT configuration")
            print("  python3 check_and_fix_sell_alerts.py --symbol ETC_USDT")
            print("  # Fix ETC_USDT")
            print("  python3 check_and_fix_sell_alerts.py --symbol ETC_USDT --fix")
            print("  # Check all symbols")
            print("  python3 check_and_fix_sell_alerts.py --check-all")
            print("  # Bulk fix all symbols with alert_enabled=True")
            print("  python3 check_and_fix_sell_alerts.py --bulk-fix")
    
    except Exception as e:
        print(f"❌ Error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    main()














