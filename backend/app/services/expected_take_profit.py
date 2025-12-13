"""
Expected Take Profit Service

Calculates expected take profit for open positions by:
1. Rebuilding open lots from executed orders (FIFO)
2. Matching TP orders to lots (OCO first, then FIFO fallback)
3. Calculating expected profit per lot and aggregated
"""
import logging
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum

logger = logging.getLogger(__name__)


# Active statuses for TP orders (orders that can still execute)
ACTIVE_TP_STATUSES = [
    OrderStatusEnum.NEW,
    OrderStatusEnum.ACTIVE,
    OrderStatusEnum.PARTIALLY_FILLED,
]

# Executed status for orders that have filled
EXECUTED_STATUS = OrderStatusEnum.FILLED


class OpenLot:
    """Represents an open lot (remaining quantity from a BUY order)"""
    def __init__(
        self,
        symbol: str,
        buy_order_id: str,
        buy_time: datetime,
        buy_price: Decimal,
        lot_qty: Decimal,
        parent_order_id: Optional[str] = None,
        oco_group_id: Optional[str] = None,
    ):
        self.symbol = symbol
        self.buy_order_id = buy_order_id
        self.buy_time = buy_time
        self.buy_price = buy_price
        self.lot_qty = lot_qty
        self.parent_order_id = parent_order_id
        self.oco_group_id = oco_group_id
        self.matched_tp = None  # Will hold matched TP order
        self.match_origin = None  # "OCO" or "FIFO"


def rebuild_open_lots(db: Session, symbol: str) -> List[OpenLot]:
    """
    Rebuild open lots from executed orders using FIFO logic.
    
    Args:
        db: Database session
        symbol: Symbol to process (can be "BTC" or "BTC_USDT" format)
        
    Returns:
        List of OpenLot objects representing remaining open quantity
    """
    # Build symbol variants to search for
    # Portfolio might give us "BTC" but orders are stored as "BTC_USDT"
    symbol_variants = [symbol]
    if '_' not in symbol:
        # If symbol is just the base currency (e.g., "BTC"), try common pairs
        symbol_variants.extend([
            f"{symbol}_USDT",
            f"{symbol}_USD",
        ])
    else:
        # If symbol already has a pair, try variants (USDT <-> USD)
        if symbol.endswith('_USDT'):
            symbol_variants.append(symbol.replace('_USDT', '_USD'))
        elif symbol.endswith('_USD'):
            symbol_variants.append(symbol.replace('_USD', '_USDT'))
    
    # Try exact match first
    executed_orders = db.query(ExchangeOrder).filter(
        ExchangeOrder.symbol.in_(symbol_variants),
        ExchangeOrder.status == EXECUTED_STATUS
    ).order_by(ExchangeOrder.exchange_create_time.asc()).all()
    
    if not executed_orders:
        # Try LIKE match for symbols starting with base currency (e.g., "BTC_%")
        base_currency = symbol.split('_')[0] if '_' in symbol else symbol
        executed_orders = db.query(ExchangeOrder).filter(
            ExchangeOrder.symbol.like(f"{base_currency}_%"),
            ExchangeOrder.status == EXECUTED_STATUS
        ).order_by(ExchangeOrder.exchange_create_time.asc()).all()
    
    if not executed_orders:
        return []
    
    # Split into buys and sells
    buys = [
        o for o in executed_orders
        if o.side == OrderSideEnum.BUY and (o.cumulative_quantity or o.quantity)
    ]
    sells = [
        o for o in executed_orders
        if o.side == OrderSideEnum.SELL and (o.cumulative_quantity or o.quantity)
    ]
    
    # Track remaining sell quantities (don't modify original objects)
    sell_remaining = {
        sell.exchange_order_id: Decimal(str(sell.cumulative_quantity or sell.quantity))
        for sell in sells
    }
    
    # Apply FIFO: track remaining quantity on each buy
    open_lots: List[OpenLot] = []
    
    for buy in buys:
        remaining_qty = Decimal(str(buy.cumulative_quantity or buy.quantity))
        
        # Apply sells in FIFO order (oldest first)
        for sell in sells:
            if remaining_qty <= 0:
                break
            
            sell_id = sell.exchange_order_id
            sell_qty = sell_remaining.get(sell_id, Decimal("0"))
            
            if sell_qty <= 0:
                continue
            
            # How much of this sell applies to this buy?
            qty_to_apply = min(remaining_qty, sell_qty)
            remaining_qty -= qty_to_apply
            sell_remaining[sell_id] = sell_qty - qty_to_apply
        
        # If there's remaining quantity, it's an open lot
        if remaining_qty > 0:
            buy_price = Decimal(str(buy.price or buy.avg_price or 0))
            buy_time = buy.exchange_create_time or buy.created_at
            
            if buy_price > 0:  # Only add if we have a valid price
                # Use the actual symbol from the order, not the input symbol
                order_symbol = buy.symbol
                open_lots.append(OpenLot(
                    symbol=order_symbol,  # Use order's symbol for consistency
                    buy_order_id=buy.exchange_order_id,
                    buy_time=buy_time,
                    buy_price=buy_price,
                    lot_qty=remaining_qty,
                    parent_order_id=buy.parent_order_id,
                    oco_group_id=buy.oco_group_id,
                ))
    
    return open_lots


def get_active_tp_orders(db: Session, symbol: str) -> List[ExchangeOrder]:
    """
    Get active take profit orders for a symbol.
    
    Args:
        db: Database session
        symbol: Symbol to filter (can be "BTC" or "BTC_USDT" format)
        
    Returns:
        List of active TP orders (NEW, ACTIVE, or PARTIALLY_FILLED)
    """
    # Build symbol variants to search for
    symbol_variants = [symbol]
    if '_' not in symbol:
        # If symbol is just the base currency (e.g., "BTC"), try common pairs
        symbol_variants.extend([
            f"{symbol}_USDT",
            f"{symbol}_USD",
        ])
    else:
        # If symbol already has a pair, try variants (USDT <-> USD)
        if symbol.endswith('_USDT'):
            symbol_variants.append(symbol.replace('_USDT', '_USD'))
        elif symbol.endswith('_USD'):
            symbol_variants.append(symbol.replace('_USD', '_USDT'))
    
    # Try exact match first
    tp_orders = db.query(ExchangeOrder).filter(
        ExchangeOrder.symbol.in_(symbol_variants),
        ExchangeOrder.side == OrderSideEnum.SELL,
        ExchangeOrder.status.in_(ACTIVE_TP_STATUSES),
        or_(
            ExchangeOrder.order_role == "TAKE_PROFIT",
            ExchangeOrder.order_type.in_(["TAKE_PROFIT", "TAKE_PROFIT_LIMIT"])
        )
    ).order_by(ExchangeOrder.exchange_create_time.asc()).all()
    
    if not tp_orders:
        # Try LIKE match for symbols starting with base currency (e.g., "BTC_%")
        base_currency = symbol.split('_')[0] if '_' in symbol else symbol
        tp_orders = db.query(ExchangeOrder).filter(
            ExchangeOrder.symbol.like(f"{base_currency}_%"),
            ExchangeOrder.side == OrderSideEnum.SELL,
            ExchangeOrder.status.in_(ACTIVE_TP_STATUSES),
            or_(
                ExchangeOrder.order_role == "TAKE_PROFIT",
                ExchangeOrder.order_type.in_(["TAKE_PROFIT", "TAKE_PROFIT_LIMIT"])
            )
        ).order_by(ExchangeOrder.exchange_create_time.asc()).all()
    
    return tp_orders


