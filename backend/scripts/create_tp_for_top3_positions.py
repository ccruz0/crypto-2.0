#!/usr/bin/env python3
"""
Script para crear TP (+3%) para las 3 posiciones más grandes sin TP
Basado en la última orden de compra. NO crea SL.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.sl_tp_checker import sl_tp_checker_service
from app.services.tp_sl_order_creator import create_take_profit_order
from app.services.portfolio_cache import get_crypto_prices
from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.utils.live_trading import get_live_trading_status
from datetime import datetime, timezone
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    db = SessionLocal()
    try:
        print("🔍 Identificando posiciones sin TP...")
        print("="*70)
        
        # Obtener posiciones sin TP/SL
        result = sl_tp_checker_service.check_positions_for_sl_tp(db)
        positions_missing = result.get('positions_missing_sl_tp', [])
        
        # Filtrar solo las que NO tienen TP (pueden tener SL o no)
        # Excluir las que ya tienen TP activo
        positions_without_tp = []
        for p in positions_missing:
            has_tp = p.get('has_tp', False)
            if not has_tp:
                positions_without_tp.append(p)
        
        # Obtener precios para calcular valores USD
        prices = get_crypto_prices()
        
        # Calcular valor USD para cada posición y ordenar
        for pos in positions_without_tp:
            currency = pos.get('currency', '')
            base_currency = currency.split('_')[0] if '_' in currency else currency
            balance = float(pos.get('balance', 0))
            current_price = prices.get(base_currency, 0)
            pos['usd_value'] = balance * current_price if current_price > 0 else 0
        
        # Ordenar por valor USD descendente y tomar las 3 más grandes
        positions_without_tp.sort(key=lambda x: x.get('usd_value', 0), reverse=True)
        top3 = positions_without_tp[:3]
        
        if not top3:
            print("✅ No hay posiciones sin TP")
            return
        
        print(f"\n📊 Top 3 posiciones sin TP (por valor USD):")
        for i, pos in enumerate(top3, 1):
            symbol = pos.get('symbol', 'N/A')
            usd_value = pos.get('usd_value', 0)
            print(f"   {i}. {symbol}: ${usd_value:,.2f}")
        
        print(f"\n🔄 Creando TP (+3%) para estas 3 posiciones...")
        print("="*70)
        
        live_trading = get_live_trading_status(db)
        print(f"💰 LIVE_TRADING: {live_trading}")
        print()
        
        created_count = 0
        failed_count = 0
        
        for i, pos in enumerate(top3, 1):
            symbol = pos.get('symbol', 'N/A')
            currency = pos.get('currency', 'N/A')
            balance = float(pos.get('balance', 0))
            
            print(f"\n{i}. {symbol} ({currency})")
            print(f"   Balance: {balance:,.8f}")
            
            # Buscar la última orden BUY FILLED para este símbolo
            last_buy_order = db.query(ExchangeOrder).filter(
                ExchangeOrder.symbol == symbol,
                ExchangeOrder.side == OrderSideEnum.BUY,
                ExchangeOrder.status == OrderStatusEnum.FILLED,
                ExchangeOrder.order_type.in_(["LIMIT", "MARKET"])
            ).order_by(ExchangeOrder.exchange_update_time.desc()).first()
            
            if not last_buy_order:
                print(f"   ❌ No se encontró orden de compra FILLED para {symbol}")
                failed_count += 1
                continue
            
            # Obtener precio y cantidad de la orden
            filled_price = float(last_buy_order.avg_price or last_buy_order.price or 0)
            filled_qty = float(last_buy_order.cumulative_quantity or last_buy_order.quantity or 0)
            
            if filled_price <= 0:
                print(f"   ❌ Precio de compra inválido: {filled_price}")
                failed_count += 1
                continue
            
            # Calcular TP a +3%
            tp_price = filled_price * 1.03
            
            print(f"   Última compra:")
            print(f"      Order ID: {last_buy_order.exchange_order_id}")
            print(f"      Precio: ${filled_price:,.6f}")
            print(f"      Cantidad: {filled_qty:,.8f}")
            print(f"      Fecha: {last_buy_order.exchange_update_time}")
            print(f"   TP calculado (+3%): ${tp_price:,.6f}")
            print(f"   Cantidad TP: {balance:,.8f}")
            
            # Verificar si ya existe un TP activo
            existing_tp = db.query(ExchangeOrder).filter(
                ExchangeOrder.symbol == symbol,
                ExchangeOrder.order_role == "TAKE_PROFIT",
                ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
            ).first()
            
            if existing_tp:
                print(f"   ⚠️  Ya existe un TP activo: {existing_tp.exchange_order_id}")
                print(f"      Precio: ${float(existing_tp.price or 0):,.6f}")
                continue
            
            # Crear TP order
            try:
                print(f"   🚀 Creando TP order...")
                tp_result = create_take_profit_order(
                    db=db,
                    symbol=symbol,
                    side="BUY",  # Original order side
                    tp_price=tp_price,
                    quantity=balance,  # Usar balance actual de la posición
                    entry_price=filled_price,
                    parent_order_id=last_buy_order.exchange_order_id,
                    oco_group_id=None,  # No crear OCO (solo TP, no SL)
                    dry_run=not live_trading,
                    source="manual_script"
                )
                
                tp_order_id = tp_result.get("order_id")
                tp_error = tp_result.get("error")
                
                if tp_order_id:
                    print(f"   ✅ TP creado exitosamente!")
                    print(f"      Order ID: {tp_order_id}")
                    created_count += 1
                else:
                    print(f"   ❌ Error creando TP: {tp_error}")
                    failed_count += 1
                    
            except Exception as e:
                print(f"   ❌ Excepción creando TP: {e}")
                logger.error(f"Error creating TP for {symbol}: {e}", exc_info=True)
                failed_count += 1
        
        print(f"\n{'='*70}")
        print(f"📊 Resumen:")
        print(f"   ✅ TP creados: {created_count}")
        print(f"   ❌ Fallidos: {failed_count}")
        print(f"   📋 Total procesadas: {len(top3)}")
        
    finally:
        db.close()

if __name__ == "__main__":
    main()





