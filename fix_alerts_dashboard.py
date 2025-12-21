#!/usr/bin/env python3
"""
Script to diagnose and fix alerts deactivated in the dashboard.
This script can be run on the server to check and enable all alert settings.
"""

import sys
import os
import requests
import json
from datetime import datetime

def check_alerts_api():
    """Check current alert status via API endpoints"""
    print("="*80)
    print("🔍 DIAGNÓSTICO: ALERTAS DESACTIVADAS EN EL DASHBOARD")
    print("="*80)

    # Try different API endpoints
    endpoints = [
        ("http://localhost:8002", "Local"),
        ("http://47.130.143.159:8002", "AWS Direct"),
        ("http://175.41.189.249:8002", "AWS Public")
    ]

    for url, label in endpoints:
        print(f"\n🌐 Probando {label}: {url}")
        try:
            # Test basic connectivity
            response = requests.get(f"{url}/ping_fast", timeout=5)
            if response.status_code == 200:
                print("  ✅ API reachable")

                # Try alert stats endpoint
                try:
                    stats_response = requests.get(f"{url}/api/dashboard/alert-stats", timeout=10)
                    if stats_response.status_code == 200:
                        data = stats_response.json()
                        print("  📊 Alert stats retrieved:")
                        print(f"     - Total items: {data.get('total_items', 0)}")
                        print(f"     - Buy alerts enabled: {data.get('buy_alerts_enabled', 0)}")
                        print(f"     - Sell alerts enabled: {data.get('sell_alerts_enabled', 0)}")
                        print(f"     - Both alerts enabled: {data.get('both_alerts_enabled', 0)}")
                        print(f"     - Trading enabled: {data.get('trade_enabled', 0)}")

                        return url, data  # Return working endpoint and data
                    else:
                        print(f"  ❌ Alert stats failed: {stats_response.status_code}")
                except Exception as e:
                    print(f"  ❌ Alert stats error: {e}")
            else:
                print(f"  ❌ API not responding: {response.status_code}")
        except Exception as e:
            print(f"  ❌ Connection failed: {e}")

    return None, None

def enable_alerts_via_api(api_url):
    """Enable all alerts via bulk update API"""
    print(f"\n🔧 HABILITANDO ALERTAS VIA API: {api_url}")

    payload = {
        "buy_alerts": True,
        "sell_alerts": True,
        "trade_enabled": False  # Keep trading disabled for safety
    }

    try:
        response = requests.post(f"{api_url}/api/dashboard/bulk-update-alerts", json=payload, timeout=30)

        if response.status_code == 200:
            data = response.json()
            print("✅ ALERTAS HABILITADAS EXITOSAMENTE")
            print(f"   - Items actualizados: {data.get('updated_count', 0)}")
            print(f"   - Total items: {data.get('total_items', 0)}")
            print(f"   - Buy alerts: {'✅' if data.get('buy_alert_enabled') else '❌'}")
            print(f"   - Sell alerts: {'✅' if data.get('sell_alert_enabled') else '❌'}")
            print(f"   - Trade enabled: {'✅' if data.get('trade_enabled') else '❌'}")
            return True
        else:
            print(f"❌ ERROR {response.status_code}: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Error conectando: {e}")
        return False

