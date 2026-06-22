#!/usr/bin/env python3
"""ACW End-to-End Real PR Validation — LAB only.

Runs the full ACW validation battery against a live LAB backend:
  1. Real lifecycle (submit → Gate 1 → Gate 2 → real PR)
  2. Artifact integrity
  3. Backend restart recovery
  4. Concurrent task isolation (3 tasks)
  5. GitHub failure handling (corrupt sandbox remote)
  6. Observability (Jarvis history + task detail)

Usage:
  python backend/scripts/diag/run_acw_e2e_validation.py
  python backend/scripts/diag/run_acw_e2e_validation.py --base-url http://127.0.0.1:8012
  python backend/scripts/diag/run_acw_e2e_validation.py --skip-real-pr --skip-restart
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
REPORT_DIR = REPO_ROOT / "logs" / "acw_e2e"
DEFAULT_BASE = "http://127.0.0.1:8012"

PRIMARY_OBJECTIVE = (
    "Add a validation marker line to docs/acw_e2e_validation.md documenting "
    "the ACW E2E validation run date (LAB only, minimal doc change)."
)
TARGET_FILES = ["docs/acw_e2e_validation.md"]

REQUIRED_ARTIFACTS = frozenset(
    {"patch.diff", "review.md", "tests.json", "evidence.json", "approval_package.json"}
)

ACW_PIPELINE = (
    "planning",
    "investigating",
    "patch_ready",
    "reviewing",
    "testing",
    "waiting_for_approval",
    "applying_patch",
    "sandbox_testing",
    "waiting_for_pr_approval",
    "creating_pr",
    "pr_created",
    "completed",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _http_json(
    method: str,
    url: str,
    body: dict[str, Any] | None = None,
    timeout: float = 600.0,
) -> tuple[int, dict[str, Any]]:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else {"detail": raw}
        except json.JSONDecodeError:
            payload = {"detail": raw}
        return exc.code, payload


def _artifact_names(detail: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for art in detail.get("artifacts") or []:
        names.add(art.get("standard_name") or art.get("name") or "")
    return {n for n in names if n}


def _status_transitions(detail: dict[str, Any]) -> list[str]:
    transitions: list[str] = []
    for entry in detail.get("execution_log") or []:
        tool = entry.get("tool") or ""
        agent = entry.get("agent") or ""
        if agent == "lifecycle" or tool.startswith("transition"):
            transitions.append(entry.get("output_summary") or tool)
    status = detail.get("status")
    if status and (not transitions or status not in transitions[-1]):
        transitions.append(status)
    return transitions


def _check_preflight(base: str) -> dict[str, Any]:
    out: dict[str, Any] = {"passed": False, "checks": {}}
    code, health = _http_json("GET", f"{base}/api/health/ready", timeout=30)
    out["checks"]["health"] = {"code": code, "ok": code == 200}

    code, safety = _http_json("GET", f"{base}/api/jarvis/safety-status", timeout=30)
    phase5 = safety.get("phase5") or {}
    out["checks"]["safety"] = {
        "code": code,
        "patch_apply": phase5.get("patch_apply_enabled"),
        "pr_creation": phase5.get("pr_creation_enabled"),
        "github_write": phase5.get("github_write_enabled"),
    }

    code, _ = _http_json("GET", f"{base}/api/jarvis/coding-workflow/00000000-0000-0000-0000-000000000000", timeout=10)
    out["checks"]["acw_route"] = {"code": code, "ok": code in (200, 404)}

    out["passed"] = (
        out["checks"]["health"]["ok"]
        and out["checks"]["acw_route"]["ok"]
        and phase5.get("patch_apply_enabled") is True
        and phase5.get("pr_creation_enabled") is True
        and phase5.get("github_write_enabled") is True
    )
    return out


def _submit_acw(base: str, objective: str, *, suffix: str = "", bootstrap_patch: Path | None = None) -> tuple[int, dict[str, Any]]:
    obj = f"{objective} [{suffix}]" if suffix else objective
    if bootstrap_patch is not None:
        out_file = REPORT_DIR / f"bootstrap_{suffix or 'submit'}.json"
        cmd = [
            sys.executable,
            str(REPO_ROOT / "backend" / "scripts" / "diag" / "acw_lab_submit_patch.py"),
            "--patch-file",
            str(bootstrap_patch),
            "--objective",
            obj,
            "--output",
            str(out_file),
        ]
        env = os.environ.copy()
        env.setdefault("DATABASE_URL", "postgresql://trader:CHANGE_ME_STRONG_PASSWORD@172.18.0.2:5432/atp")
        env.setdefault("ATP_WORKSPACE_ROOT", str(REPO_ROOT))
        env.setdefault("TESTING", "1")
        env.setdefault("EXECUTION_CONTEXT", "LAB")
        proc = subprocess.run(cmd, cwd=str(REPO_ROOT / "backend"), env=env, capture_output=True, text=True, timeout=900)
        if proc.returncode != 0:
            return 500, {"detail": proc.stderr or proc.stdout or "bootstrap submit failed"}
        if out_file.is_file():
            payload = json.loads(out_file.read_text(encoding="utf-8"))
            task_id = payload.get("task_id")
            if task_id:
                return _get_detail(base, task_id)
        return 500, {"detail": "bootstrap submit produced no task_id"}
    return _http_json(
        "POST",
        f"{base}/api/jarvis/coding-workflow/submit",
        {"objective": obj, "target_files": TARGET_FILES, "priority": "normal"},
        timeout=900,
    )


def _gate1(base: str, task_id: str) -> tuple[int, dict[str, Any]]:
    return _http_json(
        "POST",
        f"{base}/api/jarvis/coding-workflow/{task_id}/approve-apply",
        {"actor_id": "acw_e2e_validator", "comment": "Gate 1: sandbox apply approved (E2E)"},
        timeout=600,
    )


def _gate2(base: str, task_id: str) -> tuple[int, dict[str, Any]]:
    return _http_json(
        "POST",
        f"{base}/api/jarvis/coding-workflow/{task_id}/approve-pr",
        {"actor_id": "acw_e2e_validator", "comment": "Gate 2: PR creation approved (E2E)"},
        timeout=300,
    )


def _get_detail(base: str, task_id: str) -> tuple[int, dict[str, Any]]:
    return _http_json("GET", f"{base}/api/jarvis/coding-workflow/{task_id}", timeout=60)


def _get_artifacts(base: str, task_id: str) -> tuple[int, dict[str, Any]]:
    return _http_json("GET", f"{base}/api/jarvis/coding-workflow/{task_id}/artifacts", timeout=60)


def _get_execution_list(base: str) -> tuple[int, dict[str, Any]]:
    return _http_json("GET", f"{base}/api/jarvis/tasks/execution?limit=50", timeout=30)


def _get_execution_detail(base: str, task_id: str) -> tuple[int, dict[str, Any]]:
    return _http_json("GET", f"{base}/api/jarvis/tasks/execution/{task_id}", timeout=30)


def _verify_artifacts(base: str, task_id: str, detail: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"passed": False, "missing": [], "present": []}
    names = _artifact_names(detail)
    missing = REQUIRED_ARTIFACTS - names
    result["missing"] = sorted(missing)
    result["present"] = sorted(names & REQUIRED_ARTIFACTS)

    pkg = detail.get("approval_package") or {}
    result["approval_package_keys"] = sorted(pkg.keys())
    result["task_id_match"] = pkg.get("task_id") == task_id

    code, arts = _get_artifacts(base, task_id)
    result["artifacts_endpoint_ok"] = code == 200
    result["artifacts_count"] = len(arts.get("artifacts") or [])

    review = detail.get("review") or {}
    result["has_review"] = bool(review.get("risk_score") is not None or review.get("review_report"))

    phase5 = detail.get("phase5") or {}
    result["pr_url"] = phase5.get("pr_url")
    result["branch_name"] = phase5.get("branch_name")

    result["passed"] = (
        not missing
        and result["task_id_match"]
        and result["artifacts_endpoint_ok"]
        and result["artifacts_count"] >= len(REQUIRED_ARTIFACTS)
    )
    return result


def run_real_lifecycle(
    base: str,
    *,
    skip_real_pr: bool,
    bootstrap_patch: Path | None = None,
) -> dict[str, Any]:
    """Scenario 1: full ACW lifecycle with real patch and optional real PR."""
    case: dict[str, Any] = {"id": "real_lifecycle", "started_at": _now_iso()}
    t0 = time.monotonic()

    code, submit = _submit_acw(base, PRIMARY_OBJECTIVE, suffix="primary", bootstrap_patch=bootstrap_patch)
    case["submit"] = {"code": code, "status": submit.get("status"), "error": submit.get("detail")}
    if code != 200:
        case["passed"] = False
        case["duration_s"] = round(time.monotonic() - t0, 2)
        return case

    task_id = submit["task_id"]
    case["task_id"] = task_id
    case["submit_status"] = submit.get("status")
    case["status_transitions_observed"] = [submit.get("status")]

    if submit.get("status") != "waiting_for_approval":
        case["passed"] = False
        case["error"] = f"expected waiting_for_approval, got {submit.get('status')}"
        case["duration_s"] = round(time.monotonic() - t0, 2)
        return case

    case["artifacts_at_gate1"] = _verify_artifacts(base, task_id, submit)

    code, gate1 = _gate1(base, task_id)
    case["gate1"] = {"code": code, "status": gate1.get("status"), "approval_status": gate1.get("approval_status")}
    if code != 200:
        case["passed"] = False
        case["duration_s"] = round(time.monotonic() - t0, 2)
        return case

    case["status_transitions_observed"].append(gate1.get("status"))
    if gate1.get("approval_status") != "pending_pr":
        case["passed"] = False
        case["error"] = f"expected pending_pr after gate1, got {gate1.get('approval_status')}"
        case["duration_s"] = round(time.monotonic() - t0, 2)
        return case

    if skip_real_pr:
        case["passed"] = True
        case["note"] = "Gate 2 skipped (--skip-real-pr)"
        case["duration_s"] = round(time.monotonic() - t0, 2)
        return case

    code, gate2 = _gate2(base, task_id)
    case["gate2"] = {
        "code": code,
        "status": gate2.get("status"),
        "pr_url": (gate2.get("phase5") or {}).get("pr_url"),
    }
    case["status_transitions_observed"].append(gate2.get("status"))

    _, final = _get_detail(base, task_id)
    case["final"] = {
        "status": final.get("status"),
        "pr_url": (final.get("phase5") or {}).get("pr_url"),
        "branch_name": (final.get("phase5") or {}).get("branch_name"),
        "error": final.get("error"),
    }
    case["artifacts_final"] = _verify_artifacts(base, task_id, final)
    case["execution_log_entries"] = len(final.get("execution_log") or [])
    case["approvals"] = final.get("approvals") or []

    pr_url = case["final"].get("pr_url") or ""
    case["passed"] = (
        code == 200
        and final.get("status") == "completed"
        and bool(pr_url)
        and "github.com" in pr_url
        and case["artifacts_final"]["passed"]
    )
    case["duration_s"] = round(time.monotonic() - t0, 2)
    return case


def run_recovery_test(base: str, backend_cmd: list[str] | None, *, bootstrap_patch: Path | None = None) -> dict[str, Any]:
    """Scenario 3: submit task, restart backend, verify state + approvals."""
    case: dict[str, Any] = {"id": "restart_recovery", "started_at": _now_iso()}
    if not backend_cmd:
        case["passed"] = None
        case["skipped"] = True
        case["reason"] = "no --backend-restart-cmd provided"
        return case

    t0 = time.monotonic()
    code, submit = _submit_acw(base, PRIMARY_OBJECTIVE, suffix="recovery", bootstrap_patch=bootstrap_patch)
    if code != 200 or submit.get("status") != "waiting_for_approval":
        case["passed"] = False
        case["error"] = "submit failed before restart"
        return case

    task_id = submit["task_id"]
    case["task_id"] = task_id
    case["status_before_restart"] = submit.get("status")

    # Restart backend
    case["restart"] = {"cmd": backend_cmd}
    try:
        subprocess.run(backend_cmd, cwd=str(REPO_ROOT / "backend"), check=True, timeout=120)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        case["passed"] = False
        case["error"] = f"restart failed: {exc}"
        return case

    # Wait for backend ready
    ready = False
    for _ in range(60):
        time.sleep(2)
        c, _ = _http_json("GET", f"{base}/api/health/ready", timeout=10)
        if c == 200:
            ready = True
            break
    case["backend_ready_after_restart"] = ready
    if not ready:
        case["passed"] = False
        case["error"] = "backend not ready after restart"
        return case

    code, detail = _get_detail(base, task_id)
    case["detail_after_restart"] = {"code": code, "status": detail.get("status")}
    if code != 200 or detail.get("status") != "waiting_for_approval":
        case["passed"] = False
        case["error"] = "task state lost after restart"
        case["duration_s"] = round(time.monotonic() - t0, 2)
        return case

    code, gate1 = _gate1(base, task_id)
    case["gate1_after_restart"] = {"code": code, "status": gate1.get("status")}
    case["passed"] = code == 200 and gate1.get("approval_status") == "pending_pr"
    case["duration_s"] = round(time.monotonic() - t0, 2)
    return case


def run_concurrent_test(base: str, *, bootstrap_patch: Path | None = None) -> dict[str, Any]:
    """Scenario 4: 3 parallel ACW tasks — verify isolation."""
    case: dict[str, Any] = {"id": "concurrent_isolation", "started_at": _now_iso()}
    t0 = time.monotonic()
    tasks: list[dict[str, Any]] = []

    def _one(i: int) -> dict[str, Any]:
        code, detail = _submit_acw(base, PRIMARY_OBJECTIVE, suffix=f"concurrent-{i}", bootstrap_patch=bootstrap_patch)
        return {"index": i, "code": code, "task_id": detail.get("task_id"), "detail": detail}

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(_one, i) for i in range(1, 4)]
        for fut in as_completed(futures):
            tasks.append(fut.result())

    case["submissions"] = [
        {"index": t["index"], "code": t["code"], "task_id": t["task_id"], "status": t["detail"].get("status")}
        for t in tasks
    ]
    task_ids = [t["task_id"] for t in tasks if t.get("task_id")]
    case["unique_task_ids"] = len(set(task_ids)) == len(task_ids)

    contamination = False
    patch_hashes: dict[str, str] = {}
    for tid in task_ids:
        _, detail = _get_detail(base, tid)
        for art in detail.get("artifacts") or []:
            if (art.get("standard_name") or art.get("name")) == "patch.diff":
                preview = art.get("preview") or art.get("content_hash") or ""
                if tid in patch_hashes and patch_hashes[tid] != preview:
                    contamination = True
                patch_hashes[tid] = preview
        pkg = detail.get("approval_package") or {}
        if pkg.get("task_id") != tid:
            contamination = True

    case["patch_isolation"] = not contamination
    case["all_waiting"] = all(
        t["detail"].get("status") == "waiting_for_approval" for t in tasks if t["code"] == 200
    )
    case["passed"] = (
        len(task_ids) == 3
        and case["unique_task_ids"]
        and case["patch_isolation"]
        and case["all_waiting"]
    )
    case["duration_s"] = round(time.monotonic() - t0, 2)
    return case


def run_github_failure_test(base: str, *, bootstrap_patch: Path | None = None) -> dict[str, Any]:
    """Scenario 5: corrupt sandbox git remote after Gate 1, expect deterministic FAILED."""
    case: dict[str, Any] = {"id": "github_failure", "started_at": _now_iso()}
    t0 = time.monotonic()

    code, submit = _submit_acw(base, PRIMARY_OBJECTIVE, suffix="gh-failure", bootstrap_patch=bootstrap_patch)
    if code != 200 or submit.get("status") != "waiting_for_approval":
        case["passed"] = False
        case["error"] = "submit failed"
        return case

    task_id = submit["task_id"]
    case["task_id"] = task_id

    code, gate1 = _gate1(base, task_id)
    if code != 200 or gate1.get("status") != "waiting_for_pr_approval":
        case["passed"] = False
        case["error"] = f"gate1 failed: {gate1.get('detail') or gate1.get('status')}"
        return case

    # Corrupt sandbox workdir remote to force push failure
    sandbox = Path("/tmp/jarvis-sandbox") / task_id
    case["sandbox_path"] = str(sandbox)
    if sandbox.is_dir():
        config = sandbox / ".git" / "config"
        if config.is_file():
            original = config.read_text(encoding="utf-8")
            case["corrupted_remote"] = True
            config.write_text(
                original.replace("github.com", "invalid.github.example.invalid"),
                encoding="utf-8",
            )
        else:
            case["corrupted_remote"] = False
            case["note"] = "no .git/config in sandbox — push may fail differently"
    else:
        case["corrupted_remote"] = False
        case["note"] = f"sandbox not found at {sandbox}"

    code, gate2 = _gate2(base, task_id)
    _, final = _get_detail(base, task_id)
    case["gate2"] = {"code": code, "status": final.get("status"), "error": final.get("error")}
    case["remediation"] = _extract_remediation(final)

    # Cleanup sandbox
    if sandbox.is_dir():
        shutil.rmtree(sandbox, ignore_errors=True)

    case["passed"] = (
        final.get("status") == "failed"
        and bool(final.get("error"))
        and "push" in (final.get("error") or "").lower() or "gh" in (final.get("error") or "").lower() or "git" in (final.get("error") or "").lower() or "failed" in (final.get("error") or "").lower()
    )
    case["no_orphan"] = final.get("status") == "failed"
    case["duration_s"] = round(time.monotonic() - t0, 2)
    return case


def _extract_remediation(detail: dict[str, Any]) -> dict[str, Any]:
    error = detail.get("error") or ""
    phase5 = detail.get("phase5") or {}
    return {
        "error_message": error,
        "status": detail.get("status"),
        "pr_url": phase5.get("pr_url"),
        "gate2_approved": phase5.get("gate2_approved"),
        "actionable": bool(error),
    }


def run_observability_test(base: str, known_task_id: str | None) -> dict[str, Any]:
    """Scenario 6: Jarvis history + task detail lifecycle visibility."""
    case: dict[str, Any] = {"id": "observability", "started_at": _now_iso()}

    code, listing = _get_execution_list(base)
    tasks = listing.get("tasks") or []
    acw_tasks = [t for t in tasks if (t.get("plan") or {}).get("workflow_type") == "coding_workflow"]
    case["execution_list"] = {"code": code, "total": len(tasks), "acw_count": len(acw_tasks)}

    if known_task_id:
        code, detail = _get_execution_detail(base, known_task_id)
        case["execution_detail"] = {
            "code": code,
            "status": detail.get("status"),
            "has_execution_log": bool(detail.get("execution_log")),
            "log_entries": len(detail.get("execution_log") or []),
        }
        code2, cw = _get_detail(base, known_task_id)
        phase5 = cw.get("phase5") or {}
        case["coding_workflow_detail"] = {
            "code": code2,
            "status": cw.get("status"),
            "pr_url_visible": bool(phase5.get("pr_url")),
            "pr_url": phase5.get("pr_url"),
            "workflow_type": cw.get("workflow_type"),
        }

    case["passed"] = (
        case["execution_list"]["code"] == 200
        and case["execution_list"]["acw_count"] >= 1
        and (not known_task_id or case.get("execution_detail", {}).get("code") == 200)
    )
    return case


def _readiness_assessment(results: dict[str, Any]) -> dict[str, Any]:
    scenarios = results.get("scenarios") or {}
    checks = {
        "real_lifecycle": scenarios.get("real_lifecycle", {}).get("passed"),
        "artifact_integrity": scenarios.get("real_lifecycle", {}).get("artifacts_final", {}).get("passed")
        or scenarios.get("real_lifecycle", {}).get("artifacts_at_gate1", {}).get("passed"),
        "restart_recovery": scenarios.get("restart_recovery", {}).get("passed"),
        "concurrent_isolation": scenarios.get("concurrent_isolation", {}).get("passed"),
        "github_failure": scenarios.get("github_failure", {}).get("passed"),
        "observability": scenarios.get("observability", {}).get("passed"),
    }

    failures = [k for k, v in checks.items() if v is False]
    skips = [k for k, v in checks.items() if v is None]
    passed_count = sum(1 for v in checks.values() if v is True)

    if failures:
        verdict = "FAIL"
    elif passed_count >= 4 and not failures:
        verdict = "CONDITIONAL_PASS" if skips else "PASS"
    else:
        verdict = "FAIL"

    blockers: list[str] = []
    if not checks.get("real_lifecycle"):
        blockers.append("Real PR lifecycle did not complete — cursor bridge or GitHub integration blocked")
    if not checks.get("github_failure"):
        blockers.append("GitHub failure path not deterministic or missing remediation guidance")
    if not checks.get("concurrent_isolation"):
        blockers.append("Concurrent task isolation failed — artifact cross-contamination risk")
    if checks.get("restart_recovery") is False:
        blockers.append("Task state does not survive backend restart")

    return {
        "verdict": verdict,
        "checks": checks,
        "passed_count": passed_count,
        "failures": failures,
        "skips": skips,
        "blockers": blockers,
        "v2_priorities": [
            "Harden cursor bridge timeout/retry and partial-diff recovery",
            "Structured remediation objects on PR creation failure (not raw git stderr)",
            "Dedicated ACW observability dashboard with lifecycle timeline",
            "Automated sandbox cleanup and branch TTL policy",
            "Production promotion gate: deploy ACW routes + LAB profile separation",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="ACW E2E Real PR Validation (LAB only)")
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--skip-real-pr", action="store_true", help="Stop after Gate 1")
    parser.add_argument("--skip-restart", action="store_true")
    parser.add_argument("--skip-concurrent", action="store_true")
    parser.add_argument("--skip-failure", action="store_true")
    parser.add_argument(
        "--backend-restart-cmd",
        nargs="+",
        help="Shell command to restart backend between recovery test phases",
    )
    parser.add_argument(
        "--bootstrap-patch",
        type=Path,
        default=REPO_ROOT / "logs" / "acw_e2e" / "real_patch.diff",
        help="Use real on-disk patch via acw_lab_submit_patch.py (LAB when Cursor unavailable)",
    )
    parser.add_argument("--no-bootstrap-patch", action="store_true", help="Use HTTP submit (requires Cursor bridge)")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    bootstrap = None if args.no_bootstrap_patch else args.bootstrap_patch
    if bootstrap is not None and not bootstrap.is_file():
        bootstrap = None

    base = args.base_url.rstrip("/")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = args.output or REPORT_DIR / f"acw_e2e_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"

    report: dict[str, Any] = {
        "report_type": "acw_e2e_validation",
        "environment": "LAB",
        "started_at": _now_iso(),
        "base_url": base,
        "constraints": {
            "lab_only": True,
            "no_merge": True,
            "no_deploy": True,
        },
    }

    print(f"ACW E2E Validation — {base}")
    print("=" * 60)

    report["preflight"] = _check_preflight(base)
    print(f"Preflight: {'PASS' if report['preflight']['passed'] else 'FAIL'}")
    if not report["preflight"]["passed"]:
        print(json.dumps(report["preflight"], indent=2))
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Report: {report_path}")
        return 1

    scenarios: dict[str, Any] = {}

    print("\n[1/6] Real lifecycle...")
    scenarios["real_lifecycle"] = run_real_lifecycle(base, skip_real_pr=args.skip_real_pr, bootstrap_patch=bootstrap)
    print(f"  -> {'PASS' if scenarios['real_lifecycle'].get('passed') else 'FAIL'}")
    primary_task_id = scenarios["real_lifecycle"].get("task_id")

    print("\n[2/6] Artifact integrity (included in lifecycle)...")
    scenarios["artifact_integrity"] = {
        "passed": scenarios["real_lifecycle"].get("artifacts_final", {}).get("passed")
        or scenarios["real_lifecycle"].get("artifacts_at_gate1", {}).get("passed"),
        "detail": scenarios["real_lifecycle"].get("artifacts_final")
        or scenarios["real_lifecycle"].get("artifacts_at_gate1"),
    }
    print(f"  -> {'PASS' if scenarios['artifact_integrity']['passed'] else 'FAIL'}")

    if args.skip_restart:
        scenarios["restart_recovery"] = {"passed": None, "skipped": True}
        print("\n[3/6] Restart recovery — SKIPPED")
    else:
        print("\n[3/6] Restart recovery...")
        scenarios["restart_recovery"] = run_recovery_test(base, args.backend_restart_cmd, bootstrap_patch=bootstrap)
        print(f"  -> {'PASS' if scenarios['restart_recovery'].get('passed') else scenarios['restart_recovery'].get('skipped') and 'SKIP' or 'FAIL'}")

    if args.skip_concurrent:
        scenarios["concurrent_isolation"] = {"passed": None, "skipped": True}
        print("\n[4/6] Concurrent isolation — SKIPPED")
    else:
        print("\n[4/6] Concurrent isolation (3 tasks)...")
        scenarios["concurrent_isolation"] = run_concurrent_test(base, bootstrap_patch=bootstrap)
        print(f"  -> {'PASS' if scenarios['concurrent_isolation'].get('passed') else 'FAIL'}")

    if args.skip_failure:
        scenarios["github_failure"] = {"passed": None, "skipped": True}
        print("\n[5/6] GitHub failure — SKIPPED")
    else:
        print("\n[5/6] GitHub failure handling...")
        scenarios["github_failure"] = run_github_failure_test(base, bootstrap_patch=bootstrap)
        print(f"  -> {'PASS' if scenarios['github_failure'].get('passed') else 'FAIL'}")

    print("\n[6/6] Observability...")
    scenarios["observability"] = run_observability_test(base, primary_task_id)
    print(f"  -> {'PASS' if scenarios['observability'].get('passed') else 'FAIL'}")

    report["scenarios"] = scenarios
    report["lifecycle_diagram"] = {
        "expected_pipeline": list(ACW_PIPELINE),
        "primary_task_transitions": scenarios["real_lifecycle"].get("status_transitions_observed"),
        "primary_task_final_status": scenarios["real_lifecycle"].get("final", {}).get("status")
        or scenarios["real_lifecycle"].get("submit_status"),
    }
    report["readiness"] = _readiness_assessment(report)
    report["finished_at"] = _now_iso()

    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("\n" + "=" * 60)
    print(f"READINESS: {report['readiness']['verdict']}")
    print(f"Report: {report_path}")
    if report["readiness"]["blockers"]:
        print("Blockers:")
        for b in report["readiness"]["blockers"]:
            print(f"  - {b}")

    return 0 if report["readiness"]["verdict"] in ("PASS", "CONDITIONAL_PASS") else 1


if __name__ == "__main__":
    sys.exit(main())
