"""Week 5: Model for dedup_events table (actionable event deduplication with TTL)."""
from sqlalchemy import Column, Integer, String, Text, DateTime, UniqueConstraint, Index
from sqlalchemy.sql import func
from app.database import Base


class DedupEventWeek5(Base):
    __tablename__ = "dedup_events"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    key = Column(String(128), nullable=False, index=True, unique=True)
    correlation_id = Column(String(64), nullable=True)
    symbol = Column(String(50), nullable=True)
    action = Column(String(32), nullable=True)
    payload_json = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("key", name="uq_dedup_events_key"),
        Index("ix_dedup_events_created_at", "created_at"),
    )
