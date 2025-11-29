"""Shared helpers to calculate open positions / open BUY commitments.

This centralizes the logic so that:
- SignalMonitorService
- Global protection (_count_total_open_buy_orders)
- Dashboard / Telegram

all use the exact same definition of "open orders":

    OpenOrders = Pending BUY orders (NEW/ACTIVE/PARTIALLY_FILLED)
                 + BUY orders FILLED que todavía no han sido cerradas
                   completamente por órdenes SELL FILLED (SL/TP/manual).
"""

import logging
from typing import Tuple

from sqlalchemy.orm import Session
from sqlalchemy import or_, not_

from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum

logger = logging.getLogger(__name__)


def _normalized_symbol_filter(symbol: str):
    """
    Helper to build a SQLAlchemy filter for a symbol.

    - If symbol contains "_", filter by exact symbol (e.g. "ADA_USDT").
    - If not, treat as base currency and match all pairs (e.g. "ADA_%").
    """
    symbol = (symbol or "").upper()
    if not symbol:
        # No symbol provided - match nothing
        return ExchangeOrder.symbol == "__NO_SYMBOL__"

    if "_" in symbol:
        return ExchangeOrder.symbol == symbol

    # Base currency only (e.g. "ADA") -> match ADA_USD, ADA_USDT, etc.
    # Also include exact symbol equality in case some records store plain base (e.g., "ETH")
    return or_(
        ExchangeOrder.symbol == symbol,
        ExchangeOrder.symbol.like(f"{symbol}_%"),
    )


def _order_filled_quantity(order: ExchangeOrder) -> float:
    """Return the effective filled quantity for an order as float."""
    qty = order.cumulative_quantity or order.quantity or 0
    try:
        return float(qty)
    except Exception:
        return float(qty or 0)


def count_open_positions_for_symbol(db: Session, symbol: str) -> int:
    """
    Returns the number of open BUY commitments for a symbol.

    Definition:
        OpenOrders = Pending BUY orders (NEW/ACTIVE/PARTIALLY_FILLED)
                     + BUY orders FILLED que todavía no han sido cerradas
                       completamente por órdenes SELL FILLED (SL/TP/manual).

    This function is intentionally conservative and works at the symbol/base level:
    - If symbol is "ADA_USDT" -> analiza solo ese par.
    - If symbol is "ADA"      -> analiza todos los pares "ADA_*".
    """
    # 1) Pending BUY orders (principal, no SL/TP)
    pending_statuses = [
        OrderStatusEnum.NEW,
        OrderStatusEnum.ACTIVE,
        OrderStatusEnum.PARTIALLY_FILLED,
    ]
    # Some exchanges use "PENDING" but our enum may not have it – include defensively
    pending_enum = getattr(OrderStatusEnum, "PENDING", None)
    if pending_enum is not None:
        pending_statuses.append(pending_enum)

    symbol_filter = _normalized_symbol_filter(symbol)

    # Consider as "main" any order_role that is not STOP_LOSS/TAKE_PROFIT (including NULL/empty/custom)
    main_role_filter = or_(
        ExchangeOrder.order_role.is_(None),
        not_(ExchangeOrder.order_role.in_(["STOP_LOSS", "TAKE_PROFIT"])),
    )

    pending_buy_orders = db.query(ExchangeOrder).filter(
        symbol_filter,
        ExchangeOrder.side == OrderSideEnum.BUY,
        ExchangeOrder.status.in_(pending_statuses),
        main_role_filter,
    ).all()
    pending_buy_count = len(pending_buy_orders)

    # 2) Filled BUY orders (posiciones ya abiertas en algún momento)
    filled_buy_orders = (
        db.query(ExchangeOrder)
        .filter(
            symbol_filter,
            ExchangeOrder.side == OrderSideEnum.BUY,
            ExchangeOrder.status == OrderStatusEnum.FILLED,
            main_role_filter,
        )
        .order_by(ExchangeOrder.exchange_create_time.asc(), ExchangeOrder.created_at.asc(), ExchangeOrder.id.asc())
        .all()
    )

    # Total BUY filled quantity for this symbol/base
    filled_buy_qty = sum(_order_filled_quantity(o) for o in filled_buy_orders)

    # 3) Filled SELL orders that offset these BUYs (SL/TP/manual)
    filled_sell_orders = (
        db.query(ExchangeOrder)
        .filter(
            symbol_filter,
            ExchangeOrder.side == OrderSideEnum.SELL,
            ExchangeOrder.status == OrderStatusEnum.FILLED,
            # Any role can offset: STOP_LOSS, TAKE_PROFIT, or manual SELL (order_role is NULL)
            or_(
                ExchangeOrder.order_role.is_(None),
                ExchangeOrder.order_role == "STOP_LOSS",
                ExchangeOrder.order_role == "TAKE_PROFIT",
            ),
        )
        .order_by(ExchangeOrder.exchange_create_time.asc(), ExchangeOrder.created_at.asc(), ExchangeOrder.id.asc())
        .all()
    )

    filled_sell_qty = sum(_order_filled_quantity(o) for o in filled_sell_orders)

    # 4) Calculate net remaining quantity for this symbol
    net_quantity = max(filled_buy_qty - filled_sell_qty, 0.0)

    # 5) Determine how many FILLED BUY orders are still open as positions.
    # We use a simple FIFO matching: SELL quantity offsets the earliest BUYs first.
    remaining_sell_qty = filled_sell_qty
    open_filled_positions = 0

    for buy_order in filled_buy_orders:
        buy_qty = _order_filled_quantity(buy_order)
        if buy_qty <= 0:
            continue

        if remaining_sell_qty >= buy_qty:
            # This BUY is fully closed by earlier SELLs
            remaining_sell_qty -= buy_qty
        else:
            # This BUY still has some net quantity open -> count as one open position
            open_filled_positions += 1
            # All remaining SELL quantity has been consumed
            remaining_sell_qty = 0.0

    total_open_positions = pending_buy_count + open_filled_positions

    try:
        # Extra debug for diagnostics
        sample_pending = [o.symbol for o in pending_buy_orders[:5]]
        sample_buy = [o.symbol for o in filled_buy_orders[:5]]
        sample_sell = [o.symbol for o in filled_sell_orders[:5]]
        logger.info(
            "[OPEN_POSITION_DEBUG] base=%s pending=%s sample_pending=%s sample_buy=%s sample_sell=%s",
            symbol,
            pending_buy_count,
            sample_pending,
            sample_buy,
            sample_sell,
        )
    except Exception:
        pass

    logger.info(
        "[OPEN_POSITION_COUNT] symbol=%s pending_buy=%s filled_buy=%s filled_sell=%s net_qty=%s final_positions=%s",
        symbol,
        pending_buy_count,
        round(filled_buy_qty, 8),
        round(filled_sell_qty, 8),
        round(net_quantity, 8),
        total_open_positions,
    )

    return total_open_positions


