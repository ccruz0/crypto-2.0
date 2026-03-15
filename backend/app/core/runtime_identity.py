"""
Runtime identity diagnostics for /investigate and agent commands.

Returns service name, hostname, Python path, cwd without importing pydantic or app config.
Use this to trace which container/runtime executes a command when runtime-check passes
but /investigate fails (e.g. OpenClaw vs backend-aws).
"""
from __future__ import annotations

import os
import socket
import sys
from typing import Any


def get_runtime_identity() -> dict[str, Any]:
    """
    Return runtime identity without importing pydantic or app config.
    Safe to call from any execution context (backend-aws, OpenClaw, scripts).
    """
    try:
        hostname = socket.gethostname()
    except Exception:
        hostname = "unknown"

    try:
        cwd = os.getcwd()
    except Exception:
        cwd = "unknown"

    # Service name: from env or infer from hostname/cwd
    service = (os.environ.get("SERVICE_NAME") or os.environ.get("COMPOSE_SERVICE") or "").strip()
    if not service:
        if "openclaw" in hostname.lower() or "/openclaw" in cwd.lower():
            service = "openclaw"
        elif "backend" in hostname.lower() or "/app" in cwd:
            service = "backend"
        else:
            service = "unknown"

    return {
        "service": service or "unknown",
        "hostname": hostname,
        "container_id": _container_id(),
        "python_executable": sys.executable,
        "cwd": cwd,
        "runtime_origin": (os.environ.get("RUNTIME_ORIGIN") or "").strip() or "not_set",
    }


def _container_id() -> str:
    """Read container ID from cgroup if in Docker/Kubernetes."""
    try:
        with open("/proc/self/cgroup", "r") as f:
            for line in f:
                if "docker" in line or "kubepods" in line:
                    parts = line.strip().split("/")
                    if parts:
                        return parts[-1][:12]  # Short ID
    except Exception:
        pass
    return ""


def format_runtime_identity_short(identity: dict[str, Any] | None = None) -> str:
    """One-line summary for logs or Telegram preamble."""
    if identity is None:
        identity = get_runtime_identity()
    parts = [
        f"service={identity.get('service', '?')}",
        f"host={identity.get('hostname', '?')}",
        f"python={identity.get('python_executable', '?')}",
        f"cwd={identity.get('cwd', '?')}",
    ]
    if identity.get("container_id"):
        parts.insert(1, f"container={identity['container_id']}")
    if identity.get("runtime_origin") and identity["runtime_origin"] != "not_set":
        parts.append(f"origin={identity['runtime_origin']}")
    return " | ".join(parts)
