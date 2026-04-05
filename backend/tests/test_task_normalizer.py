"""Tests for task_normalizer and queue partition helpers."""

import json
from unittest.mock import patch

from app.services.task_normalizer import (
    normalize_task,
    partition_tasks_queue_isolation,
    save_normalized_task_artifact,
)


def test_normalize_docs_investigation_scheduler_doc():
    raw = {
        "task": "check if scheduler doc is correct",
        "details": "verify docs/agents/agent-scheduler.md",
        "type": "bug",
    }
    out = normalize_task(raw)
    assert out["task_type"] == "docs_investigation"
    assert out["risk_level"] in ("low", "medium", "high")


def test_normalize_anomaly():
    raw = {"task": "CPU anomaly on worker", "details": "spike", "type": "monitoring"}
    out = normalize_task(raw)
    assert out["task_type"] == "anomaly"


def test_normalize_code_change():
    raw = {"task": "Null pointer", "details": "fix the error in sync", "type": "bug"}
    out = normalize_task(raw)
    assert out["task_type"] == "code_change"


def test_normalize_risk_low_when_no_code_change():
    raw = {
        "task": "Review readme",
        "details": "Do not modify code; docs only",
        "type": "improvement",
    }
    out = normalize_task(raw)
    assert out["risk_level"] == "low"


def test_partition_human_before_anomaly():
    h = {"task": "human task", "details": "plain", "id": "a"}
    a = {"task": "x", "details": "anomaly detected", "id": "b"}
    ordered = partition_tasks_queue_isolation([a, h])
    assert ordered[0]["id"] == "a"
    assert ordered[1]["id"] == "b"


def test_save_normalized_artifact_tmp(tmp_path, monkeypatch):
    from app.services import artifact_paths

    monkeypatch.setenv("ATP_PATH_GUARD_EXTRA_ALLOWED_PREFIXES", str(tmp_path.resolve()))
    monkeypatch.setattr(artifact_paths, "get_normalized_tasks_dir", lambda: tmp_path)
    p = save_normalized_task_artifact("tid123", {"task_type": "docs_investigation", "title": "t"})
    assert p is not None
    fp = tmp_path / "task-tid123.normalized.json"
    assert fp.exists()


def test_openclaw_note_out_dir_docs_uses_task_tree(tmp_path, monkeypatch):
    from app.services import artifact_paths
    from app.services.agent_callbacks import _openclaw_note_out_dir

    monkeypatch.setattr(artifact_paths, "get_base_artifact_dir", lambda: tmp_path)
    prepared = {
        "task": {"id": "abc123", "task": "check doc"},
        "task_normalization": {"task_type": "docs_investigation"},
    }
    d = _openclaw_note_out_dir(prepared, "docs/agents/generated-notes", "abc123")
    assert d == tmp_path / "tasks" / "abc123"


def test_select_callbacks_docs_investigation_from_normalizer():
    """Runtime: task_normalization must win over Notion type=bug for doc-check titles."""
    from app.services.agent_callbacks import select_default_callbacks_for_task

    prepared = {
        "task": {
            "id": "notion-page-1",
            "task": "check if scheduler doc is correct",
            "details": "verify docs/agents/agent-scheduler.md",
            "type": "bug",
            "project": "Backend",
        },
        "repo_area": {"area_name": "Unknown"},
        "task_normalization": {
            "task_type": "docs_investigation",
            "title": "check if scheduler doc is correct",
            "risk_level": "low",
        },
    }
    out = select_default_callbacks_for_task(prepared)
    reason = (out.get("selection_reason") or "").lower()
    assert "docs investigation" in reason or "documentation" in reason
    assert "execution and state" not in reason


