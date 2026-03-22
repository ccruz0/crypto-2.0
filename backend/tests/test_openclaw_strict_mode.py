"""
Tests for OpenClaw strict execution mode.

Validates:
1. execution_mode parsing (missing -> normal, Normal -> normal, Strict -> strict, unexpected -> normal)
2. Strict proof validation (shallow fails, proof-based passes)
3. No auto-advance when strict mode proof validation fails
4. Strict PATCH invariant: normal flow (invariant log + advance), failure flow (retry, logs, alert, stay in-progress)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# execution_mode parsing
# ---------------------------------------------------------------------------


class TestExecutionModeParsing:
    """Verify execution_mode normalizes correctly."""

    def test_missing_value_returns_normal(self):
        from app.services.notion_task_reader import _normalize_execution_mode

        assert _normalize_execution_mode("") == "normal"
        assert _normalize_execution_mode(None) == "normal"

    def test_normal_variants_return_normal(self):
        from app.services.notion_task_reader import _normalize_execution_mode

        assert _normalize_execution_mode("Normal") == "normal"
        assert _normalize_execution_mode("normal") == "normal"
        assert _normalize_execution_mode("  normal  ") == "normal"

    def test_strict_variants_return_strict(self):
        from app.services.notion_task_reader import _normalize_execution_mode

        assert _normalize_execution_mode("Strict") == "strict"
        assert _normalize_execution_mode("strict") == "strict"
        assert _normalize_execution_mode("  STRICT  ") == "strict"

    def test_unexpected_value_returns_normal(self):
        from app.services.notion_task_reader import _normalize_execution_mode

        assert _normalize_execution_mode("debug") == "normal"
        assert _normalize_execution_mode("invalid") == "normal"
        assert _normalize_execution_mode("strict-ish") == "normal"


def _notion_page_with_execution_mode(
    page_id: str,
    title: str,
    status: str,
    execution_mode: str | None = None,
) -> dict[str, Any]:
    """Minimal Notion page for _parse_page with optional Execution Mode."""
    props: dict[str, Any] = {
        "Task": {"title": [{"plain_text": title}]},
        "Status": {"rich_text": [{"plain_text": status}]},
        "Priority": {"rich_text": [{"plain_text": "medium"}]},
        "Project": {"rich_text": [{"plain_text": "Test"}]},
        "Type": {"rich_text": [{"plain_text": "bug"}]},
        "Details": {"rich_text": [{"plain_text": "test"}]},
    }
    if execution_mode is not None:
        props["Execution Mode"] = {"rich_text": [{"plain_text": execution_mode}]}
    return {"id": page_id, "properties": props}


class TestExecutionModeFromParsePage:
    """Verify _parse_page includes execution_mode in task dict."""

    def test_parse_page_missing_execution_mode_defaults_normal(self):
        from app.services.notion_task_reader import _parse_page

        with patch("app.services.notion_task_reader._normalize_status_from_notion", return_value="planned"):
            page = _notion_page_with_execution_mode("id-1", "Fix bug", "planned", execution_mode=None)
            # execution_mode=None means we don't add Execution Mode property
            task = _parse_page(page)
            assert task.get("execution_mode") == "normal"

    def test_parse_page_normal_execution_mode(self):
        from app.services.notion_task_reader import _parse_page

        with patch("app.services.notion_task_reader._normalize_status_from_notion", return_value="planned"):
            page = _notion_page_with_execution_mode("id-2", "Fix bug", "planned", execution_mode="Normal")
            task = _parse_page(page)
            assert task.get("execution_mode") == "normal"

    def test_parse_page_strict_execution_mode(self):
        from app.services.notion_task_reader import _parse_page

        with patch("app.services.notion_task_reader._normalize_status_from_notion", return_value="planned"):
            page = _notion_page_with_execution_mode("id-3", "Fix bug", "planned", execution_mode="Strict")
            task = _parse_page(page)
            assert task.get("execution_mode") == "strict"

    def test_parse_page_unexpected_execution_mode_defaults_normal(self):
        from app.services.notion_task_reader import _parse_page

        with patch("app.services.notion_task_reader._normalize_status_from_notion", return_value="planned"):
            page = _notion_page_with_execution_mode("id-4", "Fix bug", "planned", execution_mode="debug")
            task = _parse_page(page)
            assert task.get("execution_mode") == "normal"


# ---------------------------------------------------------------------------
# Strict proof validation
# ---------------------------------------------------------------------------


class TestStrictModeProofValidation:
    """Verify validate_strict_mode_proof rejects shallow output and accepts proof-based output."""

    def test_shallow_summary_fails(self):
        from app.services.openclaw_client import validate_strict_mode_proof

        shallow = (
            "The bug might be in the backend. We should investigate further. "
            "Consider checking the logs and adding more error handling."
        )
        ok, reason = validate_strict_mode_proof(shallow)
        assert ok is False
        assert "missing" in reason.lower() or "incomplete" in reason.lower()

    def test_proof_based_output_passes(self):
        from app.services.openclaw_client import validate_strict_mode_proof

        proof_based = """