def _normalize_symbol(symbol: str) -> str:
    """
    Normalize symbol by treating USD and USDT as equivalent.
    Returns the base currency (e.g., "BTC" for both "BTC_USD" and "BTC_USDT").
    """
    if not symbol:
        return symbol
    
    # If symbol has USD or USDT, extract base currency
    if '_' in symbol:
        base = symbol.split('_')[0]
        # Treat USD and USDT as equivalent
        return base
    return symbol


def match_tp_orders_oco(
    lots: List[OpenLot],
    tp_orders: List[ExchangeOrder]
) -> Tuple[List[OpenLot], List[OpenLot], List[ExchangeOrder]]:
    """
    Match TP orders to lots using OCO linking (first priority).
    Supports:
    1. Single TP order matching a single lot (exact quantity match)
    2. Multiple TP orders from the same OCO group matching a single large lot (sum of TP quantities matches lot quantity)
    
    USD and USDT are treated as equivalent (same base currency).
    
    Args:
        lots: List of open lots
        tp_orders: List of active TP orders
        
    Returns:
        Tuple of (matched_lots, unmatched_lots, remaining_tp_orders)
    """
    matched_lots = []
    used_tp_ids = set()
    
    for lot in lots:
        if not lot.oco_group_id:
            # No OCO group, skip OCO matching for this lot
            continue
        
        lot_base = _normalize_symbol(lot.symbol)
        
        # Find all TP orders in the same OCO group with matching symbol base
        matching_tps = []
        for tp in tp_orders:
            if tp.exchange_order_id in used_tp_ids:
                continue
            
            tp_base = _normalize_symbol(tp.symbol)
            
            # Check OCO match conditions (including symbol base match - USD/USDT are equivalent)
            if (tp.oco_group_id == lot.oco_group_id and
                tp_base == lot_base and
                tp.side == OrderSideEnum.SELL and
                tp.status in ACTIVE_TP_STATUSES):
                
                # Check that TP was created after or close to buy time
                # Skip this check for virtual lots (they represent current portfolio positions)
                # We check if parent_order_id is None, which indicates a virtual lot
                if lot.parent_order_id is not None:
                    tp_time = tp.exchange_create_time or tp.created_at
                    if tp_time and lot.buy_time and tp_time < lot.buy_time:
                        continue  # TP was created before this lot, skip
                
                # Calculate remaining quantity
                tp_qty = Decimal(str(tp.quantity))
                tp_filled = Decimal(str(tp.cumulative_quantity or 0))
                tp_remaining = tp_qty - tp_filled
                
                if tp_remaining > 0:
                    matching_tps.append((tp, tp_remaining))
        
        if not matching_tps:
            continue  # No matching TPs found for this lot
        
        # Sort matching TPs by creation time (oldest first) to maintain FIFO within OCO group
        matching_tps.sort(key=lambda x: (x[0].exchange_create_time or x[0].created_at or datetime.min.replace(tzinfo=timezone.utc)))
        
        # Strategy 1: Try exact match with a single TP order
        single_match_found = False
        for tp, tp_remaining in matching_tps:
            if abs(tp_remaining - lot.lot_qty) < Decimal("0.00000001"):
                # Exact match found
                lot.matched_tp = tp
                lot.match_origin = "OCO"
                used_tp_ids.add(tp.exchange_order_id)
                matched_lots.append(lot)
                single_match_found = True
                logger.info(f"OCO matched: lot {lot.buy_order_id[:15]}... (qty={float(lot.lot_qty):.8f}) to TP {tp.exchange_order_id[:15]}... (qty={float(tp_remaining):.8f})")
                break
        
        if single_match_found:
            continue  # Lot matched, move to next lot
        
        # Strategy 2: Try matching multiple TP orders from the same OCO group to cover the lot
        # This handles cases where a large buy was split into multiple small TP orders
        accumulated_tp_qty = Decimal("0")
        selected_tps = []
        
        for tp, tp_remaining in matching_tps:
            if accumulated_tp_qty + tp_remaining <= lot.lot_qty:
                # This TP fits within the lot
                selected_tps.append(tp)
                accumulated_tp_qty += tp_remaining
                
                # If we've covered the entire lot, stop
                if abs(accumulated_tp_qty - lot.lot_qty) < Decimal("0.00000001"):
                    break
            elif accumulated_tp_qty < lot.lot_qty:
                # This TP would exceed, but we haven't covered the lot yet
                # Check if within tolerance (10% - OCO groups should be close)
                diff = (accumulated_tp_qty + tp_remaining) - lot.lot_qty
                tolerance = lot.lot_qty * Decimal("0.10")
                
                if diff <= tolerance:
                    # Within tolerance, add this TP
                    selected_tps.append(tp)
                    accumulated_tp_qty += tp_remaining
                break  # Stop here
        
        # If we found TPs that cover a significant portion of the lot (>= 90% for OCO groups)
        if selected_tps and accumulated_tp_qty >= lot.lot_qty * Decimal("0.90"):
            # Use the first TP as the primary match (for reporting purposes)
            lot.matched_tp = selected_tps[0]
            lot.match_origin = "OCO"
            
            # Store additional TPs in a custom attribute for later processing in details
            if len(selected_tps) > 1:
                lot._additional_tp_orders = selected_tps[1:]
            
            # Mark all selected TPs as used
            for tp in selected_tps:
                used_tp_ids.add(tp.exchange_order_id)
            
            matched_lots.append(lot)
            logger.info(f"OCO matched: lot {lot.buy_order_id[:15]}... (qty={float(lot.lot_qty):.8f}) to {len(selected_tps)} TP order(s) from same OCO group (total: {float(accumulated_tp_qty):.8f})")
    
    # Return matched lots and unused TP orders
    unmatched_lots = [lot for lot in lots if lot.matched_tp is None]
    remaining_tps = [tp for tp in tp_orders if tp.exchange_order_id not in used_tp_ids]
    
    return matched_lots, unmatched_lots, remaining_tps


