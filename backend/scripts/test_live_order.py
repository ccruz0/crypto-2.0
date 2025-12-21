#!/usr/bin/env python3
"""Script to test live order creation for AAVE_USDT"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.database import SessionLocal
from app.models.trading_settings import TradingSettings
from app.services.signal_monitor import signal_monitor_service

def activate_live_trading():
    """Activate LIVE_TRADING temporarily"""
    db = SessionLocal()
    try:
        setting = db.query(TradingSettings).filter(
            TradingSettings.setting_key == "LIVE_TRADING"
        ).first()
        
        if setting:
            old_value = setting.setting_value
            setting.setting_value = "true"
            print(f"✅ LIVE_TRADING actualizado: {old_value} -> true")
        else:
            setting = TradingSettings(setting_key="LIVE_TRADING", setting_value="true")
            db.add(setting)
            print("✅ LIVE_TRADING creado: true")
        
        db.commit()
        return True
    except Exception as e:
        print(f"❌ Error activando LIVE_TRADING: {e}")
        db.rollback()
        return False
    finally:
        db.close()

def create_live_order():
    """Create a live order for AAVE_USDT"""
    symbol = "AAVE_USDT"
    amount_usd = 10.0
    
    print(f"\n🚀 Creando orden LIVE para {symbol} con amount=${amount_usd}")
    print("⚠️  ADVERTENCIA: Esta orden usará dinero REAL\n")
    
    try:
        # Create order using signal_monitor_service
        result = signal_monitor_service._create_buy_order(
            symbol=symbol,
            amount_usd=amount_usd
        )
        
        if result:
            print(f"✅ Orden creada exitosamente: {result}")
            return result
        else:
            print("❌ La orden retornó None")
            return None
    except Exception as e:
        print(f"❌ Error creando orden: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    print("=" * 60)
    print("TEST DE ORDEN LIVE - AAVE_USDT")
    print("=" * 60)
    
    # Activate LIVE_TRADING
    if not activate_live_trading():
        print("❌ No se pudo activar LIVE_TRADING. Abortando.")
        sys.exit(1)
    
    # Wait a moment for the setting to propagate
    import time
    time.sleep(2)
    
    # Create order
    result = create_live_order()
    
    if result:
        print("\n✅ Test completado exitosamente")
    else:
        print("\n❌ Test falló - revisa los logs para más detalles")







