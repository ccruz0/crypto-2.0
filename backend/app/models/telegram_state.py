"""Model for storing Telegram polling state"""
from sqlalchemy import Column, Integer, DateTime
from sqlalchemy.sql import func
from app.database import Base


class TelegramState(Base):
    """Store Telegram polling state (last update ID)"""
    __tablename__ = "telegram_state"
    
    id = Column(Integer, primary_key=True, default=1)  # Single row
    last_update_id = Column(Integer, default=0, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    def __repr__(self):
        return f"<TelegramState(last_update_id={self.last_update_id}, updated_at={self.updated_at})>"

