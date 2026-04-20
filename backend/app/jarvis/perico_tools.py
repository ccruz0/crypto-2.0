"""Filesystem + pytest helpers for Perico (phase 1: single repo root, path-confined)."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

_MAX_LIST_ENTRIES = 200
_MAX_READ_BYTES = 400_000
_MAX_GREP_FILES = 600
_MAX_GREP_MATCHES = 120


def perico_repo_root() -> Path:
    raw = (os.getenv("PERICO_REPO_ROOT") or "/home/ubuntu/crypto-2.0").strip()
    return Path(raw).expanduser().resolve()


def _safe_child(rel: str) -> Path:
    rel_norm = (rel or ".").strip().replace("\\", "/").lstrip("/")
    if ".." in Path(rel_norm).parts:
        raise ValueError("relative_path must not contain '..'")
    root = perico_repo_root()
    full = (root / rel_norm).resolve()
    full.relative_to(root)
    return full


def perico_repo_read(
    *,
    operation: str,
    relative_path: str = "",
    pattern: str = "",
    max_results: int = 80,
) -> dict[str, Any]:
    """
    operation: list | read | grep
    - list: directory listing under relative_path (default ".")
    - read: file contents (text), truncated
    - grep: simple substring search under relative_path directory tree (Python walk)
    """
    op = (operation or "").strip().lower()
    if op not in ("list", "read", "grep"):
        return {"ok": False, "error": "invalid_operation", "allowed": ["list", "read", "grep"]}

    try:
        base = _safe_child(relative_path or ".")
    except Exception as e:
        return {"ok": False, "error": "path_not_allowed", "detail": str(e)}

    if op == "list":
        if not base.is_dir():
            return {"ok": False, "error": "not_a_directory", "path": str(base)}
        entries: list[str] = []
        try:
            for p in sorted(base.iterdir(), key=lambda x: x.name.lower()):
                suffix = "/" if p.is_dir() else ""
                entries.append(f"{p.name}{suffix}")
                if len(entries) >= _MAX_LIST_ENTRIES:
                    break
        except OSError as e:
            return {"ok": False, "error": "list_failed", "detail": str(e)}
        return {"ok": True, "operation": "list", "path": str(base), "entries": entries}

    if op == "read":
        if not base.is_file():
            return {"ok": False, "error": "not_a_file", "path": str(base)}
        try:
            raw = base.read_bytes()[:_MAX_READ_BYTES]
        except OSError as e:
            return {"ok": False, "error": "read_failed", "detail": str(e)}
        text = raw.decode("utf-8", errors="replace")
        truncated = base.stat().st_size > len(raw)
        return {
            "ok": True,
            "operation": "read",
            "path": str(base),
            "content": text,
            "truncated": truncated,
            "size_bytes": base.stat().st_size,
        }

    # grep
    if not base.exists():
        return {"ok": False, "error": "path_missing", "path": str(base)}
    needle = (pattern or "").strip()
    if len(needle) < 2:
        return {"ok": False, "error": "pattern_too_short", "min_chars": 2}
    lim = max(1, min(int(max_results or 80), _MAX_GREP_MATCHES))
    matches: list[dict[str, Any]] = []
    files_seen = 0
    try:
        pat = re.compile(re.escape(needle), re.IGNORECASE)
    except re.error as e:
        return {"ok": False, "error": "invalid_pattern", "detail": str(e)}

    def _grep_file(fp: Path) -> None:
        nonlocal files_seen, matches
        if len(matches) >= lim or files_seen > _MAX_GREP_FILES:
            return
        if fp.suffix.lower() not in (
            ".py",
            ".md",
            ".txt",
            ".json",
            ".yaml",
            ".yml",
            ".toml",
            ".sh",
            ".ts",
            ".tsx",
            ".js",
            ".jsx",
            ".css",
            ".html",
        ):
            return
        files_seen += 1
        try:
            data = fp.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return
        for i, line in enumerate(data.splitlines(), start=1):
            if pat.search(line):
                rel = str(fp.relative_to(perico_repo_root()))
                matches.append({"path": rel, "line": i, "text": line[:500]})
                if len(matches) >= lim:
                    return

    if base.is_file():
        _grep_file(base)
    else:
        for root, _, files in os.walk(base, topdown=True):
            for fn in sorted(files):
                _grep_file(Path(root) / fn)
                if len(matches) >= lim or files_seen > _MAX_GREP_FILES:
                    break
            if len(matches) >= lim or files_seen > _MAX_GREP_FILES:
                break
    return {
        "ok": True,
        "operation": "grep",
        "base": str(base),
        "pattern": needle,
        "matches": matches,
        "files_scanned": files_seen,
        "truncated": len(matches) >= lim,
    }


def perico_apply_patch(
    *,
    relative_path: str,
    old_text: str,
    new_text: str = "",
) -> dict[str, Any]:
    """
    Single-file single-occurrence replace. old_text must match exactly once.
    Guarded by PERICO_WRITE_ENABLED=1.
    """
    if (os.getenv("PERICO_WRITE_ENABLED") or "").strip().lower() not in ("1", "true", "yes", "on"):
        return {
            "ok": False,
            "error": "writes_disabled",
            "message": "Set PERICO_WRITE_ENABLED=1 to allow perico_apply_patch (dev/lab only).",
        }
    if not (relative_path or "").strip():
        return {"ok": False, "error": "missing_relative_path"}
    old = old_text or ""
    if not old.strip():
        return {"ok": False, "error": "missing_old_text"}
    try:
        path = _safe_child(relative_path)
    except Exception as e:
        return {"ok": False, "error": "path_not_allowed", "detail": str(e)}
    if not path.is_file():
        return {"ok": False, "error": "not_a_file", "path": str(path)}
    try:
        before = path.read_text(encoding="utf-8", errors="strict")
    except UnicodeDecodeError:
        return {"ok": False, "error": "not_utf8_text", "path": str(path)}
    except OSError as e:
        return {"ok": False, "error": "read_failed", "detail": str(e)}
    count = before.count(old)
    if count == 0:
        return {"ok": False, "error": "old_text_not_found", "path": str(path)}
    if count > 1:
        return {"ok": False, "error": "old_text_not_unique", "occurrences": count, "path": str(path)}
    after = before.replace(old, new_text, 1)
    try:
        path.write_text(after, encoding="utf-8", newline="\n")
    except OSError as e:
        return {"ok": False, "error": "write_failed", "detail": str(e)}
    return {
        "ok": True,
        "path": str(path),
        "relative_path": relative_path.strip(),
        "diff_preview": f"--- before (trunc)\n{before[:800]}\n+++ after (trunc)\n{after[:800]}",
        "bytes_written": len(after.encode("utf-8")),
    }


def perico_run_pytest(
    *,
    relative_path: str = "",
    extra_args: str = "",
    timeout_seconds: int = 180,
) -> dict[str, Any]:
    """
    Run ``python3 -m pytest`` with cwd = repo backend/ (or repo root if backend missing).
    """
    root = perico_repo_root()
    backend = root / "backend"
    cwd = backend if backend.is_dir() else root
    timeout = max(15, min(int(timeout_seconds or 180), 900))
    cmd = [os.environ.get("PERICO_PYTHON", "python3"), "-m", "pytest", "-q", "--tb=no"]
    tail = (relative_path or "").strip()
    if tail:
        try:
            _safe_child(tail)  # ensure path stays in repo
        except Exception as e:
            return {"ok": False, "error": "path_not_allowed", "detail": str(e)}
        cmd.append(tail)
    extra = (extra_args or "").strip()
    if extra:
        cmd.extend(extra.split())
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": "timeout",
            "timeout_seconds": timeout,
            "cmd": cmd,
            "cwd": str(cwd),
        }
    except Exception as e:
        return {"ok": False, "error": "spawn_failed", "detail": str(e)}
    out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    passed = proc.returncode == 0
    return {
        "ok": True,
        "pytest": True,
        "tests_ok": passed,
        "exit_code": proc.returncode,
        "stdout_tail": (proc.stdout or "")[-8000:],
        "stderr_tail": (proc.stderr or "")[-8000:],
        "combined_tail": out[-12_000:],
        "cwd": str(cwd),
        "cmd": cmd,
    }
