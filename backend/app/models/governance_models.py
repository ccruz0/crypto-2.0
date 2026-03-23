"""
SQLAlchemy models for ATP governance (tasks, events, manifests).

Separate from agent_approval_states: that table tracks Telegram agent execution bundles;
governance_* tracks cross-cutting PROD mutation control and audit (see docs/governance/).
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from app.database import Base


class GovernanceTask(Base):
    __tablename__ = "governance_tasks"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String(128), nullable=False, unique=True, index=True)
    source_type = Column(String(64), nullable=False, default="manual")
    source_ref = Column(String(512), nullable=True)
    status = Column(String(32), nullable=False, default="requested", index=True)
    risk_level = Column(String(16), nullable=False, default="medium")
    current_manifest_id = Column(String(128), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class GovernanceEvent(Base):
    __tablename__ = "governance_events"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String(128), nullable=False, index=True)
    event_id = Column(String(128), nullable=False, unique=True, index=True)
    ts = Column(DateTime(timezone=True), nullable=False)
    type = Column(String(32), nullable=False, index=True)
    actor_type = Column(String(32), nullable=False)
    actor_id = Column(String(255), nullable=True)
    environment = Column(String(16), nullable=False, default="prod")
    payload_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class GovernanceManifest(Base):
    __tablename__ = "governance_manifests"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String(128), nullable=False, index=True)
    manifest_id = Column(String(128), nullable=False, unique=True, index=True)
    digest = Column(String(128), nullable=False)
    commands_json = Column(Text, nullable=False)
    scope_summary = Column(String(2000), nullable=True)
    risk_level = Column(String(16), nullable=False, default="medium")
    approval_status = Column(String(32), nullable=False, default="pending", index=True)
    approved_by = Column(String(255), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
