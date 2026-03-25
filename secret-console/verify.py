"""
Compare secret values: local encrypted store vs AWS Parameter Store vs Docker.

Uses mappings.SECRET_TARGETS for explicit verify_env_vars when defined; otherwise
falls back to a single inferred env key. Docker target: SECRET_CONSOLE_VERIFY_CONTAINER
or container= kwarg.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from typing import Any

import aws_sync
import mappings

log = logging.getLogger(__name__)

CONTAINER_ENV = "SECRET_CONSOLE_VERIFY_CONTAINER"


def _name_to_env_key(secret_name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", secret_name.replace(".", "_")).upper()


def _docker_env_value(container: str, env_key: str) -> str | None:
    try:
        out = subprocess.run(
            ["docker", "exec", container, "env"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if out.returncode != 0:
            log.error("docker exec env failed: %s", out.stderr.strip())
            return None
        prefix = f"{env_key}="
        for line in out.stdout.splitlines():
            if line.startswith(prefix):
                return line[len(prefix) :]
        return None
    except FileNotFoundError:
        log.warning("docker CLI not found")
        return None
    except subprocess.TimeoutExpired:
        log.error("docker exec timed out")
        return None


def _runtime_keys_for_secret(secret_name: str, environment: str) -> list[str]:
    spec = mappings.get_deploy_target(secret_name, environment)
    if spec and spec.get("verify_env_vars"):
        return list(spec["verify_env_vars"])
    return [_name_to_env_key(secret_name)]


def _aggregate_runtime_detail(checks: list[dict[str, Any]]) -> str:
    if not checks:
        return "SKIP"
    details = [c["detail"] for c in checks]
    if any(d == "MISSING" for d in details):
        return "MISSING"
    if any(d == "MISMATCH" for d in details):
        return "MISMATCH"
    if all(d == "OK" for d in details):
        return "OK"
    return "MISMATCH"


def verify_secret(
    local_value: str,
    environment: str,
    secret_name: str,
    *,
    container: str | None = None,
    env_key_override: str | None = None,
) -> dict[str, Any]:
    """
    Overall status: OK | MISMATCH | MISSING.

    - MISSING: AWS parameter not found, or Docker verification requested but
      a required mapped env var is missing in the container.
    - MISMATCH: values differ among available sources.
    - OK: local matches AWS; if Docker is in play, every checked var matches too.
    """
    ctr = (container or os.environ.get(CONTAINER_ENV, "")).strip()

    if env_key_override:
        runtime_keys = [env_key_override]
    else:
        runtime_keys = _runtime_keys_for_secret(secret_name, environment)

    aws_val: str | None = None
    aws_detail = "MISSING"
    try:
        aws_val = aws_sync.get_secret(environment, secret_name)
        aws_detail = "OK"
    except KeyError:
        log.info("verify: AWS parameter missing for %s/%s", environment, secret_name)
    except Exception as e:
        log.error("verify: AWS error: %s", e)
        aws_detail = f"ERROR: {e}"

    runtime_checks: list[dict[str, Any]] = []
    runtime_val: str | None = None
    if ctr:
        for rk in runtime_keys:
            v = _docker_env_value(ctr, rk)
            if v is None:
                detail = "MISSING"
            elif aws_detail == "OK" and aws_val is not None and v != aws_val:
                detail = "MISMATCH"
            elif v != local_value:
                detail = "MISMATCH"
            else:
                detail = "OK"
            runtime_checks.append(
                {
                    "var": rk,
                    "detail": detail,
                    "preview": preview_secret_value(v),
                }
            )
        if runtime_checks:
            runtime_val = _docker_env_value(ctr, runtime_keys[0])
    else:
        runtime_checks = []

    runtime_detail = _aggregate_runtime_detail(runtime_checks) if ctr else "SKIP"

    if aws_detail != "OK" or aws_val is None:
        overall = "MISSING" if aws_detail == "MISSING" else "MISMATCH"
    elif aws_val != local_value:
        overall = "MISMATCH"
    elif ctr:
        if runtime_detail == "MISSING":
            overall = "MISSING"
        elif runtime_detail == "MISMATCH":
            overall = "MISMATCH"
        else:
            overall = "OK"
    else:
        overall = "OK"

    log.info(
        "verify secret=%s env=%s overall=%s aws=%s runtime=%s",
        secret_name,
        environment,
        overall,
        aws_detail,
        runtime_detail,
    )

    env_key_checked = ", ".join(runtime_keys)

    return {
        "status": overall,
        "secret_name": secret_name,
        "environment": environment,
        "env_key_checked": env_key_checked,
        "runtime_checks": runtime_checks,
        "container": ctr or None,
        "local_preview": preview_secret_value(local_value),
        "aws_preview": preview_secret_value(aws_val) if aws_val is not None else None,
        "runtime_preview": preview_secret_value(runtime_val) if runtime_val is not None else None,
        "aws_detail": aws_detail,
        "runtime_detail": runtime_detail,
    }


def preview_secret_value(s: str | None, n: int = 4) -> str | None:
    if s is None:
        return None
    if len(s) <= 2 * n:
        return "***"
    return f"{s[:n]}…{s[-n:]}"
