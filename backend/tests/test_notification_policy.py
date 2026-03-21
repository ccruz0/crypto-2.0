"""Regression tests for single-approval notification policy.

Verifies:
- No approval sent during investigation, patching, verifying, or re-iterating
- Single approval only when release-candidate-ready
- No duplicate final approvals on retry/re-entry (idempotency)
- Blocker notifications clearly marked (not approval), no approval buttons
- build_release_candidate_approval_message includes required fields
"""
import os
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock


@pytest.fixture(autouse=True)
def _env():
    os.environ.setdefault("TELEGRAM_BOT_TOKEN", "fake-token")
    os.environ.setdefault("TELEGRAM_CHAT_ID", "12345")
    os.environ.setdefault("TELEGRAM_CLAW_CHAT_ID", "12345")
    yield


class TestReleaseCandidateApprovalMessage:
    """build_release_candidate_approval_message includes all required fields."""

    def test_includes_version(self):
        from app.services.agent_telegram_approval import build_release_candidate_approval_message

        msg = build_release_candidate_approval_message(
            "task-1", "Fix bug", "passed",
            {"Root Cause": "X", "Recommended Fix": "Y", "Task Summary": "Z"},
            proposed_version="atp.3.4",
        )
        assert "atp.3.4" in msg
        assert "VERSION" in msg

    def test_includes_problems_solved(self):
        from app.services.agent_telegram_approval import build_release_candidate_approval_message

        msg = build_release_candidate_approval_message(
            "task-1", "Fix bug", "passed",
            {"Root Cause": "Root cause here", "Recommended Fix": "Fix", "Task Summary": "S"},
        )
        assert "PROBLEMS SOLVED" in msg
        assert "Root cause here" in msg

    def test_includes_improvements(self):
        from app.services.agent_telegram_approval import build_release_candidate_approval_message

        msg = build_release_candidate_approval_message(
            "task-1", "Fix bug", "passed",
            {"Root Cause": "X", "Recommended Fix": "Improvement here", "Task Summary": "S"},
        )
        assert "IMPROVEMENTS" in msg
        assert "Improvement here" in msg

    def test_includes_validation_evidence(self):
        from app.services.agent_telegram_approval import build_release_candidate_approval_message

        msg = build_release_candidate_approval_message(
            "task-1", "Fix bug", "3/3 tests passed",
            {"Root Cause": "X", "Recommended Fix": "Y", "Task Summary": "S"},
        )
        assert "VALIDATION EVIDENCE" in msg
        assert "3/3 tests passed" in msg

    def test_includes_known_risks(self):
        from app.services.agent_telegram_approval import build_release_candidate_approval_message

        msg = build_release_candidate_approval_message(
            "task-1", "Fix bug", "passed",
            {"Root Cause": "X", "Recommended Fix": "Y", "Task Summary": "S", "Risk Level": "Low"},
        )
        assert "KNOWN RISKS" in msg

    def test_includes_approve_reject_prompt(self):
        from app.services.agent_telegram_approval import build_release_candidate_approval_message

        msg = build_release_candidate_approval_message(
            "task-1", "Fix bug", "passed",
            {"Root Cause": "X", "Recommended Fix": "Y", "Task Summary": "S"},
        )
        assert "APPROVE" in msg.upper() or "REJECT" in msg.upper()


class TestBlockerNotification:
    """Blocker notifications are clearly marked, not approval."""

    def test_blocker_prefix_in_message(self):
        from app.services.agent_telegram_approval import send_blocker_notification, MSG_PREFIX_BLOCKER

        with patch("app.services.agent_telegram_approval._send_telegram_message") as mock_send:
            mock_send.return_value = (True, 1)
            send_blocker_notification(
                "task-1", "Title", "Real blocker reason",
                suggested_action="Do X",
            )
            call_args = mock_send.call_args
            text = call_args[0][1]
            assert MSG_PREFIX_BLOCKER in text
            assert "BLOCKER" in text
            assert "not an approval" in text.lower() or "approval" not in text.lower()

    def test_blocker_has_no_approval_buttons(self):
        from app.services.agent_telegram_approval import send_blocker_notification

        with patch("app.services.agent_telegram_approval._send_telegram_message") as mock_send:
            mock_send.return_value = (True, 1)
            send_blocker_notification("task-1", "Title", "Blocker")
            call_args = mock_send.call_args
            # reply_markup is 3rd positional arg
            reply_markup = call_args[0][2] if len(call_args[0]) > 2 else None
            assert reply_markup is None


class TestNoIntermediateApproval:
    """No approval sent at investigation-complete or ready-for-patch."""

    def test_executor_uses_send_release_candidate_approval_not_ready_for_patch(self):
        """advance_ready_for_patch_task sends approval only at release-candidate-ready."""
        import app.services.agent_task_executor as ate

        src = open(ate.__file__).read()
        assert "send_release_candidate_approval" in src
        # No approval at investigation-complete: executor should not call send_ready_for_patch_approval
        assert "send_ready_for_patch_approval" not in src