def test_callback_selection_needs_task_normalization_when_notion_type_is_bug():
    """advance_ready_for_patch_task minimal dict must include normalization or bug type wins."""
    from app.services.agent_callbacks import select_default_callbacks_for_task

    task = {
        "id": "page-doc-1",
        "task": "check if scheduler doc is correct",
        "details": "verify scheduler doc",
        "type": "bug",
    }
    minimal = {"task": task, "repo_area": {"area_name": "Unknown"}}
    without = select_default_callbacks_for_task(minimal)
    from app.services.task_normalizer import normalize_task

    minimal["task_normalization"] = normalize_task(task)
    with_norm = select_default_callbacks_for_task(minimal)
    assert "bug investigation" in (without.get("selection_reason") or "").lower()
    assert "docs investigation" in (with_norm.get("selection_reason") or "").lower()

    # Exact shape used in advance_ready_for_patch_task after step 3 + normalization
    continuation = {
        "task": task,
        "repo_area": {"area_name": "Unknown"},
        "claim": {"status_updated": True},
        "_use_extended_lifecycle": True,
        "task_normalization": normalize_task(task),
    }
    adv = select_default_callbacks_for_task(continuation)
    assert "docs investigation" in (adv.get("selection_reason") or "").lower()


def test_format_what_will_happen_docs_investigation_per_task_tree():
    from app.services.agent_telegram_approval import _format_what_will_happen

    msg = _format_what_will_happen(
        "docs investigation (task_normalizer; OpenClaw documentation path only)",
        {},
    )
    assert "docs/agents/tasks" in msg
    assert "per-task" in msg.lower()


def test_generate_cursor_handoff_runs_for_docs_without_openclaw_sections():
    """Readonly/template apply leaves no _openclaw_sections; docs still get a handoff."""
    prepared = {
        "task": {"id": "page-xyz", "task": "check if scheduler doc is correct"},
        "task_normalization": {"task_type": "docs_investigation"},
    }
    with patch("app.services.cursor_handoff.generate_cursor_handoff") as gch:
        gch.return_value = {"success": True, "path": "/tmp/cursor-handoff-page-xyz.md"}
        from app.services.agent_task_executor import _generate_cursor_handoff

        _generate_cursor_handoff(prepared, "page-xyz")
    assert gch.called


def test_apply_documentation_task_docs_investigation_writes_md_and_sidecar(tmp_path, monkeypatch):
    """OpenClaw-error fallback: per-task tree gets notion-task .md + .sections.json for ready-for-patch gate."""
    from app.services import artifact_paths
    from app.services.agent_callbacks import apply_documentation_task
    from app.services.agent_recovery import artifact_and_sidecar_exist_for_task

    agents_base = tmp_path / "agents"
    monkeypatch.setenv("ATP_PATH_GUARD_EXTRA_ALLOWED_PREFIXES", str(tmp_path.resolve()))
    monkeypatch.setattr(artifact_paths, "get_base_artifact_dir", lambda: agents_base)

    tid = "332b-test-docs-fallback-01"
    prepared = {
        "task": {
            "id": tid,
            "task": "check if scheduler doc is correct",
            "priority": "high",
            "project": "Infrastructure",
            "type": "bug",
            "source": "openclaw",
            "github_link": "",
        },
        "repo_area": {
            "area_name": "Docs",
            "matched_rules": ["docs"],
            "likely_files": ["docs/agents/agent-scheduler.md"],
            "relevant_docs": ["docs/architecture/system-map.md"],
            "relevant_runbooks": [],
        },
        "task_normalization": {"task_type": "docs_investigation"},
    }
    out = apply_documentation_task(prepared)
    assert out.get("success") is True

    tdir = agents_base / "tasks" / tid
    md_path = tdir / f"notion-task-{tid}.md"
    sidecar_path = tdir / f"notion-task-{tid}.sections.json"
    assert md_path.is_file()
    assert sidecar_path.is_file()
    data = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert data.get("source") == "documentation_fallback"
    assert isinstance(data.get("sections"), dict)
    assert data["sections"]

    ok, reason = artifact_and_sidecar_exist_for_task(tid, min_size=200)
    assert ok, reason
