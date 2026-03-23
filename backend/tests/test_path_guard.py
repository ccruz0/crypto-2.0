"""Tests for LAB path guard (docs/** + configured fallbacks)."""

from __future__ import annotations

import json
import logging

import pytest

from app.services.path_guard import (
    EVENT_BLOCKED,
    EVENT_PATCH_BLOCKED,
    PathGuardViolation,
    assert_lab_patch_target,
    assert_writable_lab_path,
    coerce_resolved_path,
    safe_write_text,
)


@pytest.fixture
def fake_workspace(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "analysis").mkdir(parents=True)
    (root / "backend").mkdir(parents=True)
    return root


def test_coerce_relative_resolves_under_workspace(monkeypatch, fake_workspace):
    import app.services.path_guard as pg

    monkeypatch.setattr(pg, "workspace_root", lambda: fake_workspace)
    p = coerce_resolved_path("docs/x.txt")
    assert p == (fake_workspace / "docs" / "x.txt").resolve()


def test_write_allowed_under_docs(monkeypatch, fake_workspace, caplog):
    import app.services.path_guard as pg

    monkeypatch.setattr(pg, "workspace_root", lambda: fake_workspace)
    caplog.set_level(logging.DEBUG)
    target = fake_workspace / "docs" / "analysis" / "out.md"
    safe_write_text(target, "hello", context="test:allowed")
    assert target.read_text(encoding="utf-8") == "hello"


def test_write_blocked_under_workspace_outside_docs(monkeypatch, fake_workspace, caplog):
    import app.services.path_guard as pg

    monkeypatch.setattr(pg, "workspace_root", lambda: fake_workspace)
    caplog.set_level(logging.ERROR)
    target = fake_workspace / "backend" / "evil.py"
    with pytest.raises(PathGuardViolation) as ei:
        safe_write_text(target, "x", context="test:blocked")
    assert "blocked" in str(ei.value).lower()
    assert any(EVENT_BLOCKED in r.getMessage() for r in caplog.records)
    last = [r for r in caplog.records if EVENT_BLOCKED in r.getMessage()][-1]
    msg = last.getMessage()
    payload = json.loads(msg[msg.index("{") :])
    assert payload.get("event") == EVENT_BLOCKED
    assert "backend" in payload.get("normalized_path", "")


def test_path_traversal_from_docs_to_backend_blocked(monkeypatch, fake_workspace):
    import app.services.path_guard as pg

    monkeypatch.setattr(pg, "workspace_root", lambda: fake_workspace)
    sneaky = fake_workspace / "docs" / ".." / "backend" / "x.py"
    with pytest.raises(PathGuardViolation):
        safe_write_text(sneaky, "no", context="test:traversal")


def test_assert_lab_patch_target_logs_patch_blocked(monkeypatch, fake_workspace, caplog):
    import app.services.path_guard as pg

    monkeypatch.setattr(pg, "workspace_root", lambda: fake_workspace)
    caplog.set_level(logging.ERROR)
    with pytest.raises(PathGuardViolation):
        assert_lab_patch_target(fake_workspace / "backend" / "p.py", context="test:patch")
    assert any(EVENT_PATCH_BLOCKED in r.getMessage() for r in caplog.records)


def test_guard_disabled_allows_workspace_non_docs(monkeypatch, fake_workspace):
    import app.services.path_guard as pg

    monkeypatch.setattr(pg, "workspace_root", lambda: fake_workspace)
    monkeypatch.setenv("ATP_PATH_GUARD_DISABLE", "1")
    try:
        target = fake_workspace / "backend" / "when_disabled.txt"
        # Reload policy: path_guard_enabled reads env at call time
        assert_writable_lab_path(target, context="test:disable")
    finally:
        monkeypatch.delenv("ATP_PATH_GUARD_DISABLE", raising=False)
