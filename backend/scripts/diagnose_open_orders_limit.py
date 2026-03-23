#!/usr/bin/env python3
"""Diagnose open orders limit for a specific symbol (e.g., AAVE)

This script uses the same logic as the actual system to calculate
open positions and shows why orders might be blocked.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import create_db_session
from app.models.watchlist import WatchlistItem
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.services.order_position_service import count_open_positions_for_symbol, count_total_open_positions
from sqlalchemy import or_, not_

def diagnose_open_orders_limit(symbol: str = "AAVE"):
    """
    Diagnose why orders might be blocked due to open orders limit.
    
    Args:
        symbol: Symbol to check (e.g., "AAVE", "AAVE_USDT")
    """
    db = create_db_session()
    try:
        symbol_upper = symbol.upper()
        
        # Extract base currency (e.g., "AAVE" from "AAVE_USDT")
        if "_" in symbol_upper:
            base_currency = symbol_upper.split("_")[0]
        else:
            base_currency = symbol_upper
        
        print(f"\n{'='*80}")
        print(f"🔍 DIAGNÓSTICO DE LÍMITE DE ÓRDENES ABIERTAS")
        print(f"{'='*80}")
        print(f"📊 Símbolo: {symbol_upper}")
        print(f"📊 Base Currency: {base_currency}")
        print(f"{'='*80}\n")
        
        # Get limit from signal monitor
        from app.services.signal_monitor import SignalMonitorService
        signal_monitor = SignalMonitorService()
        max_limit = signal_monitor.MAX_OPEN_ORDERS_PER_SYMBOL
        
        print(f"⚙️  CONFIGURACIÓN:")
        print(f"   - Límite máximo: {max_limit} órdenes abiertas por símbolo base")
        print()
        
        # Calculate unified open positions (same logic as system)
        unified_count = count_open_positions_for_symbol(db, base_currency)
        
        print(f"📈 CONTEO UNIFICADO DE ÓRDENES ABIERTAS:")
        print(f"   - Total: {unified_count}/{max_limit}")
        if unified_count >= max_limit:
            print(f"   - ❌ LÍMITE ALCANZADO - Las nuevas órdenes serán bloqueadas")
        else:
            print(f"   - ✅ Aún puedes crear {max_limit - unified_count} orden(es) más")
        print()
        
        # Detailed breakdown
        print(f"📋 DESGLOSE DETALLADO:")
        print(f"{'-'*80}")
        
        # 1. Pending BUY orders
        pending_statuses = [
            OrderStatusEnum.NEW,
            OrderStatusEnum.ACTIVE,
            OrderStatusEnum.PARTIALLY_FILLED,
        ]
        
        # Build symbol filter (same as order_position_service)
        if "_" in base_currency:
            symbol_filter = ExchangeOrder.symbol == base_currency
        else:
            symbol_filter = or_(
                ExchangeOrder.symbol == base_currency,
                ExchangeOrder.symbol.like(f"{base_currency}_%"),
            )
        
        main_role_filter = or_(
            ExchangeOrder.order_role.is_(None),
            not_(ExchangeOrder.order_role.in_(["STOP_LOSS", "TAKE_PROFIT"])),
        )
        
        pending_buy_orders = db.query(ExchangeOrder).filter(
            symbol_filter,
            ExchangeOrder.side == OrderSideEnum.BUY,
            ExchangeOrder.status.in_(pending_statuses),
            main_role_filter,
        ).order_by(ExchangeOrder.exchange_create_time.desc(), ExchangeOrder.created_at.desc()).all()
        
        print(f"\n1️⃣ ÓRDENES BUY PENDIENTES: {len(pending_buy_orders)}")
        if pending_buy_orders:
            for i, order in enumerate(pending_buy_orders[:10], 1):
                order_time = order.exchange_create_time or order.created_at
                qty = order.cumulative_quantity or order.quantity or 0
                price = order.price or order.avg_price or 0
                print(f"   {i}. {order.symbol} | {order.status.value} | "
                      f"Qty: {qty} | Price: ${price} | "
                      f"Time: {order_time}")
            if len(pending_buy_orders) > 10:
                print(f"   ... y {len(pending_buy_orders) - 10} más")
        else:
            print(f"   ✅ No hay órdenes pendientes")
        
        # 2. Filled BUY orders
        filled_buy_orders = (
            db.query(ExchangeOrder)
            .filter(
                symbol_filter,
                ExchangeOrder.side == OrderSideEnum.BUY,
                ExchangeOrder.status == OrderStatusEnum.FILLED,
                main_role_filter,
            )
            .order_by(ExchangeOrder.exchange_create_time.asc(), ExchangeOrder.created_at.asc())
            .all()
        )
        
        print(f"\n2️⃣ ÓRDENES BUY FILLED: {len(filled_buy_orders)}")
        if filled_buy_orders:
            total_buy_qty = sum(float(o.cumulative_quantity or o.quantity or 0) for o in filled_buy_orders)
            print(f"   - Cantidad total comprada: {total_buy_qty}")
            for i, order in enumerate(filled_buy_orders[:5], 1):
                order_time = order.exchange_create_time or order.created_at
                qty = order.cumulative_quantity or order.quantity or 0
                price = order.avg_price or order.filled_price or order.price or 0
                print(f"   {i}. {order.symbol} | Qty: {qty} | Price: ${price} | "
                      f"Time: {order_time}")
            if len(filled_buy_orders) > 5:
                print(f"   ... y {len(filled_buy_orders) - 5} más")
        else:
            print(f"   ✅ No hay órdenes BUY completadas")
        
        # 3. Filled SELL orders
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
            .order_by(ExchangeOrder.exchange_create_time.asc(), ExchangeOrder.created_at.asc())
            .all()
        )
        
        print(f"\n3️⃣ ÓRDENES SELL FILLED (que offset BUYs): {len(filled_sell_orders)}")
        if filled_sell_orders:
            total_sell_qty = sum(float(o.cumulative_quantity or o.quantity or 0) for o in filled_sell_orders)
            print(f"   - Cantidad total vendida: {total_sell_qty}")
            for i, order in enumerate(filled_sell_orders[:5], 1):
                order_time = order.exchange_create_time or order.created_at
                qty = order.cumulative_quantity or order.quantity or 0
                price = order.avg_price or order.filled_price or order.price or 0
                role = order.order_role or "MANUAL"
                print(f"   {i}. {order.symbol} | {role} | Qty: {qty} | Price: ${price} | "
                      f"Time: {order_time}")
            if len(filled_sell_orders) > 5:
                print(f"   ... y {len(filled_sell_orders) - 5} más")
        else:
            print(f"   ✅ No hay órdenes SELL completadas")
        
        # 3b. Pending TP/SL orders (informational only - they don't reduce open position count)
        pending_sell_orders = (
            db.query(ExchangeOrder)
            .filter(
                symbol_filter,
                ExchangeOrder.side == OrderSideEnum.SELL,
                ExchangeOrder.status.in_(pending_statuses),
                ExchangeOrder.order_role.in_(["STOP_LOSS", "TAKE_PROFIT"]),
            )
            .order_by(ExchangeOrder.exchange_create_time.asc(), ExchangeOrder.created_at.asc())
            .all()
        )
        
        print(f"\n3b️⃣ ÓRDENES TP/SL PENDIENTES (información - NO reducen posiciones abiertas): {len(pending_sell_orders)}")
        if pending_sell_orders:
            pending_sell_qty = sum(float(o.cumulative_quantity or o.quantity or 0) for o in pending_sell_orders)
            print(f"   - Cantidad total en TP/SL pendientes: {pending_sell_qty}")
            print(f"   - 💡 Estas órdenes NO reducen el conteo de posiciones abiertas")
            print(f"   - 💡 Solo las órdenes SELL FILLED reducen el conteo")
            for i, order in enumerate(pending_sell_orders[:5], 1):
                order_time = order.exchange_create_time or order.created_at
                qty = order.cumulative_quantity or order.quantity or 0
                price = order.price or 0
                role = order.order_role or "UNKNOWN"
                print(f"   {i}. {order.symbol} | {role} | Qty: {qty} | Price: ${price} | "
                      f"Status: {order.status.value} | Time: {order_time}")
            if len(pending_sell_orders) > 5:
                print(f"   ... y {len(pending_sell_orders) - 5} más")
        else:
            print(f"   ✅ No hay órdenes TP/SL pendientes")
        
        # 4. Calculate net positions (FIFO logic)
        if filled_buy_orders:
            print(f"\n4️⃣ CÁLCULO DE POSICIONES NETAS (FIFO):")
            filled_buy_qty = sum(float(o.cumulative_quantity or o.quantity or 0) for o in filled_buy_orders)
            filled_sell_qty = sum(float(o.cumulative_quantity or o.quantity or 0) for o in filled_sell_orders)
            pending_sell_qty = sum(float(o.cumulative_quantity or o.quantity or 0) for o in pending_sell_orders) if pending_sell_orders else 0.0
            # Only subtract FILLED SELL orders - pending TP/SL don't reduce open position count
            net_qty = max(filled_buy_qty - filled_sell_qty, 0.0)
            
            print(f"   - Total BUY: {filled_buy_qty}")
            print(f"   - Total SELL FILLED: {filled_sell_qty}")
            print(f"   - Total TP/SL PENDIENTES: {pending_sell_qty} (información - NO se resta)")
            print(f"   - Neto (BUY - SELL FILLED): {net_qty}")
            print(f"   - 💡 Las órdenes TP/SL pendientes NO reducen el conteo de posiciones abiertas")
            
            # Count how many BUY orders are still open (only considering FILLED SELL orders)
            remaining_sell_qty = filled_sell_qty
            open_filled_positions = 0
            
            for buy_order in filled_buy_orders:
                buy_qty = float(buy_order.cumulative_quantity or buy_order.quantity or 0)
                if buy_qty <= 0:
                    continue
                
                if remaining_sell_qty >= buy_qty:
                    remaining_sell_qty -= buy_qty
                else:
                    open_filled_positions += 1
                    remaining_sell_qty = 0.0
            
            print(f"   - Posiciones FILLED aún abiertas (después de restar solo SELL FILLED): {open_filled_positions}")
        
        # 5. Summary
        print(f"\n{'='*80}")
        print(f"📊 RESUMEN:")
        print(f"{'='*80}")
        print(f"   - Órdenes pendientes: {len(pending_buy_orders)}")
        if filled_buy_orders:
            # Calculate open filled positions (only considering FILLED SELL orders)
            filled_buy_qty = sum(float(o.cumulative_quantity or o.quantity or 0) for o in filled_buy_orders)
            filled_sell_qty = sum(float(o.cumulative_quantity or o.quantity or 0) for o in filled_sell_orders)
            remaining_sell_qty = filled_sell_qty
            open_filled_positions = 0
            
            for buy_order in filled_buy_orders:
                buy_qty = float(buy_order.cumulative_quantity or buy_order.quantity or 0)
                if buy_qty <= 0:
                    continue
                if remaining_sell_qty >= buy_qty:
                    remaining_sell_qty -= buy_qty
                else:
                    open_filled_positions += 1
                    remaining_sell_qty = 0.0
            
            print(f"   - Posiciones FILLED abiertas: {open_filled_positions}")
        else:
            print(f"   - Posiciones FILLED abiertas: 0")
        
        print(f"   - TOTAL: {unified_count}/{max_limit}")
        print()
        
        if unified_count >= max_limit:
            print(f"❌ CONCLUSIÓN: El límite de {max_limit} órdenes abiertas ha sido alcanzado.")
            print(f"   Las nuevas órdenes para {base_currency} serán bloqueadas hasta que:")
            print(f"   1. Se completen/cancelen órdenes pendientes, o")
            print(f"   2. Se cierren posiciones FILLED con órdenes SELL")
        else:
            print(f"✅ CONCLUSIÓN: Aún puedes crear {max_limit - unified_count} orden(es) más para {base_currency}")
        
        # Show all symbols counted together
        if "_" not in base_currency:
            all_symbols = db.query(ExchangeOrder.symbol).filter(
                symbol_filter,
                ExchangeOrder.side == OrderSideEnum.BUY,
                ExchangeOrder.status.in_(pending_statuses + [OrderStatusEnum.FILLED]),
            ).distinct().all()
            
            if all_symbols:
                symbols_list = [s[0] if isinstance(s, tuple) else s.symbol for s in all_symbols]
                print(f"\n💡 NOTA: El conteo incluye todos los pares de {base_currency}:")
                for sym in sorted(set(symbols_list)):
                    print(f"   - {sym}")
        
        print(f"\n{'='*80}\n")
        
    finally:
        db.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Diagnose open orders limit for a symbol")
    parser.add_argument(
        "--symbol",
        type=str,
        default="AAVE",
        help="Symbol to check (e.g., AAVE, AAVE_USDT, BTC)"
    )
    
    args = parser.parse_args()
    diagnose_open_orders_limit(args.symbol)





