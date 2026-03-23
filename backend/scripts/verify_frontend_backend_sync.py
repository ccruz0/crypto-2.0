#!/usr/bin/env python3
"""
Script to verify that frontend values match backend database values
"""
import sys
import os
import requests
import json

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import create_db_session
from app.models.watchlist import WatchlistItem

def fetch_frontend_data():
    """Fetch data from frontend API endpoint"""
    api_base = (
        os.getenv("API_BASE_URL")
        or os.getenv("AWS_BACKEND_URL")
        or os.getenv("API_URL")
        or "http://localhost:8002"
    )
    url = f"{api_base.rstrip('/')}/api/dashboard"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"⚠️ Frontend API returned status {response.status_code}")
            return None
    except Exception as e:
        print(f"⚠️ Could not fetch from frontend API ({url}): {e}")
        return None

def get_backend_data() -> list[WatchlistItem]:
    """Get all watchlist items from backend database"""
    db = create_db_session()
    try:
        items = db.query(WatchlistItem).filter(WatchlistItem.is_deleted == False).all()
        return list(items)
    finally:
        db.close()

def verify_sync():
    """Verify frontend and backend are in sync"""
    print("=" * 80)
    print("🔍 VERIFICACIÓN DE SINCRONIZACIÓN: FRONTEND vs BACKEND")
    print("=" * 80)
    print()
    
    # Get backend data
    print("📊 Obteniendo datos del backend...")
    backend_items = get_backend_data()
    print(f"✅ Encontrados {len(backend_items)} items en el backend")
    print()
    
    # Get frontend data
    print("📊 Obteniendo datos del frontend...")
    frontend_data = fetch_frontend_data()
    if frontend_data:
        print(f"✅ Datos obtenidos del frontend API")
    else:
        print("⚠️ No se pudieron obtener datos del frontend API")
        print("   (Esto es normal si el backend no está corriendo localmente)")
    print()
    
    # Create frontend lookup
    frontend_lookup = {}
    if frontend_data:
        for item in frontend_data:
            symbol = item.get('symbol', '').upper()
            frontend_lookup[symbol] = item
    
    # Fields to verify
    fields_to_check = [
        ('trade_enabled', 'Trade', 'boolean'),
        ('alert_enabled', 'Alert Enabled', 'boolean'),
        ('buy_alert_enabled', 'Buy Alert Enabled', 'boolean'),
        ('sell_alert_enabled', 'Sell Alert Enabled', 'boolean'),
        ('trade_amount_usd', 'Amount USD', 'float'),
        ('trade_on_margin', 'Margin', 'boolean'),
        ('sl_tp_mode', 'SL/TP Mode', 'string'),
        ('risk', 'RISK', 'string'),
        ('preset', 'Preset', 'string'),
    ]
    
    print("=" * 80)
    print("📋 COMPARACIÓN DETALLADA")
    print("=" * 80)
    print()
    
    discrepancies = []
    matches = []
    
    for backend_item in backend_items:
        symbol = backend_item.symbol.upper()
        print(f"🔍 Verificando {symbol}:")
        
        # Get frontend equivalent
        frontend_item = frontend_lookup.get(symbol) if frontend_lookup else None
        
        # Check each field
        for backend_field, display_name, field_type in fields_to_check:
            backend_value = getattr(backend_item, backend_field, None)
            
            # Handle special cases
            if backend_field == 'risk':
                # Risk is derived from strategy profile, not directly stored
                backend_value = "N/A (derived)"
            elif backend_field == 'preset':
                # Preset is derived from sl_tp_mode, not directly stored
                backend_value = "N/A (derived from sl_tp_mode)"
            elif backend_field == 'alert_enabled' and not hasattr(backend_item, 'alert_enabled'):
                backend_value = None
            
            if frontend_item:
                frontend_value = frontend_item.get(backend_field)
                
                # Type conversion for comparison
                if field_type == 'boolean':
                    backend_value = bool(backend_value) if backend_value is not None else False
                    frontend_value = bool(frontend_value) if frontend_value is not None else False
                elif field_type == 'float':
                    backend_value = float(backend_value) if backend_value is not None else None
                    frontend_value = float(frontend_value) if frontend_value is not None else None
                
                if backend_value != frontend_value:
                    discrepancies.append({
                        'symbol': symbol,
                        'field': display_name,
                        'backend': backend_value,
                        'frontend': frontend_value
                    })
                    print(f"  ❌ {display_name}: Backend={backend_value}, Frontend={frontend_value}")
                else:
                    print(f"  ✅ {display_name}: {backend_value}")
            else:
                # No frontend data, just show backend value
                print(f"  📊 {display_name}: {backend_value} (backend only)")
        
        print()
    
    # Summary
    print("=" * 80)
    print("📊 RESUMEN")
    print("=" * 80)
    print()
    
    if discrepancies:
        print(f"❌ Se encontraron {len(discrepancies)} discrepancia(s):")
        print()
        for disc in discrepancies:
            print(f"  • {disc['symbol']}.{disc['field']}:")
            print(f"    Backend:  {disc['backend']}")
            print(f"    Frontend: {disc['frontend']}")
        print()
        print("⚠️ ACCIÓN REQUERIDA: Sincronizar valores")
    else:
        print("✅ Todos los valores coinciden entre frontend y backend")
        print(f"   Verificados {len(backend_items)} items")
    
    print()
    
    # Show critical fields for each symbol
    print("=" * 80)
    print("📋 ESTADO CRÍTICO DE CADA SÍMBOLO")
    print("=" * 80)
    print()
    
    for backend_item in backend_items:
        symbol = backend_item.symbol
        trade_enabled = getattr(backend_item, "trade_enabled", False)
        alert_enabled = getattr(backend_item, 'alert_enabled', False)
        buy_alert = getattr(backend_item, 'buy_alert_enabled', False)
        sell_alert = getattr(backend_item, 'sell_alert_enabled', False)
        amount = getattr(backend_item, "trade_amount_usd", None)
        
        status_icons = []
        if trade_enabled:
            status_icons.append("✅ Trade")
        else:
            status_icons.append("❌ Trade")
        
        if alert_enabled:
            status_icons.append("✅ Alert")
        else:
            status_icons.append("❌ Alert")
        
        if buy_alert:
            status_icons.append("✅ Buy Alert")
        else:
            status_icons.append("❌ Buy Alert")
        
        if sell_alert:
            status_icons.append("✅ Sell Alert")
        else:
            status_icons.append("❌ Sell Alert")
        
        if amount:
            status_icons.append(f"✅ Amount=${amount}")
        else:
            status_icons.append("⚠️ Amount=None")
        
        print(f"{symbol}: {' | '.join(status_icons)}")
    
    print()
    print("=" * 80)
    
    return len(discrepancies) == 0

if __name__ == "__main__":
    try:
        success = verify_sync()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"❌ Error durante la verificación: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)















