"""
SL/TP Checker Service
Checks all open positions for missing SL/TP orders and sends Telegram alerts
"""
import os
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderSideEnum
from app.models.watchlist import WatchlistItem
from app.services.brokers.crypto_com_trade import trade_client
from app.services.telegram_notifier import telegram_notifier
from app.services.exchange_sync import exchange_sync_service
from app.services.tp_sl_order_creator import create_stop_loss_order, create_take_profit_order
from app.services.unified_open_orders_fetch import fetch_unified_open_orders

logger = logging.getLogger(__name__)


def _find_recent_entry_order(db: Session, symbol: str) -> Optional[ExchangeOrder]:
    """Most recent filled entry order (BUY long or SELL short), excluding protection orders."""
    return (
        db.query(ExchangeOrder)
        .filter(
            ExchangeOrder.symbol == symbol,
            ExchangeOrder.status == OrderStatusEnum.FILLED,
            ExchangeOrder.side.in_([OrderSideEnum.BUY, OrderSideEnum.SELL]),
        )
        .filter(
            (ExchangeOrder.order_role.is_(None))
            | (~ExchangeOrder.order_role.in_(["STOP_LOSS", "TAKE_PROFIT"]))
        )
        .order_by(ExchangeOrder.exchange_create_time.desc())
        .first()
    )


def _entry_side_from_order(order: ExchangeOrder) -> str:
    if order.side == OrderSideEnum.SELL:
        return "SELL"
    return "BUY"


def _compute_sl_tp_from_entry(
    entry_price: float,
    entry_side: str,
    sl_percentage: float,
    tp_percentage: float,
) -> Tuple[float, float]:
    if entry_side == "SELL":
        sl_price = entry_price * (1 + sl_percentage / 100)
        tp_price = entry_price * (1 - tp_percentage / 100)
    else:
        sl_price = entry_price * (1 - sl_percentage / 100)
        tp_price = entry_price * (1 + tp_percentage / 100)
    return sl_price, tp_price


def _classify_open_protection_leg(order: dict) -> Optional[str]:
    """Classify an open exchange order as 'SL', 'TP', or None.

    Advanced TP/SL (SPOT_ATTACH / TAKE_PROFIT_LIMIT / STOP_LIMIT) must be
    detected here — spot-only open-order endpoints miss them.
    """
    order_type = (order.get("order_type") or order.get("type") or "").upper()
    role = (order.get("order_role") or "").upper()
    contingency = (
        order.get("contingency_type") or order.get("contingencyType") or ""
    ).upper()
    side = (order.get("side") or "").upper()
    trigger_price = (
        order.get("trigger_price")
        or order.get("ref_price")
        or order.get("stop_price")
    )

    if role == "TAKE_PROFIT" or "TAKE_PROFIT" in order_type or "TAKE-PROFIT" in order_type:
        return "TP"
    if "PROFIT" in order_type and "TAKE" in order_type:
        return "TP"
    if role == "STOP_LOSS" or any(
        term in order_type for term in ("STOP_LOSS", "STOP_LIMIT", "STOP-LOSS")
    ):
        return "SL"
    if order_type in ("STOP",) or (
        "STOP" in order_type and "TAKE_PROFIT" not in order_type
    ):
        return "SL"
    if contingency in ("STOP_LOSS", "OCO_STOP"):
        return "SL"
    if contingency in ("TAKE_PROFIT", "OCO_TAKE_PROFIT"):
        return "TP"
    # Legacy Crypto.com pattern: LIMIT + trigger SELL on a long = stop loss
    if order_type == "LIMIT" and trigger_price and side == "SELL":
        return "SL"
    return None


def _order_matches_symbol_variants(order: dict, symbol_variants: List[str]) -> bool:
    order_instrument = order.get("instrument_name") or order.get("symbol") or ""
    order_symbol_normalized = str(order_instrument).replace("/", "_").upper()
    variant_normalized = [v.upper() for v in symbol_variants]
    if order_symbol_normalized in variant_normalized:
        return True
    return any(v.replace("_", "/") == order_instrument for v in symbol_variants)


def _is_active_open_order_status(order: dict) -> bool:
    order_status = (
        order.get("order_status", "") or order.get("status", "")
    ).upper()
    return order_status in ("ACTIVE", "NEW", "PENDING", "PARTIALLY_FILLED") or not order_status


def _quantity_matches_position(order: dict, position_balance: float) -> bool:
    order_quantity = float(order.get("quantity", 0) or order.get("qty", 0) or 0)
    if order_quantity <= 0 or position_balance <= 0:
        return True  # no qty info → assume match (legacy)
    return abs(order_quantity - position_balance) / position_balance <= 0.05


