"""
AI Engine tools: repo search, read snippet, tail logs. Allowlists only; no arbitrary file/shell.
"""
import os
import subprocess
from pathlib import Path
from typing import Any

# Subdirs we are allowed to search (under backend root). No arbitrary paths.
SEARCH_SUBDIRS = ("app", "scripts", "docs")

# Services allowed for tail_logs (read-only). No arbitrary service names.
ALLOWED_LOG_SERVICES = frozenset(
    {"backend-aws", "db", "frontend-aws", "market-updater-aws"}
)

# Max snippet lines per file to avoid large reads.
MAX_SNIPPET_LINES = 500


def _allowed_search_roots() -> list[Path]:
    """Return list of allowed directory roots that exist (container /app or cwd-relative)."""
    roots: list[Path] = []
    for base in (Path("/app"), Path.cwd()):
        for sub in SEARCH_SUBDIRS:
            d = base / sub
            if d.is_dir():
                roots.append(d.resolve())
    # Deduplicate (e.g. /app/app and cwd/app might resolve to same)
    seen = set()
    out = []
    for r in roots:
        key = str(r)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def _path_allowed(path: str | Path) -> bool:
    """True if path is under one of the allowed search roots."""
    try:
        resolved = Path(path).resolve()
    except Exception:
        return False
    for root in _allowed_search_roots():
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def search_repo(query: str, max_results: int = 50) -> list[dict[str, Any]]:
    """
    Search allowed repo dirs for keyword(s). Uses rg if available, else grep -R.
    Returns list of {"path": str, "line_number": int, "line": str}.
    """
    if not query or not query.strip():
        return []
    roots = _allowed_search_roots()
    if not roots:
        return []
    results: list[dict[str, Any]] = []
    # Use ripgrep first (safer, no shell)
    for root in roots:
        if len(results) >= max_results:
            break
        try:
            out = subprocess.run(
                ["rg", "-n", "--no-heading", "-e", query.strip(), str(root)],
                capture_output=True,
                text=True,
                timeout=30,
                env={**os.environ, "PATH": os.environ.get("PATH", "")},
            )
        except FileNotFoundError:
            out = None
        if out is None or out.returncode not in (0, 1):
            try:
                out = subprocess.run(
                    [
                        "grep",
                        "-Rn",
                        "--include=*.py",
                        "--include=*.md",
                        "--include=*.yml",
                        "--include=*.yaml",
                        "-e",
                        query.strip(),
                        str(root),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            except FileNotFoundError:
                break
            if out.returncode not in (0, 1):
                break
        if out and out.stdout:
            for line in out.stdout.splitlines():
                if len(results) >= max_results:
                    break
                # rg: path:line_num:content   grep: path:line_num:content
                parts = line.split(":", 2)
                if len(parts) >= 3:
                    try:
                        results.append({
                            "path": parts[0],
                            "line_number": int(parts[1]),
                            "line": parts[2].strip(),
                        })
                    except ValueError:
                        continue
    return results[:max_results]


def read_snippet(
    path: str,
    line_start: int | None = None,
    line_end: int | None = None,
    max_lines: int = 200,
) -> dict[str, Any]:
    """
    Read a small snippet from a file under allowed roots. Path can be absolute or relative.
    Returns {"path": str, "line_start": int, "line_end": int, "lines": list[str]} or {"error": str}.
    """
    if not _path_allowed(path):
        return {"error": "path not under allowed roots"}
    try:
        p = Path(path).resolve()
        if not p.is_file():
            return {"error": "not a file"}
        raw = p.read_text(encoding="utf-8", errors="replace")
        all_lines = raw.splitlines()
    except Exception as e:
        return {"error": str(e)}
    total = len(all_lines)
    if max_lines <= 0 or max_lines > MAX_SNIPPET_LINES:
        max_lines = MAX_SNIPPET_LINES
    start = (line_start or 1) - 1 if line_start else 0
    end = line_end if line_end is not None else min(start + max_lines, total)
    start = max(0, min(start, total))
    end = max(start, min(end, start + max_lines, total))
    snippet = all_lines[start:end]
    return {
        "path": str(p),
        "line_start": start + 1,
        "line_end": end,
        "total_lines": total,
        "lines": snippet,
    }


def tail_logs(service: str, lines: int = 100) -> dict[str, Any]:
    """
    Tail docker compose logs for an allowed service (read-only). Returns {"service": str, "output": str} or {"error": str}.
    """
    if service not in ALLOWED_LOG_SERVICES:
        return {"error": f"service not allowed (allowlist: {sorted(ALLOWED_LOG_SERVICES)})"}
    if lines <= 0 or lines > 2000:
        lines = 500
    try:
        # Assume we're in repo root or backend; try parent for repo root
        for cwd in (Path.cwd(), Path.cwd().parent):
            compose = cwd / "docker-compose.yml"
            if compose.is_file():
                out = subprocess.run(
                    ["docker", "compose", "logs", "--tail", str(lines), service],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    cwd=str(cwd),
                )
                return {
                    "service": service,
                    "output": (out.stdout or "") + (out.stderr or ""),
                    "returncode": out.returncode,
                    "tail_logs_source": "docker_compose",
                    "compose_dir_used": str(cwd.resolve()),
                }
        return {"error": "docker-compose.yml not found"}
    except FileNotFoundError:
        return {"error": "docker not available"}
    except subprocess.TimeoutExpired:
        return {"error": "docker compose logs timed out"}
    except Exception as e:
        return {"error": str(e)}
