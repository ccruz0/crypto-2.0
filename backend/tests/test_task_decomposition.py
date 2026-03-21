"""Tests for task decomposition and recovery flow."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services import task_decomposition as td
from app.services import task_health_monitor as thm


class TestShouldDecomposeTask:
    """should_decompose_task returns True only when eligible."""

    def test_simple_task_low_retry_not_decomposed(self):
        """Simple task with retry 0 should not decompose."""
        task = {"id": "abc", "task": "Fix typo", "details": "", "status": "investigating"}
        assert td.should_decompose_task(task, 0, already_decomposed=False) is False

    def test_complex_task_at_retry_limit_decomposed(self):
        """Complex task at retry limit should decompose."""
        task = {
            "id": "abc",
            "task": "Verify full end-to-end patch flow",
            "details": "investigate and patch",
            "status": "investigating",
        }
        assert td.should_decompose_task(task, 2, already_decomposed=False) is True

    def test_already_decomposed_skipped(self):
        """Already decomposed parent should not decompose again."""
        task = {"id": "abc", "task": "Full flow", "details": "end-to-end", "status": "investigating"}
        assert td.should_decompose_task(task, 2, already_decomposed=True) is False

    def test_child_task_not_decomposed(self):
        """Child task should not be decomposed (no nested decomposition)."""
        task = {
            "id": "child-1",
            "task": "Subtask 1",
            "details": "[ATP_SUBTASK]\nparent_task_id: parent-123\nsubtask_index: 1",
            "status": "investigating",
        }
        assert td.should_decompose_task(task, 2, already_decomposed=False) is False

    def test_retry_limit_triggers_even_if_not_keyword_complex(self):
        """At retry limit, decompose even without complexity keywords."""
        task = {"id": "abc", "task": "Fix bug", "details": "simple", "status": "investigating"}
        assert td.should_decompose_task(task, 2, already_decomposed=False) is True


class TestDecomposeTask:
    """decompose_task generates child specs."""

    def test_generates_children(self):
        """Decompose produces 2-5 child specs."""
        parent = {
            "id": "parent-123",
            "task": "Verify full patch deploy flow",
            "details": "end-to-end",
            "project": "Operations",
            "type": "Investigation",
        }
        children = td.decompose_task(parent)
        assert 2 <= len(children) <= td.MAX_CHILD_TASKS_PER_PARENT
        for i, c in enumerate(children):
            assert "parent_task_id" in c
            assert c["parent_task_id"] == "parent-123"
            assert "[ATP_SUBTASK]" in c["details"]
            assert f"parent_task_id: parent-123" in c["details"]

    def test_get_parent_task_id(self):
        """get_parent_task_id extracts from details."""
        task = {"details": "[ATP_SUBTASK]\nparent_task_id: abc-123\nsubtask_index: 1"}
        assert td.get_parent_task_id(task) == "abc-123"

    def test_is_child_task(self):
        """is_child_task True when parent_task_id in details."""
        task = {"details": "[ATP_SUBTASK]\nparent_task_id: xyz"}
        assert td.is_child_task(task) is True
        task2 = {"details": "plain task"}
        assert td.is_child_task(task2) is False


class TestTaskHealthMonitorRetryLimits:
    """Task health monitor enforces retry limits."""

    def test_max_auto_reinvestigate_is_two(self):
        """MAX_AUTO_REINVESTIGATE is 2 per spec."""
        assert thm.MAX_AUTO_REINVESTIGATE == 2

    def test_stuck_alert_accepts_retry_attempt(self):
        """_send_stuck_alert accepts retry_attempt (suppressed by quiet mode)."""
        task = {"id": "t1", "task": "Test", "status": "investigating"}
        with patch("app.services.agent_telegram_policy.should_send_agent_telegram", return_value=False):
            thm._send_stuck_alert(task, 20.0, retry_attempt=2)  # No exception


class TestExecuteDecomposition:
    """execute_decomposition creates children and updates parent."""

    def test_execute_decomposition_creates_children(self):
        """Execute creates child tasks in Notion and moves parent."""
        parent = {
            "id": "parent-xyz",
            "task": "Full flow",
            "details": "end-to-end",
            "project": "Ops",
            "type": "Investigation",
        }
        with patch("app.services.notion_tasks.create_notion_task") as mock_create:
            mock_create.side_effect = [
                {"id": "child-1"},
                {"id": "child-2"},
                {"id": "child-3"},
                {"id": "child-4"},
            ]
            with patch("app.services.notion_tasks.update_notion_task_status", return_value=True):
                with patch("app.services.notion_tasks.update_notion_task_metadata", return_value=None):
                    result = td.execute_decomposition(parent)
        assert result["ok"] is True
        assert result["parent_id"] == "parent-xyz"
        assert len(result["child_ids"]) == 4
        assert mock_create.call_count == 4
