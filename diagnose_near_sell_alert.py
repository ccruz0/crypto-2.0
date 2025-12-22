#!/usr/bin/env python3
"""
Script para diagnosticar por qué NEAR no envía alertas SELL
"""

import sys
import os
from datetime import datetime, timezone

# Agregar el directorio backend al path
script_dir = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(os.path.dirname(script_dir)) == 'scripts' and os.path.basename(os.path.dirname(os.path.dirname(script_dir))) == 'backend':
    backend_dir = os.path.dirname(os.path.dirname(script_dir))
    sys.path.insert(0, backend_dir)
else:
    backend_dir = os.path.join(script_dir, 'backend')
    if os.path.exists(backend_dir):
        sys.path.insert(0, backend_dir)

sys.path.insert(0, '/app')

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.models.signal_throttle import SignalThrottleState
from app.models.market_price import MarketPrice, MarketData

SYMBOL = "NEAR_USDT"

def main():
    print("=" * 60)
    print(f"🔍 DIAGNÓSTICO: {SYMBOL} SELL Alert")
    print("=" * 60)
    print()
    
    db = SessionLocal()
    try:
        # 1. Verificar configuración
        print("1️⃣ CONFIGURACIÓN DEL WATCHLIST")
        print("-" * 60)
        item = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == SYMBOL,
            WatchlistItem.is_deleted == False
        ).first()
        
        if not item:
            print(f"❌ {SYMBOL} no encontrado en watchlist")
            return
        
        print(f"✅ {SYMBOL} encontrado")
        print(f"   - alert_enabled: {item.alert_enabled}")
        print(f"   - sell_alert_enabled: {getattr(item, 'sell_alert_enabled', 'N/A')}")
        print(f"   - buy_alert_enabled: {getattr(item, 'buy_alert_enabled', 'N/A')}")
        print(f"   - trade_enabled: {item.trade_enabled}")
        print()
        
        # 2. Verificar datos de mercado
        print("2️⃣ DATOS DE MERCADO")
        print("-" * 60)
        market_data = db.query(MarketData).filter(MarketData.symbol == SYMBOL).first()
        market_price = db.query(MarketPrice).filter(MarketPrice.symbol == SYMBOL).first()
        
        if market_data:
            print(f"   Precio: ${market_data.price:.4f}")
            print(f"   RSI: {market_data.rsi:.2f}")
            print(f"   MA50: ${market_data.ma50:.4f}" if market_data.ma50 else "   MA50: N/A")
            print(f"   EMA10: ${market_data.ema10:.4f}" if market_data.ema10 else "   EMA10: N/A")
            print(f"   Volume ratio: {market_data.volume_ratio:.2f}x" if market_data.volume_ratio else "   Volume ratio: N/A")
            print(f"   Última actualización: {market_data.updated_at}")
        else:
            print("   ⚠️  No hay datos en market_data")
        print()
        
        # 3. Verificar throttle states
        print("3️⃣ ESTADOS DE THROTTLE")
        print("-" * 60)
        states = db.query(SignalThrottleState).filter(
            SignalThrottleState.symbol == SYMBOL
        ).all()
        
        if states:
            for state in states:
                print(f"   Side: {state.side}, Strategy: {state.strategy_key}")
                print(f"     Last Price: ${state.last_price:.4f}" if state.last_price else "     Last Price: N/A")
                if state.last_time:
                    now = datetime.now(timezone.utc)
                    if state.last_time.tzinfo is None:
                        last_time_utc = state.last_time.replace(tzinfo=timezone.utc)
                    else:
                        last_time_utc = state.last_time.astimezone(timezone.utc)
                    elapsed = (now - last_time_utc).total_seconds() / 60.0
                    print(f"     Last Time: {state.last_time} ({elapsed:.1f} min ago)")
                else:
                    print("     Last Time: N/A")
                print(f"     Source: {state.last_source or 'N/A'}")
                print(f"     Emit Reason: {state.emit_reason or 'N/A'}" if hasattr(state, 'emit_reason') else "     Emit Reason: N/A")
        else:
            print("   ℹ️  No hay estados de throttle (primera señal o nunca se ha enviado)")
        print()
        
        # 4. Verificar columnas de la tabla
        print("4️⃣ VERIFICACIÓN DE ESQUEMA")
        print("-" * 60)
        from sqlalchemy import text
        columns = db.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'signal_throttle_states'
            ORDER BY column_name
        """)).fetchall()
        
        expected = ['emit_reason', 'force_next_signal', 'previous_price']
        existing = [col[0] for col in columns]
        missing = [col for col in expected if col not in existing]
        
        if missing:
            print(f"   ❌ Columnas faltantes: {missing}")
        else:
            print("   ✅ Todas las columnas necesarias existen")
        print()
        
        # 5. Recomendaciones
        print("5️⃣ RECOMENDACIONES")
        print("-" * 60)
        if not item.alert_enabled:
            print("   ❌ Habilitar alert_enabled")
        if not getattr(item, 'sell_alert_enabled', False):
            print("   ❌ Habilitar sell_alert_enabled")
        if missing:
            print(f"   ❌ Agregar columnas faltantes: {missing}")
        if market_data and market_data.rsi:
            if market_data.rsi > 70:
                print("   ✅ RSI > 70 (condición SELL cumplida)")
            else:
                print(f"   ⚠️  RSI = {market_data.rsi:.2f} (debe ser > 70 para SELL)")
        
        print()
        print("=" * 60)
        
    except Exception as e:
        print(f"❌ Error durante diagnóstico: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    main()

