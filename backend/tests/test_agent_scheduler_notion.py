"""
Tests for the agent scheduler and Notion task reader fixes.

Validates:
1. Case-insensitive Status filter (both "planned" and "Planned" match)
2. Diagnostic logging produces expected messages
3. test_notion_task_scan() returns structured results
4. Scheduler background loop function exists and is importable
5. Scheduler is wired into FastAPI startup
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
    """Verify the case-insensitive Status filter and diagnostic logging."""

    @patch.dict("os.environ", {"NOTION_API_KEY": "secret_test", "NOTION_TASK_DB": "db_test_id_1234"})
    def test_finds_tasks_with_lowercase_planned(self):
        """Tasks with status 'planned' (lowercase) are found on the first try."""
        from app.services.notion_task_reader import get_pending_notion_tasks

        page = _notion_page("id-1", "Fix docs", "planned")
        ok_response = FakeResponse(200, _notion_query_response([page]))

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = ok_response

        with patch("app.services.notion_task_reader.httpx.Client", return_value=mock_client):
            tasks = get_pending_notion_tasks()

        assert len(tasks) == 1
        assert tasks[0]["task"] == "Fix docs"
        assert tasks[0]["status"] == "planned"

    @patch.dict("os.environ", {"NOTION_API_KEY": "secret_test", "NOTION_TASK_DB": "db_test_id_1234"})
    def test_finds_tasks_with_capitalized_planned(self):
        """When 'planned' returns 0 results, the reader retries with 'Planned'."""
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
            equals_value = rt.get("equals") or sel.get("equals") or ""

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
        # planned/rich_text returns [] (success, 0 results) → skip to "Planned" variant
        # Planned/rich_text returns 1 result → done.  Select fallback only on HTTP errors.
        assert call_count >= 2

    @patch.dict("os.environ", {"NOTION_API_KEY": "secret_test", "NOTION_TASK_DB": "db_test_id_1234"})
    def test_falls_back_to_select_filter(self):
        """When rich_text filter returns 400, the reader falls back to select filter."""
        from app.services.notion_task_reader import get_pending_notion_tasks

        page = _notion_page("id-3", "Strategy review", "planned")
        error_response = FakeResponse(400, body='{"message": "validation error"}')
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

        page = _notion_page("id-4", "Audit documentation", "planned")
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

        page = _notion_page("id-5", "Test task", "planned")
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
        assert "NOTION_API_KEY" in content
        assert "NOTION_TASK_DB" in content
