"""Unit tests for scripts/github_auto_merge.py (no network, no gh)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parent / "github_auto_merge.py"
SPEC = importlib.util.spec_from_file_location("github_auto_merge", MODULE_PATH)
assert SPEC and SPEC.loader
auto_merge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(auto_merge)


def _thread(*logins: str, resolved: bool = False) -> dict:
    return {
        "id": "thread-1",
        "isResolved": resolved,
        "comments": {"nodes": [{"author": {"login": login}} for login in logins]},
    }


def test_bot_only_thread_from_bugbot() -> None:
    assert auto_merge.is_bot_only_thread(_thread("cursor", "cursor[bot]")) is True


def test_human_thread_is_not_bot_only() -> None:
    assert auto_merge.is_bot_only_thread(_thread("cursor", "ccruz0")) is False


def test_empty_thread_is_not_bot_only() -> None:
    assert auto_merge.is_bot_only_thread(_thread()) is False


def test_immediate_merge_statuses() -> None:
    assert auto_merge.can_immediate_merge("CLEAN") is True
    assert auto_merge.can_immediate_merge("UNSTABLE") is True
    assert auto_merge.can_immediate_merge("BLOCKED") is False
    assert auto_merge.can_immediate_merge("DRAFT") is False
    assert auto_merge.can_immediate_merge("DIRTY") is False


def test_skip_merged_or_closed() -> None:
    assert auto_merge.should_skip_pr("OPEN", True) is True
    assert auto_merge.should_skip_pr("MERGED", False) is True
    assert auto_merge.should_skip_pr("OPEN", False) is False


def test_do_not_resolve_threads_until_bugbot_approves() -> None:
    assert auto_merge.should_resolve_bot_threads("CHANGES_REQUESTED") is False
    assert auto_merge.should_resolve_bot_threads("APPROVED") is True
    assert auto_merge.should_resolve_bot_threads(None) is False
    assert auto_merge.should_resolve_bot_threads("") is False


def test_parse_repo() -> None:
    assert auto_merge.parse_repo("ccruz0/crypto-2.0") == ("ccruz0", "crypto-2.0")
    with pytest.raises(ValueError):
        auto_merge.parse_repo("invalid")


def test_auto_merge_enable_ok_treats_blocked_as_retryable() -> None:
    assert auto_merge.auto_merge_enable_ok(0, "") is True
    assert auto_merge.auto_merge_enable_ok(1, "already enabled") is True
    assert (
        auto_merge.auto_merge_enable_ok(
            1, "X Pull request is not mergeable: the base branch policy prohibits the merge."
        )
        is True
    )
    assert auto_merge.auto_merge_enable_ok(1, "HTTP 403 Resource not accessible") is False


def test_path_guard_passed() -> None:
    assert auto_merge.path_guard_passed([]) is False
    assert (
        auto_merge.path_guard_passed(
            [{"name": "path-guard", "status": "COMPLETED", "conclusion": "SUCCESS", "completedAt": "2026-08-14T01:00:00Z"}]
        )
        is True
    )
    assert (
        auto_merge.path_guard_passed(
            [{"name": "path-guard", "status": "IN_PROGRESS", "conclusion": ""}]
        )
        is False
    )


def test_path_guard_uses_latest_completed_not_older_failures() -> None:
    rollup = [
        {
            "name": "path-guard",
            "status": "COMPLETED",
            "conclusion": "FAILURE",
            "completedAt": "2026-08-14T01:00:00Z",
        },
        {
            "name": "path-guard",
            "status": "COMPLETED",
            "conclusion": "SUCCESS",
            "completedAt": "2026-08-14T02:00:00Z",
        },
        {
            "name": "path-guard",
            "status": "IN_PROGRESS",
            "conclusion": "",
            "completedAt": "0001-01-01T00:00:00Z",
        },
    ]
    assert auto_merge.path_guard_passed(rollup) is True


def test_ruleset_update_block_detection() -> None:
    assert auto_merge.is_ruleset_update_block("Cannot update this protected ref.") is True
    assert auto_merge.is_ruleset_update_block("Repository rule violations found") is False
    assert (
        auto_merge.is_ruleset_update_block(
            "A conversation must be resolved before this pull request can be merged."
        )
        is False
    )
    assert auto_merge.is_unresolved_conversation_block(
        "A conversation must be resolved before this pull request can be merged."
    )
    assert auto_merge.is_ruleset_update_block("SHA did not match") is False


def test_force_resolve_bot_threads() -> None:
    assert auto_merge.should_resolve_bot_threads(None, force=True) is True
    assert auto_merge.should_resolve_bot_threads(None, force=False) is False


def test_should_attempt_squash_when_blocked_but_path_guard_green() -> None:
    assert (
        auto_merge.should_attempt_squash(
            is_draft=False,
            merge_state_status="BLOCKED",
            review_decision=None,
            path_guard_ok=True,
            human_threads=False,
        )
        is True
    )
    assert (
        auto_merge.should_attempt_squash(
            is_draft=False,
            merge_state_status="BLOCKED",
            review_decision=None,
            path_guard_ok=False,
            human_threads=False,
        )
        is False
    )
    assert (
        auto_merge.should_attempt_squash(
            is_draft=False,
            merge_state_status="BLOCKED",
            review_decision=None,
            path_guard_ok=True,
            human_threads=True,
        )
        is False
    )


# --- issue #498: never merge a commit whose checks are still in flight -------


def _check(name: str, status: str = "COMPLETED", conclusion: str | None = "SUCCESS",
           completed: str = "2026-08-17T14:43:20Z") -> dict:
    return {
        "__typename": "CheckRun",
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "completedAt": completed,
    }


def _pr499_rollup() -> list[dict]:
    """The real rollup of PR #499 at the moment it squashed itself."""
    return [
        _check("path-guard"),
        _check("trivy", status="IN_PROGRESS", conclusion=None, completed=""),
        _check("Egress Security Audit"),
        _check("Jarvis/Planner surface tests (curated subset — NOT the full backend suite)"),
        _check("check-no-inline-secrets"),
        _check("enable-auto-merge", status="IN_PROGRESS", conclusion=None, completed=""),
    ]


