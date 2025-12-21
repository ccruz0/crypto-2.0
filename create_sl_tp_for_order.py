#!/usr/bin/env python3
"""
Script para crear órdenes SL/TP para una orden específica
"""
import os
import sys
import requests
import time

# Configuración
# Intentar diferentes URLs posibles
API_BASE_URL = os.getenv("API_BASE_URL") or os.getenv("API_BASE_URL_INTERNAL") or "http://localhost:8002"
ORDER_ID = "5755600480818690399"  # Order ID de la orden SELL creada

def create_sl_tp_for_order(order_id: str):
    """Crear órdenes SL/TP para una orden específica"""
    
    print("=" * 80)
    print("🛡️ CREAR ÓRDENES SL/TP")
    print("=" * 80)
    print(f"📋 Order ID: {order_id}")
    print(f"🌐 API URL: {API_BASE_URL}")
    print()
    
    # Endpoint para crear SL/TP
    url = f"{API_BASE_URL}/api/orders/create-sl-tp/{order_id}"
    
    print(f"🔗 Endpoint: {url}")
    print()
    print("⏳ Enviando solicitud...")
    
    try:
        response = requests.post(url, timeout=30)
        
        print(f"📡 Status Code: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print()
            print("✅ ✅ ✅ ÉXITO! Órdenes SL/TP creadas")
            print()
            print("📊 Detalles:")
            print(f"   Order ID: {data.get('order_id')}")
            print(f"   Symbol: {data.get('symbol')}")
            print(f"   Side: {data.get('side')}")
            print(f"   Filled Price: ${data.get('filled_price', 0):,.4f}")
            print(f"   Filled Quantity: {data.get('filled_qty', 0):.8f}")
            print()
            
            created_sl_tp = data.get('created_sl_tp', [])
            if created_sl_tp:
                print(f"🛡️ Órdenes de Protección Creadas: {len(created_sl_tp)}")
                print()
                for order in created_sl_tp:
                    role = order.get('order_role', 'UNKNOWN')
                    order_id_sl_tp = order.get('order_id', 'N/A')
                    status = order.get('status', 'UNKNOWN')
                    price = order.get('price')
                    quantity = order.get('quantity')
                    
                    emoji = "🛑" if role == "STOP_LOSS" else "🎯"
                    print(f"   {emoji} {role}:")
                    print(f"      Order ID: {order_id_sl_tp}")
                    print(f"      Status: {status}")
                    if price:
                        print(f"      Price: ${price:,.4f}")
                    if quantity:
                        print(f"      Quantity: {quantity:.8f}")
                    print()
            else:
                print("⚠️ No se crearon órdenes SL/TP (puede que ya existan)")
            
            print(f"💬 Mensaje: {data.get('message', 'N/A')}")
            return True
            
        elif response.status_code == 404:
            print()
            print("❌ Error: Orden no encontrada")
            print(f"   La orden {order_id} no existe en la base de datos")
            print()
            print("💡 Posibles causas:")
            print("   - La orden aún no se ha sincronizado desde Crypto.com")
            print("   - El order_id es incorrecto")
            print("   - La orden no está en la base de datos")
            return False
            
        elif response.status_code == 400:
            error_data = response.json()
            detail = error_data.get('detail', 'Unknown error')
            print()
            print(f"❌ Error: {detail}")
            print()
            
            if "not FILLED" in detail:
                print("💡 La orden debe estar FILLED para crear SL/TP")
                print("   Espera a que la orden se ejecute completamente")
            elif "already has" in detail:
                print("💡 La orden ya tiene órdenes SL/TP")
            return False
            
        else:
            print()
            print(f"❌ Error: HTTP {response.status_code}")
            try:
                error_data = response.json()
                print(f"   Detalle: {error_data}")
            except:
                print(f"   Respuesta: {response.text[:200]}")
            return False
            
    except requests.exceptions.RequestException as e:
        print()
        print(f"❌ Error de conexión: {e}")
        return False
    except Exception as e:
        print()
        print(f"❌ Error inesperado: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    # Permitir pasar order_id como argumento
    order_id = sys.argv[1] if len(sys.argv) > 1 else ORDER_ID
    
    success = create_sl_tp_for_order(order_id)
    sys.exit(0 if success else 1)

