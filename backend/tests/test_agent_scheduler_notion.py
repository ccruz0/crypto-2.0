"""
Tests for the agent scheduler and Notion task reader fixes.

Validates:
1. Notion query uses only exact valid Status option names (Planned, Backlog, etc.)
2. Lowercase invalid variants (planned, backlog) are NOT sent to Notion
3. Local normalization still works after fetch
4. Diagnostic logging produces expected messages
5. test_notion_task_scan() returns structured results
6. Scheduler background loop function exists and is importable
7. Scheduler is wired into FastAPI startup
"""

from __future__ import annotations

import json
import logging
from typing import Any
from unittest.mock import MagicMock, patch

import inspect

import pytest


# ---------------------------------------------------------------------------
# Helpers: fake Notion API responses
# ---------------------------------------------------------------------------

def _notion_page(page_id: str, title: str, status: str, priority: str = "medium", project: str = "TestProject", task_type: str = "improvement") -> dict[str, Any]:
    """Build a minimal Notion page object that _parse_page can handle."""
    return {
        "id": page_id,
        "properties": {
            "Task": {"title": [{"plain_text": title}]},
            "Status": {"rich_text": [{"plain_text": status}]},
            "Priority": {"rich_text": [{"plain_text": priority}]},
            "Project": {"rich_text": [{"plain_text": project}]},
            "Type": {"rich_text": [{"plain_text": task_type}]},
            "Source": {"rich_text": [{"plain_text": "openclaw"}]},
            "Details": {"rich_text": [{"plain_text": "test details"}]},
        },
    }


def _notion_query_response(pages: list[dict[str, Any]]) -> dict[str, Any]:
    return {"results": pages, "has_more": False, "next_cursor": None}


class FakeResponse:
    def __init__(self, status_code: int, data: dict[str, Any] | None = None, body: str = ""):
        self.status_code = status_code
        self._data = data
        self.text = body or (json.dumps(data) if data else "")

    def json(self) -> dict[str, Any]:
        return self._data or {}


# ---------------------------------------------------------------------------
# Tests: Notion task reader
# ---------------------------------------------------------------------------


