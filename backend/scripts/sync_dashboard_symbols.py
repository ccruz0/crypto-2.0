#!/usr/bin/env python3
"""
Script to sync symbols from dashboard to backend
Creates missing symbols with values matching the dashboard
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from sqlalchemy.exc import IntegrityError

# Símbolos que aparecen en el dashboard con sus valores
DASHBOARD_SYMBOLS = {
    'LDO_USD': {
        'trade_enabled': True,
        'alert_enabled': True,
        'buy_alert_enabled': True,
        'sell_alert_enabled': True,
        'trade_amount_usd': 10.0,
        'trade_on_margin': True,
        'sl_tp_mode': 'conservative',
        'exchange': 'CRYPTO_COM',
    },
    'ETC_USDT': {
        'trade_enabled': True,
        'alert_enabled': True,
        'buy_alert_enabled': True,
        'sell_alert_enabled': True,
        'trade_amount_usd': 10.0,
        'trade_on_margin': True,
        'sl_tp_mode': 'conservative',
        'exchange': 'CRYPTO_COM',
    },
    'TRX_USDT': {
        'trade_enabled': True,
        'alert_enabled': True,
        'buy_alert_enabled': True,
        'sell_alert_enabled': True,
        'trade_amount_usd': 10.0,
        'trade_on_margin': True,
        'sl_tp_mode': 'aggressive',  # El dashboard mostraba RISK=Aggressive
        'exchange': 'CRYPTO_COM',
    },
}

def sync_dashboard_symbols():
    """Create missing symbols from dashboard in backend"""
    db = SessionLocal()
    try:
        print("=" * 80)
        print("🔄 SINCRONIZACIÓN: Dashboard → Backend")
        print("=" * 80)
        print()
        
        created = []
        updated = []
        existing = []
        
        for symbol, config in DASHBOARD_SYMBOLS.items():
            # Check if symbol exists
            item = db.query(WatchlistItem).filter(
                WatchlistItem.symbol == symbol,
                WatchlistItem.is_deleted == False
            ).first()
            
            if item:
                # Item exists, check if values match
                needs_update = False
                update_fields = []
                
                for key, value in config.items():
                    if key == 'exchange':
                        continue  # Skip exchange in comparison
                    current_value = getattr(item, key, None)
                    if current_value != value:
                        needs_update = True
                        update_fields.append(f"{key}: {current_value} → {value}")
                        setattr(item, key, value)
                
                if needs_update:
                    try:
                        db.commit()
                        db.refresh(item)
                        updated.append((symbol, update_fields))
                        print(f"✅ {symbol}: Actualizado")
                        for field in update_fields:
                            print(f"   - {field}")
                    except Exception as e:
                        db.rollback()
                        print(f"❌ {symbol}: Error al actualizar: {e}")
                else:
                    existing.append(symbol)
                    print(f"✅ {symbol}: Ya existe con valores correctos")
            else:
                # Create new item
                try:
                    new_item = WatchlistItem(
                        symbol=symbol,
                        exchange=config.get('exchange', 'CRYPTO_COM'),
                        trade_enabled=config.get('trade_enabled', False),
                        alert_enabled=config.get('alert_enabled', False),
                        buy_alert_enabled=config.get('buy_alert_enabled', False),
                        sell_alert_enabled=config.get('sell_alert_enabled', False),
                        trade_amount_usd=config.get('trade_amount_usd'),
                        trade_on_margin=config.get('trade_on_margin', False),
                        sl_tp_mode=config.get('sl_tp_mode', 'conservative'),
                        is_deleted=False,
                    )
                    db.add(new_item)
                    db.commit()
                    db.refresh(new_item)
                    created.append(symbol)
                    print(f"✅ {symbol}: Creado (id={new_item.id})")
                    print(f"   - trade_enabled: {new_item.trade_enabled}")
                    print(f"   - alert_enabled: {new_item.alert_enabled}")
                    print(f"   - trade_amount_usd: {new_item.trade_amount_usd}")
                    print(f"   - trade_on_margin: {new_item.trade_on_margin}")
                    print(f"   - sl_tp_mode: {new_item.sl_tp_mode}")
                except IntegrityError as e:
                    db.rollback()
                    print(f"⚠️  {symbol}: Ya existe (posible duplicado o eliminado)")
                except Exception as e:
                    db.rollback()
                    print(f"❌ {symbol}: Error al crear: {e}")
        
        print()
        print("=" * 80)
        print("📊 RESUMEN")
        print("=" * 80)
        print()
        print(f"✅ Creados: {len(created)}")
        if created:
            for symbol in created:
                print(f"   - {symbol}")
        print()
        print(f"🔄 Actualizados: {len(updated)}")
        if updated:
            for symbol, fields in updated:
                print(f"   - {symbol}: {len(fields)} campos actualizados")
        print()
        print(f"✅ Existentes (sin cambios): {len(existing)}")
        if existing:
            for symbol in existing:
                print(f"   - {symbol}")
        print()
        
        # Verify final state
        print("=" * 80)
        print("🔍 VERIFICACIÓN FINAL")
        print("=" * 80)
        print()
        
        for symbol in DASHBOARD_SYMBOLS.keys():
            item = db.query(WatchlistItem).filter(
                WatchlistItem.symbol == symbol,
                WatchlistItem.is_deleted == False
            ).first()
            
            if item:
                config = DASHBOARD_SYMBOLS[symbol]
                match = True
                mismatches = []
                
                for key, expected_value in config.items():
                    if key == 'exchange':
                        continue
                    actual_value = getattr(item, key, None)
                    if actual_value != expected_value:
                        match = False
                        mismatches.append(f"{key}: expected={expected_value}, actual={actual_value}")
                
                if match:
                    print(f"✅ {symbol}: Todos los valores coinciden")
                else:
                    print(f"❌ {symbol}: Hay discrepancias:")
                    for mismatch in mismatches:
                        print(f"   - {mismatch}")
            else:
                print(f"❌ {symbol}: No encontrado después de la sincronización")
        
        print()
        print("=" * 80)
        print("✅ Sincronización completada")
        print("=" * 80)
        
    except Exception as e:
        print(f"❌ Error durante la sincronización: {e}")
        db.rollback()
        import traceback
        traceback.print_exc()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    sync_dashboard_symbols()













