"""Database model for the daily Position Review alert (open-position close prompts + snooze).

One row per open position, keyed by ``position_key`` = "{symbol}:{side}" (e.g.
"DOT_USD:SHORT"). Tracks whether the operator has snoozed close-prompts for it and enough
state to detect that a position was closed and later re-opened (a re-opened position is a
NEW case and must be prompted again even if the old one was snoozed).
"""
from sqlalchemy import Column, Integer, String, DateTime, Numeric
from sqlalchemy.sql import func

from app.database import Base


class PositionReviewState(Base):
    """Per-position snooze / lifecycle state for the daily position-review prompts."""
    __tablename__ = "position_review_state"

    id = Column(Integer, primary_key=True, index=True)
    # "{symbol}:{side}" — e.g. "DOT_USD:SHORT". Unique: one row per (symbol, side).
    position_key = Column(String(60), nullable=False, unique=True, index=True)
    # Do not prompt again until this instant (set when the operator taps "Keep 30 days").
    snoozed_until = Column(DateTime(timezone=True), nullable=True, index=True)
    # Last observed |quantity|. 0 means "was closed / not currently open" — used to detect
    # a close->reopen transition (which resets the snooze so it's treated as a new case).
    last_seen_qty = Column(Numeric(30, 10), nullable=False, default=0)
    last_alerted_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return (
            f"<PositionReviewState(key={self.position_key}, "
            f"snoozed_until={self.snoozed_until}, last_seen_qty={self.last_seen_qty})>"
        )