def match_tp_orders_fifo(
    lots: List[OpenLot],
    tp_orders: List[ExchangeOrder]
) -> List[OpenLot]:
    """
    Match TP orders to lots using FIFO logic (fallback).
    
    This matches TP orders to lots in FIFO order, allowing:
    1. Exact match: TP qty = lot qty
    2. Partial match: TP qty matches sum of multiple lots (in FIFO order)
    
    Args:
        lots: List of unmatched open lots (sorted by buy time)
        tp_orders: List of remaining active TP orders
        
    Returns:
        List of lots with TP matches added
    """
    used_tp_ids = set()
    
    # Sort lots by buy time (oldest first)
    lots_sorted = sorted(lots, key=lambda l: l.buy_time or datetime.min.replace(tzinfo=timezone.utc))
    
    # Sort TP orders by creation time (oldest first)
    tp_orders_sorted = sorted(tp_orders, key=lambda tp: tp.exchange_create_time or tp.created_at or datetime.min.replace(tzinfo=timezone.utc))
    
    # Strategy 1: Match multiple small lots to a single large TP order
    # Try to match each TP order to one or more lots
    for tp in tp_orders_sorted:
        if tp.exchange_order_id in used_tp_ids:
            continue
        
        if tp.status not in ACTIVE_TP_STATUSES:
            continue
        
        # Get TP remaining quantity
        tp_qty = Decimal(str(tp.quantity))
        tp_filled = Decimal(str(tp.cumulative_quantity or 0))
        tp_remaining = tp_qty - tp_filled
        
        if tp_remaining <= 0:
            continue
        
        # Normalize TP symbol base (USD/USDT are equivalent)
        tp_base = _normalize_symbol(tp.symbol)
        
        # Find lots that match this TP (try exact match first, then partial match)
        # Allow matching when TP covers all available lots (TP qty >= sum of lots)
        # USD and USDT are treated as equivalent (same base currency)
        matched_lots_for_tp = []
        accumulated_qty = Decimal("0")
        
        for lot in lots_sorted:
            if lot.matched_tp is not None:
                continue  # Already matched via OCO or another TP
            
            # Check if symbol bases match (USD/USDT are equivalent)
            lot_base = _normalize_symbol(lot.symbol)
            if lot_base != tp_base:
                continue  # Different base currency, skip
            
            # Check if TP was created after buy time
            # Skip this check for virtual lots (lots without parent_order_id are virtual)
            # Virtual lots represent current portfolio positions, not actual orders
            # So TP orders should be able to match regardless of creation time
            if lot.parent_order_id is not None:
                tp_time = tp.exchange_create_time or tp.created_at
                if tp_time and lot.buy_time and tp_time < lot.buy_time:
                    continue  # TP was created before this lot, skip
            
            # Try to match this lot (or accumulate for partial match)
            lot_qty = lot.lot_qty
            
            # Check if we can add this lot to the match
            # Allow if accumulated + lot <= TP (TP covers this lot)
            # Also allow if accumulated + lot > TP but we're close (within 10% tolerance)
            diff_after_adding = (accumulated_qty + lot_qty) - tp_remaining
            tolerance = tp_remaining * Decimal("0.10")  # 10% tolerance
            
            if accumulated_qty + lot_qty <= tp_remaining:
                # TP fully covers this lot
                matched_lots_for_tp.append(lot)
                accumulated_qty += lot_qty
                
                # If we've matched exactly, break
                if abs(accumulated_qty - tp_remaining) < Decimal("0.00000001"):
                    break
            elif diff_after_adding <= tolerance:
                # Adding this lot would exceed TP, but within tolerance
                # Only add if we haven't matched anything yet (prefer exact matches)
                if not matched_lots_for_tp:
                    matched_lots_for_tp.append(lot)
                    accumulated_qty += lot_qty
                break  # Stop here, don't add more lots
        
        # If we found matching lots (exact or approximate), assign TP to them
        if matched_lots_for_tp:
            # Check if match is close enough (allow tolerance for floating point errors or partial coverage)
            # TP can cover exactly or be slightly larger (within 15% tolerance)
            diff = abs(accumulated_qty - tp_remaining)
            tolerance_abs = Decimal("1.0")  # Allow 1.0 unit difference
            tolerance_pct = tp_remaining * Decimal("0.15")  # Allow 15% difference
            
            if diff <= tolerance_abs or diff <= tolerance_pct or accumulated_qty <= tp_remaining:
                for lot in matched_lots_for_tp:
                    lot.matched_tp = tp
                    lot.match_origin = "FIFO"
                used_tp_ids.add(tp.exchange_order_id)
                logger.info(f"FIFO matched TP {tp.exchange_order_id[:15]}... ({float(tp_remaining):.8f}) to {len(matched_lots_for_tp)} lot(s) (total: {float(accumulated_qty):.8f})")
    
    # Strategy 2: Match multiple small TP orders to a single large lot
    # This handles the case where we have one large lot and many small TP orders
    # (e.g., BTC virtual lot with many small TP orders)
    for lot in lots_sorted:
        if lot.matched_tp is not None:
            continue  # Already matched
        
        lot_base = _normalize_symbol(lot.symbol)
        lot_qty = lot.lot_qty
        
        # Collect matching TP orders that can cover this lot
        matching_tps = []
        accumulated_tp_qty = Decimal("0")
        
        for tp in tp_orders_sorted:
            if tp.exchange_order_id in used_tp_ids:
                continue
            
            if tp.status not in ACTIVE_TP_STATUSES:
                continue
            
            tp_base = _normalize_symbol(tp.symbol)
            if tp_base != lot_base:
                continue  # Different base currency
            
            # Check if TP was created after buy time
            # Skip this check for virtual lots (lots without parent_order_id are virtual)
            # Virtual lots represent current portfolio positions, not actual orders
            # So TP orders should be able to match regardless of creation time
            if lot.parent_order_id is not None:
                tp_time = tp.exchange_create_time or tp.created_at
                if tp_time and lot.buy_time and tp_time < lot.buy_time:
                    continue  # TP was created before this lot, skip
            
            tp_qty = Decimal(str(tp.quantity))
            tp_filled = Decimal(str(tp.cumulative_quantity or 0))
            tp_remaining = tp_qty - tp_filled
            
            if tp_remaining <= 0:
                continue
            
            # Check if adding this TP would exceed the lot qty
            if accumulated_tp_qty + tp_remaining <= lot_qty:
                # This TP fits within the lot
                matching_tps.append(tp)
                accumulated_tp_qty += tp_remaining
                
                # If we've covered the entire lot, stop
                if abs(accumulated_tp_qty - lot_qty) < Decimal("0.00000001"):
                    break
            elif accumulated_tp_qty < lot_qty:
                # This TP would exceed, but we haven't covered the lot yet
                # Check if within tolerance (15%)
                diff = (accumulated_tp_qty + tp_remaining) - lot_qty
                tolerance = lot_qty * Decimal("0.15")
                
                if diff <= tolerance:
                    # Within tolerance, add this TP
                    matching_tps.append(tp)
                    accumulated_tp_qty += tp_remaining
                break  # Stop here
        
        # If we found matching TPs that cover a significant portion of the lot (>= 85%)
        if matching_tps and accumulated_tp_qty >= lot_qty * Decimal("0.85"):
            # Use the first TP as the primary match (for reporting purposes)
            lot.matched_tp = matching_tps[0]
            lot.match_origin = "FIFO"
            
            # Store additional TPs in a custom attribute for later processing in details
            if len(matching_tps) > 1:
                lot._additional_tp_orders = matching_tps[1:]
            
            # Mark all selected TPs as used
            for tp in matching_tps:
                used_tp_ids.add(tp.exchange_order_id)
            
            logger.info(f"FIFO matched lot {lot.buy_order_id[:15]}... (qty={float(lot_qty):.8f}) to {len(matching_tps)} TP order(s) (total: {float(accumulated_tp_qty):.8f})")
    
    return lots


def calculate_expected_profit(
    buy_price: Decimal,
    tp_price: Decimal,
    quantity: Decimal
) -> Tuple[Decimal, Decimal]:
    """
    Calculate expected profit in absolute and percentage terms.
    
    Args:
        buy_price: Price at which position was bought
        tp_price: Take profit limit price
        quantity: Quantity of the position
        
    Returns:
        Tuple of (expected_profit_absolute, expected_profit_percentage)
    """
    if buy_price <= 0 or tp_price <= 0 or quantity <= 0:
        return Decimal("0"), Decimal("0")
    
    # Expected profit in quote currency
    expected_profit = (tp_price - buy_price) * quantity
    
    # Expected profit percentage
    expected_profit_pct = ((tp_price / buy_price) - Decimal("1")) * Decimal("100")
    
    return expected_profit, expected_profit_pct


