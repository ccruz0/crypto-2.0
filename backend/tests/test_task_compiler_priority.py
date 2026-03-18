"""
Tests for task_compiler priority scoring and scheduler integration.

Covers: Bug > Investigation, urgent + prod > normal, reused boost, low priority filter.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.notion_task_reader import (
    PRIORITY_SCORE_LOW_THRESHOLD,
    get_high_priority_pending_tasks,
)
from app.services.task_compiler import (
    PRIORITY_CAP,
    compute_task_priority,
)


class TestComputeTaskPriority:
    """Priority scoring: type weight + keyword boosts, cap 100."""

    def test_bug_greater_than_investigation(self) -> None:
        bug_task = {"title": "Fix login", "type": "Bug", "details": ""}
        inv_task = {"title": "Investigate login", "type": "Investigation", "details": ""}
        bug_score = compute_task_priority(bug_task, "")
        inv_score = compute_task_priority(inv_task, "")
        assert bug_score > inv_score
        assert bug_score == 40  # Bug base
        assert inv_score == 30  # Investigation base

    def test_urgent_and_prod_higher_than_normal(self) -> None:
        normal = {"title": "Investigate alerts", "type": "Investigation", "details": ""}
        urgent_prod = {
            "title": "Fix trading orders not working in production urgent",
            "type": "Bug",
            "details": "production trading orders not working asap",
        }
        normal_score = compute_task_priority(normal, "")
        urgent_score = compute_task_priority(urgent_prod, "urgent production not working")
        assert urgent_score > normal_score
        assert urgent_score == 100  # Bug + prod + failure + urgency, capped at 100
        assert normal_score == 30

    def test_reused_task_gets_boost(self) -> None:
        task = {"title": "Investigate sync", "type": "Investigation", "details": ""}
        score_new = compute_task_priority(task, "", reused=False)
        score_reused = compute_task_priority(task, "", reused=True)
        assert score_reused == score_new + 15

    def test_priority_capped_at_100(self) -> None:
        task = {
            "title": "urgent fix production trading orders not working broken error",
            "type": "Bug",
            "details": "asap now immediately",
        }
        score = compute_task_priority(task, "urgent production not working", reused=True)
        assert score <= PRIORITY_CAP
        assert score == 100

    def test_content_low_base(self) -> None:
        task = {"title": "Write docs", "type": "Content", "details": ""}
        score = compute_task_priority(task, "")
        assert score == 10


class TestSchedulerPrioritySelection:
    """get_high_priority_pending_tasks sorts by priority_score and applies low filter."""

    @patch("app.services.notion_task_reader.get_pending_notion_tasks")
    def test_tasks_sorted_by_priority_score_desc(
        self, mock_get_pending: object
    ) -> None:
        mock_get_pending.return_value = [
            {"id": "1", "task": "Low", "priority": "low", "priority_score": 25},
            {"id": "2", "task": "High", "priority": "high", "priority_score": 85},
            {"id": "3", "task": "Mid", "priority": "medium", "priority_score": 50},
        ]
        tasks = get_high_priority_pending_tasks()
        assert len(tasks) == 3
        assert tasks[0]["id"] == "2"
        assert tasks[0]["priority_score"] == 85
        assert tasks[1]["id"] == "3"
        assert tasks[2]["id"] == "1"

    @patch("app.services.notion_task_reader.get_pending_notion_tasks")
    def test_low_priority_ignored_when_higher_available(
        self, mock_get_pending: object
    ) -> None:
        mock_get_pending.return_value = [
            {"id": "low", "task": "Content task", "priority": "low", "priority_score": 10},
            {"id": "high", "task": "Bug fix", "priority": "high", "priority_score": 70},
        ]
        tasks = get_high_priority_pending_tasks()
        # Only tasks with priority_score >= 20
        assert len(tasks) == 1
        assert tasks[0]["id"] == "high"
        assert tasks[0]["priority_score"] == 70

    @patch("app.services.notion_task_reader.get_pending_notion_tasks")
    def test_low_priority_included_when_idle(
        self, mock_get_pending: object
    ) -> None:
        mock_get_pending.return_value = [
            {"id": "only", "task": "Content only", "priority": "low", "priority_score": 10},
        ]
        tasks = get_high_priority_pending_tasks()
        # All below threshold -> idle -> return all
        assert len(tasks) == 1
        assert tasks[0]["id"] == "only"
        assert tasks[0]["priority_score"] == 10
