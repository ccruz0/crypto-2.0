#!/usr/bin/env python3
"""
Script de diagnóstico completo para simular alertas y detectar por qué no se crean órdenes.
Diagnostica: trade_enabled, trade_amount_usd, límites de órdenes, errores en creación, etc.
"""

import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderSideEnum
from datetime import datetime, timezone
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def check_watchlist_item(db: Session, symbol: str) -> dict:
    """Verifica la configuración del watchlist item"""
    logger.info(f"\n{'='*60}")
    logger.info(f"1. VERIFICANDO CONFIGURACIÓN DE {symbol}")
    logger.info(f"{'='*60}")
    
    watchlist_item = db.query(WatchlistItem).filter(
        WatchlistItem.symbol == symbol
    ).first()
    
    if not watchlist_item:
        logger.error(f"❌ {symbol} NO encontrado en watchlist")
        return {
            "exists": False,
            "trade_enabled": None,
            "trade_amount_usd": None,
            "alert_enabled": None,
        }
    
    logger.info(f"✅ {symbol} encontrado en watchlist")
    logger.info(f"   ID: {watchlist_item.id}")
    logger.info(f"   Exchange: {watchlist_item.exchange}")
    logger.info(f"   is_deleted: {watchlist_item.is_deleted}")
    logger.info(f"   alert_enabled: {watchlist_item.alert_enabled}")
    logger.info(f"   buy_alert_enabled: {getattr(watchlist_item, 'buy_alert_enabled', None)}")
    logger.info(f"   sell_alert_enabled: {getattr(watchlist_item, 'sell_alert_enabled', None)}")
    logger.info(f"   trade_enabled: {watchlist_item.trade_enabled}")
    logger.info(f"   trade_amount_usd: {watchlist_item.trade_amount_usd}")
    logger.info(f"   trade_on_margin: {watchlist_item.trade_on_margin}")
    logger.info(f"   sl_tp_mode: {watchlist_item.sl_tp_mode}")
    
    # Diagnóstico
    issues = []
    if not watchlist_item.trade_enabled:
        issues.append("❌ trade_enabled = False (la orden NO se creará)")
    if not watchlist_item.trade_amount_usd or watchlist_item.trade_amount_usd <= 0:
        issues.append(f"❌ trade_amount_usd = {watchlist_item.trade_amount_usd} (debe ser > 0)")
    if not watchlist_item.alert_enabled:
        issues.append("⚠️ alert_enabled = False (las alertas están deshabilitadas)")
    
    if issues:
        logger.warning("\n⚠️ PROBLEMAS DETECTADOS:")
        for issue in issues:
            logger.warning(f"   {issue}")
    else:
        logger.info("\n✅ CONFIGURACIÓN CORRECTA para creación de órdenes")
    
    return {
        "exists": True,
        "trade_enabled": watchlist_item.trade_enabled,
        "trade_amount_usd": watchlist_item.trade_amount_usd,
        "alert_enabled": watchlist_item.alert_enabled,
        "buy_alert_enabled": getattr(watchlist_item, 'buy_alert_enabled', None),
        "issues": issues,
    }


