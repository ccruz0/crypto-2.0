"""Tests for task lifecycle hardening fixes.

Validates:
- DB-backed retry persistence (retry count survives restart)
- DB-backed stuck alert dedup (no duplicate alerts across workers/restarts)
- Retryable LLM failures (no generic fallback, task → ready-for-investigation)
- Investigation quality gate (generic root cause rejected, concrete accepted)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services import agent_callbacks
from app.services import task_health_monitor as thm


# ---------------------------------------------------------------------------
# DB-backed retry persistence
# ---------------------------------------------------------------------------


class TestDBBackedRetryPersistence:
    """Retry count survives restart; task stops after max retries."""

    def setup_method(self):
        thm._retry_count.clear()
        thm._last_alert_sent.clear()

    def test_retry_count_from_db_persisted_after_increment(self):
        """Retry count is persisted to DB after each stuck handling (survives restart)."""
        with patch.object(thm, "_get_stuck_retry_count_db", return_value=0):
            with patch.object(thm, "_get_stuck_alert_last_sent_db", return_value=None):
                with patch.object(thm, "_set_stuck_retry_count_db") as mock_set_retry:
                    with patch.object(thm, "_set_stuck_alert_last_sent_db"):
                        t = {
                            "id": "tid-db-persist",
                            "task": "Test",
                            "status": "in-progress",
                            "last_edited_time": "2020-01-01T00:00:00.000Z",
                            "created_time": "2020-01-01T00:00:00.000Z",
                        }
                        from datetime import datetime, timezone
                        now = datetime.now(timezone.utc)
                        with patch("app.services.notion_tasks.update_notion_task_status"):
                            with patch("app.services.notion_tasks.update_notion_task_metadata"):
                                with patch.object(thm, "_send_stuck_alert"):
                                    with patch.object(thm, "_log_event"):
                                        thm.handle_stuck_task(t, now)
                        # DB receives persisted retry count (0 + 1 = 1)
                        mock_set_retry.assert_called_with("tid-db-persist", 1)
                        assert thm._retry_count.get("tid-db-persist") == 1

    def test_task_stops_after_max_retries_blocked(self):
        """At max retries, task moves to blocked, not infinite loop."""
        with patch.object(thm, "_get_stuck_retry_count_db", return_value=2):
            with patch.object(thm, "_get_stuck_alert_last_sent_db", return_value=None):
                t = {
                    "id": "tid-max",
                    "task": "Test",
                    "status": "patching",
                    "last_edited_time": "2020-01-01T00:00:00.000Z",
                    "created_time": "2020-01-01T00:00:00.000Z",
                }
                from datetime import datetime, timezone
                now = datetime.now(timezone.utc)
                with patch("app.services.task_decomposition.should_decompose_task", return_value=False):
                    with patch("app.services.task_decomposition.execute_decomposition"):
                        with patch("app.services.notion_tasks.update_notion_task_status") as mock_update:
                            with patch("app.services.notion_tasks.update_notion_task_metadata"):
                                with patch.object(thm, "_send_manual_attention_alert"):
                                    with patch.object(thm, "_log_event"):
                                        thm.handle_stuck_task(t, now)
                mock_update.assert_called_once()
                assert mock_update.call_args[0][1] == "blocked"


# ---------------------------------------------------------------------------
# DB-backed stuck alert dedup
# ---------------------------------------------------------------------------


class TestDBBackedStuckAlertDedup:
    """Duplicate alerts not sent across restarts/workers."""

    def setup_method(self):
        thm._last_alert_sent.clear()
        thm._retry_count.clear()

    def test_second_process_respects_db_alert_cooldown(self):
        """When DB has recent alert timestamp, no duplicate alert sent."""
        import time
        recent_ts = time.time() - 60  # 1 min ago
        with patch.object(thm, "_get_stuck_retry_count_db", return_value=0):
            with patch.object(thm, "_get_stuck_alert_last_sent_db", return_value=recent_ts):
                t = {
                    "id": "tid-dedup",
                    "task": "Test",
                    "status": "testing",
                    "last_edited_time": "2020-01-01T00:00:00.000Z",
                    "created_time": "2020-01-01T00:00:00.000Z",
                }
                from datetime import datetime, timezone
                now = datetime.now(timezone.utc)
                alerts = []

                def capture(task, minutes_stuck, **kw):
                    alerts.append(1)

                with patch("app.services.notion_tasks.update_notion_task_status"):
                    with patch.object(thm, "_send_stuck_alert", side_effect=capture):
                        with patch.object(thm, "_log_event"):
                            thm.handle_stuck_task(t, now)
                # Within 30 min cooldown, no alert
                assert len(alerts) == 0


# ---------------------------------------------------------------------------
# Retryable LLM failures
# ---------------------------------------------------------------------------


class TestRetryableLLMFailures:
    """No generic fallback on retryable error; task → ready-for-investigation."""

    def test_retryable_error_returns_no_fallback(self):
        """When OpenClaw fails with rate limit, no template fallback is used."""
        prepared = {
            "task": {"id": "t1", "task": "Fix bug", "type": "bug"},
            "repo_area": {},
        }
        with patch("app.services.openclaw_client.send_to_openclaw") as mock_send:
            mock_send.return_value = {
                "success": False,
                "content": "",
                "error": "HTTP 429: rate limit exceeded",
            }
            with patch("app.services.openclaw_client.is_openclaw_configured", return_value=True):
                result = agent_callbacks._apply_via_openclaw(
                    prepared,
                    lambda _: ("prompt", "instructions"),
                    "docs/agents/bug-investigations",
                    "notion-bug",
                    fallback_fn=lambda _: {"success": True, "summary": "template fallback"},
                    use_agent_schema=False,
                )
        assert result.get("success") is False
        assert result.get("retryable") is True
        assert "rate limit" in (result.get("summary") or "").lower()
        # Fallback must NOT have been used
        assert "template fallback" not in str(result)

    def test_non_retryable_error_uses_fallback(self):
        """When error is not retryable (e.g. schema), fallback can be used."""
        prepared = {
            "task": {"id": "t2", "task": "Fix bug", "type": "bug"},
            "repo_area": {},
        }
        with patch("app.services.openclaw_client.send_to_openclaw") as mock_send:
            mock_send.return_value = {
                "success": False,
                "content": "",
                "error": "Invalid schema: unknown field",
            }
            with patch("app.services.openclaw_client.is_openclaw_configured", return_value=True):
                result = agent_callbacks._apply_via_openclaw(
                    prepared,
                    lambda _: ("prompt", "instructions"),
                    "docs/agents/bug-investigations",
                    "notion-bug",
                    fallback_fn=lambda _: {"success": True, "summary": "template fallback"},
                    use_agent_schema=False,
                )
        # Non-retryable: fallback is used
        assert result.get("success") is True
        assert result.get("summary") == "template fallback"


# ---------------------------------------------------------------------------
# Investigation quality gate
# ---------------------------------------------------------------------------


class TestInvestigationQualityGate:
    """Generic root cause rejected; concrete evidence-based accepted."""

    def test_generic_root_cause_rejected(self):
        """Root Cause with only generic filler is rejected."""
        from pathlib import Path
        from app.services._paths import get_writable_dir_for_subdir
        inv_dir = get_writable_dir_for_subdir("docs/agents/bug-investigations")
        inv_dir.mkdir(parents=True, exist_ok=True)
        note_path = inv_dir / "notion-bug-t1-generic.md"
        content = """# Investigation

