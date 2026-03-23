#!/usr/bin/env python3
"""
Script para actualizar manualmente la caché del portfolio
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.portfolio_cache import get_portfolio_summary, update_portfolio_cache
from app.database import create_db_session
import time

def main():
    db = create_db_session()
    try:
        # Check current cache status
        print("📊 Verificando estado actual de la caché...")
        current = get_portfolio_summary(db)
        if current:
            last_updated = current.get('last_updated', 0)
            age_seconds = time.time() - last_updated if last_updated else 999999
            age_minutes = age_seconds / 60
            balances_count = len(current.get('balances', []))
            print(f"   • Balances en caché: {balances_count}")
            print(f"   • Última actualización: {age_minutes:.1f} minutos atrás")
            
            if age_minutes > 60:
                print(f"   ⚠️  La caché está desactualizada (>60 minutos)")
            else:
                print(f"   ✅ La caché está actualizada")
        else:
            print("   ❌ Cache vacío")
        
        print()
        print("🔄 Intentando actualizar caché desde Crypto.com...")
        result = update_portfolio_cache(db)
        
        if result.get('success'):
            print(f"✅ Caché actualizada exitosamente")
            print(f"   • Total USD: ${result.get('total_usd', 0):,.2f}")
            print(f"   • Timestamp: {result.get('last_updated', 'N/A')}")
        else:
            error = result.get('error', 'Unknown error')
            print(f"❌ Error actualizando caché: {error}")
            if result.get('used_cache'):
                print("   ℹ️  Se está usando la caché existente como respaldo")
            print()
            print("💡 Posibles soluciones:")
            print("   • Verificar que get_account_summary() funcione correctamente")
            print("   • Verificar credenciales de API en Crypto.com")
            print("   • Verificar que la IP esté en la whitelist")
    finally:
        db.close()

if __name__ == "__main__":
    main()






