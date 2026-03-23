"""Early governance_tasks stub after successful Notion task claim (prepare path)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.governance_models import GovernanceEvent, GovernanceTask


def test_prepare_next_notion_task_creates_governance_stub_when_enforced(monkeypatch):
    monkeypatch.setenv("ATP_GOVERNANCE_AGENT_ENFORCE", "true")
    monkeypatch.setenv("ENVIRONMENT", "aws")
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(
        bind=engine,
        tables=[GovernanceTask.__table__, GovernanceEvent.__table__],
    )
    Session = sessionmaker(bind=engine, future=True)
    monkeypatch.setattr("app.database.SessionLocal", lambda: Session())

    fake_task = {
        "id": "prep-gov-nid",
        "task": "Do work",
        "type": "patch",
        "priority": "high",
        "status": "planned",
    }

    monkeypatch.setattr(
        "app.services.agent_task_executor.get_high_priority_pending_tasks",
        lambda **kw: [fake_task],
    )
    monkeypatch.setattr(
        "app.services.agent_task_executor.update_notion_task_status",
        lambda page_id, status: True,
    )
    monkeypatch.setattr(
        "app.services.agent_task_executor._append_notion_page_comment",
        lambda *a, **k: True,
    )

    from app.services.agent_task_executor import prepare_next_notion_task

    out = prepare_next_notion_task()
    assert out is not None
    assert (out.get("claim") or {}).get("status_updated") is True
    s = Session()
    try:
        row = s.query(GovernanceTask).filter(GovernanceTask.task_id == "gov-notion-prep-gov-nid").first()
        assert row is not None
    finally:
        s.close()


def test_prepare_next_notion_task_skips_governance_stub_when_not_enforced(monkeypatch):
    monkeypatch.delenv("ATP_GOVERNANCE_AGENT_ENFORCE", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "aws")
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(
        bind=engine,
        tables=[GovernanceTask.__table__, GovernanceEvent.__table__],
    )
    Session = sessionmaker(bind=engine, future=True)
    monkeypatch.setattr("app.database.SessionLocal", lambda: Session())
    fake_task = {
        "id": "no-enforce-nid",
        "task": "T",
        "type": "patch",
        "priority": "high",
        "status": "planned",
    }
    monkeypatch.setattr(
        "app.services.agent_task_executor.get_high_priority_pending_tasks",
        lambda **kw: [fake_task],
    )
    monkeypatch.setattr(
        "app.services.agent_task_executor.update_notion_task_status",
        lambda page_id, status: True,
    )
    monkeypatch.setattr(
        "app.services.agent_task_executor._append_notion_page_comment",
        lambda *a, **k: True,
    )
    from app.services.agent_task_executor import prepare_next_notion_task

    prepare_next_notion_task()
    s = Session()
    try:
        assert s.query(GovernanceTask).count() == 0
    finally:
        s.close()
