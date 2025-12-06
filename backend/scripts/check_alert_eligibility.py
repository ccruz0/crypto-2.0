#!/usr/bin/env python3
"""Script to check which coins should receive BUY alerts based on new portfolio value logic.

New logic: Block BUY alerts and orders if portfolio value > 3x trade_amount_usd
If trade_amount_usd is null, use 100 USD as default.
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.services.order_position_service import count_open_positions_for_symbol
from app.services.trading_signals import calculate_trading_signals
from app.services.strategy_profiles import resolve_strategy_profile
from price_fetcher import get_price_with_fallback
from types import SimpleNamespace

def calculate_portfolio_value_for_symbol(db, symbol: str, current_price: float) -> float:
    """
    Calculate portfolio value (USD) for a symbol based on net quantity * current_price.
    
    Uses the same logic as order_position_service to get net quantity.
    """
    from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
    from sqlalchemy import or_
    
    # Normalize symbol filter
    if "_" in symbol:
        symbol_filter = ExchangeOrder.symbol == symbol
    else:
        symbol_filter = or_(
            ExchangeOrder.symbol == symbol,
            ExchangeOrder.symbol.like(f"{symbol}_%"),
        )
    
    # Get filled BUY orders
    from sqlalchemy import not_
    main_role_filter = or_(
        ExchangeOrder.order_role.is_(None),
        not_(ExchangeOrder.order_role.in_(["STOP_LOSS", "TAKE_PROFIT"])),
    )
    
    filled_buy_orders = (
        db.query(ExchangeOrder)
        .filter(
            symbol_filter,
            ExchangeOrder.side == OrderSideEnum.BUY,
            ExchangeOrder.status == OrderStatusEnum.FILLED,
            main_role_filter,
        )
        .all()
    )
    
    filled_buy_qty = sum(
        float(o.cumulative_quantity or o.quantity or 0) for o in filled_buy_orders
    )
    
    # Get filled SELL orders
    filled_sell_orders = (
        db.query(ExchangeOrder)
        .filter(
            symbol_filter,
            ExchangeOrder.side == OrderSideEnum.SELL,
            ExchangeOrder.status == OrderStatusEnum.FILLED,
            or_(
                ExchangeOrder.order_role.is_(None),
                ExchangeOrder.order_role == "STOP_LOSS",
                ExchangeOrder.order_role == "TAKE_PROFIT",
            ),
        )
        .all()
    )
    
    filled_sell_qty = sum(
        float(o.cumulative_quantity or o.quantity or 0) for o in filled_sell_orders
    )
    
    # Calculate net quantity
    net_quantity = max(filled_buy_qty - filled_sell_qty, 0.0)
    
    # Calculate portfolio value
    portfolio_value = net_quantity * current_price
    
    return portfolio_value, net_quantity

def main():
    print("=" * 100)
    print("📊 VERIFICACIÓN DE ELEGIBILIDAD PARA ALERTAS BUY")
    print("=" * 100)
    print("Lógica: Bloquear alertas BUY si valor_en_cartera > 3x trade_amount_usd")
    print("Si trade_amount_usd es null, usar 100 USD como default")
    print("=" * 100)
    print()
    
    db = SessionLocal()
    try:
        # Get all watchlist items with alert_enabled=True
        watchlist_items = (
            db.query(WatchlistItem)
            .filter(WatchlistItem.alert_enabled == True)
            .filter(WatchlistItem.is_deleted == False)
            .all()
        )
        
        if not watchlist_items:
            print("❌ No se encontraron monedas con alert_enabled=True")
            return
        
        print(f"✅ Encontradas {len(watchlist_items)} monedas con alert_enabled=True\n")
        print("-" * 100)
        
        results = []
        
        for item in watchlist_items:
            symbol = item.symbol
            if not symbol:
                continue
            
            try:
                # Get current price and indicators
                result = get_price_with_fallback(symbol, "15m")
                current_price = result.get('price', 0)
                
                if not current_price or current_price <= 0:
                    results.append({
                        'symbol': symbol,
                        'status': 'NO_PRICE',
                        'reason': 'Sin datos de precio'
                    })
                    continue
                
                # Get trade_amount_usd (default 100 if null)
                trade_amount_usd = item.trade_amount_usd if item.trade_amount_usd and item.trade_amount_usd > 0 else 100.0
                
                # Calculate portfolio value
                portfolio_value, net_quantity = calculate_portfolio_value_for_symbol(db, symbol, current_price)
                
                # Calculate limit (3x trade_amount_usd)
                limit_value = 3 * trade_amount_usd
                
                # Check if portfolio value exceeds limit
                exceeds_limit = portfolio_value > limit_value
                
                # Get indicators for signal calculation
                rsi = result.get('rsi')
                ma50 = result.get('ma50')
                ma200 = result.get('ma200')
                ema10 = result.get('ma10')
                
                # Resolve strategy profile
                strategy_type, risk_approach = resolve_strategy_profile(symbol, db, item)
                
                # Calculate trading signals
                signals = calculate_trading_signals(
                    symbol=symbol,
                    price=current_price,
                    rsi=rsi,
                    ma50=ma50,
                    ma200=ma200,
                    ema10=ema10,
                    strategy_type=strategy_type,
                    risk_approach=risk_approach,
                )
                
                buy_signal = signals.get('buy_signal', False)
                
                # Determine eligibility
                if exceeds_limit:
                    status = 'BLOQUEADA'
                    reason = f'Valor en cartera (${portfolio_value:.2f}) > 3x trade_amount (${limit_value:.2f})'
                elif not buy_signal:
                    status = 'SIN_SEÑAL'
                    reason = 'No hay señal BUY activa'
                else:
                    status = 'ELEGIBLE'
                    reason = 'Cumple todos los criterios'
                
                results.append({
                    'symbol': symbol,
                    'status': status,
                    'portfolio_value': portfolio_value,
                    'net_quantity': net_quantity,
                    'trade_amount_usd': trade_amount_usd,
                    'limit_value': limit_value,
                    'buy_signal': buy_signal,
                    'current_price': current_price,
                    'reason': reason
                })
                
            except Exception as e:
                import traceback
                error_msg = f"{str(e)}\n{traceback.format_exc()}"
                print(f"❌ Error procesando {symbol}: {error_msg}")
                results.append({
                    'symbol': symbol,
                    'status': 'ERROR',
                    'reason': str(e)
                })
        
        # Sort results: ELEGIBLE first, then by symbol
        results.sort(key=lambda x: (x['status'] != 'ELEGIBLE', x['symbol']))
        
        # Print results
        elegible_count = sum(1 for r in results if r['status'] == 'ELEGIBLE')
        bloqueada_count = sum(1 for r in results if r['status'] == 'BLOQUEADA')
        sin_senal_count = sum(1 for r in results if r['status'] == 'SIN_SEÑAL')
        
        print(f"\n📈 RESUMEN:")
        print(f"   ✅ Elegibles para alerta: {elegible_count}")
        print(f"   🚫 Bloqueadas (valor > 3x): {bloqueada_count}")
        print(f"   ⏸️  Sin señal BUY: {sin_senal_count}")
        print(f"   ❌ Errores: {len(results) - elegible_count - bloqueada_count - sin_senal_count}")
        print()
        print("-" * 100)
        print()
        
        # Print elegible coins
        if elegible_count > 0:
            print("✅ MONEDAS ELEGIBLES PARA RECIBIR ALERTAS BUY:")
            print()
            for r in results:
                if r['status'] == 'ELEGIBLE':
                    print(f"   🟢 {r['symbol']:15s} | "
                          f"Valor cartera: ${r['portfolio_value']:>10.2f} | "
                          f"Límite: ${r['limit_value']:>10.2f} | "
                          f"Trade amount: ${r['trade_amount_usd']:>8.2f} | "
                          f"Precio: ${r['current_price']:>10.4f}")
            print()
        
        # Print blocked coins
        if bloqueada_count > 0:
            print("🚫 MONEDAS BLOQUEADAS (Valor en cartera > 3x trade_amount):")
            print()
            for r in results:
                if r['status'] == 'BLOQUEADA':
                    print(f"   🔴 {r['symbol']:15s} | "
                          f"Valor cartera: ${r['portfolio_value']:>10.2f} | "
                          f"Límite: ${r['limit_value']:>10.2f} | "
                          f"Trade amount: ${r['trade_amount_usd']:>8.2f} | "
                          f"Net qty: {r['net_quantity']:>10.4f} | "
                          f"Precio: ${r['current_price']:>10.4f}")
            print()
        
        # Print coins without BUY signal
        if sin_senal_count > 0:
            print("⏸️  MONEDAS SIN SEÑAL BUY ACTIVA:")
            print()
            for r in results:
                if r['status'] == 'SIN_SEÑAL':
                    print(f"   ⚪ {r['symbol']:15s} | "
                          f"Valor cartera: ${r['portfolio_value']:>10.2f} | "
                          f"Límite: ${r['limit_value']:>10.2f} | "
                          f"Trade amount: ${r['trade_amount_usd']:>8.2f}")
            print()
        
    finally:
        db.close()

if __name__ == "__main__":
    main()

