"""
Reusable service for creating Take Profit and Stop Loss orders.
This centralizes the logic used by both automatic and manual TP/SL creation.
"""
import os
import logging
import time
import decimal
from typing import Optional, Dict, Tuple
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session

from app.services.brokers.crypto_com_trade import trade_client
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.utils.trading_guardrails import can_place_real_order
from app.services.telegram_notifier import telegram_notifier

logger = logging.getLogger(__name__)

# Rate limiting for missing rules alerts: {symbol: last_alert_timestamp}
_rules_missing_alert_times: Dict[str, float] = {}
_RULES_MISSING_ALERT_COOLDOWN_SECONDS = 6 * 3600  # 6 hours


def resolve_sltp_margin_context(db: Session, symbol: str) -> Tuple[bool, Optional[float]]:
    """Return (is_margin, leverage) from watchlist for SL/TP placement."""
    from app.models.watchlist import WatchlistItem

    item = db.query(WatchlistItem).filter(WatchlistItem.symbol == symbol).first()
    if not item:
        return False, None
    is_margin = bool(getattr(item, "trade_on_margin", False))
    leverage_raw = getattr(item, "leverage", None)
    leverage = float(leverage_raw) if leverage_raw not in (None, "") else None
    return is_margin, leverage


def get_closing_side_from_entry(entry_side: str) -> str:
    """
    Get the correct closing side for TP/SL orders based on entry side.
    
    Args:
        entry_side: Original order side ("BUY" or "SELL")
        
    Returns:
        Closing side ("SELL" for BUY entry, "BUY" for SELL entry)
        
    Raises:
        ValueError: If entry_side is invalid
    """
    entry_side = entry_side.upper()
    if entry_side == "BUY":
        return "SELL"
    if entry_side == "SELL":
        return "BUY"
    raise ValueError(f"Invalid entry_side for TP/SL closing order: {entry_side}")


def is_native_oco_enabled() -> bool:
    """Feature flag: post-fill spot SL+TP via private/advanced/create-oco (default on)."""
    return os.getenv("SLTP_NATIVE_OCO", "true").strip().lower() in ("1", "true", "yes", "on")


def is_insufficient_acc_balance_error(error: Optional[object]) -> bool:
    """True when exchange rejected a leg because qty/balance is already reserved.

    Common after placing a full-qty SL first: the sibling TP then fails with
    INSUFFICIENT_ACC_BALANCE (ETH short / dual-trigger pattern).
    """
    if error is None:
        return False
    text = str(error).upper()
    return (
        "INSUFFICIENT_ACC_BALANCE" in text
        or "INSUFFICIENT_AVAILABLE_BALANCE" in text
        or "INSUFFICIENT_BALANCE" in text
    )


def cancel_protection_leg_on_exchange(
    db: Session,
    leg: ExchangeOrder,
    *,
    source: str = "auto",
) -> bool:
    """Cancel one active SL/TP on the exchange and mark it CANCELLED in DB."""
    if not leg or not leg.exchange_order_id:
        return False
    oid = str(leg.exchange_order_id)
    cancel_type = str(leg.order_type) if leg.order_type else None
    try:
        cancel_kwargs = {"order_type": cancel_type} if cancel_type else {}
        cancel_res = trade_client.cancel_order(oid, **cancel_kwargs)
    except TypeError:
        # Older cancel_order signatures may not accept order_type.
        try:
            cancel_res = trade_client.cancel_order(oid)
        except Exception as cancel_err:
            logger.warning(
                "[%s_OCO] cancel leg %s failed: %s",
                source.upper(),
                oid,
                cancel_err,
            )
            return False
    except Exception as cancel_err:
        logger.warning(
            "[%s_OCO] cancel leg %s failed: %s",
            source.upper(),
            oid,
            cancel_err,
        )
        return False

    if isinstance(cancel_res, dict) and cancel_res.get("error") and not cancel_res.get(
        "skipped"
    ):
        err_u = str(cancel_res.get("error") or "").upper()
        if (
            "NOT_FOUND" not in err_u
            and "CANCELLED" not in err_u
            and "CANCELED" not in err_u
        ):
            logger.warning(
                "[%s_OCO] cancel leg %s rejected: %s",
                source.upper(),
                oid,
                cancel_res.get("error"),
            )
            return False

    try:
        leg.status = OrderStatusEnum.CANCELLED
        if hasattr(leg, "updated_at"):
            leg.updated_at = datetime.now(timezone.utc)
        elif hasattr(leg, "exchange_update_time"):
            leg.exchange_update_time = datetime.now(timezone.utc)
        db.add(leg)
        db.commit()
    except Exception as db_err:
        logger.warning(
            "[%s_OCO] DB mark cancel failed for %s: %s",
            source.upper(),
            oid,
            db_err,
        )
        db.rollback()
        # Exchange cancel likely succeeded; continue so qty can be reused.
    logger.info("[%s_OCO] cancelled standalone protection leg %s", source.upper(), oid)
    return True


def ensure_spot_oco_protection(
    db: Session,
    symbol: str,
    side: str,
    tp_price: float,
    sl_price: float,
    quantity: float,
    entry_price: float,
    parent_order_id: Optional[str] = None,
    dry_run: bool = False,
    source: str = "auto",
    existing_sl: Optional[ExchangeOrder] = None,
    existing_tp: Optional[ExchangeOrder] = None,
) -> Dict:
    """
    Spot-only: ensure SL+TP exist as ONE native Crypto.com OCO.

    If a standalone leg already exists (typical half-protected backfill), cancel
    it first so qty is free, then place native OCO for both legs. This is the
    only safe way to avoid INSUFFICIENT_ACC_BALANCE on spot full-qty triggers.
    """
    if not is_native_oco_enabled():
        return {
            "sl_result": {"order_id": None, "error": None},
            "tp_result": {"order_id": None, "error": None},
            "oco_group_id": None,
            "error": "native_oco_disabled",
            "skipped": True,
        }

    if parent_order_id and (existing_sl is None or existing_tp is None):
        from app.services.sl_tp_protection import get_active_protection_order

        if existing_sl is None:
            existing_sl = get_active_protection_order(db, parent_order_id, "STOP_LOSS")
        if existing_tp is None:
            existing_tp = get_active_protection_order(db, parent_order_id, "TAKE_PROFIT")

    if existing_sl and existing_tp:
        return {
            "sl_result": {"order_id": existing_sl.exchange_order_id, "error": None},
            "tp_result": {"order_id": existing_tp.exchange_order_id, "error": None},
            "oco_group_id": existing_sl.oco_group_id or existing_tp.oco_group_id,
            "error": None,
            "status": "already_protected",
            "sl_newly_created": False,
            "tp_newly_created": False,
        }

    cancelled: list = []
    for leg in (existing_sl, existing_tp):
        if not leg:
            continue
        if dry_run:
            cancelled.append(str(leg.exchange_order_id))
            continue
        if cancel_protection_leg_on_exchange(db, leg, source=source):
            cancelled.append(str(leg.exchange_order_id))
        else:
            err = (
                f"Failed to cancel standalone {leg.order_role} "
                f"{leg.exchange_order_id} before native OCO"
            )
            return {
                "sl_result": {"order_id": None, "error": err},
                "tp_result": {"order_id": None, "error": err},
                "oco_group_id": None,
                "error": err,
                "cancelled_legs": cancelled,
            }

    if cancelled:
        logger.info(
            "[%s_OCO] cancelled standalone legs %s for %s before native OCO recreate",
            source.upper(),
            cancelled,
            symbol,
        )

    oco_res = create_oco_protection_orders(
        db=db,
        symbol=symbol,
        side=side,
        tp_price=tp_price,
        sl_price=sl_price,
        quantity=quantity,
        entry_price=entry_price,
        parent_order_id=parent_order_id,
        dry_run=dry_run,
        source=source,
    )
    if cancelled:
        oco_res = {**oco_res, "cancelled_legs": cancelled, "replaced_standalone": True}
    return oco_res


