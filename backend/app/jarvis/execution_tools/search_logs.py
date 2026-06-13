"""Read-only log search for Jarvis diagnostics."""

from __future__ import annotations

import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services._paths import workspace_root

_DEFAULT_TAIL = 300
_MAX_MATCHES = 50
_SECRET_PATTERN = re.compile(
    r"(api[_-]?key|api[_-]?secret|password|token|secret|authorization)\s*[:=]\s*\S+",
    re.IGNORECASE,
)

_DEFAULT_KEYWORDS = ("orders", "open orders", "position", "trade", "error", "Crypto.com")

_LOG_SERVICES = ("backend-aws", "frontend-aws", "market-updater-aws")


def _redact_secrets(text: str) -> str:
    return _SECRET_PATTERN.sub(r"\1=***REDACTED***", text)


def _parse_log_line(line: str, *, default_source: str) -> dict[str, str]:
    ts = ""
    source = default_source
    message = line
    # docker compose prefix: service-name  | timestamp message
    if "|" in line:
        parts = line.split("|", 1)
        left = parts[0].strip()
        if left:
            source = left.split()[0] if left.split() else default_source
        message = parts[1].strip() if len(parts) > 1 else line
    iso_match = re.search(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}", message)
    if iso_match:
        ts = iso_match.group(0)
    return {
        "timestamp": ts,
        "source": source,
        "message": _redact_secrets(message[:500]),
    }


def _fetch_docker_logs(service: str, *, tail: int) -> list[str]:
    repo = workspace_root()
    try:
        proc = subprocess.run(
            ["docker", "compose", "--profile", "aws", "logs", "--tail", str(tail), service],
            capture_output=True,
            text=True,
            timeout=25,
            cwd=str(repo),
            check=False,
        )
        if proc.returncode == 0 or proc.stdout:
            return [ln for ln in proc.stdout.splitlines() if ln.strip()]
    except (OSError, subprocess.TimeoutExpired):
        pass
    return []


def _fetch_local_log_files(*, tail: int) -> list[tuple[str, str]]:
    repo = workspace_root()
    candidates = [
        repo / "logs",
        repo / "backend" / "logs",
        Path("/var/log"),
    ]
    lines: list[tuple[str, str]] = []
    for base in candidates:
        if not base.is_dir():
            continue
        for path in sorted(base.glob("*.log"))[:5]:
            try:
                content = path.read_text(encoding="utf-8", errors="ignore").splitlines()
                for ln in content[-tail:]:
                    lines.append((path.name, ln))
            except OSError:
                continue
    return lines


def _keywords_from_input(keyword: str | None, objective: str | None) -> list[str]:
    if keyword:
        return [keyword]
    if objective:
        obj_l = objective.lower()
        picked: list[str] = []
        for kw in _DEFAULT_KEYWORDS:
            if kw.lower() in obj_l:
                picked.append(kw)
        if picked:
            return picked
    return list(_DEFAULT_KEYWORDS)


def search_logs(
    *,
    keyword: str | None = None,
    keywords: list[str] | None = None,
    service: str | None = None,
    tail: int = _DEFAULT_TAIL,
    max_matches: int = _MAX_MATCHES,
    objective: str | None = None,
    action: str | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Search recent backend/container logs for diagnostic keywords."""
    limit = max(1, min(int(tail or _DEFAULT_TAIL), 1000))
    cap = max(1, min(int(max_matches or _MAX_MATCHES), 100))
    search_terms = keywords or _keywords_from_input(keyword, objective)
    patterns = [re.compile(re.escape(k), re.IGNORECASE) for k in search_terms if k]

    raw_lines: list[tuple[str, str]] = []
    services = [service] if service else list(_LOG_SERVICES)
    for svc in services:
        for ln in _fetch_docker_logs(svc, tail=limit):
            raw_lines.append((svc, ln))
    if not raw_lines:
        for src, ln in _fetch_local_log_files(tail=limit):
            raw_lines.append((src, ln))

    matches: list[dict[str, str]] = []
    for src, ln in raw_lines:
        if patterns and not any(p.search(ln) for p in patterns):
            continue
        entry = _parse_log_line(ln, default_source=src)
        matches.append(entry)
        if len(matches) >= cap:
            break

    return {
        "tool": "search_logs",
        "keywords": search_terms,
        "services_searched": services,
        "match_count": len(matches),
        "matches": matches,
        "capped_at": cap,
        "read_only": True,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
