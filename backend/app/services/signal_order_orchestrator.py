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
from app.utils.live_trading import get_live_trading_status
from app.utils.decision_reason import make_skip, ReasonCode

logger = logging.getLogger(__name__)


def compute_idempotency_key(
    signal_id: Optional[int],
    symbol: str,
    side: str,
    message_content: Optional[str] = None,
) -> str:
    """
    Compute deterministic idempotency key for order deduplication.
    
    Priority:
    1. Use telegram_messages.id as signal_id if available (most reliable)
    2. Otherwise, use content-hash + 60s bucket (fallback)
    
    Args:
        signal_id: Telegram message ID (preferred)
        symbol: Trading symbol
        side: Order side ("BUY" or "SELL")
        message_content: Message content (for fallback hash)
    
    Returns:
        Idempotency key string
    """
    env = "AWS"  # Could be made configurable
    timestamp_bucket = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    timestamp_str = timestamp_bucket.isoformat()
    
    if signal_id:
        # Preferred: use telegram_messages.id
        key = f"{env}:{symbol}:{side}:{signal_id}:{timestamp_str}"
    elif message_content:
        # Fallback: content-hash + 60s bucket
        content_hash = hashlib.sha256(message_content.encode()).hexdigest()[:16]
        key = f"{env}:{symbol}:{side}:{content_hash}:{timestamp_str}"
    else:
        # Last resort: UUID (not ideal, but ensures uniqueness)
        fallback_id = str(uuid.uuid4())[:16]
        key = f"{env}:{symbol}:{side}:{fallback_id}:{timestamp_str}"
    
    return key


def create_order_intent(
    db: Session,
    signal_id: Optional[int],
    symbol: str,
    side: str,
    message_content: Optional[str] = None,
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
    idempotency_key = compute_idempotency_key(signal_id, symbol, side, message_content)
    
    logger.info(
        f"[ORCHESTRATOR] {symbol} {side} signal_id={signal_id} idempotency_key={idempotency_key[:50]}... "
        f"Creating order intent"
    )
    
    # Check LIVE_TRADING status (this is the ONLY check allowed after signal sent)
    live_trading = get_live_trading_status(db)
    if not live_trading:
        logger.info(f"[ORCHESTRATOR] {symbol} {side} LIVE_TRADING=false - Order blocked but signal was sent")
        
        # Create order intent with BLOCKED status
        try:
            order_intent = OrderIntent(
                idempotency_key=idempotency_key,
                signal_id=signal_id,
                symbol=symbol,
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
            logger.warning(f"[ORCHESTRATOR] {symbol} {side} Duplicate idempotency_key detected (LIVE_TRADING=false path)")
            return None, "DEDUP_SKIPPED"
    
    # Try to insert order intent (atomic deduplication)
    try:
        order_intent = OrderIntent(
            idempotency_key=idempotency_key,
            signal_id=signal_id,
            symbol=symbol,
            side=side,
            status="PENDING",
        )
        db.add(order_intent)
        db.commit()
        logger.info(f"[ORCHESTRATOR] {symbol} {side} Order intent created: id={order_intent.id}")
        return order_intent, "PENDING"
    except IntegrityError:
        # Duplicate idempotency_key - this signal was already processed
        db.rollback()
        logger.warning(f"[ORCHESTRATOR] {symbol} {side} DEDUP_SKIPPED - Duplicate idempotency_key: {idempotency_key[:50]}...")
        return None, "DEDUP_SKIPPED"


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
