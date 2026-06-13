"""Tests for Jarvis Phase 4 test agent."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.jarvis.agents.patch_agent import create_patch
from app.jarvis.agents.test_agent import (
    determine_relevant_tests,
    run_selected_tests,
    run_tests_for_patch,
)


@pytest.mark.parametrize(
    "objective,expected_fragment",
    [
        ("Determine tests affected by routes_jarvis.py", "jarvis"),
        ("Analyze websocket implementation", "test_"),
        ("Find OpenClaw regression", "openclaw"),
        ("Generate patch for deploy validation", "test_"),
        ("Review patch risk", "patch"),
    ],
)
def test_determine_relevant_tests(objective, expected_fragment):
    tests = determine_relevant_tests(objective=objective)
    assert isinstance(tests, list)
    assert len(tests) >= 1
    assert any(expected_fragment in t for t in tests)


def test_determine_tests_from_changed_files():
    tests = determine_relevant_tests(
        changed_files=["backend/app/api/routes_jarvis.py"],
        objective="",
    )
    assert any("jarvis" in t for t in tests)


def test_determine_tests_limit():
    tests = determine_relevant_tests(objective="jarvis patch review repository")
    assert len(tests) <= 10


def test_run_selected_tests_dry_run():
    result = run_selected_tests(["backend/tests/test_patch_agent.py"], dry_run=True)
    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["local_only"] is True


def test_run_tests_for_patch_dry_run():
    patch = create_patch(objective="jarvis test", repository_analysis={})
    result = run_tests_for_patch(patch=patch, dry_run=True)
    assert result["agent"] == "test_agent"
    assert result["summary"]
    assert result["read_only"] is True


def test_run_tests_for_patch_selected_tests():
    patch = create_patch(objective="routes_jarvis", repository_analysis={})
    result = run_tests_for_patch(patch=patch, dry_run=True)
    assert len(result["selected_tests"]) >= 1


@patch.dict("os.environ", {"ENVIRONMENT": "production"})
def test_run_blocked_in_production():
    result = run_selected_tests(["backend/tests/test_patch_agent.py"], dry_run=False)
    assert result["ok"] is False
    assert "production" in result["error"].lower()


def test_run_tests_summary_pass():
    result = run_selected_tests([], dry_run=True)
    assert "Dry-run" in run_tests_for_patch(
        patch={"objective": "x", "target_files": []}, dry_run=True
    )["summary"]


def test_run_tests_timeout_handling():
    with patch("app.jarvis.agents.test_agent.subprocess.run") as mock_run:
        import subprocess

        mock_run.side_effect = subprocess.TimeoutExpired(cmd="pytest", timeout=1)
        result = run_selected_tests(["backend/tests/test_patch_agent.py"], dry_run=False, timeout_sec=1)
        assert result["ok"] is False
        assert "timeout" in result["error"].lower()


def test_run_tests_collects_failing():
    with patch("app.jarvis.agents.test_agent.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 1
        mock_run.return_value.stdout = "FAILED backend/tests/test_x.py::test_y"
        mock_run.return_value.stderr = ""
        result = run_selected_tests(["backend/tests/test_x.py"], dry_run=False)
        assert result["failed_count"] >= 1


def test_run_tests_execution_log():
    with patch("app.jarvis.agents.test_agent.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "1 passed"
        mock_run.return_value.stderr = ""
        result = run_selected_tests(["backend/tests/test_patch_agent.py"], dry_run=False)
        assert "execution_log" in result


def test_run_tests_local_only_flag():
    result = run_selected_tests(["backend/tests/test_patch_agent.py"], dry_run=True)
    assert result["local_only"] is True


def test_run_tests_for_patch_created_at():
    patch = create_patch(objective="x", repository_analysis={})
    result = run_tests_for_patch(patch=patch, dry_run=True)
    assert result["created_at"]


def test_default_fallback_test_file():
    tests = determine_relevant_tests(objective="unrelated xyz topic")
    assert len(tests) >= 1


def test_run_tests_returncode_preserved():
    with patch("app.jarvis.agents.test_agent.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 2
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = "error"
        result = run_selected_tests(["backend/tests/test_patch_agent.py"], dry_run=False)
        assert result["returncode"] == 2


def test_run_tests_passed_count():
    with patch("app.jarvis.agents.test_agent.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "test_foo PASSED\ntest_bar PASSED"
        mock_run.return_value.stderr = ""
        result = run_selected_tests(["backend/tests/test_patch_agent.py"], dry_run=False)
        assert result["passed_count"] >= 1
