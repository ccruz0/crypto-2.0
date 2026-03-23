"""Tests for scripts/path_guard_audit.py static scanner."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
AUDIT_SCRIPT = BACKEND_ROOT / "scripts" / "path_guard_audit.py"


def _load_audit_module():
    name = "_path_guard_audit_testmod"
    spec = importlib.util.spec_from_file_location(name, AUDIT_SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_scan_line_detects_write_text():
    audit = _load_audit_module()
    hits = audit.scan_line('    target.write_text("x")', "some_module.py")
    assert hits
    assert hits[0].pattern_name == "Path.write_text"


def test_scan_line_pg_audit_ignore_skipped():
    audit = _load_audit_module()
    hits = audit.scan_line(
        'probe.write_text("")  # pg-audit-ignore: probe',
        "cursor_execution_bridge.py",
    )
    assert hits == []


def test_lab_enforced_file_gets_error_severity():
    audit = _load_audit_module()
    hits = audit.scan_line("p.write_text(x)", "agent_callbacks.py")
    assert hits and hits[0].severity == "error"


def test_exempt_strategy_patch_is_info():
    audit = _load_audit_module()
    hits = audit.scan_line("path.write_text(u)", "agent_strategy_patch.py")
    assert hits and hits[0].severity == "info"


def test_scan_file_temp_lab_enforced_fails_fail_on_lab(tmp_path):
    audit = _load_audit_module()
    f = tmp_path / "agent_callbacks.py"
    f.write_text("def bad():\n    Path('x').write_text('y')\n", encoding="utf-8")
    findings = audit.scan_file(f)
    assert any(x.severity == "error" for x in findings)


def test_subprocess_audit_fail_on_lab_exit_zero():
    r = subprocess.run(
        [sys.executable, str(AUDIT_SCRIPT), "--fail-on-lab-bypass"],
        cwd=str(BACKEND_ROOT),
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr + r.stdout


def test_subprocess_ci_includes_pass_message():
    r = subprocess.run(
        [sys.executable, str(AUDIT_SCRIPT), "--fail-on-lab-bypass", "--ci"],
        cwd=str(BACKEND_ROOT),
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr + r.stdout
    assert "LAB path_guard_audit (CI)" in r.stdout
    assert "CI gate passed" in r.stdout


def test_lab_enforced_flags_shell_true():
    audit = _load_audit_module()
    hits = audit.scan_line("subprocess.run(args, shell=True)", "agent_callbacks.py")
    assert any(h.pattern_name == "subprocess shell=True" and h.severity == "error" for h in hits)


def test_lab_enforced_flags_os_system():
    audit = _load_audit_module()
    hits = audit.scan_line('os.system("rm -rf /")', "cursor_execution_bridge.py")
    assert any("os.system" in h.pattern_name for h in hits)


def test_subprocess_argv_list_not_error_in_lab_enforced():
    audit = _load_audit_module()
    hits = audit.scan_line(
        'result = subprocess.run(["git", "diff"], cwd=str(staging_path))',
        "cursor_execution_bridge.py",
    )
    assert not any("shell" in h.pattern_name for h in hits)


def test_shell_true_not_flagged_outside_lab_enforced():
    audit = _load_audit_module()
    hits = audit.scan_line("subprocess.run(x, shell=True)", "signal_monitor.py")
    assert not any(h.pattern_name == "subprocess shell=True" for h in hits)


def test_pg_audit_ignore_skips_subprocess_rules():
    audit = _load_audit_module()
    hits = audit.scan_line(
        'os.system("x")  # pg-audit-ignore: test only',
        "agent_callbacks.py",
    )
    assert hits == []


def test_report_findings_ci_emits_github_error_command(capsys, tmp_path):
    audit = _load_audit_module()
    p = (tmp_path / "agent_callbacks.py").resolve()
    p.write_text("# x", encoding="utf-8")
    fe = audit.Finding(
        path=p,
        line_no=2,
        pattern_name="Path.write_text",
        line="y.write_text(z)",
        severity="error",
        suggestion="Use path_guard.safe_write_text.",
    )
    n = audit.report_findings([fe], verbose=False, ci=True)
    assert n == 1
    out = capsys.readouterr().out
    assert "::error" in out
    assert "line=2" in out
    assert "path_guard_audit" in out
