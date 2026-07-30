"""Database models for the Telegram logic watchdog.

The watchdog is a *meta* monitor: it compares what the exchange/DB says
actually happened against what the Telegram alerts reported, and records
any logic inconsistency as a WatchdogAnomaly.

Each anomaly is alerted once to Telegram with inline buttons:
  - Ignore    -> status becomes 'ignored', never re-alerted
  - Fix code  -> a WatchdogFixRequest row is queued for the Cowork fixer

Dedup is by `fingerprint` (unique), so a recurring condition updates
last_seen_at / occurrences instead of spamming the channel.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Integer, String, Text, DateTime, Index
from sqlalchemy.sql import func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


# Lifecycle: new -> alerted -> (ignored | fix_requested -> fixed | failed)
ANOMALY_STATUS_NEW = "new"
ANOMALY_STATUS_ALERTED = "alerted"
ANOMALY_STATUS_IGNORED = "ignored"
ANOMALY_STATUS_FIX_REQUESTED = "fix_requested"
ANOMALY_STATUS_FIXED = "fixed"

FIX_STATUS_PENDING = "pending"
FIX_STATUS_IN_PROGRESS = "in_progress"
FIX_STATUS_DONE = "done"
FIX_STATUS_FAILED = "failed"


class WatchdogAnomaly(Base):
    """One detected logic inconsistency."""

    __tablename__ = "watchdog_anomalies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # sha1 of (kind|symbol|anchor_id) - stable across runs so we alert once
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="medium", index=True)
    symbol: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # JSON blob: order ids, prices, timestamps - what the fixer needs
    evidence_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Newline-separated file paths / function names that likely own the bug
    suspect_paths: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default=ANOMALY_STATUS_NEW, index=True)
    occurrences: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    alerted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Telegram message id of the alert carrying the buttons (so we can edit it)
    telegram_message_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    telegram_chat_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    __table_args__ = (
        Index("ix_watchdog_anomalies_status_severity", "status", "severity"),
    )

    def __repr__(self) -> str:
        return (
            f"<WatchdogAnomaly(id={self.id}, kind={self.kind}, symbol={self.symbol}, "
            f"severity={self.severity}, status={self.status})>"
        )


class WatchdogFixRequest(Base):
    """Queued 'fix the code' request, drained by the Cowork fixer task."""

    __tablename__ = "watchdog_fix_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    anomaly_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default=FIX_STATUS_PENDING, index=True)
    requested_by: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    branch: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    commit_sha: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    result_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<WatchdogFixRequest(id={self.id}, anomaly_id={self.anomaly_id}, status={self.status})>"
