"""Shared helpers to calculate open positions for guardrails.

This centralizes the logic so that:
- SignalMonitorService
- Global protection (_count_total_open_buy_orders)
- Dashboard / Telegram

all use the exact same definition of "open positions":

    OpenPositions = pending bot entry orders (BUY long / SELL short)
                    + filled bot entry orders net of protection closes on the opposite side.
"""

import logging
from typing import Tuple

from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, not_

from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum

logger = logging.getLogger(__name__)


def _infer_symbol_price(filled_buy_orders: list[ExchangeOrder]) -> float | None:
    """Best-effort price for dust USD checks when caller did not pass last_price."""
    prices: list[float] = []
    for order in filled_buy_orders:
        for raw in (order.avg_price, order.price):
            if raw is None:
                continue
            try:
                val = float(raw)
            except Exception:
                continue
            if val > 0:
                prices.append(val)
                break
    if not prices:
        return None
    return sum(prices) / len(prices)


def _is_position_dust(
    net_quantity: float,
    *,
    min_position_qty: float = 0.0,
    min_position_usd: float = 0.0,
    last_price: float | None = None,
) -> bool:
    """True when net filled quantity is below optional dust thresholds."""
    if net_quantity <= 0:
        return True
    if min_position_qty > 0 and net_quantity < min_position_qty:
        return True
    if min_position_usd > 0:
        price = last_price
        if price is None or price <= 0:
            return False
        if net_quantity * price < min_position_usd:
            return True
    return False


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


def _main_role_filter():
    """Principal orders — excludes STOP_LOSS / TAKE_PROFIT protection children."""
    return or_(
        ExchangeOrder.order_role.is_(None),
        not_(ExchangeOrder.order_role.in_(["STOP_LOSS", "TAKE_PROFIT"])),
    )


def _bot_main_entry_filter():
    """Bot principal entry orders (not SL/TP children)."""
    return and_(
        ExchangeOrder.trade_signal_id.isnot(None),
        ExchangeOrder.parent_order_id.is_(None),
        _main_role_filter(),
    )


def _long_close_sell_filter():
    """SELL orders that close long positions — excludes short-entry SELLs."""
    bot_offset_sell_filter = or_(
        ExchangeOrder.trade_signal_id.isnot(None),
        ExchangeOrder.parent_order_id.isnot(None),
        ExchangeOrder.order_role.in_(["STOP_LOSS", "TAKE_PROFIT"]),
    )
    short_entry_shape = and_(
        ExchangeOrder.trade_signal_id.isnot(None),
        ExchangeOrder.parent_order_id.is_(None),
        _main_role_filter(),
    )
    return and_(
        ExchangeOrder.side == OrderSideEnum.SELL,
        bot_offset_sell_filter,
        not_(short_entry_shape),
    )


def _short_close_buy_filter():
    """BUY orders that close short positions (protection / cover)."""
    return and_(
        ExchangeOrder.side == OrderSideEnum.BUY,
        or_(
            ExchangeOrder.parent_order_id.isnot(None),
            ExchangeOrder.order_role.in_(["STOP_LOSS", "TAKE_PROFIT"]),
        ),
    )


def _estimate_filled_open_positions(
    net_quantity: float,
    filled_entry_orders: list[ExchangeOrder],
    filled_close_qty: float,
    *,
    symbol: str,
    side_label: str,
) -> int:
    """Estimate how many filled entry orders remain open after close offsets."""
    if net_quantity <= 0:
        return 0

    filled_entry_qty = sum(_order_filled_quantity(o) for o in filled_entry_orders)
    if len(filled_entry_orders) > 0 and filled_entry_qty > 0:
        avg_position_size = filled_entry_qty / len(filled_entry_orders)
    else:
        avg_position_size = 0.0

    if net_quantity > 0 and avg_position_size > 0:
        min_position_threshold = avg_position_size * 0.01
        if net_quantity >= min_position_threshold:
            estimated = max(1, int(round(net_quantity / avg_position_size)))
        else:
            estimated = 0
            logger.debug(
                "%s position too small for %s: net_qty=%.4f < threshold=%.4f",
                side_label,
                symbol,
                net_quantity,
                min_position_threshold,
            )
        logger.info(
            "[POSITION_ESTIMATION] %s %s: net_qty=%.4f, avg_size=%.4f, estimated=%s, threshold=%.4f",
            side_label,
            symbol,
            net_quantity,
            avg_position_size,
            estimated,
            min_position_threshold,
        )
        return estimated

    logger.debug(
        "Using FIFO fallback for %s %s: net_qty=%.4f, avg_size=%.4f, entries=%s",
        side_label,
        symbol,
        net_quantity,
        avg_position_size,
        len(filled_entry_orders),
    )
    remaining_close_qty = filled_close_qty
    open_filled_positions = 0
    for entry_order in filled_entry_orders:
        entry_qty = _order_filled_quantity(entry_order)
        if entry_qty <= 0:
            continue
        if remaining_close_qty >= entry_qty:
            remaining_close_qty -= entry_qty
        else:
            open_filled_positions += 1
            remaining_close_qty = 0.0
    return open_filled_positions