class TestNotionTaskReader:
    """Verify Notion query uses exact valid Status options; normalization after fetch."""

    @patch.dict("os.environ", {"NOTION_API_KEY": "secret_test", "NOTION_TASK_DB": "db_test_id_1234"})
    def test_only_sends_valid_notion_status_options(self):
        """Notion query must use only exact valid option names; lowercase causes 400."""
        from app.services.notion_task_reader import (
            get_pending_notion_tasks,
            NOTION_PICKABLE_STATUS_OPTIONS,
        )

        # Page with Status "Planned" (valid Notion option)
        page = _notion_page("id-1", "Fix docs", "Planned")
        ok_response = FakeResponse(200, _notion_query_response([page]))

        filter_values_sent = []

        def capture_post(url, json=None, headers=None):
            nonlocal filter_values_sent
            body = json or {}
            flt = body.get("filter") or {}
            if flt.get("property") == "Status":
                eq_val = (flt.get("status") or flt.get("select") or {}).get("equals", "")
                if eq_val:
                    filter_values_sent.append(eq_val)
            return ok_response

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = capture_post

        with patch("app.services.notion_task_reader.httpx.Client", return_value=mock_client):
            get_pending_notion_tasks()

        valid_options = set(NOTION_PICKABLE_STATUS_OPTIONS)
        invalid_lowercase = {"planned", "backlog", "blocked", "ready for investigation"}
        for val in filter_values_sent:
            assert val in valid_options, f"Invalid filter value sent: {val!r} (must be in {valid_options})"
            assert val not in invalid_lowercase, f"Lowercase variant sent: {val!r} (causes 400)"

    @patch.dict("os.environ", {"NOTION_API_KEY": "secret_test", "NOTION_TASK_DB": "db_test_id_1234"})
    def test_finds_tasks_with_planned_and_normalizes(self):
        """Tasks with Status 'Planned' are found; parsed status normalized to internal."""
        from app.services.notion_task_reader import get_pending_notion_tasks

        page = _notion_page("id-1", "Fix docs", "Planned")
        ok_response = FakeResponse(200, _notion_query_response([page]))

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = ok_response

        with patch("app.services.notion_task_reader.httpx.Client", return_value=mock_client):
            tasks = get_pending_notion_tasks()

        assert len(tasks) == 1
        assert tasks[0]["task"] == "Fix docs"
        # Normalization: "Planned" -> "planned" (internal)
        assert tasks[0]["status"] == "planned"

    @patch.dict("os.environ", {"NOTION_API_KEY": "secret_test", "NOTION_TASK_DB": "db_test_id_1234"})
    def test_finds_tasks_with_capitalized_planned(self):
        """Reader queries 'Planned' (exact valid option) and finds tasks."""
        from app.services.notion_task_reader import get_pending_notion_tasks

        page = _notion_page("id-2", "Audit project documentation", "Planned")
        empty_response = FakeResponse(200, _notion_query_response([]))
        capitalized_response = FakeResponse(200, _notion_query_response([page]))

        call_count = 0

        def fake_post(url, json=None, headers=None):
            nonlocal call_count
            call_count += 1
            filter_body = json or {}
            status_filter = filter_body.get("filter", {})

            rt = status_filter.get("rich_text") or {}
            sel = status_filter.get("select") or {}
            st = status_filter.get("status") or {}
            equals_value = rt.get("equals") or sel.get("equals") or st.get("equals") or ""

            if equals_value == "Planned":
                return capitalized_response
            return empty_response

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = fake_post

        with patch("app.services.notion_task_reader.httpx.Client", return_value=mock_client):
            tasks = get_pending_notion_tasks()

        assert len(tasks) == 1
        assert tasks[0]["task"] == "Audit project documentation"
        # Reader queries each pickable status; "Planned" returns 1 result.
        assert call_count >= 1

    @patch.dict("os.environ", {"NOTION_API_KEY": "secret_test", "NOTION_TASK_DB": "db_test_id_1234"})
    def test_falls_back_to_select_filter(self):
        """When status filter returns 400, the reader falls back to select filter."""
        from app.services.notion_task_reader import get_pending_notion_tasks

        page = _notion_page("id-3", "Strategy review", "Planned")
        error_response = FakeResponse(400, body='{"message": "validation_error"}')
        ok_response = FakeResponse(200, _notion_query_response([page]))

        call_count = 0

        def fake_post(url, json=None, headers=None):
            nonlocal call_count
            call_count += 1
            filter_body = json or {}
            status_filter = filter_body.get("filter", {})
            if "select" in status_filter:
                return ok_response
            return error_response

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = fake_post

        with patch("app.services.notion_task_reader.httpx.Client", return_value=mock_client):
            tasks = get_pending_notion_tasks()

        assert len(tasks) == 1
        assert tasks[0]["task"] == "Strategy review"

    @patch.dict("os.environ", {"NOTION_API_KEY": "secret_test", "NOTION_TASK_DB": "db_test_id_1234"})
    def test_logs_task_detected(self, caplog):
        """Each detected task produces an INFO log with its title."""
        from app.services.notion_task_reader import get_pending_notion_tasks

        page = _notion_page("id-4", "Audit documentation", "Planned")
        ok_response = FakeResponse(200, _notion_query_response([page]))

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = ok_response

        with caplog.at_level(logging.INFO, logger="app.services.notion_task_reader"):
            with patch("app.services.notion_task_reader.httpx.Client", return_value=mock_client):
                get_pending_notion_tasks()

        log_text = " ".join(caplog.messages)
        assert "task_detected" in log_text
        assert "Audit documentation" in log_text
        assert "notion_tasks_found" in log_text

    def test_missing_api_key_returns_empty(self):
        from app.services.notion_task_reader import get_pending_notion_tasks

        with patch.dict("os.environ", {"NOTION_API_KEY": "", "NOTION_TASK_DB": "db_id"}, clear=False):
            with patch("app.services.notion_task_reader._get_config", return_value=("", "db_id")):
                tasks = get_pending_notion_tasks()
        assert tasks == []


# ---------------------------------------------------------------------------
# Tests: test_notion_task_scan diagnostic function
# ---------------------------------------------------------------------------