---

## Root Cause

Further investigation needed. Check the logs for more details.

## Affected modules

- `backend/app/main.py`

## Relevant docs

- docs/architecture/system-map.md

## Investigation checklist

- [ ] Confirm current behavior
"""
        try:
            note_path.write_text(content, encoding="utf-8")
            result = agent_callbacks._validate_openclaw_note(
                {"task": {"id": "t1-generic"}},
                "docs/agents/bug-investigations",
                "notion-bug",
            )
            assert result.get("success") is False
            summary = (result.get("summary") or "").lower()
            assert "actionable" in summary or "generic" in summary or "evidence" in summary
        finally:
            if note_path.exists():
                note_path.unlink(missing_ok=True)

    def test_concrete_root_cause_accepted(self):
        """Root Cause with file/function evidence is accepted."""
        from pathlib import Path
        from app.services._paths import get_writable_dir_for_subdir
        inv_dir = get_writable_dir_for_subdir("docs/agents/bug-investigations")
        inv_dir.mkdir(parents=True, exist_ok=True)
        note_path = inv_dir / "notion-bug-t1-concrete.md"
        content = """# Investigation

---

## Root Cause

The bug is in `backend/app/services/telegram_commands.py` in the `handle_task_command` function,
line 234: the condition `if not user_id` prevents the handler from running when user_id is 0.

## Affected modules

- `backend/app/services/telegram_commands.py`

## Relevant docs

- docs/architecture/system-map.md

## Investigation checklist

- [ ] Confirm current behavior
"""
        try:
            note_path.write_text(content, encoding="utf-8")
            result = agent_callbacks._validate_openclaw_note(
                {"task": {"id": "t1-concrete"}},
                "docs/agents/bug-investigations",
                "notion-bug",
            )
            assert result.get("success") is True
        finally:
            if note_path.exists():
                note_path.unlink(missing_ok=True)
