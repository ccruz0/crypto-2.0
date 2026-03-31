"""Regression tests for anomaly queue contamination and scheduler fairness."""

from __future__ import annotations

from unittest.mock import MagicMock


def _task(task_id: str, title: str, *, priority: str = "High", priority_score: int = 0, created_time: str = "") -> dict:
    return {
        "id": task_id,
        "task": title,
        "project": "Operations",
        "type": "Monitoring" if title.startswith("[Anomaly]") else "Bug",
        "status": "planned",
        "priority": priority,
        "priority_score": priority_score,
        "created_time": created_time,
    }


def test_prepare_next_notion_task_prefers_non_anomaly_when_queue_flooded(monkeypatch):
    from app.services.agent_task_executor import prepare_next_notion_task

    anomaly_tasks = [
        _task(f"a{i}", "[Anomaly] Scheduler Inactivity", created_time=f"2026-03-01T00:00:{i:02d}Z")
        for i in range(10)
    ]
    normal = _task(
        "n1",
        "Audit ATP codebase against documentation and business rules",
        priority="High",
        priority_score=0,
        created_time="2026-03-01T00:01:00Z",
    )
    queue = anomaly_tasks + [normal]

    monkeypatch.setattr("app.services.agent_task_executor.get_high_priority_pending_tasks", lambda **_: queue)
    monkeypatch.setattr("app.services.agent_task_executor.update_notion_task_status", lambda **_: True)
    monkeypatch.setattr("app.services.agent_task_executor._append_notion_page_comment", lambda *a, **k: True)
    monkeypatch.setattr("app.services.agent_task_executor._maybe_ensure_notion_governance_task_after_claim", lambda **_: None)

    out = prepare_next_notion_task()
    assert out is not None
    assert (out.get("task") or {}).get("id") == "n1"


def test_anomaly_detector_reuses_existing_active_scheduler_inactivity(monkeypatch):
    from app.services.agent_anomaly_detector import _create_anomaly_task

    existing = {
        "id": "existing-1",
        "task": "[Anomaly] Scheduler Inactivity",
        "status": "planned",
        "type": "Monitoring",
    }
    monkeypatch.setattr("app.services.notion_task_reader.get_tasks_by_status", lambda *a, **k: [existing])
    create_mock = MagicMock(return_value={"id": "new-id"})
    monkeypatch.setattr("app.services.notion_tasks.create_notion_task", create_mock)

    result = _create_anomaly_task(
        title="[Anomaly] Scheduler Inactivity",
        anomaly_type="monitoring",
        details="Anomaly type: scheduler_inactivity",
        reuse_existing=True,
    )

    assert (result or {}).get("id") == "existing-1"
    assert (result or {}).get("reused") is True
    create_mock.assert_not_called()


def test_scheduler_inactivity_recovery_marks_incident_done(monkeypatch):
    from app.services.agent_anomaly_detector import _close_scheduler_inactivity_incident_task

    existing = {
        "id": "existing-2",
        "task": "[Anomaly] Scheduler Inactivity",
        "status": "planned",
        "type": "Monitoring",
    }
    monkeypatch.setattr(
        "app.services.agent_anomaly_detector._find_active_anomaly_task_by_title",
        lambda *_a, **_k: existing,
    )

    calls: list[dict] = []

    def _mock_update(page_id: str, status: str, *, append_comment: str | None = None, **_kwargs):
        calls.append({"page_id": page_id, "status": status, "append_comment": append_comment or ""})
        return True

    monkeypatch.setattr("app.services.notion_tasks.update_notion_task_status", _mock_update)

    task_id = _close_scheduler_inactivity_incident_task()

    assert task_id == "existing-2"
    assert calls
    assert calls[0]["page_id"] == "existing-2"
    assert calls[0]["status"] == "done"
    assert "Incident resolved automatically" in calls[0]["append_comment"]

