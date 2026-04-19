"""Operational diagnostics/fix helpers for Jarvis Ops agent."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


def _safe_error(message: str, *, command: list[str] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "success": False,
        "error": message,
    }
    if command is not None:
        payload["command"] = list(command)
    return payload


def run_command(args: list[str], timeout: int = 20) -> dict[str, Any]:
    """Run a subprocess command with explicit args and timeout."""
    if not isinstance(args, list) or not args or not all(isinstance(x, str) and x for x in args):
        return _safe_error("Invalid command args; expected non-empty list[str].")
    timeout_s = max(1, int(timeout or 20))
    try:
        completed = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        return {
            "success": completed.returncode == 0,
            "returncode": int(completed.returncode),
            "stdout": (completed.stdout or "").strip(),
            "stderr": (completed.stderr or "").strip(),
            "command": list(args),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "success": False,
            "returncode": -1,
            "stdout": (exc.stdout or "").strip() if isinstance(exc.stdout, str) else "",
            "stderr": f"Command timed out after {timeout_s}s.",
            "command": list(args),
        }
    except Exception as exc:
        return {
            "success": False,
            "returncode": -1,
            "stdout": "",
            "stderr": f"Command failed: {type(exc).__name__}: {exc}",
            "command": list(args),
        }


def inspect_container_env(container_name: str, env_prefixes: list[str] | None = None) -> dict[str, Any]:
    """Read environment variables from inside a running container."""
    target = str(container_name or "").strip()
    if not target:
        return _safe_error("container_name is required.")
    result = run_command(["docker", "exec", target, "env"], timeout=20)
    entries: dict[str, str] = {}
    if result.get("success"):
        for raw in str(result.get("stdout") or "").splitlines():
            if "=" not in raw:
                continue
            key, value = raw.split("=", 1)
            entries[key.strip()] = value
    prefixes = [str(x) for x in (env_prefixes or []) if isinstance(x, str) and x.strip()]
    if prefixes:
        filtered = {
            key: value
            for key, value in entries.items()
            if any(key.startswith(prefix) for prefix in prefixes)
        }
    else:
        filtered = entries
    return {
        **result,
        "container_name": target,
        "env": filtered,
        "count": len(filtered),
    }


def inspect_container_mounts(container_name: str) -> dict[str, Any]:
    """Inspect container mounts and return parsed host/container paths."""
    target = str(container_name or "").strip()
    if not target:
        return _safe_error("container_name is required.")
    cmd = ["docker", "inspect", target, "--format", "{{json .Mounts}}"]
    result = run_command(cmd, timeout=20)
    mounts: list[dict[str, Any]] = []
    if result.get("success"):
        import json

        try:
            parsed = json.loads(str(result.get("stdout") or "[]"))
            if isinstance(parsed, list):
                for row in parsed:
                    if not isinstance(row, dict):
                        continue
                    mounts.append(
                        {
                            "type": str(row.get("Type") or row.get("type") or ""),
                            "source": str(row.get("Source") or row.get("source") or ""),
                            "destination": str(row.get("Destination") or row.get("destination") or ""),
                            "mode": str(row.get("Mode") or row.get("mode") or ""),
                            "rw": bool(row.get("RW")) if "RW" in row else bool(row.get("rw", False)),
                        }
                    )
        except Exception as exc:
            return {
                **result,
                "success": False,
                "error": f"Failed parsing docker inspect mounts: {type(exc).__name__}: {exc}",
                "mounts": [],
                "container_name": target,
            }
    return {
        **result,
        "container_name": target,
        "mounts": mounts,
        "count": len(mounts),
    }


def check_path_in_container(container_name: str, path: str) -> dict[str, Any]:
    """Check path existence inside container using test command."""
    target = str(container_name or "").strip()
    target_path = str(path or "").strip()
    if not target or not target_path:
        return _safe_error("container_name and path are required.")
    result = run_command(["docker", "exec", target, "test", "-e", target_path], timeout=10)
    exists = bool(result.get("success") and int(result.get("returncode", 1) or 1) == 0)
    return {
        **result,
        "container_name": target,
        "path": target_path,
        "exists": exists,
    }


def check_path_on_host(path: str) -> dict[str, Any]:
    """Check file/directory existence on host filesystem."""
    target = str(path or "").strip()
    if not target:
        return _safe_error("path is required.")
    p = Path(target)
    try:
        exists = p.exists()
        return {
            "success": True,
            "path": target,
            "exists": exists,
            "is_file": p.is_file() if exists else False,
            "is_dir": p.is_dir() if exists else False,
        }
    except Exception as exc:
        return _safe_error(f"Host path check failed: {type(exc).__name__}: {exc}")


def restart_backend_service(project_path: str, service_name: str = "backend-aws") -> dict[str, Any]:
    """Restart backend service with explicit docker compose profile."""
    root = str(project_path or "").strip()
    svc = str(service_name or "backend-aws").strip() or "backend-aws"
    if not root:
        return _safe_error("project_path is required.")
    cmd = ["docker", "compose", "--project-directory", root, "--profile", "aws", "restart", svc]
    result = run_command(cmd, timeout=45)
    return {
        **result,
        "project_path": root,
        "service_name": svc,
        "critical_action": True,
    }


def read_runtime_env_file(path: str) -> dict[str, Any]:
    """Best-effort parser for KEY=VALUE lines from runtime env files."""
    target = str(path or "").strip()
    if not target:
        return _safe_error("path is required.")
    p = Path(target)
    try:
        if not p.exists():
            return {
                "success": False,
                "path": target,
                "exists": False,
                "values": {},
                "error": "runtime env file not found",
            }
        values: dict[str, str] = {}
        for raw in p.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
        return {
            "success": True,
            "path": target,
            "exists": True,
            "values": values,
            "count": len(values),
        }
    except Exception as exc:
        return _safe_error(f"Failed to read runtime env file: {type(exc).__name__}: {exc}")


def upsert_runtime_env_value(path: str, key: str, value: str) -> dict[str, Any]:
    """Update or append KEY=VALUE entry in runtime env file."""
    target = str(path or "").strip()
    env_key = str(key or "").strip()
    if not target or not env_key:
        return _safe_error("path and key are required.")
    p = Path(target)
    try:
        lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
        updated = False
        out_lines: list[str] = []
        for raw in lines:
            if raw.strip().startswith(f"{env_key}="):
                out_lines.append(f"{env_key}={value}")
                updated = True
            else:
                out_lines.append(raw)
        if not updated:
            out_lines.append(f"{env_key}={value}")
        p.write_text("\n".join(out_lines).rstrip() + "\n", encoding="utf-8")
        return {
            "success": True,
            "path": target,
            "key": env_key,
            "updated": updated,
            "critical_action": True,
        }
    except Exception as exc:
        return _safe_error(f"Failed to upsert runtime env value: {type(exc).__name__}: {exc}")


def copy_file_host_to_host(source_path: str, target_path: str) -> dict[str, Any]:
    """Copy a host file to another host path (credentials staging)."""
    src = str(source_path or "").strip()
    dst = str(target_path or "").strip()
    if not src or not dst:
        return _safe_error("source_path and target_path are required.")
    source = Path(src)
    target = Path(dst)
    try:
        if not source.exists() or not source.is_file():
            return {
                "success": False,
                "error": "Source file not found",
                "source_path": src,
                "target_path": dst,
            }
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return {
            "success": True,
            "source_path": src,
            "target_path": dst,
            "bytes": os.path.getsize(dst),
            "critical_action": True,
        }
    except Exception as exc:
        return _safe_error(f"Failed to copy file: {type(exc).__name__}: {exc}")
