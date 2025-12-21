#!/usr/bin/env python3
"""
Script para revisar qué posiciones no tienen TP/SL
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.sl_tp_checker import sl_tp_checker_service
from app.database import SessionLocal

def main():
    db = SessionLocal()
    try:
        print("🔍 Revisando posiciones sin TP/SL...")
        print("="*70)
        
        result = sl_tp_checker_service.check_positions_for_sl_tp(db)
        
        total_positions = result.get('total_positions', 0)
        positions_missing = result.get('positions_missing_sl_tp', [])
        
        print(f"\n📊 Resumen:")
        print(f"   • Total de posiciones: {total_positions}")
        print(f"   • Posiciones sin TP/SL: {len(positions_missing)}")
        
        if positions_missing:
            print(f"\n❌ Posiciones sin protección TP/SL:")
            print("="*70)
            
            # Obtener precios actuales para calcular valores USD
            from app.services.portfolio_cache import get_crypto_prices
            prices = get_crypto_prices()
            
            for i, pos in enumerate(positions_missing, 1):
                symbol = pos.get('symbol', 'N/A')
                currency = pos.get('currency', 'N/A')
                balance = float(pos.get('balance', 0))
                has_sl = pos.get('has_sl', False)
                has_tp = pos.get('has_tp', False)
                
                print(f"\n{i}. {symbol} ({currency})")
                print(f"   Balance: {balance:,.8f}")
                
                # Calcular valor USD usando precios actuales
                base_currency = currency.split('_')[0] if '_' in currency else currency
                current_price = prices.get(base_currency, 0)
                
                if current_price > 0:
                    usd_value = balance * current_price
                    print(f"   Precio actual: ${current_price:,.6f}")
                    print(f"   Valor USD: ${usd_value:,.2f}")
                else:
                    print(f"   Valor USD: No disponible (precio no encontrado)")
                
                # Mostrar qué falta
                if not has_sl and not has_tp:
                    print(f"   ❌ Falta: SL y TP")
                elif not has_sl:
                    print(f"   ⚠️  Falta: STOP LOSS (tiene TP)")
                elif not has_tp:
                    print(f"   ⚠️  Falta: TAKE PROFIT (tiene SL)")
                
                # Mostrar precios sugeridos de watchlist si están disponibles
                sl_price = pos.get('sl_price')
                tp_price = pos.get('tp_price')
                if sl_price:
                    print(f"   💡 SL sugerido: ${float(sl_price):,.6f}")
                if tp_price:
                    print(f"   💡 TP sugerido: ${float(tp_price):,.6f}")
        else:
            print(f"\n✅ Todas las posiciones tienen TP/SL configurados")
        
        print("\n" + "="*70)
        print("💡 Para crear TP/SL faltantes:")
        print("   • Usa el comando de Telegram: /create_sl_tp [symbol]")
        print("   • O ejecuta: python3 scripts/create_missing_tp_orders.py")
        
    finally:
        db.close()

if __name__ == "__main__":
    main()