## Root Cause
The bug is in backend/app/services/telegram_commands.py in the send_alert() function at line 142.
When the user triggers an alert with an empty payload, the condition `if not payload` fails to handle None.

```python
def send_alert(payload):
    if not payload:  # line 142 - fails when payload is None
        return
```

## Failing scenario
1. User sends alert via Telegram
2. Payload is None due to upstream bug
3. send_alert receives None, condition passes, function returns early
4. No alert is sent

## Recommended Fix
Add explicit None check: `if payload is None or not payload:`

## How to verify
Run the bot with an empty payload and confirm no alert is sent; then add the check and confirm alert is sent.
"""
        ok, reason = validate_strict_mode_proof(proof_based)
        assert ok is True, reason
        assert "satisfied" in reason.lower() or "ok" in reason.lower()

    def test_missing_file_path_fails(self):
        from app.services.openclaw_client import validate_strict_mode_proof

        no_file = (
            "Root cause: the function returns early. "
            "def foo(): return. When user clicks, scenario fails. "
            "Recommended fix: add check. " + "x" * 50
        )
        ok, reason = validate_strict_mode_proof(no_file)
        assert ok is False
        assert "file" in reason.lower()

    def test_missing_code_block_fails(self):
        from app.services.openclaw_client import validate_strict_mode_proof

        no_block = (
            "Root cause in backend/foo.py. def bar() at line 10. "
            "When user does X, scenario fails. Recommended fix: change bar. " + "x" * 50
        )
        ok, reason = validate_strict_mode_proof(no_block)
        assert ok is False
        assert "snippet" in reason.lower() or "code" in reason.lower()

    def test_content_too_short_fails(self):
        from app.services.openclaw_client import validate_strict_mode_proof

        ok, reason = validate_strict_mode_proof("Short.")
        assert ok is False
        assert "short" in reason.lower()

    def test_shallow_investigation_without_code_fails(self):
        """Shallow output with generic phrases and no concrete code refs must fail."""
        from app.services.openclaw_client import validate_strict_mode_proof

        shallow = (
            "HARD RESET: purchase_price investigation. "
            "The issue might be in the backend. We should investigate further and consider checking the logs. "
            "Root cause could be sync related. Recommended fix: improve error handling. " + "x" * 80
        )
        ok, reason = validate_strict_mode_proof(shallow)
        assert ok is False, reason
        assert "missing" in reason.lower() or "incomplete" in reason.lower()

    def test_root_cause_might_could_fails(self):
        """Root cause stated as 'might' or 'could' without definitive code ref fails."""
        from app.services.openclaw_client import validate_strict_mode_proof

        hedged = (
            "Root cause might be in backend/app/foo.py. def bar() at line 10. "
            "When user does X, scenario fails. Recommended fix: add check. "
            "How to verify: run test. "
            "```python\nx = 1\n```" + "x" * 50
        )
        ok, reason = validate_strict_mode_proof(hedged)
        assert ok is False, reason
        assert "might" in reason.lower() or "could" in reason.lower() or "definitively" in reason.lower()

    def test_missing_validation_section_fails(self):
        """Output without explicit validation/verify section fails."""
        from app.services.openclaw_client import validate_strict_mode_proof

        no_validation = """
## Root Cause
Bug in backend/app/services/foo.py in do_thing() at line 20. Caused by null pointer.

```python
def do_thing(x):
    return x.value
```

## Failing scenario
When user passes None, do_thing fails.