def check_open_orders(db: Session, symbol: str) -> dict:
    """Verifica órdenes abiertas para el símbolo y globalmente"""
    logger.info(f"\n{'='*60}")
    logger.info(f"2. VERIFICANDO ÓRDENES ABIERTAS")
    logger.info(f"{'='*60}")
    
    # Órdenes abiertas para este símbolo
    open_statuses = [OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED]
    
    symbol_orders = db.query(ExchangeOrder).filter(
        ExchangeOrder.symbol == symbol,
        ExchangeOrder.side == OrderSideEnum.BUY,
        ExchangeOrder.status.in_(open_statuses)
    ).all()
    
    logger.info(f"📊 Órdenes abiertas para {symbol}: {len(symbol_orders)}")
    for order in symbol_orders:
        logger.info(f"   - Order ID: {order.order_id}, Status: {order.status.value}, Amount: ${order.quantity * order.price if order.quantity and order.price else 'N/A'}")
    
    # Órdenes abiertas globales (BUY)
    total_open_orders = db.query(ExchangeOrder).filter(
        ExchangeOrder.side == OrderSideEnum.BUY,
        ExchangeOrder.status.in_(open_statuses)
    ).count()
    
    logger.info(f"📊 Total órdenes BUY abiertas (global): {total_open_orders}")
    
    # Verificar límites
    MAX_OPEN_ORDERS_PER_SYMBOL = 3
    issues = []
    
    if len(symbol_orders) >= MAX_OPEN_ORDERS_PER_SYMBOL:
        issues.append(f"❌ Límite de órdenes para {symbol} alcanzado: {len(symbol_orders)}/{MAX_OPEN_ORDERS_PER_SYMBOL}")
    
    if total_open_orders >= 10:  # Límite global aproximado
        issues.append(f"⚠️ Muchas órdenes abiertas globalmente: {total_open_orders}")
    
    if issues:
        logger.warning("\n⚠️ LÍMITES:")
        for issue in issues:
            logger.warning(f"   {issue}")
    else:
        logger.info("\n✅ LÍMITES OK")
    
    return {
        "symbol_count": len(symbol_orders),
        "total_count": total_open_orders,
        "max_per_symbol": MAX_OPEN_ORDERS_PER_SYMBOL,
        "issues": issues,
    }


def check_recent_orders(db: Session, symbol: str, minutes: int = 5) -> dict:
    """Verifica órdenes recientes (últimos N minutos)"""
    logger.info(f"\n{'='*60}")
    logger.info(f"3. VERIFICANDO ÓRDENES RECIENTES (últimos {minutes} minutos)")
    logger.info(f"{'='*60}")
    
    from datetime import timedelta
    threshold = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    
    recent_orders = db.query(ExchangeOrder).filter(
        ExchangeOrder.symbol == symbol,
        ExchangeOrder.side == OrderSideEnum.BUY,
        ExchangeOrder.created_at >= threshold
    ).all()
    
    logger.info(f"📊 Órdenes BUY recientes para {symbol}: {len(recent_orders)}")
    for order in recent_orders:
        logger.info(f"   - Order ID: {order.order_id}, Created: {order.created_at}, Status: {order.status.value}")
    
    if len(recent_orders) > 0:
        logger.warning(f"⚠️ Hay {len(recent_orders)} orden(es) reciente(s) - esto puede bloquear nuevas órdenes por cooldown")
    
    return {
        "count": len(recent_orders),
        "orders": [{"order_id": o.order_id, "created_at": str(o.created_at), "status": o.status.value} for o in recent_orders],
    }


def check_portfolio_value(db: Session, symbol: str, current_price: float = None) -> dict:
    """Verifica el valor en cartera para el símbolo"""
    logger.info(f"\n{'='*60}")
    logger.info(f"4. VERIFICANDO VALOR EN CARTERA")
    logger.info(f"{'='*60}")
    
    try:
        from app.services.order_position_service import calculate_portfolio_value_for_symbol
        
        if not current_price:
            logger.warning("   ⚠️ No se proporcionó precio actual, usando precio de prueba $100")
            current_price = 100.0
        
        portfolio_value, net_quantity = calculate_portfolio_value_for_symbol(db, symbol, current_price)
        
        logger.info(f"💰 Valor en cartera para {symbol}: ${portfolio_value:.2f}")
        logger.info(f"📊 Cantidad neta: {net_quantity:.4f}")
        
        # Obtener trade_amount_usd para calcular el límite
        watchlist_item = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == symbol
        ).first()
        
        if watchlist_item and watchlist_item.trade_amount_usd:
            limit_value = 3 * watchlist_item.trade_amount_usd
            logger.info(f"📊 Límite de cartera: ${limit_value:.2f} (3x trade_amount_usd=${watchlist_item.trade_amount_usd})")
            
            if portfolio_value > limit_value:
                logger.warning(f"❌ VALOR EN CARTERA EXCEDE LÍMITE: ${portfolio_value:.2f} > ${limit_value:.2f}")
                logger.warning(f"   La orden NO se creará si el valor excede 3x trade_amount_usd")
                return {
                    "portfolio_value": portfolio_value,
                    "limit_value": limit_value,
                    "exceeds_limit": True,
                    "issue": f"Portfolio value ${portfolio_value:.2f} > limit ${limit_value:.2f}",
                }
            else:
                logger.info(f"✅ Valor en cartera OK: ${portfolio_value:.2f} <= ${limit_value:.2f}")
        
        return {
            "portfolio_value": portfolio_value,
            "net_quantity": net_quantity,
            "exceeds_limit": False,
        }
    except Exception as e:
        logger.error(f"❌ Error calculando valor en cartera: {e}")
        return {
            "error": str(e),
        }


