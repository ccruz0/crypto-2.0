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
    # Only subtract FILLED SELL orders - pending TP/SL orders don't reduce open position count
    # (they are just protection orders that haven't executed yet)
    net_quantity = max(filled_buy_qty - filled_sell_qty, 0.0)

    # 5) Determine how many FILLED BUY orders are still open as positions.
    # We use a simple FIFO matching: Only FILLED SELL quantity offsets the earliest BUYs first.
    # IMPORTANT: Pending TP/SL orders do NOT reduce open position count - they are just protection orders.
    # Count based on net quantity and average position size, not individual orders.
    # This prevents over-counting when multiple small orders exist.
    remaining_sell_qty = filled_sell_qty
    open_filled_positions = 0

    # Calculate average position size from filled BUY orders
    if len(filled_buy_orders) > 0 and filled_buy_qty > 0:
        avg_position_size = filled_buy_qty / len(filled_buy_orders)
    else:
        avg_position_size = 0

    # If we have net quantity, estimate positions based on average size
    # This is more accurate than counting each order separately
    if net_quantity > 0 and avg_position_size > 0:
        # Estimate positions: net quantity divided by average position size
        # This gives us a realistic count based on actual holdings, not individual orders
        
        # Add minimum threshold: only count as a position if net quantity is significant
        # (at least 1% of average position size to avoid counting tiny remnants)
        MIN_POSITION_THRESHOLD = avg_position_size * 0.01
        
        if net_quantity >= MIN_POSITION_THRESHOLD:
            estimated_positions = max(1, int(round(net_quantity / avg_position_size)))
        else:
            # Net quantity is too small to count as a meaningful position
            estimated_positions = 0
            logger.debug(
                f"Position too small for {symbol}: net_qty={net_quantity:.4f} < threshold={MIN_POSITION_THRESHOLD:.4f}"
            )
        
        # Use estimated positions as the primary count
        # This prevents over-counting when multiple small orders exist
        open_filled_positions = estimated_positions
        
        # Log the estimation for visibility (info level so it appears in production logs)
        logger.info(
            f"[POSITION_ESTIMATION] {symbol}: net_qty={net_quantity:.4f}, "
            f"avg_size={avg_position_size:.4f}, estimated={estimated_positions}, "
            f"threshold={MIN_POSITION_THRESHOLD:.4f}"
        )
    else:
        # Fallback to FIFO logic if we can't calculate average (edge case)
        # This should rarely happen, but provides a safety net
        logger.debug(
            f"Using FIFO fallback for {symbol}: net_qty={net_quantity:.4f}, "
            f"avg_size={avg_position_size:.4f}, filled_buy_orders={len(filled_buy_orders)}"
        )
        for buy_order in filled_buy_orders:
            buy_qty = _order_filled_quantity(buy_order)
            if buy_qty <= 0:
                continue

            if remaining_sell_qty >= buy_qty:
                # This BUY is fully closed by SELLs
                remaining_sell_qty -= buy_qty
            else:
                # This BUY still has some net quantity open
                open_filled_positions += 1
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
        "[OPEN_POSITION_COUNT] symbol=%s pending_buy=%s filled_buy=%s filled_sell=%s net_qty=%s final_positions=%s (avg_size=%s)",
        symbol,
        pending_buy_count,
        round(filled_buy_qty, 8),
        round(filled_sell_qty, 8),
        round(net_quantity, 8),
        total_open_positions,
        round(avg_position_size, 4) if avg_position_size > 0 else 0,
    )

    return total_open_positions


def count_total_open_positions(db: Session) -> int:
    """
    Count total open positions by counting only pending TAKE_PROFIT orders.
    
    This represents positions waiting to be sold. Each pending TP order = 1 open position.
    """
    # Count only TAKE_PROFIT orders that are pending (not FILLED)
    # These represent positions waiting to be sold
    pending_tp_orders = db.query(ExchangeOrder).filter(
        ExchangeOrder.order_role == "TAKE_PROFIT",
        ExchangeOrder.status.in_(
            [
                OrderStatusEnum.NEW,
                OrderStatusEnum.ACTIVE,
                OrderStatusEnum.PARTIALLY_FILLED,
            ]
        ),
    ).all()
    
    total = len(pending_tp_orders)
    
    logger.info(
        f"[OPEN_POSITION_COUNT] Counting TP orders only: {total} pending TAKE_PROFIT orders"
    )
    
    return total