def count_open_positions_for_symbol(
    db: Session,
    symbol: str,
    *,
    min_position_qty: float = 0.0,
    min_position_usd: float = 0.0,
    last_price: float | None = None,
) -> int:
    """
    Returns the number of open bot positions (long + short) for a symbol.

    Definition:
        OpenPositions = pending bot entry orders (BUY for long, SELL for short)
                        + filled bot entry orders not fully closed by protection
                          orders on the opposite side.

    Long closes: SELL with parent_order_id or STOP_LOSS/TAKE_PROFIT (not short entries).
    Short closes: BUY with parent_order_id or STOP_LOSS/TAKE_PROFIT.

    Manual or exchange-synced holdings (trade_signal_id IS NULL) are excluded.

    This function works at the symbol/base level:
    - If symbol is "ADA_USDT" -> analiza solo ese par.
    - If symbol is "ADA"      -> analiza todos los pares "ADA_*".
    """
    pending_statuses = [
        OrderStatusEnum.NEW,
        OrderStatusEnum.ACTIVE,
        OrderStatusEnum.PARTIALLY_FILLED,
    ]
    pending_enum = getattr(OrderStatusEnum, "PENDING", None)
    if pending_enum is not None:
        pending_statuses.append(pending_enum)

    symbol_filter = _normalized_symbol_filter(symbol)
    bot_entry_filter = _bot_main_entry_filter()
    order_time = (
        ExchangeOrder.exchange_create_time.asc(),
        ExchangeOrder.created_at.asc(),
        ExchangeOrder.id.asc(),
    )

    # --- Long side: pending + filled BUY entries net of long-close SELLs ---
    pending_buy_orders = db.query(ExchangeOrder).filter(
        symbol_filter,
        ExchangeOrder.side == OrderSideEnum.BUY,
        ExchangeOrder.status.in_(pending_statuses),
        bot_entry_filter,
    ).all()
    pending_buy_count = len(pending_buy_orders)

    filled_buy_orders = (
        db.query(ExchangeOrder)
        .filter(
            symbol_filter,
            ExchangeOrder.side == OrderSideEnum.BUY,
            ExchangeOrder.status == OrderStatusEnum.FILLED,
            bot_entry_filter,
        )
        .order_by(*order_time)
        .all()
    )
    filled_buy_qty = sum(_order_filled_quantity(o) for o in filled_buy_orders)

    filled_long_close_sells = (
        db.query(ExchangeOrder)
        .filter(
            symbol_filter,
            ExchangeOrder.status == OrderStatusEnum.FILLED,
            _long_close_sell_filter(),
        )
        .order_by(*order_time)
        .all()
    )
    filled_long_close_sell_qty = sum(_order_filled_quantity(o) for o in filled_long_close_sells)
    long_net_qty = max(filled_buy_qty - filled_long_close_sell_qty, 0.0)

    dust_price = last_price if last_price is not None else _infer_symbol_price(filled_buy_orders)

    if _is_position_dust(
        long_net_qty,
        min_position_qty=min_position_qty,
        min_position_usd=min_position_usd,
        last_price=dust_price,
    ):
        logger.info(
            "[OPEN_POSITION_COUNT] symbol=%s long_net_qty=%.8f treated as dust "
            "(min_qty=%s min_usd=%s price=%s)",
            symbol,
            long_net_qty,
            min_position_qty,
            min_position_usd,
            dust_price,
        )
        long_filled_positions = 0
    else:
        long_filled_positions = _estimate_filled_open_positions(
            long_net_qty,
            filled_buy_orders,
            filled_long_close_sell_qty,
            symbol=symbol,
            side_label="long",
        )

    # --- Short side: pending + filled SELL entries net of short-close BUYs ---
    pending_sell_orders = db.query(ExchangeOrder).filter(
        symbol_filter,
        ExchangeOrder.side == OrderSideEnum.SELL,
        ExchangeOrder.status.in_(pending_statuses),
        bot_entry_filter,
    ).all()
    pending_sell_count = len(pending_sell_orders)

    filled_sell_entry_orders = (
        db.query(ExchangeOrder)
        .filter(
            symbol_filter,
            ExchangeOrder.side == OrderSideEnum.SELL,
            ExchangeOrder.status == OrderStatusEnum.FILLED,
            bot_entry_filter,
        )
        .order_by(*order_time)
        .all()
    )
    filled_sell_entry_qty = sum(_order_filled_quantity(o) for o in filled_sell_entry_orders)

    filled_short_close_buys = (
        db.query(ExchangeOrder)
        .filter(
            symbol_filter,
            ExchangeOrder.status == OrderStatusEnum.FILLED,
            _short_close_buy_filter(),
        )
        .order_by(*order_time)
        .all()
    )
    filled_short_close_buy_qty = sum(_order_filled_quantity(o) for o in filled_short_close_buys)
    short_net_qty = max(filled_sell_entry_qty - filled_short_close_buy_qty, 0.0)

    short_dust_price = dust_price if dust_price is not None else _infer_symbol_price(
        filled_sell_entry_orders
    )
    if _is_position_dust(
        short_net_qty,
        min_position_qty=min_position_qty,
        min_position_usd=min_position_usd,
        last_price=short_dust_price,
    ):
        logger.info(
            "[OPEN_POSITION_COUNT] symbol=%s short_net_qty=%.8f treated as dust "
            "(min_qty=%s min_usd=%s price=%s)",
            symbol,
            short_net_qty,
            min_position_qty,
            min_position_usd,
            short_dust_price,
        )
        short_filled_positions = 0
    else:
        short_filled_positions = _estimate_filled_open_positions(
            short_net_qty,
            filled_sell_entry_orders,
            filled_short_close_buy_qty,
            symbol=symbol,
            side_label="short",
        )

    total_open_positions = (
        pending_buy_count
        + long_filled_positions
        + pending_sell_count
        + short_filled_positions
    )

    avg_position_size = 0.0
    if filled_buy_qty > 0 and filled_buy_orders:
        avg_position_size = filled_buy_qty / len(filled_buy_orders)

    try:
        logger.info(
            "[OPEN_POSITION_DEBUG] base=%s pending_long=%s pending_short=%s "
            "sample_buy=%s sample_sell_entry=%s sample_long_close=%s sample_short_close=%s",
            symbol,
            pending_buy_count,
            pending_sell_count,
            [o.symbol for o in pending_buy_orders[:5]],
            [o.symbol for o in filled_sell_entry_orders[:5]],
            [o.symbol for o in filled_long_close_sells[:5]],
            [o.symbol for o in filled_short_close_buys[:5]],
        )
    except Exception:
        pass

    logger.info(
        "[OPEN_POSITION_COUNT] symbol=%s pending_long=%s pending_short=%s "
        "filled_buy=%s long_close_sell=%s long_net=%s long_pos=%s "
        "filled_sell_entry=%s short_close_buy=%s short_net=%s short_pos=%s "
        "final_positions=%s (avg_long_size=%s)",
        symbol,
        pending_buy_count,
        pending_sell_count,
        round(filled_buy_qty, 8),
        round(filled_long_close_sell_qty, 8),
        round(long_net_qty, 8),
        long_filled_positions,
        round(filled_sell_entry_qty, 8),
        round(filled_short_close_buy_qty, 8),
        round(short_net_qty, 8),
        short_filled_positions,
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


