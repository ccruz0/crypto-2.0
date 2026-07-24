"""Exchange synchronization service
Synchronizes data from Crypto.com Exchange API to the database every 5 seconds
"""
import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple, Union
from sqlalchemy.orm import Session
from sqlalchemy import and_, not_, text
from app.database import SessionLocal
from app.models.exchange_balance import ExchangeBalance
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.models.trade_signal import TradeSignal, SignalStatusEnum
from app.services.brokers.crypto_com_trade import CryptoComTradeClient, trade_client
from app.services.open_orders import merge_orders, UnifiedOpenOrder
from app.services.open_orders_cache import store_unified_open_orders, update_open_orders_cache
from app.services.sl_tp_protection import (
    GHOST_CANCEL_GRACE_SECONDS,
    get_active_protection_order,
    has_complete_sl_tp_protection,
    release_sl_tp_creation_lock,
    should_mark_unresolved_order_cancelled,
    try_acquire_sl_tp_creation_lock,
)
# fill_dedup_postgres may be absent in some deployments; run with fill dedup disabled if missing.
# EC2 verification after deploy: git reset --hard origin/main; rebuild backend image with --no-cache;
# docker exec <backend_container> python3 -c "import app.services.exchange_sync as m; print('OK')";
# confirm no "Worker failed to boot" or "ModuleNotFoundError" for fill_dedup_postgres in logs.
try:
    from app.services.fill_dedup_postgres import get_fill_dedup  # pyright: ignore[reportMissingImports]
    FILL_DEDUP_ENABLED = True
except ModuleNotFoundError as e:
    if "app.services.fill_dedup_postgres" not in str(e):
        raise
    FILL_DEDUP_ENABLED = False
    logger = logging.getLogger(__name__)
    logger.warning(
        "fill_dedup_postgres module not found; using SQLite fill_tracker fallback for fill deduplication."
    )

    from app.services.fill_tracker import get_fill_tracker

    class _FillTrackerDedupAdapter:
        """Adapter: fill_tracker SQLite persistence when fill_dedup_postgres is absent."""

        def __init__(self):
            self._tracker = get_fill_tracker()

        def should_notify_fill(
            self,
            order_id: str,
            current_filled_qty: Union[int, float, Decimal],
            status: str,
        ) -> tuple:
            return self._tracker.should_notify_fill(
                order_id=order_id,
                current_filled_qty=float(current_filled_qty),
                status=status,
            )

        def record_fill(
            self,
            order_id: str,
            filled_qty: Union[int, float, Decimal],
            status: str,
            notification_sent: bool = False,
        ) -> None:
            self._tracker.record_fill(
                order_id=order_id,
                filled_qty=float(filled_qty),
                status=status,
                notification_sent=notification_sent,
            )

    _fill_dedup_adapter: Optional["_FillTrackerDedupAdapter"] = None

    def get_fill_dedup(db: Session):  # noqa: ARG001
        global _fill_dedup_adapter
        if _fill_dedup_adapter is None:
            _fill_dedup_adapter = _FillTrackerDedupAdapter()
        return _fill_dedup_adapter

# build_strategy_key helper: throttle_service when present, else fallback (same pattern as signal_monitor).
try:
    from app.services.throttle_service import build_strategy_key as _build_strategy_key  # pyright: ignore[reportMissingImports]
except ModuleNotFoundError as e:
    if "app.services.throttle_service" not in str(e):
        raise
    def _build_strategy_key(*args: object, **kwargs: object) -> str:
        return "default:default"
build_strategy_key = _build_strategy_key

from app.utils.pipeline_logging import log_critical_failure, make_json_safe

logger = logging.getLogger(__name__)


def _to_decimal(x: Union[Decimal, int, float, str, None]) -> Decimal:
    """Convert to Decimal for quantity/money math. Avoids float+Decimal TypeError.
    - Decimal -> return as-is
    - int/float -> Decimal(str(x)) to avoid float precision issues
    - str -> strip commas, then Decimal
    - None -> Decimal('0')
    """
    if x is None:
        return Decimal("0")
    if isinstance(x, Decimal):
        return x
    if isinstance(x, (int, float)):
        return Decimal(str(x))
    if isinstance(x, str):
        cleaned = (x or "").strip().replace(",", "")
        if not cleaned:
            return Decimal("0")
        return Decimal(cleaned)
    return Decimal(str(x))


# 1 hour: only notify for fills within this window unless order was created by system or admin resync
RECENT_FILL_WINDOW_SECONDS = 3600
# OCO sibling cancel Telegram: never re-announce the same sibling within this TTL
OCO_CANCEL_TELEGRAM_TTL_MINUTES = 7 * 24 * 60

_PROTECTIVE_ORDER_TYPES = (
    "STOP_LIMIT",
    "STOP_LOSS",
    "STOP_LOSS_LIMIT",
    "TAKE_PROFIT",
    "TAKE_PROFIT_LIMIT",
)


def is_recent_exchange_event(
    order: ExchangeOrder,
    *,
    now_utc: Optional[datetime] = None,
    window_seconds: int = RECENT_FILL_WINDOW_SECONDS,
) -> bool:
    """True when exchange create/update time is within the recent window."""
    now = now_utc or datetime.now(timezone.utc)
    event_at = getattr(order, "exchange_update_time", None) or getattr(
        order, "exchange_create_time", None
    )
    if not event_at:
        return False
    if event_at.tzinfo is None:
        event_at = event_at.replace(tzinfo=timezone.utc)
    return (now - event_at).total_seconds() <= window_seconds


def should_notify_oco_sibling_cancel(
    filled_order: ExchangeOrder,
    *,
    now_utc: Optional[datetime] = None,
) -> tuple[bool, str]:
    """Gate OCO-cancel Telegram so history sync does not re-spam old TP/SL fills."""
    if is_recent_exchange_event(filled_order, now_utc=now_utc):
        return (True, "recent fill")
    return (False, "historical fill: outside window")


def should_notify_executed_fill(
    *,
    db: Session,
    order: ExchangeOrder,
    now_utc: datetime,
    source: str,
    requested_by_admin: bool,
) -> tuple[bool, str]:
    """Gate for executed-fill Telegram notifications. Prevents history-sync spam.
    Returns (allowed, reason).
    A) requested_by_admin -> allow (unless already notified, then dedup).
    B) Order created by this system (signal / parent / protection role / intent) -> allow.
    C) Else allow only if fill is recent (within RECENT_FILL_WINDOW_SECONDS).
    D) If we already sent notification for this order -> block.
    """
    if getattr(order, "execution_notified_at", None) is not None:
        return (False, "already notified")
    if requested_by_admin:
        return (True, "admin resync")
    role = (getattr(order, "order_role", None) or "").upper()
    order_type = (getattr(order, "order_type", None) or "").upper()
    is_protection = role in ("TAKE_PROFIT", "STOP_LOSS") or order_type in _PROTECTIVE_ORDER_TYPES
    is_system_order = (
        getattr(order, "trade_signal_id", None) is not None
        or getattr(order, "parent_order_id", None) is not None
        or is_protection
    )
    if is_system_order:
        return (True, "system order")
    filled_at = getattr(order, "exchange_update_time", None) or getattr(order, "exchange_create_time", None)
    if not filled_at:
        return (False, "historical fill: no timestamp")
    if filled_at.tzinfo is None:
        filled_at = filled_at.replace(tzinfo=timezone.utc)
    age_seconds = (now_utc - filled_at).total_seconds()
    if age_seconds > RECENT_FILL_WINDOW_SECONDS:
        return (False, "historical fill: outside window")
    return (True, "recent fill")


def _count_open_entry_buy_orders(db: Session, symbol: str) -> int:
    """Count open entry BUY orders for a symbol, excluding protective SL/TP.

    For SHORT positions, SL/TP are BUY-side STOP_LIMIT / TAKE_PROFIT_LIMIT.
    Counting every open BUY inflated the ORDER EXECUTED "Open Orders" warning
    (observed 2026-07-21: "Open Orders: 22" when most were protective).
    """
    from sqlalchemy import or_

    return (
        db.query(ExchangeOrder)
        .filter(
            ExchangeOrder.symbol == symbol,
            ExchangeOrder.side == OrderSideEnum.BUY,
            ExchangeOrder.status.in_(
                [
                    OrderStatusEnum.NEW,
                    OrderStatusEnum.ACTIVE,
                    OrderStatusEnum.PARTIALLY_FILLED,
                ]
            ),
            or_(
                ExchangeOrder.order_type.is_(None),
                ~ExchangeOrder.order_type.in_(_PROTECTIVE_ORDER_TYPES),
            ),
            or_(
                ExchangeOrder.order_role.is_(None),
                ~ExchangeOrder.order_role.in_(["STOP_LOSS", "TAKE_PROFIT"]),
            ),
        )
        .count()
    )


def link_system_trade_signal_to_order(db: Session, order: ExchangeOrder) -> bool:
    """Attach trade_signal_id to an ExchangeOrder when a TradeSignal references it."""
    order_id = str(order.exchange_order_id)
    if getattr(order, "trade_signal_id", None) is not None:
        logger.debug(
            "[SLTP_SYSTEM_LINK] order=%s (%s) already has trade_signal_id=%s",
            order_id,
            order.symbol,
            order.trade_signal_id,
        )
        return False

    signal = db.query(TradeSignal).filter(
        TradeSignal.exchange_order_id == order_id
    ).first()
    if not signal:
        logger.debug(
            "[SLTP_SYSTEM_LINK] No TradeSignal.exchange_order_id match for order=%s symbol=%s",
            order_id,
            order.symbol,
        )
        return False

    order.trade_signal_id = signal.id
    logger.info(
        "[SLTP_SYSTEM_LINK] Linked trade_signal_id=%s to order %s (%s)",
        signal.id,
        order_id,
        order.symbol,
    )
    return True


def is_system_created_order(db: Session, order: ExchangeOrder) -> bool:
    """True when the order was created by ATP (signal monitor / alerts), not manual exchange."""
    order_id = str(order.exchange_order_id)
    trade_signal_id = getattr(order, "trade_signal_id", None)
    if trade_signal_id is not None:
        logger.debug(
            "[SLTP_SYSTEM_CHECK] order=%s symbol=%s is_system=True reason=trade_signal_id=%s",
            order_id,
            order.symbol,
            trade_signal_id,
        )
        return True
    if getattr(order, "parent_order_id", None) is not None:
        logger.debug(
            "[SLTP_SYSTEM_CHECK] order=%s symbol=%s is_system=True reason=parent_order_id",
            order_id,
            order.symbol,
        )
        return True

    signal_match = (
        db.query(TradeSignal.id)
        .filter(TradeSignal.exchange_order_id == order_id)
        .first()
    )
    if signal_match is not None:
        logger.debug(
            "[SLTP_SYSTEM_CHECK] order=%s symbol=%s is_system=True reason=trade_signal_exchange_order_id",
            order_id,
            order.symbol,
        )
        return True

    from app.models.order_intent import OrderIntent

    intent_match = (
        db.query(OrderIntent.id)
        .filter(OrderIntent.order_id == order_id)
        .first()
    )
    if intent_match is not None:
        logger.debug(
            "[SLTP_SYSTEM_CHECK] order=%s symbol=%s is_system=True reason=order_intent",
            order_id,
            order.symbol,
        )
        return True

    logger.info(
        "[SLTP_SYSTEM_CHECK] order=%s symbol=%s is_system=False "
        "(no trade_signal_id, TradeSignal row, or OrderIntent)",
        order_id,
        order.symbol,
    )
    return False


def should_auto_create_sl_tp_on_sync(
    db: Session,
    order: ExchangeOrder,
    order_filled_time: Optional[datetime],
    now_utc: datetime,
) -> Tuple[bool, str]:
    """Gate SL/TP backfill during exchange_sync history processing."""
    linked = link_system_trade_signal_to_order(db, order)

    parent_id = str(order.exchange_order_id)
    if has_complete_sl_tp_protection(db, parent_id):
        return False, "already_protected"

    is_system = is_system_created_order(db, order)
    logger.info(
        "[SLTP_SYSTEM_GATE] order=%s symbol=%s linked=%s is_system=%s filled_time=%s",
        parent_id,
        order.symbol,
        linked,
        is_system,
        order_filled_time,
    )

    if is_system:
        return True, "system_order_needs_protection"

    if not order_filled_time:
        return False, "external_order_no_timestamp"

    has_sl = get_active_protection_order(db, parent_id, "STOP_LOSS") is not None
    has_tp = get_active_protection_order(db, parent_id, "TAKE_PROFIT") is not None
    if has_sl ^ has_tp:
        return True, "half_protected_backfill"

    filled_at = order_filled_time
    if filled_at.tzinfo is None:
        filled_at = filled_at.replace(tzinfo=timezone.utc)
    elif filled_at.tzinfo != timezone.utc:
        filled_at = filled_at.astimezone(timezone.utc)

    time_since_filled = (now_utc - filled_at).total_seconds() / 3600
    if time_since_filled > 1.0:
        return (
            False,
            f"external_order_old_fill_{time_since_filled:.2f}h",
        )
    return True, "recent_external_fill"


def filter_sync_cancel_orders_for_telegram(
    db: Optional[Session],
    cancelled_orders: List[ExchangeOrder],
) -> List[ExchangeOrder]:
    """
    Drop routine SL/TP sync-cancel noise and dedupe entry cancels for Telegram.

    Protection legs (STOP_LOSS / TAKE_PROFIT) are logged by sync but must not page
    ATP Control — they churn during OCO / ghost cleanup. Entry cancels notify once
    per order id (7d claim).
    """
    from app.services.telegram_event_dedup import claim_telegram_event

    notify_orders: List[ExchangeOrder] = []
    for order in cancelled_orders:
        role = (order.order_role or "").upper()
        oid = str(order.exchange_order_id or "")
        if role in ("STOP_LOSS", "TAKE_PROFIT"):
            logger.info(
                "📢 Skipping Telegram for sync-cancelled protection leg %s (%s role=%s)",
                oid,
                order.symbol,
                role,
            )
            continue
        if not oid:
            continue
        if not claim_telegram_event(
            db,
            f"sync_cancel:{oid}",
            symbol=order.symbol,
            ttl_minutes=7 * 24 * 60,
            action="sync_cancel",
        ):
            logger.info(
                "📢 Skipping duplicate sync-cancel Telegram for order %s (%s)",
                oid,
                order.symbol,
            )
            continue
        notify_orders.append(order)
    return notify_orders


def sl_tp_creation_result_ok(result: Optional[dict]) -> bool:
    """True when SL/TP creation produced (or already had) both protection legs."""
    if not isinstance(result, dict):
        return False
    status = str(result.get("status") or "").strip().lower()
    if status == "already_protected":
        return True
    sl = result.get("sl_result") or {}
    tp = result.get("tp_result") or {}
    sl_ok = bool(sl.get("order_id")) and not sl.get("error")
    tp_ok = bool(tp.get("order_id")) and not tp.get("error")
    return sl_ok and tp_ok


# Crypto.com open-order statuses mapped to internal OrderStatusEnum.
# PENDING/UNTRIGGERED are trigger-order states that must count as open (not UNKNOWN).
_EXCHANGE_OPEN_STATUS_MAP: dict[str, OrderStatusEnum] = {
    "NEW": OrderStatusEnum.NEW,
    "ACTIVE": OrderStatusEnum.ACTIVE,
    "PENDING": OrderStatusEnum.ACTIVE,
    "UNTRIGGERED": OrderStatusEnum.ACTIVE,
    "OPEN": OrderStatusEnum.ACTIVE,
    "PARTIALLY_FILLED": OrderStatusEnum.PARTIALLY_FILLED,
    "FILLED": OrderStatusEnum.FILLED,
    "CANCELLED": OrderStatusEnum.CANCELLED,
    "CANCELED": OrderStatusEnum.CANCELLED,
    "REJECTED": OrderStatusEnum.REJECTED,
    "EXPIRED": OrderStatusEnum.EXPIRED,
    "EXECUTED": OrderStatusEnum.FILLED,
    "COMPLETE": OrderStatusEnum.FILLED,
    "CLOSED": OrderStatusEnum.FILLED,
}


def map_exchange_order_status(
    status_str: str | None,
    *,
    cumulative_quantity: float | int = 0,
    quantity: float | int = 0,
) -> OrderStatusEnum:
    """Map a Crypto.com order status string to OrderStatusEnum."""
    status_str_upper = (status_str or "").strip().upper()
    mapped = _EXCHANGE_OPEN_STATUS_MAP.get(status_str_upper, OrderStatusEnum.UNKNOWN)

    if status_str_upper in {"CANCELLED", "CANCELED"} and cumulative_quantity > 0:
        if cumulative_quantity >= quantity:
            return OrderStatusEnum.FILLED
        return OrderStatusEnum.PARTIALLY_FILLED

    return mapped


# Symbols always synced each background cycle (covers pairs traded outside watchlist, e.g. BTC_USD).
REQUIRED_ORDER_HISTORY_SYMBOLS: Tuple[str, ...] = ("BTC_USD", "BTC_USDT", "ETH_USDT")
DEFAULT_ORDER_HISTORY_SYMBOLS: Tuple[str, ...] = (
    "BTC_USD",
    "BTC_USDT",
    "ETH_USDT",
    "BCH_USDT",
    "ATOM_USDT",
)
ORDER_HISTORY_RECENT_LOOKBACK_DAYS = int(os.environ.get("ORDER_HISTORY_RECENT_LOOKBACK_DAYS", "30"))
ORDER_HISTORY_RECENT_WINDOW_DAYS = int(os.environ.get("ORDER_HISTORY_RECENT_WINDOW_DAYS", "14"))
ORDER_HISTORY_DEEP_LOOKBACK_DAYS = int(os.environ.get("ORDER_HISTORY_DEEP_LOOKBACK_DAYS", "180"))
ORDER_HISTORY_DEEP_WINDOW_DAYS = int(os.environ.get("ORDER_HISTORY_DEEP_WINDOW_DAYS", "7"))
ORDER_HISTORY_EMPTY_WINDOWS_STOP = int(os.environ.get("ORDER_HISTORY_EMPTY_WINDOWS_STOP", "3"))
ORDER_HISTORY_PRIORITY_MAX = int(os.environ.get("ORDER_HISTORY_PRIORITY_MAX", "8"))
ORDER_HISTORY_SYNC_MAX_SYMBOLS_PER_RUN = int(os.environ.get("ORDER_HISTORY_SYNC_MAX_SYMBOLS_PER_RUN", "3"))

_RESOLVED_STATUS_ALIASES = {
    "EXECUTED": "FILLED",
    "COMPLETE": "FILLED",
    "CLOSED": "FILLED",
    "CANCELED": "CANCELLED",
}


def quote_instrument_variants(symbol: Optional[str]) -> List[str]:
    """Return symbol plus USD/USDT twin so BTC_USD fills are not missed when only BTC_USDT is listed."""
    if not symbol:
        return []
    key = str(symbol).strip().upper()
    if not key:
        return []
    variants = [key]
    if key.endswith("_USDT"):
        variants.append(f"{key[:-5]}_USD")
    elif key.endswith("_USD"):
        variants.append(f"{key[:-4]}_USDT")
    seen: set[str] = set()
    out: List[str] = []
    for item in variants:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def expand_symbols_with_quote_variants(symbols: List[str]) -> List[str]:
    """Deduped expansion of a symbol list with USD/USDT twins, preserving first-seen order."""
    seen: set[str] = set()
    out: List[str] = []
    for sym in symbols:
        for variant in quote_instrument_variants(sym):
            if variant not in seen:
                seen.add(variant)
                out.append(variant)
    return out


def normalize_resolved_exchange_status(status_str: Optional[str]) -> str:
    """Normalize exchange status strings to our OrderStatusEnum names."""
    raw = (status_str or "").strip().upper()
    return _RESOLVED_STATUS_ALIASES.get(raw, raw)


def parse_resolved_order_payload(order_data: Optional[Dict[str, Any]], order_id: str) -> Optional[Dict[str, Any]]:
    """Extract status/qty/price from get-order-detail or history row payloads."""
    if not isinstance(order_data, dict):
        return None
    oid = order_data.get("order_id") or order_data.get("orderId") or order_data.get("id")
    if oid is not None and str(oid) != str(order_id):
        return None
    status_str = normalize_resolved_exchange_status(str(order_data.get("status", "") or ""))
    if not status_str:
        return None
    cumulative_qty = float(order_data.get("cumulative_quantity", 0) or 0)
    quantity = float(order_data.get("quantity", 0) or 0)
    # Crypto.com often returns CANCELLED/CANCELED for fully filled advanced TP/SL legs;
    # prefer fill evidence over the raw cancel label.
    mapped = map_exchange_order_status(
        status_str,
        cumulative_quantity=cumulative_qty,
        quantity=quantity,
    )
    if mapped in (OrderStatusEnum.FILLED, OrderStatusEnum.PARTIALLY_FILLED):
        status_str = mapped.value
    price = order_data.get("avg_price") or order_data.get("limit_price") or order_data.get("price")
    payload: Dict[str, Any] = {
        "status": status_str,
        "cumulative_quantity": cumulative_qty,
        "price": float(price) if price not in (None, "") else None,
        "quantity": quantity,
    }
    reject_reason = order_data.get("reject_reason")
    if reject_reason:
        payload["reject_reason"] = reject_reason
    contingency = order_data.get("contingency_type") or order_data.get("contingencyType")
    if contingency:
        payload["contingency_type"] = str(contingency).upper()
    child_exchange_id = order_data.get("exchange_order_id")
    if child_exchange_id not in (None, "", "0", 0):
        payload["child_exchange_order_id"] = str(child_exchange_id)
    return payload


def protection_role_from_order_data(order_data: Optional[Dict[str, Any]]) -> Optional[str]:
    """Infer TAKE_PROFIT / STOP_LOSS from advanced contingency or trigger order_type."""
    if not isinstance(order_data, dict):
        return None
    contingency = str(
        order_data.get("contingency_type") or order_data.get("contingencyType") or ""
    ).upper()
    if contingency in ("TAKE_PROFIT", "STOP_LOSS"):
        return contingency
    order_type = str(order_data.get("order_type") or order_data.get("type") or "").upper()
    if order_type in ("TAKE_PROFIT", "TAKE_PROFIT_LIMIT", "TAKE_PROFIT_MARKET"):
        return "TAKE_PROFIT"
    if order_type in ("STOP_LOSS", "STOP_LIMIT", "STOP_MARKET", "STOP_LOSS_LIMIT"):
        return "STOP_LOSS"
    return None


def _protection_order_price(order: ExchangeOrder) -> Optional[float]:
    """Best-effort limit/trigger price from a persisted SL/TP order row."""
    for attr in ("price", "trigger_condition"):
        val = getattr(order, attr, None)
        if val is None:
            continue
        try:
            parsed = float(val)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return None


