"""Persistent approval state for agent task execution."""
from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.sql import func

from app.database import Base


class AgentApprovalState(Base):
    """Store approval requests and decisions for Telegram-driven agent execution."""

    __tablename__ = "agent_approval_states"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String(255), nullable=False, unique=True, index=True)
    status = Column(String(20), nullable=False, default="pending", index=True)
    requested_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    approved_by = Column(String(255), nullable=True)
    decision_at = Column(DateTime(timezone=True), nullable=True, index=True)
    approval_summary = Column(Text, nullable=True)
    prepared_bundle_json = Column(Text, nullable=True)
    execution_status = Column(String(20), nullable=True, default="not_started", index=True)
    execution_started_at = Column(DateTime(timezone=True), nullable=True, index=True)
    executed_at = Column(DateTime(timezone=True), nullable=True, index=True)
    execution_summary = Column(Text, nullable=True)
    retry_count = Column(Integer, nullable=False, default=0, server_default="0")

    def __repr__(self):
        return f"<AgentApprovalState(task_id={self.task_id}, status={self.status})>"
