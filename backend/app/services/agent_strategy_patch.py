"""
Controlled strategy patch callback (manual-only, approval-gated).

Applies tiny, explicit business-logic tuning patches only when:
- an analysis artifact exists and is complete
- risk and confidence thresholds are acceptable
- affected files are strictly allowlisted

Safety:
- no network calls
- no new dependencies
- no infrastructure/trading/exchange/telegram core changes
"""

from __future__ import annotations

import logging
import re
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from app.services.agent_versioning import build_version_summary

logger = logging.getLogger(__name__)

ALLOWLIST_PATTERNS = (
    "backend/app/services/signal_monitor.py",
    "backend/app/services/alert_*.py",
    "backend/app/services/indicator_*.py",
)

_PATCH_NOTE_REQUIRED_SECTIONS = (
    "## Task ID",
    "## Current Version",
    "## Proposed Version",
    "## Affected Files",
    "## Exact Parameters Changed",
    "## Rationale",
    "## Validation Plan",
    "## Risk Level",
    "## Confidence Score",
    "## Touched Lines Summary",
)


def _repo_root() -> Path:
    from app.services._paths import workspace_root
    return workspace_root()


def _safe_task_id(prepared_task: dict[str, Any]) -> str:
    task = (prepared_task or {}).get("task") or {}
    return str(task.get("id") or "").strip()


def _task_blob(prepared_task: dict[str, Any]) -> str:
    task = (prepared_task or {}).get("task") or {}
    repo_area = (prepared_task or {}).get("repo_area") or {}
    return " ".join(
        [
            str(task.get("task") or ""),
            str(task.get("details") or ""),
            str(task.get("type") or ""),
            str(task.get("project") or ""),
            str(repo_area.get("area_name") or ""),
            " ".join(str(x) for x in (repo_area.get("matched_rules") or [])),
        ]
    ).lower()


def _looks_like_strategy_patch_task(prepared_task: dict[str, Any]) -> bool:
    blob = _task_blob(prepared_task)
    required = ("strategy", "signal", "business-logic", "business logic", "threshold", "lookback", "volume", "tuning")
    return any(k in blob for k in required)


def _analysis_paths(task_id: str) -> list[Path]:
    root = _repo_root()
    return [
        root / "docs" / "analysis" / f"signal-performance-{task_id}.md",
        root / "docs" / "analysis" / f"notion-task-{task_id}.md",
    ]


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _extract_section(text: str, section_name: str) -> str:
    marker = f"## {section_name}"
    if marker not in text:
        return ""
    rest = text.split(marker, 1)[1]
    if "\n## " in rest:
        rest = rest.split("\n## ", 1)[0]
    return rest.strip()


def _extract_first_semver(text: str) -> str:
    m = re.search(r"\b(?:v)?(\d+\.\d+\.\d+)\b", text or "", flags=re.IGNORECASE)
    return m.group(1) if m else ""


def _parse_bullets(section_text: str) -> list[str]:
    out: list[str] = []
    for line in (section_text or "").splitlines():
        s = line.strip()
        if s.startswith("- "):
            out.append(s[2:].strip())
    return out


def _parse_affected_files(section_text: str) -> list[str]:
    files: list[str] = []
    for raw in _parse_bullets(section_text):
        item = raw.strip().strip("`")
        if not item or item.startswith("data-source:"):
            continue
        files.append(item)
    # de-dup preserve order
    out: list[str] = []
    seen: set[str] = set()
    for p in files:
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


def _is_allowlisted(rel_path: str) -> bool:
    return any(fnmatch(rel_path, pat) for pat in ALLOWLIST_PATTERNS)


def _parse_confidence_score(text: str) -> float | None:
    m = re.search(r"confidence[^0-9]*([01](?:\.\d+)?)", text or "", flags=re.IGNORECASE)
    if not m:
        return None
    try:
        value = float(m.group(1))
    except Exception:
        return None
    if value < 0.0 or value > 1.0:
        return None
    return value


def _normalize_risk(text: str) -> str:
    s = (text or "").strip().lower()
    if "high" in s:
        return "high"
    if "medium" in s:
        return "medium"
    if "low" in s:
        return "low"
    return ""