def create_oco_protection_orders(
    db: Session,
    symbol: str,
    side: str,
    tp_price: float,
    sl_price: float,
    quantity: float,
    entry_price: float,
    parent_order_id: Optional[str] = None,
    dry_run: bool = False,
    source: str = "auto",
) -> Dict:
    """
    Create SL+TP as a native Crypto.com OCO (LIMIT TP + STOP_LIMIT SL).

    Persists both legs with ``oco_group_id = exchange list_id``. Spot only —
    callers must not use this for margin (use standalone creators instead).

    Returns keys aligned with ``_create_sl_tp_impl`` consumers:
    ``sl_result``, ``tp_result``, ``oco_group_id``, plus ``error`` on failure.
    """
    entry_side = side.upper()
    closing_side = get_closing_side_from_entry(entry_side)

    if parent_order_id and not dry_run:
        from app.services.sl_tp_protection import get_active_protection_order

        existing_sl = get_active_protection_order(db, parent_order_id, "STOP_LOSS")
        existing_tp = get_active_protection_order(db, parent_order_id, "TAKE_PROFIT")
        if existing_sl and existing_tp:
            return {
                "sl_result": {"order_id": existing_sl.exchange_order_id, "error": None},
                "tp_result": {"order_id": existing_tp.exchange_order_id, "error": None},
                "oco_group_id": existing_sl.oco_group_id or existing_tp.oco_group_id,
                "error": None,
                "status": "already_protected",
            }

    if not dry_run:
        order_usd_value = float(entry_price) * float(quantity)
        allowed, block_reason = can_place_real_order(
            db=db,
            symbol=symbol,
            order_usd_value=order_usd_value,
            side=closing_side,
            ignore_trade_yes=True,
            ignore_daily_limit=True,
            ignore_usd_limit=True,
            ignore_cooldown=True,
        )
        if not allowed:
            err = f"Guardrail blocked native OCO: {block_reason}"
            logger.warning("[%s_OCO] %s", source.upper(), err)
            return {
                "sl_result": {"order_id": None, "error": err},
                "tp_result": {"order_id": None, "error": err},
                "oco_group_id": None,
                "error": err,
            }

    # Native OCO previously sent entry-based TP/SL without a live-mark check.
    # Late post-fill (or delayed ensure) with tight TP% (e.g. +1%) already behind
    # the market → Crypto.com REJECTED → stuck SL-only lots (prod AAVE_USD).
    # Standalone create_take_profit_order already repairs; OCO must too.
    tp_adjust = None
    sl_adjust = None
    if not dry_run:
        from app.utils.sl_trigger_guard import (
            ensure_valid_sl_trigger,
            ensure_valid_tp_trigger,
            fetch_ticker_prices,
            reference_price_for_trigger,
        )

        tp_percentage = None
        sl_percentage = None
        try:
            from app.models.watchlist import WatchlistItem

            wl = db.query(WatchlistItem).filter(WatchlistItem.symbol == symbol).first()
            if wl and wl.tp_percentage is not None and float(wl.tp_percentage) > 0:
                tp_percentage = float(wl.tp_percentage)
            if wl and wl.sl_percentage is not None and float(wl.sl_percentage) > 0:
                sl_percentage = float(wl.sl_percentage)
        except Exception as wl_err:
            logger.debug(
                "[%s_OCO] watchlist pct lookup failed for %s: %s",
                source.upper(),
                symbol,
                wl_err,
            )

        ticker = fetch_ticker_prices(symbol)
        market_ref = reference_price_for_trigger(
            entry_side, is_tp=True, ticker=ticker
        )
        tp_price, tp_adjust = ensure_valid_tp_trigger(
            entry_side=entry_side,
            tp_price=float(tp_price),
            last_price=market_ref,
            tp_percentage=tp_percentage,
            entry_price=float(entry_price) if entry_price else None,
            ticker=ticker,
        )
        sl_price, sl_adjust = ensure_valid_sl_trigger(
            entry_side=entry_side,
            sl_price=float(sl_price),
            last_price=reference_price_for_trigger(
                entry_side, is_tp=False, ticker=ticker, last_price=market_ref
            ),
            sl_percentage=sl_percentage,
            entry_price=float(entry_price) if entry_price else None,
            ticker=ticker,
        )
        if tp_adjust:
            logger.warning(
                "[%s_OCO] Adjusted TP for %s: %s", source.upper(), symbol, tp_adjust
            )
        if sl_adjust:
            logger.warning(
                "[%s_OCO] Adjusted SL for %s: %s", source.upper(), symbol, sl_adjust
            )

    if not dry_run:
        try:
            from app.services.exchange_sync import _base_wallet_balance_from_accounts
            from app.services.sl_tp_protection import cap_protection_quantity_to_wallet
            from app.services.brokers.crypto_com_trade import trade_client

            summary = trade_client.get_account_summary()
            accounts = summary.get("accounts") or []
            wallet_bal = _base_wallet_balance_from_accounts(accounts, symbol)
            quantity, cap_reason = cap_protection_quantity_to_wallet(
                symbol, entry_side, float(quantity), wallet_bal
            )
            if cap_reason == "wallet_empty_long":
                err = f"wallet_empty_long: no {symbol} balance for protection"
                logger.error("[%s_OCO] %s", source.upper(), err)
                return {
                    "sl_result": {"order_id": None, "error": err},
                    "tp_result": {"order_id": None, "error": err},
                    "oco_group_id": None,
                    "error": err,
                }
        except Exception as bal_err:
            logger.warning(
                "[%s_OCO] wallet balance lookup failed for %s: %s",
                source.upper(),
                symbol,
                bal_err,
            )

    logger.info(
        "[%s_OCO] Creating native OCO: %s closing_side=%s qty=%s tp=%s sl=%s entry=%s",
        source.upper(),
        symbol,
        closing_side,
        quantity,
        tp_price,
        sl_price,
        entry_price,
    )

    try:
        oco = trade_client.place_oco_sl_tp(
            symbol=symbol,
            side=closing_side,
            tp_price=float(tp_price),
            sl_price=float(sl_price),
            qty=float(quantity),
            dry_run=dry_run,
            source=source,
        )
    except Exception as exc:
        err = str(exc)
        logger.error("[%s_OCO] place_oco_sl_tp raised: %s", source.upper(), err, exc_info=True)
        return {
            "sl_result": {"order_id": None, "error": err},
            "tp_result": {"order_id": None, "error": err},
            "oco_group_id": None,
            "error": err,
        }

    if oco.get("error"):
        err = str(oco.get("error"))
        logger.error("[%s_OCO] Failed for %s: %s", source.upper(), symbol, err)
        return {
            "sl_result": {"order_id": None, "error": err},
            "tp_result": {"order_id": None, "error": err},
            "oco_group_id": None,
            "error": err,
        }

    list_id = oco.get("list_id")
    oco_group_id = str(list_id) if list_id is not None else None
    # Prefer resolved child ids; fall back to stable placeholders tied to list_id
    # so Telegram/DB linkage works until sync reconciles real exchange order ids.
    tp_order_id = oco.get("tp_order_id") or (f"oco_tp_{oco_group_id}" if oco_group_id else None)
    sl_order_id = oco.get("sl_order_id") or (f"oco_sl_{oco_group_id}" if oco_group_id else None)
    tp_order_type = oco.get("tp_order_type") or "LIMIT"
    sl_order_type = oco.get("sl_order_type") or "STOP_LIMIT"
    closing_enum = OrderSideEnum.SELL if entry_side == "BUY" else OrderSideEnum.BUY

    if parent_order_id and oco_group_id:
        try:
            if sl_order_id:
                db.add(
                    ExchangeOrder(
                        exchange_order_id=str(sl_order_id),
                        symbol=symbol,
                        side=closing_enum,
                        order_type=str(sl_order_type),
                        status=OrderStatusEnum.NEW,
                        price=sl_price,
                        quantity=quantity,
                        parent_order_id=parent_order_id,
                        oco_group_id=oco_group_id,
                        order_role="STOP_LOSS",
                        exchange_create_time=datetime.utcnow(),
                    )
                )
            if tp_order_id:
                db.add(
                    ExchangeOrder(
                        exchange_order_id=str(tp_order_id),
                        symbol=symbol,
                        side=closing_enum,
                        order_type=str(tp_order_type),
                        status=OrderStatusEnum.NEW,
                        price=tp_price,
                        quantity=quantity,
                        parent_order_id=parent_order_id,
                        oco_group_id=oco_group_id,
                        order_role="TAKE_PROFIT",
                        exchange_create_time=datetime.utcnow(),
                    )
                )
            db.commit()
            logger.info(
                "[%s_OCO] Saved OCO legs for %s list_id=%s sl=%s tp=%s",
                source.upper(),
                symbol,
                oco_group_id,
                sl_order_id,
                tp_order_id,
            )
        except Exception as db_err:
            logger.warning("[%s_OCO] Failed to save OCO legs: %s", source.upper(), db_err)
            db.rollback()

    return {
        "sl_result": {"order_id": sl_order_id, "error": None},
        "tp_result": {"order_id": tp_order_id, "error": None},
        "oco_group_id": oco_group_id,
        "error": None,
        "sl_newly_created": bool(sl_order_id),
        "tp_newly_created": bool(tp_order_id),
    }


