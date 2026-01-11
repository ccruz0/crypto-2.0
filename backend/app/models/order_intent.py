"""Database model for order intents (atomic deduplication)"""
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, Index, UniqueConstraint
from sqlalchemy.sql import func
from app.database import Base


class OrderIntent(Base):
    """Model for storing order intents with atomic deduplication
    
    This table ensures that each signal (identified by idempotency_key) can only
    trigger one order attempt. The UNIQUE constraint on idempotency_key provides
    atomic deduplication at the database level.
    """
    __tablename__ = "order_intents"
    
    id = Column(Integer, primary_key=True, index=True)
    idempotency_key = Column(String(200), nullable=False, unique=True, index=True)  # UNIQUE for atomic dedup
    signal_id = Column(Integer, nullable=True, index=True)  # Reference to telegram_messages.id
    symbol = Column(String(50), nullable=False, index=True)
    side = Column(String(10), nullable=False, index=True)  # "BUY" or "SELL"
    status = Column(String(20), nullable=False, default="PENDING", index=True)  # PENDING, ORDER_PLACED, ORDER_FAILED, DEDUP_SKIPPED
    order_id = Column(String(100), nullable=True, index=True)  # Exchange order ID if placed
    error_message = Column(Text, nullable=True)  # Error message if failed
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Index for efficient queries
    __table_args__ = (
        UniqueConstraint('idempotency_key', name='uq_order_intent_idempotency_key'),
        Index('ix_order_intents_signal_id', 'signal_id'),
        Index('ix_order_intents_symbol_side', 'symbol', 'side'),
    )
    
    def __repr__(self):
        return (
            f"<OrderIntent(id={self.id}, idempotency_key={self.idempotency_key[:20]}..., "
            f"symbol={self.symbol}, side={self.side}, status={self.status}, order_id={self.order_id})>"
        )
