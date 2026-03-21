"""
Tests for task health monitor: stuck detection, recovery, retry limit, alert cooldown.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.services import task_health_monitor as thm


def _task(
    task_id: str = "tid-123",
    title: str = "Test task",
    status: str = "in-progress",
    last_edited_time: str | None = None,
    created_time: str | None = None,
) -> dict:
    return {
        "id": task_id,
        "task": title,
        "status": status,
        "last_edited_time": last_edited_time or "",
        "created_time": created_time or "",
    }


# ---------------------------------------------------------------------------
# Stuck detection
# ---------------------------------------------------------------------------


class TestIsTaskStuck:
    def test_empty_task_not_stuck(self):
        assert thm.is_task_stuck({}) is False
        assert thm.is_task_stuck(None) is False

    def test_unmonitored_status_not_stuck(self):
        now = datetime.now(timezone.utc)
        old = (now - timedelta(minutes=60)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        t = _task(status="done", last_edited_time=old)
        assert thm.is_task_stuck(t, now) is False
        t["status"] = "planned"
        assert thm.is_task_stuck(t, now) is False

    def test_in_progress_over_15_min_stuck(self):
        now = datetime.now(timezone.utc)
        old = (now - timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        t = _task(status="in-progress", last_edited_time=old)
        assert thm.is_task_stuck(t, now) is True

    def test_in_progress_under_15_min_not_stuck(self):
        now = datetime.now(timezone.utc)
        recent = (now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        t = _task(status="in-progress", last_edited_time=recent)
        assert thm.is_task_stuck(t, now) is False

    def test_patching_over_10_min_stuck(self):
        now = datetime.now(timezone.utc)
        old = (now - timedelta(minutes=12)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        t = _task(status="patching", last_edited_time=old)
        assert thm.is_task_stuck(t, now) is True

    def test_testing_over_10_min_stuck(self):
        now = datetime.now(timezone.utc)
        old = (now - timedelta(minutes=11)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        t = _task(status="testing", last_edited_time=old)
        assert thm.is_task_stuck(t, now) is True

    def test_uses_created_time_when_last_edited_missing(self):
        now = datetime.now(timezone.utc)
        old = (now - timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        t = _task(status="in-progress", last_edited_time="", created_time=old)
        assert thm.is_task_stuck(t, now) is True

    def test_no_timestamp_not_stuck(self):
        now = datetime.now(timezone.utc)
        t = _task(status="in-progress", last_edited_time="", created_time="")
        assert thm.is_task_stuck(t, now) is False


# ---------------------------------------------------------------------------
# Recovery and retry limit
# ---------------------------------------------------------------------------


class TestHandleStuckTask:
    def setup_method(self):
        # Reset in-memory state so tests don't affect each other
        thm._last_alert_sent.clear()
        thm._retry_count.clear()

    def test_investigation_stuck_moves_to_ready_for_investigation(self):
        """Investigation stuck moves to ready-for-investigation (retryable), never Needs Revision."""
        now = datetime.now(timezone.utc)
        old = (now - timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        t = _task(task_id="inv-1", status="investigating", last_edited_time=old)
        with patch("app.services.notion_tasks.update_notion_task_status") as mock_update:
            with patch("app.services.notion_tasks.update_notion_task_metadata") as mock_meta:
                with patch.object(thm, "_send_stuck_alert"):
                    with patch.object(thm, "_log_event"):
                        thm.handle_stuck_task(t, now)
        mock_update.assert_called_once()
        call_args = mock_update.call_args[0]
        assert call_args[0] == "inv-1"
        assert call_args[1] == "ready-for-investigation"

    def test_max_retries_moves_to_blocked_not_needs_revision(self):
        """Max retries moves to Blocked (operational failure), never Needs Revision."""
        now = datetime.now(timezone.utc)
        old = (now - timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        t = _task(task_id="max-1", status="patching", last_edited_time=old)
        thm._retry_count["max-1"] = thm.MAX_RETRIES  # already at max
        with patch("app.services.notion_tasks.update_notion_task_status") as mock_update:
            with patch("app.services.notion_tasks.update_notion_task_metadata") as mock_meta:
                with patch.object(thm, "_send_manual_attention_alert") as mock_manual:
                    with patch.object(thm, "_log_event"):
                        thm.handle_stuck_task(t, now)
        mock_update.assert_called_once()
        call_args = mock_update.call_args[0]
        assert call_args[0] == "max-1"
        assert call_args[1] == "blocked"
        mock_manual.assert_called_once()
        # Retry count should be cleared so we don't keep updating
        assert "max-1" not in thm._retry_count

    def test_alert_cooldown_prevents_duplicate_stuck_alerts(self):
        now = datetime.now(timezone.utc)
        old = (now - timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        t = _task(task_id="cooldown-1", status="testing", last_edited_time=old)
        alerts = []

        def capture_alert(task, minutes_stuck, **kwargs):
            alerts.append((task.get("id"), minutes_stuck))

        with patch("app.services.notion_tasks.update_notion_task_status"):
            with patch.object(thm, "_send_stuck_alert", side_effect=capture_alert):
                with patch.object(thm, "_log_event"):
                    thm.handle_stuck_task(t, now)
                    thm.handle_stuck_task(t, now)  # same task again immediately
        # Should have sent alert only once (second call is within cooldown)
        assert len(alerts) == 1
        assert alerts[0][0] == "cooldown-1"


# ---------------------------------------------------------------------------
# check_for_stuck_tasks
# ---------------------------------------------------------------------------


class TestCheckForStuckTasks:
    def setup_method(self):
        thm._last_alert_sent.clear()
        thm._retry_count.clear()

    def test_returns_count_of_stuck_tasks_handled(self):
        now = datetime.now(timezone.utc)
        old = (now - timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        stuck_task = _task(task_id="stuck-1", status="in-progress", last_edited_time=old)
        with patch("app.services.notion_task_reader.get_tasks_by_status", return_value=[stuck_task]):
            with patch.object(thm, "handle_stuck_task"):
                n = thm.check_for_stuck_tasks()
        assert n == 1

    def test_returns_zero_when_no_stuck_tasks(self):
        now = datetime.now(timezone.utc)
        recent = (now - timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        fresh = _task(task_id="fresh-1", status="in-progress", last_edited_time=recent)
        with patch("app.services.notion_task_reader.get_tasks_by_status", return_value=[fresh]):
            n = thm.check_for_stuck_tasks()
        assert n == 0

    def test_handles_empty_task_list(self):
        with patch("app.services.notion_task_reader.get_tasks_by_status", return_value=[]):
            n = thm.check_for_stuck_tasks()
        assert n == 0
