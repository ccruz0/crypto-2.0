"""
Tests for task_compiler task type inference (keyword/rule-based).

Covers: Investigation, Bug, Patch, Monitoring, Content, Deploy, and
ambiguous default to Investigation.
"""

from __future__ import annotations

import pytest

from app.services.task_compiler import (
    compile_task_from_intent,
    infer_task_type,
    validate_and_fix_task,
)


class TestInferTaskType:
    """Clear cases for each inferred type."""

    def test_clear_investigation(self) -> None:
        assert infer_task_type("investigate why dashboard position size does not match") == "Investigation"
        assert infer_task_type("Investigate why alerts are not sent when buy conditions are met") == "Investigation"
        assert infer_task_type("figure out why sync fails") == "Investigation"
        assert infer_task_type("look into the timeout") == "Investigation"
        assert infer_task_type("find out why orders are duplicated") == "Investigation"

    def test_clear_bug(self) -> None:
        assert infer_task_type("fix the dashboard position mismatch") == "Bug"
        assert infer_task_type("bug in exchange sync timeout") == "Bug"
        assert infer_task_type("not working when market is closed") == "Bug"
        assert infer_task_type("fix the login error") == "Bug"
        assert infer_task_type("failing tests in signal monitor") == "Bug"

    def test_clear_patch(self) -> None:
        assert infer_task_type("apply patch for the SSL fix") == "Patch"
        assert infer_task_type("update code to use new API") == "Patch"
        assert infer_task_type("patch to add retry logic") == "Patch"
        assert infer_task_type("implement fix for race condition") == "Patch"

    def test_clear_monitoring(self) -> None:
        assert infer_task_type("monitor the order queue depth") == "Monitoring"
        assert infer_task_type("watch for duplicate signals") == "Monitoring"
        assert infer_task_type("check if health endpoint returns 200") == "Monitoring"
        assert infer_task_type("alert when balance drops below threshold") == "Monitoring"

    def test_clear_content(self) -> None:
        assert infer_task_type("write the runbook for deploy") == "Content"
        assert infer_task_type("create post about the new feature") == "Content"
        assert infer_task_type("draft the incident report") == "Content"
        assert infer_task_type("document the API changes") == "Content"

    def test_clear_deploy(self) -> None:
        assert infer_task_type("deploy to production tonight") == "Deploy"
        assert infer_task_type("push to prod after tests pass") == "Deploy"
        assert infer_task_type("release to prod the new backend") == "Deploy"
        assert infer_task_type("roll out the new backend") == "Deploy"

    def test_ambiguous_defaults_to_investigation(self) -> None:
        assert infer_task_type("something random") == "Investigation"
        assert infer_task_type("review the code") == "Investigation"
        assert infer_task_type("") == "Investigation"
        assert infer_task_type("   ") == "Investigation"


class TestCompileRespectsInferredType:
    """compile_task_from_intent uses inferred type."""

    def test_compile_investigation(self) -> None:
        task = compile_task_from_intent("investigate why alerts are not sent", "Carlos")
        assert task.get("type") == "Investigation"

    def test_compile_bug(self) -> None:
        task = compile_task_from_intent("fix the dashboard sync bug", "Carlos")
        assert task.get("type") == "Bug"

    def test_compile_patch(self) -> None:
        task = compile_task_from_intent("apply patch for SSL", "Carlos")
        assert task.get("type") == "Patch"

    def test_compile_monitoring(self) -> None:
        task = compile_task_from_intent("monitor the order queue", "Carlos")
        assert task.get("type") == "Monitoring"

    def test_compile_content(self) -> None:
        task = compile_task_from_intent("write the runbook for deploy", "Carlos")
        assert task.get("type") == "Content"

    def test_compile_deploy(self) -> None:
        task = compile_task_from_intent("deploy to production", "Carlos")
        assert task.get("type") == "Deploy"

    def test_compile_ambiguous_default_investigation(self) -> None:
        task = compile_task_from_intent("review the architecture", "Carlos")
        assert task.get("type") == "Investigation"


class TestValidationAcceptsInferredTypes:
    """validate_and_fix_task normalizes and accepts all inferred types."""

    @pytest.mark.parametrize("task_type", ["Investigation", "Bug", "Patch", "Monitoring", "Content", "Deploy"])
    def test_valid_type_preserved(self, task_type: str) -> None:
        task = {
            "title": "Test task",
            "type": task_type,
            "status": "planned",
            "execution_mode": "Strict",
            "source": "Carlos",
            "objective": "Test objective",
            "details": "Test details",
        }
        fixed, err = validate_and_fix_task(task)
        assert err is None
        assert (fixed.get("type") or "").strip() == task_type
