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
