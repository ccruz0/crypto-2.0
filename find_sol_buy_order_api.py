#!/usr/bin/env python3
"""
Script para encontrar la orden de compra (BUY) original usando la API REST.
Busca la orden de compra que generó las órdenes SL/TP de SOL_USD ejecutadas hoy.
"""

import requests
import json
from datetime import datetime, timezone

def find_buy_order():
    """Buscar orden de compra original usando la API"""
    
    print("=" * 80)
    print("BÚSQUEDA DE ORDEN DE COMPRA ORIGINAL PARA SOL_USD (vía API)")
    print("=" * 80)
    print()
    
    api_base = "http://localhost:8000/api"
    
    try:
        # 1. Obtener órdenes ejecutadas
        print("📥 Obteniendo historial de órdenes ejecutadas...")
        history_url = f"{api_base}/orders/history"
        params = {"limit": 500, "offset": 0}
        
        response = requests.get(history_url, params=params, timeout=30)
        
        if response.status_code != 200:
            print(f"❌ Error al obtener historial: {response.status_code}")
            print(response.text)
            return
        
        history_data = response.json()
        orders = history_data.get("orders", [])
        
        print(f"✅ Obtenidas {len(orders)} órdenes del historial")
        print()
        
        # 2. Buscar orden TAKE_PROFIT_LIMIT de SOL_USD ejecutada hoy
        today = datetime.now(timezone.utc).date()
        tp_orders = []
        
        for order in orders:
            if (order.get("instrument_name") == "SOL_USD" and
                order.get("order_type") == "TAKE_PROFIT_LIMIT" and
                order.get("status") == "FILLED"):
                
                update_time = order.get("update_time")
                if update_time:
                    dt = datetime.fromtimestamp(update_time / 1000, tz=timezone.utc)
                    if dt.date() == today:
                        tp_orders.append((dt, order))
        
        if not tp_orders:
            print("⚠️  No se encontró orden TP de hoy. Buscando la más reciente...")
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
        
        tp_orders.sort(key=lambda x: x[0], reverse=True)
        dt, tp_order = tp_orders[0]
        
        print("✅ Orden TAKE_PROFIT_LIMIT encontrada:")
        print(f"   Order ID: {tp_order.get('order_id')}")
        print(f"   Fecha ejecución: {dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"   Precio ejecución: ${tp_order.get('avg_price') or tp_order.get('price')}")
        print(f"   Cantidad: {tp_order.get('quantity')}")
        print()
        
        # 3. Buscar orden de compra BUY que generó esta TP
        # Nota: La API no expone parent_order_id directamente, así que buscaremos por lógica
        
        print("🔍 Buscando orden de compra (BUY) que generó esta TP...")
        print()
        
        # Buscar órdenes BUY de SOL_USD ejecutadas antes de la TP
        buy_orders = []
        for order in orders:
            if (order.get("instrument_name") == "SOL_USD" and
                order.get("side") == "BUY" and
                order.get("status") == "FILLED" and
                order.get("order_type") in ["LIMIT", "MARKET"]):
                
                create_time = order.get("create_time")
                if create_time:
                    buy_dt = datetime.fromtimestamp(create_time / 1000, tz=timezone.utc)
                    # La compra debe ser anterior a la TP
                    if buy_dt < dt:
                        buy_orders.append((buy_dt, order))
        
        # Ordenar por fecha (más reciente primero)
        buy_orders.sort(key=lambda x: x[0], reverse=True)
        
        if buy_orders:
            print(f"📋 Encontradas {len(buy_orders)} órdenes BUY de SOL_USD ejecutadas antes de la TP:")
            print()
            
            # Buscar la compra más probable (misma cantidad o similar)
            tp_quantity = float(tp_order.get("quantity", 0))
            best_match = None
            best_score = 0
            
            for buy_dt, buy_order in buy_orders[:10]:  # Revisar las 10 más recientes
                buy_quantity = float(buy_order.get("quantity", 0))
                
                # Calcular similitud (misma cantidad = mejor match)
                if buy_quantity > 0:
                    quantity_match = min(tp_quantity, buy_quantity) / max(tp_quantity, buy_quantity)
                    # También considerar proximidad temporal
                    time_diff_hours = abs((dt - buy_dt).total_seconds() / 3600)
                    time_score = max(0, 1 - (time_diff_hours / 168))  # Penalizar si es muy antigua (>1 semana)
                    
                    score = quantity_match * 0.7 + time_score * 0.3
                    
                    if score > best_score:
                        best_score = score
                        best_match = (buy_dt, buy_order)
            
            if best_match:
                buy_dt, buy_order = best_match
                
                print("=" * 80)
                print("✅ ORDEN DE COMPRA ORIGINAL PROBABLE:")
                print("=" * 80)
                print(f"   Order ID: {buy_order.get('order_id')}")
                print(f"   Tipo: {buy_order.get('order_type')}")
                print(f"   Lado: BUY (Compra)")
                print(f"   Estado: FILLED (Ejecutada)")
                print(f"   Precio de compra: ${buy_order.get('avg_price') or buy_order.get('price')}")
                print(f"   Cantidad: {buy_order.get('quantity')}")
                buy_value = float(buy_order.get('cumulative_value', 0)) or (float(buy_order.get('avg_price') or buy_order.get('price', 0)) * float(buy_order.get('quantity', 0)))
                print(f"   Valor total: ${buy_value:.2f}")
                print(f"   Fecha de compra: {buy_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
                print()
                print(f"   Coincidencia: {best_score*100:.1f}% (cantidad y tiempo)")
                print()
                
                # Calcular ganancia
                tp_value = float(tp_order.get('cumulative_value', 0)) or (float(tp_order.get('avg_price') or tp_order.get('price', 0)) * float(tp_order.get('quantity', 0)))
                profit = tp_value - buy_value
                profit_pct = (profit / buy_value * 100) if buy_value > 0 else 0
                
                print("📊 Resumen de la operación completa:")
                print(f"   1. Compra ejecutada: {buy_order.get('order_id')}")
                print(f"      - Precio: ${buy_order.get('avg_price') or buy_order.get('price')}")
                print(f"      - Cantidad: {buy_order.get('quantity')}")
                print(f"      - Fecha: {buy_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
                print()
                print(f"   2. TP ejecutada hoy: {tp_order.get('order_id')}")
                print(f"      - Precio: ${tp_order.get('avg_price') or tp_order.get('price')}")
                print(f"      - Cantidad: {tp_order.get('quantity')}")
                print(f"      - Fecha: {dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
                print()
                print(f"   💰 Ganancia: ${profit:.2f} ({profit_pct:+.2f}%)")
                print()
                print("=" * 80)
                print("CONCLUSIÓN:")
                print("=" * 80)
                print("✅ Esta orden de compra probablemente generó las órdenes SL/TP automáticamente")
                print("   (basado en cantidad similar y proximidad temporal)")
                print()
                print("⚠️  Nota: La API no expone parent_order_id directamente.")
                print("   Para confirmación exacta, ejecuta el script en el contenedor Docker:")
                print("   docker compose exec backend-aws python3 find_sol_buy_order.py")
            else:
                print("⚠️  No se pudo encontrar una orden de compra con cantidad similar.")
        else:
            print("❌ No se encontraron órdenes BUY de SOL_USD ejecutadas antes de la TP.")
            print("   Esto puede significar que la orden de compra es muy antigua o no está en el historial.")
        
    except requests.exceptions.ConnectionError:
        print("❌ No se pudo conectar al backend.")
        print("   Asegúrate de que el backend esté corriendo en http://localhost:8000")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    find_buy_order()







