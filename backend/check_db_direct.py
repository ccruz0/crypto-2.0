#!/usr/bin/env python3
"""Script para verificar trade_enabled directamente desde la base de datos"""
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem

db = SessionLocal()
try:
    items = db.query(WatchlistItem).filter(WatchlistItem.is_deleted == False).order_by(WatchlistItem.symbol).all()
    print(f"📊 Encontradas {len(items)} monedas")
    print("=" * 100)
    print(f"{'Symbol':<15} {'Trade':<10} {'Amount USD':<12}")
    print("=" * 100)
    trade_yes = []
    for item in items:
        symbol = item.symbol or "N/A"
        trade_status = "✅ YES" if item.trade_enabled else "❌ NO"
        amount_str = f"${item.trade_amount_usd:,.2f}" if item.trade_amount_usd else "N/A"
        print(f"{symbol:<15} {trade_status:<10} {amount_str:<12}")
        if item.trade_enabled:
            trade_yes.append(symbol)
    print("=" * 100)
    print(f"✅ Trade YES: {len(trade_yes)} monedas")
    print(f"❌ Trade NO: {len(items) - len(trade_yes)} monedas")
    print(f"📋 Monedas con Trade YES: {', '.join(sorted(trade_yes)) if trade_yes else 'Ninguna'}")
    print()
    print("🔍 Verificación específica del dashboard:")
    dashboard_symbols = ["ETH_USDT", "SOL_USDT", "LDO_USD", "BTC_USD"]
    for symbol in dashboard_symbols:
        found = next((item for item in items if item.symbol == symbol), None)
        if found:
            status = "✅ YES" if found.trade_enabled else "❌ NO"
            print(f"   {status} {symbol:<15} Trade: {status}")
        else:
            print(f"   ⚠️  {symbol:<15} No encontrada")
finally:
    db.close()

