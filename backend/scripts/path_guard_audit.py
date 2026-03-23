#!/usr/bin/env python3
"""
Static scan for direct filesystem writes and high-risk subprocess/shell usage.

Scans Python sources under backend/app/services and optionally backend/scripts
for: (1) Path/open write patterns, (2) in LAB_ENFORCED files only — shell=True,
os.system, string-form subprocess, and asyncio.create_subprocess_shell.
Not a full parser; no detection of dynamic command strings or shell redirection hidden in variables.

Usage (from backend/):
  python scripts/path_guard_audit.py
  python scripts/path_guard_audit.py --fail-on-lab-bypass
  python scripts/path_guard_audit.py --fail-on-lab-bypass --ci   # GitHub Actions (lab-path-guard-audit.yml)

Exit codes:
  0 — success (with --fail-on-lab-bypass: no violations in LAB-enforced files)
  1 — --fail-on-lab-bypass and at least one error-level finding in LAB-enforced files
  2 — bad arguments
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_ROOT.parent
SERVICES_DIR = BACKEND_ROOT / "app" / "services"
SCRIPTS_DIR = BACKEND_ROOT / "scripts"

# Operational / PROD mutation modules — direct writes expected; do not fail CI on these.
EXEMPT_BASENAMES = frozenset(
    {
        "path_guard.py",
        "agent_strategy_patch.py",
        "config_loader.py",
        "notion_env.py",
        "task_fallback_store.py",
        "agent_activity_log.py",
        "signal_monitor.py",
        "margin_leverage_cache.py",
        "exchange_sync.py",
        "crypto_com_trade.py",
        "telegram_commands.py",
        "fill_tracker.py",
        "engine.py",  # ai_engine: operational run artifacts under AI_RUNS_DIR / tmp
        "_paths.py",  # writable-dir probes; not OpenClaw artifact writes
    }
)

# LAB-aligned services: bypasses here are high severity with --fail-on-lab-bypass.
LAB_ENFORCED = frozenset(
    {
        "agent_callbacks.py",
        "agent_recovery.py",
        "cursor_handoff.py",
        "agent_strategy_analysis.py",
        "signal_performance_analysis.py",
        "profile_setting_analysis.py",
        "agent_versioning.py",
        "cursor_execution_bridge.py",
    }
)

IGNORE_SUBSTRING = "pg-audit-ignore"

PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\.write_text\s*\("), "Path.write_text"),
    (re.compile(r"\.write_bytes\s*\("), "Path.write_bytes"),
    (re.compile(r"open\s*\([^)]*['\"](w|wb|a|ab)['\"]"), "open(..., 'w'|'a'|...)"),
]

# LAB_ENFORCED only: subprocess/shell patterns that often bypass path_guard (redirection, shell parsing).
# List-argv subprocess.run([...]) without shell=True is intentionally not flagged (e.g. git/cursor in staging).
SUBPROCESS_LAB_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bshell\s*=\s*True\b"), "subprocess shell=True"),
    (re.compile(r"\bos\.system\s*\("), "os.system("),
    (re.compile(r"asyncio\.create_subprocess_shell\s*\("), "asyncio.create_subprocess_shell("),
    (re.compile(r"subprocess\.run\s*\(\s*[\"']"), "subprocess.run(string shell)"),
    (re.compile(r"subprocess\.Popen\s*\(\s*[\"']"), "subprocess.Popen(string shell)"),
]


@dataclass
class Finding:
    path: Path
    line_no: int
    pattern_name: str
    line: str
    severity: str  # error | warn | info
    suggestion: str


def _severity_for_file(basename: str, line: str) -> str:
    if basename in EXEMPT_BASENAMES:
        return "info"
    if IGNORE_SUBSTRING in line:
        return "info"
    if basename in LAB_ENFORCED:
        return "error"
    if basename.startswith("agent_") or "openclaw" in basename or basename.startswith("governance_"):
        return "warn"
    return "info"


def _suggestion(severity: str, pattern_name: str) -> str:
    if pattern_name.startswith("Path."):
        return "Prefer app.services.path_guard.safe_write_text / safe_write_bytes for LAB docs and artifacts."
    if pattern_name.startswith("open("):
        return "Prefer path_guard.safe_open_text(..., 'w'|'a') for LAB paths under docs/ or artifact dirs."
    if (
        "shell=True" in pattern_name
        or "os.system" in pattern_name
        or "string shell" in pattern_name
        or "create_subprocess_shell" in pattern_name
    ):
        return (
            "Do not use shell-based subprocess for LAB repo/doc outputs (redirection bypasses path_guard). "
            "Build content in Python and use path_guard.safe_*; use argv lists without shell=True for git/CLI in staging."
        )
    return "Review: use path_guard for LAB-safe writes; keep PROD/operational writes out of guarded APIs."


def scan_line(line: str, basename: str) -> list[Finding]:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return []
    if IGNORE_SUBSTRING in line:
        return []

    out: list[Finding] = []
    for rx, name in PATTERNS:
        if rx.search(line):
            sev = _severity_for_file(basename, line)
            out.append(
                Finding(
                    path=Path(basename),
                    line_no=0,
                    pattern_name=name,
                    line=stripped[:200],
                    severity=sev,
                    suggestion=_suggestion(sev, name),
                )
            )

    if basename in LAB_ENFORCED:
        for rx, name in SUBPROCESS_LAB_PATTERNS:
            if rx.search(line):
                out.append(
                    Finding(
                        path=Path(basename),
                        line_no=0,
                        pattern_name=name,
                        line=stripped[:200],
                        severity="error",
                        suggestion=_suggestion("error", name),
                    )
                )
    return out


def scan_file(path: Path) -> list[Finding]:
    basename = path.name
    if basename == "path_guard_audit.py":
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []

    findings: list[Finding] = []
    for i, line in enumerate(text.splitlines(), start=1):
        for f in scan_line(line, basename):
            f = Finding(
                path=path,
                line_no=i,
                pattern_name=f.pattern_name,
                line=f.line,
                severity=f.severity,
                suggestion=f.suggestion,
            )
            findings.append(f)
    return findings


def scan_tree(root: Path, *, label: str) -> list[Finding]:
    if not root.is_dir():
        return []
    out: list[Finding] = []
    for p in sorted(root.rglob("*.py")):
        if p.name.startswith("test_") or "/tests/" in p.as_posix():
            continue
        out.extend(scan_file(p))
    return out


def _repo_relative_path(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        try:
            return path.relative_to(BACKEND_ROOT).as_posix()
        except ValueError:
            return path.as_posix()


def _print_ci_error_annotations(errors: list[Finding]) -> None:
    """GitHub Actions workflow commands (file annotations in PR UI)."""
    for f in errors:
        rel = _repo_relative_path(f.path)
        hint = (
            "Use path_guard.safe_* or pg-audit-ignore only for documented probes."
            if not any(
                x in f.pattern_name
                for x in ("shell", "os.system", "subprocess", "create_subprocess_shell")
            )
            else "Remove shell writes; use path_guard for repo paths or argv-only subprocess."
        )
        msg = f"LAB-enforced file issue: {f.pattern_name}. {hint} {f.suggestion}"
        safe = msg.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::error file={rel},line={f.line_no},title=path_guard_audit::{safe}")


def report_findings(findings: list[Finding], *, verbose: bool, ci: bool) -> int:
    errors = [f for f in findings if f.severity == "error"]
    warns = [f for f in findings if f.severity == "warn"]
    infos = [f for f in findings if f.severity == "info"]

    def _print_batch(title: str, items: list[Finding]) -> None:
        if not items:
            return
        print(f"\n=== {title} ({len(items)}) ===")
        for f in items:
            rel = f.path.relative_to(BACKEND_ROOT) if f.path.is_relative_to(BACKEND_ROOT) else f.path
            print(f"  {rel}:{f.line_no}  [{f.severity}] {f.pattern_name}")
            print(f"    {f.line}")
            print(f"    -> {f.suggestion}")
            if verbose and f.path.name in EXEMPT_BASENAMES:
                print("    (file is in EXEMPT_BASENAMES — informational only)")

    if ci:
        print(
            "LAB path_guard_audit (CI) — failing on error-level hits in LAB_ENFORCED files "
            "(raw Path/open writes + shell=True / os.system / string subprocess / create_subprocess_shell)."
        )
        print(f"Scan: {SERVICES_DIR.relative_to(REPO_ROOT).as_posix()}/ (scripts excluded; PROD/operational modules exempt in scanner).")

    _print_batch("error", errors)
    if ci and errors:
        _print_ci_error_annotations(errors)
    _print_batch("warn", warns)
    if verbose:
        _print_batch("info", infos)

    print(f"\nTotal: {len(errors)} error, {len(warns)} warn, {len(infos)} info (info hidden without --verbose)")
    if ci and len(errors) == 0:
        print("\nOK: No LAB bypass patterns (writes + risky subprocess) in LAB_ENFORCED service files (CI gate passed).")
    return len(errors)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan for direct writes and risky subprocess usage (LAB_ENFORCED files)"
    )
    parser.add_argument(
        "--fail-on-lab-bypass",
        action="store_true",
        help="Exit 1 if any error-level finding in LAB_ENFORCED files",
    )
    parser.add_argument(
        "--include-scripts",
        action="store_true",
        help="Also scan backend/scripts (default: services only)",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Include info-level findings in report")
    parser.add_argument(
        "--ci",
        action="store_true",
        help="CI-friendly header + GitHub Actions ::error:: annotations for each error finding",
    )
    args = parser.parse_args(argv)

    findings: list[Finding] = []
    findings.extend(scan_tree(SERVICES_DIR, label="services"))
    if args.include_scripts:
        findings.extend(scan_tree(SCRIPTS_DIR, label="scripts"))

    err_count = report_findings(findings, verbose=args.verbose, ci=args.ci)
    if args.fail_on_lab_bypass and err_count > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
