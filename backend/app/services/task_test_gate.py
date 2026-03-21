"""
Test gate for task lifecycle progression.

Records test execution results and conditionally advances tasks through
the extended lifecycle based on outcome:

    patching / testing  →  release-candidate-ready  (if passed)
    patching / testing  →  stays in place            (if failed / partial / not-run)

Persists the test outcome to the Notion ``Test Status`` metadata field
and appends a comment to the task page for auditability.

This module is intentionally decoupled from the executor so that test
results can arrive from any source: the built-in validate_fn callback,
a CI webhook, a Cursor patch runner, or a manual Telegram action.

No network calls beyond Notion.  No side effects on trading, exchange,
or deployment systems.  Safe to call from any context.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Test outcome constants
# ---------------------------------------------------------------------------

TEST_PASSED = "passed"
TEST_FAILED = "failed"
TEST_PARTIAL = "partial"
TEST_NOT_RUN = "not-run"

VALID_TEST_OUTCOMES = (TEST_PASSED, TEST_FAILED, TEST_PARTIAL, TEST_NOT_RUN)

# Statuses from which a passing test can advance the task
_ADVANCEABLE_STATUSES = ("testing", "patching")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------


def record_test_result(
    task_id: str,
    outcome: str,
    *,
    summary: str = "",
    details: dict[str, Any] | None = None,
    advance_on_pass: bool = True,
    current_status: str = "",
) -> dict[str, Any]:
    """Record a test result for a task and optionally advance its lifecycle.

    Parameters
    ----------
    task_id:
        Notion page ID of the task.
    outcome:
        One of ``passed``, ``failed``, ``partial``, ``not-run``.
    summary:
        Short human-readable description of the test result (e.g. "3/3 passed").
    details:
        Optional structured details (stored in activity log, not Notion).
    advance_on_pass:
        When True and outcome is ``passed``, advance the task from
        ``testing`` / ``patching`` to ``release-candidate-ready``.
        Set to False if you only want to record the result without
        moving the task (useful for legacy lifecycle callers).
    current_status:
        Hint for the task's current Notion status.  If empty, the
        function still writes metadata but will only advance if
        ``advance_on_pass`` is True (it does not re-read status from
        Notion to keep this module simple and side-effect-free).

    Returns
    -------
    dict with keys:
        ok (bool): True if at least the metadata write succeeded.
        outcome (str): The normalized outcome value.
        advanced (bool): Whether the task status was moved forward.
        advanced_to (str): Target status if advanced, else "".
        metadata_result (dict): Result from update_notion_task_metadata.
        comment_appended (bool): Whether a Notion page comment was added.
    """
    task_id = (task_id or "").strip()
    normalized = (outcome or "").strip().lower()

    if normalized not in VALID_TEST_OUTCOMES:
        logger.warning(
            "record_test_result: invalid outcome=%r task_id=%s (expected one of %s)",
            outcome, task_id, VALID_TEST_OUTCOMES,
        )
        return {
            "ok": False,
            "outcome": normalized,
            "advanced": False,
            "advanced_to": "",
            "metadata_result": {},
            "comment_appended": False,
            "error": f"invalid outcome: {outcome}",
        }

    if not task_id:
        logger.warning("record_test_result: empty task_id")
        return {
            "ok": False,
            "outcome": normalized,
            "advanced": False,
            "advanced_to": "",
            "metadata_result": {},
            "comment_appended": False,
            "error": "empty task_id",
        }

    summary_text = (summary or "").strip() or normalized
    timestamp = _utc_now_iso()

    # --- 1. Write test_status to Notion metadata ---
    metadata_result: dict[str, Any] = {}
    try:
        from app.services.notion_tasks import update_notion_task_metadata
        metadata_result = update_notion_task_metadata(
            task_id,
            {"test_status": f"{normalized}: {summary_text}"[:200]},
            append_comment=f"[{timestamp}] Test result: {normalized} — {summary_text[:300]}",
        )
        logger.info(
            "record_test_result: metadata written task_id=%s outcome=%s updated=%s",
            task_id, normalized, metadata_result.get("updated_fields"),
        )
    except Exception as e:
        logger.warning("record_test_result: metadata write failed task_id=%s: %s", task_id, e)
        metadata_result = {"ok": False, "reason": str(e)}

    # --- 2. Advance status if passed ---
    advanced = False
    advanced_to = ""
    metadata_ok = bool(metadata_result.get("ok"))

    if normalized == TEST_PASSED and advance_on_pass:
        if not metadata_ok:
            logger.warning(
                "record_test_result: BLOCKING advancement — metadata write for Test Status "
                "did not succeed task_id=%s metadata_result=%s",
                task_id, metadata_result,
            )
        else:
            norm_current = (current_status or "").strip().lower()
            should_advance = norm_current in _ADVANCEABLE_STATUSES or not norm_current
            if should_advance:
                try:
                    from app.services.notion_tasks import (
                        TASK_STATUS_RELEASE_CANDIDATE_READY,
                        update_notion_task_status,
                    )
                    target = TASK_STATUS_RELEASE_CANDIDATE_READY
                    ok = update_notion_task_status(
                        task_id,
                        target,
                        append_comment=f"[{timestamp}] Tests passed — task advanced to {target}.",
                    )
                    if ok:
                        advanced = True
                        advanced_to = target
                        logger.info(
                            "record_test_result: advanced task_id=%s to=%s "
                            "(Test Status metadata confirmed written)",
                            task_id, target,
                        )
                    else:
                        logger.warning(
                            "record_test_result: status advance failed task_id=%s target=%s",
                            task_id, target,
                        )
                except Exception as e:
                    logger.warning("record_test_result: advance failed task_id=%s: %s", task_id, e)
            else:
                logger.info(
                    "record_test_result: not advancing task_id=%s current_status=%r (not in advanceable set)",
                    task_id, norm_current,
                )

    if normalized == TEST_FAILED:
        logger.info(
            "record_test_result: tests failed — task stays in current status task_id=%s",
            task_id,
        )

    if normalized == TEST_PARTIAL:
        logger.info(
            "record_test_result: tests partial — task stays in current status for review task_id=%s",
            task_id,
        )

    if normalized == TEST_NOT_RUN:
        logger.info(
            "record_test_result: tests not run — task stays in current status task_id=%s",
            task_id,
        )

    # --- 3. Activity log ---
    try:
        from app.services.agent_activity_log import log_agent_event
        log_agent_event(
            "test_result_recorded",
            task_id=task_id,
            details={
                "outcome": normalized,
                "summary": summary_text[:300],
                "advanced": advanced,
                "advanced_to": advanced_to,
                **(details or {}),
            },
        )
    except Exception:
        pass

    return {
        "ok": metadata_ok,
        "outcome": normalized,
        "advanced": advanced,
        "advanced_to": advanced_to,
        "metadata_ok": metadata_ok,
        "metadata_result": metadata_result,
        "comment_appended": True,
    }


# ---------------------------------------------------------------------------
# Convenience: derive outcome from executor validation result
# ---------------------------------------------------------------------------


def test_outcome_from_validation(
    validation_attempted: bool,
    validation_success: bool,
    validation_summary: str = "",
) -> tuple[str, str]:
    """Map the executor's validation result to a test outcome + summary.

    Returns (outcome, summary) suitable for ``record_test_result``.
    """
    if not validation_attempted:
        return TEST_NOT_RUN, "validation callback not supplied"
    if validation_success:
        return TEST_PASSED, validation_summary or "validation passed"
    return TEST_FAILED, validation_summary or "validation failed"
