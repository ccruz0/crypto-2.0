#!/usr/bin/env python3
"""
Script de diagnóstico para verificar el estado del market_updater.py
Verifica:
1. Si el proceso está corriendo
2. Última actualización de datos
3. Comparación con Crypto.com API
4. Estado de las tablas MarketPrice y MarketData
"""

import sys
import os
import requests
from datetime import datetime, timedelta
import subprocess

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import SessionLocal
from app.models.market_price import MarketPrice, MarketData
from app.models.watchlist import WatchlistItem

def check_process_running():
    """Verificar si market_updater está corriendo"""
    print("\n" + "="*80)
    print("1. VERIFICANDO PROCESO market_updater")
    print("="*80)
    
    try:
        # Verificar en Docker
        result = subprocess.run(
            ["docker", "ps", "--filter", "name=market-updater", "--format", "{{.Names}} {{.Status}}"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0 and result.stdout.strip():
            print(f"✅ Proceso Docker encontrado: {result.stdout.strip()}")
            return True
        else:
            print("⚠️  No se encontró proceso Docker 'market-updater'")
            
            # Verificar proceso Python
            result = subprocess.run(
                ["ps", "aux"],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if "run_updater.py" in result.stdout or "market_updater" in result.stdout:
                print("✅ Proceso Python encontrado en ps aux")
                return True
            else:
                print("❌ No se encontró proceso market_updater corriendo")
                return False
    except Exception as e:
        print(f"⚠️  Error verificando proceso: {e}")
        return None

def get_crypto_com_price(symbol: str) -> dict:
    """Obtener precio desde Crypto.com API v1"""
    try:
        url = "https://api.crypto.com/exchange/v1/public/get-tickers"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if "result" in data and "data" in data["result"]:
            for ticker in data["result"]["data"]:
                instrument_name = ticker.get("i", "")
                if instrument_name == symbol:
                    return {
                        "price": float(ticker.get("a", 0)),
                        "timestamp": datetime.now()
                    }
        return None
    except Exception as e:
        print(f"❌ Error obteniendo precio de Crypto.com: {e}")
        return None

def check_database_data(symbol: str = "BTC_USDT"):
    """Verificar datos en la base de datos"""
    print("\n" + "="*80)
    print(f"2. VERIFICANDO DATOS EN BASE DE DATOS para {symbol}")
    print("="*80)
    
    db = SessionLocal()
    try:
        # Verificar MarketPrice
        market_price = db.query(MarketPrice).filter(
            MarketPrice.symbol == symbol
        ).first()
        
        if market_price:
            print(f"✅ MarketPrice encontrado:")
            print(f"   Precio: ${market_price.price:,.2f}" if market_price.price else "   Precio: None")
            print(f"   Fuente: {market_price.source}")
            print(f"   Actualizado: {market_price.updated_at}" if market_price.updated_at else "   Actualizado: None")
            
            if market_price.updated_at:
                age = datetime.now() - market_price.updated_at.replace(tzinfo=None) if market_price.updated_at.tzinfo else datetime.now() - market_price.updated_at
                print(f"   Edad: {age}")
                if age > timedelta(minutes=5):
                    print(f"   ⚠️  ADVERTENCIA: Datos tienen más de 5 minutos de antigüedad")
        else:
            print(f"❌ No se encontró MarketPrice para {symbol}")
        
        # Verificar MarketData
        market_data = db.query(MarketData).filter(
            MarketData.symbol == symbol
        ).first()
        
        if market_data:
            print(f"\n✅ MarketData encontrado:")
            print(f"   Precio: ${market_data.price:,.2f}" if market_data.price else "   Precio: None")
            print(f"   RSI: {market_data.rsi:.2f}" if market_data.rsi else "   RSI: None")
            print(f"   ATR: {market_data.atr:,.2f}" if market_data.atr else "   ATR: None")
            print(f"   MA50: ${market_data.ma50:,.2f}" if market_data.ma50 else "   MA50: None")
            print(f"   MA200: ${market_data.ma200:,.2f}" if market_data.ma200 else "   MA200: None")
            print(f"   Actualizado: {market_data.updated_at}" if market_data.updated_at else "   Actualizado: None")
            
            if market_data.updated_at:
                age = datetime.now() - market_data.updated_at.replace(tzinfo=None) if market_data.updated_at.tzinfo else datetime.now() - market_data.updated_at
                print(f"   Edad: {age}")
                if age > timedelta(minutes=5):
                    print(f"   ⚠️  ADVERTENCIA: Datos tienen más de 5 minutos de antigüedad")
        else:
            print(f"❌ No se encontró MarketData para {symbol}")
        
        # Verificar WatchlistItem
        watchlist_item = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == symbol,
            WatchlistItem.is_deleted == False
        ).first()
        
        if watchlist_item:
            print(f"\n✅ WatchlistItem encontrado:")
            print(f"   Precio: ${watchlist_item.price:,.2f}" if watchlist_item.price else "   Precio: None")
            print(f"   RSI: {watchlist_item.rsi:.2f}" if watchlist_item.rsi else "   RSI: None")
            print(f"   ATR: {watchlist_item.atr:,.2f}" if watchlist_item.atr else "   ATR: None")
            print(f"   Actualizado: {watchlist_item.updated_at}" if hasattr(watchlist_item, 'updated_at') and watchlist_item.updated_at else "   Actualizado: None")
        else:
            print(f"⚠️  No se encontró WatchlistItem para {symbol}")
        
        return {
            "market_price": market_price,
            "market_data": market_data,
            "watchlist_item": watchlist_item
        }
    finally:
        db.close()

def compare_with_crypto_com(symbol: str = "BTC_USDT"):
    """Comparar datos de la BD con Crypto.com API"""
    print("\n" + "="*80)
    print(f"3. COMPARANDO CON CRYPTO.COM API para {symbol}")
    print("="*80)
    
    # Obtener datos de Crypto.com
    crypto_com = get_crypto_com_price(symbol)
    
    if not crypto_com:
        print(f"❌ No se pudo obtener precio de Crypto.com para {symbol}")
        return
    
    print(f"✅ Precio desde Crypto.com: ${crypto_com['price']:,.2f}")
    
    # Obtener datos de la BD
    db = SessionLocal()
    try:
        market_price = db.query(MarketPrice).filter(
            MarketPrice.symbol == symbol
        ).first()
        
        if market_price and market_price.price:
            diff = abs(crypto_com['price'] - market_price.price)
            diff_pct = (diff / crypto_com['price']) * 100
            
            print(f"✅ Precio desde BD: ${market_price.price:,.2f}")
            print(f"   Diferencia: ${diff:,.2f} ({diff_pct:.3f}%)")
            
            if diff_pct < 0.1:
                print(f"   ✅ COINCIDEN (diferencia < 0.1%)")
            elif diff_pct < 1.0:
                print(f"   ⚠️  Diferencia pequeña pero aceptable (< 1%)")
            else:
                print(f"   ❌ NO COINCIDEN (diferencia > 1%)")
        else:
            print(f"❌ No hay precio en BD para comparar")
    finally:
        db.close()

def check_all_symbols():
    """Verificar cuántos símbolos están siendo actualizados"""
    print("\n" + "="*80)
    print("4. ESTADÍSTICAS GENERALES")
    print("="*80)
    
    db = SessionLocal()
    try:
        # Contar MarketPrice entries
        market_price_count = db.query(MarketPrice).count()
        print(f"✅ Total MarketPrice entries: {market_price_count}")
        
        # Contar MarketData entries
        market_data_count = db.query(MarketData).count()
        print(f"✅ Total MarketData entries: {market_data_count}")
        
        # Contar WatchlistItems activos
        watchlist_count = db.query(WatchlistItem).filter(
            WatchlistItem.is_deleted == False
        ).count()
        print(f"✅ Total WatchlistItems activos: {watchlist_count}")
        
        # Verificar última actualización
        latest_price = db.query(MarketPrice).order_by(
            MarketPrice.updated_at.desc()
        ).first()
        
        if latest_price and latest_price.updated_at:
            age = datetime.now() - latest_price.updated_at.replace(tzinfo=None) if latest_price.updated_at.tzinfo else datetime.now() - latest_price.updated_at
            print(f"✅ Última actualización: {latest_price.updated_at} (hace {age})")
            
            if age > timedelta(minutes=10):
                print(f"   ⚠️  ADVERTENCIA: Última actualización hace más de 10 minutos")
        else:
            print(f"❌ No se encontró ninguna actualización reciente")
    finally:
        db.close()

def main():
    """Función principal"""
    print("\n" + "="*80)
    print("🔍 DIAGNÓSTICO DE market_updater.py")
    print("="*80)
    print(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 1. Verificar proceso
    process_running = check_process_running()
    
    # 2. Verificar datos para BTC_USDT
    db_data = check_database_data("BTC_USDT")
    
    # 3. Comparar con Crypto.com
    compare_with_crypto_com("BTC_USDT")
    
    # 4. Estadísticas generales
    check_all_symbols()
    
    # Resumen
    print("\n" + "="*80)
    print("📊 RESUMEN")
    print("="*80)
    
    if process_running:
        print("✅ Proceso market_updater: CORRIENDO")
    elif process_running is False:
        print("❌ Proceso market_updater: NO ESTÁ CORRIENDO")
        print("   💡 Solución: Ejecutar 'python3 run_updater.py' o iniciar el servicio Docker")
    else:
        print("⚠️  Proceso market_updater: NO SE PUDO VERIFICAR")
    
    if db_data.get("market_price"):
        print("✅ Datos en MarketPrice: DISPONIBLES")
    else:
        print("❌ Datos en MarketPrice: NO DISPONIBLES")
    
    if db_data.get("market_data"):
        print("✅ Datos en MarketData: DISPONIBLES")
    else:
        print("❌ Datos en MarketData: NO DISPONIBLES")
    
    print("\n" + "="*80 + "\n")

if __name__ == "__main__":
    main()