class TestNotionTaskScan:

    @patch.dict("os.environ", {"NOTION_API_KEY": "", "NOTION_TASK_DB": ""})
    def test_reports_missing_config(self):
        from app.services.notion_task_reader import test_notion_task_scan

        with patch("app.services.notion_task_reader._get_config", return_value=("", "")):
            report = test_notion_task_scan()

        assert report["ok"] is False
        assert "not set" in (report["error"] or "").lower()

    @patch.dict("os.environ", {"NOTION_API_KEY": "secret_test", "NOTION_TASK_DB": "db_test_id_1234"})
    def test_returns_structured_report(self):
        from app.services.notion_task_reader import test_notion_task_scan

        page = _notion_page("id-5", "Test task", "Planned")
        ok_response = FakeResponse(200, _notion_query_response([page]))

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = ok_response

        with patch("app.services.notion_task_reader.httpx.Client", return_value=mock_client):
            report = test_notion_task_scan()

        assert report["ok"] is True
        assert report["tasks_found"] == 1
        assert report["tasks"][0]["task"] == "Test task"
        assert report["config"]["api_key_set"] is True


# ---------------------------------------------------------------------------
# Tests: scheduler loop and startup wiring
# ---------------------------------------------------------------------------


class TestSchedulerWiring:

    def test_start_agent_scheduler_loop_importable(self):
        """The async loop function exists and is importable."""
        from app.services.agent_scheduler import start_agent_scheduler_loop
        assert inspect.iscoroutinefunction(start_agent_scheduler_loop)

    def test_scheduler_cycle_returns_structured_result(self):
        """run_agent_scheduler_cycle returns a dict with ok/action/reason."""
        from app.services.agent_scheduler import run_agent_scheduler_cycle

        # prepare_task_with_approval_check is lazily imported inside the function,
        # so we mock at the source module where it's defined.
        with patch("app.services.agent_task_executor.get_high_priority_pending_tasks", return_value=[]):
            result = run_agent_scheduler_cycle()

        assert result["ok"] is True
        assert result["action"] == "none"
        assert result["reason"] == "no task"

    def test_scheduler_interval_env_var(self):
        """Interval is configurable via AGENT_SCHEDULER_INTERVAL_SECONDS."""
        from app.services.agent_scheduler import _get_scheduler_interval

        with patch.dict("os.environ", {"AGENT_SCHEDULER_INTERVAL_SECONDS": "120"}):
            assert _get_scheduler_interval() == 120

        with patch.dict("os.environ", {"AGENT_SCHEDULER_INTERVAL_SECONDS": ""}):
            assert _get_scheduler_interval() == 300  # default

        with patch.dict("os.environ", {"AGENT_SCHEDULER_INTERVAL_SECONDS": "10"}):
            assert _get_scheduler_interval() == 30  # minimum clamp

    def test_main_py_references_agent_scheduler(self):
        """main.py contains the startup wiring for the agent scheduler."""
        from pathlib import Path
        main_py = Path(__file__).resolve().parents[1] / "app" / "main.py"
        content = main_py.read_text()
        assert "start_agent_scheduler_loop" in content
        assert "NOTION_API_KEY" in content or "notion_env" in content

    def test_notion_env_missing_then_auto_repair_proceeds(self):
        """Missing NOTION env → pre-flight triggers repair (mocked) → cycle proceeds to no task (no manual steps)."""
        import os
        from app.services.agent_scheduler import run_agent_scheduler_cycle

        saved_key = os.environ.pop("NOTION_API_KEY", None)
        saved_db = os.environ.pop("NOTION_TASK_DB", None)
        try:
            check_calls = []
            def mock_check():
                if len(check_calls) == 0:
                    check_calls.append(1)
                    return (False, "missing")
                return (True, "ssm_repair")

            def mock_repair():
                os.environ["NOTION_API_KEY"] = "test-secret-not-logged"
                os.environ["NOTION_TASK_DB"] = "eb90cfa139f94724a8b476315908510a"
                return True

            with patch("app.services.notion_env.check_notion_env", side_effect=mock_check), \
                 patch("app.services.notion_env.try_repair_notion_env_from_ssm", side_effect=mock_repair), \
                 patch("app.services.agent_task_executor.prepare_task_with_approval_check", return_value=None):
                result = run_agent_scheduler_cycle()
            assert result["ok"] is True
            assert result.get("reason") == "no task"
        finally:
            if saved_key is not None:
                os.environ["NOTION_API_KEY"] = saved_key
            elif "NOTION_API_KEY" in os.environ:
                os.environ.pop("NOTION_API_KEY")
            if saved_db is not None:
                os.environ["NOTION_TASK_DB"] = saved_db
            elif "NOTION_TASK_DB" in os.environ:
                os.environ.pop("NOTION_TASK_DB")

    def test_notion_env_missing_no_repair_skips_cycle(self):
        """When NOTION env missing and repair fails, cycle returns without crashing (reason notion_env_missing)."""
        import os
        from app.services.agent_scheduler import run_agent_scheduler_cycle

        saved_key = os.environ.pop("NOTION_API_KEY", None)
        saved_db = os.environ.pop("NOTION_TASK_DB", None)
        try:
            with patch("app.services.agent_scheduler._ensure_notion_env_preflight", return_value=False):
                result = run_agent_scheduler_cycle()
            assert result["ok"] is True
            assert result.get("reason") == "notion_env_missing"
        finally:
            if saved_key is not None:
                os.environ["NOTION_API_KEY"] = saved_key
            if saved_db is not None:
                os.environ["NOTION_TASK_DB"] = saved_db


