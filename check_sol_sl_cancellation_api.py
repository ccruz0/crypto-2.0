#!/usr/bin/env python3
"""
Script alternativo para verificar cancelación de Stop Loss usando la API.
Ejecuta este script cuando el backend esté corriendo.
"""

import requests
import json
from datetime import datetime, timezone

def check_sol_sl_cancellation():
    """Verificar si la orden SL se canceló usando la API"""
    
    print("=" * 80)
    print("VERIFICACIÓN DE CANCELACIÓN DE STOP LOSS PARA SOL_USD (vía API)")
    print("=" * 80)
    print()
    
    # URL de la API (ajusta si es necesario)
    api_base = "http://localhost:8000/api"
    
    try:
        # 1. Obtener órdenes ejecutadas (historial)
        print("📥 Obteniendo historial de órdenes ejecutadas...")
        history_url = f"{api_base}/orders/history"
        params = {"limit": 200, "offset": 0}
        
        response = requests.get(history_url, params=params, timeout=30)
        
        if response.status_code != 200:
            print(f"❌ Error al obtener historial: {response.status_code}")
            print(response.text)
            return
        
        history_data = response.json()
        orders = history_data.get("orders", [])
        
        # Buscar orden TAKE_PROFIT_LIMIT de SOL_USD ejecutada hoy
        today = datetime.now(timezone.utc).date()
        tp_orders = []
        
        for order in orders:
            if (order.get("instrument_name") == "SOL_USD" and
                order.get("order_type") == "TAKE_PROFIT_LIMIT" and
                order.get("status") == "FILLED"):
                
                # Verificar fecha
                update_time = order.get("update_time")
                if update_time:
                    dt = datetime.fromtimestamp(update_time / 1000, tz=timezone.utc)
                    if dt.date() == today:
                        tp_orders.append((dt, order))
        
        if not tp_orders:
            print("⚠️  No se encontró orden TAKE_PROFIT_LIMIT de SOL_USD ejecutada hoy.")
            print("   Buscando la más reciente...")
            
            # Buscar la más reciente sin restricción de fecha
            for order in orders:
                if (order.get("instrument_name") == "SOL_USD" and
                    order.get("order_type") == "TAKE_PROFIT_LIMIT" and
                    order.get("status") == "FILLED"):
                    update_time = order.get("update_time")
                    if update_time:
                        dt = datetime.fromtimestamp(update_time / 1000, tz=timezone.utc)
                        tp_orders.append((dt, order))
                        break
        
        if not tp_orders:
            print("❌ No se encontró ninguna orden TAKE_PROFIT_LIMIT de SOL_USD.")
            return
        
        # Ordenar por fecha (más reciente primero)
        tp_orders.sort(key=lambda x: x[0], reverse=True)
        dt, tp_order = tp_orders[0]
        
        print("✅ Orden TAKE_PROFIT_LIMIT encontrada:")
        print(f"   Order ID: {tp_order.get('order_id')}")
        print(f"   Fecha ejecución: {dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"   Precio: ${tp_order.get('avg_price') or tp_order.get('price')}")
        print(f"   Cantidad: {tp_order.get('quantity')}")
        print()
        
        # 2. Obtener órdenes abiertas
        print("📥 Obteniendo órdenes abiertas...")
        open_orders_url = f"{api_base}/orders/open"
        
        response = requests.get(open_orders_url, timeout=30)
        
        if response.status_code != 200:
            print(f"❌ Error al obtener órdenes abiertas: {response.status_code}")
            print(response.text)
            return
        
        open_data = response.json()
        open_orders = open_data.get("orders", [])
        
        # Buscar órdenes STOP_LIMIT de SOL_USD abiertas
        sl_orders = [
            o for o in open_orders
            if (o.get("instrument_name") == "SOL_USD" and
                o.get("order_type") == "STOP_LIMIT")
        ]
        
        print()
        print("=" * 80)
        print("RESULTADO:")
        print("=" * 80)
        
        if sl_orders:
            print(f"⚠️  ADVERTENCIA: Se encontraron {len(sl_orders)} orden(es) STOP_LIMIT de SOL_USD aún abiertas:")
            print()
            for i, sl_order in enumerate(sl_orders, 1):
                print(f"   Orden SL #{i}:")
                print(f"   Order ID: {sl_order.get('order_id')}")
                print(f"   Precio trigger: ${sl_order.get('price')}")
                print(f"   Cantidad: {sl_order.get('quantity')}")
                print()
            print("⚠️  Estas órdenes deberían haberse cancelado automáticamente.")
            print("   Se recomienda cancelarlas manualmente para evitar ejecuciones no deseadas.")
        else:
            print("✅ No se encontraron órdenes STOP_LIMIT de SOL_USD abiertas.")
            print("   La orden de Stop Loss fue cancelada correctamente (o nunca existió).")
        
    except requests.exceptions.ConnectionError:
        print("❌ No se pudo conectar al backend.")
        print("   Asegúrate de que el backend esté corriendo en http://localhost:8000")
        print("   O ajusta la variable 'api_base' en el script si usa otro puerto.")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_sol_sl_cancellation()