## Recommended Fix
Add check: if x is None return.
"""
        ok, reason = validate_strict_mode_proof(no_validation)
        assert ok is False, reason
        assert "validat" in reason.lower() or "verify" in reason.lower() or "test" in reason.lower()

    def test_code_block_without_code_like_content_fails(self):
        """Code block that is just plain text or markdown fails."""
        from app.services.openclaw_client import validate_strict_mode_proof

        fake_block = (
            "Root cause in backend/app/bar.py. def baz() at line 5. "
            "Failing scenario: when user clicks. Recommended fix: add handling. "
            "How to verify: run and confirm. "
            "```\njust some text no code\n```" + "x" * 50
        )
        ok, reason = validate_strict_mode_proof(fake_block)
        assert ok is False, reason
        assert "code" in reason.lower() or "snippet" in reason.lower()

    def test_bare_filename_without_path_fails(self):
        """Bare 'something.py' without path (e.g. backend/.../file.py) fails."""
        from app.services.openclaw_client import validate_strict_mode_proof

        bare = (
            "Root cause in telegram_commands.py. def send_alert() at line 142. "
            "Failing scenario: when user sends. Recommended fix: add check. How to verify: test. "
            "```python\ndef send_alert(): pass\n```" + "x" * 50
        )
        ok, reason = validate_strict_mode_proof(bare)
        assert ok is False, reason
        assert "file" in reason.lower()


# ---------------------------------------------------------------------------
# No auto-advance when proof fails
# ---------------------------------------------------------------------------


class TestStrictModeNoAutoAdvance:
    """Verify execute_prepared_notion_task does not auto-advance when strict mode proof fails."""

    def test_strict_mode_proof_fail_stays_in_progress(self):
        """When execution_mode=strict and proof validation fails, task stays in-progress."""
        from app.services.agent_task_executor import execute_prepared_notion_task

        prepared_task = {
            "task": {
                "id": "test-task-123",
                "task": "Fix bug",
                "execution_mode": "strict",
            },
            "repo_area": {},
            "claim": {"status_updated": True},
            "_use_extended_lifecycle": True,
            "_openclaw_sections": {},
        }

        def mock_apply(_pt):
            return {"success": True, "summary": "ok"}

        with (
            patch("app.services.agent_recovery.artifact_exists_for_task", return_value=True),
            patch(
                "app.services.agent_recovery.artifact_and_sidecar_exist_for_task",
                return_value=(True, "ok"),
            ),
            patch(
                "app.services.agent_recovery.get_artifact_content_for_task",
                return_value="Shallow summary without proof. " + "x" * 100,
            ),
            patch(
                "app.services.openclaw_client.validate_strict_mode_proof",
                return_value=(False, "strict mode proof incomplete: missing exact file reference"),
            ),
            patch("app.services.agent_task_executor.update_notion_task_status") as mock_status,
            patch("app.services.agent_task_executor._append_notion_page_comment") as mock_comment,
            patch("app.services.agent_task_executor._enrich_metadata_from_openclaw"),
            patch("app.services.agent_task_executor._generate_cursor_handoff"),
        ):
            result = execute_prepared_notion_task(
                prepared_task,
                apply_change_fn=mock_apply,
                validate_fn=None,
                deploy_fn=None,
            )

        assert result.get("final_status") == "in-progress"
        status_calls = [c for c in mock_status.call_args_list if len(c[0]) >= 2 and c[0][1] == "ready-for-patch"]
        assert len(status_calls) == 0, "Should not advance to ready-for-patch when proof fails"
        assert mock_comment.called
        comment_text = "".join(str(c) for c in mock_comment.call_args_list)
        assert "Strict" in comment_text or "proof" in comment_text.lower()


# ---------------------------------------------------------------------------
# Handoff: strict investigation passes -> patch task created
# ---------------------------------------------------------------------------


class TestStrictModeHandoffPatchTask:
    """When strict investigation passes, a Cursor-ready patch task is created. When it fails, none is created."""

    def test_strict_investigation_passes_patch_task_created(self):
        """Strict proof passes -> create_patch_task_from_investigation is called with correct args."""
        from app.services.agent_task_executor import execute_prepared_notion_task

        prepared_task = {
            "task": {
                "id": "inv-task-456",
                "task": "HARD RESET: purchase_price investigation",
                "execution_mode": "strict",
            },
            "repo_area": {"likely_files": ["backend/app/services/foo.py"]},
            "claim": {"status_updated": True},
            "_use_extended_lifecycle": True,
            "_openclaw_sections": {
                "Root Cause": "Sync issue in get_purchase_price.",
                "Recommended Fix": "Add fallback to exchange API.",
            },
        }

        artifact_body = (
            "## Root Cause\nIn backend/app/services/bar.py get_price() at line 10.\n\n"
            "```python\ndef get_price(): return 0\n```\n\n"
            "Failing scenario: when order is new. Recommended fix: add check. How to verify: run test."
        )

        with (
            patch("app.services.agent_recovery.artifact_exists_for_task", return_value=True),
            patch(
                "app.services.agent_recovery.artifact_and_sidecar_exist_for_task",
                return_value=(True, "ok"),
            ),
            patch(
                "app.services.agent_recovery.get_artifact_content_for_task",
                return_value=artifact_body,
            ),
            patch(
                "app.services.openclaw_client.validate_strict_mode_proof",
                return_value=(True, "proof criteria satisfied"),
            ),
            patch(
                "app.services.notion_tasks.create_patch_task_from_investigation",
            ) as mock_create_patch,
            patch("app.services.agent_task_executor.update_notion_task_status") as mock_status,
            patch("app.services.agent_task_executor._append_notion_page_comment"),
            patch("app.services.agent_task_executor._enrich_metadata_from_openclaw"),
            patch("app.services.agent_telegram_approval.send_investigation_complete_info"),
        ):
            mock_create_patch.return_value = {"id": "patch-789"}

            def mock_apply(_pt):
                return {"success": True, "summary": "ok"}

            result = execute_prepared_notion_task(
                prepared_task,
                apply_change_fn=mock_apply,
                validate_fn=None,
                deploy_fn=None,
            )

            assert result.get("final_status") == "ready-for-patch"
            mock_create_patch.assert_called_once()
            call_kw = mock_create_patch.call_args[1]
            assert call_kw["investigation_task_id"] == "inv-task-456"
            assert "purchase_price" in call_kw["investigation_title"] or "HARD RESET" in call_kw["investigation_title"]
            assert call_kw["artifact_body"] == artifact_body
            assert call_kw["sections"]["Root Cause"] == "Sync issue in get_purchase_price."

    def test_strict_normal_flow_invariant_log_and_advance(self):
        """Normal strict flow: proof passes, patch creation succeeds, strict_patch_invariant_enforced log, task advances."""
        from app.services.agent_task_executor import execute_prepared_notion_task
        import logging

        prepared_task = {
            "task": {
                "id": "inv-task-456",
                "task": "Investigation",
                "execution_mode": "strict",
            },
            "repo_area": {},
            "claim": {"status_updated": True},
            "_use_extended_lifecycle": True,
            "_openclaw_sections": {},
        }
        artifact_body = (
            "## Root Cause\nIn backend/app/foo.py.\n\n```python\ndef x(): pass\n```\n"
            "Failing scenario: when X. Recommended fix: add check. How to verify: run test."
        )

        with (
            patch("app.services.agent_recovery.artifact_exists_for_task", return_value=True),
            patch(
                "app.services.agent_recovery.artifact_and_sidecar_exist_for_task",
                return_value=(True, "ok"),
            ),
            patch(
                "app.services.agent_recovery.get_artifact_content_for_task",
                return_value=artifact_body,
            ),
            patch(
                "app.services.openclaw_client.validate_strict_mode_proof",
                return_value=(True, "ok"),
            ),
            patch(
                "app.services.notion_tasks.create_patch_task_from_investigation",
                return_value={"id": "patch-789"},
            ),
            patch("app.services.agent_task_executor.update_notion_task_status"),
            patch("app.services.agent_task_executor._append_notion_page_comment"),
            patch("app.services.agent_task_executor._enrich_metadata_from_openclaw"),
            patch("app.services.agent_telegram_approval.send_investigation_complete_info"),
        ):
            with patch.object(
                logging.getLogger("app.services.agent_task_executor"),
                "info",
                wraps=logging.getLogger("app.services.agent_task_executor").info,
            ) as mock_info:
                result = execute_prepared_notion_task(
                    prepared_task,
                    apply_change_fn=lambda _: {"success": True, "summary": "ok"},
                    validate_fn=None,
                    deploy_fn=None,
                )
                info_calls = [str(c) for c in mock_info.call_args_list]
                assert any("strict_patch_invariant_enforced" in c for c in info_calls), (
                    "Expected log strict_patch_invariant_enforced in " + str(info_calls)
                )
            assert result.get("final_status") == "ready-for-patch"

    def test_strict_patch_creation_failure_retry_then_block_and_alert(self):
        """Failure strict flow: create_patch fails (both attempts), retry once, then set_last_pickup_status, comment, stay in-progress, no advance."""
        from app.services.agent_task_executor import execute_prepared_notion_task

        prepared_task = {
            "task": {
                "id": "inv-task-fail",
                "task": "Investigation",
                "execution_mode": "strict",
            },
            "repo_area": {},
            "claim": {"status_updated": True},
            "_use_extended_lifecycle": True,
            "_openclaw_sections": {},
        }
        artifact_body = (
            "## Root Cause\nIn backend/app/foo.py.\n\n```python\ndef x(): pass\n```\n"
            "Failing scenario: when X. Recommended fix: add check. How to verify: run test."
        )

        with (
            patch("app.services.agent_recovery.artifact_exists_for_task", return_value=True),
            patch(
                "app.services.agent_recovery.artifact_and_sidecar_exist_for_task",
                return_value=(True, "ok"),
            ),
            patch(
                "app.services.agent_recovery.get_artifact_content_for_task",
                return_value=artifact_body,
            ),
            patch(
                "app.services.openclaw_client.validate_strict_mode_proof",
                return_value=(True, "ok"),
            ),
            patch(
                "app.services.notion_tasks.create_patch_task_from_investigation",
                return_value=None,
            ),
            patch("app.services.agent_task_executor.update_notion_task_status") as mock_status,
            patch("app.services.agent_task_executor._append_notion_page_comment") as mock_comment,
            patch("app.services.agent_task_executor._enrich_metadata_from_openclaw"),
            patch("app.services.notion_env.set_last_pickup_status") as mock_set_status,
            patch(
                "app.services.agent_telegram_approval.send_blocker_notification",
                return_value={"sent": True},
            ) as mock_blocker,
        ):
            result = execute_prepared_notion_task(
                prepared_task,
                apply_change_fn=lambda _: {"success": True, "summary": "ok"},
                validate_fn=None,
                deploy_fn=None,
            )

        assert result.get("final_status") == "in-progress"
        mock_set_status.assert_called_once()
        args = mock_set_status.call_args[0]
        assert args[0] == "patch_creation_failed"
        assert len(args) >= 2 and (args[1] is None or "None" in str(args[1]) or "create_patch" in str(args[1]))

        mock_comment.assert_called()
        comment_calls = " ".join(str(c) for c in mock_comment.call_args_list)
        assert "PATCH" in comment_calls and ("failed" in comment_calls or "in-progress" in comment_calls)

        advance_to_inv_complete = [c for c in mock_status.call_args_list if len(c[0]) >= 2 and c[0][1] == "investigation-complete"]
        advance_to_ready = [c for c in mock_status.call_args_list if len(c[0]) >= 2 and c[0][1] == "ready-for-patch"]
        assert len(advance_to_inv_complete) == 0, "Must not advance to investigation-complete when PATCH creation failed"
        assert len(advance_to_ready) == 0, "Must not advance to ready-for-patch when PATCH creation failed"

        mock_blocker.assert_called_once()
        _reason = (mock_blocker.call_args.kwargs or {}).get("reason", "")
        assert "create_patch" in str(_reason) or "None" in str(_reason)

    def test_strict_patch_creation_failure_logs_and_telegram(self):
        """Failure flow: strict_patch_creation_failed and strict_patch_invariant_enforced block_advance=patch_creation_failed in logs; Telegram sent."""
        from app.services.agent_task_executor import execute_prepared_notion_task
        import logging

        prepared_task = {
            "task": {"id": "inv-123", "task": "T", "execution_mode": "strict"},
            "repo_area": {},
            "claim": {"status_updated": True},
            "_use_extended_lifecycle": True,
            "_openclaw_sections": {},
        }
        artifact_body = "## Root Cause\nIn backend/app/foo.py.\n\n```python\ndef x(): pass\n```\nFailing: X. Fix: check. Verify: test."

        with (
            patch("app.services.agent_recovery.artifact_exists_for_task", return_value=True),
            patch(
                "app.services.agent_recovery.artifact_and_sidecar_exist_for_task",
                return_value=(True, "ok"),
            ),
            patch("app.services.agent_recovery.get_artifact_content_for_task", return_value=artifact_body),
            patch("app.services.openclaw_client.validate_strict_mode_proof", return_value=(True, "ok")),
            patch("app.services.notion_tasks.create_patch_task_from_investigation", return_value=None),
            patch("app.services.agent_task_executor.update_notion_task_status"),
            patch("app.services.agent_task_executor._append_notion_page_comment"),
            patch("app.services.agent_task_executor._enrich_metadata_from_openclaw"),
            patch("app.services.notion_env.set_last_pickup_status"),
            patch(
                "app.services.agent_telegram_approval.send_blocker_notification",
                return_value={"sent": True},
            ) as mock_blocker,
        ):
            logger = logging.getLogger("app.services.agent_task_executor")
            with patch.object(logger, "warning") as mock_warn, patch.object(logger, "info") as mock_info:
                result = execute_prepared_notion_task(
                    prepared_task,
                    apply_change_fn=lambda _: {"success": True, "summary": "ok"},
                    validate_fn=None,
                    deploy_fn=None,
                )
                warn_calls = [str(c) for c in mock_warn.call_args_list]
                info_calls = [str(c) for c in mock_info.call_args_list]
                assert any("strict_patch_creation_failed" in c for c in warn_calls), (
                    "Expected strict_patch_creation_failed log: " + str(warn_calls)
                )
                assert any(
                    "strict_patch_invariant_enforced" in c and "block_advance=patch_creation_failed" in c
                    for c in info_calls
                ), "Expected strict_patch_invariant_enforced block_advance=patch_creation_failed: " + str(info_calls)

        assert result.get("final_status") == "in-progress"
        mock_blocker.assert_called_once()
        assert "create_patch" in str(mock_blocker.call_args) or "None" in str(mock_blocker.call_args)

    def test_strict_investigation_fails_no_patch_task(self):
        """Strict proof fails -> create_patch_task_from_investigation is not called."""
        from app.services.agent_task_executor import execute_prepared_notion_task

        prepared_task = {
            "task": {"id": "inv-task-999", "task": "Fix bug", "execution_mode": "strict"},
            "repo_area": {},
            "claim": {"status_updated": True},
            "_use_extended_lifecycle": True,
            "_openclaw_sections": {},
        }

        with (
            patch("app.services.agent_recovery.artifact_exists_for_task", return_value=True),
            patch(
                "app.services.agent_recovery.artifact_and_sidecar_exist_for_task",
                return_value=(True, "ok"),
            ),
            patch(
                "app.services.agent_recovery.get_artifact_content_for_task",
                return_value="Shallow output. " + "x" * 100,
            ),
            patch(
                "app.services.openclaw_client.validate_strict_mode_proof",
                return_value=(False, "strict mode proof incomplete: missing exact file reference"),
            ),
            patch(
                "app.services.notion_tasks.create_patch_task_from_investigation",
            ) as mock_create_patch,
            patch("app.services.agent_task_executor.update_notion_task_status"),
            patch("app.services.agent_task_executor._append_notion_page_comment"),
        ):
            result = execute_prepared_notion_task(
                prepared_task,
                apply_change_fn=lambda _: {"success": True, "summary": "ok"},
                validate_fn=None,
                deploy_fn=None,
            )

            assert result.get("final_status") == "in-progress"
            mock_create_patch.assert_not_called()

    def test_patch_task_contains_required_fields(self):
        """create_patch_task_from_investigation builds task with PATCH: title, Type=Patch, Source=OpenClaw, and details with prompt."""
        from app.services.notion_tasks import create_patch_task_from_investigation, create_notion_task

        with patch("app.services.notion_tasks.create_notion_task") as mock_create:
            mock_create.return_value = {"id": "new-page-id"}

            result = create_patch_task_from_investigation(
                investigation_task_id="orig-123",
                investigation_title="purchase_price investigation",
                artifact_body="## Root Cause\nBug in foo.py.\n\n## How to verify\nRun tests.",
                sections={
                    "Root Cause": "Sync issue.",
                    "Recommended Fix": "Add fallback.",
                    "Files Affected": "backend/app/foo.py",
                },
                task={"project": "Backend"},
                repo_area={},
            )

            assert result == {"id": "new-page-id"}
            mock_create.assert_called_once()
            call_kw = mock_create.call_args[1]
            assert call_kw["title"] == "PATCH: purchase_price investigation"
            assert call_kw["type"] == "Patch"
            assert call_kw["status"] == "planned"
            assert call_kw["source"] == "OpenClaw"
            details = call_kw["details"]
            assert "Original investigation task ID: orig-123" in details
            assert "Root cause" in details or "Sync issue" in details
            assert "Cursor-ready implementation prompt" in details
            assert "Validation steps" in details
            assert "backend/app/foo.py" in details or "Sync issue" in details


# ---------------------------------------------------------------------------
# Patch task pickup: PATCH tasks with Status=Planned are eligible for execution
# ---------------------------------------------------------------------------


class TestPatchTaskPickupEligibility:
    """PATCH tasks created by handoff (Type=Patch, Status=Planned) must be pickable by Cursor flow."""

    def test_create_notion_task_planned_sends_select_status(self):
        """create_notion_task with status=planned sends Status as Select 'Planned' so reader finds it."""
        from app.services.notion_tasks import create_notion_task

        with (
            patch("app.services.notion_tasks._get_config", return_value=("test-key", "test-db-id")),
            patch("app.services.notion_tasks._dedup_prune_and_check", return_value=False),
            patch("app.services.notion_tasks._dedup_record"),
            patch("app.services.notion_tasks.httpx") as mock_httpx,
        ):
            mock_client = mock_httpx.Client.return_value.__enter__.return_value
            mock_client.post.return_value.status_code = 200
            mock_client.post.return_value.json.return_value = {"id": "new-id"}

            create_notion_task(
                title="PATCH: test",
                project="Operations",
                type="Patch",
                details="Details",
                status="planned",
                source="OpenClaw",
            )

            mock_client.post.assert_called_once()
            call_args = mock_client.post.call_args
            body = call_args[1]["json"]
            status_prop = body.get("properties", {}).get("Status", {})
            assert "select" in status_prop
            assert status_prop["select"].get("name") == "Planned"

    def test_patch_task_eligible_when_in_pickable_list(self):
        """When get_high_priority_pending_tasks returns a Patch task (planned), prepare_next_notion_task selects it."""
        from app.services.agent_task_executor import prepare_next_notion_task

        patch_task = {
            "id": "patch-page-123",
            "task": "PATCH: purchase_price fix",
            "type": "Patch",
            "status": "planned",
            "project": "Operations",
            "priority": "medium",
            "source": "OpenClaw",
            "details": "Original investigation task ID: inv-456",
        }

        with (
            patch(
                "app.services.agent_task_executor.get_high_priority_pending_tasks",
                return_value=[patch_task],
            ),
            patch("app.services.agent_task_executor.update_notion_task_status", return_value=True),
            patch("app.services.agent_task_executor._append_notion_page_comment", return_value=True),
            patch("app.services.agent_task_executor.infer_repo_area_for_task", return_value={"area_name": "backend", "matched_rules": []}),
        ):
            result = prepare_next_notion_task(project=None, type_filter=None)

        assert result is not None
        assert result["task"]["id"] == "patch-page-123"
        assert result["task"]["type"] == "Patch"
        assert result["task"]["status"] == "planned"
        assert result["task"]["task"] == "PATCH: purchase_price fix"

    def test_wrong_status_not_pickable(self):
        """Done and other terminal statuses are not in pickable options, so such tasks are not queried."""
        from app.services.notion_task_reader import (
            NOTION_PICKABLE_STATUS_OPTIONS,
            INTERNAL_PICKABLE_STATUSES,
        )

        assert "Done" not in NOTION_PICKABLE_STATUS_OPTIONS
        assert "done" not in INTERNAL_PICKABLE_STATUSES
        assert "Planned" in NOTION_PICKABLE_STATUS_OPTIONS
        assert "planned" in INTERNAL_PICKABLE_STATUSES