class ExchangeSyncService:
    """Service to sync exchange data with database"""
    
    def __init__(self):
        self.is_running = False
        self.sync_interval = 5  # seconds between background (balances + order history) cycles
        self.open_orders_sync_interval = 5  # seconds between open-orders refresh cycles
        self.startup_open_orders_delay = 2  # seconds before first open-orders refresh on startup
        self.background_sync_startup_delay = 15  # seconds before first balances/order-history cycle
        self.order_history_timeout = int(os.environ.get("ORDER_HISTORY_SYNC_TIMEOUT_SEC", "300"))
        self.last_sync: Optional[datetime] = None
        self.last_open_orders_sync: Optional[datetime] = None
        self.processed_order_ids: Dict[str, float] = {}  # Track already processed executed orders {order_id: timestamp}
        self.latest_unified_open_orders: List[UnifiedOpenOrder] = []
        # Advanced detail confirmed these CANCELLED/REJECTED protection rows are not fills;
        # skip re-polling them every open-orders cycle (process-lifetime).
        self._protection_reconcile_exhausted: set[str] = set()
    
    def _purge_stale_processed_orders(self):
        """Remove processed order IDs older than 10 minutes"""
        current_time = time.time()
        stale_threshold = 600  # 10 minutes in seconds
        
        stale_ids = [
            order_id for order_id, timestamp in self.processed_order_ids.items()
            if (current_time - timestamp) > stale_threshold
        ]
        
        for order_id in stale_ids:
            del self.processed_order_ids[order_id]
        
        if stale_ids:
            logger.debug(f"Purged {len(stale_ids)} stale processed order IDs")
    
    def _resolve_order_status_from_exchange(
        self,
        order_id: str,
        order_created_at: Optional[datetime] = None,
        instrument_name: Optional[str] = None,
    ) -> Optional[Dict]:
        """
        Resolve order status from exchange.

        Prefer get-order-detail (exact order_id). Fall back to per-instrument order
        history — Crypto.com often returns empty without instrument_name — then
        advanced/trigger history.

        For TP/SL protection rows, try advanced detail first: spot get-order-detail
        returns empty or misleading CANCELLED for Advanced Order Management ids.
        """
        try:
            prefer_advanced = False
            # Prefer explicit symbol; otherwise recover from DB so history queries can filter.
            try:
                db = SessionLocal()
                try:
                    row = (
                        db.query(ExchangeOrder)
                        .filter(ExchangeOrder.exchange_order_id == str(order_id))
                        .first()
                    )
                    if row:
                        if not instrument_name and row.symbol:
                            instrument_name = row.symbol
                        role = (getattr(row, "order_role", None) or "").upper()
                        otype = (getattr(row, "order_type", None) or "").upper()
                        prefer_advanced = role in ("TAKE_PROFIT", "STOP_LOSS") or otype in _PROTECTIVE_ORDER_TYPES
                finally:
                    db.close()
            except Exception:
                pass

            def _try_spot_detail() -> Optional[Dict[str, Any]]:
                try:
                    detail = trade_client.get_order_detail(str(order_id))
                    result = detail.get("result") if isinstance(detail, dict) else None
                    parsed = parse_resolved_order_payload(
                        result if isinstance(result, dict) else None,
                        str(order_id),
                    )
                    if parsed:
                        logger.info(
                            "Found order %s via get-order-detail: status=%s cumulative_qty=%s",
                            order_id,
                            parsed["status"],
                            parsed["cumulative_quantity"],
                        )
                        return parsed
                except Exception as detail_err:
                    logger.debug("get-order-detail failed for %s: %s", order_id, detail_err)
                return None

            def _try_advanced_detail() -> Optional[Dict[str, Any]]:
                try:
                    adv_detail_fn = getattr(trade_client, "get_advanced_order_detail", None)
                    if not callable(adv_detail_fn):
                        return None
                    adv_detail = adv_detail_fn(str(order_id))
                    adv_result = adv_detail.get("result") if isinstance(adv_detail, dict) else None
                    parsed = parse_resolved_order_payload(
                        adv_result if isinstance(adv_result, dict) else None,
                        str(order_id),
                    )
                    if parsed:
                        logger.info(
                            "Found order %s via advanced/get-order-detail: status=%s cumulative_qty=%s",
                            order_id,
                            parsed["status"],
                            parsed["cumulative_quantity"],
                        )
                        return parsed
                except Exception as adv_detail_err:
                    logger.debug("advanced get-order-detail failed for %s: %s", order_id, adv_detail_err)
                return None

            # 1) Exact order detail — advanced first for protection, else spot then advanced
            if prefer_advanced:
                parsed = _try_advanced_detail()
                if parsed:
                    return parsed
                parsed = _try_spot_detail()
                if parsed:
                    return parsed
            else:
                parsed = _try_spot_detail()
                if parsed:
                    return parsed
                parsed = _try_advanced_detail()
                if parsed:
                    return parsed

            end_time_ms = int(time.time() * 1000)
            if order_created_at:
                start_time = order_created_at - timedelta(hours=1)
                start_time_ms = int(start_time.timestamp() * 1000)
            else:
                start_time_ms = int((datetime.now(timezone.utc) - timedelta(hours=24)).timestamp() * 1000)

            # 2) Per-instrument history (USD/USDT twins), then unscoped as last history attempt
            instruments_to_try = quote_instrument_variants(instrument_name) + [None]
            seen_instruments: set[str] = set()
            for instrument in instruments_to_try:
                key = instrument or "__ALL__"
                if key in seen_instruments:
                    continue
                seen_instruments.add(key)
                try:
                    kwargs: Dict[str, Any] = {
                        "page_size": 200,
                        "page": 0,
                        "start_time": start_time_ms,
                        "end_time": end_time_ms,
                    }
                    if instrument:
                        kwargs["instrument_name"] = instrument
                    response = trade_client.get_order_history(**kwargs)
                except Exception as hist_err:
                    logger.debug(
                        "Order history query failed for %s instrument=%s: %s",
                        order_id,
                        instrument,
                        hist_err,
                    )
                    continue

                if not response or "data" not in response:
                    continue

                for order_data in response.get("data", []) or []:
                    parsed = parse_resolved_order_payload(
                        order_data if isinstance(order_data, dict) else None,
                        str(order_id),
                    )
                    if parsed:
                        logger.info(
                            "Found order %s in exchange history (instrument=%s): status=%s cumulative_qty=%s",
                            order_id,
                            instrument or "ALL",
                            parsed["status"],
                            parsed["cumulative_quantity"],
                        )
                        return parsed

            logger.debug(
                "Order %s not found in spot order history; trying advanced/trigger history",
                order_id,
            )
            advanced_info = self._resolve_advanced_order_status_from_exchange(
                order_id, order_created_at
            )
            if advanced_info:
                advanced_info["status"] = normalize_resolved_exchange_status(
                    advanced_info.get("status")
                )
                return advanced_info
            return None

        except Exception as e:
            logger.warning(
                f"Error resolving order status from exchange for {order_id}: {e}",
                exc_info=True,
            )
            return None

    def _resolve_advanced_order_status_from_exchange(
        self, order_id: str, order_created_at: Optional[datetime] = None
    ) -> Optional[Dict]:
        """Resolve conditional/advanced order status (includes REJECTED + reject_reason).

        Crypto.com advanced history returns empty for wide time ranges (often >~48h),
        so we query narrow 24h windows around create_time instead of create→now.
        """
        try:
            from datetime import timedelta

            instrument_name = None
            try:
                from app.database import SessionLocal
                from app.models.exchange_order import ExchangeOrder

                db = SessionLocal()
                try:
                    row = db.query(ExchangeOrder).filter(ExchangeOrder.exchange_order_id == order_id).first()
                    if row:
                        instrument_name = row.symbol
                finally:
                    db.close()
            except Exception:
                instrument_name = None

            # Prefer exact advanced detail when available (no window-size trap).
            try:
                adv_detail_fn = getattr(trade_client, "get_advanced_order_detail", None)
                if callable(adv_detail_fn):
                    adv_detail = adv_detail_fn(str(order_id))
                    adv_result = adv_detail.get("result") if isinstance(adv_detail, dict) else None
                    parsed = parse_resolved_order_payload(
                        adv_result if isinstance(adv_result, dict) else None,
                        str(order_id),
                    )
                    if parsed:
                        logger.info(
                            "Found advanced order %s via get-order-detail: status=%s cumulative_qty=%s",
                            order_id,
                            parsed["status"],
                            parsed["cumulative_quantity"],
                        )
                        return parsed
            except Exception as adv_detail_err:
                logger.debug("advanced get-order-detail failed for %s: %s", order_id, adv_detail_err)

            # Narrow windows: Crypto.com advanced history goes empty on multi-day spans.
            window_ms = 24 * 60 * 60 * 1000
            max_windows = 14
            if order_created_at:
                anchor_ms = int(order_created_at.timestamp() * 1000)
            else:
                anchor_ms = int((datetime.now(timezone.utc) - timedelta(hours=12)).timestamp() * 1000)
            now_ms = int(time.time() * 1000)

            instruments = quote_instrument_variants(instrument_name) or [None]
            for instrument in instruments:
                for i in range(max_windows):
                    window_start = anchor_ms - (60 * 60 * 1000) + (i * window_ms)
                    window_end = min(now_ms, window_start + window_ms)
                    if window_start >= now_ms:
                        break
                    query_params: Dict[str, Any] = {
                        "limit": 200,
                        "start_time": window_start,
                        "end_time": window_end,
                    }
                    if instrument:
                        query_params["instrument_name"] = instrument
                    response = trade_client.get_advanced_order_history(**query_params)
                    if not response or "data" not in response:
                        continue
                    for order_data in response.get("data", []) or []:
                        parsed = parse_resolved_order_payload(
                            order_data if isinstance(order_data, dict) else None,
                            str(order_id),
                        )
                        if parsed:
                            if order_data.get("reject_reason"):
                                parsed["reject_reason"] = order_data.get("reject_reason")
                            logger.info(
                                "Found advanced order %s in history: status=%s reject_reason=%s instrument=%s window=%s..%s",
                                order_id,
                                parsed["status"],
                                parsed.get("reject_reason"),
                                instrument,
                                window_start,
                                window_end,
                            )
                            return parsed
            return None
        except Exception as e:
            logger.debug("Advanced order history lookup failed for %s: %s", order_id, e)
            return None
    
    def _upsert_protection_child_spot_fill(
        self,
        db: Session,
        parent: ExchangeOrder,
        order_info: Dict[str, Any],
    ) -> Optional[str]:
        """Persist the spot child fill id from advanced TP/SL detail (exchange_order_id).

        Crypto.com Advanced Order Management keeps the contingency parent (73817…) and
        creates a separate spot child (57556…) when the TP/SL triggers. Without upserting
        the child, Executed Orders / history miss the real fill and later spot sync can
        emit a second unlabeled ORDER EXECUTED.
        """
        child_id = order_info.get("child_exchange_order_id")
        if child_id in (None, "", "0", 0):
            return None
        child_id = str(child_id)
        if child_id == str(parent.exchange_order_id):
            return None

        role = self._infer_protection_order_role(parent) or parent.order_role
        cum = float(order_info.get("cumulative_quantity") or parent.cumulative_quantity or 0)
        price = order_info.get("price")
        if price is None:
            price = float(parent.avg_price or parent.price or 0) or None
        now = datetime.now(timezone.utc)

        existing = (
            db.query(ExchangeOrder)
            .filter(ExchangeOrder.exchange_order_id == child_id)
            .first()
        )
        if existing:
            existing.status = OrderStatusEnum.FILLED
            if cum > 0:
                existing.cumulative_quantity = cum
            if price:
                existing.avg_price = float(price)
            if role and not existing.order_role:
                existing.order_role = role
            if parent.parent_order_id and not existing.parent_order_id:
                existing.parent_order_id = parent.parent_order_id
            # Suppress duplicate Telegram if spot history later rediscovers this child.
            if existing.execution_notified_at is None and parent.execution_notified_at is not None:
                existing.execution_notified_at = parent.execution_notified_at
            elif existing.execution_notified_at is None:
                existing.execution_notified_at = now
            existing.exchange_update_time = now
            logger.info(
                "Upserted protection child fill %s (parent=%s role=%s) status=FILLED",
                child_id,
                parent.exchange_order_id,
                role,
            )
            return child_id

        side = parent.side if isinstance(parent.side, OrderSideEnum) else (
            OrderSideEnum.SELL if str(getattr(parent.side, "value", parent.side) or "").upper() == "SELL"
            else OrderSideEnum.BUY
        )
        child = ExchangeOrder(
            exchange_order_id=child_id,
            symbol=parent.symbol,
            side=side,
            order_type=parent.order_type or "LIMIT",
            status=OrderStatusEnum.FILLED,
            price=float(price) if price else (float(parent.price) if parent.price else None),
            quantity=float(parent.quantity or cum or 0),
            cumulative_quantity=cum if cum > 0 else float(parent.quantity or 0),
            avg_price=float(price) if price else None,
            order_role=role,
            parent_order_id=parent.parent_order_id or str(parent.exchange_order_id),
            exchange_create_time=parent.exchange_create_time or parent.created_at,
            exchange_update_time=now,
            # Parent already owns the Telegram ORDER EXECUTED for this fill.
            execution_notified_at=parent.execution_notified_at or now,
        )
        db.add(child)
        logger.info(
            "Inserted protection child fill %s (parent=%s role=%s symbol=%s)",
            child_id,
            parent.exchange_order_id,
            role,
            parent.symbol,
        )
        return child_id

    def _apply_protection_fill_from_resolve(
        self,
        db: Session,
        order: ExchangeOrder,
        order_info: Dict[str, Any],
        *,
        source: str,
    ) -> bool:
        """Mark a protection order FILLED from resolved exchange payload; notify Telegram.

        Returns True when status changed to FILLED.
        """
        resolved_status = normalize_resolved_exchange_status(order_info.get("status"))
        if resolved_status != "FILLED":
            return False
        cum = float(order_info.get("cumulative_quantity") or 0)
        if cum <= 0:
            return False

        old_status = order.status
        order.status = OrderStatusEnum.FILLED
        order.cumulative_quantity = cum
        if order_info.get("price"):
            order.avg_price = order_info["price"]

        if old_status != OrderStatusEnum.FILLED:
            try:
                self._maybe_notify_executed_fill_telegram(
                    db,
                    order,
                    source=source,
                    price=order_info.get("price"),
                    quantity=cum,
                    status_str="FILLED",
                )
            except Exception as tg_err:
                logger.warning(
                    "Failed fill Telegram after %s for %s: %s",
                    source,
                    order.exchange_order_id,
                    tg_err,
                    exc_info=True,
                )

        order.exchange_update_time = datetime.now(timezone.utc)

        try:
            self._upsert_protection_child_spot_fill(db, order, order_info)
        except Exception as child_err:
            logger.warning(
                "Failed upserting protection child fill for %s: %s",
                order.exchange_order_id,
                child_err,
                exc_info=True,
            )

        if old_status != OrderStatusEnum.FILLED:
            try:
                from app.services.signal_monitor import _emit_lifecycle_event
                from app.services.strategy_profiles import resolve_strategy_profile
                from app.models.watchlist import WatchlistItem

                watchlist_item = db.query(WatchlistItem).filter(
                    WatchlistItem.symbol == order.symbol
                ).first()
                strategy_type, risk_approach = resolve_strategy_profile(
                    order.symbol, db, watchlist_item
                )
                strategy_key = build_strategy_key(strategy_type, risk_approach)
                _emit_lifecycle_event(
                    db=db,
                    symbol=order.symbol,
                    strategy_key=strategy_key,
                    side=order.side.value if hasattr(order.side, "value") else str(order.side),
                    price=order_info.get("price")
                    or (float(order.price) if order.price else None),
                    event_type="ORDER_EXECUTED",
                    event_reason=(
                        f"order_id={order.exchange_order_id}, qty={cum}, "
                        f"status_source={source}"
                    ),
                    order_id=order.exchange_order_id,
                )
            except Exception as emit_err:
                logger.warning(
                    "Failed to emit ORDER_EXECUTED for %s: %s",
                    order.exchange_order_id,
                    emit_err,
                    exc_info=True,
                )
            try:
                self._cancel_oco_after_protection_fill(db, order)
            except Exception as oco_err:
                logger.warning(
                    "Failed to cancel OCO sibling after %s for %s: %s",
                    source,
                    order.exchange_order_id,
                    oco_err,
                    exc_info=True,
                )

        logger.info(
            "Order %s (%s) marked FILLED via %s (was %s, avg=%s qty=%s)",
            order.exchange_order_id,
            order.symbol,
            source,
            getattr(old_status, "value", old_status),
            order_info.get("price"),
            cum,
        )
        return old_status != OrderStatusEnum.FILLED

    def _reconcile_misclassified_protection_fills(
        self, db: Session, *, limit: int = 10
    ) -> int:
        """Re-check CANCELLED TP/SL with zero fill qty via advanced/get-order-detail.

        Spot detail cannot see Advanced Order Management IDs, so filled TPs were sometimes
        stuck ACTIVE then wrongly CANCELLED with cumulative_quantity=0. Upgrade when the
        exchange reports FILLED with cumulative_quantity > 0.
        """
        from sqlalchemy import or_

        candidates = (
            db.query(ExchangeOrder)
            .filter(
                ExchangeOrder.status == OrderStatusEnum.CANCELLED,
                or_(
                    ExchangeOrder.cumulative_quantity.is_(None),
                    ExchangeOrder.cumulative_quantity <= 0,
                ),
                or_(
                    ExchangeOrder.order_role.in_(["TAKE_PROFIT", "STOP_LOSS"]),
                    ExchangeOrder.order_type.in_(
                        [
                            "TAKE_PROFIT",
                            "TAKE_PROFIT_LIMIT",
                            "TAKE_PROFIT_MARKET",
                            "STOP_LOSS",
                            "STOP_LIMIT",
                            "STOP_MARKET",
                            "STOP_LOSS_LIMIT",
                        ]
                    ),
                ),
            )
            .order_by(ExchangeOrder.updated_at.desc())
            .limit(max(1, int(limit)) * 3)
            .all()
        )
        repaired = 0
        checked = 0
        for order in candidates:
            oid = str(order.exchange_order_id)
            if oid in self._protection_reconcile_exhausted:
                continue
            if checked >= max(1, int(limit)):
                break
            checked += 1
            try:
                info = self._resolve_advanced_order_status_from_exchange(
                    order.exchange_order_id,
                    order.exchange_create_time or order.created_at,
                )
                if not info:
                    continue
                status = normalize_resolved_exchange_status(info.get("status"))
                cum = float(info.get("cumulative_quantity") or 0)
                if status in ("CANCELLED", "REJECTED", "EXPIRED") and cum <= 0:
                    # Confirmed non-fill — do not re-poll every sync cycle.
                    self._protection_reconcile_exhausted.add(oid)
                    continue
                if self._apply_protection_fill_from_resolve(
                    db,
                    order,
                    info,
                    source="protection_fill_reconcile",
                ):
                    repaired += 1
                    self._protection_reconcile_exhausted.discard(oid)
            except Exception as err:
                logger.warning(
                    "Failed reconciling protection order %s: %s",
                    order.exchange_order_id,
                    err,
                    exc_info=True,
                )
        return repaired
    
    def _infer_protection_order_role(self, order: ExchangeOrder) -> Optional[str]:
        """Return TAKE_PROFIT / STOP_LOSS when role or order_type indicates protection."""
        role = (getattr(order, "order_role", None) or "").upper()
        if role in ("TAKE_PROFIT", "STOP_LOSS"):
            return role
        order_type = (getattr(order, "order_type", None) or "").upper()
        if order_type in ("TAKE_PROFIT", "TAKE_PROFIT_LIMIT", "TAKE_PROFIT_MARKET"):
            return "TAKE_PROFIT"
        if order_type in ("STOP_LOSS", "STOP_LIMIT", "STOP_MARKET", "STOP_LOSS_LIMIT"):
            return "STOP_LOSS"
        return None

    def _lookup_entry_price_for_protection(
        self, db: Session, order: ExchangeOrder
    ) -> Optional[float]:
        """Find parent/entry fill price for TP/SL profit display."""
        if order.parent_order_id:
            parent = (
                db.query(ExchangeOrder)
                .filter(ExchangeOrder.exchange_order_id == order.parent_order_id)
                .first()
            )
            if parent:
                price = parent.avg_price if parent.avg_price else parent.price
                if price is not None:
                    return float(price)

        side = order.side.value if hasattr(order.side, "value") else str(order.side or "")
        side = side.upper()
        opposite = OrderSideEnum.BUY if side == "SELL" else OrderSideEnum.SELL
        q = db.query(ExchangeOrder).filter(
            ExchangeOrder.symbol == order.symbol,
            ExchangeOrder.side == opposite,
            ExchangeOrder.status == OrderStatusEnum.FILLED,
            ExchangeOrder.order_type.in_(["MARKET", "LIMIT"]),
            ExchangeOrder.exchange_order_id != order.exchange_order_id,
        )
        if order.exchange_create_time:
            q = q.filter(ExchangeOrder.exchange_create_time <= order.exchange_create_time)
        original = q.order_by(ExchangeOrder.exchange_update_time.desc()).first()
        if original:
            price = original.avg_price if original.avg_price else original.price
            if price is not None:
                return float(price)
        return None

    def _maybe_notify_executed_fill_telegram(
        self,
        db: Session,
        order: ExchangeOrder,
        *,
        source: str,
        price: Optional[float] = None,
        quantity: Optional[float] = None,
        status_str: str = "FILLED",
    ) -> bool:
        """Send ORDER EXECUTED Telegram for entry/TP/SL fills when gating allows.

        Used by order-history sync and by open-orders resolve (orders that left
        open orders as FILLED). Does not notify historical spam: relies on
        should_notify_executed_fill + fill_dedup + execution_notified_at.
        """
        try:
            from app.services.telegram_notifier import telegram_notifier

            fill_status = normalize_resolved_exchange_status(status_str)
            if fill_status not in ("FILLED", "PARTIALLY_FILLED"):
                return False

            fill_qty = quantity
            if fill_qty is None:
                fill_qty = float(order.cumulative_quantity or order.quantity or 0)
            else:
                fill_qty = float(fill_qty)
            if fill_qty <= 0:
                return False

            fill_price = price
            if fill_price is None:
                fill_price = float(order.avg_price or order.price or 0)
            else:
                fill_price = float(fill_price)

            gate_ok, gate_reason = should_notify_executed_fill(
                db=db,
                order=order,
                now_utc=datetime.now(timezone.utc),
                source=source,
                requested_by_admin=False,
            )
            fill_dedup = get_fill_dedup(db)
            if not gate_ok:
                fill_dedup.record_fill(
                    order_id=str(order.exchange_order_id),
                    filled_qty=fill_qty,
                    status=fill_status,
                    notification_sent=False,
                )
                logger.debug(
                    "Skipping fill Telegram for %s (%s): %s",
                    order.exchange_order_id,
                    order.symbol,
                    gate_reason,
                )
                return False

            should_notify, notify_reason = fill_dedup.should_notify_fill(
                order_id=str(order.exchange_order_id),
                current_filled_qty=fill_qty,
                status=fill_status,
            )
            if not should_notify:
                logger.debug(
                    "Skipping fill Telegram for %s: %s",
                    order.exchange_order_id,
                    notify_reason,
                )
                return False

            if order.trade_signal_id is None:
                link_system_trade_signal_to_order(db, order)

            inferred_role = self._infer_protection_order_role(order)
            entry_price = None
            if inferred_role:
                entry_price = self._lookup_entry_price_for_protection(db, order)

            side = order.side.value if hasattr(order.side, "value") else str(order.side or "BUY")
            total_usd = fill_price * fill_qty if fill_price and fill_qty else 0.0
            open_orders_count = _count_open_entry_buy_orders(db, order.symbol)

            audit_log = make_json_safe(
                {
                    "event": "ORDER_EXECUTED_NOTIFICATION",
                    "symbol": order.symbol,
                    "side": side,
                    "order_id": str(order.exchange_order_id),
                    "status": fill_status,
                    "cumulative_quantity": fill_qty,
                    "price": fill_price,
                    "order_type": order.order_type,
                    "order_role": inferred_role,
                    "trade_signal_id": order.trade_signal_id,
                    "parent_order_id": order.parent_order_id,
                    "notify_reason": notify_reason,
                    "handler": source,
                }
            )
            logger.info("[FILL_NOTIFICATION] %s", json.dumps(audit_log))

            result = telegram_notifier.send_executed_order(
                symbol=order.symbol,
                side=side,
                price=fill_price or 0,
                quantity=fill_qty,
                total_usd=total_usd,
                order_id=str(order.exchange_order_id),
                order_type=order.order_type or "LIMIT",
                entry_price=entry_price,
                open_orders_count=open_orders_count,
                order_role=inferred_role,
                trade_signal_id=order.trade_signal_id,
                parent_order_id=order.parent_order_id,
            )
            if result:
                order.execution_notified_at = datetime.now(timezone.utc)
                try:
                    db.flush()
                except Exception as flush_err:
                    logger.warning(
                        "Failed to flush execution_notified_at for %s: %s",
                        order.exchange_order_id,
                        flush_err,
                    )
                fill_dedup.record_fill(
                    order_id=str(order.exchange_order_id),
                    filled_qty=fill_qty,
                    status=fill_status,
                    notification_sent=True,
                )
                logger.info(
                    "Sent Telegram notification for executed order: %s %s - %s (source=%s reason=%s)",
                    order.symbol,
                    side,
                    order.exchange_order_id,
                    source,
                    notify_reason,
                )
                return True

            logger.warning(
                "Failed to send Telegram notification for executed order: %s %s - %s",
                order.symbol,
                side,
                order.exchange_order_id,
            )
            return False
        except Exception as telegram_err:
            logger.warning(
                "Failed to send fill Telegram for %s: %s",
                getattr(order, "exchange_order_id", None),
                telegram_err,
                exc_info=True,
            )
            return False

    def _mark_order_processed(self, order_id: str):
        """Mark an order as processed with current timestamp"""
        self.processed_order_ids[order_id] = time.time()
    
    def sync_balances(self, db: Session):
        """Sync account balances from Crypto.com"""
        try:
            # Use portfolio_cache to get REAL balances (not simulated)
            # This avoids the DRY_RUN mode that returns simulated 10k USDT
            from app.services.portfolio_cache import get_portfolio_summary
            
            portfolio_summary = get_portfolio_summary(db)
            
            # Update portfolio cache if empty OR if stale (>60 seconds)
            # This runs in background, so timeouts are OK - it will retry next cycle
            needs_portfolio_update = False
            if not portfolio_summary or not portfolio_summary.get("balances"):
                needs_portfolio_update = True
                logger.info("No cached portfolio data, will update cache from Crypto.com...")
            else:
                last_updated = portfolio_summary.get("last_updated")
                if last_updated:
                    age_seconds = time.time() - last_updated
                    if age_seconds > 60:  # Update if cache is >60 seconds old
                        needs_portfolio_update = True
                        logger.debug(f"Portfolio cache is {age_seconds:.1f}s old, will update...")
            
            if needs_portfolio_update:
                try:
                    from app.services.portfolio_cache import update_portfolio_cache
                    # This may take time but runs in background - OK if it takes 30+ seconds
                    update_result = update_portfolio_cache(db)
                    if update_result.get("success"):
                        portfolio_summary = get_portfolio_summary(db)
                        logger.info(f"✅ Portfolio cache updated: ${update_result.get('total_usd', 0):,.2f}")
                        
                        # Also create a portfolio snapshot when cache is updated (for fresh dashboard data)
                        try:
                            from app.services.portfolio_snapshot import fetch_live_portfolio_snapshot, store_portfolio_snapshot
                            snapshot = fetch_live_portfolio_snapshot(db)
                            store_portfolio_snapshot(db, snapshot)
                            logger.info(f"✅ Portfolio snapshot created: {len(snapshot.get('assets', []))} assets, total=${snapshot.get('total_value_usd', 0):,.2f}")
                        except Exception as snapshot_err:
                            # Don't fail the sync if snapshot creation fails - it's optional
                            logger.debug(f"Could not create portfolio snapshot (non-critical): {snapshot_err}")
                        
                        # Use cached portfolio data (real balances) after successful update
                        accounts = []
                        for balance in portfolio_summary.get("balances", []):
                            accounts.append({
                                'currency': balance['currency'],
                                'balance': str(balance['balance']),
                                'available': str(balance['balance'])  # Use balance as available for now
                            })
                    else:
                        logger.warning("Failed to update portfolio cache, will try direct API call")
                        # Fallback to direct API call
                        # Note: get_account_summary() can raise ValueError or RuntimeError if API credentials are not configured
                        # or if there are authentication/network issues. We need to catch these exceptions.
                        try:
                            response = trade_client.get_account_summary()
                            if not response:
                                logger.warning("No balance data received from Crypto.com")
                                return
                            accounts = []
                            if 'accounts' in response:
                                accounts = response.get('accounts', [])
                            elif 'result' in response:
                                result = response.get('result', {})
                                if 'accounts' in result:
                                    accounts = result.get('accounts', [])
                                elif 'data' in result:
                                    data = result.get('data', [])
                                    if isinstance(data, list) and len(data) > 0:
                                        for item in data:
                                            if 'position_balances' in item:
                                                for balance in item['position_balances']:
                                                    accounts.append({
                                                        'currency': balance.get('instrument_name', ''),
                                                        'balance': balance.get('quantity', '0'),
                                                        'available': balance.get('max_withdrawal_balance', balance.get('quantity', '0'))
                                                    })
                        except (ValueError, RuntimeError) as e:
                            # API credentials not configured or authentication/network error
                            logger.warning(f"Failed to get account summary from API: {e}. Using cached data if available.")
                            # If we have cached data from earlier, continue with that
                            if portfolio_summary and portfolio_summary.get("balances"):
                                logger.info("Using previously cached portfolio data")
                                accounts = []
                                for balance in portfolio_summary.get("balances", []):
                                    accounts.append({
                                        'currency': balance['currency'],
                                        'balance': str(balance['balance']),
                                        'available': str(balance['balance'])
                                    })
                            else:
                                # No cached data available, skip this sync cycle
                                logger.warning("No cached data available, skipping balance sync")
                                return
                        except Exception as e:
                            # Catch any other unexpected exceptions
                            logger.error(f"Unexpected error getting account summary: {e}", exc_info=True)
                            # Try to use cached data if available
                            if portfolio_summary and portfolio_summary.get("balances"):
                                logger.info("Using previously cached portfolio data due to error")
                                accounts = []
                                for balance in portfolio_summary.get("balances", []):
                                    accounts.append({
                                        'currency': balance['currency'],
                                        'balance': str(balance['balance']),
                                        'available': str(balance['balance'])
                                    })
                            else:
                                logger.warning("No cached data available, skipping balance sync")
                                return
                except Exception as try_err:
                    logger.error(f"Error in portfolio update block: {try_err}", exc_info=True)
                    return
            else:
                # Use cached portfolio data (real balances)
                accounts = []
                for balance in portfolio_summary.get("balances", []):
                    accounts.append({
                        'currency': balance['currency'],
                        'balance': str(balance['balance']),
                        'available': str(balance['balance'])  # Use balance as available for now
                    })
            
            if not accounts:
                logger.warning("Empty balance data from Crypto.com")
                return
            
            # Track processed assets
            processed_assets = set()
            
            # Process accounts
            for account in accounts:
                asset = account.get('currency', '').upper()
                if not asset:
                    continue

                try:
                    # Use Decimal consistently for all numeric operations to match database model
                    from decimal import Decimal

                    free_str = account.get('available', account.get('balance', '0'))
                    balance_total_str = account.get('balance', '0')

                    # Convert to Decimal at boundaries, handling potential string inputs
                    try:
                        free = Decimal(str(free_str)) if free_str else Decimal('0')
                        logger.debug(f"[EXCHANGE_SYNC_NUMERIC] field=free before_type={type(free_str).__name__} after_type=Decimal value={free}")
                    except Exception as e:
                        logger.warning(f"[EXCHANGE_SYNC_NUMERIC] field=free before_type={type(free_str).__name__} after_type=Decimal - invalid value: {free_str}, error: {e}")
                        free = Decimal('0')

                    try:
                        balance_total = Decimal(str(balance_total_str)) if balance_total_str else Decimal('0')
                        logger.debug(f"[EXCHANGE_SYNC_NUMERIC] field=balance_total before_type={type(balance_total_str).__name__} after_type=Decimal value={balance_total}")
                    except Exception as e:
                        logger.warning(f"[EXCHANGE_SYNC_NUMERIC] field=balance_total before_type={type(balance_total_str).__name__} after_type=Decimal - invalid value: {balance_total_str}, error: {e}")
                        balance_total = Decimal('0')

                    locked = max(Decimal('0'), balance_total - free)
                    total = free + locked
                    
                    # Only sync non-zero balances
                    if total <= 0:
                        continue
                    
                    # Track this asset as processed
                    processed_assets.add(asset)
                    
                    # Upsert balance
                    existing = db.query(ExchangeBalance).filter(
                        ExchangeBalance.asset == asset
                    ).first()
                    
                    if existing:
                        existing.free = free
                        existing.locked = locked
                        existing.total = total
                        existing.updated_at = datetime.utcnow()
                    else:
                        new_balance = ExchangeBalance(
                            asset=asset,
                            free=free,
                            locked=locked,
                            total=total
                        )
                        db.add(new_balance)
                except (ValueError, TypeError) as e:
                    logger.warning(f"Error processing balance for {asset}: {e}")
                    continue
            
            # After processing accounts, zero out balances for assets that didn't appear
            if processed_assets:
                orphaned_balances = db.query(ExchangeBalance).filter(
                    not_(ExchangeBalance.asset.in_(list(processed_assets)))
                ).all()
                
                for orphaned in orphaned_balances:
                    orphaned.free = Decimal("0")
                    orphaned.locked = Decimal("0")
                    orphaned.total = Decimal("0")
                    orphaned.updated_at = datetime.now(timezone.utc)
                    logger.debug(f"Zeroed out orphaned balance for asset: {orphaned.asset}")
            
            db.commit()
            logger.info(f"Synced {len(accounts)} account balances")
            
        except Exception as e:
            logger.error(f"Error syncing balances: {e}", exc_info=True)
            db.rollback()
    
    def sync_open_orders(self, db: Session):
        """Sync open orders from Crypto.com"""
        from app.services.open_orders_sync_status import (
            record_open_orders_sync_failure,
            record_open_orders_sync_success,
        )
        from app.services.unified_open_orders_fetch import fetch_unified_open_orders

        started_at = time.monotonic()
        logger.info("sync_open_orders start")
        try:
            fetch_result = fetch_unified_open_orders(trade_client)

            if not fetch_result.get("data_verified"):
                record_open_orders_sync_failure(
                    sync_status=fetch_result.get("sync_status") or "api_error",
                    error_code=fetch_result.get("error_code"),
                    error_message=fetch_result.get("error_message"),
                )
                logger.warning(
                    "sync_open_orders end duration=%.2fs status=failed (%s): %s — preserving existing cache",
                    time.monotonic() - started_at,
                    fetch_result.get("sync_status"),
                    fetch_result.get("error_message"),
                )
                return

            unified_orders = fetch_result.get("orders") or []
            all_raw_orders = fetch_result.get("all_raw_orders") or []
            orders = all_raw_orders or (
                (fetch_result.get("regular_raw") or [])
                + (fetch_result.get("trigger_raw") or [])
                + (fetch_result.get("advanced_raw") or [])
            )
            trigger_orders = fetch_result.get("trigger_raw") or []
            advanced_orders = fetch_result.get("advanced_raw") or []

            update_open_orders_cache(unified_orders)
            record_open_orders_sync_success(
                order_count=len(unified_orders),
                trigger_orders_status=fetch_result.get("trigger_orders_status"),
                trigger_orders_error=fetch_result.get("trigger_orders_error"),
                trigger_orders_error_code=fetch_result.get("trigger_orders_error_code"),
            )
            
            # Mark orders not in response as cancelled/closed
            # Include regular, trigger, and advanced orders in the live ID set
            all_exchange_order_ids = set()
            for order in orders:
                for id_field in ("order_id", "exchange_order_id", "client_oid"):
                    oid = order.get(id_field)
                    if oid:
                        all_exchange_order_ids.add(str(oid))
            
            if all_exchange_order_ids or orders or trigger_orders or advanced_orders:
                existing_orders = db.query(ExchangeOrder).filter(
                    and_(
                        ExchangeOrder.exchange_order_id.notin_(all_exchange_order_ids),
                        ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
                    )
                ).all()
                
                # Track cancelled orders for notification
                cancelled_orders = []
                
                # CRITICAL FIX: Refresh database session to ensure we have the latest order statuses
                # from the order history sync that runs before this function
                db.expire_all()
                
                for order in existing_orders:
                    # Refresh this specific order to get latest status from database
                    # This ensures we see if it was just marked as FILLED by order history sync
                    try:
                        db.refresh(order)
                    except Exception as refresh_err:
                        # If refresh fails (e.g., order was deleted), log and continue with fresh query below
                        logger.debug(f"Could not refresh order {order.exchange_order_id}: {refresh_err}")
                    
                    # Check if order is filled in history (might have been filled between syncs)
                    # For MARKET orders, they may execute immediately and not appear in open orders
                    # Check order history first before marking as cancelled
                    # Order history sync runs on a separate schedule; refresh this row and resolve
                    # status from exchange history before marking anything cancelled.
                    if order.status == OrderStatusEnum.FILLED:
                        logger.debug(f"Order {order.exchange_order_id} ({order.symbol}) is FILLED, skipping cancellation")
                        continue
                    
                    # Double-check with a fresh query to be absolutely sure (handles cases where refresh failed)
                    filled_order = db.query(ExchangeOrder).filter(
                        and_(
                            ExchangeOrder.exchange_order_id == order.exchange_order_id,
                            ExchangeOrder.status == OrderStatusEnum.FILLED
                        )
                    ).first()
                    
                    if not filled_order:
                        # CRITICAL FIX: Resolve real final status from exchange before marking as canceled
                        # "Order not found in Open Orders" ≠ "Order canceled" - order may have been FILLED
                        order_info = self._resolve_order_status_from_exchange(
                            order.exchange_order_id,
                            order.exchange_create_time or order.created_at,
                            instrument_name=order.symbol,
                        )
                        
                        if order_info:
                            # Order found in exchange history - use confirmed status
                            resolved_status = normalize_resolved_exchange_status(
                                order_info.get("status")
                            )
                            old_status = order.status
                            
                            if resolved_status == 'FILLED':
                                is_protection = (
                                    order.order_role in ("TAKE_PROFIT", "STOP_LOSS")
                                    or (
                                        order.order_type
                                        and str(order.order_type).upper() in _PROTECTIVE_ORDER_TYPES
                                    )
                                )
                                if is_protection:
                                    # Shared path: Telegram + child spot upsert + OCO cancel
                                    self._apply_protection_fill_from_resolve(
                                        db,
                                        order,
                                        order_info,
                                        source="sync_open_orders_resolve",
                                    )
                                    continue

                                # Entry / non-protection fill — update status and emit ORDER_EXECUTED
                                order.status = OrderStatusEnum.FILLED
                                order.cumulative_quantity = order_info.get('cumulative_quantity', order.quantity)
                                if order_info.get('price'):
                                    order.avg_price = order_info['price']
                                logger.info(f"Order {order.exchange_order_id} ({order.symbol}) confirmed as FILLED via exchange history")

                                # Telegram BEFORE bumping exchange_update_time so the
                                # historical-fill gate still uses create/prior update time
                                # (system TP/SL with parent_order_id still notify).
                                if old_status != OrderStatusEnum.FILLED:
                                    try:
                                        self._maybe_notify_executed_fill_telegram(
                                            db,
                                            order,
                                            source="sync_open_orders_resolve",
                                            price=order_info.get("price"),
                                            quantity=order_info.get("cumulative_quantity"),
                                            status_str="FILLED",
                                        )
                                    except Exception as tg_err:
                                        logger.warning(
                                            "Failed fill Telegram after open-orders resolve for %s: %s",
                                            order.exchange_order_id,
                                            tg_err,
                                            exc_info=True,
                                        )

                                order.exchange_update_time = datetime.now(timezone.utc)
                                
                                # Emit ORDER_EXECUTED event
                                if old_status != OrderStatusEnum.FILLED:
                                    try:
                                        from app.services.signal_monitor import _emit_lifecycle_event
                                        from app.services.strategy_profiles import resolve_strategy_profile
                                        from app.models.watchlist import WatchlistItem
                                        
                                        watchlist_item = db.query(WatchlistItem).filter(
                                            WatchlistItem.symbol == order.symbol
                                        ).first()
                                        strategy_type, risk_approach = resolve_strategy_profile(
                                            order.symbol, db, watchlist_item
                                        )
                                        strategy_key = build_strategy_key(strategy_type, risk_approach)
                                        
                                        _emit_lifecycle_event(
                                            db=db,
                                            symbol=order.symbol,
                                            strategy_key=strategy_key,
                                            side=order.side.value if hasattr(order.side, 'value') else str(order.side),
                                            price=order_info.get('price') or (float(order.price) if order.price else None),
                                            event_type="ORDER_EXECUTED",
                                            event_reason=f"order_id={order.exchange_order_id}, qty={order_info.get('cumulative_quantity', 0)}, status_source=order_history",
                                            order_id=order.exchange_order_id,
                                        )
                                    except Exception as emit_err:
                                        logger.warning(f"Failed to emit ORDER_EXECUTED event for {order.exchange_order_id}: {emit_err}", exc_info=True)
                                
                                # Don't add to cancelled_orders - order was executed
                                continue
                                
                            elif resolved_status in ('CANCELLED', 'EXPIRED', 'REJECTED'):
                                # Order was canceled/expired/rejected - update status and emit ORDER_CANCELED
                                order.status = OrderStatusEnum(resolved_status)
                                order.exchange_update_time = datetime.now(timezone.utc)
                                logger.info(f"Order {order.exchange_order_id} ({order.symbol}) confirmed as {resolved_status} via exchange history")
                                if resolved_status == "REJECTED" and order.order_role in ("STOP_LOSS", "TAKE_PROFIT"):
                                    reject_reason = order_info.get("reject_reason") or "unknown"
                                    try:
                                        from app.services.telegram_notifier import telegram_notifier

                                        telegram_notifier.send_message(
                                            "🚫 <b>PROTECTION ORDER REJECTED</b>\n\n"
                                            f"📊 Symbol: <b>{order.symbol}</b>\n"
                                            f"📋 Role: {order.order_role}\n"
                                            f"🆔 Order: <code>{order.exchange_order_id}</code>\n"
                                            f"⚠️ Reason: <code>{reject_reason}</code>",
                                            symbol=order.symbol,
                                        )
                                    except Exception as alert_err:
                                        logger.warning("Failed protection reject alert: %s", alert_err)
                                
                                # Emit ORDER_CANCELED event if status actually changed
                                if old_status != OrderStatusEnum(resolved_status):
                                    try:
                                        from app.services.signal_monitor import _emit_lifecycle_event
                                        from app.services.strategy_profiles import resolve_strategy_profile
                                        from app.models.watchlist import WatchlistItem
                                        
                                        watchlist_item = db.query(WatchlistItem).filter(
                                            WatchlistItem.symbol == order.symbol
                                        ).first()
                                        strategy_type, risk_approach = resolve_strategy_profile(
                                            order.symbol, db, watchlist_item
                                        )
                                        strategy_key = build_strategy_key(strategy_type, risk_approach)
                                        
                                        _emit_lifecycle_event(
                                            db=db,
                                            symbol=order.symbol,
                                            strategy_key=strategy_key,
                                            side=order.side.value if hasattr(order.side, 'value') else str(order.side),
                                            price=float(order.price) if order.price else None,
                                            event_type="ORDER_CANCELED",
                                            event_reason=f"order_id={order.exchange_order_id}, status={resolved_status}, status_source=order_history",
                                            order_id=order.exchange_order_id,
                                        )
                                    except Exception as emit_err:
                                        logger.warning(f"Failed to emit ORDER_CANCELED event for {order.exchange_order_id}: {emit_err}", exc_info=True)
                                
                                cancelled_orders.append(order)
                                continue
                            else:
                                # Status is NEW, ACTIVE, PARTIALLY_FILLED - order still pending, don't mark as canceled
                                logger.debug(f"Order {order.exchange_order_id} ({order.symbol}) status is {resolved_status} - still pending, not marking as canceled")
                                continue
                        else:
                            # Order not found in exchange history — only ghost-cancel
                            # non-protection rows after grace. SL/TP trigger orders are
                            # often missing from spot open/history snapshots; marking
                            # them CANCELLED caused recreate loops (moved TP prices).
                            order_created = order.exchange_create_time or order.created_at
                            age_seconds = None
                            if order_created:
                                created_utc = order_created
                                if created_utc.tzinfo is None:
                                    created_utc = created_utc.replace(tzinfo=timezone.utc)
                                age_seconds = (datetime.now(timezone.utc) - created_utc).total_seconds()
                            may_cancel, cancel_reason = should_mark_unresolved_order_cancelled(
                                order,
                                age_seconds,
                                grace_seconds=GHOST_CANCEL_GRACE_SECONDS,
                            )
                            if may_cancel:
                                old_status = order.status
                                order.status = OrderStatusEnum.CANCELLED
                                order.exchange_update_time = datetime.now(timezone.utc)
                                logger.info(
                                    "Order %s (%s) not in open orders or history for %.0fs — marking CANCELLED (DB ghost cleanup, reason=%s)",
                                    order.exchange_order_id,
                                    order.symbol,
                                    age_seconds if age_seconds is not None else -1,
                                    cancel_reason,
                                )
                                if old_status != OrderStatusEnum.CANCELLED:
                                    cancelled_orders.append(order)
                            else:
                                logger.info(
                                    "Order %s (%s role=%s type=%s) unresolved on exchange — "
                                    "not ghost-cancelling (reason=%s, age_s=%s)",
                                    order.exchange_order_id,
                                    order.symbol,
                                    order.order_role,
                                    order.order_type,
                                    cancel_reason,
                                    f"{age_seconds:.0f}" if age_seconds is not None else "unknown",
                                )
                            continue
                
                # Telegram for sync cancels: skip routine SL/TP leg noise; dedupe entry cancels.
                if cancelled_orders:
                    try:
                        from app.services.telegram_notifier import telegram_notifier

                        notify_orders = filter_sync_cancel_orders_for_telegram(db, cancelled_orders)

                        if not notify_orders:
                            logger.info(
                                "📢 No sync-cancel Telegram sent (%d cancelled; all protection or deduped)",
                                len(cancelled_orders),
                            )
                        elif len(notify_orders) == 1:
                            order = notify_orders[0]
                            parent_entry_side = None
                            if order.parent_order_id:
                                parent_order = db.query(ExchangeOrder).filter(
                                    ExchangeOrder.exchange_order_id == order.parent_order_id
                                ).first()
                                if parent_order:
                                    parent_entry_side = (
                                        parent_order.side.value
                                        if hasattr(parent_order.side, "value")
                                        else str(parent_order.side)
                                    )
                            message = telegram_notifier.format_sync_cancelled_order_message(
                                symbol=order.symbol,
                                side=order.side.value if hasattr(order.side, "value") else str(order.side),
                                order_type=order.order_type or "UNKNOWN",
                                order_id=order.exchange_order_id,
                                order_role=order.order_role,
                                parent_order_id=order.parent_order_id,
                                parent_entry_side=parent_entry_side,
                                price=float(order.price) if order.price else None,
                                quantity=float(order.quantity) if order.quantity else None,
                            )
                            telegram_notifier.send_message(message.strip(), origin="AWS")
                            logger.info(
                                "✅ Sent Telegram notification for 1 sync-cancelled entry order"
                            )
                        else:
                            message = (
                                f"❌ <b>ORDERS CANCELLED (Sync)</b>\n\n"
                                f"📋 <b>{len(notify_orders)} orders</b> have been cancelled (not found in exchange open orders):\n\n"
                            )
                            for idx, order in enumerate(notify_orders[:10], 1):
                                order_type = order.order_type or "UNKNOWN"
                                order_role = f" ({order.order_role})" if order.order_role else ""
                                side = order.side.value if hasattr(order.side, "value") else str(order.side)
                                message += (
                                    f"{idx}. <b>{order.symbol}</b> - {order_type}{order_role} ({side})\n"
                                    f"   ID: <code>{order.exchange_order_id}</code>\n\n"
                                )
                            if len(notify_orders) > 10:
                                message += f"... and {len(notify_orders) - 10} more orders\n\n"
                            message += "💡 <b>Reason:</b> Orders not found in exchange open orders during sync"
                            telegram_notifier.send_message(message.strip(), origin="AWS")
                            logger.info(
                                "✅ Sent Telegram notification for %d sync-cancelled entry order(s)",
                                len(notify_orders),
                            )
                    except Exception as notify_err:
                        logger.warning(f"⚠️ Failed to send Telegram notification for cancelled orders from sync: {notify_err}", exc_info=True)
                        # Don't fail sync if notification fails
            
            # Upsert orders from merged live response (regular + trigger + advanced)
            for order_data in orders:
                order_id = order_data.get('order_id') or order_data.get('exchange_order_id')
                if not order_id:
                    continue
                order_id = str(order_id)
                
                symbol = order_data.get('instrument_name', '')
                side = order_data.get('side', '').upper()
                status_str = order_data.get('status', '').upper()
                
                # Parse timestamps
                create_time = None
                update_time = None
                if order_data.get('create_time'):
                    try:
                        # CRITICAL FIX: Use timezone.utc to ensure timestamps are interpreted as UTC, not local time
                        create_time = datetime.fromtimestamp(order_data['create_time'] / 1000, tz=timezone.utc)
                    except:
                        pass
                if order_data.get('update_time'):
                    try:
                        # CRITICAL FIX: Use timezone.utc to ensure timestamps are interpreted as UTC, not local time
                        update_time = datetime.fromtimestamp(order_data['update_time'] / 1000, tz=timezone.utc)
                    except:
                        pass
                
                status = map_exchange_order_status(
                    status_str,
                    cumulative_quantity=order_data.get("cumulative_quantity", 0) or 0,
                    quantity=order_data.get("quantity", 0) or 0,
                )
                
                # Get price from limit_price (primary) or price (fallback)
                # Crypto.com API uses 'limit_price' for limit orders
                order_price = order_data.get('limit_price') or order_data.get('price')
                order_price_float = float(order_price) if order_price else None
                
                # Upsert order
                existing = db.query(ExchangeOrder).filter(
                    ExchangeOrder.exchange_order_id == order_id
                ).first()
                
                if existing:
                    existing.symbol = symbol
                    existing.side = OrderSideEnum.BUY if side == 'BUY' else OrderSideEnum.SELL
                    existing.status = status
                    existing.price = _to_decimal(order_price_float) if order_price_float is not None else None
                    existing.quantity = _to_decimal(order_data.get('quantity') or 0)
                    existing.cumulative_quantity = _to_decimal(order_data.get('cumulative_quantity') or 0)
                    existing.cumulative_value = _to_decimal(order_data.get('cumulative_value') or 0)
                    existing.avg_price = _to_decimal(order_data.get('avg_price')) if order_data.get('avg_price') else None
                    existing.exchange_create_time = create_time
                    existing.exchange_update_time = update_time
                    existing.updated_at = datetime.utcnow()
                    # CRITICAL: Preserve parent_order_id and order_role if they exist
                    # These are set when SL/TP orders are created and should not be overwritten
                    # Do NOT update parent_order_id or order_role from exchange sync
                    
                    # Auto-cancel REJECTED TP orders (they should be removed automatically)
                    if status == OrderStatusEnum.REJECTED:
                        order_type_upper = order_data.get('order_type', '').upper()
                        # Check if it's a TP order (TAKE_PROFIT_LIMIT or TAKE_PROFIT)
                        if 'TAKE_PROFIT' in order_type_upper or existing.order_role == 'TAKE_PROFIT':
                            from app.utils.live_trading import get_live_trading_status
                            live_trading = get_live_trading_status(db)
                            
                            if not live_trading:
                                logger.info(f"DRY_RUN: Would cancel REJECTED TP order {order_id} ({symbol})")
                            else:
                                try:
                                    from app.services.live_trading_gate import assert_exchange_mutation_allowed, LiveTradingBlockedError  # pyright: ignore[reportMissingImports]
                                    assert_exchange_mutation_allowed(db, "cancel_rejected_tp", symbol, None)
                                    # Try to cancel the order on the exchange (in case it's still there)
                                    cancel_result = trade_client.cancel_order(order_id)
                                    
                                    # Check if cancellation was successful
                                    if "error" in cancel_result:
                                        error_msg = cancel_result.get("error", "Unknown error")
                                        logger.warning(f"⚠️ Could not cancel REJECTED TP order {order_id} on exchange: {error_msg}")
                                    else:
                                        logger.info(f"✅ Cancelled REJECTED TP order {order_id} ({symbol}) on exchange")
                                    
                                    # Send Telegram notification for REJECTED TP auto-cancellation
                                    # (Note: We notify regardless of cancellation success since the order is REJECTED)
                                    try:
                                        from app.services.telegram_notifier import telegram_notifier
                                        
                                        price_text = f"\n💵 Price: ${existing.price:.4f}" if existing.price else ""
                                        qty_text = f"\n📦 Quantity: {existing.quantity:.8f}" if existing.quantity else ""
                                        
                                        message = (
                                            f"🗑️ <b>REJECTED TP ORDER AUTO-CANCELLED</b>\n\n"
                                            f"📊 Symbol: <b>{symbol}</b>\n"
                                            f"📋 Order ID: <code>{order_id}</code>\n"
                                            f"🎯 Type: {order_type_upper}{price_text}{qty_text}\n\n"
                                            f"💡 <b>Reason:</b> TP order was REJECTED by exchange and automatically cancelled to prevent issues"
                                        )
                                        
                                        telegram_notifier.send_message(message.strip(), origin="AWS")
                                        logger.info(f"✅ Sent Telegram notification for REJECTED TP auto-cancellation: {order_id}")
                                    except Exception as notify_err:
                                        logger.warning(f"⚠️ Failed to send Telegram notification for REJECTED TP auto-cancellation: {notify_err}", exc_info=True)
                                        # Don't fail cancellation if notification fails
                                except LiveTradingBlockedError:
                                    logger.info("[HANDOFF_TOTAL] exchange_sync skipped action=cancel_rejected_tp symbol=%s", symbol)
                                except Exception as cancel_err:
                                    logger.warning(f"⚠️ Could not cancel REJECTED TP order {order_id} on exchange (may already be cancelled): {cancel_err}")
                            
                            logger.info(f"🗑️ REJECTED TP order {order_id} ({symbol}) detected - marked for cleanup")
                else:
                    # For new orders from exchange sync, try to infer parent_order_id and order_role
                    # if this looks like an SL/TP order (STOP_LIMIT or TAKE_PROFIT_LIMIT)
                    order_type_str = order_data.get('order_type', 'LIMIT')
                    inferred_order_role = None
                    inferred_parent_order_id = None
                    
                    if order_type_str in ['STOP_LIMIT', 'STOP_LOSS_LIMIT']:
                        inferred_order_role = 'STOP_LOSS'
                        # Try to find a recent FILLED BUY order for this symbol that might be the parent
                        # Look for orders filled within the last 24 hours
                        from datetime import timedelta
                        recent_threshold = datetime.now(timezone.utc) - timedelta(hours=24)
                        if side == 'SELL':  # SL after BUY
                            parent_candidate = db.query(ExchangeOrder).filter(
                                ExchangeOrder.symbol == symbol,
                                ExchangeOrder.side == OrderSideEnum.BUY,
                                ExchangeOrder.status == OrderStatusEnum.FILLED,
                                ExchangeOrder.order_type.in_(['MARKET', 'LIMIT']),
                                ExchangeOrder.exchange_update_time >= recent_threshold
                            ).order_by(ExchangeOrder.exchange_update_time.desc()).first()
                            if parent_candidate:
                                inferred_parent_order_id = parent_candidate.exchange_order_id
                    elif order_type_str in ['TAKE_PROFIT_LIMIT', 'TAKE_PROFIT']:
                        inferred_order_role = 'TAKE_PROFIT'
                        # Try to find a recent FILLED BUY order for this symbol that might be the parent
                        from datetime import timedelta
                        recent_threshold = datetime.now(timezone.utc) - timedelta(hours=24)
                        if side == 'SELL':  # TP after BUY
                            parent_candidate = db.query(ExchangeOrder).filter(
                                ExchangeOrder.symbol == symbol,
                                ExchangeOrder.side == OrderSideEnum.BUY,
                                ExchangeOrder.status == OrderStatusEnum.FILLED,
                                ExchangeOrder.order_type.in_(['MARKET', 'LIMIT']),
                                ExchangeOrder.exchange_update_time >= recent_threshold
                            ).order_by(ExchangeOrder.exchange_update_time.desc()).first()
                            if parent_candidate:
                                inferred_parent_order_id = parent_candidate.exchange_order_id
                    
                    new_order = ExchangeOrder(
                        exchange_order_id=order_id,
                        client_oid=order_data.get('client_oid'),
                        symbol=symbol,
                        side=OrderSideEnum.BUY if side == 'BUY' else OrderSideEnum.SELL,
                        order_type=order_data.get('order_type', 'LIMIT'),
                        status=status,
                        price=order_price_float,
                        quantity=float(order_data.get('quantity', 0)) if order_data.get('quantity') else 0,
                        cumulative_quantity=float(order_data.get('cumulative_quantity', 0)) if order_data.get('cumulative_quantity') else 0,
                        cumulative_value=float(order_data.get('cumulative_value', 0)) if order_data.get('cumulative_value') else 0,
                        avg_price=float(order_data.get('avg_price')) if order_data.get('avg_price') else None,
                        exchange_create_time=create_time,
                        exchange_update_time=update_time,
                        order_role=inferred_order_role,  # Set inferred role if available
                        parent_order_id=inferred_parent_order_id  # Set inferred parent if available
                    )
                    db.add(new_order)
                    logger.debug("[EXCHANGE_ORDERS_OWNER] exchange_sync upsert order_id=%s symbol=%s", order_id, symbol)
                    if inferred_order_role:
                        logger.info(f"Inferred order_role={inferred_order_role} and parent_order_id={inferred_parent_order_id} for order {order_id} ({symbol}) from exchange sync")
                
                # Update trade signal status if linked; attach trade_signal_id to ExchangeOrder
                if order_id:
                    signal = db.query(TradeSignal).filter(
                        TradeSignal.exchange_order_id == order_id
                    ).first()
                    
                    if signal:
                        if status == OrderStatusEnum.FILLED:
                            signal.status = SignalStatusEnum.FILLED
                        elif status in [OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED]:
                            signal.status = SignalStatusEnum.ORDER_PLACED
                        signal.last_update_at = datetime.utcnow()
                        order_row = db.query(ExchangeOrder).filter(
                            ExchangeOrder.exchange_order_id == order_id
                        ).first()
                        if order_row:
                            link_system_trade_signal_to_order(db, order_row)

            # Repair TP/SL rows previously misclassified as CANCELLED (cumqty=0) when
            # spot get-order-detail could not see Advanced Order Management fills.
            try:
                repaired = self._reconcile_misclassified_protection_fills(db, limit=10)
                if repaired:
                    logger.info(
                        "Repaired %d misclassified protection fill(s) via advanced/get-order-detail",
                        repaired,
                    )
            except Exception as repair_err:
                logger.warning(
                    "Protection fill reconcile failed: %s", repair_err, exc_info=True
                )

            # Lightweight sweeper: ACTIVE SL/TP whose OCO sibling is already FILLED
            # and the orphan is still present on the exchange open-orders snapshot.
            try:
                swept = self._sweep_orphaned_oco_siblings(
                    db, live_open_ids=all_exchange_order_ids, limit=20
                )
                if swept:
                    logger.info(
                        "Swept %d orphaned OCO sibling(s) still open after linked fill",
                        swept,
                    )
            except Exception as sweep_err:
                logger.warning(
                    "Orphaned OCO sibling sweep failed: %s", sweep_err, exc_info=True
                )

            db.commit()
            regular_count = fetch_result.get("regular_count", 0)
            trigger_count = fetch_result.get("trigger_count", 0)
            advanced_count = len(fetch_result.get("advanced_raw") or [])
            total_count = len(unified_orders)
            logger.info(
                "sync_open_orders end duration=%.2fs regular=%d trigger=%d advanced=%d total=%d cache_updated=%d",
                time.monotonic() - started_at,
                regular_count,
                trigger_count,
                advanced_count,
                total_count,
                total_count,
            )
            
        except Exception as e:
            logger.error(
                "sync_open_orders failed duration=%.2fs error=%s",
                time.monotonic() - started_at,
                e,
                exc_info=True,
            )
            db.rollback()
            try:
                from app.services.notion_tasks import create_bug_task
                create_bug_task(
                    title="Order synchronization failure",
                    project="Crypto Trading",
                    details=f"Error syncing open orders: {str(e)[:500]}.",
                )
                logger.info("Trading failure triggered Notion bug task: Order synchronization failure")
            except Exception as notion_err:
                logger.debug("Notion bug task creation failed (non-fatal): %s", notion_err)
    
    def _send_oco_cancellation_notification(self, db: Session, filled_order: 'ExchangeOrder', cancelled_sibling: 'ExchangeOrder', was_already_cancelled: bool = False):
        """Send Telegram notification for OCO sibling cancellation"""
        try:
            from datetime import timezone
            from app.services.telegram_notifier import telegram_notifier
            from app.services.telegram_event_dedup import claim_telegram_event
            from app.models.exchange_order import ExchangeOrder

            allow, reason = should_notify_oco_sibling_cancel(filled_order)
            if not allow:
                logger.info(
                    "Skipping OCO cancel Telegram for %s (filled=%s sibling=%s): %s",
                    getattr(cancelled_sibling, "symbol", None),
                    getattr(filled_order, "exchange_order_id", None),
                    getattr(cancelled_sibling, "exchange_order_id", None),
                    reason,
                )
                return

            dedup_key = (
                f"oco_sibling_cancel:"
                f"{filled_order.exchange_order_id}:{cancelled_sibling.exchange_order_id}"
            )
            if not claim_telegram_event(
                db,
                dedup_key,
                symbol=getattr(cancelled_sibling, "symbol", None),
                ttl_minutes=OCO_CANCEL_TELEGRAM_TTL_MINUTES,
            ):
                logger.info(
                    "Skipping duplicate OCO cancel Telegram for %s (%s)",
                    cancelled_sibling.symbol,
                    dedup_key,
                )
                return
            
            # Get filled order details
            filled_order_type = filled_order.order_type or "UNKNOWN"
            filled_order_price = filled_order.avg_price or filled_order.price or 0
            filled_order_qty = filled_order.quantity or filled_order.cumulative_quantity or 0
            filled_order_time = filled_order.exchange_update_time or filled_order.updated_at
            
            # Get cancelled order details
            cancelled_order_type = cancelled_sibling.order_type or "UNKNOWN"
            cancelled_order_price = cancelled_sibling.price or 0
            cancelled_order_qty = cancelled_sibling.quantity or 0
            cancelled_order_time = cancelled_sibling.exchange_update_time or cancelled_sibling.updated_at or datetime.now(timezone.utc)
            
            # Format times
            filled_time_str = filled_order_time.strftime("%Y-%m-%d %H:%M:%S UTC") if filled_order_time else "N/A"
            cancelled_time_str = cancelled_order_time.strftime("%Y-%m-%d %H:%M:%S UTC") if cancelled_order_time else "N/A"
            
            # Calculate profit/loss if possible
            pnl_info = ""
            if filled_order.parent_order_id:
                parent_order = db.query(ExchangeOrder).filter(
                    ExchangeOrder.exchange_order_id == filled_order.parent_order_id
                ).first()
                if parent_order:
                    entry_price = parent_order.avg_price or parent_order.price or 0
                    parent_side = parent_order.side.value if hasattr(parent_order.side, 'value') else str(parent_order.side)
                    
                    if entry_price > 0 and filled_order_price > 0 and filled_order_qty > 0:
                        if parent_side == "BUY":
                            pnl_usd = (filled_order_price - entry_price) * filled_order_qty
                            pnl_pct = ((filled_order_price - entry_price) / entry_price) * 100
                        else:  # SELL (short position)
                            pnl_usd = (entry_price - filled_order_price) * filled_order_qty
                            pnl_pct = ((entry_price - filled_order_price) / entry_price) * 100
                        
                        pnl_emoji = "💰" if pnl_usd >= 0 else "💸"
                        pnl_label = "Profit" if pnl_usd >= 0 else "Loss"
                        pnl_info = (
                            f"\n{pnl_emoji} <b>{pnl_label}:</b> ${abs(pnl_usd):,.2f} ({pnl_pct:+.2f}%)\n"
                            f"   💵 Entry: ${entry_price:,.4f} → Exit: ${filled_order_price:,.4f}"
                        )
            
            # Build message
            cancellation_note = " (already cancelled by Crypto.com OCO)" if was_already_cancelled else ""
            message = (
                f"🔄 <b>OCO: Order Cancelled{cancellation_note}</b>\n\n"
                f"📊 Symbol: <b>{cancelled_sibling.symbol}</b>\n"
                f"🔗 OCO Group ID: <code>{filled_order.oco_group_id}</code>\n\n"
                f"✅ <b>Filled Order:</b>\n"
                f"   🎯 Type: {filled_order_type}\n"
                f"   📋 Role: {filled_order.order_role or 'N/A'}\n"
                f"   💵 Price: ${filled_order_price:.4f}\n"
                f"   📦 Quantity: {filled_order_qty:.8f}\n"
                f"   ⏰ Time: {filled_time_str}\n"
                f"{pnl_info}\n"
                f"❌ <b>Cancelled Order:</b>\n"
                f"   🎯 Type: {cancelled_order_type}\n"
                f"   📋 Role: {cancelled_sibling.order_role or 'N/A'}\n"
                f"   💵 Price: ${cancelled_order_price:.4f}\n"
                f"   📦 Quantity: {cancelled_order_qty:.8f}\n"
                f"   ⏰ Cancelled: {cancelled_time_str}\n\n"
                f"📋 Order IDs:\n"
                f"   ✅ Filled: <code>{filled_order.exchange_order_id}</code>\n"
                f"   ❌ Cancelled: <code>{cancelled_sibling.exchange_order_id}</code>\n\n"
                f"💡 <b>Reason:</b> One-Cancels-Other (OCO) - When one protection order is filled, the other is automatically cancelled to prevent double execution."
            )
            
            telegram_notifier.send_message(message)
            logger.info(f"Sent detailed OCO cancellation notification for {cancelled_sibling.symbol}")
        except Exception as e:
            logger.warning(f"Failed to send OCO cancellation notification: {e}", exc_info=True)
            raise
    
    @staticmethod
    def _opposite_protection_role(role: Optional[str]) -> Optional[str]:
        role_u = (role or "").upper()
        if role_u == "TAKE_PROFIT":
            return "STOP_LOSS"
        if role_u == "STOP_LOSS":
            return "TAKE_PROFIT"
        return None

    @staticmethod
    def _is_active_oco_sibling_status(status) -> bool:
        """True for open/working sibling statuses (enum or raw string)."""
        if status is None:
            return False
        raw = getattr(status, "value", status)
        return str(raw).upper() in {
            "NEW",
            "ACTIVE",
            "PENDING",
            "OPEN",
            "PARTIALLY_FILLED",
            "UNTRIGGERED",
        }

    @staticmethod
    def _cancel_order_type_for_sibling(sibling: "ExchangeOrder") -> Optional[str]:
        """Prefer DB order_type; map protection role so advanced cancel is used."""
        ot = (getattr(sibling, "order_type", None) or "").strip().upper()
        if ot in {"STOP_LOSS", "STOP_LIMIT", "TAKE_PROFIT", "TAKE_PROFIT_LIMIT"}:
            return ot
        # Native OCO TP leg is a plain LIMIT (not TAKE_PROFIT_LIMIT).
        if ot in {"LIMIT", "LIMIT_MAKER"}:
            return ot
        role = (getattr(sibling, "order_role", None) or "").upper()
        if role == "STOP_LOSS":
            return "STOP_LIMIT"
        if role == "TAKE_PROFIT":
            return "TAKE_PROFIT_LIMIT"
        return ot or None

    @staticmethod
    def _cancel_result_indicates_already_gone(result: Optional[dict]) -> bool:
        """Idempotent success when exchange says the order is already absent."""
        if not isinstance(result, dict):
            return False
        if "error" not in result:
            return False
        msg = str(result.get("error") or result.get("message") or "").lower()
        needles = (
            "not found",
            "does not exist",
            "already cancelled",
            "already canceled",
            "order_not_found",
            "invalid order_id",
            "no such order",
        )
        return any(n in msg for n in needles)

    def _find_oco_siblings(
        self, db: Session, filled_order: "ExchangeOrder"
    ) -> list:
        """Find linked OCO siblings via oco_group_id and/or parent_order_id + opposite role.

        Never matches on NULL oco_group_id (would pull unrelated rows).
        """
        from app.models.exchange_order import ExchangeOrder

        filled_id = getattr(filled_order, "exchange_order_id", None)
        oco_gid = getattr(filled_order, "oco_group_id", None)
        parent_id = getattr(filled_order, "parent_order_id", None)
        opposite_role = self._opposite_protection_role(
            getattr(filled_order, "order_role", None)
        )

        if not oco_gid and not (parent_id and opposite_role):
            logger.debug(
                "OCO: no linkage for %s (oco_group_id=%s parent_order_id=%s role=%s)",
                filled_id,
                oco_gid,
                parent_id,
                getattr(filled_order, "order_role", None),
            )
            return []

        found: dict = {}

        if oco_gid:
            for sib in (
                db.query(ExchangeOrder)
                .filter(
                    ExchangeOrder.oco_group_id == oco_gid,
                    ExchangeOrder.exchange_order_id != filled_id,
                )
                .all()
            ):
                found[sib.exchange_order_id] = sib

        if parent_id and opposite_role:
            for sib in (
                db.query(ExchangeOrder)
                .filter(
                    ExchangeOrder.parent_order_id == parent_id,
                    ExchangeOrder.order_role == opposite_role,
                    ExchangeOrder.exchange_order_id != filled_id,
                )
                .all()
            ):
                found.setdefault(sib.exchange_order_id, sib)

        return list(found.values())

    def _cancel_oco_after_protection_fill(
        self, db: Session, filled_order: "ExchangeOrder"
    ) -> bool:
        """Cancel OCO sibling after a protection fill; fall back to parent/role search."""
        oco_ok = self._cancel_oco_sibling(db, filled_order)
        if oco_ok:
            return True
        try:
            order_type = (
                getattr(filled_order, "order_type", None)
                or getattr(filled_order, "order_role", None)
                or ""
            )
            symbol = getattr(filled_order, "symbol", None)
            order_id = getattr(filled_order, "exchange_order_id", None)
            if not symbol or not order_id:
                return False
            logger.info(
                "OCO helper returned False for %s; trying _cancel_remaining_sl_tp fallback",
                order_id,
            )
            cancelled = self._cancel_remaining_sl_tp(db, symbol, str(order_type), order_id)
            return bool(cancelled and cancelled > 0)
        except Exception as fallback_err:
            logger.warning(
                "OCO fallback cancel failed for %s: %s",
                getattr(filled_order, "exchange_order_id", None),
                fallback_err,
                exc_info=True,
            )
            return False

    def _sweep_orphaned_oco_siblings(
        self,
        db: Session,
        *,
        live_open_ids: Optional[set] = None,
        limit: int = 20,
    ) -> int:
        """Cancel ACTIVE SL/TP still open on exchange whose linked sibling is FILLED.

        Only cancels orders present in ``live_open_ids`` (current open-orders snapshot)
        so phantom ACTIVE DB rows are not live-cancelled.
        """
        from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
        from sqlalchemy import or_

        if not live_open_ids:
            return 0

        open_ids = {str(x) for x in live_open_ids if x}
        candidates = (
            db.query(ExchangeOrder)
            .filter(
                ExchangeOrder.status.in_(
                    [
                        OrderStatusEnum.NEW,
                        OrderStatusEnum.ACTIVE,
                        OrderStatusEnum.PARTIALLY_FILLED,
                    ]
                ),
                or_(
                    ExchangeOrder.order_role.in_(["TAKE_PROFIT", "STOP_LOSS"]),
                    ExchangeOrder.order_type.in_(
                        [
                            "TAKE_PROFIT",
                            "TAKE_PROFIT_LIMIT",
                            "STOP_LOSS",
                            "STOP_LIMIT",
                        ]
                    ),
                ),
                or_(
                    ExchangeOrder.oco_group_id.isnot(None),
                    ExchangeOrder.parent_order_id.isnot(None),
                ),
            )
            .order_by(ExchangeOrder.updated_at.asc())
            .limit(max(1, min(limit, 50)))
            .all()
        )

        swept = 0
        for orphan in candidates:
            if str(orphan.exchange_order_id) not in open_ids:
                continue
            siblings = self._find_oco_siblings(db, orphan)
            filled_sib = next(
                (
                    s
                    for s in siblings
                    if getattr(s, "status", None) == OrderStatusEnum.FILLED
                ),
                None,
            )
            if not filled_sib:
                continue
            if orphan.status == OrderStatusEnum.FILLED:
                continue
            logger.info(
                "OCO sweep: orphan %s (%s) still open; sibling %s is FILLED — cancelling",
                orphan.exchange_order_id,
                orphan.order_role or orphan.order_type,
                filled_sib.exchange_order_id,
            )
            try:
                if self._cancel_oco_sibling(
                    db, filled_sib, force_live_cancel=True
                ):
                    swept += 1
            except Exception as err:
                logger.warning(
                    "OCO sweep cancel failed for filled=%s orphan=%s: %s",
                    filled_sib.exchange_order_id,
                    orphan.exchange_order_id,
                    err,
                    exc_info=True,
                )
        return swept

    def _cancel_oco_sibling(
        self,
        db: Session,
        filled_order: "ExchangeOrder",
        *,
        force_live_cancel: bool = False,
    ) -> bool:
        """Cancel the sibling order in an OCO pair when one leg is FILLED.

        Linkage: ``oco_group_id`` and/or same ``parent_order_id`` with opposite
        role (TAKE_PROFIT ↔ STOP_LOSS). Cancels via advanced cancel when the
        sibling is a trigger/protection order (pass ``order_type``).

        Returns:
            bool: True if sibling cancelled / already cancelled / already gone;
            False if no sibling or live cancel failed (caller may fall back).
        """
        try:
            from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
            from app.services.brokers.crypto_com_trade import trade_client

            recent_fill = is_recent_exchange_event(filled_order) or force_live_cancel

            all_siblings = self._find_oco_siblings(db, filled_order)
            if not all_siblings:
                logger.debug(
                    "OCO: No sibling found for %s (oco_group_id=%s parent_order_id=%s)",
                    filled_order.exchange_order_id,
                    getattr(filled_order, "oco_group_id", None),
                    getattr(filled_order, "parent_order_id", None),
                )
                return False

            # Never cancel a sibling that already filled.
            for sib in all_siblings:
                if getattr(sib, "status", None) == OrderStatusEnum.FILLED:
                    logger.info(
                        "OCO: sibling %s already FILLED — not cancelling (filled=%s)",
                        sib.exchange_order_id,
                        filled_order.exchange_order_id,
                    )
                    return True

            active_sibling = next(
                (s for s in all_siblings if self._is_active_oco_sibling_status(s.status)),
                None,
            )

            if not active_sibling:
                cancelled_sibling = next(
                    (
                        s
                        for s in all_siblings
                        if getattr(s, "status", None) == OrderStatusEnum.CANCELLED
                    ),
                    None,
                )
                if cancelled_sibling:
                    logger.info(
                        "✅ OCO: Sibling %s order %s was already CANCELLED",
                        cancelled_sibling.order_role,
                        cancelled_sibling.exchange_order_id,
                    )
                    if not recent_fill:
                        logger.info(
                            "Skipping OCO already-cancelled Telegram for historical fill %s",
                            filled_order.exchange_order_id,
                        )
                        return True
                    try:
                        self._send_oco_cancellation_notification(
                            db,
                            filled_order,
                            cancelled_sibling,
                            was_already_cancelled=True,
                        )
                    except Exception as notify_err:
                        logger.warning(
                            "Failed to send OCO notification for already-cancelled sibling: %s",
                            notify_err,
                        )
                    return True

                statuses = [
                    f"{s.exchange_order_id}: {s.status}" for s in all_siblings
                ]
                logger.warning(
                    "OCO: No active sibling for %s (oco=%s parent=%s). "
                    "Found %d sibling(s) but none active: %s",
                    filled_order.exchange_order_id,
                    getattr(filled_order, "oco_group_id", None),
                    getattr(filled_order, "parent_order_id", None),
                    len(all_siblings),
                    ", ".join(statuses),
                )
                return False

            sibling = active_sibling
            cancel_type = self._cancel_order_type_for_sibling(sibling)

            # Always attempt live cancel for ACTIVE siblings (late advanced-TP detection
            # previously left orphan SLs on exchange when only DB was healed).
            # Suppress Telegram for historical / sweeper-driven cancels.
            send_telegram = bool(is_recent_exchange_event(filled_order)) and not force_live_cancel

            from app.services.brokers.crypto_com_trade import looks_like_exchange_list_id
            from app.services.live_trading_gate import (  # pyright: ignore[reportMissingImports]
                LiveTradingBlockedError,
                assert_exchange_mutation_allowed,
            )

            # Native exchange OCO: sibling is often already cancelled by the exchange when
            # one leg fills. Soft-check before forcing another cancel (avoids noise).
            oco_gid = getattr(filled_order, "oco_group_id", None) or getattr(
                sibling, "oco_group_id", None
            )
            if looks_like_exchange_list_id(oco_gid) and sibling.exchange_order_id:
                try:
                    detail = trade_client.get_order_detail(str(sibling.exchange_order_id))
                    status_raw = None
                    if isinstance(detail, dict):
                        res = detail.get("result") if isinstance(detail.get("result"), dict) else detail
                        if isinstance(res, dict):
                            status_raw = res.get("status") or res.get("order_status")
                    status_u = str(status_raw or "").upper()
                    already_gone = detail is None or status_u in {
                        "CANCELLED",
                        "CANCELED",
                        "REJECTED",
                        "EXPIRED",
                    }
                    if already_gone:
                        logger.info(
                            "OCO: native list_id=%s sibling %s already %s on exchange — soft cancel",
                            oco_gid,
                            sibling.exchange_order_id,
                            status_u or "absent",
                        )
                        sibling.status = OrderStatusEnum.CANCELLED
                        sibling.updated_at = datetime.now(timezone.utc)
                        db.add(sibling)
                        db.commit()
                        if send_telegram:
                            try:
                                self._send_oco_cancellation_notification(
                                    db,
                                    filled_order,
                                    sibling,
                                    was_already_cancelled=True,
                                )
                            except Exception as notify_err:
                                logger.warning(
                                    "Failed OCO soft-cancel Telegram: %s", notify_err
                                )
                        return True
                except Exception as soft_err:
                    logger.debug(
                        "OCO soft-check failed for sibling %s: %s",
                        sibling.exchange_order_id,
                        soft_err,
                    )

            try:
                assert_exchange_mutation_allowed(
                    db,
                    "cancel_oco_sibling",
                    getattr(filled_order, "symbol", None),
                    None,
                )
            except LiveTradingBlockedError:
                logger.info(
                    "[HANDOFF_TOTAL] exchange_sync skipped action=cancel_oco_sibling symbol=%s",
                    getattr(filled_order, "symbol", None),
                )
                return False

            logger.info(
                "🔄 OCO: Cancelling sibling %s order %s (type=%s) after filled %s %s "
                "(oco=%s parent=%s force_live=%s)",
                sibling.order_role,
                sibling.exchange_order_id,
                cancel_type,
                filled_order.order_role,
                filled_order.exchange_order_id,
                getattr(filled_order, "oco_group_id", None),
                getattr(filled_order, "parent_order_id", None),
                force_live_cancel,
            )

            result = trade_client.cancel_order(
                sibling.exchange_order_id, order_type=cancel_type
            )

            # If first attempt used a non-conditional type and failed, retry as advanced.
            if (
                "error" in result
                and cancel_type
                and str(cancel_type).upper()
                not in {
                    "STOP_LOSS",
                    "STOP_LIMIT",
                    "TAKE_PROFIT",
                    "TAKE_PROFIT_LIMIT",
                }
            ):
                role = (getattr(sibling, "order_role", None) or "").upper()
                retry_type = (
                    "STOP_LIMIT"
                    if role == "STOP_LOSS"
                    else "TAKE_PROFIT_LIMIT"
                    if role == "TAKE_PROFIT"
                    else None
                )
                if retry_type:
                    logger.warning(
                        "OCO: cancel with type=%s failed (%s); retrying as %s",
                        cancel_type,
                        result.get("error"),
                        retry_type,
                    )
                    result = trade_client.cancel_order(
                        sibling.exchange_order_id, order_type=retry_type
                    )

            already_gone = self._cancel_result_indicates_already_gone(result)
            if "error" not in result or already_gone:
                sibling.status = OrderStatusEnum.CANCELLED
                sibling.updated_at = datetime.utcnow()
                db.commit()
                if already_gone:
                    logger.info(
                        "✅ OCO: Sibling %s already gone on exchange; marked CANCELLED in DB",
                        sibling.exchange_order_id,
                    )
                else:
                    logger.info(
                        "✅ OCO: Cancelled %s order %s",
                        sibling.order_role,
                        sibling.exchange_order_id,
                    )

                if send_telegram:
                    try:
                        self._send_oco_cancellation_notification(
                            db,
                            filled_order,
                            sibling,
                            was_already_cancelled=already_gone,
                        )
                    except Exception as tg_err:
                        logger.warning(
                            "Failed to send OCO notification: %s",
                            tg_err,
                            exc_info=True,
                        )
                elif not is_recent_exchange_event(filled_order):
                    logger.info(
                        "OCO: cancelled sibling %s for historical fill %s (no Telegram)",
                        sibling.exchange_order_id,
                        filled_order.exchange_order_id,
                    )
                return True

            error_msg = result.get("error", "Unknown error")
            logger.error(
                "❌ OCO: Failed to cancel sibling order %s: %s",
                sibling.exchange_order_id,
                error_msg,
            )
            if send_telegram:
                try:
                    from app.services.telegram_notifier import telegram_notifier

                    telegram_notifier.send_message(
                        f"⚠️ <b>OCO: Cancellation Failed</b>\n\n"
                        f"📊 Symbol: <b>{sibling.symbol}</b>\n"
                        f"🎯 Filled Order: {filled_order.order_role} "
                        f"({filled_order.exchange_order_id})\n"
                        f"❌ Failed to Cancel: {sibling.order_role} "
                        f"({sibling.exchange_order_id})\n"
                        f"🔗 OCO Group: <code>{filled_order.oco_group_id}</code>\n"
                        f"🔗 Parent: <code>{filled_order.parent_order_id}</code>\n\n"
                        f"❌ Error: {error_msg}\n\n"
                        f"⚠️ Will try fallback method to cancel the order."
                    )
                except Exception as tg_err:
                    logger.warning(
                        "Failed to send OCO error notification: %s", tg_err
                    )
            return False

        except Exception as e:
            logger.error(
                "❌ OCO: Error cancelling sibling order: %s", e, exc_info=True
            )
            return False

    def _maybe_create_sl_tp_after_history_sync(
        self,
        db: Session,
        order: ExchangeOrder,
        *,
        symbol: str,
        side: str,
        filled_price: float,
        filled_qty: float,
        order_id: str,
        order_filled_time: Optional[datetime],
        order_type_label: str,
    ) -> Optional[dict]:
        """Create SL/TP for a synced fill when gate allows (replaces dead event-bus publish)."""
        now_utc = datetime.now(timezone.utc)
        allowed, reason = should_auto_create_sl_tp_on_sync(
            db, order, order_filled_time, now_utc
        )
        if not allowed:
            if reason == "external_order_no_timestamp":
                logger.info(
                    "⏰ Skipping SL/TP creation for order %s (%s): "
                    "Order was not created by this system (no trade_signal_id) and no timestamp available. "
                    "Likely an old/synced order that doesn't need automatic SL/TP creation.",
                    order_id,
                    symbol,
                )
            elif reason.startswith("external_order_old_fill"):
                hours = reason.split("_")[-1].rstrip("h")
                logger.info(
                    "⏰ Skipping SL/TP creation for order %s (%s): "
                    "Order was not created by this system and was filled %s hours ago (limit: 1 hour). "
                    "This is likely an old order synced from Crypto.com history.",
                    order_id,
                    symbol,
                    hours,
                )
            elif reason == "already_protected":
                logger.debug(
                    "Skipping SL/TP creation for order %s (%s): already has active SL and TP",
                    order_id,
                    symbol,
                )
            else:
                logger.info(
                    "⏰ Skipping SL/TP creation for order %s (%s): %s",
                    order_id,
                    symbol,
                    reason,
                )
            return None

        logger.info(
            "Creating SL/TP for %s order %s (%s): side=%s, qty=%s, gate_reason=%s",
            order_type_label,
            order_id,
            symbol,
            side,
            filled_qty,
            reason,
        )
        try:
            result = self._create_sl_tp_for_filled_order(
                db=db,
                symbol=symbol,
                side=side,
                filled_price=filled_price,
                filled_qty=filled_qty,
                order_id=order_id,
                source="exchange_sync",
            )
            if sl_tp_creation_result_ok(result):
                logger.info(
                    "✅ SL/TP created successfully for order %s (%s)",
                    order_id,
                    symbol,
                )
            else:
                logger.error(
                    "❌ SL/TP creation failed for order %s (%s): result=%s",
                    order_id,
                    symbol,
                    result,
                )
            return result
        except Exception as sl_tp_err:
            logger.error(
                "❌ SL/TP creation exception for order %s (%s): %s",
                order_id,
                symbol,
                sl_tp_err,
                exc_info=True,
            )
            return None
    
    def _create_sl_tp_for_filled_order(
        self,
        db: Session,
        symbol: str,
        side: str,
        filled_price: float,
        filled_qty: float,
        order_id: str,
        force: bool = False,
        source: str = "auto",
        strict_percentages: bool = False,
        sl_price_override: Optional[float] = None,
        tp_price_override: Optional[float] = None,
        skip_gate: bool = False,
    ):
        """Create SL and TP orders automatically when a LIMIT or MARKET order is filled.
        When skip_gate=True, do not call assert_exchange_mutation_allowed (caller must gate).
        Returns dict with sl_result, tp_result for all code paths."""
        from app.models.watchlist import WatchlistItem
        from app.api.routes_signals import calculate_stop_loss_and_take_profit

        default_result = {"sl_result": {"order_id": None, "error": None}, "tp_result": {"order_id": None, "error": None}}

        if not filled_price or filled_qty <= 0:
            logger.warning(f"Cannot create SL/TP for order {order_id}: invalid price ({filled_price}) or quantity ({filled_qty})")
            return default_result

        # Manual/explicit TP/SL overrides must be validated early (fail fast with clear errors).
        # This is ONLY about the user-provided numbers; it does not change auth/client behavior.
        side_upper = (side or "").upper()
        if side_upper not in {"BUY", "SELL"}:
            raise ValueError(f"Invalid side '{side}'. Expected BUY or SELL.")
        try:
            filled_price_f = float(filled_price)
        except Exception:
            raise ValueError(f"Invalid filled_price '{filled_price}'. Must be a number.")

        def _validate_override_price(name: str, value: Optional[float]) -> Optional[float]:
            if value is None:
                return None
            try:
                v = float(value)
            except Exception:
                raise ValueError(f"Invalid {name} '{value}'. Must be a number.")
            if not (v > 0):
                raise ValueError(f"Invalid {name} '{v}'. Must be > 0.")
            return v

        sl_price_override_f = _validate_override_price("sl_price", sl_price_override)
        tp_price_override_f = _validate_override_price("tp_price", tp_price_override)

        if sl_price_override_f is not None:
            if side_upper == "BUY" and not (sl_price_override_f < filled_price_f):
                raise ValueError(
                    f"Invalid sl_price for BUY: sl_price must be < filled_price "
                    f"(sl_price={sl_price_override_f}, filled_price={filled_price_f})."
                )
            if side_upper == "SELL" and not (sl_price_override_f > filled_price_f):
                raise ValueError(
                    f"Invalid sl_price for SELL: sl_price must be > filled_price "
                    f"(sl_price={sl_price_override_f}, filled_price={filled_price_f})."
                )
        if tp_price_override_f is not None:
            if side_upper == "BUY" and not (tp_price_override_f > filled_price_f):
                raise ValueError(
                    f"Invalid tp_price for BUY: tp_price must be > filled_price "
                    f"(tp_price={tp_price_override_f}, filled_price={filled_price_f})."
                )
            if side_upper == "SELL" and not (tp_price_override_f < filled_price_f):
                raise ValueError(
                    f"Invalid tp_price for SELL: tp_price must be < filled_price "
                    f"(tp_price={tp_price_override_f}, filled_price={filled_price_f})."
                )
        
        # When skip_gate=True, caller (ProtectionOrderService) has already gated and checked idempotency. Do creation only.
        if skip_gate:
            return self._create_sl_tp_impl(
                db=db,
                symbol=symbol,
                side_upper=side_upper,
                filled_price_f=filled_price_f,
                filled_qty=filled_qty,
                order_id=order_id,
                source=source,
                strict_percentages=strict_percentages,
                sl_price_override_f=sl_price_override_f,
                tp_price_override_f=tp_price_override_f,
            )
        
        # If any protection order has already been FILLED, do not recreate protection orders.
        existing_sl_tp_filled = db.query(ExchangeOrder).filter(
            ExchangeOrder.parent_order_id == order_id,
            ExchangeOrder.order_role.in_(["STOP_LOSS", "TAKE_PROFIT"]),
            ExchangeOrder.status == OrderStatusEnum.FILLED,
        ).count()
        if existing_sl_tp_filled > 0:
            logger.info(
                f"⚠️ SL/TP already FILLED for order {order_id} ({symbol}): found {existing_sl_tp_filled} filled protection order(s). "
                f"Skipping SL/TP creation."
            )
            return default_result

        # Cross-process lock: in-memory locks do not work across backend-aws / canary workers.
        lock_acquired = try_acquire_sl_tp_creation_lock(db, order_id)
        if not lock_acquired:
            existing_sl = get_active_protection_order(db, order_id, "STOP_LOSS")
            existing_tp = get_active_protection_order(db, order_id, "TAKE_PROFIT")
            if existing_sl or existing_tp:
                logger.info(
                    "🚫 BLOCKED: SL/TP creation already in progress for order %s (%s). "
                    "Reusing existing protection (SL=%s, TP=%s).",
                    order_id,
                    symbol,
                    existing_sl.exchange_order_id if existing_sl else None,
                    existing_tp.exchange_order_id if existing_tp else None,
                )
                return {
                    "symbol": symbol,
                    "order_id": order_id,
                    "source": source,
                    "status": "already_protected",
                    "sl_result": {
                        "order_id": existing_sl.exchange_order_id if existing_sl else None,
                        "error": None,
                    },
                    "tp_result": {
                        "order_id": existing_tp.exchange_order_id if existing_tp else None,
                        "error": None,
                    },
                    "sl_price": _protection_order_price(existing_sl) if existing_sl else None,
                    "tp_price": _protection_order_price(existing_tp) if existing_tp else None,
                }
            logger.warning(
                "🚫 BLOCKED: SL/TP creation already in progress for order %s (%s). "
                "Skipping to prevent duplicate creation.",
                order_id,
                symbol,
            )
            return default_result

        # Sync open orders so the single-path service sees latest state before idempotency check
        try:
            logger.info(f"🔄 Syncing open orders from exchange before creating SL/TP for {symbol} order {order_id}")
            self.sync_open_orders(db)
            logger.info(f"✅ Open orders synced successfully")
        except Exception as sync_err:
            logger.warning(f"⚠️ Failed to sync open orders before creating SL/TP: {sync_err}. Continuing with database check only.")
        db.expire_all()

        logger.info(f"Creating SL/TP for {symbol} order {order_id}: filled_price={filled_price}, filled_qty={filled_qty}")

        from app.services.live_trading_gate import get_live_trading  # pyright: ignore[reportMissingImports]

        try:
            impl_result = self._create_sl_tp_impl(
                db=db,
                symbol=symbol,
                side_upper=side_upper,
                filled_price_f=filled_price_f,
                filled_qty=filled_qty,
                order_id=order_id,
                source=source,
                strict_percentages=strict_percentages,
                sl_price_override_f=sl_price_override_f,
                tp_price_override_f=tp_price_override_f,
            )
        finally:
            release_sl_tp_creation_lock(db, order_id)

        sl_result = impl_result.get("sl_result")
        tp_result = impl_result.get("tp_result")
        sl_order_id = (sl_result or {}).get("order_id")
        tp_order_id = (tp_result or {}).get("order_id")
        sl_price = impl_result.get("sl_price")
        tp_price = impl_result.get("tp_price")
        oco_group_id = impl_result.get("oco_group_id")
        skip_tp_creation = impl_result.get("skip_tp_creation", False)
        skip_tp_reason = impl_result.get("skip_tp_reason")
        live_trading = get_live_trading(db)
        sl_order_error = (sl_result or {}).get("error")
        tp_order_error = (tp_result or {}).get("error")

        sl_newly_created = bool(impl_result.get("sl_newly_created"))
        tp_newly_created = bool(impl_result.get("tp_newly_created"))

        # Idempotent path: another process already created SL/TP — do not re-notify Telegram.
        if impl_result.get("status") == "already_protected":
            logger.info(
                "📢 Skipping SL/TP Telegram for order %s (%s): already protected (idempotent).",
                order_id,
                symbol,
            )
            return {
                "symbol": symbol,
                "order_id": order_id,
                "source": source,
                "status": "already_protected",
                "live_trading": bool(live_trading),
                "oco_group_id": oco_group_id,
                "sl_price": float(sl_price) if sl_price is not None else None,
                "tp_price": float(tp_price) if tp_price is not None else None,
                "sl_result": sl_result,
                "tp_result": tp_result,
                "skip_tp_creation": bool(skip_tp_creation),
                "skip_tp_reason": skip_tp_reason,
            }

        # Prepare for Telegram notification
        watchlist_item = db.query(WatchlistItem).filter(WatchlistItem.symbol == symbol).first()
        sl_tp_mode = (getattr(watchlist_item, "sl_tp_mode", None) or "conservative").lower() if watchlist_item else "conservative"
        _sl_pct = getattr(watchlist_item, "sl_percentage", None) if watchlist_item else None
        _tp_pct = getattr(watchlist_item, "tp_percentage", None) if watchlist_item else None
        effective_sl_pct = abs(float(_sl_pct)) if (_sl_pct is not None and float(_sl_pct) > 0) else 3.0
        effective_tp_pct = abs(float(_tp_pct)) if (_tp_pct is not None and float(_tp_pct) > 0) else 3.0

        # Send Telegram only when a protection leg was newly created this call.
        # Reusing an existing SL while TP retries fail was re-announcing the same SL every
        # few minutes (production evidence: identical SL order IDs ~every 5–6 minutes).
        try:
            from app.services.telegram_notifier import telegram_notifier
            from app.services.telegram_event_dedup import claim_telegram_event

            notification_sent_key = f"sl_tp_notification_sent_{order_id}"
            if not hasattr(self, '_sl_tp_notification_sent'):
                self._sl_tp_notification_sent = {}
            if notification_sent_key in self._sl_tp_notification_sent:
                notification_timestamp = self._sl_tp_notification_sent[notification_sent_key]
                time_since_notification = time.time() - notification_timestamp
                if time_since_notification < 300:  # 5 minutes in-process guard
                    logger.info(
                        f"📢 Notification already sent for order {order_id} ({symbol}) "
                        f"{time_since_notification:.1f}s ago. Skipping duplicate notification."
                    )
                    return {
                        "symbol": symbol,
                        "order_id": order_id,
                        "source": source,
                        "live_trading": bool(live_trading),
                        "oco_group_id": oco_group_id,
                        "sl_price": float(sl_price) if sl_price is not None else None,
                        "tp_price": float(tp_price) if tp_price is not None else None,
                        "sl_result": sl_result,
                        "tp_result": tp_result,
                        "skip_tp_creation": bool(skip_tp_creation),
                        "skip_tp_reason": skip_tp_reason,
                    }

            db.expire_all()  # Force refresh to see latest orders
            existing_sl_check = db.query(ExchangeOrder).filter(
                ExchangeOrder.parent_order_id == order_id,
                ExchangeOrder.order_role == "STOP_LOSS",
                ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
            ).first()
            existing_tp_check = db.query(ExchangeOrder).filter(
                ExchangeOrder.parent_order_id == order_id,
                ExchangeOrder.order_role == "TAKE_PROFIT",
                ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
            ).first()

            # No new protection legs this call → never re-announce existing SL/TP.
            if not sl_newly_created and not tp_newly_created:
                logger.info(
                    "📢 Skipping SL/TP Telegram for order %s (%s): no newly created protection "
                    "(sl_id=%s tp_id=%s skip_tp=%s).",
                    order_id,
                    symbol,
                    sl_order_id,
                    tp_order_id,
                    skip_tp_reason,
                )
                return {
                    "symbol": symbol,
                    "order_id": order_id,
                    "source": source,
                    "status": "already_protected" if (existing_sl_check or existing_tp_check) else "no_new_protection",
                    "live_trading": bool(live_trading),
                    "oco_group_id": oco_group_id,
                    "sl_price": float(sl_price) if sl_price is not None else None,
                    "tp_price": float(tp_price) if tp_price is not None else None,
                    "sl_result": sl_result,
                    "tp_result": tp_result,
                    "skip_tp_creation": bool(skip_tp_creation),
                    "skip_tp_reason": skip_tp_reason,
                }

            # If orders failed, send error notification with detailed error messages
            if not sl_order_id and not tp_order_id and live_trading:
                # Build detailed error message
                error_details = []
                if sl_order_error:
                    error_details.append(f"SL: {sl_order_error}")
                if tp_order_error:
                    error_details.append(f"TP: {tp_order_error}")
                error_summary = " | ".join(error_details) if error_details else "Unknown error"
                
                # Format prices with appropriate decimal precision for display
                if filled_price >= 100:
                    price_fmt = "{:.4f}"
                elif filled_price >= 1:
                    price_fmt = "{:.6f}"
                else:
                    price_fmt = "{:.8f}"

                if claim_telegram_event(
                    db,
                    f"sl_tp_failed:{order_id}",
                    symbol=symbol,
                    ttl_minutes=6 * 60,
                    action="sl_tp_failed",
                ):
                    telegram_notifier.send_message(
                        f"⚠️ <b>SL/TP ORDER CREATION FAILED</b>\n\n"
                        f"📊 Symbol: <b>{symbol}</b>\n"
                        f"📋 Order ID: {order_id}\n"
                        f"💵 Filled Price: ${price_fmt.format(filled_price)}\n"
                        f"📦 Quantity: {filled_qty}\n"
                        f"🔴 SL Price: ${price_fmt.format(sl_price)}\n"
                        f"🟢 TP Price: ${price_fmt.format(tp_price)}\n"
                        f"❌ Error: {error_summary}\n\n"
                        f"Por favor revisa los logs del backend para más detalles."
                    )
                    logger.warning(
                        f"SL/TP orders failed for {symbol} order {order_id} - "
                        f"sent error notification to Telegram: {error_summary}"
                    )
                else:
                    logger.info(
                        "SL/TP failure Telegram suppressed (dedup) order=%s symbol=%s",
                        order_id,
                        symbol,
                    )
            else:
                # Send normal notification if at least one order succeeded or in DRY_RUN mode
                # Determine SL/TP sides for clarity in Telegram message
                sl_side_for_tp = "SELL" if side == "BUY" else "BUY"  # SL is opposite of original order
                tp_side_for_tp = "SELL" if side == "BUY" else "BUY"  # TP is opposite of original order
                
                # Get trigger and ref prices from the orders if available
                sl_trigger_from_order = sl_price  # trigger_price should equal sl_price
                # TP is now a LIMIT order (not TAKE_PROFIT_LIMIT), so no trigger_price needed
                tp_trigger_from_order = tp_price  # For LIMIT orders, price is the limit price
                sl_ref_from_order = sl_price  # ref_price should equal sl_price (trigger_price)
                
                # Always send notification, even if one order failed
                sl_price_f = float(sl_price) if sl_price is not None else 0.0
                tp_price_f = float(tp_price) if tp_price is not None else 0.0
                if sl_price_f <= 0 and existing_sl_check:
                    sl_price_f = _protection_order_price(existing_sl_check) or sl_price_f
                if tp_price_f <= 0 and existing_tp_check:
                    tp_price_f = _protection_order_price(existing_tp_check) or tp_price_f
                if (sl_order_id or tp_order_id) and (sl_price_f <= 0 or tp_price_f <= 0):
                    logger.warning(
                        "📢 Skipping SL/TP Telegram for order %s (%s): missing valid SL/TP prices "
                        "(sl_price=%s, tp_price=%s).",
                        order_id,
                        symbol,
                        sl_price_f,
                        tp_price_f,
                    )
                    return {
                        "symbol": symbol,
                        "order_id": order_id,
                        "source": source,
                        "live_trading": bool(live_trading),
                        "oco_group_id": oco_group_id,
                        "sl_price": sl_price_f if sl_price_f > 0 else None,
                        "tp_price": tp_price_f if tp_price_f > 0 else None,
                        "sl_result": sl_result,
                        "tp_result": tp_result,
                        "skip_tp_creation": bool(skip_tp_creation),
                        "skip_tp_reason": skip_tp_reason,
                    }
                # Distinct claim keys so a later TP-only (or SL-only) backfill can still notify
                # once, instead of being suppressed by the original paired SL/TP announcement.
                if sl_newly_created and tp_newly_created:
                    claim_key = f"sl_tp_created:{order_id}"
                elif tp_newly_created:
                    claim_key = f"sl_tp_created:{order_id}:tp"
                elif sl_newly_created:
                    claim_key = f"sl_tp_created:{order_id}:sl"
                else:
                    claim_key = f"sl_tp_created:{order_id}"
                if not claim_telegram_event(
                    db,
                    claim_key,
                    symbol=symbol,
                    ttl_minutes=7 * 24 * 60,
                    action="sl_tp_created",
                ):
                    logger.info(
                        "📢 Skipping SL/TP Telegram for order %s (%s): already claimed %s.",
                        order_id,
                        symbol,
                        claim_key,
                    )
                    return {
                        "symbol": symbol,
                        "order_id": order_id,
                        "source": source,
                        "status": "already_notified",
                        "live_trading": bool(live_trading),
                        "oco_group_id": oco_group_id,
                        "sl_price": sl_price_f if sl_price_f > 0 else None,
                        "tp_price": tp_price_f if tp_price_f > 0 else None,
                        "sl_result": sl_result,
                        "tp_result": tp_result,
                        "skip_tp_creation": bool(skip_tp_creation),
                        "skip_tp_reason": skip_tp_reason,
                    }
                result = telegram_notifier.send_sl_tp_orders(
                    symbol=symbol,
                    sl_price=sl_price_f,
                    tp_price=tp_price_f,
                    quantity=filled_qty,
                    mode=sl_tp_mode,
                    sl_order_id=str(sl_order_id) if sl_order_id else None,
                    tp_order_id=str(tp_order_id) if tp_order_id else None,
                    original_order_id=order_id,
                    sl_side=sl_side_for_tp,  # Add SL side (SELL for BUY orders, BUY for SELL orders)
                    tp_side=tp_side_for_tp,  # Add TP side (SELL for BUY orders, BUY for SELL orders)
                    entry_price=filled_price,  # Add entry price for profit/loss calculation
                    sl_trigger_price=sl_trigger_from_order,  # Add SL trigger price for verification
                    tp_trigger_price=tp_trigger_from_order,  # Add TP limit price (for LIMIT order, not TAKE_PROFIT_LIMIT)
                    sl_ref_price=sl_ref_from_order,  # Add SL ref price for verification
                    sl_percentage=effective_sl_pct,  # Add SL percentage for strategy display
                    tp_percentage=effective_tp_pct,  # Add TP percentage for strategy display
                    original_order_side=side,  # Add original order side for correct profit/loss calculation
                    sl_newly_created=sl_newly_created,
                    tp_newly_created=tp_newly_created,
                )
                if result:
                    logger.info(f"✅ Sent Telegram notification for SL/TP orders: {symbol} - SL: {sl_order_id}, TP: {tp_order_id}")
                    # Mark notification as sent to prevent duplicates
                    self._sl_tp_notification_sent[notification_sent_key] = time.time()
                else:
                    logger.error(f"❌ Failed to send Telegram notification for SL/TP orders: {symbol} - SL: {sl_order_id}, TP: {tp_order_id}")
        except Exception as telegram_err:
            logger.error(f"❌ Exception sending Telegram notification for SL/TP: {telegram_err}", exc_info=True)

        # Return a structured result for API endpoints / callers that want to surface details.
        # (Existing callers that ignore the return value remain compatible.)
        try:
            return {
                "symbol": symbol,
                "order_id": order_id,
                "source": source,
                "live_trading": bool(live_trading),
                "oco_group_id": oco_group_id,
                "sl_price": float(sl_price) if sl_price is not None else None,
                "tp_price": float(tp_price) if tp_price is not None else None,
                "sl_result": sl_result,
                "tp_result": tp_result,
                "skip_tp_creation": bool(skip_tp_creation),
                "skip_tp_reason": skip_tp_reason,
            }
        except Exception:
            return default_result

    def _create_sl_tp_impl(
        self,
        db: Session,
        symbol: str,
        side_upper: str,
        filled_price_f: float,
        filled_qty: float,
        order_id: str,
        source: str,
        strict_percentages: bool,
        sl_price_override_f: Optional[float],
        tp_price_override_f: Optional[float],
    ):
        """Actual SL/TP creation (only call when skip_gate=True from ProtectionOrderService). Uses tp_sl_order_creator."""
        from app.models.watchlist import WatchlistItem
        from app.services.tp_sl_order_creator import (
            create_stop_loss_order,
            create_take_profit_order,
            create_oco_protection_orders,
            is_native_oco_enabled,
            resolve_sltp_margin_context,
        )

        default_result = {"sl_result": {"order_id": None, "error": None}, "tp_result": {"order_id": None, "error": None}, "oco_group_id": None, "sl_price": None, "tp_price": None, "skip_tp_creation": False, "skip_tp_reason": None}
        existing_sl = get_active_protection_order(db, order_id, "STOP_LOSS")
        existing_tp = get_active_protection_order(db, order_id, "TAKE_PROFIT")
        if existing_sl and existing_tp:
            logger.info(
                "[SLTP_IDEMPOTENCY] parent=%s symbol=%s already has active SL=%s TP=%s — skipping creation",
                order_id,
                symbol,
                existing_sl.exchange_order_id,
                existing_tp.exchange_order_id,
            )
            return {
                **default_result,
                "status": "already_protected",
                "sl_result": {"order_id": existing_sl.exchange_order_id, "error": None},
                "tp_result": {"order_id": existing_tp.exchange_order_id, "error": None},
                "sl_price": _protection_order_price(existing_sl),
                "tp_price": _protection_order_price(existing_tp),
            }
        watchlist_item = db.query(WatchlistItem).filter(WatchlistItem.symbol == symbol).first()
        sl_tp_mode = (getattr(watchlist_item, "sl_tp_mode", None) or "conservative").lower() if watchlist_item else "conservative"
        sl_pct = 3.0 if sl_tp_mode == "conservative" else 2.0
        tp_pct = 3.0 if sl_tp_mode == "conservative" else 2.0
        if watchlist_item:
            _sl = getattr(watchlist_item, "sl_percentage", None)
            _tp = getattr(watchlist_item, "tp_percentage", None)
            if strict_percentages and _sl is not None and float(_sl) > 0:
                sl_pct = abs(float(_sl))
            elif _sl is not None and float(_sl) > 0:
                sl_pct = abs(float(_sl))
            if strict_percentages and _tp is not None and float(_tp) > 0:
                tp_pct = abs(float(_tp))
            elif _tp is not None and float(_tp) > 0:
                tp_pct = abs(float(_tp))
        if sl_price_override_f is not None:
            sl_price = sl_price_override_f
        else:
            if side_upper == "BUY":
                sl_price = filled_price_f * (1 - sl_pct / 100)
            else:
                sl_price = filled_price_f * (1 + sl_pct / 100)
        if tp_price_override_f is not None:
            tp_price = tp_price_override_f
        else:
            if side_upper == "BUY":
                tp_price = filled_price_f * (1 + tp_pct / 100)
            else:
                tp_price = filled_price_f * (1 - tp_pct / 100)
        sl_price = round(sl_price, 2) if sl_price >= 100 else round(sl_price, 4)
        tp_price = round(tp_price, 2) if tp_price >= 100 else round(tp_price, 4)

        is_margin, _leverage = resolve_sltp_margin_context(db, symbol)
        # Native OCO: both legs missing, spot only, feature flag on.
        # Avoids INSUFFICIENT_ACC_BALANCE from two standalone full-qty triggers.
        if (
            not existing_sl
            and not existing_tp
            and not is_margin
            and is_native_oco_enabled()
        ):
            oco_res = create_oco_protection_orders(
                db=db,
                symbol=symbol,
                side=side_upper,
                tp_price=tp_price,
                sl_price=sl_price,
                quantity=filled_qty,
                entry_price=filled_price_f,
                parent_order_id=order_id,
                dry_run=False,
                source=source,
            )
            if not oco_res.get("error") and (
                (oco_res.get("sl_result") or {}).get("order_id")
                or oco_res.get("oco_group_id")
            ):
                logger.info(
                    "[SLTP_NATIVE_OCO] parent=%s symbol=%s list_id=%s sl=%s tp=%s",
                    order_id,
                    symbol,
                    oco_res.get("oco_group_id"),
                    (oco_res.get("sl_result") or {}).get("order_id"),
                    (oco_res.get("tp_result") or {}).get("order_id"),
                )
                return {
                    "sl_result": oco_res.get("sl_result") or {"order_id": None, "error": None},
                    "tp_result": oco_res.get("tp_result") or {"order_id": None, "error": None},
                    "oco_group_id": oco_res.get("oco_group_id"),
                    "sl_price": sl_price,
                    "tp_price": tp_price,
                    "skip_tp_creation": False,
                    "skip_tp_reason": None,
                    "sl_newly_created": bool(oco_res.get("sl_newly_created")),
                    "tp_newly_created": bool(oco_res.get("tp_newly_created")),
                }
            logger.warning(
                "[SLTP_NATIVE_OCO] failed for parent=%s symbol=%s err=%s — falling back to dual create-order",
                order_id,
                symbol,
                oco_res.get("error"),
            )

        # When backfilling a missing leg, reuse the surviving leg's OCO group so Jarvis
        # and OCO checks do not treat the new TP/SL as an incomplete orphan group.
        existing_sl_oco = getattr(existing_sl, "oco_group_id", None) if existing_sl else None
        existing_tp_oco = getattr(existing_tp, "oco_group_id", None) if existing_tp else None
        if existing_sl_oco:
            oco_group_id = existing_sl_oco
        elif existing_tp_oco:
            oco_group_id = existing_tp_oco
        else:
            oco_group_id = f"oco_{order_id}_{int(time.time())}"
        sl_newly_created = False
        tp_newly_created = False
        skip_tp_creation = False
        skip_tp_reason = None
        if existing_sl:
            sl_result = {"order_id": existing_sl.exchange_order_id, "error": None}
            logger.info(
                "[SLTP_IDEMPOTENCY] Reusing existing SL %s for parent %s oco=%s",
                existing_sl.exchange_order_id,
                order_id,
                oco_group_id,
            )
            if existing_sl.oco_group_id != oco_group_id:
                existing_sl.oco_group_id = oco_group_id
                db.add(existing_sl)
                try:
                    db.commit()
                except Exception as heal_err:
                    logger.warning(
                        "[SLTP_IDEMPOTENCY] Failed to heal SL oco_group_id for parent %s: %s",
                        order_id,
                        heal_err,
                    )
                    db.rollback()
        else:
            sl_result = create_stop_loss_order(
                db=db,
                symbol=symbol,
                side=side_upper,
                sl_price=sl_price,
                quantity=filled_qty,
                entry_price=filled_price_f,
                parent_order_id=order_id,
                oco_group_id=oco_group_id,
                dry_run=False,
                source=source,
            )
            sl_newly_created = bool(sl_result.get("order_id")) and not sl_result.get("error")
        if existing_tp:
            tp_result = {"order_id": existing_tp.exchange_order_id, "error": None}
            logger.info(
                "[SLTP_IDEMPOTENCY] Reusing existing TP %s for parent %s oco=%s",
                existing_tp.exchange_order_id,
                order_id,
                oco_group_id,
            )
            if existing_tp.oco_group_id != oco_group_id:
                existing_tp.oco_group_id = oco_group_id
                db.add(existing_tp)
                try:
                    db.commit()
                except Exception as heal_err:
                    logger.warning(
                        "[SLTP_IDEMPOTENCY] Failed to heal TP oco_group_id for parent %s: %s",
                        order_id,
                        heal_err,
                    )
                    db.rollback()
        else:
            # Always place TP at the agreed calculated/watchlist price (no market widen/skip).
            tp_result = create_take_profit_order(
                db=db,
                symbol=symbol,
                side=side_upper,
                tp_price=tp_price,
                quantity=filled_qty,
                entry_price=filled_price_f,
                parent_order_id=order_id,
                oco_group_id=oco_group_id,
                dry_run=False,
                source=source,
            )
            tp_newly_created = bool(tp_result.get("order_id")) and not tp_result.get("error")
        # When SL already exists and nothing new was created, treat as idempotent
        # so callers do not re-send "SL/TP ORDERS CREATED".
        status = None
        if existing_sl and (existing_tp or skip_tp_creation) and not sl_newly_created and not tp_newly_created:
            status = "already_protected"
        return {
            "sl_result": sl_result,
            "tp_result": tp_result,
            "oco_group_id": oco_group_id,
            "sl_price": sl_price,
            "tp_price": tp_price,
            "skip_tp_creation": skip_tp_creation,
            "skip_tp_reason": skip_tp_reason,
            "sl_newly_created": sl_newly_created,
            "tp_newly_created": tp_newly_created,
            **({"status": status} if status else {}),
        }

    def _cancel_remaining_sl_tp(self, db: Session, symbol: str, executed_order_type: str, executed_order_id: str):
        """Cancel the remaining SL or TP order when one is executed"""
        try:
            # Determine which order type we need to cancel
            if executed_order_type.upper() in ('STOP_LIMIT', 'STOP_LOSS'):
                # If SL was executed, cancel TP
                target_order_type = 'TAKE_PROFIT_LIMIT'
            elif executed_order_type.upper() in ('TAKE_PROFIT_LIMIT', 'TAKE_PROFIT'):
                # If TP was executed, cancel SL
                target_order_type = 'STOP_LIMIT'
            else:
                return 0  # Not a SL/TP order
            
            # Get executed order to find parent_order_id and order_role
            executed_order = db.query(ExchangeOrder).filter(
                ExchangeOrder.exchange_order_id == executed_order_id
            ).first()
            recent_fill = bool(executed_order) and is_recent_exchange_event(executed_order)
            
            # Find open SL/TP orders of the opposite type for the same symbol
            # Try multiple strategies to find the matching SL/TP order:
            # 1. By parent_order_id (if both SL/TP share the same parent)
            # 2. By order_role (STOP_LOSS/TAKE_PROFIT) if available
            # 3. By symbol + order_type + similar creation time (fallback)
            target_orders = []
            
            # Strategy 1: Find by parent_order_id (most reliable)
            if executed_order and executed_order.parent_order_id:
                target_orders = db.query(ExchangeOrder).filter(
                    and_(
                        ExchangeOrder.symbol == symbol,
                        ExchangeOrder.parent_order_id == executed_order.parent_order_id,
                        ExchangeOrder.order_type == target_order_type,
                        ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED]),
                        ExchangeOrder.exchange_order_id != executed_order_id
                    )
                ).all()
                if target_orders:
                    logger.info(f"Found {len(target_orders)} {target_order_type} orders by parent_order_id {executed_order.parent_order_id}")
            
            # Strategy 2: Find by order_role if Strategy 1 didn't find anything
            # Also filter by side to ensure we get the correct sibling (for both BUY and SELL positions)
            if not target_orders and executed_order:
                # Determine target order_role based on executed order's order_role or order_type
                if executed_order.order_role:
                    if executed_order.order_role == "STOP_LOSS":
                        target_role = "TAKE_PROFIT"
                    elif executed_order.order_role == "TAKE_PROFIT":
                        target_role = "STOP_LOSS"
                    else:
                        target_role = None
                else:
                    # Infer from order_type
                    if executed_order_type.upper() == 'STOP_LIMIT':
                        target_role = "TAKE_PROFIT"
                    else:
                        target_role = "STOP_LOSS"
                
                if target_role:
                    # Filter by same side to ensure we get the correct sibling
                    # For BUY positions: SL/TP are both SELL orders
                    # For SELL positions (shorts): SL/TP are both BUY orders
                    target_orders = db.query(ExchangeOrder).filter(
                        and_(
                            ExchangeOrder.symbol == symbol,
                            ExchangeOrder.order_role == target_role,
                            ExchangeOrder.order_type == target_order_type,
                            ExchangeOrder.side == executed_order.side,  # Same side ensures correct position
                            ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED]),
                            ExchangeOrder.exchange_order_id != executed_order_id
                        )
                    ).all()
                    if target_orders:
                        logger.info(f"Found {len(target_orders)} {target_order_type} orders by order_role {target_role} and side {executed_order.side}")
            
            # Strategy 3: Find by symbol + order_type + similar creation time (fallback)
            # Filter by same side to ensure we get the correct sibling for both BUY and SELL positions
            if not target_orders and executed_order:
                # Look for orders created around the same time (within 5 minutes of the executed order)
                if executed_order.exchange_create_time:
                    from datetime import timedelta
                    time_window_start = executed_order.exchange_create_time - timedelta(minutes=5)
                    time_window_end = executed_order.exchange_create_time + timedelta(minutes=5)
                    
                    target_orders = db.query(ExchangeOrder).filter(
                        and_(
                            ExchangeOrder.symbol == symbol,
                            ExchangeOrder.order_type == target_order_type,
                            ExchangeOrder.side == executed_order.side,  # Same side ensures correct position
                            ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED]),
                            ExchangeOrder.exchange_order_id != executed_order_id,
                            ExchangeOrder.exchange_create_time >= time_window_start,
                            ExchangeOrder.exchange_create_time <= time_window_end
                        )
                    ).all()
                    if target_orders:
                        logger.info(f"Found {len(target_orders)} {target_order_type} orders by symbol + order_type + time window + side {executed_order.side}")
                elif executed_order.created_at:
                    # Fallback to created_at if exchange_create_time is not available
                    from datetime import timedelta
                    time_window_start = executed_order.created_at - timedelta(minutes=5)
                    time_window_end = executed_order.created_at + timedelta(minutes=5)
                    
                    target_orders = db.query(ExchangeOrder).filter(
                        and_(
                            ExchangeOrder.symbol == symbol,
                            ExchangeOrder.order_type == target_order_type,
                            ExchangeOrder.side == executed_order.side,  # Same side ensures correct position
                            ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED]),
                            ExchangeOrder.exchange_order_id != executed_order_id,
                            ExchangeOrder.created_at >= time_window_start,
                            ExchangeOrder.created_at <= time_window_end
                        )
                    ).all()
                    if target_orders:
                        logger.info(f"Found {len(target_orders)} {target_order_type} orders by symbol + order_type + time window + side {executed_order.side} (using created_at)")
            
            # Strategy 4: Final fallback - just find any open order of the target type for this symbol
            # Filter by same side to ensure we get the correct sibling for both BUY and SELL positions
            if not target_orders and executed_order:
                target_orders = db.query(ExchangeOrder).filter(
                    and_(
                        ExchangeOrder.symbol == symbol,
                        ExchangeOrder.order_type == target_order_type,
                        ExchangeOrder.side == executed_order.side,  # Same side ensures correct position
                        ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED]),
                    ExchangeOrder.exchange_order_id != executed_order_id
                )
            ).all()
                if target_orders:
                    logger.info(f"Found {len(target_orders)} {target_order_type} orders by symbol + order_type + side {executed_order.side} (fallback)")
            
            if not target_orders:
                # Log detailed debug info to help diagnose why target orders weren't found
                executed_order_details = {
                    'order_id': executed_order_id,
                    'symbol': symbol,
                    'parent_order_id': executed_order.parent_order_id if executed_order else None,
                    'order_role': executed_order.order_role if executed_order else None,
                    'order_type': executed_order.order_type if executed_order else None,
                }
                
                # Check if any TP/SL orders exist at all for this symbol (regardless of status)
                all_target_orders = db.query(ExchangeOrder).filter(
                    ExchangeOrder.symbol == symbol,
                    ExchangeOrder.order_type == target_order_type,
                    ExchangeOrder.exchange_order_id != executed_order_id
                ).all()
                
                if all_target_orders:
                    statuses = [f"{o.exchange_order_id}: {o.status.value if hasattr(o.status, 'value') else o.status} (parent={o.parent_order_id}, role={o.order_role})" for o in all_target_orders]
                    logger.warning(
                        f"No active {target_order_type} orders found to cancel for {symbol} after SL order {executed_order_id} was executed. "
                        f"Executed order details: {executed_order_details}. "
                        f"Found {len(all_target_orders)} {target_order_type} order(s) but none are active: {', '.join(statuses)}. "
                        f"(Tried strategies: parent_order_id, order_role, time window, symbol+type)"
                    )
                else:
                    logger.debug(f"No {target_order_type} orders found at all for {symbol} (tried parent_order_id, order_role, time window, and symbol+type)")
                return 0
            
            # Cancel each remaining order
            from app.utils.live_trading import get_live_trading_status
            live_trading = get_live_trading_status(db)
            
            for target_order in target_orders:
                try:
                    logger.info(f"Canceling {target_order_type} order {target_order.exchange_order_id} (remaining after {executed_order_type} {executed_order_id} was executed)")

                    # Historical fills: heal DB only — no live cancel_order, no Telegram.
                    if not recent_fill:
                        target_order.status = OrderStatusEnum.CANCELLED
                        target_order.updated_at = datetime.utcnow()
                        logger.info(
                            "Marked stale ACTIVE sibling %s CANCELLED for historical fill %s (no live cancel)",
                            target_order.exchange_order_id,
                            executed_order_id,
                        )
                        continue
                    
                    if not live_trading:
                        logger.info(f"DRY_RUN: Would cancel {target_order_type} order {target_order.exchange_order_id}")
                    else:
                        from app.services.live_trading_gate import assert_exchange_mutation_allowed, LiveTradingBlockedError  # pyright: ignore[reportMissingImports]
                        try:
                            assert_exchange_mutation_allowed(db, "cancel_sl_tp_after_exec", symbol, None)
                        except LiveTradingBlockedError:
                            logger.info("[HANDOFF_TOTAL] exchange_sync skipped action=cancel_sl_tp_after_exec symbol=%s order_id=%s", symbol, target_order.exchange_order_id)
                            continue
                        # Cancel via advanced endpoint when sibling is a protection/trigger order
                        cancel_type = self._cancel_order_type_for_sibling(target_order)
                        cancel_result = trade_client.cancel_order(
                            target_order.exchange_order_id, order_type=cancel_type
                        )
                        if "error" in cancel_result:
                            logger.warning(f"Failed to cancel {target_order_type} order {target_order.exchange_order_id}: {cancel_result.get('error')}")
                            continue
                        
                        # Update order status in database
                        target_order.status = OrderStatusEnum.CANCELLED
                        target_order.updated_at = datetime.utcnow()
                    
                    # Send detailed Telegram notification about cancellation
                    try:
                        from app.services.telegram_notifier import telegram_notifier
                        from datetime import timezone
                        
                        # Get executed order details
                        executed_order = db.query(ExchangeOrder).filter(
                            ExchangeOrder.exchange_order_id == executed_order_id
                        ).first()
                        
                        # For FILLED orders, prioritize avg_price (actual execution price) over price (limit/trigger price)
                        executed_price = executed_order.avg_price or executed_order.price or 0 if executed_order else 0
                        executed_qty = executed_order.quantity or executed_order.cumulative_quantity or 0 if executed_order else 0
                        executed_time = executed_order.exchange_update_time or executed_order.updated_at if executed_order else None
                        
                        cancelled_price = target_order.price or 0
                        cancelled_qty = target_order.quantity or 0
                        cancelled_time = datetime.now(timezone.utc)
                        
                        # Format times
                        executed_time_str = executed_time.strftime("%Y-%m-%d %H:%M:%S UTC") if executed_time else "N/A"
                        cancelled_time_str = cancelled_time.strftime("%Y-%m-%d %H:%M:%S UTC")
                        
                        # Calculate profit/loss if order was executed (for both TP and SL orders)
                        pnl_info = ""
                        if executed_order and executed_order.parent_order_id:
                            parent_order = db.query(ExchangeOrder).filter(
                                ExchangeOrder.exchange_order_id == executed_order.parent_order_id
                            ).first()
                            if parent_order:
                                entry_price = parent_order.avg_price or parent_order.price or 0
                                parent_side = parent_order.side.value if hasattr(parent_order.side, 'value') else str(parent_order.side)
                                
                                if entry_price > 0 and executed_price > 0 and executed_qty > 0:
                                    # Calculate profit/loss based on parent order side
                                    if parent_side == "BUY":
                                        # For BUY orders: profit if exit > entry, loss if exit < entry
                                        pnl_usd = (executed_price - entry_price) * executed_qty
                                        pnl_pct = ((executed_price - entry_price) / entry_price) * 100
                                    else:  # SELL (short position)
                                        # For SELL orders: profit if exit < entry, loss if exit > entry
                                        pnl_usd = (entry_price - executed_price) * executed_qty
                                        pnl_pct = ((entry_price - executed_price) / entry_price) * 100
                                    
                                    # Format profit/loss with emoji and sign
                                    if pnl_usd >= 0:
                                        pnl_emoji = "💰"
                                        pnl_label = "Profit"
                                    else:
                                        pnl_emoji = "💸"
                                        pnl_label = "Loss"
                                    
                                    pnl_info = (
                                        f"\n{pnl_emoji} <b>{pnl_label}:</b> ${abs(pnl_usd):,.2f} ({pnl_pct:+.2f}%)\n"
                                        f"   💵 Entry: ${entry_price:,.4f} → Exit: ${executed_price:,.4f}"
                                    )
                        
                        message = (
                            f"🔄 <b>SL/TP ORDER CANCELLED</b>\n\n"
                            f"📊 Symbol: <b>{symbol}</b>\n"
                            f"🔗 OCO Group ID: <code>{target_order.oco_group_id or 'N/A'}</code>\n\n"
                            f"✅ <b>Executed Order:</b>\n"
                            f"   🎯 Type: {executed_order_type}\n"
                            f"   📋 Role: {executed_order.order_role if executed_order else 'N/A'}\n"
                            f"   💵 Price: ${executed_price:.4f}\n"
                            f"   📦 Quantity: {executed_qty:.8f}\n"
                            f"   ⏰ Time: {executed_time_str}\n"
                            f"{pnl_info}\n"
                            f"❌ <b>Cancelled Order:</b>\n"
                            f"   🎯 Type: {target_order_type}\n"
                            f"   📋 Role: {target_order.order_role or 'N/A'}\n"
                            f"   💵 Price: ${cancelled_price:.4f}\n"
                            f"   📦 Quantity: {cancelled_qty:.8f}\n"
                            f"   ⏰ Cancelled: {cancelled_time_str}\n\n"
                            f"📋 Order IDs:\n"
                            f"   ✅ Executed: <code>{executed_order_id}</code>\n"
                            f"   ❌ Cancelled: <code>{target_order.exchange_order_id}</code>\n\n"
                            f"💡 <b>Reason:</b> {executed_order_type} order was executed, so the remaining {target_order_type} order has been automatically cancelled to prevent double execution."
                        )
                        
                        telegram_notifier.send_message(message)
                        logger.info(f"Sent detailed cancellation notification for {target_order_type} order: {target_order.exchange_order_id}")
                    except Exception as telegram_err:
                        logger.warning(f"Failed to send Telegram notification for cancellation: {telegram_err}", exc_info=True)
                    
                except Exception as e:
                    logger.error(f"Error canceling {target_order_type} order {target_order.exchange_order_id}: {e}")
            
            db.commit()
            cancelled_count = len(target_orders)
            logger.info(f"Cancelled {cancelled_count} remaining {target_order_type} order(s) for {symbol}")
            return cancelled_count
            
        except Exception as e:
            logger.error(f"Error in _cancel_remaining_sl_tp for {symbol}: {e}", exc_info=True)
            return 0
    
    def _notify_already_cancelled_sl_tp(self, db: Session, symbol: str, executed_order_type: str, executed_order_id: str):
        """Notify when an SL/TP order was already cancelled by the exchange (OCO auto-cancellation)"""
        try:
            # Determine which order type we're looking for
            if executed_order_type.upper() in ('STOP_LIMIT', 'STOP_LOSS'):
                # If SL was executed, check for cancelled TP
                target_order_type = 'TAKE_PROFIT_LIMIT'
            elif executed_order_type.upper() in ('TAKE_PROFIT_LIMIT', 'TAKE_PROFIT'):
                # If TP was executed, check for cancelled SL
                target_order_type = 'STOP_LIMIT'
            else:
                return  # Not a SL/TP order
            
            # Get executed order to find parent_order_id and order_role
            executed_order = db.query(ExchangeOrder).filter(
                ExchangeOrder.exchange_order_id == executed_order_id
            ).first()
            
            if not executed_order:
                return

            allow, reason = should_notify_oco_sibling_cancel(executed_order)
            if not allow:
                logger.info(
                    "Skipping already-cancelled SL/TP Telegram for %s (%s): %s",
                    symbol,
                    executed_order_id,
                    reason,
                )
                return
            
            # Find CANCELLED SL/TP orders of the opposite type for the same symbol
            # Try multiple strategies similar to _cancel_remaining_sl_tp
            target_orders = []
            
            # Strategy 1: Find by parent_order_id
            if executed_order.parent_order_id:
                target_orders = db.query(ExchangeOrder).filter(
                    and_(
                        ExchangeOrder.symbol == symbol,
                        ExchangeOrder.parent_order_id == executed_order.parent_order_id,
                        ExchangeOrder.order_type == target_order_type,
                        ExchangeOrder.status == OrderStatusEnum.CANCELLED,
                        ExchangeOrder.exchange_order_id != executed_order_id
                    )
                ).all()
                if target_orders:
                    logger.info(f"Found {len(target_orders)} already CANCELLED {target_order_type} orders by parent_order_id {executed_order.parent_order_id}")
            
            # Strategy 2: Find by order_role if Strategy 1 didn't find anything
            if not target_orders and executed_order.order_role:
                if executed_order.order_role == "STOP_LOSS":
                    target_role = "TAKE_PROFIT"
                elif executed_order.order_role == "TAKE_PROFIT":
                    target_role = "STOP_LOSS"
                else:
                    target_role = None
                
                if target_role:
                    target_orders = db.query(ExchangeOrder).filter(
                        and_(
                            ExchangeOrder.symbol == symbol,
                            ExchangeOrder.order_role == target_role,
                            ExchangeOrder.order_type == target_order_type,
                            ExchangeOrder.status == OrderStatusEnum.CANCELLED,
                            ExchangeOrder.exchange_order_id != executed_order_id
                        )
                    ).all()
                    if target_orders:
                        logger.info(f"Found {len(target_orders)} already CANCELLED {target_order_type} orders by order_role {target_role}")
            
            if not target_orders:
                logger.debug(f"No already CANCELLED {target_order_type} orders found for {symbol}")
                return
            
            # Send notification for already cancelled orders
            try:
                from app.services.telegram_notifier import telegram_notifier
                from datetime import timezone
                
                # Get executed order details
                executed_price = executed_order.avg_price or executed_order.price or 0
                executed_qty = executed_order.quantity or executed_order.cumulative_quantity or 0
                executed_time = executed_order.exchange_update_time or executed_order.updated_at
                executed_time_str = executed_time.strftime("%Y-%m-%d %H:%M:%S UTC") if executed_time else "N/A"
                
                # Get cancelled order details (use first one if multiple)
                cancelled_order = target_orders[0]
                cancelled_price = cancelled_order.price or 0
                cancelled_qty = cancelled_order.quantity or 0
                cancelled_time = cancelled_order.updated_at or cancelled_order.exchange_update_time
                cancelled_time_str = cancelled_time.strftime("%Y-%m-%d %H:%M:%S UTC") if cancelled_time else "N/A"
                
                # Calculate profit/loss if applicable
                pnl_info = ""
                if executed_order.parent_order_id:
                    parent_order = db.query(ExchangeOrder).filter(
                        ExchangeOrder.exchange_order_id == executed_order.parent_order_id
                    ).first()
                    if parent_order:
                        entry_price = parent_order.avg_price or parent_order.price or 0
                        parent_side = parent_order.side.value if hasattr(parent_order.side, 'value') else str(parent_order.side)
                        
                        if entry_price > 0 and executed_price > 0 and executed_qty > 0:
                            if parent_side == "BUY":
                                pnl_usd = (executed_price - entry_price) * executed_qty
                                pnl_pct = ((executed_price - entry_price) / entry_price) * 100
                            else:  # SELL
                                pnl_usd = (entry_price - executed_price) * executed_qty
                                pnl_pct = ((entry_price - executed_price) / entry_price) * 100
                            
                            if pnl_usd >= 0:
                                pnl_emoji = "💰"
                                pnl_label = "Profit"
                            else:
                                pnl_emoji = "💸"
                                pnl_label = "Loss"
                            
                            pnl_info = (
                                f"\n{pnl_emoji} <b>{pnl_label}:</b> ${abs(pnl_usd):,.2f} ({pnl_pct:+.2f}%)\n"
                                f"   💵 Entry: ${entry_price:,.4f} → Exit: ${executed_price:,.4f}"
                            )
                
                message = (
                    f"🔄 <b>SL/TP ORDER ALREADY CANCELLED</b>\n\n"
                    f"📊 Symbol: <b>{symbol}</b>\n\n"
                    f"✅ <b>Executed Order:</b>\n"
                    f"   🎯 Type: {executed_order_type}\n"
                    f"   💵 Price: ${executed_price:.4f}\n"
                    f"   📦 Quantity: {executed_qty:.8f}\n"
                    f"   ⏰ Time: {executed_time_str}\n"
                    f"{pnl_info}\n"
                    f"❌ <b>Auto-Cancelled Order:</b>\n"
                    f"   🎯 Type: {target_order_type}\n"
                    f"   💵 Price: ${cancelled_price:.4f}\n"
                    f"   📦 Quantity: {cancelled_qty:.8f}\n"
                    f"   ⏰ Cancelled: {cancelled_time_str}\n\n"
                    f"📋 Order IDs:\n"
                    f"   ✅ Executed: <code>{executed_order_id}</code>\n"
                    f"   ❌ Cancelled: <code>{cancelled_order.exchange_order_id}</code>\n\n"
                    f"💡 <b>Note:</b> The {target_order_type} order was automatically cancelled by Crypto.com OCO group when the {executed_order_type} order was executed."
                )
                
                telegram_notifier.send_message(message)
                logger.info(f"Sent notification for already CANCELLED {target_order_type} order: {cancelled_order.exchange_order_id}")
            except Exception as telegram_err:
                logger.warning(f"Failed to send Telegram notification for already cancelled SL/TP: {telegram_err}", exc_info=True)
                
        except Exception as e:
            logger.error(f"Error in _notify_already_cancelled_sl_tp for {symbol}: {e}", exc_info=True)

    # Time window constants for order history subdivision (ms)
    MS_PER_DAY = 24 * 60 * 60 * 1000
    MS_PER_HOUR = 60 * 60 * 1000
    MS_PER_5MIN = 5 * 60 * 1000
    MS_PER_MIN = 60 * 1000

    def _fetch_range_subdivided(
        self,
        trade_client: CryptoComTradeClient,
        instrument_name: str,
        start_ms: int,
        end_ms: int,
        limit: int,
        all_orders: List[dict],
        seen_ids: set,
        window_sizes: Optional[List[int]] = None,
    ) -> None:
        """Subdivide [start_ms, end_ms] and fetch until count < limit or window size == min (1m).
        When at 1m and still full, log WARNING and merge (may be truncating).
        Always walks the whole range; does not break early and skip remaining sub-windows.
        """
        if window_sizes is None:
            window_sizes = [
                self.MS_PER_DAY,
                self.MS_PER_HOUR,
                self.MS_PER_5MIN,
                self.MS_PER_MIN,
            ]
        range_ms = end_ms - start_ms
        if range_ms <= 0:
            return
        # Chunk size: largest in hierarchy that is smaller than current range (next level down)
        chunk_ms = None
        for ws in sorted(window_sizes, reverse=True):
            if ws < range_ms:
                chunk_ms = ws
                break
        if chunk_ms is None:
            chunk_ms = self.MS_PER_MIN  # at floor
        # Walk the whole parent window: iterate backwards from end_ms to start_ms
        chunk_end = end_ms
        while chunk_end > start_ms:
            chunk_start = max(start_ms, chunk_end - chunk_ms)
            try:
                response = trade_client.get_order_history(
                    start_time=chunk_start,
                    end_time=chunk_end,
                    page=0,
                    page_size=limit,
                    instrument_name=instrument_name,
                    skip_empty_fallbacks=True,
                )
            except TypeError as e:
                if "instrument_name" in str(e) or "skip_empty_fallbacks" in str(e):
                    logger.warning(
                        "Broker get_order_history missing optional args; calling without them."
                    )
                    response = trade_client.get_order_history(
                        start_time=chunk_start,
                        end_time=chunk_end,
                        page=0,
                        page_size=limit,
                    )
                else:
                    raise
            page_orders = response.get("data", []) if response else []
            fetched = len(page_orders)
            for o in page_orders:
                oid = o.get("order_id")
                if oid and str(oid) not in seen_ids:
                    seen_ids.add(str(oid))
                    all_orders.append(o)
            if fetched < limit:
                chunk_end = chunk_start
                continue
            # Full page: subdivide this chunk with next smaller window size in hierarchy
            next_smaller = None
            for ws in sorted(window_sizes, reverse=True):
                if ws < chunk_ms:
                    next_smaller = ws
                    break
            if next_smaller is not None:
                self._fetch_range_subdivided(
                    trade_client,
                    instrument_name,
                    chunk_start,
                    chunk_end,
                    limit,
                    all_orders,
                    seen_ids,
                    window_sizes=window_sizes,
                )
            else:
                # At floor (1 min) and still full
                logger.warning(
                    "Order history window still full at 1m; may be truncating instrument=%s start_ms=%s end_ms=%s",
                    instrument_name,
                    chunk_start,
                    chunk_end,
                )
            chunk_end = chunk_start
        return

    def _fetch_order_history_windowed(
        self,
        trade_client: CryptoComTradeClient,
        instrument_name: str,
        lookback_days: int = 180,
        window_days: int = 7,
        limit: int = 100,
    ) -> List[dict]:
        """Fetch order history for one instrument using time-windowed requests.
        Crypto.com returns data only when instrument_name is set AND the time window is narrow.
        Avoids large 180-day single requests that return empty.
        Subdivides full-page windows down to 1 day -> 1 hour -> 5 min -> 1 min; logs WARNING at 1m if still full.
        """
        now_ms = int(time.time() * 1000)
        end_ms = now_ms
        start_ms = now_ms - lookback_days * self.MS_PER_DAY
        all_orders: List[dict] = []
        seen_ids: set = set()
        window_end = end_ms
        consecutive_empty = 0
        while window_end > start_ms:
            window_start = max(start_ms, window_end - window_days * self.MS_PER_DAY)
            logger.info(
                "Order history window fetch: instrument=%s start_ms=%s end_ms=%s window_days=%s limit=%s",
                instrument_name,
                window_start,
                window_end,
                window_days,
                limit,
            )
            try:
                response = trade_client.get_order_history(
                    start_time=window_start,
                    end_time=window_end,
                    page=0,
                    page_size=limit,
                    instrument_name=instrument_name,
                    skip_empty_fallbacks=True,
                )
            except TypeError as e:
                if "instrument_name" in str(e) or "skip_empty_fallbacks" in str(e):
                    logger.warning(
                        "Broker get_order_history missing optional args; calling without them."
                    )
                    response = trade_client.get_order_history(
                        start_time=window_start,
                        end_time=window_end,
                        page=0,
                        page_size=limit,
                    )
                else:
                    raise
            page_orders = response.get("data", []) if response else []
            fetched = len(page_orders)
            for o in page_orders:
                oid = o.get("order_id")
                if oid and str(oid) not in seen_ids:
                    seen_ids.add(str(oid))
                    all_orders.append(o)

            # Advanced/conditional TP-SL fills live only on advanced history (spot history
            # often omits them). Keep the same narrow window — wide ranges return empty.
            try:
                adv_response = trade_client.get_advanced_order_history(
                    instrument_name=instrument_name,
                    limit=limit,
                    start_time=window_start,
                    end_time=window_end,
                )
                adv_orders = adv_response.get("data", []) if adv_response else []
            except Exception as adv_err:
                logger.debug(
                    "Advanced order history window fetch failed instrument=%s: %s",
                    instrument_name,
                    adv_err,
                )
                adv_orders = []
            adv_added = 0
            for o in adv_orders:
                if not isinstance(o, dict):
                    continue
                oid = o.get("order_id")
                if not oid or str(oid) in seen_ids:
                    continue
                # Normalize so sync_order_history treats contingency fills as protection.
                enriched = dict(o)
                if not enriched.get("contingency_type") and enriched.get("contingencyType"):
                    enriched["contingency_type"] = enriched.get("contingencyType")
                seen_ids.add(str(oid))
                all_orders.append(enriched)
                adv_added += 1
            logger.info(
                "Order history window result: instrument=%s fetched=%s advanced_added=%s stored=%s",
                instrument_name,
                fetched,
                adv_added,
                len(all_orders),
            )
            if fetched == 0 and adv_added == 0:
                consecutive_empty += 1
                if consecutive_empty >= ORDER_HISTORY_EMPTY_WINDOWS_STOP:
                    logger.info(
                        "Order history early stop: instrument=%s after %s consecutive empty windows",
                        instrument_name,
                        consecutive_empty,
                    )
                    break
            else:
                consecutive_empty = 0
            if fetched == limit:
                # Subdivide this window: 1d -> 1h -> 5min -> 1min; walk whole parent, log WARNING at 1m if still full
                self._fetch_range_subdivided(
                    trade_client,
                    instrument_name,
                    window_start,
                    window_end,
                    limit,
                    all_orders,
                    seen_ids,
                )
            window_end = window_start
        return all_orders

    def _get_order_history_sync_symbols(self, db: Session) -> Tuple[List[str], List[str]]:
        """Build symbol lists for order-history sync.

        Returns:
            (priority_symbols, all_symbols) — priority symbols are synced every cycle;
            all_symbols includes watchlist + traded + required pairs for cursor rotation.
        """
        watchlist_symbols: List[str] = []
        try:
            from app.models.watchlist import WatchlistItem

            rows = db.query(WatchlistItem.symbol).filter(
                WatchlistItem.is_deleted == False  # noqa: E712
            ).distinct().all()
            watchlist_symbols = [str(r[0]).upper() for r in rows if r[0]]
        except Exception as e:
            logger.debug("Order history sync: watchlist query failed: %s", e)

        recent_traded: List[str] = []
        open_symbols: List[str] = []
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=90)
            recent_rows = (
                db.query(ExchangeOrder.symbol)
                .filter(ExchangeOrder.exchange_update_time >= cutoff)
                .distinct()
                .all()
            )
            recent_traded = [str(r[0]).upper() for r in recent_rows if r[0]]

            open_rows = (
                db.query(ExchangeOrder.symbol)
                .filter(
                    ExchangeOrder.status.in_(
                        [
                            OrderStatusEnum.NEW,
                            OrderStatusEnum.ACTIVE,
                            OrderStatusEnum.PARTIALLY_FILLED,
                        ]
                    )
                )
                .distinct()
                .all()
            )
            open_symbols = [str(r[0]).upper() for r in open_rows if r[0]]
        except Exception as e:
            logger.debug("Order history sync: exchange_orders query failed: %s", e)

        if not watchlist_symbols:
            watchlist_symbols = list(DEFAULT_ORDER_HISTORY_SYMBOLS)
            logger.info(
                "Order history sync: no watchlist symbols, using defaults count=%s",
                len(watchlist_symbols),
            )
        else:
            logger.info("Order history sync: watchlist symbols count=%s", len(watchlist_symbols))

        seen: set[str] = set()
        all_symbols: List[str] = []
        for sym in expand_symbols_with_quote_variants(
            list(REQUIRED_ORDER_HISTORY_SYMBOLS)
            + recent_traded
            + open_symbols
            + watchlist_symbols
            + list(DEFAULT_ORDER_HISTORY_SYMBOLS)
        ):
            key = sym.upper()
            if key and key not in seen:
                seen.add(key)
                all_symbols.append(key)

        priority_seen: set[str] = set()
        priority_symbols: List[str] = []
        for sym in expand_symbols_with_quote_variants(
            list(REQUIRED_ORDER_HISTORY_SYMBOLS) + recent_traded + open_symbols
        ):
            key = sym.upper()
            if key and key not in priority_seen:
                priority_seen.add(key)
                priority_symbols.append(key)
                if len(priority_symbols) >= ORDER_HISTORY_PRIORITY_MAX:
                    break

        logger.info(
            "Order history sync: priority=%s all=%s",
            len(priority_symbols),
            len(all_symbols),
        )
        return priority_symbols, all_symbols

    def sync_order_history_for_instrument(
        self,
        db: Session,
        trade_client: CryptoComTradeClient,
        instrument_name: str,
        lookback_days: int = ORDER_HISTORY_DEEP_LOOKBACK_DAYS,
        window_days: int = 7,
        limit: int = 100,
    ) -> int:
        """Fetch order history for one instrument via windowed requests and upsert into DB.
        Returns total count of orders stored (new + updated) for this instrument.
        """
        orders = self._fetch_order_history_windowed(
            trade_client, instrument_name, lookback_days, window_days, limit
        )
        return self.sync_order_history(
            db,
            page_size=limit,
            max_pages=1,
            instrument_name=instrument_name,
            prefetched_orders=orders,
        )

    def _order_history_cursor_get_and_advance(
        self, db: Session, symbol_count: int, max_per_run: int
    ) -> tuple[int, int]:
        """Get current cursor and advance for next run. Uses Postgres (persistent, row lock) or file fallback.
        Returns (start_index, next_cursor). Survives container restart when using DB.
        """
        if symbol_count <= 0:
            return (0, 0)
        n = min(max_per_run, symbol_count)
        # 1) Try Postgres: one-row table, row lock for multi-worker safety
        try:
            db.execute(text(
                "CREATE TABLE IF NOT EXISTS sync_order_history_cursor (id INTEGER PRIMARY KEY DEFAULT 1, cursor_index INTEGER NOT NULL DEFAULT 0)"
            ))
            db.commit()
        except Exception as e:
            logger.debug("Order history cursor table create skip: %s", e)
            try:
                db.rollback()
            except Exception:
                pass
        try:
            row = db.execute(
                text("SELECT cursor_index FROM sync_order_history_cursor WHERE id = 1 FOR UPDATE")
            ).fetchone()
            if row is None:
                db.execute(text("INSERT INTO sync_order_history_cursor (id, cursor_index) VALUES (1, 0)"))
                cursor = 0
            else:
                cursor = int(row[0])
            start_index = cursor % symbol_count
            next_cursor = (start_index + n) % symbol_count
            db.execute(text("UPDATE sync_order_history_cursor SET cursor_index = :nc WHERE id = 1"), {"nc": next_cursor})
            db.commit()
            return (start_index, next_cursor)
        except Exception as e:
            logger.warning("Order history cursor DB failed, using file fallback: %s", e)
            try:
                db.rollback()
            except Exception:
                pass
        # 2) File fallback (set ORDER_HISTORY_SYNC_CURSOR_PATH to a mounted volume to survive restart; fcntl lock for multi-worker)
        cursor_path = os.environ.get("ORDER_HISTORY_SYNC_CURSOR_PATH", "/tmp/order_history_sync_cursor")
        cursor = 0
        if os.path.isfile(cursor_path):
            try:
                with open(cursor_path, "r") as f:
                    try:
                        import fcntl
                        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                        cursor = int(f.read().strip() or "0")
                    except ImportError:
                        cursor = int(f.read().strip() or "0")
                    finally:
                        try:
                            import fcntl
                            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                        except Exception:
                            pass
            except (ValueError, OSError):
                cursor = 0
        start_index = cursor % symbol_count
        next_cursor = (start_index + n) % symbol_count
        try:
            with open(cursor_path, "w") as f:
                try:
                    import fcntl
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                    f.write(str(next_cursor))
                except ImportError:
                    f.write(str(next_cursor))
                finally:
                    try:
                        import fcntl
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                    except Exception:
                        pass
        except OSError:
            pass
        return (start_index, next_cursor)

    def sync_order_history(self, db: Session, page_size: int = 200, max_pages: int = 5, instrument_name: Optional[str] = None, prefetched_orders: Optional[List[dict]] = None):  # pyright: ignore[reportGeneralTypeIssues]
        """Sync order history from Crypto.com - only adds new executed orders.

        Uses per-instrument time-windowed fetch: Crypto.com returns data only when
        instrument_name is set and the time window is narrow (single 180-day request returns empty).

        Args:
            db: Database session
            page_size: Number of orders per page (default 200)
            max_pages: Maximum number of pages to fetch (default 5, unused when using windowed fetch)
            instrument_name: Optional symbol (e.g. BCH_USDT) to fetch history for one instrument only.
            prefetched_orders: If set, use this list instead of fetching (used by sync_order_history_for_instrument).
        """
        # Normalize: empty string -> None so we don't use single-instrument path with ""
        _instrument = (instrument_name or "").strip() or None
        _single = _instrument is not None and prefetched_orders is None
        logger.info(
            "sync_order_history called: instrument_name=%s prefetched_orders=%s (single-instrument=%s)",
            _instrument,
            "set" if prefetched_orders is not None else "None",
            _single,
        )
        try:
            from app.services.telegram_notifier import telegram_notifier

            # Single instrument: delegate to windowed sync and return (Crypto.com returns data only with instrument_name + narrow window)
            if _single:
                logger.info("sync_order_history: delegating to sync_order_history_for_instrument instrument=%s", _instrument)
                return self.sync_order_history_for_instrument(
                    db, trade_client, _instrument,
                    lookback_days=ORDER_HISTORY_DEEP_LOOKBACK_DAYS,
                    window_days=ORDER_HISTORY_DEEP_WINDOW_DAYS,
                    limit=100,
                )

            # Purge stale processed order IDs before processing
            self._purge_stale_processed_orders()

            # Track orders processed in this cycle - mark as processed only AFTER successful commit
            orders_processed_this_cycle = []

            if prefetched_orders is not None:
                orders = prefetched_orders
                logger.info("Order history sync: using prefetched_orders count=%s", len(orders))
            else:
                priority_symbols, all_symbols = self._get_order_history_sync_symbols(db)
                ORDER_HISTORY_SYNC_SLEEP_BETWEEN_SYMBOLS_SEC = 0.2
                total_stored = 0

                # Priority pass: required + recently traded + open-order symbols every cycle (recent window).
                for i, sym in enumerate(priority_symbols):
                    if i > 0:
                        time.sleep(ORDER_HISTORY_SYNC_SLEEP_BETWEEN_SYMBOLS_SEC)
                    total_stored += self.sync_order_history_for_instrument(
                        db,
                        trade_client,
                        sym,
                        lookback_days=ORDER_HISTORY_RECENT_LOOKBACK_DAYS,
                        window_days=ORDER_HISTORY_RECENT_WINDOW_DAYS,
                        limit=100,
                    )

                # Rotating pass: remaining watchlist/traded symbols (recent window only; deep scan on manual sync).
                start_index, next_cursor = self._order_history_cursor_get_and_advance(
                    db, len(all_symbols), ORDER_HISTORY_SYNC_MAX_SYMBOLS_PER_RUN
                )
                n = min(ORDER_HISTORY_SYNC_MAX_SYMBOLS_PER_RUN, len(all_symbols))
                symbols_this_run = (
                    [all_symbols[(start_index + i) % len(all_symbols)] for i in range(n)]
                    if all_symbols
                    else []
                )
                priority_set = set(priority_symbols)
                for i, sym in enumerate(symbols_this_run):
                    if sym in priority_set:
                        continue
                    if i > 0:
                        time.sleep(ORDER_HISTORY_SYNC_SLEEP_BETWEEN_SYMBOLS_SEC)
                    total_stored += self.sync_order_history_for_instrument(
                        db,
                        trade_client,
                        sym,
                        lookback_days=ORDER_HISTORY_RECENT_LOOKBACK_DAYS,
                        window_days=ORDER_HISTORY_RECENT_WINDOW_DAYS,
                        limit=100,
                    )
                logger.info(
                    "Order history sync: priority=%s rotating=%s total_stored=%s next_cursor=%s",
                    len(priority_symbols),
                    len([s for s in symbols_this_run if s not in priority_set]),
                    total_stored,
                    next_cursor,
                )
                return total_stored
            pages_fetched = len(orders)  # windowed fetch does not use page count
            logger.info("📥 Received %s total orders from API history (windowed fetch)", len(orders))
            
            # Note: private/advanced/get-order-history returns order history (executed orders)
            # These should already be FILLED or other terminal states
            filled_count = sum(1 for o in orders if o.get('status', '').upper() == 'FILLED')
            logger.info(f"✅ Found {filled_count} FILLED orders in API response (out of {len(orders)} total orders)")
            
            new_orders_count = 0
            
            for order_data in orders:
                order_id = str(order_data.get('order_id', ''))
                if not order_id:
                    continue
                
                # Process filled orders, and also CANCELED orders that were partially/fully executed
                status_str = normalize_resolved_exchange_status(
                    str(order_data.get("status", "") or "")
                )
                
                # Check if order was executed (cumulative_quantity > 0)
                # Handle both string and numeric cumulative_quantity
                cumulative_qty_raw = order_data.get('cumulative_quantity', 0) or 0
                cumulative_qty = float(cumulative_qty_raw) if cumulative_qty_raw else 0
                original_qty = float(order_data.get('quantity', 0) or 0)

                mapped_status = map_exchange_order_status(
                    status_str,
                    cumulative_quantity=cumulative_qty,
                    quantity=original_qty,
                )
                if mapped_status in (OrderStatusEnum.FILLED, OrderStatusEnum.PARTIALLY_FILLED):
                    status_str = mapped_status.value
                
                # Process FILLED orders, or CANCELED orders that were executed
                # IMPORTANT: If status is FILLED, always process it (even if cumulative_qty is 0 in edge cases)
                # This ensures orders marked as FILLED in Crypto.com are always processed
                is_executed = (
                    status_str == 'FILLED' or  # Always process FILLED orders
                    (
                        cumulative_qty > 0
                        and status_str in ('CANCELLED', 'CANCELED', 'PARTIALLY_FILLED')
                        and cumulative_qty >= original_qty * 0.99
                    )
                )
                
                if not is_executed:
                    continue
                
                # Check if this order was already processed in the current cycle (prevent duplicates within same sync)
                if order_id in orders_processed_this_cycle:
                    logger.debug(f"Order {order_id} already processed in this sync cycle, skipping duplicate")
                    continue
                
                # NOTE: We allow re-processing orders that were processed in previous sessions
                # This ensures timestamps and other data are always synced from Crypto.com
                # The processed_order_ids check is removed to allow updates to existing orders
                
                # Extract symbol and side early for use in all code paths
                symbol = order_data.get('instrument_name', '')
                side = order_data.get('side', '').upper()
                
                # Parse timestamps early for use in all code paths
                create_time = None
                update_time = None
                if order_data.get('create_time'):
                    try:
                        # CRITICAL FIX: Use timezone.utc to ensure timestamps are interpreted as UTC, not local time
                        create_time = datetime.fromtimestamp(order_data['create_time'] / 1000, tz=timezone.utc)
                    except:
                        pass
                if order_data.get('update_time'):
                    try:
                        # CRITICAL FIX: Use timezone.utc to ensure timestamps are interpreted as UTC, not local time
                        update_time = datetime.fromtimestamp(order_data['update_time'] / 1000, tz=timezone.utc)
                    except:
                        pass
                
                # Get price and quantity early for use in all code paths
                # IMPORTANT: For SL/TP creation, we MUST use cumulative_quantity (executed quantity) from MARKET order
                # cumulative_quantity is the actual amount that was executed, not the requested quantity
                order_price = order_data.get('limit_price') or order_data.get('price') or order_data.get('avg_price')
                order_price_float = float(order_price) if order_price else None
                quantity_float = float(order_data.get('quantity', 0)) if order_data.get('quantity') else 0
                
                # Priority: cumulative_quantity (executed) > quantity (requested)
                # For MARKET orders, cumulative_quantity is the actual amount executed
                cumulative_qty_raw = order_data.get('cumulative_quantity', 0) or 0
                if cumulative_qty_raw:
                    executed_qty = float(cumulative_qty_raw)
                else:
                    # Fallback to quantity only if cumulative_quantity is not available
                    executed_qty = quantity_float if quantity_float > 0 else 0
                
                logger.info(f"Order {order_id} quantity: requested={quantity_float}, executed={executed_qty} (cumulative_quantity={cumulative_qty_raw})")
                
                # Check if order already exists in database
                existing = db.query(ExchangeOrder).filter(
                    ExchangeOrder.exchange_order_id == order_id
                ).first()
                
                if existing:
                    # Update order data from API
                    # STRICT FILL-ONLY: Notifications are handled separately using fill tracker
                    needs_update = False
                    status_before_sync = existing.status
                    
                    # Update status if changed
                    if status_str in ('FILLED', 'PARTIALLY_FILLED', 'NEW', 'ACTIVE', 'CANCELLED', 'REJECTED', 'EXPIRED'):
                        try:
                            new_status_enum = OrderStatusEnum(status_str)
                        except ValueError:
                            new_status_enum = None
                        if new_status_enum is not None and existing.status != new_status_enum:
                            needs_update = True
                            logger.debug(f"Order {order_id} status changed: {existing.status.value if existing.status else 'UNKNOWN'} -> {status_str}")
                    
                    # Always update timestamps from Crypto.com if available
                    if (update_time or create_time) and existing:
                        needs_update = True
                    
                    # Always update cumulative_quantity from API (needed for fill tracking)
                    # ROOT CAUSE of crash: new_cumulative_qty was float (API), last_seen_qty from DB is
                    # Numeric -> Decimal. Subtraction float - Decimal raises TypeError. Use _to_decimal throughout.
                    cumulative_qty_from_api = order_data.get('cumulative_quantity', '0') or '0'
                    new_cumulative_qty = _to_decimal(cumulative_qty_from_api)
                    last_seen_qty = _to_decimal(existing.cumulative_quantity)
                    delta_qty = new_cumulative_qty - last_seen_qty
                    if delta_qty < 0:
                        logger.warning(
                            "sync_order_history negative delta (order_id=%s symbol=%s new_cumulative_qty=%s last_seen_qty=%s delta_qty=%s); clamping to 0",
                            order_id, symbol or existing.symbol, new_cumulative_qty, last_seen_qty, delta_qty,
                        )
                        delta_qty = Decimal("0")
                    logger.debug(
                        "sync_order_history qty (order_id=%s new_cumulative_qty_type=%s last_seen_qty_type=%s delta_qty=%s)",
                        order_id, type(new_cumulative_qty).__name__, type(last_seen_qty).__name__, delta_qty,
                    )
                    # Always update cumulative_quantity (even if nothing else changed) for fill tracking
                    if new_cumulative_qty != _to_decimal(existing.cumulative_quantity):
                        needs_update = True
                        existing.cumulative_quantity = new_cumulative_qty

                    protection_role = protection_role_from_order_data(order_data)
                    if protection_role and existing.order_role != protection_role:
                        needs_update = True
                    
                    if needs_update:
                        # Update existing order with new status and execution data from Crypto.com history
                        logger.debug(f"Updating order {order_id} data from Crypto.com (status={status_str})")
                        
                        # Update status if provided and valid
                        old_status = existing.status
                        if status_str in ('FILLED', 'PARTIALLY_FILLED', 'NEW', 'ACTIVE', 'CANCELLED', 'REJECTED', 'EXPIRED'):
                            try:
                                existing.status = OrderStatusEnum(status_str)
                            except ValueError:
                                pass
                            
                            # Emit ORDER_CANCELED event if status changed to CANCELLED
                            if status_str == 'CANCELLED' and old_status != OrderStatusEnum.CANCELLED:
                                try:
                                    from app.services.signal_monitor import _emit_lifecycle_event
                                    from app.services.strategy_profiles import resolve_strategy_profile
                                    from app.models.watchlist import WatchlistItem
                                    
                                    # Resolve strategy for event emission
                                    watchlist_item = db.query(WatchlistItem).filter(
                                        WatchlistItem.symbol == (symbol or existing.symbol)
                                    ).first()
                                    strategy_type, risk_approach = resolve_strategy_profile(
                                        symbol or existing.symbol, db, watchlist_item
                                    )
                                    strategy_key = build_strategy_key(strategy_type, risk_approach)
                                    
                                    _emit_lifecycle_event(
                                        db=db,
                                        symbol=symbol or existing.symbol,
                                        strategy_key=strategy_key,
                                        side=side or (existing.side.value if existing.side else 'BUY'),
                                        price=order_price_float or (existing.avg_price if existing.avg_price else existing.price) or None,
                                        event_type="ORDER_CANCELED",
                                        event_reason=f"order_id={order_id}, reason=status_changed_to_cancelled",
                                        order_id=order_id,
                                    )
                                except Exception as emit_err:
                                    logger.warning(f"Failed to emit ORDER_CANCELED event for {order_id}: {emit_err}", exc_info=True)
                        # Always use data from Crypto.com history (more accurate)
                        if protection_role:
                            existing.order_role = protection_role
                        existing.price = order_price_float if order_price_float else existing.price
                        existing.quantity = executed_qty if executed_qty > 0 else (quantity_float if quantity_float > 0 else existing.quantity)
                        cumulative_val_from_api = order_data.get('cumulative_value', '0') or '0'
                        existing.cumulative_value = float(cumulative_val_from_api) if cumulative_val_from_api else 0
                        avg_price_from_api = order_data.get('avg_price', '0') or '0'
                        existing.avg_price = float(avg_price_from_api) if avg_price_from_api else (order_price_float if order_price_float else existing.avg_price)
                        
                        # CRITICAL: Always update timestamps from Crypto.com if available
                        # This ensures the order reflects the actual date from the exchange
                        if update_time:
                            existing.exchange_update_time = update_time
                            logger.info(f"Updated exchange_update_time for order {order_id} to {update_time} from Crypto.com")
                        elif create_time:
                            # If update_time is not available, use create_time
                            existing.exchange_update_time = create_time
                            logger.info(f"Updated exchange_update_time for order {order_id} to {create_time} (from create_time) from Crypto.com")
                        # Only use datetime.utcnow() as last resort if no timestamp is available from Crypto.com
                        elif not existing.exchange_update_time:
                            # Use timezone from module-level import
                            from datetime import timezone as tz
                            existing.exchange_update_time = datetime.now(tz.utc)
                            logger.warning(f"No timestamp from Crypto.com for order {order_id}, using current time")
                        
                        # Always update create_time if available from Crypto.com
                        if create_time:
                            existing.exchange_create_time = create_time
                        
                        # Use timezone from module-level import
                        from datetime import timezone as tz
                        existing.updated_at = datetime.now(tz.utc)
                        link_system_trade_signal_to_order(db, existing)
                        
                        logger.info(f"Order {order_id} updated: cumulative_qty={existing.cumulative_quantity}, cumulative_val={existing.cumulative_value}, avg_price={existing.avg_price}")
                        
                        # Mark that we updated an existing order (counts towards new_orders_count for commit)
                        new_orders_count += 1
                        
                        # IMPORTANT: Do NOT mark as processed here - wait until AFTER successful commit
                        # This prevents orders from being skipped in future syncs if commit fails
                        # Track for marking as processed after commit succeeds
                        orders_processed_this_cycle.append(order_id)
                    
                    # STRICT FILL-ONLY NOTIFICATION LOGIC (check even if needs_update was False)
                    # Only notify for real fills: status must be FILLED or PARTIALLY_FILLED with increased filled_qty
                    # Check fills for any order with fill status, regardless of whether other fields changed
                    fill_dedup = get_fill_dedup(db)
                    # Use updated cumulative_quantity (already set above if it changed)
                    current_filled_qty = existing.cumulative_quantity if existing.cumulative_quantity > 0 else executed_qty
                    # Determine current status - prefer status_str from API, fallback to existing status
                    if status_str in ('FILLED', 'PARTIALLY_FILLED'):
                        current_status_str = status_str
                    elif existing.status in (OrderStatusEnum.FILLED, OrderStatusEnum.PARTIALLY_FILLED):
                        current_status_str = existing.status.value
                    else:
                        current_status_str = None
                    
                    gate_ok, gate_reason = should_notify_executed_fill(
                        db=db,
                        order=existing,
                        now_utc=datetime.now(timezone.utc),
                        source="sync_order_history",
                        requested_by_admin=False,
                    )
                    if not gate_ok:
                        should_notify, notify_reason = False, gate_reason
                        if current_status_str in ('FILLED', 'PARTIALLY_FILLED') and current_filled_qty > 0:
                            fill_dedup.record_fill(
                                order_id=order_id,
                                filled_qty=current_filled_qty,
                                status=current_status_str,
                                notification_sent=False,
                            )
                        logger.debug(f"Skipping notification for order {order_id}: {gate_reason}")
                    else:
                        should_notify, notify_reason = fill_dedup.should_notify_fill(
                            order_id=order_id,
                            current_filled_qty=current_filled_qty,
                            status=current_status_str or 'UNKNOWN'
                        ) if current_status_str else (False, f"Status {status_str} is not a fill status")
                    
                    if gate_ok and should_notify and current_status_str in ('FILLED', 'PARTIALLY_FILLED'):
                        try:
                            from app.services.telegram_notifier import telegram_notifier
                            
                            total_usd = order_price_float * executed_qty if order_price_float and executed_qty else 0
                            order_type = order_data.get('order_type', existing.order_type or 'LIMIT')
                            order_type_upper = order_type.upper()
                            
                            # If this is a SL or TP order, find the original entry order to calculate profit/loss
                            entry_price = None
                            if order_type_upper in ['STOP_LIMIT', 'TAKE_PROFIT_LIMIT']:
                                current_side = side or (existing.side.value if existing.side else 'BUY')
                                
                                # First try to find by parent_order_id (most reliable)
                                if existing.parent_order_id:
                                    parent_order = db.query(ExchangeOrder).filter(
                                        ExchangeOrder.exchange_order_id == existing.parent_order_id
                                    ).first()
                                    if parent_order:
                                        entry_price = parent_order.avg_price if parent_order.avg_price else parent_order.price
                                        logger.info(f"Found entry price via parent_order_id for SL/TP order {order_id}: {entry_price} from parent {existing.parent_order_id}")
                                
                                # If parent_order_id not found, search for most recent BUY order
                                if not entry_price and current_side == "SELL":
                                    # This is selling (TP/SL after BUY), so find the original BUY order
                                    # Look for BUY orders created before this TP/SL order
                                    if existing.exchange_create_time:
                                        original_order = db.query(ExchangeOrder).filter(
                                            ExchangeOrder.symbol == (symbol or existing.symbol),
                                            ExchangeOrder.side == "BUY",
                                            ExchangeOrder.status == OrderStatusEnum.FILLED,
                                            ExchangeOrder.order_type.in_(["MARKET", "LIMIT"]),
                                            ExchangeOrder.exchange_order_id != order_id,  # Not the current order
                                            ExchangeOrder.exchange_create_time <= existing.exchange_create_time  # Created before TP/SL
                                        ).order_by(ExchangeOrder.exchange_update_time.desc()).first()
                                    else:
                                        # Fallback without time constraint
                                        original_order = db.query(ExchangeOrder).filter(
                                            ExchangeOrder.symbol == (symbol or existing.symbol),
                                            ExchangeOrder.side == "BUY",
                                            ExchangeOrder.status == OrderStatusEnum.FILLED,
                                            ExchangeOrder.order_type.in_(["MARKET", "LIMIT"]),
                                            ExchangeOrder.exchange_order_id != order_id
                                        ).order_by(ExchangeOrder.exchange_update_time.desc()).first()
                                    
                                    if original_order:
                                        entry_price = original_order.avg_price if original_order.avg_price else original_order.price
                                        logger.info(f"Found entry price for SL/TP order {order_id}: {entry_price} from BUY order {original_order.exchange_order_id}")
                                elif not entry_price and current_side == "BUY":
                                    # This is buying (SL/TP after SELL for short positions), find original SELL order
                                    if existing.exchange_create_time:
                                        original_order = db.query(ExchangeOrder).filter(
                                            ExchangeOrder.symbol == (symbol or existing.symbol),
                                            ExchangeOrder.side == "SELL",
                                            ExchangeOrder.status == OrderStatusEnum.FILLED,
                                            ExchangeOrder.order_type.in_(["MARKET", "LIMIT"]),
                                            ExchangeOrder.exchange_order_id != order_id,
                                            ExchangeOrder.exchange_create_time <= existing.exchange_create_time
                                        ).order_by(ExchangeOrder.exchange_update_time.desc()).first()
                                    else:
                                        original_order = db.query(ExchangeOrder).filter(
                                            ExchangeOrder.symbol == (symbol or existing.symbol),
                                            ExchangeOrder.side == "SELL",
                                            ExchangeOrder.status == OrderStatusEnum.FILLED,
                                            ExchangeOrder.order_type.in_(["MARKET", "LIMIT"]),
                                            ExchangeOrder.exchange_order_id != order_id
                                        ).order_by(ExchangeOrder.exchange_update_time.desc()).first()
                                    
                                    if original_order:
                                        entry_price = original_order.avg_price if original_order.avg_price else original_order.price
                                        logger.info(f"Found entry price for SL/TP order {order_id}: {entry_price} from SELL order {original_order.exchange_order_id}")
                            
                            # Count open entry BUY orders for this symbol (NEW, ACTIVE, PARTIALLY_FILLED).
                            # Exclude protective SL/TP orders: for SHORT positions they are BUY-side
                            # (STOP_LIMIT / TAKE_PROFIT_LIMIT), which inflated the count in the
                            # ORDER EXECUTED warning ("Open Orders: 22").
                            order_symbol = symbol or existing.symbol
                            open_orders_count = _count_open_entry_buy_orders(db, order_symbol)
                            
                            # Infer order_role from order_type if order_role is not set
                            # CRITICAL: Only set role if order_type clearly indicates it (STOP_LIMIT, TAKE_PROFIT_LIMIT)
                            # Do NOT mislabel BUY orders as Stop Loss
                            inferred_order_role = existing.order_role
                            if not inferred_order_role and order_type_upper:
                                if order_type_upper == 'STOP_LIMIT':
                                    inferred_order_role = 'STOP_LOSS'
                                elif order_type_upper == 'TAKE_PROFIT_LIMIT':
                                    inferred_order_role = 'TAKE_PROFIT'
                                # For other order types, leave as None (don't mislabel)
                            
                            # Audit log: JSON-serializable (Decimal/datetime via make_json_safe)
                            audit_log = make_json_safe({
                                "event": "ORDER_EXECUTED_NOTIFICATION",
                                "symbol": order_symbol,
                                "side": side or (existing.side.value if existing.side else 'BUY'),
                                "order_id": order_id,
                                "status": current_status_str,
                                "cumulative_quantity": current_filled_qty,
                                "delta_quantity": float(delta_qty),
                                "price": order_price_float or (existing.price or 0),
                                "avg_price": existing.avg_price,
                                "order_type": order_type,
                                "order_role": inferred_order_role,
                                "client_oid": existing.client_oid,
                                "trade_signal_id": existing.trade_signal_id,
                                "parent_order_id": existing.parent_order_id,
                                "notify_reason": notify_reason,
                                "handler": "exchange_sync.update_existing_order"
                            })
                            logger.info(f"[FILL_NOTIFICATION] {json.dumps(audit_log)}")

                            # Last-chance link retry: the TradeSignal row may have been
                            # committed by signal_monitor AFTER this order row was first
                            # synced, so an earlier link attempt could have found nothing.
                            # Without this the notification says "Origen: Manual" for
                            # bot-created orders (observed 2026-07-21 ETH/DOT/DOGE sells).
                            if existing.trade_signal_id is None:
                                link_system_trade_signal_to_order(db, existing)

                            result = telegram_notifier.send_executed_order(
                                symbol=order_symbol,
                                side=side or (existing.side.value if existing.side else 'BUY'),
                                price=order_price_float or (existing.price or 0),
                                quantity=current_filled_qty,
                                total_usd=total_usd,
                                order_id=order_id,
                                order_type=order_type,
                                entry_price=entry_price,  # Add entry_price for profit/loss calculation
                                open_orders_count=open_orders_count,  # Add open orders count for monitoring
                                order_role=inferred_order_role,  # Use inferred role if order_role is not set
                                trade_signal_id=existing.trade_signal_id,  # Pass trade_signal_id to determine if order was created by alert
                                parent_order_id=existing.parent_order_id  # Pass parent_order_id to determine if order is SL/TP
                            )
                            if result:
                                existing.execution_notified_at = datetime.now(timezone.utc)
                                try:
                                    db.flush()
                                except Exception as flush_err:
                                    logger.warning(
                                        "Failed to flush execution_notified_at for %s: %s",
                                        order_id,
                                        flush_err,
                                    )
                                # Record fill in persistent tracker (Postgres or SQLite per USE_DB_FILL_DEDUP)
                                fill_dedup.record_fill(
                                    order_id=order_id,
                                    filled_qty=current_filled_qty,
                                    status=current_status_str,
                                    notification_sent=True
                                )
                                logger.info(f"Sent Telegram notification for executed order: {symbol or existing.symbol} {side or (existing.side.value if existing.side else 'BUY')} - {order_id} (reason: {notify_reason})")
                                
                                # Emit ORDER_EXECUTED event
                                try:
                                    from app.services.signal_monitor import _emit_lifecycle_event
                                    from app.services.strategy_profiles import resolve_strategy_profile
                                    from app.models.watchlist import WatchlistItem
                                    
                                    # Resolve strategy for event emission
                                    watchlist_item = db.query(WatchlistItem).filter(
                                        WatchlistItem.symbol == (symbol or existing.symbol)
                                    ).first()
                                    strategy_type, risk_approach = resolve_strategy_profile(
                                        symbol or existing.symbol, db, watchlist_item
                                    )
                                    strategy_key = build_strategy_key(strategy_type, risk_approach)
                                    
                                    _emit_lifecycle_event(
                                        db=db,
                                        symbol=symbol or existing.symbol,
                                        strategy_key=strategy_key,
                                        side=side or (existing.side.value if existing.side else 'BUY'),
                                        price=order_price_float or (existing.avg_price if existing.avg_price else existing.price) or 0,
                                        event_type="ORDER_EXECUTED",
                                        event_reason=f"order_id={order_id}, filled_qty={current_filled_qty}, status={current_status_str}",
                                        order_id=order_id,
                                    )
                                except Exception as emit_err:
                                    logger.warning(f"Failed to emit ORDER_EXECUTED event for {order_id}: {emit_err}", exc_info=True)
                            else:
                                logger.warning(f"Failed to send Telegram notification for executed order: {symbol or existing.symbol} {side or (existing.side.value if existing.side else 'BUY')} - {order_id}")
                        except Exception as telegram_err:
                            logger.warning(f"Failed to send Telegram notification: {telegram_err}")
                    else:
                        # Record fill even if we don't notify (for tracking)
                        if current_status_str in ('FILLED', 'PARTIALLY_FILLED') and current_filled_qty > 0:
                            fill_dedup.record_fill(
                                order_id=order_id,
                                filled_qty=current_filled_qty,
                                status=current_status_str,
                                notification_sent=False
                            )
                        if current_status_str not in ('FILLED', 'PARTIALLY_FILLED'):
                            logger.debug(f"Skipping notification for order {order_id}: status={status_str} is not a fill status")
                        else:
                            logger.debug(f"Skipping notification for order {order_id}: {notify_reason}")
                    
                    # Check if this is a SL or TP order that was executed - cancel the other one
                    # Also check if this is a SELL LIMIT order that closes a position - cancel SL
                    # This logic runs regardless of whether notification was sent
                    if is_executed:
                        order_type_from_history = order_data.get('order_type', '').upper()
                        order_type_from_db = existing.order_type or ''
                        protection_role = protection_role_from_order_data(order_data) or (
                            (existing.order_role or "").upper()
                            if (existing.order_role or "").upper() in ("TAKE_PROFIT", "STOP_LOSS")
                            else None
                        )
                        is_sl_tp_executed = (
                            protection_role is not None
                            or order_type_from_history in ['STOP_LIMIT', 'TAKE_PROFIT_LIMIT', 'STOP_LOSS', 'TAKE_PROFIT']
                            or order_type_from_db.upper() in ['STOP_LIMIT', 'TAKE_PROFIT_LIMIT', 'STOP_LOSS', 'TAKE_PROFIT']
                        )
                        
                        # If this is a SELL LIMIT order (not TP/SL) that closes a position, cancel remaining SL
                        is_sell_limit_that_closes_position = (
                            order_type_from_history == 'LIMIT' and 
                            side == 'SELL' and 
                            not is_sl_tp_executed
                        )
                        
                        if is_sl_tp_executed:
                            # History sync re-visits old FILLED TPs every cycle; only act on
                            # recent fills (live OCO) — never re-Telegram / live-cancel history.
                            if (
                                status_before_sync == OrderStatusEnum.FILLED
                                and not is_recent_exchange_event(existing)
                            ):
                                logger.debug(
                                    "Skipping OCO sibling handling for historical already-FILLED %s",
                                    order_id,
                                )
                            else:
                                # CRITICAL: Always attempt to cancel the sibling order
                                # Try OCO group ID method first (most reliable if OCO group ID exists)
                                oco_success = False
                                if existing.oco_group_id:
                                    try:
                                        logger.info(f"Attempting to cancel OCO sibling for order {order_id} (group: {existing.oco_group_id})")
                                        oco_success = self._cancel_oco_sibling(db, existing)
                                        if oco_success:
                                            logger.info(f"✅ OCO cancellation succeeded for order {order_id}")
                                        else:
                                            logger.warning(f"⚠️ OCO cancellation returned False for order {order_id}, will try fallback")
                                    except Exception as oco_err:
                                        logger.warning(f"Error canceling OCO sibling for {order_id}: {oco_err}")
                                        oco_success = False
                                
                                # ALWAYS try the fallback method if OCO method didn't succeed
                                # This will search by parent_order_id, order_role, time window, or symbol+type
                                # This ensures cancellation works for both BUY and SELL orders
                                if not oco_success:
                                    try:
                                        logger.info(f"Attempting fallback cancellation for sibling of {order_id} (symbol: {symbol or existing.symbol}, type: {order_type_from_history or order_type_from_db.upper()})")
                                        cancelled_count = self._cancel_remaining_sl_tp(db, symbol or existing.symbol, order_type_from_history or order_type_from_db.upper(), order_id)
                                        if cancelled_count > 0:
                                            logger.info(f"✅ Successfully cancelled {cancelled_count} sibling order(s) via fallback method")
                                        elif cancelled_count == 0:
                                            # If no active SL/TP found to cancel, check if there's already a CANCELLED one
                                            # This means it was cancelled by Crypto.com OCO automatically, but we should still notify
                                            logger.debug(f"No active {order_type_from_db.upper()} orders found to cancel - checking for already CANCELLED orders")
                                            self._notify_already_cancelled_sl_tp(db, symbol or existing.symbol, order_type_from_history or order_type_from_db.upper(), order_id)
                                    except Exception as cancel_err:
                                        logger.error(f"❌ Error canceling remaining SL/TP for {order_id}: {cancel_err}", exc_info=True)
                        
                        # If this is a SELL LIMIT order that closes a position, cancel remaining SL orders
                        elif is_sell_limit_that_closes_position:
                            try:
                                logger.info(f"SELL LIMIT order {order_id} executed - cancelling remaining SL orders for {symbol or existing.symbol}")
                                self._cancel_remaining_sl_tp(db, symbol or existing.symbol, 'LIMIT', order_id)
                            except Exception as cancel_err:
                                logger.warning(f"Error canceling remaining SL orders after SELL LIMIT execution for {order_id}: {cancel_err}")
                    
                    # Create SL/TP for LIMIT orders that were filled (only if status just changed to FILLED)
                    # Do this AFTER we've marked the order for update, but handle errors gracefully
                    # Create SL/TP for both LIMIT and MARKET orders when they are filled
                    # IMPORTANT: NEVER create SL/TP for STOP_LIMIT or TAKE_PROFIT_LIMIT orders
                    if needs_update and is_executed:
                        order_type_from_history = order_data.get('order_type', '').upper()
                        order_type_from_db = existing.order_type or ''
                        
                        # Check if this is a SL/TP order - if so, do NOT create new SL/TP
                        # Advanced history returns LIMIT + contingency_type=TAKE_PROFIT after TP fills.
                        protection_role = protection_role_from_order_data(order_data) or (
                            (existing.order_role or "").upper()
                            if (existing.order_role or "").upper() in ("TAKE_PROFIT", "STOP_LOSS")
                            else None
                        )
                        is_sl_tp_order = (
                            protection_role is not None
                            or order_type_from_history in ['STOP_LIMIT', 'TAKE_PROFIT_LIMIT', 'STOP_LOSS', 'TAKE_PROFIT']
                            or order_type_from_db.upper() in ['STOP_LIMIT', 'TAKE_PROFIT_LIMIT', 'STOP_LOSS', 'TAKE_PROFIT']
                        )
                        
                        # Create SL/TP only for LIMIT and MARKET orders (not for STOP_LIMIT or TAKE_PROFIT_LIMIT)
                        is_main_order = (
                            (order_type_from_history in ['LIMIT', 'MARKET'] or 
                             order_type_from_db.upper() in ['LIMIT', 'MARKET']) and
                            not is_sl_tp_order  # Double check - never create SL/TP for SL/TP orders
                        )
                        
                        # CRITICAL FIX: Always check and create SL/TP for FILLED orders, not just when needs_telegram=True
                        # This ensures SL/TP are created even if the order was already FILLED in the database
                        # The _create_sl_tp_for_filled_order function already checks for duplicates, so it's safe to call multiple times
                        if is_main_order:
                            order_filled_time = update_time or create_time
                            if not order_filled_time:
                                order_filled_time = (
                                    existing.exchange_update_time or existing.exchange_create_time
                                )
                            original_side = (
                                existing.side.value if existing.side else (side or "BUY")
                            )
                            fill_price = (
                                order_price_float
                                or (float(existing.price) if existing.price else 0)
                                or 0
                            )
                            self._maybe_create_sl_tp_after_history_sync(
                                db,
                                existing,
                                symbol=symbol or existing.symbol,
                                side=original_side,
                                filled_price=fill_price,
                                filled_qty=executed_qty,
                                order_id=order_id,
                                order_filled_time=order_filled_time,
                                order_type_label="main",
                            )
                        elif is_sl_tp_order:
                            logger.debug(f"Skipping SL/TP creation for {order_type_from_history or order_type_from_db} order {order_id} - SL/TP orders should not create new SL/TP")
                    
                    # Already marked as processed before sending Telegram (see above)
                    continue  # Already synced to database
                
                # Create new order record (variables already extracted above)
                
                # Check if there's an existing order with this ID that might have oco_group_id
                # This happens when an order was created locally but then found in history
                existing_order_for_oco = db.query(ExchangeOrder).filter(ExchangeOrder.exchange_order_id == order_id).first()
                oco_group_id_from_existing = existing_order_for_oco.oco_group_id if existing_order_for_oco else None
                
                # For new orders from history, delta is the full executed qty (no previous state)
                protection_role = protection_role_from_order_data(order_data)
                raw_order_type = str(order_data.get('order_type', 'LIMIT') or 'LIMIT').upper()
                # Keep protection semantics when advanced history rewrites type to LIMIT after fill.
                if protection_role == "TAKE_PROFIT" and raw_order_type == "LIMIT":
                    stored_order_type = "TAKE_PROFIT_LIMIT"
                elif protection_role == "STOP_LOSS" and raw_order_type in ("LIMIT", "STOP_LIMIT"):
                    stored_order_type = "STOP_LIMIT"
                else:
                    stored_order_type = raw_order_type
                delta_qty = _to_decimal(executed_qty)
                new_order = ExchangeOrder(
                    exchange_order_id=order_id,
                    client_oid=order_data.get('client_oid'),
                    symbol=symbol,
                    side=OrderSideEnum.BUY if side == 'BUY' else OrderSideEnum.SELL,
                    order_type=stored_order_type,
                    status=OrderStatusEnum.FILLED,
                    price=order_price_float,  # Will use avg_price for MARKET orders
                    quantity=executed_qty,  # Use cumulative_quantity (executed amount)
                    cumulative_quantity=_to_decimal(order_data.get('cumulative_quantity') or 0),
                    cumulative_value=float(order_data.get('cumulative_value', 0)) if order_data.get('cumulative_value') else 0,
                    avg_price=float(order_data.get('avg_price')) if order_data.get('avg_price') else order_price_float,
                    exchange_create_time=create_time,
                    exchange_update_time=update_time,
                    oco_group_id=oco_group_id_from_existing,  # Preserve OCO group ID if it exists
                    order_role=protection_role,
                )
                db.add(new_order)
                logger.debug("[EXCHANGE_ORDERS_OWNER] exchange_sync upsert (history) order_id=%s symbol=%s", order_id, symbol)
                db.flush()  # Flush to get the order ID and relationships
                link_system_trade_signal_to_order(db, new_order)

                # Check if this is a SL or TP order that was executed - cancel the other one
                order_type_upper = stored_order_type
                is_sl_tp_executed = protection_role is not None or order_type_upper in [
                    'STOP_LIMIT', 'TAKE_PROFIT_LIMIT', 'STOP_LOSS', 'TAKE_PROFIT'
                ]
                
                if is_sl_tp_executed:
                    # CRITICAL: Always attempt to cancel the sibling order
                    # Try OCO group ID method first (most reliable if OCO group ID exists)
                    oco_success = False
                    if new_order.oco_group_id:
                        try:
                            logger.info(f"Attempting to cancel OCO sibling for new order {order_id} (group: {new_order.oco_group_id})")
                            oco_success = self._cancel_oco_sibling(db, new_order)
                            if oco_success:
                                logger.info(f"✅ OCO cancellation succeeded for new order {order_id}")
                            else:
                                logger.warning(f"⚠️ OCO cancellation returned False for new order {order_id}, will try fallback")
                        except Exception as oco_err:
                            logger.warning(f"Error canceling OCO sibling for new order {order_id}: {oco_err}")
                            oco_success = False
                    
                    # ALWAYS try the fallback method if OCO method didn't succeed
                    # This ensures cancellation works for both BUY and SELL orders
                    if not oco_success:
                        try:
                            logger.info(f"Attempting fallback cancellation for sibling of new order {order_id} (symbol: {symbol}, type: {order_type_upper})")
                            cancelled_count = self._cancel_remaining_sl_tp(db, symbol, order_type_upper, order_id)
                            if cancelled_count > 0:
                                logger.info(f"✅ Successfully cancelled {cancelled_count} sibling order(s) via fallback method for new order")
                            elif cancelled_count == 0:
                                # Check if sibling was already cancelled
                                logger.debug(f"No active {order_type_upper} orders found to cancel for new order - checking for already CANCELLED orders")
                                self._notify_already_cancelled_sl_tp(db, symbol, order_type_upper, order_id)
                        except Exception as cancel_err:
                            logger.error(f"❌ Error canceling remaining SL/TP for new order {order_id}: {cancel_err}", exc_info=True)
                
                # Track for marking as processed AFTER successful commit
                orders_processed_this_cycle.append(order_id)
                new_orders_count += 1
                
                # Create SL/TP for both LIMIT and MARKET orders when they are filled
                # (not for STOP_LIMIT or TAKE_PROFIT_LIMIT)
                # BUT: Only create SL/TP if the order was filled within the last hour
                order_type = stored_order_type
                
                # IMPORTANT: NEVER create SL/TP for STOP_LIMIT or TAKE_PROFIT_LIMIT orders
                # (including advanced contingency fills that arrive as LIMIT + contingency_type)
                if order_type in ['LIMIT', 'MARKET'] and not protection_role:
                    order_filled_time = update_time or create_time
                    fill_price = order_price_float or 0
                    self._maybe_create_sl_tp_after_history_sync(
                        db,
                        new_order,
                        symbol=symbol,
                        side=side,
                        filled_price=fill_price,
                        filled_qty=executed_qty,
                        order_id=order_id,
                        order_filled_time=order_filled_time,
                        order_type_label="new_main",
                    )
                elif order_type in ['STOP_LIMIT', 'TAKE_PROFIT_LIMIT'] or protection_role:
                    logger.debug(f"Skipping SL/TP creation for {order_type} order {order_id} - SL/TP orders should not create new SL/TP")
                
                # STRICT FILL-ONLY NOTIFICATION LOGIC for new orders
                # Only notify for real fills: status must be FILLED or PARTIALLY_FILLED with increased filled_qty
                fill_dedup = get_fill_dedup(db)
                current_filled_qty = executed_qty
                current_status_str = status_str if status_str in ('FILLED', 'PARTIALLY_FILLED') else None
                
                gate_ok_new, gate_reason_new = should_notify_executed_fill(
                    db=db,
                    order=new_order,
                    now_utc=datetime.now(timezone.utc),
                    source="sync_order_history",
                    requested_by_admin=False,
                )
                if not gate_ok_new:
                    should_notify, notify_reason = False, gate_reason_new
                    if current_status_str in ('FILLED', 'PARTIALLY_FILLED') and current_filled_qty > 0:
                        fill_dedup.record_fill(
                            order_id=order_id,
                            filled_qty=current_filled_qty,
                            status=current_status_str,
                            notification_sent=False,
                        )
                    logger.debug(f"Skipping notification for new order {order_id}: {gate_reason_new}")
                else:
                    should_notify, notify_reason = fill_dedup.should_notify_fill(
                        order_id=order_id,
                        current_filled_qty=current_filled_qty,
                        status=current_status_str or 'UNKNOWN'
                    ) if current_status_str else (False, f"Status {status_str} is not a fill status")
                
                # Send Telegram notification for new executed order with execution time
                if gate_ok_new and should_notify and current_status_str in ('FILLED', 'PARTIALLY_FILLED'):
                    try:
                        from app.services.telegram_notifier import telegram_notifier
                        
                        # Use the proper method for executed orders
                        total_usd = order_price_float * executed_qty if order_price_float and executed_qty else 0
                        order_type = order_data.get('order_type', 'LIMIT')
                        order_type_upper = order_type.upper()
                        
                        # If this is a SL or TP order, find the original entry order to calculate profit/loss
                        entry_price = None
                        if order_type_upper in ['STOP_LIMIT', 'TAKE_PROFIT_LIMIT']:
                            # Find the most recent BUY or SELL order (depending on side) for this symbol
                            # For SL/TP after BUY: find last BUY order
                            # For SL/TP after SELL: find last SELL order
                            # SL/TP after BUY means we're selling (SELL), so find last BUY
                            # SL/TP after SELL means we're buying (BUY), so find last SELL
                            if side == "SELL":
                                # This is selling, so find the original BUY order
                                original_order = db.query(ExchangeOrder).filter(
                                    ExchangeOrder.symbol == symbol,
                                    ExchangeOrder.side == "BUY",
                                    ExchangeOrder.status == OrderStatusEnum.FILLED,
                                    ExchangeOrder.order_type.in_(["MARKET", "LIMIT"]),
                                    ExchangeOrder.exchange_order_id != order_id  # Not the current order
                                ).order_by(ExchangeOrder.exchange_update_time.desc()).first()
                            else:  # side == "BUY"
                                # This is buying, so find the original SELL order (for short positions)
                                original_order = db.query(ExchangeOrder).filter(
                                    ExchangeOrder.symbol == symbol,
                                    ExchangeOrder.side == "SELL",
                                    ExchangeOrder.status == OrderStatusEnum.FILLED,
                                    ExchangeOrder.order_type.in_(["MARKET", "LIMIT"]),
                                    ExchangeOrder.exchange_order_id != order_id  # Not the current order
                                ).order_by(ExchangeOrder.exchange_update_time.desc()).first()
                            
                            if original_order:
                                # Use avg_price if available (more accurate for MARKET orders), otherwise price
                                entry_price = float(original_order.avg_price) if original_order.avg_price else float(original_order.price) if original_order.price else None
                                logger.info(f"Found entry price for SL/TP order {order_id}: {entry_price} from order {original_order.exchange_order_id}")
                        
                        # Count open entry BUY orders for this symbol (SL/TP excluded, see helper)
                        open_orders_count = _count_open_entry_buy_orders(db, symbol)
                        
                        # Get order_role, trade_signal_id, and parent_order_id from the order if it exists in database
                        order_role = None
                        trade_signal_id = None
                        parent_order_id = None
                        if order_id:
                            existing_order = db.query(ExchangeOrder).filter(
                                ExchangeOrder.exchange_order_id == order_id
                            ).first()
                            if existing_order:
                                # Last-chance link retry: the TradeSignal may have been
                                # committed after the earlier link attempt; without this
                                # bot-created orders are notified as "Origen: Manual".
                                if existing_order.trade_signal_id is None:
                                    link_system_trade_signal_to_order(db, existing_order)
                                order_role = existing_order.order_role
                                trade_signal_id = existing_order.trade_signal_id
                                parent_order_id = existing_order.parent_order_id
                        
                        # Infer order_role from order_type if order_role is not set
                        # CRITICAL: Only set role if order_type clearly indicates it (STOP_LIMIT, TAKE_PROFIT_LIMIT)
                        # Do NOT mislabel BUY orders as Stop Loss
                        if not order_role and order_type:
                            order_type_upper = order_type.upper()
                            if order_type_upper == 'STOP_LIMIT':
                                order_role = 'STOP_LOSS'
                            elif order_type_upper == 'TAKE_PROFIT_LIMIT':
                                order_role = 'TAKE_PROFIT'
                            # For other order types, leave as None (don't mislabel)
                        
                        # Audit log: JSON-serializable (Decimal/datetime via make_json_safe)
                        audit_log = make_json_safe({
                            "event": "ORDER_EXECUTED_NOTIFICATION",
                            "symbol": symbol,
                            "side": side,
                            "order_id": order_id,
                            "status": current_status_str,
                            "cumulative_quantity": current_filled_qty,
                            "delta_quantity": float(delta_qty),
                            "price": order_price_float or 0,
                            "avg_price": order_data.get('avg_price'),
                            "order_type": order_type,
                            "order_role": order_role,
                            "client_oid": order_data.get('client_oid'),
                            "trade_signal_id": trade_signal_id,
                            "parent_order_id": parent_order_id,
                            "notify_reason": notify_reason,
                            "handler": "exchange_sync.new_order"
                        })
                        logger.info(f"[FILL_NOTIFICATION] {json.dumps(audit_log)}")
                        
                        result = telegram_notifier.send_executed_order(
                            symbol=symbol,
                            side=side,
                            price=order_price_float or 0,
                            quantity=current_filled_qty,
                            total_usd=total_usd,
                            order_id=order_id,
                            order_type=order_type,
                            entry_price=entry_price,  # Add entry_price for profit/loss calculation
                            open_orders_count=open_orders_count,  # Add open orders count for monitoring
                            order_role=order_role,  # Use inferred role if order_role is not set
                            trade_signal_id=trade_signal_id,  # Pass trade_signal_id to determine if order was created by alert
                            parent_order_id=parent_order_id  # Pass parent_order_id to determine if order is SL/TP
                        )
                        if result:
                            new_order.execution_notified_at = datetime.now(timezone.utc)
                            try:
                                db.flush()
                            except Exception as flush_err:
                                logger.warning(
                                    "Failed to flush execution_notified_at for %s: %s",
                                    order_id,
                                    flush_err,
                                )
                            # Record fill in persistent tracker (Postgres or SQLite per USE_DB_FILL_DEDUP)
                            fill_dedup.record_fill(
                                order_id=order_id,
                                filled_qty=current_filled_qty,
                                status=current_status_str,
                                notification_sent=True
                            )
                            logger.info(f"Sent Telegram notification for executed order: {symbol} {side} - {order_id} (reason: {notify_reason})")
                        else:
                            logger.warning(f"Failed to send Telegram notification for executed order: {symbol} {side} - {order_id}")
                    except Exception as telegram_err:
                        logger.warning(f"Failed to send Telegram notification: {telegram_err}")
                else:
                    # Record fill even if we don't notify (for tracking)
                    if current_status_str in ('FILLED', 'PARTIALLY_FILLED') and current_filled_qty > 0:
                        fill_dedup.record_fill(
                            order_id=order_id,
                            filled_qty=current_filled_qty,
                            status=current_status_str,
                            notification_sent=False
                        )
                    if current_status_str not in ('FILLED', 'PARTIALLY_FILLED'):
                        logger.debug(f"Skipping notification for new order {order_id}: status={status_str} is not a fill status")
                    else:
                        logger.debug(f"Skipping notification for new order {order_id}: {notify_reason}")
            
            # Always commit to ensure status updates are saved
            # Even if SL/TP creation fails, we want to save the order status update
            try:
                db.commit()
                # CRITICAL FIX: Mark orders as processed ONLY AFTER successful commit
                # This prevents orders from being skipped in future syncs if commit fails
                for order_id in orders_processed_this_cycle:
                    self._mark_order_processed(order_id)
                
                if new_orders_count > 0:
                    logger.info(f"✅ Committed: Synced {new_orders_count} executed orders from history (new + updated), marked {len(orders_processed_this_cycle)} as processed")
                else:
                    if filled_count > 0:
                        logger.debug(f"No new executed orders to sync (all {filled_count} filled orders already in DB or updated)")
                    else:
                        logger.debug("No filled orders found in API history")
            except Exception as commit_err:
                logger.error(f"Error committing order history updates: {commit_err}", exc_info=True)
                db.rollback()
                # Do NOT mark orders as processed if commit failed - they should be retried in next sync
                raise
            return new_orders_count

        except Exception as e:
            logger.error(f"Error syncing order history: {e}", exc_info=True)
            log_critical_failure(
                message=str(e)[:500],
                error_code="SYNC_ORDER_HISTORY",
            )
            # Check if it's an authentication error
            if "40101" in str(e) or "Authentication" in str(e):
                logger.warning("Authentication error when syncing order history - check API credentials")
            try:
                db.rollback()
            except Exception:
                pass
            return 0

    def _run_open_orders_sync_sync(self, db: Session):
        """Refresh open-orders cache and DB rows — fast path, must not wait on order history."""
        self.sync_open_orders(db)

    def _run_background_sync_sync(self, db: Session):
        """Run balances and order-history sync — may be slow; runs independently of open orders."""
        self.sync_balances(db)
        history_started = time.monotonic()
        logger.info("sync_order_history start")
        try:
            self.sync_order_history(db, page_size=200, max_pages=10)
            logger.info(
                "sync_order_history end duration=%.2fs",
                time.monotonic() - history_started,
            )
        except Exception as e:
            logger.error(
                "sync_order_history failed duration=%.2fs error=%s",
                time.monotonic() - history_started,
                e,
                exc_info=True,
            )

    def _run_sync_sync(self, db: Session):
        """Legacy combined cycle — kept for tests; production uses split loops."""
        self._run_background_sync_sync(db)
        self._run_open_orders_sync_sync(db)

    async def run_open_orders_sync(self):
        """Run one open-orders refresh cycle."""
        if SessionLocal is None:
            logger.warning("Database not available (SessionLocal is None), skipping open orders sync")
            return
        db = SessionLocal()
        try:
            await asyncio.to_thread(self._run_open_orders_sync_sync, db)
            self.last_open_orders_sync = datetime.now(timezone.utc)
        finally:
            db.close()

    async def run_background_sync(self):
        """Run one balances + order-history cycle with timeout on history scan."""
        if SessionLocal is None:
            logger.warning("Database not available (SessionLocal is None), skipping background sync")
            return
        db = SessionLocal()
        try:
            await asyncio.to_thread(self.sync_balances, db)
            history_started = time.monotonic()
            logger.info("sync_order_history start")
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(self.sync_order_history, db, page_size=200, max_pages=10),
                    timeout=self.order_history_timeout,
                )
                logger.info(
                    "sync_order_history end duration=%.2fs",
                    time.monotonic() - history_started,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "sync_order_history timed out after %.2fs (limit=%ds) — open orders refresh continues independently",
                    time.monotonic() - history_started,
                    self.order_history_timeout,
                )
            except Exception as e:
                logger.error(
                    "sync_order_history failed duration=%.2fs error=%s",
                    time.monotonic() - history_started,
                    e,
                    exc_info=True,
                )
            self.last_sync = datetime.now(timezone.utc)
        finally:
            db.close()

    async def run_sync(self):
        """Run one full sync cycle (background + open orders) — async wrapper."""
        await self.run_background_sync()
        await self.run_open_orders_sync()

    async def _open_orders_loop(self):
        """Independent loop: refresh open-orders cache quickly and often."""
        await asyncio.sleep(self.startup_open_orders_delay)
        logger.info(
            "Open orders sync loop starting (interval=%ds, startup_delay=%ds)",
            self.open_orders_sync_interval,
            self.startup_open_orders_delay,
        )
        while self.is_running:
            try:
                await self.run_open_orders_sync()
            except Exception as e:
                logger.error("Error in open orders sync cycle: %s", e, exc_info=True)
            await asyncio.sleep(self.open_orders_sync_interval)

    async def _background_sync_loop(self):
        """Independent loop: balances and order history — may run for minutes."""
        await asyncio.sleep(self.background_sync_startup_delay)
        logger.info(
            "Background sync loop starting (interval=%ds, startup_delay=%ds, order_history_timeout=%ds)",
            self.sync_interval,
            self.background_sync_startup_delay,
            self.order_history_timeout,
        )
        while self.is_running:
            try:
                await self.run_background_sync()
            except Exception as e:
                logger.error("Error in background sync cycle: %s", e, exc_info=True)
            await asyncio.sleep(self.sync_interval)

    async def start(self):
        """Start the sync service with independent open-orders and background loops."""
        if self.is_running:
            logger.warning("⚠️ Exchange sync service is already running, skipping duplicate start")
            return
        self.is_running = True
        logger.info("🚀 Exchange sync service started (open orders + background loops)")

        open_orders_task = asyncio.create_task(self._open_orders_loop())
        background_task = asyncio.create_task(self._background_sync_loop())
        try:
            await asyncio.gather(open_orders_task, background_task)
        finally:
            self.is_running = False
    
    def stop(self):
        """Stop the sync service"""
        self.is_running = False
        logger.info("Exchange sync service stopped")


# Global instance
exchange_sync_service = ExchangeSyncService()