def _allowed_change_type(proposed_improvement: str) -> bool:
    p = proposed_improvement.lower()
    allowed = (
        "threshold",
        "lookback",
        "volume",
        "filter",
        "condition",
        "constant",
        "rsi",
    )
    forbidden = (
        "refactor",
        "subsystem",
        "dependency",
        "api call",
        "api endpoint",
        "order placement",
        "exchange",
        "schema",
        "migration",
        "deploy",
        "nginx",
        "docker",
        "runtime config",
        "infrastructure",
        "telegram_commands.py",
    )
    if any(x in p for x in forbidden):
        return False
    return any(x in p for x in allowed)


def _analysis_payload(prepared_task: dict[str, Any]) -> dict[str, Any]:
    task_id = _safe_task_id(prepared_task)
    if not task_id:
        return {"ok": False, "reason": "missing task.id"}

    analysis_file = None
    content = ""
    for candidate in _analysis_paths(task_id):
        if candidate.exists():
            analysis_file = candidate
            content = _read_text(candidate)
            if content.strip():
                break

    if not analysis_file or not content.strip():
        return {"ok": False, "reason": "analysis artifact not found"}

    proposed_improvement = _extract_section(content, "Proposed Improvement")
    affected_files_sec = _extract_section(content, "Affected Files")
    validation_plan_sec = _extract_section(content, "Validation Plan")
    risk_level_sec = _extract_section(content, "Risk Level")
    confidence_sec = _extract_section(content, "Confidence Score")
    change_summary = _extract_section(content, "Problem Observed")

    affected_files = _parse_affected_files(affected_files_sec)
    validation_plan = _parse_bullets(validation_plan_sec)
    confidence_score = _parse_confidence_score(confidence_sec)
    risk_level = _normalize_risk(risk_level_sec)
    current_version = _extract_first_semver(_extract_section(content, "Current Version"))
    proposed_version = _extract_first_semver(_extract_section(content, "Proposed Version"))

    if not proposed_improvement.strip():
        return {"ok": False, "reason": "analysis missing proposed improvement"}
    if not affected_files:
        return {"ok": False, "reason": "analysis missing affected files"}
    if not validation_plan:
        return {"ok": False, "reason": "analysis missing validation plan"}
    if not risk_level:
        return {"ok": False, "reason": "analysis missing risk level"}
    if confidence_score is None:
        return {"ok": False, "reason": "analysis missing confidence score"}

    return {
        "ok": True,
        "analysis_file": analysis_file.as_posix().replace(str(_repo_root()) + "/", ""),
        "analysis_path": analysis_file,
        "proposed_improvement": proposed_improvement,
        "affected_files": affected_files,
        "validation_plan": validation_plan,
        "risk_level": risk_level,
        "confidence_score": confidence_score,
        "current_version": current_version,
        "proposed_version": proposed_version,
        "change_summary": (change_summary or "").strip()[:1000],
    }


