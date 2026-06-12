"""Read-only container inspection tool."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from typing import Any


def inspect_container(*, service: str = "frontend-aws") -> dict[str, Any]:
    containers: list[dict[str, Any]] = []
    try:
        proc = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}|{{.Status}}|{{.Image}}"],
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
            "service_filter": service,
            "containers": [],
            "read_only": True,
            "error": str(exc),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    return {
        "tool": "inspect_container",
        "service_filter": service,
        "containers": containers,
        "count": len(containers),
        "read_only": True,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
