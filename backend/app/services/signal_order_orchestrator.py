"""
Signal-to-Order Orchestrator

This module orchestrates the execution of orders immediately after a signal is sent.
It ensures that every signal marked as "sent" triggers an order attempt, with only
deduplication as the safeguard.

Invariant: If a signal is marked as "sent", an order MUST be attempted immediately.
The ONLY safeguard is deduplication (idempotency_key).
"""
import logging
import hashlib
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.models.order_intent import OrderIntent
from app.utils.symbols import normalize_symbol_for_exchange
from app.utils.live_trading import get_live_trading_status
from app.utils.decision_reason import make_skip, ReasonCode

logger = logging.getLogger(__name__)


def compute_idempotency_key(
    signal_id: Optional[int],
    symbol: str,
    side: str,
    strategy_key: Optional[str] = None,
    price: Optional[float] = None,
    message_content: Optional[str] = None,
    now: Optional[datetime] = None,
) -> str:
    """
    Compute deterministic idempotency key for order deduplication.

    Priority:
    1. If signal_id is present: use signal_id-based key (idempotent forever)
    2. Otherwise: use content-based hash with message_content + normalized symbol

    Args:
        signal_id: Telegram message ID (preferred, makes key idempotent forever)
        symbol: Trading symbol (will be normalized)
        side: Order side ("BUY" or "SELL")
        strategy_key: Strategy key (optional but preferred for determinism)
        price: Optional price for bucketed stability
        message_content: Optional message content (used for idempotency when signal_id is missing)
        now: Optional fixed time for testing

    Returns:
        Idempotency key string
    """
    normalized_symbol = normalize_symbol_for_exchange(symbol)
    side_upper = side.upper()

    if signal_id:
        # Preferred: use signal_id (idempotent forever, no timestamp bucket)
        return f"signal:{signal_id}:side:{side_upper}"

    # Content-based idempotency when signal_id is missing
    # Use message_content + normalized symbol for deterministic key
    if message_content:
        # Hash normalized symbol + message content for stable idempotency
        content_str = message_content.strip()[:500]  # Limit length for safety
        raw_key = f"{normalized_symbol}|{content_str}"
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    
    # Fallback: use time-bucketed hash if no message_content provided
    current_time = now or datetime.now(timezone.utc)
    bucket_minute = current_time.minute - (current_time.minute % 5)
    bucketed_time = current_time.replace(minute=bucket_minute, second=0, microsecond=0)
    time_bucket = bucketed_time.strftime("%Y%m%d%H%M")
    strategy_value = strategy_key or "UNKNOWN"

    if price is not None:
        price_bucket = f"{price:.2f}"
        raw_key = f"{side_upper}|{normalized_symbol}|{strategy_value}|{time_bucket}|{price_bucket}"
    else:
        raw_key = f"{side_upper}|{normalized_symbol}|{strategy_value}|{time_bucket}"
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def create_order_intent(
    db: Session,
    signal_id: Optional[int],
    symbol: str,
    side: str,
    message_content: Optional[str] = None,
    strategy_key: Optional[str] = None,
    price: Optional[float] = None,
    now: Optional[datetime] = None,
) -> tuple[Optional[OrderIntent], str]:
    """
    Create order intent with atomic deduplication.
    
    Returns:
        Tuple of (OrderIntent or None, status)
        - If duplicate: (None, "DEDUP_SKIPPED")
        - If LIVE_TRADING=false: (OrderIntent with status ORDER_BLOCKED_LIVE_TRADING, "ORDER_BLOCKED_LIVE_TRADING")
        - If success: (OrderIntent with status PENDING, "PENDING")
    """
    # Compute idempotency key
    normalized_symbol = normalize_symbol_for_exchange(symbol)
    idempotency_key = compute_idempotency_key(
        signal_id=signal_id,
        symbol=normalized_symbol,
        side=side,
        strategy_key=strategy_key,
        price=price,
        message_content=message_content,
        now=now,
    )
    
    logger.info(
        f"[ORCHESTRATOR] {normalized_symbol} {side} signal_id={signal_id} idempotency_key={idempotency_key[:50]}... "
        f"Creating order intent"
    )
    
    # Check LIVE_TRADING status (this is the ONLY check allowed after signal sent)
    live_trading = get_live_trading_status(db)
    if not live_trading:
        logger.info(f"[ORCHESTRATOR] {normalized_symbol} {side} LIVE_TRADING=false - Order blocked but signal was sent")
        
        # Create order intent with BLOCKED status
        try:
            order_intent = OrderIntent(
                idempotency_key=idempotency_key,
                signal_id=signal_id,
                symbol=normalized_symbol,
                side=side,
                status="ORDER_BLOCKED_LIVE_TRADING",
                error_message="LIVE_TRADING is disabled",
            )
            db.add(order_intent)
            db.commit()
            return order_intent, "ORDER_BLOCKED_LIVE_TRADING"
        except IntegrityError:
            # Duplicate idempotency_key
            db.rollback()
            logger.warning(f"[ORCHESTRATOR] {normalized_symbol} {side} Duplicate idempotency_key detected (LIVE_TRADING=false path)")
            existing = db.query(OrderIntent).filter(OrderIntent.idempotency_key == idempotency_key).first()
            return existing, "DEDUP_SKIPPED"
    
    # Try to insert order intent (atomic deduplication)
    try:
        order_intent = OrderIntent(
            idempotency_key=idempotency_key,
            signal_id=signal_id,
            symbol=normalized_symbol,
            side=side,
            status="PENDING",
        )
        db.add(order_intent)
        db.commit()
        logger.info(f"[ORCHESTRATOR] {normalized_symbol} {side} Order intent created: id={order_intent.id}")
        return order_intent, "PENDING"
    except IntegrityError:
        # Duplicate idempotency_key - this signal was already processed
        db.rollback()
        logger.warning(f"[ORCHESTRATOR] {normalized_symbol} {side} DEDUP_SKIPPED - Duplicate idempotency_key: {idempotency_key[:50]}...")
        existing = db.query(OrderIntent).filter(OrderIntent.idempotency_key == idempotency_key).first()
        return existing, "DEDUP_SKIPPED"


def update_order_intent_status(
    db: Session,
    order_intent_id: int,
    status: str,
    order_id: Optional[str] = None,
    error_message: Optional[str] = None,
):
    """Update order intent status after order attempt."""
    order_intent = db.query(OrderIntent).filter(OrderIntent.id == order_intent_id).first()
    if order_intent:
        order_intent.status = status
        if order_id:
            order_intent.order_id = order_id
        if error_message:
            order_intent.error_message = error_message
        db.commit()
        logger.info(f"[ORCHESTRATOR] Order intent {order_intent_id} updated: status={status}, order_id={order_id}")