def simulate_alert_diagnosis(db: Session, symbol: str):
    """Diagnóstico completo para simular alerta"""
    logger.info(f"\n{'#'*60}")
    logger.info(f"DIAGNÓSTICO COMPLETO PARA SIMULAR ALERTA: {symbol}")
    logger.info(f"{'#'*60}\n")
    
    # 1. Verificar watchlist item
    watchlist_info = check_watchlist_item(db, symbol)
    
    if not watchlist_info["exists"]:
        logger.error(f"\n❌ CONCLUSIÓN: {symbol} no está en watchlist. No se puede crear orden.")
        return
    
    # 2. Verificar órdenes abiertas
    orders_info = check_open_orders(db, symbol)
    
    # 3. Verificar órdenes recientes
    recent_info = check_recent_orders(db, symbol)
    
    # 4. Verificar valor en cartera
    portfolio_info = check_portfolio_value(db, symbol)
    
    # 5. Resumen y recomendaciones
    logger.info(f"\n{'='*60}")
    logger.info(f"RESUMEN Y DIAGNÓSTICO")
    logger.info(f"{'='*60}\n")
    
    all_issues = []
    
    if watchlist_info.get("issues"):
        all_issues.extend(watchlist_info["issues"])
    
    if orders_info.get("issues"):
        all_issues.extend(orders_info["issues"])
    
    if recent_info["count"] > 0:
        all_issues.append(f"⚠️ Hay {recent_info['count']} orden(es) reciente(s) - puede bloquear creación por cooldown")
    
    if portfolio_info.get("exceeds_limit"):
        all_issues.append(portfolio_info.get("issue", "Valor en cartera excede límite"))
    
    if all_issues:
        logger.error("❌ PROBLEMAS ENCONTRADOS QUE IMPIDEN LA CREACIÓN DE ÓRDENES:\n")
        for issue in all_issues:
            logger.error(f"   {issue}")
        
        logger.info("\n💡 RECOMENDACIONES:")
        
        if not watchlist_info["trade_enabled"]:
            logger.info("   1. Habilita 'Trade' = YES para {symbol} en el Dashboard")
        if not watchlist_info["trade_amount_usd"] or watchlist_info["trade_amount_usd"] <= 0:
            logger.info(f"   2. Configura 'Amount USD' > 0 para {symbol} en el Dashboard")
        if orders_info["symbol_count"] >= orders_info["max_per_symbol"]:
            logger.info(f"   3. Espera a que se completen algunas órdenes abiertas para {symbol}")
        if portfolio_info.get("exceeds_limit"):
            logger.info("   4. Espera a que el valor en cartera disminuya o aumenta trade_amount_usd")
    else:
        logger.info("✅ NO SE ENCONTRARON PROBLEMAS OBVIOS")
        logger.info("   La configuración parece correcta para crear órdenes.")
        logger.info("   Si la orden no se crea, revisa los logs del backend para errores específicos.")
        logger.info("   Busca mensajes que contengan:")
        logger.info("   - '[Background] Error creating order'")
        logger.info("   - 'Order creation returned None'")
        logger.info("   - 'SEGURIDAD 2/2'")
        logger.info("   - 'BLOCKED at final check'")


if __name__ == "__main__":
    symbol = sys.argv[1] if len(sys.argv) > 1 else "AAVE_USDT"
    symbol = symbol.upper()
    
    db = SessionLocal()
    try:
        simulate_alert_diagnosis(db, symbol)
    finally:
        db.close()

