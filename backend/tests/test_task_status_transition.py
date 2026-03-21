"""
Regression tests for task status transition invariants.

Enforces:
1. Stuck investigation → ready-for-investigation (never needs-revision)
2. Max retries → blocked (never needs-revision)
3. Needs revision requires metadata (revision_reason/verify_summary/missing_inputs/decision_required)
4. Invalid needs-revision transition is rejected
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services import task_status_transition as tst
from app.services import notion_tasks as nt


# ---------------------------------------------------------------------------
# Needs revision invariant
# ---------------------------------------------------------------------------


class TestNeedsRevisionMetadata:
    """Needs-revision requires at least one of: revision_reason, verify_summary, missing_inputs, decision_required."""

    def test_has_valid_metadata_with_revision_reason(self):
        assert tst._has_valid_needs_revision_metadata({"revision_reason": "Solution failed"}) is True

    def test_has_valid_metadata_with_verify_summary(self):
        assert tst._has_valid_needs_revision_metadata({"verify_summary": "Output does not address task"}) is True

    def test_has_valid_metadata_with_missing_inputs(self):
        assert tst._has_valid_needs_revision_metadata({"missing_inputs": "Account not specified"}) is True

    def test_has_valid_metadata_with_decision_required(self):
        assert tst._has_valid_needs_revision_metadata({"decision_required": "Which exchange?"}) is True

    def test_empty_metadata_rejected(self):
        assert tst._has_valid_needs_revision_metadata({}) is False
        assert tst._has_valid_needs_revision_metadata(None) is False

    def test_metadata_with_empty_strings_rejected(self):
        assert tst._has_valid_needs_revision_metadata({"revision_reason": "", "verify_summary": "  "}) is False


class TestUpdateNotionTaskStatusNeedsRevisionGuard:
    """update_notion_task_status rejects needs-revision without metadata."""

    def test_needs_revision_without_metadata_rejected(self):
        """Direct update_notion_task_status to needs-revision without metadata returns False."""
        ok = nt.update_notion_task_status("page-123", "needs-revision", append_comment="test")
        assert ok is False

    def test_needs_revision_with_metadata_allowed(self):
        with patch.object(nt, "_get_config", return_value=("fake-key", "fake-db")):
            with patch("app.services.notion_tasks.httpx") as mock_httpx:
                mock_client = mock_httpx.Client.return_value.__enter__.return_value
                mock_resp = mock_client.patch.return_value
                mock_resp.status_code = 200
                mock_resp.text = ""
                ok = nt.update_notion_task_status(
                    "page-123",
                    "needs-revision",
                    append_comment="test",
                    needs_revision_metadata={"verify_summary": "Output does not address task"},
                )
        assert ok is True


class TestUpdateNotionTaskStatusPayloadFallback:
    """Re-investigate flow: update_notion_task_status tries rich_text → select → status (native)."""

    def test_ready_for_investigation_succeeds_via_status_payload_when_others_fail(self):
        """When rich_text and select return 400, native status payload succeeds (Notion Kanban Status)."""
        with patch.object(nt, "_get_config", return_value=("fake-key", "fake-db")):
            with patch("app.services.notion_tasks.httpx") as mock_httpx:
                mock_client = mock_httpx.Client.return_value.__enter__.return_value
                patch_calls = []

                def capture_patch(*args, **kwargs):
                    resp = MagicMock()
                    json_payload = kwargs.get("json", {})
                    props = json_payload.get("properties", {}).get("Status", {})
                    # Only status-update calls have properties.Status; _append_page_comment has children
                    if "properties" in json_payload:
                        patch_calls.append(props)
                    if "status" in props:
                        resp.status_code = 200
                        resp.text = ""
                    else:
                        resp.status_code = 400
                        resp.text = '{"code":"validation_error","message":"invalid"}'
                    return resp

                mock_client.patch.side_effect = capture_patch
                ok = nt.update_notion_task_status(
                    "31cb1837-03fe-8045-b8a8-e27cca1198e0",
                    "ready-for-investigation",
                    append_comment="Re-investigate approved",
                )
        assert ok is True
        assert len(patch_calls) >= 3, "Should try rich_text, select, then status"
        assert "status" in patch_calls[-1], "Third attempt must use native status payload"


class TestSafeTransitionToNeedsRevision:
    """safe_transition_to_needs_revision requires metadata."""

    def test_no_metadata_returns_false(self):
        ok = tst.safe_transition_to_needs_revision("task-1")
        assert ok is False

    def test_with_verify_summary_succeeds(self):
        with patch("app.services.task_status_transition.transition_task_status") as mock_trans:
            mock_trans.return_value = True
            ok = tst.safe_transition_to_needs_revision("task-1", verify_summary="Patch does not fix bug")
        assert ok is True
        mock_trans.assert_called_once()
        call_kw = mock_trans.call_args[1]
        assert call_kw["needs_revision_metadata"]["verify_summary"] == "Patch does not fix bug"


class TestTransitionTaskStatusInvalidNeedsRevision:
    """transition_task_status fallbacks when needs-revision has no metadata."""

    def test_invalid_needs_revision_fallbacks_to_ready_for_investigation(self):
        with patch("app.services.notion_tasks.update_notion_task_status") as mock_update:
            mock_update.return_value = True
            ok = tst.transition_task_status(
                "task-1",
                "needs-revision",
                retryable=True,
            )
        assert ok is False
        # Should have fallbacked to ready-for-investigation
        mock_update.assert_called()
        call_args = mock_update.call_args[0]
        assert call_args[1] == "ready-for-investigation"
