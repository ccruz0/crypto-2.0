"""
Tests for task value gating: compute_task_value, creation gate, execution gate, safety (Bug/prod/priority>60).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.task_compiler import (
    VALUE_CREATION_THRESHOLD,
    VALUE_SAFETY_PRIORITY_MIN,
    compute_task_value,
    _value_gate_safety_pass,
    create_task_from_telegram_intent,
)


class TestComputeTaskValue:
    """Value scoring: impact + urgency + failure + strategic - noise, cap 0-100."""

    def test_low_value_noise_only(self) -> None:
        task = {"title": "maybe try a test experiment", "details": "", "type": "Investigation"}
        value = compute_task_value(task, "")
        assert value < VALUE_CREATION_THRESHOLD
        assert value >= 0

    def test_high_value_production_urgent(self) -> None:
        task = {
            "title": "Fix orders not working in production urgent",
            "details": "trading revenue broken asap",
            "type": "Bug",
        }
        value = compute_task_value(task, "")
        assert value >= VALUE_CREATION_THRESHOLD
        assert value <= 100

    def test_high_value_failure_signal(self) -> None:
        task = {"title": "Error in sync", "details": "not working broken", "type": "Investigation"}
        value = compute_task_value(task, "")
        assert value >= VALUE_CREATION_THRESHOLD

    def test_strategic_adds_value(self) -> None:
        task = {"title": "Review core architecture", "details": "system security", "type": "Investigation"}
        value = compute_task_value(task, "")
        assert value >= 20

    def test_value_capped_at_100(self) -> None:
        task = {
            "title": "urgent production orders trading revenue error not working broken architecture core system security",
            "details": "now asap",
            "type": "Bug",
        }
        value = compute_task_value(task, "")
        assert value <= 100

    def test_operational_keywords_add_value(self) -> None:
        """Operational/production-blocking terms (blocks, incident, workflow) boost value."""
        task = {"title": "Telegram blocks operational task creation", "details": "", "type": "Investigation"}
        value = compute_task_value(task, "")
        assert value >= VALUE_CREATION_THRESHOLD

    def test_production_blocks_incident_adds_value(self) -> None:
        task = {"title": "Production task intake broken prevents incident response", "details": "", "type": "Investigation"}
        value = compute_task_value(task, "")
        assert value >= VALUE_CREATION_THRESHOLD


class TestValueGateSafetyPass:
    """Never block: Bug tasks, production-related text, or priority > 60."""

    def test_bug_always_passes(self) -> None:
        task = {"title": "maybe try something", "type": "Bug", "details": "test experiment"}
        assert _value_gate_safety_pass(task, 10) is True
        assert _value_gate_safety_pass(task, 0) is True

    def test_production_always_passes(self) -> None:
        task = {"title": "Check production", "type": "Investigation", "details": ""}
        assert _value_gate_safety_pass(task, 25) is True
        task2 = {"title": "Orders in prod", "type": "Investigation", "details": ""}
        assert _value_gate_safety_pass(task2, 20) is True

    def test_operational_keywords_always_pass(self) -> None:
        task = {"title": "Blocks operational workflow", "type": "Investigation", "details": "prevents incident response"}
        assert _value_gate_safety_pass(task, 25) is True

    def test_priority_above_60_always_passes(self) -> None:
        task = {"title": "maybe try test", "type": "Investigation", "details": "experiment"}
        assert _value_gate_safety_pass(task, 61) is True
        assert _value_gate_safety_pass(task, 60) is False

    def test_low_value_no_safety_fails(self) -> None:
        task = {"title": "maybe try later", "type": "Investigation", "details": "test"}
        assert _value_gate_safety_pass(task, 25) is False


class TestCreationGate:
    """All tasks created; low-value get status=backlog, priority=low. Never reject."""

    @patch("app.services.task_compiler.notion_is_configured", return_value=True)
    @patch("app.services.task_compiler.find_similar_task", return_value=None)
    @patch("app.services.task_compiler.create_notion_task")
    def test_low_value_task_created_queued(
        self, mock_create: object, mock_find: object, mock_notion_ok: object
    ) -> None:
        mock_create.return_value = {"id": "low-123", "dry_run": False}
        result = create_task_from_telegram_intent(
            "maybe check something later try experiment",
            "TestUser",
        )
        assert result.get("ok") is True
        assert result.get("task_id") == "low-123"
        assert result.get("priority_label") == "low"
        assert result.get("status") == "Backlog"
        mock_create.assert_called_once()
        call_kw = mock_create.call_args[1]
        assert call_kw.get("status") == "backlog"
        assert call_kw.get("priority") == "Low"

    @patch("app.services.task_compiler.notion_is_configured", return_value=True)
    @patch("app.services.task_compiler.find_similar_task", return_value=None)
    @patch("app.services.task_compiler.create_notion_task")
    def test_high_value_task_created(
        self, mock_create: object, mock_find: object, mock_notion_ok: object
    ) -> None:
        mock_create.return_value = {"id": "page-123", "dry_run": False}
        result = create_task_from_telegram_intent(
            "Fix orders failing in production urgent",
            "TestUser",
        )
        assert result.get("ok") is True
        assert result.get("task_id") == "page-123"
        mock_create.assert_called_once()

    @patch("app.services.task_compiler.notion_is_configured", return_value=True)
    @patch("app.services.task_compiler.find_similar_task", return_value=None)
    @patch("app.services.task_compiler.create_notion_task")
    def test_bug_always_passes_creation_gate(
        self, mock_create: object, mock_find: object, mock_notion_ok: object
    ) -> None:
        mock_create.return_value = {"id": "bug-456", "dry_run": False}
        result = create_task_from_telegram_intent(
            "maybe try fix bug in test",
            "TestUser",
        )
        # Bug type is inferred from "fix" and "bug"; safety pass so creation allowed even if value low
        assert result.get("ok") is True
        mock_create.assert_called_once()

    @patch("app.services.task_compiler.notion_is_configured", return_value=True)
    @patch("app.services.task_compiler.find_similar_task", return_value=None)
    @patch("app.services.task_compiler.create_notion_task")
    def test_production_task_always_passes_creation_gate(
        self, mock_create: object, mock_find: object, mock_notion_ok: object
    ) -> None:
        mock_create.return_value = {"id": "prod-789", "dry_run": False}
        result = create_task_from_telegram_intent(
            "Check production dashboard maybe later",
            "TestUser",
        )
        assert result.get("ok") is True
        mock_create.assert_called_once()

    @patch("app.services.task_compiler.notion_is_configured", return_value=True)
    @patch("app.services.task_compiler.find_similar_task", return_value=None)
    @patch("app.services.task_compiler.create_notion_task")
    def test_operational_production_blocking_tasks_accepted(
        self, mock_create: object, mock_find: object, mock_notion_ok: object
    ) -> None:
        """Operational/production-blocking task texts must be accepted (created, not rejected)."""
        mock_create.return_value = {"id": "op-1", "dry_run": False}
        texts = [
            "Telegram task creation is failing in production and blocks incident response",
            "Production task intake from Telegram is broken",
            "Operational Telegram command failure blocks workflow",
        ]
        for text in texts:
            mock_create.reset_mock()
            mock_create.return_value = {"id": "op-1", "dry_run": False}
            result = create_task_from_telegram_intent(text, "TestUser")
            assert result.get("ok") is True, f"Task text {text!r} should be accepted"
            mock_create.assert_called_once()
