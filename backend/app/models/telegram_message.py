"""Database model for storing Telegram messages"""
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, Index
from sqlalchemy.sql import func
from app.database import Base


class TelegramMessage(Base):
    """Model for storing Telegram messages (sent and blocked)"""
    __tablename__ = "telegram_messages"
    
    id = Column(Integer, primary_key=True, index=True)
    message = Column(Text, nullable=False)
    symbol = Column(String(50), nullable=True, index=True)
    blocked = Column(Boolean, nullable=False, default=False, index=True)
    throttle_status = Column(String(20), nullable=True)
    throttle_reason = Column(Text, nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    
    # Index for efficient queries
    __table_args__ = (
        Index('ix_telegram_messages_timestamp', 'timestamp'),
        Index('ix_telegram_messages_symbol_blocked', 'symbol', 'blocked'),
    )
    
    def __repr__(self):
        return (
            f"<TelegramMessage(id={self.id}, symbol={self.symbol}, blocked={self.blocked}, "
            f"status={self.throttle_status}, timestamp={self.timestamp})>"
        )