# ---------------------------------------------------------------------------
# Tests: agent recovery (stale in-progress playbook)
# ---------------------------------------------------------------------------


class TestAgentRecoveryStaleInProgress:
    """Verify stale in-progress recovery playbook behavior."""

    def test_run_stale_in_progress_playbook_returns_list(self):
        """run_stale_in_progress_playbook returns a list (never None)."""
        from app.services.agent_recovery import run_stale_in_progress_playbook

        result = run_stale_in_progress_playbook(max_tasks=1)
        assert isinstance(result, list)

    @patch.dict("os.environ", {"AGENT_RECOVERY_ENABLED": "false"})
    def test_stale_in_progress_skipped_when_recovery_disabled(self):
        """When AGENT_RECOVERY_ENABLED=false, playbook returns empty list."""
        from app.services.agent_recovery import run_stale_in_progress_playbook

        result = run_stale_in_progress_playbook(max_tasks=5)
        assert result == []


class TestAgentRecoveryMissingArtifactBridgeRace:
    """Verify missing-artifact recovery defers while Cursor Bridge is active."""

    def test_get_tasks_with_missing_artifacts_skips_active_bridge_patching(self):
        from app.services.agent_recovery import _get_tasks_with_missing_artifacts

        task = {
            "id": "32eb1837-03fe-812a-a197-d313f3928531",
            "task": "Race case",
            "status": "patching",
        }

        with (
            patch("app.services.agent_recovery._has_recovery_attempt_for_task", return_value=False),
            patch("app.services.agent_recovery._get_artifact_paths", return_value=[]),
            patch("app.services.agent_recovery._is_bridge_phase2_active_for_task", return_value=True),
            patch(
                "app.services.notion_task_reader.get_tasks_by_status",
                return_value=[task],
            ),
        ):
            result = _get_tasks_with_missing_artifacts(max_results=5)

        assert result == []

    def test_get_tasks_with_missing_artifacts_includes_non_active_bridge_patching(self):
        from app.services.agent_recovery import _get_tasks_with_missing_artifacts

        task = {
            "id": "32eb1837-03fe-812a-a197-d313f3928531",
            "task": "Race case",
            "status": "patching",
        }

        with (
            patch("app.services.agent_recovery._has_recovery_attempt_for_task", return_value=False),
            patch("app.services.agent_recovery._get_artifact_paths", return_value=[]),
            patch("app.services.agent_recovery._is_bridge_phase2_active_for_task", return_value=False),
            patch(
                "app.services.notion_task_reader.get_tasks_by_status",
                return_value=[task],
            ),
        ):
            result = _get_tasks_with_missing_artifacts(max_results=5)

        assert len(result) == 1
        assert result[0]["id"] == task["id"]
