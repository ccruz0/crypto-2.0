#!/usr/bin/env python3
"""
Script para probar diferentes variaciones de orden SELL hasta encontrar una que funcione
"""
import os
import sys
import time
import logging
from decimal import Decimal

# Agregar el directorio backend al path
# Intentar diferentes rutas posibles
possible_paths = [
    os.path.join(os.path.dirname(__file__), 'backend'),
    '/app',  # Ruta dentro del contenedor Docker
    '/workspace/backend',  # Ruta alternativa en contenedor
    os.path.dirname(__file__)  # Directorio actual
]
for path in possible_paths:
    if os.path.exists(path):
        sys.path.insert(0, path)
        break

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_sell_order_variations():
    """Probar diferentes variaciones de orden SELL"""
    
    # Importar después de configurar el path
    from app.services.brokers.crypto_com_trade import CryptoComTradeClient
    
    # Inicializar cliente
    trade_client = CryptoComTradeClient()
    
    # Parámetros base del error reportado
    symbol_base = "BTC_USD"
    amount_usd = 10.00
    quantity = 0.00011119
    
    # Obtener precio actual para calcular cantidad correcta
    logger.info("🔍 Obteniendo precio actual de BTC...")
    try:
        import requests
        ticker_url = "https://api.crypto.com/exchange/v1/public/get-tickers"
        response = requests.get(ticker_url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if "result" in data and "data" in data["result"]:
                for ticker in data["result"]["data"]:
                    inst = ticker.get("i", "")
                    if inst in ["BTC_USD", "BTCUSDT", "BTC_USDT"]:
                        current_price = float(ticker.get("a", 0))
                        if current_price > 0:
                            logger.info(f"✅ Precio actual de BTC: ${current_price:,.2f}")
                            # Recalcular cantidad basada en precio actual
                            quantity = amount_usd / current_price
                            logger.info(f"📦 Cantidad recalculada: {quantity:.8f}")
                            break
    except Exception as e:
        logger.warning(f"⚠️ No se pudo obtener precio actual: {e}")
        logger.info(f"📦 Usando cantidad original: {quantity:.8f}")
    
    # Variaciones a probar
    variations = [
        {
            "name": "BTC_USD - Cantidad original",
            "symbol": "BTC_USD",
            "qty": quantity,
            "is_margin": False,
            "leverage": None
        },
        {
            "name": "BTC_USDT - Cantidad original",
            "symbol": "BTC_USDT",
            "qty": quantity,
            "is_margin": False,
            "leverage": None
        },
        {
            "name": "BTC_USD - Cantidad redondeada a 5 decimales",
            "symbol": "BTC_USD",
            "qty": round(quantity, 5),
            "is_margin": False,
            "leverage": None
        },
        {
            "name": "BTC_USDT - Cantidad redondeada a 5 decimales",
            "symbol": "BTC_USDT",
            "qty": round(quantity, 5),
            "is_margin": False,
            "leverage": None
        },
        {
            "name": "BTC_USD - Cantidad redondeada a 8 decimales",
            "symbol": "BTC_USD",
            "qty": round(quantity, 8),
            "is_margin": False,
            "leverage": None
        },
        {
            "name": "BTC_USDT - Cantidad redondeada a 8 decimales",
            "symbol": "BTC_USDT",
            "qty": round(quantity, 8),
            "is_margin": False,
            "leverage": None
        },
        {
            "name": "BTC_USD - Cantidad mínima (0.0001)",
            "symbol": "BTC_USD",
            "qty": 0.0001,
            "is_margin": False,
            "leverage": None
        },
        {
            "name": "BTC_USDT - Cantidad mínima (0.0001)",
            "symbol": "BTC_USDT",
            "qty": 0.0001,
            "is_margin": False,
            "leverage": None
        },
        {
            "name": "BTC_USD - Con margin trading (leverage 10x)",
            "symbol": "BTC_USD",
            "qty": quantity,
            "is_margin": True,
            "leverage": 10
        },
        {
            "name": "BTC_USDT - Con margin trading (leverage 10x)",
            "symbol": "BTC_USDT",
            "qty": quantity,
            "is_margin": True,
            "leverage": 10
        },
    ]
    
    logger.info("=" * 80)
    logger.info("🧪 INICIANDO PRUEBAS DE ÓRDENES SELL")
    logger.info("=" * 80)
    logger.info(f"💰 Monto objetivo: ${amount_usd:,.2f}")
    logger.info(f"📦 Cantidad base: {quantity:.8f}")
    logger.info(f"🔢 Total de variaciones a probar: {len(variations)}")
    logger.info("")
    
    successful_orders = []
    failed_orders = []
    
    for i, variation in enumerate(variations, 1):
        logger.info("")
        logger.info("-" * 80)
        logger.info(f"🧪 Prueba {i}/{len(variations)}: {variation['name']}")
        logger.info("-" * 80)
        logger.info(f"   Símbolo: {variation['symbol']}")
        logger.info(f"   Cantidad: {variation['qty']:.8f}")
        logger.info(f"   Margin: {variation['is_margin']}")
        if variation['is_margin']:
            logger.info(f"   Leverage: {variation['leverage']}x")
        
        try:
            # Intentar crear la orden
            result = trade_client.place_market_order(
                symbol=variation['symbol'],
                side="SELL",
                qty=variation['qty'],
                is_margin=variation['is_margin'],
                leverage=variation['leverage'],
                dry_run=False  # Orden real
            )
            
            # Verificar resultado
            if result and "error" not in result:
                order_id = result.get("order_id") or result.get("client_order_id")
                logger.info(f"✅ ✅ ✅ ÉXITO! Orden creada: {order_id}")
                logger.info(f"   Resultado: {result}")
                successful_orders.append({
                    "variation": variation['name'],
                    "order_id": order_id,
                    "result": result
                })
                # Si encontramos una que funciona, podemos continuar probando o parar
                logger.info("")
                logger.info("🎉 ¡ORDEN CREADA EXITOSAMENTE!")
                logger.info("   Esta variación funcionó:")
                logger.info(f"   - Símbolo: {variation['symbol']}")
                logger.info(f"   - Cantidad: {variation['qty']:.8f}")
                logger.info(f"   - Margin: {variation['is_margin']}")
                if variation['is_margin']:
                    logger.info(f"   - Leverage: {variation['leverage']}x")
                break  # Parar después del primer éxito
            else:
                error_msg = result.get("error", "Unknown error") if result else "No response"
                logger.error(f"❌ Falla: {error_msg}")
                failed_orders.append({
                    "variation": variation['name'],
                    "error": error_msg
                })
                
        except Exception as e:
            logger.error(f"❌ Excepción: {str(e)}")
            failed_orders.append({
                "variation": variation['name'],
                "error": str(e)
            })
        
        # Esperar un poco entre intentos para evitar rate limiting
        if i < len(variations):
            logger.info("   ⏳ Esperando 2 segundos antes del siguiente intento...")
            time.sleep(2)
    
    # Resumen final
    logger.info("")
    logger.info("=" * 80)
    logger.info("📊 RESUMEN FINAL")
    logger.info("=" * 80)
    logger.info(f"✅ Órdenes exitosas: {len(successful_orders)}")
    logger.info(f"❌ Órdenes fallidas: {len(failed_orders)}")
    
    if successful_orders:
        logger.info("")
        logger.info("🎉 VARIACIONES EXITOSAS:")
        for success in successful_orders:
            logger.info(f"   ✅ {success['variation']}")
            logger.info(f"      Order ID: {success['order_id']}")
    else:
        logger.info("")
        logger.info("❌ TODAS LAS VARIACIONES FALLARON")
        logger.info("")
        logger.info("Errores encontrados:")
        for failure in failed_orders[:5]:  # Mostrar solo los primeros 5
            logger.info(f"   ❌ {failure['variation']}: {failure['error']}")
    
    return successful_orders, failed_orders

if __name__ == "__main__":
    try:
        successful, failed = test_sell_order_variations()
        sys.exit(0 if successful else 1)
    except KeyboardInterrupt:
        logger.info("\n⚠️ Prueba interrumpida por el usuario")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Error fatal: {e}", exc_info=True)
        sys.exit(1)