def create_take_profit_order(
    db: Session,
    symbol: str,
    side: str,  # "BUY" or "SELL" - the original order side
    tp_price: float,
    quantity: float,
    entry_price: float,
    parent_order_id: Optional[str] = None,
    oco_group_id: Optional[str] = None,
    is_margin: bool = False,
    leverage: Optional[float] = None,
    dry_run: bool = False,
    source: str = "auto"  # "auto" or "manual" to track the source
) -> Dict:
    """
    Create a Take Profit order using the same logic as automatic TP creation.
    
    Args:
        db: Database session
        symbol: Trading symbol (e.g., "ETH_USDT")
        side: Original order side ("BUY" or "SELL")
        tp_price: Take profit price
        quantity: Order quantity
        entry_price: Entry price (filled BUY price) - REQUIRED for ref_price
        parent_order_id: Parent order ID (optional, for linking)
        oco_group_id: OCO group ID (optional, for linking SL/TP)
        dry_run: Whether to run in dry-run mode
        
    Returns:
        Dict with 'order_id' (if successful) or 'error' (if failed)
    """
    # Determine correct side for TP order using helper function
    # After BUY: TP is SELL (sell at profit)
    # After SELL: TP is BUY (buy at profit)
    entry_side = side.upper()  # Ensure uppercase
    tp_side = get_closing_side_from_entry(entry_side)
    watchlist_is_margin, watchlist_leverage = resolve_sltp_margin_context(db, symbol)
    if not is_margin:
        is_margin = watchlist_is_margin
    if leverage is None:
        leverage = watchlist_leverage

    if parent_order_id and not dry_run:
        from app.services.sl_tp_protection import get_active_protection_order

        existing_tp = get_active_protection_order(db, parent_order_id, "TAKE_PROFIT")
        if existing_tp:
            existing_qty = float(getattr(existing_tp, "quantity", 0) or 0)
            requested_qty = float(quantity or 0)
            # Mirror SL gap-fill: reuse only when existing covers requested size.
            # Dashboard SL/TP Check passes uncovered_qty — a dust TP on the parent
            # must not block placing the remaining wallet gap.
            covers_request = (
                existing_qty <= 0
                or requested_qty <= 0
                or existing_qty + 1e-9 >= requested_qty * 0.98
            )
            if covers_request:
                logger.info(
                    "[%s_TP] Reusing active TP %s for parent %s (qty=%s requested=%s)",
                    source.upper(),
                    existing_tp.exchange_order_id,
                    parent_order_id,
                    existing_qty,
                    requested_qty,
                )
                return {"order_id": existing_tp.exchange_order_id, "error": None}
            logger.info(
                "[%s_TP] Active TP %s qty=%s < requested=%s; placing additional TP",
                source.upper(),
                existing_tp.exchange_order_id,
                existing_qty,
                requested_qty,
            )

    # Repair stale TP vs live market (short TP above last → INVALID_TRIGGER_PRICE).
    tp_percentage = None
    try:
        from app.models.watchlist import WatchlistItem

        wl = db.query(WatchlistItem).filter(WatchlistItem.symbol == symbol).first()
        if wl and wl.tp_percentage is not None and float(wl.tp_percentage) > 0:
            tp_percentage = float(wl.tp_percentage)
    except Exception as wl_err:
        logger.debug("Could not read watchlist tp_percentage for %s: %s", symbol, wl_err)

    if not dry_run:
        from app.utils.sl_trigger_guard import (
            ensure_tp_clear_of_market_after_tick,
            ensure_valid_tp_trigger,
            fetch_ticker_prices,
            reference_price_for_trigger,
        )

        ticker = fetch_ticker_prices(symbol)
        market_ref = reference_price_for_trigger(
            entry_side, is_tp=True, ticker=ticker
        )
        tp_price, tp_adjust = ensure_valid_tp_trigger(
            entry_side=entry_side,
            tp_price=float(tp_price),
            last_price=market_ref,
            tp_percentage=tp_percentage,
            entry_price=float(entry_price) if entry_price else None,
            ticker=ticker,
        )
        if tp_adjust:
            logger.warning("[%s_TP] Adjusted TP for %s: %s", source.upper(), symbol, tp_adjust)

        # Side-aware tick rounding can push a barely-valid short TP back above
        # market (ROUND_UP legacy). Nudge away from market using tick size.
        try:
            tick_raw = (trade_client._get_instrument_metadata(symbol) or {}).get(
                "price_tick_size"
            )
            tick_f = float(tick_raw) if tick_raw not in (None, "") else None
        except (TypeError, ValueError):
            tick_f = None
        if market_ref and market_ref > 0:
            cleared = ensure_tp_clear_of_market_after_tick(
                entry_side=entry_side,
                tp_price=float(tp_price),
                market_price=float(market_ref),
                tick_size=tick_f,
            )
            if cleared != float(tp_price):
                logger.warning(
                    "[%s_TP] Post-tick TP clear for %s: %s -> %s (market_ref=%s tick=%s)",
                    source.upper(),
                    symbol,
                    tp_price,
                    cleared,
                    market_ref,
                    tick_f,
                )
                tp_price = cleared

    # Place TP at the (possibly repaired) watchlist/calculated price.
    
    # Price formatting is handled by place_take_profit_order using normalize_price()
    # which follows docs/trading/crypto_com_order_formatting.md rules:
    # - TAKE_PROFIT uses ROUND_UP (per Rule 3)
    # - Uses Decimal for calculations (per Rule 1)
    # - Fetches instrument metadata (per Rule 5)
    # - Preserves trailing zeros (per Rule 4)
    # No pre-formatting needed here - pass raw price to place_take_profit_order
    
    # For TAKE_PROFIT_LIMIT: both trigger_price and price must equal tp_price
    tp_trigger = tp_price
    tp_execution_price = tp_price
    
    logger.info(
        f"[{source.upper()}_TP] Creating TP order as TAKE_PROFIT_LIMIT: {symbol}, original_side={entry_side}, "
        f"tp_side={tp_side}, price={tp_execution_price}, trigger={tp_trigger}, "
        f"qty={quantity}, entry_price={entry_price}"
    )
    
    # Log closing side details before sending to exchange
    logger.info(
        f"[TP_ORDER][{source.upper()}] Closing TP side={tp_side}, entry_side={entry_side}, "
        f"ref_price={entry_price}, price={tp_execution_price}, instrument={symbol}"
    )
    
    tp_order_id = None
    tp_order_error = None
    
    try:
        # Log detailed payload before sending to exchange
        logger.info(
            f"[{source.upper()}_TP] PAYLOAD DETAILS before calling place_take_profit_order:\n"
            f"  symbol={symbol}\n"
            f"  side={tp_side} (original_side={entry_side}, closing_side={tp_side})\n"
            f"  price={tp_execution_price}\n"
            f"  qty={quantity}\n"
            f"  trigger_price={tp_trigger}\n"
            f"  entry_price={entry_price}\n"
            f"  dry_run={dry_run}\n"
            f"  source={source}"
        )
        
        # Check guardrails before placing TP order (ignore Trade Yes since this is for existing position)
        if not dry_run:
            order_usd_value = tp_execution_price * quantity
            allowed, block_reason = can_place_real_order(
                db=db,
                symbol=symbol,
                order_usd_value=order_usd_value,
                side=tp_side,
                ignore_trade_yes=True,  # SL/TP is for existing positions
                ignore_daily_limit=True,  # Do not block protective orders by daily limit
                ignore_usd_limit=True,  # Do not block protective orders by USD limit
                ignore_cooldown=True,  # Protective orders must never be throttled by the entry cooldown
                # Exempt from LIVE_TRADING toggle + kill switch: never strip protection
                is_protective_order=True,
                parent_order_id=parent_order_id,
            )
            if not allowed:
                # Emit lifecycle event and send Telegram notification
                try:
                    from app.services.signal_monitor import _emit_lifecycle_event
                    _emit_lifecycle_event(
                        db=db,
                        symbol=symbol,
                        strategy_key="",  # Not available for SL/TP
                        side=tp_side,
                        price=tp_execution_price,
                        event_type="SLTP_BLOCKED",
                        event_reason=f"TP blocked: {block_reason}",
                    )
                except Exception as e:
                    logger.warning(f"Failed to emit lifecycle event for blocked TP: {e}")
                
                # Send Telegram notification
                try:
                    telegram_notifier.send_message(
                        f"🚫 <b>SL/TP BLOCKED</b>\n\n"
                        f"📊 Symbol: <b>{symbol}</b>\n"
                        f"🔄 Type: TAKE PROFIT\n"
                        f"💰 Price: ${tp_execution_price:.4f}\n"
                        f"📦 Quantity: {quantity}\n\n"
                        f"🚫 <b>Reason:</b> {block_reason}",
                        symbol=symbol,
                    )
                except Exception as e:
                    logger.warning(f"Failed to send Telegram alert for blocked TP: {e}")
                
                logger.warning(f"🚫 SL/TP_BLOCKED: {symbol} TP {tp_side} - {block_reason}")
                return {"order_id": None, "error": f"SL/TP blocked: {block_reason}"}
        
        # PART B: Fetch instrument rules ONCE and log structured [SLTP_NORMALIZE] for TP
        inst_meta_tp = trade_client._get_instrument_metadata(symbol)
        if not inst_meta_tp:
            # Rules missing - log and handle rate-limited alert
            logger.error(
                f"[SLTP_NORMALIZE] symbol={symbol} raw_qty={quantity} min_qty=? step=? min_notional=? "
                f"normalized_qty=? rounded_qty=? ok=false reason=rules_missing"
            )
            
            # Rate-limited telegram alert (once per symbol per 6h)
            current_time = time.time()
            last_alert_time = _rules_missing_alert_times.get(symbol, 0)
            if current_time - last_alert_time >= _RULES_MISSING_ALERT_COOLDOWN_SECONDS:
                try:
                    telegram_notifier.send_message(
                        f"⚠️ <b>INSTRUMENT RULES MISSING</b>\n\n"
                        f"Symbol: {symbol}\n"
                        f"Position status: <b>UNPROTECTED_RULES_MISSING</b>\n\n"
                        f"Cannot create SL/TP order - instrument metadata unavailable.\n"
                        f"Please check exchange connectivity."
                    )
                    _rules_missing_alert_times[symbol] = current_time
                    logger.info(f"✅ Sent rate-limited alert for missing rules: {symbol}")
                except Exception as telegram_err:
                    logger.warning(f"Failed to send missing rules alert: {telegram_err}")
        else:
            # Fetch all instrument rules
            min_qty_str = inst_meta_tp.get("min_quantity", "0.001")
            step_size_str = inst_meta_tp.get("qty_tick_size", "0.001")
            min_notional_str = inst_meta_tp.get("min_notional", "0")
            quantity_decimals = inst_meta_tp.get("quantity_decimals", 8)
            
            # Normalize quantity to get actual normalized value
            normalized_qty_str = trade_client.normalize_quantity(symbol, quantity)
            
            # Calculate rounded_qty (what we'd use if normalization succeeded)
            rounded_qty = "?"
            if normalized_qty_str:
                rounded_qty = normalized_qty_str
            else:
                # Calculate what the rounded value would be (even if below min)
                try:
                    qty_decimal = decimal.Decimal(str(quantity))
                    step_decimal = decimal.Decimal(str(step_size_str))
                    if step_decimal > 0:
                        division_result = qty_decimal / step_decimal
                        floored_result = division_result.quantize(decimal.Decimal('1'), rounding=decimal.ROUND_FLOOR)
                        rounded_qty_decimal = floored_result * step_decimal
                        rounded_qty = format(rounded_qty_decimal, f'.{quantity_decimals}f')
                except Exception as e:
                    logger.debug(f"Could not calculate rounded_qty: {e}")
            
            # Log structured [SLTP_NORMALIZE] with all numeric values
            ok_status = "true" if normalized_qty_str else "false"
            reason = "success" if normalized_qty_str else "below_min_qty"
            logger.info(
                f"[SLTP_NORMALIZE] symbol={symbol} raw_qty={quantity} min_qty={min_qty_str} "
                f"step={step_size_str} min_notional={min_notional_str} normalized_qty={normalized_qty_str or 'None'} "
                f"rounded_qty={rounded_qty} ok={ok_status} reason={reason}"
            )
        
        # Create TAKE_PROFIT_LIMIT order with trigger_price and price both equal to tp_price
        tp_order = trade_client.place_take_profit_order(
            symbol=symbol,
            side=tp_side,  # SELL for BUY orders, BUY for SELL orders
            price=tp_execution_price,  # Execution price = tp_price
            qty=quantity,  # Same quantity as the filled order
            trigger_price=tp_trigger,  # Trigger price = tp_price (same as execution price)
            entry_price=entry_price,  # REQUIRED: Use entry price for ref_price
            is_margin=is_margin,
            leverage=leverage,
            dry_run=dry_run,
            source=source  # Propagate source to HTTP logging
        )
        
        if "error" not in tp_order:
            tp_order_id = tp_order.get("order_id") or tp_order.get("client_order_id")
            logger.info(
                f"✅ Created TP order (TAKE_PROFIT_LIMIT) for {symbol} @ {tp_price} "
                f"(trigger={tp_trigger}, price={tp_execution_price})"
            )
            
            # Save TP order to database with OCO fields (same as automatic creation)
            if tp_order_id and parent_order_id:
                try:
                    tp_db_order = ExchangeOrder(
                        exchange_order_id=str(tp_order_id),
                        symbol=symbol,
                        side=OrderSideEnum.SELL if entry_side == "BUY" else OrderSideEnum.BUY,
                        order_type="TAKE_PROFIT_LIMIT",
                        status=OrderStatusEnum.NEW,
                        price=tp_price,
                        quantity=quantity,
                        parent_order_id=parent_order_id,
                        oco_group_id=oco_group_id,
                        order_role="TAKE_PROFIT",
                        exchange_create_time=datetime.utcnow()
                    )
                    db.add(tp_db_order)
                    db.commit()
                    logger.info(f"✅ Saved TP order to DB with OCO group: {oco_group_id}")
                except Exception as db_err:
                    logger.warning(f"Failed to save TP order to database: {db_err}")
                    db.rollback()
            
            return {"order_id": tp_order_id, "error": None}
        else:
            tp_order_error = tp_order.get("error", "Unknown error")
            logger.error(f"❌ Failed to create TP order (TAKE_PROFIT_LIMIT) for {symbol} @ {tp_price}: {tp_order_error}")
            return {"order_id": None, "error": tp_order_error}
            
    except Exception as e:
        tp_order_error = str(e)
        logger.error(f"❌ Error creating TP order (TAKE_PROFIT_LIMIT) for {symbol}: {e}", exc_info=True)
        return {"order_id": None, "error": tp_order_error}