def test_pending_checks_block_the_squash() -> None:
    rollup = _pr499_rollup()
    assert auto_merge.pending_check_names(rollup) == ["trivy"]
    assert auto_merge.failing_check_names(rollup) == []
    assert (
        auto_merge.should_attempt_squash(
            is_draft=False,
            merge_state_status="BLOCKED",
            review_decision=None,
            path_guard_ok=True,
            human_threads=False,
            pending_checks=auto_merge.pending_check_names(rollup),
            failed_checks=auto_merge.failing_check_names(rollup),
        )
        is False
    ), "PR #499 merged in 18s with trivy pending; that must not happen again"


def test_own_check_never_counts_as_pending() -> None:
    """The script runs inside enable-auto-merge, so its own run is always live."""
    rollup = [_check("enable-auto-merge", status="IN_PROGRESS", conclusion=None, completed="")]
    assert auto_merge.pending_check_names(rollup) == []


def test_unstable_status_no_longer_merges_with_pending_checks() -> None:
    """UNSTABLE is GitHub's state for 'mergeable but checks red or running'."""
    rollup = _pr499_rollup()
    assert (
        auto_merge.should_attempt_squash(
            is_draft=False,
            merge_state_status="UNSTABLE",
            review_decision=None,
            path_guard_ok=True,
            human_threads=False,
            pending_checks=auto_merge.pending_check_names(rollup),
            failed_checks=auto_merge.failing_check_names(rollup),
        )
        is False
    )


def test_failing_check_blocks_the_squash() -> None:
    rollup = [_check("path-guard"), _check("trivy", conclusion="FAILURE")]
    assert auto_merge.failing_check_names(rollup) == ["trivy"]
    assert (
        auto_merge.should_attempt_squash(
            is_draft=False,
            merge_state_status="CLEAN",
            review_decision=None,
            path_guard_ok=True,
            human_threads=False,
            pending_checks=[],
            failed_checks=["trivy"],
        )
        is False
    )


def test_neutral_and_skipped_are_not_failures() -> None:
    """Bugbot closes NEUTRAL when it has nothing to say; SKIPPED is a path filter."""
    rollup = [
        _check("Cursor Bugbot", conclusion="NEUTRAL"),
        _check("deploy-frontend", conclusion="SKIPPED"),
    ]
    assert auto_merge.failing_check_names(rollup) == []
    assert auto_merge.pending_check_names(rollup) == []


def test_all_green_still_merges() -> None:
    rollup = [_check("path-guard"), _check("trivy"), _check("Cursor Bugbot", conclusion="NEUTRAL")]
    assert (
        auto_merge.should_attempt_squash(
            is_draft=False,
            merge_state_status="BLOCKED",
            review_decision=None,
            path_guard_ok=True,
            human_threads=False,
            pending_checks=auto_merge.pending_check_names(rollup),
            failed_checks=auto_merge.failing_check_names(rollup),
        )
        is True
    )


def test_older_failed_attempt_does_not_poison_a_rerun() -> None:
    """GitHub keeps the old cancelled run beside the newer success."""
    rollup = [
        _check("trivy", conclusion="CANCELLED", completed="2026-08-17T14:00:00Z"),
        _check("trivy", conclusion="SUCCESS", completed="2026-08-17T14:43:20Z"),
    ]
    assert auto_merge.failing_check_names(rollup) == []