class TestDeployGateAcceptsReleaseCandidateReady:
    """Deploy gate accepts release-candidate-ready status."""

    def test_deploy_gate_includes_release_candidate_ready(self):
        import app.services.telegram_commands as tc

        # The deploy gate checks current_status in a tuple
        src = open(tc.__file__).read()
        assert "release-candidate-ready" in src


class TestReleaseCandidateApprovalBlocked:
    """Release-candidate approval is blocked when preconditions fail."""

    def test_blocked_when_proposed_version_missing(self):
        """Missing or empty proposed_version blocks send."""
        from app.services.agent_telegram_approval import send_release_candidate_approval

        task_id = "test-missing-pv"
        title = "Test"
        sections = {"Root Cause": "X", "Recommended Fix": "Y", "Task Summary": "Z", "Affected Files": "a.py"}

        with patch("app.services.agent_telegram_approval._send_telegram_message") as mock_send:
            r = send_release_candidate_approval(
                task_id, title, sections=sections, proposed_version="",
            )
            assert r.get("sent") is False
            assert r.get("skipped") == "missing_proposed_version"
            mock_send.assert_not_called()

    def test_blocked_when_dedup_check_unavailable(self):
        """DB error blocks send (fail-closed)."""
        from app.services.agent_telegram_approval import send_release_candidate_approval

        task_id = "test-db-unavail"
        title = "Test"
        sections = {"Root Cause": "X", "Recommended Fix": "Y", "Task Summary": "Z", "Affected Files": "a.py"}

        with patch("app.services.agent_telegram_approval._send_telegram_message") as mock_send, \
             patch("app.services.agent_telegram_approval._get_release_candidate_approval_last_sent_db") as mock_get:
            mock_get.side_effect = RuntimeError("DB unavailable")
            r = send_release_candidate_approval(
                task_id, title, sections=sections, proposed_version="atp.3.4",
            )
        assert r.get("sent") is False
        assert r.get("skipped") == "dedup_check_unavailable"
        mock_send.assert_not_called()


class TestReleaseCandidateApprovalIdempotency:
    """Exactly one approval per task+version; no duplicates on retry."""

    def test_second_call_skipped_same_task_version(self):
        """Second send_release_candidate_approval for same task+version is skipped."""
        from app.services.agent_telegram_approval import send_release_candidate_approval

        task_id = "test-dedup-001"
        title = "Test"
        sections = {"Root Cause": "X", "Recommended Fix": "Y", "Task Summary": "Z", "Affected Files": "a.py"}

        # Simulate "already sent" by making dedup check return (block_send=True, reason="dedup")
        with patch("app.services.agent_telegram_approval._send_telegram_message") as mock_send, \
             patch("app.services.agent_telegram_approval._check_release_candidate_approval_dedup", return_value=(True, "dedup")):
            r = send_release_candidate_approval(
                task_id, title, sections=sections, proposed_version="atp.3.4",
            )

            assert r.get("sent") is False
            assert r.get("skipped") == "dedup"
            mock_send.assert_not_called()

    def test_dedup_key_includes_version(self):
        """Dedup key is task_id:version so different versions get separate approvals."""
        from app.services.agent_telegram_approval import _release_candidate_approval_dedup_key

        k1 = _release_candidate_approval_dedup_key("task-1", "atp.3.4")
        k2 = _release_candidate_approval_dedup_key("task-1", "atp.3.5")
        assert k1 != k2
        assert "atp.3.4" in k1
        assert "atp.3.5" in k2


class TestDedupWriteFailure:
    """Send succeeds but dedup DB write fails: surface failure, block retry within same process."""

    def test_send_success_dedup_write_failure_returns_dedup_write_failed(self):
        """When send succeeds but _set_release_candidate_approval_sent_db returns False, result includes dedup_write_failed."""
        from app.services.agent_telegram_approval import send_release_candidate_approval

        task_id = "test-dedup-write-fail"
        title = "Test"
        sections = {"Root Cause": "X", "Recommended Fix": "Y", "Task Summary": "Z", "Affected Files": "a.py"}
        pv = "atp.5.0"

        with patch("app.services.agent_telegram_approval._send_telegram_message") as mock_send, \
             patch("app.services.agent_telegram_approval._check_release_candidate_approval_dedup", return_value=(False, "")), \
             patch("app.services.agent_telegram_approval._set_release_candidate_approval_sent_db", return_value=False):
            mock_send.return_value = (True, 1)
            r = send_release_candidate_approval(task_id, title, sections=sections, proposed_version=pv)

        assert r.get("sent") is True
        assert r.get("dedup_write_failed") is True
        assert mock_send.call_count == 1

    def test_retry_after_dedup_write_failure_blocked_by_in_memory_fallback(self):
        """Retry for same task+version after send success + dedup write failure is blocked; no duplicate send."""
        from app.services.agent_telegram_approval import send_release_candidate_approval

        task_id = "test-dedup-retry-001"
        title = "Test"
        sections = {"Root Cause": "X", "Recommended Fix": "Y", "Task Summary": "Z", "Affected Files": "a.py"}
        pv = "atp.5.1"

        with patch("app.services.agent_telegram_approval._send_telegram_message") as mock_send, \
             patch("app.services.agent_telegram_approval._set_release_candidate_approval_sent_db", return_value=False):
            mock_send.return_value = (True, 1)
            with patch("app.services.agent_telegram_approval._check_release_candidate_approval_dedup", return_value=(False, "")):
                r1 = send_release_candidate_approval(task_id, title, sections=sections, proposed_version=pv)
            assert r1.get("sent") is True
            assert r1.get("dedup_write_failed") is True

            # Retry: dedup check now uses real impl, hits in-memory fallback
            r2 = send_release_candidate_approval(task_id, title, sections=sections, proposed_version=pv)

        assert r2.get("sent") is False
        assert r2.get("skipped") == "dedup"
        assert mock_send.call_count == 1  # Only first call sent; retry blocked


