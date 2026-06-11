"""Tests for Jarvis Control Center persistence foundation."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool

from app.database import (
    Base,
    ensure_jarvis_control_approval_comment_column,
    ensure_jarvis_control_center_tables,
)
from app.models.jarvis_control_models import (
    JarvisControlApproval,
    JarvisControlAuditEvent,
    JarvisControlSession,
    JarvisControlTask,
)
from app.jarvis.control import persistence as jcp


@pytest.fixture()
def control_db(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            JarvisControlSession.__table__,
            JarvisControlTask.__table__,
            JarvisControlApproval.__table__,
            JarvisControlAuditEvent.__table__,
        ],
    )
    monkeypatch.setattr(jcp, "engine", engine)

    def _ensure(_engine):
        return ensure_jarvis_control_center_tables(_engine)

    monkeypatch.setattr(jcp, "ensure_jarvis_control_center_tables", _ensure)
    yield engine
    engine.dispose()


def test_models_import():
    from app.models.jarvis_control_models import JarvisControlSession, JarvisControlTask

    assert JarvisControlSession.__tablename__ == "jarvis_control_sessions"
    assert JarvisControlTask.__tablename__ == "jarvis_control_tasks"


def test_env_helpers_default_safe():
    from app.core.environment import (
        is_jarvis_builder_allowed,
        is_jarvis_control_enabled,
    )

    with patch.dict("os.environ", {}, clear=True):
        assert is_jarvis_control_enabled() is False
        assert is_jarvis_builder_allowed() is False

    with patch.dict("os.environ", {"JARVIS_BUILDER_ALLOWED": "1", "ATP_TRADING_ONLY": "1"}, clear=True):
        assert is_jarvis_builder_allowed() is False


def test_control_persistence_round_trip(control_db):
    sid = jcp.create_control_session(
        created_by="test:unit",
        default_mode="advisor",
        environment="local",
        domain="software",
    )
    assert sid.startswith("jcs-")

    tid = jcp.create_control_task(
        session_id=sid,
        prompt="summarize repo health",
        mode="advisor",
        dry_run=True,
        status="queued",
    )
    assert tid.startswith("jcc-")

    detail = jcp.get_control_task(tid)
    assert detail is not None
    assert detail["session_id"] == sid
    assert detail["prompt"] == "summarize repo health"
    assert detail["status"] == "queued"
    assert detail["dry_run"] is True

    assert jcp.update_control_task_status(tid, "completed", final_answer="done")
    updated = jcp.get_control_task(tid)
    assert updated is not None
    assert updated["status"] == "completed"
    assert updated["final_answer"] == "done"
    assert updated["completed_at"] is not None

    eid = jcp.append_control_audit_event(
        "task_created",
        task_id=tid,
        session_id=sid,
        actor_type="human",
        actor_id="tester",
        payload={"source": "unit_test"},
    )
    assert eid.startswith("jce-")

    events = jcp.list_control_audit_events(task_id=tid)
    assert len(events) == 1
    assert events[0]["type"] == "task_created"
    assert events[0]["payload"]["source"] == "unit_test"

    aid = jcp.create_control_approval(
        task_id=tid,
        scope_summary="Review builder artifact",
        risk_level="medium",
        digest="sha256:abc",
        allowed_envs="lab",
    )
    assert aid.startswith("jca-")

    tasks = jcp.list_control_tasks(session_id=sid, mode="advisor")
    assert len(tasks) == 1
    assert tasks[0]["task_id"] == tid


def test_ensure_jarvis_control_center_tables_idempotent(control_db):
    assert ensure_jarvis_control_center_tables(control_db) is True
    assert ensure_jarvis_control_center_tables(control_db) is True


def _create_legacy_approvals_table(engine) -> None:
    """Simulate Step 1 schema without the Step 7 comment column."""
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS jarvis_control_approvals"))
        conn.execute(
            text(
                """
                CREATE TABLE jarvis_control_approvals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    approval_id VARCHAR(128) NOT NULL UNIQUE,
                    task_id VARCHAR(128) NOT NULL,
                    action_id VARCHAR(128),
                    approval_status VARCHAR(32) NOT NULL DEFAULT 'pending',
                    execution_status VARCHAR(32) NOT NULL DEFAULT 'not_executed',
                    risk_level VARCHAR(16) NOT NULL DEFAULT 'medium',
                    scope_summary VARCHAR(2000),
                    digest VARCHAR(128),
                    allowed_envs VARCHAR(64),
                    requested_by VARCHAR(255) NOT NULL DEFAULT 'jarvis',
                    approved_by VARCHAR(255),
                    approved_at TIMESTAMP,
                    expires_at TIMESTAMP,
                    governance_manifest_id VARCHAR(128),
                    agent_approval_state_id INTEGER,
                    telegram_message_id VARCHAR(64),
                    execution_result_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )


def test_approval_comment_column_boot_hook_idempotent(monkeypatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            JarvisControlSession.__table__,
            JarvisControlTask.__table__,
            JarvisControlAuditEvent.__table__,
        ],
    )
    _create_legacy_approvals_table(engine)
    monkeypatch.setattr(jcp, "engine", engine)

    def _ensure(_engine):
        return ensure_jarvis_control_center_tables(_engine)

    monkeypatch.setattr(jcp, "ensure_jarvis_control_center_tables", _ensure)

    before = {col["name"] for col in inspect(engine).get_columns("jarvis_control_approvals")}
    assert "comment" not in before

    assert ensure_jarvis_control_approval_comment_column(engine) is True
    after = {col["name"] for col in inspect(engine).get_columns("jarvis_control_approvals")}
    assert "comment" in after

    assert ensure_jarvis_control_approval_comment_column(engine) is True
    assert ensure_jarvis_control_center_tables(engine) is True
    engine.dispose()


def test_approval_with_comment_after_comment_column_migration(monkeypatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            JarvisControlSession.__table__,
            JarvisControlTask.__table__,
            JarvisControlAuditEvent.__table__,
        ],
    )
    _create_legacy_approvals_table(engine)
    monkeypatch.setattr(jcp, "engine", engine)

    def _ensure(_engine):
        return ensure_jarvis_control_center_tables(_engine)

    monkeypatch.setattr(jcp, "ensure_jarvis_control_center_tables", _ensure)
    assert ensure_jarvis_control_approval_comment_column(engine) is True

    sid = jcp.create_control_session(created_by="test:migration", environment="local")
    task_id = jcp.create_control_task(
        session_id=sid,
        prompt="migration comment test",
        mode="builder",
        status="awaiting_approval",
    )
    approval = jcp.approve_control_task(
        task_id,
        actor_id="reviewer-migration",
        comment="approved after column migration",
    )
    assert approval["comment"] == "approved after column migration"
    assert approval["approval_status"] == "approved"

    stored = jcp.get_control_approvals(task_id)
    assert len(stored) == 1
    assert stored[0]["comment"] == "approved after column migration"
    engine.dispose()


def test_jarvis_routes_still_import():
    from app.api.routes_jarvis import router

    assert router is not None


def test_factory_still_imports():
    from app.factory import create_app

    app = create_app()
    assert app is not None
