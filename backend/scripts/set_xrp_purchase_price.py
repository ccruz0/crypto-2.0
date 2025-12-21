#!/usr/bin/env python3
"""
Script to set manual purchase price for XRP in watchlist
Based on the order history from Crypto.com:
- Date: 2025-09-14
- Average Price: $3.0800
- Quantity: 162.3 XRP
- Value: ~$499.88
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem

def set_xrp_purchase_price():
    """Set manual purchase price for XRP"""
    db = SessionLocal()
    try:
        # Try different symbol variants
        symbol_variants = ['XRP_USDT', 'XRP_USD', 'XRP']
        
        watchlist_item = None
        for symbol in symbol_variants:
            watchlist_item = db.query(WatchlistItem).filter(
                WatchlistItem.symbol == symbol
            ).first()
            if watchlist_item:
                print(f"✅ Found watchlist item for {symbol}")
                break
        
        if not watchlist_item:
            # Create new watchlist item for XRP
            print("📝 Creating new watchlist item for XRP_USDT")
            watchlist_item = WatchlistItem(
                symbol="XRP_USDT",
                exchange="CRYPTO_COM",
                purchase_price=3.0800,  # Average price from order history
                quantity=162.3,  # Quantity from order history
            )
            db.add(watchlist_item)
        else:
            # Update existing watchlist item
            print(f"📝 Updating existing watchlist item for {watchlist_item.symbol}")
            old_price = watchlist_item.purchase_price
            watchlist_item.purchase_price = 3.0800
            watchlist_item.quantity = 162.3
        
        db.commit()
        db.refresh(watchlist_item)
        
        print("\n" + "=" * 80)
        print("✅ Purchase Price Updated Successfully")
        print("=" * 80)
        print(f"Symbol: {watchlist_item.symbol}")
        print(f"Purchase Price: ${watchlist_item.purchase_price:.4f}")
        print(f"Quantity: {watchlist_item.quantity:.2f} XRP")
        print(f"Total Value: ${watchlist_item.purchase_price * watchlist_item.quantity:.2f}")
        print("\n💡 The Expected Take Profit dashboard should now show:")
        print(f"   - Purchase Value: ${watchlist_item.purchase_price * watchlist_item.quantity:.2f}")
        print(f"   - Expected Profit: Calculated based on TP orders")
        
    except Exception as e:
        db.rollback()
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    set_xrp_purchase_price()







