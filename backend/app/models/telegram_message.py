"""Database model for storing Telegram messages"""
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, Index
from sqlalchemy.sql import func
from app.database import Base


class TelegramMessage(Base):
    """Model for storing Telegram messages (sent and blocked)
    
    Field semantics:
    - blocked: Alert was blocked (technical/guardrail errors). When True, alert was NOT sent.
    - order_skipped: Order was skipped due to position limits. When True, alert WAS sent but order was not created.
    
    IMPORTANT: Position limits block ORDERS, not ALERTS.
    When order_skipped=True, blocked must be False (alert was sent).
    """
    __tablename__ = "telegram_messages"
    
    id = Column(Integer, primary_key=True, index=True)
    message = Column(Text, nullable=False)
    symbol = Column(String(50), nullable=True, index=True)
    blocked = Column(Boolean, nullable=False, default=False, index=True)  # Alert blocked (not sent)
    order_skipped = Column(Boolean, nullable=False, default=False, index=True)  # Order skipped (alert was sent)
    throttle_status = Column(String(20), nullable=True)
    throttle_reason = Column(Text, nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    
    # Index for efficient queries
    __table_args__ = (
        Index('ix_telegram_messages_symbol_blocked', 'symbol', 'blocked'),
    )
    
    def __repr__(self):
        return (
            f"<TelegramMessage(id={self.id}, symbol={self.symbol}, blocked={self.blocked}, "
            f"order_skipped={self.order_skipped}, status={self.throttle_status}, timestamp={self.timestamp})>"
        )