def create_fallback_script():
    """Create a fallback script that can be run directly on the server"""
    print("\n📝 CREANDO SCRIPT DE FALLBACK PARA EJECUTAR EN EL SERVIDOR")
    print("="*80)

    script_content = '''#!/usr/bin/env python3
"""
Script de fallback para habilitar alertas directamente en la base de datos.
Ejecutar en el servidor con: python3 fix_alerts_fallback.py
"""

import sys
import os

# Add backend to path
sys.path.insert(0, "/app")

try:
    from app.database import SessionLocal
    from app.models.watchlist import WatchlistItem
    import logging

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    def enable_all_alerts():
        """Enable all alerts for all active watchlist items."""
        db = SessionLocal()
        try:
            # Get all active (not deleted) watchlist items
            items = db.query(WatchlistItem).filter(
                WatchlistItem.is_deleted == False
            ).all()

            if not items:
                logger.warning("No active watchlist items found")
                return

            updated_count = 0
            for item in items:
                changed = False

                # Enable master alert
                if not item.alert_enabled:
                    item.alert_enabled = True
                    changed = True

                # Enable BUY alerts
                if hasattr(item, "buy_alert_enabled") and not item.buy_alert_enabled:
                    item.buy_alert_enabled = True
                    changed = True

                # Enable SELL alerts
                if hasattr(item, "sell_alert_enabled") and not item.sell_alert_enabled:
                    item.sell_alert_enabled = True
                    changed = True

                if changed:
                    updated_count += 1
                    logger.info(f"✅ Enabled alerts for {item.symbol}")

            db.commit()

            logger.info("="*60)
            logger.info(f"✅ Successfully enabled alerts for {updated_count} out of {len(items)} items")
            logger.info("="*60)

            # Show summary
            enabled_master = sum(1 for item in items if item.alert_enabled)
            enabled_buy = sum(1 for item in items if hasattr(item, "buy_alert_enabled") and item.buy_alert_enabled)
            enabled_sell = sum(1 for item in items if hasattr(item, "sell_alert_enabled") and item.sell_alert_enabled)

            logger.info("Summary:")
            logger.info(f"  - Master alert (alert_enabled): {enabled_master}/{len(items)}")
            logger.info(f"  - BUY alerts (buy_alert_enabled): {enabled_buy}/{len(items)}")
            logger.info(f"  - SELL alerts (sell_alert_enabled): {enabled_sell}/{len(items)}")

        except Exception as e:
            logger.error(f"❌ Error enabling alerts: {e}", exc_info=True)
            db.rollback()
            raise
        finally:
            db.close()

    if __name__ == "__main__":
        print("="*60)
        print("Enable All Alerts Script (Fallback)")
        print("="*60)
        print()
        enable_all_alerts()
        print("\\n✅ Script completed!")

except Exception as e:
    print(f"❌ FATAL ERROR: {e}")
    import traceback
    traceback.print_exc()
'''

    try:
        with open('fix_alerts_fallback.py', 'w') as f:
            f.write(script_content)
        print("✅ Script de fallback creado: fix_alerts_fallback.py")
        print()
        print("💡 INSTRUCCIONES PARA EJECUTAR EN EL SERVIDOR:")
        print("   1. Copia el archivo fix_alerts_fallback.py al servidor")
        print("   2. Ejecuta: python3 fix_alerts_fallback.py")
        print("   3. O via Docker: docker exec -it backend-aws python3 fix_alerts_fallback.py")
    except Exception as e:
        print(f"❌ Error creando script de fallback: {e}")

def main():
    print("🔧 SOLUCIÓN: ALERTAS DESACTIVADAS EN EL DASHBOARD")
    print("Este script diagnosticará y solucionará el problema de alertas desactivadas.")
    print()

    # Step 1: Check current status
    api_url, alert_stats = check_alerts_api()

    if alert_stats:
        total_items = alert_stats.get('total_items', 0)
        buy_enabled = alert_stats.get('buy_alerts_enabled', 0)
        sell_enabled = alert_stats.get('sell_alerts_enabled', 0)

        print("\\n📊 ESTADO ACTUAL:")
        print(f"   - Total de items en watchlist: {total_items}")
        print(f"   - Con alertas BUY activadas: {buy_enabled}")
        print(f"   - Con alertas SELL activadas: {sell_enabled}")

        if buy_enabled == 0 and sell_enabled == 0:
            print("   ❌ ¡TODAS LAS ALERTAS ESTÁN DESACTIVADAS!")
        elif buy_enabled < total_items * 0.8 or sell_enabled < total_items * 0.8:
            print("   ⚠️  Muchas alertas están desactivadas")
        else:
            print("   ✅ La mayoría de las alertas están activadas")
            return  # Exit if alerts are mostly enabled

    # Step 2: Try to enable alerts via API
    if api_url:
        print("\\n🔧 INTENTANDO HABILITAR ALERTAS VIA API...")
        success = enable_alerts_via_api(api_url)
        if success:
            print("\\n🎉 ¡PROBLEMA RESUELTO!")
            print("Las alertas deberían estar funcionando ahora en el dashboard.")
            return

    # Step 3: Create fallback script
    print("\\n📝 API no disponible - creando script de fallback...")
    create_fallback_script()

    print("\\n💡 PRÓXIMOS PASOS:")
    print("   1. Ejecuta el script de fallback en el servidor")
    print("   2. Reinicia los servicios si es necesario")
    print("   3. Verifica en el dashboard que las alertas estén activadas")
    print()
    print("🔍 PARA VERIFICAR:")
    print("   - Ve al dashboard")
    print("   - Cada moneda debería tener alertas BUY y SELL activadas")
    print("   - Las alertas deberían aparecer cuando se cumplan las condiciones técnicas")

if __name__ == "__main__":
    main()










