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
    
    Decision tracing fields:
    - decision_type: "SKIPPED" or "FAILED" - whether the buy was skipped before attempt or failed during attempt
    - reason_code: Canonical reason code (e.g., "TRADE_DISABLED", "EXCHANGE_REJECTED")
    - reason_message: Human-readable reason message
    - context_json: JSON object with contextual data (prices, balances, thresholds, etc.)
    - exchange_error_snippet: Raw exchange error message for FAILED decisions
    - correlation_id: Optional correlation ID for tracing across logs
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
    
    # Decision tracing fields (new)
    decision_type = Column(String(50), nullable=True)  # "SKIPPED" or "FAILED"
    reason_code = Column(String(100), nullable=True, index=True)  # Canonical reason code
    reason_message = Column(String(500), nullable=True)  # Human-readable reason (DB: varchar 500)
    context_json = Column(Text, nullable=True)  # Contextual data stored as JSON text (DB: text)
    exchange_error_snippet = Column(Text, nullable=True)  # Raw exchange error for FAILED decisions
    correlation_id = Column(String(100), nullable=True, index=True)  # Correlation ID for tracing
    
    # Index for efficient queries
    __table_args__ = (
        Index('ix_telegram_messages_symbol_blocked', 'symbol', 'blocked'),
    )
    
    def __repr__(self):
        return (
            f"<TelegramMessage(id={self.id}, symbol={self.symbol}, blocked={self.blocked}, "
            f"order_skipped={self.order_skipped}, status={self.throttle_status}, "
            f"decision_type={self.decision_type}, reason_code={self.reason_code}, timestamp={self.timestamp})>"
        )

