"""Perico filesystem + pytest tools (scoped to PERICO_REPO_ROOT)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.jarvis import tools as jarvis_tools
from app.jarvis.perico_mission import (
    build_perico_deliverables_snapshot,
    build_perico_mission_prompt,
    perico_should_block_for_operator_input,
    perico_try_auto_pytest_retry,
)
from app.jarvis.autonomous_agents import ExecutionAgent
from app.jarvis.perico_tools import perico_apply_patch, perico_repo_read, perico_run_pytest


@pytest.fixture()
def perico_repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "backend" / "tests").mkdir(parents=True)
    (root / "src" / "pkg").mkdir(parents=True)
    (root / "src" / "pkg" / "hello.py").write_text('msg = "PERICO_UNIQUE_MARKER"\n', encoding="utf-8")
    (root / "backend" / "tests" / "test_perico_smoke.py").write_text(
        "def test_smoke():\n    assert True\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PERICO_REPO_ROOT", str(root))
    return root


def test_perico_repo_read_list_and_read(perico_repo: Path):
    out = perico_repo_read(operation="list", relative_path="src/pkg")
    assert out["ok"] is True
    assert "hello.py" in out["entries"]

    out2 = perico_repo_read(operation="read", relative_path="src/pkg/hello.py")
    assert out2["ok"] is True
    assert "PERICO_UNIQUE_MARKER" in out2["content"]


def test_perico_repo_read_grep(perico_repo: Path):
    out = perico_repo_read(operation="grep", relative_path="src", pattern="PERICO_UNIQUE", max_results=20)
    assert out["ok"] is True
    assert out["matches"]
    assert out["matches"][0]["path"].replace("\\", "/").endswith("pkg/hello.py")


def test_perico_apply_patch_requires_flag(perico_repo: Path, monkeypatch):
    monkeypatch.delenv("PERICO_WRITE_ENABLED", raising=False)
    out = perico_apply_patch(
        relative_path="src/pkg/hello.py",
        old_text='msg = "PERICO_UNIQUE_MARKER"',
        new_text='msg = "patched"',
    )
    assert out["ok"] is False
    assert out["error"] == "writes_disabled"


def test_perico_apply_patch_writes(perico_repo: Path, monkeypatch):
    monkeypatch.setenv("PERICO_WRITE_ENABLED", "1")
    out = perico_apply_patch(
        relative_path="src/pkg/hello.py",
        old_text='msg = "PERICO_UNIQUE_MARKER"',
        new_text='msg = "patched"',
    )
    assert out["ok"] is True
    text = (perico_repo / "src" / "pkg" / "hello.py").read_text(encoding="utf-8")
    assert "patched" in text


def test_perico_run_pytest_smoke(perico_repo: Path, monkeypatch):
    monkeypatch.chdir(perico_repo)
    out = perico_run_pytest(relative_path="tests/test_perico_smoke.py", extra_args="-q", timeout_seconds=120)
    assert out["ok"] is True
    assert out.get("tests_ok") is True
    assert out.get("exit_code") == 0


def test_execution_agent_perico_tool_with_marker(monkeypatch):
    def fake_invoke(name, args, jarvis_run_id=None):
        assert name == "perico_repo_read"
        return {"ok": True, "operation": "list", "entries": ["a.py"], "path": "/tmp"}

    monkeypatch.setattr("app.jarvis.autonomous_agents.invoke_registered_tool", fake_invoke)
    strat = {
        "actions": [
            {
                "title": "List",
                "action_type": "perico_repo_read",
                "params": {"operation": "list", "relative_path": "."},
                "execution_mode": "auto_execute",
                "priority_score": 50,
            }
        ]
    }
    out = ExecutionAgent().run(strategy=strat, mission_prompt=build_perico_mission_prompt(user_text="x"))
    row = out["executed"][0]
    assert row["status"] == "executed"
    assert row["result"]["entries"] == ["a.py"]


def test_execution_agent_skips_perico_without_marker(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("invoke should not run")

    monkeypatch.setattr("app.jarvis.autonomous_agents.invoke_registered_tool", boom)
    strat = {
        "actions": [
            {
                "title": "List",
                "action_type": "perico_repo_read",
                "params": {"operation": "list"},
                "execution_mode": "auto_execute",
                "priority_score": 50,
            }
        ]
    }
    out = ExecutionAgent().run(strategy=strat, mission_prompt="plain marketing prompt")
    row = out["executed"][0]
    assert row["status"] == "skipped"


def test_tools_registered_in_specs():
    assert "perico_repo_read" in jarvis_tools.TOOL_SPECS
    assert "perico_apply_patch" in jarvis_tools.TOOL_SPECS
    assert "perico_run_pytest" in jarvis_tools.TOOL_SPECS


def test_perico_gate_patch_without_pytest():
    execution = {
        "executed": [
            {
                "action_type": "perico_apply_patch",
                "result": {"ok": True, "relative_path": "x.py"},
            }
        ]
    }
    msg = perico_should_block_for_operator_input(execution)
    assert msg and "perico_run_pytest" in msg


def test_perico_auto_pytest_retry_then_block(monkeypatch):
    execution = {
        "executed": [
            {
                "action_type": "perico_apply_patch",
                "result": {"ok": True, "relative_path": "z.py"},
            },
            {
                "action_type": "perico_run_pytest",
                "params": {"relative_path": "tests/x.py"},
                "result": {"ok": True, "pytest": True, "tests_ok": False, "exit_code": 1},
            },
        ]
    }

    def _fake_invoke(name, args, jarvis_run_id=None):
        assert name == "perico_run_pytest"
        return {"ok": True, "pytest": True, "tests_ok": False, "exit_code": 1, "stderr_tail": "boom"}

    monkeypatch.setattr("app.jarvis.executor.invoke_registered_tool", _fake_invoke)
    extra = perico_try_auto_pytest_retry(execution)
    assert len(extra) == 1
    execution.setdefault("executed", []).extend(extra)
    msg = perico_should_block_for_operator_input(execution)
    assert msg and ("pytest" in msg.lower() or "rojo" in msg.lower())


def test_deliverables_includes_files_and_tests_flag():
    mp = build_perico_mission_prompt(user_text="x")
    execution = {
        "executed": [
            {
                "action_type": "perico_apply_patch",
                "result": {"ok": True, "relative_path": "a.py", "diff_preview": "diff"},
            },
            {
                "action_type": "perico_run_pytest",
                "params": {"relative_path": "tests/test_x.py", "extra_args": "-q"},
                "result": {
                    "ok": True,
                    "pytest": True,
                    "tests_ok": True,
                    "exit_code": 0,
                    "cmd": ["python3", "-m", "pytest", "-q", "--tb=no", "tests/test_x.py", "-q"],
                },
            },
        ]
    }
    snap = build_perico_deliverables_snapshot(
        mission_prompt=mp,
        plan={},
        execution=execution,
        goal_satisfied=True,
        retry_attempted=True,
    )
    assert snap["patch_applied"] is True
    assert snap["tests_passed"] is True
    assert snap["retry_attempted"] is True
    assert "a.py" in snap["files_touched"]
    assert snap.get("validation_command")
    assert "pytest" in snap["validation_command"]
    assert "tests/test_x.py" in snap["validation_command"]
    assert "a.py" in snap["suspected_files"]


def test_deliverables_suspected_files_from_grep_and_read():
    mp = build_perico_mission_prompt(user_text="investigar telegram")
    execution = {
        "executed": [
            {
                "action_type": "perico_repo_read",
                "params": {"operation": "grep", "relative_path": "backend/app", "pattern": "Telegram"},
                "result": {
                    "ok": True,
                    "operation": "grep",
                    "matches": [
                        {"path": "backend/app/jarvis/telegram_control.py", "line": 10, "text": "x"},
                        {"path": "backend/app/jarvis/telegram_service.py", "line": 2, "text": "y"},
                    ],
                },
            },
            {
                "action_type": "perico_repo_read",
                "params": {"operation": "read", "relative_path": "README.md"},
                "result": {"ok": True, "operation": "read", "path": "/tmp/README.md", "content": "# x"},
            },
        ]
    }
    snap = build_perico_deliverables_snapshot(
        mission_prompt=mp,
        plan={},
        execution=execution,
        goal_satisfied=True,
    )
    sf = snap.get("suspected_files") or []
    assert "backend/app/jarvis/telegram_control.py" in sf
    assert "backend/app/jarvis/telegram_service.py" in sf
    assert "README.md" in sf
    assert snap.get("validation_command") == ""
