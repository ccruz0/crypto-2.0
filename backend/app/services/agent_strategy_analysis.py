"""
Analysis-only callback for strategy/alert/signal business-logic improvements.

Safety constraints:
- Writes analysis notes only under docs/analysis/
- Does not execute shell commands
- Does not modify production/trading/infrastructure code
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.agent_versioning import build_version_summary

logger = logging.getLogger(__name__)

_ELIGIBILITY_KEYWORDS = (
    "alert logic",
    "signal quality",
    "threshold",
    "historical trend",
    "false positive",
    "false negatives",
    "false negative",
    "business-logic alignment",
    "business logic alignment",
    "volume filter",
    "indicator tuning",
    "lookback window",
    "signal",
    "strategy",
    "alerts",
)

_REQUIRED_SECTIONS = (
    "## Title",
    "## Task ID",
    "## Current Version",
    "## Proposed Version",
    "## Problem Observed",
    "## Current Implementation Summary",
    "## Business Logic Intent",
    "## Historical Data Observations",
    "## Proposed Improvement",
    "## Expected Benefit",
    "## Affected Files",
    "## Validation Plan",
    "## Risk Level",
    "## Confidence Score",
)


def _repo_root() -> Path:
    from app.services._paths import workspace_root
    return workspace_root()


def _safe_task_id(prepared_task: dict[str, Any]) -> str:
    task = (prepared_task or {}).get("task") or {}
    return str(task.get("id") or "").strip()


def _safe_task_title(prepared_task: dict[str, Any]) -> str:
    task = (prepared_task or {}).get("task") or {}
    return str(task.get("task") or "").strip()


def _is_strategy_analysis_eligible(prepared_task: dict[str, Any]) -> bool:
    task = (prepared_task or {}).get("task") or {}
    repo_area = (prepared_task or {}).get("repo_area") or {}
    text = " ".join(
        [
            str(task.get("task") or ""),
            str(task.get("details") or ""),
            str(task.get("type") or ""),
            str(task.get("project") or ""),
            str(repo_area.get("area_name") or ""),
            " ".join(str(x) for x in (repo_area.get("matched_rules") or [])),
        ]
    ).lower()
    return any(keyword in text for keyword in _ELIGIBILITY_KEYWORDS)


def _read_text_safe(path: Path, max_chars: int = 5000) -> str:
    if not path.exists() or not path.is_file():
        return ""
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""
    return content[:max_chars]


def _line_count(path: Path) -> int:
    if not path.exists() or not path.is_file():
        return 0
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0


def _markdown_links(text: str) -> list[str]:
    return [m.group(1).strip() for m in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", text or "")]


def _collect_docs_context(prepared_task: dict[str, Any]) -> list[dict[str, str]]:
    root = _repo_root()
    repo_area = (prepared_task or {}).get("repo_area") or {}
    area_docs = [str(x) for x in (repo_area.get("relevant_docs") or []) if str(x).strip()]
    base_docs = [
        "docs/architecture/system-map.md",
        "docs/agents/context.md",
        "docs/agents/task-system.md",
        "docs/integrations/crypto-api.md",
    ]
    candidates = base_docs + area_docs
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for rel in candidates:
        if rel in seen:
            continue
        seen.add(rel)
        path = root / rel
        if not path.exists():
            continue
        snippet = _read_text_safe(path, max_chars=900).strip().replace("\n", " ")
        if snippet:
            snippet = snippet[:240]
        out.append(
            {
                "path": rel,
                "observation": snippet or "documentation file available",
            }
        )
    return out


def _collect_code_context(prepared_task: dict[str, Any]) -> list[dict[str, str]]:
    root = _repo_root()
    repo_area = (prepared_task or {}).get("repo_area") or {}
    likely_files = [str(x) for x in (repo_area.get("likely_files") or []) if str(x).strip()]
    defaults = [
        "backend/app/services/signal_monitor.py",
        "backend/app/services/trading_signals.py",
        "backend/app/models/trade_signal.py",
    ]
    candidates = likely_files + defaults
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for rel in candidates:
        if rel in seen:
            continue
        seen.add(rel)
        path = root / rel
        if not path.exists() or not path.is_file():
            continue
        lines = _line_count(path)
        snippet = _read_text_safe(path, max_chars=1200).lower()
        signals = []
        for keyword in ("signal", "alert", "threshold", "lookback", "volume", "indicator", "window"):
            if keyword in snippet:
                signals.append(keyword)
        obs = f"file exists ({lines} lines)"
        if signals:
            obs += f"; contains: {', '.join(signals[:5])}"
        out.append({"path": rel, "observation": obs})
    return out


def _collect_historical_data_context() -> list[dict[str, str]]:
    root = _repo_root()
    out: list[dict[str, str]] = []
    candidates: list[tuple[str, str]] = [
        ("order_history.db", "SQLite order history database"),
        ("runtime-history", "runtime historical folder"),
        ("logs/agent_activity.jsonl", "agent workflow event log"),
        ("backend/app/services/order_history_db.py", "order-history DB access service"),
        ("backend/app/models/exchange_order.py", "exchange order model"),
        ("backend/app/models/trade_signal.py", "trade signal model"),
    ]
    for rel, label in candidates:
        path = root / rel
        if not path.exists():
            continue
        if path.is_dir():
            sample_names = sorted([p.name for p in path.iterdir()][:5])
            out.append(
                {
                    "path": rel,
                    "observation": f"{label}; directory present with sample entries: {', '.join(sample_names) if sample_names else '(empty)'}",
                }
            )
            continue
        size_bytes = path.stat().st_size
        lines = _line_count(path) if path.suffix in (".py", ".md", ".jsonl", ".log", ".txt", ".csv") else 0
        obs = f"{label}; file present ({size_bytes} bytes"
        if lines:
            obs += f", {lines} lines"
        obs += ")"
        out.append({"path": rel, "observation": obs})
    return out


def _derive_problem_observed(prepared_task: dict[str, Any]) -> str:
    task = (prepared_task or {}).get("task") or {}
    title = str(task.get("task") or "").strip()
    details = str(task.get("details") or "").strip()
    if details:
        return details[:500]
    if title:
        return f"Task indicates potential business-logic quality issue in: {title}."
    return "Potential signal/alert logic quality issue requiring analysis."


def _build_proposed_improvement(
    *,
    task_title: str,
    affected_files: list[str],
) -> list[str]:
    title_lower = task_title.lower()
    improvements: list[str] = []
    if "false positive" in title_lower or "false negative" in title_lower:
        improvements.append(
            "Introduce an analysis-backed quality gate proposal that separates false-positive and false-negative scenarios by threshold band."
        )
    if "lookback" in title_lower or "window" in title_lower:
        improvements.append(
            "Propose adaptive lookback-window tuning rules based on recent volatility regimes from historical observations."
        )
    if "volume" in title_lower:
        improvements.append(
            "Propose a minimum-volume confirmation filter to reduce low-liquidity signal noise."
        )
    if not improvements:
        improvements.append(
            "Propose incremental indicator/threshold tuning with staged validation criteria before any production logic change."
        )
    if affected_files:
        improvements.append(
            "Limit first implementation scope to the affected files listed below and keep non-targeted business logic unchanged."
        )
    return improvements


def _risk_level() -> str:
    # Analysis-only artifact generation (no production code mutation) keeps runtime risk low.
    return "low"


def _confidence_score(
    *,
    affected_files_count: int,
    historical_obs_count: int,
    has_explicit_problem: bool,
) -> float:
    """
    Transparent rule-based confidence for strategy analysis proposals.
    """
    score = 0.45
    if affected_files_count >= 3:
        score += 0.10
    elif affected_files_count >= 1:
        score += 0.05
    if historical_obs_count >= 4:
        score += 0.10
    elif historical_obs_count >= 2:
        score += 0.05
    if has_explicit_problem:
        score += 0.05
    return max(0.0, min(1.0, round(score, 3)))


def _ensure_analysis_index(path: Path, task_id: str, title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# Analysis Notes (Agent)\n\n"
        "Analysis-only business-logic proposals generated by strategy-analysis callbacks.\n"
        "These notes do not modify production logic by themselves.\n\n"
    )
    if not path.exists():
        path.write_text(header, encoding="utf-8")
    entry = f"- [Notion task {task_id}: {title}](notion-task-{task_id}.md)"
    content = path.read_text(encoding="utf-8", errors="ignore")
    if entry not in content:
        with path.open("a", encoding="utf-8") as f:
            if not content.endswith("\n"):
                f.write("\n")
            f.write(entry + "\n")


def _render_analysis_markdown(
    *,
    title: str,
    task_id: str,
    versioning: dict[str, Any],
    problem_observed: str,
    current_impl_summary: list[str],
    business_logic_intent: str,
    historical_obs: list[str],
    proposed_improvement: list[str],
    expected_benefit: str,
    affected_files: list[str],
    validation_plan: list[str],
    risk_level: str,
    confidence_score: float,
) -> str:
    current_version = str(versioning.get("current_version") or "").strip() or "0.1.0"
    proposed_version = str(versioning.get("proposed_version") or "").strip() or current_version
    lines = [
        "## Title",
        f"{title}",
        "",
        "## Task ID",
        f"`{task_id}`",
        "",
        "## Current Version",
        f"`v{current_version}`",
        "",
        "## Proposed Version",
        f"`v{proposed_version}`",
        "",
        "## Problem Observed",
        problem_observed,
        "",
        "## Current Implementation Summary",
    ]
    lines.extend(f"- {x}" for x in (current_impl_summary or ["No current implementation observations found."]))
    lines.extend(
        [
            "",
            "## Business Logic Intent",
            business_logic_intent,
            "",
            "## Historical Data Observations",
        ]
    )
    lines.extend(f"- {x}" for x in (historical_obs or ["No historical data source found in repository path scan."]))
    lines.extend(
        [
            "",
            "## Proposed Improvement",
        ]
    )
    lines.extend(f"- {x}" for x in proposed_improvement)
    lines.extend(
        [
            "",
            "## Expected Benefit",
            expected_benefit,
            "",
            "## Affected Files",
        ]
    )
    lines.extend(f"- `{x}`" for x in (affected_files or []))
    lines.extend(
        [
            "",
            "## Validation Plan",
        ]
    )
    lines.extend(f"- {x}" for x in validation_plan)
    lines.extend(
        [
            "",
            "## Risk Level",
            risk_level,
            "",
            "## Confidence Score",
            f"{confidence_score:.3f} (rule-based: coverage of affected files + historical observations + explicit problem statement)",
            "",
            f"_Generated at {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}_",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def apply_strategy_analysis_task(prepared_task: dict[str, Any]) -> dict[str, Any]:
    """
    Build an analysis-only strategy improvement proposal note under docs/analysis/.
    """
    try:
        if not _is_strategy_analysis_eligible(prepared_task):
            return {
                "success": False,
                "summary": "task not eligible for strategy analysis callback",
            }

        task_id = _safe_task_id(prepared_task)
        title = _safe_task_title(prepared_task) or "Untitled strategy analysis task"
        if not task_id:
            return {
                "success": False,
                "summary": "missing task.id",
            }

        versioning = build_version_summary(prepared_task, analysis_result={"change_type": "minor"})
        versioning["version_status"] = "proposed"

        docs_context = _collect_docs_context(prepared_task)
        code_context = _collect_code_context(prepared_task)
        historical_context = _collect_historical_data_context()

        current_impl_summary = []
        for item in docs_context[:5]:
            current_impl_summary.append(f"Docs: `{item['path']}` - {item['observation']}")
        for item in code_context[:7]:
            current_impl_summary.append(f"Code: `{item['path']}` - {item['observation']}")

        historical_obs = [f"`{x['path']}` - {x['observation']}" for x in historical_context[:8]]

        affected_files = [x["path"] for x in code_context[:8]]
        if not affected_files:
            affected_files = ["backend/app/services/signal_monitor.py"]
        validation_plan = [
            "Confirm proposal alignment with business intent in docs and existing strategy definitions.",
            "Review historical-signal/order trends from available local data sources before changing thresholds.",
            "Run callback validation to ensure proposal completeness and traceability metadata.",
        ]
        proposed_improvement = _build_proposed_improvement(
            task_title=title,
            affected_files=affected_files,
        )

        change_summary = str(versioning.get("change_summary") or "").strip()
        if not change_summary:
            change_summary = f"Analysis-first proposal for strategy/signal quality improvements in task '{title}'."
        versioning["change_summary"] = change_summary
        versioning["affected_files"] = affected_files
        versioning["validation_plan"] = validation_plan
        confidence_score = _confidence_score(
            affected_files_count=len(affected_files),
            historical_obs_count=len(historical_obs),
            has_explicit_problem=bool(_derive_problem_observed(prepared_task).strip()),
        )
        versioning["confidence_score"] = confidence_score

        md = _render_analysis_markdown(
            title=title,
            task_id=task_id,
            versioning=versioning,
            problem_observed=_derive_problem_observed(prepared_task),
            current_impl_summary=current_impl_summary,
            business_logic_intent=(
                "Improve alert/signal decision quality while preserving existing safety constraints and avoiding direct production behavior changes in this step."
            ),
            historical_obs=historical_obs,
            proposed_improvement=proposed_improvement,
            expected_benefit=(
                "Higher signal relevance and lower noise by validating improvement hypotheses against documented intent and available historical evidence."
            ),
            affected_files=affected_files,
            validation_plan=validation_plan,
            risk_level=_risk_level(),
            confidence_score=confidence_score,
        )

        root = _repo_root()
        analysis_dir = root / "docs" / "analysis"
        analysis_dir.mkdir(parents=True, exist_ok=True)
        analysis_file = analysis_dir / f"notion-task-{task_id}.md"
        analysis_file.write_text(md, encoding="utf-8")
        _ensure_analysis_index(analysis_dir / "README.md", task_id=task_id, title=title)

        try:
            from app.services.agent_activity_log import log_agent_event

            log_agent_event(
                "strategy_analysis_generated",
                task_id=task_id,
                task_title=title,
                details={
                    "analysis_file": f"docs/analysis/notion-task-{task_id}.md",
                    "proposed_version": versioning.get("proposed_version", ""),
                    "change_summary": versioning.get("change_summary", ""),
                    "risk_level": _risk_level(),
                    "confidence_score": confidence_score,
                },
            )
        except Exception:
            pass

        return {
            "success": True,
            "summary": f"strategy analysis proposal generated at docs/analysis/notion-task-{task_id}.md",
            "analysis_file": f"docs/analysis/notion-task-{task_id}.md",
            "current_version": versioning.get("current_version", ""),
            "proposed_version": versioning.get("proposed_version", ""),
            "version_status": "proposed",
            "change_summary": versioning.get("change_summary", ""),
            "affected_files": affected_files,
            "validation_plan": validation_plan,
            "risk_level": _risk_level(),
            "confidence_score": confidence_score,
        }
    except Exception as e:
        logger.exception("apply_strategy_analysis_task failed: %s", e)
        return {
            "success": False,
            "summary": str(e),
        }


def validate_strategy_analysis_task(prepared_task: dict[str, Any]) -> dict[str, Any]:
    """
    Validate generated strategy analysis markdown for structure and completeness.
    """
    try:
        task_id = _safe_task_id(prepared_task)
        if not task_id:
            return {"success": False, "summary": "missing task.id"}

        path = _repo_root() / "docs" / "analysis" / f"notion-task-{task_id}.md"
        if not path.exists():
            return {"success": False, "summary": f"missing analysis file: {path.as_posix()}"}

        content = _read_text_safe(path, max_chars=200000)
        if not content.strip():
            return {"success": False, "summary": "analysis markdown is empty"}

        for marker in _REQUIRED_SECTIONS:
            if marker not in content:
                msg = f"missing required section: {marker}"
                try:
                    from app.services.agent_activity_log import log_agent_event

                    log_agent_event(
                        "strategy_analysis_validation_failed",
                        task_id=task_id,
                        details={"reason": msg},
                    )
                except Exception:
                    pass
                return {"success": False, "summary": msg}

        affected_section = content.split("## Affected Files", 1)[1].split("## Validation Plan", 1)[0]
        if "`" not in affected_section and "- " not in affected_section:
            msg = "no affected files listed in analysis"
            try:
                from app.services.agent_activity_log import log_agent_event
                log_agent_event("strategy_analysis_validation_failed", task_id=task_id, details={"reason": msg})
            except Exception:
                pass
            return {"success": False, "summary": msg}

        proposed_section = content.split("## Proposed Improvement", 1)[1].split("## Expected Benefit", 1)[0]
        bullet_lines = [ln.strip() for ln in proposed_section.splitlines() if ln.strip().startswith("- ")]
        if not bullet_lines:
            msg = "no concrete proposed improvement listed"
            try:
                from app.services.agent_activity_log import log_agent_event
                log_agent_event("strategy_analysis_validation_failed", task_id=task_id, details={"reason": msg})
            except Exception:
                pass
            return {"success": False, "summary": msg}

        # Validate relative links if present.
        for link in _markdown_links(content):
            if not link or "://" in link or link.startswith("#"):
                continue
            target_rel = link.split("#", 1)[0].strip()
            if not target_rel:
                continue
            resolved = (path.parent / target_rel).resolve()
            if not resolved.exists():
                msg = f"broken relative markdown link: {link}"
                try:
                    from app.services.agent_activity_log import log_agent_event
                    log_agent_event("strategy_analysis_validation_failed", task_id=task_id, details={"reason": msg})
                except Exception:
                    pass
                return {"success": False, "summary": msg}

        return {"success": True, "summary": "strategy analysis note validated (sections, improvements, links)"}
    except Exception as e:
        logger.exception("validate_strategy_analysis_task failed: %s", e)
        try:
            task_id = _safe_task_id(prepared_task)
            from app.services.agent_activity_log import log_agent_event
            log_agent_event("strategy_analysis_validation_failed", task_id=task_id or None, details={"reason": str(e)})
        except Exception:
            pass
        return {"success": False, "summary": str(e)}