def test_status_context_shape_is_understood() -> None:
    """Legacy commit statuses use context/state, not name/status/conclusion."""
    rollup = [
        {"__typename": "StatusContext", "context": "ci/legacy", "state": "PENDING"},
    ]
    assert auto_merge.pending_check_names(rollup) == ["ci/legacy"]
    rollup[0]["state"] = "SUCCESS"
    assert auto_merge.pending_check_names(rollup) == []
    assert auto_merge.failing_check_names(rollup) == []


def test_poll_survives_transient_api_failure(monkeypatch) -> None:
    """A 503 mid-poll must not kill a run whose whole job is to wait (PR #500)."""
    calls = {"n": 0}

    def flaky_load_pr(number: int) -> dict:
        calls["n"] += 1
        if calls["n"] == 1:
            raise auto_merge.GhError("gh pr view failed (1): HTTP 503")
        return {
            "number": number,
            "url": "https://example.test/pr",
            "isDraft": False,
            "state": "MERGED",
            "mergedAt": "2026-08-17T15:00:00Z",
            "mergeStateStatus": "CLEAN",
            "statusCheckRollup": [],
        }

    monkeypatch.setattr(auto_merge, "load_pr", flaky_load_pr)
    monkeypatch.setattr(auto_merge.time, "sleep", lambda _seconds: None)

    assert auto_merge.process_pr(500, "ccruz0/crypto-2.0", poll_seconds=30, dry_run=True) == 0
    assert calls["n"] >= 2, "expected the poll loop to retry after the 503"


# --- PR #505: arming survives a push and fires on the next commit ------------


def _pr(*, pending: bool, armed: bool, state: str = "OPEN") -> dict:
    checks = [_check("path-guard")]
    if pending:
        checks.append(_check("Cursor Bugbot", status="IN_PROGRESS", conclusion=None, completed=""))
    return {
        "number": 505,
        "url": "https://example.test/pr/505",
        "isDraft": False,
        "state": state,
        "mergedAt": None,
        "mergeStateStatus": "BLOCKED",
        "reviewDecision": None,
        "autoMergeRequest": {"enabledAt": "2026-08-18T06:44:47Z"} if armed else None,
        "statusCheckRollup": checks,
    }


def _instrument(monkeypatch, pr: dict) -> list[str]:
    """Record the order of side effects, and stop the run after one poll."""
    calls: list[str] = []
    monkeypatch.setattr(auto_merge, "load_pr", lambda _n: pr)
    monkeypatch.setattr(auto_merge, "load_pr_with_retry", lambda _n, **_k: pr)
    monkeypatch.setattr(auto_merge, "time", auto_merge.time)
    monkeypatch.setattr(auto_merge.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        auto_merge, "disable_auto_merge",
        lambda _u: calls.append("disable") or "auto-merge disabled",
    )
    monkeypatch.setattr(
        auto_merge, "enable_auto_merge",
        lambda _u: calls.append("enable") or "auto-merge enabled",
    )
    monkeypatch.setattr(
        auto_merge, "resolve_eligible_bot_threads",
        lambda *a, **k: calls.append("resolve_threads"),
    )
    monkeypatch.setattr(auto_merge, "list_unresolved_threads", lambda *a: [])
    monkeypatch.setattr(
        auto_merge, "try_squash_merge",
        lambda *a, **k: calls.append("squash") or "merged",
    )
    return calls


def test_stale_arming_is_disarmed_when_head_has_pending_checks(monkeypatch) -> None:
    calls = _instrument(monkeypatch, _pr(pending=True, armed=True))
    auto_merge.process_pr(505, "ccruz0/crypto-2.0", poll_seconds=0)
    assert "disable" in calls, "an arming from an earlier commit must be disarmed"
    assert "squash" not in calls, "must not merge while checks are pending"


def test_disarm_happens_before_resolving_bot_threads(monkeypatch) -> None:
    """Order matters: resolving threads is what unblocks the ruleset.

    If we resolve first, the stale arming fires before we ever disarm it —
    which is exactly how #505 merged with Bugbot still running.
    """
    calls = _instrument(monkeypatch, _pr(pending=True, armed=True))
    auto_merge.process_pr(505, "ccruz0/crypto-2.0", poll_seconds=0)
    assert calls.index("disable") < calls.index("resolve_threads")


def test_no_disarm_when_nothing_was_armed(monkeypatch) -> None:
    calls = _instrument(monkeypatch, _pr(pending=True, armed=False))
    auto_merge.process_pr(505, "ccruz0/crypto-2.0", poll_seconds=0)
    assert "disable" not in calls


def test_green_head_keeps_its_arming_and_merges(monkeypatch) -> None:
    """A green head must still arm and merge — no regression from the disarm."""
    calls = _instrument(monkeypatch, _pr(pending=False, armed=False))
    auto_merge.process_pr(505, "ccruz0/crypto-2.0", poll_seconds=0)
    assert "disable" not in calls
    assert "enable" in calls
    assert "squash" in calls