def create_stop_loss_order(
    db: Session,
    symbol: str,
    side: str,  # "BUY" or "SELL" - the original order side
    sl_price: float,
    quantity: float,
    entry_price: float,
    parent_order_id: Optional[str] = None,
    oco_group_id: Optional[str] = None,
    is_margin: bool = False,
    leverage: Optional[float] = None,
    dry_run: bool = False,
    source: str = "auto",  # "auto" or "manual" to track the source
    sl_percentage: Optional[float] = None,
) -> Dict:
    """
    Create a Stop Loss order using the same logic as automatic SL creation.
    
    Args:
        db: Database session
        symbol: Trading symbol (e.g., "ETH_USDT")
        side: Original order side ("BUY" or "SELL")
        sl_price: Stop loss price
        quantity: Order quantity
        entry_price: Entry price (filled BUY price) - REQUIRED for ref_price
        parent_order_id: Parent order ID (optional, for linking)
        oco_group_id: OCO group ID (optional, for linking SL/TP)
        dry_run: Whether to run in dry-run mode
        sl_percentage: Optional SL %% used to repair triggers on the wrong side of market
        
    Returns:
        Dict with 'order_id' (if successful) or 'error' (if failed)
    """
    # Price formatting is handled by place_stop_loss_order using normalize_price()
    # which follows docs/trading/crypto_com_order_formatting.md rules:
    # - STOP_LOSS uses ROUND_DOWN (per Rule 3)
    # - Uses Decimal for calculations (per Rule 1)
    # - Fetches instrument metadata (per Rule 5)
    # - Preserves trailing zeros (per Rule 4)
    # No pre-formatting needed here - pass raw price to place_stop_loss_order
    from app.utils.http_client import http_get, http_post
    from app.utils.sl_trigger_guard import (
        compute_market_relative_sl,
        derive_sl_percentage,
        ensure_valid_sl_trigger,
        error_is_invalid_trigger_price,
        fetch_ticker_prices,
        reference_price_for_trigger,
    )
    
    # IMPORTANT: trigger_price must be equal to sl_price for STOP_LIMIT orders
    entry_side = side.upper()  # Ensure uppercase
    sl_side = get_closing_side_from_entry(entry_side)
    watchlist_is_margin, watchlist_leverage = resolve_sltp_margin_context(db, symbol)
    if not is_margin:
        is_margin = watchlist_is_margin
    if leverage is None:
        leverage = watchlist_leverage

    if sl_percentage is None:
        try:
            from app.models.watchlist import WatchlistItem

            wl = db.query(WatchlistItem).filter(WatchlistItem.symbol == symbol).first()
            if wl and wl.sl_percentage is not None and float(wl.sl_percentage) > 0:
                sl_percentage = float(wl.sl_percentage)
        except Exception as wl_err:
            logger.debug("Could not read watchlist sl_percentage for %s: %s", symbol, wl_err)

    # Reject stale absolute SL on the wrong side of market (INVALID_TRIGGER_PRICE)
    ticker = None if dry_run else fetch_ticker_prices(symbol)
    last_price = reference_price_for_trigger(
        entry_side, is_tp=False, ticker=ticker
    )
    sl_price, adjust_reason = ensure_valid_sl_trigger(
        entry_side=entry_side,
        sl_price=float(sl_price),
        last_price=last_price,
        sl_percentage=sl_percentage,
        entry_price=float(entry_price) if entry_price else None,
        ticker=ticker,
    )
    if adjust_reason:
        logger.warning("[%s_SL] Adjusted SL for %s: %s", source.upper(), symbol, adjust_reason)

    sl_trigger = sl_price  # trigger_price equals sl_price

    if parent_order_id and not dry_run:
        from app.services.sl_tp_protection import get_active_protection_order

        existing_sl = get_active_protection_order(db, parent_order_id, "STOP_LOSS")
        if existing_sl:
            existing_qty = float(getattr(existing_sl, "quantity", 0) or 0)
            requested_qty = float(quantity or 0)
            # Reuse when qty unknown/missing (legacy idempotency) or already covers request.
            # Ops ALGO gap fill: existing SL qty=124 with requested gap=470 must place more.
            covers_request = (
                existing_qty <= 0
                or requested_qty <= 0
                or existing_qty + 1e-9 >= requested_qty * 0.98
            )
            if covers_request:
                logger.info(
                    "[%s_SL] Reusing active SL %s for parent %s (qty=%s requested=%s)",
                    source.upper(),
                    existing_sl.exchange_order_id,
                    parent_order_id,
                    existing_qty,
                    requested_qty,
                )
                return {"order_id": existing_sl.exchange_order_id, "error": None}
            logger.info(
                "[%s_SL] Active SL %s qty=%s < requested=%s; placing additional SL",
                source.upper(),
                existing_sl.exchange_order_id,
                existing_qty,
                requested_qty,
            )
    
    logger.info(
        f"[{source.upper()}_SL] Creating SL order: {symbol}, entry_side={entry_side}, closing_side={sl_side}, "
        f"sl_price={sl_price}, trigger={sl_trigger}, qty={quantity}, entry_price={entry_price}"
    )
    
    sl_order_id = None
    sl_order_error = None
    
    try:
        # Log detailed payload before sending to exchange
        logger.info(
            f"[{source.upper()}_SL] PAYLOAD DETAILS before calling place_stop_loss_order:\n"
            f"  symbol={symbol}\n"
            f"  side={sl_side} (original_side={entry_side}, closing_side={sl_side})\n"
            f"  price={sl_price}\n"
            f"  qty={quantity}\n"
            f"  trigger_price={sl_trigger}\n"
            f"  entry_price={entry_price}\n"
            f"  dry_run={dry_run}\n"
            f"  source={source}"
        )
        
        # Check guardrails before placing SL order (ignore Trade Yes since this is for existing position)
        if not dry_run:
            order_usd_value = sl_price * quantity
            allowed, block_reason = can_place_real_order(
                db=db,
                symbol=symbol,
                order_usd_value=order_usd_value,
                side=sl_side,
                ignore_trade_yes=True,  # SL/TP is for existing positions
                ignore_daily_limit=True,  # Do not block protective orders by daily limit
                ignore_usd_limit=True,  # Do not block protective orders by USD limit
                ignore_cooldown=True,  # Protective orders must never be throttled by the entry cooldown
                # Exempt from LIVE_TRADING toggle + kill switch: never strip protection
                is_protective_order=True,
                parent_order_id=parent_order_id,
            )
            if not allowed:
                # Emit lifecycle event and send Telegram notification
                try:
                    from app.services.signal_monitor import _emit_lifecycle_event
                    _emit_lifecycle_event(
                        db=db,
                        symbol=symbol,
                        strategy_key="",  # Not available for SL/TP
                        side=sl_side,
                        price=sl_price,
                        event_type="SLTP_BLOCKED",
                        event_reason=f"SL blocked: {block_reason}",
                    )
                except Exception as e:
                    logger.warning(f"Failed to emit lifecycle event for blocked SL: {e}")
                
                # Send Telegram notification
                try:
                    telegram_notifier.send_message(
                        f"🚫 <b>SL/TP BLOCKED</b>\n\n"
                        f"📊 Symbol: <b>{symbol}</b>\n"
                        f"🔄 Type: STOP LOSS\n"
                        f"💰 Price: ${sl_price:.4f}\n"
                        f"📦 Quantity: {quantity}\n\n"
                        f"🚫 <b>Reason:</b> {block_reason}",
                        symbol=symbol,
                    )
                except Exception as e:
                    logger.warning(f"Failed to send Telegram alert for blocked SL: {e}")
                
                logger.warning(f"🚫 SL/TP_BLOCKED: {symbol} SL {sl_side} - {block_reason}")
                return {"order_id": None, "error": f"SL/TP blocked: {block_reason}"}
        
        # PART B: Fetch instrument rules ONCE and log structured [SLTP_NORMALIZE]
        inst_meta = trade_client._get_instrument_metadata(symbol)
        if not inst_meta:
            # Rules missing - log and handle rate-limited alert
            logger.error(
                f"[SLTP_NORMALIZE] symbol={symbol} raw_qty={quantity} min_qty=? step=? min_notional=? "
                f"normalized_qty=? rounded_qty=? ok=false reason=rules_missing"
            )
            
            # Rate-limited telegram alert (once per symbol per 6h)
            current_time = time.time()
            last_alert_time = _rules_missing_alert_times.get(symbol, 0)
            if current_time - last_alert_time >= _RULES_MISSING_ALERT_COOLDOWN_SECONDS:
                try:
                    telegram_notifier.send_message(
                        f"⚠️ <b>INSTRUMENT RULES MISSING</b>\n\n"
                        f"Symbol: {symbol}\n"
                        f"Position status: <b>UNPROTECTED_RULES_MISSING</b>\n\n"
                        f"Cannot create SL/TP order - instrument metadata unavailable.\n"
                        f"Please check exchange connectivity."
                    )
                    _rules_missing_alert_times[symbol] = current_time
                    logger.info(f"✅ Sent rate-limited alert for missing rules: {symbol}")
                except Exception as telegram_err:
                    logger.warning(f"Failed to send missing rules alert: {telegram_err}")
            
            # Mark position as UNPROTECTED_RULES_MISSING (persist to DB if needed)
            # Note: This status would need to be added to the position model if persistence is required
            logger.warning(f"⚠️ Position {symbol} marked as UNPROTECTED_RULES_MISSING")
        else:
            # Fetch all instrument rules
            min_qty_str = inst_meta.get("min_quantity", "0.001")
            step_size_str = inst_meta.get("qty_tick_size", "0.001")
            min_notional_str = inst_meta.get("min_notional", "0")
            quantity_decimals = inst_meta.get("quantity_decimals", 8)
            
            # Normalize quantity to get actual normalized value
            normalized_qty_str = trade_client.normalize_quantity(symbol, quantity)
            
            # Calculate rounded_qty (what we'd use if normalization succeeded)
            rounded_qty = "?"
            if normalized_qty_str:
                rounded_qty = normalized_qty_str
            else:
                # Calculate what the rounded value would be (even if below min)
                try:
                    qty_decimal = decimal.Decimal(str(quantity))
                    step_decimal = decimal.Decimal(str(step_size_str))
                    if step_decimal > 0:
                        division_result = qty_decimal / step_decimal
                        floored_result = division_result.quantize(decimal.Decimal('1'), rounding=decimal.ROUND_FLOOR)
                        rounded_qty_decimal = floored_result * step_decimal
                        rounded_qty = format(rounded_qty_decimal, f'.{quantity_decimals}f')
                except Exception as e:
                    logger.debug(f"Could not calculate rounded_qty: {e}")
            
            # Log structured [SLTP_NORMALIZE] with all numeric values
            ok_status = "true" if normalized_qty_str else "false"
            reason = "success" if normalized_qty_str else "below_min_qty"
            logger.info(
                f"[SLTP_NORMALIZE] symbol={symbol} raw_qty={quantity} min_qty={min_qty_str} "
                f"step={step_size_str} min_notional={min_notional_str} normalized_qty={normalized_qty_str or 'None'} "
                f"rounded_qty={rounded_qty} ok={ok_status} reason={reason}"
            )

        sl_order = trade_client.place_stop_loss_order(
            symbol=symbol,
            side=sl_side,
            price=sl_price,
            qty=quantity,
            trigger_price=sl_trigger,  # trigger_price = sl_price
            entry_price=entry_price,  # REQUIRED: Use entry price for ref_price
            is_margin=is_margin,
            leverage=leverage,
            dry_run=dry_run,
            source=source  # Propagate source to HTTP logging
        )

        if "error" in sl_order and error_is_invalid_trigger_price(sl_order.get("error")):
            retry_last = fetch_last_price(symbol) or last_price
            if retry_last and retry_last > 0:
                pct = derive_sl_percentage(
                    entry_side, entry_price, sl_price, sl_percentage
                )
                retry_price = compute_market_relative_sl(entry_side, retry_last, pct)
                logger.warning(
                    "[%s_SL] INVALID_TRIGGER_PRICE for %s @ %s — retrying once @ %s "
                    "(last=%s pct=%s)",
                    source.upper(),
                    symbol,
                    sl_price,
                    retry_price,
                    retry_last,
                    pct,
                )
                sl_price = retry_price
                sl_trigger = retry_price
                sl_order = trade_client.place_stop_loss_order(
                    symbol=symbol,
                    side=sl_side,
                    price=sl_price,
                    qty=quantity,
                    trigger_price=sl_trigger,
                    entry_price=entry_price,
                    is_margin=is_margin,
                    leverage=leverage,
                    dry_run=dry_run,
                    source=source,
                )
        
        if "error" not in sl_order:
            sl_order_id = sl_order.get("order_id") or sl_order.get("client_order_id")
            logger.info(f"✅ Created SL order for {symbol} @ {sl_price}")

            # Save SL order to database with OCO fields (same as automatic creation)
            if sl_order_id and parent_order_id:
                try:
                    sl_db_order = ExchangeOrder(
                        exchange_order_id=str(sl_order_id),
                        symbol=symbol,
                        side=OrderSideEnum.SELL if entry_side == "BUY" else OrderSideEnum.BUY,
                        order_type="STOP_LIMIT",  # Match API order type (STOP_LIMIT, not STOP_LOSS_LIMIT)
                        status=OrderStatusEnum.NEW,
                        price=sl_price,
                        quantity=quantity,
                        parent_order_id=parent_order_id,
                        oco_group_id=oco_group_id,
                        order_role="STOP_LOSS",
                        exchange_create_time=datetime.utcnow()
                    )
                    db.add(sl_db_order)
                    db.commit()
                    logger.info(f"✅ Saved SL order to DB with OCO group: {oco_group_id}")
                except Exception as db_err:
                    logger.warning(f"Failed to save SL order to database: {db_err}")
                    db.rollback()
            
            return {"order_id": sl_order_id, "error": None}
        else:
            sl_order_error = sl_order.get("error", "Unknown error")
            logger.error(f"❌ Failed to create SL order for {symbol} @ {sl_price}: {sl_order_error}")

            # Check if this is a small position that cannot be protected
            if "quantity_below_min" in sl_order_error or "below min_quantity" in sl_order_error:
                logger.warning(f"⚠️ Small position detected for {symbol}: quantity {quantity} cannot be protected")

                # Persist to Monitoring; suppress live Telegram (expected dust / below-min qty).
                try:
                    from app.services.trade_block_telegram_policy import (
                        suppress_small_position_unprotected_telegram,
                    )
                    from app.api.routes_monitoring import add_telegram_message

                    # Fetch instrument rules (should already be fetched above, but fetch again for safety)
                    inst_meta = trade_client._get_instrument_metadata(symbol)
                    if not inst_meta:
                        logger.warning(f"⚠️ Cannot calculate top-up for {symbol}: instrument rules unavailable")
                        alert_body = (
                            f"⚠️ <b>SMALL POSITION UNPROTECTED</b>\n\n"
                            f"Symbol: {symbol}\n"
                            f"Executed Qty: {quantity}\n\n"
                            f"Position cannot be protected with SL/TP.\n"
                            f"Instrument rules unavailable."
                        )
                    else:
                        min_qty_str = inst_meta.get("min_quantity", "0.001")
                        step_size_str = inst_meta.get("qty_tick_size", "0.001")
                        min_qty = float(min_qty_str)
                        step_size = float(step_size_str)
                        
                        # PART C: Fix top-up suggestion math
                        # target_qty = min_qty
                        # topup_qty = target_qty - normalized_qty
                        # Round topup_qty UP to step size
                        normalized_qty = float(trade_client.normalize_quantity(symbol, quantity) or 0)
                        if normalized_qty == 0:
                            # If normalization failed, use raw quantity
                            normalized_qty = quantity
                        
                        target_qty = min_qty
                        topup_qty_raw = target_qty - normalized_qty
                        
                        # Round topup_qty UP to step size
                        if step_size > 0:
                            topup_qty_decimal = decimal.Decimal(str(topup_qty_raw))
                            step_decimal = decimal.Decimal(str(step_size))
                            division_result = topup_qty_decimal / step_decimal
                            # Round UP (ceiling)
                            ceiled_result = division_result.quantize(decimal.Decimal('1'), rounding=decimal.ROUND_CEILING)
                            topup_qty_rounded = float(ceiled_result * step_decimal)
                        else:
                            topup_qty_rounded = topup_qty_raw
                        
                        # Ensure topup_qty_rounded is positive and results in >= min_qty after adding
                        if topup_qty_rounded < 0:
                            topup_qty_rounded = step_size  # At least one step
                        
                        # Verify: normalized_qty + topup_qty_rounded >= min_qty
                        final_qty = normalized_qty + topup_qty_rounded
                        if final_qty < min_qty:
                            # Adjust to ensure we meet min_qty
                            topup_qty_rounded = min_qty - normalized_qty
                            if step_size > 0:
                                # Round up again
                                topup_qty_decimal = decimal.Decimal(str(topup_qty_rounded))
                                step_decimal = decimal.Decimal(str(step_size))
                                division_result = topup_qty_decimal / step_decimal
                                ceiled_result = division_result.quantize(decimal.Decimal('1'), rounding=decimal.ROUND_CEILING)
                                topup_qty_rounded = float(ceiled_result * step_decimal)
                        
                        # Get last price for USD notional calculation
                        last_price = sl_price  # Use SL price as approximation, or fetch ticker
                        try:
                            ticker_url = "https://api.crypto.com/v2/public/get-ticker"
                            ticker_params = {"instrument_name": symbol}
                            ticker_response = http_get(ticker_url, params=ticker_params, timeout=5, calling_module="tp_sl_order_creator")
                            if ticker_response.status_code == 200:
                                ticker_data = ticker_response.json()
                                result_data = ticker_data.get("result", {})
                                if "data" in result_data and len(result_data["data"]) > 0:
                                    ticker_data_item = result_data["data"][0]
                                    last_price = float(ticker_data_item.get("a", sl_price))  # Use ask price
                        except Exception as price_err:
                            logger.debug(f"Could not fetch ticker price for {symbol}, using SL price: {price_err}")
                        
                        # Calculate estimated USD notional
                        estimated_usd_notional = topup_qty_rounded * last_price
                        
                        alert_body = (
                            f"⚠️ <b>SMALL POSITION UNPROTECTED</b>\n\n"
                            f"Symbol: {symbol}\n"
                            f"Executed Qty: {quantity:.8f}\n"
                            f"Normalized Qty: {normalized_qty:.8f}\n"
                            f"Min Qty Required: {min_qty:.8f}\n"
                            f"Step Size: {step_size:.8f}\n\n"
                            f"💡 <b>Suggested Top-up:</b>\n"
                            f"Quantity: {topup_qty_rounded:.8f}\n"
                            f"Estimated USD: ${estimated_usd_notional:.2f} (@ ${last_price:.4f})\n\n"
                            f"Position cannot be protected with SL/TP.\n"
                            f"Consider manual top-up or accept risk."
                        )

                    # Always persist for Monitoring; never page Telegram for this expected case.
                    if suppress_small_position_unprotected_telegram(alert_body, sl_order_error):
                        add_telegram_message(
                            alert_body.replace("<b>", "").replace("</b>", ""),
                            symbol=symbol,
                            blocked=False,
                            sltp_failed=True,
                            error_message=sl_order_error,
                            throttle_status="SMALL_POSITION_UNPROTECTED",
                            throttle_reason="quantity_below_min",
                        )
                        logger.info(
                            "SMALL POSITION UNPROTECTED Telegram suppressed (Monitoring only): %s qty=%s",
                            symbol,
                            quantity,
                        )
                    else:
                        telegram_notifier.send_message(alert_body)
                        logger.info(f"✅ Sent alert for unprotected small position: {symbol}")
                except Exception as telegram_err:
                    logger.warning(f"Failed to send small position alert: {telegram_err}", exc_info=True)

            return {"order_id": None, "error": sl_order_error}
            
    except Exception as e:
        sl_order_error = str(e)
        logger.error(f"❌ Error creating SL order for {symbol}: {e}", exc_info=True)
        return {"order_id": None, "error": sl_order_error}