# Configuration: Include open BUY orders in risk portfolio value calculation
INCLUDE_OPEN_ORDERS_IN_RISK = True


def calculate_portfolio_value_for_symbol(db: Session, symbol: str, current_price: float) -> Tuple[float, float]:
    """
    Calculate portfolio value (USD) for a symbol based on actual exchange balances.
    
    This aligns with what the Portfolio tab shows, using real balances from the exchange
    instead of only historical filled orders.
    
    Args:
        db: Database session
        symbol: Symbol to calculate portfolio value for (e.g., "CRO_USDT" or "CRO")
        current_price: Current market price for the symbol
        
    Returns:
        Tuple[portfolio_value_usd, balance_quantity]
        - portfolio_value_usd: Total USD value (balance + optionally open BUY orders)
        - balance_quantity: Total balance quantity from exchange
    """
    # Extract base currency (e.g., "CRO" from "CRO_USDT")
    base_currency = symbol.split("_")[0] if "_" in symbol else symbol
    base_currency = base_currency.upper()
    
    # Get exchange balance from PortfolioBalance table (same source as Portfolio tab)
    balance_qty = 0.0
    balance_value_usd = 0.0
    
    try:
        from app.models.portfolio import PortfolioBalance
        from app.services.portfolio_cache import _normalize_currency_name
    
        # Query for normalized currency name (balances are stored with base currency)
        normalized_currency = _normalize_currency_name(base_currency)
        
        # Get all balances matching this currency (could be multiple entries, take most recent)
        portfolio_balances = (
            db.query(PortfolioBalance)
            .filter(PortfolioBalance.currency == normalized_currency)
            .order_by(PortfolioBalance.id.desc())
            .all()
        )
        
        # Sum all balance entries for this currency (in case of duplicates)
        for bal in portfolio_balances:
            balance_qty += float(bal.balance) if bal.balance else 0.0
            balance_value_usd += float(bal.usd_value) if bal.usd_value else 0.0
        
        # If no balance found but we have a price, calculate from quantity
        if balance_value_usd == 0.0 and balance_qty > 0:
            balance_value_usd = balance_qty * current_price
            
    except Exception as balance_err:
        logger.warning(f"Could not fetch portfolio balance for {symbol} (base={base_currency}): {balance_err}")
        balance_qty = 0.0
        balance_value_usd = 0.0
    
    # Optionally include open BUY orders exposure
    open_buy_value_usd = 0.0
    open_buy_orders_count = 0
    
    if INCLUDE_OPEN_ORDERS_IN_RISK:
        try:
            symbol_filter = _normalized_symbol_filter(symbol)
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
            
            open_buy_orders_count = len(open_buy_orders)
            for order in open_buy_orders:
                # Use order price if available, otherwise use current_price
                order_price = float(order.price) if order.price else current_price
                order_qty = _order_filled_quantity(order) or float(order.quantity or 0)
                open_buy_value_usd += order_qty * order_price
                
        except Exception as open_orders_err:
            logger.warning(f"Could not fetch open BUY orders for {symbol}: {open_orders_err}")
            open_buy_value_usd = 0.0
    
    # Calculate total portfolio value
    portfolio_value_usd = balance_value_usd + open_buy_value_usd
    
    # Log portfolio value calculation (concise for all symbols, detailed breakdown available in logs)
    logger.info(
        "[RISK_PORTFOLIO_CHECK] symbol=%s base_currency=%s balance_qty=%.8f balance_value_usd=%.2f "
        "open_buy_orders_count=%d open_buy_value_usd=%.2f total_value_usd=%.2f "
        "include_open_orders=%s",
        symbol,
        base_currency,
        balance_qty,
        balance_value_usd,
        open_buy_orders_count,
        open_buy_value_usd,
        portfolio_value_usd,
        INCLUDE_OPEN_ORDERS_IN_RISK,
    )
    
    # Return portfolio value and balance quantity
    return portfolio_value_usd, balance_qty


