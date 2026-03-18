"""
Tests for task_compiler duplicate detection and reuse (find_similar_task).

Covers: exact duplicate → reused, similar wording → reused, different meaning → new task,
completed task → NOT reused.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.task_compiler import (
    SIMILARITY_THRESHOLD,
    _similarity_score,
    _tokenize_for_similarity,
    create_task_from_telegram_intent,
    find_similar_task,
)


class TestTokenizeAndSimilarity:
    """Deterministic tokenization and score."""

    def test_tokenize_lowercase_stopwords_removed(self) -> None:
        tokens = _tokenize_for_similarity("Investigate why the alerts are not working")
        assert "investigate" in tokens
        assert "alerts" in tokens
        assert "working" in tokens
        assert "the" not in tokens
        assert "are" not in tokens

    def test_similarity_exact_match(self) -> None:
        intent = "investigate alerts not working"
        title = "Investigate why alerts are not working"
        details = "User reported alerts not firing."
        intent_t = _tokenize_for_similarity(intent)
        score = _similarity_score(intent_t, title, details)
        assert score >= SIMILARITY_THRESHOLD
        assert score == 1.0  # all intent words appear

    def test_similarity_similar_wording(self) -> None:
        intent = "investigate dashboard position size mismatch"
        title = "Investigate why dashboard position size does not match runtime"
        details = "Position size discrepancy."
        intent_t = _tokenize_for_similarity(intent)
        score = _similarity_score(intent_t, title, details)
        assert score >= SIMILARITY_THRESHOLD

    def test_similarity_different_meaning(self) -> None:
        intent = "deploy new backend to production"
        title = "Investigate why alerts are not sent"
        details = "Alerts not firing when conditions met."
        intent_t = _tokenize_for_similarity(intent)
        score = _similarity_score(intent_t, title, details)
        assert score < SIMILARITY_THRESHOLD

    def test_similarity_empty_intent_zero(self) -> None:
        assert _similarity_score(set(), "Some title", "Some details") == 0.0


class TestFindSimilarTask:
    """find_similar_task returns existing task when similar, None otherwise."""

    @patch("app.services.task_compiler.get_tasks_by_status")
    @patch("app.services.task_compiler.notion_is_configured", return_value=True)
    def test_exact_duplicate_reused(
        self, _mock_configured: object, mock_get_tasks: object
    ) -> None:
        mock_get_tasks.return_value = [
            {
                "id": "task-123",
                "task": "Investigate why alerts are not working",
                "status": "planned",
                "details": "User said alerts not firing.",
                "type": "Investigation",
            },
        ]
        found = find_similar_task("investigate why alerts are not working")
        assert found is not None
        assert found.get("id") == "task-123"
        assert "alerts" in (found.get("task") or "").lower()

    @patch("app.services.task_compiler.get_tasks_by_status")
    @patch("app.services.task_compiler.notion_is_configured", return_value=True)
    def test_similar_wording_reused(
        self, _mock_configured: object, mock_get_tasks: object
    ) -> None:
        mock_get_tasks.return_value = [
            {
                "id": "task-456",
                "task": "Investigate dashboard position size mismatch",
                "status": "ready-for-investigation",
                "details": "Dashboard shows different size than runtime.",
                "type": "Investigation",
            },
        ]
        found = find_similar_task("investigate dashboard position size does not match")
        assert found is not None
        assert found.get("id") == "task-456"

    @patch("app.services.task_compiler.get_tasks_by_status")
    @patch("app.services.task_compiler.notion_is_configured", return_value=True)
    def test_different_meaning_not_reused(
        self, _mock_configured: object, mock_get_tasks: object
    ) -> None:
        mock_get_tasks.return_value = [
            {
                "id": "task-789",
                "task": "Investigate why alerts are not sent",
                "status": "planned",
                "details": "Alerts not firing.",
                "type": "Investigation",
            },
        ]
        found = find_similar_task("deploy new backend to production tonight")
        assert found is None

    @patch("app.services.task_compiler.get_tasks_by_status")
    @patch("app.services.task_compiler.notion_is_configured", return_value=True)
    def test_completed_task_not_reused(
        self, _mock_configured: object, mock_get_tasks: object
    ) -> None:
        mock_get_tasks.return_value = [
            {
                "id": "task-done",
                "task": "Investigate why alerts are not working",
                "status": "done",
                "details": "Fixed.",
                "type": "Investigation",
            },
        ]
        found = find_similar_task("investigate why alerts are not working")
        assert found is None


class TestCreateTaskFromTelegramIntentReuse:
    """create_task_from_telegram_intent returns reused and does not create when similar exists."""

    @patch("app.services.task_compiler.update_notion_task_status")
    @patch("app.services.task_compiler.create_notion_task")
    @patch("app.services.task_compiler.find_similar_task")
    @patch("app.services.task_compiler.notion_is_configured", return_value=True)
    def test_reused_response_has_reused_true_and_no_create(
        self,
        _mock_configured: object,
        mock_find: object,
        mock_create: object,
        _mock_update_status: object,
    ) -> None:
        mock_find.return_value = {
            "id": "existing-id",
            "task": "Investigate alerts not working",
            "status": "planned",
            "type": "Investigation",
        }
        result = create_task_from_telegram_intent("investigate alerts not working", "Carlos")
        assert result.get("ok") is True
        assert result.get("reused") is True
        assert result.get("task_id") == "existing-id"
        assert result.get("title") == "Investigate alerts not working"
        mock_create.assert_not_called()

    @patch("app.services.task_compiler.create_notion_task")
    @patch("app.services.task_compiler.find_similar_task", return_value=None)
    @patch("app.services.task_compiler.notion_is_configured", return_value=True)
    def test_no_similar_creates_new(
        self, _mock_configured: object, _mock_find: object, mock_create: object
    ) -> None:
        mock_create.return_value = {"id": "new-page-id", "url": "https://notion.so/new"}
        result = create_task_from_telegram_intent("deploy to production", "Carlos")
        mock_create.assert_called_once()
        assert result.get("ok") is True
        assert result.get("reused") is not True
        assert result.get("task_id") == "new-page-id"