class SLTPCheckerService:
    """Service to check open positions for missing SL/TP orders and OCO integrity"""
    
    def __init__(self):
        self.last_check_date = None
        self._open_orders_snapshot_complete = False
    
    def _fetch_exchange_open_order_ids(self) -> set:
        """Return exchange order IDs currently open (regular + trigger + advanced)."""
        open_ids: set = set()
        self._open_orders_snapshot_complete = False
        try:
            fetch_result = fetch_unified_open_orders(trade_client)
            if not fetch_result.get("data_verified"):
                logger.warning(
                    "Unified open orders fetch not verified for orphan check: %s",
                    fetch_result.get("error_message"),
                )
            self._open_orders_snapshot_complete = bool(
                fetch_result.get("data_verified")
                and fetch_result.get("trigger_orders_status") in (None, "ok")
                and fetch_result.get("advanced_orders_status") in (None, "ok")
            )
            if not self._open_orders_snapshot_complete:
                logger.warning(
                    "Unified open-orders snapshot incomplete; ghost reconciliation disabled "
                    "(trigger=%s advanced=%s)",
                    fetch_result.get("trigger_orders_status"),
                    fetch_result.get("advanced_orders_status"),
                )
            for raw in fetch_result.get("all_raw_orders") or []:
                for field in ("order_id", "exchange_order_id", "client_oid"):
                    oid = raw.get(field)
                    if oid:
                        open_ids.add(str(oid))
        except Exception as exc:
            logger.warning("Could not fetch unified open orders for orphan check: %s", exc)
        return open_ids

    def _check_oco_issues(self, db: Session) -> Dict:
        """
        Check for OCO-related issues and stale/orphan protection orders.

        Orphan/stale cases (actionable only):
        - Sibling in OCO group already FILLED (other leg should be cancelled)
        - ACTIVE in DB but not present on exchange open orders (ghost/stale)

        Standalone trigger TPs/SLs on the exchange without parent_order_id or
        oco_group_id are valid (legacy/manual orders) and must not be flagged.
        """
        issues = {'orphaned_orders': [], 'incomplete_groups': [], 'total_oco_groups': 0}
        sl_tp_types = [
            'STOP_LIMIT', 'STOP_LOSS_LIMIT', 'STOP_LOSS', 'TAKE_PROFIT_LIMIT', 'TAKE_PROFIT',
        ]

        try:
            active_sl_tp = db.query(ExchangeOrder).filter(
                ExchangeOrder.order_type.in_(sl_tp_types),
                ExchangeOrder.status.in_([
                    OrderStatusEnum.NEW,
                    OrderStatusEnum.ACTIVE,
                    OrderStatusEnum.PARTIALLY_FILLED,
                ]),
            ).all()

            logger.info("Checking %d active SL/TP orders for OCO/orphan issues", len(active_sl_tp))
            exchange_open_ids = self._fetch_exchange_open_order_ids()
            seen_orphan_ids: set = set()

            for order in active_sl_tp:
                reasons: List[str] = []
                on_exchange = bool(
                    order.exchange_order_id
                    and exchange_open_ids
                    and str(order.exchange_order_id) in exchange_open_ids
                )

                if order.oco_group_id:
                    siblings = db.query(ExchangeOrder).filter(
                        ExchangeOrder.oco_group_id == order.oco_group_id,
                        ExchangeOrder.exchange_order_id != order.exchange_order_id,
                    ).all()
                    for sibling in siblings:
                        if sibling.status == OrderStatusEnum.FILLED:
                            reasons.append(
                                f"sibling {sibling.order_role} {sibling.exchange_order_id} FILLED"
                            )
                            break

                if order.parent_order_id:
                    sibling_filled = db.query(ExchangeOrder).filter(
                        ExchangeOrder.parent_order_id == order.parent_order_id,
                        ExchangeOrder.exchange_order_id != order.exchange_order_id,
                        ExchangeOrder.order_type.in_(sl_tp_types),
                        ExchangeOrder.status == OrderStatusEnum.FILLED,
                    ).first()
                    if sibling_filled:
                        reason = (
                            f"parent {order.parent_order_id} has filled sibling "
                            f"{sibling_filled.order_role} {sibling_filled.exchange_order_id}"
                        )
                        if reason not in reasons:
                            reasons.append(reason)

                if order.exchange_order_id and exchange_open_ids and not on_exchange:
                    reasons.append("ACTIVE in DB but not on exchange")

                if reasons and order.exchange_order_id not in seen_orphan_ids:
                    seen_orphan_ids.add(order.exchange_order_id)
                    # Ghost rows: ACTIVE in DB but gone from the exchange. Reconcile
                    # immediately so the next health check / half_protected path does
                    # not keep recreating TP or spamming the same 14 orphans
                    # (observed 2026-07-21). Sibling-FILLED orphans stay alert-only
                    # until an explicit cancel attempt.
                    if (
                        reasons == ["ACTIVE in DB but not on exchange"]
                        and self._open_orders_snapshot_complete
                    ):
                        try:
                            order.status = OrderStatusEnum.CANCELLED
                            order.updated_at = datetime.now(timezone.utc)
                            logger.info(
                                "[OCO_RECONCILE] Marked ghost SL/TP CANCELLED: "
                                "order_id=%s symbol=%s type=%s",
                                order.exchange_order_id,
                                order.symbol,
                                order.order_role or order.order_type,
                            )
                            continue  # reconciled; do not alert
                        except Exception as reconcile_err:
                            logger.warning(
                                "[OCO_RECONCILE] Failed to mark ghost %s CANCELLED: %s",
                                order.exchange_order_id,
                                reconcile_err,
                            )
                    issues['orphaned_orders'].append({
                        'order_id': order.exchange_order_id,
                        'symbol': order.symbol,
                        'type': order.order_role or order.order_type,
                        'price': float(order.price) if order.price else None,
                        'missing': "; ".join(reasons),
                        'quantity': float(order.quantity) if order.quantity else None,
                        'parent_order_id': order.parent_order_id,
                        'oco_group_id': order.oco_group_id,
                    })

            try:
                db.commit()
            except Exception as commit_err:
                logger.warning("[OCO_RECONCILE] commit failed: %s", commit_err)
                db.rollback()

            from collections import defaultdict
            oco_groups = defaultdict(list)
            for order in active_sl_tp:
                if order.oco_group_id:
                    oco_groups[order.oco_group_id].append(order)

            issues['total_oco_groups'] = len(oco_groups)

            for oco_id, orders in oco_groups.items():
                still_active = [
                    o
                    for o in orders
                    if o.status
                    in (
                        OrderStatusEnum.NEW,
                        OrderStatusEnum.ACTIVE,
                        OrderStatusEnum.PARTIALLY_FILLED,
                    )
                ]
                if not still_active:
                    continue
                has_sl = any(o.order_role == "STOP_LOSS" for o in still_active)
                has_tp = any(o.order_role == "TAKE_PROFIT" for o in still_active)
                if not (has_sl and has_tp):
                    symbol = still_active[0].symbol if still_active else "Unknown"
                    issues['incomplete_groups'].append({
                        'oco_group_id': oco_id,
                        'symbol': symbol,
                        'has_sl': has_sl,
                        'has_tp': has_tp,
                        'missing': "STOP_LOSS" if not has_sl else "TAKE_PROFIT",
                    })

            logger.info(
                "OCO check: %d orphaned, %d incomplete",
                len(issues['orphaned_orders']),
                len(issues['incomplete_groups']),
            )

        except Exception as e:
            logger.error(f"Error checking OCO issues: {e}", exc_info=True)
            issues['error'] = str(e)

        return issues
    
    def check_positions_for_sl_tp(self, db: Session) -> Dict:
        """
        Check all open positions and verify if they have SL/TP orders
        
        Returns:
            Dict with positions missing SL/TP
        """
        try:
            # Get account balance to find open positions
            balance_response = trade_client.get_account_summary()
            accounts = balance_response.get('accounts', [])
            
            logger.info(f"Received {len(accounts)} accounts from get_account_summary")
            if len(accounts) > 0:
                logger.info(f"Sample account: {accounts[0]}")
            
            # Filter positions with positive balance (excluding USDT/USD)
            open_positions = []
            for account in accounts:
                # Handle both 'currency' and 'instrument_name' fields
                currency = account.get('currency', '').upper()
                if not currency:
                    # Try instrument_name if currency is not available
                    currency = account.get('instrument_name', '').upper()
                
                if not currency:
                    logger.warning(f"Account missing currency/instrument_name: {account}")
                    continue
                    
                balance_str = account.get('balance', '0')
                
                # Handle balance format - could be string or number
                try:
                    balance = float(balance_str)
                except (ValueError, TypeError):
                    logger.warning(f"Invalid balance format for {currency}: {balance_str}")
                    continue
                
                # Skip if balance is zero or negative
                if balance <= 0:
                    logger.debug(f"Skipping {currency} - balance is {balance}")
                    continue
                
                # Handle currency format - could be "ETH" or "ETH_USDT"
                if '_' in currency:
                    # Format is already like "ETH_USDT" - extract base currency
                    base_currency = currency.split('_')[0]
                    symbol = currency  # Keep full symbol for later use
                else:
                    # Format is just currency like "ETH" - assume USDT pair
                    base_currency = currency
                    symbol = f"{currency}_USDT"
                
                # Skip stablecoins (USDT, USD, USDC, etc.) and fiat (EUR, GBP, JPY, etc.)
                stablecoins = ['USDT', 'USD', 'USDC', 'BUSD', 'DAI', 'TUSD']
                fiat = ['EUR', 'GBP', 'JPY', 'CNY', 'AUD', 'CAD', 'CHF', 'NZD', 'SGD', 'HKD', 'KRW']
                if base_currency in stablecoins or base_currency in fiat:
                    logger.debug(f"Skipping stablecoin/fiat: {base_currency}")
                    continue
                
                open_positions.append({
                    'currency': base_currency,
                    'symbol': symbol,
                    'balance': balance
                })
                
                logger.info(f"Found open position: {symbol} ({base_currency}) = {balance}")
            
            logger.info(f"Found {len(open_positions)} open positions to check for SL/TP")
            
            # For each position, check if there are active SL/TP orders
            positions_missing_sl_tp = []

            # Fetch once: regular + trigger + advanced (spot-only misses advanced TPs)
            all_orders_data: List[dict] = []
            try:
                fetch_result = fetch_unified_open_orders(trade_client)
                all_orders_data = list(fetch_result.get("all_raw_orders") or [])
                if not fetch_result.get("data_verified"):
                    logger.warning(
                        "Unified open orders not fully verified for SL/TP position check: %s",
                        fetch_result.get("error_message"),
                    )
                logger.info(
                    "Retrieved %s unified open orders for SL/TP position check "
                    "(trigger=%s advanced=%s)",
                    len(all_orders_data),
                    fetch_result.get("trigger_orders_status"),
                    fetch_result.get("advanced_orders_status"),
                )
            except Exception as e:
                logger.warning(
                    "Unified open orders fetch failed for SL/TP check, falling back to spot: %s",
                    e,
                )
                try:
                    all_open_orders = trade_client.get_open_orders()
                    all_orders_data = all_open_orders.get("data", []) or []
                except Exception as spot_err:
                    logger.warning("Spot open orders fallback also failed: %s", spot_err)
                    all_orders_data = []
            
            for position in open_positions:
                currency = position['currency']
                symbol = position.get('symbol', f"{currency}_USDT")  # Use symbol from position or default
                
                # Create symbol variants to check (BONK_USDT, BONK_USD, etc.)
                symbol_variants = [symbol]
                if symbol.endswith('_USDT'):
                    symbol_variants.append(symbol.replace('_USDT', '_USD'))
                elif symbol.endswith('_USD'):
                    symbol_variants.append(symbol.replace('_USD', '_USDT'))
                
                # Try to find symbol in watchlist - try exact match first
                watchlist_item = db.query(WatchlistItem).filter(
                    WatchlistItem.symbol == symbol
                ).first()
                
                if not watchlist_item:
                    # Try pattern match
                    watchlist_item = db.query(WatchlistItem).filter(
                        WatchlistItem.symbol.like(f"%{currency}%")
                    ).first()
                    if watchlist_item:
                        symbol = watchlist_item.symbol  # Use symbol from watchlist if found
                        # Update symbol variants
                        symbol_variants = [symbol]
                        if symbol.endswith('_USDT'):
                            symbol_variants.append(symbol.replace('_USDT', '_USD'))
                        elif symbol.endswith('_USD'):
                            symbol_variants.append(symbol.replace('_USD', '_USDT'))
                
                # Check for active SL/TP orders from Crypto.com Exchange API directly
                # This is more reliable than checking database status
                has_sl = False
                has_tp = False
                
                try:
                    open_orders_data = [
                        order
                        for order in all_orders_data
                        if _order_matches_symbol_variants(order, symbol_variants)
                    ]
                    
                    logger.debug(
                        f"Filtered {len(open_orders_data)} orders for {symbol} "
                        f"from {len(all_orders_data)} total orders"
                    )
                    
                    sl_orders_open = []
                    tp_orders_open = []
                    
                    for o in open_orders_data:
                        leg = _classify_open_protection_leg(o)
                        if leg == "SL":
                            sl_orders_open.append(o)
                            logger.debug(
                                f"Found SL order for {symbol}: "
                                f"{o.get('order_type')} id={o.get('order_id')}"
                            )
                        elif leg == "TP":
                            tp_orders_open.append(o)
                            logger.debug(
                                f"Found TP order for {symbol}: "
                                f"{o.get('order_type')} id={o.get('order_id')}"
                            )
                    
                    logger.info(
                        f"Position {symbol}: Filtered {len(sl_orders_open)} SL and "
                        f"{len(tp_orders_open)} TP orders from {len(open_orders_data)} matched orders"
                    )
                    
                    position_balance = position.get('balance', 0)
                    active_sl_orders = [
                        o for o in sl_orders_open
                        if _is_active_open_order_status(o)
                        and _quantity_matches_position(o, position_balance)
                    ]
                    active_tp_orders = [
                        o for o in tp_orders_open
                        if _is_active_open_order_status(o)
                        and _quantity_matches_position(o, position_balance)
                    ]
                    # Log exclusions for qty mismatch
                    for o in sl_orders_open:
                        if _is_active_open_order_status(o) and not _quantity_matches_position(o, position_balance):
                            logger.info(
                                f"Position {symbol}: Excluding SL order {o.get('order_id')} - "
                                f"qty mismatch vs position={position_balance}"
                            )
                    for o in tp_orders_open:
                        if _is_active_open_order_status(o) and not _quantity_matches_position(o, position_balance):
                            logger.info(
                                f"Position {symbol}: Excluding TP order {o.get('order_id')} - "
                                f"qty mismatch vs position={position_balance}"
                            )
                    
                    has_sl = len(active_sl_orders) > 0
                    has_tp = len(active_tp_orders) > 0
                    
                    logger.info(
                        f"Position {symbol}: Found {len(active_sl_orders)} active SL and "
                        f"{len(active_tp_orders)} active TP orders matching position "
                        f"balance={position_balance} (total found: {len(sl_orders_open)} SL, "
                        f"{len(tp_orders_open)} TP)"
                    )
                except Exception as e:
                    logger.warning(f"Error checking open orders from Exchange API for {symbol}: {e}")
                    # Fallback to database check
                    try:
                        from sqlalchemy import or_
                        # Check database for active orders (status NEW or ACTIVE, not FILLED)
                        sl_orders_db = db.query(ExchangeOrder).filter(
                            or_(*[ExchangeOrder.symbol == variant for variant in symbol_variants]),
                            ExchangeOrder.order_type.in_(['STOP_LIMIT', 'STOP_LOSS']),
                            ExchangeOrder.status.in_([
                                OrderStatusEnum.NEW,
                                OrderStatusEnum.ACTIVE,
                                OrderStatusEnum.PENDING
                            ])
                        ).all()
                        
                        tp_orders_db = db.query(ExchangeOrder).filter(
                            or_(*[ExchangeOrder.symbol == variant for variant in symbol_variants]),
                            ExchangeOrder.order_type.in_(['TAKE_PROFIT_LIMIT', 'TAKE_PROFIT']),
                            ExchangeOrder.status.in_([
                                OrderStatusEnum.NEW,
                                OrderStatusEnum.ACTIVE,
                                OrderStatusEnum.PENDING
                            ])
                        ).all()
                        
                        has_sl = len(sl_orders_db) > 0
                        has_tp = len(tp_orders_db) > 0
                        logger.info(f"Position {symbol}: Found {len(sl_orders_db)} SL and {len(tp_orders_db)} TP orders from database")
                    except Exception as db_err:
                        logger.error(f"Error querying orders from database for {symbol}: {db_err}", exc_info=True)
                        has_sl = False
                        has_tp = False
                
                # has_sl and has_tp are now set from Exchange API or database fallback
                logger.info(f"Position {symbol}: Final check - has_sl={has_sl}, has_tp={has_tp}")
                
                # Check if user skipped reminder for this symbol
                skip_reminder = watchlist_item.skip_sl_tp_reminder if watchlist_item else False
                
                logger.info(f"Position {symbol}: has_sl={has_sl}, has_tp={has_tp}, skip_reminder={skip_reminder}, will_include={((not has_sl or not has_tp) and not skip_reminder)}")
                
                # Always include unprotected positions for auto-create (even if reminder skipped).
                # skip_reminder only suppresses Telegram nudge buttons, not protection.
                if not has_sl or not has_tp:
                    # Get SL/TP prices from watchlist if available
                    sl_price = watchlist_item.sl_price if watchlist_item else None
                    tp_price = watchlist_item.tp_price if watchlist_item else None
                    
                    positions_missing_sl_tp.append({
                        'symbol': symbol,
                        'currency': currency,
                        'balance': position['balance'],
                        'has_sl': has_sl,
                        'has_tp': has_tp,
                        'sl_price': sl_price,
                        'tp_price': tp_price,
                        'skip_reminder': skip_reminder,
                        'watchlist_item': watchlist_item
                    })
            
            logger.info(f"Found {len(positions_missing_sl_tp)} positions missing SL/TP")
            
            # Check for OCO-related issues
            oco_issues = self._check_oco_issues(db)
            
            return {
                'positions_missing_sl_tp': positions_missing_sl_tp,
                'total_positions': len(open_positions),
                'oco_issues': oco_issues,
                'checked_at': datetime.utcnow()
            }
            
        except Exception as e:
            logger.error(f"Error checking positions for SL/TP: {e}", exc_info=True)
            return {
                'positions_missing_sl_tp': [],
                'total_positions': 0,
                'error': str(e)
            }
    
    def ensure_missing_protection(self, db: Session) -> Dict:
        """
        Always create missing SL and/or TP for open positions.

        Age of the entry fill does not matter — open balance without both
        legs is unprotected and must be healed.
        """
        result = self.check_positions_for_sl_tp(db)
        positions_missing = result.get("positions_missing_sl_tp", [])
        created: List[Dict] = []
        failed: List[Dict] = []
        still_missing: List[Dict] = []

        for pos in positions_missing:
            symbol = pos["symbol"]
            create_sl = not pos.get("has_sl")
            create_tp = not pos.get("has_tp")
            if not create_sl and not create_tp:
                continue
            logger.info(
                "Auto-creating missing protection for %s (create_sl=%s create_tp=%s)",
                symbol,
                create_sl,
                create_tp,
            )
            try:
                creation = self._create_protection_order(
                    db,
                    symbol,
                    create_sl=create_sl,
                    create_tp=create_tp,
                    force=True,
                    source="auto_ensure",
                )
            except Exception as exc:
                logger.error(
                    "Auto-create protection failed for %s: %s",
                    symbol,
                    exc,
                    exc_info=True,
                )
                failed.append({"symbol": symbol, "error": str(exc), **pos})
                still_missing.append(pos)
                continue

            if creation.get("success"):
                created.append(
                    {
                        "symbol": symbol,
                        "sl_order_id": creation.get("sl_order_id"),
                        "tp_order_id": creation.get("tp_order_id"),
                    }
                )
            else:
                failed.append(
                    {
                        "symbol": symbol,
                        "error": creation.get("error")
                        or creation.get("sl_error")
                        or creation.get("tp_error"),
                        **pos,
                    }
                )
                # Keep for Telegram reminder if still unprotected
                still_pos = dict(pos)
                if creation.get("sl_order_id"):
                    still_pos["has_sl"] = True
                if creation.get("tp_order_id"):
                    still_pos["has_tp"] = True
                if not still_pos.get("has_sl") or not still_pos.get("has_tp"):
                    still_missing.append(still_pos)

        return {
            "checked_at": result.get("checked_at"),
            "total_positions": result.get("total_positions", 0),
            "oco_issues": result.get("oco_issues", {}),
            "created": created,
            "failed": failed,
            "still_missing": still_missing,
            "positions_missing_sl_tp": still_missing,
        }

    def send_sl_tp_reminder(self, db: Session) -> bool:
        """
        Ensure every open position has SL/TP, then remind only if still missing.
        Also sends OCO issues alerts
        
        Returns:
            bool: True if reminder was sent, False otherwise
        """
        try:
            # Always auto-create missing legs first (no age gate)
            ensure_result = self.ensure_missing_protection(db)
            positions_missing = [
                p for p in ensure_result.get("still_missing", [])
                if not p.get("skip_reminder")
            ]
            oco_issues = ensure_result.get('oco_issues', {})

            if ensure_result.get("created"):
                logger.info(
                    "Auto-created protection for %s position(s): %s",
                    len(ensure_result["created"]),
                    [c.get("symbol") for c in ensure_result["created"]],
                )
            if ensure_result.get("failed"):
                logger.warning(
                    "Failed auto-create protection for %s position(s): %s",
                    len(ensure_result["failed"]),
                    [
                        f"{f.get('symbol')}: {f.get('error')}"
                        for f in ensure_result["failed"]
                    ],
                )

            # Always alert on orphan/stale OCO issues even when all positions are protected.
            oco_alerts_sent = self._send_oco_alerts(oco_issues)

            if not positions_missing:
                logger.info("All positions have SL/TP orders, no position reminders needed")
                return oco_alerts_sent > 0 or bool(ensure_result.get("created"))

            # Send one message per position with specific options
            reminders_sent = 0
            for pos in positions_missing:
                symbol = pos['symbol']
                balance = pos['balance']
                has_sl = pos['has_sl']
                has_tp = pos['has_tp']
                sl_price = pos['sl_price']
                tp_price = pos['tp_price']
                currency = pos['currency']
                
                # Determine what's missing
                missing_items = []
                if not has_sl:
                    missing_items.append("SL")
                if not has_tp:
                    missing_items.append("TP")
                
                if not missing_items:
                    continue  # Skip if nothing is missing (shouldn't happen, but just in case)
                
                # Spanish operator copy: state the problem, then list actionable options.
                # Reminder path currently tracks long balances only → close = SELL.
                close_key = f"{symbol}:LONG"
                message = f"⚠️ <b>POSICIÓN SIN PROTECCIÓN: {symbol}</b>\n\n"
                message += (
                    "⚠️ <b>Problema:</b> auto-creación falló; la posición sigue "
                    f"<b>sin {' y '.join(missing_items)}</b>.\n"
                    "Sin esa protección la posición queda expuesta.\n\n"
                )
                message += f"📊 Símbolo: <b>{symbol}</b>\n"
                message += f"💰 Balance: {balance:.6f} {currency}\n\n"

                sl_status = "✅ Activo" if has_sl else "❌ Falta"
                tp_status = "✅ Activo" if has_tp else "❌ Falta"

                message += f"🛑 Stop Loss: {sl_status}"
                if sl_price:
                    message += f" @ ${sl_price:.4f}" if has_sl else f" (precio sugerido: ${sl_price:.4f})"
                message += "\n"

                message += f"🚀 Take Profit: {tp_status}"
                if tp_price:
                    message += f" @ ${tp_price:.4f}" if has_tp else f" (precio sugerido: ${tp_price:.4f})"
                message += "\n\n"

                message += "<b>Opciones:</b>\n"
                opt_n = 1
                if not has_sl:
                    message += f"{opt_n}. Crear un SL\n"
                    opt_n += 1
                if not has_tp:
                    message += f"{opt_n}. Crear un TP\n"
                    opt_n += 1
                message += f"{opt_n}. Cerrar la posición (vender a mercado → SELL)\n\n"
                message += "Elige un botón abajo."

                buttons = []

                if not has_sl and not has_tp:
                    buttons.append([
                        {"text": "🛡️ Crear SL y TP", "callback_data": f"create_sl_tp_{symbol}"},
                    ])
                    buttons.append([
                        {"text": "🛑 Crear SL", "callback_data": f"create_sl_{symbol}"},
                        {"text": "🚀 Crear TP", "callback_data": f"create_tp_{symbol}"}
                    ])
                elif not has_sl:
                    buttons.append([
                        {"text": "🛑 Crear SL", "callback_data": f"create_sl_{symbol}"}
                    ])
                elif not has_tp:
                    buttons.append([
                        {"text": "🚀 Crear TP", "callback_data": f"create_tp_{symbol}"}
                    ])

                buttons.append([
                    {"text": "🔴 Cerrar (vender)", "callback_data": f"posrev_close:{close_key}"},
                    {"text": "⏭️ No preguntar más", "callback_data": f"skip_sl_tp_{symbol}"}
                ])
                
                # Send individual message for this position with buttons
                try:
                    telegram_notifier.send_message_with_buttons(message, buttons)
                    reminders_sent += 1
                    logger.info(f"Sent SL/TP reminder for {symbol} with buttons (missing: {', '.join(missing_items)})")
                except Exception as e:
                    logger.error(f"Error sending Telegram reminder for {symbol}: {e}")
            
            logger.info(f"Sent {reminders_sent} SL/TP reminders (one per position)")

            # Store reminder state for later processing
            self.last_reminder_positions = positions_missing
            self.last_reminder_time = datetime.utcnow()

            return (reminders_sent > 0 or oco_alerts_sent > 0)

        except Exception as e:
            logger.error(f"Error sending SL/TP reminder: {e}", exc_info=True)
            return False

    def send_orphan_order_alert(self, db: Session) -> bool:
        """Check for orphaned/stale SL/TP orders and send a Telegram alert."""
        try:
            issues = self._check_oco_issues(db)
            return self._send_oco_alerts(issues, db=db) > 0
        except Exception as e:
            logger.error("Error sending orphan order alert: %s", e, exc_info=True)
            return False

    def _send_oco_alerts(self, oco_issues: Dict, db: Session = None) -> int:
        """Send Telegram alerts for OCO issues"""
        alerts_sent = 0
        
        try:
            orphaned = oco_issues.get('orphaned_orders', [])
            incomplete = oco_issues.get('incomplete_groups', [])
            
            if not orphaned and not incomplete:
                logger.info("No OCO issues found")
                return 0

            # Suppress identical health snapshots for 24h (same orphans + incomplete groups).
            from app.services.telegram_event_dedup import claim_telegram_event

            orphan_ids = sorted(
                str(o.get("order_id") or "") for o in orphaned if o.get("order_id")
            )
            incomplete_ids = sorted(
                str(g.get("oco_group_id") or "") for g in incomplete if g.get("oco_group_id")
            )
            fingerprint = f"oco_health:{','.join(orphan_ids)}|{','.join(incomplete_ids)}"
            if not claim_telegram_event(
                db,
                fingerprint,
                ttl_minutes=24 * 60,
                action="oco_health",
            ):
                logger.info(
                    "📢 Skipping duplicate OCO health Telegram (orphaned=%d incomplete=%d)",
                    len(orphaned),
                    len(incomplete),
                )
                return 0
            
            message = "🔧 <b>ORPHAN / OCO HEALTH CHECK</b>\n\n"
            message += f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            message += f"📊 Total OCO Groups: {oco_issues.get('total_oco_groups', 0)}\n\n"

            if orphaned:
                message += f"⚠️ <b>ORPHANED / STALE ORDERS: {len(orphaned)}</b>\n\n"
                for order in orphaned:
                    message += f"• <b>{order['symbol']}</b> - {order['type']}\n"
                    if order['price']:
                        message += f"  ${order['price']:,.4f}\n"
                    message += f"  Reason: {order['missing']}\n"
                    if order.get('order_id'):
                        message += f"  Order ID: <code>{order['order_id']}</code>\n"
                    if order.get('parent_order_id'):
                        message += f"  Parent: <code>{order['parent_order_id']}</code>\n"
                    message += "\n"
            
            if incomplete:
                message += f"❌ <b>INCOMPLETE GROUPS: {len(incomplete)}</b>\n\n"
                for group in incomplete:  # Show ALL incomplete groups
                    message += f"• <b>{group['symbol']}</b>\n"
                    message += f"  Has: {group.get('missing') and 'TP' if group.get('missing') == 'STOP_LOSS' else 'SL'}\n"
                    message += f"  Missing: {group['missing']}\n"
                    if group.get('oco_group_id'):
                        message += f"  OCO Group ID: {group['oco_group_id']}\n"
                    message += "\n"
            
            message += "💡 Review with /orders command"
            
            telegram_notifier.send_message(message)
            alerts_sent += 1
            logger.info(f"Sent OCO alert: {len(orphaned)} orphaned, {len(incomplete)} incomplete")
            
        except Exception as e:
            logger.error(f"Error sending OCO alerts: {e}", exc_info=True)
        
        return alerts_sent
    
    def create_sl_for_position(self, db: Session, symbol: str, force: bool = False) -> Dict:
        """
        Create only SL order for a specific position
        
        Args:
            db: Database session
            symbol: Trading symbol (e.g., ETH_USDT)
            force: If True, create even if skip_reminder is set
        
        Returns:
            Dict with creation results
        """
        return self._create_protection_order(db, symbol, create_sl=True, create_tp=False, force=force)
    
    def create_tp_for_position(self, db: Session, symbol: str, force: bool = False) -> Dict:
        """
        Create only TP order for a specific position
        
        Args:
            db: Database session
            symbol: Trading symbol (e.g., ETH_USDT)
            force: If True, create even if skip_reminder is set
        
        Returns:
            Dict with creation results
        """
        return self._create_protection_order(db, symbol, create_sl=False, create_tp=True, force=force)
    
    def _create_protection_order(self, db: Session, symbol: str, create_sl: bool = True, create_tp: bool = True, force: bool = False, source: str = "manual") -> Dict:
        """
        Internal method to create SL and/or TP orders for a position
        
        Args:
            db: Database session
            symbol: Trading symbol (e.g., ETH_USDT)
            create_sl: Whether to create SL order
            create_tp: Whether to create TP order
            force: If True, create even if skip_reminder is set
        
        Returns:
            Dict with creation results
        """
        try:
            # First, verify there's an open position
            balance_response = trade_client.get_account_summary()
            accounts = balance_response.get('accounts', [])
            
            # Extract base currency from symbol (e.g., ETH from ETH_USDT)
            base_currency = symbol.split('_')[0] if '_' in symbol else symbol
            
            logger.debug(f"Looking for position balance for {symbol} (base currency: {base_currency})")
            logger.debug(f"Available accounts (first 5): {[(acc.get('currency'), acc.get('balance')) for acc in accounts[:5]]}")
            
            position_balance = 0.0
            for account in accounts:
                currency = account.get('currency', '').upper()
                balance_str = account.get('balance', '0')
                
                # Handle formats:
                # 1. currency = "ETH" -> matches base_currency "ETH"
                # 2. currency = "ETH_USDT" -> matches symbol "ETH_USDT"
                # 3. currency = "ETH/USDT" -> matches symbol "ETH_USDT"
                # 4. currency = "BONK/USD" -> matches symbol "BONK_USDT" (flexible)
                
                currency_normalized = currency.replace('/', '_').upper()
                symbol_normalized = symbol.upper()
                base_normalized = base_currency.upper()
                
                # Check if currency matches symbol directly or base currency
                matches = (
                    currency == symbol.upper() or  # Exact match: "ETH_USDT" == "ETH_USDT"
                    currency_normalized == symbol_normalized or  # Normalized match: "ETH/USDT" == "ETH_USDT"
                    currency == base_normalized or  # Base match: "ETH" == "ETH"
                    currency_normalized == base_normalized or  # Normalized base: "ETH/USDT" -> "ETH"
                    currency.startswith(base_normalized + '_') or  # Starts with base: "ETH_USDT" starts with "ETH_"
                    currency.startswith(base_normalized + '/')  # Starts with base and slash: "ETH/USDT" starts with "ETH/"
                )
                
                if matches:
                    try:
                        position_balance = float(balance_str)
                        logger.debug(f"Found balance for {currency}: {position_balance}")
                        if position_balance > 0:
                            break
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Invalid balance format for {currency}: {balance_str}, error: {e}")
                        continue
            
            if position_balance <= 0:
                available_currencies = [acc.get('currency') for acc in accounts[:10]]
                logger.warning(f"No open position found for {symbol}. Available currencies: {available_currencies}")
                return {
                    'success': False,
                    'error': f'No open position found for {symbol}. Please verify you have balance in {base_currency}.'
                }
            
            # Get watchlist item (if exists)
            watchlist_item = db.query(WatchlistItem).filter(
                WatchlistItem.symbol == symbol
            ).first()
            
            # If no watchlist item, create one with default values
            if not watchlist_item:
                logger.info(f"Watchlist item not found for {symbol}, creating with default values")
                
                # Get current price for calculations (skip if async - will get from order instead)
                current_price = None
                
                # Try to get entry price from most recent filled entry order
                entry_price = None
                try:
                    recent_order = _find_recent_entry_order(db, symbol)
                    if recent_order:
                        entry_price = float(recent_order.avg_price) if recent_order.avg_price else float(recent_order.price) if recent_order.price else None
                        logger.info(f"Found entry price from recent order: {entry_price}")
                except Exception as e:
                    logger.warning(f"Could not get entry price from orders: {e}")
                
                # Use entry price if available, otherwise use current price
                purchase_price = entry_price or current_price
                
                # Create watchlist item with default values
                watchlist_item = WatchlistItem(
                    symbol=symbol,
                    exchange="CRYPTO_COM",
                    trade_enabled=False,
                    alert_enabled=False,
                    sl_tp_mode="conservative",
                    skip_sl_tp_reminder=False,
                    purchase_price=purchase_price,
                    price=current_price
                )
                db.add(watchlist_item)
                db.commit()
                logger.info(f"Created watchlist item for {symbol} with purchase_price={purchase_price}, current_price={current_price}")
            
            # Check if reminder was skipped
            if watchlist_item.skip_sl_tp_reminder and not force:
                return {
                    'success': False,
                    'error': f'SL/TP reminder skipped for {symbol} (use force=True to override)'
                }
            
            # Get SL/TP prices from watchlist
            sl_price = watchlist_item.sl_price
            tp_price = watchlist_item.tp_price
            prefer_tp_from_pct = (
                create_tp
                and watchlist_item.tp_percentage is not None
                and watchlist_item.tp_percentage > 0
            )
            
            # Calculate from percentages if prices not available, or when tp_percentage is set
            entry_price = None
            entry_side = "BUY"
            if (create_sl and not sl_price) or (create_tp and (not tp_price or prefer_tp_from_pct)):
                recent_order = _find_recent_entry_order(db, symbol)

                if recent_order:
                    entry_price = float(recent_order.avg_price) if recent_order.avg_price else float(recent_order.price) if recent_order.price else None
                    entry_side = _entry_side_from_order(recent_order)
                    if entry_price:
                        logger.info(
                            f"✅ Using entry price from filled {entry_side} order for {symbol}: "
                            f"{entry_price} (Order ID: {recent_order.exchange_order_id})"
                        )
                    else:
                        logger.warning(
                            f"⚠️ Filled {entry_side} order found for {symbol} but price is None "
                            f"(Order ID: {recent_order.exchange_order_id})"
                        )
                
                # 2. Fallback: use purchase_price from watchlist (only if no BUY order found)
                if not entry_price:
                    entry_price = watchlist_item.purchase_price
                    if entry_price:
                        logger.info(f"Using purchase_price from watchlist for {symbol}: {entry_price} (no filled BUY order found)")
                
                # 3. Last resort: use last known price from watchlist (only if no BUY order and no purchase_price)
                if not entry_price:
                    entry_price = watchlist_item.price
                    if entry_price:
                        logger.info(f"Using last known price from watchlist for {symbol}: {entry_price} (no filled BUY order or purchase_price found)")
                
                # 4. Final fallback: if we have an open position but no entry price, use current market price
                # This handles cases where position exists but order history is missing
                if not entry_price and position_balance > 0:
                    try:
                        import sys
                        # Add parent directory to path to import simple_price_fetcher
                        # os is already imported at the top of the file
                        parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                        if parent_dir not in sys.path:
                            sys.path.insert(0, parent_dir)
                        from simple_price_fetcher import get_price
                        current_market_price = get_price(symbol)
                        if current_market_price and current_market_price > 0:
                            entry_price = current_market_price
                            logger.warning(f"⚠️ Using current market price as entry price for {symbol}: {entry_price} (position exists but no BUY order found in database)")
                            # Update watchlist_item with current price for future use
                            watchlist_item.price = entry_price
                            if not watchlist_item.purchase_price:
                                watchlist_item.purchase_price = entry_price
                            db.commit()
                    except Exception as e:
                        logger.warning(f"Could not fetch current market price for {symbol}: {e}")
                
                if not entry_price:
                    return {
                        'success': False,
                        'error': (
                            f'Cannot determine entry price for {symbol}. No filled entry order found in database. '
                            f'Please ensure there is a recent filled BUY or SELL entry order, or configure '
                            f'purchase_price/price in watchlist.'
                        )
                    }
                
                # Get strategy mode and percentages
                strategy_mode = watchlist_item.sl_tp_mode or "conservative"
                
                # Log what we're reading from watchlist
                logger.info(
                    f"Reading SL/TP settings for {symbol}: "
                    f"watchlist_sl_pct={watchlist_item.sl_percentage}, watchlist_tp_pct={watchlist_item.tp_percentage}, "
                    f"mode={strategy_mode}"
                )
                
                # Use configured percentages or defaults based on strategy
                # CRITICAL: Check for None and > 0 (0% would be invalid anyway)
                if watchlist_item.sl_percentage is not None and watchlist_item.sl_percentage > 0:
                    sl_percentage = abs(watchlist_item.sl_percentage)
                    logger.info(f"Using watchlist SL percentage: {sl_percentage}% (from watchlist: {watchlist_item.sl_percentage}%)")
                else:
                    # Default percentages based on strategy
                    sl_percentage = 3.0 if strategy_mode == "conservative" else 2.0
                    logger.info(f"Using default SL percentage: {sl_percentage}% (watchlist had: {watchlist_item.sl_percentage})")
                
                if watchlist_item.tp_percentage is not None and watchlist_item.tp_percentage > 0:
                    tp_percentage = abs(watchlist_item.tp_percentage)
                    logger.info(f"Using watchlist TP percentage: {tp_percentage}% (from watchlist: {watchlist_item.tp_percentage}%)")
                else:
                    # Default percentages based on strategy
                    tp_percentage = 3.0 if strategy_mode == "conservative" else 2.0
                    logger.info(f"Using default TP percentage: {tp_percentage}% (watchlist had: {watchlist_item.tp_percentage})")
                
                logger.info(f"Calculating SL/TP for {symbol}: entry_price={entry_price}, entry_side={entry_side}, strategy={strategy_mode}, sl_percentage={sl_percentage}%, tp_percentage={tp_percentage}%")
                
                # Calculate SL/TP from entry price using strategy percentages (side-aware)
                if create_sl and not sl_price:
                    sl_price, _ = _compute_sl_tp_from_entry(entry_price, entry_side, sl_percentage, tp_percentage)
                    logger.info(f"Calculated SL price for {symbol}: {sl_price} (entry: {entry_price}, side={entry_side}, {sl_percentage}%)")
                
                if create_tp and (not tp_price or prefer_tp_from_pct):
                    _, tp_price = _compute_sl_tp_from_entry(entry_price, entry_side, sl_percentage, tp_percentage)
                    logger.info(
                        f"Calculated TP price for {symbol}: {tp_price} "
                        f"(entry: {entry_price}, side={entry_side}, {tp_percentage}%, "
                        f"prefer_pct={prefer_tp_from_pct})"
                    )
            
            # Round prices to reasonable precision before passing to exchange
            # The exchange will further format according to instrument tick size
            if sl_price:
                # Round to 4 decimals for prices < 100, 2 decimals for prices >= 100
                sl_price = round(sl_price, 2) if sl_price >= 100 else round(sl_price, 4)
            if tp_price:
                # Round to 4 decimals for prices < 100, 2 decimals for prices >= 100
                tp_price = round(tp_price, 2) if tp_price >= 100 else round(tp_price, 4)
            
            live_trading = os.getenv("LIVE_TRADING", "false").lower() == "true"
            dry_run_mode = not live_trading
            
            # Ensure entry_price is available for order creation (even if prices were already set)
            entry_side = "BUY"
            if not entry_price:
                recent_order = _find_recent_entry_order(db, symbol)
                if recent_order:
                    entry_price = float(recent_order.avg_price) if recent_order.avg_price else float(recent_order.price) if recent_order.price else None
                    entry_side = _entry_side_from_order(recent_order)
                    if entry_price:
                        logger.info(
                            f"✅ Using entry price from filled {entry_side} order for {symbol}: "
                            f"{entry_price} (Order ID: {recent_order.exchange_order_id})"
                        )
            
            # Get parent order ID from most recent filled entry order (for linking TP/SL)
            parent_order_id = None
            oco_group_id = None
            if entry_price:
                try:
                    recent_order = _find_recent_entry_order(db, symbol)
                    if recent_order:
                        parent_order_id = recent_order.exchange_order_id
                        entry_side = _entry_side_from_order(recent_order)
                        # Generate OCO group ID for linking SL and TP orders (same as automatic creation)
                        import uuid
                        oco_group_id = f"oco_{parent_order_id}_{int(datetime.utcnow().timestamp())}"
                        logger.info(f"Found parent order {parent_order_id} for {symbol}, using OCO group: {oco_group_id}")
                except Exception as e:
                    logger.warning(f"Could not get parent order ID for {symbol}: {e}")
            
            # Use the reusable TP/SL order creator functions (same as automatic creation)
            from app.services.sl_tp_protection import get_active_protection_order

            # Create SL order if requested
            sl_order_id = None
            sl_error = None
            if create_sl and sl_price and entry_price:
                existing_sl = (
                    get_active_protection_order(db, parent_order_id, "STOP_LOSS")
                    if parent_order_id
                    else None
                )
                if existing_sl:
                    sl_order_id = existing_sl.exchange_order_id
                    logger.info(
                        "Reusing existing SL %s for %s (parent %s)",
                        sl_order_id,
                        symbol,
                        parent_order_id,
                    )
                else:
                    sl_result = create_stop_loss_order(
                        db=db,
                        symbol=symbol,
                        side=entry_side,
                        sl_price=sl_price,
                        quantity=position_balance,
                        entry_price=entry_price,
                        parent_order_id=parent_order_id,
                        oco_group_id=oco_group_id,
                        dry_run=dry_run_mode,
                        source=source,
                    )
                    sl_order_id = sl_result.get("order_id")
                    sl_error = sl_result.get("error")
            
            # Create TP order if requested
            tp_order_id = None
            tp_error = None
            if create_tp and tp_price and entry_price:
                existing_tp = (
                    get_active_protection_order(db, parent_order_id, "TAKE_PROFIT")
                    if parent_order_id
                    else None
                )
                if existing_tp:
                    tp_order_id = existing_tp.exchange_order_id
                    logger.info(
                        "Reusing existing TP %s for %s (parent %s)",
                        tp_order_id,
                        symbol,
                        parent_order_id,
                    )
                else:
                    tp_result = create_take_profit_order(
                        db=db,
                        symbol=symbol,
                        side=entry_side,
                        tp_price=tp_price,
                        quantity=position_balance,
                        entry_price=entry_price,
                        parent_order_id=parent_order_id,
                        oco_group_id=oco_group_id,
                        dry_run=dry_run_mode,
                        source=source,
                    )
                    tp_order_id = tp_result.get("order_id")
                    tp_error = tp_result.get("error")
            
            # BR-3: ATOMIC ROLLBACK - If both SL and TP were requested, both must succeed
            # If one failed, cancel the other (rollback)
            if create_sl and create_tp:
                if sl_order_id and not tp_order_id:
                    # SL created but TP failed - ROLLBACK: cancel SL
                    logger.error(f"🚨 ATOMIC TP/SL VIOLATION: SL created but TP failed for {symbol}. Rolling back SL order {sl_order_id}.")
                    try:
                        cancel_result = trade_client.cancel_order(sl_order_id)
                        if "error" in cancel_result:
                            logger.error(f"❌ Failed to cancel SL order {sl_order_id} during rollback: {cancel_result.get('error')}")
                        else:
                            logger.info(f"✅ Rolled back SL order {sl_order_id} after TP creation failed")
                            sl_order_id = None  # Mark as rolled back
                    except Exception as cancel_err:
                        logger.error(f"❌ Exception during SL rollback for {symbol}: {cancel_err}", exc_info=True)
                    
                    # Emit SLTP_FAILED event with explicit reason (BR-4)
                    try:
                        from app.services.signal_monitor import _emit_lifecycle_event
                        from app.services.strategy_profiles import build_strategy_key
                        watchlist_for_event = db.query(WatchlistItem).filter(WatchlistItem.symbol == symbol).first()
                        strategy_key = build_strategy_key(watchlist_for_event) if watchlist_for_event else "unknown:unknown"
                        
                        error_msg = f"TP creation failed: {tp_error or 'unknown error'}"
                        _emit_lifecycle_event(
                            db=db,
                            symbol=symbol,
                            strategy_key=strategy_key,
                            side="BUY",
                            price=entry_price,
                            event_type="SLTP_FAILED",
                            event_reason="ATOMIC_VIOLATION_TP_FAILED_SL_ROLLED_BACK",
                            error_message=error_msg,
                        )
                    except Exception as emit_err:
                        logger.warning(f"Failed to emit SLTP_FAILED event for {symbol}: {emit_err}")
                        
                elif tp_order_id and not sl_order_id:
                    # TP created but SL failed - ROLLBACK: cancel TP
                    logger.error(f"🚨 ATOMIC TP/SL VIOLATION: TP created but SL failed for {symbol}. Rolling back TP order {tp_order_id}.")
                    try:
                        cancel_result = trade_client.cancel_order(tp_order_id)
                        if "error" in cancel_result:
                            logger.error(f"❌ Failed to cancel TP order {tp_order_id} during rollback: {cancel_result.get('error')}")
                        else:
                            logger.info(f"✅ Rolled back TP order {tp_order_id} after SL creation failed")
                            tp_order_id = None  # Mark as rolled back
                    except Exception as cancel_err:
                        logger.error(f"❌ Exception during TP rollback for {symbol}: {cancel_err}", exc_info=True)
                    
                    # Emit SLTP_FAILED event with explicit reason (BR-4)
                    try:
                        from app.services.signal_monitor import _emit_lifecycle_event
                        from app.services.strategy_profiles import build_strategy_key
                        watchlist_for_event = db.query(WatchlistItem).filter(WatchlistItem.symbol == symbol).first()
                        strategy_key = build_strategy_key(watchlist_for_event) if watchlist_for_event else "unknown:unknown"
                        
                        error_msg = f"SL creation failed: {sl_error or 'unknown error'}"
                        _emit_lifecycle_event(
                            db=db,
                            symbol=symbol,
                            strategy_key=strategy_key,
                            side="BUY",
                            price=entry_price,
                            event_type="SLTP_FAILED",
                            event_reason="ATOMIC_VIOLATION_SL_FAILED_TP_ROLLED_BACK",
                            error_message=error_msg,
                        )
                    except Exception as emit_err:
                        logger.warning(f"Failed to emit SLTP_FAILED event for {symbol}: {emit_err}")
            
            # Send notification
            if sl_order_id or tp_order_id:
                try:
                    # Get percentages from watchlist or calculate from prices
                    sl_pct = watchlist_item.sl_percentage if watchlist_item.sl_percentage else None
                    tp_pct = watchlist_item.tp_percentage if watchlist_item.tp_percentage else None
                    
                    # If percentages not set, calculate from entry price and SL/TP prices
                    if entry_price and entry_price > 0:
                        if not sl_pct and sl_price:
                            sl_pct = abs((entry_price - sl_price) / entry_price * 100)
                        if not tp_pct and tp_price:
                            tp_pct = abs((tp_price - entry_price) / entry_price * 100)
                    
                    telegram_notifier.send_sl_tp_orders(
                        symbol=symbol,
                        sl_price=sl_price,
                        tp_price=tp_price,
                        quantity=position_balance,
                        mode=watchlist_item.sl_tp_mode or "conservative",
                        sl_order_id=str(sl_order_id) if sl_order_id else None,
                        tp_order_id=str(tp_order_id) if tp_order_id else None,
                        original_order_id=None,
                        entry_price=entry_price,
                        sl_percentage=sl_pct,
                        tp_percentage=tp_pct
                    )
                    logger.info(f"✅ Sent Telegram notification for SL/TP orders: {symbol} - SL: {sl_order_id}, TP: {tp_order_id}")
                except Exception as e:
                    logger.error(f"❌ Failed to send Telegram notification for SL/TP orders: {symbol} - {e}", exc_info=True)
            
            # BR-3: ATOMIC SUCCESS CHECK - If both SL and TP were requested, both must succeed
            if create_sl and create_tp:
                # Both requested - both must succeed
                success = bool(sl_order_id and tp_order_id)
            else:
                # Only one requested (or neither) - success if requested one succeeded
                success = (create_sl and sl_order_id) or (create_tp and tp_order_id) or (not create_sl and not create_tp)
            
            # If there's an error and no success, include it in the main error field
            main_error = None
            if not success:
                if create_sl and create_tp:
                    # Both requested - failure means one or both failed
                    if not sl_order_id and not tp_order_id:
                        main_error = f"Both SL and TP orders failed. SL: {sl_error or 'unknown'}, TP: {tp_error or 'unknown'}"
                    elif not sl_order_id:
                        main_error = f"SL order failed: {sl_error or 'unknown'} (TP was rolled back)"
                    elif not tp_order_id:
                        main_error = f"TP order failed: {tp_error or 'unknown'} (SL was rolled back)"
                elif create_sl and sl_error:
                    main_error = f"SL order failed: {sl_error}"
                elif create_tp and tp_error:
                    main_error = f"TP order failed: {tp_error}"
                elif create_sl and not sl_order_id:
                    main_error = sl_error or "SL order creation failed (unknown reason)"
                elif create_tp and not tp_order_id:
                    main_error = tp_error or "TP order creation failed (unknown reason)"
            
            return {
                'success': success,
                'symbol': symbol,
                'sl_order_id': sl_order_id,
                'tp_order_id': tp_order_id,
                'sl_error': sl_error,
                'tp_error': tp_error,
                'error': main_error,  # Add main error field for easier access
                'dry_run': dry_run_mode
            }
            
        except Exception as e:
            logger.error(f"Error creating protection order for position {symbol}: {e}", exc_info=True)
            error_msg = str(e)
            # Provide more specific error message
            if "Watchlist item not found" in error_msg:
                return {
                    'success': False,
                    'error': f'Watchlist item not found for {symbol}. First add {symbol} to watchlist.'
                }
            elif "No open position" in error_msg:
                return {
                    'success': False,
                    'error': error_msg  # Already has good message
                }
            else:
                return {
                    'success': False,
                    'error': f'Error creating order: {error_msg}'
                }
    
    def create_sl_tp_for_position(self, db: Session, symbol: str, force: bool = False) -> Dict:
        """
        Create both SL and TP orders for a specific position
        
        Args:
            db: Database session
            symbol: Trading symbol (e.g., ETH_USDT)
            force: If True, create even if skip_reminder is set
        
        Returns:
            Dict with creation results
        """
        return self._create_protection_order(db, symbol, create_sl=True, create_tp=True, force=force)
    
    def skip_reminder_for_symbol(self, db: Session, symbol: str) -> bool:
        """Mark symbol to skip SL/TP reminders"""
        try:
            watchlist_item = db.query(WatchlistItem).filter(
                WatchlistItem.symbol == symbol
            ).first()
            
            if not watchlist_item:
                # Create watchlist item if it doesn't exist
                watchlist_item = WatchlistItem(
                    symbol=symbol,
                    exchange="CRYPTO_COM",
                    skip_sl_tp_reminder=True
                )
                db.add(watchlist_item)
            else:
                watchlist_item.skip_sl_tp_reminder = True
            
            db.commit()
            logger.info(f"Marked {symbol} to skip SL/TP reminders")
            return True
            
        except Exception as e:
            logger.error(f"Error skipping reminder for {symbol}: {e}")
            db.rollback()
            return False


# Global instance
sl_tp_checker_service = SLTPCheckerService()

