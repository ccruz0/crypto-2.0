"""Early governance_tasks stub on Telegram approval path (timeline correlation)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.governance_models import GovernanceEvent, GovernanceManifest, GovernanceTask
from app.services.agent_execution_policy import (
    ATTR_PROD_MUTATION,
    GOVERNANCE_ACTION_CLASS_KEY,
    GOV_CLASS_PATCH_PREP,
)
from app.services.agent_telegram_approval import send_task_approval_request


def test_send_preflight_classification_conflict_still_creates_governance_task(monkeypatch):
    monkeypatch.setenv("ATP_GOVERNANCE_AGENT_ENFORCE", "true")
    monkeypatch.setenv("ENVIRONMENT", "aws")
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(
        bind=engine,
        tables=[
            GovernanceTask.__table__,
            GovernanceEvent.__table__,
            GovernanceManifest.__table__,
        ],
    )
    Session = sessionmaker(bind=engine, future=True)
    monkeypatch.setattr("app.database.SessionLocal", lambda: Session())
    monkeypatch.setattr(
        "app.services.agent_telegram_approval._get_default_chat_id",
        lambda: "1",
    )

    def _apply(x):
        return True

    setattr(_apply, ATTR_PROD_MUTATION, True)
    nid = "preflight-conflict-nid"
    bundle = {
        "prepared_task": {"task": {"id": nid, "task": "t"}},
        "callback_selection": {
            GOVERNANCE_ACTION_CLASS_KEY: GOV_CLASS_PATCH_PREP,
            "apply_change_fn": _apply,
            "selection_reason": "x",
        },
        "approval": {"required": True},
    }
    out = send_task_approval_request(bundle)
    assert out.get("summary") == "governance_classification_conflict"
    s = Session()
    try:
        assert s.query(GovernanceManifest).count() == 0
        row = s.query(GovernanceTask).filter(GovernanceTask.task_id == f"gov-notion-{nid}").first()
        assert row is not None
    finally:
        s.close()