def get_expected_take_profit_summary(
    db: Session,
    portfolio_assets: List[Dict],
    market_prices: Dict[str, float]
) -> Dict[str, Dict]:
    """
    Get expected take profit summary for all symbols with open positions.
    
    Args:
        db: Database session
        portfolio_assets: List of portfolio asset dicts (can be "balances" or "assets" format)
        market_prices: Dict mapping symbol to current market price
        
    Returns:
        Dict mapping symbol to summary data
    """
    results = {}
    logger.info(f"Expected TP: Processing {len(portfolio_assets)} portfolio assets")
    
    for asset in portfolio_assets:
        # Handle both "balances" format (currency) and "assets" format (coin)
        symbol = (asset.get("coin") or asset.get("currency") or "").upper()
        balance = Decimal(str(asset.get("balance", 0) or 0))
        
        # Filter out fiat currencies (USD, EUR) as base currencies - we don't trade with them
        # Extract base currency (first part before underscore)
        base_currency = symbol.split('_')[0] if '_' in symbol else symbol
        if base_currency in ['USD', 'EUR', 'USDT']:
            logger.debug(f"Expected TP: Skipping {symbol} - fiat/stablecoin as base currency (we don't trade with these)")
            continue
        
        if balance <= 0:
            logger.debug(f"Expected TP: Skipping {symbol} - balance <= 0")
            continue
        
        # Get current price
        current_price = market_prices.get(symbol, 0)
        if current_price <= 0:
            # Try to get from asset data
            value_usd = asset.get("value_usd", 0) or asset.get("usd_value", 0) or 0
            if balance > 0 and value_usd > 0:
                current_price = float(value_usd) / float(balance)
        
        if current_price <= 0:
            logger.debug(f"Expected TP: Skipping {symbol} - no price available (balance={balance}, value_usd={asset.get('value_usd', 0)})")
            continue  # Skip if we can't determine price
        
        # Rebuild open lots from executed orders (this gives us the net open quantity per lot)
        logger.info(f"Expected TP: Rebuilding open lots for {symbol} (balance={balance})")
        open_lots = rebuild_open_lots(db, symbol)
        
        # If no open lots found, check if there are active TP orders
        # In that case, create a virtual lot from the portfolio balance and TP order
        if not open_lots:
            logger.info(f"Expected TP: No open lots found for {symbol}, checking for active TP orders")
            # Try to find active TP orders for this symbol (try variants)
            symbol_variants = [symbol]
            if '_' not in symbol:
                symbol_variants.extend([f"{symbol}_USDT", f"{symbol}_USD"])
            else:
                if symbol.endswith('_USDT'):
                    symbol_variants.append(symbol.replace('_USDT', '_USD'))
                elif symbol.endswith('_USD'):
                    symbol_variants.append(symbol.replace('_USD', '_USDT'))
            
            # Get TP orders for all variants (USD and USDT are equivalent)
            # Combine all TP orders from both USD and USDT variants
            all_tp_orders = []
            tp_orders_dict = {}
            
            # Get base currency for normalization
            symbol_base = _normalize_symbol(symbol)
            
            if symbol_base:
                # Get TP orders for both USD and USDT variants
                tp_usd = get_active_tp_orders(db, f"{symbol_base}_USD")
                tp_usdt = get_active_tp_orders(db, f"{symbol_base}_USDT")
                
                # Combine and deduplicate
                for tp in tp_usd + tp_usdt:
                    tp_orders_dict[tp.exchange_order_id] = tp
                all_tp_orders = list(tp_orders_dict.values())
            
            # If still no TP orders found, try original symbol and variants
            if not all_tp_orders:
                tp_orders = get_active_tp_orders(db, symbol)
                if tp_orders:
                    all_tp_orders = tp_orders
                else:
                    # Try variants
                    for variant in symbol_variants:
                        tp_orders = get_active_tp_orders(db, variant)
                        if tp_orders:
                            # Combine with existing (deduplicate)
                            for tp in tp_orders:
                                tp_orders_dict[tp.exchange_order_id] = tp
                            all_tp_orders = list(tp_orders_dict.values())
                            break
            
            tp_orders = all_tp_orders
            
            if tp_orders and balance > 0:
                # Create virtual lots from TP orders and portfolio balance
                logger.info(f"Expected TP: Found {len(tp_orders)} active TP orders for {symbol} without open lots, creating virtual lots from portfolio balance")
                
                # Determine which symbol to use for the virtual lot
                # Prefer the symbol that matches the TP orders (USD/USDT are equivalent, but use the one with most TP orders)
                tp_symbol_counts = {}
                for tp in tp_orders:
                    tp_sym = tp.symbol
                    tp_symbol_counts[tp_sym] = tp_symbol_counts.get(tp_sym, 0) + 1
                
                # Use the symbol with most TP orders, or default to the first TP order's symbol
                preferred_symbol = max(tp_symbol_counts.items(), key=lambda x: x[1])[0] if tp_symbol_counts else None
                
                # Calculate weighted average buy price from ALL filled BUY orders
                # This accounts for multiple purchase orders at different prices
                all_buy_orders = []
                
                if preferred_symbol:
                    # First try to find all BUY orders for the preferred symbol with valid prices
                    orders = db.query(ExchangeOrder).filter(
                        ExchangeOrder.symbol == preferred_symbol,
                        ExchangeOrder.side == OrderSideEnum.BUY,
                        ExchangeOrder.status == OrderStatusEnum.FILLED
                    ).order_by(ExchangeOrder.exchange_create_time.asc()).all()
                    
                    # Collect all orders with valid prices
                    for order in orders:
                        price = order.avg_price or order.price
                        # If price is None or 0, try to calculate from cumulative_value / cumulative_quantity
                        if (not price or price == 0) and hasattr(order, 'cumulative_value') and hasattr(order, 'cumulative_quantity'):
                            if order.cumulative_quantity and order.cumulative_quantity > 0:
                                if order.cumulative_value and order.cumulative_value > 0:
                                    price = order.cumulative_value / order.cumulative_quantity
                        if price and price > 0:
                            qty = Decimal(str(order.cumulative_quantity or order.quantity or 0))
                            if qty > 0:
                                all_buy_orders.append({
                                    'order': order,
                                    'price': Decimal(str(price)),
                                    'qty': qty
                                })
                
                # If not found, try all variants
                if not all_buy_orders:
                    orders = db.query(ExchangeOrder).filter(
                        ExchangeOrder.symbol.in_(symbol_variants),
                        ExchangeOrder.side == OrderSideEnum.BUY,
                        ExchangeOrder.status == OrderStatusEnum.FILLED
                    ).order_by(ExchangeOrder.exchange_create_time.asc()).all()
                    
                    # Collect all orders with valid prices
                    for order in orders:
                        price = order.avg_price or order.price
                        # If price is None or 0, try to calculate from cumulative_value / cumulative_quantity
                        if (not price or price == 0) and hasattr(order, 'cumulative_value') and hasattr(order, 'cumulative_quantity'):
                            if order.cumulative_quantity and order.cumulative_quantity > 0:
                                if order.cumulative_value and order.cumulative_value > 0:
                                    price = order.cumulative_value / order.cumulative_quantity
                        if price and price > 0:
                            qty = Decimal(str(order.cumulative_quantity or order.quantity or 0))
                            if qty > 0:
                                all_buy_orders.append({
                                    'order': order,
                                    'price': Decimal(str(price)),
                                    'qty': qty
                                })
                
                if all_buy_orders:
                    # Calculate weighted average buy price
                    total_value = sum(bo['price'] * bo['qty'] for bo in all_buy_orders)
                    total_qty = sum(bo['qty'] for bo in all_buy_orders)
                    weighted_avg_price = total_value / total_qty if total_qty > 0 else Decimal("0")
                    
                    # Use the most recent order for metadata (time, order_id, etc.)
                    most_recent_buy = max(all_buy_orders, key=lambda bo: bo['order'].exchange_create_time or bo['order'].created_at or datetime.min.replace(tzinfo=timezone.utc))
                    recent_buy = most_recent_buy['order']
                    
                    buy_time = recent_buy.exchange_create_time or recent_buy.created_at
                    if weighted_avg_price > 0:
                        # Use preferred_symbol if available (matches TP orders), otherwise use recent_buy.symbol
                        # This ensures the virtual lot symbol matches the TP orders' symbol for better matching
                        virtual_lot_symbol = preferred_symbol if preferred_symbol else recent_buy.symbol
                        
                        # Create virtual lot from portfolio balance with weighted average price
                        from datetime import datetime, timezone
                        virtual_lot = OpenLot(
                            symbol=virtual_lot_symbol,  # Use symbol that matches TP orders (USD/USDT are equivalent)
                            buy_order_id=recent_buy.exchange_order_id,  # Use most recent order ID for reference
                            buy_time=buy_time or datetime.now(timezone.utc),
                            buy_price=weighted_avg_price,  # Use weighted average price from all buy orders
                            lot_qty=Decimal(str(balance)),
                            parent_order_id=recent_buy.parent_order_id,
                            oco_group_id=recent_buy.oco_group_id,
                        )
                        open_lots = [virtual_lot]
                        logger.info(f"Expected TP: Created virtual lot for {symbol} from portfolio balance: qty={balance}, weighted_avg_price={weighted_avg_price} (from {len(all_buy_orders)} buy orders), symbol={virtual_lot_symbol}, buy_order_id={recent_buy.exchange_order_id[:15]}... (preferred symbol: {preferred_symbol})")
            
            # If still no open lots but we have balance, try to create a virtual lot without TP orders
            # This allows showing coins with balance but no TP protection (uncovered position)
            if not open_lots and balance > 0:
                logger.info(f"Expected TP: No open lots or TP orders for {symbol}, but has balance {balance} - creating virtual lot to show uncovered position")
                
                # Try to find a recent BUY order to get buy price
                symbol_variants = [symbol]
                if '_' not in symbol:
                    symbol_variants.extend([f"{symbol}_USDT", f"{symbol}_USD"])
                else:
                    if symbol.endswith('_USDT'):
                        symbol_variants.append(symbol.replace('_USDT', '_USD'))
                    elif symbol.endswith('_USD'):
                        symbol_variants.append(symbol.replace('_USD', '_USDT'))
                
                # Calculate weighted average buy price from ALL filled BUY orders
                all_buy_orders = []
                for variant in symbol_variants:
                    # Get all filled BUY orders for this variant
                    orders = db.query(ExchangeOrder).filter(
                        ExchangeOrder.symbol == variant,
                        ExchangeOrder.side == OrderSideEnum.BUY,
                        ExchangeOrder.status == OrderStatusEnum.FILLED
                    ).order_by(ExchangeOrder.exchange_create_time.asc()).all()
                    
                    # Collect all orders with valid prices
                    for order in orders:
                        # Try to get price from various fields
                        price = order.avg_price or order.price
                        
                        # If price is None or 0, try to calculate from cumulative_value / cumulative_quantity
                        if (not price or price == 0) and hasattr(order, 'cumulative_value') and hasattr(order, 'cumulative_quantity'):
                            if order.cumulative_quantity and order.cumulative_quantity > 0:
                                if order.cumulative_value and order.cumulative_value > 0:
                                    price = order.cumulative_value / order.cumulative_quantity
                        
                        # If we found a valid price, add to list
                        if price and price > 0:
                            qty = Decimal(str(order.cumulative_quantity or order.quantity or 0))
                            if qty > 0:
                                all_buy_orders.append({
                                    'order': order,
                                    'price': Decimal(str(price)),
                                    'qty': qty
                                })
                
                if all_buy_orders:
                    # Calculate weighted average buy price
                    total_value = sum(bo['price'] * bo['qty'] for bo in all_buy_orders)
                    total_qty = sum(bo['qty'] for bo in all_buy_orders)
                    weighted_avg_price = total_value / total_qty if total_qty > 0 else Decimal("0")
                    
                    # Use the most recent order for metadata (time, order_id, etc.)
                    most_recent_buy = max(all_buy_orders, key=lambda bo: bo['order'].exchange_create_time or bo['order'].created_at or datetime.min.replace(tzinfo=timezone.utc))
                    recent_buy = most_recent_buy['order']
                    
                    buy_time = recent_buy.exchange_create_time or recent_buy.created_at
                    if weighted_avg_price > 0:
                        from datetime import datetime, timezone
                        virtual_lot = OpenLot(
                            symbol=recent_buy.symbol,  # Use symbol from order
                            buy_order_id=recent_buy.exchange_order_id,
                            buy_time=buy_time or datetime.now(timezone.utc),
                            buy_price=weighted_avg_price,  # Use weighted average price from all buy orders
                            lot_qty=Decimal(str(balance)),
                            parent_order_id=recent_buy.parent_order_id,
                            oco_group_id=recent_buy.oco_group_id,
                        )
                        open_lots = [virtual_lot]
                        logger.info(f"Expected TP: Created uncovered virtual lot for {symbol}: qty={balance}, weighted_avg_price={weighted_avg_price} (from {len(all_buy_orders)} buy orders), symbol={recent_buy.symbol}, order_id={recent_buy.exchange_order_id[:15]}...")
                    else:
                        # Buy price is 0 or None, use current price as fallback
                        if current_price > 0:
                            from datetime import datetime, timezone
                            virtual_lot = OpenLot(
                                symbol=recent_buy.symbol,  # Use symbol from order
                                buy_order_id=recent_buy.exchange_order_id,
                                buy_time=buy_time or datetime.now(timezone.utc),
                                buy_price=Decimal(str(current_price)),  # Use current price as fallback
                                lot_qty=Decimal(str(balance)),
                                parent_order_id=recent_buy.parent_order_id,
                                oco_group_id=recent_buy.oco_group_id,
                            )
                            open_lots = [virtual_lot]
                            logger.info(f"Expected TP: Created uncovered virtual lot for {symbol} with current price as buy price (buy order price unavailable): qty={balance}, price={current_price}, symbol={recent_buy.symbol}")
                
                # If still no virtual lot created (no recent BUY order or no valid price), create with current price
                if not open_lots and current_price > 0:
                    # No recent BUY order found, still create virtual lot with current price as buy price (fallback)
                    # This allows showing the position even if we don't know the buy price
                    from datetime import datetime, timezone
                    virtual_lot = OpenLot(
                        symbol=symbol,
                        buy_order_id=None,
                        buy_time=datetime.now(timezone.utc),
                        buy_price=Decimal(str(current_price)),  # Use current price as fallback
                        lot_qty=Decimal(str(balance)),
                        parent_order_id=None,
                        oco_group_id=None,
                    )
                    open_lots = [virtual_lot]
                    logger.info(f"Expected TP: Created uncovered virtual lot for {symbol} with current price as buy price (no historical BUY order found): qty={balance}, price={current_price}")
            
            if not open_lots:
                logger.info(f"Expected TP: No open lots found for {symbol} and no balance/price, skipping")
                continue
        
        # Use the actual symbol from the first lot (which comes from orders)
        # This ensures we use "BTC_USDT" instead of just "BTC"
        actual_symbol = open_lots[0].symbol
        logger.info(f"Expected TP: Found {len(open_lots)} open lots for {symbol} (actual symbol: {actual_symbol})")
        
        # Get active TP orders - search for both USD and USDT variants since they're equivalent
        # Normalize symbol base (treat USD/USDT as equivalent)
        symbol_base = _normalize_symbol(actual_symbol)
        tp_orders = []
        tp_orders_dict = {}
        
        if symbol_base:
            # Get TP orders for both USD and USDT variants (they're the same currency)
            tp_usd = get_active_tp_orders(db, f"{symbol_base}_USD")
            tp_usdt = get_active_tp_orders(db, f"{symbol_base}_USDT")
            
            # Combine and deduplicate by order ID
            for tp in tp_usd + tp_usdt:
                tp_orders_dict[tp.exchange_order_id] = tp
            tp_orders = list(tp_orders_dict.values())
        
        # If still no TP orders, try using actual_symbol directly
        if not tp_orders:
            tp_orders = get_active_tp_orders(db, actual_symbol)
        
        logger.info(f"Expected TP: Found {len(tp_orders)} active TP orders for {symbol} (base: {symbol_base}, actual: {actual_symbol}) - USD/USDT combined")
        
        # Match TP orders (OCO first, then FIFO)
        oco_matched, unmatched_lots, remaining_tps = match_tp_orders_oco(open_lots, tp_orders)
        fifo_matched_lots = match_tp_orders_fifo(unmatched_lots, remaining_tps)
        
        # Combine all matched lots
        all_matched = oco_matched + [lot for lot in fifo_matched_lots if lot.matched_tp is not None]
        unmatched = [lot for lot in fifo_matched_lots if lot.matched_tp is None]
        
        # Calculate totals
        covered_qty = sum(float(lot.lot_qty) for lot in all_matched)
        uncovered_qty = sum(float(lot.lot_qty) for lot in unmatched)
        
        # Total net quantity from lots should match portfolio balance (approximately)
        total_lot_qty = sum(float(lot.lot_qty) for lot in open_lots)
        net_qty = max(float(balance), total_lot_qty)  # Use larger value
        
        # Calculate total expected profit and actual position value (at buy price)
        total_expected_profit = Decimal("0")
        actual_position_value = Decimal("0")
        
        for lot in all_matched:
            if lot.matched_tp:
                tp_price = Decimal(str(lot.matched_tp.price or 0))
                if tp_price > 0:
                    profit, _ = calculate_expected_profit(lot.buy_price, tp_price, lot.lot_qty)
                    total_expected_profit += profit
            # Add to actual position value (at buy price)
            actual_position_value += lot.buy_price * lot.lot_qty
        
        # Add unmatched lots to actual position value as well
        for lot in unmatched:
            actual_position_value += lot.buy_price * lot.lot_qty
        
        position_value = net_qty * current_price
        
        # Use actual_symbol for the result key and symbol field
        # This ensures consistency with order symbols (e.g., "BTC_USDT" instead of "BTC")
        results[actual_symbol] = {
            "symbol": actual_symbol,  # Use actual symbol from orders
            "net_qty": net_qty,
            "current_price": current_price,
            "position_value": position_value,
            "actual_position_value": float(actual_position_value),  # Value at buy price
            "covered_qty": covered_qty,
            "uncovered_qty": uncovered_qty,
            "total_expected_profit": float(total_expected_profit),
            "coverage_ratio": covered_qty / net_qty if net_qty > 0 else 0,
        }
    
    return results


