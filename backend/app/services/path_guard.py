"""
Central path policy for LAB / OpenClaw artifact writes (defense in depth).

PROD mutations (backend code, runtime config, deploy, etc.) must use governance manifests
and the governed executor — they do not use this module.

Allowed targets:
  - Any path under ``<workspace_root>/docs/`` (resolved, symlink-safe).
  - Configured LAB artifact fallbacks (writable dirs when repo ``docs/`` is read-only).

Writes under the workspace but outside ``docs/`` (e.g. ``backend/``, ``frontend/``) are blocked.
Paths outside the workspace and outside configured fallbacks are blocked.

Disable only in emergencies: ``ATP_PATH_GUARD_DISABLE=true`` (logs a warning on import/use).
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Literal

logger = logging.getLogger(__name__)

EVENT_ALLOWED = "path_guard_write_allowed"
EVENT_BLOCKED = "path_guard_write_blocked"
EVENT_PATCH_BLOCKED = "path_guard_patch_blocked"


class PathGuardViolation(PermissionError):
    """Raised when a LAB/OpenClaw write targets a non-allowed path."""

    def __init__(self, message: str, *, resolved: str = "", rule: str = "") -> None:
        self.resolved_path = resolved
        self.rule = rule
        super().__init__(message)


def path_guard_enabled() -> bool:
    raw = (os.environ.get("ATP_PATH_GUARD_DISABLE") or "").strip().lower()
    return raw not in ("1", "true", "yes", "on")


def workspace_root() -> Path:
    from app.services._paths import workspace_root as _wr

    return _wr()


def _docs_root() -> Path:
    return (workspace_root() / "docs").resolve()


def _configured_fallback_roots() -> list[Path]:
    """Extra allowed roots for LAB artifacts (outside repo or when docs/ is not writable)."""
    roots: list[Path] = []
    for key in (
        "AGENT_ARTIFACTS_DIR",
        "AGENT_BUG_INVESTIGATIONS_DIR",
        "AGENT_CURSOR_HANDOFFS_DIR",
    ):
        v = (os.environ.get(key) or "").strip()
        if v:
            roots.append(Path(v).expanduser().resolve())

    roots.append(Path("/tmp/agent-artifacts").resolve())
    roots.append(Path("/tmp/agent-bug-investigations").resolve())
    roots.append(Path("/tmp/agent-cursor-handoffs").resolve())

    extra = (os.environ.get("ATP_PATH_GUARD_EXTRA_ALLOWED_PREFIXES") or "").strip()
    if extra:
        root = workspace_root()
        for part in extra.split(","):
            p = part.strip()
            if not p:
                continue
            q = Path(p)
            if q.is_absolute():
                roots.append(q.resolve())
            else:
                roots.append((root / p).resolve())

    seen: set[str] = set()
    out: list[Path] = []
    for r in roots:
        key = str(r)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def coerce_resolved_path(path: str | Path) -> Path:
    """Join relative paths to workspace_root; resolve with strict symlink resolution."""
    p = Path(path)
    if p.is_absolute():
        return p.resolve()
    return (workspace_root() / p).resolve()


def classify_lab_write_target(resolved: Path) -> tuple[bool, str, str]:
    """
    Returns (allowed, zone, detail).

    zone: docs_tree | artifact_fallback | workspace_non_docs | outside_workspace
    """
    rp = resolved.resolve()
    docs = _docs_root()
    try:
        rp.relative_to(docs)
        return True, "docs_tree", ""
    except ValueError:
        pass

    for extra in _configured_fallback_roots():
        try:
            rp.relative_to(extra)
            return True, "artifact_fallback", extra.as_posix()
        except ValueError:
            continue

    wr = workspace_root().resolve()
    try:
        rp.relative_to(wr)
        return False, "workspace_non_docs", f"path is under workspace but outside docs/: {rp}"
    except ValueError:
        pass

    return False, "outside_workspace", f"path outside workspace and LAB fallbacks: {rp}"


def assert_writable_lab_path(path: str | Path, *, context: str = "") -> Path:
    """
    Fail closed if path is not an allowed LAB write target.
    Returns fully resolved Path when allowed or when guard disabled.
    """
    if not path_guard_enabled():
        if (os.environ.get("ATP_PATH_GUARD_DISABLE") or "").strip():
            logger.warning(
                "path_guard_disabled context=%s target=%s — LAB writes are not policy-checked",
                context,
                path,
            )
        return coerce_resolved_path(path)

    resolved = coerce_resolved_path(path)
    ok, zone, detail = classify_lab_write_target(resolved)
    if ok:
        return resolved

    msg = (
        f"Path guard: LAB write blocked ({zone}). "
        f"Allowed: <workspace>/docs/** and configured LAB artifact directories. "
        f"Attempted resolved path: {resolved}. {detail}"
    )
    payload = {
        "event": EVENT_BLOCKED,
        "policy_decision": "deny",
        "zone": zone,
        "normalized_path": resolved.as_posix(),
        "attempted_path": str(path),
        "context": context,
        "detail": detail[:500],
    }
    logger.error("%s %s", EVENT_BLOCKED, json.dumps(payload, default=str))
    raise PathGuardViolation(msg, resolved=resolved.as_posix(), rule=zone)


def _log_write_allowed(resolved: Path, *, context: str, operation: str) -> None:
    if (os.environ.get("PATH_GUARD_LOG_ALLOWED") or "").strip().lower() in ("1", "true", "yes"):
        payload = {
            "event": EVENT_ALLOWED,
            "policy_decision": "allow",
            "normalized_path": resolved.as_posix(),
            "context": context,
            "operation": operation,
        }
        logger.info("%s %s", EVENT_ALLOWED, json.dumps(payload, default=str))
    else:
        logger.debug(
            "path_guard allow op=%s path=%s context=%s", operation, resolved.as_posix(), context
        )


def safe_mkdir_lab(path: str | Path, *, parents: bool = True, context: str = "") -> Path:
    target = assert_writable_lab_path(path, context=context)
    target.mkdir(parents=parents, exist_ok=True)
    _log_write_allowed(target, context=context, operation="mkdir")
    return target


def safe_write_text(
    path: str | Path,
    content: str,
    *,
    encoding: str = "utf-8",
    context: str = "",
) -> Path:
    target = assert_writable_lab_path(path, context=context)
    target.parent.mkdir(parents=True, exist_ok=True)
    assert_writable_lab_path(target.parent, context=f"{context}:parent")
    target.write_text(content, encoding=encoding)
    _log_write_allowed(target, context=context, operation="write_text")
    return target


def safe_write_bytes(path: str | Path, data: bytes, *, context: str = "") -> Path:
    target = assert_writable_lab_path(path, context=context)
    target.parent.mkdir(parents=True, exist_ok=True)
    assert_writable_lab_path(target.parent, context=f"{context}:parent")
    target.write_bytes(data)
    _log_write_allowed(target, context=context, operation="write_bytes")
    return target


def safe_append_text(
    path: str | Path,
    chunk: str,
    *,
    encoding: str = "utf-8",
    context: str = "",
) -> Path:
    target = assert_writable_lab_path(path, context=context)
    target.parent.mkdir(parents=True, exist_ok=True)
    assert_writable_lab_path(target.parent, context=f"{context}:parent")
    with target.open("a", encoding=encoding) as f:
        f.write(chunk)
    _log_write_allowed(target, context=context, operation="append_text")
    return target


@contextmanager
def safe_open_text(
    path: str | Path,
    mode: Literal["r", "w", "a"],
    *,
    encoding: str = "utf-8",
    context: str = "",
) -> Iterator[Any]:
    if mode not in ("r", "w", "a"):
        raise ValueError("safe_open_text only supports r, w, a")
    target = coerce_resolved_path(path)
    if mode != "r":
        assert_writable_lab_path(target, context=context)
        if mode in ("w", "a"):
            target.parent.mkdir(parents=True, exist_ok=True)
            assert_writable_lab_path(target.parent, context=f"{context}:parent")
    with target.open(mode, encoding=encoding) as f:
        yield f
    if mode != "r":
        _log_write_allowed(target, context=context, operation=f"open_{mode}")


def assert_lab_patch_target(path: str | Path, *, context: str = "") -> Path:
    """
    Use before applying a patch or destructive edit in LAB flows.
    Same policy as writes; logs path_guard_patch_blocked on failure.
    """
    try:
        return assert_writable_lab_path(path, context=context)
    except PathGuardViolation as e:
        payload = {
            "event": EVENT_PATCH_BLOCKED,
            "policy_decision": "deny",
            "normalized_path": e.resolved_path,
            "context": context,
            "rule": e.rule,
        }
        logger.error("%s %s", EVENT_PATCH_BLOCKED, json.dumps(payload, default=str))
        raise
