"""
SQLAlchemy models for Jarvis Control Center (sessions, tasks, approvals, audit).

Separate from jarvis_task_runs (LangGraph MVP Advisor history). Builder/Operator
lifecycle and dashboard approvals persist here. See docs/architecture/JARVIS_CONTROL_CENTER_IMPLEMENTATION_PLAN.md.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.sql import func

from app.database import Base


class JarvisControlSession(Base):
    """User or system-initiated Control Center session (groups related tasks)."""

    __tablename__ = "jarvis_control_sessions"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(128), nullable=False, unique=True, index=True)
    created_by = Column(String(255), nullable=False, default="system")
    default_mode = Column(String(32), nullable=False, default="advisor", index=True)
    environment = Column(String(16), nullable=False, default="prod")
    domain = Column(String(32), nullable=False, default="general")
    status = Column(String(32), nullable=False, default="active", index=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class JarvisControlTask(Base):
    """Primary Control Center work unit (Advisor / Builder / Operator)."""

    __tablename__ = "jarvis_control_tasks"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String(128), nullable=False, unique=True, index=True)
    session_id = Column(
        String(128),
        ForeignKey("jarvis_control_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mode = Column(String(32), nullable=False, default="advisor", index=True)
    domain = Column(String(32), nullable=False, default="general")
    prompt = Column(Text, nullable=False, default="")
    status = Column(String(32), nullable=False, default="queued", index=True)
    risk_level = Column(String(16), nullable=False, default="low")
    dry_run = Column(Boolean, nullable=False, default=True)
    plan_json = Column(Text, nullable=True)
    tool_results_json = Column(Text, nullable=True)
    final_answer = Column(Text, nullable=True)
    estimated_cost_usd = Column(Numeric, nullable=True)
    builder_artifact_json = Column(Text, nullable=True)
    governance_task_id = Column(String(128), nullable=True, index=True)
    legacy_task_run_id = Column(String(128), nullable=True, index=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class JarvisControlApproval(Base):
    """Human approval gate for Control Center tasks (dashboard / Telegram parity)."""

    __tablename__ = "jarvis_control_approvals"

    id = Column(Integer, primary_key=True, index=True)
    approval_id = Column(String(128), nullable=False, unique=True, index=True)
    task_id = Column(
        String(128),
        ForeignKey("jarvis_control_tasks.task_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action_id = Column(String(128), nullable=True, index=True)
    approval_status = Column(String(32), nullable=False, default="pending", index=True)
    execution_status = Column(String(32), nullable=False, default="not_executed")
    risk_level = Column(String(16), nullable=False, default="medium")
    scope_summary = Column(String(2000), nullable=True)
    digest = Column(String(128), nullable=True, index=True)
    allowed_envs = Column(String(64), nullable=True)
    requested_by = Column(String(255), nullable=False, default="jarvis")
    approved_by = Column(String(255), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    governance_manifest_id = Column(String(128), nullable=True)
    agent_approval_state_id = Column(Integer, nullable=True)
    telegram_message_id = Column(String(64), nullable=True)
    execution_result_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class JarvisControlAuditEvent(Base):
    """Append-only audit log for Control Center activity."""

    __tablename__ = "jarvis_control_audit_events"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(String(128), nullable=False, unique=True, index=True)
    task_id = Column(String(128), nullable=True, index=True)
    session_id = Column(String(128), nullable=True, index=True)
    approval_id = Column(String(128), nullable=True, index=True)
    ts = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    type = Column(String(64), nullable=False, index=True)
    actor_type = Column(String(32), nullable=False, default="system")
    actor_id = Column(String(255), nullable=True)
    environment = Column(String(16), nullable=False, default="prod")
    payload_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
