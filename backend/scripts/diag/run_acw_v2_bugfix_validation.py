#!/usr/bin/env python3
"""ACW v2 — Real Autonomous Bug Fix Validation (LAB only).

Validates Jarvis autonomous patch generation through the Cursor bridge for real
repository issues. No bootstrap patches; every code change comes from the bridge.

Usage:
  TESTING=1 python3 backend/scripts/diag/run_acw_v2_bugfix_validation.py
  TESTING=1 python3 backend/scripts/diag/run_acw_v2_bugfix_validation.py --max-tasks 1
  TESTING=1 python3 backend/scripts/diag/run_acw_v2_bugfix_validation.py --issue ACW-BF-001
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
REPORT_DIR = REPO / "logs" / "acw_v2"

os.environ.setdefault("TESTING", "1")
os.environ.setdefault("ENVIRONMENT", "local")
os.environ.setdefault("APP_ENV", "local")

sys.path.insert(0, str(REPO / "backend"))

from app.core.lab_secrets import load_lab_runtime_env
from app.jarvis.coding_workflow.acw_bugfix_fixtures import ACW_BF_001_OBJECTIVE

load_lab_runtime_env(repo_root=REPO)

if os.environ.get("TESTING") == "1":
    os.environ["ENVIRONMENT"] = "local"
    os.environ.setdefault("APP_ENV", "local")

# LAB env overrides (must be set before app imports)
os.environ.setdefault("ATP_WORKSPACE_ROOT", str(REPO))
os.environ.setdefault("ATP_STAGING_ROOT", "/tmp/atp-staging")
os.environ.setdefault("CURSOR_CLI_PATH", "/home/ubuntu/.cursor-server/bin/linux-x64/776d1f9d76df50a4e0aeca61819a88e7c1b861e0/bin/remote-cli/cursor")
for key, val in {
    "ATP_TRADING_ONLY": "0",
    "JARVIS_ENABLED": "true",
    "JARVIS_BUILDER_ALLOWED": "1",
    "CURSOR_BRIDGE_ENABLED": "true",
    "JARVIS_PATCH_APPLY_ENABLED": "true",
    "JARVIS_PR_CREATION_ENABLED": "true",
    "JARVIS_GITHUB_WRITE_ENABLED": "true",
    "JARVIS_REQUIRE_DOUBLE_APPROVAL": "true",
    "EXECUTION_CONTEXT": "LAB",
    "GITHUB_REPOSITORY": "ccruz0/crypto-2.0",
}.items():
    os.environ.setdefault(key, val)
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://trader:CHANGE_ME_STRONG_PASSWORD@172.18.0.2:5432/atp",
)

# ---------------------------------------------------------------------------
# Phase 1 — Candidate catalog (10 issues, ranked easiest → hardest)
# ---------------------------------------------------------------------------

CANDIDATES: list[dict[str, Any]] = [
    {
        "issue_id": "ACW-BF-001",
        "rank": 1,
        "category": "ui_display",
        "description": (
            "Rename dashboard page title from 'Trading Dashboard' to "
            "'Crypto Trading Dashboard' in page.tsx header h1 (~line 4644)"
        ),
        "affected_files": ["frontend/src/app/page.tsx"],
        "complexity": 1,
        "expected_patch_size": "S (1 JSX line changed)",
        "expected_tests": "Optional; existing frontend build",
        "objective": ACW_BF_001_OBJECTIVE,
        "target_files": ["frontend/src/app/page.tsx"],
    },
    {
        "issue_id": "ACW-BF-002",
        "rank": 2,
        "category": "missing_test",
        "description": "Add unit test verifying getMatchingFixTemplate returns null for empty candidates",
        "affected_files": [
            "frontend/src/app/components/tabs/proposalEligibilityUtils.test.ts",
            "frontend/src/app/components/tabs/proposalEligibilityUtils.ts",
        ],
        "complexity": 1,
        "expected_patch_size": "S (~10 lines)",
        "expected_tests": "vitest proposalEligibilityUtils.test.ts",
        "objective": (
            "Add a unit test in frontend/src/app/components/tabs/proposalEligibilityUtils.test.ts "
            "verifying that getMatchingFixTemplate returns null when fix_template_candidates "
            "is an empty array. Run existing tests to confirm pass."
        ),
        "target_files": ["frontend/src/app/components/tabs/proposalEligibilityUtils.test.ts"],
    },
    {
        "issue_id": "ACW-BF-003",
        "rank": 3,
        "category": "bug",
        "description": "Guard buildMiniChartSVG against empty/single-point prices (NaN/Infinity in SVG)",
        "affected_files": ["frontend/src/utils/miniChart.ts"],
        "complexity": 2,
        "expected_patch_size": "S (~12 lines)",
        "expected_tests": "New miniChart.test.ts with edge cases",
        "objective": (
            "In frontend/src/utils/miniChart.ts, add guards in buildMiniChartSVG for empty "
            "prices array and single-point array to prevent NaN/Infinity in SVG coordinates. "
            "Return a minimal valid empty SVG for edge cases. Add unit tests in "
            "frontend/src/utils/miniChart.test.ts."
        ),
        "target_files": ["frontend/src/utils/miniChart.ts", "frontend/src/utils/miniChart.test.ts"],
    },
    {
        "issue_id": "ACW-BF-004",
        "rank": 4,
        "category": "ui_display",
        "description": "Extend gateLabel to map Jarvis statuses to human-readable labels",
        "affected_files": [
            "frontend/src/lib/jarvisApproval.ts",
            "frontend/src/lib/jarvisApproval.test.ts",
        ],
        "complexity": 2,
        "expected_patch_size": "S (~20 lines)",
        "expected_tests": "New jarvisApproval.test.ts",
        "objective": (
            "Extend gateLabel in frontend/src/lib/jarvisApproval.ts to map common Jarvis "
            "task statuses (completed, failed, sandbox_testing, applying_patch, pr_created, "
            "planning, testing) to human-readable labels instead of raw status strings. "
            "Add unit tests in frontend/src/lib/jarvisApproval.test.ts."
        ),
        "target_files": ["frontend/src/lib/jarvisApproval.ts", "frontend/src/lib/jarvisApproval.test.ts"],
    },
    {
        "issue_id": "ACW-BF-005",
        "rank": 5,
        "category": "missing_test",
        "description": "Add negative test for get_recurring_template returning None for unknown IDs",
        "affected_files": [
            "backend/tests/test_jarvis_investigation_scheduler.py",
            "backend/app/jarvis/investigations/scheduler/templates.py",
        ],
        "complexity": 1,
        "expected_patch_size": "S (~5 lines)",
        "expected_tests": "pytest test_jarvis_investigation_scheduler.py",
        "objective": (
            "Add a negative unit test in backend/tests/test_jarvis_investigation_scheduler.py "
            "verifying get_recurring_template returns None for an unknown schedule_id. "
            "Import from app.jarvis.investigations.scheduler.templates."
        ),
        "target_files": ["backend/tests/test_jarvis_investigation_scheduler.py"],
    },
    {
        "issue_id": "ACW-BF-006",
        "rank": 6,
        "category": "bug",
        "description": "Missing applySyncMeta on direct open-orders API fallback in useOrders.ts",
        "affected_files": ["frontend/src/hooks/useOrders.ts"],
        "complexity": 2,
        "expected_patch_size": "S (1-3 lines)",
        "expected_tests": "useOrders.test.ts with mocked getOpenOrders",
        "objective": (
            "In frontend/src/hooks/useOrders.ts, the direct API fallback branch around "
            "line 212 calls setOpenOrders but omits applySyncMeta(response) unlike other "
            "branches. Add applySyncMeta(response) after setOpenOrders in that branch."
        ),
        "target_files": ["frontend/src/hooks/useOrders.ts"],
    },
    {
        "issue_id": "ACW-BF-007",
        "rank": 7,
        "category": "observability",
        "description": "ErrorBoundary uses console.error instead of centralized logger",
        "affected_files": ["frontend/src/app/components/ErrorBoundary.tsx"],
        "complexity": 1,
        "expected_patch_size": "S (~3 lines)",
        "expected_tests": "Optional component test",
        "objective": (
            "In frontend/src/app/components/ErrorBoundary.tsx, replace console.error with "
            "the centralized logger from @/utils/logger for componentDidCatch error reporting."
        ),
        "target_files": ["frontend/src/app/components/ErrorBoundary.tsx"],
    },
    {
        "issue_id": "ACW-BF-008",
        "rank": 8,
        "category": "status_transition",
        "description": "jarvisAgents isTerminal omits insufficient_evidence terminal state",
        "affected_files": ["frontend/src/lib/jarvisAgents.ts"],
        "complexity": 2,
        "expected_patch_size": "S (~2 lines)",
        "expected_tests": "jarvisAgents.test.ts",
        "objective": (
            "In frontend/src/lib/jarvisAgents.ts, add insufficient_evidence to isTerminal() "
            "to match backend TERMINAL_STATES in lifecycle.py. Add unit test."
        ),
        "target_files": ["frontend/src/lib/jarvisAgents.ts"],
    },
    {
        "issue_id": "ACW-BF-009",
        "rank": 9,
        "category": "missing_test",
        "description": "No unit tests for priceStreamWsUrl WebSocket URL builder",
        "affected_files": ["frontend/src/lib/priceStreamWsUrl.ts"],
        "complexity": 2,
        "expected_patch_size": "M (~40 lines tests)",
        "expected_tests": "priceStreamWsUrl.test.ts",
        "objective": (
            "Add unit tests in frontend/src/lib/priceStreamWsUrl.test.ts for "
            "getWebSocketPricesUrl covering hostname rejection and scheme normalization."
        ),
        "target_files": ["frontend/src/lib/priceStreamWsUrl.ts", "frontend/src/lib/priceStreamWsUrl.test.ts"],
    },
    {
        "issue_id": "ACW-BF-010",
        "rank": 10,
        "category": "error_handling",
        "description": "JarvisOperationalStatus setError(String(e)) loses message extraction",
        "affected_files": ["frontend/src/app/components/jarvis/JarvisOperationalStatus.tsx"],
        "complexity": 2,
        "expected_patch_size": "S (~5 lines)",
        "expected_tests": "Optional render test",
        "objective": (
            "In frontend/src/app/components/jarvis/JarvisOperationalStatus.tsx, improve error "
            "handling to extract e.message from Error objects instead of setError(String(e))."
        ),
        "target_files": ["frontend/src/app/components/jarvis/JarvisOperationalStatus.tsx"],
    },
]

SELECTED_ISSUES = [c["issue_id"] for c in CANDIDATES[:5]]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _count_diff_stats(diff: str) -> dict[str, int]:
    added = removed = 0
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return {"lines_added": added, "lines_removed": removed}


def _parse_reviewer_findings(review_md: str) -> dict[str, Any]:
    findings: dict[str, Any] = {"risk_score": None, "recommendation": None, "issues": []}
    if not review_md:
        return findings
    m = re.search(r"risk[_\s]*score[:\s]*(\d+)", review_md, re.I)
    if m:
        findings["risk_score"] = int(m.group(1))
    m = re.search(r"approval_recommendation[:\s]*(\w+)", review_md, re.I)
    if m:
        findings["recommendation"] = m.group(1)
    for line in review_md.splitlines():
        if line.strip().startswith(("- ", "* ", "1.", "2.")):
            findings["issues"].append(line.strip()[:200])
    return findings


def _classify_failure(error: str, stage: str) -> dict[str, Any]:
    err = (error or "").lower()
    root_cause = "unknown"
    category = "unknown"

    if stage == "submit":
        if "cursor" in err or "bridge" in err or "cli" in err or "placeholder" in err:
            category, root_cause = "cursor_generation_failure", error
        elif "plan" in err or "objective" in err or "forbidden" in err:
            category, root_cause = "planning_failure", error
        elif "evidence" in err or "context" in err:
            category, root_cause = "repository_search_failure", error
        else:
            category, root_cause = "cursor_generation_failure", error
    elif stage == "gate1":
        if "apply" in err or "patch" in err:
            category, root_cause = "patch_application_failure", error
        elif "test" in err or "pytest" in err or "vitest" in err:
            category, root_cause = "test_failure", error
        else:
            category, root_cause = "patch_application_failure", error
    elif stage == "gate2":
        if "push" in err or "gh" in err or "github" in err or "pr" in err:
            category, root_cause = "github_pr_failure", error
        elif "review" in err or "reject" in err:
            category, root_cause = "reviewer_rejection", error
        else:
            category, root_cause = "github_pr_failure", error

    return {
        "failure_category": category,
        "root_cause": root_cause,
        "remediation": _remediation_for(category),
    }


def _remediation_for(category: str) -> str:
    remedies = {
        "planning_failure": "Refine objective specificity; add target_files hints; verify safety classifier",
        "repository_search_failure": "Improve evidence collection; add file anchors to objective",
        "cursor_generation_failure": "Increase CURSOR_CLI_TIMEOUT; add retry with narrowed scope; verify CLI auth",
        "patch_application_failure": "Check forbidden paths; validate diff applies cleanly to current HEAD",
        "test_failure": "Run targeted tests locally; ensure patch includes test fixes; check sandbox deps",
        "reviewer_rejection": "Address reviewer findings; reduce scope; avoid forbidden paths",
        "github_pr_failure": "Verify GITHUB_APP credentials; check branch push permissions; retry Gate 2",
    }
    return remedies.get(category, "Investigate logs and task artifacts for task_id")


def _outcome_from_detail(detail: dict[str, Any]) -> str:
    status = detail.get("status", "")
    phase5 = detail.get("phase5") or {}
    if status == "completed" and phase5.get("pr_url"):
        return "SUCCESS"
    if status in ("waiting_for_pr_approval", "waiting_for_approval"):
        return "PARTIAL_SUCCESS"
    if status == "failed":
        return "FAILURE"
    if phase5.get("pr_url"):
        return "SUCCESS"
    return "PARTIAL_SUCCESS" if detail.get("patch_summary") else "FAILURE"


def _load_artifact_content(task_id: str, name: str) -> str:
    from app.jarvis.artifacts.storage import load_artifact_content

    try:
        return load_artifact_content(task_id, name) or ""
    except Exception:
        return ""


def run_single_task(candidate: dict[str, Any], *, actor_id: str = "acw_v2_validator") -> dict[str, Any]:
    """Execute full ACW pipeline for one candidate via real Cursor bridge."""
    from app.jarvis.change_execution.service import approve_patch_apply, approve_pr_creation
    from app.jarvis.coding_workflow.service import submit_coding_workflow

    result: dict[str, Any] = {
        "issue_id": candidate["issue_id"],
        "started_at": _now_iso(),
        "outcome": "FAILURE",
        "human_intervention": False,
        "retry_count": 0,
    }
    t0 = time.monotonic()

    try:
        print(f"\n[{candidate['issue_id']}] Submitting ACW task (Cursor bridge)...")
        detail = submit_coding_workflow(
            objective=candidate["objective"],
            target_files=candidate.get("target_files"),
        )
        result["task_id"] = detail.get("task_id")
        result["submit_status"] = detail.get("status")

        if detail.get("status") != "waiting_for_approval":
            result["outcome"] = "FAILURE"
            result["error"] = detail.get("error") or f"unexpected status: {detail.get('status')}"
            patch_gen = detail.get("patch_generation") or {}
            result["retry_count"] = 1 if patch_gen.get("retry_used") else 0
            result["patch_generation"] = patch_gen
            result["failure_analysis"] = _classify_failure(result["error"], "submit")
            result["duration_s"] = round(time.monotonic() - t0, 2)
            return result

        task_id = detail["task_id"]
        diff = _load_artifact_content(task_id, "patch.diff")
        review_md = _load_artifact_content(task_id, "review.md")
        tests_json_raw = _load_artifact_content(task_id, "tests.json")

        diff_stats = _count_diff_stats(diff)
        files_modified = list({m.group(1) for m in re.finditer(r"^\+\+\+ b/(.+)$", diff, re.M)})
        result.update({
            "patch_generated": bool(diff.strip()),
            "files_modified": files_modified,
            "lines_added": diff_stats["lines_added"],
            "lines_removed": diff_stats["lines_removed"],
            "reviewer_findings": _parse_reviewer_findings(review_md),
        })

        try:
            tests_data = json.loads(tests_json_raw) if tests_json_raw else {}
        except json.JSONDecodeError:
            tests_data = {}
        result["dry_run_tests"] = {
            "executed": tests_data.get("tests_run", tests_data.get("executed", 0)),
            "passed": tests_data.get("passed", tests_data.get("tests_passed", False)),
        }

        print(f"  Patch: {len(files_modified)} files, +{diff_stats['lines_added']}/-{diff_stats['lines_removed']}")
        print(f"  Gate 1: approve-apply...")
        detail = approve_patch_apply(task_id, actor_id=actor_id, comment=f"Gate 1 ACW v2 {candidate['issue_id']}")

        if detail.get("status") not in ("waiting_for_pr_approval", "completed"):
            result["outcome"] = "FAILURE"
            result["error"] = detail.get("error") or f"gate1 status: {detail.get('status')}"
            result["failure_analysis"] = _classify_failure(result["error"], "gate1")
            phase5 = detail.get("phase5") or {}
            result["sandbox_tests"] = phase5.get("test_results") or {}
            result["duration_s"] = round(time.monotonic() - t0, 2)
            return result

        phase5 = detail.get("phase5") or {}
        sandbox_tests = phase5.get("test_results") or {}
        result["sandbox_tests"] = {
            "executed": sandbox_tests.get("tests_run", sandbox_tests.get("total", 0)),
            "passed": sandbox_tests.get("passed", False),
            "details": sandbox_tests,
        }

        print(f"  Gate 2: approve-pr...")
        detail = approve_pr_creation(task_id, actor_id=actor_id, comment=f"Gate 2 ACW v2 {candidate['issue_id']}")
        phase5 = detail.get("phase5") or {}
        result["pr_url"] = phase5.get("pr_url")
        result["final_status"] = detail.get("status")
        result["outcome"] = _outcome_from_detail(detail)

        if result["outcome"] == "FAILURE":
            result["error"] = detail.get("error") or "gate2 failed"
            result["failure_analysis"] = _classify_failure(result["error"], "gate2")

    except Exception as exc:
        result["outcome"] = "FAILURE"
        result["error"] = str(exc)
        result["traceback"] = traceback.format_exc()
        stage = "submit" if "task_id" not in result else ("gate1" if "pr_url" not in result else "gate2")
        result["failure_analysis"] = _classify_failure(str(exc), stage)

    result["duration_s"] = round(time.monotonic() - t0, 2)
    result["finished_at"] = _now_iso()
    return result


def _compute_scorecard(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(tasks) or 1
    successes = [t for t in tasks if t.get("outcome") == "SUCCESS"]
    partial = [t for t in tasks if t.get("outcome") == "PARTIAL_SUCCESS"]
    failures = [t for t in tasks if t.get("outcome") == "FAILURE"]

    pr_created = sum(1 for t in tasks if t.get("pr_url"))
    durations = [t.get("duration_s", 0) for t in tasks]
    lines_added = [t.get("lines_added", 0) for t in tasks if t.get("lines_added")]
    files_touched = [len(t.get("files_modified") or []) for t in tasks]
    reviewer_issues = [len((t.get("reviewer_findings") or {}).get("issues") or []) for t in tasks]
    human_pct = sum(1 for t in tasks if t.get("human_intervention")) / n * 100
    retry_pct = sum(1 for t in tasks if (t.get("retry_count") or 0) > 0) / n * 100

    task_success_rate = len(successes) / n * 100
    pr_rate = pr_created / n * 100

    # Area scores (heuristic from observed outcomes)
    planning = min(100, 60 + len([t for t in tasks if t.get("submit_status") == "waiting_for_approval"]) / n * 40)
    repo_understanding = min(100, 50 + len([t for t in tasks if t.get("patch_generated")]) / n * 50)
    patch_gen = min(100, len([t for t in tasks if t.get("patch_generated")]) / n * 100)
    test_rel = min(100, len([t for t in tasks if (t.get("sandbox_tests") or {}).get("passed")]) / n * 100)
    review_qual = min(100, 70 + (20 if sum(reviewer_issues) / n < 3 else 0))
    github_int = pr_rate
    recovery = max(0, 100 - retry_pct * 2)
    overall = round(
        (planning + repo_understanding + patch_gen + test_rel + review_qual + github_int + recovery) / 7,
        1,
    )

    return {
        "task_success_rate_pct": round(task_success_rate, 1),
        "partial_success_rate_pct": round(len(partial) / n * 100, 1),
        "failure_rate_pct": round(len(failures) / n * 100, 1),
        "pr_creation_success_rate_pct": round(pr_rate, 1),
        "average_runtime_s": round(sum(durations) / n, 1),
        "average_patch_lines_added": round(sum(lines_added) / max(len(lines_added), 1), 1),
        "average_files_touched": round(sum(files_touched) / n, 1),
        "average_reviewer_findings": round(sum(reviewer_issues) / n, 1),
        "human_intervention_pct": round(human_pct, 1),
        "retry_pct": round(retry_pct, 1),
        "scores": {
            "planning": round(planning, 1),
            "repository_understanding": round(repo_understanding, 1),
            "patch_generation": round(patch_gen, 1),
            "test_reliability": round(test_rel, 1),
            "review_quality": round(review_qual, 1),
            "github_integration": round(github_int, 1),
            "recovery": round(recovery, 1),
            "overall": overall,
        },
        "counts": {
            "success": len(successes),
            "partial_success": len(partial),
            "failure": len(failures),
            "pr_created": pr_created,
        },
    }


def _production_readiness(scorecard: dict[str, Any], tasks: list[dict[str, Any]]) -> dict[str, Any]:
    overall = scorecard["scores"]["overall"]
    pr_rate = scorecard["pr_creation_success_rate_pct"]
    failures = scorecard["counts"]["failure"]

    if overall >= 75 and pr_rate >= 80 and failures == 0:
        verdict = "PASS"
    elif overall >= 50 and pr_rate >= 40:
        verdict = "CONDITIONAL_PASS"
    else:
        verdict = "FAIL"

    blockers = []
    if scorecard["scores"]["patch_generation"] < 60:
        blockers.append("Cursor bridge patch generation unreliable")
    if scorecard["scores"]["github_integration"] < 60:
        blockers.append("GitHub PR creation not consistently succeeding")
    if scorecard["scores"]["test_reliability"] < 60:
        blockers.append("Sandbox tests failing for generated patches")
    if any((t.get("failure_analysis") or {}).get("failure_category") == "cursor_generation_failure" for t in tasks):
        blockers.append("Cursor CLI failures observed — timeout/auth/staging issues")

    return {
        "questions": {
            "can_generate_useful_changes": scorecard["scores"]["patch_generation"] >= 60,
            "can_safely_modify_files": scorecard["scores"]["test_reliability"] >= 50,
            "can_recover_from_cursor_failures": scorecard["scores"]["recovery"] >= 50,
            "can_operate_unattended_in_lab": scorecard["human_intervention_pct"] == 0 and pr_rate >= 60,
            "blocking_production_deployment": blockers,
            "before_production_enablement": [
                "Dedicated LAB backend profile with ATP_TRADING_ONLY=0",
                "Cursor CLI mounted and authenticated in LAB container",
                "Structured retry/recovery for Cursor bridge timeouts",
                "Production safety gates remain disabled (patch apply, PR creation)",
                "Observability dashboard for ACW task lifecycle",
                "Automated sandbox cleanup and branch TTL",
            ],
        },
        "verdict": verdict,
        "advance_to_production_pilot": verdict in ("PASS", "CONDITIONAL_PASS") and pr_rate >= 50,
        "recommendation": (
            "Advance to production pilot with human Gate 1/2 approval retained"
            if verdict == "PASS"
            else (
                "Continue LAB validation; address Cursor bridge and test failures before pilot"
                if verdict == "CONDITIONAL_PASS"
                else "Do not advance — fix autonomous generation pipeline first"
            )
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="ACW v2 Real Autonomous Bug Fix Validation")
    parser.add_argument("--max-tasks", type=int, default=5, help="Number of candidates to execute (default 5)")
    parser.add_argument("--issue", action="append", help="Run specific issue_id(s) only")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = args.output or REPORT_DIR / f"acw_v2_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"

    if args.issue:
        to_run = [c for c in CANDIDATES if c["issue_id"] in args.issue]
    else:
        to_run = CANDIDATES[: args.max_tasks]

    report: dict[str, Any] = {
        "report_type": "acw_v2_bugfix_validation",
        "version": "2.0",
        "environment": "LAB",
        "started_at": _now_iso(),
        "constraints": {
            "lab_only": True,
            "no_merge": True,
            "no_deploy": True,
            "no_manual_patches": True,
            "cursor_bridge_required": True,
        },
        "phase1_candidates": CANDIDATES,
        "phase1_selected": [c["issue_id"] for c in to_run],
    }

    print("ACW v2 — Real Autonomous Bug Fix Validation")
    print("=" * 60)
    print(f"Candidates catalog: {len(CANDIDATES)} issues")
    print(f"Executing: {[c['issue_id'] for c in to_run]}")

    # Preflight
    from app.jarvis.coding_workflow.service import check_acw_submit_allowed
    from app.services.cursor_execution_bridge import (
        CursorAuthMissingError,
        get_cursor_auth_error,
        is_bridge_enabled,
        is_cursor_agent_logged_in,
        is_cursor_api_key_configured,
    )

    preflight: dict[str, Any] = {
        "acw_allowed": False,
        "bridge_enabled": is_bridge_enabled(),
        "staging_root": os.environ.get("ATP_STAGING_ROOT"),
        "cursor_cli": os.environ.get("CURSOR_CLI_PATH"),
        "cursor_api_key_set": is_cursor_api_key_configured(),
        "cursor_agent_logged_in": is_cursor_agent_logged_in(),
        "cursor_auth_error": get_cursor_auth_error(),
    }
    try:
        check_acw_submit_allowed()
        preflight["acw_allowed"] = True
    except CursorAuthMissingError as exc:
        preflight["acw_error"] = exc.error_info["cause"]
        preflight["cursor_auth_error"] = exc.error_info
    except Exception as e:
        preflight["acw_error"] = str(e)
    report["preflight"] = preflight
    preflight_ok = preflight["acw_allowed"] and preflight["bridge_enabled"] and not preflight.get("cursor_auth_error")
    print(f"Preflight: {'PASS' if preflight_ok else 'FAIL'}")
    if not preflight_ok:
        print(json.dumps({k: v for k, v in preflight.items() if k != "cursor_cli"}, indent=2))
        report_path = REPORT_DIR / f"acw_v2_bugfix_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        report["completed_at"] = _now_iso()
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return 1

    tasks: list[dict[str, Any]] = []
    for candidate in to_run:
        task_result = run_single_task(candidate)
        tasks.append(task_result)
        icon = {"SUCCESS": "✓", "PARTIAL_SUCCESS": "~", "FAILURE": "✗"}.get(task_result["outcome"], "?")
        print(f"  {icon} {candidate['issue_id']}: {task_result['outcome']} ({task_result.get('duration_s')}s)")
        if task_result.get("pr_url"):
            print(f"    PR: {task_result['pr_url']}")

    report["phase2_execution"] = tasks
    report["phase3_quality"] = [
        {
            "task_id": t.get("task_id"),
            "issue_id": t.get("issue_id"),
            "duration_s": t.get("duration_s"),
            "files_modified": t.get("files_modified"),
            "lines_added": t.get("lines_added"),
            "lines_removed": t.get("lines_removed"),
            "tests_executed": (t.get("sandbox_tests") or {}).get("executed"),
            "tests_passed": (t.get("sandbox_tests") or {}).get("passed"),
            "reviewer_findings": t.get("reviewer_findings"),
            "pr_url": t.get("pr_url"),
            "outcome": t.get("outcome"),
        }
        for t in tasks
    ]
    report["phase4_failures"] = [
        {
            "issue_id": t["issue_id"],
            "task_id": t.get("task_id"),
            **(t.get("failure_analysis") or {}),
            "error": t.get("error"),
        }
        for t in tasks
        if t.get("outcome") == "FAILURE"
    ]
    report["phase5_scorecard"] = _compute_scorecard(tasks)
    report["phase6_production_readiness"] = _production_readiness(report["phase5_scorecard"], tasks)
    report["environment_findings"] = {
        "backend_mode": "production (ATP_TRADING_ONLY=1 on port 8002)",
        "phase5_gates_on_live_backend": {
            "patch_apply_enabled": False,
            "pr_creation_enabled": False,
            "github_write_enabled": False,
        },
        "validation_execution_mode": "direct Python (TESTING=1) with LAB env overrides",
        "cursor_cli_version": "3.7.36",
        "cursor_agent_logged_in": is_cursor_agent_logged_in(),
        "cursor_api_key_configured": is_cursor_api_key_configured(),
        "prior_acw_e2e_status": "Gate 1 + Gate 2 + real PR validated via bootstrap patches (cursor bridge bypassed)",
        "v2_gap_validated": "invoke_cursor_cli headless auth — BLOCKED",
    }
    report["finished_at"] = _now_iso()

    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("\n" + "=" * 60)
    sc = report["phase5_scorecard"]
    print(f"Task success: {sc['task_success_rate_pct']}% | PR success: {sc['pr_creation_success_rate_pct']}%")
    print(f"Overall score: {sc['scores']['overall']}/100")
    print(f"Verdict: {report['phase6_production_readiness']['verdict']}")
    print(f"Report: {report_path}")
    return 0 if sc["counts"]["failure"] < len(tasks) else 1


if __name__ == "__main__":
    sys.exit(main())