def get_expected_take_profit_details(
    db: Session,
    symbol: str,
    current_price: float,
    portfolio_balance: float = 0.0,
    portfolio_summary: Dict = None
) -> Dict:
    """
    Get detailed expected take profit data for a specific symbol.
    
    Args:
        db: Database session
        symbol: Symbol to get details for
        current_price: Current market price for the symbol
        
    Returns:
        Dict with summary and detailed lot data
    """
    # Rebuild open lots
    open_lots = rebuild_open_lots(db, symbol)
    
    # If no open lots found, check if there are active TP orders
    # In that case, create a virtual lot from portfolio balance and TP order
    if not open_lots:
        logger.info(f"Expected TP Details: No open lots found for {symbol}, checking for active TP orders")
        # Try to find active TP orders for this symbol (try variants)
        symbol_variants = [symbol]
        if '_' not in symbol:
            symbol_variants.extend([f"{symbol}_USDT", f"{symbol}_USD"])
        else:
            if symbol.endswith('_USDT'):
                symbol_variants.append(symbol.replace('_USDT', '_USD'))
            elif symbol.endswith('_USD'):
                symbol_variants.append(symbol.replace('_USD', '_USDT'))
        
        # Get TP orders - search for both USD and USDT variants since they're equivalent
        symbol_base = _normalize_symbol(symbol)
        tp_orders = []
        
        if symbol_base:
            # Get TP orders for both USD and USDT variants
            tp_orders_usd = get_active_tp_orders(db, f"{symbol_base}_USD")
            tp_orders_usdt = get_active_tp_orders(db, f"{symbol_base}_USDT")
            
            # Combine and deduplicate by order ID
            tp_orders_dict = {}
            for tp in tp_orders_usd + tp_orders_usdt:
                tp_orders_dict[tp.exchange_order_id] = tp
            tp_orders = list(tp_orders_dict.values())
        
        # If still no TP orders found, try the original symbol
        if not tp_orders:
            tp_orders = get_active_tp_orders(db, symbol)
            
        # If still not found, try variants
        if not tp_orders:
            for variant in symbol_variants:
                tp_orders_temp = get_active_tp_orders(db, variant)
                if tp_orders_temp:
                    # Combine with existing (deduplicate)
                    tp_orders_dict = {tp.exchange_order_id: tp for tp in tp_orders}
                    for tp in tp_orders_temp:
                        tp_orders_dict[tp.exchange_order_id] = tp
                    tp_orders = list(tp_orders_dict.values())
                    if tp_orders:
                        break
        
        if tp_orders:
            # Get portfolio balance for this symbol
            if portfolio_summary is None:
                from app.services.portfolio_cache import get_portfolio_summary
                portfolio_summary = get_portfolio_summary(db)
            
            # Use provided balance if available, otherwise get from portfolio
            balance = Decimal("0")
            if portfolio_balance > 0:
                balance = Decimal(str(portfolio_balance))
            else:
                balances = portfolio_summary.get("balances", [])
                assets = portfolio_summary.get("assets", [])
                
                asset_balance = None
                # Try balances format
                for bal in balances:
                    currency = bal.get("currency", "").upper()
                    if currency == symbol or currency == symbol.split('_')[0]:
                        asset_balance = bal
                        break
                
                # Try assets format if not found
                if not asset_balance:
                    for asset in assets:
                        coin = asset.get("coin", "").upper()
                        if coin == symbol or coin == symbol.split('_')[0]:
                            asset_balance = asset
                            break
                
                if asset_balance:
                    bal_value = asset_balance.get("balance", 0) or asset_balance.get("value_usd", 0)
                    if bal_value and current_price > 0 and not asset_balance.get("balance", 0):
                        # Calculate balance from USD value
                        balance = Decimal(str(asset_balance.get("value_usd", 0))) / Decimal(str(current_price))
                    else:
                        balance = Decimal(str(bal_value or 0))
            
            if balance > 0:
                # Determine which symbol to use for the virtual lot
                # Prefer the symbol that matches the TP orders (USD/USDT are equivalent)
                tp_symbol_counts = {}
                for tp in tp_orders:
                    tp_sym = tp.symbol
                    tp_symbol_counts[tp_sym] = tp_symbol_counts.get(tp_sym, 0) + 1
                
                # Use the symbol with most TP orders, or default to the first TP order's symbol
                preferred_symbol = max(tp_symbol_counts.items(), key=lambda x: x[1])[0] if tp_symbol_counts else None
                
                # Calculate weighted average buy price from ALL filled BUY orders
                # This accounts for multiple purchase orders at different prices
                all_buy_orders = []
                
                if preferred_symbol:
                    # First try to find all BUY orders for the preferred symbol with valid prices
                    orders = db.query(ExchangeOrder).filter(
                        ExchangeOrder.symbol == preferred_symbol,
                        ExchangeOrder.side == OrderSideEnum.BUY,
                        ExchangeOrder.status == OrderStatusEnum.FILLED
                    ).order_by(ExchangeOrder.exchange_create_time.asc()).all()
                    
                    # Collect all orders with valid prices
                    for order in orders:
                        price = order.avg_price or order.price
                        # If price is None or 0, try to calculate from cumulative_value / cumulative_quantity
                        if (not price or price == 0) and hasattr(order, 'cumulative_value') and hasattr(order, 'cumulative_quantity'):
                            if order.cumulative_quantity and order.cumulative_quantity > 0:
                                if order.cumulative_value and order.cumulative_value > 0:
                                    price = order.cumulative_value / order.cumulative_quantity
                        if price and price > 0:
                            qty = Decimal(str(order.cumulative_quantity or order.quantity or 0))
                            if qty > 0:
                                all_buy_orders.append({
                                    'order': order,
                                    'price': Decimal(str(price)),
                                    'qty': qty
                                })
                
                # If not found, try all variants
                if not all_buy_orders:
                    orders = db.query(ExchangeOrder).filter(
                        ExchangeOrder.symbol.in_(symbol_variants),
                        ExchangeOrder.side == OrderSideEnum.BUY,
                        ExchangeOrder.status == OrderStatusEnum.FILLED
                    ).order_by(ExchangeOrder.exchange_create_time.asc()).all()
                    
                    # Collect all orders with valid prices
                    for order in orders:
                        price = order.avg_price or order.price
                        # If price is None or 0, try to calculate from cumulative_value / cumulative_quantity
                        if (not price or price == 0) and hasattr(order, 'cumulative_value') and hasattr(order, 'cumulative_quantity'):
                            if order.cumulative_quantity and order.cumulative_quantity > 0:
                                if order.cumulative_value and order.cumulative_value > 0:
                                    price = order.cumulative_value / order.cumulative_quantity
                        if price and price > 0:
                            qty = Decimal(str(order.cumulative_quantity or order.quantity or 0))
                            if qty > 0:
                                all_buy_orders.append({
                                    'order': order,
                                    'price': Decimal(str(price)),
                                    'qty': qty
                                })
                
                if all_buy_orders:
                    # Calculate weighted average buy price
                    total_value = sum(bo['price'] * bo['qty'] for bo in all_buy_orders)
                    total_qty = sum(bo['qty'] for bo in all_buy_orders)
                    weighted_avg_price = total_value / total_qty if total_qty > 0 else Decimal("0")
                    
                    # Use the most recent order for metadata (time, order_id, etc.)
                    most_recent_buy = max(all_buy_orders, key=lambda bo: bo['order'].exchange_create_time or bo['order'].created_at or datetime.min.replace(tzinfo=timezone.utc))
                    recent_buy = most_recent_buy['order']
                    
                    buy_time = recent_buy.exchange_create_time or recent_buy.created_at
                    if weighted_avg_price > 0:
                        # Use preferred_symbol if available (matches TP orders), otherwise use recent_buy.symbol
                        # This ensures the virtual lot symbol matches the TP orders' symbol for better matching
                        virtual_lot_symbol = preferred_symbol if preferred_symbol else recent_buy.symbol
                        
                        # Create virtual lot from portfolio balance with weighted average price
                        from datetime import datetime, timezone
                        virtual_lot = OpenLot(
                            symbol=virtual_lot_symbol,  # Use symbol that matches TP orders (USD/USDT are equivalent)
                            buy_order_id=recent_buy.exchange_order_id,  # Use most recent order ID for reference
                            buy_time=buy_time or datetime.now(timezone.utc),
                            buy_price=weighted_avg_price,  # Use weighted average price from all buy orders
                            lot_qty=balance,
                            parent_order_id=recent_buy.parent_order_id,
                            oco_group_id=recent_buy.oco_group_id,
                        )
                        open_lots = [virtual_lot]
                        logger.info(f"Expected TP Details: Created virtual lot for {symbol} from portfolio balance: qty={balance}, weighted_avg_price={weighted_avg_price} (from {len(all_buy_orders)} buy orders), symbol={virtual_lot_symbol}, buy_order_id={recent_buy.exchange_order_id[:15]}... (preferred symbol: {preferred_symbol})")
        
        if not open_lots:
            return {
                "symbol": symbol,
                "net_qty": 0,
                "current_price": current_price,
                "position_value": 0,
                "actual_position_value": 0,
                "covered_qty": 0,
                "uncovered_qty": 0,
                "total_expected_profit": 0,
                "matched_lots": [],
            }
    
    # Get active TP orders
    tp_orders = get_active_tp_orders(db, symbol)
    
    # Match TP orders (OCO first, then FIFO)
    oco_matched, unmatched_lots, remaining_tps = match_tp_orders_oco(open_lots, tp_orders)
    fifo_matched_lots = match_tp_orders_fifo(unmatched_lots, remaining_tps)
    
    # Combine all matched lots
    all_matched = oco_matched + [lot for lot in fifo_matched_lots if lot.matched_tp is not None]
    unmatched = [lot for lot in fifo_matched_lots if lot.matched_tp is None]
    
    # Build matched lot details (with grouping of orders executed at same time)
    matched_lot_details_raw = []
    total_expected_profit = Decimal("0")
    total_covered_qty = Decimal("0")
    total_actual_position_value = Decimal("0")
    
    for lot in sorted(all_matched, key=lambda l: l.buy_time or datetime.min.replace(tzinfo=timezone.utc)):
        if not lot.matched_tp:
            continue
        
        # Get all TP orders that match this lot (primary + additional)
        tp_orders_for_lot = [lot.matched_tp]
        if hasattr(lot, '_additional_tp_orders') and lot._additional_tp_orders:
            tp_orders_for_lot.extend(lot._additional_tp_orders)
        
        # Calculate how much of the lot each TP order covers
        # For multiple TP orders, we need to split the lot proportionally based on TP quantities
        total_tp_qty = Decimal("0")
        for tp in tp_orders_for_lot:
            tp_qty = Decimal(str(tp.quantity))
            tp_filled = Decimal(str(tp.cumulative_quantity or 0))
            total_tp_qty += (tp_qty - tp_filled)
        
        # Process each TP order that matches this lot
        accumulated_lot_qty = Decimal("0")
        
        for idx, tp in enumerate(tp_orders_for_lot):
            tp_price = Decimal(str(tp.price or 0))
            tp_qty = Decimal(str(tp.quantity))
            tp_filled = Decimal(str(tp.cumulative_quantity or 0))
            tp_remaining = tp_qty - tp_filled
            
            # Calculate the portion of the lot this TP order covers
            # If this is the last TP, cover the remaining lot quantity
            if idx == len(tp_orders_for_lot) - 1:
                lot_qty_for_this_tp = lot.lot_qty - accumulated_lot_qty
            else:
                # Proportionally split based on TP quantity
                lot_qty_for_this_tp = (tp_remaining / total_tp_qty) * lot.lot_qty
                accumulated_lot_qty += lot_qty_for_this_tp
            
            # Calculate profit for this portion
            profit, profit_pct = calculate_expected_profit(lot.buy_price, tp_price, lot_qty_for_this_tp)
            
            total_expected_profit += profit
            total_covered_qty += lot_qty_for_this_tp
            total_actual_position_value += lot.buy_price * lot_qty_for_this_tp
            
            matched_lot_details_raw.append({
                "symbol": lot.symbol,
                "buy_order_id": lot.buy_order_id,
                "buy_time": lot.buy_time.isoformat() if lot.buy_time else None,
                "buy_price": float(lot.buy_price),
                "lot_qty": float(lot_qty_for_this_tp),  # Portion of lot covered by this TP
                "tp_order_id": tp.exchange_order_id,
                "tp_time": (tp.exchange_create_time or tp.created_at).isoformat() if (tp.exchange_create_time or tp.created_at) else None,
                "tp_price": float(tp_price),
                "tp_qty": float(tp_remaining),
                "tp_status": tp.status.value,
                "match_origin": lot.match_origin,
                "expected_profit": float(profit),
                "expected_profit_pct": float(profit_pct),
            })
    
    # Group orders executed at the same time with the same TP
    # Orders are grouped if they share the same tp_order_id and tp_time, and their buy_time is within 1 minute
    matched_lot_details = []
    from collections import defaultdict
    from dateutil.parser import parse as parse_date
    
    # Create groups based on tp_order_id + tp_time + buy_time (rounded to minute)
    groups = defaultdict(list)
    for lot_detail in matched_lot_details_raw:
        # Create a group key based on TP order ID, TP time, and buy time (rounded to minute)
        tp_order_id = lot_detail["tp_order_id"]
        tp_time = lot_detail["tp_time"]
        
        # Parse buy_time and round to minute for grouping
        buy_time_str = lot_detail["buy_time"]
        buy_time_key = None
        if buy_time_str:
            try:
                buy_time = parse_date(buy_time_str)
                # Round to minute (zero out seconds)
                buy_time_rounded = buy_time.replace(second=0, microsecond=0)
                buy_time_key = buy_time_rounded.isoformat()
            except Exception:
                buy_time_key = buy_time_str  # Fallback to original if parsing fails
        
        # Group key: tp_order_id + tp_time + buy_time (rounded to minute)
        group_key = (tp_order_id, tp_time, buy_time_key)
        groups[group_key].append(lot_detail)
    
    # Aggregate grouped orders
    for group_key, lots in groups.items():
        if len(lots) == 1:
            # Single order, no grouping needed
            matched_lot_details.append(lots[0])
        else:
            # Multiple orders to group - aggregate quantities and calculate weighted averages
            tp_order_id, tp_time, _ = group_key
            
            # Aggregate lot quantities
            total_lot_qty = sum(l["lot_qty"] for l in lots)
            
            # Weighted average buy price (weighted by lot_qty)
            total_buy_value = sum(l["buy_price"] * l["lot_qty"] for l in lots)
            avg_buy_price = total_buy_value / total_lot_qty if total_lot_qty > 0 else lots[0]["buy_price"]
            
            # Sum expected profit and calculate average profit percentage
            total_expected_profit_group = sum(l["expected_profit"] for l in lots)
            # Weighted average profit percentage
            total_profit_pct_weighted = sum(l["expected_profit_pct"] * l["lot_qty"] for l in lots)
            avg_profit_pct = total_profit_pct_weighted / total_lot_qty if total_lot_qty > 0 else lots[0]["expected_profit_pct"]
            
            # Use values from first lot for TP and match info (they should all be the same)
            first_lot = lots[0]
            
            # Build list of buy order IDs (sorted)
            buy_order_ids = sorted(set(l["buy_order_id"] for l in lots))
            # Use first buy order ID for display, but include count in a note
            primary_buy_order_id = buy_order_ids[0]
            
            # Use the earliest buy_time
            buy_times = [l["buy_time"] for l in lots if l["buy_time"]]
            earliest_buy_time = min(buy_times) if buy_times else first_lot["buy_time"]
            
            # Create grouped entry
            grouped_entry = {
                "symbol": first_lot["symbol"],
                "buy_order_id": primary_buy_order_id,  # Primary order ID
                "buy_order_ids": buy_order_ids,  # All order IDs in group
                "buy_order_count": len(buy_order_ids),  # Number of orders grouped
                "buy_time": earliest_buy_time,  # Earliest buy time
                "buy_price": float(avg_buy_price),  # Weighted average buy price
                "lot_qty": float(total_lot_qty),  # Total quantity
                "tp_order_id": tp_order_id,
                "tp_time": tp_time,
                "tp_price": first_lot["tp_price"],
                "tp_qty": first_lot["tp_qty"],
                "tp_status": first_lot["tp_status"],
                "match_origin": first_lot["match_origin"],
                "expected_profit": float(total_expected_profit_group),
                "expected_profit_pct": float(avg_profit_pct),
                "is_grouped": True,  # Flag to indicate this is a grouped entry
            }
            matched_lot_details.append(grouped_entry)
    
    # Calculate uncovered quantity
    uncovered_qty = sum(float(lot.lot_qty) for lot in unmatched)
    
    # Calculate net quantity and position value
    net_qty = sum(float(lot.lot_qty) for lot in open_lots)
    position_value = net_qty * current_price
    
    # Use calculated actual position value from matched lots
    # This ensures accuracy when lots are split across multiple TP orders
    
    return {
        "symbol": symbol,
        "net_qty": net_qty,
        "current_price": current_price,
        "position_value": position_value,
        "actual_position_value": float(total_actual_position_value),
        "covered_qty": float(total_covered_qty),
        "uncovered_qty": uncovered_qty,
        "total_expected_profit": float(total_expected_profit),
        "matched_lots": matched_lot_details,
        "has_uncovered": uncovered_qty > 0,
    }