def count_total_open_positions(db: Session) -> int:
    """
    Helper to count total open BUY commitments across ALL symbols using the same
    unified logic as `count_open_positions_for_symbol`.
    """
    # Collect all symbols that have BUY activity (pending or filled)
    symbols_rows = (
        db.query(ExchangeOrder.symbol)
        .filter(
            ExchangeOrder.side == OrderSideEnum.BUY,
            ExchangeOrder.status.in_(
                [
                    OrderStatusEnum.NEW,
                    OrderStatusEnum.ACTIVE,
                    OrderStatusEnum.PARTIALLY_FILLED,
                    OrderStatusEnum.FILLED,
                ]
            ),
        )
        .distinct()
        .all()
    )

    # Normalize to BASE currency to avoid double-counting across pairs (e.g., BTC_USD and BTC_USDT)
    bases: set[str] = set()
    for row in symbols_rows:
        sym = row[0] if isinstance(row, tuple) else row.symbol if hasattr(row, "symbol") else row
        if not sym:
            continue
        sym_upper = str(sym).upper()
        base = sym_upper.split("_")[0] if "_" in sym_upper else sym_upper
        if base:
            bases.add(base)

    total = 0
    for base in bases:
        total += count_open_positions_for_symbol(db, base)

    return total


def calculate_portfolio_value_for_symbol(db: Session, symbol: str, current_price: float) -> Tuple[float, float]:
    """
    Calculate portfolio value (USD) for a symbol based on net quantity * current_price.
    
    Uses the same logic as count_open_positions_for_symbol to get net quantity.
    
    Args:
        db: Database session
        symbol: Symbol to calculate portfolio value for (e.g., "AAVE" or "AAVE_USD")
        current_price: Current market price for the symbol
        
    Returns:
        Tuple[portfolio_value_usd, net_quantity]
        - portfolio_value_usd: Total USD value of open positions for this symbol
        - net_quantity: Net quantity (filled_buy_qty - filled_sell_qty)
    """
    symbol_filter = _normalized_symbol_filter(symbol)
    
    # Get filled BUY orders
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
    
    filled_buy_qty = sum(_order_filled_quantity(o) for o in filled_buy_orders)
    
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
    
    filled_sell_qty = sum(_order_filled_quantity(o) for o in filled_sell_orders)
    
    # Calculate net quantity
    net_quantity = max(filled_buy_qty - filled_sell_qty, 0.0)
    
    # Calculate portfolio value
    portfolio_value_usd = net_quantity * current_price
    
    # Detailed logging for CRO_USDT (and variants) to debug portfolio value discrepancies
    symbol_upper = (symbol or "").upper()
    is_cro = "CRO" in symbol_upper
    
    if is_cro:
        # Get detailed breakdown for CRO
        buy_order_details = []
        for order in filled_buy_orders:
            qty = _order_filled_quantity(order)
            buy_order_details.append({
                "order_id": order.exchange_order_id,
                "quantity": qty,
                "price": float(order.price) if order.price else None,
                "status": order.status.value if hasattr(order.status, 'value') else str(order.status),
                "role": order.order_role,
            })
        
        sell_order_details = []
        for order in filled_sell_orders:
            qty = _order_filled_quantity(order)
            sell_order_details.append({
                "order_id": order.exchange_order_id,
                "quantity": qty,
                "price": float(order.price) if order.price else None,
                "status": order.status.value if hasattr(order.status, 'value') else str(order.status),
                "role": order.order_role,
            })
        
        # Also check for open orders
        from sqlalchemy import or_, not_
        pending_statuses = [
            OrderStatusEnum.NEW,
            OrderStatusEnum.ACTIVE,
            OrderStatusEnum.PARTIALLY_FILLED,
        ]
        main_role_filter = or_(
            ExchangeOrder.order_role.is_(None),
            not_(ExchangeOrder.order_role.in_(["STOP_LOSS", "TAKE_PROFIT"])),
        )
        open_buy_orders = (
            db.query(ExchangeOrder)
            .filter(
                symbol_filter,
                ExchangeOrder.side == OrderSideEnum.BUY,
                ExchangeOrder.status.in_(pending_statuses),
                main_role_filter,
            )
            .all()
        )
        open_buy_value = sum(
            (_order_filled_quantity(o) or float(o.quantity or 0)) * (float(o.price) if o.price else current_price)
            for o in open_buy_orders
        )
        
        # Check actual balances from exchange
        try:
            from app.models.portfolio_balance import PortfolioBalance
            portfolio_balances = db.query(PortfolioBalance).filter(
                PortfolioBalance.currency.like("CRO%")
            ).all()
            balance_details = []
            total_balance_usd = 0.0
            for bal in portfolio_balances:
                balance_usd = float(bal.usd_value) if bal.usd_value else 0.0
                total_balance_usd += balance_usd
                balance_details.append({
                    "currency": bal.currency,
                    "balance": float(bal.balance) if bal.balance else 0.0,
                    "usd_value": balance_usd,
                })
        except Exception as balance_err:
            balance_details = []
            total_balance_usd = 0.0
            logger.warning(f"Could not fetch portfolio balances for CRO: {balance_err}")
        
        logger.info(
            "[RISK_PORTFOLIO_CHECK] symbol=%s "
            "filled_buy_qty=%.8f filled_sell_qty=%.8f net_qty=%.8f "
            "current_price=%.4f portfolio_value_usd=%.2f "
            "open_buy_orders_count=%d open_buy_orders_value=%.2f "
            "exchange_balance_usd=%.2f "
            "buy_orders=%d sell_orders=%d",
            symbol,
            filled_buy_qty,
            filled_sell_qty,
            net_quantity,
            current_price,
            portfolio_value_usd,
            len(open_buy_orders),
            open_buy_value,
            total_balance_usd,
            len(filled_buy_orders),
            len(filled_sell_orders),
        )
        
        if buy_order_details:
            logger.info(
                "[RISK_PORTFOLIO_CHECK] CRO filled BUY orders: %s",
                buy_order_details[:5]  # Log first 5
            )
        if sell_order_details:
            logger.info(
                "[RISK_PORTFOLIO_CHECK] CRO filled SELL orders: %s",
                sell_order_details[:5]  # Log first 5
            )
        if balance_details:
            logger.info(
                "[RISK_PORTFOLIO_CHECK] CRO exchange balances: %s",
                balance_details
            )
    else:
        logger.debug(
            "[PORTFOLIO_VALUE] symbol=%s filled_buy_qty=%s filled_sell_qty=%s net_qty=%s price=%s portfolio_value=%s",
            symbol,
            round(filled_buy_qty, 8),
            round(filled_sell_qty, 8),
            round(net_quantity, 8),
            round(current_price, 4),
            round(portfolio_value_usd, 2),
        )
    
    return portfolio_value_usd, net_quantity


