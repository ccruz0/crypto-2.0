"""Extended lifecycle: strict auto-advance uses bug proof vs documentation section gate."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _fake_apply_docs(pt):
    pt["_openclaw_sections"] = {
        "Task Summary": "Summary line one two three four five",
        "Root Cause": "Root cause text here with enough chars",
        "Recommended Fix": "Fix steps one two three four five",
        "Affected Files": "backend/app/services/example.py and more",
    }
    return {"success": True, "summary": "applied"}


@pytest.fixture
def _exec_mocks(monkeypatch):
    monkeypatch.setattr(
        "app.services.agent_task_executor._maybe_run_execute_prepared_through_governance",
        lambda **kw: None,
    )
    monkeypatch.setattr("app.services.agent_task_executor._enrich_metadata_from_openclaw", lambda *a, **k: None)
    monkeypatch.setattr("app.services.agent_task_executor._generate_cursor_handoff", lambda *a, **k: None)
    monkeypatch.setattr("app.services.agent_task_executor._append_notion_page_comment", lambda *a, **k: None)
    monkeypatch.setattr(
        "app.services.agent_recovery.artifact_and_sidecar_exist_for_task",
        lambda tid, min_size=200: (True, "ok"),
    )
    monkeypatch.setattr(
        "app.services.agent_task_executor.update_notion_task_status",
        MagicMock(return_value=True),
    )


def test_docs_content_extended_strict_skips_validate_strict_mode_proof(monkeypatch, _exec_mocks):
    strict_calls: list[str] = []

    def _strict(content: str):
        strict_calls.append(content)
        return True, "ok"

    monkeypatch.setattr("app.services.openclaw_client.validate_strict_mode_proof", _strict)

    from app.services.agent_task_executor import execute_prepared_notion_task

    out = execute_prepared_notion_task(
        {
            "task": {
                "id": "tid-doc-strict-1",
                "task": "Document the scheduler flow",
                "type": "Content",
                "execution_mode": "strict",
            },
            "claim": {"status_updated": True},
            "_use_extended_lifecycle": True,
            "task_normalization": {"task_type": "docs_investigation"},
        },
        apply_change_fn=_fake_apply_docs,
    )
    assert len(strict_calls) == 0
    assert out.get("final_status") == "ready-for-patch"
    assert out.get("success") is True


def test_bug_investigation_extended_strict_still_calls_validate_strict_mode_proof(monkeypatch, _exec_mocks):
    strict_calls: list[str] = []

    def _strict(content: str):
        strict_calls.append(content)
        return True, "ok"

    monkeypatch.setattr("app.services.openclaw_client.validate_strict_mode_proof", _strict)
    monkeypatch.setattr(
        "app.services.agent_recovery.get_artifact_content_for_task",
        lambda tid: "def repro():\n    raise RuntimeError('x')\n" + "x" * 400,
    )
    monkeypatch.setattr(
        "app.services.notion_tasks.create_patch_task_from_investigation",
        lambda **kw: {"id": "patch-child-1"},
    )

    def _fake_apply_bug(pt):
        pt["_openclaw_sections"] = {"Task Summary": "y" * 30}
        return {"success": True, "summary": "applied"}

    from app.services.agent_task_executor import execute_prepared_notion_task

    out = execute_prepared_notion_task(
        {
            "task": {
                "id": "tid-bug-strict-1",
                "task": "Fix null deref in sync",
                "type": "Investigation",
                "execution_mode": "strict",
            },
            "claim": {"status_updated": True},
            "_use_extended_lifecycle": True,
        },
        apply_change_fn=_fake_apply_bug,
    )
    assert len(strict_calls) == 1
    assert out.get("final_status") == "ready-for-patch"
    assert out.get("success") is True