def _eligible_or_reason(prepared_task: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    if not _looks_like_strategy_patch_task(prepared_task):
        return False, {"reason": "task not strategy/business-logic improvement"}

    payload = _analysis_payload(prepared_task)
    if not payload.get("ok"):
        return False, {"reason": payload.get("reason", "analysis not ready")}

    if payload.get("risk_level") == "high":
        return False, {"reason": "analysis risk level is high"}
    if float(payload.get("confidence_score") or 0.0) < 0.60:
        return False, {"reason": "analysis confidence score below 0.60"}

    affected_files = payload.get("affected_files") or []
    if not all(_is_allowlisted(p) for p in affected_files):
        return False, {"reason": "analysis affected files not fully allowlisted"}

    if not _allowed_change_type(str(payload.get("proposed_improvement") or "")):
        return False, {"reason": "proposed improvement includes forbidden change type"}

    return True, payload


def strategy_patch_preview_metadata(prepared_task: dict[str, Any]) -> dict[str, Any] | None:
    """
    Public helper for callback selection to check patch eligibility and collect metadata.
    Returns None when not eligible.
    """
    ok, payload = _eligible_or_reason(prepared_task)
    if not ok:
        return None
    return payload


def _replace_one(content: str, old: str, new: str) -> tuple[str, bool]:
    count = content.count(old)
    if count != 1:
        return content, False
    return content.replace(old, new, 1), True


def _compute_changed_lines(before: str, after: str) -> int:
    b = before.splitlines()
    a = after.splitlines()
    max_len = max(len(b), len(a))
    changed = 0
    for i in range(max_len):
        left = b[i] if i < len(b) else ""
        right = a[i] if i < len(a) else ""
        if left != right:
            changed += 1
    return changed


def _apply_allowed_patch(rel_path: str, proposal_text: str) -> dict[str, Any]:
    """
    Apply a small, explicit patch in an allowlisted file.
    Current first implementation supports `signal_monitor.py` threshold tuning only.
    """
    root = _repo_root()
    path = root / rel_path
    if not path.exists():
        return {"ok": False, "reason": f"missing file: {rel_path}"}

    original = _read_text(path)
    updated = original
    changes: list[dict[str, Any]] = []

    # Narrow, auditable transformations only.
    if rel_path == "backend/app/services/signal_monitor.py":
        # Conservative threshold tuning variant.
        # Guard: exact single occurrences only; otherwise fail to avoid broad rewrites.
        updated, ok_buy = _replace_one(updated, "rsi_buy_threshold=40,", "rsi_buy_threshold=38,")
        if not ok_buy:
            return {"ok": False, "reason": "expected pattern not found or ambiguous: rsi_buy_threshold=40"}
        changes.append({"parameter": "rsi_buy_threshold", "from": "40", "to": "38"})

        updated, ok_sell = _replace_one(updated, "rsi_sell_threshold=70,", "rsi_sell_threshold=72,")
        if not ok_sell:
            return {"ok": False, "reason": "expected pattern not found or ambiguous: rsi_sell_threshold=70"}
        changes.append({"parameter": "rsi_sell_threshold", "from": "70", "to": "72"})
    else:
        # For now, keep non-signal_monitor allowlisted patterns as no-op unless explicit
        # audited mappings are added later.
        return {"ok": False, "reason": f"no audited patch mapping for {rel_path}"}

    if updated == original:
        return {"ok": False, "reason": "patch produced no changes"}

    touched = _compute_changed_lines(original, updated)
    if touched <= 0:
        return {"ok": False, "reason": "patch localization check failed"}
    if touched > 40:
        return {"ok": False, "reason": f"patch too broad ({touched} lines touched)"}

    path.write_text(updated, encoding="utf-8")
    return {
        "ok": True,
        "file": rel_path,
        "touched_lines": touched,
        "changes": changes,
        "proposal_excerpt": proposal_text[:240].replace("\n", " "),
    }


def _ensure_patch_index(path: Path, task_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# Strategy Patch Notes (Agent)\n\n"
        "Controlled, approval-gated patch notes for low-risk business-logic tuning.\n"
        "No deployment/runtime/infra actions are performed here.\n\n"
    )
    if not path.exists():
        path.write_text(header, encoding="utf-8")
    entry = f"- [Notion task {task_id} patch](notion-task-{task_id}.md)"
    content = _read_text(path)
    if entry not in content:
        with path.open("a", encoding="utf-8") as f:
            if not content.endswith("\n"):
                f.write("\n")
            f.write(entry + "\n")


def apply_strategy_patch_task(prepared_task: dict[str, Any]) -> dict[str, Any]:
    try:
        eligible, payload = _eligible_or_reason(prepared_task)
        if not eligible:
            return {"success": False, "summary": "task not eligible for strategy patch callback"}

        task_id = _safe_task_id(prepared_task)
        proposed_improvement = str(payload.get("proposed_improvement") or "")
        affected_files = list(payload.get("affected_files") or [])
        validation_plan = list(payload.get("validation_plan") or [])
        risk_level = str(payload.get("risk_level") or "medium")
        confidence_score = float(payload.get("confidence_score") or 0.0)

        # Build/merge versioning data.
        versioning = build_version_summary(prepared_task, analysis_result={"change_type": "minor"})
        if payload.get("current_version"):
            versioning["current_version"] = payload.get("current_version")
        if payload.get("proposed_version"):
            versioning["proposed_version"] = payload.get("proposed_version")
        if payload.get("change_summary"):
            versioning["change_summary"] = payload.get("change_summary")
        versioning["version_status"] = "proposed"
        versioning["confidence_score"] = confidence_score

        patch_results: list[dict[str, Any]] = []
        for rel_path in affected_files:
            if not _is_allowlisted(rel_path):
                return {"success": False, "summary": "task not eligible for strategy patch callback"}
            result = _apply_allowed_patch(rel_path, proposed_improvement)
            if not result.get("ok"):
                return {"success": False, "summary": f"patch failed safely: {result.get('reason', 'unknown')}"}
            patch_results.append(result)

        modified_files = [r["file"] for r in patch_results]
        touched_total = sum(int(r.get("touched_lines", 0)) for r in patch_results)
        if touched_total <= 0:
            return {"success": False, "summary": "patch failed safely: no lines changed"}

        root = _repo_root()
        notes_dir = root / "docs" / "analysis" / "patches"
        notes_dir.mkdir(parents=True, exist_ok=True)
        patch_note = notes_dir / f"notion-task-{task_id}.md"

        changed_lines = []
        for pr in patch_results:
            for c in pr.get("changes", []):
                changed_lines.append(
                    f"- `{pr['file']}`: `{c.get('parameter')}` `{c.get('from')}` -> `{c.get('to')}`"
                )

        note = "\n".join(
            [
                "## Task ID",
                f"`{task_id}`",
                "",
                "## Current Version",
                f"`v{versioning.get('current_version', '')}`",
                "",
                "## Proposed Version",
                f"`v{versioning.get('proposed_version', '')}`",
                "",
                "## Affected Files",
                *[f"- `{p}`" for p in modified_files],
                "",
                "## Exact Parameters Changed",
                *(changed_lines or ["- (none)"]),
                "",
                "## Rationale",
                str(versioning.get("change_summary") or proposed_improvement or "Low-risk tuning from approved analysis proposal."),
                "",
                "## Validation Plan",
                *[f"- {v}" for v in validation_plan],
                "",
                "## Risk Level",
                risk_level,
                "",
                "## Confidence Score",
                f"{confidence_score:.3f}",
                "",
                "## Touched Lines Summary",
                f"- Total touched lines (approx): `{touched_total}`",
                *[f"- `{x['file']}` touched lines: `{x.get('touched_lines', 0)}`" for x in patch_results],
            ]
        ).strip() + "\n"
        patch_note.write_text(note, encoding="utf-8")
        _ensure_patch_index(notes_dir / "README.md", task_id)

        try:
            from app.services.agent_activity_log import log_agent_event
            log_agent_event(
                "strategy_patch_generated",
                task_id=task_id,
                details={
                    "patch_note_file": f"docs/analysis/patches/notion-task-{task_id}.md",
                    "modified_files": modified_files,
                    "touched_lines_total": touched_total,
                    "proposed_version": versioning.get("proposed_version", ""),
                },
            )
        except Exception:
            pass

        return {
            "success": True,
            "summary": f"strategy patch applied with note docs/analysis/patches/notion-task-{task_id}.md",
            "patch_note_file": f"docs/analysis/patches/notion-task-{task_id}.md",
            "modified_files": modified_files,
            "current_version": versioning.get("current_version", ""),
            "proposed_version": versioning.get("proposed_version", ""),
            "version_status": "proposed",
            "change_summary": versioning.get("change_summary", ""),
            "validation_plan": validation_plan,
            "risk_level": risk_level,
            "confidence_score": confidence_score,
        }
    except Exception as e:
        logger.exception("apply_strategy_patch_task failed: %s", e)
        return {"success": False, "summary": str(e)}


def validate_strategy_patch_task(prepared_task: dict[str, Any]) -> dict[str, Any]:
    try:
        task_id = _safe_task_id(prepared_task)
        if not task_id:
            return {"success": False, "summary": "missing task.id"}

        root = _repo_root()
        note_path = root / "docs" / "analysis" / "patches" / f"notion-task-{task_id}.md"
        if not note_path.exists():
            return {"success": False, "summary": f"missing patch note: {note_path.as_posix()}"}

        note = _read_text(note_path)
        if not note.strip():
            return {"success": False, "summary": "patch note is empty"}

        for marker in _PATCH_NOTE_REQUIRED_SECTIONS:
            if marker not in note:
                msg = f"missing required patch-note section: {marker}"
                try:
                    from app.services.agent_activity_log import log_agent_event
                    log_agent_event("strategy_patch_validation_failed", task_id=task_id, details={"reason": msg})
                except Exception:
                    pass
                return {"success": False, "summary": msg}

        affected_sec = _extract_section(note, "Affected Files")
        modified_files = _parse_affected_files(affected_sec)
        if not modified_files:
            msg = "no modified files listed in patch note"
            try:
                from app.services.agent_activity_log import log_agent_event
                log_agent_event("strategy_patch_validation_failed", task_id=task_id, details={"reason": msg})
            except Exception:
                pass
            return {"success": False, "summary": msg}

        if not all(_is_allowlisted(p) for p in modified_files):
            msg = "non-allowlisted file found in patch note"
            try:
                from app.services.agent_activity_log import log_agent_event
                log_agent_event("strategy_patch_validation_failed", task_id=task_id, details={"reason": msg})
            except Exception:
                pass
            return {"success": False, "summary": msg}

        for rel in modified_files:
            if not (root / rel).exists():
                msg = f"modified file missing: {rel}"
                try:
                    from app.services.agent_activity_log import log_agent_event
                    log_agent_event("strategy_patch_validation_failed", task_id=task_id, details={"reason": msg})
                except Exception:
                    pass
                return {"success": False, "summary": msg}

        params_sec = _extract_section(note, "Exact Parameters Changed")
        param_lines = [ln.strip() for ln in params_sec.splitlines() if ln.strip().startswith("- ")]
        if not param_lines:
            msg = "patch note has no parameter changes"
            try:
                from app.services.agent_activity_log import log_agent_event
                log_agent_event("strategy_patch_validation_failed", task_id=task_id, details={"reason": msg})
            except Exception:
                pass
            return {"success": False, "summary": msg}

        touched_sec = _extract_section(note, "Touched Lines Summary")
        m = re.search(r"Total touched lines \(approx\):\s*`?(\d+)`?", touched_sec)
        touched_total = int(m.group(1)) if m else 0
        if touched_total <= 0:
            msg = "patch appears empty (no touched lines)"
            try:
                from app.services.agent_activity_log import log_agent_event
                log_agent_event("strategy_patch_validation_failed", task_id=task_id, details={"reason": msg})
            except Exception:
                pass
            return {"success": False, "summary": msg}
        if touched_total > 40:
            msg = f"patch appears non-localized ({touched_total} lines)"
            try:
                from app.services.agent_activity_log import log_agent_event
                log_agent_event("strategy_patch_validation_failed", task_id=task_id, details={"reason": msg})
            except Exception:
                pass
            return {"success": False, "summary": msg}

        # Validate relative links if present in patch note.
        for link in [m.group(1).strip() for m in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", note)]:
            if not link or "://" in link or link.startswith("#"):
                continue
            target = link.split("#", 1)[0].strip()
            if not target:
                continue
            resolved = (note_path.parent / target).resolve()
            if not resolved.exists():
                msg = f"broken relative markdown link: {link}"
                try:
                    from app.services.agent_activity_log import log_agent_event
                    log_agent_event("strategy_patch_validation_failed", task_id=task_id, details={"reason": msg})
                except Exception:
                    pass
                return {"success": False, "summary": msg}

        return {
            "success": True,
            "summary": f"strategy patch note validated; modified_files={len(modified_files)} touched_lines={touched_total}",
        }
    except Exception as e:
        logger.exception("validate_strategy_patch_task failed: %s", e)
        try:
            task_id = _safe_task_id(prepared_task)
            from app.services.agent_activity_log import log_agent_event
            log_agent_event("strategy_patch_validation_failed", task_id=task_id or None, details={"reason": str(e)})
        except Exception:
            pass
        return {"success": False, "summary": str(e)}

