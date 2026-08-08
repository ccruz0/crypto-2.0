"""Read-only container inspection tool."""

from __future__ import annotations

import re
import subprocess
from datetime import datetime, timezone
from typing import Any

_UNHEALTHY_STATUS = re.compile(r"unhealthy|restarting|exited|dead|oom|created\b", re.IGNORECASE)
_HEALTHY_STATUS = re.compile(r"\(healthy\)|\bhealthy\b|up\s+\d", re.IGNORECASE)


def inspect_container(*, service: str = "", **_kwargs: Any) -> dict[str, Any]:
    """List running containers (optionally filtered by name substring).

    Default ``service=""`` returns the full docker ps list so deployment
    investigations see all stack services, not only frontend-aws.
    """
    containers: list[dict[str, Any]] = []
    try:
        proc = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.Names}}|{{.Status}}|{{.Image}}"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        for line in (proc.stdout or "").splitlines():
            parts = line.split("|", 2)
            if len(parts) != 3:
                continue
            name, status, image = parts
            if service and service not in name:
                continue
            containers.append({"name": name, "status": status, "image": image})
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "tool": "inspect_container",
            "service_filter": service or None,
            "containers": [],
            "count": 0,
            "unhealthy_count": 0,
            "healthy_count": 0,
            "read_only": True,
            "error": str(exc),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    unhealthy = [c for c in containers if _UNHEALTHY_STATUS.search(c.get("status") or "")]
    unhealthy_names = {c["name"] for c in unhealthy}
    healthy = [
        c
        for c in containers
        if c["name"] not in unhealthy_names and _HEALTHY_STATUS.search(c.get("status") or "")
    ]

    return {
        "tool": "inspect_container",
        "service_filter": service or None,
        "containers": containers,
        "count": len(containers),
        "unhealthy_count": len(unhealthy),
        "healthy_count": len(healthy),
        "unhealthy_names": [c["name"] for c in unhealthy[:10]],
        "read_only": True,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
