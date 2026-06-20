"""Read-only repository search agent for Jarvis tasks."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from app.services._paths import workspace_root


def search_files(pattern: str, *, max_results: int = 25) -> list[dict[str, str]]:
    """Search repository file contents (read-only, ripgrep if available)."""
    repo_root = workspace_root()
    limit = max(1, min(max_results, 100))
    hits: list[dict[str, str]] = []
    try:
        proc = subprocess.run(
            ["rg", "-n", "--no-heading", "--max-count", "3", pattern, str(repo_root)],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        for line in (proc.stdout or "").splitlines()[:limit]:
            parts = line.split(":", 2)
            if len(parts) >= 3:
                hits.append({"path": parts[0], "line": parts[1], "text": parts[2][:200]})
    except (OSError, subprocess.TimeoutExpired):
        hits = _fallback_search(pattern, limit, repo_root)
    return hits


def _fallback_search(pattern: str, limit: int, repo_root: Path) -> list[dict[str, str]]:
    regex = re.compile(re.escape(pattern), re.IGNORECASE)
    hits: list[dict[str, str]] = []
    skip = {".git", "node_modules", ".next", "__pycache__", ".archive", "proc", "sys", "dev", "run"}
    for path in repo_root.rglob("*"):
        if any(part in skip for part in path.parts):
            continue
        if not path.is_file() or path.suffix not in {".py", ".ts", ".tsx", ".sh", ".yml", ".md"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for idx, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                hits.append({"path": str(path.relative_to(repo_root)), "line": str(idx), "text": line[:200]})
                if len(hits) >= limit:
                    return hits
    return hits


def summarize_module(path: str) -> dict[str, Any]:
    repo_root = workspace_root()
    target = (repo_root / path).resolve()
    if not str(target).startswith(str(repo_root)) or not target.is_file():
        return {"path": path, "error": "file not found or outside repo", "read_only": True}
    lines = target.read_text(encoding="utf-8", errors="ignore").splitlines()
    return {
        "path": str(target.relative_to(repo_root)),
        "line_count": len(lines),
        "preview": "\n".join(lines[:40]),
        "read_only": True,
    }


def investigate_objective(objective: str) -> dict[str, Any]:
    """Run repository investigation for a natural-language objective."""
    objective_l = objective.lower()
    queries: list[str] = []
    if "websocket" in objective_l:
        queries.extend(["websocket", "ws_prices", "PriceStream"])
    if "openclaw" in objective_l:
        queries.append("openclaw")
    if "deploy" in objective_l or "deployment" in objective_l:
        queries.extend(["deploy", "prod_frontend_deploy", "docker compose"])
    if "jarvis" in objective_l or "architecture" in objective_l:
        queries.extend(["jarvis", "routes_jarvis"])
    if "open order" in objective_l or "open_orders" in objective_l:
        queries.extend(["getOpenOrders", "/orders/open", "open_orders", "routes_orders"])
    if "executed" in objective_l or "wallet" in objective_l:
        queries.extend(["executed_orders", "ExecutedOrders", "order_history", "wallet orders"])
    if "reconcil" in objective_l or "portfolio" in objective_l:
        queries.extend(["reconcile", "portfolio", "wallet_reconciliation"])
    if "position" in objective_l:
        queries.extend(["open_positions", "OpenPosition", "count_open_positions"])
    if "trade" in objective_l or "history" in objective_l:
        queries.extend(["order_history", "trade_history", "exchange_orders"])
    if "count" in objective_l and "order" in objective_l:
        queries.extend(["exchange_orders", "OrderStatusEnum"])
    if any(
        term in objective_l
        for term in (
            "insufficient_evidence",
            "insufficient evidence",
            "result_validation",
            "root_cause_present",
            "conclusion_present",
            "repository agent",
            "repository_agent",
            "search_repository",
            "_detect_topics",
            "validation pipeline",
            "safety classifier",
            "planner_agent",
            "objective_classification",
            "jarvis internals",
        )
    ):
        queries.extend(["result_validation", "repository_agent", "search_repository", "planner_agent"])
    if not queries:
        queries.append(objective.split()[0] if objective.split() else "jarvis")

    findings: dict[str, list[dict[str, str]]] = {}
    for q in queries[:5]:
        findings[q] = search_files(q, max_results=10)

    return {
        "agent": "repository_agent",
        "objective": objective,
        "queries": queries,
        "findings": findings,
        "read_only": True,
    }
