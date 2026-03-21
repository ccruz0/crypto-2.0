"""
Tests for the Cursor Execution Bridge.

Validates:
1. is_bridge_enabled respects CURSOR_BRIDGE_ENABLED
2. run_bridge_phase1 rejects empty task_id
3. run_bridge_phase1 rejects when bridge disabled
4. run_bridge_phase1 rejects when handoff file missing
5. cleanup_staging with empty task_id returns False
6. ingest_bridge_results outcome mapping
7. API endpoints return expected structure
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

try:
    from app.main import app
    _HAVE_APP = True
except ImportError:
    app = None
    _HAVE_APP = False


class TestBridgeApprovalGate:
    """CURSOR_BRIDGE_REQUIRE_APPROVAL and scheduler auto-run toggles."""

    def test_require_approval_default_true(self):
        with patch.dict("os.environ", {}, clear=True):
            from app.services.cursor_execution_bridge import is_bridge_require_approval
            assert is_bridge_require_approval() is True

    def test_may_execute_api_blocks_without_patch_approved(self):
        with patch.dict("os.environ", {"CURSOR_BRIDGE_ENABLED": "true"}, clear=True):
            from app.services.cursor_execution_bridge import may_execute_cursor_bridge
            ok, err = may_execute_cursor_bridge("fake-task-id-no-approval", context="api")
            assert ok is False
            assert "patch_approved" in err.lower() or "REQUIRE_APPROVAL" in err

    def test_may_execute_telegram_allows_without_log(self):
        with patch.dict("os.environ", {"CURSOR_BRIDGE_ENABLED": "true"}, clear=True):
            from app.services.cursor_execution_bridge import may_execute_cursor_bridge
            ok, _ = may_execute_cursor_bridge("any-id", context="telegram")
            assert ok is True

    def test_scheduler_auto_unset_is_false_even_if_bridge_enabled(self):
        with patch.dict("os.environ", {"CURSOR_BRIDGE_ENABLED": "true"}, clear=True):
            from app.services.cursor_execution_bridge import scheduler_should_auto_run_cursor_bridge
            assert scheduler_should_auto_run_cursor_bridge() is False
        with patch.dict("os.environ", {}, clear=True):
            from app.services.cursor_execution_bridge import scheduler_should_auto_run_cursor_bridge
            assert scheduler_should_auto_run_cursor_bridge() is False

    def test_scheduler_auto_explicit_true(self):
        with patch.dict(
            "os.environ",
            {"CURSOR_BRIDGE_ENABLED": "true", "CURSOR_BRIDGE_AUTO_IN_ADVANCE": "true"},
            clear=True,
        ):
            from app.services.cursor_execution_bridge import scheduler_should_auto_run_cursor_bridge
            assert scheduler_should_auto_run_cursor_bridge() is True

    def test_scheduler_auto_explicit_false(self):
        with patch.dict(
            "os.environ",
            {"CURSOR_BRIDGE_ENABLED": "true", "CURSOR_BRIDGE_AUTO_IN_ADVANCE": "false"},
            clear=True,
        ):
            from app.services.cursor_execution_bridge import scheduler_should_auto_run_cursor_bridge
            assert scheduler_should_auto_run_cursor_bridge() is False


class TestCursorBridgeEnabled:
    """Verify is_bridge_enabled respects env."""

    def test_disabled_by_default(self):
        with patch.dict("os.environ", {}, clear=True):
            from app.services.cursor_execution_bridge import is_bridge_enabled
            assert is_bridge_enabled() is False

    def test_enabled_when_true(self):
        with patch.dict("os.environ", {"CURSOR_BRIDGE_ENABLED": "true"}):
            from app.services.cursor_execution_bridge import is_bridge_enabled
            assert is_bridge_enabled() is True

    def test_enabled_when_1(self):
        with patch.dict("os.environ", {"CURSOR_BRIDGE_ENABLED": "1"}):
            from app.services.cursor_execution_bridge import is_bridge_enabled
            assert is_bridge_enabled() is True


class TestRunBridgePhase1:
    """Verify run_bridge_phase1 error handling."""

    def test_empty_task_id(self):
        with patch.dict("os.environ", {"CURSOR_BRIDGE_ENABLED": "true"}, clear=False):
            from app.services.cursor_execution_bridge import run_bridge_phase1
            r = run_bridge_phase1("")
            assert r.get("ok") is False
            assert "task_id" in r.get("error", "").lower() or "empty" in r.get("error", "").lower()

    def test_bridge_disabled(self):
        with patch.dict("os.environ", {"CURSOR_BRIDGE_ENABLED": "false"}):
            from app.services.cursor_execution_bridge import run_bridge_phase1
            r = run_bridge_phase1("some-task-id")
            assert r.get("ok") is False
            assert "CURSOR_BRIDGE" in r.get("error", "")

    def test_handoff_not_found(self):
        env = {
            "CURSOR_BRIDGE_ENABLED": "true",
            "CURSOR_BRIDGE_REQUIRE_APPROVAL": "false",
        }
        with patch.dict("os.environ", env, clear=False):
            from app.services.cursor_execution_bridge import run_bridge_phase1
            r = run_bridge_phase1("nonexistent-task-id-xyz")
            assert r.get("ok") is False
            assert "handoff" in r.get("error", "").lower() or "not found" in r.get("error", "").lower()


class TestCleanupStaging:
    """Verify cleanup_staging."""

    def test_empty_task_id_returns_false(self):
        from app.services.cursor_execution_bridge import cleanup_staging
        assert cleanup_staging("") is False


class TestIngestBridgeResults:
    """Verify ingest_bridge_results outcome mapping (no Notion calls)."""

    def test_invoke_fail_maps_to_not_run(self):
        with patch("app.services.cursor_execution_bridge._log_event"):
            with patch("app.services.task_test_gate.record_test_result") as mock_record:
                from app.services.cursor_execution_bridge import ingest_bridge_results
                r = ingest_bridge_results(
                    "task-1",
                    invoke_ok=False,
                    tests_ok=False,
                    diff_path=None,
                    tests=None,
                )
                assert r.get("outcome") == "not-run"
                mock_record.assert_called_once()
                call_kw = mock_record.call_args[1]
                assert call_kw.get("summary", "").lower().find("invoke") >= 0 or call_kw.get("summary", "").lower().find("failed") >= 0


@pytest.mark.skipif(not _HAVE_APP, reason="app.main not importable (install backend deps: pip install -r backend/requirements.txt)")
class TestCursorBridgeAPI:
    """Verify cursor bridge API endpoints."""

    def test_run_bridge_requires_task_id(self):
        """POST without task_id returns error."""
        env = {"CURSOR_BRIDGE_ENABLED": "true", "CURSOR_BRIDGE_REQUIRE_APPROVAL": "false"}
        with patch.dict("os.environ", env, clear=False):
            client = TestClient(app)
            r = client.post("/api/agent/cursor-bridge/run", json={})
            assert r.status_code == 200
            data = r.json()
            assert data.get("ok") is False
            assert "task_id" in data.get("error", "").lower()

    def test_run_bridge_returns_error_when_disabled(self):
        """POST when CURSOR_BRIDGE_ENABLED is false returns error."""
        with patch.dict("os.environ", {"CURSOR_BRIDGE_ENABLED": "false"}):
            client = TestClient(app)
            r = client.post("/api/agent/cursor-bridge/run", json={"task_id": "task-123"})
            assert r.status_code == 200
            data = r.json()
            assert data.get("ok") is False
            assert "CURSOR_BRIDGE" in data.get("error", "")

    def test_cursor_bridge_events_returns_structure(self):
        """GET cursor-bridge-events returns ok and cursor_bridge_events array."""
        client = TestClient(app)
        r = client.get("/api/agent/ops/cursor-bridge-events?limit=5")
        assert r.status_code == 200
        data = r.json()
        assert "ok" in data
        assert "cursor_bridge_events" in data
        assert isinstance(data["cursor_bridge_events"], list)
        assert "count" in data

    def test_cursor_bridge_diagnostics_returns_structure(self):
        """GET cursor-bridge/diagnostics returns ok and readiness fields."""
        client = TestClient(app)
        r = client.get("/api/agent/cursor-bridge/diagnostics")
        assert r.status_code == 200
        data = r.json()
        assert "ok" in data
        assert "enabled" in data
        assert "cursor_cli_path" in data
        assert "cursor_cli_found" in data
        assert "staging_root" in data
        assert "staging_root_writable" in data
        assert "ready" in data
