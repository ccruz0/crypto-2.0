#!/usr/bin/env python3
"""Phase 4B read-only validation battery — real investigations with metrics.

Runs a fixed set of production diagnostic investigations, checks proposal
eligibility, and writes a JSON report with timing and quality heuristics.

Usage:
  python backend/scripts/diag/run_jarvis_phase4b_validation.py
  python backend/scripts/diag/run_jarvis_phase4b_validation.py --base-url http://127.0.0.1:8002
  python backend/scripts/diag/run_jarvis_phase4b_validation.py --skip-proposals
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# Battery aligned with Phase 4B launch validation (read-only, no writes).
VALIDATION_CASES: tuple[dict[str, str], ...] = (
    {"id": "open_orders", "category": "orders", "objective": "Why are open orders empty?"},
    {
        "id": "portfolio_reconcile",
        "category": "portfolio",
        "objective": "Why is portfolio equity derived instead of exchange-reported?",
    },
    {"id": "websocket_stale", "category": "websocket", "objective": "Why are websocket prices stale?"},
    {"id": "deploy_unhealthy", "category": "deployment", "objective": "Why is deployment unhealthy?"},
    {
        "id": "docker_containers",
        "category": "deployment",
        "objective": "Investigate Docker container health and recent errors (read-only)",
    },
    {
        "id": "log_analysis",
        "category": "api",
        "objective": "Analyze recent backend error logs for recurring failures (read-only)",
    },
    {
        "id": "repository_analysis",
        "category": "api",
        "objective": "Investigate Jarvis architecture and open orders code paths in repository (read-only)",
    },
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _http_json(method: str, url: str, body: dict[str, Any] | None = None, timeout: float = 180.0) -> tuple[int, dict[str, Any]]:
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


def _score_investigation(result: dict[str, Any]) -> dict[str, Any]:
    """Heuristic quality scoring (0–100) without LLM cost."""
    evidence = result.get("evidence") or []
    root_causes = result.get("ranked_causes") or result.get("ranked_root_causes") or result.get("root_causes") or []
    status = str(result.get("status") or "")
    confidence = float(result.get("confidence") or 0)

    evidence_count = result.get("evidence_count") or len(evidence)
    evidence_score = min(40, evidence_count * 5)
    cause_score = min(30, len(root_causes) * 10 + (10 if result.get("root_cause") else 0))
    status_score = 30 if status == "completed" else (15 if status == "partial_failure" else 0)
    confidence_score = min(20, confidence / 5.0)

    false_positive_risk = "low"
    if status in ("failed", "insufficient_evidence"):
        false_positive_risk = "high"
    elif not root_causes and evidence_count < 2:
        false_positive_risk = "medium"

    total = evidence_score + cause_score + status_score + confidence_score
    return {
        "quality_score": min(100, int(total)),
        "evidence_count": evidence_count,
        "root_cause_count": len(root_causes),
        "confidence": confidence,
        "false_positive_risk": false_positive_risk,
    }


def _estimate_cost_usd(duration_s: float) -> float:
    """Rough infra-only cost proxy (no LLM calls in Phase 4A investigations)."""
    # EC2 backend-aws ~2GB RAM, ~$0.05/hr amortized → negligible per investigation
    hourly = 0.05
    return round((duration_s / 3600.0) * hourly, 6)


def run_battery(
    *,
    base_url: str,
    skip_proposals: bool,
    timeout_s: float,
) -> dict[str, Any]:
    base = base_url.rstrip("/")
    started = _now_iso()
    cases_out: list[dict[str, Any]] = []
    total_duration = 0.0

    # Pre-flight: safety gates + repository graph
    _, safety = _http_json("GET", f"{base}/api/jarvis/safety-status", timeout=30)
    graph_t0 = time.monotonic()
    _, graph_meta = _http_json("GET", f"{base}/api/jarvis/repository/graph", timeout=120)
    graph_duration = time.monotonic() - graph_t0
    graph = graph_meta.get("graph") or {}
    index_summary = (graph_meta.get("report") or {}).get("index_summary") or graph.get("metadata", {}).get("index_summary", {})

    for case in VALIDATION_CASES:
        case_t0 = time.monotonic()
        case_result: dict[str, Any] = {
            "id": case["id"],
            "category": case["category"],
            "objective": case["objective"],
        }
        status_code, inv = _http_json(
            "POST",
            f"{base}/api/jarvis/investigations/run",
            {"objective": case["objective"]},
            timeout=timeout_s,
        )
        duration_s = round(time.monotonic() - case_t0, 2)
        total_duration += duration_s
        case_result["http_status"] = status_code
        case_result["duration_s"] = duration_s
        case_result["estimated_cost_usd"] = _estimate_cost_usd(duration_s)

        if status_code != 200:
            case_result["status"] = "api_error"
            case_result["error"] = inv.get("detail") or inv
            cases_out.append(case_result)
            continue

        inv_id = inv.get("investigation_id") or inv.get("id")
        case_result["investigation_id"] = inv_id
        case_result["investigation_status"] = inv.get("status")
        case_result["template_id"] = inv.get("template_id")

        # Detail endpoint includes evidence_count, ranked_causes, confidence
        if inv_id:
            _, detail = _http_json("GET", f"{base}/api/jarvis/investigations/{inv_id}", timeout=60)
            if detail.get("investigation_id"):
                inv = detail
        case_result["quality"] = _score_investigation(inv)
        case_result["confidence"] = inv.get("confidence")
        case_result["root_cause"] = inv.get("root_cause")
        case_result["evidence_count"] = inv.get("evidence_count") or len(inv.get("evidence") or [])

        # Proposal eligibility (Phase 4B read-only)
        if inv_id and not skip_proposals:
            _, elig = _http_json("GET", f"{base}/api/jarvis/proposals/eligibility/{inv_id}", timeout=60)
            case_result["proposal_eligibility"] = {
                "eligible": elig.get("eligible"),
                "primary_template": elig.get("primary_template"),
                "reasons": elig.get("reasons") or elig.get("ineligibility_reasons"),
                "confidence": elig.get("confidence"),
            }
            if elig.get("eligible"):
                prop_t0 = time.monotonic()
                prop_status, prop = _http_json(
                    "POST",
                    f"{base}/api/jarvis/investigations/{inv_id}/propose-patch",
                    timeout=timeout_s,
                )
                case_result["proposal"] = {
                    "http_status": prop_status,
                    "duration_s": round(time.monotonic() - prop_t0, 2),
                    "proposal_status": prop.get("proposal_status") or prop.get("status"),
                    "approval_required": prop.get("approval_required"),
                    "task_id": prop.get("task_id"),
                }
                total_duration += case_result["proposal"]["duration_s"]

        cases_out.append(case_result)

    completed = sum(1 for c in cases_out if c.get("investigation_status") == "completed")
    avg_quality = round(
        sum(c.get("quality", {}).get("quality_score", 0) for c in cases_out) / max(len(cases_out), 1),
        1,
    )

    return {
        "battery": "jarvis_phase4b_readonly",
        "started_at": started,
        "finished_at": _now_iso(),
        "base_url": base,
        "safety_status": safety,
        "repository_graph": {
            "node_count": graph.get("node_count", 0),
            "edge_count": graph.get("edge_count", 0),
            "fetch_duration_s": round(graph_duration, 2),
            "index_summary": index_summary,
            "repo_root": (graph_meta.get("report") or {}).get("repo_root"),
            "workflows": len((graph_meta.get("report") or {}).get("workflows") or []),
        },
        "summary": {
            "cases_total": len(cases_out),
            "cases_completed": completed,
            "cases_failed": sum(1 for c in cases_out if c.get("investigation_status") not in ("completed", "partial_failure", None)),
            "total_duration_s": round(total_duration, 2),
            "avg_quality_score": avg_quality,
            "estimated_total_cost_usd": round(sum(c.get("estimated_cost_usd", 0) for c in cases_out), 6),
            "phase4b_proposals_enabled": (safety.get("phase4b") or {}).get("phase4b_proposals_enabled"),
            "phase5_write_gates_open": any(
                (safety.get("phase5") or {}).get(k)
                for k in ("patch_apply_enabled", "pr_creation_enabled", "github_write_enabled")
            ),
        },
        "cases": cases_out,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Jarvis Phase 4B read-only validation battery")
    parser.add_argument("--base-url", default="http://127.0.0.1:8002", help="Jarvis API base URL")
    parser.add_argument("--skip-proposals", action="store_true", help="Skip propose-patch step")
    parser.add_argument("--timeout", type=float, default=180.0, help="Per-request timeout seconds")
    parser.add_argument(
        "--output",
        default="",
        help="Write JSON report to this path (default: logs/jarvis_phase4b_validation_<ts>.json)",
    )
    args = parser.parse_args()

    report = run_battery(
        base_url=args.base_url,
        skip_proposals=args.skip_proposals,
        timeout_s=args.timeout,
    )

    out_path = args.output
    if not out_path:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_dir = Path("logs")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = str(out_dir / f"jarvis_phase4b_validation_{ts}.json")

    Path(out_path).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print(f"\nFull report: {out_path}")

    if report["summary"]["cases_completed"] < len(VALIDATION_CASES) // 2:
        return 1
    if report["repository_graph"]["node_count"] <= 0:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