class TestIntermediateApprovalDisabled:
    """No approval at investigation or ready-for-patch."""

    def test_send_ready_for_patch_approval_returns_skipped(self):
        from app.services.agent_telegram_approval import send_ready_for_patch_approval

        r = send_ready_for_patch_approval(
            "task-1", "Title",
            sections={"Root Cause": "X", "Recommended Fix": "Y", "Task Summary": "Z"},
        )
        assert r.get("sent") is False
        assert r.get("skipped") == "single_approval_workflow"

    def test_send_investigation_complete_approval_returns_skipped(self):
        from app.services.agent_telegram_approval import send_investigation_complete_approval

        r = send_investigation_complete_approval(
            "task-1", "Title",
            sections={"Root Cause": "X", "Recommended Fix": "Y", "Task Summary": "Z"},
        )
        assert r.get("sent") is False
        assert r.get("skipped") == "single_approval_workflow"


class TestSingleApprovalWorkflow:
    """Higher-level workflow: no approval until release-candidate-ready; exactly one per task+version."""

    def test_no_approval_during_investigation_patching_verification(self):
        """Intermediate states never send approval."""
        from app.services.agent_telegram_approval import (
            send_ready_for_patch_approval,
            send_investigation_complete_approval,
        )

        r1 = send_ready_for_patch_approval("t1", "Title", sections={"Root Cause": "X", "Recommended Fix": "Y", "Task Summary": "Z"})
        r2 = send_investigation_complete_approval("t1", "Title", sections={"Root Cause": "X", "Recommended Fix": "Y", "Task Summary": "Z"})

        assert r1.get("sent") is False and r1.get("skipped") == "single_approval_workflow"
        assert r2.get("sent") is False and r2.get("skipped") == "single_approval_workflow"

    def test_one_final_approval_at_release_candidate_ready(self):
        """First call with valid task+version sends; second call same task+version is deduped."""
        from app.services.agent_telegram_approval import send_release_candidate_approval

        task_id = "wf-task-001"
        title = "Workflow Test"
        sections = {"Root Cause": "X", "Recommended Fix": "Y", "Task Summary": "Z", "Affected Files": "a.py"}
        pv = "atp.4.0"

        with patch("app.services.agent_telegram_approval._send_telegram_message") as mock_send, \
             patch("app.services.agent_telegram_approval._check_release_candidate_approval_dedup") as mock_check, \
             patch("app.services.agent_telegram_approval._set_release_candidate_approval_sent_db"):
            mock_send.return_value = (True, 1)
            mock_check.return_value = (False, "")  # allow first send
            r1 = send_release_candidate_approval(task_id, title, sections=sections, proposed_version=pv)
            assert r1.get("sent") is True
            assert mock_send.call_count == 1

            mock_check.return_value = (True, "dedup")  # block second (already sent)
            r2 = send_release_candidate_approval(task_id, title, sections=sections, proposed_version=pv)
            assert r2.get("sent") is False
            assert r2.get("skipped") == "dedup"
            assert mock_send.call_count == 1  # still 1, no second send

    def test_new_version_allowed_new_approval(self):
        """Different version for same task gets a new approval (different dedup key)."""
        from app.services.agent_telegram_approval import _release_candidate_approval_dedup_key

        k1 = _release_candidate_approval_dedup_key("task-1", "atp.3.4")
        k2 = _release_candidate_approval_dedup_key("task-1", "atp.3.5")
        assert k1 != k2
        # Each version has its own key, so a new approval is allowed per version
        assert "atp.3.4" in k1
        assert "atp.3.5" in k2


class TestPatchNotAppliedNoApprovalWording:
    """send_patch_not_applied_message has no approval-style prompt."""

    def test_patch_not_applied_says_not_approval_request(self):
        from app.services.agent_telegram_approval import send_patch_not_applied_message

        with patch("app.services.agent_telegram_approval._send_telegram_message") as mock_send:
            mock_send.return_value = (True, 1)
            send_patch_not_applied_message("task-1", "Title")
            text = mock_send.call_args[0][1]
            assert "not an approval request" in text
            assert "exactly one final approval" in text or "release candidate" in text
